// GTA2's own HUD glyphs, read from the level's style (FIX-HUD-5, owner request B13).
//
// Measured on the classic view (GTA2DX9_HUD_LOG_GLYPHS=1 in hud3d.cpp, out/fh5_g1 and fh5_g2): part 1
// draws the money as user sprite 16 ('$', 12x22) and a window of user sprite 158 (11x220: the digits
// 0 9 8 7 6 5 4 3 2 1 0 stacked, 20 rows each; the game rolls the window down the strip like an
// odometer), the multiplier as user 18 (a red x) and a 9x13 window of user 116, the lives as user 17
// (a green x) and user 115, the ammunition as font 1 in the font remap 6 (grey), and part 6 the hearts
// as user 113. The user sprites keep these numbers in all three districts (wil, ste, bil); the
// palettes move by one, and are read from each style.

#include "hud_gamefont.h"

#include <algorithm>
#include <atomic>
#include <mutex>

#include "../../src/gta2_style.h"
#include "log.h"

namespace gta2dx9 {
namespace {

struct Store {
    GameGlyph glyph[static_cast<int>(GameGlyphSet::Count)][128];
};

std::atomic<const Store*> g_store{nullptr};
std::atomic<int> g_generation{0};
std::mutex g_captureMutex;
std::vector<Store*> g_kept;   // earlier stores stay alive: a reader may hold a pointer (a few KB a level)

bool Crop(const std::vector<uint32_t>& argb, int w, int y0, int h, GameGlyph* out) {
    if (y0 < 0 || h <= 0 || static_cast<size_t>(y0 + h) * w > argb.size()) return false;
    out->width = w;
    out->height = h;
    out->argb.assign(argb.begin() + static_cast<size_t>(y0) * w, argb.begin() + static_cast<size_t>(y0 + h) * w);
    return true;
}

bool Whole(const gta2::Style& style, int user, GameGlyph* out) {
    int w = 0, h = 0;
    std::vector<uint32_t> argb;
    if (!style.SpriteImage(gta2::SpriteBase::User, user, &w, &h, &argb)) return false;
    return Crop(argb, w, 0, h, out);
}

// A digit strip: 0 at the top, then 9 down to 1, then 0 again, `cell` rows each.
int Strip(const gta2::Style& style, int user, int cell, GameGlyph* digits /* ['0'..'9'] */) {
    int w = 0, h = 0;
    std::vector<uint32_t> argb;
    if (!style.SpriteImage(gta2::SpriteBase::User, user, &w, &h, &argb) || h < cell * 10) return 0;
    int n = 0;
    for (int d = 0; d <= 9; ++d) n += Crop(argb, w, (d == 0 ? 0 : 10 - d) * cell, cell, &digits[d]) ? 1 : 0;
    return n;
}

int Font(const gta2::Style& style, int font, int remap, GameGlyph* glyphs /* [128] */) {
    if (font >= style.FontCount()) return 0;
    const int first = style.FontFirst(font), size = style.FontSize(font);
    int n = 0;
    for (int c = 33; c < 128 && c - 33 < size; ++c) {
        int w = 0, h = 0;
        std::vector<uint32_t> argb;
        if (!style.SpriteImage(gta2::SpriteBase::Font, first + c - 33, &w, &h, &argb, remap)) continue;
        bool ink = false;
        for (uint32_t p : argb) if (p >> 24) { ink = true; break; }
        if (!ink || w < 1) continue;   // the fonts leave characters they lack empty
        n += Crop(argb, w, 0, h, &glyphs[c]) ? 1 : 0;
    }
    // The font's cells are 25 rows with empty rows above and below the ink: trim the rows no
    // character uses, the same for all, so the baseline holds.
    int top = 1 << 20, bottom = -1;
    for (int c = 33; c < 128; ++c) {
        const GameGlyph& g = glyphs[c];
        for (int y = 0; y < g.height; ++y)
            for (int x = 0; x < g.width; ++x)
                if (g.argb[static_cast<size_t>(y) * g.width + x] >> 24) { top = (std::min)(top, y); bottom = (std::max)(bottom, y); }
    }
    if (bottom >= top)
        for (int c = 33; c < 128; ++c) {
            GameGlyph& g = glyphs[c];
            if (g.width <= 0 || bottom >= g.height) continue;
            std::vector<uint32_t> whole = g.argb;
            Crop(whole, g.width, top, bottom - top + 1, &g);
        }
    return n;
}

}  // namespace

void HudGameFontCapture(const gta2::Style& style) {
    std::lock_guard<std::mutex> lock(g_captureMutex);
    Store* s = new Store();
    auto set = [&](GameGlyphSet k) { return s->glyph[static_cast<int>(k)]; };
    int found = 0, wanted = 0;
    wanted += 2; found += Whole(style, 16, &set(GameGlyphSet::Money)['$']) ? 1 : 0;
    found += Strip(style, 158, 20, &set(GameGlyphSet::Money)['0']) == 10 ? 1 : 0;
    wanted += 2; found += Whole(style, 18, &set(GameGlyphSet::Mult)['x']) ? 1 : 0;
    found += Strip(style, 116, 13, &set(GameGlyphSet::Mult)['0']) == 10 ? 1 : 0;
    wanted += 2; found += Whole(style, 17, &set(GameGlyphSet::Lives)['x']) ? 1 : 0;
    found += Strip(style, 115, 13, &set(GameGlyphSet::Lives)['0']) == 10 ? 1 : 0;
    wanted += 2; found += Whole(style, 113, &set(GameGlyphSet::Heart)['H']) ? 1 : 0;
    found += Whole(style, 114, &set(GameGlyphSet::Heart)['h']) ? 1 : 0;
    const int ammo = Font(style, 1, 6, set(GameGlyphSet::Ammo));
    const int label = Font(style, 1, -1, set(GameGlyphSet::Label));
    Font(style, 1, 5, set(GameGlyphSet::AmmoLow));
    wanted += 2; found += ammo >= 36 ? 1 : 0; found += label >= 36 ? 1 : 0;
    // The sizes the classic path draws (a check that the numbers still point at the same art).
    const GameGlyph& dollar = set(GameGlyphSet::Money)['$'];
    const GameGlyph& heart = set(GameGlyphSet::Heart)['H'];
    const bool shapes = dollar.width == 12 && dollar.height == 22 && heart.width == 15 && heart.height == 14 &&
                        set(GameGlyphSet::Money)['0'].width == 11 && set(GameGlyphSet::Mult)['5'].height == 13;
    if (found != wanted || !shapes) {
        Log("hud3d: game glyphs: %d of %d sets read from the style%s; the modern HUD keeps its own typeface",
            found, wanted, shapes ? "" : " (sizes differ from GTA2 9.6's)");
        delete s;
        return;
    }
    g_kept.push_back(s);
    g_store.store(s);
    const int gen = ++g_generation;
    Log("hud3d: game glyphs read from the style (generation %d): money $ 12x22 and 0-9 11x20, multiplier/lives x and 0-9 9x13, "
        "hearts 15x14, font 1 %d characters (ammunition in font remap 6, labels in its own palette)", gen, label);
}

int HudGameFontGeneration() { return g_generation.load(); }

const GameGlyph* HudGameGlyph(GameGlyphSet set, char c) {
    const Store* s = g_store.load();
    const unsigned u = static_cast<unsigned char>(c);
    if (!s || u >= 128 || set == GameGlyphSet::Count) return nullptr;
    const GameGlyph& g = s->glyph[static_cast<int>(set)][u];
    return g.width > 0 ? &g : nullptr;
}

}  // namespace gta2dx9
