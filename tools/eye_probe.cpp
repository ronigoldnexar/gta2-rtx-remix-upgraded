// Regression probe for BLOCKER fp-camera-sees-through-wall (FIX-OCCLUSION): does the street
// views' camera ever see through a wall from close to it? No game needed: the real map and
// style, the same world mesh the DLL draws, and the DLL's own eye collision (eye_collision.cpp).
//
//   eye_probe sweep <map.gmp> <style.sty> [x0 y0 x1 y1] [step]
//       Every walkable cell next to a surface (every `step`-th, default 1), 3x3 standing
//       points in it and 16 headings: the first-person eye as the game would place it (his
//       centre at eye height, 0.12 ahead), then as eyecol::Clear leaves it. For each eye a
//       5x4 fan of rays over the view frustum (75 deg vertical, 16:9) from the 0.05 near
//       plane: the eye SEES THROUGH a surface when a ray's first surface within 3 blocks is
//       the back of a one-sided face (culled: the inside of a block, a void, the sky), and it
//       is NEAR-CLIPPED when a surface is closer than 0.115 (the near plane's corner reach).
//       Prints both counts for the raw and the cleared eye, the worst cleared cases, and
//       exits 1 if any cleared eye sees through or is near-clipped.
//   eye_probe spots ...  (as sweep, and prints one place per 12x12 cells where the raw eye saw
//       through and the cleared one does not: map x,y, level, heading; for in-game checks)
//   eye_probe at <map.gmp> <style.sty> <hx> <hy> <hz> <heading deg>
//       One case: the raw and the cleared eye, distances and the verdicts.
//
// Built natively:
//   g++ -O2 -std=c++17 -DEYECOL_NATIVE tools/eye_probe.cpp dll/src/eye_collision.cpp \
//       src/world_mesh.cpp src/gta2_map.cpp src/gta2_style.cpp -Isrc -o eye_probe
#define main world_raycast_main
#include "world_raycast.cpp"
#undef main

#include "../dll/src/eye_collision.h"
namespace eyecol { void DebugNear(const gta2::Vec3& p, float r); }

namespace {

gta2::WorldMesh g_mesh;

// The first surface of any kind along o + d*t for t in (tMin, tMax): front, two-sided back,
// or a culled back (what the camera sees through).
struct Any { int kind = 0; float t = 0; };   // 0 none, 1 front/two-sided, 2 culled back
Any FirstAny(const Scene& s, const float o[3], const float d[3], float tMin, float tMax) {
    Any best; best.t = tMax;
    const float ex = o[0] + d[0] * tMax, ez = o[2] + d[2] * tMax;
    const int cx0 = std::max(0, (int)std::floor(std::min(o[0], ex)) - 1), cx1 = std::min(255, (int)std::floor(std::max(o[0], ex)) + 1);
    const int cz0 = std::max(0, (int)std::floor(std::min(o[2], ez)) - 1), cz1 = std::min(255, (int)std::floor(std::max(o[2], ez)) + 1);
    for (int cz = cz0; cz <= cz1; ++cz)
        for (int cx = cx0; cx <= cx1; ++cx)
            for (int idx : s.grid[cz * 256 + cx]) {
                const Tri& t = s.tris[idx];
                const float tt = Scene::Intersect(t, o, d);
                if (tt <= tMin || tt >= best.t) continue;
                bool culled = false;
                const Hit h = s.Classify(t, d, &culled);
                if (h == kSeal) continue;
                best.t = tt;
                best.kind = (h == kBack && culled) ? 2 : 1;
            }
    return best;
}

// The view from an eye looking along `heading` (deg, 0 = +Z): 0 clean, 1 sees through.
bool SeesThrough(const Scene& s, const gta2::Vec3& eye, float heading) {
    const float o[3] = {eye.x, eye.y, eye.z};
    float fwd[3]; Dir(heading, 0.0f, fwd);
    for (int j = 0; j < 4; ++j) {
        const float pitch = -30.0f + 20.0f * j;               // -30 .. +30
        for (int i = 0; i < 5; ++i) {
            const float yaw = heading - 50.0f + 25.0f * i;    // the 16:9 frustum's ~100 deg width
            float d[3]; Dir(yaw, pitch, d);
            const float along = d[0] * fwd[0] + d[1] * fwd[1] + d[2] * fwd[2];
            const float tNear = 0.05f / std::max(along, 0.2f);
            const Any a = FirstAny(s, o, d, tNear, 3.0f);
            if (a.kind == 2) return true;
        }
    }
    return false;
}

bool Walkable(int x, int y, float* floorY) {
    const gta2::Column& col = g_map.ColumnAt(x, y);
    for (size_t i = 0; i < col.blocks.size(); ++i) {
        if (col.blocks[i] >= g_map.BlockCount()) continue;
        const gta2::Block& b = g_map.BlockAt(col.blocks[i]);
        if (!b.lid || b.lid.IsFlat() || b.SlopeType() != 0 || g_style.IsWaterTile(b.lid.Tile())) continue;
        if (i + 1 < col.blocks.size() && col.blocks[i + 1] < g_map.BlockCount()) {
            const gta2::Block& a = g_map.BlockAt(col.blocks[i + 1]);
            if (a.lid && !a.lid.IsFlat()) continue;   // a ceiling on him: not a street
        }
        *floorY = static_cast<float>(col.offset + i + 1);
        // The top-most only: a street or a roof he can walk.
        bool higher = false;
        for (size_t k = i + 1; k < col.blocks.size(); ++k)
            if (col.blocks[k] < g_map.BlockCount() && g_map.BlockAt(col.blocks[k]).lid) higher = true;
        if (!higher) return true;
    }
    return false;
}

struct Case { float hx, hy, hz, heading, raw, clr, moved; };

bool g_spots = false;
int Sweep(const Scene& s, int x0, int y0, int x1, int y1, int step) {
    long n = 0, rawSee = 0, rawClip = 0, clrSee = 0, clrClip = 0, clrBehind = 0, holes = 0, capsOn = 0, outOfPost = 0;
    std::vector<Case> worst;
    for (int y = y0; y <= y1; y += step)
        for (int x = x0; x <= x1; x += step) {
            float floorY;
            if (!Walkable(x, y, &floorY)) continue;
            const float cz = static_cast<float>(gta2::kMapHeight - y - 1);
            // Only cells with a surface within a block of the eye.
            if (eyecol::Nearest({x + 0.5f, floorY + 0.43f, cz + 0.5f}, 1.2f) >= 1.2f) continue;
            for (int sy = 0; sy < 3; ++sy)
                for (int sx = 0; sx < 3; ++sx) {
                    const gta2::Vec3 head{x + 0.15f + 0.35f * sx, floorY + 0.43f, cz + 0.15f + 0.35f * sy};
                    // Where the game keeps him: not inside anything, not touching a face.
                    if (eyecol::Nearest(head, 0.08f) < 0.08f) continue;
                    {
                        int inside = 0;
                        for (int h = 0; h < 360; h += 45) {
                            const float o[3] = {head.x, head.y, head.z}; float d[3]; Dir((float)h, 0.0f, d);
                            if (FirstAny(s, o, d, 0.0f, 1.5f).kind == 2) ++inside;
                        }
                        if (inside >= 2) continue;
                    }
                    for (int k = 0; k < 16; ++k) {
                        const float heading = 22.5f * k;
                        float fwd[3]; Dir(heading, 0.0f, fwd);
                        const gta2::Vec3 raw{head.x + fwd[0] * 0.12f, head.y, head.z + fwd[2] * 0.12f};
                        gta2::Vec3 clr = raw;
                        const float moved = eyecol::Clear(head, &clr, 0.24f);
                        ++n;
                        const float rawNear = eyecol::Nearest(raw, 0.5f), clrNear = eyecol::Nearest(clr, 0.5f);
                        const bool rs = SeesThrough(s, raw, heading), cs = SeesThrough(s, clr, heading);
                        rawSee += rs; clrSee += cs;
                        if (g_spots && rs && !cs) {
                            static std::map<std::pair<int,int>, int> seen;
                            if (seen[{x / 12, y / 12}]++ == 0)
                                printf("SPOT map %.2f,%.2f level %d heading %.1f (raw near %.3f)\n", head.x,
                                       gta2::kMapHeight - head.z, (int)std::floor(head.y - 0.43f), heading, rawNear);
                        }
                        // Seen through from an eye well clear of every surface: a hole in the
                        // mesh (FIX-WORLD's class), not the camera's.
                        if (cs && clrNear >= 0.2f) { ++holes; clrSee--; }
                        rawClip += rawNear < 0.115f; clrClip += clrNear < 0.115f;
                        float t;
                        if (eyecol::SegmentHitWalls(head, clr, &t)) ++clrBehind;
                        else if (eyecol::SegmentHit(head, clr, &t)) ++outOfPost;   // through a post's panels he stood inside: by design
                        if (eyecol::InsideSolid(clr)) ++capsOn;   // the caps would draw: must never happen out in the street
                        if ((cs && clrNear < 0.2f) || clrNear < 0.115f) worst.push_back({head.x, head.y, head.z, heading, rawNear, clrNear, moved});
                    }
                }
        }
    printf("eyes %ld\n  raw (game placement):  sees through %ld, near-clipped %ld\n"
           "  cleared (eyecol):      sees through %ld, near-clipped %ld, behind a wall from his centre %ld\n"
           "  holes in the mesh seen from a clear eye (>= 0.2 from every surface; not the camera): %ld\n"
           "  cleared eyes judged inside a block (the caps would draw; must be 0): %ld\n"
           "  eyes taken out of a post or railing he stood inside (through its two-sided panels, by design): %ld\n",
           n, rawSee, rawClip, clrSee, clrClip, clrBehind, holes, capsOn, outOfPost);
    std::sort(worst.begin(), worst.end(), [](const Case& a, const Case& b) { return a.clr < b.clr; });
    for (size_t i = 0; i < worst.size() && i < 25; ++i)
        printf("  head %.2f %.2f %.2f heading %.1f: raw near %.3f, cleared near %.3f, moved %.3f\n", worst[i].hx, worst[i].hy,
               worst[i].hz, worst[i].heading, worst[i].raw, worst[i].clr, worst[i].moved);
    return (clrSee || clrClip || clrBehind || capsOn) ? 1 : 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) { fprintf(stderr, "usage: see the header\n"); return 2; }
    std::string error;
    if (!g_map.Load(argv[2], &error) || !g_style.Load(argv[3], &error)) { fprintf(stderr, "load: %s\n", error.c_str()); return 1; }
    gta2::PartialCuts cuts;
    gta2::BuildWorldMesh(g_map, g_style, nullptr, cuts, &g_mesh);
    Scene scene;
    scene.sealTile = gta2::SealTileIndex(g_style);
    scene.Build(g_mesh);
    eyecol::Build(g_mesh, g_style);
    if (!strcmp(argv[1], "near") && argc >= 7) {
        const gta2::Vec3 p{(float)atof(argv[4]), (float)atof(argv[5]), (float)atof(argv[6])};
        eyecol::DebugNear(p, argc >= 8 ? (float)atof(argv[7]) : 0.3f);
        printf("inside a closed block: %d\n", (int)eyecol::InsideSolid(p));
        return 0;
    }
    if (!strcmp(argv[1], "inside") && argc >= 9) {
        // Points 0.43 above level `argv[8]` inside a block (most horizontal rays leave through a
        // back face within 1.5): for placing a fixed camera inside one (the solidity check).
        int found = 0;
        for (float zz = (float)atof(argv[5]); zz <= atof(argv[7]) && found < 8; zz += 0.5f)
            for (float xx = (float)atof(argv[4]); xx <= atof(argv[6]) && found < 8; xx += 0.5f) {
                const float o[3] = {xx + 0.25f, (float)atof(argv[8]) + 0.43f, gta2::kMapHeight - zz - 0.25f};
                int in = 0;
                for (int h = 0; h < 360; h += 45) { float d[3]; Dir((float)h, 0.0f, d); if (FirstAny(scene, o, d, 0.0f, 1.5f).kind == 2) ++in; }
                if (in >= 7) { printf("inside map %.2f,%.2f eye y %.2f (renderer z %.2f)\n", xx + 0.25f, zz + 0.25f, o[1], o[2]); ++found; }
            }
        return 0;
    }
    if (!strcmp(argv[1], "spots")) { g_spots = true; argv[1] = (char*)"sweep"; }
    if (!strcmp(argv[1], "sweep")) {
        int x0 = 0, y0 = 0, x1 = 255, y1 = 255, step = 1;
        if (argc >= 8) { x0 = atoi(argv[4]); y0 = atoi(argv[5]); x1 = atoi(argv[6]); y1 = atoi(argv[7]); }
        if (argc >= 9) step = atoi(argv[8]);
        return Sweep(scene, x0, y0, x1, y1, step);
    }
    if (!strcmp(argv[1], "at") && argc >= 8) {
        const gta2::Vec3 head{(float)atof(argv[4]), (float)atof(argv[5]), (float)atof(argv[6])};
        const float heading = (float)atof(argv[7]);
        float fwd[3]; Dir(heading, 0.0f, fwd);
        const gta2::Vec3 raw{head.x + fwd[0] * 0.12f, head.y, head.z + fwd[2] * 0.12f};
        gta2::Vec3 clr = raw;
        const float moved = eyecol::Clear(head, &clr, 0.24f);
        printf("raw     %.3f %.3f %.3f near %.3f sees-through %d\n", raw.x, raw.y, raw.z, eyecol::Nearest(raw, 1.0f),
               (int)SeesThrough(scene, raw, heading));
        printf("cleared %.3f %.3f %.3f near %.3f sees-through %d (moved %.3f)\n", clr.x, clr.y, clr.z, eyecol::Nearest(clr, 1.0f),
               (int)SeesThrough(scene, clr, heading), moved);
        if (getenv("DEBUGNEAR")) eyecol::DebugNear(clr, 0.3f);
        return 0;
    }
    fprintf(stderr, "unknown command\n");
    return 2;
}
