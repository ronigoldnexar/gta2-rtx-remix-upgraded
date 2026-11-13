// DISTRICTS-POC: the facade kit (tools/districts/kit.py) loaded as street-only geometry.
//
// A level's kit is a baked mesh, gta2dx9_districts\<style>.kit beside the game, made offline from the
// building catalogue: per building a skin that stands the wall 0.05 block proud of the box face with a
// hole at every window, door and shop window the tile art shows (the box face behind becomes the
// recessed glass), the openings' reveals, sills, lintels, cornices, parapets, a plinth, awnings, fire
// escapes, cladding ribs, dock canopies and roof plant (docs/districts-plan.md). Parts that show the
// wall's own art use the wall's tile (same texture, same Remix hash as the wall); the rest use one of the
// kit's own materials, gta2dx9_districts\kit_NN.dds, which take the tile slots after the riverbed's.
//
// Everything goes in as TileBatch::streetOnly batches appended after every other batch (the classic
// view's draws and ranges are unchanged) marked TileBatch::kit, which the renderer fades in with the
// street presentation over the move from the classic view (Renderer::SetKitPresentation).
// [districts] facade_kit=1 turns it on (default 0); read when the level loads.
#pragma once

#include <string>

#include "gta2_style.h"
#include "world_mesh.h"

namespace gta2 {

constexpr int kKitMaterials = 32;   // kit.py KIT (22 used); a group past it is skipped, so keep headroom
inline int KitTileIndex(const Style& style, int k) { return style.TileCount() + 2 + k; }
inline bool IsKitTile(const Style& style, int tile) { return tile >= style.TileCount() + 2 && tile < style.TileCount() + 2 + kKitMaterials; }

void SetDistrictKit(bool on, const char* dir);
bool DistrictKitEnabled();
const std::string& DistrictKitDir();

struct DistrictKitStats {
    bool loaded = false;
    int groups = 0, batches = 0, triangles = 0, vertices = 0, skipped = 0;
    size_t bytes = 0;
};

// Appends gta2dx9_districts\<styleName>.kit to the mesh (street-only kit batches). False, mesh unchanged,
// when the kit is off, the file is missing or malformed.
bool AppendDistrictKit(const Style& style, const std::string& styleName, WorldMesh* mesh, DistrictKitStats* stats);

}  // namespace gta2
