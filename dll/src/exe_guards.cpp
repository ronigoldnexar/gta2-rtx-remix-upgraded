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
}

void ExeGuardsUpdate() {
    const long hits = g_flameGuardHits;
    if (hits != g_flameLogged) {
        Log("guard: flame emitter whose ped has no object (boarding) ended instead of crashing (%ld so far)",
            hits);
        g_flameLogged = hits;
    }
}

}  // namespace gta2dx9
