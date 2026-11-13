// WEATHER-V2 (docs/weather.md): wet ground under RTX Remix. The street views' ground lids
// (road and pavement, flat, open to the sky) get a second, Remix-API-drawn layer: a wet film
// that darkens the surface and lowers its roughness, faded by the instance's alpha, and
// puddles with a mirror-like material. Nothing here runs on the plain renderer or in the
// classic view (the alpha is weighted by the view's street mix and nothing is drawn at 0).
#pragma once

#include <cstdint>
#include <vector>

namespace gta2 { class Map; }

namespace gta2dx9 {

// Once a frame in the street views, after the world and the live geometry. eye in world
// units (blocks, y up); viewMix 0 classic .. 1 street.
// WEATHER-V2: the puddle field of the whole map (the same noise and gutter/rut bias as the Remix puddles) as
// size x size ARGB texels (r: puddle value mapped to the plain wet pass's threshold, g: fine ripple noise).
void BuildPuddleField(const gta2::Map& map, int size, std::vector<uint8_t>* out);   // plain: L8, size/256 texels per block

void RemixWetFrame(const gta2::Map& map, float eyeX, float eyeY, float eyeZ, float viewMix, const float fwd[3]);   // fwd: the camera's forward, world

}  // namespace gta2dx9
