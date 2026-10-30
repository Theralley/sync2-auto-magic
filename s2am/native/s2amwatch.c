/*
 * s2am watch: records what is on SYNC 2's screen and which programs run, for diagnosis.
 * Usage: s2amwatch.exe <seconds> <output folder>
 *
 * Every 500 ms it looks at the processes (toolhelp), the top-level windows in Z order,
 * the foreground window, SYNC's own DESKTOP window, whether AutoKit's front window
 * still answers messages, and the driver list (USB devices). It writes only what
 * changed, to <folder>\watch.log, and a heartbeat every 10 s so the log shows when
 * it stopped. It copies the runner guard's log and AutoKit's own log into the folder
 * whenever they change. It changes nothing on the car and exits after <seconds>.
 *
 * It never asks another program for its window title: that is a message, and a hung
 * program would hang the watcher too. The answer check runs in a thread of its own.
 *
 * Line format: <hh:mm:ss.mmm>|<event>|<details>
 * Only COREDLL is imported; toolhelp.dll is loaded at run time.
 */
#include <windows.h>

#define TICK_MS 500
#define HEARTBEAT_MS 10000
#define PROBE_EVERY_MS 2000
#define PROBE_WAIT_MS 1000
#define LOG_LIMIT (2 * 1024 * 1024)
#define MAX_PROCS 160
#define MAX_WINDOWS 128
#define APP_NAME L"AutoKit.exe"
#define TH32CS_SNAPPROCESS 0x00000002
#define TH32CS_SNAPNOHEAPS 0x40000000

typedef struct {
    DWORD dwSize, cntUsage, th32ProcessID, th32DefaultHeapID, th32ModuleID, cntThreads;
    DWORD th32ParentProcessID;
    LONG pcPriClassBase;
    DWORD dwFlags;
    WCHAR szExeFile[MAX_PATH];
    DWORD th32MemoryBase, th32AccessKey;
} ProcessEntry;

typedef HANDLE (WINAPI *SnapshotFn)(DWORD, DWORD);
typedef BOOL (WINAPI *ProcessFn)(HANDLE, ProcessEntry *);
typedef BOOL (WINAPI *CloseSnapshotFn)(HANDLE);

typedef struct {
    DWORD pid, threads;
    WCHAR exe[32];
} Proc;

typedef struct {
    HWND hwnd;
    DWORD pid;
    BOOL visible;
    RECT rect;
    DWORD exstyle;
    WCHAR cls[40];
} Win;

/* Files copied into the output folder whenever they change: {car path, copy name}. */
static const WCHAR *copies[][2] = {
    {L"\\SyncExtendedPack\\_s2am\\guard.log", L"guard-live.log"},
    {L"\\SyncExtendedPack\\Apps\\Media\\AutoKit\\hwlog.log", L"autokit-hwlog-live.log"},
    {L"\\SyncExtendedPack\\Apps\\Media\\AutoKit\\hwlog.txt", L"autokit-hwlog-live.txt"},
    {L"\\Temp\\NAV_SHOW.TXT", L"nav-show-live.txt"},
};
#define COPY_COUNT (sizeof(copies) / sizeof(copies[0]))

static SnapshotFn snapshot;
static ProcessFn first_process, next_process;
static CloseSnapshotFn close_snapshot;

static WCHAR folder[MAX_PATH], log_path[MAX_PATH];
static char buffer[16384];
static int used;
static BOOL full, skipping;
static int write_failures;

static Proc procs[MAX_PROCS], fresh[MAX_PROCS];
static int proc_count, fresh_count;
static Win windows[MAX_WINDOWS];
static int window_count;
static DWORD copied_size[COPY_COUNT], copied_time[COPY_COUNT];

static HANDLE probe_thread;
static DWORD probe_started;

/* ---- writing ------------------------------------------------------------------------ */

static void put(const char *text)
{
    if (skipping)
        return;
    while (*text && used < (int)sizeof(buffer) - 1)
        buffer[used++] = *text++;
}

static void put_uint(unsigned long value)
{
    char digits[12];
    int i = 11;
    digits[i] = '\0';
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0 && i > 0);
    put(digits + i);
}

static void put_int(long value)
{
    if (value < 0) {
        put("-");
        put_uint((unsigned long)-value);
    } else {
        put_uint((unsigned long)value);
    }
}

static void put_hex(unsigned long value)
{
    static const char hex[] = "0123456789abcdef";
    char digits[9];
    int i;
    for (i = 7; i >= 0; i--) {
        digits[i] = hex[value & 15];
        value >>= 4;
    }
    digits[8] = '\0';
    put(digits);
}

static void put_wide(const WCHAR *text, int limit)
{
    char one[2] = {0, 0};
    while (*text && limit-- > 0) {
        one[0] = (*text < 127 && *text >= 32 && *text != '|') ? (char)*text : '?';
        put(one);
        text++;
    }
}

/* Starts a line with the wall-clock time and the event name. Once the log is full, only
 * the heartbeat is still written. */
static void begin(const char *event)
{
    SYSTEMTIME now;
    skipping = full && strncmp(event, "tick|", 5) != 0 && strcmp(event, "end") != 0;
    GetLocalTime(&now);
    if (now.wHour < 10)
        put("0");
    put_uint(now.wHour);
    put(":");
    if (now.wMinute < 10)
        put("0");
    put_uint(now.wMinute);
    put(":");
    if (now.wSecond < 10)
        put("0");
    put_uint(now.wSecond);
    put(".");
    if (now.wMilliseconds < 100)
        put("0");
    if (now.wMilliseconds < 10)
        put("0");
    put_uint(now.wMilliseconds);
    put("|");
    put(event);
}

static void end_line(void)
{
    put("\r\n");
    skipping = FALSE;
}

/* Appends what was collected this tick; the file is closed and flushed every time, so a
 * power cut loses at most one tick. */
static void flush(void)
{
    DWORD written;
    HANDLE file;
    if (used == 0)
        return;
    file = CreateFileW(log_path, GENERIC_WRITE, FILE_SHARE_READ, NULL, OPEN_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        write_failures++;
        used = 0;
        return;
    }
    write_failures = 0;
    if (!full && GetFileSize(file, NULL) > LOG_LIMIT) {
        full = TRUE;
        used = 0;
        put("log full, only the heartbeat from here\r\n");  /* this tick's lines are dropped */
    }
    SetFilePointer(file, 0, NULL, FILE_END);
    WriteFile(file, buffer, (DWORD)used, &written, NULL);
    FlushFileBuffers(file);
    CloseHandle(file);
    used = 0;
}

/* ---- processes ---------------------------------------------------------------------- */

static BOOL load_toolhelp(void)
{
    HMODULE toolhelp = LoadLibraryW(L"toolhelp.dll");
    if (!toolhelp)
        return FALSE;
    /* via void (*)(void): GCC's sanctioned way to cast between function types */
    snapshot = (SnapshotFn)(void (*)(void))GetProcAddressW(toolhelp, L"CreateToolhelp32Snapshot");
    first_process = (ProcessFn)(void (*)(void))GetProcAddressW(toolhelp, L"Process32First");
    next_process = (ProcessFn)(void (*)(void))GetProcAddressW(toolhelp, L"Process32Next");
    close_snapshot = (CloseSnapshotFn)(void (*)(void))GetProcAddressW(toolhelp,
                                                                     L"CloseToolhelp32Snapshot");
    return snapshot && first_process && next_process && close_snapshot;
}

static void list_processes(void)
{
    ProcessEntry entry;
    HANDLE list = snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPNOHEAPS, 0);
    fresh_count = 0;
    if (list == INVALID_HANDLE_VALUE)
        return;
    entry.dwSize = sizeof(entry);
    if (first_process(list, &entry)) {
        do {
            if (fresh_count < MAX_PROCS) {
                fresh[fresh_count].pid = entry.th32ProcessID;
                fresh[fresh_count].threads = entry.cntThreads;
                wcsncpy(fresh[fresh_count].exe, entry.szExeFile, 31);
                fresh[fresh_count].exe[31] = L'\0';
                fresh_count++;
            }
            entry.dwSize = sizeof(entry);
        } while (next_process(list, &entry));
    }
    close_snapshot(list);
}

static int find_pid(const Proc *list, int count, DWORD pid)
{
    int i;
    for (i = 0; i < count; i++)
        if (list[i].pid == pid)
            return i;
    return -1;
}

static void diff_processes(void)
{
    int i;
    for (i = 0; i < fresh_count; i++)
        if (find_pid(procs, proc_count, fresh[i].pid) < 0) {
            begin("proc+|");
            put_uint(fresh[i].pid);
            put("|");
            put_wide(fresh[i].exe, 31);
            put("|threads ");
            put_uint(fresh[i].threads);
            end_line();
        }
    for (i = 0; i < proc_count; i++)
        if (find_pid(fresh, fresh_count, procs[i].pid) < 0) {
            begin("proc-|");
            put_uint(procs[i].pid);
            put("|");
            put_wide(procs[i].exe, 31);
            end_line();
        }
    memcpy(procs, fresh, sizeof(Proc) * fresh_count);
    proc_count = fresh_count;
}

static const WCHAR *exe_of(DWORD pid)
{
    int i = find_pid(procs, proc_count, pid);
    return i < 0 ? L"?" : procs[i].exe;
}

static DWORD app_pid(void)
{
    int i;
    for (i = 0; i < proc_count; i++)
        if (_wcsicmp(procs[i].exe, APP_NAME) == 0)
            return procs[i].pid;
    return 0;
}

/* ---- windows ------------------------------------------------------------------------ */

static Win seen[MAX_WINDOWS];
static int seen_count;

static BOOL CALLBACK collect_window(HWND hwnd, LPARAM param)
{
    Win *win;
    (void)param;
    if (seen_count >= MAX_WINDOWS)
        return FALSE;
    win = &seen[seen_count++];
    win->hwnd = hwnd;
    win->pid = 0;
    GetWindowThreadProcessId(hwnd, &win->pid);
    win->visible = IsWindowVisible(hwnd);
    if (!GetWindowRect(hwnd, &win->rect))
        memset(&win->rect, 0, sizeof(win->rect));
    win->exstyle = (DWORD)GetWindowLongW(hwnd, GWL_EXSTYLE);
    if (!GetClassNameW(hwnd, win->cls, 40))
        win->cls[0] = L'\0';
    return TRUE;
}

static BOOL listed(const Win *win)
{
    return win->visible || wcscmp(win->cls, L"DESKTOP") == 0;
}

/* Writes the visible windows (and DESKTOP) top to bottom when anything about them changed. */
static void diff_windows(HWND *last_front)
{
    HWND front = GetForegroundWindow();
    BOOL changed = front != *last_front;
    int i, a = 0, b = 0, visible = 0;
    seen_count = 0;
    EnumWindows(collect_window, 0);
    for (;;) {  /* compare the listed windows in order */
        while (a < seen_count && !listed(&seen[a]))
            a++;
        while (b < window_count && !listed(&windows[b]))
            b++;
        if (a >= seen_count || b >= window_count) {
            if (a < seen_count || b < window_count)
                changed = TRUE;
            break;
        }
        if (seen[a].hwnd != windows[b].hwnd || seen[a].visible != windows[b].visible ||
            memcmp(&seen[a].rect, &windows[b].rect, sizeof(RECT)) != 0 ||
            seen[a].exstyle != windows[b].exstyle)
            changed = TRUE;
        a++;
        b++;
    }
    memcpy(windows, seen, sizeof(Win) * seen_count);
    window_count = seen_count;
    *last_front = front;
    if (!changed)
        return;
    for (i = 0; i < window_count; i++)
        if (windows[i].visible)
            visible++;
    {
        DWORD pid = 0;
        WCHAR cls[40] = L"";
        if (front) {
            GetWindowThreadProcessId(front, &pid);
            if (!GetClassNameW(front, cls, 40))
                cls[0] = L'\0';
        }
        begin("windows|");
        put_uint((unsigned long)window_count);
        put(" in all, ");
        put_uint((unsigned long)visible);
        put(" visible|front ");
        put_hex((unsigned long)front);
        put(" ");
        put_wide(exe_of(pid), 31);
        put(" ");
        put_wide(cls, 39);
        end_line();
    }
    for (i = 0; i < window_count; i++) {
        const Win *win = &windows[i];
        if (!listed(win))
            continue;
        begin("  win|z ");
        put_uint((unsigned long)i);
        put("|");
        put_hex((unsigned long)win->hwnd);
        put("|");
        put_uint(win->pid);
        put(" ");
        put_wide(exe_of(win->pid), 31);
        put("|");
        put_wide(win->cls, 39);
        put(win->visible ? "|visible|" : "|hidden|");
        put_int(win->rect.left);
        put(",");
        put_int(win->rect.top);
        put(",");
        put_int(win->rect.right);
        put(",");
        put_int(win->rect.bottom);
        put("|ex ");
        put_hex(win->exstyle);
        end_line();
    }
}

/* ---- does the app answer? ----------------------------------------------------------- */

static DWORD WINAPI probe(LPVOID window)
{
    SendMessageW((HWND)window, WM_NULL, 0, 0);
    return 0;
}

/* One check at a time; a check that never returns is reported, never repeated. */
static void check_answer(DWORD app, int *last)
{
    HWND target = NULL;
    int i, now;
    DWORD tick = GetTickCount();
    if (probe_thread) {
        if (WaitForSingleObject(probe_thread, 0) == WAIT_TIMEOUT) {
            now = 0;
        } else {
            CloseHandle(probe_thread);
            probe_thread = NULL;
            begin("answer|late, after ");
            put_uint(tick - probe_started);
            put(" ms");
            end_line();
            now = 1;
        }
    } else {
        static DWORD last_probe;
        if (!app || tick - last_probe < PROBE_EVERY_MS)
            return;
        last_probe = tick;
        for (i = 0; i < window_count && !target; i++)
            if (windows[i].pid == app && windows[i].visible)
                target = windows[i].hwnd;
        if (!target)
            for (i = 0; i < window_count && !target; i++)
                if (windows[i].pid == app)
                    target = windows[i].hwnd;
        if (!target)
            return;
        probe_started = tick;
        probe_thread = CreateThread(NULL, 0, probe, target, 0, NULL);
        if (!probe_thread)
            return;
        if (WaitForSingleObject(probe_thread, PROBE_WAIT_MS) == WAIT_TIMEOUT) {
            now = 0;
        } else {
            CloseHandle(probe_thread);
            probe_thread = NULL;
            now = 1;
        }
    }
    if (now != *last) {
        begin(now ? "answer|AutoKit answers" : "answer|AutoKit does NOT answer within ");
        if (!now)
            put_uint(GetTickCount() - probe_started);
        end_line();
        *last = now;
    }
}

/* ---- drivers and files -------------------------------------------------------------- */

static void diff_drivers(void)
{
    static WCHAR last[1024];
    WCHAR now[1024], key[64], path[96], name[64];
    HKEY active, device;
    DWORD i, size, type, length = 0;
    now[0] = L'\0';
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"Drivers\\Active", 0, 0, &active) != ERROR_SUCCESS)
        return;
    for (i = 0;; i++) {
        size = 64;
        if (RegEnumKeyExW(active, i, key, &size, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
            break;
        wcscpy(path, L"Drivers\\Active\\");
        wcsncat(path, key, 64);
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, path, 0, 0, &device) != ERROR_SUCCESS)
            continue;
        size = sizeof(name);
        if (RegQueryValueExW(device, L"Name", NULL, &type, (BYTE *)name, &size) == ERROR_SUCCESS &&
            type == REG_SZ) {
            name[63] = L'\0';
            if (length + wcslen(name) + 2 < 1024) {
                wcscat(now, name);
                wcscat(now, L" ");
                length += wcslen(name) + 1;
            }
        }
        RegCloseKey(device);
    }
    RegCloseKey(active);
    if (wcscmp(now, last) != 0) {
        begin("drivers|");
        put_wide(now, 1023);
        end_line();
        wcscpy(last, now);
    }
}

static void copy_changed(void)
{
    unsigned i;
    for (i = 0; i < COPY_COUNT; i++) {
        WIN32_FIND_DATAW found;
        WCHAR target[MAX_PATH];
        HANDLE search = FindFirstFileW(copies[i][0], &found);
        if (search == INVALID_HANDLE_VALUE)
            continue;
        FindClose(search);
        if (found.nFileSizeLow == copied_size[i] && found.ftLastWriteTime.dwLowDateTime == copied_time[i])
            continue;
        if (wcslen(folder) + wcslen(copies[i][1]) + 2 >= MAX_PATH)
            continue;
        wcscpy(target, folder);
        wcscat(target, L"\\");
        wcscat(target, copies[i][1]);
        if (CopyFileW(copies[i][0], target, FALSE)) {  /* busy: try again next tick */
            copied_size[i] = found.nFileSizeLow;
            copied_time[i] = found.ftLastWriteTime.dwLowDateTime;
            begin("copied|");
            put_wide(copies[i][1], 40);
            put("|");
            put_uint(found.nFileSizeLow);
            put(" bytes");
            end_line();
        }
    }
}

/* ---- main --------------------------------------------------------------------------- */

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    DWORD seconds = 0, started, last_heartbeat, desktop_state = 2;
    HWND front = (HWND)-1;
    int answer = -1;
    WCHAR *at = command;
    (void)instance;
    (void)previous;
    (void)show;

    while (*at == L' ')
        at++;
    while (*at >= L'0' && *at <= L'9')
        seconds = seconds * 10 + (DWORD)(*at++ - L'0');
    while (*at == L' ' || *at == L'"')
        at++;
    if (seconds < 10 || seconds > 3600 || !*at || wcslen(at) + 12 >= MAX_PATH)
        return 1;
    wcscpy(folder, at);
    while (wcslen(folder) && (folder[wcslen(folder) - 1] == L'"' || folder[wcslen(folder) - 1] == L' ' ||
                              folder[wcslen(folder) - 1] == L'\\'))
        folder[wcslen(folder) - 1] = L'\0';
    wcscpy(log_path, folder);
    wcscat(log_path, L"\\watch.log");

    started = GetTickCount();
    last_heartbeat = started;
    begin("start|s2am watch|seconds ");
    put_uint(seconds);
    put("|toolhelp ");
    put_uint(load_toolhelp());
    end_line();
    flush();
    if (write_failures)
        return 1;

    for (;;) {
        DWORD now = GetTickCount(), app;
        HWND desktop;
        DWORD visible;
        if (snapshot) {
            list_processes();
            diff_processes();
        }
        diff_windows(&front);
        desktop = FindWindowW(L"DESKTOP", NULL);
        visible = desktop ? (IsWindowVisible(desktop) ? 1 : 0) : 3;
        if (visible != desktop_state) {
            begin(visible == 3 ? "desktop|no DESKTOP window" :
                  visible ? "desktop|SYNC shown" : "desktop|SYNC hidden");
            end_line();
            desktop_state = visible;
        }
        app = snapshot ? app_pid() : 0;
        check_answer(app, &answer);
        if (!app && answer != -1) {
            answer = -1;
            begin("answer|no AutoKit");
            end_line();
        }
        diff_drivers();
        copy_changed();
        if (now - last_heartbeat >= HEARTBEAT_MS) {
            begin("tick|");
            put_uint((now - started) / 1000);
            put(" s");
            end_line();
            last_heartbeat = now;
        }
        flush();
        if (write_failures >= 3)
            return 1;  /* the stick is gone */
        if (now - started >= seconds * 1000)
            break;
        Sleep(TICK_MS);
    }
    begin("end");
    end_line();
    flush();
    return 0;
}
