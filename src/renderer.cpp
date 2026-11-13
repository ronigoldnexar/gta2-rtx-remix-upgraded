#include "renderer.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>

namespace gta2 {
namespace {

void (*g_trace)(const char*) = nullptr;

void Trace(const char* format, ...) {
    if (!g_trace) return;
    char line[512];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    g_trace(line);
}

// Where Direct3D comes from, and it matters which copy.
//
// RTX Remix ships as a d3d9.dll dropped beside the game, so *anything* in the
// process that asks the loader for "d3d9.dll" gets the Remix bridge client -
// including GTA2's own DirectDraw layer, which initialises during startup long
// before the renderer is loaded. That brings the Remix runtime up on a device
// DirectDraw owns: a fullscreen A8R8G8B8 one the game never draws through.
// Remix drives a single device per process, so ours arrives second, re-hooks the
// window procedure out from under the bridge's message channel, and the game
// hangs at the menu with the runtime still waiting on a handshake that can no
// longer be answered.
//
// Renaming the bridge and asking for it by that name keeps every accidental
// consumer on the system d3d9 and leaves the renderer's device the only one
// Remix ever sees. The plain name is still tried, so a stock Remix drop-in and a
// machine with no Remix at all both keep working.
const char* const kD3D9Modules[] = {"d3d9_remix.dll", "d3d9.dll"};

// Whether the Direct3D that answered is RTX Remix: the renamed bridge client, or a
// d3d9.dll that carries the Remix API (remix_api.cpp looks for the same export).
bool g_remixD3D9 = false;

IDirect3D9* CreateD3D9() {
    for (const char* name : kD3D9Modules) {
        const HMODULE module = LoadLibraryA(name);
        if (!module) continue;
        using CreateFn = IDirect3D9*(WINAPI*)(UINT);
        const auto create = reinterpret_cast<CreateFn>(GetProcAddress(module, "Direct3DCreate9"));
        if (!create) continue;
        if (IDirect3D9* d3d = create(D3D_SDK_VERSION)) {
            g_remixD3D9 = strcmp(name, "d3d9_remix.dll") == 0 || GetProcAddress(module, "remixapi_InitializeLibrary") != nullptr;
            Trace("Direct3D from %s%s", name, g_remixD3D9 ? " (RTX Remix)" : "");
            return d3d;
        }
    }
    return nullptr;
}

constexpr DWORD kWorldFvf = D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1;

// Tiles key their transparency off palette entry 0, so an alpha test is enough;
// it also keeps geometry opaque from the path tracer's point of view, which
// behaves far better than alpha blending under Remix.
constexpr DWORD kAlphaRef = 128;

AlphaMode g_alphaMode = AlphaMode::Test;
DWORD g_alphaRef = kAlphaRef;

// Sand for the riverbed (RiverbedTileIndex): muddy harbour sand with a little
// grain and the odd darker pebble. Tileable, since the bed repeats it once per
// block, and generated from fixed numbers, so the texture - and with it the
// Remix hash a sand material would key on - is the same on every run.
uint32_t SandTexel(int x, int y) {
    auto hash = [](uint32_t a, uint32_t b) {
        uint32_t h = a * 0x8DA6B343u ^ b * 0xD8163841u ^ 0x5BD1E995u;
        h ^= h >> 13;
        h *= 0x5BD1E995u;
        return (h ^ (h >> 15)) & 0xFFFFu;
    };
    // Value noise on a lattice that divides the tile, so it wraps exactly.
    auto noise = [&](int cells, uint32_t seed) {
        const float fx = static_cast<float>(x) * cells / kTileSize;
        const float fy = static_cast<float>(y) * cells / kTileSize;
        const int x0 = static_cast<int>(fx), y0 = static_cast<int>(fy);
        const float tx = fx - x0, ty = fy - y0;
        const float sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty);
        auto at = [&](int cx, int cy) {
            return hash(static_cast<uint32_t>(cx % cells) + seed, static_cast<uint32_t>(cy % cells)) /
                   65535.0f;
        };
        const float top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx;
        const float bottom = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx;
        return top + (bottom - top) * sy;
    };
    const float ripple = noise(4, 11) * 0.5f + noise(8, 23) * 0.3f + noise(16, 37) * 0.2f;
    const float grain = hash(static_cast<uint32_t>(x), static_cast<uint32_t>(y) + 101u) / 65535.0f;
    float shade = 0.82f + 0.22f * ripple + 0.08f * (grain - 0.5f);
    if (noise(32, 53) > 0.86f) shade *= 0.72f;   // pebbles
    auto channel = [&](float base) {
        const float v = base * shade;
        return static_cast<uint32_t>(v < 0.0f ? 0.0f : (v > 255.0f ? 255.0f : v));
    };
    return 0xFF000000u | (channel(150.0f) << 16) | (channel(136.0f) << 8) | channel(104.0f);
}
}  // namespace

void RendererTrace(const char* format, ...) {
    if (!g_trace) return;
    char line[512];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    g_trace(line);
}

std::string g_hdTextureDir;
std::string g_tileDumpDir;
std::string g_tileStyle = "style";
int g_hdTileMax = 128;
void SetHdTileMaxSize(int size) { g_hdTileMax = size < 64 ? 64 : (size > 1024 ? 1024 : size); }
int g_anisotropy = 0;   // 0: 8 on a GPU, 1 on a software renderer; else the level asked for
void SetAnisotropy(int level) { g_anisotropy = level < 0 ? 0 : (level > 16 ? 16 : level); }
bool g_softwareGl = false;
void SetHdTextureDir(const char* dir) { g_hdTextureDir = dir ? dir : ""; }
// The photo-material set (tools/photoreal_tiles.py), one folder per style like the HD set;
// tried before it, never on an RTX Remix device (the Remix layer is keyed by the HD set's hashes).
std::string g_photoTextureDir;
void SetPhotoTextureDir(const char* dir) { g_photoTextureDir = dir ? dir : ""; }
std::string g_roadTextureDir;
void SetRoadTextureDir(const char* dir) { g_roadTextureDir = dir ? dir : ""; }
bool g_toneMatch = true;
void SetToneMatch(bool on) { g_toneMatch = on; }
void SetTileDumpDir(const char* dir) { g_tileDumpDir = dir ? dir : ""; }
bool g_waterEffect = true;
// FIX-CLASSIC-WATER-1: GTA2DX9_CLASSIC_ANIM_TILES=0 draws the classic view's water lids with the
// street views' world-space coordinates again (the flat one-colour river, for an A/B).
bool ClassicWaterUv() {
    static int on = -1;
    if (on < 0) {
        char b[8] = {};
        on = (GetEnvironmentVariableA("GTA2DX9_CLASSIC_ANIM_TILES", b, sizeof b) && b[0] == '0') ? 0 : 1;
    }
    return on != 0;
}
void SetWaterEffect(bool on) { g_waterEffect = on; }
bool g_windowGlow = true;
void SetWindowGlow(bool on) { g_windowGlow = on; }

// The glass of a wall tile, found from its pixels: dark, cool-toned texels in
// runs at least six wide (a pane, not a mortar line), and a tile counts as a
// window when they cover a twelfth to two thirds of it. The glow texture is
// warm room light through those texels, with a few panes dark, so the wall
// reads as lit from inside when the sun is low. Null for everything else.
#include "facade_windows.inc"

// FIX-WORLD-7 (pm26): where the facade pass grounded window glass on this tile (tools/facade_boxes.json).
// Returns false when the style is not covered (the colour-run detector decides alone); with the style
// covered, `boxes` holds this tile's window rectangles, empty for a tile that has none.
// GTA2DX9_WINDOW_GLOW_BOXES=0: the old detector alone, for A/B.
struct GlowBox { int x0, y0, x1, y1; };
bool FacadeWindowsFor(int tileIndex, std::vector<GlowBox>* boxes) {
    static int s_on = -1;
    if (s_on < 0) { const char* e = getenv("GTA2DX9_WINDOW_GLOW_BOXES"); s_on = (e && e[0] == '0') ? 0 : 1; }
    boxes->clear();
    if (!s_on) return false;
    bool covered = false;
    for (const char* s : kFacadeWindowStyles) covered = covered || g_tileStyle == s;
    if (!covered) return false;
    for (const FacadeWindowBox& b : kFacadeWindowBoxes)
        if (b.tile == tileIndex && g_tileStyle == b.style) boxes->push_back({b.x0, b.y0, b.x1, b.y1});
    return true;
}

IDirect3DTexture9* UploadGlowLevels(IDirect3DDevice9* device, const std::vector<uint32_t>& level);

// sky (may be null): FIX-WORLD-7 (pm12) the same glass by day, reflecting the sky: a cool level,
// lighter toward the top of each pane, added in the street views as the night glow fades.
IDirect3DTexture9* MakeWindowGlow(IDirect3DDevice9* device, const uint32_t* pixels, int tileIndex, IDirect3DTexture9** sky) {
    constexpr int n = kTileSize;
    if (sky) *sky = nullptr;
    std::vector<GlowBox> boxes;
    const bool boxed = FacadeWindowsFor(tileIndex, &boxes);
    if (boxed && boxes.empty()) return nullptr;   // no window on this wall tile (fans, girders, grime: pm26)
    std::vector<uint8_t> glass(static_cast<size_t>(n) * n, 0);
    int count = 0;
    for (int y = 0; y < n; ++y) {
        int run = 0;
        for (int x = 0; x <= n; ++x) {
            bool g = false;
            if (x < n) {
                const uint32_t px = pixels[static_cast<size_t>(y) * n + x];
                const int r = (px >> 16) & 0xFF, gg = (px >> 8) & 0xFF, b = px & 0xFF;
                const int lum = (r * 2 + gg * 3 + b) / 6;
                g = (px >> 24) != 0 && lum < 96 && b >= r - 4 && b >= gg - 12;
            }
            if (g) { ++run; continue; }
            if (run >= 6) for (int k = x - run; k < x; ++k) { glass[static_cast<size_t>(y) * n + k] = 1; ++count; }
            run = 0;
        }
    }
    // Vertical runs too: a pane is at least four rows tall.
    std::vector<uint8_t> keep(static_cast<size_t>(n) * n, 0);
    int kept = 0;
    for (int x = 0; x < n; ++x) {
        int run = 0;
        for (int y = 0; y <= n; ++y) {
            const bool g = y < n && glass[static_cast<size_t>(y) * n + x];
            if (g) { ++run; continue; }
            if (run >= 4) for (int k = y - run; k < y; ++k) { keep[static_cast<size_t>(k) * n + x] = 1; ++kept; }
            run = 0;
        }
    }
    if (boxed) {
        // Only the glass inside a grounded window: its dark texels, as before.
        kept = 0;
        for (int y = 0; y < n; ++y) for (int x = 0; x < n; ++x) {
            uint8_t& k = keep[static_cast<size_t>(y) * n + x];
            bool in = false;
            for (const GlowBox& b : boxes) in = in || (x >= b.x0 && x < b.x1 && y >= b.y0 && y < b.y1);
            k = k && in;
            kept += k;
        }
        if (kept < 12) return nullptr;
    } else if (kept < n * n / 12 || kept > n * n * 2 / 3) return nullptr;
    // FIX-WORLD-18 (qav76): inside a box the glass rule above tears a lit window into a tan stamp with black
    // holes: its hue gate drops the dark, slightly warm texels of a pane's interior and its run filter drops
    // bars and cracks (bil 488, the barred broken window; 491; 484). In a box the rule already lights (12+
    // glass texels, so no window that was dark starts to glow), every dark texel of the opening now takes the
    // glow by how dark it is (the room through the glass full, a bar or crack a darker line, the frame and
    // the brick round it nothing), pinholes are closed and the weight softened by half a 3x3 blur, so the
    // pane reads as lit from inside with its bars, not as a cut-out. GTA2DX9_GLOW_FILL=0: the old mask.
    static int s_fill = -1;
    if (s_fill < 0) { const char* e = getenv("GTA2DX9_GLOW_FILL"); s_fill = (e && e[0] == '0') ? 0 : 1; }
    std::vector<float> weight(static_cast<size_t>(n) * n, 0.0f);
    for (size_t i = 0; i < weight.size(); ++i) weight[i] = keep[i] ? 1.0f : 0.0f;
    if (boxed && s_fill) {
        std::vector<uint8_t> lit(static_cast<size_t>(n) * n, 0), cand(static_cast<size_t>(n) * n, 0);
        for (const GlowBox& b : boxes) {
            int inBox = 0;
            for (int y = b.y0; y < b.y1; ++y) for (int x = b.x0; x < b.x1; ++x) inBox += keep[static_cast<size_t>(y) * n + x];
            if (inBox < 12) continue;
            for (int y = std::max(0, b.y0); y < std::min(n, b.y1); ++y) for (int x = std::max(0, b.x0); x < std::min(n, b.x1); ++x) lit[static_cast<size_t>(y) * n + x] = 1;
        }
        std::vector<float> w0(static_cast<size_t>(n) * n, 0.0f);
        for (int y = 0; y < n; ++y) for (int x = 0; x < n; ++x) {
            const size_t i = static_cast<size_t>(y) * n + x;
            if (!lit[i]) continue;
            const uint32_t px = pixels[i];
            const int r = (px >> 16) & 0xFF, gg = (px >> 8) & 0xFF, b = px & 0xFF;
            const float lum = (r * 2 + gg * 3 + b) / 6.0f;
            if ((px >> 24) == 0 || lum >= 100.0f || b < r - 24 || b < gg - 20) continue;
            cand[i] = 1;
            w0[i] = 0.8f * std::min(1.0f, std::max(0.0f, (60.0f - lum) / 45.0f)) + 0.2f;
        }
        std::vector<float> w1 = w0;
        for (int y = 0; y < n; ++y) for (int x = 0; x < n; ++x) {
            const size_t i = static_cast<size_t>(y) * n + x;
            if (!lit[i] || cand[i]) continue;
            int c = 0; float sum = 0.0f;
            for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
                if (!dx && !dy) continue;
                const int xx = x + dx, yy = y + dy;
                if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue;
                const size_t j = static_cast<size_t>(yy) * n + xx;
                c += cand[j]; sum += w0[j];
            }
            if (c >= 5) w1[i] = 0.6f * sum / 8.0f;   // a pinhole in the glass
        }
        for (int y = 0; y < n; ++y) for (int x = 0; x < n; ++x) {
            const size_t i = static_cast<size_t>(y) * n + x;
            if (!lit[i]) continue;
            float acc = 0.0f;
            for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
                const int xx = x + dx, yy = y + dy;
                if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue;
                acc += w1[static_cast<size_t>(yy) * n + xx] * (dy ? 1.0f : 2.0f) * (dx ? 1.0f : 2.0f);
            }
            weight[i] = 0.5f * w1[i] + 0.5f * acc / 16.0f;
            keep[i] = weight[i] > 0.004f;
        }
    }
    std::vector<uint32_t> level(static_cast<size_t>(n) * n, 0xFF000000u);
    std::vector<uint32_t> skyLevel(static_cast<size_t>(n) * n, 0xFF000000u);
    uint32_t seed = 0x9E3779B9u ^ static_cast<uint32_t>(tileIndex * 2654435761u);
    auto rnd = [&]() { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return static_cast<float>(seed & 0xFFFF) / 65535.0f; };
    // A pane is a 16x16 cell of the tile; some are dark, some warm, some cool.
    float cell[16];
    for (float& c : cell) { const float r = rnd(); c = r < 0.3f ? 0.0f : (r < 0.8f ? 0.55f + 0.45f * rnd() : 0.35f); }
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            if (!keep[static_cast<size_t>(y) * n + x]) continue;
            float c = cell[(y / 16) * 4 + x / 16];
            // A soft falloff toward the pane's edges: curtains and depth.
            float ex = std::min(x % 16, 15 - x % 16) / 7.5f, ey = std::min(y % 16, 15 - y % 16) / 7.5f;
            float fromTop = (y % 16) / 15.0f;   // 0 at the pane's top, 1 at its foot (the sky reflection)
            if (boxed) {
                // One level per window (a room is lit or not), the falloff from the window's own edges.
                for (size_t i = 0; i < boxes.size(); ++i) {
                    const GlowBox& b = boxes[i];
                    if (x < b.x0 || x >= b.x1 || y < b.y0 || y >= b.y1) continue;
                    c = cell[i % 16];
                    const float hw = 0.5f * (b.x1 - b.x0), hh = 0.5f * (b.y1 - b.y0);
                    ex = std::min(x - b.x0 + 0.5f, b.x1 - x - 0.5f) / (std::max)(1.0f, std::min(7.5f, hw));
                    ey = std::min(y - b.y0 + 0.5f, b.y1 - y - 0.5f) / (std::max)(1.0f, std::min(7.5f, hh));
                    fromTop = (y - b.y0 + 0.5f) / (std::max)(1.0f, static_cast<float>(b.y1 - b.y0));
                    break;
                }
            }
            float f = c * std::min(1.0f, 0.35f + 0.65f * std::min(ex, ey));
            // FIX-WORLD-18: a filled window is lit a little more toward its top (the room's ceiling light).
            if (boxed && s_fill) f *= weight[static_cast<size_t>(y) * n + x] * (1.12f - 0.32f * std::min(1.0f, std::max(0.0f, fromTop)));
            f = std::min(1.0f, f);
            const int r = static_cast<int>(255.0f * f * 1.0f), g = static_cast<int>(255.0f * f * 0.78f), b = static_cast<int>(255.0f * f * 0.45f);
            level[static_cast<size_t>(y) * n + x] = 0xFF000000u | (r << 16) | (g << 8) | b;
            // By day: the sky's cool grey, 0.30 at a pane's top to 0.12 at its foot, softened at the edges.
            float s = (0.12f + 0.18f * (1.0f - std::min(1.0f, std::max(0.0f, fromTop)))) * std::min(1.0f, 0.5f + 0.5f * std::min(ex, ey));
            if (boxed && s_fill) s *= std::min(1.0f, weight[static_cast<size_t>(y) * n + x]);
            const int sr = static_cast<int>(255.0f * s * 0.80f), sg = static_cast<int>(255.0f * s * 0.90f), sb = static_cast<int>(255.0f * s);
            skyLevel[static_cast<size_t>(y) * n + x] = 0xFF000000u | (sr << 16) | (sg << 8) | sb;
        }
    }
    if (sky) *sky = UploadGlowLevels(device, skyLevel);
    return UploadGlowLevels(device, level);
}

IDirect3DTexture9* UploadGlowLevels(IDirect3DDevice9* device, const std::vector<uint32_t>& level) {
    constexpr int n = kTileSize;
    IDirect3DTexture9* texture = nullptr;
    if (FAILED(device->CreateTexture(n, n, 0, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) return nullptr;
    // Mips by box filter, so the glow fades cleanly with distance.
    std::vector<uint32_t> cur = level;
    int w = n;
    for (DWORD mip = 0; mip < texture->GetLevelCount(); ++mip) {
        D3DLOCKED_RECT rect;
        if (FAILED(texture->LockRect(mip, &rect, nullptr, 0))) break;
        for (int y = 0; y < w; ++y) memcpy(static_cast<uint8_t*>(rect.pBits) + static_cast<size_t>(y) * rect.Pitch, &cur[static_cast<size_t>(y) * w], static_cast<size_t>(w) * 4);
        texture->UnlockRect(mip);
        if (w == 1) break;
        const int h = w / 2;
        std::vector<uint32_t> next(static_cast<size_t>(h) * h);
        for (int y = 0; y < h; ++y) for (int x = 0; x < h; ++x) {
            int acc[3] = {0, 0, 0};
            for (int dy = 0; dy < 2; ++dy) for (int dx = 0; dx < 2; ++dx) {
                const uint32_t px = cur[static_cast<size_t>(y * 2 + dy) * w + x * 2 + dx];
                acc[0] += (px >> 16) & 0xFF; acc[1] += (px >> 8) & 0xFF; acc[2] += px & 0xFF;
            }
            next[static_cast<size_t>(y) * h + x] = 0xFF000000u | ((acc[0] / 4) << 16) | ((acc[1] / 4) << 8) | (acc[2] / 4);
        }
        cur.swap(next);
        w = h;
    }
    return texture;
}
void SetTileStyleName(const char* name) { g_tileStyle = name && *name ? name : "style"; }

namespace {
// 32-bit uncompressed TGA, either row order. Pixels come out top-down ARGB.
bool ReadTga(const std::string& path, std::vector<uint32_t>* pixels, int* width, int* height) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    uint8_t header[18];
    if (fread(header, 1, 18, f) != 18 || header[2] != 2 || header[16] != 32) { fclose(f); return false; }
    const int w = header[12] | (header[13] << 8), h = header[14] | (header[15] << 8);
    if (w <= 0 || h <= 0 || w > 4096 || h > 4096) { fclose(f); return false; }
    fseek(f, header[0], SEEK_CUR);
    std::vector<uint32_t> rows(static_cast<size_t>(w) * h);
    const bool ok = fread(rows.data(), 4, rows.size(), f) == rows.size();
    fclose(f);
    if (!ok) return false;
    const bool topDown = (header[17] & 0x20) != 0;
    pixels->resize(rows.size());
    for (int y = 0; y < h; ++y) {
        const int src = topDown ? y : (h - 1 - y);
        memcpy(&(*pixels)[static_cast<size_t>(y) * w], &rows[static_cast<size_t>(src) * w], static_cast<size_t>(w) * 4);
    }
    *width = w;
    *height = h;
    return true;
}

void WriteTga(const std::string& path, const uint32_t* pixels, int w, int h) {
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return;
    uint8_t header[18] = {};
    header[2] = 2;
    header[12] = static_cast<uint8_t>(w); header[13] = static_cast<uint8_t>(w >> 8);
    header[14] = static_cast<uint8_t>(h); header[15] = static_cast<uint8_t>(h >> 8);
    header[16] = 32;
    header[17] = 0x28;   // 8 alpha bits, top-down
    fwrite(header, 1, 18, f);
    fwrite(pixels, 4, static_cast<size_t>(w) * h, f);
    fclose(f);
}

char g_hdName[64];
const char* TileFileName(int tile) {
    snprintf(g_hdName, sizeof(g_hdName), "tile_%04d.tga", tile);
    return g_hdName;
}
const char* TileDdsFileName(int tile) {
    snprintf(g_hdName, sizeof(g_hdName), "tile_%04d.dds", tile);
    return g_hdName;
}

// A block-compressed DDS (DXT1 or DXT5, full mip chain) as tools/pack_textures_dds.py
// writes it: 128-byte header, then the levels top down, each one tightly packed
// rows of 4x4 blocks (8 bytes a block for DXT1, 16 for DXT5).
struct DdsImage {
    int width = 0, height = 0, mips = 0;
    D3DFORMAT format = D3DFMT_UNKNOWN;
    int blockBytes = 0;
    std::vector<uint8_t> data;   // the levels, back to back
    size_t LevelBytes(int level) const {
        const int w = std::max(1, width >> level), h = std::max(1, height >> level);
        return static_cast<size_t>((w + 3) / 4) * ((h + 3) / 4) * blockBytes;
    }
};

bool ReadDds(const std::string& path, DdsImage* out) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    uint8_t header[128];
    if (fread(header, 1, 128, f) != 128 || memcmp(header, "DDS ", 4) != 0) { fclose(f); return false; }
    auto u32 = [&](int at) { return static_cast<uint32_t>(header[at]) | (header[at + 1] << 8) | (header[at + 2] << 16) | (static_cast<uint32_t>(header[at + 3]) << 24); };
    const uint32_t flags = u32(8);
    out->height = static_cast<int>(u32(12));
    out->width = static_cast<int>(u32(16));
    out->mips = (flags & 0x20000) ? static_cast<int>(u32(28)) : 1;
    if (out->mips < 1) out->mips = 1;
    const uint32_t pfFlags = u32(80);
    const uint32_t fourcc = u32(84);
    if (!(pfFlags & 0x4)) { fclose(f); return false; }                 // DDPF_FOURCC only
    if (fourcc == 0x31545844u) { out->format = D3DFMT_DXT1; out->blockBytes = 8; }        // "DXT1"
    else if (fourcc == 0x35545844u) { out->format = D3DFMT_DXT5; out->blockBytes = 16; }  // "DXT5"
    else { fclose(f); return false; }
    if (out->width <= 0 || out->height <= 0 || out->width > 4096 || out->height > 4096) { fclose(f); return false; }
    size_t total = 0;
    for (int i = 0; i < out->mips; ++i) total += out->LevelBytes(i);
    out->data.resize(total);
    const bool ok = fread(out->data.data(), 1, total, f) == total;
    fclose(f);
    return ok;
}

// The street views' tone match (defect pm-road-tiles-patchwork-tone-seams): each HD tile came
// out of the upscalers with its own mean brightness and hue, so neighbouring ground tiles step
// visibly where the game's own 64 px art matches. The street-view copy of a ground tile is
// scaled toward the game tile's mean (times the district's overall grade) by scaling the DXT
// colour endpoints: the shipped files, the classic view and Remix keep the tile as it is.
void DxtDecodeColours(const uint8_t* b, bool dxt1, float c[4][3], bool* fourth) {
    const uint16_t c0 = static_cast<uint16_t>(b[0] | (b[1] << 8)), c1 = static_cast<uint16_t>(b[2] | (b[3] << 8));
    auto rgb = [](uint16_t v, float* o) {
        o[0] = ((v >> 11) & 31) * (255.0f / 31.0f); o[1] = ((v >> 5) & 63) * (255.0f / 63.0f); o[2] = (v & 31) * (255.0f / 31.0f);
    };
    rgb(c0, c[0]); rgb(c1, c[1]);
    *fourth = true;
    for (int k = 0; k < 3; ++k) {
        if (!dxt1 || c0 > c1) { c[2][k] = (2.0f * c[0][k] + c[1][k]) / 3.0f; c[3][k] = (c[0][k] + 2.0f * c[1][k]) / 3.0f; }
        else { c[2][k] = 0.5f * (c[0][k] + c[1][k]); c[3][k] = 0.0f; *fourth = false; }
    }
}

// The base colour of a DDS: the mean of its texels at the 16 px level (or the smallest of at
// least 4 px) whose brightness is within 18 levels of the median, so the paint, a kerb or a
// manhole does not count; 0..255. False for a cutout (transparent texels).
bool DdsBaseRgb(const DdsImage& dds, float out[3]) {
    int level = 0;
    for (int l = 0; l < dds.mips; ++l) { level = l; if ((std::max)(1, dds.width >> l) <= 16) break; }
    while (level > 0 && (std::max)(1, dds.width >> level) < 4) --level;
    size_t at = 0;
    for (int l = 0; l < level; ++l) at += dds.LevelBytes(l);
    const size_t bytes = dds.LevelBytes(level);
    if (at + bytes > dds.data.size() || !bytes) return false;
    const bool dxt1 = dds.format == D3DFMT_DXT1;
    std::vector<std::array<float, 3>> texels;
    for (size_t o = at; o + dds.blockBytes <= at + bytes; o += dds.blockBytes) {
        const uint8_t* b = &dds.data[o + (dxt1 ? 0 : 8)];
        float c[4][3]; bool fourth;
        DxtDecodeColours(b, dxt1, c, &fourth);
        const uint32_t idx = static_cast<uint32_t>(b[4]) | (b[5] << 8) | (b[6] << 16) | (static_cast<uint32_t>(b[7]) << 24);
        for (int t = 0; t < 16; ++t) {
            const int i = (idx >> (2 * t)) & 3;
            if (i == 3 && !fourth) return false;   // DXT1 transparent texel: a cutout
            texels.push_back({c[i][0], c[i][1], c[i][2]});
        }
    }
    if (texels.empty()) return false;
    std::vector<float> lum;
    for (const auto& t : texels) lum.push_back(0.299f * t[0] + 0.587f * t[1] + 0.114f * t[2]);
    std::vector<float> sorted = lum;
    std::nth_element(sorted.begin(), sorted.begin() + sorted.size() / 2, sorted.end());
    const float median = sorted[sorted.size() / 2];
    double sum[3] = {0, 0, 0}; int n = 0;
    for (size_t i = 0; i < texels.size(); ++i) {
        if (std::fabs(lum[i] - median) > 18.0f) continue;
        for (int k = 0; k < 3; ++k) sum[k] += texels[i][k];
        ++n;
    }
    if (n < static_cast<int>(texels.size()) / 3) return false;
    for (int k = 0; k < 3; ++k) out[k] = static_cast<float>(sum[k] / n);
    return true;
}

// Scales every colour endpoint of every level by f (per channel). A DXT1 block keeps its
// mode: c0 > c1 (four colours) stays so, or its third and fourth colours would turn into a
// transparent texel.
void DdsTint(DdsImage* dds, const float f[3]) {
    const bool dxt1 = dds->format == D3DFMT_DXT1;
    auto scale = [&](uint16_t v) {
        int r = static_cast<int>(((v >> 11) & 31) * f[0] + 0.5f), g = static_cast<int>(((v >> 5) & 63) * f[1] + 0.5f), b = static_cast<int>((v & 31) * f[2] + 0.5f);
        r = (std::min)(31, (std::max)(0, r)); g = (std::min)(63, (std::max)(0, g)); b = (std::min)(31, (std::max)(0, b));
        return static_cast<uint16_t>((r << 11) | (g << 5) | b);
    };
    for (size_t o = 0; o + dds->blockBytes <= dds->data.size(); o += dds->blockBytes) {
        uint8_t* b = &dds->data[o + (dxt1 ? 0 : 8)];
        const uint16_t c0 = static_cast<uint16_t>(b[0] | (b[1] << 8)), c1 = static_cast<uint16_t>(b[2] | (b[3] << 8));
        uint16_t n0 = scale(c0), n1 = scale(c1);
        if (dxt1 && c0 > c1 && n0 <= n1) {
            if (n1 > 0) { n0 = n1; n1 = static_cast<uint16_t>(n1 - 1); } else { n0 = 1; n1 = 0; }
        } else if (dxt1 && c0 <= c1 && n0 > n1) {
            n0 = n1;   // keep the three-colour (cutout) mode
        }
        b[0] = static_cast<uint8_t>(n0 & 0xFF); b[1] = static_cast<uint8_t>(n0 >> 8);
        b[2] = static_cast<uint8_t>(n1 & 0xFF); b[3] = static_cast<uint8_t>(n1 >> 8);
    }
}

uint64_t TileContentHash(const uint32_t* pixels) {
    uint64_t key = 0xCBF29CE484222325ULL;
    for (size_t i = 0; i < static_cast<size_t>(kTileSize) * kTileSize; ++i) {
        key ^= pixels[i];
        key *= 0x100000001B3ULL;
    }
    return key;
}

// GTA2's water is one animated tile group - tile 608 and the frames after it
// in every district's style - drawn as a flat animated texture. The street
// views give those faces ripples and a sky tint; the classic view does not.
bool IsWaterTileIndex(int tile) { return tile >= 608 && tile <= 619; }

// Tileable value noise for the water: a few octaves summed, wrapped, grey,
// with a mip chain so distant water does not shimmer.
IDirect3DTexture9* MakeWaterNoise(IDirect3DDevice9* device) {
    const int n = 128;
    std::vector<float> v(static_cast<size_t>(n) * n, 0.0f);
    uint32_t seed = 0x9E3779B9u;
    auto rnd = [&]() { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return static_cast<float>(seed & 0xFFFF) / 65535.0f; };
    for (int octave = 0; octave < 4; ++octave) {
        const int cells = 4 << octave;             // 4, 8, 16, 32 lattice points across
        const float amp = 1.0f / static_cast<float>(1 << octave);
        std::vector<float> lattice(static_cast<size_t>(cells) * cells);
        for (float& l : lattice) l = rnd();
        for (int y = 0; y < n; ++y) {
            for (int x = 0; x < n; ++x) {
                const float fx = static_cast<float>(x) * cells / n, fy = static_cast<float>(y) * cells / n;
                const int x0 = static_cast<int>(fx) % cells, y0 = static_cast<int>(fy) % cells;
                const int x1 = (x0 + 1) % cells, y1 = (y0 + 1) % cells;
                float tx = fx - std::floor(fx), ty = fy - std::floor(fy);
                tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty);
                const float a = lattice[static_cast<size_t>(y0) * cells + x0], b = lattice[static_cast<size_t>(y0) * cells + x1];
                const float c = lattice[static_cast<size_t>(y1) * cells + x0], d = lattice[static_cast<size_t>(y1) * cells + x1];
                v[static_cast<size_t>(y) * n + x] += amp * ((a + (b - a) * tx) * (1.0f - ty) + (c + (d - c) * tx) * ty);
            }
        }
    }
    float lo = 1e9f, hi = -1e9f;
    for (float f : v) { lo = std::min(lo, f); hi = std::max(hi, f); }
    std::vector<uint32_t> level(static_cast<size_t>(n) * n);
    for (size_t i = 0; i < level.size(); ++i) {
        // Kept to a gentle range about mid-grey: the stages add it signed, so
        // this is the ripple's contrast (about +-20 % of the water's colour).
        const int g = static_cast<int>((0.30f + 0.40f * (v[i] - lo) / std::max(hi - lo, 1e-6f)) * 255.0f + 0.5f);
        level[i] = 0xFF000000u | (g << 16) | (g << 8) | g;
    }
    IDirect3DTexture9* texture = nullptr;
    if (FAILED(device->CreateTexture(n, n, 0, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) return nullptr;
    int w = n;
    for (DWORD mip = 0; mip < texture->GetLevelCount(); ++mip) {
        D3DLOCKED_RECT rect;
        if (FAILED(texture->LockRect(mip, &rect, nullptr, 0))) break;
        for (int y = 0; y < w; ++y) memcpy(static_cast<uint8_t*>(rect.pBits) + static_cast<size_t>(y) * rect.Pitch, &level[static_cast<size_t>(y) * w], static_cast<size_t>(w) * 4);
        texture->UnlockRect(mip);
        if (w == 1) break;
        std::vector<uint32_t> half(static_cast<size_t>(w / 2) * (w / 2));
        for (int y = 0; y < w / 2; ++y) {
            for (int x = 0; x < w / 2; ++x) {
                int g = 0;
                for (int dy = 0; dy < 2; ++dy) for (int dx = 0; dx < 2; ++dx) g += level[static_cast<size_t>(y * 2 + dy) * w + (x * 2 + dx)] & 0xFF;
                g /= 4;
                half[static_cast<size_t>(y) * (w / 2) + x] = 0xFF000000u | (g << 16) | (g << 8) | g;
            }
        }
        level.swap(half);
        w /= 2;
    }
    return texture;
}

// Creates a default-pool compressed texture from the DDS, through a
// system-memory staging copy that is released at once. Levels above the size
// cap are skipped, so hd_tile_max keeps working for DDS sets. Returns nullptr
// if the device will not take the format, in which case the caller falls back.
IDirect3DTexture9* CreateDdsTexture(IDirect3DDevice9* device, const DdsImage& dds, int maxSize) {
    int first = 0;
    size_t offset = 0;
    while (first < dds.mips - 1 && (std::max(1, dds.width >> first) > maxSize || std::max(1, dds.height >> first) > maxSize)) {
        offset += dds.LevelBytes(first);
        ++first;
    }
    const int w = std::max(1, dds.width >> first), h = std::max(1, dds.height >> first);
    const int levels = dds.mips - first;
    IDirect3DTexture9* texture = nullptr;
    IDirect3DTexture9* staging = nullptr;
    if (FAILED(device->CreateTexture(w, h, levels, 0, dds.format, D3DPOOL_DEFAULT, &texture, nullptr)) ||
        FAILED(device->CreateTexture(w, h, levels, 0, dds.format, D3DPOOL_SYSTEMMEM, &staging, nullptr))) {
        if (staging) staging->Release();
        if (texture) texture->Release();
        return nullptr;
    }
    bool ok = true;
    for (int level = 0; level < levels && ok; ++level) {
        const int lw = std::max(1, w >> level), lh = std::max(1, h >> level);
        const int blocksX = (lw + 3) / 4, blocksY = (lh + 3) / 4;
        const size_t rowBytes = static_cast<size_t>(blocksX) * dds.blockBytes;
        D3DLOCKED_RECT rect;
        if (FAILED(staging->LockRect(level, &rect, nullptr, 0))) { ok = false; break; }
        const uint8_t* src = dds.data.data() + offset;
        for (int y = 0; y < blocksY; ++y) {
            memcpy(static_cast<uint8_t*>(rect.pBits) + static_cast<size_t>(y) * rect.Pitch, src + y * rowBytes, rowBytes);
        }
        staging->UnlockRect(level);
        offset += dds.LevelBytes(first + level);
    }
    if (ok) ok = SUCCEEDED(device->UpdateTexture(staging, texture));
    staging->Release();
    if (!ok) { texture->Release(); return nullptr; }
    return texture;
}
}  // namespace

void SetAlphaMode(AlphaMode mode) { g_alphaMode = mode; }
AlphaMode GetAlphaMode() { return g_alphaMode; }
void SetAlphaRef(int ref) { g_alphaRef = static_cast<DWORD>(ref < 1 ? 1 : (ref > 254 ? 254 : ref)); }
int GetAlphaRef() { return static_cast<int>(g_alphaRef); }

namespace {

void SetMatrix(IDirect3DDevice9* device, D3DTRANSFORMSTATETYPE state, const Mat4& matrix) {
    D3DMATRIX d3dMatrix;
    memcpy(&d3dMatrix, matrix.m, sizeof(d3dMatrix));
    device->SetTransform(state, &d3dMatrix);
}

}  // namespace

void SetRendererTrace(void (*sink)(const char*)) { g_trace = sink; }

Renderer::~Renderer() { Shutdown(); }

void Renderer::Shutdown() {
    post_.Release();
    if (keptSurface_) { keptSurface_->Release(); keptSurface_ = nullptr; }
    if (keptTexture_) { keptTexture_->Release(); keptTexture_ = nullptr; }
    keptValid_ = false;
    weather_.Release();
    water_.Release();
    ReleaseResources();
    batches_.clear();
    if (device_) {
        device_->Release();
        device_ = nullptr;
    }
    if (d3d_) {
        d3d_->Release();
        d3d_ = nullptr;
    }
}

void Renderer::ReleaseResources() {
    post_.ReleaseWorld();
    sky_.Release();
    if (waterNoise_) { waterNoise_->Release(); waterNoise_ = nullptr; }
    for (IDirect3DTexture9* t : windowGlow_) if (t) t->Release();
    windowGlow_.clear();
    for (IDirect3DTexture9* t : windowSky_) if (t) t->Release();
    windowSky_.clear();
    // An animated tile's slot points at a frame owned by tileFrames_, so those
    // must not be released twice. Everything else in textures_ is owned here.
    for (IDirect3DTexture9* texture : textures_) {
        if (!texture) continue;
        bool ownedByFrames = false;
        for (const auto& frame : tileFrames_) {
            if (frame.second == texture) {
                ownedByFrames = true;
                break;
            }
        }
        if (!ownedByFrames) texture->Release();
    }
    textures_.clear();
    for (IDirect3DTexture9* t : photoTextures_) if (t) t->Release();
    photoTextures_.clear();
    roadTile_.clear();
    tileAnimated_.clear();
    animatedPhotoFrame_.clear();
    for (auto& frame : tileFrames_) {
        if (frame.second) frame.second->Release();
    }
    tileFrames_.clear();
    if (vertexBuffer_) {
        vertexBuffer_->Release();
        vertexBuffer_ = nullptr;
    }
    if (indexBuffer_) {
        indexBuffer_->Release();
        indexBuffer_ = nullptr;
    }
}

// Drop the level's geometry, and nothing else.
//
// GTA2 frees its map when it returns to the menu, and the renderer used to keep
// drawing the last level regardless: DrawWorld's only guard is that a vertex
// buffer exists, and one did. So quitting to the menu left a frozen cityscape on
// screen with the menu drawn over it - and under Remix that geometry was still
// in the scene, still being path traced, still lit.
//
// Deliberately not ReleaseResources: the device, the window and the tile
// textures all outlive a level, and tearing them down here would mean rebuilding
// the device every time someone backs out to the menu.
void Renderer::ReleaseWorld() {
    post_.ReleaseWorld();
    batches_.clear();
    if (savedTarget_) {
        savedTarget_->Release();
        savedTarget_ = nullptr;
    }
    if (uiSurface_) {
        uiSurface_->Release();
        uiSurface_ = nullptr;
    }
    if (uiTexture_) {
        uiTexture_->Release();
        uiTexture_ = nullptr;
    }
    uiClearPending_ = true;
    if (keptSurface_) { keptSurface_->Release(); keptSurface_ = nullptr; }
    if (keptTexture_) { keptTexture_->Release(); keptTexture_ = nullptr; }
    keptValid_ = false;
    if (vertexBuffer_) {
        vertexBuffer_->Release();
        vertexBuffer_ = nullptr;
    }
    if (indexBuffer_) {
        indexBuffer_->Release();
        indexBuffer_ = nullptr;
    }
}

bool Renderer::Initialize(HWND window, int width, int height, std::string* error) {
    width_ = width;
    height_ = height;

    // Kept across a retry: creating the interface is what starts RTX Remix's
    // runtime, and asking for it twice would start it twice.
    if (!d3d_) {
        Trace("Direct3DCreate9...");
        d3d_ = CreateD3D9();
        if (!d3d_) {
            *error = "Direct3DCreate9 failed";
            return false;
        }
        Trace("Direct3DCreate9 -> %p", d3d_);
    }

    // Only the first attempt is traced. Under RTX Remix this runs once a frame
    // until the device takes, and one line per attempt would bury the log.
    const bool trace = deviceAttempts_++ == 0;

    // A windowed backbuffer has to match the current display mode, and GTA2's
    // Glide wrapper may have switched the desktop to another depth while it
    // runs, so adopt whatever the adapter is in right now.
    D3DDISPLAYMODE displayMode = {};
    const HRESULT modeResult = d3d_->GetAdapterDisplayMode(D3DADAPTER_DEFAULT, &displayMode);
    if (trace) {
        Trace("display mode hr=0x%08lX %ux%u format=%d", static_cast<unsigned long>(modeResult),
              displayMode.Width, displayMode.Height, static_cast<int>(displayMode.Format));
    }

    D3DPRESENT_PARAMETERS pp = {};
    pp.BackBufferWidth = width;
    pp.BackBufferHeight = height;
    pp.BackBufferFormat = displayMode.Format != D3DFMT_UNKNOWN ? displayMode.Format : D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = window;
    pp.Windowed = TRUE;
    pp.EnableAutoDepthStencil = TRUE;
    pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_ONE;

    if (trace) {
        Trace("CreateDevice hwnd=%p %dx%d windowed=%d fmt=%d", window, width, height,
              (int)pp.Windowed, static_cast<int>(pp.BackBufferFormat));
    }
    HRESULT hr = d3d_->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, window,
                                    D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &device_);
    if (FAILED(hr)) {
        hr = d3d_->CreateDevice(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, window,
                                D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &device_);
    }
    if (SUCCEEDED(hr)) {
        // A software GL renderer behind wined3d (llvmpipe, softpipe, swrast):
        // anisotropic filtering costs it up to 8 texture reads a pixel over the
        // whole world, which a GPU does for nothing.
        D3DADAPTER_IDENTIFIER9 id = {};
        if (SUCCEEDED(d3d_->GetAdapterIdentifier(D3DADAPTER_DEFAULT, 0, &id))) {
            std::string desc = std::string(id.Description) + " " + id.Driver;
            for (char& c : desc) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
            g_softwareGl = desc.find("llvmpipe") != std::string::npos || desc.find("softpipe") != std::string::npos ||
                           desc.find("swrast") != std::string::npos || desc.find("software") != std::string::npos;
            Trace("adapter: %s (%s)%s", id.Description, id.Driver, g_softwareGl ? ", software renderer" : "");
        }
    }
    if (FAILED(hr)) {
        // Not necessarily fatal. RTX Remix hands the interface back before the
        // 64-bit runtime behind it can serve a device, and turns everything down
        // with D3DERR_INVALIDCALL until it can; it only gets there once the game
        // has run its own loop for a moment. The caller retries per frame.
        char message[160];
        snprintf(message, sizeof(message), "CreateDevice failed (hr=0x%08lX, display format=%d)",
                 static_cast<unsigned long>(hr), static_cast<int>(displayMode.Format));
        *error = message;
        return false;
    }
    Trace("device created on attempt %d", deviceAttempts_);
    remixDevice_ = g_remixD3D9;
    post_.Init(device_, width_, height_, remixDevice_);
    weather_.Init(device_, remixDevice_);
    water_.Init(device_, remixDevice_);
    SetSkyRemix(remixDevice_);
    return true;
}

bool Renderer::UploadWorld(const WorldMesh& mesh, const Style& style, std::string* error) {
    if (mesh.vertices.empty()) {
        *error = "world mesh is empty";
        return false;
    }
    ReleaseResources();
    batches_ = mesh.batches;
    {
        int classicWater = 0;
        for (const TileBatch& b : batches_) classicWater += b.classicIndices ? 1 : 0;
        Trace("classic water (FIX-CLASSIC-WATER-1): %d batch(es) of water lids drawn with the game's per-block coordinates in the classic view%s",
              classicWater, ClassicWaterUv() ? "" : " - OFF (GTA2DX9_CLASSIC_ANIM_TILES=0: the street views' world coordinates, one flat colour)");
    }
    // FIX-TRANSITION-ART: the street lights, one group per light: the stacked pole segments at one
    // spot, and an arm or head whose solid starts within a block of that pole's top.
    streetPoles_ = mesh.streetPoles;
    poleGroup_.assign(streetPoles_.size(), -1);
    poleGroups_.clear();
    polesOfBatch_.assign(batches_.size(), {});
    anyPoleFaded_ = false;
    {
        std::map<std::pair<int, int>, int> column;
        for (size_t i = 0; i < streetPoles_.size(); ++i) {
            const StreetPole& p = streetPoles_[i];
            if (p.arm) continue;
            const auto key = std::make_pair(static_cast<int>(std::lround(p.x * 20.0f)), static_cast<int>(std::lround(p.z * 20.0f)));
            auto it = column.find(key);
            if (it == column.end()) {
                it = column.emplace(key, static_cast<int>(poleGroups_.size())).first;
                poleGroups_.push_back({p.x, p.z, p.lo, p.hi, p.r});
            }
            PoleGroup& g = poleGroups_[static_cast<size_t>(it->second)];
            g.lo = (std::min)(g.lo, p.lo); g.hi = (std::max)(g.hi, p.hi); g.r = (std::max)(g.r, p.r);
            poleGroup_[i] = it->second;
        }
        const size_t poleOnly = poleGroups_.size();
        for (size_t i = 0; i < streetPoles_.size(); ++i) {
            const StreetPole& p = streetPoles_[i];
            if (!p.arm) continue;
            int best = -1; float bestD = 1e9f;
            for (size_t k = 0; k < poleOnly; ++k) {
                const PoleGroup& g = poleGroups_[k];
                const float d = std::hypot(g.x - p.x, g.z - p.z);
                if (d < 1.0f + p.r && std::fabs(p.lo - g.hi) < 1.2f && d < bestD) { bestD = d; best = static_cast<int>(k); }
            }
            if (best < 0) { best = static_cast<int>(poleGroups_.size()); poleGroups_.push_back({p.x, p.z, p.lo, p.hi, p.r}); }
            poleGroup_[i] = best;
        }
        for (size_t i = 0; i < streetPoles_.size(); ++i)
            if (streetPoles_[i].batch >= 0 && static_cast<size_t>(streetPoles_[i].batch) < polesOfBatch_.size())
                polesOfBatch_[static_cast<size_t>(streetPoles_[i].batch)].push_back(static_cast<int>(i));
        for (auto& list : polesOfBatch_)
            std::sort(list.begin(), list.end(), [&](int a, int b) { return streetPoles_[static_cast<size_t>(a)].indexStart < streetPoles_[static_cast<size_t>(b)].indexStart; });
        Trace("street lights: %zu pole segments, arms and classic cards in %zu lights (move-occluder fade, FIX-TRANSITION-ART)", streetPoles_.size(), poleGroups_.size());
    }

    const UINT vertexBytes = static_cast<UINT>(mesh.vertices.size() * sizeof(Vertex));
    if (FAILED(device_->CreateVertexBuffer(vertexBytes, D3DUSAGE_WRITEONLY, kWorldFvf,
                                           D3DPOOL_MANAGED, &vertexBuffer_, nullptr))) {
        *error = "CreateVertexBuffer failed";
        return false;
    }
    void* dest = nullptr;
    vertexBuffer_->Lock(0, 0, &dest, 0);
    memcpy(dest, mesh.vertices.data(), vertexBytes);
    vertexBuffer_->Unlock();

    const UINT indexBytes = static_cast<UINT>(mesh.indices.size() * sizeof(uint32_t));
    if (FAILED(device_->CreateIndexBuffer(indexBytes, D3DUSAGE_WRITEONLY, D3DFMT_INDEX32,
                                          D3DPOOL_MANAGED, &indexBuffer_, nullptr))) {
        *error = "CreateIndexBuffer failed";
        return false;
    }
    indexBuffer_->Lock(0, 0, &dest, 0);
    memcpy(dest, mesh.indices.data(), indexBytes);
    indexBuffer_->Unlock();

    // FIX-PERF-9: each batch's ranges cut into runs of 64 triangles with their boxes, for the street
    // views' frustum test in DrawWorld (the order of the triangles is never changed).
    cullChunks_.clear();
    for (int set = 0; set < 2; ++set) batchChunks_[set].assign(batches_.size(), {0u, 0u});
    for (size_t b = 0; b < batches_.size(); ++b) {
        const TileBatch& batch = batches_[b];
        for (int set = 0; set < 2; ++set) {
            if (set == 1 && !batch.streetIndices) continue;
            const uint32_t first = set ? batch.streetIndexStart : batch.indexStart;
            const uint32_t count = (set ? batch.streetIndexCount : batch.indexCount) / 3u * 3u;
            batchChunks_[set][b].first = static_cast<uint32_t>(cullChunks_.size());
            for (uint32_t at = 0; at < count; at += 192u) {
                const uint32_t n = (std::min)(192u, count - at);
                float lo[3] = {1e30f, 1e30f, 1e30f}, hi[3] = {-1e30f, -1e30f, -1e30f};
                for (uint32_t i = 0; i < n; ++i) {
                    const uint32_t vi = mesh.indices[first + at + i];
                    if (vi >= mesh.vertices.size()) continue;
                    const Vertex& v = mesh.vertices[vi];
                    lo[0] = (std::min)(lo[0], v.x); lo[1] = (std::min)(lo[1], v.y); lo[2] = (std::min)(lo[2], v.z);
                    hi[0] = (std::max)(hi[0], v.x); hi[1] = (std::max)(hi[1], v.y); hi[2] = (std::max)(hi[2], v.z);
                }
                if (lo[0] > hi[0]) { lo[0] = lo[1] = lo[2] = 0.0f; hi[0] = hi[1] = hi[2] = 1e6f; }   // never culled
                CullChunk c;
                c.cx = 0.5f * (lo[0] + hi[0]); c.cy = 0.5f * (lo[1] + hi[1]); c.cz = 0.5f * (lo[2] + hi[2]);
                c.ex = 0.5f * (hi[0] - lo[0]) + 0.01f; c.ey = 0.5f * (hi[1] - lo[1]) + 0.01f; c.ez = 0.5f * (hi[2] - lo[2]) + 0.01f;
                c.start = first + at;
                c.count = n;
                cullChunks_.push_back(c);
            }
            batchChunks_[set][b].second = static_cast<uint32_t>(cullChunks_.size()) - batchChunks_[set][b].first;
        }
    }
    Trace("world view cull: %zu batches, %zu chunks of up to 64 triangles (FIX-PERF-9)", batches_.size(), cullChunks_.size());

    // One texture per tile keeps Remix's texture hashes stable and per-tile
    // replaceable, instead of hiding every surface behind one atlas hash. Two
    // slots past the end for the seal under the world and the riverbed, which
    // have no tile of their own - see SealTileIndex and RiverbedTileIndex.
    const int sealTile = SealTileIndex(style);
    const int riverbedTile = RiverbedTileIndex(style);
    textures_.assign(static_cast<size_t>(riverbedTile) + 1, nullptr);
    warmCursor_ = 0;
    hdTiles_ = 0;
    hdDdsTiles_ = 0;
    hdFailed_ = 0;
    const std::string hdDir = g_hdTextureDir.empty() ? "" : g_hdTextureDir + "\\" + g_tileStyle;
    const std::string dumpDir = g_tileDumpDir.empty() ? "" : g_tileDumpDir + "\\" + g_tileStyle;
    hdDir_ = hdDir;
    photoDir_ = (g_photoTextureDir.empty() || remixDevice_) ? "" : g_photoTextureDir + "\\" + g_tileStyle;
    photoTiles_ = 0;
    roadDir_ = (g_roadTextureDir.empty() || remixDevice_) ? "" : g_roadTextureDir + "\\" + g_tileStyle;
    roadTiles_ = 0;
    for (IDirect3DTexture9* t : photoTextures_) if (t) t->Release();
    photoTextures_.assign(textures_.size(), nullptr);
    roadTile_.assign(textures_.size(), 0);
    tileAnimated_.assign(textures_.size(), 0);
    animatedPhotoFrame_.assign(textures_.size(), -1);
    tileByContent_.clear();
    for (int i = 0; i < style.TileCount(); ++i) {
        const Tile& t = style.GetTile(i);
        if (t.pixels.size() == static_cast<size_t>(kTileSize) * kTileSize) tileByContent_.emplace(TileContentHash(t.pixels.data()), i);
    }
    waterTile_.assign(textures_.size(), 0);
    for (int i = 0; i < style.TileCount() && i < static_cast<int>(waterTile_.size()); ++i) {
        if (IsWaterTileIndex(i)) waterTile_[i] = 1;
    }
    // FIX-WORLD-16 qav59: the sparse lattices (see SetSeeThroughNearClip), from the 64 px art's alpha.
    sparseLattice_.assign(textures_.size(), 0);
    {
        int sparse = 0;
        for (int i = 0; i < style.TileCount() && i < static_cast<int>(sparseLattice_.size()); ++i) {
            const Tile& t = style.GetTile(i);
            if (t.pixels.size() != static_cast<size_t>(kTileSize) * kTileSize) continue;
            int opaque = 0;
            for (uint32_t px : t.pixels) opaque += (px >> 24) != 0;
            const int n = kTileSize * kTileSize;
            if (opaque > n / 50 && opaque < n * 3 / 10) { sparseLattice_[static_cast<size_t>(i)] = 1; ++sparse; }
        }
        Trace("tiles: %d sparse see-through lattices (first-person near clip, FIX-WORLD-16)", sparse);
    }
    for (IDirect3DTexture9* t : windowGlow_) if (t) t->Release();
    windowGlow_.assign(textures_.size(), nullptr);
    for (IDirect3DTexture9* t : windowSky_) if (t) t->Release();
    windowSky_.assign(textures_.size(), nullptr);
    {
        // Only tiles the map uses on walls (never as lids) can be windows.
        std::vector<uint8_t> wallOnly(textures_.size(), 0), lidUse(textures_.size(), 0);
        for (const TileBatch& b : batches_) {
            if (b.tile < 0 || b.tile >= static_cast<int>(textures_.size()) || b.streetOnly) continue;
            if (b.lidFaces) lidUse[static_cast<size_t>(b.tile)] = 1; else wallOnly[static_cast<size_t>(b.tile)] = 1;
        }
        int windows = 0;
        for (int i = 0; i < style.TileCount() && i < static_cast<int>(windowGlow_.size()); ++i) {
            if (!wallOnly[static_cast<size_t>(i)] || lidUse[static_cast<size_t>(i)] || IsWaterTileIndex(i)) continue;
            const Tile& t = style.GetTile(i);
            if (t.pixels.size() != static_cast<size_t>(kTileSize) * kTileSize) continue;
            windowGlow_[static_cast<size_t>(i)] = MakeWindowGlow(device_, t.pixels.data(), i, &windowSky_[static_cast<size_t>(i)]);
            if (windowGlow_[static_cast<size_t>(i)]) ++windows;
        }
        {
            std::vector<GlowBox> probe;
            const bool boxed = FacadeWindowsFor(-1, &probe);
            Trace("windows: %d wall tiles glow from inside when the sun is low (%s)", windows,
                  boxed ? "glass inside the facade pass's window boxes, FIX-WORLD-7 pm26" : "colour-run detector alone");
        }
    }
    if (!waterNoise_) waterNoise_ = MakeWaterNoise(device_);
    water_.BuildShore(mesh, waterTile_);
    if (!dumpDir.empty()) {
        CreateDirectoryA(g_tileDumpDir.c_str(), nullptr);
        CreateDirectoryA(dumpDir.c_str(), nullptr);
    }
    // The street views' tone match (see DdsTint): the unpainted base of every asphalt road
    // tile (the lid of a road block) the street views show is brought to the district's median asphalt colour (at most
    // 12% per channel), so the road reads as one surface instead of tile-sized tone blocks.
    // Pavements, grass, roofs and cutouts are left as they are.
    streetTint_.assign(textures_.size() * 3, 1.0f);
    toneTiles_ = 0;
    if (g_toneMatch && !remixDevice_ && !hdDir.empty()) {
        LARGE_INTEGER t0, t1, freq;
        QueryPerformanceCounter(&t0);
        std::vector<uint8_t> lid(textures_.size(), 0);   // the road blocks' lids only
        for (int t : mesh.roadLidTiles)
            if (t >= 0 && t < static_cast<int>(lid.size())) lid[static_cast<size_t>(t)] = 1;
        struct Base { int tile; float rgb[3]; };
        std::vector<Base> asphalt;
        for (int i = 0; i < style.TileCount() && i < static_cast<int>(lid.size()); ++i) {
            if (!lid[static_cast<size_t>(i)] || IsWaterTileIndex(i) || i == sealTile || i == riverbedTile) continue;
            DdsImage dds;
            const std::string name = std::string("\\") + TileDdsFileName(i);
            if (!((!roadDir_.empty() && ReadDds(roadDir_ + name, &dds)) || (!photoDir_.empty() && ReadDds(photoDir_ + name, &dds)) ||
                  ReadDds(hdDir + name, &dds))) continue;
            Base m;
            m.tile = i;
            if (!DdsBaseRgb(dds, m.rgb)) continue;
            const float lum = 0.299f * m.rgb[0] + 0.587f * m.rgb[1] + 0.114f * m.rgb[2];
            const float chroma = (std::max)({m.rgb[0], m.rgb[1], m.rgb[2]}) - (std::min)({m.rgb[0], m.rgb[1], m.rgb[2]});
            // Asphalt: dark to mid grey with no strong hue (blue-green in Downtown and Industrial,
            // warm brown in Residential); a sand track or a grass verge the map calls road is not.
            if (lum < 40.0f || lum > 120.0f || chroma > 36.0f) continue;
            asphalt.push_back(m);
        }
        if (asphalt.size() >= 8) {
            float target[3];
            for (int k = 0; k < 3; ++k) {
                std::vector<float> v;
                for (const Base& m : asphalt) v.push_back(m.rgb[k]);
                std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end());
                target[k] = v[v.size() / 2];
            }
            for (const Base& m : asphalt) {
                float f[3]; bool any = false;
                for (int k = 0; k < 3; ++k) {
                    f[k] = (std::min)(1.12f, (std::max)(0.88f, target[k] / (std::max)(m.rgb[k], 1.0f)));
                    if (std::fabs(f[k] - 1.0f) > 0.01f) any = true;
                }
                if (!any) continue;
                for (int k = 0; k < 3; ++k) streetTint_[static_cast<size_t>(m.tile) * 3 + k] = f[k];
                ++toneTiles_;
            }
            QueryPerformanceCounter(&t1); QueryPerformanceFrequency(&freq);
            Trace("tone match: %d of %zu asphalt road tiles tinted to the median asphalt %.0f %.0f %.0f, %.0f ms",
                  toneTiles_, asphalt.size(), target[0], target[1], target[2], 1000.0 * (t1.QuadPart - t0.QuadPart) / freq.QuadPart);
        }
    }
    std::vector<uint32_t> hd;
    for (const TileBatch& batch : batches_) {
        if (textures_[batch.tile]) continue;

        // High-resolution artwork for this tile, if the folder has it: a
        // block-compressed DDS with mips first (tools/pack_textures_dds.py), then
        // the older uncompressed TGA.
        if (!hdDir.empty() && batch.tile != sealTile && batch.tile != riverbedTile) {
            int w = 0, h = 0;
            if (IDirect3DTexture9* texture = LoadHdTileTexture(batch.tile)) {
                textures_[batch.tile] = texture;
                photoTextures_[batch.tile] = LoadPhotoTileTexture(batch.tile);
                ++hdTiles_;
                ++hdDdsTiles_;
                continue;
            }
            if (ReadTga(hdDir + "\\" + TileFileName(batch.tile), &hd, &w, &h)) {
                // Down to the cap by halving (a box filter), alpha included.
                while ((w > g_hdTileMax || h > g_hdTileMax) && (w % 2) == 0 && (h % 2) == 0) {
                    std::vector<uint32_t> half(static_cast<size_t>(w / 2) * (h / 2));
                    for (int y = 0; y < h / 2; ++y) {
                        for (int x = 0; x < w / 2; ++x) {
                            uint32_t acc[4] = {0, 0, 0, 0};
                            for (int dy = 0; dy < 2; ++dy) for (int dx = 0; dx < 2; ++dx) {
                                const uint32_t p = hd[static_cast<size_t>(y * 2 + dy) * w + (x * 2 + dx)];
                                acc[0] += (p >> 24) & 0xFF; acc[1] += (p >> 16) & 0xFF; acc[2] += (p >> 8) & 0xFF; acc[3] += p & 0xFF;
                            }
                            half[static_cast<size_t>(y) * (w / 2) + x] = ((acc[0] / 4) << 24) | ((acc[1] / 4) << 16) | ((acc[2] / 4) << 8) | (acc[3] / 4);
                        }
                    }
                    hd.swap(half);
                    w /= 2; h /= 2;
                }
                // Default pool through a system-memory staging copy that is
                // released at once: the managed pool would keep a second copy of
                // every tile in the game's 32-bit address space.
                IDirect3DTexture9* texture = nullptr;
                IDirect3DTexture9* staging = nullptr;
                if (SUCCEEDED(device_->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &texture, nullptr)) &&
                    SUCCEEDED(device_->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &staging, nullptr))) {
                    D3DLOCKED_RECT rect;
                    if (SUCCEEDED(staging->LockRect(0, &rect, nullptr, 0))) {
                        for (int y = 0; y < h; ++y) {
                            memcpy(static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch, &hd[static_cast<size_t>(y) * w],
                                   static_cast<size_t>(w) * 4);
                        }
                        staging->UnlockRect(0);
                        if (SUCCEEDED(device_->UpdateTexture(staging, texture))) {
                            staging->Release();
                            textures_[batch.tile] = texture;
                            ++hdTiles_;
                            continue;
                        }
                    }
                }
                if (staging) staging->Release();
                if (texture) texture->Release();
                ++hdFailed_;
            }
        }

        IDirect3DTexture9* texture = nullptr;
        if (FAILED(device_->CreateTexture(kTileSize, kTileSize, 1, 0, D3DFMT_A8R8G8B8,
                                          D3DPOOL_MANAGED, &texture, nullptr))) {
            *error = "CreateTexture failed";
            return false;
        }
        if (hdFailed_ == 1 && !hdDir.empty() && !hdFailLogged_) {
            hdFailLogged_ = true;
            Trace("hd tiles: a file in %s could not be uploaded (out of texture memory, or the device refuses the format); its tile uses the game's artwork", hdDir.c_str());
        }
        D3DLOCKED_RECT rect;
        texture->LockRect(0, &rect, nullptr, 0);
        if (batch.tile == sealTile) {
            // Opaque black, and a whole tile of it: the seal is meant to absorb,
            // and giving Remix a real texture rather than an untextured draw
            // keeps it one identifiable material that can be replaced.
            for (int y = 0; y < kTileSize; ++y) {
                uint32_t* row = reinterpret_cast<uint32_t*>(
                    static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch);
                for (int x = 0; x < kTileSize; ++x) row[x] = 0xFF000000u;
            }
        } else if (batch.tile == riverbedTile) {
            for (int y = 0; y < kTileSize; ++y) {
                uint32_t* row = reinterpret_cast<uint32_t*>(
                    static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch);
                for (int x = 0; x < kTileSize; ++x) row[x] = SandTexel(x, y);
            }
        } else {
            const Tile& tile = style.GetTile(batch.tile);
            for (int y = 0; y < kTileSize; ++y) {
                memcpy(static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch,
                       &tile.pixels[static_cast<size_t>(y) * kTileSize], kTileSize * 4);
            }
            // The dump the upscaler works from: the tile as the game shows it.
            if (!dumpDir.empty()) {
                WriteTga(dumpDir + "\\" + TileFileName(batch.tile), tile.pixels.data(), kTileSize, kTileSize);
            }
        }
        texture->UnlockRect(0);
        textures_[batch.tile] = texture;
    }
    // An animation frame's photo variant by content: the frame may resolve to another
    // tile number with the same artwork, one that has no photo copy of its own.
    photoByContent_.clear();
    for (int i = 0; i < style.TileCount() && i < static_cast<int>(photoTextures_.size()); ++i) {
        const Tile& t = style.GetTile(i);
        if (photoTextures_[static_cast<size_t>(i)] && t.pixels.size() == static_cast<size_t>(kTileSize) * kTileSize)
            photoByContent_.emplace(TileContentHash(t.pixels.data()), i);
    }
    if (hdTiles_ > 0 || hdFailed_ > 0) {
        Trace("hd tiles: %d loaded (%d block-compressed DDS with mips, cap %d px), %d failed, of %zu tile textures",
              hdTiles_, hdDdsTiles_, g_hdTileMax, hdFailed_, textures_.size());
        Trace("photo tiles: %d of them from %s", photoTiles_, photoDir_.empty() ? "(off)" : photoDir_.c_str());
        Trace("road-marking tiles: %d of them from %s (street views only)", roadTiles_, roadDir_.empty() ? "(off)" : roadDir_.c_str());
    }
    post_.BuildWorld(mesh, style, vertexBuffer_);
    return true;
}

IDirect3DTexture9* Renderer::LoadHdTileTexture(int tile) {
    if (hdDir_.empty()) return nullptr;
    DdsImage dds;
    if (!ReadDds(hdDir_ + "\\" + TileDdsFileName(tile), &dds)) return nullptr;
    IDirect3DTexture9* texture = CreateDdsTexture(device_, dds, g_hdTileMax);
    if (!texture) ++hdFailed_;
    return texture;
}

IDirect3DTexture9* Renderer::LoadPhotoTileTexture(int tile) {
    DdsImage dds;
    const size_t at = static_cast<size_t>(tile) * 3;
    const float* tint = (at + 2 < streetTint_.size() &&
                         (streetTint_[at] != 1.0f || streetTint_[at + 1] != 1.0f || streetTint_[at + 2] != 1.0f)) ? &streetTint_[at] : nullptr;
    auto make = [&](int* counter) -> IDirect3DTexture9* {
        if (tint) DdsTint(&dds, tint);
        IDirect3DTexture9* texture = CreateDdsTexture(device_, dds, g_hdTileMax);
        if (texture) ++*counter;
        return texture;
    };
    // The re-authored road markings first (clean paint over the photo asphalt), then the photo set,
    // then (only to carry the tone match) the HD tile itself.
    if (!roadDir_.empty() && ReadDds(roadDir_ + "\\" + TileDdsFileName(tile), &dds)) {
        if (IDirect3DTexture9* texture = make(&roadTiles_)) {
            if (tile >= 0) {
                if (roadTile_.size() <= static_cast<size_t>(tile)) roadTile_.resize(static_cast<size_t>(tile) + 1, 0);
                roadTile_[static_cast<size_t>(tile)] = 1;
            }
            return texture;
        }
    }
    if (!photoDir_.empty() && ReadDds(photoDir_ + "\\" + TileDdsFileName(tile), &dds)) {
        if (IDirect3DTexture9* texture = make(&photoTiles_)) return texture;
    }
    int toneOnly = 0;
    if (tint && !hdDir_.empty() && ReadDds(hdDir_ + "\\" + TileDdsFileName(tile), &dds)) return make(&toneOnly);
    return nullptr;
}

void Renderer::UpdateTileTexture(int tile, const uint32_t* pixels) {
    if (!HasTileTexture(tile) || !pixels) return;
    if (tile < static_cast<int>(tileAnimated_.size())) tileAnimated_[tile] = 1;

    // GTA2 animates a tile - fans, screens, water, traffic lights - by changing
    // the artwork behind a fixed tile number. Writing the new frame into the
    // texture this tile already has, which is what this used to do, gives RTX
    // Remix one texture whose content changes: a single entry in the picker,
    // animating, with no way to replace an individual frame.
    //
    // So each distinct frame gets a texture of its own and the tile is pointed at
    // it instead. A frame that comes round again resolves to the same object and
    // therefore the same hash, so the cost is bounded by how much distinct
    // artwork exists rather than by how long the game runs.
    const uint64_t key = TileContentHash(pixels);

    // The street views' photo variant of the frame, when the frame is a tile that has one
    // (not for water, whose animation keeps the HD frames it always had). Sticky: the neon
    // also shows frames that are no tile of the style (the game rewrites the record's
    // pixels), and those keep the last photo frame rather than the smeared HD one.
    {
        const auto frameTile = photoByContent_.find(key);
        const bool water = tile < static_cast<int>(waterTile_.size()) && waterTile_[tile];
        if (!water && frameTile != photoByContent_.end() && frameTile->second >= 0 &&
            frameTile->second < static_cast<int>(photoTextures_.size()) && photoTextures_[frameTile->second] &&
            tile < static_cast<int>(animatedPhotoFrame_.size()))
            animatedPhotoFrame_[tile] = frameTile->second;
    }
    const auto existing = tileFrames_.find(key);
    if (existing != tileFrames_.end()) {
        textures_[tile] = existing->second;
        return;
    }

    // The frame is a tile of the style (the ANIM table lists frames by tile
    // number), so when that tile has high-resolution artwork the animation
    // plays in high resolution too: water, neon, screens. The texture the slot
    // held is kept under its own content so it is found again when the
    // animation comes back round, and is released with the frames.
    const auto known = tileByContent_.find(key);
    if (known != tileByContent_.end()) {
        if (IDirect3DTexture9* hd = LoadHdTileTexture(known->second)) {
            tileFrames_[key] = hd;
            textures_[tile] = hd;
            return;
        }
    }

    IDirect3DTexture9* frame = nullptr;
    if (FAILED(device_->CreateTexture(kTileSize, kTileSize, 1, 0, D3DFMT_A8R8G8B8,
                                      D3DPOOL_MANAGED, &frame, nullptr))) {
        return;
    }
    D3DLOCKED_RECT rect;
    if (FAILED(frame->LockRect(0, &rect, nullptr, 0))) {
        frame->Release();
        return;
    }
    for (int y = 0; y < kTileSize; ++y) {
        memcpy(static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch,
               pixels + static_cast<size_t>(y) * kTileSize, kTileSize * 4);
    }
    frame->UnlockRect(0);

    tileFrames_[key] = frame;   // owns it from here
    textures_[tile] = frame;
}

void Renderer::CycleCullMode() {
    cullMode_ = cullMode_ == D3DCULL_CCW ? D3DCULL_CW
                : cullMode_ == D3DCULL_CW ? D3DCULL_NONE
                                          : D3DCULL_CCW;
}

void Renderer::ApplyFixedFunctionState() {
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device_->SetRenderState(D3DRS_CULLMODE, cullMode_);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_FILLMODE, wireframe_ ? D3DFILL_WIREFRAME : D3DFILL_SOLID);

    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);

    device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    // The game's own 64 px tiles are magnified with point sampling, which is
    // their look. High-resolution artwork is filtered: trilinear over its mip
    // chain with 8x anisotropy, so a pavement seen edge-on in first person stays
    // sharp instead of smearing into the horizon.
    if (hdTiles_ > 0) {
        const int aniso = g_anisotropy > 0 ? g_anisotropy : (g_softwareGl ? 1 : 8);
        device_->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device_->SetSamplerState(0, D3DSAMP_MINFILTER, aniso > 1 ? D3DTEXF_ANISOTROPIC : D3DTEXF_LINEAR);
        device_->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
        device_->SetSamplerState(0, D3DSAMP_MAXANISOTROPY, static_cast<DWORD>(aniso > 1 ? aniso : 1));
    } else {
        device_->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        device_->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device_->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    }
}

void Renderer::MarkDrawsAsScreenUi() {
    if (!device_) return;
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device_->SetTransform(D3DTS_PROJECTION, &identity);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
}

void Renderer::MarkDrawsAsNotUi() {
    if (!device_) return;
    // A perspective shape - w taken from z, nothing left in [3][3] - so this can
    // never read as orthographic, whatever the projection was before. In the
    // front end no world has set one, and D3D's default is the identity, which
    // with the overlay's Z writes off would have made every menu draw "UI".
    D3DMATRIX perspective = {};
    perspective._11 = perspective._22 = perspective._33 = 1.0f;
    perspective._34 = 1.0f;
    perspective._44 = 0.0f;
    device_->SetTransform(D3DTS_PROJECTION, &perspective);
}

// The 2D layer the game believes it is painting into. See the note in the
// header for why it is kept rather than cleared.
//
// Everything drawn into it must not look like UI to RTX Remix. The layer is the
// size of the back buffer, which makes it a "primary" target in Remix's eyes,
// and the first UI draw into a primary target is where Remix pastes the whole
// path traced frame - into our layer, over whatever the menu had kept in it.
// With the UI texture list and the pre-transformed switch gone from rtx.conf,
// the projection is the only thing left that could say UI, so it is pinned here.
bool Renderer::BeginUiLayer(bool clearNow) {
    if (!device_) return false;
    if (!uiTexture_) {
        if (FAILED(device_->CreateTexture(width_, height_, 1, D3DUSAGE_RENDERTARGET,
                                          D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &uiTexture_,
                                          nullptr))) {
            uiTexture_ = nullptr;
            return false;
        }
        if (FAILED(uiTexture_->GetSurfaceLevel(0, &uiSurface_))) {
            uiTexture_->Release();
            uiTexture_ = nullptr;
            uiSurface_ = nullptr;
            return false;
        }
        uiClearPending_ = true;
    }
    if (FAILED(device_->GetRenderTarget(0, &savedTarget_))) {
        savedTarget_ = nullptr;
        return false;
    }
    if (FAILED(device_->SetRenderTarget(0, uiSurface_))) {
        savedTarget_->Release();
        savedTarget_ = nullptr;
        return false;
    }
    MarkDrawsAsNotUi();
    // Transparent, not black: the world is drawn underneath this, so everywhere
    // the game has not painted has to let it through. The game's own clear is
    // opaque black because in its model there is nothing underneath.
    if (clearNow || uiClearPending_) {
        device_->Clear(0, nullptr, D3DCLEAR_TARGET, 0x00000000, 1.0f, 0);
        uiClearPending_ = false;
    }
    return true;
}

void Renderer::EndUiLayer() {
    if (!device_ || !savedTarget_) return;
    device_->SetRenderTarget(0, savedTarget_);
    savedTarget_->Release();
    savedTarget_ = nullptr;
    if (!uiTexture_) return;

    struct Composite {
        float x, y, z, rhw;
        float u, v;
    };
    const float w = static_cast<float>(width_);
    const float h = static_cast<float>(height_);
    const Composite quad[4] = {{-0.5f, -0.5f, 0.0f, 1.0f, 0.0f, 0.0f},
                               {w - 0.5f, -0.5f, 0.0f, 1.0f, 1.0f, 0.0f},
                               {w - 0.5f, h - 0.5f, 0.0f, 1.0f, 1.0f, 1.0f},
                               {-0.5f, h - 0.5f, 0.0f, 1.0f, 0.0f, 1.0f}};

    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    // The layer is premultiplied (see Overlay::Flush): its colour is added as it
    // is, and its alpha says how much of the frame underneath to keep.
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device_->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    // And this quad is the frame's UI: the first draw Remix takes for UI, so the
    // path traced image goes down on the back buffer here and the layer is laid
    // over it. Without this the composite is just another pre-transformed draw,
    // which NVIDIA's 1.5.2 rasterizes before the path traced image and then
    // covers with it at Present - the UI that came and went.
    MarkDrawsAsScreenUi();
    device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device_->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    device_->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    device_->SetTexture(0, uiTexture_);
    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device_->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    device_->DrawPrimitiveUP(D3DPT_TRIANGLEFAN, 2, quad, sizeof(Composite));

    device_->SetTexture(0, nullptr);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
}

bool Renderer::BeginFrame() {
    stats_ = RenderStats{};
    if (!device_) return false;
    // Black, because that is what the game asks for. GTA2's menu paints only the
    // left third of the screen plus its text - traced from the 2D stream, the
    // whole front end is one blit at (0,0)-(278,480) and a row of glyph quads -
    // and everything else is meant to be the colour the screen was cleared to.
    // Vid_ClearScreen(ctx, 0,0,0,0,0, 640,480) is the game saying so; the video
    // proxy no longer forwards it, so this is the only clear left.
    // GTA2DX9_CLEAR_MAGENTA=1 (the city sweep's diagnostic): clear to magenta
    // instead, so that anything the frame leaves undrawn is unmistakable in a
    // screenshot (with the sky off, a magenta patch below the horizon in a
    // street view is a hole in the world).
    static int magenta = -1;
    if (magenta < 0) { char buf[8] = {}; magenta = GetEnvironmentVariableA("GTA2DX9_CLEAR_MAGENTA", buf, sizeof buf) && buf[0] == '1'; }
    device_->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER,
                   magenta ? D3DCOLOR_XRGB(255, 0, 255) : D3DCOLOR_XRGB(0, 0, 0), 1.0f, 0);
    return SUCCEEDED(device_->BeginScene());
}

void Renderer::KeepFrame() {
    keptValid_ = false;
    if (!device_ || remixDevice_ || keptFailed_) return;
    IDirect3DSurface9* back = nullptr;
    if (FAILED(device_->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) || !back) return;
    D3DSURFACE_DESC bd = {};
    back->GetDesc(&bd);
    if (keptTexture_) {
        D3DSURFACE_DESC kd = {};
        keptSurface_->GetDesc(&kd);
        if (kd.Width != bd.Width || kd.Height != bd.Height || kd.Format != bd.Format) {
            keptSurface_->Release(); keptSurface_ = nullptr;
            keptTexture_->Release(); keptTexture_ = nullptr;
        }
    }
    if (!keptTexture_) {
        // The back buffer's own format, so the copy is the same bytes (no conversion).
        if (FAILED(device_->CreateTexture(bd.Width, bd.Height, 1, D3DUSAGE_RENDERTARGET, bd.Format, D3DPOOL_DEFAULT,
                                          &keptTexture_, nullptr)) ||
            FAILED(keptTexture_->GetSurfaceLevel(0, &keptSurface_))) {
            if (keptTexture_) { keptTexture_->Release(); keptTexture_ = nullptr; }
            keptSurface_ = nullptr;
            keptFailed_ = true;
            Trace("view dissolve: no %ux%u format %d copy target; the switch cuts as before", bd.Width, bd.Height,
                  static_cast<int>(bd.Format));
            back->Release();
            return;
        }
    }
    keptValid_ = SUCCEEDED(device_->StretchRect(back, nullptr, keptSurface_, nullptr, D3DTEXF_NONE));
    back->Release();
}

void Renderer::DrawKeptFrame(float alpha) {
    if (!device_ || !keptValid_ || !keptTexture_ || alpha <= 0.0f) return;
    D3DSURFACE_DESC kd = {};
    keptSurface_->GetDesc(&kd);
    struct Composite {
        float x, y, z, rhw;
        float u, v;
    };
    const float w = static_cast<float>(kd.Width);
    const float h = static_cast<float>(kd.Height);
    // Pixel centres on texel centres (D3D9's half-pixel offset) with point sampling:
    // every pixel takes exactly its own texel.
    const Composite quad[4] = {{-0.5f, -0.5f, 0.0f, 1.0f, 0.0f, 0.0f},
                               {w - 0.5f, -0.5f, 0.0f, 1.0f, 1.0f, 0.0f},
                               {w - 0.5f, h - 0.5f, 0.0f, 1.0f, 1.0f, 1.0f},
                               {-0.5f, h - 0.5f, 0.0f, 1.0f, 0.0f, 1.0f}};
    const int a = alpha >= 1.0f ? 255 : static_cast<int>(alpha * 255.0f + 0.5f);
    if (a <= 0) return;
    device_->SetVertexShader(nullptr);
    device_->SetPixelShader(nullptr);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    device_->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    device_->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    // Fully opaque: a plain copy, no blend arithmetic at all.
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, a < 255 ? TRUE : FALSE);
    device_->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device_->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(a, 255, 255, 255));
    device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device_->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    device_->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    device_->SetSamplerState(0, D3DSAMP_SRGBTEXTURE, FALSE);
    device_->SetTexture(0, keptTexture_);
    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TFACTOR);
    device_->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
    device_->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device_->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    device_->DrawPrimitiveUP(D3DPT_TRIANGLEFAN, 2, quad, sizeof(Composite));
    device_->SetTexture(0, nullptr);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
}

long Renderer::KeptFrameDifference() {
    if (!device_ || !keptValid_ || !keptSurface_) return -1;
    IDirect3DSurface9* back = nullptr;
    if (FAILED(device_->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) || !back) return -1;
    D3DSURFACE_DESC d = {};
    back->GetDesc(&d);
    IDirect3DSurface9* sysA = nullptr;
    IDirect3DSurface9* sysB = nullptr;
    long diff = -1;
    if (SUCCEEDED(device_->CreateOffscreenPlainSurface(d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &sysA, nullptr)) &&
        SUCCEEDED(device_->CreateOffscreenPlainSurface(d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &sysB, nullptr)) &&
        SUCCEEDED(device_->GetRenderTargetData(back, sysA)) && SUCCEEDED(device_->GetRenderTargetData(keptSurface_, sysB))) {
        D3DLOCKED_RECT ra = {}, rb = {};
        if (SUCCEEDED(sysA->LockRect(&ra, nullptr, D3DLOCK_READONLY))) {
            if (SUCCEEDED(sysB->LockRect(&rb, nullptr, D3DLOCK_READONLY))) {
                diff = 0;
                for (UINT y = 0; y < d.Height; ++y) {
                    const uint32_t* a = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(ra.pBits) + y * ra.Pitch);
                    const uint32_t* b = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(rb.pBits) + y * rb.Pitch);
                    for (UINT x = 0; x < d.Width; ++x) diff += ((a[x] ^ b[x]) & 0x00FFFFFFu) != 0;
                }
                sysB->UnlockRect();
            }
            sysA->UnlockRect();
        }
    }
    if (sysA) sysA->Release();
    if (sysB) sysB->Release();
    back->Release();
    return diff;
}

void Renderer::EndFrame() {
    if (!device_) return;
    device_->EndScene();
    device_->Present(nullptr, nullptr, nullptr, nullptr);
}

// FIX-TRANSITION-ART: see Renderer::streetPoles_. The same rule as the street props' move fade
// (live_geometry.cpp DrawProps): nearer the lens than the hero, and its nearest part wider than 4.5 %
// of the frame's height (3.5 % to stay faded), or its width times the share of the frame its post runs
// across over 0.003 (0.0022 to stay faded): a mast from the top edge down to the median, 1 % wide across
// half the frame, or 2 % across a fifth of it. Either only if its post enters the middle of the frame.
void Renderer::UpdatePoleFades(const Camera& camera) {
    static int s_on = -1;
    if (s_on < 0) { const char* e = getenv("GTA2DX9_MOVE_POLE_FADE"); s_on = (e && e[0] == '0') ? 0 : 1;
                    Trace("street lights: move-occluder fade %s (GTA2DX9_MOVE_POLE_FADE)", s_on ? "on" : "off"); }
    if (!s_on || poleGroups_.empty()) return;
    if (!moveOccMoving_ && !anyPoleFaded_) return;
    const float aspect = static_cast<float>(width_) / static_cast<float>((std::max)(1, height_));
    const Mat4 view = camera.ViewMatrix(), proj = camera.ProjectionMatrix(aspect);
    float vp[4][4];
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float acc = 0.0f;
        for (int k = 0; k < 4; ++k) acc += view.m[r][k] * proj.m[k][c];
        vp[r][c] = acc;
    }
    const Vec3 eye = camera.Position();
    const float vd[3] = {view.m[0][2], view.m[1][2], view.m[2][2]};
    const float proj22 = std::fabs(proj.m[1][1]);
    const float heroDepth = (moveOccHero_.x - eye.x) * vd[0] + (moveOccHero_.y + 0.3f - eye.y) * vd[1] + (moveOccHero_.z - eye.z) * vd[2];
    auto span = [&](float x, float y0, float y1, float z, float bx = 1.0f, float by = 1.0f) -> float {
        float c[2][4];
        for (int e = 0; e < 2; ++e) {
            const float y = e ? y1 : y0;
            for (int k = 0; k < 4; ++k) c[e][k] = x * vp[0][k] + y * vp[1][k] + z * vp[2][k] + vp[3][k];
        }
        constexpr float kW = 0.05f;
        if (c[0][3] < kW && c[1][3] < kW) return 0.0f;
        for (int e = 0; e < 2; ++e) {
            if (c[e][3] >= kW) continue;
            const float t = (kW - c[e][3]) / (c[1 - e][3] - c[e][3]);
            for (int k = 0; k < 4; ++k) c[e][k] += (c[1 - e][k] - c[e][k]) * t;
        }
        const float ax = c[0][0] / c[0][3], ay = c[0][1] / c[0][3], qx = c[1][0] / c[1][3], qy = c[1][1] / c[1][3];
        float t0 = 0.0f, t1 = 1.0f;
        const float dx = qx - ax, dy = qy - ay;
        const float pq[4][2] = {{-dx, ax + bx}, {dx, bx - ax}, {-dy, ay + by}, {dy, by - ay}};
        for (const auto& e : pq) {
            if (std::fabs(e[0]) < 1e-6f) { if (e[1] < 0.0f) return 0.0f; continue; }
            const float r = e[1] / e[0];
            if (e[0] < 0.0f) t0 = (std::max)(t0, r); else t1 = (std::min)(t1, r);
            if (t0 > t1) return 0.0f;
        }
        return (std::max)(1e-4f, 0.5f * (std::max)(std::fabs(dx), std::fabs(dy)) * (t1 - t0));
    };
    bool any = false;
    for (PoleGroup& g : poleGroups_) {
        bool occ = false;
        const bool held = g.alpha < 0.98f;
        if (moveOccMoving_) {
            const float ex = g.x - eye.x, ez = g.z - eye.z;
            if (ex * ex + ez * ez < 100.0f) {
                const float cy = (std::min)(g.hi, (std::max)(g.lo, eye.y));
                const float dy = cy - eye.y;
                const float depth = ex * vd[0] + dy * vd[1] + ez * vd[2];
                if (depth < heroDepth && depth > -0.5f) {
                    const float r = (std::max)(g.r, 0.03f);
                    const float dn = (std::max)(0.02f, std::sqrt(ex * ex + dy * dy + ez * ez) - r);
                    const float width = r * proj22 / dn;
                    float sp = 0.0f;
                    // Only what crosses the middle of the frame (x 20-80 %, y 10-90 %), where the move
                    // looks; a light at the frame's edge is scenery passing by, unless it alone covers
                    // more than 15 % of the frame's height.
                    const bool central = width > 0.15f || span(g.x, g.lo, g.hi, g.z, 0.6f, 0.8f) > 0.0f;
                    occ = central && width > (held ? 0.035f : 0.045f);
                    if (central && !occ && width > 0.004f) { sp = span(g.x, g.lo, g.hi, g.z); occ = width * sp > (held ? 0.0022f : 0.003f); }
                    if (occ && !held && poleFadeLogs_ < 200) {
                        ++poleFadeLogs_;
                        Trace("street lights: move occluder at %.2f,%.2f (%.2f..%.2f) faded (nearest %.2f from the lens, %.1f%% of the frame's height wide, across %.0f%% of the frame, hero %.2f ahead)",
                              g.x, 256.0f - g.z, g.lo, g.hi, dn, 100.0f * width, 100.0f * sp, heroDepth);
                    }
                }
            }
        }
        const float target = occ ? 0.0f : 1.0f;
        g.alpha = target > g.alpha ? (std::min)(target, g.alpha + 0.17f) : (std::max)(target, g.alpha - 0.17f);
        if (g.alpha < 0.999f) any = true;
    }
    anyPoleFaded_ = any;
}

void Renderer::DrawWorld(const Camera& camera) {
    // Nothing to draw until the game has a world loaded; the frame is still
    // cleared and presented so menus have something to sit on.
    if (!device_ || !vertexBuffer_) return;

    ApplyFixedFunctionState();
    SetMatrix(device_, D3DTS_WORLD, Identity());
    SetMatrix(device_, D3DTS_VIEW, camera.ViewMatrix());
    SetMatrix(device_, D3DTS_PROJECTION,
              camera.ProjectionMatrix(static_cast<float>(width_) / static_cast<float>(height_)));
    if (post_.Active()) {
        const float aspect = static_cast<float>(width_) / static_cast<float>(height_);
        post_.SetCamera(camera.ViewMatrix(), camera.ProjectionMatrix(aspect), camera.Position(), camera.FovY(), aspect);
    }

    device_->SetFVF(kWorldFvf);
    device_->SetStreamSource(0, vertexBuffer_, 0, sizeof(Vertex));
    device_->SetIndices(indexBuffer_);

    // The street views' atmosphere. Fog stays on for the live geometry that
    // follows (EndWorldShading turns it off); the sun light is this pass only.
    if (shading_.fog) {
        const auto bits = [](float v) { DWORD d; memcpy(&d, &v, sizeof d); return d; };
        device_->SetRenderState(D3DRS_FOGENABLE, TRUE);
        device_->SetRenderState(D3DRS_FOGCOLOR, D3DCOLOR_XRGB(static_cast<int>(shading_.fogColour.x * 255.0f + 0.5f),
                                                              static_cast<int>(shading_.fogColour.y * 255.0f + 0.5f),
                                                              static_cast<int>(shading_.fogColour.z * 255.0f + 0.5f)));
        device_->SetRenderState(D3DRS_FOGVERTEXMODE, D3DFOG_NONE);
        device_->SetRenderState(D3DRS_FOGTABLEMODE, D3DFOG_LINEAR);
        device_->SetRenderState(D3DRS_FOGSTART, bits(shading_.fogStart));
        device_->SetRenderState(D3DRS_FOGEND, bits(shading_.fogEnd));
        device_->SetRenderState(D3DRS_RANGEFOGENABLE, FALSE);
    } else {
        device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    }
    if (shading_.sun) {
        D3DLIGHT9 sun = {};
        sun.Type = D3DLIGHT_DIRECTIONAL;
        sun.Diffuse.r = shading_.sunColour.x;
        sun.Diffuse.g = shading_.sunColour.y;
        sun.Diffuse.b = shading_.sunColour.z;
        sun.Diffuse.a = 1.0f;
        sun.Direction.x = -shading_.sunDir.x;
        sun.Direction.y = -shading_.sunDir.y;
        sun.Direction.z = -shading_.sunDir.z;
        D3DMATERIAL9 material = {};
        material.Diffuse.r = material.Diffuse.g = material.Diffuse.b = material.Diffuse.a = 1.0f;
        material.Ambient = material.Diffuse;
        device_->SetMaterial(&material);
        device_->SetLight(0, &sun);
        device_->LightEnable(0, TRUE);
        device_->SetRenderState(D3DRS_LIGHTING, TRUE);
        device_->SetRenderState(D3DRS_COLORVERTEX, FALSE);
        device_->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL);
        device_->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL);
        device_->SetRenderState(D3DRS_NORMALIZENORMALS, FALSE);
        device_->SetRenderState(D3DRS_AMBIENT, D3DCOLOR_XRGB(static_cast<int>(shading_.ambient.x * 255.0f + 0.5f),
                                                             static_cast<int>(shading_.ambient.y * 255.0f + 0.5f),
                                                             static_cast<int>(shading_.ambient.z * 255.0f + 0.5f)));
        device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    }

    bool alphaTestEnabled = false;
    bool doubleSided = false;   // see TileBatch::doubleSided
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    device_->SetRenderState(D3DRS_ALPHAREF, g_alphaRef);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);

    // Water batches for the shader surface (water.h), drawn together after the loop:
    // one switch to the shaders and back per frame instead of one per water tile.
    const bool waterShaderOn = (shading_.sun || shading_.fog) && WaterShaderEnabled() && water_.Ready();
    waterDeferred_.clear();
    // Both presentations while the camera moves (the classic one draws the lights' flat cards, the
    // street one their round poles); a settled classic view never: everything is back at once there.
    if (!remixDevice_ && (streetView_ || moveOccMoving_)) UpdatePoleFades(camera);
    else if (anyPoleFaded_) { for (PoleGroup& g : poleGroups_) g.alpha = 1.0f; anyPoleFaded_ = false; }
    struct FadedRange { const TileBatch* batch; uint32_t start, count; float alpha; };
    std::vector<FadedRange> fadedPoles;
    // FIX-WORLD-16 qav59: the first-person near clip of the sparse lattices, as a world-space user clip
    // plane (fixed function) `ahead` blocks in front of the eye along the view, on their batches only.
    const bool latticeClip = streetView_ && !remixDevice_ && seeThroughClip_ > 0.0f && !sparseLattice_.empty();
    bool latticeClipOn = false;
    if (latticeClip) {
        const Mat4 view = camera.ViewMatrix();
        const Vec3 eye = camera.Position();
        // The view's depth axis (UpdatePoleFades: depth = (p - eye) . (m[0][2], m[1][2], m[2][2])).
        const float fx = view.m[0][2], fy = view.m[1][2], fz = view.m[2][2];
        const float plane[4] = {fx, fy, fz, -(fx * eye.x + fy * eye.y + fz * eye.z) - seeThroughClip_};
        device_->SetClipPlane(0, plane);
    }
    // FIX-PERF-9 (14p3): the street views' frustum test of the world's batches. The six planes of
    // view x projection (row vectors: clip = p * VP); a chunk whose box lies wholly on the outer side
    // of one plane rasterises nothing, so leaving it out changes no pixel. Per batch only the span
    // from its first to its last chunk in view is drawn (one draw, never more than before; the
    // triangles keep their order), and a batch with none in view is not drawn at all.
    const bool viewCull = worldViewCull_ && streetView_ && !remixDevice_ && !cullChunks_.empty() &&
                          batchChunks_[0].size() == batches_.size();
    float planes[6][4] = {};
    int cullBatches = 0, cullDrawn = 0;
    long long cullTris = 0, cullTrisAll = 0;
    if (viewCull) {
        const Mat4 v = camera.ViewMatrix();
        const Mat4 p = camera.ProjectionMatrix(static_cast<float>(width_) / static_cast<float>(height_));
        float vp[4][4];
        for (int r = 0; r < 4; ++r)
            for (int c = 0; c < 4; ++c) {
                float acc = 0.0f;
                for (int k = 0; k < 4; ++k) acc += v.m[r][k] * p.m[k][c];
                vp[r][c] = acc;
            }
        auto col = [&](int c, int r) { return vp[r][c]; };
        for (int r = 0; r < 4; ++r) {
            planes[0][r] = col(3, r) + col(0, r);   // left
            planes[1][r] = col(3, r) - col(0, r);   // right
            planes[2][r] = col(3, r) + col(1, r);   // bottom
            planes[3][r] = col(3, r) - col(1, r);   // top
            planes[4][r] = col(2, r);               // near (D3D: 0 <= z)
            planes[5][r] = col(3, r) - col(2, r);   // far
        }
    }
    auto chunkVisible = [&](const CullChunk& c) {
        for (const float* pl : planes) {
            const float d = pl[0] * c.cx + pl[1] * c.cy + pl[2] * c.cz + pl[3];
            const float rad = std::fabs(pl[0]) * c.ex + std::fabs(pl[1]) * c.ey + std::fabs(pl[2]) * c.ez;
            if (d < -rad) return false;
        }
        return true;
    };
    for (const TileBatch& batch : batches_) {
        // FIX-PERF-9: the batch's span in view (street views), before any of its state is set.
        uint32_t spanFirst = 0, spanCount = 0;
        bool spanSet = false;
        if (viewCull && !(batch.streetOnly && !streetView_)) {
            const size_t bi = static_cast<size_t>(&batch - batches_.data());
            const bool streetSet = batch.streetIndices;
            const std::pair<uint32_t, uint32_t> range = batchChunks_[streetSet ? 1 : 0][bi];
            ++cullBatches;
            cullTrisAll += (streetSet ? batch.streetIndexCount : batch.indexCount) / 3;
            uint32_t a = 0;
            while (a < range.second && !chunkVisible(cullChunks_[range.first + a])) ++a;
            if (a == range.second) continue;   // nothing of it in view
            uint32_t z = range.second - 1;
            while (z > a && !chunkVisible(cullChunks_[range.first + z])) --z;
            const CullChunk& c0 = cullChunks_[range.first + a];
            const CullChunk& c1 = cullChunks_[range.first + z];
            spanFirst = c0.start;
            spanCount = c1.start + c1.count - c0.start;
            spanSet = true;
            ++cullDrawn;
            cullTris += spanCount / 3;
        }
        if (latticeClip) {
            const bool want = batch.needsAlphaTest && batch.tile >= 0 && batch.tile < static_cast<int>(sparseLattice_.size()) &&
                              sparseLattice_[static_cast<size_t>(batch.tile)] && (!batch.lidFaces || seeThroughClipLids_);
            if (want != latticeClipOn) {
                device_->SetRenderState(D3DRS_CLIPPLANEENABLE, want ? D3DCLIPPLANE0 : 0);
                latticeClipOn = want;
            }
        }
        // The street views' fill (world_mesh.h, TileBatch::streetOnly): never in the
        // classic view, which keeps exactly the draws it had before the fill existed.
        if (batch.streetOnly && !streetView_) continue;
        if (waterShaderOn && batch.tile < static_cast<int>(waterTile_.size()) && waterTile_[batch.tile]) {
            waterDeferred_.push_back(&batch);
            continue;
        }
        if (batch.needsAlphaTest != alphaTestEnabled) {
            alphaTestEnabled = batch.needsAlphaTest;
            const bool blending = g_alphaMode == AlphaMode::Blend;
            // Blend mode still keeps a very low alpha test: without it the fully
            // transparent texels are still rasterised and still write depth,
            // which puts an invisible wall in front of everything behind them.
            device_->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTestEnabled ? TRUE : FALSE);
            device_->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : g_alphaRef);
            device_->SetRenderState(D3DRS_ALPHABLENDENABLE,
                                    (blending && alphaTestEnabled) ? TRUE : FALSE);
        }
        if (batch.doubleSided != doubleSided) {
            doubleSided = batch.doubleSided;
            device_->SetRenderState(D3DRS_CULLMODE, doubleSided ? D3DCULL_NONE : cullMode_);
        }
        device_->SetTexture(0, BoundTileTexture(batch.tile));
        // The fixed-function ripple, when the shader surface is off or unavailable.
        const bool water = !waterShaderOn && g_waterEffect && (shading_.sun || shading_.fog) && waterNoise_ && batch.tile < static_cast<int>(waterTile_.size()) && waterTile_[batch.tile];
        if (water) {
            // Two layers of noise drifting across each other, signed-added so the
            // surface sparkles and darkens with the ripples, then pulled a
            // quarter of the way to the sky's horizon colour: the cheapest
            // reflection there is, and enough for water to read as water.
            const float t = static_cast<float>(waterClock_);
            D3DMATRIX m1 = {}, m2 = {};
            m1._11 = 3.0f; m1._22 = 3.0f; m1._33 = 1.0f; m1._44 = 1.0f; m1._31 = t * 0.021f; m1._32 = t * 0.013f;
            m2._11 = 5.0f; m2._22 = 5.0f; m2._33 = 1.0f; m2._44 = 1.0f; m2._31 = -t * 0.034f; m2._32 = t * 0.019f;
            for (DWORD stage = 1; stage <= 2; ++stage) {
                device_->SetTexture(stage, waterNoise_);
                device_->SetTextureStageState(stage, D3DTSS_TEXCOORDINDEX, 0);
                device_->SetTextureStageState(stage, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT2);
                device_->SetTransform(static_cast<D3DTRANSFORMSTATETYPE>(D3DTS_TEXTURE0 + stage), stage == 1 ? &m1 : &m2);
                device_->SetTextureStageState(stage, D3DTSS_COLOROP, D3DTOP_ADDSIGNED);
                device_->SetTextureStageState(stage, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                device_->SetTextureStageState(stage, D3DTSS_COLORARG2, D3DTA_CURRENT);
                device_->SetTextureStageState(stage, D3DTSS_ALPHAOP, D3DTOP_SELECTARG2);
                device_->SetTextureStageState(stage, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
                device_->SetSamplerState(stage, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
                device_->SetSamplerState(stage, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
                device_->SetSamplerState(stage, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
                device_->SetSamplerState(stage, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
                device_->SetSamplerState(stage, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
            }
            const Vec3 sky = shading_.fog ? shading_.fogColour : Vec3{0.6f, 0.7f, 0.85f};
            device_->SetRenderState(D3DRS_TEXTUREFACTOR,
                                    D3DCOLOR_RGBA(static_cast<int>(std::min(1.0f, sky.x) * 255.0f + 0.5f),
                                                  static_cast<int>(std::min(1.0f, sky.y) * 255.0f + 0.5f),
                                                  static_cast<int>(std::min(1.0f, sky.z) * 255.0f + 0.5f), 64));
            device_->SetTextureStageState(3, D3DTSS_COLOROP, D3DTOP_BLENDFACTORALPHA);
            device_->SetTextureStageState(3, D3DTSS_COLORARG1, D3DTA_TFACTOR);
            device_->SetTextureStageState(3, D3DTSS_COLORARG2, D3DTA_CURRENT);
            device_->SetTextureStageState(3, D3DTSS_ALPHAOP, D3DTOP_SELECTARG2);
            device_->SetTextureStageState(3, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
            device_->SetTextureStageState(4, D3DTSS_COLOROP, D3DTOP_DISABLE);
        }
        // Lit windows: the room glow added on top, scaled by how low the sun
        // is (nothing at noon, full at dusk and night), in the street views only.
        // LIGHTING-V1: staggered by the wall tile (a hashed share of the ramp), so a street's facades light up one
        // kind of wall after another through the dusk rather than all at one sun height; all lit by the sun's 6 deg.
        const float glowLead = batch.tile >= 0 ? static_cast<float>((static_cast<uint32_t>(batch.tile) * 2654435761u) >> 24) / 255.0f * 0.25f : 0.0f;
        const float glowAmount = g_windowGlow && shading_.sun && !water
                                     ? std::min(1.0f, std::max(0.0f, (0.55f - glowLead - shading_.sunDir.y) / (0.45f - glowLead)))
                                     : 0.0f;
        // FIX-WORLD-7 (pm12): by day the same panes reflect the sky (windowSky_), faded out as the
        // night glow comes in (stage 2 takes the complement of the glow's factor); a dark pane right
        // beside a first-person eye no longer reads as a black hole. GTA2DX9_WINDOW_SKY=0: off.
        static int s_windowSky = -1;
        if (s_windowSky < 0) { const char* e = getenv("GTA2DX9_WINDOW_SKY"); s_windowSky = (e && e[0] == '0') ? 0 : 1;
                               Trace("windows: %s", s_windowSky ? "panes reflect the sky by day (FIX-WORLD-7 pm12)" : "no daytime pane reflection (GTA2DX9_WINDOW_SKY=0)"); }
        const bool tileHasWindow = batch.tile < static_cast<int>(windowGlow_.size()) && windowGlow_[static_cast<size_t>(batch.tile)];
        IDirect3DTexture9* const windowSky = s_windowSky && g_windowGlow && shading_.sun && !water && tileHasWindow && glowAmount < 0.98f &&
                                             batch.tile < static_cast<int>(windowSky_.size()) ? windowSky_[static_cast<size_t>(batch.tile)] : nullptr;
        IDirect3DTexture9* glow = (glowAmount > 0.02f || windowSky) && tileHasWindow ? windowGlow_[static_cast<size_t>(batch.tile)] : nullptr;
        if (glow) {
            const int a = static_cast<int>(glowAmount * 255.0f + 0.5f);
            device_->SetTexture(1, glow);
            device_->SetTextureStageState(1, D3DTSS_TEXCOORDINDEX, 0);
            device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MULTIPLYADD);   // current + glow * factor
            device_->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_TEXTURE);
            device_->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_TFACTOR);
            device_->SetTextureStageState(1, D3DTSS_COLORARG0, D3DTA_CURRENT);
            device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG2);
            device_->SetTextureStageState(1, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
            device_->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_RGBA(a, a, a, 255));
            device_->SetSamplerState(1, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
            device_->SetSamplerState(1, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
            device_->SetSamplerState(1, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
            if (windowSky) {
                device_->SetTexture(2, windowSky);
                device_->SetTextureStageState(2, D3DTSS_TEXCOORDINDEX, 0);
                device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_MULTIPLYADD);   // current + sky * (1 - factor)
                device_->SetTextureStageState(2, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                device_->SetTextureStageState(2, D3DTSS_COLORARG2, D3DTA_TFACTOR | D3DTA_COMPLEMENT);
                device_->SetTextureStageState(2, D3DTSS_COLORARG0, D3DTA_CURRENT);
                device_->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_SELECTARG2);
                device_->SetTextureStageState(2, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
                device_->SetSamplerState(2, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
                device_->SetSamplerState(2, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
                device_->SetSamplerState(2, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);
                device_->SetTextureStageState(3, D3DTSS_COLOROP, D3DTOP_DISABLE);
            } else {
                device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
            }
        }
        if (batch.wrapUv) {
            device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
            device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        }
        // FIX-SMOOTH-SWITCH: part way through a move between the classic and a street view,
        // the tile's plain HD texture and its photo-material copy cross-fade on the same
        // triangles (stage 1 lerps by the texture factor's alpha), then the sun's lighting
        // is applied as it is to either alone. Only while 0 < photoMix_ < 1, so neither
        // settled view draws anything differently; not on water or lit-window tiles, which
        // use the extra stages themselves and take the set BoundTileTexture picks.
        IDirect3DTexture9* const photoBlend =
            (TileMix(batch.tile) > 0.0f && TileMix(batch.tile) < 1.0f && !water && !glow) ? PhotoTileTexture(batch.tile) : nullptr;
        if (photoBlend) {
            device_->SetTexture(0, textures_[batch.tile]);
            device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
            device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
            device_->SetTexture(1, photoBlend);
            device_->SetTextureStageState(1, D3DTSS_TEXCOORDINDEX, 0);
            device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_BLENDFACTORALPHA);
            device_->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_TEXTURE);
            device_->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_CURRENT);
            device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_BLENDFACTORALPHA);
            device_->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
            device_->SetTextureStageState(1, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
            static const D3DSAMPLERSTATETYPE kCopy[] = {D3DSAMP_ADDRESSU, D3DSAMP_ADDRESSV, D3DSAMP_MINFILTER, D3DSAMP_MAGFILTER,
                                                        D3DSAMP_MIPFILTER, D3DSAMP_MAXANISOTROPY};
            for (D3DSAMPLERSTATETYPE k : kCopy) {
                DWORD v = 0;
                if (SUCCEEDED(device_->GetSamplerState(0, k, &v))) device_->SetSamplerState(1, k, v);
            }
            const int a = static_cast<int>(TileMix(batch.tile) * 255.0f + 0.5f);
            device_->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_RGBA(255, 255, 255, a));
            if (shading_.sun) {
                device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_MODULATE);
                device_->SetTextureStageState(2, D3DTSS_COLORARG1, D3DTA_CURRENT);
                device_->SetTextureStageState(2, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
                device_->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                device_->SetTextureStageState(2, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
                device_->SetTextureStageState(3, D3DTSS_COLOROP, D3DTOP_DISABLE);
            } else {
                device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
            }
        }
        // The street views leave the overhead decals out (world_mesh.h, TileBatch::streetIndices).
        const bool streetRange = streetView_ && batch.streetIndices;
        const size_t batchIndex = static_cast<size_t>(&batch - batches_.data());
        const bool polePath = anyPoleFaded_ && batchIndex < polesOfBatch_.size() && !polesOfBatch_[batchIndex].empty();
        // FIX-CLASSIC-WATER-1: the classic view draws the water lids with the game's own per-block
        // coordinates (TileBatch::classicIndices); GTA2DX9_CLASSIC_ANIM_TILES=0 = before. Classic only,
        // so never together with FIX-PERF-9's span (street views only).
        const bool classicRange = !streetView_ && batch.classicIndices && ClassicWaterUv() && !polePath;
        const uint32_t fullFirst = classicRange ? batch.classicIndexStart : streetRange ? batch.streetIndexStart : batch.indexStart;
        const uint32_t fullCount = classicRange ? batch.classicIndexCount : streetRange ? batch.streetIndexCount : batch.indexCount;
        const uint32_t minVertex = classicRange ? batch.classicVertexStart : batch.vertexStart;
        // FIX-PERF-9: the span in view; the faded-pole path keeps the whole range (its pole ranges index into it).
        const uint32_t first = spanSet && !polePath && !classicRange ? spanFirst : fullFirst;
        const uint32_t count = spanSet && !polePath && !classicRange ? spanCount : fullCount;
        if (polePath) {
            // FIX-TRANSITION-ART: around the street lights that are fading or gone (UpdatePoleFades).
            uint32_t at = first;
            const uint32_t end = first + count;
            for (int pi : polesOfBatch_[batchIndex]) {
                const StreetPole& pole = streetPoles_[static_cast<size_t>(pi)];
                const float a = poleGroups_[static_cast<size_t>(poleGroup_[static_cast<size_t>(pi)])].alpha;
                if (a >= 0.999f || pole.indexStart < at || pole.indexStart + pole.indexCount > end) continue;
                if (pole.indexStart > at)
                    device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, batch.vertexStart, batch.vertexCount, at, (pole.indexStart - at) / 3);
                if (a > 0.02f) fadedPoles.push_back({&batch, pole.indexStart, pole.indexCount, a});
                at = pole.indexStart + pole.indexCount;
            }
            if (end > at + 2)
                device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, batch.vertexStart, batch.vertexCount, at, (end - at) / 3);
        } else if (count >= 3)
            device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, minVertex, batch.vertexCount,
                                          first, count / 3);
        if (photoBlend) {
            device_->SetTextureStageState(0, D3DTSS_COLOROP, shading_.sun ? D3DTOP_MODULATE : D3DTOP_SELECTARG1);
            device_->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
            for (DWORD stage = 1; stage <= 2; ++stage) {
                device_->SetTextureStageState(stage, D3DTSS_COLOROP, D3DTOP_DISABLE);
                device_->SetTextureStageState(stage, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
            }
            device_->SetTexture(1, nullptr);
        }
        if (batch.wrapUv) {
            device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
            device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        }
        if (glow) {
            device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
            device_->SetTexture(1, nullptr);
            if (windowSky) {
                device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
                device_->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
                device_->SetTexture(2, nullptr);
            }
        }
        if (water) {
            for (DWORD stage = 1; stage <= 3; ++stage) {
                device_->SetTextureStageState(stage, D3DTSS_COLOROP, D3DTOP_DISABLE);
                device_->SetTextureStageState(stage, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
                device_->SetTextureStageState(stage, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
                device_->SetTexture(stage, nullptr);
            }
        }
        stats_.drawCalls++;
        stats_.triangles += static_cast<int>(batch.indexCount / 3);
    }
    if (latticeClipOn) device_->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
    if (doubleSided) device_->SetRenderState(D3DRS_CULLMODE, cullMode_);
    if (worldCullLogEvery_ < 0) { const char* e = getenv("GTA2DX9_WORLD_CULL_LOG"); worldCullLogEvery_ = e ? (std::max)(0, atoi(e)) : 0; }
    if (viewCull && worldCullLogEvery_ > 0 && (++worldCullFrames_ % static_cast<uint32_t>(worldCullLogEvery_)) == 0)
        Trace("world view cull: %d of %d batches drawn, %lld of %lld triangles (FIX-PERF-9)", cullDrawn, cullBatches, cullTris, cullTrisAll);
    if (!fadedPoles.empty()) {
        // The fading street lights, blended over what is behind them (texture x the factor's alpha),
        // without depth writes, last of the opaque world.
        DWORD alphaOp = D3DTOP_SELECTARG1, alphaArg1 = D3DTA_TEXTURE, alphaArg2 = D3DTA_CURRENT, factor = 0xFFFFFFFF;
        device_->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
        device_->GetTextureStageState(0, D3DTSS_ALPHAARG1, &alphaArg1);
        device_->GetTextureStageState(0, D3DTSS_ALPHAARG2, &alphaArg2);
        device_->GetRenderState(D3DRS_TEXTUREFACTOR, &factor);
        device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
        device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        for (const FadedRange& f : fadedPoles) {
            const DWORD a = static_cast<DWORD>((std::min)(1.0f, f.alpha) * 255.0f + 0.5f);
            device_->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(a, 255, 255, 255));
            device_->SetTexture(0, BoundTileTexture(f.batch->tile));
            device_->SetRenderState(D3DRS_CULLMODE, f.batch->doubleSided ? D3DCULL_NONE : cullMode_);
            device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, f.batch->vertexStart, f.batch->vertexCount, f.start, f.count / 3);
        }
        device_->SetRenderState(D3DRS_CULLMODE, cullMode_);
        device_->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg1);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG2, alphaArg2);
        device_->SetRenderState(D3DRS_TEXTUREFACTOR, factor);
        device_->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
        device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    }
    if (!waterDeferred_.empty()) {
        device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
        water_.Begin(camera.ViewMatrix(), camera.ProjectionMatrix(static_cast<float>(width_) / static_cast<float>(height_)),
                     camera.Position(), shading_, waterClock_);
        for (const TileBatch* batch : waterDeferred_) {
            device_->SetRenderState(D3DRS_CULLMODE, batch->doubleSided ? D3DCULL_NONE : cullMode_);
            device_->SetTexture(0, BoundTileTexture(batch->tile));
            // The apron past the map's edge (world_mesh.cpp AddApron): its tile repeats, and
            // outside the map the shore map reads "open sea" (white border) instead of the
            // clamped edge texel, which by a walled edge would be foam to the horizon.
            if (batch->wrapUv) {
                device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
                device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
                device_->SetSamplerState(2, D3DSAMP_ADDRESSU, D3DTADDRESS_BORDER);
                device_->SetSamplerState(2, D3DSAMP_ADDRESSV, D3DTADDRESS_BORDER);
                device_->SetSamplerState(2, D3DSAMP_BORDERCOLOR, 0xFFFFFFFFu);
            }
            device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, batch->vertexStart, batch->vertexCount,
                                          batch->indexStart, batch->indexCount / 3);
            if (batch->wrapUv) {
                device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
                device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
                device_->SetSamplerState(2, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
                device_->SetSamplerState(2, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
            }
            stats_.drawCalls++;
            stats_.triangles += static_cast<int>(batch->indexCount / 3);
        }
        water_.End();
        device_->SetRenderState(D3DRS_CULLMODE, cullMode_);
        // Leave the alpha state as the loop left it, for the live geometry after.
        const bool blending = g_alphaMode == AlphaMode::Blend;
        device_->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTestEnabled ? TRUE : FALSE);
        device_->SetRenderState(D3DRS_ALPHABLENDENABLE, (blending && alphaTestEnabled) ? TRUE : FALSE);
    }
    if (shading_.sun) {
        device_->LightEnable(0, FALSE);
        device_->SetRenderState(D3DRS_LIGHTING, FALSE);
        device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    }
    // From here to EndWorldShading the cars, people and props are drawn; their draws
    // are kept for the sun's shadow maps.
    post_.StartRecording();
}

// Managed textures reach the GL driver the first time they are drawn with,
// which in play is a 20-100 ms hitch per tile texture (the "ui"/"present"
// spikes of the first minute). This binds up to `perFrame` of them in a draw
// that writes no pixels, so the uploads happen a few per frame in the first
// seconds after a level loads instead. Returns what is still to do.
bool Renderer::BeginGhostFrame() {
    if (!device_ || !vertexBuffer_ || remixDevice_ || ghostState_) return false;
    if (FAILED(device_->CreateRenderTarget(width_, height_, D3DFMT_A8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE, &ghostRt_, nullptr)) ||
        FAILED(device_->CreateDepthStencilSurface(width_, height_, D3DFMT_D24S8, D3DMULTISAMPLE_NONE, 0, TRUE, &ghostDepth_, nullptr)) ||
        FAILED(device_->CreateStateBlock(D3DSBT_ALL, &ghostState_))) {
        if (ghostRt_) { ghostRt_->Release(); ghostRt_ = nullptr; }
        if (ghostDepth_) { ghostDepth_->Release(); ghostDepth_ = nullptr; }
        ghostState_ = nullptr;
        return false;
    }
    ghostState_->Capture();
    device_->GetRenderTarget(0, &ghostSavedRt_);
    device_->GetDepthStencilSurface(&ghostSavedDepth_);
    device_->SetRenderTarget(0, ghostRt_);
    device_->SetDepthStencilSurface(ghostDepth_);
    device_->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER | D3DCLEAR_STENCIL, 0, 1.0f, 0);
    ghostShading_ = shading_;
    ghostStreet_ = streetView_;
    ghostPhotoMix_ = photoMix_;
    ghostRoadMix_ = roadMix_;
    return true;
}

void Renderer::EndGhostFrame() {
    if (!ghostState_) return;
    streetView_ = ghostStreet_;
    photoMix_ = ghostPhotoMix_;
    roadMix_ = ghostRoadMix_;
    shading_ = ghostShading_;
    device_->SetRenderTarget(0, ghostSavedRt_);
    device_->SetDepthStencilSurface(ghostSavedDepth_);
    ghostState_->Apply();
    ghostState_->Release();
    ghostState_ = nullptr;
    if (ghostSavedRt_) { ghostSavedRt_->Release(); ghostSavedRt_ = nullptr; }
    if (ghostSavedDepth_) { ghostSavedDepth_->Release(); ghostSavedDepth_ = nullptr; }
    ghostRt_->Release(); ghostRt_ = nullptr;
    ghostDepth_->Release(); ghostDepth_ = nullptr;
}

int Renderer::WarmTileTextures(int perFrame) {
    if (device_ && vertexBuffer_) sky_.Warm(device_);   // nothing once built
    if (!device_ || warmCursor_ >= textures_.size()) return 0;
    struct V { float x, y, z, rhw, u, v; };
    const V quad[4] = {{0.0f, 0.0f, 0.5f, 1.0f, 0.0f, 0.0f}, {2.0f, 0.0f, 0.5f, 1.0f, 1.0f, 0.0f},
                       {0.0f, 2.0f, 0.5f, 1.0f, 0.0f, 1.0f}, {2.0f, 2.0f, 0.5f, 1.0f, 1.0f, 1.0f}};
    DWORD colorWrite = 0xF, zWrite = TRUE, zEnable = TRUE, fvf = 0;
    device_->GetRenderState(D3DRS_COLORWRITEENABLE, &colorWrite);
    device_->GetRenderState(D3DRS_ZWRITEENABLE, &zWrite);
    device_->GetRenderState(D3DRS_ZENABLE, &zEnable);
    device_->GetFVF(&fvf);
    device_->SetRenderState(D3DRS_COLORWRITEENABLE, 0);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, FALSE);
    device_->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    int done = 0;
    while (warmCursor_ < textures_.size() && done < perFrame) {
        if (IDirect3DTexture9* t = textures_[warmCursor_]) {
            device_->SetTexture(0, t);
            device_->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(V));
            ++done;
        }
        if (warmCursor_ < photoTextures_.size() && photoTextures_[warmCursor_]) {
            device_->SetTexture(0, photoTextures_[warmCursor_]);
            device_->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(V));
        }
        ++warmCursor_;
    }
    device_->SetTexture(0, nullptr);
    device_->SetFVF(fvf);
    device_->SetRenderState(D3DRS_COLORWRITEENABLE, colorWrite);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, zWrite);
    device_->SetRenderState(D3DRS_ZENABLE, zEnable);
    if (warmCursor_ >= textures_.size()) Trace("tile textures: all %zu uploaded ahead of use", textures_.size());
    return static_cast<int>(textures_.size() - warmCursor_);
}

void Renderer::DrawSky(const Camera& camera, const SkySettings& settings, const SkyColours& colours, float blend,
                       double seconds) {
    if (!device_ || !vertexBuffer_ || blend <= 0.0f) return;
    sky_.SetHdr(post_.Active());
    // Weather (weather_fx.h): an overcast or foggy sky; the camera for the rain.
    SkySettings skySettings = settings;
    SkyColours skyColours = colours;
    WeatherAdjustSky(&skyColours, &skySettings);
    weather_.SetCamera(camera.ViewMatrix(), camera.ProjectionMatrix(static_cast<float>(width_) / static_cast<float>(height_)), camera.Position());
    sky_.Draw(device_, camera, static_cast<float>(width_) / static_cast<float>(height_), skySettings, skyColours, blend,
              seconds);
    if (post_.Active()) post_.SetSky(skyColours.zenith, skyColours.horizon, skyColours.day);
    water_.SetSky(skyColours.zenith, skyColours.horizon);
    stats_.drawCalls += 3;
}

// The street views' light, and with [visuals] on the post's targets for the frame.
void Renderer::SetWorldShading(const WorldShading& incoming) {
    // Weather (weather_fx.h) on the street views' light; the post's transition weight
    // below is still read from the fog as the view set it.
    WeatherPoll();
    WorldShading shading = incoming;
    if (!remixDevice_ && incoming.fog) {
        const float sf = SkyConfig().fogStart;
        WeatherAdjustShading(&shading, std::min(1.0f, std::max(0.0f, 1.0f - (incoming.fogStart - sf) / std::max(1.0f, 600.0f - sf))));
    }
    shading_ = shading;
    VisualsPoll();
    if (!shading.fog || !device_ || !vertexBuffer_ || !post_.Available() || !VisualsConfig().enabled) return;
    const SkySettings& sky = SkyConfig();
    // The transition's weight, from how far the fog has eased in (world_view.cpp,
    // DrawSkyAndShading: start = configured + (600 - configured) * (1 - blend)).
    float blend = 1.0f - (incoming.fogStart - sky.fogStart) / std::max(1.0f, 600.0f - sky.fogStart);
    blend = std::min(1.0f, std::max(0.0f, blend));
    const VisualsSettings& v = VisualsConfig();
    // A harder sun and a softer ambient: with shadows to take the sun away again,
    // the faces that see it can carry more of the light.
    if (shading.sun) {
        shading_.ambient = shading.ambient * (1.0f + (v.ambientScale - 1.0f) * blend);
        shading_.sunColour = shading.sunColour * (1.0f + (v.sunBoost - 1.0f) * blend);
    }
    PostFrame f;
    f.sunDir = shading_.sunDir;
    f.sunLevel = shading_.sun ? (shading_.sunColour.x + shading_.sunColour.y + shading_.sunColour.z) / 3.0f : 0.0f;
    f.ambientLevel = shading_.sun ? (shading_.ambient.x + shading_.ambient.y + shading_.ambient.z) / 3.0f : 1.0f;
    f.fogColour = shading_.fogColour;
    f.fogStart = shading_.fogStart;
    f.fogEnd = shading_.fogEnd;
    f.blend = blend;
    const float el = std::asin(std::max(-1.0f, std::min(1.0f, shading_.sunDir.y))) * 57.29578f;
    const float t = std::min(1.0f, std::max(0.0f, (el + 8.0f) / 20.0f));
    f.day = t * t * (3.0f - 2.0f * t);
    if (!post_.BeginScene(f)) shading_ = shading;
}

void Renderer::EndWorldShading() {
    if (!device_) return;
    weather_.DrawRain(shading_);
    if (post_.Active()) {
        post_.SetPuddles(WeatherNow().wetRoads && WeatherNow().wet > 0.01f ? weather_.Puddles() : nullptr);
        post_.Resolve();
    }
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->LightEnable(0, FALSE);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
}

}  // namespace gta2
