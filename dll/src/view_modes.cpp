#include "view_modes.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "../../src/gta2_map.h"
#include "game_access.h"
#include "log.h"

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

uintptr_t ScanForPed(uintptr_t base, uintptr_t bytes, uintptr_t* offsetOut) {
    for (uintptr_t offset = 0; offset < bytes; offset += sizeof(uintptr_t)) {
        uintptr_t candidate = 0;
        if (!ReadAt(base + offset, &candidate)) continue;
        if (candidate == base) continue;
        if (PedSignature(candidate)) {
            *offsetOut = offset;
            return candidate;
        }
    }
    return 0;
}

uintptr_t RememberedPed() {
    uintptr_t playerObject = 0;
    switch (g_slot) {
        case Slot::PlayerObjectIsPed:
            if (ReadAt(kPlayerObjectPtr, &playerObject) && PedSignature(playerObject)) return playerObject;
            return 0;
        case Slot::PlayerObject: {
            uintptr_t ped = 0;
            if (ReadAt(kPlayerObjectPtr, &playerObject) && Plausible(playerObject) &&
                ReadAt(playerObject + g_slotOffset, &ped) && PedSignature(ped)) {
                return ped;
            }
            return 0;
        }
        case Slot::Camera: {
            const uint8_t* camera = game::CameraStruct();
            uintptr_t ped = 0;
            if (camera && ReadAt(reinterpret_cast<uintptr_t>(camera) + g_slotOffset, &ped) &&
                PedSignature(ped)) {
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
        return false;
    }

    uintptr_t ped = RememberedPed();
    if (ped) {
        out->source = g_slot == Slot::Camera ? "camera" : "player object";
    } else if (--g_scanCooldown <= 0) {
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

    // Neither place held him: the camera itself says where he is.
    if (!ped) {
        float camX = 0.0f, camY = 0.0f;
        game::CameraPosition(&camX, &camY);
        if (g_nearPed && g_nearPedDist < 1.0f && PedSignature(reinterpret_cast<uintptr_t>(g_nearPed))) {
            ped = reinterpret_cast<uintptr_t>(g_nearPed);
            out->source = "pedestrian at the camera";
        } else if (uintptr_t car = DrivenCarAtCamera(camX, camY)) {
            uintptr_t driver = 0;
            if (ReadAt(car + game::kVehicleDriver, &driver) && PedSignature(driver)) {
                ped = driver;
                out->source = "driven car at the camera";
            }
        }
    }
    if (!ped) return false;

    const uint8_t* pedBytes = reinterpret_cast<const uint8_t*>(ped);
    uintptr_t physics = 0;
    if (!ReadAt(ped + game::kPedPhysics, &physics) || !Plausible(physics)) return false;
    const uint8_t* physicsBytes = reinterpret_cast<const uint8_t*>(physics);
    uintptr_t sprite = 0;
    ReadAt(physics + game::kPhysicsSprite, &sprite);

    out->ped = pedBytes;
    out->pedSprite = reinterpret_cast<const void*>(sprite);

    // Where he is and which way he faces, off his sprite object, which is the
    // placement block the game moves him by. The ped's own copy of the position
    // is the fallback.
    float x = 0.0f, y = 0.0f, z = 0.0f;
    bool placed = game::ReadPlacement(physicsBytes, game::kPhysicsSprite, &x, &y, &z);
    if (!placed) {
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
    out->facingKnown = game::ReadFacing(physicsBytes, game::kPhysicsSprite, &dirX, &dirY);

    // In a car, the car is the thing to follow.
    uintptr_t vehicle = 0;
    if (ReadAt(ped + game::kPedVehicle, &vehicle) && Plausible(vehicle)) {
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

    DWORD pid = 0;
    if (HWND foreground = GetForegroundWindow()) GetWindowThreadProcessId(foreground, &pid);
    const bool ours = pid == GetCurrentProcessId();

    // Polled, like F4: GTA2 reads its keyboard through DirectInput, so there is
    // no message to take it from. Alt is excluded so Alt+key chords stay the
    // system's.
    const bool altDown = (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
    const int key = g_settings.toggleKey;
    const bool keyDown = key > 0 && key < 256 && (GetAsyncKeyState(key) & 0x8000) != 0 && !altDown;
    if (keyDown && !keyWasDown && ours && !menuVisible) CycleViewMode();
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
        return false;
    }
    if (!player.valid) {
        status_ = "waiting for the player to be found";
        settled_ = false;
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
        floorSettled_ = false;
        settled_ = true;
        g_look = ViewLook{};
        eyeX_ = px;
        eyeY_ = py + 1.0f;
        eyeZ_ = pz;
    }
    lastX_ = px;
    lastZ_ = pz;

    // The floor under him: the lid at or below his own level. His own level is a
    // per-block step on ramps and kerbs, so the floor is eased.
    float floor = py;
    if (q.floorAt && q.floorAt(q.context, px, pz, py + 0.75f, &floor)) {
        // keep it
    } else {
        floor = py;
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

    if (mode == ViewMode::FirstPerson) {
        const float eyeHeight = inVehicle ? s.fpEyeCar : s.fpEyeFoot;
        const float ahead = inVehicle ? s.fpForwardCar : s.fpForwardFoot;
        const float fx = std::sin(headingYaw), fz = std::cos(headingYaw);
        const gta2::Vec3 eye{px + fx * ahead, baseY + eyeHeight, pz + fz * ahead};
        const float yaw = WrapAngle(headingYaw + look.yaw);
        const float pitch = (std::min)((std::max)(look.pitch, -80.0f * kDegToRad), 80.0f * kDegToRad);
        camera->SetPosition(eye);
        camera->SetOrientation(yaw, pitch);
        camera->SetFovY((std::min)((std::max)(s.fpFov, 30.0f), 120.0f) * kDegToRad);
        eyeX_ = eye.x;
        eyeY_ = eye.y;
        eyeZ_ = eye.z;
        yawDegrees = yaw / kDegToRad;
        pitchDegrees = pitch / kDegToRad;
        status_ = inVehicle ? "first person, at the wheel" : "first person, on foot";
        return;
    }

    // Third person. The camera's own yaw eases round behind the player, so a
    // turn swings the view over a few tenths of a second rather than snapping.
    const float tau = (std::max)(s.tpFollow, 0.01f);
    followYaw_ = WrapAngle(followYaw_ + WrapAngle(headingYaw - followYaw_) * (1.0f - std::exp(-dt / tau)));
    const float yaw = WrapAngle(followYaw_ + look.yaw);
    const float orbitPitch = (std::min)((std::max)(look.pitch, -20.0f * kDegToRad), 70.0f * kDegToRad);

    const float scale = inVehicle ? 1.0f : (std::max)(s.tpFootScale, 0.2f);
    const float distance = (std::max)(s.tpDistance, 0.5f) * scale;
    const float height = s.tpHeight * scale;
    const float lookAhead = s.tpLookAhead * scale;
    const float lookHeight = s.tpLookHeight * scale;

    // The point looked at is a little ahead of him along his heading, which is
    // what keeps the road ahead in the frame rather than his roof.
    const float hx = std::sin(followYaw_), hz = std::cos(followYaw_);
    const gta2::Vec3 lookAt{px + hx * lookAhead, baseY + lookHeight, pz + hz * lookAhead};

    // Where the camera wants to be: behind, above, swung by the mouse orbit.
    const float cp = std::cos(orbitPitch), sp = std::sin(orbitPitch);
    gta2::Vec3 desired{px - std::sin(yaw) * distance * cp, baseY + height + distance * sp,
                       pz - std::cos(yaw) * distance * cp};

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
        reach = (std::max)(reach, 0.12f);
        desired = pivot + (desired - pivot) * reach;
    }
    // And never under the floor it is over.
    if (q.floorAt) {
        float under = 0.0f;
        if (q.floorAt(q.context, desired.x, desired.z, desired.y + 0.05f, &under) && desired.y < under + 0.25f) {
            desired.y = under + 0.25f;
        }
    }

    // Eased into place. Short, so the car never gets away from it; a collision
    // pull-in is quick too, since a camera inside a wall is worse than a jolt.
    const float ease = 1.0f - std::exp(-dt / 0.07f);
    eyeX_ += (desired.x - eyeX_) * ease;
    eyeY_ += (desired.y - eyeY_) * ease;
    eyeZ_ += (desired.z - eyeZ_) * ease;

    const gta2::Vec3 eye{eyeX_, eyeY_, eyeZ_};
    const gta2::Vec3 dir = lookAt - eye;
    const float flat = std::hypot(dir.x, dir.z);
    const float camYaw = flat > 1e-5f ? std::atan2(dir.x, dir.z) : yaw;
    const float camPitch = std::atan2(dir.y, (std::max)(flat, 1e-5f));
    camera->SetPosition(eye);
    camera->SetOrientation(camYaw, camPitch);
    camera->SetFovY((std::min)((std::max)(s.tpFov, 20.0f), 110.0f) * kDegToRad);
    yawDegrees = camYaw / kDegToRad;
    pitchDegrees = camPitch / kDegToRad;
    status_ = inVehicle ? "third person, following the car" : "third person, following on foot";
    (void)player;
}

}  // namespace gta2dx9
