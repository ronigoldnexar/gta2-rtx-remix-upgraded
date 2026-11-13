// FIX-PERF-4: memory counters, the `mem:` log lines and the allocation-failure path.
// See mem_stats.h and docs/performance.md, "Memory growth and the bad_alloc crash".
#include "mem_stats.h"

#include "log.h"
#include "view_modes.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <new>

namespace gta2dx9 {
namespace {

std::atomic<long long> g_liveBytes{0};
std::atomic<long long> g_liveBlocks{0};
std::atomic<long long> g_peakBytes{0};
std::atomic<long long> g_totalAllocs{0};

// 16 bytes in front of every block (the size), so the block keeps malloc's alignment.
constexpr size_t kHeader = 16;

// Released on the first failed allocation so the FAULT line, the log and the drop to
// classic have room to run.
constexpr size_t kReserveBytes = 24u << 20;
void* g_reserve = nullptr;
std::atomic<int> g_emergency{0};
std::atomic<int> g_failures{0};
thread_local int t_inFailure = 0;

void NotePeak(long long live) {
    long long peak = g_peakBytes.load(std::memory_order_relaxed);
    while (live > peak && !g_peakBytes.compare_exchange_weak(peak, live, std::memory_order_relaxed)) {}
}

bool OnAllocFailure(size_t bytes, int attempt);

// FIX-PERF-5: where the allocations come from. With GTA2DX9_ALLOC_SITES=1 every 256th allocation's stack is
// scanned for return addresses inside this DLL (no frame pointers under -O2, so the first three words that
// point into our code); each minute line is followed by the twenty commonest sites as offsets from the
// DLL's base (symbolise with the build's gta2dx9.map).
int g_siteSampling = -1;   // -1 not read yet
uintptr_t g_dllBase = 0, g_dllEnd = 0;
struct AllocSite { uint32_t w[6]; long long n, bytes; };
constexpr int kSites = 2048;
AllocSite g_sites[kSites];
volatile LONG g_siteLock = 0;
long long g_siteSamples = 0;

void SampleAllocSite(size_t bytes) {
    if (!g_dllEnd) {
        HMODULE self = nullptr;
        if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                reinterpret_cast<LPCSTR>(&SampleAllocSite), &self) || !self) { g_siteSampling = 0; return; }
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(self);
        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(reinterpret_cast<const char*>(self) + dos->e_lfanew);
        g_dllBase = reinterpret_cast<uintptr_t>(self);
        g_dllEnd = g_dllBase + nt->OptionalHeader.SizeOfImage;
    }
    uint32_t found[6] = {0, 0, 0, 0, 0, 0};
    int k = 0;
    volatile uintptr_t marker = 0;
    const uintptr_t* sp = const_cast<const uintptr_t*>(&marker);
    // Never past this thread's stack base (a worker's stack ends a few hundred bytes above its entry).
    const uintptr_t top = reinterpret_cast<uintptr_t>(reinterpret_cast<NT_TIB*>(NtCurrentTeb())->StackBase);
    const int words = top > reinterpret_cast<uintptr_t>(sp) ? static_cast<int>((std::min<uintptr_t>)((top - reinterpret_cast<uintptr_t>(sp)) / sizeof(uintptr_t), 256)) : 0;
    for (int i = 1; i < words && k < 6; ++i) {
        const uintptr_t w = sp[i];
        if (w > g_dllBase + 0x1000 && w < g_dllEnd) found[k++] = static_cast<uint32_t>(w - g_dllBase);
    }
    if (InterlockedCompareExchange(&g_siteLock, 1, 0) != 0) return;
    ++g_siteSamples;
    uint32_t h = 0;
    for (uint32_t f : found) h = h * 2654435761u ^ f;
    for (int probe = 0; probe < 32; ++probe) {
        AllocSite& s = g_sites[(h + probe) & (kSites - 1)];
        if (s.n == 0) memcpy(s.w, found, sizeof found);
        if (memcmp(s.w, found, sizeof found) == 0) { ++s.n; s.bytes += static_cast<long long>(bytes); break; }
    }
    InterlockedExchange(&g_siteLock, 0);
}

void LogAllocSites() {
    if (g_siteSampling <= 0 || !g_siteSamples) return;
    if (InterlockedCompareExchange(&g_siteLock, 1, 0) != 0) return;
    static AllocSite top[20];
    int n = 0;
    for (const AllocSite& s : g_sites) {
        if (!s.n) continue;
        int at;
        if (n < 20) at = n++;
        else if (s.n > top[19].n) at = 19;
        else continue;
        top[at] = s;
        while (at > 0 && top[at - 1].n < top[at].n) { const AllocSite t = top[at - 1]; top[at - 1] = top[at]; top[at] = t; --at; }
    }
    const long long samples = g_siteSamples;
    // Each line covers the minute since the last (the load's own allocations do not drown the play's).
    memset(g_sites, 0, sizeof g_sites);
    g_siteSamples = 0;
    InterlockedExchange(&g_siteLock, 0);
    char line[2560];
    int len = snprintf(line, sizeof(line), "mem: alloc sites (1 in 256, %lld samples in the last minute; the first six stack words inside the DLL as offsets, share, mean bytes):", samples);
    for (int i = 0; i < n && len > 0 && len < static_cast<int>(sizeof(line)) - 120; ++i)
        len += snprintf(line + len, sizeof(line) - len, " %x/%x/%x/%x/%x/%x %.1f%% %lldB;", top[i].w[0], top[i].w[1], top[i].w[2], top[i].w[3], top[i].w[4], top[i].w[5],
                        100.0 * static_cast<double>(top[i].n) / static_cast<double>(samples), top[i].bytes / top[i].n);
    Log("%s", line);
}

// MEM-FRAG: a big block (texel buffers: a 512x512 map is 1 MB) does not go through the CRT heap. Wine serves a heap
// block that size with its own mapping, placed anywhere in the free space: one left alive in the middle of the big
// free block above 2 GB cut it in two (vawatch: 2048 MB -> 836 MB at the level's load, a 1.06 MB private commit).
// Mapped top-down they stack at the top of the address space instead (GTA2DX9_BIG_ALLOC_TOPDOWN=0: as before).
constexpr size_t kBigAlloc = 256u << 10;
constexpr size_t kBigFlag = static_cast<size_t>(1) << (sizeof(size_t) * 8 - 1);
bool BigTopDown() {
    static int on = -1;
    if (on < 0) { char v[8] = {}; on = !(GetEnvironmentVariableA("GTA2DX9_BIG_ALLOC_TOPDOWN", v, sizeof v) && v[0] == '0'); }
    return on != 0;
}

void* CountedAlloc(size_t bytes) {
    for (int attempt = 0;; ++attempt) {
        const bool big = bytes >= kBigAlloc && BigTopDown();
        void* p = big ? VirtualAlloc(nullptr, bytes + kHeader, MEM_RESERVE | MEM_COMMIT | MEM_TOP_DOWN, PAGE_READWRITE) : malloc(bytes + kHeader);
        if (p) {
            *static_cast<size_t*>(p) = big ? (bytes | kBigFlag) : bytes;
            const long long live = g_liveBytes.fetch_add(static_cast<long long>(bytes), std::memory_order_relaxed) + static_cast<long long>(bytes);
            g_liveBlocks.fetch_add(1, std::memory_order_relaxed);
            const long long count = g_totalAllocs.fetch_add(1, std::memory_order_relaxed);
            NotePeak(live);
            if ((count & 255) == 0 && g_siteSampling != 0) {
                if (g_siteSampling < 0) {
                    char buf[8] = {};
                    g_siteSampling = GetEnvironmentVariableA("GTA2DX9_ALLOC_SITES", buf, sizeof buf) && buf[0] == '1' ? 1 : 0;
                }
                if (g_siteSampling > 0) SampleAllocSite(bytes);
            }
            return static_cast<char*>(p) + kHeader;
        }
        if (!OnAllocFailure(bytes, attempt)) return nullptr;
    }
}

void CountedFree(void* q) {
    if (!q) return;
    char* p = static_cast<char*>(q) - kHeader;
    const size_t word = *reinterpret_cast<size_t*>(p);
    const size_t bytes = word & ~kBigFlag;
    g_liveBytes.fetch_sub(static_cast<long long>(bytes), std::memory_order_relaxed);
    g_liveBlocks.fetch_sub(1, std::memory_order_relaxed);
    if (word & kBigFlag) VirtualFree(p, 0, MEM_RELEASE);
    else free(p);
}

// The gauges of one full line, appended without allocating (the failure path uses it too).
char g_gauges[6144];
size_t g_gaugesLen = 0;

struct VaSurvey {
    double privMb = 0, mappedMb = 0, imageMb = 0, reservedMb = 0, freeMb = 0, largestFreeMb = 0;
    int regions = 0;
};

VaSurvey SurveyAddressSpace() {
    VaSurvey s;
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t a = reinterpret_cast<uintptr_t>(si.lpMinimumApplicationAddress);
    const uintptr_t end = reinterpret_cast<uintptr_t>(si.lpMaximumApplicationAddress);
    MEMORY_BASIC_INFORMATION mbi;
    const double mb = 1.0 / (1 << 20);
    while (a < end && VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == sizeof(mbi)) {
        const double size = static_cast<double>(mbi.RegionSize);
        if (mbi.State == MEM_COMMIT) {
            if (mbi.Type == MEM_IMAGE) s.imageMb += size * mb;
            else if (mbi.Type == MEM_MAPPED) s.mappedMb += size * mb;
            else s.privMb += size * mb;
        } else if (mbi.State == MEM_RESERVE) {
            s.reservedMb += size * mb;
        } else {
            s.freeMb += size * mb;
            if (size * mb > s.largestFreeMb) s.largestFreeMb = size * mb;
        }
        ++s.regions;
        const uintptr_t next = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        if (next <= a) break;
        a = next;
    }
    return s;
}

// MEM-FRAG: who splits the largest free block. GTA2DX9_VA_WATCH=1: every second (first 3 minutes), the address
// space is walked; whenever the largest free block shrinks by more than 32 MB, every region now inside the old
// block's range is logged (base, size, state, type, protection, allocation base) with the time, so the allocation
// that cut it (and where it sits in the block) is named.
struct FreeBlock { uintptr_t base = 0; size_t size = 0; };
FreeBlock LargestFree() {
    FreeBlock best;
    SYSTEM_INFO si; GetSystemInfo(&si);
    uintptr_t a = reinterpret_cast<uintptr_t>(si.lpMinimumApplicationAddress);
    const uintptr_t end = reinterpret_cast<uintptr_t>(si.lpMaximumApplicationAddress);
    MEMORY_BASIC_INFORMATION mbi;
    while (a < end && VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == sizeof(mbi)) {
        if (mbi.State == MEM_FREE && mbi.RegionSize > best.size) { best.base = reinterpret_cast<uintptr_t>(mbi.BaseAddress); best.size = mbi.RegionSize; }
        const uintptr_t next = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
        if (next <= a) break;
        a = next;
    }
    return best;
}
void VaWatchTick(unsigned long long now) {
    static int on = -1;
    if (on < 0) { char v[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_VA_WATCH", v, sizeof v) && v[0] == '1'; }
    if (!on) return;
    static unsigned long long start = 0, last = 0;
    if (!start) start = now;
    if (now - start > 180000 || now - last < 1000) return;
    last = now;
    static FreeBlock prev;
    const FreeBlock cur = LargestFree();
    if (prev.size && cur.size + (32u << 20) < prev.size) {
        Log("vawatch: t=%.1f s largest free block %08lx+%.1fMB -> %08lx+%.1fMB; inside the old block now:", (now - start) / 1000.0,
            static_cast<unsigned long>(prev.base), prev.size / 1048576.0, static_cast<unsigned long>(cur.base), cur.size / 1048576.0);
        MEMORY_BASIC_INFORMATION mbi; uintptr_t a = prev.base; int n = 0;
        while (a < prev.base + prev.size && n < 24 && VirtualQuery(reinterpret_cast<void*>(a), &mbi, sizeof(mbi)) == sizeof(mbi)) {
            if (mbi.State != MEM_FREE)
                Log("vawatch:   %08lx +%.2fMB state %s type %s protect %lx allocbase %08lx", static_cast<unsigned long>(reinterpret_cast<uintptr_t>(mbi.BaseAddress)),
                    mbi.RegionSize / 1048576.0, mbi.State == MEM_COMMIT ? "commit" : "reserve",
                    mbi.Type == MEM_IMAGE ? "image" : mbi.Type == MEM_MAPPED ? "mapped" : "private", static_cast<unsigned long>(mbi.Protect),
                    static_cast<unsigned long>(reinterpret_cast<uintptr_t>(mbi.AllocationBase)));
            ++n;
            const uintptr_t next = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
            if (next <= a) break;
            a = next;
        }
    }
    if (!prev.size || cur.size != prev.size) {
        static int logged = 0;
        if (logged++ < 200) Log("vawatch: t=%.1f s largest free %08lx+%.1fMB", (now - start) / 1000.0, static_cast<unsigned long>(cur.base), cur.size / 1048576.0);
    }
    prev = cur;
}

// VmSize / VmRSS / RssAnon / RssFile of this process as Linux sees it. Under Wine a file is
// opened by the wineserver, so Z:\proc\self is the server: the game's own entry is found once
// by its comm ("gta2.exe") among the container's /proc entries.
bool ReadSmallFile(const char* path, char* buf, size_t cap) {
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    DWORD got = 0, total = 0;
    while (total < cap - 1 && ReadFile(f, buf + total, static_cast<DWORD>(cap - 1 - total), &got, nullptr) && got) total += got;
    CloseHandle(f);
    buf[total] = 0;
    return total > 0;
}

char g_procStatusPath[64] = {};
long g_vmSizeMb = 0;   // the last VmSize read (0: none)
int g_procLookups = 0;

const char* ProcStatusPath() {
    if (g_procStatusPath[0] || g_procLookups >= 3) return g_procStatusPath[0] ? g_procStatusPath : nullptr;
    ++g_procLookups;
    char exe[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, exe, MAX_PATH);
    const char* base = strrchr(exe, '\\');
    base = base ? base + 1 : exe;
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA("Z:\\proc\\*", &fd);
    if (h == INVALID_HANDLE_VALUE) return nullptr;
    do {
        if (fd.cFileName[0] < '0' || fd.cFileName[0] > '9') continue;
        char path[64], comm[64];
        snprintf(path, sizeof(path), "Z:\\proc\\%s\\comm", fd.cFileName);
        if (!ReadSmallFile(path, comm, sizeof(comm))) continue;
        char* nl = strchr(comm, '\n');
        if (nl) *nl = 0;
        if (_stricmp(comm, base) == 0) {
            snprintf(g_procStatusPath, sizeof(g_procStatusPath), "Z:\\proc\\%s\\status", fd.cFileName);
            break;
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return g_procStatusPath[0] ? g_procStatusPath : nullptr;
}

void ProcStatus(char* out, size_t cap) {
    out[0] = 0;
    const char* path = ProcStatusPath();
    char buf[4096];
    if (!path || !ReadSmallFile(path, buf, sizeof(buf))) return;
    size_t n = 0;
    const char* keys[] = {"VmPeak:", "VmSize:", "VmRSS:", "RssAnon:", "RssFile:"};
    for (const char* k : keys) {
        const char* p = strstr(buf, k);
        if (!p) continue;
        long kb = strtol(p + strlen(k), nullptr, 10);
        if (k[2] == 'S') g_vmSizeMb = kb / 1024;   // VmSize
        const int w = snprintf(out + n, cap - n, " %.*s=%ld", static_cast<int>(strlen(k) - 1), k, kb / 1024);
        if (w > 0 && static_cast<size_t>(w) < cap - n) n += w;
    }
}

unsigned long long g_lastMinuteTick = 0;
unsigned long long g_startTick = 0;
int g_viewChanges = 0;
int g_memLog = -1;
bool g_emergencyHandled = false;

long CeilingMb() {
    static long ceiling = -1;
    if (ceiling < 0) {
        char v[16] = {};
        ceiling = GetEnvironmentVariableA("GTA2DX9_MEM_CEILING_MB", v, sizeof(v)) ? atol(v) : 3900;
        if (ceiling <= 0) ceiling = 1 << 30;   // 0: off
    }
    return ceiling;
}

bool MemLogOn() {
    if (g_memLog < 0) {
        char v[8] = {};
        g_memLog = !(GetEnvironmentVariableA("GTA2DX9_MEM_LOG", v, sizeof(v)) && v[0] == '0');
    }
    return g_memLog != 0;
}

bool OnAllocFailure(size_t bytes, int attempt) {
    if (t_inFailure) return false;   // the failure path itself ran out: give up
    t_inFailure = 1;
    const int nth = g_failures.fetch_add(1) + 1;
    bool retry = false;
    if (attempt == 0 && g_reserve) {
        void* r = g_reserve;
        g_reserve = nullptr;
        VirtualFree(r, 0, MEM_RELEASE);
        g_emergency.store(1);
        retry = true;
    }
    char line[256];
    snprintf(line, sizeof(line), "FAULT: allocation of %lu bytes failed (failure %d, attempt %d)%s", static_cast<unsigned long>(bytes), nth,
             attempt, retry ? ": the emergency reserve is released and the view drops to classic" : "");
    Log("%s", line);
    if (nth <= 3) MemStatsLog("allocation failure", 1);   // no gauges: any thread may be here
    LogFlush();
    t_inFailure = 0;
    return retry;
}

std::terminate_handler g_previousTerminate = nullptr;
void OnTerminate() {
    // The process is ending on an exception nobody caught (FIX-STABILITY-1's handler, installed after
    // this one, writes the FAULT line with the exception and the window state, then calls this): the
    // memory counters go with it, since std::bad_alloc is the exception a full address space throws.
    if (g_reserve) { VirtualFree(g_reserve, 0, MEM_RELEASE); g_reserve = nullptr; }
    MemStatsLog("at std::terminate", 1);
    LogFlush();
    if (g_previousTerminate) g_previousTerminate();
    abort();
}

}  // namespace

HeapCounters HeapCountersNow() {
    return HeapCounters{g_liveBytes.load(), g_liveBlocks.load(), g_peakBytes.load(), g_totalAllocs.load()};
}

void MemGauge(const char* name, double entries, double bytes) {
    if (g_gaugesLen >= sizeof(g_gauges) - 64) return;
    const int w = bytes >= 0 ? snprintf(g_gauges + g_gaugesLen, sizeof(g_gauges) - g_gaugesLen, " %s=%.0f/%.1fMB", name, entries, bytes / (1 << 20))
                             : snprintf(g_gauges + g_gaugesLen, sizeof(g_gauges) - g_gaugesLen, " %s=%.0f", name, entries);
    if (w > 0 && static_cast<size_t>(w) < sizeof(g_gauges) - g_gaugesLen) g_gaugesLen += w;
}

void MemStatsLog(const char* why, int full) {
    const HeapCounters h = HeapCountersNow();
    const double mb = 1.0 / (1 << 20);
    const double minutes = g_startTick ? (GetTickCount64() - g_startTick) / 60000.0 : 0.0;
    if (!full) {
        Log("mem: %s t=%.2f min heap live=%.1fMB blocks=%lld peak=%.1fMB allocs=%lld", why, minutes, h.liveBytes * mb, h.liveBlocks,
            h.peakBytes * mb, h.totalAllocs);
        return;
    }
    const VaSurvey va = SurveyAddressSpace();
    char proc[160];
    ProcStatus(proc, sizeof(proc));
    Log("mem: %s t=%.2f min heap live=%.1fMB blocks=%lld peak=%.1fMB allocs=%lld | va commit private=%.0fMB mapped=%.0fMB image=%.0fMB "
        "reserved=%.0fMB free=%.0fMB largest_free=%.1fMB regions=%d |%s",
        why, minutes, h.liveBytes * mb, h.liveBlocks, h.peakBytes * mb, h.totalAllocs, va.privMb, va.mappedMb, va.imageMb, va.reservedMb,
        va.freeMb, va.largestFreeMb, va.regions, proc);
    if (full < 2) return;
    g_gaugesLen = 0;
    g_gauges[0] = 0;
    ModelStoreMemGauges();
    CarBodiesMemGauges();
    TextureStoreMemGauges();
    LiveGeometryMemGauges();
    RagdollMemGauges();
    VehicleFxMemGauges();
    CarGlassMemGauges();
    MapObjectsMemGauges();
    Log("mem: caches%s", g_gauges);
    LogAllocSites();
}

void MemStatsTick() {
    // The reserve is taken at the top of the address space once the game runs (not at DLL
    // load: the game's pools are placed at level load and the low 2 GB is theirs first).
    static bool armed = false;
    if (!armed) {
        armed = true;
        g_reserve = VirtualAlloc(nullptr, kReserveBytes, MEM_RESERVE | MEM_COMMIT | MEM_TOP_DOWN, PAGE_READWRITE);
    }
    if (g_emergency.load() && !g_emergencyHandled) {
        g_emergencyHandled = true;
        Log("FAULT: memory emergency: the street views are off for the rest of the session (classic only)");
        MemStatsLog("emergency", 2);
    }
    if (g_emergency.load() && CurrentViewMode() != ViewMode::Classic) SetViewMode(ViewMode::Classic);
    VaWatchTick(GetTickCount64());
    if (!MemLogOn()) return;
    const unsigned long long now = GetTickCount64();
    if (!g_startTick) g_startTick = now;
    if (!g_lastMinuteTick || now - g_lastMinuteTick >= 60000) {
        g_lastMinuteTick = now;
        MemStatsLog("minute", 2);
    }
    // The ceiling watchdog, every 5 s: wined3d answers a map it cannot back with a null pointer
    // (fp4_sw_base: a vertex buffer Lock at VmSize 3964 MB, then a fault), long before an exception
    // could be caught, so the street views are left while there is still room.
    static unsigned long long lastCheck = 0;
    if (!g_emergency.load() && now - lastCheck >= 5000) {
        lastCheck = now;
        char proc[160];
        ProcStatus(proc, sizeof(proc));
        const VaSurvey va = g_vmSizeMb ? VaSurvey{} : SurveyAddressSpace();   // no /proc (Windows): Wine's/Windows' own count
        const bool high = g_vmSizeMb ? g_vmSizeMb >= CeilingMb() : va.freeMb < 96.0;
        if (high) {
            Log("FAULT: memory ceiling: VmSize %ld MB (limit %ld), free %.0f MB: the street views stop here (GTA2DX9_MEM_CEILING_MB)",
                g_vmSizeMb, CeilingMb(), va.freeMb);
            g_emergency.store(1);
        }
    }
}

void MemStatsViewChange(int fromMode, int toMode) {
    if (!MemLogOn()) return;
    ++g_viewChanges;
    char why[48];
    snprintf(why, sizeof(why), "view %d->%d #%d", fromMode, toMode, g_viewChanges);
    MemStatsLog(why, (g_viewChanges % 32) == 0 ? 2 : 0);
}

bool MemoryEmergency() { return g_emergency.load() != 0; }

void MemStatsInit() {
    g_previousTerminate = std::set_terminate(OnTerminate);
}

}  // namespace gta2dx9

// The DLL's own operator new/delete: counted, and an allocation failure goes through the
// FAULT/emergency path above before std::bad_alloc is thrown.
void* operator new(size_t n) {
    void* p = gta2dx9::CountedAlloc(n);
    if (!p) throw std::bad_alloc();
    return p;
}
void* operator new[](size_t n) {
    void* p = gta2dx9::CountedAlloc(n);
    if (!p) throw std::bad_alloc();
    return p;
}
void* operator new(size_t n, const std::nothrow_t&) noexcept { return gta2dx9::CountedAlloc(n); }
void* operator new[](size_t n, const std::nothrow_t&) noexcept { return gta2dx9::CountedAlloc(n); }
void operator delete(void* p) noexcept { gta2dx9::CountedFree(p); }
void operator delete[](void* p) noexcept { gta2dx9::CountedFree(p); }
void operator delete(void* p, size_t) noexcept { gta2dx9::CountedFree(p); }
void operator delete[](void* p, size_t) noexcept { gta2dx9::CountedFree(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { gta2dx9::CountedFree(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { gta2dx9::CountedFree(p); }
