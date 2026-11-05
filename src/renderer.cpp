#include "renderer.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>

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

IDirect3D9* CreateD3D9() {
    for (const char* name : kD3D9Modules) {
        const HMODULE module = LoadLibraryA(name);
        if (!module) continue;
        using CreateFn = IDirect3D9*(WINAPI*)(UINT);
        const auto create = reinterpret_cast<CreateFn>(GetProcAddress(module, "Direct3DCreate9"));
        if (!create) continue;
        if (IDirect3D9* d3d = create(D3D_SDK_VERSION)) {
            Trace("Direct3D from %s", name);
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

std::string g_hdTextureDir;
std::string g_tileDumpDir;
std::string g_tileStyle = "style";
int g_hdTileMax = 128;
void SetHdTileMaxSize(int size) { g_hdTileMax = size < 64 ? 64 : (size > 1024 ? 1024 : size); }
int g_anisotropy = 0;   // 0: 8 on a GPU, 1 on a software renderer; else the level asked for
void SetAnisotropy(int level) { g_anisotropy = level < 0 ? 0 : (level > 16 ? 16 : level); }
bool g_softwareGl = false;
void SetHdTextureDir(const char* dir) { g_hdTextureDir = dir ? dir : ""; }
void SetTileDumpDir(const char* dir) { g_tileDumpDir = dir ? dir : ""; }
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
    sky_.Release();
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
    return true;
}

bool Renderer::UploadWorld(const WorldMesh& mesh, const Style& style, std::string* error) {
    if (mesh.vertices.empty()) {
        *error = "world mesh is empty";
        return false;
    }
    ReleaseResources();
    batches_ = mesh.batches;

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

    // One texture per tile keeps Remix's texture hashes stable and per-tile
    // replaceable, instead of hiding every surface behind one atlas hash. Two
    // slots past the end for the seal under the world and the riverbed, which
    // have no tile of their own - see SealTileIndex and RiverbedTileIndex.
    const int sealTile = SealTileIndex(style);
    sealTile_ = sealTile;
    const int riverbedTile = RiverbedTileIndex(style);
    textures_.assign(static_cast<size_t>(riverbedTile) + 1, nullptr);
    warmCursor_ = 0;
    hdTiles_ = 0;
    hdDdsTiles_ = 0;
    hdFailed_ = 0;
    const std::string hdDir = g_hdTextureDir.empty() ? "" : g_hdTextureDir + "\\" + g_tileStyle;
    const std::string dumpDir = g_tileDumpDir.empty() ? "" : g_tileDumpDir + "\\" + g_tileStyle;
    if (!dumpDir.empty()) {
        CreateDirectoryA(g_tileDumpDir.c_str(), nullptr);
        CreateDirectoryA(dumpDir.c_str(), nullptr);
    }
    std::vector<uint32_t> hd;
    for (const TileBatch& batch : batches_) {
        if (textures_[batch.tile]) continue;

        // High-resolution artwork for this tile, if the folder has it: a
        // block-compressed DDS with mips first (tools/pack_textures_dds.py), then
        // the older uncompressed TGA.
        if (!hdDir.empty() && batch.tile != sealTile && batch.tile != riverbedTile) {
            int w = 0, h = 0;
            DdsImage dds;
            if (ReadDds(hdDir + "\\" + TileDdsFileName(batch.tile), &dds)) {
                if (IDirect3DTexture9* texture = CreateDdsTexture(device_, dds, g_hdTileMax)) {
                    textures_[batch.tile] = texture;
                    ++hdTiles_;
                    ++hdDdsTiles_;
                    continue;
                }
                ++hdFailed_;
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
    if (hdTiles_ > 0 || hdFailed_ > 0) {
        Trace("hd tiles: %d loaded (%d block-compressed DDS with mips, cap %d px), %d failed, of %zu tile textures",
              hdTiles_, hdDdsTiles_, g_hdTileMax, hdFailed_, textures_.size());
    }
    return true;
}

void Renderer::UpdateTileTexture(int tile, const uint32_t* pixels) {
    if (!HasTileTexture(tile) || !pixels) return;

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
    uint64_t key = 0xCBF29CE484222325ULL;
    for (size_t i = 0; i < static_cast<size_t>(kTileSize) * kTileSize; ++i) {
        key ^= pixels[i];
        key *= 0x100000001B3ULL;
    }

    const auto existing = tileFrames_.find(key);
    if (existing != tileFrames_.end()) {
        textures_[tile] = existing->second;
        return;
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
    static int voidTestClear = -1;
    if (voidTestClear < 0) { char buf[16] = {}; voidTestClear = GetEnvironmentVariableA("GTA2DX9_VOIDTEST", buf, sizeof buf) ? atoi(buf) : 0; }
    device_->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, (voidTestClear & 32) ? D3DCOLOR_XRGB(255, 0, 255) : D3DCOLOR_XRGB(0, 0, 0), 1.0f,
                   0);
    return SUCCEEDED(device_->BeginScene());
}

void Renderer::EndFrame() {
    if (!device_) return;
    device_->EndScene();
    device_->Present(nullptr, nullptr, nullptr, nullptr);
}

void Renderer::DrawWorld(const Camera& camera) {
    // Nothing to draw until the game has a world loaded; the frame is still
    // cleared and presented so menus have something to sit on.
    if (!device_ || !vertexBuffer_) return;

    ApplyFixedFunctionState();
    // Temporary diagnostic switches (GTA2DX9_VOIDTEST env): 1 cull none, 2 z always,
    // 4 no fog/sun, 8 near plane 0.3, 16 wireframe.
    static int voidTest = -1;
    if (voidTest < 0) { char buf[16] = {}; voidTest = GetEnvironmentVariableA("GTA2DX9_VOIDTEST", buf, sizeof buf) ? atoi(buf) : 0; }
    SetMatrix(device_, D3DTS_WORLD, Identity());
    SetMatrix(device_, D3DTS_VIEW, camera.ViewMatrix());
    if (voidTest & 8) {
        SetMatrix(device_, D3DTS_PROJECTION,
                  PerspectiveFovLH(camera.FovY(), static_cast<float>(width_) / static_cast<float>(height_), 0.3f, 2000.0f));
    } else {
        SetMatrix(device_, D3DTS_PROJECTION,
                  camera.ProjectionMatrix(static_cast<float>(width_) / static_cast<float>(height_)));
    }
    if (voidTest & 1) device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    if (voidTest & 2) device_->SetRenderState(D3DRS_ZFUNC, D3DCMP_ALWAYS);
    if (voidTest & 16) device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_WIREFRAME);

    device_->SetFVF(kWorldFvf);
    device_->SetStreamSource(0, vertexBuffer_, 0, sizeof(Vertex));
    device_->SetIndices(indexBuffer_);

    // The street views' atmosphere. Fog stays on for the live geometry that
    // follows (EndWorldShading turns it off); the sun light is this pass only.
    if (shading_.fog && !(voidTest & 4)) {
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
    if (shading_.sun && !(voidTest & 4)) {
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

    for (const TileBatch& batch : batches_) {
        if ((voidTest & 64) && batch.tile == sealTile_) continue;
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
        device_->SetTexture(0, textures_[batch.tile]);
        device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, batch.vertexStart, batch.vertexCount,
                                      batch.indexStart, batch.indexCount / 3);
        stats_.drawCalls++;
        stats_.triangles += static_cast<int>(batch.indexCount / 3);
    }
    if (doubleSided) device_->SetRenderState(D3DRS_CULLMODE, cullMode_);
    if (voidTest & 2) device_->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    if (voidTest & 16) device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    if (shading_.sun) {
        device_->LightEnable(0, FALSE);
        device_->SetRenderState(D3DRS_LIGHTING, FALSE);
        device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    }
}

// Managed textures reach the GL driver the first time they are drawn with,
// which in play is a 20-100 ms hitch per tile texture (the "ui"/"present"
// spikes of the first minute). This binds up to `perFrame` of them in a draw
// that writes no pixels, so the uploads happen a few per frame in the first
// seconds after a level loads instead. Returns what is still to do.
int Renderer::WarmTileTextures(int perFrame) {
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
    static int voidTestSky = -1;
    if (voidTestSky < 0) { char buf[16] = {}; voidTestSky = GetEnvironmentVariableA("GTA2DX9_VOIDTEST", buf, sizeof buf) ? atoi(buf) : 0; }
    if (voidTestSky & 32) return;
    sky_.Draw(device_, camera, static_cast<float>(width_) / static_cast<float>(height_), settings, colours, blend,
              seconds);
    stats_.drawCalls += 3;
}

void Renderer::EndWorldShading() {
    if (!device_) return;
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->LightEnable(0, FALSE);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
}

}  // namespace gta2
