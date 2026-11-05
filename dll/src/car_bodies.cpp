// See car_bodies.h.
#include "car_bodies.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>

#include "log.h"
#include "model_store.h"
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
    if (!ReadArt(art, &b.px, &w, &h) || !MeasureSprite(b.px, w, h, use.sprite, &b.measure)) {
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

int CarBodiesBuilt() { return g_built; }
int CarBodiesDrawn() { return g_drawn; }

void CarBodiesReleaseDevice() {
    for (auto& e : g_cache) {
        if (e.second.atlas) e.second.atlas->Release();
        ReleaseBuffers(&e.second);
    }
    g_cache.clear();
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
    if (cars.empty()) return;
    if (g_device != device) {
        CarBodiesReleaseDevice();
        g_device = device;
    }
    // Lit, so the body has shape: one sun from high in front and to the side,
    // some ambient, and a modest specular lobe for the paint.
    D3DLIGHT9 sun = {};
    sun.Type = D3DLIGHT_DIRECTIONAL;
    sun.Diffuse = {0.80f, 0.78f, 0.75f, 1.0f};
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
    for (const CarBodyUse& use : cars) {
        bool effect = false;
        IDirect3DTexture9* art = DeviceTextureFor(device, use.texture, &effect, true);
        if (!art) continue;
        Built* b = Measured(device, use, art, frame);
        if (!b) continue;
        const gta2::Mat4 carToWorld = Mul(CarToLocal(use), use.objectToWorld);
        D3DMATRIX wm;
        // The camera inside this car (standing at a parked car's door in the chase
        // view): the body would fill the screen with its underside. Not the own car.
        if (!use.own && Inside(carToWorld, eye, 0.5f * b->bodyWidth, 0.5f * b->bodyLength, 1.4f * b->bodyWidth)) continue;

        // A hand-made model for this vehicle: placed on the sprite's footprint,
        // its painted parts in the car's own colour.
        if (const Model* model = ModelForVehicle(use.model, use.sprite)) {
            const float modelLen = (std::max)(model->Length(), 0.01f), modelWid = (std::max)(model->Width(), 0.01f);
            const bool sideways = modelWid > modelLen * 1.3f;   // modelled along x rather than z
            const float along = sideways ? modelWid : modelLen, across = sideways ? modelLen : modelWid;
            const float sz = b->bodyLength / along, sx = b->bodyWidth / across;
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
                g_cabins[use.object] = {0.62f * roof, roof, (b->measure.cabinFront - cy) * b->scale, 0.5f * b->bodyWidth, frame};
            }
            ModelSetPaintTint(tint);
            ModelDraw(device, *model, Mul(fit, carToWorld), nullptr, 0.0f);
            ModelSetPaintTint(nullptr);
            device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
            ++g_drawn;
            continue;
        }

        // Otherwise the body from the sprite. Building is a few milliseconds
        // each; a street of new cars is spread over frames.
        if (!b->meshBuilt && builtThisFrame >= 3) continue;
        if (!b->meshBuilt) ++builtThisFrame;
        if (!BodyMesh(device, use, b)) continue;
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
        ++g_drawn;
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

}  // namespace gta2dx9
