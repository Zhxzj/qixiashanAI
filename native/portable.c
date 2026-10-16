/* Windows 10/11 x64 native cached portable bootstrap. No shell or external runtime.
 * File container: records (u32 pathlen,u64 raw,u64 packed,SHA256,path,data), footer.
 * Per-file XPRESS_HUFF via the Windows Compression API; BCrypt for integrity.
 */
#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <bcrypt.h>
#include <compressapi.h>
#include <shlobj.h>
#include <stdint.h>
#include <stdio.h>
#include <wchar.h>
#include <string.h>
#include <stdlib.h>

#pragma pack(push,1)
typedef struct { char magic[8]; uint64_t offset; uint32_t count; char build[64]; unsigned char digest[32]; } Footer;
typedef struct { uint32_t namesize; uint64_t rawsize, packedsize; unsigned char digest[32]; } Record;
#pragma pack(pop)
static HWND window;
static int quiet=0;
static HANDLE source=INVALID_HANDLE_VALUE;
static wchar_t root[32768], version[32768], stage[32768];
static BCRYPT_ALG_HANDLE algorithm;

static void pump(void) {
    MSG msg;
    while(PeekMessageW(&msg,NULL,0,0,PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
}
static void status(const wchar_t *message) { if(window) {SetWindowTextW(window,message);pump();} }
static int fail(const wchar_t *message) {
    DWORD error=GetLastError();
    wchar_t base[32768],path[32768];
    if(GetEnvironmentVariableW(L"QIXI_USER_DIR",base,32000)) {
        SHCreateDirectoryExW(NULL,base,NULL);
        swprintf(path,32768,L"%ls\\bootstrap-error.txt",base);
        FILE *log=_wfopen(path,L"w, ccs=UTF-8");
        if(log) {fwprintf(log,L"%ls (system error %lu)\n",message,error);fclose(log);}
    }
    if(!quiet) MessageBoxW(NULL,message,L"栖霞山小向导 · 启动失败",MB_OK|MB_ICONERROR);
    return 1;
}
static int read_exact(HANDLE f,void *data,DWORD length) {
    DWORD got;
    return ReadFile(f,data,length,&got,NULL) && got==length;
}
static int seek_to(HANDLE f,uint64_t position) {
    LARGE_INTEGER li;li.QuadPart=position;
    return SetFilePointerEx(f,li,NULL,FILE_BEGIN);
}
static int hash_memory(unsigned char *data,ULONG size,unsigned char out[32]) {
    BCRYPT_HASH_HANDLE h;
    if(BCryptCreateHash(algorithm,&h,NULL,0,NULL,0,0)) return 0;
    int ok=!BCryptHashData(h,data,size,0) && !BCryptFinishHash(h,out,32,0);
    BCryptDestroyHash(h);return ok;
}
static int hash_file(const wchar_t *path,unsigned char out[32]) {
    HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,NULL);
    if(f==INVALID_HANDLE_VALUE) return 0;
    BCRYPT_HASH_HANDLE h;
    if(BCryptCreateHash(algorithm,&h,NULL,0,NULL,0,0)) {CloseHandle(f);return 0;}
    unsigned char buf[65536];DWORD n;int ok=1;
    while(1) {
        if(!ReadFile(f,buf,sizeof(buf),&n,NULL)) {ok=0;break;}
        if(!n) break;
        if(BCryptHashData(h,buf,n,0)) {ok=0;break;}
    }
    if(BCryptFinishHash(h,out,32,0)) ok=0;
    BCryptDestroyHash(h);CloseHandle(f);return ok;
}
static int make_dirs(wchar_t *path) {
    /* Win32 extended paths avoid MAX_PATH failures in deeply nested user caches. */
    wchar_t copy[32768];wcscpy(copy,path);
    size_t start=!wcsncmp(copy,L"\\\\?\\",4)?7:3;
    for(wchar_t *p=copy+start;*p;p++) if(*p==L'\\') {
        *p=0;
        if(!CreateDirectoryW(copy,NULL) && GetLastError()!=ERROR_ALREADY_EXISTS) return 0;
        *p=L'\\';
    }
    return CreateDirectoryW(copy,NULL) || GetLastError()==ERROR_ALREADY_EXISTS;
}
/* Never follow a junction or symlink while cleaning the two explicit cache roots. */
static int clean_tree(const wchar_t *path,int deleting) {
    DWORD attrs=GetFileAttributesW(path);
    if(attrs==INVALID_FILE_ATTRIBUTES) return 1;
    if(attrs&FILE_ATTRIBUTE_REPARSE_POINT) return 0;
    wchar_t pattern[32768];swprintf(pattern,32768,L"%ls\\*",path);
    WIN32_FIND_DATAW data;HANDLE find=FindFirstFileW(pattern,&data);
    if(find!=INVALID_HANDLE_VALUE) {
        do {
            if(!wcscmp(data.cFileName,L".") || !wcscmp(data.cFileName,L"..")) continue;
            if(data.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT) {FindClose(find);return 0;}
            wchar_t child[32768];swprintf(child,32768,L"%ls\\%ls",path,data.cFileName);
            int ok=1;
            if(data.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY) ok=clean_tree(child,deleting);
            else if(deleting) ok=DeleteFileW(child);
            if(!ok) {FindClose(find);return 0;}
        } while(FindNextFileW(find,&data));
        FindClose(find);
    }
    return !deleting || RemoveDirectoryW(path);
}
static int safe_path(const char *name) {
    if(!*name || name[0]=='/' || name[0]=='\\' || strstr(name,"..") || strchr(name,':')) return 0;
    return !strchr(name,'\\'); /* canonical names contain forward slashes only */
}
static int enough_space(Footer *footer) {
    if(!make_dirs(root) || !seek_to(source,footer->offset)) return 0;
    uint64_t needed=16*1024*1024;
    for(uint32_t i=0;i<footer->count;i++) {
        Record entry;LARGE_INTEGER skip;
        if(!read_exact(source,&entry,sizeof(entry)) || !entry.namesize || entry.namesize>=2048 || entry.rawsize>536870912 || entry.packedsize>536870912) return 0;
        needed+=entry.rawsize;
        skip.QuadPart=entry.namesize+entry.packedsize;
        if(!SetFilePointerEx(source,skip,NULL,FILE_CURRENT)) return 0;
    }
    ULARGE_INTEGER freeBytes;
    return GetDiskFreeSpaceExW(root,&freeBytes,NULL,NULL) && freeBytes.QuadPart>=needed;
}
static int unpack(Footer *footer,int verify) {
    if(!seek_to(source,footer->offset)) return 0;
    DECOMPRESSOR_HANDLE decompressor;
    if(!CreateDecompressor(COMPRESS_ALGORITHM_XPRESS_HUFF,NULL,&decompressor)) return 0;
    int ok=1;
    for(uint32_t i=0;i<footer->count;i++) {
        Record entry;char name[2048];wchar_t wname[2048],path[32768];
        if(!read_exact(source,&entry,sizeof(entry)) || !entry.namesize || entry.namesize>=sizeof(name) || entry.rawsize>536870912 || entry.packedsize>536870912) {ok=0;break;}
        if(!read_exact(source,name,entry.namesize)) {ok=0;break;}
        name[entry.namesize]=0;
        if(strlen(name)!=entry.namesize || !safe_path(name) || !MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name,-1,wname,2048)) {ok=0;break;}
        for(wchar_t *ch=wname;*ch;ch++) if(*ch==L'/') *ch=L'\\';
        if(swprintf(path,32768,L"%ls\\%ls",verify?version:stage,wname)<0) {ok=0;break;}
        if(verify) {
            unsigned char digest[32];LARGE_INTEGER skip;skip.QuadPart=entry.packedsize;
            if(!hash_file(path,digest) || memcmp(digest,entry.digest,32) || !SetFilePointerEx(source,skip,NULL,FILE_CURRENT)) {ok=0;break;}
        } else {
            unsigned char *packed=malloc((size_t)entry.packedsize+1),*raw=malloc((size_t)entry.rawsize+1),digest[32];
            SIZE_T decoded=0;
            int valid=packed && raw && read_exact(source,packed,(DWORD)entry.packedsize);
            if(valid && entry.rawsize) valid=Decompress(decompressor,packed,(SIZE_T)entry.packedsize,raw,(SIZE_T)entry.rawsize,&decoded) && decoded==entry.rawsize;
            if(valid) valid=hash_memory(raw,(ULONG)entry.rawsize,digest) && !memcmp(digest,entry.digest,32);
            if(valid) {
                wchar_t *sep=wcsrchr(path,L'/');wchar_t *sep2=wcsrchr(path,L'\\');if(!sep || (sep2 && sep2>sep)) sep=sep2;
                if(sep) {*sep=0;valid=make_dirs(path);*sep=L'\\';}
                HANDLE file=CreateFileW(path,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);DWORD written=0;
                valid=valid && file!=INVALID_HANDLE_VALUE;
                if(valid) valid=WriteFile(file,raw,(DWORD)entry.rawsize,&written,NULL) && written==entry.rawsize && FlushFileBuffers(file);
                if(file!=INVALID_HANDLE_VALUE) CloseHandle(file);
            }
            free(packed);free(raw);
            if(!valid) {ok=0;break;}
        }
        pump();
    }
    CloseDecompressor(decompressor);return ok;
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE prev,LPWSTR args,int show) {
    (void)instance;(void)prev;(void)show;
    quiet=GetEnvironmentVariableW(L"QIXI_NO_BROWSER",NULL,0)>0 || wcsstr(args,L"--check")!=NULL;
    if(!quiet) {
        window=CreateWindowExW(WS_EX_TOPMOST,L"STATIC",L"栖霞山小向导 · 正在检查运行环境…",WS_OVERLAPPED|WS_CAPTION|WS_VISIBLE, CW_USEDEFAULT,CW_USEDEFAULT,540,90,NULL,NULL,instance,NULL);
        SendMessageW(window,WM_SETICON,ICON_BIG,(LPARAM)LoadIconW(instance,MAKEINTRESOURCEW(1)));
        pump();
    }
    wchar_t self[32768];GetModuleFileNameW(NULL,self,32768);
    source=CreateFileW(self,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_FLAG_SEQUENTIAL_SCAN,NULL);
    LARGE_INTEGER size;
    Footer footer;
    if(source==INVALID_HANDLE_VALUE || !GetFileSizeEx(source,&size) || size.QuadPart<(LONGLONG)sizeof(Footer) || !seek_to(source,size.QuadPart-sizeof(Footer)) || !read_exact(source,&footer,sizeof(Footer)) || memcmp(footer.magic,"QIXIPK02",8) || footer.offset>=(uint64_t)size.QuadPart-sizeof(Footer) || !footer.count || footer.count>50000) return fail(L"文件不完整，请重新获取便携 EXE。");
    for(int i=0;i<64;i++) if(!((footer.build[i]>='0'&&footer.build[i]<='9')||(footer.build[i]>='a'&&footer.build[i]<='f'))) return fail(L"版本清单无效。");
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,NULL,0)) return fail(L"系统校验组件不可用。");
    /* The entire container is checked before trusting its path and file digests. */
    if(!seek_to(source,footer.offset)) return fail(L"无法读取负载。");
    BCRYPT_HASH_HANDLE contentHash;BCryptCreateHash(algorithm,&contentHash,NULL,0,NULL,0,0);
    uint64_t remaining=(uint64_t)size.QuadPart-sizeof(Footer)-footer.offset;
    unsigned char buffer[65536],digest[32];
    while(remaining) {DWORD n=remaining>sizeof(buffer)?sizeof(buffer):(DWORD)remaining;if(!read_exact(source,buffer,n)||BCryptHashData(contentHash,buffer,n,0)) return fail(L"负载校验失败。");remaining-=n;pump();}
    BCryptFinishHash(contentHash,digest,32,0);BCryptDestroyHash(contentHash);
    if(memcmp(digest,footer.digest,32)) return fail(L"便携文件已损坏，请重新获取。");
    if(!GetEnvironmentVariableW(L"QIXI_USER_DIR",root,32768)) {
        if(!GetEnvironmentVariableW(L"LOCALAPPDATA",root,32000)) return fail(L"无法找到当前用户缓存目录。");
        wcscat(root,L"\\QixiGuide");
    }
    if(wcsncmp(root,L"\\\\?\\",4)) {
        wchar_t full[32768];
        if(!GetFullPathNameW(root,32760,full,NULL) || full[1]!=L':') return fail(L"用户缓存必须位于本机磁盘的绝对路径。");
        swprintf(root,32768,L"\\\\?\\%ls",full);
    }
    wchar_t build[65];for(int i=0;i<64;i++) build[i]=(wchar_t)footer.build[i];build[64]=0;
    swprintf(version,32768,L"%ls\\versions\\%ls",root,build);
    swprintf(stage,32768,L"%ls\\staging\\%ls-%lu-%llu",root,build,GetCurrentProcessId(),GetTickCount64());
    unsigned char rootHash[32];hash_memory((unsigned char*)root,(ULONG)(wcslen(root)*sizeof(wchar_t)),rootHash);
    wchar_t mutexName[100];swprintf(mutexName,100,L"Local\\QixiGuideUnpack-%02x%02x%02x%02x%02x%02x%02x%02x",rootHash[0],rootHash[1],rootHash[2],rootHash[3],rootHash[4],rootHash[5],rootHash[6],rootHash[7]);
    HANDLE mutex=CreateMutexW(NULL,FALSE,mutexName);
    DWORD locked;
    while((locked=WaitForSingleObject(mutex,100))==WAIT_TIMEOUT) pump();
    if(locked!=WAIT_OBJECT_0 && locked!=WAIT_ABANDONED) return fail(L"无法锁定缓存，请重试。");
    if(wcsstr(args,L"--clean-cache")) {
        wchar_t path[32768], cache[32768], pending[32768];
        swprintf(path,32768,L"%ls\\instance",root);make_dirs(path);
        swprintf(path,32768,L"%ls\\instance\\host.lock",root);
        HANDLE host=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_ALWAYS,0,NULL);
        OVERLAPPED overlap={0};
        if(host==INVALID_HANDLE_VALUE || !LockFileEx(host,LOCKFILE_EXCLUSIVE_LOCK|LOCKFILE_FAIL_IMMEDIATELY,0,1,0,&overlap)) return fail(L"请先退出全部应用实例，再清理缓存。");
        swprintf(cache,32768,L"%ls\\versions",root);swprintf(pending,32768,L"%ls\\staging",root);
        int cleaned=clean_tree(cache,0) && clean_tree(pending,0) && clean_tree(cache,1) && clean_tree(pending,1);
        CloseHandle(host);ReleaseMutex(mutex);CloseHandle(mutex);
        if(!cleaned) return fail(L"缓存包含正在使用的文件或异常链接，未能完成清理。配置和行程保留。");
        if(!quiet) MessageBoxW(NULL,L"版本缓存已清理，配置、行程和日志已保留。",L"栖霞山小向导",MB_OK);
        return 0;
    }
    if(!unpack(&footer,1)) {
        status(L"栖霞山小向导 · 首次准备环境，请稍候…");
        if(!enough_space(&footer)) {ReleaseMutex(mutex);return fail(L"用户目录可用空间不足或无法访问。请清理磁盘后重试。");}
        if(!make_dirs(stage) || !unpack(&footer,0)) {ReleaseMutex(mutex);return fail(L"环境展开失败。请检查用户目录权限或可用空间，然后重新打开。");}
        wchar_t versions[32768];swprintf(versions,32768,L"%ls\\versions",root);make_dirs(versions);
        if(GetFileAttributesW(version)!=INVALID_FILE_ATTRIBUTES) {
            wchar_t broken[32768];swprintf(broken,32768,L"%ls.corrupt-%llu",version,GetTickCount64());
            if(!MoveFileExW(version,broken,MOVEFILE_WRITE_THROUGH)) {ReleaseMutex(mutex);return fail(L"缓存正在使用，无法修复。请先退出旧实例后重试。");}
        }
        if(!MoveFileExW(stage,version,MOVEFILE_WRITE_THROUGH)) {ReleaseMutex(mutex);return fail(L"无法完成版本缓存切换，请重试。");}
    }
    ReleaseMutex(mutex);CloseHandle(mutex);CloseHandle(source);BCryptCloseAlgorithmProvider(algorithm,0);
    status(L"栖霞山小向导 · 正在启动…");
    SetEnvironmentVariableW(L"QIXI_BUILD_ID",build);
    SetEnvironmentVariableW(L"QIXI_USER_DIR",root);
    wchar_t eventName[128];swprintf(eventName,128,L"Local\\QixiGuideReady-%lu-%llu",GetCurrentProcessId(),GetTickCount64());
    HANDLE ready=CreateEventW(NULL,TRUE,FALSE,eventName);
    SetEnvironmentVariableW(L"QIXI_READY_EVENT",eventName);
    wchar_t python[32768],command[32768];
    swprintf(python,32768,L"%ls\\runtime\\python\\pythonw.exe",version);
    swprintf(command,32768,L"\"%ls\" -B \"%ls\\launcher.py\" %ls",python,version,args);
    STARTUPINFOW startup={0};startup.cb=sizeof(startup);PROCESS_INFORMATION process;
    if(!CreateProcessW(python,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,version,&startup,&process)) return fail(L"无法启动自带运行时，请检查文件是否被系统隔离。诊断文件位于用户缓存 logs 目录。");
    HANDLE waits[2]={process.hProcess,ready};
    while(1) {
        DWORD wait=WaitForMultipleObjects(2,waits,FALSE,100);
        if(wait==WAIT_OBJECT_0 || wait==WAIT_OBJECT_0+1) break;
        pump();
    }
    if(window) {DestroyWindow(window);window=NULL;}
    WaitForSingleObject(process.hProcess,INFINITE);
    DWORD code=1;GetExitCodeProcess(process.hProcess,&code);
    CloseHandle(process.hThread);CloseHandle(process.hProcess);CloseHandle(ready);
    return (int)code;
}
