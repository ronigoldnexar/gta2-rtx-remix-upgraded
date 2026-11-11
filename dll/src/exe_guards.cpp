// Guards over gta2.exe's own null-pointer crashes.
//
// The flame emitter (FIX-CRASH-2, qaf57). A flamethrower's flame is an emitter
// object updated each frame by FUN_00490130 (called from the particle update's
// switch, FUN_00490760). For an emitter owned by a pedestrian it reads the
// owner's object at [emitter+0x28]+8, the ped at [object+0x7C], and from 0x4902D6
// asks the ped where his object stands (FUN_00435C20: [[ped+0x168]+0x98/+0x9C]).
// While the ped boards a car (state 3 sub 6) with the fire key held, ped+0x168 is
// already null: FUN_00435C20 reads 0x98 and the game dies (C0000005 at
// gta2.exe+0x35C2A, ecx 0). The game crashes there in any view.
//
// The detour replaces the 13 bytes at 0x4902D6 (mov ecx,[ebp+0x7C]; lea edx,
// [esp+0x50]; push edx; call 0x435C20) with a jump to a thunk that does the same
// when the ped and his object are there, and otherwise takes the function's own
// "owner gone" exit at 0x49074E (al=1: the emitter ends), the exit its earlier
// checks already use for a missing owner object or ped. Nothing else changes.
#include "exe_guards.h"

#include <windows.h>

#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "log.h"

extern "C" {
uintptr_t s_flamePedPos = 0x00435C20;   // FUN_00435C20, the ped's object position
uintptr_t s_flameResume = 0x00490403;   // where the original call's jmp goes
uintptr_t s_flameEnd = 0x0049074E;      // FUN_00490130's al=1 exit
volatile long g_flameGuardHits = 0;
}

#ifdef _MSC_VER
static __declspec(naked) void FlameOwnerThunk() {
    __asm {
        mov ecx, dword ptr [ebp + 0x7C]
        test ecx, ecx
        jz gone
        cmp dword ptr [ecx + 0x168], 0
        jz gone
        lea edx, [esp + 0x50]
        push edx
        call dword ptr [s_flamePedPos]
        jmp dword ptr [s_flameResume]
    gone:
        lock inc dword ptr [g_flameGuardHits]
        jmp dword ptr [s_flameEnd]
    }
}
#else
extern "C" void FlameOwnerThunk();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    "_FlameOwnerThunk:\n"
    "    mov ecx, dword ptr [ebp + 0x7C]\n"
    "    test ecx, ecx\n"
    "    jz 1f\n"
    "    cmp dword ptr [ecx + 0x168], 0\n"
    "    jz 1f\n"
    "    lea edx, [esp + 0x50]\n"
    "    push edx\n"
    "    call dword ptr [_s_flamePedPos]\n"
    "    jmp dword ptr [_s_flameResume]\n"
    "1:\n"
    "    lock inc dword ptr [_g_flameGuardHits]\n"
    "    jmp dword ptr [_s_flameEnd]\n"
    ".att_syntax prefix\n"
    );
#endif

// The object grid's two free lists (FIX-PERF-9, 00y5 qaf91: C0000005 at gta2.exe+0x47352 reading 4).
// gta2.exe keeps every object linked into each map block it covers through two pools built per level at
// 0x4471B0: [0x5E6684] 4 096 nodes of 8 bytes {object, next} and [0x5E6688] 6 000 of 12 bytes {level, list,
// next}, each a singly linked free list headed at the pool's first dword. Their pops (0x447350, next at +4;
// 0x447370, next at +8) never test for an empty list: at six stars in Industrial a car blast or the army's
// fire takes the 8-byte pool from ~650 free to 0 (the classic view as shipped too, ~170 at one blast) and the
// pop reads [0+4]. Every other use is a pointer push (0x447360/0x447380) and the pool is freed as a whole at
// the level's end, so a node from elsewhere is as good as one of the array's. The detour pops exactly as the
// game does and, only when the list is empty, first links a fresh block of 1 024 nodes (ours, never freed:
// 8 KB / 12 KB) in front; until that moment nothing differs. At most 16 blocks a process; past that, or with
// [density] grid_pool_grow=0 (GTA2DX9_GRID_POOL_GROW=0), the game's own fault as before.
extern "C" {
volatile long g_gridPoolGrowOn = 1;
volatile long g_gridPoolGrown[2] = {0, 0};   // blocks added to the 8-byte / 12-byte pool
void __cdecl GridPoolGrow(uint8_t* pool, int which);
}

#ifdef _MSC_VER
static __declspec(naked) void GridPopCellThunk() {
    __asm {
        mov eax, dword ptr [ecx]
        test eax, eax
        jz grow
        mov edx, dword ptr [eax + 4]
        mov dword ptr [ecx], edx
        ret
    grow:
        push ecx
        push 0
        push ecx
        call GridPoolGrow
        add esp, 8
        pop ecx
        mov eax, dword ptr [ecx]
        mov edx, dword ptr [eax + 4]
        mov dword ptr [ecx], edx
        ret
    }
}
static __declspec(naked) void GridPopColumnThunk() {
    __asm {
        mov eax, dword ptr [ecx]
        test eax, eax
        jz grow
        mov edx, dword ptr [eax + 8]
        mov dword ptr [ecx], edx
        ret
    grow:
        push ecx
        push 1
        push ecx
        call GridPoolGrow
        add esp, 8
        pop ecx
        mov eax, dword ptr [ecx]
        mov edx, dword ptr [eax + 8]
        mov dword ptr [ecx], edx
        ret
    }
}
#else
extern "C" void GridPopCellThunk();
extern "C" void GridPopColumnThunk();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    "_GridPopCellThunk:\n"
    "    mov eax, dword ptr [ecx]\n"
    "    test eax, eax\n"
    "    jz 1f\n"
    "    mov edx, dword ptr [eax + 4]\n"
    "    mov dword ptr [ecx], edx\n"
    "    ret\n"
    "1:\n"
    "    push ecx\n"
    "    push 0\n"
    "    push ecx\n"
    "    call _GridPoolGrow\n"
    "    add esp, 8\n"
    "    pop ecx\n"
    "    mov eax, dword ptr [ecx]\n"
    "    mov edx, dword ptr [eax + 4]\n"   // still empty: the game's own fault (reading 4), as before
    "    mov dword ptr [ecx], edx\n"
    "    ret\n"
    "_GridPopColumnThunk:\n"
    "    mov eax, dword ptr [ecx]\n"
    "    test eax, eax\n"
    "    jz 2f\n"
    "    mov edx, dword ptr [eax + 8]\n"
    "    mov dword ptr [ecx], edx\n"
    "    ret\n"
    "2:\n"
    "    push ecx\n"
    "    push 1\n"
    "    push ecx\n"
    "    call _GridPoolGrow\n"
    "    add esp, 8\n"
    "    pop ecx\n"
    "    mov eax, dword ptr [ecx]\n"
    "    mov edx, dword ptr [eax + 8]\n"
    "    mov dword ptr [ecx], edx\n"
    "    ret\n"
    ".att_syntax prefix\n"
    );
#endif

namespace {
struct GridBlock { uint8_t* lo; uint8_t* hi; };
GridBlock g_gridBlocks[2][16];
}

extern "C" void __cdecl GridPoolGrow(uint8_t* pool, int which) {
    if (!pool || !g_gridPoolGrowOn || which < 0 || which > 1) return;
    const long have = g_gridPoolGrown[which];
    if (have >= 16) return;
    const size_t stride = which ? 12 : 8, next = which ? 8 : 4, nodes = 1024;
    uint8_t* block = static_cast<uint8_t*>(VirtualAlloc(nullptr, nodes * stride, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!block) return;
    for (size_t i = 0; i < nodes; ++i) {
        uint8_t* nd = block + i * stride;
        *reinterpret_cast<uint8_t**>(nd + next) = i + 1 < nodes ? block + (i + 1) * stride : *reinterpret_cast<uint8_t**>(pool);
    }
    *reinterpret_cast<uint8_t**>(pool) = block;
    g_gridBlocks[which][have] = {block, block + nodes * stride};
    g_gridPoolGrown[which] = have + 1;   // the game thread only: no other writer
}

namespace {

using gta2dx9::Log;

long g_flameLogged = 0;

// Writes a jmp to the thunk over `length` bytes at `at` (the rest NOPs) if the
// first `check` bytes there are `expected`.
bool Detour(uintptr_t at, const uint8_t* expected, int check, int length, const void* thunk, const char* what) {
    uint8_t* site = reinterpret_cast<uint8_t*>(at);
    if (memcmp(site, expected, check) != 0) {
        Log("patch: %s at %08X bytes differ, not applied", what, static_cast<unsigned>(at));
        return false;
    }
    uint8_t patch[32];
    memset(patch, 0x90, sizeof(patch));
    patch[0] = 0xE9;
    const int32_t to = static_cast<int32_t>(reinterpret_cast<uintptr_t>(thunk) - (at + 5));
    memcpy(patch + 1, &to, sizeof(to));
    DWORD previous = 0;
    if (!VirtualProtect(site, length, PAGE_EXECUTE_READWRITE, &previous)) {
        Log("patch: %s at %08X could not be unprotected, not applied", what, static_cast<unsigned>(at));
        return false;
    }
    memcpy(site, patch, length);
    VirtualProtect(site, length, previous, &previous);
    FlushInstructionCache(GetCurrentProcess(), site, length);
    Log("patch: %s at %08X applied", what, static_cast<unsigned>(at));
    return true;
}

}  // namespace

namespace gta2dx9 {

void ExeGuardsInstall() {
    // mov ecx,[ebp+0x7C]; lea edx,[esp+0x50]; push edx; call 0x435C20; jmp 0x490403.
    // All 18 checked (so a different build is left alone), the first 13 replaced.
    static const uint8_t kFlame[18] = {0x8B, 0x4D, 0x7C, 0x8D, 0x54, 0x24, 0x50, 0x52, 0xE8,
                                       0x3D, 0x59, 0xFA, 0xFF, 0xE9, 0x1B, 0x01, 0x00, 0x00};
    Detour(0x004902D6, kFlame, sizeof(kFlame), 13, reinterpret_cast<const void*>(&FlameOwnerThunk),
           "flame emitter owner guard (ped object null while boarding)");
    // FIX-PERF-9: the object grid's two pops (8 bytes each: mov eax,[ecx]; mov edx,[eax+4|8]; mov [ecx],edx; ret).
    {
        char v[8] = {};
        if (GetEnvironmentVariableA("GTA2DX9_GRID_POOL_GROW", v, sizeof v)) g_gridPoolGrowOn = atoi(v) != 0;
        if (!g_gridPoolGrowOn) {   // [density] grid_pool_grow=0: gta2.exe's pops left exactly as shipped
            Log("patch: object grid pool pops left as shipped (grid_pool_grow=0)");
            return;
        }
        static const uint8_t kCellPop[8] = {0x8B, 0x01, 0x8B, 0x50, 0x04, 0x89, 0x11, 0xC3};
        static const uint8_t kColumnPop[8] = {0x8B, 0x01, 0x8B, 0x50, 0x08, 0x89, 0x11, 0xC3};
        Detour(0x00447350, kCellPop, sizeof(kCellPop), 8, reinterpret_cast<const void*>(&GridPopCellThunk),
               "object grid cell pool pop (an empty list grows by 1024 nodes instead of faulting)");
        Detour(0x00447370, kColumnPop, sizeof(kColumnPop), 8, reinterpret_cast<const void*>(&GridPopColumnThunk),
               "object grid column pool pop (an empty list grows by 1024 nodes instead of faulting)");
    }
}

void ExeGuardsSetGridPoolGrow(bool on) { g_gridPoolGrowOn = on ? 1 : 0; }
int ExeGuardsGridPoolGrown(int which) { return which == 0 || which == 1 ? static_cast<int>(g_gridPoolGrown[which]) : 0; }
bool ExeGuardsGridNode(const void* p, int which) {
    if (which < 0 || which > 1) return false;
    const uint8_t* q = static_cast<const uint8_t*>(p);
    const long n = g_gridPoolGrown[which];
    const size_t stride = which ? 12 : 8;
    for (long i = 0; i < n; ++i)
        if (q >= g_gridBlocks[which][i].lo && q < g_gridBlocks[which][i].hi && (static_cast<size_t>(q - g_gridBlocks[which][i].lo) % stride) == 0) return true;
    return false;
}

void ExeGuardsUpdate() {
    static long gridLogged[2] = {0, 0};
    for (int w = 0; w < 2; ++w) {
        const long grown = g_gridPoolGrown[w];
        if (grown != gridLogged[w]) {
            Log("guard: the object grid's %s pool ran empty and grew by 1024 nodes instead of faulting at gta2.exe+0x%X (%ld blocks so far, FIX-PERF-9)",
                w ? "12-byte column" : "8-byte cell", w ? 0x47372u : 0x47352u, grown);
            gridLogged[w] = grown;
        }
    }
    const long hits = g_flameGuardHits;
    if (hits != g_flameLogged) {
        Log("guard: flame emitter whose ped has no object (boarding) ended instead of crashing (%ld so far)",
            hits);
        g_flameLogged = hits;
    }
}

}  // namespace gta2dx9
