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
#include <backends/imgui_impl_dx9.h>

#include "../../src/gta2_map.h"
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

namespace gta2dx9 {
namespace {

// ---- Settings ---------------------------------------------------------------------------

struct Config {
    bool loaded = false;
    bool modern = true;     // [hud] modern
    bool minimap = true;    // [hud] minimap
    int toggleKey = 0;      // [hud] toggle_key, 0 none
    float scale = 1.0f;     // [hud] scale_pct / 100
    bool test = false;      // GTA2DX9_HUD_TEST=1: [hud] modern/test_health/test_clock re-read live
};
Config g_cfg;

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
Capture g_weaponIcon, g_portrait;
Capture g_weaponBuild, g_portraitBuild;
bool g_active = false;                // the modern HUD is on screen (decides the swallowing)
bool g_briefResolved = false;         // this frame's brief has text of ours

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

struct Arrow { int type; float x, y; };

struct Values {
    bool valid = false;
    bool inVehicle = false;
    int money = -1, mult = -1, lives = -1, health = -1, wanted = 0;
    int weapon = 0, ammo = 0;
    int carDamage = -1;
    int timerTicks = -1;          // the first running clock
    int counter = -1;             // the first counter's value
    std::string messageKey;
    std::vector<Arrow> arrows;
    float x = 0, y = 0, dirX = 0, dirY = 1;
};

Values ReadValues() {
    Values v;
    const PlayerState& p = ViewPlayer();
    if (!p.valid || !p.ped) return v;
    v.valid = true;
    v.inVehicle = p.inVehicle;
    v.x = p.x; v.y = p.y; v.dirX = p.dirX; v.dirY = p.dirY;
    v.money = GameSaveMoney();
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
        if (p.inVehicle && p.vehicle) v.carDamage = *reinterpret_cast<const int16_t*>(static_cast<const uint8_t*>(p.vehicle) + 0x74);
        const char* buf = reinterpret_cast<const char*>(kMessageKey);
        for (int n = 0; n < 8 && buf[n] > 0x20 && buf[n] < 0x7F; ++n) v.messageKey.push_back(buf[n]);
        const uintptr_t hud = *reinterpret_cast<const uintptr_t*>(kHudObject);
        if (hud > 0x10000) {
            for (int i = 0; i < 4; ++i) {
                const uint8_t* slot = reinterpret_cast<const uint8_t*>(hud + kHudCounters + i * 12);
                const int32_t ticks = *reinterpret_cast<const int32_t*>(slot);
                const int32_t* value = *reinterpret_cast<const int32_t* const*>(slot + 4);
                if (ticks >= 0 && v.timerTicks < 0) v.timerTicks = ticks;
                else if (ticks < 0 && value && game::PlausiblePointer(value) && v.counter < 0) v.counter = *value;
            }
            const uint8_t* arrows = reinterpret_cast<const uint8_t*>(hud + kHudArrows);
            for (int i = 0; i < 17; ++i) {
                const uint8_t* slot = arrows + i * 0x7C;
                const int32_t type = *reinterpret_cast<const int32_t*>(slot + 0x20);
                const int32_t kind = *reinterpret_cast<const int32_t*>(slot + 0x40);
                const int32_t fx = *reinterpret_cast<const int32_t*>(slot + 0x44);
                const int32_t fy = *reinterpret_cast<const int32_t*>(slot + 0x48);
                if ((type == 0 && kind == 0) || (fx == 0 && fy == 0)) continue;
                v.arrows.push_back({type, fx / 16384.0f, fy / 16384.0f});
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
    float moneyPx = 0, heavyPx = 0, labelPx = 0, textPx = 0;
};

ImGuiContext* g_ctx = nullptr;
IDirect3DDevice9* g_device = nullptr;
Fonts g_fonts;
int g_fontHeight = 0;
float g_u = 1.0f;     // one unit: a pixel of a 720-line screen

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
    io.Fonts->Build();
    ImGui_ImplDX9_InvalidateDeviceObjects();   // the font texture is made again on NewFrame
    g_fontHeight = height;
    Log("hud3d: fonts baked for %d lines (%.0f/%.0f/%.0f/%.0f px)", height, g_fonts.moneyPx, g_fonts.heavyPx,
        g_fonts.labelPx, g_fonts.textPx);
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

void DrawCapture(ImDrawList* dl, IDirect3DDevice9* device, const Capture& c, ImVec2 a, ImVec2 b, float alpha) {
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
                     Fade(IM_COL32_WHITE, alpha));
}

// ---- The mini-map's picture -----------------------------------------------------------

IDirect3DTexture9* g_mapTex = nullptr;
const void* g_mapKey = nullptr;
size_t g_mapBlocks = 0;

void BuildMap(IDirect3DDevice9* device, const gta2::Map& map) {
    const void* key = map.Empty() ? nullptr : &map.ColumnAt(0, 0);
    if (!key) return;
    if (g_mapTex && key == g_mapKey && map.BlockCount() == g_mapBlocks) return;
    if (!g_mapTex && FAILED(device->CreateTexture(gta2::kMapWidth, gta2::kMapHeight, 1, 0, D3DFMT_A8R8G8B8,
                                                   D3DPOOL_MANAGED, &g_mapTex, nullptr))) {
        g_mapTex = nullptr;
        return;
    }
    D3DLOCKED_RECT lr;
    if (FAILED(g_mapTex->LockRect(0, &lr, nullptr, 0))) return;
    int roads = 0;
    for (int y = 0; y < gta2::kMapHeight; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
        for (int x = 0; x < gta2::kMapWidth; ++x) {
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
            uint32_t c = 0xFF0C0F14;                              // nothing: the edge of the world
            if (type == 1) { c = 0xFF5E6676; ++roads; }           // road
            else if (type == 2) c = level <= 2 ? 0xFF353B47 : 0xFF2A2F3A;   // pavement / low roofs
            else if (type == 3) c = 0xFF1F3326;                   // field, park
            else if (type == 0) c = 0xFF1A1E27;                   // a lid of air: roofs, decks
            if (type >= 0 && level >= 4 && type != 1) {
                const int lift = (std::min)(level - 3, 4) * 5;     // taller buildings a shade lighter
                c += (lift << 16) | (lift << 8) | lift;
            }
            row[x] = c;
        }
    }
    g_mapTex->UnlockRect(0);
    g_mapKey = key;
    g_mapBlocks = map.BlockCount();
    Log("hud3d: mini-map built from the level (%d road cells)", roads);
}

// ---- QB-50: pickup labels and score pops in the world ----------------------------------
//
// Over each floating pickup within kLabelFar blocks of the eye, its name ("SHOTGUN",
// "POWER-UP": which power-up a token's colour is is not mapped) on a small dark pill, fading
// out with distance. A money gain floats "+$n" up from the player (in first person, a little
// ahead of the eye) and fades; a weapon picked up (its ammo rising) floats its name up from
// the pickup he walked over (else from him). The pickups and the projection come from
// map_objects.cpp, read back from the frame the street views drew. Labels are not tested
// against walls: one behind a building within the range still shows (kept short for that).

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
            for (char& c : name) c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
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
        for (const PickupSpot* p : order) {
            float sx, sy;
            if (!MapObjectsProject(p->x, p->y + 0.22f, p->z, &sx, &sy)) continue;
            if (sx < -0.05f || sx > 1.05f || sy < -0.05f || sy > 1.05f) continue;
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
        for (const PickupSpot& p : MapObjectPickups()) nearest = (std::min)(nearest, p.eyeDistance);
        Log("hud3d: world layer: pickups drawn=%zu (nearest %.2f from the eye) labelled=%d (peak %d, %d frames with a label) pops money=%d weapon=%d live=%zu",
            MapObjectPickups().size(), nearest, labelled, w.labelledPeak, w.labelFrames, w.moneyPops, w.weaponPops, w.pops.size());
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

void Draw(ImDrawList* dl, IDirect3DDevice9* device, const Values& v, float W, float H, float dt) {
    Anim& an = g_anim;
    const float A = an.fade;
    const float u = g_u;
    const float margin = 28.0f * u;

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
    if (v.money >= 0) {
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
    {
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

    // The weapon: the game's own icon on a glass card, its name and the ammunition.
    if (v.weapon > 0) {
        const float h = 54.0f * u, w = 200.0f * u;
        const ImVec2 a(right - w, y), b(right, y + h);
        Panel(dl, a, b, A);
        const bool icon = g_weaponIcon.frame + 1 >= g_frame && g_weaponIcon.texture;
        if (icon) {
            const float iw = g_weaponIcon.maxX - g_weaponIcon.minX, ih = g_weaponIcon.maxY - g_weaponIcon.minY;
            const float fit = (std::min)((h - 10 * u) / ih, 96.0f * u / iw);
            const ImVec2 ia(a.x + 10 * u, a.y + (h - ih * fit) * 0.5f);
            DrawCapture(dl, device, g_weaponIcon, ia, ImVec2(ia.x + iw * fit, ia.y + ih * fit), A);
        }
        char ammo[24];
        if (v.ammo < 0) snprintf(ammo, sizeof ammo, "INF");
        else snprintf(ammo, sizeof ammo, "%d", (v.ammo + 9) / 10);
        const ImVec2 as = Measure(g_fonts.heavy, g_fonts.heavyPx, ammo);
        Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(b.x - 10 * u - as.x, a.y + 4 * u), v.ammo >= 0 && v.ammo < 50 ? kRed : kWhite, ammo, A);
        std::string name = WeaponName(v.weapon);
        for (char& c : name) c = c == '_' ? ' ' : static_cast<char>(toupper(static_cast<unsigned char>(c)));
        const ImVec2 ns = Measure(g_fonts.label, g_fonts.labelPx, name.c_str());
        Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(b.x - 10 * u - ns.x, b.y - ns.y - 4 * u), Fade(kWhite, 0.8f), name.c_str(), A);
        y = b.y + 10 * u;
    }

    // The clock and the counter, top centre.
    {
        float cy = margin;
        if (v.timerTicks >= 0) {
            const int secs = (v.timerTicks + 29) / 30;
            char t[16];
            snprintf(t, sizeof t, "%d:%02d", secs / 60, secs % 60);
            const ImVec2 s = Measure(g_fonts.money, g_fonts.moneyPx * 0.85f, t);
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
            Text(dl, g_fonts.money, g_fonts.moneyPx * 0.85f, ImVec2(a.x + 44 * u, a.y + 4 * u), urgent ? Mix(kWhite, kRed, blink) : kWhite, t, A);
            cy = b.y + 8 * u;
        }
        if (v.counter >= 0) {
            char t[24];
            snprintf(t, sizeof t, "%d", v.counter);
            const ImVec2 s = Measure(g_fonts.heavy, g_fonts.heavyPx, t);
            const ImVec2 ls = Measure(g_fonts.label, g_fonts.labelPx, "COUNT");
            const float w = s.x + ls.x + 34 * u, h = s.y + 6 * u;
            const ImVec2 a(W * 0.5f - w * 0.5f, cy), b(W * 0.5f + w * 0.5f, cy + h);
            Panel(dl, a, b, A, kYellow);
            Text(dl, g_fonts.label, g_fonts.labelPx, ImVec2(a.x + 14 * u, a.y + (h - ls.y) * 0.5f), Fade(kWhite, 0.75f), "COUNT", A);
            Text(dl, g_fonts.heavy, g_fonts.heavyPx, ImVec2(b.x - 10 * u - s.x, a.y + 3 * u), kWhite, t, A);
        }
    }

    // The mini-map, bottom left, turned with the camera; health (and the car) under it.
    const float mapW = 260.0f * u, mapH = 160.0f * u;
    const float barH = 8.0f * u;
    const ImVec2 m0(margin, H - margin - barH - 6 * u - mapH), m1(margin + mapW, H - margin - barH - 6 * u);
    float yaw = 0, pitch = 0;
    ViewCameraAngles(&yaw, &pitch);
    const float yr = yaw * 0.017453293f;
    const float cs = std::cos(yr), sn = std::sin(yr);
    // game offset -> map screen offset: right = (cos, sin), forward = (sin, -cos)
    const ImVec2 mc((m0.x + m1.x) * 0.5f, m0.y + mapH * 0.62f);
    const float wantZoom = v.inVehicle ? 64.0f : 34.0f;
    an.zoom += (wantZoom - an.zoom) * (1.0f - std::exp(-dt * 1.5f));
    const float scale = mapW / an.zoom;   // pixels per block
    auto toScreen = [&](float gx, float gy) {
        const float dx = gx - v.x, dy = gy - v.y;
        const float r = dx * cs + dy * sn, f = dx * sn - dy * cs;
        return ImVec2(mc.x + r * scale, mc.y - f * scale);
    };
    if (g_cfg.minimap) {
        dl->AddRectFilled(ImVec2(m0.x - 3 * u, m0.y - 3 * u), ImVec2(m1.x + 3 * u, m1.y + 3 * u), Fade(IM_COL32(0, 0, 0, 170), A), 6 * u);
        if (g_mapTex) {
            ImVec2 uv[4];
            const ImVec2 corner[4] = {m0, ImVec2(m1.x, m0.y), m1, ImVec2(m0.x, m1.y)};
            for (int i = 0; i < 4; ++i) {
                const float r = (corner[i].x - mc.x) / scale, f = -(corner[i].y - mc.y) / scale;
                const float gx = v.x + r * cs + f * sn, gy = v.y + r * sn - f * cs;
                uv[i] = ImVec2(gx / gta2::kMapWidth, gy / gta2::kMapHeight);
            }
            dl->AddImageQuad(reinterpret_cast<ImTextureID>(g_mapTex), corner[0], corner[1], corner[2], corner[3],
                             uv[0], uv[1], uv[2], uv[3], Fade(IM_COL32_WHITE, A * 0.92f));
        }
        dl->PushClipRect(m0, m1, true);
        // Blips: phones small and cyan, the job's own arrows yellow and larger; off the map
        // they sit on its edge as a chevron.
        for (const Arrow& ar : v.arrows) {
            const bool phone = ar.type >= 1 && ar.type <= 4;
            ImVec2 p = toScreen(ar.x, ar.y);
            const ImVec2 inner(m0.x + 9 * u, m0.y + 9 * u), outer(m1.x - 9 * u, m1.y - 9 * u);
            const bool off = p.x < inner.x || p.x > outer.x || p.y < inner.y || p.y > outer.y;
            if (off && phone) continue;
            if (off) {
                const float dx = p.x - mc.x, dy = p.y - mc.y;
                const float t = (std::min)({dx > 0 ? (outer.x - mc.x) / dx : dx < 0 ? (inner.x - mc.x) / dx : 1e9f,
                                            dy > 0 ? (outer.y - mc.y) / dy : dy < 0 ? (inner.y - mc.y) / dy : 1e9f});
                p = ImVec2(mc.x + dx * t, mc.y + dy * t);
                const float ang = std::atan2(dy, dx);
                const float r = 9 * u;
                dl->AddTriangleFilled(ImVec2(p.x + std::cos(ang) * r, p.y + std::sin(ang) * r),
                                      ImVec2(p.x + std::cos(ang + 2.4f) * r, p.y + std::sin(ang + 2.4f) * r),
                                      ImVec2(p.x + std::cos(ang - 2.4f) * r, p.y + std::sin(ang - 2.4f) * r), Fade(kYellow, A));
                continue;
            }
            const float r = (phone ? 4.0f : 6.5f) * u;
            dl->AddCircleFilled(p, r + 1.5f * u, Fade(kShadow, A));
            dl->AddCircleFilled(p, r, Fade(phone ? kCyan : kYellow, A));
            if (!phone) dl->AddCircle(p, r + (3.0f + 4.0f * std::fmod(an.time, 1.0f)) * u, Fade(kYellow, A * (1.0f - std::fmod(an.time, 1.0f))), 20, 1.5f * u);
        }
        // The player: an arrow along his heading, as the camera sees it.
        const float heading = std::atan2(v.dirX, -v.dirY);
        const float a = heading - yr;
        const float r = 9.0f * u;
        const ImVec2 fwd(std::sin(a), -std::cos(a)), side(std::cos(a), std::sin(a));
        const ImVec2 tip(mc.x + fwd.x * r, mc.y + fwd.y * r);
        const ImVec2 l(mc.x - fwd.x * r * 0.7f - side.x * r * 0.75f, mc.y - fwd.y * r * 0.7f - side.y * r * 0.75f);
        const ImVec2 rr(mc.x - fwd.x * r * 0.7f + side.x * r * 0.75f, mc.y - fwd.y * r * 0.7f + side.y * r * 0.75f);
        const ImVec2 back(mc.x - fwd.x * r * 0.3f, mc.y - fwd.y * r * 0.3f);
        dl->AddTriangleFilled(tip, l, back, Fade(kWhite, A));
        dl->AddTriangleFilled(tip, back, rr, Fade(kWhite, A));
        dl->AddLine(tip, l, Fade(kShadow, A), 1.2f * u);
        dl->AddLine(tip, rr, Fade(kShadow, A), 1.2f * u);
        // North, on the rim.
        {
            const float dx = -sn, dy = -cs;   // game north (0,-1) on the map: r = -sin, f = cos
            const float t = (std::min)(std::fabs((mapW * 0.5f - 12 * u) / (std::fabs(dx) + 1e-4f)),
                                       std::fabs((dy < 0 ? (mc.y - m0.y - 12 * u) : (m1.y - mc.y - 12 * u)) / (std::fabs(dy) + 1e-4f)));
            const ImVec2 np(mc.x + dx * t, mc.y + dy * t);
            dl->AddCircleFilled(np, 8 * u, Fade(IM_COL32(20, 22, 28, 230), A));
            const ImVec2 ns = Measure(g_fonts.label, g_fonts.labelPx * 0.8f, "N");
            dl->AddText(g_fonts.label, g_fonts.labelPx * 0.8f, ImVec2(np.x - ns.x * 0.5f, np.y - ns.y * 0.5f), Fade(kWhite, A), "N");
        }
        dl->PopClipRect();
        dl->AddRect(ImVec2(m0.x - 1, m0.y - 1), ImVec2(m1.x + 1, m1.y + 1), Fade(IM_COL32(255, 255, 255, 60), A), 4 * u, 0, 1.0f * u);
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
        if (up && v.messageKey != an.briefKey) {
            an.briefKey = v.messageKey;
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
    // QB-50: under the panels (the background list is drawn first).
    DrawWorldLayer(ImGui::GetBackgroundDrawList(), v, A, W, H, dt);
}

}  // namespace

bool Hud3dActive() { return g_active; }

bool Hud3dSwallow(bool hud, int part, const void* texture, const void* corners, int count) {
    if (!hud || part < 0 || part > 18) return false;
    g_partSeen[part] = g_frame;
    const Corner* k = static_cast<const Corner*>(corners);
    if (k && texture) {
        if (part == 1) {
            float minX = k[0].x, maxX = k[0].x;
            for (int i = 1; i < count; ++i) { minX = (std::min)(minX, k[i].x); maxX = (std::max)(maxX, k[i].x); }
            if (maxX - minX >= 24.0f) Note(&g_weaponIcon, texture, k, count);   // not a digit of the score (12x22)
        }
        else if (part == 10) Note(&g_portrait, texture, k, count);
    }
    if (!g_active) return false;
    switch (part) {
        case 1:    // score, lives, multiplier, weapon and ammo
        case 4:    // the row of icons centred at the top: the wanted heads
        case 6:    // the hearts
        case 11:   // the clocks and counters
            return true;
        case 10:   // the talking head, when the brief's text is ours to show
            return g_briefResolved;
        default:
            return false;
    }
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
    const bool street = worldLoaded && ViewCameraActive() && CurrentViewMode() != ViewMode::Classic;
    Values v = street && g_cfg.modern ? ReadValues() : Values{};
    // The pause and stats screen (part 16) is the game's alone: the modern HUD steps aside.
    const bool paused = g_partSeen[16] + 2 >= g_frame;
    const bool want = street && g_cfg.modern && v.valid && !paused;

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
    if (want) {
        LoadGxt();
        // Briefs have numeric keys (3230, 1619...); the buffer also holds the pause screen's
        // and the zone names' keys ("ganga7"), which are not a talking head's words.
        bool numeric = !v.messageKey.empty();
        for (char c : v.messageKey) numeric = numeric && c >= '0' && c <= '9';
        g_briefResolved = numeric && g_gxt.count(v.messageKey) != 0;
    } else {
        g_briefResolved = false;
    }
    g_active = want;

    Anim& an = g_anim;
    an.time += dt;
    an.fade += ((want ? 1.0f : 0.0f) - an.fade) * (1.0f - std::exp(-dt * 8.0f));
    if (!want && an.fade < 0.01f) {
        an.fade = 0.0f;
        an.money = -1;
        an.lastMoney = -1;
        an.lastHealth = -1;
    }

    if (an.fade > 0.01f && v.valid && device && width > 0 && height > 0 && EnsureContext(device, height)) {
        ImGuiContext* previous = ImGui::GetCurrentContext();
        ImGui::SetCurrentContext(g_ctx);
        if (g_fontHeight != height) BuildFonts(height);
        if (g_cfg.minimap) BuildMap(device, map);
        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(static_cast<float>(width), static_cast<float>(height));
        io.DeltaTime = dt > 0 ? dt : 1.0f / 30.0f;
        ImGui_ImplDX9_NewFrame();
        ImGui::NewFrame();
        Draw(ImGui::GetForegroundDrawList(), device, v, static_cast<float>(width), static_cast<float>(height), dt);
        ImGui::EndFrame();
        ImGui::Render();
        ImGui_ImplDX9_RenderDrawData(ImGui::GetDrawData());
        ImGui::SetCurrentContext(previous);
    }

    // The values once every two seconds, for reading a run back against the game's own line.
    if (want && g_frame - g_lastLog >= 60) {
        g_lastLog = g_frame;
        Log("hud3d: money=%d shown=%.0f mult=%d lives=%d health=%d wanted=%d weapon=%s(%d) ammo=%d car=%d timer=%d counter=%d "
            "msg=%s brief=%d portrait=%.0fx%.0f icon=%.0fx%.0f arrows=%zu parts=%s%s%s%s%s",
            v.money, an.money, v.mult, v.lives, v.health, v.wanted, WeaponName(v.weapon), v.weapon, v.ammo, v.carDamage,
            v.timerTicks, v.counter, v.messageKey.c_str(), g_briefResolved ? 1 : 0,
            g_portrait.maxX - g_portrait.minX, g_portrait.maxY - g_portrait.minY,
            g_weaponIcon.maxX - g_weaponIcon.minX, g_weaponIcon.maxY - g_weaponIcon.minY, v.arrows.size(),
            g_partSeen[1] + 1 >= g_frame ? "1" : "", g_partSeen[4] + 1 >= g_frame ? ",4" : "", g_partSeen[6] + 1 >= g_frame ? ",6" : "",
            g_partSeen[10] + 1 >= g_frame ? ",10" : "", g_partSeen[11] + 1 >= g_frame ? ",11" : "");
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
