#include "heap_check.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>
#include <cstring>

#include "crash_safe.h"
#include "log.h"
#include "thread_watch.h"

namespace gta2dx9 {
namespace {
DWORD g_everyMs = 0;
int g_abort = 0;

DWORD WINAPI HeapCheckThread(LPVOID) {
    NameThisThread("heap check");
    typedef intptr_t(__cdecl * GetHeapHandle)();
    HMODULE crt = GetModuleHandleA("msvcrt.dll");
    GetHeapHandle get = crt ? reinterpret_cast<GetHeapHandle>(GetProcAddress(crt, "_get_heap_handle")) : nullptr;
    const HANDLE crtHeap = get ? reinterpret_cast<HANDLE>(get()) : nullptr;
    const HANDLE procHeap = GetProcessHeap();
    bool bad[64] = {};
    DWORD passes = 0, worst = 0, lastReport = GetTickCount();
    for (;;) {
        Sleep(g_everyMs);
        HANDLE heaps[64];
        const DWORD n = GetProcessHeaps(64, heaps);
        for (DWORD i = 0; i < n && i < 64; ++i) {
            if (bad[i]) continue;
            const DWORD t0 = GetTickCount();
            const BOOL ok = HeapValidate(heaps[i], 0, nullptr);
            const DWORD dt = GetTickCount() - t0;
            if (dt > worst) worst = dt;
            if (ok) continue;
            bad[i] = true;
            Log("heap check: HEAP %p (%s) FAILED HeapValidate after %lu passes (this validation took %lu ms); the heap is corrupt",
                heaps[i], heaps[i] == procHeap ? "process heap" : heaps[i] == crtHeap ? "msvcrt heap" : "other heap",
                static_cast<unsigned long>(passes), static_cast<unsigned long>(dt));
            LogFlush();
            if (g_abort) crash::FatalException("heap check: a heap failed validation", nullptr);
        }
        ++passes;
        if (GetTickCount() - lastReport > 60000) {
            lastReport = GetTickCount();
            Log("heap check: %lu passes over %lu heaps, none failed so far (worst validation %lu ms)", static_cast<unsigned long>(passes),
                static_cast<unsigned long>(n), static_cast<unsigned long>(worst));
        }
    }
    return 0;
}
}  // namespace

void StartHeapCheck() {
    static bool started = false;
    if (started) return;
    char path[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = n && n < MAX_PATH ? strrchr(path, '\\') : nullptr;
    if (!slash) return;
    strcpy(slash + 1, "gta2dx9.ini");
    g_everyMs = GetPrivateProfileIntA("devtools", "heap_check_ms", 0, path);
    g_abort = GetPrivateProfileIntA("devtools", "heap_check_abort", 0, path);
    if (!g_everyMs) return;
    started = true;
    Log("heap check: validating every heap every %lu ms%s", static_cast<unsigned long>(g_everyMs), g_abort ? ", ending the game at the first failure" : "");
    if (HANDLE t = CreateThread(nullptr, 0, HeapCheckThread, nullptr, 0, nullptr)) CloseHandle(t);
}

}  // namespace gta2dx9
