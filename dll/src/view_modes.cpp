#include "view_modes.h"

#define DIRECTINPUT_VERSION 0x0800
#include <dinput.h>

#include <algorithm>
#include <vector>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "../../src/gta2_map.h"
#include "car_bodies.h"
#include "game_access.h"
#include "log.h"
#include "remix_api.h"

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

float WrapAngle(float a) {
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

// A read that cannot fault, for pointers that came out of a scan rather than
// off a known structure.
template <typename T>
bool ReadAt(uintptr_t address, T* out) {
    if (address < 0x10000 || address >= 0x7FFE0000) return false;
    SIZE_T got = 0;
    return ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(address), out,
                             sizeof(T), &got) &&
           got == sizeof(T);
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
    if (address < 0x10000 || address >= 0x7FFE0000) return false;
    SIZE_T put = 0;
    return WriteProcessMemory(GetCurrentProcess(), reinterpret_cast<LPVOID>(address), &value, sizeof(T), &put) &&
           put == sizeof(T);
}

ViewQueries g_devQueries;
void ViewModeSetQueries(const ViewQueries& queries) { g_devQueries = queries; }

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
bool NearestParkedTrafficCarOnRoad(float x, float y, float within, float* vx, float* vy, float* distance,
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
        if (g_navActive) {
            for (int i = 0; i < 4; ++i) keys[kNavDik[i]] = g_inj[i] ? 0x80 : 0;
        }
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
    if (FAILED(hr) && hr != DI_BUFFEROVERFLOW) return hr;
    BYTE* base = reinterpret_cast<BYTE*>(dod);
    DWORD n = *inOut, w = 0;
    for (DWORD r = 0; r < n; ++r) {
        DIDEVICEOBJECTDATA_DX3* e = reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + r * cbObj);
        const int i = NavIndexOfDik(e->dwOfs);
        if (e->dwSequence > g_navSeq) g_navSeq = e->dwSequence;   // catch up with the real stream
        g_navLastStamp = e->dwTimeStamp;
        if (i >= 0) {
            g_phys[i] = (e->dwData & 0x80) != 0;
            ++g_diReads;
            if (g_navActive) continue;        // the arrow is ours: the game does not see it
        }
        if (w != r) memmove(base + w * cbObj, e, cbObj);
        if (!(flags & DIGDD_PEEK)) reinterpret_cast<DIDEVICEOBJECTDATA_DX3*>(base + w * cbObj)->dwSequence = ++g_navSeq;
        ++w;
    }
    if (g_navActive && !(flags & DIGDD_PEEK)) {
        for (int i = 0; i < 4 && w < capacity; ++i) {
            if (g_injSeen[i] == g_inj[i]) continue;
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
        const float fx = std::sin(g_navCamYaw), fz = std::cos(g_navCamYaw);
        const float rx = std::cos(g_navCamYaw), rz = -std::sin(g_navCamYaw);
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
            Log("nav: %s keys U%d D%d L%d R%d -> heading %.0f rate %.0f wanted %.0f err %.0f pred %.0f : game U%d D%d L%d R%d (reads %ld, state %ld data %ld)",
                mode == ViewMode::ThirdPerson ? "third" : "first", up, down, left, right,
                g_navHeading / kDegToRad, g_navRate / kDegToRad, desired / kDegToRad, e / kDegToRad, ePred / kDegToRad,
                g_inj[0], g_inj[1], g_inj[2], g_inj[3], g_diReads, g_diStateCalls, g_diDataCalls);
    }
}
}  // namespace

ViewModeSettings& ViewModes() { return g_settings; }
ViewLook& LookOffsets() { return g_look; }

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
        ped = g_lastPlayerPed;
        atTheWheel = true;
        out->source = "driver of a car";
    }
    if (!ped && --g_scanCooldown <= 0) {
        g_scanCooldown = kScanEveryFrames;
        ped = ScanForPlayer();
        if (ped) {
            out->source = g_slot == Slot::Camera ? "camera" : "player object";
            if (!g_slotLogged) {
                g_slotLogged = true;
                Log("view: player pedestrian found through the %s at +0x%02X",
                    g_slot == Slot::Camera ? "camera struct" : "player object",
                    static_cast<unsigned>(g_slotOffset));
            }
        }
    }

    if (!ped) {
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
    if (!ped) return false;
    if (!atTheWheel && PedSignature(ped)) g_lastPlayerPed = ped;

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
        const bool nowActive = active && g_diHooked;
        if (g_navActive && !nowActive) ReleaseInjected();
        g_navActive = nowActive;
        if (g_navActive) SteerPlayer(mode, dt);
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
static void LogCameraFrame(const char* view, float camYaw, float headingYaw, float dt) {
    static int enabled = -1;
    if (enabled < 0) {
        char buf[8] = {};
        enabled = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", buf, sizeof buf) && atoi(buf) ? 1 : 0;
    }
    if (!enabled) return;
    static float lastCam = 0.0f;
    const float rate = WrapAngle(camYaw - lastCam) / (std::max)(dt, 1e-3f) / kDegToRad;
    lastCam = camYaw;
    Log("cam: %s yaw=%.1f heading=%.1f rate=%.0f dt=%.3f", view, camYaw / kDegToRad, headingYaw / kDegToRad, rate, dt);
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
    finalYawKnown_ = false;
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

bool ViewCameraSolver::Update(const PlayerState& player, const ViewQueries& queries, float dt,
                              gta2::Camera* camera) {
    const ViewMode mode = CurrentViewMode();
    if (mode != lastMode_) {
        Reset();
        lastMode_ = mode;
    }
    if (mode == ViewMode::Classic) {
        status_ = "classic";
        camera->SetRoll(0.0f);
        g_navHeadingKnown = false;
        return false;
    }
    if (!player.valid) {
        status_ = "waiting for the player to be found";
        settled_ = false;
        camera->SetRoll(0.0f);
        g_navHeadingKnown = false;
        return false;
    }

    // Into the renderer's frame: x east, y up, z north. Map rows run north to
    // south, so the row is mirrored exactly as the mesh builder mirrors it.
    const float px = player.x;
    const float pz = static_cast<float>(gta2::kMapHeight) - player.y;
    const float py = player.z;
    // The camera's yaw convention: 0 looks north (+z), and Forward() is
    // (sin yaw, ., cos yaw). The game's facing is (dirX east, dirY south).
    const float headingYaw = player.facingKnown ? std::atan2(player.dirX, -player.dirY) : followYaw_;

    Solve(player, queries, dt, camera, px, py, pz, headingYaw, player.inVehicle);
    return true;
}

namespace {

// A cheap, smooth, non-repeating wobble for the impact shake: three sines at
// incommensurate frequencies.
float Wobble(double t, float f) {
    return 0.5f * static_cast<float>(std::sin(t * f * 6.2832) + 0.6 * std::sin(t * f * 9.17 + 1.3) +
                                     0.3 * std::sin(t * f * 15.31 + 2.1));
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
    }

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
    shake_ *= std::exp(-dt / 0.22f);
    shakeClock_ += dt;

    // The floor under him: the lid at or below his own level. His own level is a
    // per-block step on ramps and kerbs, so the floor is eased.
    float floor = py;
    if (!(q.floorAt && q.floorAt(q.context, px, pz, py + 0.75f, &floor))) floor = py;
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

    if (mode == ViewMode::FirstPerson) {
        float eyeHeight = inVehicle ? s.fpEyeCar : s.fpEyeFoot;
        float ahead = inVehicle ? s.fpForwardCar : s.fpForwardFoot;
        float seat = 0.0f;
        if (inVehicle) {
            // In the cabin of the car's 3D body, when it has one: the driver's head.
            float deck, roof, screen, halfWidth;
            if (CarBodiesCabin(player.vehicleSprite, &deck, &roof, &screen, &halfWidth)) {
                eyeHeight = deck + (roof - deck) * s.fpEyeCabin;
                ahead = screen - s.fpBehindScreen;
                seat = halfWidth * s.fpSeatCar;
            }
        }
        // Sideways is the heading turned a quarter: (-hz, hx) is the car's left.
        gta2::Vec3 eye{px + hx * ahead - hz * seat, baseY + eyeHeight, pz + hz * ahead + hx * seat};
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
        // The view heading lags the game's: a rate cap and a short ease, so an
        // about-face is a half-second sweep rather than a two-frame whirl. At
        // the wheel it also leans a little toward where the car is going.
        if (!inVehicle && g_navActive) {
            // The view is its own: the keys turn it (in the poll) and the mouse
            // adds to it; the pedestrian is steered to follow it, so what the
            // game does with his heading never swings the picture.
            g_fpViewYaw = WrapAngle(g_fpViewYaw + look.yaw);
            look.yaw = 0.0f;
            fpYaw_ = g_fpViewYaw;
            fpYawVel_ = 0.0f;
        } else {
            float target = headingYaw;
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
        if (inVehicle && s.fpLean > 0.0f) {
            // The nose dips under braking and lifts under power; the head leans
            // into a turn.
            pitch += (std::max)((std::min)(forwardAccel_ / 25.0f, 1.0f), -1.0f) * 2.5f * kDegToRad * s.fpLean;
            yawRate_ += (fpYawVel_ - yawRate_) * (1.0f - std::exp(-dt / 0.15f));
            roll += (std::max)((std::min)(yawRate_ * speedFrac_ * 0.5f, 1.0f), -1.0f) * 3.0f * kDegToRad * s.fpLean;
        }
        lastYaw_ = fpYaw_;
        followYaw_ = fpYaw_;   // so a switch to the chase view starts from where the eyes look
        followYawVel_ = fpYawVel_;

        // The kick of an impact, and the stretch of speed.
        if (shake_ > 0.001f) {
            yaw += Wobble(shakeClock_, 7.0f) * 2.5f * kDegToRad * shake_;
            pitch += Wobble(shakeClock_ + 3.1, 9.0f) * 2.0f * kDegToRad * shake_;
            roll += Wobble(shakeClock_ + 7.7, 5.0f) * 2.0f * kDegToRad * shake_;
        }
        pitch = (std::min)((std::max)(pitch, -80.0f * kDegToRad), 80.0f * kDegToRad);
        const float fov = (std::min)((std::max)(s.fpFov, 30.0f), 120.0f) + s.speedFov * speedFrac_;

        camera->SetPosition(eye);
        camera->SetOrientation(yaw, pitch);
        camera->SetRoll(roll);
        camera->SetFovY((std::min)(fov, 140.0f) * kDegToRad);
        LogCameraFrame("first", yaw, headingYaw, dt);
        {
            // Once a second: where the eye is against the floor under him, for the log.
            static float logClock = 0.0f;
            logClock += dt;
            if (logClock > 1.0f) {
                logClock = 0.0f;
                float under = 0.0f;
                const bool hasUnder = q.floorAt && q.floorAt(q.context, eye.x, eye.z, eye.y + 0.75f, &under);
                Log("view: fp eye %.2f,%.2f,%.2f  player y=%.2f floor=%.2f  lid under the eye=%s%.2f",
                    eye.x, eye.y, eye.z, py, floorY_, hasUnder ? "" : "none ", under);
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
    float orbitYaw;
    if (!inVehicle) {
        // An orbit camera: the mouse turns it directly, the player turns inside
        // the frame, and only the direction he walks in draws it slowly round
        // behind him. It never spins with his heading.
        followYaw_ = WrapAngle(followYaw_ + look.yaw);
        look.yaw = 0.0f;
        const float scale = ViewTurnSpeedScale();
        const bool walking = speed > 0.6f;
        const float walkYaw = walking ? std::atan2(velX_, velZ_) : followYaw_;
        if (s.tpOrbitFollow) {
            // Drift round behind whichever way he walks.
            const float rate = s.turnRateFoot * scale * kDegToRad;
            SpringTurn(&followYaw_, &followYawVel_, walkYaw, 2.0f / (std::max)(s.tpOrbitTau, 0.1f), rate > 0.0f ? rate : 0.0f, dt);
            awayTime_ = 0.0f;
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
    // A tall vehicle (truck cab, bus, van) fills the frame from the sedan
    // distance: the chase pulls back and rises with the body's roof, which the
    // car bodies know (a sedan roof is about 0.35 blocks, a truck cab 0.9).
    float tall = 1.0f;
    if (inVehicle) {
        float deck, roof, screen, halfWidth;
        if (CarBodiesCabin(player.vehicleSprite, &deck, &roof, &screen, &halfWidth) && roof > 0.45f)
            tall = (std::min)(1.0f + (roof - 0.45f) * 1.6f, 1.8f);
    }
    const float distance = ((std::max)(s.tpDistance, 0.5f) + s.tpPullBack * speedFrac_) * scale * tall;
    const float height = (s.tpHeight + 0.25f * s.tpPullBack * speedFrac_) * scale * tall;
    const float lookAhead = (s.tpLookAhead + 0.8f * speedFrac_) * scale;
    const float lookHeight = s.tpLookHeight * scale;
    // Over the shoulder on foot: the camera, and what it looks at, sit a little
    // to the right of him, so he is not a figure in the dead centre.
    const float shoulder = inVehicle ? 0.0f : s.tpShoulder * scale;
    const float sx = std::cos(followYaw_), sz = -std::sin(followYaw_);   // right of the chase yaw

    // The point looked at is a little ahead of him along his heading, which is
    // what keeps the road ahead in the frame rather than his roof.
    // On foot the point looked at is ahead along the camera, not his heading:
    // an orbit camera frames the street it looks down, whichever way he faces.
    const float ax = inVehicle ? hx : std::sin(yaw), az = inVehicle ? hz : std::cos(yaw);
    const gta2::Vec3 lookAt{px + ax * lookAhead + sx * shoulder, baseY + lookHeight,
                            pz + az * lookAhead + sz * shoulder};

    // Where the camera wants to be: behind, above, swung by the mouse orbit.
    const float cp = std::cos(orbitPitch), sp = std::sin(orbitPitch);
    gta2::Vec3 desired{px - std::sin(yaw) * distance * cp + sx * shoulder, baseY + height + distance * sp,
                       pz - std::cos(yaw) * distance * cp + sz * shoulder};

    // Not through a wall: walk from just above his head out to where the camera
    // wants to be and stop short of the first solid block.
    if (s.tpCollide && q.blocked) {
        const gta2::Vec3 pivot{px, baseY + 0.6f, pz};
        constexpr int kSteps = 32;
        float reach = 1.0f;
        for (int i = 1; i <= kSteps; ++i) {
            const float t = static_cast<float>(i) / kSteps;
            const gta2::Vec3 p = pivot + (desired - pivot) * t;
            if (q.blocked(q.context, p.x, p.y, p.z)) {
                reach = static_cast<float>(i - 1) / kSteps - 0.03f;
                break;
            }
        }
        // Never closer than a stride from a car, whatever is in the way: nearer
        // than that the camera is inside its own body. On foot the figure is
        // small (under half a block), so the camera may come in to half a block;
        // and when a wall holds it that close it rises instead, so the view is
        // down over his head rather than into the stonework behind him.
        const gta2::Vec3 span = desired - pivot;
        const float spanLength = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
        const float minPull = inVehicle ? 1.4f : 0.5f;
        const float minReach = spanLength > 1e-3f ? (std::min)(1.0f, minPull / spanLength) : 1.0f;
        reach = (std::max)(reach, minReach);
        desired = pivot + (desired - pivot) * reach;
        if (!inVehicle && reach < 0.6f) {
            const float rise = (0.6f - reach) * 1.2f;
            if (!q.blocked(q.context, desired.x, desired.y + rise, desired.z)) desired.y += rise;
        }
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
    if (q.panelDistance) {
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
                    if (q.blocked && q.blocked(q.context, p.x, p.y, p.z)) break;
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

    // The camera moves with him first, so that at a steady speed it never
    // trails, and is then eased onto where it wants to be: a swing or a pull-in
    // is spread over a few frames, straight-line motion is not.
    eyeX_ += velX_ * dt;
    eyeZ_ += velZ_ * dt;
    const float ease = 1.0f - std::exp(-dt / 0.09f);
    eyeX_ += (desired.x - eyeX_) * ease;
    eyeY_ += (desired.y - eyeY_) * ease;
    eyeZ_ += (desired.z - eyeZ_) * ease;
    // But never further than a block from where it should be - a cut, a wall -
    // which is where easing would show as the camera arriving late.
    {
        const float dx = desired.x - eyeX_, dy = desired.y - eyeY_, dz = desired.z - eyeZ_;
        const float away = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (away > 1.0f) {
            const float pull = (away - 1.0f) / away;
            eyeX_ += dx * pull;
            eyeY_ += dy * pull;
            eyeZ_ += dz * pull;
        }
    }

    gta2::Vec3 eye{eyeX_, eyeY_, eyeZ_};
    if (shake_ > 0.001f) {
        eye.x += Wobble(shakeClock_, 11.0f) * 0.04f * shake_;
        eye.y += Wobble(shakeClock_ + 2.3, 13.0f) * 0.03f * shake_;
    }
    const gta2::Vec3 dir = lookAt - eye;
    const float flat = std::hypot(dir.x, dir.z);
    float camYaw = flat > 1e-5f ? std::atan2(dir.x, dir.z) : yaw;
    float camPitch = std::atan2(dir.y, (std::max)(flat, 1e-5f));
    // The orientation that is actually set is what the player sees, and the
    // eye's own lag can swing it faster than the orbit's yaw (a car turning
    // under a camera still on its way): the cap applies to it too, so no frame
    // turns the picture more than the rate allows at 30 fps.
    {
        const float cap = (inVehicle ? s.turnRateCar : s.turnRateFoot) * ViewTurnSpeedScale() * kDegToRad * (std::min)(dt, 1.0f / 30.0f);
        if (finalYawKnown_ && cap > 0.0f) {
            const float d = WrapAngle(camYaw - finalYaw_);
            camYaw = WrapAngle(finalYaw_ + (std::max)(-cap, (std::min)(cap, d)));
        }
        finalYaw_ = camYaw;
        finalYawKnown_ = true;
    }
    // Lean into the turn: a few degrees of roll with the rate of turn, at speed.
    float roll = (std::max)((std::min)(-yawRate_ * speedFrac_ * 0.35f, 1.0f), -1.0f) * 3.5f * kDegToRad * s.tpLean;
    if (shake_ > 0.001f) {
        camYaw += Wobble(shakeClock_ + 1.1, 8.0f) * 1.5f * kDegToRad * shake_;
        camPitch += Wobble(shakeClock_ + 4.2, 10.0f) * 1.2f * kDegToRad * shake_;
        roll += Wobble(shakeClock_ + 6.5, 6.0f) * 1.5f * kDegToRad * shake_;
    }
    roll_ += (roll - roll_) * (1.0f - std::exp(-dt / 0.15f));
    const float fov = (std::min)((std::max)(s.tpFov, 20.0f), 110.0f) + s.speedFov * speedFrac_;

    camera->SetPosition(eye);
    camera->SetOrientation(camYaw, camPitch);
    camera->SetRoll(roll_);
    camera->SetFovY((std::min)(fov, 130.0f) * kDegToRad);
    LogCameraFrame("third", camYaw, headingYaw, dt);
    yawDegrees = camYaw / kDegToRad;
    pitchDegrees = camPitch / kDegToRad;
    g_navCamYaw = camYaw;
    g_navHeading = headingYaw;
    g_navInVehicle = inVehicle;
    g_navHeadingKnown = player.facingKnown;
    status_ = inVehicle ? "third person, following the car"
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

}  // namespace gta2dx9
