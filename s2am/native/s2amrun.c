/*
 * s2am runner guard: stands in for SyncAppsRunner.exe so that leaving an app never
 * leaves SYNC 2 with a dead screen.
 *
 * How the stock runner works (from its disassembly): it hides SYNC's window of
 * class "DESKTOP" and sets the named event SYNC_DESKTOP_HIDE_UI, starts the app,
 * and a thread waits for the app's process to end. Only then does it give the
 * screen back: SYNC_DESKTOP_SHOW_UI, ShowWindow(DESKTOP), SetForegroundWindow,
 * then the events "show" and "HandleShow". If the app hides itself instead of
 * ending, or hangs while closing, the screen stays dead.
 *
 * This program starts the original runner (SyncAppsRunner.orig.exe, next to it)
 * with the same command line, so everything the stock runner does still happens.
 * While the app runs, it looks once a second. It acts only when NOTHING usable is
 * on the screen: no visible window of the app, SYNC's DESKTOP hidden, and no visible
 * foreground window of any other program (so never over the reversing camera or a
 * second program's picture).
 *   - the app has shown a window before and nothing usable has been on the screen
 *     for 5 s: the app gets WM_CLOSE; if nothing became usable again within 3 s it
 *     is terminated. The original runner then gives the screen back as usual.
 *   - the app has ended and nothing usable has been on the screen for 5 s: it gives
 *     the screen back itself, with the stock runner's own steps.
 * It keeps watching while the app lives, whichever runner instance started it. A
 * second start while it watches (the icon tapped again) goes straight to the
 * original runner, which toggles the app as before.
 *
 * Every state change is appended to \SyncExtendedPack\_s2am\guard.log.
 * Usage: SyncAppsRunner.exe <app path>       (as the app plugins call it)
 *        s2amrun.exe --s2am-selftest <file>  (writes what it can see, changes nothing)
 * Only COREDLL is imported; toolhelp.dll (which the stock runner also uses) is
 * loaded at run time.
 */
#include <windows.h>

#define TICK_MS 1000
#define STUCK_TICKS 5
#define CLOSE_WAIT_MS 3000
#define CLOSE_POLL_MS 500
#define LOG_PATH L"\\SyncExtendedPack\\_s2am\\guard.log"
#define LOG_LIMIT (64 * 1024)
#define ORIGINAL_NAME L"SyncAppsRunner.orig.exe"
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

/* Named in the self-test. Its size also keeps this file from ever being the size of
 * Ford's runner, which the install job uses to tell the two apart (and checks). */
const char s2am_guard_id[1024] = "s2am runner guard";

static SnapshotFn snapshot;
static ProcessFn first_process, next_process;
static CloseSnapshotFn close_snapshot;
static DWORD started;

/* ---- log ------------------------------------------------------------------------- */

static void append(const WCHAR *path, const char *text, BOOL truncate)
{
    DWORD written;
    HANDLE file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                              truncate ? CREATE_ALWAYS : OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;
    SetFilePointer(file, 0, NULL, FILE_END);
    WriteFile(file, text, (DWORD)strlen(text), &written, NULL);
    CloseHandle(file);
}

static char *put_uint(char *at, unsigned long value)
{
    char digits[12];
    int i = 11;
    digits[i] = '\0';
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0 && i > 0);
    while (digits[i])
        *at++ = digits[i++];
    return at;
}

static char *put_text(char *at, const char *text)
{
    while (*text)
        *at++ = *text++;
    return at;
}

static char *put_wide(char *at, const WCHAR *text, int limit)
{
    while (*text && limit-- > 0) {
        *at++ = (*text < 128 && *text >= 32) ? (char)*text : '?';
        text++;
    }
    return at;
}

/* One log line: "<ms since start>|<event>|<detail>". */
static void note(const char *event, const char *detail, unsigned long value)
{
    char line[200], *at = line;
    at = put_uint(at, GetTickCount() - started);
    at = put_text(at, "|");
    at = put_text(at, event);
    if (detail) {
        at = put_text(at, "|");
        at = put_text(at, detail);
        at = put_uint(at, value);
    }
    at = put_text(at, "\r\n");
    *at = '\0';
    append(LOG_PATH, line, FALSE);
}

/* ---- what is on the screen ----------------------------------------------------------- */

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

/* Process id of the first process whose file name is ``name``, or 0. */
static DWORD find_process(const WCHAR *name, int *count)
{
    ProcessEntry entry;
    DWORD found = 0;
    HANDLE list = snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPNOHEAPS, 0);
    if (count)
        *count = 0;
    if (list == INVALID_HANDLE_VALUE)
        return 0;
    entry.dwSize = sizeof(entry);
    if (first_process(list, &entry)) {
        do {
            if (count)
                (*count)++;
            if (!found && _wcsicmp(entry.szExeFile, name) == 0)
                found = entry.th32ProcessID;
            entry.dwSize = sizeof(entry);
        } while (next_process(list, &entry));
    }
    close_snapshot(list);
    return found;
}

typedef struct {
    DWORD pid;
    BOOL visible;
    BOOL close;
} WindowScan;

static BOOL CALLBACK scan_window(HWND window, LPARAM param)
{
    WindowScan *scan = (WindowScan *)param;
    DWORD pid = 0;
    GetWindowThreadProcessId(window, &pid);
    if (pid == scan->pid) {
        if (IsWindowVisible(window))
            scan->visible = TRUE;
        if (scan->close)
            PostMessageW(window, WM_CLOSE, 0, 0);
    }
    return TRUE;
}

static BOOL app_visible(DWORD pid)
{
    WindowScan scan = {pid, FALSE, FALSE};
    EnumWindows(scan_window, (LPARAM)&scan);
    return scan.visible;
}

static BOOL sync_visible(void)
{
    HWND desktop = FindWindowW(L"DESKTOP", NULL);
    return desktop && IsWindowVisible(desktop);
}

/* A visible foreground window of another program (the camera, another app's picture). */
static BOOL other_on_screen(DWORD app)
{
    DWORD pid = 0;
    HWND front = GetForegroundWindow();
    if (!front || !IsWindowVisible(front))
        return FALSE;
    GetWindowThreadProcessId(front, &pid);
    return pid != app;
}

/* True when the screen shows nothing the user can work with: the frozen state. */
static BOOL nothing_on_screen(DWORD app)
{
    return !(app && app_visible(app)) && !sync_visible() && !other_on_screen(app);
}

/* ---- what it does ------------------------------------------------------------------- */

static void set_event(const WCHAR *name)
{
    HANDLE event = OpenEventW(EVENT_ALL_ACCESS, FALSE, name);
    if (event) {
        SetEvent(event);
        CloseHandle(event);
    }
}

/* The stock runner's own "give the screen back" steps, in the same order. */
static void show_sync(void)
{
    HWND desktop = FindWindowW(L"DESKTOP", NULL);
    set_event(L"SYNC_DESKTOP_SHOW_UI");
    if (desktop) {
        ShowWindow(desktop, SW_SHOW);
        SetForegroundWindow((HWND)((DWORD)desktop | 1));
    }
    set_event(L"show");
    set_event(L"HandleShow");
}

/* WM_CLOSE first; terminate only if the app neither ends nor shows anything usable. */
static void close_app(DWORD pid)
{
    WindowScan scan = {pid, FALSE, TRUE};
    HANDLE process = OpenProcess(0, FALSE, pid);
    DWORD waited;
    if (!process)
        return;
    EnumWindows(scan_window, (LPARAM)&scan);
    note("close", "sent WM_CLOSE to pid ", pid);
    for (waited = 0; waited < CLOSE_WAIT_MS; waited += CLOSE_POLL_MS) {
        if (WaitForSingleObject(process, CLOSE_POLL_MS) != WAIT_TIMEOUT) {
            note("closed", "pid ", pid);
            CloseHandle(process);
            return;
        }
        if (!nothing_on_screen(pid)) {
            note("recovered", "something is on the screen again, leaving pid ", pid);
            CloseHandle(process);
            return;
        }
    }
    TerminateProcess(process, 0);
    note("terminate", "pid ", pid);
    CloseHandle(process);
}

/* The app's file name from "<path to app> [arguments]", quotes allowed. */
static void app_name(const WCHAR *command, WCHAR *name, int size)
{
    const WCHAR *start, *end, *slash;
    int length;
    while (*command == L' ')
        command++;
    if (*command == L'"') {
        start = ++command;
        end = wcschr(start, L'"');
    } else {
        start = command;
        end = wcschr(start, L' ');
    }
    if (!end)
        end = start + wcslen(start);
    for (slash = start; slash < end; slash++)
        if (*slash == L'\\')
            start = slash + 1;
    length = (int)(end - start);
    if (length >= size)
        length = size - 1;
    wcsncpy(name, start, length);
    name[length] = L'\0';
}

static int selftest(WCHAR *path)
{
    char line[200], *at = line;
    int count = 0;
    HWND desktop;
    while (*path == L' ' || *path == L'"')
        path++;
    if (wcslen(path) && path[wcslen(path) - 1] == L'"')
        path[wcslen(path) - 1] = L'\0';
    desktop = FindWindowW(L"DESKTOP", NULL);
    at = put_text(at, "s2amrun ok|");
    at = put_text(at, s2am_guard_id);
    at = put_text(at, "|toolhelp ");
    at = put_uint(at, load_toolhelp());
    if (snapshot)
        find_process(L"nk.exe", &count);
    at = put_text(at, "|processes ");
    at = put_uint(at, (unsigned long)count);
    at = put_text(at, "|desktop ");
    at = put_uint(at, desktop != NULL);
    at = put_text(at, "|desktop_visible ");
    at = put_uint(at, desktop && IsWindowVisible(desktop));
    at = put_text(at, "\r\n");
    *at = '\0';
    append(path, line, TRUE);
    return 0;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR original[MAX_PATH], name[MAX_PATH], *slash;
    PROCESS_INFORMATION runner;
    HANDLE guard;
    BOOL watching, seen = FALSE, shown = FALSE, restored = FALSE, runner_done = FALSE,
         last_app = FALSE, last_vis = FALSE, last_sync = TRUE, last_empty = FALSE;
    DWORD pid = 0, code = 0;
    HANDLE app_process = NULL;
    int hidden = 0, gone = 0, after = 0;
    HANDLE log;
    (void)instance;
    (void)previous;
    (void)show;

    started = GetTickCount();
    if (wcsncmp(command, L"--s2am-selftest", 15) == 0)
        return selftest(command + 15);

    log = CreateFileW(LOG_PATH, 0, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (log != INVALID_HANDLE_VALUE) {  /* keep the log small */
        BOOL large = GetFileSize(log, NULL) > LOG_LIMIT;
        CloseHandle(log);
        if (large)
            append(LOG_PATH, "log restarted\r\n", TRUE);
    }

    /* The first instance watches; a second one (the icon tapped again) only passes on. */
    guard = CreateMutexW(NULL, FALSE, L"s2amRunnerGuard");
    watching = guard && GetLastError() != ERROR_ALREADY_EXISTS && load_toolhelp();

    GetModuleFileNameW(NULL, original, MAX_PATH);
    slash = wcsrchr(original, L'\\');
    if (!slash || (slash - original) + 1 + wcslen(ORIGINAL_NAME) >= MAX_PATH)
        return 1;
    wcscpy(slash + 1, ORIGINAL_NAME);
    app_name(command, name, MAX_PATH);
    {
        char line[200], *at = line;
        at = put_text(at, watching ? "start|" : "pass|");
        at = put_wide(at, name, 60);
        *at = '\0';
        note(line, NULL, 0);
    }
    if (!CreateProcessW(original, command, NULL, NULL, FALSE, 0, NULL, NULL, NULL, &runner)) {
        note("error", "original runner did not start, error ", GetLastError());
        return 1;
    }
    CloseHandle(runner.hThread);

    if (!watching) {  /* a toggle (or no toolhelp): behave exactly like the original */
        WaitForSingleObject(runner.hProcess, INFINITE);
        GetExitCodeProcess(runner.hProcess, &code);
        CloseHandle(runner.hProcess);
        if (guard)
            CloseHandle(guard);
        return (int)code;
    }

    /* Watch while the original runner or the app lives (a second runner may own the app). */
    for (;;) {
        BOOL app, vis, sync, empty;
        if (!runner_done) {
            if (WaitForSingleObject(runner.hProcess, TICK_MS) != WAIT_TIMEOUT) {
                runner_done = TRUE;
                GetExitCodeProcess(runner.hProcess, &code);
                note("runner-exit", "code ", code);
            }
        } else {
            Sleep(TICK_MS);
        }
        if (app_process && WaitForSingleObject(app_process, 0) != WAIT_TIMEOUT) {
            CloseHandle(app_process);  /* the app has ended */
            app_process = NULL;
        }
        if (!app_process) {
            pid = find_process(name, NULL);
            app_process = pid ? OpenProcess(0, FALSE, pid) : NULL;
        }
        app = pid != 0;
        vis = app && app_visible(pid);
        sync = sync_visible();
        empty = nothing_on_screen(app ? pid : 0);
        if (app)
            seen = TRUE;
        if (vis)
            shown = TRUE;  /* not before: a starting app has no window yet */
        if (app != last_app || vis != last_vis || sync != last_sync || empty != last_empty) {
            char line[80], *at = line;
            at = put_text(at, "state|app ");
            at = put_uint(at, app);
            at = put_text(at, " app_visible ");
            at = put_uint(at, vis);
            at = put_text(at, " sync_visible ");
            at = put_uint(at, sync);
            at = put_text(at, " nothing_usable ");
            at = put_uint(at, empty);
            *at = '\0';
            note(line, NULL, 0);
            last_app = app;
            last_vis = vis;
            last_sync = sync;
            last_empty = empty;
        }
        hidden = (shown && app && empty) ? hidden + 1 : 0;
        if (hidden >= STUCK_TICKS) {
            note("stuck", "nothing usable on the screen, closing pid ", pid);
            close_app(pid);
            hidden = 0;
            shown = FALSE;
        }
        gone = (seen && !app && empty) ? gone + 1 : 0;
        if (gone >= STUCK_TICKS && !restored) {
            note("restore", "app ended but SYNC stayed hidden", 0);
            show_sync();
            restored = TRUE;
        }
        if (runner_done && !app) {
            if (!seen || !empty || restored || ++after > 2 * STUCK_TICKS)
                break;  /* never started, back to normal, repaired, or given up */
        }
    }
    if (app_process)
        CloseHandle(app_process);
    CloseHandle(runner.hProcess);
    if (guard)
        CloseHandle(guard);
    return (int)code;
}
