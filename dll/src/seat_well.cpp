// FIX-COCKPIT-CAB-6 (qav51): an open-top body's driver's seat from its own mesh (seat_well.h).
//
// The body's top surface is rasterised into a height map (24 across, 64 along). Seen from above, an
// open cockpit is a run of rows where the driver's band (between 15 % and 65 % of the half width
// either side of the centre line) is well under the body's height while its sides (the doors' tops)
// stand above it. The run nearest the nose is the front seats (a jeep's or a pickup's bed is further
// back). The hip sits half the run behind its front edge (the windscreen's foot), between 4 % and 14 %
// of the body's length; the cushion is the low part of the band there; the headliner the windscreen's
// header just ahead of it.
#include "seat_well.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <vector>
#include <windows.h>

#include "car_bodies.h"
#include "log.h"
#include "model_store.h"

using gta2dx9::Model;
using gta2dx9::ModelMesh;
using gta2dx9::ModelVertex;
using gta2dx9::ModelRestNodeWorlds;
using gta2dx9::Log;
using gta2dx9::CarBodiesDevIni;

namespace {

struct Entry { bool ok = false; float seat[4] = {}; };
std::map<const Model*, Entry> g_cache;

bool Enabled() {
    static const bool envOff = [] { char b[8] = {}; return GetEnvironmentVariableA("GTA2DX9_SEAT_WELL", b, sizeof b) && b[0] == '0'; }();
    if (envOff) return false;
    // [devtools] seat_well re-read once a second (a same-spot A/B in one run).
    static DWORD last = 0;
    static bool on = true;
    const DWORD now = GetTickCount();
    if (last == 0 || now - last > 1000) {
        last = now | 1;
        const char* ini = CarBodiesDevIni();
        on = !(ini && ini[0]) || GetPrivateProfileIntA("devtools", "seat_well", 1, ini) != 0;
    }
    return on;
}

bool Find(const Model& model, float out[4]) {
    constexpr int NX = 24, NZ = 64;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    struct P { float x, y, z; };
    std::vector<P> tri;
    float lo[3] = {1e9f, 1e9f, 1e9f}, hi[3] = {-1e9f, -1e9f, -1e9f};
    for (size_t i = 0; i < model.nodes.size() && i < worlds.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& mesh = model.meshes[mi];
        if (mesh.skin >= 0) continue;
        const gta2::Mat4& w = worlds[i];
        for (size_t k = 0; k + 2 < mesh.indices.size(); k += 3)
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = mesh.vertices[mesh.indices[k + c]];
                const P p{v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0],
                          v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1],
                          v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2]};
                tri.push_back(p);
                lo[0] = (std::min)(lo[0], p.x); lo[1] = (std::min)(lo[1], p.y); lo[2] = (std::min)(lo[2], p.z);
                hi[0] = (std::max)(hi[0], p.x); hi[1] = (std::max)(hi[1], p.y); hi[2] = (std::max)(hi[2], p.z);
            }
    }
    if (tri.size() < 300) return false;
    const float W = hi[0] - lo[0], H = hi[1] - lo[1], L = hi[2] - lo[2];
    if (W <= 0.01f || H <= 0.01f || L <= 0.01f) return false;
    const float cw = W / NX, cl = L / NZ;
    std::vector<float> top(NX * NZ, -1.0f);
    for (size_t k = 0; k + 2 < tri.size(); k += 3) {
        const P& a = tri[k]; const P& b = tri[k + 1]; const P& c = tri[k + 2];
        auto span = [&](const P& p, const P& q) { return (std::max)(std::fabs(p.x - q.x) / cw, std::fabs(p.z - q.z) / cl); };
        const int n = (std::min)(48, 1 + static_cast<int>(2.0f * (std::max)({span(a, b), span(b, c), span(c, a)})));
        for (int i = 0; i <= n; ++i)
            for (int j = 0; i + j <= n; ++j) {
                const float s = static_cast<float>(i) / n, t = static_cast<float>(j) / n, r = 1.0f - s - t;
                const float x = a.x * r + b.x * s + c.x * t, y = a.y * r + b.y * s + c.y * t, z = a.z * r + b.z * s + c.z * t;
                const int ix = (std::min)(NX - 1, (std::max)(0, static_cast<int>((x - lo[0]) / cw)));
                const int iz = (std::min)(NZ - 1, (std::max)(0, static_cast<int>((z - lo[2]) / cl)));
                float& h = top[iz * NX + ix];
                h = (std::max)(h, y - lo[1]);
            }
    }
    // Rows along the car from the nose (row 0) to the tail; a(row) is the row's middle, model z.
    const float fwd = model.forward < 0.0f ? -1.0f : 1.0f;
    auto rowZ = [&](int r) { const int iz = fwd > 0 ? NZ - 1 - r : r; return lo[2] + (iz + 0.5f) * cl; };
    auto cell = [&](int r, int ix) { const int iz = fwd > 0 ? NZ - 1 - r : r; return top[iz * NX + ix]; };
    auto median = [](std::vector<float> v) {
        if (v.empty()) return -1.0f;
        std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end());
        return v[v.size() / 2];
    };
    // Per row, against the row's own width (a cockpit is narrower than the bounds' mirrors and bumpers): the
    // driver's band (15-65 % of the row's half width either side of its middle), its sides (the outer two cells
    // each side: the doors' tops), the row's highest point.
    struct Row { bool ok = false; float band = 0.0f, side = 0.0f, top = 0.0f; };
    std::vector<Row> rows(NZ);
    for (int r = 0; r < NZ; ++r) {
        std::vector<int> occ;
        for (int ix = 0; ix < NX; ++ix) if (cell(r, ix) >= 0.0f) occ.push_back(ix);
        if (occ.size() < 8) continue;
        const float x0 = lo[0] + occ.front() * cw, x1 = lo[0] + (occ.back() + 1) * cw, xc = 0.5f * (x0 + x1), hw = 0.5f * (x1 - x0);
        std::vector<float> band, side;
        Row& q = rows[r];
        for (int ix : occ) {
            const float u = std::fabs((lo[0] + (ix + 0.5f) * cw - xc) / hw);
            if (u >= 0.15f && u <= 0.65f) band.push_back(cell(r, ix));
            q.top = (std::max)(q.top, cell(r, ix));
        }
        for (size_t k = 0; k < 2; ++k) { side.push_back(cell(r, occ[k])); side.push_back(cell(r, occ[occ.size() - 1 - k])); }
        if (band.size() < 4) continue;
        q.ok = true; q.band = median(band); q.side = median(side);
    }
    // The windscreen: the first row from the nose (past its first tenth) that stands at 85 % of the body's height;
    // the bonnet's height: the band's median over the rows ahead of it. No windscreen, no open cockpit.
    int wsRow = -1;
    for (int r = NZ / 10; r < NZ * 7 / 10 && wsRow < 0; ++r) if (rows[r].ok && rows[r].top >= 0.85f * H) wsRow = r;
    if (wsRow < 0) return false;
    std::vector<float> bon;
    for (int r = NZ / 10; r < wsRow; ++r) if (rows[r].ok) bon.push_back(rows[r].band);
    const float bonnet = median(bon);
    // A well row: the band under 55 % of the height and either under its sides (a tub) or well under the bonnet
    // (a jeep's flat tub, 022). A one-row gap (a seat back's top) does not split a run.
    std::vector<int> well(NZ, 0);
    std::vector<float> bandMed(NZ, -1.0f);
    for (int r = 0; r < NZ; ++r) {
        const Row& q = rows[r];
        if (!q.ok) continue;
        bandMed[r] = q.band;
        well[r] = q.band < 0.55f * H && (q.side > q.band + 0.12f * H || (bonnet > 0.0f && q.band < bonnet - 0.12f * H));
    }
    for (int r = 1; r + 1 < NZ; ++r)
        if (!well[r] && well[r - 1] && well[r + 1]) well[r] = 2;
    // The first run behind the windscreen, starting within ten rows of it (a pickup's bed behind a closed cab
    // starts further back), at least 5 % of the length long.
    int front = -1, back = -1;
    for (int r = wsRow + 1; r < NZ && r <= wsRow + 10 && front < 0; ++r) {
        if (!well[r]) continue;
        int e = r;
        while (e + 1 < NZ && well[e + 1]) ++e;
        if ((e - r + 1) * cl >= 0.05f * L) { front = r; back = e; }
        r = e;
    }
    if (front < 0) return false;
    const float aFront = rowZ(front) * fwd + 0.5f * cl, aBack = rowZ(back) * fwd - 0.5f * cl;
    const float run = aFront - aBack;
    const float hipA = aFront - (std::min)(0.14f * L, (std::max)(0.04f * L, 0.5f * run));
    // The cushion: the low part of the driver's band in the rows about the hip.
    std::vector<float> cush;
    float roof = 0.0f;
    for (int r = 0; r < NZ; ++r) {
        const float a = rowZ(r) * fwd;
        if (std::fabs(a - hipA) <= 0.035f * L && well[r]) {
            for (int ix = 0; ix < NX; ++ix) {
                const float h = cell(r, ix);
                const float u = std::fabs((lo[0] + (ix + 0.5f) * cw) / (0.5f * W));
                if (h >= 0.0f && u >= 0.15f && u <= 0.65f && h <= bandMed[r] + 0.02f * H) cush.push_back(h);
            }
        }
        if (a >= aFront - 0.5f * cl && a <= aFront + 0.12f * L)
            for (int ix = 0; ix < NX; ++ix) roof = (std::max)(roof, cell(r, ix));
    }
    if (cush.size() < 4) return false;
    std::sort(cush.begin(), cush.end());
    const float cushion = cush[cush.size() * 3 / 10];
    // Nothing over the hip: the headliner is the body's height (boarding seats him on the cushion, no roof to clear).
    roof = H;
    out[0] = 0.15f * W;
    out[1] = cushion;
    out[2] = hipA * fwd;
    out[3] = roof;
    Log("seat well: %s: cockpit well %+.3f..%+.3f along (%d rows) of %.3f, hip %+.3f u %.3f cushion %.3f (band %.3f) headliner %.3f, height %.3f",
        model.name.c_str(), aBack, aFront, back - front + 1, L, hipA, out[0], cushion, bandMed[(front + back) / 2], roof, H);
    return true;
}

}  // namespace

bool SeatWellFor(const Model& model, float out[4]) {
    if (!Enabled()) return false;
    auto it = g_cache.find(&model);
    if (it == g_cache.end()) {
        Entry e;
        e.ok = Find(model, e.seat);
        if (!e.ok) Log("seat well: %s: no cockpit well (the sprite's seat)", model.name.c_str());
        it = g_cache.emplace(&model, e).first;
    }
    if (!it->second.ok) return false;
    for (int k = 0; k < 4; ++k) out[k] = it->second.seat[k];
    return true;
}
