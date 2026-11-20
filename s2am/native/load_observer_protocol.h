#ifndef S2AM_LOAD_OBSERVER_PROTOCOL_H
#define S2AM_LOAD_OBSERVER_PROTOCOL_H
#include <windows.h>
#define LOAD_ROUNDS 60u
#define LOAD_PERIOD 5000u
#define LOAD_THREADS 512u
#define LOAD_PROCESSES 256u
#define LOAD_BUDGET 360000u
/* CE 6 Toolhelp ABI, also used by the existing car-tested load collector. */
typedef struct {
    DWORD dwSize,cntUsage,th32ProcessID,th32DefaultHeapID,th32ModuleID,cntThreads;
    DWORD th32ParentProcessID; LONG pcPriClassBase; DWORD dwFlags;
    WCHAR szExeFile[MAX_PATH]; DWORD th32MemoryBase,th32AccessKey;
} LoadProcess;
typedef struct {
    DWORD dwSize,cntUsage,th32ThreadID,th32OwnerProcessID;
    LONG tpBasePri,tpDeltaPri; DWORD dwFlags,th32AccessKey,th32CurrentProcessID;
} LoadThread;
#ifndef S2AM_LOAD_HOST_TEST
typedef char load_process_abi[(sizeof(LoadProcess)==564)?1:-1];
typedef char load_thread_abi[(sizeof(LoadThread)==36)?1:-1];
#endif
#endif
