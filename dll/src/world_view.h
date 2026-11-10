// The world-space view drawn in place of GTA2's own renderer.
//
// Reads the game's live map and camera, builds true 3D geometry, and draws it
// through D3D9 fixed-function so RTX Remix can path trace it. The game's own
// draw stream is ignored: it is pre-transformed screen space, which Remix skips.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <string>
#include <vector>

#include "../../src/camera.h"
#include "../../src/renderer.h"
#include "game_access.h"
#include "ground.h"
#include "live_geometry.h"
#include "overlay.h"
#include "view_modes.h"

namespace gta2dx9 {

// Whether gta2.exe is patched so its own view rectangle is the shape of the
// frame we draw, which keeps new cars and pedestrians out of a wide frame's
// margins. Off puts every byte of the game back the way it shipped - the sites
// keep their original bytes, so this is reversible while the game is running.
constexpr bool kDefaultSpawnOffscreen = true;
void SetSpawnOffscreen(bool on);

// How much the view's following of the game's camera is smoothed, as a multiple:
// 0 is the game's camera exactly as it is, 1 the default, 2 twice as slow to follow
// a change. See WorldView::UpdateCamera.
constexpr float kDefaultCameraSmoothing = 1.0f;
void SetCameraSmoothing(float strength);
float CameraSmoothing();
bool SpawnOffscreen();
// Whether the patches are in force right now, for the menu to show.
bool SpawnOffscreenActive();

// The chase and first-person views, for the menu: the player as last found,
// what the camera solver is doing, and whether one of those views is up.
// See view_modes.h.
const PlayerState& ViewPlayer();
const char* ViewCameraStatus();
bool ViewCameraActive();
// What the picture presents (FIX-SMOOTH-SWITCH): the street views' content (figures,
// models, props, the street-only fill, the modern HUD, contact shadows) or the classic
// view's (the game's sprites, the plain HD tiles, the game's HUD). It follows the
// camera's progress through a move between the views, not the V key: the press only
// starts the camera, and the content changes over in the fastest part of the move.
// Equal to "a street view is the current view" whenever no move is in progress.
bool StreetPresentation();
// FIX-SEAT-ENTRY-2: while the camera moves from another view into the driver's seat, the seat's
// eye (the move's destination, world space); false otherwise. The car bodies make the seat view's
// parts (hood dash, cab interior, hands) ahead with it, unseen, so the first frame in the seat
// does not build them on the render thread (~200 ms on the 068 van's first entry).
bool SeatMoveEye(gta2::Vec3* seatEye);
// 0..1, how far the ground's material has gone over to the street set during a move
// (0 classic, 1 street); the tile set cross-fades on the same geometry by it.
float StreetPresentationMix();
// 0..1, the weight of the street-only shading extras that fade in after the content
// has changed over (contact shadows); 1 in a settled street view, 0 in classic.
float StreetExtrasWeight();
// A move between the views is in progress (the camera is neither the settled classic
// camera nor a settled street camera).
bool ViewCameraMoving();
void ViewCameraAngles(float* yawDegrees, float* pitchDegrees);
float ViewPlayerSpeed();

// Whether pedestrians leave blood pools, which GTA2 has but keeps behind a debug
// flag. See game::kDoBloodFlag. Off hands the flag back to whatever the game had.
constexpr bool kDefaultBlood = true;
void SetBlood(bool on);
bool Blood();

// Where the renderer presents. GTA2 loads a *video* device alongside the render
// device, and that is what owns the screen; these are the ways of getting out
// from under it. own_window in gta2dx9.ini selects one.
enum class PresentWindow {
    GameWindow = 0,  // share the game's, which deadlocks Remix's first Present
    Child = 1,       // a child of the game's window
    Topmost = 2,     // a separate top-level window in the topmost band
};

class WorldView {
public:
    // pitchDegrees: -90 looks straight down, matching GTA2's own view.
    // useGameTiles: take tile artwork from the running game rather than from our
    // own parse of the style file.
    // ownWindow: present into a window of our own rather than the game's, which
    // DirectDraw has already claimed.
    void Configure(float pitchDegrees, float fovDegrees, bool useGameTiles, PresentWindow present);

    // The size to actually render and present at, which is deliberately not the
    // game's. GTA2's own resolution is whatever its options screen last wrote -
    // 640x480 out of the box, and its manager will not offer much better because
    // the list comes from DirectDraw mode enumeration. That number has no
    // business deciding how big the path traced image is: it is the resolution
    // the HUD is laid out in, and the overlay already scales that to whatever it
    // is drawn into.
    //
    // 0 x 0 means the desktop resolution, which is what you want essentially
    // always. Anything else is taken literally.
    void SetRenderSize(int width, int height);

    bool Initialize(HWND window, int width, int height, std::string* error);
    void Shutdown();
    bool Ready() const { return ready_; }

    // GTA2 hands the renderer the visible tile rectangle every frame, which is
    // exactly its zoom and centre - no need to reverse a projection.
    void SetVisibleTileBounds(float minX, float minY, float maxX, float maxY);

    // Called when the game starts a level, so the next frame rebuilds.
    void InvalidateWorld() { loadedMapObject_ = nullptr; }

    // The game cleared its screen. gta2.exe!0x004619BC does this only when one
    // of its repaint flags is set, so it is the one statement that the 2D layer
    // may be thrown away.
    void NoteScreenClear() { renderer_.NoteScreenClear(); }

    void BeginFrame() {
        // The first scene after the intro starts on a clean 2D layer: the menu
        // only paints what it changes, and would otherwise leave the movie's last
        // frame showing through wherever it does not paint.
        if (movieShown_) {
            movieShown_ = false;
            overlay_.EndMovie();
            NoteScreenClear();
        }
        MatchGameViewToFrame();
        ApplyBlood();
        overlay_.BeginFrame();
        live_.BeginFrame();
    }
    void RenderFrame();

    // FIX-STABILITY-1 (owner-5090-minimize-fatal). The game window's focus and minimise state,
    // fed from its window procedure (dllmain.cpp ClosingWndProc). Parked = minimised: RenderFrame
    // draws and presents nothing (no scene, no Present, no device Reset) until the window is
    // restored; the device and both windows stay as they are. Inactive = it lost the focus: our
    // topmost present window leaves the topmost band so whatever took the focus is not covered by a
    // frozen frame, and goes back on top when the game has the focus again. simulated: the devtools
    // test sent the messages, so the window is not really iconic and IsIconic must not end the park.
    void SetGameParked(bool parked, const char* why, bool simulated = false);
    void SetGameActive(bool active, const char* why);
    bool GameParked() const { return parked_; }
    bool GameActive() const { return active_; }
    HWND PresentHwnd() const { return window_; }
    HWND GameHwnd() const { return gameWindow_; }
    PresentWindow PresentMode() const { return present_; }   // FIX-STABILITY-2: own_window as configured
    int FrameCount() const { return frameCount_; }
    bool WorldUploaded() const { return worldUploaded_; }
    // A C++ exception escaped a frame: close the scene the device may still be in.
    void AbortFrame();

    // One frame of the intro movie, which the game plays without a scene of its
    // own: drawn over the screen and presented here. See intro_movie.cpp.
    void ShowMovieFrame(const void* pixels, int width, int height, int pitch) {
        overlay_.BeginFrame();
        overlay_.MovieFrame(pixels, width, height, pitch);
        movieShown_ = true;
        RenderFrame();
    }

    // The HUD and menus arrive as screen-space draws and are replayed on top of
    // the world rather than dropped.
    Overlay& GetOverlay() { return overlay_; }

    // Sprites and the block shapes the static mesh does not build, placed as
    // real 3D geometry from the world coordinates the game itself computed.
    LiveGeometry& Live() { return live_; }


    // Compares a tile the game just drew against what our own map walk says
    // belongs at that cell, to locate a placement mismatch.
    void CheckDrawnTile(const void* textureRecord);

    // Logs the world-space corners the game itself computed for a face of an
    // awkward block shape, so the mesh builder's idea of that shape can be
    // checked against the game rather than against a reading of its code.
    void CheckDrawnShape(int corners);

private:
    bool EnsureDevice();
    bool EnsureWorldLoaded();
    void RefreshAnimatedTiles();
    void UpdateCamera();
    void DumpCameraStruct() const;
    float GroundHeightAt(float tileX, float tileY) const;

    // What the chase camera asks of the map: the floor under a point and
    // whether a point is inside a solid block. Renderer coordinates.
    bool FloorAt(float x, float z, float ceiling, float* y) const;
    bool Blocked(float x, float y, float z) const;
    // Whether a point is inside a block with a solid (non-flat) side face: a wall. A
    // lid-only block (a road, a deck over a walkable passage) is not a wall.
    bool Walled(float x, float y, float z) const;
    // The distance from a point to the nearest flat panel (fence, railing,
    // grille) of the block it is in; false when the block has none.
    bool PanelDistance(float x, float y, float z, float* distance) const;
    // FIX-FIGURE-2 (fp-eye-inside-railing): a point moved to `clear` from every flat
    // panel of its block and the eight round it (a railing on the tile edge belongs to
    // either side's block, and its bars stand a few pixels off that plane); false when
    // none is that close.
    bool PanelPush(float x, float y, float z, float clear, float* outX, float* outZ) const;
    static bool PanelPushThunk(void* context, float x, float y, float z, float clear, float* outX, float* outZ) {
        return static_cast<const WorldView*>(context)->PanelPush(x, y, z, clear, outX, outZ);
    }
    static bool FloorThunk(void* context, float x, float z, float ceiling, float* y) {
        return static_cast<const WorldView*>(context)->FloorAt(x, z, ceiling, y);
    }
    static bool BlockedThunk(void* context, float x, float y, float z) {
        return static_cast<const WorldView*>(context)->Blocked(x, y, z);
    }
    static bool WalledThunk(void* context, float x, float y, float z) {
        return static_cast<const WorldView*>(context)->Walled(x, y, z);
    }
    static bool PanelThunk(void* context, float x, float y, float z, float* distance) {
        return static_cast<const WorldView*>(context)->PanelDistance(x, y, z, distance);
    }
    // The highest surface at or below `ceiling` in a column with its ground type.
    bool GroundAt(float x, float z, float ceiling, float* y, int* type) const;
    // The road arrows of the surface under a point (the GMP block's arrow bits:
    // 1 north, 2 south, 4 west, 8 east, the red set shifted up four); 0 when none.
    int RoadArrowsAt(float x, float z, float ceiling) const;
    static int ArrowsThunk(void* context, float x, float z, float ceiling) {
        return static_cast<const WorldView*>(context)->RoadArrowsAt(x, z, ceiling);
    }
    static bool GroundThunk(void* context, float x, float z, float ceiling, float* y, int* type) {
        return static_cast<const WorldView*>(context)->GroundAt(x, z, ceiling, y, type);
    }
    // A point inside a street prop's footprint moved just outside it.
    bool PropPush(float x, float y, float z, float* outX, float* outZ) const;
    static bool PropThunk(void* context, float x, float y, float z, float* outX, float* outZ) {
        return static_cast<const WorldView*>(context)->PropPush(x, y, z, outX, outZ);
    }

    // Widen GTA2's own view rectangle to the frame's aspect. See the .cpp.
    void MatchGameViewToFrame();
    // Keep GTA2's blood flag set while the blood setting is on.
    void ApplyBlood();

    gta2::Renderer renderer_;
    Overlay overlay_;
    bool movieShown_ = false;
    LiveGeometry live_;
    gta2::Camera camera_;
    gta2::Map map_;
    // The floor the sprite pass stands sprites on, rebuilt with the world. It
    // reads map_ directly, so the two can never describe different ground.
    GroundSampler ground_;
    const void* loadedMapObject_ = nullptr;
    // Whether a level's geometry is currently uploaded. Distinct from
    // loadedMapObject_, which gbh_EndLevel clears to force a rebuild while the
    // old mesh is still sitting in the vertex buffer.
    bool worldUploaded_ = false;
    std::string dataDir_;

    float minX_ = 0.0f, minY_ = 0.0f, maxX_ = 0.0f, maxY_ = 0.0f;
    bool haveBounds_ = false;
    bool ready_ = false;
    int frameCount_ = 0;

    // Where the device is to be created, kept because creating it can take more
    // than one attempt; roughly ten seconds of frames before giving up.
    static constexpr int kMaxDeviceAttempts = 600;
    HWND window_ = nullptr;      // what we present into
    HWND gameWindow_ = nullptr;  // what the game owns, and its video device with it
    PresentWindow present_ = PresentWindow::Child;
    volatile bool parked_ = false;      // FIX-STABILITY-1: see SetGameParked
    bool parkSimulated_ = false;
    volatile bool active_ = true;
    int parkedFrames_ = 0;
    DWORD parkedSince_ = 0;
    int width_ = 0;
    int height_ = 0;
    // 0 means "the desktop", resolved in Initialize.
    int requestedWidth_ = 0;
    int requestedHeight_ = 0;
    int deviceAttempts_ = 0;

    float smoothedHeight_ = 0.0f;
    bool heightSettled_ = false;
    // The view's own camera position, which follows the game's. See UpdateCamera.
    bool camSettled_ = false;
    float camX_ = 0.0f, camY_ = 0.0f;        // where the view is
    float camVX_ = 0.0f, camVY_ = 0.0f;      // its smoothed velocity, tiles a second
    float camRawX_ = 0.0f, camRawY_ = 0.0f;  // where the game's camera was last frame
    double camTime_ = 0.0;
    float camZoom_ = 0.0f;                   // the smoothed visible height in tiles
    float visibleTiles_ = 0.0f;

    // The chase and first-person views. See view_modes.h. The classic pitch and
    // field of view are kept so the top-down view comes back exactly as
    // configured when one of the others is switched off.
    ViewCameraSolver viewSolver_;
    bool viewActive_ = false;
    // The move between views. See ApplyTransition.
    struct CameraPose {
        gta2::Vec3 position;
        float yaw = 0.0f, pitch = 0.0f, roll = 0.0f, fov = 0.0f;
    };
    CameraPose lastPose_;          // what was shown last frame, blended
    bool lastPoseValid_ = false;
    CameraPose transitionFrom_;    // where the camera was when the view changed
    float transitionAimYaw_ = 0.0f;   // FIX-CAMERA-2: the move's aim heading, unwrapped frame to frame
    float transitionT_ = 1.0f;     // 0..1, 1 when no move is in progress
    ViewMode lastViewMode_ = ViewMode::Classic;
    bool transitionToClassic_ = false;
    bool transitionFromClassic_ = false;
    bool transitionFromFirst_ = false;   // FIX-CAMERA-6: the move started in first person (pfeel4's aim)
    bool transitionPlayerKnown_ = false, locatedValid_ = false;   // FIX-CAMERA-6: him at the press / this frame
    float transitionPlayerX0_ = 0.0f, transitionPlayerZ0_ = 0.0f, locatedX_ = 0.0f, locatedZ_ = 0.0f;
    // How much of the street views' sky, fog and sun is shown: 0 in the classic
    // view, 1 in the others, eased through a move between them. See sky.h.
    float skyBlend_ = 0.0f;
    // The classic-to-street dissolve (BEV-PURITY): the frame on which the renderer last
    // kept a settled classic frame, and while a move out of the classic view runs, the
    // move's progress on its first frame (-1 until then).
    int keptClassicAt_ = -100;
    bool dissolveActive_ = false;
    float dissolveT0_ = -1.0f;
    int viewLostFrames_ = 0;       // frames a ground view has gone without the player
    // FIX-SMOOTH-SWITCH: the presentation last applied (see StreetPresentation), so the
    // car body numbers swap once per change.
    bool presentedStreet_ = false;
    float transitionLift_ = 0.0f;  // the eased lift of the move's path out of buildings (blocks)
    float moveCatch_ = 0.0f;       // FIX-CAMERA-7: seconds left to catch up the turn a move left (MoveTurnCap)
    // FIX-CAMERA-8 (pfl11): the street view fell back to the classic camera because the player was lost
    // (a death or an arrest, the game between two bodies), not because of the V key; found again, the
    // view cuts to its solved pose instead of the classic -> street descent.
    bool lostFallback_ = false;
    bool levelStartCut_ = false;   // FIX-CAMERA-18 (qaexp32): a level was loaded; the first street view cuts in
    int levelStartFrame_ = 0;
    void MoveTurnCap(CameraPose* pose, float dt, ViewMode mode);
    // FIX-CAMERA-5 (feel23): the move rides its destination. The destination's pose when the move
    // began; the start pose is carried along with it (moved, and between street views turned, by
    // the destination's motion since), so a V in a moving car is a move inside the car's frame.
    gta2::Vec3 transitionTarget0_{};
    float transitionTargetYaw0_ = 0.0f;
    float transitionSeconds_ = 1.4f;   // this move's length (shorter between the two street views)
    void ApplyTransition(float dt, ViewMode mode);
    void ApplyPresentation(ViewMode mode);
    void DrawSkyAndShading();
    // FIX-PERF-VSWITCH: one street frame drawn where nothing shows, in the classic view.
    void GhostStreetFrame();
    int ghostAt_ = -1;   // the frame it ran (-1 not yet; again with each level)
    int ghostWait_ = 0;  // classic frames of this level so far
    double viewTime_ = 0.0;
    float classicPitch_ = -1.5708f;
    float classicFov_ = 0.6981f;
    bool useGameTiles_ = true;
    int tileChecks_ = 0;
    int shapeChecks_ = 0;

    // What the artwork for each tile was last taken from, so an animated tile
    // can be spotted and re-uploaded.
    struct TileSource {
        const void* record = nullptr;
        uint16_t revision = 0;
    };
    std::vector<TileSource> tileSources_;
};

}  // namespace gta2dx9
