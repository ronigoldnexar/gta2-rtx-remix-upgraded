// FIX-DEADLOCK-1 (remix-ste-start-game-thread-heap-deadlock-freeze): the stall sampler (dllmain.cpp)
// saw the game thread wait inside msvcrt's free() for nine minutes and could not say on what: the
// owner of a critical section is another thread, and the sampler only looked at the game thread.
// When the game thread has been stuck at one address for seconds the sampler now calls
// DumpAllThreads once, which writes:
//  - "stall dump: lock" lines: every critical section whose address sits on the game thread's
//    stack (the one RtlEnterCriticalSection waits on is among them), with its owner thread,
//    recursion and Wine's debug name ("heap.c: heap.cs" ...); plus msvcrt's and the process
//    heap's own lock, found in the heap header the same way;
//  - "stall dump: thread" lines: every thread of the process, its name (NameThisThread), its start
//    address and its stack as module+offset, each thread suspended only while its registers and
//    stack words are copied into static memory, and resumed before anything is formatted, logged
//    or allocated;
//  - "stall dump: guarded fault" lines: faults a GTA2_TRY swallowed (compat.cpp), which resume the
//    thread at the guard and so leave behind any lock taken between the guard and the fault.
#include "thread_watch.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <malloc.h>

#include "car_bodies.h"
#include "log.h"

namespace gta2dx9 {
namespace {

// Long-lived threads keep their slot; short-lived ones (a thread per job) share a ring.
constexpr int kMaxNames = 32;
volatile LONG g_nameCount = 0;
DWORD g_nameTid[kMaxNames];
const char* g_nameText[kMaxNames];
constexpr int kRing = 32;
volatile LONG g_ringCount = 0;
DWORD g_ringTid[kRing];
const char* g_ringText[kRing];

constexpr int kFaultRing = 16;
struct GuardedFault {
    DWORD tid, tick, code;
    uintptr_t at, reading;
};
GuardedFault g_faults[kFaultRing];
volatile LONG g_faultCount = 0;

const char* NameOf(DWORD tid) {
    const LONG n = g_nameCount < kMaxNames ? g_nameCount : kMaxNames;
    for (LONG i = n - 1; i >= 0; --i)
        if (g_nameTid[i] == tid && g_nameText[i]) return g_nameText[i];
    for (int i = 0; i < kRing; ++i)
        if (g_ringTid[i] == tid && g_ringText[i]) return g_ringText[i];
    return nullptr;
}

void Describe(uintptr_t address, char* out, size_t size) {
    HMODULE module = nullptr;
    char leaf[MAX_PATH] = "?";
    if (address >= 0x10000 &&
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(address), &module) && module) {
        char path[MAX_PATH] = {};
        if (GetModuleFileNameA(module, path, MAX_PATH)) {
            const char* slash = strrchr(path, '\\');
            snprintf(leaf, sizeof(leaf), "%s", slash ? slash + 1 : path);
        }
        snprintf(out, size, "%s+0x%X", leaf, static_cast<unsigned>(address - reinterpret_cast<uintptr_t>(module)));
    } else {
        snprintf(out, size, "%08X", static_cast<unsigned>(address));
    }
}

bool ReadMem(uintptr_t at, void* out, size_t size) {
    SIZE_T got = 0;
    return at >= 0x10000 && ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(at), out, size, &got) && got == size;
}

// A return address follows a call: E8 rel32 five bytes back, or FF /2 two, three or six back.
bool ReturnAddress(uintptr_t p) {
    MEMORY_BASIC_INFORMATION mbi;
    if (p < 0x10000 || !VirtualQuery(reinterpret_cast<LPCVOID>(p), &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) return false;
    if (!(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))) return false;
    unsigned char b[6];
    if (!ReadMem(p - 6, b, 6)) return false;   // b[k] = p[k - 6]
    return b[1] == 0xE8 || (b[4] == 0xFF && (b[5] & 0x38) == 0x10) || (b[3] == 0xFF && (b[4] & 0x38) == 0x10) ||
           (b[0] == 0xFF && (b[1] & 0x38) == 0x10);
}

// RTL_CRITICAL_SECTION (32-bit): DebugInfo, LockCount, RecursionCount, OwningThread (a thread id),
// LockSemaphore, SpinCount. Its debug record points back at it (DebugInfo->CriticalSection, +4),
// and Wine keeps a name string in DebugInfo->Spare[0] (+0x18).
struct CsView {
    uintptr_t at;
    LONG lockCount, recursion;
    DWORD owner;
    char name[64];
};
bool ReadCriticalSection(uintptr_t at, CsView* v) {
    if (at < 0x10000 || (at & 3)) return false;
    uintptr_t cs[6];
    if (!ReadMem(at, cs, sizeof(cs))) return false;
    const uintptr_t debug = cs[0];
    // debug == at is an empty list head (next == prev == itself), not a lock.
    if (debug < 0x10000 || debug == static_cast<uintptr_t>(-1) || debug == at) return false;
    const LONG recursion = static_cast<LONG>(cs[2]);
    const LONG lockCount = static_cast<LONG>(cs[1]);
    if (recursion < 0 || recursion > 4096 || cs[3] > 0x100000 || lockCount < -1 || lockCount > 65536)
        return false;   // a thread id, a sane depth and count
    uintptr_t back = 0;
    if (!ReadMem(debug + 4, &back, sizeof(back)) || back != at) return false;
    v->at = at;
    v->lockCount = static_cast<LONG>(cs[1]);
    v->recursion = static_cast<LONG>(cs[2]);
    v->owner = static_cast<DWORD>(cs[3]);
    v->name[0] = 0;
    uintptr_t spare = 0;
    if (ReadMem(debug + 0x18, &spare, sizeof(spare)) && spare >= 0x10000) {
        char text[64] = {};
        for (size_t i = 0; i + 1 < sizeof(text); ++i) {
            if (!ReadMem(spare + i, &text[i], 1)) { text[i] = 0; break; }
            if (!text[i]) break;
            if (text[i] < 0x20 || text[i] > 0x7E) { text[0] = 0; break; }
        }
        memcpy(v->name, text, sizeof(text));
    }
    return true;
}

void LogLock(const char* what, const CsView& v) {
    const char* owner = v.owner ? NameOf(v.owner) : nullptr;
    Log("stall dump: lock %s at %08X%s%s%s: owner thread %lu%s%s%s, lock count %ld, recursion %ld", what,
        static_cast<unsigned>(v.at), v.name[0] ? " (" : "", v.name, v.name[0] ? ")" : "",
        static_cast<unsigned long>(v.owner), owner ? " (" : "", owner ? owner : "", owner ? ")" : "", v.lockCount, v.recursion);
}

// The lock in a heap's header: the first critical section whose debug record points back at it.
bool HeapLockOf(HANDLE heap, CsView* v) {
    const uintptr_t base = reinterpret_cast<uintptr_t>(heap);
    if (!base) return false;
    for (uintptr_t off = 0; off < 0x400; off += 4)
        if (ReadCriticalSection(base + off, v)) return true;
    return false;
}

HANDLE MsvcrtHeap() {
    typedef intptr_t(__cdecl * GetHeapHandle)();
    HMODULE crt = GetModuleHandleA("msvcrt.dll");
    GetHeapHandle get = crt ? reinterpret_cast<GetHeapHandle>(GetProcAddress(crt, "_get_heap_handle")) : nullptr;
    return get ? reinterpret_cast<HANDLE>(get()) : nullptr;
}

constexpr int kStackWords = 1024;
uintptr_t g_words[kStackWords];   // the sampler's own buffer: one thread at a time

void FormatCallers(const uintptr_t* words, int count, char* line, size_t size, int maxFound) {
    size_t at = 0;
    int found = 0;
    line[0] = 0;
    for (int i = 0; i < count && found < maxFound && at + 64 < size; ++i) {
        if (words[i] < 0x10000 || !ReturnAddress(words[i])) continue;
        char one[160];
        Describe(words[i], one, sizeof(one));
        at += snprintf(line + at, size - at, "%s%s", found ? " < " : "", one);
        ++found;
    }
}

volatile LONG g_testHeld = 0;
CRITICAL_SECTION g_testLock;

DWORD WINAPI StallDumpTestThread(LPVOID) {
    NameThisThread("stall-dump test");
    EnterCriticalSection(&g_testLock);
    Log("stall_dump_test: thread %lu holds the test lock %p for 10 s; the game thread waits for it at its next frame",
        GetCurrentThreadId(), static_cast<void*>(&g_testLock));
    InterlockedExchange(&g_testHeld, 1);
    Sleep(10000);
    InterlockedExchange(&g_testHeld, 0);
    LeaveCriticalSection(&g_testLock);
    Log("stall_dump_test: released");
    return 0;
}

}  // namespace

void NameThisThread(const char* name, bool shortLived) {
    if (shortLived) {
        const LONG i = (InterlockedIncrement(&g_ringCount) - 1) % kRing;
        g_ringText[i] = name;
        g_ringTid[i] = GetCurrentThreadId();
        return;
    }
    const LONG i = InterlockedIncrement(&g_nameCount) - 1;
    if (i >= kMaxNames) return;
    g_nameText[i] = name;
    g_nameTid[i] = GetCurrentThreadId();
}

void NoteGuardedFault(uint32_t code, uintptr_t at, uintptr_t reading) {
    const LONG i = (InterlockedIncrement(&g_faultCount) - 1) % kFaultRing;
    GuardedFault& f = g_faults[i];
    f.tid = GetCurrentThreadId();
    f.tick = GetTickCount();
    f.code = code;
    f.at = at;
    f.reading = reading;
}

void DumpAllThreads(uint32_t gameThread, const uintptr_t* gameStack, int gameWords) {
    const DWORD self = GetCurrentThreadId();
    Log("stall dump: begin (game thread %lu, sampler %lu)", static_cast<unsigned long>(gameThread), static_cast<unsigned long>(self));
    // 1. The locks: critical sections on the game thread's stack, then the two heaps' own.
    {
        uintptr_t seen[16];
        int nseen = 0;
        for (int i = 0; i < gameWords && nseen < 16; ++i) {
            CsView v;
            if (!ReadCriticalSection(gameStack[i], &v)) continue;
            bool dup = false;
            for (int k = 0; k < nseen; ++k) dup = dup || seen[k] == v.at;
            if (dup) continue;
            seen[nseen++] = v.at;
            char what[48];
            snprintf(what, sizeof(what), "on the game thread's stack (word %d)", i);
            LogLock(what, v);
        }
        CsView v;
        HANDLE crt = MsvcrtHeap();
        if (crt && HeapLockOf(crt, &v)) LogLock("of the msvcrt heap", v);
        else Log("stall dump: msvcrt heap %p: lock not found", crt);
        HANDLE proc = GetProcessHeap();
        if (proc != crt && HeapLockOf(proc, &v)) LogLock("of the process heap", v);
    }
    // 2. The guarded faults swallowed so far (the newest 16).
    {
        const LONG total = g_faultCount;
        Log("stall dump: %ld guarded faults swallowed so far", total);
        for (LONG k = total > kFaultRing ? total - kFaultRing : 0; k < total; ++k) {
            const GuardedFault& f = g_faults[k % kFaultRing];
            char at[160];
            Describe(f.at, at, sizeof(at));
            const char* name = NameOf(f.tid);
            Log("stall dump: guarded fault %08lX in thread %lu%s%s%s at %s reading %08X, %lu ms ago", static_cast<unsigned long>(f.code),
                static_cast<unsigned long>(f.tid), name ? " (" : "", name ? name : "", name ? ")" : "", at,
                static_cast<unsigned>(f.reading), static_cast<unsigned long>(GetTickCount() - f.tick));
        }
    }
    // 3. Every thread. The list first (Wine's snapshot allocates from the process heap: if that
    // heap's lock is the stuck one this blocks the sampler, after the lines above are out).
    LogFlush();
    DWORD tids[256];
    int ntids = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap != INVALID_HANDLE_VALUE) {
        THREADENTRY32 te;
        te.dwSize = sizeof(te);
        const DWORD pid = GetCurrentProcessId();
        for (BOOL ok = Thread32First(snap, &te); ok && ntids < 256; ok = Thread32Next(snap, &te))
            if (te.th32OwnerProcessID == pid) tids[ntids++] = te.th32ThreadID;
        CloseHandle(snap);
    }
    typedef LONG(NTAPI * QueryThread)(HANDLE, int, PVOID, ULONG, PULONG);
    static QueryThread query = reinterpret_cast<QueryThread>(GetProcAddress(GetModuleHandleA("ntdll.dll"), "NtQueryInformationThread"));
    Log("stall dump: %d threads", ntids);
    for (int t = 0; t < ntids; ++t) {
        const DWORD tid = tids[t];
        const char* name = tid == self ? "stall sampler" : NameOf(tid);
        if (tid == gameThread) name = "game";
        HANDLE h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, tid);
        if (!h) {
            Log("stall dump: thread %lu%s%s%s: cannot open (%lu)", static_cast<unsigned long>(tid), name ? " (" : "",
                name ? name : "", name ? ")" : "", GetLastError());
            continue;
        }
        uintptr_t start = 0;
        if (query) query(h, 9 /* ThreadQuerySetWin32StartAddress */, &start, sizeof(start), nullptr);
        uintptr_t pc = 0;
        uintptr_t regs[8] = {};
        int words = 0;
        if (tid != self) {
            // Suspended from here to ResumeThread: no allocation, no log, no lock of ours.
            if (SuspendThread(h) != static_cast<DWORD>(-1)) {
                CONTEXT c = {};
                c.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
                if (GetThreadContext(h, &c)) {
                    pc = c.Eip;
                    regs[0] = c.Eax; regs[1] = c.Ebx; regs[2] = c.Ecx; regs[3] = c.Edx;
                    regs[4] = c.Esi; regs[5] = c.Edi; regs[6] = c.Ebp; regs[7] = c.Esp;
                    const uintptr_t sp = c.Esp;
                    SIZE_T got = 0;
                    if (ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(sp), g_words, sizeof(g_words), &got)) {
                        words = static_cast<int>(got / sizeof(uintptr_t));
                    } else {
                        for (; words < kStackWords; ++words)
                            if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(sp + words * sizeof(uintptr_t)),
                                                   &g_words[words], sizeof(uintptr_t), &got)) break;
                    }
                }
                ResumeThread(h);
            }
        }
        CloseHandle(h);
        char startText[160], pcText[160];
        Describe(start, startText, sizeof(startText));
        Describe(pc, pcText, sizeof(pcText));
        static char callers[1400];
        FormatCallers(g_words, words, callers, sizeof(callers), 14);
        Log("stall dump: thread %lu%s%s%s start %s at %s, callers %s", static_cast<unsigned long>(tid), name ? " (" : "",
            name ? name : "", name ? ")" : "", startText, tid == self ? "(this thread)" : pcText, callers);
        if (pc) {
            // The frame-pointer chain from ebp (Wine's builtins and most game code keep one): exact
            // callers where the stack scan above also lists stale words (RtlWakeAddressAll keeps a
            // 1 KB array of thread ids on its stack).
            char chain[1000];
            size_t at = 0;
            chain[0] = 0;
            uintptr_t bp = regs[6];
            for (int k = 0; k < 16 && bp >= 0x10000 && at + 64 < sizeof(chain); ++k) {
                uintptr_t fr[2] = {};
                if (!ReadMem(bp, fr, sizeof(fr)) || fr[1] < 0x10000) break;
                char one[160];
                Describe(fr[1], one, sizeof(one));
                at += snprintf(chain + at, sizeof(chain) - at, "%s%s", k ? " < " : "", one);
                if (fr[0] <= bp) break;   // a frame chain only grows up the stack
                bp = fr[0];
            }
            Log("stall dump: thread %lu ebp chain %s", static_cast<unsigned long>(tid), chain);
            Log("stall dump: thread %lu registers eax %08X ebx %08X ecx %08X edx %08X esi %08X edi %08X ebp %08X esp %08X",
                static_cast<unsigned long>(tid), static_cast<unsigned>(regs[0]), static_cast<unsigned>(regs[1]), static_cast<unsigned>(regs[2]),
                static_cast<unsigned>(regs[3]), static_cast<unsigned>(regs[4]), static_cast<unsigned>(regs[5]), static_cast<unsigned>(regs[6]),
                static_cast<unsigned>(regs[7]));
            // Wine's RtlWaitOnAddress / RtlWakeAddress* (ntdll sync.c) spin on a per-bucket lock
            // (struct futex_queue { list head; LONG lock; }, entries { next, prev, addr, tid } on the
            // waiters' stacks); a spinner holds the lock's address in ecx at its lock cmpxchg. A held
            // lock (-1) with nobody inside the bucket's code was left behind.
            if (tid == gameThread) {
                LONG lock = 0;
                if (ReadMem(regs[2], &lock, sizeof(lock)) && lock == -1) {
                    const uintptr_t head = regs[2] - 8;
                    uintptr_t e = 0;
                    ReadMem(head, &e, sizeof(e));
                    Log("stall dump: ecx %08X reads -1: a held spin lock; as a futex bucket its list head %08X -> %08X",
                        static_cast<unsigned>(regs[2]), static_cast<unsigned>(head), static_cast<unsigned>(e));
                    for (int k = 0; k < 12 && e && e != head; ++k) {
                        uintptr_t ent[4] = {};
                        if (!ReadMem(e, ent, sizeof(ent))) { Log("stall dump: futex entry %08X unreadable", static_cast<unsigned>(e)); break; }
                        const char* wn = NameOf(static_cast<DWORD>(ent[3]));
                        Log("stall dump: futex entry %08X next %08X prev %08X addr %08X tid %lu%s%s%s", static_cast<unsigned>(e),
                            static_cast<unsigned>(ent[0]), static_cast<unsigned>(ent[1]), static_cast<unsigned>(ent[2]),
                            static_cast<unsigned long>(ent[3]), wn ? " (" : "", wn ? wn : "", wn ? ")" : "");
                        e = ent[0];
                    }
                }
            }
        }
        LogFlush();   // one line at a time: the pending buffer stays small (a small block, never the heap's big-block path)
    }
    Log("stall dump: end");
    LogFlush();
}

void GuardedFaultsReport() {
    static LONG reported = 0;
    static int lines = 0;
    const LONG total = g_faultCount;
    if (total == reported || lines >= 200) return;
    LONG from = reported;
    if (total - from > kFaultRing) {
        Log("stall sampler: %ld guarded faults not shown (ring overrun)", total - kFaultRing - from);
        from = total - kFaultRing;
    }
    static HMODULE self = nullptr;
    if (!self)
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(&GuardedFaultsReport), &self);
    for (LONG k = from; k < total && lines < 200; ++k, ++lines) {
        const GuardedFault& f = g_faults[k % kFaultRing];
        char at[160];
        Describe(f.at, at, sizeof(at));
        HMODULE module = nullptr;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(f.at), &module);
        const char* name = NameOf(f.tid);
        Log("stall sampler: guarded fault %ld: %08lX in thread %lu%s%s%s at %s reading %08X%s", k + 1, static_cast<unsigned long>(f.code),
            static_cast<unsigned long>(f.tid), name ? " (" : "", name ? name : "", name ? ")" : "", at, static_cast<unsigned>(f.reading),
            module == self ? "" : " (outside gta2dx9.dll: a lock taken there is left held)");
    }
    reported = total;
}

void StallDumpTestPoll() {
    static DWORD last = 0;
    static int lastValue = 0;
    static bool made = false;
    const DWORD now = GetTickCount();
    if (now - last < 1000) return;
    last = now;
    const char* ini = CarBodiesDevIni();
    if (!ini || !ini[0]) return;
    const int value = GetPrivateProfileIntA("devtools", "stall_dump_test", 0, ini);
    if (value && !lastValue) {
        if (!made) { InitializeCriticalSection(&g_testLock); made = true; }
        if (HANDLE h = CreateThread(nullptr, 0, StallDumpTestThread, nullptr, 0, nullptr)) CloseHandle(h);
    }
    lastValue = value;
}

}  // namespace gta2dx9

namespace gta2dx9 {
void StallDumpTestFrame() {
    static LONG done = 0;
    if (!g_testHeld || done) return;
    done = 1;
    Log("stall_dump_test: the game thread waits for the test lock");
    EnterCriticalSection(&g_testLock);
    LeaveCriticalSection(&g_testLock);
    Log("stall_dump_test: the game thread has the test lock: frames go on");
}
}  // namespace gta2dx9
