/*
 * s2am registry: a read-only copy of chosen parts of SYNC's registry, for the call sound.
 * Usage: s2amreg.exe <depth> <root>[,<root>...] <output folder>
 *   <root> is HKLM\<path> or HKCU\<path> without spaces, e.g. HKLM\Software\Microsoft\Bluetooth;
 *   the output folder is the rest of the line, so it may hold spaces ("\USB Disk\...").
 * It writes <folder>\registry.txt, and registry-done.txt with the summary once it has finished,
 * so a script can wait for it with a time limit.
 *
 * It lists every key under each root, down to <depth> levels, with each value's name, type
 * and contents. It only opens keys to read them and writes nothing but the output file on
 * the stick. A value is written as "<not copied, N bytes>" when its name or its key's path looks
 * like a secret (key, pin, pass, secret: a paired phone's link key, a PIN), and so is every
 * binary value longer than 8 bytes, whatever its name: such secrets must not leave the car.
 *
 * Lines:  K|<key>     V|<key>|<name>|<type>|<value>     E|<key>|cannot open     T|<summary>
 * Text is kept to printable ASCII ('|' and the rest become '?'); binary values are written
 * as hex, the first 256 bytes. It stops at 200,000 lines or 16 MB and says so.
 * Only COREDLL is imported.
 */
#include <windows.h>
#include <string.h>

#define MAX_DEPTH 8
#define MAX_LINES 200000UL
#define LIMIT_BYTES (16UL * 1024 * 1024)
#define SHOW_BYTES 256
#define NAME_CHARS 256
#define DATA_BYTES 16384
#define PATH_CHARS 512
#define LINE_CHARS (PATH_CHARS + NAME_CHARS + 2 * SHOW_BYTES + 160)

/* pure: begin (plain C, built and tested on the Mac too) */
static int is_secret(const char *name)
{
    static const char *const words[] = {"key", "pin", "pass", "secret"};
    char low[2 * NAME_CHARS + 16];
    size_t i, w;
    for (i = 0; name[i] && i < sizeof(low) - 1; i++)
        low[i] = (name[i] >= 'A' && name[i] <= 'Z') ? (char)(name[i] + 32) : name[i];
    low[i] = '\0';
    for (w = 0; w < sizeof(words) / sizeof(words[0]); w++)
        if (strstr(low, words[w]))
            return 1;
    return 0;
}

#define BINARY_SHOWN 8  /* longer binary values are never copied: a link key is 16 bytes */

static int withheld(const char *key, const char *name, unsigned long type, unsigned long size)
{
    if (is_secret(name) || is_secret(key))
        return 1;
    return type != 1 && type != 2 && type != 4 && type != 7 && type != 11 && size > BINARY_SHOWN;
}

static void clean(char *text)  /* one field per '|': no separators, no line breaks */
{
    for (; *text; text++)
        if (*text == '|' || (unsigned char)*text < 32 || (unsigned char)*text > 126)
            *text = '?';
}

static void add(char *out, size_t cap, const char *text)
{
    size_t used = strlen(out);
    while (*text && used < cap - 1)
        out[used++] = *text++;
    out[used] = '\0';
}

static void add_uint(char *out, size_t cap, unsigned long value)
{
    char digits[12];
    int i = 11;
    digits[i] = '\0';
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0 && i > 0);
    add(out, cap, digits + i);
}

static void add_hex(char *out, size_t cap, const unsigned char *data, unsigned long size)
{
    static const char hex[] = "0123456789abcdef";
    char two[3] = {0, 0, 0};
    unsigned long i;
    for (i = 0; i < size && i < SHOW_BYTES; i++) {
        two[0] = hex[data[i] >> 4];
        two[1] = hex[data[i] & 15];
        add(out, cap, two);
    }
    if (size > SHOW_BYTES) {
        add(out, cap, " ...(");
        add_uint(out, cap, size);
        add(out, cap, " bytes)");
    }
}

static const char *type_name(unsigned long type)
{
    switch (type) {
    case 1: return "sz";
    case 2: return "expand_sz";
    case 3: return "binary";
    case 4: return "dword";
    case 7: return "multi_sz";
    case 11: return "qword";
    default: return "other";
    }
}
/* pure: end */

static HANDLE out_file = INVALID_HANDLE_VALUE;
static unsigned long lines, written, keys, values, hidden;
static int full, failed;
#define RESERVE_LINES 2  /* the limit line and the summary always fit */
#define RESERVE_BYTES 256
static BYTE data[DATA_BYTES];

static void write_all(const char *text, DWORD n)
{
    DWORD done = 0;
    if (!WriteFile(out_file, text, n, &done, NULL) || done != n) {
        failed = 1;
        full = 1;
    }
}

static void emit(const char *text)
{
    DWORD n = (DWORD)strlen(text);
    if (full)
        return;
    if (lines + 1 + RESERVE_LINES > MAX_LINES || written + n + 2 + RESERVE_BYTES > LIMIT_BYTES) {
        full = 1;
        write_all("T|limit reached\r\n", 17);
        lines++;
        written += 17;
        return;
    }
    write_all(text, n);
    write_all("\r\n", 2);
    written += n + 2;
    lines++;
}

static void narrow(const WCHAR *wide, size_t chars, char *out, size_t cap)
{
    size_t i;
    for (i = 0; i < chars && wide[i] && i < cap - 1; i++)
        out[i] = (wide[i] >= 32 && wide[i] < 127) ? (char)wide[i] : '?';
    out[i] = '\0';
}

static void value_line(const char *key, const WCHAR *wide_name, DWORD type, DWORD size, int too_long)
{
    static char line[LINE_CHARS];
    char name[NAME_CHARS], text[2 * SHOW_BYTES + 40];
    narrow(wide_name, NAME_CHARS, name, sizeof(name));
    clean(name);
    text[0] = '\0';
    if (too_long) {
        add(text, sizeof(text), "<too long, not read>");
    } else if (withheld(key, name, type, size)) {
        add(text, sizeof(text), "<not copied, ");
        add_uint(text, sizeof(text), size);
        add(text, sizeof(text), " bytes>");
        hidden++;
    } else if ((type == REG_SZ || type == REG_EXPAND_SZ || type == REG_MULTI_SZ) && size >= sizeof(WCHAR)) {
        size_t chars = size / sizeof(WCHAR), i;
        WCHAR *wide = (WCHAR *)data;
        for (i = 0; i + 1 < chars; i++)  /* a multi_sz's inner ends become ';' */
            if (wide[i] == L'\0')
                wide[i] = L';';
        narrow(wide, chars, text, SHOW_BYTES);
        clean(text);
    } else if (type == REG_DWORD && size == 4) {
        unsigned long v = (unsigned long)data[0] | ((unsigned long)data[1] << 8) | ((unsigned long)data[2] << 16) |
                          ((unsigned long)data[3] << 24);
        add_uint(text, sizeof(text), v);
        add(text, sizeof(text), " (0x");
        add_hex(text, sizeof(text), data + 3, 1);
        add_hex(text, sizeof(text), data + 2, 1);
        add_hex(text, sizeof(text), data + 1, 1);
        add_hex(text, sizeof(text), data, 1);
        add(text, sizeof(text), ")");
    } else {
        add_hex(text, sizeof(text), data, size);
    }
    line[0] = '\0';
    add(line, sizeof(line), "V|");
    add(line, sizeof(line), key);
    add(line, sizeof(line), "|");
    add(line, sizeof(line), name);
    add(line, sizeof(line), "|");
    add(line, sizeof(line), type_name(type));
    add(line, sizeof(line), "|");
    add(line, sizeof(line), text);
    emit(line);
    values++;
}

static void walk(HKEY root, const char *root_name, const WCHAR *path, int depth)
{
    static char line[LINE_CHARS];
    char key_name[PATH_CHARS + 8];
    WCHAR child[PATH_CHARS], sub[NAME_CHARS], name[NAME_CHARS];
    HKEY key;
    DWORD i;
    if (full)
        return;
    key_name[0] = '\0';
    add(key_name, sizeof(key_name), root_name);
    add(key_name, sizeof(key_name), "\\");
    {
        char narrowed[PATH_CHARS];
        narrow(path, PATH_CHARS, narrowed, sizeof(narrowed));
        clean(narrowed);
        add(key_name, sizeof(key_name), narrowed);
    }
    line[0] = '\0';
    if (RegOpenKeyExW(root, path, 0, 0, &key) != ERROR_SUCCESS) {
        add(line, sizeof(line), "E|");
        add(line, sizeof(line), key_name);
        add(line, sizeof(line), "|cannot open");
        emit(line);
        return;
    }
    add(line, sizeof(line), "K|");
    add(line, sizeof(line), key_name);
    emit(line);
    keys++;
    for (i = 0; !full; i++) {
        DWORD name_chars = NAME_CHARS, type = 0, size = DATA_BYTES;
        LONG result = RegEnumValueW(key, i, name, &name_chars, NULL, &type, data, &size);
        if (result == ERROR_NO_MORE_ITEMS)
            break;
        if (result == ERROR_MORE_DATA) {
            value_line(key_name, name, type, 0, 1);
            continue;
        }
        if (result != ERROR_SUCCESS)
            break;
        value_line(key_name, name, type, size, 0);
    }
    for (i = 0; depth > 0 && !full; i++) {
        DWORD sub_chars = NAME_CHARS;
        if (RegEnumKeyExW(key, i, sub, &sub_chars, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
            break;
        if (wcslen(path) + 1 + wcslen(sub) + 1 >= PATH_CHARS)
            continue;
        wcscpy(child, path);
        if (child[0])
            wcscat(child, L"\\");
        wcscat(child, sub);
        walk(root, root_name, child, depth - 1);
    }
    RegCloseKey(key);
}

static WCHAR *next_word(WCHAR **at, WCHAR stop)  /* up to `stop` (or the end), spaces skipped first */
{
    WCHAR *start, *end;
    while (**at == L' ')
        (*at)++;
    if (!**at)
        return NULL;
    start = *at;
    end = stop ? wcschr(start, stop) : NULL;
    if (end) {
        *end = L'\0';
        *at = end + 1;
    } else {
        *at = start + wcslen(start);
    }
    return start;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR *at = command, *word, *roots, *output, path[MAX_PATH];
    int depth;
    char summary[160];
    DWORD done;
    (void)instance;
    (void)previous;
    (void)show;

    word = next_word(&at, L' ');
    if (!word || word[0] < L'0' || word[0] > L'9' || word[1])
        return 1;
    depth = word[0] - L'0';
    roots = next_word(&at, L' ');
    output = next_word(&at, 0);
    if (depth > MAX_DEPTH || !roots || !output)
        return 1;
    while (wcslen(output) && (output[wcslen(output) - 1] == L' ' || output[wcslen(output) - 1] == L'"'))
        output[wcslen(output) - 1] = L'\0';
    while (wcslen(output) && output[wcslen(output) - 1] == L'\\')
        output[wcslen(output) - 1] = L'\0';
    if (wcslen(output) + 24 >= MAX_PATH)
        return 1;
    wcscpy(path, output);
    wcscat(path, L"\\registry.txt");
    out_file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out_file == INVALID_HANDLE_VALUE)
        return 2;
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    while ((word = next_word(&roots, L',')) != NULL) {
        HKEY root = NULL;
        const char *root_name = NULL;
        if (wcsncmp(word, L"HKLM\\", 5) == 0) {
            root = HKEY_LOCAL_MACHINE;
            root_name = "HKLM";
        } else if (wcsncmp(word, L"HKCU\\", 5) == 0) {
            root = HKEY_CURRENT_USER;
            root_name = "HKCU";
        }
        if (!root || wcslen(word + 5) >= PATH_CHARS) {
            emit("E|unknown root|not HKLM\\ or HKCU\\");
            continue;
        }
        walk(root, root_name, word + 5, depth);
    }
    summary[0] = '\0';
    add(summary, sizeof(summary), failed ? "T|write failed (stick full?)|" :
                                  full ? "T|stopped at the limit|" : "T|complete|");
    add_uint(summary, sizeof(summary), keys);
    add(summary, sizeof(summary), " keys|");
    add_uint(summary, sizeof(summary), values);
    add(summary, sizeof(summary), " values|");
    add_uint(summary, sizeof(summary), hidden);
    add(summary, sizeof(summary), " not copied");
    WriteFile(out_file, summary, (DWORD)strlen(summary), &done, NULL);  /* the reserve keeps room for it */
    WriteFile(out_file, "\r\n", 2, &done, NULL);
    CloseHandle(out_file);
    wcscpy(path, output);
    wcscat(path, L"\\registry-done.txt");  /* last: the job waits for this file */
    out_file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out_file != INVALID_HANDLE_VALUE) {
        WriteFile(out_file, summary, (DWORD)strlen(summary), &done, NULL);
        CloseHandle(out_file);
    }
    return 0;
}
