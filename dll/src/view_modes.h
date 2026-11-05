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
    // ViewMode, as an int so the settings table can carry it.
    int mode = 0;
    // The virtual-key code that cycles the modes. 'V' is free in GTA2's own
    // default controls.
    int toggleKey = 'V';

    bool mouseLook = true;
    float mouseSensitivity = 1.0f;   // 1 is 0.12 degrees per count
    bool invertY = false;

    // Third person. Distances in blocks: a GTA2 block is about 2 m, a car about
    // one block long.
    float tpDistance = 3.4f;        // behind the target
    float tpHeight = 1.25f;         // above it
    float tpLookAhead = 1.2f;       // the point looked at, blocks ahead of the target...
    float tpLookHeight = 0.35f;     // ...and above it
    float tpFootScale = 0.65f;      // distance and height are scaled by this on foot
    float tpFov = 50.0f;            // vertical, degrees
    float tpFollow = 0.25f;         // seconds the camera takes to swing round behind a turn
    float tpReturnDelay = 1.5f;     // seconds after the last mouse input before the orbit returns
    bool tpCollide = true;          // pulled in front of walls rather than through them

    // First person.
    float fpEyeFoot = 0.78f;        // eye height above the floor on foot (1.55 m)
    float fpEyeCar = 0.52f;         // ... at the wheel (just over 1 m)
    float fpForwardFoot = 0.12f;    // the eye sits this far ahead of the object's centre
    float fpForwardCar = 0.30f;
    float fpFov = 68.0f;
    bool fpHideOwnBody = true;      // the player's own sprite, and his car, are not drawn
    float fpReturnDelay = 2.0f;     // free look swings back to straight ahead after this

    // Both.
    // Pedestrians are drawn from above and lie flat on the road, which from a low
    // camera is a line. With this on, each one on his feet is stood up as a
    // billboard facing the camera: a paper figure, but a visible one.
    bool uprightPeds = true;
    // How much more of the world gta2.exe is told it shows. The game creates,
    // draws and removes cars and pedestrians inside the window its own camera
    // frames; a chase camera sees well beyond that window, so it is widened by
    // this factor while a chase or first-person view is up. 1 leaves it alone.
    float gameViewScale = 1.8f;
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
};

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

private:
    void Solve(const PlayerState& player, const ViewQueries& queries, float dt,
               gta2::Camera* camera, float px, float py, float pz, float headingYaw,
               bool inVehicle);

    bool settled_ = false;
    float followYaw_ = 0.0f;      // the yaw the chase camera sits at
    float floorY_ = 0.0f;         // eased floor height under the player
    bool floorSettled_ = false;
    float eyeX_ = 0.0f, eyeY_ = 0.0f, eyeZ_ = 0.0f;   // eased third-person eye
    float lastX_ = 0.0f, lastZ_ = 0.0f;
    const char* status_ = "classic";
    ViewMode lastMode_ = ViewMode::Classic;
};

// The mouse look offsets the input poll accumulated, in radians, and when the
// mouse last moved (seconds, performance counter) so the camera can swing back.
struct ViewLook {
    float yaw = 0.0f;
    float pitch = 0.0f;
    double lastMoved = 0.0;
};
ViewLook& LookOffsets();

}  // namespace gta2dx9
