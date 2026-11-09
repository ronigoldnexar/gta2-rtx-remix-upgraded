// See car_glass.h.
#include "car_glass.h"

#include <algorithm>
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

namespace gta2dx9 {
namespace {

constexpr int kR = 256;        // mask resolution (the body textures are 512 or 1024)
int g_on = 1;
float g_alpha = 0.52f;
float g_range = 40.0f;

struct Quad { float p[4][3]; float n[3]; uint32_t colour; };

struct Glass {
    std::atomic<int> state{0};   // 0 queued, 1 building, 2 built (CPU), 3 textures made, -1 no glass
    std::map<std::string, std::vector<uint8_t>> masks;   // stem -> kR*kR, 255 = glass
    std::vector<Quad> cabin;     // model space
    int glassTexels = 0;
    int rearTexels = 0;          // of them on a rear screen (the seated driver seen from behind)
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

// A texel of the body's paint: near one of its colours, or (a saturated paint) the same hue,
// brighter or darker (the bake keeps the concept's highlights and shade on the panels).
bool PaintLike(float r, float g, float b, const float clusters[3][3], int n) {
    float hue, sat, val;
    HueSat(r, g, b, &hue, &sat, &val);
    for (int c = 0; c < n; ++c) {
        const float dr = r - clusters[c][0], dg = g - clusters[c][1], db = b - clusters[c][2];
        if (dr * dr + dg * dg + db * db < 0.10f * 0.10f) return true;
        float ch, cs, cv;
        HueSat(clusters[c][0], clusters[c][1], clusters[c][2], &ch, &cs, &cv);
        if (cs < 0.30f || sat < 0.25f || val < 0.10f) continue;
        float dh = std::fabs(hue - ch);
        if (dh > 180.0f) dh = 360.0f - dh;
        if (dh < 22.0f && sat > 0.45f * cs) return true;
    }
    return false;
}

// Drops the glass components that read as paint as a whole: bright and tinted (a cream or white
// upper body of a two-tone van, a cargo bed's slats, a roof sign), or near white. Glass in the bakes
// is darker, or a near-neutral pale grey (sat under 0.12).
int DropPaintComponents(Mask& g, const std::vector<float>& rgb) {
    std::vector<int> label(g.size(), 0), stack, pts;
    int n = 0, dropped = 0;
    for (int i = 0; i < kR * kR; ++i) {
        if (!g[i] || label[i]) continue;
        ++n;
        stack.assign(1, i); label[i] = n; pts.clear();
        double sv = 0, ss = 0;
        while (!stack.empty()) {
            const int a = stack.back(); stack.pop_back();
            pts.push_back(a);
            float hue, sat, val;
            HueSat(rgb[a * 3], rgb[a * 3 + 1], rgb[a * 3 + 2], &hue, &sat, &val);
            sv += val; ss += sat;
            const int x = a % kR, y = a / kR;
            const int nb[4] = {x > 0 ? a - 1 : -1, x + 1 < kR ? a + 1 : -1, y > 0 ? a - kR : -1, y + 1 < kR ? a + kR : -1};
            for (int b : nb)
                if (b >= 0 && g[b] && !label[b]) { label[b] = n; stack.push_back(b); }
        }
        const double mv = sv / pts.size(), ms = ss / pts.size();
        if ((mv > 0.62 && ms > 0.12) || mv > 0.85) {
            for (int a : pts) g[a] = 0;
            ++dropped;
        }
    }
    return dropped;
}

// The mask and the cabin of one model (worker thread; the model is immutable once loaded).
void Build(const Model* model, std::shared_ptr<Glass> glass) {
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

    struct SideStat { float zMin = 1e9f, zMax = -1e9f; float yMax[8]; float xIn[8]; int n[8]; };
    SideStat ss;
    for (int k = 0; k < 8; ++k) { ss.yMax[k] = -1e9f; ss.xIn[k] = 1e9f; ss.n[k] = 0; }
    int totalGlass = 0;
    // The roof line over the middle strip, from the surface samples (a roof triangle spans many
    // slices, so the vertices alone leave slices that only hold the floor).
    float hmC[kNb], under[kNb];
    for (int b = 0; b < kNb; ++b) { hmC[b] = -1e9f; under[b] = -1e9f; }
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
        float clusters[3][3]; int nClusters = 0;
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
        // The glasshouse: side faces under the roof, the windscreen ahead of it, the rear screen
        // behind; between the belt and nine tenths of the roof, not the roof or bonnet tops.
        Mask g(kR * kR, 0), band(kR * kR, 0), paintLike(kR * kR, 0), strict(kR * kR, 0);
        for (int i = 0; i < kR * kR; ++i) {
            if (!valid[i]) continue;
            const float h = (pos[i * 3 + 1] - minY) / H, z = pos[i * 3 + 2];
            const float nx = nrm[i * 3], ny = nrm[i * 3 + 1], nz = nrm[i * 3 + 2];
            if (h < 0.60f || h > 0.90f || ny > 0.80f) continue;
            const bool inRoof = z >= z0 && z <= z1;
            const bool sideW = inRoof && std::fabs(nx) > 0.4f;
            const bool screen = h > 0.64f && ((nz > 0.35f && z > z1 - 0.05f * L && z < z1 + rake) ||
                                              (nz < -0.35f && z < z0 + 0.05f * L && z > z0 - rake));
            if (!sideW && !screen) continue;
            band[i] = 1;
            const float r = rgb[i * 3], gg = rgb[i * 3 + 1], b = rgb[i * 3 + 2];
            const float val = (std::max)((std::max)(r, gg), b);
            // Livery and paint bands are saturated and bright; glass is not.
            float hue, sat, vv;
            HueSat(r, gg, b, &hue, &sat, &vv);
            const bool rearScreen = !sideW && nz < -0.35f;
            // Strictly bodywork: within 0.12 of a paint colour, a saturated bright livery, or a rear
            // "screen" as light as the paint, or upright and not clearly darker than it (a tailgate).
            bool nearPaint = false;
            for (int c = 0; c < nClusters && !nearPaint; ++c) {
                const float dr = r - clusters[c][0], dg = gg - clusters[c][1], db = b - clusters[c][2];
                nearPaint = dr * dr + dg * dg + db * db < 0.12f * 0.12f;
            }
            if (nearPaint || (sat > 0.55f && vv > 0.25f) || (rearScreen && ((ny < 0.15f && !(vv < 0.55f * paintVal)) || !(vv < 0.9f * paintVal || vv < 0.35f))))
                strict[i] = 1;
            if (strict[i] || PaintLike(r, gg, b, clusters, nClusters)) {
                paintLike[i] = 1;
                continue;
            }
            if (val < 0.18f && darkPaint) continue;
            g[i] = 1;
        }
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
        DropPaintComponents(g, rgb);
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
        glass->masks[stem] = std::move(g);
    }
    glass->glassTexels = totalGlass;
    if (totalGlass < 200 || ss.zMax <= ss.zMin) { glass->state = -1; return; }
    // The cabin: a shell just inside the side glass, from the dash (ahead of the side windows'
    // front) to the parcel shelf, floor at 0.30 of the roof, the headliner at the glass's top.
    const float cx = 0.5f * (minX + maxX);
    // Inside the body's ends (a bus's side windows run to its nose).
    const float zr = (std::max)(ss.zMin - 0.02f * L, minZ + 0.07f * L), zf = (std::min)(ss.zMax + 0.03f * L, maxZ - 0.07f * L);
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
        const int b0 = (std::max)(0, static_cast<int>((zr - minZ) / L * kNb)), b1 = (std::min)(kNb - 1, static_cast<int>((zf - minZ) / L * kNb));
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
    auto quad = [&](float a[3], float b[3], float c[3], float d[3], float nx, float ny, float nz, uint32_t col) {
        Quad q;
        memcpy(q.p[0], a, 12); memcpy(q.p[1], b, 12); memcpy(q.p[2], c, 12); memcpy(q.p[3], d, 12);
        q.n[0] = nx; q.n[1] = ny; q.n[2] = nz; q.colour = col;
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
    box(cx - halfW, cx + halfW, floorY, ceil, zr, zf, true, 0xFF1C1A19u, 0xFF4A4642u, 0xFF141210u);
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
        if (cabLen > 0.33f * L) {
            box(cx - halfW * 0.95f, cx + halfW * 0.95f, floorY + 0.05f * H, belt + 0.08f * H, zr + 0.02f * L, zr + 0.06f * L, false,
                0xFF2A2522u, 0xFF332D29u, 0xFF2A2522u);
        }
        // The dash: a dark slab across the front, under the windscreen.
        box(cx - halfW * 0.98f, cx + halfW * 0.98f, floorY + 0.10f * H, belt + 0.02f * H, zf - 0.07f * L, zf - 0.005f * L, false,
            0xFF161514u, 0xFF201E1Cu, 0xFF161514u);
    }
    Log("car glass: %s: %d glass texels in %zu texture(s), cabin z %.3f..%.3f, half width %.3f, floor %.3f, headliner %.3f (roof %.3f)",
        model->name.c_str(), totalGlass, glass->masks.size(), zr, zf, halfW, floorY, ceil, top);
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

// The glass triangles of a mesh: any of seven points of its UV footprint on glass.
const GlassPart& GlassTris(const ModelMesh& mesh, const std::vector<uint8_t>& g) {
    auto it = g_meshTris.find(&mesh);
    if (it != g_meshTris.end()) return it->second;
    GlassPart& part = g_meshTris[&mesh];
    std::vector<uint32_t> out;
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

float Det3(const gta2::Mat4& m) {
    return m.m[0][0] * (m.m[1][1] * m.m[2][2] - m.m[1][2] * m.m[2][1]) - m.m[0][1] * (m.m[1][0] * m.m[2][2] - m.m[1][2] * m.m[2][0]) +
           m.m[0][2] * (m.m[1][0] * m.m[2][1] - m.m[1][1] * m.m[2][0]);
}

}  // namespace

void CarGlassSettings(int enabled, int alphaPercent, int rangeBlocks) {
    g_on = enabled;
    g_alpha = (std::max)(0.05f, (std::min)(1.0f, alphaPercent / 100.0f));
    g_range = static_cast<float>((std::max)(1, rangeBlocks));
    Log("car glass: %s, alpha %.2f, range %.0f blocks", g_on ? "on" : "off", g_alpha, g_range);
}

void CarGlassSetEnabled(int enabled) {
    if ((enabled != 0) != (g_on != 0)) Log("car glass: %s (devtools)", enabled ? "on" : "off");
    g_on = enabled;
}

bool CarGlassOn() {
    return g_on && !RemixApiAvailable() && CurrentViewMode() != ViewMode::Classic;
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

bool CarGlassHasRear(const Model& base) {
    std::lock_guard<std::mutex> lk(g_lock);
    auto it = g_models.find(&base);
    return it != g_models.end() && it->second->rearTexels >= 40;
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
        auto mk = gl->second->masks.find(stem);
        if (mk == gl->second->masks.end()) continue;
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
    struct V { float x, y, z; uint32_t c; };
    std::vector<V> verts;
    verts.reserve(glass->cabin.size() * 6);
    // Which way each face is wound: front faces clockwise in D3D, so a quad meant to be seen from
    // the side its normal points to is wound so; a mirrored placement flips the sense.
    const bool mirrored = Det3(placement) < 0.0f;
    const float dim = night ? 0.45f : 1.0f;
    for (const Quad& q : glass->cabin) {
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
        for (int k = 0; k < 6; ++k) {
            const float* p = q.p[flip ? rev[k] : order[k]];
            verts.push_back({p[0], p[1], p[2], cc});
        }
    }
    if (verts.empty()) return;
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
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts.size() / 3), verts.data(), sizeof(V));
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
    IDirect3DCubeTexture9* cube = SkyCube(device);
    if (!cube) return;
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
    DWORD rs[sizeof kRs / sizeof kRs[0]], ts[3][sizeof kTs / sizeof kTs[0]], sm[2][sizeof kSs / sizeof kSs[0]], fvf = 0;
    for (size_t k = 0; k < sizeof kRs / sizeof kRs[0]; ++k) device->GetRenderState(kRs[k], &rs[k]);
    for (int st = 0; st < 3; ++st) for (size_t k = 0; k < sizeof kTs / sizeof kTs[0]; ++k) device->GetTextureStageState(st, kTs[k], &ts[st][k]);
    for (int st = 0; st < 2; ++st) for (size_t k = 0; k < sizeof kSs / sizeof kSs[0]; ++k) device->GetSamplerState(st, kSs[k], &sm[st][k]);
    device->GetFVF(&fvf);
    IDirect3DBaseTexture9* tex[2] = {nullptr, nullptr};
    device->GetTexture(0, &tex[0]); device->GetTexture(1, &tex[1]);
    D3DMATERIAL9 oldMat; device->GetMaterial(&oldMat);
    D3DMATRIX oldWorld, oldTex0;
    device->GetTransform(D3DTS_WORLD, &oldWorld); device->GetTransform(D3DTS_TEXTURE0, &oldTex0);
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
            if (e.mask != bound) { device->SetTexture(1, e.mask); bound = e.mask; }
            gta2::Mat4 w;
            for (int r = 0; r < 4; ++r)
                for (int c = 0; c < 4; ++c)
                    w.m[r][c] = worlds[i].m[r][0] * q.placement.m[0][c] + worlds[i].m[r][1] * q.placement.m[1][c] +
                                worlds[i].m[r][2] * q.placement.m[2][c] + worlds[i].m[r][3] * q.placement.m[3][c];
            D3DMATRIX m;
            memcpy(&m, w.m, sizeof m);
            device->SetTransform(D3DTS_WORLD, &m);
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(part.v.size()), static_cast<UINT>(idx.size() / 3),
                                           idx.data(), D3DFMT_INDEX32, part.v.data(), sizeof(ModelVertex));
            ++drawn; tris += static_cast<int>(idx.size() / 3);
        }
    }
    for (size_t k = 0; k < sizeof kRs / sizeof kRs[0]; ++k) device->SetRenderState(kRs[k], rs[k]);
    for (int st = 0; st < 3; ++st) for (size_t k = 0; k < sizeof kTs / sizeof kTs[0]; ++k) device->SetTextureStageState(st, kTs[k], ts[st][k]);
    for (int st = 0; st < 2; ++st) for (size_t k = 0; k < sizeof kSs / sizeof kSs[0]; ++k) device->SetSamplerState(st, kSs[k], sm[st][k]);
    device->SetFVF(fvf);
    for (int st = 0; st < 2; ++st) { device->SetTexture(st, tex[st]); if (tex[st]) tex[st]->Release(); }
    device->SetMaterial(&oldMat);
    device->SetTransform(D3DTS_WORLD, &oldWorld); device->SetTransform(D3DTS_TEXTURE0, &oldTex0);
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
    g_queue.clear();
}

}  // namespace gta2dx9
