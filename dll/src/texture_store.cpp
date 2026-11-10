#include "thread_watch.h"
#include "texture_store.h"

#include "live_geometry.h"
#include "log.h"

#include "../../src/alpha_bleed.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "game_access.h"

namespace gta2dx9 {
namespace {

constexpr int kPaletteEntries = 256;
constexpr int kPaletteStride = 64;  // in dwords, matching the style file layout
constexpr int kTileSize = 64;

// Tiles are not tightly packed: they live inside 256x256 pages holding a 4x4
// grid of them, and the game registers each tile as a pointer to its top-left
// pixel within that page. Rows are therefore a page apart, not a tile apart.
// Reading them contiguously produces interleaved strips rather than a tile.
constexpr int kPageStride = 256;

// Where each palette lives inside the game's own palette pages, not a copy of
// it. GTA2 registers a palette before it has filled the colours in - 74 of them
// came back entirely black across a single level load - so a snapshot taken at
// registration freezes whatever happened to be there at that instant. That is
// what left cars flat black until something else forced their texture to
// rebuild. Holding the pointer and reading the colours when a texture is
// actually built means we always see what the game currently has.
std::map<int, const uint32_t*> g_palettes;

// Expanded on demand into one shared buffer; a texture build reads it once.
uint32_t g_expanded[kPaletteEntries];

}  // namespace

TextureTrouble g_trouble;

void StorePalette(int index, const uint32_t* source) {
    if (!source || index < 0) return;
    g_palettes[index] = source;
}

void ForgetPalette(int index) { g_palettes.erase(index); }

int PaletteCount() { return static_cast<int>(g_palettes.size()); }

// hasColour reports whether the game has actually filled this palette in yet;
// entry 0 is the transparency key and is ignored for that.
const uint32_t* PaletteColours(int index, bool* hasColour) {
    const auto found = g_palettes.find(index);
    if (found == g_palettes.end() || !found->second) {
        if (hasColour) *hasColour = false;
        return nullptr;
    }
    const uint32_t* page = found->second;
    bool any = false;
    for (int i = 0; i < kPaletteEntries; ++i) {
        g_expanded[i] = page[static_cast<size_t>(i) * kPaletteStride];
        if (i > 0 && (g_expanded[i] & 0x00FFFFFFu) != 0) any = true;
    }
    if (hasColour) *hasColour = any;
    if (!any) ++g_trouble.paletteAllBlack;
    return g_expanded;
}

namespace {

struct CachedTexture {
    IDirect3DTexture9* texture = nullptr;
    uint16_t width = 0, height = 0;
    uint16_t palette = 0xFFFF;
    uint16_t revision = 0xFFFF;
    const void* pixels = nullptr;
    bool provisional = false;  // built before the game had filled the palette in
    bool effect = false;       // glow artwork rather than a cutout; see the header
    uint64_t key = 0;          // which frame of artwork this record is showing
};

std::map<const void*, CachedTexture> g_deviceTextures;

EffectSpriteSettings g_effects;
int g_effectFrames = 0;
int g_classifiedFrames = 0;

float Luminance(uint32_t argb) {
    // Rec.601, which is what "how bright does this look" means here; the exact
    // weights matter far less than the fringe being near zero and the core not.
    const float r = static_cast<float>((argb >> 16) & 0xFF);
    const float g = static_cast<float>((argb >> 8) & 0xFF);
    const float b = static_cast<float>(argb & 0xFF);
    return 0.299f * r + 0.587f * g + 0.114f * b;
}

// Everything the classification is decided from, kept rather than reduced to a
// yes/no, because the interesting question is always "how close was it?" - a
// sprite with a black rim that did not qualify is a threshold to move, and the
// only way to know by how much is to have the numbers.
struct EffectMeasure {
    bool  hasCutout = false;
    int   fringeTexels = 0;
    int   opaqueTexels = 0;
    float fringeMedian = 0.0f;   // median luminance of the opaque texels on the boundary
    float fringeMean = 0.0f;
    float fringeDarkFraction = 0.0f;  // share of the boundary below 40, for context
    float peak = 0.0f;                // brightest texel anywhere in the sprite
};

// Is this frame of artwork a glow rather than a cutout?
//
// The test is on the *opaque* texels that touch the transparent region: for a
// fence, a tree or a car those are ordinary picture, whatever colour the artist
// used; for a fireball they are the black the glow fades out into. The median
// rather than the mean, so one stray dark pixel on a car cannot swing it.
EffectMeasure MeasureEffect(const uint32_t* image, int width, int height) {
    EffectMeasure m;
    if (!image || width < 3 || height < 3) return m;

    std::vector<float> fringe;
    fringe.reserve(static_cast<size_t>(width) * 2 + height * 2);

    auto clearAt = [&](int x, int y) {
        if (x < 0 || y < 0 || x >= width || y >= height) return true;  // past the edge
        return (image[static_cast<size_t>(y) * width + x] >> 24) == 0;
    };

    double sum = 0.0;
    int dark = 0;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const uint32_t texel = image[static_cast<size_t>(y) * width + x];
            if ((texel >> 24) == 0) {
                m.hasCutout = true;
                continue;
            }
            ++m.opaqueTexels;
            const float luma = Luminance(texel);
            if (luma > m.peak) m.peak = luma;
            if (clearAt(x - 1, y) || clearAt(x + 1, y) || clearAt(x, y - 1) || clearAt(x, y + 1)) {
                fringe.push_back(luma);
                sum += luma;
                if (luma < 40.0f) ++dark;
            }
        }
    }
    m.fringeTexels = static_cast<int>(fringe.size());
    if (fringe.empty()) return m;

    std::nth_element(fringe.begin(), fringe.begin() + fringe.size() / 2, fringe.end());
    m.fringeMedian = fringe[fringe.size() / 2];
    m.fringeMean = static_cast<float>(sum / fringe.size());
    m.fringeDarkFraction = static_cast<float>(dark) / static_cast<float>(fringe.size());
    return m;
}

bool IsEffect(const EffectMeasure& m, const EffectSpriteSettings& settings) {
    // No hole at all is a solid bitmap - a HUD panel, a road tile - and has no
    // fringe to judge.
    if (!m.hasCutout || !m.fringeTexels) return false;
    // The outline is black, so the artwork is a glow.
    if (m.fringeMedian < settings.edgeLuma) return true;
    // Or the whole sprite is black, which is the same glow three frames later.
    // Whatever it is, an opaque near-black world sprite is wrong under a path
    // tracer; drawn additively it fades out instead of sitting there.
    if (settings.faintLuma > 0.0f && m.peak < settings.faintLuma) return true;
    return false;
}

// --- The texture report ---------------------------------------------------
//
// One row per distinct frame of artwork the session built, with the numbers the
// classification was decided from and whether the world-space sprite pass ever
// drew it. Written beside the game on shutdown, next to a folder of the frames
// themselves as 32-bit TGAs, so a sprite that still has a black rim can be
// looked at rather than guessed at.
//
// Costs nothing to leave on: the frames are a few kilobytes each and there are a
// few hundred of them in a session.
struct FrameNote {
    uint64_t key = 0;
    int width = 0, height = 0;
    int palette = 0;
    EffectMeasure measure;
    bool classified = false;   // came out an effect under the settings at build time
    bool drawnAsSprite = false;
    bool dumped = false;
};

std::map<uint64_t, FrameNote> g_notes;
bool g_dumpTextures = true;
// See CloseArtworkHoles in alpha_bleed.h.
bool g_closeHoles = true;
int  g_closeHoleMax = 0;
int  g_holesClosed = 0;
char g_dumpDir[MAX_PATH] = "";
volatile LONG g_dumped = 0;   // the car art worker dumps too
const int kMaxDumped = 2048;

// Where the game is, which is where everything else this DLL writes goes.
const char* DumpDir() {
    if (!g_dumpDir[0]) {
        GetModuleFileNameA(nullptr, g_dumpDir, sizeof(g_dumpDir));
        char* slash = strrchr(g_dumpDir, '\\');
        if (slash) strcpy(slash + 1, "gta2dx9_textures");
        else strcpy(g_dumpDir, "gta2dx9_textures");
    }
    return g_dumpDir;
}

// 32-bit uncompressed TGA, top-left origin. Chosen over anything nicer because
// the pixels are already B,G,R,A in memory order, so the body is one write and
// there is no encoder to get wrong.
bool WriteTga(const char* path, const uint32_t* image, int width, int height) {
    FILE* out = fopen(path, "wb");
    if (!out) return false;
    uint8_t header[18] = {};
    header[2] = 2;   // uncompressed true colour
    header[12] = static_cast<uint8_t>(width & 0xFF);
    header[13] = static_cast<uint8_t>((width >> 8) & 0xFF);
    header[14] = static_cast<uint8_t>(height & 0xFF);
    header[15] = static_cast<uint8_t>((height >> 8) & 0xFF);
    header[16] = 32;
    header[17] = 0x28;   // 8 alpha bits, rows top to bottom
    fwrite(header, 1, sizeof(header), out);
    fwrite(image, 4, static_cast<size_t>(width) * height, out);
    fclose(out);
    return true;
}

void DumpFrame(uint64_t key, const uint32_t* image, int width, int height) {
    if (!g_dumpTextures || g_dumped >= kMaxDumped) return;
    CreateDirectoryA(DumpDir(), nullptr);
    char path[MAX_PATH];
    _snprintf(path, sizeof(path) - 1, "%s\\%016llX.tga", DumpDir(),
              static_cast<unsigned long long>(key));
    path[sizeof(path) - 1] = '\0';
    if (WriteTga(path, image, width, height)) InterlockedIncrement(&g_dumped);
}

// Every distinct frame of artwork ever seen, keyed by its content, and the owner
// of all the D3D textures.
//
// GTA2 animates a tile by rewriting the pixels behind the same texture record -
// ceiling fans, screens, water, traffic lights. Filling those new pixels back
// into the same IDirect3DTexture9, which is what this used to do, gives RTX
// Remix one texture whose content changes: it appears once in the texture picker
// and animates there, and there is no way to replace a single frame of it.
//
// Giving each distinct frame its own texture object gives each its own stable
// Remix hash, so every frame shows up separately and can be replaced on its own.
// The cost is one texture per frame rather than per record, which is bounded by
// how much animation the artwork actually has - a few hundred at most, and
// identical frames still share one entry because the key is the content.
struct Frame {
    IDirect3DTexture9* texture = nullptr;
    bool effect = false;
};
std::map<uint64_t, Frame> g_frames;

// Hashed off the palette indices rather than the finished RGBA, because that is
// the smaller buffer and it is what actually changed.
uint64_t ArtKey(int width, int height, uint16_t palette, const uint8_t* indices, int stride) {
    uint64_t h = 0xCBF29CE484222325ULL;
    auto mix = [&h](uint64_t v) {
        h ^= v;
        h *= 0x100000001B3ULL;
    };
    mix(static_cast<uint64_t>(width));
    mix(static_cast<uint64_t>(height));
    // Two sprites with the same indices and different palettes are different
    // pictures, so the palette is part of the identity.
    mix(palette);
    for (int y = 0; y < height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * stride;
        for (int x = 0; x < width; ++x) mix(row[x]);
    }
    return h;
}

uint64_t FrameKey(const TextureRecord* record) {
    return ArtKey(record->width, record->height, record->palette,
                  static_cast<const uint8_t*>(record->pixels), kPageStride);
}

// The artwork without its colour: size and palette indices only. Two draws of
// the same strip in different palettes get the same key, which is the point.
uint64_t IndexKey(int width, int height, const uint8_t* indices, int stride) {
    uint64_t h = 0xCBF29CE484222325ULL;
    auto mix = [&h](uint64_t v) {
        h ^= v;
        h *= 0x100000001B3ULL;
    };
    mix(static_cast<uint64_t>(width));
    mix(static_cast<uint64_t>(height));
    for (int y = 0; y < height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * stride;
        for (int x = 0; x < width; ++x) mix(row[x]);
    }
    return h;
}

std::set<uint64_t> g_decalKeys;
int g_decalMaxSide = 0;

// Per record, re-decided only when the record is pointed at other artwork.
struct DecalVerdict {
    const void* pixels = nullptr;
    uint16_t revision = 0xFFFF;
    uint16_t width = 0, height = 0;
    bool decal = false;
};
std::map<const void*, DecalVerdict> g_decalVerdicts;

// A hash that turned out not to be stable would otherwise grow this without
// limit and exhaust video memory in a long session.
const size_t kMaxFrames = 8192;
bool g_frameLimitLogged = false;
// Set when the limit is reached: a car's artwork is a new frame for every state of its
// damage and paint, so a long session of fighting fills the table with frames nobody will
// see again, and from then on a new frame was refused - the record kept showing the artwork
// it had last, a stale and sometimes a different car's, which is the damaged car drawn as a
// low-resolution sprite of the wrong shape. The world view empties the table, at the start of
// a frame, and the artwork that is in use is built again.
bool g_flushRequested = false;


// The pixel work a frame of artwork gets before it becomes a texture, shared by
// the render thread's build and the car art worker so both make the same texels.
// The settings are copied in, because the worker must not read the menu's.
struct ArtSettings {
    EffectSpriteSettings effects;
    bool closeHoles = true;
    int closeHoleMax = 0;
    float feather = 0.0f;
};

void ClassifyArtwork(const uint32_t* image, int width, int height, bool mayBeEffect,
                     const ArtSettings& st, EffectMeasure* measure, bool* isEffect) {
    *measure = MeasureEffect(image, width, height);
    *isEffect = mayBeEffect && st.effects.mode != EffectSpriteMode::Off && IsEffect(*measure, st.effects);
}

// Returns how many texels CloseArtworkHoles closed.
int FinishArtwork(uint32_t* image, int width, int height, bool isEffect, const ArtSettings& st) {
    const size_t n = static_cast<size_t>(width) * height;
    if (isEffect && st.effects.mode == EffectSpriteMode::Additive) {
        // Additive wants the transparent texels to stay pure black: with
        // SRCBLEND ONE they are *added* to the frame, so a bled colour out there
        // would paint a square halo round the sprite. Black adds nothing, and
        // filtering across the boundary then fades the glow out exactly the way
        // the artwork intends.
        for (size_t i = 0; i < n; ++i) {
            if ((image[i] >> 24) == 0) image[i] = 0u;
        }
        return 0;
    }
    if (isEffect && st.effects.mode == EffectSpriteMode::Cutout) {
        // Keep the alpha test, and give it something to cut: the artwork's own
        // brightness becomes its alpha, so the black fringe fades out instead of
        // being drawn. The colour is left alone - dimming it as well would take
        // the heat out of the fireball's edge.
        for (size_t i = 0; i < n; ++i) {
            if ((image[i] >> 24) == 0) continue;
            const float faded = Luminance(image[i]) * st.effects.cutoutGain;
            const uint32_t alpha = faded >= 255.0f ? 255u : static_cast<uint32_t>(faded + 0.5f);
            image[i] = (alpha << 24) | (image[i] & 0x00FFFFFFu);
        }
        gta2::BleedTransparentEdges(image, width, height);
        return 0;
    }
    // Keyed texels are transparent *black*, and every filter that touches
    // this texture - ours, and the mipmaps Remix builds for its own
    // materials - averages that black into the neighbouring colour. That is
    // the hard black rim around cutouts. Give the invisible texels a colour
    // and it goes away.
    gta2::BleedTransparentEdges(image, width, height);
    // Slits and speckles the artist drew in the key colour, which are holes
    // to a path tracer and were an outline to GTA2. Before the feather,
    // which reads alpha and would otherwise soften an edge about to close.
    int closed = 0;
    if (st.closeHoles) closed = gta2::CloseArtworkHoles(image, width, height, st.closeHoleMax);
    // And then invent the gradient the artwork never had. Off by default: a
    // fence wants its hard edge, an explosion does not.
    gta2::FeatherAlpha(image, width, height, st.feather);
    return closed;
}

// --- Car sprite artwork off the render thread (PERF-4) ---------------------
//
// See the header. The worker gets copies of the palette indices and colours, never
// the game's own memory, which it rewrites whenever it likes; everything that
// touches the device or the caches stays on the render thread.

double ArtNowMs() {
    static LARGE_INTEGER freq = {};
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return 1000.0 * static_cast<double>(t.QuadPart) / static_cast<double>(freq.QuadPart);
}

struct CarArtJob {
    uint64_t key = 0;
    int width = 0, height = 0;
    uint16_t palette = 0;
    int sprite = -1;                 // the car sprite, for a precached frame
    bool precache = false;
    bool dump = false;
    std::vector<uint8_t> indices;    // width * height, rows packed
    uint32_t colours[kPaletteEntries];
    ArtSettings settings;
    double asked = 0.0;              // when the render thread asked, ms
};
struct CarArtDone {
    CarArtJob job;
    std::vector<uint32_t> image;
    EffectMeasure measure;
    bool isEffect = false;
    int holes = 0;
    double ms = 0.0;
};
// One car sprite of the style: its artwork and every palette it is drawn in.
struct CarSpriteArt {
    int sprite = 0;
    int width = 0, height = 0;
    std::vector<uint8_t> indices;
    std::vector<uint16_t> palettes;
};

CRITICAL_SECTION g_artLock;
HANDLE g_artWake = nullptr;
bool g_artStarted = false, g_artFailed = false;
// Under g_artLock.
std::deque<CarArtJob*> g_artUrgent, g_artIdle;
std::vector<CarArtDone*> g_artDone;
std::string g_artParsePath;
std::vector<CarSpriteArt>* g_artParsed = nullptr;
volatile LONG g_artMail = 0;   // something for the render thread: a parse or a finished frame

// Render thread only.
std::vector<CarSpriteArt> g_carSprites;
std::vector<char> g_carPalette;                  // 65536 flags: a palette some car is drawn in
std::unordered_set<uint32_t> g_carShapes;        // width << 16 | height of a car sprite
std::unordered_map<uint64_t, std::vector<int>> g_carByShapePal;   // (shape, palette) -> sprites
std::unordered_map<uint64_t, uint64_t> g_carBaseKey;             // (sprite, palette) -> frame key
std::unordered_map<uint64_t, int> g_artPending;  // key -> 1 queued ahead, 2 asked for urgently
std::unordered_map<uint64_t, int> g_artWaits;    // key -> stand-in answers while it was built
std::unordered_set<uint64_t> g_artPrecached;     // made ahead and not yet asked for
std::vector<std::pair<int, uint16_t>> g_precacheTodo;   // (index into g_carSprites, palette)
size_t g_precacheAt = 0;
int g_precacheQueued = 0, g_precacheUploaded = 0, g_precacheRetries = 0;
double g_precacheStart = 0.0, g_precacheBytes = 0.0;
bool g_precacheLogged = true;
IDirect3DTexture9* g_standIn = nullptr;
// The upload budget, per 20 ms window (about a frame at the 30 fps cap; the
// render thread's frames are not visible from here).
constexpr double kArtWindowMs = 20.0;
constexpr int kUrgentPerWindow = 4;
constexpr double kUrgentMsPerWindow = 2.0;
constexpr int kAheadPerWindow = 6;
constexpr double kAheadMsPerWindow = 1.0;
double g_artWindow = -1e9;
int g_artWindowUrgent = 0, g_artWindowAhead = 0;
double g_artWindowMs = 0.0;
struct CarArtStats {
    int urgentBuilt = 0, aheadBuilt = 0, standIns = 0, standInsStale = 0, standInsBase = 0,
        standInsBlank = 0, precacheHits = 0, dynamicFailed = 0, slowUploads = 0;
    double workerMs = 0.0, workerMax = 0.0, uploadMs = 0.0, uploadMax = 0.0, waitMax = 0.0;
    int uploads = 0;
} g_artStats;

uint64_t ShapePal(int width, int height, uint16_t palette) {
    return (static_cast<uint64_t>(width) << 32) | (static_cast<uint64_t>(height) << 16) | palette;
}
uint64_t SpritePal(int sprite, uint16_t palette) {
    return (static_cast<uint64_t>(sprite) << 16) | palette;
}

// The car sprites of a style file and the palettes their models are drawn in:
// a sprite's own (PALX at tiles + sprite) and each remap its CARI entries list
// (PALX at tiles + all sprites + remap). The game registers a car's texture with
// that physical palette: sprite 33 in remap 9 came as palette 176 = PALX[992 +
// 2089 + 9] in wil.sty.
bool ParseCarSprites(const std::string& path, std::vector<CarSpriteArt>* out) {
    FILE* in = fopen(path.c_str(), "rb");
    if (!in) return false;
    std::vector<uint8_t> data;
    fseek(in, 0, SEEK_END);
    const long size = ftell(in);
    fseek(in, 0, SEEK_SET);
    if (size > 0 && size < (64L << 20)) {
        data.resize(static_cast<size_t>(size));
        if (fread(data.data(), 1, data.size(), in) != data.size()) data.clear();
    }
    fclose(in);
    if (data.size() < 6) return false;
    auto u16 = [&](size_t at) { return static_cast<uint16_t>(data[at] | (data[at + 1] << 8)); };
    auto u32 = [&](size_t at) {
        return static_cast<uint32_t>(data[at] | (data[at + 1] << 8) | (data[at + 2] << 16) |
                                     (static_cast<uint32_t>(data[at + 3]) << 24));
    };
    size_t sprgOff = 0, sprgSize = 0, sprxOff = 0, sprxSize = 0, palxOff = 0, palxSize = 0;
    size_t cariOff = 0, cariSize = 0;
    uint16_t palb[2] = {0, 0}, carSprites = 0;
    for (size_t at = 6; at + 8 <= data.size();) {
        const size_t body = at + 8, len = u32(at + 4);
        if (body + len > data.size()) break;
        if (!memcmp(&data[at], "SPRG", 4)) { sprgOff = body; sprgSize = len; }
        else if (!memcmp(&data[at], "SPRX", 4)) { sprxOff = body; sprxSize = len; }
        else if (!memcmp(&data[at], "PALX", 4)) { palxOff = body; palxSize = len; }
        else if (!memcmp(&data[at], "CARI", 4)) { cariOff = body; cariSize = len; }
        else if (!memcmp(&data[at], "PALB", 4) && len >= 4) { palb[0] = u16(body); palb[1] = u16(body + 2); }
        else if (!memcmp(&data[at], "SPRB", 4) && len >= 2) { carSprites = u16(body); }
        at = body + len;
    }
    if (!sprgSize || !sprxSize || !palxSize || !carSprites) return false;
    auto palx = [&](size_t slot) -> int {
        return slot * 2 + 2 <= palxSize ? u16(palxOff + slot * 2) : -1;
    };
    out->clear();
    for (int n = 0; n < carSprites && static_cast<size_t>(n) * 8 + 8 <= sprxSize; ++n) {
        const size_t e = sprxOff + static_cast<size_t>(n) * 8;
        CarSpriteArt art;
        art.sprite = n;
        art.width = data[e + 4];
        art.height = data[e + 5];
        const size_t offset = u32(e);
        if (art.width < 4 || art.height < 4 || (offset % kPageStride) + art.width > kPageStride ||
            offset + static_cast<size_t>(art.height - 1) * kPageStride + art.width > sprgSize) {
            continue;
        }
        art.indices.resize(static_cast<size_t>(art.width) * art.height);
        for (int y = 0; y < art.height; ++y) {
            memcpy(&art.indices[static_cast<size_t>(y) * art.width],
                   &data[sprgOff + offset + static_cast<size_t>(y) * kPageStride], art.width);
        }
        const int own = palx(static_cast<size_t>(palb[0]) + n);
        if (own >= 0) art.palettes.push_back(static_cast<uint16_t>(own));
        out->push_back(std::move(art));
    }
    // CARI: model, sprite flag (1: art of its own, 0: the previous model's), width, height,
    // remap count, passengers, wreck, rating, four offsets, two flag bytes, the remaps, the
    // door count and two bytes a door. See gta2_style.cpp.
    int sprite = -1;
    for (size_t at = cariOff; cariSize && at + 14 <= cariOff + cariSize;) {
        const uint8_t* r = &data[at];
        const int remaps = r[4];
        if (at + 14 + remaps + 1 > cariOff + cariSize) break;
        if (r[1]) ++sprite;
        const int doors = data[at + 14 + remaps];
        for (int i = 0; i < remaps && sprite >= 0; ++i) {
            const int pal = palx(static_cast<size_t>(palb[0]) + palb[1] + r[14 + i]);
            if (pal < 0) continue;
            for (CarSpriteArt& art : *out) {
                if (art.sprite != sprite) continue;
                if (std::find(art.palettes.begin(), art.palettes.end(), pal) == art.palettes.end()) {
                    art.palettes.push_back(static_cast<uint16_t>(pal));
                }
            }
        }
        at += 14 + remaps + 1 + 2 * static_cast<size_t>(doors);
    }
    return !out->empty();
}

DWORD WINAPI CarArtThread(void*) {
    NameThisThread("car art");
    for (;;) {
        std::string parse;
        CarArtJob* job = nullptr;
        EnterCriticalSection(&g_artLock);
        if (!g_artParsePath.empty()) { parse.swap(g_artParsePath); }
        else if (!g_artUrgent.empty()) { job = g_artUrgent.front(); g_artUrgent.pop_front(); }
        else if (!g_artIdle.empty()) { job = g_artIdle.front(); g_artIdle.pop_front(); }
        LeaveCriticalSection(&g_artLock);
        if (!parse.empty()) {
            auto* sprites = new std::vector<CarSpriteArt>;
            const double t0 = ArtNowMs();
            if (!ParseCarSprites(parse, sprites)) {
                Log("car art: could not read the car sprites of %s; car artwork is built as before",
                    parse.c_str());
                delete sprites;
                continue;
            }
            Log("car art: %zu car sprites read from %s in %.0f ms", sprites->size(), parse.c_str(),
                ArtNowMs() - t0);
            EnterCriticalSection(&g_artLock);
            delete g_artParsed;
            g_artParsed = sprites;
            LeaveCriticalSection(&g_artLock);
            InterlockedExchange(&g_artMail, 1);
            continue;
        }
        if (!job) {
            // Polled rather than woken: SetEvent is a wineserver round trip, and on a
            // busy host one cost the render thread 10-27 ms (p4_ax1_wil, the shells'
            // "car setup slow" lines). 2 ms of latency is nothing next to a frame.
            Sleep(2);
            continue;
        }
        auto* done = new CarArtDone;
        const double t0 = ArtNowMs();
        const int w = job->width, h = job->height;
        done->image.resize(static_cast<size_t>(w) * h);
        for (size_t i = 0, n = done->image.size(); i < n; ++i) {
            const uint8_t index = job->indices[i];
            done->image[i] = index ? (job->colours[index] | 0xFF000000u) : 0u;
        }
        ClassifyArtwork(done->image.data(), w, h, true, job->settings, &done->measure, &done->isEffect);
        if (job->dump && done->measure.hasCutout) DumpFrame(job->key, done->image.data(), w, h);
        done->holes = FinishArtwork(done->image.data(), w, h, done->isEffect, job->settings);
        done->ms = ArtNowMs() - t0;
        job->indices.clear();
        job->indices.shrink_to_fit();
        const bool ahead = job->precache;
        done->job = std::move(*job);
        delete job;
        const double ms = done->ms;
        EnterCriticalSection(&g_artLock);
        g_artDone.push_back(done);
        LeaveCriticalSection(&g_artLock);
        InterlockedExchange(&g_artMail, 1);
        // Work ahead of need takes at most about half of one CPU (the play container
        // has three, shared with the game, Wine and the VNC encoder), as PERF-3's.
        if (ahead) Sleep(static_cast<DWORD>((std::max)(2.0, ms)));
    }
}

bool CarArtStart() {
    if (g_artStarted) return true;
    if (g_artFailed) return false;
    DumpDir();   // filled in here, before the worker can race for it
    InitializeCriticalSection(&g_artLock);
    g_artWake = CreateEventA(nullptr, FALSE, FALSE, nullptr);
    HANDLE thread = g_artWake ? CreateThread(nullptr, 0, CarArtThread, nullptr, 0, nullptr) : nullptr;
    if (!thread) {
        g_artFailed = true;
        Log("car art: no worker thread; car artwork is built on the render thread as before");
        return false;
    }
    SetThreadPriority(thread, THREAD_PRIORITY_BELOW_NORMAL);
    CloseHandle(thread);
    g_artStarted = true;
    return true;
}

void CarArtPush(CarArtJob* job, bool urgent) {
    EnterCriticalSection(&g_artLock);
    if (urgent) g_artUrgent.push_back(job);
    else g_artIdle.push_back(job);
    LeaveCriticalSection(&g_artLock);
}

ArtSettings CurrentArtSettings() {
    ArtSettings st;
    st.effects = g_effects;
    st.closeHoles = CloseHoles();
    st.closeHoleMax = CloseHoleMax();
    st.feather = SpriteFeather();
    return st;
}

bool IsCarArt(const TextureRecord* record) {
    return !g_carPalette.empty() && g_carPalette[record->palette] &&
           g_carShapes.count((static_cast<uint32_t>(record->width) << 16) | record->height) != 0;
}

void InstallCarSprites(std::vector<CarSpriteArt>&& sprites) {
    g_carSprites = std::move(sprites);
    g_carPalette.assign(65536, 0);
    g_carShapes.clear();
    g_carByShapePal.clear();
    g_carBaseKey.clear();
    g_precacheTodo.clear();
    g_precacheAt = 0;
    for (size_t i = 0; i < g_carSprites.size(); ++i) {
        const CarSpriteArt& art = g_carSprites[i];
        g_carShapes.insert((static_cast<uint32_t>(art.width) << 16) | static_cast<uint32_t>(art.height));
        for (uint16_t pal : art.palettes) {
            g_carPalette[pal] = 1;
            g_carByShapePal[ShapePal(art.width, art.height, pal)].push_back(static_cast<int>(i));
            g_carBaseKey[SpritePal(static_cast<int>(i), pal)] =
                ArtKey(art.width, art.height, pal, art.indices.data(), art.width);
            g_precacheTodo.emplace_back(static_cast<int>(i), pal);
        }
    }
    g_precacheQueued = g_precacheUploaded = g_precacheRetries = 0;
    g_precacheBytes = 0.0;
    g_precacheStart = ArtNowMs();
    g_precacheLogged = false;
    Log("car art: %zu car sprites in %zu palettes to make ahead (%zu frames)", g_carSprites.size(),
        static_cast<size_t>(std::count(g_carPalette.begin(), g_carPalette.end(), 1)),
        g_precacheTodo.size());
}

// Up to a few dozen precache jobs a window: the palette colours copied from the
// game's pages as they stand now, which is only worth doing once the game has
// filled them in (a palette it has not is tried again a little later).
void QueuePrecache() {
    if (g_precacheTodo.empty()) return;
    std::vector<std::pair<int, uint16_t>> retry;
    const ArtSettings st = CurrentArtSettings();
    int queued = 0;
    while (g_precacheAt < g_precacheTodo.size() && queued < 48) {
        const auto item = g_precacheTodo[g_precacheAt++];
        const CarSpriteArt& art = g_carSprites[static_cast<size_t>(item.first)];
        const uint64_t key = g_carBaseKey[SpritePal(item.first, item.second)];
        if (g_frames.count(key) || g_artPending.count(key)) continue;
        bool has = false;
        const uint32_t* colours = PaletteColours(item.second, &has);
        if (!colours || !has) {
            retry.push_back(item);
            continue;
        }
        auto* job = new CarArtJob;
        job->key = key;
        job->width = art.width;
        job->height = art.height;
        job->palette = item.second;
        job->sprite = art.sprite;
        job->precache = true;
        job->indices = art.indices;
        memcpy(job->colours, colours, sizeof(job->colours));
        job->settings = st;
        job->asked = ArtNowMs();
        g_artPending[key] = 1;
        CarArtPush(job, false);
        ++queued;
        ++g_precacheQueued;
    }
    if (g_precacheAt >= g_precacheTodo.size()) {
        // Palettes still empty are tried again from the start, for a while.
        g_precacheTodo.swap(retry);
        g_precacheAt = 0;
        if (!g_precacheTodo.empty() && ++g_precacheRetries > 3000) {
            Log("car art: %zu frames never had their palette filled in; left to be built when seen",
                g_precacheTodo.size());
            g_precacheTodo.clear();
        }
    } else {
        g_precacheTodo.insert(g_precacheTodo.end(), retry.begin(), retry.end());
    }
}

FrameNote& NoteFrame(uint64_t key, int width, int height, int palette, const EffectMeasure& measure,
                     bool isEffect) {
    FrameNote& note = g_notes[key];
    note.key = key;
    note.width = width;
    note.height = height;
    note.palette = palette;
    note.measure = measure;
    note.classified = isEffect;
    return note;
}

// A finished frame into a texture: dynamic, default pool, written with DISCARD,
// which wined3d serves from an upload buffer instead of waiting for the frame's
// queued GL work the way a managed texture's first lock does.
bool UploadCarArt(IDirect3DDevice9* device, CarArtDone* done) {
    const CarArtJob& job = done->job;
    if (g_frames.count(job.key)) {   // made already (asked for while it was queued ahead)
        g_artWaits.erase(job.key);
        return true;
    }
    if (g_frames.size() >= kMaxFrames) {
        g_flushRequested = true;
        return false;
    }
    const double t0 = ArtNowMs();
    IDirect3DTexture9* tex = nullptr;
    bool dynamic = true;
    if (FAILED(device->CreateTexture(job.width, job.height, 1, D3DUSAGE_DYNAMIC, D3DFMT_A8R8G8B8,
                                     D3DPOOL_DEFAULT, &tex, nullptr)) || !tex) {
        ++g_artStats.dynamicFailed;
        dynamic = false;
        tex = nullptr;
        if (FAILED(device->CreateTexture(job.width, job.height, 1, 0, D3DFMT_A8R8G8B8,
                                         D3DPOOL_MANAGED, &tex, nullptr)) || !tex) {
            return false;
        }
    }
    D3DLOCKED_RECT locked;
    if (FAILED(tex->LockRect(0, &locked, nullptr, dynamic ? D3DLOCK_DISCARD : 0))) {
        ++g_trouble.lockFailed;
        tex->Release();
        return false;
    }
    for (int y = 0; y < job.height; ++y) {
        memcpy(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch,
               done->image.data() + static_cast<size_t>(y) * job.width,
               static_cast<size_t>(job.width) * 4);
    }
    tex->UnlockRect(0);
    const double ms = ArtNowMs() - t0;
    g_frames[job.key] = Frame{tex, done->isEffect};
    ++g_classifiedFrames;
    if (done->isEffect) ++g_effectFrames;
    g_holesClosed += done->holes;
    ++g_trouble.built;
    FrameNote& note = NoteFrame(job.key, job.width, job.height, job.palette, done->measure, done->isEffect);
    if (job.dump) note.dumped = true;
    ++g_artStats.uploads;
    g_artStats.uploadMs += ms;
    g_artStats.uploadMax = (std::max)(g_artStats.uploadMax, ms);
    g_artStats.workerMs += done->ms;
    g_artStats.workerMax = (std::max)(g_artStats.workerMax, done->ms);
    if (ms > 3.0 && g_artStats.slowUploads++ < 40) {
        Log("car art: an upload took %.1f ms (%dx%d, %s)", ms, job.width, job.height,
            job.precache ? "made ahead" : "asked for");
    }
    if (job.precache) {
        ++g_precacheUploaded;
        g_precacheBytes += 4.0 * job.width * job.height;
        g_artPrecached.insert(job.key);
        ++g_artStats.aheadBuilt;
    } else {
        ++g_artStats.urgentBuilt;
        const double waited = ArtNowMs() - job.asked;
        g_artStats.waitMax = (std::max)(g_artStats.waitMax, waited);
        const auto waits = g_artWaits.find(job.key);
        const int answers = waits == g_artWaits.end() ? 0 : waits->second;
        if (waits != g_artWaits.end()) g_artWaits.erase(waits);
        if (g_artStats.urgentBuilt <= 60) {
            Log("car art: %dx%d in palette %u made on the worker in %.1f ms, uploaded in %.2f ms, "
                "%.0f ms after it was asked for (%d draws with a stand-in)",
                job.width, job.height, static_cast<unsigned>(job.palette), done->ms, ms, waited, answers);
        }
    }
    return true;
}

// The render thread's side, run from DeviceTextureFor (the only place it can be
// sure of a device): take a parse, queue precache jobs, upload finished frames
// within the window's budget.
void PumpCarArt(IDirect3DDevice9* device) {
    if (!g_artStarted) return;
    const double now = ArtNowMs();
    const bool newWindow = now - g_artWindow >= kArtWindowMs;
    if (newWindow) {
        g_artWindow = now;
        g_artWindowUrgent = g_artWindowAhead = 0;
        g_artWindowMs = 0.0;
    }
    if (InterlockedExchange(&g_artMail, 0) == 0) {
        if (newWindow) QueuePrecache();
        return;
    }
    std::vector<CarSpriteArt>* parsed = nullptr;
    std::vector<CarArtDone*> done;
    EnterCriticalSection(&g_artLock);
    parsed = g_artParsed;
    g_artParsed = nullptr;
    done.swap(g_artDone);
    LeaveCriticalSection(&g_artLock);
    if (parsed) {
        InstallCarSprites(std::move(*parsed));
        delete parsed;
    }
    if (newWindow) QueuePrecache();
    // Asked-for frames first.
    std::stable_partition(done.begin(), done.end(), [](const CarArtDone* d) { return !d->job.precache; });
    std::vector<CarArtDone*> later;
    for (CarArtDone* d : done) {
        const bool urgent = !d->job.precache;
        const bool fits = urgent ? (g_artWindowUrgent == 0 ||
                                    (g_artWindowUrgent < kUrgentPerWindow && g_artWindowMs < kUrgentMsPerWindow))
                                 : (g_artWindowAhead < kAheadPerWindow && g_artWindowMs < kAheadMsPerWindow);
        if (!fits) {
            later.push_back(d);
            continue;
        }
        const double t0 = ArtNowMs();
        UploadCarArt(device, d);
        g_artWindowMs += ArtNowMs() - t0;
        if (urgent) ++g_artWindowUrgent;
        else ++g_artWindowAhead;
        g_artPending.erase(d->job.key);
        delete d;
    }
    if (!later.empty()) {
        EnterCriticalSection(&g_artLock);
        g_artDone.insert(g_artDone.begin(), later.begin(), later.end());
        LeaveCriticalSection(&g_artLock);
        InterlockedExchange(&g_artMail, 1);
    }
    if (!g_precacheLogged && g_precacheTodo.empty() && g_precacheUploaded >= g_precacheQueued &&
        g_precacheQueued > 0) {
        bool idle = true;
        for (const auto& p : g_artPending) if (p.second == 1) { idle = false; break; }
        if (idle) {
            g_precacheLogged = true;
            Log("car art: made ahead %d frames (%.1f MB of texels) in %.1f s; uploads mean %.2f ms, max %.2f ms; "
                "worker mean %.2f ms, max %.1f ms; %d dynamic textures refused",
                g_precacheUploaded, g_precacheBytes / (1 << 20), (ArtNowMs() - g_precacheStart) / 1000.0,
                g_artStats.uploads ? g_artStats.uploadMs / g_artStats.uploads : 0.0, g_artStats.uploadMax,
                g_artStats.uploads ? g_artStats.workerMs / g_artStats.uploads : 0.0, g_artStats.workerMax,
                g_artStats.dynamicFailed);
        }
    }
}

// What to draw a car with while its new artwork is made: the record's previous
// artwork if it is the same size (the same car before a door or a dent), else
// the precached frame of the car sprite in this palette that its pixels match
// best (the car without the delta), else a transparent stand-in.
IDirect3DTexture9* CarArtStandIn(IDirect3DDevice9* device, const TextureRecord* record,
                                 const CachedTexture& cached, bool* effect) {
    ++g_artStats.standIns;
    if (cached.texture && cached.width == record->width && cached.height == record->height) {
        ++g_artStats.standInsStale;
        *effect = cached.effect;
        return cached.texture;
    }
    *effect = false;
    const auto candidates = g_carByShapePal.find(ShapePal(record->width, record->height, record->palette));
    if (candidates != g_carByShapePal.end()) {
        IDirect3DTexture9* best = nullptr;
        int bestScore = -1;
        const uint8_t* pixels = static_cast<const uint8_t*>(record->pixels);
        for (int i : candidates->second) {
            const auto key = g_carBaseKey.find(SpritePal(i, record->palette));
            if (key == g_carBaseKey.end()) continue;
            const auto frame = g_frames.find(key->second);
            if (frame == g_frames.end() || !frame->second.texture) continue;
            const CarSpriteArt& art = g_carSprites[static_cast<size_t>(i)];
            int score = 0;
            for (int y = 0; y < art.height; y += 2) {
                const uint8_t* row = pixels + static_cast<size_t>(y) * kPageStride;
                const uint8_t* mine = art.indices.data() + static_cast<size_t>(y) * art.width;
                for (int x = 0; x < art.width; x += 2) score += row[x] == mine[x];
            }
            if (score > bestScore) {
                bestScore = score;
                best = frame->second.texture;
            }
        }
        if (best) {
            ++g_artStats.standInsBase;
            return best;
        }
    }
    if (!g_standIn) {
        if (SUCCEEDED(device->CreateTexture(8, 8, 1, D3DUSAGE_DYNAMIC, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT,
                                            &g_standIn, nullptr)) && g_standIn) {
            D3DLOCKED_RECT locked;
            if (SUCCEEDED(g_standIn->LockRect(0, &locked, nullptr, D3DLOCK_DISCARD))) {
                for (int y = 0; y < 8; ++y) memset(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch, 0, 32);
                g_standIn->UnlockRect(0);
            }
        }
    }
    ++g_artStats.standInsBlank;
    return g_standIn;
}

// A car frame the cache does not have, asked for on the worker. Null when it has
// to be built here after all (no worker, or the game has not filled the palette).
IDirect3DTexture9* DeferCarArt(IDirect3DDevice9* device, const TextureRecord* record, uint64_t key,
                               const CachedTexture& cached, bool* effect) {
    if (!g_artStarted || !IsCarArt(record)) return nullptr;
    auto pending = g_artPending.find(key);
    if (pending == g_artPending.end() || pending->second == 1) {
        bool has = false;
        const uint32_t* colours = PaletteColours(record->palette, &has);
        if (!colours || !has) return nullptr;   // a provisional build, as before
        auto* job = new CarArtJob;
        job->key = key;
        job->width = record->width;
        job->height = record->height;
        job->palette = record->palette;
        job->indices.resize(static_cast<size_t>(record->width) * record->height);
        const uint8_t* pixels = static_cast<const uint8_t*>(record->pixels);
        for (int y = 0; y < record->height; ++y) {
            memcpy(&job->indices[static_cast<size_t>(y) * record->width], pixels + static_cast<size_t>(y) * kPageStride,
                   record->width);
        }
        memcpy(job->colours, colours, sizeof(job->colours));
        job->settings = CurrentArtSettings();
        const auto note = g_notes.find(key);
        job->dump = g_dumpTextures && (note == g_notes.end() || !note->second.dumped);
        job->asked = ArtNowMs();
        // Queued ahead and not built yet: asked for again, first in line (whichever
        // copy finishes first is uploaded, the other is dropped).
        g_artPending[key] = 2;
        CarArtPush(job, true);
    }
    ++g_artWaits[key];
    IDirect3DTexture9* stand = CarArtStandIn(device, record, cached, effect);
    return stand;
}

}  // namespace

void CarArtPrecache(const char* stylePath) {
    if (!stylePath || !*stylePath) return;
    if (!CarArtStart()) return;
    EnterCriticalSection(&g_artLock);
    g_artParsePath = stylePath;
    LeaveCriticalSection(&g_artLock);
    SetEvent(g_artWake);
}

EffectSpriteSettings& EffectSprites() { return g_effects; }
int EffectSpriteFrames() { return g_effectFrames; }
int ClassifiedFrames() { return g_classifiedFrames; }

// The gang emblems: sprites 1257-1263 of the style file, which the game lays on the roofs of the
// Loonies, Yakuza, Zaibatsu, Rednecks, SRS, Krishna and Russian Mafia cars (and in the respect
// bars). Identified by the palette indices alone, hashed exactly as IndexKey does, because the
// game draws them in whatever palette the car's gang calls for. Keys read off bil.sty.
uint64_t SpriteIndexKey(const void* handle) {
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || !record->width || !record->height) return 0;
    return IndexKey(record->width, record->height, static_cast<const uint8_t*>(record->pixels),
                    kPageStride);
}

int GangLogoFor(const void* handle) {
    static const struct { uint64_t key; int id; } kLogos[] = {
        {0xAAAE0A921CA11FD3ULL, kLogoLoonies},  {0x62E50F443CC91F8FULL, kLogoYakuza},
        {0x61B129905C026E88ULL, kLogoZaibatsu}, {0xFB012EC211143064ULL, kLogoRednecks},
        {0xF0E058CC9766FC28ULL, kLogoSrs},      {0x6F5B436E2DE3B73AULL, kLogoKrishna},
        {0xB3824FE9EDF3643AULL, kLogoRussian},
    };
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || record->width > 32 || record->height > 32 ||
        record->width < 8 || record->height < 8) {
        return -1;
    }
    // Per record, re-decided only when the record is pointed at other artwork.
    struct Verdict { const void* pixels = nullptr; uint16_t revision = 0xFFFF; uint16_t palette = 0xFFFF; int id = -1; };
    static std::map<const void*, Verdict> verdicts;
    Verdict& v = verdicts[handle];
    if (v.pixels == record->pixels && v.revision == record->revision && v.palette == record->palette) return v.id;
    v.pixels = record->pixels;
    v.revision = record->revision;
    v.palette = record->palette;
    v.id = -1;
    const uint64_t key = SpriteIndexKey(handle);
    for (const auto& logo : kLogos) {
        if (logo.key == key) v.id = logo.id;
    }
    return v.id;
}

bool TextureIsEffect(const void* handle) {
    const auto it = g_deviceTextures.find(handle);
    return it != g_deviceTextures.end() && it->second.effect;
}

IDirect3DTexture9* DeviceTextureFor(IDirect3DDevice9* device, const void* handle, bool* effect,
                                    bool mayBeEffect) {
    if (effect) *effect = false;
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!device || !record || !record->pixels || !record->width || !record->height) return nullptr;
    PumpCarArt(device);

    CachedTexture& cached = g_deviceTextures[handle];
    // A texture built from a palette the game had not filled in yet is kept but
    // not trusted, so the next frame builds it again rather than leaving it
    // black for good.
    // An effect texture handed to a caller that says it cannot be one is rebuilt
    // below as ordinary artwork, which then replaces it for good.
    const bool wrongKind = cached.effect && !mayBeEffect;
    if (cached.texture && !cached.provisional && !wrongKind && cached.width == record->width &&
        cached.height == record->height && cached.palette == record->palette &&
        cached.revision == record->revision) {
        // The four fields the original cache keyed on can all be unchanged while
        // the record has been pointed at different artwork: GTA2 recycles its
        // texture records, and a record reused for another sprite of the same
        // size and palette looks identical here. Counted rather than acted on
        // for now, to find out whether it happens at all.
        if (cached.pixels != record->pixels) ++g_trouble.pixelsMovedSilently;
        if (effect) *effect = cached.effect;
        return cached.texture;
    }

    // The content decides which texture this is. An animated tile cycling back
    // to a frame it has already shown gets the same object again, and with it the
    // same Remix hash, which is the whole point.
    const uint64_t key = FrameKey(record);
    const auto existing = g_frames.find(key);
    if (existing != g_frames.end() && !(existing->second.effect && !mayBeEffect)) {
        cached.texture = existing->second.texture;
        cached.width = record->width;
        cached.height = record->height;
        cached.palette = record->palette;
        cached.revision = record->revision;
        cached.pixels = record->pixels;
        cached.provisional = false;
        cached.effect = existing->second.effect;
        cached.key = key;
        if (!g_artPrecached.empty() && g_artPrecached.erase(key)) ++g_artStats.precacheHits;
        if (effect) *effect = cached.effect;
        return cached.texture;
    }

    if (g_frames.size() >= kMaxFrames) {
        if (!g_frameLimitLogged) {
            g_frameLimitLogged = true;
            Log("texture cache: %u distinct frames, refusing more. Either this district has "
                "extraordinary amounts of animation or the frame hash is not stable.",
                static_cast<unsigned>(g_frames.size()));
        }
        g_flushRequested = true;
        return cached.texture;   // whatever we had last, rather than nothing, until the flush
    }

    // Never reused: each frame owns its texture for the life of the process, so
    // that its Remix hash stays put.
    //
    // Built into a local and only published to the cache once it is complete.
    // This used to clear cached.texture up front and return null from any of the
    // three failures below, which threw away the artwork that was on screen a
    // frame ago *before* its replacement existed. GTA2 rewrites a record every
    // time the menu text changes, and if the palette had not been filled in yet
    // the caller got nothing - so a glyph blinked out for that frame, which is
    // the flicker when moving through the options. Keeping the last good texture
    // turns a failed rebuild into one stale frame, which nobody can see, rather
    // than one missing frame, which everybody can.
    //
    // It also stops the leak: the old path abandoned a created texture on every
    // failing frame without releasing it.
    //
    // A car's artwork is made on the worker instead (PERF-4); the car is drawn with
    // a stand-in until it is uploaded.
    if (mayBeEffect) {
        bool standInEffect = false;
        const double t0 = ArtNowMs();
        IDirect3DTexture9* stand = DeferCarArt(device, record, key, cached, &standInEffect);
        const double ms = ArtNowMs() - t0;
        static int slowDefers = 0;
        if (ms > 4.0 && slowDefers++ < 40) Log("car art: asking the worker took %.1f ms", ms);
        if (stand) {
            if (effect) *effect = standInEffect;
            return stand;
        }
    }
    IDirect3DTexture9* fresh = nullptr;
    if (FAILED(device->CreateTexture(record->width, record->height, 1, 0, D3DFMT_A8R8G8B8,
                                     D3DPOOL_MANAGED, &fresh, nullptr))) {
        return cached.texture;
    }

    bool paletteHasColour = false;
    const uint32_t* palette = PaletteColours(record->palette, &paletteHasColour);
    if (!palette) {
        ++g_trouble.paletteMissing;
        fresh->Release();
        return cached.texture;
    }
    if (record->flags & 1) ++g_trouble.builtWhileLocked;  // game is mid-rewrite

    D3DLOCKED_RECT locked;
    if (FAILED(fresh->LockRect(0, &locked, nullptr, 0))) {
        ++g_trouble.lockFailed;
        fresh->Release();
        return cached.texture;
    }
    const uint8_t* indices = static_cast<const uint8_t*>(record->pixels);
    std::vector<uint32_t> image(static_cast<size_t>(record->width) * record->height);
    for (int y = 0; y < record->height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * kPageStride;
        uint32_t* out = image.data() + static_cast<size_t>(y) * record->width;
        for (int x = 0; x < record->width; ++x) {
            const uint8_t index = row[x];
            out[x] = index ? (palette[index] | 0xFF000000u) : 0u;
        }
    }
    // Is this a fireball rather than a cutout? Measured on the artwork as the
    // palette produced it, before anything below has moved a texel - and the
    // measurements are kept, not just the verdict, so a sprite that still has a
    // black rim can be looked up afterwards and the thresholds moved with the
    // numbers in front of you rather than by guessing. See WriteTextureReport.
    const ArtSettings settings = CurrentArtSettings();
    EffectMeasure measure;
    bool isEffect = false;
    ClassifyArtwork(image.data(), record->width, record->height, mayBeEffect, settings, &measure,
                    &isEffect);
    ++g_classifiedFrames;
    if (isEffect) ++g_effectFrames;

    FrameNote& note = NoteFrame(key, record->width, record->height, record->palette, measure, isEffect);
    // The artwork as the game supplied it, before the effect handling below
    // rewrites texels: what is wanted from a dump is the thing being judged.
    if (measure.hasCutout && !note.dumped) {
        DumpFrame(key, image.data(), record->width, record->height);
        note.dumped = true;
    }

    g_holesClosed += FinishArtwork(image.data(), record->width, record->height, isEffect, settings);
    for (int y = 0; y < record->height; ++y) {
        memcpy(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch,
               image.data() + static_cast<size_t>(y) * record->width,
               static_cast<size_t>(record->width) * 4);
    }
    fresh->UnlockRect(0);

    cached.texture = fresh;
    cached.width = record->width;
    cached.height = record->height;
    cached.palette = record->palette;
    cached.revision = record->revision;
    cached.pixels = record->pixels;
    cached.provisional = !paletteHasColour;
    cached.effect = isEffect;
    cached.key = key;
    // A texture built before the game filled its palette in is the wrong picture,
    // so it is not published under this content key - the next frame builds it
    // again and that one gets remembered.
    if (!cached.provisional) g_frames[key] = Frame{cached.texture, isEffect};
    ++g_trouble.built;
    if (effect) *effect = isEffect;
    return cached.texture;
}

void ClearGroundDecalArtwork() {
    g_decalKeys.clear();
    g_decalMaxSide = 0;
    g_decalVerdicts.clear();
}

void AddGroundDecalArtwork(int width, int height, const uint8_t* indices, int stride) {
    if (!indices || width <= 0 || height <= 0) return;
    g_decalKeys.insert(IndexKey(width, height, indices, stride));
    g_decalMaxSide = (std::max)(g_decalMaxSide, (std::max)(width, height));
    g_decalVerdicts.clear();
}

int GroundDecalArtworkCount() { return static_cast<int>(g_decalKeys.size()); }

bool IsGroundDecal(const void* handle) {
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || g_decalKeys.empty()) return false;
    // Decals are a handful of tiny strips; anything bigger is not one, and not
    // worth hashing to find out.
    if (record->width > g_decalMaxSide || record->height > g_decalMaxSide) return false;
    DecalVerdict& v = g_decalVerdicts[handle];
    if (v.pixels != record->pixels || v.revision != record->revision ||
        v.width != record->width || v.height != record->height) {
        v.pixels = record->pixels;
        v.revision = record->revision;
        v.width = record->width;
        v.height = record->height;
        v.decal = g_decalKeys.count(IndexKey(record->width, record->height,
                                             static_cast<const uint8_t*>(record->pixels),
                                             kPageStride)) != 0;
    }
    return v.decal;
}

void NoteSpriteTexture(const void* handle) {
    const auto found = g_deviceTextures.find(handle);
    if (found == g_deviceTextures.end() || !found->second.key) return;
    const auto note = g_notes.find(found->second.key);
    if (note != g_notes.end()) note->second.drawnAsSprite = true;
}

void SetTextureDumping(bool on) { g_dumpTextures = on; }
bool TextureDumping() { return g_dumpTextures; }

void SetCloseHoles(bool on) { g_closeHoles = on; }
bool CloseHoles() { return g_closeHoles; }
void SetCloseHoleMax(int texels) { g_closeHoleMax = texels < 0 ? 0 : texels; }
int  CloseHoleMax() { return g_closeHoleMax; }
int  HolesClosed() { return g_holesClosed; }
const char* TextureDumpDir() { return DumpDir(); }
int TextureFramesDumped() { return static_cast<int>(g_dumped); }

int WriteTextureReport() {
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, sizeof(path));
    char* slash = strrchr(path, '\\');
    if (slash) strcpy(slash + 1, "gta2dx9_textures.csv");
    else strcpy(path, "gta2dx9_textures.csv");

    FILE* out = fopen(path, "w");
    if (!out) {
        Log("texture report: could not write %s", path);
        return 0;
    }
    fprintf(out, "; Every distinct frame of artwork this session built.\n");
    fprintf(out, "; sprite=1 means the world-space sprite pass drew it (a car, a pedestrian, a\n");
    fprintf(out, "; fireball); sprite=0 is a tile or something the HUD drew. effect=1 means it\n");
    fprintf(out, "; was classified as additive effect artwork: edge_median<%.1f, or peak<%.1f.\n",
            g_effects.edgeLuma, g_effects.faintLuma);
    fprintf(out, "; A sprite with a black rim that reads effect=0 is a threshold to move: look\n");
    fprintf(out, "; at its edge_median and peak. The frames themselves are TGAs in %s.\n",
            DumpDir());
    fprintf(out, "key,width,height,palette,sprite,effect,cutout,edge_median,edge_mean,"
                 "edge_dark_fraction,peak,fringe_texels,opaque_texels\n");
    int rows = 0;
    for (const auto& entry : g_notes) {
        const FrameNote& n = entry.second;
        fprintf(out, "%016llX,%d,%d,%d,%d,%d,%d,%.2f,%.2f,%.3f,%.2f,%d,%d\n",
                static_cast<unsigned long long>(n.key), n.width, n.height, n.palette,
                n.drawnAsSprite ? 1 : 0, n.classified ? 1 : 0, n.measure.hasCutout ? 1 : 0,
                n.measure.fringeMedian, n.measure.fringeMean, n.measure.fringeDarkFraction,
                n.measure.peak, n.measure.fringeTexels, n.measure.opaqueTexels);
        ++rows;
    }
    fclose(out);

    int sprites = 0, effects = 0, cutouts = 0;
    for (const auto& entry : g_notes) {
        if (entry.second.drawnAsSprite) ++sprites;
        if (entry.second.classified) ++effects;
        if (entry.second.measure.hasCutout) ++cutouts;
    }
    Log("texture report: %d frame(s) to %s -- %d drawn as sprites, %d with a cutout, %d "
        "classified as effects; %d frame(s) dumped to %s",
        rows, path, sprites, cutouts, effects, static_cast<int>(g_dumped), DumpDir());
    return rows;
}

bool SpriteOpaqueBounds(const void* handle, int* x0, int* x1, int* y0, int* y1, int* width,
                        int* height) {
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || record->width <= 0 || record->height <= 0 ||
        record->width > kPageStride) {
        return false;
    }
    const uint8_t* indices = static_cast<const uint8_t*>(record->pixels);
    int minX = record->width, maxX = -1, minY = record->height, maxY = -1;
    for (int y = 0; y < record->height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * kPageStride;
        for (int x = 0; x < record->width; ++x) {
            if (!row[x]) continue;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }
    }
    if (maxX < 0) return false;
    *x0 = minX;
    *x1 = maxX + 1;
    *y0 = minY;
    *y1 = maxY + 1;
    *width = record->width;
    *height = record->height;
    return true;
}

void ForgetDeviceTexture(const void* handle) {
    // Only the record's bookkeeping goes: the texture itself belongs to g_frames
    // and may well be shared with another record showing the same artwork.
    g_deviceTextures.erase(handle);
}

void ReleaseDeviceTextures() {
    g_deviceTextures.clear();
    for (auto& entry : g_frames) {
        if (entry.second.texture) entry.second.texture->Release();
    }
    g_frames.clear();
    if (g_standIn) g_standIn->Release();
    g_standIn = nullptr;
    // The car frames made ahead went with the rest: make them again (frames still
    // on the worker are uploaded when they come back, into the next device's cache).
    g_artPrecached.clear();
    if (!g_carSprites.empty()) {
        g_precacheTodo.clear();
        g_precacheAt = 0;
        for (size_t i = 0; i < g_carSprites.size(); ++i) {
            for (uint16_t pal : g_carSprites[i].palettes) g_precacheTodo.emplace_back(static_cast<int>(i), pal);
        }
    }
    g_frameLimitLogged = false;
    g_effectFrames = 0;
    g_classifiedFrames = 0;
}

bool TextureCacheTakeFlushRequest() {
    const bool wanted = g_flushRequested;
    g_flushRequested = false;
    return wanted;
}

void RebuildDeviceTextures() {
    // Same thing, said for a different reason: the classification and the pixel
    // work both happen on the way in, so the only way a threshold change reaches
    // artwork already in the cache is to throw the cache away. The device keeps
    // a reference to anything it is still bound to, so releasing here is safe
    // even mid-frame.
    ReleaseDeviceTextures();
    Log("textures: dropped for a rebuild (effect classification changed)");
}

bool SpriteImageFor(const void* handle, std::vector<uint32_t>* out, int* width, int* height) {
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || !record->width || !record->height) return false;
    const uint32_t* palette = PaletteColours(record->palette);
    if (!palette) return false;
    *width = record->width;
    *height = record->height;
    out->assign(static_cast<size_t>(record->width) * record->height, 0u);
    const uint8_t* indices = static_cast<const uint8_t*>(record->pixels);
    for (int y = 0; y < record->height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * kPageStride;
        uint32_t* dst = out->data() + static_cast<size_t>(y) * record->width;
        for (int x = 0; x < record->width; ++x) {
            const uint8_t index = row[x];
            dst[x] = index ? (palette[index] | 0xFF000000u) : 0u;
        }
    }
    return true;
}

// FIX-CAR-IDENTITY-2 (pm40, feel25): the same artwork decoded in another palette of the car sprite.
// Drawn in a remap: in the sprite's own palette (CARI's first, the style's colours before any remap),
// *remapped = true. Drawn in its own palette: in its first remap, *remapped = false. The texels whose
// colour differs between the two are the paint (a remap recolours exactly the paint ramp). False when
// the sprite or palette is unknown or the sprite has no remap. Read only: the classic draw is untouched.
bool CarSpriteOtherImageFor(const void* handle, int sprite, std::vector<uint32_t>* out, bool* remapped) {
    const TextureRecord* record = static_cast<const TextureRecord*>(handle);
    if (!record || !record->pixels || !record->width || !record->height) return false;
    const CarSpriteArt* found = nullptr;
    for (const CarSpriteArt& art : g_carSprites) {
        if (art.sprite == sprite) { found = &art; break; }
    }
    if (!found || found->palettes.empty()) return false;
    int other = -1;
    if (found->palettes[0] != record->palette) { other = found->palettes[0]; *remapped = true; }
    else if (found->palettes.size() > 1) { other = found->palettes[1]; *remapped = false; }
    if (other < 0) return false;
    const uint32_t* palette = PaletteColours(other);
    if (!palette) return false;
    out->assign(static_cast<size_t>(record->width) * record->height, 0u);
    const uint8_t* indices = static_cast<const uint8_t*>(record->pixels);
    for (int y = 0; y < record->height; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * kPageStride;
        uint32_t* dst = out->data() + static_cast<size_t>(y) * record->width;
        for (int x = 0; x < record->width; ++x) dst[x] = row[x] ? (palette[row[x]] | 0xFF000000u) : 0u;
    }
    return true;
}

// FIX-CAR-IDENTITY-5 (pmt4): the car sprite's CLEAN artwork (the style file's indices: no dent, door, lamp or
// damage delta) decoded in `palette` and in the other palette CarSpriteOtherImageFor would pick. The paint
// measured from these is a pure function of (sprite, palette): the same for every car, frame and session
// drawn in that remap. False when the sprite, its art or either palette is unknown, or it has no remap.
bool CarSpriteCleanImages(int sprite, int palette, std::vector<uint32_t>* drawn, std::vector<uint32_t>* other, int* width,
                          int* height, bool* remapped) {
    const CarSpriteArt* found = nullptr;
    for (const CarSpriteArt& art : g_carSprites) {
        if (art.sprite == sprite) { found = &art; break; }
    }
    if (!found || found->palettes.empty() || found->width <= 0 || found->height <= 0 ||
        found->indices.size() < static_cast<size_t>(found->width) * found->height) return false;
    int alt = -1;
    if (found->palettes[0] != palette) { alt = found->palettes[0]; *remapped = true; }
    else if (found->palettes.size() > 1) { alt = found->palettes[1]; *remapped = false; }
    if (alt < 0) return false;
    // PaletteColours returns one shared buffer: copy the first palette before asking for the second.
    bool hasA = false, hasB = false;
    uint32_t pa[256];
    const uint32_t* first = PaletteColours(palette, &hasA);
    if (!first || !hasA) return false;
    memcpy(pa, first, sizeof pa);
    const uint32_t* pb = PaletteColours(alt, &hasB);
    if (!pb || !hasB) return false;
    const size_t n = static_cast<size_t>(found->width) * found->height;
    drawn->assign(n, 0u);
    other->assign(n, 0u);
    for (size_t i = 0; i < n; ++i) {
        const uint8_t ix = found->indices[i];
        if (!ix) continue;
        (*drawn)[i] = pa[ix] | 0xFF000000u;
        (*other)[i] = pb[ix] | 0xFF000000u;
    }
    *width = found->width;
    *height = found->height;
    return true;
}

bool ResolveTileImage(int tileNumber, uint32_t* out) {
    const TextureRecord* record = static_cast<const TextureRecord*>(game::TextureForTile(tileNumber));
    if (!record || !record->pixels) return false;
    if (record->width != kTileSize || record->height != kTileSize) return false;

    const uint32_t* colours = PaletteColours(record->palette);
    if (!colours) return false;

    const uint8_t* indices = static_cast<const uint8_t*>(record->pixels);
    for (int y = 0; y < kTileSize; ++y) {
        const uint8_t* row = indices + static_cast<size_t>(y) * kPageStride;
        for (int x = 0; x < kTileSize; ++x) {
            const uint8_t index = row[x];
            out[y * kTileSize + x] = index ? (colours[index] | 0xFF000000u) : 0u;
        }
    }
    gta2::BleedTransparentEdges(out, kTileSize, kTileSize);
    // No CloseArtworkHoles here. A tile's key texels only let anything through
    // on a flat face, where the game keys them too, and there the gaps in a
    // grille are one or two texels wide - exactly what it would close. On a
    // solid face the draw has no alpha test and the slits are already solid.
    // See ColourKeyed in world_mesh.cpp.
    return true;
}

}  // namespace gta2dx9
