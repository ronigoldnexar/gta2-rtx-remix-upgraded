#include "gta2_style.h"

#include "alpha_bleed.h"

#include <cstdio>
#include <cstring>

namespace gta2 {
namespace {

constexpr int kTilesPerPage = 16;      // 4x4 grid of 64x64 tiles in a 256x256 page
constexpr int kPageStride = 256;
constexpr int kPageBytes = kPageStride * kPageStride;
constexpr int kPalettesPerPage = 64;
constexpr int kPalettePageBytes = 256 * kPalettesPerPage * 4;

bool ReadFile(const std::string& path, std::vector<uint8_t>* out) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    out->resize(static_cast<size_t>(size));
    bool ok = size > 0 && fread(out->data(), 1, out->size(), f) == out->size();
    fclose(f);
    return ok;
}

uint32_t ReadU32(const uint8_t* p) {
    uint32_t v;
    memcpy(&v, p, 4);
    return v;
}

uint16_t ReadU16(const uint8_t* p) {
    uint16_t v;
    memcpy(&v, p, 2);
    return v;
}

}  // namespace

bool Style::Load(const std::string& path, std::string* error) {
    std::vector<uint8_t> data;
    if (!ReadFile(path, &data)) {
        *error = "cannot read style file: " + path;
        return false;
    }
    if (data.size() < 6 || memcmp(data.data(), "GBST", 4) != 0) {
        *error = "not a GBST style file: " + path;
        return false;
    }

    size_t tileOff = 0, tileSize = 0, palOff = 0, palxOff = 0, palxSize = 0;
    sprites_.clear();
    spriteGraphics_.clear();
    deltas_.clear();
    deltaStore_.clear();
    waterTiles_.clear();
    palettes_.clear();
    paletteIndex_.clear();
    tilePalettes_ = 0;
    size_t delxOff = 0, delxSize = 0;
    memset(spriteBases_, 0, sizeof(spriteBases_));
    fontSizes_.clear();
    cars_.clear();
    size_t offset = 6;
    while (offset + 8 <= data.size()) {
        char tag[5] = {};
        memcpy(tag, &data[offset], 4);
        uint32_t size = ReadU32(&data[offset + 4]);
        size_t body = offset + 8;
        if (body + size > data.size()) break;

        if (!strcmp(tag, "TILE")) {
            tileOff = body;
            tileSize = size;
        } else if (!strcmp(tag, "PPAL")) {
            palOff = body;
            palettes_.assign(data.begin() + body, data.begin() + body + size);
        } else if (!strcmp(tag, "PALX")) {
            palxOff = body;
            palxSize = size;
            for (size_t at = body; at + 2 <= body + size; at += 2) {
                paletteIndex_.push_back(ReadU16(&data[at]));
            }
        } else if (!strcmp(tag, "PALB") && size >= 2) {
            tilePalettes_ = ReadU16(&data[body]);
            for (int i = 0; i < 8; ++i) paletteBases_[i] = (static_cast<size_t>(i) * 2 + 2 <= size) ? ReadU16(&data[body + i * 2]) : 0;
        } else if (!strcmp(tag, "SPRG")) {
            spriteGraphics_.assign(data.begin() + body, data.begin() + body + size);
        } else if (!strcmp(tag, "SPRX")) {
            for (size_t at = body; at + 8 <= body + size; at += 8) {
                sprites_.push_back({ReadU32(&data[at]), data[at + 4], data[at + 5]});
            }
        } else if (!strcmp(tag, "SPRB") && size >= sizeof(spriteBases_)) {
            for (int i = 0; i < 6; ++i) spriteBases_[i] = ReadU16(&data[body + i * 2]);
        } else if (!strcmp(tag, "FONB") && size >= 2) {
            const int fonts = ReadU16(&data[body]);
            for (int i = 0; i < fonts && static_cast<size_t>(i) * 2 + 4 <= size; ++i) fontSizes_.push_back(ReadU16(&data[body + 2 + i * 2]));
        } else if (!strcmp(tag, "DELX")) {
            delxOff = body;
            delxSize = size;
        } else if (!strcmp(tag, "DELS")) {
            deltaStore_.assign(data.begin() + body, data.begin() + body + size);
        } else if (!strcmp(tag, "CARI")) {
            // Per model: model, sprite flag (1: art of its own, 0: the previous model's), width,
            // height, remap count, passengers, wreck, rating, then the wheel and window offsets
            // as signed bytes, two flag bytes, the remaps, and the doors (two signed bytes each).
            int sprite = -1;
            for (size_t at = body; at + 14 <= body + size;) {
                const uint8_t* r = &data[at];
                const int remaps = r[4];
                if (at + 14 + remaps + 1 > body + size) break;
                const int doors = data[at + 14 + remaps];
                if (r[1]) ++sprite;
                CarInfo info;
                info.model = r[0];
                info.sprite = sprite < 0 ? 0 : sprite;
                info.width = r[2];
                info.height = r[3];
                info.passengers = r[5];
                info.wreck = r[6] != 0;
                info.frontWheel = static_cast<int8_t>(r[8]);
                info.rearWheel = static_cast<int8_t>(r[9]);
                info.frontWindow = static_cast<int8_t>(r[10]);
                info.rearWindow = static_cast<int8_t>(r[11]);
                info.doors = doors;
                cars_.push_back(info);
                at += 14 + remaps + 1 + 2 * static_cast<size_t>(doors);
            }
        } else if (!strcmp(tag, "SPEC")) {
            // See IsWaterTile: the third zero-terminated list.
            constexpr int kWaterList = 2;
            int list = 0;
            for (size_t at = body; at + 2 <= body + size; at += 2) {
                const uint16_t tile = ReadU16(&data[at]);
                if (!tile) {
                    if (++list > kWaterList) break;
                    continue;
                }
                if (list != kWaterList) continue;
                if (tile >= waterTiles_.size()) waterTiles_.resize(tile + 1u, 0);
                waterTiles_[tile] = 1;
            }
        }
        offset = body + size;
    }

    if (!tileOff || !palOff || !palxOff) {
        *error = "style file missing TILE/PPAL/PALX chunks";
        return false;
    }

    DecodeTiles(data.data(), tileOff, tileSize, palOff, palxOff, palxSize);

    // DELX: per sprite, its number, how many deltas it has and each one's size in
    // DELS, whose data runs on in the same order.
    uint32_t storeAt = 0;
    for (size_t at = delxOff; delxOff && at + 4 <= delxOff + delxSize;) {
        const int sprite = ReadU16(&data[at]);
        const int count = data[at + 2];
        at += 4;
        if (at + static_cast<size_t>(count) * 2 > delxOff + delxSize) break;
        DeltaSet set;
        for (int i = 0; i < count; ++i) {
            const uint16_t size = ReadU16(&data[at + i * 2]);
            set.offsets.push_back(storeAt);
            set.sizes.push_back(size);
            storeAt += size;
        }
        at += static_cast<size_t>(count) * 2;
        deltas_.emplace_back(sprite, std::move(set));
    }
    return true;
}

// A delta is a list of runs: a 16-bit skip from where the last run ended, a
// length, and that many palette indices. Positions are in the sprite's page, so
// a row is 256 bytes whatever the sprite's own width.
bool Style::DeltaPixels(SpriteBase base, int index, int delta, std::vector<DeltaPixel>* out) const {
    const int which = static_cast<int>(base);
    if (index < 0 || index >= spriteBases_[which] || delta < 0) return false;
    int first = 0;
    for (int i = 0; i < which; ++i) first += spriteBases_[i];
    const int sprite = first + index;
    for (const auto& entry : deltas_) {
        if (entry.first != sprite) continue;
        const DeltaSet& set = entry.second;
        if (delta >= static_cast<int>(set.sizes.size())) return false;
        const size_t begin = set.offsets[delta];
        const size_t end = begin + set.sizes[delta];
        if (end > deltaStore_.size()) return false;
        out->clear();
        uint32_t position = 0;
        for (size_t at = begin; at + 3 <= end;) {
            position += ReadU16(&deltaStore_[at]);
            const int length = deltaStore_[at + 2];
            at += 3;
            for (int i = 0; i < length && at + i < end; ++i) {
                out->push_back({static_cast<int>((position + i) % kPageStride),
                                static_cast<int>((position + i) / kPageStride),
                                deltaStore_[at + i]});
            }
            position += length;
            at += length;
        }
        return !out->empty();
    }
    return false;
}

bool Style::SpriteDeltaCentre(SpriteBase base, int index, int delta, float* x, float* y) const {
    std::vector<DeltaPixel> pixels;
    if (!DeltaPixels(base, index, delta, &pixels)) return false;
    double sumX = 0.0, sumY = 0.0;
    for (const DeltaPixel& p : pixels) {
        sumX += p.x;
        sumY += p.y;
    }
    // Pixel centres, so a one-pixel delta at column 0 is at 0.5.
    *x = static_cast<float>(sumX / pixels.size()) + 0.5f;
    *y = static_cast<float>(sumY / pixels.size()) + 0.5f;
    return true;
}

bool Style::SpriteDeltaBounds(SpriteBase base, int index, int delta, int* x0, int* y0, int* x1,
                              int* y1) const {
    std::vector<DeltaPixel> pixels;
    if (!DeltaPixels(base, index, delta, &pixels)) return false;
    *x0 = *y0 = 1 << 30;
    *x1 = *y1 = -1;
    for (const DeltaPixel& p : pixels) {
        if (p.x < *x0) *x0 = p.x;
        if (p.y < *y0) *y0 = p.y;
        if (p.x + 1 > *x1) *x1 = p.x + 1;
        if (p.y + 1 > *y1) *y1 = p.y + 1;
    }
    return true;
}

bool Style::SpriteDeltaImage(SpriteBase base, int index, int delta, int* x0, int* y0, int* width,
                             int* height, std::vector<uint32_t>* argb) const {
    std::vector<DeltaPixel> pixels;
    if (!DeltaPixels(base, index, delta, &pixels)) return false;
    int x1 = 0, y1 = 0;
    if (!SpriteDeltaBounds(base, index, delta, x0, y0, &x1, &y1)) return false;
    *width = x1 - *x0;
    *height = y1 - *y0;
    const int which = static_cast<int>(base);
    int first = 0;
    for (int i = 0; i < which; ++i) first += spriteBases_[i];
    const size_t slot = static_cast<size_t>(tilePalettes_) + first + index;
    if (slot >= paletteIndex_.size()) return false;
    const uint16_t palette = paletteIndex_[slot];
    const size_t paletteBase = static_cast<size_t>(palette / kPalettesPerPage) * kPalettePageBytes +
                               static_cast<size_t>(palette % kPalettesPerPage) * 4;
    argb->assign(static_cast<size_t>(*width) * *height, 0);
    for (const DeltaPixel& p : pixels) {
        if (p.index == 0) continue;
        const size_t at = paletteBase + static_cast<size_t>(p.index) * 256;
        if (at + 3 > palettes_.size()) continue;
        (*argb)[static_cast<size_t>(p.y - *y0) * *width + (p.x - *x0)] =
            0xFF000000u | (static_cast<uint32_t>(palettes_[at + 2]) << 16) |
            (static_cast<uint32_t>(palettes_[at + 1]) << 8) | palettes_[at];
    }
    return true;
}

// PPAL keeps 64 palettes to a 64K page, interleaved: entry i of palette p is the
// dword at (p / 64) * 64K + i * 256 + (p % 64) * 4, as B, G, R. A sprite's own
// palette is the PALX slot after the tiles' ones, at its number across all bases.
bool Style::SpriteDeltaColour(SpriteBase base, int index, int delta, float* rgb) const {
    std::vector<DeltaPixel> pixels;
    if (!DeltaPixels(base, index, delta, &pixels)) return false;
    const int which = static_cast<int>(base);
    int first = 0;
    for (int i = 0; i < which; ++i) first += spriteBases_[i];
    const size_t slot = static_cast<size_t>(tilePalettes_) + first + index;
    if (slot >= paletteIndex_.size()) return false;
    const uint16_t palette = paletteIndex_[slot];
    const size_t paletteBase = static_cast<size_t>(palette / kPalettesPerPage) * kPalettePageBytes +
                               static_cast<size_t>(palette % kPalettesPerPage) * 4;
    double sum[3] = {};
    int counted = 0;
    for (const DeltaPixel& p : pixels) {
        if (p.index == 0) continue;
        const size_t at = paletteBase + static_cast<size_t>(p.index) * 256;
        if (at + 3 > palettes_.size()) continue;
        sum[0] += palettes_[at + 2];
        sum[1] += palettes_[at + 1];
        sum[2] += palettes_[at];
        ++counted;
    }
    if (!counted) return false;
    for (int c = 0; c < 3; ++c) rgb[c] = static_cast<float>(sum[c] / counted / 255.0);
    return true;
}

bool Style::SpriteArtwork(SpriteBase base, int index, SpriteIndices* out) const {
    const int which = static_cast<int>(base);
    if (!out || index < 0 || index >= spriteBases_[which]) return false;
    int first = 0;
    for (int i = 0; i < which; ++i) first += spriteBases_[i];
    const size_t n = static_cast<size_t>(first + index);
    if (n >= sprites_.size()) return false;
    const SpriteEntry& e = sprites_[n];
    const size_t page = e.offset / kPageBytes;
    const size_t x = e.offset % kPageStride;
    const size_t y = (e.offset % kPageBytes) / kPageStride;
    if (x + e.width > kPageStride || y + e.height > kPageStride ||
        (page + 1) * kPageBytes > spriteGraphics_.size()) {
        return false;
    }
    out->width = e.width;
    out->height = e.height;
    out->indices.resize(static_cast<size_t>(e.width) * e.height);
    for (int row = 0; row < e.height; ++row) {
        memcpy(&out->indices[static_cast<size_t>(row) * e.width],
               &spriteGraphics_[page * kPageBytes + (y + row) * kPageStride + x], e.width);
    }
    return true;
}

bool Style::SpriteImage(SpriteBase base, int index, int* width, int* height, std::vector<uint32_t>* argb,
                        int fontRemap) const {
    SpriteIndices art;
    if (!argb || !SpriteArtwork(base, index, &art)) return false;
    int first = 0;
    for (int i = 0; i < static_cast<int>(base); ++i) first += spriteBases_[i];
    size_t slot = static_cast<size_t>(tilePalettes_) + first + index;
    if (fontRemap >= 0) {   // PALB: tile, sprite, car, ped, code_obj, map_obj, user, font remaps
        if (fontRemap >= paletteBases_[7]) return false;
        slot = 0;
        for (int i = 0; i < 7; ++i) slot += paletteBases_[i];
        slot += static_cast<size_t>(fontRemap);
    }
    if (slot >= paletteIndex_.size()) return false;
    const uint16_t palette = paletteIndex_[slot];
    const size_t paletteBase = static_cast<size_t>(palette / kPalettesPerPage) * kPalettePageBytes +
                               static_cast<size_t>(palette % kPalettesPerPage) * 4;
    argb->assign(art.indices.size(), 0);
    for (size_t i = 0; i < art.indices.size(); ++i) {
        const uint8_t c = art.indices[i];
        if (!c) continue;
        const size_t at = paletteBase + static_cast<size_t>(c) * 256;
        if (at + 3 > palettes_.size()) continue;
        (*argb)[i] = 0xFF000000u | (static_cast<uint32_t>(palettes_[at + 2]) << 16) |
                     (static_cast<uint32_t>(palettes_[at + 1]) << 8) | palettes_[at];
    }
    if (width) *width = art.width;
    if (height) *height = art.height;
    return true;
}

void Style::OverrideTile(int index, const uint32_t* pixels) {
    if (index < 0 || index >= static_cast<int>(tiles_.size()) || !pixels) return;
    Tile& tile = tiles_[index];
    memcpy(tile.pixels.data(), pixels, kTilePixels * sizeof(uint32_t));
    tile.hasTransparency = false;
    for (uint32_t pixel : tile.pixels) {
        if ((pixel & 0xFF000000u) == 0) {
            tile.hasTransparency = true;
            break;
        }
    }
}

void Style::DecodeTiles(const uint8_t* data, size_t tileOffset, size_t tileSize,
                        size_t palOffset, size_t palIndexOffset, size_t palIndexSize) {
    const int pageCount = static_cast<int>(tileSize / kPageBytes);
    const int tileCount = pageCount * kTilesPerPage;
    const int paletteEntries = static_cast<int>(palIndexSize / 2);

    tiles_.resize(tileCount);
    for (int index = 0; index < tileCount; ++index) {
        Tile& tile = tiles_[index];
        tile.pixels.resize(kTilePixels);

        const int page = index / kTilesPerPage;
        const int slot = index % kTilesPerPage;
        const size_t pixelBase = tileOffset + static_cast<size_t>(page) * kPageBytes +
                                 static_cast<size_t>(slot / 4) * kTileSize * kPageStride +
                                 static_cast<size_t>(slot % 4) * kTileSize;

        const uint16_t palette =
            index < paletteEntries ? ReadU16(&data[palIndexOffset + index * 2]) : 0;
        const size_t paletteBase = palOffset +
                                   static_cast<size_t>(palette / kPalettesPerPage) * kPalettePageBytes +
                                   static_cast<size_t>(palette % kPalettesPerPage) * 4;

        for (int y = 0; y < kTileSize; ++y) {
            const uint8_t* row = &data[pixelBase + static_cast<size_t>(y) * kPageStride];
            for (int x = 0; x < kTileSize; ++x) {
                const uint8_t colorIndex = row[x];
                if (colorIndex == 0) {
                    tile.pixels[y * kTileSize + x] = 0;
                    tile.hasTransparency = true;
                    continue;
                }
                const uint8_t* c = &data[paletteBase + static_cast<size_t>(colorIndex) * 256];
                tile.pixels[y * kTileSize + x] =
                    0xFF000000u | (static_cast<uint32_t>(c[2]) << 16) |
                    (static_cast<uint32_t>(c[1]) << 8) | c[0];
            }
        }
        // See alpha_bleed.h: transparent black is what makes a cutout's edge
        // read as a hard black line once anything filters it.
        // Nothing is closed: the key only shows through on flat faces, where
        // the game keys it too - see ColourKeyed in world_mesh.cpp. The live
        // path in texture_store.cpp does the same; this is the fallback that
        // parses the .sty itself.
        if (tile.hasTransparency) {
            BleedTransparentEdges(tile.pixels.data(), kTileSize, kTileSize);
        }
    }
}

int Style::PedRemapPalette(int remap) const {
    if (remap < 0 || remap >= paletteBases_[3]) return -1;
    const size_t slot = static_cast<size_t>(paletteBases_[0]) + paletteBases_[1] + paletteBases_[2] + static_cast<size_t>(remap);
    return slot < paletteIndex_.size() ? paletteIndex_[slot] : -1;
}

}  // namespace gta2
