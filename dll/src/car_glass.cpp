// See car_glass.h.
#include "mem_stats.h"
#include "thread_watch.h"
#include "car_glass.h"
#include "car_glass_split.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <atomic>
#include <cmath>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include "log.h"
#include "model_store.h"
#include "remix_api.h"
#include "view_modes.h"
#include "../../src/sky.h"

#define XXH_INLINE_ALL
#include "../deps/xxhash/xxhash.h"

namespace gta2dx9 {
namespace {

constexpr int kR = 256;        // mask resolution (the body textures are 512 or 1024)
int g_on = 1;
float g_alpha = 0.52f;
float g_range = 40.0f;

// kind: 0 a wall of the cabin shell, 1 its headliner, 2 its floor, 3 furniture (seats, dash).
struct Quad { float p[4][3]; float n[3]; uint32_t colour; int kind; };

struct Glass {
    std::atomic<int> state{0};   // 0 queued, 1 building, 2 built (CPU), 3 textures made, -1 no glass
    std::map<std::string, std::vector<uint8_t>> masks;   // stem -> kR*kR, 255 = glass
    std::map<std::string, std::vector<uint8_t>> panes;   // the same eroded by 1 texel: the Remix cut (inside the painted rim)
    std::vector<Quad> cabin;     // model space
    int glassTexels = 0;
    int rearTexels = 0;          // of them on a rear screen (the seated driver seen from behind)
    bool closedRoof = false;     // VEHICLE-GLASS-3: the mesh has a hard top (CarGlassClosedRoof)
    // FIX-DRIVER-GEOM (pfl74): the driver's place on the cabin's own front seat (CarGlassDriverSeat), the
    // manifest's "driver_seat" frame: x from the centre line, cushion and headliner over the model's lowest point, z.
    bool hasSeat = false;
    float seat[4] = {};
};

std::mutex g_lock;                                   // g_models, g_stemTex, g_meshTris
std::map<const Model*, std::shared_ptr<Glass>> g_models;
std::map<std::string, IDirect3DTexture9*> g_stemTex;  // stem -> mask texture (alpha 0 at glass)
std::map<std::string, std::shared_ptr<Glass>> g_stemGlass;
struct GlassPart { std::vector<ModelVertex> v; std::vector<uint32_t> i; };   // a mesh's glass triangles, compacted
std::map<const ModelMesh*, GlassPart> g_meshTris;
std::mutex g_buildLock;
IDirect3DDevice9* g_device = nullptr;

// Per-frame lookups cached by address (the store never frees a model or its meshes).
std::map<const std::string*, IDirect3DTexture9*> g_texByName;   // a mesh's texture name -> its mask (or null)
struct DrawEntry { size_t node; const ModelMesh* mesh; IDirect3DTexture9* mask; const std::vector<uint8_t>* g; };
std::map<const Model*, std::vector<DrawEntry>> g_entries;      // a model's meshes that carry glass

// Cut mode.
bool g_cut = false;
struct Queued { const Model* model; gta2::Mat4 placement; };
std::vector<Queued> g_queue;

IDirect3DCubeTexture9* g_cube = nullptr;

// VEHICLE-GLASS-2, the Remix half. Remix ignores the extra texture stage that cuts the hull in the
// plain renderer and keys its materials on the stage-0 texture's hash. Under Remix the hull is cut
// by geometry instead (its glass triangles are left out of the draw, CarGlassCutIndexBuffer), the
// panes are drawn as those triangles with ONE shared glass texture for the whole fleet (fixed
// content, so a fixed XXH3 hash that a translucent material in the gta2hd layer keys on), and the
// cabin is drawn with two shared textures (trim, headliner) of their own.
int g_remixOn = 1;                                         // GTA2DX9_GLASS_REMIX=0: the old behaviour (nothing under Remix)
IDirect3DTexture9* g_glassTex = nullptr;                   // the fleet's pane texture
IDirect3DTexture9* g_cabinTex[2] = {nullptr, nullptr};     // trim, headliner
std::map<const ModelMesh*, GlassPart> g_paneTris;          // under Remix: a mesh's pane triangles (majority on glass)
struct CutIb { IDirect3DIndexBuffer9* ib = nullptr; UINT tris = 0; bool none = false; };
std::map<const ModelMesh*, CutIb> g_cutIb;                 // under Remix: a mesh's triangles less its panes
// VEHICLE-GLASS-3: the hull and the panes split along the window's outline (car_glass_split.h) instead of
// whole triangles voted pane or hull (a sawtooth on dense meshes, baked triangles left on coarse ones).
int g_rearGate = 0;                                        // GTA2DX9_GLASS_REAR_GATE=1: under Remix too, a seated car needs a rear screen (old)
int g_holesOn = 1;                                         // GTA2DX9_GLASS_HOLES=0: no fill of hull islands inside a pane (VEHICLE-GLASS-5)
int g_mirrorOn = 1;                                        // GTA2DX9_GLASS_MIRROR=0: no mirror fill of the side windows (VEHICLE-GLASS-5)
int g_beltOn = 1;                                          // GTA2DX9_GLASS_BELT=0: no near-black windows on the belt (VEHICLE-GLASS-4)
int g_splitOn = 1;                                         // GTA2DX9_GLASS_SPLIT=0: the whole-triangle vote
std::map<const ModelMesh*, GlassSplit> g_split;
std::map<const ModelMesh*, GlassPart> g_splitPane;         // the split's pane pieces, for the glass pass
bool SplitOn();                                            // g_splitOn and not [devtools] car_glass=4
const GlassSplit& SplitFor(const ModelMesh& mesh, const std::vector<uint8_t>& g) {
    auto it = g_split.find(&mesh);
    if (it != g_split.end()) return it->second;
    GlassSplit& s = g_split[&mesh];
    SplitGlass(mesh.vertices, mesh.indices, g, kR, &s);
    static int logged = 0;
    if (logged++ < 40)
        Log("car glass: remix split %s: %d triangles on the outline -> hull %zu tris (%zu verts, mesh %zu), pane %zu tris", mesh.texture.c_str(),
            s.straddling, s.hullI.size() / 3, s.hullV.size(), mesh.vertices.size(), s.paneI.size() / 3);
    return s;
}

bool RemixMode() { return g_remixOn && RemixApiAvailable(); }

// Under Remix the panes and the cabin are drawn from managed buffers made once, as the hulls are
// (vg2_rxp1..5: drawn from memory, their layer material never applied).
struct StaticBuf { IDirect3DVertexBuffer9* vb = nullptr; IDirect3DIndexBuffer9* ib = nullptr; UINT nv = 0, ntri = 0; bool failed = false; };
std::map<const void*, StaticBuf> g_staticBufs;
const StaticBuf* StaticBufFor(IDirect3DDevice9* device, const void* key, const void* verts, UINT nv, UINT stride, DWORD fvf,
                              const uint32_t* idx, UINT ni) {
    StaticBuf& b = g_staticBufs[key];
    if (b.vb) return &b;
    if (b.failed || !nv) return nullptr;
    b.failed = true;
    if (FAILED(device->CreateVertexBuffer(nv * stride, D3DUSAGE_WRITEONLY, fvf, D3DPOOL_MANAGED, &b.vb, nullptr)) || !b.vb) { b.vb = nullptr; return nullptr; }
    void* p = nullptr;
    if (FAILED(b.vb->Lock(0, 0, &p, 0))) { b.vb->Release(); b.vb = nullptr; return nullptr; }
    memcpy(p, verts, static_cast<size_t>(nv) * stride);
    b.vb->Unlock();
    if (idx && ni) {
        if (FAILED(device->CreateIndexBuffer(ni * 4, D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_MANAGED, &b.ib, nullptr)) || !b.ib) {
            b.vb->Release(); b.vb = nullptr; b.ib = nullptr; return nullptr;
        }
        if (FAILED(b.ib->Lock(0, 0, &p, 0))) { b.vb->Release(); b.ib->Release(); b.vb = nullptr; b.ib = nullptr; return nullptr; }
        memcpy(p, idx, static_cast<size_t>(ni) * 4);
        b.ib->Unlock();
        b.ntri = ni / 3;
    } else {
        b.ntri = nv / 3;
    }
    b.nv = nv;
    b.failed = false;
    return &b;
}

// A small texture of fixed content (the same bytes every session, so the same Remix hash):
// a base colour with a 2-bit ordered ripple, so it is unlike any flat texture the game makes.
IDirect3DTexture9* FixedTexture(IDirect3DDevice9* device, uint32_t argb, const char* what) {
    // 256 x 256: Remix did not key its materials on the same texture at 16 x 16 (vg2_rxp1..4: the panes
    // drew with the legacy texture under a probe prim); the body textures that do key are 512-1024.
    constexpr int kN = 256;
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(kN, kN, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (FAILED(t->LockRect(0, &lr, nullptr, 0))) { t->Release(); return nullptr; }
    std::vector<uint8_t> bytes(kN * kN * 4);
    for (int y = 0; y < kN; ++y)
        for (int x = 0; x < kN; ++x) {
            const uint32_t d = static_cast<uint32_t>((x * 7 + y * 13) & 3);
            const uint32_t r = ((argb >> 16) & 0xFF) + d, g = ((argb >> 8) & 0xFF) + d, b = (argb & 0xFF) + d;
            const uint32_t px = (argb & 0xFF000000u) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF);
            memcpy(&bytes[(y * kN + x) * 4], &px, 4);
        }
    for (int y = 0; y < kN; ++y) memcpy(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch, &bytes[y * kN * 4], kN * 4);
    t->UnlockRect(0);
    Log("car glass: %s texture 0x%016llX (Remix hash, 256x256 A8R8G8B8)", what, static_cast<unsigned long long>(XXH3_64bits(bytes.data(), bytes.size())));
    return t;
}

bool RemixTextures(IDirect3DDevice9* device) {
    if (!g_glassTex) g_glassTex = FixedTexture(device, 0x50B4C2C8u, "pane");
    if (!g_cabinTex[0]) g_cabinTex[0] = FixedTexture(device, 0xFF2E2A27u, "cabin trim");
    if (!g_cabinTex[1]) g_cabinTex[1] = FixedTexture(device, 0xFF6E6862u, "cabin headliner");
    return g_glassTex && g_cabinTex[0] && g_cabinTex[1];
}
float g_cubeKey[6] = {-1, -1, -1, -1, -1, -1};

std::string StemOf(const std::string& texture) {
    std::string s = texture;
    const size_t dot = s.rfind('.');
    if (dot != std::string::npos) s = s.substr(0, dot);
    const size_t p = s.find("_paint");
    if (p != std::string::npos) s.erase(p, 6);
    return s;
}

bool ReadTga(const std::string& path, int* w, int* h, std::vector<uint8_t>* bgra) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    std::vector<uint8_t> d;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size > 18) { d.resize(static_cast<size_t>(size)); if (fread(d.data(), 1, d.size(), f) != d.size()) d.clear(); }
    fclose(f);
    if (d.size() <= 18 || d[2] != 2 || d[16] != 32) return false;
    *w = d[12] | (d[13] << 8); *h = d[14] | (d[15] << 8);
    if (*w <= 0 || *h <= 0 || d.size() < 18u + static_cast<size_t>(*w) * *h * 4) return false;
    const bool topDown = (d[17] & 0x20) != 0;
    bgra->resize(static_cast<size_t>(*w) * *h * 4);
    for (int y = 0; y < *h; ++y) {
        const int src = topDown ? y : (*h - 1 - y);
        memcpy(&(*bgra)[static_cast<size_t>(y) * *w * 4], &d[18 + static_cast<size_t>(src) * *w * 4], static_cast<size_t>(*w) * 4);
    }
    return true;
}

// The picture at kR x kR: rgb 0..1 (box mean) and, from the paint half, its coverage 0..1.
bool Downsample(const std::string& file, std::vector<float>* rgb, std::vector<float>* alpha) {
    int w = 0, h = 0;
    std::vector<uint8_t> px;
    if (!ReadTga(std::string(ModelsFolder()) + "\\" + file, &w, &h, &px)) return false;
    if (rgb) rgb->assign(kR * kR * 3, 0.0f);
    if (alpha) alpha->assign(kR * kR, 0.0f);
    std::vector<float> cnt(kR * kR, 0.0f);
    for (int y = 0; y < h; ++y) {
        const int cy = y * kR / h;
        for (int x = 0; x < w; ++x) {
            const uint8_t* p = &px[(static_cast<size_t>(y) * w + x) * 4];
            const int c = cy * kR + x * kR / w;
            if (rgb) { (*rgb)[c * 3] += p[2] / 255.0f; (*rgb)[c * 3 + 1] += p[1] / 255.0f; (*rgb)[c * 3 + 2] += p[0] / 255.0f; }
            if (alpha) (*alpha)[c] += p[3] / 255.0f;
            cnt[c] += 1.0f;
        }
    }
    for (int i = 0; i < kR * kR; ++i) {
        if (cnt[i] <= 0) continue;
        if (rgb) for (int k = 0; k < 3; ++k) (*rgb)[i * 3 + k] /= cnt[i];
        if (alpha) (*alpha)[i] /= cnt[i];
    }
    return true;
}

using Mask = std::vector<uint8_t>;
Mask Dilate(const Mask& m) {
    Mask o = m;
    for (int y = 0; y < kR; ++y)
        for (int x = 0; x < kR; ++x) {
            if (m[y * kR + x]) continue;
            if ((x > 0 && m[y * kR + x - 1]) || (x + 1 < kR && m[y * kR + x + 1]) || (y > 0 && m[(y - 1) * kR + x]) ||
                (y + 1 < kR && m[(y + 1) * kR + x]))
                o[y * kR + x] = 1;
        }
    return o;
}
Mask Erode(const Mask& m) {
    Mask inv(m.size());
    for (size_t i = 0; i < m.size(); ++i) inv[i] = m[i] ? 0 : 1;
    inv = Dilate(inv);
    for (size_t i = 0; i < m.size(); ++i) inv[i] = inv[i] ? 0 : 1;
    return inv;
}
Mask KeepComponents(const Mask& m, int minSize) {
    Mask out(m.size(), 0);
    std::vector<int> label(m.size(), 0), stack, pts;
    int n = 0;
    for (int i = 0; i < kR * kR; ++i) {
        if (!m[i] || label[i]) continue;
        ++n;
        stack.assign(1, i); label[i] = n; pts.clear();
        while (!stack.empty()) {
            const int a = stack.back(); stack.pop_back();
            pts.push_back(a);
            const int x = a % kR, y = a / kR;
            const int nb[4] = {x > 0 ? a - 1 : -1, x + 1 < kR ? a + 1 : -1, y > 0 ? a - kR : -1, y + 1 < kR ? a + kR : -1};
            for (int b : nb)
                if (b >= 0 && m[b] && !label[b]) { label[b] = n; stack.push_back(b); }
        }
        if (static_cast<int>(pts.size()) >= minSize)
            for (int a : pts) out[a] = 1;
    }
    return out;
}

// VEHICLE-GLASS-5: hull islands enclosed by glass (GLASS-4's measure: 030 211 texels, 035 111, 084 108) are bake blobs
// inside a pane, drawn as torn hull patches. A 4-connected component of non-glass texels touching no texel outside the
// body raster (the UV island's border) and no image edge, of at most 300 texels and less than half strictly bodywork
// (the paint pillars between the 006 box car's windows are enclosed by its glass in UV), becomes glass. The twin is
// tools/car_glass_mask.py fill_holes.
void FillHoles(Mask& g, const std::vector<uint8_t>& valid, const Mask& strict) {
    std::vector<int> label(kR * kR, 0), stack, pts;
    int n = 0;
    for (int i = 0; i < kR * kR; ++i) {
        if (g[i] || label[i]) continue;
        ++n;
        stack.assign(1, i); label[i] = n; pts.clear();
        bool bad = false;
        int nStrict = 0;
        while (!stack.empty()) {
            const int a = stack.back(); stack.pop_back();
            pts.push_back(a);
            const int x = a % kR, y = a / kR;
            if (!valid[a] || x == 0 || y == 0 || x == kR - 1 || y == kR - 1) bad = true;
            if (strict[a]) ++nStrict;
            const int nb[4] = {x > 0 ? a - 1 : -1, x + 1 < kR ? a + 1 : -1, y > 0 ? a - kR : -1, y + 1 < kR ? a + kR : -1};
            for (int b : nb)
                if (b >= 0 && !g[b] && !label[b]) { label[b] = n; stack.push_back(b); }
        }
        if (!bad && pts.size() <= 300 && 2 * nStrict < static_cast<int>(pts.size()))
            for (int a : pts) g[a] = 1;
    }
}

// VEHICLE-GLASS-5: the bodies are symmetric, the bakes are not: 071 Rumbler's left window is found to the A pillar, its
// right one stops a quarter short (that corner is baked in the paint's own hue: no colour rule can take it without
// taking paint). Cells over the side faces of the glasshouse (1/48 of the length, 1/16 of 0.60-0.90 of the roof); a
// cell is glass when at least 0.6 of its texels (and 2) are. Sources: glass cells with glass (or no texel) above and
// below, in an 8-connected group at least 4 rows tall and 12 cells big (never a trim strip: 001's chrome belt). Only
// when the two sides' glass cells overlap (IoU 0.5: 003's camo sides disagree, 0.00). A side glasshouse texel, not
// livery, becomes glass when the cell at its station and height on the OTHER side is a source; the result is closed
// by 2 texels inside the side glasshouse. The twin is tools/car_glass_mask.py mirror_fill.
void MirrorFill(Mask& g, const Mask& band, const Mask& livery, const std::vector<uint8_t>& valid, const std::vector<float>& pos,
                const std::vector<float>& nrm, float minY, float H, float minZ, float L) {
    constexpr int NZ = 48, NH = 16;
    std::vector<int> cell(kR * kR, -1);
    int cnt[2][NH][NZ], gc[2][NH][NZ];
    std::memset(cnt, 0, sizeof cnt); std::memset(gc, 0, sizeof gc);
    for (int i = 0; i < kR * kR; ++i) {
        if (!valid[i] || !band[i] || std::fabs(nrm[i * 3]) <= 0.4f) continue;
        const int qz = (std::max)(0, (std::min)(NZ - 1, static_cast<int>((pos[i * 3 + 2] - minZ) / L * NZ)));
        const int qh = (std::max)(0, (std::min)(NH - 1, static_cast<int>(((pos[i * 3 + 1] - minY) / H - 0.60f) / 0.30f * NH)));
        const int sd = nrm[i * 3] > 0.0f ? 1 : 0;
        cell[i] = (sd * NH + qh) * NZ + qz;
        ++cnt[sd][qh][qz];
        if (g[i]) ++gc[sd][qh][qz];
    }
    bool gcell[2][NH][NZ], core[2][NH][NZ];
    int inter = 0, uni = 0;
    for (int s = 0; s < 2; ++s)
        for (int a = 0; a < NH; ++a)
            for (int b = 0; b < NZ; ++b) gcell[s][a][b] = gc[s][a][b] >= 2 && gc[s][a][b] >= 0.6f * cnt[s][a][b];
    for (int a = 0; a < NH; ++a)
        for (int b = 0; b < NZ; ++b) {
            inter += gcell[0][a][b] && gcell[1][a][b];
            uni += gcell[0][a][b] || gcell[1][a][b];
        }
    if (uni == 0 || inter < 0.5f * uni) return;
    auto ok = [&](int s, int a, int b) { return a < 0 || a >= NH || gcell[s][a][b] || cnt[s][a][b] == 0; };
    for (int s = 0; s < 2; ++s)
        for (int a = 0; a < NH; ++a)
            for (int b = 0; b < NZ; ++b)
                core[s][a][b] = gcell[s][a][b] && (a > 0 && ok(s, a - 1, b)) && (a + 1 < NH && ok(s, a + 1, b));
    for (int s = 0; s < 2; ++s) {   // sources: 8-connected groups at least 4 rows tall and 12 cells big
        int lab[NH][NZ];
        std::memset(lab, 0, sizeof lab);
        int n = 0;
        for (int a = 0; a < NH; ++a)
            for (int b = 0; b < NZ; ++b) {
                if (!core[s][a][b] || lab[a][b]) continue;
                ++n;
                std::vector<std::pair<int, int>> st{{a, b}}, mem;
                lab[a][b] = n;
                bool rows[NH] = {};
                while (!st.empty()) {
                    const auto c = st.back(); st.pop_back();
                    mem.push_back(c); rows[c.first] = true;
                    for (int dx = -1; dx <= 1; ++dx)
                        for (int dy = -1; dy <= 1; ++dy) {
                            const int u = c.first + dx, w = c.second + dy;
                            if (u >= 0 && u < NH && w >= 0 && w < NZ && core[s][u][w] && !lab[u][w]) { lab[u][w] = n; st.push_back({u, w}); }
                        }
                }
                int nr = 0;
                for (bool r : rows) nr += r;
                if (nr < 4 || mem.size() < 12)
                    for (const auto& c : mem) core[s][c.first][c.second] = false;
            }
    }
    Mask out = g, side(kR * kR, 0);
    bool added = false;
    for (int i = 0; i < kR * kR; ++i) {
        if (cell[i] < 0) continue;
        if (!livery[i]) side[i] = 1;
        if (g[i] || livery[i]) continue;
        const int sd = cell[i] / (NH * NZ), rest = cell[i] % (NH * NZ);
        if (core[1 - sd][rest / NZ][rest % NZ]) { out[i] = 1; added = true; }
    }
    if (added) {
        Mask c = out;
        for (int k = 0; k < 2; ++k) c = Dilate(c);
        for (int k = 0; k < 2; ++k) c = Erode(c);
        for (int i = 0; i < kR * kR; ++i) if (c[i] && side[i]) out[i] = 1;
    }
    g.swap(out);
}

// VEHICLE-GLASS-4: a near-black side texel is a window, not tyre-black trim, when it sits on the paint belt at its
// station along the car (071 Rumbler: near-black side windows straight over its dark red belt line; the tyre-black
// rule dropped them, 290 of ~1100 texels found). Cells of (side, 1/24 of 0.40-0.90 of the roof height, 1/48 of the
// length) over the side faces; a cell is paint / black when at least half of its texels (and 2) are. A black cell
// at 0.55 of the roof or higher is accepted with a paint cell below it in its column, in a run of 3 such cells up
// the column (019's black deck streaks are thinner) and with its mirrored cell on the other side accepted too
// (+-1 cell: the bodies are symmetric; 003's black camo on one flank is green on the other). Rear and front faces
// never (003's rear doors, 007's cab back wall). The twin is tools/car_glass_mask.py on_belt.
void BeltBlack(Mask& g, const Mask& cand, const Mask& paint, const Mask& black, const std::vector<uint8_t>& valid,
               const std::vector<float>& pos, const std::vector<float>& nrm, float minY, float H, float minZ, float L) {
    constexpr int NH = 24, NZ = 48;
    int cnt[2][NH][NZ] = {}, pc[2][NH][NZ] = {}, bc[2][NH][NZ] = {};   // ~28 KB on the worker's stack
    bool acc[2][NH][NZ] = {}, keep[2][NH][NZ] = {}, mir[2][NH][NZ] = {};
    auto cell = [&](int i, int* sd, int* hb, int* zb) {
        if (!valid[i] || std::fabs(nrm[i * 3]) <= 0.4f) return false;
        *hb = static_cast<int>(std::floor(((pos[i * 3 + 1] - minY) / H - 0.40f) / 0.50f * NH));
        if (*hb < 0 || *hb >= NH) return false;
        *zb = (std::max)(0, (std::min)(NZ - 1, static_cast<int>((pos[i * 3 + 2] - minZ) / L * NZ)));
        *sd = nrm[i * 3] > 0.0f ? 1 : 0;
        return true;
    };
    for (int i = 0; i < kR * kR; ++i) {
        int sd, hb, zb;
        if (!cell(i, &sd, &hb, &zb)) continue;
        ++cnt[sd][hb][zb];
        if (paint[i]) ++pc[sd][hb][zb];
        if (black[i]) ++bc[sd][hb][zb];
    }
    for (int sd = 0; sd < 2; ++sd)
        for (int zb = 0; zb < NZ; ++zb) {
            bool seen = false;
            for (int k = 0; k < NH; ++k) {
                const bool pcell = pc[sd][k][zb] >= 2 && 2 * pc[sd][k][zb] >= cnt[sd][k][zb];
                const bool bcell = bc[sd][k][zb] >= 2 && 2 * bc[sd][k][zb] >= cnt[sd][k][zb];
                acc[sd][k][zb] = bcell && seen && k >= 7;   // 7 = 0.55 of the roof height
                seen = seen || (pcell && !bcell);
            }
            for (int k = 0; k + 2 < NH; ++k)
                if (acc[sd][k][zb] && acc[sd][k + 1][zb] && acc[sd][k + 2][zb])
                    keep[sd][k][zb] = keep[sd][k + 1][zb] = keep[sd][k + 2][zb] = true;
        }
    for (int sd = 0; sd < 2; ++sd)   // a lone missing station between two (wraps, as the twin's np.roll)
        for (int k = 0; k < NH; ++k)
            for (int zb = 0; zb < NZ; ++zb)
                acc[sd][k][zb] = keep[sd][k][zb] || (keep[sd][k][(zb + NZ - 1) % NZ] && keep[sd][k][(zb + 1) % NZ]);
    for (int sd = 0; sd < 2; ++sd)
        for (int k = 0; k < NH; ++k)
            for (int zb = 0; zb < NZ; ++zb) {
                bool m = false;
                for (int dk = -1; dk <= 1 && !m; ++dk)
                    for (int dz = -1; dz <= 1 && !m; ++dz) m = acc[1 - sd][(k + dk + NH) % NH][(zb + dz + NZ) % NZ];
                mir[sd][k][zb] = m;
            }
    for (int i = 0; i < kR * kR; ++i) {
        int sd, hb, zb;
        if (!cand[i] || !cell(i, &sd, &hb, &zb)) continue;
        if (acc[sd][hb][zb] && mir[sd][hb][zb]) g[i] = 1;
    }
}

void HueSat(float r, float g, float b, float* hue, float* sat, float* val) {
    const float mx = (std::max)((std::max)(r, g), b), mn = (std::min)((std::min)(r, g), b), d = mx - mn;
    *val = mx; *sat = mx > 1e-4f ? d / mx : 0.0f;
    float h = 0.0f;
    if (d > 1e-5f) {
        if (mx == r) h = std::fmod((g - b) / d + 6.0f, 6.0f);
        else if (mx == g) h = (b - r) / d + 2.0f;
        else h = (r - g) / d + 4.0f;
    }
    *hue = h * 60.0f;
}

constexpr int kMaxClusters = 5;   // up to three flank colours and two light roof colours

// How far a paint colour's RGB tolerance reaches: 0.10 of RGB is most of a dark green's whole range,
// so the tolerance scales with the paint's brightness (VEHICLE-GLASS-2; 030 Land Roamer).
float PaintScale(const float c[3]) {
    const float v = (std::max)((std::max)(c[0], c[1]), c[2]);
    return (std::max)(0.60f, (std::min)(1.0f, v / 0.40f));
}

// A texel of the body's paint: near one of its colours, or (a saturated paint) the same hue,
// brighter or darker (the bake keeps the concept's highlights and shade on the panels).
bool PaintLike(float r, float g, float b, const float clusters[][3], int n) {
    float hue, sat, val;
    HueSat(r, g, b, &hue, &sat, &val);
    for (int c = 0; c < n; ++c) {
        const float dr = r - clusters[c][0], dg = g - clusters[c][1], db = b - clusters[c][2];
        const float t = 0.10f * PaintScale(clusters[c]);
        if (dr * dr + dg * dg + db * db < t * t) return true;
        float ch, cs, cv;
        HueSat(clusters[c][0], clusters[c][1], clusters[c][2], &ch, &cs, &cv);
        if (cs < 0.30f || sat < 0.25f || val < 0.10f) continue;
        float dh = std::fabs(hue - ch);
        if (dh > 180.0f) dh = 360.0f - dh;
        if (dh < 22.0f && sat > 0.45f * cs) return true;
    }
    return false;
}

// 4-connected components of a mask: label per texel (0 = none), the count returned.
int Label(const Mask& m, std::vector<int>* label) {
    label->assign(m.size(), 0);
    std::vector<int> stack;
    int n = 0;
    for (int i = 0; i < kR * kR; ++i) {
        if (!m[i] || (*label)[i]) continue;
        ++n;
        stack.assign(1, i); (*label)[i] = n;
        while (!stack.empty()) {
            const int a = stack.back(); stack.pop_back();
            const int x = a % kR, y = a / kR;
            const int nb[4] = {x > 0 ? a - 1 : -1, x + 1 < kR ? a + 1 : -1, y > 0 ? a - kR : -1, y + 1 < kR ? a + kR : -1};
            for (int b : nb)
                if (b >= 0 && m[b] && !(*label)[b]) { (*label)[b] = n; stack.push_back(b); }
        }
    }
    return n;
}

// The glass components that read as paint as a whole: bright and tinted (a cream or white upper
// body of a two-tone van, a cargo bed's slats, a roof sign), or near white. Glass in the bakes is
// darker, or a near-neutral pale grey (sat under 0.12).
std::vector<char> PaintComponents(const Mask& g, const std::vector<float>& rgb, std::vector<int>* label) {
    const int n = Label(g, label);
    std::vector<double> sv(n + 1, 0.0), ss(n + 1, 0.0), cnt(n + 1, 0.0);
    for (int i = 0; i < kR * kR; ++i) {
        const int l = (*label)[i];
        if (!l) continue;
        float hue, sat, val;
        HueSat(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], &hue, &sat, &val);
        sv[l] += val; ss[l] += sat; cnt[l] += 1.0;
    }
    std::vector<char> drop(n + 1, 0);
    for (int l = 1; l <= n; ++l) {
        const double mv = sv[l] / cnt[l], ms = ss[l] / cnt[l];
        drop[l] = ((mv > 0.62 && ms > 0.12) || mv > 0.85) ? 1 : 0;
    }
    return drop;
}

// Drops the components that read as paint (above). VEHICLE-GLASS-2: such a component first loses
// only its paint texels, the bright ones and the shaded ones of the same chromaticity (a two-tone
// van's cream band in light and shade); what is left (the darker cab window the glass grew into the
// band through) is closed over small highlights and kept when it reads as glass on its own (067).
int DropPaintComponents(Mask& g, const std::vector<float>& rgb) {
    std::vector<int> label;
    std::vector<char> drop = PaintComponents(g, rgb, &label);
    int dropped = 0;
    for (size_t l = 1; l < drop.size(); ++l) dropped += drop[l];
    if (!dropped) return 0;
    std::vector<float> val(kR * kR), sat(kR * kR), chroma(kR * kR * 3);
    for (int i = 0; i < kR * kR; ++i) {
        float hue;
        HueSat(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], &hue, &sat[i], &val[i]);
        for (int k = 0; k < 3; ++k) chroma[i * 3 + k] = rgb[i * 3 + k] / (std::max)(val[i], 1e-3f);
    }
    auto bright = [&](int i) { return (val[i] > 0.62f && sat[i] > 0.12f) || val[i] > 0.85f; };
    // Each flagged component's bright chromaticity.
    std::vector<double> ref((drop.size()) * 3, 0.0), nb(drop.size(), 0.0);
    for (int i = 0; i < kR * kR; ++i) {
        const int l = label[i];
        if (!l || !drop[l] || !bright(i)) continue;
        for (int k = 0; k < 3; ++k) ref[l * 3 + k] += chroma[i * 3 + k];
        nb[l] += 1.0;
    }
    Mask flagged(kR * kR, 0), rest(kR * kR, 0);
    for (int i = 0; i < kR * kR; ++i) {
        const int l = label[i];
        if (!l || !drop[l]) continue;
        flagged[i] = 1;
        if (bright(i)) continue;
        if (nb[l] >= 10) {
            double d = 0.0;
            for (int k = 0; k < 3; ++k) { const double e = chroma[i * 3 + k] - ref[l * 3 + k] / nb[l]; d += e * e; }
            if (d < 0.12 * 0.12) continue;   // the same paint in shade
        }
        rest[i] = 1;
    }
    for (int k = 0; k < 2; ++k) rest = Dilate(rest);
    for (int k = 0; k < 2; ++k) rest = Erode(rest);
    for (int i = 0; i < kR * kR; ++i) rest[i] = rest[i] && flagged[i];
    rest = KeepComponents(rest, 30);
    for (int i = 0; i < kR * kR; ++i) if (flagged[i]) g[i] = rest[i];
    drop = PaintComponents(g, rgb, &label);
    for (int i = 0; i < kR * kR; ++i) if (label[i] && drop[label[i]]) g[i] = 0;
    return dropped;
}

// The mask and the cabin of one model (worker thread; the model is immutable once loaded).
// VEHICLE-GLASS-6 (vr-car-glass, VEHICLE_PRIORITY 2): a pane the colour rules did not find is synthesized from the
// glasshouse's own geometry, so no closed generated body keeps an opaque baked window (029 Dementia's side windows and
// 005 Beamer's are baked in the paint's own colour; 028 found no glass at all; 002/016/035/037/048/071 no rear screen,
// i.e. no driver seen from the chase camera). Regions, model-wide over every body texture: each side's windows (side
// faces in the roof span at 0.63-0.87 of the roof height, 0.05 of the length kept as the A and C pillars, a B pillar of
// 0.035 of it on a span over 0.30 of the length), the windscreen and the rear screen (facing forward / back at 0.66-0.87,
// inset 0.14 of the screen's own width each side for the pillars). A region whose found glass covers under a quarter of
// its aperture takes the whole aperture (less bright livery; a synthesized side from 0.66); a side only when both sides missed. Sides and rear only on a car-like glasshouse: a roof span
// of at most 0.70 of the length and tumblehome (the side glass's |x| at 0.78-0.87 of the roof under 0.90 of the belt's
// at 0.45-0.55: a box truck's, van's or bus's flanks stand upright, 0.96-1.00, and their blank cargo sides must stay
// metal); the windscreen on every closed body. The tank, the trailers and the flatbed (54, 55, 61, 65, 66) and the wrecks
// are never glazed. GTA2DX9_GLASS_SYNTH=0 turns it off for a session; the twin is tools/car_glass_mask.py synthesize.
struct StemWork {
    std::string stem;
    Mask g;
    std::vector<float> pos, nrm;
    std::vector<uint8_t> valid;
    Mask livery;   // saturated and bright: a sign or a stripe, never glazed
};
int g_synthOn = 1;                                         // GTA2DX9_GLASS_SYNTH=0: no synthesized panes (VEHICLE-GLASS-6)
int g_columnsOn = 1;                                       // GTA2DX9_GLASS_COLUMNS=0: no column completion of the side windows
int g_colTopOn = 1;                                        // GTA2DX9_GLASS_COLTOP=0: column completion stops at 0.87, not the band's 0.90 (VEHICLE-GLASS-7)
int g_beltCutOn = 1;                                       // GTA2DX9_GLASS_BELTCUT=0: no drop of side glass under the sill ledge (VEHICLE-GLASS-7)

void SynthesizePanes(const std::string& name, std::vector<StemWork>& work, float minY, float H, float minZ, float L,
                     float z0, float z1, float rake, float midX, float W) {
    const int number = name.size() >= 3 && isdigit(static_cast<unsigned char>(name[0])) ? atoi(name.substr(0, 3).c_str()) : -1;
    if (number == 54 || number == 55 || number == 61 || number == 65 || number == 66 || (number >= 72 && number <= 81)) return;
    const float span = (z1 - z0) / L;
    std::vector<float> hi, lo;
    for (const StemWork& w : work) {
        if (w.stem.find("underpan") != std::string::npos) continue;
        for (int i = 0; i < kR * kR; ++i) {
            if (!w.valid[i] || std::fabs(w.nrm[i * 3]) <= 0.4f) continue;
            const float z = w.pos[i * 3 + 2], h = (w.pos[i * 3 + 1] - minY) / H;
            if (z <= z0 || z >= z1) continue;
            const float ax = std::fabs(w.pos[i * 3] - midX);
            if (h > 0.78f && h < 0.87f) hi.push_back(ax);
            else if (h > 0.45f && h < 0.55f) lo.push_back(ax);
        }
    }
    auto median = [](std::vector<float>& v) { std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end()); return v[v.size() / 2]; };
    const float tumble = hi.size() >= 20 && lo.size() >= 20 ? median(hi) / (std::max)(median(lo), 1e-6f) : 1.0f;
    const bool carLike = span <= 0.70f && tumble < 0.90f;
    const float pin = 0.05f * L, zm = 0.5f * (z0 + z1);
    // Region of a texel: 0 none, 1 side +x, 2 side -x, 3 windscreen, 4 rear screen.
    std::vector<std::vector<uint8_t>> region(work.size());
    // VEHICLE-GLASS-7: the side band from 0.87 up to the glasshouse bound (0.90, the band's own top), side 1/2 as region:
    // column completion fills a window's top to the roof's turn, not to a line the bake's pale band sits above (071).
    std::vector<std::vector<uint8_t>> topReg(work.size());
    for (size_t k = 0; k < work.size(); ++k) {
        const StemWork& w = work[k];
        region[k].assign(kR * kR, 0);
        topReg[k].assign(kR * kR, 0);
        if (w.stem.find("underpan") != std::string::npos) continue;   // VEHICLE-ART-13's floor pan
        for (int i = 0; i < kR * kR; ++i) {
            if (!w.valid[i] || w.livery[i]) continue;
            const float nx = w.nrm[i * 3], ny = w.nrm[i * 3 + 1], nz = w.nrm[i * 3 + 2];
            if (ny > 0.80f) continue;
            const float h = (w.pos[i * 3 + 1] - minY) / H, z = w.pos[i * 3 + 2];
            if (std::fabs(nx) > 0.4f && h > 0.87f && h <= 0.90f && z >= z0 + pin && z <= z1 - pin &&
                !(z1 - z0 > 0.30f * L && std::fabs(z - zm) <= 0.0175f * L))
                topReg[k][i] = nx > 0.0f ? 1 : 2;
            if (std::fabs(nx) > 0.4f && h >= 0.63f && h <= 0.87f && z >= z0 + pin && z <= z1 - pin &&
                !(z1 - z0 > 0.30f * L && std::fabs(z - zm) <= 0.0175f * L)) {
                region[k][i] = nx > 0.0f ? 1 : 2;
                continue;
            }
            if (h < 0.66f || h > 0.87f || std::fabs(nx) > 0.6f) continue;
            if (nz > 0.35f && z > z1 - 0.05f * L && z < z1 + rake) region[k][i] = 3;
            else if (nz < -0.35f && z < z0 + 0.05f * L && z > z0 - rake) region[k][i] = 4;
        }
    }
    // The screens' own width (2nd..98th percentile of x over the region), inset at each side for the pillars.
    for (uint8_t r = 3; r <= 4; ++r) {
        std::vector<float> xs;
        for (size_t k = 0; k < work.size(); ++k)
            for (int i = 0; i < kR * kR; ++i) if (region[k][i] == r) xs.push_back(work[k].pos[i * 3]);
        if (xs.size() < 20) continue;
        std::sort(xs.begin(), xs.end());
        const float x0 = xs[xs.size() * 2 / 100], x1 = xs[(xs.size() * 98) / 100];
        const float inset = 0.14f * (x1 - x0);
        for (size_t k = 0; k < work.size(); ++k)
            for (int i = 0; i < kR * kR; ++i)
                if (region[k][i] == r && (work[k].pos[i * 3] <= x0 + inset || work[k].pos[i * 3] >= x1 - inset)) region[k][i] = 0;
    }
    static const char* kNames[5] = {"", "side+", "side-", "windscreen", "rear screen"};
    char said[256] = {};
    int sl = 0;
    int ap[5] = {}, found[5] = {};
    for (size_t k = 0; k < work.size(); ++k)
        for (int i = 0; i < kR * kR; ++i)
            if (region[k][i]) { ++ap[region[k][i]]; found[region[k][i]] += work[k].g[i] ? 1 : 0; }
    auto missed = [&](int r) { return ap[r] >= 40 && found[r] * 4 < ap[r]; };
    // A side only when BOTH sides missed (windows painted on): one side found and the other not is an asymmetric body
    // (023's serving hatch) or MirrorFill's business.
    const bool bothSides = carLike && missed(1) && missed(2);
    for (uint8_t r = 1; r <= 4; ++r) {
        if (r != 3 && !carLike) continue;
        if (r <= 2 && !bothSides) continue;
        if (!missed(r)) continue;
        // a synthesized side starts at 0.66 of the roof (at 0.63 it cut under 028's chrome sill: dark notches)
        for (size_t k = 0; k < work.size(); ++k)
            for (int i = 0; i < kR * kR; ++i)
                if (region[k][i] == r && (r > 2 || (work[k].pos[i * 3 + 1] - minY) / H >= 0.66f)) work[k].g[i] = 1;
        if (sl < 200) sl += snprintf(said + sl, sizeof said - sl, "%s%s %d of %d", sl ? ", " : "", kNames[r], ap[r] - found[r], ap[r]);
    }
    // Column completion: on a side the colour rules found, a station (1/48 of the length) whose aperture is at least 0.4
    // glass takes its aperture above the median height of the station's found glass (the pale band the bakes leave along
    // a window's top; never the lower half: filled down to the aperture's 0.63, or to the lowest found texel, it cut dark
    // notches under 071's and 002's chrome belts, runs qa_vg6_a2/a3); a station under that (a pillar, a door's baked slab) stays as it is. GTA2DX9_GLASS_COLUMNS=0 / twin "columns".
    int colAdded[3] = {};
    if (carLike && g_columnsOn && !bothSides) {
        for (uint8_t r = 1; r <= 2; ++r) {
            int cap[48] = {}, cfd[48] = {};
            std::vector<float> colY[48];   // the station's found glass heights: the fill goes up from their median
            auto zbin = [&](const StemWork& w, int i) {
                return (std::max)(0, (std::min)(47, static_cast<int>((w.pos[i * 3 + 2] - minZ) / L * 48)));
            };
            for (size_t k = 0; k < work.size(); ++k)
                for (int i = 0; i < kR * kR; ++i)
                    if (region[k][i] == r) {
                        const int b = zbin(work[k], i);
                        ++cap[b];
                        if (work[k].g[i]) { ++cfd[b]; colY[b].push_back(work[k].pos[i * 3 + 1]); }
                    }
            float cmid[48];
            for (int b = 0; b < 48; ++b) {
                cmid[b] = 1e9f;
                if (colY[b].empty()) continue;
                std::nth_element(colY[b].begin(), colY[b].begin() + colY[b].size() / 2, colY[b].end());
                cmid[b] = colY[b][colY[b].size() / 2];
            }
            for (size_t k = 0; k < work.size(); ++k)
                for (int i = 0; i < kR * kR; ++i) {
                    if ((region[k][i] != r && !(g_colTopOn && topReg[k][i] == r)) || work[k].g[i]) continue;
                    const int b = zbin(work[k], i);
                    if (cap[b] >= 4 && cfd[b] * 10 >= cap[b] * 4 && work[k].pos[i * 3 + 1] >= cmid[b]) { work[k].g[i] = 1; ++colAdded[r]; }
                }
        }
    }
    // VEHICLE-GLASS-7 belt cut: a side window starts above the belt. Where the body has a sill ledge (an up-facing surface,
    // normal y > 0.7, at 0.55-0.72 of the roof, |x| over 0.30 of the width from the middle), side glass at that station
    // (1/48 of the length) and side under the ledge's top and outboard of its inner edge (on the door's skin; a window stands
    // inboard of its sill) is the door's top, not glass: 001 Wellard's beige strip under its chrome sill (its bake gives no
    // paint cluster, so no colour rule held it), 002's and 005's dark door tops. GTA2DX9_GLASS_BELTCUT=0 / twin "beltcut".
    int beltDropped = 0;
    if (carLike && g_beltCutOn) {
        float lh[2][48], lx[2][48];
        for (int s = 0; s < 2; ++s) for (int b = 0; b < 48; ++b) { lh[s][b] = -1.0f; lx[s][b] = 1e9f; }
        auto sb = [&](const StemWork& w, int i, int* s, int* b) {
            *s = w.pos[i * 3] > midX ? 1 : 0;
            *b = (std::max)(0, (std::min)(47, static_cast<int>((w.pos[i * 3 + 2] - minZ) / L * 48)));
        };
        for (const StemWork& w : work) {
            if (w.stem.find("underpan") != std::string::npos) continue;
            for (int i = 0; i < kR * kR; ++i) {
                if (!w.valid[i] || w.nrm[i * 3 + 1] <= 0.7f) continue;
                const float h = (w.pos[i * 3 + 1] - minY) / H, ax = std::fabs(w.pos[i * 3] - midX);
                if (h < 0.55f || h > 0.72f || ax <= 0.30f * W) continue;
                int s, b;
                sb(w, i, &s, &b);
                lh[s][b] = (std::max)(lh[s][b], h);
                lx[s][b] = (std::min)(lx[s][b], ax);
            }
        }
        for (StemWork& w : work) {
            if (w.stem.find("underpan") != std::string::npos) continue;
            for (int i = 0; i < kR * kR; ++i) {
                if (!w.g[i] || std::fabs(w.nrm[i * 3]) <= 0.4f) continue;
                const float h = (w.pos[i * 3 + 1] - minY) / H;
                if (h >= 0.72f) continue;
                int s, b;
                sb(w, i, &s, &b);
                if (lh[s][b] >= 0.0f && h < lh[s][b] && std::fabs(w.pos[i * 3] - midX) >= lx[s][b]) { w.g[i] = 0; ++beltDropped; }
            }
        }
    }
    Log("car glass: %s: glasshouse span %.2f, tumblehome %.2f (%s), synthesized panes: %s; side columns +%d / +%d; belt cut -%d", name.c_str(), span,
        tumble, carLike ? "car" : "van/truck: windscreen only", sl ? said : "none", colAdded[1], colAdded[2], beltDropped);
}

void Build(const Model* model, std::shared_ptr<Glass> glass) {
    NameThisThread("car glass build", true);
    std::lock_guard<std::mutex> one(g_buildLock);
    glass->state = 1;
    // VEHICLE-ART-2's authored bodies model their glass and cabin ("_glass", "_interior" textures).
    for (const ModelMesh& mesh : model->meshes)
        if (mesh.texture.find("_glass") != std::string::npos || mesh.texture.find("_interior") != std::string::npos) {
            Log("car glass: %s: has its own glass (authored body), left as it is", model->name.c_str());
            glass->state = -1;
            return;
        }
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(*model, &worlds);
    // Every vertex in model space, for the profile.
    struct Tri { gta2::Vec3 p[3]; float uv[3][2]; gta2::Vec3 n; };
    std::map<std::string, std::vector<Tri>> tris;   // by stem (the paint half repeats the rest's triangles)
    std::vector<float> ys;
    float minX = 1e9f, maxX = -1e9f, minY = 1e9f, minZ = 1e9f, maxZ = -1e9f;
    std::vector<gta2::Vec3> all;
    for (size_t i = 0; i < model->nodes.size(); ++i) {
        const int mi = model->nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model->meshes.size()) || i >= worlds.size()) continue;
        const ModelMesh& mesh = model->meshes[mi];
        if (mesh.skin >= 0 || mesh.indices.size() < 3) continue;
        const std::string stem = StemOf(mesh.texture);
        const bool repeat = tris.count(stem) != 0;
        const gta2::Mat4& w = worlds[i];
        auto xf = [&](const ModelVertex& v) {
            return gta2::Vec3{v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0],
                              v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1],
                              v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2]};
        };
        if (repeat) continue;
        std::vector<Tri>& list = tris[stem];
        for (const ModelVertex& v : mesh.vertices) {
            const gta2::Vec3 p = xf(v);
            all.push_back(p);
            minX = (std::min)(minX, p.x); maxX = (std::max)(maxX, p.x);
            minY = (std::min)(minY, p.y); minZ = (std::min)(minZ, p.z); maxZ = (std::max)(maxZ, p.z);
            ys.push_back(p.y);
        }
        for (size_t k = 0; k + 2 < mesh.indices.size(); k += 3) {
            Tri t;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = mesh.vertices[mesh.indices[k + c]];
                t.p[c] = xf(v); t.uv[c][0] = v.u; t.uv[c][1] = v.v;
            }
            const gta2::Vec3 e1{t.p[1].x - t.p[0].x, t.p[1].y - t.p[0].y, t.p[1].z - t.p[0].z};
            const gta2::Vec3 e2{t.p[2].x - t.p[0].x, t.p[2].y - t.p[0].y, t.p[2].z - t.p[0].z};
            gta2::Vec3 n{e1.y * e2.z - e1.z * e2.y, e1.z * e2.x - e1.x * e2.z, e1.x * e2.y - e1.y * e2.x};
            const float l = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
            if (l < 1e-12f) continue;
            n.x /= l; n.y /= l; n.z /= l;
            t.n = n;
            list.push_back(t);
        }
    }
    if (ys.size() < 100) { glass->state = -1; return; }
    // The roof: the highest point over the middle strip of the width (exhaust stacks and mirrors
    // stand out at the sides; a percentile of all heights lands on the belt, most vertices are low).
    const float W = maxX - minX, midX = 0.5f * (minX + maxX);
    float top = -1e9f;
    for (const gta2::Vec3& p : all)
        if (std::fabs(p.x - midX) < 0.30f * W) top = (std::max)(top, p.y);
    const float H = top - minY, L = maxZ - minZ;
    if (H <= 1e-4f || L <= 1e-4f) { glass->state = -1; return; }
    // The roof line along the length: the highest point in each of 48 slices.
    constexpr int kNb = 48;
    float hm[kNb] = {};
    for (const gta2::Vec3& p : all) {
        const int b = (std::max)(0, (std::min)(kNb - 1, static_cast<int>((p.z - minZ) / L * kNb)));
        hm[b] = (std::max)(hm[b], (std::min)(1.2f, (p.y - minY) / H));
    }
    int r0 = -1, r1 = -1;
    for (int b = 0; b < kNb; ++b) if (hm[b] >= 0.86f) { if (r0 < 0) r0 = b; r1 = b; }
    if (r0 < 0) { glass->state = -1; return; }
    const float z0 = minZ + r0 * L / kNb, z1 = minZ + (r1 + 1) * L / kNb;
    const float rake = 0.45f * H;
    {   // VEHICLE-GLASS-3: a hard top: the roof span is over a fifth of the length and the middle strip stays at
        // 0.80 of the roof over three quarters of it. The game's open tops (CabOpenTop) are open in their
        // sprites, but the generated 030 Land Roamer is a hard-top with windows (span 0.62, 0.83); the real
        // open meshes fail (022 0.60/0.34 gun mount, 031 0.10, 044 0.38/0.39, 045 0.08).
        float hc[kNb];
        for (int b = 0; b < kNb; ++b) hc[b] = -1.0f;
        for (const gta2::Vec3& p : all) {
            if (std::fabs(p.x - midX) >= 0.30f * W) continue;
            const int b = (std::max)(0, (std::min)(kNb - 1, static_cast<int>((p.z - minZ) / L * kNb)));
            hc[b] = (std::max)(hc[b], (p.y - minY) / H);
        }
        int high = 0;
        for (int b = r0; b <= r1; ++b) high += hc[b] >= 0.80f ? 1 : 0;
        glass->closedRoof = (r1 - r0 + 1) >= 0.20f * kNb && high >= 0.75f * (r1 - r0 + 1);
    }

    struct SideStat { float zMin = 1e9f, zMax = -1e9f; float yMax[8]; float xIn[8]; int n[8]; };
    SideStat ss;
    for (int k = 0; k < 8; ++k) { ss.yMax[k] = -1e9f; ss.xIn[k] = 1e9f; ss.n[k] = 0; }
    int totalGlass = 0;
    // The roof line over the middle strip, from the surface samples (a roof triangle spans many
    // slices, so the vertices alone leave slices that only hold the floor).
    float hmC[kNb], under[kNb];
    for (int b = 0; b < kNb; ++b) { hmC[b] = -1e9f; under[b] = -1e9f; }
    std::vector<StemWork> work;
    for (auto& entry : tris) {
        const std::string& stem = entry.first;
        std::vector<float> rgb, paintA;
        if (!Downsample(stem + ".tga", &rgb, nullptr)) continue;
        const bool havePaint = Downsample(stem + "_paint.tga", nullptr, &paintA);
        // UV raster: each texel's point on the body and its face normal.
        std::vector<float> pos(kR * kR * 3, 0.0f), nrm(kR * kR * 3, 0.0f);
        std::vector<uint8_t> valid(kR * kR, 0);
        for (const Tri& t : entry.second) {
            float u[3], v[3];
            float umin = 1e9f, umax = -1e9f, vmin = 1e9f, vmax = -1e9f;
            for (int c = 0; c < 3; ++c) {
                u[c] = (t.uv[c][0] - std::floor(t.uv[c][0])) * kR; v[c] = (t.uv[c][1] - std::floor(t.uv[c][1])) * kR;
                umin = (std::min)(umin, u[c]); umax = (std::max)(umax, u[c]); vmin = (std::min)(vmin, v[c]); vmax = (std::max)(vmax, v[c]);
            }
            if (umax - umin > kR / 2 || vmax - vmin > kR / 2) continue;
            const float den = (v[1] - v[2]) * (u[0] - u[2]) + (u[2] - u[1]) * (v[0] - v[2]);
            if (std::fabs(den) < 1e-9f) continue;
            const float e = -0.6f / std::sqrt(std::fabs(den));
            const int x0 = (std::max)(0, static_cast<int>(std::floor(umin))), x1 = (std::min)(kR - 1, static_cast<int>(std::ceil(umax)));
            const int y0 = (std::max)(0, static_cast<int>(std::floor(vmin))), y1 = (std::min)(kR - 1, static_cast<int>(std::ceil(vmax)));
            for (int y = y0; y <= y1; ++y)
                for (int x = x0; x <= x1; ++x) {
                    const float px = x + 0.5f, py = y + 0.5f;
                    const float l1 = ((v[1] - v[2]) * (px - u[2]) + (u[2] - u[1]) * (py - v[2])) / den;
                    const float l2 = ((v[2] - v[0]) * (px - u[2]) + (u[0] - u[2]) * (py - v[2])) / den;
                    const float l3 = 1.0f - l1 - l2;
                    if (l1 < e || l2 < e || l3 < e) continue;
                    const int i = y * kR + x;
                    pos[i * 3] = l1 * t.p[0].x + l2 * t.p[1].x + l3 * t.p[2].x;
                    pos[i * 3 + 1] = l1 * t.p[0].y + l2 * t.p[1].y + l3 * t.p[2].y;
                    pos[i * 3 + 2] = l1 * t.p[0].z + l2 * t.p[1].z + l3 * t.p[2].z;
                    nrm[i * 3] = t.n.x; nrm[i * 3 + 1] = t.n.y; nrm[i * 3 + 2] = t.n.z;
                    valid[i] = 1;
                }
        }
        for (int i = 0; i < kR * kR; ++i) {
            if (!valid[i] || std::fabs(pos[i * 3] - midX) > 0.30f * W) continue;
            const int b = (std::max)(0, (std::min)(kNb - 1, static_cast<int>((pos[i * 3 + 2] - minZ) / L * kNb)));
            hmC[b] = (std::max)(hmC[b], pos[i * 3 + 1]);
            // The underside: the highest downward-facing surface below the belt (a box body's floor
            // over open chassis).
            if (nrm[i * 3 + 1] < -0.5f && pos[i * 3 + 1] < minY + 0.55f * H) under[b] = (std::max)(under[b], pos[i * 3 + 1]);
        }
        // The body's paint colours: the lower flanks (above the tyres), up to three dominant ones.
        std::vector<int> side;
        for (int pass = 0; pass < 2 && side.size() < 50; ++pass) {
            side.clear();
            for (int i = 0; i < kR * kR; ++i) {
                if (!valid[i]) continue;
                const float h = (pos[i * 3 + 1] - minY) / H;
                if (h < 0.35f || h > 0.55f || std::fabs(nrm[i * 3]) < 0.6f) continue;
                if (pass == 0 && havePaint && paintA[i] < 0.5f) continue;
                side.push_back(i);
            }
        }
        float clusters[kMaxClusters][3]; int nClusters = 0;
        if (!side.empty()) {
            std::map<int, std::vector<int>> bins;
            for (int i : side) {
                const int b = static_cast<int>((std::min)(7.99f, rgb[i * 3] * 8)) * 64 + static_cast<int>((std::min)(7.99f, rgb[i * 3 + 1] * 8)) * 8 +
                              static_cast<int>((std::min)(7.99f, rgb[i * 3 + 2] * 8));
                bins[b].push_back(i);
            }
            std::vector<std::pair<size_t, int>> order;
            for (auto& b : bins) order.push_back({b.second.size(), b.first});
            std::sort(order.rbegin(), order.rend());
            for (auto& o : order) {
                if (nClusters >= 3 || o.first * 100 < side.size() * 15) break;
                float c[3] = {0, 0, 0};
                for (int i : bins[o.second]) for (int k = 0; k < 3; ++k) c[k] += rgb[i * 3 + k];
                for (int k = 0; k < 3; ++k) clusters[nClusters][k] = c[k] / o.first;
                ++nClusters;
            }
        }
        float paintVal = 0.5f;
        for (int c = 0; c < nClusters; ++c)
            paintVal = c == 0 ? (std::max)((std::max)(clusters[c][0], clusters[c][1]), clusters[c][2])
                              : (std::max)(paintVal, (std::max)((std::max)(clusters[c][0], clusters[c][1]), clusters[c][2]));
        bool darkPaint = false;
        for (int c = 0; c < nClusters; ++c)
            if ((std::max)((std::max)(clusters[c][0], clusters[c][1]), clusters[c][2]) < 0.2f) darkPaint = true;
        {   // VEHICLE-GLASS-2: the roof's colour is paint too (the upper body of a two-tone van or bus is the
            // roof's colour, and the flanks never see it). Light, near-neutral roofs only: a dark roof may
            // share the glass's tone, a tinted one is a roof rack or a sign.
            std::vector<int> roof;
            for (int i = 0; i < kR * kR; ++i)
                if (valid[i] && (pos[i * 3 + 1] - minY) / H > 0.92f && nrm[i * 3 + 1] > 0.80f && std::fabs(pos[i * 3] - midX) < 0.30f * W)
                    roof.push_back(i);
            if (roof.size() >= 40) {
                std::map<int, std::vector<int>> bins;
                for (int i : roof)
                    bins[static_cast<int>((std::min)(7.99f, rgb[i * 3] * 8)) * 64 + static_cast<int>((std::min)(7.99f, rgb[i * 3 + 1] * 8)) * 8 +
                         static_cast<int>((std::min)(7.99f, rgb[i * 3 + 2] * 8))].push_back(i);
                std::vector<std::pair<size_t, int>> order;
                for (auto& b : bins) order.push_back({b.second.size(), b.first});
                std::sort(order.rbegin(), order.rend());
                for (size_t o = 0; o < order.size() && o < 2 && nClusters < kMaxClusters; ++o) {
                    if (order[o].first * 100 < roof.size() * 25) break;
                    float c[3] = {0, 0, 0};
                    for (int i : bins[order[o].second]) for (int k = 0; k < 3; ++k) c[k] += rgb[i * 3 + k];
                    for (int k = 0; k < 3; ++k) c[k] /= order[o].first;
                    float ch, cs, cv;
                    HueSat(c[0], c[1], c[2], &ch, &cs, &cv);
                    bool distinct = true;
                    for (int k = 0; k < nClusters; ++k) {
                        const float dr = c[0] - clusters[k][0], dg = c[1] - clusters[k][1], db = c[2] - clusters[k][2];
                        distinct = distinct && dr * dr + dg * dg + db * db > 0.06f * 0.06f;
                    }
                    if (cv > 0.45f && cs < 0.25f && distinct) { for (int k = 0; k < 3; ++k) clusters[nClusters][k] = c[k]; ++nClusters; }
                }
            }
        }
        // VEHICLE-GLASS-3: on a body whose paints are all dark and saturated, a texel off every paint's hue (more
        // than 25 degrees) or far less saturated (under 0.4 of it), and not in shade (at least 0.6 of the
        // nearest paint's value), is not the paint however close in RGB: 030's grey-green windows on dark
        // olive paint (paint hue 100, sat 0.46; window hue 136-143, sat 0.30, 0.025 of RGB apart).
        float cHue[kMaxClusters], cSat[kMaxClusters], cVal[kMaxClusters];
        bool allSaturated = nClusters > 0;
        for (int c = 0; c < nClusters; ++c) {
            HueSat(clusters[c][0], clusters[c][1], clusters[c][2], &cHue[c], &cSat[c], &cVal[c]);
            allSaturated = allSaturated && cSat[c] >= 0.30f && cVal[c] < 0.40f;   // dark ones: 002's cream highlights went white
        }
        // The glasshouse: side faces under the roof, the windscreen ahead of it, the rear screen
        // behind; between the belt and nine tenths of the roof, not the roof or bonnet tops.
        Mask g(kR * kR, 0), band(kR * kR, 0), paintLike(kR * kR, 0), strict(kR * kR, 0);
        // VEHICLE-GLASS-4 (BeltBlack below): per side texel between 0.40 and 0.90 of the roof, paint / near-black
        // for the belt cells, and the glasshouse's near-black texels the tyre-black rule would drop.
        Mask beltPaint(kR * kR, 0), beltBlack(kR * kR, 0), blackCand(kR * kR, 0), liveryM(kR * kR, 0);
        for (int i = 0; i < kR * kR; ++i) {
            if (!valid[i]) continue;
            const float h = (pos[i * 3 + 1] - minY) / H, z = pos[i * 3 + 2];
            const float nx = nrm[i * 3], ny = nrm[i * 3 + 1], nz = nrm[i * 3 + 2];
            const bool beltSide = std::fabs(nx) > 0.4f && h >= 0.40f && h < 0.90f;
            if (!beltSide && (h < 0.60f || h > 0.90f || ny > 0.80f)) continue;
            const bool inRoof = z >= z0 && z <= z1;
            const bool sideW = inRoof && std::fabs(nx) > 0.4f;
            const bool screen = h > 0.64f && ((nz > 0.35f && z > z1 - 0.05f * L && z < z1 + rake) ||
                                              (nz < -0.35f && z < z0 + 0.05f * L && z > z0 - rake));
            const bool inBand = !(h < 0.60f || h > 0.90f || ny > 0.80f) && (sideW || screen);
            if (!inBand && !beltSide) continue;
            const float r = rgb[i * 3], gg = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
            const float val = (std::max)((std::max)(r, gg), b);
            // Livery and paint bands are saturated and bright; glass is not.
            float hue, sat, vv;
            HueSat(r, gg, b, &hue, &sat, &vv);
            const bool rearScreen = !sideW && nz < -0.35f;
            // Strictly bodywork: within 0.12 of a paint colour, a saturated bright livery, or a rear
            // "screen" as light as the paint, or upright and not clearly darker than it (a tailgate).
            bool nearPaint = false;
            float dmin = 9.0f;   // the distance to the nearest paint, in units of its tolerance scale
            bool cooler = nClusters > 0;
            for (int c = 0; c < nClusters; ++c) {
                const float dr = r - clusters[c][0], dg = gg - clusters[c][1], db = b - clusters[c][2];
                const float sc = PaintScale(clusters[c]), d = std::sqrt(dr * dr + dg * dg + db * db);
                nearPaint = nearPaint || d < 0.12f * sc;
                dmin = (std::min)(dmin, d / sc);
                cooler = cooler && (b - r) > (clusters[c][2] - clusters[c][0]) + 0.08f;
            }
            bool offHue = false;
            if (allSaturated) {
                int nearest = 0;
                float best = 1e9f;
                for (int c = 0; c < nClusters; ++c) {
                    const float dr = r - clusters[c][0], dg = gg - clusters[c][1], db = b - clusters[c][2];
                    if (dr * dr + dg * dg + db * db < best) { best = dr * dr + dg * dg + db * db; nearest = c; }
                }
                offHue = vv >= 0.6f * cVal[nearest];
                for (int c = 0; c < nClusters && offHue; ++c) {
                    float dh = std::fabs(hue - cHue[c]);
                    if (dh > 180.0f) dh = 360.0f - dh;
                    offHue = dh > 25.0f || sat < 0.4f * cSat[c];
                }
                if (offHue) nearPaint = false;
            }
            // VEHICLE-GLASS-2: a rear screen reflecting the sky is cooler (bluer) than a warm pale paint:
            // glass, not a tailgate (011). (A dark body's light rear screen was tried and dropped: 012's
            // white-baked rear was only half found, a ragged hole where FIX-SEATED's band looked better.)
            const bool sky = cooler && sat < 0.35f && dmin > 0.10f;
            // A screen carries no livery: its saturated bake (the dash's reflection) may be grown into from
            // the glass around it (012's strip), but never seeds glass (a hot-dog van's sign, 024).
            const bool livery = sideW && sat > 0.55f && vv > 0.25f;
            if (beltSide) {
                beltBlack[i] = val < 0.08f ? 1 : 0;
                beltPaint[i] = (nearPaint || livery) && !beltBlack[i] ? 1 : 0;
            }
            if (!inBand) continue;
            band[i] = 1;
            liveryM[i] = livery ? 1 : 0;
            const bool liveryScreen = !sideW && sat > 0.55f && vv > 0.25f;
            if (nearPaint || livery || (rearScreen && !sky && ((ny < 0.15f && !(vv < 0.55f * paintVal)) || !(vv < 0.9f * paintVal || vv < 0.35f))))
                strict[i] = 1;
            if (strict[i] || liveryScreen || (!offHue && PaintLike(r, gg, b, clusters, nClusters))) {
                paintLike[i] = 1;
                continue;
            }
            if (val < 0.08f && darkPaint) { blackCand[i] = 1; continue; }   // tyre-black (was 0.18: every dark glass texel of a dark car)
            g[i] = 1;
        }
        if (darkPaint && g_beltOn) BeltBlack(g, blackCand, beltPaint, beltBlack, valid, pos, nrm, minY, H, minZ, L);
        g = Dilate(Erode(g));
        g = KeepComponents(g, 30);
        for (int k = 0; k < 2; ++k) g = Dilate(g);
        for (int k = 0; k < 2; ++k) g = Erode(g);
        for (int i = 0; i < kR * kR; ++i) g[i] = g[i] && band[i] && !paintLike[i] ? 1 : 0;
        // Grow the glass over the rest of each pane: the bake paints the lower glass with the cabin's
        // reflection, often the paint's hue; up to 6 texels into anything in the glasshouse that is
        // not strictly bodywork.
        for (int k = 0; k < 6; ++k) {
            const Mask d = Dilate(g);
            for (int i = 0; i < kR * kR; ++i) if (d[i] && band[i] && !strict[i]) g[i] = 1;
        }
        {   // VEHICLE-GLASS-3: the bake paints the cabin seen through a pane in the paint's hue but far darker
            // (000: value 0.26 under a 0.57 paint), paint-like only by hue, and the growth above stops inside such
            // a patch (blobs and drips left in the pane, drawn as hull under Remix). A side texel of that kind
            // becomes glass when real windows (components of 120+ texels) lie on the same side at its height both
            // ahead of it and behind it, within a quarter of the length: a patch between two windows, never an
            // open-ended dark panel (003's shaded flank and rear doors). tools/car_glass_mask.py "deep".
            const Mask big = KeepComponents(g, 120);
            bool G[2][12][48] = {};
            auto bins = [&](int i, int* sd, int* hb, int* zb) {
                *sd = nrm[i * 3] > 0.0f ? 1 : 0;
                *hb = (std::max)(0, (std::min)(11, static_cast<int>(((pos[i * 3 + 1] - minY) / H - 0.60f) / 0.30f * 12)));
                *zb = (std::max)(0, (std::min)(47, static_cast<int>((pos[i * 3 + 2] - minZ) / L * 48)));
            };
            for (int i = 0; i < kR * kR; ++i) {
                if (!big[i] || !band[i] || std::fabs(nrm[i * 3]) <= 0.4f) continue;
                int sd, hb, zb;
                bins(i, &sd, &hb, &zb);
                G[sd][hb][zb] = true;
            }
            Mask bridge(kR * kR, 0);
            for (int i = 0; i < kR * kR; ++i) {
                if (!band[i] || strict[i] || std::fabs(nrm[i * 3]) <= 0.4f || g[i]) continue;
                const float vv = (std::max)((std::max)(rgb[i * 3], rgb[i * 3 + 1]), rgb[i * 3 + 2]);
                if (vv >= 0.45f * paintVal) continue;
                int sd, hb, zb;
                bins(i, &sd, &hb, &zb);
                bool ahead = false, behind = false;
                for (int dh = -1; dh <= 1; ++dh) {
                    const int h2 = (hb + dh + 12) % 12;   // as the twin's np.roll
                    for (int k = 1; k <= 12; ++k) {
                        if (zb + k < 48 && G[sd][h2][zb + k]) ahead = true;
                        if (zb - k >= 0 && G[sd][h2][zb - k]) behind = true;
                    }
                }
                bridge[i] = ahead && behind ? 1 : 0;
            }
            for (int k = 0; k < 16; ++k) {
                const Mask d = Dilate(g);
                for (int i = 0; i < kR * kR; ++i) if (d[i] && bridge[i]) g[i] = 1;
            }
        }
        DropPaintComponents(g, rgb);
        if (g_mirrorOn) MirrorFill(g, band, liveryM, valid, pos, nrm, minY, H, minZ, L);
        if (g_holesOn) FillHoles(g, valid, strict);
        // VEHICLE-GLASS-6: the counting, the dump and the panes run after every texture's mask, once the panes the
        // colour rules missed are synthesized from the glasshouse (SynthesizePanes, model-wide).
        work.push_back(StemWork{stem, std::move(g), std::move(pos), std::move(nrm), std::move(valid), {}});
        {
            Mask& lv = work.back().livery;
            lv.assign(kR * kR, 0);
            for (int i = 0; i < kR * kR; ++i) {
                float hh, sa, va;
                HueSat(rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], &hh, &sa, &va);
                lv[i] = sa > 0.55f && va > 0.60f ? 1 : 0;
            }
        }
    }
    if (g_synthOn) SynthesizePanes(model->name, work, minY, H, minZ, L, z0, z1, rake, midX, W);
    for (StemWork& w : work) {
        const std::string& stem = w.stem;
        Mask& g = w.g;
        const std::vector<float>& pos = w.pos;
        const std::vector<float>& nrm = w.nrm;
        int count = 0;
        for (int i = 0; i < kR * kR; ++i) {
            g[i] = g[i] ? 255 : 0;
            if (!g[i]) continue;
            ++count;
            // The side windows' extent, for the cabin.
            const float x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
            if (nrm[i * 3 + 2] < -0.35f && z < z0 + 0.05f * L) ++glass->rearTexels;
            if (std::fabs(nrm[i * 3]) > 0.4f && z >= z0 && z <= z1) {
                ss.zMin = (std::min)(ss.zMin, z); ss.zMax = (std::max)(ss.zMax, z);
                const int s = (std::max)(0, (std::min)(7, static_cast<int>((z - z0) / (z1 - z0 + 1e-6f) * 8)));
                ss.yMax[s] = (std::max)(ss.yMax[s], y);
                ss.xIn[s] = (std::min)(ss.xIn[s], std::fabs(x - 0.5f * (minX + maxX)));
                ++ss.n[s];
            }
        }
        totalGlass += count;
        {   // GTA2DX9_GLASS_DUMP=1: the mask as a PGM in the run's out folder, for an offline check.
            char v[8] = {};
            if (GetEnvironmentVariableA("GTA2DX9_GLASS_DUMP", v, sizeof v) && v[0] == '1') {
                const std::string path = "Z:\\out\\glass_" + stem + ".pgm";
                if (FILE* f = fopen(path.c_str(), "wb")) {
                    fprintf(f, "P5\n%d %d\n255\n", kR, kR);
                    fwrite(g.data(), 1, g.size(), f);
                    fclose(f);
                }
            }
        }
        {
            Mask pane(kR * kR);
            for (int i = 0; i < kR * kR; ++i) pane[i] = g[i] ? 1 : 0;
            pane = Erode(pane);
            for (auto& v : pane) v = v ? 255 : 0;
            glass->panes[stem] = std::move(pane);
        }
        glass->masks[stem] = std::move(g);
    }
    glass->glassTexels = totalGlass;
    if (totalGlass < 200 || ss.zMax <= ss.zMin) {   // VEHICLE-ART-21: say so (070 Z-Type kept the band silently)
        Log("car glass: %s: %d glass texels: painted windows kept (FIX-SEATED band when seated)", model->name.c_str(), totalGlass);
        glass->state = -1; return;
    }
    // The cabin: a shell just inside the side glass, from the dash (ahead of the side windows'
    // front) to the parcel shelf, floor at 0.30 of the roof, the headliner at the glass's top.
    const float cx = 0.5f * (minX + maxX);
    // Inside the body's ends (a bus's side windows run to its nose).
    float zr = (std::max)(ss.zMin - 0.02f * L, minZ + 0.07f * L), zf = (std::min)(ss.zMax + 0.03f * L, maxZ - 0.07f * L);
    float halfW = 0.0f, ceil = 0.0f; int used = 0;
    for (int s = 0; s < 8; ++s) {
        if (ss.n[s] < 4) continue;
        halfW += ss.xIn[s]; ceil += ss.yMax[s]; ++used;
    }
    if (!used) { glass->state = -1; return; }
    halfW = (std::min)(halfW / used * 0.92f, 0.46f * W);
    ceil = ceil / used + 0.01f * H;
    // Never above the hull: under the lowest roof point (middle strip) over the cabin's length, so the
    // shell cannot stand out of a cab whose roof drops behind the doors.
    {
        int b0 = (std::max)(0, static_cast<int>((zr - minZ) / L * kNb)), b1 = (std::min)(kNb - 1, static_cast<int>((zf - minZ) / L * kNb));
        // VEHICLE-GLASS-3: first trim the cabin's ends (up to a quarter of its length each) where the roof line
        // is under the headliner: the windscreen's or rear screen's slope (030's windscreen dips to 0.67 of
        // the roof in the middle, which capped the headliner under the belt: "no room for a cabin").
        // Only when the untrimmed cap leaves no room (every other body keeps its cabin as before).
        float lowest0 = 1e9f;
        for (int b = b0; b <= b1; ++b) if (hmC[b] > -1e8f) lowest0 = (std::min)(lowest0, hmC[b]);
        const bool trim = lowest0 < 1e8f && (std::min)(ceil, lowest0 - 0.04f * H) < minY + 0.66f * H;   // belt 0.58 + 0.08
        const int trimMax = trim ? (b1 - b0 + 1) / 4 : 0;
        for (int t = 0; t < trimMax && b1 > b0 && hmC[b1] > -1e8f && hmC[b1] < ceil + 0.04f * H; ++t) { --b1; zf = (std::min)(zf, minZ + (b1 + 1) * L / kNb); }
        for (int t = 0; t < trimMax && b0 < b1 && hmC[b0] > -1e8f && hmC[b0] < ceil + 0.04f * H; ++t) { ++b0; zr = (std::max)(zr, minZ + b0 * L / kNb); }
        float lowest = 1e9f;
        for (int b = b0; b <= b1; ++b) if (hmC[b] > -1e8f) lowest = (std::min)(lowest, hmC[b]);
        if (lowest < 1e8f) ceil = (std::min)(ceil, lowest - 0.04f * H);
    }
    float floorY = minY + 0.30f * H;
    const float belt = minY + 0.58f * H;
    {   // Never under the hull: above the highest underside over the cabin's length.
        const int b0 = (std::max)(0, static_cast<int>((zr - minZ) / L * kNb)), b1 = (std::min)(kNb - 1, static_cast<int>((zf - minZ) / L * kNb));
        for (int b = b0; b <= b1; ++b) if (under[b] > -1e8f) floorY = (std::max)(floorY, under[b] + 0.02f * H);
        floorY = (std::min)(floorY, belt - 0.04f * H);
    }
    if (ceil < belt + 0.08f * H) { Log("car glass: %s: no room for a cabin under the roof (headliner %.3f, belt %.3f)", model->name.c_str(), ceil, belt); glass->state = -1; return; }
    int shellKind = -1;   // -1 furniture; else the shell (0 walls, 1 top, 2 bottom by the face)
    auto quad = [&](float a[3], float b[3], float c[3], float d[3], float nx, float ny, float nz, uint32_t col) {
        Quad q;
        memcpy(q.p[0], a, 12); memcpy(q.p[1], b, 12); memcpy(q.p[2], c, 12); memcpy(q.p[3], d, 12);
        q.n[0] = nx; q.n[1] = ny; q.n[2] = nz; q.colour = col;
        q.kind = shellKind < 0 ? 3 : ny < -0.5f ? 1 : ny > 0.5f ? 2 : 0;   // the shell faces inward: its top's normal points down
        glass->cabin.push_back(q);
    };
    // A box's six faces, each facing inward (seen from inside) or outward.
    auto box = [&](float x0, float x1, float y0, float y1, float za, float zb, bool inward, uint32_t side, uint32_t topCol, uint32_t bottomCol) {
        float v[8][3] = {{x0, y0, za}, {x1, y0, za}, {x1, y1, za}, {x0, y1, za}, {x0, y0, zb}, {x1, y0, zb}, {x1, y1, zb}, {x0, y1, zb}};
        // Outward normals; the winding is fixed in the draw from the normal and the eye.
        const float s = inward ? -1.0f : 1.0f;
        quad(v[0], v[1], v[2], v[3], 0, 0, -s, side);         // za end
        quad(v[5], v[4], v[7], v[6], 0, 0, s, side);          // zb end
        quad(v[4], v[0], v[3], v[7], -s, 0, 0, side);         // x0 side
        quad(v[1], v[5], v[6], v[2], s, 0, 0, side);          // x1 side
        quad(v[3], v[2], v[6], v[7], 0, s, 0, topCol);        // top
        quad(v[4], v[5], v[1], v[0], 0, -s, 0, bottomCol);    // bottom
    };
    // Colours: trim near black, a lighter headliner (the depth cue through the glass), seats dark.
    shellKind = 0;
    box(cx - halfW, cx + halfW, floorY, ceil, zr, zf, true, 0xFF1C1A19u, 0xFF4A4642u, 0xFF141210u);
    shellKind = -1;
    const float cabLen = zf - zr;
    if (cabLen > 0.18f * L && halfW > 0.05f) {
        // Seat backs and headrests, front pair and a rear bench when the cabin is long enough.
        const float seatW = halfW * 0.78f;
        const float frontBack = zf - 0.50f * cabLen;
        auto seat = [&](float x0, float x1, float zBack) {
            box(x0, x1, floorY + 0.05f * H, belt + 0.10f * H, zBack - 0.035f * L, zBack, false, 0xFF2A2522u, 0xFF332D29u, 0xFF2A2522u);
            const float hw = 0.30f * (x1 - x0), hc = 0.5f * (x0 + x1);
            box(hc - hw, hc + hw, belt + 0.12f * H, belt + 0.22f * H, zBack - 0.03f * L, zBack - 0.005f * L, false, 0xFF2A2522u, 0xFF332D29u, 0xFF2A2522u);
        };
        seat(cx - halfW * 0.95f, cx - halfW * 0.95f + seatW, frontBack);
        seat(cx + halfW * 0.95f - seatW, cx + halfW * 0.95f, frontBack);
        // FIX-DRIVER-GEOM (pfl74): the driver sits on this seat (hip ahead of its back, on its middle line,
        // the cushion at the back's foot, his head under this cabin's headliner): the figure and the seat drawn
        // through the glass come from one measure of the body. The sprite's window rows put the 001 Wellard's
        // driver on the rear deck, outside the glass.
        glass->seat[0] = halfW * 0.95f - 0.5f * seatW;
        glass->seat[1] = floorY + 0.05f * H - minY;
        // (a long cabin, a van's or a bus's side glass running back to its tail: his hip at most 0.30 behind the dash,
        // not on the middle of the cabin where the seats are drawn)
        // The hip 0.06 ahead of the back's face: the seated figure leans back a little, and at 0.025 his head stood inside
        // the seat back and headrest drawn here (dg74a: no driver seen from any side).
        glass->seat[2] = (std::max)(frontBack + 0.06f, zf - 0.07f * L - 0.30f);
        // The headliner his head must clear: the hull's own roof over the seat (its middle strip, from the hip back to
        // the seat back, less the skin), as the sprite's seat used the hull's top; not this cabin's headliner, which
        // follows the glass's top (0.26 on the 001 against a 0.34 roof): sunk under it his head sat below the
        // Wellard's high waist, no driver seen through any window (dg74b).
        {
            float roofAt = 1e9f;
            const float za = frontBack - 0.04f * L, zb = glass->seat[2];
            const int ba = (std::max)(0, (std::min)(kNb - 1, static_cast<int>((za - minZ) / L * kNb)));
            const int bb = (std::max)(0, (std::min)(kNb - 1, static_cast<int>((zb - minZ) / L * kNb)));
            for (int b = ba; b <= bb; ++b) if (hmC[b] > -1e8f) roofAt = (std::min)(roofAt, hmC[b]);
            const float inner = roofAt < 1e8f ? roofAt - 0.06f * H : ceil;
            glass->seat[3] = (std::max)(ceil, inner) - minY;
        }
        glass->hasSeat = glass->seat[3] > glass->seat[1] + 0.02f;
        if (cabLen > 0.33f * L) {
            box(cx - halfW * 0.95f, cx + halfW * 0.95f, floorY + 0.05f * H, belt + 0.08f * H, zr + 0.02f * L, zr + 0.06f * L, false,
                0xFF2A2522u, 0xFF332D29u, 0xFF2A2522u);
        }
        // The dash: a dark slab across the front, under the windscreen.
        box(cx - halfW * 0.98f, cx + halfW * 0.98f, floorY + 0.10f * H, belt + 0.02f * H, zf - 0.07f * L, zf - 0.005f * L, false,
            0xFF161514u, 0xFF201E1Cu, 0xFF161514u);
    }
    Log("car glass: %s: %d glass texels in %zu texture(s), cabin z %.3f..%.3f, half width %.3f, floor %.3f, headliner %.3f (roof %.3f), rear screen %d",
        model->name.c_str(), totalGlass, glass->masks.size(), zr, zf, halfW, floorY, ceil, top, glass->rearTexels);
    if (glass->hasSeat)
        Log("car glass: %s: driver's seat (front seat) u %.3f cushion %.3f z %+.3f headliner %.3f", model->name.c_str(),
            glass->seat[0], glass->seat[1], glass->seat[2], glass->seat[3]);
    glass->state = 2;
}

IDirect3DTexture9* MakeMask(IDirect3DDevice9* device, const std::vector<uint8_t>& g) {
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(kR, kR, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (FAILED(t->LockRect(0, &lr, nullptr, 0))) { t->Release(); return nullptr; }
    // A 3x3 box blur of the binary mask: the bilinear lookup and the alpha test then cut along a
    // smoothed contour instead of the texel staircase.
    for (int y = 0; y < kR; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
        for (int x = 0; x < kR; ++x) {
            int sum = 0, n = 0;
            for (int dy = -1; dy <= 1; ++dy)
                for (int dx = -1; dx <= 1; ++dx) {
                    const int xx = x + dx, yy = y + dy;
                    if (xx < 0 || yy < 0 || xx >= kR || yy >= kR) continue;
                    sum += g[yy * kR + xx] ? 1 : 0; ++n;
                }
            const uint32_t a = 255u - static_cast<uint32_t>(sum * 255 / n);
            row[x] = (a << 24) | 0x00FFFFFFu;
        }
    }
    t->UnlockRect(0);
    return t;
}

// Under Remix a triangle is a pane when more than half of it is glass on the pane mask (15 points
// spread over its UV footprint): a pillar edge stays metal, a coarse body's large window triangles go.
int PaneVotes(const ModelMesh& mesh, const std::vector<uint8_t>& g, size_t k) {
    const ModelVertex& a = mesh.vertices[mesh.indices[k]];
    const ModelVertex& b = mesh.vertices[mesh.indices[k + 1]];
    const ModelVertex& c = mesh.vertices[mesh.indices[k + 2]];
    int n = 0;
    for (int i = 0; i <= 4; ++i)
        for (int j = 0; i + j <= 4; ++j) {
            const float l0 = i / 4.0f, l1 = j / 4.0f, l2 = 1.0f - l0 - l1;
            float u = l0 * a.u + l1 * b.u + l2 * c.u, v = l0 * a.v + l1 * b.v + l2 * c.v;
            u -= std::floor(u); v -= std::floor(v);
            const int x = (std::min)(kR - 1, static_cast<int>(u * kR)), y = (std::min)(kR - 1, static_cast<int>(v * kR));
            n += g[y * kR + x] ? 1 : 0;
        }
    return n;
}
constexpr int kPaneVotes = 8;   // of 15

// The glass triangles of a mesh: in the plain renderer any of seven points of its UV footprint on
// glass (the mask's stage cuts the exact contour); under Remix the pane triangles (kPaneVotes).
const GlassPart& GlassTris(const ModelMesh& mesh, const std::vector<uint8_t>& g) {
    const bool remix = RemixMode();
    std::map<const ModelMesh*, GlassPart>& cache = remix ? (SplitOn() ? g_splitPane : g_paneTris) : g_meshTris;
    auto it = cache.find(&mesh);
    if (it != cache.end()) return it->second;
    GlassPart& part = cache[&mesh];
    std::vector<uint32_t> out;
    if (remix && SplitOn()) {
        const GlassSplit& sp = SplitFor(mesh, g);
        part.v = sp.paneV;
        part.i = sp.paneI;
        return part;
    } else if (remix) {
        for (size_t k = 0; k + 2 < mesh.indices.size(); k += 3)
            if (PaneVotes(mesh, g, k) >= kPaneVotes) out.insert(out.end(), {mesh.indices[k], mesh.indices[k + 1], mesh.indices[k + 2]});
    } else {
    auto at = [&](float u, float v) {
        u -= std::floor(u); v -= std::floor(v);
        const int x = (std::min)(kR - 1, static_cast<int>(u * kR)), y = (std::min)(kR - 1, static_cast<int>(v * kR));
        return g[y * kR + x] != 0;
    };
    for (size_t k = 0; k + 2 < mesh.indices.size(); k += 3) {
        const ModelVertex& a = mesh.vertices[mesh.indices[k]];
        const ModelVertex& b = mesh.vertices[mesh.indices[k + 1]];
        const ModelVertex& c = mesh.vertices[mesh.indices[k + 2]];
        const float w[7][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {.5f, .5f, 0}, {0, .5f, .5f}, {.5f, 0, .5f}, {1 / 3.f, 1 / 3.f, 1 / 3.f}};
        bool hit = false;
        for (const auto& l : w)
            if (at(l[0] * a.u + l[1] * b.u + l[2] * c.u, l[0] * a.v + l[1] * b.v + l[2] * c.v)) { hit = true; break; }
        if (hit) out.insert(out.end(), {mesh.indices[k], mesh.indices[k + 1], mesh.indices[k + 2]});
    }
    }
    // Only the vertices those triangles use: an "UP" draw copies every vertex in its range.
    std::map<uint32_t, uint32_t> remap;
    for (uint32_t vi : out) {
        auto r = remap.find(vi);
        if (r == remap.end()) { r = remap.emplace(vi, static_cast<uint32_t>(part.v.size())).first; part.v.push_back(mesh.vertices[vi]); }
        part.i.push_back(r->second);
    }
    return part;
}

// This frame's sky as a cube map: zenith overhead, horizon round, a dark street below.
IDirect3DCubeTexture9* SkyCube(IDirect3DDevice9* device) {
    const gta2::SkySettings& sky = gta2::SkyConfig();
    const gta2::SkyColours c = gta2::ComputeSkyColours(sky.sunElevationDeg, sky.sunAzimuthDeg);
    const float key[6] = {c.zenith.x, c.zenith.y, c.zenith.z, c.horizon.x, c.horizon.y, c.horizon.z};
    bool same = g_cube != nullptr;
    for (int k = 0; k < 6 && same; ++k) same = std::fabs(key[k] - g_cubeKey[k]) < 0.01f;
    if (same) return g_cube;
    constexpr int kN = 16;
    if (!g_cube && (FAILED(device->CreateCubeTexture(kN, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_MANAGED, &g_cube, nullptr)) || !g_cube)) {
        g_cube = nullptr;
        return nullptr;
    }
    memcpy(g_cubeKey, key, sizeof key);
    for (int f = 0; f < 6; ++f) {
        D3DLOCKED_RECT lr;
        if (FAILED(g_cube->LockRect(static_cast<D3DCUBEMAP_FACES>(f), 0, &lr, nullptr, 0))) continue;
        for (int y = 0; y < kN; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < kN; ++x) {
                const float s = (x + 0.5f) / kN * 2.0f - 1.0f, t = (y + 0.5f) / kN * 2.0f - 1.0f;
                float d[3];
                switch (f) {   // D3D cube face directions
                    case 0: d[0] = 1; d[1] = -t; d[2] = -s; break;
                    case 1: d[0] = -1; d[1] = -t; d[2] = s; break;
                    case 2: d[0] = s; d[1] = 1; d[2] = t; break;
                    case 3: d[0] = s; d[1] = -1; d[2] = -t; break;
                    case 4: d[0] = s; d[1] = -t; d[2] = 1; break;
                    default: d[0] = -s; d[1] = -t; d[2] = -1; break;
                }
                const float l = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
                const float up = d[1] / l;
                float r, g, b;
                if (up >= 0.0f) {
                    const float k = std::sqrt(up);
                    r = c.horizon.x + (c.zenith.x - c.horizon.x) * k; g = c.horizon.y + (c.zenith.y - c.horizon.y) * k;
                    b = c.horizon.z + (c.zenith.z - c.horizon.z) * k;
                } else {
                    // The street and the buildings: dark grey, lit a little by the horizon.
                    const float k = (std::min)(1.0f, -up * 4.0f);
                    const float gr = 0.10f;
                    r = c.horizon.x * (1 - k) * 0.6f + gr * k; g = c.horizon.y * (1 - k) * 0.6f + gr * k; b = c.horizon.z * (1 - k) * 0.6f + gr * k;
                }
                auto to8 = [](float v) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(1.0f, v)) * 255.0f + 0.5f); };
                row[x] = 0xFF000000u | (to8(r) << 16) | (to8(g) << 8) | to8(b);
            }
        }
        g_cube->UnlockRect(static_cast<D3DCUBEMAP_FACES>(f), 0);
    }
    return g_cube;
}

// The Fresnel ramp (VEHICLE-GLASS-2): 256 x 4, u = 0.5 n.z of the camera-space normal wrapped into
// 0..1, so 2 min(u, 1 - u) is the cosine to the viewer (either face). rgb = the sky reflection's strength (0.20 facing the eye,
// rising to 0.95 at grazing: Schlick's (1 - cos)^5 softened to ^4 for the bakes' low-poly panes),
// alpha = the glass's opacity (car_glass_alpha facing, up to 0.94 at grazing).
IDirect3DTexture9* g_ramp = nullptr;
float g_rampAlpha = -1.0f;
IDirect3DTexture9* FresnelRamp(IDirect3DDevice9* device) {
    if (g_ramp && std::fabs(g_rampAlpha - g_alpha) < 1e-4f) return g_ramp;
    if (!g_ramp && (FAILED(device->CreateTexture(256, 4, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_ramp, nullptr)) || !g_ramp)) {
        g_ramp = nullptr;
        return nullptr;
    }
    D3DLOCKED_RECT lr;
    if (FAILED(g_ramp->LockRect(0, &lr, nullptr, 0))) return nullptr;
    for (int y = 0; y < 4; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
        for (int x = 0; x < 256; ++x) {
            const float u = (x + 0.5f) / 256.0f, c = 2.0f * (std::min)(u, 1.0f - u), k = 1.0f - c;
            const float refl = (std::min)(1.0f, 0.20f + 0.75f * k * k * k * k);
            const float op = (std::min)(1.0f, g_alpha + (0.94f - g_alpha) * k * k * k);
            const uint32_t r8 = static_cast<uint32_t>(refl * 255.0f + 0.5f), a8 = static_cast<uint32_t>(op * 255.0f + 0.5f);
            row[x] = (a8 << 24) | (r8 << 16) | (r8 << 8) | r8;
        }
    }
    g_ramp->UnlockRect(0);
    g_rampAlpha = g_alpha;
    return g_ramp;
}

float Det3(const gta2::Mat4& m) {
    return m.m[0][0] * (m.m[1][1] * m.m[2][2] - m.m[1][2] * m.m[2][1]) - m.m[0][1] * (m.m[1][0] * m.m[2][2] - m.m[1][2] * m.m[2][0]) +
           m.m[0][2] * (m.m[1][0] * m.m[2][1] - m.m[1][1] * m.m[2][0]);
}

}  // namespace

void CarGlassSettings(int enabled, int alphaPercent, int rangeBlocks) {
    g_on = enabled;
    char v[8] = {};
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_REMIX", v, sizeof v) && v[0] == '0') g_remixOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_SPLIT", v, sizeof v) && v[0] == '0') g_splitOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_BELT", v, sizeof v) && v[0] == '0') g_beltOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_MIRROR", v, sizeof v) && v[0] == '0') g_mirrorOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_HOLES", v, sizeof v) && v[0] == '0') g_holesOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_SYNTH", v, sizeof v) && v[0] == '0') g_synthOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_COLUMNS", v, sizeof v) && v[0] == '0') g_columnsOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_COLTOP", v, sizeof v) && v[0] == '0') g_colTopOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_BELTCUT", v, sizeof v) && v[0] == '0') g_beltCutOn = 0;
    if (GetEnvironmentVariableA("GTA2DX9_GLASS_REAR_GATE", v, sizeof v) && v[0] == '1') g_rearGate = 1;
    g_alpha = (std::max)(0.05f, (std::min)(1.0f, alphaPercent / 100.0f));
    g_range = static_cast<float>((std::max)(1, rangeBlocks));
    Log("car glass: %s, alpha %.2f, range %.0f blocks", g_on ? "on" : "off", g_alpha, g_range);
}

void CarGlassSetEnabled(int enabled) {
    if (enabled != g_on)
        Log("car glass: %s (devtools)", enabled == 3 ? "on, Fresnel ramp (experimental)" : enabled == 4 ? "on, Remix whole-triangle cut (A/B)" : enabled ? "on" : "off");
    if ((enabled == 4) != (g_on == 4)) { std::lock_guard<std::mutex> lk(g_lock); g_entries.clear(); }   // the pane parts differ between the cuts
    g_on = enabled;
}
namespace {
bool SplitOn() { return g_splitOn && g_on != 4; }
}  // namespace

bool CarGlassOn() {
    return g_on && (!RemixApiAvailable() || g_remixOn) && CurrentViewMode() != ViewMode::Classic;
}

bool CarGlassReady(IDirect3DDevice9* device, const Model& base) {
    if (!CarGlassOn()) return false;
    std::shared_ptr<Glass> glass;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        if (g_device != device) {
            // A new device: the old textures belong to the old one.
            g_stemTex.clear();
            g_texByName.clear();
            g_entries.clear();
            for (auto& m : g_models) if (m.second->state == 3) m.second->state = 2;
            g_device = device;
        }
        auto it = g_models.find(&base);
        if (it == g_models.end()) {
            glass = std::make_shared<Glass>();
            g_models[&base] = glass;
            std::thread(Build, &base, glass).detach();
            return false;
        }
        glass = it->second;
    }
    const int st = glass->state.load();
    if (st == 3) return true;
    if (st != 2) return false;
    std::lock_guard<std::mutex> lk(g_lock);
    for (auto& m : glass->masks) {
        if (!g_stemTex.count(m.first)) {
            IDirect3DTexture9* t = MakeMask(device, m.second);
            if (!t) return false;
            g_stemTex[m.first] = t;
            g_stemGlass[m.first] = glass;
            g_entries.clear();   // derived models (dents, doors, wheels) asked before this was ready
        }
    }
    glass->state = 3;
    return true;
}

void CarGlassRequestMasks(const Model& base) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (g_models.count(&base)) return;
    auto glass = std::make_shared<Glass>();
    g_models[&base] = glass;
    std::thread(Build, &base, glass).detach();
}

int CarGlassMaskForTexture(const std::string& texture, std::vector<uint8_t>* out, int* size) {
    const std::string stem = StemOf(texture);
    std::lock_guard<std::mutex> lk(g_lock);
    bool pending = false;
    for (auto& m : g_models) {
        const int st = m.second->state.load();
        if (st == 0 || st == 1) { pending = true; continue; }
        if (st < 2) continue;
        auto it = m.second->masks.find(stem);
        if (it == m.second->masks.end()) continue;
        if (out) *out = it->second;
        if (size) *size = kR;
        return 1;
    }
    return pending ? 0 : -1;
}

bool CarGlassPending(const Model& base) {
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_models.find(&base);
    return it == g_models.end() || (it->second->state >= 0 && it->second->state < 2);
}

bool CarGlassHasRear(const Model& base) {
    // VEHICLE-GLASS-4: car_bodies keeps FIX-SEATED's see-through band for a seated car whose rear screen was not
    // found, but that band is a plain-renderer clip-plane draw (never under Remix). Under Remix such a car drew
    // neither: a driven 071 Rumbler (rear 0) kept its whole baked window. Under Remix the glass always wins.
    if (RemixMode() && !g_rearGate) return true;
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_models.find(&base);
    return it != g_models.end() && it->second->rearTexels >= 40;
}

bool CarGlassDriverSeat(const Model& base, float out[4]) {
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_models.find(&base);
    if (it == g_models.end() || it->second->state.load() < 2 || !it->second->hasSeat) return false;
    for (int k = 0; k < 4; ++k) out[k] = it->second->seat[k];
    return true;
}

bool CarGlassClosedRoof(const Model& base) {
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_models.find(&base);
    return it != g_models.end() && it->second->closedRoof;
}

void CarGlassBeginCut(const Model& base, float distance) {
    (void)base;
    g_cut = distance <= g_range;
}
void CarGlassEndCut() { g_cut = false; }

IDirect3DTexture9* CarGlassCutMask(const std::string& texture) {
    if (!g_cut) return nullptr;
    auto c = g_texByName.find(&texture);
    if (c != g_texByName.end()) return c->second;
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_stemTex.find(StemOf(texture));
    IDirect3DTexture9* t = it == g_stemTex.end() ? nullptr : it->second;
    // Only cache a hit: a model whose mask is still being made asks again.
    if (t) g_texByName[&texture] = t;
    return t;
}

IDirect3DIndexBuffer9* CarGlassCutIndexBuffer(IDirect3DDevice9* device, const ModelMesh& mesh, UINT* triangles,
                                              IDirect3DVertexBuffer9** vb, UINT* vertices) {
    if (!g_cut || !RemixMode()) return nullptr;
    if (SplitOn()) {
        const std::vector<uint8_t>* g = nullptr;
        {
            std::lock_guard<std::mutex> lk(g_lock);
            const std::string stem = StemOf(mesh.texture);
            auto gl = g_stemGlass.find(stem);
            if (gl == g_stemGlass.end()) return nullptr;   // not ready yet
            auto mk = gl->second->panes.find(stem);
            if (mk == gl->second->panes.end()) return nullptr;
            g = &mk->second;
        }
        const GlassSplit& sp = SplitFor(mesh, *g);
        if (sp.paneI.empty() || sp.hullI.empty()) return nullptr;
        const StaticBuf* sb = StaticBufFor(device, &sp, sp.hullV.data(), static_cast<UINT>(sp.hullV.size()), sizeof(ModelVertex),
                                           D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1, sp.hullI.data(), static_cast<UINT>(sp.hullI.size()));
        if (!sb || !sb->ib) return nullptr;
        *vb = sb->vb; *vertices = sb->nv; *triangles = sb->ntri;
        return sb->ib;
    }
    auto c = g_cutIb.find(&mesh);
    if (c != g_cutIb.end()) {
        if (c->second.none) return nullptr;
        *triangles = c->second.tris;
        *vb = nullptr;
        return c->second.ib;
    }
    const std::vector<uint8_t>* g = nullptr;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        const std::string stem = StemOf(mesh.texture);
        auto gl = g_stemGlass.find(stem);
        if (gl == g_stemGlass.end()) return nullptr;   // not ready yet: ask again next time
        auto mk = gl->second->panes.find(stem);
        if (mk != gl->second->panes.end()) g = &mk->second;
    }
    CutIb& e = g_cutIb[&mesh];
    e.none = true;
    if (!g) return nullptr;
    std::vector<uint32_t> keep;
    keep.reserve(mesh.indices.size());
    size_t panes = 0;
    for (size_t k = 0; k + 2 < mesh.indices.size(); k += 3) {
        if (PaneVotes(mesh, *g, k) >= kPaneVotes) { ++panes; continue; }
        keep.insert(keep.end(), {mesh.indices[k], mesh.indices[k + 1], mesh.indices[k + 2]});
    }
    if (!panes || keep.empty()) return nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    if (FAILED(device->CreateIndexBuffer(static_cast<UINT>(keep.size() * 4), D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_MANAGED, &ib, nullptr)) || !ib)
        return nullptr;
    void* p = nullptr;
    if (FAILED(ib->Lock(0, 0, &p, 0))) { ib->Release(); return nullptr; }
    memcpy(p, keep.data(), keep.size() * 4);
    ib->Unlock();
    e.ib = ib; e.tris = static_cast<UINT>(keep.size() / 3); e.none = false;
    static int logged = 0;
    if (logged++ < 40) Log("car glass: remix cut %s: %zu pane triangles of %zu", mesh.texture.c_str(), panes, mesh.indices.size() / 3);
    *triangles = e.tris;
    *vb = nullptr;
    return ib;
}

namespace {
const std::vector<DrawEntry>& EntriesFor(const Model& model) {
    auto it = g_entries.find(&model);
    if (it != g_entries.end()) return it->second;
    std::vector<DrawEntry>& out = g_entries[&model];
    std::map<std::string, bool> done;
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& mesh = model.meshes[mi];
        const std::string stem = StemOf(mesh.texture);
        if (done[stem]) continue;   // the paint half repeats the rest's triangles
        auto tx = g_stemTex.find(stem);
        auto gl = g_stemGlass.find(stem);
        if (tx == g_stemTex.end() || gl == g_stemGlass.end()) continue;
        // Under Remix the panes are cut by triangles: the eroded mask keeps the edge triangles hull.
        const std::map<std::string, std::vector<uint8_t>>& src = RemixMode() ? gl->second->panes : gl->second->masks;
        auto mk = src.find(stem);
        if (mk == src.end()) continue;
        done[stem] = true;
        if (GlassTris(mesh, mk->second).i.empty()) continue;   // wheels, a door with no window
        out.push_back({i, &mesh, tx->second, &mk->second});
    }
    return out;
}
}  // namespace

void CarGlassCutQueue(const Model& model, const gta2::Mat4& placement) {
    if (!g_cut) return;
    std::lock_guard<std::mutex> lk(g_lock);
    if (!EntriesFor(model).empty()) g_queue.push_back({&model, placement});
}

void CarGlassDrawInterior(IDirect3DDevice9* device, const Model& base, const gta2::Mat4& placement, bool night) {
    if (!g_cut) return;
    std::shared_ptr<Glass> glass;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        auto it = g_models.find(&base);
        if (it == g_models.end() || it->second->state != 3) return;
        glass = it->second;
    }
    struct V { float x, y, z; uint32_t c; float u, v; };
    const bool remix = RemixMode();
    if (remix && !RemixTextures(device)) return;
    // Under Remix: two draws (trim, headliner), and none of the shell's walls: the path tracer sees
    // them from both sides, so they would stand just inside the glass and hide the cabin; without
    // them a side window shows the seats, the far window and the street beyond, as in a real car.
    std::vector<V> verts, lining;
    verts.reserve(glass->cabin.size() * 6);
    // Which way each face is wound: front faces clockwise in D3D, so a quad meant to be seen from
    // the side its normal points to is wound so; a mirrored placement flips the sense.
    const bool mirrored = Det3(placement) < 0.0f;
    const float dim = night ? 0.45f : 1.0f;
    for (const Quad& q : glass->cabin) {
        if (remix && q.kind == 0) continue;
        std::vector<V>& to = remix && q.kind == 1 ? lining : verts;
        // The quad's own winding normal (model space), against the face's intended normal.
        const float* a = q.p[0]; const float* b = q.p[1]; const float* c = q.p[2];
        const float e1[3] = {b[0] - a[0], b[1] - a[1], b[2] - a[2]}, e2[3] = {c[0] - a[0], c[1] - a[1], c[2] - a[2]};
        const float wn[3] = {e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]};
        // In a left-handed D3D frame a face wound clockwise on screen (kept by CULL_CCW) has its
        // cross product (e1 x e2) pointing toward the eye: flip when it points against the side meant to show.
        bool flip = (wn[0] * q.n[0] + wn[1] * q.n[1] + wn[2] * q.n[2]) < 0.0f;
        if (mirrored) flip = !flip;
        auto col = [&](uint32_t c0) {
            const uint32_t r = static_cast<uint32_t>(((c0 >> 16) & 0xFF) * dim), g = static_cast<uint32_t>(((c0 >> 8) & 0xFF) * dim),
                           bl = static_cast<uint32_t>((c0 & 0xFF) * dim);
            return 0xFF000000u | (r << 16) | (g << 8) | bl;
        };
        const uint32_t cc = col(q.colour);
        const int order[6] = {0, 1, 2, 0, 2, 3};
        const int rev[6] = {0, 2, 1, 0, 3, 2};
        const float uv[4][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
        for (int k = 0; k < 6; ++k) {
            const int ci = flip ? rev[k] : order[k];
            const float* p = q.p[ci];
            to.push_back({p[0], p[1], p[2], remix ? 0xFFFFFFFFu : cc, uv[ci][0], uv[ci][1]});
        }
    }
    if (verts.empty() && lining.empty()) return;
    DWORD lighting, cull, fvf, aTest, aBlend, c0op, c0a1, a0op, a0a1, c1op, a1op, spec;
    IDirect3DBaseTexture9* tex0 = nullptr;
    device->GetRenderState(D3DRS_LIGHTING, &lighting);
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &aTest);
    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &aBlend);
    device->GetRenderState(D3DRS_SPECULARENABLE, &spec);
    device->GetFVF(&fvf);
    device->GetTextureStageState(0, D3DTSS_COLOROP, &c0op);
    device->GetTextureStageState(0, D3DTSS_COLORARG1, &c0a1);
    device->GetTextureStageState(0, D3DTSS_ALPHAOP, &a0op);
    device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &a0a1);
    device->GetTextureStageState(1, D3DTSS_COLOROP, &c1op);
    device->GetTextureStageState(1, D3DTSS_ALPHAOP, &a1op);
    device->GetTexture(0, &tex0);
    D3DMATRIX m;
    memcpy(&m, placement.m, sizeof m);
    device->SetTransform(D3DTS_WORLD, &m);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_CCW);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1);
    device->SetTexture(0, remix ? g_cabinTex[0] : nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, remix ? D3DTA_TEXTURE : D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, remix ? D3DTA_TEXTURE : D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    if (remix) device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    if (remix) {
        const char* key = reinterpret_cast<const char*>(glass.get()) + (mirrored ? 2 : 0);
        const StaticBuf* a = StaticBufFor(device, key, verts.data(), static_cast<UINT>(verts.size()), sizeof(V), D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1, nullptr, 0);
        const StaticBuf* b = StaticBufFor(device, key + 1, lining.data(), static_cast<UINT>(lining.size()), sizeof(V), D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1, nullptr, 0);
        if (a) { device->SetStreamSource(0, a->vb, 0, sizeof(V)); device->DrawPrimitive(D3DPT_TRIANGLELIST, 0, a->ntri); }
        if (b) { device->SetTexture(0, g_cabinTex[1]); device->SetStreamSource(0, b->vb, 0, sizeof(V)); device->DrawPrimitive(D3DPT_TRIANGLELIST, 0, b->ntri); }
        device->SetStreamSource(0, nullptr, 0, 0);
    } else {
        if (!verts.empty()) device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts.size() / 3), verts.data(), sizeof(V));
        if (!lining.empty()) {
            device->SetTexture(0, g_cabinTex[1]);
            device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(lining.size() / 3), lining.data(), sizeof(V));
        }
    }
    device->SetRenderState(D3DRS_LIGHTING, lighting);
    device->SetRenderState(D3DRS_SPECULARENABLE, spec);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, aTest);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, aBlend);
    device->SetFVF(fvf);
    device->SetTexture(0, tex0);
    if (tex0) tex0->Release();
    device->SetTextureStageState(0, D3DTSS_COLOROP, c0op);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, c0a1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, a0op);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, a0a1);
    device->SetTextureStageState(1, D3DTSS_COLOROP, c1op);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, a1op);
}

void CarGlassFlush(IDirect3DDevice9* device) {
    if (g_queue.empty()) return;
    std::vector<Queued> queue;
    queue.swap(g_queue);
    if (!CarGlassOn()) return;
    const bool remix = RemixMode();
    if (remix && !RemixTextures(device)) return;
    IDirect3DCubeTexture9* cube = remix ? nullptr : SkyCube(device);
    if (!remix && !cube) return;
    LARGE_INTEGER t0, t1, freq;
    QueryPerformanceCounter(&t0);
    // What this pass changes, saved and put back (a full state block a frame cost ~0.3 ms on wined3d).
    static const D3DRENDERSTATETYPE kRs[] = {D3DRS_LIGHTING, D3DRS_SPECULARENABLE, D3DRS_LOCALVIEWER, D3DRS_NORMALIZENORMALS,
        D3DRS_COLORVERTEX, D3DRS_DIFFUSEMATERIALSOURCE, D3DRS_AMBIENTMATERIALSOURCE, D3DRS_SPECULARMATERIALSOURCE, D3DRS_CULLMODE,
        D3DRS_ZENABLE, D3DRS_ZWRITEENABLE, D3DRS_ZFUNC, D3DRS_ALPHABLENDENABLE, D3DRS_SRCBLEND, D3DRS_DESTBLEND, D3DRS_ALPHATESTENABLE,
        D3DRS_ALPHAFUNC, D3DRS_ALPHAREF, D3DRS_CLIPPLANEENABLE, D3DRS_STENCILENABLE, D3DRS_COLORWRITEENABLE, D3DRS_TEXTUREFACTOR};
    static const D3DTEXTURESTAGESTATETYPE kTs[] = {D3DTSS_COLOROP, D3DTSS_COLORARG1, D3DTSS_COLORARG2, D3DTSS_ALPHAOP, D3DTSS_ALPHAARG1,
        D3DTSS_ALPHAARG2, D3DTSS_TEXCOORDINDEX, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTSS_RESULTARG};
    static const D3DSAMPLERSTATETYPE kSs[] = {D3DSAMP_MINFILTER, D3DSAMP_MAGFILTER, D3DSAMP_MIPFILTER, D3DSAMP_ADDRESSU, D3DSAMP_ADDRESSV,
        D3DSAMP_ADDRESSW};
    DWORD rs[sizeof kRs / sizeof kRs[0]], ts[4][sizeof kTs / sizeof kTs[0]], sm[3][sizeof kSs / sizeof kSs[0]], fvf = 0;
    for (size_t k = 0; k < sizeof kRs / sizeof kRs[0]; ++k) device->GetRenderState(kRs[k], &rs[k]);
    for (int st = 0; st < 4; ++st) for (size_t k = 0; k < sizeof kTs / sizeof kTs[0]; ++k) device->GetTextureStageState(st, kTs[k], &ts[st][k]);
    for (int st = 0; st < 3; ++st) for (size_t k = 0; k < sizeof kSs / sizeof kSs[0]; ++k) device->GetSamplerState(st, kSs[k], &sm[st][k]);
    device->GetFVF(&fvf);
    IDirect3DBaseTexture9* tex[3] = {nullptr, nullptr, nullptr};
    for (int st = 0; st < 3; ++st) device->GetTexture(st, &tex[st]);
    D3DMATERIAL9 oldMat; device->GetMaterial(&oldMat);
    D3DMATRIX oldWorld, oldTex0, oldTex1;
    device->GetTransform(D3DTS_WORLD, &oldWorld); device->GetTransform(D3DTS_TEXTURE0, &oldTex0); device->GetTransform(D3DTS_TEXTURE1, &oldTex1);
    IDirect3DVertexShader9* vs = nullptr; IDirect3DPixelShader9* ps = nullptr;
    device->GetVertexShader(&vs); device->GetPixelShader(&ps);
    // The reflection: the eye-space reflection vector turned back to the world by the view's
    // rotation (row vectors: world = eye * transpose(view)).
    D3DMATRIX view;
    device->GetTransform(D3DTS_VIEW, &view);
    D3DMATRIX tm = {};
    tm._11 = view._11; tm._12 = view._21; tm._13 = view._31;
    tm._21 = view._12; tm._22 = view._22; tm._23 = view._32;
    tm._31 = view._13; tm._32 = view._23; tm._33 = view._33;
    tm._44 = 1.0f;
    device->SetTransform(D3DTS_TEXTURE0, &tm);
    device->SetVertexShader(nullptr);
    device->SetPixelShader(nullptr);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
    device->SetRenderState(D3DRS_SPECULARENABLE, TRUE);
    device->SetRenderState(D3DRS_LOCALVIEWER, TRUE);
    device->SetRenderState(D3DRS_NORMALIZENORMALS, TRUE);
    device->SetRenderState(D3DRS_COLORVERTEX, FALSE);
    device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_SPECULARMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetRenderState(D3DRS_ZENABLE, TRUE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    const DWORD a8 = static_cast<DWORD>(g_alpha * 255.0f + 0.5f);
    device->SetRenderState(D3DRS_ALPHAREF, (std::max)(1ul, a8 / 2));
    device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
    device->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    device->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    // Reflection strength (rgb) and the glass's opacity (alpha).
    device->SetRenderState(D3DRS_TEXTUREFACTOR, (a8 << 24) | 0x00505050u);
    device->SetTexture(0, cube);
    device->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, D3DTSS_TCI_CAMERASPACEREFLECTIONVECTOR);
    device->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT3);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TFACTOR);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSW, D3DTADDRESS_CLAMP);
    device->SetTextureStageState(1, D3DTSS_TEXCOORDINDEX, 0);
    device->SetTextureStageState(1, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_ADD);
    device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
    device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
    device->SetTextureStageState(1, D3DTSS_ALPHAARG2, D3DTA_TEXTURE | D3DTA_COMPLEMENT);
    device->SetTextureStageState(1, D3DTSS_RESULTARG, D3DTA_CURRENT);
    device->SetSamplerState(1, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(1, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(1, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    device->SetSamplerState(1, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
    device->SetSamplerState(1, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
    device->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    // The glass's own colour: a dark blue-grey tint lit by the scene's lights, and a hard
    // specular for the sun's glint.
    D3DMATERIAL9 mat = {};
    mat.Diffuse = {0.035f, 0.042f, 0.040f, 1.0f};
    mat.Ambient = {0.030f, 0.036f, 0.034f, 1.0f};
    mat.Specular = {0.9f, 0.9f, 0.85f, 1.0f};
    mat.Power = 48.0f;
    device->SetMaterial(&mat);
    // VEHICLE-GLASS-2 Fresnel: real glass reflects more and hides more of the cabin at grazing angles.
    // Stage 0 looks the facing up in a ramp (the camera-space normal's depth component, |n.z| = the
    // cosine to a distant viewer) giving the reflection strength (rgb) and the opacity (alpha); stage 1
    // multiplies the sky reflection by it; stage 2 adds the lit tint and cuts by the mask. GPU texgen,
    // no per-vertex work. EXPERIMENTAL, off: [devtools] car_glass=3 only. In vg2_pl1/pl3 every pane came
    // out at the facing value (uniformly darker, no grazing brightening), so the texgen lookup does not
    // work on wined3d as written; car_glass=1 keeps the constant look (docs/car-glass.md 5.3).
    IDirect3DTexture9* ramp = !remix && g_on == 3 ? FresnelRamp(device) : nullptr;
    const DWORD maskStage = ramp ? 2 : 1;
    if (ramp) {
        D3DMATRIX fm = {};
        fm._31 = 0.5f;   // u = 0.5 n.z, wrapped (the generated coordinate's translation row is not applied: vg2_pl1)
        device->SetTransform(D3DTS_TEXTURE0, &fm);
        device->SetTransform(D3DTS_TEXTURE1, &tm);
        device->SetTexture(0, ramp);
        device->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, D3DTSS_TCI_CAMERASPACENORMAL);
        device->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT2);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        device->SetTexture(1, cube);
        device->SetTextureStageState(1, D3DTSS_TEXCOORDINDEX, D3DTSS_TCI_CAMERASPACEREFLECTIONVECTOR);
        device->SetTextureStageState(1, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT3);
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_CURRENT);
        device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
        device->SetTextureStageState(1, D3DTSS_RESULTARG, D3DTA_CURRENT);
        device->SetSamplerState(1, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device->SetSamplerState(1, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device->SetSamplerState(1, D3DSAMP_ADDRESSW, D3DTADDRESS_CLAMP);
        device->SetTextureStageState(2, D3DTSS_TEXCOORDINDEX, 0);
        device->SetTextureStageState(2, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
        device->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_ADD);
        device->SetTextureStageState(2, D3DTSS_COLORARG1, D3DTA_CURRENT);
        device->SetTextureStageState(2, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device->SetTextureStageState(2, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
        device->SetTextureStageState(2, D3DTSS_ALPHAARG2, D3DTA_TEXTURE | D3DTA_COMPLEMENT);
        device->SetTextureStageState(2, D3DTSS_RESULTARG, D3DTA_CURRENT);
        device->SetSamplerState(2, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(2, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(2, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        device->SetSamplerState(2, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
        device->SetSamplerState(2, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        device->SetTextureStageState(3, D3DTSS_COLOROP, D3DTOP_DISABLE);
        device->SetTextureStageState(3, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    }
    if (remix) {
        // Under Remix: the panes with the fleet's glass texture on stage 0 (its hash keys the layer's
        // translucent material); the sky reflection and the mask stage mean nothing to the path tracer.
        device->SetTexture(0, g_glassTex);
        device->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
        device->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        device->SetTexture(1, nullptr);
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        // Opaque draw state: the translucency is the layer material's (a blended draw is classed by
        // Remix as a legacy translucent surface).
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
        // Unlit, white: Remix multiplies the replacement's albedo by the legacy colour (the lit dark
        // tint of the plain pass made the panes near black and hid the cabin, vg2_rxp1..3).
        device->SetRenderState(D3DRS_LIGHTING, FALSE);
        device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
        device->SetRenderState(D3DRS_TEXTUREFACTOR, 0xFFFFFFFFu);
    }
    int drawn = 0, tris = 0;
    IDirect3DTexture9* bound = nullptr;
    std::lock_guard<std::mutex> lk(g_lock);
    std::vector<gta2::Mat4> worlds;
    for (const Queued& q : queue) {
        const std::vector<DrawEntry>& entries = EntriesFor(*q.model);
        if (entries.empty()) continue;
        ModelRestNodeWorlds(*q.model, &worlds);
        for (const DrawEntry& e : entries) {
            const size_t i = e.node;
            if (i >= worlds.size()) continue;
            const ModelMesh& mesh = *e.mesh;
            const GlassPart& part = GlassTris(mesh, *e.g);
            const std::vector<uint32_t>& idx = part.i;
            if (!remix && e.mask != bound) { device->SetTexture(maskStage, e.mask); bound = e.mask; }
            gta2::Mat4 w;
            for (int r = 0; r < 4; ++r)
                for (int c = 0; c < 4; ++c)
                    w.m[r][c] = worlds[i].m[r][0] * q.placement.m[0][c] + worlds[i].m[r][1] * q.placement.m[1][c] +
                                worlds[i].m[r][2] * q.placement.m[2][c] + worlds[i].m[r][3] * q.placement.m[3][c];
            D3DMATRIX m;
            memcpy(&m, w.m, sizeof m);
            device->SetTransform(D3DTS_WORLD, &m);
            const StaticBuf* sb = remix ? StaticBufFor(device, &part, part.v.data(), static_cast<UINT>(part.v.size()), sizeof(ModelVertex),
                                                       D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1, idx.data(), static_cast<UINT>(idx.size()))
                                        : nullptr;
            if (sb) {
                device->SetStreamSource(0, sb->vb, 0, sizeof(ModelVertex));
                device->SetIndices(sb->ib);
                device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, sb->nv, 0, sb->ntri);
            } else {
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(part.v.size()), static_cast<UINT>(idx.size() / 3),
                                               idx.data(), D3DFMT_INDEX32, part.v.data(), sizeof(ModelVertex));
            }
            ++drawn; tris += static_cast<int>(idx.size() / 3);
        }
    }
    if (remix) { device->SetStreamSource(0, nullptr, 0, 0); device->SetIndices(nullptr); }
    for (size_t k = 0; k < sizeof kRs / sizeof kRs[0]; ++k) device->SetRenderState(kRs[k], rs[k]);
    for (int st = 0; st < 4; ++st) for (size_t k = 0; k < sizeof kTs / sizeof kTs[0]; ++k) device->SetTextureStageState(st, kTs[k], ts[st][k]);
    for (int st = 0; st < 3; ++st) for (size_t k = 0; k < sizeof kSs / sizeof kSs[0]; ++k) device->SetSamplerState(st, kSs[k], sm[st][k]);
    device->SetFVF(fvf);
    for (int st = 0; st < 3; ++st) { device->SetTexture(st, tex[st]); if (tex[st]) tex[st]->Release(); }
    device->SetMaterial(&oldMat);
    device->SetTransform(D3DTS_WORLD, &oldWorld); device->SetTransform(D3DTS_TEXTURE0, &oldTex0);
    device->SetTransform(D3DTS_TEXTURE1, &oldTex1);
    device->SetVertexShader(vs); device->SetPixelShader(ps);
    if (vs) vs->Release();
    if (ps) ps->Release();
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&freq);
    static double sumMs = 0.0, worst = 0.0;
    static int frames = 0, sumDrawn = 0, sumTris = 0;
    const double ms = static_cast<double>(t1.QuadPart - t0.QuadPart) * 1000.0 / static_cast<double>(freq.QuadPart);
    sumMs += ms; worst = (std::max)(worst, ms); sumDrawn += drawn; sumTris += tris;
    if (++frames >= 300) {
        Log("car glass: %.3f ms avg, %.3f worst over %d frames, %.1f glass draws (%.0f triangles) a frame", sumMs / frames, worst, frames,
            static_cast<double>(sumDrawn) / frames, static_cast<double>(sumTris) / frames);
        sumMs = worst = 0.0; frames = sumDrawn = sumTris = 0;
    }
}

void CarGlassReleaseDevice() {
    std::lock_guard<std::mutex> lk(g_lock);
    for (auto& t : g_stemTex) if (t.second) t.second->Release();
    g_stemTex.clear();
    g_stemGlass.clear();
    g_texByName.clear();
    g_entries.clear();
    for (auto& m : g_models) if (m.second->state == 3) m.second->state = 2;
    if (g_cube) { g_cube->Release(); g_cube = nullptr; }
    if (g_glassTex) { g_glassTex->Release(); g_glassTex = nullptr; }
    if (g_ramp) { g_ramp->Release(); g_ramp = nullptr; }
    for (auto& t : g_cabinTex) if (t) { t->Release(); t = nullptr; }
    for (auto& c : g_cutIb) if (c.second.ib) c.second.ib->Release();
    g_cutIb.clear();
    g_split.clear();
    for (auto& b : g_staticBufs) { if (b.second.vb) b.second.vb->Release(); if (b.second.ib) b.second.ib->Release(); }
    g_staticBufs.clear();
    g_queue.clear();
}

// FIX-PERF-4: this module's caches for the `mem:` lines (mem_stats.h).
void CarGlassMemGauges() {
    MemGauge("cg.models", static_cast<double>(g_models.size() + g_entries.size()));
    MemGauge("cg.meshes", static_cast<double>(g_meshTris.size() + g_split.size() + g_splitPane.size() + g_paneTris.size() + g_cutIb.size()));
    MemGauge("cg.static", static_cast<double>(g_staticBufs.size()));
    MemGauge("cg.stemtex", static_cast<double>(g_stemTex.size() + g_texByName.size()));
}

}  // namespace gta2dx9
