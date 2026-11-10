// Traffic and pedestrian density in the street views (QB-9 "boulevards empty",
// QB-42 "peds appear at the spawn ring's edge").
//
// gta2.exe creates, keeps and removes ambient cars and people inside the window
// its top-down camera frames. The street views scale that window 2.6x and make it
// square (WorldView::MatchGameViewToFrame), so things are created out in the haze
// rather than in plain sight - but the game's budgets did not grow with it:
//
//   - Traffic: at most 16 "recycled" (ambient) cars alive at once, whatever the
//     window. CarManager::CanAllocateCarOfKind (0x420D30: < 16, and a sibling at
//     0x420C90: < 15), the traffic spawner (0x4B34E0) and its per-camera driver
//     (0x4B4A60, both == 16) read the sum of the counts at CarManager+0x28 and
//     +0x40 against an imm8. The spawn probability already scales with the
//     window's area (TrafficSpawner: density_scale = w * h / 86, clamped to 99%),
//     so the cap is the whole limit: 16 cars spread over 31 x 42 tiles instead of
//     about 12 x 9.
//   - People: a dummy pedestrian is placed on the window's edge only while the
//     number of peds in the window is under zone.ped_density / 25 (0x441042:
//     imul 0x51EB851F, sar edx,3) - 8 in Downtown (density 200), 20 in Residential
//     (500) - and while fewer than PedManager+0 (50 as shipped; halved above three
//     stars) dummies exist.
//
// Names and layouts from the CriminalRETeam/gta2_re reimplementation (10.5),
// matched against the 9.6 binary byte for byte at each site below.
//
// Each site is checked before it is written and keeps its original byte; in the
// classic view every byte goes back, so the top-down game is exactly as shipped -
// except that the traffic cap goes back only once the street view's extra cars
// have drained to the stock 16 (an equality check below the live count would
// never stop the spawner again: see DensityUpdate).
#include "density.h"

#include <windows.h>

#include <cstdint>
#include <cstring>

#include "frame_limiter.h"
#include "game_access.h"
#include "log.h"

namespace gta2dx9 {
namespace {

int g_trafficCap = kDefaultTrafficCap;
int g_pedScale = kDefaultPedDensityScale;
int g_pedCap = kDefaultPedCap;
int g_zoneCar = kDefaultZoneCarDensity;
// Budget level, 0 (the game's own) .. kLevels - 1 (the configured): see FollowFrameRate.
constexpr int kLevels = 4;
int g_level = kLevels - 1;

constexpr int kStockTrafficCap = 16;
constexpr int kStockPedShift = 3;   // ped_density / 25

// One immediate byte in gta2.exe's code.
struct ImmSite {
    uintptr_t at;          // the imm8 itself
    uint8_t prefix[2];     // the two opcode bytes before it, checked
    uint8_t stock;         // what it holds as shipped
    int offsetFromCap;     // traffic: cap + this (the < 15 sibling is cap - 1)
    bool patched;
    bool bad;              // did not hold what was expected: never touched
};

ImmSite g_trafficSites[] = {
    {0x00420C9F, {0x83, 0xF9}, 0x0F, -1, false, false},   // CanAllocate sibling: < 15
    {0x00420D3F, {0x83, 0xF9}, 0x10, 0, false, false},    // CanAllocateCarOfKind: < 16
    {0x004B34FE, {0x83, 0xF9}, 0x10, 0, false, false},    // SpawnTrafficCar: == 16
    {0x004B4A88, {0x83, 0xF9}, 0x10, 0, false, false},    // MakeTrafficForCurrCamera: == 16
};
ImmSite g_pedShiftSite = {0x0044104B, {0xC1, 0xFA}, kStockPedShift, 0, false, false};

// PedManager (allocated, pointer here); its first word is the dummy cap. The
// dummy count and the "peds in the window" count, for the census.
constexpr uintptr_t kPedManagerPtr = 0x005E5BC0;
constexpr uintptr_t kNumDummyChars = 0x005E5BEA;   // uint8
constexpr uintptr_t kPedManagerPedsInWindow = 0x06;  // uint8
// CarManager (pointer), ambient car counts.
constexpr uintptr_t kCarManagerPtr = 0x005E4CA4;
constexpr uintptr_t kCarManagerRecycled = 0x28;
constexpr uintptr_t kCarManagerProtoRecycled = 0x40;

constexpr uintptr_t kCarManagerSpawnBlock = 0x54;   // uint8, > 0 stops the spawner
// The player: [[0x5EB4FC]+0x38] (game_save.cpp, hud3d.cpp).
constexpr uintptr_t kPlayerHolderPtr = 0x005EB4FC;
constexpr uintptr_t kPlayerInHolder = 0x38;
constexpr uintptr_t kPlayerTrafficCounter = 0x680;    // uint16 (0x4A7EA6)
constexpr uintptr_t kPlayerTrafficThreshold = 0x682;  // uint16 (0x424A38)

// Map_0x370 (pointer) and its GetZoneInfoAt(x, y) (0x4DF890 in 10.5; the 9.6
// copy is the one FUN_00441000's ped spawner calls before reading +0x0A).
constexpr uintptr_t kMapPtr = 0x00662C08;
constexpr uintptr_t kGetZoneInfoAt = 0x00465250;

// The ped pool (Pool<Ped, 200>, built by FUN_0043E0E0): the free list's head
// at +0, linked through each ped's +0x160. Its Allocate does not check for an
// empty free list - running it dry crashes the game - so the raised budgets
// stand down to the game's own while fewer than kPedHeadroomLow are free, and
// come back above kPedHeadroomHigh. Every traffic car carries a driver, and
// police, roadblocks, gangs and missions draw on the same 200.
constexpr uintptr_t kPedPoolPtr = 0x005E5BBC;
constexpr uintptr_t kPedPoolNext = 0x160;
constexpr int kPedPoolSize = 200;
constexpr int kPedHeadroomLow = 40;
constexpr int kPedHeadroomHigh = 60;
bool g_headroomHold = false;
int g_lastFree = -1;

int FreePeds() {
    uint8_t* pool = *reinterpret_cast<uint8_t**>(kPedPoolPtr);
    if (!game::PlausiblePointer(pool)) return -1;
    int n = 0;
    for (uint8_t* p = *reinterpret_cast<uint8_t**>(pool); p && n <= kPedPoolSize; ++n) {
        if (!game::PlausiblePointer(p)) return -1;
        p = *reinterpret_cast<uint8_t**>(p + kPedPoolNext);
    }
    return n;
}

// The vehicle pool (Pool<Car, 306>, built at 0x426DB0): free list head at +0,
// linked through each car's +0x4C. Its Allocate (0x425480) does not check for an
// empty list either - gta2.exe+0x25486 reading 0x4C is that - so the raised
// traffic budget stands down while fewer than kCarHeadroomLow are free.
constexpr int kCarPoolSize = 0x132;
constexpr int kCarHeadroomLow = 40;
constexpr int kCarHeadroomHigh = 60;
int g_lastFreeCars = -1;

// FIX-PERF-6 (qastress-gta2exe-null-read-0x47352): the game's object grid. Every car, person and object
// is linked into each map block its bounding box covers, through two node pools built at 0x4471B0:
// [0x5E6684] Pool<{object, next}, 4096> (8-byte nodes, next at +4) and [0x5E6688] Pool<{byte y, list,
// next}, 6000> (12-byte nodes, next at +8), each with its free list's head at +0. Neither pop (0x447350,
// 0x447370: head = head->next) checks for an empty list: gta2.exe+0x47352 reading 00000004 is the
// 4096-node pool run dry (inserted by 0x4479D0 for each block of 0x447C00's rectangle). The raised
// budgets put more cars and people into it, so they stand down while either pool runs low, as for the
// ped and vehicle pools. [density] grid_headroom=0 (or GTA2DX9_GRID_HEADROOM=0) leaves it unwatched.
constexpr uintptr_t kGridCellPoolPtr = 0x005E6684;
constexpr uintptr_t kGridColumnPoolPtr = 0x005E6688;
constexpr int kGridCellNodes = 4096, kGridColumnNodes = 6000;
constexpr int kGridCellLow = 240, kGridCellHigh = 400;   // idles at 450-700 free (perf6_buf20); at 6 stars it fell 45 below a hold at 160 (perf6_want6: 107)
constexpr int kGridColumnLow = 400, kGridColumnHigh = 600;   // idles at ~3100 free
bool g_gridWatch = true;
int g_lastFreeCells = -1, g_lastFreeColumns = -1, g_minFreeCells = 1 << 30, g_minFreeColumns = 1 << 30;

// Free nodes on a grid pool's list (-1: cannot tell); every node must lie inside the pool's own block.
int FreeGridNodes(uintptr_t holder, int nodes, size_t stride, size_t next) {
    uint8_t* pool = *reinterpret_cast<uint8_t**>(holder);
    if (!game::PlausiblePointer(pool)) return -1;
    const uint8_t* lo = pool + 4;
    const uint8_t* hi = lo + static_cast<size_t>(nodes) * stride;
    int n = 0;
    for (uint8_t* p = *reinterpret_cast<uint8_t**>(pool); p; ++n) {
        if (n > nodes || p < lo || p >= hi || (static_cast<size_t>(p - lo) % stride) != 0) return -1;
        p = *reinterpret_cast<uint8_t**>(p + next);
    }
    return n;
}

int FreeCars() {
    uint8_t* pool = *reinterpret_cast<uint8_t**>(game::kVehiclePoolPtr);
    if (!game::PlausiblePointer(pool)) return -1;
    int n = 0;
    for (uint8_t* p = *reinterpret_cast<uint8_t**>(pool); p && n <= kCarPoolSize; ++n) {
        if (!game::PlausiblePointer(p)) return -1;
        p = *reinterpret_cast<uint8_t**>(p + game::kVehicleNext);
    }
    return n;
}

bool g_pedCapWritten = false;
int16_t g_pedCapOriginal = 50;
bool g_checked = false;

bool WriteByte(uintptr_t at, uint8_t value) {
    void* target = reinterpret_cast<void*>(at);
    DWORD previous = 0;
    if (!VirtualProtect(target, 1, PAGE_EXECUTE_READWRITE, &previous)) return false;
    *reinterpret_cast<uint8_t*>(target) = value;
    VirtualProtect(target, 1, previous, &previous);
    FlushInstructionCache(GetCurrentProcess(), target, 1);
    return true;
}

void CheckSite(ImmSite* s) {
    const uint8_t* p = reinterpret_cast<const uint8_t*>(s->at);
    if (p[-2] != s->prefix[0] || p[-1] != s->prefix[1] || p[0] != s->stock) {
        s->bad = true;
        Log("density: %08X does not hold what this expects (%02X %02X %02X) - left alone",
            static_cast<unsigned>(s->at), p[-2], p[-1], p[0]);
    }
}

void SetSite(ImmSite* s, bool on, uint8_t value) {
    if (s->bad) return;
    const uint8_t want = on ? value : s->stock;
    if (*reinterpret_cast<const uint8_t*>(s->at) == want) {
        s->patched = on && want != s->stock;
        return;
    }
    if (WriteByte(s->at, want)) s->patched = on && want != s->stock;
}

int PedShiftFor(int scale) {
    // /25 is sar 3; each halving of the divisor doubles the people allowed.
    if (scale >= 8) return 0;
    if (scale >= 4) return 1;
    if (scale >= 2) return 2;
    return kStockPedShift;
}

uint8_t* PedManager() {
    uint8_t* m = *reinterpret_cast<uint8_t**>(kPedManagerPtr);
    return game::PlausiblePointer(m) ? m : nullptr;
}

uint8_t* CarManager() {
    uint8_t* m = *reinterpret_cast<uint8_t**>(kCarManagerPtr);
    return game::PlausiblePointer(m) ? m : nullptr;
}

// Recycled (ambient) cars alive: the sum every traffic site compares, -1 unknown.
int LiveTraffic() {
    uint8_t* cm = CarManager();
    if (!cm) return -1;
    return *reinterpret_cast<int32_t*>(cm + kCarManagerRecycled) +
           *reinterpret_cast<int32_t*>(cm + kCarManagerProtoRecycled);
}

int LevelPedCap();
int16_t g_pedCapWant = 0;   // what we last wrote

void ApplyPedCap(bool on) {
    uint8_t* m = PedManager();
    if (!m) {
        g_pedCapWritten = false;
        return;
    }
    int16_t* cap = reinterpret_cast<int16_t*>(m);
    const int levelCap = LevelPedCap();
    if (on && levelCap > 0) {
        const int16_t want = static_cast<int16_t>(levelCap);
        if (!g_pedCapWritten || *cap != g_pedCapWant) {
            // Whatever is there and is not ours (50 as built, or a script's
            // value) is the game's, and goes back in the classic view.
            g_pedCapOriginal = *cap;
        }
        *cap = want;
        g_pedCapWant = want;
        g_pedCapWritten = true;
    } else if (g_pedCapWritten) {
        if (*cap == g_pedCapWant) *cap = g_pedCapOriginal;
        g_pedCapWritten = false;
    }
}

// The traffic spawner takes its car density from the zone the *player* stands in
// (TrafficSpawner::GenerateTraffic: field_10_zone), not from the road it spawns
// on. Downtown's script gives the church plaza at the start (and other car-free
// places) a car density of 0, so standing there stops all traffic on the roads
// around - which a street view sees plainly, out to 25 blocks. While a street view
// is up and the player stands in such a zone, that zone gets g_zoneCar; it goes
// back when he leaves it or the view goes back to classic. Each spawn point still
// checks the zone it is in and needs an arrowed road lane, so cars only come onto
// real roads - including any inside that zone.
const uint8_t* ZoneAt(float x, float y) {
    void* map = *reinterpret_cast<void**>(kMapPtr);
    if (!game::PlausiblePointer(map) || !(x >= 0.0f && y >= 0.0f && x < 256.0f && y < 256.0f)) return nullptr;
    typedef const uint8_t*(__attribute__((thiscall)) * ZoneAtFn)(void*, int32_t, int32_t);
    const uint8_t* zone =
        reinterpret_cast<ZoneAtFn>(kGetZoneInfoAt)(map, static_cast<int32_t>(x), static_cast<int32_t>(y));
    // Zone records are 22 bytes, so only the range is checked, not the alignment.
    const uintptr_t za = reinterpret_cast<uintptr_t>(zone);
    return game::InUserSpace(za, 22) ? zone : nullptr;
}

uint16_t* g_zoneWritten = nullptr;   // the record holding our value, if any
uint16_t g_zoneOriginal = 0;

void RestoreZone() {
    if (g_zoneWritten && *g_zoneWritten == static_cast<uint16_t>(g_zoneCar)) *g_zoneWritten = g_zoneOriginal;
    g_zoneWritten = nullptr;
}

void ApplyPlayerZone(bool on, bool playerValid, float px, float py) {
    if (!on || g_zoneCar <= 0 || !playerValid) {
        RestoreZone();
        return;
    }
    uint16_t* car = const_cast<uint16_t*>(reinterpret_cast<const uint16_t*>(ZoneAt(px, py)));
    if (!car) {
        RestoreZone();
        return;
    }
    if (car == g_zoneWritten) {
        // A script that set the zone since has the last word.
        if (*car != static_cast<uint16_t>(g_zoneCar)) g_zoneWritten = nullptr;
        return;
    }
    RestoreZone();   // he has left the zone we filled
    if (*car != 0) return;   // only a zone with no traffic at all is filled in
    g_zoneOriginal = *car;
    *car = static_cast<uint16_t>(g_zoneCar);
    g_zoneWritten = car;
}

// Every 300 frames, what the game is holding: the census the before/after
// numbers in docs/performance.md come from.
int g_frame = 0;
void Census(bool ground, bool playerValid, float px, float py) {
    if (++g_frame % 300 != 0) return;
    uint8_t* cm = CarManager();
    uint8_t* pm = PedManager();
    const int traffic = cm ? *reinterpret_cast<int32_t*>(cm + kCarManagerRecycled)
                                 + *reinterpret_cast<int32_t*>(cm + kCarManagerProtoRecycled)
                           : -1;
    const int dummies = *reinterpret_cast<const uint8_t*>(kNumDummyChars);
    const int dummyCap = pm ? *reinterpret_cast<int16_t*>(pm) : -1;
    const int inWindow = pm ? pm[kPedManagerPedsInWindow] : -1;
    int live = 0, driven = 0, near8 = 0, near16 = 0;
    int guard = 0;
    for (uint8_t* v = game::VehicleListHead(); v && guard < 400;
         v = game::NextInList(v, game::kVehicleNext), ++guard) {
        ++live;
        if (!game::VehicleHasDriver(v)) continue;
        ++driven;
        float x, y, z;
        if (!playerValid || !game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
        const float d2 = (x - px) * (x - px) + (y - py) * (y - py);
        if (d2 < 16.0f * 16.0f) ++near16;
        if (d2 < 8.0f * 8.0f) ++near8;
    }
    // The player's traffic pacing (Player+0x680 counts frames up to 100, +0x682
    // is 100 - the zone's density as last computed) and the spawn block.
    int counter = -1, threshold = -1;
    uint8_t* holder = *reinterpret_cast<uint8_t**>(kPlayerHolderPtr);
    if (game::PlausiblePointer(holder)) {
        uint8_t* player = *reinterpret_cast<uint8_t**>(holder + kPlayerInHolder);
        if (game::PlausiblePointer(player)) {
            counter = *reinterpret_cast<uint16_t*>(player + kPlayerTrafficCounter);
            threshold = *reinterpret_cast<uint16_t*>(player + kPlayerTrafficThreshold);
        }
    }
    const int block = cm ? cm[kCarManagerSpawnBlock] : -1;
    // The zone the player stands in: the traffic spawner takes its car density
    // (and so whether there is any traffic at all) from here, not from the road
    // it spawns on.
    int zoneCar = -1, zonePed = -1;
    if (const uint8_t* zone = playerValid ? ZoneAt(px, py) : nullptr) {
        zoneCar = *reinterpret_cast<const uint16_t*>(zone + 0x0);
        zonePed = *reinterpret_cast<const int16_t*>(zone + 0xA);
    }
    Log("density: view=%s level=%d free_peds=%d zone_filled=%d zone_car=%d zone_ped=%d traffic=%d/%d pace=%d/%d block=%d dummies=%d/%d peds_in_window=%d ped_shift=%d free_cars=%d vehicles=%d "
        "driven=%d driven_within8=%d driven_within16=%d grid_free=%d/%d grid_min=%d/%d",
        ground ? "street" : (g_headroomHold ? "held" : "classic"), g_level, g_lastFree, g_zoneWritten ? 1 : 0, zoneCar, zonePed, traffic,
        g_trafficSites[1].patched ? *reinterpret_cast<const uint8_t*>(g_trafficSites[1].at)
                                  : kStockTrafficCap,
        counter, threshold, block, dummies, dummyCap, inWindow, *reinterpret_cast<const uint8_t*>(g_pedShiftSite.at), g_lastFreeCars, live,
        driven, near8, near16, g_lastFreeCells, g_lastFreeColumns, g_minFreeCells == (1 << 30) ? -1 : g_minFreeCells,
        g_minFreeColumns == (1 << 30) ? -1 : g_minFreeColumns);
}

// Frame-time guard. More cars and people cost simulation and, above all, skinned
// figures to pose and draw (measured: 2-3 skinned figures a frame at the game's
// own budgets, 10-20 at the full ones). The budgets therefore come in levels,
// from the game's own (0) to the configured ones (kLevels - 1), and the level
// follows the frame rate actually achieved: more than kLateDown of the frames in
// a 2 s window later than 1.15 frame periods steps it down; fewer than kLateUp
// for kUpWindows windows in a row steps it back up. (On the shared test host the
// game's own budgets already run 5-16% late frames per window in the street
// views - median 8.6% - so the band between the two holds a level steady.) The period is the frame cap's
// (30 fps unless set otherwise; GTA2_SPEED runs cap higher).
constexpr double kLateDown = 0.15;
constexpr double kLateUp = 0.05;
constexpr int kUpWindows = 2;
LARGE_INTEGER g_lastFrame = {};
double g_windowStart = 0.0;
int g_windowFrames = 0, g_windowLate = 0, g_quietWindows = 0;
double g_qpcToSeconds = 0.0;

double NowSeconds() {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    if (g_qpcToSeconds == 0.0) {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        g_qpcToSeconds = 1.0 / static_cast<double>(f.QuadPart);
    }
    return static_cast<double>(t.QuadPart) * g_qpcToSeconds;
}

void FollowFrameRate(bool ground) {
    // GTA2DX9_DENSITY_LEVEL=0..3 pins the budget level (measurements: FIX-TRAFFIC-1's cap table
    // on a shared host, where the controller otherwise moves the cap mid-run).
    static int pinned = -2;
    if (pinned == -2) {
        char e[8] = {};
        pinned = GetEnvironmentVariableA("GTA2DX9_DENSITY_LEVEL", e, sizeof e) && e[0] >= '0' && e[0] <= '3' ? e[0] - '0' : -1;
        if (pinned >= 0) Log("density: budget level pinned at %d (GTA2DX9_DENSITY_LEVEL)", pinned);
    }
    if (pinned >= 0) { g_level = pinned; return; }
    static double last = 0.0;
    const double now = NowSeconds();
    const double interval = last > 0.0 ? now - last : 0.0;
    last = now;
    if (!ground || interval <= 0.0 || interval > 1.0) {   // menus, loads, a paused container
        g_windowStart = now;
        g_windowFrames = g_windowLate = 0;
        return;
    }
    const float fps = FrameLimitFps();
    const double period = 1.0 / (fps > 1.0f ? fps : 30.0f);
    ++g_windowFrames;
    if (interval > period * 1.15) ++g_windowLate;
    if (now - g_windowStart < 2.0) return;
    const double late = static_cast<double>(g_windowLate) / g_windowFrames;
    const int before = g_level;
    if (late > kLateDown) {
        if (g_level > 0) --g_level;
        g_quietWindows = 0;
    } else if (late < kLateUp) {
        if (++g_quietWindows >= kUpWindows && g_level < kLevels - 1) {
            ++g_level;
            g_quietWindows = 0;
        }
    } else {
        g_quietWindows = 0;
    }
    if (g_level != before)
        Log("density: %.0f%% of frames late over %.1f s - budget level %d -> %d", late * 100.0,
            now - g_windowStart, before, g_level);
    g_windowStart = now;
    g_windowFrames = g_windowLate = 0;
}

// The budgets at the current level: the game's own at 0, the configured ones at
// the top, in proportion between.
int LevelTrafficCap() {
    if (g_trafficCap <= kStockTrafficCap) return g_trafficCap;
    return kStockTrafficCap + (g_trafficCap - kStockTrafficCap) * g_level / (kLevels - 1);
}
int LevelPedScale() {
    // Doublings in proportion to the level: 4 is 1, 2, 2, 4 over the levels.
    int doublings = 0;
    for (int s = 1; s * 2 <= g_pedScale && doublings < 3; s *= 2) ++doublings;
    const int at = (doublings * g_level * 2 + (kLevels - 1)) / (2 * (kLevels - 1));   // rounded
    return 1 << at;
}
int LevelPedCap() {
    if (g_pedCap <= 0) return 0;
    if (g_pedCap <= 50) return g_pedCap;
    return 50 + (g_pedCap - 50) * g_level / (kLevels - 1);
}

}  // namespace

void SetGridHeadroom(bool on) {
    char env[8] = {};
    if (GetEnvironmentVariableA("GTA2DX9_GRID_HEADROOM", env, sizeof env)) on = env[0] != '0';
    g_gridWatch = on;
    Log("density: grid_headroom=%d (object grid node pools watched: the raised budgets stand down under %d/%d free)", on ? 1 : 0,
        kGridCellLow, kGridColumnLow);
}

void SetZoneCarDensity(int density) {
    g_zoneCar = density < 0 ? 0 : (density > 1000 ? 1000 : density);
    Log("density: zone_car_density=%d (street views only)", g_zoneCar);
}

void SetDensity(int trafficCap, int pedDensityScale, int pedCap) {
    g_trafficCap = trafficCap < 0 ? 0 : (trafficCap > 100 ? 100 : trafficCap);
    g_pedScale = pedDensityScale < 0 ? 0 : pedDensityScale;
    g_pedCap = pedCap < 0 ? 0 : (pedCap > 120 ? 120 : pedCap);
    Log("density: traffic_cap=%d ped_density_scale=%d ped_cap=%d (street views only)", g_trafficCap,
        g_pedScale, g_pedCap);
}

void DensityUpdate(bool ground, bool playerValid, float px, float py) {
    if (!g_checked) {
        g_checked = true;
        for (ImmSite& s : g_trafficSites) CheckSite(&s);
        CheckSite(&g_pedShiftSite);
        // Part of the traffic cap without the rest is worse than none.
        bool anyBad = false;
        for (ImmSite& s : g_trafficSites) anyBad |= s.bad;
        if (anyBad)
            for (ImmSite& s : g_trafficSites) s.bad = true;
    }
    // Headroom in the ped and vehicle pools decides whether the raised budgets may stand.
    const int freePeds = FreePeds();
    const int freeCars = FreeCars();
    g_lastFree = freePeds;
    g_lastFreeCars = freeCars;
    // FIX-PERF-6: the object grid's two node pools (above); unwatched (or unreadable) counts as plenty.
    int freeCells = -1, freeColumns = -1;
    if (g_gridWatch) {
        freeCells = FreeGridNodes(kGridCellPoolPtr, kGridCellNodes, 8, 4);
        freeColumns = FreeGridNodes(kGridColumnPoolPtr, kGridColumnNodes, 12, 8);
        if (freeCells >= 0 && freeCells < g_minFreeCells) g_minFreeCells = freeCells;
        if (freeColumns >= 0 && freeColumns < g_minFreeColumns) g_minFreeColumns = freeColumns;
    }
    g_lastFreeCells = freeCells;
    g_lastFreeColumns = freeColumns;
    const bool gridLow = (freeCells >= 0 && freeCells < kGridCellLow) || (freeColumns >= 0 && freeColumns < kGridColumnLow);
    const bool gridHigh = (freeCells < 0 || freeCells > kGridCellHigh) && (freeColumns < 0 || freeColumns > kGridColumnHigh);
    if (freePeds < 0 || freeCars < 0) {
        g_headroomHold = true;   // cannot tell: the game's own budgets
    } else if (!g_headroomHold && (freePeds < kPedHeadroomLow || freeCars < kCarHeadroomLow || gridLow)) {
        g_headroomHold = true;
        Log("density: %d of %d people, %d of %d cars, %d of %d grid cells, %d of %d grid columns free - the game's own budgets until %d, %d, %d and %d are",
            freePeds, kPedPoolSize, freeCars, kCarPoolSize, freeCells, kGridCellNodes, freeColumns, kGridColumnNodes,
            kPedHeadroomHigh, kCarHeadroomHigh, kGridCellHigh, kGridColumnHigh);
    } else if (g_headroomHold && freePeds > kPedHeadroomHigh && freeCars > kCarHeadroomHigh && gridHigh) {
        g_headroomHold = false;
        Log("density: %d of %d people, %d of %d cars, %d grid cells, %d grid columns free - raised budgets again", freePeds, kPedPoolSize,
            freeCars, kCarPoolSize, freeCells, freeColumns);
    }
    FollowFrameRate(ground);
    ground = ground && !g_headroomHold;
    // The spawner's two checks (0x4B34FC, 0x4B4A86) are `cmp count, cap; je`:
    // equality. A cap written below the cars already alive (the level stepping
    // down from 36 with 36 out, a pool hold, or the view going back to classic)
    // is never met again and traffic runs on until the vehicle pool is empty
    // (gta2.exe+0x25486). So the written cap never goes below the live count,
    // and the stock byte goes back only once the surplus has drained to it.
    int trafficCap = ground ? LevelTrafficCap() : kStockTrafficCap;
    const int live = LiveTraffic();
    if (live > trafficCap) trafficCap = live > 127 ? 127 : live;   // imm8 is sign-extended
    const bool traffic = trafficCap > kStockTrafficCap;
    for (ImmSite& s : g_trafficSites)
        SetSite(&s, traffic, static_cast<uint8_t>(trafficCap + s.offsetFromCap));
    const int shift = PedShiftFor(LevelPedScale());
    SetSite(&g_pedShiftSite, ground && shift != kStockPedShift, static_cast<uint8_t>(shift));
    ApplyPedCap(ground);
    ApplyPlayerZone(ground, playerValid, px, py);
    Census(ground, playerValid, px, py);
}

}  // namespace gta2dx9
