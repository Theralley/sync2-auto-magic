/* Standalone ordinary-API observer. No spin, driver, PMU, MMIO, registry,
 * configuration/priority changes, screenshots or copied logs. See LOAD-OBSERVER-V1.
 * One thread, fixed caps, RAM collection before output, no overwrite/retry cleanup.
 * A blocked OS call cannot be interrupted by this application. */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include "load_observer_protocol.h"
#include <string.h>
#include <wchar.h>

typedef unsigned long long U64;
typedef HANDLE (WINAPI *SnapshotFn)(DWORD,DWORD);
typedef BOOL (WINAPI *ProcessFn)(HANDLE,LoadProcess*);
typedef BOOL (WINAPI *ThreadFn)(HANDLE,LoadThread*);
typedef BOOL (WINAPI *SnapshotCloseFn)(HANDLE);
typedef HANDLE (WINAPI *OpenThreadFn)(DWORD,BOOL,DWORD);
typedef BOOL (WINAPI *TimesFn)(HANDLE,FILETIME*,FILETIME*,FILETIME*,FILETIME*);
typedef DWORD (WINAPI *IdleFn)(void);
static SnapshotFn snapshot;
static ProcessFn process_first,process_next;
static ThreadFn thread_first,thread_next;
static SnapshotCloseFn snapshot_close;
static OpenThreadFn open_thread;
static TimesFn thread_times;
static IdleFn idle_time;
#define LOOKUP(m,t,n) ((t)(void(*)(void))GetProcAddressW(m,L##n))

typedef struct {
    DWORD pid,tid,status,error; LONG base,delta;
    U64 creation,kernel,user,before,after;
} Reading;
typedef struct { DWORD pid; char name[64]; } Process;
typedef struct {
    U64 before,after,idle_before,idle_after;
    DWORD idle_ok,idle_value,idle_error,thread_error,thread_truncated;
    DWORD process_error,process_truncated,process_count,thread_count;
    Reading self,threads[LOAD_THREADS]; Process processes[LOAD_PROCESSES];
} Round;
static Round data;
static DWORD started,self_pid,self_tid,io_failed,total_bytes,line_bytes;
static U64 last_qpc;
static HANDLE output=INVALID_HANDLE_VALUE;
static char buffer[4096]; static unsigned used;
static WCHAR scratch[MAX_PATH],published[MAX_PATH];
static const char *const statuses[]={"ok","open_fail","times_fail","no_creation"};

static DWORD error_now(void) { return GetLastError(); }
static DWORD enum_error(void) { DWORD e=error_now(); return e==18?0:(e?e:13); }
static int admitted(void) { return (DWORD)(GetTickCount()-started)<LOAD_BUDGET; }
static int stamp(U64 *v) {
    LARGE_INTEGER q;
    if(!admitted()) return 0;
    q.QuadPart=0;
    if(!QueryPerformanceCounter(&q)||q.QuadPart<=0||(U64)q.QuadPart<last_qpc) return 0;
    *v=(U64)q.QuadPart; last_qpc=*v; return 1;
}
static U64 filetime(FILETIME t) { return ((U64)t.dwHighDateTime<<32)|t.dwLowDateTime; }

static void flush_buffer(void) {
    DWORD at=0;
    if(io_failed) return;
    while(at<used) {
        DWORD got=0;
        if(!WriteFile(output,buffer+at,used-at,&got,NULL)||!got||got>used-at) {
            io_failed=1; return;
        }
        at+=got;
    }
    used=0;
}
static void put(const char *s) {
    while(*s&&!io_failed) {
        if(total_bytes>=8u*1024u*1024u||line_bytes>=256u) { io_failed=1; return; }
        if(used==sizeof(buffer)) flush_buffer();
        if(io_failed) return;
        buffer[used++]=*s++; total_bytes++; line_bytes++;
    }
}
static void number(U64 n) {
    char out[21]; unsigned i=20; out[i]=0;
    do { out[--i]=(char)('0'+n%10); n/=10; } while(n);
    put(out+i);
}
static void field(U64 n) { put(","); number(n); }
static void signed_field(LONG n) {
    put(","); if(n<0) { put("-"); number((U64)(-(long long)n)); }
    else number((U64)n);
}
static void line(void) { put("\r\n"); line_bytes=0; }
static int durable(void) {
    flush_buffer();
    if(io_failed||!FlushFileBuffers(output)) { io_failed=1; return 0; }
    return 1;
}

/* QPC brackets the entire read attempt, including a failed OpenThread and CloseHandle.
 * Failed timer or resource cleanup aborts publication, never yields zero brackets. */
static int read_thread(Reading *r) {
    HANDLE h; FILETIME c,e,k,u;
    if(!stamp(&r->before)) return 0;
    memset(&c,0,sizeof(c)); memset(&e,0,sizeof(e));
    memset(&k,0,sizeof(k)); memset(&u,0,sizeof(u));
    SetLastError(0); h=open_thread(0x40,FALSE,r->tid);
    if(!h) { r->status=1; r->error=error_now(); }
    else {
        SetLastError(0);
        if(!thread_times(h,&c,&e,&k,&u)) { r->status=2; r->error=error_now(); }
        else {
            r->creation=filetime(c); r->kernel=filetime(k); r->user=filetime(u);
            r->status=r->creation?0:3;
        }
        if(!CloseHandle(h)) return 0;
    }
    return stamp(&r->after);
}
static int namechar(WCHAR c) {
    return (c>=L'a'&&c<=L'z')||(c>=L'A'&&c<=L'Z')||
           (c>=L'0'&&c<=L'9')||c==L'_'||c==L'-'||c==L'.'||c==L'?';
}
static void basename(char out[64],const WCHAR *name) {
    unsigned i,start=0,at=0;
    for(i=0;i<MAX_PATH&&name[i];i++) if(name[i]==L'\\'||name[i]==L'/') start=i+1;
    for(i=start;i<MAX_PATH&&name[i]&&at<63;i++) out[at++]=namechar(name[i])?(char)name[i]:'?';
    if(!at) { out[at++]='?'; }
    out[at]=0;
}
static int collect(void) {
    HANDLE list; LoadProcess p; LoadThread t; BOOL have; unsigned i;
    memset(&data,0,sizeof(data));
    if(!stamp(&data.before)) return 0;
    data.self.pid=self_pid; data.self.tid=self_tid;
    if(!read_thread(&data.self)||!stamp(&data.idle_before)) return 0;
    SetLastError(0);
    if(!idle_time) { data.idle_error=127; }
    else {
        data.idle_value=idle_time(); data.idle_error=error_now();
        if(data.idle_value!=0xffffffffu) { data.idle_ok=1; data.idle_error=0; }
    }
    if(!stamp(&data.idle_after)) return 0;
    SetLastError(0); list=snapshot(0x40000006u,0);
    if(list==INVALID_HANDLE_VALUE||!list) {
        data.thread_error=data.process_error=error_now();
        if(!data.thread_error) data.thread_error=data.process_error=13;
        return stamp(&data.after);
    }
    memset(&p,0,sizeof(p)); p.dwSize=sizeof(p);
    SetLastError(0); have=process_first(list,&p);
    while(have) {
        if(!admitted()) goto fatal;
        if(data.process_count==LOAD_PROCESSES) { data.process_truncated=1; break; }
        if(!p.th32ProcessID||p.dwSize!=sizeof(p)) { data.process_error=13; break; }
        for(i=0;i<data.process_count;i++) if(data.processes[i].pid==p.th32ProcessID) break;
        if(i<data.process_count) { data.process_error=13; break; }
        data.processes[data.process_count].pid=p.th32ProcessID;
        basename(data.processes[data.process_count++].name,p.szExeFile);
        memset(&p,0,sizeof(p)); p.dwSize=sizeof(p);
        SetLastError(0); have=process_next(list,&p);
    }
    if(!have) data.process_error=enum_error();
    memset(&t,0,sizeof(t)); t.dwSize=sizeof(t);
    SetLastError(0); have=thread_first(list,&t);
    while(have) {
        Reading *r;
        if(!admitted()) goto fatal;
        if(data.thread_count==LOAD_THREADS) { data.thread_truncated=1; break; }
        if(!t.th32ThreadID||!t.th32OwnerProcessID||t.dwSize!=sizeof(t)) { data.thread_error=13; break; }
        for(i=0;i<data.thread_count;i++) if(data.threads[i].tid==t.th32ThreadID) break;
        if(i<data.thread_count) { data.thread_error=13; break; }
        r=&data.threads[data.thread_count]; r->pid=t.th32OwnerProcessID;
        r->tid=t.th32ThreadID; r->base=t.tpBasePri; r->delta=t.tpDeltaPri;
        if(!read_thread(r)) goto fatal;
        data.thread_count++;
        memset(&t,0,sizeof(t)); t.dwSize=sizeof(t);
        SetLastError(0); have=thread_next(list,&t);
    }
    if(!have) data.thread_error=enum_error();
    if(!snapshot_close(list)) return 0;
    return stamp(&data.after);
fatal:
    snapshot_close(list); return 0;
}
static void reading(const Reading *r,int is_self,DWORD seq) {
    put(is_self?"self":"thread"); field(seq);
    if(!is_self) { field(r->pid); field(r->tid); }
    field(r->creation); field(r->kernel); field(r->user); field(r->before); field(r->after);
    if(!is_self) { signed_field(r->base); signed_field(r->delta); }
    put(","); put(statuses[r->status]); field(r->error); line();
}
static int emit(DWORD seq) {
    unsigned i; DWORD counts[4]={0,0,0,0};
    put("round"); field(seq); field(data.before); field(data.after);
    field(data.thread_error); field(data.thread_truncated);
    field(data.process_error); field(data.process_truncated); line();
    reading(&data.self,1,seq);
    put("idle"); field(seq); field(data.idle_ok); field(data.idle_before);
    field(data.idle_after); field(data.idle_value); field(data.idle_error); line();
    for(i=0;i<data.process_count;i++) {
        put("process"); field(seq); field(data.processes[i].pid);
        put(","); put(data.processes[i].name); line();
    }
    for(i=0;i<data.thread_count;i++) {
        counts[data.threads[i].status]++; reading(&data.threads[i],0,seq);
    }
    put("endround"); field(seq); field(data.thread_count);
    for(i=0;i<4;i++) { field(counts[i]); }
    line();
    return durable();
}
static int paths(void) {
    WCHAR path[MAX_PATH]; DWORD n; unsigned i,last=0; int found=0;
    n=GetModuleFileNameW(NULL,path,MAX_PATH);
    if(!n||n>=MAX_PATH) return 0;
    for(i=0;i<n;i++) if(path[i]==L'\\') { last=i+1; found=1; }
    if(!found||last+9>=MAX_PATH) return 0;
    path[last]=0; wcscpy(scratch,path); wcscpy(published,path);
    wcscat(scratch,L"LOAD.TMP"); wcscat(published,L"LOAD.CSV"); return 1;
}
int WINAPI WinMain(HINSTANCE instance,HINSTANCE prior,LPWSTR command,int show) {
    HMODULE core=NULL,toolhelp=NULL; LARGE_INTEGER freq,endfreq;
    DWORD seq,attrs; U64 previous=0; int ok=0;
    (void)instance; (void)prior; (void)show;
    started=GetTickCount();
    if((command&&*command)||!paths()) goto done;
    self_pid=GetCurrentProcessId(); self_tid=GetCurrentThreadId();
    if(!self_pid||!self_tid) goto done;
    SetLastError(0); attrs=GetFileAttributesW(published);
    if(attrs!=INVALID_FILE_ATTRIBUTES||GetLastError()!=2) goto done;
    core=GetModuleHandleW(L"coredll.dll"); toolhelp=LoadLibraryW(L"\\Windows\\toolhelp.dll");
    if(!core||!toolhelp) goto done;
    snapshot=LOOKUP(toolhelp,SnapshotFn,"CreateToolhelp32Snapshot");
    process_first=LOOKUP(toolhelp,ProcessFn,"Process32First");
    process_next=LOOKUP(toolhelp,ProcessFn,"Process32Next");
    thread_first=LOOKUP(toolhelp,ThreadFn,"Thread32First");
    thread_next=LOOKUP(toolhelp,ThreadFn,"Thread32Next");
    snapshot_close=LOOKUP(toolhelp,SnapshotCloseFn,"CloseToolhelp32Snapshot");
    open_thread=LOOKUP(core,OpenThreadFn,"OpenThread");
    thread_times=LOOKUP(core,TimesFn,"GetThreadTimes"); idle_time=LOOKUP(core,IdleFn,"GetIdleTime");
    if(!snapshot||!process_first||!process_next||!thread_first||!thread_next||
       !snapshot_close||!open_thread||!thread_times) goto done;
    freq.QuadPart=0;
    if(!QueryPerformanceFrequency(&freq)||freq.QuadPart<1||freq.QuadPart>1000000000) goto done;
    output=CreateFileW(scratch,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(output==INVALID_HANDLE_VALUE) goto done;
    put("S2AM-LOAD,1"); line(); put("meta,60,5000,512,256"); field(self_pid); field(self_tid); line();
    put("frequency,start"); field((U64)freq.QuadPart); line();
    if(!durable()) goto done;
    for(seq=0;seq<LOAD_ROUNDS;seq++) {
        if(!admitted()||!collect()||data.before<=previous||!emit(seq)) goto done;
        previous=data.after;
        if(seq+1<LOAD_ROUNDS) Sleep(LOAD_PERIOD);
    }
    endfreq.QuadPart=0;
    if(!admitted()||!QueryPerformanceFrequency(&endfreq)||endfreq.QuadPart!=freq.QuadPart) goto done;
    /* Release the dynamic module BEFORE footer publication: failed cleanup is not success. */
    if(!FreeLibrary(toolhelp)) { toolhelp=NULL; goto done; } toolhelp=NULL;
    put("frequency,end"); field((U64)endfreq.QuadPart); line(); put("complete,60"); line();
    if(!durable()) goto done;
    { HANDLE h=output; output=INVALID_HANDLE_VALUE; if(!CloseHandle(h)) goto done; }
    if(!MoveFileW(scratch,published)) goto done;
    ok=1;
done:
    if(output!=INVALID_HANDLE_VALUE) { CloseHandle(output); output=INVALID_HANDLE_VALUE; }
    if(toolhelp) FreeLibrary(toolhelp);
    MessageBoxW(NULL,ok?L"Logging finished. LOAD.CSV is saved. Do not run again; return the USB.":
                L"Logging did not complete. Do not run again; return the USB for analysis.",
                L"SYNC 2 load logger",MB_OK|(ok?MB_ICONINFORMATION:MB_ICONEXCLAMATION));
    return ok?0:1;
}
