/*
 * s2am native hello: proves that code built with CeGCC runs on SYNC 2.
 * Usage: hello.exe <output file>. Writes one line with the Windows CE version.
 * Only COREDLL is used, so nothing besides this .exe has to be on the car.
 */
#include <windows.h>

static HANDLE out = INVALID_HANDLE_VALUE;

static void put(const char *text)
{
    DWORD written;
    WriteFile(out, text, (DWORD)strlen(text), &written, NULL);
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

/* MortScript passes the parameter string as it is; tolerate surrounding quotes and spaces. */
static WCHAR *argument(WCHAR *text)
{
    WCHAR *end;
    while (*text == L' ' || *text == L'"')
        text++;
    end = text + wcslen(text);
    while (end > text && (end[-1] == L' ' || end[-1] == L'"'))
        *--end = L'\0';
    return text;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    OSVERSIONINFO version;
    (void)instance;
    (void)previous;
    (void)show;

    out = CreateFileW(argument(command), GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                      FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        return 1;
    version.dwOSVersionInfoSize = sizeof(version);
    GetVersionEx(&version);
    put("s2am native hello ok|wince ");
    put_uint(version.dwMajorVersion);
    put(".");
    put_uint(version.dwMinorVersion);
    put(" build ");
    put_uint(version.dwBuildNumber);
    put("|uptime_ms ");
    put_uint(GetTickCount());
    put("\r\n");
    CloseHandle(out);
    return 0;
}
