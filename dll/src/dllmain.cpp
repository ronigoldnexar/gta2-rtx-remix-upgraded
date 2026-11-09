// gta2dx9.dll - in-process renderer for GTA2, loaded via the `rendername`
// registry value.
//
// Two modes, selected by gta2dx9.ini next to the game:
//   backend=3dfx.dll  mode=proxy     forward everything to the original renderer
//   mode=takeover                    own the device and draw the world ourselves
//
// Proxy is the default so a bad build can never leave the game unbootable.
//
// Every export is __stdcall: the originals end in `ret N`. The argument counts
// below come from those epilogues, and getting one wrong unbalances the stack.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <intrin.h>
#include <psapi.h>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cctype>
#include <cstdlib>
#include <cstring>

#include "debug_overlay.h"
#include "frame_limiter.h"
#include "game_access.h"
#include "gibs.h"
#include "density.h"
#include "hud_pass.h"
#include "intro_movie.h"
#include "live_geometry.h"
#include "car_glass.h"
#include "frame_log.h"
#include "log.h"
#include "remix_api.h"
#include "remix_lights.h"
#include "settings.h"
#include "synthetic_lights.h"
#include "texture_store.h"
#include "time_of_day.h"
#include "voice_over.h"
#include "audio3d.h"
#include "city_ai.h"
#include "cache_warmup.h"
#include "world_view.h"
#include "../../src/sky.h"
#include "view_modes.h"
#include "car_bodies.h"
#include "model_store.h"
#include "compat.h"

using gta2dx9::Log;

namespace {

enum class Mode { Proxy, Takeover };

Mode g_mode = Mode::Proxy;
HMODULE g_self = nullptr;
char g_backendName[MAX_PATH] = "3dfx.dll";
HMODULE g_backend = nullptr;
void* g_system = nullptr;
gta2dx9::WorldView g_world;
bool g_intro = gta2dx9::kDefaultIntro;

// gbh_GetGlobals hands the game a counter block; the original exposes polys and
// texture swaps drawn this frame.
struct Globals {
    int polygons = 0;
    int textureSwaps = 0;
    int spare[6] = {};
} g_globals;

void PathBesideGame(const char* leaf, char* out, size_t size) {
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(size));
    char* slash = strrchr(out, '\\');
    if (slash) strcpy(slash + 1, leaf);
    else strncpy(out, leaf, size - 1);
}

#define SLOT(name) void* g_p_##name = nullptr;
SLOT(gbh_InitDLL) SLOT(gbh_CloseDLL) SLOT(gbh_Init) SLOT(gbh_DrawTile) SLOT(gbh_DrawTilePart)
SLOT(gbh_DrawQuad) SLOT(gbh_DrawQuadClipped) SLOT(gbh_DrawTriangle) SLOT(gbh_Plot)
SLOT(gbh_SetWindow) SLOT(gbh_PrintBitmap) SLOT(gbh_SetColourDepth) SLOT(gbh_GetGlobals)
SLOT(gbh_ConvertColour) SLOT(gbh_RegisterTexture) SLOT(gbh_BeginScene) SLOT(gbh_EndScene)
SLOT(gbh_BeginLevel) SLOT(gbh_EndLevel) SLOT(ConvertColourBank) SLOT(DrawLine)
SLOT(MakeScreenTable) SLOT(SetShadeTableA) SLOT(gbh_UnlockTexture) SLOT(gbh_RegisterPalette)
SLOT(gbh_FreePalette) SLOT(gbh_FreeTexture) SLOT(gbh_AssignPalette) SLOT(gbh_LockTexture)
SLOT(gbh_GetUsedCache) SLOT(gbh_SetCamera) SLOT(gbh_ResetLights) SLOT(gbh_AddLight)
SLOT(gbh_SetAmbient) SLOT(gbh_InitImageTable) SLOT(gbh_FreeImageTable) SLOT(gbh_LoadImage)
SLOT(gbh_BlitImage) SLOT(gbh_BlitBuffer) SLOT(gbh_DrawFlatRect) SLOT(gbh_CloseScreen)
SLOT(gbh_Convert16BitGraphic)
#undef SLOT

struct Binding { const char* name; void** slot; };

const Binding kBindings[] = {
#define BIND(name) {#name, &g_p_##name},
    BIND(gbh_InitDLL) BIND(gbh_CloseDLL) BIND(gbh_Init) BIND(gbh_DrawTile) BIND(gbh_DrawTilePart)
    BIND(gbh_DrawQuad) BIND(gbh_DrawQuadClipped) BIND(gbh_DrawTriangle) BIND(gbh_Plot)
    BIND(gbh_SetWindow) BIND(gbh_PrintBitmap) BIND(gbh_SetColourDepth) BIND(gbh_GetGlobals)
    BIND(gbh_ConvertColour) BIND(gbh_RegisterTexture) BIND(gbh_BeginScene) BIND(gbh_EndScene)
    BIND(gbh_BeginLevel) BIND(gbh_EndLevel) BIND(ConvertColourBank) BIND(DrawLine)
    BIND(MakeScreenTable) BIND(SetShadeTableA) BIND(gbh_UnlockTexture) BIND(gbh_RegisterPalette)
    BIND(gbh_FreePalette) BIND(gbh_FreeTexture) BIND(gbh_AssignPalette) BIND(gbh_LockTexture)
    BIND(gbh_GetUsedCache) BIND(gbh_SetCamera) BIND(gbh_ResetLights) BIND(gbh_AddLight)
    BIND(gbh_SetAmbient) BIND(gbh_InitImageTable) BIND(gbh_FreeImageTable) BIND(gbh_LoadImage)
    BIND(gbh_BlitImage) BIND(gbh_BlitBuffer) BIND(gbh_DrawFlatRect) BIND(gbh_CloseScreen)
    BIND(gbh_Convert16BitGraphic)
#undef BIND
};

// What the loader knows this DLL as. deploy.bat installs a second copy of it as
// d3ddll.dll, because the renderer list in "gta2 manager.exe" and in the game's
// own options screen is a hardcoded table of 3dfx.dll / d3ddll.dll / softdll.dll
// (strings at 0x39D08 in the manager) and can never be made to offer a fourth
// name. Claiming the Direct3D slot is what stops either of them silently
// swapping the renderer out the moment you go in to change the resolution.
const char* OwnModuleLeaf() {
    static char leaf[MAX_PATH] = "";
    if (!leaf[0]) {
        char path[MAX_PATH] = "";
        GetModuleFileNameA(g_self, path, sizeof(path));
        const char* slash = strrchr(path, '\\');
        strncpy(leaf, slash ? slash + 1 : path, sizeof(leaf) - 1);
    }
    return leaf;
}

void LoadConfig() {
    char ini[MAX_PATH];
    PathBesideGame("gta2dx9.ini", ini, sizeof(ini));

    // Proxy mode forwards to the original renderer. Which one that is depends on
    // the name we were loaded under: as d3ddll.dll the original D3D renderer has
    // been moved aside to d3ddll_orig.dll, and forwarding to "d3ddll.dll" would
    // just load us again.
    const bool wearingD3dName = _stricmp(OwnModuleLeaf(), "d3ddll.dll") == 0;
    GetPrivateProfileStringA("renderer", "backend", wearingD3dName ? "d3ddll_orig.dll" : "3dfx.dll",
                             g_backendName, sizeof(g_backendName), ini);
    if (_stricmp(g_backendName, OwnModuleLeaf()) == 0) {
        Log("backend '%s' is this DLL; using %s instead", g_backendName,
            wearingD3dName ? "d3ddll_orig.dll" : "3dfx.dll");
        strcpy(g_backendName, wearingD3dName ? "d3ddll_orig.dll" : "3dfx.dll");
    }
    char mode[32] = {};
    GetPrivateProfileStringA("renderer", "mode", "proxy", mode, sizeof(mode), ini);
    g_mode = _stricmp(mode, "takeover") == 0 ? Mode::Takeover : Mode::Proxy;

    // Tenths of a degree, because the ini API only reads integers.
    const int pitch = GetPrivateProfileIntA("camera", "pitch_tenths", -900, ini);
    const int fov = GetPrivateProfileIntA("camera", "fov_tenths", 150, ini);
    const bool gameTiles = GetPrivateProfileIntA("renderer", "use_game_tiles", 1, ini) != 0;
    const int ownWindow = GetPrivateProfileIntA("renderer", "own_window", 1, ini);
    g_world.Configure(pitch / 10.0f, fov / 10.0f, gameTiles,
                      static_cast<gta2dx9::PresentWindow>(ownWindow));

    // The view to start in and the key that cycles them. gta2dx9_settings.ini,
    // read after this, overrides both when the menu has saved them.
    {
        gta2dx9::ViewModeSettings& vm = gta2dx9::ViewModes();
        char modeName[32] = {};
        GetPrivateProfileStringA("camera", "mode", "classic", modeName, sizeof(modeName), ini);
        if (_stricmp(modeName, "third") == 0 || _stricmp(modeName, "1") == 0) {
            vm.mode = 1;
        } else if (_stricmp(modeName, "first") == 0 || _stricmp(modeName, "2") == 0) {
            vm.mode = 2;
        } else {
            vm.mode = 0;
        }
        char keyName[32] = {};
        GetPrivateProfileStringA("camera", "toggle_key", "V", keyName, sizeof(keyName), ini);
        if (strlen(keyName) == 1) {
            vm.toggleKey = toupper(static_cast<unsigned char>(keyName[0]));
        } else if ((keyName[0] == 'F' || keyName[0] == 'f') && isdigit(static_cast<unsigned char>(keyName[1]))) {
            const int n = atoi(keyName + 1);
            if (n >= 1 && n <= 24) vm.toggleKey = VK_F1 + n - 1;
        } else if (strncmp(keyName, "0x", 2) == 0 || strncmp(keyName, "0X", 2) == 0) {
            vm.toggleKey = static_cast<int>(strtol(keyName, nullptr, 16));
        } else if (isdigit(static_cast<unsigned char>(keyName[0]))) {
            vm.toggleKey = atoi(keyName);
        }
        if (vm.toggleKey <= 0 || vm.toggleKey >= 256) vm.toggleKey = 'V';
        // For a recording: switch by itself this many seconds into a level.
        vm.demoSwitchSeconds =
            static_cast<float>(GetPrivateProfileIntA("camera", "demo_switch_seconds", 0, ini));
        vm.demoSwitchTo = GetPrivateProfileIntA("camera", "demo_switch_to", 2, ini);
        // The feel of the street views; the F4 menu's saved settings override these.
        vm.mouseLook = GetPrivateProfileIntA("camera", "mouse_look", 1, ini) != 0;
        vm.turnSpeed = static_cast<float>(GetPrivateProfileIntA("camera", "turn_speed", 100, ini));
        vm.turnRateFoot = static_cast<float>(GetPrivateProfileIntA("camera", "turn_rate_foot", 120, ini));
        vm.turnRateCar = static_cast<float>(GetPrivateProfileIntA("camera", "turn_rate_car", 90, ini));
        vm.navMap = GetPrivateProfileIntA("camera", "nav_map", 1, ini) != 0;
        {
            const int d = GetPrivateProfileIntA("camera", "switch_dissolve_percent", 0, ini);
            vm.switchDissolve = static_cast<float>(d < 0 ? 0 : (d > 100 ? 100 : d)) / 100.0f;
        }
        vm.navTurnSign = GetPrivateProfileIntA("camera", "nav_turn_sign", 1, ini) < 0 ? -1 : 1;
        vm.fpTurnKeyRate = static_cast<float>(GetPrivateProfileIntA("camera", "first_turn_key_rate", 70, ini));
        vm.tpOrbitFollow = GetPrivateProfileIntA("camera", "orbit_follow", 0, ini) != 0;
        vm.carImpactShake = static_cast<float>(GetPrivateProfileIntA("camera", "car_impact_shake", 100, ini)) / 100.0f;
        vm.fpBodyRide = static_cast<float>(GetPrivateProfileIntA("camera", "first_body_ride", 100, ini)) / 100.0f;
        {
            // Soft follow on foot (seconds): follow_tau_walk 0 turns it off.
            auto iniFloat = [&](const char* key, float fallback) {
                char v[32] = {};
                GetPrivateProfileStringA("camera", key, "", v, sizeof(v), ini);
                return v[0] ? static_cast<float>(atof(v)) : fallback;
            };
            vm.tpFollowTauWalk = iniFloat("follow_tau_walk", 1.5f);
            vm.tpFollowTauRun = iniFloat("follow_tau_run", 1.0f);
            vm.tpFollowDelay = iniFloat("follow_delay", 0.4f);
        }
        vm.logKeys = GetPrivateProfileIntA("devtools", "log_keys", 0, ini) != 0;
        gta2dx9::CarBodiesSetWreckTest(GetPrivateProfileIntA("devtools", "wreck_models", 0, ini) != 0);
        gta2dx9::CarBodiesSetDevIni(ini);
        gta2dx9::PedRemapOverride(GetPrivateProfileIntA("devtools", "ped_remap_override", -1, ini));
        {
            char warpKey[32] = {};
            GetPrivateProfileStringA("devtools", "warp_key", "", warpKey, sizeof(warpKey), ini);
            vm.devWarpKey = 0;
            if (warpKey[0] == 'F' || warpKey[0] == 'f') vm.devWarpKey = VK_F1 + atoi(warpKey + 1) - 1;
            else if (warpKey[0]) vm.devWarpKey = atoi(warpKey);
            char sceneKey[32] = {}, sceneXy[64] = {};
            GetPrivateProfileStringA("devtools", "scene_key", "", sceneKey, sizeof(sceneKey), ini);
            GetPrivateProfileStringA("devtools", "scene_xy", "164.5,149.5", sceneXy, sizeof(sceneXy), ini);
            strncpy(vm.devIniPath, ini, sizeof(vm.devIniPath) - 1);
            vm.devSceneKey = 0;
            if (sceneKey[0] == 'F' || sceneKey[0] == 'f') vm.devSceneKey = VK_F1 + atoi(sceneKey + 1) - 1;
            else if (sceneKey[0]) vm.devSceneKey = atoi(sceneKey);
            float sx = 0.0f, sy = 0.0f, sz = -1.0f;
            if (sscanf(sceneXy, "%f,%f,%f", &sx, &sy, &sz) >= 2) {
                vm.devSceneX = sx;
                vm.devSceneY = sy;
                vm.devSceneZ = sz;   // optional third number: the map level
            }
        }   // its own section: an appended [camera] would be the ini's second
    }

    // What we render at, which is nothing to do with what GTA2 thinks its screen
    // is. Its own resolution only lays the HUD out, and the overlay pass scales
    // that to whatever it is drawn into - so 640x480 in the game's options does
    // not have to mean 640x480 of path traced image. 0 means the desktop.
    g_world.SetRenderSize(GetPrivateProfileIntA("renderer", "render_width", 0, ini),
                          GetPrivateProfileIntA("renderer", "render_height", 0, ini));

    // Thousandths of a block, for the same reason the camera angles are tenths
    // of a degree: the ini API only reads integers.
    const int lift = GetPrivateProfileIntA(
        "renderer", "sprite_lift_thousandths",
        static_cast<int>(gta2dx9::kDefaultSpriteLift * 1000.0f + 0.5f), ini);
    gta2dx9::SetSpriteLift(lift / 1000.0f);

    // Stand sprites on the ground plane under them instead of at a fixed height
    // above their own level. 0 restores the fixed lift exactly, which is the way
    // back if the map read ever misdescribes a district's floor.
    gta2dx9::SetSpriteConform(GetPrivateProfileIntA("renderer", "sprite_conform", 1, ini) != 0);
    gta2dx9::SetCarWheels(GetPrivateProfileIntA("renderer", "car_wheels",
        gta2dx9::kDefaultCarWheels ? 1 : 0, ini) != 0,
        static_cast<float>(GetPrivateProfileIntA("renderer", "car_wheel_max_angle_degrees",
        static_cast<int>(gta2dx9::kDefaultCarWheelMaxAngle), ini)),
        GetPrivateProfileIntA("renderer", "car_wheel_side_percent",
        static_cast<int>(gta2dx9::kDefaultCarWheelSide * 100.0f + 0.5f), ini) / 100.0f,
        GetPrivateProfileIntA("renderer", "car_wheel_axle_inset_percent",
        static_cast<int>(gta2dx9::kDefaultCarWheelAxleInset * 100.0f + 0.5f), ini) / 100.0f,
        GetPrivateProfileIntA("renderer", "car_wheel_front_extra_percent",
        static_cast<int>(gta2dx9::kDefaultCarWheelFrontExtra * 100.0f + 0.5f), ini) / 100.0f);
    gta2dx9::SetSpriteSmooth(GetPrivateProfileIntA("renderer", "sprite_smooth",
        gta2dx9::kDefaultSpriteSmooth ? 1 : 0, ini) != 0);

    // How high the object a sprite stands in for sits above the road, in
    // thousandths of a block. Not the same thing as the lift above: that is a
    // depth-buffer clearance, this is what gives a car a shadow.
    const int height = GetPrivateProfileIntA(
        "renderer", "sprite_height_thousandths",
        static_cast<int>(gta2dx9::kDefaultSpriteHeight * 1000.0f + 0.5f), ini);
    gta2dx9::SetSpriteHeight(height / 1000.0f);

    // How much of a sideways tilt a sprite keeps, in thousandths. A car crossing
    // a ramp at an angle stands on a plane tilted both ways, so following it
    // whole rolls the body and lifts a corner - which a car on wheels does not
    // do. 0 keeps sprites level side to side, 1000 is the full fitted plane.
    // Whether gta2.exe's own view rectangle is widened to the frame we draw, so
    // new cars and pedestrians stay out of the extra width a 16:9 frame has. 0
    // leaves the game exactly as it shipped, popping included.
    gta2dx9::SetSpawnOffscreen(GetPrivateProfileIntA("renderer", "spawn_offscreen",
                                                     gta2dx9::kDefaultSpawnOffscreen ? 1 : 0, ini)
                               != 0);

    // Traffic and people in the street views (density.cpp). GTA2DX9_DENSITY=0 in
    // the environment turns all three off, for before/after measurements.
    {
        char env[8] = {};
        const bool off = GetEnvironmentVariableA("GTA2DX9_DENSITY", env, sizeof env) && env[0] == '0';
        gta2dx9::SetDensity(
            off ? 0 : GetPrivateProfileIntA("density", "traffic_cap", gta2dx9::kDefaultTrafficCap, ini),
            off ? 0 : GetPrivateProfileIntA("density", "ped_density_scale", gta2dx9::kDefaultPedDensityScale, ini),
            off ? 0 : GetPrivateProfileIntA("density", "ped_cap", gta2dx9::kDefaultPedCap, ini));
        gta2dx9::SetZoneCarDensity(
            off ? 0 : GetPrivateProfileIntA("density", "zone_car_density", gta2dx9::kDefaultZoneCarDensity, ini));
    }

    // Blood pools under bodies, which GTA2 keeps behind a debug flag.
    gta2dx9::SetBlood(
        GetPrivateProfileIntA("renderer", "blood", gta2dx9::kDefaultBlood ? 1 : 0, ini) != 0);

    // Gibs for pedestrians killed by explosions. Experimental, so off unless asked.
    gta2dx9::SetGibs(
        GetPrivateProfileIntA("renderer", "gibs", gta2dx9::kDefaultGibs ? 1 : 0, ini) != 0);
    gta2dx9::SetGibsCar(GetPrivateProfileIntA("renderer", "gibs_car",
                                              gta2dx9::kDefaultGibsCar ? 1 : 0, ini) != 0);

    // Cars as lifted bodies with a sloping skirt, so a glossy material has
    // something to reflect. Height and inset in hundredths of a block.
    // 3D cars in the ground views (car_bodies.h): off until the models are verified.
    gta2dx9::SetCarModels3d(GetPrivateProfileIntA("renderer", "car_models3d", 0, ini) != 0);
    gta2dx9::SetCarLamps(GetPrivateProfileIntA("renderer", "car_lamps", 1, ini));
    gta2dx9::SetContactShadows(GetPrivateProfileIntA("renderer", "contact_shadows", 70, ini));
    gta2dx9::SetTyreShadows(GetPrivateProfileIntA("renderer", "tyre_shadows", 1, ini));
    gta2dx9::CarGlassSettings(GetPrivateProfileIntA("renderer", "car_glass", 1, ini), GetPrivateProfileIntA("renderer", "car_glass_alpha", 52, ini),
                              GetPrivateProfileIntA("renderer", "car_glass_range", 40, ini));   // VEHICLE-GLASS
    gta2dx9::SetCarBodies(GetPrivateProfileIntA("renderer", "car_bodies",
                                                gta2dx9::kDefaultCarBodies ? 1 : 0, ini) != 0);
    gta2dx9::SetCarBodyHeight(
        GetPrivateProfileIntA("renderer", "car_body_height_hundredths",
                              static_cast<int>(gta2dx9::kDefaultCarBodyHeight * 100.0f + 0.5f),
                              ini) / 100.0f);
    gta2dx9::SetCarDomeShoulder(
        GetPrivateProfileIntA("renderer", "car_dome_shoulder_hundredths", 70, ini) / 100.0f);
    gta2dx9::SetCarBodyInset(
        GetPrivateProfileIntA("renderer", "car_body_inset_hundredths",
                              static_cast<int>(gta2dx9::kDefaultCarBodyInset * 100.0f + 0.5f),
                              ini) / 100.0f);

    // Cars as their own Remix material - glossy metal on the cars alone - when the
    // Remix API can take a mesh. Roughness and metallic in hundredths.
    gta2dx9::SetCarMaterial(
        GetPrivateProfileIntA("renderer", "car_material",
                              gta2dx9::kDefaultCarMaterial ? 1 : 0, ini) != 0,
        GetPrivateProfileIntA("renderer", "car_roughness_hundredths",
                              static_cast<int>(gta2dx9::kDefaultCarRoughness * 100.0f + 0.5f),
                              ini) / 100.0f,
        GetPrivateProfileIntA("renderer", "car_metallic_hundredths",
                              static_cast<int>(gta2dx9::kDefaultCarMetallic * 100.0f + 0.5f),
                              ini) / 100.0f);

    // Hand-made car artwork and maps from gta2dx9_hd\, where there are some.
    gta2dx9::SetCarNormalStrength(
        GetPrivateProfileIntA("renderer", "car_normal_strength_hundredths", 50, ini) / 100.0f);
    gta2dx9::SetCarDamage(
        GetPrivateProfileIntA("renderer", "car_damage_percent", 140, ini) / 100.0f);
    gta2dx9::SetCarPaintFloor(
        GetPrivateProfileIntA("renderer", "car_paint_floor_percent", 30, ini) / 100.0f);
    gta2dx9::ModelSetCarSmoothing(GetPrivateProfileIntA("renderer", "car_smooth_normals", 1, ini),
                                  GetPrivateProfileIntA("renderer", "car_crease_deg", 60, ini));   // VEHICLE-GLASS
    gta2dx9::ModelSetSoftPaintMasks(
        GetPrivateProfileIntA("renderer", "car_paint_soft_mask", 1, ini) != 0);
    gta2dx9::SetCarGlassGloss(
        GetPrivateProfileIntA("renderer", "car_glass_gloss_percent", 100, ini) / 100.0f);
    gta2dx9::RemixLoadConfigSection(ini);
    gta2dx9::RemixSetLightSampling(
        GetPrivateProfileIntA("remix", "di_initial_samples", 16, ini),
        GetPrivateProfileIntA("remix", "di_spatial_samples", 3, ini),
        GetPrivateProfileIntA("remix", "di_disocclusion_samples", 8, ini));
    gta2dx9::SetOwnFigureShadowAllowed(GetPrivateProfileIntA("remix", "own_shadow_first_person", 0, ini) != 0);
    gta2dx9::SetCarPaintGloss(
        GetPrivateProfileIntA("renderer", "car_paint_gloss_percent", 100, ini) / 100.0f);
    for (int sprite = 0; sprite < 80; ++sprite) {
        char key[48];
        sprintf_s(key, "car_paint_gloss_%02d_percent", sprite);
        const int percent = GetPrivateProfileIntA("renderer", key, -1, ini);
        // Unset reads back as the default, -1 (a stored negative number would read as huge).
        if (static_cast<int>(percent) >= 0) gta2dx9::SetCarPaintGlossFor(sprite, percent / 100.0f);
    }
    gta2dx9::SetCarGlassCurve(
        GetPrivateProfileIntA("renderer", "car_glass_curve_percent", 60, ini) / 100.0f);
    gta2dx9::SkidSmokeLoad(ini);
    gta2dx9::FireEffectsLoad(ini);
    gta2dx9::CrowdLoad(ini);
    gta2dx9::SetCarHd(GetPrivateProfileIntA("renderer", "car_hd", 1, ini) != 0,
                      GetPrivateProfileIntA("renderer", "car_normal_maps", 1, ini) != 0);

    // How brightly a lit car lamp glows (emissive intensity; 0 = a plain quad).
    gta2dx9::SetCarLampGlow(static_cast<float>(
        GetPrivateProfileIntA("renderer", "car_lamp_glow",
                              static_cast<int>(gta2dx9::kDefaultCarLampGlow), ini)));

    // Blood on the ground: dark and wet. roughness is 0..100 (0 a mirror); darkness is the share
    // of the game's red kept, so lower is darker.
    gta2dx9::SetBloodLook(GetPrivateProfileIntA("renderer", "blood_gloss", 1, ini) != 0,
                          GetPrivateProfileIntA("renderer", "blood_roughness_percent", 7, ini) / 100.0f,
                          GetPrivateProfileIntA("renderer", "blood_albedo_percent", 55, ini) / 100.0f);

    gta2dx9::SetCarLampSize(GetPrivateProfileIntA("renderer", "car_lamp_size_percent",
        static_cast<int>(gta2dx9::kDefaultCarLampSize * 100.0f + 0.5f), ini) / 100.0f);

    // The arrows and target markers move with the world, not with the game's camera.
    gta2dx9::SetHudWorldFollow(GetPrivateProfileIntA("renderer", "hud_world_follow",
        gta2dx9::kDefaultHudWorldFollow ? 1 : 0, ini) != 0);
    // How much the view eases the game's camera: 0 is the game's own, 100 the
    // default, 200 twice as slow to follow a swing.
    gta2dx9::SetCameraSmoothing(GetPrivateProfileIntA("renderer", "camera_smooth_percent",
        static_cast<int>(gta2dx9::kDefaultCameraSmoothing * 100.0f + 0.5f), ini) / 100.0f);

    // Car lamps as our own small quads rather than GTA2's whole-car one.
    gta2dx9::SetOwnCarLamps(GetPrivateProfileIntA("renderer", "own_car_lamps",
                                                  gta2dx9::kDefaultOwnCarLamps ? 1 : 0, ini) != 0);

    // Whether the intro movie plays. Decided here rather than by GTA2's own
    // do_play_movie, and either way it never goes near DirectDraw.
    g_intro =
        GetPrivateProfileIntA("renderer", "intro", gta2dx9::kDefaultIntro ? 1 : 0, ini) != 0;

    gta2dx9::SetSpriteRoll(
        GetPrivateProfileIntA("renderer", "sprite_roll_thousandths",
                              static_cast<int>(gta2dx9::kDefaultSpriteRoll * 1000.0f + 0.5f), ini)
        / 1000.0f);

    // Dump every distinct frame of artwork as a TGA, and write the classification
    // numbers beside it. On by default: the files are a few kilobytes each and a
    // few hundred per session, and it is the only way to find a sprite whose
    // black rim was missed.
    gta2dx9::SetTextureDumping(GetPrivateProfileIntA("renderer", "dump_textures", 1, ini) != 0);

    // High-resolution tiles from gta2dx9_textures_hd\ beside the game (see
    // tools/upscale_textures.py), and the dump they are made from: dump_tiles=1
    // writes every tile the world uses to gta2dx9_tiles\ at level load.
    {
        char dir[MAX_PATH];
        PathBesideGame("gta2dx9_textures_hd", dir, sizeof(dir));
        gta2::SetHdTextureDir(dir);
        // Photo-material versions of the tiles (tools/photoreal_tiles.py) in its photo\ subfolder.
        if (GetPrivateProfileIntA("renderer", "photo_tiles", 1, ini) != 0) {
            char photo[MAX_PATH];
            snprintf(photo, sizeof(photo), "%s\\photo", dir);
            gta2::SetPhotoTextureDir(photo);
        }
        // Road markings re-authored over the photo asphalt (tools/reauthor_road_markings.py) in roads\.
        if (GetPrivateProfileIntA("renderer", "road_markings", 1, ini) != 0) {
            char roads[MAX_PATH];
            snprintf(roads, sizeof(roads), "%s\\roads", dir);
            gta2::SetRoadTextureDir(roads);
        }
        gta2::SetToneMatch(GetPrivateProfileIntA("renderer", "tone_match", 1, ini) != 0);
        gta2::SetHdTileMaxSize(GetPrivateProfileIntA("renderer", "hd_tile_max", 512, ini));
        gta2::SetWaterEffect(GetPrivateProfileIntA("renderer", "water_effect", 1, ini) != 0);
        gta2::SetWaterShader(GetPrivateProfileIntA("renderer", "water_shader", 1, ini) != 0);
        gta2::SetWaterTuning(GetPrivateProfileIntA("renderer", "water_waves", 100, ini) / 100.0f,
                             GetPrivateProfileIntA("renderer", "water_reflection", 100, ini) / 100.0f,
                             GetPrivateProfileIntA("renderer", "water_foam", 100, ini) / 100.0f);
        gta2::SetWindowGlow(GetPrivateProfileIntA("renderer", "window_glow", 1, ini) != 0);
        gta2::SetAnisotropy(GetPrivateProfileIntA("renderer", "anisotropy", 0, ini));
        if (GetPrivateProfileIntA("renderer", "dump_tiles", 0, ini) != 0) {
            PathBesideGame("gta2dx9_tiles", dir, sizeof(dir));
            gta2::SetTileDumpDir(dir);
        }
    }

    // Our own frame cap, because GTA2's is a checkbox: its pacer waits on a
    // hardcoded 33 ms step and the two registry values only turn that waiting on
    // and off. 0 leaves the game free-running. Note that the game advances its
    // simulation one step per frame, so this sets the speed as well as the
    // smoothness - see frame_limiter.h.
    gta2dx9::FrameLimitSet(
        static_cast<float>(GetPrivateProfileIntA("renderer", "fps_cap", 30, ini)));

    // The day/night cycle. Hours and minutes rather than a float, because the ini
    // API only reads integers; 0200 is 2 am.
    gta2dx9::TimeOfDaySettings& tod = gta2dx9::TimeOfDay();
    tod.enabled = GetPrivateProfileIntA("timeofday", "enabled", 1, ini) != 0;
    const int start = GetPrivateProfileIntA("timeofday", "start_hhmm", 200, ini);
    tod.startHour = static_cast<float>(start / 100) + static_cast<float>(start % 100) / 60.0f;
    // The clock stopped: every level then starts and stays at start_hhmm, for
    // anyone who would rather play at one time of day.
    tod.paused = GetPrivateProfileIntA("timeofday", "paused", 0, ini) != 0;
    // Tenths, like the camera angles: the ini API only reads integers, and 10 is
    // the default one real second to one game minute.
    tod.minutesPerSecond =
        GetPrivateProfileIntA("timeofday", "game_minutes_per_second_tenths", 10, ini) / 10.0f;
    tod.latitudeDeg =
        GetPrivateProfileIntA("timeofday", "latitude_tenths", 400, ini) / 10.0f;
    tod.declinationDeg =
        GetPrivateProfileIntA("timeofday", "declination_tenths", 0, ini) / 10.0f;
    const int lightsOff = GetPrivateProfileIntA("timeofday", "lights_off_hhmm", 600, ini);
    const int lightsOn = GetPrivateProfileIntA("timeofday", "lights_on_hhmm", 1800, ini);
    tod.lightsOffHour =
        static_cast<float>(lightsOff / 100) + static_cast<float>(lightsOff % 100) / 60.0f;
    tod.lightsOnHour =
        static_cast<float>(lightsOn / 100) + static_cast<float>(lightsOn % 100) / 60.0f;
    // Under Remix: the exposure cap and the sky fill by day and by night (tenths; 0
    // leaves the option to rtx.conf), switched when the sun crosses the horizon.
    tod.dayMaxExposure =
        GetPrivateProfileIntA("timeofday", "remix_day_max_exposure_tenths", 60, ini) / 10.0f;
    tod.nightMaxExposure =
        GetPrivateProfileIntA("timeofday", "remix_night_max_exposure_tenths", 25, ini) / 10.0f;
    tod.daySkyFill = GetPrivateProfileIntA("timeofday", "remix_day_sky_fill_tenths", 30, ini) / 10.0f;
    tod.nightSkyFill =
        GetPrivateProfileIntA("timeofday", "remix_night_sky_fill_tenths", 10, ini) / 10.0f;
    tod.playerFill = GetPrivateProfileIntA("timeofday", "remix_player_fill_percent", 25, ini) / 100.0f;
    gta2dx9::TimeOfDayReset();

    // The sky of the street-level views. See sky.h and the [sky] section.
    {
        gta2::SkySettings& sky = gta2::SkyConfig();
        sky.enabled = GetPrivateProfileIntA("sky", "enabled", 1, ini) != 0;
        sky.followClock = GetPrivateProfileIntA("sky", "follow_clock", 0, ini) != 0;
        sky.sunElevationDeg = GetPrivateProfileIntA("sky", "sun_elevation_tenths", 240, ini) / 10.0f;
        sky.sunAzimuthDeg = GetPrivateProfileIntA("sky", "sun_azimuth_tenths", 2350, ini) / 10.0f;
        sky.fogStart = static_cast<float>(GetPrivateProfileIntA("sky", "fog_start_blocks", 18, ini));
        sky.fogEnd = static_cast<float>(GetPrivateProfileIntA("sky", "fog_end_blocks", 130, ini));
        if (sky.fogEnd < sky.fogStart + 5.0f) sky.fogEnd = sky.fogStart + 5.0f;
        sky.cloudCover = GetPrivateProfileIntA("sky", "cloud_cover_percent", 45, ini) / 100.0f;
        sky.ambient = GetPrivateProfileIntA("sky", "ambient_percent", 80, ini) / 100.0f;
        sky.sunLight = GetPrivateProfileIntA("sky", "sun_light_percent", 40, ini) / 100.0f;
        gta2dx9::Log("sky: %s, sun %s at elevation %.0f azimuth %.0f, fog %.0f..%.0f blocks, clouds %.0f%%, ambient %.0f%% sun %.0f%%",
                     sky.enabled ? "on in the street views" : "off", sky.followClock ? "from the clock" : "fixed",
                     sky.sunElevationDeg, sky.sunAzimuthDeg, sky.fogStart, sky.fogEnd, sky.cloudCover * 100.0f,
                     sky.ambient * 100.0f, sky.sunLight * 100.0f);
    }

    // The effective sprite numbers, not the compiled-in ones. gta2dx9.ini's
    // template used to carry a stale copy of the ride height and quietly override
    // the code with it for several builds; printing what actually took effect is
    // what would have caught that on the first run.
    Log("loaded as %s; mode=%s backend=%s fps_cap=%.0f tod=%s@%05.2f", OwnModuleLeaf(),
        g_mode == Mode::Takeover ? "takeover" : "proxy", g_backendName,
        gta2dx9::FrameLimitFps(), tod.enabled ? "on" : "off", tod.startHour);
    Log("sprites: conform=%s height=%.3f roll=%.2f fallback_lift=%.3f stack_step=%.3f blocks",
        gta2dx9::SpriteConform() ? "on" : "off", gta2dx9::SpriteHeight(), gta2dx9::SpriteRoll(),
        gta2dx9::SpriteLift(), gta2dx9::SpriteStackStep());
}

bool BindBackend() {
    g_backend = LoadLibraryA(g_backendName);
    if (g_backend == g_self) {
        // Belt and braces against the name juggling above: loading ourselves as
        // the backend would recurse through every export until the stack ran out.
        Log("FATAL: backend '%s' resolved to this DLL; refusing to proxy to myself",
            g_backendName);
        g_backend = nullptr;
        return false;
    }
    if (!g_backend) {
        Log("FATAL: cannot load backend '%s' (error %lu)", g_backendName, GetLastError());
        return false;
    }
    int missing = 0;
    for (const Binding& binding : kBindings) {
        *binding.slot = reinterpret_cast<void*>(GetProcAddress(g_backend, binding.name));
        if (!*binding.slot) ++missing;
    }
    Log("backend bound, %d missing", missing);
    return true;
}

bool Proxying() { return g_mode == Mode::Proxy; }

void PresentMovieFrame(const void* pixels, int width, int height, int pitch) {
    g_world.ShowMovieFrame(pixels, width, height, pitch);
}

template <typename Fn>
Fn Backend(void* slot) { return reinterpret_cast<Fn>(slot); }

using gta2dx9::TextureRecord;

WNDPROC g_originalWndProc = nullptr;

// Alt+F4 does not necessarily reach gbh_CloseScreen, so the device is also
// released straight off the window's own close message. Without this the game
// exits its loop while D3D9 still holds the window, leaving the process alive
// and the desktop in a half-torn-down state.
// The game window is gone and the game is meant to be gone with it. If the
// process is still there a few seconds later, something in the game's or the
// bridge's own teardown is stuck, and the person is left looking at a window
// that takes no input and has to kill it by hand. End it for them.
DWORD WINAPI QuitWatchdog(LPVOID) {
    Sleep(4000);
    Log("quit watchdog: process still alive 4 s after the game window closed; ending it");
    TerminateProcess(GetCurrentProcess(), 0);
    return 0;
}

// The thread above does not survive the way GTA2 quits: it calls ExitProcess, which
// ends every other thread first and then hangs in some module's teardown - after
// which no thread of ours is left to do anything. A separate process is. This one
// waits a few seconds and ends the game by process id; if the game has exited by
// itself by then, taskkill finds nothing and does nothing.
//
// Everything it runs is named by its full path under the Windows system folder, and the helper
// starts with that folder as its working directory. Nothing is looked up through the search path,
// so a cmd.exe, ping.exe or taskkill.exe that someone has put in the game folder is never run.
void SpawnQuitKiller() {
    wchar_t sysDir[MAX_PATH] = {};
    const UINT length = GetSystemDirectoryW(sysDir, MAX_PATH);
    if (length == 0 || length >= MAX_PATH - 20) {
        Log("quit watchdog: could not find the Windows sysDir folder (error %lu)", GetLastError());
        return;
    }
    wchar_t shell[MAX_PATH] = {};
    wsprintfW(shell, L"%s\\cmd.exe", sysDir);
    wchar_t command[1400] = {};
    // cmd /c "<line>": the outer quotes are removed by cmd, which leaves the two quoted program paths.
    wsprintfW(command,
              L"\"%s\" /c \"\"%s\\ping.exe\" -n 6 127.0.0.1 >nul & \"%s\\taskkill.exe\" /F /PID %lu >nul 2>&1\"",
              shell, sysDir, sysDir, GetCurrentProcessId());
    STARTUPINFOW startup = {};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION info = {};
    if (CreateProcessW(shell, command, nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr,
                       sysDir, &startup, &info)) {
        CloseHandle(info.hThread);
        CloseHandle(info.hProcess);
        Log("quit watchdog: helper process started, will end the game in ~5 s if it is still there");
    } else {
        Log("quit watchdog: could not start the helper process (error %lu)", GetLastError());
    }
}

// ---- Where the game is when it stalls or closes -------------------------------------------
//
// The Options screen freezes the game for seconds, or closes its window, and nothing in the
// log says what it is doing. Two aids, both log-only:
//  - every address on a call stack is written as module+offset, so a window that is destroyed
//    or a thread that is stuck can be traced to the code that did it;
//  - a sampler thread watches the frame heartbeat, and when the game thread has not drawn a
//    frame for 1.5 s it stops that thread for a moment, copies its registers and the return
//    addresses on its stack, lets it go and logs them.
volatile DWORD g_beat = 0;          // tick count at the last gbh_BeginScene
volatile LONG g_shuttingDown = 0;
DWORD g_gameThread = 0;

void DescribeAddress(const void* address, char* out, size_t size) {
    HMODULE module = nullptr;
    char leaf[MAX_PATH] = "?";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCSTR>(address), &module) && module) {
        char path[MAX_PATH] = {};
        if (GetModuleFileNameA(module, path, MAX_PATH)) {
            const char* slash = strrchr(path, '\\');
            strncpy_s(leaf, slash ? slash + 1 : path, _TRUNCATE);
        }
        _snprintf_s(out, size, _TRUNCATE, "%s+0x%X", leaf,
                    static_cast<unsigned>(reinterpret_cast<const char*>(address) -
                                          reinterpret_cast<const char*>(module)));
    } else {
        _snprintf_s(out, size, _TRUNCATE, "%p", address);
    }
}

void LogBacktrace(const char* why) {
    void* frames[28] = {};
    const USHORT count = CaptureStackBackTrace(1, 28, frames, nullptr);
    char line[1024] = {};
    size_t at = 0;
    for (USHORT i = 0; i < count && at + 64 < sizeof(line); ++i) {
        char one[160];
        DescribeAddress(frames[i], one, sizeof(one));
        at += _snprintf_s(line + at, sizeof(line) - at, _TRUNCATE, "%s%s", i ? " < " : "", one);
    }
    Log("%s: call stack %s", why, line);
}

bool LooksLikeReturnAddress(const uint8_t* p) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT) return false;
    if (!(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                         PAGE_EXECUTE_WRITECOPY))) return false;
    // A return address follows a call: E8 rel32 five bytes back, or FF /2 two to seven back.
    GTA2_TRY {
        if (p[-5] == 0xE8) return true;
        if (p[-2] == 0xFF && (p[-1] & 0x38) == 0x10) return true;
        if (p[-3] == 0xFF && (p[-2] & 0x38) == 0x10) return true;
        if (p[-6] == 0xFF && (p[-5] & 0x38) == 0x10) return true;
    } GTA2_EXCEPT {
    }
    return false;
}

DWORD WINAPI StallSampler(LPVOID) {
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                               FALSE, g_gameThread);
    if (!thread) {
        Log("stall sampler: cannot open the game thread (error %lu)", GetLastError());
        return 0;
    }
    int samples = 0;
    DWORD lastSample = 0;
    // FIX-REMIX-NIGHT (pt-remix-ultra-cold-cache-freeze-on-first-view-switch): after the first 60 stack
    // samples the sampler used to stop, so a stall that went on (a Remix server compiling for minutes on a
    // cold shader cache) left the log silent from 49 s on. Past the cap it now writes one short line every
    // 5 s while the thread is idle, and one when it comes back, with no stack walk.
    DWORD stallBeat = 0, longest = 0;
    while (!g_shuttingDown) {
        Sleep(250);
        const DWORD beat = g_beat;
        const DWORD now = GetTickCount();
        if (stallBeat && beat != stallBeat) {
            if (samples >= 60) Log("stall sampler: game thread back after %lu ms idle", static_cast<unsigned long>(longest));
            stallBeat = 0;
            longest = 0;
        }
        if (!beat || now - beat < 1500) continue;
        stallBeat = beat;
        longest = now - beat;
        if (samples >= 60) {
            if (now - lastSample >= 5000) {
                lastSample = now;
                Log("stall sampler: game thread idle %lu ms (no stack: past the sample cap)", static_cast<unsigned long>(now - beat));
            }
            continue;
        }
        if (now - lastSample < 1000) continue;
        lastSample = now;
        uintptr_t pc = 0, sp = 0;
        uintptr_t stackWords[512] = {};
        int words = 0;
        if (SuspendThread(thread) == static_cast<DWORD>(-1)) continue;
        CONTEXT context = {};
        context.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (GetThreadContext(thread, &context)) {
#ifdef _M_IX86
            pc = context.Eip;
            sp = context.Esp;
#else
            pc = context.Rip;
            sp = context.Rsp;
#endif
            SIZE_T got = 0;
            if (ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<LPCVOID>(sp), stackWords,
                                  sizeof(stackWords), &got)) {
                words = static_cast<int>(got / sizeof(uintptr_t));
            } else {
                for (; words < 512; ++words) {   // up to the end of the readable stack
                    if (!ReadProcessMemory(GetCurrentProcess(),
                                           reinterpret_cast<LPCVOID>(sp + words * sizeof(uintptr_t)),
                                           &stackWords[words], sizeof(uintptr_t), &got)) break;
                }
            }
        }
        ResumeThread(thread);   // before anything that logs: the game thread must not hold us up
        ++samples;
        if (!pc) continue;
        char where[160];
        DescribeAddress(reinterpret_cast<const void*>(pc), where, sizeof(where));
        char line[1400] = {};
        size_t at = 0;
        int found = 0;
        for (int i = 0; i < words && found < 20 && at + 64 < sizeof(line); ++i) {
            const uint8_t* candidate = reinterpret_cast<const uint8_t*>(stackWords[i]);
            if (stackWords[i] < 0x10000 || !LooksLikeReturnAddress(candidate)) continue;
            char one[160];
            DescribeAddress(candidate, one, sizeof(one));
            at += _snprintf_s(line + at, sizeof(line) - at, _TRUNCATE, "%s%s", found ? " < " : "", one);
            ++found;
        }
        Log("stall sampler: game thread idle %lu ms (sample %d) at %s, callers %s",
            static_cast<unsigned long>(now - beat), samples, where, line);
    }
    CloseHandle(thread);
    return 0;
}

void StartStallSampler(DWORD gameThread) {
    static bool started = false;
    if (started || !gameThread) return;
    started = true;
    g_gameThread = gameThread;
    if (HANDLE thread = CreateThread(nullptr, 0, StallSampler, nullptr, 0, nullptr)) CloseHandle(thread);
}

LRESULT CALLBACK ClosingWndProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    // The messages that would say the game is changing its display mode or window: logged with
    // the code that sent them, the first few times each.
    {
        static int seen[512] = {};
        const bool interesting =
            message == WM_CLOSE || message == WM_DESTROY || message == WM_QUIT ||
            message == WM_DISPLAYCHANGE || message == WM_ACTIVATEAPP || message == WM_SIZE ||
            message == WM_SYSCOMMAND || message == WM_STYLECHANGED || message == WM_SHOWWINDOW ||
            message == WM_SETFOCUS || message == WM_KILLFOCUS;
        if (interesting && message < 512 && seen[message]++ < 12) {
            Log("window message %u (wparam %llx lparam %llx)", message,
                static_cast<unsigned long long>(wparam), static_cast<unsigned long long>(lparam));
            if (message == WM_CLOSE || message == WM_DESTROY || message == WM_DISPLAYCHANGE ||
                message == WM_SYSCOMMAND) {
                LogBacktrace("window message");
            }
        }
    }
    if (message == WM_CLOSE || message == WM_DESTROY) {
        Log("window closing (msg %u): releasing renderer", message);
        InterlockedExchange(&g_shuttingDown, 1);
        g_world.Shutdown();
    }
    if (message == WM_DESTROY) {
        static bool armed = false;
        if (!armed) {
            armed = true;
            SpawnQuitKiller();
            if (HANDLE thread = CreateThread(nullptr, 0, QuitWatchdog, nullptr, 0, nullptr))
                CloseHandle(thread);
        }
    }
    return CallWindowProc(g_originalWndProc, window, message, wparam, lparam);
}

void HookWindowClose(HWND window) {
    if (g_originalWndProc || !window) return;
    // Pinned first: once a window procedure of ours is installed, this DLL must
    // outlive the window. GTA2 quits from inside the close message - WM_CLOSE
    // reaches ClosingWndProc, CallWindowProc runs the game's own handler, and
    // that tears the game down and FreeLibrary's the renderer while
    // ClosingWndProc is still on the stack waiting for it to return. Unloaded,
    // the return lands in freed memory: the access violation at d3ddll.dll+0x20C0
    // on every quit. Unhooking cannot help with a frame already on the stack;
    // keeping the code mapped until the process ends does.
    HMODULE pinned = nullptr;
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                            reinterpret_cast<LPCSTR>(&ClosingWndProc), &pinned)) {
        Log("could not pin the renderer (error %lu); not hooking the window close",
            GetLastError());
        return;
    }
    g_originalWndProc = reinterpret_cast<WNDPROC>(
        SetWindowLongPtrA(window, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(ClosingWndProc)));
}

}  // namespace

extern "C" {

// What is already in the process by the time the game reaches its renderer.
// Under RTX Remix this is how you tell whether something else has already
// dragged Direct3D 9 in and taken the window: whatever did so owns the display
// before we exist, and our own device then loses the argument.
void LogGraphicsModules() {
    HMODULE modules[512];
    DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) return;
    const size_t count = needed / sizeof(HMODULE);
    for (size_t i = 0; i < count; ++i) {
        char path[MAX_PATH];
        if (!GetModuleFileNameA(modules[i], path, MAX_PATH)) continue;
        const char* leaf = strrchr(path, '\\');
        leaf = leaf ? leaf + 1 : path;
        // The video device too, and anything that could stand in for one: on a
        // machine where the game's own DirectDraw device was loaded instead of
        // ours, this is the line that says which file it was.
        char lower[MAX_PATH];
        strncpy(lower, leaf, sizeof(lower) - 1);
        lower[sizeof(lower) - 1] = '\0';
        _strlwr(lower);
        if (_stricmp(leaf, "d3d9.dll") == 0 || _stricmp(leaf, "ddraw.dll") == 0 ||
            _stricmp(leaf, "dxgi.dll") == 0 || _stricmp(leaf, "d3d9_remix.dll") == 0 ||
            _stricmp(leaf, "dciman32.dll") == 0 || strstr(lower, "video") ||
            strstr(lower, "dma") || strstr(lower, "glide") || strstr(lower, "gta2dx9")) {
            Log("already loaded: %s", path);
        }
    }
    // Which file the game is actually calling for its video device: the module
    // that holds the Vid_Init_SYS it resolved (gta2.exe's table at 0x00595020).
    const void* vidInit = *reinterpret_cast<void* const*>(0x00595020);
    HMODULE owner = nullptr;
    char ownerPath[MAX_PATH] = "(none)";
    if (vidInit &&
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCSTR>(vidInit), &owner)) {
        GetModuleFileNameA(owner, ownerPath, MAX_PATH);
    }
    Log("video device in use: %s (Vid_Init_SYS at %p)", ownerPath, vidInit);
}

// Make the process DPI-aware, before our present window exists.
//
// A DPI-unaware process on a scaled desktop has its windows scaled by the window
// manager on the way out. For the present window that means the swap chain is
// composited rather than flipped straight to the screen, which is what frame
// generation wants; it came and went with whatever else happened to make the
// process aware first. dxwrapper's ddraw.dll did ("Disabling High DPI Scaling"),
// and the RTX Remix bridge does, but only once it loads - after the window.
// Neither is something to rely on: the release ships no dxwrapper.
//
// The same three calls dxwrapper makes, newest first. Each fails harmlessly if
// the process already has an awareness, and the window gets one of its own in
// CreatePresentWindow either way.
void MakeProcessDpiAware() {
    HMODULE user32 = GetModuleHandleA("user32.dll");
    typedef BOOL(WINAPI * SetContextFn)(HANDLE);
    const SetContextFn setContext = user32 ? reinterpret_cast<SetContextFn>(
        GetProcAddress(user32, "SetProcessDpiAwarenessContext")) : nullptr;
    // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, spelled out so this builds
    // against any SDK.
    if (setContext && setContext(reinterpret_cast<HANDLE>(static_cast<intptr_t>(-4)))) {
        Log("dpi: process made per-monitor aware (v2)");
        return;
    }
    if (HMODULE shcore = LoadLibraryA("shcore.dll")) {
        typedef HRESULT(WINAPI * SetAwarenessFn)(int);
        const SetAwarenessFn setAwareness =
            reinterpret_cast<SetAwarenessFn>(GetProcAddress(shcore, "SetProcessDpiAwareness"));
        if (setAwareness && SUCCEEDED(setAwareness(2))) {  // PROCESS_PER_MONITOR_DPI_AWARE
            Log("dpi: process made per-monitor aware");
            return;
        }
    }
    typedef BOOL(WINAPI * SetAwareFn)();
    const SetAwareFn setAware =
        user32 ? reinterpret_cast<SetAwareFn>(GetProcAddress(user32, "SetProcessDPIAware"))
               : nullptr;
    if (setAware && setAware()) {
        Log("dpi: process made system aware");
        return;
    }
    Log("dpi: process awareness left as it was (already set, or not available)");
}

__declspec(dllexport) void __stdcall gbh_InitDLL(void* system) {
    g_system = system;
    Log("gbh_InitDLL(system=%p)", system);
    LogGraphicsModules();
    LoadConfig();
    if (Proxying()) {
        if (BindBackend() && g_p_gbh_InitDLL) {
            Backend<void(__stdcall*)(void*)>(g_p_gbh_InitDLL)(system);
        }
        Log("proxy live");
    } else {
        Log("takeover mode: the original renderer is not loaded");
        MakeProcessDpiAware();
        // Before anything else the game does: its startup decides whether to play
        // the intro straight after loading us.
        gta2dx9::IntroInstall(g_intro, &PresentMovieFrame);
        // So the overlay can tell the HUD from screen-space draws tied to the
        // world, and move only the HUD out to the edges of a wide display.
        gta2dx9::HudPassInstall();
        // Every death passes through us so gibs can be switched on from the menu.
        gta2dx9::GibsInstall();
        // Recorded voice-overs for the game's text messages, from gta2dx9_voice\.
        gta2dx9::VoiceInstall();
        // The car engines' volume goes through us too, so the menu can turn them down.
        gta2dx9::EngineSoundInstall();
        // Radio stations stay in stereo at any distance, unless the menu switches the effect on.
        gta2dx9::RadioInstall();
        // In the street views every sound is placed relative to our camera, not the game's top-down one.
        {
            char audioIni[MAX_PATH];
            PathBesideGame("gta2dx9.ini", audioIni, sizeof(audioIni));
            gta2dx9::Audio3DInstall(audioIni);
            // Pedestrians react to gunfire, cars and fires at street-view distances.
            gta2dx9::CityAiInstall(audioIni);
        }
        // The game's Options button opens our panel; GTA2 Manager.exe does nothing here.
        gta2dx9::OptionsButtonInstall();
        // Reads last session's files into memory in the background, so cars do not stall on a cold disk.
        gta2dx9::CacheWarmupStart();
        char path[MAX_PATH];
        PathBesideGame("gta2dx9_lights.ini", path, sizeof(path));
        gta2dx9::LightsInit(path);
        PathBesideGame("gta2dx9_effects.ini", path, sizeof(path));
        gta2dx9::SyntheticLightsLoad(path);
        // Last, so it can override anything gta2dx9.ini set: deploy rewrites that
        // file on every build, this one is the user's own tuning.
        PathBesideGame("gta2dx9_settings.ini", path, sizeof(path));
        gta2dx9::SettingsInit(path);
        gta2dx9::SettingsLoadAll();
        // The imported 3D models for the ground views. See model_store.h.
        PathBesideGame("gta2dx9_models", path, sizeof(path));
        gta2dx9::ModelsLoad(path);
    }
}

// Both teardown paths release the device. The game closes the screen before it
// destroys its window, and leaving a live D3D9 device attached to a window that
// is going away keeps the process alive after Alt+F4 with the display left in a
// half-torn-down state.
__declspec(dllexport) void __stdcall gbh_CloseScreen(void* param) {
    g_world.Shutdown();
    if (Proxying() && g_p_gbh_CloseScreen) {
        Backend<void(__stdcall*)(void*)>(g_p_gbh_CloseScreen)(param);
    }
}

__declspec(dllexport) void __stdcall gbh_CloseDLL() {
    g_world.Shutdown();
    gta2dx9::FrameLimitShutdown();
    if (Proxying() && g_p_gbh_CloseDLL) Backend<void(__stdcall*)()>(g_p_gbh_CloseDLL)();
}

__declspec(dllexport) int __stdcall gbh_Init(int param) {
    if (Proxying() && g_p_gbh_Init) return Backend<int(__stdcall*)(int)>(g_p_gbh_Init)(param);

    HWND window = game::MainWindow();
    RECT client = {};
    GetClientRect(window, &client);
    const int width = client.right > 0 ? client.right : 640;
    const int height = client.bottom > 0 ? client.bottom : 480;

    // Remix drives its runtime through window messages sent to the thread that
    // owns the game window, so which thread that is matters.
    const DWORD windowThread = GetWindowThreadProcessId(window, nullptr);
    Log("gbh_Init: hwnd=%p client=%dx%d owner thread=%lu, we are thread=%lu", window, width, height,
        windowThread, GetCurrentThreadId());

    // Not fatal if the device is not up yet: RTX Remix needs the game's message
    // loop to have run before it can hand one over, which has not happened at
    // this point in startup. The frame loop keeps asking.
    std::string error;
    if (!g_world.Initialize(window, width, height, &error)) {
        Log("world view init deferred: %s", error.c_str());
    }
    HookWindowClose(window);
    StartStallSampler(windowThread ? windowThread : GetCurrentThreadId());
    // Plugins drawing through the original renderer's device - see
    // plugin_d3d6.cpp. Here because by now every plugin the game loads is in.
    gta2dx9::PluginD3D6Install();
    return 0;
}

// Intercepted rather than ignored: the texture the game passes identifies the
// tile it believes belongs at the cell it is drawing, which is the ground truth
// our own map walk is checked against.
__declspec(dllexport) void __stdcall gbh_DrawTile(unsigned flags, void* texture, float* vertices,
                                                  unsigned char shade) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_DrawTile) {
        Backend<void(__stdcall*)(unsigned, void*, float*, unsigned char)>(g_p_gbh_DrawTile)(
            flags, texture, vertices, shade);
        return;
    }
    g_world.CheckDrawnShape(4);
    g_world.CheckDrawnTile(texture);
}

__declspec(dllexport) void __stdcall gbh_BeginScene() {
    g_beat = GetTickCount();
    gta2dx9::FrameLogMarkBeginScene();
    if (Proxying() && g_p_gbh_BeginScene) { Backend<void(__stdcall*)()>(g_p_gbh_BeginScene)(); return; }
    g_world.BeginFrame();
}

__declspec(dllexport) void __stdcall gbh_EndScene() {
    if (Proxying() && g_p_gbh_EndScene) { Backend<void(__stdcall*)()>(g_p_gbh_EndScene)(); return; }
    // Between this frame's particle update and the next, which is when a limb
    // about to land has to be caught.
    gta2dx9::GibsUpdate();
    g_world.RenderFrame();
}

__declspec(dllexport) void __stdcall gbh_BeginLevel() {
    if (Proxying() && g_p_gbh_BeginLevel) { Backend<void(__stdcall*)()>(g_p_gbh_BeginLevel)(); return; }
    g_world.InvalidateWorld();
    gta2dx9::GibsReset();
    // Every run starts at the same time of day, which is the point of a start
    // hour: 2 am, and dark.
    gta2dx9::TimeOfDayReset();
}

__declspec(dllexport) void __stdcall gbh_EndLevel() {
    if (Proxying() && g_p_gbh_EndLevel) { Backend<void(__stdcall*)()>(g_p_gbh_EndLevel)(); return; }
    g_world.InvalidateWorld();
    gta2dx9::GibsReset();
}

__declspec(dllexport) void __stdcall gbh_SetCamera(float minX, float minY, float maxX, float maxY) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_SetCamera) {
        Backend<void(__stdcall*)(float, float, float, float)>(g_p_gbh_SetCamera)(minX, minY, maxX, maxY);
        return;
    }
    g_world.SetVisibleTileBounds(minX, minY, maxX, maxY);
}

__declspec(dllexport) void* __stdcall gbh_RegisterTexture(unsigned short width, unsigned short height,
                                                          void* pixels, int palette, char flag) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_RegisterTexture) {
        return Backend<void*(__stdcall*)(unsigned short, unsigned short, void*, int, char)>(
            g_p_gbh_RegisterTexture)(width, height, pixels, palette, flag);
    }
    TextureRecord* record = static_cast<TextureRecord*>(calloc(1, sizeof(TextureRecord)));
    if (record) {
        record->width = width;
        record->height = height;
        record->palette = static_cast<uint16_t>(palette);
        record->paletteLow = static_cast<uint8_t>(palette);
        record->pixels = pixels;
    }
    return record;
}

__declspec(dllexport) void __stdcall gbh_FreeTexture(void* texture) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_FreeTexture) { Backend<void(__stdcall*)(void*)>(g_p_gbh_FreeTexture)(texture); return; }
    gta2dx9::ForgetDeviceTexture(texture);
    free(texture);
}

__declspec(dllexport) void __stdcall gbh_LockTexture(void* texture) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_LockTexture) { Backend<void(__stdcall*)(void*)>(g_p_gbh_LockTexture)(texture); return; }
    if (texture) static_cast<TextureRecord*>(texture)->flags |= 1;
}

// The game edits a texture's pixels between lock and unlock, so an unlock is
// the signal that any cached copy of it is stale.
__declspec(dllexport) void __stdcall gbh_UnlockTexture(void* texture) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_UnlockTexture) { Backend<void(__stdcall*)(void*)>(g_p_gbh_UnlockTexture)(texture); return; }
    if (!texture) return;
    TextureRecord* record = static_cast<TextureRecord*>(texture);
    record->flags &= ~1;
    ++record->revision;  // invalidates any cached copy of its pixels
}

__declspec(dllexport) void __stdcall gbh_AssignPalette(void* texture, int palette) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_AssignPalette) {
        Backend<void(__stdcall*)(void*, int)>(g_p_gbh_AssignPalette)(texture, palette);
        return;
    }
    if (!texture) return;
    TextureRecord* record = static_cast<TextureRecord*>(texture);
    record->palette = static_cast<uint16_t>(palette);
    record->paletteLow = static_cast<uint8_t>(palette);
}

__declspec(dllexport) void __stdcall gbh_RegisterPalette(int index, unsigned* palette) {
    gta2dx9::StorePalette(index, palette);
    if (Proxying() && g_p_gbh_RegisterPalette) {
        Backend<void(__stdcall*)(int, unsigned*)>(g_p_gbh_RegisterPalette)(index, palette);
    }
}

__declspec(dllexport) void __stdcall gbh_FreePalette(int index) {
    // We hold a pointer into the game's palette page rather than a copy, so this
    // is where it stops being safe to read.
    gta2dx9::ForgetPalette(index);
    if (Proxying() && g_p_gbh_FreePalette) Backend<void(__stdcall*)(int)>(g_p_gbh_FreePalette)(index);
}

__declspec(dllexport) unsigned __stdcall gbh_ConvertColour(unsigned r, unsigned g, unsigned b) {
    if (Proxying() && g_p_gbh_ConvertColour) {
        return Backend<unsigned(__stdcall*)(unsigned, unsigned, unsigned)>(g_p_gbh_ConvertColour)(r, g, b);
    }
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3);  // 5:6:5
}

__declspec(dllexport) void* __stdcall gbh_GetGlobals() {
    if (Proxying() && g_p_gbh_GetGlobals) return Backend<void*(__stdcall*)()>(g_p_gbh_GetGlobals)();
    return &g_globals;
}

__declspec(dllexport) int __stdcall gbh_GetUsedCache(int bank) {
    if (Proxying() && g_p_gbh_GetUsedCache) return Backend<int(__stdcall*)(int)>(g_p_gbh_GetUsedCache)(bank);
    return 0;
}

// Not an opaque handle: the game passes the return value straight back to
// gbh_BlitImage as an index into the image table (gta2.exe!FUN_00453020), and
// the original returns -1 on failure.
__declspec(dllexport) void* __stdcall gbh_LoadImage(void* spec) {
    if (Proxying() && g_p_gbh_LoadImage) return Backend<void*(__stdcall*)(void*)>(g_p_gbh_LoadImage)(spec);
    const int index = g_world.GetOverlay().LoadImage(spec);
    return reinterpret_cast<void*>(static_cast<intptr_t>(index));
}

// ---------------------------------------------------------------------------
// The screen-space stream: HUD, menus and sprites.
//
// GTA2 transforms these itself and hands over D3DFVF_XYZRHW-style vertices, so
// they cannot join the world mesh. Ignoring them - which is what this DLL used
// to do - is why the menus, the HUD and every car and pedestrian were missing.
// They are replayed as a 2D pass over the world instead.
// ---------------------------------------------------------------------------

// Sprites - cars, pedestrians, powerups - and the 2D UI share this entry point,
// so they are told apart by which call site reached it: the object draw
// (FUN_004be060) is the only producer of world sprites. Those are placed as real
// 3D geometry from the world coordinates the game itself computed; the rest is
// genuine 2D and goes to the screen-space pass.
namespace {
// GTA2DX9_LOG_SCREEN_QUADS=1: each call site of the 2D stream outside the HUD pass and the object
// draw (return address, flags, the quad's box, its texture's size), once per site. A probe.
void ProbeScreenQuad(const void* ret, unsigned flags, const void* texture, const float* v) {
    static int on = -1;
    if (on < 0) { char buf[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_LOG_SCREEN_QUADS", buf, sizeof buf) && buf[0] == '1'; }
    if (!on || !v || gta2dx9::HudPassActive()) return;
    const TextureRecord* record = static_cast<const TextureRecord*>(texture);
    float x0 = v[0], x1 = v[0], y0 = v[1], y1 = v[1];
    if (!(flags & gta2dx9::quad_flags::kExpandFromTexture)) {
        for (int i = 1; i < 4; ++i) {
            const float* c = v + i * 8;
            x0 = (std::min)(x0, c[0]); x1 = (std::max)(x1, c[0]); y0 = (std::min)(y0, c[1]); y1 = (std::max)(y1, c[1]);
        }
    }
    static uint64_t seen[128];
    static int count = 0, big = 0;
    const uint64_t key = (static_cast<uint64_t>(reinterpret_cast<uintptr_t>(ret)) << 32) | (flags & 0xFFFFFF);
    bool known = false;
    for (int i = 0; i < count; ++i) known = known || seen[i] == key;
    const bool tall = y1 - y0 > 40.0f && big < 60;
    if (known && !tall) return;
    if (!known && count < 128) seen[count++] = key;
    if (tall) ++big;
    gta2dx9::Log("screen quad: site %p flags %06X box %.0f-%.0f x %.0f-%.0f texture %dx%d z %.3f%s", ret, flags & 0xFFFFFF, x0, x1, y0, y1,
                 record ? record->width : -1, record ? record->height : -1, v[2], tall ? " (tall)" : "");
}
}  // namespace

__declspec(dllexport) void __stdcall gbh_DrawQuad(unsigned flags, void* texture, float* vertices,
                                                  unsigned char shade) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_DrawQuad) {
        Backend<void(__stdcall*)(unsigned, void*, float*, unsigned char)>(g_p_gbh_DrawQuad)(
            flags, texture, vertices, shade);
        return;
    }
    if (game::IsObjectDraw(_ReturnAddress())) {
        // A car's lamps, drawn apart from its body. Lights take their place when
        // the car lamp category is on; otherwise the quad is laid on the body.
        // See kSynthCarLamp and LiveGeometry::AddSprite.
        const bool lamps =
            reinterpret_cast<uintptr_t>(_ReturnAddress()) == game::kObjectDrawLampsReturn;
        if (lamps && gta2dx9::SyntheticCarLampsReplaceQuads()) return;
        g_world.Live().AddSprite(flags, texture, vertices, 4, lamps);
        return;
    }
    ProbeScreenQuad(_ReturnAddress(), flags, texture, vertices);
    if (reinterpret_cast<uintptr_t>(_ReturnAddress()) == gta2dx9::kScreenSpriteReturn) {
        const bool pop = gta2dx9::HudPassTakeScorePop();
        g_world.GetOverlay().MarkScorePop(pop && !gta2dx9::HudPassActive());
    }
    g_world.GetOverlay().Quad(flags, texture, vertices, shade);
}

// The original ignores the extra argument and shares gbh_DrawQuad's body.
__declspec(dllexport) void __stdcall gbh_DrawQuadClipped(unsigned flags, void* texture,
                                                         float* vertices, unsigned char shade,
                                                         int clip) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_DrawQuadClipped) {
        Backend<void(__stdcall*)(unsigned, void*, float*, unsigned char, int)>(
            g_p_gbh_DrawQuadClipped)(flags, texture, vertices, shade, clip);
        return;
    }
    if (game::IsObjectDraw(_ReturnAddress())) {
        // A car's lamps, drawn apart from its body. Lights take their place when
        // the car lamp category is on; otherwise the quad is laid on the body.
        // See kSynthCarLamp and LiveGeometry::AddSprite.
        const bool lamps =
            reinterpret_cast<uintptr_t>(_ReturnAddress()) == game::kObjectDrawLampsReturn;
        if (lamps && gta2dx9::SyntheticCarLampsReplaceQuads()) return;
        g_world.Live().AddSprite(flags, texture, vertices, 4, lamps);
        return;
    }
    ProbeScreenQuad(_ReturnAddress(), flags, texture, vertices);
    if (reinterpret_cast<uintptr_t>(_ReturnAddress()) == gta2dx9::kScreenSpriteReturn) {
        const bool pop = gta2dx9::HudPassTakeScorePop();
        g_world.GetOverlay().MarkScorePop(pop && !gta2dx9::HudPassActive());
    }
    g_world.GetOverlay().Quad(flags, texture, vertices, shade);
}

// Not UI at all: the only caller is FUN_0046c210, the triangular half-wall of a
// partial block, so this is map geometry and belongs in the world.
__declspec(dllexport) void __stdcall gbh_DrawTriangle(unsigned flags, void* texture,
                                                      float* vertices, unsigned char shade) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_DrawTriangle) {
        Backend<void(__stdcall*)(unsigned, void*, float*, unsigned char)>(g_p_gbh_DrawTriangle)(
            flags, texture, vertices, shade);
        return;
    }
    // World geometry, and the static mesh already builds it, so the stream is
    // ignored exactly the way gbh_DrawTile is - but it is the only place the
    // awkward block shapes show their real corners, so they are logged.
    (void)flags; (void)texture; (void)vertices; (void)shade;
    g_world.CheckDrawnShape(3);
}

__declspec(dllexport) void __stdcall gbh_DrawFlatRect(float* vertices, unsigned colour) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_DrawFlatRect) {
        Backend<void(__stdcall*)(float*, unsigned)>(g_p_gbh_DrawFlatRect)(vertices, colour);
        return;
    }
    g_world.GetOverlay().FlatRect(vertices, colour);
}

// ---------------------------------------------------------------------------
// Lighting.
//
// The one part of the gbh_* interface that is genuinely world space. GTA2 works
// out every light in the frame itself - map lamps, traffic lights, headlights -
// and lists them here in tile coordinates. The original renderer used them for
// per-vertex lighting; we hand them to RTX Remix as real lights instead.
// ---------------------------------------------------------------------------

// Opens the frame's list. Only called during a world render, and only when the
// game's own `lighting` option is on.
__declspec(dllexport) void __stdcall gbh_ResetLights() {
    if (Proxying() && g_p_gbh_ResetLights) {
        Backend<void(__stdcall*)()>(g_p_gbh_ResetLights)();
        return;
    }
    gta2dx9::LightsBeginCollect();
}

// One 20-byte descriptor. Decoded in remix_lights.cpp; the layout is in
// docs/lighting-analysis.md.
__declspec(dllexport) void __stdcall gbh_AddLight(void* descriptor) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_AddLight) {
        Backend<void(__stdcall*)(void*)>(g_p_gbh_AddLight)(descriptor);
        return;
    }
    gta2dx9::LightsAddRaw(descriptor);
}

__declspec(dllexport) void __stdcall gbh_SetAmbient(float ambient) {
    if (Proxying() && g_p_gbh_SetAmbient) {
        Backend<void(__stdcall*)(float)>(g_p_gbh_SetAmbient)(ambient);
        return;
    }
    gta2dx9::LightsSetAmbient(ambient);
}

// Floats, not ints. The game's only call site builds them with fild/fstp at
// gta2.exe!0x004CAF1F and passes gbh_SetWindow(0.0f, 0.0f, width-1, height-1).
// Declared as ints, 639.0f arrives as 1142312960, which NoteWindow rejected as
// out of range - so this call had never once told the overlay anything, and the
// menu was laid out to a default that happened to be right until a level had
// been played.
// Called by our video device proxy when GTA2 clears its screen.
//
// The menu paints incrementally and clears only when it wants a repaint, so this
// is the only moment the 2D layer may be discarded. The proxy is a separate DLL
// - it wears the game's videoname - so the two are joined by this one export
// rather than by sharing state.
extern "C" __declspec(dllexport) void __stdcall gta2dx9_NoteScreenClear() {
    g_world.NoteScreenClear();
}

__declspec(dllexport) void __stdcall gbh_SetWindow(float a, float b, float c, float d) {
    if (Proxying() && g_p_gbh_SetWindow) {
        Backend<void(__stdcall*)(float, float, float, float)>(g_p_gbh_SetWindow)(a, b, c, d);
        return;
    }
    g_world.GetOverlay().NoteWindow(a, b, c, d);
}

__declspec(dllexport) void __stdcall gbh_InitImageTable(int count) {
    if (Proxying() && g_p_gbh_InitImageTable) {
        Backend<void(__stdcall*)(int)>(g_p_gbh_InitImageTable)(count);
        return;
    }
    g_world.GetOverlay().InitImageTable(count);
}

__declspec(dllexport) void __stdcall gbh_FreeImageTable() {
    if (Proxying() && g_p_gbh_FreeImageTable) { Backend<void(__stdcall*)()>(g_p_gbh_FreeImageTable)(); return; }
    g_world.GetOverlay().FreeImageTable();
}

// Returns an int, as the original does: the front end decides whether to draw
// the second half of its background on it. See Overlay::BlitImage.
__declspec(dllexport) int __stdcall gbh_BlitImage(int image, int srcX1, int srcY1, int srcX2,
                                                  int srcY2, int dstX, int dstY) {
    gta2dx9::FrameLogHookScope frameLogScope;
    if (Proxying() && g_p_gbh_BlitImage) {
        return Backend<int(__stdcall*)(int, int, int, int, int, int, int)>(g_p_gbh_BlitImage)(
            image, srcX1, srcY1, srcX2, srcY2, dstX, dstY);
    }
    return g_world.GetOverlay().BlitImage(image, srcX1, srcY1, srcX2, srcY2, dstX, dstY);
}

__declspec(dllexport) void __stdcall DrawLine(int x1, int y1, int x2, int y2, int colour) {
    if (Proxying() && g_p_DrawLine) {
        Backend<void(__stdcall*)(int, int, int, int, int)>(g_p_DrawLine)(x1, y1, x2, y2, colour);
        return;
    }
    g_world.GetOverlay().Line(x1, y1, x2, y2, static_cast<uint32_t>(colour));
}

__declspec(dllexport) void __stdcall gbh_Plot(int x, int y, int colour, int spare) {
    if (Proxying() && g_p_gbh_Plot) {
        Backend<void(__stdcall*)(int, int, int, int)>(g_p_gbh_Plot)(x, y, colour, spare);
        return;
    }
    g_world.GetOverlay().Line(x, y, x + 1, y, static_cast<uint32_t>(colour));
}

// The remaining entry points either drive the screen-space draw stream, which is
// unusable for path tracing, or the software UI surface we do not present.
#define PASSTHROUGH_0(name)                                                    \
    __declspec(dllexport) void __stdcall name() {                              \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)()>(g_p_##name)(); \
    }
#define PASSTHROUGH_1(name, T0)                                                \
    __declspec(dllexport) void __stdcall name(T0 a) {                          \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0)>(g_p_##name)(a); \
    }
#define PASSTHROUGH_2(name, T0, T1)                                            \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b) {                    \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1)>(g_p_##name)(a, b); \
    }
#define PASSTHROUGH_3(name, T0, T1, T2)                                        \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b, T2 c) {              \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1, T2)>(g_p_##name)(a, b, c); \
    }
#define PASSTHROUGH_4(name, T0, T1, T2, T3)                                    \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b, T2 c, T3 d) {        \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1, T2, T3)>(g_p_##name)(a, b, c, d); \
    }
#define PASSTHROUGH_5(name, T0, T1, T2, T3, T4)                                \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b, T2 c, T3 d, T4 e) {  \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1, T2, T3, T4)>(g_p_##name)(a, b, c, d, e); \
    }
#define PASSTHROUGH_6(name, T0, T1, T2, T3, T4, T5)                            \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b, T2 c, T3 d, T4 e, T5 f) { \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1, T2, T3, T4, T5)>(g_p_##name)(a, b, c, d, e, f); \
    }
#define PASSTHROUGH_7(name, T0, T1, T2, T3, T4, T5, T6)                        \
    __declspec(dllexport) void __stdcall name(T0 a, T1 b, T2 c, T3 d, T4 e, T5 f, T6 g) { \
        if (Proxying() && g_p_##name) Backend<void(__stdcall*)(T0, T1, T2, T3, T4, T5, T6)>(g_p_##name)(a, b, c, d, e, f, g); \
    }

// gbh_DrawTilePart shares gbh_DrawTile's implementation in the original, so it
// is world geometry too and is ignored for the same reason.
PASSTHROUGH_4(gbh_DrawTilePart, unsigned, void*, float*, unsigned char)
PASSTHROUGH_1(gbh_PrintBitmap, void*)
PASSTHROUGH_0(gbh_SetColourDepth)
PASSTHROUGH_1(ConvertColourBank, int)
PASSTHROUGH_3(MakeScreenTable, void*, unsigned, int)
PASSTHROUGH_5(SetShadeTableA, int, int, int, int, int)
PASSTHROUGH_6(gbh_BlitBuffer, int, int, int, int, int, int)
PASSTHROUGH_2(gbh_Convert16BitGraphic, int, int)

}  // extern "C"

// The original renderer's blit, for plugins that patch it.
//
// Plugins written for the original game patch d3ddll.dll as well as gta2.exe:
// when a module of that name loads they find "89 7C 24 28 89 74 24 2C" in it -
// two stores in the original gbh_BlitImage - and hook it to rescale the front
// end's backgrounds. At least one widely used one takes the first match without
// checking there is one, so a d3ddll.dll that is not the original - this one,
// under that name - has it read through a null pointer, and the game dies on
// boot before this DLL's DllMain even runs.
//
// So the sequence is here, once, in a function nothing calls. The plugin finds
// it, hooks it, and carries on; the hook does nothing, which is right, because
// the blit it was correcting is the original renderer's, and this renderer
// rescales the front end itself (Overlay::BlitImage).
//
// Kept referenced so the linker cannot drop it, and counted at attach: if the
// compiler ever emits the same two stores in real code ahead of this, a plugin
// would patch that instead, and the log says so.
#ifdef _MSC_VER
extern "C" __declspec(naked) void OriginalBlitStores() {
    __asm {
        mov dword ptr [esp + 0x28], edi
        mov dword ptr [esp + 0x2C], esi
        ret
    }
}
#else
extern "C" void OriginalBlitStores();
__asm__(
    ".text\n"
    ".intel_syntax noprefix\n"
    ".globl _OriginalBlitStores\n"
    "_OriginalBlitStores:\n"
    "    mov dword ptr [esp + 0x28], edi\n"
    "    mov dword ptr [esp + 0x2C], esi\n"
    "    ret\n"
    ".att_syntax prefix\n"
    );
#endif
extern "C" void (*volatile g_originalBlitStores)() = OriginalBlitStores;

namespace {

// How often the pattern occurs in this DLL's code, and whether the first
// occurrence is the copy above - which is what a plugin will patch.
void CheckOriginalBlitStores(HMODULE module) {
    const uint8_t* base = reinterpret_cast<const uint8_t*>(module);
    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const IMAGE_NT_HEADERS* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const uint8_t* begin = base + nt->OptionalHeader.BaseOfCode;
    const size_t size = nt->OptionalHeader.SizeOfCode;
    static const uint8_t kPattern[] = {0x89, 0x7C, 0x24, 0x28, 0x89, 0x74, 0x24, 0x2C};
    int count = 0;
    const uint8_t* first = nullptr;
    for (size_t i = 0; i + sizeof(kPattern) <= size; ++i) {
        if (memcmp(begin + i, kPattern, sizeof(kPattern)) == 0) {
            if (!first) first = begin + i;
            ++count;
        }
    }
    const uint8_t* copy = reinterpret_cast<const uint8_t*>(g_originalBlitStores);
    // A jump where the copy starts is a plugin's hook: it got there first, which
    // is the whole point.
    if (copy[0] == 0xE9 && count == 0) {
        Log("a plugin hooked the original blit's stores here, as intended");
        return;
    }
    if (count == 1 && first == copy) return;
    Log("original blit stores: pattern found %d time(s), first %s the copy - a plugin "
        "would patch live code", count, first == copy ? "is" : "is NOT");
}

}  // namespace

// plugin_draw.h, for plugin_d3d6.cpp, which cannot see the overlay's headers.
namespace gta2dx9 {
int PluginImageCreate(int width, int height, const uint32_t* argb) {
    return g_world.GetOverlay().CreatePluginImage(width, height, argb);
}
void PluginImageUpdate(int id, int width, int height, const uint32_t* argb) {
    g_world.GetOverlay().UpdatePluginImage(id, width, height, argb);
}
void PluginImageRelease(int id) { g_world.GetOverlay().ReleasePluginImage(id); }
void PluginDraw(PluginPrimitive type, const PluginVertex* vertices, int count, int image,
                bool additive, bool linear) {
    g_world.GetOverlay().PluginPrimitives(type, vertices, count, image, additive, linear);
}
}  // namespace gta2dx9

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        // The GCC build's stand-in for __try; nothing on MSVC. See compat.h.
        gta2dx9::SehCompatInstall();
        g_self = module;
        DisableThreadLibraryCalls(module);
        gta2dx9::OpenLog();
        Log("gta2dx9.dll attached to pid %lu, loaded at %p", GetCurrentProcessId(), static_cast<void*>(module));
        CheckOriginalBlitStores(module);
        // Before any plugin can look for the original renderer's device.
        gta2dx9::PluginD3D6Init(module);
    } else if (reason == DLL_PROCESS_DETACH) {
        gta2dx9::CloseLog();
    }
    return TRUE;
}
