#include <chrono>
#include "mem_stats.h"
#include "world_view.h"
#include "city_map.h"
#include "hud_gamefont.h"
#include "prop_collision.h"
#include "regress_cam.h"
#include "density.h"
#include "boarding.h"
#include "city_ai.h"

#include "beats.h"
#include "car_bodies.h"
#include "map_objects.h"
#include "model_store.h"
#include "identity.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "../../src/gta2_style.h"
#include "../../src/world_mesh.h"
#include "../../src/district_kit.h"
#include "../../src/post_fx.h"   // SetPostCockpitReach (FIX-COCKPIT-CAB-4)
#include "../../src/weather_fx.h"   // LIGHTING-V1: follow_clock=auto
#include "debug_overlay.h"
#include "hud3d.h"
#include "regress_cam.h"
#include "frame_limiter.h"
#include "frame_log.h"
#include "game_access.h"
#include "compat.h"
#include "game_save.h"
#include "eye_collision.h"
#include "remix_wet.h"
#include "../../src/weather_fx.h"
#include "live_geometry.h"
#include "light_bench.h"
#include "log.h"
#include "remix_api.h"
#include "remix_lights.h"
#include "vehicle_fx.h"
#include "synthetic_lights.h"
#include "texture_store.h"
#include "time_of_day.h"

namespace gta2dx9 {
namespace { const gta2::Map* g_coverMap = nullptr; }

namespace { int g_playerAmmoLogged = 0; }
namespace {

// Where each frame's time goes, so a stutter can be pinned on a stage. A frame over
// kHitchMs is logged with its stages; every 256 frames the worst of each stage is too.
// Stage 0 is the game's own simulation between our frames, 1 the lights prepared and
// reconciled (the bridge), 2 the world mesh, 3 sprites and cars, 4 UI, 5 the lights
// drawn, 6 the flip to Remix, 7 our frame wait.
constexpr double kHitchMs = 45.0;
constexpr int kStages = 8;
struct FrameTimer {
    LARGE_INTEGER last = {};          // end of the previous frame
    double worst[kStages] = {};
    double sum[kStages] = {};
    int frames = 0;
    int hitchLogged = 0;
    int hitchLoggedOurs = 0;
};
FrameTimer g_frameTimer;
double g_solverMs = 0.0;
double g_camLocateMs = 0.0, g_camProbesMs = 0.0;   // UpdateCamera: the player locator; the state lines and probes   // the chase/first-person camera solver's share of UpdateCamera (frame log)
double g_scriptLinesMs = 0.0;   // FIX-PERF-2: the state lines (view: player/peds/cars) this frame
struct LogCostSummary { long calls = 0, bytes = 0; double sum = 0.0, worst = 0.0, linesSum = 0.0, linesWorst = 0.0; };
LogCostSummary g_logCost;
double QpcMs(LARGE_INTEGER a, LARGE_INTEGER b) {
    static double toMs = 0.0;
    if (toMs == 0.0) {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        toMs = 1000.0 / static_cast<double>(f.QuadPart);
    }
    return static_cast<double>(b.QuadPart - a.QuadPart) * toMs;
}

constexpr uint32_t kMaxColumnWords = 1 << 20;
constexpr uint32_t kMaxBlocks = 1 << 18;
constexpr size_t kMatchBlocks = 4000;

// Per-frame easing toward the street height under the camera.
constexpr float kHeightFollowRate = 0.06f;

// The camera filter's time constants, in seconds, at a smoothing of 1. See
// WorldView::UpdateCamera.
constexpr float kCameraVelocityTau = 0.32f;
constexpr float kCameraPullTau = 0.60f;
constexpr float kCameraZoomTau = 0.35f;
// The furthest the view may be from the game's camera, in tiles. The game only
// draws and populates the window its own camera frames, with a little to spare.
constexpr float kCameraMaxLag = 1.3f;
// pm18 (FIX-CLASSIC): a float exponential filter stalls a few ULPs short of its target, and
// where it stalls depends on the path taken (the camera before a V cycle sat 0.0001 tiles
// off the game's camera, after it on it with the zoom one ULP out), so the settled classic
// frame differed by a level or two in thousands of texels. Within this gap (tiles; ~0.1 px
// at the classic zoom) each filter lands exactly on its target and stops.
constexpr float kCameraSnap = 1e-3f;
float g_cameraSmoothing = kDefaultCameraSmoothing;

// ---------------------------------------------------------------------------
// The one patch gta2.exe needs to reason about a wide frame, and the switch
// that takes it back out. The sites keep the bytes they had, so
// spawn_offscreen=0 - or the checkbox in the menu, mid-game - leaves the running
// process byte for byte as it shipped.
// ---------------------------------------------------------------------------

bool g_spawnOffscreen = kDefaultSpawnOffscreen;
bool g_spawnOffscreenActive = false;

// For the menu: the player as the view last found him, and what the camera
// solver reported. See view_modes.h.
PlayerState g_viewPlayer;
const char* g_viewStatus = "classic";
// The top-down view's car numbers, kept while a ground view has its own.
float g_classicCarHeight = kDefaultCarBodyHeight;
float g_classicCarShoulder = 0.7f;
bool g_classicCarWheels = kDefaultCarWheels;
bool g_viewActive = false;
// FIX-SMOOTH-SWITCH: the presentation, set by WorldView::ApplyTransition (see StreetPresentation).
bool g_presentStreet = false;
float g_presentMix = 0.0f;
// FIX-TRANSITION-ART: the camera's progress s last applied (0 classic .. 1 street), and the s a
// move started from. A V pressed while a move is still under way starts the next move from the
// pose last shown: the presentation now carries on from the s it had there instead of starting
// again from the end the old move set out from (it flipped the whole picture in one frame: the
// game's sprites, HUD and plain tiles over a tilted camera, or the figures and props snapped in
// at material mix 1.000 with the camera still high; pmab5 rapid V). GTA2DX9_MOVE_S_CARRY=0: A/B.
float g_presentS = 0.0f;
float g_moveS0 = 0.0f;
// The re-authored road-marking tiles' own material mix (Renderer::SetStreetView roadMix).
float g_presentRoadMix = 0.0f;
float g_presentExtras = 0.0f;
bool g_viewMoving = false;
// FIX-SEAT-ENTRY-2: the seat's eye while the camera moves into the driver's seat (SeatMoveEye).
bool g_seatMove = false;
gta2::Vec3 g_seatMoveEye{};
// How far from the eye the street views add the map's own lamps, in tiles, and how many at most.
constexpr float kFarLampRadius = 36.0f;
constexpr int kFarLampCap = 120;
float g_viewYaw = 0.0f, g_viewPitch = 0.0f;

// One patched run of bytes and what was there before it.
struct BytePatch {
    uintptr_t at = 0;
    size_t size = 0;
    uint8_t original[8] = {};
    bool applied = false;
};

bool WriteCode(uintptr_t at, const void* bytes, size_t size) {
    void* target = reinterpret_cast<void*>(at);
    DWORD previous = 0;
    if (!VirtualProtect(target, size, PAGE_EXECUTE_READWRITE, &previous)) return false;
    memcpy(target, bytes, size);
    VirtualProtect(target, size, previous, &previous);
    FlushInstructionCache(GetCurrentProcess(), nullptr, 0);
    return true;
}

// Saves what is there, then writes. A site that does not hold what it is
// supposed to is left alone rather than half patched - that is the guard
// against a different build of gta2.exe.
bool ApplyPatch(BytePatch* patch, uintptr_t at, const void* expected, const void* bytes,
                size_t size, const char* what) {
    if (patch->applied) return true;
    if (size > sizeof(patch->original)) return false;
    if (memcmp(reinterpret_cast<const void*>(at), expected, size) != 0) {
        Log("%s: %08X does not hold what this expects - leaving gta2.exe alone", what,
            static_cast<unsigned>(at));
        return false;
    }
    memcpy(patch->original, reinterpret_cast<const void*>(at), size);
    if (!WriteCode(at, bytes, size)) {
        Log("%s: could not write %08X", what, static_cast<unsigned>(at));
        return false;
    }
    patch->at = at;
    patch->size = size;
    patch->applied = true;
    return true;
}

void RevertPatch(BytePatch* patch) {
    if (!patch->applied) return;
    WriteCode(patch->at, patch->original, patch->size);
    patch->applied = false;
}

// The two Fixed values FUN_0041E7A0 reads in place of its own 0.5 and 0.75 once
// its operands point here. See game_access.h kViewHalfScaleSite. They hold the
// game's own values until a frame says otherwise, so a patch applied before the
// first frame changes nothing.
int32_t g_viewHalfScale = game::kViewHalfScaleStock;
int32_t g_viewAspect = game::kViewAspectStock;
BytePatch g_viewHalfScalePatch;
BytePatch g_viewAspectPatch;

bool ApplyGamePatches() {
    struct Site {
        BytePatch* patch;
        uintptr_t at;
        uintptr_t expected;
        int32_t* replacement;
        const char* what;
    };
    const Site sites[2] = {
        {&g_viewHalfScalePatch, game::kViewHalfScaleSite, game::kViewHalfScale, &g_viewHalfScale,
         "view width"},
        {&g_viewAspectPatch, game::kViewAspectSite, game::kViewAspect, &g_viewAspect,
         "view aspect"},
    };
    bool ok = true;
    for (const Site& site : sites) {
        if (*reinterpret_cast<const uint8_t*>(site.at - 1) != 0x68) {
            Log("%s: %08X is not a PUSH", site.what, static_cast<unsigned>(site.at));
            ok = false;
            break;
        }
        ok &= ApplyPatch(site.patch, site.at, &site.expected, &site.replacement, sizeof(void*),
                         site.what);
    }
    // Width without height, or the other way round, is a wrong rectangle rather
    // than a stock one - so it is both or neither.
    if (!ok) {
        RevertPatch(&g_viewHalfScalePatch);
        RevertPatch(&g_viewAspectPatch);
    }
    Log("spawn offscreen: %s", ok ? "gta2.exe patched" : "not applied, see above");
    return ok;
}

void RevertGamePatches() {
    RevertPatch(&g_viewHalfScalePatch);
    RevertPatch(&g_viewAspectPatch);
    Log("spawn offscreen: gta2.exe put back the way it shipped");
}

constexpr float kDegreesToRadians = 3.14159265f / 180.0f;

// The desktop, in the physical pixels a window is really sized in.
//
// Three APIs answer "how big is the screen" and on a scaled desktop they
// disagree. Measured here on a 1920x1080 display at 125%:
//
//   EnumDisplaySettings(ENUM_CURRENT_SETTINGS)   1920x1080   the mode in force
//   EnumDisplaySettings(ENUM_REGISTRY_SETTINGS)  3840x2400   a mode from months ago
//   GetSystemMetrics / MONITORINFO               1536x864    the DPI-scaled desktop
//
// CreateWindowEx sizes land on screen as physical pixels, so the current display
// mode is the one to build a present window from. The other two each broke it in
// their own direction:
//
//   - the registry mode is the display's *persistent* mode, not the mode it is
//     in. It was preferred here, on the reasoning that ENUM_CURRENT_SETTINGS
//     reads back GTA2's own 640x480 once its video device has taken the display.
//     It does survive that - but it also survived the desktop being moved from
//     3840x2400 down to 1920x1080, so the present window was built at twice the
//     size of the screen and only its top-left quarter was ever visible. That is
//     what a front end "zoomed in" is.
//   - GetSystemMetrics reports the desktop as a DPI-unaware process may address
//     it, which is 4/5 of the real thing at 125%. Sizing the window from that
//     leaves a fifth of the screen showing the desktop behind it.
//
// The takeover case the old comment worried about is guarded rather than
// assumed: a mode too small to be a desktop is not believed, and the registry
// mode - the one the display will go back to - is used instead. As deployed it
// cannot arise anyway, because configure_game.py asserts dxwrapper's
// EnableWindowMode and GTA2 then never changes the mode at all.
void DesktopSize(int* width, int* height) {
    // Anything smaller than this is GTA2's own screen, not a desktop.
    const DWORD kMinDesktopWidth = 800;
    const DWORD kMinDesktopHeight = 600;

    // DWORD, not int: ENUM_CURRENT_SETTINGS and ENUM_REGISTRY_SETTINGS are
    // (DWORD)-1 and (DWORD)-2, which narrow.
    const DWORD modes[2] = {ENUM_CURRENT_SETTINGS, ENUM_REGISTRY_SETTINGS};
    for (DWORD which : modes) {
        DEVMODEA mode = {};
        mode.dmSize = sizeof(mode);
        if (EnumDisplaySettingsA(nullptr, which, &mode) && mode.dmPelsWidth >= kMinDesktopWidth
            && mode.dmPelsHeight >= kMinDesktopHeight) {
            *width = static_cast<int>(mode.dmPelsWidth);
            *height = static_cast<int>(mode.dmPelsHeight);
            return;
        }
    }
    // Last, and the one that is wrong on a scaled desktop - but a window that is
    // too small still shows all of itself, which is the better failure.
    *width = GetSystemMetrics(SM_CXSCREEN);
    *height = GetSystemMetrics(SM_CYSCREEN);
}

std::string GameDirectory() {
    char path[MAX_PATH];
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (slash) *slash = '\0';
    return std::string(path) + "\\data";
}

// Reads the game's DMAP arrays straight out of its map object. The in-memory
// layout is identical to the file, so the same parser handles both.
bool ReadLiveMap(const uint8_t* mapObject, gta2::Map* map, std::string* error) {
    const uint8_t* base = mapObject;
    const uint8_t* columns = *reinterpret_cast<const uint8_t* const*>(mapObject + gta2::kMapObjectColumnsPtr);
    const uint8_t* blocks = *reinterpret_cast<const uint8_t* const*>(mapObject + gta2::kMapObjectBlocksPtr);
    if (!columns || !blocks) {
        *error = "map arrays are not populated";
        return false;
    }

    // Neither array stores its length, so the extents come from the indices the
    // base array actually references.
    uint32_t maxWord = 0;
    for (size_t i = 0; i < gta2::kDmapBaseBytes; i += 4) {
        uint32_t word;
        memcpy(&word, base + i, 4);
        if (word > maxWord && word < kMaxColumnWords) maxWord = word;
    }
    const size_t columnBytes = (static_cast<size_t>(maxWord) + 1 + gta2::kMapLevels) * 4;

    uint32_t maxBlock = 0;
    for (size_t i = 0; i < gta2::kDmapBaseBytes; i += 4) {
        uint32_t word;
        memcpy(&word, base + i, 4);
        const size_t header = static_cast<size_t>(word) * 4;
        if (header + 4 > columnBytes) continue;
        const int count = columns[header] - columns[header + 1];
        for (int b = 0; b < count; ++b) {
            uint32_t index;
            memcpy(&index, columns + header + 4 + static_cast<size_t>(b) * 4, 4);
            if (index > maxBlock && index < kMaxBlocks) maxBlock = index;
        }
    }

    return map->LoadFromDmap(base, columns, columnBytes, blocks,
                             (static_cast<size_t>(maxBlock) + 1) * 12, error);
}

// One chunk of a .gmp file, by its four-letter tag; empty if the file or the
// chunk is missing.
std::vector<uint8_t> FileChunk(const std::string& path, const char* tag) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return {};
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::vector<uint8_t> data(size > 0 ? static_cast<size_t>(size) : 0);
    const bool ok = !data.empty() && fread(data.data(), 1, data.size(), f) == data.size();
    fclose(f);
    if (!ok || data.size() < 6 || memcmp(data.data(), "GBMP", 4) != 0) return {};

    size_t offset = 6;
    while (offset + 8 <= data.size()) {
        uint32_t chunk;
        memcpy(&chunk, &data[offset + 4], 4);
        const size_t body = offset + 8;
        if (body + chunk > data.size()) return {};
        if (memcmp(&data[offset], tag, 4) == 0) {
            return std::vector<uint8_t>(data.begin() + body, data.begin() + body + chunk);
        }
        offset = body + chunk;
    }
    return {};
}

std::vector<uint8_t> FileBlockArray(const std::string& path) {
    const std::vector<uint8_t> dmap = FileChunk(path, "DMAP");
    const size_t pool = gta2::kDmapBaseBytes;
    if (pool + 4 > dmap.size()) return {};
    uint32_t words;
    memcpy(&words, &dmap[pool], 4);
    const size_t countAt = pool + 4 + static_cast<size_t>(words) * 4;
    if (countAt + 4 > dmap.size()) return {};
    uint32_t count;
    memcpy(&count, &dmap[countAt], 4);
    const size_t start = countAt + 4;
    const size_t bytes = (std::min)(static_cast<size_t>(count) * 12, dmap.size() - start);
    return std::vector<uint8_t>(dmap.begin() + start, dmap.begin() + start + bytes);
}

// The map's own lamps (LGHT: 16 bytes each - ARGB, then x, y, z and radius at
// 128 to a tile, then intensity, shape, on and off time), as x, y, z.
std::vector<uint16_t> FileLightPositions(const std::string& path) {
    const std::vector<uint8_t> lght = FileChunk(path, "LGHT");
    std::vector<uint16_t> xyz;
    xyz.reserve(lght.size() / 16 * 3);
    for (size_t i = 0; i + 16 <= lght.size(); i += 16) {
        uint16_t v[3];
        memcpy(v, &lght[i + 4], sizeof(v));
        xyz.insert(xyz.end(), v, v + 3);
    }
    return xyz;
}

// Which style each map is played with, from the game's own level lists: the
// single-player sequence (test1.seq, MainOrBonus / GMPFile / STYFile entries)
// and the multiplayer maps (*.mmp, the same keys under [MapFiles]). A district's
// map shares its style's basename, but its bonus levels do not - lorne2e.gmp is
// played with wil.sty, mike1e.gmp with ste.sty, mike2e.gmp with bil.sty - and
// neither do the multiplayer maps (MP1-comp.gmp is bil.sty). Keys are the
// lowercased map filename.
std::map<std::string, std::string> MapStyles(const std::string& dataDir) {
    std::map<std::string, std::string> styles;
    auto lower = [](std::string s) {
        for (char& c : s) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
        return s;
    };
    auto trim = [](std::string s) {
        const size_t first = s.find_first_not_of(" \t\r\n");
        if (first == std::string::npos) return std::string();
        return s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
    };
    for (const char* pattern : {"\\*.seq", "\\*.mmp"}) {
        WIN32_FIND_DATAA find = {};
        HANDLE handle = FindFirstFileA((dataDir + pattern).c_str(), &find);
        if (handle == INVALID_HANDLE_VALUE) continue;
        do {
            FILE* file = fopen((dataDir + "\\" + find.cFileName).c_str(), "rb");
            if (!file) continue;
            std::string map;
            char line[512];
            while (fgets(line, sizeof(line), file)) {
                std::string text = line;
                const size_t equals = text.find('=');
                if (equals == std::string::npos) continue;
                const std::string key = lower(trim(text.substr(0, equals)));
                const std::string value = trim(text.substr(equals + 1));
                // GMPFile comes first in every entry; the STYFile after it is
                // that map's style.
                if (key == "gmpfile") {
                    map = lower(value);
                } else if (key == "styfile" && !map.empty() && !value.empty()) {
                    styles.emplace(map, value);
                    map.clear();
                }
            }
            fclose(file);
        } while (FindNextFileA(handle, &find));
        FindClose(handle);
    }
    return styles;
}

// The game does not keep the style filename anywhere obvious, so the map is
// identified by matching its live blocks against the .gmp files on disk, and
// its style looked up in the game's level lists (MapStyles). A map they do not
// mention is taken to share its style's basename, which every district does.
std::string DetectStylePath(const uint8_t* mapObject, const std::string& dataDir,
                            std::string* mapPath) {
    const uint8_t* blocks = *reinterpret_cast<const uint8_t* const*>(mapObject + gta2::kMapObjectBlocksPtr);
    if (!blocks) return {};

    WIN32_FIND_DATAA find = {};
    HANDLE handle = FindFirstFileA((dataDir + "\\*.gmp").c_str(), &find);
    if (handle == INVALID_HANDLE_VALUE) return {};

    std::string bestName;
    double bestScore = 0.0;
    do {
        const std::vector<uint8_t> fileBlocks = FileBlockArray(dataDir + "\\" + find.cFileName);
        const size_t common = (std::min)(kMatchBlocks * 12, fileBlocks.size());
        if (common < 12) continue;

        size_t same = 0;
        for (size_t i = 0; i + 12 <= common; i += 12) {
            if (memcmp(blocks + i, &fileBlocks[i], 12) == 0) ++same;
        }
        const double score = static_cast<double>(same) / (common / 12);
        if (score > bestScore) {
            bestScore = score;
            bestName = find.cFileName;
        }
    } while (FindNextFileA(handle, &find));
    FindClose(handle);

    if (bestScore < 0.9 || bestName.empty()) return {};
    *mapPath = dataDir + "\\" + bestName;
    std::string lowerName = bestName;
    for (char& c : lowerName) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
    const std::map<std::string, std::string> styles = MapStyles(dataDir);
    const auto listed = styles.find(lowerName);
    if (listed != styles.end()) {
        Log("map %s is played with %s (from the game's level lists)", bestName.c_str(),
            listed->second.c_str());
        return dataDir + "\\" + listed->second;
    }
    std::string stem = bestName.substr(0, bestName.find_last_of('.'));
    const size_t dash = stem.find('-');
    if (dash != std::string::npos) stem = stem.substr(0, dash);
    return dataDir + "\\" + stem + ".sty";
}

// A window of our own to present into.
//
// GTA2 sets DirectDraw up on its own window during startup, and on Windows 10
// and 11 DirectDraw is itself implemented on Direct3D 9: it takes the window
// into an exclusive fullscreen device before the renderer is even loaded. A
// second swap chain on that same window is tolerated by Microsoft's D3D9 but
// not by RTX Remix, whose Vulkan presentation never completes - the game hangs
// on its first Present with the Remix runtime spinning. Presenting into a
// window we own leaves DirectDraw in sole possession of the game's.
//
// It has to be a *child* of the game's window rather than a popup over it. A
// popup loses the z-order the moment the game is activated, and DirectDraw's
// empty primary surface is then what you see: black while the game has focus,
// and the path traced picture only when you alt-tab away and the game's window
// drops back down. A child window is always painted above its parent's client
// area, so there is no ordering to lose, and it can never take the focus or the
// input away from the game either.
HWND g_presentGameWindow = nullptr;

// The present window covers the game's, so the mouse is over ours, and a click
// there is ours: the game never hears of it, and a click on another top-level
// window takes the activation away from the game, which then pauses itself.
// The game does not use the mouse, but plugins for it do - a front end driven by
// the mouse reads it off the game's window. So a click is refused the
// activation, and the mouse messages go on to the game's window, at the place
// under the cursor in its own client area: exactly what it would have been sent
// with nothing of ours in the way. Not while the F4 menu has the mouse, which
// reads it for itself.
void GiveGameForeground(HWND gameWindow);
// FIX-STABILITY-1: whether the game window is minimised or has lost the focus (WorldView::SetGameParked
// and SetGameActive keep it), so a click on our window while it shows the paused frame brings the game
// back instead of being refused.
bool g_presentGameAway = false;
HWND g_presentWindow = nullptr;   // FIX-FOCUS-HANG: our top-level present window (own_window=2), for RequestGameFocus
bool g_focusHandoff = true;       // FIX-FOCUS-HANG: [renderer] focus_watchdog (0 turns the hand-over off too, for an A/B)

// FIX-FOCUS-HANG (5090 release blocker): GTA2 pauses itself on WM_KILLFOCUS (game::kFocusPausedFlag) and runs
// again only on WM_SETFOCUS to its own window. Our present window is WS_EX_NOACTIVATE, but SetForegroundWindow
// (a launcher, a test harness, the shell after a toast or a popup closes) activates it anyway, and then the game
// window never gets the focus back: the permanent freeze. So the present window never keeps the activation or
// the focus: either one is handed straight back to the game window (on the next message, not inside the
// activation itself), which runs GTA2's own WM_ACTIVATE + WM_SETFOCUS resume path.
constexpr UINT kMsgGiveGameFocus = WM_APP + 0x2F1;   // wparam: why (FocusWhy)
const char* FocusWhyName(WPARAM why) {
    switch (why) {
        case 1: return "the present window was activated";
        case 2: return "the present window got the keyboard focus";
        case 3: return "watchdog: GTA2 paused while the foreground is ours";
        case 4: return "devtools test";
        default: return "asked";
    }
}

LRESULT CALLBACK PresentWndProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_MOUSEACTIVATE) {
        // FIX-FOCUS-HANG: GTA2's own pause flag counts as away too: after a WM_ACTIVATEAPP 0 -> 1 blip (a toast)
        // our own active_ said "back" while GTA2 still waited for WM_SETFOCUS, and every click was refused.
        if ((g_presentGameAway || game::FocusPausedFlag()) && g_presentGameWindow) {
            Log("focus: click on the present window while the game is away (gta2 paused flag %d): giving the game "
                "the foreground", game::FocusPausedFlag());
            GiveGameForeground(g_presentGameWindow);
        }
        return MA_NOACTIVATE;
    }
    if (g_focusHandoff && g_presentGameWindow && window != g_presentGameWindow &&
        ((message == WM_ACTIVATE && LOWORD(wparam) != WA_INACTIVE) || message == WM_SETFOCUS)) {
        static int logged = 0;
        if (logged++ < 200) {
            Log("focus: %s (%s %p, gta2 paused flag %d): handing it to the game window", message == WM_ACTIVATE ?
                "present window activated" : "present window got the keyboard focus", message == WM_ACTIVATE ?
                "previously active" : "focus came from", reinterpret_cast<void*>(message == WM_ACTIVATE ? lparam :
                static_cast<LPARAM>(wparam)), game::FocusPausedFlag());
        }
        PostMessageA(window, kMsgGiveGameFocus, message == WM_ACTIVATE ? 1 : 2, 0);
        return message == WM_ACTIVATE ? DefWindowProcA(window, message, wparam, lparam) : 0;
    }
    if (message == WM_APP + 0x2F2) {   // kMsgTestTakeFocus (devtools)
        const HWND before = GetForegroundWindow();
        SetForegroundWindow(window);
        SetFocus(window);
        Log("devtools: present window takes the focus: foreground %p -> %p, focus %p (present %p, game %p), gta2 "
            "paused flag %d", static_cast<void*>(before), static_cast<void*>(GetForegroundWindow()),
            static_cast<void*>(GetFocus()), static_cast<void*>(window), static_cast<void*>(g_presentGameWindow),
            game::FocusPausedFlag());
        return 0;
    }
    if (message == kMsgGiveGameFocus) {
        if (g_presentGameWindow) {
            const HWND foreground = GetForegroundWindow();
            const HWND focus = GetFocus();
            GiveGameForeground(g_presentGameWindow);
            static int logged = 0;
            if (logged++ < 200) {
                Log("focus: game focus asked for (%s): foreground %p -> %p, focus %p -> %p (game window %p), gta2 "
                    "paused flag %d", FocusWhyName(wparam), static_cast<void*>(foreground),
                    static_cast<void*>(GetForegroundWindow()), static_cast<void*>(focus), static_cast<void*>(GetFocus()),
                    static_cast<void*>(g_presentGameWindow), game::FocusPausedFlag());
            }
        }
        return 0;
    }
    if (message == WM_MOUSEWHEEL) CityMapNoteWheel(GET_WHEEL_DELTA_WPARAM(wparam));   // CITYMAP-1
    if (message == WM_LBUTTONDOWN || message == WM_LBUTTONUP || message == WM_RBUTTONDOWN)   // CITYMAP-1: the map's clicks
        CityMapNoteButton(message == WM_RBUTTONDOWN ? 1 : 0, message != WM_LBUTTONUP);
    const bool mouse = message >= WM_MOUSEFIRST && message <= WM_MOUSELAST
                       && message != WM_MOUSEWHEEL && message != WM_MOUSEHWHEEL;
    if (mouse && g_presentGameWindow && !DebugMenuWantsMouse()) {
        POINT p = {static_cast<short>(LOWORD(lparam)), static_cast<short>(HIWORD(lparam))};
        ClientToScreen(window, &p);
        ScreenToClient(g_presentGameWindow, &p);
        PostMessageA(g_presentGameWindow, message, wparam,
                     MAKELPARAM(static_cast<short>(p.x), static_cast<short>(p.y)));
        return 0;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

// Windows refuses SetForegroundWindow to a process that did not receive the
// last input. Attaching to the input queue of the current foreground window's
// thread for the duration of the call is the accepted way round that.
void GiveGameForeground(HWND gameWindow) {
    if (!gameWindow) return;
    HWND foreground = GetForegroundWindow();
    if (foreground == gameWindow) {
        // FIX-FOCUS-HANG: the foreground alone is not enough: GTA2 resumes on WM_SETFOCUS, so the keyboard
        // focus must be on its window too (GetFocus answers for this thread's queue, the game window's).
        if (GetFocus() != gameWindow && GetWindowThreadProcessId(gameWindow, nullptr) == GetCurrentThreadId())
            SetFocus(gameWindow);
        return;
    }
    const DWORD me = GetCurrentThreadId();
    const DWORD other = foreground ? GetWindowThreadProcessId(foreground, nullptr) : 0;
    const bool attached = other && other != me && AttachThreadInput(me, other, TRUE);
    if (IsIconic(gameWindow)) ShowWindow(gameWindow, SW_RESTORE);
    BringWindowToTop(gameWindow);
    SetForegroundWindow(gameWindow);
    SetFocus(gameWindow);
    if (attached) AttachThreadInput(me, other, FALSE);
    Log("focus: foreground was %p, game window %p, now %p", foreground, gameWindow,
        GetForegroundWindow());
}

HWND CreatePresentWindow(HWND gameWindow, int width, int height, PresentWindow mode) {
    static bool registered = false;
    HINSTANCE instance = GetModuleHandleA(nullptr);
    if (!registered) {
        WNDCLASSA wc = {};
        wc.lpfnWndProc = PresentWndProc;
        wc.hInstance = instance;
        wc.hCursor = LoadCursorA(nullptr, IDC_ARROW);
        wc.lpszClassName = "gta2dx9_present";
        if (!RegisterClassA(&wc)) return nullptr;
        registered = true;
    }
    if (!gameWindow) return nullptr;
    g_presentGameWindow = gameWindow;

    // Without this the game's window is free to paint its own background over
    // the child.
    SetWindowLongA(gameWindow, GWL_STYLE, GetWindowLongA(gameWindow, GWL_STYLE) | WS_CLIPCHILDREN);

    if (mode == PresentWindow::Child) {
        // Child coordinates are relative to the parent's client area, which is
        // the rectangle gbh_Init measured.
        HWND window = CreateWindowExA(WS_EX_NOACTIVATE, "gta2dx9_present", "GTA2",
                                      WS_CHILD | WS_VISIBLE, 0, 0, width, height, gameWindow,
                                      nullptr, instance, nullptr);
        if (window) {
            SetWindowPos(window, HWND_TOP, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        }
        return window;
    }

    // Topmost: a separate top-level window in the topmost band, which sits above
    // the game's window even while the game is the activated one. A child cannot
    // help against a video device that presents past the window manager
    // altogether; this at least competes in the right band.
    // Positioned over the game's window but sized to the render resolution, not
    // to it: the game's window is whatever GTA2's options screen last wrote, and
    // 640x480 of path traced image is not the goal. Centred on the desktop when
    // the render size is larger than the game's window, so a 4K image over a
    // 640x480 game window still lands somewhere sensible.
    RECT gameRect = {0, 0, width, height};
    GetWindowRect(gameWindow, &gameRect);
    int left = gameRect.left;
    int top = gameRect.top;
    // The same measure the render size came from, so the two are comparable. On
    // a scaled desktop GetSystemMetrics answers a different question - see
    // DesktopSize - and mixing the two here put the window half off the screen.
    int screenW = 0, screenH = 0;
    DesktopSize(&screenW, &screenH);
    if (width >= screenW && height >= screenH) {
        left = 0;
        top = 0;
    } else {
        if (left + width > screenW) left = (screenW - width) / 2;
        if (top + height > screenH) top = (screenH - height) / 2;
        if (left < 0) left = 0;
        if (top < 0) top = 0;
    }
    // Created per-monitor DPI-aware whatever the process is, so a size in
    // physical pixels stays one and the window manager never scales the swap
    // chain. See MakeProcessDpiAware in dllmain.cpp for why that matters.
    typedef HANDLE(WINAPI * SetThreadContextFn)(HANDLE);
    static const SetThreadContextFn setThreadContext = reinterpret_cast<SetThreadContextFn>(
        GetProcAddress(GetModuleHandleA("user32.dll"), "SetThreadDpiAwarenessContext"));
    // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
    const HANDLE previous = setThreadContext
        ? setThreadContext(reinterpret_cast<HANDLE>(static_cast<intptr_t>(-4)))
        : nullptr;
    HWND window = CreateWindowExA(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
                                  "gta2dx9_present", "GTA2", WS_POPUP, left, top, width, height,
                                  nullptr, nullptr, instance, nullptr);
    if (previous) setThreadContext(previous);
    if (!window) return nullptr;
    g_presentWindow = window;   // FIX-FOCUS-HANG
    ShowWindow(window, SW_SHOWNOACTIVATE);
    SetWindowPos(window, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
    return window;
}

}  // namespace

// FIX-FOCUS-HANG: from any thread (the stall sampler's watchdog, the devtools test). Posted to our present
// window, so the hand-over runs on the game thread, inside GTA2's own message loop when the game is paused there
// (it dispatches every message of the thread). False when there is no present window of our own.
void SetFocusHandoff(bool on) { g_focusHandoff = on; }

bool RequestGameFocus(int why) {
    return g_presentWindow && g_presentGameWindow &&
           PostMessageA(g_presentWindow, kMsgGiveGameFocus, static_cast<WPARAM>(why), 0) != 0;
}

// FIX-FOCUS-HANG devtools: what a launcher or rc_fclick.ps1 does: our present window made the foreground and
// given the keyboard focus (both ignore WS_EX_NOACTIVATE). Runs on the present window's thread.
constexpr UINT kMsgTestTakeFocus = WM_APP + 0x2F2;
bool TestPresentTakesFocus() {
    return g_presentWindow && PostMessageA(g_presentWindow, kMsgTestTakeFocus, 0, 0) != 0;
}

bool g_blood = kDefaultBlood;
bool g_bloodForced = false;     // whether we are the ones holding the flag up
uint8_t g_bloodGameValue = 0;   // what the game had before we did

void SetBlood(bool on) { g_blood = on; }
bool Blood() { return g_blood; }

// Written every frame rather than once: a demo replay restores the flag from the
// recording, and the debug cheat toggles it, and either would otherwise turn
// blood off behind the setting's back. Turning the setting off hands back the
// value the game had, so a do_blood the player set in the registry survives.
void WorldView::ApplyBlood() {
    uint8_t* flag = reinterpret_cast<uint8_t*>(game::kDoBloodFlag);
    if (g_blood) {
        if (!g_bloodForced) {
            g_bloodGameValue = *flag;
            g_bloodForced = true;
        }
        *flag = 1;
    } else if (g_bloodForced) {
        *flag = g_bloodGameValue;
        g_bloodForced = false;
    }
}

void SetSpawnOffscreen(bool on) { g_spawnOffscreen = on; }
bool SpawnOffscreen() { return g_spawnOffscreen; }
bool SpawnOffscreenActive() { return g_spawnOffscreenActive; }

// Make GTA2's own view rectangle the shape of the frame we draw.
//
// Cars and pedestrians appeared and vanished inside a 16:9 frame's left and
// right margins because everything in gta2.exe that asks "is this on screen" -
// where traffic may be created, the ring pedestrians are placed on, which grid
// cells are drawn, what the recycler may destroy - measures against one
// rectangle, and FUN_0041E7A0 builds that rectangle 4:3. Earlier attempts moved
// the consumers one at a time (a detoured car test, a widened pedestrian ring, a
// padded grid walk, a padded rectangle), and each one that moved alone fell out
// of step with the rest: a spawn point pushed past what the recycler counts as
// seen is destroyed before it arrives, which is how the streets emptied.
//
// This moves the source instead, so every consumer stays consistent with every
// other exactly as it is in the stock game - only wider. Height is untouched:
// the renderer frames the game's own vertical extent, and the half-width scale
// and the aspect are changed by reciprocal amounts so their product, the
// half-height, stays what it was.
void WorldView::MatchGameViewToFrame() {
    // Follow the switch, in both directions and at any time. Applying reads and
    // keeps the original bytes, so turning it off mid-game is a real revert.
    if (g_spawnOffscreen != g_spawnOffscreenActive) {
        if (g_spawnOffscreen) {
            // A site that does not match is a different gta2.exe: give up for
            // good rather than ask again every frame.
            if (!ApplyGamePatches()) g_spawnOffscreen = false;
        } else {
            RevertGamePatches();
        }
        g_spawnOffscreenActive = g_spawnOffscreen;
    }

    // Never narrower than the game's own: a 4:3 or taller frame is already
    // covered by the stock rectangle.
    float widen = 1.0f;
    if (renderer_.Width() > 0 && renderer_.Height() > 0) {
        const float aspect =
            static_cast<float>(renderer_.Width()) / static_cast<float>(renderer_.Height());
        widen = (std::max)(1.0f, aspect / game::kViewAspectRatioStock);
    }
    // A chase or first-person camera sees well beyond the window the game's own
    // camera frames, and the game only creates, draws and removes cars and
    // pedestrians inside that window. So while one of those views is up the
    // window is scaled up as a whole - width and height alike, which is the
    // half-width scale alone since the aspect multiplies it into the height.
    float scale = 1.0f;
    const bool ground = g_viewActive && CurrentViewMode() != ViewMode::Classic;
    if (ground) scale = DensityGameViewScale((std::min)((std::max)(ViewModes().gameViewScale, 1.0f), 4.0f));   // FIX-PERF-8
    g_viewHalfScale = static_cast<int32_t>(game::kViewHalfScaleStock * widen * scale + 0.5f);
    // From the ground the camera looks along either axis, so the window is made
    // square: with the stock 16:9 shape traffic was created six blocks ahead
    // when looking along the short axis, and popped into clear air.
    // FIX-PERF-8: while the grid guard has the window fully back at the game's own size (5+ stars, a shed),
    // its shape is the game's own too, so the game keeps exactly what the classic view keeps.
    g_viewAspect = ground && !DensityClassicWindow() ? static_cast<int32_t>(0x4000 * widen + 0.5f)
                          : static_cast<int32_t>(game::kViewAspectStock / widen + 0.5f);
    // The game's car and people budgets grow with that window (density.cpp);
    // the classic view gets them back as shipped.
    DensityUpdate(ground && g_spawnOffscreenActive, g_viewPlayer.valid, g_viewPlayer.x, g_viewPlayer.y);
    // Pedestrian reactions sized for the street views, and the ai: census (city_ai.cpp).
    CityAiUpdate(ground, g_viewPlayer.ped, g_viewPlayer.valid, g_viewPlayer.x, g_viewPlayer.y);
}

const PlayerState& ViewPlayer() { return g_viewPlayer; }
const char* ViewCameraStatus() { return g_viewStatus; }
bool ViewCameraActive() { return g_viewActive; }
bool StreetPresentation() { return g_presentStreet; }
float StreetPresentationMix() { return g_presentMix; }
float StreetExtrasWeight() { return g_presentExtras; }
bool ViewCameraMoving() { return g_viewMoving; }
bool SeatMoveEye(gta2::Vec3* seatEye) {
    if (!g_seatMove) return false;
    if (seatEye) *seatEye = g_seatMoveEye;
    return true;
}
void ViewCameraAngles(float* yawDegrees, float* pitchDegrees) {
    *yawDegrees = g_viewYaw;
    *pitchDegrees = g_viewPitch;
}
float g_viewSpeed = 0.0f;
float ViewPlayerSpeed() { return g_viewSpeed; }

bool WorldView::FloorAt(float x, float z, float ceiling, float* y) const {
    return ground_.Ready() && ground_.SurfaceAt(x, z, ceiling, y);
}

// Whether a point is inside a block that has any face at all. Map rows run
// north to south, so the row is the mirror the mesh builder uses; a block at
// level L fills L to L+1. The all-empty blocks a column uses as air are not
// solid; a block with only a lid - a road - is.
bool WorldView::Blocked(float x, float y, float z) const {
    if (map_.Empty()) return false;
    const float mapY = static_cast<float>(gta2::kMapHeight) - z;
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(mapY));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return false;
    const int level = static_cast<int>(std::floor(y));
    const gta2::Column& column = map_.ColumnAt(bx, by);
    const int i = level - static_cast<int>(column.offset);
    if (i < 0 || i >= static_cast<int>(column.blocks.size())) return false;
    const uint32_t index = column.blocks[static_cast<size_t>(i)];
    if (index >= map_.BlockCount()) return false;
    const gta2::Block& block = map_.BlockAt(index);
    // A lid, or a solid wall, is a building. A face flagged flat is a fence, a
    // pole, a sign: see-through, and no reason to pull the camera in.
    if (block.lid) return true;
    auto solid = [](const gta2::Face& f) { return f && !f.IsFlat(); };
    return solid(block.left) || solid(block.right) || solid(block.top) || solid(block.bottom);
}

// Blocked without the lid rule and with the game's own collision bit: only a side face the
// game stops peds and cars at (bit 10 of the face word) counts. Under a deck the blocks at
// head height carry the deck's lid and decorative faces (arches, undersides) while the
// passage is walkable, and Blocked called all of it solid (pm-pickup-label-floats-on-wall-and-
// in-air: the line from the eye to a pickup in plain view read as walled, runs tri_label5/6).
bool WorldView::Walled(float x, float y, float z) const {
    if (map_.Empty()) return false;
    const float mapY = static_cast<float>(gta2::kMapHeight) - z;
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(mapY));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return false;
    const int level = static_cast<int>(std::floor(y));
    const gta2::Column& column = map_.ColumnAt(bx, by);
    const int i = level - static_cast<int>(column.offset);
    if (i < 0 || i >= static_cast<int>(column.blocks.size())) return false;
    const uint32_t index = column.blocks[static_cast<size_t>(i)];
    if (index >= map_.BlockCount()) return false;
    const gta2::Block& block = map_.BlockAt(index);
    auto solid = [](const gta2::Face& f) { return f && f.IsWall() && !f.IsFlat(); };
    return solid(block.left) || solid(block.right) || solid(block.top) || solid(block.bottom);
}

// A flat face is a zero-thickness panel on the block's edge: left on the west
// plane x = bx, right on the east plane, top on the north plane, bottom on the
// south (the mesh builder's corners). A camera inside such a block but a few
// centimetres from the panel sees nothing but its texels, so the chase camera
// asks how close it is.
bool WorldView::PanelPush(float x, float y, float z, float clear, float* outX, float* outZ) const {
    if (map_.Empty()) return false;
    const int level = static_cast<int>(std::floor(y));
    float px = x, pz = z;
    bool moved = false;
    // Twice: in a corner of two railings the first push can bring the point to the other.
    for (int pass = 0; pass < 2; ++pass) {
        const float mapY = static_cast<float>(gta2::kMapHeight) - pz;
        const int cbx = static_cast<int>(std::floor(px)), cby = static_cast<int>(std::floor(mapY));
        float bestD = clear, bestNx = 0.0f, bestNz = 0.0f;
        // The eye's level and the one below: a stair's railing is built on the sloped
        // block whose panel rises past the level line.
        for (int lv = level - 1; lv <= level; ++lv)
        for (int by = cby - 1; by <= cby + 1; ++by)
        for (int bx = cbx - 1; bx <= cbx + 1; ++bx) {
            if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) continue;
            const gta2::Column& column = map_.ColumnAt(bx, by);
            const int i = lv - static_cast<int>(column.offset);
            if (i < 0 || i >= static_cast<int>(column.blocks.size())) continue;
            const uint32_t index = column.blocks[static_cast<size_t>(i)];
            if (index >= map_.BlockCount()) continue;
            const gta2::Block& block = map_.BlockAt(index);
            const float x0 = static_cast<float>(bx), x1 = x0 + 1.0f;
            const float z0 = static_cast<float>(gta2::kMapHeight - by - 1), z1 = z0 + 1.0f;
            // A segment of the panel's line in x/z: the nearest point and the way out from it.
            auto consider = [&](const gta2::Face& f, float ax, float az, float bx2, float bz2) {
                if (!(f && f.IsFlat())) return;
                const float sx = bx2 - ax, sz = bz2 - az;
                const float len2 = sx * sx + sz * sz;
                float t = len2 > 0.0f ? ((px - ax) * sx + (pz - az) * sz) / len2 : 0.0f;
                t = (std::max)(0.0f, (std::min)(1.0f, t));
                const float qx = ax + sx * t, qz = az + sz * t;
                float dx = px - qx, dz = pz - qz;
                const float d = std::sqrt(dx * dx + dz * dz);
                if (d >= bestD) return;
                if (d < 1e-4f) { dx = -sz; dz = sx; }   // on the line: either side; the caller checks walls
                const float n = std::sqrt(dx * dx + dz * dz);
                bestD = d; bestNx = dx / n; bestNz = dz / n;
            };
            consider(block.left, x0, z0, x0, z1);
            consider(block.right, x1, z0, x1, z1);
            consider(block.top, x0, z1, x1, z1);
            consider(block.bottom, x0, z0, x1, z0);
        }
        if (bestD >= clear) break;
        px += bestNx * (clear - bestD + 0.002f);
        pz += bestNz * (clear - bestD + 0.002f);
        moved = true;
    }
    if (moved) { *outX = px; *outZ = pz; }
    return moved;
}

bool WorldView::PanelDistance(float x, float y, float z, float* distance) const {
    if (map_.Empty()) return false;
    const float mapY = static_cast<float>(gta2::kMapHeight) - z;
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(mapY));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return false;
    const int level = static_cast<int>(std::floor(y));
    const gta2::Column& column = map_.ColumnAt(bx, by);
    const int i = level - static_cast<int>(column.offset);
    if (i < 0 || i >= static_cast<int>(column.blocks.size())) return false;
    const uint32_t index = column.blocks[static_cast<size_t>(i)];
    if (index >= map_.BlockCount()) return false;
    const gta2::Block& block = map_.BlockAt(index);
    const float zSouth = static_cast<float>(gta2::kMapHeight - by - 1);
    float best = 1e9f;
    bool any = false;
    auto consider = [&](const gta2::Face& f, float d) {
        if (f && f.IsFlat()) { best = (std::min)(best, std::fabs(d)); any = true; }
    };
    consider(block.left, x - static_cast<float>(bx));
    consider(block.right, static_cast<float>(bx + 1) - x);
    consider(block.top, (zSouth + 1.0f) - z);
    consider(block.bottom, z - zSouth);
    // A lamp post is drawn at every one of the map's lamps (DrawProps), and the
    // chase camera resting inside its post sees a black bar across the frame
    // just as it did inside a railing; the post counts as a panel too. Only the
    // lamps of this block and its neighbours can be near.
    // The lamps by map cell, built once (PERF-2: this ran over every lamp of the map for
    // each of the chase camera's clearance tests, 1-4 ms a frame in Industrial).
    static std::vector<std::vector<uint16_t>> lampGrid;
    static size_t lampGridFrom = static_cast<size_t>(-1);
    const std::vector<gta2::Vec3>& lamps = MapLamps();
    if (lampGridFrom != lamps.size()) {
        lampGrid.assign(static_cast<size_t>(gta2::kMapWidth) * gta2::kMapHeight, {});
        for (size_t k = 0; k < lamps.size() && k < 65535; ++k) {
            const int gx = static_cast<int>(std::floor(lamps[k].x)), gz = static_cast<int>(std::floor(lamps[k].z));
            if (gx >= 0 && gx < gta2::kMapWidth && gz >= 0 && gz < gta2::kMapHeight)
                lampGrid[static_cast<size_t>(gz) * gta2::kMapWidth + gx].push_back(static_cast<uint16_t>(k));
        }
        lampGridFrom = lamps.size();
    }
    const int cellX = static_cast<int>(std::floor(x)), cellZ = static_cast<int>(std::floor(z));
    for (int gz = cellZ - 2; gz <= cellZ + 2; ++gz)
    for (int gx = cellX - 2; gx <= cellX + 2; ++gx) {
    if (gx < 0 || gx >= gta2::kMapWidth || gz < 0 || gz >= gta2::kMapHeight) continue;
    for (uint16_t k : lampGrid[static_cast<size_t>(gz) * gta2::kMapWidth + gx]) {
        const gta2::Vec3& at = lamps[k];
        if (std::fabs(at.x - x) > 1.5f || std::fabs(at.z - z) > 1.5f) continue;
        if (at.y - y > 3.5f || y - at.y > 1.0f) continue;   // the post stands below the lamp
        const float dx = at.x - x, dz = at.z - z;
        const float d = std::sqrt(dx * dx + dz * dz) - 0.06f;   // the post's own radius
        best = (std::min)(best, (std::max)(d, 0.0f));
        any = true;
    }
    }
    // The street furniture placed by rule (bins, benches, meters, signs): the
    // same clearance, from the footprints DrawProps kept.
    for (const PropFootprint& p : live_.PlacedProps()) {
        if (std::fabs(p.x - x) > 1.5f || std::fabs(p.z - z) > 1.5f) continue;
        if (y < p.y - 0.2f || y > p.y + p.height + 0.2f) continue;
        const float dx = p.x - x, dz = p.z - z;
        const float d = std::sqrt(dx * dx + dz * dz) - p.radius;
        best = (std::min)(best, (std::max)(d, 0.0f));
        any = true;
    }
    if (any && distance) *distance = best;
    return any;
}

bool WorldView::PropPush(float x, float y, float z, float* outX, float* outZ) const {
    const PropFootprint* inside = nullptr;
    float deepest = 0.0f;
    for (const std::vector<PropFootprint>* list : {&live_.PlacedProps(), &MapObjectFootprints()}) {
        for (const PropFootprint& p : *list) {
            if (y < p.y - 0.2f || y > p.y + p.height + 0.2f) continue;
            const float dx = x - p.x, dz = z - p.z;
            const float depth = p.radius - std::sqrt(dx * dx + dz * dz);
            if (depth > deepest) { deepest = depth; inside = &p; }
        }
    }
    if (!inside) return false;
    float dx = x - inside->x, dz = z - inside->z;
    float len = std::sqrt(dx * dx + dz * dz);
    if (len < 1e-3f) { dx = 1.0f; dz = 0.0f; len = 1.0f; }
    const float want = inside->radius + 0.08f;
    *outX = inside->x + dx / len * want;
    *outZ = inside->z + dz / len * want;
    return true;
}

// The surface under a point, as the game and the camera see it (the ground
// sampler: a real lid, slopes followed), with the lid's ground type. A block
// without a lid is nothing to stand on even when its type bits say "road":
// the game drops a pedestrian through it, which is what the first scene warps
// to another district did.
bool WorldView::GroundAt(float x, float z, float ceiling, float* y, int* type) const {
    if (map_.Empty()) return false;
    float surface = 0.0f;
    if (!FloorAt(x, z, ceiling, &surface)) return false;
    const float mapY = static_cast<float>(gta2::kMapHeight) - z;
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(mapY));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return false;
    const gta2::Column& column = map_.ColumnAt(bx, by);
    // The lidded block whose top is that surface (a slope's lid is its block's top too).
    int found = 0;
    for (size_t i = 0; i < column.blocks.size(); ++i) {
        const uint32_t index = column.blocks[i];
        if (index >= map_.BlockCount()) continue;
        const gta2::Block& block = map_.BlockAt(index);
        if (!block.lid) continue;
        const float top = static_cast<float>(column.offset + static_cast<int>(i) + 1);
        if (std::fabs(top - std::ceil(surface - 1e-3f)) < 0.5f) { found = block.GroundType(); break; }
    }
    if (y) *y = surface;
    if (type) *type = found;
    return true;
}

int WorldView::RoadArrowsAt(float x, float z, float ceiling) const {
    if (map_.Empty()) return 0;
    float surface = 0.0f;
    if (!FloorAt(x, z, ceiling, &surface)) return 0;
    const float mapY = static_cast<float>(gta2::kMapHeight) - z;
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(mapY));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return 0;
    const gta2::Column& column = map_.ColumnAt(bx, by);
    for (size_t i = 0; i < column.blocks.size(); ++i) {
        const uint32_t index = column.blocks[i];
        if (index >= map_.BlockCount()) continue;
        const gta2::Block& block = map_.BlockAt(index);
        if (!block.lid) continue;
        const float top = static_cast<float>(column.offset + static_cast<int>(i) + 1);
        if (std::fabs(top - std::ceil(surface - 1e-3f)) < 0.5f) return block.arrows;
    }
    return 0;
}

void WorldView::Configure(float pitchDegrees, float fovDegrees, bool useGameTiles,
                          PresentWindow present) {
    camera_.SetOrientation(0.0f, pitchDegrees * kDegreesToRadians);
    camera_.SetFovY(fovDegrees * kDegreesToRadians);
    classicPitch_ = pitchDegrees * kDegreesToRadians;
    classicFov_ = fovDegrees * kDegreesToRadians;
    useGameTiles_ = useGameTiles;
    present_ = present;
    Log("camera pitch %.1f deg, fov %.1f deg; tile artwork from %s", pitchDegrees, fovDegrees,
        useGameTiles ? "the game" : "the style file");
}

void WorldView::SetRenderSize(int width, int height) {
    requestedWidth_ = width;
    requestedHeight_ = height;
}

bool WorldView::Initialize(HWND window, int width, int height, std::string* error) {
    dataDir_ = GameDirectory();
    // Both live here, so the pointer is good for the process. The sampler stays
    // empty until a map is loaded, and the sprite pass falls back until it is.
    live_.SetGround(&ground_);
    LightsSetGround(&ground_);
    VehicleFxSetGround(&ground_);   // VEHICLE-FEEL: kerbs under the wheels
    // The first frames the game draws are the front end, which is the same 2D
    // stream the menus use later. Traced once so a broken menu can be compared
    // against a working one.
    overlay_.TraceNextFrames(3);
    gameWindow_ = window;
    window_ = window;

    // What the game thinks its screen is only sets out the HUD; the overlay pass
    // scales that to whatever it is drawn into. So the render size is ours to
    // choose, and defaults to the desktop rather than to GTA2's 640x480.
    int desktopW = 0, desktopH = 0;
    DesktopSize(&desktopW, &desktopH);
    width_ = requestedWidth_ > 0 ? requestedWidth_ : desktopW;
    height_ = requestedHeight_ > 0 ? requestedHeight_ : desktopH;
    if (width_ < 320 || height_ < 240) {
        width_ = width;
        height_ = height;
    }
    // Everything the sizing depends on, in one line: the three answers Windows
    // gives for "how big is the screen" disagree whenever DPI scaling is on, and
    // which one arrived is the first thing to know when the picture is the wrong
    // size.
    {
        typedef UINT(WINAPI * GetDpiForWindowFn)(HWND);
        static GetDpiForWindowFn getDpi = reinterpret_cast<GetDpiForWindowFn>(
            GetProcAddress(GetModuleHandleA("user32.dll"), "GetDpiForWindow"));
        DEVMODEA mode = {};
        mode.dmSize = sizeof(mode);
        EnumDisplaySettingsA(nullptr, ENUM_CURRENT_SETTINGS, &mode);
        // The client rect of our own window is what ImGui lays the F4 menu out
        // in and what the mouse is measured against, so a disagreement with the
        // back buffer is a misplaced cursor rather than a wrong-sized picture.
        Log("render size %dx%d (monitor %dx%d, system metrics %dx%d, display mode %ux%u, "
            "game window %u dpi, game screen %dx%d, ini asked for %dx%d)",
            width_, height_, desktopW, desktopH, GetSystemMetrics(SM_CXSCREEN),
            GetSystemMetrics(SM_CYSCREEN), mode.dmPelsWidth, mode.dmPelsHeight,
            getDpi && window ? getDpi(window) : 0, width, height, requestedWidth_,
            requestedHeight_);
    }
    if (desktopW <= 800 && requestedWidth_ <= 0) {
        Log("WARNING: even the registry display mode reads %dx%d. Set render_width and "
            "render_height in gta2dx9.ini explicitly.", desktopW, desktopH);
    }
    width = width_;
    height = height_;
    if (present_ != PresentWindow::GameWindow) {
        window_ = CreatePresentWindow(window, width, height, present_);
        RECT client = {0, 0, 0, 0};
        if (window_) GetClientRect(window_, &client);
        Log("presenting into our own %s window %p (client %ldx%ld) over the game's %p",
            present_ == PresentWindow::Child ? "child" : "topmost", window_,
            client.right - client.left, client.bottom - client.top, window);
        if (!window_) window_ = window;
        // Our window is topmost and never activated, so if the game was started
        // from another program's window (update.bat's console, a launcher) the
        // game window may never have been given the keyboard and every key goes
        // to that other window. Take the focus for the game explicitly.
        GiveGameForeground(window);
    }
    gta2::SetRendererTrace([](const char* line) { Log("d3d: %s", line); });
    if (EnsureDevice()) return true;
    *error = "device not up yet, retrying from the frame loop";
    return false;
}

// The device does not necessarily come up on the first ask. Under RTX Remix the
// runtime backing D3D9 is a separate 64-bit process that is still starting when
// the game asks its renderer to initialise, and it only finishes once the game
// has run its message loop for a moment - which first happens between frames.
// Retrying from the frame loop is what gives it that moment; failing outright
// here is what used to leave the game sitting at a black menu.
bool WorldView::EnsureDevice() {
    if (ready_) return true;
    if (!window_ || deviceAttempts_ >= kMaxDeviceAttempts) return false;

    ++deviceAttempts_;
    std::string error;
    if (!renderer_.Initialize(window_, width_, height_, &error)) {
        // One line per attempt would be hundreds of them, so only the first and
        // the last are worth keeping.
        if (deviceAttempts_ == 1 || deviceAttempts_ == kMaxDeviceAttempts) {
            Log("device not up on attempt %d: %s", deviceAttempts_, error.c_str());
        }
        return false;
    }
    ready_ = true;
    Log("world view up on hwnd %p at %dx%d after %d attempt(s)", window_, width_, height_,
        deviceAttempts_);
    return true;
}

void WorldView::Shutdown() {
    if (!ready_ && !loadedMapObject_) return;
    ready_ = false;
    loadedMapObject_ = nullptr;
    const HWND ours = window_ != gameWindow_ ? window_ : nullptr;
    window_ = nullptr;  // stops the frame loop bringing the device back up
    // ImGui and the Remix lights both hold device-side or bridge-side objects, so
    // they go first: the menu's font texture belongs to the device we are about
    // to release, and a light handle outliving the bridge is a leak on the far
    // side of it.
    DebugMenuShutdown();
    LightsShutdown();
    RemixApiShutdown();
    // Device-owned textures have to go before the device does.
    overlay_.ReleaseResources();
    live_.ReleaseResources();
    // Before the frames go: the report is the only record of what this session
    // actually built and drew.
    WriteTextureReport();
    CarBodiesReleaseDevice();
    ModelsReleaseDevice();   // its default-pool skin buffers must go before the device
    ReleaseDeviceTextures();
    renderer_.Shutdown();
    if (ours) DestroyWindow(ours);
    Log("world view shut down, device released");
}

void WorldView::SetGameParked(bool parked, const char* why, bool simulated) {
    if (parked == parked_) return;
    if (parked) {
        parked_ = true;
        parkSimulated_ = simulated;
        parkedFrames_ = 0;
        parkedSince_ = GetTickCount();
        Log("focus: game window minimised (%s%s): presenting paused at frame %d, device %p kept, no reset",
            why, simulated ? ", simulated" : "", frameCount_, static_cast<void*>(renderer_.Device()));
        SetGameActive(false, why);
    } else {
        parked_ = false;
        Log("focus: game window restored (%s): presenting again after %lu ms, %d frame(s) skipped",
            why, static_cast<unsigned long>(GetTickCount() - parkedSince_), parkedFrames_);
        parkSimulated_ = false;
    }
    g_presentGameAway = parked_ || !active_;
}

void WorldView::SetGameActive(bool active, const char* why) {
    if (active == active_) return;
    active_ = active;
    g_presentGameAway = parked_ || !active_;
    const bool ownTopmost = window_ && window_ != gameWindow_ && present_ == PresentWindow::Topmost;
    Log("focus: game window %s (%s)%s", active ? "has the focus" : "lost the focus", why,
        ownTopmost ? (active ? "; present window back on top" : "; present window leaves the topmost band") : "");
    if (!ownTopmost) return;
    SetWindowPos(window_, active ? HWND_TOPMOST : HWND_NOTOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
}

void WorldView::AbortFrame() {
    if (IDirect3DDevice9* device = renderer_.Device()) device->EndScene();
}

void WorldView::SetVisibleTileBounds(float minX, float minY, float maxX, float maxY) {
    minX_ = minX;
    minY_ = minY;
    maxX_ = maxX;
    maxY_ = maxY;
    haveBounds_ = maxX > minX && maxY > minY;
}

bool WorldView::EnsureWorldLoaded() {
    const uint8_t* mapObject = game::MapObject();
    if (!mapObject) {
        // Back at the menu. The game has freed its map, so the level's geometry
        // has to go with it - otherwise the last frame of the city stays in the
        // scene, drawn behind the menu and still path traced by Remix, and the
        // menu never appears to come back.
        if (worldUploaded_) {
            Log("level ended: releasing the world mesh");
            renderer_.ReleaseWorld();
            worldUploaded_ = false;
            // The sprite pass must not conform to a map that is no longer there,
            // and the next level's camera should not ease down from this one's
            // rooftops.
            ground_.Clear();
            tileSources_.clear();
            heightSettled_ = false;
            camSettled_ = false;
            camZoom_ = 0.0f;
            // Back to the menu's own scale immediately, rather than keeping the
            // level's until the game next calls gbh_SetWindow.
            overlay_.RevertToWindowSize();
            // Back at the menu is exactly where the 2D stream wants looking at.
            overlay_.TraceNextFrames(3);
        }
        loadedMapObject_ = nullptr;
        return false;
    }
    if (mapObject == loadedMapObject_) return true;

    std::string error;
    // The old ground describes the old map. Cleared here rather than after the
    // rebuild, so a level that fails to load leaves sprites on the fixed lift
    // instead of on a floor from the district before it.
    ground_.Clear();
    if (!ReadLiveMap(mapObject, &map_, &error)) {
        Log("live map read failed: %s", error.c_str());
        loadedMapObject_ = mapObject;  // Do not retry every frame on a bad map.
        return false;
    }

    std::string mapPath;
    const std::string stylePath = DetectStylePath(mapObject, dataDir_, &mapPath);
    gta2::Style style;
    if (stylePath.empty()) {
        Log("could not identify the district for map object %p", mapObject);
        loadedMapObject_ = mapObject;
        return false;
    }
    MemStatsLog("level load: before the style", 1);   // FIX-PERF-4: what each load step keeps
    if (!style.Load(stylePath, &error)) {
        Log("style load failed (%s): %s", stylePath.c_str(), error.c_str());
        loadedMapObject_ = mapObject;
        return false;
    }
    CarBodiesSetInfo(style.CarInfos());
    HudGameFontCapture(style);   // FIX-HUD-5: GTA2's own HUD glyphs for the modern HUD (hud_gamefont.cpp)
    CarArtPrecache(stylePath.c_str());   // PERF-4: every car sprite's artwork, made on a worker
    {
        // Which tiles are grass, for the park trees of the street views: a
        // green-dominant tile with little blue (the water tiles are a teal
        // whose blue is close to their green, so this leaves them out).
        std::vector<uint8_t> grass(static_cast<size_t>(style.TileCount()), 0);
        int grassTiles = 0;
        for (int i = 0; i < style.TileCount(); ++i) {
            const gta2::Tile& tile = style.GetTile(i);
            if (tile.pixels.size() != static_cast<size_t>(gta2::kTileSize) * gta2::kTileSize) continue;
            uint64_t r = 0, g = 0, b = 0, n = 0;
            for (uint32_t px : tile.pixels) {
                if ((px >> 24) == 0) continue;
                r += (px >> 16) & 0xFF; g += (px >> 8) & 0xFF; b += px & 0xFF; ++n;
            }
            if (n < static_cast<uint64_t>(gta2::kTileSize) * gta2::kTileSize / 2) continue;
            r /= n; g /= n; b /= n;
            // The water group (608..619, a teal) just clears the blue test; it is never grass.
            if (i >= 608 && i <= 619) continue;
            // Green over red, or the yellow-green of a sun-dried lawn (Residential's
            // lawns alternate tile 202, 86/87/45, with the greener 216, 78/89/42:
            // the four-neighbour lawn test placed no trees there at all).
            if (g + 2 >= r && r < 112 && g > b + 28 && g < 140) { grass[static_cast<size_t>(i)] = 1; ++grassTiles; }
        }
        SetGrassTiles(grass);
        std::string which;
        for (int i = 0; i < style.TileCount() && which.size() < 200; ++i) if (grass[static_cast<size_t>(i)]) { which += std::to_string(i); which += ' '; }
        Log("park trees: %d grass tiles in the style: %s", grassTiles, which.c_str());
    }
    {
        // The physical palette of each pedestrian remap: a ped's texture palette
        // then names his type (police, gang, medic...) for the 3D people.
        std::vector<int> byRemap;
        for (int r = 0; r < style.PedRemapCount(); ++r) byRemap.push_back(style.PedRemapPalette(r));
        PedRemapsSetPalettes(byRemap);
    }

    // The district's name salts the per-light override keys, so a lamp standing
    // in the same spot in two districts does not share one entry.
    {
        const size_t slash = stylePath.find_last_of('\\');
        std::string district = slash == std::string::npos ? stylePath : stylePath.substr(slash + 1);
        const size_t dot = district.find_last_of('.');
        if (dot != std::string::npos) district = district.substr(0, dot);
        LightsSetScene(district.c_str());
    }

    // What lies on the road rather than standing on it, so the sprite pass can
    // lay it flat instead of lifting it like a car. By code_obj number, which
    // every shipped district shares:
    //   497-502  a blood pool, growing in six steps
    //   515      a pair of drops
    //   516-527  trail strips, 4 wide at three lengths (24, 36, 16), each
    //            fading from solid to sparse - skid marks in grey (palette 257
    //            in game) and blood trails in red, the same artwork either way
    //   528-531  the dots at the end of a trail
    ClearGroundDecalArtwork();
    const int kDecalRanges[][2] = {{497, 502}, {515, 531}};
    for (const auto& range : kDecalRanges) {
        for (int sprite = range[0]; sprite <= range[1]; ++sprite) {
            gta2::SpriteIndices art;
            if (style.SpriteArtwork(gta2::SpriteBase::CodeObj, sprite, &art)) {
                AddGroundDecalArtwork(art.width, art.height, art.indices.data(), art.width);
            }
        }
    }
    Log("ground decals: %d skid, trail and blood sprites registered", GroundDecalArtworkCount());

    // Where each car's lamps are, from the deltas the game lights for them. A
    // car sprite faces down the page - its headlight delta is on the bottom row -
    // so the heading runs along +y and the lamp's offset from the middle, at 64
    // pixels a tile, is where the light goes relative to the car.
    {
        const int cars = style.SpriteCount(gta2::SpriteBase::Car);
        for (const int delta : game::kCarLampDeltas) {
            std::vector<CarLamp> lamps(cars > 0 ? cars : 0);
            int found = 0;
            for (int sprite = 0; sprite < cars; ++sprite) {
                gta2::SpriteIndices art;
                float x = 0.0f, y = 0.0f;
                if (!style.SpriteArtwork(gta2::SpriteBase::Car, sprite, &art) ||
                    !style.SpriteDeltaCentre(gta2::SpriteBase::Car, sprite, delta, &x, &y)) {
                    continue;
                }
                lamps[sprite].valid = true;
                lamps[sprite].along = (y - art.height * 0.5f) / 64.0f;
                lamps[sprite].side = (x - art.width * 0.5f) / 64.0f;
                lamps[sprite].nose = art.height * 0.5f / 64.0f;
                style.SpriteDeltaColour(gta2::SpriteBase::Car, sprite, delta, lamps[sprite].rgb);
                ++found;
            }
            SyntheticSetCarLamps(delta, std::move(lamps));

            // And the lamp's own pixels, for our own lamp quads.
            std::vector<LampArt> arts(cars > 0 ? cars : 0);
            for (int sprite = 0; sprite < cars; ++sprite) {
                gta2::SpriteIndices art;
                LampArt& a = arts[sprite];
                if (style.SpriteArtwork(gta2::SpriteBase::Car, sprite, &art) &&
                    style.SpriteDeltaImage(gta2::SpriteBase::Car, sprite, delta, &a.x0, &a.y0,
                                           &a.width, &a.height, &a.argb)) {
                    a.spriteWidth = art.width;
                    a.spriteHeight = art.height;
                }
            }
            SetCarLampArt(delta, std::move(arts));
            Log("car lamps: delta %d placed from the artwork for %d of %d car sprites", delta,
                found, cars);
        }

        // The race number's other digits: art only, no lamp position, for they are not lamps.
        for (const int delta : game::kRoofNumberExtraDeltas) {
            std::vector<LampArt> arts(cars > 0 ? cars : 0);
            for (int sprite = 0; sprite < cars; ++sprite) {
                gta2::SpriteIndices art;
                LampArt& a = arts[sprite];
                if (style.SpriteArtwork(gta2::SpriteBase::Car, sprite, &art) &&
                    style.SpriteDeltaImage(gta2::SpriteBase::Car, sprite, delta, &a.x0, &a.y0,
                                           &a.width, &a.height, &a.argb)) {
                    a.spriteWidth = art.width;
                    a.spriteHeight = art.height;
                }
            }
            SetCarLampArt(delta, std::move(arts));
        }

        // The dents and doors, whose pixels a car with hand-made artwork has drawn
        // over its body: the game paints them into its own sprite, which that car
        // does not use. Deltas 0-4 are dents and 7-14 the doors' frames.
        for (const int delta : {0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14}) {
            std::vector<LampArt> arts(cars > 0 ? cars : 0);
            int found = 0;
            for (int sprite = 0; sprite < cars; ++sprite) {
                gta2::SpriteIndices art;
                LampArt& a = arts[sprite];
                if (style.SpriteArtwork(gta2::SpriteBase::Car, sprite, &art) &&
                    style.SpriteDeltaImage(gta2::SpriteBase::Car, sprite, delta, &a.x0, &a.y0,
                                           &a.width, &a.height, &a.argb)) {
                    a.spriteWidth = art.width;
                    a.spriteHeight = art.height;
                    ++found;
                }
            }
            SetCarDeltaArt(delta, std::move(arts));
            Log("car deltas: delta %d has artwork for %d of %d car sprites", delta, found, cars);
        }
    }

    // Prefer the game's own artwork over our parse of the style file: the game
    // resolves tile numbers through a remap table, so indexing the file directly
    // yields the right set of textures in the wrong order.
    int overridden = 0;
    tileSources_.assign(style.TileCount(), TileSource{});
    if (useGameTiles_) {
        std::vector<uint32_t> pixels(gta2::kTilePixels);
        for (int tile = 1; tile < style.TileCount(); ++tile) {
            if (ResolveTileImage(tile, pixels.data())) {
                style.OverrideTile(tile, pixels.data());
                const void* record = game::TextureForTile(tile);
                tileSources_[tile].record = record;
                tileSources_[tile].revision =
                    record ? static_cast<const TextureRecord*>(record)->revision : 0;
                ++overridden;
            }
        }
    }
    Log("tile artwork from the game: %d/%d (palettes captured: %d)", overridden,
        style.TileCount(), PaletteCount());

    // Ramp shapes come from the game's own slope table rather than a derived
    // formula: it is the only statement of which way each type climbs and over
    // how many blocks, and it exists only in the running process.
    std::array<gta2::SlopeInfo, gta2::kSlopeTypeCount> slopes = {};
    {
        uint8_t directions[gta2::kSlopeTypeCount] = {};
        uint8_t steps[gta2::kSlopeTypeCount] = {};
        uint8_t stepIndices[gta2::kSlopeTypeCount] = {};
        game::ReadSlopeTable(directions, steps, stepIndices, gta2::kSlopeTypeCount);
        int ramps = 0;
        for (int type = 0; type < gta2::kSlopeTypeCount; ++type) {
            slopes[type].direction = directions[type];
            slopes[type].steps = steps[type];
            slopes[type].step = stepIndices[type];
            if (directions[type] >= 1 && directions[type] <= 4 && steps[type]) ++ramps;
        }
        Log("slope table: %d ramp types read from the game", ramps);
    }

    // The sprite pass stands sprites on the lid this same table shapes. Resolved
    // once, here, and handed to both consumers: two readings of a ramp would be
    // two different floors, and a sprite conformed to the wrong one is exactly
    // the bug conforming exists to remove.
    std::array<gta2::SlopeInfo, gta2::kSlopeTypeCount> resolvedSlopes = {};
    gta2::ResolveSlopeTable(slopes.data(), resolvedSlopes.data());
    ground_.Reset(&map_, resolvedSlopes.data());
    // Which of the lights the game lists are the map's own lamps, the only ones
    // lifted onto these floors.
    {
        const std::vector<uint16_t> mapLights = FileLightPositions(mapPath);
        {
            // For the lamp posts of the ground views: the same lamps, in the
            // renderer's frame, a fraction below the lamp (which is the bulb).
            std::vector<gta2::Vec3> lamps;
            lamps.reserve(mapLights.size() / 3);
            for (size_t i = 0; i + 2 < mapLights.size(); i += 3) {
                lamps.push_back({mapLights[i] / 128.0f, mapLights[i + 2] / 128.0f,
                                 static_cast<float>(gta2::kMapHeight) - mapLights[i + 1] / 128.0f});
            }
            SetMapLamps(lamps);
        }
        LightsSetMapLights(mapLights);
        LightsSetMapLightRecords(FileChunk(mapPath, "LGHT"));
        Log("map lamps: %u in %s", static_cast<unsigned>(mapLights.size() / 3), mapPath.c_str());
    }
    {
        // The map's zones, for the street views' environment rules: the bus
        // stops (zone type 7, named bus...) get a shelter; the "trak" zones seed
        // a flood fill along the elevated track's lid tiles, which gives every
        // rail cell its girders. ZONE records: type, x, y, w, h, name length,
        // name.
        const std::vector<uint8_t> zone = FileChunk(mapPath, "ZONE");
        std::vector<EnvCell> busStops, rail;
        std::vector<std::pair<int, int>> seeds;
        for (size_t p = 0; p + 6 <= zone.size();) {
            const int type = zone[p], zx = zone[p + 1], zy = zone[p + 2], zw = zone[p + 3], zh = zone[p + 4], nl = zone[p + 5];
            if (p + 6 + nl > zone.size()) break;
            std::string name(reinterpret_cast<const char*>(&zone[p + 6]), nl);
            for (char& c : name) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
            p += 6 + nl;
            if (type == 7 && name.find("bus") != std::string::npos) busStops.push_back({zx, zy, 0, 0});
            if (name.compare(0, 4, "trak") == 0) for (int yy = zy; yy < zy + zh; ++yy) for (int xx = zx; xx < zx + zw; ++xx) seeds.push_back({xx, yy});
        }
        auto lidOf = [&](int x, int y, int* tile, int* level) {
            if (x < 0 || x >= gta2::kMapWidth || y < 0 || y >= gta2::kMapHeight) return false;
            const gta2::Column& column = map_.ColumnAt(x, y);
            if (column.blocks.empty() || column.blocks.back() >= map_.BlockCount()) return false;
            const gta2::Block& block = map_.BlockAt(column.blocks.back());
            *tile = block.lid.Tile();
            *level = column.offset + static_cast<int>(column.blocks.size());
            return true;
        };
        // The track tiles sit in one band of the style sheet (540..600 in all
        // three districts); the fill stays on that band and within a level.
        std::vector<uint8_t> seen(static_cast<size_t>(gta2::kMapWidth) * gta2::kMapHeight, 0);
        std::vector<std::pair<int, int>> queue = seeds;
        while (!queue.empty()) {
            const auto [x, y] = queue.back();
            queue.pop_back();
            if (x < 0 || x >= gta2::kMapWidth || y < 0 || y >= gta2::kMapHeight) continue;
            uint8_t& mark = seen[static_cast<size_t>(y) * gta2::kMapWidth + x];
            if (mark) continue;
            mark = 1;
            int tile, level;
            if (!lidOf(x, y, &tile, &level) || tile < 540 || tile > 600) continue;
            int nt, nlvl;
            // Only the track itself gets girders and rails, not the platforms,
            // their hazard stripes or the signs that share the band: the track
            // tiles per style, read off the style sheets (Downtown has no rail).
            auto isTrack = [&](int tile) {
                if (stylePath.find("ste") != std::string::npos) return tile == 572;
                if (stylePath.find("bil") != std::string::npos) return tile == 553 || tile == 562 || tile == 563 || tile == 565;
                return false;
            };
            if (isTrack(tile)) {
                // The track runs the way its tiles run furthest; the ribbon is two
                // cells wide, so a straight piece reads at once. Equal runs are a
                // curve or a crossing: left as the flat tile.
                auto run = [&](int dx, int dy) {
                    int n = 0;
                    for (int k = 1; k <= 5; ++k) {
                        if (!lidOf(x + dx * k, y + dy * k, &nt, &nlvl) || !isTrack(nt) || nlvl != level) break;
                        ++n;
                    }
                    return n;
                };
                const int runX = run(1, 0) + run(-1, 0), runY = run(0, 1) + run(0, -1);
                rail.push_back({x, y, level, runX > runY ? 1 : (runY > runX ? 0 : 2)});
            }
            for (const auto [dx, dy] : {std::pair<int, int>{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
                if (lidOf(x + dx, y + dy, &nt, &nlvl) && nt >= 540 && nt <= 600 && std::abs(nlvl - level) <= 1) queue.push_back({x + dx, y + dy});
            }
        }
        SetEnvCells(rail, busStops);
        CityMapSetLevel(map_, zone, mapPath);   // CITYMAP-1: the city map's graph, labels and picture
        Log("environment: %u rail cells from %u track zone cells, %u bus stops", static_cast<unsigned>(rail.size()),
            static_cast<unsigned>(seeds.size()), static_cast<unsigned>(busStops.size()));
    }

    // Where a partial or corner block is cut, likewise straight from the game
    // rather than assumed. The two outer constants are a sanity check: they must
    // read as an empty and a whole cell, or the addresses are wrong.
    gta2::PartialCuts cuts;
    {
        const float zero = game::CellFraction(game::kCellZeroPtr);
        const float one = game::CellFraction(game::kCellOnePtr);
        const float low = game::CellFraction(game::kCellLowPtr);
        const float high = game::CellFraction(game::kCellHighPtr);
        const bool sane = std::abs(zero) < 0.01f && std::abs(one - 1.0f) < 0.01f && low > 0.0f &&
                          low < high && high < 1.0f;
        if (sane) {
            cuts.low = low;
            cuts.high = high;
        }
        Log("partial block cuts: %.4f / %.4f (bounds %.4f..%.4f) %s", low, high, zero, one,
            sane ? "accepted" : "REJECTED, using defaults");
    }

    MemStatsLog("level load: style and map read", 0);
    gta2::WorldMesh mesh;
    gta2::BuildWorldMesh(map_, style, slopes.data(), cuts, &mesh);
    MemStatsLog("level load: world mesh built", 0);
    // The street views' camera collides with this same mesh (BLOCKER fp-camera-sees-through-wall).
    eyecol::Build(mesh, style);
    MemStatsLog("level load: camera collision built", 0);
    {
        // Tile numbers are per style, so the high-resolution folder and the dump
        // are kept per style: wil, bil, ste.
        std::string leaf = stylePath;
        const size_t slash = leaf.find_last_of("\\/");
        if (slash != std::string::npos) leaf = leaf.substr(slash + 1);
        const size_t dot = leaf.find_last_of('.');
        if (dot != std::string::npos) leaf = leaf.substr(0, dot);
        for (char& c : leaf) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
        gta2::SetTileStyleName(leaf.c_str());
        // DISTRICTS-POC: the facade kit, appended after the camera's collision mesh was built (the kit's
        // small overhangs do not push the street cameras) and after every other batch (classic unchanged).
        const std::string kitStreamPath = gta2::DistrictKitDir() + "\\" + leaf + ".kit2";
        kitStreamFile_ = gta2::DistrictKitEnabled() && GetFileAttributesA(kitStreamPath.c_str()) != INVALID_FILE_ATTRIBUTES ? kitStreamPath : std::string();
        if (gta2::DistrictKitEnabled() && kitStreamFile_.empty()) {
            const size_t vBefore = mesh.vertices.size(), iBefore = mesh.indices.size();
            gta2::DistrictKitStats ks;
            const bool ok = gta2::AppendDistrictKit(style, leaf, &mesh, &ks);
            Log("districts: facade kit %s\\%s.kit %s: %d group(s), %d batch(es), %d triangles, %d vertices, %d skipped, file %u KB, "
                "mesh +%u KB (vertices) +%u KB (indices)", gta2::DistrictKitDir().c_str(), leaf.c_str(), ok ? "loaded" : "NOT loaded",
                ks.groups, ks.batches, ks.triangles, ks.vertices, ks.skipped, static_cast<unsigned>(ks.bytes / 1024),
                static_cast<unsigned>((mesh.vertices.size() - vBefore) * sizeof(gta2::Vertex) / 1024),
                static_cast<unsigned>((mesh.indices.size() - iBefore) * 4 / 1024));
            MemStatsLog("level load: facade kit appended", 0);
        }
    }
    if (!renderer_.UploadWorld(mesh, style, &error)) {
        Log("world upload failed: %s", error.c_str());
        loadedMapObject_ = mapObject;
        return false;
    }

    MemStatsLog("level load: world uploaded", 1);
    // WEATHER-V2 C: the road/pavement lid tiles and, on a Remix device, every wet variant of their
    // textures, made here at level load: creating them in the middle of a frame (p1h) hung the game
    // thread on a heap lock. Off the plain renderer nothing is made.
    // Only with [weather] on at level load (WEATHER-V2: ~58 MB of variants are not paid with the weather off);
    // switched on later, the stepped materials start at the next level load.
    const bool weatherOn = CarBodiesDevIni()[0] && GetPrivateProfileIntA("weather", "enabled", 0, CarBodiesDevIni()) != 0;
    if (renderer_.IsRemixDevice() && !map_.Empty() && !weatherOn) {
        renderer_.SetWetTiles(std::vector<uint8_t>());
        Log("weather: off at level load: no wet variant textures (the stepped wet materials start at the next level load)");
    }
    // WEATHER-V2: the plain renderer's puddles from the same field as Remix's (gutters, ruts, junctions). Baked at
    // every level load (road cells only, 4 MB L8) so weather switched on mid-level has them too; the texture is made on first use.
    if (!renderer_.IsRemixDevice() && !map_.Empty()) {
        const auto t0 = std::chrono::steady_clock::now();
        std::vector<uint8_t> field;
        BuildPuddleField(map_, 2048, &field);
        renderer_.SetPuddleField(field, 2048);
        if (const char* dump = std::getenv("GTA2DX9_WX_FIELD_DUMP")) {   // debug: the field's red channel as a PGM
            if (FILE* f = std::fopen(dump, "wb")) {
                std::fprintf(f, "P5 2048 2048 255\n");
                std::fwrite(field.data(), 1, field.size(), f);
                std::fclose(f);
            }
        }
        Log("weather: plain puddle field 2048x2048 (L8) baked from the map (%.0f ms)",
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    }
    if (renderer_.IsRemixDevice() && !map_.Empty() && weatherOn) {
        std::vector<uint8_t> tiles(1024, 0);
        int n = 0;
        for (int my = 0; my < gta2::kMapHeight; ++my) {
            for (int mx = 0; mx < gta2::kMapWidth; ++mx) {
                for (uint32_t index : map_.ColumnAt(mx, my).blocks) {
                    if (index >= map_.BlockCount()) continue;
                    const gta2::Block& b = map_.BlockAt(index);
                    const int g = b.GroundType();
                    if (b.lid && b.SlopeType() == 0 && (g == 1 || g == 2) && !tiles[b.lid.Tile()]) { tiles[b.lid.Tile()] = 1; ++n; }
                }
            }
        }
        renderer_.SetWetTiles(tiles);
        const int made = renderer_.PreloadWetVariants();
        Log("weather: %d road/pavement lid tiles, %d wet variant textures made at level load", n, made);
        MemStatsLog("level load: wet variants", 1);
    }
    if (!kitStreamFile_.empty()) {
        const bool ok = renderer_.LoadKitStream(kitStreamFile_, style);
        const gta2::KitStreamStats ks = renderer_.KitStreamStatus();
        Log("districts: facade kit stream %s %s: %d chunk entries, %u KB packed in memory", kitStreamFile_.c_str(), ok ? "loaded" : "NOT loaded",
            ks.entries, static_cast<unsigned>(ks.fileBytes / 1024));
        MemStatsLog("level load: facade kit stream loaded", 1);
    }
    if (game::ViewRotation() != 0xFF) {
        Log("WARNING: view rotation is %u, not the 0xFF the tile orientation assumes",
            game::ViewRotation());
    }
    Log("tile artwork: %d tile(s) from gta2dx9_textures_hd", renderer_.HdTileCount());
    Log("world loaded: %s, %zu blocks, %zu triangles, %zu batches, floor %s", stylePath.c_str(),
        map_.BlockCount(), mesh.indices.size() / 3, mesh.batches.size(),
        gta2::WorldSeal() ? "sealed" : "OPEN (the sky shows through any gap)");
    {
        const gta2::StreetFillCounts f = gta2::LastStreetFillCounts();
        Log("street fill (street views only): %s, %d risers, %d floors, %d ground cells, %d overhang ceilings (lattice: %d left open, %d raised to the deck above), %d base sides re-dressed, %d ramp sides, %d deck undersides, %d diagonal undersides, apron tile %d at %.1f",
            gta2::StreetFill() ? "on" : "off (GTA2DX9_STREET_FILL=0)", f.risers, f.floors, f.ground, f.ceilings, f.latticeCeilingsSkipped, f.latticeCeilingsRaised, f.baseSides, f.rampSides, f.decks, f.diagonalUndersides, f.apronTile, f.apronHeight);
        const gta2::OverheadDecalStats od = gta2::LastOverheadDecalStats();
        Log("overhead decals (left out of the street views): %d tile(s), %d lid(s); %d sloped sign lid(s) stood up as boards",
            od.tiles, od.lids, gta2::LastUprightBoards());
        Log("fire escapes (street views, FIX-WORLD-18 qav5): %d flight(s), %d landing(s), %d ladder(s)%s",
            gta2::LastFireEscapeFlights(), gta2::LastFireEscapeLandings(), gta2::LastFireEscapeLadders(),
            getenv("GTA2DX9_FIRE_ESCAPES") && getenv("GTA2DX9_FIRE_ESCAPES")[0] == '0' ? " (off: GTA2DX9_FIRE_ESCAPES=0)" : "");
        Log("roof grates (street views, FIX-WORLD-19): %d see-through slope lid(s) backed by a dark attic%s",
            gta2::LastGrateBackings(),
            getenv("GTA2DX9_GRATE_BACKING") && getenv("GTA2DX9_GRATE_BACKING")[0] == '0' ? " (off: GTA2DX9_GRATE_BACKING=0)" : "");
        Log("lamp poles (street views: round poles for the map's flat pole cards): %s, %d segment(s), %d arm/head solid(s)",
            gta2::LampPoles() ? "on" : "off (GTA2DX9_LAMP_POLES=0)", gta2::LastLampPoleSegments(), gta2::LastLampArms());
        const gta2::MapTreeStats mt = gta2::LastMapTreeStats();
        Log("map trees (street views: models): %d tree(s), %d face(s) left out; grating undersides: %d", mt.trees, mt.faces, gta2::LastGrateUndersides());
        Log("plain window backs (street views: the composed side seen through): %d face(s) left out", gta2::LastPlainPanelSides());
        Log("gantry signals (street views: signal scale %.2f of a block, FIX-WORLD-8 ptrmx22): %d slab(s)", gta2::SignalHeadScale(), gta2::LastSignalHeads());
        const gta2::RailingStats r = gta2::LastRailingStats();
        Log("railings (QB-11): %s, %d tile(s), %d panel(s) from %d flat quads, %d triangles",
            gta2::RailingModels() ? "modelled" : "off (flat panels)", r.tiles, r.panels, r.quadsReplaced, r.triangles);
    }
    loadedMapObject_ = mapObject;
    worldUploaded_ = true;
    // FIX-REMIX-3: the level's light state from the clock, pushed now whatever the view
    // (pt-remix-classic-lit-state-flips-after-3d-roundtrip); a no-op without Remix.
    TimeOfDayRepush("level loaded");
    ghostAt_ = -1;   // FIX-PERF-VSWITCH: this level's street frame, drawn unseen (GhostStreetFrame)
    ghostWait_ = 0;
    levelStartCut_ = true;   // FIX-CAMERA-18 (qaexp32): see ApplyTransition
    levelStartFrame_ = frameCount_;
    MemStatsLog("level load: end (the mesh and style locals are freed after this line)", 0);
    return true;
}

// GTA2 animates ceiling fans, screens and water by changing the artwork behind
// a tile number, not by moving anything: either the style's remap sends the tile
// at a different texture record, or the record's own pixels are rewritten
// between a lock and an unlock. Both show up here, so the static world mesh
// keeps its geometry and only the affected textures are re-uploaded.
void WorldView::RefreshAnimatedTiles() {
    if (!useGameTiles_ || tileSources_.empty()) return;

    std::vector<uint32_t> pixels;
    int updated = 0;
    for (int tile = 1; tile < static_cast<int>(tileSources_.size()); ++tile) {
        if (!renderer_.HasTileTexture(tile)) continue;  // not used by any face
        const void* record = game::TextureForTile(tile);
        if (!record) continue;
        const uint16_t revision = static_cast<const TextureRecord*>(record)->revision;
        TileSource& source = tileSources_[tile];
        if (record == source.record && revision == source.revision) continue;

        if (pixels.empty()) pixels.resize(gta2::kTilePixels);
        if (!ResolveTileImage(tile, pixels.data())) continue;
        renderer_.UpdateTileTexture(tile, pixels.data());
        source.record = record;
        source.revision = revision;
        // A handful of tiles animate; a cap keeps a pathological frame from
        // stalling on hundreds of texture uploads.
        if (++updated >= 64) break;
    }
}

// Street level under a point. Deliberately the *bottom* of the column rather
// than the top: the topmost block is a building roof, so following it makes the
// camera leap whenever it crosses a building.
float WorldView::GroundHeightAt(float tileX, float tileY) const {
    const int x = (std::clamp)(static_cast<int>(tileX), 0, gta2::kMapWidth - 1);
    const int y = (std::clamp)(static_cast<int>(tileY), 0, gta2::kMapHeight - 1);
    const gta2::Column& column = map_.ColumnAt(x, y);
    return column.blocks.empty() ? 0.0f : static_cast<float>(column.offset + 1);
}

void SetCameraSmoothing(float strength) {
    g_cameraSmoothing = strength < 0.0f ? 0.0f : (strength > 4.0f ? 4.0f : strength);
}
float CameraSmoothing() { return g_cameraSmoothing; }

// The view follows the game's camera, but not step for step.
//
// GTA2 moves its camera ahead of the car in the direction the car is going, and
// that lead swings as the car's heading does: at speed, a small turn moves the
// camera a couple of tiles sideways inside a few frames, and the whole world
// lurches with it. The game runs one simulation step to a frame, so there is no
// finer motion to be had from it - only the camera's own path to be eased.
//
// A plain low-pass on the position would trail the car by its speed times the time
// constant at all times, which is a car drifting off the middle of the screen. So
// the filter works on velocity: the game camera's velocity is low-passed, the view
// is moved by that, and a gentler pull brings it back to where the game's camera
// is. At a steady speed the two agree and there is no lag at all; a sudden swing
// in the camera's course is spread over a few tenths of a second instead of
// three frames. The view is never allowed further than kCameraMaxLag tiles from
// the game's camera, since beyond that it would be showing ground the game has
// not drawn yet, and a jump too big to be motion - a respawn, a cut - is followed
// at once.
// A vehicle's condition as the game keeps it (PLAYTHROUGH-7 probe, docs/actions-3d.md
// "Vehicle fields"): the damage is the int16 at +0x74, 0 fresh, capped at 32000 by the
// damage routine FUN_00427180 (add, clamp, then the stages); 32001 marks a wreck
// (FUN_0040F890). The stage byte at +0x8C goes to 3 at 16000 (flames attached, the
// effect list at +0x00 gets an entry) and to 4 at 25000 (a second fire effect); from
// 16000 on the damage also climbs by itself one point a frame, so a burning car
// explodes at 32000 (calls FUN_00426FA0) (32000 - damage) / 30 game seconds later.
// hp = 32000 - damage (0 for a wreck); fire = 0 none, 1 burning (stage 3), 2 burning
// hard (stage 4). False when unreadable.
static bool ReadVehicleCondition(const void* vehicle, int* damage, int* hp, int* fire) {
    if (!game::PlausiblePointer(vehicle)) return false;
    bool ok = true;
    GTA2_TRY {
        const uint8_t* v = static_cast<const uint8_t*>(vehicle);
        const int d = *reinterpret_cast<const int16_t*>(v + 0x74);
        const int stage = *(v + 0x8C);
        *damage = d;
        *hp = d >= 32000 ? 0 : (d < 0 ? 32000 : 32000 - d);
        *fire = d > 32000 ? 0 : (stage >= 4 ? 2 : (stage == 3 ? 1 : 0));
    } GTA2_EXCEPT { ok = false; }
    return ok;
}

// PLAYTHROUGH-9: the peds and cars round the player, for a script that has to aim at
// them ("run over the gang members", "shoot the marked characters", "follow that car").
//
// The ped pool. Its layout is the one of the GTA2 decompilation (CriminalRETeam/gta2_re,
// Char_Pool.hpp, Ped.hpp; built for a later exe, so its global addresses are not ours but
// the structures are: its Car offsets +0x4C next, +0x50 sprite, +0x54 driver, +0x74 damage,
// +0x84 model are the ones this renderer found by probing 9.6): a PedPool object whose +4
// is the head of the live peds, chained through the ped's +0x160. Where 9.6 keeps the
// pointer to that object is not known, so it is looked for once at run time: a word in the
// exe's writable sections whose object's +4 chain reaches the player's own ped.
// Ped fields used (Ped.hpp): +0x16C car, +0x17C gang, +0x200 id, +0x216 health,
// +0x240 occupation, +0x244 remap (byte), +0x278/+0x27C state words.
namespace {
constexpr uintptr_t kPedNext = 0x160;
constexpr uintptr_t kPedGang = 0x17C;
constexpr uintptr_t kPedId = 0x200;
constexpr uintptr_t kPedHealth = 0x216;
constexpr uintptr_t kPedOccupation = 0x240;
constexpr uintptr_t kPedRemap = 0x244;
constexpr uintptr_t kCarId = 0x6C;
uintptr_t g_pedPoolPtr = 0;      // address of the global that holds the PedPool*
int g_pedPoolTries = 0;

bool ChainReaches(uintptr_t pool, const void* target, int* count) {
    bool hit = false;
    int n = 0;
    GTA2_TRY {
        const uint8_t* p = *reinterpret_cast<const uint8_t* const*>(pool + 4);
        for (; game::PlausiblePointer(p) && n < 260; ++n) {
            if (p == target) hit = true;
            p = *reinterpret_cast<const uint8_t* const*>(p + kPedNext);
        }
    } GTA2_EXCEPT { return false; }
    *count = n;
    return hit && n < 260;
}

void FindPedPool(const void* playerPed) {
    if (g_pedPoolPtr || g_pedPoolTries > 6 || !game::PlausiblePointer(playerPed)) return;
    ++g_pedPoolTries;
    // 9.6: the PedPool* is at 0x5E5BBC (found by the scan below on 8 Nov, PLAYTHROUGH-9: pool
    // object, free head at +0, live head at +4, Ped[200] from +8 at a stride of 0x294)
    GTA2_TRY {
        const uintptr_t d = *reinterpret_cast<const uintptr_t*>(0x005E5BBC);
        // unsigned: a pool above 2 GB (large-address-aware) must not turn this negative
        const uintptr_t pp = reinterpret_cast<uintptr_t>(playerPed);
        const uintptr_t off = pp - d - 8;
        if (game::PlausiblePointer(reinterpret_cast<const void*>(d)) && pp >= d + 8 && off % 0x294 == 0 && off / 0x294 < 200) g_pedPoolPtr = 0x005E5BBC;
    } GTA2_EXCEPT { }
    if (g_pedPoolPtr) { Log("view: peds: ped pool at 005E5BBC"); return; }
    const uint8_t* exe = reinterpret_cast<const uint8_t*>(GetModuleHandleA(nullptr));
    if (!exe) return;
    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(exe);
    const IMAGE_NT_HEADERS* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(exe + dos->e_lfanew);
    const IMAGE_SECTION_HEADER* sec = IMAGE_FIRST_SECTION(nt);
    int found = 0;
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (!(sec->Characteristics & IMAGE_SCN_MEM_WRITE)) continue;
        const uintptr_t start = reinterpret_cast<uintptr_t>(exe) + sec->VirtualAddress;
        const uintptr_t size = (std::max)(static_cast<uintptr_t>(sec->Misc.VirtualSize), static_cast<uintptr_t>(sec->SizeOfRawData));
        for (uintptr_t a = start; a + 4 <= start + size; a += 4) {
            const uintptr_t d = *reinterpret_cast<const uintptr_t*>(a);
            if (!game::PlausiblePointer(reinterpret_cast<const void*>(d)) || (d >= start && d < start + size)) continue;
            int n = 0;
            if (!ChainReaches(d, playerPed, &n)) continue;
            Log("view: peds: pool candidate at %08X -> %08X, %d live peds", static_cast<unsigned>(a), static_cast<unsigned>(d), n);
            // a pool's peds are an array of 0x294-byte records from +8 (the player's own
            // ped among them); a chain that merely passes through him is not the pool
            const uintptr_t pp = reinterpret_cast<uintptr_t>(playerPed);
            const uintptr_t off = pp - d - 8;
            if (pp < d + 8 || off % 0x294 != 0 || off / 0x294 >= 200) continue;
            if (!g_pedPoolPtr) g_pedPoolPtr = a;
            if (++found >= 4) break;
        }
    }
    if (!g_pedPoolPtr) Log("view: peds: no ped pool found (try %d)", g_pedPoolTries);
}

const char* PedTypeName(const uint8_t* ped, int occupation) {
    if (ped && game::PlausiblePointer(*reinterpret_cast<const void* const*>(ped + kPedGang))) return "gang";
    switch (occupation) {
        case 0: return "player";
        case 24: case 29: case 37: case 46: return "cop";
        case 25: case 30: return "swat";
        case 26: return "fbi";
        case 27: case 31: case 36: case 39: return "army";
        case 23: case 38: case 47: return "emerg";
        case 19: case 35: case 42: case 48: return "gang";
        case 22: case 44: case 49: return "elvis";
        case 15: case 40: return "mugger";
        case 14: case 16: case 17: case 18: case 33: case 34: return "crim";
        case 28: case 32: return "guard";
        default: return "civ";
    }
}
// The gang a remap is (docs/actions-3d.md, ACTIONS-3D-3: the remap table's types).
const char* RemapName(int remap) {
    switch (remap) {
        case 0: case 1: return "police";
        case 4: return "army";
        case 5: return "redneck";
        case 7: return "scientist";
        case 8: return "zaibatsu";
        case 9: return "krishna";
        case 10: return "russian";
        case 11: return "loony";
        case 12: return "elvis";
        case 13: return "yakuza";
        case 14: return "fireman";
        case 16: return "medic";
        case 17: return "mugger";
        case 22: return "prisoner";
        default: return "civ";
    }
}

struct ArrowTarget { int slot, kind; float x, y; uint32_t obj[4]; };
int ReadArrowTargets(ArrowTarget* out, int max) {
    int n = 0;
    GTA2_TRY {
        const uintptr_t mgrBase = *reinterpret_cast<const uintptr_t*>(0x00672F40);
        if (mgrBase > 0x10000) {
            const uint8_t* arrows = reinterpret_cast<const uint8_t*>(mgrBase + 0x1F18);
            for (int i = 0; i < 17 && n < max; ++i) {
                const uint8_t* slot = arrows + i * 0x7C;
                const int32_t kind = *reinterpret_cast<const int32_t*>(slot + 0x40);
                if (kind != 2 && kind != 3) continue;
                ArrowTarget& t = out[n++];
                t.slot = i; t.kind = kind;
                t.x = *reinterpret_cast<const int32_t*>(slot + 0x44) / 16384.0f;
                t.y = *reinterpret_cast<const int32_t*>(slot + 0x48) / 16384.0f;
                t.obj[0] = *reinterpret_cast<const uint32_t*>(slot + 0x30);
                t.obj[1] = *reinterpret_cast<const uint32_t*>(slot + 0x34);
                t.obj[2] = *reinterpret_cast<const uint32_t*>(slot + 0x38);
                t.obj[3] = *reinterpret_cast<const uint32_t*>(slot + 0x5C);
            }
        }
    } GTA2_EXCEPT { }
    return n;
}
// The arrow that marks this object: one whose target words name it (the ped, or its game
// object), else one of the kind standing within 0.6 blocks of it. -1 when none.
int ArrowFor(const ArrowTarget* t, int n, int kind, uintptr_t a, uintptr_t b, float x, float y) {
    for (int i = 0; i < n; ++i) {
        if (t[i].kind != kind) continue;
        for (uint32_t o : t[i].obj) if (o && (o == a || o == b)) return t[i].slot;
    }
    for (int i = 0; i < n; ++i)
        if (t[i].kind == kind && std::fabs(t[i].x - x) < 0.6f && std::fabs(t[i].y - y) < 0.6f) return t[i].slot;
    return -1;
}

struct CarMemo { float x, y; int frame; float v; };
std::map<uintptr_t, CarMemo> g_carMemo;

// view: peds / view: cars. Every GTA2DX9_PEDS_EVERY frames (10; 0 off), peds within 24
// blocks (nearest 28) and cars within 30 (nearest 20), nearest first.
void LogPedsAndCars(const PlayerState& player, int frameCount) {
    static int every = -1;
    if (every < 0) {
        char buf[8] = {};
        every = GetEnvironmentVariableA("GTA2DX9_PEDS_EVERY", buf, sizeof buf) ? atoi(buf) : 10;
        if (every < 0 || every > 600) every = 10;
    }
    if (every == 0 || (frameCount % every) != 3 % every || !player.ped) return;
    FindPedPool(player.ped);
    // the renderer's own frame count: GTA2 steps once per rendered frame (0x5E8108 is no counter)
    const int gframe = frameCount;
    ArrowTarget arrows[17];
    const int narrows = ReadArrowTargets(arrows, 17);
    // peds
    if (g_pedPoolPtr) {
        struct Row { float d; std::string s; };
        std::vector<Row> rows;
        int live = 0;
        GTA2_TRY {
            const uintptr_t pool = *reinterpret_cast<const uintptr_t*>(g_pedPoolPtr);
            const uint8_t* p = game::PlausiblePointer(reinterpret_cast<const void*>(pool))
                                   ? *reinterpret_cast<const uint8_t* const*>(pool + 4) : nullptr;
            for (; game::PlausiblePointer(p) && live < 260; p = *reinterpret_cast<const uint8_t* const*>(p + kPedNext), ++live) {
                if (p == player.ped) continue;
                const uint8_t* car = *reinterpret_cast<const uint8_t* const*>(p + game::kPedVehicle);
                float x = 0, y = 0, z = 0;
                const bool inCar = game::PlausiblePointer(car);
                if (inCar) {
                    if (!game::ReadPlacement(car, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
                } else {
                    x = *reinterpret_cast<const int32_t*>(p + game::kPedX) * game::kFixedScale;
                    y = *reinterpret_cast<const int32_t*>(p + game::kPedY) * game::kFixedScale;
                    z = *reinterpret_cast<const int32_t*>(p + game::kPedZ) * game::kFixedScale;
                }
                const float d = std::hypot(x - player.x, y - player.y);
                if (d > 24.0f) continue;
                const int occ = *reinterpret_cast<const int32_t*>(p + kPedOccupation);
                const int remap = *reinterpret_cast<const int8_t*>(p + kPedRemap);
                const int st = *reinterpret_cast<const int32_t*>(p + game::kPedState);
                const int sub = *reinterpret_cast<const int32_t*>(p + game::kPedSubState);
                const int hp = *reinterpret_cast<const int16_t*>(p + kPedHealth);
                const unsigned id = *reinterpret_cast<const uint32_t*>(p + kPedId);
                const uintptr_t obj = *reinterpret_cast<const uintptr_t*>(p + game::kPedPhysics);
                const int mark = ArrowFor(arrows, narrows, 2, reinterpret_cast<uintptr_t>(p), obj, x, y);
                char car_s[16] = "-";
                if (inCar) snprintf(car_s, sizeof car_s, "m%d", *reinterpret_cast<const int32_t*>(car + game::kVehicleModel));
                char mark_s[8] = "-";
                if (mark >= 0) snprintf(mark_s, sizeof mark_s, "a%d", mark);
                char b[160];
                snprintf(b, sizeof b, " %u:%s/%s:%d:%d:%.2f,%.2f,%.2f:%d:%d:%d:%s:%s", id, PedTypeName(p, occ), RemapName(remap), remap, occ,
                         x, y, z, st, sub, hp, car_s, mark_s);
                rows.push_back({d, b});
            }
        } GTA2_EXCEPT { }
        std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return a.d < b.d; });
        if (rows.size() > 28) rows.resize(28);
        std::string line;
        for (const Row& r : rows) line += r.s;
        Log("view: peds frame=%d live=%d near=%d%s", gframe, live, static_cast<int>(rows.size()), line.c_str());
    }
    // cars
    {
        struct Row { float d; std::string s; };
        std::vector<Row> rows;
        GTA2_TRY {
            int guard = 0;
            for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
                float x = 0, y = 0, z = 0;
                if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
                const float d = std::hypot(x - player.x, y - player.y);
                CarMemo& m = g_carMemo[reinterpret_cast<uintptr_t>(v)];
                if (gframe > m.frame && m.frame > 0 && gframe - m.frame < 120) {
                    const float inst = std::hypot(x - m.x, y - m.y) / ((gframe - m.frame) / 30.0f);
                    m.v += (inst - m.v) * 0.6f;
                } else if (gframe != m.frame) m.v = 0.0f;
                if (gframe != m.frame) { m.x = x; m.y = y; m.frame = gframe; }
                if (d > 30.0f) continue;
                float hx = 0, hy = 0;
                game::ReadFacing(v, game::kVehiclePlacementPtr, &hx, &hy);
                int dmg = 0, hp = -1, fire = 0;
                if (!ReadVehicleCondition(v, &dmg, &hp, &fire)) { hp = -1; fire = 0; }
                const uint8_t* drv = *reinterpret_cast<const uint8_t* const*>(v + game::kVehicleDriver);
                char drv_s[32] = "-";
                if (drv == player.ped) snprintf(drv_s, sizeof drv_s, "P");
                else if (game::PlausiblePointer(drv)) {
                    const int occ = *reinterpret_cast<const int32_t*>(drv + kPedOccupation);
                    const int remap = *reinterpret_cast<const int8_t*>(drv + kPedRemap);
                    snprintf(drv_s, sizeof drv_s, "%s/%s", PedTypeName(drv, occ), RemapName(remap));
                }
                const int mark = ArrowFor(arrows, narrows, 3, reinterpret_cast<uintptr_t>(v), 0, x, y);
                char mark_s[8] = "-";
                if (mark >= 0) snprintf(mark_s, sizeof mark_s, "a%d", mark);
                char b[160];
                snprintf(b, sizeof b, " %d:m%d:%.2f,%.2f,%.2f:%.2f,%.2f:%.2f:%d:%d:%s:%s", *reinterpret_cast<const int32_t*>(v + kCarId),
                         *reinterpret_cast<const int32_t*>(v + game::kVehicleModel), x, y, z, hx, hy, m.v, hp, fire, drv_s, mark_s);
                rows.push_back({d, b});
            }
        } GTA2_EXCEPT { }
        if (g_carMemo.size() > 2048) g_carMemo.clear();
        std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return a.d < b.d; });
        if (rows.size() > 20) rows.resize(20);
        std::string line;
        for (const Row& r : rows) line += r.s;
        Log("view: cars frame=%d near=%d%s", gframe, static_cast<int>(rows.size()), line.c_str());
    }
}
}  // namespace

void WorldView::UpdateCamera() {
    float tileX = 0.0f, tileY = 0.0f;
    if (!game::CameraPosition(&tileX, &tileY)) return;
    const float rawX = tileX, rawY = tileY;

    LARGE_INTEGER counter, frequency;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&frequency);
    const double now = static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart);
    // GTA2 moves everything one fixed step per rendered frame and scales nothing by
    // time, so with the frame limiter on the camera follows in the same steps: a frame
    // that came 10 ms late moved the world no further, and a camera eased by the wall
    // clock then jumped ahead of it (PERF-2: at a steady speed the chase camera's
    // per-frame step ranged 0.08-0.21 blocks for a car moving 0.13-0.15). Uncapped, the
    // wall clock as before.
    const bool stepLocked = FrameLimitFps() > 0.0f;
    const float kGameStep = 1.0f / 30.0f;
    const float dt = camSettled_ ? (stepLocked ? kGameStep : static_cast<float>(now - camTime_)) : 0.0f;
    camTime_ = now;

    // A chase or first-person view, when one is up: the camera is placed from
    // where the player is rather than from where the game's camera is. See
    // view_modes.h. The classic filter below restarts from the game's camera
    // when the view comes back to it.
    {
        const float viewDt = viewTime_ > 0.0 ? (stepLocked ? kGameStep : static_cast<float>(now - viewTime_)) : 0.0f;
        viewTime_ = now;
        const ViewMode mode = CurrentViewMode();
        const bool wantView = mode != ViewMode::Classic && worldUploaded_;
        PlayerState player;
        if (worldUploaded_) LocatePlayer(&player);
        {
            // FIX-FIGURE-17 (owner10nov B4): the player's key (identity.h) on every exit, entry and view change,
            // and whenever the located ped, its id or how it was found changes.
            static bool wasIn = false, wasValid = false;
            static ViewMode wasMode = ViewMode::Classic;
            if (worldUploaded_ && player.valid) {
                int id = -1;
                if (const uint8_t* me = static_cast<const uint8_t*>(player.ped)) {
                    GTA2_TRY { if (game::PlausiblePointer(me)) id = *reinterpret_cast<const int32_t*>(me + 0x200); } GTA2_EXCEPT { id = -1; }
                }
                const char* why = nullptr;
                char modeWhy[32];
                if (wasValid && wasIn && !player.inVehicle) why = "exit";
                else if (wasValid && !wasIn && player.inVehicle) why = "enter";
                else if (mode != wasMode) {
                    snprintf(modeWhy, sizeof modeWhy, "view %s", mode == ViewMode::Classic ? "classic" : mode == ViewMode::ThirdPerson ? "third" : "first");
                    why = modeWhy;
                }
                IdentityNotePlayerKey(why, player.ped, id, player.pedSprite, player.source, player.inVehicle);
                wasIn = player.inVehicle;
                wasMode = mode;
            }
            wasValid = worldUploaded_ && player.valid;
        }
        // FIX-CAMERA-6 (pfeel4): where he is (renderer frame), every frame and in every view, for the move into
        // the classic view to ride him (the classic camera leads the car at speed).
        locatedValid_ = worldUploaded_ && player.valid;
        if (locatedValid_) { locatedX_ = player.x; locatedZ_ = static_cast<float>(gta2::kMapHeight) - player.y; }
        // FIX-COLLISION: the street props are solid in the 3D views (prop_collision.h). His
        // body is moved out of any he walked into, in the game's own position, before
        // anything here reads where he is. Never in the classic view (no 3D props there,
        // and its frame stays the game's).
        PropCollisionSetPlayerCorrection(0.0f, 0.0f);
        if (!wantView) PropCollisionTakePeds();   // none kept from a frame without the solver
        if (wantView && PropCollisionEnabled()) {
            const float dtc = stepLocked ? kGameStep : static_cast<float>(viewDt);
            const int state = player.valid && !player.inVehicle && player.ped ? ReadPedState(player.ped) : -1;
            // On his feet and free: not knocked down or dead (8, 9), not at a car door (3, 4).
            if (state >= 0 && state != 8 && state != 9 && state != 3 && state != 4 && !BeatActive()) {
                float rx = player.x, rz = static_cast<float>(gta2::kMapHeight) - player.y;
                const float fx = player.facingKnown ? player.dirX : 0.0f, fz = player.facingKnown ? -player.dirY : 0.0f;
                if (PropCollisionResolvePlayer(&rx, &rz, player.z, fx, fz, mode == ViewMode::FirstPerson, ViewModes().fpForwardFoot,
                                               dtc, &WorldView::WalledThunk, this)) {
                    const float gx = rx, gy = static_cast<float>(gta2::kMapHeight) - rz;
                    if (WritePlayerGroundPosition(player.ped, gx, gy)) {
                        PropCollisionSetPlayerCorrection(gx - player.x, (static_cast<float>(gta2::kMapHeight) - gy) -
                                                                            (static_cast<float>(gta2::kMapHeight) - player.y));
                        player.x = gx; player.y = gy;
                    }
                }
            } else {
                PropCollisionStepPushables(dtc, &WorldView::WalledThunk, this);
            }
            // The passers-by drawn this frame, each out of the props it walked into.
            for (const PedBody& b : PropCollisionTakePeds()) {
                if (player.valid && (std::fabs(b.x - player.x) > 9.0f ||
                                     std::fabs((static_cast<float>(gta2::kMapHeight) - b.z) - player.y) > 9.0f)) continue;
                float bx = b.x, bz = b.z;
                if (PropCollisionResolvePed(&bx, &bz, b.y, dtc, &WorldView::WalledThunk, this))
                    WritePlayerGroundPosition(b.ped, bx, static_cast<float>(gta2::kMapHeight) - bz);
            }
        }
        g_viewPlayer = player;
        LARGE_INTEGER locatedAt;
        QueryPerformanceCounter(&locatedAt);
        g_camLocateMs = QpcMs(counter, locatedAt);
        // Where he is, twice a second, in the game's own frame: for reading a
        // session back, and for driving the game from a script (the test
        // harness steers by this line).
        // GTA2DX9_STATE_EVERY=N: the line every N frames instead of 15, for a script
        // driving fast (at 15 a car doing 6 blocks a second moves 3 blocks between samples)
        static int stateEvery = -1;
        if (stateEvery < 0) {
            char buf[8] = {};
            stateEvery = GetEnvironmentVariableA("GTA2DX9_STATE_EVERY", buf, sizeof buf) ? atoi(buf) : 15;
            if (stateEvery < 1 || stateEvery > 60) stateEvery = 15;
        }
        LARGE_INTEGER scriptLines0;
        QueryPerformanceCounter(&scriptLines0);
        if (worldUploaded_ && player.valid && (frameCount_ % stateEvery) == 0) {
            float vx = 0.0f, vy = 0.0f, vd = 0.0f, px = 0.0f, py = 0.0f, pd = 0.0f;
            bool driven = false, parkedDriven = false;
            const void* carPtr = nullptr;
            const void* parkedPtr = nullptr;
            const bool car = NearestVehicle(player.x, player.y, 40.0f, false, &vx, &vy, &vd, &driven, &carPtr);
            const bool parked =
                NearestVehicle(player.x, player.y, 60.0f, true, &px, &py, &pd, &parkedDriven, &parkedPtr);
            // The car's heading and the player's state words, for a script
            // walking up to a door and for reading back what Enter did.
            float chx = 0.0f, chy = 0.0f, phx = 0.0f, phy = 0.0f;
            if (car) VehicleFacing(carPtr, &chx, &chy);
            if (parked) VehicleFacing(parkedPtr, &phx, &phy);
            const PedWords words = ReadPedWords(player.ped);
            Log("view: player x=%.2f y=%.2f z=%.2f face=%.3f,%.3f %s | car %s x=%.2f y=%.2f d=%.2f%s | parked %s x=%.2f y=%.2f d=%.2f"
                " | carhead=%.3f,%.3f parkedhead=%.3f,%.3f ped state=%d sub=%d pend=%d veh=%08X"
                " | me=%08X phys=%08X sprite=%08X cardrv=%08X src=%s carmodel=%d fire=%d",
                player.x, player.y, player.z, player.dirX, player.dirY,
                player.inVehicle ? "driving" : "on foot", car ? "nearest" : "none", vx, vy, vd,
                driven ? " (driven)" : "", parked ? "nearest" : "none", px, py, pd,
                chx, chy, phx, phy, words.state, words.sub, words.pending, static_cast<unsigned>(words.vehicle),
                static_cast<unsigned>(reinterpret_cast<uintptr_t>(player.ped)),
                static_cast<unsigned>(player.ped ? *reinterpret_cast<const uintptr_t*>(
                                                       static_cast<const uint8_t*>(player.ped) + game::kPedPhysics)
                                                 : 0),
                static_cast<unsigned>(reinterpret_cast<uintptr_t>(player.pedSprite)),
                static_cast<unsigned>(carPtr ? *reinterpret_cast<const uintptr_t*>(
                                                   static_cast<const uint8_t*>(carPtr) + game::kVehicleDriver)
                                             : 0),
                player.source,
                car ? *reinterpret_cast<const int32_t*>(static_cast<const uint8_t*>(carPtr) + 0x84) : -1,
                FireSpotsNear(player.x, player.y, 1.6f, player.inVehicle ? player.vehicleSprite : nullptr));
        }
        LARGE_INTEGER scriptLines1;
        QueryPerformanceCounter(&scriptLines1);
        g_scriptLinesMs = QpcMs(scriptLines0, scriptLines1);
        // The mission state, twice a second, for a script playing the game:
        // money and the score keeper's multiplier/lives/death reason (the save
        // slot object at [[0x5EB4FC]+0x38]), the police manager's wanted level
        // ([0x66B7A0]+0x654), the ped's health word (+0x216), the driven car's
        // damage byte (+0x74) and model (+0x84), the key of the message the
        // game last showed (the buffer DISPLAY_MESSAGE fills at 0x5E9808) and
        // the frame counter (0x5E8108). Offsets from the GTAMP memory thread
        // and the save module; every read is guarded, -1 means unreadable.
        // (The damage is a word, see ReadVehicleCondition.)
        // The weapon in the player's hand: the weapon object his ped points at
        // (game::PedWeaponOf: +0x170, its type at +0x1C, its ammunition at +0),
        // 0 with bare hands, -1 while unreadable. The figures and the first-person
        // view model take it from SetPlayerWeapon.
        if (worldUploaded_ && player.valid && player.ped) {
            int weapon = -1, ammo = 0;
            GTA2_TRY {
                weapon = game::PedWeaponOf(static_cast<const uint8_t*>(player.ped), &ammo);
            } GTA2_EXCEPT { weapon = -1; ammo = 0; }
            SetPlayerWeapon(weapon, ammo);
            g_playerAmmoLogged = ammo;
        } else if (!player.valid) {
            SetPlayerWeapon(-1, 0);
        }
        // GTA2DX9_LOG_CAR_WORDS=1: every word of the player's vehicle object (0x140
        // bytes) and of the object its +0x58 names that changed since the last look,
        // every third frame, to find the car's health and burning fields. A probe,
        // off by default.
        {
            static int carProbe = -1;
            if (carProbe < 0) { char buf[8] = {}; carProbe = GetEnvironmentVariableA("GTA2DX9_LOG_CAR_WORDS", buf, sizeof buf) && buf[0] == '1'; }
            static const void* lastVeh = nullptr;
            const void* target = nullptr;
            if (carProbe && worldUploaded_ && player.valid && (frameCount_ % 3) == 0) {
                // the player's car, else the car watched last while it is still live
                // and within 15 blocks, else the nearest car within 8 (shooting one)
                if (player.inVehicle && player.vehicle) target = player.vehicle;
                GTA2_TRY {
                    if (!target && lastVeh) {
                        int guard = 0;
                        for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
                            if (v != lastVeh) continue;
                            float cx = 0, cy = 0, cz = 0;
                            if (game::ReadPlacement(v, game::kVehiclePlacementPtr, &cx, &cy, &cz) && std::hypot(cx - player.x, cy - player.y) < 15.0f) target = v;
                            break;
                        }
                    }
                } GTA2_EXCEPT { target = nullptr; }
                if (!target) {
                    float vx = 0, vy = 0, vd = 0; bool dr = false;
                    if (!NearestVehicle(player.x, player.y, 8.0f, false, &vx, &vy, &vd, &dr, &target)) target = nullptr;
                }
            }
            if (target) {
                constexpr size_t kCarWords = 0x140 / 4, kSubWords = 0x100 / 4;
                static uint32_t lastCar[kCarWords] = {}, lastSub[kSubWords] = {};
                static uintptr_t lastSubPtr = 0;
                uint32_t nowCar[kCarWords] = {}, nowSub[kSubWords] = {};
                uintptr_t subPtr = 0;
                bool ok = true;
                GTA2_TRY {
                    memcpy(nowCar, target, sizeof(nowCar));
                    subPtr = nowCar[0x58 / 4];
                    if (game::PlausiblePointer(reinterpret_cast<const void*>(subPtr))) memcpy(nowSub, reinterpret_cast<const void*>(subPtr), sizeof(nowSub));
                    else subPtr = 0;
                } GTA2_EXCEPT { ok = false; }
                if (ok) {
                    std::string line;
                    if (lastVeh != target) {
                        line = "new car";
                        for (size_t i = 0; i < kCarWords; ++i) { char b[24]; snprintf(b, sizeof b, " %02X:%08X", static_cast<unsigned>(i * 4), nowCar[i]); line += b; }
                        Log("car words: %p model %d %s", target, static_cast<int>(nowCar[0x84 / 4]), line.c_str());
                        line.clear();
                        memcpy(lastCar, nowCar, sizeof(nowCar));
                        lastVeh = target;

                    }
                    // GTA2DX9_PROBE_CARDMG=N (probe only): the player's car starts at damage N, so
                    // a few wall hits take it through the game's own smoke/fire/explosion stages
                    static const void* damagedVeh = nullptr;
                    char dbuf[16] = {};
                    if (player.inVehicle && target == player.vehicle && target != damagedVeh &&
                        GetEnvironmentVariableA("GTA2DX9_PROBE_CARDMG", dbuf, sizeof dbuf)) {
                        damagedVeh = target;
                        const int n = atoi(dbuf);
                        GTA2_TRY {
                            int16_t* dmg = reinterpret_cast<int16_t*>(static_cast<uint8_t*>(const_cast<void*>(target)) + 0x74);
                            if (n > 0 && n < 32000 && *dmg < n) { *dmg = static_cast<int16_t>(n); Log("car words: probe set damage %d", n); }
                        } GTA2_EXCEPT {}
                    }
                    for (size_t i = 0; i < kCarWords; ++i) {
                        if (nowCar[i] != lastCar[i]) { char b[40]; snprintf(b, sizeof b, " c%02X:%08X->%08X", static_cast<unsigned>(i * 4), lastCar[i], nowCar[i]); line += b; }
                        lastCar[i] = nowCar[i];
                    }
                    if (subPtr != lastSubPtr) { char b[40]; snprintf(b, sizeof b, " sub=%08X", static_cast<unsigned>(subPtr)); line += b; memcpy(lastSub, nowSub, sizeof(nowSub)); lastSubPtr = subPtr; }
                    for (size_t i = 0; i < kSubWords && subPtr; ++i) {
                        if (nowSub[i] != lastSub[i]) { char b[40]; snprintf(b, sizeof b, " s%02X:%08X->%08X", static_cast<unsigned>(i * 4), lastSub[i], nowSub[i]); line += b; }
                        lastSub[i] = nowSub[i];
                    }
                    if (!line.empty()) Log("car words: f%d%s", static_cast<int>(frameCount_), line.c_str());
                }
            }
        }
        if (worldUploaded_ && player.valid) {
            LARGE_INTEGER p0, p1;
            QueryPerformanceCounter(&p0);
            LogPedsAndCars(player, frameCount_);
            QueryPerformanceCounter(&p1);
            g_scriptLinesMs += QpcMs(p0, p1);
        }
        if (worldUploaded_ && player.valid && (frameCount_ % 15) == 7) {
            int money = GameSaveMoney();
            int mult = -1, lives = -1, death = -1, wanted = -1, health = -1, carDamage = -1, carModel = -1, frame = -1;
            int carHp = -1, carFire = -1, tcarHp = -1, tcarFire = -1, tcarDamage = -1;
            float tcarX = 0.0f, tcarY = 0.0f;
            char msg[20] = "";
            GTA2_TRY {
                const uintptr_t playerObj = *reinterpret_cast<const uintptr_t*>(0x005EB4FC);
                const uintptr_t keeper = playerObj > 0x10000 ? *reinterpret_cast<const uintptr_t*>(playerObj + 0x38) : 0;
                if (keeper > 0x10000) {
                    mult = *reinterpret_cast<const int32_t*>(keeper + 0x6BC);
                    lives = *reinterpret_cast<const int32_t*>(keeper + 0x684);
                    death = *reinterpret_cast<const int32_t*>(keeper + 0x44);
                }
                const uintptr_t police = *reinterpret_cast<const uintptr_t*>(0x0066B7A0);
                if (police > 0x10000) wanted = *reinterpret_cast<const int32_t*>(police + 0x654);
                if (player.ped) health = *reinterpret_cast<const uint16_t*>(static_cast<const uint8_t*>(player.ped) + 0x216);
                if (player.inVehicle && player.vehicle) {
                    if (!ReadVehicleCondition(player.vehicle, &carDamage, &carHp, &carFire)) carDamage = carHp = carFire = -1;
                    carModel = *reinterpret_cast<const int32_t*>(static_cast<const uint8_t*>(player.vehicle) + 0x84);
                }
                const char* buf = reinterpret_cast<const char*>(0x005E9808);
                int n = 0;
                for (; n < 19 && buf[n] >= 0x20 && buf[n] < 0x7F; ++n) msg[n] = buf[n];
                msg[n] = '\0';
                frame = *reinterpret_cast<const int32_t*>(0x005E8108);
            } GTA2_EXCEPT {
            }
            // The mission's target car: the first objective arrow of kind 3 (a vehicle)
            // whose +0x34 names a live vehicle (the Z-Type, PIZZA CAKE's van, a Pickup).
            GTA2_TRY {
                const uintptr_t mgrBase = *reinterpret_cast<const uintptr_t*>(0x00672F40);
                if (mgrBase > 0x10000) {
                    const uint8_t* arrows = reinterpret_cast<const uint8_t*>(mgrBase + 0x1F18);
                    for (int i = 0; i < 17 && tcarHp < 0; ++i) {
                        const uint8_t* slot = arrows + i * 0x7C;
                        if (*reinterpret_cast<const int32_t*>(slot + 0x40) != 3) continue;
                        const void* car = *reinterpret_cast<const void* const*>(slot + 0x34);
                        if (!game::PlausiblePointer(car)) continue;
                        int guard = 0;
                        for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
                            if (v != car) continue;
                            float cz = 0.0f;
                            game::ReadPlacement(v, game::kVehiclePlacementPtr, &tcarX, &tcarY, &cz);
                            if (!ReadVehicleCondition(v, &tcarDamage, &tcarHp, &tcarFire)) tcarHp = tcarFire = -1;
                            break;
                        }
                    }
                }
            } GTA2_EXCEPT { tcarHp = tcarFire = -1; }
            // cardmg is the damage word (+0x74, 0..32000; it was read as a byte before,
            // which wrapped); carhp = 32000 - damage, carfire 0/1/2 (none, burning, hard);
            // the same for the target car as tcar*, -1 when there is none.
            Log("view: mission money=%d mult=%d lives=%d death=%d wanted=%d health=%d cardmg=%d carmodel=%d msg=%s frame=%d weapon=%s(%d) ammo=%d"
                " carhp=%d carfire=%d tcarhp=%d tcarfire=%d tcar=%.1f,%.1f",
                money, mult, lives, death, wanted, health, carDamage, carModel, msg, frame, WeaponName(PlayerWeapon()), PlayerWeapon(),
                g_playerAmmoLogged, carHp, carFire, tcarHp, tcarFire, tcarX, tcarY);
            // GTA2DX9_LOG_PED_WORDS=1: every 32-bit word of the player's ped that
            // changed since the last look, bar the ones known to move every frame
            // (position, state, timers), to find the fields nobody has mapped yet
            // (the weapon in hand, its ammunition). A probe, off by default.
            {
                static int probe = -1;
                if (probe < 0) { char buf[8] = {}; probe = GetEnvironmentVariableA("GTA2DX9_LOG_PED_WORDS", buf, sizeof buf) && buf[0] == '1'; }
                if (probe && player.ped) {
                    // The weapon objects as the game keeps them: the inventory's
                    // selected slot, the weapon in hand (type, ammo), the ped's +0x254,
                    // and every slot of the inventory that holds a weapon (type/ammo).
                    GTA2_TRY {
                        const uint8_t* ped = static_cast<const uint8_t*>(player.ped);
                        const uint8_t* inv = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedWeaponInventory);
                        const uint8_t* cur = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedCurrentWeapon);
                        const int32_t p254 = *reinterpret_cast<const int32_t*>(ped + 0x254);
                        int sel = -2, curType = -1, curAmmo = -1;
                        std::string slots;
                        if (game::PlausiblePointer(inv)) {
                            sel = *reinterpret_cast<const int16_t*>(inv + game::kInventorySelected);
                            for (int i = 0; i < game::kInventorySlotCount; ++i) {
                                const uint8_t* w = *reinterpret_cast<const uint8_t* const*>(inv + game::kInventorySlots + i * 4);
                                if (!game::PlausiblePointer(w)) continue;
                                char b[48]; snprintf(b, sizeof b, " %d:t%d/a%d", i, *reinterpret_cast<const int32_t*>(w + game::kWeaponType),
                                                     *reinterpret_cast<const int16_t*>(w + game::kWeaponAmmo));
                                slots += b;
                            }
                        }
                        if (game::PlausiblePointer(cur)) {
                            curType = *reinterpret_cast<const int32_t*>(cur + game::kWeaponType);
                            curAmmo = *reinterpret_cast<const int16_t*>(cur + game::kWeaponAmmo);
                        }
                        Log("weapon probe: inv %p sel %d cur %p type %d ammo %d p254 %d slots%s", static_cast<const void*>(inv), sel,
                            static_cast<const void*>(cur), curType, curAmmo, p254, slots.c_str());
                    } GTA2_EXCEPT {
                        Log("weapon probe: unreadable");
                    }
                    static std::vector<uint32_t> last;
                    static const void* lastPed = nullptr;
                    constexpr size_t kWords = 0x800 / 4;
                    uint32_t now[kWords] = {};
                    bool ok = true;
                    GTA2_TRY { memcpy(now, player.ped, sizeof(now)); } GTA2_EXCEPT { ok = false; }
                    if (ok) {
                        if (lastPed != player.ped || last.size() != kWords) { last.assign(now, now + kWords); lastPed = player.ped; Log("ped words: new ped %p", player.ped); }
                        std::string line;
                        for (size_t i = 0; i < kWords; ++i) {
                            const size_t off = i * 4;
                            if ((off >= 0x1A0 && off < 0x1C0) || (off >= 0x270 && off < 0x2A0) || off == 0x210 || off == 0x214 || off == 0x218 || off == 0x21C) continue;
                            if (now[i] != last[i]) {
                                char b[64]; snprintf(b, sizeof b, " +0x%03X:%08X->%08X", static_cast<unsigned>(off), last[i], now[i]);
                                line += b;
                            }
                            last[i] = now[i];
                        }
                        if (!line.empty()) Log("ped words:%s", line.c_str());
                    }
                }
            }
            // The script's objective arrows: the arrow manager at [0x672F40]+0x1F18
            // holds seventeen slots of 0x7C bytes (hud_pass.cpp). A slot in use has
            // its type at +0x20 (1..3 the gang phone markers, 4 the information
            // phones; a mission's own arrow is whatever the script allocates), the
            // target kind at +0x40 and the target position at +0x44/+0x48/+0x4C as
            // 18.14 fixed point (16384 = one block), as the probe of 7 Nov showed.
            // One line, every half second: slot:type:kind:x,y,z for every slot
            // with a target, so a script can tell which objective is current.
            GTA2_TRY {
                const uintptr_t mgrBase = *reinterpret_cast<const uintptr_t*>(0x00672F40);
                if (mgrBase > 0x10000) {
                    const uint8_t* arrows = reinterpret_cast<const uint8_t*>(mgrBase + 0x1F18);
                    char line[900]; int len = 0;
                    for (int i = 0; i < 17 && len < 800; ++i) {
                        const uint8_t* slot = arrows + i * 0x7C;
                        const int32_t type = *reinterpret_cast<const int32_t*>(slot + 0x20);
                        const int32_t kind = *reinterpret_cast<const int32_t*>(slot + 0x40);
                        const int32_t fx = *reinterpret_cast<const int32_t*>(slot + 0x44);
                        const int32_t fy = *reinterpret_cast<const int32_t*>(slot + 0x48);
                        const int32_t fz = *reinterpret_cast<const int32_t*>(slot + 0x4C);
                        const uint32_t obj = *reinterpret_cast<const uint32_t*>(slot + 0x5C);
                        const uint32_t d0 = *reinterpret_cast<const uint32_t*>(slot + 0x30);
                        const uint32_t d1 = *reinterpret_cast<const uint32_t*>(slot + 0x34);
                        const uint32_t d2 = *reinterpret_cast<const uint32_t*>(slot + 0x38);
                        if (type == 0 && kind == 0 && fx == 0 && fy == 0) continue;
                        len += snprintf(line + len, sizeof(line) - len, " %d:%d:%d:%.2f,%.2f,%.2f:%08X:%08X,%08X,%08X", i, type, kind,
                                        fx / 16384.0, fy / 16384.0, fz / 16384.0, obj, d0, d1, d2);
                    }
                    Log("view: arrows%s", line);
                }
            } GTA2_EXCEPT {
            }
        }
        ViewQueries queries;
        queries.context = this;
        queries.floorAt = &WorldView::FloorThunk;
        queries.blocked = &WorldView::BlockedThunk;
        queries.walled = &WorldView::WalledThunk;
        queries.panelDistance = &WorldView::PanelThunk;
        queries.panelPush = &WorldView::PanelPushThunk;
        queries.groundAt = &WorldView::GroundThunk;
        queries.propPush = &WorldView::PropThunk;
        queries.roadArrows = &WorldView::ArrowsThunk;
        ViewModeSetQueries(queries);
        LARGE_INTEGER solveT0, solveT1;
        QueryPerformanceCounter(&solveT0);
        g_camProbesMs = QpcMs(locatedAt, solveT0);
        const bool placed = wantView && viewSolver_.Update(player, queries, viewDt, &camera_);
        QueryPerformanceCounter(&solveT1);
        g_solverMs = QpcMs(solveT0, solveT1);
        if (viewSolver_.Status() != g_viewStatus) {
            // Every change of what the solver is doing, for reading a session back.
            Log("view: %s (player %s, source %s)", viewSolver_.Status(), player.valid ? "found" : "not found",
                player.source);
        }
        g_viewStatus = viewSolver_.Status();
        ViewModePushRemixOptions(placed);
        // A view that cannot find the player this frame - he is being arrested,
        // has just died, the game is between two bodies - holds its last camera
        // for a couple of seconds rather than cutting to the sky and back.
        // Five seconds covers the game's WASTED / BUSTED sequence, which ends with
        // the new body at the hospital or police station being found again.
        if (wantView && !placed && viewActive_ && viewLostFrames_ < 150) {
            ++viewLostFrames_;
            return;
        }
        if (placed) viewLostFrames_ = 0;
        if (!wantView) lostFallback_ = false;   // the key went to classic: a later V is a V
        if (placed) {
            g_viewActive = true;
            viewActive_ = true;
            g_viewYaw = viewSolver_.yawDegrees;
            g_viewPitch = viewSolver_.pitchDegrees;
            g_viewSpeed = viewSolver_.speed;
            camSettled_ = false;
            heightSettled_ = false;
            // The HUD's world-anchored parts were laid out against the game's
            // top-down camera and have no place in this view; left where the
            // game put them.
            SetHudCameraMap(HudCameraMap{});
            // What the picture shows (figures, models, the player's own body hidden from
            // his eyes, car bodies with height) follows the camera's move, not the key:
            // ApplyTransition -> ApplyPresentation (FIX-SMOOTH-SWITCH).
            ApplyTransition(viewDt, mode);
            return;
        }
        if (viewActive_) {
            viewActive_ = false;
            lostFallback_ = wantView;   // FIX-CAMERA-8: lost, not V (see ApplyTransition)
            camera_.SetOrientation(0.0f, classicPitch_);
            camera_.SetFovY(classicFov_);
            camera_.SetRoll(0.0f);
        }
        g_viewActive = false;
        // The street presentation stays up while the camera rises out of a street view,
        // and is handed back to the classic one part way up (ApplyPresentation, called
        // from ApplyTransition at the end of the classic camera below).
    }

    const float k = g_cameraSmoothing;
    if (k < 0.01f) {
        camSettled_ = false;
    } else {
        const float jump = std::hypot(rawX - camX_, rawY - camY_);
        if (!camSettled_ || dt > 0.25f || jump > 4.0f) {
            camX_ = rawX;
            camY_ = rawY;
            camVX_ = camVY_ = 0.0f;
            camRawX_ = rawX;
            camRawY_ = rawY;
            camSettled_ = true;
        } else if (dt >= 1e-4f) {
            // A step bigger than any car makes in one frame is a cut, not motion.
            const float step = std::hypot(rawX - camRawX_, rawY - camRawY_);
            const float vx = step > 3.0f ? 0.0f : (rawX - camRawX_) / dt;
            const float vy = step > 3.0f ? 0.0f : (rawY - camRawY_) / dt;
            camRawX_ = rawX;
            camRawY_ = rawY;
            const float follow = 1.0f - std::exp(-dt / (kCameraVelocityTau * k));
            camVX_ += (vx - camVX_) * follow;
            camVY_ += (vy - camVY_) * follow;
            camX_ += camVX_ * dt;
            camY_ += camVY_ * dt;
            const float pull = 1.0f - std::exp(-dt / (kCameraPullTau * k));
            camX_ += (rawX - camX_) * pull;
            camY_ += (rawY - camY_) * pull;
            const float lag = std::hypot(camX_ - rawX, camY_ - rawY);
            const float most = kCameraMaxLag * (std::min)(k, 1.5f);
            if (lag > most) {
                const float shrink = most / lag;
                camX_ = rawX + (camX_ - rawX) * shrink;
                camY_ = rawY + (camY_ - rawY) * shrink;
            }
            if (std::fabs(rawX - camX_) < kCameraSnap && std::fabs(rawY - camY_) < kCameraSnap &&
                std::fabs(camVX_) < kCameraSnap && std::fabs(camVY_) < kCameraSnap) {
                camX_ = rawX;
                camY_ = rawY;
                camVX_ = camVY_ = 0.0f;
            }
        }
        tileX = camX_;
        tileY = camY_;
    }

    // Ground height is a per-tile step function, so following it directly makes
    // the camera bob every time it crosses a tile edge. Ease toward it instead.
    const float desired = GroundHeightAt(tileX, tileY);
    if (!heightSettled_) {
        smoothedHeight_ = desired;
        heightSettled_ = true;
    } else {
        smoothedHeight_ += (desired - smoothedHeight_) * kHeightFollowRate;
        if (std::fabs(desired - smoothedHeight_) < kCameraSnap) smoothedHeight_ = desired;
    }

    // Map rows run north to south, so the row is mirrored exactly the way the
    // mesh builder mirrors it.
    const gta2::Vec3 target{tileX, smoothedHeight_,
                            static_cast<float>(gta2::kMapHeight) - tileY};

    // Zoom comes from the camera struct's continuous visible extent. The tile
    // rectangle handed to gbh_SetCamera is the same window rounded out to whole
    // tiles, so driving zoom from it makes the view step as the camera crosses
    // tile boundaries even when the game is not zooming at all.
    game::ViewExtent extent;
    if (game::VisibleExtent(&extent)) {
        visibleTiles_ = extent.Height();
    }
    if (visibleTiles_ <= 0.01f) {
        // No game camera to frame (between levels): the classic presentation, as before.
        g_presentStreet = false; g_presentMix = 0.0f; g_presentExtras = 0.0f; g_presentRoadMix = 0.0f; g_presentS = 0.0f;
        ApplyPresentation(ViewMode::Classic);
        return;
    }

    // The game's zoom is eased the same way, but the view never shows noticeably
    // more than the game has drawn, whichever way it is going.
    float shown = visibleTiles_;
    if (k >= 0.01f) {
        if (camZoom_ <= 0.01f || dt <= 0.0f || dt > 0.25f) {
            camZoom_ = visibleTiles_;
        } else {
            camZoom_ += (visibleTiles_ - camZoom_) * (1.0f - std::exp(-dt / (kCameraZoomTau * k)));
            if (std::fabs(visibleTiles_ - camZoom_) < kCameraSnap) camZoom_ = visibleTiles_;
        }
        shown = (std::min)(camZoom_, visibleTiles_ * 1.05f);
    } else {
        camZoom_ = 0.0f;
    }

    // The top-down view states its orientation every frame: a move between views
    // leaves the camera turned part way, and framing along that would make the
    // move's destination drift with it.
    camera_.SetOrientation(0.0f, classicPitch_);
    camera_.SetFovY(classicFov_);
    camera_.SetRoll(0.0f);
    const float distance = (shown * 0.5f) / std::tan(camera_.FovY() * 0.5f);
    camera_.FrameTarget(target, distance);
    ApplyTransition(viewTime_ > 0.0 ? dt : 0.0f, ViewMode::Classic);
    {   // FIX-CLASSIC probe (GTA2DX9_LOG_CLASSIC_CAM=1): the classic camera's inputs, bit-exact, every 15 frames.
        static int logCam = -1;
        if (logCam < 0) { char buf[8] = {}; logCam = GetEnvironmentVariableA("GTA2DX9_LOG_CLASSIC_CAM", buf, sizeof buf) && buf[0] == '1'; }
        if (logCam && frameCount_ % 15 == 0) {
            const gta2::Vec3& p = camera_.Position();
            Log("classic cam f=%d raw=%a,%a cam=%a,%a h=%a zoom=%a vis=%a shown=%a pos=%a,%a,%a yaw=%a pitch=%a fov=%a dt=%a",
                frameCount_, rawX, rawY, camX_, camY_, smoothedHeight_, camZoom_, visibleTiles_, shown,
                p.x, p.y, p.z, camera_.Yaw(), camera_.Pitch(), camera_.FovY(), dt);
        }
    }

    // Tell the HUD how the two cameras differ. See HudCameraMap.
    HudCameraMap map;
    map.valid = true;
    map.rawX = rawX;
    map.rawY = rawY;
    map.viewX = tileX;
    map.viewY = tileY;
    map.rawTiles = visibleTiles_;
    map.viewTiles = shown;
    SetHudCameraMap(map);
}

// What the picture presents, applied once a frame after the camera is placed
// (FIX-SMOOTH-SWITCH; the settings are those the street views always used, moved here
// from the moment the solver placed the camera, which was the V press itself).
void WorldView::ApplyPresentation(ViewMode mode) {
    const bool street = g_presentStreet;
    if (street != presentedStreet_) {
        if (street) {
            // Cars as bodies with height, for a camera that is not above them.
            // The top-down numbers come back with the classic presentation.
            g_classicCarHeight = CarBodyHeight();
            g_classicCarShoulder = CarDomeShoulder();
            g_classicCarWheels = CarWheels();
            SetCarBodyHeight(ViewModes().groundCarHeight);
            SetCarDomeShoulder(ViewModes().groundCarShoulder);
            if (ViewModes().groundCarWheels) SetCarWheels(true, kDefaultCarWheelMaxAngle);
        } else {
            SetCarBodyHeight(g_classicCarHeight);
            SetCarDomeShoulder(g_classicCarShoulder);
            SetCarWheels(g_classicCarWheels, kDefaultCarWheelMaxAngle);
        }
        presentedStreet_ = street;
        Log("view: presentation %s (frame %d, move %.3f, %s)", street ? "street" : "classic", frameCount_, transitionT_,
            ViewModeName(mode));
    }
    if (street) {
        const PlayerState& player = g_viewPlayer;
        // From his own eyes he is not in the picture, nor is the car he is
        // in; behind him, both are.
        // (QB-17/18: a beat's camera stands outside him, so he is drawn through it.)
        // FIX-CAMERA-15 (cam14-fp-at-the-wheel-beat-hand-back-fades-in-with-no-cab-wheel-or-hands-for-0p7s): the
        // beat lasts 0.9 s past its hand-back (the picture fades in from black with its camera share already 0
        // and the eye back in the seat); keyed on BeatActive() the car was drawn whole round the seat's eye for
        // those ~27 frames (the bare bonnet, no dash, wheel or hands, then the cockpit popped in, run cam15_bust1).
        // From its hand-back on he is seen from his own eyes again. GTA2DX9_CAM_BEAT_SEAT_HIDE=0 restores the old
        // gate (A/B).
        static int beatSeatHide = -1;
        if (beatSeatHide < 0) { char b[8] = {}; beatSeatHide = GetEnvironmentVariableA("GTA2DX9_CAM_BEAT_SEAT_HIDE", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const bool beatHoldsCamera = BeatActive() && (!beatSeatHide || Beat().camera > 0.0f || Beat().t < 0.5f);
        const bool hide = mode == ViewMode::FirstPerson && ViewModes().fpHideOwnBody && !beatHoldsCamera;
        // FIX-FP-ENTRY (feel11): for the first half second out of a car in first person the eye glides
        // out of the seat through the door; his car stays drawn as from the seat (the cut hull, the cab)
        // until then, so the eye is never inside a whole body (which drew nothing: the car vanished).
        static const void* lastCarSprite = nullptr;
        static int framesOut = 1000;
        if (player.inVehicle && player.vehicleSprite) { lastCarSprite = player.vehicleSprite; framesOut = 0; }
        else if (framesOut < 1000) ++framesOut;
        const void* heldCar = hide && player.inVehicle ? player.vehicleSprite
                              : (hide && FirstPersonBoardEyeOn() && (framesOut <= 14 || FpExitHoldsCar()) ? lastCarSprite : nullptr);   // FIX-FP-EXIT-1
        // FIX-SEAT-ENTRY-2: a V out of the driver's seat (to classic or the chase view) starts from the
        // seat's eye; while the moving eye is still inside the car's body the car stays drawn from the
        // seat (the cut hull and the cab), not whole round the eye (a black frame).
        static const void* seatHeld = nullptr;
        if (!heldCar && seatHeld && player.inVehicle && player.vehicleSprite == seatHeld && transitionT_ < 1.0f) {
            const gta2::Vec3 e = camera_.Position();
            for (const CameraCar& c : LiveCameraCars()) {
                if (c.object != reinterpret_cast<uintptr_t>(seatHeld)) continue;
                // FIX-CAMERA-9 (pfeel33-residual-fp-to-classic-one-or-two-street-frames-with-no-car-after-the-cockpit):
                // on the rise out of the seat into the classic view the first frame's eye is just over the roof (0.15,
                // looking 7 degrees down: the roof under the frame's bottom edge) and that frame showed the street with
                // no car, held 0.4 s by a hitch (run cam9_v21a f1121); the car stays drawn from the seat until 0.25 over
                // the roof, from where the roof is in the picture (f1122: 0.32 over, 11 down).
                const float over = transitionToClassic_ && transitionFromFirst_ ? 0.25f : 0.02f;
                bool in = e.y < c.y1 + over;
                for (int i = 0; i < 4 && in; ++i) {
                    const int j = (i + 1) & 3, k = (i + 2) & 3;
                    const float ex = c.x[j] - c.x[i], ez = c.z[j] - c.z[i];
                    const float sideE = ex * (e.z - c.z[i]) - ez * (e.x - c.x[i]);
                    const float sideK = ex * (c.z[k] - c.z[i]) - ez * (c.x[k] - c.x[i]);
                    if (sideE * sideK < 0.0f) in = false;
                }
                if (in) heldCar = seatHeld;
                break;
            }
        }
        seatHeld = heldCar;
        SetHiddenObjects(hide ? player.pedSprite : nullptr, heldCar);
        // REMIX-3D-QUALITY: under Remix his figure is still drawn from his eyes, with
        // textures Remix keeps out of the eye's rays, so he casts the shadow his
        // sprite casts in the classic view (on foot; in a car the game draws no ped).
        SetOwnFigureShadowOnly(hide && !player.inVehicle && RemixApiAvailable() && OwnFigureShadowAllowed() &&
                               ViewModes().uprightPeds && ViewModes().groundPedFigures && ViewModes().groundModels &&
                               ModelsAvailable());
        SetPlayerObject(player.pedSprite);
        SetPlayerPed(player.ped);
        SetPlayerPosition(player.x, player.z, static_cast<float>(gta2::kMapHeight) - player.y, player.valid);
        {
            // FIX-FX-2 (fire-fx 3d): his car alight, for the bonnet flames in first person.
            int dmg = 0, hp = 0, fire = 0;
            float hx = 0.0f, hy = 0.0f;
            const bool burning = mode == ViewMode::FirstPerson && !BeatActive() && player.valid && player.inVehicle &&
                                 player.vehicle && ReadVehicleCondition(player.vehicle, &dmg, &hp, &fire) && fire >= 1 &&
                                 VehicleFacing(player.vehicle, &hx, &hy);
            SetOwnCarFire(burning, player.x, player.z, static_cast<float>(gta2::kMapHeight) - player.y, hx, -hy, fire);
        }
        SetPlayerInVehicle(player.inVehicle);
        SetUprightPeds(ViewModes().uprightPeds);
        SetPedFigures(ViewModes().uprightPeds && ViewModes().groundPedFigures);
        SetGroundModels(ViewModes().groundModels && ModelsAvailable());
    } else {
        SetHiddenObjects(nullptr, nullptr);
        SetOwnFigureShadowOnly(false);
        SetPlayerObject(nullptr);
        SetPlayerPed(nullptr);
        SetPlayerPosition(0.0f, 0.0f, 0.0f, false);
        SetOwnCarFire(false, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0);
        SetPlayerInVehicle(false);
        SetUprightPeds(false);
        SetPedFigures(false);
        SetGroundModels(false);
    }
}

// The move between views.
//
// Every frame the view in force has set camera_ to where it wants the camera;
// this is called last with that. When the view has just changed, the camera as
// it was last shown becomes the start of a move, and for transitionSeconds the
// camera is placed between that start and whatever the new view asks for this
// frame - so the destination can go on moving (a car driving off) and the
// camera still arrives on it. The path bows upward by transitionArc of its
// length, and any point of it inside a building is lifted clear; the heading
// turns the short way round, pitch, roll and field of view are eased. Changing
// view again mid-move starts the next move from wherever the camera is.
// FIX-CAMERA-7 (the V moves' residual turns, FIX-CAMERA-6's tables: the end of the classic -> third descent turned
// 10-12 degrees a frame for 2 frames as the aim met the chase pose; the arrival in the cab at the roof line cut to
// the driver's pose, 12 degrees of pitch in one frame): into a street view, the pose shown turns at most
// kMoveTurn degrees a second (8 a frame at 30 fps) from the one shown last frame, through the move and the
// frames after it until it has caught up with the view's own. Never in the classic view (the game's camera, byte for
// byte). GTA2DX9_MOVE_TURN_CAP=0 turns it off (A/B).
namespace {
// FIX-CAMERA-17 (owner10nov-B10): what the world-mesh clearance cannot see. eyecol holds the static map mesh only
// (its Nearest returns its search radius, 0.6, when no map face is nearer: the constant 0.600 of the owner's log);
// the street objects (phone boxes, bins, lights: MapObjectObstacles), the cars and wrecks drawn last frame
// (LiveCameraCars) and the people drawn last frame (LiveAimPeds, him left out) are measured here: the distance from
// p to each one's body (a cylinder for an object or a person, the footprint box for a car), 0 when inside it.
struct DynamicClear { float prop = 9.0f, car = 9.0f, ped = 9.0f; };
float BoxGap(float y, float y0, float y1) { return y < y0 ? y0 - y : (y > y1 ? y - y1 : 0.0f); }
DynamicClear DynamicClearance(const gta2::Vec3& p, const void* ownPed, const void* ownCar) {
    DynamicClear r;
    for (const PropFootprint& o : MapObjectObstacles()) {
        if (std::fabs(o.x - p.x) > 3.0f || std::fabs(o.z - p.z) > 3.0f) continue;
        const float flat = (std::max)(0.0f, std::hypot(p.x - o.x, p.z - o.z) - o.radius * 1.42f);
        const float v = BoxGap(p.y, o.y, o.y + o.height);
        r.prop = (std::min)(r.prop, std::sqrt(flat * flat + v * v));
    }
    for (const CameraCar& c : LiveCameraCars()) {
        if (ownCar && c.object == reinterpret_cast<uintptr_t>(ownCar)) continue;
        const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
        if (std::fabs(cx - p.x) > 6.0f || std::fabs(cz - p.z) > 6.0f) continue;
        // outside the quad: the distance to its nearest edge; inside: 0
        bool inside = true;
        float flat = 1e9f;
        float area = 0.0f;
        for (int i = 0; i < 4; ++i) { const int j = (i + 1) & 3; area += c.x[i] * c.z[j] - c.x[j] * c.z[i]; }
        for (int i = 0; i < 4; ++i) {
            const int j = (i + 1) & 3;
            const float ex = c.x[j] - c.x[i], ez = c.z[j] - c.z[i];
            const float cross = ex * (p.z - c.z[i]) - ez * (p.x - c.x[i]);
            if (cross * area < 0.0f) inside = false;
            const float l2 = ex * ex + ez * ez;
            float t = l2 > 1e-8f ? ((p.x - c.x[i]) * ex + (p.z - c.z[i]) * ez) / l2 : 0.0f;
            t = (std::max)(0.0f, (std::min)(1.0f, t));
            flat = (std::min)(flat, std::hypot(p.x - (c.x[i] + ex * t), p.z - (c.z[i] + ez * t)));
        }
        if (inside) flat = 0.0f;
        const float v = BoxGap(p.y, c.y0, c.y1);
        r.car = (std::min)(r.car, std::sqrt(flat * flat + v * v));
    }
    for (const AimPed& a : LiveAimPeds()) {
        if (a.corpse || (ownPed && a.object == reinterpret_cast<uintptr_t>(ownPed))) continue;
        if (std::fabs(a.x - p.x) > 3.0f || std::fabs(a.z - p.z) > 3.0f) continue;
        const float flat = (std::max)(0.0f, std::hypot(p.x - a.x, p.z - a.z) - 0.12f);
        const float v = BoxGap(p.y, a.y, a.y + 0.5f);
        r.ped = (std::min)(r.ped, std::sqrt(flat * flat + v * v));
    }
    return r;
}
}  // namespace

void WorldView::MoveTurnCap(CameraPose* pose, float dt, ViewMode mode) {
    static int on = -1;
    if (on < 0) { char b[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_MOVE_TURN_CAP", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    if (!on || mode == ViewMode::Classic || !lastPoseValid_) return;
    // FIX-CAMERA-17: the turn budget's rate when one is set (8 a frame = 240 a second, the old constant, by default)
    const float kMoveTurn = (CameraTurnBudgetDeg() > 0.0f ? CameraTurnBudgetDeg() * 30.0f : 240.0f) * 0.0174533f;
    const float cap = kMoveTurn * (std::min)((std::max)(dt, 1.0f / 120.0f), 1.0f / 20.0f);
    float dy = pose->yaw - lastPose_.yaw;
    while (dy > 3.14159265f) dy -= 6.2831853f;
    while (dy < -3.14159265f) dy += 6.2831853f;
    const float dp = pose->pitch - lastPose_.pitch;
    if (std::fabs(dy) <= cap && std::fabs(dp) <= cap) return;
    static int every = 0;
    // FIX-CAMERA-17: the numbers are what the move still wants to turn from the frame shown last (the gap), not this
    // frame's turn, which is the cap (the owner's -159.7/-121.5/-81.5/-41.5 were one gap closing 8 degrees a frame,
    // logged every 5th frame).
    if ((++every % 5) == 1)
        Log("view: move turn capped: yaw %+.1f pitch %+.1f deg still to turn (this frame at most %.1f)", dy * 57.2958f, dp * 57.2958f, cap * 57.2958f);
    pose->yaw = lastPose_.yaw + (std::max)(-cap, (std::min)(cap, dy));
    pose->pitch = lastPose_.pitch + (std::max)(-cap, (std::min)(cap, dp));
}

namespace {
bool RespawnCutOn() {
    static int on = -1;
    if (on < 0) { char b[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_RESPAWN_CUT", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    return on != 0;
}
}  // namespace

static bool LevelStartCutOn() {
    static int env = -2;
    if (env < -1) { char b[8] = {}; env = GetEnvironmentVariableA("GTA2DX9_LEVEL_START_CUT", b, sizeof b) ? atoi(b) : -1; }
    return env >= 0 ? env != 0 : ViewModes().levelStartCut;
}

void WorldView::ApplyTransition(float dt, ViewMode mode) {
    const ViewModeSettings& vm = ViewModes();
    CameraPose target;
    target.position = camera_.Position();
    target.yaw = camera_.Yaw();
    target.pitch = camera_.Pitch();
    target.roll = camera_.Roll();
    target.fov = camera_.FovY();

    // FIX-CAMERA-8 (pfl11-third-respawn-after-busted-camera-starts-straight-down): found again after the
    // street view fell back to the classic camera (a death or an arrest; the new body at the hospital
    // or the station), the street view is not entered by the classic -> street descent (which started
    // straight down at the paving, the hero out of frame, and swooped up over 1.5 s) but cut to: the
    // first frame is the chase rig's solved pose behind him (the solver re-arms on the jump).
    // GTA2DX9_RESPAWN_CUT=0 restores the descent (A/B).
    if (mode != lastViewMode_ && mode != ViewMode::Classic && lostFallback_ && RespawnCutOn()) {
        Log("view: found again after the classic fallback: cut to %s at its solved pose (no move)", ViewModeName(mode));
        transitionT_ = 1.0f;
        moveCatch_ = 0.0f;
        dissolveActive_ = false;
        lastViewMode_ = mode;
    }
    // FIX-CAMERA-18 (qaexp32-first-person-new-game-from-menu-1p7s-aerial-swoop-over-whole-city-before-street-view): a
    // street view kept through PLAYER QUIT -> main menu -> a new game opened the level with the classic -> street move
    // from the last classic pose (the game's camera high over the city): 1.4 s of aerial frames over the whole map and
    // the sea under the TRAINING MISSION banner, then the street (run qa_qaexp32b_main: 'moving the camera to First
    // person over 1.4 s' on the level's first placed frame). After a level load the street view is cut to, as after a
    // respawn (FIX-CAMERA-8): its first frame is the solved pose at the hero. A classic frame shown as the wanted view
    // (the player chose classic) or 10 s without a street frame ends it, so a later V is a V. [camera]
    // level_start_cut=0 or GTA2DX9_LEVEL_START_CUT=0: the move as before (A/B).
    if (levelStartCut_ && (mode == ViewMode::Classic || frameCount_ - levelStartFrame_ > 300 || !LevelStartCutOn())) levelStartCut_ = false;
    if (mode != lastViewMode_ && mode != ViewMode::Classic && levelStartCut_) {
        Log("view: the level's first street frame: cut to %s at its solved pose (no move from the classic camera)", ViewModeName(mode));
        transitionT_ = 1.0f;
        moveCatch_ = 0.0f;
        dissolveActive_ = false;
        lastViewMode_ = mode;
    }
    if (mode != ViewMode::Classic) levelStartCut_ = false;
    if (mode != ViewMode::Classic) lostFallback_ = false;
    if (mode != lastViewMode_) {
        MemStatsViewChange(static_cast<int>(lastViewMode_), static_cast<int>(mode));   // FIX-PERF-4
        if (lastPoseValid_ && vm.transitionSeconds > 0.01f) {
            transitionFrom_ = lastPose_;
            transitionT_ = 0.0f;
            g_moveS0 = g_presentS;
            transitionLift_ = 0.0f;
            transitionToClassic_ = mode == ViewMode::Classic;
            transitionFromClassic_ = lastViewMode_ == ViewMode::Classic;
            transitionFromFirst_ = lastViewMode_ == ViewMode::FirstPerson;
            transitionPlayerKnown_ = locatedValid_;
            transitionPlayerX0_ = locatedX_; transitionPlayerZ0_ = locatedZ_;
            transitionTarget0_ = target.position;
            transitionTargetYaw0_ = target.yaw;
            // FIX-CAMERA-5 (feel23): between the two street views (third <-> first) the move is
            // short (the classic -> third move is the reference for how a switch should feel); a
            // 1.4 s glide from the chase eye into the cab at speed left the player with neither view.
            transitionSeconds_ = (!transitionToClassic_ && !transitionFromClassic_) ? (std::min)(vm.transitionSeconds, 0.8f)
                                                                                    : vm.transitionSeconds;
            // The last frame drawn was the settled classic view and the renderer kept it:
            // the move opens on that frame and dissolves it away (RenderFrame).
            dissolveActive_ = transitionFromClassic_ && vm.switchDissolve > 0.001f && renderer_.HasKeptFrame() &&
                              keptClassicAt_ == frameCount_ - 1;
            dissolveT0_ = -1.0f;
            Log("view dissolve: %s", dissolveActive_ ? "from the last classic frame" : "none (no kept classic frame)");
            Log("view: moving the camera to %s over %.1f s (anchor=%s)", ViewModeName(mode), transitionSeconds_,
                transitionToClassic_ ? "world" : (transitionFromClassic_ ? "destination" : "destination+heading"));
        }
        lastViewMode_ = mode;
    }

    CameraPose shown = target;
    skyBlend_ = mode == ViewMode::Classic ? 0.0f : 1.0f;
    g_seatMove = false;
    if (transitionT_ < 1.0f) {
        if (dt > 0.25f) dt = 1.0f / 30.0f;
        transitionT_ = (std::min)(1.0f, transitionT_ + dt / (std::max)(transitionSeconds_, 0.05f));
        // Smoothstep: the camera starts and arrives gently.
        const float t = transitionT_;
        const float e = t * t * (3.0f - 2.0f * t);
        // FIX-CAMERA-5 (feel23-v-third-to-first-while-driving-...): the start pose rides the
        // destination. It was a world point fixed at the key press: in a car doing 1-2 blocks a
        // second the van drove out of the picture while the camera eased off that point, and the
        // cockpit swung in from behind 3 s later. Now the start is moved with the destination
        // (the driver's eye, the chase eye, the hero) and, between the two street views, turned
        // with its heading, so the whole move happens in the car's (or his) own frame. Into the
        // classic view the start stays where it was (the classic camera is the game's).
        CameraPose from = transitionFrom_;
        if (!transitionToClassic_) {
            float dh = 0.0f;
            if (!transitionFromClassic_) {
                dh = target.yaw - transitionTargetYaw0_;
                while (dh > 3.14159265f) dh -= 6.2831853f;
                while (dh < -3.14159265f) dh += 6.2831853f;
            }
            const gta2::Vec3 v = transitionFrom_.position - transitionTarget0_;
            const float cd = std::cos(dh), sd = std::sin(dh);
            from.position = target.position + gta2::Vec3{v.x * cd + v.z * sd, v.y, -v.x * sd + v.z * cd};
            from.yaw = transitionFrom_.yaw + dh;
        }
        // FIX-CAMERA-6 (pfeel4-third-to-classic-while-driving-camera-loses-van-and-climbs-facade): into the
        // classic view too the start rides along, by how far the classic camera (the game's, which follows the
        // car) has gone since the press: at speed the van drove out of the picture for 1.5 s while the camera
        // rose from where the chase eye had been. Across only (the classic height changes with the game's zoom).
        gta2::Vec3 rideToClassic{0.0f, 0.0f, 0.0f};
        static int rideOn = -1;
        if (rideOn < 0) { char b2[8] = {}; rideOn = GetEnvironmentVariableA("GTA2DX9_MOVE_RIDE_CLASSIC", b2, sizeof b2) && atoi(b2) == 0 ? 0 : 1; }
        if (transitionToClassic_ && rideOn) {
            // him (located every frame), else the classic camera (which leads the car at speed)
            rideToClassic = transitionPlayerKnown_ && locatedValid_
                                ? gta2::Vec3{locatedX_ - transitionPlayerX0_, 0.0f, locatedZ_ - transitionPlayerZ0_}
                                : gta2::Vec3{target.position.x - transitionTarget0_.x, 0.0f, target.position.z - transitionTarget0_.z};
            from.position = transitionFrom_.position + rideToClassic;
        }
        const gta2::Vec3& a = from.position;
        const gta2::Vec3& b = target.position;
        const gta2::Vec3 span = b - a;
        const float length = std::sqrt(span.x * span.x + span.y * span.y + span.z * span.z);
        // FIX-SMOOTH-SWITCH: between the classic camera (high above) and a street camera (by
        // the player) the height goes in proportion, not in equal steps: the picture changes
        // with the height's ratio, so equal steps swept a street-level picture past at many
        // times the rate of the high one (on the way up from first person, a wall a metre
        // away tore past at 40-55/255 a frame). Above a floor a block under the lower end,
        // the height runs geometrically with the eased progress; across and along, as before.
        const float floorY = (std::min)(a.y, b.y) - 1.0f;
        const float ha = a.y - floorY, hb = b.y - floorY;   // both >= 1
        // FIX-CAMERA-5 (feel23): from the chase camera into first person (see below: the move ends on
        // the cab's roof line).
        const bool intoEye = !transitionFromClassic_ && !transitionToClassic_ && mode == ViewMode::FirstPerson;
        // FIX-CAMERA-7B (pfeel33-fp-to-classic-while-driving-cockpit-vanishes-...): out of the driver's seat into the
        // classic view the eye first rises straight up over the seat (riding the car) and only then drifts across to
        // the classic camera, which leads the car at speed by blocks: the drift from the first frame took the eye out
        // through the windscreen in 0.3 s, one frame showed the street with no car, then the van sat at the frame's
        // bottom edge for ten frames (run cam7b_p1 vfpc_0). GTA2DX9_MOVE_FP_RISE=0 restores the straight path (A/B).
        static int fpRiseOn = -1;
        if (fpRiseOn < 0) { char b2[8] = {}; fpRiseOn = GetEnvironmentVariableA("GTA2DX9_MOVE_FP_RISE", b2, sizeof b2) && atoi(b2) == 0 ? 0 : 1; }
        const bool fpRise = fpRiseOn && transitionToClassic_ && transitionFromFirst_ && rideOn;
        const auto pathAt = [&](float ee) {
            float eh = ee;
            if (fpRise) {
                const float u = (std::min)(1.0f, (std::max)(0.0f, (ee - 0.25f) / 0.75f));
                eh = u * u * (3.0f - 2.0f * u);
            }
            gta2::Vec3 q = a + (b - a) * eh;
            q.y = floorY + ha * std::pow(hb / ha, ee);
            // The arc: a sine bump along the way, scaled by the distance.
            q.y += std::sin(ee * 3.14159265f) * length * vm.transitionArc;
            return q;
        };
        gta2::Vec3 p = pathAt(e);
        if (fpRise) {
            // FIX-CAMERA-7B: up out of the seat at once (1.4 blocks over 0.5 s, fastest at the start, then on at 1.5 a
            // second until the path is higher): risen on the smooth path the eye spent 3-4 frames just over the roof,
            // the roof a slab across the picture (cam7b_p2); a pop that stopped dead stalled the climb 4 frames (p3).
            const float sec = transitionT_ * (std::max)(transitionSeconds_, 0.05f);
            const float u = (std::min)(1.0f, sec / 0.5f);
            const float pop = 1.0f - (1.0f - u) * (1.0f - u);
            p.y = (std::max)(p.y, a.y + 1.4f * pop + 1.5f * (std::max)(0.0f, sec - 0.5f));
            // and back over the car's rear as it rises (2.2 blocks, a little after the rise, so the eye is over the roof
            // first; given back as the drift to the classic pose comes in): straight over the seat the car was under the
            // lens, below the picture for 0.45 s (run cam7b_p4 vfpc_0); 1.6 back and 2.2 up still put it under the
            // picture's bottom edge for 8 frames (cam7b_p5)
            const float ud = (std::min)(1.0f, (std::max)(0.0f, (e - 0.25f) / 0.75f));
            const float back = 2.2f * pop * std::sqrt(pop) * (1.0f - ud * ud * (3.0f - 2.0f * ud));
            p.x -= std::sin(from.yaw) * back;
            p.z -= std::cos(from.yaw) * back;
        }
        // Out of any building the path crosses - by a storey at most, so a short
        // move past a wall never becomes a flight over the city.
        // FIX-SMOOTH-SWITCH: the lift is eased, never stepped. It was added whole on the
        // frame it was needed, in quarter-block steps per cell, so a move that began
        // where the cells read 'blocked' (a first-person eye under a sign or beside a
        // wall) jumped up to 1.5 blocks on its first frame, and a path crossing cells
        // hopped. Now: the most the path needs over the next stretch of the move (looking
        // ahead, so it rises before it reaches a roof), approached at no more than
        // kLiftRate blocks a second from 0 at the start of the move (whose first pose is
        // the one last shown, which needs none).
        {
            constexpr float kLiftRate = 3.0f;
            const auto liftAt = [&](float ee) {
                const gta2::Vec3 q = pathAt(ee);
                float l = 0.0f;
                for (int i = 0; i < 6 && Blocked(q.x, q.y + l, q.z); ++i) l += 0.25f;
                return l;
            };
            float need = 0.0f;
            for (int k = 0; k <= 3; ++k) need = (std::max)(need, liftAt((std::min)(1.0f, e + 0.05f * static_cast<float>(k))));
            // Arriving, the lift goes with the arc: none is left on the destination's own pose.
            need *= (std::min)(1.0f, (1.0f - e) / 0.15f);
            const float step = kLiftRate * (std::max)(dt, 1.0f / 120.0f);
            if (transitionLift_ == 0.0f && need > 0.0f && e < 0.02f)
                Log("view: move path lift: %.2f blocks needed at the start, eased in at %.1f blocks/s", need, kLiftRate);
            transitionLift_ += (std::max)(-step, (std::min)(step, need - transitionLift_));
            p.y += transitionLift_;
        }
        // FIX-CAMERA-5 (feel23): into first person at the wheel, the move ends where the eye passes
        // below the roof of the car the destination sits in. Flown on down into the cab it showed the
        // top of the dash as a black slab (two frames, run fc5_all_v1); come in level from behind it
        // crossed a van's closed cargo box (twelve dark frames, run fc5_rebased). The car is the body
        // whose footprint holds the destination at its height (LiveCameraCars, one frame old).
        bool arriveNow = false;
        if (intoEye) {
            const auto depth = [](const CameraCar& c, float x, float z) {
                float area = 0.0f;
                for (int i = 0; i < 4; ++i) { const int j = (i + 1) & 3; area += c.x[i] * c.z[j] - c.x[j] * c.z[i]; }
                const float wind = area >= 0.0f ? 1.0f : -1.0f;
                float d = 1e9f;
                for (int i = 0; i < 4; ++i) {
                    const int j = (i + 1) & 3;
                    const float ex = c.x[j] - c.x[i], ez = c.z[j] - c.z[i];
                    const float el = std::hypot(ex, ez);
                    if (el < 1e-4f) continue;
                    d = (std::min)(d, wind * (ex * (z - c.z[i]) - ez * (x - c.x[i])) / el);
                }
                return d;
            };
            // The list is a frame old: at speed the footprint trails the car by a tenth of a block or
            // more, and the driver's eye sits near its front, so the body nearest the destination is
            // taken (within 0.4), and the eye counts as over it within 0.3 of its edge.
            const CameraCar* own = nullptr;
            float best = -0.4f;
            for (const CameraCar& c : LiveCameraCars()) {
                if (b.y < c.y0 - 0.1f || b.y > c.y1 + 0.3f) continue;
                const float d = depth(c, b.x, b.z);
                if (d > best) { best = d; own = &c; }
            }
            // FIX-CAMERA-9 (pfl21-third-to-first-v-while-driving-camera-climbs-over-own-roof-11-frames): over the
            // footprint within 0.6 of the roof (was 0.3). The move's arc carries the eye 0.5 over a van's roof as it
            // reaches the rear edge, so it crossed the whole roof before coming down to 0.3: 7 frames of the roof as a
            // slab across the bottom with the wall the only subject, then the cut (run cam9_v21a f1060-1066).
            if (own && depth(*own, p.x, p.z) > -0.3f && p.y < own->y1 + 0.6f) arriveNow = true;
            if (own && !arriveNow) { g_seatMove = true; g_seatMoveEye = b; }
            static int logged = 0;
            if (transitionT_ <= dt / (std::max)(transitionSeconds_, 0.05f) + 1e-4f && logged < 40) {
                ++logged;
                Log("view: move into the cab: %s (destination %.2f inside its footprint, roof %.2f)", own ? "the car found" : "no car under the destination",
                    own ? best : 0.0f, own ? own->y1 : 0.0f);
            }
            if (arriveNow) Log("view: move into the cab: arrived at t=%.2f (the eye passed the roof line)", transitionT_);
        }
        // FIX-OCCLUSION: nor through a wall the cells do not see (a diagonal, a partial block):
        // on the way into a street view the camera is never on the far side of a surface from
        // where it is going, nor nearer one than the near plane allows.
        if (!transitionToClassic_ && eyecol::Ready()) {
            // FIX-SMOOTH-SWITCH: only near the destination, and blended in by the distance. Over
            // the whole move it cast from the destination (the chase eye by the player) up to the
            // camera high on the path, and anything across that line (a stair rail, a sign) put
            // the camera next to the destination for the frames it stayed crossed: a flash of a
            // close-up in the middle of the flight (first V, wil 159.5,139.5, frames 72-73).
            // Within 3 blocks it takes over smoothly; at 1.5 blocks and nearer it is whole.
            const gta2::Vec3 toB = p - b;
            const float db = std::sqrt(toB.x * toB.x + toB.y * toB.y + toB.z * toB.z);
            if (db < 3.0f) {
                gta2::Vec3 c = p;
                eyecol::Clear(b, &c, 0.15f);
                const float u = (std::min)(1.0f, (std::max)(0.0f, (3.0f - db) / 1.5f));
                p = p + (c - p) * (u * u * (3.0f - 2.0f * u));
            }
            // Still in a closed block (the path dives through a roof the destination is under):
            // the camera waits where it was last shown, outside, until the path leaves it.
            if (lastPoseValid_ && eyecol::InsideSolid(p) && !eyecol::InsideSolid(lastPose_.position)) p = lastPose_.position;
        }
        // FIX-CAMERA-6 (pfeel4): on the way up into the classic view, near where it set off (the car), the
        // camera keeps clear of the drawn mesh as seen from the car's side: from the chase eye beside a facade
        // the path rose along its windows and over its cornice. Blended in by the distance from the start, as
        // the arrival's clearance above is by the distance from the destination.
        if (transitionToClassic_ && rideOn && eyecol::Ready()) {
            const gta2::Vec3 f0{std::sin(transitionFrom_.yaw) * std::cos(transitionFrom_.pitch), std::sin(transitionFrom_.pitch),
                                std::cos(transitionFrom_.yaw) * std::cos(transitionFrom_.pitch)};
            gta2::Vec3 anchor = transitionFrom_.position + f0 * 1.2f + rideToClassic;   // over the car, a little ahead
            // FIX-CAMERA-9 (pfeel33 residual): out of the driver's seat with the car's nose at a wall the point 1.2 ahead
            // of the eye is beyond the wall, and the clearance seen from there put the first rise frame's eye 1.37
            // block through the wall, the street on its far side with no car (run cam9_v21c f1174, 0.3 s with a
            // hitch). From the seat the anchor stops short of the first surface ahead of the eye.
            if (transitionFromFirst_) {
                const gta2::Vec3 start = transitionFrom_.position + rideToClassic;
                float th = 1.0f;
                if (eyecol::SegmentHit(start, anchor, &th)) anchor = start + (anchor - start) * (std::max)(0.0f, th - 0.15f / 1.2f);
            }
            const gta2::Vec3 toA = p - anchor;
            const float da = std::sqrt(toA.x * toA.x + toA.y * toA.y + toA.z * toA.z);
            if (da < 4.0f) {
                gta2::Vec3 c = p;
                eyecol::Clear(anchor, &c, 0.15f);
                const float u = (std::min)(1.0f, (std::max)(0.0f, (4.0f - da) / 2.0f));
                p = p + (c - p) * (u * u * (3.0f - 2.0f * u));
            }
        }
        // The short way round for the heading.
        float dyaw = target.yaw - from.yaw;
        while (dyaw > 3.14159265f) dyaw -= 6.2831853f;
        while (dyaw < -3.14159265f) dyaw += 6.2831853f;
        shown.position = p;
        shown.yaw = from.yaw + dyaw * e;
        shown.pitch = from.pitch + (target.pitch - from.pitch) * e;
        static int moveAim = -1;
        if (moveAim < 0) { char b2[8] = {}; moveAim = GetEnvironmentVariableA("GTA2DX9_MOVE_AIM", b2, sizeof b2) && atoi(b2) == 0 ? 0 : 1; }
        if (!transitionToClassic_ && moveAim) {
            // FIX-CAMERA-2 (pm11-classic-to-third-switch-camera-rolls-and-lands-behind-wall-player-hidden).
            // Into a street view the camera looks, as it goes, at the point the destination
            // looks at (kLookAhead along its view: him, from the chase camera), blended in
            // with the move; the camera held over him by the walls (the yard at the Industrial
            // start: 4 blocks up for the first 60 % of the move, above) used to tilt up to the
            // chase pitch blindly and look level at the yard's walls, him out of the picture
            // below. And the turn's direction is chosen once: with the destination heading at
            // +-180 degrees "the short way" flipped between frames and the picture spun 88
            // degrees back in three frames (run fc2_sw_log).
            constexpr float kLookAhead = 2.4f;
            const gta2::Vec3 f{std::sin(target.yaw) * std::cos(target.pitch), std::sin(target.pitch),
                               std::cos(target.yaw) * std::cos(target.pitch)};
            const gta2::Vec3 look = b + f * kLookAhead;
            const gta2::Vec3 to = look - p;
            const float flat = std::sqrt(to.x * to.x + to.z * to.z);
            float aimYaw = target.yaw, aimPitch = target.pitch;
            if (flat > 0.3f) {
                aimYaw = std::atan2(to.x, to.z);
                aimPitch = std::atan2(to.y, flat);
            } else {
                aimPitch = -1.5f;   // straight over the point: down at it
            }
            // The aim's heading unwrapped next to last frame's, and the turn from the start's
            // heading kept on the side it began on.
            float d = aimYaw - transitionAimYaw_;
            while (d > 3.14159265f) d -= 6.2831853f;
            while (d < -3.14159265f) d += 6.2831853f;
            transitionAimYaw_ = transitionT_ <= dt / (std::max)(transitionSeconds_, 0.05f) + 1e-4f
                                    ? from.yaw + [&] { float w = aimYaw - from.yaw;
                                                                  while (w > 3.14159265f) w -= 6.2831853f;
                                                                  while (w < -3.14159265f) w += 6.2831853f;
                                                                  return w; }()
                                    : transitionAimYaw_ + d;
            // The turn onto that point is done in the first 60 % of the move (the camera may be
            // held where it is for most of it, so the position's ease is no guide).
            const float ta = (std::min)(1.0f, t / 0.6f);
            const float ea = ta * ta * (3.0f - 2.0f * ta);
            shown.yaw = from.yaw + (transitionAimYaw_ - from.yaw) * ea;
            shown.pitch = from.pitch + (aimPitch - from.pitch) * ea;
        }
        if (transitionToClassic_ && moveAim && rideOn) {
            // FIX-CAMERA-6 (pfeel4): out of a street view the camera looks, as it rises, at the point the chase
            // view looked at (2.4 along its view, riding with the car), and turns to the classic orientation only
            // over the second half of the move, when it is high over the car: the plain blend swung the heading
            // round first and looked along the facades while the car left the picture.
            // (from the driver's eye the car is under the lens: its nose, 0.8 ahead, not the street 2.4 ahead)
            // (FIX-CAMERA-7B: with the rise straight up, the car's middle: 0.35 ahead of the seat, 0.45 down)
            const float kLookAhead = fpRise ? 0.35f : transitionFromFirst_ ? 0.8f : 2.4f;
            const gta2::Vec3 f0{std::sin(transitionFrom_.yaw) * std::cos(transitionFrom_.pitch), std::sin(transitionFrom_.pitch),
                                std::cos(transitionFrom_.yaw) * std::cos(transitionFrom_.pitch)};
            const gta2::Vec3 look = transitionFrom_.position + f0 * kLookAhead + gta2::Vec3{0.0f, fpRise ? -0.45f : transitionFromFirst_ ? -0.25f : 0.0f, 0.0f} + rideToClassic;
            const gta2::Vec3 to = look - p;
            const float flat = std::sqrt(to.x * to.x + to.z * to.z);
            float aimYaw = from.yaw, aimPitch = target.pitch;
            if (flat > 0.05f) {
                aimYaw = std::atan2(to.x, to.z);
                aimPitch = std::atan2(to.y, flat);
            }
            // the aim's heading kept next to the start's (never the long way round)
            float w0 = aimYaw - from.yaw;
            while (w0 > 3.14159265f) w0 -= 6.2831853f;
            while (w0 < -3.14159265f) w0 += 6.2831853f;
            aimYaw = from.yaw + w0;
            // in over the first 20 % (from the pose at the press), out to the classic pose over the last half
            const float tin = (std::min)(1.0f, t / 0.2f), win = tin * tin * (3.0f - 2.0f * tin);
            const float tout = (std::min)(1.0f, (std::max)(0.0f, (t - 0.5f) / 0.5f)), wout = tout * tout * (3.0f - 2.0f * tout);
            float yA = from.yaw + (aimYaw - from.yaw) * win, pA = from.pitch + (aimPitch - from.pitch) * win;
            if (fpRise) {
                // FIX-CAMERA-7B: from the seat the heading stays the cab's until the turn to the classic pose (below),
                // and the pitch turns onto the car's middle over the first 0.3 s of the move (about 9 degrees a frame at
                // most): tied to the height, it whipped 72 degrees down in two frames (run cam7b_p3 vfpc_0); over
                // 0.05-0.45 s the van was a sliver of roof at the bottom edge for 0.25 s (cam7b_p6).
                const float h = (std::min)(1.0f, (std::max)(0.0f, (transitionT_ * (std::max)(transitionSeconds_, 0.05f)) / 0.3f));
                const float wh = h * h * (3.0f - 2.0f * h);
                yA = from.yaw;
                pA = from.pitch + (aimPitch - from.pitch) * wh;
                // FIX-CAMERA-11 (pfeel33-residual-fp-to-classic-one-or-two-street-frames-with-no-car-after-the-cockpit):
                // the eye leaves the seat at ~0.17 a frame while that ease starts slowly, so for the first 3-4 frames
                // after the cockpit the car's middle was under the frame's bottom edge: street with no car (cam11_vfpc1
                // f~57-60 of both presses). The pitch is never so high that the car's middle falls below 85 % of the
                // frame height (it follows the rise; no whip: the rise is what turns it). GTA2DX9_MOVE_RISE_KEEP_CAR=0
                // turns it off (A/B).
                static int keepCarOn = -1;
                if (keepCarOn < 0) { char b[8] = {}; keepCarOn = GetEnvironmentVariableA("GTA2DX9_MOVE_RISE_KEEP_CAR", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
                if (keepCarOn) {
                    const float halfFov = 0.5f * (from.fov + (target.fov - from.fov) * e);
                    const float highest = aimPitch + 0.7f * halfFov;
                    if (pA > highest) {
                        static int keepLogs = 0;
                        if (keepLogs < 20) { ++keepLogs; Log("view: rise from the seat: pitch %.1f -> %.1f deg to keep the car in the frame (t=%.2f)", pA * 57.2958f, highest * 57.2958f, transitionT_); }
                        pA = highest;
                    }
                }
            }
            float dy2 = target.yaw - yA;
            while (dy2 > 3.14159265f) dy2 -= 6.2831853f;
            while (dy2 < -3.14159265f) dy2 += 6.2831853f;
            shown.yaw = yA + dy2 * wout;
            shown.pitch = pA + (target.pitch - pA) * wout;
        }
        shown.roll = from.roll + (target.roll - from.roll) * e;
        shown.fov = from.fov + (target.fov - from.fov) * e;
        // The sky comes up as the eye comes down, and goes as it rises (from where an
        // interrupted move left it, FIX-TRANSITION-ART: below, with the presentation).
        if (transitionToClassic_) skyBlend_ = 1.0f - e;
        else if (transitionFromClassic_) skyBlend_ = e;
        if (arriveNow) {
            shown = target;
            transitionT_ = 1.0f;
        }
        if (transitionT_ >= 1.0f) moveCatch_ = 0.6f;   // FIX-CAMERA-7: the move ends this frame (below)
        MoveTurnCap(&shown, dt, mode);
        camera_.SetPosition(shown.position);
        camera_.SetOrientation(shown.yaw, shown.pitch);
        camera_.SetRoll(shown.roll);
        camera_.SetFovY(shown.fov);
        // The HUD's world-anchored parts only line up with the classic camera
        // once it is there.
        if (transitionToClassic_) SetHudCameraMap(HudCameraMap{});
    }
    else if (moveCatch_ > 0.0f) {
        // FIX-CAMERA-7: the frames after a move into a street view ended: what the move left of the turn
        // to the view's own orientation is caught up at the same capped rate (MoveTurnCap).
        CameraPose caught = shown;
        MoveTurnCap(&caught, dt, mode);
        if (caught.yaw != shown.yaw || caught.pitch != shown.pitch) {
            shown = caught;
            camera_.SetOrientation(shown.yaw, shown.pitch);
        } else {
            moveCatch_ = 0.0f;
        }
        moveCatch_ -= dt;
    }
    // FIX-SMOOTH-SWITCH: what the picture presents follows the camera, not the key.
    // s is how far the camera has gone from the classic pose towards a street pose
    // (the move's own eased progress). The content that can only be one thing or the
    // other (the game's sprites or the figures and models, the street-only fill, the
    // modern HUD) changes over at s = 0.5, where the eased camera moves fastest, so the
    // press itself changes nothing but the camera; the ground's material cross-fades on
    // the same geometry over s 0.3..0.7, and the contact shadows come in after the
    // change-over. A move between two street views (third <-> first) is street throughout.
    {
        static int sCarry = -1;
        if (sCarry < 0) {
            char b[8] = {};
            sCarry = GetEnvironmentVariableA("GTA2DX9_MOVE_S_CARRY", b, sizeof b) && b[0] == '0' ? 0 : 1;
            Log("view: interrupted moves carry the presentation on from where they were %s (FIX-TRANSITION-ART; GTA2DX9_MOVE_S_CARRY)",
                sCarry ? "on" : "off");
        }
        const float sEnd = mode == ViewMode::Classic ? 0.0f : 1.0f;
        float s = sEnd;
        if (transitionT_ < 1.0f) {
            const float t = transitionT_;
            const float e = t * t * (3.0f - 2.0f * t);
            if (sCarry) {
                // From the s the move started at (1 for a move between the two street views, 0 or 1
                // for one from a settled view: the same as before) to the destination's.
                s = g_moveS0 + (sEnd - g_moveS0) * e;
                if (transitionFromClassic_ || transitionToClassic_ || g_moveS0 < 1.0f) skyBlend_ = s;
            } else if (transitionFromClassic_ || transitionToClassic_) {
                s = transitionToClassic_ ? 1.0f - e : e;
            }
        }
        g_presentS = s;
        const auto ramp = [](float a, float b, float x) {
            const float u = (std::min)(1.0f, (std::max)(0.0f, (x - a) / (b - a)));
            return u * u * (3.0f - 2.0f * u);
        };
        g_presentStreet = s >= 0.5f;
        g_presentMix = ramp(0.3f, 0.7f, s);
        // FIX-TRANSITION-ART (pmab5 wil zebra noise): the road-marking tiles with a re-authored
        // street copy change over near the classic end of the move, where the camera is nearly
        // overhead and its height is close to the classic one, so the plain HD art's worm-noise
        // stripes are never seen magnified on a tilted, lowered camera. The settled ends are
        // unchanged (s 0: 0, s 1: 1). GTA2DX9_ROAD_MIX_EARLY=0: the ground's ramp (A/B).
        static int roadEarly = -1;
        if (roadEarly < 0) {
            char b[8] = {};
            roadEarly = GetEnvironmentVariableA("GTA2DX9_ROAD_MIX_EARLY", b, sizeof b) && b[0] == '0' ? 0 : 1;
        }
        g_presentRoadMix = roadEarly ? ramp(0.0f, 0.2f, s) : g_presentMix;
        g_presentExtras = g_presentStreet ? ramp(0.5f, 0.85f, s) : 0.0f;
        g_viewMoving = transitionT_ < 1.0f;
    }
    ApplyPresentation(mode);
    // While the camera travels into first person nothing of the player's own body is
    // hidden either, since the eye is not yet in his head.
    // FIX-CAMERA-11 (pfl23-third-to-first-v-while-firing-camera-dives-hero-crops-no-gun-2-frames): on foot the eye
    // came to within a hand of his head well before t = 0.8, and for ~5 frames the frame was his head and the barrel
    // cut at the bottom edge (tri17_v23 f47-51) before the view model took over: from t ~0.46 the view is already
    // pitched toward the eye's while the eye is still ~0.9 behind his head, and his figure sinks out of the frame's
    // bottom (pose box top over 0.9 of the height, cam11_v23a). On foot he is left out (and the view model drawn,
    // FIX-FIGURE-10) once his feet project below the frame's bottom edge (the figure cut by it; from t 0.05, the first frame of the move excepted).
    // GTA2DX9_MOVE_FP_HIDE_NEAR=0 restores the t < 0.8 rule alone (A/B).
    if (transitionT_ < 1.0f && mode == ViewMode::FirstPerson && transitionT_ < 0.8f) {
        static int hideNearOn = -1;
        if (hideNearOn < 0) { char b[8] = {}; hideNearOn = GetEnvironmentVariableA("GTA2DX9_MOVE_FP_HIDE_NEAR", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
        const PlayerState& pl = g_viewPlayer;
        bool nearHead = false;
        if (hideNearOn && pl.valid && !pl.inVehicle) {
            const gta2::Vec3 e = camera_.Position();
            const float hx = pl.x, hy = pl.z + 0.02f, hz = static_cast<float>(gta2::kMapHeight) - pl.y;   // his feet
            const float dx = hx - e.x, dy = hy - e.y, dz = hz - e.z;
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            const float cy = std::cos(camera_.Yaw()), sy = std::sin(camera_.Yaw());
            const float cp = std::cos(camera_.Pitch()), sp = std::sin(camera_.Pitch());
            const float fwd = dx * sy * cp + dy * sp + dz * cy * cp;
            const float up = -dx * sy * sp + dy * cp - dz * cy * sp;
            const float th = std::tan(0.5f * camera_.FovY());
            const float screenY = fwd > 1e-3f ? 0.5f - 0.5f * (up / fwd) / (th > 1e-3f ? th : 1e-3f) : 2.0f;   // 0 top .. 1 bottom
            // FIX-TRANSITION-ART: only while the eye is close to him (FIX-FIGURE-10's case, the eye ~0.9
            // behind his head). From a high eye (a V pressed again while the camera was still up over the
            // street) his feet under the frame's edge only mean the camera looks past him: the first-
            // person hands were drawn over a frame seen from 3-4 blocks up. GTA2DX9_MOVE_FP_HIDE_REACH
            // (blocks, 1.6; 0 = no limit, as before).
            static float hideReach = -1.0f;
            if (hideReach < 0.0f) { char b[16] = {}; hideReach = GetEnvironmentVariableA("GTA2DX9_MOVE_FP_HIDE_REACH", b, sizeof b) ? static_cast<float>(atof(b)) : 1.6f; }
            nearHead = transitionT_ >= 0.05f && screenY > 1.0f && (hideReach <= 0.0f || d < hideReach);
            static int nearLogs = 0;
            if (nearHead && nearLogs < 20) { ++nearLogs; Log("view: move into first person: his feet at %.2f of the frame height (eye %.2f from them) at t=%.2f, his figure left out", screenY, d, transitionT_); }
        }
        if (!nearHead) SetHiddenObjects(nullptr, nullptr);
    }
    // FIX-OCCLUSION safety net, every street view (the first-person eye has already been kept
    // 0.24 clear; the chase camera solves its own boom): never closer to a surface than the
    // near plane's corners (0.09 at the widest field of view), so no wall is ever cut open.
    if (mode != ViewMode::Classic && eyecol::Ready()) {
        gta2::Vec3 p = camera_.Position();
        const float netMove = eyecol::Push(&p, 0.12f);
        if (netMove > 0.0f) {
            camera_.SetPosition(p);
            shown.position = p;
        }
        // Once a second: the closest any surface came to the camera that was shown (the
        // regression evidence: under 0.093, the near plane's corner reach, a wall is cut open).
        static float clearMin = 99.0f, clearClock = 0.0f, netMax = 0.0f;
        static int clearFrames = 0, netFrames = 0;
        static gta2::Vec3 clearAt{};
        const float nearNow = eyecol::Nearest(p, 0.6f);
        if (nearNow < clearMin) { clearMin = nearNow; clearAt = p; }
        ++clearFrames;
        if (netMove > 0.0f) { ++netFrames; netMax = (std::max)(netMax, netMove); }
        // FIX-CAMERA-17: the street objects, the cars and the people too (DynamicClearance above): the nearest each
        // came to the lens over the second, and the frames the lens was inside one (0.0 = inside its body).
        static float propMin = 9.0f, carMin = 9.0f, pedMin = 9.0f;
        static int insideFrames = 0;
        {
            const DynamicClear dc = DynamicClearance(p, g_viewPlayer.pedSprite, g_viewPlayer.inVehicle ? g_viewPlayer.vehicleSprite : nullptr);
            propMin = (std::min)(propMin, dc.prop);
            carMin = (std::min)(carMin, dc.car);
            pedMin = (std::min)(pedMin, dc.ped);
            if (dc.prop <= 0.0f || dc.car <= 0.0f || dc.ped <= 0.0f) ++insideFrames;
        }
        clearClock += dt;
        if (clearClock >= 1.0f) {
            Log("view: camera clearance (%s%s): nearest surface %.3f at %.2f,%.2f,%.2f over %d frames, safety net moved %d frames (max %.3f); "
                "map mesh only, searched to 0.6 (0.600 = no map face within 0.6); street object %.2f car %.2f person %.2f (9 = none within 3), "
                "lens inside one %d frames",
                ViewModeName(mode), transitionT_ < 1.0f ? ", moving" : "", clearMin, clearAt.x, clearAt.y, clearAt.z, clearFrames,
                netFrames, netMax, propMin, carMin, pedMin, insideFrames);
            clearMin = 99.0f; clearClock = 0.0f; netMax = 0.0f; clearFrames = netFrames = 0;
            propMin = carMin = pedMin = 9.0f; insideFrames = 0;
        }
    }
    // FIX-CAMERA-17 (owner10nov-B10): the turn budget. In third person on foot the picture never turns more than
    // [camera] turn_budget degrees (yaw, and pitch, each; at 30 fps, scaled by the frame time) from the frame shown
    // last; every frame whose camera wanted more is logged ('view: turn over budget'), the counter the operator reads
    // (it should stay at 0: the solver itself turns within the budget, see view_modes.cpp). Not across a cut (the
    // lens moved 0.6 block or more in a frame: a warp, a respawn, the swing's cut round a pocket; logged as 'view:
    // camera cut'), nor while the mouse turns the camera (the player's flick).
    // GTA2DX9_CAM_TURN_BUDGET=0 (or turn_budget=0) turns it off (A/B).
    {
        static bool havePrev = false;
        static float prevYaw = 0.0f, prevPitch = 0.0f;
        static gta2::Vec3 prevPos{};
        static int prevFrame = -5;
        static long overLogs = 0;
        const float budget = CameraTurnBudgetDeg();
        const bool onFoot3 = mode == ViewMode::ThirdPerson && !(g_viewPlayer.valid && g_viewPlayer.inVehicle);
        if (budget > 0.0f && onFoot3 && havePrev && prevFrame + 1 == frameCount_) {
            const gta2::Vec3 e = camera_.Position();
            const float jump = std::sqrt((e.x - prevPos.x) * (e.x - prevPos.x) + (e.y - prevPos.y) * (e.y - prevPos.y) + (e.z - prevPos.z) * (e.z - prevPos.z));
            LARGE_INTEGER c, f;
            QueryPerformanceCounter(&c);
            QueryPerformanceFrequency(&f);
            const double nowS = static_cast<double>(c.QuadPart) / static_cast<double>(f.QuadPart);
            const bool mouse = LookOffsets().lastMoved > 0.0 && nowS - LookOffsets().lastMoved < 0.3;
            if (jump >= 0.6f && !mouse) {
                // a cut (the swing round a pocket with no way open, a warp, a respawn): the lens jumped, the picture did
                // not turn; counted apart
                static long cuts = 0;
                ++cuts;
                if (cuts <= 500) Log("view: camera cut (not a turn): the lens moved %.2f in one frame (%ld so far)", jump, cuts);
            }
            if (jump < 0.6f && !mouse) {
                const float cap = budget * 0.0174533f * (std::min)(1.5f, (std::max)(0.25f, dt * 30.0f));
                float dy = camera_.Yaw() - prevYaw;
                while (dy > 3.14159265f) dy -= 6.2831853f;
                while (dy < -3.14159265f) dy += 6.2831853f;
                const float dp = camera_.Pitch() - prevPitch;
                if (std::fabs(dy) > cap || std::fabs(dp) > cap) {
                    const float ny = prevYaw + (std::max)(-cap, (std::min)(cap, dy));
                    const float np = prevPitch + (std::max)(-cap, (std::min)(cap, dp));
                    ++overLogs;
                    if (overLogs <= 3000 || (overLogs % 30) == 0)
                        Log("view: turn over budget: wanted yaw %+.1f pitch %+.1f deg this frame, budget %.1f (dt %.3f), shown %+.1f %+.1f (%ld so far)",
                            dy * 57.2958f, dp * 57.2958f, cap * 57.2958f, dt, (ny - prevYaw) * 57.2958f, (np - prevPitch) * 57.2958f, overLogs);
                    camera_.SetOrientation(ny, np);
                    shown.yaw = ny;
                    shown.pitch = np;
                }
            }
        }
        havePrev = mode != ViewMode::Classic;
        prevYaw = camera_.Yaw();
        prevPitch = camera_.Pitch();
        prevPos = camera_.Position();
        prevFrame = frameCount_;
    }
    {
        // FIX-CAMERA-2 (pm11): the shown pose against the view's own for 3 s after a switch
        // (GTA2DX9_LOG_CAMERA=1), every third frame.
        static int logEnv = -1;
        if (logEnv < 0) { char b[8] = {}; logEnv = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", b, sizeof b) && atoi(b) ? 1 : 0; }
        static float since = 99.0f;
        static int n = 0;
        if (transitionT_ < 1.0f && transitionT_ <= dt / (std::max)(transitionSeconds_, 0.05f) + 1e-4f) since = 0.0f;
        since += dt;
        // How far the shown view points from the destination's look point (2.4 along its view).
        const gta2::Vec3 tf{std::sin(target.yaw) * std::cos(target.pitch), std::sin(target.pitch), std::cos(target.yaw) * std::cos(target.pitch)};
        const gta2::Vec3 lk = target.position + tf * 2.4f - shown.position;
        const gta2::Vec3 sf{std::sin(shown.yaw) * std::cos(shown.pitch), std::sin(shown.pitch), std::cos(shown.yaw) * std::cos(shown.pitch)};
        const float ll = std::sqrt(lk.x * lk.x + lk.y * lk.y + lk.z * lk.z);
        const float off = ll > 1e-3f ? std::acos((std::max)(-1.0f, (std::min)(1.0f, (lk.x * sf.x + lk.y * sf.y + lk.z * sf.z) / ll))) * 57.2958f : 0.0f;
        static float lastYaw = 0.0f;
        float yawStep = shown.yaw - lastYaw;
        while (yawStep > 3.14159265f) yawStep -= 6.2831853f;
        while (yawStep < -3.14159265f) yawStep += 6.2831853f;
        lastYaw = shown.yaw;
        if (logEnv && since < 3.0f && (mode != ViewMode::Classic || transitionT_ < 1.0f))
            Log("view move: t=%.2f %s pos=%.2f,%.2f,%.2f yaw=%.1f pitch=%.1f roll=%.1f off=%.1f ystep=%.1f | view pos=%.2f,%.2f,%.2f yaw=%.1f pitch=%.1f",
                transitionT_, ViewModeName(mode), shown.position.x, shown.position.y, shown.position.z, shown.yaw * 57.2958f,
                shown.pitch * 57.2958f, shown.roll * 57.2958f, off, yawStep * 57.2958f, target.position.x, target.position.y, target.position.z,
                target.yaw * 57.2958f, target.pitch * 57.2958f);
    }
    {
        // FIX-CAMERA-6: every street frame (and every frame of a move), the pose that is shown and
        // where his figure (on foot: feet to head) or his car (its footprint box) lands on the screen,
        // 0..1 from the left and from the top (GTA2DX9_LOG_CAMERA=1). The tables of the camera work
        // orders (pitch steps, eye steps, the hero in frame) are read off these lines.
        static int poseLog = -1;
        if (poseLog < 0) { char b[8] = {}; poseLog = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", b, sizeof b) && atoi(b) ? 1 : 0; }
        if (poseLog && (mode != ViewMode::Classic || transitionT_ < 1.0f)) {
            const gta2::Vec3 e = camera_.Position();
            const float cyw = camera_.Yaw(), cpt = camera_.Pitch(), fovY = camera_.FovY();
            const float sy = std::sin(cyw), cy = std::cos(cyw), sp = std::sin(cpt), cpv = std::cos(cpt);
            const float th = std::tan(0.5f * fovY), tw = th * (16.0f / 9.0f);
            float hx = 0.0f, hy = 0.0f, hz = 0.0f;
            bool inCar = false;
            const bool have = viewSolver_.LastPlayer(&hx, &hy, &hz, &inCar);
            float x0 = 9.0f, x1 = -9.0f, y0 = 9.0f, y1 = -9.0f;
            bool behind = false;
            auto add = [&](float x, float y, float z) {
                const float dx = x - e.x, dy = y - e.y, dz = z - e.z;
                const float zf = dx * sy * cpv + dy * sp + dz * cy * cpv;
                if (zf < 0.02f) { behind = true; return; }
                const float sx = 0.5f + 0.5f * (dx * cy - dz * sy) / zf / tw;
                const float syy = 0.5f - 0.5f * (-dx * sy * sp + dy * cpv - dz * cy * sp) / zf / th;
                x0 = (std::min)(x0, sx); x1 = (std::max)(x1, sx); y0 = (std::min)(y0, syy); y1 = (std::max)(y1, syy);
            };
            if (have && !inCar) {
                // his axis, feet to the top of the head, and his width either side at the chest (seen from the eye)
                add(hx, hy, hz);
                add(hx, hy + 0.48f, hz);
                const float sx = std::cos(cyw), sz = -std::sin(cyw);   // the view's right
                add(hx + sx * 0.12f, hy + 0.3f, hz + sz * 0.12f);
                add(hx - sx * 0.12f, hy + 0.3f, hz - sz * 0.12f);
            } else if (have) {
                const CameraCar* own = nullptr;
                float best = 1e9f;
                for (const CameraCar& c : LiveCameraCars()) {
                    const float cx = 0.25f * (c.x[0] + c.x[1] + c.x[2] + c.x[3]), cz = 0.25f * (c.z[0] + c.z[1] + c.z[2] + c.z[3]);
                    const float d = std::hypot(cx - hx, cz - hz);
                    if (d < best && d < 1.5f) { best = d; own = &c; }
                }
                if (own)
                    for (int i = 0; i < 4; ++i) { add(own->x[i], own->y0, own->z[i]); add(own->x[i], own->y1, own->z[i]); }
            }
            static gta2::Vec3 lastE{};
            static float lastPitch = 0.0f;
            static int lastFrame = -5;
            const bool prev = lastFrame + 1 == frameCount_;
            const float step = prev ? std::sqrt((e.x - lastE.x) * (e.x - lastE.x) + (e.y - lastE.y) * (e.y - lastE.y) + (e.z - lastE.z) * (e.z - lastE.z)) : 0.0f;
            const float pstep = prev ? (cpt - lastPitch) * 57.2958f : 0.0f;
            // FIX-CAMERA-17: the yaw turned since the last frame too (ystep, at the line's end)
            static float lastYawPose = 0.0f;
            float ystep = prev ? cyw - lastYawPose : 0.0f;
            while (ystep > 3.14159265f) ystep -= 6.2831853f;
            while (ystep < -3.14159265f) ystep += 6.2831853f;
            lastYawPose = cyw;
            lastE = e; lastPitch = cpt; lastFrame = frameCount_;
            Log("cam: pose f=%d %s t=%.2f eye=%.2f,%.2f,%.2f yaw=%.1f pitch=%.1f fov=%.1f step=%.3f pstep=%.1f %s=%.2f,%.2f,%.2f box=%.2f..%.2f,%.2f..%.2f%s roll=%.1f ystep=%.1f",
                frameCount_, ViewModeName(mode), transitionT_, e.x, e.y, e.z, cyw * 57.2958f, cpt * 57.2958f, fovY * 57.2958f, step, pstep,
                inCar ? "car" : "hero", hx, hy, hz, x0, x1, y0, y1, behind ? " behind" : "", camera_.Roll() * 57.2958f, ystep * 57.2958f);
        }
    }
    lastPose_ = shown;
    lastPoseValid_ = true;
    // The visual regression harness's fixed camera (regress_cam.h; off unless
    // GTA2DX9_REGRESS_CAM is set): the street views only, the classic view stays the game's.
    if (mode != ViewMode::Classic && transitionT_ >= 1.0f) RegressCameraOverride(&camera_);
    {   // FIX-COCKPIT-CAB-4 (owner O2g: looking down at the wheel the arms ended in the near plane's cut, forearm fragments
        // floating at the frame's edges): his shoulders sit ~0.045 block from the eye, inside the 0.05 near plane. Looking
        // down the far scene leaves the frame (its top edge reaches the horizon at 35 degrees), so the near plane eases in
        // from 28 degrees to 0.028 by 42 degrees (the arms whole from the frame's edge to the rim, cab4_near3 068) without the far depth
        // precision a smaller near would cost a level view (at 40 degrees the old 0.05 still cut the forearms, cab4_near5); from 42 to 72 degrees (straight down at the lap) it eases back
        // out to 0.030, which still clips his collar and chin under the eye (0.020-0.028 showed a skin sliver there, 0.034 cut
        // the arm into a floating elbow again: cab4_near3/near4 on 021 and 068).
        // First person in a vehicle only; every other view keeps 0.05. GTA2DX9_FP_NEAR_LOOKDOWN=0: off (A/B); [devtools]
        // fp_near_min_milli / fp_near_deep_milli: the two floors live.
        constexpr float kFpNearLookDownMin = 0.028f, kFpNearLookDownDeep = 0.030f;
        static const bool nearOn = [] { char v[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_FP_NEAR_LOOKDOWN", v, sizeof v) && v[0] == '0'); }();
        float nearZ = 0.05f;
        if (nearOn && mode == ViewMode::FirstPerson && g_viewPlayer.valid && g_viewPlayer.inVehicle) {
            const float down = -camera_.Pitch() * 57.29578f;
            const int devMin = CarDevFpNearMinMilli(), devDeep = CarDevFpNearDeepMilli();
            const float floorMin = devMin > 0 ? devMin / 1000.0f : kFpNearLookDownMin;
            const float floorDeep = devDeep > 0 ? devDeep / 1000.0f : kFpNearLookDownDeep;
            auto smooth = [](float x) { x = (std::max)(0.0f, (std::min)(1.0f, x)); return x * x * (3.0f - 2.0f * x); };
            const float in = smooth((down - 28.0f) / 14.0f), out = smooth((down - 42.0f) / 30.0f);
            nearZ = 0.05f + (floorMin - 0.05f) * in + (floorDeep - floorMin) * out;
        }
        // FIX-COCKPIT-CAB-4 (qav12 rest, dg2 forearm band): the post's AO and hemisphere skip the cockpit (cab, bonnet, his
        // arms: nearer than 0.6 block) in first person at the wheel; their depth-rebuilt normals are noise at that range
        // (the bonnet mottled ~25 % darker than the same paint in third at dawn, the dash's crease laid over the forearm).
        // GTA2DX9_FP_POST_REACH=<milli> (0 = off, the old composite).
        {
            static const float reach = [] { char v[12] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_POST_REACH", v, sizeof v) ? atoi(v) / 1000.0f : 0.6f; }();
            gta2::SetPostCockpitReach(mode == ViewMode::FirstPerson && g_viewPlayer.valid && g_viewPlayer.inVehicle ? reach : 0.0f);
        }
        if (nearZ != camera_.NearZ()) {
            static int logs = 0;
            if (logs < 40 && std::fabs(nearZ - camera_.NearZ()) > 0.01f) { ++logs; Log("view: near plane %.3f (first person look-down %.0f deg)", nearZ, -camera_.Pitch() * 57.29578f); }
            camera_.SetNearZ(nearZ);
        }
    }
    // ANIM-VEHICLE-ENTRY verification aid (GTA2DX9_BOARDING_CAM=1, off by default): beside the door.
    gta2::Vec3 boardEye; float boardYaw = 0.0f, boardPitch = 0.0f;
    if (mode != ViewMode::Classic && BoardingDebugCamera(&boardEye, &boardYaw, &boardPitch)) {
        camera_.SetPosition(boardEye);
        camera_.SetOrientation(boardYaw, boardPitch);
        camera_.SetRoll(0.0f);
    }
}

// The game's zoom has to come from the camera struct, not from the visible tile
// rectangle: that rectangle is a whole number of tiles, so using it as the zoom
// source can only ever change in steps. This dumps the struct so the continuous
// field driving zoom can be identified from real gameplay rather than guessed.
void WorldView::DumpCameraStruct() const {
    const uint8_t* camera = game::CameraStruct();
    if (!camera) return;

    char line[512];
    int used = snprintf(line, sizeof(line), "cam[%d] bounds=%.1f,%.1f..%.1f,%.1f |", frameCount_,
                        minX_, minY_, maxX_, maxY_);
    for (uintptr_t offset = 0x60; offset <= 0xC0 && used > 0 && used < (int)sizeof(line) - 32;
         offset += 4) {
        const int32_t raw = *reinterpret_cast<const int32_t*>(camera + offset);
        const float asFloat = *reinterpret_cast<const float*>(camera + offset);
        // Report both readings; the struct mixes 16.14 fixed point with floats.
        used += snprintf(line + used, sizeof(line) - used, " %02X:%.3f/%.3f", (unsigned)offset,
                         raw * game::kFixedScale, asFloat);
    }
    Log("%s", line);
}

void WorldView::CheckDrawnTile(const void* textureRecord) {
    if (map_.Empty() || tileChecks_ >= 24) return;

    float cellX = 0.0f, cellY = 0.0f;
    int level = 0;
    if (!game::CurrentCell(&cellX, &cellY, &level)) return;

    const int x = static_cast<int>(cellX + 0.5f);
    const int y = static_cast<int>(cellY + 0.5f);
    if (x < 0 || x >= gta2::kMapWidth || y < 0 || y >= gta2::kMapHeight) return;

    const int drawn = game::TileForTexture(textureRecord);
    if (drawn <= 0) return;

    // What our own walk of the map has at that cell and level.
    const gta2::Column& column = map_.ColumnAt(x, y);
    const int slot = level - column.offset;
    int ours[5] = {-1, -1, -1, -1, -1};
    if (slot >= 0 && slot < static_cast<int>(column.blocks.size())) {
        const gta2::Block& block = map_.BlockAt(column.blocks[slot]);
        ours[0] = block.left.Tile();
        ours[1] = block.right.Tile();
        ours[2] = block.top.Tile();
        ours[3] = block.bottom.Tile();
        ours[4] = block.lid.Tile();
    }

    const bool match = drawn == ours[0] || drawn == ours[1] || drawn == ours[2] ||
                       drawn == ours[3] || drawn == ours[4];
    Log("tilecheck cell=(%d,%d) lvl=%d game=%d ours[l/r/t/b/lid]=%d/%d/%d/%d/%d %s", x, y, level,
        drawn, ours[0], ours[1], ours[2], ours[3], ours[4], match ? "MATCH" : "MISMATCH");
    ++tileChecks_;
}

// The game writes each projected vertex's absolute world position four slots
// further along the vertex array, so the shape it actually draws for a block can
// be read straight off. Positions are in the game's own frame: x east, y south,
// z the level.
void WorldView::CheckDrawnShape(int corners) {
    const int slopeType = game::CurrentBlockSlopeType();
    if (slopeType < 45 || slopeType > 61) return;
    if (shapeChecks_ >= 40) return;

    float cellX = 0.0f, cellY = 0.0f;
    int level = 0;
    if (!game::CurrentCell(&cellX, &cellY, &level)) return;

    char line[320];
    int used = snprintf(line, sizeof(line), "shape type=%d cell=(%.0f,%.0f) lvl=%d %s", slopeType,
                        cellX, cellY, level, corners == 3 ? "tri" : "quad");
    for (int i = 0; i < corners && used > 0 && used < static_cast<int>(sizeof(line)) - 40; ++i) {
        const float* world = reinterpret_cast<const float*>(
            game::kTileVertexArray +
            static_cast<uintptr_t>(i + game::kWorldShadowSlots) * game::kVertexStride);
        used += snprintf(line + used, sizeof(line) - used, "  (%.3f %.3f %.3f)", world[0], world[1],
                         world[2]);
    }
    Log("%s", line);
    ++shapeChecks_;
}

// The sky dome and the world shading of the street views, weighted by the
// transition's blend. The sun stands where the ini says, or follows the
// day/night clock when asked to. Under a Remix runtime with an atmosphere of
// its own the dome is left out: that sky is the real one.
void WorldView::DrawSkyAndShading() {
    const gta2::SkySettings& sky = gta2::SkyConfig();
    const float blend = (sky.enabled && worldUploaded_ && !RemixApiHasAtmosphere()) ? skyBlend_ : 0.0f;
    if (blend <= 0.0f) {
        renderer_.SetWorldShading(gta2::WorldShading{});
        return;
    }
    float elevation = sky.sunElevationDeg, azimuth = sky.sunAzimuthDeg;
    if (sky.followClock) TimeOfDayAngles(&elevation, &azimuth);
    const gta2::SkyColours colours = gta2::ComputeSkyColours(elevation, azimuth);

    gta2::WorldShading shading;
    shading.fog = true;
    shading.fogColour = colours.fog;
    // The fog eases in with the sky: from far away and faint to its real reach.
    shading.fogStart = sky.fogStart + (600.0f - sky.fogStart) * (1.0f - blend);
    shading.fogEnd = sky.fogEnd + (2000.0f - sky.fogEnd) * (1.0f - blend);
    shading.sun = sky.sunLight > 0.001f || sky.ambient < 0.999f;
    shading.sunDir = colours.sunDir;
    // At night the sun is below the horizon and contributes nothing; the
    // ambient falls with the daylight, but never below a readable level since
    // nothing else in the raster picture gets darker at night.
    const float dayLight = gta2::AmbientDayLight(colours);
    const float ambient = 1.0f + (sky.ambient * dayLight - 1.0f) * blend;
    shading.ambient = gta2::Vec3{ambient, ambient, ambient};
    shading.ambient = gta2::Vec3{shading.ambient.x * colours.ambient.x, shading.ambient.y * colours.ambient.y,
                                 shading.ambient.z * colours.ambient.z};
    shading.sunColour = colours.sunColour * (sky.sunLight * blend * colours.day);
    renderer_.SetWorldShading(shading);

    LARGE_INTEGER counter, frequency;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&frequency);
    // RegressClock: held still for the visual regression harness (regress_cam.h), else as is.
    const double seconds = RegressClock(static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart));
    renderer_.SetWaterClock(seconds);
    renderer_.DrawSky(camera_, sky, colours, blend, seconds);
}

// FIX-PERF-VSWITCH: the first V of a session froze the game for 0.5-9 s (defect
// first-v-press-freezes-game-up-to-9s-world-upload). Most of it was not the uploads: wined3d makes a
// GL program for each new fixed-function state and for each shader the first time a draw uses it,
// and the street views' first frames use dozens the classic view never does (the sky, the lit and
// fogged world, water, the post passes and shadows, lit figures, tinted paint): with the driver's
// shader cache warm the same switch cost 371 ms instead of 0.8-2.3 s (out/vsw_glcb1 vs vsw_glcb2).
// So, once, on the second frame of a level (inside the level's own loading stall: drawn 3 s into play
// it was a 0.8 s classic hitch, out/vsw_a3c_2), the classic view draws one street frame - sky, shading,
// world with its street fill, post passes, a prop, the avatar, a car and the sprite pass's states -
// into targets of its own
// that are never shown, every device state captured before and put back after. The classic
// frame itself is already complete (and kept for the dissolve) when this runs; what is presented
// is unchanged. GTA2DX9_GHOST_FRAME=0 turns it off for a before/after run.
// LIGHTING-V1 (owner: day/night must agree between the classic view and the street views in both renderers). By day and
// under a clear sky nothing runs and the classic frame is the game's own, pixel for pixel (vreg spawn_classic at 12:30).
// As the clock leaves full day the frame (world and sprites, not the HUD) is graded with the hour's tint
// (TimeOfDayClassicGrade: the street views' daylight curve and the weather's overcast, composed in time_of_day.cpp), and
// the game's lights lay pools on it: the map's lamps (at their own staggered switching), car head lamps ahead of the car,
// brake lamps, sirens and fires, projected with the classic camera. Lit texels (lamp heads, neon, tail lamps) keep their
// own brightness in the shader. GTA2DX9_CLASSIC_NIGHT=0: off (the classic view always as drawn).
void WorldView::ApplyClassicNight(float weight) {
    static int off = -1;
    if (off < 0) { char b[8] = {}; off = GetEnvironmentVariableA("GTA2DX9_CLASSIC_NIGHT", b, sizeof b) && b[0] == '0' ? 1 : 0; }
    if (off) return;
    float tint[3], amount = 0.0f, night = 0.0f;
    TimeOfDayClassicGrade(tint, &amount, &night);
    amount *= weight < 0.0f ? 0.0f : (weight > 1.0f ? 1.0f : weight);
    if (amount <= 0.001f) return;
    const int w = renderer_.Width(), h = renderer_.Height();
    const gta2::Mat4 view = camera_.ViewMatrix();
    const gta2::Mat4 proj = camera_.ProjectionMatrix(static_cast<float>(w) / static_cast<float>((std::max)(1, h)));
    auto toScreen = [&](float x, float y, float z, float* sx, float* sy) {
        const float vx = x * view.m[0][0] + y * view.m[1][0] + z * view.m[2][0] + view.m[3][0];
        const float vy = x * view.m[0][1] + y * view.m[1][1] + z * view.m[2][1] + view.m[3][1];
        const float vz = x * view.m[0][2] + y * view.m[1][2] + z * view.m[2][2] + view.m[3][2];
        const float cx = vx * proj.m[0][0] + vy * proj.m[1][0] + vz * proj.m[2][0] + proj.m[3][0];
        const float cy = vx * proj.m[0][1] + vy * proj.m[1][1] + vz * proj.m[2][1] + proj.m[3][1];
        const float cw = vx * proj.m[0][3] + vy * proj.m[1][3] + vz * proj.m[2][3] + proj.m[3][3];
        if (!(cw > 0.05f)) return false;
        *sx = (0.5f + 0.5f * cx / cw) * w;
        *sy = (0.5f - 0.5f * cy / cw) * h;
        return true;
    };
    std::vector<gta2::PostFx::ClassicPool> pools;
    if (night > 0.02f) {
        for (const RemixTrackedLight& t : LightsTracked()) {
            const RemixLightDesc& d = t.def;
            if (d.intensity < 0.02f) continue;
            float pos[3] = {d.pos[0], d.pos[1], d.pos[2]}, reach = 0.0f, gain = 0.0f, share = night;
            float rgb[3] = {d.rgb[0], d.rgb[1], d.rgb[2]};
            switch (d.source) {
                case kLightSourceGame: {
                    const float own = LightsTrackedDaylight(t);
                    share = own >= 0.0f ? own : 1.0f;   // ungated classes (signals) at every hour
                    if (d.spot) continue;               // the Remix pool under a fitted lamp: the lamp itself stands for it
                    // A disc round each street lamp (the plaza's lamps overlapped into one wash at 3 blocks); a sign or other
                    // map light only a small glow at its spot.
                    if (ClassifyGameLight(d, false) == kGameLightStreet) { reach = (std::min)(1.8f, (std::max)(1.0f, d.radius * 0.5f)); gain = 0.9f; }
                    else { reach = 0.8f; gain = 0.5f; }
                    gain *= (std::min)(1.0f, d.intensity);
                    // As the street views draw them (visuals.cpp FIX-WORLD-20/21, FIX-REMIX-NIGHT-8): a street-class lamp is
                    // a sodium amber at its own luminance, a sign keeps 30 % of its hue over a warm white; the game's raw
                    // colours (#FF8080, #80FF00 ...) summed over the plaza washed the classic frame pink and green.
                    {
                        const uint8_t klass = ClassifyGameLight(d, false);
                        static const float kSodium[3] = {1.0f, 0.64f, 0.28f}, kWarm[3] = {1.0f, 0.86f, 0.66f};
                        const float* to = klass == kGameLightStreet ? kSodium : kWarm;
                        const float keep = klass == kGameLightStreet ? 0.0f : 0.3f;
                        const float lum = (std::max)(0.45f, 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2]);
                        const float tl = 0.2126f * to[0] + 0.7152f * to[1] + 0.0722f * to[2];
                        for (int i = 0; i < 3; ++i) rgb[i] = keep * rgb[i] + (1.0f - keep) * to[i] * lum / tl;
                    }
                    break;
                }
                case kLightSourceHeadlight:
                    for (int i = 0; i < 3; ++i) pos[i] += d.dir[i] * 1.5f;
                    reach = 1.9f; gain = 0.9f; break;
                case kLightSourceBrake: reach = 0.8f; gain = 0.6f; break;
                case kLightSourceSiren: reach = d.spot ? 0.0f : 2.4f; gain = 0.40f; share = (std::max)(night, 0.3f); break;
                case kLightSourceFire: reach = 2.4f; gain = 0.6f; share = 1.0f; break;
                default: continue;
            }
            if (reach <= 0.0f || share <= 0.01f) continue;
            float sx, sy, ex, ey;
            if (!toScreen(pos[0], pos[1], pos[2], &sx, &sy) || !toScreen(pos[0] + reach, pos[1], pos[2], &ex, &ey)) continue;
            const float r = std::sqrt((ex - sx) * (ex - sx) + (ey - sy) * (ey - sy));
            if (r < 2.0f || sx < -r || sy < -r || sx > w + r || sy > h + r) continue;
            gta2::PostFx::ClassicPool p{sx, sy, r, {rgb[0] * gain * share, rgb[1] * gain * share, rgb[2] * gain * share}};
            pools.push_back(p);
            if (pools.size() >= 160) break;
        }
    }
    const bool ok = renderer_.ClassicNight(tint, amount, pools);
    static int logged = 0;
    if ((frameCount_ % 600) == 0 && logged < 40) {
        ++logged;
        Log("classic night: tint %.2f %.2f %.2f night %.2f, %d pools%s", tint[0], tint[1], tint[2], night,
            static_cast<int>(pools.size()), ok ? "" : " (pass unavailable)");
    }
}

void WorldView::GhostStreetFrame() {
    LARGE_INTEGER a, b, f;
    QueryPerformanceCounter(&a);
    const gta2::SkySettings& sky = gta2::SkyConfig();
    const bool street = sky.enabled && !RemixApiHasAtmosphere();
    gta2::Camera cam = camera_;
    const gta2::Vec3 over = camera_.Position();
    cam.SetPosition(gta2::Vec3{over.x, 3.0f, over.z - 4.0f});
    cam.SetOrientation(0.0f, -0.30f);
    cam.SetFovY(1.1f);
    cam.SetRoll(0.0f);
    if (!renderer_.BeginGhostFrame()) return;
    if (street) {
        float elevation = sky.sunElevationDeg, azimuth = sky.sunAzimuthDeg;
        if (sky.followClock) TimeOfDayAngles(&elevation, &azimuth);
        const gta2::SkyColours colours = gta2::ComputeSkyColours(elevation, azimuth);
        gta2::WorldShading shading;
        shading.fog = true;
        shading.fogColour = colours.fog;
        shading.fogStart = sky.fogStart;
        shading.fogEnd = sky.fogEnd;
        shading.sun = sky.sunLight > 0.001f || sky.ambient < 0.999f;
        shading.sunDir = colours.sunDir;
        const float ambient = sky.ambient * gta2::AmbientDayLight(colours);
        shading.ambient = gta2::Vec3{ambient * colours.ambient.x, ambient * colours.ambient.y, ambient * colours.ambient.z};
        shading.sunColour = colours.sunColour * (sky.sunLight * colours.day);
        renderer_.SetWorldShading(shading);
        LARGE_INTEGER counter, frequency;
        QueryPerformanceCounter(&counter);
        QueryPerformanceFrequency(&frequency);
        renderer_.DrawSky(cam, sky, colours, 1.0f, static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart));
    }
    renderer_.SetStreetView(true, 1.0f);   // the photo set, as a settled street view binds it
    renderer_.DrawWorld(cam);
    if (IDirect3DDevice9* device = renderer_.Device()) {
        const gta2::Mat4 view = cam.ViewMatrix();
        const gta2::Mat4 proj = cam.ProjectionMatrix(static_cast<float>(renderer_.Width()) / static_cast<float>((std::max)(1, renderer_.Height())));
        D3DMATRIX m;
        memcpy(&m, view.m, sizeof m);
        device->SetTransform(D3DTS_VIEW, &m);
        memcpy(&m, proj.m, sizeof m);
        device->SetTransform(D3DTS_PROJECTION, &m);
        gta2::Mat4 at = {};
        at.m[0][0] = at.m[1][1] = at.m[2][2] = 0.5f;
        at.m[3][0] = over.x; at.m[3][1] = 2.0f; at.m[3][2] = over.z; at.m[3][3] = 1.0f;
        ModelsGhostDraws(device, at);
    }
    if (street) renderer_.EndWorldShading();
    renderer_.EndGhostFrame();
    LiveGeometryGhostSprites();   // and the sprite pass, in the next classic frame's own draw
    QueryPerformanceCounter(&b);
    QueryPerformanceFrequency(&f);
    Log("view: street frame drawn unseen in the classic view (frame %d, %.1f ms queued), for the first V",
        frameCount_, 1000.0 * static_cast<double>(b.QuadPart - a.QuadPart) / static_cast<double>(f.QuadPart));
}

void WorldView::RenderFrame() {
    LARGE_INTEGER entryStamp;
    QueryPerformanceCounter(&entryStamp);
    if (!EnsureDevice()) return;
    if (FrameLogEnabled()) FrameLogAttachDevice(renderer_.Device());
    MemStatsTick();   // FIX-PERF-4: the per-minute `mem:` line; an allocation failure holds classic

    if (window_ != gameWindow_) {
        // The game pumps its own window, not ours, and an unpumped window is a
        // hung one as far as Windows is concerned.
        MSG message;
        while (PeekMessageA(&message, window_, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageA(&message);
        }
        // The game window is often not yet shown when Initialize runs, so the
        // focus is asked for again once it has been up for a moment - only while
        // the foreground still belongs to another process.
        if (frameCount_ == 90 || frameCount_ == 400) {
            DWORD foregroundPid = 0;
            if (HWND foreground = GetForegroundWindow()) GetWindowThreadProcessId(foreground, &foregroundPid);
            if (foregroundPid != GetCurrentProcessId()) GiveGameForeground(gameWindow_);
        }
        // The game is free to reorder or resize its own children; re-stating
        // where ours belongs occasionally is cheaper than trusting it not to.
        // FIX-STABILITY-1: not while the game has lost the focus (SetGameActive took us out of the
        // topmost band), but notice when the foreground came back without a message saying so.
        if ((frameCount_ & 0x3F) == 0 && !active_) {
            DWORD foregroundPid = 0;
            if (HWND foreground = GetForegroundWindow()) GetWindowThreadProcessId(foreground, &foregroundPid);
            if (foregroundPid == GetCurrentProcessId()) SetGameActive(true, "the foreground is ours again");
        }
        if ((frameCount_ & 0x3F) == 0 && active_) {
            SetWindowPos(window_, present_ == PresentWindow::Topmost ? HWND_TOPMOST : HWND_TOP, 0, 0,
                         width_, height_,
                         SWP_NOACTIVATE | SWP_SHOWWINDOW |
                             (present_ == PresentWindow::Topmost ? SWP_NOMOVE : 0));
        }
    }

    // FIX-STABILITY-1: minimised, nothing is drawn or presented (a swap chain on an iconic window is
    // what the owner's 5090 died around); the window messages above are still pumped.
    if (parked_) {
        if (!parkSimulated_ && gameWindow_ && !IsIconic(gameWindow_)) {
            SetGameParked(false, "the game window is not minimised any more");
        } else {
            ++parkedFrames_;
            return;
        }
    }

    LARGE_INTEGER preStamp[6] = {};
    QueryPerformanceCounter(&preStamp[0]);
    EnsureWorldLoaded();
    QueryPerformanceCounter(&preStamp[1]);
    RefreshAnimatedTiles();
    QueryPerformanceCounter(&preStamp[2]);
    // The view's own key and, in a chase or first-person view, the mouse.
    ViewModePollInput(window_, DebugMenuVisible(), worldUploaded_);
    QueryPerformanceCounter(&preStamp[3]);
    UpdateCamera();
    QueryPerformanceCounter(&preStamp[4]);

    // The game's own screen size is what its HUD coordinates are expressed in,
    // and it is not our back buffer size. Prefer the camera struct, which holds
    // it as plain pixel integers; gbh_SetWindow covers the menus, where no
    // camera exists yet.
    // Only while a world is loaded. The camera struct pointer outlives the level
    // it described, so at the menu this reads a freed allocation - which laid the
    // front end out to the wrong scale, and made it jitter as the allocator
    // handed that memory to something else. gbh_SetWindow is the authority there,
    // which is what its own comment in overlay.cpp has always said.
    if (worldUploaded_) {
        if (const uint8_t* camera = game::CameraStruct()) {
            const int32_t screenW =
                *reinterpret_cast<const int32_t*>(camera + game::kScreenWidthOffset);
            const int32_t screenH =
                *reinterpret_cast<const int32_t*>(camera + game::kScreenHeightOffset);
            if (screenW >= 320 && screenW <= 8192 && screenH >= 200 && screenH <= 8192) {
                overlay_.SetGameScreenSize(screenW, screenH);
            }
        }
    }

    // The bridge server is a separate process that is still starting while the
    // game asks its renderer to initialise, so this is retried from the frame
    // loop until it takes, exactly like the device is.
    RemixApiInit();
    // FIX-STABILITY-1: [sky] follow_clock=auto turns into 1 the first frame the Remix API answers.
    {
        gta2::SkySettings& sky = gta2::SkyConfig();
        if (sky.followClockAuto && RemixApiAvailable()) {
            sky.followClockAuto = false;
            sky.followClock = true;
            Log("sky: follow_clock=auto: RTX Remix runtime detected, the sun follows the clock (one sun with Remix's sky)");
        }
        // LIGHTING-V1: in the plain renderer the night has its lamps, neon, lit windows and car lamps once the [visuals]
        // passes are on, so the day/night cycle runs there too: auto follows the clock while [visuals] is on (re-read
        // live), and keeps the fixed [sky] sun with them off (v1.5's look, where nothing else goes dark at night).
        if (sky.followClockAuto) {
            // ([weather] on with time_of_day=1 forces it on by itself, weather.cpp ApplyClock: kept on then.)
            const bool want = gta2::VisualsConfig().enabled || gta2::WeatherNow().active;
            if (want != sky.followClock) {
                sky.followClock = want;
                Log("sky: follow_clock=auto: %s", want ? "[visuals] on, the street views' sun follows the clock (day/night cycle)"
                                                      : "[visuals] off, the fixed [sky] sun");
            }
        }
    }
    // Not conditional on that: when Remix is absent the menu is the thing that
    // says so, which it cannot do if it only exists once Remix is there.
    DebugMenuInit(gameWindow_, window_, renderer_.Device());
    DebugMenuPoll();

    // The sky. Runs whether or not Remix answered - the clock is ours and the
    // menu shows it either way - and pushes the sun when it can.
    QueryPerformanceCounter(&preStamp[5]);
    TimeOfDayUpdate();

    // Lights for the effects the game draws but never lights, read straight off
    // its particle and vehicle lists. Before the reconcile, so they are matched
    // and handled in the same pass as the game's own.
    LARGE_INTEGER stamp[kStages + 1] = {};
    QueryPerformanceCounter(&stamp[0]);
    SyntheticLightsUpdate();
    ShotLightsSubmit();   // the figures' muzzle flashes (live_geometry), lit by Remix
    // The light benchmark's own lights, when one is running. See light_bench.h.
    LightBenchSubmit();
    // The street views see far past the game's own top-down window, and the
    // game lists only the lamps inside that window: from the ground the road
    // was lit for a dozen blocks and dark beyond. The map's steady lamps within
    // reach of the eye fill the rest, nearest first, up to a budget that keeps
    // the direct-light sampling honest (see RemixSetLightSampling).
    // They come and go with the camera move, weighted by the same blend as the sky
    // (skyBlend_: 0 -> 1 as the eye comes down from the classic view, 1 -> 0 as it
    // goes back up), so V does not switch a hundred lights on or off in one frame;
    // on the way back they now fade over the move rather than vanishing at the key
    // press. skyBlend_ is 0 whenever the classic view is settled, so the classic
    // view's light set is unchanged (REMIX-3D-PARITY).
    // GTA2DX9_FAR_LAMP_FADE=0 puts back the old switch (all at once, only while a 3D
    // view is the current one), for a before/after run.
    static int farFade = -1;
    if (farFade < 0) { char buf[8] = {}; farFade = GetEnvironmentVariableA("GTA2DX9_FAR_LAMP_FADE", buf, sizeof buf) && buf[0] == '0' ? 0 : 1; }
    if (farFade ? (worldUploaded_ && skyBlend_ > 0.001f) : (g_viewActive && CurrentViewMode() != ViewMode::Classic)) {
        const gta2::Vec3& eye = camera_.Position();
        const float e[3] = {eye.x, eye.y, eye.z};
        LightsSubmitMapLampsNear(e, kFarLampRadius, kFarLampCap, farFade ? skyBlend_ : 1.0f);
    }

    // The game lists this frame's lights during its own world pass, which runs
    // between gbh_BeginScene and the gbh_EndScene that brought us here - so by
    // now the list is complete and can be matched against what Remix already has.
    // Timed, for the benchmark: this is where every CreateLight crosses the bridge.
    LARGE_INTEGER lightTimer[4] = {};
    LARGE_INTEGER skyStamp = {};
    QueryPerformanceCounter(&lightTimer[0]);
    LightsReconcile();
    QueryPerformanceCounter(&lightTimer[1]);
    stamp[1] = lightTimer[1];

    FrameLogStage(kFlPre);   // FIX-PERF-4: draws per stage (frame log only)
    if (renderer_.BeginFrame()) {
        // The street views' sky, and the fog and sun that go with it; nothing
        // in the classic view.
        DrawSkyAndShading();
        QueryPerformanceCounter(&skyStamp);
        FrameLogStage(kFlSky);
        // Photo-material tiles only while the street presentation shows (always classic
        // when the classic view is settled): classic keeps the plain HD set unchanged.
        // During a move the ground's material cross-fades from one set to the other on
        // the same geometry (StreetPresentationMix), and the street-only fill comes and
        // goes with the presentation (FIX-SMOOTH-SWITCH; it switched at the V press before).
        {
            const bool street = worldUploaded_ && g_presentStreet;
            // The tile set switch (plain HD set in classic, photo/road set in the street views),
            // logged with its frame so a classic A/B can tell a move's tail from the settled view.
            static int lastStreet = -1;
            if (static_cast<int>(street) != lastStreet) {
                Log("view: tile set %s (frame %d, sky blend %.4f, material mix %.3f)", street ? "street (photo/road)" : "classic (plain HD)",
                    frameCount_, skyBlend_, g_presentMix);
                lastStreet = street ? 1 : 0;
            }
            renderer_.SetStreetView(street, worldUploaded_ ? g_presentMix : 0.0f, worldUploaded_ ? g_presentRoadMix : 0.0f);
            // FIX-TRANSITION-ART: the map's street lights near the lens fade while the camera moves.
            const PlayerState& hero = g_viewPlayer;
            renderer_.SetMoveOccluders(worldUploaded_ && g_viewMoving && hero.valid,
                                       gta2::Vec3{hero.x, hero.z, static_cast<float>(gta2::kMapHeight) - hero.y});
            // DISTRICTS-POC: the facade kit fades in with the street extras over the move from the classic
            // view (and out on the way back); [devtools] district_kit_show=0 hides it live (A/B frames).
            static int kitShow = 1;
            static uint32_t kitPolls = 0;
            if (CarBodiesDevIni()[0] && (kitPolls++ % 30u) == 0) {
                const int v = GetPrivateProfileIntA("devtools", "district_kit_show", 1, CarBodiesDevIni());
                if (v != kitShow) Log("devtools: district_kit_show %d", v);
                kitShow = v;
            }
            renderer_.SetKitPresentation(worldUploaded_ ? g_presentExtras : 0.0f, kitShow != 0);
            if (renderer_.KitStreaming()) {
                // resident chunks, triangles and buffer memory every 2 s; the address space every 10 s (DISTRICTS pilot)
                static uint32_t kitLogFrame = 0;
                if ((++kitLogFrame % 60u) == 0) {
                    const gta2::KitStreamStats s = renderer_.KitStreamStatus();
                    Log("districts stream: resident %d chunks (LOD0 %d, LOD1 %d, fading %d), %d triangles, %u KB buffers; created %d, released %d",
                        s.resident, s.lod0, s.lod1, s.fading, s.triangles, static_cast<unsigned>(s.gpuBytes / 1024), s.created, s.released);
                    if ((kitLogFrame % 300u) == 0) MemStatsLog("districts stream", 1);
                }
            }
        }
        {
            // FIX-WORLD-16 qav59: first person clips the sparse lattices (pylon girders) nearer than 0.35
            // block ahead of the eye (Renderer::SetSeeThroughNearClip). [devtools] lattice_clip=<hundredths
            // of a block>, 0 = off, re-read once a second, for a same-spot A/B.
            static int clipCm = 35;
            static uint32_t polls = 0;
            if (CarBodiesDevIni()[0] && (polls++ % 30u) == 0) {
                const int v = GetPrivateProfileIntA("devtools", "lattice_clip", 35, CarBodiesDevIni());
                if (v != clipCm) Log("devtools: lattice_clip %d (hundredths of a block)", v);
                clipCm = v;
            }
            const bool fp = worldUploaded_ && g_presentStreet && CurrentViewMode() == ViewMode::FirstPerson;
            // FIX-CAMERA-20 (qaexp52: driving under the ste Army Base rail truss the chase lens stood inside its steel lattice
            // for ~1.3 s, the truck a red smear behind the girders): in third person the same clip stands between the lens and
            // him, so every sparse lattice face (sides and decks) nearer the lens than him less a margin (0.45 on foot, 1.2 at
            // the wheel: the car's body) is not drawn; the lattice behind him and beside the picture's far part stays.
            // [camera] chase_lattice_clip=0 or GTA2DX9_CAM_LATTICE_CLIP=0: off (A/B). Plain renderer only (Remix: no clip planes).
            float chaseClip = 0.0f;
            const PlayerState& lp = g_viewPlayer;
            if (worldUploaded_ && g_presentStreet && CurrentViewMode() == ViewMode::ThirdPerson && transitionT_ >= 1.0f && lp.valid && clipCm > 0 &&
                CameraLatticeClipOn()) {
                const gta2::Mat4 view = camera_.ViewMatrix();
                const gta2::Vec3 e = camera_.Position();
                const gta2::Vec3 h{lp.x, lp.z + 0.4f, static_cast<float>(gta2::kMapHeight) - lp.y};
                const float depth = (h.x - e.x) * view.m[0][2] + (h.y - e.y) * view.m[1][2] + (h.z - e.z) * view.m[2][2];
                const float ahead = depth - (lp.inVehicle ? 1.2f : 0.45f);
                // at most a block from the lens: a lattice there fills the frame; further out it is part of the picture (a balcony's
                // railing in the foreground of the vreg cityinfo_chase pose went with a deeper clip)
                if (ahead > 0.3f) chaseClip = (std::min)(ahead, 1.0f);
                static int every = 0, logOn = -1;
                if (logOn < 0) { char b[8] = {}; logOn = GetEnvironmentVariableA("GTA2DX9_LOG_CAMERA", b, sizeof b) && atoi(b) ? 1 : 0; }
                if (chaseClip > 0.0f && logOn && (++every % 30) == 1)
                    Log("view: chase lattice clip %.2f ahead of the lens (him at %.2f)", chaseClip, depth);
            }
            renderer_.SetSeeThroughNearClip(fp ? static_cast<float>(clipCm) * 0.01f : chaseClip, chaseClip > 0.0f);
        }
        {
            // FIX-WORLD-17: [devtools] window_glow=0/1 overrides [renderer] window_glow live (re-read once a
            // second; -1, the default, leaves the ini's value): the night-glow mislabel discriminator (a facade
            // box on non-glass art) as a same-spot A/B in one session.
            static int glowDev = -1;
            static uint32_t glowPolls = 0;
            if (CarBodiesDevIni()[0] && (glowPolls++ % 30u) == 0) {
                const int v = GetPrivateProfileIntA("devtools", "window_glow", -1, CarBodiesDevIni());
                if (v != glowDev) {
                    const bool on = v < 0 ? GetPrivateProfileIntA("renderer", "window_glow", 1, CarBodiesDevIni()) != 0 : v != 0;
                    gta2::SetWindowGlow(on);
                    Log("devtools: window_glow %d (glow %s)", v, on ? "on" : "off");
                    glowDev = v;
                }
            }
        }
        {
            // FIX-PERF-9: [renderer] world_view_cull (default 1; GTA2DX9_WORLD_VIEW_CULL=0|1 overrides it), live
            // [devtools] world_view_cull=0|1 (-1: the ini's) for a same-pose A/B; re-read once a second.
            static int iniCull = -2, devCull = -1;
            static uint32_t cullPolls = 0;
            if (iniCull == -2) {
                char b[8] = {};
                iniCull = GetEnvironmentVariableA("GTA2DX9_WORLD_VIEW_CULL", b, sizeof b) ? atoi(b)
                          : CarBodiesDevIni()[0] ? GetPrivateProfileIntA("renderer", "world_view_cull", 1, CarBodiesDevIni()) : 1;
                Log("world view cull: %s (FIX-PERF-9)", iniCull ? "on" : "off");
            }
            if (CarBodiesDevIni()[0] && (cullPolls++ % 30u) == 0) {
                const int v = GetPrivateProfileIntA("devtools", "world_view_cull", -1, CarBodiesDevIni());
                if (v != devCull) Log("devtools: world_view_cull %d", v);
                devCull = v;
            }
            renderer_.SetWorldViewCull(devCull >= 0 ? devCull != 0 : iniCull != 0);
        }
        // WEATHER-V2: rain leaves covered places out (a lid of a real ground type above the point).
        g_coverMap = map_.Empty() ? nullptr : &map_;
        gta2::SetWeatherCover([](float x, float y, float z) -> bool {
            const gta2::Map* m = g_coverMap;
            if (!m) return false;
            const int cx = static_cast<int>(std::floor(x)), my = gta2::kMapHeight - 1 - static_cast<int>(std::floor(z));
            if (cx < 0 || cx >= gta2::kMapWidth || my < 0 || my >= gta2::kMapHeight) return false;
            const gta2::Column& c = m->ColumnAt(cx, my);
            for (int i = static_cast<int>(c.blocks.size()) - 1; i >= 0; --i) {
                const float top = static_cast<float>(c.offset + i + 1);
                if (top <= y + 0.05f) break;
                if (c.blocks[i] >= m->BlockCount()) continue;
                const gta2::Block& b = m->BlockAt(c.blocks[i]);
                if (b.lid && b.GroundType() != 0) return true;
            }
            return false;
        });
        renderer_.DrawWorld(camera_);
        // FIX-OCCLUSION: should the eye still be in a block, the block is closed round it
        // (back sides of the faces near the eye, depth-hidden from outside). Street views only,
        // never under Remix (its own geometry rules) nor in the classic view.
        if (worldUploaded_ && g_presentStreet && !renderer_.IsRemixDevice() &&
            renderer_.Device()) {
            DWORD cull = D3DCULL_CCW;
            renderer_.Device()->GetRenderState(D3DRS_CULLMODE, &cull);
            eyecol::DrawInteriorCaps(renderer_.Device(), camera_.Position(), cull);
        }
        renderer_.WarmTileTextures(CurrentViewMode() == ViewMode::Classic ? 24 : 6);   // nothing once every tile has been drawn with
        QueryPerformanceCounter(&stamp[2]);
        FrameLogStage(kFlWorld);
        // Sprites and the captured block shapes are real world geometry, so they
        // are depth tested against the static mesh rather than painted over it.
        live_.Draw(renderer_.Device(), camera_, renderer_.Width(), renderer_.Height());
        // WEATHER-V2: the wet ground under Remix (API instances; nothing on the plain renderer
        // or in the classic view, the layer's alpha follows the street mix).
        if (renderer_.IsRemixDevice() && worldUploaded_ && !map_.Empty()) {
            const auto eye = camera_.Position();
            const gta2::Mat4 wv = camera_.ViewMatrix();
            const float fwd[3] = {wv.m[0][2], wv.m[1][2], wv.m[2][2]};
            RemixWetFrame(map_, eye.x, eye.y, eye.z, g_presentStreet ? g_presentMix : 0.0f, fwd);
            renderer_.SetRemixWeatherFrame(camera_, g_presentStreet ? g_presentMix : 0.0f);
            // C: the stepped wet materials. The road/pavement lid tiles once per map; the level from the
            // wetness with hysteresis ([devtools] wx_wet_level forces one).
            static int wetLevel = 0;
            const float wet = gta2::WeatherNow().active ? gta2::WeatherNow().wet : 0.0f;
            const float up[3] = {0.25f, 0.55f, 0.85f};
            while (wetLevel < 3 && wet > up[wetLevel] + 0.03f) ++wetLevel;
            while (wetLevel > 0 && wet < up[wetLevel - 1] - 0.03f) --wetLevel;
            static int forced = -1, wetPolls = 0;
            if ((wetPolls++ % 30) == 0) forced = GetPrivateProfileIntA("devtools", "wx_wet_level", -1, CarBodiesDevIni());
            const int level = g_presentStreet ? (forced >= 0 ? forced : wetLevel) : 0;
            if (level != renderer_.WetLevel()) Log("weather: Remix wet material level %d (wetness %.2f)", level, wet);
            renderer_.SetWetLevel(level);
            SetCarWetLevel(level);
        }
        renderer_.EndWorldShading();
        // LIGHTING-V1: the plain classic view takes the hour too (the street views and the Remix classic view already
        // do): graded here, after the world and its sprites and before the 2D layer, so the HUD stays as drawn.
        TimeOfDaySetClassicWeight(1.0f - skyBlend_);   // LIGHTING-CLASSIC: the Remix classic exposure bias follows the move
        // Through the camera move too, weighted by how much of the picture is the classic look (1 - skyBlend_): the street
        // views' own night shading fades out toward the classic frame's look as the camera comes down (skyBlend_ -> 0), so
        // without the grade the last frames of a move back to the classic view showed the daytime picture (lt_cl9: ~0.6 s).
        if (skyBlend_ < 1.0f && worldUploaded_ && !renderer_.IsRemixDevice() && gta2::SkyConfig().followClock)
            ApplyClassicNight(1.0f - skyBlend_);
        QueryPerformanceCounter(&stamp[3]);
        // The 2D stream goes into a layer that is kept between frames, because
        // GTA2's menu only redraws what changed and clears the screen just when
        // it wants a repaint. In a level that reasoning does not apply - the HUD
        // is redrawn every frame and the world under it moves - so the layer is
        // cleared every frame there, which is what it always did.
        if (renderer_.BeginUiLayer(worldUploaded_)) {
            // WEATHER-V2: rain on the lens in first person (under the HUD); nothing in the other views.
            renderer_.DrawScreenRain(g_presentStreet ? g_presentMix : 0.0f);
            renderer_.DrawLensDrops(g_presentStreet && CurrentViewMode() == ViewMode::FirstPerson ? g_presentMix : 0.0f);
            overlay_.Flush(renderer_.Device(), renderer_.Width(), renderer_.Height());
            renderer_.EndUiLayer();
        } else {
            // Straight onto the back buffer, so these draws are the frame's UI
            // themselves. See Renderer::MarkDrawsAsScreenUi.
            renderer_.MarkDrawsAsScreenUi();
            overlay_.Flush(renderer_.Device(), renderer_.Width(), renderer_.Height());
        }
        // CITYMAP-1: the map's keys and the route's progress; the street views' ground chevrons under the HUD
        CityMapUpdate(renderer_.Device(), renderer_.Width(), renderer_.Height(), window_, worldUploaded_);
        CityMapDrawWorld(renderer_.Device(), renderer_.Width(), renderer_.Height());
        Hud3dHoldForSwitch(dissolveActive_);   // the kept classic frame carries the game's HUD (pm7)
        Hud3dRender(renderer_.Device(), renderer_.Width(), renderer_.Height(), map_, worldUploaded_);   // MODERN HUD (hud3d.cpp)
        // The view switch out of the classic view (BEV-PURITY). The street view's renderer
        // draws its own figures, photo tiles, sky and HUD from the very first frame of the
        // move, while the camera is still at the classic camera, so V changed the top-down
        // picture at once (the player's dark sprite became the lighter 3D figure seen from
        // above). Instead the move opens on the last classic frame itself, copied bit for bit,
        // and that frame dissolves into the street view over the first switch_dissolve_percent
        // of the move, as the eye starts to come down. The settled classic view is untouched:
        // it is only copied (KeepFrame), never drawn over.
        if (dissolveActive_) {
            if (CurrentViewMode() == ViewMode::Classic || !transitionFromClassic_ || transitionT_ >= 1.0f) {
                dissolveActive_ = false;
            } else {
                if (dissolveT0_ < 0.0f) dissolveT0_ = transitionT_;
                const float span = (std::max)(ViewModes().switchDissolve * (1.0f - dissolveT0_), 0.01f);
                const float u = (std::min)(1.0f, (std::max)(0.0f, (transitionT_ - dissolveT0_) / span));
                const float alpha = 1.0f - u * u * (3.0f - 2.0f * u);
                if (alpha <= 0.0f) dissolveActive_ = false;
                else renderer_.DrawKeptFrame(alpha);
                static int verify = -1;
                if (verify < 0) { char buf[8] = {}; verify = GetEnvironmentVariableA("GTA2DX9_DISSOLVE_VERIFY", buf, sizeof buf) && buf[0] == '1'; }
                if (verify && dissolveT0_ == transitionT_)
                    Log("view dissolve: first frame of the move vs the last classic frame: %ld pixels differ (alpha %.3f)",
                        renderer_.KeptFrameDifference(), alpha);
            }
        }
        // FIX-CAMERA-19 (cam18-third-pocket residual: the boom's one-frame cut round him in the wil pockets): the last
        // third-person frame (kept below) dissolves into the cut's first frame over [camera] cut_dissolve (0.3 s: 9 frames), so the
        // cut reads as a camera blend, not a jump. Plain renderer only (Remix keeps no frame copy: the hard cut).
        {
            const uint32_t serial = ChaseCutSerial();
            const float span = ChaseCutDissolveSeconds();
            if (serial != cutSerialSeen_) {
                cutSerialSeen_ = serial;
                if (span > 0.0f && !dissolveActive_ && renderer_.HasKeptFrame() && keptThirdAt_ == frameCount_ - 1 &&
                    (CurrentViewMode() == ViewMode::ThirdPerson || CurrentViewMode() == ViewMode::FirstPerson)) {
                    cutDissolveAt_ = 0.0;   // progress, seconds
                    cutDissolveLast_ = -1.0;
                    Log("view: the %s dissolves from the frame before over %.2f s", CurrentViewMode() == ViewMode::FirstPerson ? "seat step" : "boom's cut", span);
                }
            }
            if (cutDissolveAt_ >= 0.0) {
                // the clock, each frame's step capped at 1/30 s: a hitch at the cut (cam19_pk1: 130 ms) spent most of a
                // plainly clocked dissolve before its first frame was shown; counted in frames it ran in 0.1 s at 90 fps
                LARGE_INTEGER c, f;
                QueryPerformanceCounter(&c); QueryPerformanceFrequency(&f);
                const double t = static_cast<double>(c.QuadPart) / static_cast<double>(f.QuadPart);
                if (cutDissolveLast_ >= 0.0) cutDissolveAt_ += (std::min)(t - cutDissolveLast_, 1.0 / 30.0);
                cutDissolveLast_ = t;
                const float u = span > 0.0f ? static_cast<float>(cutDissolveAt_ / span) : 1.0f;
                if (u >= 1.0f || CurrentViewMode() == ViewMode::Classic || dissolveActive_) cutDissolveAt_ = -1.0;
                else {
                    const float k = (std::max)(0.0f, u);
                    renderer_.DrawKeptFrame(1.0f - k * k * (3.0f - 2.0f * k));
                }
            }
        }
        CityMapDrawOverlay(renderer_.Device(), renderer_.Width(), renderer_.Height());   // CITYMAP-1: the full map, when open
        // ImGui issues ordinary D3D9 draws, so it belongs inside the scene.
        DebugMenuRender();
        // Remix clears its per-frame light list every frame, so a light is in the
        // scene exactly when it is drawn here. Last thing before the flip.
        QueryPerformanceCounter(&lightTimer[2]);
        stamp[4] = lightTimer[2];
        FrameLogStage(kFlUi);   // FIX-PERF-4: the 2D layer, dissolve and menu
        LightsDraw();
        QueryPerformanceCounter(&lightTimer[3]);
        stamp[5] = lightTimer[3];
        // A settled classic frame is kept for the dissolve above (a copy; this frame is
        // presented exactly as drawn). Any other frame drops the copy.
        if (worldUploaded_ && ViewModes().switchDissolve > 0.001f && CurrentViewMode() == ViewMode::Classic && !g_viewActive &&
            transitionT_ >= 1.0f && skyBlend_ <= 0.0f && !DebugMenuVisible()) {
            renderer_.KeepFrame();
            keptClassicAt_ = frameCount_;
        } else if (worldUploaded_ && ChaseCutDissolveSeconds() > 0.0f && CurrentViewMode() != ViewMode::Classic && g_viewActive &&
                   transitionT_ >= 1.0f && !dissolveActive_ && cutDissolveAt_ < 0.0 && !DebugMenuVisible()) {
            // FIX-CAMERA-19: every settled street-view frame is kept (a copy) for the dissolve over a boom cut or the seat step
            renderer_.KeepFrame();
            keptThirdAt_ = frameCount_;
        } else if (renderer_.HasKeptFrame() && !dissolveActive_ && cutDissolveAt_ < 0.0) {
            renderer_.DropKeptFrame();
        }
        // FIX-PERF-VSWITCH: the street views' GL programs, built while the classic view is up
        // (GhostStreetFrame). Once a level, on its second frame.
        if (ghostAt_ < 0 && worldUploaded_ && CurrentViewMode() == ViewMode::Classic && !g_viewActive && skyBlend_ <= 0.0f &&
            transitionT_ >= 1.0f && !renderer_.IsRemixDevice()) {
            static int ghostOff = -1;
            if (ghostOff < 0) { char buf[8] = {}; ghostOff = GetEnvironmentVariableA("GTA2DX9_GHOST_FRAME", buf, sizeof buf) && buf[0] == '0' ? 1 : 0; }
            if (ghostOff) ghostAt_ = frameCount_;
            else if (++ghostWait_ >= 2) {   // inside the level's own loading stall, not in play
                GhostStreetFrame();
                ghostAt_ = frameCount_;
                // GTA2DX9_GHOST_VERIFY=1: this frame's back buffer against its own copy taken just before
                // the street frame (KeepFrame above): the classic picture must be untouched.
                char buf[8] = {};
                if (GetEnvironmentVariableA("GTA2DX9_GHOST_VERIFY", buf, sizeof buf) && buf[0] == '1')
                    Log("view: street frame unseen: %ld pixels of the classic frame differ after it (kept copy %s)",
                        renderer_.HasKeptFrame() && keptClassicAt_ == frameCount_ ? renderer_.KeptFrameDifference() : -1L,
                        renderer_.HasKeptFrame() && keptClassicAt_ == frameCount_ ? "this frame" : "missing");
            }
        }
        renderer_.EndFrame();
        QueryPerformanceCounter(&stamp[6]);
    }

    ++frameCount_;
    if ((frameCount_ & 0xFF) == 0) {
        // What conforming actually did, which is also the answer to the one
        // question the design could not settle by reading the game: whether GTA2
        // gives a sprite the true height of the ramp under it or the top of the
        // block. A street full of traffic with maxgap near zero says it gives the
        // true height and the conform is doing its job; a persistent gap the size
        // of a ramp step says it does not, and the tilt fade is quietly switching
        // itself off on every slope in the city.
        const LiveGeometry::Conform& c = live_.ConformCounts();
        // FIX-SPRITES-1 (B2): airborne/maxgap are cars and pedestrians over the floor they rest on;
        // onstep = on the upper floor of a step; raised = objects the game holds up (lamp heads).
        Log("frame %d: %d sprite quads | conform grounded=%d airborne=%d noground=%d capped=%d "
            "straddled=%d maxgap=%.3f maxresidual=%.3f | onstep=%d raised=%d (max %.2f)",
            frameCount_, live_.SpriteQuads(), c.grounded, c.airborne, c.noGround, c.capped,
            c.straddled, c.maxGap, c.maxResidual, c.onStep, c.raised, c.raisedMaxGap);
    }
    // Anything here is a sprite the player should have seen and did not, or a
    // texture built from artwork that was not ready.
    if ((frameCount_ & 0x3F) == 0) {
        const LiveGeometry::Drops& drops = live_.DropCounts();
        // A sprite the game asked for, that we took, that never reached the device is the
        // flicker itself: the 'unplaced' fates (FIX-SPRITES-1; accepted != drawn said nothing,
        // since a model, a figure or a batch stands in for most of them). Quiet windows print
        // nothing and still start a new window.
        if (!drops.Quiet() || !g_trouble.Quiet() || drops.unplacedPed || drops.unplacedCar || drops.unplacedOther) {
            // FIX-SPRITES-1: 'drawn' counts the sprite pass's device draws (a batch of puffs or a
            // figure's quad is one), not sprites; where every accepted sprite went is the fates part
            // (received = model + own + ghost + lamp + queued + unplaced; figures are of the queued).
            // 'shadows' are the game's drop shadows, dropped on purpose (they were all of the old
            // wrongarray); 'wrongarray' is now any other non-array draw, a real loss.
            Log("sprite trouble @%d: accepted=%d drawn=%d | dropped expand=%d wrongarray=%d "
                "nonfinite=%d outside=%d degenerate=%d notexture=%d | textures built=%d "
                "nopalette=%d blackpalette=%d pixelsmoved=%d whilelocked=%d lockfail=%d | shadows=%d | "
                "fates received=%d model=%d own=%d ghost=%d lamp=%d queued=%d (figure=%d) unplaced ped=%d car=%d other=%d",
                frameCount_, drops.accepted, drops.drawn, drops.expandFlag, drops.notTheSpriteArray,
                drops.notFinite, drops.outOfWorld, drops.degenerate, drops.noTexture,
                g_trouble.built, g_trouble.paletteMissing, g_trouble.paletteAllBlack,
                g_trouble.pixelsMovedSilently, g_trouble.builtWhileLocked, g_trouble.lockFailed,
                drops.gameShadow, drops.received, drops.fateModel, drops.fateOwn, drops.fateGhost,
                drops.fateLamp, drops.fateQueued, drops.fateFigure, drops.unplacedPed, drops.unplacedCar,
                drops.unplacedOther);
        } else if ((frameCount_ & 0xFF) == 0) {
            // FIX-SPRITES-1: the same window's accounting when nothing went wrong, once per 256
            // frames: every accepted sprite's fate, the game's drop shadows left out on purpose.
            Log("sprite fates @%d (64 frames): accepted=%d shadows=%d | received=%d model=%d own=%d ghost=%d "
                "lamp=%d queued=%d (figure=%d) unplaced=0 | device draws=%d",
                frameCount_, drops.accepted, drops.gameShadow, drops.received, drops.fateModel, drops.fateOwn,
                drops.fateGhost, drops.fateLamp, drops.fateQueued, drops.fateFigure, drops.drawn);
        }
        live_.ClearDropCounts();
        g_trouble = TextureTrouble{};
    }
    // The game's own view rectangle against the frame we draw. With the view
    // patch in, the two widths agree; if cars ever pop in the margins again
    // this line says at once whether gta2.exe is still reasoning 4:3.
    if ((frameCount_ & 0xFF) == 0) {
        game::ViewExtent view;
        if (game::VisibleExtent(&view) && renderer_.Height() > 0) {
            const float aspect =
                static_cast<float>(renderer_.Width()) / static_cast<float>(renderer_.Height());
            Log("view @%d: game %.2f x %.2f tiles | frame %.2f x %.2f | %s", frameCount_,
                view.Width(), view.Height(), visibleTiles_ * aspect, visibleTiles_,
                SpawnOffscreenActive() ? "gta2.exe patched" : "gta2.exe as shipped");
        }
    }

    if ((frameCount_ & 0x3F) == 0) DumpCameraStruct();

    // Last thing in the frame, after the flip: GTA2's own pacer is a checkbox
    // between 30 fps and none at all, so the number lives here instead. See
    // frame_limiter.h for what a cap above 30 does to the game's speed.
    FrameLimitWait();

    {
        // Stage times in ms. A stage that did not run (no device this frame) reads zero.
        QueryPerformanceCounter(&stamp[7]);
        double ms[kStages] = {};
        FrameTimer& t = g_frameTimer;
        if (t.last.QuadPart) ms[0] = QpcMs(t.last, stamp[0]);
        if (stamp[1].QuadPart) ms[1] = QpcMs(stamp[0], stamp[1]);
        if (stamp[2].QuadPart) ms[2] = QpcMs(stamp[1], stamp[2]);
        if (stamp[3].QuadPart) ms[3] = QpcMs(stamp[2], stamp[3]);
        if (stamp[4].QuadPart) ms[4] = QpcMs(stamp[3], stamp[4]);
        if (stamp[5].QuadPart) ms[5] = QpcMs(stamp[4], stamp[5]);
        if (stamp[6].QuadPart) ms[6] = QpcMs(stamp[5], stamp[6]);
        ms[7] = QpcMs(stamp[6].QuadPart ? stamp[6] : stamp[1], stamp[7]);
        // Our own part of the frame, without the wait that holds it to the cap.
        const double work = ms[1] + ms[2] + ms[3] + ms[4] + ms[5] + ms[6];
        const double whole = t.last.QuadPart ? QpcMs(t.last, stamp[7]) : 0.0;
        for (int i = 0; i < kStages; ++i) {
            t.worst[i] = (std::max)(t.worst[i], ms[i]);
            t.sum[i] += ms[i];
        }
        ++t.frames;
        // Two budgets: a slow present (the driver, the host) is common and
        // would use up the log; an expensive sprites stage is ours to explain.
        // FIX-PERF-2: "hitch @N: frame" is written only for a frame that missed its
        // budget (work or the game's step over kHitchMs, or the whole frame over 50 ms),
        // once a frame, so counting "hitch @" counts frames a viewer could see
        // (qa_lib's CHECK, sweep_detect, run_stats). An expensive sprites stage inside
        // a frame that still made its budget is "slow sprites @N" instead, and the
        // breakdown lines of either are "hitch detail @N" / "slow sprites detail @N".
        const bool ours = ms[3] > 12.0;
        const bool over = work > kHitchMs || ms[0] > kHitchMs || whole > 50.0;
        if ((over || ours) && (ours ? t.hitchLoggedOurs < 300 : t.hitchLogged < 400)) {
            if (ours) ++t.hitchLoggedOurs; else ++t.hitchLogged;
            const char* what = over ? "hitch" : "slow sprites";
            Log("%s @%d: frame %.1f ms | game %.1f lights %.1f world %.1f sprites %.1f ui %.1f "
                "lightsdraw %.1f present %.1f wait %.1f",
                what, frameCount_, whole, ms[0], ms[1], ms[2], ms[3], ms[4], ms[5], ms[6], ms[7]);
            if (ms[3] > 12.0) {
                const double* d = LiveDrawStageMs();
                Log("%s detail @%d: sprites stage was setup %.1f loop %.1f skidmemory %.1f issue %.1f cars %.1f props %.1f "
                    "objects %.1f peds %.1f rest %.1f",
                    what, frameCount_, d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8]);
                const double* m = ModelDrawStats();
                Log("%s detail @%d: models: %.0f draws (%.0f skinned) %.1f ms, of which posing %.1f, buffer fills %.1f",
                    what, frameCount_, m[3], m[4], m[2], m[0], m[1]);
                const double* c = CarBodiesStats();
                Log("%s detail @%d: car bodies: measured %.0f (%.1f ms) built %.0f (%.1f ms) model draws %.0f (%.1f ms) sprite bodies %.0f (%.1f ms)",
                    what, frameCount_, c[4], c[0], c[5], c[1], c[6], c[2], c[7], c[3]);
                const double* parts = nullptr;
                const char* const* partNames = nullptr;
                const int nParts = CarBodiesPartStats(&parts, &partNames);
                char line[512];
                int len = 0;
                for (int i = 0; i < nParts && len < 400; ++i)
                    if (parts[i] >= 1.0) len += snprintf(line + len, sizeof(line) - static_cast<size_t>(len), " %s %.1f", partNames[i], parts[i]);
                if (len > 0) Log("%s detail @%d: car parts (ms):%s", what, frameCount_, line);
            }
        }
        if (FrameLogEnabled()) {
            // GTA2DX9_FRAME_LOG: the same stages, one line a frame (frame_log.h).
            FrameLogRecord r = {};
            r.whole = whole;
            r.pre = t.last.QuadPart ? QpcMs(entryStamp, stamp[0]) : 0.0;
            r.game = t.last.QuadPart ? QpcMs(t.last, entryStamp) : 0.0;
            r.lights = ms[1];
            r.preParts[0] = QpcMs(entryStamp, preStamp[1]);   // device, window, world load
            r.preParts[1] = QpcMs(preStamp[1], preStamp[2]);  // animated tiles
            r.preParts[2] = QpcMs(preStamp[2], preStamp[3]);  // input
            r.preParts[3] = QpcMs(preStamp[3], preStamp[4]);  // camera, player locator
            r.preParts[4] = QpcMs(preStamp[4], preStamp[5]);  // HUD size, Remix, F4 menu
            r.preParts[5] = QpcMs(preStamp[5], stamp[0]);     // time of day
            r.sky = skyStamp.QuadPart ? QpcMs(stamp[1], skyStamp) : 0.0;
            r.world = skyStamp.QuadPart && stamp[2].QuadPart ? QpcMs(skyStamp, stamp[2]) : ms[2];
            const double* d = LiveDrawStageMs();
            for (int i = 0; i < 9; ++i) r.sprites[i] = stamp[3].QuadPart ? d[i] : 0.0;
            r.ui = ms[4];
            r.lightsDraw = ms[5];
            r.present = ms[6];
            r.wait = ms[7];
            const double* m = ModelDrawStats();
            r.posing = m[0];
            r.fills = m[1];
            r.modelDraws = static_cast<int>(m[3]);
            r.skinned = static_cast<int>(m[4]);
            const double* c = CarBodiesStats();
            r.carMeasured = static_cast<int>(c[4]);
            r.carBuilt = static_cast<int>(c[5]);
            r.view = !g_viewActive ? 0 : (CurrentViewMode() == ViewMode::FirstPerson ? 2 : (CurrentViewMode() == ViewMode::Classic ? 0 : 1));
            r.driving = g_viewPlayer.valid && g_viewPlayer.inVehicle ? 1 : 0;
            r.px = g_viewPlayer.valid ? g_viewPlayer.x : 0.0f;
            r.py = g_viewPlayer.valid ? g_viewPlayer.y : 0.0f;
            r.pz = g_viewPlayer.valid ? g_viewPlayer.z : 0.0f;
            r.cx = camera_.Position().x;
            r.cy = camera_.Position().y;
            r.cz = camera_.Position().z;
            r.spriteQuads = live_.SpriteQuads();
            r.entryQpc = entryStamp.QuadPart;
            r.solver = g_solverMs;
            r.camLocate = g_camLocateMs;
            r.camProbes = g_camProbesMs;
            FrameLogEndFrame(static_cast<uint32_t>(frameCount_), r);
        }
        {
            // FIX-PERF-2: what the log costs the render thread (every Log() call, its
            // formatting and hand-off to the writer thread) and the scripted runners'
            // state lines (view: player / peds / cars: reading the game and building
            // the text), per frame, summarised with the frame times below.
            LogCost lc;
            LogCostTake(&lc);
            g_logCost.calls += lc.calls;
            g_logCost.bytes += lc.bytes;
            g_logCost.sum += lc.ms;
            g_logCost.worst = (std::max)(g_logCost.worst, lc.ms);
            g_logCost.linesSum += g_scriptLinesMs;
            g_logCost.linesWorst = (std::max)(g_logCost.linesWorst, g_scriptLinesMs);
            g_scriptLinesMs = 0.0;
        }
        if (t.frames >= 256) {
            Log("log cost, avg/worst ms a frame over %d frames | Log() %.3f/%.3f (%ld lines, %ld KB) "
                "state lines %.3f/%.3f",
                t.frames, g_logCost.sum / t.frames, g_logCost.worst, g_logCost.calls, g_logCost.bytes / 1024,
                g_logCost.linesSum / t.frames, g_logCost.linesWorst);
            g_logCost = LogCostSummary{};
            Log("frame times, avg/worst ms over %d frames | game %.1f/%.1f lights %.1f/%.1f world %.1f/%.1f "
                "sprites %.1f/%.1f ui %.1f/%.1f lightsdraw %.1f/%.1f present %.1f/%.1f wait %.1f/%.1f",
                t.frames, t.sum[0] / t.frames, t.worst[0], t.sum[1] / t.frames, t.worst[1],
                t.sum[2] / t.frames, t.worst[2], t.sum[3] / t.frames, t.worst[3], t.sum[4] / t.frames,
                t.worst[4], t.sum[5] / t.frames, t.worst[5], t.sum[6] / t.frames, t.worst[6],
                t.sum[7] / t.frames, t.worst[7]);
            for (int i = 0; i < kStages; ++i) t.worst[i] = t.sum[i] = 0.0;
            t.frames = 0;
        }
        QueryPerformanceCounter(&t.last);
    }

    if (LightBenchRunning()) {
        LARGE_INTEGER frequency;
        QueryPerformanceFrequency(&frequency);
        const double toMs = 1000.0 / static_cast<double>(frequency.QuadPart);
        LightBenchRecord(static_cast<double>(lightTimer[1].QuadPart - lightTimer[0].QuadPart) * toMs,
                         static_cast<double>(lightTimer[3].QuadPart - lightTimer[2].QuadPart) * toMs);
    }
}

}  // namespace gta2dx9
