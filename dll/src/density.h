// Traffic and pedestrian density in the street views (QB-9, QB-42). See density.cpp.
#pragma once

namespace gta2dx9 {

// How many ambient traffic cars gta2.exe keeps alive at once while a chase or
// first-person view is up. The game's own number is 16, sized for the top-down
// window; the street views widen that window 2.6x (gameViewScale) and the same 16
// cars spread over it leave the boulevards empty. 16 or less leaves the game's
// code as it shipped. At most 100 (the car pool holds 306, the ped pool 200 and
// every traffic car carries a driver).
// FIX-TRAFFIC-1 (10 Nov): 24, not 36. At 36 the extra cars only queued (bil: 3.1 moving
// of 11.1 near the player against 4.3 of 8.6 at 24; free stops 64 % of the cars against 36 %
// at the stock 16), docs/vehicle-feel.md FIX-TRAFFIC-1.
constexpr int kDefaultTrafficCap = 24;
// Multiplier on the per-zone pedestrian density the game spawns against: 1, 2, 4
// or 8 (GTA2 allows zone.ped_density / 25 people in its window: 8 in Downtown).
constexpr int kDefaultPedDensityScale = 4;
// gta2.exe's cap on ambient ("dummy") pedestrians, 50 as shipped.
constexpr int kDefaultPedCap = 80;

// Car density (0..1000) given, in the street views, to the zone the player stands
// in when the game has it at 0 (Downtown's church plaza at the start). GTA2 takes
// traffic density from the player's zone, not the road's, so standing there
// stopped all traffic on the roads in view. 0 leaves zones alone.
constexpr int kDefaultZoneCarDensity = 400;
void SetZoneCarDensity(int density);
// FIX-PERF-6: watch the game's object-grid node pools (0x5E6684/0x5E6688) and stand the raised budgets
// down while they run low; [density] grid_headroom (2; 1 = FIX-PERF-6's static thresholds, 0 off),
// GTA2DX9_GRID_HEADROOM. FIX-PERF-8 (2): also on the pool's slope and at wantedHold+ stars
// ([density] wanted_hold, GTA2DX9_WANTED_HOLD; 0 off), and the game's window back to its own size
// while the pool is about to run dry.
// At wantedHold+ stars the game's window is also brought down to wantedWindowPercent of the street views'
// scale's base (100 = the game's own top-down window; [density] wanted_window_percent).
void SetGridHeadroom(int mode, int wantedHold, int wantedWindowPercent);
// The street views' scale of the game's window (gameViewScale) as the grid guard lets it stand now:
// the scale itself, or less (down to 1, the game's own) while the guard sheds (FIX-PERF-8).
float DensityGameViewScale(float scale);
// True while that scale is held at 1 (the game's own size): the window then takes the game's own shape too.
bool DensityClassicWindow();

// 0 for any of these turns that part off (the game's own value is kept).
void SetDensity(int trafficCap, int pedDensityScale, int pedCap);

// Once a frame from WorldView::MatchGameViewToFrame. groundView is true while a
// chase or first-person view is up; in the classic view every byte goes back to
// what gta2.exe shipped. playerX/Y in tiles, for the census log line.
void DensityUpdate(bool groundView, bool playerValid, float playerX, float playerY);

}  // namespace gta2dx9
