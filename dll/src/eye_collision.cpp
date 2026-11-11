// The street views' camera against the drawn world mesh. See eye_collision.h.
#include "eye_collision.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

#include "../../src/gta2_map.h"
#include "../../src/gta2_style.h"
#include "../../src/world_mesh.h"
#ifndef EYECOL_NATIVE
#include "log.h"
#else
#include <cstdio>
namespace gta2dx9 { template <typename... A> void Log(const char* f, A... a) { std::fprintf(stderr, f, a...); std::fputc(10, stderr); } }
#endif

namespace eyecol {
using gta2dx9::Log;
namespace {

using gta2::Vec3;

struct Tri {
    uint32_t v[3];
    int8_t n[3];        // outward unit normal x127 (the builder's facing)
    uint8_t flags;      // kTwoSided
    uint16_t tile;
};
constexpr uint8_t kTwoSided = 1;
constexpr uint8_t kPanel = 2;   // a railing's plane (never drawn): the bars as one sheet
constexpr uint8_t kBar = 4;     // FIX-CAMERA-6: a face of a railing's bars, rails or finials (on a kPanel's plane)
constexpr int kGrid = 256;

std::vector<Vec3> g_pos;
std::vector<Tri> g_tris;
std::vector<uint32_t> g_cellStart;   // kGrid*kGrid+1, offsets into g_cellTris
std::vector<uint32_t> g_cellTris;
std::vector<uint32_t> g_tileTone;    // darkened mean colour of each tile, for the caps
std::vector<uint8_t> g_tileSeeThrough;   // a tile with holes in it (fences, grilles): no cap
std::vector<uint32_t> g_stamp;       // per triangle: the query that last tested it
uint32_t g_query = 0;
bool g_ready = false;
Stats g_stats;

inline Vec3 Sub(const Vec3& a, const Vec3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline float Len(const Vec3& a) { return std::sqrt(a.x * a.x + a.y * a.y + a.z * a.z); }
inline Vec3 N(const Tri& t) { return {t.n[0] / 127.0f, t.n[1] / 127.0f, t.n[2] / 127.0f}; }

// Ericson, Real-Time Collision Detection 5.1.5.
Vec3 ClosestOnTri(const Vec3& p, const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 ab = Sub(b, a), ac = Sub(c, a), ap = Sub(p, a);
    const float d1 = gta2::Dot(ab, ap), d2 = gta2::Dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) return a;
    const Vec3 bp = Sub(p, b);
    const float d3 = gta2::Dot(ab, bp), d4 = gta2::Dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) return b;
    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) { const float v = d1 / (d1 - d3); return a + ab * v; }
    const Vec3 cp = Sub(p, c);
    const float d5 = gta2::Dot(ab, cp), d6 = gta2::Dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) return c;
    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) { const float w = d2 / (d2 - d6); return a + ac * w; }
    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        const float w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        return b + Sub(c, b) * w;
    }
    const float denom = 1.0f / (va + vb + vc);
    const float v = vb * denom, w = vc * denom;
    return a + ab * v + ac * w;
}

// Möller-Trumbore on the segment o + d*t, t in [0,1].
bool SegTri(const Vec3& o, const Vec3& d, const Vec3& a, const Vec3& b, const Vec3& c, float* t) {
    const Vec3 e1 = Sub(b, a), e2 = Sub(c, a);
    const Vec3 p = gta2::Cross(d, e2);
    const float det = gta2::Dot(e1, p);
    if (std::fabs(det) < 1e-12f) return false;
    const float inv = 1.0f / det;
    const Vec3 s = Sub(o, a);
    const float u = gta2::Dot(s, p) * inv;
    if (u < 0.0f || u > 1.0f) return false;
    const Vec3 q = gta2::Cross(s, e1);
    const float v = gta2::Dot(d, q) * inv;
    if (v < 0.0f || u + v > 1.0f) return false;
    const float tt = gta2::Dot(e2, q) * inv;
    if (tt < 0.0f || tt > 1.0f) return false;
    *t = tt;
    return true;
}

// Every triangle binned in the cells of the box [x0,x1]x[z0,z1], each once per query.
template <typename F>
void ForTris(float x0, float z0, float x1, float z1, F&& f) {
    if (++g_query == 0) { std::fill(g_stamp.begin(), g_stamp.end(), 0u); g_query = 1; }
    const int cx0 = (std::max)(0, static_cast<int>(std::floor(x0))), cx1 = (std::min)(kGrid - 1, static_cast<int>(std::floor(x1)));
    const int cz0 = (std::max)(0, static_cast<int>(std::floor(z0))), cz1 = (std::min)(kGrid - 1, static_cast<int>(std::floor(z1)));
    for (int cz = cz0; cz <= cz1; ++cz)
        for (int cx = cx0; cx <= cx1; ++cx) {
            const size_t cell = static_cast<size_t>(cz) * kGrid + cx;
            for (uint32_t k = g_cellStart[cell]; k < g_cellStart[cell + 1]; ++k) {
                const uint32_t idx = g_cellTris[k];
                if (g_stamp[idx] == g_query) continue;
                g_stamp[idx] = g_query;
                f(g_tris[idx]);
            }
        }
}

}  // namespace

void Build(const gta2::WorldMesh& mesh, const gta2::Style& style) {
    g_ready = false;
    g_pos.clear(); g_tris.clear(); g_cellTris.clear();
    g_pos.reserve(mesh.vertices.size());
    for (const gta2::Vertex& v : mesh.vertices) g_pos.push_back({v.x, v.y, v.z});
    std::vector<uint32_t> counts(static_cast<size_t>(kGrid) * kGrid, 0);
    std::vector<std::pair<int, int>> spans;   // per triangle: cell box packed
    struct Box { int16_t x0, z0, x1, z1; };
    std::vector<Box> boxes;
    for (const gta2::TileBatch& batch : mesh.batches) {
        // The street views' range (world_mesh.h, TileBatch::streetIndices): a face they leave out
        // (an overhead decal, a map tree's blocks, now a tree model) holds no camera back.
        const uint32_t first = batch.streetIndices ? batch.streetIndexStart : batch.indexStart;
        const uint32_t count = batch.streetIndices ? batch.streetIndexCount : batch.indexCount;
        for (uint32_t i = first; i + 2 < first + count; i += 3) {
            Tri t;
            t.v[0] = mesh.indices[i]; t.v[1] = mesh.indices[i + 1]; t.v[2] = mesh.indices[i + 2];
            const Vec3& a = g_pos[t.v[0]]; const Vec3& b = g_pos[t.v[1]]; const Vec3& c = g_pos[t.v[2]];
            Vec3 n = gta2::Cross(Sub(b, a), Sub(c, a));
            const float len = Len(n);
            if (len < 1e-9f) continue;
            n = n * (1.0f / len);
            // The builder's normal says which way the face looks; the winding is made to match
            // it (world_raycast relies on the same), but take the vertex normal as the truth.
            const gta2::Vertex& va = mesh.vertices[t.v[0]];
            if (n.x * va.nx + n.y * va.ny + n.z * va.nz < 0.0f) n = n * -1.0f;
            t.n[0] = static_cast<int8_t>(std::lround(n.x * 127.0f));
            t.n[1] = static_cast<int8_t>(std::lround(n.y * 127.0f));
            t.n[2] = static_cast<int8_t>(std::lround(n.z * 127.0f));
            t.flags = batch.doubleSided ? kTwoSided : 0;
            t.tile = static_cast<uint16_t>(batch.tile < 0 ? 0 : batch.tile);
            const float lx = (std::min)({a.x, b.x, c.x}), hx = (std::max)({a.x, b.x, c.x});
            const float lz = (std::min)({a.z, b.z, c.z}), hz = (std::max)({a.z, b.z, c.z});
            // The seal and the apron past the map edge are huge and never near an eye in town.
            if (hx - lx > 6.0f || hz - lz > 6.0f) continue;
            // The cells the triangle covers, a face on a cell line in the cell above the line only:
            // every query's box reaches that cell from either side, so no padding is needed (it
            // doubled the grid, PERF: the game is a 32-bit process).
            const auto last = [](float lo, float hi) {
                const float c = std::ceil(hi) - 1.0f;
                return static_cast<int>(hi > lo && c >= std::floor(lo) ? c : std::floor(hi));
            };
            Box bx{static_cast<int16_t>((std::max)(0, static_cast<int>(std::floor(lx)))),
                   static_cast<int16_t>((std::max)(0, static_cast<int>(std::floor(lz)))),
                   static_cast<int16_t>((std::min)(kGrid - 1, last(lx, hx))),
                   static_cast<int16_t>((std::min)(kGrid - 1, last(lz, hz)))};
            if (bx.x0 > bx.x1 || bx.z0 > bx.z1) continue;
            for (int z = bx.z0; z <= bx.z1; ++z)
                for (int x = bx.x0; x <= bx.x1; ++x) ++counts[static_cast<size_t>(z) * kGrid + x];
            g_tris.push_back(t);
            boxes.push_back(bx);
        }
    }
    // The railings' planes (WorldMesh::railingPanels): the bars and rails have gaps a ray or a
    // sphere slips through, and the eye went among them (pm26 fence) or the boom through them,
    // leaving the third-person camera behind the plaza fence looking through it for 9 s
    // (feel25). For the camera a railing is a sheet, from either side.
    // GTA2DX9_RAILING_SHEETS=0: without them, as before (for a before/after run).
    bool sheets = true;
#ifndef EYECOL_NATIVE
    {
        char v[8] = {};
        if (GetEnvironmentVariableA("GTA2DX9_RAILING_SHEETS", v, sizeof v) && v[0] == '0') sheets = false;
    }
#endif
    int panels = 0;
    struct PanelBox { Vec3 lo, hi, p0, n; };
    std::vector<PanelBox> panelBoxes;
    for (size_t k = 0; sheets && k + 12 <= mesh.railingPanels.size(); k += 12) {
        const float* f = &mesh.railingPanels[k];
        {
            PanelBox pb{{f[0], f[1], f[2]}, {f[0], f[1], f[2]}, {f[0], f[1], f[2]}, {0.0f, 0.0f, 0.0f}};
            for (int i = 1; i < 4; ++i) {
                pb.lo = {(std::min)(pb.lo.x, f[i * 3]), (std::min)(pb.lo.y, f[i * 3 + 1]), (std::min)(pb.lo.z, f[i * 3 + 2])};
                pb.hi = {(std::max)(pb.hi.x, f[i * 3]), (std::max)(pb.hi.y, f[i * 3 + 1]), (std::max)(pb.hi.z, f[i * 3 + 2])};
            }
            const Vec3 nn = gta2::Cross(Sub(Vec3{f[3], f[4], f[5]}, pb.p0), Sub(Vec3{f[6], f[7], f[8]}, pb.p0));
            const float nl = Len(nn);
            if (nl > 1e-9f) { pb.n = nn * (1.0f / nl); panelBoxes.push_back(pb); }
        }
        const uint32_t base = static_cast<uint32_t>(g_pos.size());
        for (int i = 0; i < 4; ++i) g_pos.push_back({f[i * 3], f[i * 3 + 1], f[i * 3 + 2]});
        for (const std::array<uint32_t, 3> tri : {std::array<uint32_t, 3>{0, 1, 2}, std::array<uint32_t, 3>{0, 2, 3}}) {
            Tri t;
            for (int i = 0; i < 3; ++i) t.v[i] = base + tri[static_cast<size_t>(i)];
            const Vec3& a = g_pos[t.v[0]]; const Vec3& b = g_pos[t.v[1]]; const Vec3& c = g_pos[t.v[2]];
            Vec3 n = gta2::Cross(Sub(b, a), Sub(c, a));
            const float len = Len(n);
            if (len < 1e-9f) continue;
            n = n * (1.0f / len);
            t.n[0] = static_cast<int8_t>(std::lround(n.x * 127.0f));
            t.n[1] = static_cast<int8_t>(std::lround(n.y * 127.0f));
            t.n[2] = static_cast<int8_t>(std::lround(n.z * 127.0f));
            t.flags = kTwoSided | kPanel;
            t.tile = 0;
            const float lx = (std::min)({a.x, b.x, c.x}), hx = (std::max)({a.x, b.x, c.x});
            const float lz = (std::min)({a.z, b.z, c.z}), hz = (std::max)({a.z, b.z, c.z});
            const auto last = [](float lo, float hi) {
                const float cc = std::ceil(hi) - 1.0f;
                return static_cast<int>(hi > lo && cc >= std::floor(lo) ? cc : std::floor(hi));
            };
            Box bx{static_cast<int16_t>((std::max)(0, static_cast<int>(std::floor(lx)))),
                   static_cast<int16_t>((std::max)(0, static_cast<int>(std::floor(lz)))),
                   static_cast<int16_t>((std::min)(kGrid - 1, last(lx, hx))),
                   static_cast<int16_t>((std::min)(kGrid - 1, last(lz, hz)))};
            if (bx.x0 > bx.x1 || bx.z0 > bx.z1) continue;
            for (int z = bx.z0; z <= bx.z1; ++z)
                for (int x = bx.x0; x <= bx.x1; ++x) ++counts[static_cast<size_t>(z) * kGrid + x];
            g_tris.push_back(t);
            boxes.push_back(bx);
        }
        ++panels;
    }
    g_cellStart.assign(static_cast<size_t>(kGrid) * kGrid + 1, 0);
    for (size_t c = 0; c < counts.size(); ++c) g_cellStart[c + 1] = g_cellStart[c] + counts[c];
    g_cellTris.assign(g_cellStart.back(), 0);
    std::vector<uint32_t> fill(g_cellStart.begin(), g_cellStart.end() - 1);
    for (size_t i = 0; i < g_tris.size(); ++i) {
        const Box& bx = boxes[i];
        for (int z = bx.z0; z <= bx.z1; ++z)
            for (int x = bx.x0; x <= bx.x1; ++x) g_cellTris[fill[static_cast<size_t>(z) * kGrid + x]++] = static_cast<uint32_t>(i);
    }
    g_stamp.assign(g_tris.size(), 0u);
    g_query = 0;
    // FIX-CAMERA-6 (pfeel3): the faces of a railing's bars, rails and finials (QB-11, one-sided boxes 0.08 thick
    // on the railing's plane) are marked: the chase boom stops at a wall at once but eases in at a see-through
    // railing (SegmentHitSolid leaves them out). Every one-sided face with all three corners within kBarSlab of a
    // railing sheet's plane and inside its box (grown by kBarSlab) is one.
    int bars = 0;
    {
        constexpr float kBarSlab = 0.15f;
        for (const PanelBox& pb : panelBoxes) {
            const int x0 = (std::max)(0, static_cast<int>(std::floor(pb.lo.x - kBarSlab)));
            const int x1 = (std::min)(kGrid - 1, static_cast<int>(std::floor(pb.hi.x + kBarSlab)));
            const int z0 = (std::max)(0, static_cast<int>(std::floor(pb.lo.z - kBarSlab)));
            const int z1 = (std::min)(kGrid - 1, static_cast<int>(std::floor(pb.hi.z + kBarSlab)));
            for (int z = z0; z <= z1; ++z)
                for (int x = x0; x <= x1; ++x) {
                    const size_t c = static_cast<size_t>(z) * kGrid + x;
                    for (uint32_t e = g_cellStart[c]; e < g_cellStart[c + 1]; ++e) {
                        Tri& t = g_tris[g_cellTris[e]];
                        if (t.flags & (kTwoSided | kBar)) continue;
                        bool on = true;
                        for (int i = 0; i < 3 && on; ++i) {
                            const Vec3& v = g_pos[t.v[i]];
                            on = v.x >= pb.lo.x - kBarSlab && v.x <= pb.hi.x + kBarSlab && v.y >= pb.lo.y - kBarSlab &&
                                 v.y <= pb.hi.y + kBarSlab && v.z >= pb.lo.z - kBarSlab && v.z <= pb.hi.z + kBarSlab &&
                                 std::fabs(gta2::Dot(Sub(v, pb.p0), pb.n)) < kBarSlab;
                        }
                        if (on) { t.flags |= kBar; ++bars; }
                    }
                }
        }
    }
    // The caps' colour: each tile's mean, at 45% (the inside of a wall is in its own shadow).
    g_tileTone.assign(static_cast<size_t>((std::max)(style.TileCount(), 1)), 0xFF2A2826u);
    g_tileSeeThrough.assign(g_tileTone.size(), 0);
    for (int i = 0; i < style.TileCount(); ++i) {
        const gta2::Tile& tile = style.GetTile(i);
        if (tile.pixels.empty()) continue;
        uint64_t r = 0, g = 0, b = 0, n = 0, holes = 0;
        for (uint32_t px : tile.pixels) {
            if ((px >> 24) < 128) { ++holes; continue; }
            r += (px >> 16) & 0xFF; g += (px >> 8) & 0xFF; b += px & 0xFF; ++n;
        }
        if (holes * 20 > tile.pixels.size()) g_tileSeeThrough[static_cast<size_t>(i)] = 1;
        if (!n) continue;
        const auto dark = [&](uint64_t s) { return static_cast<uint32_t>((s / n) * 45 / 100); };
        g_tileTone[static_cast<size_t>(i)] = 0xFF000000u | (dark(r) << 16) | (dark(g) << 8) | dark(b);
    }
    g_ready = !g_tris.empty();
#ifndef EYECOL_NATIVE
    // GTA2DX9_EYE_COLLISION=0: off, the cell tests alone as before (for a before/after run).
    char off[8] = {};
    if (GetEnvironmentVariableA("GTA2DX9_EYE_COLLISION", off, sizeof off) && off[0] == '0') {
        g_ready = false;
        Log("eye collision: off (GTA2DX9_EYE_COLLISION=0)");
    }
#endif
    Log("eye collision: %zu triangles of the world mesh in a %dx%d grid (%zu cell entries, %.1f MB), %d railing panels as sheets, %d bar faces on them",
        g_tris.size(), kGrid, kGrid, g_cellTris.size(),
        (g_pos.size() * sizeof(Vec3) + g_tris.size() * (sizeof(Tri) + 4) + g_cellTris.size() * 4 + g_cellStart.size() * 4) / 1048576.0, panels, bars);
}

bool Ready() { return g_ready; }

namespace { bool g_panelsOnly = false; }

float PushPanels(Vec3* p, float radius) {
    g_panelsOnly = true;
    const float moved = Push(p, radius);
    g_panelsOnly = false;
    return moved;
}

float Push(Vec3* p, float radius) {
    if (!g_ready) return 0.0f;
    const Vec3 start = *p;
    for (int pass = 0; pass < 6; ++pass) {
        // The deepest overlap first, one at a time: in a corner the two pushes add up
        // instead of fighting.
        float bestDepth = 0.0f;
        Vec3 bestDir{};
        ForTris(p->x - radius, p->z - radius, p->x + radius, p->z + radius, [&](const Tri& t) {
            // Flat floors count too: the floor under him is 0.43 below the eye, out of reach, but
            // the top of a low wall or a planter at eye height is not.
            if (g_panelsOnly && !(t.flags & kPanel)) return;
            const Vec3& a = g_pos[t.v[0]]; const Vec3& b = g_pos[t.v[1]]; const Vec3& c = g_pos[t.v[2]];
            if (p->y < (std::min)({a.y, b.y, c.y}) - radius || p->y > (std::max)({a.y, b.y, c.y}) + radius) return;
            const Vec3 n = N(t);
            const float s = gta2::Dot(Sub(*p, a), n);
            if (std::fabs(s) >= radius) return;
            const Vec3 q = ClosestOnTri(*p, a, b, c);
            Vec3 d = Sub(*p, q);
            const float dist = Len(d);
            if (dist >= radius) return;
            // Behind a one-sided face, square to it: inside the block (SegmentHit's case, never
            // pushed through). Behind its plane but off its edge: the edge counts - a face
            // missing next to it (a ramp's riser) must not let the near plane reach the gap.
            if (!(t.flags & kTwoSided) && s < 0.0f && dist - std::fabs(s) < 1e-3f) return;
            if (dist < 1e-5f) d = s >= 0.0f ? n : n * -1.0f;
            else d = d * (1.0f / dist);
            const float depth = radius - dist;
            if (depth > bestDepth) { bestDepth = depth; bestDir = d; }
        });
        if (bestDepth <= 0.0f) break;
        // Sideways where it can be: the eye keeps its height (his eyes do not sink at a ramp's
        // edge), unless the surface is almost straight above or below.
        const float h = std::sqrt(bestDir.x * bestDir.x + bestDir.z * bestDir.z);
        if (h > 0.6f) {
            const Vec3 side{bestDir.x / h, 0.0f, bestDir.z / h};
            *p = *p + side * ((bestDepth + 0.002f) / h);
        } else {
            *p = *p + bestDir * (bestDepth + 0.002f);
        }
    }
    return Len(Sub(*p, start));
}

namespace { bool g_wallsOnly = false, g_solidOnly = false; float g_nearSoftSkip = 0.0f; }

void SetNearSoftSkip(float distance) { g_nearSoftSkip = (std::max)(0.0f, distance); }
float NearSoftSkip() { return g_nearSoftSkip; }

bool SegmentHit(const Vec3& a, const Vec3& b, float* tOut) {
    if (!g_ready) return false;
    const Vec3 d = Sub(b, a);
    float best = 2.0f;
    ForTris((std::min)(a.x, b.x), (std::min)(a.z, b.z), (std::max)(a.x, b.x), (std::max)(a.z, b.z), [&](const Tri& t) {
        // Roofs count: a view transition comes down from above (bil run occl_walls_bil: the
        // move into third person went in through a lid and was inside the block for a frame).
        const Vec3 n = N(t);
        if ((t.flags & kTwoSided) && g_wallsOnly) return;
        if ((t.flags & (kTwoSided | kBar)) && g_solidOnly) return;
        if (!(t.flags & kTwoSided) && gta2::Dot(d, n) >= 0.0f) return;   // leaving through the back: culled, and no wall
        float tt;
        if (SegTri(a, d, g_pos[t.v[0]], g_pos[t.v[1]], g_pos[t.v[2]], &tt) && tt < best) {
            // FIX-CAMERA-7: a sheet or a bar crossed within g_nearSoftSkip of the start is one the start is
            // leaning on (see SetNearSoftSkip), not one in the way.
            if (g_nearSoftSkip > 0.0f && (t.flags & (kTwoSided | kBar)) && tt * Len(d) < g_nearSoftSkip) return;
            best = tt;
        }
    });
    if (best > 1.0f) return false;
    *tOut = best;
    return true;
}

bool SegmentBlocked(const Vec3& a, const Vec3& b, float skipA) {
    if (!g_ready) return false;
    const Vec3 d = Sub(b, a);
    const float len = Len(d);
    if (len < 1e-4f) return false;
    const float tSkip = skipA / len;
    auto cellHit = [&](int cx, int cz) {
        if (cx < 0 || cz < 0 || cx >= kGrid || cz >= kGrid) return false;
        const size_t cell = static_cast<size_t>(cz) * kGrid + cx;
        for (uint32_t k = g_cellStart[cell]; k < g_cellStart[cell + 1]; ++k) {
            const Tri& t = g_tris[g_cellTris[k]];
            if (t.flags & (kTwoSided | kPanel | kBar)) continue;
            if (gta2::Dot(d, N(t)) >= 0.0f) continue;   // from behind: no wall
            float tt;
            if (SegTri(a, d, g_pos[t.v[0]], g_pos[t.v[1]], g_pos[t.v[2]], &tt) && tt > tSkip) return true;
        }
        return false;
    };
    // Amanatides-Woo over the one-block cells of the segment's ground track.
    int cx = static_cast<int>(std::floor(a.x)), cz = static_cast<int>(std::floor(a.z));
    const int ex = static_cast<int>(std::floor(b.x)), ez = static_cast<int>(std::floor(b.z));
    const int sx = d.x > 0.0f ? 1 : -1, sz = d.z > 0.0f ? 1 : -1;
    const float inf = 1e30f;
    const float dtx = std::fabs(d.x) > 1e-9f ? std::fabs(1.0f / d.x) : inf, dtz = std::fabs(d.z) > 1e-9f ? std::fabs(1.0f / d.z) : inf;
    float tx = std::fabs(d.x) > 1e-9f ? ((sx > 0 ? (cx + 1.0f - a.x) : (a.x - cx)) * dtx) : inf;
    float tz = std::fabs(d.z) > 1e-9f ? ((sz > 0 ? (cz + 1.0f - a.z) : (a.z - cz)) * dtz) : inf;
    for (int guard = 0; guard < 2 * kGrid; ++guard) {
        if (cellHit(cx, cz)) return true;
        if (cx == ex && cz == ez) break;
        if (tx < tz) { if (tx > 1.0f) break; cx += sx; tx += dtx; }
        else { if (tz > 1.0f) break; cz += sz; tz += dtz; }
    }
    return false;
}

bool SegmentHitSolid(const Vec3& a, const Vec3& b, float* t) {
    g_solidOnly = true;
    const bool hit = SegmentHit(a, b, t);
    g_solidOnly = false;
    return hit;
}

bool SegmentHitWalls(const Vec3& a, const Vec3& b, float* t) {
    g_wallsOnly = true;
    const bool hit = SegmentHit(a, b, t);
    g_wallsOnly = false;
    return hit;
}

float Nearest(const Vec3& p, float maxR) {
    if (!g_ready) return maxR;
    float best = maxR;
    ForTris(p.x - maxR, p.z - maxR, p.x + maxR, p.z + maxR, [&](const Tri& t) {
        const Vec3 q = ClosestOnTri(p, g_pos[t.v[0]], g_pos[t.v[1]], g_pos[t.v[2]]);
        best = (std::min)(best, Len(Sub(p, q)));
    });
    return best;
}

int FirstSide(const Vec3& o, const Vec3& d, float maxT, Vec3* normal = nullptr);

float Clear(const Vec3& head, Vec3* eye, float radius) {
    if (!g_ready) return 0.0f;
    const Vec3 start = *eye;
    // Standing inside a thin post or a railing's bars (the game walks him into props it does
    // not know; ste run probe: a 0.25 column round his centre): the panels round him may not
    // hold the eye in, or no place in the post is clear of them. Walls still do.
    bool boxed = true;
    for (const Vec3 d : {Vec3{1, 0, 0}, Vec3{-1, 0, 0}, Vec3{0, 0, 1}, Vec3{0, 0, -1}})
        if (FirstSide(head, d, 0.35f) == 0) { boxed = false; break; }
    struct Restore { ~Restore() { g_wallsOnly = false; } } restore;
    g_wallsOnly = boxed;
    for (int round = 0; round < 3; ++round) {
        float t;
        const Vec3 span = Sub(*eye, head);
        const float len = Len(span);
        if (len > 1e-4f && SegmentHit(head, *eye, &t)) {
            // Stopped short of the face; the push below takes it the rest of the way clear.
            const float keep = (std::max)(0.0f, t * len - radius) / len;
            *eye = head + span * keep;
            if (round == 0) NoteSegmentStop();
        }
        Push(eye, radius);
        // The push must not have carried it through something else.
        const Vec3 span2 = Sub(*eye, head);
        if (Len(span2) < 1e-4f || !SegmentHit(head, *eye, &t)) break;
    }
    if (boxed && Nearest(*eye, radius) < radius - 0.02f) {
        // Still among the post's faces: out of it, the clear place nearest where the eye was meant.
        Vec3 best = *eye;
        float bestD = 1e9f;
        for (int k = 0; k < 8; ++k) {
            const float a = static_cast<float>(k) * 0.78539816f;
            for (const float r : {0.3f, 0.4f, 0.5f}) {
                Vec3 c{head.x + std::sin(a) * r, eye->y, head.z + std::cos(a) * r};
                float t;
                if (SegmentHit(head, c, &t)) continue;   // never through a wall
                Push(&c, radius);
                if (Nearest(c, radius) < radius - 0.02f) continue;
                const float d = Len(Sub(c, start));
                if (d < bestD) { bestD = d; best = c; }
            }
        }
        *eye = best;
    }
    const float moved = Len(Sub(*eye, start));
    if (moved > 1e-4f) {
        ++g_stats.pushes;
        g_stats.maxPush = (std::max)(g_stats.maxPush, moved);
    }
    return moved;
}

// The first surface along o + d*t, t in (0, maxT]: +1 a front (or two-sided) face, -1 the back
// of a one-sided face, 0 none.
int FirstSide(const Vec3& o, const Vec3& d, float maxT, Vec3* normal) {
    const Vec3 e = o + d * maxT;
    float best = 2.0f; int side = 0;
    ForTris((std::min)(o.x, e.x), (std::min)(o.z, e.z), (std::max)(o.x, e.x), (std::max)(o.z, e.z), [&](const Tri& t) {
        float tt;
        if (!SegTri(o, e - o, g_pos[t.v[0]], g_pos[t.v[1]], g_pos[t.v[2]], &tt) || tt <= 1e-5f || tt >= best) return;
        best = tt;
        side = (t.flags & kTwoSided) || gta2::Dot(d, N(t)) < 0.0f ? 1 : -1;
        if (normal) *normal = N(t);
    });
    return side;
}

bool InsideSolid(const Vec3& p) {
    if (!g_ready) return false;
    // Inside a block: straight up is the back of its roof (a lid facing up, seen from under
    // it), and every one of eight ways out sideways leaves through the back of a face, none
    // through a front. An open courtyard (nothing above), a porch or an arcade (a way out to
    // the street) and a rooftop walled by faces that look outward (vreg bank_chase: the backs
    // all round, but sky above) are not inside.
    Vec3 roof{};
    if (FirstSide(p, {0, 1, 0}, 12.0f, &roof) >= 0 || roof.y < 0.7f) return false;
    for (int k = 0; k < 8; ++k) {
        const float a = static_cast<float>(k) * 0.78539816f;
        if (FirstSide(p, {std::sin(a), 0.0f, std::cos(a)}, 12.0f) >= 0) return false;
    }
    return true;
}

#ifndef EYECOL_NATIVE
void DrawInteriorCaps(IDirect3DDevice9* device, const Vec3& eye, DWORD worldCull) {
    g_stats.capTris = 0;
    if (!g_ready || !device) return;
    // Only with the eye inside a block (the collision failed, or a fixed camera put it there):
    // outside one, the backs of faces are either behind their own fronts or a hole in the
    // world (FIX-WORLD's), and a cap switched on as he nears a wall would pop. The reach
    // covers the largest building block.
    constexpr float kReach = 6.0f;
    if (!InsideSolid(eye)) return;
    struct V { float x, y, z; DWORD c; };
    static std::vector<V> verts;
    verts.clear();
    ForTris(eye.x - kReach, eye.z - kReach, eye.x + kReach, eye.z + kReach, [&](const Tri& t) {
        if (t.flags & kTwoSided) return;   // a two-sided panel is already drawn from both sides
        const Vec3& a = g_pos[t.v[0]]; const Vec3& b = g_pos[t.v[1]]; const Vec3& c = g_pos[t.v[2]];
        if ((std::max)({a.y, b.y, c.y}) < eye.y - kReach || (std::min)({a.y, b.y, c.y}) > eye.y + kReach) return;
        // Only faces the eye is behind: the rest would be culled anyway.
        const Vec3 n = N(t);
        if (gta2::Dot(Sub(eye, a), n) >= 0.0f) return;
        if (t.tile < g_tileSeeThrough.size() && g_tileSeeThrough[t.tile]) return;
        const DWORD col = t.tile < g_tileTone.size() ? g_tileTone[t.tile] : 0xFF2A2826u;
        // A few millimetres into the block, so a face of the next block on the same plane
        // (looking the other way, drawn) always wins the depth test.
        const Vec3 in = n * -0.004f;
        verts.push_back({a.x + in.x, a.y + in.y, a.z + in.z, col});
        verts.push_back({b.x + in.x, b.y + in.y, b.z + in.z, col});
        verts.push_back({c.x + in.x, c.y + in.y, c.z + in.z, col});
    });
    if (verts.empty()) return;
    g_stats.capTris = static_cast<int>(verts.size() / 3);
    DWORD lighting, cull, alphaBlend, alphaTest, colorOp, colorArg, alphaOp, op1;
    IDirect3DBaseTexture9* tex0 = nullptr;
    IDirect3DVertexShader9* vs = nullptr;
    IDirect3DPixelShader9* ps = nullptr;
    DWORD fvf;
    device->GetRenderState(D3DRS_LIGHTING, &lighting);
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &alphaBlend);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &alphaTest);
    device->GetTextureStageState(0, D3DTSS_COLOROP, &colorOp);
    device->GetTextureStageState(0, D3DTSS_COLORARG1, &colorArg);
    device->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
    device->GetTextureStageState(1, D3DTSS_COLOROP, &op1);
    device->GetTexture(0, &tex0);
    device->GetVertexShader(&vs);
    device->GetPixelShader(&ps);
    device->GetFVF(&fvf);

    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetVertexShader(nullptr);
    device->SetPixelShader(nullptr);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    // The world culls `worldCull`; the caps are the same triangles seen from behind.
    device->SetRenderState(D3DRS_CULLMODE, worldCull == D3DCULL_CW ? D3DCULL_CCW : worldCull == D3DCULL_CCW ? D3DCULL_CW : D3DCULL_NONE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE);
    device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts.size() / 3), verts.data(), sizeof(V));

    device->SetFVF(fvf);
    device->SetVertexShader(vs);
    device->SetPixelShader(ps);
    if (vs) vs->Release();
    if (ps) ps->Release();
    device->SetTexture(0, tex0);
    if (tex0) tex0->Release();
    device->SetTextureStageState(1, D3DTSS_COLOROP, op1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, colorArg);
    device->SetTextureStageState(0, D3DTSS_COLOROP, colorOp);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTest);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, alphaBlend);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetRenderState(D3DRS_LIGHTING, lighting);
}

#else
void DebugNear(const Vec3& p, float r) {
    ForTris(p.x - r, p.z - r, p.x + r, p.z + r, [&](const Tri& t) {
        const Vec3& a = g_pos[t.v[0]]; const Vec3& b = g_pos[t.v[1]]; const Vec3& c = g_pos[t.v[2]];
        const Vec3 q = ClosestOnTri(p, a, b, c);
        const float d = Len(Sub(p, q));
        if (d >= r) return;
        const Vec3 n = N(t);
        std::printf("  tri d %.3f s %.3f n %.2f %.2f %.2f flags %d tile %d  a %.2f %.2f %.2f b %.2f %.2f %.2f c %.2f %.2f %.2f\n", d,
                    gta2::Dot(Sub(p, a), n), n.x, n.y, n.z, t.flags, t.tile, a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
    });
}
#endif

Stats TakeStats() {
    const Stats s = g_stats;
    g_stats = Stats{};
    return s;
}

void NoteSegmentStop() { ++g_stats.segmentStops; }

}  // namespace eyecol
