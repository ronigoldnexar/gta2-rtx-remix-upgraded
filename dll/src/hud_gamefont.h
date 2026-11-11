// GTA2's own HUD glyphs for the modern HUD (FIX-HUD-5, owner request B13; docs/hud.md).
//
// The classic view draws the money, the multiplier, the lives, the hearts and the ammunition
// with sprites of the level's style file (the user base and font 1). At level load the same
// sprites are read from the style the world view loads, in their own palettes (the ammunition
// in the font remap the game uses), and kept in memory as ARGB: never written anywhere, since
// they are the game's art. hud3d.cpp re-authors them at the display's pixel size into its atlas.
#pragma once

#include <cstdint>
#include <vector>

namespace gta2 { class Style; }

namespace gta2dx9 {

enum class GameGlyphSet {
    Money,    // '$' (user sprite 16) and the gold digits of the money strip (user 158, 11x20 a digit)
    Mult,     // the multiplier: red 'x' (user 18) and the red digit strip (user 116, 9x13)
    Lives,    // the lives: green 'x' (user 17) and the green digit strip (user 115)
    Ammo,     // font 1 in font remap 6 (grey), as the game draws the ammunition under the weapon
    AmmoLow,  // font 1 in font remap 5 (red): the ammunition when it runs low
    Label,    // font 1 in its own palette (gold): letters for the weapon's name
    Pop,      // the same glyphs at the ammunition's size: the money's gain pop
    Heart,    // 'H' the full heart (user 113, 15x14), 'h' the small one (user 114)
    Lcd,      // FIX-HUD-7: the clock/counter panel's green LCD (part 11): 0-9 user 123-132 (6x12), '#' the unlit
              // cell (user 122, the game's blank leading digit), ':' the colon (121), '.' the colon off (120, 2x12)
    Count
};

struct GameGlyph {
    int width = 0, height = 0;
    std::vector<uint32_t> argb;   // A8R8G8B8, alpha 0 or 255
};

// Called by the world view right after it loads a level's style.
void HudGameFontCapture(const gta2::Style& style);

// Bumped by every capture that found the glyphs: the HUD re-bakes its atlas when it changes.
int HudGameFontGeneration();

// The glyph of a character in a set, or null (the set has none: the caller keeps its fallback).
const GameGlyph* HudGameGlyph(GameGlyphSet set, char c);

}  // namespace gta2dx9
