// The modern HUD of the street views (third and first person). See hud3d.cpp and docs/hud.md.
//
// In the classic view nothing changes: the game's own HUD is drawn as it always was. In the
// street views, with [hud] modern=1 (the default), the parts of the game's HUD this replaces
// (score, lives, multiplier and weapon; the wanted heads; the hearts; the talking head and its
// subtitle; the timers and counters) are dropped from the 2D stream, and this draws the same
// values, read from the game, as a clean layer of its own with a mini-map.
#pragma once

#include <cstdint>
#include <string>

struct IDirect3DDevice9;
namespace gta2 { class Map; }

namespace gta2dx9 {

// Once a frame, inside the scene, after the game's 2D layer and before the F4 menu.
// `map` is the level the world was built from (the mini-map's road cells).
void Hud3dRender(IDirect3DDevice9* device, int width, int height, const gta2::Map& map, bool worldLoaded);

// The overlay asks this for every 2D draw it is handed. `corners` points at `count` vertices
// of 28 bytes each (x, y, z, rhw floats; ARGB colour; u, v texels), in the game's own screen
// coordinates. True: the modern HUD shows this part itself, so the draw is dropped.
bool Hud3dSwallow(bool hud, int part, const void* texture, const void* corners, int count);
// FIX-HUD-2 (pm50, feel4): what becomes of a digit of the game's score pop (the number that zooms
// up and fades over a kill or a payout, laid out on the game's top-down camera). 0: drawn as the
// game drew it (the classic view, always); 1: dropped (a street view with the modern HUD up, whose
// "+$n" pop rises from the car instead); 2: drawn no taller than a tenth of the screen (a street
// view with the game's HUD).
int Hud3dScorePop();

// Whether the modern HUD is the one on screen this frame.
bool Hud3dActive();

// While the view switch's dissolve shows the last classic frame (the game's HUD in it) over
// the street view, the modern HUD stays off and the game's HUD on, under its own copy; it cuts
// to the modern HUD when the dissolve ends (pm7). Set once a frame before Hud3dRender.
void Hud3dHoldForSwitch(bool hold);

// The street views' top plates (the zone name, part 7; the car's name, part 8), pm2: false in the
// classic view (placed as the game places them). Otherwise `bandBottom` is the bottom of the
// first-person cockpit's roof band in game pixels (480 tall; 0 when there is none), the plates
// drop out from under it.
bool Hud3dTopPlates(float* bandBottom);
// FIX-HUD-8: the street views' top plates' lowest edge this frame (game y of 480; < 0: none).
void Hud3dNoteTopPlatesBottom(float y480);

// QB-17/18: a text of the player's data\e.gxt by key ("wasted", "1124"); false when unknown.
bool Hud3dGameText(const char* key, std::u16string* out);

}  // namespace gta2dx9
