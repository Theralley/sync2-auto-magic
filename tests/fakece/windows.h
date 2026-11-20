/* A small stand-in for the Windows CE API, so s2amflash.c runs whole on the Mac in tests:
 * a registry key with four values, a handful of files in memory, a mutex, and failures on demand
 * (environment FAIL="set=2,flush=1+": the 2nd value write fails, every flush from the 1st on).
 * File failures count only calls on the backup and its staging file; "report" fails writes to
 * flash.txt (two per line: the text, then the line end) and "short" writes half of one. */
#ifndef FAKE_WINDOWS_H
#define FAKE_WINDOWS_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

typedef uint32_t DWORD;
typedef int32_t LONG;
typedef int BOOL;
typedef unsigned char BYTE;
typedef wchar_t WCHAR;
typedef WCHAR *LPWSTR;
typedef void *HANDLE;
typedef void *HINSTANCE;
typedef void *HKEY;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define HKEY_LOCAL_MACHINE ((HKEY)(intptr_t)2)
#define ERROR_SUCCESS 0
#define ERROR_FILE_NOT_FOUND 2
#define REG_SZ 1
#define REG_DWORD 4
#define GENERIC_READ 0x80000000u
#define GENERIC_WRITE 0x40000000u
#define FILE_SHARE_READ 1
#define CREATE_NEW 1
#define CREATE_ALWAYS 2
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 0x80
#define WAIT_OBJECT_0 0
#define WAIT_ABANDONED 0x80
#define WAIT_TIMEOUT 258

#define FAKE_VALUES 4
#define FAKE_FILES 8
static const wchar_t *const fake_names[FAKE_VALUES] = {L"ThreadPrio256", L"FastThreadPrio256",
                                                      L"FlashNormalTimerInterval", L"FlashFastTimerInterval"};
static struct { int present; DWORD type, value; } fake_reg[FAKE_VALUES];
static int fake_key = 1, fake_lock;
static struct fake_file { int used, open, reading; size_t length, at; wchar_t path[200]; char data[2048]; } fake_files[FAKE_FILES];

static int fake_fails(const char *what)  /* is this call of `what` one that FAIL names? */
{
    static struct { char name[16]; int calls; } seen[16];
    const char *plan = getenv("FAIL"), *at;
    size_t n = strlen(what);
    int i, call = 0;
    for (i = 0; i < 16; i++) {
        if (!seen[i].name[0]) strcpy(seen[i].name, what);
        if (!strcmp(seen[i].name, what)) { call = ++seen[i].calls; break; }
    }
    for (at = plan; at && *at; at = strchr(at, ',') ? strchr(at, ',') + 1 : NULL)
        if (!strncmp(at, what, n) && at[n] == '=') {
            int from = atoi(at + n + 1);
            const char *end = at + n + 1;
            while (*end >= '0' && *end <= '9') end++;
            return *end == '+' ? call >= from : call == from;
        }
    return 0;
}

static int fake_backup(const wchar_t *path) { return wcsstr(path, L"flash-backup") != NULL; }

static struct fake_file *fake_find(const wchar_t *path)
{
    int i;
    for (i = 0; i < FAKE_FILES; i++)
        if (fake_files[i].used && !wcscmp(fake_files[i].path, path)) return &fake_files[i];
    return NULL;
}

static int fake_value(const WCHAR *name)
{
    int i;
    for (i = 0; i < FAKE_VALUES; i++)
        if (!wcscmp(fake_names[i], name)) return i;
    fprintf(stderr, "a value outside the four was touched\n");
    abort();
}

static LONG RegOpenKeyExW(HKEY root, const WCHAR *path, DWORD options, DWORD access, HKEY *key)
{
    (void)options; (void)access;
    if (root != HKEY_LOCAL_MACHINE || wcscmp(path, L"Software\\Ford\\Flash")) abort();
    *key = (HKEY)(intptr_t)7;
    return fake_key ? ERROR_SUCCESS : ERROR_FILE_NOT_FOUND;
}

static LONG RegCloseKey(HKEY key) { (void)key; return ERROR_SUCCESS; }

static LONG RegQueryValueExW(HKEY key, const WCHAR *name, DWORD *reserved, DWORD *type, BYTE *data, DWORD *size)
{
    int i = fake_value(name);
    (void)key; (void)reserved;
    if (fake_fails("query")) return 5;
    if (!fake_reg[i].present) return ERROR_FILE_NOT_FOUND;
    *type = fake_reg[i].type;
    if (fake_reg[i].type != REG_DWORD) { *size = 10; return ERROR_SUCCESS; }
    memcpy(data, &fake_reg[i].value, 4);
    *size = 4;
    return ERROR_SUCCESS;
}

static LONG RegSetValueExW(HKEY key, const WCHAR *name, DWORD reserved, DWORD type, const BYTE *data, DWORD size)
{
    int i = fake_value(name);
    (void)key; (void)reserved;
    if (type != REG_DWORD || size != 4) abort();
    if (fake_fails("set")) return 5;
    fake_reg[i].present = 1;
    fake_reg[i].type = REG_DWORD;
    memcpy(&fake_reg[i].value, data, 4);
    return ERROR_SUCCESS;
}

static LONG RegDeleteValueW(HKEY key, const WCHAR *name)
{
    int i = fake_value(name);
    (void)key;
    if (fake_fails("del")) return 5;
    if (!fake_reg[i].present) return ERROR_FILE_NOT_FOUND;
    fake_reg[i].present = 0;
    return ERROR_SUCCESS;
}

static LONG RegFlushKey(HKEY key) { (void)key; return fake_fails("flush") ? 5 : ERROR_SUCCESS; }

static BOOL CreateDirectoryW(const WCHAR *path, void *security) { (void)path; (void)security; return TRUE; }

static DWORD GetFileAttributesW(const WCHAR *path) { return fake_find(path) ? FILE_ATTRIBUTE_NORMAL : 0xFFFFFFFF; }

static HANDLE CreateFileW(const WCHAR *path, DWORD access, DWORD share, void *security, DWORD how, DWORD flags,
                          HANDLE model)
{
    struct fake_file *file = fake_find(path);
    int i;
    (void)share; (void)security; (void)flags; (void)model;
    if (fake_backup(path) && how != OPEN_EXISTING && fake_fails("create")) return INVALID_HANDLE_VALUE;
    if (how == OPEN_EXISTING && !file) return INVALID_HANDLE_VALUE;
    if (how == CREATE_NEW && file) return INVALID_HANDLE_VALUE;
    for (i = 0; !file && i < FAKE_FILES; i++)
        if (!fake_files[i].used) {
            file = &fake_files[i];
            file->used = 1;
            wcscpy(file->path, path);
        }
    if (!file || file->open) abort();
    if (how != OPEN_EXISTING) file->length = 0;
    file->open = 1;
    file->reading = access == GENERIC_READ;
    file->at = 0;
    return file;
}

static BOOL WriteFile(HANDLE handle, const void *data, DWORD size, DWORD *done, void *overlapped)
{
    struct fake_file *file = handle;
    (void)overlapped;
    if (file->reading || file->length + size > sizeof(file->data)) abort();
    if (fake_backup(file->path) && fake_fails("write")) size /= 2;  /* a write cut short */
    if (wcsstr(file->path, L"flash.txt") && fake_fails("report")) { *done = 0; return FALSE; }
    if (wcsstr(file->path, L"flash.txt") && fake_fails("short")) size /= 2;  /* part of a line, "success" */
    memcpy(file->data + file->length, data, size);
    file->length += size;
    *done = size;
    return TRUE;
}

static BOOL ReadFile(HANDLE handle, void *data, DWORD size, DWORD *done, void *overlapped)
{
    struct fake_file *file = handle;
    (void)overlapped;
    if (!file->reading) abort();
    if (size > file->length - file->at) size = (DWORD)(file->length - file->at);
    memcpy(data, file->data + file->at, size);
    file->at += size;
    *done = size;
    return TRUE;
}

static BOOL FlushFileBuffers(HANDLE handle) { (void)handle; return TRUE; }

static BOOL CloseHandle(HANDLE handle)
{
    if (handle == (HANDLE)&fake_lock) return TRUE;
    ((struct fake_file *)handle)->open = 0;
    return TRUE;
}

static BOOL DeleteFileW(const WCHAR *path)
{
    struct fake_file *file = fake_find(path);
    if (!file) return FALSE;
    if (file->open) abort();
    if (!wcscmp(path + wcslen(path) - 4, L".txt") && fake_backup(path) && fake_fails("delfile")) return FALSE;
    file->used = 0;
    return TRUE;
}

static BOOL MoveFileW(const WCHAR *from, const WCHAR *to)
{
    struct fake_file *file = fake_find(from);
    if (!file || file->open || fake_find(to) || fake_fails("move")) return FALSE;
    wcscpy(file->path, to);
    return TRUE;
}

static HANDLE CreateMutexW(void *security, BOOL owned, const WCHAR *name)
{
    (void)security; (void)owned;
    if (wcscmp(name, L"s2amflash")) abort();
    return &fake_lock;
}

static DWORD WaitForSingleObject(HANDLE handle, DWORD ms)
{
    const char *lock = getenv("LOCK");
    if (handle != (HANDLE)&fake_lock || !ms) abort();
    if (lock && !strcmp(lock, "held")) return WAIT_TIMEOUT;
    fake_lock = 1;
    return lock && !strcmp(lock, "abandoned") ? WAIT_ABANDONED : WAIT_OBJECT_0;
}

static BOOL ReleaseMutex(HANDLE handle)
{
    if (handle != (HANDLE)&fake_lock || !fake_lock) abort();
    fake_lock = 0;
    return TRUE;
}
#endif
