// See car_bodies.h.
#include "car_bodies.h"

#include "live_geometry.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <tuple>

#include "compat.h"
#include "log.h"
#include "model_store.h"
#include "remix_api.h"
#include "texture_store.h"

namespace gta2dx9 {
namespace {

constexpr float kPi = 3.14159265358979f;
constexpr int kStations = 26;        // cross-sections along the length
constexpr int kAtlasScale = 4;       // the sprite is scaled up this much for the roof
constexpr int kBandRows = 32;        // the side strip under the sprite in the atlas
constexpr int kBlockRows = 16;       // the caps, rubber and hub blocks under that
constexpr int kWheelSegments = 14;
constexpr size_t kCacheMax = 96;

std::map<int, gta2::CarInfo> g_info;
int g_built = 0, g_drawn = 0;
bool g_wreckTest = false;   // [devtools] wreck_models=1: every car drawn as a wreck, to check the models
int g_forceModel = -1;      // [devtools] force_car_model=N: every traffic car drawn as model N (re-read once a second)
int g_forceDamage = -1;     // [devtools] force_car_damage=N: every car body drawn at damage byte N (re-read once a second)
int g_forceDoor = 0;        // [devtools] force_car_door=1|-1: every car body drawn with its right|left door open (re-read once a second)
char g_devIni[260] = {};
int g_logNoses = -1;        // GTA2DX9_LOG_CAR_NOSES=1: a line per drawn car every 15 frames, for tools/check_car_noses.py
// Where the cars stage's time went in the last call: measuring artwork, building
// bodies, drawing models, drawing sprite-built bodies (ms), and the counts.
double g_carStats[8] = {};
LARGE_INTEGER g_carFreq = {};
double CarNowMs() {
    if (!g_carFreq.QuadPart) QueryPerformanceFrequency(&g_carFreq);
    LARGE_INTEGER t; QueryPerformanceCounter(&t);
    return 1000.0 * static_cast<double>(t.QuadPart) / static_cast<double>(g_carFreq.QuadPart);
}

struct Rgb { float r, g, b; };

inline uint32_t Pack(Rgb c) {
    auto q = [](float v) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(255.0f, v + 0.5f))); };
    return 0xFF000000u | (q(c.r) << 16) | (q(c.g) << 8) | q(c.b);
}
inline Rgb Unpack(uint32_t c) {
    return {static_cast<float>((c >> 16) & 0xFF), static_cast<float>((c >> 8) & 0xFF), static_cast<float>(c & 0xFF)};
}
inline Rgb Scale(Rgb c, float k) { return {c.r * k, c.g * k, c.b * k}; }
inline Rgb Mix(Rgb a, Rgb b, float t) { return {a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t}; }
inline float Luma(Rgb c) { return 0.299f * c.r + 0.587f * c.g + 0.114f * c.b; }
inline float Smooth(float t) { t = (std::max)(0.0f, (std::min)(1.0f, t)); return t * t * (3.0f - 2.0f * t); }

// Scale2x (EPX): doubles a picture, rounding the staircases of the pixel art
// without blurring it. Whole ARGB values, so the cutout keeps its shape.
std::vector<uint32_t> Scale2x(const std::vector<uint32_t>& src, int w, int h) {
    std::vector<uint32_t> out(static_cast<size_t>(w) * h * 4);
    auto at = [&](int x, int y) {
        x = (std::max)(0, (std::min)(w - 1, x));
        y = (std::max)(0, (std::min)(h - 1, y));
        return src[static_cast<size_t>(y) * w + x];
    };
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const uint32_t p = at(x, y), a = at(x, y - 1), b = at(x + 1, y), c = at(x - 1, y), d = at(x, y + 1);
            uint32_t e0 = p, e1 = p, e2 = p, e3 = p;
            if (c == a && c != d && a != b) e0 = a;
            if (a == b && a != c && b != d) e1 = b;
            if (d == c && d != b && c != a) e2 = c;
            if (b == d && b != a && d != c) e3 = d;
            uint32_t* row0 = &out[static_cast<size_t>(y * 2) * w * 2 + x * 2];
            uint32_t* row1 = row0 + static_cast<size_t>(w) * 2;
            row0[0] = e0; row0[1] = e1; row1[0] = e2; row1[1] = e3;
        }
    }
    return out;
}

// Transparent texels take the colour of their nearest opaque neighbour, so
// bilinear sampling at the outline never pulls in black.
void ExtendEdges(std::vector<uint32_t>* px, int w, int h, int passes) {
    std::vector<uint32_t> next;
    for (int pass = 0; pass < passes; ++pass) {
        next = *px;
        bool any = false;
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                uint32_t& p = next[static_cast<size_t>(y) * w + x];
                if (p >> 24) continue;
                const int dx[4] = {1, -1, 0, 0}, dy[4] = {0, 0, 1, -1};
                for (int k = 0; k < 4; ++k) {
                    const int nx = x + dx[k], ny = y + dy[k];
                    if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
                    const uint32_t q = (*px)[static_cast<size_t>(ny) * w + nx];
                    if (q >> 24) { p = q; any = true; break; }
                }
            }
        }
        px->swap(next);
        if (!any) break;
    }
}

struct Measure {
    int w = 0, h = 0;             // sprite canvas
    int top = 0, bottom = 0;      // opaque rows: tail .. nose (inclusive)
    std::vector<float> halfW;     // per canvas row, pixels, 0 where empty
    float maxHalfW = 0.0f;
    float cabinRear = 0.0f, cabinFront = 0.0f;   // rows (nose is larger)
    float wheelFront = 0.0f, wheelRear = 0.0f;   // rows
    int doors = 2;
    Rgb paint{128, 128, 128};
    std::vector<Rgb> rowPaint;   // per canvas row
    bool hasInfo = false;
};

struct Built {
    IDirect3DTexture9* atlas = nullptr;
    std::vector<CarBodyVertex> verts;
    std::vector<uint16_t> indices;
    std::vector<CarBodyVertex> wheelVerts;
    std::vector<uint16_t> wheelIndices;
    // Managed buffers of the two meshes, filled once (see model_store.cpp for
    // why not DrawIndexedPrimitiveUP); null when the device gave none.
    IDirect3DVertexBuffer9* vb = nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    IDirect3DVertexBuffer9* wvb = nullptr;
    IDirect3DIndexBuffer9* wib = nullptr;
    bool buffersTried = false;
    // What any hand-made model of this car needs: its paint and its footprint.
    Rgb paint{128, 128, 128};
    float bodyLength = 1.0f, bodyWidth = 0.5f;   // tiles
    float scale = 1.0f / 64.0f;                  // tiles per sprite pixel
    bool measured = false;
    Measure measure;
    std::vector<uint32_t> px;
    bool meshBuilt = false;
    float wheelZ[2] = {0.0f, 0.0f};   // front, rear
    float wheelX = 0.0f;              // half track
    float wheelY = 0.0f;              // axle height
    float wheelbase = 0.3f;
    float deckY = 0.0f, roofY = 0.0f;   // the hood line and the roof, blocks
    uint32_t used = 0;
    bool ok = false;
};
void ReleaseBuffers(Built* b) {
    if (b->vb) b->vb->Release();
    if (b->ib) b->ib->Release();
    if (b->wvb) b->wvb->Release();
    if (b->wib) b->wib->Release();
    b->vb = nullptr; b->ib = nullptr; b->wvb = nullptr; b->wib = nullptr;
}

struct Key {
    int sprite;
    IDirect3DTexture9* art;
    bool operator<(const Key& o) const { return sprite != o.sprite ? sprite < o.sprite : art < o.art; }
};
std::map<Key, Built> g_cache;
IDirect3DDevice9* g_device = nullptr;

struct Steer {
    float x = 0, z = 0, yaw = 0, angle = 0;
    uint32_t frame = 0;
};
std::map<uintptr_t, Steer> g_steer;

struct Cabin {
    float deck, roof, windscreen, halfWidth;
    uint32_t frame;
    float length, height;   // the body as drawn: blocks along it and its full height (roof gear included)
};
std::map<uintptr_t, Cabin> g_cabins;

float WrapAngle(float a) {
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

// The texels of the car's artwork as the game has it right now, its repaint
// included: read back from the device texture the sprite pass made.
bool ReadArt(IDirect3DTexture9* art, std::vector<uint32_t>* px, int* w, int* h) {
    D3DSURFACE_DESC desc;
    if (FAILED(art->GetLevelDesc(0, &desc)) || desc.Format != D3DFMT_A8R8G8B8) return false;
    if (desc.Width < 4 || desc.Height < 4 || desc.Width > 256 || desc.Height > 256) return false;
    *w = static_cast<int>(desc.Width);
    *h = static_cast<int>(desc.Height);
    px->assign(static_cast<size_t>(*w) * *h, 0);
    D3DLOCKED_RECT locked;
    if (FAILED(art->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) return false;
    for (int y = 0; y < *h; ++y) {
        memcpy(&(*px)[static_cast<size_t>(y) * *w], static_cast<const uint8_t*>(locked.pBits) + y * locked.Pitch,
               static_cast<size_t>(*w) * 4);
    }
    art->UnlockRect(0);
    return true;
}

// The atlas: the sprite scaled up on top, then the side band, then the blocks.
struct Atlas {
    int w = 0, h = 0;
    std::vector<uint32_t> px;
    int spriteH = 0;   // rows the scaled sprite takes
    void Put(int x, int y, Rgb c) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        px[static_cast<size_t>(y) * w + x] = Pack(c);
    }
};

bool MeasureSprite(const std::vector<uint32_t>& px, int w, int h, int sprite, Measure* m) {
    m->w = w; m->h = h;
    m->halfW.assign(h, 0.0f);
    m->rowPaint.assign(h, Rgb{128, 128, 128});
    int top = -1, bottom = -1;
    const float cx = 0.5f * w;
    std::vector<float> lum;
    for (int y = 0; y < h; ++y) {
        int x0 = -1, x1 = -1;
        for (int x = 0; x < w; ++x) {
            if ((px[static_cast<size_t>(y) * w + x] >> 24) < 128) continue;
            if (x0 < 0) x0 = x;
            x1 = x;
        }
        if (x0 < 0) continue;
        if (top < 0) top = y;
        bottom = y;
        // Half-width about the canvas centre, which is what the game turns the sprite about.
        m->halfW[y] = (std::max)(cx - x0, x1 + 1 - cx);
    }
    if (top < 0 || bottom - top < 6) return false;
    m->top = top; m->bottom = bottom;
    const gta2::CarInfo* info = nullptr;
    const auto found = g_info.find(sprite);
    if (found != g_info.end()) info = &found->second;
    m->hasInfo = info != nullptr;
    // An open door sticks out of the outline: the body is no wider than CARI says.
    float cap = 1e9f;
    if (info && info->width > 4) cap = 0.5f * info->width + 1.0f;
    // Median of five, then the cap.
    std::vector<float> smooth(h, 0.0f);
    for (int y = top; y <= bottom; ++y) {
        float v[5];
        int n = 0;
        for (int k = -2; k <= 2; ++k) {
            const int yy = y + k;
            if (yy < top || yy > bottom) continue;
            v[n++] = m->halfW[yy];
        }
        std::sort(v, v + n);
        smooth[y] = (std::min)(v[n / 2], cap);
    }
    m->halfW = smooth;
    m->maxHalfW = 0.0f;
    for (int y = top; y <= bottom; ++y) m->maxHalfW = (std::max)(m->maxHalfW, m->halfW[y]);
    if (m->maxHalfW < 2.0f) return false;

    const float cy = 0.5f * h;
    const float len = static_cast<float>(bottom - top + 1);
    if (info) {
        m->cabinFront = cy + info->frontWindow;
        m->cabinRear = cy + info->rearWindow;
        m->wheelFront = cy + info->frontWheel;
        m->wheelRear = cy + info->rearWheel;
        m->doors = info->doors;
    } else {
        m->cabinFront = top + 0.72f * len;
        m->cabinRear = top + 0.30f * len;
        m->wheelFront = top + 0.80f * len;
        m->wheelRear = top + 0.20f * len;
    }
    m->cabinFront = (std::max)(static_cast<float>(top) + 2.0f, (std::min)(static_cast<float>(bottom) - 1.0f, m->cabinFront));
    m->cabinRear = (std::max)(static_cast<float>(top) + 1.0f, (std::min)(m->cabinFront - 2.0f, m->cabinRear));
    m->wheelFront = (std::max)(static_cast<float>(top) + 3.0f, (std::min)(static_cast<float>(bottom) - 3.0f, m->wheelFront));
    m->wheelRear = (std::max)(static_cast<float>(top) + 3.0f, (std::min)(m->wheelFront - 4.0f, m->wheelRear));

    // Paint: per row, the mean of the brighter half of the opaque texels (the
    // lit metal, not the outline or the glass); the car's paint overall from the
    // hood and trunk rows, which have no glass in them.
    Rgb sum{0, 0, 0};
    float count = 0.0f;
    for (int y = top; y <= bottom; ++y) {
        std::vector<std::pair<float, Rgb>> row;
        for (int x = 0; x < w; ++x) {
            const uint32_t c = px[static_cast<size_t>(y) * w + x];
            if ((c >> 24) < 128) continue;
            const Rgb rgb = Unpack(c);
            row.push_back({Luma(rgb), rgb});
        }
        if (row.empty()) continue;
        std::sort(row.begin(), row.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        Rgb s{0, 0, 0};
        int n = 0;
        for (size_t i = row.size() / 2; i < row.size(); ++i) { s.r += row[i].second.r; s.g += row[i].second.g; s.b += row[i].second.b; ++n; }
        if (n) m->rowPaint[y] = Scale(s, 1.0f / n);
        const bool deck = y > m->cabinFront + 1 || y < m->cabinRear - 1;
        if (deck && n) { sum.r += m->rowPaint[y].r; sum.g += m->rowPaint[y].g; sum.b += m->rowPaint[y].b; count += 1.0f; }
    }
    if (count > 0.0f) m->paint = Scale(sum, 1.0f / count);
    else {
        Rgb s{0, 0, 0}; int n = 0;
        for (int y = top; y <= bottom; ++y) { s.r += m->rowPaint[y].r; s.g += m->rowPaint[y].g; s.b += m->rowPaint[y].b; ++n; }
        if (n) m->paint = Scale(s, 1.0f / n);
    }
    // Smooth the row paint a little so the side does not stripe with the artwork's rows.
    std::vector<Rgb> rp = m->rowPaint;
    for (int y = top; y <= bottom; ++y) {
        Rgb s{0, 0, 0}; int n = 0;
        for (int k = -2; k <= 2; ++k) {
            const int yy = y + k;
            if (yy < top || yy > bottom) continue;
            s.r += m->rowPaint[yy].r; s.g += m->rowPaint[yy].g; s.b += m->rowPaint[yy].b; ++n;
        }
        rp[y] = Scale(s, 1.0f / n);
    }
    m->rowPaint = rp;
    return true;
}

// The texture: the sprite scaled up and edge-extended on top; under it the side
// band (glass over paint, by column along the length) and the small blocks for
// the nose, the tail, the rubber and the hubs.
IDirect3DTexture9* MakeAtlas(IDirect3DDevice9* device, const std::vector<uint32_t>& px, const Measure& m, Atlas* out) {
    const int sw = m.w * kAtlasScale, sh = m.h * kAtlasScale;
    out->w = (std::max)(sw, 192);
    out->h = sh + kBandRows + kBlockRows;
    out->spriteH = sh;
    out->px.assign(static_cast<size_t>(out->w) * out->h, 0xFF000000u);
    // The sprite, 4x.
    std::vector<uint32_t> big = Scale2x(Scale2x(px, m.w, m.h), m.w * 2, m.h * 2);
    ExtendEdges(&big, sw, sh, 12);
    // A light blur, so the enlarged pixels read as paint rather than tiles.
    {
        std::vector<uint32_t> soft(big.size());
        for (int y = 0; y < sh; ++y) {
            for (int x = 0; x < sw; ++x) {
                float r = 0, g = 0, b = 0, wsum = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int xx = (std::max)(0, (std::min)(sw - 1, x + dx)), yy = (std::max)(0, (std::min)(sh - 1, y + dy));
                        const uint32_t c = big[static_cast<size_t>(yy) * sw + xx];
                        if (!(c >> 24)) continue;
                        const float wgt = (dx == 0 && dy == 0) ? 2.0f : 1.0f;
                        const Rgb k = Unpack(c);
                        r += k.r * wgt; g += k.g * wgt; b += k.b * wgt; wsum += wgt;
                    }
                }
                const uint32_t c = big[static_cast<size_t>(y) * sw + x];
                soft[static_cast<size_t>(y) * sw + x] = (wsum > 0.0f && (c >> 24)) ? Pack(Rgb{r / wsum, g / wsum, b / wsum}) : c;
            }
        }
        big.swap(soft);
    }
    for (int y = 0; y < sh; ++y) {
        for (int x = 0; x < sw; ++x) {
            const uint32_t c = big[static_cast<size_t>(y) * sw + x];
            out->px[static_cast<size_t>(y) * out->w + x] = c | 0xFF000000u;
        }
    }
    // The band: column X runs tail -> nose along the car; rows 0..15 are the
    // glass zone, rows 16..31 the lower side down to the sill.
    const float len = static_cast<float>(m.bottom - m.top + 1);
    const float cabinLen = m.cabinFront - m.cabinRear;
    const Rgb glassTop{92, 112, 130}, glassBottom{26, 32, 40};
    for (int X = 0; X < out->w; ++X) {
        const float f = (X + 0.5f) / out->w;
        const float row = m.top + f * len;
        const int ry = (std::max)(m.top, (std::min)(m.bottom, static_cast<int>(row)));
        Rgb paint = Mix(m.rowPaint[ry], m.paint, 0.35f);
        const bool cabin = row >= m.cabinRear && row <= m.cabinFront;
        // Pillars: at both ends of the glass, and in the middle of a four-door.
        const float pillar = (std::max)(1.2f, 0.06f * cabinLen);
        bool isPillar = cabin && (row - m.cabinRear < pillar || m.cabinFront - row < pillar);
        if (cabin && m.doors >= 4 && std::fabs(row - 0.5f * (m.cabinRear + m.cabinFront)) < 0.5f * pillar) isPillar = true;
        for (int r = 0; r < kBandRows; ++r) {
            Rgb c;
            if (r < 16) {
                if (cabin && !isPillar) {
                    const float t = r / 15.0f;
                    c = Mix(glassTop, glassBottom, t);
                    // A pale reflection band near the top, as glass has.
                    if (r >= 2 && r <= 5) c = Mix(c, Rgb{200, 215, 230}, 0.25f);
                } else {
                    c = Scale(paint, isPillar ? 0.55f : 1.0f);
                }
            } else if (r < 20) {
                c = Scale(paint, 1.10f);   // the shoulder catches the sky
            } else if (r < 28) {
                c = paint;
            } else {
                c = Scale(paint, 0.55f);   // the sill, in shadow
            }
            out->Put(X, sh + r, c);
        }
    }
    // The blocks: nose [0,64), tail [64,128), rubber [128,144), hub [144,160).
    const int by = sh + kBandRows;
    for (int y = 0; y < kBlockRows; ++y) {
        for (int x = 0; x < 64; ++x) {
            Rgb c = Scale(m.paint, y < 3 ? 1.05f : 1.0f);
            const bool side = x < 6 || x >= 58;
            if (y >= 7 && y <= 11 && ((x >= 7 && x <= 17) || (x >= 46 && x <= 56))) c = Rgb{255, 248, 215};   // headlamps
            else if (y >= 9 && y <= 12 && x >= 22 && x <= 41) c = Scale(m.paint, 0.28f);               // grille
            else if (y >= 13) c = Scale(m.paint, side ? 0.6f : 0.5f);                                    // bumper
            out->Put(x, by + y, c);
            Rgb t = Scale(m.paint, y < 3 ? 1.05f : 1.0f);
            if (y >= 7 && y <= 11 && ((x >= 5 && x <= 16) || (x >= 47 && x <= 58))) t = Rgb{205, 28, 24};   // tail lamps
            else if (y >= 8 && y <= 12 && x >= 26 && x <= 37) t = Rgb{225, 225, 212};                      // the plate
            else if (y >= 13) t = Scale(m.paint, 0.5f);
            out->Put(64 + x, by + y, t);
        }
        for (int x = 0; x < 16; ++x) {
            const float n = 0.9f + 0.1f * static_cast<float>((x * 7 + y * 13) % 5) / 4.0f;
            out->Put(128 + x, by + y, Scale(Rgb{30, 30, 32}, n));
            const float dx = x - 7.5f, dy = y - 7.5f;
            const float d = std::sqrt(dx * dx + dy * dy);
            Rgb hub = d > 7.2f ? Rgb{24, 24, 26} : (d > 5.0f ? Rgb{150, 152, 158} : (d > 1.5f ? Rgb{118, 120, 126} : Rgb{60, 60, 64}));
            out->Put(144 + x, by + y, hub);
        }
    }
    IDirect3DTexture9* tex = nullptr;
    if (FAILED(device->CreateTexture(out->w, out->h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    D3DLOCKED_RECT locked;
    if (FAILED(tex->LockRect(0, &locked, nullptr, 0))) { tex->Release(); return nullptr; }
    for (int y = 0; y < out->h; ++y) {
        memcpy(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch, &out->px[static_cast<size_t>(y) * out->w],
               static_cast<size_t>(out->w) * 4);
    }
    tex->UnlockRect(0);
    return tex;
}

// Builds the body and the wheel in car space: x across (right positive), y up,
// z along the length toward the nose, in tiles; the origin under the sprite's
// centre on the ground. `scale` is tiles per sprite pixel.
void BuildMesh(const Measure& m, const Atlas& atlas, float scale, Built* b) {
    const float W = 2.0f * m.maxHalfW * scale;                          // the body's width in tiles
    const float cy = 0.5f * m.h;
    const float zTail = (m.top - cy) * scale, zNose = (m.bottom + 1 - cy) * scale;
    const float L = zNose - zTail;
    const float zCabinRear = (m.cabinRear - cy) * scale, zCabinFront = (m.cabinFront - cy) * scale;
    const float cabinFrac = (zCabinFront - zCabinRear) / L;
    // Proportions. A sedan's roof is four fifths of its width up; a van or bus
    // is taller, with a nearly upright windscreen.
    const float tall = Smooth((cabinFrac - 0.58f) / 0.25f);
    const float hSill = 0.14f * W, hBelt = 0.38f * W;
    const float hTail = 0.42f * W, hTrunk = 0.49f * W, hHood = 0.51f * W, hNose = 0.40f * W;
    const float hRoof = W * (0.76f + 0.50f * tall);
    const float rakeFront = L * (0.15f - 0.10f * tall), rakeRear = L * (0.11f - 0.07f * tall);
    // The roof texture: the sprite's u runs across the canvas, v down it (tail to nose).
    const float atlasW = static_cast<float>(atlas.w), atlasH = static_cast<float>(atlas.h);
    const float spriteU = static_cast<float>(m.w * kAtlasScale) / atlasW;   // the sprite's share of the atlas width
    const float spriteV = static_cast<float>(atlas.spriteH) / atlasH;
    auto topUv = [&](float x, float z, float* u, float* v) {
        *u = (0.5f + x / (m.w * scale)) * spriteU;
        *v = ((z / scale + cy) / m.h) * spriteV;
    };
    const float bandV0 = static_cast<float>(atlas.spriteH) / atlasH;
    const float bandV1 = static_cast<float>(atlas.spriteH + kBandRows) / atlasH;
    auto bandUv = [&](float z, float heightFrac /* 0 sill .. 1 roof */, float* u, float* v) {
        *u = (z - zTail) / L;
        // Rows 16..31 (the lower side) are heights 0..0.5 of the way up; rows 0..15 the glass, 0.5..1.
        *v = bandV0 + (bandV1 - bandV0) * (1.0f - heightFrac) ;
    };
    const float blockV0 = static_cast<float>(atlas.spriteH + kBandRows) / atlasH;
    const float blockV1 = static_cast<float>(atlas.spriteH + kBandRows + kBlockRows) / atlasH;

    auto halfWidthAt = [&](float z) {
        const float row = z / scale + cy;
        const float fy = row - 0.5f;
        int y0 = static_cast<int>(std::floor(fy));
        const float t = fy - y0;
        y0 = (std::max)(m.top, (std::min)(m.bottom, y0));
        const int y1 = (std::max)(m.top, (std::min)(m.bottom, y0 + 1));
        float hw = m.halfW[y0] * (1 - t) + m.halfW[y1] * t;
        return (std::max)(hw * scale, 0.08f * W);
    };
    auto deckHeight = [&](float z) {
        if (z <= zCabinRear) {
            const float t = (z - zTail) / (std::max)(zCabinRear - zTail, 1e-3f);
            return hTail + (hTrunk - hTail) * Smooth(t);
        }
        if (z >= zCabinFront) {
            const float t = (z - zCabinFront) / (std::max)(zNose - zCabinFront, 1e-3f);
            return hHood + (hNose - hHood) * t * t;
        }
        return hHood + (hTrunk - hHood) * (zCabinFront - z) / (std::max)(zCabinFront - zCabinRear, 1e-3f);
    };
    auto roofHeight = [&](float z, float deck) {
        if (z < zCabinRear || z > zCabinFront) return deck;
        float t = 1.0f;
        if (z > zCabinFront - rakeFront) t = (std::min)(t, (zCabinFront - z) / rakeFront);
        if (z < zCabinRear + rakeRear) t = (std::min)(t, (z - zCabinRear) / rakeRear);
        return deck + (hRoof - deck) * Smooth(t);
    };

    // Four strips a side, each its own vertices so the creases between them stay.
    struct Pt { float x, y; };
    enum Family { kSide, kDeck, kGlass, kRoof, kFamilies };
    const int counts[kFamilies] = {5, 2, 2, 3};
    b->verts.clear();
    b->indices.clear();
    // verts laid out: [side][family][station][k]
    int base[2][kFamilies];
    for (int side = 0; side < 2; ++side) {
        const float sx = side == 0 ? -1.0f : 1.0f;
        for (int fam = 0; fam < kFamilies; ++fam) {
            base[side][fam] = static_cast<int>(b->verts.size());
            for (int i = 0; i <= kStations; ++i) {
                const float z = zTail + (zNose - zTail) * i / kStations;
                const float hw = halfWidthAt(z);
                const float deck = deckHeight(z), roof = roofHeight(z, deck);
                const bool cabin = z >= zCabinRear && z <= zCabinFront;
                Pt pts[5];
                int n = counts[fam];
                switch (fam) {
                    case kSide:
                        pts[0] = {hw * 0.95f, hSill};
                        pts[1] = {hw * 1.00f, hSill + 0.45f * (hBelt - hSill)};
                        pts[2] = {hw * 1.00f, hBelt};
                        pts[3] = {hw * 0.985f, deck - 0.05f * W};
                        pts[4] = {hw * 0.94f, deck};
                        break;
                    case kDeck:
                        pts[0] = {hw * 0.94f, deck};
                        pts[1] = {hw * 0.86f, deck + 0.012f * W};
                        break;
                    case kGlass:
                        pts[0] = {hw * 0.86f, deck + 0.012f * W};
                        pts[1] = {hw * (cabin ? 0.78f : 0.84f), (std::max)(roof - 0.015f * W, deck + 0.012f * W)};
                        break;
                    default:
                        pts[0] = {hw * (cabin ? 0.78f : 0.84f), (std::max)(roof - 0.015f * W, deck + 0.012f * W)};
                        pts[1] = {hw * (cabin ? 0.66f : 0.60f), roof + (cabin ? 0.0f : 0.012f * W)};
                        pts[2] = {0.0f, roof + 0.014f * W};
                        break;
                }
                for (int k = 0; k < n; ++k) {
                    CarBodyVertex v = {};
                    v.x = sx * pts[k].x;
                    v.y = pts[k].y;
                    v.z = z;
                    if (fam == kSide) {
                        bandUv(z, 0.5f * static_cast<float>(k) / (n - 1), &v.u, &v.v);
                    } else if (fam == kGlass) {
                        bandUv(z, k == 0 ? 0.52f : 0.98f, &v.u, &v.v);
                    } else {
                        topUv(v.x, z, &v.u, &v.v);
                    }
                    b->verts.push_back(v);
                }
            }
        }
    }
    auto quad = [&](int a, int bq, int c, int d) {
        b->indices.insert(b->indices.end(), {static_cast<uint16_t>(a), static_cast<uint16_t>(bq), static_cast<uint16_t>(c),
                                             static_cast<uint16_t>(a), static_cast<uint16_t>(c), static_cast<uint16_t>(d)});
    };
    for (int side = 0; side < 2; ++side) {
        for (int fam = 0; fam < kFamilies; ++fam) {
            const int n = counts[fam];
            for (int i = 0; i < kStations; ++i) {
                for (int k = 0; k + 1 < n; ++k) {
                    const int p00 = base[side][fam] + i * n + k, p01 = p00 + 1;
                    const int p10 = p00 + n, p11 = p10 + 1;
                    quad(p00, p10, p11, p01);
                }
            }
        }
    }
    // Normals from the faces, averaged per vertex, turned outward.
    std::vector<float> acc(b->verts.size() * 3, 0.0f);
    for (size_t t = 0; t + 2 < b->indices.size(); t += 3) {
        const CarBodyVertex &p = b->verts[b->indices[t]], &q = b->verts[b->indices[t + 1]], &r = b->verts[b->indices[t + 2]];
        const float ax = q.x - p.x, ay = q.y - p.y, az = q.z - p.z;
        const float bx = r.x - p.x, byy = r.y - p.y, bz = r.z - p.z;
        float nx = ay * bz - az * byy, ny = az * bx - ax * bz, nz = ax * byy - ay * bx;
        // Outward: away from the body's axis at this height.
        const float mx = (p.x + q.x + r.x) / 3.0f, my = (p.y + q.y + r.y) / 3.0f;
        if (nx * mx + ny * (my - 0.5f * hBelt) < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
        for (int k = 0; k < 3; ++k) {
            const uint16_t idx = b->indices[t + k];
            acc[idx * 3] += nx; acc[idx * 3 + 1] += ny; acc[idx * 3 + 2] += nz;
        }
    }
    for (size_t i = 0; i < b->verts.size(); ++i) {
        float nx = acc[i * 3], ny = acc[i * 3 + 1], nz = acc[i * 3 + 2];
        const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len < 1e-9f) { nx = 0; ny = 1; nz = 0; } else { nx /= len; ny /= len; nz /= len; }
        b->verts[i].nx = nx; b->verts[i].ny = ny; b->verts[i].nz = nz;
    }
    // The caps: a fan over the end ring, textured from the nose or tail block.
    for (int end = 0; end < 2; ++end) {
        const int station = end == 0 ? 0 : kStations;
        const float z = end == 0 ? zTail : zNose;
        const float hw = halfWidthAt(z);
        const float deck = deckHeight(z), roof = roofHeight(z, deck);
        const float topY = (std::max)(roof, deck) + 0.02f * W;
        const float u0 = (end == 0 ? 64.0f : 0.0f) / atlasW, u1 = (end == 0 ? 128.0f : 64.0f) / atlasW;
        auto capUv = [&](float x, float y, float* u, float* v) {
            *u = u0 + (u1 - u0) * (0.5f + 0.5f * x / (std::max)(hw, 1e-3f));
            *v = blockV0 + (blockV1 - blockV0) * (1.0f - (y - hSill) / (std::max)(topY - hSill, 1e-3f));
        };
        std::vector<int> ring;   // indices into the new cap vertices
        const int centre = static_cast<int>(b->verts.size());
        {
            CarBodyVertex c = {};
            c.x = 0; c.y = 0.5f * (hSill + deck); c.z = z;
            c.nz = end == 0 ? -1.0f : 1.0f;
            capUv(c.x, c.y, &c.u, &c.v);
            b->verts.push_back(c);
        }
        // Left side up, over the top, right side down.
        auto add = [&](int side, int fam, int k) {
            const CarBodyVertex& src = b->verts[base[side][fam] + station * counts[fam] + k];
            CarBodyVertex v = src;
            v.nx = 0; v.ny = 0; v.nz = end == 0 ? -1.0f : 1.0f;
            capUv(v.x, v.y, &v.u, &v.v);
            ring.push_back(static_cast<int>(b->verts.size()));
            b->verts.push_back(v);
        };
        for (int fam = 0; fam < kFamilies; ++fam) for (int k = 0; k < counts[fam]; ++k) add(0, fam, k);
        for (int fam = kFamilies - 1; fam >= 0; --fam) for (int k = counts[fam] - 1; k >= 0; --k) add(1, fam, k);
        for (size_t i = 0; i + 1 < ring.size(); ++i) {
            b->indices.insert(b->indices.end(), {static_cast<uint16_t>(centre), static_cast<uint16_t>(ring[i]),
                                                 static_cast<uint16_t>(ring[i + 1])});
        }
    }

    // The wheel, at its own origin, axle along x.
    const float r = (std::min)(0.21f * W, 0.09f * L);
    const float ww = 0.13f * W;
    b->wheelVerts.clear();
    b->wheelIndices.clear();
    const float ru0 = 128.0f / atlasW, ru1 = 144.0f / atlasW, hu0 = 144.0f / atlasW, hu1 = 160.0f / atlasW;
    for (int s = 0; s <= kWheelSegments; ++s) {
        const float a = 2.0f * kPi * s / kWheelSegments;
        const float cy_ = std::cos(a), sz_ = std::sin(a);
        for (int side = 0; side < 2; ++side) {
            CarBodyVertex v = {};
            v.x = side == 0 ? -0.5f * ww : 0.5f * ww;
            v.y = r * cy_;
            v.z = r * sz_;
            v.nx = 0; v.ny = cy_; v.nz = sz_;
            v.u = ru0 + (ru1 - ru0) * (static_cast<float>(s) / kWheelSegments) * 3.0f;
            v.u = ru0 + std::fmod(v.u - ru0, ru1 - ru0);
            v.v = blockV0 + (blockV1 - blockV0) * (side == 0 ? 0.05f : 0.95f);
            b->wheelVerts.push_back(v);
        }
    }
    for (int s = 0; s < kWheelSegments; ++s) {
        const int p = s * 2;
        b->wheelIndices.insert(b->wheelIndices.end(), {static_cast<uint16_t>(p), static_cast<uint16_t>(p + 2), static_cast<uint16_t>(p + 3),
                                                       static_cast<uint16_t>(p), static_cast<uint16_t>(p + 3), static_cast<uint16_t>(p + 1)});
    }
    for (int side = 0; side < 2; ++side) {
        const int centre = static_cast<int>(b->wheelVerts.size());
        const float x = side == 0 ? -0.5f * ww : 0.5f * ww;
        CarBodyVertex c = {};
        c.x = x; c.nx = side == 0 ? -1.0f : 1.0f;
        c.u = 0.5f * (hu0 + hu1); c.v = 0.5f * (blockV0 + blockV1);
        b->wheelVerts.push_back(c);
        for (int s = 0; s <= kWheelSegments; ++s) {
            const float a = 2.0f * kPi * s / kWheelSegments;
            CarBodyVertex v = {};
            v.x = x; v.y = r * std::cos(a); v.z = r * std::sin(a);
            v.nx = c.nx;
            v.u = hu0 + (hu1 - hu0) * (0.5f + 0.5f * std::cos(a));
            v.v = blockV0 + (blockV1 - blockV0) * (0.5f + 0.5f * std::sin(a));
            b->wheelVerts.push_back(v);
        }
        for (int s = 0; s < kWheelSegments; ++s) {
            b->wheelIndices.insert(b->wheelIndices.end(), {static_cast<uint16_t>(centre), static_cast<uint16_t>(centre + 1 + s),
                                                           static_cast<uint16_t>(centre + 2 + s)});
        }
    }
    b->deckY = hHood;
    b->roofY = hRoof;
    b->wheelZ[0] = (m.wheelFront - cy) * scale;
    b->wheelZ[1] = (m.wheelRear - cy) * scale;
    b->wheelX = (std::max)(halfWidthAt(b->wheelZ[0]), halfWidthAt(b->wheelZ[1])) * 0.96f - 0.5f * ww;
    b->wheelY = r;
    b->wheelbase = (std::max)(b->wheelZ[0] - b->wheelZ[1], 0.05f);
}

// Tiles per sprite pixel, from the quad: its length along v over the texture's rows.
float PixelScale(const CarBodyUse& use, int h) {
    const CarBodyVertex* c = use.local;
    const float ax = c[1].x - c[0].x, az = c[1].z - c[0].z, bx = c[3].x - c[0].x, bz = c[3].z - c[0].z;
    const float dvA = c[1].v - c[0].v, dvB = c[3].v - c[0].v;
    const bool lengthIsB = std::fabs(dvB) >= std::fabs(dvA);
    const float edge = lengthIsB ? std::sqrt(bx * bx + bz * bz) : std::sqrt(ax * ax + az * az);
    const float dv = std::fabs(lengthIsB ? dvB : dvA);
    return dv > 1e-6f && h > 0 ? edge / dv / static_cast<float>(h) : 1.0f / 64.0f;
}

// The car's measurements (paint, footprint) from its artwork: what both a
// hand-made model and a body built here need. The body mesh itself is built
// only when it is going to be drawn (BodyMesh).

// From the driver's seat the model is a solid hull: on the plain D3D9 path two
// user clip planes cut it just below the eye and at the windscreen. RTX Remix
// ignores user clip planes (the hull then shows as a bright cut surface across
// the view), so under Remix the same cut is made on the CPU: a copy of the model
// keeping only the triangles whose centre, in the car's own frame after the fit,
// lies below `yCut` and ahead of `zCut` (the hood, the fenders, the cowl). Each
// (model, cuts) pair is built once and registered with the store.
struct HoodKey {
    const Model* model; int yq, zq;
    bool operator<(const HoodKey& o) const { return std::tie(model, yq, zq) < std::tie(o.model, o.yq, o.zq); }
};
std::map<HoodKey, const Model*> g_hoods;

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b);   // defined below
inline gta2::Vec3 PointBy(const gta2::Mat4& m, float x, float y, float z) {
    return {x * m.m[0][0] + y * m.m[1][0] + z * m.m[2][0] + m.m[3][0],
            x * m.m[0][1] + y * m.m[1][1] + z * m.m[2][1] + m.m[3][1],
            x * m.m[0][2] + y * m.m[1][2] + z * m.m[2][2] + m.m[3][2]};
}

const Model* HoodModelFor(const Model& model, const gta2::Mat4& fit, float yCut, float zCut) {
    // 0.04-block steps: the eye bobs and leans a little, the cache stays small.
    const HoodKey key{&model, static_cast<int>(std::floor(yCut * 25.0f)), static_cast<int>(std::floor(zCut * 25.0f))};
    auto it = g_hoods.find(key);
    if (it != g_hoods.end()) return it->second;
    if (g_hoods.size() > 96) g_hoods.clear();   // the store keeps the models; only the lookup is dropped
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model hood;
    hood.name = model.name + "#hood";
    hood.nodes = model.nodes;
    hood.forward = model.forward;
    hood.boundsMin = model.boundsMin; hood.boundsMax = model.boundsMax;
    for (int k = 0; k < 3; ++k) hood.paintRgb[k] = model.paintRgb[k];
    hood.splitPaint = model.splitPaint;
    hood.meshes.resize(model.meshes.size());
    size_t kept = 0, all = 0;
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& dst = hood.meshes[static_cast<size_t>(mi)];
        dst.vertices = src.vertices;
        dst.texture = src.texture;
        dst.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        // A vertex with its signed distances inside the two cuts: below the eye
        // plane (yCut - y) and ahead of the windscreen plane (z - zCut); the mesh
        // is clipped against both, so the hood's edge is the plane itself rather
        // than a stair of dropped triangles.
        struct CV { ModelVertex v; float dy, dz; };
        auto lerpV = [](const ModelVertex& a, const ModelVertex& b, float t) {
            ModelVertex o;
            o.x = a.x + (b.x - a.x) * t; o.y = a.y + (b.y - a.y) * t; o.z = a.z + (b.z - a.z) * t;
            o.nx = a.nx + (b.nx - a.nx) * t; o.ny = a.ny + (b.ny - a.ny) * t; o.nz = a.nz + (b.nz - a.nz) * t;
            o.u = a.u + (b.u - a.u) * t; o.v = a.v + (b.v - a.v) * t;
            return o;
        };
        // Sutherland-Hodgman against one plane: keep where d >= 0.
        auto clipPoly = [&](std::vector<CV>& poly, int which) {
            std::vector<CV> out;
            const size_t n = poly.size();
            for (size_t i = 0; i < n; ++i) {
                const CV& a = poly[i];
                const CV& b = poly[(i + 1) % n];
                const float da = which == 0 ? a.dy : a.dz, db = which == 0 ? b.dy : b.dz;
                if (da >= 0.0f) out.push_back(a);
                if ((da >= 0.0f) != (db >= 0.0f)) {
                    const float t = da / (da - db);
                    CV c;
                    c.v = lerpV(a.v, b.v, t);
                    c.dy = a.dy + (b.dy - a.dy) * t;
                    c.dz = a.dz + (b.dz - a.dz) * t;
                    out.push_back(c);
                }
            }
            poly.swap(out);
        };
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            ++all;
            gta2::Vec3 q[3];
            std::vector<CV> poly(3);
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                poly[static_cast<size_t>(c)] = {v, yCut - q[c].y, q[c].z - zCut};
            }
            // Only faces that lie flat enough to be the hood's top (or its underside,
            // hidden behind it): the engine bay's inner walls and the fenders' sides
            // are what the eye would otherwise see from inside the hull.
            const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
            const float nl = std::sqrt(gta2::Dot(nrm, nrm));
            const bool flat = nl > 1e-9f && std::fabs(nrm.y) / nl > 0.35f;
            if (!flat) continue;
            const bool allIn = poly[0].dy >= 0 && poly[1].dy >= 0 && poly[2].dy >= 0 && poly[0].dz >= 0 && poly[1].dz >= 0 && poly[2].dz >= 0;
            if (allIn) {
                dst.indices.push_back(src.indices[t]);
                dst.indices.push_back(src.indices[t + 1]);
                dst.indices.push_back(src.indices[t + 2]);
                ++kept;
                continue;
            }
            clipPoly(poly, 0);
            if (poly.size() >= 3) clipPoly(poly, 1);
            if (poly.size() < 3) continue;
            // The clipped polygon as a fan of new vertices.
            const uint32_t base = static_cast<uint32_t>(dst.vertices.size());
            for (const CV& c : poly) dst.vertices.push_back(c.v);
            for (size_t i = 1; i + 1 < poly.size(); ++i) {
                dst.indices.push_back(base);
                dst.indices.push_back(base + static_cast<uint32_t>(i));
                dst.indices.push_back(base + static_cast<uint32_t>(i + 1));
            }
            ++kept;
        }
    }
    const Model* stored = ModelRegisterDerived(std::move(hood));
    g_hoods[key] = stored;
    Log("car bodies: hood copy of %s for the driver's seat: %zu of %zu triangles (y < %.2f, z > %.2f)", model.name.c_str(), kept, all, yCut, zCut);
    return stored;
}

// The driver's cab of a tall or long model (truck, bus, van, fire truck), in the
// car's own frame after the fit (blocks; y up from the road, +z the nose): where
// the hood ends and the windscreen starts, the hood's top (the deck) and the
// cab's roof over the driver. A sedan's numbers come from its roof alone (deck
// 0.62 of it, the windscreen from CARI); a truck's roof is often a box body or
// roof gear behind the cab, and CARI's windscreen line on those long sprites
// lies inside that body, so the eye sat behind the fire truck's ladder (run
// a33_fire2 ft_drive_06). The model's own side profile says where the cab is:
// the height of the middle band of the body in 32 slices from tail to nose; the
// hood is the run of slices from the nose that stay within an eighth of the
// height of the nose; the windscreen is where that run ends. A flat front (bus,
// cab-over truck, train) has no hood: the windscreen is at the nose and the
// deck a little over half the cab's height. Built once per model and fit.
struct CabShape {
    bool valid = false;
    float length = 0, height = 0, deck = 0, roof = 0, windscreen = 0;
};
struct CabKey {
    const Model* model; int xq, yq, zq;
    bool operator<(const CabKey& o) const { return std::tie(model, xq, yq, zq) < std::tie(o.model, o.xq, o.yq, o.zq); }
};
std::map<CabKey, CabShape> g_cabShapes;

CabShape CabShapeFor(const Model& model, const gta2::Mat4& fit, int modelNumber) {
    const CabKey key{&model, static_cast<int>(std::lround(std::fabs(fit.m[0][0] + fit.m[2][0]) * 100.0f)),
                     static_cast<int>(std::lround(fit.m[1][1] * 100.0f)),
                     static_cast<int>(std::lround(std::fabs(fit.m[2][2] + fit.m[0][2]) * 100.0f))};
    auto it = g_cabShapes.find(key);
    if (it != g_cabShapes.end()) return it->second;
    if (g_cabShapes.size() > 256) g_cabShapes.clear();
    CabShape cab;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f, minZ = 1e9f, maxZ = -1e9f;
    auto each = [&](auto&& fn) {
        for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
            const int mi = model.nodes[n].mesh;
            if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
            const gta2::Mat4 toCar = Mul(worlds[n], fit);
            for (const ModelVertex& v : model.meshes[static_cast<size_t>(mi)].vertices) fn(PointBy(toCar, v.x, v.y, v.z));
        }
    };
    each([&](const gta2::Vec3& q) {
        minX = (std::min)(minX, q.x); maxX = (std::max)(maxX, q.x);
        minY = (std::min)(minY, q.y); maxY = (std::max)(maxY, q.y);
        minZ = (std::min)(minZ, q.z); maxZ = (std::max)(maxZ, q.z);
    });
    const float L = maxZ - minZ, H = maxY - minY, W = maxX - minX, cx = 0.5f * (minX + maxX);
    if (!(L > 0.05f && H > 0.05f && W > 0.05f)) {
        g_cabShapes[key] = cab;
        return cab;
    }
    constexpr int kSlices = 32;
    float h[kSlices];
    for (float& v : h) v = -1.0f;
    each([&](const gta2::Vec3& q) {
        if (std::fabs(q.x - cx) > 0.35f * W) return;
        const int b = (std::min)(kSlices - 1, (std::max)(0, static_cast<int>((q.z - minZ) / L * kSlices)));
        h[b] = (std::max)(h[b], q.y - minY);
    });
    for (int b = 1; b < kSlices; ++b) if (h[b] < 0.0f) h[b] = h[b - 1];
    for (int b = kSlices - 2; b >= 0; --b) if (h[b] < 0.0f) h[b] = h[b + 1];
    const float slice = L / kSlices;
    const float nose = (std::max)(h[kSlices - 1], h[kSlices - 2]);
    int end = kSlices - 1;   // the last slice of the hood run, counting from the nose
    while (end > 0 && h[end - 1] <= nose + 0.125f * H) --end;
    const float runLength = (kSlices - end) * slice;
    const bool flat = nose >= 0.85f * H || runLength > 0.45f * L;
    cab.windscreen = flat ? maxZ - 0.06f * L : minZ + end * slice;
    float roof = 0.0f;
    for (int b = 0; b < kSlices; ++b) {
        const float z0 = minZ + b * slice, z1 = z0 + slice;
        if (z1 > cab.windscreen - 0.35f && z0 < cab.windscreen + 0.02f) roof = (std::max)(roof, h[b]);
    }
    cab.roof = roof;
    cab.deck = flat ? 0.55f * roof : nose;
    if (cab.roof < cab.deck + 0.08f) cab.roof = cab.deck + 0.08f;
    cab.length = L;
    cab.height = H;
    cab.valid = true;
    g_cabShapes[key] = cab;
    Log("car bodies: cab of model %d (%s): %.2f x %.2f x %.2f blocks, %s front, hood %.2f long at %.2f, windscreen %+.2f, cab roof %.2f",
        modelNumber, model.name.c_str(), L, W, H, flat ? "flat" : "hooded", runLength, cab.deck, cab.windscreen, cab.roof);
    return cab;
}

// Dents. The game keeps a damage byte per vehicle (+0x74: 0 fresh, rising with
// every knock, past 200 the car burns) and paints dents into the sprite; a
// model shows the same wear as a copy whose shell is pressed in by a smooth,
// low-frequency field (three octaves of value noise over the car's own frame)
// along normals smoothed across every seam, at most 2 % of the body length at
// the top step, with the normals recomputed afterwards. No vertex moves on its
// own, so nothing tears and nothing shows light through; the two paint-split
// halves share positions, so they move together. Cached per (model, step).
struct DentKey {
    const Model* model; int step;
    bool operator<(const DentKey& o) const { return std::tie(model, step) < std::tie(o.model, o.step); }
};
std::map<DentKey, const Model*> g_dents;
constexpr int kDentSteps = 4;
int DentStepFor(int damage) { return damage <= 0 ? 0 : (std::min)(kDentSteps, (damage + 32) / 64); }

uint32_t DentHash(int32_t x, int32_t y, int32_t z, uint32_t seed) {
    uint32_t h = static_cast<uint32_t>(x) * 73856093u ^ static_cast<uint32_t>(y) * 19349663u ^ static_cast<uint32_t>(z) * 83492791u ^ seed * 2654435761u;
    h ^= h >> 13; h *= 0x5bd1e995u; h ^= h >> 15;
    return h;
}
// Value noise in [0,1]: a hashed lattice, smoothstep interpolation.
float DentNoise(float x, float y, float z, uint32_t seed) {
    const float fx = std::floor(x), fy = std::floor(y), fz = std::floor(z);
    const int32_t ix = static_cast<int32_t>(fx), iy = static_cast<int32_t>(fy), iz = static_cast<int32_t>(fz);
    float tx = x - fx, ty = y - fy, tz = z - fz;
    tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty); tz = tz * tz * (3.0f - 2.0f * tz);
    auto at = [&](int dx, int dy, int dz) { return static_cast<float>(DentHash(ix + dx, iy + dy, iz + dz, seed) & 0xFFFF) / 65535.0f; };
    const float c00 = at(0, 0, 0) + (at(1, 0, 0) - at(0, 0, 0)) * tx, c10 = at(0, 1, 0) + (at(1, 1, 0) - at(0, 1, 0)) * tx;
    const float c01 = at(0, 0, 1) + (at(1, 0, 1) - at(0, 0, 1)) * tx, c11 = at(0, 1, 1) + (at(1, 1, 1) - at(0, 1, 1)) * tx;
    const float c0 = c00 + (c10 - c00) * ty, c1 = c01 + (c11 - c01) * ty;
    return c0 + (c1 - c0) * tz;
}

const Model* DentedModelFor(const Model& model, int step) {
    const DentKey key{&model, step};
    auto it = g_dents.find(key);
    if (it != g_dents.end()) return it->second;
    Model dented = model;
    dented.name = model.name + "#dent" + std::to_string(step);
    const float height = (std::max)(model.Height(), 0.05f);
    const float length = (std::max)(model.Length(), 0.05f);
    const float sill = model.boundsMin.y + 0.20f * height;
    const float amplitude = 0.02f * length * static_cast<float>(step) / static_cast<float>(kDentSteps);
    // Positions are shared by the paint-split halves and across mesh seams:
    // key every vertex by its quantised position, and smooth the normals over
    // that key before displacing, then rebuild them from the moved faces.
    struct PosKey { int32_t x, y, z; bool operator<(const PosKey& o) const { return std::tie(x, y, z) < std::tie(o.x, o.y, o.z); } };
    auto keyOf = [&](const ModelVertex& v) {
        const float q = 2000.0f / length;
        return PosKey{static_cast<int32_t>(std::lround(v.x * q)), static_cast<int32_t>(std::lround(v.y * q)), static_cast<int32_t>(std::lround(v.z * q))};
    };
    std::map<PosKey, gta2::Vec3> smooth;
    for (const ModelMesh& mesh : dented.meshes)
        for (const ModelVertex& v : mesh.vertices) {
            gta2::Vec3& n = smooth[keyOf(v)];
            n.x += v.nx; n.y += v.ny; n.z += v.nz;
        }
    for (auto& kv : smooth) {
        const float l = std::sqrt(gta2::Dot(kv.second, kv.second));
        if (l > 1e-8f) { kv.second.x /= l; kv.second.y /= l; kv.second.z /= l; }
    }
    size_t moved = 0;
    const uint32_t seed = static_cast<uint32_t>(std::hash<std::string>{}(model.name) & 0xFFFF);
    const float sx = 1.0f / (std::max)(model.Width(), 0.05f);
    for (ModelMesh& mesh : dented.meshes) {
        for (ModelVertex& v : mesh.vertices) {
            // Fade in above the sill so the sill is not a crease.
            const float wSill = (std::min)(1.0f, (std::max)(0.0f, (v.y - sill) / (0.12f * height)));
            if (wSill <= 0.0f) continue;
            const float px = v.x * sx, py = v.y / height, pz = v.z / length;   // -0.5..0.5 about the body
            float n = 0.60f * DentNoise(px * 2.6f, py * 2.0f, pz * 4.0f, seed)
                    + 0.28f * DentNoise(px * 5.2f + 3.1f, py * 4.0f, pz * 8.0f + 1.7f, seed + 1)
                    + 0.12f * DentNoise(px * 10.4f + 7.9f, py * 8.0f, pz * 16.0f + 5.3f, seed + 2);
            // Only the peaks dent: most of the shell stays as it was.
            const float f = (std::max)(0.0f, n - 0.42f) / 0.58f;
            if (f <= 0.0f) continue;
            const gta2::Vec3& sn = smooth[keyOf(v)];
            const float depth = amplitude * f * f * wSill;
            v.x -= sn.x * depth; v.y -= sn.y * depth; v.z -= sn.z * depth;
            ++moved;
        }
    }
    // Normals from the moved faces, accumulated per shared position.
    std::map<PosKey, gta2::Vec3> rebuilt;
    for (const ModelMesh& mesh : dented.meshes) {
        for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
            const ModelVertex& a = mesh.vertices[mesh.indices[t]];
            const ModelVertex& b = mesh.vertices[mesh.indices[t + 1]];
            const ModelVertex& c = mesh.vertices[mesh.indices[t + 2]];
            const gta2::Vec3 e1{b.x - a.x, b.y - a.y, b.z - a.z}, e2{c.x - a.x, c.y - a.y, c.z - a.z};
            const gta2::Vec3 fn = gta2::Cross(e1, e2);
            for (const ModelVertex* v : {&a, &b, &c}) {
                gta2::Vec3& acc = rebuilt[keyOf(*v)];
                acc.x += fn.x; acc.y += fn.y; acc.z += fn.z;
            }
        }
    }
    for (ModelMesh& mesh : dented.meshes) {
        for (ModelVertex& v : mesh.vertices) {
            auto r = rebuilt.find(keyOf(v));
            if (r == rebuilt.end()) continue;
            const float l = std::sqrt(gta2::Dot(r->second, r->second));
            if (l <= 1e-10f) continue;
            // Keep the original facing where the rebuilt one disagrees (a flipped sliver).
            gta2::Vec3 nn{r->second.x / l, r->second.y / l, r->second.z / l};
            if (nn.x * v.nx + nn.y * v.ny + nn.z * v.nz < 0.0f) { nn.x = -nn.x; nn.y = -nn.y; nn.z = -nn.z; }
            v.nx = nn.x; v.ny = nn.y; v.nz = nn.z;
        }
    }
    const Model* stored = ModelRegisterDerived(std::move(dented));
    g_dents[key] = stored;
    Log("car bodies: dented copy of %s, step %d of %d: %zu vertices pressed in, up to %.3f of the length", model.name.c_str(), step, kDentSteps, moved,
        0.02f * static_cast<float>(step) / static_cast<float>(kDentSteps));
    return stored;
}

// Doors. A car's model is a sealed hull; when someone gets in or out the game
// draws the door open on the sprite, so the body copy here loses the door's
// panel (the outer skin between the windscreen base and a door's length back,
// on the boarding side) and that panel is drawn on its own, swung about its
// front edge. Both copies are cached per (model, side, position).
struct DoorKey {
    const Model* model; int side, zf, zr;
    bool operator<(const DoorKey& o) const { return std::tie(model, side, zf, zr) < std::tie(o.model, o.side, o.zf, o.zr); }
};
struct DoorSplit { const Model* body; const Model* door; };
std::map<DoorKey, DoorSplit> g_doorSplits;

DoorSplit DoorSplitFor(const Model& model, const gta2::Mat4& fit, int side, float zFront, float zRear, float roof, float halfW) {
    const DoorKey key{&model, side, static_cast<int>(std::floor(zFront * 20.0f)), static_cast<int>(std::floor(zRear * 20.0f))};
    auto it = g_doorSplits.find(key);
    if (it != g_doorSplits.end()) return it->second;
    if (g_doorSplits.size() > 64) g_doorSplits.clear();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model body, door;
    for (Model* m : {&body, &door}) {
        m->nodes = model.nodes; m->forward = model.forward;
        m->boundsMin = model.boundsMin; m->boundsMax = model.boundsMax;
        for (int k = 0; k < 3; ++k) m->paintRgb[k] = model.paintRgb[k];
        m->splitPaint = model.splitPaint;
        m->meshes.resize(model.meshes.size());
    }
    body.name = model.name + "#nodoor"; door.name = model.name + "#door";
    size_t doorTris = 0;
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& db = body.meshes[static_cast<size_t>(mi)];
        ModelMesh& dd = door.meshes[static_cast<size_t>(mi)];
        db.vertices = src.vertices; db.texture = src.texture; db.skin = -1;
        dd.vertices = src.vertices; dd.texture = src.texture; dd.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            gta2::Vec3 q[3];
            float cx = 0.0f, cy = 0.0f, cz = 0.0f;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                cx += q[c].x; cy += q[c].y; cz += q[c].z;
            }
            cx /= 3.0f; cy /= 3.0f; cz /= 3.0f;
            const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
            const float nl = std::sqrt(gta2::Dot(nrm, nrm));
            const bool lateral = nl > 1e-9f && std::fabs(nrm.x) / nl > 0.45f;
            const bool isDoor = lateral && static_cast<float>(side) * cx > 0.5f * halfW && cy > 0.10f * roof && cy < 0.95f * roof &&
                                cz > zRear && cz < zFront;
            ModelMesh& dst = isDoor ? dd : db;
            dst.indices.push_back(src.indices[t]); dst.indices.push_back(src.indices[t + 1]); dst.indices.push_back(src.indices[t + 2]);
            if (isDoor) ++doorTris;
        }
    }
    // The door's inner face is seen once it swings out: the same triangles again,
    // wound the other way with their normals flipped, so the inside is lit too.
    for (ModelMesh& mesh : door.meshes) {
        if (mesh.indices.empty()) continue;
        const uint32_t base = static_cast<uint32_t>(mesh.vertices.size());
        std::vector<ModelVertex> inner = mesh.vertices;
        // Normals kept as the outer skin's: the inside of a swung door takes the
        // same light as the panel, not the dark of a face turned from the sun.
        mesh.vertices.insert(mesh.vertices.end(), inner.begin(), inner.end());
        const size_t n = mesh.indices.size();
        for (size_t t = 0; t + 2 < n; t += 3) {
            mesh.indices.push_back(base + mesh.indices[t + 2]);
            mesh.indices.push_back(base + mesh.indices[t + 1]);
            mesh.indices.push_back(base + mesh.indices[t]);
        }
    }
    DoorSplit split{ModelRegisterDerived(std::move(body)), ModelRegisterDerived(std::move(door))};
    g_doorSplits[key] = split;
    Log("car bodies: door split of %s, side %d: %zu door triangles between z %.2f and %.2f", model.name.c_str(), side, doorTris, zRear, zFront);
    return split;
}

// Turrets (POLICE-3D). The tank's gun turret and the fire truck's roof gear
// (the water cannon on its ladder deck) are part of each model's one sealed
// mesh, and the game aims them on their own: the turret is a sprite object of
// its own over the hull, with a heading of its own (CarBodiesSetTurret). The
// model is split once into the hull and the part above a height cut (`cut` of
// the roof; for the fire truck only behind `zMax` along the body), and that part
// is turned about the vertical through its own middle by the turret's heading
// against the hull's.
struct TurretKey {
    const Model* model; int cut, zMax;
    bool operator<(const TurretKey& o) const { return std::tie(model, cut, zMax) < std::tie(o.model, o.cut, o.zMax); }
};
struct TurretSplit { const Model* hull; const Model* turret; float pivotX, pivotZ; };
std::map<TurretKey, TurretSplit> g_turretSplits;
struct TurretAim { float dirX = 0.0f, dirZ = 1.0f; uint32_t frame = 0; };
std::map<uintptr_t, TurretAim> g_turretAims;   // by the car's sprite object
int g_turretLogged = 0;

TurretSplit TurretSplitFor(const Model& model, const gta2::Mat4& fit, float roof, float cut, float zMax) {
    const TurretKey key{&model, static_cast<int>(cut * 100.0f), static_cast<int>(std::floor(zMax * 50.0f))};
    auto it = g_turretSplits.find(key);
    if (it != g_turretSplits.end()) return it->second;
    if (g_turretSplits.size() > 16) g_turretSplits.clear();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model hull, top;
    for (Model* m : {&hull, &top}) {
        m->nodes = model.nodes; m->forward = model.forward;
        m->boundsMin = model.boundsMin; m->boundsMax = model.boundsMax;
        for (int k = 0; k < 3; ++k) m->paintRgb[k] = model.paintRgb[k];
        m->splitPaint = model.splitPaint;
        m->meshes.resize(model.meshes.size());
    }
    hull.name = model.name + "#hull"; top.name = model.name + "#turret";
    size_t topTris = 0;
    double ax = 0.0, az = 0.0, aw = 0.0;
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& dh = hull.meshes[static_cast<size_t>(mi)];
        ModelMesh& dt = top.meshes[static_cast<size_t>(mi)];
        dh.vertices = src.vertices; dh.texture = src.texture; dh.skin = -1;
        dt.vertices = src.vertices; dt.texture = src.texture; dt.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            gta2::Vec3 q[3];
            float cx = 0.0f, cy = 0.0f, cz = 0.0f;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                cx += q[c].x; cy += q[c].y; cz += q[c].z;
            }
            cx /= 3.0f; cy /= 3.0f; cz /= 3.0f;
            const bool isTop = cy > cut * roof && cz < zMax;
            ModelMesh& dst = isTop ? dt : dh;
            dst.indices.push_back(src.indices[t]); dst.indices.push_back(src.indices[t + 1]); dst.indices.push_back(src.indices[t + 2]);
            if (isTop) {
                ++topTris;
                const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
                const double area = std::sqrt(gta2::Dot(nrm, nrm));
                ax += area * cx; az += area * cz; aw += area;
            }
        }
    }
    TurretSplit split{nullptr, nullptr, 0.0f, 0.0f};
    if (topTris >= 8 && aw > 0.0) {
        split.pivotX = static_cast<float>(ax / aw); split.pivotZ = static_cast<float>(az / aw);
        split.hull = ModelRegisterDerived(std::move(hull));
        split.turret = ModelRegisterDerived(std::move(top));
    }
    g_turretSplits[key] = split;
    Log("car bodies: turret split of %s above %.2f of the roof (z < %.2f): %zu triangles, pivot %.3f,%.3f", model.name.c_str(), cut, zMax, topTris,
        split.pivotX, split.pivotZ);
    return split;
}

// How far each car's door stands open (0 shut, 1 fully), by sprite object.
struct DoorState { float open = 0.0f; int side = 1; uint32_t frame = 0; };
std::map<uintptr_t, DoorState> g_doors;
int g_damageLogged = 0;

Built* Measured(IDirect3DDevice9* device, const CarBodyUse& use, IDirect3DTexture9* art, uint32_t frame) {
    (void)device;
    const Key key{use.sprite, art};
    auto found = g_cache.find(key);
    if (found != g_cache.end()) {
        found->second.used = frame;
        return found->second.measured ? &found->second : nullptr;
    }
    if (g_cache.size() >= kCacheMax) {
        for (auto it = g_cache.begin(); it != g_cache.end();) {
            if (frame - it->second.used > 300) {
                if (it->second.atlas) it->second.atlas->Release();
                ReleaseBuffers(&it->second);
                it = g_cache.erase(it);
            } else {
                ++it;
            }
        }
    }
    Built& b = g_cache[key];
    b.used = frame;
    int w = 0, h = 0;
    const double t0 = CarNowMs();
    // The game's own palette indices decoded on the CPU: a device readback of a
    // texture the driver has just uploaded stalls the whole pipeline on a GPU
    // (hundreds of milliseconds at a car's door animation, which is a new
    // texture every frame); the readback is kept only as the fallback.
    const bool decoded = SpriteImageFor(use.texture, &b.px, &w, &h) && w >= 4 && h >= 4 && w <= 256 && h <= 256;
    const bool ok = (decoded || ReadArt(art, &b.px, &w, &h)) && MeasureSprite(b.px, w, h, use.sprite, &b.measure);
    g_carStats[0] += CarNowMs() - t0;
    g_carStats[4] += 1;
    if (!ok) {
        static int logged = 0;
        if (logged++ < 10) Log("car body: sprite %d has no usable artwork (%dx%d)", use.sprite, w, h);
        b.px.clear();
        return nullptr;
    }
    b.scale = PixelScale(use, h);
    b.paint = b.measure.paint;
    const gta2::CarInfo* info = g_info.count(use.sprite) ? &g_info[use.sprite] : nullptr;
    b.bodyLength = (info && info->height > 4 ? info->height : (b.measure.bottom - b.measure.top + 1)) * b.scale;
    b.bodyWidth = (info && info->width > 4 ? info->width : 2.0f * b.measure.maxHalfW) * b.scale;
    b.measured = true;
    return &b;
}

// The body built from the artwork, made on first use.
bool BodyMesh(IDirect3DDevice9* device, const CarBodyUse& use, Built* b) {
    if (b->meshBuilt) return b->ok;
    b->meshBuilt = true;
    Atlas atlas;
    b->atlas = MakeAtlas(device, b->px, b->measure, &atlas);
    if (!b->atlas) return false;
    BuildMesh(b->measure, atlas, b->scale, b);
    b->ok = !b->verts.empty() && b->verts.size() < 65000;
    b->px.clear();
    b->px.shrink_to_fit();
    ++g_built;
    static int logged = 0;
    if (logged++ < 40) {
        const Measure& m = b->measure;
        Log("car body: sprite %d (model %d) built from %dx%d art, body rows %d..%d, cabin %.0f..%.0f, wheels %.0f/%.0f, "
            "%u vertices, %s", use.sprite, use.model, m.w, m.h, m.top, m.bottom, m.cabinRear, m.cabinFront, m.wheelRear,
            m.wheelFront, static_cast<unsigned>(b->verts.size()),
            m.hasInfo ? "measured from CARI" : "no CARI entry, proportions guessed");
    }
    return b->ok;
}

// The buffers of a body, made once; false when the device gives none (then
// the body is drawn from memory).
bool Buffers(IDirect3DDevice9* device, Built* b) {
    if (b->buffersTried) return b->vb != nullptr;
    b->buffersTried = true;
    auto make = [&](const std::vector<CarBodyVertex>& v, const std::vector<uint16_t>& i, IDirect3DVertexBuffer9** vb,
                    IDirect3DIndexBuffer9** ib) {
        const UINT vbytes = static_cast<UINT>(v.size() * sizeof(CarBodyVertex)), ibytes = static_cast<UINT>(i.size() * 2);
        if (FAILED(device->CreateVertexBuffer(vbytes, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, vb, nullptr))) return false;
        if (FAILED(device->CreateIndexBuffer(ibytes, D3DUSAGE_WRITEONLY, D3DFMT_INDEX16, D3DPOOL_MANAGED, ib, nullptr))) return false;
        void* data = nullptr;
        if (FAILED((*vb)->Lock(0, vbytes, &data, 0)) || !data) return false;
        memcpy(data, v.data(), vbytes);
        (*vb)->Unlock();
        if (FAILED((*ib)->Lock(0, ibytes, &data, 0)) || !data) return false;
        memcpy(data, i.data(), ibytes);
        (*ib)->Unlock();
        return true;
    };
    if (!make(b->verts, b->indices, &b->vb, &b->ib) || !make(b->wheelVerts, b->wheelIndices, &b->wvb, &b->wib)) {
        ReleaseBuffers(b);
        Log("car body: no vertex buffers; drawing from memory");
        return false;
    }
    return true;
}

// Car space into the quad's own space: x across, y up (which way the quad's
// normal points), z toward the nose (larger v), origin at the canvas centre.
gta2::Mat4 CarToLocal(const CarBodyUse& use) {
    const CarBodyVertex* c = use.local;
    const float ax = c[1].x - c[0].x, ay = c[1].y - c[0].y, az = c[1].z - c[0].z;
    const float bx = c[3].x - c[0].x, by = c[3].y - c[0].y, bz = c[3].z - c[0].z;
    const float duA = c[1].u - c[0].u, dvA = c[1].v - c[0].v, duB = c[3].u - c[0].u, dvB = c[3].v - c[0].v;
    const float det = duA * dvB - duB * dvA;
    gta2::Mat4 out;
    out.m[3][3] = 1.0f;
    if (std::fabs(det) < 1e-9f) {
        out.m[0][0] = out.m[1][1] = out.m[2][2] = 1.0f;
        return out;
    }
    // s, t from u, v: [s t] = inv([duA duB; dvA dvB]) [u-u0 v-v0]
    const float i00 = dvB / det, i01 = -duB / det, i10 = -dvA / det, i11 = duA / det;
    // d local / d u and d local / d v (per unit of u and v).
    const float dux = ax * i00 + bx * i10, duy = ay * i00 + by * i10, duz = az * i00 + bz * i10;
    const float dvx = ax * i01 + bx * i11, dvy = ay * i01 + by * i11, dvz = az * i01 + bz * i11;
    float ex = dux, ey = duy, ez = duz;
    float fx = dvx, fy = dvy, fz = dvz;
    const float el = std::sqrt(ex * ex + ey * ey + ez * ez), fl = std::sqrt(fx * fx + fy * fy + fz * fz);
    if (el > 1e-9f) { ex /= el; ey /= el; ez /= el; }
    if (fl > 1e-9f) { fx /= fl; fy /= fl; fz /= fl; }
    // Up: the quad's normal, signed by which way the world calls up.
    float nx = ey * fz - ez * fy, ny = ez * fx - ex * fz, nz = ex * fy - ey * fx;
    const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
    if (nl > 1e-9f) { nx /= nl; ny /= nl; nz /= nl; } else { nx = 0; ny = 1; nz = 0; }
    // The world's up through the placement: the local axis whose image points up.
    const gta2::Mat4& o = use.objectToWorld;
    const float upWorld = nx * o.m[0][1] + ny * o.m[1][1] + nz * o.m[2][1];
    if (upWorld < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
    // Origin: the canvas centre (u, v = 0.5) on the quad.
    const float s = i00 * (0.5f - c[0].u) + i01 * (0.5f - c[0].v);
    const float t = i10 * (0.5f - c[0].u) + i11 * (0.5f - c[0].v);
    out.m[0][0] = ex; out.m[0][1] = ey; out.m[0][2] = ez;
    out.m[1][0] = nx; out.m[1][1] = ny; out.m[1][2] = nz;
    out.m[2][0] = fx; out.m[2][1] = fy; out.m[2][2] = fz;
    out.m[3][0] = c[0].x + s * ax + t * bx;
    out.m[3][1] = c[0].y + s * ay + t * by;
    out.m[3][2] = c[0].z + s * az + t * bz;
    return out;
}

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b) {
    gta2::Mat4 out;
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float s = 0.0f;
        for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
        out.m[r][c] = s;
    }
    return out;
}

float SteerFor(const CarBodyUse& use, const gta2::Mat4& world, float wheelbase, uint32_t frame) {
    if (!use.object) return 0.0f;
    // The nose in the world.
    float fx = world.m[2][0], fz = world.m[2][2];
    const float fl = std::sqrt(fx * fx + fz * fz);
    if (fl < 1e-6f) return 0.0f;
    fx /= fl; fz /= fl;
    const float x = world.m[3][0], z = world.m[3][2];
    const float yaw = std::atan2(fz, fx);
    Steer& st = g_steer[use.object];
    if (frame - st.frame > 30) {
        st = Steer{};
        st.x = x; st.z = z; st.yaw = yaw; st.frame = frame;
    } else if (st.frame != frame) {
        const float ds = (x - st.x) * fx + (z - st.z) * fz;
        const float dyaw = WrapAngle(yaw - st.yaw);
        float target = st.angle * 0.92f;
        if (std::fabs(ds) > 0.004f && std::fabs(ds) < 1.0f) {
            target = std::atan(wheelbase * dyaw / ds);
            target = (std::max)(-0.6f, (std::min)(0.6f, target));
        }
        st.angle += (target - st.angle) * 0.3f;
        st.x = x; st.z = z; st.yaw = yaw; st.frame = frame;
    }
    if (g_steer.size() > 256) {
        for (auto it = g_steer.begin(); it != g_steer.end();) {
            it = (frame - it->second.frame > 600) ? g_steer.erase(it) : std::next(it);
        }
    }
    return st.angle;
}

}  // namespace

void CarBodiesSetInfo(const std::vector<gta2::CarInfo>& infos) {
    g_info.clear();
    for (const gta2::CarInfo& c : infos) {
        if (g_info.find(c.sprite) == g_info.end()) g_info[c.sprite] = c;
    }
    Log("car bodies: %u car models measured for %u sprites", static_cast<unsigned>(infos.size()),
        static_cast<unsigned>(g_info.size()));
}

bool CarBodiesCabin(const void* object, float* deck, float* roof, float* windscreen, float* halfWidth) {
    const auto it = g_cabins.find(reinterpret_cast<uintptr_t>(object));
    if (it == g_cabins.end()) return false;
    *deck = it->second.deck;
    *roof = it->second.roof;
    *windscreen = it->second.windscreen;
    *halfWidth = it->second.halfWidth;
    return true;
}

bool CarBodiesExtent(const void* object, float* length, float* height, float* halfWidth) {
    const auto it = g_cabins.find(reinterpret_cast<uintptr_t>(object));
    if (it == g_cabins.end()) return false;
    *length = it->second.length;
    *height = it->second.height;
    *halfWidth = it->second.halfWidth;
    return true;
}

int CarBodiesBuilt() { return g_built; }
const double* CarBodiesStats() { return g_carStats; }
int CarBodiesDrawn() { return g_drawn; }

// ---------------------------------------------------------------------------
// Lamps. Headlamps and tail lamps as additive glows at the body's ends when it
// is dark, and brake lamps (brighter, larger red) while the car is losing
// speed, by day too. A radial glow texture, made once.
int g_lampMode = 1;
bool g_lampDark = false;
IDirect3DTexture9* g_glow = nullptr;
struct Motion { float x, z, speed; uint32_t frame; float brake; };
std::map<uintptr_t, Motion> g_motion;

IDirect3DTexture9* GlowTexture(IDirect3DDevice9* device) {
    if (g_glow) return g_glow;
    const int n = 32;
    if (FAILED(device->CreateTexture(n, n, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_glow, nullptr))) { g_glow = nullptr; return nullptr; }
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(g_glow->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < n; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < n; ++x) {
                const float dx = (x + 0.5f) / n - 0.5f, dy = (y + 0.5f) / n - 0.5f;
                const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
                const float a = (std::max)(0.0f, 1.0f - r);
                const int v = static_cast<int>(a * a * 255.0f + 0.5f);
                row[x] = (static_cast<uint32_t>(v) << 24) | (static_cast<uint32_t>(v) << 16) | (static_cast<uint32_t>(v) << 8) | static_cast<uint32_t>(v);
            }
        }
        g_glow->UnlockRect(0);
    }
    return g_glow;
}

struct LampVertex { float x, y, z; DWORD color; float u, v; };
constexpr DWORD kLampFvf = D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1;

// `carToWorld`: the body's frame (x across, y up, z along, nose +z); `length`,
// `width`, `roof` in blocks. Leaves the states it changes as it found them.
void DrawLamps(IDirect3DDevice9* device, const CarBodyUse& use, const gta2::Mat4& carToWorld, float length,
               float width, float roof, uint32_t frame, bool wreck) {
    if (g_lampMode == 0 || wreck) return;
    // How fast, and is it slowing: the body's position frame to frame.
    Motion& mo = g_motion[use.object];
    const float x = carToWorld.m[3][0], z = carToWorld.m[3][2];
    if (mo.frame && frame > mo.frame && frame - mo.frame < 10) {
        const float dt = static_cast<float>(frame - mo.frame) / 30.0f;
        const float speed = std::sqrt((x - mo.x) * (x - mo.x) + (z - mo.z) * (z - mo.z)) / dt;
        const float decel = (mo.speed - speed) / dt;   // blocks/s^2
        const float want = (mo.speed > 0.6f && decel > 1.5f) ? 1.0f : 0.0f;
        mo.brake += (want - mo.brake) * (std::min)(1.0f, dt / (want > mo.brake ? 0.05f : 0.35f));
        mo.speed = speed;
    } else {
        mo.speed = 0.0f; mo.brake = 0.0f;
    }
    mo.x = x; mo.z = z; mo.frame = frame;
    if (g_motion.size() > 2048) { const Motion keep = mo; g_motion.clear(); g_motion[use.object] = keep; }
    const bool lit = g_lampMode == 2 || g_lampDark;
    if (!lit && mo.brake < 0.05f) return;
    IDirect3DTexture9* glow = GlowTexture(device);
    if (!glow) return;
    const float hx = 0.34f * width, hy = (std::max)(0.05f, 0.30f * roof), nose = 0.5f * length + 0.006f;
    struct Lamp { float x, y, z; float size; DWORD color; };
    Lamp lamps[4]; int n = 0;
    if (lit) {
        lamps[n++] = {-hx, hy, nose, 0.11f, 0xFFFFF0C8u};
        lamps[n++] = {hx, hy, nose, 0.11f, 0xFFFFF0C8u};
    }
    {
        const float b = mo.brake;
        const int r = static_cast<int>((lit ? 150.0f : 0.0f) + b * 105.0f), g = static_cast<int>(lit ? 30.0f : 0.0f);
        if (r > 0) {
            const DWORD col = D3DCOLOR_ARGB(255, r, g, g / 2);
            const float sz = 0.07f + 0.05f * b;
            lamps[n++] = {-hx, hy, -nose, sz, col};
            lamps[n++] = {hx, hy, -nose, sz, col};
        }
    }
    if (!n) return;
    // Camera-facing quads: the car's axes give "across" and "up" of the body; a
    // lamp glow is round, so its own quad is spanned by the car's x and y.
    LampVertex v[16];
    int count = 0;
    for (int i = 0; i < n; ++i) {
        const Lamp& l = lamps[i];
        const float ax[3] = {carToWorld.m[0][0], carToWorld.m[0][1], carToWorld.m[0][2]};
        const float ay[3] = {carToWorld.m[1][0], carToWorld.m[1][1], carToWorld.m[1][2]};
        const float az[3] = {carToWorld.m[2][0], carToWorld.m[2][1], carToWorld.m[2][2]};
        float c[3];
        for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + l.x * ax[j] + l.y * ay[j] + l.z * az[j];
        const float s = l.size;
        const float corners[4][2] = {{-s, -s}, {s, -s}, {s, s}, {-s, s}};
        const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
        for (int k = 0; k < 4; ++k) {
            LampVertex& o = v[count++];
            o.x = c[0] + corners[k][0] * ax[0] + corners[k][1] * ay[0];
            o.y = c[1] + corners[k][0] * ax[1] + corners[k][1] * ay[1];
            o.z = c[2] + corners[k][0] * ax[2] + corners[k][1] * ay[2];
            o.color = l.color; o.u = uv[k][0]; o.v = uv[k][1];
        }
    }
    static const uint16_t idx[24] = {0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11, 12, 13, 14, 12, 14, 15};
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, glow);
    device->SetFVF(kLampFvf);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(count), static_cast<UINT>(n * 2), idx,
                                   D3DFMT_INDEX16, v, sizeof(LampVertex));
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
}

// Emergency lights on the 3D bodies (POLICE-3D). The game lights a siren car's
// roof lamps as sprite deltas 15..18 (the car's delta mask, vehicle +0x08) while
// its siren runs; a 3D model hides the sprite, so those lamps were lost in the
// street views. A car of a siren model (cop car 12, ambulance 34, fire truck 17,
// SWAT van 52) with any of those bits set gets two
// beacons on its roof that flash in turn, the colours by model; with the siren
// off the bar is dark. Drawn day and night, whatever car_lamps says.
// `[devtools] force_sirens=1` lights them on every siren model for checks.
int g_forceSirens = 0;
int g_beaconLogged = 0;
void DrawBeacons(IDirect3DDevice9* device, const CarBodyUse& use, const gta2::Mat4& carToWorld, float length, float width,
                 float roof, uint32_t frame, int modelNumber) {
    DWORD colA = 0, colB = 0;
    float along = 0.0f;
    switch (modelNumber) {
        case 12: case 52: colA = 0xFFFF2010u; colB = 0xFF1040FFu; along = -0.05f; break;   // police: red, blue
        case 34: colA = 0xFFFF2010u; colB = 0xFFFFF4E0u; along = 0.30f; break;                     // ambulance: red, white, over the cab
        case 17: colA = 0xFFFF2010u; colB = 0xFFFF7010u; along = 0.36f; break;                     // fire truck: red, amber, over the cab
        default: return;
    }
    uint32_t mask = 0;
    {
        const uint8_t* object = reinterpret_cast<const uint8_t*>(use.object);
        const uint8_t* car = object ? *reinterpret_cast<const uint8_t* const*>(object + 0x08) : nullptr;   // sprite owner -> vehicle
        if (car && reinterpret_cast<uintptr_t>(car) > 0x10000) mask = *reinterpret_cast<const uint32_t*>(car + 0x08);
    }
    const uint32_t sirenBits = (0xFu << 15) | (0xFu << (15 + 17));   // deltas 15..18 and their mirrored copies
    const bool on = (mask & sirenBits) != 0 || g_forceSirens != 0;
    if (!on) return;
    IDirect3DTexture9* glow = GlowTexture(device);
    if (!glow) return;
    if (g_beaconLogged < 12) {
        ++g_beaconLogged;
        Log("car bodies: beacons on model %d object %p (delta mask %08x%s)", modelNumber, reinterpret_cast<const void*>(use.object), mask,
            g_forceSirens ? ", forced" : "");
    }
    // The game's own lamps alternate; where it holds them all lit the flash is ours: 2.5 Hz.
    const bool phase = ((frame / 6u) & 1u) != 0;
    const bool litA = (mask & ((1u << 15) | (1u << 17))) ? true : phase;
    const bool litB = (mask & ((1u << 16) | (1u << 18))) ? true : !phase;
    const bool aOn = ((mask & sirenBits) == sirenBits || g_forceSirens) ? phase : litA;
    const bool bOn = ((mask & sirenBits) == sirenBits || g_forceSirens) ? !phase : litB;
    struct Beacon { float x; DWORD color; float size; };
    Beacon beacons[4]; int n = 0;
    const float hx = 0.22f * width, y = roof + 0.02f, z = along * length;
    // A lit beacon is a bright core and a wide soft halo.
    if (aOn) { beacons[n++] = {-hx, colA, 0.07f}; beacons[n++] = {-hx, (colA & 0x00FFFFFFu) | 0xFF000000u, 0.18f}; }
    if (bOn) { beacons[n++] = {hx, colB, 0.07f}; beacons[n++] = {hx, (colB & 0x00FFFFFFu) | 0xFF000000u, 0.18f}; }
    if (!n) return;
    LampVertex v[32];
    int count = 0;
    const float ax[3] = {carToWorld.m[0][0], carToWorld.m[0][1], carToWorld.m[0][2]};
    const float ay[3] = {carToWorld.m[1][0], carToWorld.m[1][1], carToWorld.m[1][2]};
    const float az[3] = {carToWorld.m[2][0], carToWorld.m[2][1], carToWorld.m[2][2]};
    // Billboards facing the eye would need the camera here; the glows are spanned
    // by the car's across and along axes (seen from above) and by across and up
    // (seen from the street): two crossed quads per beacon.
    for (int i = 0; i < n; ++i) {
        const Beacon& bc = beacons[i];
        const float s = bc.size;
        DWORD col = bc.color;
        if (s > 0.1f) {   // the halo dimmer than the core
            const int r = static_cast<int>(((col >> 16) & 0xFF) * 0.45f), g = static_cast<int>(((col >> 8) & 0xFF) * 0.45f),
                      b = static_cast<int>((col & 0xFF) * 0.45f);
            col = D3DCOLOR_ARGB(255, r, g, b);
        }
        float c[3];
        for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + bc.x * ax[j] + y * ay[j] + z * az[j];
        const float corners[4][2] = {{-s, -s}, {s, -s}, {s, s}, {-s, s}};
        const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
        const float* second[2] = {ay, az};
        for (int q = 0; q < 2 && count + 4 <= 32; ++q) {
            const float* b2 = second[q];
            for (int k = 0; k < 4; ++k) {
                LampVertex& o = v[count++];
                o.x = c[0] + corners[k][0] * ax[0] + corners[k][1] * b2[0];
                o.y = c[1] + corners[k][0] * ax[1] + corners[k][1] * b2[1];
                o.z = c[2] + corners[k][0] * ax[2] + corners[k][1] * b2[2];
                o.color = col; o.u = uv[k][0]; o.v = uv[k][1];
            }
        }
    }
    uint16_t idx[48];
    for (int q = 0; q < count / 4; ++q) {
        const uint16_t b0 = static_cast<uint16_t>(q * 4);
        const uint16_t t[6] = {b0, static_cast<uint16_t>(b0 + 1), static_cast<uint16_t>(b0 + 2), b0, static_cast<uint16_t>(b0 + 2), static_cast<uint16_t>(b0 + 3)};
        memcpy(idx + q * 6, t, sizeof t);
    }
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, glow);
    device->SetFVF(kLampFvf);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(count), static_cast<UINT>(count / 2), idx,
                                   D3DFMT_INDEX16, v, sizeof(LampVertex));
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
}

void CarBodiesSetLamps(int mode, bool dark) { g_lampMode = mode; g_lampDark = dark; }

void CarBodiesReleaseDevice() {
    for (auto& e : g_cache) {
        if (e.second.atlas) e.second.atlas->Release();
        ReleaseBuffers(&e.second);
    }
    g_cache.clear();
    if (g_glow) { g_glow->Release(); g_glow = nullptr; }
    g_device = nullptr;
}

// Whether a point of the world lies inside the car's box (car space, a little margin).
bool Inside(const gta2::Mat4& carToWorld, const gta2::Vec3& p, float halfW, float halfL, float height) {
    // Invert the rigid part: rows are the car's axes in the world.
    const float dx = p.x - carToWorld.m[3][0], dy = p.y - carToWorld.m[3][1], dz = p.z - carToWorld.m[3][2];
    const float x = dx * carToWorld.m[0][0] + dy * carToWorld.m[0][1] + dz * carToWorld.m[0][2];
    const float y = dx * carToWorld.m[1][0] + dy * carToWorld.m[1][1] + dz * carToWorld.m[1][2];
    const float z = dx * carToWorld.m[2][0] + dy * carToWorld.m[2][1] + dz * carToWorld.m[2][2];
    return std::fabs(x) < halfW + 0.15f && std::fabs(z) < halfL + 0.15f && y > -0.2f && y < height + 0.15f;
}

void CarBodiesDraw(IDirect3DDevice9* device, const std::vector<CarBodyUse>& cars, uint32_t frame, const gta2::Vec3& eye) {
    g_built = 0;
    g_drawn = 0;
    for (double& v : g_carStats) v = 0.0;
    if (cars.empty()) return;
    if (g_device != device) {
        CarBodiesReleaseDevice();
        g_device = device;
    }
    // Lit, so the body has shape: one sun from high in front and to the side,
    // some ambient, and a modest specular lobe for the paint.
    D3DLIGHT9 sun = {};
    sun.Type = D3DLIGHT_DIRECTIONAL;
    sun.Diffuse = {0.78f, 0.78f, 0.78f, 1.0f};   // neutral: the paint tint must not pick up a cast
    sun.Specular = {0.55f, 0.55f, 0.55f, 1.0f};
    const float dx = 0.38f, dy = -0.78f, dz = 0.50f;
    const float dl = std::sqrt(dx * dx + dy * dy + dz * dz);
    sun.Direction = {dx / dl, dy / dl, dz / dl};
    device->SetLight(0, &sun);
    device->LightEnable(0, TRUE);
    D3DMATERIAL9 material = {};
    material.Diffuse = {1.0f, 1.0f, 1.0f, 1.0f};
    material.Ambient = {1.0f, 1.0f, 1.0f, 1.0f};
    material.Specular = {0.6f, 0.6f, 0.6f, 1.0f};
    material.Power = 26.0f;
    device->SetMaterial(&material);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
    device->SetRenderState(D3DRS_AMBIENT, 0x005A5A5Au);
    device->SetRenderState(D3DRS_SPECULARENABLE, TRUE);
    device->SetRenderState(D3DRS_LOCALVIEWER, TRUE);
    device->SetRenderState(D3DRS_NORMALIZENORMALS, TRUE);
    device->SetRenderState(D3DRS_COLORVERTEX, FALSE);
    device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_SPECULARMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);

    int builtThisFrame = 0;
    if (g_devIni[0] && frame % 60 == 0) {
        g_forceModel = GetPrivateProfileIntA("devtools", "force_car_model", -1, g_devIni);
        g_forceDamage = GetPrivateProfileIntA("devtools", "force_car_damage", -1, g_devIni);
        g_forceDoor = GetPrivateProfileIntA("devtools", "force_car_door", 0, g_devIni);
        g_forceSirens = GetPrivateProfileIntA("devtools", "force_sirens", 0, g_devIni);
    }
    if (g_logNoses < 0) { char v[8] = {}; g_logNoses = GetEnvironmentVariableA("GTA2DX9_LOG_CAR_NOSES", v, sizeof v) ? atoi(v) : 0; }
    for (const CarBodyUse& use : cars) {
        bool effect = false;
        IDirect3DTexture9* art = DeviceTextureFor(device, use.texture, &effect, true);
        if (!art) continue;
        Built* b = Measured(device, use, art, frame);
        if (!b) continue;
        const gta2::Mat4 carToWorld = Mul(CarToLocal(use), use.objectToWorld);
        if (g_logNoses && frame % 15 == 0) {
            // The placement's nose (+z of the car frame) in the world, before any
            // model's own `forward`; the checker pairs consecutive samples of one
            // object into a velocity and compares it with this direction.
            const Model* lm = (use.sprite >= 65 && use.sprite <= 74) ? nullptr : ModelForVehicle(g_forceModel >= 0 && !use.own ? g_forceModel : use.model, use.sprite);
            Log("car nose: obj=%08x sprite=%d model=%d f=%+d x=%.3f z=%.3f nx=%.3f nz=%.3f own=%d frame=%u",
                static_cast<unsigned>(use.object), use.sprite, use.model, lm ? (lm->forward < 0 ? -1 : 1) : 0,
                carToWorld.m[3][0], carToWorld.m[3][2], carToWorld.m[2][0], carToWorld.m[2][2], use.own ? 1 : 0, frame);
        }
        // A car behind the camera costs its whole transform and clip on the
        // software driver for nothing on screen; the margin covers a bus.
        if (!use.own && BehindView(carToWorld.m[3][0], carToWorld.m[3][1], carToWorld.m[3][2], 2.5f)) continue;
        D3DMATRIX wm;
        // The camera inside this car (standing at a parked car's door in the chase
        // view): the body would fill the screen with its underside. Not the own car:
        // from the driver's seat the models are solid hulls with painted windows, so
        // everything above a hand's breadth below the eye is clipped away and what
        // is left - hood, fenders, the cowl - is the view over a dashboard.
        const bool inside = Inside(carToWorld, eye, 0.5f * b->bodyWidth, 0.5f * b->bodyLength, 1.4f * b->bodyWidth);
        // Nor the car he drives: a chase camera at the sedan distance sits inside a
        // fire truck or a bus (run a33_fire1: the truck vanished from the chase view).
        if (inside && !use.own && !use.driven) continue;
        bool clipped = false;
        // The hood-only copy is drawn on both paths (Remix ignores user clip planes;
        // on plain D3D9 the plane below still trims the copy's edge exactly).
        const bool cpuCut = inside && use.own;
        float eyeLocalY = 0.0f, eyeLocalZ = 0.0f;
        if (cpuCut) {
            // The eye in the car's own frame: along its up and forward axes.
            const float ux = carToWorld.m[1][0], uy = carToWorld.m[1][1], uz = carToWorld.m[1][2];
            const float fx = carToWorld.m[2][0], fy = carToWorld.m[2][1], fz = carToWorld.m[2][2];
            const float dx = eye.x - carToWorld.m[3][0], dy = eye.y - carToWorld.m[3][1], dz = eye.z - carToWorld.m[3][2];
            const float ul = ux * ux + uy * uy + uz * uz, fl = fx * fx + fy * fy + fz * fz;
            eyeLocalY = ul > 1e-8f ? (dx * ux + dy * uy + dz * uz) / ul : 0.0f;
            eyeLocalZ = fl > 1e-8f ? (dx * fx + dy * fy + dz * fz) / fl : 0.0f;
        }
        if (inside && use.own && !RemixApiAvailable()) {
            const float ux = carToWorld.m[1][0], uy = carToWorld.m[1][1], uz = carToWorld.m[1][2];
            const float ul = std::sqrt(ux * ux + uy * uy + uz * uz);
            if (ul > 1e-6f) {
                const float nx = -ux / ul, ny = -uy / ul, nz = -uz / ul;   // keep what lies below
                const float margin = 0.035f;
                const float px_ = eye.x + ux / ul * -margin, py_ = eye.y + uy / ul * -margin, pz_ = eye.z + uz / ul * -margin;
                // Fixed-function clip planes are given in world space when no vertex shader is bound.
                const float plane[4] = {nx, ny, nz, -(nx * px_ + ny * py_ + nz * pz_)};
                device->SetClipPlane(0, plane);
                device->SetRenderState(D3DRS_CLIPPLANEENABLE, 1u);
                clipped = true;
            }
        }
        struct ClipOff {
            IDirect3DDevice9* device; bool on;
            ~ClipOff() { if (on) device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0u); }
        } clipOff{device, clipped};

        // A hand-made model for this vehicle: placed on the sprite's footprint,
        // its painted parts in the car's own colour.
        // A burnt-out car keeps its model number but the game swaps its sprite for
        // one of the ten wreck sprites (65..74): those are CARI models 72..81.
        const int modelNumber = (use.sprite >= 65 && use.sprite <= 74) ? 72 + (use.sprite - 65)
                                : g_wreckTest ? 72 + (use.sprite % 10)
                                : (g_forceModel >= 0 && !use.own) ? g_forceModel : use.model;
        if (const Model* model = ModelForVehicle(modelNumber, use.sprite)) {
            const float modelLen = (std::max)(model->Length(), 0.01f), modelWid = (std::max)(model->Width(), 0.01f);
            const bool sideways = modelWid > modelLen * 1.3f;   // modelled along x rather than z
            const float along = sideways ? modelWid : modelLen, across = sideways ? modelLen : modelWid;
            float sz = b->bodyLength / along, sx = b->bodyWidth / across;
            {
                // The footprint is the sprite's; a model with different proportions
                // would be stretched one way. Keep its shape: the aspect may change
                // by 15 % at most, the rest overhangs or falls short of the sprite.
                constexpr float kMaxAspect = 1.15f;
                const float s = std::sqrt(sx * sz);
                float r = sx / sz;
                r = (std::max)(1.0f / kMaxAspect, (std::min)(kMaxAspect, r));
                sx = s * std::sqrt(r);
                sz = s / std::sqrt(r);
            }
            const float sy = std::sqrt(sx * sz);
            gta2::Mat4 fit;
            const float f = model->forward;
            if (!sideways) {
                fit.m[0][0] = sx; fit.m[1][1] = sy; fit.m[2][2] = sz * f;
            } else {
                fit.m[0][2] = sz * f; fit.m[1][1] = sy; fit.m[2][0] = -sx;
            }
            fit.m[3][1] = -model->boundsMin.y * sy;
            fit.m[3][3] = 1.0f;
            // The car's paint over the model's own: what its painted textures are multiplied by.
            const float tint[3] = {b->paint.r / model->paintRgb[0], b->paint.g / model->paintRgb[1], b->paint.b / model->paintRgb[2]};
            {
                const float roof = model->Height() * sy;
                const float cy = 0.5f * b->measure.h;
                Cabin cabin{0.62f * roof, roof, (b->measure.cabinFront - cy) * b->scale, 0.5f * b->bodyWidth, frame,
                            b->bodyLength, roof};
                // A tall or long body (taller than a sedan's roof by a quarter, or a
                // third longer): the driver's cab from the model's own profile.
                if ((roof > 0.45f || b->bodyLength > 1.3f) && modelNumber < 72) {
                    const CabShape cab = CabShapeFor(*model, fit, modelNumber);
                    if (cab.valid) {
                        cabin.deck = cab.deck;
                        cabin.roof = cab.roof;
                        cabin.windscreen = cab.windscreen;
                        cabin.length = (std::max)(cab.length, b->bodyLength);
                        cabin.height = cab.height;
                    }
                }
                g_cabins[use.object] = cabin;
            }
            ModelSetPaintTint(tint);
            // A baked texture split into paint and the rest (import_assets.py's
            // paint_split) is two alpha-tested draws of the same mesh.
            device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
            device->SetRenderState(D3DRS_ALPHAREF, 128u);
            device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
            const double tm = CarNowMs();
            // Under Remix the own car is its hood-only copy (see HoodModelFor); the
            // same cuts the clip planes make elsewhere: a hand below the eye, a hand
            // ahead of it.
            // Wear: the damage byte in four steps, dents and a duller paint.
            const int dentStep = DentStepFor(g_forceDamage >= 0 ? g_forceDamage : use.damage);
            const Model* worn = dentStep > 0 && modelNumber < 72 ? DentedModelFor(*model, dentStep) : model;
            if (dentStep > 0) {
                const float dull = 1.0f - 0.06f * static_cast<float>(dentStep);
                const float tintWorn[3] = {tint[0] * dull, tint[1] * dull, tint[2] * dull};
                ModelSetPaintTint(tintWorn);
                if (g_damageLogged < 40) { ++g_damageLogged; Log("car bodies: object %p damage %d -> dent step %d", reinterpret_cast<const void*>(use.object), use.damage, dentStep); }
            }
            const Model* drawn = worn;
            if (cpuCut) drawn = HoodModelFor(*worn, fit, eyeLocalY - 0.035f, eyeLocalZ + 0.10f);
            // The door: swings open while someone boards or leaves, shuts after.
            DoorState& ds = g_doors[use.object];
            {
                const float dt = (std::min)(5u, (std::max)(1u, frame - ds.frame)) / 30.0f;
                ds.frame = frame;
                if (use.doorPed && ds.open < 0.02f) {
                    // Which side he stands on, in the car's frame.
                    const float rx = carToWorld.m[0][0], ry = carToWorld.m[0][1], rz = carToWorld.m[0][2];
                    const float dxp = use.doorPedX - carToWorld.m[3][0], dzp = use.doorPedZ - carToWorld.m[3][2];
                    const float lateral = dxp * rx + 0.0f * ry + dzp * rz;
                    ds.side = lateral >= 0.0f ? 1 : -1;
                }
                if (g_forceDoor != 0 && ds.open < 0.02f) ds.side = g_forceDoor > 0 ? 1 : -1;
                const float target = (use.doorPed || g_forceDoor != 0) ? 1.0f : 0.0f;
                if (target > ds.open) ds.open = (std::min)(1.0f, ds.open + dt * 2.5f);
                else ds.open = (std::max)(0.0f, ds.open - dt * 1.7f);
            }
            if (ds.open > 0.02f && !cpuCut && modelNumber < 72) {
                const float roofY = model->Height() * sy, halfW = 0.5f * b->bodyWidth;
                float zFront = (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale;
                zFront = (std::min)(zFront, 0.42f * b->bodyLength);
                const float zRear = zFront - 0.27f * b->bodyLength;
                const DoorSplit split = DoorSplitFor(*worn, fit, ds.side, zFront, zRear, roofY, halfW);
                ModelDraw(device, *split.body, Mul(fit, carToWorld), nullptr, 0.0f);
                // Swing about the vertical through the door's front edge, outward.
                const float theta = -static_cast<float>(ds.side) * ds.open * (60.0f * kPi / 180.0f);
                const float cs = std::cos(theta), sn = std::sin(theta);
                const float hx = static_cast<float>(ds.side) * 0.92f * halfW, hz = zFront;
                gta2::Mat4 hinge;
                hinge.m[0][0] = cs; hinge.m[0][2] = -sn; hinge.m[1][1] = 1.0f; hinge.m[2][0] = sn; hinge.m[2][2] = cs;
                hinge.m[3][0] = hx - (hx * cs + hz * sn); hinge.m[3][2] = hz - (-hx * sn + hz * cs); hinge.m[3][3] = 1.0f;
                ModelDraw(device, *split.door, Mul(Mul(fit, hinge), carToWorld), nullptr, 0.0f);
            } else if ((modelNumber == 54 || modelNumber == 17) && !cpuCut) {
                // The turret turned to the game's aim (see TurretSplitFor); without an
                // aim seen in the last second it stays straight ahead.
                const float roofY = model->Height() * sy;
                const TurretSplit split = modelNumber == 54 ? TurretSplitFor(*worn, fit, roofY, 0.56f, 99.0f)
                                                            : TurretSplitFor(*worn, fit, roofY, 0.80f, 0.05f * b->bodyLength);
                auto aim = g_turretAims.find(use.object);
                float yaw = 0.0f;
                if (aim != g_turretAims.end() && frame - aim->second.frame < 30) {
                    // The aim in the car's own frame: across (x) and along (z), from its world axes.
                    const float ax = carToWorld.m[0][0], az = carToWorld.m[0][2], fx = carToWorld.m[2][0], fz = carToWorld.m[2][2];
                    const float across = aim->second.dirX * ax + aim->second.dirZ * az, along = aim->second.dirX * fx + aim->second.dirZ * fz;
                    if (across * across + along * along > 1e-8f) yaw = std::atan2(across, along);
                }
                if (split.turret) {
                    ModelDraw(device, *split.hull, Mul(fit, carToWorld), nullptr, 0.0f);
                    const float cs = std::cos(yaw), sn = std::sin(yaw);
                    const float px = split.pivotX, pz = split.pivotZ;
                    gta2::Mat4 turn;
                    turn.m[0][0] = cs; turn.m[0][2] = -sn; turn.m[1][1] = 1.0f; turn.m[2][0] = sn; turn.m[2][2] = cs;
                    turn.m[3][0] = px - (px * cs + pz * sn); turn.m[3][2] = pz - (-px * sn + pz * cs); turn.m[3][3] = 1.0f;
                    ModelDraw(device, *split.turret, Mul(Mul(fit, turn), carToWorld), nullptr, 0.0f);
                    if (g_turretLogged < 30 && (frame % 30u) == 0 && std::fabs(yaw) > 0.05f) {
                        ++g_turretLogged;
                        Log("car bodies: model %d turret turned %.0f deg (object %p)", modelNumber, yaw * 180.0f / kPi, reinterpret_cast<const void*>(use.object));
                    }
                } else {
                    ModelDraw(device, *drawn, Mul(fit, carToWorld), nullptr, 0.0f);
                }
            } else {
                ModelDraw(device, *drawn, Mul(fit, carToWorld), nullptr, 0.0f);
            }
            g_carStats[2] += CarNowMs() - tm;
            g_carStats[6] += 1;
            device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
            ModelSetPaintTint(nullptr);
            device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
            DrawLamps(device, use, carToWorld, b->bodyLength, b->bodyWidth, model->Height() * sy, frame, modelNumber >= 72);
            if (modelNumber < 72) {
                GTA2_TRY {
                    DrawBeacons(device, use, carToWorld, b->bodyLength, b->bodyWidth, model->Height() * sy, frame, modelNumber);
                } GTA2_EXCEPT {
                }
            }
            ++g_drawn;
            continue;
        }

        // Otherwise the body from the sprite. Building is a few milliseconds
        // each; a street of new cars is spread over frames.
        if (!b->meshBuilt && builtThisFrame >= 3) continue;
        if (!b->meshBuilt) ++builtThisFrame;
        const double tb = CarNowMs();
        const bool fresh = !b->meshBuilt;
        const bool built = BodyMesh(device, use, b);
        if (fresh) { g_carStats[1] += CarNowMs() - tb; g_carStats[5] += 1; }
        if (!built) continue;
        const double td = CarNowMs();
        const bool buffered = Buffers(device, b);
        memcpy(&wm, carToWorld.m, sizeof(wm));
        device->SetTexture(0, b->atlas);
        device->SetTransform(D3DTS_WORLD, &wm);
        if (buffered) {
            device->SetStreamSource(0, b->vb, 0, sizeof(CarBodyVertex));
            device->SetIndices(b->ib);
            device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(b->verts.size()), 0,
                                         static_cast<UINT>(b->indices.size() / 3));
            device->SetStreamSource(0, b->wvb, 0, sizeof(CarBodyVertex));
            device->SetIndices(b->wib);
        } else {
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(b->verts.size()),
                                           static_cast<UINT>(b->indices.size() / 3), b->indices.data(), D3DFMT_INDEX16,
                                           b->verts.data(), sizeof(CarBodyVertex));
        }
        g_cabins[use.object] = {b->deckY, b->roofY, (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale,
                                0.5f * b->bodyWidth, frame};
        const float steer = SteerFor(use, carToWorld, b->wheelbase, frame);
        for (int w = 0; w < 4; ++w) {
            const bool front = w < 2;
            const float x = (w & 1) ? b->wheelX : -b->wheelX;
            const float phi = front ? steer : 0.0f;
            const float cs = std::cos(phi), sn = std::sin(phi);
            gta2::Mat4 local;
            local.m[0][0] = cs;  local.m[0][2] = sn;
            local.m[1][1] = 1.0f;
            local.m[2][0] = -sn; local.m[2][2] = cs;
            local.m[3][0] = x; local.m[3][1] = b->wheelY; local.m[3][2] = b->wheelZ[front ? 0 : 1]; local.m[3][3] = 1.0f;
            const gta2::Mat4 ww = Mul(local, carToWorld);
            memcpy(&wm, ww.m, sizeof(wm));
            device->SetTransform(D3DTS_WORLD, &wm);
            if (buffered) {
                device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(b->wheelVerts.size()), 0,
                                             static_cast<UINT>(b->wheelIndices.size() / 3));
            } else {
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(b->wheelVerts.size()),
                                               static_cast<UINT>(b->wheelIndices.size() / 3), b->wheelIndices.data(),
                                               D3DFMT_INDEX16, b->wheelVerts.data(), sizeof(CarBodyVertex));
            }
        }
        if (buffered) {
            device->SetStreamSource(0, nullptr, 0, 0);
            device->SetIndices(nullptr);
        }
        DrawLamps(device, use, carToWorld, b->bodyLength, b->bodyWidth, b->roofY, frame, use.sprite >= 65 && use.sprite <= 74);
        g_carStats[3] += CarNowMs() - td;
        g_carStats[7] += 1;
        ++g_drawn;
    }
    // The texture budget, now and then: the game is a 32-bit process.
    if (frame % 900 == 0) {
        int count = 0;
        const size_t modelBytes = ModelsTextureBytes(&count);
        size_t atlasBytes = 0;
        for (const auto& e : g_cache) if (e.second.atlas) atlasBytes += e.second.measure.w * kAtlasScale * static_cast<size_t>(e.second.measure.h * kAtlasScale + kBandRows + kBlockRows) * 4;
        Log("car models: %d textures, %.1f MB in the managed pool; %u sprite-built atlases, %.1f MB; %d cars drawn this frame",
            count, modelBytes / 1048576.0, static_cast<unsigned>(g_cache.size()), atlasBytes / 1048576.0, g_drawn);
    }
    if (g_doors.size() > 256) {
        for (auto it = g_doors.begin(); it != g_doors.end();) it = (frame - it->second.frame > 600) ? g_doors.erase(it) : std::next(it);
    }
    if (g_cabins.size() > 128) {
        for (auto it = g_cabins.begin(); it != g_cabins.end();) {
            it = (frame - it->second.frame > 600) ? g_cabins.erase(it) : std::next(it);
        }
    }
    device->LightEnable(0, FALSE);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    device->SetRenderState(D3DRS_NORMALIZENORMALS, FALSE);
    device->SetRenderState(D3DRS_COLORVERTEX, TRUE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_CURRENT);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTexture(0, nullptr);
}

void CarBodiesSetWreckTest(bool on) { g_wreckTest = on; }
void CarBodiesSetDevIni(const char* ini) {
    if (!ini) { g_devIni[0] = 0; return; }
    strncpy(g_devIni, ini, sizeof(g_devIni) - 1);
    g_forceModel = GetPrivateProfileIntA("devtools", "force_car_model", -1, g_devIni);
    g_forceDamage = GetPrivateProfileIntA("devtools", "force_car_damage", -1, g_devIni);
    g_forceDoor = GetPrivateProfileIntA("devtools", "force_car_door", 0, g_devIni);
}
const char* CarBodiesDevIni() { return g_devIni; }
void CarBodiesSetTurret(uintptr_t carObject, float dirX, float dirZ, uint32_t frame) {
    TurretAim& a = g_turretAims[carObject];
    a.dirX = dirX; a.dirZ = dirZ; a.frame = frame;
    if (g_turretAims.size() > 64) {
        for (auto it = g_turretAims.begin(); it != g_turretAims.end();) it = (frame - it->second.frame > 300) ? g_turretAims.erase(it) : std::next(it);
    }
}

}  // namespace gta2dx9
