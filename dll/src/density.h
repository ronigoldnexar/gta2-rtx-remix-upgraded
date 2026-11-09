// Traffic and pedestrian density in the street views (QB-9, QB-42). See density.cpp.
#pragma once

namespace gta2dx9 {

// How many ambient traffic cars gta2.exe keeps alive at once while a chase or
// first-person view is up. The game's own number is 16, sized for the top-down
// window; the street views widen that window 2.6x (gameViewScale) and the same 16
// cars spread over it leave the boulevards empty. 16 or less leaves the game's
// code as it shipped. At most 100 (the car pool holds 306, the ped pool 200 and
// every traffic car carries a driver).
constexpr int kDefaultTrafficCap = 36;
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

// 0 for any of these turns that part off (the game's own value is kept).
void SetDensity(int trafficCap, int pedDensityScale, int pedCap);

// Once a frame from WorldView::MatchGameViewToFrame. groundView is true while a
// chase or first-person view is up; in the classic view every byte goes back to
// what gta2.exe shipped. playerX/Y in tiles, for the census log line.
void DensityUpdate(bool groundView, bool playerValid, float playerX, float playerY);

}  // namespace gta2dx9
