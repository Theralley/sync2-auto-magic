/* Manual parked test, no arguments. Fixed read-only Flash keys, Desktop.exe only.
 * Never changes priority or brings any window forward. Fixed new files on USB only. */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include "load_observer_protocol.h"
#include <wchar.h>
#include <string.h>
typedef unsigned long long U64;
typedef HANDLE (WINAPI *Snapshot)(DWORD,DWORD);
typedef BOOL (WINAPI *Process)(HANDLE,LoadProcess*);
typedef BOOL (WINAPI *Thread)(HANDLE,LoadThread*);
typedef BOOL (WINAPI *SnapClose)(HANDLE);
typedef HANDLE (WINAPI *OpenT)(DWORD,BOOL,DWORD);
typedef BOOL (WINAPI *Times)(HANDLE,FILETIME*,FILETIME*,FILETIME*,FILETIME*);
#define GET(h,t,name) ((t)(void(*)(void))GetProcAddressW(h,L##name))
static Snapshot snap; static Process pf,pn; static Thread tf,tn;
static SnapClose sc; static OpenT ot; static Times timesfn;
static HANDLE output=INVALID_HANDLE_VALUE;
static WCHAR tmp[MAX_PATH],csv[MAX_PATH];static DWORD start_tick;
static int allowed(void){return (DWORD)(GetTickCount()-start_tick)<60000u;}
static WCHAR upper(WCHAR c){return c>=L'a'&&c<=L'z'?(WCHAR)(c-32):c;}
static int eq(const WCHAR *a,const WCHAR *b){
    while(*a&&*b&&upper(*a)==upper(*b)){a++;b++;}return !*a&&!*b;
}
static int paths(void){
    static const WCHAR*const mounts[]={L"\\USB Disk",L"\\USB Disk1",L"\\USB Disk2",L"\\USB Disk 2",L"\\USB Disk3"};
    WCHAR module[MAX_PATH],want[MAX_PATH];unsigned i;
    DWORD n=GetModuleFileNameW(NULL,module,MAX_PATH);
    if(!n||n>=MAX_PATH)return 0;
    module[n]=0;
    for(i=0;i<5;i++){
        wcscpy(want,mounts[i]);wcscat(want,L"\\S2AM-DESK\\DESKTEST.EXE");
        if(eq(module,want)){
            wcscpy(tmp,mounts[i]);wcscat(tmp,L"\\S2AM-DESK\\DESK.TMP");
            wcscpy(csv,mounts[i]);wcscat(csv,L"\\S2AM-DESK\\DESK.CSV");return 1;
        }
    }
    return 0;
}
/* Fixed schema, <=15 decimal fields per row. Buffer overflow fails closed. */
static char buf[512];static unsigned used;static int broken;
static void put(const char*s){while(*s){if(used>=sizeof(buf)){broken=1;return;}buf[used++]=*s++;}}
static void num(U64 n){char b[21];unsigned i=20;b[i]=0;do{b[--i]=(char)('0'+n%10);n/=10;}while(n);put(b+i);}
static void fnum(U64 n){put(",");num(n);}
static void fsigned(LONG n){put(",");if(n<0){put("-");num((U64)(-(long long)n));}else num((U64)n);}
static int endline(void){
    unsigned at=0;put("\r\n");if(broken)return 0;
    while(at<used){DWORD got=0;if(!allowed()||!WriteFile(output,buf+at,used-at,&got,NULL)||!got||got>used-at)return 0;at+=got;}
    used=0;return 1;
}
static int config(void){
    const WCHAR*const keys[]={L"ThreadPrio256",L"FastThreadPrio256"};
    const char*const names[]={"ThreadPrio256","FastThreadPrio256"};
    HKEY h=NULL;LONG opened=RegOpenKeyExW(HKEY_LOCAL_MACHINE,L"Software\\Ford\\Flash",0,0,&h);
    unsigned i;int ok=1;
    for(i=0;i<2&&ok;i++){
        DWORD type=0,value=0,size=sizeof(value);LONG error=opened;
        if(!error)error=RegQueryValueExW(h,keys[i],NULL,&type,(BYTE*)&value,&size);
        if(!error&&(type!=REG_DWORD||size!=4))error=13;
        put("config,");put(names[i]);if(error){put(",unknown,,");num((DWORD)error);}
        else{put(",ok,");num(value);put(",0");}
        ok=endline();
    }
    if(!opened&&RegCloseKey(h)!=0)ok=0;
    return ok;
}
static U64 stamp(FILETIME x){return ((U64)x.dwHighDateTime<<32)|x.dwLowDateTime;}
static int is_desktop(const WCHAR*name){
    unsigned i,base=0;for(i=0;i<MAX_PATH&&name[i];i++)if(name[i]==L'\\'||name[i]==L'/')base=i+1;
    return i<MAX_PATH&&eq(name+base,L"Desktop.exe");
}
typedef struct {DWORD tid,error,at;LONG base,delta;U64 creation,k,u;} Row;
static Row rows[128];
static DWORD error_or(DWORD fallback){DWORD e=GetLastError();return e?e:fallback;}
static int sample(DWORD seq){
    DWORD begin=GetTickCount()-start_tick,pid=0,matches=0,count=0,walk=0,error=0,front=0;
    const char*status="ok";HANDLE list;BOOL more;unsigned i;
    LoadProcess p;LoadThread t;HWND fg;
    SetLastError(0);list=snap(0x40000006u,0);
    if(!list||list==INVALID_HANDLE_VALUE){status="snap_error";error=error_or(13);goto emit;}
    memset(&p,0,sizeof(p));p.dwSize=sizeof(p);SetLastError(0);more=pf(list,&p);
    while(more){
        if(!allowed()||++walk>256||p.dwSize!=sizeof(p)||!p.th32ProcessID){status="process_limit";error=13;break;}
        if(is_desktop(p.szExeFile)){pid=p.th32ProcessID;matches++;}
        memset(&p,0,sizeof(p));p.dwSize=sizeof(p);SetLastError(0);more=pn(list,&p);
    }
    if(!error&&!more&&GetLastError()!=18){status="process_error";error=error_or(13);}
    if(error||matches!=1){if(!error)status=matches?"ambiguous":"absent";pid=0;goto close_snapshot;}
    fg=GetForegroundWindow();if(fg&&!GetWindowThreadProcessId(fg,&front))front=0;
    walk=0;memset(&t,0,sizeof(t));t.dwSize=sizeof(t);SetLastError(0);more=tf(list,&t);
    while(more){
        if(!allowed()||++walk>1024||t.dwSize!=sizeof(t)||!t.th32ThreadID){status="thread_limit";error=13;break;}
        if(t.th32OwnerProcessID==pid){
            Row *r;HANDLE th;FILETIME c,e,k,u;
            if(count==128){status="row_limit";error=13;break;}
            for(i=0;i<count;i++)if(rows[i].tid==t.th32ThreadID)break;
            if(i!=count){status="duplicate_tid";error=13;break;}
            r=&rows[count++];memset(r,0,sizeof(*r));r->tid=t.th32ThreadID;r->base=t.tpBasePri;r->delta=t.tpDeltaPri;
            r->at=GetTickCount()-start_tick;SetLastError(0);th=ot(0x40,FALSE,r->tid);
            if(!th)r->error=error_or(13);
            else{
                SetLastError(0);
                if(!timesfn(th,&c,&e,&k,&u))r->error=error_or(13);
                else if(!stamp(c))r->error=13;
                else{r->creation=stamp(c);r->k=stamp(k);r->u=stamp(u);}
                if(!CloseHandle(th)){sc(list);return 0;}
            }
        }
        memset(&t,0,sizeof(t));t.dwSize=sizeof(t);SetLastError(0);more=tn(list,&t);
    }
    if(!error&&!more&&GetLastError()!=18){status="thread_error";error=error_or(13);}
close_snapshot:
    if(!sc(list))return 0;
emit:
    put("round");fnum(seq);fnum(begin);fnum(GetTickCount()-start_tick);put(",");put(status);
    fnum(error);fnum(pid);put(",");put(!front||!pid?"unknown":(front==pid?"desktop":"other"));fnum(count);
    if(!endline())return 0;
    for(i=0;i<count;i++){
        Row*r=&rows[i];put("thread");fnum(seq);fnum(pid);fnum(r->tid);fsigned(r->base);fsigned(r->delta);fnum(r->at);
        if(r->error){put(",,,,");num(r->error);}else{fnum(r->creation);fnum(r->k);fnum(r->u);fnum(0);}
        if(!endline())return 0;
    }
    return FlushFileBuffers(output)!=0;
}
int WINAPI WinMain(HINSTANCE inst,HINSTANCE prev,LPWSTR args,int show){
    HMODULE tool=NULL,core;unsigned i;int ok=0;
    (void)inst;(void)prev;(void)show;start_tick=GetTickCount();
    if((args&&*args)||!paths())goto done;
    SetLastError(0);if(GetFileAttributesW(csv)!=INVALID_FILE_ATTRIBUTES||GetLastError()!=2)goto done;
    core=GetModuleHandleW(L"coredll.dll");tool=LoadLibraryW(L"\\Windows\\toolhelp.dll");if(!core||!tool)goto done;
    snap=GET(tool,Snapshot,"CreateToolhelp32Snapshot");sc=GET(tool,SnapClose,"CloseToolhelp32Snapshot");
    pf=GET(tool,Process,"Process32First");pn=GET(tool,Process,"Process32Next");
    tf=GET(tool,Thread,"Thread32First");tn=GET(tool,Thread,"Thread32Next");
    ot=GET(core,OpenT,"OpenThread");timesfn=GET(core,Times,"GetThreadTimes");
    if(!snap||!sc||!pf||!pn||!tf||!tn||!ot||!timesfn)goto done;
    output=CreateFileW(tmp,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(output==INVALID_HANDLE_VALUE)goto done;
    put("S2AM-DESK,1");if(!endline()||!config())goto done;
    for(i=0;i<7;i++){if(!allowed()||!sample(i))goto done;if(i<6)Sleep(5000);}
    if(!FreeLibrary(tool)){tool=NULL;goto done;}tool=NULL;
    put("complete,7");if(!endline()||!FlushFileBuffers(output))goto done;
    {HANDLE h=output;output=INVALID_HANDLE_VALUE;if(!CloseHandle(h))goto done;}
    if(!MoveFileW(tmp,csv))goto done;
    ok=1;
done:
    if(output!=INVALID_HANDLE_VALUE)CloseHandle(output);
    if(tool)FreeLibrary(tool);
    MessageBoxW(NULL,ok?L"Test finished. DESK.CSV is on the USB. Press OK, close, and return the stick.":
        L"Test not confirmed. Press OK, close, and return the stick. Do not delete files or retry.",
        L"Parked Desktop priority test",MB_OK|(ok?MB_ICONINFORMATION:MB_ICONEXCLAMATION));
    return ok?0:1;
}
