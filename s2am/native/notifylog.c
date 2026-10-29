/*
 * s2am notifylog: records AutoKit's registered window messages and foreground changes.
 * Usage: notifylog.exe <seconds> <output file>
 *
 * AutoKit.exe and Uigeardll2.dll import RegisterWindowMessageW and PostMessageW,
 * so its _UIGEAR_* states are registered window messages. This program registers
 * the same names on a hidden top-level window. Messages AutoKit broadcasts reach
 * it; messages AutoKit posts to its own window do not, and the log shows which.
 * Every 500 ms it also records a change of the foreground window. It exits by
 * itself after <seconds> and changes nothing on the car.
 *
 * Line format: <ms since start>|MSG|<name>|<wParam>|<lParam>
 *              <ms since start>|FG|<window class>|<window title>
 */
#include <windows.h>

#define TIMER_ID 1
#define TICK_MS 500

/* Every _UIGEAR_ name in AutoKit.exe and Uigeardll2.dll (2022.02.15 build). */
static const WCHAR *names[] = {
    L"_UIGEAR_BOX_NOTIFY_",
    L"_UIGEAR_ASTEP_VISABLE_",
    L"_UIGEAR_ASTEP_ONOFF_AA_",
    L"_UIGEAR_ASTEP_SET_WORK_MODE_",
    L"_UIGEAR_ASTEP_A2DPOK_",
    L"_UIGEAR_ASTEP_BACKINGCAR_AA_",
    L"_UIGEAR_ASTEP_LANGRUAGE_",
    L"_UIGEAR_ASTEP_SEND_CTRL_CMD_AA_",
    L"_UIGEAR_ASTEP_SET_VOLUME_AA_",
    L"_UIGEAR_ASTEP_SET_VOLUME_ALTAUDIO_AA_",
    L"_UIGEAR_ASTEP_SET_VOLUME_MAINAUDIO_AA_",
};
#define COUNT (sizeof(names) / sizeof(names[0]))

static UINT ids[COUNT];
static HANDLE logfile = INVALID_HANDLE_VALUE;
static DWORD started;
static DWORD duration_ms;
static HWND last_foreground;

static void put(const char *text)
{
    DWORD written;
    WriteFile(logfile, text, (DWORD)strlen(text), &written, NULL);
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

static void put_hex(unsigned long value)
{
    static const char hex[] = "0123456789abcdef";
    char digits[11];
    int i;
    digits[0] = '0';
    digits[1] = 'x';
    for (i = 0; i < 8; i++)
        digits[2 + i] = hex[(value >> (28 - 4 * i)) & 0xf];
    digits[10] = '\0';
    put(digits);
}

/* Window titles are UTF-16; the log stays ASCII ('|' and non-ASCII become '?'). */
static void put_wide(const WCHAR *text)
{
    char buffer[200];
    int i = 0;
    while (*text != L'\0' && i < (int)sizeof(buffer) - 1) {
        WCHAR c = *text++;
        buffer[i++] = (c >= 32 && c < 127 && c != L'|') ? (char)c : '?';
    }
    buffer[i] = '\0';
    put(buffer);
}

static void line_start(const char *kind)
{
    put_uint(GetTickCount() - started);
    put("|");
    put(kind);
    put("|");
}

static void line_end(void)
{
    put("\r\n");
    FlushFileBuffers(logfile); /* the stick may be pulled at any time */
}

static void log_foreground(void)
{
    HWND foreground = GetForegroundWindow();
    WCHAR title[128];
    WCHAR class_name[64];
    if (foreground == last_foreground)
        return;
    last_foreground = foreground;
    title[0] = L'\0';
    class_name[0] = L'\0';
    if (foreground != NULL) {
        GetWindowTextW(foreground, title, 128);
        GetClassNameW(foreground, class_name, 64);
    }
    line_start("FG");
    put_wide(class_name);
    put("|");
    put_wide(title);
    line_end();
}

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    unsigned i;
    for (i = 0; i < COUNT; i++) {
        if (ids[i] != 0 && message == ids[i]) {
            line_start("MSG");
            put_wide(names[i]);
            put("|");
            put_hex((unsigned long)wparam);
            put("|");
            put_hex((unsigned long)lparam);
            line_end();
            return 0;
        }
    }
    if (message == WM_TIMER) {
        log_foreground();
        if (GetTickCount() - started >= duration_ms)
            PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

/* "<seconds> <path>", the path possibly quoted or containing spaces. */
static WCHAR *parse(WCHAR *command, DWORD *seconds)
{
    WCHAR *end;
    *seconds = 0;
    while (*command == L' ')
        command++;
    while (*command >= L'0' && *command <= L'9')
        *seconds = *seconds * 10 + (DWORD)(*command++ - L'0');
    while (*command == L' ' || *command == L'"')
        command++;
    end = command + wcslen(command);
    while (end > command && (end[-1] == L' ' || end[-1] == L'"'))
        *--end = L'\0';
    return command;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WNDCLASSW window_class;
    HWND window;
    MSG message;
    DWORD seconds;
    WCHAR *path;
    unsigned i;
    (void)previous;
    (void)show;

    path = parse(command, &seconds);
    if (seconds < 10 || seconds > 900 || *path == L'\0')
        return 2;
    duration_ms = seconds * 1000;
    logfile = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, OPEN_ALWAYS,
                          FILE_ATTRIBUTE_NORMAL, NULL);
    if (logfile == INVALID_HANDLE_VALUE)
        return 1;
    SetFilePointer(logfile, 0, NULL, FILE_END);
    started = GetTickCount();
    line_start("start");
    put_uint(seconds);
    line_end();

    for (i = 0; i < COUNT; i++) {
        ids[i] = RegisterWindowMessageW(names[i]);
        line_start("REG");
        put_wide(names[i]);
        put("|");
        put_hex(ids[i]);
        line_end();
    }

    memset(&window_class, 0, sizeof(window_class));
    window_class.lpfnWndProc = window_proc;
    window_class.hInstance = instance;
    window_class.lpszClassName = L"s2am_notifylog";
    RegisterClassW(&window_class);
    /* A top-level window that is never shown: broadcasts reach it, the screen does not change. */
    window = CreateWindowExW(0, L"s2am_notifylog", L"s2am notifylog", WS_POPUP,
                             0, 0, 0, 0, NULL, NULL, instance, NULL);
    if (window == NULL) {
        line_start("error");
        put("CreateWindowExW failed ");
        put_uint(GetLastError());
        line_end();
        CloseHandle(logfile);
        return 3;
    }
    SetTimer(window, TIMER_ID, TICK_MS, NULL);
    log_foreground();

    while (GetMessageW(&message, NULL, 0, 0) > 0)
        DispatchMessageW(&message);

    line_start("end");
    line_end();
    CloseHandle(logfile);
    return 0;
}
