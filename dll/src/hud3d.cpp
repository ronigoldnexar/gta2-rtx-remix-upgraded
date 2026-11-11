// The modern HUD of the street views. See hud3d.h and docs/hud.md.
//
// What it shows, and where each value comes from (all read from the game each frame, every
// read guarded):
//
//   money             the score keeper's GetMoney (game_save.cpp), ticking towards the value
//   multiplier, lives the score keeper ([[0x5EB4FC]+0x38]) +0x6BC and +0x684
//   health            the player's ped +0x216 (100 full: the game draws health/10+1 hearts)
//   car condition     the driven car's damage word +0x74 (0 fresh .. 32000 explodes)
//   wanted            the ped's cop points +0x20A, in stars at 600/1600/3000/5000/8000/12000
//   weapon, ammo      the ped's weapon object (+0x170: type +0x1C, ammo +0, shown as ammo/10);
//                     the icon is the game's own HUD icon, taken from its draw (part 1)
//   brief             the key of the message on screen (0x5E9808) looked up in data\e.gxt; the
//                     speaker's portrait is the game's own, taken from its draw (part 10)
//   timers, counters  the HUD's four counter slots at [0x672F40]+0x7E8, 12 bytes each: +0 the
//                     clock in ticks (30 a second, < 0 none), +4 a pointer to a counter's value
//   objective, phones the HUD's arrow slots at [0x672F40]+0x1F18 (17 of 0x7C: type +0x20,
//                     target position +0x44/+0x48 in 18.14 fixed point); types 1-4 are phones
//   mini-map          the level's own cells: the top lid of each column, by ground type
//
// It is drawn with Dear ImGui's draw lists in a context of its own (the F4 menu keeps the
// other one), with Barlow Condensed (SIL OFL 1.1, embedded from assets/fonts by
// tools/gen_hud_font.py) rasterised at the exact pixel size the display needs, re-baked when
// the window's height changes: crisp at any resolution, no scaled bitmaps.

#include "hud3d.h"
#include "cab_interior.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include <imgui.h>
#include <imgui_internal.h>   // ShadeVertsLinearColorGradientKeepAlpha (the beat title's fill)
#include <backends/imgui_impl_dx9.h>

#include "../../src/gta2_map.h"
#include "beats.h"
#include "compat.h"
#include "game_access.h"
#include "game_save.h"
#include "live_geometry.h"
#include "log.h"
#include "map_objects.h"
#include "texture_store.h"
#include "view_modes.h"
#include "world_view.h"

#include "hud3d_font.inc"
#include "hud_gamefont.h"

namespace gta2dx9 {
namespace {

// ---- Settings ---------------------------------------------------------------------------

struct Config {
    bool loaded = false;
    bool modern = true;     // [hud] modern
    bool minimap = true;    // [hud] minimap
    bool markers = true;    // [hud] objective_markers: the game's target arrows as 3D-projected markers
    bool gameFont = true;   // [hud] game_font: GTA2's own glyphs for money, multiplier, lives, hearts, ammo (FIX-HUD-5, owner B13)
    bool glyphSmooth = true; // [hud] game_font_smooth: the glyphs re-authored edge-aware (Scale2x/3x) rather than plain integer pixels
    bool hearts = true;     // [hud] hearts: the game's row of hearts (health, a heart a started 20) top right (FIX-HUD-4, owner B12)
    int toggleKey = 0;      // [hud] toggle_key, 0 none
    float scale = 1.0f;     // [hud] scale_pct / 100
    bool test = false;      // GTA2DX9_HUD_TEST=1: [hud] modern/test_health/test_clock re-read live
};
Config g_cfg;
int g_testMoney = -1;   // GTA2DX9_HUD_TEST=1: [hud] test_money=N shows N as the money (the game's untouched)

int ParseKey(const char* name) {
    if (!name || !name[0]) return 0;
    if ((name[0] == 'F' || name[0] == 'f') && name[1]) {
        const int n = atoi(name + 1);
        if (n >= 1 && n <= 24) return VK_F1 + n - 1;
    }
    if (!name[1]) return toupper(static_cast<unsigned char>(name[0]));
    if (name[0] == '0' && (name[1] == 'x' || name[1] == 'X')) return static_cast<int>(strtol(name, nullptr, 16));
    return 0;
}

void LoadConfig() {
    if (g_cfg.loaded) return;
    g_cfg.loaded = true;
    const char* ini = ViewModes().devIniPath;
    if (ini && ini[0]) {
        g_cfg.modern = GetPrivateProfileIntA("hud", "modern", 1, ini) != 0;
        g_cfg.minimap = GetPrivateProfileIntA("hud", "minimap", 1, ini) != 0;
        g_cfg.markers = GetPrivateProfileIntA("hud", "objective_markers", 1, ini) != 0;
        g_cfg.hearts = GetPrivateProfileIntA("hud", "hearts", 1, ini) != 0;
        g_cfg.gameFont = GetPrivateProfileIntA("hud", "game_font", 1, ini) != 0;
        g_cfg.glyphSmooth = GetPrivateProfileIntA("hud", "game_font_smooth", 1, ini) != 0;
        const int pct = GetPrivateProfileIntA("hud", "scale_pct", 100, ini);
        g_cfg.scale = static_cast<float>((std::max)(50, (std::min)(200, pct))) / 100.0f;
        char key[16] = {};
        GetPrivateProfileStringA("hud", "toggle_key", "", key, sizeof key, ini);
        g_cfg.toggleKey = ParseKey(key);
    }
    char buf[8] = {};
    g_cfg.test = GetEnvironmentVariableA("GTA2DX9_HUD_TEST", buf, sizeof buf) && buf[0] == '1';
    Log("hud3d: modern HUD %s in the street views (minimap %d, scale %.2f, toggle key 0x%02X%s)",
        g_cfg.modern ? "on" : "off", g_cfg.minimap ? 1 : 0, g_cfg.scale, g_cfg.toggleKey,
        g_cfg.test ? ", test switches read from the ini" : "");
}

// ---- What the game's own HUD drew this frame ---------------------------------------------

struct Corner {
    float x, y, z, rhw;
    uint32_t colour;
    float u, v;
};
static_assert(sizeof(Corner) == 28, "the overlay's vertex");

// The largest textured quad of a part: the weapon icon (part 1), the portrait (part 10).
struct Capture {
    const void* texture = nullptr;
    float area = 0.0f;
    float minX = 0, minY = 0, maxX = 0, maxY = 0;
    float nx[4] = {}, ny[4] = {}, u[4] = {}, v[4] = {};   // corners, normalised to the box
    int count = 0;
    uint32_t frame = 0;
};

uint32_t g_frame = 1;                 // bumped at the end of each Hud3dRender
uint32_t g_partSeen[19] = {};         // the frame each part last drew in
float g_part10MinY = 1e9f;             // top of the game's subtitle/portrait block (game y) in frame g_part10Frame
uint32_t g_part10Frame = 0;
Capture g_weaponIcon, g_portrait;
// FIX-HUD-7 (qaf90): the last frame the game's part 1 drew an ammunition glyph (font 1, 25 rows; the money's
// digits are 20-22, the multiplier's 13): classic writes no number under some car weapons (the fire truck's
// water cannon, ammunition 500), so the street views show the ammunition only when the game writes it.
uint32_t g_gameAmmoFrame = 0;
Capture g_weaponBuild, g_portraitBuild;
bool g_active = false;                // the modern HUD is on screen (decides the swallowing)
bool g_street = false;                // a street view's camera was up at the last Hud3dRender
bool g_briefResolved = false;         // this frame's brief has text of ours
bool g_testGameBrief = false;         // GTA2DX9_HUD_TEST + [hud] test_game_brief=1: every brief stays the game's
// The brief on screen (pm15-third-two-subtitle-renderers-overlap-pixel-font-over-minimap). The
// key buffer at 0x5E9808 is the game's last text lookup, not the subtitle it shows: a second into
// Industrial's opening brief (3230) it reads "svscore" (the save point's text, looked up while
// the brief is still up), which handed part 10 back to the game mid-brief and drew both
// subtitles. So the text is told by what the game draws: the block's first glyphs (texture
// coordinates) are a signature, bound to the key the buffer held when that signature first
// appeared; later frames with the same signature keep that key whatever the buffer says.
std::string g_briefKey;               // the brief the game's block shows; empty: not ours, the game draws it
uint32_t g_briefSig = 2166136261u;    // this frame's signature so far
int g_briefGlyphs = 0, g_briefGlyphsAll = 0;   // glyphs in it (at most 8), all small quads of part 10
uint32_t g_briefSigFrame = 0;
std::unordered_map<uint32_t, std::string> g_briefBySig;

void Note(Capture* c, const void* texture, const Corner* k, int count) {
    if (!texture || count < 3 || count > 4) return;
    float minX = k[0].x, maxX = k[0].x, minY = k[0].y, maxY = k[0].y;
    for (int i = 1; i < count; ++i) {
        minX = (std::min)(minX, k[i].x); maxX = (std::max)(maxX, k[i].x);
        minY = (std::min)(minY, k[i].y); maxY = (std::max)(maxY, k[i].y);
    }
    const float area = (maxX - minX) * (maxY - minY);
    if (c->frame == g_frame && area <= c->area) return;
    if (maxX - minX < 1.0f || maxY - minY < 1.0f) return;
    c->texture = texture;
    c->area = area;
    c->minX = minX; c->maxX = maxX; c->minY = minY; c->maxY = maxY;
    c->count = count;
    for (int i = 0; i < count; ++i) {
        c->nx[i] = (k[i].x - minX) / (maxX - minX);
        c->ny[i] = (k[i].y - minY) / (maxY - minY);
        c->u[i] = k[i].u;
        c->v[i] = k[i].v;
    }
    c->frame = g_frame;
}

// ---- The game's text ----------------------------------------------------------------------

std::unordered_map<std::string, std::u16string> g_gxt;
bool g_gxtTried = false;

void LoadGxt() {
    if (g_gxtTried) return;
    g_gxtTried = true;
    FILE* f = fopen("data\\e.gxt", "rb");
    if (!f) { Log("hud3d: data\\e.gxt not found; briefs keep the game's own talking head"); return; }
    std::vector<uint8_t> data;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size > 16 && size < 16 * 1024 * 1024) {
        data.resize(static_cast<size_t>(size));
        if (fread(data.data(), 1, data.size(), f) != data.size()) data.clear();
    }
    fclose(f);
    if (data.size() < 16 || memcmp(data.data(), "GBL", 3) != 0) { Log("hud3d: e.gxt is not a GBL file"); return; }
    struct Key { std::string name; uint32_t offset; };
    std::vector<Key> keys;
    const uint8_t* tdat = nullptr;
    size_t tdatSize = 0;
    size_t off = 6;
    while (off + 8 <= data.size()) {
        uint32_t chunk = 0;
        memcpy(&chunk, &data[off + 4], 4);
        const size_t body = off + 8;
        if (body + chunk > data.size()) break;
        if (memcmp(&data[off], "TKEY", 4) == 0) {
            for (size_t i = 0; i + 12 <= chunk; i += 12) {
                uint32_t o = 0;
                memcpy(&o, &data[body + i], 4);
                char name[9] = {};
                memcpy(name, &data[body + i + 4], 8);
                keys.push_back({name, o});
            }
        } else if (memcmp(&data[off], "TDAT", 4) == 0) {
            tdat = &data[body];
            tdatSize = chunk;
        }
        off = body + chunk;
    }
    if (!tdat) return;
    for (const Key& k : keys) {
        std::u16string s;
        for (size_t o = k.offset; o + 1 < tdatSize; o += 2) {
            const char16_t c = static_cast<char16_t>(tdat[o] | (tdat[o + 1] << 8));
            if (!c) break;
            s.push_back(c);
        }
        g_gxt[k.name] = s;
    }
    Log("hud3d: %zu texts from data\\e.gxt", g_gxt.size());
}

// A run of a brief's words: highlighted (between '#' marks) or not.
struct Word { std::string text; bool highlight; bool glue; };   // glue: no space before it

// The brief's words in UTF-8, without the leading speaker mark; empty when unknown.
bool BriefWords(const std::string& key, std::vector<Word>* out) {
    out->clear();
    auto it = g_gxt.find(key);
    if (it == g_gxt.end()) return false;
    const std::u16string& s = it->second;
    size_t i = 0;
    while (i < s.size() && (s[i] < 0x20 || s[i] > 0xFF)) ++i;   // the speaker glyph
    // Most briefs are wrapped whole in one pair of marks ("#By the way, a #Church# like...#"):
    // the outer pair is the box's own colour, the inner pairs are the words to pick out.
    size_t end = s.size();
    while (end > i && (s[end - 1] == ' ' || s[end - 1] == '\n')) --end;
    if (end - i >= 2 && s[i] == '#' && s[end - 1] == '#') { ++i; --end; }
    bool highlight = false, glue = false;
    std::string word;
    auto flush = [&](bool nextGlued) {
        if (!word.empty()) out->push_back({word, highlight, glue});
        word.clear();
        glue = nextGlued;
    };
    for (; i < end; ++i) {
        const char16_t c = s[i];
        // a colour mark inside a word ("#Mafia#,") keeps the pieces together
        if (c == '#') { const bool inWord = !word.empty(); flush(inWord); if (!inWord && !out->empty() && i > 0 && s[i - 1] != ' ') glue = true; highlight = !highlight; continue; }
        if (c == ' ' || c == '\n' || c == '\r') { flush(false); continue; }
        if (c < 0x20) continue;
        if (c < 0x80) word.push_back(static_cast<char>(c));
        else if (c < 0x800) { word.push_back(static_cast<char>(0xC0 | (c >> 6))); word.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
        else { word.push_back(static_cast<char>(0xE0 | (c >> 12))); word.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F))); word.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
    }
    flush(false);
    return !out->empty();
}

// ---- Values ----------------------------------------------------------------------------

constexpr uintptr_t kPlayerObject = 0x005EB4FC;
constexpr uintptr_t kHudObject = 0x00672F40;
constexpr uintptr_t kHudCounters = 0x7E8;
constexpr uintptr_t kHudArrows = 0x1F18;
constexpr uintptr_t kMessageKey = 0x005E9808;
constexpr uintptr_t kAddTimer = 0x004C9310;   // HUD counters' "add a clock" (this, seconds)

std::string ReadMessageKey() {
    std::string key;
    GTA2_TRY {
        const char* buf = reinterpret_cast<const char*>(kMessageKey);
        for (int n = 0; n < 8 && buf[n] > 0x20 && buf[n] < 0x7F; ++n) key.push_back(buf[n]);
    } GTA2_EXCEPT { key.clear(); }
    return key;
}

struct Arrow { int type; float x, y; int kind = 0; float z = 0.0f; };

// A gang the game shows a respect bar for (part 5, FUN_004C74F0): the gang pool [0x5EB898],
// 10 gangs of 0x144 bytes; +0 non-zero for a slot in use, +2 the name ("yakuzagang", "zaibatsugang",
// "looniegang" in Downtown, in the order the game draws them, top down), +0x11C the player's
// respect, a signed byte -100..100 (a bar of the game's meter is 20), +0x138 its HUD colour.
constexpr uintptr_t kGangPool = 0x005EB898;
struct Gang { char name[17]; int respect; int colour; };

struct Values {
    std::vector<Gang> gangs;
    bool valid = false;
    bool inVehicle = false;
    int money = -1, mult = -1, lives = -1, health = -1, wanted = 0;
    int weapon = 0, ammo = 0;
    int carWeapon = -1;           // FIX-HUD-6 (qaf2): the car's own weapon the game puts in his hands in a car (type 11+)
    int carDamage = -1;
    int timerTicks = -1;          // the first running clock
    int counter = -1;             // the first counter's value
    int counterSlot = -1, clockSlot = -1;
    std::string messageKey;
    std::vector<Arrow> arrows;
    float x = 0, y = 0, dirX = 0, dirY = 1;
};

// The car weapons (the game's types 11..27, a car's slots of the inventory). Only the tank's is
// verified (qaf2 / FIX-HUD-6, the wil dock frenzy tank) and the fire truck's (qaf90 / FIX-HUD-7); the others
// read as the car's gun.
const char* CarWeaponName(int raw) {
    switch (raw) {
        case 19: return "TANK CANNON";
        case 20: return "WATER CANNON";   // FIX-HUD-7 (qaf90): the wil fire truck's (model 17)
        default: return "CAR GUN";
    }
}

Values ReadValues() {
    Values v;
    const PlayerState& p = ViewPlayer();
    if (!p.valid || !p.ped) return v;
    v.valid = true;
    v.inVehicle = p.inVehicle;
    v.x = p.x; v.y = p.y; v.dirX = p.dirX; v.dirY = p.dirY;
    v.money = GameSaveMoney();
    if (g_testMoney >= 0) v.money = g_testMoney;   // FIX-HUD-5 probe: [hud] test_money (shown only)
    GTA2_TRY {
        const uintptr_t player = *reinterpret_cast<const uintptr_t*>(kPlayerObject);
        const uintptr_t keeper = player > 0x10000 ? *reinterpret_cast<const uintptr_t*>(player + 0x38) : 0;
        if (keeper > 0x10000) {
            v.mult = *reinterpret_cast<const int32_t*>(keeper + 0x6BC);
            v.lives = *reinterpret_cast<const int32_t*>(keeper + 0x684);
        }
        const uint8_t* ped = static_cast<const uint8_t*>(p.ped);
        v.health = *reinterpret_cast<const int16_t*>(ped + 0x216);
        v.wanted = game::PedWantedStars(ped);
        int raw = -1, ammo = 0;
        raw = game::PedWeaponRaw(ped, &ammo);
        v.weapon = game::PedWeaponOf(ped, nullptr);
        v.ammo = raw >= 0 ? ammo : 0;
        // FIX-HUD-6 (qaf2): in a car with a weapon (the kill frenzy tank's cannon, a gun car) the game's
        // weapon object in his hands is the car's, type 11 or more, which PedWeaponOf calls bare hands;
        // the game's part 1 draws its icon and ammunition (K.F. in a frenzy) all the same.
        if (p.inVehicle && raw >= 11 && raw < game::kInventorySlotCount) v.carWeapon = raw;
        if (p.inVehicle && p.vehicle) v.carDamage = *reinterpret_cast<const int16_t*>(static_cast<const uint8_t*>(p.vehicle) + 0x74);
        const char* buf = reinterpret_cast<const char*>(kMessageKey);
        for (int n = 0; n < 8 && buf[n] > 0x20 && buf[n] < 0x7F; ++n) v.messageKey.push_back(buf[n]);
        const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(kHudObject);
        if (hud > 0x10000) {
            for (int i = 0; i < 4; ++i) {
                const uint8_t* slot = reinterpret_cast<const uint8_t*>(hud + kHudCounters + i * 12);
                const int32_t ticks = *reinterpret_cast<const int32_t*>(slot);
                const int32_t* value = *reinterpret_cast<const int32_t* const*>(slot + 4);
                if (ticks >= 0 && v.timerTicks < 0) { v.timerTicks = ticks; v.clockSlot = i; }
                // FIX-HUD-6 (qaf2): a slot can hold a clock AND a counter (a kill frenzy: the kills still
                // needed over the time left, one box in classic); the counter was read only from a
                // slot without a clock, so the frenzy's read counter=-1 all the way.
                if (value && game::PlausiblePointer(value) && v.counter < 0) { v.counter = *value; v.counterSlot = i; }
            }
            // The four slots raw, logged on a change of which slots are in use (FIX-HUD-6 probe).
            static std::string s_slots;
            std::string slots;
            for (int i = 0; i < 4; ++i) {
                const uint8_t* slot = reinterpret_cast<const uint8_t*>(hud + kHudCounters + i * 12);
                const int32_t ticks = *reinterpret_cast<const int32_t*>(slot);
                const uintptr_t ptr = *reinterpret_cast<const uintptr_t*>(slot + 4);
                char t[64];
                snprintf(t, sizeof t, " %d:%s/%s/%08X", i, ticks >= 0 ? "clock" : "-", ptr ? "ptr" : "-",
                         *reinterpret_cast<const uint32_t*>(slot + 8));
                slots += t;
            }
            if (slots != s_slots) {
                s_slots = slots;
                Log("hud3d: counter slots%s (clock slot %d, counter slot %d = %d)", slots.c_str(), v.clockSlot, v.counterSlot, v.counter);
            }
            (void)kHudArrows;
        }
        const uintptr_t pool = *reinterpret_cast<const uintptr_t*>(kGangPool);
        if (pool > 0x10000) {
            for (int i = 0; i < 10 && v.gangs.size() < 6; ++i) {
                const uint8_t* g = reinterpret_cast<const uint8_t*>(pool + i * 0x144);
                if (!g[0]) continue;
                Gang gang = {};
                int n = 0;
                for (; n < 16 && g[2 + n] >= 0x20 && g[2 + n] < 0x7F; ++n) gang.name[n] = static_cast<char>(g[2 + n]);   // "yakuzagang"
                // (Industrial's Rednecks read back unprintable in docs/missions-batch2.md: kept, styled by colour.)
                gang.respect = static_cast<int8_t>(g[0x11C]);
                gang.colour = g[0x138];
                v.gangs.push_back(gang);
                static bool dumped[10] = {};
                if (!dumped[i] && GetEnvironmentVariableA("GTA2DX9_HUD_GANG_DUMP", nullptr, 0)) {
                    dumped[i] = true;
                    std::string hex, txt;
                    for (int k = 0; k < 0x144; ++k) {
                        char h[4];
                        snprintf(h, sizeof h, "%02x", g[k]);
                        hex += h;
                        txt.push_back(g[k] >= 0x20 && g[k] < 0x7F ? static_cast<char>(g[k]) : '.');
                    }
                    Log("hud3d: gang %d raw %s", i, hex.c_str());
                    Log("hud3d: gang %d txt %s", i, txt.c_str());
                }
            }
        }
        if (hud > 0x10000) {
            const uint8_t* arrows = reinterpret_cast<const uint8_t*>(hud + kHudArrows);
            for (int i = 0; i < 17; ++i) {
                const uint8_t* slot = arrows + i * 0x7C;
                const int32_t type = *reinterpret_cast<const int32_t*>(slot + 0x20);
                const int32_t kind = *reinterpret_cast<const int32_t*>(slot + 0x40);
                const int32_t fx = *reinterpret_cast<const int32_t*>(slot + 0x44);
                const int32_t fy = *reinterpret_cast<const int32_t*>(slot + 0x48);
                const int32_t fz = *reinterpret_cast<const int32_t*>(slot + 0x4C);
                if ((type == 0 && kind == 0) || (fx == 0 && fy == 0)) continue;
                v.arrows.push_back({type, fx / 16384.0f, fy / 16384.0f, kind, fz / 16384.0f});
            }
        }
    } GTA2_EXCEPT {
    }
    return v;
}

// ---- The look --------------------------------------------------------------------------

// GTA2's palette: the score's warm white, the yellow of its multiplier and its arrows, the red
// of the hearts, the cyan of the front end, on dark glass.
constexpr ImU32 kWhite = IM_COL32(244, 240, 228, 255);
constexpr ImU32 kYellow = IM_COL32(255, 206, 32, 255);
constexpr ImU32 kRed = IM_COL32(232, 52, 44, 255);
constexpr ImU32 kGreen = IM_COL32(92, 204, 96, 255);
constexpr ImU32 kCyan = IM_COL32(64, 200, 240, 255);
constexpr ImU32 kGlass = IM_COL32(10, 12, 18, 150);
constexpr ImU32 kShadow = IM_COL32(0, 0, 0, 200);

ImU32 Fade(ImU32 c, float a) {
    const int alpha = static_cast<int>(((c >> IM_COL32_A_SHIFT) & 0xFF) * (std::max)(0.0f, (std::min)(1.0f, a)));
    return (c & ~IM_COL32_A_MASK) | (static_cast<ImU32>(alpha) << IM_COL32_A_SHIFT);
}
ImU32 Mix(ImU32 a, ImU32 b, float t) {
    t = (std::max)(0.0f, (std::min)(1.0f, t));
    auto ch = [&](int s) { return static_cast<ImU32>(((a >> s) & 0xFF) * (1 - t) + ((b >> s) & 0xFF) * t) << s; };
    return ch(0) | ch(8) | ch(16) | ch(24);
}

struct Fonts {
    ImFont* money = nullptr;   // heavy italic, large
    ImFont* heavy = nullptr;   // heavy italic, medium
    ImFont* label = nullptr;   // bold italic, small
    ImFont* text = nullptr;    // semibold upright, the briefs
    ImFont* title = nullptr;   // heavy italic, the beats' titles (QB-17/18)
    float moneyPx = 0, heavyPx = 0, labelPx = 0, textPx = 0, titlePx = 0;
};

ImGuiContext* g_ctx = nullptr;
IDirect3DDevice9* g_device = nullptr;
Fonts g_fonts;
int g_fontHeight = 0;
float g_u = 1.0f;     // one unit: a pixel of a 720-line screen

// ---- FIX-HUD-5 (owner request B13): GTA2's own glyphs --------------------------------------
//
// hud_gamefont.cpp reads the sprites the classic view draws its money, multiplier, lives, hearts
// and ammunition with from the level's style. Here each one is re-authored at the display's size:
// an integer factor k = round(2 * u) (2 at 720p, 4 at 1440p, 3 at 1080p), made of Scale2x/Scale3x
// passes (edge-aware pixel-art scalers: a staircase edge becomes a cleaner diagonal, flat runs and
// the bevel's colours stay exact, no new colours and no partial alpha) with any remaining factor as
// whole pixels, packed into the HUD's ImGui atlas as custom rects and drawn 1:1 at whole-pixel
// positions: nothing is filtered, at any resolution. Never written to disk.

std::vector<uint32_t> Scale2x(const std::vector<uint32_t>& s, int w, int h) {
    std::vector<uint32_t> d(static_cast<size_t>(w) * h * 4);
    auto at = [&](int x, int y) { x = (std::max)(0, (std::min)(w - 1, x)); y = (std::max)(0, (std::min)(h - 1, y)); return s[static_cast<size_t>(y) * w + x]; };
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const uint32_t B = at(x, y - 1), D = at(x - 1, y), E = at(x, y), F = at(x + 1, y), H = at(x, y + 1);
            uint32_t e0 = E, e1 = E, e2 = E, e3 = E;
            if (B != H && D != F) {
                e0 = D == B ? D : E; e1 = B == F ? F : E; e2 = D == H ? D : E; e3 = H == F ? F : E;
            }
            const size_t o = static_cast<size_t>(y * 2) * (w * 2) + x * 2;
            d[o] = e0; d[o + 1] = e1; d[o + w * 2] = e2; d[o + w * 2 + 1] = e3;
        }
    return d;
}

std::vector<uint32_t> Scale3x(const std::vector<uint32_t>& s, int w, int h) {
    std::vector<uint32_t> d(static_cast<size_t>(w) * h * 9);
    auto at = [&](int x, int y) { x = (std::max)(0, (std::min)(w - 1, x)); y = (std::max)(0, (std::min)(h - 1, y)); return s[static_cast<size_t>(y) * w + x]; };
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const uint32_t A = at(x - 1, y - 1), B = at(x, y - 1), C = at(x + 1, y - 1), D = at(x - 1, y), E = at(x, y),
                           F = at(x + 1, y), G = at(x - 1, y + 1), H = at(x, y + 1), I = at(x + 1, y + 1);
            uint32_t e[9] = {E, E, E, E, E, E, E, E, E};
            if (B != H && D != F) {
                e[0] = D == B ? D : E;
                e[1] = (D == B && E != C) || (B == F && E != A) ? B : E;
                e[2] = B == F ? F : E;
                e[3] = (D == B && E != G) || (D == H && E != A) ? D : E;
                e[5] = (B == F && E != I) || (H == F && E != C) ? F : E;
                e[6] = D == H ? D : E;
                e[7] = (D == H && E != I) || (H == F && E != G) ? H : E;
                e[8] = H == F ? F : E;
            }
            for (int j = 0; j < 3; ++j)
                for (int i = 0; i < 3; ++i) d[static_cast<size_t>(y * 3 + j) * (w * 3) + x * 3 + i] = e[j * 3 + i];
        }
    return d;
}

std::vector<uint32_t> Whole(const std::vector<uint32_t>& s, int w, int h, int f) {
    std::vector<uint32_t> d(static_cast<size_t>(w) * h * f * f);
    for (int y = 0; y < h * f; ++y)
        for (int x = 0; x < w * f; ++x) d[static_cast<size_t>(y) * (w * f) + x] = s[static_cast<size_t>(y / f) * w + x / f];
    return d;
}

// The glyph at k times its size: Scale3x/Scale2x passes for the factors of 3 and 2, the rest whole pixels.
std::vector<uint32_t> Reauthor(const GameGlyph& g, int k, bool smooth, int* w, int* h) {
    std::vector<uint32_t> img = g.argb;
    int cw = g.width, ch = g.height, left = k;
    if (smooth) {
        while (left % 3 == 0 && left > 1) { img = Scale3x(img, cw, ch); cw *= 3; ch *= 3; left /= 3; }
        while (left % 2 == 0 && left > 1) { img = Scale2x(img, cw, ch); cw *= 2; ch *= 2; left /= 2; }
    }
    if (left > 1) { img = Whole(img, cw, ch, left); cw *= left; ch *= left; }
    *w = cw; *h = ch;
    return img;
}

constexpr int kGlyphSets = static_cast<int>(GameGlyphSet::Count);
constexpr int kGlyphSetsN = 9;
static_assert(kGlyphSets == kGlyphSetsN, "one factor a set");
struct BakedGlyph { int w = 0, h = 0; ImVec2 uv0, uv1; };
struct GameGlyphs {
    bool on = false;
    int k[kGlyphSetsN] = {1, 1, 1, 1, 1, 1, 1, 1, 1};   // each set's integer factor
    int gen = -1;
    BakedGlyph g[kGlyphSets][128];
};
GameGlyphs g_glyphs;
struct PendingGlyph { int set = 0, c = 0, rect = -1, w = 0, h = 0; std::vector<uint32_t> img; };

std::vector<PendingGlyph> QueueGameGlyphs(ImFontAtlas* atlas) {
    std::vector<PendingGlyph> out;
    g_glyphs = GameGlyphs{};
    g_glyphs.gen = HudGameFontGeneration();
    if (!g_cfg.gameFont || g_glyphs.gen <= 0) return out;
    for (int set = 0; set < kGlyphSets; ++set) {
        // 2 at 720p, 4 at 1440p; the weapon's name (font 1 letters) at half that
        // FIX-HUD-7: the clock's LCD cells (6x12, half the money's height) at 3 (18x36 at 720p)
        const float f = set == static_cast<int>(GameGlyphSet::Label) ? 1.0f : set == static_cast<int>(GameGlyphSet::Lcd) ? 3.0f : 2.0f;
        g_glyphs.k[set] = (std::max)(1, static_cast<int>(std::lround(f * g_u)));
    }
    for (int set = 0; set < kGlyphSets; ++set)
        for (int c = 33; c < 128; ++c) {
            const GameGlyph* src = HudGameGlyph(static_cast<GameGlyphSet>(set), static_cast<char>(c));
            if (!src) continue;
            PendingGlyph p;
            p.set = set; p.c = c;
            // FIX-HUD-7: the LCD cells are a dithered plate with faint unlit segments: Scale2x/3x turns that
            // texture into blobs, so they are whole pixels (as classic's nearest)
            p.img = Reauthor(*src, g_glyphs.k[set], g_cfg.glyphSmooth && set != static_cast<int>(GameGlyphSet::Lcd), &p.w, &p.h);
            p.rect = atlas->AddCustomRectRegular(p.w, p.h);
            out.push_back(std::move(p));
        }
    return out;
}

void FinishGameGlyphs(ImFontAtlas* atlas, const std::vector<PendingGlyph>& pending) {
    if (pending.empty()) return;
    unsigned char* px = nullptr;
    int tw = 0, th = 0;
    atlas->GetTexDataAsRGBA32(&px, &tw, &th);
    if (!px) return;
    for (const PendingGlyph& p : pending) {
        const ImFontAtlasCustomRect* r = atlas->GetCustomRectByIndex(p.rect);
        if (!r || !r->IsPacked()) continue;
        for (int y = 0; y < p.h; ++y)
            for (int x = 0; x < p.w; ++x) {
                const uint32_t c = p.img[static_cast<size_t>(y) * p.w + x];   // A8R8G8B8
                unsigned char* d = px + (static_cast<size_t>(r->Y + y) * tw + r->X + x) * 4;   // R G B A
                const unsigned a = c >> 24;
                d[0] = a ? static_cast<unsigned char>(c >> 16) : 0;
                d[1] = a ? static_cast<unsigned char>(c >> 8) : 0;
                d[2] = a ? static_cast<unsigned char>(c) : 0;
                d[3] = static_cast<unsigned char>(a);
            }
        BakedGlyph& b = g_glyphs.g[p.set][p.c];
        b.w = p.w; b.h = p.h;
        atlas->CalcCustomRectUV(r, &b.uv0, &b.uv1);
    }
    atlas->TexPixelsUseColors = true;   // coloured texels: the DX9 backend keeps R and B in place
    g_glyphs.on = true;
}

bool GlyphsOn() { return g_glyphs.on; }
const BakedGlyph* Glyph(GameGlyphSet set, char c) {
    const unsigned u = static_cast<unsigned char>(c);
    if (u >= 128) return nullptr;
    const BakedGlyph& b = g_glyphs.g[static_cast<int>(set)][u];
    return b.w > 0 ? &b : nullptr;
}
// The advance of a character in game pixels times k: the glyph's own width and `gap` game pixels
// after it; ',' is a thin gap (the money's thousands, which the game's strip has no comma for) and
// ' ' a word gap.
float GlyphAdvance(GameGlyphSet set, char c, float gap) {
    const float k = static_cast<float>(g_glyphs.k[static_cast<int>(set)]);
    const bool money = set == GameGlyphSet::Money || set == GameGlyphSet::Pop;
    if (c == ',' && money) return 3.0f * k;   // the thousands: a thin gap, never font 1's comma
    if (const BakedGlyph* b = Glyph(set, c)) return b->w + gap * k;
    if (c == ',') return 3.0f * k;
    if (c == ' ') return 5.0f * k;
    return 0.0f;
}
ImVec2 GlyphMeasure(GameGlyphSet set, const char* s, float gap) {
    float w = 0, h = 0;
    for (const char* p = s; *p; ++p) {
        w += GlyphAdvance(set, *p, gap);
        if (const BakedGlyph* b = Glyph(set, *p)) h = (std::max)(h, static_cast<float>(b->h));
    }
    if (*s) {
        const char last = s[strlen(s) - 1];
        if (Glyph(set, last)) w -= gap * g_glyphs.k[static_cast<int>(set)];
    }
    return ImVec2(w, h);
}
// Drawn 1:1 at whole pixels, the glyphs' own colours (white vertex colour), with a soft dark drop
// shadow one game pixel down-right so they read over a bright sky. `tint` multiplies (a dim copy).
void GlyphText(ImDrawList* dl, GameGlyphSet set, ImVec2 at, const char* s, float A, float gap, bool shadow = true,
               ImU32 tint = IM_COL32(255, 255, 255, 255)) {
    ImTextureID tex = ImGui::GetIO().Fonts->TexID;
    const float k = static_cast<float>(g_glyphs.k[static_cast<int>(set)]);
    const float h = GlyphMeasure(set, s, gap).y;
    float x = std::floor(at.x + 0.5f);
    const float y0 = std::floor(at.y + 0.5f);
    const int alpha = static_cast<int>(255.0f * (std::max)(0.0f, (std::min)(1.0f, A)) * ((tint >> IM_COL32_A_SHIFT) & 0xFF) / 255.0f);
    const ImU32 col = (tint & ~IM_COL32_A_MASK) | (static_cast<ImU32>(alpha) << IM_COL32_A_SHIFT);
    const ImU32 sh = IM_COL32(0, 0, 0, alpha * 110 / 255);
    const float so = (std::max)(1.0f, std::floor(k * 0.5f + 0.5f));
    const bool money = set == GameGlyphSet::Money || set == GameGlyphSet::Pop;
    for (const char* p = s; *p; ++p) {
        const BakedGlyph* b = money && *p == ',' ? nullptr : Glyph(set, *p);
        if (b) {
            const float y = y0 + (h - b->h);   // bottom-aligned (the strips' cells are one height)
            if (shadow) dl->AddImage(tex, ImVec2(x + so, y + so), ImVec2(x + so + b->w, y + so + b->h), b->uv0, b->uv1, sh);
            dl->AddImage(tex, ImVec2(x, y), ImVec2(x + b->w, y + b->h), b->uv0, b->uv1, col);
        }
        x += GlyphAdvance(set, *p, gap);
    }
}

void BuildFonts(int height) {
    ImGuiIO& io = ImGui::GetIO();
    io.Fonts->Clear();
    g_u = static_cast<float>(height) / 720.0f * g_cfg.scale;
    ImFontConfig cfg;
    cfg.FontDataOwnedByAtlas = false;
    cfg.OversampleH = 2;
    cfg.OversampleV = 1;
    static const ImWchar kRanges[] = {0x0020, 0x00FF, 0x2013, 0x2026, 0};
    auto add = [&](const unsigned char* data, size_t size, float px) {
        return io.Fonts->AddFontFromMemoryTTF(const_cast<unsigned char*>(data), static_cast<int>(size), px, &cfg, kRanges);
    };
    g_fonts.moneyPx = std::round(46.0f * g_u);
    g_fonts.heavyPx = std::round(26.0f * g_u);
    g_fonts.labelPx = std::round(17.0f * g_u);
    g_fonts.textPx = std::round(22.0f * g_u);
    g_fonts.money = add(kHudFontHeavy, sizeof kHudFontHeavy, g_fonts.moneyPx);
    g_fonts.heavy = add(kHudFontHeavy, sizeof kHudFontHeavy, g_fonts.heavyPx);
    g_fonts.label = add(kHudFontBold, sizeof kHudFontBold, g_fonts.labelPx);
    g_fonts.text = add(kHudFontText, sizeof kHudFontText, g_fonts.textPx);
    g_fonts.titlePx = std::round(92.0f * g_u);
    g_fonts.title = add(kHudFontHeavy, sizeof kHudFontHeavy, g_fonts.titlePx);
    const std::vector<PendingGlyph> pending = QueueGameGlyphs(io.Fonts);
    io.Fonts->Build();
    FinishGameGlyphs(io.Fonts, pending);
    ImGui_ImplDX9_InvalidateDeviceObjects();   // the font texture is made again on NewFrame
    g_fontHeight = height;
    Log("hud3d: fonts baked for %d lines (%.0f/%.0f/%.0f/%.0f px); game glyphs %s", height, g_fonts.moneyPx, g_fonts.heavyPx,
        g_fonts.labelPx, g_fonts.textPx, g_glyphs.on ? "on" : "off (Barlow)");
    if (g_glyphs.on)
        Log("hud3d: game glyphs re-authored at %dx (%s, %zu glyphs, generation %d): the money, multiplier, lives, hearts and ammunition in GTA2's own type",
            g_glyphs.k[0], g_cfg.glyphSmooth ? "edge-aware Scale2x/Scale3x" : "integer pixels", pending.size(), g_glyphs.gen);
}

bool EnsureContext(IDirect3DDevice9* device, int height) {
    if (g_ctx && g_device != device) return false;   // a device of its own once made; never seen change
    if (!g_ctx) {
        ImGuiContext* previous = ImGui::GetCurrentContext();
        g_ctx = ImGui::CreateContext();
        ImGui::SetCurrentContext(g_ctx);
        ImGuiIO& io = ImGui::GetIO();
        io.IniFilename = nullptr;
        io.LogFilename = nullptr;
        if (!ImGui_ImplDX9_Init(device)) {
            Log("hud3d: ImGui DX9 init failed; the game's HUD stays");
            ImGui::DestroyContext(g_ctx);
            g_ctx = nullptr;
            ImGui::SetCurrentContext(previous);
            return false;
        }
        g_device = device;
        BuildFonts(height);
        ImGui::SetCurrentContext(previous);
    }
    return true;
}

// Text with GTA2's black edge: a one-unit outline under it, then the colour.
void Text(ImDrawList* dl, ImFont* font, float px, ImVec2 at, ImU32 col, const char* s, float alpha, bool edge = true) {
    if (edge) {
        const float o = (std::max)(1.0f, std::round(1.5f * g_u));
        const ImU32 sh = Fade(kShadow, alpha * ((col >> IM_COL32_A_SHIFT) & 0xFF) / 255.0f);
        dl->AddText(font, px, ImVec2(at.x + o, at.y + o), sh, s);
        dl->AddText(font, px, ImVec2(at.x - o * 0.5f, at.y + o), sh, s);
        dl->AddText(font, px, ImVec2(at.x + o, at.y - o * 0.5f), sh, s);
    }
    dl->AddText(font, px, at, Fade(col, alpha), s);
}
ImVec2 Measure(ImFont* font, float px, const char* s) { return font->CalcTextSizeA(px, FLT_MAX, 0.0f, s); }

void Star(ImDrawList* dl, ImVec2 c, float r, ImU32 fill, ImU32 edge, bool filled) {
    ImVec2 p[10];
    for (int i = 0; i < 10; ++i) {
        const float a = -1.5707963f + i * 0.6283185f;
        const float rr = (i & 1) ? r * 0.45f : r;
        p[i] = ImVec2(c.x + std::cos(a) * rr, c.y + std::sin(a) * rr);
    }
    if (filled) for (int i = 0; i < 10; ++i) dl->AddTriangleFilled(c, p[i], p[(i + 1) % 10], fill);
    dl->AddPolyline(p, 10, edge, ImDrawFlags_Closed, (std::max)(1.0f, 1.6f * g_u));
}

void Panel(ImDrawList* dl, ImVec2 a, ImVec2 b, float alpha, ImU32 accent = 0) {
    dl->AddRectFilled(a, b, Fade(kGlass, alpha), 6.0f * g_u);
    if (accent) dl->AddRectFilled(a, ImVec2(a.x + 4.0f * g_u, b.y), Fade(accent, alpha), 6.0f * g_u, ImDrawFlags_RoundCornersLeft);
}

void DrawCapture(ImDrawList* dl, IDirect3DDevice9* device, const Capture& c, ImVec2 a, ImVec2 b, float alpha, ImU32 tint = IM_COL32_WHITE) {
    if (!c.texture || c.count != 4) return;
    const TextureRecord* rec = static_cast<const TextureRecord*>(c.texture);
    if (!rec->width || !rec->height) return;
    IDirect3DTexture9* tex = DeviceTextureFor(device, c.texture, nullptr, false);
    if (!tex) return;
    ImVec2 p[4], uv[4];
    for (int i = 0; i < 4; ++i) {
        p[i] = ImVec2(a.x + c.nx[i] * (b.x - a.x), a.y + c.ny[i] * (b.y - a.y));
        uv[i] = ImVec2(c.u[i] / rec->width, c.v[i] / rec->height);
    }
    dl->AddImageQuad(reinterpret_cast<ImTextureID>(tex), p[0], p[1], p[2], p[3], uv[0], uv[1], uv[2], uv[3],
                     Fade(tint | IM_COL32_A_MASK, alpha));
}

// ---- The mini-map's picture -----------------------------------------------------------
//
// FIX-HUD-4 (owner playtest 10 Nov, item 6: "increase the resolution of the nice map ... and
// change its shape from square to circular"). The map was one texel per cell (256x256),
// magnified ~8x at 720p (~15x at 1440p) and bilinear-filtered: every cell a soft square.
// Now the level's cells are classed once per level into tones (road, pavement, field, roofs
// by height) and each tone's cells merged into maximal rectangles; every frame the rectangles
// inside the inset are drawn as screen-space polygons through the camera's turn, with ImGui's
// one-pixel anti-aliased edges, and clipped exactly to the circle. So an edge is resolved at
// the output resolution whatever the window (no texture, no texel density to run out of).

constexpr int kMapTones = 6 * 5;   // base class x height lift
struct MapRect { uint16_t x0, y0, x1, y1; uint8_t tone; };
std::vector<MapRect> g_mapRects;   // sorted by tone (roads last: drawn on top)
ImU32 g_mapToneCol[kMapTones] = {};
int g_mapBaseTone = 0;             // the commonest tone: the circle's fill, not in g_mapRects
const void* g_mapKey = nullptr;
size_t g_mapBlocks = 0;
int g_mapCellsRoad = 0;
int g_mapSmoothed = 0;

void BuildMap(IDirect3DDevice9* /*device*/, const gta2::Map& map) {
    const void* key = map.Empty() ? nullptr : &map.ColumnAt(0, 0);
    if (!key) return;
    if (key == g_mapKey && map.BlockCount() == g_mapBlocks) return;
    // The tones of the old picture (pavement/park/roof tones kept), ABGR for ImGui.
    static const uint32_t kBase[6] = {0x0C0F14, 0x5E6676, 0x353B47, 0x2A2F3A, 0x1F3326, 0x1A1E27};
    for (int t = 0; t < kMapTones; ++t) {
        const uint32_t c = kBase[t / 5];
        const int lift = (t % 5) * 5;   // taller buildings a shade lighter
        const int r = (std::min)(255, static_cast<int>((c >> 16) & 0xFF) + lift);
        const int g = (std::min)(255, static_cast<int>((c >> 8) & 0xFF) + lift);
        const int b = (std::min)(255, static_cast<int>(c & 0xFF) + lift);
        // The HUD's vertex colours reach the screen squared by the display path (measured: kGreen
        // 92,204,96 shows as 27,156,29 under plain GL and Remix alike, the old map's texels as
        // written), so the tones go in as their 1/2.2 power: the old picture's colours on screen.
        auto lin = [](int x) { return static_cast<int>(std::lround(255.0 * std::pow(x / 255.0, 1.0 / 2.2))); };
        g_mapToneCol[t] = IM_COL32(lin(r), lin(g), lin(b), 255);
    }
    const int W = gta2::kMapWidth, H = gta2::kMapHeight;
    std::vector<uint8_t> tone(static_cast<size_t>(W) * H);
    int counts[kMapTones] = {};
    int roads = 0;
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const gta2::Column& col = map.ColumnAt(x, y);
            int type = -1, level = 0;
            for (int i = static_cast<int>(col.blocks.size()) - 1; i >= 0; --i) {
                const uint32_t index = col.blocks[i];
                if (index >= map.BlockCount()) continue;
                const gta2::Block& b = map.BlockAt(index);
                if (!b.lid) continue;
                type = b.GroundType();
                level = col.offset + i;
                break;
            }
            int base = 0;                                         // nothing: the edge of the world
            if (type == 1) { base = 1; ++roads; }                 // road
            else if (type == 2) base = level <= 2 ? 2 : 3;        // pavement / low roofs
            else if (type == 3) base = 4;                         // field, park
            else if (type == 0) base = 5;                         // a lid of air: roofs, decks
            // Roofs and decks a shade lighter the taller; a field is one green at any height (its
            // lifted squares read as noise at the disc's sharpness).
            const int lift = (type >= 0 && level >= 4 && type != 1 && type != 3) ? (std::min)(level - 3, 4) : 0;
            const uint8_t t = static_cast<uint8_t>(base * 5 + lift);
            tone[static_cast<size_t>(y) * W + x] = t;
            ++counts[t];
        }
    }
    // One-cell speckle (a lamp, a tree's top, a roof vent: no side neighbour of its own tone) is
    // merged into its surroundings where five or more of its eight neighbours share one tone;
    // paths one cell wide are kept, roads are never changed or grown.
    int changed = 0;
    for (int pass = 0; pass < 2; ++pass) {
        std::vector<uint8_t> smooth = tone;
        for (int y = 1; y + 1 < H; ++y) {
            for (int x = 1; x + 1 < W; ++x) {
                const uint8_t t = tone[static_cast<size_t>(y) * W + x];
                if (t / 5 == 1) continue;
                // A cell with a same-tone side neighbour is part of a path or a block: kept.
                if (tone[static_cast<size_t>(y - 1) * W + x] == t || tone[static_cast<size_t>(y + 1) * W + x] == t ||
                    tone[static_cast<size_t>(y) * W + x - 1] == t || tone[static_cast<size_t>(y) * W + x + 1] == t) continue;
                int best = -1, bestN = 0;
                uint8_t seen[8]; int n[8] = {}, k = 0;
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        if (!dx && !dy) continue;
                        const uint8_t q = tone[static_cast<size_t>(y + dy) * W + x + dx];
                        int j = 0;
                        while (j < k && seen[j] != q) ++j;
                        if (j == k) { seen[k] = q; ++k; }
                        if (++n[j] > bestN) { bestN = n[j]; best = q; }
                    }
                if (bestN >= 5 && best != t && best / 5 != 1) {
                    --counts[t]; ++counts[best];
                    smooth[static_cast<size_t>(y) * W + x] = static_cast<uint8_t>(best);
                    ++changed;
                }
            }
        }
        tone.swap(smooth);
    }
    g_mapSmoothed = changed;
    g_mapBaseTone = 0;
    for (int t = 1; t < kMapTones; ++t) if (counts[t] > counts[g_mapBaseTone]) g_mapBaseTone = t;
    // Greedy maximal rectangles per tone: a run along x, grown down while the whole run matches.
    std::vector<uint8_t> used(tone.size(), 0);
    g_mapRects.clear();
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const size_t i = static_cast<size_t>(y) * W + x;
            if (used[i]) continue;
            const uint8_t t = tone[i];
            int x1 = x + 1;
            while (x1 < W && !used[static_cast<size_t>(y) * W + x1] && tone[static_cast<size_t>(y) * W + x1] == t) ++x1;
            int y1 = y + 1;
            for (; y1 < H; ++y1) {
                bool ok = true;
                for (int xx = x; xx < x1 && ok; ++xx) {
                    const size_t j = static_cast<size_t>(y1) * W + xx;
                    ok = !used[j] && tone[j] == t;
                }
                if (!ok) break;
            }
            for (int yy = y; yy < y1; ++yy)
                for (int xx = x; xx < x1; ++xx) used[static_cast<size_t>(yy) * W + xx] = 1;
            if (t != g_mapBaseTone)
                g_mapRects.push_back({static_cast<uint16_t>(x), static_cast<uint16_t>(y), static_cast<uint16_t>(x1), static_cast<uint16_t>(y1), t});
        }
    }
    // Draw order: the dark classes first, the road network last (on top).
    auto rank = [](uint8_t t) { const int b = t / 5; return b == 1 ? 100 : b == 0 ? 0 : 10 + b * 5 + t % 5; };
    std::stable_sort(g_mapRects.begin(), g_mapRects.end(), [&](const MapRect& p, const MapRect& q) { return rank(p.tone) < rank(q.tone); });
    g_mapKey = key;
    g_mapBlocks = map.BlockCount();
    g_mapCellsRoad = roads;
    Log("hud3d: mini-map built from the level (%d road cells, %d speckle cells merged; %zu rectangles over the base tone %d)", roads, g_mapSmoothed, g_mapRects.size(), g_mapBaseTone);
}

// A convex polygon (clockwise on screen: increasing angle, y down) cut to the disc of radius R
// round c: its edges inside the disc, and where it leaves the disc the rim from that point on to
// where it comes back, in steps of `step` radians. Exact at the rim whatever the polygon's size
// (a Sutherland-Hodgman pass against a 96-gon cost ~0.2 ms a frame). Returns the point count.
int ClipDisc(const ImVec2* in, int n, ImVec2 c, float R, float step, ImVec2* out, int cap) {
    const float R2 = R * R;
    auto inside = [&](ImVec2 p) { const float dx = p.x - c.x, dy = p.y - c.y; return dx * dx + dy * dy <= R2; };
    int k = 0;
    bool anyIn = false, anyCross = false;
    float exitAngle = 0.0f;
    bool pendingExit = false, firstEntryNeeded = false;
    float firstEntryAngle = 0.0f;
    int firstExitSlot = -1;
    auto arc = [&](float a0, float a1) {   // the rim from a0 forward (increasing angle) to a1
        float span = a1 - a0;
        while (span < 0) span += 6.2831853f;
        while (span >= 6.2831853f) span -= 6.2831853f;
        for (float t = step; t < span && k < cap; t += step) out[k++] = ImVec2(c.x + std::cos(a0 + t) * R, c.y + std::sin(a0 + t) * R);
    };
    for (int i = 0; i < n; ++i) {
        const ImVec2 p = in[i], q = in[(i + 1) % n];
        const bool pin = inside(p), qin = inside(q);
        if (pin) { anyIn = true; if (k < cap) out[k++] = p; }
        // Intersections of p->q with the circle: |p + t (q - p) - c|^2 = R^2, 0 < t < 1.
        const float dx = q.x - p.x, dy = q.y - p.y, fx = p.x - c.x, fy = p.y - c.y;
        const float A = dx * dx + dy * dy, B = 2 * (fx * dx + fy * dy), C = fx * fx + fy * fy - R2;
        const float disc = B * B - 4 * A * C;
        if (A < 1e-9f || disc <= 0) continue;
        const float sq = std::sqrt(disc);
        const float t0 = (-B - sq) / (2 * A), t1 = (-B + sq) / (2 * A);
        // Entering at t0 (outside -> inside), leaving at t1.
        const float ts[2] = {t0, t1};
        for (int j = 0; j < 2; ++j) {
            const float t = ts[j];
            if (t <= 0.0f || t >= 1.0f) continue;
            anyCross = true;
            const ImVec2 x(p.x + dx * t, p.y + dy * t);
            const float ang = std::atan2(x.y - c.y, x.x - c.x);
            if (j == 0) {   // entering
                if (pendingExit) arc(exitAngle, ang);
                else if (!firstEntryNeeded && firstExitSlot < 0) { firstEntryNeeded = true; firstEntryAngle = ang; }
                pendingExit = false;
                if (k < cap) out[k++] = x;
            } else {        // leaving
                if (k < cap) out[k++] = x;
                exitAngle = ang;
                pendingExit = true;
                if (firstExitSlot < 0) firstExitSlot = k;
            }
        }
        (void)qin;
    }
    // The polygon's walk began outside: the last exit joins the first entry over the rim.
    if (pendingExit && firstEntryNeeded) arc(exitAngle, firstEntryAngle);
    if (!anyIn && !anyCross) {
        // Disjoint, or the polygon holds the whole disc (its centre inside every edge).
        bool holds = true;
        for (int i = 0; i < n && holds; ++i) {
            const ImVec2 p = in[i], q = in[(i + 1) % n];
            holds = (q.x - p.x) * (c.y - p.y) - (q.y - p.y) * (c.x - p.x) >= 0;
        }
        if (!holds) return 0;
        k = 0;
        for (float t = 0; t < 6.2831853f && k < cap; t += step) out[k++] = ImVec2(c.x + std::cos(t) * R, c.y + std::sin(t) * R);
    }
    return k;
}

// The level inside a circle of radius R (pixels) round the screen point c; the player at game
// (px,py) drawn at the screen point pc, the camera's turn (cs,sn), `scale` pixels a block.
struct MapDrawStats { int rects = 0, clipped = 0, frames = 0; long long ticks = 0, respectTicks = 0, renderTicks = 0, vtx = 0, cmds = 0; int renders = 0; };
MapDrawStats g_mapStats;
MapDrawStats DrawMapDisc(ImDrawList* dl, ImVec2 c, float R, ImVec2 pc, float px, float py, float cs, float sn, float scale, float alpha) {
    MapDrawStats st;
    constexpr int kSeg = 96;
    ImVec2 circ[kSeg];
    for (int i = 0; i < kSeg; ++i) {   // clockwise on screen (y down): increasing angle
        const float a = i * (6.2831853f / kSeg);
        circ[i] = ImVec2(c.x + std::cos(a) * R, c.y + std::sin(a) * R);
    }
    dl->AddConvexPolyFilled(circ, kSeg, Fade(g_mapToneCol[g_mapBaseTone], alpha));
    const float worldR = (R + std::hypot(pc.x - c.x, pc.y - c.y)) / scale + 1.5f;
    const float e = 0.6f / scale;   // half a pixel and a bit: same-tone neighbours overlap, no seam
    const float in2 = (R - 1.0f) * (R - 1.0f);
    ImVec2 poly[4], out[kSeg + 8];
    for (const MapRect& r : g_mapRects) {
        // Nearest point of the rectangle to the player, against the disc's radius in blocks.
        const float nx = (std::max)(static_cast<float>(r.x0), (std::min)(px, static_cast<float>(r.x1)));
        const float ny = (std::max)(static_cast<float>(r.y0), (std::min)(py, static_cast<float>(r.y1)));
        if ((nx - px) * (nx - px) + (ny - py) * (ny - py) > worldR * worldR) continue;
        const float gx[4] = {r.x0 - e, r.x1 + e, r.x1 + e, r.x0 - e};
        const float gy[4] = {r.y0 - e, r.y0 - e, r.y1 + e, r.y1 + e};
        bool inside = true;
        for (int i = 0; i < 4; ++i) {
            const float dx = gx[i] - px, dy = gy[i] - py;
            const float rr = dx * cs + dy * sn, f = dx * sn - dy * cs;
            poly[i] = ImVec2(pc.x + rr * scale, pc.y - f * scale);
            const float ox = poly[i].x - c.x, oy = poly[i].y - c.y;
            inside = inside && ox * ox + oy * oy <= in2;
        }
        // Clockwise on screen.
        const float area = (poly[1].x - poly[0].x) * (poly[2].y - poly[0].y) - (poly[1].y - poly[0].y) * (poly[2].x - poly[0].x);
        if (area < 0) std::swap(poly[1], poly[3]);
        const ImU32 col = Fade(g_mapToneCol[r.tone], alpha);
        ++st.rects;
        if (inside) { dl->AddConvexPolyFilled(poly, 4, col); continue; }
        const int n = ClipDisc(poly, 4, c, R, 6.2831853f / kSeg, out, kSeg + 8);
        if (n >= 3) { dl->AddConvexPolyFilled(out, n, col); ++st.clipped; }
    }
    return st;
}

// ---- QB-50: pickup labels and score pops in the world ----------------------------------
//
// Over each floating pickup within kLabelFar blocks of the eye, its name ("SHOTGUN",
// "POWER-UP": which power-up a token's colour is is not mapped) on a small dark pill, fading
// out with distance. A money gain floats "+$n" up from the player (in first person, a little
// ahead of the eye) and fades; a weapon picked up (its ammo rising) floats its name up from
// the pickup he walked over (else from him). The pickups and the projection come from
// map_objects.cpp, read back from the frame the street views drew. A label whose pickup
// is behind a wall (the line from the eye to it crosses a block with a solid side face,
// ViewLineWalled; lids alone do not count, or a pickup under a deck would lose its label)
// is not drawn (pm-pickup-label-floats-on-wall-and-in-air: "MACHINE GUN" hung on a facade).

std::string Thousands(long long v);   // below, with the money counter

constexpr float kLabelNear = 0.45f, kLabelFull = 4.0f, kLabelFar = 7.0f, kPopTime = 1.6f;

struct WorldLayer {
    struct Pop { float x, y, z, t; std::string text; ImU32 col; };
    std::vector<Pop> pops;
    int lastMoney = -1, lastWeapon = -1, lastAmmo = -1;
    uint32_t lastPickupsFrame = 0;
    struct Recent { float x, y, z; double seen; const char* label; };
    std::vector<Recent> recent;            // pickups seen near him in the last half second
    double clock = 0.0, lastLog = 0.0;
    int moneyPops = 0, weaponPops = 0, labelledPeak = 0, labelFrames = 0;
};
WorldLayer g_world;
int g_noWorldLabels = -1;   // GTA2DX9_PICKUP_LABELS=0 turns the layer off (QA before/after)

// Where a pop starts: the given point, or, when that is within reach of the eye (his own
// chest in first person), 1.2 blocks ahead of the eye a little below its line.
void PopAnchor(float* x, float* y, float* z) {
    float eye[3], dir[3];
    if (!MapObjectsEye(eye, dir)) return;
    const float dx = *x - eye[0], dy = *y - eye[1], dz = *z - eye[2];
    if (dx * dx + dy * dy + dz * dz < 0.8f * 0.8f) {
        *x = eye[0] + dir[0] * 1.2f;
        *y = eye[1] + dir[1] * 1.2f - 0.12f;
        *z = eye[2] + dir[2] * 1.2f;
    }
}

void DrawWorldLayer(ImDrawList* dl, const Values& v, float A, float W, float H, float dt) {
    if (g_noWorldLabels < 0) {
        const char* e = getenv("GTA2DX9_PICKUP_LABELS");
        g_noWorldLabels = (e && e[0] == '0') ? 1 : 0;
        Log("hud3d: pickup labels and world score pops %s (QB-50)", g_noWorldLabels ? "off" : "on");
    }
    if (g_noWorldLabels) return;
    WorldLayer& w = g_world;
    w.clock += dt;
    const float u = g_u;
    // The pickups list is this frame's only when the street views drew since the last HUD frame.
    const bool fresh = MapObjectPickupsFrame() != w.lastPickupsFrame;
    w.lastPickupsFrame = MapObjectPickupsFrame();
    const float px = v.x, pz = static_cast<float>(gta2::kMapHeight) - v.y;
    const float py = ViewPlayer().z;

    // Pickups near him lately: where a weapon he just got came from.
    if (fresh) {
        for (const PickupSpot& p : MapObjectPickups()) {
            if (std::hypot(p.x - px, p.z - pz) < 1.2f && std::fabs(p.y - py) < 1.0f) {
                bool known = false;
                for (WorldLayer::Recent& r : w.recent) {
                    if (std::fabs(r.x - p.x) < 0.05f && std::fabs(r.z - p.z) < 0.05f) { r.seen = w.clock; r.y = p.y; known = true; }
                }
                if (!known) w.recent.push_back({p.x, p.y, p.z, w.clock, p.label});
            }
        }
    }
    w.recent.erase(std::remove_if(w.recent.begin(), w.recent.end(), [&](const WorldLayer::Recent& r) { return w.clock - r.seen > 0.6; }), w.recent.end());

    // New pops: money gained; a weapon picked up.
    if (v.money >= 0) {
        if (w.lastMoney >= 0 && v.money > w.lastMoney) {
            char text[40];
            snprintf(text, sizeof text, "+%s", Thousands(v.money - w.lastMoney).c_str());
            float x = px, y = py + 0.55f, z = pz;
            PopAnchor(&x, &y, &z);
            w.pops.push_back({x, y, z, kPopTime, text, kYellow});
            ++w.moneyPops;
        }
        w.lastMoney = v.money;
    }
    if (v.weapon > 0 && w.lastWeapon >= 0) {
        // More ammo for the weapon in hand, or a new weapon in hand just after he passed over
        // a pickup (a switch with no pickup near is the player choosing, not a pickup).
        const bool gained = v.weapon == w.lastWeapon ? v.ammo > w.lastAmmo : !w.recent.empty();
        if (gained) {
            float x = px, y = py + 0.5f, z = pz;
            if (!w.recent.empty()) {
                const WorldLayer::Recent* best = &w.recent[0];
                for (const WorldLayer::Recent& r : w.recent)
                    if (std::hypot(r.x - px, r.z - pz) < std::hypot(best->x - px, best->z - pz)) best = &r;
                x = best->x; y = best->y + 0.15f; z = best->z;
            }
            PopAnchor(&x, &y, &z);
            std::string name = WeaponName(v.weapon);
            for (char& c : name) c = c == '_' ? ' ' : static_cast<char>(toupper(static_cast<unsigned char>(c)));   // FIX-HUD-8: was MACHINE_GUN
            w.pops.push_back({x, y, z, kPopTime, name, kGreen});
            ++w.weaponPops;
            w.recent.clear();
        }
    }
    if (v.weapon >= 0) { w.lastWeapon = v.weapon; w.lastAmmo = v.ammo; }

    // Labels over the pickups, nearest drawn last (on top).
    int labelled = 0;
    if (fresh || w.clock < 0.1) {
        std::vector<const PickupSpot*> order;
        for (const PickupSpot& p : MapObjectPickups())
            if (p.eyeDistance > kLabelNear && p.eyeDistance < kLabelFar) order.push_back(&p);
        std::sort(order.begin(), order.end(), [](const PickupSpot* a, const PickupSpot* b) { return a->eyeDistance > b->eyeDistance; });
        float eye[3], eyeDir[3];
        const bool haveEye = MapObjectsEye(eye, eyeDir);
        for (const PickupSpot* p : order) {
            float sx, sy;
            if (!MapObjectsProject(p->x, p->y + 0.22f, p->z, &sx, &sy)) continue;
            if (sx < -0.05f || sx > 1.05f || sy < -0.05f || sy > 1.05f) continue;
            // Behind a wall: the pickup itself is hidden by the depth test, so no label either.
            if (haveEye && ViewLineWalled(eye[0], eye[1], eye[2], p->x, p->y + 0.15f, p->z)) continue;
            const float nearA = (std::min)(1.0f, (p->eyeDistance - kLabelNear) / 0.35f);
            const float farA = p->eyeDistance < kLabelFull ? 1.0f : 1.0f - (p->eyeDistance - kLabelFull) / (kLabelFar - kLabelFull);
            const float a = A * (std::max)(0.0f, (std::min)(nearA, farA));
            if (a < 0.02f) continue;
            const float px2 = g_fonts.labelPx * (p->eyeDistance < 2.0f ? 1.0f : (std::max)(0.72f, 1.0f - (p->eyeDistance - 2.0f) * 0.06f));
            const ImVec2 ts = Measure(g_fonts.label, px2, p->label);
            const ImVec2 at(sx * W - ts.x * 0.5f, sy * H - ts.y);
            const float padX = 6 * u, padY = 2 * u;
            dl->AddRectFilled(ImVec2(at.x - padX, at.y - padY), ImVec2(at.x + ts.x + padX, at.y + ts.y + padY), Fade(kGlass, a), 4 * u);
            dl->AddRectFilled(ImVec2(at.x - padX, at.y + ts.y + padY - 2 * u), ImVec2(at.x + ts.x + padX, at.y + ts.y + padY), Fade(kCyan, a * 0.9f), 1 * u);
            Text(dl, g_fonts.label, px2, at, kWhite, p->label, a, false);
            ++labelled;
        }
    }
    if (labelled) ++w.labelFrames;
    w.labelledPeak = (std::max)(w.labelledPeak, labelled);

    // The pops: rise half a block, hold, fade.
    for (WorldLayer::Pop& p : w.pops) {
        const float age = kPopTime - p.t;
        float sx, sy;
        if (MapObjectsProject(p.x, p.y + 0.5f * (1.0f - std::exp(-age * 2.5f)), p.z, &sx, &sy)) {
            const float a = A * (std::min)(1.0f, p.t / 0.5f) * (std::min)(1.0f, age / 0.08f);
            const float scale = 1.0f + 0.25f * std::exp(-age * 8.0f);   // a little punch on arrival
            const float fpx = g_fonts.heavyPx * scale;
            const ImVec2 ts = Measure(g_fonts.heavy, fpx, p.text.c_str());
            Text(dl, g_fonts.heavy, fpx, ImVec2(sx * W - ts.x * 0.5f, sy * H - ts.y * 0.5f), p.col, p.text.c_str(), a);
        }
        p.t -= dt;
    }
    w.pops.erase(std::remove_if(w.pops.begin(), w.pops.end(), [](const WorldLayer::Pop& p) { return p.t <= 0.0f; }), w.pops.end());

    if (w.clock - w.lastLog >= 2.0) {
        w.lastLog = w.clock;
        float nearest = 99.0f;
        const PickupSpot* nearSpot = nullptr;
        for (const PickupSpot& p : MapObjectPickups()) if (p.eyeDistance < nearest) { nearest = p.eyeDistance; nearSpot = &p; }
        float eye[3], eyeDir[3];
        const bool haveEye = MapObjectsEye(eye, eyeDir);
        const int nearBlocked = (nearSpot && haveEye) ? (ViewLineWalled(eye[0], eye[1], eye[2], nearSpot->x, nearSpot->y + 0.15f, nearSpot->z) ? 1 : 0) : -1;
        Log("hud3d: world layer: pickups drawn=%zu (nearest %.2f from the eye: %s at %.1f,%.2f,%.1f, wall between %d) labelled=%d (peak %d, %d frames with a label) pops money=%d weapon=%d live=%zu",
            MapObjectPickups().size(), nearest, nearSpot ? nearSpot->label : "-", nearSpot ? nearSpot->x : 0.0f, nearSpot ? nearSpot->y : 0.0f, nearSpot ? nearSpot->z : 0.0f, nearBlocked,
            labelled, w.labelledPeak, w.labelFrames, w.moneyPops, w.weaponPops, w.pops.size());
        w.labelledPeak = 0;
        w.labelFrames = 0;
    }
}

// ---- Animation state ----------------------------------------------------------------------

struct Anim {
    float fade = 0.0f;           // the whole HUD's opacity
    double money = -1;           // the shown money, ticking to the real one
    int lastMoney = -1;
    float gain = 0;              // seconds left of the "+$n" pop
    int gainAmount = 0;
    int lastHealth = -1;
    float hurt = 0;              // the damage flash, 1 at a hit
    float briefAlpha = 0;
    std::string briefKey;
    std::vector<Word> brief;
    Capture briefPortrait;
    float time = 0;
    float zoom = 34.0f;          // blocks across the mini-map
    bool cutIn = false;          // the modern HUD comes on next frame, at full strength (pm7)
    float lift = 0.0f;           // pixels the mini-map is raised above the game's own subtitle box (eased)
};
Anim g_anim;

LARGE_INTEGER g_qpf = {};
double g_costSum = 0, g_costWorst = 0;
int g_costFrames = 0;
LARGE_INTEGER g_lastStamp = {};
uint32_t g_lastLog = 0;
bool g_toggleDown = false;

bool KeyEdge(int vk, bool* down) {
    const bool now = vk > 0 && (GetAsyncKeyState(vk) & 0x8000) != 0;
    const bool edge = now && !*down;
    *down = now;
    return edge;
}

std::string Thousands(long long v) {
    char raw[32];
    snprintf(raw, sizeof raw, "%lld", v < 0 ? -v : v);
    std::string s;
    const int n = static_cast<int>(strlen(raw));
    for (int i = 0; i < n; ++i) {
        s.push_back(raw[i]);
        if ((n - i - 1) % 3 == 0 && i != n - 1) s.push_back(',');
    }
    return (v < 0 ? "-$" : "$") + s;
}


// ---- QB-6: the reticle, the target and the hit markers ------------------------------------
//
// GTA2 has no aim: a bullet leaves the gun along the way the pedestrian faces. So the reticle
// marks that line. The target is the first person standing on it (within a corridor that
// widens a little with range, and not behind a wall) up to the weapon's reach; with one the
// reticle sits on his chest, turns red and brackets him; with none it sits where the line
// meets a wall or runs out. A shot opens the reticle for a moment. A hit is the game's own
// word: a person's health word drops (or he goes down) within a second of the player's
// shot while he is near the line of fire; it flashes an X on the reticle, white, or red and
// larger for a kill, and the hit is counted against whether he was the one highlighted when
// the shot left the gun (docs/quality-bar.md FEEL-13: >= 90 %).

struct AimHud {
    bool show = false;
    float fade = 0.0f;
    bool target = false;
    uintptr_t targetObject = 0;
    float tx = 0, ty = 0, tz = 0;            // the target's sprite origin
    bool reticleKnown = false;
    float rx = 0, ry = 0;                     // the reticle, pixels, eased
    float bracketHalf = 0;                    // the target's projected half height, pixels
    float spread = 0;                         // 1 just after a shot, decaying
    float retFade = 0;                        // the reticle's own fade (third person: aiming only, never on him)
    bool retOnHero = false;                   // this frame's reticle fell inside his projected figure
    uint32_t lastShots = 0;
    uintptr_t targetAtShot = 0;
    // The people highlighted at the shots of the last 0.7 s: a machine gun's hit may come
    // from any shot of the burst still in the air.
    std::vector<std::pair<uintptr_t, double>> recentTargets;
    double shotTime = -10.0;
    double clock = 0.0;
    float hitT = 0;                           // the X's remaining time, seconds
    bool hitKill = false;
    struct Pop { float x, y, z, t; bool kill; };
    std::vector<Pop> pops;                    // marks on the people hit
    struct Seen { int health; bool corpse; double hitAt; };   // hitAt: our last hit on him, -1 none
    std::unordered_map<uintptr_t, Seen> seen;
    int shots = 0, hits = 0, hitsHighlighted = 0, kills = 0, shotsWithTarget = 0;
    int framesArmed = 0, framesShown = 0;
    double lastLog = 0.0;
    int hitLogs = 0;
    // FIX-AIM-2 (owner10nov B9b): why a shot left with nothing highlighted, by class (the aim: noTarget line), and
    // the person highlighted last before it (a target lost between the reticle and the press).
    uintptr_t lastHighlighted = 0;
    double lastHighlightedAt = -10.0;
    int ntNobody = 0, ntRange = 0, ntBearing = 0, ntWall = 0, ntLid = 0, ntHeight = 0, ntLost = 0, ntOther = 0;
    int shotLogs = 0;
    // FIX-AIM-2: each shot's target followed for 1 s: his velocity across and along the line of fire (from the drawn
    // people) and whether he was hit: the 'aim: shot N ->' outcome line (GTA2DX9_LOG_AIM=1).
    struct Followed { int shot; uintptr_t obj; float x0, z0, hx, hz, d0; double t0; float x1 = 0, z1 = 0; double t1 = -1.0; bool hit = false; bool anyHit = false; };
    std::vector<Followed> followed;
    int outShots = 0, outHits = 0, outMoving = 0, outMovingHits = 0;
};
AimHud g_aimHud;


float WeaponReach(int weapon) {
    switch (weapon) {
        case 6: case 10: return 3.0f;    // electro gun, flamethrower
        case 7: case 8: return 6.0f;     // molotov, grenade (thrown)
        case 9: return 6.0f;             // shotgun
        case 5: return 12.0f;            // rocket launcher
        default: return 10.0f;           // the pistols and machine guns
    }
}

// ---- FIX-AIM-1 (owner10nov B9): every attack, what was in front of him and what the game made of it ----------
// One record per press of the fire key the game was told of (ViewFirePresses), on foot in a street view, fists or
// armed. At the press: his facing (the game's), the weapon, and every standing person within reach of the weapon
// (fists 2 blocks) with distance, bearing off his facing, height step and the corridor test's verdict. Then for
// the window after it (fists 0.6 s while the key is up, extended while held; guns 1.2 s) whose health word drops
// or who goes down: the game's own hit. GTA2DX9_LOG_AIM=1 logs one 'aim: swing' line at the press and one
// 'aim: swing ... ->' line with the outcome; the 'aim: fists' tally rides with the shots tally every 10 s.
struct SwingLog {
    uint32_t presses = 0;
    bool open = false;
    int id = 0, weapon = 0;
    double t0 = 0.0, until = 0.0;
    float ox = 0, oz = 0, heading = 0;
    bool hadTarget = false;      // a standing person within the weapon's reach and arc at the press
    uintptr_t aimed = 0;         // the candidate nearest his facing line
    std::unordered_map<uintptr_t, std::pair<int, bool>> before;   // health, down the frame before the press
    std::unordered_map<uintptr_t, std::pair<int, bool>> lastFrame;   // every drawn person's, last fresh frame
    bool pressPending = false;   // a press seen on a frame whose people list was not fresh yet
    std::vector<std::pair<uintptr_t, int>> hits;   // who dropped, by how much
    int fistSwings = 0, fistWithTarget = 0, fistHits = 0, fistMissWithTarget = 0;
    int missNobody = 0, missArc = 0, missNoContact = 0;   // the fists' misses by reason (the melee: line)
    float nearD = -1.0f, nearOff = 0.0f;                  // the nearest standing person at the press, any bearing
    int gunSwings = 0, gunWithTarget = 0, gunHits = 0;
};
SwingLog g_swing;

bool AimLogOn() {
    static int on = -1;
    if (on < 0) { char b[4] = {}; on = GetEnvironmentVariableA("GTA2DX9_LOG_AIM", b, sizeof b) && b[0] == '1'; }
    return on == 1;
}

float AimDegOff(float heading, float dx, float dz) {
    float a = std::atan2(dx, dz) - heading;
    while (a > 3.14159265f) a -= 6.2831853f;
    while (a < -3.14159265f) a += 6.2831853f;
    return a * 57.29578f;
}

// FIX-AIM-2 (owner10nov B9b): what stands between his gun and a person. 0 clear, 1 a lid only (a kerb step, a deck,
// the road under a ramp: the old test called him covered, the game's bullets reached him, fixaim1_gun2 swings 4/6),
// 2 a wall (a block with a solid side face). AimCovered: the verdict the pick and the reticle use (aim_cover_walls=1:
// walls only; 0: the old lid-and-wall test).
int AimCoverOf(float x0, float y0, float z0, float x1, float y1, float z1) {
    if (ViewLineWalled(x0, y0, z0, x1, y1, z1)) return 2;
    return ViewLineBlocked(x0, y0, z0, x1, y1, z1) ? 1 : 0;
}
bool AimCovered(float x0, float y0, float z0, float x1, float y1, float z1) {
    return ViewAimCoverWallsOn() ? ViewLineWalled(x0, y0, z0, x1, y1, z1) : ViewLineBlocked(x0, y0, z0, x1, y1, z1);
}

// FIX-AIM-2 (owner10nov B9b): one shot, what the targeting saw. The game's bullet leaves along his facing (the
// heading the renderer reads from the game, a.headingYaw); the highlighted person is the owner counter's
// with_target. With none: the class, from every standing person within reach + 4 blocks: 'lost' (someone was
// highlighted within 0.3 s before the shot), 'wall' / 'lid' (the nearest-bearing person inside the arc and reach
// is behind a wall / only a lid by the old test), 'height' (more than 1.2 blocks above or below), 'range' (inside
// the arc but beyond the weapon's reach), 'bearing' (in reach, every one outside the arc: the smallest angle off
// is logged), 'nobody' (no one within reach + 4). GTA2DX9_LOG_AIM=1 adds one 'aim: shot N' line per shot.
void ClassifyShot(AimHud& h, const AimState& a, const std::vector<AimPed>& peds, int n) {
    const bool first = CurrentViewMode() == ViewMode::FirstPerson;
    const float reach = WeaponReach(a.weapon);
    const float arc = ViewAimAssistOn() ? (first ? 12.0f : 30.0f) : 20.0f;
    const float ox = a.x, oy = a.y + 0.30f, oz = a.z;
    // The nearest by bearing among those inside the reach + 4 band.
    const AimPed* inArc = nullptr; float inArcOff = 1e9f, inArcD = 0.0f;
    const AimPed* any = nullptr; float anyOff = 1e9f, anyD = 0.0f;
    bool tooHigh = false;
    for (const AimPed& p : peds) {
        if (p.corpse || p.health == 0) continue;
        const float dx = p.x - ox, dz = p.z - oz, d = std::hypot(dx, dz);
        if (d < 0.05f || d > reach + 4.0f) continue;
        const float off = std::fabs(AimDegOff(a.headingYaw, dx, dz));
        if (std::fabs(p.y - a.y) > 1.2f) { if (off <= arc && d <= reach) tooHigh = true; continue; }
        if (off < anyOff && d <= reach) { anyOff = off; anyD = d; any = &p; }
        if (off <= arc && off < inArcOff) { inArcOff = off; inArcD = d; inArc = &p; }
    }
    const char* cls = "target";
    int cover = 0;
    char who[96] = "";
    if (h.target) {
        const float dx = h.tx - ox, dz = h.tz - oz;
        snprintf(who, sizeof who, "%04x d=%.2f off=%+.1f", static_cast<unsigned>((h.targetObject >> 2) & 0xFFFF), std::hypot(dx, dz),
                 AimDegOff(a.headingYaw, dx, dz));
    } else {
        if (h.lastHighlighted && h.clock - h.lastHighlightedAt < 0.3) { cls = "lost"; h.ntLost += n; }
        else if (inArc && inArcD <= reach) {
            cover = AimCoverOf(ox, oy, oz, inArc->x, inArc->y + 0.25f, inArc->z);
            if (cover == 2) { cls = "wall"; h.ntWall += n; }
            else if (cover == 1) { cls = "lid"; h.ntLid += n; }
            else { cls = "other"; h.ntOther += n; }
        } else if (tooHigh) { cls = "height"; h.ntHeight += n; }
        else if (inArc) { cls = "range"; h.ntRange += n; }
        else if (any) { cls = "bearing"; h.ntBearing += n; }
        else { cls = "nobody"; h.ntNobody += n; }
        const AimPed* q = inArc ? inArc : any;
        if (q) snprintf(who, sizeof who, "nearest-bearing %04x d=%.2f off=%+.1f", static_cast<unsigned>((q->object >> 2) & 0xFFFF),
                        inArc ? inArcD : anyD, inArc ? inArcOff : anyOff);
    }
    if (AimLogOn() && h.shotLogs < 400) {
        ++h.shotLogs;
        Log("aim: shot %d weapon %d %s fire heading %.1f at %.2f,%.2f reach %.0f arc %.0f -> %s %s%s", h.shots, a.weapon, first ? "first" : "third",
            a.headingYaw * 57.29578f, a.x, static_cast<float>(gta2::kMapHeight) - a.z, reach, arc, h.target ? "TARGET" : "NO TARGET:", h.target ? "" : cls,
            who[0] ? (std::string(" ") + who).c_str() : "");
    }
}

// FIX-AIM-1: the person an attack is meant for, the one the aim assist turns him onto and the reticle highlights.
// Fists: within kFistPick blocks and 75 degrees of his facing, nearest by distance and angle. A gun: within its
// reach, 30 degrees (12 in first person, where the view already aims), not behind a wall, smallest angle first.
// tol: how far off his heading may be and still land (fists kFistTolDeg; a gun: the angle of a quarter block at
// his distance, 2.5-8 degrees).
constexpr float kFistPick = 1.2f, kFistArcDeg = 75.0f, kFistTolDeg = 12.0f;
uintptr_t g_lastPick = 0;
struct AimPick { bool valid = false; uintptr_t object = 0; float x = 0, y = 0, z = 0, d = 0, bearing = 0, tol = 0, offDeg = 0; };
AimPick ComputeAimPick(const AimState& a, const std::vector<AimPed>& peds) {
    AimPick best;
    if (!a.valid || ViewPlayer().inVehicle) return best;
    const bool fists = a.weapon == 0;
    const bool first = CurrentViewMode() == ViewMode::FirstPerson;
    const float reach = fists ? kFistPick : WeaponReach(a.weapon);
    const float arc = fists ? kFistArcDeg : (first ? 12.0f : 30.0f);
    float bestScore = 1e9f;
    for (const AimPed& p : peds) {
        if (p.corpse || p.health == 0) continue;
        const float dx = p.x - a.x, dz = p.z - a.z, d = std::hypot(dx, dz);
        if (d < 0.05f || d > reach) continue;
        if (std::fabs(p.y - a.y) > (fists ? 0.6f : 1.2f)) continue;
        const float off = std::fabs(AimDegOff(a.headingYaw, dx, dz));
        if (off > arc) continue;
        const float score = (fists ? off + 40.0f * d : off + 1.5f * d) - (p.object == g_lastPick ? 12.0f : 0.0f);   // keeps the one he turns onto
        if (score >= bestScore) continue;
        if (!fists && AimCovered(a.x, a.y + 0.30f, a.z, p.x, p.y + 0.25f, p.z)) continue;
        bestScore = score;
        best.valid = true; best.object = p.object; best.x = p.x; best.y = p.y; best.z = p.z; best.d = d; best.offDeg = off;
        best.bearing = std::atan2(dx, dz);
        best.tol = fists ? kFistTolDeg * 0.0174533f : (std::min)(8.0f * 0.0174533f, (std::max)(2.5f * 0.0174533f, std::atan2(0.25f, d)));
    }
    g_lastPick = best.valid ? best.object : 0;
    return best;
}

void UpdateSwingLog(bool street, const AimState& a, const std::vector<AimPed>& peds, bool fresh, double clock) {
    SwingLog& g = g_swing;
    const uint32_t presses = ViewFirePresses();
    const bool onFoot = street && a.valid && !ViewPlayer().inVehicle;
    const bool fireHeld = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
    // The outcome: any drop of a health word (or a fall) among the people seen at the press.
    auto scan = [&]() {
        for (const AimPed& p : peds) {
            const auto it = g.before.find(p.object);
            if (it == g.before.end() || it->second.second) continue;
            // A blow or a bullet of his: within the weapon's reach of where he stood (a car running a man down
            // across the street is not his swing).
            if (std::hypot(p.x - g.ox, p.z - g.oz) > (g.weapon == 0 ? 1.5f : WeaponReach(g.weapon) + 1.5f)) continue;
            const int was = it->second.first;
            if ((p.health >= 0 && p.health < was) || p.corpse) {
                bool known = false;
                for (auto& hgot : g.hits) if (hgot.first == p.object) { known = true; hgot.second = was - p.health; }
                if (!known) g.hits.push_back({p.object, was - p.health});
                it->second.first = p.health;
                if (p.corpse) it->second.second = true;
            }
        }
        if (g.weapon == 0 && fireHeld) g.until = (std::max)(g.until, clock + 0.6);   // held fists swing again
    };
    if (g.open && fresh) scan();
    if (g.open && (clock >= g.until || presses != g.presses || !onFoot)) {
        g.open = false;
        const bool fists = g.weapon == 0;
        if (!g.hits.empty()) { if (fists) ++g.fistHits; else ++g.gunHits; }
        else if (fists && g.hadTarget) ++g.fistMissWithTarget;
        // owner10nov B9a: the melee: line, always on, one per punch. A miss's reason: nobody within 1.2 blocks; the
        // nearest outside 75 degrees of his facing; or nobody touching him (GTA2's fist takes only a ped overlapping
        // his own body within 0.25 block, FUN_00433D00: a man standing a step off is never hit, whichever way he faces).
        if (fists) {
            const char* why = "";
            if (g.hits.empty()) {
                if (g.nearD < 0.0f || g.nearD > kFistPick) { why = "nothing in range"; ++g.missNobody; }
                else if (std::fabs(g.nearOff) > kFistArcDeg) { why = "outside the arc"; ++g.missArc; }
                else { why = "no contact (the game hits only a body touching his, within 0.25 block)"; ++g.missNoContact; }
            }
            Log("melee: swing %d %s%s%s nearest %.2f block %+.0f deg off his facing at the press (%s)", g.fistSwings, g.hits.empty() ? "MISS: " : "HIT",
                why, g.hits.empty() ? ";" : ":", g.nearD, g.nearOff, CurrentViewMode() == ViewMode::FirstPerson ? "first" : "third");
        }
        if (AimLogOn()) {
            std::string what;
            for (const auto& hgot : g.hits) {
                char b[96];
                float d = -1.0f, off = 0.0f;
                for (const AimPed& p : peds) if (p.object == hgot.first) { d = std::hypot(p.x - g.ox, p.z - g.oz); off = AimDegOff(g.heading, p.x - g.ox, p.z - g.oz); }
                snprintf(b, sizeof b, " %04x(-%d d=%.2f off=%.0f%s)", static_cast<unsigned>((hgot.first >> 2) & 0xFFFF), hgot.second, d, off,
                         hgot.first == g.aimed ? " aimed" : "");
                what += b;
            }
            Log("aim: swing %d -> %s%s (%.2f s)", g.id, g.hits.empty() ? (g.hadTarget ? "MISS with a person in reach" : "miss, nobody in reach") : "HIT",
                what.c_str(), clock - g.t0);
        }
    }
    // GTA2 takes a punch's health off on the press frame itself, so the people are judged against the frame
    // before the press (lastFrame), refreshed below after any press is opened.
    if (presses != g.presses) {
        g.pressPending = onFoot && presses > g.presses;
        g.presses = presses;
    }
    if (g.pressPending && fresh) {
        g.pressPending = false;
        {
            g.open = true;
            if (a.weapon == 0) ++g.fistSwings; else ++g.gunSwings;
            g.id = g.fistSwings + g.gunSwings;
            g.weapon = a.weapon;
            g.t0 = clock;
            g.until = clock + (a.weapon == 0 ? 0.6 : 1.2);
            g.ox = a.x; g.oz = a.z; g.heading = a.headingYaw;
            g.hits.clear();
            g.before = g.lastFrame;
            g.aimed = 0;
            g.hadTarget = false;
            const bool fists = a.weapon == 0;
            const float reach = fists ? kFistPick : WeaponReach(a.weapon);
            const float arc = fists ? kFistArcDeg : 20.0f;
            std::string cands;
            float bestOff = 1e9f;
            g.nearD = -1.0f; g.nearOff = 0.0f;
            int listed = 0;
            for (const AimPed& p : peds) {
                if (!g.before.count(p.object)) g.before[p.object] = {p.health, p.corpse};
                const auto& b0 = g.before[p.object];   // as he stood the frame before the press
                if (b0.second || b0.first == 0) continue;
                const float dx = p.x - a.x, dz = p.z - a.z, d = std::hypot(dx, dz);
                if (d > reach + 1.0f) continue;
                const float off = AimDegOff(a.headingYaw, dx, dz);
                const float dy = p.y - a.y;
                if (std::fabs(dy) <= 0.6f && (g.nearD < 0.0f || d < g.nearD)) { g.nearD = d; g.nearOff = off; }
                const char* why = "ok";
                if (std::fabs(dy) > 1.2f) why = "height";
                else if (d > reach) why = "beyond reach";
                else if (std::fabs(off) > arc) why = "outside arc";
                else if (!fists) {
                    const int cov = AimCoverOf(a.x, a.y + 0.30f, a.z, p.x, p.y + 0.25f, p.z);   // FIX-AIM-2: wall vs a lid only
                    if (cov == 2) why = "wall";
                    else if (cov == 1) why = ViewAimCoverWallsOn() ? "ok lid" : "lid";
                }
                if (why[0] == 'o' && why[1] == 'k') {
                    g.hadTarget = true;
                    if (std::fabs(off) < bestOff) { bestOff = std::fabs(off); g.aimed = p.object; }
                }
                if (listed < 8) {
                    char b[96];
                    snprintf(b, sizeof b, " %04x(d=%.2f off=%+.0f dy=%+.2f %s)", static_cast<unsigned>((p.object >> 2) & 0xFFFF), d, off, dy, why);
                    cands += b; ++listed;
                }
            }
            if (fists) g.fistWithTarget += g.hadTarget ? 1 : 0; else g.gunWithTarget += g.hadTarget ? 1 : 0;
            scan();   // the press frame's own drop (a punch lands on it)
            static bool reachLogged = false;
            if (AimLogOn() && !reachLogged) {
                // FUN_00433D00's distance bound for the overlapping victim (16.14 fixed point; read only).
                reachLogged = true;
                int32_t raw = 0;
                GTA2_TRY { raw = *reinterpret_cast<const int32_t*>(static_cast<uintptr_t>(0x005E5D64)); } GTA2_EXCEPT { raw = -1; }
                Log("aim: the game's punch victim distance bound [0x5E5D64] = %d (%.3f blocks)", raw, raw / 16384.0f);
            }
            if (AimLogOn())
                Log("aim: swing %d %s weapon %d %s heading %.0f at %.2f,%.2f highlighted %04x |%s", g.id, fists ? "fists" : "gun", a.weapon,
                    CurrentViewMode() == ViewMode::FirstPerson ? "first" : "third", a.headingYaw * 57.29578f, a.x,
                    static_cast<float>(gta2::kMapHeight) - a.z, static_cast<unsigned>((g_aimHud.targetObject >> 2) & 0xFFFF),
                    cands.empty() ? " nobody within reach+1" : cands.c_str());
        }
    }
    if (fresh) {
        g.lastFrame.clear();
        for (const AimPed& p : peds) g.lastFrame[p.object] = {p.health, p.corpse};
    }
    static double lastTally = 0.0;
    if (g.fistSwings + g.gunSwings > 0 && clock - lastTally >= 10.0) {
        lastTally = clock;
        // owner10nov B9a: the fists' counter on the aim: line's pattern (with_target: a standing person within 1.2
        // blocks and 75 degrees of his facing at the press; contacts: the game took health off or knocked one down).
        if (g.fistSwings > 0)
            Log("melee: swings=%d with_target=%d contacts=%d (%.0f%%) misses: nothing_in_range=%d outside_arc=%d no_contact=%d assist=%d",
                g.fistSwings, g.fistWithTarget, g.fistHits, 100.0 * g.fistHits / g.fistSwings, g.missNobody, g.missArc, g.missNoContact,
                ViewAimAssistOn() ? 1 : 0);
        if (g.gunSwings > 0)
            Log("aim: gun presses=%d with_target=%d hits=%d", g.gunSwings, g.gunWithTarget, g.gunHits);
    }
}

void UpdateAimHud(bool street, float W, float H, float dt) {
    AimHud& h = g_aimHud;
    h.clock += dt;
    const AimState& a = ViewAim();
    const bool fresh = LiveAimPedsFrame() == LiveDrawFrame();
    const std::vector<AimPed>& peds = LiveAimPeds();
    h.show = street && a.valid && a.armed && !ViewPlayer().inVehicle;
    h.fade += ((h.show ? 1.0f : 0.0f) - h.fade) * (1.0f - std::exp(-dt / 0.08f));
    const float hx = std::sin(a.headingYaw), hz = std::cos(a.headingYaw);
    const float ox = a.x, oy = a.y + 0.30f, oz = a.z;
    const float reach = WeaponReach(a.weapon);

    // The target: the nearest person along the line of fire.
    h.target = false;
    if (h.show && fresh) {
        float best = 1e9f;
        for (const AimPed& p : peds) {
            if (p.corpse || p.health == 0) continue;
            const float rx = p.x - ox, rz = p.z - oz;
            const float along = rx * hx + rz * hz;
            if (along < 0.05f || along > reach) continue;   // point-blank counts (run qb6_aim11)
            const float perp = std::fabs(rx * hz - rz * hx);
            // The game's bullets were measured landing up to 0.45 block off the line at 4
            // blocks (run qb6_aim2: the person's own width and the bullet's): the corridor.
            if (perp > 0.32f + 0.03f * along) continue;
            if (std::fabs(p.y - a.y) > 1.2f) continue;
            if (along >= best) continue;
            if (AimCovered(ox, oy, oz, p.x, p.y + 0.25f, p.z)) continue;
            best = along;
            h.target = true;
            h.targetObject = p.object;
            h.tx = p.x; h.ty = p.y; h.tz = p.z;
        }
    }
    // FIX-AIM-1: with the aim assist on, the highlighted person is the one a shot turns him onto (the reticle honest:
    // what it brackets is what the press goes for); the corridor stays the rule with it off.
    if (fresh) {
        const AimPick pick = ComputeAimPick(a, peds);
        ViewSetAimPick(pick.valid && street, a.weapon == 0, pick.bearing, pick.tol, pick.d, pick.object);
        if (h.show && ViewAimAssistOn() && pick.valid) {
            h.target = true;
            h.targetObject = pick.object;
            h.tx = pick.x; h.ty = pick.y; h.tz = pick.z;
        }
    }
    if (!h.target) h.targetObject = 0;
    else { h.lastHighlighted = h.targetObject; h.lastHighlightedAt = h.clock; }   // FIX-AIM-2 (before this frame's shot is judged)

    // A shot: what was highlighted as it left the gun.
    if (a.shots != h.lastShots) {
        if (h.show && a.shots > h.lastShots) {
            const int n = static_cast<int>(a.shots - h.lastShots);
            h.shots += n;
            if (h.target) h.shotsWithTarget += n;
            ClassifyShot(h, a, peds, n);   // FIX-AIM-2
            if (h.target && AimLogOn() && h.followed.size() < 16)
                h.followed.push_back({h.shots, h.targetObject, h.tx, h.tz, hx, hz, std::hypot(h.tx - ox, h.tz - oz), h.clock});
            h.targetAtShot = h.targetObject;
            h.shotTime = h.clock;
            if (h.target) h.recentTargets.push_back({h.targetObject, h.clock});
            h.spread = 1.0f;
        }
        h.lastShots = a.shots;
    }
    h.spread = (std::max)(0.0f, h.spread - dt / 0.25f);
    h.recentTargets.erase(std::remove_if(h.recentTargets.begin(), h.recentTargets.end(),
                                         [&](const std::pair<uintptr_t, double>& t) { return h.clock - t.second > 0.7; }),
                          h.recentTargets.end());

    // Hits, from the people's health words.
    if (fresh) {
        std::unordered_map<uintptr_t, AimHud::Seen> now;
        now.reserve(peds.size());
        for (const AimPed& p : peds) {
            AimHud::Seen& mine = now[p.object];
            mine = {p.health, p.corpse, -1.0};
            const auto it = h.seen.find(p.object);
            if (it == h.seen.end()) continue;
            const AimHud::Seen& was = it->second;
            mine.hitAt = was.hitAt;
            // Down after a hit of ours (the game knocks him down and drains what health he has
            // left four a frame): the kill marker, once, not a hit of its own.
            if (!was.corpse && p.corpse && was.hitAt >= 0.0 && h.clock - was.hitAt < 1.5) {
                ++h.kills;
                h.hitT = 0.45f;
                h.hitKill = true;
                h.pops.push_back({p.x, p.y, p.z, 0.9f, true});
                mine.hitAt = -1.0;
                continue;
            }
            // Only a drop of the health word while he stands: a fall alone is a car or a shove,
            // and the drain of a man already down is not a bullet.
            const bool dropped = !was.corpse && was.health > 0 && p.health >= 0 && p.health < was.health;
            if (!dropped || h.clock - h.shotTime > 1.0) continue;
            const float rx = p.x - ox, rz = p.z - oz;
            const float along = rx * hx + rz * hz;
            const float perp = std::fabs(rx * hz - rz * hx);
            if (along < -0.3f || along > reach + 1.5f || perp > 0.9f + 0.05f * (std::max)(0.0f, along)) continue;
            const bool kill = p.corpse || p.health <= 0;
            mine.hitAt = kill ? -1.0 : h.clock;
            bool highlighted = false;
            for (const auto& t : h.recentTargets) highlighted = highlighted || t.first == p.object;
            ++h.hits;
            for (AimHud::Followed& f : h.followed) { f.anyHit = true; if (f.obj == p.object) f.hit = true; }   // FIX-AIM-2
            h.hitsHighlighted += highlighted ? 1 : 0;
            h.kills += kill ? 1 : 0;
            h.hitT = kill ? 0.45f : 0.25f;
            h.hitKill = kill;
            h.pops.push_back({p.x, p.y, p.z, kill ? 0.9f : 0.6f, kill});
            if (h.hitLogs < 200) {
                ++h.hitLogs;
                Log("aim: hit %04x health %d -> %d%s %.2f s after the shot, %.1f along %.2f off the line, highlighted %d",
                    static_cast<unsigned>((p.object >> 2) & 0xFFFF), was.health, p.health, kill ? " (down)" : "",
                    h.clock - h.shotTime, along, perp, highlighted ? 1 : 0);
            }
        }
        h.seen.swap(now);
    }
    // FIX-AIM-2: the followed targets: his drawn position 0.3 s after the shot (velocity), the outcome at 1.0 s.
    if (fresh) {
        for (AimHud::Followed& f : h.followed) {
            if (f.t1 < 0.0 && h.clock - f.t0 >= 0.3)
                for (const AimPed& p : peds) if (p.object == f.obj) { f.x1 = p.x; f.z1 = p.z; f.t1 = h.clock; }
        }
        for (auto it = h.followed.begin(); it != h.followed.end();) {
            AimHud::Followed& f = *it;
            if (h.clock - f.t0 < 1.0) { ++it; continue; }
            float across = 0.0f, along = 0.0f;
            if (f.t1 > 0.0) {
                const float dt = static_cast<float>(f.t1 - f.t0), vx = (f.x1 - f.x0) / dt, vz = (f.z1 - f.z0) / dt;
                along = vx * f.hx + vz * f.hz; across = vx * f.hz - vz * f.hx;
            }
            const bool moving = std::hypot(across, along) > 0.5f;
            ++h.outShots; h.outHits += f.hit ? 1 : 0; h.outMoving += moving ? 1 : 0; h.outMovingHits += (moving && f.hit) ? 1 : 0;
            Log("aim: shot %d -> %s %04x at %.2f blocks, moving %.2f across %.2f along the line (blocks/s)%s%s", f.shot, f.hit ? "HIT" : "MISS",
                static_cast<unsigned>((f.obj >> 2) & 0xFFFF), f.d0, across, along, f.t1 < 0.0 ? " (lost from view)" : "",
                (!f.hit && f.anyHit) ? " (someone else hit)" : "");
            it = h.followed.erase(it);
        }
    }
    UpdateSwingLog(street, a, peds, fresh, h.clock);   // FIX-AIM-1
    h.hitT = (std::max)(0.0f, h.hitT - dt);
    for (AimHud::Pop& p : h.pops) p.t -= dt;
    h.pops.erase(std::remove_if(h.pops.begin(), h.pops.end(), [](const AimHud::Pop& p) { return p.t <= 0.0f; }), h.pops.end());

    // Where the reticle goes: the target's chest, or where the line meets a wall or ends.
    if (h.show) {
        float wx, wy, wz;
        if (h.target) {
            wx = h.tx; wy = h.ty + 0.28f; wz = h.tz;
        } else {
            float lo = 0.0f, hi = (std::min)(reach, 8.0f);
            // FIX-FIGURE-15 (pfl76): the flamethrower's reticle at the end of its jet (live_geometry FlameJetEmit: the
            // game's flames end ~2.5 blocks out, run over kerbs and lids, stop at a wall). The lid test stopped it 0.6
            // out on the open wil plaza, under the nozzle, so the jet never crossed it.
            const bool flame = a.weapon == 10;
            if (flame) hi = 2.5f;
            auto blocked = [&](float d) {
                return flame ? ViewLineWalled(ox, oy, oz, ox + hx * d, oy, oz + hz * d) : ViewLineBlocked(ox, oy, oz, ox + hx * d, oy, oz + hz * d);
            };
            if (blocked(hi)) {
                for (int i = 0; i < 6; ++i) {
                    const float mid = 0.5f * (lo + hi);
                    if (blocked(mid)) hi = mid; else lo = mid;
                }
                hi = (std::max)(lo, flame ? 0.8f : 0.6f);
            }
            wx = ox + hx * hi; wy = oy; wz = oz + hz * hi;
        }
        // Off the view, the reticle is hidden, never held where it last was nor clamped to an
        // edge (defect pm37: it sat under the minimap while the line ran out of the picture).
        float sx, sy;
        if (!LiveWorldToScreen(wx, wy, wz, &sx, &sy) || sx < 0.03f || sx > 0.97f || sy < 0.03f || sy > 0.97f) {
            h.reticleKnown = false;
        } else {
            sx *= W; sy *= H;
            if (!h.reticleKnown || std::hypot(sx - h.rx, sy - h.ry) > 0.4f * H) { h.rx = sx; h.ry = sy; }
            else {
                const float k = 1.0f - std::exp(-dt / 0.045f);
                h.rx += (sx - h.rx) * k; h.ry += (sy - h.ry) * k;
            }
            h.reticleKnown = true;
        }
        h.bracketHalf = 0.0f;
        float ax, ay, bx, by;
        if (h.target && LiveWorldToScreen(h.tx, h.ty, h.tz, &ax, &ay) && LiveWorldToScreen(h.tx, h.ty + 0.5f, h.tz, &bx, &by))
            h.bracketHalf = (std::min)(0.25f * H, (std::max)(10.0f, 0.5f * std::fabs(ay - by) * H));
        // FIX-HUD-3 (pmx9-bil-third-aim-reticle-drawn-on-hero-back): from the chase camera a wall
        // just ahead of him puts the line's end behind his own back. The figure's box (feet to
        // head, his shoulders' width) is projected; a reticle inside it is not drawn.
        h.retOnHero = false;
        if (h.reticleKnown && CurrentViewMode() == ViewMode::ThirdPerson) {
            float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
            int seen = 0;
            for (int i = 0; i < 8; ++i) {
                float qx, qy;
                // 0.07 block either side: his shoulders measured ~55 px wide on a 190 px figure (0.46 block
                // tall) in fh3_aim1; 0.15 hid a reticle on a man a body's width beside him.
                if (!LiveWorldToScreen(a.x + ((i & 1) ? 0.07f : -0.07f), a.y + ((i & 2) ? 0.50f : 0.0f), a.z + ((i & 4) ? 0.07f : -0.07f), &qx, &qy)) continue;
                ++seen;
                x0 = (std::min)(x0, qx * W); x1 = (std::max)(x1, qx * W);
                y0 = (std::min)(y0, qy * H); y1 = (std::max)(y1, qy * H);
            }
            const float pad = 4.0f * g_u;
            h.retOnHero = seen == 8 && h.rx > x0 - pad && h.rx < x1 + pad && h.ry > y0 - pad && h.ry < y1 + pad;
        }
        ++h.framesArmed;
        h.framesShown += h.reticleKnown ? 1 : 0;
    } else {
        h.reticleKnown = false;
    }

    // The reticle in third person only while he aims: the figure raises the gun for about a second
    // after each shot (live_geometry aimUntil, 30 frames) and carries it at low ready otherwise, so an
    // idle reticle marked a line nothing was aimed along. First person keeps it (the view model aims).
    {
        const bool thirdPerson = CurrentViewMode() == ViewMode::ThirdPerson;
        const bool aiming = !thirdPerson || h.clock - h.shotTime < 1.2;
        const bool want = h.show && h.reticleKnown && aiming && !h.retOnHero;
        // In quickly with a shot; out over a quarter second; off at once when it lands on him.
        if (h.retOnHero) h.retFade = 0.0f;
        else h.retFade += ((want ? 1.0f : 0.0f) - h.retFade) * (1.0f - std::exp(-dt / (want ? 0.04f : 0.12f)));
        static int hiddenIdle = 0, hiddenHero = 0, shownFrames = 0;
        if (h.show && thirdPerson) {
            if (h.retOnHero) ++hiddenHero; else if (!aiming) ++hiddenIdle; else if (h.reticleKnown) ++shownFrames;
        }
        static double lastRetLog = 0.0;
        if (h.clock - lastRetLog >= 5.0 && hiddenIdle + hiddenHero + shownFrames > 0) {
            lastRetLog = h.clock;
            Log("aim: reticle frames (third person, armed) shown=%d hidden_idle=%d hidden_on_hero=%d", shownFrames, hiddenIdle, hiddenHero);
            hiddenIdle = hiddenHero = shownFrames = 0;
        }
    }

    // GTA2DX9_LOG_AIM=1 (scripted probes): three times a second, the nearest person standing
    // in the open within 8 blocks (game coordinates, for a script to turn the player to him),
    // the reticle on screen and whether a target is highlighted.
    static int logAim = -1;
    if (logAim < 0) { char b[4] = {}; logAim = GetEnvironmentVariableA("GTA2DX9_LOG_AIM", b, sizeof b) && b[0] == '1'; }
    static uint32_t aimLogFrame = 0;
    if (logAim && h.show && fresh && ++aimLogFrame % 10 == 0) {
        float best = 64.0f, nx = 0, nz = 0;
        for (const AimPed& p : peds) {
            if (p.corpse || p.health == 0) continue;
            const float d2 = (p.x - ox) * (p.x - ox) + (p.z - oz) * (p.z - oz);
            if (d2 >= best || d2 < 0.3f * 0.3f || std::fabs(p.y - a.y) > 1.2f) continue;
            if (AimCovered(ox, oy, oz, p.x, p.y + 0.25f, p.z)) continue;
            best = d2; nx = p.x; nz = p.z;
        }
        Log("aim: near %s x=%.2f y=%.2f d=%.2f reticle=%.0f,%.0f target=%d",
            best < 64.0f ? "ped" : "none", nx, static_cast<float>(gta2::kMapHeight) - nz, std::sqrt(best), h.rx, h.ry, h.target ? 1 : 0);
    }
    if (h.shots > 0 && h.clock - h.lastLog >= 10.0) {
        h.lastLog = h.clock;
        Log("aim: shots=%d with_target=%d hits=%d on_highlighted=%d (%.0f%%) kills=%d reticle_frames=%d/%d mix=%.2f",
            h.shots, h.shotsWithTarget, h.hits, h.hitsHighlighted, h.hits ? 100.0 * h.hitsHighlighted / h.hits : 0.0,
            h.kills, h.framesShown, h.framesArmed, a.aimMix);
        if (h.outShots > 0)   // FIX-AIM-2: the followed shots' outcome, standing vs moving targets
            Log("aim: followed shots=%d hits=%d | target standing %d hits %d | target moving (>0.5 b/s) %d hits %d", h.outShots, h.outHits,
                h.outShots - h.outMoving, h.outHits - h.outMovingHits, h.outMoving, h.outMovingHits);
        if (h.shots > h.shotsWithTarget)   // FIX-AIM-2: the shots with nothing highlighted, by class
            Log("aim: no_target=%d lost=%d wall=%d lid=%d height=%d range=%d bearing=%d nobody=%d other=%d cover_walls=%d assist=%d",
                h.shots - h.shotsWithTarget, h.ntLost, h.ntWall, h.ntLid, h.ntHeight, h.ntRange, h.ntBearing, h.ntNobody, h.ntOther,
                ViewAimCoverWallsOn() ? 1 : 0, ViewAimAssistOn() ? 1 : 0);
    }
}

void Line2(ImDrawList* dl, ImVec2 a, ImVec2 b, ImU32 col, float w) {
    dl->AddLine(a, b, Fade(kShadow, (float)(col >> IM_COL32_A_SHIFT & 0xFF) / 255.0f * 0.7f), w + 2.0f * g_u);
    dl->AddLine(a, b, col, w);
}

void DrawAimLayer(ImDrawList* dl, float alpha, float W, float H) {
    const AimHud& h = g_aimHud;
    const float A = alpha * h.fade;
    const float u = g_u;
    // The marks on the people hit, in the world: a small red cross rising off a kill.
    for (const AimHud::Pop& p : h.pops) {
        float sx, sy;
        if (!LiveWorldToScreen(p.x, p.y + 0.55f + (p.kill ? 0.25f : 0.1f) * (1.0f - p.t), p.z, &sx, &sy)) continue;
        const ImVec2 c(sx * W, sy * H);
        const float r = (p.kill ? 7.0f : 5.0f) * u;
        const ImU32 col = Fade(p.kill ? kRed : kWhite, alpha * (std::min)(1.0f, p.t * 3.0f));
        Line2(dl, ImVec2(c.x - r, c.y - r), ImVec2(c.x + r, c.y + r), col, 2.5f * u);
        Line2(dl, ImVec2(c.x - r, c.y + r), ImVec2(c.x + r, c.y - r), col, 2.5f * u);
    }
    if (A < 0.02f || !h.reticleKnown) return;
    const float R = A * h.retFade;   // FIX-HUD-3: the reticle aims only (UpdateAimHud)
    if (R < 0.02f) return;
    const ImVec2 c(h.rx, h.ry);
    const ImU32 col = Fade(h.target ? kRed : kWhite, R);
    // Four ticks round a dot, opened by a shot.
    const float gap = (6.0f + 10.0f * h.spread) * u, len = 10.0f * u, w = 3.0f * u;
    Line2(dl, ImVec2(c.x - gap - len, c.y), ImVec2(c.x - gap, c.y), col, w);
    Line2(dl, ImVec2(c.x + gap, c.y), ImVec2(c.x + gap + len, c.y), col, w);
    Line2(dl, ImVec2(c.x, c.y - gap - len), ImVec2(c.x, c.y - gap), col, w);
    Line2(dl, ImVec2(c.x, c.y + gap), ImVec2(c.x, c.y + gap + len), col, w);
    dl->AddCircleFilled(c, 3.4f * u, Fade(kShadow, R * 0.8f));
    dl->AddCircleFilled(c, 2.2f * u, col);
    // The target bracketed.
    if (h.target && h.bracketHalf > 0.0f) {
        float sx, sy;
        if (LiveWorldToScreen(h.tx, h.ty + 0.25f, h.tz, &sx, &sy)) {
            const ImVec2 m(sx * W, sy * H);
            const float bh = h.bracketHalf * 1.15f, bw = h.bracketHalf * 0.75f, k = (std::max)(5.0f * u, bw * 0.4f);
            const ImU32 bc = Fade(kRed, R * 0.9f);
            for (int sxn = -1; sxn <= 1; sxn += 2)
                for (int syn = -1; syn <= 1; syn += 2) {
                    const ImVec2 corner(m.x + sxn * bw, m.y + syn * bh);
                    Line2(dl, corner, ImVec2(corner.x - sxn * k, corner.y), bc, 2.5f * u);
                    Line2(dl, corner, ImVec2(corner.x, corner.y - syn * k), bc, 2.5f * u);
                }
        }
    }
    // The hit marker: an X round the reticle.
    if (h.hitT > 0.0f) {
        const float t = h.hitT / (h.hitKill ? 0.45f : 0.25f);
        const float r0 = (h.hitKill ? 9.0f : 7.0f) * u, r1 = r0 + (h.hitKill ? 14.0f : 10.0f) * u;
        const ImU32 hc = Fade(h.hitKill ? kRed : kWhite, alpha * (std::min)(1.0f, t * 2.0f));
        const float wv = (h.hitKill ? 3.0f : 2.5f) * u;
        for (int sxn = -1; sxn <= 1; sxn += 2)
            for (int syn = -1; syn <= 1; syn += 2)
                Line2(dl, ImVec2(c.x + sxn * r0 * 0.7071f, c.y + syn * r0 * 0.7071f), ImVec2(c.x + sxn * r1 * 0.7071f, c.y + syn * r1 * 0.7071f), hc, wv);
    }
}

// The game's target arrows (its 17 HUD arrow slots), seen through the street view's own
// camera: a filled, shaded pin pointing down at the target with the distance over it when it
// is on screen, a chevron on the screen's edge pointing round the camera toward it when not.
// The game draws these as flat sprites round the player laid out for the top-down camera
// (parts 2 and 13, swallowed in Hud3dSwallow whenever a street view is up); kind 5 is a place
// to go (the job's own and the gang arrows), anything else an object (a phone, a car, a
// person) shown only when it is near.
// BLOCKER-objective-arrow-magenta-outline-on-player: the pin never sits on a wall or on the
// player. When a wall stands between the eye and the spot over the target, the pin is lifted
// over the target until the line clears it (a beacon over the roofs); if no lift up to
// kMarkerLiftMax clears it the target is shown by the edge chevron, as when off screen ("blocked"
// in the log); in third person the pin is pushed above the figure's screen box.
struct MarkerStats {
    int arrows = 0, pins = 0, lifted = 0, blocked = 0, edges = 0;
    bool hit = false; float hitAt[3] = {}, hitFrom[3] = {}, hitTo[3] = {};   // the nearest arrow's first wall sample
};
MarkerStats g_markerStats;
int g_markerSwallowed = 0;   // the game's arrow sprites (parts 2/13) dropped since the last log

ImU32 Shade(ImU32 c, float k) {   // k < 1 darker, k > 1 toward white
    const float r = static_cast<float>((c >> IM_COL32_R_SHIFT) & 0xFF), g = static_cast<float>((c >> IM_COL32_G_SHIFT) & 0xFF),
                b = static_cast<float>((c >> IM_COL32_B_SHIFT) & 0xFF), a = static_cast<float>((c >> IM_COL32_A_SHIFT) & 0xFF);
    auto f = [k](float x) { return static_cast<int>((std::min)(255.0f, k <= 1.0f ? x * k : x + (255.0f - x) * (k - 1.0f))); };
    return IM_COL32(f(r), f(g), f(b), static_cast<int>(a));
}

// A pin with its tip at `tip`, `s` pixels per unit: a head pointing down and a shaft above
// it, the left half lit and the right half in shade, a soft drop shadow behind.
void DrawMarkerPin(ImDrawList* dl, ImVec2 tip, float s, ImU32 col, float a) {
    const float hw = 0.9f * s, hh = 1.0f * s, sw = 0.36f * s, sh = 1.05f * s;
    auto P = [&](float x, float y, float o) { return ImVec2(tip.x + x + o, tip.y + y + o); };
    const float o = (std::max)(1.5f, 0.16f * s);
    const ImVec2 shadowHead[3] = {P(-hw * 1.08f, -hh * 1.04f, o), P(hw * 1.08f, -hh * 1.04f, o), P(0, hh * 0.08f, o)};
    const ImVec2 shadowShaft[4] = {P(-sw * 1.15f, -hh - sh * 1.04f, o), P(sw * 1.15f, -hh - sh * 1.04f, o), P(sw * 1.15f, -hh, o), P(-sw * 1.15f, -hh, o)};
    dl->AddConvexPolyFilled(shadowHead, 3, Fade(kShadow, a * 0.55f));
    dl->AddConvexPolyFilled(shadowShaft, 4, Fade(kShadow, a * 0.55f));
    const ImU32 lit = Fade(Shade(col, 1.35f), a), mid = Fade(col, a), dark = Fade(Shade(col, 0.62f), a);
    const ImVec2 headL[3] = {P(-hw, -hh, 0), P(0, -hh, 0), P(0, 0, 0)};
    const ImVec2 headR[3] = {P(0, -hh, 0), P(hw, -hh, 0), P(0, 0, 0)};
    const ImVec2 shaftL[4] = {P(-sw, -hh - sh, 0), P(0, -hh - sh, 0), P(0, -hh + 0.5f, 0), P(-sw, -hh + 0.5f, 0)};
    const ImVec2 shaftR[4] = {P(0, -hh - sh, 0), P(sw, -hh - sh, 0), P(sw, -hh + 0.5f, 0), P(0, -hh + 0.5f, 0)};
    dl->AddConvexPolyFilled(headL, 3, lit);
    dl->AddConvexPolyFilled(headR, 3, dark);
    dl->AddConvexPolyFilled(shaftL, 4, mid);
    dl->AddConvexPolyFilled(shaftR, 4, dark);
    // A highlight along the head's top edge, so it reads as a solid rather than a cut-out.
    dl->AddLine(P(-hw + 0.5f, -hh + 0.5f, 0), P(hw - 0.5f, -hh + 0.5f, 0), Fade(Shade(col, 1.6f), a * 0.8f), (std::max)(1.0f, 0.1f * s));
}

constexpr float kMarkerLiftMax = 2.0f;   // blocks above a PLACE target the pin may rise to clear a wall; more and it hangs in the sky (pm15-orange-arrowhead-sprites)

// A wall between the eye and a marker's spot: samples every quarter block, leaving out the
// eye's own half block and the last three quarters before the spot (the target's own cell,
// whose building faces may be stored on it).
bool MarkerSightBlocked(const float eye[3], float x, float y, float z, float* hit) {
    const float dx = x - eye[0], dy = y - eye[1], dz = z - eye[2];
    const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
    if (d < 1.3f) return false;
    const int n = (std::min)(480, static_cast<int>(d / 0.25f) + 1);
    for (int i = 1; i < n; ++i) {
        const float t = static_cast<float>(i) / n, along = t * d;
        if (along < 0.5f || d - along < 0.75f) continue;
        const float px = eye[0] + dx * t, py = eye[1] + dy * t, pz = eye[2] + dz * t;
        if (ViewPointWalled(px, py, pz)) {
            if (hit) { hit[0] = px; hit[1] = py; hit[2] = pz; }
            return true;
        }
    }
    return false;
}

void DrawObjectiveMarkers(ImDrawList* dl, const Values& v, float W, float H, float A) {
    if (!g_cfg.markers || v.arrows.empty()) return;
    const float u = g_u;
    const PlayerState& p = ViewPlayer();
    float yawDeg = 0.0f, pitchDeg = 0.0f;
    ViewCameraAngles(&yawDeg, &pitchDeg);
    const float yaw = yawDeg * 3.14159265f / 180.0f;
    float eye[3], eyeDir[3];
    const bool haveEye = MapObjectsEye(eye, eyeDir);
    // The player's figure on screen (third person), so a marker never sits on him.
    float fx0 = 0, fy0 = 0, fx1 = 0, fy1 = 0;
    bool figure = false;
    if (CurrentViewMode() == ViewMode::ThirdPerson) {
        float ax, ay, bx, by;
        const float pz = static_cast<float>(gta2::kMapHeight) - p.y;
        if (LiveWorldToScreen(p.x, p.z, pz, &ax, &ay) && LiveWorldToScreen(p.x, p.z + 0.65f, pz, &bx, &by)) {
            const float h = std::fabs(ay - by) * H, cx = 0.5f * (ax + bx) * W;
            fx0 = cx - 0.45f * h; fx1 = cx + 0.45f * h; fy0 = by * H - 0.15f * h; fy1 = ay * H;
            figure = h > 4.0f;
        }
    }
    const float edge = 34.0f * u;
    const float bob = std::sin(g_anim.time * 3.2f);
    const Arrow* nearestArrow = nullptr;
    const Arrow* nearestPlace = nullptr;   // the one place target that gets an edge chevron when off screen
    {
        float nd = 1e9f;
        for (const Arrow& ar : v.arrows) { const float d = std::hypot(ar.x - v.x, ar.y - v.y); if (d < nd) { nd = d; nearestArrow = &ar; } }
        float npd = 1e9f;
        for (const Arrow& ar : v.arrows) { if (ar.kind != 5) continue; const float d = std::hypot(ar.x - v.x, ar.y - v.y); if (d < npd) { npd = d; nearestPlace = &ar; } }
    }
    for (const Arrow& ar : v.arrows) {
        const bool place = ar.kind == 5;
        const float dist = std::hypot(ar.x - v.x, ar.y - v.y);
        if (!place && dist > 20.0f) continue;
        if (dist < 0.8f) continue;   // standing on it
        ++g_markerStats.arrows;
        const ImU32 col = place ? kYellow : kCyan;
        const float wx = ar.x, wz = static_cast<float>(gta2::kMapHeight) - ar.y;
        float wy = ar.z + (place ? 1.1f : 0.8f);
        // Lift the pin over any wall between the eye and it (lids alone do not count).
        // If none clears it the pin would sit on the wall: the edge chevron shows the way instead.
        // The answer is kept for three frames per target (a far target behind the block costs
        // ten sight lines of up to 480 samples).
        struct Sight { float x = -1, y = -1, lift = 0; bool hidden = false; uint32_t frame = 0; };
        static Sight cache[24];
        Sight* cached = nullptr;
        for (Sight& c : cache) if (c.x == ar.x && c.y == ar.y && g_frame - c.frame < 3) { cached = &c; break; }
        bool hidden = false;
        float hit[3];
        if (cached) {
            wy += cached->lift;
            hidden = cached->hidden;
            if (cached->lift > 0) ++g_markerStats.lifted;
            if (hidden) ++g_markerStats.blocked;
        } else if (haveEye && MarkerSightBlocked(eye, wx, wy, wz, hit)) {
            if (&ar == nearestArrow) {
                g_markerStats.hit = true;
                for (int k = 0; k < 3; ++k) g_markerStats.hitAt[k] = hit[k], g_markerStats.hitFrom[k] = eye[k];
                g_markerStats.hitTo[0] = wx; g_markerStats.hitTo[1] = wy; g_markerStats.hitTo[2] = wz;
            }
            bool clear = false;
            // Only a place marker is lifted (a little); an object pointer (ped, car, phone) behind a wall
            // is simply not shown: lifted object pins scattered orange triangles over walls and sky
            // (pm15-orange-arrowhead-sprites-scatter-across-3d-views).
            if (place) {
                for (float lift = 1.0f; lift <= kMarkerLiftMax + 0.01f; lift += 1.0f) {
                    if (!MarkerSightBlocked(eye, wx, wy + lift, wz, nullptr)) { wy += lift; clear = true; break; }
                }
            }
            if (clear) ++g_markerStats.lifted;
            else { hidden = true; ++g_markerStats.blocked; }
        }
        if (!cached && haveEye) {
            Sight* slot = &cache[0];
            for (Sight& c : cache) if (c.frame < slot->frame) slot = &c;   // the oldest entry
            slot->x = ar.x; slot->y = ar.y; slot->hidden = hidden; slot->frame = g_frame;
            slot->lift = hidden ? 0.0f : wy - (ar.z + (place ? 1.1f : 0.8f));
        }
        float sx, sy;
        const bool proj = !hidden && LiveWorldToScreen(wx, wy, wz, &sx, &sy);
        const bool on = proj && sx > 0.04f && sx < 0.96f && sy > 0.10f && sy < 0.94f;
        if (on) {
            // Bigger when near, never a speck far away.
            const float s = u * (place ? (std::max)(15.0f, (std::min)(24.0f, 24.0f - (dist - 6.0f) * 0.15f))
                                       : (std::max)(10.0f, (std::min)(15.0f, 15.0f - (dist - 4.0f) * 0.25f)));
            ImVec2 tip(sx * W, sy * H + bob * 0.18f * s);
            const float top = tip.y - 2.05f * s;
            if (figure && tip.x + 0.9f * s > fx0 && tip.x - 0.9f * s < fx1 && tip.y > fy0 && top < fy1) tip.y = fy0 - 6.0f * u;
            DrawMarkerPin(dl, tip, s, col, A * 0.95f);
            ++g_markerStats.pins;
            if (place) {
                char t[24];
                snprintf(t, sizeof t, "%.0fm", dist * 2.0f);   // a block is two metres
                const ImVec2 ts = Measure(g_fonts.label, g_fonts.labelPx, t);
                Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(tip.x - ts.x * 0.5f, tip.y - 2.05f * s - 3.0f * u - ts.y), kWhite, t, A * 0.9f);
            }
            continue;
        }
        if (!place) continue;
        // One chevron, for the nearest place: three gang arrows plus the job's at once read as noise
        // on the screen edge (pm15-orange-arrowhead-sprites-scatter-across-3d-views).
        if (&ar != nearestPlace) continue;
        ++g_markerStats.edges;
        // Off screen (or behind the eye): the bearing from the camera's heading, laid on an
        // ellipse inside the screen's edge; ahead is up, behind is down.
        const float dx = wx - p.x, dz = wz - (static_cast<float>(gta2::kMapHeight) - p.y);
        const float fx = std::sin(yaw), fz = std::cos(yaw);
        const float ahead = dx * fx + dz * fz, side = dx * fz - dz * fx;
        const float b = std::atan2(side, ahead);   // 0 ahead, + to the right
        const ImVec2 c(W * 0.5f + std::sin(b) * (W * 0.5f - edge), H * 0.5f - std::cos(b) * (H * 0.5f - edge));
        const float r = 11.0f * u, ca = std::cos(b), sa = std::sin(b);
        auto rot = [&](float x, float y) { return ImVec2(c.x + x * ca - y * sa, c.y + x * sa + y * ca); };
        const ImVec2 sh[3] = {rot(0, -r * 1.15f), rot(r * 0.95f, r * 0.8f), rot(-r * 0.95f, r * 0.8f)};
        dl->AddConvexPolyFilled(sh, 3, Fade(kShadow, A * 0.6f));
        const ImVec2 triL[3] = {rot(0, -r), rot(0, r * 0.35f), rot(-r * 0.8f, r * 0.65f)};
        const ImVec2 triR[3] = {rot(0, -r), rot(r * 0.8f, r * 0.65f), rot(0, r * 0.35f)};
        dl->AddConvexPolyFilled(triL, 3, Fade(Shade(kYellow, 1.3f), A * 0.95f));
        dl->AddConvexPolyFilled(triR, 3, Fade(Shade(kYellow, 0.7f), A * 0.95f));
    }
}

// The letterbox bars' height this frame, pixels (0 without a beat): DrawBeat draws them.
float BeatBarPx(float W, float H) {
    const BeatState& b = Beat();
    if (!g_street || b.kind == BeatKind::None) return 0.0f;
    const float barFull = (std::max)(0.0f, (H - W / 2.39f) * 0.5f);
    return barFull * (1.0f - (1.0f - b.letterbox) * (1.0f - b.letterbox));
}

// FIX-HUD-4 (owner request B12, 10 Nov: "I'd like to have the heart icons back in the top-right
// corner, just like before, to give it a nostalgic feel"): a heart as a vector (the classic parametric curve), GTA2's red with a
// black edge and a light upper-left lobe, at the output resolution.
void HeartShape(ImDrawList* dl, ImVec2 c, float r, ImU32 fill, bool filled) {
    constexpr int kN = 40;
    ImVec2 p[kN];
    for (int i = 0; i < kN; ++i) {
        const float t = i * (6.2831853f / kN);
        const float s = std::sin(t);
        const float x = 16.0f * s * s * s;
        const float y = 13.0f * std::cos(t) - 5.0f * std::cos(2 * t) - 2.0f * std::cos(3 * t) - std::cos(4 * t);
        p[i] = ImVec2(c.x + x * r / 16.0f, c.y - (y + 2.0f) * r / 16.0f);
    }
    // (Top notch, right lobe, tip, left lobe: clockwise on screen, as ImGui's anti-aliased fill wants.)
    ImVec2 sh[kN];
    const float o = (std::max)(1.0f, 1.5f * g_u);
    for (int i = 0; i < kN; ++i) sh[i] = ImVec2(p[i].x + o, p[i].y + o);
    dl->AddConcavePolyFilled(sh, kN, Fade(kShadow, 0.85f));
    if (filled) {
        dl->AddConcavePolyFilled(p, kN, fill);
        // The light lobe: a small soft highlight on the upper left.
        dl->AddCircleFilled(ImVec2(c.x - r * 0.42f, c.y - r * 0.38f), r * 0.22f, Fade(IM_COL32(255, 200, 190, 255), 0.55f), 12);
    } else {
        dl->AddConcavePolyFilled(p, kN, Fade(IM_COL32(40, 20, 22, 255), 0.6f));
    }
    dl->AddPolyline(p, kN, IM_COL32(0, 0, 0, 230), ImDrawFlags_Closed, (std::max)(1.0f, 1.3f * g_u));
}

// The heart's triangles are made once per size (ImGui's concave fill ear-clips: ten of them a frame
// cost ~0.25 ms) and copied each frame, moved, scaled about the centre and faded.
struct HeartMesh { float r = 0; std::vector<ImDrawVert> vtx; std::vector<ImDrawIdx> idx; };
HeartMesh g_heartMesh[2];   // [0] lost, [1] full
void Heart(ImDrawList* dl, ImVec2 c, float r, float grow, float A, bool filled) {
    HeartMesh& m = g_heartMesh[filled ? 1 : 0];
    if (m.r != r || m.vtx.empty()) {
        ImDrawList scratch(dl->_Data);
        scratch._ResetForNewFrame();
        scratch.Flags = dl->Flags;            // anti-aliased fills and lines, as the frame's lists
        scratch._FringeScale = dl->_FringeScale;
        scratch.PushClipRectFullScreen();
        scratch.PushTextureID(dl->_CmdHeader.TextureId);
        HeartShape(&scratch, ImVec2(0, 0), r, kRed, filled);
        m.vtx.assign(scratch.VtxBuffer.Data, scratch.VtxBuffer.Data + scratch.VtxBuffer.Size);
        m.idx.assign(scratch.IdxBuffer.Data, scratch.IdxBuffer.Data + scratch.IdxBuffer.Size);
        m.r = r;
    }
    const int nv = static_cast<int>(m.vtx.size()), ni = static_cast<int>(m.idx.size());
    if (!nv || !ni) return;
    dl->PrimReserve(ni, nv);
    const ImDrawIdx base = static_cast<ImDrawIdx>(dl->_VtxCurrentIdx);
    for (int i = 0; i < nv; ++i) {
        ImDrawVert v = m.vtx[i];
        v.pos = ImVec2(c.x + v.pos.x * grow, c.y + v.pos.y * grow);
        v.col = Fade(v.col, A);
        dl->_VtxWritePtr[i] = v;
    }
    for (int i = 0; i < ni; ++i) dl->_IdxWritePtr[i] = static_cast<ImDrawIdx>(base + m.idx[i]);
    dl->_VtxWritePtr += nv;
    dl->_IdxWritePtr += ni;
    dl->_VtxCurrentIdx += nv;
}

// ---- FIX-HUD-4: the gang respect meters (the game's part 5), top left --------------------
//
// Owner playtest 10 Nov, item 7: "the three bars in the top-left corner appear to have too low a
// resolution relative to the overall look". They were the game's own respect meters (HUD part 5,
// FUN_004C74F0: an emblem sprite and a gradient tube per gang, 77x16 game pixels, scaled 3x at
// 1440p), which the modern HUD left to the game. Now part 5 is swallowed with the modern HUD up
// and each gang's meter is drawn here from the gang pool: the gang's emblem as a vector/type
// glyph, a pill track split at its middle (respect 0) into five bars a side (a bar is 20), the
// fill from the middle out in the gang's colour (darker, with a red cap, to the left: they hate
// you), and three
// pips under it at 0, 2 and 4 bars, the respect the green, yellow and red phones ask for, lit
// once reached.

enum class Emblem { Glyph, Smiley, Flower, Star, Flag, Shield };
struct GangStyle { const char* glyph; ImU32 emblem, bar; Emblem shape; };
GangStyle StyleOf(const Gang& g) {
    std::string n;
    for (const char* c = g.name; *c; ++c) n.push_back(static_cast<char>(tolower(static_cast<unsigned char>(*c))));
    auto has = [&](const char* k) { return n.find(k) != std::string::npos; };
    // The pool's names: "yakuzagang", "zaibatsugang", "looniegang" (Downtown); "krisgang", "zaibgang",
    // "russgang" (Industrial), so four-letter stems.
    if (has("zaib")) return {"Z", IM_COL32(255, 214, 40, 255), IM_COL32(76, 150, 160, 255), Emblem::Glyph};
    if (has("yaku")) return {"\xC2\xA5", IM_COL32(196, 210, 236, 255), IM_COL32(112, 84, 240, 255), Emblem::Glyph};
    if (has("loon")) return {"", IM_COL32(255, 222, 50, 255), IM_COL32(70, 214, 70, 255), Emblem::Smiley};
    // Residential: "redngang", "sciegang", "zaibgang" (the game's emblems: a red flag crossed in blue
    // over a blue bar, a gold striped shield over a yellow one).
    if (has("redn")) return {"", IM_COL32(210, 40, 36, 255), IM_COL32(52, 132, 226, 255), Emblem::Flag};
    if (has("srs") || has("scie")) return {"", IM_COL32(232, 184, 52, 255), IM_COL32(214, 204, 40, 255), Emblem::Shield};
    if (has("kris") || has("hare")) return {"", IM_COL32(255, 150, 40, 255), IM_COL32(236, 136, 36, 255), Emblem::Flower};
    if (has("russ") || has("mafi")) return {"", IM_COL32(226, 44, 40, 255), IM_COL32(200, 44, 44, 255), Emblem::Star};
    // Unknown or unprintable: by the game's colour byte, a neutral emblem.
    static const ImU32 kByColour[8] = {IM_COL32(204, 112, 48, 255), IM_COL32(112, 84, 240, 255), IM_COL32(70, 214, 70, 255),
                                       IM_COL32(76, 150, 160, 255), IM_COL32(200, 48, 48, 255), IM_COL32(240, 140, 40, 255),
                                       IM_COL32(150, 176, 210, 255), IM_COL32(200, 200, 200, 255)};
    const ImU32 c = kByColour[g.colour & 7];
    return {"?", Mix(c, kWhite, 0.4f), c, Emblem::Glyph};
}

void Smiley(ImDrawList* dl, ImVec2 c, float r, ImU32 face, float A) {
    dl->AddCircleFilled(c, r + 1.6f * g_u, Fade(kShadow, A), 32);
    dl->AddCircleFilled(c, r, Fade(face, A), 32);
    dl->AddCircleFilled(ImVec2(c.x - r * 0.35f, c.y - r * 0.28f), r * 0.13f, Fade(IM_COL32(30, 24, 10, 255), A), 12);
    // A wink, as the game's Loonies emblem.
    dl->AddLine(ImVec2(c.x + r * 0.18f, c.y - r * 0.26f), ImVec2(c.x + r * 0.52f, c.y - r * 0.30f), Fade(IM_COL32(30, 24, 10, 255), A), (std::max)(1.0f, r * 0.16f));
    dl->PathArcTo(c, r * 0.58f, 0.35f, 2.79f, 16);
    dl->PathStroke(Fade(IM_COL32(30, 24, 10, 255), A), 0, (std::max)(1.0f, r * 0.17f));
}

// qaf23: the game's collect message (part 9, one sprite word at the top centre: "Health", a weapon's
// name) over a street view was the 1990s red pixel word. Told apart by what just changed: the health
// rose (read live at the part's first frame, and against the last frames) -> ours, a modern chip;
// a weapon or its ammunition gained -> swallowed and drawn as a chip with the game's own words for it.
// FIX-HUD-8 (qar33): the part is classified at its first frame in ANY view (the classic view keeps the
// game's word, but a word collected there and still up after V was 'unknown' in the street view: the
// gain was never seen, the values are read only in the street views), the gains are followed in the
// classic view too, and the weapon chip says what the game's word says: the e.gxt text 'cNN' with NN
// the game's weapon type (c01 "S-Uzi Machine Gun"). The game's last text key, when it is one of the
// collect words c28-c37 (multiplier, life, armour, power-ups), names any other part-9 word the same way.
enum class CollectKind { None, Health, Weapon, Other };
struct Collect { uint32_t frame = 0; CollectKind kind = CollectKind::None; int gain = 0; float alpha = 0.0f; int shown = 0, kept = 0, swallowed = 0;
                 std::string text; uint32_t first = 0; bool logged = false; CollectKind drawn = CollectKind::None; std::string drawnText; };
Collect g_collect;
float g_platesBottom = -1.0f;   // FIX-HUD-8: the top plates' lowest edge (game y of 480), from the overlay's flush
int g_seenHealth = -1, g_seenWeapon = -1, g_seenAmmo = -1;
uint32_t g_healthRiseFrame = 0, g_weaponGainFrame = 0;

// The game's own words for a collect key (e.gxt, Latin-1 to UTF-8, upper case, '*' and '#' dropped).
std::string CollectWords(const char* key) {
    std::u16string t;
    if (!Hud3dGameText(key, &t)) return std::string();
    std::string out;
    for (char16_t c : t) {
        if (c == u'*' || c == u'#') continue;
        if (c >= u'a' && c <= u'z') c = static_cast<char16_t>(c - 32);
        if (c < 0x80) out.push_back(static_cast<char>(c));
        else if (c < 0x100) { out.push_back(static_cast<char>(0xC0 | (c >> 6))); out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
    }
    while (!out.empty() && out.back() == ' ') out.pop_back();
    return out;
}

int g_respectDrawn = 0;
void DrawRespect(ImDrawList* dl, const Values& v, float A) {
    const float u = g_u;
    const float margin = 28.0f * u;
    const float rowH = 30.0f * u, emblemW = 30.0f * u, barW = 150.0f * u, barH = 11.0f * u;
    float y = margin;
    g_respectDrawn = 0;
    for (const Gang& g : v.gangs) {
        if (g_respectDrawn >= 3) break;
        const GangStyle st = StyleOf(g);
        const float cy = y + rowH * 0.5f;
        // The emblem.
        const ImVec2 ec(margin + emblemW * 0.5f, cy);
        if (st.shape == Emblem::Smiley) {
            Smiley(dl, ec, 11.0f * u, st.emblem, A);
        } else if (st.shape == Emblem::Star) {   // the Russians' red star
            Star(dl, ec, 12.5f * u + 1.5f * u, Fade(kShadow, A * 0.8f), Fade(kShadow, A * 0.8f), true);
            Star(dl, ec, 12.5f * u, Fade(st.emblem, A), Fade(IM_COL32(90, 10, 10, 255), A), true);
        } else if (st.shape == Emblem::Flag) {    // the Rednecks' flag: red, crossed in blue
            const float w = 13.0f * u, h = 9.5f * u;
            const ImVec2 fa(ec.x - w, ec.y - h), fb(ec.x + w, ec.y + h);
            dl->AddRectFilled(ImVec2(fa.x + 1.5f * u, fa.y + 1.5f * u), ImVec2(fb.x + 1.5f * u, fb.y + 1.5f * u), Fade(kShadow, A * 0.8f), 1.5f * u);
            dl->AddRectFilled(fa, fb, Fade(st.emblem, A), 1.5f * u);
            dl->PushClipRect(fa, fb, true);
            const ImU32 blue = Fade(IM_COL32(40, 70, 190, 255), A), white = Fade(kWhite, A);
            dl->AddLine(fa, fb, white, 5.2f * u); dl->AddLine(ImVec2(fa.x, fb.y), ImVec2(fb.x, fa.y), white, 5.2f * u);
            dl->AddLine(fa, fb, blue, 3.4f * u); dl->AddLine(ImVec2(fa.x, fb.y), ImVec2(fb.x, fa.y), blue, 3.4f * u);
            dl->PopClipRect();
            dl->AddRect(fa, fb, Fade(IM_COL32(0, 0, 0, 220), A), 1.5f * u, 0, 1.2f * u);
        } else if (st.shape == Emblem::Shield) {  // the Scientists' shield: gold, three bands
            const float w = 10.0f * u, h = 12.0f * u;
            ImVec2 p[6] = {ImVec2(ec.x - w, ec.y - h), ImVec2(ec.x + w, ec.y - h), ImVec2(ec.x + w, ec.y + h * 0.25f),
                           ImVec2(ec.x, ec.y + h), ImVec2(ec.x - w, ec.y + h * 0.25f), ImVec2(ec.x - w, ec.y - h)};
            ImVec2 q[5];
            for (int i = 0; i < 5; ++i) q[i] = ImVec2(p[i].x + 1.5f * u, p[i].y + 1.5f * u);
            dl->AddConvexPolyFilled(q, 5, Fade(kShadow, A * 0.8f));
            dl->AddConvexPolyFilled(p, 5, Fade(st.emblem, A));
            for (int i = 0; i < 3; ++i) {
                const float y = ec.y - h * 0.55f + i * h * 0.42f;
                const float half = w * (i < 2 ? 0.7f : 0.45f);
                dl->AddLine(ImVec2(ec.x - half, y), ImVec2(ec.x + half, y), Fade(IM_COL32(110, 70, 10, 255), A), 1.8f * u);
            }
            dl->AddPolyline(p, 5, Fade(IM_COL32(0, 0, 0, 220), A), ImDrawFlags_Closed, 1.2f * u);
        } else if (st.shape == Emblem::Flower) {  // the Krishnas' flower: eight petals round a dark heart
            const float r = 11.0f * u;
            for (int pass = 0; pass < 2; ++pass)
                for (int i = 0; i < 8; ++i) {
                    const float a = i * 0.7853982f;
                    const ImVec2 pc(ec.x + std::cos(a) * r * 0.58f, ec.y + std::sin(a) * r * 0.58f);
                    if (pass == 0) dl->AddCircleFilled(pc, r * 0.40f + 1.5f * u, Fade(kShadow, A * 0.8f), 14);
                    else dl->AddCircleFilled(pc, r * 0.40f, Fade(i & 1 ? Mix(st.emblem, kWhite, 0.25f) : st.emblem, A), 14);
                }
            dl->AddCircleFilled(ec, r * 0.34f, Fade(IM_COL32(120, 40, 70, 255), A), 14);
        } else {
            const ImVec2 sz = Measure(g_fonts.heavy, g_fonts.heavyPx, st.glyph);
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(ec.x - sz.x * 0.5f, cy - sz.y * 0.5f), st.emblem, st.glyph, A);
        }
        // FIX-HUD-9 (owner 11 Nov, RTX 5090: "the three bars look too modern and don't match the style of the hearts"):
        // the meter in the hearts' language (HeartShape): ten square blocks, five a side of respect 0, each with the
        // hearts' hard black edge and drop shadow, a flat fill in the gang's colour with the hearts' light upper-left
        // highlight, and an unearned block in the lost heart's dark red. No rounded track, no gradient. A block is 20
        // respect (the game's own meter); the block holding the current value fills in proportion. Above zero the blocks
        // fill rightward from the middle, below zero leftward in the gang's colour darkened with a red edge (they hate you).
        const int kCells = 10;
        const float gap = (std::max)(1.0f, 2.0f * u);
        const float cellW = (barW - gap * (kCells - 1)) / kCells, cellH = 13.0f * u;
        const float x0 = margin + emblemW + 8.0f * u, xm = x0 + 5 * (cellW + gap) - gap * 0.5f;
        const float top = cy - cellH * 0.5f, bot = cy + cellH * 0.5f;
        const float edge = (std::max)(1.0f, 1.3f * u), shadow = (std::max)(1.0f, 1.5f * u);
        const float val = (std::max)(-100.0f, (std::min)(100.0f, static_cast<float>(g.respect)));
        const ImU32 lost = IM_COL32(40, 20, 22, 255);
        for (int i = 0; i < kCells; ++i) {
            const float cx0 = x0 + i * (cellW + gap), cx1 = cx0 + cellW;
            // How much of this block the respect covers, 0..1, counted from the middle out.
            float cover = 0.0f;
            const bool right = i >= 5;
            const int k = right ? i - 5 : 4 - i;          // 0 next to the middle
            const float side = right ? val : -val;          // respect toward this side
            if (side > 0.0f) cover = (std::max)(0.0f, (std::min)(1.0f, (side - k * 20.0f) / 20.0f));
            dl->AddRectFilled(ImVec2(cx0 + shadow, top + shadow), ImVec2(cx1 + shadow, bot + shadow), Fade(kShadow, A * 0.85f));
            // Unearned: the gang's colour dimmed (as an empty heart reads against the street), so the meter shows at respect 0.
            dl->AddRectFilled(ImVec2(cx0, top), ImVec2(cx1, bot), Fade(Mix(st.bar, IM_COL32(0, 0, 0, 255), 0.62f), A * 0.95f));
            if (cover > 0.0f) {
                const ImU32 col = right ? st.bar : Mix(st.bar, IM_COL32(0, 0, 0, 255), 0.45f);
                // Fill from the middle side of the block.
                const float fx0 = right ? cx0 : cx1 - cellW * cover, fx1 = right ? cx0 + cellW * cover : cx1;
                dl->AddRectFilled(ImVec2(fx0, top), ImVec2(fx1, bot), Fade(col, A));
                if (cover >= 0.999f)   // the hearts' light lobe, a small highlight in the upper left
                    dl->AddRectFilled(ImVec2(cx0 + cellW * 0.16f, top + cellH * 0.18f), ImVec2(cx0 + cellW * 0.42f, top + cellH * 0.40f),
                                      Fade(IM_COL32(255, 255, 255, 255), A * 0.45f));
            }
            dl->AddRect(ImVec2(cx0, top), ImVec2(cx1, bot), Fade(right || val >= 0 ? IM_COL32(0, 0, 0, 230) : (cover > 0 ? kRed : IM_COL32(0, 0, 0, 230)), A),
                        0.0f, 0, edge);
        }
        // Respect 0: a short white tick between the halves.
        dl->AddLine(ImVec2(xm, top - 3.0f * u), ImVec2(xm, bot + 3.0f * u), Fade(kWhite, A * 0.85f), (std::max)(1.0f, 1.6f * u));
        // The phones' tiers under the meter (0, 2 and 4 blocks: green, yellow, red jobs), as small black-edged squares.
        static const ImU32 kTier[3] = {IM_COL32(92, 220, 96, 255), IM_COL32(255, 196, 40, 255), IM_COL32(240, 64, 52, 255)};
        for (int t = 0; t < 3; ++t) {
            const float x = xm + (t * 2) * (cellW + gap);
            const bool lit = g.respect >= t * 40;
            const float h = 2.6f * u;
            const ImVec2 q0(x - h, bot + 3.5f * u), q1(x + h, bot + 3.5f * u + 2 * h);
            dl->AddRectFilled(ImVec2(q0.x + shadow, q0.y + shadow), ImVec2(q1.x + shadow, q1.y + shadow), Fade(kShadow, A * 0.8f));
            dl->AddRectFilled(q0, q1, Fade(lit ? kTier[t] : lost, A * (lit ? 1.0f : 0.6f)));
            dl->AddRect(q0, q1, Fade(IM_COL32(0, 0, 0, 230), A), 0.0f, 0, edge);
        }
        y += rowH;
        ++g_respectDrawn;
    }
}

void Draw(ImDrawList* dl, IDirect3DDevice9* device, const Values& v, float W, float H, float dt) {
    // FIX-HUD-3 (pmq10, pm10): what the panels draw from here on is moved inside the letterbox
    // picture below while the bars slide in (the money and stars half under the top bar, the
    // mini-map under the bottom one, as they faded). The aim layer above follows the world.
    Anim& an = g_anim;
    const float A = an.fade;
    const float u = g_u;
    const float margin = 28.0f * u;
    DrawAimLayer(dl, A, W, H);   // QB-6
    const int panelVtx0 = dl->VtxBuffer.Size, panelCmd0 = dl->CmdBuffer.Size;
    {
        LARGE_INTEGER q0, q1;
        QueryPerformanceCounter(&q0);
        DrawRespect(dl, v, A);   // FIX-HUD-4: the game's part 5, redrawn
        QueryPerformanceCounter(&q1);
        g_mapStats.respectTicks += q1.QuadPart - q0.QuadPart;
    }

    // Money, ticking up (or down) to the game's value; the gain pops above it.
    if (v.money >= 0) {
        if (an.money < 0) an.money = v.money;
        if (an.lastMoney >= 0 && v.money > an.lastMoney) { an.gainAmount = v.money - an.lastMoney; an.gain = 2.0f; }
        an.lastMoney = v.money;
        const double diff = v.money - an.money;
        const double step = (std::max)(std::fabs(diff) * (1.0 - std::exp(-dt * 5.0)), 40.0 * dt);
        an.money = std::fabs(diff) <= step ? v.money : an.money + (diff > 0 ? step : -step);
    }
    float y = margin;
    const float right = W - margin;
    if (v.money >= 0 && GlyphsOn()) {
        // FIX-HUD-5: the game's own gold money digits and its '$', thousands parted by a thin gap.
        std::string m = Thousands(static_cast<long long>(std::llround(an.money)));
        const ImVec2 sz = GlyphMeasure(GameGlyphSet::Money, m.c_str(), 1.0f);
        GlyphText(dl, GameGlyphSet::Money, ImVec2(right - sz.x, y), m.c_str(), A, 1.0f);
        if (an.gain > 0) {
            // the gain pops left of it in the game's font 1 (gold), its '+' drawn in that gold
            char g[32];
            snprintf(g, sizeof g, "%s", Thousands(an.gainAmount).c_str());
            const ImVec2 gs = GlyphMeasure(GameGlyphSet::Pop, g, -1.0f);
            const float t = an.gain / 2.0f;
            const float ga = A * (std::min)(1.0f, t * 2.0f);
            const float k = static_cast<float>(g_glyphs.k[static_cast<int>(GameGlyphSet::Pop)]);
            const float gx = std::floor(right - sz.x - gs.x - 20 * u), gy = std::floor(y + (sz.y - gs.y) * 0.5f - (1 - t) * 16 * u);
            GlyphText(dl, GameGlyphSet::Pop, ImVec2(gx, gy), g, ga, -1.0f);
            const float pc = std::floor(gx - 7 * k), pm = std::floor(gy + gs.y * 0.5f);
            const ImU32 gold = Fade(IM_COL32(233, 194, 64, 255), ga), edge = Fade(IM_COL32(40, 30, 8, 255), ga);
            dl->AddRectFilled(ImVec2(pc - 5.0f * k, pm - 1.5f * k), ImVec2(pc + 5.0f * k, pm + 1.5f * k), edge);
            dl->AddRectFilled(ImVec2(pc - 1.5f * k, pm - 5.0f * k), ImVec2(pc + 1.5f * k, pm + 5.0f * k), edge);
            dl->AddRectFilled(ImVec2(pc - 4.0f * k, pm - 0.5f * k), ImVec2(pc + 4.0f * k, pm + 0.5f * k), gold);
            dl->AddRectFilled(ImVec2(pc - 0.5f * k, pm - 4.0f * k), ImVec2(pc + 0.5f * k, pm + 4.0f * k), gold);
            an.gain -= dt;
        }
        y += sz.y + 4 * u;
    } else if (v.money >= 0) {
        const std::string m = Thousands(static_cast<long long>(std::llround(an.money)));
        const ImVec2 sz = Measure(g_fonts.money, g_fonts.moneyPx, m.c_str());
        const bool ticking = std::llround(an.money) != v.money;
        Text(dl, g_fonts.money, g_fonts.moneyPx, ImVec2(right - sz.x, y), ticking ? Mix(kWhite, kYellow, 0.6f) : kWhite, m.c_str(), A);
        if (an.gain > 0) {
            char g[32];
            snprintf(g, sizeof g, "+%s", Thousands(an.gainAmount).c_str());
            const ImVec2 gs = Measure(g_fonts.heavy, g_fonts.heavyPx, g);
            const float t = an.gain / 2.0f;
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(right - sz.x - gs.x - 14 * u, y + (sz.y - gs.y) * 0.5f - (1 - t) * 16 * u),
                 kYellow, g, A * (std::min)(1.0f, t * 2.0f));
            an.gain -= dt;
        }
        y += sz.y - 2 * u;
    }

    // Multiplier and lives on one line under it.
    if (GlyphsOn()) {
        // FIX-HUD-5: as the game draws them, a red x and digits for the multiplier, a green x and
        // digits for the lives (its two lines left of the money), here on one line right-aligned.
        char line[32];
        float x = right;
        float lineH = 0;
        if (v.lives >= 0) {
            snprintf(line, sizeof line, "x%d", v.lives);
            const ImVec2 s = GlyphMeasure(GameGlyphSet::Lives, line, 2.0f);
            x -= s.x;
            GlyphText(dl, GameGlyphSet::Lives, ImVec2(x, y), line, A, 2.0f);
            x -= 12 * u;
            lineH = (std::max)(lineH, s.y);
        }
        if (v.mult >= 0) {
            snprintf(line, sizeof line, "x%d", v.mult);
            const ImVec2 s = GlyphMeasure(GameGlyphSet::Mult, line, 2.0f);
            x -= s.x;
            GlyphText(dl, GameGlyphSet::Mult, ImVec2(x, y), line, A, 2.0f);
            lineH = (std::max)(lineH, s.y);
        }
        y += lineH + 8 * u;
    } else {
        char line[64];
        float x = right;
        if (v.lives >= 0) {
            snprintf(line, sizeof line, "%d", v.lives);
            const ImVec2 s = Measure(g_fonts.heavy, g_fonts.heavyPx, line);
            x -= s.x;
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(x, y), kWhite, line, A);
            const ImVec2 ls = Measure(g_fonts.label, g_fonts.labelPx, "LIVES");
            x -= ls.x + 5 * u;
            Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(x, y + (s.y - ls.y) * 0.6f), Fade(kWhite, 0.75f), "LIVES", A);
            x -= 16 * u;
        }
        if (v.mult >= 0) {
            snprintf(line, sizeof line, "x%d", v.mult);
            const ImVec2 s = Measure(g_fonts.heavy, g_fonts.heavyPx, line);
            x -= s.x + 12 * u;
            dl->AddRectFilled(ImVec2(x, y + 3 * u), ImVec2(x + s.x + 12 * u, y + s.y - 1 * u), Fade(kYellow, A * 0.95f), 4 * u);
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(x + 6 * u, y), IM_COL32(20, 20, 24, 255), line, A, false);
        }
        y += g_fonts.heavyPx + 8 * u;
    }

    // FIX-HUD-4 (owner request B12): the game's hearts, right-aligned under that line. They are the
    // player's health, as the game counts them (measured in out/fh4_h1 with the game's HUD in a street
    // view: health 100 -> 5 hearts, 75 -> 4, 35 -> 2: one a started 20), lost ones a dim outline; at 30 or
    // less the last one beats (a hit flashes the health bar under the map).
    if (v.health >= 0 && g_cfg.hearts && GlyphsOn() && Glyph(GameGlyphSet::Heart, 'H')) {
        // FIX-HUD-5: the game's own heart sprite; lost ones as its dark silhouette; at 30 or less
        // the last one blinks (whole pixels: a size pulse would resample it).
        const int full = (std::max)(0, (std::min)(5, (v.health + 19) / 20));
        const BakedGlyph* hb = Glyph(GameGlyphSet::Heart, 'H');
        const float step = hb->w + 3.0f * g_glyphs.k[static_cast<int>(GameGlyphSet::Heart)];
        const bool low = v.health <= 30;
        const float beat = low ? 0.5f + 0.5f * std::sin(an.time * 7.0f) : 0.0f;
        for (int i = 0; i < 5; ++i) {
            const int slot = 4 - i;
            const bool on = slot < full;
            const bool last = on && slot == full - 1;
            const ImVec2 at(right - hb->w - i * step, y);
            if (on) GlyphText(dl, GameGlyphSet::Heart, at, "H", A * (last && low ? 0.45f + 0.55f * (1.0f - beat) : 1.0f), 0.0f);
            else GlyphText(dl, GameGlyphSet::Heart, at, "H", A * 0.45f, 0.0f, false, IM_COL32(24, 12, 12, 255));
        }
        y += hb->h + 8 * u;
    } else if (v.health >= 0 && g_cfg.hearts) {
        const int full = (std::max)(0, (std::min)(5, (v.health + 19) / 20));
        const float r = 11.0f * u, step = 2.3f * r;
        const float cy = y + r;
        const bool low = v.health <= 30;
        const float beat = low ? 0.5f + 0.5f * std::sin(an.time * 7.0f) : 0.0f;
        for (int i = 0; i < 5; ++i) {
            const int slot = 4 - i;   // drawn right to left; slot 0 is the leftmost
            const ImVec2 c(right - r - i * step, cy);
            const bool on = slot < full;
            const bool last = on && slot == full - 1;
            const float grow = last && low ? 1.0f + 0.12f * beat : 1.0f;
            Heart(dl, c, r, grow, A, on);
        }
        y += r * 2 + 8 * u;
    }

    // Wanted: six stars, the earned ones filled and pulsing.
    if (v.wanted > 0) {
        const float r = 11.0f * u;
        const float pulse = 0.5f + 0.5f * std::sin(an.time * 6.0f);
        for (int i = 0; i < 6; ++i) {
            const ImVec2 c(right - r - i * (r * 2.3f), y + r);
            const bool on = (5 - i) < v.wanted;
            const float grow = on ? 1.0f + 0.10f * pulse : 1.0f;
            const ImU32 fill = Mix(kYellow, kWhite, on ? pulse * 0.5f : 0.0f);
            Star(dl, c, r * grow + 1.2f * u, Fade(kShadow, A * 0.6f), Fade(kShadow, A * 0.8f), on);
            Star(dl, c, r * grow, Fade(fill, A), Fade(on ? kYellow : kWhite, A * (on ? 1.0f : 0.45f)), on);
        }
        y += r * 2 + 10 * u;
    }

    // The weapon: the game's own icon, its ammunition and name, right-aligned under the lives
    // in the same shadowed type as the money and lives, with no card behind it (a glass card
    // here read as a dirty patch on the facade behind, pm9-third-ammo-panel-translucent-box-bleeds-into-scene).
    // FIX-HUD-6 (qaf2): in a car with a gun (the kill frenzy's tank) the car's weapon, as classic's part 1.
    if (v.weapon > 0 || v.carWeapon >= 0) {
        const float h = 54.0f * u;
        char ammo[24];
        // -1 is a kill frenzy's weapon (the game sets its slot's ammunition to -1): classic writes K.F.
        if (v.ammo < 0) snprintf(ammo, sizeof ammo, "K.F.");
        else snprintf(ammo, sizeof ammo, "%d", (v.ammo + 9) / 10);
        // FIX-HUD-7 (qaf90): the number only when the game writes one (its part 1 drew a font cell lately);
        // while part 1 is not seen at all, as before.
        if (g_partSeen[1] + 2 >= g_frame && g_gameAmmoFrame + 3 < g_frame) ammo[0] = 0;
        std::string name = v.carWeapon >= 0 ? CarWeaponName(v.carWeapon) : WeaponName(v.weapon);
        for (char& c : name) c = c == '_' ? ' ' : static_cast<char>(toupper(static_cast<unsigned char>(c)));
        ImVec2 as, ns;
        if (GlyphsOn()) {
            // FIX-HUD-5: the ammunition in the game's font 1, grey as it draws it (red when low), the
            // weapon's name in the same font's gold
            const GameGlyphSet aset = v.ammo >= 0 && v.ammo < 50 ? GameGlyphSet::AmmoLow : GameGlyphSet::Ammo;
            as = GlyphMeasure(aset, ammo, 0.0f);
            ns = GlyphMeasure(GameGlyphSet::Label, name.c_str(), 0.0f);
            GlyphText(dl, aset, ImVec2(right - as.x, y), ammo, A, 0.0f);
            GlyphText(dl, GameGlyphSet::Label, ImVec2(right - ns.x, y + h - ns.y), name.c_str(), A * 0.9f, 0.0f);
        } else {
            as = Measure(g_fonts.heavy, g_fonts.heavyPx, ammo);
            ns = Measure(g_fonts.label, g_fonts.labelPx, name.c_str());
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(right - as.x, y), v.ammo >= 0 && v.ammo < 50 ? kRed : kWhite, ammo, A);
            Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(right - ns.x, y + h - ns.y - 2 * u), Fade(kWhite, 0.8f), name.c_str(), A);
        }
        const bool icon = g_weaponIcon.frame + 1 >= g_frame && g_weaponIcon.texture;
        if (icon) {
            const float iw = g_weaponIcon.maxX - g_weaponIcon.minX, ih = g_weaponIcon.maxY - g_weaponIcon.minY;
            const float fit = (std::min)((h - 6 * u) / ih, 96.0f * u / iw);
            const float textW = (std::max)(as.x, ns.x);
            const ImVec2 ia(right - textW - 12 * u - iw * fit, y + (h - ih * fit) * 0.5f);
            const ImVec2 ib(ia.x + iw * fit, ia.y + ih * fit);
            // the same drop shadow as the type: the icon's silhouette, dark, offset down-right
            const float o = (std::max)(1.0f, std::round(2.0f * u));
            DrawCapture(dl, device, g_weaponIcon, ImVec2(ia.x + o, ia.y + o), ImVec2(ib.x + o, ib.y + o), A * 0.55f, IM_COL32(0, 0, 0, 255));
            DrawCapture(dl, device, g_weaponIcon, ia, ib, A);
        }
        y += h + 10 * u;
    }

    // The clock and the counter, top centre.
    // FIX-HUD-7: the digits in the game's own LCD cells (part 11's green panel: user 123-132, the unlit cell
    // 122, the colon 121/120 blinking as classic's does), on a plate of the cells' own green; Barlow when the
    // style has no such cells (game_font=0, another style).
    {
        const bool lcd = GlyphsOn() && Glyph(GameGlyphSet::Lcd, '0') && Glyph(GameGlyphSet::Lcd, ':') && Glyph(GameGlyphSet::Lcd, '#');
        const float lk = static_cast<float>(g_glyphs.k[static_cast<int>(GameGlyphSet::Lcd)]);
        ImU32 plate = IM_COL32(0, 0, 0, 255);
        if (lcd) {
            if (const GameGlyph* blank = HudGameGlyph(GameGlyphSet::Lcd, '#')) {
                // the plate between the cells: the blank cell's mean colour (the game's plate, user 119, is the same green)
                double sum[3] = {0, 0, 0};
                for (uint32_t c : blank->argb) { sum[0] += (c >> 16) & 0xFF; sum[1] += (c >> 8) & 0xFF; sum[2] += c & 0xFF; }
                const double n = blank->argb.empty() ? 1.0 : static_cast<double>(blank->argb.size());
                auto lin = [&](double x) { return static_cast<int>(std::lround(255.0 * std::pow(x / n / 255.0, 1.0 / 2.2))); };
                plate = IM_COL32(lin(sum[0]), lin(sum[1]), lin(sum[2]), 255);   // the HUD's vertex colours reach the screen squared
            }
        }
        // An LCD strip: the cells a game pixel apart (classic's 7-pixel pitch), on the plate one game pixel
        // wider all round; returns its size.
        auto lcdMeasure = [&](const char* t) {
            const ImVec2 m = GlyphMeasure(GameGlyphSet::Lcd, t, 1.0f);
            return ImVec2(m.x + 2 * lk, m.y + 2 * lk);
        };
        auto lcdDraw = [&](ImVec2 at, const char* t) {
            const ImVec2 m = lcdMeasure(t);
            const ImVec2 p0(std::floor(at.x + 0.5f), std::floor(at.y + 0.5f));
            dl->AddRectFilled(ImVec2(p0.x + lk, p0.y + lk), ImVec2(p0.x + m.x + lk, p0.y + m.y + lk), IM_COL32(0, 0, 0, static_cast<int>(110 * A)));
            dl->AddRectFilled(p0, ImVec2(p0.x + m.x, p0.y + m.y), Fade(plate, A));
            GlyphText(dl, GameGlyphSet::Lcd, ImVec2(p0.x + lk, p0.y + lk), t, A, 1.0f, false);
        };
        float cy = margin;
        if (v.timerTicks >= 0) {
            const int secs = (v.timerTicks + 29) / 30;
            char t[16];
            // "00:58" as classic's panel; the colon blinks as the game's does (121 lit, 120 dark), half a second each
            snprintf(t, sizeof t, lcd ? "%02d%c%02d" : "%d%c%02d", secs / 60, !lcd || std::fmod(an.time, 1.0f) < 0.5f ? ':' : '.', secs % 60);
            const ImVec2 s = lcd ? lcdMeasure(t) : Measure(g_fonts.money, g_fonts.moneyPx * 0.85f, t);
            const float w = s.x + 60 * u, h = s.y + 8 * u;
            const ImVec2 a(W * 0.5f - w * 0.5f, cy), b(W * 0.5f + w * 0.5f, cy + h);
            const bool urgent = secs <= 10;
            const float blink = urgent ? 0.5f + 0.5f * std::sin(an.time * 10.0f) : 0.0f;
            Panel(dl, a, b, A);
            dl->AddRect(a, b, Fade(urgent ? kRed : kCyan, A * (0.6f + 0.4f * blink)), 6 * u, 0, 2 * u);
            // a clock face
            const ImVec2 c(a.x + 24 * u, (a.y + b.y) * 0.5f);
            dl->AddCircle(c, 10 * u, Fade(kWhite, A), 20, 2 * u);
            const float hand = an.time * 6.2831853f / 2.0f;
            dl->AddLine(c, ImVec2(c.x + std::sin(hand) * 7 * u, c.y - std::cos(hand) * 7 * u), Fade(kWhite, A), 2 * u);
            if (lcd) lcdDraw(ImVec2(a.x + 44 * u, a.y + 4 * u), t);
            else Text(dl, g_fonts.money, g_fonts.moneyPx * 0.85f, ImVec2(a.x + 44 * u, a.y + 4 * u), urgent ? Mix(kWhite, kRed, blink) : kWhite, t, A);
            cy = b.y + 8 * u;
        }
        if (v.counter >= 0) {
            char t[24];
            // two cells at least, the leading one unlit, as classic's panel ("#5")
            if (lcd && v.counter < 10) snprintf(t, sizeof t, "#%d", v.counter);
            else snprintf(t, sizeof t, "%d", v.counter);
            // FIX-HUD-7: a counter in the clock's own slot is a kill frenzy's kills still needed
            const char* label = v.counterSlot >= 0 && v.counterSlot == v.clockSlot ? "KILLS" : "COUNT";
            const ImVec2 s = lcd ? lcdMeasure(t) : Measure(g_fonts.heavy, g_fonts.heavyPx, t);
            const ImVec2 ls = Measure(g_fonts.label, g_fonts.labelPx, label);
            const float w = s.x + ls.x + 34 * u, h = s.y + 6 * u;
            const ImVec2 a(W * 0.5f - w * 0.5f, cy), b(W * 0.5f + w * 0.5f, cy + h);
            Panel(dl, a, b, A, kYellow);
            Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(a.x + 14 * u, a.y + (h - ls.y) * 0.5f), Fade(kWhite, 0.75f), label, A);
            if (lcd) lcdDraw(ImVec2(b.x - 10 * u - s.x, a.y + 3 * u), t);
            else Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(b.x - 10 * u - s.x, a.y + 3 * u), kWhite, t, A);
        }
    }

    // The mini-map, bottom left, turned with the camera; health (and the car) under it.
    // FIX-HUD-4: a disc (owner, 10 Nov: "change its shape from square to circular"), drawn as
    // vectors (DrawMapDisc); the same pixels a block as the old 260-wide square.
    const float mapD = 200.0f * u;
    const float mapW = mapD, mapH = mapD;
    const float barH = 8.0f * u;
    // While the game draws its own talking head and subtitle (part 10, bottom left, when the
    // brief's text is not ours to show) the map and the bar under it slide up out of its band
    // (pm-hud-minimap-covers-subtitle-and-portrait: the panel ate the first word and the portrait).
    const bool gameBrief = !g_briefResolved && g_partSeen[10] + 2 >= g_frame;
    float wantLift = 0.0f;
    if (gameBrief) {
        // At least two lines' worth; more when the game's block is taller (a four-line brief
        // starts higher: its first word sat behind the map, pm21).
        wantLift = 84.0f * u;
        if (g_part10Frame + 2 >= g_frame && g_part10MinY < 1e8f) {
            const float blockTop = g_part10MinY * (H / 480.0f);
            const float mapBottom = H - margin;   // the bar under the map
            wantLift = (std::max)(wantLift, mapBottom - blockTop + 10.0f * u);
        }
    }
    an.lift += (wantLift - an.lift) * (1.0f - std::exp(-dt * 10.0f));
    const float lift = an.lift;
    const ImVec2 m0(margin, H - margin - barH - 8 * u - mapH - lift), m1(margin + mapW, H - margin - barH - 8 * u - lift);
    float yaw = 0, pitch = 0;
    ViewCameraAngles(&yaw, &pitch);
    const float yr = yaw * 0.017453293f;
    const float cs = std::cos(yr), sn = std::sin(yr);
    // game offset -> map screen offset: right = (cos, sin), forward = (sin, -cos)
    const ImVec2 mc((m0.x + m1.x) * 0.5f, (m0.y + m1.y) * 0.5f);   // the disc's centre
    const float R = mapD * 0.5f;
    // The player a little below the centre: more of the street ahead.
    const ImVec2 pc(mc.x, mc.y + R * 0.18f);
    const float wantZoom = v.inVehicle ? 64.0f : 34.0f;
    an.zoom += (wantZoom - an.zoom) * (1.0f - std::exp(-dt * 1.5f));
    const float scale = 260.0f * u / an.zoom;   // pixels per block (as the old 260-wide square)
    auto toScreen = [&](float gx, float gy) {
        const float dx = gx - v.x, dy = gy - v.y;
        const float r = dx * cs + dy * sn, f = dx * sn - dy * cs;
        return ImVec2(pc.x + r * scale, pc.y - f * scale);
    };
    if (g_cfg.minimap) {
        // A soft shadow round the disc, then the map, then a thin rim.
        dl->AddCircleFilled(ImVec2(mc.x, mc.y + 2 * u), R + 4 * u, Fade(IM_COL32(0, 0, 0, 120), A), 96);
        LARGE_INTEGER q0, q1;
        QueryPerformanceCounter(&q0);
        const MapDrawStats ms = DrawMapDisc(dl, mc, R, pc, v.x, v.y, cs, sn, scale, A);
        QueryPerformanceCounter(&q1);
        g_mapStats.ticks += q1.QuadPart - q0.QuadPart;
        g_mapStats.rects += ms.rects; g_mapStats.clipped += ms.clipped; ++g_mapStats.frames;
        // Blips: phones small and cyan, the job's own arrows yellow and larger; off the map
        // they sit on its rim as a chevron.
        const float inner = R - 10 * u;
        for (const Arrow& ar : v.arrows) {
            const bool phone = ar.type >= 1 && ar.type <= 4;
            ImVec2 p = toScreen(ar.x, ar.y);
            float dx = p.x - mc.x, dy = p.y - mc.y;
            const float d = std::sqrt(dx * dx + dy * dy);
            const bool off = d > inner;
            if (off && phone) continue;
            if (off) {
                // Along the line from the player to the target, where it leaves the disc.
                float ux = p.x - pc.x, uy = p.y - pc.y;
                const float ul = std::sqrt(ux * ux + uy * uy) + 1e-4f;
                ux /= ul; uy /= ul;
                const float ox = pc.x - mc.x, oy = pc.y - mc.y;
                const float bq = ox * ux + oy * uy, cq = ox * ox + oy * oy - inner * inner;
                const float t = -bq + std::sqrt((std::max)(0.0f, bq * bq - cq));
                p = ImVec2(pc.x + ux * t, pc.y + uy * t);
                const float ang = std::atan2(uy, ux);
                const float r = 9 * u;
                const ImVec2 t0(p.x + std::cos(ang) * r, p.y + std::sin(ang) * r);
                const ImVec2 t1(p.x + std::cos(ang + 2.4f) * r, p.y + std::sin(ang + 2.4f) * r);
                const ImVec2 t2(p.x + std::cos(ang - 2.4f) * r, p.y + std::sin(ang - 2.4f) * r);
                dl->AddTriangleFilled(t0, t1, t2, Fade(kYellow, A));
                dl->AddTriangle(t0, t1, t2, Fade(kShadow, A * 0.8f), 1.0f * u);
                continue;
            }
            const float r = (phone ? 4.0f : 6.5f) * u;
            dl->AddCircleFilled(p, r + 1.5f * u, Fade(kShadow, A));
            dl->AddCircleFilled(p, r, Fade(phone ? kCyan : kYellow, A));
            if (!phone) {
                const float ring = r + (3.0f + 4.0f * std::fmod(an.time, 1.0f)) * u;
                if (d + ring < R) dl->AddCircle(p, ring, Fade(kYellow, A * (1.0f - std::fmod(an.time, 1.0f))), 24, 1.5f * u);
            }
        }
        // The player: an arrow along his heading, as the camera sees it.
        const float heading = std::atan2(v.dirX, -v.dirY);
        const float a = heading - yr;
        const float r = 9.0f * u;
        const ImVec2 fwd(std::sin(a), -std::cos(a)), side(std::cos(a), std::sin(a));
        const ImVec2 tip(pc.x + fwd.x * r, pc.y + fwd.y * r);
        const ImVec2 l(pc.x - fwd.x * r * 0.7f - side.x * r * 0.75f, pc.y - fwd.y * r * 0.7f - side.y * r * 0.75f);
        const ImVec2 rr(pc.x - fwd.x * r * 0.7f + side.x * r * 0.75f, pc.y - fwd.y * r * 0.7f + side.y * r * 0.75f);
        const ImVec2 back(pc.x - fwd.x * r * 0.3f, pc.y - fwd.y * r * 0.3f);
        const ImVec2 arrow[4] = {tip, rr, back, l};
        dl->AddPolyline(arrow, 4, Fade(kShadow, A), ImDrawFlags_Closed, 2.4f * u);
        dl->AddTriangleFilled(tip, l, back, Fade(kWhite, A));
        dl->AddTriangleFilled(tip, back, rr, Fade(kWhite, A));
        // The rim, then north on it.
        dl->AddCircle(mc, R, Fade(IM_COL32(0, 0, 0, 200), A), 96, 3.0f * u);
        dl->AddCircle(mc, R - 1.0f * u, Fade(IM_COL32(244, 240, 228, 150), A), 96, 1.2f * u);
        {
            const float dx = -sn, dy = -cs;   // game north (0,-1) on the map: r = -sin, f = cos
            const ImVec2 np(mc.x + dx * R, mc.y + dy * R);
            dl->AddCircleFilled(np, 8.5f * u, Fade(IM_COL32(20, 22, 28, 240), A), 24);
            dl->AddCircle(np, 8.5f * u, Fade(IM_COL32(244, 240, 228, 150), A), 24, 1.0f * u);
            const ImVec2 ns = Measure(g_fonts.label, g_fonts.labelPx * 0.8f, "N");
            dl->AddText(g_fonts.label, g_fonts.labelPx * 0.8f, ImVec2(np.x - ns.x * 0.5f, np.y - ns.y * 0.5f), Fade(kWhite, A), "N");
        }
    }

    // Health (and armour, if the game ever tells us) under the map; the car's condition beside.
    if (v.health >= 0) {
        if (an.lastHealth >= 0 && v.health < an.lastHealth) an.hurt = 1.0f;
        an.lastHealth = v.health;
        const float frac = (std::max)(0.0f, (std::min)(1.0f, v.health / 100.0f));
        const bool low = v.health <= 30;
        const float pulse = low ? 0.5f + 0.5f * std::sin(an.time * 7.0f) : 0.0f;
        const float carW = v.carDamage >= 0 ? mapW * 0.38f : 0.0f;
        const ImVec2 a(m0.x, m1.y + 6 * u), b(m1.x - (carW > 0 ? carW + 6 * u : 0), m1.y + 6 * u + barH);
        dl->AddRectFilled(a, b, Fade(IM_COL32(0, 0, 0, 160), A), 3 * u);
        const ImU32 col = low ? Mix(kRed, kWhite, pulse * 0.4f) : Mix(kGreen, kWhite, an.hurt * 0.8f);
        dl->AddRectFilled(ImVec2(a.x + 1.5f * u, a.y + 1.5f * u), ImVec2(a.x + 1.5f * u + (b.x - a.x - 3 * u) * frac, b.y - 1.5f * u), Fade(col, A), 2 * u);
        if (carW > 0) {
            const float cf = (std::max)(0.0f, (std::min)(1.0f, (32000.0f - v.carDamage) / 32000.0f));
            const ImVec2 ca(b.x + 6 * u, a.y), cb(m1.x, b.y);
            dl->AddRectFilled(ca, cb, Fade(IM_COL32(0, 0, 0, 160), A), 3 * u);
            dl->AddRectFilled(ImVec2(ca.x + 1.5f * u, ca.y + 1.5f * u), ImVec2(ca.x + 1.5f * u + (cb.x - ca.x - 3 * u) * cf, cb.y - 1.5f * u),
                              Fade(v.carDamage >= 16000 ? IM_COL32(255, 140, 30, 255) : kCyan, A), 2 * u);
        }
        // The damage flash and, at low health, a slow red pulse at the screen's edges.
        const float vign = (std::max)(an.hurt * 0.55f, low ? 0.22f + 0.18f * pulse : 0.0f) * A;
        if (vign > 0.01f) {
            const ImU32 r0 = Fade(kRed, vign), r1 = Fade(kRed, 0.0f);
            const float e = H * 0.22f;
            dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(W, e), r0, r0, r1, r1);
            dl->AddRectFilledMultiColor(ImVec2(0, H - e), ImVec2(W, H), r1, r1, r0, r0);
            dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(e, H), r0, r1, r1, r0);
            dl->AddRectFilledMultiColor(ImVec2(W - e, 0), ImVec2(W, H), r1, r0, r0, r1);
        }
        an.hurt = (std::max)(0.0f, an.hurt - dt / 0.6f);
    }

    // qaf23: the health collect message as a chip at the game's top-centre slot; FIX-HUD-8 (qar33):
    // a weapon's (green accent) and any other collect word's (cyan) the same way, in the game's own
    // words, up exactly while the game's word is (the part's frames), out over a quarter second.
    {
        const bool on = g_collect.kind != CollectKind::None && g_collect.frame + 2 >= g_frame;
        if (on) { g_collect.drawn = g_collect.kind; g_collect.drawnText = g_collect.text; }
        g_collect.alpha += ((on ? 1.0f : 0.0f) - g_collect.alpha) * (1.0f - std::exp(-dt * (on ? 20.0f : 8.0f)));
        if (g_collect.alpha > 0.01f && g_collect.drawn != CollectKind::None) {
            const float ca = A * g_collect.alpha;
            const bool health = g_collect.drawn == CollectKind::Health;
            const std::string word = health ? std::string("HEALTH") : g_collect.drawnText;
            char gain[16] = {};
            if (health && g_collect.gain > 0) snprintf(gain, sizeof gain, "+%d", g_collect.gain);
            const ImVec2 ws = Measure(g_fonts.heavy, g_fonts.heavyPx, word.c_str());
            const ImVec2 gs = gain[0] ? Measure(g_fonts.heavy, g_fonts.heavyPx, gain) : ImVec2(0, 0);
            const float h = ws.y + 8 * u, iconW = 30 * u;
            const float w = iconW + ws.x + (gain[0] ? gs.x + 10 * u : 0) + 26 * u;
            // Under the zone/car plates when they are up (eased, they slide), else the game's slot.
            static float s_top480 = 30.0f;
            const float want480 = (std::max)(30.0f, g_platesBottom > 0.0f ? g_platesBottom + 4.0f : 30.0f);
            s_top480 = g_collect.alpha < 0.05f ? want480 : s_top480 + (want480 - s_top480) * (1.0f - std::exp(-dt * 12.0f));
            const float top = H * (s_top480 / 480.0f) + (1.0f - g_collect.alpha) * -6 * u;
            const ImVec2 a(W * 0.5f - w * 0.5f, top), b(W * 0.5f + w * 0.5f, top + h);
            const ImU32 accent = health ? kRed : g_collect.drawn == CollectKind::Weapon ? kGreen : kCyan;
            Panel(dl, a, b, ca, accent);
            const ImVec2 ic(a.x + 12 * u + iconW * 0.5f, (a.y + b.y) * 0.5f);
            if (health) Heart(dl, ic, 11.0f * u, 0.82f, ca, true);   // the row's mesh, scaled
            else {   // a plus in a ring: "collected"
                const float r = 9.5f * u, t = (std::max)(1.5f, 2.2f * u);
                dl->AddCircle(ic, r, Fade(accent, ca), 24, t);
                dl->AddLine(ImVec2(ic.x - r * 0.5f, ic.y), ImVec2(ic.x + r * 0.5f, ic.y), Fade(kWhite, ca), t);
                dl->AddLine(ImVec2(ic.x, ic.y - r * 0.5f), ImVec2(ic.x, ic.y + r * 0.5f), Fade(kWhite, ca), t);
            }
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(a.x + 14 * u + iconW, a.y + 4 * u), kWhite, word.c_str(), ca);
            if (gain[0]) Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(b.x - 12 * u - gs.x, a.y + 4 * u), kGreen, gain, ca);
        }
    }

    // The phone: the nearest phone marker within ten blocks, a ringing chip on the right.
    {
        const Arrow* best = nullptr;
        float bestD = 10.0f;
        for (const Arrow& ar : v.arrows) {
            if (ar.type < 1 || ar.type > 4) continue;
            const float d = std::hypot(ar.x - v.x, ar.y - v.y);
            if (d < bestD) { bestD = d; best = &ar; }
        }
        if (best && !v.inVehicle) {
            const float h = 46 * u, w = 230 * u;
            const ImVec2 a(W - margin - w, H * 0.52f), b(W - margin, H * 0.52f + h);
            Panel(dl, a, b, A, kCyan);
            const ImVec2 c(a.x + 28 * u, a.y + h * 0.5f);
            const float ring = std::fmod(an.time * 1.4f, 1.0f);
            dl->AddCircle(c, (8 + 12 * ring) * u, Fade(kCyan, A * (1 - ring)), 24, 2 * u);
            // a handset
            dl->AddRectFilled(ImVec2(c.x - 7 * u, c.y - 3 * u), ImVec2(c.x + 7 * u, c.y + 3 * u), Fade(kWhite, A), 3 * u);
            dl->AddRectFilled(ImVec2(c.x - 9 * u, c.y - 6 * u), ImVec2(c.x - 4 * u, c.y + 1 * u), Fade(kWhite, A), 2 * u);
            dl->AddRectFilled(ImVec2(c.x + 4 * u, c.y - 6 * u), ImVec2(c.x + 9 * u, c.y + 1 * u), Fade(kWhite, A), 2 * u);
            const char* title = bestD < 1.2f ? "ANSWER THE PHONE" : "PHONE RINGING";
            Text(dl, g_fonts.heavy, g_fonts.heavyPx * 0.85f, ImVec2(a.x + 50 * u, a.y + 4 * u), kWhite, title, A);
            char sub[48];
            if (bestD < 1.2f) snprintf(sub, sizeof sub, "STEP ONTO IT");
            else snprintf(sub, sizeof sub, "%.0f BLOCKS AWAY", std::ceil(bestD));
            Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(a.x + 50 * u, b.y - g_fonts.labelPx - 4 * u), Fade(kCyan, 0.95f), sub, A);
        }
    }

    // The brief: the speaker's portrait and the words, bottom centre, '#' words in yellow.
    {
        const bool up = g_briefResolved && g_partSeen[10] + 2 >= g_frame;
        if (up && g_briefKey != an.briefKey) {
            an.briefKey = g_briefKey;
            BriefWords(an.briefKey, &an.brief);
        }
        if (up && g_portrait.frame + 2 >= g_frame && g_portrait.texture) an.briefPortrait = g_portrait;
        an.briefAlpha += ((up ? 1.0f : 0.0f) - an.briefAlpha) * (1.0f - std::exp(-dt * 10.0f));
        if (an.briefAlpha > 0.02f && !an.brief.empty()) {
            const float BA = A * an.briefAlpha;
            const float w = (std::min)(W * 0.56f, 760.0f * u);
            const float pad = 14 * u, portrait = 84 * u;
            const float textX = pad * 2 + portrait, textW = w - textX - pad;
            // lay the words out
            const float space = Measure(g_fonts.text, g_fonts.textPx, " ").x;
            struct Placed { const Word* w; float x, line; };
            std::vector<Placed> placed;
            float x = 0;
            int line = 0;
            for (const Word& wd : an.brief) {
                const float ww = Measure(g_fonts.text, g_fonts.textPx, wd.text.c_str()).x;
                if (wd.glue && x > 0) x -= space;
                if (x > 0 && x + ww > textW && !wd.glue) { x = 0; ++line; }
                placed.push_back({&wd, x, static_cast<float>(line)});
                x += ww + space;
            }
            const float lineH = g_fonts.textPx * 1.18f;
            const float h = (std::max)(portrait + pad * 2, (line + 1) * lineH + pad * 2);
            const float slide = (1.0f - an.briefAlpha) * 18 * u;
            const ImVec2 a(W * 0.5f - w * 0.5f, H - margin - h + slide), b(W * 0.5f + w * 0.5f, H - margin + slide);
            // keep clear of the map
            const ImVec2 aa(std::max(a.x, m1.x + 20 * u), a.y), bb(std::max(b.x, m1.x + 20 * u + w), b.y);
            Panel(dl, aa, bb, BA * 1.15f, kYellow);
            const ImVec2 pa(aa.x + pad, aa.y + pad), pb(pa.x + portrait, pa.y + portrait);
            dl->AddRectFilled(pa, pb, Fade(IM_COL32(0, 0, 0, 200), BA), 4 * u);
            if (an.briefPortrait.texture) {
                const float pw = an.briefPortrait.maxX - an.briefPortrait.minX, ph = an.briefPortrait.maxY - an.briefPortrait.minY;
                const float fit = (std::min)(portrait / pw, portrait / ph);
                const ImVec2 ia(pa.x + (portrait - pw * fit) * 0.5f, pa.y + (portrait - ph * fit) * 0.5f);
                DrawCapture(dl, device, an.briefPortrait, ia, ImVec2(ia.x + pw * fit, ia.y + ph * fit), BA);
            }
            dl->AddRect(pa, pb, Fade(kYellow, BA * 0.8f), 4 * u, 0, 1.5f * u);
            const float ty = aa.y + (h - (line + 1) * lineH) * 0.5f;
            for (const Placed& p : placed)
                Text(dl, g_fonts.text, g_fonts.textPx, ImVec2(aa.x + textX + p.x, ty + p.line * lineH),
                     p.w->highlight ? kYellow : kWhite, p.w->text.c_str(), BA);
        }
    }
    // The panels inside the letterbox: the top half's down by the bar, the bottom half's up.
    const float bar = BeatBarPx(W, H);
    if (bar > 0.5f) {
        for (int i = panelVtx0; i < dl->VtxBuffer.Size; ++i) {
            ImDrawVert& vx = dl->VtxBuffer[i];
            vx.pos.y += vx.pos.y < H * 0.5f ? bar : -bar;
        }
        // Clip rects narrower than the screen (the mini-map's) go with what they clip.
        for (int i = (std::max)(0, panelCmd0 - 1); i < dl->CmdBuffer.Size; ++i) {
            ImVec4& c = dl->CmdBuffer[i].ClipRect;
            if (c.w - c.y >= H - 1.0f) continue;
            const float dy = 0.5f * (c.y + c.w) < H * 0.5f ? bar : -bar;
            c.y += dy; c.w += dy;
        }
    }
    // QB-50: under the panels (the background list is drawn first).
    DrawWorldLayer(ImGui::GetBackgroundDrawList(), v, A, W, H, dt);
}

// QB-17/18: a beat's screen treatment - a colour wash and an edge darkening, the
// letterbox bars sliding in, the title in the HUD's heavy face with a short scale-in, and
// the fade to black that hides the respawn cut.
float Smoothstep01(float x) {
    x = (std::max)(0.0f, (std::min)(1.0f, x));
    return x * x * (3.0f - 2.0f * x);
}

void DrawBeat(ImDrawList* dl, float W, float H) {
    const BeatState& b = Beat();
    const float u = g_u;
    ImU32 wash = IM_COL32(0, 0, 0, 0), edge = IM_COL32(0, 0, 0, 0), rule = kWhite;
    switch (b.kind) {
        case BeatKind::Wasted:     // drained, a dark red cast, heavy edges
            wash = IM_COL32(70, 58, 58, 110); edge = IM_COL32(40, 0, 0, 200);
            rule = IM_COL32(222, 38, 32, 255);
            break;
        case BeatKind::Busted:     // cold blue cast, the edges lit red/blue in turn
            wash = IM_COL32(20, 34, 80, 90); edge = IM_COL32(0, 10, 40, 190);
            rule = IM_COL32(110, 160, 255, 255);
            break;
        case BeatKind::Complete:   // warm, light
            wash = IM_COL32(90, 70, 20, 40); edge = IM_COL32(30, 20, 0, 120);
            rule = kYellow;
            break;
        default: return;
    }
    const float tint = b.tint;
    if (tint > 0.0f) {
        dl->AddRectFilled(ImVec2(0, 0), ImVec2(W, H), Fade(wash, tint));
        // The edges: gradients a fifth of the way in from each side.
        const ImU32 e = Fade(edge, tint), clear = Fade(edge, 0.0f);
        const float ex = W * 0.2f, ey = H * 0.22f;
        dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(ex, H), e, clear, clear, e);
        dl->AddRectFilledMultiColor(ImVec2(W - ex, 0), ImVec2(W, H), clear, e, e, clear);
        dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(W, ey), e, e, clear, clear);
        dl->AddRectFilledMultiColor(ImVec2(0, H - ey), ImVec2(W, H), clear, clear, e, e);
        if (b.kind == BeatKind::Busted) {
            // The squad car's beacons on the edges: red left, blue right, swapping 2.5 times a second.
            const bool phase = std::fmod(b.t * 2.5f, 1.0f) < 0.5f;
            const ImU32 red = Fade(IM_COL32(230, 30, 30, 90), tint), blue = Fade(IM_COL32(40, 80, 255, 90), tint);
            const ImU32 l = phase ? red : blue, r = phase ? blue : red;
            const ImU32 l0 = Fade(l, 0.0f), r0 = Fade(r, 0.0f);
            dl->AddRectFilledMultiColor(ImVec2(0, 0), ImVec2(W * 0.14f, H), l, l0, l0, l);
            dl->AddRectFilledMultiColor(ImVec2(W - W * 0.14f, 0), ImVec2(W, H), r0, r, r, r0);
        }
    }
    // Letterbox: 2.39:1 at full height of the bars.
    const float barFull = (std::max)(0.0f, (H - W / 2.39f) * 0.5f);
    const float bar = barFull * (1.0f - (1.0f - b.letterbox) * (1.0f - b.letterbox));
    if (bar > 0.5f) {
        dl->AddRectFilled(ImVec2(0, 0), ImVec2(W, bar), IM_COL32(0, 0, 0, 255));
        dl->AddRectFilled(ImVec2(0, H - bar), ImVec2(W, H), IM_COL32(0, 0, 0, 255));
    }
    // The fade to black that hides the respawn cut, under the title (which stays readable on it).
    if (b.black > 0.0f) dl->AddRectFilled(ImVec2(0, 0), ImVec2(W, H), Fade(IM_COL32(0, 0, 0, 255), b.black));
    // FIX-HUD-3 (pmq10-third-busted-caption): the title in the classic view's own colour and weight,
    // the game's big-message face: opaque, a vertical yellow-to-orange fill (255,241,66 at the top,
    // 255,122,40 at the foot, measured on the classic BUSTED! of pt8_bil19 shot_625) inside an indigo
    // outline with a drop shadow. Before, it faded in over 0.4 s in the beat's cast colour (BUSTED a
    // light blue) under a black shadow at the same alpha: the playtest frame caught it at 15 % as a
    // dark navy stamp on the grass at his feet, which read as something in the world. It is set
    // where classic sets it, in the upper third (inside the letterbox picture), over the figures,
    // at full strength within 0.12 s of the message, and drawn over the fade to black.
    if (b.title > 0.01f && g_fonts.title && !b.titleText.empty()) {
        const float pop = 1.0f + 0.12f * std::exp(-b.t / 0.18f);
        const float px = g_fonts.titlePx * pop;
        const char* s = b.titleText.c_str();
        const ImVec2 sz = Measure(g_fonts.title, px, s);
        const ImVec2 at(std::round((W - sz.x) * 0.5f), std::round((std::max)(barFull + 0.035f * H, 0.215f * H - 0.5f * (px - g_fonts.titlePx))));
        const float a = b.title;
        const float o = (std::max)(2.0f, std::round(3.0f * u));       // the outline's width
        const float d = (std::max)(3.0f, std::round(5.0f * u));       // the drop shadow's offset
        const ImU32 shadow = Fade(IM_COL32(16, 10, 40, 235), a);
        const ImU32 outline = Fade(IM_COL32(72, 56, 138, 255), a);
        dl->AddText(g_fonts.title, px, ImVec2(at.x + d, at.y + d), shadow, s);
        dl->AddText(g_fonts.title, px, ImVec2(at.x + d - o, at.y + d), shadow, s);
        for (int i = 0; i < 8; ++i) {
            const float ang = static_cast<float>(i) * 0.7853982f;
            dl->AddText(g_fonts.title, px, ImVec2(at.x + o * std::cos(ang), at.y + o * std::sin(ang)), outline, s);
        }
        const int v0 = dl->VtxBuffer.Size;
        dl->AddText(g_fonts.title, px, at, Fade(IM_COL32(255, 255, 255, 255), a), s);
        // The glyphs' ink spans about 0.2..0.92 of the line height in this face.
        ImGui::ShadeVertsLinearColorGradientKeepAlpha(dl, v0, dl->VtxBuffer.Size, ImVec2(at.x, at.y + 0.2f * sz.y),
                                                      ImVec2(at.x, at.y + 0.92f * sz.y), IM_COL32(255, 241, 66, 255), IM_COL32(255, 122, 40, 255));
        // A thin rule under it, drawn out from the middle, in the beat's cast.
        const float half = sz.x * 0.5f * Smoothstep01((b.t - 0.3f) / 0.5f);
        const float ry = at.y + sz.y + 6.0f * u;
        if (half > 1.0f && b.black < 0.5f)
            dl->AddRectFilled(ImVec2(W * 0.5f - half, ry), ImVec2(W * 0.5f + half, ry + (std::max)(2.0f, 3.0f * u)), Fade(rule, a * 0.9f * (1.0f - b.black)));
    }
}

// FIX-PERF-VSWITCH: what the modern HUD builds on its first street frame (the game's texts, the
// ImGui context and its fonts, the mini-map, the font texture and the GL program its draws need)
// made in the classic view instead, a piece a frame from two seconds into a level: 180-590 ms of
// the first V's frame (out/vsw_before1 "ui 586", out/vsw_glcb2 "ui 181"). Nothing is drawn: the
// one ImGui frame below is rendered with colour writes off, under the backend's own state block.
int g_prewarmStep = 0;
int g_prewarmFrames = 0;
void Prewarm(IDirect3DDevice9* device, int width, int height, const gta2::Map& map, bool worldLoaded) {
    if (g_prewarmStep > 4 || !device || width <= 0 || height <= 0 || !worldLoaded) return;
    if (!g_cfg.modern && !g_cfg.markers) { g_prewarmStep = 5; return; }
    if (++g_prewarmFrames < 60 || (g_prewarmFrames & 1)) return;   // every other frame from ~2 s in
    LARGE_INTEGER a, b, f;
    QueryPerformanceCounter(&a);
    const int step = g_prewarmStep++;
    if (step == 0) {
        LoadGxt();
    } else if (step == 1) {
        if (!EnsureContext(device, height)) { g_prewarmStep = 5; return; }
    } else if (step == 2) {
        if (g_cfg.minimap && g_cfg.modern) BuildMap(device, map);
    } else if (step == 3 || step == 4) {
        // The font texture (step 3), then one invisible frame through the backend (step 4).
        ImGuiContext* previous = ImGui::GetCurrentContext();
        ImGui::SetCurrentContext(g_ctx);
        if (g_fontHeight != height || g_glyphs.gen != HudGameFontGeneration()) BuildFonts(height);
        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(static_cast<float>(width), static_cast<float>(height));
        io.DeltaTime = 1.0f / 30.0f;
        ImGui_ImplDX9_NewFrame();
        ImGui::NewFrame();
        if (step == 4) {
            ImDrawList* dl = ImGui::GetForegroundDrawList();
            dl->AddRectFilled(ImVec2(0, 0), ImVec2(4, 4), IM_COL32(0, 0, 0, 255));
            if (g_fonts.text) dl->AddText(g_fonts.text, g_fonts.textPx, ImVec2(0, 0), IM_COL32(255, 255, 255, 255), "0");
        }
        ImGui::EndFrame();
        ImGui::Render();
        if (step == 4) {
            DWORD colorWrite = 0xF;
            device->GetRenderState(D3DRS_COLORWRITEENABLE, &colorWrite);
            device->SetRenderState(D3DRS_COLORWRITEENABLE, 0);
            ImGui_ImplDX9_RenderDrawData(ImGui::GetDrawData());
            device->SetRenderState(D3DRS_COLORWRITEENABLE, colorWrite);
        }
        ImGui::SetCurrentContext(previous);
    }
    QueryPerformanceCounter(&b);
    QueryPerformanceFrequency(&f);
    Log("hud3d: made ahead in the classic view: step %d (%s) %.1f ms", step,
        step == 0 ? "texts" : step == 1 ? "context and fonts" : step == 2 ? "mini-map" : step == 3 ? "font texture" : "first draw",
        1000.0 * static_cast<double>(b.QuadPart - a.QuadPart) / static_cast<double>(f.QuadPart));
}

}  // namespace

bool Hud3dActive() { return g_active; }

bool g_switchHold = false;
void Hud3dHoldForSwitch(bool hold) { g_switchHold = hold; }

bool Hud3dTopPlates(float* bandBottom) {
    if (bandBottom) *bandBottom = 0.0f;
    if (!StreetPresentation()) return false;   // with the rest of the street presentation (FIX-SMOOTH-SWITCH)
    // The roof lining's lower edge sits at about 45 of 480 in a closed cab (cab_interior.cpp, the
    // header at a fixed angle from the eye). An open top (CabOpenTop) has sky there and its
    // windscreen rail near 85: the plates keep the game's slot above the rail.
    // The lining's edge as the cab drew it this frame (CabHeaderScreenBottom), which moves with the
    // cab class and the car's pitch: 32-85 of 480 in a Z-Type, 0-45 in a Panto.
    const PlayerState& p = ViewPlayer();
    float f = 0.0f;
    if (bandBottom && CurrentViewMode() == ViewMode::FirstPerson && p.valid && p.inVehicle && CabHeaderScreenBottom(&f))
        *bandBottom = (std::min)(200.0f, (std::max)(0.0f, f * 480.0f + 2.0f));
    return true;
}

void Hud3dNoteTopPlatesBottom(float y480) { g_platesBottom = y480; }

bool Hud3dGameText(const char* key, std::u16string* out) {
    LoadGxt();
    const auto it = g_gxt.find(key ? key : "");
    if (it == g_gxt.end()) return false;
    if (out) *out = it->second;
    return true;
}

// FIX-HUD-8 (pmw2): the quit prompt (part 18, FUN_004C8710: "Is that it?" / "Press the ENTER key to quit
// play." / "Press the ESC key to resume play.", e.gxt quit1-quit3) over a street view was the game's olive
// 640x480 pixel font straight on the live scene. There it is swallowed and drawn here: the scene (and the
// modern HUD) dimmed by a scrim, a centred glass card with the game's three lines in the HUD's type, the
// key word of each line (the upper-case word: ENTER, ESC) on a key cap. The classic view keeps the game's.
uint32_t g_quitFrame = 0;
float g_quitAlpha = 0.0f;
std::string QuitLine(const char* key, const char* fallback) {
    std::u16string t;
    if (!Hud3dGameText(key, &t)) return fallback;
    std::string out;
    for (char16_t c : t) {
        if (c == u'#') continue;
        if (c < 0x80) out.push_back(static_cast<char>(c));
        else if (c < 0x100) { out.push_back(static_cast<char>(0xC0 | (c >> 6))); out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
    }
    return out.empty() ? std::string(fallback) : out;
}
void DrawQuit(ImDrawList* dl, float W, float H, float alpha) {
    const float u = g_u;
    // The scrim: the whole frame dimmed, a little more towards the middle where the card sits.
    dl->AddRectFilled(ImVec2(0, 0), ImVec2(W, H), IM_COL32(0, 0, 0, static_cast<int>(150 * alpha)));
    static std::string title, lines[2];
    if (title.empty()) {
        title = QuitLine("quit1", "Is that it?");
        lines[0] = QuitLine("quit2", "Press the ENTER key to quit play.");
        lines[1] = QuitLine("quit3", "Press the ESC key to resume play.");
        for (char& c : title) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
    }
    ImFont* tf = g_fonts.title ? g_fonts.title : g_fonts.heavy;
    const float tpx = (g_fonts.title ? g_fonts.titlePx * 0.62f : g_fonts.heavyPx * 1.4f);
    ImFont* lf = g_fonts.text ? g_fonts.text : g_fonts.heavy;
    const float lpx = g_fonts.text ? g_fonts.textPx * 1.12f : g_fonts.heavyPx;
    const float capPad = 7 * u, gap = lpx * 0.28f;
    // Lay each line out as words; the all-capitals word (2+ letters) goes on a key cap.
    struct Piece { std::string s; bool cap; float w; };
    std::vector<Piece> rows[2];
    float rowW[2] = {0, 0};
    for (int r = 0; r < 2; ++r) {
        size_t i = 0;
        const std::string& L = lines[r];
        while (i < L.size()) {
            size_t j = L.find(' ', i);
            if (j == std::string::npos) j = L.size();
            std::string w = L.substr(i, j - i);
            i = j + 1;
            if (w.empty()) continue;
            int letters = 0, upper = 0;
            for (char c : w) if (isalpha(static_cast<unsigned char>(c))) { ++letters; if (isupper(static_cast<unsigned char>(c))) ++upper; }
            const bool cap = letters >= 2 && upper == letters;
            const float ww = Measure(lf, lpx, w.c_str()).x + (cap ? capPad * 2 : 0);
            rows[r].push_back({w, cap, ww});
            rowW[r] += ww + (rows[r].size() > 1 ? gap : 0);
        }
    }
    const ImVec2 ts = Measure(tf, tpx, title.c_str());
    const float cardW = (std::max)((std::max)(rowW[0], rowW[1]), ts.x) + 64 * u;
    const float rowH = lpx + 10 * u;
    const float cardH = 22 * u + ts.y + 16 * u + rowH * 2 + 8 * u + 22 * u;
    const ImVec2 a(W * 0.5f - cardW * 0.5f, H * 0.42f - cardH * 0.5f), b(W * 0.5f + cardW * 0.5f, H * 0.42f + cardH * 0.5f);
    dl->AddRectFilled(a, b, IM_COL32(8, 10, 16, static_cast<int>(222 * alpha)), 10 * u);
    dl->AddRect(a, b, Fade(kYellow, 0.55f * alpha), 10 * u, 0, (std::max)(1.0f, 1.5f * u));
    float y = a.y + 22 * u;
    Text(dl, tf, tpx, ImVec2(W * 0.5f - ts.x * 0.5f, y), kYellow, title.c_str(), alpha);
    y += ts.y + 8 * u;
    dl->AddRectFilled(ImVec2(W * 0.5f - cardW * 0.32f, y), ImVec2(W * 0.5f + cardW * 0.32f, y + (std::max)(1.0f, 1.5f * u)), Fade(kWhite, 0.25f * alpha));
    y += 8 * u;
    for (int r = 0; r < 2; ++r) {
        float x = W * 0.5f - rowW[r] * 0.5f;
        for (const Piece& pc : rows[r]) {
            if (pc.cap) {
                const ImVec2 c0(x, y + 1 * u), c1(x + pc.w, y + lpx + 5 * u);
                dl->AddRectFilled(c0, c1, Fade(kWhite, 0.92f * alpha), 5 * u);
                dl->AddRectFilled(ImVec2(c0.x, c1.y - 3 * u), c1, IM_COL32(120, 120, 128, static_cast<int>(235 * alpha)), 5 * u, ImDrawFlags_RoundCornersBottom);
                Text(dl, lf, lpx, ImVec2(x + capPad, y + 1 * u), IM_COL32(12, 14, 20, 255), pc.s.c_str(), alpha, false);
            } else {
                Text(dl, lf, lpx, ImVec2(x, y + 3 * u), kWhite, pc.s.c_str(), alpha);
            }
            x += pc.w + gap;
        }
        y += rowH;
    }
}

// GTA2DX9_HUD_LOG_PARTS=1 (FIX-HUD-4, qaf23): in a street view, each appearance of a centred text part
// (7, 8, 9, 12, 14) is logged once with its box, its quads and the game's last text key.
struct PartTrace { uint32_t frame = 0, first = 0; float minX = 1e9f, minY = 1e9f, maxX = -1e9f, maxY = -1e9f; int quads = 0; bool logged = false; };
PartTrace g_partTrace[19];


int g_logParts = -1;

bool Hud3dSwallow(bool hud, int part, const void* texture, const void* corners, int count) {
    if (!hud || part < 0 || part > 18) return false;
    if (g_logParts < 0) { char b[4] = {}; g_logParts = GetEnvironmentVariableA("GTA2DX9_HUD_LOG_PARTS", b, sizeof b) && b[0] == '1'; }
    if (g_logParts && g_street && (part == 7 || part == 8 || part == 9 || part == 12 || part == 14) && corners) {
        PartTrace& t = g_partTrace[part];
        if (t.frame + 3 < g_frame) { t = PartTrace{}; t.first = g_frame; }
        if (t.frame != g_frame) t.quads = 0;
        t.frame = g_frame;
        ++t.quads;
        const Corner* k = static_cast<const Corner*>(corners);
        for (int i = 0; i < count; ++i) {
            t.minX = (std::min)(t.minX, k[i].x); t.maxX = (std::max)(t.maxX, k[i].x);
            t.minY = (std::min)(t.minY, k[i].y); t.maxY = (std::max)(t.maxY, k[i].y);
        }
        if (!t.logged && g_frame >= t.first + 2) {
            t.logged = true;
            Log("hud3d: part %d in a street view: box %.0f,%.0f-%.0f,%.0f, %d quads a frame, last text key '%s'",
                part, t.minX, t.minY, t.maxX, t.maxY, t.quads, ReadMessageKey().c_str());
        }
    }
    // GTA2DX9_HUD_LOG_GLYPHS=1 (FIX-HUD-5 probe): the game's own text quads of parts 1, 6 and 11, each
    // distinct one logged once: its texture's size and palette, the texel rect, the quad's size and colour.
    static int s_logGlyphs = -1;
    if (s_logGlyphs < 0) { char b[4] = {}; s_logGlyphs = GetEnvironmentVariableA("GTA2DX9_HUD_LOG_GLYPHS", b, sizeof b) && b[0] == '1'; }
    if (s_logGlyphs && (part == 1 || part == 6 || part == 11) && corners && texture && count >= 3) {
        static std::vector<uint64_t> s_seen;
        const Corner* q = static_cast<const Corner*>(corners);
        const gta2dx9::TextureRecord* r = static_cast<const gta2dx9::TextureRecord*>(texture);
        const uint64_t key = (static_cast<uint64_t>(reinterpret_cast<uintptr_t>(r->pixels)) << 16) ^ (static_cast<uint64_t>(q[0].u * 1024) << 40) ^ (static_cast<uint64_t>(q[0].v * 1024) << 52) ^ r->palette ^ (static_cast<uint64_t>(part) << 60);
        if (s_seen.size() < 200 && std::find(s_seen.begin(), s_seen.end(), key) == s_seen.end()) {
            s_seen.push_back(key);
            Log("hud3d: glyph part %d view %d tex %dx%d pal %d pix %p uv %.4f,%.4f-%.4f,%.4f quad %.1f,%.1f %.1fx%.1f col %08X",
                part, static_cast<int>(CurrentViewMode()), r->width, r->height, r->palette, r->pixels, q[0].u, q[0].v, q[2].u, q[2].v,
                q[0].x, q[0].y, q[2].x - q[0].x, q[2].y - q[0].y, q[0].colour);
        }
    }
    if (part == 18 && g_street) {   // FIX-HUD-8 (pmw2): the quit prompt, drawn by DrawQuit
        if (g_quitFrame + 3 < g_frame) Log("hud3d: quit prompt (part 18) in a street view: swallowed, drawn as a card over a scrim");
        g_quitFrame = g_frame; g_partSeen[part] = g_frame;
        return true;
    }
    if (part == 9) {
        // A new appearance (in any view: FIX-HUD-8): what is it? Asked again each frame of the first second
        // while the answer is 'unknown': the word comes up the frame of the pickup, the gun reaches his
        // hand a frame or more later (fh8_a: weapon 0 at the word's first frame, 4 after).
        const bool fresh = g_collect.frame + 3 < g_frame;
        if (fresh) { g_collect.first = g_frame; g_collect.logged = false; }
        if (fresh || (g_collect.kind == CollectKind::None && g_frame <= g_collect.first + 30)) {
            int health = -1, weapon = -1, ammo = 0, raw = -1;
            GTA2_TRY {
                const uint8_t* ped = static_cast<const uint8_t*>(ViewPlayer().ped);
                if (ped) {
                    health = *reinterpret_cast<const int16_t*>(ped + 0x216);
                    raw = game::PedWeaponRaw(ped, &ammo);
                    weapon = raw >= 0 ? game::PedWeaponOf(ped, nullptr) : 0;
                }
            } GTA2_EXCEPT {}
            const bool healthUp = (g_seenHealth >= 0 && health > g_seenHealth) || g_healthRiseFrame + 30 >= g_frame;
            const bool weaponUp = (weapon > 0 && g_seenWeapon >= 0 && (weapon != g_seenWeapon || ammo > g_seenAmmo)) || g_weaponGainFrame + 30 >= g_frame;
            const std::string key = ReadMessageKey();
            g_collect.text.clear();
            g_collect.kind = healthUp ? CollectKind::Health : weaponUp ? CollectKind::Weapon : CollectKind::None;
            if (g_collect.kind == CollectKind::Weapon) {
                char k[8];
                snprintf(k, sizeof k, "c%02d", raw >= 0 && raw < 100 ? raw : 0);
                g_collect.text = raw >= 0 ? CollectWords(k) : std::string();
                if (g_collect.text.empty()) {   // not in the gxt: the renderer's own name for it
                    g_collect.text = WeaponName(weapon);
                    for (char& c : g_collect.text) c = c == '_' ? ' ' : static_cast<char>(toupper(static_cast<unsigned char>(c)));
                }
            } else if (g_collect.kind == CollectKind::None && key.size() == 3 && key[0] == 'c' && key >= "c28" && key <= "c37" && key != "c30") {
                g_collect.text = CollectWords(key.c_str());
                if (!g_collect.text.empty()) g_collect.kind = CollectKind::Other;
            }
            g_collect.gain = healthUp && g_seenHealth >= 0 && health > g_seenHealth ? health - g_seenHealth : 0;
            const bool streetNow = g_active && g_street;
            if (!g_collect.logged && (g_collect.kind != CollectKind::None || g_frame >= g_collect.first + 30)) {
            g_collect.logged = true;
            if (streetNow) {
                if (g_collect.kind == CollectKind::Health) ++g_collect.shown;
                else if (g_collect.kind != CollectKind::None) ++g_collect.swallowed;
                else ++g_collect.kept;
            }
            Log("hud3d: collect message (part 9) %s: %s%s%s (health %d -> %d, weapon %d raw %d ammo %d, text key '%s')",
                streetNow ? "in a street view" : "in the classic view (the game's; classified for a switch)",
                g_collect.kind == CollectKind::Health ? "health, drawn as a chip" : g_collect.kind == CollectKind::Weapon ? "a weapon, drawn as a chip: " :
                g_collect.kind == CollectKind::Other ? "a collect word, drawn as a chip: " : "unknown, the game's",
                g_collect.text.c_str(), g_frame > g_collect.first ? " (told on a later frame)" : "", g_seenHealth, health, weapon, raw, ammo, key.c_str());
            }
        }
        g_collect.frame = g_frame;
        if (g_active && g_street && g_collect.kind != CollectKind::None) { g_partSeen[part] = g_frame; return true; }
    }
    g_partSeen[part] = g_frame;
    const Corner* k = static_cast<const Corner*>(corners);
    if (k && texture) {
        if (part == 1) {
            float minX = k[0].x, maxX = k[0].x;
            for (int i = 1; i < count; ++i) { minX = (std::min)(minX, k[i].x); maxX = (std::max)(maxX, k[i].x); }
            if (maxX - minX >= 24.0f) Note(&g_weaponIcon, texture, k, count);   // not a digit of the score (12x22)
            else {
                float minY = k[0].y, maxY = k[0].y;
                for (int i = 1; i < count; ++i) { minY = (std::min)(minY, k[i].y); maxY = (std::max)(maxY, k[i].y); }
                if (maxY - minY >= 24.0f) g_gameAmmoFrame = g_frame;   // FIX-HUD-7: a font-1 cell, the ammunition
            }
        }
        else if (part == 10) {
            Note(&g_portrait, texture, k, count);
            // The top of the game's subtitle block this frame (game y, 480 tall), so the
            // mini-map can rise above the whole block, not a fixed two lines
            // (pm21-third-fp-raised-minimap-still-clips-first-word-of-subtitle).
            if (g_part10Frame != g_frame) { g_part10Frame = g_frame; g_part10MinY = 1e9f; }
            for (int i = 0; i < count; ++i) g_part10MinY = (std::min)(g_part10MinY, k[i].y);
            // The block's first eight glyphs (small quads; the portrait is the big one) by
            // their texture coordinates: which text it is (pm15).
            if (g_briefSigFrame != g_frame) { g_briefSigFrame = g_frame; g_briefSig = 2166136261u; g_briefGlyphs = 0; g_briefGlyphsAll = 0; }
            if (count >= 3 && std::fabs(k[2].x - k[0].x) < 32.0f && std::fabs(k[2].y - k[0].y) < 32.0f) {
                ++g_briefGlyphsAll;
                if (g_briefGlyphs < 8) {
                    const uint32_t q[4] = {static_cast<uint32_t>(k[0].u * 4096.0f), static_cast<uint32_t>(k[0].v * 4096.0f),
                                           static_cast<uint32_t>(k[2].u * 4096.0f), static_cast<uint32_t>(k[2].v * 4096.0f)};
                    for (uint32_t x : q) g_briefSig = (g_briefSig ^ x) * 16777619u;
                    ++g_briefGlyphs;
                }
            }
        }
    }
    // QB-17/18: during a beat its title is drawn here, in the beat's own treatment.
    // (Never in the classic view, which keeps the game's HUD as it draws it.)
    if (part == 15 && Beat().kind != BeatKind::None && CurrentViewMode() != ViewMode::Classic) return true;
    // The game's target arrows (part 2, the marker over a target, and part 13, the arrows
    // pointing at targets) are laid out round the player for the top-down camera: in a street
    // view they hovered on the figure's chest (third person) or mid-screen and on walls (first),
    // as pink/green/violet outlines. They go whenever a street view is up, whatever the modern
    // HUD's state (modern=0, the pause screen, a frame the values could not be read);
    // DrawObjectiveMarkers shows the same slots through the 3D camera. Never in the classic view.
    // FIX-SMOOTH-SWITCH: also through a move between the views, where they would slide over
    // a world the camera no longer frames the game's way (they come back with the settled
    // classic camera).
    if ((part == 2 || part == 13) && g_cfg.markers && (g_street || ViewCameraMoving())) {
        ++g_markerSwallowed;
        return true;
    }
    // FIX-HUD-2 (pm9-fp-wasted / pm10-third-wasted): while WASTED or BUSTED holds a street view the
    // screen belongs to the beat (letterbox, wash, title) and the HUD is none at all. The modern HUD
    // steps aside then and he is often no longer readable as a player (dead, cuffed), so g_active
    // goes off and the game's own corner parts came back: its weapon and ammo, respect bars, wanted
    // heads and hearts, half under the letterbox bars. Never in the classic view, where the beat
    // never runs (it ends at once there).
    if (g_street && (part == 1 || part == 4 || part == 5 || part == 6 || part == 11)) {
        const BeatKind kind = Beat().kind;
        if (kind == BeatKind::Wasted || kind == BeatKind::Busted) return true;
    }
    if (!g_active) return false;
    switch (part) {
        case 1:    // score, lives, multiplier, weapon and ammo
        case 4:    // the row of icons centred at the top: the wanted heads
        case 6:    // the hearts
        case 11:   // the clocks and counters
            return true;
        case 5:    // the gang respect meters (FIX-HUD-4), when ours were drawn
            return g_respectDrawn > 0;
        case 10:   // the talking head, when the brief's text is ours to show
            // The key resolved at the end of the last frame; on the block's first frame, the
            // buffer's key if the gxt has it (the brief was just looked up), so that frame is ours too.
            if (g_briefKey.empty() && g_partSeen[10] == g_frame && g_briefSigFrame + 1 < g_frame) {
                const std::string key = ReadMessageKey();
                LoadGxt();
                if (!key.empty() && g_gxt.count(key) && !g_testGameBrief) g_briefKey = key;
            }
            return !g_briefKey.empty();
        default:
            return false;
    }
}

int Hud3dScorePop() {
    if (!StreetPresentation()) return 0;
    const int verdict = g_active ? 1 : 2;
    static int quads[3] = {0, 0, 0};
    static DWORD last = 0;
    ++quads[verdict];
    const DWORD now = GetTickCount();
    if (now - last > 1000) {
        last = now;
        Log("hud3d: score pop in a street view: %d glyph quads dropped (the modern HUD's +$ pop carries it), %d held to a tenth of the screen",
            quads[1], quads[2]);
        quads[1] = quads[2] = 0;
    }
    return verdict;
}

void Hud3dRender(IDirect3DDevice9* device, int width, int height, const gta2::Map& map, bool worldLoaded) {
    LoadConfig();
    LARGE_INTEGER t0, t1;
    if (!g_qpf.QuadPart) QueryPerformanceFrequency(&g_qpf);
    QueryPerformanceCounter(&t0);
    const float dt = g_lastStamp.QuadPart ? (std::min)(0.1f, static_cast<float>(static_cast<double>(t0.QuadPart - g_lastStamp.QuadPart) / g_qpf.QuadPart)) : 1.0f / 30.0f;
    g_lastStamp = t0;

    if (KeyEdge(g_cfg.toggleKey, &g_toggleDown)) {
        g_cfg.modern = !g_cfg.modern;
        Log("hud3d: toggle key: %s HUD", g_cfg.modern ? "modern" : "classic");
    }
    // The street presentation, which follows the camera through a move between the views
    // rather than the V key (FIX-SMOOTH-SWITCH; world_view.h StreetPresentation): the
    // modern HUD takes over from the game's where the figures take over from the sprites.
    const bool street = worldLoaded && StreetPresentation();
    if (!street) Prewarm(device, width, height, map, worldLoaded);
    Values v = (street || g_active) && (g_cfg.modern || g_cfg.markers) ? ReadValues() : Values{};
    g_street = street;
    if (v.valid) {   // qaf23: what just changed, for telling the collect message apart
        if (g_seenHealth >= 0 && v.health > g_seenHealth) g_healthRiseFrame = g_frame;
        if (v.weapon > 0 && g_seenWeapon >= 0 && (v.weapon != g_seenWeapon || v.ammo > g_seenAmmo)) g_weaponGainFrame = g_frame;
        g_seenHealth = v.health; g_seenWeapon = v.weapon; g_seenAmmo = v.ammo;
    } else if (worldLoaded && ViewPlayer().valid && ViewPlayer().ped) {
        // FIX-HUD-8 (qar33): the same in the classic view (where the values are not read), so a collect
        // word that began there is still known for what it is after V.
        int health = -1, weapon = -1, ammo = 0;
        GTA2_TRY {
            const uint8_t* ped = static_cast<const uint8_t*>(ViewPlayer().ped);
            health = *reinterpret_cast<const int16_t*>(ped + 0x216);
            const int raw = game::PedWeaponRaw(ped, &ammo);
            weapon = raw >= 0 ? game::PedWeaponOf(ped, nullptr) : 0;
            if (raw < 0) ammo = 0;
        } GTA2_EXCEPT { health = -1; }
        if (health >= 0) {
            if (g_seenHealth >= 0 && health > g_seenHealth) g_healthRiseFrame = g_frame;
            if (weapon > 0 && g_seenWeapon >= 0 && (weapon != g_seenWeapon || ammo > g_seenAmmo)) g_weaponGainFrame = g_frame;
            g_seenHealth = health; g_seenWeapon = weapon; g_seenAmmo = ammo;
        }
    }
    // The pause and stats screen (part 16) is the game's alone: the modern HUD steps aside.
    const bool paused = g_partSeen[16] + 2 >= g_frame;
    const bool want = street && g_cfg.modern && v.valid && !paused && !g_switchHold;

    // GTA2DX9_HUD_TEST=1: the [hud] keys modern, test_health and test_clock are re-read once a
    // second, so a script switches and pokes by editing the ini (no key the game might take).
    bool pokeHealth = false, pokeClock = false;
    static int lastModern = -1, lastHealth = -1, lastClock = 0;
    if (g_cfg.test && (g_frame % 30) == 0 && ViewModes().devIniPath[0]) {
        const char* ini = ViewModes().devIniPath;
        const int modern = GetPrivateProfileIntA("hud", "modern", 1, ini);
        if (modern != lastModern) { if (lastModern >= 0) { g_cfg.modern = modern != 0; Log("hud3d: ini: %s HUD", g_cfg.modern ? "modern" : "classic"); } lastModern = modern; }
        const int health = GetPrivateProfileIntA("hud", "test_health", -1, ini);
        if (health != lastHealth) { pokeHealth = health >= 0; lastHealth = health; }
        const int clock = GetPrivateProfileIntA("hud", "test_clock", 0, ini);
        if (clock != lastClock) { pokeClock = clock > lastClock; lastClock = clock; }
        // FIX-HUD-4: test_game_brief=1 leaves every brief to the game (its own subtitle box: the
        // mini-map's lift over it can be checked on any brief).
        g_testGameBrief = GetPrivateProfileIntA("hud", "test_game_brief", 0, ini) != 0;
        g_testMoney = GetPrivateProfileIntA("hud", "test_money", -1, ini);   // FIX-HUD-5: the money's digits, gap and pop
        // FIX-HUD-4: test_respect=a,b,c sets the player's respect with the first three gangs in use.
        static char lastRespect[64] = {};
        char respect[64] = {};
        GetPrivateProfileStringA("hud", "test_respect", "", respect, sizeof respect, ini);
        if (respect[0] && strcmp(respect, lastRespect) != 0) {
            int r[3] = {0, 0, 0};
            const int n = sscanf(respect, "%d,%d,%d", &r[0], &r[1], &r[2]);
            int set = 0;
            GTA2_TRY {
                const uintptr_t pool = *reinterpret_cast<const uintptr_t*>(kGangPool);
                for (int i = 0; pool > 0x10000 && i < 10 && set < n; ++i) {
                    uint8_t* g = reinterpret_cast<uint8_t*>(pool + i * 0x144);
                    if (!g[0]) continue;
                    g[0x11C] = static_cast<uint8_t>(static_cast<int8_t>((std::max)(-100, (std::min)(100, r[set]))));
                    ++set;
                }
            } GTA2_EXCEPT {}
            static int misses = 0;
            if (set > 0 || ++misses <= 2) Log("hud3d: test: respect %s set on %d gangs", respect, set);
            if (set > 0) strncpy(lastRespect, respect, sizeof lastRespect - 1);   // before the level: tried again
        }
    }
    if (g_cfg.test && want) {
        if (pokeHealth) {
            GTA2_TRY { *reinterpret_cast<int16_t*>(static_cast<uint8_t*>(const_cast<void*>(ViewPlayer().ped)) + 0x216) = static_cast<int16_t>(lastHealth); } GTA2_EXCEPT {}
            Log("hud3d: test: player health set to %d", lastHealth);
        }
        if (pokeClock) {
            int slot = -1;
            GTA2_TRY {
                const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(kHudObject);
                if (hud > 0x10000) {
                    typedef int(__attribute__((thiscall)) * AddTimer)(void* self, int seconds);
                    slot = reinterpret_cast<AddTimer>(kAddTimer)(reinterpret_cast<void*>(hud + kHudCounters), 75);
                }
            } GTA2_EXCEPT { slot = -2; }
            Log("hud3d: test: a 75 s clock added through the game's own call (slot %d)", slot);
        }
    }

    // The brief is ours only when its text is known.
    // Which brief the game's subtitle block shows this frame (pm15): its glyph signature's key,
    // or, for a signature not seen before, the buffer's key unless that key already belongs to
    // another text (a stale lookup): then the block stays the game's own.
    if (g_briefSigFrame == g_frame && g_briefGlyphs >= 4) {
        const auto it = g_briefBySig.find(g_briefSig);
        if (it != g_briefBySig.end()) {
            g_briefKey = it->second;
        } else {
            LoadGxt();
            std::string key = ReadMessageKey();
            bool stale = key.empty() || !g_gxt.count(key);
            for (const auto& e : g_briefBySig) stale = stale || e.second == key;
            g_briefKey = stale ? std::string() : key;
            if (g_briefBySig.size() > 256) g_briefBySig.clear();
            g_briefBySig[g_briefSig] = g_briefKey;
            Log("hud3d: brief: a new subtitle block (%d glyphs) bound to key '%s'%s", g_briefGlyphsAll, key.c_str(),
                stale ? " (stale or unknown: the game draws it)" : "");
        }
    } else if (g_partSeen[10] + 2 < g_frame) {
        g_briefKey.clear();
    }
    if (g_testGameBrief) g_briefKey.clear();
    g_briefResolved = want && !g_briefKey.empty();
    // What this frame's game HUD pass was swallowed by (pm7-classic-to-third-switch-shows-both-huds-overlaid).
    const bool wasActive = g_active;
    g_active = want;
    // The objective markers stand in for the game's arrows (swallowed in any street view), so
    // they are drawn with the modern HUD off too.
    const bool markersWant = street && g_cfg.markers && v.valid && !paused;
    static float markerFade = 0.0f;
    UpdateAimHud(want, static_cast<float>(width), static_cast<float>(height), dt);   // QB-6

    Anim& an = g_anim;
    an.time += dt;
    // QB-17/18: the panels step aside while a beat holds the screen.
    const float beatHide = street ? Beat().hudHide : 0.0f;
    // The HUD cuts between the game's and ours (pm7): the game's parts are swallowed from the
    // frame after `want` turns on (this frame's were already drawn), so ours appears then, at
    // full strength; when it turns off the game's parts come back next frame, so ours is drawn
    // this last frame (its parts were swallowed) and is gone the next. Never both, never neither.
    // A death beat (WASTED, BUSTED) hides it entirely: the game's corner parts are gone then too
    // (Hud3dSwallow), so a faint panel at the screen's edge would be the only HUD left (pm10).
    const bool deathBeat = street && (Beat().kind == BeatKind::Wasted || Beat().kind == BeatKind::Busted);
    const float hideFactor = deathBeat ? 1.0f : 0.92f;
    const float fadeWant = 1.0f - hideFactor * beatHide;
    if (want && !wasActive) {
        an.fade = 0.0f;
        an.cutIn = true;
    } else if (want && an.cutIn) {
        an.fade = fadeWant;
        an.briefAlpha = g_briefResolved && g_partSeen[10] + 2 >= g_frame ? 1.0f : 0.0f;
        an.cutIn = false;
    } else if (want) {
        an.fade += (fadeWant - an.fade) * (1.0f - std::exp(-dt * 8.0f));
    } else if (!wasActive) {
        an.fade = 0.0f;
    }
    if (!want && !wasActive && an.fade < 0.01f) {
        an.fade = 0.0f;
        an.money = -1;
        an.lastMoney = -1;
        an.lastHealth = -1;
    }

    markerFade += ((markersWant ? 1.0f - hideFactor * beatHide : 0.0f) - markerFade) * (1.0f - std::exp(-dt * 8.0f));
    if (!markersWant && markerFade < 0.01f) markerFade = 0.0f;
    const bool markersShown = markerFade > 0.01f && v.valid;

    const bool beatShown = street && Beat().kind != BeatKind::None;
    // FIX-HUD-8 (pmw2): the quit prompt's card, in fast, out fast (the game drops it the frame Esc is let go).
    const bool quitWant = street && g_quitFrame + 2 >= g_frame;
    g_quitAlpha = quitWant ? (std::min)(1.0f, g_quitAlpha + dt / 0.12f) : (std::max)(0.0f, g_quitAlpha - dt / 0.1f);
    const bool quitShown = g_quitAlpha > 0.01f && street;
    if (((an.fade > 0.01f && v.valid) || beatShown || markersShown || quitShown) && device && width > 0 && height > 0 && EnsureContext(device, height)) {
        ImGuiContext* previous = ImGui::GetCurrentContext();
        ImGui::SetCurrentContext(g_ctx);
        if (g_fontHeight != height || g_glyphs.gen != HudGameFontGeneration()) BuildFonts(height);
        if (g_cfg.minimap && g_cfg.modern) BuildMap(device, map);
        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(static_cast<float>(width), static_cast<float>(height));
        io.DeltaTime = dt > 0 ? dt : 1.0f / 30.0f;
        ImGui_ImplDX9_NewFrame();
        ImGui::NewFrame();
        if (markersShown)   // under the HUD's panels, over the world
            DrawObjectiveMarkers(ImGui::GetForegroundDrawList(), v, static_cast<float>(width), static_cast<float>(height), markerFade);
        if (an.fade > 0.01f && v.valid)
            Draw(ImGui::GetForegroundDrawList(), device, v, static_cast<float>(width), static_cast<float>(height), dt);
        if (beatShown) DrawBeat(ImGui::GetForegroundDrawList(), static_cast<float>(width), static_cast<float>(height));
        if (quitShown) DrawQuit(ImGui::GetForegroundDrawList(), static_cast<float>(width), static_cast<float>(height), g_quitAlpha);
        ImGui::EndFrame();
        ImGui::Render();
        LARGE_INTEGER q0, q1;
        QueryPerformanceCounter(&q0);
        ImGui_ImplDX9_RenderDrawData(ImGui::GetDrawData());
        QueryPerformanceCounter(&q1);
        g_mapStats.renderTicks += q1.QuadPart - q0.QuadPart;
        if (ImDrawData* dd = ImGui::GetDrawData()) {
            g_mapStats.vtx += dd->TotalVtxCount;
            int cmds = 0;
            for (int i = 0; i < dd->CmdListsCount; ++i) cmds += dd->CmdLists[i]->CmdBuffer.Size;
            g_mapStats.cmds += cmds;
            ++g_mapStats.renders;
        }
        ImGui::SetCurrentContext(previous);
    }

    // The values once every two seconds, for reading a run back against the game's own line.
    if (want && g_frame - g_lastLog >= 60) {
        g_lastLog = g_frame;
        Log("hud3d: money=%d shown=%.0f mult=%d lives=%d health=%d wanted=%d weapon=%s(%d) ammo=%d car=%d timer=%d counter=%d cargun=%d "
            "msg=%s brief=%d(%s) portrait=%.0fx%.0f icon=%.0fx%.0f arrows=%zu parts=%s%s%s%s%s",
            v.money, an.money, v.mult, v.lives, v.health, v.wanted, WeaponName(v.weapon), v.weapon, v.ammo, v.carDamage,
            v.timerTicks, v.counter, v.carWeapon, v.messageKey.c_str(), g_briefResolved ? 1 : 0, g_briefKey.c_str(),
            g_portrait.maxX - g_portrait.minX, g_portrait.maxY - g_portrait.minY,
            g_weaponIcon.maxX - g_weaponIcon.minX, g_weaponIcon.maxY - g_weaponIcon.minY, v.arrows.size(),
            g_partSeen[1] + 1 >= g_frame ? "1" : "", g_partSeen[4] + 1 >= g_frame ? ",4" : "", g_partSeen[6] + 1 >= g_frame ? ",6" : "",
            g_partSeen[10] + 1 >= g_frame ? ",10" : "", g_partSeen[11] + 1 >= g_frame ? ",11" : "");
    }

    // FIX-HUD-4: the respect meters and the mini-map's geometry every two seconds.
    static uint32_t respectLog = 0;
    if (want && g_frame - respectLog >= 60) {
        respectLog = g_frame;
        char gl[256] = {};
        int off = 0;
        for (const Gang& g : v.gangs)
            off += snprintf(gl + off, sizeof gl - off > 0 ? sizeof gl - off : 0, " %s:%d(c%d)", g.name[0] ? g.name : "?", g.respect, g.colour);
        const double f = g_mapStats.frames ? static_cast<double>(g_mapStats.frames) : 1.0;
        const double msPer = 1000.0 / static_cast<double>(g_qpf.QuadPart) / f;
        Log("hud3d: respect meters drawn=%d gangs:%s | mini-map rects=%.0f clipped=%.0f a frame (%d frames); ms a frame: map %.3f respect %.3f render %.3f (%lld vertices, %lld draw commands a frame)",
            g_respectDrawn, gl, g_mapStats.rects / f, g_mapStats.clipped / f, g_mapStats.frames,
            g_mapStats.ticks * msPer, g_mapStats.respectTicks * msPer, g_mapStats.renderTicks * msPer,
            g_mapStats.renders ? g_mapStats.vtx / g_mapStats.renders : 0, g_mapStats.renders ? g_mapStats.cmds / g_mapStats.renders : 0);
        g_mapStats = MapDrawStats{};
    }

    // The markers every two seconds: arrows in range, pins drawn (lifted over a wall; blocked when
    // no lift cleared it), edge chevrons, and the game's arrow sprites swallowed.
    static uint32_t markerLog = 0;
    if (street && g_frame - markerLog >= 60) {
        markerLog = g_frame;
        const Arrow* nearest = nullptr;
        float nd = 1e9f;
        for (const Arrow& ar : v.arrows) {
            const float d = std::hypot(ar.x - v.x, ar.y - v.y);
            if (d < nd) { nd = d; nearest = &ar; }
        }
        if (g_markerStats.hit)
            Log("hud3d: markers: nearest's sight line %.2f,%.2f,%.2f -> %.2f,%.2f,%.2f first walled at %.2f,%.2f,%.2f",
                g_markerStats.hitFrom[0], g_markerStats.hitFrom[1], g_markerStats.hitFrom[2], g_markerStats.hitTo[0], g_markerStats.hitTo[1], g_markerStats.hitTo[2],
                g_markerStats.hitAt[0], g_markerStats.hitAt[1], g_markerStats.hitAt[2]);
        Log("hud3d: markers: view=%s modern=%d slots=%zu (nearest kind %d at %.1f,%.1f,%.1f, %.1f blocks) frames: arrows=%d pins=%d lifted=%d blocked=%d edges=%d; game arrow sprites swallowed=%d",
            CurrentViewMode() == ViewMode::FirstPerson ? "first" : "third", g_cfg.modern ? 1 : 0, v.arrows.size(),
            nearest ? nearest->kind : -1, nearest ? nearest->x : 0.0f, nearest ? nearest->y : 0.0f, nearest ? nearest->z : 0.0f, nearest ? nd : 0.0f,
            g_markerStats.arrows, g_markerStats.pins, g_markerStats.lifted, g_markerStats.blocked, g_markerStats.edges, g_markerSwallowed);
        g_markerStats = MarkerStats{};
        g_markerSwallowed = 0;
    }

    QueryPerformanceCounter(&t1);
    if (want) {
        const double ms = static_cast<double>(t1.QuadPart - t0.QuadPart) * 1000.0 / g_qpf.QuadPart;
        g_costSum += ms;
        g_costWorst = (std::max)(g_costWorst, ms);
        if (++g_costFrames >= 300) {
            Log("hud3d: modern HUD %.3f ms a frame on average, worst %.3f ms (%d frames)", g_costSum / g_costFrames, g_costWorst, g_costFrames);
            g_costSum = g_costWorst = 0;
            g_costFrames = 0;
        }
    }
    ++g_frame;
}

}  // namespace gta2dx9
