/* Fixed clock/power file inspection using ordinary CE file APIs only.
 * Usage: s2ammodules.exe <report folder>. Never loads a DLL or opens a device.
 * ROMMODULE files are metadata-only: CE cannot expose them as ordinary files.
 * Other files are copied with read-only source handles, at most 4 MiB each.
 * The 60-second budget is checked between calls; it cannot cancel a blocked API.
 */
#include <windows.h>
#include <string.h>

#define FILE_LIMIT (4UL * 1024 * 1024)
#define BUDGET_MS 60000UL
static const char *const names[] = {
    "cspddk.dll", "autopmdrv.dll", "pmicPdk_mc13892.dll", "pmicSdk_mc13892.dll",
    "dvfc_mc13892.dll", "nk.exe", "kernel.dll", "coredll.dll"
};
static HANDLE report = INVALID_HANDLE_VALUE;
static int report_failed;
static DWORD started;
static unsigned char buffer[4096];
static int expired(void) { return (DWORD)(GetTickCount() - started) >= BUDGET_MS; }

/* -1 means the cooperative copy budget expired, 0 is an I/O failure. */
static int write_all(HANDLE file, const void *data, DWORD size, DWORD *total, int bounded)
{
    const unsigned char *p = data;
    while (size) {
        DWORD written = 0;
        if (bounded && expired()) return -1;
        if (!WriteFile(file, p, size, &written, NULL) || !written || written > size)
            return 0;
        *total += written;
        p += written;
        size -= written;
    }
    return 1;
}

static void put(const char *text)
{
    DWORD total = 0;
    if (!report_failed && !write_all(report, text, (DWORD)strlen(text), &total, 0))
        report_failed = 1;
}

static void number(DWORD value)
{
    char digits[11];
    int i = 10;
    digits[i] = 0;
    do { digits[--i] = (char)('0' + value % 10); value /= 10; } while (value && i);
    put(digits + i);
}

static void field(DWORD value) { put("|"); number(value); }
static void line_end(void)
{
    put("\r\n");
    if (!report_failed && !FlushFileBuffers(report)) report_failed = 1;
}

static void append_ascii(WCHAR *path, const char *name)
{
    WCHAR *p = path + wcslen(path);
    while (*name) *p++ = (WCHAR)(unsigned char)*name++;
    *p = 0;
}

static DWORD crc_update(DWORD crc, const unsigned char *data, DWORD count)
{
    DWORD i;
    unsigned int bit;
    for (i = 0; i < count; i++) {
        crc ^= data[i];
        for (bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320UL : 0);
    }
    return crc;
}

static const char *copy_file(const WCHAR *source, const WCHAR *target,
                            const WIN32_FILE_ATTRIBUTE_DATA *before,
                            DWORD *error, DWORD *copied, DWORD *checksum)
{
    HANDLE input, output;
    WIN32_FILE_ATTRIBUTE_DATA after;
    DWORD crc = 0xffffffffUL, remaining = before->nFileSizeLow;
    const char *status = "copied";
    if (expired()) return "error-budget";
    input = CreateFileW(source, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (input == INVALID_HANDLE_VALUE) { *error = GetLastError(); return "open-error"; }
    if (expired()) { CloseHandle(input); return "error-budget"; }
    output = CreateFileW(target, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE) {
        *error = GetLastError(); CloseHandle(input); return "create-error";
    }
    while (remaining) {
        DWORD got = 0, want = remaining < sizeof(buffer) ? remaining : (DWORD)sizeof(buffer);
        int written;
        if (expired()) { status = "error-budget"; break; }
        if (!ReadFile(input, buffer, want, &got, NULL)) {
            *error = GetLastError(); status = "read-error"; break;
        }
        if (!got || got > want) { status = "changed"; break; }
        written = write_all(output, buffer, got, copied, 1);
        if (written <= 0) {
            if (!written) { *error = GetLastError(); status = "write-error"; }
            else status = "error-budget";
            break;
        }
        crc = crc_update(crc, buffer, got);
        remaining -= got;
    }
    if (!strcmp(status, "copied") && expired()) status = "error-budget";
    if (!strcmp(status, "copied")) {
        DWORD got = 0;
        if (!ReadFile(input, buffer, 1, &got, NULL)) {
            *error = GetLastError(); status = "read-error";
        } else if (got) status = "changed";
    }
    if (!strcmp(status, "copied") && expired()) status = "error-budget";
    if (!strcmp(status, "copied")) {
        if (!GetFileAttributesExW(source, GetFileExInfoStandard, &after)) {
            *error = GetLastError(); status = "changed";
        } else if (before->dwFileAttributes != after.dwFileAttributes ||
                   before->nFileSizeHigh != after.nFileSizeHigh ||
                   before->nFileSizeLow != after.nFileSizeLow ||
                   before->ftLastWriteTime.dwHighDateTime != after.ftLastWriteTime.dwHighDateTime ||
                   before->ftLastWriteTime.dwLowDateTime != after.ftLastWriteTime.dwLowDateTime)
            status = "changed";
    }
    if (!FlushFileBuffers(output) && !strcmp(status, "copied")) {
        *error = GetLastError(); status = "flush-error";
    }
    if (!CloseHandle(output) && !strcmp(status, "copied")) {
        *error = GetLastError(); status = "close-error";
    }
    if (!CloseHandle(input) && !strcmp(status, "copied")) {
        *error = GetLastError(); status = "close-error";
    }
    if (!strcmp(status, "copied")) *checksum = crc ^ 0xffffffffUL;
    return status;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR folder[MAX_PATH], path[MAX_PATH], module_folder[MAX_PATH], *end;
    unsigned int i;
    DWORD directory_error = 0;
    (void)instance; (void)previous; (void)show;
    while (*command == L' ' || *command == L'"') command++;
    if (!*command || wcslen(command) + 50 >= MAX_PATH) return 1;
    wcscpy(folder, command);
    end = folder + wcslen(folder);
    while (end > folder && (end[-1] == L' ' || end[-1] == L'"' || end[-1] == L'\\')) *--end = 0;
    if (!*folder) return 1;
    wcscpy(path, folder); wcscat(path, L"\\modules.txt");
    report = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (report == INVALID_HANDLE_VALUE) return 2;
    started = GetTickCount();
    wcscpy(module_folder, folder); wcscat(module_folder, L"\\modules");
    if (!CreateDirectoryW(module_folder, NULL)) {
        directory_error = GetLastError();
        if (directory_error == ERROR_ALREADY_EXISTS) directory_error = 0;
    }
    put("S|s2am-modules-v1|8"); line_end();
    for (i = 0; i < sizeof(names) / sizeof(names[0]) && !report_failed; i++) {
        WIN32_FILE_ATTRIBUTE_DATA info;
        WCHAR source[MAX_PATH];
        DWORD error = 0, copied = 0, checksum = 0;
        const char *status;
        memset(&info, 0, sizeof(info));
        wcscpy(source, L"\\Windows\\"); append_ascii(source, names[i]);
        wcscpy(path, module_folder); wcscat(path, L"\\"); append_ascii(path, names[i]);
        if (expired()) status = "error-budget";
        else if (!GetFileAttributesExW(source, GetFileExInfoStandard, &info)) {
            error = GetLastError(); memset(&info, 0, sizeof(info)); status = "attrs-error";
        } else if (info.dwFileAttributes & FILE_ATTRIBUTE_ROMMODULE) status = "rom-module";
        else if (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) status = "directory";
        else if (info.nFileSizeHigh || info.nFileSizeLow > FILE_LIMIT) status = "too-large";
        else if (directory_error) { error = directory_error; status = "create-error"; }
        else status = copy_file(source, path, &info, &error, &copied, &checksum);
        put("F|"); put(names[i]); field(info.dwFileAttributes); field(info.nFileSizeHigh);
        field(info.nFileSizeLow); field(info.ftLastWriteTime.dwHighDateTime);
        field(info.ftLastWriteTime.dwLowDateTime); put("|"); put(status);
        field(error); field(copied); field(checksum); line_end();
    }
    put("T|complete"); line_end();
    if (!CloseHandle(report)) report_failed = 1;
    if (report_failed) return 3;
    wcscpy(path, folder); wcscat(path, L"\\modules-done.txt");
    report = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (report == INVALID_HANDLE_VALUE) return 4;
    put("T|complete"); line_end();
    if (!CloseHandle(report)) report_failed = 1;
    return report_failed ? 5 : 0;
}
