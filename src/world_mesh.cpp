#include "world_mesh.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <map>
#include <set>
#include <tuple>
#include <utility>
#include <vector>

namespace gta2 {
namespace {

// Tiles are packed edge-to-edge in 256x256 pages, so sampling must stay half a
// texel inside the tile or neighbours bleed in at the seams.
constexpr float kUvInset = 0.5f / kTileSize;
constexpr float kUvMin = kUvInset;
constexpr float kUvMax = 1.0f - kUvInset;

// Flat faces are decals sitting on a neighbouring block's surface; nudging them
// along their normal keeps them off the coincident wall plane.
constexpr float kFlatFaceOffset = 0.002f;

struct Uv {
    float u, v;
};

}  // namespace

// --- Lid shape ------------------------------------------------------------
//
// Out of the anonymous namespace and declared in the header because the sprite
// pass samples the same surface it builds here. Two readings of a ramp would be
// two different floors, and a sprite conformed to the wrong one is exactly the
// bug the conform exists to remove.

// The heights the game itself uses for a ramp block, taken straight from its
// slope descriptor (gta2.exe!FUN_00471ce0): the raised edge sits at
// (steps - step)/steps and the opposite one a single step lower. Deriving
// "step + 1" instead - the obvious reading - runs every ramp backwards.
CornerHeights RampHeights(const SlopeInfo& slope) {
    if (slope.direction < 1 || slope.direction > 4 || slope.steps == 0) {
        return {1.0f, 1.0f, 1.0f, 1.0f};
    }
    const float steps = static_cast<float>(slope.steps);
    const float high = static_cast<float>(slope.steps - slope.step) / steps;
    const float low = static_cast<float>(slope.steps - slope.step - 1) / steps;
    switch (slope.direction) {
        case 1: return {high, high, low, low};   // rises north
        case 2: return {low, low, high, high};   // rises south
        case 3: return {high, low, low, high};   // rises west
        default: return {low, high, high, low};  // rises east
    }
}

// Used only when the game's table has not been read (the offline tools:
// tools/world_raycast.cpp, dump_block); reproduces the same families it builds at
// startup: 1-8 climb in two steps, 9-40 in eight, 41-44 in one, in the order north,
// south, west, east. Within a family the first type is the LOW piece (RampHeights
// reads step from the top): Downtown's ramp at (28,45..52), types 17..24, climbs from
// the street at level 2 north of it to the ground at level 3 south of it. Counting
// the steps the other way made 50-85 % of the joins between ramp blocks in the three
// districts a step (each ramp a sawtooth, open at its sides); this way 99 % join
// (FIX-WORLD-2, 9 Nov 2026).
SlopeInfo DeriveSlope(int slopeType) {
    SlopeInfo slope;
    int index = -1;
    if (slopeType >= 1 && slopeType <= 8) {
        slope.direction = static_cast<uint8_t>((slopeType - 1) / 2 + 1);
        slope.steps = 2;
        index = (slopeType - 1) % 2;
    } else if (slopeType >= 9 && slopeType <= 40) {
        slope.direction = static_cast<uint8_t>((slopeType - 9) / 8 + 1);
        slope.steps = 8;
        index = (slopeType - 9) % 8;
    } else if (slopeType >= 41 && slopeType <= 44) {
        slope.direction = static_cast<uint8_t>(slopeType - 41 + 1);
        slope.steps = 1;
        index = 0;
    }
    if (index >= 0) slope.step = static_cast<uint8_t>(slope.steps - 1 - index);
    return slope;
}

CornerHeights LidHeights(const SlopeInfo& slope) { return RampHeights(slope); }

void ResolveSlopeTable(const SlopeInfo* slopes, SlopeInfo* out) {
    for (int type = 0; type < kSlopeTypeCount; ++type) {
        const bool usable = slopes && slopes[type].direction >= 1 && slopes[type].direction <= 4 &&
                            slopes[type].steps != 0 && slopes[type].step < slopes[type].steps;
        out[type] = usable ? slopes[type] : DeriveSlope(type);
    }
}

namespace {

// Orientation tables copied verbatim out of gta2.exe. Each face type has its
// own: the game indexes them with the face word's bits 13-15 and passes the
// result to gbh_DrawTile as orientation flags. Walls therefore carry a built-in
// rotation relative to lids, and use flip bit 0x10 where lids use 0x08 - which
// is why applying the lid's rules to walls scrambles wall artwork even when the
// tile itself is correct.
//
// Addresses are for the default view-rotation state (0xFF); the other states
// also permute corner positions and are not handled here.
constexpr uint8_t kLidFlags[8] = {0x00, 0x08, 0x20, 0x28, 0x40, 0x48, 0x60, 0x68};     // 0x593154
constexpr uint8_t kLeftFlags[8] = {0x23, 0x33, 0x43, 0x53, 0x63, 0x73, 0x03, 0x13};    // 0x5930D4
constexpr uint8_t kRightFlags[8] = {0x64, 0x74, 0x04, 0x14, 0x24, 0x34, 0x44, 0x54};   // 0x5930F4
constexpr uint8_t kTopFlags[8] = {0x41, 0x49, 0x61, 0x69, 0x01, 0x09, 0x21, 0x29};     // 0x593114
constexpr uint8_t kBottomFlags[8] = {0x02, 0x0A, 0x22, 0x2A, 0x42, 0x4A, 0x62, 0x6A};  // 0x593134

// Diagonal blocks draw their lid as a triangle, and each of the four facings
// gets its own table (gta2.exe!FUN_0046dfe0, cases 0..3).
constexpr uint8_t kDiagLidDropNw[8] = {0x65, 0x75, 0x05, 0x15, 0x25, 0x35, 0x45, 0x55};  // 0x5931B4
constexpr uint8_t kDiagLidDropSe[8] = {0x25, 0x35, 0x45, 0x55, 0x65, 0x75, 0x05, 0x15};  // 0x593194
constexpr uint8_t kDiagLidDropNeSw[8] = {0x05, 0x0D, 0x25, 0x2D, 0x45, 0x4D, 0x65, 0x6D};  // 0x5931D4

// Maps a fraction of the tile onto the inset range, so a face covering only
// part of its cell shows only the matching part of the artwork.
float UvAt(float fraction) { return kUvMin + fraction * (kUvMax - kUvMin); }

// Reproduces gbh_DrawTile's orientation handling exactly: the flags permute the
// four corners' texture coordinates, and 180 degrees is expressed as "apply both
// flips" rather than as a rotation. Doing arithmetic on the coordinates instead
// gives the right artwork in the wrong orientation.
std::array<Uv, 4> FaceUvs(const Face& face, const uint8_t (&table)[8]) {
    std::array<Uv, 4> uv = {{{kUvMin, kUvMin}, {kUvMax, kUvMin}, {kUvMax, kUvMax}, {kUvMin, kUvMax}}};

    unsigned flags = table[(face.raw >> 13) & 7];
    switch (flags & 0x60) {
        case 0x20: {  // one quarter turn: every corner takes the previous one's UV
            const Uv last = uv[3];
            uv[3] = uv[2];
            uv[2] = uv[1];
            uv[1] = uv[0];
            uv[0] = last;
            break;
        }
        case 0x40:  // half turn is expressed as both flips
            flags ^= 0x18;
            break;
        case 0x60: {  // three quarter turns: the same shift in reverse
            const Uv first = uv[0];
            uv[0] = uv[1];
            uv[1] = uv[2];
            uv[2] = uv[3];
            uv[3] = first;
            break;
        }
        default:
            break;
    }
    if (flags & 0x8) {
        std::swap(uv[0], uv[1]);
        std::swap(uv[2], uv[3]);
    }
    if (flags & 0x10) {
        std::swap(uv[0], uv[3]);
        std::swap(uv[1], uv[2]);
    }
    return uv;
}

// The part of a face's tile that a face covering only part of its cell shows:
// a slab a quarter of a cell deep shows a quarter of the tile, not the tile
// squeezed into a quarter.
//
// Which quarter turns with the tile. The game builds the whole cell's mapping
// onto the whole tile, orientation included (gta2.exe!FUN_0046bea0), and then
// passes each corner's *position in the cell* through it (FUN_0046c0c0). So the
// crop is taken in the face's own space, not the texture's: a north slab whose
// lid is turned half way round shows the bottom rows of its tile. Cropping the
// texture first and turning only the crop showed the top rows whatever the
// rotation - and on the lattice over the first save point, whose top rows are
// all colour key, that left nothing at all.
//
// s runs from the face's slot 0 to slot 1, t from slot 0 to slot 3, both as
// fractions of the whole face; the corners come back in the face's slot order.
std::array<Uv, 4> FaceUvsPart(const Face& face, const uint8_t (&table)[8], float s0, float s1,
                              float t0, float t1) {
    const std::array<Uv, 4> whole = FaceUvs(face, table);
    const Uv along{whole[1].u - whole[0].u, whole[1].v - whole[0].v};
    const Uv across{whole[3].u - whole[0].u, whole[3].v - whole[0].v};
    const float s[4] = {s0, s1, s1, s0};
    const float t[4] = {t0, t0, t1, t1};
    std::array<Uv, 4> uv;
    for (int i = 0; i < 4; ++i) {
        uv[i] = Uv{whole[0].u + s[i] * along.u + t[i] * across.u,
                   whole[0].v + s[i] * along.v + t[i] * across.v};
    }
    return uv;
}

struct Vec3 {
    float x, y, z;
};


// --- QB-11: railings as models ------------------------------------------------
//
// A railing in GTA2 is a flat panel: one tile of iron bars and rails with the
// gaps keyed out, hung on a block's edge. From the street that is a sheet of
// cut-out paper, and the upscaled art made it worse - the park fence's spear
// finials became dark blocky blobs with orange specks (quality bar row 11).
//
// So a tile whose cut-out is nothing but full-width horizontal rails and
// vertical bars (with an optional finial on top of each bar) is rebuilt as
// geometry on that panel instead: square bars, flat rails, and each finial a
// four-sided lathe of the artwork's own outline, row by row. The shape is read
// from the tile's alpha at mesh build, so it is the same in all three
// districts without a table of tile numbers, and a tile that does not decompose
// cleanly (lattices, X braces, hoardings, single poles) keeps its flat panel.
// The geometry samples the tile's own opaque pixels, so it keeps the tile's
// texture, its HD replacement and its Remix hash.
struct RailingBar {
    int x0 = 0, x1 = 0;          // columns, inclusive
    int top = 0, bottom = 0;     // rows of the straight part, inclusive
    // The finial's outline from its tip down to the bar: (row centre, half width), pixels.
    std::vector<std::pair<float, float>> finial;
};
struct RailingShape {
    bool valid = false;
    std::vector<std::pair<int, int>> rails;   // rows, inclusive
    std::vector<RailingBar> bars;
    float barDepth = 4.0f, railDepth = 3.0f;  // pixels
};

// Douglas-Peucker on a (row, half width) outline: a spear keeps its tip, belly,
// neck and collar and loses the staircase of single-pixel steps between them.
void SimplifyOutline(const std::vector<std::pair<float, float>>& in, size_t a, size_t b,
                     float tolerance, std::vector<bool>* keep) {
    if (b <= a + 1) return;
    float worst = -1.0f;
    size_t at = a;
    const float dy = in[b].first - in[a].first, dr = in[b].second - in[a].second;
    const float len = std::sqrt(dy * dy + dr * dr);
    for (size_t i = a + 1; i < b; ++i) {
        const float d = len < 1e-6f ? std::fabs(in[i].second - in[a].second)
                                    : std::fabs(dr * (in[i].first - in[a].first) - dy * (in[i].second - in[a].second)) / len;
        if (d > worst) { worst = d; at = i; }
    }
    if (worst > tolerance) {
        (*keep)[at] = true;
        SimplifyOutline(in, a, at, tolerance, keep);
        SimplifyOutline(in, at, b, tolerance, keep);
    }
}

RailingShape AnalyseRailing(const Tile& tile) {
    RailingShape shape;
    if (!tile.hasTransparency || tile.pixels.size() < static_cast<size_t>(kTilePixels)) return shape;
    constexpr int N = kTileSize;
    auto solid = [&](int x, int y) { return (tile.pixels[static_cast<size_t>(y) * N + x] & 0xFF000000u) != 0; };
    int opaque = 0;
    bool full[N] = {};
    for (int y = 0; y < N; ++y) {
        int row = 0;
        for (int x = 0; x < N; ++x) row += solid(x, y) ? 1 : 0;
        full[y] = row >= N - 4;
        opaque += row;
    }
    if (opaque > N * N * 3 / 4) return shape;
    int railRows = 0;
    for (int y = 0; y < N;) {
        if (!full[y]) { ++y; continue; }
        const int y0 = y;
        while (y < N && full[y]) ++y;
        if (y - y0 > 10) return shape;           // a wall or kerb, not a rail
        shape.rails.push_back({y0, y - 1});
        railRows += y - y0;
    }
    // Bar columns: a vertical run of opaque pixels well past what the rails give.
    bool barColumn[N] = {};
    for (int x = 0; x < N; ++x) {
        int best = 0, run = 0;
        for (int y = 0; y < N; ++y) { run = solid(x, y) ? run + 1 : 0; best = (std::max)(best, run); }
        barColumn[x] = best >= (std::max)(12, railRows + 6);
    }
    std::vector<std::pair<int, int>> columns;
    for (int x = 0; x < N;) {
        if (!barColumn[x]) { ++x; continue; }
        const int x0 = x;
        while (x < N && barColumn[x]) ++x;
        if (x - x0 > 8) return shape;
        columns.push_back({x0, x - 1});
    }
    // The run of opaque pixels through a bar's centre on one row.
    auto runAt = [&](int y, int centre, int* l, int* r) {
        if (!solid(centre, y)) return false;
        *l = *r = centre;
        while (*l > 0 && solid(*l - 1, y)) --*l;
        while (*r < N - 1 && solid(*r + 1, y)) ++*r;
        return true;
    };
    std::vector<uint8_t> rebuilt(static_cast<size_t>(N) * N, 0);
    for (const auto& rail : shape.rails)
        for (int y = rail.first; y <= rail.second; ++y)
            for (int x = 0; x < N; ++x) rebuilt[static_cast<size_t>(y) * N + x] = 1;
    float widest = 1.0f;
    for (const auto& column : columns) {
        RailingBar bar;
        bar.x0 = column.first;
        bar.x1 = column.second;
        const int centre = (bar.x0 + bar.x1) / 2;
        // The bar's own width is the commonest run through its centre in the lower half.
        int counts[N + 1] = {};
        for (int y = N / 2; y < N; ++y) {
            int l, r;
            if (!full[y] && runAt(y, centre, &l, &r)) ++counts[r - l + 1];
        }
        int w = bar.x1 - bar.x0 + 1, most = 0;
        for (int k = 1; k <= N; ++k) if (counts[k] > most) { most = counts[k]; w = k; }
        if (w > 8) continue;
        // Rows that belong to the straight bar; a rail row always does, and a
        // one- or two-row blemish between good rows is forgiven.
        int ok[N] = {};
        for (int y = 0; y < N; ++y) {
            int l, r;
            ok[y] = full[y] || (runAt(y, centre, &l, &r) && r - l + 1 >= w - 1 && r - l + 1 <= w &&
                                l >= bar.x0 - 1 && r <= bar.x1 + 1);
        }
        for (int y = 1; y < N - 1; ++y)
            if (!ok[y] && ok[y - 1] && (ok[y + 1] || (y + 2 < N && !ok[y + 1] && ok[y + 2]))) ok[y] = 2;
        int bestTop = 0, bestLen = 0;
        for (int y = 0; y < N;) {
            if (!ok[y]) { ++y; continue; }
            const int y0 = y;
            while (y < N && ok[y]) ++y;
            if (y - y0 > bestLen) { bestLen = y - y0; bestTop = y0; }
        }
        if (bestLen < 8) continue;
        bar.top = bestTop;
        bar.bottom = bestTop + bestLen - 1;
        // Above the bar: whatever outline continues through its centre is the finial.
        std::vector<std::pair<float, float>> outline;
        std::vector<std::array<int, 3>> spans;
        for (int y = bar.top - 1; y >= 0; --y) {
            int l, r;
            if (!runAt(y, centre, &l, &r) && !(centre + 1 < N && runAt(y, centre + 1, &l, &r)) &&
                !(centre > 0 && runAt(y, centre - 1, &l, &r)))
                break;
            if (r - l + 1 > 3 * w || full[y]) break;
            outline.push_back({y + 0.5f, (r - l + 1) * 0.5f});
            spans.push_back({y, l, r});
        }
        if (outline.size() >= 4) {
            for (const auto& span : spans)
                for (int x = span[1]; x <= span[2]; ++x) rebuilt[static_cast<size_t>(span[0]) * N + x] = 1;
            std::reverse(outline.begin(), outline.end());   // tip first
            std::vector<std::pair<float, float>> pts;
            pts.push_back({outline.front().first - 0.5f, 0.0f});      // the point
            pts.insert(pts.end(), outline.begin(), outline.end());
            pts.push_back({static_cast<float>(bar.top), w * 0.5f});   // meets the bar
            std::vector<bool> keep(pts.size(), false);
            keep.front() = keep.back() = true;
            SimplifyOutline(pts, 0, pts.size() - 1, 0.6f, &keep);
            for (size_t i = 0; i < pts.size(); ++i) if (keep[i]) bar.finial.push_back(pts[i]);
        }
        for (int y = bar.top; y <= bar.bottom; ++y)
            for (int x = bar.x0; x <= bar.x1; ++x) rebuilt[static_cast<size_t>(y) * N + x] = 1;
        widest = (std::max)(widest, static_cast<float>(w));
        shape.bars.push_back(std::move(bar));
    }
    // A railing has a row of bars; one or two are a pole, a frame or a sign's edge.
    if (shape.bars.size() < 3) return shape;
    int both = 0, either = 0;
    for (int i = 0; i < N * N; ++i) {
        const bool a = solid(i % N, i / N), b = rebuilt[static_cast<size_t>(i)] != 0;
        both += (a && b) ? 1 : 0;
        either += (a || b) ? 1 : 0;
    }
    if (either == 0 || both * 100 < either * 92) return shape;
    shape.barDepth = widest;
    float railHeight = 0.0f;
    for (const auto& rail : shape.rails) railHeight = (std::max)(railHeight, static_cast<float>(rail.second - rail.first + 1));
    shape.railDepth = (std::max)(1.5f, (std::min)(railHeight, 0.7f * widest));
    shape.valid = true;
    return shape;
}

bool g_railingModels = true;
RailingStats g_railingStats;

class MeshBuilder {
public:
    // Two past the style's own tiles, for the seal and the riverbed - see
    // SealTileIndex and RiverbedTileIndex.
    explicit MeshBuilder(const Style& style) : style_(style) {
        for (int keyed = 0; keyed < 2; ++keyed) {
            perTile_[keyed].resize(style.TileCount() + 2);
            perTileTriangle_[keyed].resize(style.TileCount() + 2);
        }
        street_.resize(style.TileCount() + 2);
        apron_.resize(style.TileCount() + 2);
    }

    // While set, AddPlainQuad (floor, side, seal) goes to a street-only group: 1 the fill
    // (AddStreetFill), 2 the apron past the map's edge (AddApron, WRAP addressing). See
    // TileBatch::streetOnly.
    void SetStreetMode(int mode) { streetMode_ = mode; }

    // A quad with no tile behind it, for the black seal under the world. The
    // corners are given anticlockwise seen from the side the normal points at,
    // and the winding is worked out the same way AddFaceUv does it.
    void AddSealQuad(const std::array<Vec3, 4>& corners, Vec3 normal) {
        // The texture is one flat colour, so the coordinates only have to be
        // inside it; the corners of the tile keep the mapping obvious.
        static const std::array<Uv, 4> kUv = {{{0.0f, 0.0f}, {1.0f, 0.0f}, {1.0f, 1.0f},
                                              {0.0f, 1.0f}}};
        AddPlainQuad(SealTileIndex(style_), corners, normal, kUv);
    }

    // One cell of ground where the map stores no block: the top of a column's
    // implicit solid base (see AddImplicitFloors), textured like a neighbour.
    void AddFloorQuad(int tile, const std::array<Vec3, 4>& corners) {
        static const std::array<Uv, 4> kUv = {{{0.0f, 0.0f}, {1.0f, 0.0f}, {1.0f, 1.0f},
                                              {0.0f, 1.0f}}};
        AddPlainQuad(tile, corners, {0.0f, 1.0f, 0.0f}, kUv);
    }

    // One level of the side of that base, where a neighbour's base is lower.
    void AddSideQuad(int tile, const std::array<Vec3, 4>& corners, Vec3 normal) {
        static const std::array<Uv, 4> kUv = {{{0.0f, 0.0f}, {1.0f, 0.0f}, {1.0f, 1.0f},
                                              {0.0f, 1.0f}}};
        AddPlainQuad(tile, corners, normal, kUv);
    }

    // One cell of riverbed, face up. Its coordinates come from the world, one
    // repeat per block, so the sand runs on across cells without a seam.
    void AddRiverbedQuad(const std::array<Vec3, 4>& corners) {
        std::array<Uv, 4> uv;
        for (int i = 0; i < 4; ++i) uv[i] = Uv{corners[i].x, corners[i].z};
        AddPlainQuad(RiverbedTileIndex(style_), corners, {0.0f, 1.0f, 0.0f}, uv);
    }

    void AddPlainQuad(int slot, const std::array<Vec3, 4>& corners, Vec3 normal,
                      const std::array<Uv, 4>& uv) {
        const Vec3 edge1{corners[1].x - corners[0].x, corners[1].y - corners[0].y,
                         corners[1].z - corners[0].z};
        const Vec3 edge2{corners[2].x - corners[0].x, corners[2].y - corners[0].y,
                         corners[2].z - corners[0].z};
        const Vec3 cross{edge1.y * edge2.z - edge1.z * edge2.y,
                         edge1.z * edge2.x - edge1.x * edge2.z,
                         edge1.x * edge2.y - edge1.y * edge2.x};
        const bool reversed =
            cross.x * normal.x + cross.y * normal.y + cross.z * normal.z < 0.0f;
        static const int kForward[4] = {0, 1, 2, 3};
        static const int kReverse[4] = {0, 3, 2, 1};
        const int* order = reversed ? kReverse : kForward;
        // A face can name a tile the style does not have (1023 is the map's
        // "no face", and Face's bool test only excludes 0); the implicit
        // floors read neighbours' faces raw, so guard the slot here rather
        // than corrupt the heap. (Residential crashed on exactly this.)
        if (slot < 0 || static_cast<size_t>(slot) >= perTile_[0].size()) return;
        std::vector<Vertex>& out = streetMode_ == 2 ? apron_[static_cast<size_t>(slot)]
                                 : streetMode_ == 1 ? street_[static_cast<size_t>(slot)]
                                                    : perTile_[0][static_cast<size_t>(slot)];
        for (int i = 0; i < 4; ++i) {
            const int corner = order[i];
            out.push_back(Vertex{corners[corner].x, corners[corner].y, corners[corner].z,
                                 normal.x, normal.y, normal.z, uv[corner].u, uv[corner].v});
        }
    }

    // Corners are given in the original renderer's own vertex-slot order for
    // that face, since the orientation tables are written against it.
    //
    // extraPush moves the quad further along its normal than a flat face's own
    // nudge, for a tile the game paints onto a plane something else already
    // occupies.
    //
    // panelBack marks the back of a flat panel, which is see-through whatever
    // its own face word says - see ColourKeyed.
    void AddFace(const Face& face, const std::array<Vec3, 4>& corners, Vec3 normal,
                 const uint8_t (&table)[8], float extraPush = 0.0f, bool panelBack = false) {
        AddFaceUv(face, corners, normal, FaceUvs(face, table), extraPush, panelBack);
    }

    // Ramps bypass the orientation tables entirely: the game writes texture
    // coordinates in by hand so a shortened wall shows the *bottom* of its tile
    // with the top cropped off, rather than the whole tile squashed into a
    // shorter quad (gta2.exe!FUN_0046c2c0, the DAT_006633b8 = 0x4005 path).
    void AddFaceUv(const Face& face, const std::array<Vec3, 4>& corners, Vec3 normal,
                   const std::array<Uv, 4>& uv, float extraPush = 0.0f,
                   bool panelBack = false) {
        const int tile = face.Tile();
        if (tile <= 0 || tile >= static_cast<int>(perTile_[0].size())) return;

        // QB-11: a railing tile on a panel becomes bars and rails - see AnalyseRailing.
        if ((face.IsFlat() || panelBack) && TryRailing(tile, corners, normal, uv)) return;

        const float push = (face.IsFlat() ? kFlatFaceOffset : 0.0f) + extraPush;

        // Water lids take their coordinates from the world - see
        // SetWaterUvBlocks. Only lids: a water tile hung on a wall is a
        // picture of water, and keeps its orientation.
        std::array<Uv, 4> worldUv;
        const std::array<Uv, 4>* texcoords = &uv;
        const float repeat = WaterUvBlocks();
        if (repeat > 0.0f && normal.y > 0.5f && style_.IsWaterTile(tile)) {
            for (int i = 0; i < 4; ++i) {
                worldUv[i] = Uv{corners[i].x / repeat, corners[i].z / repeat};
            }
            texcoords = &worldUv;
        }

        // Slot order differs per face, so winding is derived from the geometry
        // rather than assumed: if the corners wind away from the outward normal,
        // the quad is emitted reversed.
        const Vec3 edge1{corners[1].x - corners[0].x, corners[1].y - corners[0].y,
                         corners[1].z - corners[0].z};
        const Vec3 edge2{corners[2].x - corners[0].x, corners[2].y - corners[0].y,
                         corners[2].z - corners[0].z};
        const Vec3 cross{edge1.y * edge2.z - edge1.z * edge2.y,
                         edge1.z * edge2.x - edge1.x * edge2.z,
                         edge1.x * edge2.y - edge1.y * edge2.x};
        const float facing = cross.x * normal.x + cross.y * normal.y + cross.z * normal.z;
        const bool reversed = facing < 0.0f;

        // The normal the vertices carry is the surface's own, measured, rather
        // than the one the caller named.
        //
        // Callers pass the direction the face *points* - which for a wall is
        // exact, and for a lid is {0,1,0} whether or not that lid is a ramp. A
        // ramp's four corner heights differ by construction, so its quad is a
        // sloped plane being described as level. Nothing in the D3D9 pass
        // noticed, because D3DRS_LIGHTING is off and fixed function never reads
        // a normal; RTX Remix does read them, so every ramp in the city was
        // being path traced with the shading of flat ground.
        //
        // The cross product above is already the true surface direction, up to
        // sign, and the caller's normal is exactly the thing that says which
        // sign is outward. So take the measurement and let the caller orient it.
        // Walls are unaffected: their cross is parallel to what they pass.
        Vec3 surface = normal;
        const float length = std::sqrt(cross.x * cross.x + cross.y * cross.y + cross.z * cross.z);
        if (length > 1e-6f) {
            const float sign = reversed ? -1.0f : 1.0f;
            surface = {cross.x * sign / length, cross.y * sign / length, cross.z * sign / length};
        }

        std::vector<Vertex>& out = perTile_[ColourKeyed(face, panelBack)][tile];
        static const int kForward[4] = {0, 1, 2, 3};
        static const int kReverse[4] = {0, 3, 2, 1};
        const int* order = reversed ? kReverse : kForward;
        for (int i = 0; i < 4; ++i) {
            const int slot = order[i];
            out.push_back(Vertex{corners[slot].x + surface.x * push,
                                 corners[slot].y + surface.y * push,
                                 corners[slot].z + surface.z * push,
                                 surface.x, surface.y, surface.z,
                                 (*texcoords)[slot].u, (*texcoords)[slot].v});
        }
    }

    // The cut face of a corner ramp is a genuine triangle, not a collapsed quad
    // (the game draws it through gbh_DrawTriangle, not gbh_DrawTile).
    void AddTriangle(const Face& face, const std::array<Vec3, 3>& corners,
                     const std::array<Uv, 3>& uv) {
        const int tile = face.Tile();
        if (tile <= 0 || tile >= static_cast<int>(perTile_[0].size())) return;

        const Vec3 edge1{corners[1].x - corners[0].x, corners[1].y - corners[0].y,
                         corners[1].z - corners[0].z};
        const Vec3 edge2{corners[2].x - corners[0].x, corners[2].y - corners[0].y,
                         corners[2].z - corners[0].z};
        Vec3 normal{edge1.y * edge2.z - edge1.z * edge2.y, edge1.z * edge2.x - edge1.x * edge2.z,
                    edge1.x * edge2.y - edge1.y * edge2.x};
        const float length =
            std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        if (length < 1e-6f) return;
        normal = {normal.x / length, normal.y / length, normal.z / length};
        // It is a ramp surface, so the outward side is the one facing up; that
        // fixes the winding without having to know the slot order.
        const bool flip = normal.y < 0.0f;
        if (flip) normal = {-normal.x, -normal.y, -normal.z};

        static const int kForward[3] = {0, 1, 2};
        static const int kReverse[3] = {0, 2, 1};
        const int* order = flip ? kReverse : kForward;
        // Kept apart from the quads so each can be indexed by its own stride.
        std::vector<Vertex>& out = perTileTriangle_[ColourKeyed(face, false)][tile];
        for (int i = 0; i < 3; ++i) {
            const int slot = order[i];
            out.push_back(Vertex{corners[slot].x, corners[slot].y, corners[slot].z, normal.x,
                                 normal.y, normal.z, uv[slot].u, uv[slot].v});
        }
    }

    // How many distinct tiles were built as railings (QB-11).
    int RailingTiles() const {
        std::set<int> tiles;
        for (const auto& key : railingPanels_) tiles.insert(std::get<0>(key));
        return static_cast<int>(tiles.size());
    }

    // Opaque batches first, then the see-through ones, so a tile used both ways
    // is two draws sharing one texture.
    void MarkRoadLid(int tile) { roadLids_.insert(tile); }
    std::set<int> roadLids_;

    void Flatten(WorldMesh* out) const {
        out->roadLidTiles.assign(roadLids_.begin(), roadLids_.end());
        for (int keyed = 0; keyed < 2; ++keyed) {
            for (size_t tile = 0; tile < perTile_[keyed].size(); ++tile) {
                FlattenOne(out, static_cast<int>(tile), keyed != 0);
            }
        }
        // Last, so every batch before them is exactly what it was without the fill.
        for (int group = 0; group < 2; ++group)
        for (size_t tile = 0; tile < street_.size(); ++tile) {
            const std::vector<Vertex>& quads = group == 0 ? street_[tile] : apron_[tile];
            if (quads.empty()) continue;
            TileBatch batch;
            batch.tile = static_cast<int>(tile);
            batch.streetOnly = true;
            batch.wrapUv = group == 1;
            batch.vertexStart = static_cast<uint32_t>(out->vertices.size());
            batch.vertexCount = static_cast<uint32_t>(quads.size());
            batch.indexStart = static_cast<uint32_t>(out->indices.size());
            for (const Vertex& v : quads) if (v.ny > 0.5f) { batch.lidFaces = true; break; }
            out->vertices.insert(out->vertices.end(), quads.begin(), quads.end());
            for (uint32_t quad = 0; quad < quads.size(); quad += 4) {
                const uint32_t base = batch.vertexStart + quad;
                out->indices.insert(out->indices.end(), {base + 0, base + 1, base + 2, base + 0, base + 2, base + 3});
            }
            batch.indexCount = static_cast<uint32_t>(out->indices.size()) - batch.indexStart;
            out->batches.push_back(batch);
        }
    }

private:
    const RailingShape& RailingOf(int tile) {
        if (railingShapes_.empty()) {
            railingShapes_.resize(perTile_[0].size());
            railingKnown_.assign(perTile_[0].size(), 0);
        }
        if (!railingKnown_[static_cast<size_t>(tile)]) {
            railingKnown_[static_cast<size_t>(tile)] = 1;
            if (tile < style_.TileCount()) railingShapes_[static_cast<size_t>(tile)] = AnalyseRailing(style_.GetTile(tile));
        }
        return railingShapes_[static_cast<size_t>(tile)];
    }

    // A quad with its normal measured from its corners and turned to face `outward`;
    // the winding follows, as in AddFaceUv. Opaque: the railing samples only the
    // tile's solid pixels, and its boxes are closed, so it is culled like a wall.
    void AddSolidQuad(int tile, const std::array<Vec3, 4>& c, Vec3 outward, const std::array<Uv, 4>& uv) {
        const Vec3 e1{c[1].x - c[0].x, c[1].y - c[0].y, c[1].z - c[0].z};
        const Vec3 e2{c[2].x - c[0].x, c[2].y - c[0].y, c[2].z - c[0].z};
        const Vec3 e3{c[3].x - c[0].x, c[3].y - c[0].y, c[3].z - c[0].z};
        // A quad with a collapsed edge (a finial's point) still has an area in one of
        // its two triangles; measure the normal from whichever is larger.
        Vec3 n{e1.y * e2.z - e1.z * e2.y, e1.z * e2.x - e1.x * e2.z, e1.x * e2.y - e1.y * e2.x};
        const Vec3 m{e2.y * e3.z - e2.z * e3.y, e2.z * e3.x - e2.x * e3.z, e2.x * e3.y - e2.y * e3.x};
        if (m.x * m.x + m.y * m.y + m.z * m.z > n.x * n.x + n.y * n.y + n.z * n.z) n = m;
        const float length = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
        if (length < 1e-9f) return;
        const bool reversed = n.x * outward.x + n.y * outward.y + n.z * outward.z < 0.0f;
        const float sign = reversed ? -1.0f : 1.0f;
        n = {n.x * sign / length, n.y * sign / length, n.z * sign / length};
        static const int kForward[4] = {0, 1, 2, 3};
        static const int kReverse[4] = {0, 3, 2, 1};
        const int* order = reversed ? kReverse : kForward;
        std::vector<Vertex>& out = perTile_[0][static_cast<size_t>(tile)];
        for (int i = 0; i < 4; ++i) {
            const int k = order[i];
            out.push_back(Vertex{c[k].x, c[k].y, c[k].z, n.x, n.y, n.z, uv[k].u, uv[k].v});
        }
        g_railingStats.triangles += 2;
    }

    bool TryRailing(int tile, const std::array<Vec3, 4>& c, Vec3 normal, const std::array<Uv, 4>& uv) {
        if (!g_railingModels || std::fabs(normal.y) > 0.1f) return false;
        const RailingShape& shape = RailingOf(tile);
        if (!shape.valid) return false;
        // Only a whole tile on a whole rectangle: a ramp-cropped or partial face keeps its panel.
        for (const Uv& t : uv) {
            const bool uEdge = std::fabs(t.u - kUvMin) < 1e-4f || std::fabs(t.u - kUvMax) < 1e-4f;
            const bool vEdge = std::fabs(t.v - kUvMin) < 1e-4f || std::fabs(t.v - kUvMax) < 1e-4f;
            if (!uEdge || !vEdge) return false;
        }
        const Vec3 fourth{c[1].x + c[3].x - c[0].x, c[1].y + c[3].y - c[0].y, c[1].z + c[3].z - c[0].z};
        if (std::fabs(fourth.x - c[2].x) + std::fabs(fourth.y - c[2].y) + std::fabs(fourth.z - c[2].z) > 1e-3f) return false;
        // The affine map from texture to panel, from corners 0, 1 and 3.
        const float du1 = uv[1].u - uv[0].u, dv1 = uv[1].v - uv[0].v;
        const float du3 = uv[3].u - uv[0].u, dv3 = uv[3].v - uv[0].v;
        const float det = du1 * dv3 - dv1 * du3;
        if (std::fabs(det) < 1e-6f) return false;
        const Vec3 e1{c[1].x - c[0].x, c[1].y - c[0].y, c[1].z - c[0].z};
        const Vec3 e3{c[3].x - c[0].x, c[3].y - c[0].y, c[3].z - c[0].z};
        const Vec3 dU{(dv3 * e1.x - dv1 * e3.x) / det, (dv3 * e1.y - dv1 * e3.y) / det, (dv3 * e1.z - dv1 * e3.z) / det};
        const Vec3 dV{(du1 * e3.x - du3 * e1.x) / det, (du1 * e3.y - du3 * e1.y) / det, (du1 * e3.z - du3 * e1.z) / det};

        // One railing per panel: the two sides of a panel carry the same tile on one plane.
        const float cx = (c[0].x + c[1].x + c[2].x + c[3].x) * 0.25f;
        const float cy = (c[0].y + c[1].y + c[2].y + c[3].y) * 0.25f;
        const float cz = (c[0].z + c[1].z + c[2].z + c[3].z) * 0.25f;
        const auto key = std::make_tuple(tile, static_cast<int>(std::lround(cx * 256.0f)),
                                         static_cast<int>(std::lround(cy * 256.0f)), static_cast<int>(std::lround(cz * 256.0f)));
        ++g_railingStats.quadsReplaced;
        if (!railingPanels_.insert(key).second) return true;
        ++g_railingStats.panels;

        const float nl = std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        const Vec3 n{normal.x / nl, normal.y / nl, normal.z / nl};
        const float step = (kUvMax - kUvMin) / kTileSize;     // texture per pixel
        // A point given in tile pixels (x across, y down the artwork) and a depth in pixels off the plane.
        auto at = [&](float px, float py, float pd) {
            const float u = kUvMin + px * step - uv[0].u, v = kUvMin + py * step - uv[0].v;
            const float d = pd / kTileSize;
            return Vec3{c[0].x + u * dU.x + v * dV.x + n.x * d, c[0].y + u * dU.y + v * dV.y + n.y * d,
                        c[0].z + u * dU.z + v * dV.z + n.z * d};
        };
        const Vec3 o = at(0.0f, 0.0f, 0.0f);
        const Vec3 ax = at(1.0f, 0.0f, 0.0f), ay = at(0.0f, 1.0f, 0.0f);
        const Vec3 xDir{ax.x - o.x, ax.y - o.y, ax.z - o.z}, yDir{ay.x - o.x, ay.y - o.y, ay.z - o.z};
        const Vec3 nNeg{-n.x, -n.y, -n.z}, xNeg{-xDir.x, -xDir.y, -xDir.z}, yNeg{-yDir.x, -yDir.y, -yDir.z};
        auto tex = [&](float px, float py) { return Uv{kUvMin + px * step, kUvMin + py * step}; };
        // A box over pixels [x0,x1] x [y0,y1] (edges), depth +-h; its faces sample the
        // texel rectangle [sx0,sx1] x [sy0,sy1] (centres), the sides a strip of it.
        auto box = [&](float x0, float x1, float y0, float y1, float h, float sx0, float sx1, float sy0, float sy1,
                       bool topCap, bool bottomCap, bool endCaps) {
            const float mx = (sx0 + sx1) * 0.5f, my = (sy0 + sy1) * 0.5f;
            const std::array<Uv, 4> face{{tex(sx0, sy0), tex(sx1, sy0), tex(sx1, sy1), tex(sx0, sy1)}};
            const std::array<Uv, 4> side{{tex(mx, sy0), tex(mx, sy0), tex(mx, sy1), tex(mx, sy1)}};
            const std::array<Uv, 4> cap{{tex(sx0, my), tex(sx1, my), tex(sx1, my), tex(sx0, my)}};
            AddSolidQuad(tile, {{at(x0, y0, h), at(x1, y0, h), at(x1, y1, h), at(x0, y1, h)}}, n, face);
            AddSolidQuad(tile, {{at(x0, y0, -h), at(x1, y0, -h), at(x1, y1, -h), at(x0, y1, -h)}}, nNeg, face);
            if (endCaps) {
                AddSolidQuad(tile, {{at(x0, y0, -h), at(x0, y0, h), at(x0, y1, h), at(x0, y1, -h)}}, xNeg, side);
                AddSolidQuad(tile, {{at(x1, y0, -h), at(x1, y0, h), at(x1, y1, h), at(x1, y1, -h)}}, xDir, side);
            }
            if (topCap) AddSolidQuad(tile, {{at(x0, y0, -h), at(x1, y0, -h), at(x1, y0, h), at(x0, y0, h)}}, yNeg, cap);
            if (bottomCap) AddSolidQuad(tile, {{at(x0, y1, -h), at(x1, y1, -h), at(x1, y1, h), at(x0, y1, h)}}, yDir, cap);
        };
        constexpr float kLast = static_cast<float>(kTileSize);
        for (const auto& rail : shape.rails) {
            const float y0 = static_cast<float>(rail.first), y1 = static_cast<float>(rail.second + 1);
            box(0.0f, kLast, y0, y1, shape.railDepth * 0.5f, 0.5f, kLast - 0.5f, y0 + 0.5f, y1 - 0.5f, true, true, true);
        }
        for (const RailingBar& bar : shape.bars) {
            const float x0 = static_cast<float>(bar.x0), x1 = static_cast<float>(bar.x1 + 1);
            const float y0 = static_cast<float>(bar.top), y1 = static_cast<float>(bar.bottom + 1);
            const float h = (std::min)(shape.barDepth, x1 - x0) * 0.5f;
            const float sx0 = x0 + 0.5f, sx1 = (std::max)(x0 + 0.5f, x1 - 0.5f);
            // A cap only where the bar's end shows: not under a finial, not at the tile's
            // edge (the bar carries on into the panel above or meets the ground), not
            // buried in a rail.
            auto inRail = [&](int row) {
                for (const auto& rail : shape.rails) if (row >= rail.first && row <= rail.second) return true;
                return false;
            };
            box(x0, x1, y0, y1, h, sx0, sx1, y0 + 0.5f, y1 - 0.5f, bar.finial.empty() && bar.top > 0 && !inRail(bar.top),
                bar.bottom < kTileSize - 1 && !inRail(bar.bottom), true);
            if (bar.finial.size() < 2) continue;
            // The finial: a square lathe of the outline, its point at the top. It samples
            // a band of the bar's own iron rather than its pixels, which on the upscaled
            // art are the blobs and specks this replaces.
            const float mid = (x0 + x1) * 0.5f;
            const float band0 = y0 + 0.5f, band1 = (std::min)(y1 - 0.5f, y0 + 6.5f);
            for (size_t i = 0; i + 1 < bar.finial.size(); ++i) {
                const float ya = bar.finial[i].first, ra = bar.finial[i].second;
                const float yb = bar.finial[i + 1].first, rb = bar.finial[i + 1].second;
                const float va = band0 + (band1 - band0) * static_cast<float>(i) / (bar.finial.size() - 1);
                const float vb = band0 + (band1 - band0) * static_cast<float>(i + 1) / (bar.finial.size() - 1);
                const std::array<Uv, 4> t{{tex(sx0, va), tex(sx1, va), tex(sx1, vb), tex(sx0, vb)}};
                AddSolidQuad(tile, {{at(mid - ra, ya, ra), at(mid + ra, ya, ra), at(mid + rb, yb, rb), at(mid - rb, yb, rb)}}, n, t);
                AddSolidQuad(tile, {{at(mid - ra, ya, -ra), at(mid + ra, ya, -ra), at(mid + rb, yb, -rb), at(mid - rb, yb, -rb)}}, nNeg, t);
                AddSolidQuad(tile, {{at(mid - ra, ya, -ra), at(mid - ra, ya, ra), at(mid - rb, yb, rb), at(mid - rb, yb, -rb)}}, xNeg, t);
                AddSolidQuad(tile, {{at(mid + ra, ya, -ra), at(mid + ra, ya, ra), at(mid + rb, yb, rb), at(mid + rb, yb, -rb)}}, xDir, t);
            }
        }
        return true;
    }

    std::vector<RailingShape> railingShapes_;
    std::vector<uint8_t> railingKnown_;
    std::set<std::tuple<int, int, int, int>> railingPanels_;

    // Whether the game lets this quad's colour key through. It does only for a
    // flat face - each face routine ORs 0x80 into the draw flags when the face
    // word has 0x1000 (gta2.exe!FUN_0046c2c0 and its siblings, the lid in
    // FUN_0046dfe0) - and for the back of a flat panel, which the game draws
    // with 0x1000 forced into the word (FUN_00471d60). Every other face goes
    // out without 0x80, and the original renderer then uploads the tile with
    // no colour key at all (d3ddll.dll!FUN_00e02810 keys on 0x380): palette
    // entry 0 is just a colour there, nearly black in every district.
    //
    // So a grille on a flat face is see-through, and the same tile on a solid
    // wall is not. Keying every face alike opened slits through solid walls,
    // and closing those by shape closed the grilles too.
    static int ColourKeyed(const Face& face, bool panelBack) {
        return (face.IsFlat() || panelBack) ? 1 : 0;
    }

    void FlattenOne(WorldMesh* out, int tile, bool keyed) const {
        const std::vector<Vertex>& quads = perTile_[keyed][tile];
        const std::vector<Vertex>& tris = perTileTriangle_[keyed][tile];
        if (quads.empty() && tris.empty()) return;

        TileBatch batch;
        batch.tile = tile;
        batch.vertexStart = static_cast<uint32_t>(out->vertices.size());
        batch.vertexCount = static_cast<uint32_t>(quads.size() + tris.size());
        batch.indexStart = static_cast<uint32_t>(out->indices.size());
        // The seal has no tile in the style and nothing to cut out of it.
        batch.needsAlphaTest =
            keyed && tile < style_.TileCount() && style_.GetTile(tile).hasTransparency;
        batch.doubleSided = keyed;
        for (const Vertex& v : quads) if (v.ny > 0.5f) { batch.lidFaces = true; break; }
        if (!batch.lidFaces) for (const Vertex& v : tris) if (v.ny > 0.5f) { batch.lidFaces = true; break; }

        out->vertices.insert(out->vertices.end(), quads.begin(), quads.end());
        // Corners arrive clockwise seen from outside, which is front-facing
        // under D3DCULL_CCW once the viewport flips Y.
        for (uint32_t quad = 0; quad < quads.size(); quad += 4) {
            const uint32_t base = batch.vertexStart + quad;
            out->indices.insert(out->indices.end(),
                                {base + 0, base + 1, base + 2, base + 0, base + 2, base + 3});
        }

        const uint32_t triStart = batch.vertexStart + static_cast<uint32_t>(quads.size());
        out->vertices.insert(out->vertices.end(), tris.begin(), tris.end());
        for (uint32_t tri = 0; tri < tris.size(); tri += 3) {
            const uint32_t base = triStart + tri;
            out->indices.insert(out->indices.end(), {base + 0, base + 1, base + 2});
        }

        batch.indexCount = static_cast<uint32_t>(out->indices.size()) - batch.indexStart;
        out->batches.push_back(batch);
    }

    const Style& style_;
    int streetMode_ = 0;
    std::vector<std::vector<Vertex>> street_;   // [tile], plain quads, street views only
    std::vector<std::vector<Vertex>> apron_;    // [tile], the apron past the edge, WRAP
    // Indexed [ColourKeyed][tile].
    std::vector<std::vector<Vertex>> perTile_[2];
    std::vector<std::vector<Vertex>> perTileTriangle_[2];
};

// Texture coordinates for a corner ramp's diagonal cut.
//
// A triangle is not oriented the way a quad is. A quad's four corners are
// permuted through the per-face-type table; gbh_DrawTriangle has only three, so
// the game hands it a fixed set of coordinates and then rewrites them from the
// face word's own flip and rotation bits - FUN_0046b710 for the peak shape,
// FUN_0046b910 for the chamfer. Neither goes near the wall tables.
//
// Both were decoded branch by branch and they agree on all eight cases, which
// are the symmetries of the square indexed by (rotation << 1) | flip:
//
//   0 identity        1 mirror u          2 quarter turn    3 transpose
//   4 half turn       5 mirror v          6 three quarters  7 anti-transpose
//
// The game does it by matching the three canonical texel values 0, 32 and
// 63.9999 and swapping them about, which is the same thing written out for the
// only coordinates a triangle can have. Doing it as arithmetic keeps it readable
// and gives the same answer.
Uv TriangleUv(const Face& face, float u, float v) {
    if (face.IsFlipped()) u = 1.0f - u;
    switch (face.Rotation()) {
        case 1: {  // a quarter turn
            const float was = u;
            u = v;
            v = 1.0f - was;
            break;
        }
        case 2:  // half
            u = 1.0f - u;
            v = 1.0f - v;
            break;
        case 3: {  // three quarters
            const float was = u;
            u = 1.0f - v;
            v = was;
            break;
        }
        default:
            break;
    }
    return Uv{UvAt(u), UvAt(v)};
}

// Texture coordinates anywhere on a wall, whatever the tile's orientation.
//
// A wall's four corners carry the coordinates the orientation table gave them,
// and the table is not the identity even for a face word with no flip and no
// rotation - the left wall's entry 0 is 0x23, a quarter turn. So the coordinates
// cannot be written out by hand from the geometry: they have to come from the
// table, and anything wanted at a point *between* the corners has to be
// interpolated in whatever frame the table left behind.
//
// That is what this is. The four corners are re-indexed by what they mean on the
// wall rather than by slot - along the wall, and up it - and At() reads any
// point out of that. A ramp then asks for its shortened top edge, and a corner
// ramp's diagonal cut asks for the midpoint of the top edge, without either of
// them needing to know which way the artwork ended up facing.
//
// This is what the sloped-wall path was missing. It wrote u from the geometry
// and v from the height, which reproduces the table exactly for a face word of
// zero - the uOrder tables below were chosen to make it so - and ignores flip
// and rotation entirely for anything else. Across the shipped districts 12% to
// 21% of ramp walls carry one, and 4% to 42% of corner-ramp cuts do, which is
// why the roofs in Downtown were the worst of it.
struct WallUvFrame {
    Uv corner[2][2];   // [along the wall 0 or 1][up it 0 or 1]

    Uv At(float along, float up) const {
        const Uv bottom{corner[0][0].u + (corner[1][0].u - corner[0][0].u) * along,
                        corner[0][0].v + (corner[1][0].v - corner[0][0].v) * along};
        const Uv top{corner[0][1].u + (corner[1][1].u - corner[0][1].u) * along,
                     corner[0][1].v + (corner[1][1].v - corner[0][1].v) * along};
        return Uv{bottom.u + (top.u - bottom.u) * up, bottom.v + (top.v - bottom.v) * up};
    }
};

// topSlots names the two slots carrying the wall's top edge and uOrder which end
// of the wall each slot sits at, which between them say what every slot means.
WallUvFrame WallFrame(const Face& face, const uint8_t (&table)[8], const int (&topSlots)[2],
                      const int (&uOrder)[4]) {
    const std::array<Uv, 4> uv = FaceUvs(face, table);
    WallUvFrame frame{};
    for (int slot = 0; slot < 4; ++slot) {
        const int up = (slot == topSlots[0] || slot == topSlots[1]) ? 1 : 0;
        frame.corner[uOrder[slot]][up] = uv[slot];
    }
    return frame;
}

// A wall a ramp has shortened shows the *bottom* of its tile with the top
// cropped off, rather than the whole tile squashed into a shorter quad
// (gta2.exe!FUN_0046c2c0, which stores 63.9999 - height * 64 into the vertex's
// own coordinate and takes the orientation flags from the face word as usual).
// So each top corner is simply the point `height` of the way up the wall.
std::array<Uv, 4> SlopedWallUvs(const Face& face, const uint8_t (&table)[8],
                                const int (&topSlots)[2], const float (&topHeights)[2],
                                const int (&uOrder)[4]) {
    const WallUvFrame frame = WallFrame(face, table, topSlots, uOrder);
    std::array<Uv, 4> uv;
    for (int slot = 0; slot < 4; ++slot) {
        float up = 0.0f;
        if (slot == topSlots[0]) up = topHeights[0];
        else if (slot == topSlots[1]) up = topHeights[1];
        uv[slot] = frame.At(static_cast<float>(uOrder[slot]), up);
    }
    return uv;
}

// A flat face is a zero-thickness panel rather than one side of a solid block,
// so when one of an opposing pair is flat the game puts *both* tiles on that one
// panel, one facing each way (FUN_00471d60 -> FUN_00470060 and its three
// siblings, and the same again for partial blocks in FUN_00470be0 and its
// siblings). Drawing only the flat one leaves the panel blank from behind, which
// is where the gaps in fences and hoardings came from.
//
// The game asks whether the opposite face is there by its whole word, not its
// tile, so a flat flag with no tile (0x1000) still makes a panel. Maps use
// exactly that to hang a sign or graffiti on the far edge of an empty block,
// against the neighbour's wall: the tile is drawn on the far plane and nothing
// on its own edge.
bool SoloFace(const Face& face, const Face& opposite) {
    return static_cast<bool>(face) &&
           (opposite.raw == 0 || !opposite.IsFlat() || face.IsFlat());
}

// Whenever the opposite face is flat, its panel also carries this face's tile on
// its back. With both flat that gives four quads - two panels, each double
// sided - which is exactly what the game emits.
bool PanelBack(const Face& face, const Face& opposite) {
    return static_cast<bool>(face) && opposite.raw != 0 && opposite.IsFlat();
}

// A panel with no tile of its own is only there to carry this one onto a plane
// the neighbour's wall (or its flat face) already occupies. The game paints it
// last; here it is lifted clear of that plane instead.
float DecalPush(const Face& opposite) { return opposite ? 0.0f : 2.0f * kFlatFaceOffset; }

// A diagonal block is a triangular prism: two of its four side walls stay put,
// the third spans the cut, and the lid becomes a triangle. Which is which comes
// straight from the game's dispatch (gta2.exe!FUN_0046edd0), and the lid corner
// it drops agrees independently with the slot rotation FUN_0046dfe0 applies.
void AddDiagonalBlock(MeshBuilder* builder, const Block& block, int slopeType, float xWest,
                      float xEast, float zNorth, float zSouth, float base) {
    const float top = base + 1.0f;
    const Vec3 nw{xWest, top, zNorth}, ne{xEast, top, zNorth};
    const Vec3 se{xEast, top, zSouth}, sw{xWest, top, zSouth};
    const Vec3 nwB{xWest, base, zNorth}, neB{xEast, base, zNorth};
    const Vec3 seB{xEast, base, zSouth}, swB{xWest, base, zSouth};

    constexpr float kDiag = 0.70710678f;

    // face  = the block word whose tile the diagonal wall wears
    // aTop/aBase, bTop/bBase = the two ends of the cut
    // leftOrder = the cut is drawn with the left wall's slot order, not the right's
    const Face* face = nullptr;
    Vec3 aTop{}, aBase{}, bTop{}, bBase{}, normal{};
    bool leftOrder = true;
    std::array<Vec3, 4> lid{};
    const uint8_t (*lidTable)[8] = &kDiagLidDropNw;

    switch (slopeType) {
        case 45:  // solid to the east and south, cut faces north-west
            face = &block.left;
            aTop = ne; aBase = neB; bTop = sw; bBase = swB;
            normal = {-kDiag, 0.0f, kDiag};
            leftOrder = true;
            lid = {ne, se, sw, ne};
            lidTable = &kDiagLidDropNw;
            if (block.right) builder->AddFace(block.right, {{ne, neB, seB, se}}, {1.0f, 0.0f, 0.0f}, kRightFlags);
            if (block.bottom) builder->AddFace(block.bottom, {{sw, se, seB, swB}}, {0.0f, 0.0f, -1.0f}, kBottomFlags);
            break;
        case 46:  // solid to the west and south, cut faces north-east
            face = &block.right;
            aTop = nw; aBase = nwB; bTop = se; bBase = seB;
            normal = {kDiag, 0.0f, kDiag};
            leftOrder = false;
            lid = {nw, se, se, sw};
            lidTable = &kDiagLidDropNeSw;
            if (block.left) builder->AddFace(block.left, {{nwB, nw, sw, swB}}, {-1.0f, 0.0f, 0.0f}, kLeftFlags);
            if (block.bottom) builder->AddFace(block.bottom, {{sw, se, seB, swB}}, {0.0f, 0.0f, -1.0f}, kBottomFlags);
            break;
        case 47:  // solid to the east and north, cut faces south-west
            face = &block.left;
            aTop = nw; aBase = nwB; bTop = se; bBase = seB;
            normal = {-kDiag, 0.0f, -kDiag};
            leftOrder = true;
            lid = {nw, ne, se, nw};
            lidTable = &kDiagLidDropNeSw;
            if (block.right) builder->AddFace(block.right, {{ne, neB, seB, se}}, {1.0f, 0.0f, 0.0f}, kRightFlags);
            if (block.top) builder->AddFace(block.top, {{nwB, neB, ne, nw}}, {0.0f, 0.0f, 1.0f}, kTopFlags);
            break;
        default:  // 48: solid to the west and north, cut faces south-east
            face = &block.right;
            aTop = ne; aBase = neB; bTop = sw; bBase = swB;
            normal = {kDiag, 0.0f, -kDiag};
            leftOrder = false;
            lid = {sw, nw, ne, sw};
            lidTable = &kDiagLidDropSe;
            if (block.left) builder->AddFace(block.left, {{nwB, nw, sw, swB}}, {-1.0f, 0.0f, 0.0f}, kLeftFlags);
            if (block.top) builder->AddFace(block.top, {{nwB, neB, ne, nw}}, {0.0f, 0.0f, 1.0f}, kTopFlags);
            break;
    }

    if (face && *face) {
        const std::array<Vec3, 4> corners =
            leftOrder ? std::array<Vec3, 4>{{aBase, aTop, bTop, bBase}}
                      : std::array<Vec3, 4>{{aTop, aBase, bBase, bTop}};
        builder->AddFace(*face, corners, normal, leftOrder ? kLeftFlags : kRightFlags);
    }
    if (block.lid) builder->AddFace(block.lid, lid, {0.0f, 1.0f, 0.0f}, *lidTable);
}

// Slope types 49-52: corner ramps, reached through the dispatcher FUN_0046ee40.
//
// There are *two* shapes per type, chosen by whether the lid tile is 0x3FF, and
// they are not rotations of one another:
//
//   with a lid (0x0046E910 and its siblings) - two walls whole, a triangular
//     lid over three corners, and the fourth chamfered off by a triangle
//     running from the diagonal at the top down to that corner's foot;
//   without one (0x0046E490 and its siblings) - the opposite half of the cell:
//     a peak at one corner, the diagonal lying on the floor, and the two walls
//     sloping away from the peak.
//
// Type 49 was decoded from the disassembly at 0x0046E910; the lidless shape was
// confirmed against the world coordinates the running game computed for a type
// 52 block. Four blocks in five are the lidless one (81 of 99 in `wil`), so
// building only the lidded shape put nearly every corner piece in upside down.
void AddCornerRampBlock(MeshBuilder* builder, const Block& block, int slopeType, float xWest,
                        float xEast, float zNorth, float zSouth, float base) {
    // Corner order is north-west, north-east, south-east, south-west.
    const float cornerX[4] = {xWest, xEast, xEast, xWest};
    const float cornerZ[4] = {zNorth, zNorth, zSouth, zSouth};
    auto at = [&](int corner, float height) {
        return Vec3{cornerX[corner], base + height, cornerZ[corner]};
    };

    // The corner each type is built around, and with it the two walls that stay
    // solid - always the pair facing away from it. The tile for the cut comes
    // from the west face for a western corner, the east face for an eastern one.
    static const int kSpecial[4] = {0, 1, 3, 2};  // types 49, 50, 51, 52
    const int special = kSpecial[slopeType - 49];
    const bool westCorner = special == 0 || special == 3;
    const Face& cutFace = westCorner ? block.left : block.right;

    const bool lidless = block.lid.Tile() == 0x3FF;
    const int peak = (special + 2) & 3;

    // Corner heights: whole all round for the lidded shape; for the other one
    // raised at the peak and flat elsewhere, which is what the game expresses by
    // sending its two walls through the ramp path with a single step.
    float h[4];
    for (int corner = 0; corner < 4; ++corner) {
        h[corner] = lidless ? (corner == peak ? 1.0f : 0.0f) : 1.0f;
    }

    // A wall a slope has shortened crops its texture rather than squashing it,
    // exactly as an ordinary ramp does.
    auto wall = [&](const Face& face, const std::array<Vec3, 4>& corners, Vec3 normal,
                    const uint8_t (&table)[8], const int (&topSlots)[2], const float (&heights)[2],
                    const int (&uOrder)[4]) {
        if (!face) return;
        if (heights[0] < 1.0f || heights[1] < 1.0f) {
            builder->AddFaceUv(face, corners, normal,
                               SlopedWallUvs(face, table, topSlots, heights, uOrder));
        } else {
            builder->AddFace(face, corners, normal, table);
        }
    };

    const int leftTop[2] = {1, 2};
    const int leftU[4] = {0, 0, 1, 1};
    const int rightTop[2] = {0, 3};
    const int rightU[4] = {1, 1, 0, 0};
    const int northTop[2] = {2, 3};
    const int southTop[2] = {0, 1};
    const int alongX[4] = {0, 1, 1, 0};

    if (westCorner) {  // 49 and 51 keep the east wall
        const float heights[2] = {h[1], h[2]};
        wall(block.right, {{at(1, h[1]), at(1, 0.0f), at(2, 0.0f), at(2, h[2])}},
             {1.0f, 0.0f, 0.0f}, kRightFlags, rightTop, heights, rightU);
    } else {  // 50 and 52 keep the west wall
        const float heights[2] = {h[0], h[3]};
        wall(block.left, {{at(0, 0.0f), at(0, h[0]), at(3, h[3]), at(3, 0.0f)}},
             {-1.0f, 0.0f, 0.0f}, kLeftFlags, leftTop, heights, leftU);
    }
    if (special == 0 || special == 1) {  // 49 and 50 keep the south wall
        const float heights[2] = {h[3], h[2]};
        wall(block.bottom, {{at(3, h[3]), at(2, h[2]), at(2, 0.0f), at(3, 0.0f)}},
             {0.0f, 0.0f, -1.0f}, kBottomFlags, southTop, heights, alongX);
    } else {  // 51 and 52 keep the north wall
        const float heights[2] = {h[1], h[0]};
        wall(block.top, {{at(0, 0.0f), at(1, 0.0f), at(1, h[1]), at(0, h[0])}},
             {0.0f, 0.0f, 1.0f}, kTopFlags, northTop, heights, alongX);
    }

    if (cutFace) {
        // The cut runs diagonally across the cell and the tile runs with it: one
        // end of the diagonal at each end of the tile, the odd corner at its
        // middle. 42% of the corner ramps in Downtown carry a flip or a rotation,
        // which is why its hip roofs had the eaves course running up the hip.
        if (lidless) {
            // A peak: one corner at the top, the diagonal lying on the floor.
            // The game's own coordinates for it are (32,0) (64,64) (0,64).
            builder->AddTriangle(
                cutFace, {at(peak, 1.0f), at((peak + 1) & 3, 0.0f), at((peak + 3) & 3, 0.0f)},
                {TriangleUv(cutFace, 0.5f, 0.0f), TriangleUv(cutFace, 1.0f, 1.0f),
                 TriangleUv(cutFace, 0.0f, 1.0f)});
        } else {
            // A chamfer: the diagonal along the top, dropping to the one corner.
            builder->AddTriangle(
                cutFace,
                {at((special + 1) & 3, 1.0f), at(special, 0.0f), at((special + 3) & 3, 1.0f)},
                {TriangleUv(cutFace, 0.0f, 0.0f), TriangleUv(cutFace, 0.5f, 1.0f),
                 TriangleUv(cutFace, 1.0f, 0.0f)});
        }
    }

    if (!lidless && block.lid) {
        // The lid is the ordinary quad with one corner folded onto another,
        // which is how the game turns it into a triangle (FUN_0046dfe0, the
        // view-rotation states 0 to 3).
        static const int kLidSlots[4][4] = {{1, 2, 3, 1},   // 49, drops north-west
                                            {0, 2, 2, 3},   // 50, drops north-east
                                            {0, 1, 2, 0},   // 51, drops south-west
                                            {3, 0, 1, 3}};  // 52, drops south-east
        const uint8_t(*lidTable)[8] = slopeType == 49   ? &kDiagLidDropNw
                                      : slopeType == 52 ? &kDiagLidDropSe
                                                        : &kDiagLidDropNeSw;
        const int* slots = kLidSlots[slopeType - 49];
        builder->AddFace(
            block.lid,
            {{at(slots[0], 1.0f), at(slots[1], 1.0f), at(slots[2], 1.0f), at(slots[3], 1.0f)}},
            {0.0f, 1.0f, 0.0f}, *lidTable);
    }
}

// Slope types 53-61: a plain box occupying only part of its cell. Which part is
// decided by two cut fractions the game holds at 0x006634FC and 0x006635B8, and
// FUN_00471c30 spells the footprints out by passing them as the wall extents -
// 53 to 56 are slabs against each edge, 57 to 60 are corner posts, 61 is a post
// in the middle. Each face shows the matching part of its tile rather than the
// whole of it squeezed down; that the game draws the *unshortened* walls with
// the ordinary full-tile routine is what confirms the reading.
void AddPartialBlock(MeshBuilder* builder, const Block& block, int slopeType,
                     const PartialCuts& cuts, float bx, float zNorth, float base) {
    const float lo = cuts.low;
    const float hi = cuts.high;
    float x0 = 0.0f, x1 = 1.0f, y0 = 0.0f, y1 = 1.0f;
    switch (slopeType) {
        case 53: x1 = lo; break;                        // slab against the west edge
        case 54: x0 = hi; break;                        // east
        case 55: y1 = lo; break;                        // north
        case 56: y0 = hi; break;                        // south
        case 57: x1 = lo; y1 = lo; break;               // north-west post
        case 58: x0 = hi; y1 = lo; break;               // north-east
        case 59: x0 = hi; y0 = hi; break;               // south-east
        case 60: x1 = lo; y0 = hi; break;               // south-west
        default: x0 = lo; x1 = hi; y0 = lo; y1 = hi; break;  // 61, centred post
    }

    const float xWest = bx + x0;
    const float xEast = bx + x1;
    // Map rows run north to south, so a larger y is further south, which is a
    // smaller z once the row is mirrored.
    const float zN = zNorth - y0;
    const float zS = zNorth - y1;
    const float top = base + 1.0f;

    if (block.lid) {
        builder->AddFaceUv(block.lid,
                           {{{xWest, top, zN}, {xEast, top, zN}, {xEast, top, zS}, {xWest, top, zS}}},
                           {0.0f, 1.0f, 0.0f},
                           FaceUvsPart(block.lid, kLidFlags, x0, x1, y0, y1));
    }
    // Only the axis a face runs along is cropped; its height is always whole.
    // The same pairing as a whole block (SoloFace, PanelBack), on the
    // footprint's own planes.
    const std::array<Uv, 4> leftUv = FaceUvsPart(block.left, kLeftFlags, 0.0f, 1.0f, y0, y1);
    const std::array<Uv, 4> rightUv = FaceUvsPart(block.right, kRightFlags, 0.0f, 1.0f, y0, y1);
    const std::array<Uv, 4> topUv = FaceUvsPart(block.top, kTopFlags, x0, x1, 0.0f, 1.0f);
    const std::array<Uv, 4> bottomUv = FaceUvsPart(block.bottom, kBottomFlags, x0, x1, 0.0f, 1.0f);
    if (SoloFace(block.left, block.right)) {
        builder->AddFaceUv(block.left,
                           {{{xWest, base, zN}, {xWest, top, zN}, {xWest, top, zS}, {xWest, base, zS}}},
                           {-1.0f, 0.0f, 0.0f}, leftUv);
    }
    if (SoloFace(block.right, block.left)) {
        builder->AddFaceUv(block.right,
                           {{{xEast, top, zN}, {xEast, base, zN}, {xEast, base, zS}, {xEast, top, zS}}},
                           {1.0f, 0.0f, 0.0f}, rightUv);
    }
    if (SoloFace(block.top, block.bottom)) {
        builder->AddFaceUv(block.top,
                           {{{xWest, base, zN}, {xEast, base, zN}, {xEast, top, zN}, {xWest, top, zN}}},
                           {0.0f, 0.0f, 1.0f}, topUv);
    }
    if (SoloFace(block.bottom, block.top)) {
        builder->AddFaceUv(block.bottom,
                           {{{xWest, top, zS}, {xEast, top, zS}, {xEast, base, zS}, {xWest, base, zS}}},
                           {0.0f, 0.0f, -1.0f}, bottomUv);
    }
    // The backs of the panels, in each tile's own slot order - see AddBlock.
    if (PanelBack(block.right, block.left)) {
        builder->AddFaceUv(block.right,
                           {{{xWest, top, zN}, {xWest, base, zN}, {xWest, base, zS}, {xWest, top, zS}}},
                           {1.0f, 0.0f, 0.0f}, rightUv, DecalPush(block.left), true);
    }
    if (PanelBack(block.left, block.right)) {
        builder->AddFaceUv(block.left,
                           {{{xEast, base, zN}, {xEast, top, zN}, {xEast, top, zS}, {xEast, base, zS}}},
                           {-1.0f, 0.0f, 0.0f}, leftUv, DecalPush(block.right), true);
    }
    if (PanelBack(block.bottom, block.top)) {
        builder->AddFaceUv(block.bottom,
                           {{{xWest, top, zN}, {xEast, top, zN}, {xEast, base, zN}, {xWest, base, zN}}},
                           {0.0f, 0.0f, -1.0f}, bottomUv, DecalPush(block.top), true);
    }
    if (PanelBack(block.top, block.bottom)) {
        builder->AddFaceUv(block.top,
                           {{{xWest, base, zS}, {xEast, base, zS}, {xEast, top, zS}, {xWest, top, zS}}},
                           {0.0f, 0.0f, 1.0f}, topUv, DecalPush(block.bottom), true);
    }
}

void AddBlock(MeshBuilder* builder, const Block& block, const SlopeInfo& slope,
              const PartialCuts& cuts, int bx, int by, int level) {
    if (block.lid && block.GroundType() == 1) builder->MarkRoadLid(block.lid.Tile());   // the street views' tone match
    // Map rows run north to south, so the row index is mirrored into +Z-is-north.
    // Keeping north positive makes the world frame agree with the left-handed
    // view frame; sharing the sign would mirror the whole city.
    const float xWest = static_cast<float>(bx);
    const float xEast = xWest + 1.0f;
    const float zSouth = static_cast<float>(kMapHeight - by - 1);
    const float zNorth = zSouth + 1.0f;
    const float base = static_cast<float>(level);

    const int slopeType = block.SlopeType();
    if (slopeType >= 45 && slopeType <= 48) {
        AddDiagonalBlock(builder, block, slopeType, xWest, xEast, zNorth, zSouth, base);
        return;
    }
    if (slopeType >= 49 && slopeType <= 52) {
        AddCornerRampBlock(builder, block, slopeType, xWest, xEast, zNorth, zSouth, base);
        return;
    }
    if (slopeType >= 53 && slopeType <= 61) {
        AddPartialBlock(builder, block, slopeType, cuts, xWest, zNorth, base);
        return;
    }

    const CornerHeights h = LidHeights(slope);
    const float yNW = base + h[0];
    const float yNE = base + h[1];
    const float ySE = base + h[2];
    const float ySW = base + h[3];
    const bool ramp = slope.direction >= 1 && slope.direction <= 4 && slope.steps != 0;

    // Vertex slots below follow the original's own ordering per face, recovered
    // from which slot each projection call writes.
    if (block.lid) {
        builder->AddFace(block.lid,
                         {{{xWest, yNW, zNorth},    // v0 (x,   y)
                           {xEast, yNE, zNorth},    // v1 (x+1, y)
                           {xEast, ySE, zSouth},    // v2 (x+1, y+1)
                           {xWest, ySW, zSouth}}},  // v3 (x,   y+1)
                         {0.0f, 1.0f, 0.0f}, kLidFlags);
    }

    const std::array<Vec3, 4> leftCorners = {{{xWest, base, zNorth},   // v0 bottom (x, y)
                                              {xWest, yNW, zNorth},    // v1 top    (x, y)
                                              {xWest, ySW, zSouth},    // v2 top    (x, y+1)
                                              {xWest, base, zSouth}}}; // v3 bottom (x, y+1)
    const std::array<Vec3, 4> rightCorners = {{{xEast, yNE, zNorth},    // v0 top    (x+1, y)
                                               {xEast, base, zNorth},   // v1 bottom (x+1, y)
                                               {xEast, base, zSouth},   // v2 bottom (x+1, y+1)
                                               {xEast, ySE, zSouth}}};  // v3 top    (x+1, y+1)
    const std::array<Vec3, 4> topCorners = {{{xWest, base, zNorth},   // v0 bottom (x,   y)
                                             {xEast, base, zNorth},   // v1 bottom (x+1, y)
                                             {xEast, yNE, zNorth},    // v2 top    (x+1, y)
                                             {xWest, yNW, zNorth}}};  // v3 top    (x,   y)
    const std::array<Vec3, 4> bottomCorners = {{{xWest, ySW, zSouth},    // v0 top    (x,   y+1)
                                                {xEast, ySE, zSouth},    // v1 top    (x+1, y+1)
                                                {xEast, base, zSouth},   // v2 bottom (x+1, y+1)
                                                {xWest, base, zSouth}}}; // v3 bottom (x, y+1)

    constexpr Vec3 kWest{-1.0f, 0.0f, 0.0f};
    constexpr Vec3 kEast{1.0f, 0.0f, 0.0f};
    constexpr Vec3 kNorth{0.0f, 0.0f, 1.0f};
    constexpr Vec3 kSouth{0.0f, 0.0f, -1.0f};

    // Only a wall that a ramp actually shortened needs hand-written texture
    // coordinates; every full-height wall keeps the table-driven path, which is
    // verified against the original renderer.
    auto addWall = [&](const Face& face, const std::array<Vec3, 4>& corners, Vec3 normal,
                       const uint8_t (&table)[8], const int (&topSlots)[2],
                       const float (&topHeights)[2], const int (&uOrder)[4]) {
        if (ramp && (topHeights[0] < 1.0f || topHeights[1] < 1.0f)) {
            builder->AddFaceUv(face, corners, normal,
                               SlopedWallUvs(face, table, topSlots, topHeights, uOrder));
        } else {
            builder->AddFace(face, corners, normal, table);
        }
    };

    // Slot 1 and 2 hold the left wall's top edge; 0 and 3 the right wall's.
    const int leftTop[2] = {1, 2};
    const float leftHeights[2] = {h[0], h[3]};
    const int leftU[4] = {0, 0, 1, 1};
    const int rightTop[2] = {0, 3};
    const float rightHeights[2] = {h[1], h[2]};
    const int rightU[4] = {1, 1, 0, 0};
    const int northTop[2] = {2, 3};
    const float northHeights[2] = {h[1], h[0]};
    const int northU[4] = {0, 1, 1, 0};
    const int southTop[2] = {0, 1};
    const float southHeights[2] = {h[3], h[2]};
    const int southU[4] = {0, 1, 1, 0};

    if (SoloFace(block.left, block.right)) {
        addWall(block.left, leftCorners, kWest, kLeftFlags, leftTop, leftHeights, leftU);
    }
    if (SoloFace(block.right, block.left)) {
        addWall(block.right, rightCorners, kEast, kRightFlags, rightTop, rightHeights, rightU);
    }
    if (SoloFace(block.top, block.bottom)) {
        addWall(block.top, topCorners, kNorth, kTopFlags, northTop, northHeights, northU);
    }
    if (SoloFace(block.bottom, block.top)) {
        addWall(block.bottom, bottomCorners, kSouth, kBottomFlags, southTop, southHeights, southU);
    }

    // The far side of a flat panel: the opposite face's tile, on the panel's own
    // plane, facing the other way.
    //
    // The corners have to be in the slot order belonging to the face whose tile
    // is being drawn, not the one whose plane it borrows. Each orientation table
    // is written against its own face's slot order, and left and right number
    // their corners in opposite directions - left starts at the foot, right at
    // the top - so handing one the other's ordering turns the artwork upside
    // down. The game keeps them straight by giving each side its own helper:
    // FUN_00470060 draws the left tile in left order, FUN_00470250 the right
    // tile in right order.
    if (PanelBack(block.right, block.left)) {
        builder->AddFace(block.right,
                         {{{xWest, yNW, zNorth},     // v0 top    (x, y)
                           {xWest, base, zNorth},    // v1 bottom (x, y)
                           {xWest, base, zSouth},    // v2 bottom (x, y+1)
                           {xWest, ySW, zSouth}}},   // v3 top    (x, y+1)
                         kEast, kRightFlags, DecalPush(block.left), true);
    }
    if (PanelBack(block.left, block.right)) {
        builder->AddFace(block.left,
                         {{{xEast, base, zNorth},    // v0 bottom (x+1, y)
                           {xEast, yNE, zNorth},     // v1 top    (x+1, y)
                           {xEast, ySE, zSouth},     // v2 top    (x+1, y+1)
                           {xEast, base, zSouth}}},  // v3 bottom (x+1, y+1)
                         kWest, kLeftFlags, DecalPush(block.right), true);
    }
    if (PanelBack(block.bottom, block.top)) {
        builder->AddFace(block.bottom,
                         {{{xWest, yNW, zNorth},     // v0 top    (x,   y)
                           {xEast, yNE, zNorth},     // v1 top    (x+1, y)
                           {xEast, base, zNorth},    // v2 bottom (x+1, y)
                           {xWest, base, zNorth}}},  // v3 bottom (x,   y)
                         kSouth, kBottomFlags, DecalPush(block.top), true);
    }
    if (PanelBack(block.top, block.bottom)) {
        builder->AddFace(block.top,
                         {{{xWest, base, zSouth},    // v0 bottom (x,   y+1)
                           {xEast, base, zSouth},    // v1 bottom (x+1, y+1)
                           {xEast, ySE, zSouth},     // v2 top    (x+1, y+1)
                           {xWest, ySW, zSouth}}},   // v3 top    (x,   y+1)
                         kNorth, kTopFlags, DecalPush(block.bottom), true);
    }
}

}  // namespace

namespace {
bool g_seal = true;
float g_waterUvBlocks = kDefaultWaterUvBlocks;
float g_riverbedDepth = kDefaultRiverbedDepth;

// See SetRiverbedDepth.
void AddRiverbed(MeshBuilder* builder, const Map& map, const Style& style, float depth) {
    constexpr float kNone = 1e9f;
    std::vector<float> bed(static_cast<size_t>(kMapWidth) * kMapHeight, kNone);
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            for (size_t i = 0; i < column.blocks.size(); ++i) {
                const uint32_t index = column.blocks[i];
                if (index >= map.BlockCount()) continue;
                const Block& block = map.BlockAt(index);
                if (!block.lid || !style.IsWaterTile(block.lid.Tile())) continue;
                const float floor =
                    static_cast<float>(column.offset + static_cast<int>(i)) + 1.0f - depth;
                for (int dy = -kRiverbedPad; dy <= kRiverbedPad; ++dy) {
                    for (int dx = -kRiverbedPad; dx <= kRiverbedPad; ++dx) {
                        const int cx = x + dx, cy = y + dy;
                        if (cx < 0 || cy < 0 || cx >= kMapWidth || cy >= kMapHeight) continue;
                        float& at = bed[static_cast<size_t>(cy) * kMapWidth + cx];
                        if (floor < at) at = floor;
                    }
                }
            }
        }
    }
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const float h = bed[static_cast<size_t>(y) * kMapWidth + x];
            if (h >= kNone) continue;
            // The same mirroring as AddBlock: map row y is the cell from
            // kMapHeight - y - 1 to kMapHeight - y in Z.
            const float xWest = static_cast<float>(x);
            const float zSouth = static_cast<float>(kMapHeight - y - 1);
            builder->AddRiverbedQuad({{{xWest, h, zSouth + 1.0f},
                                       {xWest + 1.0f, h, zSouth + 1.0f},
                                       {xWest + 1.0f, h, zSouth},
                                       {xWest, h, zSouth}}});
        }
    }
}
}  // namespace

namespace {
// The ground under arches, gates, arcades and porches.
//
// A column's `offset` blocks are not stored in the map: GTA2 only ever looked
// down on the city, and whatever lies under a column's first stored block is
// never seen from above, so the engine keeps it as implicit solid ground (the
// player walks through the Avalon gate at street level, over a column whose
// first stored block is the air under the arch). From a street-level camera
// that ground is in plain view, and without a quad for it the seal showed
// through: a fog- or sky-coloured hole in the pavement beside every gateway.
// So where a column's first stored block has no lid of its own, its base is
// closed with a flat quad at the offset height, textured with the lid a
// neighbouring column shows at that same height (the pavement runs on under
// the arch), nearest first; and where a neighbouring column's base is lower,
// the exposed side of the base gets the wall tile the column shows on that
// side higher up. Every such column in the shipped maps has a lid higher up,
// so the top-down view is unchanged: the roof still hides all of it.
int NeighbourLidTile(const Map& map, int x, int y, int level) {
    // A flat lid at exactly this height, nearest first; failing that (a step
    // inside a porch, say) the lowest flat lid of the nearest column at any
    // height, so a step is at least paved like the ground beside it.
    for (int pass = 0; pass < 2; ++pass) {
        for (int radius = 1; radius <= 3; ++radius) {
            for (int dy = -radius; dy <= radius; ++dy) {
                for (int dx = -radius; dx <= radius; ++dx) {
                    if ((std::max)(std::abs(dx), std::abs(dy)) != radius) continue;
                    const int cx = x + dx, cy = y + dy;
                    if (cx < 0 || cy < 0 || cx >= kMapWidth || cy >= kMapHeight) continue;
                    const Column& column = map.ColumnAt(cx, cy);
                    for (size_t i = 0; i < column.blocks.size(); ++i) {
                        if (pass == 0 && column.offset + static_cast<int>(i) != level - 1) continue;
                        const uint32_t index = column.blocks[i];
                        if (index >= map.BlockCount()) continue;
                        const Block& block = map.BlockAt(index);
                        if (!block.lid || block.SlopeType() != 0 || block.lid.IsFlat()) continue;
                        return block.lid.Tile();
                    }
                }
            }
        }
    }
    return 0;
}

// The side of a column's implicit base, where a neighbouring column's base is
// lower: the first face the column shows on that side higher up (the parapet
// wall continues down), else the floor tile.
int ImplicitSideTile(const Map& map, const Column& column, int side, int floorTile) {
    for (uint32_t index : column.blocks) {
        if (index >= map.BlockCount()) continue;
        const Block& block = map.BlockAt(index);
        const Face& face = side == 0 ? block.left : side == 1 ? block.right : side == 2 ? block.top : block.bottom;
        if (face) return face.Tile();
    }
    return floorTile;
}

void AddImplicitFloors(MeshBuilder* builder, const Map& map) {
    static const int kSideDx[4] = {-1, 1, 0, 0};   // left, right, top (north), bottom (south)
    static const int kSideDy[4] = {0, 0, -1, 1};
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            if (column.offset == 0 || column.blocks.empty()) continue;
            const uint32_t first = column.blocks[0];
            if (first >= map.BlockCount()) continue;
            const int floorTile = NeighbourLidTile(map, x, y, column.offset);
            const float h = static_cast<float>(column.offset);
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;
            if (!map.BlockAt(first).lid && floorTile != 0) {
                builder->AddFloorQuad(floorTile, {{{xWest, h, zNorth}, {xEast, h, zNorth}, {xEast, h, zSouth}, {xWest, h, zSouth}}});
            }
            for (int side = 0; side < 4; ++side) {
                const int nx = x + kSideDx[side], ny = y + kSideDy[side];
                if (nx < 0 || ny < 0 || nx >= kMapWidth || ny >= kMapHeight) continue;
                const int low = map.ColumnAt(nx, ny).offset;
                if (low >= column.offset) continue;
                const int tile = ImplicitSideTile(map, column, side, floorTile);
                if (tile == 0) continue;
                for (int level = low; level < column.offset; ++level) {
                    const float y0 = static_cast<float>(level), y1 = y0 + 1.0f;
                    std::array<Vec3, 4> corners;
                    Vec3 normal;
                    switch (side) {
                        case 0: corners = {{{xWest, y1, zNorth}, {xWest, y1, zSouth}, {xWest, y0, zSouth}, {xWest, y0, zNorth}}}; normal = {-1.0f, 0.0f, 0.0f}; break;
                        case 1: corners = {{{xEast, y1, zSouth}, {xEast, y1, zNorth}, {xEast, y0, zNorth}, {xEast, y0, zSouth}}}; normal = {1.0f, 0.0f, 0.0f}; break;
                        case 2: corners = {{{xEast, y1, zNorth}, {xWest, y1, zNorth}, {xWest, y0, zNorth}, {xEast, y0, zNorth}}}; normal = {0.0f, 0.0f, 1.0f}; break;
                        default: corners = {{{xWest, y1, zSouth}, {xEast, y1, zSouth}, {xEast, y0, zSouth}, {xWest, y0, zSouth}}}; normal = {0.0f, 0.0f, -1.0f}; break;
                    }
                    builder->AddSideQuad(tile, corners, normal);
                }
            }
        }
    }
}

// The second kind of face the top-down renderer never needed: surfaces under
// something else. (a) A road or pavement that runs under a bridge or an
// overhang is stored as a block with a ground type and road arrows but no lid,
// because from above the deck hides it; the game walks and drives on its top
// all the same. (b) The underside of that deck, and of every overhang whose
// column stores an empty block beneath it, has no face either (GTA2 blocks
// have no bottom). From the street both are in plain view and showed the sky
// through the world. The road gets a lid at its top, textured like the lid a
// neighbouring column shows at that height; the deck gets an underside at its
// base, textured with a side face of the deck block, else its lid. All of it is
// hidden from above by the deck itself, so the classic view is unchanged.
int DeckUndersideTile(const Block& block) {
    for (const Face* face : {&block.left, &block.right, &block.top, &block.bottom}) {
        if (*face && !face->IsFlat()) return face->Tile();
    }
    return block.lid.Tile();
}

void AddHiddenSurfaces(MeshBuilder* builder, const Map& map) {
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;
            for (size_t i = 0; i < column.blocks.size(); ++i) {
                const uint32_t index = column.blocks[i];
                if (index >= map.BlockCount()) continue;
                const Block& block = map.BlockAt(index);
                const int level = column.offset + static_cast<int>(i);
                const Block* above = nullptr;
                if (i + 1 < column.blocks.size() && column.blocks[i + 1] < map.BlockCount()) above = &map.BlockAt(column.blocks[i + 1]);
                const Block* below = nullptr;
                if (i > 0 && column.blocks[i - 1] < map.BlockCount()) below = &map.BlockAt(column.blocks[i - 1]);

                // (a) a lidless road or pavement with something built over it,
                // and nothing lidded directly under it that could be the real
                // surface instead.
                const bool groundBlock = !block.lid && block.SlopeType() == 0 && (block.GroundType() != 0 || block.arrows != 0);
                const bool covered = above && (above->lid || above->left || above->right || above->top || above->bottom);
                const bool belowIsSurface = below && (below->lid || below->SlopeType() != 0);
                if (groundBlock && covered && !belowIsSurface) {
                    const int tile = NeighbourLidTile(map, x, y, level + 1);
                    if (tile != 0) {
                        const float h = static_cast<float>(level + 1);
                        builder->AddFloorQuad(tile, {{{xWest, h, zNorth}, {xEast, h, zNorth}, {xEast, h, zSouth}, {xWest, h, zSouth}}});
                    }
                }

                // (b) the underside of a deck: a lidded block over a stored,
                // empty block (air with no faces and no slope).
                if (block.lid && !block.lid.IsFlat() && block.SlopeType() == 0 && below) {
                    const bool emptyBelow = !below->lid && !below->left && !below->right && !below->top && !below->bottom && below->SlopeType() == 0;
                    if (emptyBelow) {
                        const float h = static_cast<float>(level);
                        builder->AddSideQuad(DeckUndersideTile(block), {{{xWest, h, zSouth}, {xEast, h, zSouth}, {xEast, h, zNorth}, {xWest, h, zNorth}}}, {0.0f, -1.0f, 0.0f});
                    }
                }
            }
        }
    }
}
}  // namespace

namespace {
bool g_streetFill = true;

// The street views' fill (see SetStreetFill). GTA2's map is a set of shells for a
// camera that only ever looked down: a column's implicit base and a road block's
// lid have no sides, so wherever a walkable surface steps down to a lower one
// without a wall face (the Industrial start roof at (44,99) is one: a field block
// one level above the pavement under the church, no riser) a camera at street or
// roof height looks under the higher lid, through the solid ground, and onto the
// seal - a flat clear- or fog-coloured sheet where the street should be. The world
// is treated as cells that are solid or air, and every face between a solid cell
// and an air one that the map leaves open is closed; where a column has nothing at
// all at level 0 a ground plane goes under it. Everything here is drawn in the
// street views only (TileBatch::streetOnly), so the classic view is untouched even
// where a riser would show at the edge of its perspective.
class StreetSolid {
public:
    StreetSolid(const Map& map, const Style& style) : map_(map), style_(style) {}

    const Block* At(int x, int y, int level) const {
        if (x < 0 || y < 0 || x >= kMapWidth || y >= kMapHeight || level < 0) return nullptr;
        const Column& column = map_.ColumnAt(x, y);
        const int i = level - column.offset;
        if (i < 0 || i >= static_cast<int>(column.blocks.size())) return nullptr;
        const uint32_t index = column.blocks[static_cast<size_t>(i)];
        return index < map_.BlockCount() ? &map_.BlockAt(index) : nullptr;
    }

    bool Water(const Block& block) const { return block.lid && style_.IsWaterTile(block.lid.Tile()); }

    // A lidless road or pavement under a deck, given a lid by AddHiddenSurfaces (a).
    bool HiddenGround(int x, int y, int level) const {
        const Block* block = At(x, y, level);
        if (!block || block->lid || block->SlopeType() != 0 || (block->GroundType() == 0 && block->arrows == 0)) return false;
        const Block* above = At(x, y, level + 1);
        const Block* below = At(x, y, level - 1);
        const bool covered = above && (above->lid || above->left || above->right || above->top || above->bottom);
        const bool belowIsSurface = below && (below->lid || below->SlopeType() != 0);
        return covered && !belowIsSurface && NeighbourLidTile(map_, x, y, level + 1) != 0;
    }

    bool Solid(int x, int y, int level) const {
        if (level < 0) return true;
        if (x < 0 || y < 0 || x >= kMapWidth || y >= kMapHeight || level >= kMapLevels) return false;
        if (level < map_.ColumnAt(x, y).offset) return true;
        const Block* block = At(x, y, level);
        if (!block) return false;
        if (block->lid && !block->lid.IsFlat() && block->SlopeType() == 0 &&
            block->lid.Tile() < style_.TileCount() && !Water(*block))
            return true;
        if (SlopeSupport(x, y, level) && Solid(x, y, level - 1)) return true;   // standing on solid ground
        return HiddenGround(x, y, level);
    }

    // Slope type 63 under a ramp or a pitched roof: the block that carries the slope
    // (the attic under a roof, the fill under a ramp). It is solid up to the slope's
    // foot, but has no lid and usually no sides, so from beside it the eye went in under
    // the roof and out through the roof's culled underside: the eave of a roof hung in
    // the sky with nothing under it (9h, Downtown (164..165,138..141)). Counted solid
    // only under a ramp or a pitched roof (types 1-44) with a solid lid, or under another
    // such block.
    bool SlopeSupport(int x, int y, int level) const {
        for (int l = level; l < kMapLevels; ++l) {
            const Block* block = At(x, y, l);
            if (!block) return false;
            const int type = block->SlopeType();
            if (l > level && type >= 1 && type <= 44) return block->lid && !block->lid.IsFlat();
            if (type != 63) return false;
        }
        return false;
    }

    // Solid and standing on something: a lid over air (an awning, a deck) keeps its
    // thin edge; only ground and what is built on it gets risers.
    bool Grounded(int x, int y, int level) const {
        for (int l = level; l >= 0; --l) if (!Solid(x, y, l)) return false;
        return true;
    }

private:
    const Map& map_;
    const Style& style_;
};

const Face& SideFace(const Block& block, int side) {
    return side == 0 ? block.left : side == 1 ? block.right : side == 2 ? block.top : block.bottom;
}

// A solid wall tile: not a see-through face and no colour-keyed pixels (a riser is
// drawn opaque, where a grille's key colour would show as black).
bool RealTile(const Style& style, const Face& face) {
    return face && !face.IsFlat() && face.Tile() < style.TileCount() && !style.GetTile(face.Tile()).hasTransparency;
}

// A wall tile for a riser on `side` of (x, y, level). In order: the face the cell's
// own column shows on that side higher up (a building's wall continues down to the
// street), any wall of the cell's own block or of its column below, a wall a
// neighbouring column shows at that level or below (the retaining wall of the next
// cell), and failing all of those the ground's own lid tile - never a neighbour's
// facade from higher up, whose windows on a step in the ground looked wrong.
int RiserTile(const Style& style, const StreetSolid& solid, int x, int y, int level, int side, int lidTile) {
    for (int l = level; l < kMapLevels; ++l) {
        if (const Block* block = solid.At(x, y, l)) if (RealTile(style, SideFace(*block, side))) return SideFace(*block, side).Tile();
    }
    for (int l = level; l >= 0; --l) {
        if (const Block* block = solid.At(x, y, l)) {
            for (int s = 0; s < 4; ++s) if (RealTile(style, SideFace(*block, s))) return SideFace(*block, s).Tile();
        }
    }
    for (int radius = 1; radius <= 2; ++radius) {
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                if ((std::max)(std::abs(dx), std::abs(dy)) != radius) continue;
                for (int l = level; l >= 0; --l) {
                    if (const Block* block = solid.At(x + dx, y + dy, l)) {
                        for (int s = 0; s < 4; ++s) if (RealTile(style, SideFace(*block, s))) return SideFace(*block, s).Tile();
                    }
                }
            }
        }
    }
    return lidTile;
}

int GroundTileNear(const Map& map, int x, int y, int level) {
    if (const int tile = NeighbourLidTile(map, x, y, level)) return tile;
    for (int radius = 4; radius <= 12; ++radius) {
        for (int dy = -radius; dy <= radius; ++dy) {
            for (int dx = -radius; dx <= radius; ++dx) {
                if ((std::max)(std::abs(dx), std::abs(dy)) != radius) continue;
                const int cx = x + dx, cy = y + dy;
                if (cx < 0 || cy < 0 || cx >= kMapWidth || cy >= kMapHeight) continue;
                const Column& column = map.ColumnAt(cx, cy);
                for (uint32_t index : column.blocks) {
                    if (index >= map.BlockCount()) continue;
                    const Block& block = map.BlockAt(index);
                    if (block.lid && !block.lid.IsFlat() && block.SlopeType() == 0) return block.lid.Tile();
                }
            }
        }
    }
    return 0;
}

struct StreetFillStats { int risers = 0, floors = 0, ground = 0, apronTile = 0; float apronHeight = 0.0f; int ceilings = 0, baseSides = 0, rampSides = 0, decks = 0; };
StreetFillStats g_streetFillStats;

// Ceilings (9g, 9h): a building that overhangs the street - an arcade, a passage,
// an upper storey on a wall face over a pavement - is stored as blocks with side faces
// and one lid at the top. Nothing closes its bottom: a top-down camera never looks up.
// From under it a street camera looked up through the open shell at the sky, at the
// back of the roof lid (culled) and at whatever stands on the roof (a rooftop unit
// seen from below hung in the sky as a disc). AddHiddenSurfaces (b) gives a lidded
// block over an empty one its underside; this does the same for the lowest block of
// any overhanging mass that ends in a roof: every block from it up to the column's top
// has a face, a lid or a slope, the top has a lid or a slope, and the cell under it is
// open (no lid, no slope, not the base), and the block is closed all round. Faced down.
bool HasRealSide(const Block& block) {
    for (const Face* face : {&block.left, &block.right, &block.top, &block.bottom})
        if (*face && !face->IsFlat()) return true;
    return false;
}

void AddOverhangCeilings(MeshBuilder* builder, const Map& map, const Style& style, const StreetSolid& solid,
                         StreetFillStats* stats) {
    // The ceiling's tile: of the walls the block shows, the one the map uses most (plain
    // brick or stone, not the rose window or the shop sign that happens to come first).
    std::vector<int> wallUse(static_cast<size_t>(style.TileCount()) + 1, 0);
    for (size_t index = 0; index < map.BlockCount(); ++index) {
        const Block& block = map.BlockAt(static_cast<uint32_t>(index));
        for (int side = 0; side < 4; ++side)
            if (RealTile(style, SideFace(block, side))) ++wallUse[static_cast<size_t>(SideFace(block, side).Tile())];
    }
    auto ceilingTile = [&](const Block& block) {
        int best = 0, use = -1;
        for (int side = 0; side < 4; ++side) {
            const Face& face = SideFace(block, side);
            if (RealTile(style, face) && wallUse[static_cast<size_t>(face.Tile())] > use) { best = face.Tile(); use = wallUse[static_cast<size_t>(face.Tile())]; }
        }
        return best ? best : DeckUndersideTile(block);
    };
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            const int top = column.offset + static_cast<int>(column.blocks.size()) - 1;
            const Block* topBlock = solid.At(x, y, top);
            if (!topBlock || !(topBlock->lid || topBlock->SlopeType() != 0)) continue;
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;
            // Walk down from the roof while the mass is unbroken.
            for (int level = top; level > column.offset; --level) {
                const Block* block = solid.At(x, y, level);
                if (!block || !(block->lid || block->SlopeType() != 0 || HasRealSide(*block))) break;
                const Block* below = solid.At(x, y, level - 1);
                if (below && (below->lid || below->SlopeType() != 0 || HasRealSide(*below))) continue;
                if (solid.Solid(x, y, level - 1)) break;
                // The lowest block of the mass, over open air. Ramps and partial blocks
                // have their own undersides or none to give; a flat lid over an empty
                // block is AddHiddenSurfaces (b)'s.
                const bool emptyBelow = below && !below->lid && !below->left && !below->right && !below->top && !below->bottom;
                const bool solidLid = block->lid && !block->lid.IsFlat();
                const bool doneByB = solidLid && emptyBelow;
                // Closed all round at that level (its own wall, or a neighbour that is solid
                // or part of a building): a shell open on a side (Industrial (42,98), a north
                // wall only) would show its ceiling as a slab hanging in the air.
                bool closed = true;
                for (int side = 0; side < 4 && closed; ++side) {
                    if (SideFace(*block, side)) continue;
                    const int nx = x + (side == 1) - (side == 0), ny = y + (side == 3) - (side == 2);
                    if (solid.Solid(nx, ny, level)) continue;
                    const Block* other = solid.At(nx, ny, level);
                    closed = other && (other->lid || other->SlopeType() != 0 || HasRealSide(*other));
                }
                if (closed && block->SlopeType() == 0 && (HasRealSide(*block) || solidLid) && !doneByB) {
                    const int tile = ceilingTile(*block);
                    if (tile > 0) {
                        const float h = static_cast<float>(level);
                        builder->AddSideQuad(tile, {{{xWest, h, zSouth}, {xEast, h, zSouth}, {xEast, h, zNorth}, {xWest, h, zNorth}}}, {0.0f, -1.0f, 0.0f});
                        ++stats->ceilings;
                    }
                }
                break;
            }
        }
    }
}

// Base sides over a see-through tile (9h): AddImplicitFloors dresses the side of a
// column's implicit base with the first face the column shows on that side at any
// height, and on a pitched roof that is the ridge's crest trim (Downtown (164,140):
// tile 3, scallops and finials over colour-keyed nothing). Alpha-tested on a solid base
// it read as a black hole in the wall with the trim along its bottom, and the eave of
// the roof above seemed to float over it. The classic view keeps its quad; the street
// views draw an opaque wall over it at the same corners (same vertices, so the same
// depth, and drawn later under LESSEQUAL it wins): the column's own wall on that side
// higher up, else a wall nearby (RiserTile), else the floor's tile.
void AddBaseSideCovers(MeshBuilder* builder, const Map& map, const Style& style, const StreetSolid& solid, StreetFillStats* stats) {
    static const int kSideDx[4] = {-1, 1, 0, 0};
    static const int kSideDy[4] = {0, 0, -1, 1};
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            if (column.offset == 0 || column.blocks.empty() || column.blocks[0] >= map.BlockCount()) continue;
            const int floorTile = NeighbourLidTile(map, x, y, column.offset);
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;
            for (int side = 0; side < 4; ++side) {
                const int nx = x + kSideDx[side], ny = y + kSideDy[side];
                if (nx < 0 || ny < 0 || nx >= kMapWidth || ny >= kMapHeight) continue;
                const int low = map.ColumnAt(nx, ny).offset;
                if (low >= column.offset) continue;
                // The face ImplicitSideTile picks; only a see-through one is replaced.
                const Face* picked = nullptr;
                for (uint32_t index : column.blocks) {
                    if (index >= map.BlockCount()) continue;
                    const Face& face = SideFace(map.BlockAt(index), side);
                    if (face) { picked = &face; break; }
                }
                if (!picked || RealTile(style, *picked)) continue;
                for (int level = low; level < column.offset; ++level) {
                    const int tile = RiserTile(style, solid, x, y, level, side, floorTile);
                    if (tile <= 0 || tile >= style.TileCount() || tile == picked->Tile()) continue;
                    const float y0 = static_cast<float>(level), y1 = y0 + 1.0f;
                    std::array<Vec3, 4> corners;
                    Vec3 normal;
                    switch (side) {   // as AddImplicitFloors, corner for corner
                        case 0: corners = {{{xWest, y1, zNorth}, {xWest, y1, zSouth}, {xWest, y0, zSouth}, {xWest, y0, zNorth}}}; normal = {-1.0f, 0.0f, 0.0f}; break;
                        case 1: corners = {{{xEast, y1, zSouth}, {xEast, y1, zNorth}, {xEast, y0, zNorth}, {xEast, y0, zSouth}}}; normal = {1.0f, 0.0f, 0.0f}; break;
                        case 2: corners = {{{xEast, y1, zNorth}, {xWest, y1, zNorth}, {xWest, y0, zNorth}, {xEast, y0, zNorth}}}; normal = {0.0f, 0.0f, 1.0f}; break;
                        default: corners = {{{xWest, y1, zSouth}, {xEast, y1, zSouth}, {xEast, y0, zSouth}, {xWest, y0, zSouth}}}; normal = {0.0f, 0.0f, -1.0f}; break;
                    }
                    builder->AddSideQuad(tile, corners, normal);
                    ++stats->baseSides;
                }
            }
        }
    }
}

// Ramp sides: a ramp block's side under its sloping lid is a triangle (or, mid-ramp, a
// trapezium) that the map leaves open wherever a top-down camera never saw it. With the
// fill under a ramp counted solid (StreetSolid::SlopeSupport) the eye went in through
// that open side and down through the fill; before, it went under the roof of a pitched
// building and out through its culled underside. Each open side of a ramp (types 1-44)
// with a solid lid, standing on solid ground, whose neighbour at that level is not
// solid is closed from the neighbour's own ramp
// height at the shared edge (0 if it is not a ramp) up to this lid's, tiled like a riser.
void AddRampSides(MeshBuilder* builder, const Map& map, const Style& style, const StreetSolid& solid,
                  const SlopeInfo* slopes, StreetFillStats* stats) {
    static const int kSideDx[4] = {-1, 1, 0, 0};
    static const int kSideDy[4] = {0, 0, -1, 1};
    static const int kOpposite[4] = {1, 0, 3, 2};
    // Corner indices (CornerHeights: NW, NE, SE, SW) along each side, first then second
    // in the order the riser corners of AddStreetFill run along that side.
    static const int kEdge[4][2] = {{0, 3}, {2, 1}, {1, 0}, {3, 2}};
    auto edgeHeights = [&](const Block& block, int side, float* a, float* b) {
        const int type = block.SlopeType();
        if (type < 1 || type > 44) { *a = *b = 0.0f; return false; }
        const CornerHeights h = LidHeights(slopes[type]);
        *a = h[kEdge[side][0]];
        *b = h[kEdge[side][1]];
        return true;
    };
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;
            for (size_t i = 0; i < column.blocks.size(); ++i) {
                if (column.blocks[i] >= map.BlockCount()) continue;
                const Block& block = map.BlockAt(column.blocks[i]);
                const int type = block.SlopeType();
                if (type < 1 || type > 44 || !block.lid || block.lid.IsFlat()) continue;
                const int level = column.offset + static_cast<int>(i);
                // A ramp standing on the ground or on its fill; a see-through or floating
                // one (a gantry, a sign frame over the street) is seen from both sides.
                if (level > 0 && !solid.Grounded(x, y, level - 1)) continue;
                for (int side = 0; side < 4; ++side) {
                    if (SideFace(block, side)) continue;
                    float top0, top1;
                    edgeHeights(block, side, &top0, &top1);
                    if (top0 <= 0.0f && top1 <= 0.0f) continue;
                    const int nx = x + kSideDx[side], ny = y + kSideDy[side];
                    if (solid.Solid(nx, ny, level)) continue;
                    // The neighbour's ramp along the shared edge, corner for corner: its
                    // opposite side runs the other way along the edge.
                    float bot0 = 0.0f, bot1 = 0.0f;
                    if (const Block* other = solid.At(nx, ny, level)) {
                        float o0, o1;
                        if (edgeHeights(*other, kOpposite[side], &o0, &o1)) { bot0 = o1; bot1 = o0; }
                    }
                    if (top0 <= bot0 + 1e-3f && top1 <= bot1 + 1e-3f) continue;
                    bot0 = (std::min)(bot0, top0);
                    bot1 = (std::min)(bot1, top1);
                    const int lidTile = block.lid ? block.lid.Tile() : NeighbourLidTile(map, x, y, level + 1);
                    const int tile = RiserTile(style, solid, x, y, level, side, lidTile);
                    if (tile <= 0 || tile >= style.TileCount()) continue;
                    const float l = static_cast<float>(level);
                    std::array<Vec3, 4> corners;
                    Vec3 normal;
                    switch (side) {
                        case 0: corners = {{{xWest, l + top0, zNorth}, {xWest, l + top1, zSouth}, {xWest, l + bot1, zSouth}, {xWest, l + bot0, zNorth}}}; normal = {-1.0f, 0.0f, 0.0f}; break;
                        case 1: corners = {{{xEast, l + top0, zSouth}, {xEast, l + top1, zNorth}, {xEast, l + bot1, zNorth}, {xEast, l + bot0, zSouth}}}; normal = {1.0f, 0.0f, 0.0f}; break;
                        case 2: corners = {{{xEast, l + top0, zNorth}, {xWest, l + top1, zNorth}, {xWest, l + bot1, zNorth}, {xEast, l + bot0, zNorth}}}; normal = {0.0f, 0.0f, 1.0f}; break;
                        default: corners = {{{xWest, l + top0, zSouth}, {xEast, l + top1, zSouth}, {xEast, l + bot1, zSouth}, {xWest, l + bot0, zSouth}}}; normal = {0.0f, 0.0f, -1.0f}; break;
                    }
                    // The texture at wall scale, cropped to the trapezium, not the whole tile
                    // squeezed into it: a ramp's low piece is an eighth of a level high, and the
                    // stone of the Residential flyover ramp (210..217,140) read as streaks (pm12).
                    const std::array<Uv, 4> uv = {{{0.0f, 1.0f - top0}, {1.0f, 1.0f - top1}, {1.0f, 1.0f - bot1}, {0.0f, 1.0f - bot0}}};
                    builder->AddPlainQuad(tile, corners, normal, uv);
                    ++stats->rampSides;
                }
            }
        }
    }
}

// Flyover decks (pm12): a road bridge over a street is stored as a lidded road block
// one level above the street's own lidded block (Residential (218..225,140..141): road
// at level 2 over the street at level 1, see-through girders on its sides). The block's
// volume is the clearance the traffic under it drives through, so the deck is nothing
// but the lid at its top - one-sided, culled from below. From the street the cars on
// the bridge rode on air inside the lattice. Every such deck - a solid lid, no slope,
// directly over a block that has a lid or a ramp of its own, open on some side - gets
// the lid's underside at the same height, faced down (AddHiddenSurfaces (b) is the deck
// over an empty block, AddOverhangCeilings the closed storey over the pavement). The
// underside's tile: the wall the bridge's ends and abutments show most (the stone of the
// ramps), voted over the whole connected deck so a bridge is one material, else the
// deck's own side, else its lid. Hidden from above by the lid itself.
void AddPassageDecks(MeshBuilder* builder, const Map& map, const Style& style, const StreetSolid& solid,
                     StreetFillStats* stats) {
    static const int kSideDx[4] = {-1, 1, 0, 0};
    static const int kSideDy[4] = {0, 0, -1, 1};
    auto isDeck = [&](int x, int y, int level) {
        const Block* block = solid.At(x, y, level);
        if (!block || !block->lid || block->lid.IsFlat() || block->SlopeType() != 0 ||
            block->lid.Tile() >= style.TileCount() || solid.Water(*block))
            return false;
        const Block* below = solid.At(x, y, level - 1);
        if (!below || !(below->lid || below->SlopeType() != 0)) return false;
        int walls = 0;
        for (int side = 0; side < 4; ++side) if (RealTile(style, SideFace(*block, side))) ++walls;
        return walls < 4;
    };
    std::vector<uint8_t> done(static_cast<size_t>(kMapWidth) * kMapHeight * kMapLevels, 0);
    auto key = [](int x, int y, int level) { return (static_cast<size_t>(level) * kMapHeight + y) * kMapWidth + x; };
    for (int level = 1; level < kMapLevels; ++level) {
        for (int y = 0; y < kMapHeight; ++y) {
            for (int x = 0; x < kMapWidth; ++x) {
                if (done[key(x, y, level)] || !isDeck(x, y, level)) continue;
                // The connected deck at this level, and the vote for its tile.
                std::vector<std::pair<int, int>> cells, stack = {{x, y}};
                std::map<int, int> votes;
                done[key(x, y, level)] = 1;
                auto vote = [&](const Block& b) {
                    for (int side = 0; side < 4; ++side)
                        if (RealTile(style, SideFace(b, side))) ++votes[SideFace(b, side).Tile()];
                };
                while (!stack.empty()) {
                    const auto c = stack.back();
                    stack.pop_back();
                    cells.push_back(c);
                    vote(*solid.At(c.first, c.second, level));
                    for (int side = 0; side < 4; ++side) {
                        const int nx = c.first + kSideDx[side], ny = c.second + kSideDy[side];
                        if (nx < 0 || ny < 0 || nx >= kMapWidth || ny >= kMapHeight) continue;
                        if (isDeck(nx, ny, level)) {
                            if (!done[key(nx, ny, level)]) { done[key(nx, ny, level)] = 1; stack.push_back({nx, ny}); }
                        } else if (const Block* other = solid.At(nx, ny, level)) {
                            vote(*other);   // the abutment or the ramp that meets the deck
                        }
                    }
                }
                int tile = 0, best = 0;
                for (const auto& kv : votes) if (kv.second > best) { tile = kv.first; best = kv.second; }
                for (const auto& c : cells) {
                    const Block& block = *solid.At(c.first, c.second, level);
                    const int t = tile ? tile : DeckUndersideTile(block);
                    if (t <= 0 || t >= style.TileCount()) continue;
                    const float xWest = static_cast<float>(c.first), xEast = xWest + 1.0f;
                    const float zSouth = static_cast<float>(kMapHeight - c.second - 1), zNorth = zSouth + 1.0f;
                    const float h = static_cast<float>(level + 1);
                    builder->AddSideQuad(t, {{{xWest, h, zSouth}, {xEast, h, zSouth}, {xEast, h, zNorth}, {xWest, h, zNorth}}}, {0.0f, -1.0f, 0.0f});
                    ++stats->decks;
                }
            }
        }
    }
}

void AddStreetFill(MeshBuilder* builder, const Map& map, const Style& style, const SlopeInfo* slopes) {
    static const int kSideDx[4] = {-1, 1, 0, 0};   // left (west), right (east), top (north), bottom (south)
    static const int kSideDy[4] = {0, 0, -1, 1};
    static const int kOpposite[4] = {1, 0, 3, 2};
    const StreetSolid solid(map, style);
    StreetFillStats stats;
    // Cells near water keep the riverbed, not a ground plane.
    std::vector<uint8_t> wet(static_cast<size_t>(kMapWidth) * kMapHeight, 0);
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            bool water = false;
            for (uint32_t index : column.blocks) if (index < map.BlockCount() && solid.Water(map.BlockAt(index))) water = true;
            if (!water) continue;
            for (int dy = -kRiverbedPad - 1; dy <= kRiverbedPad + 1; ++dy)
                for (int dx = -kRiverbedPad - 1; dx <= kRiverbedPad + 1; ++dx) {
                    const int cx = x + dx, cy = y + dy;
                    if (cx >= 0 && cy >= 0 && cx < kMapWidth && cy < kMapHeight) wet[static_cast<size_t>(cy) * kMapWidth + cx] = 1;
                }
        }
    }
    builder->SetStreetMode(1);
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            const float xWest = static_cast<float>(x), xEast = xWest + 1.0f;
            const float zSouth = static_cast<float>(kMapHeight - y - 1), zNorth = zSouth + 1.0f;

            // The top of the implicit base where AddImplicitFloors found no tile for it.
            if (column.offset > 0 && !solid.Solid(x, y, column.offset)) {
                const Block* first = solid.At(x, y, column.offset);
                const bool covered = first && (first->lid || first->SlopeType() != 0);
                if (!covered && NeighbourLidTile(map, x, y, column.offset) == 0) {
                    if (const int tile = GroundTileNear(map, x, y, column.offset)) {
                        const float h = static_cast<float>(column.offset);
                        builder->AddFloorQuad(tile, {{{xWest, h, zNorth}, {xEast, h, zNorth}, {xEast, h, zSouth}, {xWest, h, zSouth}}});
                        ++stats.floors;
                    }
                }
            }

            // Nothing at the bottom of the column: a ground plane at level 0.
            if (!wet[static_cast<size_t>(y) * kMapWidth + x] && !solid.Solid(x, y, 0)) {
                const Block* bottom = solid.At(x, y, 0);
                const bool covered = bottom && (bottom->lid || bottom->SlopeType() != 0);
                if (!covered) {
                    if (const int tile = GroundTileNear(map, x, y, 1)) {
                        builder->AddFloorQuad(tile, {{{xWest, 0.0f, zNorth}, {xEast, 0.0f, zNorth}, {xEast, 0.0f, zSouth}, {xWest, 0.0f, zSouth}}});
                        ++stats.ground;
                    }
                }
            }

            // Risers: a grounded solid cell beside an air one, with no face between.
            for (int level = 0; level < kMapLevels; ++level) {
                if (!solid.Solid(x, y, level) || !solid.Grounded(x, y, level)) continue;
                const Block* block = solid.At(x, y, level);
                for (int side = 0; side < 4; ++side) {
                    const int nx = x + kSideDx[side], ny = y + kSideDy[side];
                    if (solid.Solid(nx, ny, level)) continue;
                    if (block && SideFace(*block, side)) continue;
                    // A face of the air block next door on this plane faces away from it, into
                    // this solid cell: our renderer culls its back, so from the air side it is
                    // not there (Residential spawn, (116,121)). Only a see-through face, drawn
                    // both ways, already closes the side.
                    if (const Block* other = solid.At(nx, ny, level)) {
                        const Face& face = SideFace(*other, kOpposite[side]);
                        if (face && face.IsFlat()) continue;
                    }
                    // AddImplicitFloors already closed the side of the base here.
                    if (level < column.offset && nx >= 0 && ny >= 0 && nx < kMapWidth && ny < kMapHeight &&
                        map.ColumnAt(nx, ny).offset <= level &&
                        ImplicitSideTile(map, column, side, NeighbourLidTile(map, x, y, column.offset)) != 0)
                        continue;
                    const int lidTile = block && block->lid ? block->lid.Tile() : NeighbourLidTile(map, x, y, level + 1);
                    const int tile = RiserTile(style, solid, x, y, level, side, lidTile);
                    if (tile <= 0 || tile >= style.TileCount()) continue;
                    const float y0 = static_cast<float>(level), y1 = y0 + 1.0f;
                    std::array<Vec3, 4> corners;
                    Vec3 normal;
                    switch (side) {
                        case 0: corners = {{{xWest, y1, zNorth}, {xWest, y1, zSouth}, {xWest, y0, zSouth}, {xWest, y0, zNorth}}}; normal = {-1.0f, 0.0f, 0.0f}; break;
                        case 1: corners = {{{xEast, y1, zSouth}, {xEast, y1, zNorth}, {xEast, y0, zNorth}, {xEast, y0, zSouth}}}; normal = {1.0f, 0.0f, 0.0f}; break;
                        case 2: corners = {{{xEast, y1, zNorth}, {xWest, y1, zNorth}, {xWest, y0, zNorth}, {xEast, y0, zNorth}}}; normal = {0.0f, 0.0f, 1.0f}; break;
                        default: corners = {{{xWest, y1, zSouth}, {xEast, y1, zSouth}, {xEast, y0, zSouth}, {xWest, y0, zSouth}}}; normal = {0.0f, 0.0f, -1.0f}; break;
                    }
                    builder->AddSideQuad(tile, corners, normal);
                    ++stats.risers;
                }
            }
        }
    }
    AddOverhangCeilings(builder, map, style, solid, &stats);
    AddBaseSideCovers(builder, map, style, solid, &stats);
    AddRampSides(builder, map, style, solid, slopes, &stats);
    AddPassageDecks(builder, map, style, solid, &stats);
    builder->SetStreetMode(0);
    g_streetFillStats = stats;
}

// The apron (9d, the horizon): GTA2's map simply stops at its edge, so from a roof or
// in the descent from the top-down view the city ended in a ruler-straight line with
// the sky's skirt under it, wherever the edge was nearer than the fog's full reach
// (the Industrial start is 44 blocks from the west edge, fog full at 130). Past every
// edge the world goes on as flat ground for kApronReach blocks at the level and in
// the tile the map's border shows most - water at sea level in all three districts,
// so the city stands on a sea that the distance fog dissolves into the horizon. The
// quads repeat their tile once per block (TileBatch::wrapUv); a water tile is drawn by
// the water pass like the map's own water.
constexpr float kApronReach = 640.0f;

void AddApron(MeshBuilder* builder, const Map& map, const Style& style) {
    const StreetSolid solid(map, style);
    std::map<int, int> waterTiles, groundTiles, heights;
    auto border = [&](int x, int y) {
        const Column& column = map.ColumnAt(x, y);
        for (size_t i = 0; i < column.blocks.size(); ++i) {
            const uint32_t index = column.blocks[i];
            if (index >= map.BlockCount()) continue;
            const Block& block = map.BlockAt(index);
            if (!block.lid || block.lid.IsFlat() || block.SlopeType() != 0 || block.lid.Tile() >= style.TileCount()) continue;
            if (solid.Water(block)) ++waterTiles[block.lid.Tile()];
            else ++groundTiles[block.lid.Tile()];
            ++heights[column.offset + static_cast<int>(i) + 1];
            return;
        }
    };
    for (int i = 0; i < kMapWidth; ++i) { border(i, 0); border(i, kMapHeight - 1); }
    for (int i = 1; i + 1 < kMapHeight; ++i) { border(0, i); border(kMapWidth - 1, i); }
    auto most = [](const std::map<int, int>& m) {
        int best = 0, count = 0;
        for (const auto& kv : m) if (kv.second > count) { best = kv.first; count = kv.second; }
        return best;
    };
    int tile = most(waterTiles);
    float h = 1.0f;   // the water's surface: a water lid sits on level 0
    if (tile == 0) {
        tile = most(groundTiles);
        h = static_cast<float>(most(heights));
    }
    if (tile <= 0) return;
    const float lo = -kApronReach;
    const float hiX = static_cast<float>(kMapWidth) + kApronReach, hiZ = static_cast<float>(kMapHeight) + kApronReach;
    const float W = static_cast<float>(kMapWidth), H = static_cast<float>(kMapHeight);
    // Four strips and four corners around the map, face up, one tile repeat per block.
    const float rects[8][4] = {
        {lo, 0.0f, 0.0f, H}, {W, 0.0f, hiX, H}, {0.0f, lo, W, 0.0f}, {0.0f, H, W, hiZ},
        {lo, lo, 0.0f, 0.0f}, {W, lo, hiX, 0.0f}, {lo, H, 0.0f, hiZ}, {W, H, hiX, hiZ}};
    builder->SetStreetMode(2);
    for (const auto& r : rects) {
        const std::array<Vec3, 4> corners = {{{r[0], h, r[3]}, {r[2], h, r[3]}, {r[2], h, r[1]}, {r[0], h, r[1]}}};
        std::array<Uv, 4> uv;
        for (int i = 0; i < 4; ++i) uv[i] = Uv{corners[i].x, -corners[i].z};
        builder->AddPlainQuad(tile, corners, {0.0f, 1.0f, 0.0f}, uv);
    }
    builder->SetStreetMode(0);
    g_streetFillStats.apronTile = tile;
    g_streetFillStats.apronHeight = h;
}
}  // namespace

void SetStreetFill(bool on) { g_streetFill = on; }
bool StreetFill() { return g_streetFill; }
StreetFillCounts LastStreetFillCounts() {
    return StreetFillCounts{g_streetFillStats.risers, g_streetFillStats.floors, g_streetFillStats.ground,
                            g_streetFillStats.apronTile, g_streetFillStats.apronHeight, g_streetFillStats.ceilings,
                            g_streetFillStats.baseSides, g_streetFillStats.rampSides, g_streetFillStats.decks};
}

void SetRiverbedDepth(float blocks) {
    // Above the seal, which is kSealDepth below level 0 - a sea-level bed any
    // deeper would sit under it.
    const float deepest = kSealDepth + 0.9f;
    g_riverbedDepth = blocks < 0.0f ? 0.0f : (blocks > deepest ? deepest : blocks);
}
float RiverbedDepth() { return g_riverbedDepth; }

void SetRailingModels(bool on) { g_railingModels = on; }
bool RailingModels() { return g_railingModels; }
RailingStats LastRailingStats() { return g_railingStats; }

void SetWorldSeal(bool on) { g_seal = on; }
bool WorldSeal() { return g_seal; }

void SetWaterUvBlocks(float blocks) {
    g_waterUvBlocks = blocks < 0.0f ? 0.0f : (blocks > 64.0f ? 64.0f : blocks);
}
float WaterUvBlocks() { return g_waterUvBlocks; }

void BuildWorldMesh(const Map& map, const Style& style, const SlopeInfo* slopes,
                    const PartialCuts& cuts, WorldMesh* out) {
    // Prefer the game's own slope descriptors; fall back to deriving them when
    // they could not be read, so a map still builds without a live game.
    std::array<SlopeInfo, kSlopeTypeCount> resolved;
    ResolveSlopeTable(slopes, resolved.data());

    g_railingStats = RailingStats{};
    if (const char* e = std::getenv("GTA2DX9_RAILINGS")) g_railingModels = e[0] != '0';
    MeshBuilder builder(style);
    for (int y = 0; y < kMapHeight; ++y) {
        for (int x = 0; x < kMapWidth; ++x) {
            const Column& column = map.ColumnAt(x, y);
            for (size_t i = 0; i < column.blocks.size(); ++i) {
                const uint32_t index = column.blocks[i];
                if (index >= map.BlockCount()) continue;
                const Block& block = map.BlockAt(index);
                AddBlock(&builder, block, resolved[block.SlopeType() & (kSlopeTypeCount - 1)], cuts,
                         x, y, column.offset + static_cast<int>(i));
            }
        }
    }
    AddImplicitFloors(&builder, map);
    AddHiddenSurfaces(&builder, map);
    if (g_riverbedDepth > 0.0f) AddRiverbed(&builder, map, style, g_riverbedDepth);
    if (const char* e = std::getenv("GTA2DX9_STREET_FILL")) g_streetFill = e[0] != '0';
    g_streetFillStats = StreetFillStats{};
    if (g_streetFill) {
        AddStreetFill(&builder, map, style, resolved.data());
        AddApron(&builder, map, style);
    }
    if (g_seal) {
        // One quad, face up, below everything and reaching well past the map on
        // every side. Winding is left to AddSealQuad; the normal is what says
        // which way it faces.
        const float lo = -kSealOverhang;
        const float hiX = static_cast<float>(kMapWidth) + kSealOverhang;
        const float hiZ = static_cast<float>(kMapHeight) + kSealOverhang;
        const float y = -kSealDepth;
        builder.AddSealQuad({{{lo, y, lo}, {hiX, y, lo}, {hiX, y, hiZ}, {lo, y, hiZ}}},
                            {0.0f, 1.0f, 0.0f});
    }
    builder.Flatten(out);
    g_railingStats.tiles = builder.RailingTiles();
}

}  // namespace gta2
