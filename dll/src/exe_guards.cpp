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
#include <cstdio>
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

// The player respawn (FIX-CRASH-WARP, gta2.exe+0x35FDF reading 0x80; docs/warp-crash.md).
// FUN_00435FA0 (__thiscall on the player's ped, called only from the "wasted" countdown at 0x4A7B4F once its
// 70 ticks are up) saves the ped's physics object edi = [ped+0x168], resets the ped (FUN_00435720), puts edi back
// and, from 0x435FDF, reads the sprite object [edi+0x80] and copies its position into the ped's x/y/z. It never
// tests edi: a ped whose physics object the game has let go of (the pool slot goes back with FUN_004355C0 the tick
// after FUN_0043E650, the game's kill-and-remove, cleared the ped's "alive" bit - see docs/warp-crash.md for who
// did that to the player's ped) crashes the game there with edi = 0.
// Two layers, both silent until the pointer is null:
//  1. at the function's entry, a ped with no physics object gets one from the game's own allocator, FUN_004360C0
//     (the call every spawn makes: x, y, z in 16.14 from the ped's own +0x1AC/+0x1B0/+0x1B4), so the respawn
//     goes on exactly as if it had been there all along;
//  2. at 0x435FDF, if the allocator found the pool empty, the position copy (0x435FDF-0x43600A) is skipped and the
//     function carries on from its next call, 0x436010.
extern "C" {
uintptr_t s_respawnResume = 0x00435FA5;     // after the 5 stolen bytes: push ebx / push ebp / push esi / mov esi, ecx
uintptr_t s_allocPhysics = 0x004360C0;      // FUN_004360C0 (ped = ecx; x, y, z pushed z first; ret 0xC)
uintptr_t s_respawnCopy = 0x00435FE5;       // after the stolen mov eax, [edi+0x80]
uintptr_t s_respawnSkipTo = 0x00436010;     // the call after the position copy
volatile long g_respawnNoPhysics = 0;       // respawns that found the ped without a physics object
volatile long g_respawnSkipped = 0;         // of those, the position copy skipped because the pool was empty
void __cdecl PedRespawnNoPhysics(uint8_t* ped);
}

#ifdef _MSC_VER
static __declspec(naked) void PedRespawnThunk() {
    __asm {
        cmp dword ptr [ecx + 0x168], 0
        jne have
        pushad
        push ecx
        call PedRespawnNoPhysics
        add esp, 4
        popad
        pushad
        push dword ptr [ecx + 0x1B4]
        push dword ptr [ecx + 0x1B0]
        push dword ptr [ecx + 0x1AC]
        call dword ptr [s_allocPhysics]
        popad
    have:
        push ebx
        push ebp
        push esi
        mov esi, ecx
        jmp dword ptr [s_respawnResume]
    }
}
static __declspec(naked) void PedRespawnCopyThunk() {
    __asm {
        test edi, edi
        jz none
        mov eax, dword ptr [edi + 0x80]
        jmp dword ptr [s_respawnCopy]
    none:
        lock inc dword ptr [g_respawnSkipped]
        push 0x64
        mov ecx, esi
        jmp dword ptr [s_respawnSkipTo]
    }
}
#else
extern "C" void PedRespawnThunk();
extern "C" void PedRespawnCopyThunk();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    "_PedRespawnThunk:\n"
    "    cmp dword ptr [ecx + 0x168], 0\n"
    "    jne 1f\n"
    "    pushad\n"
    "    push ecx\n"
    "    call _PedRespawnNoPhysics\n"
    "    add esp, 4\n"
    "    popad\n"
    "    pushad\n"
    "    push dword ptr [ecx + 0x1B4]\n"
    "    push dword ptr [ecx + 0x1B0]\n"
    "    push dword ptr [ecx + 0x1AC]\n"
    "    call dword ptr [_s_allocPhysics]\n"
    "    popad\n"
    "1:\n"
    "    push ebx\n"
    "    push ebp\n"
    "    push esi\n"
    "    mov esi, ecx\n"
    "    jmp dword ptr [_s_respawnResume]\n"
    "_PedRespawnCopyThunk:\n"
    "    test edi, edi\n"
    "    jz 2f\n"
    "    mov eax, dword ptr [edi + 0x80]\n"
    "    jmp dword ptr [_s_respawnCopy]\n"
    "2:\n"
    "    lock inc dword ptr [_g_respawnSkipped]\n"
    "    push 0x64\n"
    "    mov ecx, esi\n"
    "    jmp dword ptr [_s_respawnSkipTo]\n"
    ".att_syntax prefix\n"
    );
#endif

// Trace of the calls that end a ped's life (GTA2DX9_PED_TRACE=1): the game's kill-and-remove FUN_0043E650 and
// the physics release FUN_00435F70, each logged with the callers when the ped is the player's.
extern "C" {
uintptr_t s_killResume = 0x0043E659;        // after 9 stolen bytes: push esi / mov esi, ecx / mov eax, [esi+0x240]
uintptr_t s_freeResume = 0x00435F79;        // after 9 stolen bytes: push esi / mov esi, ecx / mov eax, [esi+0x168]
void __cdecl PedTraceKill(uint8_t* ped, const uintptr_t* stack);
void __cdecl PedTraceFree(uint8_t* ped, const uintptr_t* stack);
}
#ifdef _MSC_VER
static __declspec(naked) void PedKillThunk() {
    __asm {
        pushad
        lea eax, [esp + 32]
        push eax
        push ecx
        call PedTraceKill
        add esp, 8
        popad
        push esi
        mov esi, ecx
        mov eax, dword ptr [esi + 0x240]
        jmp dword ptr [s_killResume]
    }
}
static __declspec(naked) void PedFreeThunk() {
    __asm {
        pushad
        lea eax, [esp + 32]
        push eax
        push ecx
        call PedTraceFree
        add esp, 8
        popad
        push esi
        mov esi, ecx
        mov eax, dword ptr [esi + 0x168]
        jmp dword ptr [s_freeResume]
    }
}
#else
extern "C" void PedKillThunk();
extern "C" void PedFreeThunk();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    "_PedKillThunk:\n"
    "    pushad\n"
    "    lea eax, [esp + 32]\n"
    "    push eax\n"
    "    push ecx\n"
    "    call _PedTraceKill\n"
    "    add esp, 8\n"
    "    popad\n"
    "    push esi\n"
    "    mov esi, ecx\n"
    "    mov eax, dword ptr [esi + 0x240]\n"
    "    jmp dword ptr [_s_killResume]\n"
    "_PedFreeThunk:\n"
    "    pushad\n"
    "    lea eax, [esp + 32]\n"
    "    push eax\n"
    "    push ecx\n"
    "    call _PedTraceFree\n"
    "    add esp, 8\n"
    "    popad\n"
    "    push esi\n"
    "    mov esi, ecx\n"
    "    mov eax, dword ptr [esi + 0x168]\n"
    "    jmp dword ptr [_s_freeResume]\n"
    ".att_syntax prefix\n"
    );
#endif

namespace {
// The game's player object ([0x5EB4FC] -> +0x38) and the ped it drives (+0x2C4); 0 when not up.
uintptr_t GamePlayerObjectNow() {
    const uintptr_t root = *reinterpret_cast<const uintptr_t*>(0x005EB4FC);
    if (root < 0x10000 || root >= 0x7FFE0000) return 0;
    const uintptr_t player = *reinterpret_cast<const uintptr_t*>(root + 0x38);
    return player < 0x10000 || player >= 0x7FFE0000 ? 0 : player;
}
uintptr_t GamePlayerPedNow() {
    const uintptr_t player = GamePlayerObjectNow();
    return player ? *reinterpret_cast<const uintptr_t*>(player + 0x2C4) : 0;
}
// "gta2.exe+0xNNNN < ..." for the return addresses in gta2.exe's code found in the first words of the stack.
void Callers(const uintptr_t* stack, char* out, size_t cap) {
    size_t n = 0;
    out[0] = 0;
    int found = 0;
    for (int i = 0; i < 40 && found < 6; ++i) {
        const uintptr_t w = stack[i];
        if (w < 0x00401000 || w >= 0x0056E000) continue;
        n += static_cast<size_t>(snprintf(out + n, cap - n, "%sgta2.exe+0x%X", found ? " < " : "", static_cast<unsigned>(w - 0x00400000)));
        if (n >= cap - 24) break;
        ++found;
    }
}
void PedLine(const char* what, const uint8_t* ped, const uintptr_t* stack) {
    const uintptr_t player = GamePlayerObjectNow();
    const bool mine = player && reinterpret_cast<uintptr_t>(ped) == GamePlayerPedNow();
    static long other = 0;
    if (!mine) { ++other; return; }
    char callers[256];
    Callers(stack, callers, sizeof callers);
    gta2dx9::Log("pedtrace: %s the PLAYER's ped %p: state %d sub %d pending %d, phys %08X veh %08X, +0x234 %u +0x21C %08X +0x20E %u +0x240 %d +0x238 %d; "
        "player object +0x28 %u +0x2C %u (%ld other peds so far) callers %s",
        what, ped, *reinterpret_cast<const int32_t*>(ped + 0x278), *reinterpret_cast<const int32_t*>(ped + 0x27C),
        *reinterpret_cast<const int32_t*>(ped + 0x280), *reinterpret_cast<const unsigned*>(ped + 0x168),
        *reinterpret_cast<const unsigned*>(ped + 0x16C), *(ped + 0x234), *reinterpret_cast<const unsigned*>(ped + 0x21C),
        *reinterpret_cast<const uint16_t*>(ped + 0x20E), *reinterpret_cast<const int32_t*>(ped + 0x240), *reinterpret_cast<const int32_t*>(ped + 0x238),
        *reinterpret_cast<const uint8_t*>(player + 0x28), *reinterpret_cast<const uint16_t*>(player + 0x2C), other, callers);
}
}  // namespace

extern "C" void __cdecl PedTraceKill(uint8_t* ped, const uintptr_t* stack) { PedLine("kill-and-remove (FUN_0043E650) on", ped, stack); }
extern "C" void __cdecl PedTraceFree(uint8_t* ped, const uintptr_t* stack) { PedLine("physics release (FUN_00435F70) on", ped, stack); }
extern "C" void __cdecl PedRespawnNoPhysics(uint8_t* ped) {
    InterlockedIncrement(&g_respawnNoPhysics);
    const uintptr_t player = GamePlayerObjectNow();
    gta2dx9::Log("guard: the respawn of ped %p (%s) found no physics object: state %d sub %d, +0x234 %u +0x21C %08X, player object +0x28 %u +0x2C %u; "
        "asking the game's allocator for one at %.2f,%.2f,%.2f",
        ped, reinterpret_cast<uintptr_t>(ped) == GamePlayerPedNow() ? "the player's" : "not the game's player ped",
        *reinterpret_cast<const int32_t*>(ped + 0x278), *reinterpret_cast<const int32_t*>(ped + 0x27C), *(ped + 0x234),
        *reinterpret_cast<const unsigned*>(ped + 0x21C), player ? *reinterpret_cast<const uint8_t*>(player + 0x28) : 0u,
        player ? *reinterpret_cast<const uint16_t*>(player + 0x2C) : 0u,
        *reinterpret_cast<const int32_t*>(ped + 0x1AC) / 16384.0, *reinterpret_cast<const int32_t*>(ped + 0x1B0) / 16384.0,
        *reinterpret_cast<const int32_t*>(ped + 0x1B4) / 16384.0);
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
    // FIX-CRASH-WARP: the player's respawn (FUN_00435FA0) with no physics object on the ped (gta2.exe+0x35FDF).
    {
        char v[8] = {};
        const bool on = !(GetEnvironmentVariableA("GTA2DX9_RESPAWN_GUARD", v, sizeof v) && v[0] == '0');
        static const uint8_t kEntry[5] = {0x53, 0x55, 0x56, 0x8B, 0xF1};                 // push ebx / push ebp / push esi / mov esi, ecx
        static const uint8_t kCopy[6] = {0x8B, 0x87, 0x80, 0x00, 0x00, 0x00};            // mov eax, [edi+0x80]
        if (on) {
            Detour(0x00435FA0, kEntry, sizeof(kEntry), 5, reinterpret_cast<const void*>(&PedRespawnThunk),
                   "player respawn: no physics object on the ped gets one from the game's allocator");
            Detour(0x00435FDF, kCopy, sizeof(kCopy), 6, reinterpret_cast<const void*>(&PedRespawnCopyThunk),
                   "player respawn: position copy skipped when the ped still has no physics object");
        } else {
            Log("patch: player respawn guard off (GTA2DX9_RESPAWN_GUARD=0)");
        }
        if (GetEnvironmentVariableA("GTA2DX9_PED_TRACE", v, sizeof v) && v[0] == '1') {
            static const uint8_t kKill[9] = {0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x40, 0x02, 0x00, 0x00};
            static const uint8_t kFree[9] = {0x56, 0x8B, 0xF1, 0x8B, 0x86, 0x68, 0x01, 0x00, 0x00};
            Detour(0x0043E650, kKill, sizeof(kKill), 9, reinterpret_cast<const void*>(&PedKillThunk), "ped trace: kill-and-remove");
            Detour(0x00435F70, kFree, sizeof(kFree), 9, reinterpret_cast<const void*>(&PedFreeThunk), "ped trace: physics release");
        }
    }
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

static volatile DWORD g_testWarpTick = 0;
void ExeGuardsNoteWarp() { g_testWarpTick = GetTickCount() | 1; }

void ExeGuardsUpdate() {
    static long testMs = -2;
    if (testMs == -2) {
        char v[16] = {};
        testMs = GetEnvironmentVariableA("GTA2DX9_TEST_DEATH_AFTER_WARP_MS", v, sizeof v) && v[0] ? atol(v) : -1;
        if (testMs >= 0) Log("test: the player's ped is killed through the game's death handler %ld ms after each developer warp (GTA2DX9_TEST_DEATH_AFTER_WARP_MS)", testMs);
    }
    // FIX-CRASH-WARP, the source: while the player's "wasted" countdown runs (player object +0x28 set, +0x2C ticks left)
    // his dead ped's state timer [ped+0x20E] must not pass 200, or FUN_004454E0 takes him for an old corpse and
    // FUN_0043E650 removes him (his physics object goes 3 ticks later; the respawn needs it). The timer is not reset at
    // death, so a player who stood about for 130+ ticks before dying (right after a warp: state 2 for seconds) crosses 200
    // inside the 70-tick countdown. Kept at 120 while the countdown runs; GTA2DX9_CORPSE_CLAMP=0 leaves it alone.
    {
        static int clampOn = -1;
        if (clampOn < 0) { char v[8] = {}; clampOn = !(GetEnvironmentVariableA("GTA2DX9_CORPSE_CLAMP", v, sizeof v) && v[0] == '0'); }
        const uintptr_t player = clampOn ? GamePlayerObjectNow() : 0;
        const uintptr_t ped = player ? *reinterpret_cast<const uintptr_t*>(player + 0x2C4) : 0;
        if (ped >= 0x10000 && ped < 0x7FFE0000 && *reinterpret_cast<const uint8_t*>(player + 0x28) &&
            *reinterpret_cast<const uint16_t*>(player + 0x2C) && *reinterpret_cast<const int32_t*>(ped + 0x278) == 9) {
            uint16_t* timer = reinterpret_cast<uint16_t*>(ped + 0x20E);
            if (*timer > 120 && *timer < 0x270F) { static long n = 0; if (n++ < 20) Log("guard: wasted player's ped timer +0x20E %u held at 120 (corpse timeout is 200)", *timer); *timer = 120; }
        }
    }
    if (testMs >= 0) {   // the soak used up its lives: keep them up so the loop can go on
        const uintptr_t player = GamePlayerObjectNow();
        if (player) { int32_t* lives = reinterpret_cast<int32_t*>(player + 0x684); if (*lives >= 0 && *lives < 3) *lives = 5; }
    }
    if (testMs >= 0 && g_testWarpTick && static_cast<long>(GetTickCount() - g_testWarpTick) >= testMs) {
        g_testWarpTick = 0;
        const uintptr_t ped = GamePlayerPedNow();
        if (ped >= 0x10000 && ped < 0x7FFE0000 && *reinterpret_cast<const int32_t*>(ped + 0x278) != 9 && *reinterpret_cast<const unsigned*>(ped + 0x168)) {
            *reinterpret_cast<int32_t*>(ped + 0x290) = 1;   // damage cause 1: hit by a car
#ifdef _MSC_VER
            typedef void(__thiscall * DeathFn)(void*);
#else
            typedef void(__attribute__((thiscall)) * DeathFn)(void*);
#endif
            Log("test: killing the player's ped %08X through the death handler (state %d sub %d, phys %08X, +0x20E %u +0x238 %d +0x240 %d)", static_cast<unsigned>(ped),
                *reinterpret_cast<const int32_t*>(ped + 0x278), *reinterpret_cast<const int32_t*>(ped + 0x27C), *reinterpret_cast<const unsigned*>(ped + 0x168),
                *reinterpret_cast<const uint16_t*>(ped + 0x20E), *reinterpret_cast<const int32_t*>(ped + 0x238), *reinterpret_cast<const int32_t*>(ped + 0x240));
            reinterpret_cast<DeathFn>(0x004411B0)(reinterpret_cast<void*>(ped));
        }
    }
    static long gridLogged[2] = {0, 0};
    for (int w = 0; w < 2; ++w) {
        const long grown = g_gridPoolGrown[w];
        if (grown != gridLogged[w]) {
            Log("guard: the object grid's %s pool ran empty and grew by 1024 nodes instead of faulting at gta2.exe+0x%X (%ld blocks so far, FIX-PERF-9)",
                w ? "12-byte column" : "8-byte cell", w ? 0x47372u : 0x47352u, grown);
            gridLogged[w] = grown;
        }
    }
    static long respawnLogged = 0;
    if (g_respawnSkipped != respawnLogged) {
        Log("guard: a respawn found the ped without a physics object and the allocator had none: the position copy at gta2.exe+0x35FDF was skipped (%ld so far)",
            static_cast<long>(g_respawnSkipped));
        respawnLogged = g_respawnSkipped;
    }
    const long hits = g_flameGuardHits;
    if (hits != g_flameLogged) {
        Log("guard: flame emitter whose ped has no object (boarding) ended instead of crashing (%ld so far)",
            hits);
        g_flameLogged = hits;
    }
}

}  // namespace gta2dx9
