// The modern HUD of the street views (third and first person). See hud3d.cpp and docs/hud.md.
//
// In the classic view nothing changes: the game's own HUD is drawn as it always was. In the
// street views, with [hud] modern=1 (the default), the parts of the game's HUD this replaces
// (score, lives, multiplier and weapon; the wanted heads; the hearts; the talking head and its
// subtitle; the timers and counters) are dropped from the 2D stream, and this draws the same
// values, read from the game, as a clean layer of its own with a mini-map.
#pragma once

#include <cstdint>

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

// Whether the modern HUD is the one on screen this frame.
bool Hud3dActive();

}  // namespace gta2dx9
