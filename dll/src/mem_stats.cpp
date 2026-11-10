// FIX-PERF-4: memory counters, the `mem:` log lines and the allocation-failure path.
// See mem_stats.h and docs/performance.md, "Memory growth and the bad_alloc crash".
#include "mem_stats.h"

#include "log.h"
#include "view_modes.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <atomic>
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

void* CountedAlloc(size_t bytes) {
    for (int attempt = 0;; ++attempt) {
        void* p = malloc(bytes + kHeader);
        if (p) {
            *static_cast<size_t*>(p) = bytes;
            const long long live = g_liveBytes.fetch_add(static_cast<long long>(bytes), std::memory_order_relaxed) + static_cast<long long>(bytes);
            g_liveBlocks.fetch_add(1, std::memory_order_relaxed);
            g_totalAllocs.fetch_add(1, std::memory_order_relaxed);
            NotePeak(live);
            return static_cast<char*>(p) + kHeader;
        }
        if (!OnAllocFailure(bytes, attempt)) return nullptr;
    }
}

void CountedFree(void* q) {
    if (!q) return;
    char* p = static_cast<char*>(q) - kHeader;
    g_liveBytes.fetch_sub(static_cast<long long>(*reinterpret_cast<size_t*>(p)), std::memory_order_relaxed);
    g_liveBlocks.fetch_sub(1, std::memory_order_relaxed);
    free(p);
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

void OnTerminate() {
    // An exception nobody caught (std::bad_alloc included) used to end the process with only
    // the C++ runtime's message on stderr: leave the reason and the counters in the log first.
    const char* what = "unknown";
    try {
        std::exception_ptr e = std::current_exception();
        if (e) std::rethrow_exception(e);
        what = "no active exception";
    } catch (const std::bad_alloc&) {
        what = "std::bad_alloc";
    } catch (const std::exception& ex) {
        what = ex.what();
    } catch (...) {
    }
    if (g_reserve) { VirtualFree(g_reserve, 0, MEM_RELEASE); g_reserve = nullptr; }
    Log("FAULT: std::terminate: uncaught exception (%s); the process ends now", what);
    LogFlush();
    MemStatsLog("terminate", 1);
    LogFlush();
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
    std::set_terminate(OnTerminate);
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
