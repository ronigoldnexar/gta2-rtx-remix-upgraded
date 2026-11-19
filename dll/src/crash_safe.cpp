// FIX-HANG-1: see crash_safe.h. Nothing below the "report" line may use the CRT heap, stdio, C++ runtime or a lock.
#include "crash_safe.h"

#include <tlhelp32.h>

#include <cstdint>
#include <cstring>

#include "log.h"
#include "thread_watch.h"

namespace gta2dx9 {
namespace crash {
namespace {

// ---- state set up by Init (allocation allowed there) ------------------------------------------------
HANDLE g_fatalFile = INVALID_HANDLE_VALUE;   // gta2dx9_fatal.log, appended
HANDLE g_mainLog = INVALID_HANDLE_VALUE;     // the log's own OS handle (not ours to close)
char g_exeDir[MAX_PATH] = {};                // with the trailing backslash
DWORD g_pid = 0;
DWORD g_gameTid = 0;
volatile DWORD* g_beat = nullptr;
struct HistEntry { DWORD tick; LONG suspend; ULONG64 cycles; };
constexpr int kHist = 64;
HistEntry g_hist[kHist];
int g_histN = 0;


DWORD g_killMs = 6000, g_busyKillMs = 60000, g_dumpMode = 1;
typedef LONG(NTAPI* NtGetNextThreadFn)(HANDLE, HANDLE, ACCESS_MASK, ULONG, ULONG, PHANDLE);
typedef BOOL(WINAPI* QueryThreadCycleTimeFn)(HANDLE, PULONG64);
typedef LONG(NTAPI* NtQueryInformationThreadFn)(HANDLE, ULONG, PVOID, ULONG, PULONG);
NtQueryInformationThreadFn g_ntQueryThread = nullptr;
NtGetNextThreadFn g_ntGetNextThread = nullptr;
uintptr_t g_waitStubs[5] = {};   // NtWaitForSingleObject, NtWaitForMultipleObjects, NtDelayExecution, NtSignalAndWaitForSingleObject, NtWaitForMultipleObjects32
QueryThreadCycleTimeFn g_queryCycles = nullptr;
volatile DWORD g_serverPid = 0;

// ---- the writer: one static buffer, flushed with WriteFile ------------------------------------------
constexpr size_t kBuf = 32768;
char g_buf[kBuf];
size_t g_n = 0;
volatile LONG g_reporting = 0;
volatile DWORD g_reportingTid = 0;
volatile LONG g_faultLines = 0;
volatile LONG g_debugLines = 0;

void Flush() {
    if (!g_n) return;
    DWORD wrote = 0;
    if (g_fatalFile != INVALID_HANDLE_VALUE) WriteFile(g_fatalFile, g_buf, static_cast<DWORD>(g_n), &wrote, nullptr);
    if (g_mainLog != INVALID_HANDLE_VALUE) WriteFile(g_mainLog, g_buf, static_cast<DWORD>(g_n), &wrote, nullptr);
    g_n = 0;
}

void Put(const char* s) {
    while (*s) {
        if (g_n + 2 >= kBuf) Flush();
        g_buf[g_n++] = *s++;
    }
}

void PutChar(char c) {
    if (g_n + 2 >= kBuf) Flush();
    g_buf[g_n++] = c;
}

void Hex(uint32_t v, int digits = 8) {
    static const char d[] = "0123456789ABCDEF";
    for (int i = digits - 1; i >= 0; --i) PutChar(d[(v >> (i * 4)) & 15]);
}

void Dec(int64_t v) {
    char t[24];
    int n = 0;
    uint64_t u = v < 0 ? static_cast<uint64_t>(-v) : static_cast<uint64_t>(v);
    if (v < 0) PutChar('-');
    do { t[n++] = static_cast<char>('0' + u % 10); u /= 10; } while (u && n < 22);
    while (n) PutChar(t[--n]);
}

// "[HH:MM:SS.mmm] PREFIX" like Log() does.
void LineStart(const char* prefix) {
    SYSTEMTIME t;
    GetLocalTime(&t);
    PutChar('[');
    Dec(t.wHour / 10); Dec(t.wHour % 10); PutChar(':');
    Dec(t.wMinute / 10); Dec(t.wMinute % 10); PutChar(':');
    Dec(t.wSecond / 10); Dec(t.wSecond % 10); PutChar('.');
    Dec(t.wMilliseconds / 100); Dec((t.wMilliseconds / 10) % 10); Dec(t.wMilliseconds % 10);
    Put("] ");
    Put(prefix);
}
void LineEnd() { PutChar('\n'); if (g_n > kBuf - 2048) Flush(); }

// ---- reading memory without a heap or an exception handler -----------------------------------------
bool Readable(const void* p, size_t n) {
    const uintptr_t a = reinterpret_cast<uintptr_t>(p);
    if (a < 0x10000 || a + n < a) return false;
    MEMORY_BASIC_INFORMATION m;
    if (!VirtualQuery(p, &m, sizeof(m))) return false;
    if (m.State != MEM_COMMIT || (m.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    const uintptr_t end = reinterpret_cast<uintptr_t>(m.BaseAddress) + m.RegionSize;
    if (a + n <= end) return true;
    // The next region may continue (a stack is several regions of equal protection).
    return Readable(reinterpret_cast<const void*>(end), a + n - end);
}

struct Mod { uintptr_t base, end; char name[28]; };
constexpr int kMods = 192;
Mod g_mods[kMods];
int g_modCount = 0;

// The loader's module list straight from the PEB (no loader lock, no heap). 32-bit LDR_DATA_TABLE_ENTRY:
// InMemoryOrderLinks +8, DllBase +0x18, SizeOfImage +0x20, BaseDllName (len +0x2C, buffer +0x30).
void CollectModules() {
    g_modCount = 0;
    uintptr_t peb = 0;
    __asm__ volatile("movl %%fs:0x30, %0" : "=r"(peb));
    if (!Readable(reinterpret_cast<void*>(peb), 0x10)) return;
    const uintptr_t ldr = *reinterpret_cast<const uintptr_t*>(peb + 0x0C);
    if (!Readable(reinterpret_cast<void*>(ldr), 0x20)) return;
    const uintptr_t head = ldr + 0x14;
    uintptr_t e = *reinterpret_cast<const uintptr_t*>(head);
    for (int guard = 0; e && e != head && g_modCount < kMods && guard < 1024; ++guard) {
        if (!Readable(reinterpret_cast<void*>(e - 8), 0x40)) break;
        const uint8_t* entry = reinterpret_cast<const uint8_t*>(e - 8);
        Mod& m = g_mods[g_modCount];
        m.base = *reinterpret_cast<const uint32_t*>(entry + 0x18);
        m.end = m.base + *reinterpret_cast<const uint32_t*>(entry + 0x20);
        const unsigned len = *reinterpret_cast<const uint16_t*>(entry + 0x2C) / 2;
        const wchar_t* nm = *reinterpret_cast<const wchar_t* const*>(entry + 0x30);
        int k = 0;
        if (nm && Readable(nm, len * 2)) {
            for (; k < static_cast<int>(sizeof(m.name)) - 1 && static_cast<unsigned>(k) < len; ++k) m.name[k] = nm[k] < 128 ? static_cast<char>(nm[k]) : '?';
        }
        m.name[k] = 0;
        if (m.base) ++g_modCount;
        e = *reinterpret_cast<const uintptr_t*>(e);
        if (!Readable(reinterpret_cast<void*>(e), 8)) break;
    }
}

// Hex without leading zeros (module offsets, as the stall sampler writes them).
void HexShort(uint32_t v) {
    static const char d[] = "0123456789ABCDEF";
    bool started = false;
    for (int i = 7; i >= 0; --i) {
        const uint32_t nib = (v >> (i * 4)) & 15;
        if (nib || started || i == 0) { PutChar(d[nib]); started = true; }
    }
}

void PutWhere(uintptr_t a) {
    for (int i = 0; i < g_modCount; ++i) {
        if (a >= g_mods[i].base && a < g_mods[i].end) {
            Put(g_mods[i].name); Put("+0x"); HexShort(static_cast<uint32_t>(a - g_mods[i].base));
            return;
        }
    }
    Hex(static_cast<uint32_t>(a));
}

bool IsReturnAddress(uintptr_t p) {
    if (p < 0x10000) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(reinterpret_cast<LPCVOID>(p), &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) return false;
    if (!(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))) return false;
    if (!Readable(reinterpret_cast<const void*>(p - 6), 6)) return false;
    const uint8_t* b = reinterpret_cast<const uint8_t*>(p - 6);
    return b[1] == 0xE8 || (b[4] == 0xFF && (b[5] & 0x38) == 0x10) || (b[3] == 0xFF && (b[4] & 0x38) == 0x10) ||
           (b[0] == 0xFF && (b[1] & 0x38) == 0x10);
}

// Return-address-looking words from esp up (stale words included; the ebp chain below is the exact one).
void PutStackWords(uintptr_t esp, int maxFound, int maxWords) {
    int found = 0;
    for (int i = 0; i < maxWords && found < maxFound; ++i) {
        const uintptr_t at = (esp & ~static_cast<uintptr_t>(3)) + static_cast<uintptr_t>(i) * 4;
        if (!Readable(reinterpret_cast<const void*>(at), 4)) break;
        const uintptr_t w = *reinterpret_cast<const uint32_t*>(at);
        if (!IsReturnAddress(w)) continue;
        if (found) Put(" < ");
        PutWhere(w);
        ++found;
    }
}

void PutChain(uintptr_t ebp, int maxFrames) {
    uintptr_t bp = ebp;
    for (int k = 0; k < maxFrames; ++k) {
        if (!Readable(reinterpret_cast<const void*>(bp), 8) || (bp & 3)) break;
        const uint32_t* f = reinterpret_cast<const uint32_t*>(bp);
        if (f[1] < 0x10000) break;
        if (k) Put(" < ");
        PutWhere(f[1]);
        if (f[0] <= bp) break;
        bp = f[0];
    }
}

void PutRegs(const CONTEXT& c) {
    Put("eax "); Hex(c.Eax); Put(" ebx "); Hex(c.Ebx); Put(" ecx "); Hex(c.Ecx); Put(" edx "); Hex(c.Edx);
    Put(" esi "); Hex(c.Esi); Put(" edi "); Hex(c.Edi); Put(" ebp "); Hex(c.Ebp); Put(" esp "); Hex(c.Esp);
    Put(" eip "); Hex(c.Eip);
}

void PutThreadName(DWORD tid) {
    if (tid == g_gameTid) { Put(" (game)"); return; }
    const char* n = ThreadNameOf(tid);
    if (n) { Put(" ("); Put(n); Put(")"); }
}

// Critical sections whose address is on a thread's stack (the one RtlEnterCriticalSection waits on is among them): address,
// where it lives (module+offset, or a heap/stack address), owner thread and recursion. A CS has a debug record that points back
// at it (DebugInfo->CriticalSection, +4).
void PutLocksOnStack(uintptr_t esp, int maxWords) {
    uintptr_t seen[8];
    int nseen = 0;
    for (int i = 0; i < maxWords && nseen < 8; ++i) {
        const uintptr_t at = (esp & ~static_cast<uintptr_t>(3)) + static_cast<uintptr_t>(i) * 4;
        if (!Readable(reinterpret_cast<const void*>(at), 4)) break;
        const uintptr_t p = *reinterpret_cast<const uint32_t*>(at);
        if (p < 0x10000 || (p & 3) || !Readable(reinterpret_cast<const void*>(p), 24)) continue;
        const uint32_t* cs = reinterpret_cast<const uint32_t*>(p);
        const uintptr_t dbg = cs[0];
        if (dbg < 0x10000 || dbg == 0xFFFFFFFFu || dbg == p || !Readable(reinterpret_cast<const void*>(dbg), 8)) continue;
        if (*reinterpret_cast<const uint32_t*>(dbg + 4) != p) continue;
        if (cs[2] > 4096 || cs[3] > 0x100000) continue;
        bool dup = false;
        for (int k = 0; k < nseen; ++k) dup = dup || seen[k] == p;
        if (dup) continue;
        seen[nseen++] = p;
        Put(" | CS "); Hex(static_cast<uint32_t>(p)); Put(" at "); PutWhere(p);
        Put(": owner "); Dec(cs[3]); PutThreadName(cs[3]); Put(" recursion "); Dec(static_cast<int32_t>(cs[2])); Put(" count "); Dec(static_cast<int32_t>(cs[1]));
    }
}

// Suspends the thread only while the registers are copied; resumes before anything is formatted.
bool Snapshot(HANDLE th, CONTEXT* c, DWORD* previousSuspend) {
    const DWORD prev = SuspendThread(th);
    if (prev == static_cast<DWORD>(-1)) return false;
    c->ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
    const BOOL ok = GetThreadContext(th, c);
    ResumeThread(th);
    if (previousSuspend) *previousSuspend = prev;
    return ok != FALSE;
}

// The lock in a heap's header: on 32-bit Windows 10/11 an RTL_CRITICAL_SECTION embedded at +0x260 (DebugInfo, LockCount,
// RecursionCount, OwningThread, LockSemaphore, SpinCount). LockCount is -1 free, below -1 with waiters; OwningThread is the
// owner's thread id. A heap made without a lock (HEAP_NO_SERIALIZE) shows zeros there.
void PutHeapLock(HANDLE heap) {
    const uintptr_t base = reinterpret_cast<uintptr_t>(heap);
    Put("heap "); Hex(static_cast<uint32_t>(base));
    if (!Readable(reinterpret_cast<void*>(base + 0x260), 24)) { Put(" unreadable"); return; }
    const uint32_t* cs = reinterpret_cast<const uint32_t*>(base + 0x260);
    if (!cs[0]) { Put(" no lock (zeros at +0x260)"); return; }
    Put(" lock +0x260: count "); Dec(static_cast<int32_t>(cs[1])); Put(" recursion "); Dec(static_cast<int32_t>(cs[2]));
    Put(" owner thread "); Dec(cs[3]); PutThreadName(cs[3]);
    Put(cs[3] ? (cs[1] == 0xFFFFFFFFu ? " (held, nobody waiting)" : " (HELD, threads waiting)") : " (free)");
}

void PutHeapLocks(const char* prefix) {
    HANDLE heaps[48];
    const DWORD n = GetProcessHeaps(48, heaps);
    HANDLE proc = GetProcessHeap();
    for (DWORD i = 0; i < n && i < 48; ++i) {
        LineStart(prefix);
        Put(heaps[i] == proc ? "process " : "");
        PutHeapLock(heaps[i]);
        LineEnd();
    }
}

// Every thread of the process, one line each: id, name, where it is, the exact callers (ebp chain) and the stack scan.
void DumpThreads(const char* prefix) {
    if (!g_ntGetNextThread) return;
    const DWORD self = GetCurrentThreadId();
    HANDLE prev = nullptr;
    int count = 0;
    for (;;) {
        HANDLE next = nullptr;
        const LONG st = g_ntGetNextThread(GetCurrentProcess(), prev,
                                          THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, 0, 0, &next);
        if (prev) CloseHandle(prev);
        if (st < 0 || !next) break;
        prev = next;
        if (++count > 128) break;
        const DWORD tid = GetThreadId(next);
        CONTEXT c = {};
        DWORD suspended = 0;
        const bool ok = tid != self && Snapshot(next, &c, &suspended);
        LineStart(prefix);
        Put("thread "); Dec(tid); PutThreadName(tid);
        if (g_ntQueryThread) {
            uintptr_t start = 0;
            if (g_ntQueryThread(next, 9, &start, sizeof(start), nullptr) >= 0 && start) { Put(" start "); PutWhere(start); }
        }
        if (tid == self) { Put(" (this thread)"); LineEnd(); continue; }
        if (!ok) { Put(": no context"); LineEnd(); continue; }
        if (suspended) { Put(" SUSPENDED x"); Dec(suspended); }
        Put(" at "); PutWhere(c.Eip); Put(", chain "); PutChain(c.Ebp, 10);
        Put(", stack "); PutStackWords(c.Esp, 8, 300);
        PutLocksOnStack(c.Esp, 300);
        LineEnd();
    }
    if (prev) CloseHandle(prev);
}

// A minidump from a helper process: comsvcs.dll MiniDump through rundll32, created SUSPENDED at start-up (Init) and only
// resumed here, because creating a process allocates from the process heap, which is the lock a heap hang holds. The helper
// is in a kill-on-close job, so it dies with the game when it is never used. Waits up to 40 s for it.
HANDLE g_dumpProc = nullptr, g_dumpThread = nullptr, g_dumpJob = nullptr;

void PrepareDumper() {
    if (!g_dumpMode) return;
    char sys[MAX_PATH];
    const UINT n = GetSystemWow64DirectoryA(sys, MAX_PATH);
    if (!n || n > 200) return;
    char cmd[640];
    size_t k = 0;
    auto add = [&](const char* s2) { while (*s2 && k + 1 < sizeof(cmd)) cmd[k++] = *s2++; };
    add(sys); add("\\rundll32.exe "); add(sys); add("\\comsvcs.dll, MiniDump ");
    char numr[16]; int nn = 0; DWORD v = g_pid; do { numr[nn++] = static_cast<char>('0' + v % 10); v /= 10; } while (v);
    char num[16]; int ni = 0; while (nn) num[ni++] = numr[--nn]; num[ni] = 0;
    add(num);
    add(" "); add(g_exeDir); add("gta2dx9_hang_"); add(num); add(".dmp"); add(g_dumpMode >= 2 ? " full" : " normal");
    cmd[k] = 0;
    g_dumpJob = CreateJobObjectA(nullptr, nullptr);
    if (g_dumpJob) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION li = {};
        li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(g_dumpJob, JobObjectExtendedLimitInformation, &li, sizeof(li));
    }
    STARTUPINFOA si = {};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION pi = {};
    if (CreateProcessA(nullptr, cmd, nullptr, nullptr, FALSE, CREATE_SUSPENDED | CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
        g_dumpProc = pi.hProcess;
        g_dumpThread = pi.hThread;
        const BOOL assigned = g_dumpJob ? AssignProcessToJobObject(g_dumpJob, pi.hProcess) : FALSE;
        Log("crash safe: minidump helper %lu ready (suspended%s): %s", static_cast<unsigned long>(pi.dwProcessId),
            assigned ? ", in a kill-on-close job" : ", NOT in a job: it stays until the game ends it", cmd);
    } else {
        Log("crash safe: minidump helper not started (error %lu)", GetLastError());
    }
}

void RequestMinidump(const char* what) {
    if (!g_dumpThread) { LineStart(what); Put("minidump: no helper was prepared (hang_dump=0 or it did not start)"); LineEnd(); Flush(); return; }
    LineStart(what); Put("minidump: waking the helper"); LineEnd(); Flush();
    ResumeThread(g_dumpThread);
    const DWORD w = WaitForSingleObject(g_dumpProc, 40000);
    LineStart(what); Put(w == WAIT_OBJECT_0 ? "minidump written (gta2dx9_hang_<pid>.dmp)" : "minidump helper still running after 40 s; going on"); LineEnd();
    Flush();
}

// Only one thread reports. The same thread arriving again (a fault inside the report) ends the process at once; another
// thread waits a while for the first to finish, then ends it too.
void EnterReport() {
    const DWORD me = GetCurrentThreadId();
    for (int i = 0; i < 100; ++i) {
        if (InterlockedCompareExchange(&g_reporting, 1, 0) == 0) { g_reportingTid = me; return; }
        if (g_reportingTid == me) TerminateProcess(GetCurrentProcess(), 0xDEAD0003);
        Sleep(100);
    }
    TerminateProcess(GetCurrentProcess(), 0xDEAD0004);
}

}  // namespace


// ---- the Miles timer thread suspends the game thread: the root cause of the QA r52 hang -------------------------------
// mss32.dll (Miles Sound System, the 1999 game's audio) has a service thread (start mss32+0x1520) that, about 150 times a
// second, SuspendThread()s the game thread, runs its timer work (DirectSound calls that allocate: DSOUND -> ucrtbase malloc ->
// the PROCESS HEAP lock) and resumes it. When the suspension lands while the game thread is inside the process heap
// (RtlAllocateHeap / RtlFreeHeap from the Remix bridge, ucrtbase or ntdll itself), it stops holding the heap's lock; the Miles
// thread then waits for that lock for ever: game thread suspended, Miles thread blocked, every other allocating thread behind
// them (r52: 5.4 minutes; tdr/h2_rc_drizzle; reproduced in minutes with heap debug flags that lengthen the time spent in the
// heap). Found by hooking NtSuspendThread (below): thread, callers and times are in the hang report.
//
// The fix here is at the same place: NtSuspendThread / NtResumeThread are hooked in this process's 32-bit ntdll; when the
// caller is in mss32.dll and the target is the game thread, the suspension is made SAFE: suspend, then look (the thread
// cannot change now) whether it owns a heap lock, the loader lock or the PEB lock; if it does, resume it at once, yield and try
// again (up to ~3 s, then behave as before). And a backstop in the watchdog: a game thread that stays suspended by a Miles
// suspension for over a second is resumed from there (the Miles thread's own ResumeThread later does nothing).
namespace {
struct SuspRec { DWORD tick, caller, target, resume, seq; uint32_t words[20]; };
volatile LONG g_evSeq = 0;
constexpr int kSusp = 32;
SuspRec g_susp[kSusp];            // game-thread suspensions by anyone but mss32 (the sampler, the dump, an overlay ...)
volatile LONG g_suspN = 0;
SuspRec g_lastMss[2];             // the last mss32 SUSPEND [0] and RESUME [1] of the game thread
volatile LONG g_suspTotal = 0, g_resumeTotal = 0, g_mssSuspends = 0, g_safeRetries = 0, g_safeGaveUp = 0, g_breaks = 0;
bool g_safeSuspend = true;
uintptr_t g_mssBase = 0, g_mssEnd = 0;
uint8_t* g_trampSuspend = nullptr;
uint8_t* g_trampResume = nullptr;
uint8_t* g_stubSuspend = nullptr;   // the patched ntdll stubs and their original first five bytes (UnhookStubs puts them back)
uint8_t* g_stubResume = nullptr;
uint8_t g_origSuspend[5] = {}, g_origResume[5] = {};
typedef LONG(NTAPI* NtSuspendFn)(HANDLE, PULONG);

DWORD TargetTid(HANDLE h) {
    struct { LONG exitStatus; PVOID teb; DWORD pid, tid; ULONG affinity; LONG priority, basePriority; } tbi = {};
    if (!g_ntQueryThread || g_ntQueryThread(h, 0, &tbi, sizeof(tbi), nullptr) < 0) return 0;
    return tbi.tid;
}

// mss32.dll's image range from the loader's list (no lock, no heap); retried until it is loaded.
void FindMss() {
    uintptr_t peb = 0;
    __asm__ volatile("movl %%fs:0x30, %0" : "=r"(peb));
    if (!Readable(reinterpret_cast<void*>(peb), 0x10)) return;
    const uintptr_t ldr = *reinterpret_cast<const uintptr_t*>(peb + 0x0C);
    if (!Readable(reinterpret_cast<void*>(ldr), 0x20)) return;
    const uintptr_t head = ldr + 0x14;
    uintptr_t e = *reinterpret_cast<const uintptr_t*>(head);
    for (int guard = 0; e && e != head && guard < 1024; ++guard) {
        if (!Readable(reinterpret_cast<void*>(e - 8), 0x40)) return;
        const uint8_t* entry = reinterpret_cast<const uint8_t*>(e - 8);
        const unsigned len = *reinterpret_cast<const uint16_t*>(entry + 0x2C) / 2;
        const wchar_t* nm = *reinterpret_cast<const wchar_t* const*>(entry + 0x30);
        if (len == 9 && nm && Readable(nm, 18)) {
            static const wchar_t want[] = L"mss32.dll";
            bool same = true;
            for (int i = 0; i < 9; ++i) { wchar_t c = nm[i]; if (c >= 'A' && c <= 'Z') c += 32; if (c != want[i]) same = false; }
            if (same) {
                g_mssBase = *reinterpret_cast<const uint32_t*>(entry + 0x18);
                g_mssEnd = g_mssBase + *reinterpret_cast<const uint32_t*>(entry + 0x20);
                return;
            }
        }
        e = *reinterpret_cast<const uintptr_t*>(e);
        if (!Readable(reinterpret_cast<void*>(e), 8)) return;
    }
}

bool CallerIsMss(const uint32_t* frame) {
    if (!g_mssBase) FindMss();
    if (!g_mssBase) return false;
    for (int i = 0; i < 8; ++i)
        if (frame[i] >= g_mssBase && frame[i] < g_mssEnd) return true;
    return false;
}

// A critical section that the game thread, stopped now, makes dangerous for whoever needs it next: it owns it, or it is mid-release
// (owner already cleared, recursion 0) of a lock that still has waiters (LockCount below -1): the waiters are woken by the
// releasing thread, which is the one that is stopped, and a thread arriving now queues behind them for good (seen in r75: the Miles
// thread "waits" on a heap lock with owner 0, recursion 0, count -10).
bool OwnsCs(const uint32_t* cs, DWORD tid) {   // RTL_CRITICAL_SECTION: DebugInfo, LockCount, RecursionCount, OwningThread
    if (!cs[0]) return false;
    if (cs[2] > 0 && cs[2] < 4096 && cs[3] == tid) return true;
    return cs[3] == 0 && cs[2] == 0 && static_cast<int32_t>(cs[1]) < -1 && static_cast<int32_t>(cs[1]) > -1000000;
}

// Does the (suspended) game thread own a heap's lock, the loader lock or the PEB lock? Reads the PEB's heap list directly:
// GetProcessHeaps takes the PEB lock, which may be the one the game thread holds.
bool GameHoldsLocks() {
    uintptr_t peb = 0;
    __asm__ volatile("movl %%fs:0x30, %0" : "=r"(peb));
    if (!Readable(reinterpret_cast<void*>(peb), 0xB0)) return false;
    const uint32_t nHeaps = *reinterpret_cast<const uint32_t*>(peb + 0x88);
    const uint32_t* heaps = *reinterpret_cast<const uint32_t* const*>(peb + 0x90);
    if (heaps && nHeaps && nHeaps <= 256 && Readable(heaps, nHeaps * 4)) {
        for (uint32_t i = 0; i < nHeaps; ++i) {
            const uintptr_t h = heaps[i];
            if (h && Readable(reinterpret_cast<void*>(h + 0x260), 16) && OwnsCs(reinterpret_cast<const uint32_t*>(h + 0x260), g_gameTid)) return true;
        }
    }
    const uintptr_t fastPeb = *reinterpret_cast<const uintptr_t*>(peb + 0x1C);
    const uintptr_t loader = *reinterpret_cast<const uintptr_t*>(peb + 0xA0);
    if (fastPeb && Readable(reinterpret_cast<void*>(fastPeb), 16) && OwnsCs(reinterpret_cast<const uint32_t*>(fastPeb), g_gameTid)) return true;
    if (loader && Readable(reinterpret_cast<void*>(loader), 16) && OwnsCs(reinterpret_cast<const uint32_t*>(loader), g_gameTid)) return true;
    return false;
}

__attribute__((noinline)) void RecordGame(const uint32_t* frame, DWORD resume, bool mss) {
    SuspRec* r;
    if (mss) {
        r = &g_lastMss[resume ? 1 : 0];
        if (!resume) InterlockedIncrement(&g_mssSuspends);
    } else {
        r = &g_susp[(InterlockedIncrement(&g_suspN) - 1) % kSusp];
    }
    r->tick = GetTickCount();
    r->caller = GetCurrentThreadId();
    r->target = g_gameTid;
    r->resume = resume;
    r->seq = static_cast<DWORD>(InterlockedIncrement(&g_evSeq));
    for (int k = 0; k < 20; ++k) r->words[k] = frame[k];
}

LONG NTAPI HookSuspend(HANDLE th, PULONG prev) {
    const uint32_t* frame = reinterpret_cast<const uint32_t*>(&th) - 1;
    InterlockedIncrement(&g_suspTotal);
    NtSuspendFn real = reinterpret_cast<NtSuspendFn>(g_trampSuspend);
    NtSuspendFn realResume = reinterpret_cast<NtSuspendFn>(g_trampResume);
    if (!g_gameTid || TargetTid(th) != g_gameTid) return real(th, prev);
    const bool mss = CallerIsMss(frame);
    if (mss && g_safeSuspend) {
        for (int attempt = 0;; ++attempt) {
            const LONG r = real(th, prev);
            if (r < 0) return r;
            if (!GameHoldsLocks() || attempt >= 3000) {
                if (attempt >= 3000) InterlockedIncrement(&g_safeGaveUp);
                RecordGame(frame, 0, true);
                return r;
            }
            ULONG dummy = 0;
            realResume(th, &dummy);
            InterlockedIncrement(&g_safeRetries);
            if (attempt < 20) SwitchToThread(); else Sleep(1);
        }
    }
    RecordGame(frame, 0, mss);
    return real(th, prev);
}

LONG NTAPI HookResume(HANDLE th, PULONG prev) {
    const uint32_t* frame = reinterpret_cast<const uint32_t*>(&th) - 1;
    InterlockedIncrement(&g_resumeTotal);
    if (g_gameTid && TargetTid(th) == g_gameTid) RecordGame(frame, 1, CallerIsMss(frame));
    return reinterpret_cast<NtSuspendFn>(g_trampResume)(th, prev);
}

// Replaces the first five bytes of an ntdll syscall stub (mov eax, imm32) by a jump to `hook`; the trampoline runs them.
uint8_t* HookStub(const char* name, void* hook, uint8_t** stubOut, uint8_t* origOut) {
    HMODULE nt = GetModuleHandleA("ntdll.dll");
    uint8_t* stub = nt ? reinterpret_cast<uint8_t*>(GetProcAddress(nt, name)) : nullptr;
    if (!stub || stub[0] != 0xB8) return nullptr;
    uint8_t* tramp = static_cast<uint8_t*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramp) return nullptr;
    memcpy(tramp, stub, 5);
    memcpy(origOut, stub, 5);
    *stubOut = stub;
    tramp[5] = 0xE9;
    *reinterpret_cast<int32_t*>(tramp + 6) = static_cast<int32_t>((stub + 5) - (tramp + 10));
    DWORD old = 0;
    if (!VirtualProtect(stub, 5, PAGE_EXECUTE_READWRITE, &old)) return nullptr;
    stub[0] = 0xE9;
    *reinterpret_cast<int32_t*>(stub + 1) = static_cast<int32_t>(reinterpret_cast<uint8_t*>(hook) - (stub + 5));
    VirtualProtect(stub, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), stub, 5);
    return tramp;
}

// Puts the original five bytes back: the game may unload this DLL (FreeLibrary) while the process lives, and a stub that jumps
// into an unmapped hook would end it at the next Miles suspension. The trampolines stay allocated for a call already in flight.
void UnhookStubs() {
    uint8_t* stubs[2] = {g_stubSuspend, g_stubResume};
    const uint8_t* orig[2] = {g_origSuspend, g_origResume};
    for (int i = 0; i < 2; ++i) {
        if (!stubs[i]) continue;
        DWORD old = 0;
        if (!VirtualProtect(stubs[i], 5, PAGE_EXECUTE_READWRITE, &old)) continue;
        memcpy(stubs[i], orig[i], 5);
        VirtualProtect(stubs[i], 5, old, &old);
        FlushInstructionCache(GetCurrentProcess(), stubs[i], 5);
    }
    g_stubSuspend = g_stubResume = nullptr;
}

void PutOneSusp(const char* prefix, const char* label, const SuspRec& r) {
    LineStart(prefix); Put(label); Put(" of the game thread by thread "); Dec(r.caller); PutThreadName(r.caller);
    Put(", "); Dec(static_cast<int64_t>(GetTickCount() - r.tick)); Put(" ms ago, callers ");
    int shown = 0;
    for (int i = 0; i < 20 && shown < 10; ++i) {
        if (!IsReturnAddress(r.words[i])) continue;
        if (shown) Put(" < ");
        PutWhere(r.words[i]);
        ++shown;
    }
    LineEnd();
}

void PutSuspendHistory(const char* prefix) {
    LineStart(prefix); Put("NtSuspendThread calls in this process "); Dec(g_suspTotal); Put(", NtResumeThread "); Dec(g_resumeTotal);
    Put(", of the game thread by mss32.dll "); Dec(g_mssSuspends); Put(" (safe suspend ");
    Put(g_safeSuspend ? "ON" : "off"); Put(": "); Dec(g_safeRetries); Put(" retries because the game thread held a heap/loader/PEB lock, ");
    Dec(g_safeGaveUp); Put(" gave up, "); Dec(g_breaks); Put(" suspensions broken by the watchdog)");
    Put(g_trampSuspend ? "" : " (hook NOT installed)"); LineEnd();
    if (g_lastMss[0].tick) PutOneSusp(prefix, "last mss32 SUSPEND", g_lastMss[0]);
    if (g_lastMss[1].tick) PutOneSusp(prefix, "last mss32 RESUME", g_lastMss[1]);
    const LONG n = g_suspN < kSusp ? g_suspN : kSusp;
    const LONG first = g_suspN < kSusp ? 0 : g_suspN - kSusp;
    for (LONG k = first; k < first + n; ++k) PutOneSusp(prefix, g_susp[k % kSusp].resume ? "other RESUME" : "other SUSPEND", g_susp[k % kSusp]);
}
}  // namespace

// ---- Init -------------------------------------------------------------------------------------------
void Init() {
    g_pid = GetCurrentProcessId();
    char path[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = n && n < MAX_PATH ? strrchr(path, '\\') : nullptr;
    if (slash) {
        slash[1] = 0;
        strncpy(g_exeDir, path, sizeof(g_exeDir) - 1);
        strcat(path, "gta2dx9_fatal.log");
        g_fatalFile = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                  OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        char ini[MAX_PATH];
        strncpy(ini, g_exeDir, sizeof(ini) - 20);
        ini[sizeof(ini) - 20] = 0;
        strcat(ini, "gta2dx9.ini");
        g_killMs = GetPrivateProfileIntA("devtools", "hang_kill_ms", 6000, ini);
        g_busyKillMs = GetPrivateProfileIntA("devtools", "hang_busy_kill_ms", 60000, ini);
        g_dumpMode = GetPrivateProfileIntA("devtools", "hang_dump", 1, ini);
        g_safeSuspend = GetPrivateProfileIntA("devtools", "mss_safe_suspend", 1, ini) != 0;
    }
    g_mainLog = static_cast<HANDLE>(LogOsHandle());
    HMODULE nt = GetModuleHandleA("ntdll.dll");
    if (nt) {
        const char* names[5] = {"NtWaitForSingleObject", "NtWaitForMultipleObjects", "NtDelayExecution", "NtSignalAndWaitForSingleObject", "NtWaitForMultipleObjects32"};
        for (int i = 0; i < 5; ++i) g_waitStubs[i] = reinterpret_cast<uintptr_t>(GetProcAddress(nt, names[i]));
    }
    g_ntQueryThread = nt ? reinterpret_cast<NtQueryInformationThreadFn>(GetProcAddress(nt, "NtQueryInformationThread")) : nullptr;
    g_ntGetNextThread = nt ? reinterpret_cast<NtGetNextThreadFn>(GetProcAddress(nt, "NtGetNextThread")) : nullptr;
    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    g_queryCycles = k32 ? reinterpret_cast<QueryThreadCycleTimeFn>(GetProcAddress(k32, "QueryThreadCycleTime")) : nullptr;
    CollectModules();   // a first table (the report refreshes it)
    PrepareDumper();
    g_trampResume = HookStub("NtResumeThread", reinterpret_cast<void*>(&HookResume), &g_stubResume, g_origResume);
    g_trampSuspend = HookStub("NtSuspendThread", reinterpret_cast<void*>(&HookSuspend), &g_stubSuspend, g_origSuspend);
    Log("crash safe: fatal log %s, stall limit %lu ms (%lu ms while the Remix server is busy), hang dump mode %lu, NtGetNextThread %s",
        g_fatalFile != INVALID_HANDLE_VALUE ? "open" : "NOT open", static_cast<unsigned long>(g_killMs),
        static_cast<unsigned long>(g_busyKillMs), static_cast<unsigned long>(g_dumpMode), g_ntGetNextThread ? "found" : "missing");
}

void LogSuspendCounters() {
    Log("mss32 suspend guard (%s): %ld NtSuspendThread calls in the process, %ld of the game thread by mss32.dll, %ld retried because the game thread held a "
        "heap/loader/PEB lock, %ld gave up, %ld broken by the watchdog",
        g_safeSuspend ? "on" : "off", static_cast<long>(g_suspTotal), static_cast<long>(g_mssSuspends), static_cast<long>(g_safeRetries),
        static_cast<long>(g_safeGaveUp), static_cast<long>(g_breaks));
}

void SetGameThread(DWORD tid, volatile DWORD* beat) {
    g_gameTid = tid;
    g_beat = beat;
}

DWORD HangKillMs() { return g_killMs; }
DWORD HangBusyKillMs() { return g_busyKillMs; }

void RefreshServerPid() {
    // Toolhelp allocates: only from the sampler thread, while the game is healthy.
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return;
    PROCESSENTRY32 pe;
    pe.dwSize = sizeof(pe);
    DWORD found = 0;
    for (BOOL ok = Process32First(snap, &pe); ok; ok = Process32Next(snap, &pe)) {
        if (_stricmp(pe.szExeFile, "NvRemixBridge.exe") == 0) { found = pe.th32ProcessID; break; }
    }
    CloseHandle(snap);
    g_serverPid = found;
}

static ULONGLONG ProcessCpu100ns(HANDLE p) {
    FILETIME c, e, k, u;
    if (!GetProcessTimes(p, &c, &e, &k, &u)) return 0;
    return ((static_cast<ULONGLONG>(k.dwHighDateTime) << 32) | k.dwLowDateTime) +
           ((static_cast<ULONGLONG>(u.dwHighDateTime) << 32) | u.dwLowDateTime);
}

bool ServerBusy() {
    const DWORD pid = g_serverPid;
    if (!pid) return false;
    HANDLE p = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!p) return false;
    const ULONGLONG a = ProcessCpu100ns(p);
    Sleep(500);
    const ULONGLONG b = ProcessCpu100ns(p);
    CloseHandle(p);
    return b > a && (b - a) >= 1000000ull;   // 100 ms in 100 ns units
}

void LogUnguardedFault(EXCEPTION_POINTERS* info) {
    if (InterlockedIncrement(&g_faultLines) > 3) return;
    if (InterlockedCompareExchange(&g_reporting, 1, 0) != 0) return;   // a fatal report is being written
    g_reportingTid = GetCurrentThreadId();
    const DWORD lastError = GetLastError();
    CollectModules();
    const EXCEPTION_RECORD* r = info->ExceptionRecord;
    const CONTEXT* c = info->ContextRecord;
    LineStart("FAULT: code "); Hex(r->ExceptionCode); Put(" at "); Hex(reinterpret_cast<uint32_t>(r->ExceptionAddress));
    Put(" ("); PutWhere(reinterpret_cast<uintptr_t>(r->ExceptionAddress)); Put("), reading ");
    Hex(r->NumberParameters > 1 ? static_cast<uint32_t>(r->ExceptionInformation[1]) : 0);
    Put(", thread "); Dec(GetCurrentThreadId()); PutThreadName(GetCurrentThreadId()); LineEnd();
    LineStart("FAULT: "); PutRegs(*c); LineEnd();
    LineStart("FAULT: callers "); PutChain(c->Ebp, 12); Put(" | stack "); PutStackWords(c->Esp, 12, 400); LineEnd();
    Flush();
    g_reportingTid = 0;
    InterlockedExchange(&g_reporting, 0);
    SetLastError(lastError);
}

void NoteDebugString(EXCEPTION_POINTERS* info) {
    const EXCEPTION_RECORD* r = info->ExceptionRecord;
    if (r->NumberParameters < 2) return;
    if (InterlockedIncrement(&g_debugLines) > 60) return;
    if (InterlockedCompareExchange(&g_reporting, 1, 0) != 0) return;
    g_reportingTid = GetCurrentThreadId();
    const char* text = reinterpret_cast<const char*>(r->ExceptionInformation[1]);
    const bool wide = r->ExceptionCode == 0x4001000A;   // DBG_PRINTEXCEPTION_WIDE_C: [1] is a wchar_t*, [0] its length
    LineStart("heap debug: ");
    if (wide) {
        const wchar_t* w = reinterpret_cast<const wchar_t*>(text);
        for (ULONG_PTR i = 0; i < 300 && Readable(w + i, 2) && w[i]; ++i) if (w[i] != '\n' && w[i] != '\r') PutChar(w[i] < 128 ? static_cast<char>(w[i]) : '?');
    } else {
        for (int i = 0; i < 300 && Readable(text + i, 1) && text[i]; ++i) if (text[i] != '\n' && text[i] != '\r') PutChar(text[i]);
    }
    Put(" [thread "); Dec(GetCurrentThreadId()); Put("]");
    LineEnd();
    Flush();
    g_reportingTid = 0;
    InterlockedExchange(&g_reporting, 0);
}

void FatalException(const char* why, EXCEPTION_POINTERS* info) {
    EnterReport();
    const DWORD tid = GetCurrentThreadId();
    CollectModules();
    const DWORD beat = g_beat ? *g_beat : 0;
    LineStart("FAULT: "); Put(why ? why : "fatal");
    if (info && info->ExceptionRecord) {
        const EXCEPTION_RECORD* r = info->ExceptionRecord;
        Put(": exception "); Hex(r->ExceptionCode); Put(" at "); Hex(reinterpret_cast<uint32_t>(r->ExceptionAddress));
        Put(" ("); PutWhere(reinterpret_cast<uintptr_t>(r->ExceptionAddress)); Put(")");
        if (r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters > 1) {
            Put(r->ExceptionInformation[0] == 1 ? ", writing " : r->ExceptionInformation[0] == 8 ? ", executing " : ", reading ");
            Hex(static_cast<uint32_t>(r->ExceptionInformation[1]));
        }
    }
    Put(", thread "); Dec(tid); PutThreadName(tid);
    Put(", "); Dec(beat ? static_cast<int64_t>(GetTickCount() - beat) : -1); Put(" ms since the last frame; the process ends now");
    LineEnd();
    if (info && info->ContextRecord) {
        const CONTEXT* c = info->ContextRecord;
        LineStart("FAULT: "); PutRegs(*c); LineEnd();
        LineStart("FAULT: callers "); PutChain(c->Ebp, 14); Put(" | stack "); PutStackWords(c->Esp, 14, 500); LineEnd();
    }
    PutSuspendHistory("FAULT: ");
    PutHeapLocks("FAULT: ");
    DumpThreads("FAULT: ");
    Flush();
    RequestMinidump("FAULT: ");
    LineStart("FAULT: ended by the crash handler"); LineEnd();
    Flush();
    TerminateProcess(GetCurrentProcess(),
                     info && info->ExceptionRecord ? info->ExceptionRecord->ExceptionCode : 0xDEAD0001);
    for (;;) Sleep(1000);
}

void HangExit(HANDLE gameThread, DWORD idleMs, const char* why) {
    EnterReport();
    CollectModules();
    LineStart("HANG: game thread "); Dec(g_gameTid); Put(" has drawn no frame for "); Dec(idleMs);
    Put(" ms (limit "); Dec(g_killMs); Put(" ms, "); Put(why ? why : ""); Put("): ending the process"); LineEnd();
    if (g_ntQueryThread) {
        ULONG now = 0;
        const LONG st = g_ntQueryThread(gameThread, 35, &now, sizeof(now), nullptr);
        LineStart("HANG: game thread suspend count now (NtQueryInformationThread, nothing suspended): ");
        if (st >= 0) Dec(now); else Put("unavailable");
        LineEnd();
    }
    if (g_histN) {
        LineStart("HANG: game thread history (ms before this report: suspend count, Mcycles since the previous entry):");
        for (int i = 0; i < g_histN; ++i) {
            PutChar(' '); Dec(-static_cast<int64_t>(GetTickCount() - g_hist[i].tick)); PutChar(':'); Dec(g_hist[i].suspend);
            PutChar('/'); Dec(i ? static_cast<int64_t>((g_hist[i].cycles - g_hist[i - 1].cycles) / 1000000) : 0);
        }
        LineEnd();
    }
    // The game thread: suspend count it had (non-zero = something else holds it suspended), registers, and repeated samples
    // (a spinning thread moves its eip and burns cycles; a waiting one does not).
    CONTEXT c = {};
    DWORD prevSuspend = 0;
    ULONG64 cyc0 = 0, cyc1 = 0;
    if (g_queryCycles) g_queryCycles(gameThread, &cyc0);
    if (Snapshot(gameThread, &c, &prevSuspend)) {
        LineStart("HANG: game thread suspend count before ours "); Dec(prevSuspend);
        Put(prevSuspend ? " (SUSPENDED BY SOMEONE ELSE)" : " (not suspended)"); LineEnd();
        LineStart("HANG: game thread at "); PutWhere(c.Eip); Put(": "); PutRegs(c); LineEnd();
        LineStart("HANG: game thread chain "); PutChain(c.Ebp, 16); LineEnd();
        LineStart("HANG: game thread stack "); PutStackWords(c.Esp, 16, 600); LineEnd();
        Flush();
        uint32_t eips[12];
        int ne = 0;
        for (int i = 0; i < 12; ++i) {
            CONTEXT s = {};
            if (Snapshot(gameThread, &s, nullptr)) eips[ne++] = s.Eip;
            Sleep(17);
        }
        LineStart("HANG: game thread eip samples (17 ms apart):");
        for (int i = 0; i < ne; ++i) { PutChar(' '); PutWhere(eips[i]); }
        LineEnd();
    } else {
        LineStart("HANG: game thread: no context (suspend failed, error "); Dec(GetLastError()); Put(")"); LineEnd();
    }
    if (g_queryCycles) {
        g_queryCycles(gameThread, &cyc1);
        FILETIME cr, ex, kt, ut;
        GetThreadTimes(gameThread, &cr, &ex, &kt, &ut);
        LineStart("HANG: game thread cycles over the samples (~200 ms): "); Dec(static_cast<int64_t>(cyc1 - cyc0));
        Put(cyc1 - cyc0 > 1000000 ? " (RUNNING: spinning)" : " (idle: blocked)");
        Put(", kernel time "); Dec(((static_cast<int64_t>(kt.dwHighDateTime) << 32) | kt.dwLowDateTime) / 10000);
        Put(" ms, user time "); Dec(((static_cast<int64_t>(ut.dwHighDateTime) << 32) | ut.dwLowDateTime) / 10000); Put(" ms");
        LineEnd();
    }
    PutSuspendHistory("HANG: ");
    PutHeapLocks("HANG: ");
    DumpThreads("HANG: ");
    Flush();
    RequestMinidump("HANG: ");
    LineStart("HANG: ended by the stall watchdog"); LineEnd();
    Flush();
    TerminateProcess(GetCurrentProcess(), 0xDEAD0002);
    for (;;) Sleep(1000);
}

// ---- the stall watchdog: a thread of its own that never touches the process heap -------------------------------
namespace {
// What the game thread was doing once a second while it stalled, taken without suspending it: its suspend count
// (NtQueryInformationThread ThreadSuspendCount, 35) and its cycle counter (a thread that is not running adds none).
void RecordHistory(HANDLE game) {
    if (g_histN >= kHist) return;
    HistEntry& e = g_hist[g_histN++];
    e.tick = GetTickCount();
    ULONG count = 0;
    e.suspend = g_ntQueryThread && g_ntQueryThread(game, 35, &count, sizeof(count), nullptr) >= 0 ? static_cast<LONG>(count) : -1;
    ULONG64 c = 0;
    e.cycles = g_queryCycles && g_queryCycles(game, &c) ? c : 0;
}

bool (*g_byDesign)() = nullptr;
volatile LONG* g_frames = nullptr;
LONG g_armFrames = 0;
volatile LONG g_stopWatch = 0;
volatile LONG g_watchRunning = 0;
HANDLE g_watchThread = nullptr;

// The game thread is blocked in a kernel handle wait or a Sleep (ntdll's Nt stub, which the thread sits just after): what
// the Remix bridge client does while it waits for its server. A thread blocked on a critical section or SRW lock (the
// heap's: NtWaitForAlertByThreadId) or running in ntdll's heap code is not.
bool InHandleWait(HANDLE game) {
    CONTEXT c = {};
    if (!Snapshot(game, &c, nullptr)) return false;
    for (int i = 0; i < 5; ++i)
        if (g_waitStubs[i] && c.Eip >= g_waitStubs[i] && c.Eip < g_waitStubs[i] + 0x30) return true;
    return false;
}

// A game thread that a Miles suspension has held for over 400 ms (a timer tick takes microseconds): resume it (the Miles thread
// is waiting for a lock the game thread owns, see the long comment above; its own ResumeThread later finds count 0 and does
// nothing). The safe suspend in HookSuspend should make this unnecessary; this is the backstop, and it says so in the log.
void BreakMissSuspend(HANDLE game) {
    ULONG count = 0;
    if (!g_ntQueryThread || g_ntQueryThread(game, 35, &count, sizeof(count), nullptr) < 0 || !count) return;
    const DWORD now = GetTickCount();
    if (!g_lastMss[0].tick || g_lastMss[0].seq < g_lastMss[1].seq || now - g_lastMss[0].tick < 400) return;
    if (InterlockedCompareExchange(&g_reporting, 1, 0) != 0) return;
    g_reportingTid = GetCurrentThreadId();
    InterlockedIncrement(&g_breaks);
    LineStart("HANG: BREAK: the game thread has been suspended by thread "); Dec(g_lastMss[0].caller); PutThreadName(g_lastMss[0].caller);
    Put(" of mss32.dll for "); Dec(now - g_lastMss[0].tick); Put(" ms (suspend count "); Dec(count);
    Put("), which waits for a lock the game thread holds: resumed it (break #"); Dec(g_breaks); Put(")"); LineEnd();
    PutOneSusp("HANG: BREAK: ", "the Miles SUSPEND was", g_lastMss[0]);
    // What the Miles thread waits on: its registers, callers and the critical sections on its stack with their owners.
    if (HANDLE miles = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, g_lastMss[0].caller)) {
        CONTEXT c = {};
        if (Snapshot(miles, &c, nullptr)) {
            LineStart("HANG: BREAK: the Miles thread is at "); PutWhere(c.Eip); Put(", chain "); PutChain(c.Ebp, 12);
            Put(", stack "); PutStackWords(c.Esp, 10, 300); PutLocksOnStack(c.Esp, 300); LineEnd();
        }
        CloseHandle(miles);
    }
    Flush();
    ResumeThread(game);   // after the report: the Miles thread is still blocked while it is written
    g_reportingTid = 0;
    InterlockedExchange(&g_reporting, 0);
}

DWORD WINAPI WatchdogThread(LPVOID) {
    NameThisThread("stall watchdog");
    HANDLE game = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, g_gameTid);
    if (!game) { InterlockedExchange(&g_watchRunning, 0); return 0; }
    while (!g_stopWatch) {
        Sleep(250);
        BreakMissSuspend(game);   // a Miles suspension of the game thread that outlasts 400 ms is a deadlock, not a timer tick
        const DWORD beat = g_beat ? *g_beat : 0;
        if (!beat || !g_killMs) continue;
        if (g_frames && *g_frames < g_armFrames) continue;   // start-up (the Remix attach alone takes up to 40 s) is not watched
        const DWORD idle = GetTickCount() - beat;
        if (idle < 1000) g_histN = 0;
        if (idle >= 1000 && (!g_histN || GetTickCount() - g_hist[g_histN - 1].tick >= 500)) RecordHistory(game);
        if (idle < g_killMs) continue;
        if (g_byDesign && g_byDesign()) continue;   // paused for a focus loss or minimised: GTA2 runs no frame by design
        // Waiting on a handle while the Remix server is alive and working may be a cold shader cache compiling: give it
        // hang_busy_kill_ms. Anything else (a lock, a spin, a dead server) is a hang now.
        const bool maybeRemix = idle < g_busyKillMs && InHandleWait(game) && ServerBusy();   // ServerBusy sleeps 500 ms
        if (*g_beat != beat) continue;                  // it came back meanwhile
        if (g_stopWatch) break;
        if (maybeRemix) continue;
        g_histN = g_histN;   // (the history is read by HangExit below)
        HangExit(game, GetTickCount() - beat, idle >= g_busyKillMs ? "past the limit even waiting on a handle with the Remix server busy"
                                                                    : "not a wait on the Remix server (a lock, a spin or a dead server)");
    }
    CloseHandle(game);
    InterlockedExchange(&g_watchRunning, 0);
    return 0;
}
}  // namespace

void StartWatchdog(bool (*byDesign)(), volatile LONG* frames, LONG armAfterFrames) {
    if (g_watchThread || !g_beat || !g_gameTid) return;
    g_byDesign = byDesign;
    g_frames = frames;
    g_armFrames = armAfterFrames;
    g_stopWatch = 0;
    InterlockedExchange(&g_watchRunning, 1);
    g_watchThread = CreateThread(nullptr, 64 * 1024, WatchdogThread, nullptr, 0, nullptr);
    if (!g_watchThread) InterlockedExchange(&g_watchRunning, 0);
}

void Shutdown() {
    g_stopWatch = 1;
    UnhookStubs();
    Sleep(20);   // a call that already entered a hook leaves it (its trampoline stays allocated)
    if (g_watchThread) {
        for (int i = 0; i < 100 && g_watchRunning; ++i) {
            if (WaitForSingleObject(g_watchThread, 0) == WAIT_OBJECT_0) break;
            Sleep(5);
        }
        CloseHandle(g_watchThread);
        g_watchThread = nullptr;
    }
    // The helper was never needed: end it (the job would, with the game).
    if (g_dumpProc && WaitForSingleObject(g_dumpProc, 0) == WAIT_TIMEOUT && g_reporting == 0) TerminateProcess(g_dumpProc, 0);
}

}  // namespace crash
}  // namespace gta2dx9
