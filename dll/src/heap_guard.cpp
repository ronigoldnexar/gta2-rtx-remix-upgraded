// FIX-HANG-1 diagnostics: a guard-page heap for the Remix bridge client (d3d9.dll), the DLL-targeted page heap that
// Image File Execution Options would not give us (PageHeapTargetDlls did nothing on this Windows build, checked with a
// test DLL). [devtools] bridge_guard_heap=1 patches the import table entries of HeapAlloc / HeapFree / HeapReAlloc /
// HeapSize in the bridge's d3d9.dll so that every block it allocates ends at a no-access page: a write past its end (the
// bridge copying more than it allocated, or our code writing past a locked vertex/index/texture shadow buffer) faults
// at the writer and the fatal report names it; a block is decommitted when freed, so a write after Unlock into a
// freed shadow buffer faults too. Blocks made before the patch are forwarded to the real heap.
// Off by default; this is a diagnostic with a large address-space cost (bridge_guard_arena_mb, default 600).
#include "heap_guard.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>
#include <cstring>

#include "log.h"

namespace gta2dx9 {
namespace {

constexpr uintptr_t kPage = 4096;
constexpr uint32_t kMagic = 0xB1D6E0CD;

struct Header { uint32_t magic, size, pages, pad; };   // 16 bytes just before the user pointer

uintptr_t g_arena = 0, g_arenaEnd = 0, g_bump = 0;
CRITICAL_SECTION g_lock;
volatile LONG g_ready = 0;
volatile LONG g_exhausted = 0;
volatile LONG g_allocs = 0, g_frees = 0, g_forwarded = 0;
volatile LONG g_liveBytes = 0;

// Freed runs (page offset, page count) wait in a ring before their address space is reused.
struct Run { uintptr_t at; uint32_t pages; };
constexpr int kQuarantine = 16384;
Run g_quarantine[kQuarantine];
int g_qHead = 0, g_qCount = 0;
uint64_t g_qPages = 0;
constexpr int kFreeRuns = 4096;
Run g_free[kFreeRuns];
int g_freeCount = 0;

typedef LPVOID(WINAPI* HeapAllocFn)(HANDLE, DWORD, SIZE_T);
typedef BOOL(WINAPI* HeapFreeFn)(HANDLE, DWORD, LPVOID);
typedef LPVOID(WINAPI* HeapReAllocFn)(HANDLE, DWORD, LPVOID, SIZE_T);
typedef SIZE_T(WINAPI* HeapSizeFn)(HANDLE, DWORD, LPCVOID);
HeapAllocFn g_realAlloc = nullptr;
HeapFreeFn g_realFree = nullptr;
HeapReAllocFn g_realReAlloc = nullptr;
HeapSizeFn g_realSize = nullptr;

bool Ours(const void* p) {
    const uintptr_t a = reinterpret_cast<uintptr_t>(p);
    return a >= g_arena && a < g_arenaEnd;
}

// Takes `pages` data pages plus one guard page from the arena; the guard stays reserved, never committed.
uintptr_t TakeRun(uint32_t pages) {
    const uint32_t need = pages + 1;
    for (int i = 0; i < g_freeCount; ++i) {
        if (g_free[i].pages == need) {
            const uintptr_t at = g_free[i].at;
            g_free[i] = g_free[--g_freeCount];
            return at;
        }
    }
    if (g_bump + static_cast<uintptr_t>(need) * kPage > g_arenaEnd) {
        // Recycle the oldest quarantined runs of this size or larger (no coalescing: the sizes repeat).
        for (int k = 0; k < g_qCount; ++k) {
            Run& r = g_quarantine[(g_qHead + k) % kQuarantine];
            if (r.pages == need) { const uintptr_t at = r.at; r = g_quarantine[(g_qHead + g_qCount - 1) % kQuarantine]; --g_qCount; g_qPages -= need; return at; }
        }
        return 0;
    }
    const uintptr_t at = g_bump;
    g_bump += static_cast<uintptr_t>(need) * kPage;
    return at;
}

void* GuardAlloc(SIZE_T n, bool zero) {
    if (!n) n = 1;
    const SIZE_T rounded = (n + 15) & ~static_cast<SIZE_T>(15);
    const SIZE_T total = rounded + sizeof(Header);
    const uint32_t pages = static_cast<uint32_t>((total + kPage - 1) / kPage);
    EnterCriticalSection(&g_lock);
    const uintptr_t run = TakeRun(pages);
    LeaveCriticalSection(&g_lock);
    if (!run) return nullptr;
    if (!VirtualAlloc(reinterpret_cast<void*>(run), static_cast<SIZE_T>(pages) * kPage, MEM_COMMIT, PAGE_READWRITE)) return nullptr;
    const uintptr_t guard = run + static_cast<uintptr_t>(pages) * kPage;
    const uintptr_t user = guard - rounded;
    Header* h = reinterpret_cast<Header*>(user - sizeof(Header));
    h->magic = kMagic;
    h->size = static_cast<uint32_t>(n);
    h->pages = pages;
    // Fresh committed pages are zero; a recycled run was decommitted, so it is zero too.
    (void)zero;
    InterlockedIncrement(&g_allocs);
    InterlockedExchangeAdd(&g_liveBytes, static_cast<LONG>(n));
    return reinterpret_cast<void*>(user);
}

bool GuardFree(void* p) {
    Header* h = reinterpret_cast<Header*>(reinterpret_cast<uintptr_t>(p) - sizeof(Header));
    if (h->magic != kMagic) {
        Log("bridge guard heap: free of %p with a damaged header (magic %08X): the bytes before the block were overwritten", p, h->magic);
        LogFlush();
        return false;
    }
    const uint32_t pages = h->pages;
    const uintptr_t guard = (reinterpret_cast<uintptr_t>(p) + 15) & ~static_cast<uintptr_t>(15);
    (void)guard;
    // Where the run starts: the block ends at a page boundary (the guard page), so count back `pages` from there.
    const uintptr_t end = (reinterpret_cast<uintptr_t>(p) + h->size + 15) & ~static_cast<uintptr_t>(15);
    const uintptr_t run = end - static_cast<uintptr_t>(pages) * kPage;
    InterlockedExchangeAdd(&g_liveBytes, -static_cast<LONG>(h->size));
    h->magic = 0xDEADDEAD;
    VirtualFree(reinterpret_cast<void*>(run), static_cast<SIZE_T>(pages) * kPage, MEM_DECOMMIT);
    EnterCriticalSection(&g_lock);
    if (g_qCount == kQuarantine) {
        const Run old = g_quarantine[g_qHead];
        g_qHead = (g_qHead + 1) % kQuarantine;
        --g_qCount;
        g_qPages -= old.pages;
        if (g_freeCount < kFreeRuns) g_free[g_freeCount++] = old;
    }
    g_quarantine[(g_qHead + g_qCount) % kQuarantine] = Run{run, pages + 1};
    ++g_qCount;
    g_qPages += pages + 1;
    // Keep about 64 MB of address space quarantined, no more than that.
    while (g_qPages * kPage > (64u << 20) && g_qCount > 0) {
        const Run old = g_quarantine[g_qHead];
        g_qHead = (g_qHead + 1) % kQuarantine;
        --g_qCount;
        g_qPages -= old.pages;
        if (g_freeCount < kFreeRuns) g_free[g_freeCount++] = old;
    }
    LeaveCriticalSection(&g_lock);
    InterlockedIncrement(&g_frees);
    return true;
}

LPVOID WINAPI HookAlloc(HANDLE heap, DWORD flags, SIZE_T n) {
    if (g_ready && heap == GetProcessHeap()) {
        void* p = GuardAlloc(n, (flags & HEAP_ZERO_MEMORY) != 0);
        if (p) return p;
        if (!InterlockedExchange(&g_exhausted, 1)) Log("bridge guard heap: arena exhausted (or a commit failed) at %ld live allocations; going back to the real heap for the rest", static_cast<long>(g_allocs - g_frees));
    }
    InterlockedIncrement(&g_forwarded);
    return g_realAlloc(heap, flags, n);
}

BOOL WINAPI HookFree(HANDLE heap, DWORD flags, LPVOID p) {
    if (p && Ours(p)) return GuardFree(p) ? TRUE : FALSE;
    return g_realFree(heap, flags, p);
}

LPVOID WINAPI HookReAlloc(HANDLE heap, DWORD flags, LPVOID p, SIZE_T n) {
    if (p && Ours(p)) {
        Header* h = reinterpret_cast<Header*>(reinterpret_cast<uintptr_t>(p) - sizeof(Header));
        if (flags & 0x10) return n <= h->size ? p : nullptr;   // HEAP_REALLOC_IN_PLACE_ONLY
        void* fresh = HookAlloc(heap, flags, n);
        if (!fresh) return nullptr;
        memcpy(fresh, p, h->size < n ? h->size : n);
        GuardFree(p);
        return fresh;
    }
    return g_realReAlloc(heap, flags, p, n);
}

SIZE_T WINAPI HookSize(HANDLE heap, DWORD flags, LPCVOID p) {
    if (p && Ours(p)) return reinterpret_cast<const Header*>(reinterpret_cast<uintptr_t>(p) - sizeof(Header))->size;
    return g_realSize(heap, flags, p);
}

// Replaces one import of `module` (from any KERNEL32-family DLL) by `replacement`; returns the original.
void* PatchImport(HMODULE module, const char* name, void* replacement) {
    const uint8_t* base = reinterpret_cast<const uint8_t*>(module);
    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const IMAGE_NT_HEADERS* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    for (const IMAGE_IMPORT_DESCRIPTOR* d = reinterpret_cast<const IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
        const IMAGE_THUNK_DATA* names = reinterpret_cast<const IMAGE_THUNK_DATA*>(base + (d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk));
        IMAGE_THUNK_DATA* addrs = reinterpret_cast<IMAGE_THUNK_DATA*>(const_cast<uint8_t*>(base) + d->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++addrs) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            const IMAGE_IMPORT_BY_NAME* by = reinterpret_cast<const IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (strcmp(reinterpret_cast<const char*>(by->Name), name) != 0) continue;
            void* original = reinterpret_cast<void*>(addrs->u1.Function);
            DWORD old = 0;
            if (!VirtualProtect(&addrs->u1.Function, sizeof(void*), PAGE_READWRITE, &old)) return nullptr;
            addrs->u1.Function = reinterpret_cast<DWORD>(replacement);
            VirtualProtect(&addrs->u1.Function, sizeof(void*), old, &old);
            return original;
        }
    }
    return nullptr;
}
}  // namespace

void BridgeGuardHeapInstall() {
    static bool tried = false;
    static int enabled = -1;   // the ini is read once
    if (tried || enabled == 0) return;
    char path[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = n && n < MAX_PATH ? strrchr(path, '\\') : nullptr;
    if (!slash) return;
    strcpy(slash + 1, "gta2dx9.ini");
    if (enabled < 0) enabled = GetPrivateProfileIntA("devtools", "bridge_guard_heap", 0, path) ? 1 : 0;
    if (!enabled) return;
    HMODULE bridge = GetModuleHandleA("d3d9.dll");
    if (!bridge) return;   // not loaded yet: the caller tries again
    tried = true;
    const int arenaMb = GetPrivateProfileIntA("devtools", "bridge_guard_arena_mb", 600, path);
    InitializeCriticalSection(&g_lock);
    for (int mb = arenaMb; mb >= 64 && !g_arena; mb -= 64)
        g_arena = reinterpret_cast<uintptr_t>(VirtualAlloc(nullptr, static_cast<SIZE_T>(mb) << 20, MEM_RESERVE, PAGE_NOACCESS));
    if (!g_arena) { Log("bridge guard heap: could not reserve an arena"); return; }
    MEMORY_BASIC_INFORMATION mbi;
    VirtualQuery(reinterpret_cast<void*>(g_arena), &mbi, sizeof(mbi));
    g_arenaEnd = g_arena + mbi.RegionSize;
    g_bump = g_arena;
    g_realAlloc = reinterpret_cast<HeapAllocFn>(PatchImport(bridge, "HeapAlloc", reinterpret_cast<void*>(&HookAlloc)));
    g_realFree = reinterpret_cast<HeapFreeFn>(PatchImport(bridge, "HeapFree", reinterpret_cast<void*>(&HookFree)));
    g_realReAlloc = reinterpret_cast<HeapReAllocFn>(PatchImport(bridge, "HeapReAlloc", reinterpret_cast<void*>(&HookReAlloc)));
    g_realSize = reinterpret_cast<HeapSizeFn>(PatchImport(bridge, "HeapSize", reinterpret_cast<void*>(&HookSize)));
    if (!g_realAlloc || !g_realFree || !g_realReAlloc || !g_realSize) {
        Log("bridge guard heap: some imports of the bridge were not found (alloc %p free %p realloc %p size %p); not enabled", g_realAlloc, g_realFree, g_realReAlloc, g_realSize);
        return;
    }
    InterlockedExchange(&g_ready, 1);
    Log("bridge guard heap: ON for the bridge (d3d9.dll at %p): arena %lu MB at %08X; every block it allocates ends at a no-access page", bridge,
        static_cast<unsigned long>((g_arenaEnd - g_arena) >> 20), static_cast<unsigned>(g_arena));
}

void BridgeGuardHeapReport() {
    if (!g_ready) return;
    Log("bridge guard heap: %ld allocs, %ld frees, %ld live (%.1f MB), %ld forwarded to the real heap, arena %.0f of %.0f MB used", static_cast<long>(g_allocs),
        static_cast<long>(g_frees), static_cast<long>(g_allocs - g_frees), g_liveBytes / 1048576.0, static_cast<long>(g_forwarded),
        (g_bump - g_arena) / 1048576.0, (g_arenaEnd - g_arena) / 1048576.0);
}

}  // namespace gta2dx9
