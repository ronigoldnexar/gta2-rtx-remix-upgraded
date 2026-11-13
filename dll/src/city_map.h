// CITYMAP-1: the full city map with GPS navigation. See city_map.cpp and docs/citymap.md.
//
// M (the [citymap] key) opens a full-screen map of the level drawn from its own .gmp: roads,
// blocks, water, district names and landmarks, the player's position and heading. A click (or
// Enter on the keyboard cursor) sets a waypoint, snapped to the nearest drivable road; the
// shortest drivable route over the map's own lane arrows (one-way lanes kept, bridges and
// tunnels on their own levels) is drawn on the map, on the street views' mini-map, as faint
// chevrons on the road ahead in the street views, and, in the classic view, on a small GPS disc
// shown only while a waypoint is set. The game is not paused (GTA2 has no pause the DLL could
// ask for): while the map is open the game's control keys are withheld through the DirectInput
// filter the camera-relative controls already use. Game logic is untouched.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>
#include <string>
#include <vector>

struct IDirect3DDevice9;
namespace gta2 { class Map; }

namespace gta2dx9 {

// One block of the map in metres, for every distance the player reads (the Remix scene's scale:
// sceneScale 0.0025, a block about 4 m). [citymap] metres_per_block overrides it for the read-outs.
constexpr float kCityMapMetresPerBlock = 4.0f;

// At level load (world_view.cpp, after the map is parsed): the map, its ZONE chunk and its file.
void CityMapSetLevel(const gta2::Map& map, const std::vector<uint8_t>& zones, const std::string& mapPath);

// Once a frame before anything of ours is drawn: the keys, the mouse, the route's progress.
void CityMapUpdate(IDirect3DDevice9* device, int width, int height, HWND presentWindow, bool worldLoaded);
// The street views' ground chevrons (before the modern HUD, over the world).
void CityMapDrawWorld(IDirect3DDevice9* device, int width, int height);
// The full map when it is open (last, over everything but the F4 menu).
void CityMapDrawOverlay(IDirect3DDevice9* device, int width, int height);

// The window procedures hand the wheel over (WM_MOUSEWHEEL's delta).
void CityMapNoteWheel(int delta);
// ... and the mouse buttons (0 left, 1 right): a click can be shorter than a frame.
void CityMapNoteButton(int button, bool down);

bool CityMapOpen();

// What the mini-maps draw (hud3d.cpp): the route from the player on (map cells, filleted, the
// road's middle), the waypoint, the next turn and the distance left. False: no route.
struct CityMapGuide {
    std::vector<float> lineX, lineY;
    float wayX = 0, wayY = 0;
    float turnBlocks = -1.0f;   // < 0: no turn before the waypoint
    int turnDir = 0;            // -1 left, 1 right
    float remainingBlocks = 0;
    bool arrived = false;
    bool offNetwork = false;    // he is somewhere the road net does not reach (a dashed hop to it)
};
bool CityMapGuideNow(CityMapGuide* out);
// The classic view's GPS disc is wanted this frame (a waypoint is set, the map is closed).
bool CityMapClassicDisc();
// A distance in the read-outs' words ("320 M", "1.24 KM").
std::string CityMapDistanceText(float blocks);

}  // namespace gta2dx9
