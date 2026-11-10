// City life in the street views (AI-TRAFFIC-PEDS). See city_ai.h and docs/city-ai.md.
//
// What gta2.exe 9.6 does, read off the binary (names from the CriminalRETeam/gta2_re
// reimplementation of 10.5, whose Ped layout is the same; every site below is checked
// byte for byte before it is written, and keeps its original bytes for the classic view):
//
//   Threat reaction, "run away" (the plain civilians, Ped+0x28C == 3; 9.6 0x43F3DF..): on a
//   frame when somebody fired a weapon or drove recklessly (the threatening-ped list
//   0x5E5EE0, flag 0x5E5BE2), the closest such ped is looked up, and if he carries a weapon
//   or sits in a car and is within 4 blocks (Chebyshev; the compare is `push 0x5E5C9C` /
//   `call 0x4037E0` at 0x43F4D3/0x43F4E0) the civilian takes the internal objective
//   "flee char on foot till safe" (2), faces away and panics. 4 blocks is about half the
//   top-down screen; from the street a gunshot ten blocks away left everybody strolling.
//
//   Flee till safe (internal objective 2, 9.6 0x4347D0): the ped runs while the threat is
//   within 6 blocks (`push 0x5E5C2C` at 0x434804) and stops as soon as it is further and
//   he stands on pavement - so anyone told to flee from further than 6 blocks stopped on
//   the spot. Raising the reaction radius alone does nothing without raising this too.
//
//   Pedestrians and cars: traffic brakes and honks for a ped in its probe (CarAI
//   0x451FF0 in 10.5), but a ped never steps out of a car's way; a fast car - the
//   player's above all - runs through a crowd that keeps walking. And nobody keeps clear
//   of a burning car.
//
// What this changes, in the street views only:
//   1. the reaction radius: gun_radius blocks for an armed threat, car_radius for one at
//      the wheel (the call at 0x43F4E0 goes to ThreatLess below, which picks by edi, the
//      threatening ped, as the game's own code holds him there);
//   2. the safe distance: safe_distance blocks (the operand at 0x434805);
//   3. dodge: a civilian standing or walking in the path of a car moving faster than
//      dodge_speed blocks a second, within dodge_time seconds of it, is given the game's
//      own "flee on foot till safe" (internal objective 1, gta2.exe's SetObjective2,
//      0x436920) from the nearest point of the car's path, facing straight away from it
//      and running; and anyone within fire_radius of a burning car flees it the same way.
//
// The census: every census_every frames an `ai:` line counts, within census_radius of the
// player, the peds on foot by what they are doing and the cars by what they are doing; an
// `ai: event` line is written at each flee onset, dodge, near miss and threat frame. The
// analysis is tools/ai_census.py.
#include "city_ai.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <unordered_map>

#include "compat.h"
#include "game_access.h"
#include "log.h"
#include "view_modes.h"
#include "../../src/gta2_map.h"

// Read by ThreatLess (assembly), so plain C names.
extern "C" {
ASM_USED int32_t g_cityAiGunRadius = 4 << 14;   // 16.14 fixed, blocks
ASM_USED int32_t g_cityAiCarRadius = 4 << 14;
ASM_USED int32_t g_cityAiSafeDistance = 6 << 14;
}

// The compare gta2.exe makes at 0x43F4E0, `distance < 4`, with the threat's own radius:
// ecx points at the Chebyshev distance (16.14), [esp+4] at the game's constant (ignored),
// edi is the threatening ped. Same contract as 0x4037E0: 1 or 0 in eax, ret 4.
#ifdef _MSC_VER
extern "C" __declspec(naked) void CityAiThreatLess() {
    __asm {
        mov eax, dword ptr [ecx]
        mov edx, dword ptr [edi + 0x16C]
        test edx, edx
        jz gun
        mov edx, dword ptr [g_cityAiCarRadius]
        jmp compare
    gun:
        mov edx, dword ptr [g_cityAiGunRadius]
    compare:
        xor ecx, ecx
        cmp eax, edx
        setl cl
        mov eax, ecx
        ret 4
    }
}
#else
extern "C" void CityAiThreatLess();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    ".globl _CityAiThreatLess\n"
    "_CityAiThreatLess:\n"
    "    mov eax, dword ptr [ecx]\n"
    "    mov edx, dword ptr [edi + 0x16C]\n"
    "    test edx, edx\n"
    "    jz 1f\n"
    "    mov edx, dword ptr [_g_cityAiCarRadius]\n"
    "    jmp 2f\n"
    "1:\n"
    "    mov edx, dword ptr [_g_cityAiGunRadius]\n"
    "2:\n"
    "    xor ecx, ecx\n"
    "    cmp eax, edx\n"
    "    setl cl\n"
    "    mov eax, ecx\n"
    "    ret 4\n"
    ".att_syntax prefix\n"
    );
#endif

namespace gta2dx9 {
namespace {

// ---- gta2.exe 9.6 ----------------------------------------------------------------------
constexpr uintptr_t kThreatRadiusPush = 0x0043F4D3;   // push 0x5E5C9C (4.0)
constexpr uintptr_t kThreatCompareCall = 0x0043F4E0;  // call 0x4037E0 (Fix16 <)
constexpr uintptr_t kFixLess = 0x004037E0;
constexpr uintptr_t kFixFour = 0x005E5C9C;
constexpr uintptr_t kSafeDistancePush = 0x00434804;   // push 0x5E5C2C (6.0)
constexpr uintptr_t kFixSix = 0x005E5C2C;
constexpr uintptr_t kSetObjective2 = 0x00436920;      // Ped::SetObjective2(objective, timer), thiscall
constexpr uintptr_t kThreatFlag = 0x005E5BE2;         // somebody threatening this frame
constexpr uintptr_t kPedPoolPtr = 0x005E5BBC;         // PedPool*: +4 live head, chained by +0x160

// Ped (Ped.hpp)
constexpr uintptr_t kPedNext = 0x160;
constexpr uintptr_t kPedGroup = 0x164;
constexpr uintptr_t kPedGameObject = 0x168;   // the Char: +0x38 speed, +0x40 rotation
constexpr uintptr_t kPedCar = 0x16C;
constexpr uintptr_t kPedWeapon = 0x170;
constexpr uintptr_t kPedInternalTarget = 0x14C;
constexpr uintptr_t kPedFacingTarget = 0x130;
constexpr uintptr_t kPedThreatX = 0x1D0;      // internal target point, 16.14
constexpr uintptr_t kPedId = 0x200;
constexpr uintptr_t kPedFlags = 0x21C;        // bit 2 panicking
constexpr uintptr_t kPedObjective = 0x258;
constexpr uintptr_t kPedInternalObjective = 0x25C;
constexpr uintptr_t kPedOccupation = 0x240;
constexpr uintptr_t kPedType = 0x238;         // 2 player
constexpr uintptr_t kPedThreatReaction = 0x28C;   // 3 run away
constexpr uintptr_t kCharRotation = 0x40;
constexpr int kStateWalking = 0, kStateRunning = 1, kStatePath = 2, kStateStanding = 7, kStateDown = 8,
              kStateDead = 9;
constexpr int kObjFleePoint = 1, kObjFleePed = 2;
constexpr uint16_t kQuarterTurn = 0x168;      // Ang16: 0x5A0 a turn

using SetObjective2Fn = void(__fastcall*)(void* ped, void* edx, int objective, int timer);

// ---- settings --------------------------------------------------------------------------
bool g_enabled = true;      // the behaviour; the census runs either way
float g_gunRadius = 12.0f, g_carRadius = 5.0f, g_safeDistance = 14.0f;
bool g_dodge = true;
float g_dodgeSpeed = 2.0f, g_dodgeTime = 1.4f, g_dodgeHalfWidth = 0.75f;
float g_fireRadius = 4.0f;
int g_censusEvery = 15;
// GTA2DX9_TRAFFIC_LOG=1: one `ai: stop` line per free-stopped car (at most every 2 s a car), for reading the causes.
bool g_stopLog = false;
float g_censusRadius = 20.0f;
int g_maxPerFrame = 6;

// ---- patch state -----------------------------------------------------------------------
bool g_sitesOk = false, g_sitesChecked = false, g_patched = false;

bool Writable(uintptr_t at, const void* bytes, size_t n) {
    DWORD previous = 0;
    void* p = reinterpret_cast<void*>(at);
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &previous)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, previous, &previous);
    return true;
}

int32_t Rel32(uintptr_t site, uintptr_t to) { return static_cast<int32_t>(to - (site + 5)); }

bool CheckSites() {
    const uint8_t* a = reinterpret_cast<const uint8_t*>(kThreatRadiusPush);
    const uint8_t* b = reinterpret_cast<const uint8_t*>(kThreatCompareCall);
    const uint8_t* c = reinterpret_cast<const uint8_t*>(kSafeDistancePush);
    uint32_t imm = 0;
    int32_t rel = 0;
    bool ok = a[0] == 0x68 && (memcpy(&imm, a + 1, 4), imm == kFixFour);
    ok = ok && b[0] == 0xE8 && (memcpy(&rel, b + 1, 4), rel == Rel32(kThreatCompareCall, kFixLess));
    ok = ok && c[0] == 0x68 && (memcpy(&imm, c + 1, 4), imm == kFixSix);
    // the call may already be ours (a second install): treat that as fine
    if (!ok && b[0] == 0xE8) {
        memcpy(&rel, b + 1, 4);
        if (rel == Rel32(kThreatCompareCall, reinterpret_cast<uintptr_t>(&CityAiThreatLess))) ok = true;
    }
    return ok;
}

void Patch(bool on) {
    if (on == g_patched) return;
    const int32_t rel = on ? Rel32(kThreatCompareCall, reinterpret_cast<uintptr_t>(&CityAiThreatLess))
                           : Rel32(kThreatCompareCall, kFixLess);
    const uint32_t imm = on ? static_cast<uint32_t>(reinterpret_cast<uintptr_t>(&g_cityAiSafeDistance))
                            : static_cast<uint32_t>(kFixSix);
    bool ok = Writable(kThreatCompareCall + 1, &rel, 4);
    ok = Writable(kSafeDistancePush + 1, &imm, 4) && ok;
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);
    g_patched = on;
    Log("ai: %s (gun %.1f, car %.1f, safe %.1f blocks)%s", on ? "street-view reactions on" : "reactions as shipped",
        g_gunRadius, g_carRadius, g_safeDistance, ok ? "" : " - a write failed");
}

// ---- per-car memory: velocity from the last frame ---------------------------------------
struct CarSeen {
    float x = 0, y = 0, z = 0, vx = 0, vy = 0;
    int frame = -1000;
    bool moving = false;
    // FIX-TRAFFIC-1 stop counter (census only): a driven car's go/stop state with hysteresis
    // (stopped under 0.4 blocks/s, going again over 0.8), the frame it last changed, and the
    // top speed of the last half second or so (decays 7% a frame) for "a hard stop".
    bool halted = false;
    int stopLoggedAt = -1000;
    int firstSeen = 0;      // the frame it came into the 30-block window (a new car starts at rest)
    int haltedAt = -1000;
    float recentTop = 0.0f;
};
std::unordered_map<uintptr_t, CarSeen> g_cars;
struct PedSeen {
    int fleeing = 0;     // last sample's flee/panic word
    int dodgedAt = -100000;
    int nearMissAt = -100000;
    // the last dodge, checked one game second later: how far off the car's path he got
    float qx = 0, qy = 0, ux = 0, uy = 0, lat0 = 0;
    bool pending = false;
};
std::unordered_map<uint32_t, PedSeen> g_peds;
int g_frame = 0;

// Census counters accumulated between census lines.
struct Tally {
    int samples = 0;
    long peds = 0, walk = 0, run = 0, stand = 0, down = 0, dead = 0, panic = 0, flee = 0;
    long cars = 0, moving = 0, stopped = 0, queued = 0, freeStop = 0, axis = 0, movingAxisN = 0, burning = 0;
    long driven = 0;
    // FIX-TRAFFIC-1: free stops by cause (car samples), and stop events (per car, every frame).
    long fsPed = 0, fsGap = 0, fsCross = 0, fsJunction = 0, fsMid = 0;
    int stops = 0, hardStops = 0, shortGo = 0;
    long fresh = 0;
    int threatFrames = 0, fleeOnsets = 0, dodges = 0, fireFlees = 0, nearMisses = 0, dodgeClear = 0, dodgeDown = 0;
    float speedSum = 0;
} g_tally;

inline int32_t I32(const uint8_t* p, uintptr_t o) { return *reinterpret_cast<const int32_t*>(p + o); }
inline const uint8_t* P(const uint8_t* p, uintptr_t o) { return *reinterpret_cast<const uint8_t* const*>(p + o); }

// A plain passer-by the game would itself send running from a threat: not the player, on
// foot, alive and upright, no objective of his own, no group, not panicking already.
bool Civilian(const uint8_t* ped) {
    if (I32(ped, kPedType) == 2) return false;
    if (game::PlausiblePointer(P(ped, kPedCar)) || !game::PlausiblePointer(P(ped, kPedGameObject))) return false;
    if (game::PlausiblePointer(P(ped, kPedGroup))) return false;
    if (I32(ped, kPedThreatReaction) != 3) return false;
    if (I32(ped, kPedObjective) != 0 || I32(ped, kPedInternalObjective) != 0) return false;
    if (I32(ped, kPedFlags) & 4) return false;
    const int st = I32(ped, game::kPedState);
    return st == kStateWalking || st == kStateStanding || st == kStatePath;
}

// The game's own "flee on foot till safe" from a point, facing straight away from `away`.
void FleeFromPoint(uint8_t* ped, float px, float py, float pz, float awayX, float awayY) {
    reinterpret_cast<SetObjective2Fn>(kSetObjective2)(ped, nullptr, kObjFleePoint, 9999);
    *reinterpret_cast<uint32_t*>(ped + kPedInternalTarget) = 0;
    int32_t* t = reinterpret_cast<int32_t*>(ped + kPedThreatX);
    t[0] = static_cast<int32_t>(px * 16384.0f);
    t[1] = static_cast<int32_t>(py * 16384.0f);
    t[2] = static_cast<int32_t>(pz * 16384.0f);
    if (t[0] == 0) t[0] = 1;   // (0,0) means "no point" to the game
    if (t[1] == 0) t[1] = 1;
    // Ang16 with x = sin, y = cos (FUN_0041FC20), 0x5A0 to the turn
    float a = std::atan2(awayX, awayY);
    if (a < 0) a += 6.2831853f;
    const uint16_t ang = static_cast<uint16_t>(static_cast<int>(a / 6.2831853f * 1440.0f + 0.5f) % 1440);
    *reinterpret_cast<uint16_t*>(ped + kPedFacingTarget) = ang;
    uint8_t* obj = const_cast<uint8_t*>(P(ped, kPedGameObject));
    *reinterpret_cast<uint16_t*>(obj + kCharRotation) = ang;
    // run (ChangeNextPedState1/2 are plain stores outside state 8, which Civilian excludes)
    *reinterpret_cast<int32_t*>(ped + game::kPedState) = kStateRunning;
    *reinterpret_cast<int32_t*>(ped + game::kPedSubState) = 3;
}

void Event(const char* what, const uint8_t* ped, float d, float extra) {
    Log("ai: event %s frame=%d id=%u d=%.1f x=%.1f", what, g_frame, *reinterpret_cast<const uint32_t*>(ped + kPedId), d, extra);
}

void Step(bool ground, const uint8_t* player, bool playerValid, float px, float py) {
    ++g_frame;
    const bool threat = *reinterpret_cast<const uint8_t*>(kThreatFlag) != 0;
    if (threat) ++g_tally.threatFrames;

    // cars: positions, velocities
    struct Car { const uint8_t* v; float x, y, z, vx, vy, speed, hx, hy; bool driven, burning, fresh, own; CarSeen* seen; };
    const uint8_t* ownCar = player && playerValid ? P(player, kPedCar) : nullptr;
    Car cars[96];
    int ncars = 0;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 400; v = game::NextInList(v, game::kVehicleNext), ++guard) {
        float x, y, z;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
        if (playerValid && (std::fabs(x - px) > 30.0f || std::fabs(y - py) > 30.0f)) continue;
        CarSeen& s = g_cars[reinterpret_cast<uintptr_t>(v)];
        bool fresh = s.frame != g_frame - 1;
        if (!fresh) {
            const float vx = (x - s.x) * 30.0f, vy = (y - s.y) * 30.0f;
            // a jump (respawn, recycle into a new car) is not motion: GTA2 reuses a car object at
            // a spawn point, at rest, so it starts over as a new car
            if (std::fabs(vx) < 40.0f && std::fabs(vy) < 40.0f) { s.vx += (vx - s.vx) * 0.5f; s.vy += (vy - s.vy) * 0.5f; }
            else fresh = true;
        }
        if (fresh) { s.vx = s.vy = 0; s.firstSeen = g_frame; s.halted = true; s.haltedAt = g_frame; s.recentTop = 0; }
        s.x = x; s.y = y; s.z = z; s.frame = g_frame;
        if (ncars >= 96) continue;
        Car& c = cars[ncars++];
        c.v = v; c.x = x; c.y = y; c.z = z; c.vx = s.vx; c.vy = s.vy;
        c.speed = std::hypot(s.vx, s.vy);
        c.hx = 0; c.hy = 1;
        game::ReadFacing(v, game::kVehiclePlacementPtr, &c.hx, &c.hy);
        c.driven = game::VehicleHasDriver(v);
        const int dmg = *reinterpret_cast<const int16_t*>(v + 0x74);
        c.burning = dmg >= 16000 && dmg <= 32000;
        c.seen = &s;
        // A car that came into being (or into the window) under 3 s ago and has not got going yet:
        // GTA2 creates traffic at rest on the lane; it is not a car that braked. The player's car
        // is not traffic.
        c.fresh = s.halted && s.haltedAt == s.firstSeen && g_frame - s.firstSeen < 90;
        c.own = v == ownCar;
        // Stop events of driven cars near the player (FIX-TRAFFIC-1): go -> stop with hysteresis;
        // a stop from over 2.5 blocks/s within the last half second is a hard one; a stop that
        // comes less than 2 s after the car last got going is a stop-start cycle.
        s.recentTop = (std::max)(c.speed, s.recentTop * 0.93f);
        if (c.driven && !c.own && playerValid && std::hypot(x - px, y - py) <= g_censusRadius) {
            if (!s.halted && c.speed < 0.4f) {
                s.halted = true;
                ++g_tally.stops;
                if (s.recentTop > 2.5f) ++g_tally.hardStops;
                if (g_frame - s.haltedAt < 60) ++g_tally.shortGo;
                s.haltedAt = g_frame;
            } else if (s.halted && c.speed > 0.8f) {
                s.halted = false;
                s.haltedAt = g_frame;
            }
        } else {
            s.halted = c.speed < 0.4f;
        }
    }
    if ((g_frame & 255) == 0 && g_cars.size() > 600) {
        for (auto it = g_cars.begin(); it != g_cars.end();) it = (g_frame - it->second.frame > 60) ? g_cars.erase(it) : std::next(it);
    }

    const bool census = g_censusEvery > 0 && (g_frame % g_censusEvery) == 0 && playerValid;
    const bool act = ground && g_enabled && g_patched;
    int acted = 0;

    const uintptr_t pool = *reinterpret_cast<const uintptr_t*>(kPedPoolPtr);
    if (!game::PlausiblePointer(reinterpret_cast<const void*>(pool))) return;
    const uint8_t* p = P(reinterpret_cast<const uint8_t*>(pool), 4);
    int live = 0;
    for (; game::PlausiblePointer(p) && live < 260; p = P(p, kPedNext), ++live) {
        if (p == player) continue;
        if (game::PlausiblePointer(P(p, kPedCar))) continue;   // in a car: counted as a car
        const float x = I32(p, game::kPedX) * game::kFixedScale, y = I32(p, game::kPedY) * game::kFixedScale,
                    z = I32(p, game::kPedZ) * game::kFixedScale;
        const float dp = playerValid ? std::hypot(x - px, y - py) : 0.0f;
        if (playerValid && dp > 30.0f) continue;
        const uint32_t id = *reinterpret_cast<const uint32_t*>(p + kPedId);
        const int st = I32(p, game::kPedState);
        const int iobj = I32(p, kPedInternalObjective);
        const bool panicking = (I32(p, kPedFlags) & 4) != 0;
        const bool fleeing = panicking || (iobj >= 1 && iobj <= 6) || (I32(p, kPedObjective) >= 1 && I32(p, kPedObjective) <= 6);
        PedSeen& seen = g_peds[id];
        if (fleeing && !seen.fleeing && st != kStateDead) {
            ++g_tally.fleeOnsets;
            Event("flee", p, dp, threat ? 1.0f : 0.0f);
        }
        seen.fleeing = fleeing;

        if (census && dp <= g_censusRadius) {
            ++g_tally.peds;
            switch (st) {
                case kStateWalking: case kStatePath: ++g_tally.walk; break;
                case kStateRunning: ++g_tally.run; break;
                case kStateStanding: ++g_tally.stand; break;
                case kStateDown: ++g_tally.down; break;
                case kStateDead: ++g_tally.dead; break;
                default: break;
            }
            if (panicking) ++g_tally.panic;
            if (fleeing) ++g_tally.flee;
        }
        if (seen.pending && g_frame - seen.dodgedAt >= 30) {
            seen.pending = false;
            const float lat1 = -(x - seen.qx) * seen.uy + (y - seen.qy) * seen.ux;
            const bool down = st == kStateDead || st == kStateDown;
            const bool clear = !down && std::fabs(lat1) >= 1.0f;
            if (down) ++g_tally.dodgeDown;
            if (clear) ++g_tally.dodgeClear;
            Log("ai: event dodgeout frame=%d id=%u lat0=%.2f lat1=%.2f state=%d %s", g_frame, id, seen.lat0, lat1, st,
                down ? "down" : (clear ? "clear" : "in_path"));
        }
        if (st == kStateDead || st == kStateDown) continue;

        // cars bearing down on this ped
        for (int i = 0; i < ncars; ++i) {
            const Car& c = cars[i];
            if (std::fabs(c.z - z) > 0.8f) continue;
            const float rx = x - c.x, ry = y - c.y;
            const float d = std::hypot(rx, ry);
            // near miss: a moving car passes within a block (sampled each frame, once per ped per 2 s)
            if (c.speed > 2.0f && d < 1.0f && g_frame - seen.nearMissAt > 60 && dp <= g_censusRadius) {
                seen.nearMissAt = g_frame;
                ++g_tally.nearMisses;
                Event("nearmiss", p, dp, c.speed);
            }
            if (!act || acted >= g_maxPerFrame || g_frame - seen.dodgedAt < 90) continue;
            if (c.burning && d < g_fireRadius) {
                if (!Civilian(p)) continue;
                const float n = d > 0.01f ? d : 1.0f;
                FleeFromPoint(const_cast<uint8_t*>(p), c.x, c.y, c.z, rx / n, ry / n);
                seen.dodgedAt = g_frame;
                ++acted; ++g_tally.fireFlees;
                Event("fireflee", p, dp, d);
                break;
            }
            if (!g_dodge || c.speed < g_dodgeSpeed) continue;
            const float ux = c.vx / c.speed, uy = c.vy / c.speed;
            const float along = rx * ux + ry * uy;
            const float lat = -rx * uy + ry * ux;   // signed, perpendicular to the path
            if (along < 0.3f || along > c.speed * g_dodgeTime + 0.6f || std::fabs(lat) > g_dodgeHalfWidth) continue;
            if (!Civilian(p)) continue;
            // flee from the point of the path beside him, straight off it
            const float qx = c.x + ux * along, qy = c.y + uy * along;
            float ax = -uy, ay = ux;                // the left of the path
            if (lat < 0) { ax = -ax; ay = -ay; }
            if (std::fabs(lat) < 0.05f) { ax = -uy; ay = ux; }
            FleeFromPoint(const_cast<uint8_t*>(p), qx - ax * 0.5f, qy - ay * 0.5f, c.z, ax, ay);
            seen.dodgedAt = g_frame;
            seen.pending = true;
            seen.qx = c.x; seen.qy = c.y; seen.ux = ux; seen.uy = uy; seen.lat0 = lat;
            ++acted; ++g_tally.dodges;
            Event("dodge", p, dp, c.speed);
            break;
        }
    }

    if (census) {
        for (int i = 0; i < ncars; ++i) {
            const Car& c = cars[i];
            if (std::hypot(c.x - px, c.y - py) > g_censusRadius) continue;
            if (c.burning) ++g_tally.burning;
            if (!c.driven || c.own) continue;   // parked; the player's own
            if (c.fresh) { ++g_tally.fresh; continue; }   // created at rest, not yet away
            ++g_tally.cars;
            ++g_tally.driven;
            if (c.speed > 0.4f) {
                ++g_tally.moving;
                g_tally.speedSum += c.speed;
                ++g_tally.movingAxisN;
                if (std::fabs(c.hx) > 0.985f || std::fabs(c.hy) > 0.985f) ++g_tally.axis;   // within 10 degrees of a street
            } else {
                ++g_tally.stopped;
                // queued: another car within 1.6 blocks ahead, in its heading
                bool queued = false;
                for (int j = 0; j < ncars && !queued; ++j) {
                    if (j == i) continue;
                    const float rx = cars[j].x - c.x, ry = cars[j].y - c.y;
                    const float along = rx * c.hx + ry * c.hy, lat = std::fabs(-rx * c.hy + ry * c.hx);
                    queued = along > 0.2f && along < 1.6f && lat < 0.5f;
                }
                if (queued) { ++g_tally.queued; continue; }
                ++g_tally.freeStop;
                // Why (FIX-TRAFFIC-1), first match: a person on foot (or the player) within 2 blocks
                // ahead in its lane; a car 1.6-3.5 blocks ahead in its lane (a queue the 1.6-block test
                // misses: GTA2's probe looks ~1.75 ahead, and the cars behind a queued car stop
                // further back); a car across its path (heading within 60 degrees of square to it,
                // up to 3.5 ahead); on or a block before a junction (the road arrows run both ways:
                // lights and give-ways); else mid-street with nothing seen.
                bool cause = false;
                int guardQ = 0;
                for (const uint8_t* q = P(reinterpret_cast<const uint8_t*>(pool), 4); game::PlausiblePointer(q) && !cause && guardQ < 260;
                     q = P(q, kPedNext), ++guardQ) {
                    if (game::PlausiblePointer(P(q, kPedCar))) continue;
                    const int qs = I32(q, game::kPedState);
                    if (qs == kStateDead) continue;
                    const float rx = I32(q, game::kPedX) * game::kFixedScale - c.x, ry = I32(q, game::kPedY) * game::kFixedScale - c.y;
                    if (std::fabs(rx) > 3.0f || std::fabs(ry) > 3.0f) continue;
                    const float along = rx * c.hx + ry * c.hy, lat = std::fabs(-rx * c.hy + ry * c.hx);
                    cause = along > 0.0f && along < 2.0f && lat < 0.7f;
                }
                if (cause) { ++g_tally.fsPed; continue; }
                bool gap = false, cross = false;
                for (int j = 0; j < ncars; ++j) {
                    if (j == i) continue;
                    const float rx = cars[j].x - c.x, ry = cars[j].y - c.y;
                    const float along = rx * c.hx + ry * c.hy, lat = std::fabs(-rx * c.hy + ry * c.hx);
                    if (along > 0.2f && along < 3.5f && lat < 0.7f) gap = true;
                    else if (along > -0.5f && along < 3.5f && lat < 3.0f &&
                             std::fabs(cars[j].hx * c.hx + cars[j].hy * c.hy) < 0.5f)
                        cross = true;
                }
                if (gap) { ++g_tally.fsGap; continue; }
                if (cross) { ++g_tally.fsCross; continue; }
                const ViewQueries& vq = ViewModeQueries();
                bool junction = false;
                if (vq.roadArrows) {
                    for (int k = 0; k <= 3 && !junction; ++k) {
                        const float ax = c.x + c.hx * static_cast<float>(k), ay = c.y + c.hy * static_cast<float>(k);
                        const int a = vq.roadArrows(vq.context, ax, static_cast<float>(gta2::kMapHeight) - ay, c.z + 0.95f) & 0xF;
                        junction = (a & 3) && (a & 12);
                    }
                }
                if (junction) ++g_tally.fsJunction; else ++g_tally.fsMid;
                if (g_stopLog && g_frame - c.seen->stopLoggedAt >= 60) {
                    c.seen->stopLoggedAt = g_frame;
                    int a[3] = {};
                    for (int k = 0; k <= 2 && vq.roadArrows; ++k)
                        a[k] = vq.roadArrows(vq.context, c.x + c.hx * k, static_cast<float>(gta2::kMapHeight) - (c.y + c.hy * k), c.z + 0.95f);
                    float best = 99.0f, bAlong = 0, bLat = 0, bSpeed = 0;
                    for (int j = 0; j < ncars; ++j) {
                        if (j == i) continue;
                        const float d = std::hypot(cars[j].x - c.x, cars[j].y - c.y);
                        if (d < best) {
                            best = d;
                            bAlong = (cars[j].x - c.x) * c.hx + (cars[j].y - c.y) * c.hy;
                            bLat = -(cars[j].x - c.x) * c.hy + (cars[j].y - c.y) * c.hx;
                            bSpeed = cars[j].speed;
                        }
                    }
                    Log("ai: stop frame=%d car=%08X model=%d x=%.2f y=%.2f z=%.2f d=%.1f head=%.2f,%.2f %s for=%.1fs arrows=%02X,%02X,%02X "
                        "nearest car d=%.2f along=%.2f lat=%.2f v=%.2f dmg=%d",
                        g_frame, static_cast<unsigned>(reinterpret_cast<uintptr_t>(c.v)), *reinterpret_cast<const int32_t*>(c.v + 0x84),
                        c.x, c.y, c.z, std::hypot(c.x - px, c.y - py), c.hx, c.hy, junction ? "junction" : "mid",
                        (g_frame - c.seen->haltedAt) / 30.0f, a[0], a[1], a[2], best, bAlong, bLat, bSpeed,
                        *reinterpret_cast<const int16_t*>(c.v + 0x74));
                }
            }
        }
        ++g_tally.samples;
        if (g_tally.samples >= 2) {   // one line a second at 30 fps with census_every 15
            const Tally& t = g_tally;
            const float s = static_cast<float>(t.samples);
            Log("ai: frame=%d view=%s peds=%.1f walk=%.1f run=%.1f stand=%.1f down=%.1f dead=%.1f panic=%.1f flee=%.1f "
                "cars=%.1f moving=%.1f stopped=%.1f queued=%.1f freestop=%.1f axis=%.2f speed=%.2f burning=%.1f "
                "threat=%d onsets=%d dodges=%d fireflees=%d nearmiss=%d dodgeclear=%d dodgedown=%d "
                "fs_ped=%.1f fs_gap=%.1f fs_cross=%.1f fs_junction=%.1f fs_mid=%.1f stops=%d hardstops=%d stopstart=%d fresh=%.1f",
                g_frame, ground ? "street" : "classic", t.peds / s, t.walk / s, t.run / s, t.stand / s, t.down / s,
                t.dead / s, t.panic / s, t.flee / s, t.cars / s, t.moving / s, t.stopped / s, t.queued / s,
                t.freeStop / s, t.movingAxisN ? static_cast<float>(t.axis) / t.movingAxisN : 0.0f,
                t.moving ? t.speedSum / t.moving : 0.0f, t.burning / s, t.threatFrames, t.fleeOnsets, t.dodges,
                t.fireFlees, t.nearMisses, t.dodgeClear, t.dodgeDown, t.fsPed / s, t.fsGap / s, t.fsCross / s,
                t.fsJunction / s, t.fsMid / s, t.stops, t.hardStops, t.shortGo, t.fresh / s);
            g_tally = Tally{};
        }
    }
    if ((g_frame & 1023) == 0 && g_peds.size() > 2000) g_peds.clear();
}

float IniFloat(const char* ini, const char* key, float def) {
    char buf[32] = {};
    GetPrivateProfileStringA("city_ai", key, "", buf, sizeof buf, ini);
    return buf[0] ? static_cast<float>(atof(buf)) : def;
}

}  // namespace

void CityAiInstall(const char* ini) {
    g_enabled = GetPrivateProfileIntA("city_ai", "enabled", 1, ini) != 0;
    char env[8] = {};
    if (GetEnvironmentVariableA("GTA2DX9_CITY_AI", env, sizeof env) && env[0] == '0') g_enabled = false;
    g_gunRadius = IniFloat(ini, "gun_radius", g_gunRadius);
    g_carRadius = IniFloat(ini, "car_radius", g_carRadius);
    g_safeDistance = IniFloat(ini, "safe_distance", g_safeDistance);
    g_dodge = GetPrivateProfileIntA("city_ai", "dodge", 1, ini) != 0;
    g_dodgeSpeed = IniFloat(ini, "dodge_speed", g_dodgeSpeed);
    g_dodgeTime = IniFloat(ini, "dodge_time", g_dodgeTime);
    g_fireRadius = IniFloat(ini, "fire_radius", g_fireRadius);
    g_censusEvery = GetPrivateProfileIntA("city_ai", "census_every", g_censusEvery, ini);
    {
        char tl[8] = {};
        g_stopLog = GetEnvironmentVariableA("GTA2DX9_TRAFFIC_LOG", tl, sizeof tl) && tl[0] == '1';
    }
    g_censusRadius = IniFloat(ini, "census_radius", g_censusRadius);
    auto clampf = [](float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); };
    g_gunRadius = clampf(g_gunRadius, 1.0f, 40.0f);
    g_carRadius = clampf(g_carRadius, 1.0f, 40.0f);
    g_safeDistance = clampf(g_safeDistance, 2.0f, 60.0f);
    g_cityAiGunRadius = static_cast<int32_t>(g_gunRadius * 16384.0f);
    g_cityAiCarRadius = static_cast<int32_t>(g_carRadius * 16384.0f);
    g_cityAiSafeDistance = static_cast<int32_t>(g_safeDistance * 16384.0f);
    Log("ai: city_ai %s; gun %.1f car %.1f safe %.1f; dodge %d (%.1f b/s, %.1f s); fire %.1f; census every %d within %.0f",
        g_enabled ? "on" : "off (census only)", g_gunRadius, g_carRadius, g_safeDistance, g_dodge ? 1 : 0, g_dodgeSpeed,
        g_dodgeTime, g_fireRadius, g_censusEvery, g_censusRadius);
}

void CityAiUpdate(bool groundView, const void* playerPed, bool playerValid, float playerX, float playerY) {
    if (!g_sitesChecked) {
        g_sitesChecked = true;
        g_sitesOk = CheckSites();
        if (!g_sitesOk) Log("ai: gta2.exe is not the 9.6 this knows; reactions as shipped, census only");
    }
    if (g_sitesOk) Patch(groundView && g_enabled && playerValid);
    if (!playerValid) return;   // menus, loading: the pools are not to be walked
    GTA2_TRY {
        Step(groundView, static_cast<const uint8_t*>(playerPed), playerValid, playerX, playerY);
    } GTA2_EXCEPT {
        static int faults = 0;
        if (++faults <= 3) Log("ai: a read faulted (stale entity); skipped this frame");
    }
}

}  // namespace gta2dx9
