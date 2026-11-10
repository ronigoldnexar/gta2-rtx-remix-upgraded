#include "view_modes.h"

#include "cockpit_mode.h"
#include "eye_collision.h"

#define DIRECTINPUT_VERSION 0x0800
#include <dinput.h>

#include <algorithm>
#include <map>
#include <vector>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>

#include "../../src/gta2_map.h"
#include "beats.h"
#include "boarding.h"
#include "car_bodies.h"
#include "compat.h"
#include "game_access.h"
#include "live_geometry.h"
#include "log.h"
#include "map_objects.h"
#include "ragdoll.h"   // FIX-KNOCKDOWN: KnockdownPlayerEye
#include "model_store.h"
#include "remix_api.h"
#include "vehicle_fx.h"

namespace gta2dx9 {
namespace {

constexpr float kPi = 3.14159265f;
constexpr float kDegToRad = kPi / 180.0f;

// The player object (see game_save.cpp, where its +0x38 is the score keeper).
// Which of its fields is the pedestrian is not written down anywhere, so it is
// searched for by signature - see LocatePlayer in the header.
constexpr uintptr_t kPlayerObjectPtr = 0x005EB4FC;
constexpr uintptr_t kPlayerObjectScanBytes = 0x200;
constexpr uintptr_t kCameraScanBytes = 0x100;
// Frames between scans while nothing has been found. A scan is a few hundred
// guarded reads, which is cheap, but not something to do thirty times a second
// in the front end where there is no player to find.
constexpr int kScanEveryFrames = 15;

ViewModeSettings g_settings;
ViewLook g_look;

double Now() {
    static double toSeconds = 0.0;
    if (toSeconds == 0.0) {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        toSeconds = 1.0 / static_cast<double>(f.QuadPart);
    }
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return static_cast<double>(c.QuadPart) * toSeconds;
}

// FIX-FP-ENTRY (pfeel32): the seat eye's raw position and car_bodies' answer (view_modes.h).
struct FpSeat { bool valid = false; gta2::Vec3 raw{}; gta2::Vec3 delta{}; double rawAt = 0.0, deltaAt = 0.0; };
FpSeat g_fpSeat;
// FIX-FP-ENTRY: an ease in and out over 0..1.
float Smooth01(float x) { x = x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); return x * x * (3.0f - 2.0f * x); }
// GTA2DX9_FP_BOARD_EYE=0: the old first-person entry/exit (the eye at the game's spot, a 0.12 s glide).
bool FpSeatGlideOn() {
    static int on = -1;
    if (on < 0) { char v[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_FP_BOARD_EYE", v, sizeof v) && v[0] == '0' ? 0 : 1; }
    return on != 0;
}
float WrapAngle(float a) {
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

// A read that cannot fault, for pointers that came out of a scan rather than
// off a known structure. It was ReadProcessMemory on every read, which under Wine
// is a wineserver round trip: the player locator walks the vehicle list at the
// wheel (VehicleDrivenBy), and that cost 3-4 ms of every frame and 20-70 ms when
// the server was busy (PERF-2, cam_locate in the frame log). Now the region an
// address lies in is checked once with VirtualQuery (committed, readable, no guard
// page) and remembered; reads inside a known region are plain loads under the
// fault guard, which also covers a region freed since.
struct ReadableRange { uintptr_t lo, hi; };
ReadableRange g_readable[64];
int g_readableCount = 0, g_readableNext = 0;
unsigned g_readableCalls = 0;
bool KnownReadable(uintptr_t address, size_t bytes) {
    if (++g_readableCalls >= 65536) { g_readableCalls = 0; g_readableCount = 0; g_readableNext = 0; }   // look again now and then
    for (int i = 0; i < g_readableCount; ++i) {
        if (address >= g_readable[i].lo && address + bytes <= g_readable[i].hi) return true;
    }
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(reinterpret_cast<LPCVOID>(address), &mbi, sizeof mbi)) return false;
    const DWORD readable = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                           PAGE_EXECUTE_WRITECOPY;
    if (mbi.State != MEM_COMMIT || !(mbi.Protect & readable) || (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
    const uintptr_t lo = reinterpret_cast<uintptr_t>(mbi.BaseAddress), hi = lo + mbi.RegionSize;
    if (address + bytes > hi) return false;
    g_readable[g_readableNext] = {lo, hi};
    g_readableNext = (g_readableNext + 1) % 64;
    if (g_readableCount < 64) ++g_readableCount;
    return true;
}
template <typename T>
bool ReadAt(uintptr_t address, T* out) {
    if (!game::InUserSpace(address, sizeof(T))) return false;
    if (!KnownReadable(address, sizeof(T))) return false;
    bool ok = true;
    GTA2_TRY { memcpy(out, reinterpret_cast<const void*>(address), sizeof(T)); } GTA2_EXCEPT { ok = false; }
    return ok;
}

bool Plausible(uintptr_t address) {
    return game::PlausiblePointer(reinterpret_cast<const void*>(address));
}

// Whether `ped` still leads to its physics object and back: the one link that
// holds whatever he is doing - on foot, at the wheel, knocked down. The full
// signature below needs his sprite to be a pedestrian's, which it is not while
// he sits in a car, so a pedestrian once found is kept by this test alone.
bool PedStillLinked(uintptr_t ped) {
    if (!Plausible(ped)) return false;
    uintptr_t physics = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    uintptr_t back = 0;
    return ReadAt(physics + game::kPhysicsPed, &back) && back == ped;
}

// Whether `ped` is a pedestrian structure, by the three cross-links described
// in the header.
bool PedSignature(uintptr_t ped) {
    if (!Plausible(ped)) return false;
    uintptr_t physics = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    uintptr_t back = 0;
    if (!ReadAt(physics + game::kPhysicsPed, &back) || back != ped) return false;
    uintptr_t sprite = 0;
    if (!ReadAt(physics + game::kPhysicsSprite, &sprite) || !Plausible(sprite)) return false;
    int32_t base = 0;
    if (!ReadAt(sprite + game::kSpriteObjectBase, &base) || base != game::kSpriteBasePed) return false;
    uintptr_t owner = 0;
    if (!ReadAt(sprite + game::kSpriteObjectOwner, &owner) || owner != physics) return false;
    return true;
}

// Where the player's pointer was found last time, so it is read rather than
// searched for on every frame.
enum class Slot { None, PlayerObjectIsPed, PlayerObject, Camera };
Slot g_slot = Slot::None;
uintptr_t g_slotOffset = 0;
int g_scanCooldown = 0;
bool g_slotLogged = false;

// The fallback feed from the sprite pass: this frame's pedestrian on foot
// nearest the game's camera, and last frame's, which is the one a frame reads.
const void* g_nearPedNow = nullptr;
float g_nearPedNowDist = 1e9f;
const void* g_nearPed = nullptr;
float g_nearPedDist = 1e9f;

// The ped the slots last held: once he gets into a car the camera's slot
// turns to the car and his sprite goes, but a vehicle's driver word still
// names him, which is how he is followed at the wheel.
uintptr_t g_lastPlayerPed = 0;
// FIX-CAMERA-13 (pmv10): the id word (+0x200) that ped held when the slots last named him. The game
// recycles a ped's struct for a new pedestrian after an arrest or a death; the driver word of a car then
// names the struct again (run pmv10a_bil: BUSTED, and 0.4 s later the struct was a medic driving an
// ambulance off, followed as "the player at the wheel" for 33 s: first person with no cab, the real hero
// at the station unseen). The new pedestrian gets a new id.
uint32_t g_lastPlayerPedId = 0;
constexpr uintptr_t kPedIdWord = 0x200;

// The vehicle whose driver word is `ped`, or 0.
uintptr_t VehicleDrivenBy(uintptr_t ped) {
    if (!ped) return 0;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        uintptr_t driver = 0;
        if (ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleDriver, &driver) && driver == ped) {
            return reinterpret_cast<uintptr_t>(v);
        }
    }
    return 0;
}

// A pedestrian by his links alone, standing within a few tiles of the game's
// camera: what a scan falls back to when no candidate passes the full
// signature, which the player's new body fails for a while after an arrest
// or a death.
bool PedLinkedNearCamera(uintptr_t ped) {
    if (!PedStillLinked(ped)) return false;
    uintptr_t physics = 0, sprite = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !ReadAt(physics + game::kPhysicsSprite, &sprite) || !Plausible(sprite)) {
        return false;
    }
    int32_t fx = 0, fy = 0;
    if (!ReadAt(sprite + game::kPlaceX, &fx) || !ReadAt(sprite + game::kPlaceY, &fy)) return false;
    float camX = 0.0f, camY = 0.0f;
    if (!game::CameraPosition(&camX, &camY)) return false;
    return std::hypot(fx * game::kFixedScale - camX, fy * game::kFixedScale - camY) < 4.0f;
}

uintptr_t ScanForPed(uintptr_t base, uintptr_t bytes, uintptr_t* offsetOut) {
    for (int pass = 0; pass < 2; ++pass) {
        for (uintptr_t offset = 0; offset < bytes; offset += sizeof(uintptr_t)) {
            uintptr_t candidate = 0;
            if (!ReadAt(base + offset, &candidate)) continue;
            if (candidate == base) continue;
            if (pass == 0 ? PedSignature(candidate) : PedLinkedNearCamera(candidate)) {
                *offsetOut = offset;
                return candidate;
            }
        }
    }
    return 0;
}

uintptr_t RememberedPed() {
    uintptr_t playerObject = 0;
    switch (g_slot) {
        case Slot::PlayerObjectIsPed:
            if (ReadAt(kPlayerObjectPtr, &playerObject) && PedStillLinked(playerObject)) return playerObject;
            return 0;
        case Slot::PlayerObject: {
            uintptr_t ped = 0;
            if (ReadAt(kPlayerObjectPtr, &playerObject) && Plausible(playerObject) &&
                ReadAt(playerObject + g_slotOffset, &ped) && PedStillLinked(ped)) {
                return ped;
            }
            return 0;
        }
        case Slot::Camera: {
            const uint8_t* camera = game::CameraStruct();
            uintptr_t ped = 0;
            if (camera && ReadAt(reinterpret_cast<uintptr_t>(camera) + g_slotOffset, &ped) &&
                PedStillLinked(ped)) {
                return ped;
            }
            return 0;
        }
        default:
            return 0;
    }
}

uintptr_t ScanForPlayer() {
    uintptr_t playerObject = 0;
    if (ReadAt(kPlayerObjectPtr, &playerObject) && Plausible(playerObject)) {
        if (PedSignature(playerObject)) {
            g_slot = Slot::PlayerObjectIsPed;
            g_slotOffset = 0;
            return playerObject;
        }
        uintptr_t offset = 0;
        if (uintptr_t ped = ScanForPed(playerObject, kPlayerObjectScanBytes, &offset)) {
            g_slot = Slot::PlayerObject;
            g_slotOffset = offset;
            return ped;
        }
    }
    if (const uint8_t* camera = game::CameraStruct()) {
        uintptr_t offset = 0;
        if (uintptr_t ped = ScanForPed(reinterpret_cast<uintptr_t>(camera), kCameraScanBytes, &offset)) {
            g_slot = Slot::Camera;
            g_slotOffset = offset;
            return ped;
        }
    }
    g_slot = Slot::None;
    return 0;
}

// The car the game's camera is centred on, if someone is driving it: the
// camera leads a moving car by a tile or two, so the radius is generous.
uintptr_t DrivenCarAtCamera(float camX, float camY) {
    uintptr_t best = 0;
    float bestDist = 3.0f;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        if (!game::VehicleHasDriver(v)) continue;
        float x = 0.0f, y = 0.0f, z = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
        const float d = std::hypot(x - camX, y - camY);
        if (d < bestDist) {
            bestDist = d;
            best = reinterpret_cast<uintptr_t>(v);
        }
    }
    return best;
}

// FIX-CAMERA-16 (qaexp8-ste-third-first-riding-a-train-the-3d-views-lose-the-player): aboard a train the game keeps
// no player ped (the player struct is gone for the ride) and its camera rides the train. The train (models 59-61:
// the cab and its carriages) the game's camera is on, within 3 blocks (the camera leads a moving vehicle), nearest.
uintptr_t TrainAtCamera(float camX, float camY, float* dist) {
    uintptr_t best = 0;
    float bestDist = 3.0f;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        int32_t model = 0;
        if (!ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model) || model < 59 || model > 61) continue;
        float x = 0.0f, y = 0.0f, z = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
        const float d = std::hypot(x - camX, y - camY);
        if (d < bestDist) {
            bestDist = d;
            best = reinterpret_cast<uintptr_t>(v);
        }
    }
    if (dist) *dist = bestDist;
    return best;
}
// The train `train` is still in the vehicle list (a train model); its distance from (camX, camY).
bool TrainStillLive(uintptr_t train, float camX, float camY, float* dist) {
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        if (reinterpret_cast<uintptr_t>(v) != train) continue;
        int32_t model = 0;
        if (!ReadAt(train + game::kVehicleModel, &model) || model < 59 || model > 61) return false;
        float x = 0.0f, y = 0.0f, z = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) return false;
        *dist = std::hypot(x - camX, y - camY);
        return true;
    }
    return false;
}
// Where LocatePlayer last found him (game frame) and when; the train he rides.
float g_foundX = -1.0f, g_foundY = -1.0f;
double g_foundAt = -1.0;
uintptr_t g_rideTrain = 0;
int RideTrainOn() {
    static int on = -1;
    if (on < 0) { char b[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_CAM_TRAIN_RIDE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    return on;
}

}  // namespace

bool NearestVehicle(float x, float y, float within, bool parkedOnly, float* vx, float* vy, float* distance,
                    bool* driven, const void** vehicle) {
    bool found = false;
    float best = within;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        const bool hasDriver = game::VehicleHasDriver(v);
        if (parkedOnly && hasDriver) continue;
        float cx = 0.0f, cy = 0.0f, cz = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
        const float d = std::hypot(cx - x, cy - y);
        // The game keeps a car of the player's own beside him (his last, or his
        // next); a parked car under his feet is that, not one to walk to.
        if (parkedOnly && d < 0.55f) continue;
        if (d < best) {
            best = d;
            found = true;
            *vx = cx;
            *vy = cy;
            *distance = d;
            *driven = hasDriver;
            if (vehicle) *vehicle = v;
        }
    }
    return found;
}

bool VehicleFacing(const void* vehicle, float* dirX, float* dirY) {
    if (!vehicle || !Plausible(reinterpret_cast<uintptr_t>(vehicle))) return false;
    return game::ReadFacing(reinterpret_cast<const uint8_t*>(vehicle), game::kVehiclePlacementPtr, dirX, dirY);
}

template <typename T>
bool WriteAt(uintptr_t address, const T& value) {
    if (!game::InUserSpace(address, sizeof(T))) return false;
    SIZE_T put = 0;
    return WriteProcessMemory(GetCurrentProcess(), reinterpret_cast<LPVOID>(address), &value, sizeof(T), &put) &&
           put == sizeof(T);
}

ViewQueries g_devQueries;
void ViewModeSetQueries(const ViewQueries& queries) { g_devQueries = queries; }
const ViewQueries& ViewModeQueries() { return g_devQueries; }

// ---- QB-6: aiming -------------------------------------------------------------------
AimState g_aim;
const AimState& ViewAim() { return g_aim; }

namespace {
bool LineHits(bool (*test)(void*, float, float, float), float x0, float y0, float z0, float x1, float y1, float z1) {
    if (!test) return false;
    const float d = std::sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0) + (z1 - z0) * (z1 - z0));
    const int steps = (std::max)(2, (std::min)(64, static_cast<int>(d / 0.2f)));
    // The first and last fifth of a block are the shooter's and the target's own cells.
    for (int i = 1; i < steps; ++i) {
        const float t = static_cast<float>(i) / steps;
        if (t * d < 0.2f || (1.0f - t) * d < 0.2f) continue;
        if (test(g_devQueries.context, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z0 + (z1 - z0) * t)) return true;
    }
    return false;
}
}  // namespace
bool ViewLineBlocked(float x0, float y0, float z0, float x1, float y1, float z1) {
    return LineHits(g_devQueries.blocked, x0, y0, z0, x1, y1, z1);
}
bool ViewLineWalled(float x0, float y0, float z0, float x1, float y1, float z1) {
    return LineHits(g_devQueries.walled, x0, y0, z0, x1, y1, z1);
}
bool ViewPointWalled(float x, float y, float z) {
    return g_devQueries.walled && g_devQueries.walled(g_devQueries.context, x, y, z);
}

namespace {
// The player's weapon words last frame: a drop in the ammunition or a restart of the reload
// timer with the same weapon object in his hands is a shot (live_geometry.cpp reads a
// stranger's shots the same way).
uintptr_t g_aimWeaponObject = 0;
int g_aimLastAmmo = -1, g_aimLastReload = -1;

bool CameraLogOnForAim();
void UpdateAim(const PlayerState& player, float px, float pz, float headingYaw, float dt) {
    AimState& a = g_aim;
    a.valid = player.valid;
    a.x = px;
    a.z = pz;
    a.headingYaw = headingYaw;
    int weapon = 0, ammo = -1, reload = -1;
    uintptr_t object = 0;
    int state = 0;
    if (player.valid && !player.inVehicle && player.ped) {
        GTA2_TRY {
            const uint8_t* ped = static_cast<const uint8_t*>(player.ped);
            weapon = game::PedWeaponOf(ped, nullptr);
            const uint8_t* w = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedCurrentWeapon);
            if (weapon > 0 && game::PlausiblePointer(w)) {
                object = reinterpret_cast<uintptr_t>(w);
                ammo = *reinterpret_cast<const int16_t*>(w + game::kWeaponAmmo);
                reload = *reinterpret_cast<const int16_t*>(w + 2);
            }
        } GTA2_EXCEPT {
            weapon = 0;
            object = 0;
        }
        state = ReadPedWords(player.ped).state;
    }
    a.weapon = weapon > 0 ? weapon : 0;
    // Standing armed: not knocked down, dead or arrested (8/9), not in a car's door (3/4).
    a.armed = a.weapon > 0 && state != 8 && state != 9 && state != 3 && state != 4;
    if (object && object == g_aimWeaponObject) {
        const bool shot = (ammo >= 0 && g_aimLastAmmo >= 0 && ammo < g_aimLastAmmo) ||
                          (reload > g_aimLastReload && g_aimLastReload >= 0);
        if (shot && a.armed) {
            ++a.shots;
            a.lastShot = Now();
        }
    }
    g_aimWeaponObject = object;
    g_aimLastAmmo = ammo;
    g_aimLastReload = reload;
    // The framing: over the shoulder for 2.5 s after a shot, a light lean in while armed.
    const bool firing = a.armed && a.lastShot > 0.0 && Now() - a.lastShot < 2.5;
    float want = (CurrentViewMode() == ViewMode::ThirdPerson && a.armed) ? (firing ? 1.0f : 0.35f) : 0.0f;
    float tau = want > a.aimMix ? 0.18f : 0.5f;   // in quickly, out gently
    // FIX-CAMERA-11 (feel15-pistol-runs-dry-camera-pulls-back-and-aim-pose-stays): the last round fired, the game
    // takes the weapon away (weapon none) and the framing dropped to the unarmed one at once: the camera eased 1.4x
    // further out within a second of the last shot, a zoom-out at the moment he runs dry. Standing (not knocked down,
    // dead, arrested or at a car door) with the weapon gone inside the firing window, the framing stays as it was
    // until 2.5 s after the last shot, then eases out on a 2.5 s time constant (under 15 % a second). Only the camera's mix: the figure's armed state is
    // the game's. GTA2DX9_CAM_DRY_HOLD=0 restores the old drop (A/B).
    {
        static int dryHoldOn = -1;
        if (dryHoldOn < 0) { char b[8] = {}; dryHoldOn = GetEnvironmentVariableA("GTA2DX9_CAM_DRY_HOLD", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        static double dryUntil = 0.0, dryEaseUntil = 0.0;
        const bool standing = state != 8 && state != 9 && state != 3 && state != 4;
        if (dryHoldOn && CurrentViewMode() == ViewMode::ThirdPerson && standing && !a.armed && a.weapon == 0) {
            if (dryUntil == 0.0 && a.lastShot > 0.0 && Now() - a.lastShot < 2.5 && a.aimMix > 0.05f) {
                dryUntil = a.lastShot + 2.5;
                dryEaseUntil = dryUntil + 8.0;
                if (CameraLogOnForAim()) Log("cam: weapon gone %.2f s after the last shot: the aim framing (%.2f) held until 2.5 s", Now() - a.lastShot, a.aimMix);
            }
            if (dryUntil > 0.0 && Now() < dryUntil) { want = a.aimMix; }
            else if (dryUntil > 0.0 && Now() < dryEaseUntil) { tau = 2.5f; }
        } else if (a.armed || !standing) {
            dryUntil = dryEaseUntil = 0.0;
        }
    }
    a.aimMix += (want - a.aimMix) * (1.0f - std::exp(-(dt > 0.0f && dt < 0.25f ? dt : 1.0f / 30.0f) / tau));
    if (a.aimMix < 0.002f) a.aimMix = 0.0f;
}
}  // namespace

// After a warp the game streams the map around the player's new place; until
// it has, there is nothing under him and he sinks through the lid he was put
// on (seen on every warp of fifty blocks or more). So the position is held for
// a moment, written again every frame from the key poll.
struct WarpHold {
    bool active = false;
    int32_t fx = 0, fy = 0, fz = 0;
    double until = 0.0;
};
WarpHold g_warpHold;

void StartWarpHold(float x, float y, float z, double seconds) {
    g_warpHold.active = true;
    g_warpHold.fx = static_cast<int32_t>(x * (1 << 14));
    g_warpHold.fy = static_cast<int32_t>(y * (1 << 14));
    g_warpHold.fz = static_cast<int32_t>(z * (1 << 14));
    g_warpHold.until = Now() + seconds;
}

void ServiceWarpHold() {
    if (!g_warpHold.active) return;
    if (Now() > g_warpHold.until) { g_warpHold.active = false; return; }
    PlayerState player;
    if (!LocatePlayer(&player) || !player.valid || player.inVehicle || !player.ped) return;
    const uintptr_t ped = reinterpret_cast<uintptr_t>(player.ped);
    uintptr_t physics = 0, place = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return;
    if (!ReadAt(physics + game::kPhysicsSprite, &place) || !Plausible(place)) return;
    WriteAt(place + game::kPlaceX, g_warpHold.fx); WriteAt(place + game::kPlaceY, g_warpHold.fy); WriteAt(place + game::kPlaceZ, g_warpHold.fz);
    WriteAt(ped + game::kPedX, g_warpHold.fx); WriteAt(ped + game::kPedY, g_warpHold.fy); WriteAt(ped + game::kPedZ, g_warpHold.fz);
}

// FIX-COLLISION: the player's ground position (game frame, tiles) moved by the street
// props' collision (prop_collision.cpp): x and y only, the level is the game's. Written
// where the warp hold writes it, the sprite's placement and the ped's own copy.
bool WritePlayerGroundPosition(const void* pedPtr, float x, float y) {
    const uintptr_t ped = reinterpret_cast<uintptr_t>(pedPtr);
    if (!Plausible(ped)) return false;
    uintptr_t physics = 0, place = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    if (!ReadAt(physics + game::kPhysicsSprite, &place) || !Plausible(place)) return false;
    const int32_t fx = static_cast<int32_t>(std::lround(x * (1 << 14)));
    const int32_t fy = static_cast<int32_t>(std::lround(y * (1 << 14)));
    return WriteAt(place + game::kPlaceX, fx) && WriteAt(place + game::kPlaceY, fy) &&
           WriteAt(ped + game::kPedX, fx) && WriteAt(ped + game::kPedY, fy);
}

// The ped's state word (game::kPedState), -1 when unreadable.
int ReadPedState(const void* pedPtr) {
    int32_t state = -1;
    if (!ReadAt(reinterpret_cast<uintptr_t>(pedPtr) + game::kPedState, &state)) return -1;
    return state;
}

// Where a developer warp may put the player: the surface under the asked-for
// point at the reference level, else the nearest road (then pavement) cell
// within six blocks, else nowhere. Game coordinates in and out (x east, y
// south, z the level); the queries speak the renderer's (z north = kMapHeight - y).
bool ResolveWarpFloor(float x, float y, float refLevel, float* outX, float* outY, float* outZ, const char** how) {
    *outX = x; *outY = y; *outZ = refLevel; *how = "as asked (no floor query)";
    if (!g_devQueries.groundAt) return true;
    auto ground = [&](float gx, float gy, float ceiling, float* level, int* type) {
        return g_devQueries.groundAt(g_devQueries.context, gx, static_cast<float>(gta2::kMapHeight) - gy, ceiling, level, type);
    };
    float level = 0.0f;
    int type = 0;
    if (ground(x, y, refLevel + 0.95f, &level, &type) && type >= 1 && type <= 3) {
        *outZ = level; *how = "the floor under the point"; return true;
    }
    // Spiral out over the cells, nearest first: a road at the reference level,
    // then a road at any level, then pavement at the reference level.
    struct Cell { int dx, dy; };
    std::vector<Cell> cells;
    for (int dy = -6; dy <= 6; ++dy) for (int dx = -6; dx <= 6; ++dx) if (dx * dx + dy * dy <= 36) cells.push_back({dx, dy});
    std::sort(cells.begin(), cells.end(), [](const Cell& a, const Cell& b) { return a.dx * a.dx + a.dy * a.dy < b.dx * b.dx + b.dy * b.dy; });
    const float cx0 = std::floor(x) + 0.5f, cy0 = std::floor(y) + 0.5f;
    struct Pass { float ceiling; int want; const char* name; };
    const Pass passes[3] = {{refLevel + 0.95f, 1, "the nearest road cell at the level"},
                            {8.0f, 1, "the nearest road cell at any level"},
                            {refLevel + 0.95f, 2, "the nearest pavement cell at the level"}};
    for (const Pass& pass : passes) {
        for (const Cell& c : cells) {
            const float gx = cx0 + c.dx, gy = cy0 + c.dy;
            if (ground(gx, gy, pass.ceiling, &level, &type) && type == pass.want) {
                *outX = gx; *outY = gy; *outZ = level; *how = pass.name; return true;
            }
        }
    }
    return false;
}

// Whether the game point (gx, gy) has a walkable surface at `level`
// (within half a block of it): the queries speak the renderer's z.
bool WarpFloorMatches(float gx, float gy, float level) {
    if (!g_devQueries.groundAt) return true;
    float y = 0.0f;
    int type = 0;
    return g_devQueries.groundAt(g_devQueries.context, gx, static_cast<float>(gta2::kMapHeight) - gy, level + 0.95f, &y, &type) &&
           std::fabs(y - level) < 0.5f && type >= 1 && type <= 3;
}

// The nearest driverless car on the given level whose model is an ordinary
// traffic car (no wreck, train, trailer, tank or special), for the scene warp.
bool NearestParkedTrafficCar(float x, float y, float within, float level, float* vx, float* vy, float* distance,
                             const void** vehicle) {
    bool found = false;
    float best = within;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        if (game::VehicleHasDriver(v)) continue;
        int32_t model = -1;
        if (!ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model)) continue;
        if (model < 0 || model > 86 || model == 3 || model == 6 || model == 22 || model == 54 || model == 55 ||
            (model >= 59 && model <= 61) || model == 65 || model == 66 || (model >= 72 && model <= 81)) continue;
        float cx = 0.0f, cy = 0.0f, cz = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
        if (std::fabs(cz - level) > 0.5f) continue;
        const float d = std::hypot(cx - x, cy - y);
        if (d < 0.55f || d >= best) continue;
        best = d;
        found = true;
        *vx = cx; *vy = cy; *distance = d;
        if (vehicle) *vehicle = v;
    }
    return found;
}

namespace {
bool WarpPlayerToCarDoor(const PlayerState& player, const void* car, float cx, float cy);
}

// As above, any level, but the car must stand on a road cell (so a drive can
// start from it), nearest to the given point.
// GTA2DX9_SCENE_MODELS="11,86,7,63" (a developer aid for the camera tests): the
// scene warp takes the nearest driverless vehicle of one of these model numbers
// anywhere in the district, road or not, and logs every one it saw.
bool SceneModelWanted(int32_t model, bool* listed) {
    static int count = -1;
    static int models[16];
    if (count < 0) {
        count = 0;
        char buf[128] = {};
        if (GetEnvironmentVariableA("GTA2DX9_SCENE_MODELS", buf, sizeof buf)) {
            for (char* tok = strtok(buf, ", "); tok && count < 16; tok = strtok(nullptr, ", ")) models[count++] = atoi(tok);
        }
    }
    *listed = count > 0;
    for (int i = 0; i < count; ++i) if (models[i] == model) return true;
    return false;
}

bool NearestParkedTrafficCarOnRoad(float x, float y, float within, float* vx, float* vy, float* distance,
                                   const void** vehicle) {
    bool found = false;
    float best = within;
    int guard = 0;
    bool listed = false;
    SceneModelWanted(-1, &listed);
    if (listed) {
        best = 1e9f;
        std::string seen;
        for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
            int32_t model = -1;
            if (!ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model)) continue;
            bool l = false;
            if (!SceneModelWanted(model, &l)) continue;
            float cx = 0.0f, cy = 0.0f, cz = 0.0f;
            if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
            const bool driver = game::VehicleHasDriver(v);
            char buf[64];
            snprintf(buf, sizeof buf, " m%d@%.1f,%.1f,%.0f%s", model, cx, cy, cz, driver ? "(driven)" : "");
            if (seen.size() < 900) seen += buf;
            if (driver) continue;
            const float d = std::hypot(cx - x, cy - y);
            if (d >= best) continue;
            best = d;
            found = true;
            *vx = cx; *vy = cy; *distance = d;
            if (vehicle) *vehicle = v;
        }
        Log("devtools: scene models seen:%s", seen.empty() ? " none" : seen.c_str());
        return found;
    }
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        if (game::VehicleHasDriver(v)) continue;
        int32_t model = -1;
        if (!ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model)) continue;
        if (model < 0 || model > 86 || model == 3 || model == 6 || model == 22 || model == 54 || model == 55 ||
            (model >= 59 && model <= 61) || model == 65 || model == 66 || (model >= 72 && model <= 81)) continue;
        float cx = 0.0f, cy = 0.0f, cz = 0.0f;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
        const float d = std::hypot(cx - x, cy - y);
        if (d >= best) continue;
        int arrows = 0;
        if (g_devQueries.roadArrows) arrows = g_devQueries.roadArrows(g_devQueries.context, cx, static_cast<float>(gta2::kMapHeight) - cy, cz + 0.95f);
        if (!arrows) continue;
        best = d;
        found = true;
        *vx = cx; *vy = cy; *distance = d;
        if (vehicle) *vehicle = v;
    }
    return found;
}

bool WarpPlayerToParkedCar(float within) {
    PlayerState player;
    if (!LocatePlayer(&player) || !player.valid || player.inVehicle || !player.ped) return false;
    float cx = 0.0f, cy = 0.0f, d = 0.0f;
    bool driven = false;
    const void* car = nullptr;
    if (!NearestVehicle(player.x, player.y, within, true, &cx, &cy, &d, &driven, &car)) return false;
    return WarpPlayerToCarDoor(player, car, cx, cy);
}

namespace {
bool WarpPlayerToCarDoor(const PlayerState& player, const void* car, float cx, float cy) {
    float hx = 0.0f, hy = 1.0f;
    VehicleFacing(car, &hx, &hy);
    // The driver's door is on the car's left: facing (hx, hy) with y south,
    // left is (hy, -hx). A car parked against a wall has its left door in the
    // building: then the other side, where there is a floor to stand on.
    float cz0 = player.z;
    {
        float px = 0.0f, py = 0.0f, pz = 0.0f;
        if (game::ReadPlacement(static_cast<const uint8_t*>(car), game::kVehiclePlacementPtr, &px, &py, &pz)) cz0 = pz;
    }
    float tx = cx + 0.55f * hy;
    float ty = cy - 0.55f * hx;
    if (!WarpFloorMatches(tx, ty, cz0) && WarpFloorMatches(cx - 0.55f * hy, cy + 0.55f * hx, cz0)) {
        tx = cx - 0.55f * hy;
        ty = cy + 0.55f * hx;
    }
    const uintptr_t ped = reinterpret_cast<uintptr_t>(player.ped);
    uintptr_t physics = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    uintptr_t place = 0;
    if (!ReadAt(physics + game::kPhysicsSprite, &place) || !Plausible(place)) return false;
    const int32_t fx = static_cast<int32_t>(tx * (1 << 14));
    const int32_t fy = static_cast<int32_t>(ty * (1 << 14));
    bool ok = WriteAt(place + game::kPlaceX, fx) && WriteAt(place + game::kPlaceY, fy);
    ok = WriteAt(ped + game::kPedX, fx) && WriteAt(ped + game::kPedY, fy) && ok;
    // The car's own level, so the door is not reached from under the road.
    float cz = player.z;
    {
        float px = 0.0f, py = 0.0f, pz = 0.0f;
        if (game::ReadPlacement(static_cast<const uint8_t*>(car), game::kVehiclePlacementPtr, &px, &py, &pz)) cz = pz;
    }
    const int32_t fz = static_cast<int32_t>(cz * (1 << 14));
    ok = WriteAt(place + game::kPlaceZ, fz) && WriteAt(ped + game::kPedZ, fz) && ok;
    if (ok) StartWarpHold(tx, ty, cz, 1.5);
    Log("devtools: warped the player from %.2f,%.2f,%.2f to %.2f,%.2f,%.2f, the driver's door of the parked car at %.2f,%.2f "
        "heading %.2f,%.2f (%s)",
        player.x, player.y, player.z, tx, ty, cz, cx, cy, hx, hy, ok ? "written" : "write failed");
    return ok;
}
}  // namespace

bool WarpSceneToRoad(float x, float y, float z) {
    PlayerState player;
    if (!LocatePlayer(&player) || !player.valid || player.inVehicle || !player.ped) {
        Log("devtools: scene warp ignored (player not located on foot)");
        return false;
    }
    // The spot must have a floor: a point over nothing (the default spot in
    // another district, a terrace that is really a roof) used to leave him in
    // the air or under the map, and the chase view looking up at the city.
    {
        float rx = x, ry = y, rz = z;
        const char* how = "";
        if (!ResolveWarpFloor(x, y, z >= 0.0f ? z : player.z, &rx, &ry, &rz, &how)) {
            Log("devtools: scene warp refused: no road or pavement within six blocks of %.2f,%.2f at level %.0f",
                x, y, z >= 0.0f ? z : player.z);
            return false;
        }
        if (rx != x || ry != y || rz != z) Log("devtools: scene %.2f,%.2f,%.1f resolved to %.2f,%.2f,%.2f (%s)", x, y, z, rx, ry, rz, how);
        x = rx; y = ry; z = rz;
    }
    float cx = 0.0f, cy = 0.0f, d = 0.0f;
    const void* car = nullptr;
    // A car that is moved by writing its placement keeps its old place in the
    // game's own bookkeeping (Residential: a car brought 10 or 22 tiles to the
    // spawn road could not be entered however it was placed, while the same
    // cars were entered at once where they stood), so no car is moved any
    // more: the player goes to the driver's door of the nearest parked
    // traffic car around the scene that stands on a road, at the car's level.
    // GTA2DX9_SCENE_NO_CAR=1 (the city sweep): the scene point itself is what
    // is wanted, never a car; the player is moved alone, as below.
    static int noCar = -1;
    if (noCar < 0) { char buf[8] = {}; noCar = GetEnvironmentVariableA("GTA2DX9_SCENE_NO_CAR", buf, sizeof buf) && buf[0] == '1'; }
    if (!noCar && NearestParkedTrafficCarOnRoad(x, y, 40.0f, &cx, &cy, &d, &car)) {
        const bool ok = WarpPlayerToCarDoor(player, car, cx, cy);
        Log("devtools: scene %.2f,%.2f: the player goes to the parked car at %.2f,%.2f (%.1f tiles from the scene) instead of the car coming%s",
            x, y, cx, cy, d, ok ? "" : " (write failed)");
        return ok;
    }
    const uint8_t* place = nullptr;
    if (!place) {
        // No parked car to bring: move the player alone (objects and views can still be checked there).
        const float tx = x, ty = y;
        const uintptr_t ped = reinterpret_cast<uintptr_t>(player.ped);
        uintptr_t physics = 0, pedPlace = 0;
        bool ok = false;
        if (ReadAt(ped + game::kPedPhysics, &physics) && Plausible(physics) &&
            ReadAt(physics + game::kPhysicsSprite, &pedPlace) && Plausible(pedPlace)) {
            const int32_t fx = static_cast<int32_t>(tx * (1 << 14));
            const int32_t fy = static_cast<int32_t>(ty * (1 << 14));
            ok = WriteAt(pedPlace + game::kPlaceX, fx) && WriteAt(pedPlace + game::kPlaceY, fy) &&
                 WriteAt(ped + game::kPedX, fx) && WriteAt(ped + game::kPedY, fy);
            if (z >= 0.0f) {
                const int32_t fz = static_cast<int32_t>(z * (1 << 14));
                ok = WriteAt(pedPlace + game::kPlaceZ, fz) && WriteAt(ped + game::kPedZ, fz) && ok;
            }
        }
        if (ok) StartWarpHold(tx, ty, z >= 0.0f ? z : player.z, 1.5);
        Log("devtools: no parked car within reach; moved the player alone from %.2f,%.2f to %.2f,%.2f (%s)",
            player.x, player.y, tx, ty, ok ? "written" : "write failed");
        return ok;
    }
    const uintptr_t placeAt = reinterpret_cast<uintptr_t>(place);
    // The car goes on the resolved point, along the road: a car set crosswise
    // on a one-lane road (Residential's spawn road runs north-south) had its
    // ends in the kerbs and the game would not let him in. The road's arrows
    // give the direction; heading 0 is north and a quarter turn (0x5A0 / 4)
    // east, clockwise. The player stands at the driver's door, the car's left
    // (facing (hx, hy) with y south, left is (hy, -hx)), or at the right one
    // when only that side has a floor.
    int arrows = 0;
    if (g_devQueries.roadArrows) arrows = g_devQueries.roadArrows(g_devQueries.context, x, static_cast<float>(gta2::kMapHeight) - y, z + 0.95f);
    const int dir = (arrows & 0x0f) ? (arrows & 0x0f) : ((arrows >> 4) & 0x0f);
    float hx = 1.0f, hy = 0.0f;   // east unless the road says otherwise
    uint16_t heading = static_cast<uint16_t>(game::kAngleFullTurn / 4);
    if (dir & 1) { hx = 0.0f; hy = -1.0f; heading = 0; }
    else if (dir & 2) { hx = 0.0f; hy = 1.0f; heading = static_cast<uint16_t>(game::kAngleFullTurn / 2); }
    else if (dir & 4) { hx = -1.0f; hy = 0.0f; heading = static_cast<uint16_t>(game::kAngleFullTurn * 3 / 4); }
    const float carX = x, carY = y;
    float tx = carX + 0.55f * hy, ty = carY - 0.55f * hx;
    if (!WarpFloorMatches(tx, ty, z) && WarpFloorMatches(carX - 0.55f * hy, carY + 0.55f * hx, z)) {
        tx = carX - 0.55f * hy;
        ty = carY + 0.55f * hx;
    }
    bool ok = WriteAt(placeAt + game::kPlaceX, static_cast<int32_t>(carX * (1 << 14))) &&
              WriteAt(placeAt + game::kPlaceY, static_cast<int32_t>(carY * (1 << 14))) &&
              WriteAt(placeAt + game::kPlaceHeading, heading);
    const uintptr_t ped = reinterpret_cast<uintptr_t>(player.ped);
    uintptr_t physics = 0, pedPlace = 0;
    if (ReadAt(ped + game::kPedPhysics, &physics) && Plausible(physics) &&
        ReadAt(physics + game::kPhysicsSprite, &pedPlace) && Plausible(pedPlace)) {
        const int32_t fx = static_cast<int32_t>(tx * (1 << 14));
        const int32_t fy = static_cast<int32_t>(ty * (1 << 14));
        ok = WriteAt(pedPlace + game::kPlaceX, fx) && WriteAt(pedPlace + game::kPlaceY, fy) &&
             WriteAt(ped + game::kPedX, fx) && WriteAt(ped + game::kPedY, fy) && ok;
        if (z >= 0.0f) {
            const int32_t fz = static_cast<int32_t>(z * (1 << 14));
            ok = WriteAt(pedPlace + game::kPlaceZ, fz) && WriteAt(ped + game::kPedZ, fz) &&
                 WriteAt(placeAt + game::kPlaceZ, fz) && ok;
        }
    } else {
        ok = false;
    }
    if (ok) StartWarpHold(tx, ty, z >= 0.0f ? z : player.z, 1.5);
    Log("devtools: moved the parked car at %.2f,%.2f (%.2f tiles off) to %.2f,%.2f heading %.0f,%.0f (road arrows %d) and the player from "
        "%.2f,%.2f to its door at %.2f,%.2f level %.2f (%s)",
        cx, cy, d, carX, carY, hx, hy, arrows, player.x, player.y, tx, ty, z, ok ? "written" : "write failed");
    return ok;
}

PedWords ReadPedWords(const void* ped) {
    PedWords w;
    const uintptr_t p = reinterpret_cast<uintptr_t>(ped);
    if (!Plausible(p)) return w;
    ReadAt(p + game::kPedState, &w.state);
    ReadAt(p + game::kPedSubState, &w.sub);
    ReadAt(p + game::kPedStatePending, &w.pending);
    ReadAt(p + game::kPedVehicle, &w.vehicle);
    return w;
}

// ---------------------------------------------------------------------------
// Camera-relative controls: the game reads its keyboard through DirectInput's
// GetDeviceState (a 256-byte array indexed by DIK code), so that is where the
// arrows are taken from it and ours are put in. The device's vtable is shared
// by every device the DLL creates, so a keyboard device of our own gives us
// the table to patch; the hook tells a keyboard read by its 256-byte size.
// Nothing is injected into the system: the game sees the array it asked for.
// ---------------------------------------------------------------------------
namespace {
const BYTE kNavDik[4] = {DIK_UP, DIK_DOWN, DIK_LEFT, DIK_RIGHT};
// GUID_SysKeyboard and IID_IDirectInput8A, spelled out so no DirectInput import library is needed.
const GUID kSysKeyboard = {0x6F1D2B61, 0xD5A0, 0x11CF, {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}};
const GUID kIidDirectInput8A = {0xBF798030, 0x483A, 0x4DA2, {0xAA, 0x99, 0x5D, 0x64, 0xED, 0x36, 0x97, 0x00}};
bool g_hookTried = false;
bool g_diHooked = false;
bool g_navActive = false;      // the physical arrows are the controller's while this is set
bool g_phys[4] = {};           // physical Up, Down, Left, Right as the game last read them
bool g_inj[4] = {};            // what the game is told is held down
float g_navCamYaw = 0.0f;      // the camera's yaw last frame (renderer frame)
float g_fpViewYaw = 0.0f;      // first person: the view heading the pedestrian follows
float g_navHeading = 0.0f;     // the player's heading last frame
bool g_navHeadingKnown = false;
bool g_navInVehicle = true;
double g_navLastPoll = 0.0;
double g_navLogClock = 0.0;
float g_navLastHeading = 0.0f;   // for the measured turn rate
bool g_navHaveLast = false;
float g_navRate = 0.0f;          // radians a second, eased
int g_navPulse = 0, g_navCool = 0;
int g_navLogEveryFrame = -1;
long g_diReads = 0;
// Third person: the camera yaw the arrows are read against. Latched when the
// set of arrows held changes (a press or a release) and otherwise moved only
// by an explicit look (the mouse orbit, g_navLookYaw): with the soft follow the
// camera swings round behind him while a key is held, and re-reading the camera
// every frame would turn the wanted heading with it, a circle that chases its
// own tail. Latched, Right walks him straight off to the right of where the
// camera looked, and the camera settles behind him.
float g_navRefYaw = 0.0f;
int g_navLastKeys = -1;
float g_navLookYaw = 0.0f;       // mouse orbit applied by the camera since the controller last ran

typedef HRESULT(WINAPI* GetDeviceStateFn)(IDirectInputDevice8A*, DWORD, LPVOID);
typedef HRESULT(WINAPI* GetDeviceDataFn)(IDirectInputDevice8A*, DWORD, LPDIDEVICEOBJECTDATA, LPDWORD, DWORD);
GetDeviceStateFn g_realGetDeviceState = nullptr;
GetDeviceDataFn g_realGetDeviceData = nullptr;
IDirectInput8A* g_ourDi = nullptr;
IDirectInputDevice8A* g_ourKeyboard = nullptr;
long g_diStateCalls = 0, g_diDataCalls = 0;
bool g_injSeen[4] = {};   // what the game has been told through buffered data so far
// One sequence counter for everything the game reads: DirectInput numbers its
// events, and the game keeps the highest number it has seen and drops anything
// at or below it. An injected event stamped from a private counter (it used
// to start at 0x40000000) therefore made the game ignore every real key after
// it: fire, Enter, Tab. Now every event passing through here, real or ours, is
// renumbered from a counter that first catches up with the real stream, so the
// order the game sees is strictly increasing and the real stream never falls
// below what we handed out.
DWORD g_navSeq = 0;
DWORD g_navLastStamp = 0;

// FIX-KNOCKDOWN: the keys the game is not told of while the player is down (ViewHoldPlayerInput).
const BYTE kHoldDik[] = {DIK_UP, DIK_DOWN, DIK_LEFT, DIK_RIGHT, DIK_LCONTROL, DIK_RCONTROL, DIK_RETURN, DIK_NUMPADENTER, DIK_SPACE};
constexpr int kHoldCount = sizeof(kHoldDik) / sizeof(kHoldDik[0]);
bool g_holdPhys[kHoldCount] = {};   // physically down, as the device last reported
bool g_holdTold[kHoldCount] = {};   // what the game was last told
ULONGLONG g_holdUntil = 0;
bool g_holdLogged = false;
bool InputHeld() { return g_holdUntil && GetTickCount64() < g_holdUntil; }
void EntryNoteKey(DWORD dik, bool down, bool withheld);   // FIX-ENTRY-1, below
void EntryNoteReadFailure(long hr);                         // FIX-ENTRY-1, below
// FIX-AIM-1: the fire key (either Ctrl) as the game is told of it: each press that reaches the game is an attack
// (a punch with fists, a shot or a throw armed); hud3d's swing log reads the count (ViewFirePresses).
bool g_fireToldDown = false;
uint32_t g_firePresses = 0;
void NoteFireTold(bool down) {
    if (down && !g_fireToldDown) ++g_firePresses;
    g_fireToldDown = down;
}
// FIX-AIM-1 aim assist (ViewModeSettings::aimAssist). The pick is hud3d's (ViewSetAimPick, once a frame); the
// press is judged inside the game's keyboard read, so the game never sees a press the assist holds back.
// GTA2's fist (FUN_00444B50) takes its victim from FUN_00433D00: the collision grid's ped OVERLAPPING the puncher's
// own sprite (FUN_00447540, nothing moved ahead, no facing arc), then a distance check. Two peds standing apart do not
// overlap: fixaim1_base1/sweep1 missed 42 of 44 presses from 0.29-0.40 block, facing him to within 4 degrees; the
// owner demo's punches landed while he walked INTO the victim. So a fist press with the person further than
// kAssistFistLand is held while Up walks him in, facing him (bound kAssistFistBound), and Up stays down
// kAssistFistPush s after the press is let go, so the bodies are pressed together on the punch frame.
constexpr float kAssistFistLand = 0.28f;   // drawn centres; the game's bound [0x5E5D64] is 0.25 block (fixaim1_as2 log), two
                                           // bodies pressed together sit 0.25-0.30 apart
constexpr double kAssistFistPush = 0.30;   // the press reaches the game up to a read (~0.12 s) after it is let go
constexpr double kAssistFistContact = 0.066;   // walked into him this long, inside kAssistFistLand, before the press goes
constexpr double kAssistFistBound = 0.7, kAssistGunBound = 0.25;
struct AimPickShared { bool valid = false; bool fists = false; float bearing = 0, tol = 0, dist = 0; uintptr_t object = 0; double at = 0.0; };
AimPickShared g_pick;
enum AssistPhase { kAssistIdle = 0, kAssistAlign, kAssistTrack };
int g_assistPhase = kAssistIdle;
bool g_assistAllowed = false;     // this frame: on foot in a street view, keys not held for a knock-down, hook in
bool g_fireKeyPhys[2] = {};       // left / right Ctrl physically down
bool g_fireWithheld = false;      // a press the game has not been told of yet (turning onto the pick)
bool g_fireTapOwed = false;       // that press already came up: hand the game a short tap when it is let go
// The owed tap, by events (the game reads its buffer one event at a time, ~8 reads a second, and the slot is often
// a real key's: a 90 ms timed tap expired before it was ever delivered, fixaim1_as6): 1 = the down is owed,
// 2 = the down was told, up at g_fireTapUpAt.
int g_fireTap = 0;
ULONGLONG g_fireTapUpAt = 0;
double g_assistT0 = 0.0;
float g_assistErr0 = 0.0f;
uintptr_t g_assistObject = 0;
int g_assistOwn = 0;              // arrows the assist holds (bit i = kNavDik[i]); with nav_map=1 they are the controller's anyway
bool g_pickFists = false;         // the pick is for bare hands: the press also waits until he stands within kAssistFistLand
float g_assistLastHeading = 0.0f, g_assistRate = 0.0f;
bool g_assistHaveLast = false;
int g_assistCool = 0;
int g_assistLogs = 0;
double g_assistPushUntil = 0.0;   // fists: Up held into him until then (after the press is let go)
double g_assistContactSince = 0.0;   // fists: since when he has been walked into him inside kAssistFistLand (0 = not)
bool FirePhys() { return g_fireKeyPhys[0] || g_fireKeyPhys[1]; }
bool PickFresh() { return g_pick.valid && Now() - g_pick.at < 0.15; }
bool AssistLogOn() {
    static int on = -1;
    if (on < 0) { char b[4] = {}; on = GetEnvironmentVariableA("GTA2DX9_LOG_AIM", b, sizeof b) && b[0] == '1'; }
    return on == 1;
}
// A physical change of a fire key, from whichever read saw it first. A press with a pick off his facing is held back.
void NoteFirePhys(int which, bool down) {
    const bool was = FirePhys();
    g_fireKeyPhys[which] = down;
    const bool now = FirePhys();
    if (now && !was) {
        if (g_assistAllowed && !InputHeld() && PickFresh()) {
            const float err = WrapAngle(g_pick.bearing - g_navHeading);
            g_assistObject = g_pick.object;
            g_pickFists = g_pick.fists;
            if (std::fabs(err) > g_pick.tol || g_pick.fists) {
                g_fireWithheld = true;
                g_fireTapOwed = false;
                g_assistPhase = kAssistAlign;
                g_assistT0 = Now();
                g_assistErr0 = err;
                g_assistContactSince = 0.0;
            } else {
                g_assistPhase = kAssistTrack;
                if (AssistLogOn() && g_assistLogs < 400) {
                    ++g_assistLogs;
                    Log("aim: assist press on %04x already on him (%.1f deg off, tolerance %.1f, %.2f blocks): passed at once",
                        static_cast<unsigned>((g_pick.object >> 2) & 0xFFFF), err / kDegToRad, g_pick.tol / kDegToRad, g_pick.dist);
                }
            }
        }
    } else if (!now && was) {
        if (g_fireWithheld) g_fireTapOwed = true;
        if (g_assistPhase == kAssistTrack) g_assistPhase = kAssistIdle;
    }
}
bool FireKeyWanted(int which) {   // what the game should believe of this fire key
    if (g_fireWithheld) return false;
    if (g_fireKeyPhys[which]) return true;
    if (which != 0) return false;
    if (g_fireTap == 1) return true;
    if (g_fireTap == 2) return GetTickCount64() < g_fireTapUpAt;
    return false;
}
bool ArrowOwned(int i) { return g_navActive || (g_assistOwn & (1 << i)) != 0; }
int HoldIndexOfDik(DWORD ofs) {
    for (int i = 0; i < kHoldCount; ++i) if (ofs == kHoldDik[i]) return i;
    return -1;
}

int NavIndexOfDik(DWORD ofs) {
    for (int i = 0; i < 4; ++i) if (ofs == kNavDik[i]) return i;
    return -1;
}

HRESULT WINAPI NavGetDeviceState(IDirectInputDevice8A* self, DWORD cbData, LPVOID data) {
    const HRESULT hr = g_realGetDeviceState(self, cbData, data);
    if (self != g_ourKeyboard) ++g_diStateCalls;
    if (cbData == 256 && data && self != g_ourKeyboard) {
        ++g_diReads;
        BYTE* keys = static_cast<BYTE*>(data);
        for (int i = 0; i < 4; ++i) g_phys[i] = SUCCEEDED(hr) && (keys[kNavDik[i]] & 0x80) != 0;
        for (int i = 0; i < 4; ++i) if (ArrowOwned(i)) keys[kNavDik[i]] = g_inj[i] ? 0x80 : 0;
        // FIX-AIM-1: the fire keys as the assist lets the game see them.
        if (SUCCEEDED(hr)) {
            const bool l = (keys[DIK_LCONTROL] & 0x80) != 0, r = (keys[DIK_RCONTROL] & 0x80) != 0;
            // The physical key from the buffered events when the game reads those (the snapshot can lag them a read
            // and flipped the key up and down: phantom presses, fixaim1_as4); from the snapshot only otherwise.
            if (g_diDataCalls == 0) {
                if (l != g_fireKeyPhys[0]) NoteFirePhys(0, l);
                if (r != g_fireKeyPhys[1]) NoteFirePhys(1, r);
            }
            if (g_diDataCalls == 0 && g_fireTap == 1) { g_fireTap = 2; g_fireTapUpAt = GetTickCount64() + 90; }   // snapshot readers
            if (g_diDataCalls == 0 && g_fireTap == 2 && GetTickCount64() >= g_fireTapUpAt) g_fireTap = 0;
            keys[DIK_LCONTROL] = FireKeyWanted(0) ? 0x80 : 0;
            keys[DIK_RCONTROL] = FireKeyWanted(1) ? 0x80 : 0;
        }
        if (InputHeld()) for (int i = 0; i < kHoldCount; ++i) keys[kHoldDik[i]] = 0;   // FIX-KNOCKDOWN
        if (g_diDataCalls == 0) NoteFireTold((keys[DIK_LCONTROL] & 0x80) != 0 || (keys[DIK_RCONTROL] & 0x80) != 0);   // FIX-AIM-1
    }
    return hr;
}

// Buffered reads: the arrows' events are taken out of the game's buffer and
// the controller's put in (the buffer the game passed has room for what it
// asked for; a peek is left alone).
HRESULT WINAPI NavGetDeviceData(IDirectInputDevice8A* self, DWORD cbObj, LPDIDEVICEOBJECTDATA dod, LPDWORD inOut, DWORD flags) {
    const DWORD capacity = inOut ? *inOut : 0;
    const HRESULT hr = g_realGetDeviceData(self, cbObj, dod, inOut, flags);
    if (self == g_ourKeyboard || !inOut || !dod || cbObj < sizeof(DIDEVICEOBJECTDATA_DX3)) return hr;
    ++g_diDataCalls;
    if (FAILED(hr) && hr != DI_BUFFEROVERFLOW) { EntryNoteReadFailure(static_cast<long>(hr)); return hr; }
    BYTE* base = reinterpret_cast<BYTE*>(dod);
    DWORD n = *inOut, w = 0;
    const bool held = InputHeld();
    for (DWORD r = 0; r < n; ++r) {
        DIDEVICEOBJECTDATA_DX3* e = reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + r * cbObj);
        const int i = NavIndexOfDik(e->dwOfs);
        if (e->dwSequence > g_navSeq) g_navSeq = e->dwSequence;   // catch up with the real stream
        g_navLastStamp = e->dwTimeStamp;
        if (i >= 0) {
            g_phys[i] = (e->dwData & 0x80) != 0;
            ++g_diReads;
            if (ArrowOwned(i)) continue;      // the arrow is ours: the game does not see it
        }
        // FIX-AIM-1: a fire key's event; while the assist holds the press back the game is not told of it.
        if ((e->dwOfs == DIK_LCONTROL || e->dwOfs == DIK_RCONTROL) && !(flags & DIGDD_PEEK)) {
            const int which = e->dwOfs == DIK_LCONTROL ? 0 : 1;
            const bool down = (e->dwData & 0x80) != 0;
            if (down != g_fireKeyPhys[which]) NoteFirePhys(which, down);
            const int hk = HoldIndexOfDik(e->dwOfs);
            if (hk >= 0) g_holdPhys[hk] = down;
            if (g_fireWithheld || (!down && FireKeyWanted(which))) continue;   // told later, by the reconcile below
        }
        // FIX-ENTRY-1: GTA2DX9_LOG_ENTRY=1 logs every Return the game's keyboard reports (EntryService).
        if ((e->dwOfs == DIK_RETURN || e->dwOfs == DIK_NUMPADENTER) && !(flags & DIGDD_PEEK))
            EntryNoteKey(e->dwOfs, (e->dwData & 0x80) != 0, held);
        // FIX-KNOCKDOWN: down on the ground the keys are noted, not passed on.
        const int hk = HoldIndexOfDik(e->dwOfs);
        if (hk >= 0) {
            g_holdPhys[hk] = (e->dwData & 0x80) != 0;
            if (held && !(flags & DIGDD_PEEK)) continue;
            if (!(flags & DIGDD_PEEK)) g_holdTold[hk] = g_holdPhys[hk];
        }
        if (w != r) memmove(base + w * cbObj, e, cbObj);
        if (!(flags & DIGDD_PEEK)) reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + w * cbObj)->dwSequence = ++g_navSeq;
        if (!(flags & DIGDD_PEEK) && (e->dwOfs == DIK_LCONTROL || e->dwOfs == DIK_RCONTROL)) NoteFireTold((e->dwData & 0x80) != 0);   // FIX-AIM-1
        ++w;
    }
    // FIX-AIM-1: an owed fire change goes first. The game reads one event at a time (~8 reads a second), and the
    // assist's own turn and walk events took the slot ahead of it: the press reached the game reads late, after the
    // bodies had drifted apart (fixaim1_rb1).
    if (!(flags & DIGDD_PEEK) && !held) {
        for (int k = 0; k < kHoldCount && w < capacity; ++k) {
            if (kHoldDik[k] != DIK_LCONTROL && kHoldDik[k] != DIK_RCONTROL) continue;
            const bool want = FireKeyWanted(kHoldDik[k] == DIK_LCONTROL ? 0 : 1);
            if (want == g_holdTold[k]) continue;
            DIDEVICEOBJECTDATA_DX3* e = reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + w * cbObj);
            memset(e, 0, cbObj);
            e->dwOfs = kHoldDik[k];
            e->dwData = want ? 0x80 : 0;
            e->dwTimeStamp = g_navLastStamp ? g_navLastStamp : GetTickCount();
            e->dwSequence = ++g_navSeq;
            g_holdTold[k] = want;
            NoteFireTold(want);
            if (want && g_fireTap == 1 && kHoldDik[k] == DIK_LCONTROL) { g_fireTap = 2; g_fireTapUpAt = GetTickCount64() + 90; }
            if (!want && g_fireTap == 2) g_fireTap = 0;
            if (AssistLogOn() && g_assistLogs < 400) { ++g_assistLogs; Log("aim: fire key %s told to the game (first in the read)", want ? "down" : "up"); }
            ++w;
        }
    }
    if (!(flags & DIGDD_PEEK)) {
        for (int i = 0; i < 4 && w < capacity; ++i) {
            if (!ArrowOwned(i) || g_injSeen[i] == g_inj[i]) continue;
            DIDEVICEOBJECTDATA_DX3* e = reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + w * cbObj);
            memset(e, 0, cbObj);
            e->dwOfs = kNavDik[i];
            e->dwData = g_inj[i] ? 0x80 : 0;
            e->dwTimeStamp = g_navLastStamp ? g_navLastStamp : GetTickCount();
            e->dwSequence = ++g_navSeq;
            g_injSeen[i] = g_inj[i];
            ++w;
        }
    }
    // FIX-KNOCKDOWN: as the hold starts the game is told the held keys went up; as it lapses, the ones
    // still down are pressed for it again (the arrows the camera-relative controller owns are its own).
    if (!(flags & DIGDD_PEEK)) {
        for (int k = 0; k < kHoldCount && w < capacity; ++k) {
            if (g_navActive && k < 4) continue;
            const bool fireKey = kHoldDik[k] == DIK_LCONTROL || kHoldDik[k] == DIK_RCONTROL;
            const bool want = held ? false : fireKey ? FireKeyWanted(kHoldDik[k] == DIK_LCONTROL ? 0 : 1) : g_holdPhys[k];
            if (want == g_holdTold[k]) continue;
            DIDEVICEOBJECTDATA_DX3* e = reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + w * cbObj);
            memset(e, 0, cbObj);
            e->dwOfs = kHoldDik[k];
            e->dwData = want ? 0x80 : 0;
            e->dwTimeStamp = g_navLastStamp ? g_navLastStamp : GetTickCount();
            e->dwSequence = ++g_navSeq;
            g_holdTold[k] = want;
            if (fireKey) {   // FIX-AIM-1
                NoteFireTold(want);
                if (want && g_fireTap == 1 && kHoldDik[k] == DIK_LCONTROL) { g_fireTap = 2; g_fireTapUpAt = GetTickCount64() + 90; }
                if (!want && g_fireTap == 2) g_fireTap = 0;
                if (AssistLogOn() && g_assistLogs < 400) { ++g_assistLogs; Log("aim: fire key %s told to the game (buffered read, %lu of %lu slots)", want ? "down" : "up", static_cast<unsigned long>(w + 1), static_cast<unsigned long>(capacity)); }
            }
            ++w;
        }
        // FIX-AIM-1: a fire change owed but no room left in the game's buffer this read (it goes on the next).
        if (w >= capacity && AssistLogOn() && g_assistLogs < 200 && FireKeyWanted(0) != g_holdTold[HoldIndexOfDik(DIK_LCONTROL)]) {
            ++g_assistLogs;
            Log("aim: fire key change owed, the game's buffer is full (%lu slots)", static_cast<unsigned long>(capacity));
        }
    }
    *inOut = w;
    return hr;
}

void InjectKey(int i, bool down) { g_inj[i] = down; }
void ReleaseInjected() { for (int i = 0; i < 4; ++i) g_inj[i] = false; }   // the buffered path sends the releases on the next read

void InstallNavHook(bool) {
    if (g_hookTried) return;
    g_hookTried = true;
    // The game imports DirectInput8Create from dinput8.dll (not dinput.dll:
    // under Wine each is its own module with its own vtables).
    HMODULE dinput = GetModuleHandleA("dinput8.dll");
    if (!dinput) dinput = LoadLibraryA("dinput8.dll");
    typedef HRESULT(WINAPI* CreateFn)(HINSTANCE, DWORD, REFIID, LPVOID*, IUnknown*);
    CreateFn create = dinput ? reinterpret_cast<CreateFn>(GetProcAddress(dinput, "DirectInput8Create")) : nullptr;
    if (!create) {
        Log("nav: dinput8.dll has no DirectInput8Create; the arrows stay the game's");
        return;
    }
    HMODULE self = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCWSTR>(&NavGetDeviceState), &self);
    if (FAILED(create(self, DIRECTINPUT_VERSION, kIidDirectInput8A, reinterpret_cast<LPVOID*>(&g_ourDi), nullptr)) || !g_ourDi ||
        FAILED(g_ourDi->CreateDevice(kSysKeyboard, &g_ourKeyboard, nullptr)) || !g_ourKeyboard) {
        Log("nav: could not create a DirectInput keyboard device; the arrows stay the game's");
        return;
    }
    // The vtable: slot 9 is GetDeviceState.
    void** vtable = *reinterpret_cast<void***>(g_ourKeyboard);
    DWORD old = 0;
    if (!VirtualProtect(&vtable[9], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
        Log("nav: the DirectInput vtable is not writable (%lu); the arrows stay the game's", GetLastError());
        return;
    }
    g_realGetDeviceState = reinterpret_cast<GetDeviceStateFn>(vtable[9]);
    vtable[9] = reinterpret_cast<void*>(&NavGetDeviceState);
    VirtualProtect(&vtable[9], sizeof(void*), old, &old);
    if (VirtualProtect(&vtable[10], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
        g_realGetDeviceData = reinterpret_cast<GetDeviceDataFn>(vtable[10]);
        vtable[10] = reinterpret_cast<void*>(&NavGetDeviceData);
        VirtualProtect(&vtable[10], sizeof(void*), old, &old);
    }
    g_diHooked = true;
    Log("nav: camera-relative controls: DirectInput8 GetDeviceState/GetDeviceData hooked (vtable %p)", static_cast<void*>(vtable));
}

// The controller, once a frame: which of the game's keys to hold so the
// pedestrian walks where the player means, as the camera sees it.
void SteerPlayer(ViewMode mode, float dt) {
    const ViewModeSettings& s = g_settings;
    const bool up = g_phys[0], down = g_phys[1], left = g_phys[2], right = g_phys[3];
    float desired = g_navHeading;
    bool wantMove = false, reverse = false, keepAligned = false;
    if (mode == ViewMode::ThirdPerson) {
        const int keys = (up ? 1 : 0) | (down ? 2 : 0) | (left ? 4 : 0) | (right ? 8 : 0);
        if (keys != g_navLastKeys) {
            g_navRefYaw = g_navCamYaw;
            g_navLastKeys = keys;
        } else {
            g_navRefYaw = WrapAngle(g_navRefYaw + g_navLookYaw);
        }
        g_navLookYaw = 0.0f;
        const float fx = std::sin(g_navRefYaw), fz = std::cos(g_navRefYaw);
        const float rx = std::cos(g_navRefYaw), rz = -std::sin(g_navRefYaw);
        const float f = (up ? 1.0f : 0.0f) - (down ? 1.0f : 0.0f);
        const float r = (right ? 1.0f : 0.0f) - (left ? 1.0f : 0.0f);
        const float vx = fx * f + rx * r, vz = fz * f + rz * r;
        if (std::fabs(vx) + std::fabs(vz) > 1e-3f) {
            desired = std::atan2(vx, vz);
            wantMove = true;
        }
    } else {
        // First person: Left and Right turn the view; the pedestrian follows it.
        // The turn starts gently and winds up (an acceleration ramp, as a pad's
        // stick is eased), and dies away over a few frames on release.
        static float keyRate = 0.0f, keyDir = 0.0f;
        const float dir = (right ? 1.0f : 0.0f) - (left ? 1.0f : 0.0f);
        const float dtc = (std::min)(dt, 1.0f / 30.0f);
        if (dir != 0.0f) {
            if (dir != keyDir) keyRate = 0.0f;
            keyDir = dir;
            const float start = (std::max)(s.fpTurnKeyStart, 1.0f);
            const float cap = (std::max)(s.fpTurnKeyRate, start);
            if (keyRate < start) keyRate = start;
            keyRate = (std::min)(cap, keyRate + (cap - start) / (std::max)(s.fpTurnKeyRamp, 0.01f) * dtc);
        } else {
            keyRate *= std::exp(-dtc / (std::max)(s.fpTurnKeyDecay, 0.01f));
            if (keyRate < 1.0f) keyRate = 0.0f;
        }
        const float turn = keyDir * keyRate * ViewTurnSpeedScale() * kDegToRad * dtc;
        g_fpViewYaw = WrapAngle(g_fpViewYaw + turn);
        desired = g_fpViewYaw;
        wantMove = up;
        reverse = down && !up;
        keepAligned = true;
    }
    const float sign = static_cast<float>(s.navTurnSign < 0 ? -1 : 1);
    const float e = WrapAngle(desired - g_navHeading) * sign;
    // The game turns him at 300-350 degrees a second and our press reaches it
    // a few frames late, so a press held until the error is zero overshoots by
    // half a turn. The controller measures his turn rate, predicts where he
    // will be when a release takes effect, and steers on that: a hold while
    // far off, single-frame pulses with a pause to look when close.
    const float rate = g_navHaveLast ? WrapAngle(g_navHeading - g_navLastHeading) / dt : 0.0f;
    g_navLastHeading = g_navHeading;
    g_navHaveLast = true;
    g_navRate += (rate - g_navRate) * 0.5f;
    const float latency = (std::max)(s.navLatency, 0.0f);
    const float ePred = WrapAngle(desired - (g_navHeading + g_navRate * latency)) * sign;
    const float band = s.navDeadband * kDegToRad;
    const bool turning = wantMove || keepAligned;
    bool pressR = false, pressL = false;
    if (!turning) {
        g_navPulse = 0;
        g_navCool = 0;
    } else if (g_navCool > 0) {
        --g_navCool;
    } else if (std::fabs(ePred) > band) {
        // Held while well off (he winds up to full rate in five frames and the
        // prediction lets go in time); near the target a single frame on and
        // two off, about five degrees a pulse.
        const bool farOff = std::fabs(ePred) > 20.0f * kDegToRad;
        pressR = ePred > 0.0f;
        pressL = !pressR;
        if (!farOff) g_navCool = 2;
    }
    InjectKey(3, pressR);
    InjectKey(2, pressL);
    // Walk once roughly facing the way: he arcs round while still turning,
    // which is how a modern character handles a change of direction.
    InjectKey(0, wantMove && std::fabs(e) < 100.0f * kDegToRad);
    InjectKey(1, reverse);
    const double now = Now();
    if (g_navLogEveryFrame < 0) {
        char buf[8] = {};
        g_navLogEveryFrame = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    if (g_navLogEveryFrame ? (turning || g_inj[0] || g_inj[2] || g_inj[3]) : now - g_navLogClock > 0.5) {
        g_navLogClock = now;
        if (wantMove || keepAligned || g_inj[0] || g_inj[2] || g_inj[3])
            Log("nav: %s keys U%d D%d L%d R%d ref %.0f -> heading %.0f rate %.0f wanted %.0f err %.0f pred %.0f : game U%d D%d L%d R%d (reads %ld, state %ld data %ld)",
                mode == ViewMode::ThirdPerson ? "third" : "first", up, down, left, right, g_navRefYaw / kDegToRad,
                g_navHeading / kDegToRad, g_navRate / kDegToRad, desired / kDegToRad, e / kDegToRad, ePred / kDegToRad,
                g_inj[0], g_inj[1], g_inj[2], g_inj[3], g_diReads, g_diStateCalls, g_diDataCalls);
    }
}

// FIX-AIM-1: the aim assist, once a frame after the camera-relative controller. A held-back press is let go once
// his heading (predicted 0.1 s ahead, as the controller does) is within the pick's tolerance, or after 0.25 s,
// or when the pick is gone; while the key stays down he is kept turned onto the person. The turn is the game's
// own Left/Right, pressed by the same hook (nothing is written into the game).
void AssistSteer(bool allowed, float dt) {
    g_assistAllowed = allowed;
    const float heading = g_navHeading;
    const float rate = g_assistHaveLast && dt > 0.0f ? WrapAngle(heading - g_assistLastHeading) / dt : 0.0f;
    g_assistLastHeading = heading;
    g_assistHaveLast = allowed;
    g_assistRate += (rate - g_assistRate) * 0.5f;
    const bool fresh = PickFresh() && g_pick.object == g_assistObject;
    auto letGo = [&](const char* why) {
        if (g_pickFists) g_assistPushUntil = Now() + kAssistFistPush;
        if (g_fireWithheld) {
            g_fireWithheld = false;
            if (g_fireTapOwed) g_fireTap = 1;   // a tap: down when the game next has room, up ~3 frames after
            g_fireTapOwed = false;
            if (AssistLogOn() && g_assistLogs < 400) {
                ++g_assistLogs;
                Log("aim: assist press on %04x let go after %.2f s: %s (heading %.1f deg off at the press, %.1f now, tolerance %.1f; key %s; reads state %ld data %ld)",
                    static_cast<unsigned>((g_assistObject >> 2) & 0xFFFF), Now() - g_assistT0, why, g_assistErr0 / kDegToRad,
                    g_pick.valid ? WrapAngle(g_pick.bearing - heading) / kDegToRad : 0.0f, g_pick.tol / kDegToRad,
                    FirePhys() ? "still down" : "already up: a tap", g_diStateCalls, g_diDataCalls);
            }
        }
        g_assistPhase = FirePhys() && fresh ? kAssistTrack : kAssistIdle;
    };
    bool walkIn = false;
    if (!allowed) {
        letGo("assist off this frame");
        g_assistPhase = kAssistIdle;
    } else if (g_assistPhase == kAssistAlign) {
        const float ePred = WrapAngle(g_pick.bearing - (heading + g_assistRate * 0.06f));
        const float e = WrapAngle(g_pick.bearing - heading);
        const bool facing = std::fabs(e) <= g_pick.tol && std::fabs(ePred) <= g_pick.tol;
        // Fists: inside kAssistFistLand with Up held into him for kAssistFistContact (the bodies pressed together).
        if (g_pickFists && g_pick.dist <= kAssistFistLand) { if (g_assistContactSince <= 0.0) g_assistContactSince = Now(); }
        else g_assistContactSince = 0.0;
        const bool close = !g_pickFists || (g_assistContactSince > 0.0 && Now() - g_assistContactSince >= kAssistFistContact);
        if (!fresh) letGo("the person left the pick");
        else if (facing && close) letGo(g_pickFists ? "on him, within reach" : "on him");
        else if (Now() - g_assistT0 > (g_pickFists ? kAssistFistBound : kAssistGunBound)) letGo(g_pickFists ? "0.7 s bound" : "0.25 s bound");
        else walkIn = std::fabs(e) < 35.0f * kDegToRad;   // fists: Up into him until the press goes
    } else if (g_assistPhase == kAssistTrack) {
        if (!FirePhys() || !fresh) g_assistPhase = kAssistIdle;
    }
    // The turn: the controller's rule (held while far off, one-frame pulses near), on a tighter band.
    const bool pushIn = g_pickFists && Now() < g_assistPushUntil;
    const bool turning = allowed && (g_assistPhase != kAssistIdle || pushIn) && fresh;
    // Up is the assist's while it walks him in, and for kAssistFistPush after the press goes to the game.
    const bool lunge = turning && g_pickFists && (g_assistPhase == kAssistAlign || pushIn);
    if (pushIn && g_assistPhase != kAssistAlign) walkIn = std::fabs(WrapAngle(g_pick.bearing - heading)) < 35.0f * kDegToRad;
    if (turning) {
        const int want = 4 | 8 | (lunge ? 1 : 0);
        if (!g_navActive)
            for (int i = 0; i < 4; ++i)
                if ((want & (1 << i)) && !(g_assistOwn & (1 << i))) g_injSeen[i] = g_phys[i];   // what the game was told
        if (!lunge && (g_assistOwn & 1) && !g_navActive) {
            InjectKey(0, g_phys[0]);   // hand Up back
            if (g_injSeen[0] == g_phys[0]) g_assistOwn &= ~1;
        }
        g_assistOwn |= want & ~(lunge ? 0 : 1);
        if (lunge) InjectKey(0, walkIn);
        const float sign = static_cast<float>(g_settings.navTurnSign < 0 ? -1 : 1);
        const float latency = (std::max)(g_settings.navLatency, 0.0f);
        const float ePred = WrapAngle(g_pick.bearing - (heading + g_assistRate * latency)) * sign;
        const float band = (std::max)(0.6f * g_pick.tol, 2.5f * kDegToRad);
        bool pressR = false, pressL = false;
        // (Steering kept up inside 0.3 block: frozen there, he walked past a body that slid aside, fixaim1_as3.)
        if (g_assistCool > 0) --g_assistCool;
        else if (std::fabs(ePred) > band) {
            pressR = ePred > 0.0f;
            pressL = !pressR;
            // Pulses near the mark for a gun; walking in with fists the turn is held (pulses lost him at 0.7 s, as2).
            if (std::fabs(ePred) <= 20.0f * kDegToRad && !lunge) g_assistCool = 2;
        }
        InjectKey(3, pressR);
        InjectKey(2, pressL);
    } else if (g_assistOwn) {
        // Hand the arrows back: the game is told the physical state first (nav_map=0), then they pass through again.
        g_assistCool = 0;
        if (g_navActive) g_assistOwn = 0;
        else {
            for (int i = 0; i < 4; ++i) {
                if (!(g_assistOwn & (1 << i))) continue;
                InjectKey(i, g_phys[i]);
                if (g_injSeen[i] == g_phys[i]) g_assistOwn &= ~(1 << i);
            }
        }
    }
}

// ---- FIX-ENTRY-1: the game's own entry, traced and on a developer key ----------------------
// How GTA2 9.6 decides an Enter (read off gta2.exe, 10 Nov): the player object is [[0x5EB4FC]+0x38]
// (its ped at +0x2C4; +0x7D the enter control held, +0x89 changed this frame; +0x2F set skips the
// handler). FUN_004A76D0 runs on the press: in a car he gets out (objective 0x24); on foot it asks
// FUN_00424E70 for a car, which moves the ped's own sprite a fixed distance (the word at 0x5E4F38,
// 16.14) AHEAD along his heading, asks the collision grid (FUN_00447540) what overlaps it there and
// takes that car - driven or parked, the game does not care (a driven one is a jack). No overlap: no
// car, nothing happens, the ped stays in state 7/0xE (the ordinary on-foot state). With a car it sets
// objective 0x23 (0x25, a passenger, for models 59..61) through FUN_0043BBC0, the target car at +0x150,
// +0x248 = 0, byte +0x24C = 0; the objective then walks him to the door (state 3/4) and boards.
// So a Return beside a car but facing along it (the 5090 filing: face 0,-1 between two cars heading
// 0,-1) finds nothing. GTA2DX9_LOG_ENTRY=1 logs every Return the game's keyboard reports and what the
// game made of it; [devtools] enter_key runs the handler's own steps on the nearest parked car.
constexpr uintptr_t kEntryPlayerSlot = 0x38;
constexpr uintptr_t kEntryPlayerPed = 0x2C4;
constexpr uintptr_t kEntryProbeDistance = 0x005E4F38;
constexpr uintptr_t kPedObjective = 0x258;
constexpr uintptr_t kPedObjectiveCar = 0x150;
constexpr int kObjectiveEnterAsDriver = 0x23;
constexpr int kObjectiveEnterAsPassenger = 0x25;
int g_entryLog = -1;
int g_entryWatch = 0;         // frames left watching the objective after a press
int32_t g_entryObjective0 = 0, g_entryState0 = 0;
bool EntryLogOn() {
    if (g_entryLog < 0) { char b[8] = {}; g_entryLog = GetEnvironmentVariableA("GTA2DX9_LOG_ENTRY", b, sizeof b) && atoi(b) ? 1 : 0; }
    return g_entryLog == 1;
}
ULONGLONG g_entryDiDownTick = 0;   // when the game's keyboard last reported a Return down
long g_entryReadFailures = 0;
void EntryNoteReadFailure(long hr) {
    ++g_entryReadFailures;
    if (EntryLogOn() && (g_entryReadFailures <= 5 || (g_entryReadFailures % 300) == 0))
        Log("entry: the game's keyboard read failed (hr %08lX, %ld so far): no key reaches the game while this lasts",
            static_cast<unsigned long>(hr), g_entryReadFailures);
}
void EntryLogSnapshot(const char* why, const PlayerState& p);
void EntryNoteKey(DWORD dik, bool down, bool withheld) {
    if (down) g_entryDiDownTick = GetTickCount64();
    if (!EntryLogOn()) return;
    Log("entry: %s %s %s the game's keyboard", dik == DIK_RETURN ? "Return" : "keypad Enter", down ? "down" : "up",
        withheld ? "withheld from (knock-down hold)" : "reached");
    if (!down || withheld) return;
    // Inside the game's own keyboard read, so before its handler runs this frame: the state it will judge.
    PlayerState p;
    if (LocatePlayer(&p) && p.valid && p.ped) {
        EntryLogSnapshot(p.inVehicle ? "Return in a car (before the game's handler)" : "Return on foot (before the game's handler)", p);
        const uintptr_t ped = reinterpret_cast<uintptr_t>(p.ped);
        ReadAt(ped + kPedObjective, &g_entryObjective0); ReadAt(ped + game::kPedState, &g_entryState0);
        g_entryWatch = 45;
    }
}
uintptr_t EntryPlayerObject() {
    uintptr_t root = 0, player = 0;
    if (!ReadAt(kPlayerObjectPtr, &root) || !Plausible(root)) return 0;
    if (!ReadAt(root + kEntryPlayerSlot, &player) || !Plausible(player)) return 0;
    return player;
}
bool OrdinaryCarModel(int32_t model) {
    return !(model < 0 || model > 86 || model == 3 || model == 6 || model == 22 || model == 54 || model == 55 ||
             (model >= 59 && model <= 61) || model == 65 || model == 66 || (model >= 72 && model <= 81));
}
// What the game will find ahead of him: every car within 2.5 tiles, with the probe point in its frame.
void EntryLogSnapshot(const char* why, const PlayerState& p) {
    const uintptr_t ped = reinterpret_cast<uintptr_t>(p.ped);
    int32_t probeRaw = 0, objective = -1, state = -1, sub = -1;
    uintptr_t target = 0, veh = 0, player = EntryPlayerObject();
    uint8_t locked = 0xFF, held = 0xFF;
    ReadAt(kEntryProbeDistance, &probeRaw);
    ReadAt(ped + kPedObjective, &objective); ReadAt(ped + kPedObjectiveCar, &target);
    ReadAt(ped + game::kPedState, &state); ReadAt(ped + game::kPedSubState, &sub); ReadAt(ped + game::kPedVehicle, &veh);
    if (player) { ReadAt(player + 0x2F, &locked); ReadAt(player + 0x7D, &held); }
    const float reach = probeRaw / 16384.0f;
    // the sprite's own heading, the one FUN_00424E70 turns into the probe (FUN_0041FC20)
    float fx = p.dirX, fy = p.dirY;
    uintptr_t physics = 0;
    const bool spriteFacing = ReadAt(ped + game::kPedPhysics, &physics) && Plausible(physics) &&
                              game::ReadFacing(reinterpret_cast<const uint8_t*>(physics), game::kPhysicsSprite, &fx, &fy);
    const float qx = p.x + fx * reach, qy = p.y + fy * reach;
    std::string cars;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
        float cx = 0, cy = 0, cz = 0, hx = 0, hy = 1;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
        if (std::hypot(cx - p.x, cy - p.y) > 2.5f || std::fabs(cz - p.z) > 1.0f) continue;
        VehicleFacing(v, &hx, &hy);
        int32_t model = -1;
        ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model);
        // the probe in the car's frame: along its heading, and across (+ = its right)
        const float dx = qx - cx, dy = qy - cy;
        char b[200];
        snprintf(b, sizeof b, " [m%d %p at %.2f,%.2f head %.2f,%.2f %s d=%.2f probe along=%.2f across=%.2f]", model, static_cast<const void*>(v),
                 cx, cy, hx, hy, game::VehicleHasDriver(v) ? "driven" : "parked", std::hypot(cx - p.x, cy - p.y),
                 dx * hx + dy * hy, dx * -hy + dy * hx);
        if (cars.size() < 1400) cars += b;
    }
    Log("entry: %s: player %.2f,%.2f,%.2f face %.3f,%.3f (sprite heading %.3f,%.3f%s) state=%d sub=%d veh=%08X objective=%d target=%08X | player object %08X "
        "locked=%d enter_held=%d | probe %.3f ahead -> %.2f,%.2f | cars within 2.5:%s",
        why, p.x, p.y, p.z, p.dirX, p.dirY, fx, fy, spriteFacing ? "" : ", unreadable", state, sub, static_cast<unsigned>(veh), objective, static_cast<unsigned>(target),
        static_cast<unsigned>(player), locked, held, reach, qx, qy, cars.empty() ? " none" : cars.c_str());
}

// [devtools] enter_key: the steps of the game's own handler (FUN_004A76D0 after the car search), on the
// nearest driverless ordinary car on his level within 8 tiles, whichever way he faces and whatever
// traffic stands nearer. The objective walks him to its door and boards him as a Return would: the
// vehicle pointer, the ped's state and the driver are the game's, so a Return afterwards gets him out.
// Runs on the game thread (the renderer's frame), as the game's own handler does.
void EnterNearestParkedCar() {
    PlayerState p;
    if (!LocatePlayer(&p) || !p.valid || !p.ped) { Log("devtools: enter_key ignored (player not located)"); return; }
    if (p.inVehicle) { Log("devtools: enter_key ignored (he is in a car: Return gets him out)"); return; }
    const uintptr_t ped = reinterpret_cast<uintptr_t>(p.ped);
    int32_t state = -1, objective = -1;
    ReadAt(ped + game::kPedState, &state); ReadAt(ped + kPedObjective, &objective);
    if (state == 3 || state == 4 || state == 8 || state == 9 || state == 10) {
        Log("devtools: enter_key ignored (ped state %d: boarding, leaving, down, dead or seated)", state);
        return;
    }
    const uint8_t* best = nullptr;
    float bestD = 8.0f, bx = 0, by = 0;
    int32_t bestModel = -1;
    int guard = 0;
    for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
        if (game::VehicleHasDriver(v)) continue;
        int32_t model = -1;
        if (!ReadAt(reinterpret_cast<uintptr_t>(v) + game::kVehicleModel, &model) || !OrdinaryCarModel(model)) continue;
        float cx = 0, cy = 0, cz = 0;
        if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz)) continue;
        if (std::fabs(cz - p.z) > 0.6f) continue;
        const float d = std::hypot(cx - p.x, cy - p.y);
        if (d >= bestD) continue;
        best = v; bestD = d; bx = cx; by = cy; bestModel = model;
    }
    if (!best) { Log("devtools: enter_key: no driverless car on his level within 8 tiles of %.2f,%.2f", p.x, p.y); return; }
    if (EntryLogOn()) EntryLogSnapshot("enter_key", p);
    typedef void(__attribute__((thiscall)) * ClearFn)(void* ped, int a, int b);          // FUN_00436920
    typedef void(__attribute__((thiscall)) * ObjectiveFn)(void* ped, int objective, int timer);   // FUN_0043BBC0
    void* pedMut = const_cast<void*>(p.ped);
    reinterpret_cast<ClearFn>(0x00436920)(pedMut, 0, 9999);
    reinterpret_cast<ObjectiveFn>(0x0043BBC0)(pedMut, kObjectiveEnterAsDriver, 9999);
    WriteAt(ped + kPedObjectiveCar, reinterpret_cast<uintptr_t>(best));   // FUN_00403AA0
    WriteAt(ped + 0x248, static_cast<int32_t>(0));                        // FUN_004039B0(0)
    WriteAt(ped + 0x24C, static_cast<uint8_t>(0));                        // FUN_00403A70(0)
    int32_t after = -1;
    ReadAt(ped + game::kPedState, &after);
    Log("devtools: enter_key: the game's entry objective %d on the parked car m%d %p at %.2f,%.2f (%.2f tiles) for the player at "
        "%.2f,%.2f (state %d -> %d, objective was %d)",
        kObjectiveEnterAsDriver, bestModel, static_cast<const void*>(best), bx, by, bestD, p.x, p.y, state, after, objective);
    g_entryWatch = EntryLogOn() ? 90 : 0;
    g_entryObjective0 = objective; g_entryState0 = state;
}

// Once a frame from the key poll: trace a Return the game was told of (what the game made of it).
void EntryService() {
    if (!EntryLogOn()) return;
    InstallNavHook(false);   // the hook is otherwise installed only for the camera-relative arrows or a knock-down
    // Windows saw a Return (any window of this process in front) but the game's keyboard reported none within
    // half a second: the key never reached the game (its DirectInput device, the focus), not a game rule.
    {
        static bool osWas = false;
        static int pendingFrames = 0;
        static ULONGLONG edgeTick = 0;
        const bool osDown = (GetAsyncKeyState(VK_RETURN) & 0x8000) != 0;
        if (osDown && !osWas) { pendingFrames = 15; edgeTick = GetTickCount64(); }
        osWas = osDown;
        // the game's read may come before this poll sees the edge, or after it: either within half a second
        if (pendingFrames > 0 && --pendingFrames == 0 && !(g_entryDiDownTick + 500 >= edgeTick && g_entryDiDownTick <= edgeTick + 1500)) {
            HWND fg = GetForegroundWindow();
            DWORD pid = 0;
            if (fg) GetWindowThreadProcessId(fg, &pid);
            Log("entry: Windows reported Return down but the game's keyboard did not within 15 frames (foreground %p, %s; "
                "keyboard reads %ld, failed %ld): the key is not reaching the game",
                static_cast<void*>(fg), pid == GetCurrentProcessId() ? "this process" : "another process", g_diDataCalls,
                g_entryReadFailures);
        }
    }
    PlayerState p;
    const bool have = LocatePlayer(&p) && p.valid && p.ped;
    if (g_entryWatch <= 0 || !have) return;
    const uintptr_t ped = reinterpret_cast<uintptr_t>(p.ped);
    int32_t objective = -1, state = -1, sub = -1;
    uintptr_t target = 0, veh = 0;
    ReadAt(ped + kPedObjective, &objective); ReadAt(ped + game::kPedState, &state); ReadAt(ped + game::kPedSubState, &sub);
    ReadAt(ped + kPedObjectiveCar, &target); ReadAt(ped + game::kPedVehicle, &veh);
    if (objective != g_entryObjective0 || state != g_entryState0 || p.inVehicle) {
        Log("entry: the game acted: objective %d -> %d, state %d -> %d sub %d, target car %08X, veh %08X%s", g_entryObjective0, objective,
            g_entryState0, state, sub, static_cast<unsigned>(target), static_cast<unsigned>(veh), p.inVehicle ? " (in the car)" : "");
        g_entryObjective0 = objective; g_entryState0 = state;
        if (p.inVehicle) { g_entryWatch = 0; return; }
    }
    if (--g_entryWatch == 0)
        Log("entry: watch ended: objective %d state %d sub %d veh %08X %s", objective, state, sub, static_cast<unsigned>(veh),
            p.inVehicle ? "in a car" : "on foot");
}
}  // namespace

uint32_t ViewFirePresses() { return g_firePresses; }   // FIX-AIM-1
bool ViewFireDown() { return g_fireToldDown; }          // FIX-AIM-1
void ViewSetAimPick(bool valid, bool fists, float bearingYaw, float tolRad, float dist, uintptr_t object) {   // FIX-AIM-1
    g_pick.valid = valid;
    if (!valid) return;
    g_pick.fists = fists; g_pick.bearing = bearingYaw; g_pick.tol = tolRad; g_pick.dist = dist; g_pick.object = object; g_pick.at = Now();
    // Held, or a fist press walking him in: follow the pick when it moves to another person.
    if (object != g_assistObject && (g_assistPhase == kAssistTrack || (g_assistPhase == kAssistAlign && fists))) g_assistObject = object;
}
bool ViewAimAssistOn() {   // FIX-AIM-1: aim_assist=1 and not GTA2DX9_AIM_ASSIST=0
    static int env = -1;
    if (env < 0) { char b[4] = {}; env = GetEnvironmentVariableA("GTA2DX9_AIM_ASSIST", b, sizeof b) && b[0] == '0' ? 0 : 1; }
    return env == 1 && g_settings.aimAssist;
}
bool ViewAimCoverWallsOn() {   // FIX-AIM-2
    static int env = -1;
    if (env < 0) { char b[4] = {}; env = GetEnvironmentVariableA("GTA2DX9_AIM_COVER_WALLS", b, sizeof b) && b[0] == '0' ? 0 : 1; }
    return env == 1 && g_settings.aimCoverWalls;
}

// FIX-COCKPIT-CAB-4: the steering keys the game is told are held (view_modes.h).
int GameSteerKeys() {   // FIX-COCKPIT-CAB-4
    if (InputHeld()) return 0;
    bool l = g_navActive ? g_inj[2] : g_phys[2], r = g_navActive ? g_inj[3] : g_phys[3];
    if (!g_diHooked) {   // no hook (direct arrows, not knocked down yet): the game reads the physical arrows
        l = (GetAsyncKeyState(VK_LEFT) & 0x8000) != 0;
        r = (GetAsyncKeyState(VK_RIGHT) & 0x8000) != 0;
    }
    return l == r ? 0 : (l ? -1 : 1);
}

void ViewHoldPlayerInput() {
    if (CurrentViewMode() == ViewMode::Classic) return;
    InstallNavHook(false);
    // FIX-KNOCKDOWN-2 (kd2_r2): the hook is installed lazily, at the first knock-down; a key already down before it
    // (the arrow he was walking on) was never seen, so it counted as "told up": no release was sent as the hold began,
    // its real release was swallowed, and the game walked him on 3 blocks while his body lay. As a hold begins, every
    // held key counts as down in the game, so the next buffered read tells it each went up (a no-op for a key that was up).
    static const bool kd2 = [] { char b[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_KD_HOLD_RELEASE", b, sizeof b) && b[0] == '0'); }();
    if (kd2 && !InputHeld())
        for (int k = 0; k < kHoldCount; ++k) g_holdTold[k] = true;
    g_holdUntil = GetTickCount64() + 300;   // a frame or two without a renewal (a hitch) is not a release
}

ViewModeSettings& ViewModes() { return g_settings; }
ViewLook& LookOffsets() { return g_look; }
float CameraTurnBudgetDeg() {
    static float env = -2.0f;
    if (env < -1.0f) { char b[16] = {}; env = GetEnvironmentVariableA("GTA2DX9_CAM_TURN_BUDGET", b, sizeof b) ? static_cast<float>(atof(b)) : -1.0f; }
    const float v = env >= 0.0f ? env : ViewModes().turnBudget;
    return v > 0.0f ? (std::max)(1.0f, v) : 0.0f;
}

bool CameraPocketLiftOn() {
    static int env = -2;
    if (env < -1) { char b[8] = {}; env = GetEnvironmentVariableA("GTA2DX9_CAM_POCKET_LIFT", b, sizeof b) ? atoi(b) : -1; }
    return env >= 0 ? env != 0 : ViewModes().pocketLift;
}

bool CameraPedFadeOn() {
    static int env = -2;
    if (env < -1) { char b[8] = {}; env = GetEnvironmentVariableA("GTA2DX9_CAM_PED_FADE", b, sizeof b) ? atoi(b) : -1; }
    return env >= 0 ? env != 0 : ViewModes().chasePedFade;
}

ViewMode CurrentViewMode() {
    const int m = g_settings.mode;
    return static_cast<ViewMode>(m < 0 || m >= kViewModeCount ? 0 : m);
}

void SetViewMode(ViewMode mode) {
    const int m = static_cast<int>(mode);
    if (m == g_settings.mode) return;
    g_settings.mode = m;
    g_look = ViewLook{};
    Log("view: %s", ViewModeName(mode));
}

void CycleViewMode() {
    SetViewMode(static_cast<ViewMode>((static_cast<int>(CurrentViewMode()) + 1) % kViewModeCount));
}

const char* ViewModeName(ViewMode mode) {
    switch (mode) {
        case ViewMode::ThirdPerson: return "Third person";
        case ViewMode::FirstPerson: return "First person";
        default: return "Classic (top down)";
    }
}

const char* KeyName(int vk) {
    static char buffer[32];
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) {
        buffer[0] = static_cast<char>(vk);
        buffer[1] = '\0';
        return buffer;
    }
    if (vk >= VK_F1 && vk <= VK_F24) {
        snprintf(buffer, sizeof(buffer), "F%d", vk - VK_F1 + 1);
        return buffer;
    }
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD9) {
        snprintf(buffer, sizeof(buffer), "Num %d", vk - VK_NUMPAD0);
        return buffer;
    }
    switch (vk) {
        case VK_HOME: return "Home";
        case VK_END: return "End";
        case VK_INSERT: return "Insert";
        case VK_DELETE: return "Delete";
        case VK_PRIOR: return "Page Up";
        case VK_NEXT: return "Page Down";
        case VK_TAB: return "Tab";
        case VK_CAPITAL: return "Caps Lock";
        case VK_OEM_3: return "` (grave)";
        case VK_MBUTTON: return "Middle mouse";
        case VK_XBUTTON1: return "Mouse 4";
        case VK_XBUTTON2: return "Mouse 5";
        default:
            snprintf(buffer, sizeof(buffer), "key 0x%02X", vk);
            return buffer;
    }
}

void NotePedNearCamera(const void* ped, float distanceTiles) {
    if (!ped) return;
    if (distanceTiles < g_nearPedNowDist) {
        g_nearPedNowDist = distanceTiles;
        g_nearPedNow = ped;
    }
}

// The player's ped as LocatePlayer last found it (on foot, or the one still at the wheel
// of the car he drove off in); null in the menus. For the devtools that write his ped
// (live_geometry.cpp force_wanted) in any view, the classic one included.
// FIX-STABILITY-2 (owner-5090-minimize-fatal, the V-move stall at move 0.524 on the 5090): the ped this
// file keeps can outlive its memory (0x4849D5B0 through a V move: 168 guarded faults in ActionProbes and a
// minute-long stall). Asked of the page table itself, not of KnownReadable's cache, which keeps a region
// it once found readable.
bool PedPagesCommitted(uintptr_t ped) {
    if (!ped) return false;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(reinterpret_cast<const void*>(ped), &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    return ped + 0x280 <= reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
}

const void* GamePlayerPed() {
    const uintptr_t player = EntryPlayerObject();
    uintptr_t ped = 0;
    if (!player || !ReadAt(player + kEntryPlayerPed, &ped) || !PedStillLinked(ped)) return nullptr;
    return reinterpret_cast<const void*>(ped);
}

const void* LocatedPlayerPed() {
    const uintptr_t ped = g_lastPlayerPed;
    return PedPagesCommitted(ped) ? reinterpret_cast<const void*>(ped) : nullptr;
}

bool LocatePlayer(PlayerState* out) {
    *out = PlayerState{};

    // The sprite pass's note is for the frame it was drawn in, which is the one
    // ending now. Hand it over and start the next.
    g_nearPed = g_nearPedNow;
    g_nearPedDist = g_nearPedNowDist;
    g_nearPedNow = nullptr;
    g_nearPedNowDist = 1e9f;

    const uint8_t* camera = game::CameraStruct();
    if (!game::MapObject() || !camera) {
        g_slot = Slot::None;
        g_slotLogged = false;
        g_lastPlayerPed = 0;
        return false;
    }

    if (g_lastPlayerPed && !PedPagesCommitted(g_lastPlayerPed)) {
        static int logged = 0;
        if (logged++ < 20)
            Log("view: the player's last ped %08X is no longer mapped memory: dropped", static_cast<unsigned>(g_lastPlayerPed));
        g_lastPlayerPed = 0;
        g_lastPlayerPedId = 0;
        g_readableCount = 0;   // the readable-region cache may hold the region it was in
    }
    uintptr_t ped = RememberedPed();
    if (ped) {
        out->source = g_slot == Slot::Camera ? "camera" : "player object";
    } else {
        static int lost = 0;
        if (g_slot != Slot::None && lost++ < 20) {
            Log("view: the remembered player slot (%s +0x%02X) no longer holds a pedestrian; looking again",
                g_slot == Slot::Camera ? "camera" : "player object", static_cast<unsigned>(g_slotOffset));
        }
        if (g_slot != Slot::None) g_scanCooldown = 0;   // he was there a moment ago: look now
    }
    // The slot lost him as he got into a car: the car names him as its driver.
    // His physics object and sprite are recycled by the game while he sits in
    // it, so neither is read then.
    bool atTheWheel = false;
    if (!ped && g_lastPlayerPed && VehicleDrivenBy(g_lastPlayerPed)) {
        static int idCheck = -1;
        if (idCheck < 0) { char b[8] = {}; idCheck = GetEnvironmentVariableA("GTA2DX9_PLAYER_ID_CHECK", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        uint32_t id = 0;
        if (idCheck && g_lastPlayerPedId && ReadAt(g_lastPlayerPed + kPedIdWord, &id) && id != g_lastPlayerPedId) {
            static int logged = 0;
            int32_t occupation = -1;
            ReadAt(g_lastPlayerPed + 0x240, &occupation);
            if (logged++ < 20)
                Log("view: the player's last ped struct now holds ped %u (occupation %d), not him (%u): not followed at the wheel",
                    id, occupation, g_lastPlayerPedId);
            g_lastPlayerPed = 0;
            g_lastPlayerPedId = 0;
        } else {
            ped = g_lastPlayerPed;
            atTheWheel = true;
            out->source = "driver of a car";
        }
    }
    if (!ped && --g_scanCooldown <= 0) {
        g_scanCooldown = kScanEveryFrames;
        ped = ScanForPlayer();
        if (ped) {
            out->source = g_slot == Slot::Camera ? "camera" : "player object";
            if (!g_slotLogged) {
                g_slotLogged = true;
                Log("view: player pedestrian found through the %s at +0x%02X: ped %08X (user space ends %08X)",
                    g_slot == Slot::Camera ? "camera struct" : "player object",
                    static_cast<unsigned>(g_slotOffset), static_cast<unsigned>(ped),
                    static_cast<unsigned>(game::UserSpaceEnd()));
            }
        }
    }

    // FIX-FIGURE-17 (owner10nov B4: "out of a police cruiser, V, and the hero became a random NPC"): the slots above
    // are a pointer found once in the camera struct (or the player-object block) and read there since. An arrest or
    // a death plays on a NEW ped struct (game id 0, his sprite and outfit) while his own goes to the station or the
    // hospital: the camera's slot names that body through the beat. When the beat is over the slot loses it, the
    // scan finds the same body again, now an ordinary pedestrian with a crowd id walking away, and the views followed
    // that stranger until the next warp (run fig17_bu2: BUSTED 19:30:40.9, located ped id 89 at 127..131,111 for
    // 15 s, his own ped at the station dealt a crowd avatar). The game's own player object names his ped
    // ([[0x5EB4FC]+0x38]+0x2C4, the one the keys drive): when it is a pedestrian and differs from the slot's, it wins,
    // except while a beat plays or the slot's ped is the beat's body (game id 0): the beat follows the game's camera.
    // Never at the wheel (the car is followed). GTA2DX9_PLAYER_GAME_PED=0 keeps the slots alone (A/B).
    if (!atTheWheel && !BeatActive()) {
        static int gameFirst = -1;
        if (gameFirst < 0) { char b[8] = {}; gameFirst = GetEnvironmentVariableA("GTA2DX9_PLAYER_GAME_PED", b, sizeof b) && b[0] == '0' ? 0 : 1; }
        const uintptr_t gamePed = gameFirst ? reinterpret_cast<uintptr_t>(GamePlayerPed()) : 0;
        uint32_t id = 1;
        if (gamePed && gamePed != ped && PedSignature(gamePed) && !(ped && ReadAt(ped + kPedIdWord, &id) && id == 0)) {
            static int logs = 0;
            static uintptr_t lastPair[2] = {0, 0};
            uint32_t gid = 0;
            ReadAt(gamePed + kPedIdWord, &gid);
            const bool newPair = lastPair[0] != ped || lastPair[1] != gamePed;
            lastPair[0] = ped; lastPair[1] = gamePed;
            if (newPair && logs++ < 60)
                Log("view: the %s named ped %08X (id %u), the game's player object names %08X (id %u): his is followed",
                    ped ? out->source : "slots", static_cast<unsigned>(ped), ped ? id : 0u, static_cast<unsigned>(gamePed), gid);
            ped = gamePed;
            out->source = "the game's player object";
        }
    }
    if (!ped && !(g_rideTrain && RideTrainOn())) {   // FIX-CAMERA-16: riding a train, no passer-by at the camera is him
        float camX = 0.0f, camY = 0.0f;
        game::CameraPosition(&camX, &camY);
        if (g_nearPed && g_nearPedDist < 1.0f && PedSignature(reinterpret_cast<uintptr_t>(g_nearPed))) {
            ped = reinterpret_cast<uintptr_t>(g_nearPed);
            out->source = "pedestrian at the camera";
        } else if (uintptr_t car = DrivenCarAtCamera(camX, camY)) {
            uintptr_t driver = 0;
            if (ReadAt(car + game::kVehicleDriver, &driver) && PedStillLinked(driver)) {
                ped = driver;
                out->source = "driven car at the camera";
            }
        }
    }
    if (!ped && RideTrainOn()) {
        // FIX-CAMERA-16: lost beside a train the game's camera now rides (or already riding it): he is its rider. The
        // train is the vehicle to follow, as a car he drives (its placement, facing and sprite); no ped.
        float camX = 0.0f, camY = 0.0f, d = 9.0f;
        game::CameraPosition(&camX, &camY);
        // Riding: the boarded carriage while it is a live train within 18 blocks of the game's camera (which leads a
        // train at 8 b/s by ~10 and zooms out: runs cam16_tr1 at 3, cam16_tr4 at 8 lost it); never another carriage.
        float rd = 99.0f;
        const bool keep = g_rideTrain && TrainStillLive(g_rideTrain, camX, camY, &rd) && rd < 18.0f;
        if (g_rideTrain && !keep) { Log("view: the train ride ends (train %08X %s)", static_cast<unsigned>(g_rideTrain), rd < 99.0f ? "away from the camera" : "gone"); g_rideTrain = 0; }
        const uintptr_t train = keep ? g_rideTrain : TrainAtCamera(camX, camY, &d);
        float tx = 0.0f, ty = 0.0f, tz = 0.0f;
        const uint8_t* tb = reinterpret_cast<const uint8_t*>(train);
        if (train && game::ReadPlacement(tb, game::kVehiclePlacementPtr, &tx, &ty, &tz)) {
            const bool boarding = g_foundAt > 0.0 && Now() - g_foundAt < 20.0 && std::hypot(tx - g_foundX, ty - g_foundY) < 4.0f;
            if (train == g_rideTrain || boarding) {
                if (train != g_rideTrain) Log("view: the player rides train %08X (lost %.1f s ago %.1f blocks from it): following it", static_cast<unsigned>(train),
                                              Now() - g_foundAt, std::hypot(tx - g_foundX, ty - g_foundY));
                g_rideTrain = train;
                out->inVehicle = true;
                out->vehicle = tb;
                out->vehicleSprite = game::Placement(tb, game::kVehiclePlacementPtr);
                out->x = tx; out->y = ty; out->z = tz;
                float fx = 0.0f, fy = 0.0f;
                if (game::ReadFacing(tb, game::kVehiclePlacementPtr, &fx, &fy) && std::hypot(fx, fy) > 1e-4f) {
                    const float l = std::hypot(fx, fy);
                    out->dirX = fx / l; out->dirY = fy / l; out->facingKnown = true;
                }
                // The body drawn last frame for its sprite, when there is one, is the train as the views show it (run
                // cam16_tr6: it agrees with the placement within 0.06; the z 2 and 1 stretches are the line's tunnels
                // and low track, not a misread).
                for (const CameraCar& c : LiveCameraCars()) {
                    if (c.object != reinterpret_cast<uintptr_t>(out->vehicleSprite)) continue;
                    const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
                    static double lastLog = -1.0;
                    if (Now() - lastLog > 1.0) {
                        lastLog = Now();
                        Log("view: train ride: body drawn at %.2f,%.2f z %.2f, placement %.2f,%.2f z %.2f", cx, static_cast<float>(gta2::kMapHeight) - cz, c.y0, tx, ty, tz);
                    }
                    out->x = cx; out->y = static_cast<float>(gta2::kMapHeight) - cz; out->z = c.y0;
                    break;
                }
                out->source = "rider of a train at the camera";
                out->valid = tx >= -1.0f && tx <= gta2::kMapWidth + 1.0f && ty >= -1.0f && ty <= gta2::kMapHeight + 1.0f;
                return out->valid;
            }
        }
    }
    if (!ped) return false;
    g_rideTrain = 0;
    if (!atTheWheel && PedSignature(ped)) {
        g_lastPlayerPed = ped;
        const uint32_t was = g_lastPlayerPedId;
        if (!ReadAt(ped + kPedIdWord, &g_lastPlayerPedId)) g_lastPlayerPedId = 0;
        static int idLogs = 0;
        if (g_lastPlayerPedId != was && idLogs++ < 40) Log("view: player ped id %u (was %u)", g_lastPlayerPedId, was);
    }

    const uint8_t* pedBytes = reinterpret_cast<const uint8_t*>(ped);
    uintptr_t physics = 0;
    if (!atTheWheel && (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics))) return false;
    const uint8_t* physicsBytes = reinterpret_cast<const uint8_t*>(physics);
    uintptr_t sprite = 0;
    if (physics) ReadAt(physics + game::kPhysicsSprite, &sprite);

    out->ped = pedBytes;
    out->pedSprite = reinterpret_cast<const void*>(sprite);

    // Where he is and which way he faces, off his sprite object, which is the
    // placement block the game moves him by. The ped's own copy of the position
    // is the fallback.
    float x = 0.0f, y = 0.0f, z = 0.0f;
    bool placed = physics && game::ReadPlacement(physicsBytes, game::kPhysicsSprite, &x, &y, &z);
    if (!placed && !atTheWheel) {
        int32_t fx = 0, fy = 0, fz = 0;
        if (!ReadAt(ped + game::kPedX, &fx) || !ReadAt(ped + game::kPedY, &fy) ||
            !ReadAt(ped + game::kPedZ, &fz)) {
            return false;
        }
        x = fx * game::kFixedScale;
        y = fy * game::kFixedScale;
        z = fz * game::kFixedScale;
    }
    float dirX = 0.0f, dirY = 0.0f;
    out->facingKnown = physics && game::ReadFacing(physicsBytes, game::kPhysicsSprite, &dirX, &dirY);

    // In a car, the car is the thing to follow. The ped's own vehicle word at
    // +0x16C stays empty at the wheel (measured: it reads zero while a car he
    // got into drives off with him), so the car is found from the other end:
    // the vehicle whose driver word is this ped. His sprite placement is
    // recycled by the game once he is inside, so it must not be read then.
    uintptr_t vehicle = 0;
    if (!(ReadAt(ped + game::kPedVehicle, &vehicle) && Plausible(vehicle))) vehicle = 0;
    if (!vehicle) vehicle = VehicleDrivenBy(ped);
    if (vehicle) {
        float vx = 0.0f, vy = 0.0f, vz = 0.0f;
        const uint8_t* vehicleBytes = reinterpret_cast<const uint8_t*>(vehicle);
        if (game::ReadPlacement(vehicleBytes, game::kVehiclePlacementPtr, &vx, &vy, &vz)) {
            out->inVehicle = true;
            out->vehicle = vehicleBytes;
            out->vehicleSprite = game::Placement(vehicleBytes, game::kVehiclePlacementPtr);
            x = vx;
            y = vy;
            z = vz;
            float vdx = 0.0f, vdy = 0.0f;
            if (game::ReadFacing(vehicleBytes, game::kVehiclePlacementPtr, &vdx, &vdy)) {
                dirX = vdx;
                dirY = vdy;
                out->facingKnown = true;
            }
        }
    }

    if (!(x >= -1.0f && x <= gta2::kMapWidth + 1.0f && y >= -1.0f && y <= gta2::kMapHeight + 1.0f &&
          z >= -1.0f && z <= gta2::kMapLevels + 2.0f)) {
        return false;
    }
    out->x = x;
    out->y = y;
    out->z = z;
    if (out->facingKnown) {
        const float len = std::hypot(dirX, dirY);
        if (len > 1e-4f) {
            out->dirX = dirX / len;
            out->dirY = dirY / len;
        } else {
            out->facingKnown = false;
        }
    }
    out->valid = true;
    g_foundX = x; g_foundY = y; g_foundAt = Now();   // FIX-CAMERA-16: for the train rider
    return true;
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------

void ViewModePollInput(HWND presentWindow, bool menuVisible, bool worldLoaded) {
    static bool keyWasDown = false;
    static bool captured = false;
    static double levelUpSince = 0.0;
    static bool demoDone = false;

    // The scripted switch for a recording. See demoSwitchSeconds.
    if (!worldLoaded) {
        levelUpSince = 0.0;
        demoDone = false;
    } else if (g_settings.demoSwitchSeconds > 0.0f && !demoDone) {
        const double now = Now();
        if (levelUpSince == 0.0) levelUpSince = now;
        if (now - levelUpSince >= g_settings.demoSwitchSeconds) {
            demoDone = true;
            const int to = g_settings.demoSwitchTo;
            SetViewMode(static_cast<ViewMode>(to < 0 || to >= kViewModeCount ? 2 : to));
            Log("view: demo switch after %.0f s", g_settings.demoSwitchSeconds);
        }
    }

    DWORD pid = 0;
    if (HWND foreground = GetForegroundWindow()) GetWindowThreadProcessId(foreground, &pid);
    const bool ours = pid == GetCurrentProcessId();
    if (worldLoaded) ServiceWarpHold();

    // The game's own control keys, as this process sees them, for reading a
    // scripted session back: one line per press and release.
    // Edges on the held state: the "pressed since last call" bit is consumed
    // by whichever poll of the key runs first in a frame (the progress probe
    // reads F9 too), so a press could be lost.
    static bool warpHeld = false, sceneHeld = false;
    const bool warpDown = g_settings.devWarpKey > 0 && g_settings.devWarpKey < 256 && ours &&
                          (GetAsyncKeyState(g_settings.devWarpKey) & 0x8000) != 0;
    const bool sceneDown = g_settings.devSceneKey > 0 && g_settings.devSceneKey < 256 && ours &&
                           (GetAsyncKeyState(g_settings.devSceneKey) & 0x8000) != 0;
    const bool warpPressed = warpDown && !warpHeld, scenePressed = sceneDown && !sceneHeld;
    warpHeld = warpDown;
    sceneHeld = sceneDown;
    if (warpPressed && worldLoaded) {
        WarpPlayerToParkedCar(80.0f);
    }
    // FIX-ENTRY-1: [devtools] enter_key, the game's own entry on the nearest parked car; the Return trace.
    {
        static bool enterHeld = false;
        const bool enterDown = g_settings.devEnterKey > 0 && g_settings.devEnterKey < 256 && ours &&
                               (GetAsyncKeyState(g_settings.devEnterKey) & 0x8000) != 0;
        if (enterDown && !enterHeld && worldLoaded) EnterNearestParkedCar();
        enterHeld = enterDown;
        if (worldLoaded) EntryService();
    }
    if (scenePressed && worldLoaded) {
        if (g_settings.devIniPath[0]) {
            // Re-read the spot each press: a scenario script may edit the ini between warps.
            char sceneXy[64] = {};
            GetPrivateProfileStringA("devtools", "scene_xy", "", sceneXy, sizeof(sceneXy), g_settings.devIniPath);
            float sx = 0.0f, sy = 0.0f, sz = -1.0f;
            if (sscanf(sceneXy, "%f,%f,%f", &sx, &sy, &sz) >= 2) {
                g_settings.devSceneX = sx; g_settings.devSceneY = sy; g_settings.devSceneZ = sz;
            }
        }
        WarpSceneToRoad(g_settings.devSceneX, g_settings.devSceneY, g_settings.devSceneZ);
    }
    if (g_settings.logKeys) {
        static const struct { int vk; const char* name; } kWatched[] = {
            {VK_RETURN, "Return"}, {VK_CONTROL, "Ctrl"}, {VK_SPACE, "Space"}, {VK_TAB, "Tab"},
            {VK_MENU, "Alt"}, {VK_SHIFT, "Shift"}, {VK_UP, "Up"}, {VK_DOWN, "Down"},
            {VK_LEFT, "Left"}, {VK_RIGHT, "Right"}, {'F', "F"}, {'E', "E"},
        };
        static bool wasDown[sizeof(kWatched) / sizeof(kWatched[0])] = {};
        for (size_t i = 0; i < sizeof(kWatched) / sizeof(kWatched[0]); ++i) {
            const bool down = (GetAsyncKeyState(kWatched[i].vk) & 0x8000) != 0;
            if (down != wasDown[i]) {
                Log("key: %s %s (foreground %s)", kWatched[i].name, down ? "down" : "up", ours ? "ours" : "other");
                wasDown[i] = down;
            }
        }
    }

    // Polled, like F4: GTA2 reads its keyboard through DirectInput, so there is
    // no message to take it from. Alt is excluded so Alt+key chords stay the
    // system's.
    const bool altDown = (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
    const int key = g_settings.toggleKey;
    // Bit 15 is "down now"; bit 0 is "pressed since the last call", which is what
    // catches a tap shorter than one frame - a frame can be a long time here.
    const SHORT state = key > 0 && key < 256 ? GetAsyncKeyState(key) : 0;
    const bool keyDown = (state & 0x8000) != 0 && !altDown;
    const bool tapped = (state & 0x0001) != 0 && !altDown;
    if ((tapped || (keyDown && !keyWasDown)) && ours && !menuVisible) CycleViewMode();
    keyWasDown = keyDown;
    // FIX-COCKPIT-BODY (owner item 3): the dashcam key, at the wheel in first person (cockpit_mode.h).
    CockpitModePoll(ours && !menuVisible && !altDown && worldLoaded, g_navInVehicle && CurrentViewMode() == ViewMode::FirstPerson);

    // Camera-relative controls on foot in the street views.
    {
        const double now = Now();
        float dt = g_navLastPoll > 0.0 ? static_cast<float>(now - g_navLastPoll) : 1.0f / 30.0f;
        g_navLastPoll = now;
        if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
        const ViewMode mode = CurrentViewMode();
        const bool active = g_settings.navMap && worldLoaded && ours && !menuVisible &&
                            mode != ViewMode::Classic && g_navHeadingKnown && !g_navInVehicle;
        if (active) InstallNavHook(false);
        // FIX-AIM-1: the attack key is read through the same hook (the swing log, the aim assist), so it goes in on
        // foot in a street view whatever nav_map says; it passes every key through unchanged until something needs it.
        if (worldLoaded && ours && mode != ViewMode::Classic && !g_navInVehicle) InstallNavHook(false);
        const bool nowActive = active && g_diHooked;
        if (g_navActive && !nowActive) ReleaseInjected();
        if (!nowActive) g_navLastKeys = -1, g_navLookYaw = 0.0f;   // re-latched on the next frame on foot
        g_navActive = nowActive;
        if (g_navActive) SteerPlayer(mode, dt);
        // FIX-AIM-1: the aim assist (after the controller: its turn keys win while it holds a press or tracks).
        AssistSteer(g_settings.aimAssist && ViewAimAssistOn() && worldLoaded && ours && !menuVisible && mode != ViewMode::Classic &&
                        g_navHeadingKnown && !g_navInVehicle && g_diHooked && !InputHeld(), dt);
        if (g_navActive && InputHeld()) ReleaseInjected();   // FIX-KNOCKDOWN: down, he goes nowhere
        if (InputHeld() != g_holdLogged) {
            g_holdLogged = !g_holdLogged;
            Log("knockdown: player keys %s", g_holdLogged ? "held (down on the ground)" : "back to the player");
        }
    }

    const bool want = worldLoaded && ours && !menuVisible && g_settings.mouseLook &&
                      CurrentViewMode() != ViewMode::Classic && presentWindow != nullptr;
    if (!want) {
        captured = false;
        return;
    }
    RECT rect;
    if (!GetWindowRect(presentWindow, &rect)) {
        captured = false;
        return;
    }
    const POINT centre = {(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2};
    POINT cursor;
    if (!GetCursorPos(&cursor)) return;
    if (!captured) {
        // The first frame only parks the cursor; the jump from wherever it was
        // is not a look.
        captured = true;
        SetCursorPos(centre.x, centre.y);
        return;
    }
    int dx = cursor.x - centre.x;
    int dy = cursor.y - centre.y;
    if (dx == 0 && dy == 0) return;
    SetCursorPos(centre.x, centre.y);
    // A remote pointer (VNC, a remote desktop) is placed, not moved: when the
    // warp did not reach the client, the next report is the whole way back from
    // wherever its pointer sits. That is not a look; a hand never moves the
    // mouse a quarter of the screen in a frame.
    const int maxStep = (std::max)(1, static_cast<int>(g_settings.mouseMaxStep));
    if (std::abs(dx) > maxStep * 8 || std::abs(dy) > maxStep * 8) return;
    dx = (std::max)(-maxStep, (std::min)(maxStep, dx));
    dy = (std::max)(-maxStep, (std::min)(maxStep, dy));
    // Sensitivity 1: a quarter turn across the window's width.
    const float width = static_cast<float>((std::max)(static_cast<LONG>(320), rect.right - rect.left));
    const float perCount = (90.0f / width) * kDegToRad * (std::max)(0.05f, g_settings.mouseSensitivity) * ViewTurnSpeedScale();
    g_look.yaw = WrapAngle(g_look.yaw + static_cast<float>(dx) * perCount);
    g_look.pitch += static_cast<float>(g_settings.invertY ? dy : -dy) * perCount;
    g_look.pitch = (std::min)((std::max)(g_look.pitch, -85.0f * kDegToRad), 85.0f * kDegToRad);
    g_look.lastMoved = Now();
}

// ---------------------------------------------------------------------------
// The camera itself
// ---------------------------------------------------------------------------

// Every frame's camera yaw against the game's heading, when GTA2DX9_LOG_CAMERA=1
// is in the environment: for measuring the turn rate from a test session.
static bool cameraLogVerbose() {   // FIX-CAMERA-8: GTA2DX9_LOG_CAMERA=2 adds per-frame swing/boom lines
    static int v = -1;
    if (v < 0) { char buf[8] = {}; v = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) >= 2 ? 1 : 0; }
    return v != 0;
}
static bool cameraLogOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    return enabled != 0;
}
namespace { bool CameraLogOnForAim() { return cameraLogOn(); } }   // FIX-CAMERA-11: for UpdateAim above

static void LogCameraFrame(const char* view, float camYaw, float headingYaw, float dt,
                           const gta2::Vec3* eye = nullptr, float px = 0.0f, float pz = 0.0f, float extra = 0.0f) {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    if (!enabled) return;
    static float lastCam = 0.0f;
    const float rate = WrapAngle(camYaw - lastCam) / (std::max)(dt, 1e-3f) / kDegToRad;
    lastCam = camYaw;
    if (eye)
        Log("cam: %s yaw=%.1f heading=%.1f rate=%.0f dt=%.3f eye=%.2f,%.2f,%.2f at=%.2f,%.2f back=%.2f x=%.2f", view, camYaw / kDegToRad,
            headingYaw / kDegToRad, rate, dt, eye->x, eye->y, eye->z, px, pz, std::hypot(eye->x - px, eye->z - pz), extra);
    else
        Log("cam: %s yaw=%.1f heading=%.1f rate=%.0f dt=%.3f", view, camYaw / kDegToRad, headingYaw / kDegToRad, rate, dt);
}

// QUALITY-BAR row 22: the car chase framing. A low, close camera (the car about
// 40 % of the frame's width at rest, its rear bumper in the frame), a field of
// view that widens and a camera that drops back a little with speed, and a look
// point that leads into a turn. The rig is sized from the car's own body
// (CarBodiesExtent), so a van or a bus is framed as a sedan is. ThirdDistance
// and ThirdHeight in the ini still scale it (their defaults 3.4 and 1.25 are 1).
namespace chase {
constexpr float kWidthAtRest = 0.40f;   // the car's share of the frame's width at a standstill
constexpr float kPitch = 13.0f;         // degrees the camera looks down at a standstill
constexpr float kSpeedFov = 11.0f;      // extra degrees of vertical field of view at full speed
constexpr float kPullBack = 0.15f;      // extra blocks behind at full speed (times ThirdPullBack)
constexpr float kTurnLead = 0.15f;      // blocks of sideways lead per rad/s of turn...
constexpr float kTurnLeadMax = 0.30f;   // ...up to this
float g_back = 0.0f, g_height = 0.0f, g_lookHeight = 0.0f;   // eased rig for the current body
bool g_known = false;
float g_lastHeading = 0.0f, g_turnRate = 0.0f, g_lead = 0.0f;
bool g_headingKnown = false;
// Framing counter (log): frames, sum of the width share, frames with the whole car in frame.
int g_frames = 0, g_whole = 0;
double g_widthSum = 0.0, g_fovSum = 0.0;
}  // namespace chase

// The soft follow's own line (GTA2DX9_LOG_CAMERA=1): the camera's yaw, what it
// follows, his facing and the way he walks, his speed, and whether it follows.
static void LogFootFollow(float yaw, float target, float heading, float walkYaw, float speed, bool following,
                          bool keys, float engage) {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    if (!enabled) return;
    Log("foot: yaw=%.1f target=%.1f heading=%.1f walk=%.1f speed=%.2f follow=%d keys=%d engage=%.2f", yaw / kDegToRad,
        target / kDegToRad, heading / kDegToRad, walkYaw / kDegToRad, speed, following ? 1 : 0, keys ? 1 : 0, engage);
}

float ViewTurnSpeedScale() { return (std::max)(g_settings.turnSpeed, 5.0f) / 100.0f; }

bool ViewPlayerDrawnTurn(float* capRadPerSec, float* easeSec) {
    if (CurrentViewMode() != ViewMode::ThirdPerson || g_navInVehicle || !g_navHeadingKnown) return false;
    if (capRadPerSec) *capRadPerSec = (std::max)(g_settings.pedDrawnTurnRate, 10.0f) * ViewTurnSpeedScale() * kDegToRad;
    if (easeSec) *easeSec = (std::max)(g_settings.pedDrawnEase, 0.01f);
    return true;
}

void ViewLogPlayerDrawnYaw(float heading, float rate, float dt) {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    if (!enabled) return;
    Log("ped: yaw=%.1f rate=%.0f dt=%.3f", heading / kDegToRad, rate / kDegToRad, dt);
}

void ViewCameraSolver::Reset() {
    settled_ = false;
    awayTime_ = 0.0f;
    engageTime_ = 0.0f;
    idleTime_ = 0.0f;
    footFollowing_ = false;
    finalYawKnown_ = false;
    shownPoseKnown_ = false;
    carRaise_ = 0.0f;
    pocket_ = 0.0f;
    floorSettled_ = false;
    status_ = "classic";
    velX_ = velZ_ = 0.0f;
    speedFrac_ = 0.0f;
    yawRate_ = 0.0f;
    followYawVel_ = 0.0f;
    fpYawVel_ = 0.0f;
    roll_ = 0.0f;
    shake_ = 0.0f;
    forwardAccel_ = 0.0f;
    speed = 0.0f;
    blend_ = 0.0f;
    downTime_ = 0.0f;
    deathMix_ = 0.0f;
    lastDeathCam_ = false;
    lastPitchKnown_ = false;
    fpEyeKnown_ = false;
    fpOffX_ = fpOffY_ = fpOffZ_ = 0.0f;
    fpGlideDur_ = 0.0f; fpRiding_ = false; fpRideMode_ = 0;
    boomKnown_ = false;
    snapEye_ = true;
}

// A critically damped spring on an angle: `yaw` chases `target` with velocity
// `vel`, never faster than `maxRate` (radians a second). The spring settles in
// about 4 / omega seconds without overshoot; the cap is what keeps a spin from
// becoming a whirl.
static void SpringTurn(float* yaw, float* vel, float target, float omega, float maxRate, float dt) {
    const float error = WrapAngle(target - *yaw);
    const float accel = omega * omega * error - 2.0f * omega * *vel;
    *vel += accel * dt;
    if (maxRate > 0.0f) *vel = (std::max)(-maxRate, (std::min)(maxRate, *vel));
    // Never past the target within a step: the clamp above can leave the
    // velocity pointing through it on a tiny error. And never more in one
    // frame than the rate allows at 30 fps: a long frame (a hitch) turns the
    // picture no further than a short one would have.
    float step = *vel * (std::min)(dt, 1.0f / 30.0f);
    if ((error > 0.0f && step > error) || (error < 0.0f && step < error)) {
        step = error;
        *vel = 0.0f;
    }
    *yaw = WrapAngle(*yaw + step);
}

// ---- QB-17/18: the beats' camera (WASTED, BUSTED, JOB COMPLETE; see beats.h) ----------
namespace beatcam {
uint32_t g_serial = 0;
float g_yaw0 = 0.0f;       // where round him the orbit starts (polar angle about the anchor)
float g_clearR = 1e9f;     // the radius the walls leave, eased
float g_lastLog = -1.0f;
bool g_cut = false;        // the chase camera was far from him at the start: cut, not blend
// FIX-CAMERA-12 (pmq77): the shown eye's own line to him. Blocked (under half clear) for a
// moment, the orbit is searched again from where it stands (cut to the clearest place round
// him); with no place half clear the beat hands the frame back to the chase camera.
float g_blockedT = 0.0f;   // seconds the shown eye's line has been under half clear
float g_lastSearch = -10.0f;
float g_fall = 0.0f;       // 0..1, how far the beat has handed the frame back
float g_hExtra = 0.0f;     // height a re-search added (above a wall)
bool g_fallWant = false;
int BeatWallGuard() {
    static int on = -1;
    if (on < 0) { char b[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_BEAT_CAM_GUARD", b, sizeof b) && atoi(b) == 0 ? 0 : 1;
                  Log("beat cam: walled-spot guard %s (FIX-CAMERA-12 pmq77)", on ? "on" : "off (GTA2DX9_BEAT_CAM_GUARD=0)"); }
    return on;
}

// How far along the line from `from` to `to` is free of solid blocks (1 all of it).
float FreeFraction(const ViewQueries& q, const gta2::Vec3& from, const gta2::Vec3& to) {
    if (!q.blocked) return 1.0f;
    const float d = std::sqrt((to.x - from.x) * (to.x - from.x) + (to.y - from.y) * (to.y - from.y) + (to.z - from.z) * (to.z - from.z));
    const int steps = (std::max)(6, (std::min)(96, static_cast<int>(d / 0.04f)));
    // The cell he stands in may count as solid itself (a stair or a slope has a lid): the
    // line starts where it first leaves solid ground, and ends at the next wall - or at a
    // railing, a fence or a sign (flat panels, see-through for the chase camera, but a
    // beat's shot through one is a shot of the railing).
    bool out = false;
    float cellFree = 1.0f;
    for (int i = 1; i <= steps; ++i) {
        const float t = static_cast<float>(i) / steps;
        const float x = from.x + (to.x - from.x) * t, y = from.y + (to.y - from.y) * t, z = from.z + (to.z - from.z) * t;
        float panel = 1.0f;
        const bool solid = q.blocked(q.context, x, y, z) ||
                           (out && q.panelDistance && q.panelDistance(q.context, x, y, z, &panel) && panel < 0.04f);
        if (!solid) out = true;
        else if (out) { cellFree = static_cast<float>(i - 1) / steps; break; }
    }
    // FIX-CAMERA-9 (pm9-fp-wasted-death-cam / pm10-third-wasted-...-camera-in-truck): the cells do not see the drawn
    // mesh's partial faces (the iron staircase's rail at the wil spawn yard: the shot framed through its sheet, ~60 %
    // of the frame dark rail, run fh3_beat1) nor the vehicles (the WASTED shot stood inside a truck parked by the
    // body). The line also stops at the first surface the mesh draws and at a car body's box, skipping the car the
    // body lies in (died at the wheel). GTA2DX9_BEAT_CAM_MESH=0 restores the cells only (A/B).
    static int meshOn = -1;
    if (meshOn < 0) { char b[8] = {}; meshOn = GetEnvironmentVariableA("GTA2DX9_BEAT_CAM_MESH", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    if (!meshOn) return cellFree;
    float free = cellFree;
    if (eyecol::Ready()) {
        float t = 1.0f;
        if (eyecol::SegmentHit(from, to, &t)) free = (std::min)(free, (std::max)(0.0f, t - 0.12f / (std::max)(d, 0.12f)));
    }
    auto inside = [](const CameraCar& c, float x, float y, float z) {
        if (y < c.y0 - 0.02f || y > c.y1 + 0.08f) return false;
        float sgn = 0.0f;
        for (int k = 0; k < 4; ++k) {
            const int j = (k + 1) & 3;
            const float cr = (c.x[j] - c.x[k]) * (z - c.z[k]) - (c.z[j] - c.z[k]) * (x - c.x[k]);
            if (sgn == 0.0f) sgn = cr >= 0.0f ? 1.0f : -1.0f;
            else if (cr * sgn < 0.0f) return false;
        }
        return true;
    };
    for (const CameraCar& c : LiveCameraCars()) {
        if (inside(c, from.x, from.y, from.z) || inside(c, from.x, c.y0 + 0.05f, from.z)) continue;   // the car he lies in
        for (int i = 1; i <= steps; ++i) {
            const float t = static_cast<float>(i) / steps;
            if (t >= free) break;
            const float x = from.x + (to.x - from.x) * t, y = from.y + (to.y - from.y) * t, z = from.z + (to.z - from.z) * t;
            if (inside(c, x, y, z)) { free = (std::max)(0.0f, static_cast<float>(i - 1) / steps - 0.12f / (std::max)(d, 0.12f)); break; }
        }
    }
    return free;
}

struct Shot { float r0, r1, h0, h1, look, orbitDeg, fovDeg, pushSecs; };
Shot ShotFor(const BeatState& b) {
    Shot s{};
    switch (b.kind) {
        // High over the body, craning down and in while it turns slowly round him.
        case BeatKind::Wasted:   s = {1.7f, 1.05f, 1.7f, 0.75f, 0.08f, 10.0f, 50.0f, 3.2f}; break;
        // Eye level, close, turning the other way: him and the officers on him.
        case BeatKind::Busted:   s = {1.5f, 1.0f, 0.65f, 0.5f, 0.30f, -7.0f, 50.0f, 3.0f}; break;
        // In front of him, low, looking up a little, pushing in: the hero shot.
        case BeatKind::Complete: s = {1.5f, 0.95f, 0.36f, 0.30f, 0.36f, 6.0f, 46.0f, 3.0f}; break;
        default: break;
    }
    if (b.inVehicle) {
        s.r0 *= 2.0f; s.r1 *= 2.0f;
        s.h0 += 0.5f; s.h1 += 0.5f;
        s.look = (std::max)(s.look, 0.25f);
    }
    return s;
}

// The beat's framing, blended over whatever the solver set (its share is Beat().camera).
// In polar terms about where he was: the angle, radius and height go from the chase
// camera's to the beat's, so the move swings round him and never passes through him; at
// share 0 it is exactly the chase camera.
void Apply(const ViewQueries& q, float dt, gta2::Camera* camera) {
    const BeatState& b = Beat();
    if (b.kind == BeatKind::None) {
        g_serial = 0;
        return;
    }
    float w = b.camera;
    const Shot shot = ShotFor(b);
    const gta2::Vec3 A{b.x, b.y, b.z};
    const gta2::Vec3 T{A.x, A.y + shot.look, A.z};
    const gta2::Vec3 P = camera->Position();
    const float nYaw = camera->Yaw(), nPitch = camera->Pitch(), nFov = camera->FovY();
    const float dx = P.x - A.x, dz = P.z - A.z;
    const float rn = std::hypot(dx, dz);
    const float phiN = rn > 0.3f ? std::atan2(dx, dz) : WrapAngle(nYaw + kPi);
    const float hn = P.y - A.y;
    if (b.serial != g_serial) {
        // Where round him to stand: the clearest of 24 angles near the preferred one - for
        // the death and the arrest where the camera already is, for the job in front of him.
        g_serial = b.serial;
        const float prefer = b.kind == BeatKind::Complete ? b.yaw : phiN;
        float best = -1e9f, bestFree = 0.0f;
        g_yaw0 = prefer;
        const float rTest = 0.5f * (shot.r0 + shot.r1), hTest = 0.5f * (shot.h0 + shot.h1);
        const bool guard = BeatWallGuard() != 0;
        for (int k = 0; k < 24; ++k) {
            const float off = ((k + 1) / 2) * (15.0f * kDegToRad) * ((k & 1) ? 1.0f : -1.0f);
            const float phi = WrapAngle(prefer + off);
            const gta2::Vec3 e{A.x + std::sin(phi) * rTest, A.y + hTest, A.z + std::cos(phi) * rTest};
            float free = FreeFraction(q, T, e);
            if (guard) {
                // pmq77: the mid pose alone was 74 % clear where the shot's start (r0, h0) was 18 %:
                // the whole path counts, its start and its end where the orbit has turned.
                const float phiEnd = WrapAngle(phi + shot.orbitDeg * kDegToRad * shot.pushSecs);
                const gta2::Vec3 e0{A.x + std::sin(phi) * shot.r0, A.y + shot.h0, A.z + std::cos(phi) * shot.r0};
                const gta2::Vec3 e1{A.x + std::sin(phiEnd) * shot.r1, A.y + shot.h1, A.z + std::cos(phiEnd) * shot.r1};
                free = (std::min)(free, (std::min)(FreeFraction(q, T, e0), FreeFraction(q, T, e1)));
            }
            const float score = free - 0.3f * std::fabs(off) / kPi;
            if (score > best) { best = score; bestFree = free; g_yaw0 = phi; }
        }
        g_clearR = 1e9f;
        g_lastLog = -1.0f;
        g_blockedT = 0.0f;
        g_lastSearch = -10.0f;
        g_fall = 0.0f;
        g_hExtra = 0.0f;
        g_fallWant = false;
        // The chase camera may already have gone to the new body the game placed at the
        // hospital or the station (66 blocks away in qb17_beats6): no sweep across the
        // city, the beat cuts to its shot.
        g_cut = std::hypot(rn, hn) > 6.0f;
        Log("beat cam: %s from yaw %.0f (chase at %.0f, r %.2f, h %.2f): orbit starts at %.0f, %.0f%% clear%s",
            BeatName(b.kind), prefer * (180.0f / kPi), phiN * (180.0f / kPi), rn, hn, g_yaw0 * (180.0f / kPi), bestFree * 100.0f,
            g_cut ? ", the chase camera is far: cut" : "");
    }
    if (g_cut && b.t < 1.0f) w = 1.0f;
    if (w <= 0.001f) return;
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    const float push = 1.0f - std::exp(-b.t / (shot.pushSecs * 0.4f));
    float r = shot.r0 + (shot.r1 - shot.r0) * push;
    float h = shot.h0 + (shot.h1 - shot.h0) * push;
    const float phi = WrapAngle(g_yaw0 + shot.orbitDeg * kDegToRad * b.t);
    // The walls: pull in to the free part of the line (fast in, slow out), and up a little.
    const gta2::Vec3 want{A.x + std::sin(phi) * r, A.y + h, A.z + std::cos(phi) * r};
    const float free = FreeFraction(q, T, want);
    const float rc = (std::max)(0.45f, r * free - 0.12f);
    g_clearR += (rc - g_clearR) * (rc < g_clearR ? 1.0f - std::exp(-dt / 0.06f) : 1.0f - std::exp(-dt / 0.5f));
    if (g_clearR > 1e8f) g_clearR = rc;
    if (free < 1.0f) h += (1.0f - free) * 0.4f;
    h += g_hExtra;
    r = (std::min)(r, g_clearR);
    // Blend from the chase camera's polar place.
    const float phiM = WrapAngle(phiN + WrapAngle(phi - phiN) * w);
    const float rM = rn + (r - rn) * w, hM = hn + (h - hn) * w;
    gta2::Vec3 eye{A.x + std::sin(phiM) * rM, A.y + hM, A.z + std::cos(phiM) * rM};
    if (q.floorAt) {
        float fy = 0.0f;
        if (q.floorAt(q.context, eye.x, eye.z, eye.y + 0.5f, &fy) && eye.y < fy + 0.2f) eye.y += (fy + 0.2f - eye.y) * w;
    }
    float eyeFree = -1.0f;
    if (BeatWallGuard() && q.blocked) {
        // FIX-CAMERA-12 (pmq77, cam12_beat1): under a deck (the ste passage where pmq77 died) the high WASTED
        // shot rose into the deck's slab and framed its underside. The eye stays 0.15 under the first
        // solid cell over him or over itself.
        float ceil = 1e9f;
        for (float y = A.y + 0.35f; y < eye.y + 0.2f; y += 0.1f) {
            if (q.blocked(q.context, A.x, y, A.z) || q.blocked(q.context, eye.x, y, eye.z)) { ceil = y; break; }
        }
        if (eye.y > ceil - 0.15f) eye.y = (std::max)(A.y + 0.25f, ceil - 0.15f);
    }
    if (BeatWallGuard() && w > 0.3f) {
        // FIX-CAMERA-12 (pmq77): the line from the eye actually shown. Under half clear for
        // 0.15 s: search the orbit again round him at this radius and height, and at the
        // shot's start and end radii and higher (the clearest place, 15 degree steps); cut
        // there if one is at least 60 % clear, else hand the frame back to the chase camera.
        eyeFree = FreeFraction(q, T, eye);
        g_blockedT = eyeFree < 0.5f ? g_blockedT + dt : 0.0f;
        if (g_blockedT > 0.15f && b.t - g_lastSearch > 0.4f && !g_fallWant) {
            g_lastSearch = b.t;
            float bestF = -1.0f, bestPhi = phi, bestR = r, bestH = h;
            const float rs[3] = {r, (std::max)(0.6f, 0.6f * r), shot.r1 * (b.inVehicle ? 2.0f : 1.0f)};
            const float hs[2] = {h, h + 0.8f};
            for (int k = 0; k < 24; ++k) {
                const float off = ((k + 1) / 2) * (15.0f * kDegToRad) * ((k & 1) ? 1.0f : -1.0f);
                const float ph = WrapAngle(phi + off);
                for (float rr : rs) for (float hh : hs) {
                    const gta2::Vec3 e{A.x + std::sin(ph) * rr, A.y + hh, A.z + std::cos(ph) * rr};
                    const float f = FreeFraction(q, T, e) - 0.05f * std::fabs(off) / kPi;
                    if (f > bestF) { bestF = f; bestPhi = ph; bestR = rr; bestH = hh; }
                }
            }
            if (bestF >= 0.6f) {
                // The orbit continues from the new place; the radius the walls leave starts there.
                g_yaw0 = WrapAngle(bestPhi - shot.orbitDeg * kDegToRad * b.t);
                g_clearR = bestR;
                g_hExtra += bestH - h;
                Log("beat cam: %s t=%.1f line from the eye %.0f%% clear: cut to %.0f deg, r %.2f h %.2f (%.0f%% clear)",
                    BeatName(b.kind), b.t, eyeFree * 100.0f, bestPhi * (180.0f / kPi), bestR, bestH, bestF * 100.0f);
                const gta2::Vec3 e{A.x + std::sin(bestPhi) * bestR, A.y + bestH, A.z + std::cos(bestPhi) * bestR};
                eye = e;
                eyeFree = bestF;
                g_blockedT = 0.0f;
            } else {
                g_fallWant = true;
                Log("beat cam: %s t=%.1f line from the eye %.0f%% clear and no place round him over 60%% (best %.0f%%): "
                    "the chase camera keeps the frame", BeatName(b.kind), b.t, eyeFree * 100.0f, bestF * 100.0f);
            }
        }
    }
    if (g_fallWant) g_fall += (1.0f - g_fall) * (1.0f - std::exp(-dt / 0.12f));
    if (g_fall > 0.001f) {
        // Back toward the camera the solver set this frame (the chase boom, or over where he was).
        const float k = g_fall;
        eye = {eye.x + (P.x - eye.x) * k, eye.y + (P.y - eye.y) * k, eye.z + (P.z - eye.z) * k};
        w *= 1.0f - k;
    }
    const float fx = T.x - eye.x, fz = T.z - eye.z;
    const float flat = (std::max)(std::hypot(fx, fz), 1e-3f);
    const float lookYaw = std::atan2(fx, fz), lookPitch = std::atan2(T.y - eye.y, flat);
    camera->SetPosition(eye);
    if (g_fall > 0.001f) {
        // Still looking at him (the solver's own aim is ahead of where he was), the beat's lens eased out.
        const float wl = (std::max)(w, g_fall);
        camera->SetOrientation(WrapAngle(nYaw + WrapAngle(lookYaw - nYaw) * wl), nPitch + (lookPitch - nPitch) * wl);
    } else {
        camera->SetOrientation(WrapAngle(nYaw + WrapAngle(lookYaw - nYaw) * w), nPitch + (lookPitch - nPitch) * w);
    }
    camera->SetRoll(camera->Roll() * (1.0f - w));
    camera->SetFovY(nFov + (shot.fovDeg * kDegToRad - nFov) * w);
    if (b.t - g_lastLog >= 0.5f) {
        g_lastLog = b.t;
        Log("beat cam: %s t=%.1f share %.2f eye %.2f,%.2f,%.2f r %.2f h %.2f at %.0f deg, line %.0f%% clear%s",
            BeatName(b.kind), b.t, w, eye.x, eye.y, eye.z, rM, hM, phiM * (180.0f / kPi), free * 100.0f,
            eyeFree >= 0.0f ? (eyeFree < 0.5f ? ", from the eye under half" : "") : "");
        if (eyeFree >= 0.0f) Log("beat cam: %s t=%.1f from the eye %.0f%% clear, handed back %.2f", BeatName(b.kind), b.t, eyeFree * 100.0f, g_fall);
    }
}
}  // namespace beatcam

bool ViewCameraSolver::Update(const PlayerState& player, const ViewQueries& queries, float dt,
                              gta2::Camera* camera) {
    const ViewMode mode = CurrentViewMode();
    {
        // QB-17/18: the beats watch the game's big message every frame of a street view.
        const float bx = player.x, bz = static_cast<float>(gta2::kMapHeight) - player.y;
        const float byaw = player.facingKnown ? std::atan2(player.dirX, -player.dirY) : followYaw_;
        // Its height is the floor the solver measured under him (a stair or a raised plaza
        // stands above the game's own z).
        const float by = floorSettled_ && std::hypot(bx - lastX_, bz - lastZ_) < 1.5f ? floorY_ : player.z;
        BeatsUpdate(player, mode != ViewMode::Classic, bx, by, bz, byaw, dt);
    }
    if (mode != lastMode_) {
        Reset();
        resetByModeSwitch_ = true;
        lastMode_ = mode;
    }
    if (mode == ViewMode::Classic || !player.valid) {
        g_aim.valid = false;
        g_aim.armed = false;
        g_aim.aimMix = 0.0f;
    }
    if (mode == ViewMode::Classic) {
        status_ = "classic";
        camera->SetRoll(0.0f);
        g_navHeadingKnown = false;
        return false;
    }
    if (!player.valid) {
        // Lost a moment ago - killed in a car that blew up, between the body and the
        // WASTED / BUSTED screen, between two bodies: for a few seconds the camera
        // rises and draws back over where he was, turning slowly, instead of
        // freezing inside the fireball (run cp2_new9 exp_t: a white frame for three
        // seconds). Found again far away (the hospital, the station), it cuts.
        if (settled_ && lostTime_ < 6.0f) {
            lostTime_ += (dt > 0.0f && dt < 0.25f) ? dt : 1.0f / 30.0f;
            SolveLost(queries, dt, camera);
            beatcam::Apply(queries, dt, camera);   // QB-17/18
            status_ = "third person, over where the player was";
            g_navHeadingKnown = false;
            return true;
        }
        status_ = "waiting for the player to be found";
        settled_ = false;
        resetByModeSwitch_ = false;   // found again after this: a respawn
        camera->SetRoll(0.0f);
        g_navHeadingKnown = false;
        return false;
    }
    lostTime_ = 0.0f;

    // Into the renderer's frame: x east, y up, z north. Map rows run north to
    // south, so the row is mirrored exactly as the mesh builder mirrors it.
    float px = player.x;
    float pz = static_cast<float>(gta2::kMapHeight) - player.y;
    const float py = player.z;
    // FIX-KNOCKDOWN (kd_t3 #4): knocked down, the subject is his body where it lies (up to 0.9 block off the
    // game's spot), not the spot: the chase camera framed a truck while he lay at the edge behind a post.
    if (!player.inVehicle && CurrentViewMode() != ViewMode::Classic) {
        float bx = 0.0f, bz = 0.0f;
        if (KnockdownPlayerBody(&bx, &bz) && std::hypot(bx - px, bz - pz) < 1.5f) { px = bx; pz = bz; }
    }
    // The camera's yaw convention: 0 looks north (+z), and Forward() is
    // (sin yaw, ., cos yaw). The game's facing is (dirX east, dirY south).
    const float headingYaw = player.facingKnown ? std::atan2(player.dirX, -player.dirY) : followYaw_;

    // A developer aid for the camera tests: [devtools] set_car_damage=N (re-read
    // twice a second, -1 off) writes N once into the damage word (+0x74) of the
    // car the player drives; from 16000 the game sets it alight and raises it by
    // itself, at 32000 it explodes (docs/actions-3d.md "Vehicle fields").
    if (g_settings.devIniPath[0] && player.inVehicle && player.vehicle) {
        static int clock = 0, applied = -1;
        if (++clock % 15 == 0) {
            const int want = GetPrivateProfileIntA("devtools", "set_car_damage", -1, g_settings.devIniPath);
            if (want >= 0 && want != applied && want <= 32000) {
                const int16_t v = static_cast<int16_t>(want);
                const bool ok = WriteAt(reinterpret_cast<uintptr_t>(player.vehicle) + 0x74, v);
                Log("devtools: set_car_damage %d on the player's car %p (%s)", want, player.vehicle, ok ? "written" : "write failed");
            }
            applied = want;
        }
    }
    // And [devtools] set_player_health=N: his health word (ped+0x216), written once
    // per change, so the next knock kills him (the WASTED camera checks).
    if (g_settings.devIniPath[0] && player.ped) {
        static int clock = 0, applied = -1;
        if (++clock % 15 == 0) {
            const int want = GetPrivateProfileIntA("devtools", "set_player_health", -1, g_settings.devIniPath);
            if (want >= 0 && want != applied && want <= 1000) {
                const bool ok = WriteAt(reinterpret_cast<uintptr_t>(player.ped) + 0x216, static_cast<uint16_t>(want));
                Log("devtools: set_player_health %d (%s)", want, ok ? "written" : "write failed");
            }
            applied = want;
        }
    }
    UpdateAim(player, px, pz, headingYaw, dt);
    // And [devtools] set_player_ammo=N (QB-6, scripted shooting): the ammunition word of the
    // gun in his hands is topped up to N whenever it is below (re-read twice a second, -1 off);
    // after UpdateAim, which has to see the drop a shot makes first.
    if (g_settings.devIniPath[0] && player.ped && !player.inVehicle) {
        static int clock = 0, want = -1;
        if (++clock % 15 == 0) {
            const int now = GetPrivateProfileIntA("devtools", "set_player_ammo", -1, g_settings.devIniPath);
            if (now != want) Log("devtools: set_player_ammo %d", now);
            want = now;
        }
        if (want > 0 && want <= 30000) {
            uintptr_t weapon = 0;
            int16_t ammo = 0;
            if (ReadAt(reinterpret_cast<uintptr_t>(player.ped) + game::kPedCurrentWeapon, &weapon) && weapon > 0x10000 &&
                ReadAt(weapon + game::kWeaponAmmo, &ammo) && ammo >= 0 && ammo < want / 2)
                WriteAt(weapon + game::kWeaponAmmo, static_cast<int16_t>(want));
        }
    }
    Solve(player, queries, dt, camera, px, py, pz, headingYaw, player.inVehicle);
    beatcam::Apply(queries, dt, camera);   // QB-17/18
    g_aim.y = floorY_;
    return true;
}

void ViewCameraSolver::SolveLost(const ViewQueries& q, float dt, gta2::Camera* camera) {
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    const gta2::Vec3 centre{lastX_, floorY_ + 0.2f, lastZ_};
    gta2::Vec3 eye{shownX_, shownY_, shownZ_};
    // A third of a second of stillness first: a locator that misses him for a
    // frame or two (a car door, a respawn scan) does not start a crane move. On
    // foot and on his feet (not down, not in a car that blew up) he is only being
    // re-found - getting into a car loses him for up to a second while the locator
    // re-scans - so the camera holds where it is for 1.5 s: before, it craned up and
    // back 3 blocks and the chase view then started from there, a hard cut to a high
    // far rig (QUALITY-BAR row 7).
    const bool aliveOnFoot = !lastInVehicle_ && downTime_ <= 0.0f && deathMix_ < 0.01f;
    if (lostTime_ > (aliveOnFoot ? 1.5f : 0.3f)) {
        float ox = eye.x - centre.x, oz = eye.z - centre.z;
        if (std::hypot(ox, oz) < 0.2f) {
            const float back = yawDegrees * kDegToRad;
            ox = -std::sin(back);
            oz = -std::cos(back);
        }
        const float around = std::atan2(ox, oz) + 6.0f * kDegToRad * dt;
        gta2::Vec3 want{centre.x + std::sin(around) * 3.2f, centre.y + 2.8f, centre.z + std::cos(around) * 3.2f};
        if (q.blocked) {
            const gta2::Vec3 from{centre.x, centre.y + 0.4f, centre.z};
            for (int i = 1; i <= 24; ++i) {
                const float t = static_cast<float>(i) / 24.0f;
                const gta2::Vec3 p = from + (want - from) * t;
                if (q.blocked(q.context, p.x, p.y, p.z)) {
                    want = from + (want - from) * (std::max)(0.0f, static_cast<float>(i - 1) / 24.0f - 0.03f);
                    break;
                }
            }
        }
        const float k = 1.0f - std::exp(-dt / 0.6f);
        eye = eye + (want - eye) * k;
    }
    const gta2::Vec3 dir = centre - eye;
    const float flat = std::hypot(dir.x, dir.z);
    float yaw = flat > 1e-4f ? std::atan2(dir.x, dir.z) : yawDegrees * kDegToRad;
    float pitch = std::atan2(dir.y, (std::max)(flat, 1e-4f));
    {
        // No faster than the chase camera turns, and the pitch eased.
        const float cap = 90.0f * kDegToRad * (std::min)(dt, 1.0f / 30.0f);
        const float last = yawDegrees * kDegToRad;
        yaw = WrapAngle(last + (std::max)(-cap, (std::min)(cap, WrapAngle(yaw - last))));
        if (lastPitchKnown_) pitch = lastPitch_ + (pitch - lastPitch_) * (1.0f - std::exp(-dt / 0.25f));
        lastPitch_ = pitch;
        lastPitchKnown_ = true;
    }
    roll_ *= std::exp(-dt / 0.2f);
    camera->SetPosition(eye);
    camera->SetOrientation(yaw, pitch);
    camera->SetRoll(roll_);
    shownX_ = eye.x;
    shownY_ = eye.y;
    shownZ_ = eye.z;
    eyeX_ = eye.x;
    eyeY_ = eye.y;
    eyeZ_ = eye.z;
    finalYaw_ = yaw;
    finalYawKnown_ = true;
    yawDegrees = yaw / kDegToRad;
    pitchDegrees = pitch / kDegToRad;
    LogCameraFrame("lost", yaw, yaw, dt, &eye, centre.x, centre.z, lostTime_);
}

namespace {

// A cheap, smooth, non-repeating wobble for the impact shake: three sines at
// incommensurate frequencies.
float Wobble(double t, float f) {
    return 0.5f * static_cast<float>(std::sin(t * f * 6.2832) + 0.6 * std::sin(t * f * 9.17 + 1.3) +
                                     0.3 * std::sin(t * f * 15.31 + 2.1));
}

// The street objects the camera keeps clear of, as upright cylinders (renderer
// frame): the game's own objects drawn as models (phone boxes, traffic lights,
// cones, crates, bins: map_objects.cpp, every one the game drew this frame, the
// ones behind the camera too) and the posts under the map's lamps (DrawProps
// stands one under every lamp). The map's walls and flat panels, and the street
// furniture placed by rule (PanelDistance, PropPush), are queried as before.
struct Obstacle {
    float x, z, y0, y1, r;
    bool post;
    bool tree = false;   // FIX-CAMERA-16: a tree's trunk, up to the top of its crown: never hopped over
};

// FIX-CAMERA-16: the trees DrawProps placed (SetChaseTrees), and the hero the third-person boom framed last
// (ChaseTreeAlpha's line). GTA2DX9_CAM_TREES=0: neither the boom nor the fade knows them (A/B).
std::vector<ChaseTree> g_chaseTrees;
struct ChaseHero { float x = 0.0f, y = 0.0f, z = 0.0f, height = 0.5f; double at = -1.0; } g_chaseHero;
bool ChaseTreesOn() {
    static int on = -1;
    if (on < 0) { char b[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_CAM_TREES", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    return on != 0;
}

void GatherObstacles(float x, float z, float range, bool posts, std::vector<Obstacle>* out, bool trees = false) {
    out->clear();
    for (const PropFootprint& p : MapObjectObstacles()) {
        if (std::fabs(p.x - x) > range || std::fabs(p.z - z) > range) continue;
        // The footprint radius is half the longer side of the object's quad; a box's
        // corner is up to 1.42 times that from its middle.
        out->push_back({p.x, p.z, p.y - 0.05f, p.y + p.height + 0.05f, p.radius * 1.42f, false});
    }
    if (trees && ChaseTreesOn())
        for (const ChaseTree& t : g_chaseTrees) {
            if (std::fabs(t.x - x) > range || std::fabs(t.z - z) > range) continue;
            Obstacle o{t.x, t.z, t.y - 0.05f, t.y + t.height + 0.05f, t.trunkR, false};
            o.tree = true;
            out->push_back(o);
        }
    if (!posts) return;
    // DrawProps stands the post at the cell's kerb or wall, not under the light
    // (MapLampPosts; the lamps themselves until it has run).
    const std::vector<gta2::Vec3>& lampPosts = MapLampPosts().size() == MapLamps().size() ? MapLampPosts() : MapLamps();
    for (const gta2::Vec3& at : lampPosts) {
        if (std::isnan(at.x)) continue;
        if (std::fabs(at.x - x) > range || std::fabs(at.z - z) > range) continue;
        // The post stands under the lamp (up to 3.5 blocks below it, DrawProps); the
        // street_lamp model's foot is 0.15 of a block across at most.
        out->push_back({at.x, at.z, at.y - 3.6f, at.y + 0.35f, 0.08f, true});
    }
}

// The obstacle whose cylinder, widened by `clear`, holds the point; null when none.
const Obstacle* ObstacleAt(const std::vector<Obstacle>& list, const gta2::Vec3& p, float clear, bool posts) {
    const Obstacle* found = nullptr;
    float deepest = 0.0f;
    for (const Obstacle& o : list) {
        if (o.post && !posts) continue;
        if (p.y < o.y0 - clear || p.y > o.y1 + clear) continue;
        const float depth = o.r + clear - std::hypot(p.x - o.x, p.z - o.z);
        if (depth > deepest) {
            deepest = depth;
            found = &o;
        }
    }
    return found;
}

// FIX-CAMERA-2: how far a point lies inside a car's footprint (seen from above), in blocks;
// negative outside (the distance to the nearest edge's line, which is the distance to the
// quad near its sides and an underestimate off its corners).
float CarFootprintDepth(const CameraCar& c, float x, float z) {
    float area = 0.0f;
    for (int i = 0; i < 4; ++i) {
        const int j = (i + 1) & 3;
        area += c.x[i] * c.z[j] - c.x[j] * c.z[i];
    }
    const float wind = area >= 0.0f ? 1.0f : -1.0f;
    float depth = 1e9f;
    for (int i = 0; i < 4; ++i) {
        const int j = (i + 1) & 3;
        const float ex = c.x[j] - c.x[i], ez = c.z[j] - c.z[i];
        const float el = std::hypot(ex, ez);
        if (el < 1e-4f) continue;
        // Inward is to the left of the edge for a counter-clockwise quad.
        const float d = wind * (ex * (z - c.z[i]) - ez * (x - c.x[i])) / el;
        depth = (std::min)(depth, d);
    }
    return depth;
}

// FIX-CAMERA-14 (pfl65 camera half, from FIX-CAMERA-13's unshipped patch): another car's body (not one the point's
// foot stands in or against) across the line from the eye `e` to the point `mid`: sampled at 11 points along it,
// inside a footprint below its roof.
// FIX-CAMERA-15 (pfl65): how fast each listed car moves (blocks a second, eased), from its footprint's centre frame to
// frame; updated once a frame by CarMotionUpdate. A car passing in traffic is not one to crane over.
struct CarMotion { float cx = 0.0f, cz = 0.0f, speed = 0.0f; double seen = 0.0; };
std::map<uintptr_t, CarMotion> g_carMotion;
void CarMotionUpdate(float dt) {
    const double now = Now();
    for (const CameraCar& c : LiveCameraCars()) {
        const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
        auto it = g_carMotion.find(c.object);
        if (it == g_carMotion.end() || now - it->second.seen > 0.5) {
            g_carMotion[c.object] = {cx, cz, 9.0f, now};   // unknown: taken as moving until measured
            continue;
        }
        CarMotion& m = it->second;
        if (dt > 1e-4f && dt < 0.25f) {
            const float v = std::hypot(cx - m.cx, cz - m.cz) / dt;
            m.speed += (v - m.speed) * (1.0f - std::exp(-dt / 0.3f));
        }
        m.cx = cx; m.cz = cz; m.seen = now;
    }
    if (g_carMotion.size() > 512)
        for (auto it = g_carMotion.begin(); it != g_carMotion.end();) it = now - it->second.seen > 2.0 ? g_carMotion.erase(it) : std::next(it);
}
float CarMotionSpeed(uintptr_t object) {
    const auto it = g_carMotion.find(object);
    return it == g_carMotion.end() ? 9.0f : it->second.speed;
}

bool CarHidesPoint(const gta2::Vec3& e, const gta2::Vec3& mid, float maxSpeed = 1e9f) {
    for (const CameraCar& c : LiveCameraCars()) {
        if (CarMotionSpeed(c.object) > maxSpeed) continue;
        if (CarFootprintDepth(c, mid.x, mid.z) > -0.1f) continue;   // he is in it or against it
        if (c.y1 < mid.y - 0.05f) continue;                          // lower than the point: seen over it
        if (CarFootprintDepth(c, e.x, e.z) > -0.05f && e.y < c.y1) continue;   // the eye in it: the car is not drawn
        for (int i = 1; i < 12; ++i) {
            const float t = static_cast<float>(i) / 12.0f;
            const gta2::Vec3 p = e + (mid - e) * t;
            if (p.y < c.y1 && p.y > c.y0 && CarFootprintDepth(c, p.x, p.z) > 0.0f) return true;
        }
    }
    return false;
}

// The cars and wrecks the chase camera keeps clear of: OFF with GTA2DX9_CAM_CARS=0 (A/B).
bool CameraCarsOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_CARS", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}

// The in-car lift cap and pitch hold (feel8): OFF with GTA2DX9_CAM_PITCHCAP=0 (A/B).
bool CameraMeshSolveOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_MESH", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}

// FIX-CAMERA-4: GTA2DX9_CAM_SWING=0 turns the on-foot boom swing off (A/B).
// FIX-CAMERA-10 (pfl14): the swing turns fast onto a clear heading and the boom eases at a sheet meanwhile.
bool CameraSwingFirstOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_SWING_FIRST", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}
bool CameraSwingOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_SWING", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}

bool CameraFrameClampOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_FRAME", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}

bool CameraCarPitchCapOn() {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_CAM_PITCHCAP", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
    }
    return enabled != 0;
}

}  // namespace

void ViewCameraSolver::Solve(const PlayerState& player, const ViewQueries& q, float dt,
                             gta2::Camera* camera, float px, float py, float pz,
                             float headingYaw, bool inVehicle) {
    const ViewMode mode = CurrentViewMode();
    const ViewModeSettings& s = g_settings;
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;   // the first frame, or a stall

    // A jump too big to be motion - a respawn, a level cut - is followed at once.
    const bool jumped = settled_ && std::hypot(px - lastX_, pz - lastZ_) > 4.0f;
    if (!settled_ || jumped) {
        followYaw_ = headingYaw;
        followYawVel_ = 0.0f;
        fpYaw_ = headingYaw;
        fpYawVel_ = 0.0f;
        g_fpViewYaw = headingYaw;
        lastYaw_ = headingYaw;
        floorSettled_ = false;
        settled_ = true;
        // The open-side sweep below is for a respawn or a warp only. A V switch keeps his
        // heading: without nav the sweep was a view-only offset, so the first-person view
        // looked 90 degrees away from his firing line (defect pm37: the reticle parked at
        // the screen edge after a V round trip that ended facing a wall).
        fpRespawnPending_ = resetByModeSwitch_ && !jumped ? 0.0f : 2.0f;
        resetByModeSwitch_ = false;
        fpRespawnLeft_ = fpRespawnOffset_ = 0.0f;
        g_look = ViewLook{};
        eyeX_ = px;
        eyeY_ = py + 1.0f;
        eyeZ_ = pz;
        velX_ = velZ_ = 0.0f;
        speedFrac_ = 0.0f;
        yawRate_ = 0.0f;
        roll_ = 0.0f;
        shake_ = 0.0f;
        forwardAccel_ = 0.0f;
        lastX_ = px;
        lastZ_ = pz;
        blend_ = 0.0f;
        lastInVehicle_ = inVehicle;
        downTime_ = 0.0f;
        deathMix_ = 0.0f;
        lastDeathCam_ = false;
        lastPitchKnown_ = false;
        fpEyeKnown_ = false;
        fpOffX_ = fpOffY_ = fpOffZ_ = 0.0f;
    fpGlideDur_ = 0.0f; fpRiding_ = false; fpRideMode_ = 0;
        extraLength_ = extraHeight_ = bodyHeight_ = 0.0f;
        framingKnown_ = false;
        boomKnown_ = false;
        snapEye_ = true;   // a warp or a level cut: the first frame is the solved rig, not his head
    }
    // In or out of a car, or thrown out of one by a blast: not a cut, a glide.
    if (inVehicle != lastInVehicle_) blend_ = 1.0f;
    lastInVehicle_ = inVehicle;
    // Down on the ground - knocked over, dead, arrested (ped state 8/9) - for more
    // than a moment: the death camera, pulled back and up over him, eased in.
    {
        const PedWords w = inVehicle ? PedWords{} : ReadPedWords(player.ped);
        const bool down = !inVehicle && (w.state == 8 || w.state == 9);
        downTime_ = down ? downTime_ + dt : 0.0f;
    }
    const bool deathCam = downTime_ > 0.8f;
    if (deathCam != lastDeathCam_) blend_ = 1.0f;
    deathMix_ += ((deathCam ? 1.0f : 0.0f) - deathMix_) * (1.0f - std::exp(-dt / 0.45f));
    if (!deathCam && deathMix_ < 0.01f) deathMix_ = 0.0f;

    // --- Motion ----------------------------------------------------------
    // Velocity from the position difference, lightly eased; the acceleration
    // from the velocity difference, which is what a crash shows up in.
    const float rawVX = (px - lastX_) / dt, rawVZ = (pz - lastZ_) / dt;
    lastX_ = px;
    lastZ_ = pz;
    const float prevVX = velX_, prevVZ = velZ_;
    const float velEase = 1.0f - std::exp(-dt / 0.06f);
    velX_ += (rawVX - velX_) * velEase;
    velZ_ += (rawVZ - velZ_) * velEase;
    speed = std::hypot(velX_, velZ_);
    const float reference = (std::max)(s.referenceSpeed, 1.0f);
    const float targetFrac = (std::min)(speed / reference, 1.0f);
    speedFrac_ += (targetFrac - speedFrac_) * (1.0f - std::exp(-dt / 0.35f));
    const float hx = std::sin(headingYaw), hz = std::cos(headingYaw);
    // Acceleration along the heading: braking is negative.
    const float accelX = (velX_ - prevVX) / dt, accelZ = (velZ_ - prevVZ) / dt;
    const float forwardAccel = accelX * hx + accelZ * hz;
    forwardAccel_ += (forwardAccel - forwardAccel_) * (1.0f - std::exp(-dt / 0.12f));
    // A hard stop - the raw velocity dropping by more than a car's worth in a
    // frame or two - kicks the camera.
    const float rawDrop = std::hypot(rawVX - prevVX, rawVZ - prevVZ);
    if (s.impactShake > 0.0f && rawDrop > 3.0f && speed < reference) {
        shake_ = (std::min)(shake_ + (rawDrop - 3.0f) / 8.0f * s.impactShake, 1.5f);
    }
    // FIX-VEHICLES: at the wheel, the body model's own impacts (the speed the car lost
    // in a step, filtered against GTA2's traffic jumps) kick the camera too, and its
    // drawn pitch, roll and heave are kept for the first-person eye.
    {
        VehicleFxMotion m;
        const bool have = inVehicle && VehicleFxPlayerMotion(&m);
        VehicleFxSetFirstRide(s.fpBodyRide);
        carPitch_ = have ? m.pitch : 0.0f;
        carRoll_ = have ? m.roll : 0.0f;
        carHeave_ = have ? m.heave : 0.0f;
        if (have && s.carImpactShake > 0.0f && m.impulse > 0.6f) {
            const float add = (std::min)((m.impulse - 0.4f) / 3.0f, 1.0f) * s.carImpactShake;
            shake_ = (std::min)(shake_ + add, 1.5f);
            Log("view: car impact %.2f blocks/s lost, camera shake %.2f", m.impulse, shake_);
        }
    }
    shake_ *= std::exp(-dt / 0.22f);
    shakeClock_ += dt;

    // The floor under him: the lid at or below his own level. His own level is a
    // per-block step on ramps and kerbs, so the floor is eased.
    float floor = py;
    if (!(q.floorAt && q.floorAt(q.context, px, pz, py + 0.75f, &floor))) floor = py;
    // FIX-CAMERA-9 (pm33-bil-third-pitch-black-upside-down-vehicle-silhouette-hangs-over-wall): at the wheel never under
    // the car's own height. Driven off a raised level (bil 158.5,144.5: z 4.0 -> 2.2 in 0.6 s, run fci4_pm33a) or up on
    // another car, the lid under it is the street's, the rig's base dropped there in 0.08 s and the chase eye sat
    // under the car, its black floor pan and wheels hanging over the top of the frame. GTA2DX9_CAM_CAR_Z=0: as before.
    {
        static int carZOn = -1;
        if (carZOn < 0) { char b[8] = {}; carZOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_Z", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        if (carZOn && inVehicle && py > floor + 0.05f) {
            if (cameraLogOn() && py > floor + 0.3f) {
                static int every = 0;
                if ((++every % 10) == 1) Log("cam: car above its floor: z %.2f, lid %.2f (the rig rides the car)", py, floor);
            }
            floor = py;
        }
    }
    if (!floorSettled_) {
        floorY_ = floor;
        floorSettled_ = true;
    } else {
        floorY_ += (floor - floorY_) * (1.0f - std::exp(-dt / 0.08f));
    }
    const float baseY = floorY_;

    // Free look swings back to straight ahead once the mouse has been still for
    // a while; 0 means it never does.
    ViewLook& look = g_look;
    const float returnDelay = mode == ViewMode::ThirdPerson ? s.tpReturnDelay : s.fpReturnDelay;
    if (returnDelay > 0.0f && Now() - look.lastMoved > returnDelay) {
        const float k = 1.0f - std::exp(-dt / 0.35f);
        look.yaw -= look.yaw * k;
        look.pitch -= look.pitch * k;
    }

    // Where the chase camera wants to look from: behind the heading, but when a
    // car is sliding - velocity and heading disagree - part way round towards
    // where it is actually going, so a drift is seen as one. Reversing keeps
    // the camera behind the nose, as every driving game does.
    float chaseYaw = headingYaw;
    if (inVehicle && speed > 1.5f) {
        const float vx = velX_ / speed, vz = velZ_ / speed;
        const float along = vx * hx + vz * hz;
        if (along > 0.2f) {
            const float velocityYaw = std::atan2(vx, vz);
            const float weight = (std::min)((speed - 1.5f) / 4.0f, 1.0f) * 0.6f;
            chaseYaw = WrapAngle(headingYaw + WrapAngle(velocityYaw - headingYaw) * weight);
        }
    }

    blend_ = (std::max)(0.0f, blend_ - dt / 1.2f);
    if (mode == ViewMode::FirstPerson) {
        lastDeathCam_ = deathCam;
        float eyeHeight = inVehicle ? s.fpEyeCar : s.fpEyeFoot;
        float ahead = inVehicle ? s.fpForwardCar : s.fpForwardFoot;
        float seat = 0.0f;
        if (inVehicle) {
            // In the cabin of the car's 3D body, when it has one: the driver's head.
            float deck, roof, screen, halfWidth;
            float bodyLength, bodyHeight, bodyHalfWidth;
            if (CarBodiesExtent(player.vehicleSprite, &bodyLength, &bodyHeight, &bodyHalfWidth)) {
                exitCar_ = player.vehicle;
                exitCarHalfLength_ = 0.5f * bodyLength;
                exitCarHalfWidth_ = bodyHalfWidth;
                exitCarHeight_ = bodyHeight;
            }
            if (CarBodiesCabin(player.vehicleSprite, &deck, &roof, &screen, &halfWidth)) {
                eyeHeight = deck + (roof - deck) * s.fpEyeCabin;
                ahead = screen - s.fpBehindScreen;
                seat = halfWidth * s.fpSeatCar;
            }
        }
        // Sideways is the heading turned a quarter: (-hz, hx) is the car's left.
        gta2::Vec3 eye{px + hx * ahead - hz * seat, baseY + eyeHeight, pz + hz * ahead + hx * seat};
        // FIX-FP-ENTRY (feel15, feel11): getting into or out of a car, the eye is the boarding plan's
        // head (the figure the chase view shows: to the door, held there while a driver is hauled out,
        // the climb; out over the sill, the turn and the shove that shuts the door), kept outside the
        // car's body until the game has him in the seat; from there it glides into the seat (below).
        // Before, it stood at the game's spot (in the lane, cars through the lens) and cut to the seat.
        BoardingEye ride;
        // (only a plan on the car he is at: a boarding that guessed a car in passing traffic drove off
        // with the eye, 4 blocks in a second, run fpentry_d)
        const bool riding = !inVehicle && !deathCam && BoardingPlayerEye(&ride) &&
                            std::hypot(ride.carX - px, ride.carZ - pz) < 1.5f && std::hypot(ride.x - px, ride.z - pz) < 1.2f;
        float rideCarX = 0.0f, rideCarZ = 0.0f;
        if (riding) {
            const float rhx = std::sin(ride.heading), rhz = std::cos(ride.heading);
            // the head ducks with the sink, but never below a seated head's height
            const float sinkEye = (std::min)(ride.sink, 0.16f);
            eye = {ride.x + rhx * 0.03f, ride.groundY + s.fpEyeFoot - sinkEye, ride.z + rhz * 0.03f};
            rideCarX = ride.carX; rideCarZ = ride.carZ;
            // outside the body he is boarding: 0.14 beyond (0.06 pressed the eye to the panel) the nearest side of its footprint
            if (CameraCarsOn()) {
                const CameraCar* best = nullptr;
                float bestD = 0.6f;
                for (const CameraCar& c : LiveCameraCars()) {
                    const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
                    const float d = std::hypot(cx - ride.carX, cz - ride.carZ);
                    if (d < bestD) { bestD = d; best = &c; }
                }
                if (best) {
                    constexpr float kRideClear = 0.14f;
                    const float depth = CarFootprintDepth(*best, eye.x, eye.z);
                    if (depth > -kRideClear) {
                        // out along the nearest edge's outward normal
                        float area = 0.0f;
                        for (int i = 0; i < 4; ++i) { const int j = (i + 1) & 3; area += best->x[i] * best->z[j] - best->x[j] * best->z[i]; }
                        const float wind = area >= 0.0f ? 1.0f : -1.0f;
                        float dmin = 1e9f, nx = 0.0f, nz = 0.0f;
                        for (int i = 0; i < 4; ++i) {
                            const int j = (i + 1) & 3;
                            const float ex = best->x[j] - best->x[i], ez = best->z[j] - best->z[i], el = std::hypot(ex, ez);
                            if (el < 1e-4f) continue;
                            const float d = wind * (ex * (eye.z - best->z[i]) - ez * (eye.x - best->x[i])) / el;
                            if (d < dmin) { dmin = d; nx = wind * ez / el; nz = -wind * ex / el; }   // outward
                        }
                        const float push = dmin + kRideClear;
                        const float ox = eye.x + nx * push, oz = eye.z + nz * push;
                        if (!(q.blocked && q.blocked(q.context, ox, eye.y, oz))) { eye.x = ox; eye.z = oz; }
                    }
                }
            }
        }
        if (riding != fpRiding_) {
            // onto the plan or off it: a short glide (0.35 s); in or out of the seat: below
            if (fpEyeKnown_ && inVehicle == lastFpInVehicle_) {
                fpGlideX_ = shownX_ - eye.x; fpGlideY_ = shownY_ - eye.y; fpGlideZ_ = shownZ_ - eye.z;
                fpGlideT_ = 0.0f; fpGlideDur_ = 0.35f;
                fpOffX_ = fpOffY_ = fpOffZ_ = 0.0f;
            }
            Log("view: fp ride %s (mode %d t %.2f)", riding ? "on" : "off", riding ? ride.mode : fpRideMode_, riding ? ride.t : 0.0f);
        }
        fpRiding_ = riding;
        fpRideMode_ = riding ? ride.mode : 0;
        // Out of a bin or a parking meter the game let him stand in (on leaving
        // a car at the kerb): a small step sideways, never through a wall.
        if (!inVehicle && q.propPush) {
            float ox = eye.x, oz = eye.z;
            if (q.propPush(q.context, eye.x, eye.y, eye.z, &ox, &oz) &&
                !(q.blocked && q.blocked(q.context, ox, eye.y, oz))) {
                eye.x = ox;
                eye.z = oz;
            }
        }
        // Nor at a lamp post or a phone box (QA3 qa_crash_10: a post a hand from the eye
        // drew a dark bar down a fifth of the frame; the game walks him through our posts,
        // which it does not know). The eye is kept 0.3 block from a post's axis and 0.1
        // clear of a game object's box, moved sideways round it (a continuous slide, no
        // jump), never into a wall.
        float fpPostDistance = 99.0f;
        if (!inVehicle) {
            static std::vector<Obstacle> fpObstacles;
            GatherObstacles(eye.x, eye.z, 1.5f, true, &fpObstacles);
            for (const Obstacle& o : fpObstacles) {
                if (o.post && eye.y >= o.y0 && eye.y <= o.y1) fpPostDistance = (std::min)(fpPostDistance, std::hypot(eye.x - o.x, eye.z - o.z));
            }
            for (int iter = 0; iter < 3; ++iter) {
                const Obstacle* o = ObstacleAt(fpObstacles, eye, 0.22f, true);
                float clear = 0.22f;
                if (!o || !o->post) {
                    const Obstacle* box = ObstacleAt(fpObstacles, eye, 0.10f, false);
                    if (box) { o = box; clear = 0.10f; }
                }
                if (!o) break;
                float ox = eye.x - o->x, oz = eye.z - o->z;
                float len = std::hypot(ox, oz);
                if (len < 1e-3f) { ox = -hx; oz = -hz; len = 1.0f; }
                const float rim = o->r + clear + 0.005f;
                const float nx = o->x + ox / len * rim, nz = o->z + oz / len * rim;
                if (q.blocked && q.blocked(q.context, nx, eye.y, nz)) break;
                eye.x = nx;
                eye.z = nz;
            }
        }
        // Nor a hand from the car he just left (QA3 qa_crash_10: the Truck Cab's exhaust
        // stack, 0.3 block from the eye, drew a dark bar down a sixth of the frame): the
        // eye keeps 0.3 block outside the body's box (CarBodiesExtent, remembered from
        // the wheel; a sedan's box for any other car), slid out sideways or lengthways,
        // whichever is shorter, never into a wall.
        if (!inVehicle) {
            float vx = 0.0f, vy = 0.0f, vd = 0.0f;
            bool driven = false;
            const void* vehicle = nullptr;
            const float gameY = static_cast<float>(gta2::kMapHeight) - eye.z;
            float fx = 0.0f, fy = 0.0f;
            if (NearestVehicle(eye.x, gameY, 3.0f, false, &vx, &vy, &vd, &driven, &vehicle) && vehicle &&
                VehicleFacing(vehicle, &fx, &fy)) {
                const bool known = vehicle == exitCar_ && exitCarHalfLength_ > 0.1f;
                const float hl = known ? exitCarHalfLength_ : 0.6f, hw = known ? exitCarHalfWidth_ : 0.3f;
                const float top = known ? exitCarHeight_ : 0.45f;
                constexpr float kCarClear = 0.3f;
                // Renderer frame: forward (fx, -fy) in x/z, side perpendicular.
                const float flen = std::hypot(fx, fy);
                if (flen > 1e-3f && eye.y < baseY + top + 0.15f) {
                    const float ax = fx / flen, az = -fy / flen;
                    const float cx = vx, cz = static_cast<float>(gta2::kMapHeight) - vy;
                    const float rx = eye.x - cx, rz = eye.z - cz;
                    float along = rx * ax + rz * az, side = -rx * az + rz * ax;
                    const float inAlong = hl + kCarClear - std::fabs(along), inSide = hw + kCarClear - std::fabs(side);
                    if (inAlong > 0.0f && inSide > 0.0f) {
                        float a2 = along, s2 = side;
                        if (inSide <= inAlong) s2 = (side >= 0.0f ? 1.0f : -1.0f) * (hw + kCarClear);
                        else a2 = (along >= 0.0f ? 1.0f : -1.0f) * (hl + kCarClear);
                        const float nx = cx + a2 * ax - s2 * az, nz = cz + a2 * az + s2 * ax;
                        if (!(q.blocked && q.blocked(q.context, nx, eye.y, nz))) {
                            eye.x = nx;
                            eye.z = nz;
                        }
                    }
                }
            }
        }
        // FIX-FIGURE-2: the eye's wall tests below ask `walled` (a solid side face the game
        // stops him at). `blocked` also counts any block with a lid, so under a deck or an
        // elevated walkway the eye's own block read as a wall 0.00 ahead and nothing moved
        // (run ff2_rail1: every frame "wall 0.00 ahead, eye stepped back 0.00").
        auto eyeWall = [&](float x, float y, float z) {
            return q.walled ? q.walled(q.context, x, y, z) : q.blocked(q.context, x, y, z);
        };
        // pm-fp-respawn-eye-pressed-into-facade (FIX-FIGURE-2): after a respawn the game
        // can leave him facing a facade a hand away; the screen was three magnified
        // windows until the player turned. On the first frame on foot after a jump, if a
        // wall is within half a block along his heading, the view sweeps (0.4 s) to the
        // longest free ray of the eight directions at eye height. With nav the view yaw
        // turns (he follows it when he walks); without, it is an offset to his heading the
        // view follows, released when he turns or walks off.
        if (fpRespawnPending_ > 0.0f) {
            fpRespawnPending_ -= dt;
            if (!inVehicle && q.blocked) {
                fpRespawnPending_ = 0.0f;
                auto freeRun = [&](float a, float maxLen) {
                    const float fx = std::sin(a), fz = std::cos(a);
                    for (float d = 0.05f; d <= maxLen; d += 0.05f)
                        if (eyeWall(eye.x + fx * d, eye.y, eye.z + fz * d)) return d - 0.05f;
                    return maxLen;
                };
                const float ahead = freeRun(headingYaw, 0.5f);
                if (ahead < 0.5f) {
                    float best = ahead, bestYaw = headingYaw;
                    for (int k = 1; k < 8; ++k) {
                        const float a = WrapAngle(headingYaw + static_cast<float>(k) * kPi / 4.0f);
                        const float run = freeRun(a, 4.0f);
                        if (run > best + 0.05f) { best = run; bestYaw = a; }
                    }
                    const float turn = WrapAngle(bestYaw - headingYaw);
                    if (std::fabs(turn) > 0.01f) {
                        fpRespawnLeft_ = turn;
                        fpRespawnRate_ = std::fabs(turn) / 0.4f;
                        fpRespawnOffset_ = 0.0f;
                        fpRespawnHeading_ = headingYaw;
                        Log("view: fp respawn: turned to open side: wall %.2f ahead, turn %.0f deg, free %.2f",
                            ahead, turn / kDegToRad, best);
                    }
                }
            }
        }
        if (inVehicle) fpRespawnLeft_ = fpRespawnOffset_ = 0.0f;
        if (fpRespawnLeft_ != 0.0f) {
            const float step = (std::min)(std::fabs(fpRespawnLeft_), fpRespawnRate_ * dt) * (fpRespawnLeft_ > 0.0f ? 1.0f : -1.0f);
            fpRespawnLeft_ -= step;
            if (std::fabs(fpRespawnLeft_) < 1e-4f) fpRespawnLeft_ = 0.0f;
            if (g_navActive) g_fpViewYaw = WrapAngle(g_fpViewYaw + step);
            else fpRespawnOffset_ += step;
        }
        if (fpRespawnOffset_ != 0.0f && (g_navActive || std::fabs(WrapAngle(headingYaw - fpRespawnHeading_)) > 3.0f * kDegToRad ||
                                         speed > 0.5f)) {
            fpRespawnOffset_ = fpRespawnLeft_ = 0.0f;
        }
        // The view heading lags the game's: a rate cap and a short ease, so an
        // about-face is a half-second sweep rather than a two-frame whirl. At
        // the wheel it also leans a little toward where the car is going.
        if (riding) {
            // FIX-FP-ENTRY: his head turns with the plan's figure (to the door, into the seat, out and round)
            const float omega = 2.0f / 0.18f;
            // out of the car the figure faces away from it; his eyes keep the door in view: part way
            // round toward the car while he climbs out, onto it while he shuts the door
            float target = WrapAngle(ride.heading);
            // FIX-CAMERA-12 (pfl48): out of the car the eye no longer rides the figure's turn (away from the car,
            // round to shut the door, back): with the eyes kept on the door that was a ~300 degree sweep along the
            // van's flank to its grille over 3 s while his facing stayed put. Out of the seat (modes 3 and 4) the
            // view keeps his facing, with at most a short glance (under 20 degrees) toward the door while he climbs
            // out. GTA2DX9_FP_EXIT_FACING=0: the ride's turn as before (A/B).
            static int exitFacing = -1;
            if (exitFacing < 0) { char b[8] = {}; exitFacing = GetEnvironmentVariableA("GTA2DX9_FP_EXIT_FACING", b, sizeof b) && atoi(b) == 0 ? 0 : 1;
                                  Log("view: fp exit %s (FIX-CAMERA-12 pfl48)", exitFacing ? "keeps his facing" : "rides the figure's turn (old)"); }
            if (ride.mode >= 3 && exitFacing) {
                const float toCar = std::atan2(ride.carX - eye.x, ride.carZ - eye.z);
                const float glance = (std::max)(-35.0f * kDegToRad, (std::min)(35.0f * kDegToRad, WrapAngle(toCar - headingYaw)));
                target = WrapAngle(headingYaw + glance * (ride.mode == 3 ? 0.5f : 0.0f));
            } else if (ride.mode >= 3) {
                const float toCar = std::atan2(ride.carX - eye.x, ride.carZ - eye.z);
                target = WrapAngle(target + WrapAngle(toCar - target) * (ride.mode == 3 ? 0.6f : 0.8f));
            }
            SpringTurn(&fpYaw_, &fpYawVel_, target, omega, 400.0f * kDegToRad, dt);
            g_fpViewYaw = fpYaw_;
            look.yaw = 0.0f;
        } else if (!inVehicle && g_navActive) {
            // The view is its own: the keys turn it (in the poll) and the mouse
            // adds to it; the pedestrian is steered to follow it, so what the
            // game does with his heading never swings the picture.
            g_fpViewYaw = WrapAngle(g_fpViewYaw + look.yaw);
            look.yaw = 0.0f;
            fpYaw_ = g_fpViewYaw;
            fpYawVel_ = 0.0f;
        } else {
            float target = WrapAngle(headingYaw + fpRespawnOffset_);
            if (inVehicle && speed > 1.5f) {
                const float vx = velX_ / speed, vz = velZ_ / speed;
                if (vx * hx + vz * hz > 0.2f) {
                    const float weight = (std::min)((speed - 1.5f) / 4.0f, 1.0f) * 0.25f;
                    target = WrapAngle(headingYaw + WrapAngle(std::atan2(vx, vz) - headingYaw) * weight);
                }
            }
            const float rate = (inVehicle ? s.fpCarRate : s.fpFollowRate) * ViewTurnSpeedScale() * kDegToRad;
            const float omega = 2.0f / (std::max)(s.fpSmooth, 0.02f);   // 120 ms: fixed to the car, eased
            SpringTurn(&fpYaw_, &fpYawVel_, target, omega, rate > 0.0f ? rate : 0.0f, dt);
            g_fpViewYaw = fpYaw_;
        }
        float yaw = WrapAngle(fpYaw_ + look.yaw);
        float pitch = look.pitch;
        {
            // FIX-FP-ENTRY: a glance down at the sill and the door while getting in or out, eased
            const float want = riding && ride.mode >= 2 ? -10.0f * kDegToRad : 0.0f;
            fpRidePitch_ += (want - fpRidePitch_) * (1.0f - std::exp(-dt / 0.2f));
            pitch += fpRidePitch_;
        }
        float roll = 0.0f;

        if (!inVehicle && s.fpHeadBob > 0.0f) {
            // A walking bob: one cycle per stride, about 0.35 of a block, that
            // grows with pace and dies away standing still.
            const float pace = (std::min)(speed / 3.0f, 1.0f);
            bobPhase_ += speed * dt / 0.35f;
            if (bobPhase_ > 1e4f) bobPhase_ -= 1e4f;
            const float amp = 0.022f * pace * s.fpHeadBob;
            eye.y += std::sin(bobPhase_ * 2.0f * kPi) * amp;
            const float sway = std::cos(bobPhase_ * kPi) * amp * 0.6f;
            eye.x += -hz * sway;   // sideways is the heading turned a quarter
            eye.z += hx * sway;
            roll += std::cos(bobPhase_ * kPi) * 0.6f * kDegToRad * pace * s.fpHeadBob;
        }
        // QB-49: nor a hand from a wall he walks into. The eye sits ahead of his centre, so
        // flush against a shop front it was at the bricks and one tile filled the frame. When
        // a wall is closer than kWallClear along the view, the eye steps back along it (up to
        // kWallBack, never into another wall behind).
        if (!inVehicle && q.blocked) {
            // pt-fp-wall-closeup-smear: 0.20/0.18 left the eye 0.2 block (40 cm) from the
            // bricks, one magnified tile filling the frame; 0.32 is an arm's length. The eye
            // may end up a little behind his centre: first person draws no body.
            constexpr float kWallClear = 0.32f, kWallBack = 0.28f;
            const float fx = std::sin(yaw), fz = std::cos(yaw);
            float wall = kWallClear;
            for (int i = 0; i <= 10; ++i) {
                const float d = kWallClear * static_cast<float>(i) / 10.0f;
                if (eyeWall(eye.x + fx * d, eye.y, eye.z + fz * d)) { wall = d; break; }
            }
            // FIX-OCCLUSION: and the drawn surface along the view, which the cells miss on a
            // diagonal wall or a partial block.
            if (eyecol::Ready()) {
                float t = 0.0f;
                if (eyecol::SegmentHit(eye, {eye.x + fx * kWallClear, eye.y, eye.z + fz * kWallClear}, &t))
                    wall = (std::min)(wall, t * kWallClear);
            }
            if (wall < kWallClear) {
                const float want = (std::min)(kWallClear - wall, kWallBack);
                // As far as the space behind allows: a full step, else two thirds, else a third.
                float back = 0.0f;
                for (const float part : {1.0f, 2.0f / 3.0f, 1.0f / 3.0f}) {
                    const float nx = eye.x - fx * want * part, nz = eye.z - fz * want * part;
                    if (!eyeWall(nx, eye.y, nz)) { eye.x = nx; eye.z = nz; back = want * part; break; }
                }
                static int wallLogs = 0;
                if (wallLogs < 20) { ++wallLogs; Log("view: fp eye: wall %.2f ahead, eye stepped back %.2f", wall, back); }
            }
        }
        // fp-eye-inside-railing (FIX-FIGURE-2): QB-49 asks `blocked`, which passes flat
        // panels by design, and the game lets him stand at a railing's tile edge, so with
        // the eye ahead of him and the head-bob sway the eye went 0.1 block from the
        // railing line and into its 3D bars (black and brown slabs cut by the near plane).
        // The eye keeps kPanelClear from every flat panel of its block and the blocks round
        // it, after the bob, so the sway cannot carry it through a bar.
        if (!inVehicle && q.panelPush) {
            constexpr float kPanelClear = 0.22f;
            float nx = eye.x, nz = eye.z;
            if (q.panelPush(q.context, eye.x, eye.y, eye.z, kPanelClear, &nx, &nz) &&
                !eyeWall(nx, eye.y, nz)) {
                static int panelLogs = 0;
                if (panelLogs < 20) {
                    ++panelLogs;
                    Log("view: fp eye: panel within %.2f, eye moved %.2f", kPanelClear, std::hypot(nx - eye.x, nz - eye.z));
                }
                eye.x = nx;
                eye.z = nz;
            }
        }
        // FIX-FP (pm3-fp-eye-inside-passing-car-black-blue-body): nor a hand from a car. The wall
        // solves above and the drawn-mesh clearance below know the map, not the traffic: walking
        // into a parked car or with one brushing past, the eye (ahead of his centre) went 0.1-0.3
        // block from the hull, which filled half the frame as a dark wall of paint. On foot the eye
        // keeps kCarClear from every car's footprint (LiveCameraCars, the chase camera's boxes, which
        // the 3D bodies overhang by up to a tenth of a block): pulled back toward his centre, then
        // straight out from the car if his centre itself is that close, never into a wall.
        if (!inVehicle && CameraCarsOn()) {
            constexpr float kCarClear = 0.30f;
            for (int pass = 0; pass < 2; ++pass) {
                for (const CameraCar& c : LiveCameraCars()) {
                    if (c.y0 > eye.y + 0.1f || c.y1 + 0.15f < eye.y) continue;   // under or over it
                    const float depth = CarFootprintDepth(c, eye.x, eye.z);
                    if (depth <= -kCarClear) continue;
                    if (CarFootprintDepth(c, px, pz) > -0.02f) continue;          // he is in it (boarding)
                    if (riding && std::hypot(0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]) - rideCarX,
                                             0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]) - rideCarZ) < 0.6f) continue;   // the one he boards
                    float nx = eye.x, nz = eye.z;
                    // back toward his centre, in eighths
                    bool clear = false;
                    for (int k = 1; k <= 8; ++k) {
                        const float t = static_cast<float>(k) / 8.0f;
                        const float tx = eye.x + (px - eye.x) * t, tz = eye.z + (pz - eye.z) * t;
                        nx = tx; nz = tz;
                        if (CarFootprintDepth(c, tx, tz) <= -kCarClear) { clear = true; break; }
                    }
                    if (!clear) {
                        // still too near at his centre: out from the car's middle by what is missing
                        const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
                        float dx = nx - cx, dz = nz - cz;
                        const float dl = std::hypot(dx, dz);
                        if (dl > 1e-4f) {
                            const float need = kCarClear + CarFootprintDepth(c, nx, nz);
                            nx += dx / dl * need; nz += dz / dl * need;
                        }
                    }
                    if (eyeWall(nx, eye.y, nz) || std::hypot(nx - eye.x, nz - eye.z) < 0.002f) continue;
                    static int carLogs = 0;
                    if (carLogs < 30) {
                        ++carLogs;
                        Log("view: fp eye: car %08x %.2f from the eye, eye moved %.2f (%s)", static_cast<unsigned>(c.object), -depth,
                            std::hypot(nx - eye.x, nz - eye.z), clear ? "back" : "out");
                    }
                    eye.x = nx; eye.z = nz;
                }
            }
        }
        // FIX-CAMERA-6 (pm43-bil-fp-respawn-at-hospital-eye-inside-ped-face-fills-frame): nor inside a figure.
        // After WASTED the first-person eye was put at the hospital door with a pedestrian standing there: his
        // face and shirt, cut by the near plane, filled the frame until he walked off. The tests above know the
        // map, the props and the cars, not the people. On foot the eye keeps kFigureClear (seen from above) from
        // every other figure drawn last frame, moved straight out from it (toward his own centre first, which a
        // figure overlapping him leaves behind the eye), never into a wall; a move over a quarter block glides
        // (the glide below). The renderer also leaves a figure at the lens undrawn (live_geometry.cpp).
        if (!inVehicle) {
            constexpr float kFigureClear = 0.30f;   // about 1.2 m (a block is about 3.9 m: an adult is 0.46)
            float fx = 0.0f, fy = 0.0f, fz = 0.0f, fd = 99.0f;
            for (int pass = 0; pass < 2; ++pass) {
                if (!NearestFigureSpot(eye.x, eye.y, eye.z, px, pz, &fx, &fy, &fz, &fd) || fd >= kFigureClear) break;
                float ox = eye.x - fx, oz = eye.z - fz;
                float ol = std::hypot(ox, oz);
                if (ol < 1e-3f) { ox = -hx; oz = -hz; ol = 1.0f; }
                const float nx = fx + ox / ol * kFigureClear, nz = fz + oz / ol * kFigureClear;
                // Not further than half a block from his centre, never into a wall or the drawn mesh.
                if (std::hypot(nx - px, nz - pz) > 0.4f || eyeWall(nx, eye.y, nz)) break;
                float t = 1.0f;
                if (eyecol::Ready() && eyecol::SegmentHit({px, eye.y, pz}, {nx, eye.y, nz}, &t)) break;
                static int figureLogs = 0;
                if (figureLogs < 40) {
                    ++figureLogs;
                    Log("view: fp eye: figure %.2f from the eye, eye moved %.2f%s", fd, std::hypot(nx - eye.x, nz - eye.z),
                        fpRespawnLeft_ != 0.0f || fpRespawnPending_ > 0.0f ? " (respawn)" : "");
                }
                eye.x = nx; eye.z = nz;
            }
        }
        float dbgBody = 0.0f, dbgLean = 0.0f, dbgShake = 0.0f;   // FIX-CAMERA-9: the in-car eye pitch's parts, for the log
        if (inVehicle && s.fpBodyRide > 0.0f) {
            // FIX-VEHICLES: the eye sits in the sprung body: it dips with the nose
            // under braking, tips back on a launch, leans with the roll and rises and
            // falls with the heave, by the share the cockpit is drawn with.
            const float ride = (std::min)(s.fpBodyRide, 1.0f);
            pitch -= carPitch_ * ride;   // the body's pitch is nose down +, the camera's down -
            dbgBody = -carPitch_ * ride;
            roll -= carRoll_ * ride;     // the body's roll is left side down +, the camera's leaning right +
            eye.y += carHeave_ * ride;
        }
        if (inVehicle && FpSeatGlideOn()) {
            // FIX-FP-ENTRY (pfeel32): the body's whole pose (a kerb's tilt included), measured by car_bodies
            // against last frame's raw eye (see FirstPersonSeatEyeRaw), eased in over a few frames.
            g_fpSeat.valid = true; g_fpSeat.raw = eye; g_fpSeat.rawAt = Now();
            gta2::Vec3 want{0.0f, 0.0f, 0.0f};
            if (Now() - g_fpSeat.deltaAt < 0.2) want = g_fpSeat.delta;
            const float k = 1.0f - std::exp(-dt / 0.05f);
            fpSeatFix_.x += (want.x - fpSeatFix_.x) * k; fpSeatFix_.y += (want.y - fpSeatFix_.y) * k; fpSeatFix_.z += (want.z - fpSeatFix_.z) * k;
            eye.x += fpSeatFix_.x; eye.y += fpSeatFix_.y; eye.z += fpSeatFix_.z;
        } else {
            g_fpSeat.valid = false;
            fpSeatFix_ = {0.0f, 0.0f, 0.0f};
        }
        // FIX-COCKPIT-BODY (owner item 3): the dashcam: a camera on the windscreen, higher, further forward and
        // toward the car's middle than the driver's eye (after the seat lock, which holds the driver's eye), eased
        // over the switch (cockpit_mode.h); no head lean and no body roll in it (a level horizon).
        const float dashcam = inVehicle ? DashcamBlend() : 0.0f;
        if (dashcam > 0.0f) {
            float dUp = 0.0f, dAhead = 0.0f, dCentre = 0.0f;
            DashcamOffsets(&dUp, &dAhead, &dCentre);
            // (-hz, hx) is the car's left, where `seat` put the eye: back toward the middle by dCentre of it
            eye.x += (hx * dAhead + hz * seat * dCentre) * dashcam;
            eye.z += (hz * dAhead - hx * seat * dCentre) * dashcam;
            eye.y += dUp * dashcam;
            if (s.fpBodyRide > 0.0f) roll += carRoll_ * (std::min)(s.fpBodyRide, 1.0f) * dashcam;   // the body's roll out
        }
        if (inVehicle && s.fpLean > 0.0f) {
            // The nose dips under braking and lifts under power; the head leans
            // into a turn.
            dbgLean = (std::max)((std::min)(forwardAccel_ / 25.0f, 1.0f), -1.0f) * 2.5f * kDegToRad * s.fpLean * (1.0f - dashcam);
            pitch += dbgLean;
            yawRate_ += (fpYawVel_ - yawRate_) * (1.0f - std::exp(-dt / 0.15f));
            roll += (std::max)((std::min)(yawRate_ * speedFrac_ * 0.5f, 1.0f), -1.0f) * 3.0f * kDegToRad * s.fpLean * (1.0f - dashcam);
        }
        lastYaw_ = fpYaw_;
        followYaw_ = fpYaw_;   // so a switch to the chase view starts from where the eyes look
        followYawVel_ = fpYawVel_;

        // Down on the ground (knocked over, dead, arrested): the eye sinks to
        // the road and the head tips onto its side, eased in over half a second
        // and out again when he gets up. (The chase view shows the body instead.)
        if (deathMix_ > 0.0f) {
            eye.y += (baseY + 0.10f - eye.y) * deathMix_;
            roll += 35.0f * kDegToRad * deathMix_;
            pitch += (8.0f * kDegToRad - pitch) * deathMix_;
        }
        // FIX-KNOCKDOWN (owner item 1): knocked down by a car or a blast (the game stands him up after
        // 0.37 s, far too soon for the death camera above): the eye rides his head through the fall, lies
        // with it, the head tipped and the gaze up at the sky on his back or down at the road on his front,
        // and rises with the get-up.
        KnockdownEye kde;
        if (!inVehicle && deathMix_ < 0.5f && KnockdownPlayerEye(&kde)) {
            const float w = kde.weight;
            eye.x += (kde.x - eye.x) * w;
            eye.y += (kde.y + 0.03f - eye.y) * w;
            eye.z += (kde.z - eye.z) * w;
            const float standEye = kde.groundY + eyeHeight;
            const float low = w * (std::min)(1.0f, (std::max)(0.0f, (standEye - kde.y) / (std::max)(0.1f, eyeHeight - 0.08f)));
            roll += 25.0f * kDegToRad * low;
            // FIX-KNOCKDOWN-2 (kd2_f1): the gaze follows the chest eased (0.25 s): the played roll turns the chest from
            // up to down fastest at its middle, and the view swung from the sky to the road in 6 frames (0.2 s).
            static float gaze = 0.0f;
            static ULONGLONG gazeTick = 0;
            static const bool gazeEase = [] { char b[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_KD_GAZE_EASE", b, sizeof b) && b[0] == '0'); }();
            {
                const ULONGLONG now = GetTickCount64();
                const float c = (std::max)(-1.0f, (std::min)(1.0f, kde.chestUp));
                const float gdt = gazeTick ? (std::min)(0.1f, static_cast<float>(now - gazeTick) / 1000.0f) : 0.0f;
                if (!gazeEase || !gazeTick || now - gazeTick > 300) gaze = c;   // a new knock-down starts where the chest is
                else gaze += (c - gaze) * (std::min)(1.0f, gdt / 0.25f);
                gazeTick = now;
            }
            pitch += ((3.0f + 35.0f * gaze) * kDegToRad - pitch) * low;   // up at the sky .. down at the road
            static ULONGLONG lastLog = 0;
            if (GetTickCount64() - lastLog > 250) {
                lastLog = GetTickCount64();
                Log("view: fp knockdown eye w=%.2f low=%.2f head y=%.2f (ground %.2f) %s", w, low, kde.y, kde.groundY, kde.faceUp ? "on his back" : "on his front");
            }
        }
        // The kick of an impact, and the stretch of speed.
        if (shake_ > 0.001f) {
            // FIX-CAMERA-9 (pfl25-fp-car-collision-cockpit-dives-...): at the wheel the cockpit (dash, wheel, hands)
            // is drawn with the car's body and does not take the shake, so the shake moves it about the frame. At a
            // wall the shake saturates at 1.5 (2.5/2.0/2.0 degrees a unit: 3.75 of yaw and 3 of pitch, the hands and
            // the wheel sliding off the frame with the body's own dip on top): in a car it is a shudder of at most
            // 1.2 degrees of yaw, 1.5 of pitch and 2 of roll, dying with the shake (GTA2DX9_FP_CAR_SHAKE=0: as before).
            static int fpCarShake = -1;
            if (fpCarShake < 0) { char b[8] = {}; fpCarShake = GetEnvironmentVariableA("GTA2DX9_FP_CAR_SHAKE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            const bool soft = inVehicle && fpCarShake;
            const float k = soft ? (std::min)(shake_, 1.0f) : shake_;
            yaw += Wobble(shakeClock_, 7.0f) * (soft ? 1.2f : 2.5f) * kDegToRad * k;
            dbgShake = Wobble(shakeClock_ + 3.1, 9.0f) * (soft ? 1.5f : 2.0f) * kDegToRad * k;
            pitch += dbgShake;
            roll += Wobble(shakeClock_ + 7.7, 5.0f) * 2.0f * kDegToRad * k;
        }
        pitch = (std::min)((std::max)(pitch, -80.0f * kDegToRad), 80.0f * kDegToRad);
        const float fov = (std::min)((std::max)(s.fpFov, 30.0f), 120.0f) + s.speedFov * speedFrac_;

        // A discontinuity of the eye that is not a cut - into the driver's seat,
        // out of it, thrown by a blast, back from the death camera - is a glide:
        // the eye keeps where it was shown and the difference dies away over a
        // quarter of a second. Ordinary motion (the predicted step) never is.
        {
            if (fpEyeKnown_) {
                const float ex = fpRawX_ + velX_ * dt, ez = fpRawZ_ + velZ_ * dt;
                const float off = std::sqrt((eye.x - ex) * (eye.x - ex) + (eye.y - fpRawY_) * (eye.y - fpRawY_) + (eye.z - ez) * (eye.z - ez));
                if (inVehicle != lastFpInVehicle_ && off < 6.0f && FpSeatGlideOn()) {
                    // FIX-FP-ENTRY: into the seat (from the door, where the ride left the eye) over 0.6 s,
                    // out of it over 0.5 s, eased at both ends; the old 0.12 s decay read as a cut.
                    fpGlideX_ = shownX_ - eye.x; fpGlideY_ = shownY_ - eye.y; fpGlideZ_ = shownZ_ - eye.z;
                    fpGlideT_ = 0.0f; fpGlideDur_ = inVehicle ? 0.6f : 0.5f;
                    // a long way (a hand-over far from where he was shown): no frame steps more than ~0.25 block
                    fpGlideDur_ = (std::max)(fpGlideDur_, off * 1.5f / (0.25f * 30.0f));
                    fpOffX_ = fpOffY_ = fpOffZ_ = 0.0f;
                    Log("view: fp seat glide %s %.2f blocks over %.1f s", inVehicle ? "in" : "out", off, fpGlideDur_);
                } else if (fpGlideDur_ > 0.0f && off > 0.03f && off < 1.0f && inVehicle == lastFpInVehicle_) {
                    // a late step of the seat's own eye (the cab measured a frame or two after the hand-over):
                    // absorbed into the glide, which keeps the eye where it is shown
                    const float left = 1.0f - Smooth01(fpGlideT_ / fpGlideDur_);
                    const float jx = shownX_ - eye.x - fpOffX_, jy = shownY_ - eye.y - fpOffY_, jz = shownZ_ - eye.z - fpOffZ_;
                    if (left > 0.25f) { fpGlideX_ = jx / left; fpGlideY_ = jy / left; fpGlideZ_ = jz / left; }
                    else { fpGlideX_ = jx; fpGlideY_ = jy; fpGlideZ_ = jz; fpGlideT_ = 0.0f; fpGlideDur_ = 0.3f; }
                } else if ((inVehicle != lastFpInVehicle_ || off > 0.25f) && off < 6.0f) {
                    fpOffX_ = shownX_ - eye.x - fpGlideX_ * (fpGlideDur_ > 0.0f ? 1.0f - Smooth01(fpGlideT_ / fpGlideDur_) : 0.0f);
                    fpOffY_ = shownY_ - eye.y - fpGlideY_ * (fpGlideDur_ > 0.0f ? 1.0f - Smooth01(fpGlideT_ / fpGlideDur_) : 0.0f);
                    fpOffZ_ = shownZ_ - eye.z - fpGlideZ_ * (fpGlideDur_ > 0.0f ? 1.0f - Smooth01(fpGlideT_ / fpGlideDur_) : 0.0f);
                }
            }
            fpRawX_ = eye.x; fpRawY_ = eye.y; fpRawZ_ = eye.z;
            fpEyeKnown_ = true;
            lastFpInVehicle_ = inVehicle;
            const float k = std::exp(-dt / 0.12f);
            fpOffX_ *= k; fpOffY_ *= k; fpOffZ_ *= k;
            if (fpGlideDur_ > 0.0f) {
                fpGlideT_ += dt;
                if (fpGlideT_ >= fpGlideDur_) {
                    fpGlideDur_ = 0.0f;
                    fpGlideX_ = fpGlideY_ = fpGlideZ_ = 0.0f;
                }
            }
            const float glideLeft = fpGlideDur_ > 0.0f ? 1.0f - Smooth01(fpGlideT_ / fpGlideDur_) : 0.0f;
            // (the glide is carried in fpOff for the wall test below, then taken out again)
            const float gX = fpGlideX_ * glideLeft, gY = fpGlideY_ * glideLeft, gZ = fpGlideZ_ * glideLeft;
            fpOffX_ += gX; fpOffY_ += gY; fpOffZ_ += gZ;
            const float preX = fpOffX_, preY = fpOffY_, preZ = fpOffZ_;
            gta2::Vec3 shown{eye.x + fpOffX_, eye.y + fpOffY_, eye.z + fpOffZ_};
            // The glide must not pass through a wall: from the seat out to where it is shown.
            if (q.blocked && (std::fabs(fpOffX_) + std::fabs(fpOffY_) + std::fabs(fpOffZ_)) > 0.02f) {
                for (int i = 1; i <= 8; ++i) {
                    const float t = static_cast<float>(i) / 8.0f;
                    if (q.blocked(q.context, eye.x + fpOffX_ * t, eye.y + fpOffY_ * t, eye.z + fpOffZ_ * t)) {
                        const float keep = static_cast<float>(i - 1) / 8.0f;
                        fpOffX_ *= keep; fpOffY_ *= keep; fpOffZ_ *= keep;
                        shown = {eye.x + fpOffX_, eye.y + fpOffY_, eye.z + fpOffZ_};
                        break;
                    }
                }
            }
            {
                // the glide's share back out of the decaying offset, as far as the wall test let it go
                const float pre = std::fabs(preX) + std::fabs(preY) + std::fabs(preZ);
                const float r = pre > 1e-5f ? (std::fabs(fpOffX_) + std::fabs(fpOffY_) + std::fabs(fpOffZ_)) / pre : 1.0f;
                fpOffX_ -= gX * r; fpOffY_ -= gY * r; fpOffZ_ -= gZ * r;
                if (r < 0.999f) { fpGlideX_ *= r; fpGlideY_ *= r; fpGlideZ_ *= r; }
            }
            eye = shown;
            // BLOCKER fp-camera-sees-through-wall (FIX-OCCLUSION): the tests above ask the map's
            // cells, which do not see a diagonal wall, a partial block or any face off a cell
            // edge. At the chamfered church corner in wil the eye went to 0.03 of the bricks,
            // the 0.05 near plane cut the wall open and the frame was the inside of the block
            // (backfaces, a black void, sky) for three seconds. Last of all, against the mesh
            // that is drawn: from his centre at eye height the eye goes no further than a
            // surface on the way, and keeps a sphere's clearance from every surface round it
            // (0.24 on foot, a hand; 0.12 in a car's cabin, the near plane's reach), slid along
            // it, not stopped.
            if (eyecol::Ready()) {
                const gta2::Vec3 head{px, eye.y, pz};
                const float moved = eyecol::Clear(head, &eye, inVehicle ? 0.12f : 0.24f);
                if (moved > 0.0f) {
                    static int clearLogs = 0;
                    if (clearLogs < 40) {
                        ++clearLogs;
                        Log("view: fp eye: surface clearance moved the eye %.3f (near %.3f after)", moved,
                            eyecol::Nearest(eye, 1.0f));
                    }
                }
            }
            shownX_ = eye.x; shownY_ = eye.y; shownZ_ = eye.z;
            lastPitch_ = pitch;
            lastPitchKnown_ = true;
        }

        camera->SetPosition(eye);
        camera->SetOrientation(yaw, pitch);
        camera->SetRoll(roll);
        camera->SetFovY((std::min)(fov, 140.0f) * kDegToRad);
        LogCameraFrame("first", yaw, headingYaw, dt, &eye, px, pz, eyeHeight);
        if (inVehicle && cameraLogOn())
            Log("cam: fp car pitch=%.1f body=%.1f lean=%.1f shake=%.1f (%.2f) roll=%.1f heave=%.3f seatfix=%.3f,%.3f,%.3f", pitch / kDegToRad,
                dbgBody / kDegToRad, dbgLean / kDegToRad, dbgShake / kDegToRad, shake_, roll / kDegToRad, carHeave_, fpSeatFix_.x, fpSeatFix_.y,
                fpSeatFix_.z);
        {
            // Once a second: where the eye is against the floor under him, for the log.
            static float logClock = 0.0f;
            logClock += dt;
            if (logClock > 1.0f) {
                logClock = 0.0f;
                float under = 0.0f;
                const bool hasUnder = q.floorAt && q.floorAt(q.context, eye.x, eye.z, eye.y + 0.75f, &under);
                const eyecol::Stats cs = eyecol::TakeStats();
                Log("view: fp eye %.2f,%.2f,%.2f  player y=%.2f floor=%.2f  lid under the eye=%s%.2f  post %.2f  surface %.3f"
                    "  (clear: %d moves, max %.3f, %d segment stops, caps %d)",
                    eye.x, eye.y, eye.z, py, floorY_, hasUnder ? "" : "none ", under, fpPostDistance,
                    eyecol::Nearest(eye, 2.0f), cs.pushes, cs.maxPush, cs.segmentStops, cs.capTris);
            }
        }
        eyeX_ = eye.x;
        eyeY_ = eye.y;
        eyeZ_ = eye.z;
        roll_ = roll;
        yawDegrees = yaw / kDegToRad;
        pitchDegrees = pitch / kDegToRad;
        g_navCamYaw = fpYaw_;
        g_navHeading = headingYaw;
        g_navInVehicle = inVehicle;
        g_navHeadingKnown = player.facingKnown;
        boomKnown_ = false;   // third person starts its boom afresh from where the eye is
        shownPoseKnown_ = false;
        snapEye_ = false;
        status_ = inVehicle ? "first person, at the wheel" : (g_navActive ? "first person, on foot (keys turn the view)" : "first person, on foot");
        return;
    }

    // --- Third person -----------------------------------------------------
    // The camera's own yaw eases round behind the player, so a turn swings the
    // view over a few tenths of a second rather than snapping; quicker at speed,
    // where a camera that dawdles loses the road.
    // A critically damped spring, quicker at speed, and never faster than the
    // turn rate: the player turns on the spot in the game, the camera swings
    // round behind him over a few tenths of a second.
    lastDeathCam_ = deathCam;
    float orbitYaw;
    if (!inVehicle) {
        // An orbit camera: the mouse turns it directly, the player turns inside
        // the frame, and only the direction he walks in draws it slowly round
        // behind him. It never spins with his heading.
        // A mouse movement takes the yaw over at once: whatever swing the follow had
        // under way stops, so it never drifts on against the hand (it waits
        // tpReturnDelay after the last movement, then starts again from rest).
        if (look.yaw != 0.0f) followYawVel_ = 0.0f;
        followYaw_ = WrapAngle(followYaw_ + look.yaw);
        g_navLookYaw = WrapAngle(g_navLookYaw + look.yaw);   // the arrows' reference turns with an explicit look
        look.yaw = 0.0f;
        // Over the body the death camera turns slowly round him.
        followYaw_ = WrapAngle(followYaw_ + 6.0f * kDegToRad * dt * deathMix_);
        const float scale = ViewTurnSpeedScale();
        const bool walking = speed > 0.6f;
        const float walkYaw = walking ? std::atan2(velX_, velZ_) : followYaw_;
        // QB-6: firing, the camera swings round behind the way he faces (the way the
        // game's bullets fly) on a quick spring, so the line of fire runs into the
        // picture and the reticle sits near its middle; the mouse still overrides it.
        const bool aimRecentMouse = look.lastMoved > 0.0 && Now() - look.lastMoved < s.tpReturnDelay;
        const bool aimFollow = g_aim.aimMix > 0.5f && !aimRecentMouse && downTime_ <= 0.0f && deathMix_ < 0.01f;
        if (aimFollow) {
            // FIX-CAMERA-11 (pfl37-third-pistol-shot-at-passing-ped-camera-whips-100deg-in-0p3s): the catch-up
            // when he fires facing well off the camera (turned on the spot, the game's lock-on turned him) was a
            // 0.15 s spring at 240 deg/s: a 100 degree whip in 0.3 s, the eased eye cutting the chord past him
            // (a passer-by's head at the lens) and the shown view trailing until he left the frame. Now an eased
            // follow: at most 110 deg/s (33 in any 0.3 s), reached over a quarter second (no jerk at the shot),
            // settling in about a second. GTA2DX9_CAM_AIM_RATE=0 restores the old spring (A/B).
            static int aimRateOn = -1;
            if (aimRateOn < 0) {
                char buf[16] = {};
                aimRateOn = GetEnvironmentVariableA("GTA2DX9_CAM_AIM_RATE", buf, sizeof buf) && atoi(buf) == 0 ? 0 : 1;
            }
            const float rate = 2.0f * s.turnRateFoot * scale * kDegToRad;
            if (aimRateOn) {
                const float capRate = (std::min)(rate > 0.0f ? rate : 0.0f, 110.0f * kDegToRad);
                const float velBefore = followYawVel_;
                const float yawBefore = followYaw_;
                SpringTurn(&followYaw_, &followYawVel_, headingYaw, 2.0f / 0.45f, capRate, dt);
                const float maxDv = 440.0f * kDegToRad * (std::min)(dt > 0.0f ? dt : 1.0f / 30.0f, 1.0f / 30.0f);
                if (std::fabs(followYawVel_ - velBefore) > maxDv) {
                    // Accelerate no faster than 440 deg/s^2: redo the step with the bounded velocity.
                    followYawVel_ = velBefore + (followYawVel_ > velBefore ? maxDv : -maxDv);
                    const float err = WrapAngle(headingYaw - yawBefore);
                    float step = followYawVel_ * (std::min)(dt, 1.0f / 30.0f);
                    if ((err > 0.0f && step > err) || (err < 0.0f && step < err)) { step = err; followYawVel_ = 0.0f; }
                    followYaw_ = WrapAngle(yawBefore + step);
                }
                static double aimLogT = -1.0;
                const float errNow = WrapAngle(headingYaw - followYaw_);
                if (cameraLogOn() && std::fabs(errNow) > 20.0f * kDegToRad && (aimLogT < 0.0 || Now() - aimLogT > 0.5)) {
                    aimLogT = Now();
                    Log("cam: aim follow %.1f deg off his facing, turning %.0f deg/s", errNow / kDegToRad, followYawVel_ / kDegToRad);
                }
            } else {
                SpringTurn(&followYaw_, &followYawVel_, headingYaw, 2.0f / 0.3f, rate > 0.0f ? rate : 0.0f, dt);
            }
            footFollowing_ = false;
            engageTime_ = 0.0f;
            awayTime_ = 0.0f;
        } else if (s.tpOrbitFollow) {
            // Drift round behind whichever way he walks.
            const float rate = s.turnRateFoot * scale * kDegToRad;
            SpringTurn(&followYaw_, &followYawVel_, walkYaw, 2.0f / (std::max)(s.tpOrbitTau, 0.1f), rate > 0.0f ? rate : 0.0f, dt);
            awayTime_ = 0.0f;
        } else if (s.tpFollowTauWalk > 0.0f) {
            // Soft follow, as GTA V's camera on foot: while he walks the yaw eases
            // round behind the way he goes; a key pressed while he stands turns him
            // and the camera follows his facing. Each turn is followed only after
            // tpFollowDelay (so a tap or a step does not stir the picture), on a
            // critically damped spring (no overshoot) with a time constant from
            // tpFollowTauWalk at a walk to tpFollowTauRun at a run, capped at
            // turnRateFoot. Standing with no key held for a moment, it holds.
            awayTime_ = 0.0f;
            const bool keysHeld = g_navActive && (g_phys[0] || g_phys[1] || g_phys[2] || g_phys[3]);
            keyAge_ = keysHeld ? 0.0f : keyAge_ + dt;
            // What is followed is his facing (the game's heading; the spring and the
            // delay smooth its snaps and the controller's pulses), not the way he
            // moves: a car shoving him, a wall he slides along, being knocked down
            // (ped state 8/9) never swing the camera. Moving more than 100 degrees
            // off his facing is being pushed, not walking.
            const bool down = downTime_ > 0.0f;
            const bool pushed = walking && std::fabs(WrapAngle(walkYaw - headingYaw)) > 100.0f * kDegToRad;
            // A key pressed (or let go under a second ago: a tap that turned him
            // where he stands) or walking his own way is a wish to turn.
            const bool intent = !down && !pushed && (walking || keysHeld || keyAge_ < 1.0f);
            idleTime_ = intent ? 0.0f : idleTime_ + dt;
            float target = headingYaw;
            float err = WrapAngle(target - followYaw_);
            // Nearly about-face (he turned to walk toward the camera): keep turning
            // the way it already turns, so noise about 180 degrees cannot flip it.
            if (std::fabs(err) > 150.0f * kDegToRad && followYawVel_ * err < 0.0f) {
                err = (followYawVel_ > 0.0f ? 1.0f : -1.0f) * 150.0f * kDegToRad;
                target = WrapAngle(followYaw_ + err);
            }
            // A new episode (a press, a step off after standing) waits the delay.
            if (!footFollowing_) {
                if (intent && std::fabs(err) > 2.0f * kDegToRad) {
                    engageTime_ += dt;
                    if (engageTime_ >= (std::max)(s.tpFollowDelay, 0.0f)) footFollowing_ = true;
                } else {
                    engageTime_ = 0.0f;
                }
            }
            // A turn begun by a key is finished after the key is let go (he stands
            // facing his new way, the camera settles behind him); then it holds.
            // A bump or a shove, with no key, never starts one.
            if (footFollowing_ && !intent &&
                (idleTime_ > 2.5f || (std::fabs(err) < 1.0f * kDegToRad && std::fabs(followYawVel_) < 2.0f * kDegToRad))) {
                footFollowing_ = false;
                engageTime_ = 0.0f;
            }
            // The mouse is the player's: no follow until tpReturnDelay after it last moved.
            const bool mouseRecent = look.lastMoved > 0.0 && Now() - look.lastMoved < s.tpReturnDelay;
            if (footFollowing_ && !mouseRecent && !down && !pushed && deathMix_ < 0.01f) {
                const float runSpeed = 2.6f, walkSpeed = 0.8f;   // blocks a second (GTA2 on foot runs at about 2.6)
                const float k = (std::min)((std::max)((speed - walkSpeed) / (runSpeed - walkSpeed), 0.0f), 1.0f);
                const float tauWalk = (std::max)(s.tpFollowTauWalk, 0.1f);
                const float tauRun = s.tpFollowTauRun > 0.0f ? (std::max)(s.tpFollowTauRun, 0.1f) : tauWalk;
                const float tau = tauWalk + (tauRun - tauWalk) * k;
                const float rate = s.turnRateFoot * scale * kDegToRad;
                SpringTurn(&followYaw_, &followYawVel_, target, 2.0f / tau, rate > 0.0f ? rate : 0.0f, dt);
            } else {
                // Holding: whatever turn was under way dies away over a fifth of a
                // second rather than stopping dead.
                followYawVel_ *= std::exp(-dt / 0.2f);
                if (std::fabs(followYawVel_) < 0.5f * kDegToRad) followYawVel_ = 0.0f;
                followYaw_ = WrapAngle(followYaw_ + followYawVel_ * (std::min)(dt, 1.0f / 30.0f));
            }
            LogFootFollow(followYaw_, target, headingYaw, walkYaw, speed, footFollowing_, keysHeld, engageTime_);
        } else {
            // Hold the yaw: he walks toward, away from or across the frame and
            // nothing turns by itself. Only after he has walked straight away
            // from the camera for a while does it ease round behind him, slowly.
            const bool away = walking && std::fabs(WrapAngle(walkYaw - followYaw_)) < 30.0f * kDegToRad;
            awayTime_ = away ? awayTime_ + dt : 0.0f;
            if (away && awayTime_ > s.tpRecentreDelay) {
                const float rate = s.tpRecentreRate * scale * kDegToRad;
                SpringTurn(&followYaw_, &followYawVel_, walkYaw, 2.0f / (std::max)(s.tpRecentreTau, 0.1f), rate > 0.0f ? rate : 0.0f, dt);
            } else {
                followYawVel_ = 0.0f;
            }
        }
        orbitYaw = followYaw_;
    } else {
        // The chase camera: heavily damped, aligned with where the car is going.
        const float rate = s.turnRateCar * ViewTurnSpeedScale() * kDegToRad;
        awayTime_ = 0.0f;
        engageTime_ = 0.0f;
        footFollowing_ = false;
        SpringTurn(&followYaw_, &followYawVel_, chaseYaw, 2.0f / (std::max)(s.tpChaseTau, 0.1f), rate > 0.0f ? rate : 0.0f, dt);
        orbitYaw = WrapAngle(followYaw_ + look.yaw);
    }
    lastYaw_ = followYaw_;
    fpYaw_ = followYaw_;   // a switch to first person starts from the camera's heading
    fpYawVel_ = followYawVel_;
    g_fpViewYaw = followYaw_;
    yawRate_ += (followYawVel_ - yawRate_) * (1.0f - std::exp(-dt / 0.12f));
    const float yaw = orbitYaw;
    const float orbitPitch = (std::min)((std::max)(look.pitch, -20.0f * kDegToRad), 70.0f * kDegToRad);

    const float scale = inVehicle ? 1.0f : (std::max)(s.tpFootScale, 0.2f);
    // A long or tall vehicle (fire truck, bus, truck, tank, train cab) is framed
    // from its own body, which the car bodies know (CarBodiesExtent: length and
    // full height in blocks): the camera stands back by the part of the length a
    // sedan does not have and by the extra height, rises with the height, and
    // looks at a point as much higher and further ahead, so the whole vehicle is
    // in the frame from the first frame at the wheel. A sedan (about a block long,
    // under 0.45 tall) gets no extra at all: its framing is the one tuned before.
    // The extras are eased, so a body that becomes known a frame late never pops.
    {
        float extraLength = 0.0f, extraHeight = 0.0f, bodyHeight = 0.0f;
        float length = 0.0f, height = 0.0f, halfWidth = 0.0f;
        if (inVehicle && CarBodiesExtent(player.vehicleSprite, &length, &height, &halfWidth)) {
            exitCar_ = player.vehicle;
            exitCarHalfLength_ = 0.5f * length;
            exitCarHalfWidth_ = halfWidth;
            exitCarHeight_ = height;
            extraLength = (std::max)(0.0f, length - 1.2f);
            extraHeight = (std::max)(0.0f, height - 0.45f);
            bodyHeight = height;
        }
        if (!framingKnown_) {
            extraLength_ = extraLength;
            extraHeight_ = extraHeight;
            bodyHeight_ = bodyHeight;
            framingKnown_ = true;
        } else {
            const float k = 1.0f - std::exp(-dt / 0.4f);
            extraLength_ += (extraLength - extraLength_) * k;
            extraHeight_ += (extraHeight - extraHeight_) * k;
            bodyHeight_ += (bodyHeight - bodyHeight_) * k;
        }
    }
    float distance = ((std::max)(s.tpDistance, 0.5f) + s.tpPullBack * speedFrac_) * scale + 0.5f * extraLength_ + 1.0f * extraHeight_;
    float height = (s.tpHeight + 0.25f * s.tpPullBack * speedFrac_) * scale + 0.8f * extraHeight_ + 0.1f * extraLength_;
    float lookAhead = (s.tpLookAhead + 0.8f * speedFrac_) * scale + 0.5f * extraLength_;
    float lookHeight = s.tpLookHeight * scale + 0.5f * extraHeight_;
    float chaseFovExtra = s.speedFov * speedFrac_;
    gta2::Vec3 turnLead{0.0f, 0.0f, 0.0f};
    if (inVehicle) {
        // QUALITY-BAR row 22 (chase:: above). The body's size: the one known from the
        // car bodies, else a sedan's.
        const bool body = exitCar_ == player.vehicle && exitCarHalfWidth_ > 0.05f && exitCarHalfLength_ > 0.1f;
        const float halfW = body ? exitCarHalfWidth_ : 0.32f;
        const float halfL = body ? exitCarHalfLength_ : 0.6f;
        const float tall = body ? (std::max)(exitCarHeight_, 0.3f) : 0.45f;
        const float fov0 = (std::min)((std::max)(s.tpFov, 20.0f), 110.0f);
        const float tanH = std::tan(0.5f * fov0 * kDegToRad) * (16.0f / 9.0f);
        // From the rear bumper, back by as much as puts its width at kWidthAtRest of
        // the frame; up a little over the roof; looking at a point low and close
        // enough ahead that the pitch keeps the bumper in the picture.
        // The pitch is fixed at kPitch down (the horizon a third of the way from the
        // top), and the camera is never so close that the bumper's lower edge falls
        // out of the frame's bottom 5 % (a truck cab's wheels did, run qb22_after4).
        const float up = (tall + 0.17f) * (std::max)(s.tpHeight, 0.2f) / 1.25f;
        const float bottomAngle = chase::kPitch * kDegToRad + std::atan(0.90f * std::tan(0.5f * fov0 * kDegToRad));
        const float rear = (std::max)(halfW / (chase::kWidthAtRest * tanH), up / std::tan(bottomAngle));
        const float back = (halfL + rear) * (std::max)(s.tpDistance, 0.5f) / 3.4f;
        const float lookUp = (std::max)(0.05f, up - (rear + 2.0f * halfL + 0.25f) * std::tan(chase::kPitch * kDegToRad));
        if (!chase::g_known) {
            chase::g_back = back;
            chase::g_height = up;
            chase::g_lookHeight = lookUp;
            chase::g_known = true;
        } else {
            const float k = 1.0f - std::exp(-dt / 0.4f);
            chase::g_back += (back - chase::g_back) * k;
            chase::g_height += (up - chase::g_height) * k;
            chase::g_lookHeight += (lookUp - chase::g_lookHeight) * k;
        }
        // Speed: eased in on a smooth curve, so cruising and a standstill look the same
        // and the stretch comes as the car gets going.
        const float c = speedFrac_ * speedFrac_ * (3.0f - 2.0f * speedFrac_);
        distance = chase::g_back + chase::kPullBack * s.tpPullBack * c;
        height = chase::g_height + 0.05f * c;
        lookAhead = halfL + (0.25f + 0.9f * c) * (std::max)(s.tpLookAhead, 0.0f) / 1.2f;
        lookHeight = chase::g_lookHeight;
        chaseFovExtra = (std::max)(s.speedFov, chase::kSpeedFov) * c;
        // Into a turn: the look point leads sideways with the car's rate of turn (its
        // heading, eased), at speed only, so the road it is turning into is in frame.
        if (!chase::g_headingKnown) {
            chase::g_lastHeading = headingYaw;
            chase::g_headingKnown = true;
        }
        const float rawRate = WrapAngle(headingYaw - chase::g_lastHeading) / dt;
        chase::g_lastHeading = headingYaw;
        chase::g_turnRate += ((std::max)(-4.0f, (std::min)(4.0f, rawRate)) - chase::g_turnRate) * (1.0f - std::exp(-dt / 0.15f));
        const float leadWant = (std::max)(-chase::kTurnLeadMax, (std::min)(chase::kTurnLeadMax, chase::g_turnRate * chase::kTurnLead)) *
                               (std::min)(speed / 2.0f, 1.0f);
        chase::g_lead += (leadWant - chase::g_lead) * (1.0f - std::exp(-dt / 0.25f));
        turnLead = {std::cos(headingYaw) * chase::g_lead, 0.0f, -std::sin(headingYaw) * chase::g_lead};
    } else {
        chase::g_known = false;
        chase::g_headingKnown = false;
        chase::g_turnRate = chase::g_lead = 0.0f;
    }
    // The death camera: back and up over him, looking at the body.
    if (deathMix_ > 0.0f) {
        distance += (2.8f - distance) * deathMix_;
        height += (2.3f - height) * deathMix_;
        lookAhead += (0.0f - lookAhead) * deathMix_;
        lookHeight += (0.1f - lookHeight) * deathMix_;
    }
    // QB-6, the aim framing (armed on foot, fully while firing): in closer and lower,
    // further over the right shoulder, looking down range, a few degrees narrower.
    const float aimMix = inVehicle ? 0.0f : g_aim.aimMix * (1.0f - deathMix_);
    if (aimMix > 0.0f) {
        distance *= 1.0f - 0.30f * aimMix;
        height *= 1.0f - 0.35f * aimMix;
        lookAhead += 1.6f * scale * aimMix;
        lookHeight += 0.12f * scale * aimMix;
    }
    // Over the shoulder on foot: the camera, and what it looks at, sit a little
    // to the right of him, so he is not a figure in the dead centre.
    const float shoulder = inVehicle ? 0.0f : (s.tpShoulder + 0.30f * aimMix) * scale * (1.0f - deathMix_);
    const float sx = std::cos(followYaw_), sz = -std::sin(followYaw_);   // right of the chase yaw

    // The point looked at is a little ahead of him along his heading, which is
    // what keeps the road ahead in the frame rather than his roof.
    // On foot the point looked at is ahead along the camera, not his heading:
    // an orbit camera frames the street it looks down, whichever way he faces.
    // In a car (QUALITY-BAR row 22) along the chase yaw with the car's heading pulling it at most
    // 20 degrees round: from the close chase a spin or a full-lock turn put the point looked at
    // 45 degrees off the camera's axis and the car at the frame's edge (run qb22_after8).
    float carLookYaw = headingYaw;
    if (inVehicle) {
        const float pull = (std::max)(-20.0f * kDegToRad, (std::min)(20.0f * kDegToRad, WrapAngle(headingYaw - followYaw_)));
        carLookYaw = WrapAngle(followYaw_ + pull);
    }
    const float ax = inVehicle ? std::sin(carLookYaw) : std::sin(yaw), az = inVehicle ? std::cos(carLookYaw) : std::cos(yaw);
    const gta2::Vec3 lookAt{px + ax * lookAhead + sx * shoulder + turnLead.x, baseY + lookHeight,
                            pz + az * lookAhead + sz * shoulder + turnLead.z};

    // Where the camera wants to be: behind, above, swung by the mouse orbit.
    const float cp = std::cos(orbitPitch), sp = std::sin(orbitPitch);
    gta2::Vec3 desired{px - std::sin(yaw) * distance * cp + sx * shoulder, baseY + height + distance * sp,
                       pz - std::cos(yaw) * distance * cp + sz * shoulder};
    const gta2::Vec3 rigEye = desired;   // before any wall moves it (the boom filter below)

    // Not through a wall: walk from just above his head (or the vehicle's roof)
    // out to where the camera wants to be and stop short of the first solid block.
    // Where that is nearer than the camera may come (a stride behind a car, half a
    // block behind him on foot: reversing into a wall, his back to a building) it
    // does not go on through the wall, as it once did: it swings up over him on an
    // arc at the same distance, up to 75 degrees, to the first height that clears,
    // and that lift is eased so it is a crane move, not a jump. Under a roof (a
    // tunnel) where no height clears, it stays in front of the wall.
    // His own map cell is not a wall to the camera on foot. GTA2 puts the solid face of
    // a shop front on the pavement block in front of it as often as on the building's,
    // and Blocked() calls such a block solid: with his back to the shop front every ray
    // from him was blocked at once, the pivot was moved up to 0.9 block in front of him
    // and the camera stared down at the paving ahead of him (QA3 qa_crash_11,
    // QUALITY-BAR row 2). The march now starts in the open from his own cell.
    const int ownX = static_cast<int>(std::floor(px)), ownZ = static_cast<int>(std::floor(pz));
    const int ownY = static_cast<int>(std::floor(baseY + 0.6f));
    // FIX-CAMERA-7B (pf2feel-third-reverse-open-street-camera-stays-put-van-backs-under-it): at the wheel a
    // cell the map calls solid is asked of the drawn mesh too. A ramp's block has a lid, so Blocked() calls
    // the whole block solid, air over the slope included: the van reversing toward a ramp (wil 198.5,61, the
    // ramp's face 2.8 blocks behind at the camera's height) had the eye stop dead 1.5 blocks early, the boom
    // fell from 1.47 to 0.70 in 0.3 s and the van backed under the lens, its roof filling the frame (run
    // cam7b_rev1). A point in such a block that is in no closed block of the mesh and 0.2 or more from any
    // drawn surface is air; the boom's line is still stopped by every wall the mesh draws (reachTo below).
    // GTA2DX9_CAM_CAR_MESH=0 turns it off (A/B).
    static int carMeshOn = -1;
    if (carMeshOn < 0) { char b[8] = {}; carMeshOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_MESH", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    const bool carMesh = inVehicle && carMeshOn && eyecol::Ready();
    // FIX-CAMERA-8 (pfl14): on foot in third person too, a cell the map calls solid is asked of the mesh. The iron
    // staircase at the wil plaza (159.5,139.5) has cells solid where the drawn stair is air: the solve's line out of
    // him read reach 0 there (run cam8_p14q) and the boom was pulled into his head with the mesh clear all the way.
    // OFF by default (GTA2DX9_CAM_FOOT_CELL_MESH=1 turns it on): not yet shown safe beyond the plaza probe.
    static int footCellMeshOn = -1;
    if (footCellMeshOn < 0) { char b[8] = {}; footCellMeshOn = GetEnvironmentVariableA("GTA2DX9_CAM_FOOT_CELL_MESH", b, sizeof b) ? (atoi(b) == 1 ? 1 : 0) : (CameraSwingFirstOn() ? 1 : 0); }
    const bool footCellMesh = !inVehicle && footCellMeshOn && mode == ViewMode::ThirdPerson && eyecol::Ready() && CameraMeshSolveOn();
    auto solidAt = [&](float x, float y, float z) {
        if (!inVehicle && static_cast<int>(std::floor(x)) == ownX && static_cast<int>(std::floor(z)) == ownZ &&
            static_cast<int>(std::floor(y)) == ownY)
            return false;
        if (!q.blocked(q.context, x, y, z)) return false;
        if (carMesh || footCellMesh) {
            const gta2::Vec3 p{x, y, z};
            if (eyecol::Nearest(p, 0.2f) >= 0.2f && !eyecol::InsideSolid(p)) return false;
        }
        return true;
    };
    gta2::Vec3 pivot{px, baseY + (std::max)(0.6f, bodyHeight_ + 0.1f), pz};
    // A car shoved against a building can have its middle inside the wall's
    // block (run cp2_new8: the van reversed into a wall, every ray out of the
    // pivot was blocked at once and the camera sat inside the van). The pivot
    // then moves up and toward the nose until it is in the open.
    if (q.blocked && solidAt(pivot.x, pivot.y, pivot.z)) {
        const gta2::Vec3 base = pivot;
        bool found = false;
        for (int f = 0; f <= 3 && !found; ++f) {
            for (int u = 0; u <= 4 && !found; ++u) {
                const gta2::Vec3 c{base.x + hx * 0.3f * f, base.y + 0.25f * u, base.z + hz * 0.3f * f};
                if (!solidAt(c.x, c.y, c.z)) {
                    pivot = c;
                    found = true;
                }
            }
        }
    }
    // The rescue's step (0.25-1 block up or toward the nose) is eased for the shown camera
    // (FIX-CAMERA: a car grinding a wall hopped the picture half a block in one frame as its
    // centre went in and out of the wall's block, run fixcam_wall4); the solve uses the
    // raw pivot.
    {
        const gta2::Vec3 lift{pivot.x - px, pivot.y - (baseY + (std::max)(0.6f, bodyHeight_ + 0.1f)), pivot.z - pz};
        if (!boomKnown_) {
            rescueX_ = lift.x; rescueY_ = lift.y; rescueZ_ = lift.z;
        } else {
            const float k = 1.0f - std::exp(-dt / 0.2f);
            rescueX_ += (lift.x - rescueX_) * k;
            rescueY_ += (lift.y - rescueY_) * k;
            rescueZ_ += (lift.z - rescueZ_) * k;
        }
    }
    // FIX-CAMERA-14 (pfl28 residual: the car scraping a wall along its side). Backing along a wall with the car's flank
    // 0.0-0.1 off it (wil x=182.0, run cam13_rev8 angled2: the car's middle 0.23 from the bricks), every line out of the
    // car's middle runs within the lens berth of the wall: the solve wanted a boom of 0.22-0.35, the shown eye sat on
    // its 0.57 minimum, 0.25 off the wall, and the car's rear hung past the bottom edge for ~2 s (box bottom 1.4-1.98 of
    // the frame, f88-144); at the x=186 wall the drive-off cut then snapped to a solved eye 0.3 from the car's middle
    // (rev8 angled f872-877: the lens inside the car). The boom's pivot moves off a wall beside the car (level: out to
    // kPivotSide from every drawn surface, at most kPivotShiftMax, never through anything), eased, so the boom runs
    // clear of the wall it is beside and keeps its length. GTA2DX9_CAM_CAR_PIVOT_SIDE=0 turns it off (A/B).
    {
        static int pivotSideOn = -1;
        if (pivotSideOn < 0) { char b[8] = {}; pivotSideOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_PIVOT_SIDE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        constexpr float kPivotSide = 0.5f, kPivotShiftMax = 0.4f;
        float wantX = 0.0f, wantZ = 0.0f;
        if (pivotSideOn && carMesh && mode == ViewMode::ThirdPerson && s.tpCollide) {
            gta2::Vec3 e = pivot;
            if (eyecol::Push(&e, kPivotSide) > 1e-4f) {
                float dx = e.x - pivot.x, dz = e.z - pivot.z;
                const float d = std::hypot(dx, dz);
                if (d > kPivotShiftMax) { dx *= kPivotShiftMax / d; dz *= kPivotShiftMax / d; }
                const gta2::Vec3 to{pivot.x + dx, pivot.y, pivot.z + dz};
                float t = 1.0f;
                if (d > 1e-3f && !eyecol::SegmentHitSolid(pivot, to, &t) && !eyecol::InsideSolid(to) && !solidAt(to.x, to.y, to.z)) {
                    wantX = dx;
                    wantZ = dz;
                }
            }
        }
        // out fast (the wall is there now), back slowly (a car leaving a wall)
        const bool growing = wantX * wantX + wantZ * wantZ > pivotSideX_ * pivotSideX_ + pivotSideZ_ * pivotSideZ_;
        const float k = 1.0f - std::exp(-dt / (growing ? 0.1f : 0.5f));
        pivotSideX_ += (wantX - pivotSideX_) * k;
        pivotSideZ_ += (wantZ - pivotSideZ_) * k;
        if (!carMesh || mode != ViewMode::ThirdPerson) pivotSideX_ = pivotSideZ_ = 0.0f;
        if (pivotSideX_ != 0.0f || pivotSideZ_ != 0.0f) {
            const gta2::Vec3 to{pivot.x + pivotSideX_, pivot.y, pivot.z + pivotSideZ_};
            float t = 1.0f;
            if (!eyecol::SegmentHitSolid(pivot, to, &t) && !solidAt(to.x, to.y, to.z)) {
                pivot = to;
                if (cameraLogOn()) {
                    static int every = 0;
                    if ((++every % 10) == 1) Log("cam: car pivot off the wall %.2f (want %.2f)", std::hypot(pivotSideX_, pivotSideZ_), std::hypot(wantX, wantZ));
                }
            } else {
                pivotSideX_ = pivotSideZ_ = 0.0f;
            }
        }
    }
    const gta2::Vec3 shownPivot{px + rescueX_ + pivotSideX_, baseY + (std::max)(0.6f, bodyHeight_ + 0.1f) + rescueY_, pz + rescueZ_ + pivotSideZ_};
    // FIX-CAMERA-16: at the wheel the line's target is the car (a tree the game drives it through: run cam16_pk1 off).
    if (mode == ViewMode::ThirdPerson) g_chaseHero = {px, baseY, pz, inVehicle ? 0.5f : (std::min)(0.6f, (std::max)(0.4f, bodyHeight_)), Now()};
    // FIX-CAMERA-3 (feel17-armed-third-camera-inside-hero-screen-filled-with-blurred-cloth): on foot
    // the boom is solved against the drawn mesh as well as the map's cells. The cells do not see the
    // iron staircase by the phone box at wil 159.5,139.5 (nor any diagonal or partial face): the
    // camera stood behind its rail for the whole burst, the rail's bars a blurred olive smear over
    // 80 % of the frame and the hero hidden behind them (run fc3_a1, pistol). The first surface on
    // the way stops the boom kMeshClear short of it, and the arc over a wall (below) clears what the
    // mesh says too. In a car the cells alone, as before. GTA2DX9_CAM_MESH=0 turns it off (A/B).
    const bool meshSolve = !inVehicle && eyecol::Ready() && CameraMeshSolveOn();
    constexpr float kMeshClear = 0.15f;
    // FIX-CAMERA-7 (pfeel3 residual: the fence pocket crane): every boom segment on foot starts at his centre,
    // and a railing's sheet on a cell edge runs through his body when he leans on it (the plaza fence at
    // z=108.0, him at 108.02): every way out of him crossed it at t=0, the solve collapsed to nothing, the boom
    // fell into his head at 9 blocks/s and the view craned over him looking 50-59 degrees down for ~1 s (run
    // cam7_base punch_0: 22 frames with him out of the box). A sheet or a bar within his body's reach of the
    // start is one he leans on: the boom keeps its side of it (the bars are see-through). Walls still stop it.
    // FIX-CAMERA-7B: OFF unless GTA2DX9_CAM_LEAN_SHEET=1 (ported uncommitted from FIX-CAMERA-7, not yet shown to
    // help: run cam7b_p3 punch_1 still slid the lens through the finials for 3 frames with it on).
    struct LeanSkip {
        bool on = false;
        explicit LeanSkip(bool want, float r) : on(want) { if (on) eyecol::SetNearSoftSkip(r); }
        ~LeanSkip() { if (on) eyecol::SetNearSoftSkip(0.0f); }
    };
    static int leanSheetOn = -1;
    // FIX-CAMERA-8 (pfl14): still OFF by default; GTA2DX9_CAM_LEAN_SHEET=1 is FIX-CAMERA-7's 0.25, =2 skips sheets
    // within 0.45 of him (the wil iron staircase's rail, 0.2-0.43 from his centre, pulls the boom into his head:
    // runs cam8_p14a..n); not shipped for the same reason as the sheet ease (cam8_p14H).
    static float leanSheetR = -1.0f;
    if (leanSheetOn < 0) {
        char b[8] = {};
        const int v = GetEnvironmentVariableA("GTA2DX9_CAM_LEAN_SHEET", b, sizeof b) ? atoi(b) : 0;
        leanSheetOn = v != 0 ? 1 : 0;
        leanSheetR = v == 1 ? 0.25f : 0.45f;
    }
    // FIX-CAMERA-18 (CAMERA-17's residual: the wil kerb strip at 164.5,147.6, a wall on one side and a railing he walks
    // against on the other, cut round him every 2.7-9 s on walking loops, run cam17_f7): the probe at the cut (run cam18_k2,
    // 'cam: pocket probe') showed every heading over the road blocked only by the railing's sheet 0.05 from his centre
    // (walls only: the full boom) and the walled side open only at the strip's two ends. A pocket memory: the first time
    // a cut is wanted, a sheet or bar crossed within 0.9 of him (FIX-CAMERA-7's lean sheet, at 0.45 the kerb still cut with him 0.74 off
    // the railing: run cam18_k3) stops
    // counting for the boom for 20 s while he stays within 2.5 blocks of that spot, so the swing goes round over the road
    // and looks at him through the bars instead of cutting to the strip's far end. [camera] pocket_lift=0 or
    // GTA2DX9_CAM_POCKET_LIFT=0: off (A/B).
    static float pocketLeanT = 0.0f, pocketLeanX = 0.0f, pocketLeanZ = 0.0f;
    pocketLeanT = (std::max)(0.0f, pocketLeanT - dt);
    const bool pocketLean = pocketLeanT > 0.0f && !inVehicle && std::hypot(px - pocketLeanX, pz - pocketLeanZ) < 2.5f && CameraPocketLiftOn();
    const LeanSkip leanSkip(meshSolve && (leanSheetOn || pocketLean) && mode == ViewMode::ThirdPerson, pocketLean ? 0.9f : leanSheetR);
    auto reachTo = [&](const gta2::Vec3& from, const gta2::Vec3& to) {
        constexpr int kSteps = 32;
        float reach = 1.0f;
        for (int i = 1; i <= kSteps; ++i) {
            const float t = static_cast<float>(i) / kSteps;
            const gta2::Vec3 p = from + (to - from) * t;
            if (solidAt(p.x, p.y, p.z)) { reach = (std::max)(0.0f, static_cast<float>(i - 1) / kSteps - 0.03f); break; }
        }
        if (carMesh) {
            // FIX-CAMERA-7B: at the wheel the cells' false walls are air (solidAt): the mesh's walls stop the line
            // (a railing's sheets and bars do not: the cells never stopped it at a flat panel either).
            const gta2::Vec3 span = to - from;
            const float len = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
            float t = 1.0f;
            if (len > 1e-3f && eyecol::SegmentHitSolid(from, to, &t)) reach = (std::min)(reach, (std::max)(0.0f, t - kMeshClear / len));
        }
        if (meshSolve) {
            const gta2::Vec3 span = to - from;
            const float len = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
            float t = 1.0f;
            if (len > 1e-3f && eyecol::SegmentHit(from, to, &t)) reach = (std::min)(reach, (std::max)(0.0f, t - kMeshClear / len));
        }
        return reach;
    };
    // FIX-CAMERA-4: on foot, round what stands behind him before over it. With a railing, a
    // stair or a wall corner close behind him the boom could only shorten, then crane up over
    // his head and look down at the paving (feel25: the plaza fence corner; pm26: the spawn
    // staircase; the near top-down shot FIX-CAMERA-3 left in tight corners). When the line
    // behind him reaches less than kSwingGood of the rig's length, the boom turns about him
    // (the smallest yaw, 15 degree steps up to 90, the side it already swung to first) to
    // where it reaches that far, eased, and back as the way behind him opens. The frame clamp
    // turns the view onto him from wherever the eye ends up. The lift over a wall below still
    // applies when no swing clears. GTA2DX9_CAM_SWING=0 turns it off (A/B).
    if (!boomKnown_ || inVehicle) { swingAngle_ = 0.0f; swingRigKnown_ = false; }
    bool swingClearing = false;   // FIX-CAMERA-10 (pfl14): this frame the swing turns fast onto a clear heading
    bool swingCut = false;        // FIX-CAMERA-10: ... or cuts there (neither way round open)
    swingClearHold_ = inVehicle ? 0.0f : (std::max)(0.0f, swingClearHold_ - dt);
    if (s.tpCollide && q.blocked && !inVehicle && meshSolve && CameraSwingOn()) {
        const gta2::Vec3 span0 = desired - pivot;
        const float len0 = std::sqrt(span0.x * span0.x + span0.y * span0.y + span0.z * span0.z);
        auto turned = [&](float a) {
            const float c = std::cos(a), sn = std::sin(a);
            return gta2::Vec3{pivot.x + span0.x * c - span0.z * sn, desired.y, pivot.z + span0.x * sn + span0.z * c};
        };
        float wantSwing = 0.0f;
        if (len0 > 0.8f) {
            constexpr float kSwingGood = 0.6f;
            const float good = (std::max)(0.9f, kSwingGood * len0);
            if (reachTo(pivot, desired) * len0 < good) {
                const float first = swingAngle_ < 0.0f ? -1.0f : 1.0f;
                bool found = false;
                for (int k = 1; k <= 6 && !found; ++k) {
                    for (const float sg : {first, -first}) {
                        const float a = sg * static_cast<float>(k) * (15.0f * kDegToRad);
                        if (reachTo(pivot, turned(a)) * len0 >= good) { wantSwing = a; found = true; break; }
                    }
                }
                if (!found) {
                    // A pocket (wall, railing and a lamp post round him: the owner demo's punch, run
                    // fc4_demo2, where the boom fell to 0.03 and the lens sat in his head for 2.6 s):
                    // the way that reaches furthest, out to 165 degrees, the side it is on unless the
                    // other is clearly better; none better than where it is: hold.
                    float bestA = swingAngle_, bestR = reachTo(pivot, turned(swingAngle_)) * len0 + 0.25f;
                    for (int k = 0; k <= 11; ++k) {
                        for (const float sg : {first, -first}) {
                            const float a = sg * static_cast<float>(k) * (15.0f * kDegToRad);
                            const float r = reachTo(pivot, turned(a)) * len0 - (sg != first && k > 0 ? 0.2f : 0.0f);
                            if (r > bestR) { bestR = r; bestA = a; }
                        }
                    }
                    wantSwing = bestA;
                }
            }
        }
        // FIX-CAMERA-8 (pfl11-third-respawn-after-busted-camera-starts-straight-down-hero-gone-then-swoops-1p5s):
        // on the frame the rig re-arms (a respawn at the hospital or the station, a warp, a level cut:
        // snapEye_) the swing it wants is taken at once, so the first frame is the clear boom round what
        // stands behind him. Eased from 0, the respawn at the wil station door opened on a boom of 0.36
        // against the sheet behind him, the view 46 degrees down on his head, and craned out over 1.2 s
        // (run cam8_p11base). GTA2DX9_CAM_REARM_SWING=0 eases it as before (A/B).
        static int rearmSwingOn = -1;
        if (rearmSwingOn < 0) { char b[8] = {}; rearmSwingOn = GetEnvironmentVariableA("GTA2DX9_CAM_REARM_SWING", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const bool rearmSwing = rearmSwingOn && snapEye_ && wantSwing != 0.0f;
        const float wantSwingRearm = wantSwing;
        const float tau = std::fabs(wantSwing) > std::fabs(swingAngle_) ? 0.25f : 0.6f;
        // FIX-CAMERA-5 (feel24-third-armed-turn-to-target-camera-swings-through-wall-...): the swing
        // is an offset from the rig, and the armed rig turns with him at up to 240 degrees a second
        // (QB-6). Eased over 0.25 s, the offset lagged a turn toward a wall by 60 degrees: the boom
        // went into the wall's corner and the filter pulled it from 1.5 to 0.6 block in five frames
        // (the hero 2.5 times bigger, seen from above: run fc5_all_base, wil 163.5,137.5). Now a swing
        // that is wanted may take up the rig's own turn at once: anywhere between following the rig
        // and holding its heading in the world is no motion of the picture beyond what the rig makes
        // anyway, so the camera holds still while the rig turns toward the wall, and only the rest
        // is eased. GTA2DX9_CAM_SWING_HOLD=0 restores the plain ease (A/B).
        const float rigYaw = std::atan2(span0.x, span0.z);
        float dRig = 0.0f;
        if (swingRigKnown_) dRig = WrapAngle(rigYaw - swingRigYaw_);
        swingRigYaw_ = rigYaw;
        swingRigKnown_ = true;
        static int holdOn = -1;
        if (holdOn < 0) { char b[8] = {}; holdOn = GetEnvironmentVariableA("GTA2DX9_CAM_SWING_HOLD", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        bool held = false, waiting = false;
        if (holdOn && len0 > 0.8f && std::fabs(dRig) < 0.6f) {
            // turned(a) puts the boom at the rig's heading minus a: the camera's heading held in the
            // world is the swing plus the rig's turn this frame.
            // The swing kept within +-180 (the same heading), and the path checked below is the one
            // the ease takes from there (a hold wrapped on its own had the ease go the long way round,
            // through the walls it was holding off: run fc5_all_v2).
            swingAngle_ = WrapAngle(swingAngle_);
            const float hold = swingAngle_ + dRig;
            const float good = (std::max)(0.9f, 0.6f * len0);
            // The way the swing would go from there to what it wants (the eased path, sampled every
            // 15 degrees or less): through a wall (a corner he spins in: the armed rig follows a full
            // turn) the camera does not go, it waits where it is and he turns in the picture; it
            // follows once the way round is open (or what it holds closes in, below).
            const float span = wantSwing - hold;
            const int n = static_cast<int>(std::fabs(span) / (15.0f * kDegToRad)) + 1;
            bool blocked = false;
            for (int k = 1; k <= n && !blocked; ++k)
                blocked = reachTo(pivot, turned(hold + span * static_cast<float>(k) / n)) * len0 < good;
            if (blocked && reachTo(pivot, turned(hold)) * len0 >= 0.9f * good) {
                wantSwing = hold;
                swingAngle_ = hold;
                held = waiting = true;
            } else {
                // Anywhere between following the rig and holding the world heading is no motion
                // beyond the rig's own: the swing may take that up at once, only the rest is eased.
                const float lo = (std::min)(swingAngle_, swingAngle_ + dRig), hi = (std::max)(swingAngle_, swingAngle_ + dRig);
                const float base = (std::max)(lo, (std::min)(hi, wantSwing));
                swingAngle_ = base + (wantSwing - base) * (1.0f - std::exp(-dt / tau));
                held = true;
            }
        }
        const float swingAtStart = swingAngle_;
        if (!held) swingAngle_ += (wantSwing - swingAngle_) * (1.0f - std::exp(-dt / tau));
        // FIX-CAMERA-10 (pfl14-third-on-foot-plaza-camera-lunge-and-roll): beside the wil iron staircase the
        // stair's side (a two-sided railing face 0.2 from his centre) cuts the line behind him as he steps along it;
        // the swing to the open side eased over 0.25 s while the boom fell in at 9 blocks/s, so the camera lunged
        // into his head and craned to 55-60 degrees down (run cam10_p24a punch_1: solved 1.37 -> 0.07 in a frame,
        // pitch -11 -> -59 in 6). When the heading the swing is at cannot reach and the one it wants can, it
        // turns there fast (kSwingFast; the shown boom's direction is still capped at 4 rad/s below) and the boom
        // eases in at a see-through sheet instead of cutting (the boom filter, swingClearing): the distance
        // holds while the camera goes round. GTA2DX9_CAM_SWING_FIRST=0 restores HEAD (A/B).
        // FIX-CAMERA-17 (owner10nov-B10): under the turn budget (CameraTurnBudgetDeg) the fast swing turns at most
        // three quarters of the budget's rate (a 360 deg/s swing showed as 10-degree frames for half a second), never
        // cuts (the 'neither way round is open' cut turned the picture 110-177 degrees in one frame: beside the wil
        // phone box at the iron stair, and on the kerb between the wall and the railing at 164.5,147.6, where it cut
        // back and forth every 0.3-6 s: run cam17_b0), and for 1 s after a fast swing it does not start one the other
        // way round unless the line where it is has collapsed (the ping-pong). The boom still eases in at a sheet
        // while it goes round (swingClearing), and the eye collision keeps the lens out of the walls.
        const float budgetDeg = CameraTurnBudgetDeg();
        swingDwell_ = (std::max)(0.0f, swingDwell_ - dt);
        sinceSwingCut_ = (std::min)(sinceSwingCut_ + dt, 60.0f);
        if (!waiting && len0 > 0.8f && CameraSwingFirstOn()) {
            const float kSwingFast = budgetDeg > 0.0f ? (std::min)(360.0f, 0.75f * budgetDeg * 30.0f) * kDegToRad : 360.0f * kDegToRad;
            const float good = (std::max)(0.9f, 0.6f * len0);
            const float rest = WrapAngle(wantSwing - swingAngle_);
            const float reachHere = reachTo(pivot, turned(swingAtStart)) * len0;
            const bool reversing = budgetDeg > 0.0f && swingDwell_ > 0.0f && rest * swingDwellDir_ < 0.0f && reachHere >= 0.35f * good;
            if (reversing && cameraLogOn()) {
                static int every = 0;
                if ((++every % 10) == 1) Log("cam: swing first held: a swing the other way within 1 s of the last (rest %.1f deg)", rest / kDegToRad);
            }
            if (!reversing && std::fabs(rest) > 3.0f * kDegToRad && reachHere < good &&
                reachTo(pivot, turned(wantSwing)) * len0 >= good) {
                // The way round: the short one unless a heading on it reaches under half the boom and the long
                // one's do not (run cam10_p14h: the short way round crossed the staircase, the lens 0.08 over its
                // treads).
                auto pathMin = [&](float from, float span) {
                    const int n = static_cast<int>(std::fabs(span) / (15.0f * kDegToRad)) + 1;
                    float m = 1.0f;
                    for (int k = 1; k < n; ++k) m = (std::min)(m, reachTo(pivot, turned(from + span * static_cast<float>(k) / n)));
                    return m;
                };
                const float longSpan = rest > 0.0f ? rest - 2.0f * kPi : rest + 2.0f * kPi;
                float dir = rest;
                const float shortMin = pathMin(swingAngle_, rest), longMin = pathMin(swingAngle_, longSpan);
                if (shortMin * len0 < 0.5f * good && longMin * len0 >= 0.5f * good) dir = longSpan;
                if (cameraLogVerbose()) Log("cam: swing first route: short %.2f long %.2f (good %.2f)%s", shortMin * len0, longMin * len0, good,
                                            dir != rest ? " the long way" : "");
                // Neither way round is open (the stair beside him one way, the wall behind the other: run
                // cam10_p15c, both 0.07): a cut to the clear heading, at the same distance and pitch, instead of a
                // swing through the staircase that ends with the lens in his head.
                // Only when the line where it is has collapsed (at the plaza fence a corner walk's line reaching
                // 0.5 of good went round smoothly on HEAD and was cut needlessly: run cam10_r6on cornerwalk_1).
                // FIX-CAMERA-17: under the turn budget at most one cut in kCutGap seconds (on the kerb between the wall and
                // the railing it cut 116 -> -30, then -13 -> 105 0.3 s later: run cam17_b0); in between the swing goes
                // round at its budgeted rate. (Without the cut a pocket's swing dragged the boom across the rail and the
                // lens fell onto his axis: runs cam17_f2..f4.)
                const bool cutWantedEarly = reachTo(pivot, turned(swingAtStart)) * len0 < 0.35f * good && shortMin * len0 < 0.5f * good &&
                                            longMin * len0 < 0.5f * good && std::fabs(rest) > 30.0f * kDegToRad;
                // FIX-CAMERA-18 (CAMERA-17's residual: the kerb at wil 164.5,147.6 is an L-shaped strip round a building's corner
                // with railings on its outside; walking loops there, the boom cut round him every 2.7-9 s, run cam17_f7): neither
                // way round open, the arc over what closes the line where the boom already is (the on-foot lift below, up to 45
                // degrees) is tried before a cut or a swing through it; if it opens the line the swing holds and the boom rises
                // over the railing (the lift below does it, eased). The heading changes only once a way round opens.
                // [camera] pocket_lift=0 or GTA2DX9_CAM_POCKET_LIFT=0: CAMERA-17's cut (A/B).
                bool pocketHold = false;
                if (budgetDeg > 0.0f && CameraPocketLiftOn() && !pocketLean && cutWantedEarly) {
                    // the pocket memory (above): from the next frame the sheet he leans on is see-through for the boom
                    pocketLeanT = 20.0f; pocketLeanX = px; pocketLeanZ = pz;
                    pocketHold = true;
                    if (cameraLogOn())
                        Log("cam: pocket: a cut wanted at %.2f,%.2f; the railing he leans on stops counting for the boom for 20 s within 2.5 blocks (swing %.1f want %.1f)",
                            px, static_cast<float>(gta2::kMapHeight) - pz, swingAtStart / kDegToRad, wantSwing / kDegToRad);
                }
                if (!pocketHold && budgetDeg > 0.0f && CameraPocketLiftOn() && shortMin * len0 < 0.5f * good && longMin * len0 < 0.5f * good) {
                    const gta2::Vec3 here = turned(swingAtStart);
                    const gta2::Vec3 sp = here - pivot;
                    const float flat = std::hypot(sp.x, sp.z), L = std::sqrt(sp.x * sp.x + sp.y * sp.y + sp.z * sp.z);
                    if (flat > 1e-3f && L > 1e-3f) {
                        const float a0 = std::atan2(sp.y, flat), aMax = (std::max)(a0, 45.0f * kDegToRad);
                        for (int k = 1; k <= 6 && !pocketHold; ++k) {
                            const float a = a0 + (aMax - a0) * static_cast<float>(k) / 6.0f;
                            const gta2::Vec3 e{pivot.x + sp.x / flat * std::cos(a) * L, pivot.y + std::sin(a) * L, pivot.z + sp.z / flat * std::cos(a) * L};
                            if (reachTo(pivot, e) * L >= 0.5f * good) {
                                pocketHold = true;
                                if (cameraLogOn()) {
                                    static int every = 0;
                                    if ((++every % 10) == 1)
                                        Log("cam: pocket: no way round is open, the boom rises %.0f deg over what closes the line at %.1f (want %.1f) instead of a cut",
                                            (a - a0) / kDegToRad, swingAtStart / kDegToRad, wantSwing / kDegToRad);
                                }
                            }
                        }
                    }
                }
                if (!pocketHold) {
                constexpr float kCutGap = 2.0f;
                const bool cutWanted = reachTo(pivot, turned(swingAtStart)) * len0 < 0.35f * good && shortMin * len0 < 0.5f * good &&
                                       longMin * len0 < 0.5f * good && std::fabs(rest) > 30.0f * kDegToRad;
                const bool cut = cutWanted && (budgetDeg <= 0.0f || sinceSwingCut_ >= kCutGap);
                if (cut) sinceSwingCut_ = 0.0f;
                else if (cutWanted && cameraLogOn()) Log("cam: swing first: cut wanted %.1f s after the last, swung instead", sinceSwingCut_);
                const float step = cut ? std::fabs(dir) : (std::min)(std::fabs(dir), kSwingFast * (std::min)(dt, 1.0f / 20.0f));
                const float before = swingAngle_;
                swingAngle_ += dir > 0.0f ? step : -step;
                swingDwell_ = 1.0f;
                swingDwellDir_ = dir > 0.0f ? 1.0f : -1.0f;
                if (cut && cameraLogOn()) {   // FIX-CAMERA-18: what closes each heading round him at a cut (mesh, walls only, lifted)
                    char buf[1400]; int nb = 0;
                    for (int k = -11; k <= 12 && nb < 1300; ++k) {
                        const float a = swingAngle_ + static_cast<float>(k) * (15.0f * kDegToRad);
                        const gta2::Vec3 e = turned(a);
                        const gta2::Vec3 sp = e - pivot;
                        const float flat = std::hypot(sp.x, sp.z), L = std::sqrt(sp.x * sp.x + sp.y * sp.y + sp.z * sp.z);
                        float ts = 1.0f;
                        const bool hs = L > 1e-3f && eyecol::SegmentHitSolid(pivot, e, &ts);
                        auto lifted = [&](float deg) {
                            const float a0 = std::atan2(sp.y, flat), al = a0 + deg * kDegToRad;
                            const gta2::Vec3 q{pivot.x + sp.x / flat * std::cos(al) * L, pivot.y + std::sin(al) * L, pivot.z + sp.z / flat * std::cos(al) * L};
                            return reachTo(pivot, q) * L;
                        };
                        nb += snprintf(buf + nb, sizeof buf - nb, " %d:%.2f/%.2f/%.2f/%.2f", static_cast<int>(std::lround(WrapAngle(a) / kDegToRad)),
                                       reachTo(pivot, e) * len0, hs ? ts * L : L, flat > 1e-3f ? lifted(30.0f) : 0.0f, flat > 1e-3f ? lifted(60.0f) : 0.0f);
                    }
                    Log("cam: pocket probe at the cut (swing:mesh/walls/lift30/lift60, len %.2f good %.2f, pivot %.2f,%.2f,%.2f):%s", len0, good, pivot.x, pivot.y,
                        static_cast<float>(gta2::kMapHeight) - pivot.z, buf);
                }
                if (cut) {
                    swingCut = true;
                    if (cameraLogOn()) Log("cam: swing first: neither way round is open, cut %.1f -> %.1f deg", before / kDegToRad,
                                           swingAngle_ / kDegToRad);
                }
                // The camera goes round with the swing: the eye state turns about him by this frame's step, so the
                // ease below does not cut the chord through him (run cam10_p14u: eased along the chord, the shown
                // boom turned 5 degrees a frame and crossed the staircase on the way).
                {
                    const float a = swingAngle_ - before, c = std::cos(a), sn = std::sin(a);
                    const float ox = eyeX_ - pivot.x, oz = eyeZ_ - pivot.z;
                    eyeX_ = pivot.x + ox * c - oz * sn;
                    eyeZ_ = pivot.z + ox * sn + oz * c;
                }
                swingAngle_ = WrapAngle(swingAngle_);
                swingClearing = true;
                swingClearHold_ = 0.6f;
                if (cameraLogOn()) Log("cam: swing first %.1f -> %.1f want %.1f deg", swingAtStart / kDegToRad, swingAngle_ / kDegToRad,
                                       wantSwing / kDegToRad);
                }   // FIX-CAMERA-18 !pocketHold
            }
        }
        if (rearmSwing) {
            swingAngle_ = wantSwingRearm;
            if (cameraLogOn()) Log("cam: re-armed with the swing it wants: %.1f deg", swingAngle_ / kDegToRad);
        }
        if (std::fabs(swingAngle_) < 1e-3f) swingAngle_ = 0.0f;
        if (swingAngle_ != 0.0f) desired = turned(swingAngle_);
        if (cameraLogVerbose())
            Log("cam: swingv %.1f want %.1f rig %.1f dRig %.1f len0 %.2f reach %.2f%s%s", swingAngle_ / kDegToRad, wantSwing / kDegToRad,
                rigYaw / kDegToRad, dRig / kDegToRad, len0, reachTo(pivot, desired), held ? " held" : "", waiting ? " waiting" : "");
        if (cameraLogOn() && (swingAngle_ != 0.0f || wantSwing != 0.0f)) {
            static int every = 0;
            if ((++every % 10) == 1) Log("cam: swing %.1f want %.1f deg%s", swingAngle_ / kDegToRad, wantSwing / kDegToRad, waiting ? " (holding: the way round is walled)" : "");
        }
    } else {
        swingAngle_ = 0.0f;
        swingRigKnown_ = false;
    }
    // FIX-CAMERA-9 (pfl28-third-reverse-after-hard-turn-van-backs-under-camera-roof-fills-60pct-for-2p2s): at the
    // wheel the boom turns aside when neither the line behind the car nor the arc over what stands there keeps the
    // car arc's minimum pull. A van reversing at the wil plaza corner (199,81) toward a building's wall 1.25 block
    // behind its centre, under a lid at 3.0 that stops the arc, had the boom fall to its 0.72 minimum (the lens 0.15
    // off the rear bumper), then rise over the roof looking down 35 degrees: the roof filled 50-65 % of the frame for
    // 2 s (run cam9_p28a). The open street lies 60-90 degrees to the side. Reversing, the line is tested as far out as
    // the car will have backed in 1.2 s (cam9_p28e: tested 0.8 s ahead, the turn began with the
    // van 0.6 s from the wall and it filled half the frame mid-turn), so the turn starts before the boom has to shorten. The smallest
    // turn (20-degree steps, out to 120, the side it is on first) that keeps 90 % of the boom, else the minimum pull;
    // eased out over ~0.12 s (at most 200 degrees a second), back over ~0.8 s once the line behind holds the pull with room to spare.
    // GTA2DX9_CAM_CAR_SWING=0 turns it off (A/B).
    // FIX-INCAR-1: GTA2DX9_CAM_CAR_SWING_EARLY=0 restores FIX-CAMERA-9's turn (A/B).
    static int carSwingEarly = -1;
    if (carSwingEarly < 0) { char b[8] = {}; carSwingEarly = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_SWING_EARLY", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    auto CarSwingEarlyOn = [&]() { return carSwingEarly != 0; };
    float carSwingStep = 0.0f;      // FIX-INCAR-1: this frame's turn of the in-car boom (the view's yaw cap below lets it through)
    bool carDriveOffCut = false;    // FIX-CAMERA-13: this frame the in-car boom cuts from ahead of the car to behind it
    static float carSwing = 0.0f;   // FIX-CAMERA-9: the in-car boom's turn aside (radians; the aim below uses it too)
    {
        static int carSwingOn = -1;
        if (carSwingOn < 0) { char b[8] = {}; carSwingOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_SWING", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const gta2::Vec3 span0 = desired - pivot;
        const float len0 = std::sqrt(span0.x * span0.x + span0.y * span0.y + span0.z * span0.z);
        if (carSwingOn && inVehicle && mode == ViewMode::ThirdPerson && boomKnown_ && boomInVehicle_ && s.tpCollide && q.blocked &&
            deathMix_ < 0.01f && len0 > 0.8f && std::hypot(span0.x, span0.z) > 0.3f) {
            const float good = (std::min)(1.4f + 0.5f * extraLength_ + 0.5f * extraHeight_, 0.75f * len0);   // the arc's minPull
            const float backing = (std::max)(0.0f, -(velX_ * hx + velZ_ * hz));
            // FIX-INCAR-1 (pfl28, triage tri15_p28): at 3 blocks a second the 2-block cap was 0.7 s, not 1.2: the van
            // backing straight at a wall tripped the turn 0.5 s before it hit and backed under the lens mid-turn.
            const float ahead = (std::min)(CarSwingEarlyOn() ? 3.6f : 2.0f, 1.2f * backing);
            auto turned = [&](float a, float len) {
                const float c = std::cos(a), sn = std::sin(a), k = len / len0;
                return gta2::Vec3{pivot.x + (span0.x * c - span0.z * sn) * k, pivot.y + span0.y * k, pivot.z + (span0.x * sn + span0.z * c) * k};
            };
            auto reachAt = [&](float a) { return reachTo(pivot, turned(a, len0 + ahead)) * (len0 + ahead) - ahead; };
            // The arc over it (the lift below: up to 40 degrees at the wheel) clears it: that is the lift's to do.
            auto arcClears = [&]() {
                const float flat = std::hypot(span0.x, span0.z), a0 = std::atan2(span0.y, flat);
                for (int k = 1; k <= 4; ++k) {
                    const float a = a0 + ((std::max)(a0, 40.0f * kDegToRad) - a0) * k / 4.0f, L = len0 + ahead;
                    const gta2::Vec3 e{pivot.x + span0.x / flat * std::cos(a) * L, pivot.y + std::sin(a) * L, pivot.z + span0.z / flat * std::cos(a) * L};
                    if (reachTo(pivot, e) * L - ahead >= good) return true;
                }
                return false;
            };
            const float straight = reachAt(0.0f);
            const bool swung = std::fabs(carSwing) > 1e-3f;
            float want = 0.0f;
            // FIX-INCAR-1 (pfl28, tri15_p28): backing toward it, or already turned aside, the arc over it is not a way:
            // the lift craned over the roof looking 35 degrees down while the van closed on the wall (roof 55-70 % of the
            // frame for 0.5 s before the turn, run tri15_p28 f66-f80), and turned aside the arc sent the boom back over
            // the roof as the van drove off (the lens over the van at 5.0-5.8 s, f150-f174): the turn holds until the
            // line behind keeps the pull.
            const bool arcWay = !(CarSwingEarlyOn() && (backing > 0.3f || swung));
            // FIX-CAMERA-11 (pfl28 angled, triage tri18_rev): a car backing along a wall at a building's corner took a
            // turn whose eye went round through the wall (the turn 106 -> 134 with the lens on the wall's face: 0.3 s of
            // black frames), then flipped to the far side (-20..-60) through the blocked line behind. A turn is only to a
            // heading on the side it is turned to when the way round to it is open now (every 10 degrees from where
            // the turn is keeps 0.35 block of boom), and the turned eye is never put past a wall (below). (A cut to the
            // far side was tried: the car turns on the impact and the heading cut to was walled a frame later, the eye
            // over the roof for 1.5 s, run cam11_rev3.) GTA2DX9_CAM_CAR_ARC=0 restores FIX-INCAR-1's search (A/B).
            static int carArcOn = -1;
            if (carArcOn < 0) { char b[8] = {}; carArcOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_ARC", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            const bool arcCheck = carArcOn && CarSwingEarlyOn();
            const int maxSteps = 6;
            auto wayOpen = [&](float a) {
                if (!arcCheck) return true;
                const float from = carSwing, span = a - from;
                const int n = (std::max)(1, static_cast<int>(std::ceil(std::fabs(span) / (10.0f * kDegToRad))));
                for (int i = 1; i <= n; ++i) {
                    const float t = from + span * static_cast<float>(i) / n;
                    if (reachTo(pivot, turned(t, len0)) * len0 < (std::min)(0.5f * good, 0.35f)) return false;
                }
                return true;
            };
            // FIX-CAMERA-13 (pfl28 corner pocket): backing with the wheel over along a wall, the car's rear corner swept into
            // a lens the wall held, while the line straight behind still reached the pull (it fell only once the car was in
            // the pocket): 0.75 s of the canopy over the lower frame before the turn (runs cam13_rev1/3/5 angled f78-100).
            // When the eye's distance to the car's footprint closes so fast it would reach 0.1 within 0.3 s, the turn is
            // looked for now. GTA2DX9_CAM_CAR_LENS_GUARD=0 turns it off (A/B).
            bool carAtLens = false;
            bool lensImminent = false;   // FIX-CAMERA-14: the car reaches the lens within 0.15 s
            {
                static int lensGuard = -1;
                if (lensGuard < 0) { char b[8] = {}; lensGuard = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_LENS_GUARD", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                static float prevGap = -1.0f;
                float gap = -1.0f;
                for (const CameraCar& c : LiveCameraCars())
                    if (c.object == reinterpret_cast<uintptr_t>(player.vehicleSprite)) { gap = -CarFootprintDepth(c, eyeX_, eyeZ_); break; }
                if (lensGuard && gap >= 0.0f && prevGap >= 0.0f && backing > 0.5f && dt > 1e-4f) {
                    const float closing = (prevGap - gap) / dt;
                    if (closing > 0.0f && gap - 0.3f * closing < 0.1f && gap < 0.8f) {
                        carAtLens = true;
                        lensImminent = gap - 0.15f * closing < 0.05f;
                        if (cameraLogOn()) Log("cam: car at the lens: gap %.2f closing %.2f/s, turn looked for (behind reaches %.2f)", gap, closing, straight);
                    }
                }
                prevGap = gap;
                // held while it still backs (the next frame's gap no longer closes and the turn would ease back onto it)
                static float lensHold = 0.0f;
                if (carAtLens) lensHold = 0.8f;
                else if (lensHold > 0.0f && backing > 0.3f) { lensHold -= dt; carAtLens = true; }
                else lensHold = 0.0f;
            }
            if ((straight < good + (swung ? 0.2f : 0.0f) || carAtLens) && !(arcWay && arcClears())) {
                const float first = carSwing < 0.0f ? -1.0f : 1.0f;
                bool found = false;
                // the whole boom if a turn of up to 120 degrees has it (cam9_p28b: the turn that kept only the
                // minimum pull left the lens at the van's rear corner, the van filling half the frame), else the pull
                // one side out to 120 before the other (cam9_p28c: alternating per step flipped a 36-degree turn to -60)
                // FIX-INCAR-1 (pfl28): turned aside already, the side it is on keeps the turn while any heading on it
                // keeps the pull: a reverse with the wheel over flipped the wanted side frame to frame (+80 / -60) and
                // the boom finally crossed from +78 to -80 through the blocked line behind, the car out of the frame for
                // ~0.3 s (run incar1_rev1 angled f100-f120).
                if (CarSwingEarlyOn() && swung) {
                    for (const float need : {(std::max)(good, 0.9f * len0), good})
                        for (int k = 1; k <= maxSteps && !found; ++k) {
                            const float a = first * static_cast<float>(k) * (20.0f * kDegToRad);
                            if (reachAt(a) >= need && wayOpen(a)) { want = a; found = true; }
                        }
                    if (!found) {
                        float bestSame = -1e9f, bestA = carSwing;
                        for (int k = 1; k <= (std::max)(7, maxSteps); ++k) {
                            const float a = first * static_cast<float>(k) * (20.0f * kDegToRad), r = reachAt(a);
                            if (r > bestSame && wayOpen(a)) { bestSame = r; bestA = a; }
                        }
                        if (bestSame >= 0.5f * good) { want = bestA; found = true; }
                    }
                }
                for (const float need : {(std::max)(good, 0.9f * len0), good})
                    for (const float sg : {first, -first})
                        for (int k = 1; k <= maxSteps && !found; ++k) {
                            const float a = sg * static_cast<float>(k) * (20.0f * kDegToRad);
                            if (reachAt(a) >= need) { want = a; found = true; }
                        }
                if (!found) {
                    // Nowhere keeps the pull: the way that reaches furthest, if clearly better than straight behind.
                    float bestR = straight + 0.3f;
                    for (int k = 1; k <= (std::max)(7, maxSteps); ++k)
                        for (const float sg : {first, -first}) {
                            const float a = sg * static_cast<float>(k) * (20.0f * kDegToRad), r = reachAt(a);
                            if (r > bestR) { bestR = r; want = a; }
                        }
                }

            }
            // FIX-CAMERA-14: one cut at a time (two cuts 0.25 s apart read as a glitch, run cam14_rev10).
            static float sinceCarCut = 10.0f;
            sinceCarCut += dt;
            // FIX-CAMERA-14 (pfl28: the car backing into the lens faster than the turn goes round). Backing at 3 blocks a
            // second toward an eye turned to 140 degrees, the guard tripped with the gap 0.49 closing at 3.1/s; the turn,
            // capped at 140 degrees a second (2 blocks a second at the lens), could not get away, the side it looked for
            // flipped +-80 frame to frame, and the lens slid over the car's flank for 9 frames (run cam14_rev4 angled
            // f902-910: box 1.6 x 2.3 frames, pitch -33). When the car will reach the lens within 0.15 s and a turn with
            // the whole pull lies more than 30 degrees from where it is, it cuts there (the solved pose at once), as the
            // drive-off does. GTA2DX9_CAM_CAR_LENS_CUT=0 turns it off (A/B).
            {
                static int lensCut = -1;
                if (lensCut < 0) { char b[8] = {}; lensCut = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_LENS_CUT", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                if (lensCut && lensImminent && sinceCarCut > 0.6f && std::fabs(want - carSwing) > 30.0f * kDegToRad && reachAt(want) >= good) {
                    if (cameraLogOn()) Log("cam: car at the lens: cut %.1f -> %.1f (reaches %.2f of %.2f)", carSwing / kDegToRad, want / kDegToRad, reachAt(want), good);
                    carSwing = want;
                    carDriveOffCut = true;
                }
            }
            // FIX-CAMERA-13 (pfl28 drive-off): turned past 100 degrees the eye is ahead of the car; driving off forward the
            // turn eased back over 0.8 s and the car drove into the lens pinned on the wall it had backed along (run
            // cam13_rev4 angled f147-188: the canopy over the whole frame, then the car cut at the bottom edge, 1.4 s).
            // Driving forward with the line behind reaching half the pull, it cuts to behind the car (the solved pose at once).
            // GTA2DX9_CAM_CAR_DRIVEOFF_CUT=0 turns it off (A/B).
            {
                static int driveOffCut = -1;
                if (driveOffCut < 0) { char b[8] = {}; driveOffCut = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_DRIVEOFF_CUT", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                const float forward = velX_ * hx + velZ_ * hz;
                // (not waiting for the turn's hold to let go: held until the line behind kept the pull, the cut came 0.6 s
                // into the drive-off with the car's nose over the lower half of the frame, run cam13_rev6 f117-135; the boom
                // behind may be short a while, the filter eases it out)
                // FIX-CAMERA-14 (pfl28: the cut into the car): with the car's rear against the wall it had backed into
                // (wil x=187), the line behind reached 0.45 of a 0.86 pull, the half-pull test passed, and the cut landed
                // 0.2 behind the car's middle: four frames with the lens inside the car (run cam14_rev1 angledR f1152-1157,
                // box 5.7 x 19.5 frames). The cut goes to the smallest turn that has the whole pull, behind first, then
                // side-on out to 100 degrees (the side it is on first); only when none has it, behind at half the pull as
                // before. GTA2DX9_CAM_CAR_CUT_ROOM=0 restores FIX-CAMERA-13's cut (A/B).
                static int cutRoom = -1;
                if (cutRoom < 0) { char b[8] = {}; cutRoom = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_CUT_ROOM", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                if (driveOffCut && std::fabs(carSwing) > 100.0f * kDegToRad && forward > 0.3f && sinceCarCut > 0.6f) {
                    float to = 0.0f;
                    bool cut = false;
                    if (cutRoom) {
                        const float sideFirst = carSwing < 0.0f ? -1.0f : 1.0f;
                        if (straight >= good) cut = true;
                        // out to 80: a cut to 100 still passed the > 100 test (float) and cut again every frame (cam14_rev10)
                        for (int k = 1; k <= 4 && !cut; ++k)
                            for (const float sg : {sideFirst, -sideFirst}) {
                                const float a = sg * static_cast<float>(k) * (20.0f * kDegToRad);
                                if (!cut && reachAt(a) >= good) { to = a; cut = true; }
                            }
                    }
                    if (!cut && straight >= 0.5f * good) { to = 0.0f; cut = true; }
                    if (cut) {
                        if (cameraLogOn())
                            Log("cam: car swing %.1f: driving off at %.2f with the eye ahead of the car, cut to %.0f (behind reaches %.2f of %.2f)",
                                carSwing / kDegToRad, forward, to / kDegToRad, straight, good);
                        carSwing = to;
                        want = to;
                        carDriveOffCut = true;
                    }
                }
            }
            // FIX-CAMERA-14 (pfl28: the turn re-started after a cut). The car driving off along the x=186 wall with its
            // middle 0.28 off it: the cut put the boom behind at half the pull, and the next frame the turn set off again
            // (9 -> 44 degrees wanting 120), toward the wall; the eye sat on the wall's berth 0.45 behind the car for
            // ~1.5 s, the lens on the car (run cam14_rev8 angled f867-899: box up to 4 x 12 frames). After a cut the turn
            // holds where the cut put it for 1 s (the car drives out of the pocket and the boom eases out), unless that
            // heading loses half the pull. GTA2DX9_CAM_CAR_CUT_HOLD=0 turns it off (A/B).
            {
                static int cutHoldOn = -1;
                if (cutHoldOn < 0) { char b[8] = {}; cutHoldOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_CUT_HOLD", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                static float cutHold = 0.0f;
                if (carDriveOffCut) { cutHold = cutHoldOn ? 1.0f : 0.0f; sinceCarCut = 0.0f; }
                else if (cutHold > 0.0f) {
                    cutHold -= dt;
                    // only a turn that sets off again is held: easing back toward behind is not (a hold at -40 kept the
                    // eye on the wall's berth while the car drove off, the line behind open: cam14_rev11 angledR f117-205)
                    if (std::fabs(want) <= std::fabs(carSwing) && want * carSwing >= 0.0f) {
                    } else if (reachAt(carSwing) >= 0.5f * good) {
                        if (want != carSwing && cameraLogOn()) {
                            static int every = 0;
                            if ((++every % 10) == 1) Log("cam: car swing held %.1f after the cut (wanted %.1f)", carSwing / kDegToRad, want / kDegToRad);
                        }
                        want = carSwing;
                    } else {
                        cutHold = 0.0f;
                    }
                }
            }
            const float tau = std::fabs(want) > std::fabs(carSwing) ? 0.12f : 0.8f;
            float d = (want - carSwing) * (1.0f - std::exp(-dt / tau));
            // FIX-INCAR-1: tripped earlier now, the turn can be gentler (140 degrees a second, was 200).
            const float cap = (CarSwingEarlyOn() ? 140.0f : 200.0f) * kDegToRad * (std::min)(dt, 1.0f / 20.0f);
            d = (std::max)(-cap, (std::min)(cap, d));
            carSwing += d;
            carSwingStep = std::fabs(d);
            if (CarSwingEarlyOn() && d != 0.0f) {
                // FIX-INCAR-1: the eye goes round with the turn (the eased eye cut the chord: 0.65 block from the van's
                // middle mid-turn, the van filling the frame, run tri15_p28 f1043).
                const float c = std::cos(d), sn = std::sin(d);
                const float ox = eyeX_ - pivot.x, oz = eyeZ_ - pivot.z;
                const gta2::Vec3 rot{pivot.x + ox * c - oz * sn, eyeY_, pivot.z + ox * sn + oz * c};
                // FIX-CAMERA-11: never round into a wall (the turned eye was put on the pillar's face, tri18_rev f93-99):
                // a turned eye the mesh stops on the way from the car stays where it was (the boom filter eases it).
                float th = 1.0f;
                if (!(carArcOn && carMesh && eyecol::SegmentHitSolid(pivot, rot, &th))) {
                    eyeX_ = rot.x;
                    eyeZ_ = rot.z;
                }
            }
            if (std::fabs(carSwing) < 1e-3f) carSwing = 0.0f;
            if (carSwing != 0.0f) desired = turned(carSwing, len0);
            if (cameraLogOn() && (carSwing != 0.0f || want != 0.0f))
                Log("cam: car swing %.1f want %.1f (behind reaches %.2f of %.2f, backing %.2f)", carSwing / kDegToRad, want / kDegToRad, straight, good, backing);
        } else {
            carSwing = 0.0f;
        }
    }
    if (s.tpCollide && q.blocked) {
        const gta2::Vec3 span = desired - pivot;
        const float spanLength = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
        const float spanFlat = std::hypot(span.x, span.z);
        // In a car: a stride behind the bumper, but the low close chase (row 22) is only
        // that far back to begin with, so no more than three quarters of the way out.
        const float minPull = inVehicle ? (std::min)(1.4f + 0.5f * extraLength_ + 0.5f * extraHeight_, 0.75f * spanLength) : 0.5f;
        float wantLift = 0.0f;
        // Something overhead (a sign gantry, a railway bridge over the road): the camera
        // goes down under it at the same distance, and neither pulls in nor swings up.
        // Before, the line to the camera met the gantry, the camera was pulled 1-4 blocks
        // toward the car in one frame (the ease allows a block of lag) and then craned up
        // over it, every time a car passed under one (PERF-2, Downtown carriageway).
        bool under = false;
        if (desired.y > pivot.y + 0.1f && reachTo(pivot, desired) < 0.999f) {
            for (int k = 1; k <= 4 && !under; ++k) {
                gta2::Vec3 lower = desired;
                lower.y = desired.y - (desired.y - (pivot.y + 0.05f)) * static_cast<float>(k) / 4.0f;
                // only a true overhead: the ground beneath the camera's spot is open at the car's level
                if (reachTo(pivot, lower) >= 0.999f) { desired = lower; under = true; }
            }
        }
        if (under) {
            liftAngle_ += (0.0f - liftAngle_) * (1.0f - std::exp(-dt / 0.6f));
        } else if (spanLength > 1e-3f && spanFlat > 1e-3f) {
            const float a0 = std::atan2(span.y, spanFlat);
            // On foot at most 45 degrees (FIX-CAMERA): at 75 the camera hung over him looking
            // straight down at the paving while he stood with his back to a wall (feel probe
            // punch bursts); past 45 the boom shortens instead (the boom filter below).
            // In a car at most 40 (FIX-CAMERA-2): at 75 a van backed into a wall had the camera
            // straight over its roof looking down for ~3 s (feel8-third-reverse-into-wall-camera-
            // straight-down-onto-roof); past 40 the boom shortens instead, and the pitch below is
            // held at 35 degrees down.
            const float aMax = (std::max)(a0, (inVehicle ? (CameraCarPitchCapOn() ? 40.0f : 75.0f) : 45.0f) * kDegToRad);
            auto at = [&](float a) {
                return gta2::Vec3{pivot.x + span.x / spanFlat * std::cos(a) * spanLength, pivot.y + std::sin(a) * spanLength,
                                  pivot.z + span.z / spanFlat * std::cos(a) * spanLength};
            };
            if (reachTo(pivot, desired) * spanLength < minPull) {
                for (int k = 1; k <= 6; ++k) {
                    const float a = a0 + (aMax - a0) * k / 6.0f;
                    if (reachTo(pivot, at(a)) * spanLength >= minPull) {
                        wantLift = a - a0;
                        break;
                    }
                }
            }
            // FIX-CAMERA-14 (pfl65 camera half): over a car that hides him. A jammed truck's cab between the lens and him
            // on foot left him getting up and walking tiny and half-hidden behind its bonnet for ~3 s (run pfl65a 10.5 s);
            // the street objects' fade is for props, and a turn round the car (FIX-CAMERA-13, cam13_kd1) found no win. When
            // another car's body crosses the line from the eye to his chest for kRiseDwell (a car passing in traffic crosses
            // it in less), the boom rises on its arc, same length, to the smallest lift (of the six to the on-foot 45 degree
            // cap) whose line clears to his chest, else to his head; held kRiseKeep after, then eased down like a wall's
            // lift. Only above a wall's own lift; the turn and the boom filter are untouched. GTA2DX9_CAM_CAR_RISE=0 (A/B).
            if (!inVehicle && mode == ViewMode::ThirdPerson && CameraCarsOn()) {
                static int riseOn = -1;
                if (riseOn < 0) { char b[8] = {}; riseOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_RISE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                constexpr float kRiseDwell = 0.3f, kRiseKeep = 1.0f;
                const gta2::Vec3 chest{px, baseY + 0.30f, pz}, head{px, baseY + 0.42f, pz};
                // FIX-CAMERA-15: asked of the eye with the wall's lift only, not the car rise already shown: from the risen
                // eye the car no longer hid him, the hold ran out and the lens came back down behind the cab (run cam15_occ6
                // 8-10 s), so the rise hunted.
                const gta2::Vec3 from = wantLift > 0.0f ? at(a0 + wantLift) : desired;
                // FIX-CAMERA-15: only cars standing (or creeping, under kStillSpeed): CAMERA-14's rise craned over trucks
                // passing in traffic (run cam14_rise2); a car going by hides him for a moment, as in any chase view.
                constexpr float kStillSpeed = 0.6f;
                CarMotionUpdate(dt);
                const bool hides = riseOn && CarHidesPoint(from, chest, kStillSpeed);
                carRiseT_ = hides ? carRiseT_ + dt : 0.0f;
                if (hides && carRiseT_ >= kRiseDwell) carRiseHold_ = kRiseKeep;
                else carRiseHold_ = (std::max)(0.0f, carRiseHold_ - dt);
                if (carRiseHold_ > 0.0f) {
                    float rise = -1.0f;
                    for (const gta2::Vec3* target : {&chest, &head}) {
                        for (int k = 0; k <= 6 && rise < 0.0f; ++k) {
                            const float a = a0 + (aMax - a0) * k / 6.0f;
                            const gta2::Vec3 e = at(a);
                            if (!CarHidesPoint(e, *target, kStillSpeed) && reachTo(pivot, e) * spanLength >= minPull) rise = a - a0;
                        }
                        if (rise >= 0.0f) break;
                    }
                    if (rise < 0.0f) rise = aMax - a0;
                    // a lift already shown is kept while held (no hunting down onto the roof between frames)
                    rise = (std::max)(rise, hides ? 0.0f : liftAngle_);
                    if (rise > wantLift) {
                        if (cameraLogOn()) {
                            static int every = 0;
                            if ((++every % 10) == 1) Log("cam: car hides him (%.2f s): rise %.1f deg (wall lift %.1f)%s", carRiseT_, rise / kDegToRad,
                                                         wantLift / kDegToRad, hides ? "" : " kept");
                        }
                        wantLift = rise;
                    }
                }
            }
            // Up quickly (a wall is coming), down slowly (it has gone).
            liftAngle_ += (wantLift - liftAngle_) * (1.0f - std::exp(-dt / (wantLift > liftAngle_ ? 0.15f : 0.6f)));
            if (liftAngle_ < 1e-3f) liftAngle_ = 0.0f;
            if (liftAngle_ > 0.0f) desired = at(a0 + liftAngle_);
        }
        const float reach = reachTo(pivot, desired);
        desired = pivot + (desired - pivot) * reach;
        // Pulled in toward him by a wall the arc could not clear: the camera stays on
        // the boom's line, shortened (the boom filter below), looking where the rig looks.
        // It used to crane up to 1.2 blocks over him and swing 30-120 degrees round him
        // within a frame or two, and the framing below then looked down at the paving
        // (feel-armed-third-camera-collapses-to-eye-looking-down, chase-cam-foot-snap-cuts):
        // on the boom's line his head stays where the rig puts it in the picture.
    }
    // And never under the floor it is over.
    if (q.floorAt) {
        float under = 0.0f;
        if (q.floorAt(q.context, desired.x, desired.z, desired.y + 0.05f, &under) && desired.y < under + 0.25f) {
            desired.y = under + 0.25f;
        }
    }
    // Nor a few centimetres from a fence. Railings, grilles and signs are flat
    // panels the camera may look through, so they do not stop it; but a camera
    // that comes to rest inside a railing's block within a hand of the panel
    // sees nothing but its texels (the whole frame goes to black bars and
    // holes). Then it goes on through to the far side, and if that is solid,
    // stops short of the panel instead.
    // On foot with the mesh solve, not this: a railing is a sheet there (eye_collision.cpp,
    // WorldMesh::railingPanels) and a flat panel a two-sided face, so the boom already stops
    // short of either; going on through put the camera behind the plaza fence looking through
    // its bars for 9 s (feel25).
    if (q.panelDistance && !meshSolve) {
        constexpr float kClear = 0.35f;
        float d = 0.0f;
        if (q.panelDistance(q.context, desired.x, desired.y, desired.z, &d) && d < kClear) {
            const gta2::Vec3 pivot{px, baseY + 0.6f, pz};
            gta2::Vec3 dir = desired - pivot;
            const float len = std::sqrt(dir.x * dir.x + dir.y * dir.y + dir.z * dir.z);
            if (len > 1e-3f) {
                dir = dir * (1.0f / len);
                bool placed = false;
                for (int step = 1; step <= 12 && !placed; ++step) {
                    const gta2::Vec3 p = desired + dir * (0.1f * step);
                    if (q.blocked && solidAt(p.x, p.y, p.z)) break;
                    float pd = 0.0f;
                    if (!q.panelDistance(q.context, p.x, p.y, p.z, &pd) || pd >= kClear) {
                        desired = p;
                        placed = true;
                    }
                }
                if (!placed) {
                    // Back toward him, to a hand's breadth before the panel.
                    const float back = (std::min)(len - 0.5f, kClear + d);
                    if (back > 0.0f) desired = desired - dir * back;
                }
            }
        }
    }

    // Nor inside a street object (QA3: after answering the tutorial phone the camera
    // stood in the phone box, its glass and roof filling the frame). The game's
    // objects drawn as models are upright cylinders round their footprint, widened
    // to the box's corners (GatherObstacles); the camera keeps 0.15 block clear of
    // one. Over a low one (a phone box, a bin, a cone) it rises above the roof at the
    // same spot; a tall one (a traffic light's pole), or one with no room above, it
    // stands in front of, toward him; when he stands at it, round its side.
    static std::vector<Obstacle> obstacles;
    GatherObstacles(px, pz, distance + 3.0f, false, &obstacles, !inVehicle);
    // Only what stands on the ground about his level: a traffic light's head over the
    // road is passed under or beside, never hopped over.
    obstacles.erase(std::remove_if(obstacles.begin(), obstacles.end(),
                                   [&](const Obstacle& o) { return o.y0 > baseY + 0.6f || o.y0 < baseY - 1.5f; }),
                    obstacles.end());
    auto clearOfObstacles = [&](gta2::Vec3 e) {
        constexpr float kPropClear = 0.15f;
        for (int iter = 0; iter < 3; ++iter) {
            const Obstacle* o = ObstacleAt(obstacles, e, kPropClear, false);
            if (!o) break;
            const float top = o->y1 + 0.3f;   // well over the roof, not skimming it
            const gta2::Vec3 over{e.x, top, e.z};
            if (!o->tree && top - e.y < 0.9f && !(q.blocked && solidAt(over.x, over.y, over.z)) &&
                (!q.blocked || reachTo(pivot, over) >= 1.0f)) {
                e = over;
                continue;
            }
            const float rim = o->r + kPropClear + 0.01f;
            const gta2::Vec3 toE = e - pivot;
            const float flat = std::hypot(toE.x, toE.z);
            bool moved = false;
            if (flat > 1e-3f) {
                // Where the line from him (seen from above) enters the widened circle.
                const float dx = toE.x / flat, dz = toE.z / flat;
                const float fx = pivot.x - o->x, fz = pivot.z - o->z;
                const float b = fx * dx + fz * dz, c = fx * fx + fz * fz - rim * rim;
                const float disc = b * b - c;
                if (c > 0.0f && disc > 0.0f) {
                    const float enter = -b - std::sqrt(disc);
                    if (enter > 0.35f && enter < flat) {
                        e = pivot + toE * (enter / flat);
                        moved = true;
                    }
                }
            }
            if (!moved) {
                float ox = e.x - o->x, oz = e.z - o->z;
                float len = std::hypot(ox, oz);
                if (len < 1e-3f) { ox = -std::sin(yaw); oz = -std::cos(yaw); len = 1.0f; }
                const gta2::Vec3 side{o->x + ox / len * rim, e.y, o->z + oz / len * rim};
                if (!(q.blocked && solidAt(side.x, side.y, side.z))) e = side;
                else if (!(q.blocked && solidAt(over.x, over.y, over.z))) e = over;
                else break;
            }
        }
        return e;
    };
    desired = clearOfObstacles(desired);

    // The camera moves with him first, so that at a steady speed it never
    // trails, and is then eased onto where it wants to be: a swing or a pull-in
    // is spread over a few frames, straight-line motion is not.
    // How long the solve lets the boom be this frame (the boom filter below compares
    // it with the rig's own length to tell a pull-in from the eye's ordinary lag).
    const float solveLen = std::sqrt((desired.x - pivot.x) * (desired.x - pivot.x) + (desired.y - pivot.y) * (desired.y - pivot.y) +
                                     (desired.z - pivot.z) * (desired.z - pivot.z));
    if (swingCut || carDriveOffCut) {   // FIX-CAMERA-10: the cut round the staircase is drawn as a cut (the solved pose at once)
        snapEye_ = true;
        boomKnown_ = false;
    }
    if (snapEye_) {
        // The first frame after a warp, a respawn or a level cut: the eye on the solved
        // rig at once. It used to start on his head (py + 1) and ease out from there, so
        // the first frames looked down at the paving from inside him
        // (feel-armed-third-camera-collapses-to-eye-looking-down).
        eyeX_ = desired.x;
        eyeY_ = desired.y;
        eyeZ_ = desired.z;
        velX_ = velZ_ = 0.0f;
        lastPitchKnown_ = false;
        finalYawKnown_ = false;
        shownPoseKnown_ = false;
        snapEye_ = false;
    }
    eyeX_ += velX_ * dt;
    eyeZ_ += velZ_ * dt;
    // Just after a discontinuity (in or out of a car, thrown, down) the ease is
    // slower and the lag allowed larger, so the move is a glide (blend_).
    const float ease = 1.0f - std::exp(-dt / (0.09f + 0.35f * blend_ + 0.3f * deathMix_ * (1.0f - deathMix_)));
    eyeX_ += (desired.x - eyeX_) * ease;
    eyeY_ += (desired.y - eyeY_) * ease;
    eyeZ_ += (desired.z - eyeZ_) * ease;
    // But never further than a block from where it should be - a cut, a wall -
    // which is where easing would show as the camera arriving late.
    {
        const float maxLag = 1.0f + 5.0f * blend_;
        const float dx = desired.x - eyeX_, dy = desired.y - eyeY_, dz = desired.z - eyeZ_;
        const float away = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (away > maxLag) {
            const float pull = (away - maxLag) / away;
            eyeX_ += dx * pull;
            eyeY_ += dy * pull;
            eyeZ_ += dz * pull;
        }
    }
    // The eased eye is checked again: on its way it may cut a corner the wanted
    // spot does not (a swing round a building, a pull-in): never through a wall,
    // and a hand's breadth clear of one, so the near plane does not enter it.
    if (s.tpCollide && q.blocked) {
        gta2::Vec3 e{eyeX_, eyeY_, eyeZ_};
        float t = reachTo(pivot, e);
        if (t < 1.0f && desired.y < e.y) {
            // On its way down under an overhead (above): the eased eye at the wanted
            // height first, rather than pulled in along the ray.
            const gta2::Vec3 lower{e.x, desired.y, e.z};
            if (reachTo(pivot, lower) >= 1.0f) { e = lower; t = 1.0f; }
        }
        if (t < 1.0f) {
            // Cut off by a corner on its way (the car turning past a building): the nearest
            // point toward the wanted spot that the car can see, rather than pulled in along
            // the ray, which put the camera a block from the car for one frame and back the
            // next (PERF-2: 10-20 such one-frame dips a minute while driving).
            for (int k = 1; k <= 4 && t < 1.0f; ++k) {
                const gta2::Vec3 toward = e + (desired - e) * (static_cast<float>(k) / 4.0f);
                if (reachTo(pivot, toward) >= 1.0f) { e = toward; t = 1.0f; }
            }
        }
        if (t < 1.0f) e = pivot + (e - pivot) * t;
        constexpr float kRadius = 0.1f;
        auto clear = [&](const gta2::Vec3& p) {
            return !solidAt(p.x + kRadius, p.y, p.z) && !solidAt(p.x - kRadius, p.y, p.z) &&
                   !solidAt(p.x, p.y, p.z + kRadius) && !solidAt(p.x, p.y, p.z - kRadius) &&
                   !solidAt(p.x, p.y + 0.07f, p.z);
        };
        const gta2::Vec3 back = pivot - e;
        const float backLength = std::sqrt(back.x * back.x + back.y * back.y + back.z * back.z);
        for (int i = 0; i < 10 && backLength > 1e-3f && !clear(e); ++i) {
            const float stepLength = (std::min)(0.04f, backLength * 0.1f);
            e = e + back * (stepLength / backLength);
        }
        eyeX_ = e.x;
        eyeY_ = e.y;
        eyeZ_ = e.z;
    }
    {
        // The eased eye too: on its way it may pass through a phone box the wanted spot is clear of.
        const gta2::Vec3 e = clearOfObstacles({eyeX_, eyeY_, eyeZ_});
        eyeX_ = e.x;
        eyeY_ = e.y;
        eyeZ_ = e.z;
    }

    // FIX-CAMERA: the boom filter. The solve above says where the camera may be (eyeX_,
    // its state, kept as it was); what is shown sits on the same line from the pivot at
    // boom_, a length with a capped rate. A pull-in shortens it at most kBoomIn blocks a
    // second (the solve used to move the eye 0.7 block toward his head in one frame and
    // straight back out the next: chase-cam-foot-snap-cuts, cam: third back=0.68 ->
    // 0.07 -> 0.00); it lengthens only once the solve has left it alone for kBoomHold
    // seconds, then eased at most kBoomOut a second (a car grinding along a wall, its
    // heading wobbling, pumped the boom a block every two seconds:
    // pt-chase-camera-pumps-against-wall). Never shorter than half a block or so from his
    // head on foot, and outside the car's own body at the wheel (the eye once sat inside
    // the van's roof). The camera's orientation is the rig's along that line: a pull-in
    // slides the camera along the boom and turns nothing, as a spring arm does.
    gta2::Vec3 orientEye{eyeX_, eyeY_, eyeZ_};
    float pulledShort = 0.0f, rigLength = 0.0f;   // FIX-CAMERA-6: how much shorter than the rig the boom is shown
    {
        constexpr float kBoomIn = 9.0f, kBoomOut = 2.2f, kBoomHold = 0.3f;
        const gta2::Vec3 solved{eyeX_, eyeY_, eyeZ_};
        const gta2::Vec3 arm = solved - pivot;
        const float armLen = std::sqrt(arm.x * arm.x + arm.y * arm.y + arm.z * arm.z);
        const gta2::Vec3 rigArm = rigEye - pivot;
        const float rigLen = std::sqrt(rigArm.x * rigArm.x + rigArm.y * rigArm.y + rigArm.z * rigArm.z);
        // The boom's direction: the solved eye's, turned toward at a capped rate (4 rad/s:
        // the shown yaw is capped at the turn rate anyway, so no turn is slowed, but a prop
        // clearance or a corner that lifts the solved eye no longer swings a short boom over
        // his head in one frame, run fixcam_feel3). Pulled in to under 0.35 block, the solved
        // eye's direction from the pivot is noise (the eye height jumped half a block a frame,
        // run fixcam_wall1): the boom turns toward the rig's own direction instead, slower.
        float armLag = 0.0f;   // FIX-CAMERA-10: radians the shown boom trails the solved eye's direction (after its turn)
        bool swingEase = false;  // FIX-CAMERA-10: the boom eases in at a sheet while a fast swing goes round (below)
        if (!boomKnown_ || inVehicle != boomInVehicle_) {
            const gta2::Vec3 d = armLen > 0.05f ? arm : rigArm;
            const float l = (std::max)(std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z), 1e-4f);
            armDirX_ = d.x / l;
            armDirY_ = d.y / l;
            armDirZ_ = d.z / l;
        } else if (armLen > 0.35f || rigLen > 1e-3f) {
            const bool own = armLen > 0.35f;
            const gta2::Vec3 want = own ? gta2::Vec3{arm.x / armLen, arm.y / armLen, arm.z / armLen}
                                        : gta2::Vec3{rigArm.x / rigLen, rigArm.y / rigLen, rigArm.z / rigLen};
            const float c = (std::max)(-1.0f, (std::min)(1.0f, armDirX_ * want.x + armDirY_ * want.y + armDirZ_ * want.z));
            const float angle = std::acos(c);
            // FIX-CAMERA-10: after a fast swing (swingClearHold_) the shown boom follows it at 7 rad/s, not 4: trailing,
            // its line still crossed the stair's sheet and the pull-in cut once the swing had arrived (run cam10_p14b).
            const float armRate = own ? (swingClearHold_ > 0.0f ? 7.0f : 4.0f) : 2.5f;
            const float t = angle > 1e-4f ? (std::min)(1.0f, armRate * dt / angle) : 1.0f;
            armLag = angle * (1.0f - t);
            const float nx = armDirX_ + (want.x - armDirX_) * t, ny = armDirY_ + (want.y - armDirY_) * t, nz = armDirZ_ + (want.z - armDirZ_) * t;
            const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
            if (nl > 1e-4f) { armDirX_ = nx / nl; armDirY_ = ny / nl; armDirZ_ = nz / nl; }
        }
        float halfLen = 0.6f;
        if (inVehicle && exitCar_ == player.vehicle && exitCarHalfLength_ > 0.1f) halfLen = exitCarHalfLength_;
        // On foot 0.6 block measured flat (the boom may be lifted up to 45 degrees over a wall
        // behind him; a 3D 0.6 then put the eye 0.52 behind him, nearly over his head).
        const float flatPart = (std::max)(std::hypot(armDirX_, armDirZ_), 0.5f);
        const float minBoom = (std::min)(inVehicle ? halfLen + 0.15f : 0.6f / flatPart, (std::max)(rigLen, 0.1f));
        const float target = (std::max)(armLen, minBoom);
        const bool pulled = solveLen < rigLen - 0.15f || armLen < (std::min)(solveLen, boom_) - 0.15f;
        boomClear_ = pulled ? 0.0f : boomClear_ + dt;
        const float boomAtStart = boomKnown_ && inVehicle == boomInVehicle_ ? boom_ : -1.0f;   // FIX-CAMERA-6: one rate a frame
        // FIX-CAMERA-8 (pfl14-third-on-foot-plaza-camera-lunge-and-roll): a see-through sheet he stands against
        // (the iron staircase's rail at the wil plaza, 0.2-0.45 from his centre) is crossed by the boom's line on
        // and off as he steps and turns; each crossing pulled the boom in at kBoomIn (9 blocks/s: 2.1 -> 0.06 in 7
        // frames, run cam8_p14a; 1.15 -> 0.55 in 2 frames on a one-frame crossing, cam8_p14b), it grew back at
        // kBoomOut after a hold, and the view lunged in and looked down 50-60 degrees over him (the "roll" in the
        // report is that pitch's perspective: the camera's roll stayed 0). With nothing solid on the shown line
        // out to the boom's length, and a sheet on it (if any) with the lens at least kLensPast beyond it (the
        // rail is see-through; runs cam8_p14e/z: sheets 0.95-1.33 from him, the lens 0.5-0.9 past), the boom comes in at
        // kSheetIn instead: a crossing of a frame or two costs a few centimetres, a lasting one is a glide over
        // half a second or more while the swing finds the open side. A wall, or a sheet nearer the lens, still
        // pulls it in at once. OFF by default: GTA2DX9_CAM_SHEET_EASE=1 turns it on. Not shipped: at the iron staircase it
        // held the lens beyond the stair's rail sheet while the solve wanted 0.3, filming the treads with him hidden
        // behind them for ~10 frames (run cam8_p14H): the treads seen from below are no wall to SegmentHitSolid.
        float inRate = kBoomIn;
        {
            static int sheetEaseOn = -1;
            if (sheetEaseOn < 0) { char b[8] = {}; sheetEaseOn = GetEnvironmentVariableA("GTA2DX9_CAM_SHEET_EASE", b, sizeof b) && atoi(b) == 1 ? 1 : 0; }
            constexpr float kSheetIn = 2.5f, kLensPast = 0.45f;
            // FIX-CAMERA-10: also while the swing turns fast onto a clear heading (swingClearing, above), with the
            // lens kept 0.45 over the floor beneath it (cam8_p14H: 0.22 over the stair's treads, behind its rail).
            swingEase = swingClearing || (swingClearHold_ > 0.0f && armLag > 8.0f * kDegToRad);
            if ((sheetEaseOn || swingEase) && meshSolve && s.tpCollide && boomAtStart > 1e-3f) {
                const gta2::Vec3 tip{shownPivot.x + armDirX_ * boomAtStart, shownPivot.y + armDirY_ * boomAtStart,
                                     shownPivot.z + armDirZ_ * boomAtStart};
                float ta = 1.0f, tw = 1.0f;
                const bool hitAny = eyecol::SegmentHit(shownPivot, tip, &ta);
                // solid: a wall or a solid cell on the line short of the lens (the lens itself near a surface is
                // the berth's and the near fade's business, not a reason to cut)
                const float upTo = (std::max)(0.0f, 1.0f - 0.15f / boomAtStart);
                const bool meshWall = eyecol::SegmentHitSolid(shownPivot, tip, &tw) && tw < upTo;
                // The mesh only: the cells' false walls (the iron staircase's cells at wil 159.5,139.5, solid where
                // the drawn stair is air: run cam8_p14k) vetoed every crossing; on foot the boom is the mesh's.
                const bool cellWall = false;
                const bool solid = meshWall;
                if (cameraLogVerbose() && (solid || hitAny))
                    Log("cam: sheet ease test: mesh wall %d at %.2f, cell wall %d, sheet %d at %.2f, boom %.2f", meshWall ? 1 : 0,
                        tw * boomAtStart, cellWall ? 1 : 0, hitAny ? 1 : 0, ta * boomAtStart, boomAtStart);
                if (!solid && (!hitAny || ta * boomAtStart <= boomAtStart - kLensPast)) {
                    inRate = kSheetIn;
                    if (cameraLogVerbose()) Log("cam: sheet ease (%s)", hitAny ? "a sheet by him" : "clear line");
                } else if (!solid && hitAny) {
                    // The lens closing on the sheet it is beyond: across it at 12 % of the boom a frame (run cam8_p14C:
                    // 1.46 -> 0.87 in two frames at kBoomIn), still a move of a few frames, not a cut.
                    inRate = (std::min)(kBoomIn, (std::max)(kSheetIn, 3.6f * boomAtStart));
                    if (cameraLogVerbose()) Log("cam: sheet ease (crossing at the lens)");
                }
            }
        }
        if (!boomKnown_ || inVehicle != boomInVehicle_) {
            // Afresh (third person entered, a warp) or the frame he got in or out: from
            // where the eye is, so the hand-over is continuous.
            boom_ = (std::max)(armLen, minBoom);
            boomKnown_ = true;
            boomInVehicle_ = inVehicle;
            boomClear_ = 0.0f;
        } else if (target < boom_) {
            boom_ = (std::max)(target, boom_ - inRate * dt);
        } else if (boomClear_ >= kBoomHold || !pulled) {
            // Lengthening: at once by a hair (the rig breathing with speed), eased and
            // capped for a release after a pull-in.
            const float gap = target - boom_;
            const float step = boomClear_ >= kBoomHold ? (std::max)(0.25f * dt, gap * (1.0f - std::exp(-dt / 0.3f))) : 0.25f * dt;
            boom_ += (std::min)(gap, (std::min)(step, kBoomOut * dt));
        }
        const gta2::Vec3 dir{armDirX_, armDirY_, armDirZ_};
        // FIX-CAMERA-3: the minimum boom does not push the shown eye through what the mesh says is
        // in the way (the staircase's rail behind him: the 0.6 minimum put the lens among its bars).
        // Too close to him that way is handled below (over his head, never inside the figure).
        // FIX-CAMERA-6 (pfeel3-third-punch-contact-camera-cuts-in-one-frame-to-overhead): a wall on the way still
        // stops the boom at once (the lens may not be behind a wall), but a two-sided sheet (a railing, a sign
        // panel: see-through) or a railing's own bars (eyecol kBar faces) pull it in at the boom's own rate. Cut at once, the plaza fence behind him at the
        // owner demo's punch spot took the eye from 2.14 block behind into his head in one frame, and the frame
        // clamp then turned the view 122 degrees and 26 down in the same frame (run cam6_tp_base, punch_1).
        // GTA2DX9_CAM_SOFT_PANELS=0 cuts at a sheet as before (A/B).
        if (meshSolve && s.tpCollide && boom_ > 1e-3f) {
            static int softPanels = -1;
            if (softPanels < 0) { char b[8] = {}; softPanels = GetEnvironmentVariableA("GTA2DX9_CAM_SOFT_PANELS", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            const float boom0 = boom_;
            const gta2::Vec3 tip{shownPivot.x + dir.x * boom0, shownPivot.y + dir.y * boom0, shownPivot.z + dir.z * boom0};
            float tw = 1.0f, ta = 1.0f;
            const bool hitWall = softPanels ? eyecol::SegmentHitSolid(shownPivot, tip, &tw) : false;
            const bool hitAny = eyecol::SegmentHit(shownPivot, tip, &ta);
            if (hitWall) {
                // A wall too pulls in at the boom's rate while the slower eye is still in the open (a corner edge
                // he walks round sweeps across the boom's line: the eye is in clear air on the far side of it and
                // the wall only hides part of him for a frame or two); at once when the slower eye would be in a
                // solid block or within a near plane's reach of a surface (walking back into a wall).
                const float want = (std::max)(0.0f, tw * boom0 - kMeshClear);
                if (want < boom_) {
                    const float slow = softPanels && boomAtStart > 0.0f ? (std::min)(boom_, (std::max)(want, boomAtStart - kBoomIn * dt)) : want;
                    const gta2::Vec3 at{shownPivot.x + dir.x * slow, shownPivot.y + dir.y * slow, shownPivot.z + dir.z * slow};
                    const bool open = slow > want && !eyecol::InsideSolid(at) && eyecol::Nearest(at, 0.2f) >= 0.14f &&
                                      !(q.blocked && solidAt(at.x, at.y, at.z));
                    boom_ = open ? slow : want;
                    if (open && cameraLogOn()) {
                        static int every = 0;
                        if ((++every % 10) == 1) Log("cam: boom eased in at a wall edge: len=%.2f wall at %.2f", boom_, want);
                    }
                }
            }
            if (hitAny && (!hitWall || ta < tw - 1e-4f)) {
                const float want = (std::max)(0.0f, ta * boom0 - kMeshClear);
                if (!softPanels) boom_ = (std::min)(boom_, want);
                else if (want < boom_) {
                    boom_ = boomAtStart > 0.0f ? (std::min)(boom_, (std::max)(want, boomAtStart - inRate * dt)) : want;
                    if (cameraLogOn()) {
                        static int every = 0;
                        if ((++every % 10) == 1) Log("cam: boom eased in at a sheet: len=%.2f sheet at %.2f", boom_, ta * boom0);
                    }
                }
            }
        }
        // FIX-CAMERA-10 (pmt2-wil-third-camera-inside-phone-booth-blue-panes-wash-a-quarter-of-the-frame): the shown
        // boom against the street objects. The solve keeps the solved eye out of a phone box (clearOfObstacles), but
        // the shown lens sits on the boom's own line at its eased length and direction, which trail the solve: as he
        // turned by the plaza phone box the lens went into it and its blue panes and mirrored sign washed a quarter to
        // half of the frame (evidence pmt2). The first object the shown line enters (cylinder widened by 0.12, from
        // 0.35 out) stops the lens 0.05 short of it, eased in at the boom's rate while the slower lens is outside every
        // object, at once otherwise. GTA2DX9_CAM_PROP_BOOM=0 turns it off (A/B).
        if (meshSolve && s.tpCollide && boom_ > 0.4f && !obstacles.empty()) {
            static int propBoomOn = -1;
            if (propBoomOn < 0) { char b[8] = {}; propBoomOn = GetEnvironmentVariableA("GTA2DX9_CAM_PROP_BOOM", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            constexpr float kPropLens = 0.12f;
            float enter = -1.0f;
            const Obstacle* hit = nullptr;
            for (float d = 0.35f; propBoomOn && d <= boom_ + 0.05f; d += 0.05f) {
                const float dd = (std::min)(d, boom_);
                const gta2::Vec3 p{shownPivot.x + armDirX_ * dd, shownPivot.y + armDirY_ * dd, shownPivot.z + armDirZ_ * dd};
                if ((hit = ObstacleAt(obstacles, p, kPropLens, false)) != nullptr) { enter = dd; break; }
            }
            if (cameraLogOn()) {
                static int every = 0;
                if ((++every % 30) == 1) {
                    const gta2::Vec3 lens{shownPivot.x + armDirX_ * boom_, shownPivot.y + armDirY_ * boom_, shownPivot.z + armDirZ_ * boom_};
                    float best = 1e9f; const Obstacle* nb = nullptr;
                    for (const Obstacle& o : obstacles) { const float dd = std::hypot(o.x - lens.x, o.z - lens.z); if (!o.post && dd < best) { best = dd; nb = &o; } }
                    if (nb) Log("cam: props by the boom: %d, nearest to the lens %.2f (at %.2f,%.2f r %.2f, %.2f..%.2f, lens y %.2f)", (int)obstacles.size(), best, nb->x,
                                nb->z, nb->r, nb->y0, nb->y1, lens.y);
                }
            }
            // FIX-CAMERA-17: under the turn budget an object only BETWEEN the lens and him does not shorten the boom:
            // it fades as a foreground occluder (map_objects.cpp, FIX-CAMERA-12), and the shortening put the lens on
            // his shoulder beside the wil phone box (boom 0.30, the frame clamp flipping the pitch -11/-38 every
            // frame, the hero off the frame's edge: run cam17_f1). Only a lens that would stand in the object's widened
            // cylinder stops short of it, and only from 0.6 out; nearer him the berth below moves the lens aside.
            if (enter > 0.0f && CameraTurnBudgetDeg() > 0.0f) {
                const gta2::Vec3 lensP{shownPivot.x + armDirX_ * boom_, shownPivot.y + armDirY_ * boom_, shownPivot.z + armDirZ_ * boom_};
                const bool lensIn = ObstacleAt(obstacles, lensP, kPropLens, false) != nullptr;
                if (!lensIn || enter < 0.6f) {
                    if (cameraLogOn()) {
                        static int every = 0;
                        if ((++every % 10) == 1)
                            Log("cam: prop on the boom at %.2f kept len=%.2f (%s; object at %.2f,%.2f)", enter, boom_,
                                lensIn ? "at him: the berth moves the lens aside" : "between the lens and him: it fades", hit->x, hit->z);
                    }
                    enter = -1.0f;
                }
            }
            if (enter > 0.0f) {
                const float want = (std::max)(0.3f, enter - 0.05f);
                // FIX-CAMERA-16: past a tree's trunk over about 0.3 s (4 blocks/s), not kBoomIn's 0.1 s: while the lens
                // is still behind the trunk the tree fades (ChaseTreeAlpha, "across the line to him").
                const float rateIn = hit && hit->tree ? 4.0f : kBoomIn;
                const float slow = boomAtStart > 0.0f ? (std::max)(want, boomAtStart - rateIn * dt) : want;
                const gta2::Vec3 at{shownPivot.x + armDirX_ * slow, shownPivot.y + armDirY_ * slow, shownPivot.z + armDirZ_ * slow};
                // FIX-CAMERA-17: under the turn budget the shortening is eased all the way unless the eased lens would
                // be inside the object itself (its cylinder, not the 0.12 widening): the snap to `want` was a jump of
                // the lens of up to a block in a frame beside the phone box, which the frame clamp turned into yaw.
                const float snapMargin = CameraTurnBudgetDeg() > 0.0f ? 0.0f : kPropLens;
                boom_ = (std::min)(boom_, ObstacleAt(obstacles, at, snapMargin, false) ? want : slow);
                if (cameraLogOn()) Log("cam: prop on the boom at %.2f: len=%.2f (object at %.2f,%.2f r %.2f, %.2f..%.2f)", enter, boom_, hit->x, hit->z,
                                       hit->r, hit->y0, hit->y1);
            }
        }
        if (s.tpCollide) {
            eyeX_ = shownPivot.x + dir.x * boom_;
            eyeY_ = shownPivot.y + dir.y * boom_;
            eyeZ_ = shownPivot.z + dir.z * boom_;
            // FIX-CAMERA-10: while the boom eases round a fast swing its line may pass over a staircase beside him
            // (the wil iron stair: the shown arm trails the swing across the treads, run cam10_p14n): the lens keeps
            // 0.45 over the floor beneath it there instead of skimming the treads (cam8_p14H: 0.2 over them).
            // FIX-CAMERA-10 (pmt2): and a berth off the street objects: a lens beside the phone box (not on the line to
            // him) still had its blue panes down a frame edge (run cam10_pmt2b, flamethrower fire_walk_01). Inside an
            // object's widened cylinder below its roof, the lens moves straight out from its axis, never through the mesh.
            // FIX-CAMERA-17: under the turn budget the berth is an offset eased toward what it wants at kBerthRate
            // blocks a second both ways (propBerthX_/Z_), at once only while the lens is inside the object's body
            // itself: the snap out of the widened cylinder was a lens jump each frame he turned by the phone box.
            const bool berthEase = CameraTurnBudgetDeg() > 0.0f;
            float berthWantX = 0.0f, berthWantZ = 0.0f;
            bool berthSnap = false;
            if (meshSolve && !obstacles.empty()) {
                static int propBerthOn = -1;
                if (propBerthOn < 0) { char b[8] = {}; propBerthOn = GetEnvironmentVariableA("GTA2DX9_CAM_PROP_BOOM", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                constexpr float kPropBerth = 0.15f;
                const gta2::Vec3 e{eyeX_, eyeY_, eyeZ_};
                const Obstacle* o = propBerthOn ? ObstacleAt(obstacles, e, kPropBerth, false) : nullptr;
                if (o && e.y < o->y1 + 0.1f) {
                    float ox = e.x - o->x, oz = e.z - o->z;
                    float len = std::hypot(ox, oz);
                    if (len < 1e-3f) { ox = e.x - shownPivot.x; oz = e.z - shownPivot.z; len = (std::max)(std::hypot(ox, oz), 1e-3f); }
                    const float rim = o->r + kPropBerth + 0.01f;
                    const gta2::Vec3 out{o->x + ox / len * rim, e.y, o->z + oz / len * rim};
                    float t = 1.0f;
                    if (!eyecol::SegmentHit(shownPivot, out, &t) && !ObstacleAt(obstacles, out, kPropBerth, false)) {
                        if (berthEase) {
                            berthWantX = out.x - e.x;
                            berthWantZ = out.z - e.z;
                            berthSnap = len < o->r;
                        } else {
                            eyeX_ = out.x;
                            eyeZ_ = out.z;
                        }
                        if (cameraLogOn()) Log("cam: prop berth moved %.2f (object at %.2f,%.2f)%s", rim - len, o->x, o->z,
                                               berthEase ? (berthSnap ? " at once (inside it)" : " eased") : "");
                    }
                }
            }
            if (berthEase) {
                constexpr float kBerthRate = 2.5f;
                if (berthSnap || !boomKnown_) { propBerthX_ = berthWantX; propBerthZ_ = berthWantZ; }
                else {
                    const float dx = berthWantX - propBerthX_, dz = berthWantZ - propBerthZ_, d = std::hypot(dx, dz);
                    const float k = d > kBerthRate * dt ? kBerthRate * dt / d : 1.0f;
                    propBerthX_ += dx * k;
                    propBerthZ_ += dz * k;
                }
                if (propBerthX_ != 0.0f || propBerthZ_ != 0.0f) {
                    const gta2::Vec3 to{eyeX_ + propBerthX_, eyeY_, eyeZ_ + propBerthZ_};
                    float t = 1.0f;
                    if (!eyecol::SegmentHit(shownPivot, to, &t)) { eyeX_ = to.x; eyeZ_ = to.z; }
                    else propBerthX_ = propBerthZ_ = 0.0f;
                }
            } else {
                propBerthX_ = propBerthZ_ = 0.0f;
            }
            if (swingEase && meshSolve && q.floorAt) {
                float under = 0.0f;
                if (q.floorAt(q.context, eyeX_, eyeZ_, eyeY_ + 0.6f, &under) && eyeY_ < under + 0.45f) {
                    const gta2::Vec3 up{eyeX_, under + 0.45f, eyeZ_};
                    float t = 1.0f;
                    if (!eyecol::SegmentHitSolid(gta2::Vec3{eyeX_, eyeY_, eyeZ_}, up, &t)) {
                        if (cameraLogOn()) Log("cam: swing first: lens lifted %.2f over the treads", up.y - eyeY_);
                        eyeY_ = up.y;
                    }
                }
            }
            // FIX-CAMERA-4: a railing's bars are thick near the lens (the plaza fence's spear tops
            // a dark band over a quarter of the frame at 0.12, run fc4_fence4): kRailClear off its
            // sheet sideways (0.3 still left the corner post over a quarter of the frame, fc4_fence5), never
            // through anything on the way.
            if (meshSolve && CameraSwingOn()) {
                constexpr float kRailClear = 0.45f;
                gta2::Vec3 e{eyeX_, eyeY_, eyeZ_};
                float t = 1.0f;
                if (eyecol::PushPanels(&e, kRailClear) > 1e-4f && !eyecol::SegmentHit(shownPivot, e, &t) &&
                    !(q.blocked && solidAt(e.x, e.y, e.z))) {
                    eyeX_ = e.x; eyeY_ = e.y; eyeZ_ = e.z;
                }
            }
            // FIX-CAMERA-5 (pm15-third-camera-flush-with-wall-corner-half-frame-blur-player-sliced): the
            // boom stops kMeshClear short of what is on its own line, but a wall beside that line (a
            // corner he walks round, the side of an alley) could come to a hair from the lens: half
            // the frame one blurred wall plane, a hard edge through him. The shown eye keeps
            // kSideClear off every surface, never through anything on the way from his head.
            // GTA2DX9_CAM_SIDE=0 turns it off (A/B).
            static int sideOn = -1;
            if (sideOn < 0) { char b[8] = {}; sideOn = GetEnvironmentVariableA("GTA2DX9_CAM_SIDE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            if (meshSolve && sideOn) {
                constexpr float kSideClear = 0.25f;
                gta2::Vec3 e{eyeX_, eyeY_, eyeZ_};
                float t = 1.0f;
                const float moved = eyecol::Push(&e, kSideClear);
                if (moved > 1e-4f && !eyecol::SegmentHit(shownPivot, e, &t) && !(q.blocked && solidAt(e.x, e.y, e.z))) {
                    eyeX_ = e.x; eyeY_ = e.y; eyeZ_ = e.z;
                    if (cameraLogOn()) {
                        static int every = 0;
                        if ((++every % 15) == 1) Log("cam: side berth moved %.2f", moved);
                    }
                }
            }
            // FIX-CAMERA-11 (pfl28 angled tri18_rev, pm27 ste x=117): at the wheel the shown eye had no berth from
            // the faces beside its line: a car backing along a wall (or jammed against one) put the lens 0.0-0.15
            // from the bricks, the near plane cut the wall open (black frames; a magnified tile filling the frame).
            // The chase eye keeps kCarSide off every drawn wall (sheets and bars are not walls), never through anything
            // on the way from the car. GTA2DX9_CAM_CAR_BERTH=0 turns it off (A/B).
            static int carBerthOn = -1;
            if (carBerthOn < 0) { char b[8] = {}; carBerthOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_BERTH", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
            if (carMesh && sideOn && carBerthOn && mode == ViewMode::ThirdPerson) {
                // FIX-CAMERA-16 (pfl28 1w4 residual): 0.25 left the lens 0.25 from a building's corner beside a car
                // pinned along a wall, a magnified dark slab down the frame's side for ~3 s (tri37_pk, cam16_pk0).
                // GTA2DX9_CAM_CAR_BERTH_R (blocks; default 0.4, 0.25 = before).
                static float kCarSide = -1.0f;
                if (kCarSide < 0.0f) { char b[16] = {}; kCarSide = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_BERTH_R", b, sizeof b) ? static_cast<float>(atof(b)) : 0.4f;
                                       if (!(kCarSide > 0.05f && kCarSide < 1.0f)) kCarSide = 0.4f; }
                const gta2::Vec3 e0{eyeX_, eyeY_, eyeZ_};
                float t = 1.0f;
                // A lens already past a face on its way from the car (the turned eye on the pillar): back along the
                // line to the berth short of it first.
                const gta2::Vec3 span = e0 - shownPivot;
                const float spanLen = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
                auto berthed = [&](float side) {
                    gta2::Vec3 b = e0;
                    float th = 1.0f;
                    if (spanLen > 1e-3f && eyecol::SegmentHitSolid(shownPivot, e0, &th)) {
                        const float k = (std::max)(0.0f, th - side / spanLen);
                        b = {shownPivot.x + span.x * k, shownPivot.y + span.y * k, shownPivot.z + span.z * k};
                    }
                    eyecol::Push(&b, side);
                    return b;
                };
                gta2::Vec3 e = berthed(kCarSide);
                // FIX-CAMERA-16 (cam16_pk3 pin): in a tight pocket the wider berth costs the lens room from the car (the
                // eye held 0.9 from its centre, the car past the frame's bottom edge): the wider berth only where it
                // keeps the lens as far from the car as 0.25 would, or past the pocket's reach (half its length + 0.45).
                if (kCarSide > 0.25f) {
                    const gta2::Vec3 narrow = berthed(0.25f);
                    const float reachNeed = (exitCar_ == player.vehicle && exitCarHalfLength_ > 0.1f ? exitCarHalfLength_ : 0.45f) + 0.45f;
                    const float dWide = std::hypot(e.x - shownPivot.x, e.z - shownPivot.z), dNarrow = std::hypot(narrow.x - shownPivot.x, narrow.z - shownPivot.z);
                    if (dWide < dNarrow - 0.02f && dWide < reachNeed + 0.3f) e = narrow;
                }
                const float moved = std::sqrt((e.x - e0.x) * (e.x - e0.x) + (e.y - e0.y) * (e.y - e0.y) + (e.z - e0.z) * (e.z - e0.z));
                t = 1.0f;
                if (moved > 1e-4f && !eyecol::SegmentHitSolid(shownPivot, e, &t)) {
                    eyeX_ = e.x; eyeY_ = e.y; eyeZ_ = e.z;
                    if (cameraLogOn()) {
                        static int every = 0;
                        if ((++every % 10) == 1) Log("cam: car berth moved %.2f (near %.2f after)", moved, eyecol::Nearest(e, 1.0f));
                    }
                }
            }
            const float full = (std::max)(rigLen, boom_);
            orientEye = {shownPivot.x + dir.x * full, shownPivot.y + dir.y * full, shownPivot.z + dir.z * full};
            pulledShort = (std::max)(0.0f, rigLen - boom_);
            rigLength = rigLen;
        }
        if (cameraLogOn()) {
            static int every = 0;
            if (pulled || (++every % 15) == 0)
                Log("cam: boom %s len=%.2f solved=%.2f want=%.2f rig=%.2f min=%.2f clear=%.2f", inVehicle ? "car" : "foot", boom_, armLen, solveLen, rigLen, minBoom, boomClear_);
        }
    }
    // FIX-CAMERA-2 (feel7-third-chase-camera-inside-car-or-wreck-body): the lens never in or
    // against another car's or a wreck's body. The boom used to pass through traffic and
    // wrecks level with his car, and the hull's inside filled the frame for up to a second
    // (run pl7_feel). A car is low and the chase camera only a little over the roofs, so the
    // shown eye rises over any body within kCarNear of it (seen from above) to kCarClear over
    // its roof, at most kCarUp blocks a second (a car coming alongside is met a few frames
    // early, no jump), and comes down eased once it has passed. Not through the wall solve:
    // made solid there, a car crossing behind his pulled the boom in and craned it up over
    // his own roof at once (run fc2_drive_c1). Not the car he drives, nor one he stands in.
    if (s.tpCollide && CameraCarsOn() && mode == ViewMode::ThirdPerson) {
        constexpr float kCarNear = 0.55f, kCarClear = 0.2f, kCarUp = 6.0f, kCarRiseMax = 1.2f;
        float want = 0.0f;
        for (const CameraCar& c : LiveCameraCars()) {
            if (inVehicle && c.object == reinterpret_cast<uintptr_t>(player.vehicleSprite)) continue;
            if (c.y0 > eyeY_ + 0.5f || c.y1 + kCarClear < eyeY_) continue;
            if (CarFootprintDepth(c, px, pz) > -0.1f) continue;   // he is in it or against it
            if (CarFootprintDepth(c, eyeX_, eyeZ_) <= -kCarNear) continue;
            want = (std::max)(want, c.y1 + kCarClear - eyeY_);
        }
        want = (std::min)(want, kCarRiseMax);
        if (!boomKnown_) carLift_ = want;
        else if (want > carLift_) carLift_ = (std::min)(want, carLift_ + kCarUp * dt);
        else carLift_ += (want - carLift_) * (1.0f - std::exp(-dt / 0.5f));
        if (carLift_ < 1e-3f) carLift_ = 0.0f;
        // Not into a ceiling: the lift stops short of anything solid over the eye.
        if (carLift_ > 0.0f && q.blocked) {
            for (int k = 1; k <= 6; ++k) {
                const float y = eyeY_ + carLift_ * k / 6.0f + 0.1f;
                if (solidAt(eyeX_, y, eyeZ_)) { carLift_ = (std::max)(0.0f, carLift_ * (k - 1) / 6.0f); break; }
            }
        }
        orientEye.y += carLift_;   // the shown eye too, below (eyeY_ stays the solve's state)
    } else {
        carLift_ = 0.0f;
    }
    // FIX-CAMERA-6 (pfeel32-v-first-to-third-parked-camera-stays-steep-60deg-car-cropped-at-bottom-edge): at the
    // wheel with the boom pulled in (the car stopped with a building close behind it), the eye came to rest on the
    // body's rear edge at roof height looking level along the roof: the roof filled the lower 60 % of the frame for
    // the 6 s he sat there and the car was never seen (run cam6_tp_base, parkv: a van against a wall, boom 0.72 of
    // 1.43). Pulled in, the eye rises over the roof by most of what the boom lost (up to 0.8 block, eased, as far as
    // the space over it is open) and the view tips down from the full rig's line toward the eye that is shown, so it
    // looks over the roof at the car's nose and the street; within the 35 degree cap below. GTA2DX9_CAM_CAR_RAISE=0
    // turns it off (A/B).
    {
        static int raiseOn = -1;
        if (raiseOn < 0) { char b[8] = {}; raiseOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_RAISE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        float want = 0.0f;
        if (raiseOn && inVehicle && mode == ViewMode::ThirdPerson && s.tpCollide && rigLength > 0.5f && pulledShort > 0.15f * rigLength) {
            // stopped or creeping only: at speed a pull-in is a corner passing, not a place he sits in
            want = (std::min)(0.8f, 0.8f * pulledShort) * (std::min)(1.0f, (std::max)(0.0f, (2.5f - speed) / 2.0f));
            for (int k = 1; k <= 6; ++k) {
                const float y = eyeY_ + carLift_ + want * k / 6.0f + 0.1f;
                if (q.blocked && solidAt(eyeX_, y, eyeZ_)) { want = (std::max)(0.0f, want * (k - 1) / 6.0f); break; }
            }
        }
        carRaise_ += (want - carRaise_) * (1.0f - std::exp(-dt / (want > carRaise_ ? 0.3f : 0.8f)));
        if (carRaise_ < 1e-3f) carRaise_ = 0.0f;
        if (carRaise_ > 0.0f) {
            const gta2::Vec3 shownNow{eyeX_, eyeY_ + carLift_ + carRaise_, eyeZ_};
            const float w = (std::min)(1.0f, carRaise_ / 0.4f);
            orientEye = orientEye + (shownNow - orientEye) * w;
            if (cameraLogOn()) {
                static int every = 0;
                if ((++every % 15) == 1) Log("cam: car raise %.2f (boom %.2f short of %.2f)", carRaise_, pulledShort, rigLength);
            }
        }
    }
    // FIX-CAMERA-2: how near the shown eye is to another car's body (the hull at the lens),
    // for the log: GTA2DX9_LOG_CAMERA=1 prints each near frame and a count every 900 frames
    // (cars from LiveCameraCars, measured even with GTA2DX9_CAM_CARS=0 for the A/B).
    if (cameraLogOn() && mode == ViewMode::ThirdPerson) {
        static int frames = 0, near10 = 0, inside = 0;
        float best = 9.0f;
        for (const CameraCar& c : LiveCameraCars()) {
            if (inVehicle && c.object == reinterpret_cast<uintptr_t>(player.vehicleSprite)) continue;
            if (CarFootprintDepth(c, px, pz) > -0.1f) continue;
            const float ey = eyeY_ + carLift_;
            const float out = -CarFootprintDepth(c, eyeX_, eyeZ_);
            const float vert = ey > c.y1 ? ey - c.y1 : (ey < c.y0 ? c.y0 - ey : 0.0f);
            const float d = (std::max)(out, vert);
            best = (std::min)(best, d);
        }
        // FIX-CAMERA-14 (pfl65): on foot, frames whose shown eye has another car's body across the line to his chest
        {
            static int footFrames = 0, hiddenFrames = 0;
            if (!inVehicle) {
                ++footFrames;
                if (CarHidesPoint(gta2::Vec3{eyeX_, eyeY_ + carLift_, eyeZ_}, gta2::Vec3{px, baseY + 0.30f, pz})) {
                    ++hiddenFrames;
                    Log("cam: car hides him from the eye (lift %.1f deg)", liftAngle_ / kDegToRad);
                }
                if (footFrames >= 900) {
                    Log("cam: car hide summary: %d of %d on-foot third-person frames with another car across the line to him", hiddenFrames, footFrames);
                    footFrames = hiddenFrames = 0;
                }
            }
        }
        ++frames;
        if (best < 0.1f) ++near10;
        if (best < 0.0f) ++inside;
        if (best < 0.4f) Log("cam: car near d=%.2f %s", best, inVehicle ? "car" : "foot");
        if (frames >= 900) {
            Log("cam: car near summary: %d of %d third-person frames with another car's body within 0.1 of the eye, %d inside it", near10, frames, inside);
            frames = near10 = inside = 0;
        }
    }
    // FIX-CAMERA-3 (feel17-armed-third-camera-inside-hero): never inside the figure. A boom the walls
    // have pulled in to under kBodyClear (flat) from his centre line, below the top of his head plus
    // kOverHead, goes up over his head instead (as far as the space over him is open: cells and mesh),
    // and the framing below looks down at him. Eased on the way up and down, so it is a crane move.
    if (!inVehicle && mode == ViewMode::ThirdPerson && s.tpCollide && meshSolve) {
        constexpr float kBodyClear = 0.4f, kOverHead = 0.3f, kFigureTop = 0.48f;
        const float flatD = std::hypot(eyeX_ - px, eyeZ_ - pz);
        // FIX-CAMERA-4: nearer his axis, higher (up to 0.4 more at the axis): an eye just at
        // head+0.3 over him looked level over his head with him under the frame (fc4_demo2).
        const float top = baseY + kFigureTop + kOverHead + 0.4f * (std::max)(0.0f, 1.0f - flatD / kBodyClear);
        float want = 0.0f;
        if (flatD < kBodyClear && eyeY_ < top) {
            // Fully over him at the axis, nothing needed at kBodyClear.
            const float u = 1.0f - flatD / kBodyClear;
            want = (top - eyeY_) * (std::min)(1.0f, 1.6f * u);
            const gta2::Vec3 from{eyeX_, eyeY_, eyeZ_}, to{eyeX_, eyeY_ + want + 0.1f, eyeZ_};
            float t = 1.0f;
            if (eyecol::SegmentHit(from, to, &t)) want = (std::max)(0.0f, (want + 0.1f) * t - kMeshClear);
            for (int k = 1; k <= 4; ++k)
                if (q.blocked && solidAt(eyeX_, eyeY_ + want * k / 4.0f + 0.07f, eyeZ_)) { want = (std::max)(0.0f, want * (k - 1) / 4.0f); break; }
        }
        bodyLift_ += (want - bodyLift_) * (1.0f - std::exp(-dt / (want > bodyLift_ ? 0.08f : 0.4f)));
        if (bodyLift_ < 1e-3f) bodyLift_ = 0.0f;
        if (cameraLogOn() && bodyLift_ > 0.0f) {
            static int every = 0;
            if ((++every % 10) == 1) Log("cam: over the figure lift=%.2f want=%.2f flat=%.2f", bodyLift_, want, flatD);
        }
    } else {
        bodyLift_ = 0.0f;
    }
    eyeY_ += bodyLift_;
    gta2::Vec3 eye{eyeX_, eyeY_ + carLift_ + carRaise_, eyeZ_};
    eyeY_ -= bodyLift_;   // the solve's state stays the boom's
    if (shake_ > 0.001f) {
        eye.x += Wobble(shakeClock_, 11.0f) * 0.04f * shake_;
        eye.y += Wobble(shakeClock_ + 2.3, 13.0f) * 0.03f * shake_;
    }
    // Pulled in close (a wall behind him, craned up over him): the point looked at
    // comes back from ahead of him toward his chest, so the frame holds him and
    // not the wall beyond (on foot; at 0.4 block or less, 80 % of the way).
    gta2::Vec3 aim = lookAt;
    if (inVehicle && carSwing != 0.0f) {
        // FIX-CAMERA-9 (pfl28): turned aside, the chase looks at the car, not down the road ahead of it (from the
        // side the point ahead put the van's nose off the frame's edge, run cam9_p28c); whole at a 60-degree turn.
        const float m = (std::min)(1.0f, std::fabs(carSwing) / (60.0f * kDegToRad));
        const gta2::Vec3 mid{px, lookAt.y, pz};
        aim = lookAt + (mid - lookAt) * m;
    }
    if (!inVehicle) {
        const float nearDist = std::hypot(orientEye.x - px, orientEye.z - pz);
        const float mix = 0.8f * (std::min)(1.0f, (std::max)(0.0f, (1.1f - nearDist) / 0.7f));
        if (mix > 0.0f) {
            const gta2::Vec3 chest{px, baseY + 0.25f, pz};
            aim = lookAt + (chest - lookAt) * mix;
        }
    }
    const gta2::Vec3 dir = aim - orientEye;   // the rig's orientation (FIX-CAMERA boom filter above)
    const float flat = std::hypot(dir.x, dir.z);
    float camYaw = flat > 1e-5f ? std::atan2(dir.x, dir.z) : yaw;
    float camPitch = std::atan2(dir.y, (std::max)(flat, 1e-5f));
    // FIX-CAMERA-2 (feel8): at the wheel never steeper than 35 degrees down (unless the mouse
    // orbit asks for more), so the horizon stays in the picture when a wall behind the car
    // shortens and lifts the boom; it used to look straight down at the roof.
    const float rawPitch = camPitch;
    if (inVehicle && mode == ViewMode::ThirdPerson && CameraCarPitchCapOn()) {
        const float limit = -(std::max)(35.0f * kDegToRad, orbitPitch + chase::kPitch * kDegToRad);
        if (camPitch < limit) camPitch = limit;
    }
    if (cameraLogOn() && mode == ViewMode::ThirdPerson) {
        static int every = 0;
        if (inVehicle || (++every % 15) == 0) Log("cam: pitch %.1f raw=%.1f %s", camPitch / kDegToRad, rawPitch / kDegToRad, inVehicle ? "car" : "foot");
    }
    // Through a glide the pitch eases too: from the eyes to the death camera the
    // first frames look steeply down at a body right under the eye.
    if (lastPitchKnown_ && (blend_ > 0.0f || (deathMix_ > 0.0f && deathMix_ < 0.99f))) {
        camPitch = lastPitch_ + (camPitch - lastPitch_) * (1.0f - std::exp(-dt / 0.2f));
    }
    lastPitch_ = camPitch;
    lastPitchKnown_ = true;
    // The orientation that is actually set is what the player sees, and the
    // eye's own lag can swing it faster than the orbit's yaw (a car turning
    // under a camera still on its way): the cap applies to it too, so no frame
    // turns the picture more than the rate allows at 30 fps.
    {
        // FIX-INCAR-1 (pfl28): the in-car boom turning aside carries the view round with it; capped at the car rate
        // alone the view's yaw fell 50 degrees behind the turn and the car slid off the frame's edge (run incar1_rev1
        // f615-f629, box -0.28..0.48).
        const float cap = (inVehicle ? s.turnRateCar : s.turnRateFoot) * ViewTurnSpeedScale() * kDegToRad * (std::min)(dt, 1.0f / 30.0f) +
                          (CarSwingEarlyOn() ? carSwingStep : 0.0f);
        if (finalYawKnown_ && cap > 0.0f) {
            const float d = WrapAngle(camYaw - finalYaw_);
            camYaw = WrapAngle(finalYaw_ + (std::max)(-cap, (std::min)(cap, d)));
        }
        finalYaw_ = camYaw;
        finalYawKnown_ = true;
    }
    // FIX-CAMERA-3 (feel16-armed-third-hero-sinks-off-bottom-edge-while-firing,
    // feel17-third-alley-camera-crops-hero-legs-at-hip-or-knee): on foot the whole figure, feet to
    // the top of the head, stays inside the frame's middle 80 % (10 %..90 % of the height and
    // width), measured from the eye that is actually shown. The orientation above is the rig's,
    // taken from the full-length boom (orientEye), so a pull-in that brought the eye to 0.6 block
    // behind him kept looking out over him: pitch -11 with his feet 47 degrees down (run fc3_base17,
    // the alley at wil 159.5,139.5), and the armed rig's look-ahead turned with him while firing put
    // him under the bottom edge for 3 s. The clamp moves the pitch and the yaw only as far as the
    // figure needs, so an ordinary frame is untouched; a figure too big for the frame (the eye very
    // close) is centred. Not while the mouse has the camera (looking up at a roof is the player's
    // choice), nor over the body (death camera). GTA2DX9_CAM_FRAME=0 turns it off (A/B).
    if (!inVehicle && mode == ViewMode::ThirdPerson && deathMix_ < 0.01f && CameraFrameClampOn()) {
        const gta2::Vec3 shownEye = eye;
        const float fovNow = ((std::min)((std::min)((std::max)(s.tpFov, 20.0f), 110.0f) + chaseFovExtra, 130.0f) - 8.0f * aimMix) * kDegToRad;
        const float tv = std::tan(0.5f * fovNow), th = tv * (16.0f / 9.0f);
        const float mv = std::atan(0.76f * tv), mh = std::atan(0.76f * th);   // inside the 80 % box with room for the shake/recoil
        constexpr float kFigureTop = 0.48f, kFigureRadius = 0.12f;
        const float dx = px - shownEye.x, dz = pz - shownEye.z;
        const float flatD = std::hypot(dx, dz);
        // FIX-CAMERA-17: under the turn budget, from within 0.3 block of his axis (seen from above: the lens over him)
        // the bearing to him is noise and the yaw is left as it is, fully applied again from 0.5; and the pitch part
        // runs down to the axis (it used to switch off under 0.05 and the view sawed between -62 and -11 degrees).
        const bool budgetClamp = CameraTurnBudgetDeg() > 0.0f;
        if (flatD > (budgetClamp ? 0.005f : 0.05f)) {
            // Sideways: the figure's centre line and its width inside the side margins.
            const float bearing = std::atan2(dx, dz);
            const float halfW = std::atan2(kFigureRadius, flatD);
            const float side = (std::max)(0.0f, mh - halfW);
            const float off = WrapAngle(bearing - camYaw);
            float yawFix = 0.0f;
            if (off > side) yawFix = off - side;
            else if (off < -side) yawFix = off + side;
            if (budgetClamp) yawFix *= (std::min)(1.0f, (std::max)(0.0f, (flatD - 0.3f) / 0.2f));
            if (yawFix != 0.0f) {
                camYaw = WrapAngle(camYaw + yawFix);
                finalYaw_ = camYaw;
            }
            // Up and down: elevation of the feet and the head along the view's forward direction.
            const float fwdRaw = dx * std::sin(camYaw) + dz * std::cos(camYaw);
            const float fwd = budgetClamp && fwdRaw > -0.3f ? (std::max)(fwdRaw, 0.08f) : fwdRaw;
            const bool mouseHasIt = look.lastMoved > 0.0 && Now() - look.lastMoved < s.tpReturnDelay;
            if (fwd > 0.05f && !mouseHasIt) {
                const float aFeet = std::atan2(baseY - shownEye.y, fwd);
                const float aHead = std::atan2(baseY + kFigureTop - shownEye.y, fwd);
                const float lo = aHead - mv, hi = aFeet + mv;   // pitch range that holds both
                const float before = camPitch;
                if (lo > hi) camPitch = 0.5f * (aFeet + aHead);
                else camPitch = (std::max)(lo, (std::min)(hi, camPitch));
                lastPitch_ = camPitch;
                if (cameraLogOn() && (std::fabs(camPitch - before) > 0.5f * kDegToRad || yawFix != 0.0f)) {
                    static int every = 0;
                    if ((++every % 5) == 1)
                        Log("cam: frame clamp pitch %.1f -> %.1f yaw %+.1f (feet %.1f head %.1f margin %.1f, flat %.2f)", before / kDegToRad,
                            camPitch / kDegToRad, yawFix / kDegToRad, aFeet / kDegToRad, aHead / kDegToRad, mv / kDegToRad, flatD);
                }
            }
        }
    }
    // FIX-CAMERA-13 (pfl28 residual): at the wheel the car's body box (8 corners) stays inside the middle 90 % of the
    // frame's width (and under its top edge), measured from the eye that is shown. The orientation is the full rig's (orientEye); with the boom pulled in
    // at a corner pocket or along a wall the shown eye is a block off that line and the car sat cut at the frame's
    // edge for 0.5-1 s (FIX-CAMERA-11: box past an edge in ~50 frames a reverse, runs cam11_rev4/6/7). Like the on-foot
    // frame clamp: the yaw (and the pitch, up) move only as far as the box needs (an ordinary chase frame is untouched), a
    // box too wide for the frame is centred; the pitch stays inside the 35 degree cap. Not while the mouse has the
    // camera, nor with the eye over the car's own footprint. GTA2DX9_CAM_CAR_FRAME=0 turns it off (A/B).
    {
        static int carFrameOn = -1;
        if (carFrameOn < 0) { char b[8] = {}; carFrameOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_FRAME", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const bool mouseHasIt = look.lastMoved > 0.0 && Now() - look.lastMoved < s.tpReturnDelay;
        if (carFrameOn && inVehicle && mode == ViewMode::ThirdPerson && deathMix_ < 0.01f && !mouseHasIt && exitCar_ == player.vehicle &&
            exitCarHalfWidth_ > 0.05f) {
            const float halfW = exitCarHalfWidth_, halfL = exitCarHalfLength_, tall = exitCarHeight_;
            const float fovNow = (std::min)((std::min)((std::max)(s.tpFov, 20.0f), 110.0f) + chaseFovExtra, 130.0f) * kDegToRad;
            const float tv = std::tan(0.5f * fovNow), th = tv * (16.0f / 9.0f);
            const float mv = std::atan(0.9f * tv), mh = std::atan(0.9f * th);
            float offMin = 1e9f, offMax = -1e9f;
            bool usable = true;
            gta2::Vec3 cs[8];
            // the drawn body's footprint when the car list has it (a frame old), else the body box round him
            const CameraCar* drawnCar = nullptr;
            for (const CameraCar& c : LiveCameraCars())
                if (c.object == reinterpret_cast<uintptr_t>(player.vehicleSprite)) { drawnCar = &c; break; }
            for (int i = 0; i < 8; ++i) {
                if (drawnCar) {
                    cs[i] = gta2::Vec3{drawnCar->x[i & 3], (i & 4) ? drawnCar->y1 : drawnCar->y0, drawnCar->z[i & 3]};
                } else {
                    const float l = (i & 1) ? halfL : -halfL, w = (i & 2) ? halfW : -halfW, h = (i & 4) ? tall : 0.0f;
                    cs[i] = gta2::Vec3{px + hx * l + std::cos(headingYaw) * w, baseY + h, pz + hz * l - std::sin(headingYaw) * w};
                }
                const float dx = cs[i].x - eye.x, dz = cs[i].z - eye.z;
                // (a corner 0.2 from a pulled-in eye still has a bearing; the extent test below drops the eye over the car)
                if (std::hypot(dx, dz) < 0.08f) { usable = false; break; }
                const float off = WrapAngle(std::atan2(dx, dz) - camYaw);
                offMin = (std::min)(offMin, off);
                offMax = (std::max)(offMax, off);
            }
            if (usable && offMax - offMin < 150.0f * kDegToRad) {
                float yawFix = 0.0f;
                if (offMax - offMin > 2.0f * mh) yawFix = 0.5f * (offMin + offMax);
                else if (offMax > mh) yawFix = offMax - mh;
                else if (offMin < -mh) yawFix = offMin + mh;
                const float yawBefore = camYaw, pitchBefore = camPitch;
                if (yawFix != 0.0f) {
                    camYaw = WrapAngle(camYaw + yawFix);
                    finalYaw_ = camYaw;
                }
                // up and down: each corner's elevation along the (fixed) view direction
                float eMin = 1e9f, eMax = -1e9f;
                bool ahead = true;
                for (const gta2::Vec3& c : cs) {
                    const float fwd = (c.x - eye.x) * std::sin(camYaw) + (c.z - eye.z) * std::cos(camYaw);
                    // (a body within 0.6 of the lens is the boom's to fix: tipped up to its roof the view looked into the
                    // sky over a car at the lens, run cam13_rev4 f166-178)
                    if (fwd < 0.6f) { ahead = false; break; }
                    const float e = std::atan2(c.y - eye.y, fwd);
                    eMin = (std::min)(eMin, e);
                    eMax = (std::max)(eMax, e);
                }
                if (ahead) {
                    // only the top edge: the chase framing has the near bumper under the bottom edge by design
                    // (the logged box's bottom is 1.04-1.39 at rest), and a car below the frame is the boom's
                    // business (the raise over a pulled-in boom)
                    camPitch = (std::max)(camPitch, (std::min)(eMax - mv, camPitch + 8.0f * kDegToRad));
                    (void)eMin;
                    if (CameraCarPitchCapOn()) {
                        const float limit = -(std::max)(35.0f * kDegToRad, orbitPitch + chase::kPitch * kDegToRad);
                        if (camPitch < limit) camPitch = limit;
                    }
                    lastPitch_ = camPitch;
                }
                if (cameraLogOn() && (yawFix != 0.0f || std::fabs(camPitch - pitchBefore) > 0.2f * kDegToRad)) {
                    static int every = 0;
                    if ((++every % 3) == 1)
                        Log("cam: car frame clamp yaw %+.1f pitch %.1f -> %.1f (box %.1f..%.1f deg, margin %.1f)", WrapAngle(camYaw - yawBefore) / kDegToRad,
                            pitchBefore / kDegToRad, camPitch / kDegToRad, offMin / kDegToRad, offMax / kDegToRad, mh / kDegToRad);
                }
            }
        }
    }
    // FIX-CAMERA-15 (pfl28-residual-driveoff-cut-lands-on-pulled-in-boom-car-drops-past-bottom-edge-0p3s): a car
    // stopped in a pocket (pinned at a building's corner, turning in place against it) leaves the chase eye no place
    // behind it: the walls and the berth put the shown eye over the car's own body, 0.2-0.5 from its centre, raised a
    // block and capped at 35 degrees down, so the car sat under the frame's bottom edge (box bottom 2-11 frame heights,
    // runs cam14_rev12 f1059-1078, tri32_rev). When the shown eye is nearer the car's centre than its half length and
    // a margin and the car is slow, the camera cranes up over the car (to about 0.9 + half its length over the roof,
    // as far as the space over it is open) and looks down at it, past the 35 degree cap (to 80): the car whole in
    // the middle of the frame. Eased in over ~0.12 s and out over ~0.5 s, so it is a crane move, not a cut.
    // GTA2DX9_CAM_CAR_POCKET=0 turns it off (A/B).
    {
        static int pocketOn = -1;
        if (pocketOn < 0) { char b[8] = {}; pocketOn = GetEnvironmentVariableA("GTA2DX9_CAM_CAR_POCKET", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const bool mouseHasIt = look.lastMoved > 0.0 && Now() - look.lastMoved < s.tpReturnDelay;
        float want = 0.0f;
        const float halfL = exitCarHalfLength_ > 0.1f ? exitCarHalfLength_ : 0.6f;
        const float tall = (std::max)(exitCarHeight_, 0.3f);
        const float flatD = std::hypot(eye.x - px, eye.z - pz);
        if (pocketOn && inVehicle && mode == ViewMode::ThirdPerson && s.tpCollide && exitCar_ == player.vehicle && deathMix_ < 0.01f &&
            !mouseHasIt) {
            const float need = halfL + 0.45f;
            const float slow = (std::min)(1.0f, (std::max)(0.0f, 2.0f - speed));
            want = (std::min)(1.0f, (std::max)(0.0f, (need - flatD) / 0.35f)) * slow;
        }
        if (!(dt > 0.0f && dt < 0.25f)) pocket_ = want;
        else pocket_ += (want - pocket_) * (1.0f - std::exp(-dt / (want > pocket_ ? 0.12f : 0.5f)));
        if (pocket_ < 1e-3f) pocket_ = 0.0f;
        if (pocket_ > 0.0f) {
            const float topY = baseY + tall + 0.9f + 0.5f * halfL;
            float lift = (std::max)(0.0f, topY - eye.y);
            // not into a ceiling or a deck over the car: cells, then the drawn mesh
            for (int k = 1; k <= 6 && lift > 0.0f; ++k) {
                const float y = eye.y + lift * k / 6.0f + 0.1f;
                if (q.blocked && solidAt(eye.x, y, eye.z)) { lift = (std::max)(0.0f, lift * (k - 1) / 6.0f); break; }
            }
            float t = 1.0f;
            if (lift > 0.0f && eyecol::SegmentHitSolid(eye, gta2::Vec3{eye.x, eye.y + lift + 0.15f, eye.z}, &t))
                lift = (std::max)(0.0f, (lift + 0.15f) * t - 0.15f);
            eye.y += lift * pocket_;
            const float fx = px - eye.x, fz = pz - eye.z, fl = std::hypot(fx, fz);
            const float pitchCar = (std::max)(-80.0f * kDegToRad, std::atan2(baseY + 0.4f * tall - eye.y, (std::max)(fl, 0.05f)));
            const float yawCar = fl > 0.25f ? std::atan2(fx, fz) : camYaw;
            camPitch += (pitchCar - camPitch) * pocket_;
            camYaw = WrapAngle(camYaw + WrapAngle(yawCar - camYaw) * pocket_);
            finalYaw_ = camYaw;
            lastPitch_ = camPitch;
            if (cameraLogOn()) {
                static int every = 0;
                if ((++every % 5) == 1)
                    Log("cam: car pocket %.2f lift %.2f flat %.2f (need %.2f) pitch %.1f", pocket_, lift, flatD, halfL + 0.45f, camPitch / kDegToRad);
            }
        }
    }
    // FIX-CAMERA-6 (pfeel3): the orientation that is shown never turns more than a capped rate in a frame,
    // the frame clamp's correction included (it set the yaw and the pitch outright: +122 and -26 degrees in one
    // frame when the boom was pulled into him at the fence; 30 degrees of pitch a frame while the eye sat over
    // his axis). 280 degrees a second of pitch (9 a frame at 30 fps) and 300 of yaw: a crane move of a few frames, never a cut. Not
    // the first frame of a view (the move from the last view's pose is ApplyTransition's), nor the death
    // camera's glide. GTA2DX9_CAM_RATE=0 turns it off (A/B).
    {
        static int rateOn = -1;
        if (rateOn < 0) { char b[8] = {}; rateOn = GetEnvironmentVariableA("GTA2DX9_CAM_RATE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const float step = (std::min)(dt, 1.0f / 20.0f);
        const bool mouseTurning = look.lastMoved > 0.0 && Now() - look.lastMoved < 0.3;   // a flick is the player's
        if (rateOn && shownPoseKnown_ && deathMix_ < 0.01f && !mouseTurning) {
            // FIX-CAMERA-8 (pfl14): GTA2DX9_CAM_FOOT_PITCH_RATE=<deg/s> sets the on-foot pitch cap (default 280, FIX-
            // CAMERA-6's; 19 degrees every two frames when a wall cuts the boom, runs cam8_p14a/f/q). At 140 the
            // crane meets pfl14's 10-degree acceptance but his feet stay off the bottom edge longer (cam8_p14G/H).
            static float footPitchRate = -1.0f;
            if (footPitchRate < 0.0f) {
                char b[16] = {};
                footPitchRate = GetEnvironmentVariableA("GTA2DX9_CAM_FOOT_PITCH_RATE", b, sizeof b) && atof(b) > 1.0 ? static_cast<float>(atof(b)) : 280.0f;
            }
            // FIX-CAMERA-17: on foot under the turn budget, yaw and pitch each at most the budget's rate (8 a frame at
            // 30 fps by default, against 10 of yaw and 9.3 of pitch before).
            const float budgetRate = inVehicle ? 0.0f : CameraTurnBudgetDeg() * 30.0f;   // on foot (the in-car chase keeps its rates)
            const float maxP = (budgetRate > 0.0f ? (std::min)(budgetRate, inVehicle ? 280.0f : footPitchRate) : (inVehicle ? 280.0f : footPitchRate)) * kDegToRad * step,
                        maxY = (budgetRate > 0.0f ? (std::min)(budgetRate, 300.0f) : 300.0f) * kDegToRad * step;
            const float dp = camPitch - shownPitch_, dy = WrapAngle(camYaw - shownYaw_);
            if (std::fabs(dp) > maxP || std::fabs(dy) > maxY) {
                if (cameraLogOn()) {
                    static int every = 0;
                    if ((++every % 5) == 1) Log("cam: turn capped: pitch %+.1f yaw %+.1f deg this frame", dp / kDegToRad, dy / kDegToRad);
                }
                camPitch = shownPitch_ + (std::max)(-maxP, (std::min)(maxP, dp));
                camYaw = WrapAngle(shownYaw_ + (std::max)(-maxY, (std::min)(maxY, dy)));
                finalYaw_ = camYaw;
                lastPitch_ = camPitch;
            }
        }
        shownPitch_ = camPitch;
        shownYaw_ = camYaw;
        shownPoseKnown_ = true;
    }
    // Lean into the turn: a few degrees of roll with the rate of turn, at speed.
    float roll = (std::max)((std::min)(-yawRate_ * speedFrac_ * 0.35f, 1.0f), -1.0f) * 3.5f * kDegToRad * s.tpLean;
    if (shake_ > 0.001f) {
        camYaw += Wobble(shakeClock_ + 1.1, 8.0f) * 1.5f * kDegToRad * shake_;
        camPitch += Wobble(shakeClock_ + 4.2, 10.0f) * 1.2f * kDegToRad * shake_;
        roll += Wobble(shakeClock_ + 6.5, 6.0f) * 1.5f * kDegToRad * shake_;
    }
    roll_ += (roll - roll_) * (1.0f - std::exp(-dt / 0.15f));
    const float fov = (std::min)((std::max)(s.tpFov, 20.0f), 110.0f) + chaseFovExtra;

    camera->SetPosition(eye);
    camera->SetOrientation(camYaw, camPitch);
    camera->SetRoll(roll_);
    camera->SetFovY((std::min)(fov, 130.0f) * kDegToRad);
    if (aimMix > 0.0f) {
        // QB-6: the aim framing is 8 degrees narrower, and each shot kicks the view up
        // 0.3 degrees, back over a tenth of a second (recoil).
        camera->SetFovY(camera->FovY() - 8.0f * aimMix * kDegToRad);
        const float since = g_aim.lastShot > 0.0 ? static_cast<float>(Now() - g_aim.lastShot) : 1.0f;
        if (since >= 0.0f && since < 0.4f) camera->SetOrientation(camYaw, camPitch + 0.3f * kDegToRad * std::exp(-since / 0.1f));
    }
    LogCameraFrame("third", camYaw, headingYaw, dt, &eye, px, pz, distance);
    if (inVehicle && deathMix_ < 0.01f) {
        // QUALITY-BAR row 22: the car's share of the frame's width (16:9) and whether the
        // whole body (its box) is in the picture, from the camera actually set.
        const bool body = exitCar_ == player.vehicle && exitCarHalfWidth_ > 0.05f;
        const float halfW = body ? exitCarHalfWidth_ : 0.32f, halfL = body ? exitCarHalfLength_ : 0.6f;
        const float tall = body ? exitCarHeight_ : 0.45f;
        const float sy = std::sin(camYaw), cy = std::cos(camYaw), sp = std::sin(camPitch), cpv = std::cos(camPitch);
        const float th = std::tan(0.5f * (std::min)(fov, 130.0f) * kDegToRad), tw = th * (16.0f / 9.0f);
        float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f;
        bool front = true;
        for (int i = 0; i < 8; ++i) {
            const float l = (i & 1) ? halfL : -halfL, w = (i & 2) ? halfW : -halfW, h = (i & 4) ? tall : 0.0f;
            const gta2::Vec3 c{px + hx * l + std::cos(headingYaw) * w, baseY + h, pz + hz * l - std::sin(headingYaw) * w};
            const gta2::Vec3 d = c - eye;
            const float zf = d.x * sy * cpv + d.y * sp + d.z * cy * cpv;
            if (zf < 0.05f) { front = false; continue; }
            const float xr = (d.x * cy - d.z * sy) / zf / tw;
            const float yu = (-d.x * sy * sp + d.y * cpv - d.z * cy * sp) / zf / th;
            minX = (std::min)(minX, xr); maxX = (std::max)(maxX, xr);
            minY = (std::min)(minY, yu); maxY = (std::max)(maxY, yu);
        }
        const float share = front ? ((std::min)(maxX, 1.0f) - (std::max)(minX, -1.0f)) * 0.5f : 1.0f;
        const bool whole = front && minX >= -1.0f && maxX <= 1.0f && minY >= -1.0f && maxY <= 1.0f;
        ++chase::g_frames;
        chase::g_whole += whole ? 1 : 0;
        chase::g_widthSum += share;
        chase::g_fovSum += fov;
        LogCameraFrame("chase", camYaw, headingYaw, dt, &eye, px, pz, share);
        if (chase::g_frames % 150 == 0) {
            Log("view: framing chase frames=%d width=%.2f (now %.2f) whole=%d fov=%.1f (now %.1f) speed=%.2f back=%.2f up=%.2f lead=%.2f bottom=%.2f",
                chase::g_frames, chase::g_widthSum / 150.0, share, chase::g_whole, chase::g_fovSum / 150.0, fov, speed, distance, height,
                chase::g_lead, minY);
            chase::g_widthSum = chase::g_fovSum = 0.0;
            chase::g_whole = 0;
        }
    }
    if (!inVehicle && deathMix_ < 0.01f) {
        // QUALITY-BAR row 2: is his head in the picture (16:9) and not behind a wall?
        const gta2::Vec3 head{px, baseY + 0.42f, pz};
        const float sy = std::sin(camYaw), cy = std::cos(camYaw), sp = std::sin(camPitch), cpv = std::cos(camPitch);
        const gta2::Vec3 d = head - eye;
        const float zf = d.x * sy * cpv + d.y * sp + d.z * cy * cpv;
        const float xr = d.x * cy - d.z * sy;
        const float yu = -d.x * sy * sp + d.y * cpv - d.z * cy * sp;
        const float th = std::tan(0.5f * (std::min)(fov, 130.0f) * kDegToRad);
        const bool in = zf > 0.06f && std::fabs(yu / zf) < th && std::fabs(xr / zf) < th * (16.0f / 9.0f);
        bool seen = in;
        if (seen && q.blocked) {
            for (int i = 1; i < 16 && seen; ++i) {
                const gta2::Vec3 p = eye + d * (static_cast<float>(i) / 16.0f);
                if (solidAt(p.x, p.y, p.z)) seen = false;
            }
        }
        // FIX-CAMERA-3: the whole figure, feet and the top of the head, inside the middle 80 % of the
        // frame (the acceptance box of feel16/feel17), from the camera actually set.
        const float thSet = std::tan(0.5f * camera->FovY());   // the aim framing's narrower field included
        auto inBox = [&](const gta2::Vec3& w) {
            const gta2::Vec3 v = w - eye;
            const float z = v.x * sy * cpv + v.y * sp + v.z * cy * cpv;
            const float x = v.x * cy - v.z * sy, y = -v.x * sy * sp + v.y * cpv - v.z * cy * sp;
            return z > 0.06f && std::fabs(y / z) <= 0.8f * thSet && std::fabs(x / z) <= 0.8f * thSet * (16.0f / 9.0f);
        };
        const bool whole = inBox({px, baseY, pz}) && inBox({px, baseY + 0.48f, pz});
        framingWhole_ += whole ? 1 : 0;
        if (!whole && cameraLogOn()) Log("cam: figure cut eye=%.2f,%.2f,%.2f at=%.2f,%.2f,%.2f", eye.x, eye.y, eye.z, px, baseY, pz);
        ++framingFrames_;
        framingHeadIn_ += in ? 1 : 0;
        framingHeadSeen_ += seen ? 1 : 0;
        if (!seen && (framingFrames_ - framingHeadSeen_) % 5 == 1) Log("view: framing miss eye=%.2f,%.2f,%.2f head=%.2f,%.2f,%.2f in=%d", eye.x, eye.y, eye.z, head.x, head.y, head.z, in ? 1 : 0);
        if (framingFrames_ % 300 == 0)
            Log("view: framing third on foot frames=%d head_in=%d head_seen=%d whole=%d", framingFrames_, framingHeadIn_, framingHeadSeen_, framingWhole_);
    }
    shownX_ = eye.x;
    shownY_ = eye.y;
    shownZ_ = eye.z;
    yawDegrees = camYaw / kDegToRad;
    pitchDegrees = camPitch / kDegToRad;
    g_navCamYaw = camYaw;
    g_navHeading = headingYaw;
    g_navInVehicle = inVehicle;
    g_navHeadingKnown = player.facingKnown;
    status_ = inVehicle ? "third person, following the car"
                        : deathCam ? "third person, over the player on the ground"
                        : (g_navActive ? "third person, orbit (the keys walk as the camera sees)" : "third person, following on foot");
    (void)player;
}

// ---------------------------------------------------------------------------
// RTX Remix options that go with the views
// ---------------------------------------------------------------------------

void ViewModePushRemixOptions(bool viewActive) {
    static int lastPushed = -1;   // -1 nothing yet, else 0 off / 1 on
    static bool lastAvailable = false;
    const bool available = RemixApiAvailable();
    if (!available) {
        lastAvailable = false;
        return;
    }
    if (!lastAvailable) {
        lastAvailable = true;
        lastPushed = -1;   // a fresh runtime has its own default; say it again
    }
    int want = -1;
    switch (g_settings.motionBlur) {
        case 1: want = viewActive ? 1 : 0; break;
        case 2: want = 1; break;
        default: want = -1; break;
    }
    if (want < 0 || want == lastPushed) return;
    if (RemixSetConfig("rtx.enableMotionBlur", want ? "True" : "False")) {
        lastPushed = want;
        Log("view: Remix motion blur %s", want ? "on" : "off");
    }
}

bool FirstPersonSeatEyeRaw(gta2::Vec3* eye) {
    if (!g_fpSeat.valid || Now() - g_fpSeat.rawAt > 0.2) return false;
    *eye = g_fpSeat.raw;
    return true;
}
void SetFirstPersonSeatCorrection(const gta2::Vec3& delta) { g_fpSeat.delta = delta; g_fpSeat.deltaAt = Now(); }
bool FirstPersonBoardEyeOn() { return FpSeatGlideOn(); }

// FIX-CAMERA-16: see view_modes.h.
void SetChaseTrees(std::vector<ChaseTree>&& trees) { g_chaseTrees = std::move(trees); }

float ChaseTreeAlpha(const gta2::Vec3& eye, float x, float y, float z, float height, float crownR, float trunkR) {
    if (!ChaseTreesOn() || CurrentViewMode() != ViewMode::ThirdPerson || g_chaseHero.at < 0.0 || Now() - g_chaseHero.at > 0.25) return 1.0f;
    const float top = y + height;
    // The crown: from about 45 % of the height (tree_01..03: leaves from 0.45-0.53, the branch rods from 0.3 up to
    // 0.66) to the top, out to its radius; the lens in it or under it among the rods, or a crown or trunk across the
    // line to the hero, fades the tree.
    const float crown0 = y + 0.45f * height, rods0 = y + 0.3f * height;
    const float ex = eye.x - x, ez = eye.z - z, e2 = ex * ex + ez * ez;
    const char* why = nullptr;
    if (eye.y > crown0 - 0.25f && eye.y < top + 0.3f && e2 < (crownR + 0.3f) * (crownR + 0.3f)) why = "lens in the crown";
    else if (eye.y >= rods0 - 0.2f && eye.y <= crown0 && e2 < (0.8f * crownR + 0.2f) * (0.8f * crownR + 0.2f)) why = "lens among the branches";
    else if (eye.y >= y - 0.2f && eye.y <= crown0 && e2 < (trunkR + 0.45f) * (trunkR + 0.45f)) why = "trunk at the lens";
    else {
        // Three points on him (feet, chest, head): a line from the lens to each, sampled.
        int blocked = 0;
        const float hy[3] = {0.08f, 0.55f, 0.95f};
        for (float f : hy) {
            const gta2::Vec3 to{g_chaseHero.x, g_chaseHero.y + f * g_chaseHero.height, g_chaseHero.z};
            for (int i = 1; i < 24; ++i) {
                const float t = static_cast<float>(i) / 24.0f;
                const gta2::Vec3 p = eye + (to - eye) * t;
                const float dx = p.x - x, dz = p.z - z, d2 = dx * dx + dz * dz;
                const bool trunk = p.y >= y && p.y <= crown0 && d2 < (trunkR + 0.04f) * (trunkR + 0.04f);
                const bool crown = p.y > crown0 + 0.1f && p.y < top - 0.1f && d2 < 0.6f * crownR * 0.6f * crownR;
                if (trunk || crown) { ++blocked; break; }
            }
        }
        if (blocked) why = "across the line to him";
    }
    // Held 0.4 s after the last reason (no flicker as the lens or he moves along the crown's edge).
    static std::map<int64_t, double> s_held;
    const int64_t key = (static_cast<int64_t>(std::lround(x * 8.0f)) << 32) ^ static_cast<int64_t>(static_cast<uint32_t>(std::lround(z * 8.0f)));
    const double now = Now();
    if (!why) {
        const auto it = s_held.find(key);
        if (it == s_held.end() || now - it->second > 0.4) return 1.0f;
        return 0.0f;
    }
    s_held[key] = now;
    if (s_held.size() > 256)
        for (auto it = s_held.begin(); it != s_held.end();) it = now - it->second > 2.0 ? s_held.erase(it) : std::next(it);
    if (cameraLogOn()) {
        static double last = -1.0;
        if (Now() - last > 0.5) {
            last = Now();
            Log("cam: tree faded (%s) at %.2f,%.2f h %.2f crown %.2f trunk %.2f, eye %.2f,%.2f,%.2f", why, x,
                static_cast<float>(gta2::kMapHeight) - z, height, crownR, trunkR, eye.x, eye.y, static_cast<float>(gta2::kMapHeight) - eye.z);
        }
    }
    return 0.0f;
}

}  // namespace gta2dx9
