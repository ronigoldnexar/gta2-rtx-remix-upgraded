// CITYMAP-1: the full city map, the waypoint and the GPS route. See city_map.h and docs/citymap.md.
//
// The level's surfaces and its drivable/walkable graphs are built once a level (city_route.cpp);
// the map's picture is baked off the render thread into one texture (8 pixels a cell, mipmapped)
// and drawn through Dear ImGui in a context of our own, in the HUD's screen-space UI pass (which
// RTX Remix rasterises over the path-traced frame, never traces). Everything else (the route,
// the markers, the labels, the frame) is vectors drawn at the output's resolution.
//
// Routing: the waypoint is snapped onto the main strongly connected road network; one backward
// Dijkstra from it gives every node's cost to the waypoint and its next hop, so following,
// leaving and rejoining the route never searches again: a re-route is a walk down next hops from
// wherever he is now (throttled; logged). The search is redone only when the waypoint, the level
// or his mode (in a car / on foot) changes.
#include "city_map.h"

#include <d3d9.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <imgui.h>

#include "../../src/gta2_map.h"
#include "beats.h"
#include "city_route.h"
#include "compat.h"
#include "debug_overlay.h"
#include "hud3d.h"
#include "live_geometry.h"
#include "log.h"
#include "map_objects.h"
#include "view_modes.h"
#include "world_view.h"

#include "hud3d_font.inc"

namespace gta2dx9 {
namespace {

using namespace citymap;

// ---- settings ---------------------------------------------------------------------------

struct Config {
    bool loaded = false;
    bool enabled = true;        // [citymap] enabled
    int key = 'M';              // [citymap] key
    bool classicDisc = true;    // [citymap] classic_disc
    bool minimapRoute = true;   // [citymap] minimap_route
    bool chevrons = true;       // [citymap] chevrons
    float chevronAlpha = 0.55f; // [citymap] chevron_pct / 100
    float scrim = 0.86f;        // [citymap] scrim_pct / 100
    bool gammaFix = true;       // [citymap] gamma_fix: colours in as their 1/2.2 power (the HUD's display path squares them)
    float metres = kCityMapMetresPerBlock;   // [citymap] metres_per_block
};
Config g_cfg;

int ParseKey(const char* name) {
    if (!name || !name[0]) return 0;
    if ((name[0] == 'F' || name[0] == 'f') && name[1]) { const int n = atoi(name + 1); if (n >= 1 && n <= 24) return VK_F1 + n - 1; }
    if (!name[1]) return toupper(static_cast<unsigned char>(name[0]));
    if (name[0] == '0' && (name[1] == 'x' || name[1] == 'X')) return static_cast<int>(strtol(name, nullptr, 16));
    return 0;
}

void LoadConfig() {
    if (g_cfg.loaded) return;
    g_cfg.loaded = true;
    const char* ini = ViewModes().devIniPath;
    if (ini && ini[0]) {
        g_cfg.enabled = GetPrivateProfileIntA("citymap", "enabled", 1, ini) != 0;
        char key[16] = {};
        GetPrivateProfileStringA("citymap", "key", "M", key, sizeof key, ini);
        g_cfg.key = ParseKey(key) ? ParseKey(key) : 'M';
        g_cfg.classicDisc = GetPrivateProfileIntA("citymap", "classic_disc", 1, ini) != 0;
        g_cfg.minimapRoute = GetPrivateProfileIntA("citymap", "minimap_route", 1, ini) != 0;
        g_cfg.chevrons = GetPrivateProfileIntA("citymap", "chevrons", 1, ini) != 0;
        g_cfg.chevronAlpha = (std::max)(0, (std::min)(100, static_cast<int>(GetPrivateProfileIntA("citymap", "chevron_pct", 55, ini)))) / 100.0f;
        g_cfg.scrim = (std::max)(0, (std::min)(100, static_cast<int>(GetPrivateProfileIntA("citymap", "scrim_pct", 86, ini)))) / 100.0f;
        g_cfg.gammaFix = GetPrivateProfileIntA("citymap", "gamma_fix", 1, ini) != 0;
        char m[32] = {};
        GetPrivateProfileStringA("citymap", "metres_per_block", "", m, sizeof m, ini);
        if (m[0] && atof(m) > 0.1) g_cfg.metres = static_cast<float>(atof(m));
    }
    Log("citymap: %s, key 0x%02X, classic disc %d, mini-map route %d, chevrons %d (%.0f%%), %.2f m a block",
        g_cfg.enabled ? "on" : "off", g_cfg.key, g_cfg.classicDisc, g_cfg.minimapRoute, g_cfg.chevrons, g_cfg.chevronAlpha * 100, g_cfg.metres);
}

double Now() {
    static LARGE_INTEGER f = {};
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return static_cast<double>(c.QuadPart) / static_cast<double>(f.QuadPart);
}

// ---- the level --------------------------------------------------------------------------

Level g_level;
std::string g_levelName;      // wil, ste, bil
uint32_t g_levelSerial = 0;
HANDLE g_bakeThread = nullptr;
volatile LONG g_bakeDone = 0;
constexpr int kPpc = 8;
IDirect3DTexture9* g_tex = nullptr;

struct Label { std::string name; float x, y, area; bool district; };
std::vector<Label> g_labels;

std::string Upper(std::string s) { for (char& c : s) c = static_cast<char>(toupper(static_cast<unsigned char>(c))); return s; }

std::string GameText(const std::string& key) {
    std::u16string t;
    if (!Hud3dGameText(key.c_str(), &t)) return std::string();
    std::string s;
    for (char16_t c : t) {
        if (c >= 0x20 && c < 0x7F) s.push_back(static_cast<char>(c));
        else if (c == 0x2019) s.push_back('\'');
    }
    while (!s.empty() && s[0] == ' ') s.erase(0, 1);
    return s;
}

// The picture in DXT1 (8:1 against ARGB: 2.7 MB with its mips instead of 21 MB): at 2560x1440 the device's
// video memory budget under Wine is nearly spent by the frame's own targets, and an ARGB map texture
// pushed ImGui's buffers (the modern HUD's too) out of it. Flat map colours survive DXT1 well.
std::vector<std::vector<uint8_t>> g_dxt;   // level 0.. (4x4 and up), each the level's blocks
uint16_t To565(int r, int g, int b) { return static_cast<uint16_t>(((r * 31 + 127) / 255) << 11 | ((g * 63 + 127) / 255) << 5 | ((b * 31 + 127) / 255)); }
void From565(uint16_t c, int* r, int* g, int* b) { *r = ((c >> 11) & 31) * 255 / 31; *g = ((c >> 5) & 63) * 255 / 63; *b = (c & 31) * 255 / 31; }
void EncodeDxt1(const std::vector<uint32_t>& px, int size, std::vector<uint8_t>* out) {
    const int nb = size / 4;
    out->assign(static_cast<size_t>(nb) * nb * 8, 0);
    for (int by = 0; by < nb; ++by)
        for (int bx = 0; bx < nb; ++bx) {
            int rgb[16][3];
            int lo = 0, hi = 0, lmin = 1 << 30, lmax = -1;
            for (int i = 0; i < 16; ++i) {
                const uint32_t v = px[static_cast<size_t>(by * 4 + i / 4) * size + bx * 4 + i % 4];
                rgb[i][0] = (v >> 16) & 255; rgb[i][1] = (v >> 8) & 255; rgb[i][2] = v & 255;
                const int l = rgb[i][0] * 2 + rgb[i][1] * 5 + rgb[i][2];
                if (l < lmin) { lmin = l; lo = i; }
                if (l > lmax) { lmax = l; hi = i; }
            }
            uint16_t c0 = To565(rgb[hi][0], rgb[hi][1], rgb[hi][2]), c1 = To565(rgb[lo][0], rgb[lo][1], rgb[lo][2]);
            uint32_t idx = 0;
            if (c0 == c1) {
                if (c0 > 0) --c1; else ++c0;   // four-colour mode needs c0 > c1; every texel takes index 0 (c0's colour)
                if (c0 < c1) std::swap(c0, c1);
                // keep the exact colour on the endpoint that matches it
                const uint16_t want = To565(rgb[hi][0], rgb[hi][1], rgb[hi][2]);
                idx = want == c0 ? 0u : 0x55555555u;
            } else {
                if (c0 < c1) std::swap(c0, c1);
                int pal[4][3];
                From565(c0, &pal[0][0], &pal[0][1], &pal[0][2]);
                From565(c1, &pal[1][0], &pal[1][1], &pal[1][2]);
                for (int k = 0; k < 3; ++k) { pal[2][k] = (2 * pal[0][k] + pal[1][k]) / 3; pal[3][k] = (pal[0][k] + 2 * pal[1][k]) / 3; }
                for (int i = 0; i < 16; ++i) {
                    int best = 0, bd = 1 << 30;
                    for (int p = 0; p < 4; ++p) {
                        const int dr = rgb[i][0] - pal[p][0], dg = rgb[i][1] - pal[p][1], db = rgb[i][2] - pal[p][2];
                        const int d = dr * dr * 2 + dg * dg * 4 + db * db;
                        if (d < bd) { bd = d; best = p; }
                    }
                    idx |= static_cast<uint32_t>(best) << (2 * i);
                }
            }
            uint8_t* o = &(*out)[(static_cast<size_t>(by) * nb + bx) * 8];
            o[0] = c0 & 255; o[1] = c0 >> 8; o[2] = c1 & 255; o[3] = c1 >> 8;
            o[4] = idx & 255; o[5] = (idx >> 8) & 255; o[6] = (idx >> 16) & 255; o[7] = idx >> 24;
        }
}

DWORD WINAPI BakeThread(LPVOID) {
    const double t0 = Now();
    std::vector<uint32_t> cur, nxt;
    g_level.Bake(kPpc, false, &cur);   // texels reach the screen as they are (only vertex colours are squared)
    g_level.cells.Clear();
    std::vector<std::vector<uint8_t>> levels;
    int size = kW * kPpc;
    while (size >= 4) {
        levels.emplace_back();
        EncodeDxt1(cur, size, &levels.back());
        const int half = size / 2;
        if (half < 4) break;
        nxt.assign(static_cast<size_t>(half) * half, 0);
        for (int y = 0; y < half; ++y)
            for (int x = 0; x < half; ++x) {
                const uint32_t q[4] = {cur[static_cast<size_t>(2 * y) * size + 2 * x], cur[static_cast<size_t>(2 * y) * size + 2 * x + 1],
                                       cur[static_cast<size_t>(2 * y + 1) * size + 2 * x], cur[static_cast<size_t>(2 * y + 1) * size + 2 * x + 1]};
                uint32_t o = 0xFF000000u;
                for (int sh = 0; sh < 24; sh += 8) { uint32_t v = 0; for (uint32_t w : q) v += (w >> sh) & 255; o |= ((v + 2) / 4) << sh; }
                nxt[static_cast<size_t>(y) * half + x] = o;
            }
        cur.swap(nxt);
        size = half;
    }
    size_t bytes = 0;
    for (const auto& l : levels) bytes += l.size();
    g_dxt.swap(levels);
    Log("citymap: map picture baked (%dx%d, DXT1 %zu levels %.1f MB, %.0f ms, off the render thread)", kW * kPpc, kH * kPpc, g_dxt.size(),
        bytes / 1048576.0, (Now() - t0) * 1000.0);
    InterlockedExchange(&g_bakeDone, 1);
    return 0;
}

void BuildLabels() {
    g_labels.clear();
    struct Acc { std::string name; float bx, by, ba, area; bool district; };
    std::vector<Acc> acc;
    for (const Zone& z : g_level.Zones()) {
        const bool district = z.type == 1 || (z.type == 15 && !z.key.empty() && (z.key[0] == 'm' || z.key[0] == 'M'));
        const bool landmark = z.type == 15 && !district;
        if (!district && !landmark) continue;
        const std::string name = GameText(z.key);
        if (name.empty()) continue;
        Acc* a = nullptr;
        for (Acc& e : acc) if (e.name == name && e.district == district) a = &e;
        if (!a) { acc.push_back({name, 0, 0, -1, 0, district}); a = &acc.back(); }
        const float area = static_cast<float>(z.w * z.h);
        a->area += area;
        if (area > a->ba) { a->ba = area; a->bx = z.x + z.w * 0.5f; a->by = z.y + z.h * 0.5f; }
    }
    for (const Acc& a : acc) g_labels.push_back({a.name, a.bx, a.by, a.area, a.district});
    std::sort(g_labels.begin(), g_labels.end(), [](const Label& a, const Label& b) {
        if (a.district != b.district) return a.district;
        return a.area > b.area;
    });
}

std::string DistrictAt(float x, float y) {
    const std::string k = g_level.DistrictKeyAt(static_cast<int>(x), static_cast<int>(y));
    return k.empty() ? std::string() : GameText(k);
}

std::string LandmarkAt(float x, float y) {
    std::string best;
    int ba = 1 << 30;
    for (const Zone& z : g_level.Zones()) {
        if (z.type != 15 || z.key.empty() || z.key[0] == 'm' || z.key[0] == 'M') continue;
        if (x < z.x || y < z.y || x >= z.x + z.w || y >= z.y + z.h || z.w * z.h >= ba) continue;
        const std::string t = GameText(z.key);
        if (!t.empty()) { best = t; ba = z.w * z.h; }
    }
    return best;
}

// ---- the route --------------------------------------------------------------------------

struct Route {
    bool active = false;
    float clickX = 0, clickY = 0;     // where he asked for it
    int goal[2] = {-1, -1};           // car, walk
    int fieldMode = -1;               // the mode dist/next were searched for
    std::vector<float> dist;
    std::vector<int> next;
    std::vector<int> path;
    float hop = 0, hopX = 0, hopY = 0;   // a dashed hop from him to the network
    // the full lines of the current path: the road's middle (raw and rounded) and the lane's own
    std::vector<float> cx, cy, fx, fy, lx, ly, lz, lcum;
    int laneSeg = 0;                  // the lane segment he was last seen along
    float laneS = 0;                  // his distance along the lane line
    float offLine = 0;
    double lastTick = 0, offSince = -1, lastReroute = -10, arrivedAt = -1;
    int reroutes = 0;
};
Route g_route;
bool g_open = false;
bool g_escLatch = false;      // the map was closed by Escape: the game keeps not seeing keys until it is let go
LONG volatile g_wheel = 0;
// The buttons from the window procedures: a scripted click (or a quick tap) can be shorter than a frame.
LONG volatile g_lDown = 0, g_lUp = 0, g_rDown = 0;
LONG g_seenLDown = 0, g_seenLUp = 0, g_seenRDown = 0;
DWORD g_lastButtonTick[3] = {};

struct PlayerNow { bool valid = false, inCar = false; float x = 0, y = 0, z = 0, heading = NAN; };
PlayerNow g_me;

std::string DistanceText(float blocks) {
    const float m = blocks * g_cfg.metres;
    char b[32];
    if (m >= 1000.0f) snprintf(b, sizeof b, "%.2f KM", m / 1000.0f);
    else snprintf(b, sizeof b, "%d M", static_cast<int>(std::lround(m / 10.0f) * 10));
    return b;
}

void RebuildLines() {
    Route& r = g_route;
    const Mode m = static_cast<Mode>(r.fieldMode);
    std::vector<float> rz;
    g_level.Polyline(r.path, m == kCar, m, &r.cx, &r.cy, &rz);
    Fillet(r.cx, r.cy, 1.4f, 5, &r.fx, &r.fy);
    g_level.Polyline(r.path, false, m, &r.lx, &r.ly, &r.lz);
    r.lcum.assign(r.lx.size(), 0.0f);
    for (size_t k = 1; k < r.lx.size(); ++k) r.lcum[k] = r.lcum[k - 1] + std::hypot(r.lx[k] - r.lx[k - 1], r.ly[k] - r.ly[k - 1]);
    r.laneSeg = 0;
    r.laneS = 0;
}

void Reroute(const char* why) {
    Route& r = g_route;
    const Mode m = static_cast<Mode>(r.fieldMode);
    int start = g_level.StartNode(g_me.x, g_me.y, g_me.z, g_me.heading, m, r.dist);
    r.hop = 0;
    if (start < 0) {
        start = g_level.NearestReaching(g_me.x, g_me.y, g_me.z, r.dist, &r.hop);
        if (start >= 0) { r.hopX = g_level.Nodes()[start].x + 0.5f; r.hopY = g_level.Nodes()[start].y + 0.5f; }
    }
    r.path = g_level.Path(start, r.next);
    RebuildLines();
    r.lastReroute = Now();
    r.offSince = -1;
    ++r.reroutes;
    const float len = Length(r.cx, r.cy);
    Log("citymap: route (%s) %s from %.1f,%.1f,%.1f: %zu nodes, %s%s", why, m == kCar ? "car" : "walk", g_me.x, g_me.y, g_me.z,
        r.path.size(), DistanceText(len).c_str(), r.hop > 0 ? " (off the network: a dashed hop to it)" : "");
    // the lane's corners (for scripted drivers and the log reader): x,y,level each
    std::string corners;
    for (size_t k = 0; k < r.lx.size() && k < 80; ++k) {
        char c[40];
        snprintf(c, sizeof c, "%s%.1f,%.1f,%.1f", k ? " " : "", r.lx[k], r.ly[k], r.lz[k]);
        corners += c;
    }
    Log("citymap: route lane %s", corners.c_str());
}

void SearchField(Mode m) {
    Route& r = g_route;
    const double t0 = Now();
    if (r.goal[m] < 0) r.goal[m] = g_level.Snap(r.clickX, r.clickY, -1.0f, m, 40, true);
    g_level.CostTo(r.goal[m], m, &r.dist, &r.next);
    r.fieldMode = m;
    int reached = 0;
    for (float d : r.dist) reached += d < 1e29f;
    Log("citymap: %s search from the waypoint: %d nodes reach it (%.1f ms)", m == kCar ? "car" : "walk", reached, (Now() - t0) * 1000.0);
    Reroute(m == kCar ? "in a car" : "on foot");
}

void ClearWaypoint(const char* why) {
    if (!g_route.active) return;
    g_route = Route();
    Log("citymap: waypoint cleared (%s)", why);
}

void SetWaypoint(float x, float y) {
    if (!g_level.Ready()) return;
    const int car = g_level.Snap(x, y, -1.0f, kCar, 40, true);
    if (car < 0) { Log("citymap: no road near %.1f,%.1f: no waypoint", x, y); return; }
    g_route = Route();
    Route& r = g_route;
    r.active = true;
    r.clickX = x; r.clickY = y;
    r.goal[kCar] = car;
    r.goal[kWalk] = g_level.Snap(x, y, -1.0f, kWalk, 40, true);
    const Node& n = g_level.Nodes()[car];
    Log("citymap: waypoint at %.1f,%.1f (%s%s%s): road %d,%d level %d", x, y, DistrictAt(x, y).c_str(),
        LandmarkAt(x, y).empty() ? "" : ", ", LandmarkAt(x, y).c_str(), n.x, n.y, n.z);
    if (g_me.valid) SearchField(g_me.inCar ? kCar : kWalk);
}

// He is followed along the lane line: the nearest point on its segments a little behind to well
// ahead of where he was last seen (a route that comes back near itself never jumps ahead).
void TrackLane() {
    Route& r = g_route;
    if (r.lx.size() < 2) { r.offLine = r.lx.empty() ? 1e9f : std::hypot(r.lx[0] - g_me.x, r.ly[0] - g_me.y); return; }
    const int n = static_cast<int>(r.lx.size());
    const int k0 = (std::max)(1, r.laneSeg - 2), k1 = (std::min)(n - 1, r.laneSeg + 40);
    float bd = 1e30f; int bk = r.laneSeg < 1 ? 1 : r.laneSeg; float bt = 0;
    for (int k = k0; k <= k1; ++k) {
        const float ax = r.lx[k - 1], ay = r.ly[k - 1], dx = r.lx[k] - ax, dy = r.ly[k] - ay, L2 = dx * dx + dy * dy;
        float t = L2 > 1e-9f ? ((g_me.x - ax) * dx + (g_me.y - ay) * dy) / L2 : 0.0f;
        t = (std::max)(0.0f, (std::min)(1.0f, t));
        const float h = r.lz[k - 1] + (r.lz[k] - r.lz[k - 1]) * t;
        const float d = std::hypot(ax + dx * t - g_me.x, ay + dy * t - g_me.y) + (std::fabs(h - g_me.z) > 1.5f ? 10.0f : 0.0f);
        if (d < bd) { bd = d; bk = k; bt = t; }
    }
    r.laneSeg = bk;
    r.laneS = r.lcum[bk - 1] + (r.lcum[bk] - r.lcum[bk - 1]) * bt;
    r.offLine = bd;
}

void UpdateRoute() {
    Route& r = g_route;
    if (!r.active || !g_level.Ready() || !g_me.valid) return;
    const Mode m = g_me.inCar ? kCar : kWalk;
    if (r.fieldMode != m) SearchField(m);
    const double now = Now();
    TrackLane();
    if (now - r.lastTick < 0.2) return;
    r.lastTick = now;
    if (r.arrivedAt < 0) {
        const int goal = r.goal[m];
        if (goal >= 0) {
            const Node& g = g_level.Nodes()[goal];
            if (std::hypot(g.x + 0.5f - g_me.x, g.y + 0.5f - g_me.y) < 2.5f && std::fabs(g.z + 1 - g_me.z) < 1.6f) {
                r.arrivedAt = now;
                Log("citymap: arrived at the waypoint (%d reroutes on the way)", r.reroutes);
            }
        }
    }
    if (r.arrivedAt >= 0) {
        if (now - r.arrivedAt > 3.5) ClearWaypoint("arrived");
        return;
    }
    const float limit = m == kCar ? 2.6f : 2.2f;
    if (r.hop > 0 && r.offLine > limit) return;   // still making his way to the network: the hop shows it
    if (r.offLine > limit) {
        if (r.offSince < 0) r.offSince = now;
        if (now - r.offSince > 0.6 && now - r.lastReroute > 0.5) {
            char why[64];
            snprintf(why, sizeof why, "off the route by %.1f blocks", r.offLine);
            Reroute(why);
        }
    } else {
        r.offSince = -1;
    }
}

// ---- danger: what the open map must not hide for long ----------------------------------

struct Danger { int health = -1, lastHealth = -1, stars = 0; double hurtAt = -10; };
Danger g_danger;

void ReadDanger() {
    const PlayerState& p = ViewPlayer();
    if (!p.valid || !p.ped) { g_danger.lastHealth = -1; return; }
    int health = -1, cop = 0;
    GTA2_TRY {
        const uint8_t* ped = static_cast<const uint8_t*>(p.ped);
        health = *reinterpret_cast<const int16_t*>(ped + 0x216);
        cop = *reinterpret_cast<const int16_t*>(ped + 0x20A);
    } GTA2_EXCEPT { health = -1; }
    if (health < 0) return;
    if (g_danger.lastHealth >= 0 && health < g_danger.lastHealth) {
        g_danger.hurtAt = Now();
        if (g_open) Log("citymap: hurt while the map is open (health %d -> %d)", g_danger.lastHealth, health);
    }
    g_danger.lastHealth = health;
    g_danger.health = health;
    static const int kStar[6] = {600, 1600, 3000, 5000, 8000, 12000};
    int s = 0;
    while (s < 6 && cop >= kStar[s]) ++s;
    g_danger.stars = s;
}

// ---- the ImGui context ------------------------------------------------------------------

ImGuiContext* g_ctx = nullptr;
IDirect3DDevice9* g_device = nullptr;
int g_fontHeight = 0;
float g_u = 1.0f;
struct Fonts { ImFont *title = nullptr, *big = nullptr, *district = nullptr, *label = nullptr, *text = nullptr; float titlePx, bigPx, districtPx, labelPx, textPx; };
Fonts g_f;

// ---- our own ImGui renderer -------------------------------------------------------------
//
// Not imgui_impl_dx9: that one needs a dynamic vertex and index buffer and its font texture in
// D3DPOOL_DEFAULT, and under Wine at 2560x1440 the device reports no texture memory left (the HD tiles
// stream in until it is spent): CreateVertexBuffer fails with D3DERR_OUTOFVIDEOMEMORY and that backend
// silently draws nothing (measured: cm_probe1440b; the modern HUD's frames show it too). Here the
// vertices go up with DrawIndexedPrimitiveUP from system memory and the textures are MANAGED, so the
// map draws whatever the device's budget. The states are imgui_impl_dx9's (an orthographic projection
// with Z writes off: RTX Remix takes the draws as UI and rasterises them over the traced frame).
IDirect3DTexture9* g_fontTex = nullptr;
struct UiVertex { float x, y, z; D3DCOLOR col; float u, v; };
constexpr DWORD kUiFvf = D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1;

void MakeFontTexture() {
    ImGuiIO& io = ImGui::GetIO();
    unsigned char* pixels = nullptr;
    int w = 0, h = 0;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &w, &h);
    if (g_fontTex) { g_fontTex->Release(); g_fontTex = nullptr; }
    if (!g_device || !pixels) return;
    if (FAILED(g_device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_fontTex, nullptr)) || !g_fontTex) {
        Log("citymap: the font texture could not be made (%dx%d)", w, h);
        g_fontTex = nullptr;
        return;
    }
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(g_fontTex->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < h; ++y) {
            const unsigned char* src = pixels + static_cast<size_t>(y) * w * 4;
            uint32_t* dst = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + static_cast<size_t>(y) * lr.Pitch);
            for (int x = 0; x < w; ++x)
                dst[x] = (static_cast<uint32_t>(src[x * 4 + 3]) << 24) | (static_cast<uint32_t>(src[x * 4]) << 16) |
                         (static_cast<uint32_t>(src[x * 4 + 1]) << 8) | src[x * 4 + 2];
        }
        g_fontTex->UnlockRect(0);
    }
    io.Fonts->SetTexID(reinterpret_cast<ImTextureID>(g_fontTex));
}

void SetupUiState(IDirect3DDevice9* d, const ImDrawData* dd) {
    D3DVIEWPORT9 vp = {0, 0, static_cast<DWORD>(dd->DisplaySize.x), static_cast<DWORD>(dd->DisplaySize.y), 0.0f, 1.0f};
    d->SetViewport(&vp);
    d->SetPixelShader(nullptr);
    d->SetVertexShader(nullptr);
    d->SetFVF(kUiFvf);
    d->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    d->SetRenderState(D3DRS_SHADEMODE, D3DSHADE_GOURAUD);
    d->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    d->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    d->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    d->SetRenderState(D3DRS_ZENABLE, FALSE);
    d->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    d->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    d->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    d->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    d->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, TRUE);
    d->SetRenderState(D3DRS_SRCBLENDALPHA, D3DBLEND_ONE);
    d->SetRenderState(D3DRS_DESTBLENDALPHA, D3DBLEND_INVSRCALPHA);
    d->SetRenderState(D3DRS_SCISSORTESTENABLE, TRUE);
    d->SetRenderState(D3DRS_FOGENABLE, FALSE);
    d->SetRenderState(D3DRS_RANGEFOGENABLE, FALSE);
    d->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    d->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    d->SetRenderState(D3DRS_CLIPPING, TRUE);
    d->SetRenderState(D3DRS_LIGHTING, FALSE);
    d->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    d->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    d->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    d->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    d->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    d->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    d->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
    d->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    d->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    d->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    d->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    d->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    d->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR);   // the map's mips (the font has one level)
    d->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    d->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    const float L = dd->DisplayPos.x + 0.5f, R = dd->DisplayPos.x + dd->DisplaySize.x + 0.5f;
    const float T = dd->DisplayPos.y + 0.5f, B = dd->DisplayPos.y + dd->DisplaySize.y + 0.5f;
    D3DMATRIX id = {{{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}}};
    D3DMATRIX proj = {{{2.0f / (R - L), 0, 0, 0, 0, 2.0f / (T - B), 0, 0, 0, 0, 0.5f, 0, (L + R) / (L - R), (T + B) / (B - T), 0.5f, 1.0f}}};
    d->SetTransform(D3DTS_WORLD, &id);
    d->SetTransform(D3DTS_VIEW, &id);
    d->SetTransform(D3DTS_PROJECTION, &proj);
}

void RenderUi(IDirect3DDevice9* d, ImDrawData* dd) {
    if (!d || !dd || dd->DisplaySize.x <= 0 || dd->DisplaySize.y <= 0 || dd->TotalVtxCount == 0) return;
    IDirect3DStateBlock9* sb = nullptr;
    if (FAILED(d->CreateStateBlock(D3DSBT_ALL, &sb)) || !sb) return;
    sb->Capture();
    D3DMATRIX w, v, p;
    d->GetTransform(D3DTS_WORLD, &w); d->GetTransform(D3DTS_VIEW, &v); d->GetTransform(D3DTS_PROJECTION, &p);
    SetupUiState(d, dd);
    static std::vector<UiVertex> verts;
    for (int n = 0; n < dd->CmdListsCount; ++n) {
        const ImDrawList* cl = dd->CmdLists[n];
        verts.resize(static_cast<size_t>(cl->VtxBuffer.Size));
        for (int i = 0; i < cl->VtxBuffer.Size; ++i) {
            const ImDrawVert& s = cl->VtxBuffer.Data[i];
            const ImU32 c = s.col;   // ABGR in memory order RGBA -> D3DCOLOR ARGB
            verts[i] = {s.pos.x, s.pos.y, 0.0f, (c & 0xFF00FF00u) | ((c & 0xFF) << 16) | ((c >> 16) & 0xFF), s.uv.x, s.uv.y};
        }
        for (int c = 0; c < cl->CmdBuffer.Size; ++c) {
            const ImDrawCmd& cmd = cl->CmdBuffer.Data[c];
            if (cmd.UserCallback) {
                if (cmd.UserCallback == ImDrawCallback_ResetRenderState) SetupUiState(d, dd);
                else cmd.UserCallback(cl, &cmd);
                continue;
            }
            if (cmd.ElemCount == 0) continue;
            const RECT r = {static_cast<LONG>(cmd.ClipRect.x - dd->DisplayPos.x), static_cast<LONG>(cmd.ClipRect.y - dd->DisplayPos.y),
                            static_cast<LONG>(cmd.ClipRect.z - dd->DisplayPos.x), static_cast<LONG>(cmd.ClipRect.w - dd->DisplayPos.y)};
            if (r.right <= r.left || r.bottom <= r.top) continue;
            d->SetScissorRect(&r);
            d->SetTexture(0, reinterpret_cast<IDirect3DTexture9*>(cmd.GetTexID()));
            const UINT nv = static_cast<UINT>(cl->VtxBuffer.Size) - cmd.VtxOffset;
            d->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, nv, cmd.ElemCount / 3, cl->IdxBuffer.Data + cmd.IdxOffset,
                                      sizeof(ImDrawIdx) == 2 ? D3DFMT_INDEX16 : D3DFMT_INDEX32, verts.data() + cmd.VtxOffset, sizeof(UiVertex));
        }
    }
    d->SetTransform(D3DTS_WORLD, &w); d->SetTransform(D3DTS_VIEW, &v); d->SetTransform(D3DTS_PROJECTION, &p);
    sb->Apply();
    sb->Release();
}

void BuildFonts(int height) {
    ImGuiIO& io = ImGui::GetIO();
    io.Fonts->Clear();
    g_u = static_cast<float>(height) / 720.0f;
    ImFontConfig cfg;
    cfg.FontDataOwnedByAtlas = false;
    cfg.OversampleH = 2;
    cfg.OversampleV = 1;
    static const ImWchar kRanges[] = {0x0020, 0x00FF, 0x2013, 0x2026, 0};
    auto add = [&](const unsigned char* data, size_t size, float px) {
        return io.Fonts->AddFontFromMemoryTTF(const_cast<unsigned char*>(data), static_cast<int>(size), px, &cfg, kRanges);
    };
    g_f.titlePx = std::round(34 * g_u); g_f.bigPx = std::round(24 * g_u); g_f.districtPx = std::round(22 * g_u);
    g_f.labelPx = std::round(15 * g_u); g_f.textPx = std::round(13.5f * g_u);
    g_f.title = add(kHudFontHeavy, sizeof kHudFontHeavy, g_f.titlePx);
    g_f.big = add(kHudFontHeavy, sizeof kHudFontHeavy, g_f.bigPx);
    g_f.district = add(kHudFontHeavy, sizeof kHudFontHeavy, g_f.districtPx);
    g_f.label = add(kHudFontBold, sizeof kHudFontBold, g_f.labelPx);
    g_f.text = add(kHudFontText, sizeof kHudFontText, g_f.textPx);
    io.Fonts->Build();
    MakeFontTexture();
    g_fontHeight = height;
}

bool EnsureContext(IDirect3DDevice9* device, int height) {
    if (g_ctx && g_device != device) return false;
    if (!g_ctx) {
        ImGuiContext* previous = ImGui::GetCurrentContext();
        g_ctx = ImGui::CreateContext();
        ImGui::SetCurrentContext(g_ctx);
        ImGuiIO& io = ImGui::GetIO();
        io.IniFilename = nullptr;
        io.LogFilename = nullptr;
        io.BackendRendererName = "gta2dx9_citymap";
        io.BackendFlags |= ImGuiBackendFlags_RendererHasVtxOffset;
        g_device = device;
        BuildFonts(height);
        ImGui::SetCurrentContext(previous);
    }
    return true;
}

// Colours as they should reach the screen (the HUD's display path squares what it is given).
int Lin(int c) { return g_cfg.gammaFix ? static_cast<int>(std::lround(255.0 * std::pow(c / 255.0, 1.0 / 2.2))) : c; }
ImU32 Col(int r, int g, int b, float a = 1.0f) {
    return IM_COL32(Lin(r), Lin(g), Lin(b), static_cast<int>((std::max)(0.0f, (std::min)(1.0f, a)) * 255.0f + 0.5f));
}
const int kWhite[3] = {244, 240, 228}, kYellow[3] = {255, 206, 32}, kCyan[3] = {64, 200, 240}, kRoute[3] = {255, 62, 170},
          kRouteHi[3] = {255, 200, 232}, kCase[3] = {40, 4, 26}, kRed[3] = {232, 52, 44};
ImU32 C3(const int c[3], float a = 1.0f) { return Col(c[0], c[1], c[2], a); }

float Advance(ImFont* f, float px, char c) {
    const ImFontGlyph* g = f->FindGlyph(static_cast<ImWchar>(static_cast<unsigned char>(c)));
    return g ? g->AdvanceX * px / f->FontSize : px * 0.4f;
}
float SpacedWidth(ImFont* f, float px, const std::string& s, float spacing) {
    float w = 0;
    for (char c : s) w += Advance(f, px, c);
    return w + spacing * (s.size() > 1 ? s.size() - 1 : 0);
}
// Text at (x, y): align 0 left, 1 centre, 2 right; vertically centred on y. edge: a dark rim round
// the glyphs (labels over the light roads); shadow: GTA2's drop to the bottom right.
void Txt(ImDrawList* dl, ImFont* f, float px, float x, float y, const std::string& s, ImU32 col, int align = 0, float spacing = 0,
         float edge = 0, bool shadow = true) {
    const float w = SpacedWidth(f, px, s, spacing);
    if (align == 1) x -= w * 0.5f;
    else if (align == 2) x -= w;
    y -= px * 0.5f;
    const float a = ((col >> IM_COL32_A_SHIFT) & 0xFF) / 255.0f;
    auto run = [&](float ox, float oy, ImU32 c) {
        float xx = x + ox;
        if (spacing == 0) { dl->AddText(f, px, ImVec2(xx, y + oy), c, s.c_str()); return; }
        for (size_t i = 0; i < s.size();) {   // glyph by glyph (UTF-8: a lead byte and its continuation bytes together)
            size_t n = 1;
            const unsigned char ch = static_cast<unsigned char>(s[i]);
            if (ch >= 0xC0) while (i + n < s.size() && (static_cast<unsigned char>(s[i + n]) & 0xC0) == 0x80) ++n;
            const std::string g = s.substr(i, n);
            dl->AddText(f, px, ImVec2(xx, y + oy), c, g.c_str());
            xx += (n == 1 ? Advance(f, px, s[i]) : f->CalcTextSizeA(px, FLT_MAX, 0.0f, g.c_str()).x) + spacing;
            i += n;
        }
    };
    if (edge > 0) {
        const ImU32 e = Col(8, 10, 14, 0.82f * a);
        for (int i = 0; i < 8; ++i) {
            const float ang = i * 0.785398f;
            run(std::cos(ang) * edge, std::sin(ang) * edge, e);
        }
    } else if (shadow) {
        const float o = (std::max)(1.0f, std::round(1.5f * g_u));
        run(o, o, Col(0, 0, 0, 0.66f * a));
    }
    run(0, 0, col);
}

void KeyCap(ImDrawList* dl, float x, float y, float h, const char* label, float* w) {
    const float tw = SpacedWidth(g_f.label, g_f.labelPx * 0.85f, label, 0);
    *w = (std::max)(h, tw + 12 * g_u);
    dl->AddRectFilled(ImVec2(x, y), ImVec2(x + *w, y + h), Col(232, 228, 216, 0.92f), 4 * g_u);
    Txt(dl, g_f.label, g_f.labelPx * 0.85f, x + *w * 0.5f, y + h * 0.5f + 0.5f, label, Col(16, 18, 24), 1, 0, 0, false);
}

void PlayerArrow(ImDrawList* dl, ImVec2 p, float heading, float r, bool halo, float a = 1.0f) {
    if (halo) {
        dl->AddCircleFilled(p, r * 2.2f, C3(kCyan, 0.16f * a), 40);
        dl->AddCircleFilled(p, r * 1.7f, C3(kCyan, 0.24f * a), 40);
    }
    const ImVec2 f(std::sin(heading), -std::cos(heading)), s(std::cos(heading), std::sin(heading));
    const ImVec2 tip(p.x + f.x * r, p.y + f.y * r);
    const ImVec2 l(p.x - f.x * r * 0.75f - s.x * r * 0.8f, p.y - f.y * r * 0.75f - s.y * r * 0.8f);
    const ImVec2 rr(p.x - f.x * r * 0.75f + s.x * r * 0.8f, p.y - f.y * r * 0.75f + s.y * r * 0.8f);
    const ImVec2 back(p.x - f.x * r * 0.3f, p.y - f.y * r * 0.3f);
    const ImVec2 pts[4] = {tip, rr, back, l};
    dl->AddPolyline(pts, 4, Col(0, 0, 0, a), ImDrawFlags_Closed, 2.4f * g_u);
    dl->AddTriangleFilled(tip, l, back, C3(kWhite, a));
    dl->AddTriangleFilled(tip, back, rr, C3(kWhite, a));
}

void Diamond(ImDrawList* dl, ImVec2 c, float r, ImU32 fill, ImU32 inner) {
    const ImVec2 o[4] = {ImVec2(c.x, c.y - r), ImVec2(c.x + r, c.y), ImVec2(c.x, c.y + r), ImVec2(c.x - r, c.y)};
    dl->AddConvexPolyFilled(o, 4, fill);
    dl->AddPolyline(o, 4, Col(0, 0, 0), ImDrawFlags_Closed, 1.6f * g_u);
    if (inner) {
        const float q = r * 0.45f;
        const ImVec2 i[4] = {ImVec2(c.x, c.y - q), ImVec2(c.x + q, c.y), ImVec2(c.x, c.y + q), ImVec2(c.x - q, c.y)};
        dl->AddConvexPolyFilled(i, 4, inner);
    }
}

void WaypointPin(ImDrawList* dl, ImVec2 p, float t) {
    const float u = g_u;
    const float ph = std::fmod(t, 1.4f) / 1.4f;
    dl->AddCircle(p, (14 + 12 * ph) * u, C3(kRoute, 0.8f * (1 - ph)), 40, 2 * u);
    const float h = 22 * u, w = 9 * u, top = p.y - h;
    dl->AddLine(p, ImVec2(p.x, top + w), Col(0, 0, 0, 0.8f), 4 * u);
    dl->AddLine(p, ImVec2(p.x, top + w), C3(kRoute), 2 * u);
    Diamond(dl, ImVec2(p.x, top), w, C3(kRoute), C3(kRouteHi));
    dl->AddCircleFilled(p, 3 * u, C3(kRoute), 12);
    dl->AddCircle(p, 3 * u, Col(0, 0, 0), 12, 1 * u);
}

// A line with GTA2's GPS look: a dark casing, the colour, and short bright dashes travelling along.
void RouteLine(ImDrawList* dl, const std::vector<ImVec2>& pts, float w, float phase, float alpha = 1.0f) {
    if (pts.size() < 2) return;
    dl->AddPolyline(pts.data(), static_cast<int>(pts.size()), C3(kCase, 0.9f * alpha), ImDrawFlags_None, w + 4 * g_u);
    dl->AddPolyline(pts.data(), static_cast<int>(pts.size()), C3(kRoute, alpha), ImDrawFlags_None, w);
    // the dashes at fixed arc lengths (k * period - phase): no float creep at a segment's end
    const float period = 22 * g_u, on = 6 * g_u;
    std::vector<float> cum(pts.size(), 0.0f);
    for (size_t k = 1; k < pts.size(); ++k) cum[k] = cum[k - 1] + std::hypot(pts[k].x - pts[k - 1].x, pts[k].y - pts[k - 1].y);
    const float total = cum.back();
    auto at = [&](float s, size_t* seg) {
        while (*seg + 1 < pts.size() - 1 && cum[*seg + 1] < s) ++*seg;
        const size_t k = *seg;
        const float L = cum[k + 1] - cum[k];
        const float t = L > 1e-6f ? (std::max)(0.0f, (std::min)(1.0f, (s - cum[k]) / L)) : 0.0f;
        return ImVec2(pts[k].x + (pts[k + 1].x - pts[k].x) * t, pts[k].y + (pts[k + 1].y - pts[k].y) * t);
    };
    size_t seg = 0;
    const int maxDashes = 4000;
    int n = 0;
    for (float s0 = -phase * period; s0 < total && n < maxDashes; s0 += period, ++n) {
        const float a0 = (std::max)(0.0f, s0), a1 = (std::min)(total, s0 + on);
        if (a1 <= a0) continue;
        size_t sa = seg;
        const ImVec2 p0 = at(a0, &sa);
        size_t sb = sa;
        const ImVec2 p1 = at(a1, &sb);
        if (sb == sa) dl->AddLine(p0, p1, C3(kRouteHi, alpha), (std::max)(1.0f, w - 2 * g_u));
        else {   // a dash round a corner
            dl->AddLine(p0, pts[sa + 1], C3(kRouteHi, alpha), (std::max)(1.0f, w - 2 * g_u));
            dl->AddLine(pts[sa + 1], p1, C3(kRouteHi, alpha), (std::max)(1.0f, w - 2 * g_u));
        }
        seg = sa;
    }
}

void DashedLine(ImDrawList* dl, ImVec2 a, ImVec2 b, ImU32 col, float w) {
    const float L = std::hypot(b.x - a.x, b.y - a.y), seg = 7 * g_u;
    for (float t = 0; t < L; t += seg * 2) {
        const float e = (std::min)(L, t + seg);
        dl->AddLine(ImVec2(a.x + (b.x - a.x) * t / L, a.y + (b.y - a.y) * t / L), ImVec2(a.x + (b.x - a.x) * e / L, a.y + (b.y - a.y) * e / L), col, w);
    }
}

// ---- the map's view and input -----------------------------------------------------------

struct View { float cx = 128, cy = 128, s = 4; float x0 = 0, y0 = 0, x1 = 0, y1 = 0; };
View g_view;
bool g_viewInit = false;
ImVec2 g_cursor(0, 0), g_lastMouse(-1, -1);
bool g_lmb = false, g_rmb = false, g_dragging = false;
ImVec2 g_dragFrom(0, 0);
float g_dragCx = 0, g_dragCy = 0;
double g_openedAt = 0;
float g_keyHold = 0;
int g_mapW = 0, g_mapH = 0;

ImVec2 ToScreen(float x, float y) {
    return ImVec2((x - g_view.cx) * g_view.s + (g_view.x0 + g_view.x1) * 0.5f, (y - g_view.cy) * g_view.s + (g_view.y0 + g_view.y1) * 0.5f);
}
void ToCell(ImVec2 p, float* x, float* y) {
    *x = (p.x - (g_view.x0 + g_view.x1) * 0.5f) / g_view.s + g_view.cx;
    *y = (p.y - (g_view.y0 + g_view.y1) * 0.5f) / g_view.s + g_view.cy;
}
float FitScale() { return (g_view.y1 - g_view.y0 - 24 * g_u) / 256.0f; }
void ClampView() {
    const float lo = FitScale(), hi = 16.0f * g_u;
    g_view.s = (std::max)(lo, (std::min)(hi, g_view.s));
    g_view.cx = (std::max)(0.0f, (std::min)(256.0f, g_view.cx));
    g_view.cy = (std::max)(0.0f, (std::min)(256.0f, g_view.cy));
}
void ZoomAt(ImVec2 p, float factor) {
    float bx, by;
    ToCell(p, &bx, &by);
    g_view.s *= factor;
    ClampView();
    float ax, ay;
    ToCell(p, &ax, &ay);
    g_view.cx += bx - ax;
    g_view.cy += by - ay;
    ClampView();
}

bool KeyDown(int vk) { return vk > 0 && (GetAsyncKeyState(vk) & 0x8000) != 0; }
struct Edge { bool down = false; };
Edge g_edges[256];
bool KeyEdge(int vk) {
    if (vk <= 0 || vk >= 256) return false;
    const SHORT st = GetAsyncKeyState(vk);
    const bool now = (st & 0x8000) != 0;
    const bool hit = now && !g_edges[vk].down;
    g_edges[vk].down = now;
    return hit;
}

void Layout(int W, int H) {
    g_view.x0 = 0;
    g_view.y0 = std::round(58 * g_u);
    g_view.x1 = static_cast<float>(W);
    g_view.y1 = static_cast<float>(H) - std::round(40 * g_u);
}

void OpenMap() {
    g_open = true;
    g_openedAt = Now();
    if (!g_viewInit) { g_view.s = FitScale() * 1.7f; g_viewInit = true; }
    g_view.cx = g_me.x; g_view.cy = g_me.y;
    ClampView();
    g_cursor = ToScreen(g_me.x, g_me.y);
    g_lastMouse = ImVec2(-1, -1);
    for (int k : {VK_LBUTTON, VK_RBUTTON, VK_RETURN, VK_SPACE, VK_DELETE, VK_BACK, VK_HOME, VK_ESCAPE}) g_edges[k].down = KeyDown(k);
    g_lmb = KeyDown(VK_LBUTTON); g_rmb = KeyDown(VK_RBUTTON);
    InterlockedExchange(&g_wheel, 0);
    Log("citymap: map opened at %.1f,%.1f (%s, %s view)", g_me.x, g_me.y, g_me.inCar ? "in a car" : "on foot",
        CurrentViewMode() == ViewMode::Classic ? "classic" : CurrentViewMode() == ViewMode::FirstPerson ? "first person" : "third person");
}
void CloseMap(const char* why) {
    if (!g_open) return;
    g_open = false;
    g_dragging = false;
    Log("citymap: map closed (%s)", why);
}

void MapInput(HWND present, int W, int H, float dt) {
    const float u = g_u;
    // the mouse, in the frame's pixels
    POINT pt;
    RECT rc;
    bool haveMouse = false;
    ImVec2 mouse(0, 0);
    if (present && GetCursorPos(&pt) && ScreenToClient(present, &pt) && GetClientRect(present, &rc) && rc.right > 0 && rc.bottom > 0) {
        mouse = ImVec2(pt.x * static_cast<float>(W) / rc.right, pt.y * static_cast<float>(H) / rc.bottom);
        haveMouse = mouse.x >= 0 && mouse.y >= 0 && mouse.x < W && mouse.y < H;
    }
    if (haveMouse && (g_lastMouse.x < 0 || std::hypot(mouse.x - g_lastMouse.x, mouse.y - g_lastMouse.y) > 0.5f)) {
        if (g_lastMouse.x >= 0) g_cursor = mouse;
        g_lastMouse = mouse;
    }
    // the keyboard cursor; at the map's edge it pushes the view
    float kx = (KeyDown(VK_RIGHT) ? 1.0f : 0.0f) - (KeyDown(VK_LEFT) ? 1.0f : 0.0f);
    float ky = (KeyDown(VK_DOWN) ? 1.0f : 0.0f) - (KeyDown(VK_UP) ? 1.0f : 0.0f);
    if (kx != 0 || ky != 0) {
        g_keyHold += dt;
        const float speed = (300.0f + 500.0f * (std::min)(1.0f, g_keyHold / 0.8f)) * u * dt;
        g_cursor.x += kx * speed;
        g_cursor.y += ky * speed;
        const float m = 48 * u;
        float px = 0, py = 0;
        if (g_cursor.x < g_view.x0 + m) { px = g_cursor.x - (g_view.x0 + m); g_cursor.x = g_view.x0 + m; }
        if (g_cursor.x > g_view.x1 - m) { px = g_cursor.x - (g_view.x1 - m); g_cursor.x = g_view.x1 - m; }
        if (g_cursor.y < g_view.y0 + m) { py = g_cursor.y - (g_view.y0 + m); g_cursor.y = g_view.y0 + m; }
        if (g_cursor.y > g_view.y1 - m) { py = g_cursor.y - (g_view.y1 - m); g_cursor.y = g_view.y1 - m; }
        g_view.cx += px / g_view.s;
        g_view.cy += py / g_view.s;
        ClampView();
    } else {
        g_keyHold = 0;
    }
    // drag to pan; a click (no drag) sets the waypoint
    const LONG ld = g_lDown, lu = g_lUp, rd = g_rDown;
    const bool downEvent = ld != g_seenLDown, upEvent = lu != g_seenLUp;
    g_seenLDown = ld; g_seenLUp = lu;
    bool lmb = KeyDown(VK_LBUTTON) || (downEvent && !upEvent);
    if (downEvent && !g_lmb) {   // a press seen only as an event: it counts as the frame's press
        if (haveMouse) { g_dragFrom = mouse; g_dragCx = g_view.cx; g_dragCy = g_view.cy; }
        g_dragging = false;
        g_lmb = true;
        if (upEvent) lmb = false;
    }
    const bool inMap = g_cursor.y > g_view.y0 && g_cursor.y < g_view.y1;
    if (lmb && !g_lmb && haveMouse) { g_dragFrom = mouse; g_dragCx = g_view.cx; g_dragCy = g_view.cy; g_dragging = false; }
    if (lmb && g_lmb && haveMouse) {
        if (!g_dragging && std::hypot(mouse.x - g_dragFrom.x, mouse.y - g_dragFrom.y) > 6 * u) g_dragging = true;
        if (g_dragging) {
            g_view.cx = g_dragCx - (mouse.x - g_dragFrom.x) / g_view.s;
            g_view.cy = g_dragCy - (mouse.y - g_dragFrom.y) / g_view.s;
            ClampView();
        }
    }
    if (!lmb && g_lmb) {
        float cxl, cyl;
        ToCell(g_cursor, &cxl, &cyl);
        Log("citymap: click at %.0f,%.0f (cell %.1f,%.1f)%s%s", g_cursor.x, g_cursor.y, cxl, cyl, g_dragging ? ", a drag" : "", inMap ? "" : ", outside the map");
        if (!g_dragging && inMap) { float x, y; ToCell(g_cursor, &x, &y); SetWaypoint(x, y); }
        g_dragging = false;
    }
    g_lmb = lmb;
    const bool rmb = KeyDown(VK_RBUTTON) || rd != g_seenRDown;
    g_seenRDown = rd;
    if (rmb && !g_rmb) ClearWaypoint("right click");
    g_rmb = rmb;
    if (KeyEdge(VK_RETURN) || KeyEdge(VK_SPACE)) { float x, y; ToCell(g_cursor, &x, &y); SetWaypoint(x, y); }
    if (KeyEdge(VK_DELETE) || KeyEdge(VK_BACK)) ClearWaypoint("delete key");
    if (KeyEdge(VK_HOME)) { g_view.cx = g_me.x; g_view.cy = g_me.y; ClampView(); g_cursor = ToScreen(g_me.x, g_me.y); }
    // zoom: the wheel at the cursor, + / - and Page Up / Down at the cursor too
    const LONG wheel = InterlockedExchange(&g_wheel, 0);
    if (wheel) ZoomAt(g_cursor, std::pow(1.25f, wheel / 120.0f));
    const bool zin = KeyDown(VK_OEM_PLUS) || KeyDown(VK_ADD) || KeyDown(VK_PRIOR);
    const bool zout = KeyDown(VK_OEM_MINUS) || KeyDown(VK_SUBTRACT) || KeyDown(VK_NEXT);
    if (zin != zout) ZoomAt(g_cursor, std::pow(2.0f, (zin ? 1.6f : -1.6f) * dt));
}

// ---- devtools (scripted tests) ----------------------------------------------------------

void PollDevtools() {
    static uint32_t polls = 0;
    const char* ini = ViewModes().devIniPath;
    if (!ini || !ini[0] || (polls++ % 15u) != 0) return;
    static char lastWay[64] = "\x01", lastOpen[16] = "\x01", lastView[64] = "\x01";
    char b[64] = {};
    GetPrivateProfileStringA("devtools", "citymap_waypoint", "", b, sizeof b, ini);
    if (strcmp(b, lastWay) != 0) {
        const bool first = lastWay[0] == '\x01';
        strncpy(lastWay, b, sizeof lastWay - 1);
        float x, y;
        if (!first && sscanf(b, "%f,%f", &x, &y) == 2) { Log("devtools: citymap_waypoint %s", b); SetWaypoint(x, y); }
        else if (!first && !strcmp(b, "clear")) ClearWaypoint("devtools");
    }
    GetPrivateProfileStringA("devtools", "citymap_open", "", b, sizeof b, ini);
    if (strcmp(b, lastOpen) != 0) {
        const bool first = lastOpen[0] == '\x01';
        strncpy(lastOpen, b, sizeof lastOpen - 1);
        if (!first && b[0] == '1' && !g_open && g_me.valid && g_level.Ready()) OpenMap();
        if (!first && b[0] == '0') CloseMap("devtools");
    }
    GetPrivateProfileStringA("devtools", "citymap_view", "", b, sizeof b, ini);
    if (strcmp(b, lastView) != 0) {
        const bool first = lastView[0] == '\x01';
        strncpy(lastView, b, sizeof lastView - 1);
        float x, y, s;
        if (!first && sscanf(b, "%f,%f,%f", &x, &y, &s) == 3) { g_view.cx = x; g_view.cy = y; g_view.s = s * g_u; g_viewInit = true; ClampView(); g_cursor = ToScreen(x, y); }
    }
}

// ---- the texture ------------------------------------------------------------------------

double g_texRetryAt = 0;
double g_closedAt = -1;
void EnsureTexture(IDirect3DDevice9* device) {
    if (g_tex || !g_bakeDone || g_dxt.empty() || !device || Now() < g_texRetryAt) return;
    const int N = kW * kPpc;
    const double t0 = Now();
    const UINT levels = static_cast<UINT>(g_dxt.size());
    // MANAGED: the runtime keeps the copy and pages it in; a full video memory budget does not refuse it
    HRESULT hr = device->CreateTexture(N, N, levels, 0, D3DFMT_DXT1, D3DPOOL_MANAGED, &g_tex, nullptr);
    if (SUCCEEDED(hr) && g_tex) {
        int size = N;
        for (UINT l = 0; l < levels; ++l, size /= 2) {
            D3DLOCKED_RECT lr;
            if (FAILED(g_tex->LockRect(l, &lr, nullptr, 0))) { hr = E_FAIL; break; }
            const int rows = size / 4, rowBytes = (size / 4) * 8;
            for (int y = 0; y < rows; ++y) memcpy(static_cast<uint8_t*>(lr.pBits) + static_cast<size_t>(y) * lr.Pitch, &g_dxt[l][static_cast<size_t>(y) * rowBytes], rowBytes);
            g_tex->UnlockRect(l);
        }
    }
    if (FAILED(hr) || !g_tex) {
        if (g_tex) { g_tex->Release(); g_tex = nullptr; }
        g_texRetryAt = Now() + 2.0;
        Log("citymap: the map texture could not be made on the device (%08lx; texture memory left %u MB); the map draws without its picture",
            static_cast<unsigned long>(hr), device->GetAvailableTextureMem() / 1048576u);
        return;
    }
    Log("citymap: map texture %dx%d DXT1, %u levels, on the device in %.0f ms (texture memory left %u MB)", N, N, levels, (Now() - t0) * 1000.0,
        device->GetAvailableTextureMem() / 1048576u);
}

void ReleaseTexture() {
    if (g_tex) { g_tex->Release(); g_tex = nullptr; }
}

// ---- the overlay ------------------------------------------------------------------------

std::string g_lastHereKey;

void DrawMap(ImDrawList* dl, int W, int H, float t) {
    const float u = g_u;
    const View& v = g_view;
    // the scrim over the running game, the level's picture in the map's band
    dl->AddRectFilled(ImVec2(0, 0), ImVec2(static_cast<float>(W), static_cast<float>(H)), Col(6, 8, 12, g_cfg.scrim));
    dl->PushClipRect(ImVec2(v.x0, v.y0), ImVec2(v.x1, v.y1), true);
    const ImVec2 e0 = ToScreen(0, 0), e1 = ToScreen(256, 256);
    if (g_tex) dl->AddImage(reinterpret_cast<ImTextureID>(g_tex), e0, e1, ImVec2(0, 0), ImVec2(1, 1), IM_COL32_WHITE);
    else {
        dl->AddRectFilled(e0, e1, Col(7, 9, 13));
        Txt(dl, g_f.big, g_f.bigPx, (e0.x + e1.x) * 0.5f, (e0.y + e1.y) * 0.5f, "DRAWING THE MAP...", C3(kWhite, 0.7f), 1, 2 * u);
    }
    dl->AddRect(e0, e1, Col(255, 255, 255, 0.16f), 0, 0, 1 * u);
    // the survey grid: every 32 cells, lettered along the top, numbered down the side
    for (int k = 1; k < 8; ++k) {
        const ImVec2 g = ToScreen(k * 32.0f, k * 32.0f);
        dl->AddLine(ImVec2(g.x, (std::max)(v.y0, e0.y)), ImVec2(g.x, (std::min)(v.y1, e1.y)), Col(255, 255, 255, 0.055f), 1 * u);
        dl->AddLine(ImVec2((std::max)(v.x0, e0.x), g.y), ImVec2((std::min)(v.x1, e1.x), g.y), Col(255, 255, 255, 0.055f), 1 * u);
    }
    for (int k = 0; k < 8; ++k) {
        const ImVec2 g = ToScreen(k * 32 + 16.0f, k * 32 + 16.0f);
        const float ly = (std::max)(v.y0, e0.y) + 12 * u, lx = (std::max)(v.x0, e0.x) + 10 * u;
        char s[4] = {static_cast<char>('A' + k), 0};
        if (g.x > v.x0 + 10 && g.x < v.x1 - 10) Txt(dl, g_f.text, g_f.textPx * 0.85f, g.x, ly, s, Col(255, 255, 255, 0.45f), 1);
        snprintf(s, sizeof s, "%d", k + 1);
        if (g.y > v.y0 + 10 && g.y < v.y1 - 10) Txt(dl, g_f.text, g_f.textPx * 0.85f, lx, g.y, s, Col(255, 255, 255, 0.45f), 0);
    }
    // district names, then landmarks once close enough to read
    std::vector<ImVec4> placed;
    auto freeBox = [&](const ImVec4& b) {
        if (b.x < v.x0 || b.z > v.x1 || b.y < v.y0 + 16 * u || b.w > v.y1) return false;
        for (const ImVec4& q : placed) if (!(b.z < q.x || q.z < b.x || b.w < q.y || q.w < b.y)) return false;
        return true;
    };
    for (const Label& l : g_labels) {
        if (!l.district) continue;
        const ImVec2 p = ToScreen(l.x, l.y);
        const float px = (13 + 7 * (std::min)(1.0f, std::sqrt(l.area) / 90.0f)) * u * (0.85f + 0.15f * (std::min)(2.0f, v.s / (2.4f * u)));
        const std::string s = Upper(l.name);
        const float sp = px * 0.12f, w = SpacedWidth(g_f.district, px, s, sp);
        const ImVec4 box(p.x - w / 2 - 4, p.y - px * 0.6f, p.x + w / 2 + 4, p.y + px * 0.6f);
        if (!freeBox(box)) continue;
        placed.push_back(box);
        Txt(dl, g_f.district, px, p.x, p.y, s, Col(236, 240, 248, 0.86f), 1, sp, 2.0f * u);
    }
    if (v.s >= 3.6f * u) {
        for (const Label& l : g_labels) {
            if (l.district) continue;
            const ImVec2 p = ToScreen(l.x, l.y);
            const std::string s = Upper(l.name);
            const float px = g_f.labelPx * 0.8f, w = SpacedWidth(g_f.label, px, s, 0);
            const ImVec4 box(p.x - 6 * u, p.y - 8 * u, p.x + 10 * u + w, p.y + 8 * u);
            if (!freeBox(box)) continue;
            placed.push_back(box);
            dl->AddRectFilled(ImVec2(p.x - 3 * u, p.y - 3 * u), ImVec2(p.x + 3 * u, p.y + 3 * u), C3(kYellow));
            dl->AddRect(ImVec2(p.x - 3 * u, p.y - 3 * u), ImVec2(p.x + 3 * u, p.y + 3 * u), Col(0, 0, 0), 0, 0, 1 * u);
            Txt(dl, g_f.label, px, p.x + 7 * u, p.y, s, Col(255, 226, 140, 0.95f), 0, 0, 1.6f * u);
        }
    }
    // the route, the hop to the network, the waypoint, him
    const Route& r = g_route;
    if (r.active && r.fx.size() >= 2) {
        std::vector<float> cx, cy;
        float off = 0;
        CutAt(r.fx, r.fy, nullptr, g_me.x, g_me.y, static_cast<int>(r.fx.size()), &cx, &cy, nullptr, &off);
        std::vector<ImVec2> sp;
        for (size_t k = 0; k < cx.size(); ++k) sp.push_back(ToScreen(cx[k], cy[k]));
        RouteLine(dl, sp, (std::max)(3.0f * u, (std::min)(6.0f * u, v.s * 0.9f)), std::fmod(t * 1.2f, 1.0f));
        if (r.hop > 0) DashedLine(dl, ToScreen(g_me.x, g_me.y), sp.front(), C3(kRoute, 0.9f), 2.5f * u);
        WaypointPin(dl, sp.back(), t);
    } else if (r.active) {
        WaypointPin(dl, ToScreen(r.clickX, r.clickY), t);
    }
    PlayerArrow(dl, ToScreen(g_me.x, g_me.y), std::isnan(g_me.heading) ? 0.0f : g_me.heading, 11 * u, true);
    // the cursor: a reticle, its cross lines, the road it would snap to and what is under it
    {
        const ImVec2 c = g_cursor;
        dl->AddLine(ImVec2(v.x0, c.y), ImVec2(v.x1, c.y), Col(255, 255, 255, 0.22f), 1 * u);
        dl->AddLine(ImVec2(c.x, v.y0), ImVec2(c.x, v.y1), Col(255, 255, 255, 0.22f), 1 * u);
        const float rr = 13 * u, a = 6 * u;
        for (int sx = -1; sx <= 1; sx += 2)
            for (int sy = -1; sy <= 1; sy += 2) {
                const ImVec2 k(c.x + sx * rr, c.y + sy * rr);
                dl->AddLine(k, ImVec2(k.x - sx * a, k.y), C3(kWhite), 2 * u);
                dl->AddLine(k, ImVec2(k.x, k.y - sy * a), C3(kWhite), 2 * u);
            }
        float x, y;
        ToCell(c, &x, &y);
        if (x >= 0 && y >= 0 && x < 256 && y < 256) {
            const int sn = g_level.Snap(x, y, -1.0f, kCar, 40, true);
            if (sn >= 0) {
                const ImVec2 s = ToScreen(g_level.Nodes()[sn].x + 0.5f, g_level.Nodes()[sn].y + 0.5f);
                dl->AddLine(c, s, Col(255, 255, 255, 0.45f), 1 * u);
                dl->AddCircle(s, 3.5f * u, C3(kRoute), 16, 2 * u);
            }
            std::string what = LandmarkAt(x, y);
            if (what.empty()) what = DistrictAt(x, y);
            const std::string lab = "SET WAYPOINT" + (what.empty() ? std::string() : "  \xC2\xB7  " + Upper(what));
            const float px = g_f.labelPx * 0.9f, w = SpacedWidth(g_f.label, px, lab, 0);
            const float bx = (std::min)(c.x + 18 * u, v.x1 - w - 24 * u), by = (std::min)(c.y + 14 * u, v.y1 - 24 * u);
            dl->AddRectFilled(ImVec2(bx, by), ImVec2(bx + w + 14 * u, by + 20 * u), Col(10, 12, 18, 0.85f), 3 * u);
            dl->AddRect(ImVec2(bx, by), ImVec2(bx + w + 14 * u, by + 20 * u), Col(255, 255, 255, 0.2f), 3 * u, 0, 1 * u);
            Txt(dl, g_f.label, px, bx + 7 * u, by + 10 * u, lab, C3(kWhite), 0, 0, 0, false);
        }
    }
    // the scale bar, bottom left of the level
    {
        const float mpp = g_cfg.metres / v.s;
        int nice = 1000;
        for (int n : {25, 50, 100, 200, 250, 500, 1000}) if (n / mpp >= 70 * u) { nice = n; break; }
        const float bl = nice / mpp, bx = (std::max)(v.x0, e0.x) + 30 * u, by = v.y1 - 22 * u;
        dl->AddRectFilled(ImVec2(bx, by - 3 * u), ImVec2(bx + bl, by), C3(kWhite, 0.8f));
        dl->AddRectFilled(ImVec2(bx, by - 3 * u), ImVec2(bx + bl / 2, by), Col(20, 22, 28, 0.86f));
        dl->AddRect(ImVec2(bx, by - 3 * u), ImVec2(bx + bl, by), C3(kWhite, 0.8f), 0, 0, 1 * u);
        char s[16];
        if (nice < 1000) snprintf(s, sizeof s, "%d M", nice); else snprintf(s, sizeof s, "1 KM");
        Txt(dl, g_f.text, g_f.textPx * 0.9f, bx, by - 13 * u, s, C3(kWhite, 0.85f));
    }
    // the legend, bottom right
    {
        const float lx = v.x1 - 196 * u, ly = v.y1 - 92 * u;
        dl->AddRectFilled(ImVec2(lx, ly), ImVec2(v.x1 - 14 * u, v.y1 - 14 * u), Col(9, 11, 16, 0.8f), 6 * u);
        dl->AddRect(ImVec2(lx, ly), ImVec2(v.x1 - 14 * u, v.y1 - 14 * u), Col(255, 255, 255, 0.16f), 6 * u, 0, 1 * u);
        const char* rows[4] = {"YOU", "WAYPOINT", "ROUTE", "ROAD  \xC2\xB7  OVERPASS"};
        for (int i = 0; i < 4; ++i) {
            const float yy = ly + 13 * u + i * 17 * u, ix = lx + 18 * u;
            if (i == 0) PlayerArrow(dl, ImVec2(ix, yy), 0, 6 * u, false);
            else if (i == 1) Diamond(dl, ImVec2(ix, yy), 6 * u, C3(kRoute), 0);
            else if (i == 2) { dl->AddLine(ImVec2(ix - 9 * u, yy), ImVec2(ix + 9 * u, yy), C3(kCase), 7 * u); dl->AddLine(ImVec2(ix - 9 * u, yy), ImVec2(ix + 9 * u, yy), C3(kRoute), 4 * u); }
            else { dl->AddRectFilled(ImVec2(ix - 9 * u, yy - 4 * u), ImVec2(ix + 9 * u, yy + 4 * u), Col(198, 203, 212)); dl->AddRectFilled(ImVec2(ix - 2 * u, yy - 6 * u), ImVec2(ix + 2 * u, yy + 6 * u), Col(110, 118, 132)); }
            Txt(dl, g_f.text, g_f.textPx * 0.95f, ix + 18 * u, yy, rows[i], C3(kWhite, 0.85f), 0, 1 * u, 0, false);
        }
    }
    dl->PopClipRect();
    // header and footer
    const float hh = v.y0, fy = v.y1;
    dl->AddRectFilled(ImVec2(0, 0), ImVec2(static_cast<float>(W), hh), Col(9, 11, 16, 0.93f));
    dl->AddRectFilled(ImVec2(0, fy), ImVec2(static_cast<float>(W), static_cast<float>(H)), Col(9, 11, 16, 0.93f));
    dl->AddLine(ImVec2(0, hh - 1 * u), ImVec2(static_cast<float>(W), hh - 1 * u), C3(kYellow, 0.8f), 2 * u);
    dl->AddLine(ImVec2(0, fy), ImVec2(static_cast<float>(W), fy), Col(255, 255, 255, 0.16f), 1 * u);
    const char* title = g_levelName == "ste" ? "RESIDENTIAL" : g_levelName == "bil" ? "INDUSTRIAL" : g_levelName == "wil" ? "DOWNTOWN" : "CITY";
    Txt(dl, g_f.title, g_f.titlePx, 22 * u, hh / 2 + 1, title, C3(kYellow), 0, 2 * u);
    const float tw = SpacedWidth(g_f.title, g_f.titlePx, title, 2 * u);
    Txt(dl, g_f.text, g_f.textPx, 22 * u + tw + 14 * u, hh / 2 - 8 * u, "CITY MAP", C3(kWhite, 0.6f), 0, 2 * u, 0, false);
    const std::string here = DistrictAt(g_me.x, g_me.y);
    if (!here.empty()) Txt(dl, g_f.text, g_f.textPx, 22 * u + tw + 14 * u, hh / 2 + 9 * u, "YOU ARE IN  " + Upper(here), C3(kWhite, 0.86f), 0, 1 * u, 0, false);
    // the danger chip: hurt in the last few seconds or wanted, so he can close the map at once
    const bool hurt = Now() - g_danger.hurtAt < 3.0;
    if (hurt || g_danger.stars > 0) {
        const float pulse = 0.65f + 0.35f * std::sin(t * 7.0f);
        std::string s = hurt ? "UNDER ATTACK" : "WANTED";
        const float px = g_f.label->FontSize * 0, w = SpacedWidth(g_f.big, g_f.bigPx * 0.7f, s, 1.5f * u) + (g_danger.stars ? g_danger.stars * 14 * u + 8 * u : 0);
        (void)px;
        const float cx = W * 0.5f, x0 = cx - (w + 80 * u) / 2, y0 = hh * 0.5f - 15 * u;
        dl->AddRectFilled(ImVec2(x0, y0), ImVec2(x0 + w + 80 * u, y0 + 30 * u), Col(kRed[0], kRed[1], kRed[2], 0.85f * pulse), 5 * u);
        Txt(dl, g_f.big, g_f.bigPx * 0.7f, x0 + 12 * u, y0 + 15 * u, s, C3(kWhite), 0, 1.5f * u);
        float sx = x0 + 12 * u + SpacedWidth(g_f.big, g_f.bigPx * 0.7f, s, 1.5f * u) + 10 * u;
        for (int i = 0; i < g_danger.stars; ++i, sx += 14 * u) {
            ImVec2 st[10];
            for (int k = 0; k < 10; ++k) {
                const float a = -1.5708f + k * 0.6283f, rr = (k & 1) ? 2.6f * u : 6.2f * u;
                st[k] = ImVec2(sx + 6 * u + std::cos(a) * rr, y0 + 15 * u + std::sin(a) * rr);
            }
            for (int k = 0; k < 10; k += 2) dl->AddTriangleFilled(ImVec2(sx + 6 * u, y0 + 15 * u), st[k], st[(k + 1) % 10], C3(kYellow));
            for (int k = 1; k < 10; k += 2) dl->AddTriangleFilled(ImVec2(sx + 6 * u, y0 + 15 * u), st[k], st[(k + 1) % 10], C3(kYellow));
        }
        float kw;
        KeyCap(dl, x0 + w + 34 * u, y0 + 5 * u, 20 * u, "M", &kw);
        Txt(dl, g_f.label, g_f.labelPx * 0.8f, x0 + w + 34 * u + kw + 4 * u, y0 + 15 * u, "", C3(kWhite));
    }
    // the GPS read-out on the right of the header
    if (r.active) {
        const float xr = W - 22 * u;
        CityMapGuide gd;
        CityMapGuideNow(&gd);
        const std::string d = gd.arrived ? "ARRIVED" : DistanceText(gd.remainingBlocks);
        Txt(dl, g_f.big, g_f.bigPx, xr, hh / 2 + 1, d, C3(kWhite), 2);
        const float dw = SpacedWidth(g_f.big, g_f.bigPx, d, 0);
        std::string dest = LandmarkAt(r.clickX, r.clickY);
        if (dest.empty()) dest = DistrictAt(r.clickX, r.clickY);
        if (dest.empty()) dest = "WAYPOINT";
        Txt(dl, g_f.text, g_f.textPx * 0.9f, xr - dw - 12 * u, hh / 2 - 8 * u, "DESTINATION", C3(kRoute), 2, 1.5f * u, 0, false);
        Txt(dl, g_f.label, g_f.labelPx, xr - dw - 12 * u, hh / 2 + 9 * u, Upper(dest), C3(kWhite), 2, 0, 0, false);
        if (gd.turnBlocks >= 0 && !gd.arrived) {
            const float lw = (std::max)(SpacedWidth(g_f.label, g_f.labelPx, Upper(dest), 0), SpacedWidth(g_f.text, g_f.textPx * 0.9f, "DESTINATION", 1.5f * u));
            const float cx = xr - dw - 12 * u - lw - 44 * u, cy = hh / 2;
            dl->AddRectFilled(ImVec2(cx - 16 * u, cy - 16 * u), ImVec2(cx + 16 * u, cy + 16 * u), C3(kRoute), 5 * u);
            const float sg = static_cast<float>(gd.turnDir);
            const ImVec2 a[3] = {ImVec2(cx - sg * 5 * u, cy + 10 * u), ImVec2(cx - sg * 5 * u, cy - 2 * u), ImVec2(cx + sg * 5 * u, cy - 2 * u)};
            dl->AddPolyline(a, 3, C3(kWhite), ImDrawFlags_None, 3.2f * u);
            dl->AddTriangleFilled(ImVec2(cx + sg * 10 * u, cy - 2 * u), ImVec2(cx + sg * 3 * u, cy - 8 * u), ImVec2(cx + sg * 3 * u, cy + 4 * u), C3(kWhite));
            Txt(dl, g_f.text, g_f.textPx * 0.9f, cx - 22 * u, cy - 8 * u, "NEXT", C3(kWhite, 0.6f), 2, 1.5f * u, 0, false);
            Txt(dl, g_f.label, g_f.labelPx, cx - 22 * u, cy + 9 * u, std::string(gd.turnDir < 0 ? "LEFT IN " : "RIGHT IN ") + DistanceText(gd.turnBlocks), C3(kWhite), 2, 0, 0, false);
        }
    }
    // the keys
    struct Hint { const char* keys[3]; const char* label; };
    const Hint hints[] = {{{"M", nullptr}, "CLOSE"}, {{"ARROWS", nullptr}, "CURSOR"}, {{"DRAG", nullptr}, "PAN"},
                          {{"WHEEL", "+", "-"}, "ZOOM"}, {{"CLICK", "ENTER", nullptr}, "SET WAYPOINT"},
                          {{"RMB", "DEL", nullptr}, "CLEAR"}, {{"HOME", nullptr}, "FIND ME"}};
    float x = 22 * u;
    const float ky = fy + (H - fy - 20 * u) / 2;
    for (const Hint& h : hints) {
        for (const char* k : h.keys) {
            if (!k) break;
            float kw;
            KeyCap(dl, x, ky, 20 * u, k, &kw);
            x += kw + 4 * u;
        }
        Txt(dl, g_f.text, g_f.textPx * 0.95f, x + 3 * u, ky + 10 * u, h.label, C3(kWhite, 0.8f), 0, 1 * u, 0, false);
        x += SpacedWidth(g_f.text, g_f.textPx * 0.95f, h.label, 1 * u) + 22 * u;
    }
}

// ---- the street views' chevrons ----------------------------------------------------------

struct ChevronStats { int drawn = 0, walled = 0, covered = 0, behind = 0; };
ChevronStats g_chev;

bool Project(float gx, float gy, float h, ImVec2* out, float* depth, int W, int H) {
    float sx, sy, d = 0;
    if (!MapObjectsProject(gx, h, static_cast<float>(gta2::kMapHeight) - gy, &sx, &sy, &d)) return false;
    *out = ImVec2(sx * W, sy * H);
    if (depth) *depth = d;
    return true;
}

void DrawChevrons(ImDrawList* dl, int W, int H, float t) {
    const Route& r = g_route;
    if (!r.active || r.arrivedAt >= 0 || r.lx.size() < 2) return;
    float eye[3], dir[3];
    if (!MapObjectsEye(eye, dir)) return;
    const float u = g_u;
    const bool first = CurrentViewMode() == ViewMode::FirstPerson;
    const PlayerState& p = ViewPlayer();
    // what stands between the eye and the road: cars (not his own from the driver's seat), people
    struct Box { float x0, y0, x1, y1, depth; };
    std::vector<Box> boxes;
    for (const CameraCar& c : LiveCameraCars()) {
        if (first && c.object == reinterpret_cast<uintptr_t>(p.vehicleSprite)) continue;
        Box b = {1e9f, 1e9f, -1e9f, -1e9f, 1e9f};
        bool any = false;
        for (int i = 0; i < 4; ++i)
            for (float y : {c.y0, c.y1}) {
                float sx, sy, d;
                if (!MapObjectsProject(c.x[i], y, c.z[i], &sx, &sy, &d)) continue;
                any = true;
                b.x0 = (std::min)(b.x0, sx * W); b.x1 = (std::max)(b.x1, sx * W);
                b.y0 = (std::min)(b.y0, sy * H); b.y1 = (std::max)(b.y1, sy * H);
                b.depth = (std::min)(b.depth, d);
            }
        if (any && b.depth > 0.8f) boxes.push_back(b);   // one round the eye (the cab he sits in) has no box worth the name
    }
    auto addFigure = [&](float x, float y, float z, float height) {
        Box b = {1e9f, 1e9f, -1e9f, -1e9f, 1e9f};
        bool any = false;
        for (float dx : {-0.2f, 0.2f})
            for (float dz : {-0.2f, 0.2f})
                for (float dy : {0.0f, height}) {
                    float sx, sy, d;
                    if (!MapObjectsProject(x + dx, y + dy, z + dz, &sx, &sy, &d)) continue;
                    any = true;
                    b.x0 = (std::min)(b.x0, sx * W); b.x1 = (std::max)(b.x1, sx * W);
                    b.y0 = (std::min)(b.y0, sy * H); b.y1 = (std::max)(b.y1, sy * H);
                    b.depth = (std::min)(b.depth, d);
                }
        if (any) boxes.push_back(b);
    };
    const float meX = p.x, meZ = static_cast<float>(gta2::kMapHeight) - p.y;
    for (const AimPed& a : LiveAimPeds()) {
        if (std::hypot(a.x - meX, a.z - meZ) < 1.2f) continue;   // himself (in the driver's seat he is drawn round the eye)
        addFigure(a.x, a.y, a.z, a.corpse ? 0.25f : 0.8f);
    }
    if (!first && !g_me.inCar && p.valid) addFigure(p.x, p.z, static_cast<float>(gta2::kMapHeight) - p.y, 0.8f);
    // the turn ahead, for the gentle pulse
    std::vector<float> cx, cy, cz;
    float off;
    CutAt(r.lx, r.ly, &r.lz, g_me.x, g_me.y, 40, &cx, &cy, &cz, &off);
    float turnAt = -1;
    {
        std::vector<float> rx, ry;
        CutAt(r.cx, r.cy, nullptr, g_me.x, g_me.y, 40, &rx, &ry, nullptr, &off);
        float td; int tdir;
        if (NextTurn(rx, ry, &td, &tdir)) turnAt = td;
    }
    // blocks: ~36 m shown; from the driver's seat they start further out (the first blocks lie under the bonnet)
    const bool seat = first && g_me.inCar;
    const float spacing = 1.25f, nearFade0 = seat ? 2.2f : 1.0f, nearFade1 = seat ? 3.4f : 2.2f, farFade0 = 6.5f, farFade1 = 9.5f;
    const float sPlayer = r.laneS;
    float s = std::ceil((sPlayer + nearFade0) / spacing) * spacing;
    int seg = (std::max)(1, r.laneSeg);
    const int n = static_cast<int>(r.lx.size());
    const float base = g_cfg.chevronAlpha;
    for (; s < sPlayer + farFade1 && s < r.lcum.back(); s += spacing) {
        while (seg < n - 1 && r.lcum[seg] < s) ++seg;
        const float L = r.lcum[seg] - r.lcum[seg - 1];
        if (L < 1e-4f) continue;
        const float k = (s - r.lcum[seg - 1]) / L;
        const float gx = r.lx[seg - 1] + (r.lx[seg] - r.lx[seg - 1]) * k, gy = r.ly[seg - 1] + (r.ly[seg] - r.ly[seg - 1]) * k;
        const float h = r.lz[seg - 1] + (r.lz[seg] - r.lz[seg - 1]) * k + 0.03f;
        const float dx = (r.lx[seg] - r.lx[seg - 1]) / L, dy = (r.ly[seg] - r.ly[seg - 1]) / L;
        const float ahead = s - sPlayer;
        auto smooth = [](float a, float b, float x) { const float q = (std::max)(0.0f, (std::min)(1.0f, (x - a) / (b - a))); return q * q * (3 - 2 * q); };
        float alpha = base * smooth(nearFade0, nearFade1, ahead) * (1.0f - smooth(farFade0, farFade1, ahead));
        if (turnAt > 0 && ahead > turnAt - 3.0f && ahead < turnAt + 1.5f && turnAt < 9.0f) alpha *= 0.85f + 0.3f * (0.5f + 0.5f * std::sin(t * 5.0f));
        if (alpha < 0.02f) continue;
        // the chevron flat on the road: tip ahead, two arms back, a block wide over all
        const float sx = -dy, sy = dx;   // to the right of the travel (map frame, y down)
        auto g = [&](float a, float b, ImVec2* o, float* d) { return Project(gx + dx * a + sx * b, gy + dy * a + sy * b, h, o, d, W, H); };
        const float S = 1.3f;
        const float A[6][2] = {{0.18f, 0}, {-0.14f, -0.30f}, {-0.26f, -0.30f}, {0.03f, 0}, {-0.26f, 0.30f}, {-0.14f, 0.30f}};
        ImVec2 q[6];
        float depth = 0, dd;
        bool ok = true;
        for (int i = 0; i < 6 && ok; ++i) { ok = g(A[i][0] * S, A[i][1] * S, &q[i], &dd); depth = (std::max)(depth, dd); }
        if (!ok) { ++g_chev.behind; continue; }
        const ImVec2 c((q[0].x + q[3].x) * 0.5f, (q[0].y + q[3].y) * 0.5f);
        // one close to the eye (a turn beside the chase camera) would sweep across the screen: by its size
        // on screen it fades out from a tenth of the frame's width and is gone at a sixth
        float sx0 = 1e9f, sx1 = -1e9f;
        for (const ImVec2& v : q) { sx0 = (std::min)(sx0, v.x); sx1 = (std::max)(sx1, v.x); }
        const float span = (sx1 - sx0) / W;
        if (span > 0.16f) { ++g_chev.behind; continue; }
        if (span > 0.10f) alpha *= 1.0f - (span - 0.10f) / 0.06f;
        if (c.x < -50 || c.y < -50 || c.x > W + 50 || c.y > H + 50) continue;
        if (ViewLineWalled(eye[0], eye[1], eye[2], gx, h + 0.15f, static_cast<float>(gta2::kMapHeight) - gy)) { ++g_chev.walled; continue; }
        bool covered = false;
        for (const Box& b : boxes)
            if (b.depth < depth - 0.3f && c.x > b.x0 && c.x < b.x1 && c.y > b.y0 && c.y < b.y1) { covered = true; break; }
        if (covered) { ++g_chev.covered; continue; }
        ++g_chev.drawn;
        const ImVec2 arm1[4] = {q[0], q[1], q[2], q[3]}, arm2[4] = {q[0], q[3], q[4], q[5]};
        const ImU32 fill = C3(kRoute, alpha), rim = C3(kRouteHi, (std::min)(1.0f, alpha * 1.25f));
        dl->AddConvexPolyFilled(arm1, 4, fill);
        dl->AddConvexPolyFilled(arm2, 4, fill);
        const ImVec2 outline[6] = {q[0], q[1], q[2], q[3], q[4], q[5]};
        dl->AddPolyline(outline, 6, rim, ImDrawFlags_Closed, (std::max)(1.0f, 1.0f * u));
    }
}

double g_lastStamp = 0;
uint32_t g_frame = 0;

void BeginFrame(int W, int H, float dt) {
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(static_cast<float>(W), static_cast<float>(H));
    io.DeltaTime = dt > 0 ? dt : 1.0f / 30.0f;
    ImGui::NewFrame();
}
void EndFrame(const char* what) {
    ImGui::EndFrame();
    ImGui::Render();
    ImDrawData* dd = ImGui::GetDrawData();
    RenderUi(g_device, dd);
    static double last[2] = {0, 0};
    const int k = what[0] == 'm' ? 0 : 1;
    const double now = Now();
    if (dd && now - last[k] > 2.0) {
        last[k] = now;
        Log("citymap: %s drawn: %d vertices, %d indices, display %.0fx%.0f; texture memory left %u MB", what, dd->TotalVtxCount, dd->TotalIdxCount,
            dd->DisplaySize.x, dd->DisplaySize.y, g_device ? g_device->GetAvailableTextureMem() / 1048576u : 0u);
    }
}

float g_dt = 1.0f / 30.0f;
float g_time = 0;

}  // namespace

// ---- the interface ------------------------------------------------------------------------

std::string CityMapDistanceText(float blocks) { return DistanceText(blocks); }

void CityMapSetLevel(const gta2::Map& map, const std::vector<uint8_t>& zones, const std::string& mapPath) {
    LoadConfig();
    if (g_bakeThread) {
        WaitForSingleObject(g_bakeThread, INFINITE);
        CloseHandle(g_bakeThread);
        g_bakeThread = nullptr;
    }
    CloseMap("level change");
    if (g_route.active) ClearWaypoint("level change");
    ReleaseTexture();
    std::vector<std::vector<uint8_t>>().swap(g_dxt);
    InterlockedExchange(&g_bakeDone, 0);
    const size_t slash = mapPath.find_last_of("\\/");
    std::string file = slash == std::string::npos ? mapPath : mapPath.substr(slash + 1);
    for (char& c : file) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
    g_levelName = file.substr(0, 3);
    if (!g_cfg.enabled || map.Empty()) return;
    const double t0 = Now();
    g_level.Build(map, zones);
    ++g_levelSerial;
    BuildLabels();
    Log("citymap: level %s: %zu surfaces, %d road; car edges %d (main network %d), walk edges %d (main %d); %zu labels; built in %.0f ms",
        g_levelName.c_str(), g_level.Nodes().size(), g_level.RoadNodes(), g_level.Edges(kCar), g_level.MainCount(kCar), g_level.Edges(kWalk),
        g_level.MainCount(kWalk), g_labels.size(), (Now() - t0) * 1000.0);
    g_bakeThread = CreateThread(nullptr, 0, BakeThread, nullptr, 0, nullptr);
    if (!g_bakeThread) BakeThread(nullptr);
}

void CityMapNoteWheel(int delta) { if (g_open) InterlockedExchangeAdd(&g_wheel, delta); }

void CityMapNoteButton(int button, bool down) {
    if (!g_open || button < 0 || button > 1) return;
    // the present window passes its mouse messages on to the game's window: the same press arrives twice
    const int slot = button == 0 ? (down ? 0 : 1) : 2;
    const DWORD now = GetTickCount();
    if (now - g_lastButtonTick[slot] < 40) return;
    g_lastButtonTick[slot] = now;
    static int logged = 0;
    if (logged++ < 40) Log("citymap: mouse %s %s", button == 0 ? "left" : "right", down ? "down" : "up");
    if (button == 0) InterlockedIncrement(down ? &g_lDown : &g_lUp);
    else if (down) InterlockedIncrement(&g_rDown);
}

bool CityMapOpen() { return g_open; }

void CityMapUpdate(IDirect3DDevice9* device, int width, int height, HWND presentWindow, bool worldLoaded) {
    LoadConfig();
    const double now = Now();
    g_dt = g_lastStamp > 0 ? static_cast<float>((std::min)(0.1, now - g_lastStamp)) : 1.0f / 30.0f;
    g_lastStamp = now;
    g_time += g_dt;
    ++g_frame;
    if (!g_cfg.enabled) return;
    const PlayerState& p = ViewPlayer();
    g_me.valid = worldLoaded && p.valid;
    if (g_me.valid) {
        g_me.inCar = p.inVehicle;
        g_me.x = p.x; g_me.y = p.y; g_me.z = p.z;
        g_me.heading = p.facingKnown ? std::atan2(p.dirX, -p.dirY) : NAN;
    }
    if (height > 0 && std::fabs(height / 720.0f - g_u) > 1e-4f && !g_ctx) g_u = height / 720.0f;
    Layout(width, height);
    ReadDanger();
    if (!worldLoaded) CloseMap("left the level");
    // WASTED or BUSTED: the map steps aside for the game's own moment (and he is somewhere else after it)
    if (g_open && (Beat().kind == BeatKind::Wasted || Beat().kind == BeatKind::Busted)) CloseMap(Beat().kind == BeatKind::Wasted ? "wasted" : "busted");
    {   // a respawn or any jump of more than 30 blocks: the map closes, the route is re-picked from the new spot
        static float lx = -1, ly = -1;
        if (g_me.valid && lx >= 0 && std::hypot(g_me.x - lx, g_me.y - ly) > 30.0f) {
            CloseMap("he was moved (a respawn)");
            if (g_route.active) { g_route.offSince = -1; g_route.lastReroute = -10; g_route.path.clear(); g_route.fieldMode = -1; }
        }
        if (g_me.valid) { lx = g_me.x; ly = g_me.y; }
    }
    const bool canOpen = g_me.valid && g_level.Ready() && !DebugMenuVisible();
    if (KeyEdge(g_cfg.key)) {
        if (g_open) CloseMap("key");
        else if (canOpen) OpenMap();
    }
    if (g_open && KeyEdge(VK_ESCAPE)) { CloseMap("escape"); g_escLatch = true; }
    if (g_escLatch && !KeyDown(VK_ESCAPE)) g_escLatch = false;
    if (g_open && DebugMenuVisible()) CloseMap("F4 menu");
    PollDevtools();
    ViewSetMapHold(g_open || g_escLatch);
    if (g_open) MapInput(presentWindow, width, height, g_dt);
    UpdateRoute();
    // the picture lives on the device only while the map is open (and 10 s after, for a quick reopen)
    if (device && g_open) EnsureTexture(device);
    if (g_open) g_closedAt = -1;
    else if (g_tex) {
        if (g_closedAt < 0) g_closedAt = now;
        if (now - g_closedAt > 10.0) { ReleaseTexture(); g_closedAt = -1; Log("citymap: map texture released (closed 10 s)"); }
    }
    // the route's state every two seconds
    static double lastLog = 0;
    if (g_route.active && now - lastLog > 2.0) {
        lastLog = now;
        CityMapGuide gd;
        CityMapGuideNow(&gd);
        Log("citymap: guide %s at %.2f,%.2f,%.2f lane %.1f/%.1f off %.2f: %s left, next %s %s; chevrons drawn %d walled %d covered %d behind %d; reroutes %d",
            g_me.inCar ? "car" : "walk", g_me.x, g_me.y, g_me.z, g_route.laneS, g_route.lcum.empty() ? 0.0f : g_route.lcum.back(), g_route.offLine,
            DistanceText(gd.remainingBlocks).c_str(), gd.turnBlocks >= 0 ? (gd.turnDir < 0 ? "left" : "right") : "-",
            gd.turnBlocks >= 0 ? DistanceText(gd.turnBlocks).c_str() : "", g_chev.drawn, g_chev.walled, g_chev.covered, g_chev.behind, g_route.reroutes);
        g_chev = ChevronStats();
    }
}

void CityMapDrawWorld(IDirect3DDevice9* device, int width, int height) {
    if (!g_cfg.enabled || !g_cfg.chevrons || g_open || !g_route.active || !StreetPresentation() || !device || width <= 0) return;
    if (!EnsureContext(device, height)) return;
    ImGuiContext* previous = ImGui::GetCurrentContext();
    ImGui::SetCurrentContext(g_ctx);
    if (g_fontHeight != height) BuildFonts(height);
    BeginFrame(width, height, g_dt);
    DrawChevrons(ImGui::GetForegroundDrawList(), width, height, g_time);
    EndFrame("chevrons");
    ImGui::SetCurrentContext(previous);
}

void CityMapDrawOverlay(IDirect3DDevice9* device, int width, int height) {
    if (!g_cfg.enabled || !g_open || !device || width <= 0) return;
    if (!EnsureContext(device, height)) return;
    ImGuiContext* previous = ImGui::GetCurrentContext();
    ImGui::SetCurrentContext(g_ctx);
    if (g_fontHeight != height) BuildFonts(height);
    Layout(width, height);
    BeginFrame(width, height, g_dt);
    DrawMap(ImGui::GetForegroundDrawList(), width, height, g_time);
    EndFrame("map");
    ImGui::SetCurrentContext(previous);
}

bool CityMapGuideNow(CityMapGuide* out) {
    *out = CityMapGuide();
    const Route& r = g_route;
    if (!g_cfg.enabled || !r.active || r.fx.size() < 2 || !g_me.valid) return false;
    std::vector<float> zx, zy;
    float off;
    CutAt(r.fx, r.fy, nullptr, g_me.x, g_me.y, static_cast<int>(r.fx.size()), &out->lineX, &out->lineY, nullptr, &off);
    CutAt(r.cx, r.cy, nullptr, g_me.x, g_me.y, static_cast<int>(r.cx.size()), &zx, &zy, nullptr, &off);
    out->wayX = r.fx.back();
    out->wayY = r.fy.back();
    out->remainingBlocks = Length(zx, zy) + (r.hop > 0 ? r.hop : 0);
    float d; int dir;
    if (NextTurn(zx, zy, &d, &dir)) { out->turnBlocks = d; out->turnDir = dir; }
    out->arrived = r.arrivedAt >= 0;
    out->offNetwork = r.hop > 0;
    if (!g_cfg.minimapRoute) out->lineX.clear(), out->lineY.clear();
    return true;
}

bool CityMapClassicDisc() {
    return g_cfg.enabled && g_cfg.classicDisc && g_route.active && !g_open && g_me.valid;
}

}  // namespace gta2dx9
