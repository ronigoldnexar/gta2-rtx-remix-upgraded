#include "audio3d.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cmath>
#include <cstdint>
#include <cstring>

#include "log.h"
#include "view_modes.h"
#include "world_view.h"

namespace gta2dx9 {
namespace {

// The sound manager's "offset of a source from the listener" (gta2.exe 9.6):
//   void __thiscall Offset(SoundManager* this, const Fix32 src[3], Fix32 out[3])  ; ret 8
// out = src - listener, the listener at this+0x1468/0x146C/0x1470. Its two
// callers: the per-frame update of a playing sound (4177F0; then 2D pan from
// out.x at 41788A, or 3D position (x, 0, -y) at 417840) and the start of one
// (417A89; 417AA0 pan, the 3D position after it).
constexpr uintptr_t kOffset = 0x004168E0;
constexpr uintptr_t kCallSites[] = {0x004177F0, 0x00417A89};
constexpr uintptr_t kListener = 0x1468;
const uint8_t kOffsetHead[] = {0x53, 0x56, 0x8B, 0xF1, 0x57};   // push ebx / push esi / mov esi,ecx / push edi

// Fixed point: 1 block = 2^14 (the game's Fix32, as its view scale 0x4000).
constexpr float kFix = 16384.0f;
// The player is used as the listener only while he is this close to the game's own listener
// (the game camera leads a fast car by a few blocks); further means our reading is off.
constexpr float kPlayerTrust = 12.0f;

bool g_installed = false;
bool g_enabled = true;
bool g_playerListener = true;
int g_logEvery = 0;
unsigned g_calls = 0, g_rotated = 0, g_playerFar = 0;

using OffsetFn = void(__fastcall*)(void* self, void* edx, const int32_t* src, int32_t* out);

// Same register and stack use as the game's __thiscall with two arguments: this in ecx, the
// two pointers on the stack, popped by us.
void __fastcall OffsetHook(void* self, void* edx, const int32_t* src, int32_t* out) {
    reinterpret_cast<OffsetFn>(kOffset)(self, edx, src, out);
    if (++g_calls == 1) {
        // The flag the game's sound update tests at every call site (this+0x1D): Miles 3D voices or
        // the 2D mixer with its own pan.
        Log("audio3d: first positioned sound; the game's mixer is %s",
            static_cast<uint8_t*>(self)[0x1D] ? "Miles 3D (do_3d_sound=1)" : "2D with pan");
    }
    if (!g_enabled || !ViewCameraActive() || CurrentViewMode() == ViewMode::Classic) {
        // Left as the game placed it. Logged too (QA: the same probe reads both cases).
        if (g_logEvery > 0 && g_calls % static_cast<unsigned>(g_logEvery) == 0) {
            float yawDeg = 0.0f, pitchDeg = 0.0f;
            ViewCameraAngles(&yawDeg, &pitchDeg);
            const bool street = ViewCameraActive() && CurrentViewMode() != ViewMode::Classic;
            Log("audio3d: yaw %.0f game (%.2f,%.2f) -> cam right %.2f ahead %.2f from game; untouched (%s)",
                street ? yawDeg : 0.0f, out[0] / kFix, out[1] / kFix, out[0] / kFix, -out[1] / kFix,
                street ? "positional=0" : "classic view");
        }
        return;
    }

    const int32_t* listener = reinterpret_cast<const int32_t*>(static_cast<uint8_t*>(self) + kListener);
    float rx = static_cast<float>(out[0]);
    float ry = static_cast<float>(out[1]);
    float rz = static_cast<float>(out[2]);
    const PlayerState& player = ViewPlayer();
    bool fromPlayer = false;
    if (g_playerListener && player.valid) {
        const float dx = player.x * kFix - static_cast<float>(listener[0]);
        const float dy = player.y * kFix - static_cast<float>(listener[1]);
        if (std::fabs(dx) < kPlayerTrust * kFix && std::fabs(dy) < kPlayerTrust * kFix) {
            rx = static_cast<float>(src[0]) - player.x * kFix;
            ry = static_cast<float>(src[1]) - player.y * kFix;
            rz = static_cast<float>(src[2]) - player.z * kFix;
            fromPlayer = true;
        } else {
            ++g_playerFar;
        }
    }
    // The camera's yaw: 0 looks north (game -y), positive turns toward east (+x). In the game's
    // frame its right is (cos, sin) and ahead (sin, -cos); the game's convention wants right in
    // x and ahead in -y.
    float yawDeg = 0.0f, pitchDeg = 0.0f;
    ViewCameraAngles(&yawDeg, &pitchDeg);
    const float yaw = yawDeg * 0.017453293f;
    const float c = std::cos(yaw), s = std::sin(yaw);
    const float right = rx * c + ry * s;
    const float ahead = rx * s - ry * c;
    const int32_t ox = out[0], oy = out[1];
    out[0] = static_cast<int32_t>(std::lround(right));
    out[1] = static_cast<int32_t>(std::lround(-ahead));
    out[2] = static_cast<int32_t>(std::lround(rz));
    ++g_rotated;
    if (g_logEvery > 0 && g_rotated % static_cast<unsigned>(g_logEvery) == 0) {
        Log("audio3d: yaw %.0f game (%.2f,%.2f) -> cam right %.2f ahead %.2f from %s; n=%u far=%u", yawDeg,
            ox / kFix, oy / kFix, right / kFix, ahead / kFix, fromPlayer ? "player" : "game", g_rotated,
            g_playerFar);
    }
}

}  // namespace

bool Audio3DAvailable() { return g_installed; }

void Audio3DInstall(const char* iniPath) {
    g_enabled = GetPrivateProfileIntA("audio", "positional", 1, iniPath) != 0;
    char listener[16] = {};
    GetPrivateProfileStringA("audio", "listener", "player", listener, sizeof(listener), iniPath);
    g_playerListener = _stricmp(listener, "game") != 0;
    g_logEvery = GetPrivateProfileIntA("audio", "log_every", 0, iniPath);
    if (!g_enabled) {
        Log("audio3d: off ([audio] positional=0); sound is panned for the top-down camera");
        // With a log asked for, the hook still goes in to log the game's own offsets (QA baseline).
        if (g_logEvery <= 0) return;
    }
    if (memcmp(reinterpret_cast<const void*>(kOffset), kOffsetHead, sizeof(kOffsetHead)) != 0) {
        Log("audio3d: gta2.exe is not the build this knows; sound stays panned for the top-down camera");
        return;
    }
    for (uintptr_t site : kCallSites) {
        const uint8_t* p = reinterpret_cast<const uint8_t*>(site);
        int32_t rel = 0;
        memcpy(&rel, p + 1, sizeof(rel));
        if (p[0] != 0xE8 || site + 5 + static_cast<uintptr_t>(rel) != kOffset) {
            Log("audio3d: a call to the sound offset is not where this knows; no positional sound");
            return;
        }
    }
    for (uintptr_t site : kCallSites) {
        uint8_t* p = reinterpret_cast<uint8_t*>(site);
        DWORD previous = 0;
        if (!VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &previous)) {
            Log("audio3d: could not patch a call; no positional sound");
            return;   // the first site may already point at us: harmless, the hook is a superset
        }
        const int32_t to = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&OffsetHook) - (site + 5));
        memcpy(p + 1, &to, sizeof(to));
        VirtualProtect(p, 5, previous, &previous);
    }
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);
    g_installed = true;
    Log("audio3d: sounds placed relative to the street-view camera (listener: %s, log_every %d)",
        g_playerListener ? "player" : "game", g_logEvery);
}

}  // namespace gta2dx9
