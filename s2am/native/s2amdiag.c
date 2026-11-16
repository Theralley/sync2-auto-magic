/* Direct POST_APP decoder evidence collector; no interpreter is needed to collect.
 * Sources are fixed and read-only. Only the new job's breadcrumb and its fresh USB
 * report are written. The optional children are a fresh harmless script and the
 * read-only clock helper, never the old decoder script. A timeout does not kill a
 * child or claim failure/completion. The 60 s cooperative budget cannot cancel a
 * blocked filesystem/process API. Cleanup and report completion remain allowed.
 *
 * D|label|attrs|attrsError|spaceOK|spaceError|freeHigh|freeLow|totalHigh|totalLow
 * P/C|status|error|waitResult|exitValid|exitCode|markerPresent
 * P's marker is own/probe-done.txt; C's is report/clock.txt. Presence is only an
 * observation at collection time, never proof that a timed-out child completed.
 */
#include <windows.h>
#include <string.h>

#define FILE_LIMIT (4UL * 1024 * 1024)
#define BUDGET_MS 60000UL
static const WCHAR job_root[] = L"\\SyncExtendedPack\\_s2am\\jobs\\";
static const WCHAR *const mounts[] = {
    L"\\USB Disk", L"\\USB Disk2", L"\\USB Disk 2", L"\\USB Disk1", L"\\USB Disk3"
};
static const char *const labels[] = {
    "active-avcodec-56.dll", "active-avutil-54.dll", "active-avformat-56.dll",
    "backup-avcodec-56.dll", "backup-avutil-54.dll", "backup-avformat-56.dll",
    "staged-new-avcodec-56.dll", "staged-new-avutil-54.dll", "staged-new-avformat-56.dll",
    "staged-script", "staged-runner", "staged-mortscript", "staged-job", "old-done"
};
static const WCHAR *const dlls[] = {L"avcodec-56.dll", L"avutil-54.dll", L"avformat-56.dll"};
static const WCHAR *const staged[] = {L"s2amjob.mscr", L"s2amjob.exe", L"MortScript.exe", L"job.json"};
static HANDLE report = INVALID_HANDLE_VALUE, trace = INVALID_HANDLE_VALUE;
static int report_failed;
static DWORD started, report_error;
static unsigned char buffer[4096];
static WCHAR own[MAX_PATH], old[MAX_PATH], backup[MAX_PATH], usb[MAX_PATH];
static WCHAR out[MAX_PATH], files[MAX_PATH], own_id[32], target_id[32];

static int expired(void) { return (DWORD)(GetTickCount() - started) >= BUDGET_MS; }

/* -1: cooperative deadline, 0: I/O failure, 1: complete. */
static int write_all(HANDLE file, const void *data, DWORD size, DWORD *total, int bounded)
{
    const unsigned char *p = data;
    while (size) {
        DWORD written = 0;
        if (bounded && expired()) return -1;
        SetLastError(0);
        if (!WriteFile(file, p, size, &written, NULL)) return 0;
        if (!written || written > size) { SetLastError(29); return 0; }
        *total += written; p += written; size -= written;
    }
    return 1;
}

static void breadcrumb(const char *line)
{
    DWORD total = 0;
    if (trace != INVALID_HANDLE_VALUE) {
        (void)write_all(trace, line, (DWORD)strlen(line), &total, 0);
        (void)FlushFileBuffers(trace);
    }
}

static void breadcrumb_error(const char *phase, DWORD error)
{
    char line[100], digits[11]; int i = 10;
    digits[i] = 0;
    do { digits[--i] = (char)('0' + error % 10); error /= 10; } while (error && i);
    strcpy(line, phase); strcat(line, "|"); strcat(line, digits + i); strcat(line, "\r\n");
    breadcrumb(line);
}

static void put(const char *text)
{
    DWORD total = 0;
    if (!report_failed && !write_all(report, text, (DWORD)strlen(text), &total, 0)) {
        report_error = GetLastError(); report_failed = 1;
    }
}

static void number(DWORD value)
{
    char digits[11]; int i = 10;
    digits[i] = 0;
    do { digits[--i] = (char)('0' + value % 10); value /= 10; } while (value && i);
    put(digits + i);
}

static void field(DWORD value) { put("|"); number(value); }
static void line_end(void)
{
    put("\r\n");
    if (!report_failed && !FlushFileBuffers(report)) {
        report_error = GetLastError(); report_failed = 1;
    }
}

static void wide_ascii(const WCHAR *value)
{
    char s[2]; s[1] = 0;
    while (*value) { s[0] = (char)*value++; put(s); }
}

static int path(WCHAR *dest, const WCHAR *base, const WCHAR *tail)
{
    if (wcslen(base) + wcslen(tail) >= MAX_PATH) return 0;
    wcscpy(dest, base); wcscat(dest, tail); return 1;
}

static int named_path(WCHAR *dest, const WCHAR *base, const WCHAR *name)
{
    if (wcslen(base) + wcslen(name) + 1 >= MAX_PATH) return 0;
    wcscpy(dest, base); wcscat(dest, L"\\"); wcscat(dest, name); return 1;
}

static int id_valid(const WCHAR *id, const WCHAR *kind)
{
    size_t i, n = wcslen(kind);
    if (wcslen(id) != 21 + n || id[8] != L'-' || id[15] != L'-' || id[16+n] != L'-') return 0;
    for (i = 0; i < 15; ++i)
        if (i != 8 && (id[i] < L'0' || id[i] > L'9')) return 0;
    if (wcsncmp(id + 16, kind, n)) return 0;
    for (i = 17+n; i < 21+n; ++i)
        if (!((id[i] >= L'0' && id[i] <= L'9') || (id[i] >= L'a' && id[i] <= L'f'))) return 0;
    return 1;
}

static int own_folder(void)
{
    DWORD n = GetModuleFileNameW(NULL, own, MAX_PATH);
    WCHAR *slash; size_t i;
    if (!n || n >= MAX_PATH - 1) return 0;
    slash = wcsrchr(own, L'\\');
    if (!slash) return 0;
    *slash = 0;
    if (wcslen(own) < wcslen(job_root)) return 0;
    for (i = 0; job_root[i]; ++i) {
        WCHAR a = own[i], b = job_root[i];
        if (a >= L'A' && a <= L'Z') a += L'a' - L'A';
        if (b >= L'A' && b <= L'Z') b += L'a' - L'A';
        if (a != b) return 0;
    }
    slash = own + wcslen(job_root);
    if (!id_valid(slash, L"decdiag")) return 0;
    wcscpy(own_id, slash); return 1;
}

static int target(void)
{
    WCHAR p[MAX_PATH]; unsigned char bytes[64]; DWORD used = 0; HANDLE input; unsigned int i;
    if (!named_path(p, own, L"target.txt") || expired()) return 0;
    input = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (input == INVALID_HANDLE_VALUE) return 0;
    while (used < sizeof(bytes)) {
        DWORD got = 0;
        if (expired() || !ReadFile(input, bytes + used, (DWORD)sizeof(bytes) - used, &got, NULL) ||
            got > sizeof(bytes) - used) { CloseHandle(input); return 0; }
        if (!got) break;
        used += got;
    }
    if (!CloseHandle(input) || used == sizeof(bytes)) return 0;
    if (used && bytes[used-1] == '\n') { --used; if (used && bytes[used-1] == '\r') --used; }
    if (used != 24) return 0;
    for (i = 0; i < used; ++i) target_id[i] = bytes[i];
    target_id[used] = 0;
    if (!id_valid(target_id, L"dec")) return 0;
    return path(old, job_root, target_id) && path(backup, L"\\SyncExtendedPack\\_s2am\\backup\\", target_id);
}

static int find_usb(void)
{
    unsigned int i; int count = 0;
    for (i = 0; i < sizeof(mounts) / sizeof(mounts[0]); ++i) {
        WCHAR p[MAX_PATH], suffix[80]; WIN32_FILE_ATTRIBUTE_DATA info;
        wcscpy(suffix, L"\\s2am\\pending\\"); wcscat(suffix, own_id); wcscat(suffix, L".json");
        if (!path(p, mounts[i], suffix) || expired()) return 0;
        if (GetFileAttributesExW(p, GetFileExInfoStandard, &info)) {
            if (!(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) { wcscpy(usb, mounts[i]); ++count; }
        } else {
            DWORD error = GetLastError();
            if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) {
                breadcrumb_error("pending-mount-error", error); return 0;
            }
        }
    }
    breadcrumb_error("pending-mount-count", (DWORD)count);
    return count == 1;
}

static int directory(const WCHAR *p, int fresh)
{
    WIN32_FILE_ATTRIBUTE_DATA info;
    if (CreateDirectoryW(p, NULL)) return 1;
    if (fresh || GetLastError() != ERROR_ALREADY_EXISTS) return 0;
    return GetFileAttributesExW(p, GetFileExInfoStandard, &info) && (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY);
}

static int prepare_report(void)
{
    WCHAR p[MAX_PATH], suffix[80];
    if (!path(p, usb, L"\\s2am") || !directory(p, 0) ||
        !path(p, usb, L"\\s2am\\reports") || !directory(p, 0)) return 0;
    wcscpy(suffix, L"\\s2am\\reports\\"); wcscat(suffix, own_id);
    if (!path(out, usb, suffix) || !directory(out, 1) ||
        !named_path(files, out, L"files") || !directory(files, 1) ||
        !named_path(p, out, L"decdiag.txt")) return 0;
    report = CreateFileW(p, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    return report != INVALID_HANDLE_VALUE;
}

static DWORD crc_update(DWORD crc, const unsigned char *data, DWORD count)
{
    DWORD i; unsigned int bit;
    for (i = 0; i < count; ++i) {
        crc ^= data[i];
        for (bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320UL : 0);
    }
    return crc;
}

static const char *copy_file(const WCHAR *source, const WCHAR *dest,
                            const WIN32_FILE_ATTRIBUTE_DATA *before,
                            DWORD *error, DWORD *copied, DWORD *checksum)
{
    HANDLE input, output; WIN32_FILE_ATTRIBUTE_DATA after;
    DWORD crc = 0xffffffffUL, remaining = before->nFileSizeLow;
    const char *status = "copied";
    if (expired()) return "error-budget";
    input = CreateFileW(source, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (input == INVALID_HANDLE_VALUE) { *error = GetLastError(); return "open-error"; }
    if (expired()) { CloseHandle(input); return "error-budget"; }
    output = CreateFileW(dest, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE) { *error = GetLastError(); CloseHandle(input); return "create-error"; }
    while (remaining) {
        DWORD got = 0, want = remaining < sizeof(buffer) ? remaining : (DWORD)sizeof(buffer);
        int written;
        if (expired()) { status = "error-budget"; break; }
        if (!ReadFile(input, buffer, want, &got, NULL)) { *error = GetLastError(); status = "read-error"; break; }
        if (!got || got > want) { status = "changed"; break; }
        written = write_all(output, buffer, got, copied, 1);
        if (written <= 0) {
            if (!written) { *error = GetLastError(); status = "write-error"; }
            else status = "error-budget";
            break;
        }
        crc = crc_update(crc, buffer, got); remaining -= got;
    }
    if (!strcmp(status, "copied") && expired()) status = "error-budget";
    if (!strcmp(status, "copied")) {
        DWORD got = 0;
        if (!ReadFile(input, buffer, 1, &got, NULL)) { *error = GetLastError(); status = "read-error"; }
        else if (got) status = "changed";
    }
    if (!strcmp(status, "copied") && expired()) status = "error-budget";
    if (!strcmp(status, "copied")) {
        if (!GetFileAttributesExW(source, GetFileExInfoStandard, &after)) { *error = GetLastError(); status = "changed"; }
        else if (before->dwFileAttributes != after.dwFileAttributes || before->nFileSizeHigh != after.nFileSizeHigh ||
                 before->nFileSizeLow != after.nFileSizeLow ||
                 before->ftLastWriteTime.dwHighDateTime != after.ftLastWriteTime.dwHighDateTime ||
                 before->ftLastWriteTime.dwLowDateTime != after.ftLastWriteTime.dwLowDateTime) status = "changed";
    }
    if (!FlushFileBuffers(output) && !strcmp(status, "copied")) { *error = GetLastError(); status = "flush-error"; }
    if (!CloseHandle(output) && !strcmp(status, "copied")) { *error = GetLastError(); status = "close-error"; }
    if (!CloseHandle(input) && !strcmp(status, "copied")) { *error = GetLastError(); status = "close-error"; }
    if (!strcmp(status, "copied")) *checksum = crc ^ 0xffffffffUL;
    return status;
}

static void capture(unsigned int index)
{
    WCHAR source[MAX_PATH], dest[MAX_PATH], label[80], suffix[80]; unsigned int i;
    WIN32_FILE_ATTRIBUTE_DATA info; DWORD error = 0, copied = 0, checksum = 0;
    const char *status;
    for (i = 0; labels[index][i]; ++i) label[i] = (WCHAR)labels[index][i];
    label[i] = 0;
    (void)named_path(dest, files, label);
    if (index < 3) (void)named_path(source, L"\\SyncExtendedPack\\Apps\\Media\\AutoKit", dlls[index]);
    else if (index < 6) (void)named_path(source, backup, dlls[index-3]);
    else if (index < 9) {
        wcscpy(suffix, L"new-"); wcscat(suffix, dlls[index-6]); (void)named_path(source, old, suffix);
    } else if (index < 13) (void)named_path(source, old, staged[index-9]);
    else {
        wcscpy(suffix, target_id); wcscat(suffix, L".txt");
        (void)named_path(source, L"\\SyncExtendedPack\\_s2am\\done", suffix);
    }
    memset(&info, 0, sizeof(info));
    if (expired()) status = "error-budget";
    else if (!GetFileAttributesExW(source, GetFileExInfoStandard, &info)) {
        error = GetLastError(); memset(&info, 0, sizeof(info)); status = "attrs-error";
    } else if (info.dwFileAttributes & FILE_ATTRIBUTE_ROMMODULE) status = "rom-module";
    else if (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) status = "directory";
    else if (info.nFileSizeHigh || info.nFileSizeLow > FILE_LIMIT) status = "too-large";
    else status = copy_file(source, dest, &info, &error, &copied, &checksum);
    put("F|"); put(labels[index]); field(info.dwFileAttributes); field(info.nFileSizeHigh); field(info.nFileSizeLow);
    field(info.ftLastWriteTime.dwHighDateTime); field(info.ftLastWriteTime.dwLowDateTime); put("|"); put(status);
    field(error); field(copied); field(checksum); line_end();
}

static void disk(const char *label, const WCHAR *p)
{
    WIN32_FILE_ATTRIBUTE_DATA info; ULARGE_INTEGER free_bytes, total, total_free;
    DWORD attr_error = 0, space_error = 0, space_ok = 0;
    memset(&info, 0, sizeof(info)); memset(&free_bytes, 0, sizeof(free_bytes)); memset(&total, 0, sizeof(total));
    if (expired()) attr_error = 1460; /* ERROR_TIMEOUT; no further collection call */
    else if (!GetFileAttributesExW(p, GetFileExInfoStandard, &info)) {
        attr_error = GetLastError(); memset(&info, 0, sizeof(info));
    }
    if (!attr_error && (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
        if (expired()) space_error = 1460;
        else if (GetDiskFreeSpaceExW(p, &free_bytes, &total, &total_free)) space_ok = 1;
        else { space_error = GetLastError(); memset(&free_bytes, 0, sizeof(free_bytes)); memset(&total, 0, sizeof(total)); }
    }
    put("D|"); put(label); field(info.dwFileAttributes); field(attr_error); field(space_ok); field(space_error);
    field(free_bytes.HighPart); field(free_bytes.LowPart); field(total.HighPart); field(total.LowPart); line_end();
}

static int present(const WCHAR *p, DWORD *error)
{
    WIN32_FILE_ATTRIBUTE_DATA info;
    if (!GetFileAttributesExW(p, GetFileExInfoStandard, &info)) { *error = GetLastError(); return 0; }
    *error = 0;
    return (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? 2 : 1;
}

static void child(const char *type, int clock)
{
    WCHAR exe[MAX_PATH], arg[MAX_PATH], marker[MAX_PATH], command[MAX_PATH + 2];
    PROCESS_INFORMATION pi; DWORD error = 0, waited = WAIT_FAILED, exit_valid = 0, code = 0, observed = 0;
    DWORD ignored = 0, remaining, limit = clock ? 15000UL : 10000UL;
    const char *status = "unavailable";
    (void)named_path(exe, own, clock ? L"s2amclock.exe" : L"MortScript.exe");
    (void)named_path(arg, clock ? out : own, clock ? L"clock.txt" : L"probe.mscr");
    (void)named_path(marker, clock ? out : own, clock ? L"clock.txt" : L"probe-done.txt");
    if (expired()) { status = "error-budget"; goto emit; }
    if (present(marker, &error)) { status = "stale-marker"; observed = 1; goto emit; }
    if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) goto emit;
    if (expired()) { status = "error-budget"; error = 0; goto emit; }
    if (present(exe, &error) != 1) goto emit;
    if (!clock) {
        if (expired()) { status = "error-budget"; goto emit; }
        if (present(arg, &error) != 1) goto emit;
    }
    if (expired()) { status = "error-budget"; error = 0; goto emit; }
    command[0] = L'"'; command[1] = 0; wcscat(command, arg); wcscat(command, L"\"");
    memset(&pi, 0, sizeof(pi));
    if (!CreateProcessW(exe, command, NULL, NULL, FALSE, 0, NULL, NULL, NULL, &pi)) {
        status = "launch-error"; error = GetLastError(); goto emit;
    }
    remaining = (DWORD)(GetTickCount() - started);
    remaining = remaining >= BUDGET_MS ? 0 : BUDGET_MS - remaining;
    if (limit > remaining) limit = remaining;
    waited = WaitForSingleObject(pi.hProcess, limit);
    if (waited == WAIT_OBJECT_0) {
        if (GetExitCodeProcess(pi.hProcess, &code)) { exit_valid = 1; status = "exited"; }
        else { status = "exit-error"; error = GetLastError(); code = 0; }
    } else if (waited == WAIT_TIMEOUT) status = "timeout";
    else { status = "wait-error"; error = GetLastError(); }
    (void)CloseHandle(pi.hThread); (void)CloseHandle(pi.hProcess);
    /* Snapshot only; a marker appearing later cannot change this report row. */
    if (!expired()) observed = present(marker, &ignored) == 1;
 emit:
    put(type); put("|"); put(status); field(error); field(waited); field(exit_valid); field(code); field(observed); line_end();
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR p[MAX_PATH]; unsigned int i; DWORD count = 0; int result = 0;
    (void)instance; (void)previous; (void)command; (void)show;
    started = GetTickCount();
    if (!own_folder()) return 1;
    if (named_path(p, own, L"native-entry.txt"))
        trace = CreateFileW(p, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    breadcrumb("native-entry\r\n");
    if (!target()) { breadcrumb("target-invalid\r\n"); result = 2; goto finish; }
    if (!find_usb()) { breadcrumb("pending-usb-not-unique\r\n"); result = 3; goto finish; }
    if (!prepare_report()) { breadcrumb_error("fresh-report-failed", GetLastError()); result = 4; goto finish; }
    put("S|s2am-decdiag-v1|"); wide_ascii(own_id); put("|"); wide_ascii(target_id); line_end();
    for (i = 0; i < sizeof(labels) / sizeof(labels[0]) && !report_failed; ++i) capture(i);
    if (!report_failed) {
        disk("root", L"\\"); disk("apps", L"\\SyncExtendedPack"); disk("usb", usb);
        disk("staged", old); disk("backup", backup);
    }
    if (!report_failed) child("P", 0);
    if (!report_failed) child("C", 1);
    put("T|complete"); line_end();
    if (!CloseHandle(report) && !report_failed) { report_error = GetLastError(); report_failed = 1; }
    report = INVALID_HANDLE_VALUE;
    if (report_failed) { breadcrumb_error("report-incomplete", report_error); result = 5; goto finish; }
    (void)named_path(p, out, L"done.txt");
    report = CreateFileW(p, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (report == INVALID_HANDLE_VALUE) { breadcrumb("done-create-failed\r\n"); result = 6; goto finish; }
    for (i = 0; own_id[i]; ++i) buffer[i] = (unsigned char)own_id[i];
    if (!write_all(report, buffer, i, &count, 0) || !FlushFileBuffers(report)) result = 7;
    if (!CloseHandle(report)) result = 7;
    report = INVALID_HANDLE_VALUE;
    breadcrumb(result ? "done-write-failed\r\n" : "complete\r\n");
 finish:
    if (trace != INVALID_HANDLE_VALUE) (void)CloseHandle(trace);
    return result;
}
