// Casts rays through the static world mesh the street views draw, to find where a
// camera sees through the city (a hole) without launching the game.
//
//   world_raycast pano <map.gmp> <style.sty> <x> <y> <z> <out.ppm> [mode]
//       An equirectangular panorama (1 px per 0.5 deg, heading 0..360 left to
//       right from north, pitch +30..-90 top to bottom) from the world point x,y,z
//       (the renderer log's "fp eye"). Colours: a front face grey by its normal,
//       darker with distance; a back face of a one-sided batch (culled, so the sky
//       shows) blue; the seal under the world red; nothing at all magenta.
//       mode "street" also counts the street-view-only fill (see world_mesh.h).
//   world_raycast scan <map.gmp> <style.sty> [step] [mode]
//       From an eye 1.7 above every walkable lid on a grid of `step` cells, rays
//       below the horizon; prints each cell whose rays see the seal, a culled back
//       face or nothing within 120 blocks, worst first, with where the ray went
//       through (the leaking cell).
//
// Built natively (g++ -O2 -std=c++17 tools/world_raycast.cpp src/world_mesh.cpp
// src/gta2_map.cpp src/gta2_style.cpp -Isrc -o world_raycast).
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "../src/gta2_map.h"
#include "../src/gta2_style.h"
#include "../src/world_mesh.h"

namespace {

struct Tri {
    float a[3], e1[3], e2[3];
    float n[3];        // geometric normal from the winding
    float vn[3];       // the vertex normal (what the builder says it faces)
    int batch;
};

enum Hit { kNone = 0, kFront, kBack, kSeal };

struct Scene {
    std::vector<Tri> tris;
    std::vector<gta2::TileBatch> batches;
    int sealTile = -1;
    std::vector<std::vector<int>> grid;   // 256x256 cells, triangles by bbox
    std::vector<int> big;                 // triangles too large for the grid

    void Build(const gta2::WorldMesh& mesh) {
        batches = mesh.batches;
        grid.assign(256 * 256, {});
        for (size_t b = 0; b < mesh.batches.size(); ++b) {
            const auto& batch = mesh.batches[b];
            for (uint32_t i = batch.indexStart; i + 2 < batch.indexStart + batch.indexCount; i += 3) {
                const gta2::Vertex& p0 = mesh.vertices[mesh.indices[i]];
                const gta2::Vertex& p1 = mesh.vertices[mesh.indices[i + 1]];
                const gta2::Vertex& p2 = mesh.vertices[mesh.indices[i + 2]];
                Tri t;
                t.a[0] = p0.x; t.a[1] = p0.y; t.a[2] = p0.z;
                t.e1[0] = p1.x - p0.x; t.e1[1] = p1.y - p0.y; t.e1[2] = p1.z - p0.z;
                t.e2[0] = p2.x - p0.x; t.e2[1] = p2.y - p0.y; t.e2[2] = p2.z - p0.z;
                t.n[0] = t.e1[1] * t.e2[2] - t.e1[2] * t.e2[1];
                t.n[1] = t.e1[2] * t.e2[0] - t.e1[0] * t.e2[2];
                t.n[2] = t.e1[0] * t.e2[1] - t.e1[1] * t.e2[0];
                t.vn[0] = p0.nx; t.vn[1] = p0.ny; t.vn[2] = p0.nz;
                t.batch = static_cast<int>(b);
                const int idx = static_cast<int>(tris.size());
                tris.push_back(t);
                float lo[2] = {std::min({p0.x, p1.x, p2.x}), std::min({p0.z, p1.z, p2.z})};
                float hi[2] = {std::max({p0.x, p1.x, p2.x}), std::max({p0.z, p1.z, p2.z})};
                if (hi[0] - lo[0] > 3 || hi[1] - lo[1] > 3) { big.push_back(idx); continue; }
                for (int z = std::max(0, (int)std::floor(lo[1] - 1e-3f)); z <= std::min(255, (int)std::floor(hi[1] + 1e-3f)); ++z)
                    for (int x = std::max(0, (int)std::floor(lo[0] - 1e-3f)); x <= std::min(255, (int)std::floor(hi[0] + 1e-3f)); ++x)
                        grid[z * 256 + x].push_back(idx);
            }
        }
    }

    // Möller-Trumbore; returns t or -1.
    static float Intersect(const Tri& t, const float o[3], const float d[3]) {
        const float p[3] = {d[1] * t.e2[2] - d[2] * t.e2[1], d[2] * t.e2[0] - d[0] * t.e2[2], d[0] * t.e2[1] - d[1] * t.e2[0]};
        const float det = t.e1[0] * p[0] + t.e1[1] * p[1] + t.e1[2] * p[2];
        if (std::fabs(det) < 1e-9f) return -1;
        const float inv = 1.0f / det;
        const float s[3] = {o[0] - t.a[0], o[1] - t.a[1], o[2] - t.a[2]};
        const float u = (s[0] * p[0] + s[1] * p[1] + s[2] * p[2]) * inv;
        if (u < -1e-5f || u > 1.0f + 1e-5f) return -1;
        const float q[3] = {s[1] * t.e1[2] - s[2] * t.e1[1], s[2] * t.e1[0] - s[0] * t.e1[2], s[0] * t.e1[1] - s[1] * t.e1[0]};
        const float v = (d[0] * q[0] + d[1] * q[1] + d[2] * q[2]) * inv;
        if (v < -1e-5f || u + v > 1.0f + 1e-5f) return -1;
        const float tt = (t.e2[0] * q[0] + t.e2[1] * q[1] + t.e2[2] * q[2]) * inv;
        return tt > 1e-4f ? tt : -1;
    }

    // Front/back from the vertex normal (the builder's facing); D3D culls by winding,
    // and the builder winds every quad to match its normal.
    Hit Classify(const Tri& t, const float d[3], bool* culled) const {
        const float dn = t.vn[0] * d[0] + t.vn[1] * d[1] + t.vn[2] * d[2];
        const auto& b = batches[t.batch];
        if (b.tile == sealTile) return kSeal;
        const bool back = dn > 0;
        *culled = back && !b.doubleSided;
        return back ? kBack : kFront;
    }

    struct Result { Hit hit = kNone; float t = 0; int tri = -1; };

    Result Cast(const float o[3], const float d[3], float maxT) const {
        Result best; best.t = maxT;
        auto test = [&](int idx) {
            const Tri& t = tris[idx];
            const float tt = Intersect(t, o, d);
            if (tt < 0 || tt >= best.t) return;
            bool culled = false;
            const Hit h = Classify(t, d, &culled);
            if (h == kBack && culled) {
                // Culled: invisible, the ray goes on. Remember it as the cause if nothing else is hit.
                return;
            }
            best.hit = h; best.t = tt; best.tri = idx;
        };
        for (int idx : big) test(idx);
        // 2D DDA over x,z.
        float x = o[0], z = o[2];
        int cx = (int)std::floor(x), cz = (int)std::floor(z);
        const int sx = d[0] > 0 ? 1 : -1, sz = d[2] > 0 ? 1 : -1;
        const float tdx = std::fabs(d[0]) > 1e-9f ? std::fabs(1.0f / d[0]) : 1e30f;
        const float tdz = std::fabs(d[2]) > 1e-9f ? std::fabs(1.0f / d[2]) : 1e30f;
        float tmx = std::fabs(d[0]) > 1e-9f ? ((sx > 0 ? (cx + 1 - x) : (x - cx)) * tdx) : 1e30f;
        float tmz = std::fabs(d[2]) > 1e-9f ? ((sz > 0 ? (cz + 1 - z) : (z - cz)) * tdz) : 1e30f;
        float tcell = 0;
        while (tcell < best.t) {
            if (cx >= 0 && cz >= 0 && cx < 256 && cz < 256) {
                // Neighbours too: a triangle on a cell border is binned on both sides, but
                // the epsilon above keeps this cheap.
                for (int idx : grid[cz * 256 + cx]) test(idx);
            } else if ((cx < -1 && sx < 0) || (cz < -1 && sz < 0) || (cx > 256 && sx > 0) || (cz > 256 && sz > 0)) {
                break;
            }
            // Below the seal: nothing more can be hit.
            if (o[1] + d[1] * tcell < -gta2::kSealDepth - 0.5f) break;
            if (tmx < tmz) { tcell = tmx; tmx += tdx; cx += sx; } else { tcell = tmz; tmz += tdz; cz += sz; }
        }
        return best;
    }
};

gta2::Map g_map;
gta2::Style g_style;
bool g_streetFill = true;

bool LoadScene(const char* mapPath, const char* stylePath, Scene* scene) {
    std::string error;
    gta2::Map& map = g_map;
    gta2::Style& style = g_style;
    if (!map.Load(mapPath, &error) || !style.Load(stylePath, &error)) {
        fprintf(stderr, "load: %s\n", error.c_str());
        return false;
    }
    gta2::PartialCuts cuts;
    gta2::WorldMesh mesh;
    gta2::BuildWorldMesh(map, style, nullptr, cuts, &mesh);
    scene->sealTile = gta2::SealTileIndex(style);
    if (!g_streetFill) {
        std::vector<gta2::TileBatch> kept;
        for (const auto& b : mesh.batches) if (!b.streetOnly) kept.push_back(b);
        mesh.batches = kept;
    }
    scene->Build(mesh);
    fprintf(stderr, "mesh: %zu triangles, %zu batches\n", scene->tris.size(), scene->batches.size());
    return true;
}

void Dir(float headingDeg, float pitchDeg, float d[3]) {
    const float h = headingDeg * 3.14159265f / 180.0f, p = pitchDeg * 3.14159265f / 180.0f;
    // Heading 0 = north. North is -Z in this frame (map y grows south, Z = 255 - y... +Z is south per
    // world_mesh.h) so north = -Z? world_mesh.h: +Z south... but the mesh mirrors rows, so +Z is north.
    d[0] = std::sin(h) * std::cos(p);
    d[1] = std::sin(p);
    d[2] = std::cos(h) * std::cos(p);
}

int Pano(const Scene& s, float ex, float ey, float ez, const char* out) {
    const int W = 720, H = 240;   // 0.5 deg; pitch +30 .. -90
    std::vector<unsigned char> img(W * H * 3);
    const float o[3] = {ex, ey, ez};
    for (int j = 0; j < H; ++j) {
        const float pitch = 30.0f - j * 0.5f;
        for (int i = 0; i < W; ++i) {
            float d[3];
            Dir(i * 0.5f, pitch, d);
            const Scene::Result r = s.Cast(o, d, 400.0f);
            unsigned char* px = &img[(j * W + i) * 3];
            if (r.hit == Hit::kNone) { px[0] = pitch < 0 ? 255 : 120; px[1] = 0; px[2] = pitch < 0 ? 255 : 120; }
            else if (r.hit == Hit::kSeal) { px[0] = 255; px[1] = 0; px[2] = 0; }
            else {
                const Tri& t = s.tris[r.tri];
                float shade = 0.55f + 0.45f * std::fabs(t.vn[1]) * 0.6f + 0.25f * std::fabs(t.vn[0]);
                shade *= 1.0f - std::min(0.6f, r.t / 200.0f);
                const int g = (int)(shade * 230);
                if (r.hit == Hit::kBack) { px[0] = g / 3; px[1] = g / 2; px[2] = g; }   // double-sided back, drawn
                else { px[0] = px[1] = px[2] = (unsigned char)g; }
            }
        }
    }
    // Horizon and every 90 deg marked.
    for (int i = 0; i < W; ++i) { unsigned char* px = &img[(60 * W + i) * 3]; px[1] = 255; }
    for (int i = 0; i < W; i += 180) for (int j = 0; j < H; ++j) { unsigned char* px = &img[(j * W + i) * 3]; px[0] = 255; px[1] = 255; px[2] = 0; }
    FILE* f = fopen(out, "wb");
    if (!f) return 1;
    fprintf(f, "P6 %d %d 255\n", W, H);
    fwrite(img.data(), 1, img.size(), f);
    fclose(f);
    return 0;
}

// Eye positions: 0.45 (first person) and 1.6 (chase) above every flat lid that has air
// above it, on cells every `step`; rays below the horizon. A ray is a leak when it
// ends on the seal or on nothing while it crosses level 0 inside the map.
int ScanHoles(const Scene& s, int step, int x0, int y0, int x1, int y1) {
    struct Leak { int ex, ey; float eh; int count; float hx, hz; };
    std::vector<Leak> leaks;
    std::map<std::pair<int,int>, int> landing;
    long rays = 0, bad = 0;
    for (int y = y0; y <= y1; y += step) {
        for (int x = x0; x <= x1; x += step) {
            const gta2::Column& col = g_map.ColumnAt(x, y);
            for (size_t i = 0; i < col.blocks.size(); ++i) {
                if (col.blocks[i] >= g_map.BlockCount()) continue;
                const gta2::Block& b = g_map.BlockAt(col.blocks[i]);
                if (!b.lid || b.lid.IsFlat() || b.SlopeType() != 0 || g_style.IsWaterTile(b.lid.Tile())) continue;
                if (i + 1 < col.blocks.size() && col.blocks[i + 1] < g_map.BlockCount()) {
                    const gta2::Block& a = g_map.BlockAt(col.blocks[i + 1]);
                    if (a.lid || a.SlopeType() != 0) continue;   // no room to stand
                }
                const float top = static_cast<float>(col.offset + i + 1);
                for (float eh : {0.45f, 1.6f}) {
                    // The eye must be in open air: no block with a lid, a slope or a wall at its level.
                    const int el = static_cast<int>(top + eh);
                    const int ei = el - col.offset;
                    if (ei >= 0 && ei < static_cast<int>(col.blocks.size()) && col.blocks[ei] < g_map.BlockCount()) {
                        const gta2::Block& eb = g_map.BlockAt(col.blocks[ei]);
                        if (eb.lid || eb.SlopeType() != 0 || eb.left || eb.right || eb.top || eb.bottom) continue;
                    }
                    const float o[3] = {x + 0.5f, top + eh, static_cast<float>(gta2::kMapHeight - y - 1) + 0.5f};
                    int count = 0; float hx = 0, hz = 0;
                    for (int h = 0; h < 360; h += 10) {
                        for (int p = -2; p >= -50; p -= 4) {
                            float d[3]; Dir((float)h, (float)p, d);
                            const Scene::Result r = s.Cast(o, d, 300.0f);
                            ++rays;
                            if (r.hit == kFront || r.hit == kBack) continue;
                            // Where it crossed level 0.
                            const float t0 = (o[1] - 0.0f) / -d[1];
                            const float cx = o[0] + d[0] * t0, cz = o[2] + d[2] * t0;
                            if (cx < 1 || cz < 1 || cx > 255 || cz > 255) continue;
                            ++count; ++bad; hx = cx; hz = cz;
                            landing[{(int)cx, gta2::kMapHeight - 1 - (int)cz}]++;
                        }
                    }
                    if (count) leaks.push_back({x, y, top + eh, count, hx, hz});
                }
            }
        }
    }
    std::sort(leaks.begin(), leaks.end(), [](const Leak& a, const Leak& b) { return a.count > b.count; });
    printf("rays %ld leaking %ld eyes-with-leaks %zu\n", rays, bad, leaks.size());
    for (size_t i = 0; i < leaks.size() && i < 40; ++i)
        printf("eye (%d,%d) h %.2f: %d rays, e.g. through map (%d,%d)\n", leaks[i].ex, leaks[i].ey, leaks[i].eh, leaks[i].count,
               (int)leaks[i].hx, gta2::kMapHeight - 1 - (int)leaks[i].hz);
    std::vector<std::pair<int, std::pair<int,int>>> lv;
    for (auto& kv : landing) lv.push_back({kv.second, kv.first});
    std::sort(lv.rbegin(), lv.rend());
    printf("landing cells (level-0 crossing):\n");
    for (size_t i = 0; i < lv.size() && i < 30; ++i) printf("  (%d,%d) %d\n", lv[i].second.first, lv[i].second.second, lv[i].first);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) { fprintf(stderr, "usage: see the header\n"); return 2; }
    if (getenv("NOFILL")) g_streetFill = false;
    Scene scene;
    if (!LoadScene(argv[2], argv[3], &scene)) return 1;
    if (!strcmp(argv[1], "pano") && argc >= 8) {
        return Pano(scene, (float)atof(argv[4]), (float)atof(argv[5]), (float)atof(argv[6]), argv[7]);
    }
    if (!strcmp(argv[1], "ray") && argc >= 9) {
        const float o[3] = {(float)atof(argv[4]), (float)atof(argv[5]), (float)atof(argv[6])};
        float d[3]; Dir((float)atof(argv[7]), (float)atof(argv[8]), d);
        const Scene::Result r = scene.Cast(o, d, 400.0f);
        printf("hit %d t %.2f at %.2f %.2f %.2f", (int)r.hit, r.t, o[0] + d[0] * r.t, o[1] + d[1] * r.t, o[2] + d[2] * r.t);
        if (r.tri >= 0) { const Tri& t = scene.tris[r.tri]; printf(" tile %d vn %.1f %.1f %.1f ds %d", scene.batches[t.batch].tile, t.vn[0], t.vn[1], t.vn[2], (int)scene.batches[t.batch].doubleSided); }
        printf("\n");
        return 0;
    }
    if (!strcmp(argv[1], "scan")) {
        const int step = argc >= 5 ? atoi(argv[4]) : 4;
        int x0 = 0, y0 = 0, x1 = 255, y1 = 255;
        if (argc >= 9) { x0 = atoi(argv[5]); y0 = atoi(argv[6]); x1 = atoi(argv[7]); y1 = atoi(argv[8]); }
        return ScanHoles(scene, step, x0, y0, x1, y1);
    }
    fprintf(stderr, "unknown command\n");
    return 2;
}
