#include "settings.h"

#include "debug_overlay.h"
#include "frame_limiter.h"
#include "hud_pass.h"
#include "live_geometry.h"
#include "log.h"
#include "overlay.h"
#include "remix_lights.h"
#include "synthetic_lights.h"
#include "texture_store.h"
#include "time_of_day.h"
#include "view_modes.h"
#include "voice_over.h"
#include "gibs.h"
#include "world_view.h"

#include "../../src/renderer.h"
#include "../../src/world_mesh.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace gta2dx9 {
namespace {

char g_path[MAX_PATH] = "gta2dx9_settings.ini";
bool g_dirty = false;

// One table, walked in both directions. Adding a setting means adding a line
// here and nothing else; a save/load pair that can disagree is the usual way
// these files rot.
struct FloatField {
    const char* section;
    const char* key;
    float* value;
};
struct BoolField {
    const char* section;
    const char* key;
    bool* value;
};
struct IntField {
    const char* section;
    const char* key;
    int* value;
};

// Built fresh each call: the settings live in their owning modules, and taking
// pointers once at startup would break the moment one of them reallocated.
void Fields(FloatField** floats, int* floatCount, BoolField** bools, int* boolCount,
            IntField** ints, int* intCount) {
    static FloatField f[160];
    static BoolField b[80];
    static IntField i[48];
    int nf = 0, nb = 0, ni = 0;

    RemixLightSettings& ls = LightsSettings();
    b[nb++] = {"lights", "Enabled", &ls.enabled};
    b[nb++] = {"lights", "InjectStatic", &ls.injectStatic};
    b[nb++] = {"lights", "InjectMoving", &ls.injectMoving};
    b[nb++] = {"lights", "AmbientFill", &ls.ambientFill};
    f[nf++] = {"lights", "Brightness", &ls.radianceScale};
    f[nf++] = {"lights", "MovingScale", &ls.movingScale};
    f[nf++] = {"lights", "ReferenceRadius", &ls.referenceRadius};
    f[nf++] = {"lights", "RadiusExponent", &ls.radiusExponent};
    f[nf++] = {"lights", "Saturation", &ls.saturation};
    f[nf++] = {"lights", "EmitterRadius", &ls.emitterRadius};
    f[nf++] = {"lights", "MinIntensity", &ls.minIntensity};
    f[nf++] = {"lights", "AmbientFillScale", &ls.ambientFillScale};
    f[nf++] = {"lights", "NightSkyFill", &ls.nightSkyFill};
    f[nf++] = {"lights", "DuskFillDegrees", &ls.duskFillDeg};
    f[nf++] = {"lights", "DayBounceFill", &ls.dayBounceFill};
    f[nf++] = {"lights", "ConeSoftness", &ls.coneSoftness};
    f[nf++] = {"lights", "BuriedLift", &ls.buriedLift};
    f[nf++] = {"lights", "PoolConeDegrees", &ls.poolConeDeg};

    for (int c = 0; c < kGameLightClassCount; ++c) {
        // The section name is the class name, so the file reads as
        // [maplights.Street] Enabled / DaylightGate / GateOffAbove / GateOnBelow.
        static char sections[kGameLightClassCount][32];
        _snprintf(sections[c], sizeof(sections[c]) - 1, "maplights.%s", GameLightClassName(c));
        sections[c][sizeof(sections[c]) - 1] = '\0';
        GameLightClassSettings& gc = ls.gameClass[c];
        b[nb++] = {sections[c], "Enabled", &gc.enabled};
        b[nb++] = {sections[c], "DaylightGate", &gc.gate.enabled};
        f[nf++] = {sections[c], "GateOffAbove", &gc.gate.offAboveDeg};
        f[nf++] = {sections[c], "GateOnBelow", &gc.gate.onBelowDeg};
    }

    TimeOfDaySettings& tod = TimeOfDay();
    b[nb++] = {"timeofday", "Enabled", &tod.enabled};
    b[nb++] = {"timeofday", "Paused", &tod.paused};
    b[nb++] = {"timeofday", "RotationClockwise", &tod.rotationClockwise};
    b[nb++] = {"timeofday", "ClearSky", &tod.clearSky};
    f[nf++] = {"timeofday", "StartHour", &tod.startHour};
    f[nf++] = {"timeofday", "MinutesPerSecond", &tod.minutesPerSecond};
    f[nf++] = {"timeofday", "LightsOffHour", &tod.lightsOffHour};
    f[nf++] = {"timeofday", "LightsOnHour", &tod.lightsOnHour};
    f[nf++] = {"timeofday", "LightsFadeMinutes", &tod.lightsFadeMinutes};
    f[nf++] = {"timeofday", "Latitude", &tod.latitudeDeg};
    f[nf++] = {"timeofday", "Declination", &tod.declinationDeg};
    f[nf++] = {"timeofday", "RotationOffset", &tod.rotationOffsetDeg};
    f[nf++] = {"timeofday", "ElevationOffset", &tod.elevationOffsetDeg};
    f[nf++] = {"timeofday", "PushIntervalMs", &tod.pushIntervalMs};

    f[nf++] = {"sound", "EngineVolumePercent", &EngineVolumePercent()};
    b[nb++] = {"sound", "RadioReception", &RadioReceptionEffect()};

    // The menu's own scale. 0 means follow the display.
    f[nf++] = {"ui", "Scale", &DebugMenuUiScale()};

    // The chase and first-person views. See view_modes.h.
    ViewModeSettings& vm = ViewModes();
    i[ni++] = {"camera", "Mode", &vm.mode};
    i[ni++] = {"camera", "ToggleKey", &vm.toggleKey};
    b[nb++] = {"camera", "MouseLook", &vm.mouseLook};
    f[nf++] = {"camera", "MouseSensitivity", &vm.mouseSensitivity};
    f[nf++] = {"camera", "MouseMaxStep", &vm.mouseMaxStep};
    f[nf++] = {"camera", "TurnSpeed", &vm.turnSpeed};
    f[nf++] = {"camera", "TurnRateFoot", &vm.turnRateFoot};
    f[nf++] = {"camera", "TurnRateCar", &vm.turnRateCar};
    f[nf++] = {"camera", "FirstCarRate", &vm.fpCarRate};
    f[nf++] = {"camera", "PedTurnRate", &vm.pedDrawnTurnRate};
    f[nf++] = {"camera", "PedTurnEase", &vm.pedDrawnEase};
    f[nf++] = {"camera", "FirstTurnKeyStart", &vm.fpTurnKeyStart};
    f[nf++] = {"camera", "FirstTurnKeyRamp", &vm.fpTurnKeyRamp};
    f[nf++] = {"camera", "FirstTurnKeyDecay", &vm.fpTurnKeyDecay};
    b[nb++] = {"camera", "ThirdOrbitFollow", &vm.tpOrbitFollow};
    f[nf++] = {"camera", "ThirdRecentreDelay", &vm.tpRecentreDelay};
    f[nf++] = {"camera", "ThirdRecentreTau", &vm.tpRecentreTau};
    f[nf++] = {"camera", "ThirdRecentreRate", &vm.tpRecentreRate};
    f[nf++] = {"camera", "ThirdFollowTauWalk", &vm.tpFollowTauWalk};
    f[nf++] = {"camera", "ThirdFollowTauRun", &vm.tpFollowTauRun};
    f[nf++] = {"camera", "ThirdFollowDelay", &vm.tpFollowDelay};
    f[nf++] = {"camera", "FirstSmooth", &vm.fpSmooth};
    f[nf++] = {"camera", "FirstFollowRate", &vm.fpFollowRate};
    b[nb++] = {"camera", "NavMap", &vm.navMap};
    b[nb++] = {"camera", "AimAssist", &vm.aimAssist};   // FIX-AIM-1
    f[nf++] = {"camera", "NavDeadband", &vm.navDeadband};
    f[nf++] = {"camera", "NavLatency", &vm.navLatency};
    i[ni++] = {"camera", "NavTurnSign", &vm.navTurnSign};
    f[nf++] = {"camera", "FirstTurnKeyRate", &vm.fpTurnKeyRate};
    f[nf++] = {"camera", "ThirdOrbitTau", &vm.tpOrbitTau};
    f[nf++] = {"camera", "ThirdChaseTau", &vm.tpChaseTau};
    b[nb++] = {"camera", "InvertY", &vm.invertY};
    f[nf++] = {"camera", "ThirdDistance", &vm.tpDistance};
    f[nf++] = {"camera", "ThirdHeight", &vm.tpHeight};
    f[nf++] = {"camera", "ThirdLookAhead", &vm.tpLookAhead};
    f[nf++] = {"camera", "ThirdLookHeight", &vm.tpLookHeight};
    f[nf++] = {"camera", "ThirdFootScale", &vm.tpFootScale};
    f[nf++] = {"camera", "ThirdFov", &vm.tpFov};
    f[nf++] = {"camera", "ThirdFollow", &vm.tpFollow};
    f[nf++] = {"camera", "ThirdReturnDelay", &vm.tpReturnDelay};
    b[nb++] = {"camera", "ThirdCollide", &vm.tpCollide};
    f[nf++] = {"camera", "FirstEyeFoot", &vm.fpEyeFoot};
    f[nf++] = {"camera", "FirstEyeCar", &vm.fpEyeCar};
    f[nf++] = {"camera", "FirstForwardFoot", &vm.fpForwardFoot};
    f[nf++] = {"camera", "FirstForwardCar", &vm.fpForwardCar};
    f[nf++] = {"camera", "FirstEyeCabin", &vm.fpEyeCabin};
    f[nf++] = {"camera", "FirstBehindScreen", &vm.fpBehindScreen};
    f[nf++] = {"camera", "FirstSeatCar", &vm.fpSeatCar};
    f[nf++] = {"camera", "FirstFov", &vm.fpFov};
    b[nb++] = {"camera", "FirstHideOwnBody", &vm.fpHideOwnBody};
    f[nf++] = {"camera", "FirstReturnDelay", &vm.fpReturnDelay};
    b[nb++] = {"camera", "UprightPeds", &vm.uprightPeds};
    f[nf++] = {"camera", "GameViewScale", &vm.gameViewScale};
    f[nf++] = {"camera", "ThirdShoulder", &vm.tpShoulder};
    f[nf++] = {"camera", "ThirdPullBack", &vm.tpPullBack};
    f[nf++] = {"camera", "ThirdLean", &vm.tpLean};
    f[nf++] = {"camera", "FirstHeadBob", &vm.fpHeadBob};
    f[nf++] = {"camera", "FirstLean", &vm.fpLean};
    f[nf++] = {"camera", "ReferenceSpeed", &vm.referenceSpeed};
    f[nf++] = {"camera", "SpeedFov", &vm.speedFov};
    f[nf++] = {"camera", "ImpactShake", &vm.impactShake};
    i[ni++] = {"camera", "MotionBlur", &vm.motionBlur};
    f[nf++] = {"camera", "GroundCarHeight", &vm.groundCarHeight};
    f[nf++] = {"camera", "GroundCarShoulder", &vm.groundCarShoulder};
    b[nb++] = {"camera", "GroundCarWheels", &vm.groundCarWheels};
    b[nb++] = {"camera", "GroundPedFigures", &vm.groundPedFigures};
    b[nb++] = {"camera", "GroundModels", &vm.groundModels};
    f[nf++] = {"camera", "TransitionSeconds", &vm.transitionSeconds};
    f[nf++] = {"camera", "TransitionArc", &vm.transitionArc};

    EffectSpriteSettings& fx = EffectSprites();
    f[nf++] = {"effectsprites", "EdgeLuma", &fx.edgeLuma};
    f[nf++] = {"effectsprites", "FaintLuma", &fx.faintLuma};
    f[nf++] = {"effectsprites", "CutoutGain", &fx.cutoutGain};

    *floats = f;
    *floatCount = nf;
    *bools = b;
    *boolCount = nb;
    *ints = i;
    *intCount = ni;
}

char* Trim(char* s) {
    while (*s == ' ' || *s == '\t') ++s;
    char* e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = '\0';
    return s;
}

// FIX-STABILITY-2 (settings-ini-silently-overrides-gta2dx9-ini): every value this file holds, as the
// text the Save button writes, in the order it writes them. Save, the load-time override log and the
// "only what the user changed" rule all read this one list.
struct Value {
    const char* section;
    const char* key;
    std::string text;
};

std::vector<Value> CurrentValues() {
    FloatField* f;
    BoolField* b;
    IntField* i;
    int nf, nb, ni;
    Fields(&f, &nf, &b, &nb, &i, &ni);
    std::vector<Value> out;
    char text[64];
    auto add = [&](const char* section, const char* key, const char* fmt, auto v) {
        _snprintf(text, sizeof(text) - 1, fmt, v);
        text[sizeof(text) - 1] = '\0';
        out.push_back({section, key, text});
    };
    for (int n = 0; n < nb; ++n) add(b[n].section, b[n].key, "%d", *b[n].value ? 1 : 0);
    for (int n = 0; n < nf; ++n) add(f[n].section, f[n].key, "%.5f", static_cast<double>(*f[n].value));
    for (int n = 0; n < ni; ++n) add(i[n].section, i[n].key, "%d", *i[n].value);
    // Things that live outside a settings struct.
    add("render", "SpawnOffscreen", "%d", SpawnOffscreen() ? 1 : 0);
    add("render", "Blood", "%d", Blood() ? 1 : 0);
    add("render", "Gibs", "%d", Gibs() ? 1 : 0);
    add("render", "GibsCar", "%d", GibsCar() ? 1 : 0);
    add("render", "OwnCarLamps", "%d", OwnCarLamps() ? 1 : 0);
    add("render", "SpriteConform", "%d", SpriteConform() ? 1 : 0);
    add("render", "SpriteHeight", "%.4f", static_cast<double>(SpriteHeight()));
    add("render", "SpriteRoll", "%.4f", static_cast<double>(SpriteRoll()));
    add("render", "SpriteLift", "%.4f", static_cast<double>(SpriteLift()));
    add("render", "SpriteStackStep", "%.4f", static_cast<double>(SpriteStackStep()));
    add("render", "SpriteFeather", "%.4f", static_cast<double>(SpriteFeather()));
    add("render", "AlphaMode", "%s", gta2::GetAlphaMode() == gta2::AlphaMode::Blend ? "blend" : "test");
    add("render", "AlphaRef", "%d", gta2::GetAlphaRef());
    add("render", "HudFit", "%s",
        HudFit() == HudFitMode::Stretch ? "stretch" : HudFit() == HudFitMode::Widescreen ? "widescreen" : "fit");
    add("render", "HideStageArrow", "%d", HideStageArrow() ? 1 : 0);
    add("render", "FpsCap", "%.4f", static_cast<double>(FrameLimitFps()));
    add("render", "DumpTextures", "%d", TextureDumping() ? 1 : 0);
    add("render", "CloseHoles", "%d", CloseHoles() ? 1 : 0);
    add("render", "CloseHoleMax", "%d", CloseHoleMax());
    add("render", "WorldSeal", "%d", gta2::WorldSeal() ? 1 : 0);
    add("render", "WaterUvBlocks", "%.4f", static_cast<double>(gta2::WaterUvBlocks()));
    add("render", "RiverbedDepth", "%.4f", static_cast<double>(gta2::RiverbedDepth()));
    const EffectSpriteMode mode = EffectSprites().mode;
    add("render", "EffectSprites", "%s",
        mode == EffectSpriteMode::Additive ? "additive" : (mode == EffectSpriteMode::Cutout ? "cutout" : "off"));
    return out;
}

// What gta2dx9.ini (and the code's defaults) made of every value, before this file was first read.
std::vector<Value> g_iniValues;
bool g_haveIniValues = false;

const Value* FindValue(const std::vector<Value>& values, const char* section, const char* key) {
    for (const Value& v : values) {
        if (!_stricmp(v.section, section) && !_stricmp(v.key, key)) return &v;
    }
    return nullptr;
}

}  // namespace

void SettingsInit(const char* path) {
    if (path && *path) {
        strncpy(g_path, path, sizeof(g_path) - 1);
        g_path[sizeof(g_path) - 1] = '\0';
    }
}

const char* SettingsPath() { return g_path; }
bool SettingsDirty() { return g_dirty; }
void SettingsMarkDirty() { g_dirty = true; }

void SettingsSaveAll() {
    const std::vector<Value> values = CurrentValues();
    FILE* out = fopen(g_path, "w");
    if (!out) {
        Log("settings: could not write %s", g_path);
        return;
    }
    fprintf(out, "; GTA2 RTX Remix -- what the F4 menu changed.\n");
    fprintf(out, ";\n");
    fprintf(out, "; Written by the Save button, read at startup after gta2dx9.ini. Separate from it on\n");
    fprintf(out, "; purpose: deploy regenerates that one on every build, so anything saved into\n");
    fprintf(out, "; it would be lost. Where the two overlap this file wins, and the log says so per key\n");
    fprintf(out, "; ('settings override: [section] Key ini=<a> settings=<b>'). Only values that differ\n");
    fprintf(out, "; from what gta2dx9.ini and the defaults give are written, so a value you never\n");
    fprintf(out, "; changed here keeps following gta2dx9.ini. [renderer] ignore_saved_settings=1 in\n");
    fprintf(out, "; gta2dx9.ini skips this file.\n");
    fprintf(out, ";\n");
    fprintf(out, "; Per-light overrides are in gta2dx9_lights.ini and the effect categories in\n");
    fprintf(out, "; gta2dx9_effects.ini; the Save button writes all three.\n");

    const char* section = "";
    int written = 0, skipped = 0;
    for (const Value& v : values) {
        // FIX-STABILITY-2: a value equal to what the ini gives is the ini's, not the user's.
        if (g_haveIniValues) {
            const Value* ini = FindValue(g_iniValues, v.section, v.key);
            if (ini && ini->text == v.text) {
                ++skipped;
                continue;
            }
        }
        if (strcmp(section, v.section) != 0) {
            fprintf(out, "\n[%s]\n", v.section);
            section = v.section;
        }
        fprintf(out, "%s=%s\n", v.key, v.text.c_str());
        ++written;
    }
    fclose(out);

    // One button, everything saved - the three files are an implementation
    // detail and nobody should have to remember which is which.
    LightsSaveOverrides();
    SyntheticLightsSave();

    g_dirty = false;
    Log("settings: saved %s: %d value(s) changed from gta2dx9.ini, %d left to it (plus light overrides and effect "
        "settings)", g_path, written, skipped);
}

void SettingsLoadAll() {
    // FIX-STABILITY-2: what gta2dx9.ini gave, kept from the first call (the menu's Load button calls
    // this again), for the override lines below and for Save.
    const std::vector<Value> before = CurrentValues();
    if (!g_haveIniValues) {
        g_iniValues = before;
        g_haveIniValues = true;
    }
    FILE* in = fopen(g_path, "r");
    if (!in) return;   // first run

    FloatField* f;
    BoolField* b;
    IntField* i;
    int nf, nb, ni;
    Fields(&f, &nf, &b, &nb, &i, &ni);

    char sectionName[64] = "";
    char line[512];
    while (fgets(line, sizeof(line), in)) {
        char* s = Trim(line);
        if (!*s || *s == ';' || *s == '#') continue;
        if (*s == '[') {
            char* close = strchr(s, ']');
            if (!close) continue;
            *close = '\0';
            strncpy(sectionName, s + 1, sizeof(sectionName) - 1);
            sectionName[sizeof(sectionName) - 1] = '\0';
            continue;
        }
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = '\0';
        const char* key = Trim(s);
        char* value = Trim(eq + 1);

        bool handled = false;
        for (int n = 0; n < nb && !handled; ++n) {
            if (!_stricmp(sectionName, b[n].section) && !_stricmp(key, b[n].key)) {
                *b[n].value = atoi(value) != 0;
                handled = true;
            }
        }
        for (int n = 0; n < nf && !handled; ++n) {
            if (!_stricmp(sectionName, f[n].section) && !_stricmp(key, f[n].key)) {
                *f[n].value = static_cast<float>(atof(value));
                handled = true;
            }
        }
        for (int n = 0; n < ni && !handled; ++n) {
            if (!_stricmp(sectionName, i[n].section) && !_stricmp(key, i[n].key)) {
                *i[n].value = atoi(value);
                handled = true;
            }
        }
        if (handled || _stricmp(sectionName, "render") != 0) continue;

        if (!_stricmp(key, "SpawnOffscreen")) {
            SetSpawnOffscreen(atoi(value) != 0);
        } else if (!_stricmp(key, "Blood")) {
            SetBlood(atoi(value) != 0);
        } else if (!_stricmp(key, "Gibs")) {
            SetGibs(atoi(value) != 0);
        } else if (!_stricmp(key, "GibsCar")) {
            SetGibsCar(atoi(value) != 0);
        } else if (!_stricmp(key, "OwnCarLamps")) {
            SetOwnCarLamps(atoi(value) != 0);
        } else if (!_stricmp(key, "SpriteRoll")) {
            SetSpriteRoll(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "SpriteHeight")) {
            SetSpriteHeight(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "SpriteConform")) {
            SetSpriteConform(atoi(value) != 0);
        } else if (!_stricmp(key, "SpriteLift")) {
            SetSpriteLift(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "SpriteStackStep")) {
            SetSpriteStackStep(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "SpriteFeather")) {
            SetSpriteFeather(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "AlphaMode")) {
            gta2::SetAlphaMode(!_stricmp(value, "blend") ? gta2::AlphaMode::Blend
                                                         : gta2::AlphaMode::Test);
        } else if (!_stricmp(key, "AlphaRef")) {
            gta2::SetAlphaRef(atoi(value));
        } else if (!_stricmp(key, "HudFit")) {
            SetHudFit(!_stricmp(value, "stretch")      ? HudFitMode::Stretch
                      : !_stricmp(value, "widescreen") ? HudFitMode::Widescreen
                                                       : HudFitMode::Fit);
        } else if (!_stricmp(key, "HideStageArrow")) {
            SetHideStageArrow(atoi(value) != 0);
        } else if (!_stricmp(key, "FpsCap")) {
            FrameLimitSet(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "DumpTextures")) {
            SetTextureDumping(atoi(value) != 0);
        } else if (!_stricmp(key, "CloseHoles")) {
            SetCloseHoles(atoi(value) != 0);
        } else if (!_stricmp(key, "CloseHoleMax")) {
            SetCloseHoleMax(atoi(value));
        } else if (!_stricmp(key, "WorldSeal")) {
            gta2::SetWorldSeal(atoi(value) != 0);
        } else if (!_stricmp(key, "WaterUvBlocks")) {
            gta2::SetWaterUvBlocks(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "RiverbedDepth")) {
            gta2::SetRiverbedDepth(static_cast<float>(atof(value)));
        } else if (!_stricmp(key, "EffectSprites")) {
            EffectSprites().mode = !_stricmp(value, "off")
                                       ? EffectSpriteMode::Off
                                       : (!_stricmp(value, "cutout") ? EffectSpriteMode::Cutout
                                                                     : EffectSpriteMode::Additive);
        }
    }
    fclose(in);
    g_dirty = false;
    // FIX-STABILITY-2: loud, one line per key this file changed (it used to win in silence: the owner's
    // day length, frame cap and alpha mode were this file's for four relaunches of a gta2dx9.ini fix).
    int overrides = 0;
    for (const Value& v : CurrentValues()) {
        const Value* was = FindValue(before, v.section, v.key);
        if (!was || was->text == v.text) continue;
        ++overrides;
        Log("settings override: [%s] %s ini=%s settings=%s (%s wins; [renderer] ignore_saved_settings=1 skips it)",
            v.section, v.key, was->text.c_str(), v.text.c_str(), g_path);
    }
    Log("settings: loaded %s: %d value(s) differ from gta2dx9.ini%s", g_path, overrides,
        overrides ? ", see the 'settings override' lines" : "");
}

}  // namespace gta2dx9
