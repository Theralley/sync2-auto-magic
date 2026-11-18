/*
 * s2am runner guard: stands in for SyncAppsRunner.exe so that leaving an app never
 * leaves SYNC 2 with a dead screen.
 *
 * How the stock runner works (from its disassembly): it hides SYNC's window of
 * class "DESKTOP" and sets the named event SYNC_DESKTOP_HIDE_UI, starts the app,
 * and a thread waits for the app's process to end. Only then does it give the
 * screen back: SYNC_DESKTOP_SHOW_UI, ShowWindow(DESKTOP), SetForegroundWindow,
 * then the events "show" and "HandleShow".
 *
 * What happens in the car (s2amwatch, 2026-10-30): AutoKit's Exit button only hides
 * AutoKit's window (its log says SW_HIDE); the process keeps running. What is left on
 * the screen is SYNC's shell background, a window of class DesktopExplorerWindow
 * (mishell.exe) that is always visible behind everything. The runner keeps waiting,
 * so the screen looks frozen until something ends AutoKit.
 *
 * This program starts the original runner (SyncAppsRunner.orig.exe, next to it)
 * with the same command line, so everything the stock runner does still happens.
 * While the app runs, it looks once a second. Both of its rules wait until the app
 * has shown a window: a starting app has none for its first 2-3 s.
 *   - NOTHING usable has been on the screen for 3 s: no visible top-level window at
 *     all except that shell background. SYNC's DESKTOP, the reversing camera, a
 *     dialog or the app itself all count as usable. The app gets WM_CLOSE; if nothing
 *     became usable again within 2 s it is terminated. The original runner then gives
 *     the screen back as usual.
 *   - the app has had no visible window of its own for 5 s, whatever else is on the
 *     screen. On 2026-11-15 the installer's status window came up 1 s after Exit, so
 *     the first rule never held, the hidden AutoKit kept running, and SYNC's CarPlay
 *     button did nothing until SYNC restarted. The same close follows; here it only
 *     counts as recovered if the app shows a window again.
 *   - the app has ended (or would not end) and nothing usable has been on the screen
 *     for 3 s: it gives the screen back itself, with the stock runner's own steps. Once
 *     per freeze: a screen that is usable again re-arms it for the next one.
 * Each close looks once more, and WM_CLOSE goes only to the windows that look found, after
 * it found the app still gone; an app that is back is left. An app that was left is still
 * judged by both rules from then on, and only a window of its own starts its 5 s again. A
 * close that could not be done (no handle for the app, or the wait or the terminate
 * refused) leaves both rules armed: the same rule tries again once it holds again, and
 * SYNC gets the screen back as for an app that would not end.
 * It keeps watching while the app lives, whichever runner instance started it. A
 * second start while it watches (the icon tapped again) goes straight to the
 * original runner, which toggles the app as before. That toggle (and the stock
 * runner's own switch to SYNC's parking screen) only shows or hides SYNC's DESKTOP
 * over the app and never hides the app's window, so an app behind SYNC still has a
 * visible window and neither rule touches it.
 *
 * Optional, off unless \SyncExtendedPack\_s2am\guard-boost.txt holds 250 or 251
 * (`s2am job runner-guard --boost`): while the app's window is visible and nothing
 * else usable is on the screen, the app's threads at priority 252, the lowest there is
 * (AutoKit's video decoding), run at that level instead: 251 is still below Ford's
 * screens (Desktop.exe runs at 250), 250 shares with them. As soon as anything else is
 * on the screen, or the app's window is gone, they go back to 252, through the handle the
 * guard kept for each; one that would not go back is tried again every second. Only
 * threads of the app's own process are touched, and only while the guard holds a handle
 * for that process: only the handle tells the app ended from a look that failed, and
 * the raised threads are forgotten only once it has ended. The guard then runs one level
 * above them, so it still looks every second. Without the file none of this runs.
 *
 * Optional, off unless \SyncExtendedPack\_s2am\guard-calm.txt holds 252
 * (`s2am job runner-guard --calm`): while the app's window is visible and nothing else
 * usable is on the screen, the threads of Desktop.exe (Ford's screens, a Flash movie that
 * keeps playing behind the app) that run at 250 run at 252 instead, level with the app's
 * video thread and never below it, so they still get their turn. As soon as anything else
 * is on the screen, or the app's window is gone, they go back to 250 through the handle the
 * guard kept for each; one that would not go back is tried again every second, and the
 * guard does not end while one is left (for half a minute). The guard runs at 249 meanwhile,
 * above them. Not together with the boost: with both files the calm stays off. Without the
 * file none of this runs.
 *
 * Optional, off unless \SyncExtendedPack\_s2am\guard-mic.txt holds "on"
 * (`s2am job runner-guard --mic`): SYNC's audio driver is a router, and a recording device
 * carries sound only while a route connects a line to it. The app (AutoKit) opens recording
 * device 0 and asks for no route, so it hears nothing. While the app runs, a second thread
 * of the guard asks the router to connect the microphone (line 0x8003) to device 0: the
 * request is made four times a second, is refused while nothing records there and takes hold
 * as soon as the app starts recording; the driver drops the route by itself when the app closes the device. The request
 * is the driver's own (waveInSetProperty); SYNC's own microphone route is not touched, and
 * nothing is stored. With "find" in the file instead, the request goes to every recording
 * device in turn, to learn which one the app records on. Without the file none of this runs.
 *
 * Every state change is appended to \SyncExtendedPack\_s2am\guard.log.
 * Usage: SyncAppsRunner.exe <app path>       (as the app plugins call it; they use
 *                                             forward slashes: /SyncExtendedPack/...)
 *        s2amrun.exe --s2am-selftest <file>  (writes what it can see, changes nothing)
 * Only COREDLL is imported; toolhelp.dll (which the stock runner also uses) and the
 * thread functions are looked up at run time.
 */
#include <windows.h>

#define TICK_MS 1000
#define STUCK_TICKS 3
#define HIDDEN_TICKS 5  /* looks in a row without a window of the app: 4-5 s, as the log says */
#define CLOSE_WAIT_MS 2000
#define CLOSE_POLL_MS 500
#define LOG_PATH L"\\SyncExtendedPack\\_s2am\\guard.log"
#define BOOST_PATH L"\\SyncExtendedPack\\_s2am\\guard-boost.txt"
#define LOG_LIMIT (64 * 1024)
#define ORIGINAL_NAME L"SyncAppsRunner.orig.exe"
#define BACKGROUND_CLASS L"DesktopExplorerWindow"  /* mishell.exe, always visible */
#define BOOST_FROM 252     /* the lowest priority; AutoKit's video thread (load log, 2026-11-15) */
/* Never above Ford's screens (Desktop.exe, 250): there, a busy video could keep them from
 * ever showing the window that ends the boost. */
#define BOOST_HIGHEST 250
#define BOOST_LOWEST 251
#define MAX_BOOSTED 32
#define CALM_PATH L"\\SyncExtendedPack\\_s2am\\guard-calm.txt"
#define CALM_NAME L"Desktop.exe"
#define CALM_FROM 250      /* Desktop.exe's busy thread (load log, 2026-11-18) */
#define CALM_LEVEL 252     /* level with the app's video thread: shared, never starved */
#define MAX_CALMED 32
#define CALM_END_TRIES 30  /* looks, a second apart, before the guard ends with one left */
#define MIC_PATH L"\\SyncExtendedPack\\_s2am\\guard-mic.txt"
#define MIC_LINE 0x8003    /* the microphone, as the audio driver numbers its lines */
#define MIC_DEVICE 0       /* the recording device the app opens (the default one) */
#define MIC_CONNECT 0      /* the router's request "connect a line" */
#define MIC_HELD 12        /* its answer when that route is in place already */
/* The app may open, close and open its recording at any moment, and speech starts at once. */
#define MIC_ASK_MS 250     /* between requests while the app runs */
#define MIC_IDLE_MS 1000   /* between looks while no app runs: nothing is asked */
#define MIC_FIND_MS 500    /* between rounds of the search over every recording device */
#define MIC_FORGET 7       /* the router's request "take this route out of the table" */
#define MIC_NO_STREAM 13   /* its answer when nothing has that recording device open */
#define MIC_DEVICES 14     /* recording devices 0-13 */
#define MAX_LISTED 256     /* threads of the app in one list; more, and the boost waits */
#define MAX_WINDOWS 32     /* windows of the app one look keeps for WM_CLOSE */
#define TH32CS_SNAPPROCESS 0x00000002
#define TH32CS_SNAPTHREAD 0x00000004
#define TH32CS_SNAPNOHEAPS 0x40000000

typedef struct {
    DWORD dwSize, cntUsage, th32ProcessID, th32DefaultHeapID, th32ModuleID, cntThreads;
    DWORD th32ParentProcessID;
    LONG pcPriClassBase;
    DWORD dwFlags;
    WCHAR szExeFile[MAX_PATH];
    DWORD th32MemoryBase, th32AccessKey;
} ProcessEntry;

typedef struct {
    DWORD dwSize, cntUsage, th32ThreadID, th32OwnerProcessID;
    LONG tpBasePri, tpDeltaPri;
    DWORD dwFlags, th32AccessKey, th32CurrentProcessID;
} ThreadEntry;

typedef HANDLE (WINAPI *SnapshotFn)(DWORD, DWORD);
typedef BOOL (WINAPI *ProcessFn)(HANDLE, ProcessEntry *);
typedef BOOL (WINAPI *ThreadFn)(HANDLE, ThreadEntry *);
typedef BOOL (WINAPI *CloseSnapshotFn)(HANDLE);
typedef HANDLE (WINAPI *OpenThreadFn)(DWORD, BOOL, DWORD);
typedef BOOL (WINAPI *SetPriorityFn)(HANDLE, int);
typedef DWORD (WINAPI *SetPropertyFn)(UINT, const GUID *, ULONG, void *, ULONG, void *, ULONG);

/* via void (*)(void): GCC's sanctioned way to cast between function types */
#define LOOKUP(module, type, name) ((type)(void (*)(void))GetProcAddressW(module, name))

/* Named in the self-test. Its size also keeps this file from ever being the size of
 * the stock runner, which the install job uses to tell the two apart (and checks). */
const char s2am_guard_id[1024] = "s2am runner guard";

static HMODULE toolhelp;
static SnapshotFn snapshot;
static ProcessFn first_process, next_process;
static ThreadFn first_thread, next_thread;
static CloseSnapshotFn close_snapshot;
static OpenThreadFn open_thread;
static SetPriorityFn set_priority;
static DWORD started;

/* ---- log ------------------------------------------------------------------------- */

/* One writer at a time: the microphone thread logs too, and a second open of the file while
 * the first is still writing would fail, and its line be lost. */
static CRITICAL_SECTION log_lock;

static void append(const WCHAR *path, const char *text, BOOL truncate)
{
    DWORD written;
    HANDLE file;
    EnterCriticalSection(&log_lock);
    file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                       truncate ? CREATE_ALWAYS : OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file != INVALID_HANDLE_VALUE) {
        SetFilePointer(file, 0, NULL, FILE_END);
        WriteFile(file, text, (DWORD)strlen(text), &written, NULL);
        CloseHandle(file);
    }
    LeaveCriticalSection(&log_lock);
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
    toolhelp = LoadLibraryW(L"toolhelp.dll");
    if (!toolhelp)
        return FALSE;
    snapshot = LOOKUP(toolhelp, SnapshotFn, L"CreateToolhelp32Snapshot");
    first_process = LOOKUP(toolhelp, ProcessFn, L"Process32First");
    next_process = LOOKUP(toolhelp, ProcessFn, L"Process32Next");
    close_snapshot = LOOKUP(toolhelp, CloseSnapshotFn, L"CloseToolhelp32Snapshot");
    return snapshot && first_process && next_process && close_snapshot;
}

/* The id of the first process whose file name is ``name`` goes to ``pid``, 0 when none runs.
 * FALSE when there is no process list: then nothing is known, which is not "not running". */
static BOOL find_process(const WCHAR *name, DWORD *pid, int *count)
{
    ProcessEntry entry;
    HANDLE list = snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPNOHEAPS, 0);
    *pid = 0;
    if (count)
        *count = 0;
    if (list == INVALID_HANDLE_VALUE)
        return FALSE;
    entry.dwSize = sizeof(entry);
    if (!first_process(list, &entry)) {
        close_snapshot(list);
        return FALSE;  /* a running system has processes: none listed is no list */
    }
    do {
        if (count)
            (*count)++;
        if (!*pid && _wcsicmp(entry.szExeFile, name) == 0)
            *pid = entry.th32ProcessID;
        entry.dwSize = sizeof(entry);
    } while (next_process(list, &entry));
    close_snapshot(list);
    return TRUE;
}

/* Every visible top-level window is something the user can work with, except SYNC's
 * shell background: on its own it is exactly what the frozen screen shows. */
static BOOL usable(const WCHAR *cls, BOOL visible)
{
    return visible && wcscmp(cls, BACKGROUND_CLASS) != 0;
}

/* One look at the screen. It only collects: a close sends WM_CLOSE to the app's windows it
 * kept only after the whole look found none of them shown (close_app). */
typedef struct {
    DWORD pid;
    BOOL app_visible; /* a visible window of the app */
    int others;       /* usable windows of anything else: SYNC, the camera, a dialog */
    HWND windows[MAX_WINDOWS];  /* the app's windows, shown or not; any more are left to the
                                   terminate */
    int count;
} WindowScan;

static BOOL CALLBACK scan_window(HWND window, LPARAM param)
{
    WindowScan *scan = (WindowScan *)param;
    WCHAR cls[40];
    DWORD pid = 0;
    BOOL visible = IsWindowVisible(window);
    GetWindowThreadProcessId(window, &pid);
    if (!GetClassNameW(window, cls, 40))
        cls[0] = L'\0';
    if (scan->pid && pid == scan->pid) {
        if (visible)
            scan->app_visible = TRUE;
        if (scan->count < MAX_WINDOWS)
            scan->windows[scan->count++] = window;
    } else if (usable(cls, visible)) {
        scan->others++;
    }
    return TRUE;
}

static void scan_screen(DWORD app, WindowScan *scan)
{
    scan->pid = app;
    scan->app_visible = FALSE;
    scan->others = 0;
    scan->count = 0;
    EnumWindows(scan_window, (LPARAM)scan);
}

static BOOL sync_visible(void)
{
    HWND desktop = FindWindowW(L"DESKTOP", NULL);
    return desktop && IsWindowVisible(desktop);
}

/* ---- the two rules, one look at a time --------------------------------------------- */

typedef struct {
    BOOL shown;  /* the app has shown a window; before that it is still starting */
    int hidden;  /* looks in a row with nothing usable on the screen */
    int unseen;  /* looks in a row without a window of the app */
} Rules;

enum { KEEP, CLOSE_STUCK, CLOSE_HIDDEN };
/* How a close went. NOT_BACK only within one: the app is still gone, so the close goes on.
 * APP_BACK: a window of the app shows again; OTHERS_BACK: the app is still hidden, but
 * something else usable is on the screen again (only the stuck close stops for that).
 * CLOSE_FAILED: no handle for the app, or the wait or the terminate refused: it may still run. */
enum { NOT_BACK, APP_BACK, OTHERS_BACK, APP_ENDED, APP_TERMINATED, CLOSE_FAILED };

/* What one look means: ``app`` runs, ``vis`` is a window of it shown, ``others`` the usable
 * windows of anything else. Uses only C and BOOL, so the tests replay car logs through it. */
static int judge(Rules *rules, BOOL app, BOOL vis, int others)
{
    if (vis)
        rules->shown = TRUE;  /* not before: a starting app has no window yet */
    rules->hidden = (rules->shown && app && !vis && others == 0) ? rules->hidden + 1 : 0;
    rules->unseen = (rules->shown && app && !vis) ? rules->unseen + 1 : 0;
    if (rules->hidden >= STUCK_TICKS)
        return CLOSE_STUCK;
    if (rules->unseen >= HIDDEN_TICKS)  /* hidden, while something else is on the screen */
        return CLOSE_HIDDEN;
    return KEEP;
}

static void judge_again(Rules *rules)
{
    rules->shown = FALSE;
    rules->hidden = rules->unseen = 0;
}

/* After a close. An app that still runs keeps being judged by both rules (``shown`` stays).
 * Only a window of its own starts the count of looks without one again: a stuck close left
 * because something else came up keeps it, or that could put the hidden rule off for ever. A
 * close that failed starts both counts again, so it is tried again once a rule holds again (3
 * or 5 looks on), not on every look. An app that ended or was terminated is judged from the
 * start, so one that lingers is not closed every few seconds. */
static void judge_after_close(Rules *rules, int outcome)
{
    if (outcome == APP_BACK || outcome == CLOSE_FAILED)
        rules->hidden = rules->unseen = 0;
    else if (outcome == OTHERS_BACK)
        rules->hidden = 0;
    else
        judge_again(rules);
}

/* ---- the guard's own way back for SYNC, and when it stops watching ------------------- */

typedef struct {
    BOOL seen;      /* the app has run */
    BOOL killed;    /* its last close terminated it or failed, and no window of it has shown
                       since: SYNC gets the screen back once nothing usable is on it */
    BOOL restored;  /* the guard gave SYNC the screen, and nothing usable has been on it since */
    int gone;       /* looks in a row with nothing usable while the app has ended or was killed */
} Restore;

enum { SHOW_SYNC = 1, STOP = 2 };  /* what restore_step asks for, either or both */

static void restore_again(Restore *restore)
{
    restore->killed = restore->restored = FALSE;
    restore->gone = 0;
}

/* One look, after the rules: ``app`` runs, ``vis`` a window of it shows, ``empty`` nothing
 * usable was on the screen when the look began, ``outcome`` how this look's close went
 * (NOT_BACK: there was none), ``runner_done`` the original runner has ended. A close that
 * found the app back (APP_BACK, OTHERS_BACK) saw a usable screen in its own later look, so
 * that look counts as usable whatever ``empty`` said. Each freeze gets its own restore: a
 * usable screen re-arms it, and a window of the app ends what a failed close left; a screen
 * that stays empty, failed closes and all, gets none again. It stops once the runner and the
 * app have ended and the app never ran, the screen is usable (back to normal), or SYNC got the
 * screen (repaired). With nothing usable that is within STUCK_TICKS looks: the restore comes
 * first, so no other limit is needed. Uses only C and BOOL, like judge(). */
static int restore_step(Restore *restore, BOOL app, BOOL vis, BOOL empty, int outcome,
                        BOOL runner_done)
{
    int act = 0;
    BOOL usable = !empty || outcome == APP_BACK || outcome == OTHERS_BACK;
    if (app)
        restore->seen = TRUE;
    if (outcome != NOT_BACK)
        restore->killed = outcome == APP_TERMINATED || outcome == CLOSE_FAILED;
    else if (vis)
        restore->killed = FALSE;
    if (usable)
        restore->restored = FALSE;
    restore->gone = (restore->seen && (!app || restore->killed) && !usable) ? restore->gone + 1 : 0;
    if (restore->gone >= STUCK_TICKS && !restore->restored) {
        restore->restored = TRUE;
        act |= SHOW_SYNC;
    }
    if (runner_done && !app && (!restore->seen || usable || restore->restored))
        act |= STOP;
    return act;
}

/* The app's process, as the guard follows it from look to look (follow_app). */
typedef struct {
    DWORD pid;       /* 0: no app runs, as far as the last list said */
    HANDLE process;  /* held while it runs, if it would open: only it can say the app ended */
    BOOL told;       /* a wait on it failed and that was logged; once until it works again */
} Watched;

/* ---- the boost: the app's threads at 252 get more of the processor while it is alone ---- */

typedef struct {
    DWORD id;
    int priority;  /* the base priority the thread list shows */
} Listed;

enum { LEFT, OPENED, RAISED };

typedef struct {
    DWORD id;
    int state;      /* LEFT: would not open or change, left as it is while the app is alone;
                       OPENED: opened on this look, raised once a second list still shows it
                       in the app at 252; RAISED: at the level, set by the guard */
    HANDLE thread;  /* OPENED and RAISED: held, so the id stays this thread's (it is not
                       reused while a handle is open), and the way back goes through it */
    BOOL fresh;     /* raised: what the list shows for it next is logged, once */
    BOOL told;      /* a way back that failed is logged once, and tried on every look */
} Boosted;

static int boost_level;  /* 0: off, and the guard does exactly what it did before the boost */
static Boosted boosted[MAX_BOOSTED];  /* the app's threads the guard has handled */
static int boosted_count;

static BOOL is_blank(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

/* 250 or 251 from the boost file's text, spaces and line ends around it allowed; else 0. */
static int boost_level_of(const char *text, int length)
{
    int i = 0, level = 0, digits = 0;
    while (i < length && is_blank(text[i]))
        i++;
    while (i < length && text[i] >= '0' && text[i] <= '9' && digits < 4) {
        level = level * 10 + (text[i++] - '0');
        digits++;
    }
    while (i < length && is_blank(text[i]))
        i++;
    if (i != length || digits != 3 || level < BOOST_HIGHEST || level > BOOST_LOWEST)
        return 0;
    return level;
}

/* The thread functions, looked up at run time like toolhelp's: a system without one of
 * them loses only the boost. */
static BOOL load_priority(void)
{
    HMODULE core = LoadLibraryW(L"coredll.dll");
    if (!toolhelp || !core)
        return FALSE;
    first_thread = LOOKUP(toolhelp, ThreadFn, L"Thread32First");
    next_thread = LOOKUP(toolhelp, ThreadFn, L"Thread32Next");
    open_thread = LOOKUP(core, OpenThreadFn, L"OpenThread");
    set_priority = LOOKUP(core, SetPriorityFn, L"CeSetThreadPriority");
    return first_thread && next_thread && open_thread && set_priority;
}

/* The app's threads from a fresh thread list: the same list and field as s2amdrive's load
 * logger, whose numbers from the car the boost is built on (AutoKit's video thread: base
 * 252). -1 when there is no list, or more threads than fit: then nothing is decided. */
static int read_threads(DWORD pid, Listed *list, int size)
{
    ThreadEntry entry;
    int count = 0;
    HANDLE snap = snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPTHREAD | TH32CS_SNAPNOHEAPS, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return -1;
    entry.dwSize = sizeof(entry);
    if (first_thread(snap, &entry)) {
        do {
            if (entry.th32OwnerProcessID == pid && count >= 0) {
                if (count == size) {
                    count = -1;
                } else {
                    list[count].id = entry.th32ThreadID;
                    list[count].priority = (int)entry.tpBasePri;
                    count++;
                }
            }
            entry.dwSize = sizeof(entry);
        } while (next_thread(snap, &entry));
    }
    close_snapshot(snap);
    return count > 0 ? count : -1;  /* a running app has a thread: none listed is no list */
}

/* "boost|thread <id><what>[<value>][<more>[<value2>]]"; a value below 0 is left out. */
static void note_thread(DWORD id, const char *what, int value, const char *more, int value2)
{
    char line[120], *at = line;
    at = put_text(at, "boost|thread ");
    at = put_uint(at, id);
    at = put_text(at, what);
    if (value >= 0)
        at = put_uint(at, (unsigned long)value);
    if (more) {
        at = put_text(at, more);
        if (value2 >= 0)
            at = put_uint(at, (unsigned long)value2);
    }
    *at = '\0';
    note(line, NULL, 0);
}

/* The base priority ``list`` shows for thread ``id``, or -1 when it is not in it. */
static int listed_at(const Listed *list, int count, DWORD id)
{
    int i;
    for (i = 0; i < count; i++)
        if (list[i].id == id)
            return list[i].priority;
    return -1;
}

static void drop(int i)
{
    if (boosted[i].thread)
        CloseHandle(boosted[i].thread);
    boosted[i] = boosted[--boosted_count];
}

/* Every entry against a list of the app's threads: one that is not listed has ended, and goes.
 * Not alone on the screen: each thread the guard raised goes back to BOOST_FROM through its
 * handle when the list shows it at the level or still at BOOST_FROM (whether this list shows
 * a change at all is not known yet); any other value is the app's own doing and stays. One
 * that would not go back is tried again on every look. Entries of threads the guard left are
 * dropped, so the next time the app is alone they are tried again. */
static void boost_settle(BOOL alone, const Listed *list, int count)
{
    int i, now;
    for (i = boosted_count - 1; i >= 0; i--) {
        now = listed_at(list, count, boosted[i].id);
        if (now < 0 || (!alone && boosted[i].state != RAISED)) {
            drop(i);
        } else if (!alone) {
            if (now != boost_level && now != BOOST_FROM) {
                note_thread(boosted[i].id, " left as the app set it, at ", now, NULL, -1);
                drop(i);
            } else if (set_priority(boosted[i].thread, BOOST_FROM)) {
                note_thread(boosted[i].id, " from ", boost_level, " to ", BOOST_FROM);
                drop(i);
            } else if (!boosted[i].told) {
                note_thread(boosted[i].id, " would not go back from ", boost_level, NULL, -1);
                boosted[i].told = TRUE;
            }
        }
    }
}

/* Alone on the screen: opens each thread the list shows at BOOST_FROM that has no entry yet.
 * TRUE when one was opened; it is raised only against a second list (boost_raise). */
static BOOL boost_open(const Listed *list, int count)
{
    int i;
    BOOL opened = FALSE;
    Boosted *entry;
    for (i = 0; i < count && boosted_count < MAX_BOOSTED; i++) {
        if (list[i].priority != BOOST_FROM)
            continue;
        for (entry = boosted; entry < boosted + boosted_count && entry->id != list[i].id; entry++)
            ;
        if (entry < boosted + boosted_count)
            continue;  /* handled already: each thread once while the app is alone */
        entry->id = list[i].id;
        entry->fresh = entry->told = FALSE;
        entry->thread = open_thread(THREAD_SET_INFORMATION, FALSE, list[i].id);
        entry->state = entry->thread ? OPENED : LEFT;
        if (entry->thread)
            opened = TRUE;
        else
            note_thread(list[i].id, " could not be opened, so it stays at ", BOOST_FROM, NULL, -1);
        boosted_count++;
    }
    return opened;
}

/* The threads opened on this look, against a list taken after they were opened: only one the
 * list still shows in the app's process at BOOST_FROM is raised, so a thread of any other
 * process is never changed. With no list (``count`` below 0) none is. */
static void boost_raise(const Listed *list, int count)
{
    int i;
    for (i = boosted_count - 1; i >= 0; i--) {
        if (boosted[i].state != OPENED)
            continue;
        if (listed_at(list, count, boosted[i].id) != BOOST_FROM) {
            drop(i);  /* ended, moved by the app, or no list: looked at again on the next look */
        } else if (set_priority(boosted[i].thread, boost_level)) {
            note_thread(boosted[i].id, " from ", BOOST_FROM, " to ", boost_level);
            boosted[i].state = RAISED;
            boosted[i].fresh = TRUE;
        } else {
            note_thread(boosted[i].id, " would not change from ", BOOST_FROM, NULL, -1);
            CloseHandle(boosted[i].thread);
            boosted[i].thread = NULL;
            boosted[i].state = LEFT;
        }
    }
}

/* Once after each raise: what the list shows for that thread. Whether this system's list
 * shows a change at all is not known; the first run in the car tells. */
static void boost_report(const Listed *list, int count)
{
    int i, now;
    for (i = 0; i < boosted_count; i++) {
        if (!boosted[i].fresh)
            continue;
        now = listed_at(list, count, boosted[i].id);
        if (now < 0)
            note_thread(boosted[i].id, " not listed after the change", -1, NULL, -1);
        else
            note_thread(boosted[i].id, " listed at ", now, " after the change", -1);
        boosted[i].fresh = FALSE;
    }
}

/* The app's process has ended (its handle is signalled): its threads ended with it, only the
 * handles go. */
static void boost_forget(void)
{
    while (boosted_count)
        drop(boosted_count - 1);
}

/* One look of the boost. It runs only while the guard holds a handle for the app's process:
 * without one, the app's end could not be told from a look that failed, and what was raised
 * could be forgotten while it still runs. Each step works on a fresh list of the app's threads;
 * without a list nothing is decided, and every entry is kept for the next look. */
static void boost(const Watched *app, BOOL alone)
{
    Listed list[MAX_LISTED];
    int count;
    DWORD pid = app->pid;
    if (!boost_level || !app->process)
        return;  /* off, or no handle: nothing is raised (and so nothing is held) */
    if (!alone && !boosted_count)
        return;  /* nothing raised, nothing to put back: no list needed */
    count = read_threads(pid, list, MAX_LISTED);
    if (count < 0)
        return;
    boost_report(list, count);  /* a raise whose own list failed */
    boost_settle(alone, list, count);
    if (!alone || !boost_open(list, count))
        return;
    count = read_threads(pid, list, MAX_LISTED);  /* after the opening: are they still the app's? */
    boost_raise(list, count);
    count = read_threads(pid, list, MAX_LISTED);
    if (count >= 0)
        boost_report(list, count);
}

/* Reads the boost file once per start. Without it nothing of the boost runs. */
static void start_boost(void)
{
    char text[16];
    DWORD got = 0;
    HANDLE file = CreateFileW(BOOST_PATH, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;
    if (!ReadFile(file, text, sizeof(text), &got, NULL))
        got = 0;
    CloseHandle(file);
    boost_level = got < sizeof(text) ? boost_level_of(text, (int)got) : 0;
    if (!boost_level) {
        note("boost|off: the boost file holds neither 250 nor 251", NULL, 0);
        return;
    }
    /* The guard must stay ahead of what it raises, or it could not look once a second. */
    if (!load_priority() || !set_priority(GetCurrentThread(), boost_level - 1)) {
        boost_level = 0;
        note("boost|off: the thread functions are missing or refused", NULL, 0);
        return;
    }
    note("boost", "on: while the app is alone on the screen, its threads at 252 run at ",
         (unsigned long)boost_level);
}

/* ---- the calm: Ford's screens share with the app's video while they are hidden ---------- */

typedef struct {
    DWORD id;
    HANDLE thread;  /* held from before the change, so the id stays this thread's */
    BOOL lowered;   /* at CALM_LEVEL, set by the guard */
    BOOL told;      /* a way back that failed is logged once, and tried on every look */
} Calmed;

static BOOL calm_on;  /* FALSE: off, and the guard does exactly what it did before the calm */
static Calmed calmed[MAX_CALMED];
static int calmed_count;
static DWORD calm_pid;       /* Desktop.exe, while the guard holds calm_process for it */
static HANDLE calm_process;  /* held from before any thread list: the id stays this process's */

static void note_calm(DWORD id, const char *what, int value, const char *more, int value2)
{
    char line[120], *at = line;
    at = put_text(at, "calm|thread ");
    at = put_uint(at, id);
    at = put_text(at, what);
    if (value >= 0)
        at = put_uint(at, (unsigned long)value);
    if (more) {
        at = put_text(at, more);
        if (value2 >= 0)
            at = put_uint(at, (unsigned long)value2);
    }
    *at = '\0';
    note(line, NULL, 0);
}

static void calm_drop(int i)
{
    CloseHandle(calmed[i].thread);
    calmed[i] = calmed[--calmed_count];
}

/* Every lowered thread goes back to CALM_FROM through its handle, whatever a thread list
 * says: a list may be cut short, so a thread it does not show is not taken as ended. An
 * entry goes only once its thread is back, or its own handle says the thread has ended. One
 * that would not go back stays, for the next look. */
static void calm_back(void)
{
    int i;
    for (i = calmed_count - 1; i >= 0; i--) {
        if (!calmed[i].lowered) {
            calm_drop(i);
        } else if (set_priority(calmed[i].thread, CALM_FROM)) {
            note_calm(calmed[i].id, " from ", CALM_LEVEL, " to ", CALM_FROM);
            calm_drop(i);
        } else if (WaitForSingleObject(calmed[i].thread, 0) == WAIT_OBJECT_0) {
            calm_drop(i);  /* it has ended */
        } else if (!calmed[i].told) {
            note_calm(calmed[i].id, " would not go back from ", CALM_LEVEL, NULL, -1);
            calmed[i].told = TRUE;
        }
    }
}

/* Desktop.exe's process, pinned by a handle the guard keeps: TRUE while that handle is held
 * and has not said the process ended. The handle is opened first and the process list asked
 * again after it: only a list that still shows the same id for Desktop.exe counts, so the
 * threads listed under that id afterwards are Desktop.exe's and no other process's. */
static BOOL calm_pin(void)
{
    DWORD pid, again;
    if (calm_process) {
        if (WaitForSingleObject(calm_process, 0) != WAIT_OBJECT_0)
            return TRUE;
        calm_back();  /* it has ended: its threads with it, the handles go */
        CloseHandle(calm_process);
        calm_process = NULL;
        calm_pid = 0;
    }
    if (!find_process(CALM_NAME, &pid, NULL) || !pid)
        return FALSE;
    calm_process = OpenProcess(0, FALSE, pid);
    if (!calm_process)
        return FALSE;
    if (!find_process(CALM_NAME, &again, NULL) || again != pid ||
        WaitForSingleObject(calm_process, 0) != WAIT_TIMEOUT) {
        CloseHandle(calm_process);
        calm_process = NULL;
        return FALSE;
    }
    calm_pid = pid;
    return TRUE;
}

/* One look of the calm. Not alone on the screen: every lowered thread goes back. Alone: each
 * thread of Desktop.exe a list shows at CALM_FROM is opened, once, and lowered only if a
 * second list, taken after the opening, still shows it in that process at CALM_FROM. Without
 * a list, or without Desktop.exe pinned, nothing new is lowered. */
static void calm(BOOL alone)
{
    Listed list[MAX_LISTED];
    int count, i, j, first;
    if (!calm_on)
        return;
    if (!alone) {
        if (calmed_count)
            calm_back();
        return;
    }
    if (!calm_pin())
        return;
    count = read_threads(calm_pid, list, MAX_LISTED);
    if (count < 0)
        return;
    for (i = calmed_count - 1; i >= 0; i--)  /* only one whose own handle says it ended goes */
        if (WaitForSingleObject(calmed[i].thread, 0) == WAIT_OBJECT_0)
            calm_drop(i);
    first = calmed_count;
    for (i = 0; i < count && calmed_count < MAX_CALMED; i++) {
        if (list[i].priority != CALM_FROM)
            continue;
        for (j = 0; j < calmed_count && calmed[j].id != list[i].id; j++)
            ;
        if (j < calmed_count)
            continue;  /* handled already (its owner may have moved it back: left alone) */
        calmed[calmed_count].thread = open_thread(THREAD_SET_INFORMATION, FALSE, list[i].id);
        if (!calmed[calmed_count].thread)
            continue;  /* stays as it is; looked at again on the next look */
        calmed[calmed_count].id = list[i].id;
        calmed[calmed_count].lowered = calmed[calmed_count].told = FALSE;
        calmed_count++;
    }
    if (calmed_count == first)
        return;
    count = read_threads(calm_pid, list, MAX_LISTED);  /* after the opening: still Desktop.exe's? */
    for (j = calmed_count - 1; j >= first; j--) {
        if (count < 0 || listed_at(list, count, calmed[j].id) != CALM_FROM) {
            calm_drop(j);
        } else if (set_priority(calmed[j].thread, CALM_LEVEL)) {
            note_calm(calmed[j].id, " from ", CALM_FROM, " to ", CALM_LEVEL);
            calmed[j].lowered = TRUE;
        } else {
            note_calm(calmed[j].id, " would not change from ", CALM_FROM, NULL, -1);
            calm_drop(j);
        }
    }
}

/* The watch is over: every lowered thread goes back before the guard ends, and with it the
 * handles. One that will not go back is tried once a second for CALM_END_TRIES looks; the
 * guard does not end before that, since nothing else could put it back. */
static void calm_end(void)
{
    int tries;
    if (!calm_on)
        return;
    for (tries = 0; calmed_count && tries < CALM_END_TRIES; tries++) {
        if (tries)
            Sleep(TICK_MS);
        calm_back();
    }
    if (calmed_count)
        note("calm", "gave up: threads of Desktop.exe left at 252 until SYNC restarts, ",
             (unsigned long)calmed_count);
    if (calm_process)
        CloseHandle(calm_process);
    calm_process = NULL;
}

/* Reads the calm file once per start. Without it nothing of the calm runs. Not together with
 * the boost: a raised video thread would outrank Ford's lowered screens, which could then
 * never show the window that ends both. The guard itself goes above CALM_FROM, so a thread
 * it has just put back cannot keep it from putting back the next. */
static void start_calm(void)
{
    char text[16];
    DWORD got = 0;
    HANDLE file = CreateFileW(CALM_PATH, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;
    if (!ReadFile(file, text, sizeof(text), &got, NULL))
        got = sizeof(text);
    CloseHandle(file);
    if (got >= sizeof(text))
        got = 0;  /* unreadable, or longer than any valid file */
    while (got && is_blank(text[got - 1]))
        got--;
    if (got != 3 || text[0] != '2' || text[1] != '5' || text[2] != '2') {
        note("calm|off: the calm file does not hold 252", NULL, 0);
        return;
    }
    if (boost_level) {
        note("calm|off: the boost is on, and the two do not go together", NULL, 0);
        return;
    }
    if (!load_priority() || !set_priority(GetCurrentThread(), CALM_FROM - 1)) {
        note("calm|off: the thread functions are missing or refused", NULL, 0);
        return;
    }
    calm_on = TRUE;
    note("calm", "on: while the app is alone on the screen, Desktop.exe's threads at 250 run at ",
         CALM_LEVEL);
}

/* ---- the microphone: the router is asked to connect it to the app's recording device ----- */

typedef struct {
    DWORD source, source_dir, sink, sink_dir, flags;
} LineConnect;

#define MIC_NO_ANSWER 0xFFFFFFFF  /* nothing asked yet since the app started */

/* The audio router's property set in wavedev2_cs42448.dll. */
static const GUID MIC_ROUTER = {0xb8ed20d3, 0x954f, 0x48d8, {0x8a, 0x71, 0xd1, 0x36, 0xae, 0xb0, 0x8d, 0xb4}};
static SetPropertyFn set_property;
static volatile LONG mic_wanted;       /* 1 while the app runs, written by the watch loop */
static DWORD mic_last = MIC_NO_ANSWER;  /* the router's last answer, so only changes are logged */
static BOOL mic_finding;               /* the file holds "find": every device is tried */
static DWORD mic_found[MIC_DEVICES];   /* per device, the router's last answer in the search */
static BOOL mic_ours[MIC_DEVICES];     /* per device, the route there is one this search made */
/* The search and its tidying up never run at the same time, and never again once the guard
 * has begun to end: both are done inside ``mic_lock``, and ``mic_over`` is set inside it. */
static CRITICAL_SECTION mic_lock;
static BOOL mic_over;
#define MIC_KEPT 3  /* routes of its own the search keeps at most: the table has few free places */

/* One request: the microphone to the app's recording device. The driver adds no second table
 * entry for a route it already lists, and takes a connection that failed out again, so asking
 * again and again leaves nothing behind. */
static DWORD mic_request(ULONG what, DWORD device)
{
    LineConnect line;
    line.source = MIC_LINE;
    line.source_dir = 0;
    line.sink = device;
    line.sink_dir = 0;
    line.flags = 0;
    return set_property(MIC_DEVICE, &MIC_ROUTER, what, NULL, 0, &line, sizeof(line));
}

static DWORD mic_ask(void)
{
    return mic_request(MIC_CONNECT, MIC_DEVICE);
}

/* The search ("find" in the file): it is not known which recording device the app opens, or
 * whether it opens one at all. One round asks the router to connect the microphone to each
 * device but three: 4 is the one SYNC keeps for its own microphone, 3 and 6 are of another
 * kind (the telephone's sound). A device nobody has open answers MIC_NO_STREAM; any other
 * answer is logged when it changes, with the device, so the log shows which device the app
 * records on and when. Every request enters its route in the router's table, also one that
 * does not connect; unless the route in place is one this search made, the entry is taken
 * out again at once, and the ones it kept go when the app or the guard ends (mic_tidy). The
 * entry for device 0 is one SYNC has from the start and stays. The search keeps at most
 * MIC_KEPT routes of its own: the table has five free places, and a connect that finds it
 * full connects without an entry and answers as if it had failed. */
static void mic_find(void)
{
    DWORD device, answer;
    int kept = 0;
    for (device = 0; device < MIC_DEVICES; device++)
        kept += mic_ours[device] && device != MIC_DEVICE;
    for (device = 0; device < MIC_DEVICES; device++) {
        if (device == 3 || device == 4 || device == 6)
            continue;
        if (kept >= MIC_KEPT && !mic_ours[device] && device != MIC_DEVICE)
            continue;  /* no room in the table for a route to one more device */
        answer = mic_request(MIC_CONNECT, device);
        if (answer == 0) {
            kept += !mic_ours[device] && device != MIC_DEVICE;
            mic_ours[device] = TRUE;
        } else if (answer != MIC_HELD) {  /* MIC_HELD may be ours or somebody else's */
            kept -= mic_ours[device] && device != MIC_DEVICE;
            mic_ours[device] = FALSE;     /* ours is gone */
        }
        if (!mic_ours[device] && device != MIC_DEVICE)
            mic_request(MIC_FORGET, device);
        if (answer != mic_found[device] && !(answer == MIC_HELD && mic_found[device] == 0) &&
            !(answer == MIC_NO_STREAM && mic_found[device] == MIC_NO_ANSWER)) {
            char line[80], *at = line;
            at = put_text(at, "mic|device ");
            at = put_uint(at, device);
            at = put_text(at, answer == 0 ? " connected" : answer == MIC_NO_STREAM ?
                          " is closed again" : " answers ");
            if (answer != 0 && answer != MIC_NO_STREAM)
                at = put_uint(at, answer);
            *at = '\0';
            note(line, NULL, 0);
        }
        mic_found[device] = answer;
    }
}

/* The app is gone, or the guard ends: the table entries the search may have left are taken
 * out (the driver has dropped the routes with the devices), and what the search knew is
 * forgotten. Asking for an entry that is not there is refused and changes nothing. */
static void mic_tidy(void)
{
    DWORD device;
    for (device = 0; device < MIC_DEVICES; device++) {
        if (mic_finding && mic_ours[device] && device != MIC_DEVICE)
            mic_request(MIC_FORGET, device);
        mic_ours[device] = FALSE;
        mic_found[device] = MIC_NO_ANSWER;
    }
    mic_last = MIC_NO_ANSWER;
}

/* One look of the microphone thread; returns how long to wait before the next. No app: nothing
 * is asked. Otherwise the router is asked, and its answer is logged whenever it differs from
 * the last one: 0 means the route was made (the app has begun to record), MIC_HELD that it is
 * still in place, anything else that it was refused, which is the usual answer while the app
 * does not record. An answer of MIC_HELD right after 0 is the same state and not logged. */
static DWORD mic_look(void)
{
    DWORD answer, wait = MIC_IDLE_MS;
    EnterCriticalSection(&mic_lock);
    if (mic_over) {
        /* the guard is ending and has tidied up: nothing more is asked */
    } else if (!mic_wanted) {
        mic_tidy();
    } else if (mic_finding) {
        mic_find();
        wait = MIC_FIND_MS;
    } else {
        answer = mic_ask();
        if (answer != mic_last && !(answer == MIC_HELD && mic_last == 0)) {
            if (answer == 0)
                note("mic", "connected to recording device ", MIC_DEVICE);
            else if (answer == MIC_HELD)
                note("mic", "the route to the recording device is in place already, device ", MIC_DEVICE);
            else
                note("mic", "not connected, the router answers ", answer);
        }
        mic_last = answer;
        wait = MIC_ASK_MS;
    }
    LeaveCriticalSection(&mic_lock);
    return wait;
}

/* The guard ends: the thread asks for nothing more, and what the search left is tidied up. */
static void mic_end(void)
{
    if (!set_property)
        return;  /* off: never started */
    EnterCriticalSection(&mic_lock);
    mic_over = TRUE;
    mic_tidy();
    LeaveCriticalSection(&mic_lock);
}

static DWORD WINAPI mic_thread(LPVOID unused)
{
    (void)unused;
    for (;;)
        Sleep(mic_look());
    return 0;
}

/* Reads the microphone file once per start. Without it nothing of this runs. */
static void start_mic(void)
{
    char text[8];
    DWORD got = 0, got_device;
    HMODULE core;
    HANDLE thread;
    HANDLE file = CreateFileW(MIC_PATH, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;
    if (!ReadFile(file, text, sizeof(text), &got, NULL))
        got = sizeof(text);
    CloseHandle(file);
    if (got >= sizeof(text))
        got = 0;  /* unreadable, or longer than any valid file */
    while (got && is_blank(text[got - 1]))
        got--;
    InitializeCriticalSection(&mic_lock);
    for (got_device = 0; got_device < MIC_DEVICES; got_device++) {
        mic_found[got_device] = MIC_NO_ANSWER;
        mic_ours[got_device] = FALSE;
    }
    mic_finding = got == 4 && text[0] == 'f' && text[1] == 'i' && text[2] == 'n' && text[3] == 'd';
    if (!mic_finding && (got != 2 || text[0] != 'o' || text[1] != 'n')) {
        note("mic|off: the microphone file holds neither on nor find", NULL, 0);
        return;
    }
    core = LoadLibraryW(L"coredll.dll");
    set_property = core ? LOOKUP(core, SetPropertyFn, L"waveInSetProperty") : NULL;
    if (!set_property) {
        note("mic|off: this SYNC has no waveInSetProperty", NULL, 0);
        return;
    }
    thread = CreateThread(NULL, 0, mic_thread, NULL, 0, NULL);
    if (!thread) {
        set_property = NULL;
        note("mic|off: its thread did not start", NULL, 0);
        return;
    }
    CloseHandle(thread);
    note(mic_finding ? "mic|find: the router is asked to connect the microphone to every recording device"
                     : "mic|on: the router is asked to connect the microphone to the app's recording device",
         NULL, 0);
    /* With the boost on, the app's video may run above this thread and keep it waiting. */
}

/* ---- the app's process ---------------------------------------------------------------- */

/* One look at the app's process. While the guard holds a handle for it, only that handle says
 * the app has ended (signalled). A wait that fails says nothing: the app counts as running and
 * what the boost raised is kept, which keeps the guard watching for as long as it fails, so
 * that is logged once, with the error. Once the app has ended, the boost's entries go, since
 * the threads ended with the process. Without a handle the process list is asked, and a list
 * that could not be taken says nothing either: the last look's answer stands. A handle that
 * would not open is tried again on the next look. TRUE when another instance runs (say a quick
 * relaunch): the rules start over. */
static BOOL follow_app(Watched *app, const WCHAR *name)
{
    DWORD found, waited;
    BOOL renewed;
    if (app->process) {
        waited = WaitForSingleObject(app->process, 0);
        if (waited == WAIT_TIMEOUT) {
            app->told = FALSE;
            return FALSE;
        }
        if (waited != WAIT_OBJECT_0) {
            if (!app->told)
                note("error", "cannot wait for the app, it counts as running, error ",
                     GetLastError());
            app->told = TRUE;
            return FALSE;
        }
        CloseHandle(app->process);  /* it has ended */
        app->process = NULL;
        app->pid = 0;
        app->told = FALSE;
        boost_forget();
    }
    if (!find_process(name, &found, NULL))
        return FALSE;
    renewed = found && found != app->pid;
    app->pid = found;
    if (found)
        app->process = OpenProcess(0, FALSE, found);
    return renewed;
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

/* What one look (``scan``) says about an app being closed: APP_BACK once a window of its own
 * shows; for the stuck close (not ``own``) also OTHERS_BACK once anything else usable is on
 * the screen again. The hidden close is about the app's own window only: other windows may be
 * there all along. NOT_BACK otherwise. Noted when it is back. */
static int came_back(const WindowScan *scan, DWORD pid, BOOL own)
{
    if (scan->app_visible) {
        note("recovered", "the app shows a window again, leaving pid ", pid);
        return APP_BACK;
    }
    if (!own && scan->others) {
        note("recovered", "something is on the screen again, leaving pid ", pid);
        return OTHERS_BACK;
    }
    return NOT_BACK;
}

/* WM_CLOSE first; terminate only if the app neither ends nor comes back. ``process`` is the
 * guard's own handle for the app: without one nothing is sent, as the guard could neither wait
 * for the end nor terminate. WM_CLOSE goes to the windows of one last look, and only once that
 * whole look found the app still gone: a window that shows during the look stops it, and one
 * that shows later is seen within half a second. A wait or a terminate that fails is
 * CLOSE_FAILED, never an end. */
static int close_app(HANDLE process, DWORD pid, BOOL own)
{
    WindowScan scan;
    DWORD waited, result;
    int i, back;
    if (!process) {
        note("close", "not possible, no handle for pid ", pid);
        return CLOSE_FAILED;
    }
    scan_screen(pid, &scan);
    back = came_back(&scan, pid, own);
    if (back != NOT_BACK)
        return back;
    for (i = 0; i < scan.count; i++)
        PostMessageW(scan.windows[i], WM_CLOSE, 0, 0);
    note("close", "sent WM_CLOSE to pid ", pid);
    for (waited = 0; waited < CLOSE_WAIT_MS; waited += CLOSE_POLL_MS) {
        result = WaitForSingleObject(process, CLOSE_POLL_MS);
        if (result == WAIT_OBJECT_0) {
            note("closed", "pid ", pid);
            return APP_ENDED;
        }
        if (result != WAIT_TIMEOUT) {
            note("close", "failed, could not wait for pid ", pid);
            return CLOSE_FAILED;
        }
        scan_screen(pid, &scan);
        back = came_back(&scan, pid, own);
        if (back != NOT_BACK)
            return back;
    }
    if (!TerminateProcess(process, 0)) {
        note("terminate", "refused for pid ", pid);
        return CLOSE_FAILED;
    }
    note("terminate", "pid ", pid);
    return APP_TERMINATED;
}

/* The app's file name from "<path to app> [arguments]", quotes allowed. The plugins
 * write the path with forward slashes, so both kinds separate folders. */
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
        if (*slash == L'\\' || *slash == L'/')
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
    DWORD found;
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
        find_process(L"nk.exe", &found, &count);
    at = put_text(at, "|processes ");
    at = put_uint(at, (unsigned long)count);
    at = put_text(at, "|desktop ");
    at = put_uint(at, desktop != NULL);
    at = put_text(at, "|desktop_visible ");
    at = put_uint(at, desktop && IsWindowVisible(desktop));
    at = put_text(at, "|background ");
    at = put_uint(at, FindWindowW(BACKGROUND_CLASS, NULL) != NULL);
    at = put_text(at, "|priority ");  /* the boost's thread functions are all there */
    at = put_uint(at, load_priority());
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
    BOOL watching, runner_done = FALSE, last_app = FALSE, last_vis = FALSE, last_sync = TRUE,
         last_empty = FALSE;
    int last_others = -1;
    DWORD code = 0;
    Watched watched = {0, NULL, FALSE};
    Rules rules;
    Restore restore = {FALSE, FALSE, FALSE, 0};
    int outcome, act;
    HANDLE log;
    (void)instance;
    (void)previous;
    (void)show;

    started = GetTickCount();
    InitializeCriticalSection(&log_lock);
    judge_again(&rules);
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
    if (watching)
        start_boost();
    if (watching)
        start_calm();
    if (watching)
        start_mic();
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
        WindowScan scan;
        if (!runner_done) {
            if (WaitForSingleObject(runner.hProcess, TICK_MS) != WAIT_TIMEOUT) {
                runner_done = TRUE;
                GetExitCodeProcess(runner.hProcess, &code);
                note("runner-exit", "code ", code);
            }
        } else {
            Sleep(TICK_MS);
        }
        if (follow_app(&watched, name)) {  /* a new instance (say a quick relaunch): start over */
            judge_again(&rules);
            restore_again(&restore);
        }
        app = watched.pid != 0;
        InterlockedExchange(&mic_wanted, app);  /* the microphone thread asks only while the app runs */
        scan_screen(watched.pid, &scan);
        vis = scan.app_visible;
        sync = sync_visible();
        empty = !vis && scan.others == 0;
        if (app != last_app || vis != last_vis || sync != last_sync || empty != last_empty ||
            scan.others != last_others) {
            char line[100], *at = line;
            at = put_text(at, "state|app ");
            at = put_uint(at, app);
            at = put_text(at, " app_visible ");
            at = put_uint(at, vis);
            at = put_text(at, " sync_visible ");
            at = put_uint(at, sync);
            at = put_text(at, " other_windows ");
            at = put_uint(at, (unsigned long)scan.others);
            at = put_text(at, " nothing_usable ");
            at = put_uint(at, empty);
            *at = '\0';
            note(line, NULL, 0);
            last_app = app;
            last_vis = vis;
            last_sync = sync;
            last_empty = empty;
            last_others = scan.others;
        }
        /* before either rule closes the app: its threads are back at 252 by then */
        boost(&watched, vis && scan.others == 0);
        calm(vis && scan.others == 0);
        outcome = NOT_BACK;  /* no close on this look */
        switch (judge(&rules, app, vis, scan.others)) {
        case CLOSE_STUCK:
            note("stuck", "nothing usable on the screen, closing pid ", watched.pid);
            outcome = close_app(watched.process, watched.pid, FALSE);
            judge_after_close(&rules, outcome);
            break;
        case CLOSE_HIDDEN:
            note("hidden", "no window of the app on the screen for 5 s, closing pid ", watched.pid);
            outcome = close_app(watched.process, watched.pid, TRUE);
            judge_after_close(&rules, outcome);
            break;
        default:
            break;
        }
        act = restore_step(&restore, app, vis, empty, outcome, runner_done);
        if (act & SHOW_SYNC) {
            note("restore", app ? "app would not end, SYNC gets the screen, pid "
                                : "app ended but SYNC stayed hidden, pid ", watched.pid);
            show_sync();
        }
        if (act & STOP)
            break;  /* never started, back to normal, or repaired */
    }
    InterlockedExchange(&mic_wanted, 0);
    mic_end();
    calm_end();  /* whatever ended the watch: Ford's screens are back at 250 */
    if (watched.process)
        CloseHandle(watched.process);
    CloseHandle(runner.hProcess);
    if (guard)
        CloseHandle(guard);
    return (int)code;
}
