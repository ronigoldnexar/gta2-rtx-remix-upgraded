// Third-person and first-person views, as a modern game has them, on top of
// GTA2's own top-down camera.
//
// The renderer already draws the city as true 3D geometry and places every car
// and pedestrian in it as a real object, so there is nothing stopping the
// camera from standing behind the player or sitting in his head - except that
// the game only ever tells the renderer where its *own* camera is. So the
// player is found in gta2.exe's state (see LocatePlayer), the view is built
// from where he is and which way he faces, and the game's own camera is left
// to do what it always did: decide what is simulated and drawn.
//
// Three modes, cycled with one key (V out of the box):
//
//   Classic       GTA2's view, from above, exactly as before.
//   Third person  a chase camera behind the player, on foot or at the wheel,
//                 with mouse orbit that swings back behind him on its own.
//   First person  from his eyes, or the driving seat; mouse look.
//
// Everything here is a setting on the Camera tab of the F4 menu and saved with
// everything else.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>

#include "../../src/camera.h"

namespace gta2dx9 {

enum class ViewMode : int { Classic = 0, ThirdPerson = 1, FirstPerson = 2 };
constexpr int kViewModeCount = 3;

struct ViewModeSettings {
    // Log every press and release of the game's control keys (a developer
    // aid for scripted sessions): [devtools] log_keys=1.
    bool logKeys = false;
    // A developer aid for scripted sessions: this key moves the player to the
    // driver's door of the nearest parked car ([devtools] warp_key=F9; 0 off).
    int devWarpKey = 0;
    // And this one brings the nearest parked car to a given spot on the map,
    // heading east, with the player at its driver's door: [devtools]
    // scene_key=F10, scene_xy=164.5,149.5 (the Downtown start's carriageway).
    int devSceneKey = 0;
    float devSceneX = 0.0f, devSceneY = 0.0f;
    float devSceneZ = -1.0f;   // map level for the scene warp; < 0 leaves the level alone
    // The ini the scene spot was read from: re-read on every press, so a test
    // script can retarget the warp mid-run by editing [devtools] scene_xy.
    char devIniPath[260] = {};
    // ViewMode, as an int so the settings table can carry it.
    int mode = 0;
    // The virtual-key code that cycles the modes. 'V' is free in GTA2's own
    // default controls.
    int toggleKey = 'V';

    bool mouseLook = true;
    float mouseSensitivity = 1.0f;   // 1 is a quarter turn (90 degrees) across the window's width
    bool invertY = false;
    // A VNC or remote-desktop pointer arrives as absolute positions, so the
    // warp-to-centre scheme sees jumps; a frame's motion is clamped to this many
    // counts each way, and a jump too big to be a hand (eight times it) is taken
    // as the pointer being parked and ignored.
    float mouseMaxStep = 25.0f;

    // How fast the camera may turn, degrees a second. GTA2's pedestrian spins
    // about-face in a few frames; a camera that follows that 1:1 whirls the
    // whole world, so the chase camera and the first-person view turn at a
    // bounded rate on a critically damped spring, the way a modern game's do.
    // The game's own turning is untouched; only the picture lags it.
    float turnRateFoot = 180.0f;
    float turnRateCar = 240.0f;
    // First person: the view heading eases onto the game's over this long
    // (seconds), on top of the rate cap.
    float fpSmooth = 0.12f;

    // Third person. Distances in blocks: a GTA2 block is about 2 m, a car about
    // one block long.
    float tpDistance = 3.4f;        // behind the target
    float tpHeight = 1.25f;         // above it
    float tpLookAhead = 1.2f;       // the point looked at, blocks ahead of the target...
    float tpLookHeight = 0.35f;     // ...and above it
    float tpFootScale = 0.62f;      // distance and height are scaled by this on foot (0.46-block people)
    float tpFov = 60.0f;            // vertical, degrees
    float tpFollow = 0.25f;         // seconds the camera takes to swing round behind a turn
    float tpReturnDelay = 1.5f;     // seconds after the last mouse input before the orbit returns
    bool tpCollide = true;          // pulled in front of walls rather than through them
    float tpShoulder = 0.22f;       // on foot, the camera sits this far to the right (over the shoulder)
    float tpPullBack = 1.0f;        // extra blocks of distance at full speed
    float tpLean = 0.0f;            // roll into turns, 1 is a few degrees at speed; off by default

    // First person.
    float fpEyeFoot = 0.43f;        // eye height above the floor on foot: 0.93 of the 0.46-block adult (live_geometry.cpp kPedHeight)
    float fpEyeCar = 0.30f;         // ... at the wheel of a car without a 3D body (the sprite dome is 0.42 tall)
    float fpForwardFoot = 0.12f;    // the eye sits this far ahead of the object's centre
    float fpForwardCar = 0.30f;
    // At the wheel of a car drawn as a 3D body (CarBodiesCabin): the eye sits in
    // the cabin instead - this far up between the hood line and the roof, this far
    // behind the windscreen's base, and this far from the middle (positive: the
    // left seat; as a fraction of half the car's width).
    float fpEyeCabin = 0.62f;
    float fpBehindScreen = 0.12f;
    float fpSeatCar = 0.45f;
    float fpFov = 70.0f;
    bool fpHideOwnBody = true;      // the player's own sprite, and his car, are not drawn
    float fpReturnDelay = 2.0f;     // free look swings back to straight ahead after this
    float fpHeadBob = 0.5f;         // walking bob on foot; 0 is none
    float fpLean = 0.0f;            // in a car: nose dip under braking, lean into turns; off by default

    // Both.
    // Pedestrians are drawn from above and lie flat on the road, which from a low
    // camera is a line. With this on, each one on his feet is stood up as a
    // billboard facing the camera: a paper figure, but a visible one.
    bool uprightPeds = true;
    // How much more of the world gta2.exe is told it shows. The game creates,
    // draws and removes cars and pedestrians inside the window its own camera
    // frames; a chase camera sees well beyond that window, so it is widened by
    // this factor while a chase or first-person view is up. 1 leaves it alone.
    float gameViewScale = 2.6f;      // 2.6 and square: traffic exists 15 blocks out in every direction (was 1.8, 6 blocks ahead on the short axis)
    // Motion. Speeds are in blocks a second; a GTA2 car flat out does roughly
    // the reference speed, and the effects below reach full strength there.
    float referenceSpeed = 8.0f;
    float speedFov = 4.0f;          // extra degrees of field of view at full speed (subtle)
    float impactShake = 0.0f;       // the camera's kick on a hard stop; 0 is none (default off)
    // RTX Remix's own motion blur, pushed through its API while a chase or
    // first-person view is up: 0 leaves Remix's setting alone, 1 turns it on
    // there and back off in the classic view, 2 keeps it on everywhere.
    int motionBlur = 0;

    // Cars seen from the ground. From above a car is a flat picture with a low
    // dome, which is right for the top-down view and a card seen edge-on from a
    // chase camera. While a chase or first-person view is up the dome is made
    // car-height and boxier, and the tyres are drawn, and the top-down numbers
    // come back when it is switched off. Blocks and an exponent (lower is boxier).
    float groundCarHeight = 0.42f;
    float groundCarShoulder = 0.35f;
    bool groundCarWheels = true;
    // Pedestrians seen from the ground: small three-dimensional figures that walk
    // (legs and arms swinging with their speed), in place of the top-down sprite.
    // Off leaves the sprites as billboards facing the camera.
    bool groundPedFigures = true;
    // Imported 3D models (gta2dx9_models\ beside the game, see
    // tools/import_assets.py) in place of the cars' domes and the pedestrian
    // figures, in the ground views. Off keeps the domes and the box figures.
    bool groundModels = true;

    // The move between views. Rather than a cut, the camera travels from where
    // it is to where the new view wants it - position along an arc that rises
    // over the city, heading by the shortest turn, pitch, roll and field of
    // view each eased - over this many seconds (0 cuts). The arc's height is a
    // fraction of the distance travelled, so a drop from the sky to the street
    // stays clear of the rooftops on the way, and any point of the path that
    // would still be inside a building is lifted out of it.
    float transitionSeconds = 1.4f;
    float transitionArc = 0.25f;

    // For recording a demonstration: this many seconds after a level comes up
    // the view switches by itself to `demoSwitchTo`, as if the key had been
    // pressed. 0 (the default) never does. From gta2dx9.ini only, not saved.
    float demoSwitchSeconds = 0.0f;
    int demoSwitchTo = 2;
};

ViewModeSettings& ViewModes();
ViewMode CurrentViewMode();
void SetViewMode(ViewMode mode);
void CycleViewMode();
const char* ViewModeName(ViewMode mode);
// "V", "F6", "Num 0"... for the menu and the log.
const char* KeyName(int virtualKey);

// The player, as found in gta2.exe's own state. Coordinates are the game's:
// x east, y south, z the map level, one unit per block.
struct PlayerState {
    bool valid = false;
    bool inVehicle = false;
    const void* ped = nullptr;
    const void* vehicle = nullptr;
    // The sprite objects the game draws him, and his car, with - the thing
    // LiveGeometry sees as GameObjectBeingDrawn.
    const void* pedSprite = nullptr;
    const void* vehicleSprite = nullptr;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    float dirX = 0.0f, dirY = 1.0f;   // facing, in the game's frame
    bool facingKnown = false;
    const char* source = "";          // how he was found, for the menu
};

// Finds the player this frame. False in the menus, or until he is found.
//
// The ped is recognised by his own structure rather than by an address someone
// wrote down: ped -> physics object at +0x168, which points back at the ped from
// +0x7C and at his sprite object from +0x80, whose base is 3 (a pedestrian) and
// whose owner at +0x08 is the physics object again. Three cross-links that
// nothing else in the process satisfies by accident. The pointer to him is
// searched for in the player object (0x005EB4FC) and in the camera, and the
// slot that held him is remembered; if both fail, the pedestrian the game's
// camera is centred on, or the driven car it is centred on, is taken instead.
bool LocatePlayer(PlayerState* out);

// The sprite pass's contribution to the fallback above: the pedestrian on foot
// it drew nearest the game's camera centre this frame.
void NotePedNearCamera(const void* ped, float distanceTiles);

// The car nearest a point in the game's frame (x east, y south), for the log
// and for scripted play: false when there is none within `within` tiles.
bool NearestVehicle(float x, float y, float within, bool parkedOnly, float* vx, float* vy, float* distance,
                    bool* driven, const void** vehicle = nullptr);

// The driving-seat side of a car, for a script walking up to its door: the
// car's heading as a unit vector, and its pointer, for the log. False when
// `vehicle` is not a car the finder returned.
bool VehicleFacing(const void* vehicle, float* dirX, float* dirY);

// What the player's pedestrian structure says he is doing: the game's own
// state words, for reading a session back. Zero when unreadable.
struct PedWords {
    int32_t state = 0, sub = 0, pending = 0;
    uintptr_t vehicle = 0;
};
PedWords ReadPedWords(const void* ped);

// Moves the player's pedestrian to the driver's door of the nearest parked
// car within `within` tiles, writing the game's own position words (a
// developer aid for scripted sessions; see ViewModeSettings::devWarpKey).
bool WarpPlayerToParkedCar(float within);
// Moves the nearest parked car to (x, y) heading east and the player to its
// driver's door (the same developer aid, for a drive on a real road).
bool WarpSceneToRoad(float x, float y, float z = -1.0f);

// Polls the toggle key and, in a chase or first-person view, the mouse. The
// mouse is only taken while a level is up, the F4 menu is closed and the game is
// the foreground window; it is warped back to the middle of `presentWindow`
// each frame, which is how every game reads relative motion from a cursor.
void ViewModePollInput(HWND presentWindow, bool menuVisible, bool worldLoaded);

// What the camera solver needs to know about the world, without a dependency on
// the map classes. All in renderer coordinates: x east, y up, z north.
struct ViewQueries {
    void* context = nullptr;
    // The highest floor at or below `ceiling` under a point.
    bool (*floorAt)(void* context, float x, float z, float ceiling, float* y) = nullptr;
    // Whether a point is inside a solid block.
    bool (*blocked)(void* context, float x, float y, float z) = nullptr;
    // The distance from a point to the nearest flat panel (fence, railing) of
    // the block it is in; false when there is none.
    bool (*panelDistance)(void* context, float x, float y, float z, float* distance) = nullptr;
    // The highest surface at or below `ceiling` under a point, with its ground
    // type (1 road, 2 pavement, 3 field, 0 other); false when there is none.
    bool (*groundAt)(void* context, float x, float z, float ceiling, float* y, int* type) = nullptr;
    // A point inside a street prop's footprint (bin, bench, meter...) moved to
    // just outside it; false when it is clear.
    bool (*propPush)(void* context, float x, float y, float z, float* outX, float* outZ) = nullptr;
    // The road arrows of the surface under a point (GMP bits: 1 north, 2 south,
    // 4 west, 8 east, red set << 4); 0 when none.
    int (*roadArrows)(void* context, float x, float z, float ceiling) = nullptr;
};

// The queries, kept for the developer warps (which run from the key poll, not
// the solver). Set by the world view every frame it has a level.
void ViewModeSetQueries(const ViewQueries& queries);

class ViewCameraSolver {
public:
    // Places `camera` for the current mode. False when the mode is Classic or
    // the player is not usable, in which case the caller frames the game's own
    // camera as before.
    bool Update(const PlayerState& player, const ViewQueries& queries, float dt,
                gta2::Camera* camera);
    void Reset();
    const char* Status() const { return status_; }

    // Where the camera is, for the menu.
    float yawDegrees = 0.0f, pitchDegrees = 0.0f;
    float speed = 0.0f;   // the player's, blocks a second

private:
    void Solve(const PlayerState& player, const ViewQueries& queries, float dt,
               gta2::Camera* camera, float px, float py, float pz, float headingYaw,
               bool inVehicle);

    bool settled_ = false;
    float followYaw_ = 0.0f;      // the yaw the chase camera sits at
    float followYawVel_ = 0.0f;   // its angular velocity, radians a second (the spring)
    float fpYaw_ = 0.0f;          // first person: the eased, rate-capped view heading
    float fpYawVel_ = 0.0f;
    float floorY_ = 0.0f;         // eased floor height under the player
    bool floorSettled_ = false;
    float eyeX_ = 0.0f, eyeY_ = 0.0f, eyeZ_ = 0.0f;   // eased third-person eye
    float lastX_ = 0.0f, lastZ_ = 0.0f;
    // Motion, estimated from where the player was last frame: the game keeps a
    // velocity for cars but not one this renderer reads, and the difference of
    // positions is exact for a simulation that moves once a frame anyway.
    float velX_ = 0.0f, velZ_ = 0.0f;       // smoothed, blocks a second
    float speedFrac_ = 0.0f;                // speed over the reference speed, eased, 0..1
    float lastYaw_ = 0.0f;                  // the chase yaw last frame, for its rate
    float yawRate_ = 0.0f;                  // eased, radians a second
    float roll_ = 0.0f;                     // eased camera roll
    float shake_ = 0.0f;                    // impact energy, decaying
    double shakeClock_ = 0.0;
    float bobPhase_ = 0.0f;                 // walking cycle, turns
    float forwardAccel_ = 0.0f;             // eased, blocks a second squared
    const char* status_ = "classic";
    ViewMode lastMode_ = ViewMode::Classic;
};

// Pushes the motion blur choice to RTX Remix when it changes. Cheap to call
// every frame: it only crosses the bridge when the answer is different.
void ViewModePushRemixOptions(bool viewActive);

// The mouse look offsets the input poll accumulated, in radians, and when the
// mouse last moved (seconds, performance counter) so the camera can swing back.
struct ViewLook {
    float yaw = 0.0f;
    float pitch = 0.0f;
    double lastMoved = 0.0;
};
ViewLook& LookOffsets();

}  // namespace gta2dx9
