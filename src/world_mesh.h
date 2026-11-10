// Converts a GTA2 block map into true 3D world-space triangle geometry.
//
// World frame is left-handed, one block = one unit:
//   +X east (map x), +Y up (map level), +Z south (map y).
//
// Nothing here is screen-relative: vertices are absolute world positions, which
// is what RTX Remix needs to build acceleration structures. Geometry is grouped
// by tile so each tile becomes its own draw call with its own texture, giving
// Remix a stable per-tile hash to key asset replacements off.
#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "gta2_map.h"
#include "gta2_style.h"

namespace gta2 {

struct Vertex {
    float x, y, z;
    float nx, ny, nz;
    float u, v;
};

// One draw call: all faces in the map that use a single tile.
struct TileBatch {
    int tile = 0;
    uint32_t indexStart = 0;
    uint32_t indexCount = 0;
    uint32_t vertexStart = 0;
    uint32_t vertexCount = 0;
    bool needsAlphaTest = false;
    // Any of its faces is a lid (normal up): a tile seen on roofs or roads is
    // never a window, whatever its pixels look like.
    bool lidFaces = false;
    // Drawn without culling. GTA2's own renderer culls nothing
    // (d3ddll.dll!0x00E01A97 sets D3DRENDERSTATE_CULLMODE to D3DCULL_NONE), so
    // a lone fence or grille shows from both sides; a solid wall is one side of
    // a closed block and nobody sees behind it. So only the see-through faces -
    // flat ones and the backs of panels, ColourKeyed - are drawn both ways.
    bool doubleSided = false;
    // Drawn only in the street views (Renderer::SetStreetView), never in the classic
    // top-down view: the fill that makes the city watertight from a street or a roof
    // (AddStreetFill in world_mesh.cpp). Appended after every other batch, so the
    // classic view's draws and vertex ranges are what they were without it.
    bool streetOnly = false;
    // Texture coordinates run past 0..1 (one repeat per block) and want WRAP addressing:
    // the apron past the map's edge (AddApron in world_mesh.cpp). Street views only.
    bool wrapUv = false;
    // The street views draw this batch from streetIndexStart/streetIndexCount instead of
    // indexStart/indexCount: the same triangles less the overhead decals
    // (FindOverheadDecals in world_mesh.cpp).
    // Appended after every other index, so the classic view's ranges are unchanged.
    bool streetIndices = false;
    uint32_t streetIndexStart = 0;
    uint32_t streetIndexCount = 0;
};

struct WorldMesh {
    std::vector<Vertex> vertices;
    std::vector<uint32_t> indices;
    std::vector<TileBatch> batches;
    // Tiles used as the lid of a road block (ground type 1): the street views' tone match
    // (renderer.cpp, tone_match) evens out their asphalt.
    std::vector<int> roadLidTiles;
    // The plane of every railing built as bars (QB-11), four corners each: never drawn. The
    // bars have gaps a ray slips through, so the street cameras' clearance (eye_collision.cpp)
    // takes the panel as one solid sheet: no eye or boom ends up among the bars or behind
    // the railing looking through it (feel25, pm26 fence). 12 floats a panel: x,y,z of its
    // corners in order round the quad.
    std::vector<float> railingPanels;
};

// One entry of gta2.exe's slope descriptor table at 0x00662DB0, twelve bytes
// apiece, indexed by slope type. It is built at startup rather than stored in
// the image, so it has to be read out of the running game; when it is not
// available the mesh builder falls back to deriving the same values.
//
//   direction  1 = rises north, 2 = south, 3 = west, 4 = east (0 = not a ramp)
//   steps      how many blocks the whole ramp climbs over
//   step       which one of them this block is
struct SlopeInfo {
    uint8_t direction = 0;
    uint8_t steps = 0;
    uint8_t step = 0;
};

constexpr int kSlopeTypeCount = 64;

// Where the cut falls in a partial or corner block (slope types 53-61), as a
// fraction of the cell. Read from the game alongside the slope table; the
// defaults are the quarter and three-quarter marks the shapes imply.
struct PartialCuts {
    float low = 0.25f;
    float high = 0.75f;
};

// Corner heights of a block's lid above its own base, in the order NW, NE, SE,
// SW - matching the block's world corners (xWest,zNorth), (xEast,zNorth),
// (xEast,zSouth), (xWest,zSouth). A flat lid is {1,1,1,1}.
//
// Shared with the sprite pass, which samples the same surface this builds so a
// sprite conforms to the floor that is actually drawn under it.
using CornerHeights = std::array<float, 4>;
CornerHeights LidHeights(const SlopeInfo& slope);

// Fills out[kSlopeTypeCount] with the game's descriptors where they were read
// and derived ones where they were not. Every consumer of the slope table goes
// through this, so none of them can disagree about a ramp.
void ResolveSlopeTable(const SlopeInfo* slopes, SlopeInfo* out);

// The batch that seals the world from underneath.
//
// GTA2's map is not a closed solid. A column stores only the blocks it actually
// has, every block is a shell of the faces the original renderer needed to draw,
// and where the artwork used the colour-key index there are slits straight
// through a wall. None of that mattered against a black background; under a path
// tracer with a sky, every one of them is a hole with the sky behind it.
//
// Rather than trying to work out which faces the map is missing - which cannot
// be done reliably, because a fence block and a solid block look alike from the
// map data - one black quad goes underneath the whole city, well below the
// lowest block. Anything looking down through a hole then lands on that instead
// of on the sky, which is what the original showed. It cannot clip anything
// above ground, because it is not above ground.
//
// It gets a tile index one past the style's own so it is its own batch, its own
// texture and its own stable Remix hash, rather than being smuggled into some
// real tile's draw call.
inline int SealTileIndex(const Style& style) { return style.TileCount(); }

// The batch for the riverbed, two past the style's own tiles - see
// SetRiverbedDepth. Its own texture and so its own stable Remix hash, for a sand
// material to replace.
inline int RiverbedTileIndex(const Style& style) { return style.TileCount() + 1; }

// How far below level 0 the seal sits, and how far past the map it reaches. The
// overhang is what stops a camera near the edge of the city seeing sky under its
// own feet.
constexpr float kSealDepth = 2.0f;
constexpr float kSealOverhang = 512.0f;

// On by default. Off leaves the world exactly as the map describes it, which is
// the way to see what the seal was hiding. Read when the mesh is built, so a
// change wants a level reload.
void SetWorldSeal(bool on);
bool WorldSeal();

// The street views' fill (on by default; GTA2DX9_STREET_FILL=0 or [map] street_fill=0
// leaves it out): risers where a solid block meets air with no face between them, so a
// camera on a roof or in the street never looks under a lid into the implicit ground
// and down to the seal, and a ground plane at level 0 under columns with nothing at
// the bottom. Read when the mesh is built.
void SetStreetFill(bool on);
bool StreetFill();
struct StreetFillCounts { int risers = 0, floors = 0, ground = 0, apronTile = 0; float apronHeight = 0.0f; int ceilings = 0, baseSides = 0, rampSides = 0, decks = 0, latticeCeilingsSkipped = 0, latticeCeilingsRaised = 0, diagonalUndersides = 0; };
StreetFillCounts LastStreetFillCounts();

// The overhead decals the street views leave out (lamp brackets, wire ends:
// see FindOverheadDecals in world_mesh.cpp): how many tiles qualify and how many lids.
struct OverheadDecalStats { int tiles = 0, lids = 0; };
OverheadDecalStats LastOverheadDecalStats();
// Sloped see-through lids the street views stand up as boards (UprightBoard in world_mesh.cpp).
int LastUprightBoards();
// FIX-WORLD-10 (ptrmx28): flat lamp-pole cards stood up as round poles for the street views (AddLampPole),
// one per card per level; GTA2DX9_LAMP_POLES=0 keeps the cards (LampPoles() false).
int LastLampPoleSegments();
// FIX-WORLD-11: the lamps' flat arm/head lids beside those poles hung as solids (AddLampArm), street views only.
int LastLampArms();
bool LampPoles();

// The map's own trees (defects pm8 / pm23): GTA2 draws a tree as a 2x2 group of lidless
// corner ramps (slope types 49 NW, 50 NE, 51 SW, 52 SE) whose see-through cut faces (the
// branch tile, flat bit set) rise to a peak over the group's middle, standing on a 2x2 of
// see-through flat lids one level down (the crown seen from above). From above that is a
// tree; from the street it is a black spiky pyramid over a flat sheet of branches. The
// street views leave both out (FindMapTrees decides which, BuildWorldMesh hides them through
// TileBatch::streetIndices, so the classic view is unchanged) and stand a tree model there
// (LiveGeometry::DrawProps). x, y: the group's north-west cell (map coordinates); level:
// the pyramid's level (its base at height `level`, its peak at `level + 1`). The trunk
// stands at the group's middle: world x = x + 1, world z = kMapHeight - 1 - y.
// GTA2DX9_MAP_TREES=0 keeps the map's own blocks in the street views and places no models.
struct MapTree { int x = 0, y = 0, level = 0; };
std::vector<MapTree> FindMapTrees(const Map& map);
bool MapTreesEnabled();
struct MapTreeStats { int trees = 0, faces = 0; };
// FIX-ARTEFACTS (pm24): the plain flat sides of composed window panels (the rose windows'
// unflipped quarters) the street views leave out, so the composed side shows from behind
// (FindPlainPanelSides in world_mesh.cpp); the faces left out at the last build.
std::vector<uint8_t> FindPlainPanelSides(const Map& map);
int LastPlainPanelSides();
MapTreeStats LastMapTreeStats();
// FIX-WORLD-8 (ptrmx22): gantry signal slabs whose two lamp panels the street views draw at signal
// scale (world_mesh.cpp SignalSlab); GTA2DX9_SIGNAL_HEADS=0 keeps the block-tall lamps.
int LastSignalHeads();
float SignalHeadScale();
// Walkable see-through gratings given an opaque underside in the street views (defect pm36).
int LastGrateUndersides();

// How many blocks one repeat of a water tile's texture spans.
//
// GTA2 lays each water tile on its block like any other lid: one whole tile per
// block, turned however the face word says. Under the original texture that
// reads as open water. A replacement water material - an animated wave sheet
// through Remix's sprite_sheet_* inputs - shows it for what it is: the same few
// metres of waves stamped once per block, a visible grid, with seams wherever a
// lid is turned. So a water lid (Style::IsWaterTile) instead takes its texture
// coordinates from its position in the world, one repeat every this many
// blocks, the same way up everywhere. Remix wraps them itself (frac, with the
// gradients kept continuous), and so does the D3D9 sampler.
//
// A block is about 4 m (rtx.sceneScale), so the default 2.5 makes one repeat
// 10 m. 0 turns it off and gives water the ordinary per-block coordinates.
// Read when the mesh is built, so a change wants a level reload.
constexpr float kDefaultWaterUvBlocks = 2.5f;
void SetWaterUvBlocks(float blocks);
float WaterUvBlocks();

// A riverbed under the water, this many blocks below each water lid.
//
// GTA2's water is a lid with nothing under it; the original never showed
// anything through it. Through a translucent water material the path tracer
// looks straight down to the seal, three blocks below the sea, and the water
// reads as black. So every water cell gets a sand floor under it - deep enough
// that a sinking sprite still has water around it before it gets there - and so
// does every cell within kRiverbedPad of one. The quays have no walls below the
// waterline, so a view at an angle past a quay edge would otherwise find the
// black seal under the land. Under land the pad is hidden inside the ground.
//
// Where cells of different water heights meet, the lower bed wins, so no water
// surface ever has sand closer than the depth under it. 0 is no riverbed. Read
// when the mesh is built, so a change wants a level reload.
constexpr float kDefaultRiverbedDepth = 1.0f;
constexpr int kRiverbedPad = 1;
void SetRiverbedDepth(float blocks);
float RiverbedDepth();

// QB-11: railings as models. A railing tile on a panel (a cut-out of full-width
// rails and a row of vertical bars, with or without finials, read from the tile's
// own alpha) is built as square bars, flat rails and lathed finials on the
// panel's plane instead of the flat alpha-tested quad. On by default;
// GTA2DX9_RAILINGS=0 in the environment (read at each build) gives the flat panels
// back. Read when the mesh is built, so a change wants a level reload.
struct RailingStats {
    int tiles = 0;          // distinct tiles built as railings
    int panels = 0;         // panels built (one per plane, both sides)
    int quadsReplaced = 0;  // flat quads not emitted (a panel's two sides)
    int triangles = 0;      // triangles the railings added
};
void SetRailingModels(bool on);
bool RailingModels();
RailingStats LastRailingStats();

// slopes may be null, in which case the ramp geometry is derived instead.
void BuildWorldMesh(const Map& map, const Style& style, const SlopeInfo* slopes,
                    const PartialCuts& cuts, WorldMesh* out);

}  // namespace gta2
