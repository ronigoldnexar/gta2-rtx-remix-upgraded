#include "view_modes.h"

#include <algorithm>
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

bool WarpPlayerToParkedCar(float within) {
    PlayerState player;
    if (!LocatePlayer(&player) || !player.valid || player.inVehicle || !player.ped) return false;
    float cx = 0.0f, cy = 0.0f, d = 0.0f;
    bool driven = false;
    const void* car = nullptr;
    if (!NearestVehicle(player.x, player.y, within, true, &cx, &cy, &d, &driven, &car)) return false;
    float hx = 0.0f, hy = 1.0f;
    VehicleFacing(car, &hx, &hy);
    // The driver's door is on the car's left: facing (hx, hy) with y south,
    // left is (hy, -hx).
    const float tx = cx + 0.55f * hy;
    const float ty = cy - 0.55f * hx;
    const uintptr_t ped = reinterpret_cast<uintptr_t>(player.ped);
    uintptr_t physics = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    uintptr_t place = 0;
    if (!ReadAt(physics + game::kPhysicsSprite, &place) || !Plausible(place)) return false;
    const int32_t fx = static_cast<int32_t>(tx * (1 << 14));
    const int32_t fy = static_cast<int32_t>(ty * (1 << 14));
    bool ok = WriteAt(place + game::kPlaceX, fx) && WriteAt(place + game::kPlaceY, fy);
    ok = WriteAt(ped + game::kPedX, fx) && WriteAt(ped + game::kPedY, fy) && ok;
    Log("devtools: warped the player from %.2f,%.2f to %.2f,%.2f, the driver's door of the parked car at %.2f,%.2f "
        "heading %.2f,%.2f (%s)",
        player.x, player.y, tx, ty, cx, cy, hx, hy, ok ? "written" : "write failed");
    return ok;
}

bool WarpSceneToRoad(float x, float y, float z) {
    PlayerState player;
    if (!LocatePlayer(&player) || !player.valid || player.inVehicle || !player.ped) {
        Log("devtools: scene warp ignored (player not located on foot)");
        return false;
    }
    float cx = 0.0f, cy = 0.0f, d = 0.0f;
    bool driven = false;
    const void* car = nullptr;
    const uint8_t* place = nullptr;
    if (NearestVehicle(player.x, player.y, 250.0f, true, &cx, &cy, &d, &driven, &car)) {
        place = game::Placement(static_cast<const uint8_t*>(car), game::kVehiclePlacementPtr);
    }
    if (!place) {
        // No parked car to bring: move the player alone (objects and views can still be checked there).
        const float tx = x, ty = y - 0.55f;
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
        Log("devtools: no parked car within reach; moved the player alone from %.2f,%.2f to %.2f,%.2f (%s)",
            player.x, player.y, tx, ty, ok ? "written" : "write failed");
        return ok;
    }
    const uintptr_t placeAt = reinterpret_cast<uintptr_t>(place);
    // East: sin = 1, cos = 0 - a quarter of the game's 0x5A0 turn.
    const uint16_t east = static_cast<uint16_t>(game::kAngleFullTurn / 4);
    bool ok = WriteAt(placeAt + game::kPlaceX, static_cast<int32_t>(x * (1 << 14))) &&
              WriteAt(placeAt + game::kPlaceY, static_cast<int32_t>(y * (1 << 14))) &&
              WriteAt(placeAt + game::kPlaceHeading, east);
    // The driver's door: the left of a car facing east is its north side.
    const float tx = x, ty = y - 0.55f;
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
    Log("devtools: moved the parked car at %.2f,%.2f (%.2f tiles off) to %.2f,%.2f heading east and the player from "
        "%.2f,%.2f to its door at %.2f,%.2f (%s)",
        cx, cy, d, x, y, player.x, player.y, tx, ty, ok ? "written" : "write failed");
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

    // The game's own control keys, as this process sees them, for reading a
    // scripted session back: one line per press and release.
    if (g_settings.devWarpKey > 0 && g_settings.devWarpKey < 256 && worldLoaded &&
        (GetAsyncKeyState(g_settings.devWarpKey) & 0x0001) != 0) {
        WarpPlayerToParkedCar(80.0f);
    }
    if (g_settings.devSceneKey > 0 && g_settings.devSceneKey < 256 && worldLoaded &&
        (GetAsyncKeyState(g_settings.devSceneKey) & 0x0001) != 0) {
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
    const int dx = cursor.x - centre.x;
    const int dy = cursor.y - centre.y;
    if (dx == 0 && dy == 0) return;
    SetCursorPos(centre.x, centre.y);
    const float perCount = 0.12f * kDegToRad * (std::max)(0.05f, g_settings.mouseSensitivity);
    g_look.yaw = WrapAngle(g_look.yaw + static_cast<float>(dx) * perCount);
    g_look.pitch += static_cast<float>(g_settings.invertY ? dy : -dy) * perCount;
    g_look.pitch = (std::min)((std::max)(g_look.pitch, -85.0f * kDegToRad), 85.0f * kDegToRad);
    g_look.lastMoved = Now();
}

// ---------------------------------------------------------------------------
// The camera itself
// ---------------------------------------------------------------------------

void ViewCameraSolver::Reset() {
    settled_ = false;
    floorSettled_ = false;
    status_ = "classic";
    velX_ = velZ_ = 0.0f;
    speedFrac_ = 0.0f;
    yawRate_ = 0.0f;
    roll_ = 0.0f;
    shake_ = 0.0f;
    forwardAccel_ = 0.0f;
    speed = 0.0f;
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
        return false;
    }
    if (!player.valid) {
        status_ = "waiting for the player to be found";
        settled_ = false;
        camera->SetRoll(0.0f);
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
        float yaw = WrapAngle(headingYaw + look.yaw);
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
            const float yawRate = WrapAngle(headingYaw - lastYaw_) / dt;
            yawRate_ += (yawRate - yawRate_) * (1.0f - std::exp(-dt / 0.15f));
            roll += (std::max)((std::min)(yawRate_ * speedFrac_ * 0.5f, 1.0f), -1.0f) * 3.0f * kDegToRad * s.fpLean;
        }
        lastYaw_ = headingYaw;

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
        status_ = inVehicle ? "first person, at the wheel" : "first person, on foot";
        return;
    }

    // --- Third person -----------------------------------------------------
    // The camera's own yaw eases round behind the player, so a turn swings the
    // view over a few tenths of a second rather than snapping; quicker at speed,
    // where a camera that dawdles loses the road.
    const float tau = (std::max)(s.tpFollow, 0.01f) * (1.0f - 0.45f * speedFrac_);
    followYaw_ = WrapAngle(followYaw_ + WrapAngle(chaseYaw - followYaw_) * (1.0f - std::exp(-dt / tau)));
    const float rawYawRate = WrapAngle(followYaw_ - lastYaw_) / dt;
    lastYaw_ = followYaw_;
    yawRate_ += (rawYawRate - yawRate_) * (1.0f - std::exp(-dt / 0.12f));
    const float yaw = WrapAngle(followYaw_ + look.yaw);
    const float orbitPitch = (std::min)((std::max)(look.pitch, -20.0f * kDegToRad), 70.0f * kDegToRad);

    const float scale = inVehicle ? 1.0f : (std::max)(s.tpFootScale, 0.2f);
    const float distance = ((std::max)(s.tpDistance, 0.5f) + s.tpPullBack * speedFrac_) * scale;
    const float height = (s.tpHeight + 0.25f * s.tpPullBack * speedFrac_) * scale;
    const float lookAhead = (s.tpLookAhead + 0.8f * speedFrac_) * scale;
    const float lookHeight = s.tpLookHeight * scale;
    // Over the shoulder on foot: the camera, and what it looks at, sit a little
    // to the right of him, so he is not a figure in the dead centre.
    const float shoulder = inVehicle ? 0.0f : s.tpShoulder * scale;
    const float sx = std::cos(followYaw_), sz = -std::sin(followYaw_);   // right of the chase yaw

    // The point looked at is a little ahead of him along his heading, which is
    // what keeps the road ahead in the frame rather than his roof.
    const gta2::Vec3 lookAt{px + hx * lookAhead + sx * shoulder, baseY + lookHeight,
                            pz + hz * lookAhead + sz * shoulder};

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
    yawDegrees = camYaw / kDegToRad;
    pitchDegrees = camPitch / kDegToRad;
    status_ = inVehicle ? "third person, following the car" : "third person, following on foot";
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
