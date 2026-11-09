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
    float mouseSensitivity = 0.5f;   // 1 is a quarter turn (90 degrees) across the window's width
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
    // Every rate below is scaled by turnSpeed, a percentage (100 = as set;
    // 50 halves all turning: camera, keyboard look, mouse, the drawn figure).
    float turnSpeed = 100.0f;
    float turnRateFoot = 120.0f;    // the orbit camera on foot (mouse orbit and the re-centre)
    float turnRateCar = 90.0f;      // the chase camera at the wheel
    float fpCarRate = 240.0f;       // first person at the wheel: fixed to the car, this is only a safety cap
    float fpFollowRate = 150.0f;    // first person on foot when the view follows the heading
    // First person: the view heading eases onto the game's over this long
    // (seconds), on top of the rate cap.
    float fpSmooth = 0.12f;
    // Third person on foot: the player's drawn figure turns no faster than
    // this (degrees a second) and eases over pedDrawnEase seconds, so the model
    // never snaps although the game's heading does; the game logic is untouched.
    float pedDrawnTurnRate = 240.0f;
    float pedDrawnEase = 0.12f;

    // Camera-relative controls on foot, as a modern game plays. The arrow keys
    // mean "walk that way as the camera sees it": Up toward where the camera
    // looks, Left and Right to its sides, Down back toward it. The pedestrian
    // is steered onto that heading through the game's own turn keys, which the
    // renderer presses and releases for him (a keyboard hook takes the physical
    // arrows, keybd_event gives the game ours), so the game's movement, speeds
    // and collisions stay exactly its own. In first person Left and Right turn
    // the view at fpTurnKeyRate and the pedestrian follows the view. In a car
    // the game's own driving keys are untouched.
    bool navMap = true;
    float navDeadband = 8.0f;       // degrees of heading error before a turn key is pressed
    float navLatency = 0.10f;       // seconds from our key press to the game's heading moving; the
                                    // controller releases that far ahead of the target
    int navTurnSign = 1;            // -1 if the turn keys come out mirrored
    // First person Left/Right: the view turns at fpTurnKeyStart degrees a
    // second the moment a key goes down and ramps to fpTurnKeyRate over
    // fpTurnKeyRamp seconds; on release the turn decays over fpTurnKeyDecay.
    float fpTurnKeyRate = 70.0f;
    float fpTurnKeyStart = 25.0f;
    float fpTurnKeyRamp = 0.8f;
    float fpTurnKeyDecay = 0.15f;
    // The third-person camera on foot is an orbit camera: it does not follow the
    // player's heading, he turns inside the frame. By default it holds its yaw
    // while he walks (he walks toward, away or across the frame) and only an
    // explicit look input orbits it; a slow re-centre behind him (tpRecentreTau
    // seconds, no faster than tpRecentreRate) starts only once he has walked
    // straight away from the camera for tpRecentreDelay seconds. tpOrbitFollow
    // instead drifts it round behind whichever way he walks, over tpOrbitTau.
    // In a car the chase camera's yaw is damped over tpChaseTau.
    bool tpOrbitFollow = false;
    float tpOrbitTau = 1.5f;
    // Soft follow on foot (the GTA V camera; on with tpOrbitFollow off and
    // tpFollowTauWalk > 0): while he walks, the yaw eases round behind the way he
    // is going on a critically damped spring with this time constant, seconds -
    // tpFollowTauWalk at a walk, tpFollowTauRun at full running pace, in between
    // by speed - never faster than turnRateFoot. A turn (a key pressed, or he
    // sets off) is followed only after tpFollowDelay seconds; standing still with
    // no key held the camera holds its yaw. tpFollowTauWalk 0 restores the held
    // orbit with its slow re-centre below. [camera] follow_tau_walk,
    // follow_tau_run, follow_delay in gta2dx9.ini.
    float tpFollowTauWalk = 1.5f;
    float tpFollowTauRun = 1.0f;
    float tpFollowDelay = 0.4f;
    float tpRecentreDelay = 2.0f;
    float tpRecentreTau = 4.0f;
    float tpRecentreRate = 30.0f;
    float tpChaseTau = 0.8f;

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
    // FIX-VEHICLES, at the wheel: the camera's kick on an impact the car's body
    // model measured (the speed lost, vehicle_fx), and the share of the drawn body's
    // pitch, roll and heave the first-person eye rides. [camera] car_impact_shake,
    // first_body_ride (percent).
    float carImpactShake = 1.0f;
    float fpBodyRide = 1.0f;
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
    // [camera] switch_dissolve_percent: a fallback only, 0 (off) is the intended value.
    // The first part of a move out of the classic view (percent of the move) over which
    // the last classic frame would dissolve into the street view (BEV-PURITY). The move
    // needs no image effect since the presentation follows the camera (FIX-SMOOTH-SWITCH).
    float switchDissolve = 0.0f;

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

// The global turning scale (turnSpeed / 100).
float ViewTurnSpeedScale();
// Third person on foot: true when the player's drawn figure should turn under
// the smoothed rule, with the cap (radians a second) and the ease (seconds).
bool ViewPlayerDrawnTurn(float* capRadPerSec, float* easeSec);
// The sprite pass reports the player's drawn heading each frame (radians, the
// rate in radians a second) for the camera log.
void ViewLogPlayerDrawnYaw(float heading, float rate, float dt);

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
// FIX-COLLISION: move the player on foot to (x, y) in the game's frame (tiles east, south),
// keeping his level; false when the ped cannot be reached.
bool WritePlayerGroundPosition(const void* ped, float x, float y);
// The ped's state word (8 knocked down, 9 dead, 3/4 at a car door), -1 when unreadable.
int ReadPedState(const void* ped);
// The ped LocatePlayer last found for him (kept while he is at the wheel); null in the menus.
const void* LocatedPlayerPed();

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
    // Whether a point is inside a block with a solid side face (a wall; lids alone do not count).
    bool (*walled)(void* context, float x, float y, float z) = nullptr;
    // The distance from a point to the nearest flat panel (fence, railing) of
    // the block it is in; false when there is none.
    bool (*panelDistance)(void* context, float x, float y, float z, float* distance) = nullptr;
    // A point moved `clear` away from every flat panel of its block and the blocks
    // round it (x/z only); false when none is that close.
    bool (*panelPush)(void* context, float x, float y, float z, float clear, float* outX, float* outZ) = nullptr;
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
    // The player lost for a moment (killed, between two bodies): the camera
    // rises and draws back over where he was last.
    void SolveLost(const ViewQueries& queries, float dt, gta2::Camera* camera);
    float lostTime_ = 0.0f;

    bool settled_ = false;
    bool finalYawKnown_ = false;  // third person: the orientation actually set last frame
    float finalYaw_ = 0.0f;
    float followYaw_ = 0.0f;      // the yaw the chase camera sits at
    float followYawVel_ = 0.0f;   // its angular velocity, radians a second (the spring)
    float awayTime_ = 0.0f;       // third person on foot: seconds walked straight away from the camera
    // Soft follow on foot: seconds since this turn or walk began (the follow waits
    // tpFollowDelay), seconds since the last key or step (it finishes a turn begun
    // by a key, then holds), and whether it is under way.
    float engageTime_ = 0.0f;
    float idleTime_ = 0.0f;
    float keyAge_ = 10.0f;        // seconds since an arrow was last held on foot
    bool footFollowing_ = false;
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
    float carPitch_ = 0.0f, carRoll_ = 0.0f, carHeave_ = 0.0f;   // the drawn body of his car (vehicle_fx)
    double shakeClock_ = 0.0;
    float bobPhase_ = 0.0f;                 // walking cycle, turns
    // pm-fp-respawn-eye-pressed-into-facade: after a respawn or level cut the first-person
    // view turns from a wall within half a block toward the most open side.
    float fpRespawnPending_ = 0.0f;         // seconds left to look for the first on-foot frame
    bool resetByModeSwitch_ = false;        // the last Reset was a V switch, not a respawn or a warp
    float fpRespawnLeft_ = 0.0f;            // turn still to sweep (nav: on the view yaw)
    float fpRespawnRate_ = 0.0f;            // radians a second of that sweep
    float fpRespawnOffset_ = 0.0f;          // without nav: added to the heading the view follows
    float fpRespawnHeading_ = 0.0f;         // his heading when it was chosen (a turn of his releases it)
    float forwardAccel_ = 0.0f;             // eased, blocks a second squared
    // The chase framing of a long or tall vehicle: how much longer and taller its
    // body is than a sedan's, eased so the framing never pops when it becomes known.
    float extraLength_ = 0.0f, extraHeight_ = 0.0f, bodyHeight_ = 0.0f;
    bool framingKnown_ = false;
    float liftAngle_ = 0.0f;   // the chase camera swung up over a wall behind it, radians, eased
    float swingAngle_ = 0.0f;  // on foot: the boom swung round (yaw) what stands behind him, radians, eased
    // FIX-CAMERA (chase-cam-foot-snap-cuts, pt-chase-camera-pumps-against-wall): the
    // third-person boom as a state. The collision solve says how long the boom may be;
    // the shown camera sits on that boom's direction at boom_, which shortens at a
    // capped rate and lengthens only after the line has been clear for a moment, so a
    // ray that flickers blocked/clear never cuts or pumps the picture.
    float boom_ = 0.0f;
    float boomClear_ = 0.0f;          // seconds since the solve last pulled the boom in
    bool boomKnown_ = false;
    float bodyLift_ = 0.0f;           // FIX-CAMERA-3: the shown eye's rise over his head when the walls pull the boom into him
    float carLift_ = 0.0f;            // FIX-CAMERA-2: the shown eye's rise over a car or wreck beside it
    bool boomInVehicle_ = false;      // the boom was last solved at the wheel (a change restarts it)
    float armDirX_ = 0.0f, armDirY_ = 0.0f, armDirZ_ = -1.0f;
    float rescueX_ = 0.0f, rescueY_ = 0.0f, rescueZ_ = 0.0f;   // the pivot rescue's offset, eased for the shown camera
    bool snapEye_ = true;             // after a reset: the eye straight onto the solved rig
    // A blend after a discontinuity that is not a cut (in or out of a car, thrown
    // by a blast, down and up again): 1 just after it, 0 once settled. The eye
    // then eases more slowly and may lag further, so the move is a glide.
    float blend_ = 0.0f;
    bool lastInVehicle_ = false;
    // The player down (knocked over, dead, arrested: ped state 8/9) for this long,
    // and the death camera's share (eased 0..1): pulled back and up over him.
    float downTime_ = 0.0f;
    float deathMix_ = 0.0f;
    bool lastDeathCam_ = false;
    float lastPitch_ = 0.0f;
    // The car he last drove, and its body's half length, half width and height (from
    // CarBodiesExtent while at the wheel): on foot beside it the first-person eye is
    // kept clear of it (QA3: the Truck Cab's exhaust stack drew a dark bar a hand
    // from the eye after leaving it).
    const void* exitCar_ = nullptr;
    float exitCarHalfLength_ = 0.0f, exitCarHalfWidth_ = 0.0f, exitCarHeight_ = 0.0f;
    // Third person on foot: frames solved and frames with his head inside the
    // picture and not behind a wall, for the log (view: framing).
    int framingFrames_ = 0, framingHeadIn_ = 0, framingHeadSeen_ = 0, framingWhole_ = 0;   // whole: feet and head top inside 10..90 %
    bool lastPitchKnown_ = false;
    // First person: the eye's own glide over a discontinuity (offset added to the
    // seat or head position, decaying), and the raw and shown eyes last frame.
    float fpOffX_ = 0.0f, fpOffY_ = 0.0f, fpOffZ_ = 0.0f;
    float fpRawX_ = 0.0f, fpRawY_ = 0.0f, fpRawZ_ = 0.0f;
    float shownX_ = 0.0f, shownY_ = 0.0f, shownZ_ = 0.0f;
    bool fpEyeKnown_ = false;
    bool lastFpInVehicle_ = false;
    const char* status_ = "classic";
    ViewMode lastMode_ = ViewMode::Classic;
};

// QB-6: aiming in the street views. Updated once a frame by the camera solver from the
// player's ped: armed (on foot, a gun in his hands, standing), his shots (his weapon's
// ammunition dropped or its reload timer restarted: the game's own word that a shot left
// the gun), and how far the third-person camera has moved to the aim framing (0 the
// normal chase, 1 over the shoulder, closer and lower, behind his heading).
struct AimState {
    bool armed = false;
    int weapon = 0;            // the renderer's PedWeapon (live_geometry.cpp)
    uint32_t shots = 0;        // shots seen since the level came up
    double lastShot = 0.0;     // seconds (performance counter) of the last one; 0 none
    float aimMix = 0.0f;       // the camera's blend to the aim framing
    float headingYaw = 0.0f;   // his facing, renderer yaw (0 north, sin/cos)
    float x = 0.0f, y = 0.0f, z = 0.0f;   // where he stands, renderer frame (y the eased floor)
    bool valid = false;
};
const AimState& ViewAim();
// True when the straight line between two points (renderer frame) passes through a solid
// block of the map, by the camera's own world queries; false when they are unknown.
bool ViewLineBlocked(float x0, float y0, float z0, float x1, float y1, float z1);
// True when the straight line between two points (renderer frame) passes through a block
// with a solid side face (a wall); lids alone (roads, decks over a passage) do not count.
bool ViewLineWalled(float x0, float y0, float z0, float x1, float y1, float z1);
// Whether one point is inside a block with a solid side face (ViewQueries.walled).
bool ViewPointWalled(float x, float y, float z);

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
