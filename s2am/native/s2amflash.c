/*
 * s2am flash tune: change how much processor time Ford's screen program (Desktop.exe) asks for.
 * Usage: s2amflash.exe set:<name>=<number>[,<name>=<number>...]|<output folder>
 *        s2amflash.exe undo|<output folder>
 *
 * Desktop.exe reads four numbers from HKLM\Software\Ford\Flash when it starts: the priority of
 * its drawing thread (ThreadPrio256, and FastThreadPrio256 while it animates) and how often it
 * draws (FlashNormalTimerInterval and FlashFastTimerInterval, in ms). This program changes only
 * those four, only as numbers, and only within the limits below. It never creates the key.
 *
 * Before the first change it writes all four present values to
 * \SyncExtendedPack\_s2am\flash-backup.txt (through a staging file, so a power cut never leaves
 * half a backup under that name), and it refuses to change anything if that fails. An existing
 * backup is kept, so it always holds Ford's values however often the job runs; one that cannot
 * be read is never replaced. "undo" writes the backup's values back and then removes the backup.
 * One run at a time: a named mutex is held from the first read to the last write. After any
 * write, whether it worked or not, the registry is saved and all four values are read back and
 * reported; a change that fails half way is taken back and the report says whether that worked.
 * Desktop.exe uses the new numbers after SYNC restarts.
 *
 * Output: <folder>\flash.txt, then flash-done.txt once finished.
 *   before|<name>|<number or absent>     after|<name>|<number or absent>
 *   restore|<name>|<number or absent>    (undo: what the backup holds)
 *   backup|written / kept / removed      flush|<code>
 * The report stops at the first line that cannot be written whole; without its done line the
 * result counts as not known.
 *   done|ok      done|refused|<why> (it stopped before writing anything to the registry)
 *   done|failed|<why> (it stopped after it began writing: the after| lines say what is there)
 * Only COREDLL is imported.
 */
#include <windows.h>
#include <string.h>

#define NAMES 4
#define TEXT_CHARS 512

/* pure: begin (plain C, built and tested on the Mac too) */
struct setting { const char *name; unsigned long low, high; };

static const struct setting settings[NAMES] = {
    {"ThreadPrio256", 250, 253},            /* Ford: 250. 251 is where ordinary programs run */
    {"FastThreadPrio256", 248, 253},        /* Ford: 248. 254 and 255 would be idle time only */
    {"FlashNormalTimerInterval", 500, 2000},/* Ford: 500 ms */
    {"FlashFastTimerInterval", 66, 250},    /* Ford: 66 ms */
};

struct plan { int wanted[NAMES]; unsigned long value[NAMES]; int absent[NAMES]; };

static int setting_index(const char *name, size_t length)
{
    int i;
    for (i = 0; i < NAMES; i++)
        if (strlen(settings[i].name) == length && !memcmp(settings[i].name, name, length))
            return i;
    return -1;
}

/* A decimal number that fits 32 bits; returns the character after it, or NULL. */
static const char *read_number(const char *at, unsigned long *value)
{
    int digits = 0;
    *value = 0;
    while (*at >= '0' && *at <= '9') {
        unsigned long digit = (unsigned long)(*at++ - '0');
        if (*value > (0xFFFFFFFFUL - digit) / 10) return NULL;
        *value = *value * 10 + digit;
        digits++;
    }
    return digits ? at : NULL;
}

/* "Name=number" items separated by `separator`. With `limits` every number must be inside its
 * setting's limits; without, "absent" is accepted too (the backup's way to say the value was
 * not there). Each name at most once, at least one item. Returns 1 when the whole text is valid. */
static int read_plan(const char *text, char separator, int limits, struct plan *plan)
{
    int any = 0;
    memset(plan, 0, sizeof(*plan));
    while (*text) {
        const char *equals = strchr(text, '=');
        int index;
        if (!equals) return 0;
        index = setting_index(text, (size_t)(equals - text));
        if (index < 0 || plan->wanted[index]) return 0;
        text = equals + 1;
        if (!limits && !strncmp(text, "absent", 6)) {
            plan->absent[index] = 1;
            text += 6;
        } else {
            text = read_number(text, &plan->value[index]);
            if (!text) return 0;
            if (limits && (plan->value[index] < settings[index].low || plan->value[index] > settings[index].high))
                return 0;
        }
        plan->wanted[index] = 1;
        any = 1;
        if (*text == separator) {
            text++;
            if (!*text) return 0;
        } else if (*text) {
            return 0;
        }
    }
    return any;
}

static int complete(const struct plan *plan)  /* a backup must name all four */
{
    int i;
    for (i = 0; i < NAMES; i++)
        if (!plan->wanted[i]) return 0;
    return 1;
}

static void add(char *out, size_t cap, const char *text)
{
    size_t used = strlen(out), n = strlen(text);
    if (used + n >= cap) n = cap - 1 - used;
    memcpy(out + used, text, n);
    out[used + n] = '\0';
}

static void add_uint(char *out, size_t cap, unsigned long value)
{
    char digits[12];
    int n = 0;
    do { digits[n++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (n) { char one[2] = {digits[--n], '\0'}; add(out, cap, one); }
}

static void add_value(char *out, size_t cap, int absent, unsigned long value)
{
    if (absent) add(out, cap, "absent");
    else add_uint(out, cap, value);
}

/* The backup's text: one "Name=value" per line, all four. */
static void backup_text(const struct plan *now, char *out, size_t cap)
{
    int i;
    out[0] = '\0';
    for (i = 0; i < NAMES; i++) {
        add(out, cap, settings[i].name);
        add(out, cap, "=");
        add_value(out, cap, now->absent[i], now->value[i]);
        add(out, cap, "\n");
    }
}
/* pure: end */

#define KEY_PATH L"Software\\Ford\\Flash"
#define BACKUP_PATH L"\\SyncExtendedPack\\_s2am\\flash-backup.txt"
#define STAGING_PATH L"\\SyncExtendedPack\\_s2am\\flash-backup.new"
#define LOCK_NAME L"s2amflash"
#define LOCK_MS 20000

static HANDLE out_file = INVALID_HANDLE_VALUE;

static int report_broken;  /* a line did not reach the stick whole: nothing more is written */

/* A report with a hole could be read as saying something else, so after the first line that is
 * not written whole and saved the report stops, without its "done" line: an unknown result. */
static void emit(const char *text)
{
    DWORD done = 0, length = (DWORD)strlen(text);
    if (out_file == INVALID_HANDLE_VALUE || report_broken)
        return;
    if (!WriteFile(out_file, text, length, &done, NULL) || done != length ||
        !WriteFile(out_file, "\r\n", 2, &done, NULL) || done != 2 || !FlushFileBuffers(out_file))
        report_broken = 1;
}

static void emit_value(const char *what, int index, int absent, unsigned long value)
{
    char line[TEXT_CHARS] = "";
    add(line, sizeof(line), what);
    add(line, sizeof(line), "|");
    add(line, sizeof(line), settings[index].name);
    add(line, sizeof(line), "|");
    add_value(line, sizeof(line), absent, value);
    emit(line);
}

static void emit_code(const char *what, long code)
{
    char line[TEXT_CHARS] = "";
    add(line, sizeof(line), what);
    add(line, sizeof(line), "|");
    add_uint(line, sizeof(line), (unsigned long)code);
    emit(line);
}

static void wide(const char *text, WCHAR *out, size_t cap)
{
    size_t i;
    for (i = 0; text[i] && i < cap - 1; i++) out[i] = (WCHAR)(unsigned char)text[i];
    out[i] = 0;
}

/* 1 with the number, 2 when the value is not there, 0 when it cannot be read as a number. */
static int read_one(HKEY key, int index, unsigned long *value)
{
    WCHAR name[64];
    DWORD type = 0, data = 0, size = sizeof(data);
    LONG code;
    wide(settings[index].name, name, 64);
    code = RegQueryValueExW(key, name, NULL, &type, (BYTE *)&data, &size);
    if (code == ERROR_FILE_NOT_FOUND) return 2;
    if (code != ERROR_SUCCESS || type != REG_DWORD || size != sizeof(data)) return 0;
    *value = data;
    return 1;
}

static int read_all(HKEY key, struct plan *now)
{
    int i;
    memset(now, 0, sizeof(*now));
    for (i = 0; i < NAMES; i++) {
        int got = read_one(key, i, &now->value[i]);
        if (!got) return 0;
        now->wanted[i] = 1;
        now->absent[i] = got == 2;
    }
    return 1;
}

static int write_one(HKEY key, int index, int absent, unsigned long value)
{
    WCHAR name[64];
    DWORD data = value;
    LONG code;
    wide(settings[index].name, name, 64);
    if (absent) {
        code = RegDeleteValueW(key, name);
        return code == ERROR_SUCCESS || code == ERROR_FILE_NOT_FOUND;
    }
    return RegSetValueExW(key, name, 0, REG_DWORD, (const BYTE *)&data, sizeof(data)) == ERROR_SUCCESS;
}

/* Write the chosen values of `want`, stopping at the first that fails. */
static int write_plan(HKEY key, const struct plan *want)
{
    int i;
    for (i = 0; i < NAMES; i++)
        if (want->wanted[i] && !write_one(key, i, want->absent[i], want->value[i]))
            return 0;
    return 1;
}

static int matches(const struct plan *want, const struct plan *now)
{
    int i;
    for (i = 0; i < NAMES; i++)
        if (want->wanted[i] && (want->absent[i] != now->absent[i] ||
                                (!want->absent[i] && want->value[i] != now->value[i])))
            return 0;
    return 1;
}

static int exists(const WCHAR *path)
{
    return GetFileAttributesW(path) != 0xFFFFFFFF;
}

static int read_backup(const WCHAR *path, struct plan *plan)
{
    char text[TEXT_CHARS];
    DWORD got = 0;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    BOOL ok;
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = ReadFile(file, text, sizeof(text) - 1, &got, NULL);
    CloseHandle(file);
    if (!ok || !got || got >= sizeof(text) - 1) return 0;
    text[got] = '\0';
    if (strlen(text) != got || text[got - 1] != '\n') return 0;  /* a cut-off backup is not trusted */
    text[got - 1] = '\0';
    return read_plan(text, '\n', 0, plan) && complete(plan);
}

/* The staging file is written, saved, closed and read back before it takes the backup's name;
 * MoveFileW does not replace an existing file, so an existing backup can never be overwritten. */
static int write_backup(const struct plan *now)
{
    char text[TEXT_CHARS];
    struct plan again;
    DWORD done = 0;
    HANDLE file;
    BOOL ok;
    backup_text(now, text, sizeof(text));
    CreateDirectoryW(L"\\SyncExtendedPack\\_s2am", NULL);
    file = CreateFileW(STAGING_PATH, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    ok = WriteFile(file, text, (DWORD)strlen(text), &done, NULL) && done == strlen(text);
    ok = FlushFileBuffers(file) && ok;
    ok = CloseHandle(file) && ok;
    ok = ok && read_backup(STAGING_PATH, &again) && matches(now, &again);
    ok = ok && MoveFileW(STAGING_PATH, BACKUP_PATH);
    if (!ok) {
        DeleteFileW(STAGING_PATH);
        return 0;
    }
    return read_backup(BACKUP_PATH, &again) && matches(now, &again);
}

/* The whole change, with the lock held. Returns NULL when it worked, else why not; `began` is
 * set just before the first write to the registry, and stays 0 when it stopped before that. */
static const char *change(const char *mode, int undo, int *began)
{
    struct plan want, before, after, saved;
    HKEY key;
    int i, wrote;
    LONG code;
    const char *why = NULL;

    memset(&want, 0, sizeof(want));
    if (!undo && !read_plan(mode + 4, ',', 1, &want))
        return "the request is not valid";
    code = RegOpenKeyExW(HKEY_LOCAL_MACHINE, KEY_PATH, 0, 0, &key);
    if (code != ERROR_SUCCESS) return "Ford's Flash settings are not in the registry";
    if (!read_all(key, &before)) {
        RegCloseKey(key);
        return "a present value is not a number";
    }
    for (i = 0; i < NAMES; i++) emit_value("before", i, before.absent[i], before.value[i]);

    DeleteFileW(STAGING_PATH);  /* left by a run that was cut short; never the backup itself */
    if (undo) {
        if (!exists(BACKUP_PATH)) why = "there is no backup, so nothing was changed by this tool";
        else if (!read_backup(BACKUP_PATH, &want)) why = "the backup cannot be read";
        else for (i = 0; i < NAMES; i++) emit_value("restore", i, want.absent[i], want.value[i]);
    } else if (exists(BACKUP_PATH)) {
        if (!read_backup(BACKUP_PATH, &saved)) why = "the existing backup cannot be read";
        else emit("backup|kept");
    } else if (!write_backup(&before)) {
        why = "the backup could not be written";
    } else {
        emit("backup|written");
    }
    if (why) {
        RegCloseKey(key);
        return why;  /* nothing has been written */
    }

    *began = 1;
    wrote = write_plan(key, &want);
    if (!wrote)
        for (i = 0; i < NAMES; i++)  /* take it back; the read-back below says whether that worked */
            if (want.wanted[i]) write_one(key, i, before.absent[i], before.value[i]);
    code = RegFlushKey(key);
    emit_code("flush", code);
    if (!read_all(key, &after)) {
        why = wrote ? "the values cannot be read back"
                    : "a value could not be written and the values cannot be read back";
    } else {
        for (i = 0; i < NAMES; i++) emit_value("after", i, after.absent[i], after.value[i]);
        if (!wrote)
            why = matches(&before, &after) && code == ERROR_SUCCESS
                ? "a value could not be written; the earlier values are back"
                : "a value could not be written and the earlier values are not all back";
        else if (!matches(&want, &after)) why = "the values read back are not the ones written";
        else if (code != ERROR_SUCCESS) why = "the registry could not be saved to storage";
    }
    if (!why && undo) {
        if (DeleteFileW(BACKUP_PATH)) emit("backup|removed");
        else why = "the values are back, but the backup could not be removed";
    }
    RegCloseKey(key);
    return why;
}

static const char *work(const char *mode, int *began)
{
    int undo = !strcmp(mode, "undo");
    HANDLE lock;
    DWORD got;
    const char *why;
    if (!undo && strncmp(mode, "set:", 4))
        return "the request is not valid";
    lock = CreateMutexW(NULL, FALSE, LOCK_NAME);
    if (!lock) return "the lock could not be made";
    got = WaitForSingleObject(lock, LOCK_MS);
    if (got != WAIT_OBJECT_0 && got != WAIT_ABANDONED) {
        CloseHandle(lock);
        return "another run has not finished; nothing was changed by this one";
    }
    why = change(mode, undo, began);
    ReleaseMutex(lock);
    CloseHandle(lock);
    return why;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    char mode[TEXT_CHARS];
    WCHAR path[MAX_PATH + 32];
    const WCHAR *bar = command ? wcschr(command, L'|') : NULL;
    const char *why;
    size_t i, n;
    int began = 0;
    HANDLE done;
    DWORD count;
    (void)instance; (void)previous; (void)show;

    if (!bar || !bar[1] || (size_t)(bar - command) >= sizeof(mode) || wcslen(bar + 1) > MAX_PATH - 20)
        return 2;
    n = (size_t)(bar - command);
    for (i = 0; i < n; i++) {
        if (command[i] < 32 || command[i] > 126) return 2;
        mode[i] = (char)command[i];
    }
    mode[n] = '\0';

    wcscpy(path, bar + 1);
    wcscat(path, L"\\flash.txt");
    out_file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out_file == INVALID_HANDLE_VALUE) return 3;  /* no report, no change */

    why = work(mode, &began);
    if (why) {
        char line[TEXT_CHARS] = "";
        add(line, sizeof(line), began ? "done|failed|" : "done|refused|");
        add(line, sizeof(line), why);
        emit(line);
    } else {
        emit("done|ok");
    }
    CloseHandle(out_file);

    wcscpy(path, bar + 1);
    wcscat(path, L"\\flash-done.txt");
    done = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (done != INVALID_HANDLE_VALUE) {
        const char *word = !why ? "ok" : began ? "failed" : "refused";
        WriteFile(done, word, (DWORD)strlen(word), &count, NULL);
        CloseHandle(done);
    }
    return why ? 1 : 0;
}
