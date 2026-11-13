#include "time_of_day.h"

#include "log.h"
#include "remix_api.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace gta2dx9 {
namespace {

TimeOfDaySettings g_settings;
float g_hour = 2.0f;

float g_elevation = -30.0f;
float g_rotation = 0.0f;

bool  g_pushed = false;
int   g_pushes = 0;
char  g_status[128] = "not started";

LARGE_INTEGER g_frequency = {};
LARGE_INTEGER g_lastTick = {};
LARGE_INTEGER g_lastPush = {};
bool g_haveTick = false;
bool g_forcePush = false;      // set by TimeOfDayReset: push everything on the next frame
float g_loggedElevation = 1e9f;
LARGE_INTEGER g_lastPushLog = {};

// Last values actually sent, so an unchanged sky costs nothing.
float g_sentElevation = 1e9f;
float g_sentRotation = 1e9f;

constexpr float kPi = 3.14159265358979323846f;
constexpr float kDegToRad = kPi / 180.0f;
constexpr float kRadToDeg = 180.0f / kPi;

double Seconds(const LARGE_INTEGER& from, const LARGE_INTEGER& to) {
    if (!g_frequency.QuadPart) return 0.0;
    return static_cast<double>(to.QuadPart - from.QuadPart) /
           static_cast<double>(g_frequency.QuadPart);
}

void SetStatus(const char* text) {
    strncpy(g_status, text, sizeof(g_status) - 1);
    g_status[sizeof(g_status) - 1] = '\0';
}

bool Push(const char* key, float degrees) {
    char value[32];
    _snprintf(value, sizeof(value) - 1, "%.4f", degrees);
    value[sizeof(value) - 1] = '\0';
    return RemixSetConfig(key, value);
}

// The clouds. Remix's atmosphere has a cloud layer, and under it the sky, the sun's
// light and the ground are all dimmed and greyed - overcast. Switching the layer off
// leaves the clear sky and the sun at full strength. Sent when the setting changes and
// again every few seconds while it is on, in case Remix restores its own value (a level
// load, a settings reload).
float g_overcast = 0.0f;      // WEATHER-V2: quantised to 0.05
float g_dayT = -1.0f;            // 0 night .. 1 day, last pushed; -1 unknown (push now)
float g_sentOvercast = -1.0f;
bool g_skyKnown = false;
bool g_skyState = false;
bool g_skyOk = true;
LARGE_INTEGER g_lastSky = {};

bool PushText(const char* key, const char* value) { return RemixSetConfig(key, value); }

void UpdateSky(const LARGE_INTEGER& now) {
    if (!RemixApiAvailable() || !RemixApiHasAtmosphere()) {
        g_skyOk = true;
        return;
    }
    const bool want = g_settings.clearSky && g_overcast < 0.05f;
    const bool changed = !g_skyKnown || g_skyState != want || g_sentOvercast != g_overcast;
    if (!changed && (!want || Seconds(g_lastSky, now) < 5.0)) return;
    g_lastSky = now;

    // The second layer is off by default and stays off; it is named so a clear sky
    // is clear whichever layers a preset has switched on.
    const bool a = PushText("rtx.atmosphere.cloudEnabled", want ? "False" : "True");
    const bool b = want ? PushText("rtx.atmosphere.cloudLayer2Enable", "False") : true;
    // The clouds' shadow on the ground is a separate term (a voxel grid of the cloud
    // deck, rtx.atmosphere.cloudVoxelShadowsEnable) and switching the clouds off does
    // not clear it: the default deck kept shading the sun, so a clear noon was lit by
    // the sky alone, with no sun and no shadows, depending on where the sun stood and
    // how far the invisible deck had drifted (FIX-REMIX-2, pt-remix-daytime-no-sun-
    // no-shadows: one live push of cloudShadowStrength=0 brought the noon sun back).
    const bool c = PushText("rtx.atmosphere.cloudShadowStrength", want ? "0" : "1");
    g_skyOk = a && b && c;
    if (g_sentOvercast != g_overcast) {
        // WEATHER-V2 overcast: coverage from the rain-free default (0.29) toward a closed grey deck.
        char text[16];
        _snprintf(text, sizeof(text) - 1, "%.3f", 0.29f + 0.66f * g_overcast);
        text[sizeof(text) - 1] = '\0';
        PushText("rtx.atmosphere.cloudCoverageMean", text);
        Log("time of day: overcast %.2f (cloud coverage %s)", g_overcast, text);
        g_sentOvercast = g_overcast;
        g_dayT = -1.0f;   // re-push the day look with the overcast's fill, sun and shadow softness
    }
    if (changed) {
        Log("time of day: clouds %s %s", want ? "off (clear sky)" : "on",
            g_skyOk ? "set" : "refused by Remix");
    }
    g_skyKnown = true;
    g_skyState = want;
}

// The day and night looks under Remix (FIX-REMIX-2, pt-remix-day-shade-black-no-sky-
// bounce): the exposure cap that keeps the night a night (2.5) left every street in
// building shade near black by day, and the sky's diffuse fill is weak next to the sun.
// So the cap and the sky fill follow the time of day: the night values while the sun is
// well down, the day values once it is up.
//
// FIX-REMIX-3 (pt-remix-classic-lit-state-flips-after-3d-roundtrip): they used to switch
// in one frame when the sun crossed dayLookAboveDeg. The shipped clock starts at 02:00 and
// runs a game minute a second, so a few minutes into every level the whole picture jumped
// 2.5x in brightness in one frame (33 -> 115 mean luma in the filer's run), which read as
// the classic view's lighting flipping after a trip to the 3D views. Now they ramp across
// the twilight: smoothstep over kDayLookBandDeg either side of dayLookAboveDeg, pushed
// whenever a value has moved by a step the eye cannot see, and each push is logged.
constexpr float kDayLookBandDeg = 6.0f;
float g_loggedDayT = -1.0f;
int g_dayState = -1;             // -1 unknown, 0 night, 1 day: for the log only
bool g_nightHold = false;        // FIX-REMIX-NIGHT-10: auto-exposure held at full night

void PushFloat(const char* key, float value) {
    char text[32];
    _snprintf(text, sizeof(text) - 1, "%.3f", value);
    text[sizeof(text) - 1] = '\0';
    RemixSetConfig(key, text);
}

void UpdateDayLook(float elevation) {
    if (!RemixApiAvailable() || !RemixApiHasAtmosphere()) {
        g_dayT = -1.0f;
        g_dayState = -1;
        return;
    }
    const TimeOfDaySettings& s = g_settings;
    float t = (elevation - (s.dayLookAboveDeg - kDayLookBandDeg)) / (2.0f * kDayLookBandDeg);
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    t = t * t * (3.0f - 2.0f * t);
    // 1/50 of the ramp is a 2 % step of the exposure cap: below what the eye picks out.
    if (g_dayT >= 0.0f && std::fabs(t - g_dayT) < 0.02f && !(t == 0.0f && g_dayT != 0.0f) && !(t == 1.0f && g_dayT != 1.0f))
        return;
    const bool first = g_dayT < 0.0f;
    g_dayT = t;
    const float exposure = s.nightMaxExposure + (s.dayMaxExposure - s.nightMaxExposure) * t;
    const float fill = s.nightSkyFill + (s.daySkyFill - s.nightSkyFill) * t;
    if (s.dayMaxExposure > 0.0f && s.nightMaxExposure > 0.0f) PushFloat("rtx.autoExposure.maxExposure", exposure);
    if (s.daySkyFill > 0.0f && s.nightSkyFill > 0.0f) PushFloat("rtx.atmosphere.skyIndirectRadianceScale", fill * (1.0f + 0.8f * g_overcast));
    // WEATHER-V2 overcast: the sun's direct light dimmed and its shadows softened (live keys, gate 0).
    PushFloat("rtx.atmosphere.directionalLightRadianceScale", 1.0f - 0.7f * g_overcast);
    PushFloat("rtx.atmosphere.sunShadowSoftnessDeg", 0.4f + 5.0f * g_overcast);
    const int state = t >= 1.0f ? 1 : (t <= 0.0f ? 0 : 2);
    // FIX-REMIX-NIGHT-10 (owner 11 Nov: "in the 3D view the night is dark but slightly lit; in first person the world gets
    // brighter"): the renderer pushes only a CAP on Remix's auto-exposure, and the meter then adapts to the frame: a
    // first-person frame is mostly dark road and sky, so the exposure rises to the cap; a third-person frame holds the
    // lit facades, so it settles lower. The night look must not depend on the view. At full night the meter is held:
    // auto-exposure off and a fixed exposure (remix_night_fixed_exposure_tenths, 0 = the old floating meter), pushed
    // as rtx.tonemap.exposureBias = log2(exposure); through twilight and by day the meter is back on with the cap.
    if (s.nightFixedExposure > 0.0f && RemixApiAvailable()) {
        const bool hold = state == 0;
        if (first || hold != g_nightHold) {
            RemixSetConfig("rtx.autoExposure.enabled", hold ? "False" : "True");
            PushFloat("rtx.tonemap.exposureBias", hold ? std::log2(s.nightFixedExposure) : 0.0f);
            Log("time of day: night exposure %s (fixed x%.2f = bias %.2f EV, auto-exposure %s)", hold ? "held" : "released",
                s.nightFixedExposure, std::log2(s.nightFixedExposure), hold ? "off" : "on");
            g_nightHold = hold;
        }
    }
    if (first || state != g_dayState || std::fabs(t - g_loggedDayT) >= 0.25f) {
        Log("time of day: %s look (sun %.1f deg, day %.2f): exposure cap %.2f, sky fill %.2f%s",
            state == 1 ? "day" : (state == 0 ? "night" : "twilight"), elevation, t, exposure, fill, first ? " (first push)" : "");
        g_loggedDayT = t;
    }
    g_dayState = state;
}

}  // namespace

bool TimeOfDayClearSkyOk() { return g_skyOk; }

void TimeOfDaySetOvercast(float overcast) {
    overcast = overcast < 0.0f ? 0.0f : (overcast > 1.0f ? 1.0f : overcast);
    g_overcast = std::floor(overcast * 20.0f + 0.5f) / 20.0f;
}

TimeOfDaySettings& TimeOfDay() { return g_settings; }

float TimeOfDayHour() { return g_hour; }

void TimeOfDaySetHour(float hour) {
    hour = std::fmod(hour, 24.0f);
    if (hour < 0.0f) hour += 24.0f;
    g_hour = hour;
}

// A level start (and the ini load) resets the clock. Every value this file sends to
// Remix is sent only when it changes, so a value Remix dropped or replaced (the
// runtime's own defaults at a level load, a push made before the runtime answered)
// would stay wrong until the sun moved far enough or crossed the horizon: the
// classic view then ran on Remix's own exposure cap and sky fill until something
// else happened to re-send them (FIX-REMIX-3, pt-remix-classic-lit-state-flips-
// after-3d-roundtrip). So a reset forgets what was sent and the next frame pushes
// the clock's whole preset (sun, day/night look, clouds), whatever the view.
void TimeOfDayRepush(const char* why) {
    g_sentElevation = 1e9f;
    g_sentRotation = 1e9f;
    g_dayT = -1.0f;
    g_skyKnown = false;
    g_forcePush = true;
    Log("time of day: %s: the preset is pushed again (clock %05.2f, %s)", why ? why : "repush", g_hour,
        g_settings.paused ? "paused" : "running");
}

void TimeOfDayReset() {
    TimeOfDaySetHour(g_settings.startHour);
    g_sentElevation = 1e9f;
    g_sentRotation = 1e9f;
    g_dayT = -1.0f;
    g_skyKnown = false;
    g_forcePush = true;
    Log("time of day: clock reset to %05.2f (%s, %.1f game minutes per real second); the preset is pushed again",
        g_settings.startHour, g_settings.paused ? "paused" : "running", g_settings.minutesPerSecond);
}

// Where the sun is, from the standard solar position equations.
//
// With latitude phi, solar declination delta and hour angle H (zero at local
// noon, 15 degrees per hour, positive in the afternoon):
//
//     sin(altitude) = sin(phi) sin(delta) + cos(phi) cos(delta) cos(H)
//     cos(azimuth)  = (sin(delta) - sin(phi) sin(altitude)) / (cos(phi) cos(altitude))
//
// with the azimuth measured clockwise from north and mirrored about noon, which
// is what puts sunrise in the east. Nothing here is approximated: this is the
// same geometry a sundial uses, and it is why the night is as long as it is and
// why the sun barely clears the horizon in a northern winter.
void TimeOfDaySunAt(float hour, const TimeOfDaySettings& settings, float* elevationDeg,
                    float* rotationDeg) {
    const float phi = settings.latitudeDeg * kDegToRad;
    const float decl = settings.declinationDeg * kDegToRad;
    const float H = (hour - 12.0f) * 15.0f * kDegToRad;

    const float sinAlt = std::sin(phi) * std::sin(decl) +
                         std::cos(phi) * std::cos(decl) * std::cos(H);
    const float altitude = std::asin(sinAlt < -1.0f ? -1.0f : (sinAlt > 1.0f ? 1.0f : sinAlt));

    float azimuth = 0.0f;
    const float cosAlt = std::cos(altitude);
    // At the poles, and at the instant the sun is straight overhead, the azimuth
    // is undefined rather than merely awkward. Due south is the harmless answer.
    if (std::fabs(cosAlt) > 1e-5f && std::fabs(std::cos(phi)) > 1e-5f) {
        float cosAz = (std::sin(decl) - std::sin(phi) * sinAlt) / (std::cos(phi) * cosAlt);
        if (cosAz < -1.0f) cosAz = -1.0f;
        if (cosAz > 1.0f) cosAz = 1.0f;
        azimuth = std::acos(cosAz) * kRadToDeg;   // 0 = north, 180 = south
        if (H > 0.0f) azimuth = 360.0f - azimuth;  // afternoon is the western half
    } else {
        azimuth = 180.0f;
    }

    if (!settings.rotationClockwise) azimuth = 360.0f - azimuth;
    azimuth += settings.rotationOffsetDeg;
    azimuth = std::fmod(azimuth, 360.0f);
    if (azimuth < 0.0f) azimuth += 360.0f;

    float elevation = altitude * kRadToDeg + settings.elevationOffsetDeg;
    if (elevation < -90.0f) elevation = -90.0f;
    if (elevation > 90.0f) elevation = 90.0f;

    if (elevationDeg) *elevationDeg = elevation;
    if (rotationDeg) *rotationDeg = azimuth;
}

void TimeOfDayUpdate() {
    if (!g_frequency.QuadPart) QueryPerformanceFrequency(&g_frequency);

    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    if (!g_haveTick) {
        g_lastTick = now;
        g_lastPush = now;
        g_haveTick = true;
        TimeOfDaySetHour(g_settings.startHour);
    }
    const double delta = Seconds(g_lastTick, now);
    g_lastTick = now;

    UpdateSky(now);

    if (!g_settings.enabled) {
        SetStatus("off");
        return;
    }

    if (!g_settings.paused) {
        // A level load can stall a frame for seconds; letting that run the clock
        // would jump the sun across the sky on the frame the map appears.
        const double step = delta > 1.0 ? 1.0 : delta;
        TimeOfDaySetHour(g_hour +
                         static_cast<float>(step * g_settings.minutesPerSecond / 60.0));
    }

    TimeOfDaySunAt(g_hour, g_settings, &g_elevation, &g_rotation);
    UpdateDayLook(g_elevation);

    if (!RemixApiAvailable()) {
        g_pushed = false;
        SetStatus("Remix API not available; the clock runs but the sky does not move");
        return;
    }
    if (!RemixApiHasAtmosphere()) {
        g_pushed = false;
        SetStatus("off: this Remix has no atmospheric sky to move (needs Remix Plus)");
        return;
    }

    const double sincePush = Seconds(g_lastPush, now) * 1000.0;
    const bool due = g_forcePush || sincePush >= g_settings.pushIntervalMs;
    const bool moved = std::fabs(g_elevation - g_sentElevation) > 0.005f ||
                       std::fabs(g_rotation - g_sentRotation) > 0.005f;
    if (!due || !moved) return;
    g_lastPush = now;

    const bool okElevation = Push("rtx.atmosphere.sunElevation", g_elevation);
    const bool okRotation = Push("rtx.atmosphere.sunRotation", g_rotation);
    g_pushed = okElevation && okRotation;
    if (g_pushed) {
        // One line per 2 degrees of sun movement, per reset and at least every 30 s
        // while it moves, so a run's log says which sun every frame was lit by.
        if (g_forcePush || std::fabs(g_elevation - g_loggedElevation) >= 2.0f || Seconds(g_lastPushLog, now) >= 30.0) {
            Log("time of day: sun pushed: elevation %.2f, rotation %.2f (clock %05.2f, %s%s)", g_elevation, g_rotation,
                g_hour, g_settings.paused ? "paused" : "running", g_forcePush ? ", after a reset" : "");
            g_loggedElevation = g_elevation;
            g_lastPushLog = now;
        }
        g_forcePush = false;
        g_sentElevation = g_elevation;
        g_sentRotation = g_rotation;
        ++g_pushes;
        if (g_pushes == 1) {
            Log("time of day: driving rtx.atmosphere.sunElevation/sunRotation "
                "(start %05.2f, %.0f game minutes per real second)",
                g_settings.startHour, g_settings.minutesPerSecond);
        }
        SetStatus("driving the Remix sun");
    } else {
        SetStatus("SetConfigVariable was refused - is this Remix build recent enough?");
    }
}

namespace {

// Hours from `from` forward to `to`, round the clock: 0..24.
float HoursAfter(float from, float to) {
    float d = std::fmod(to - from, 24.0f);
    if (d < 0.0f) d += 24.0f;
    return d;
}

float Smooth(float t) {
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    // Smoothstep rather than a straight ramp: the ends are what the eye notices,
    // and a linear fade visibly starts and stops.
    return t * t * (3.0f - 2.0f * t);
}

}  // namespace

float DaylightGateFactorAtHour(const DaylightGate& gate, float hour) {
    if (!gate.enabled) return 1.0f;
    const float fade = (std::max)(g_settings.lightsFadeMinutes, 0.0f) / 60.0f;
    const float off = g_settings.lightsOffHour;
    const float on = g_settings.lightsOnHour;
    // Where the clock is within the lit stretch, from the on hour to the off hour.
    const float lit = HoursAfter(on, off);
    const float sinceOn = HoursAfter(on, hour);
    if (sinceOn >= lit) return 0.0f;   // daytime
    if (fade <= 0.0f) return 1.0f;
    // Fading in after the on hour, fading out before the off hour.
    const float in = Smooth(sinceOn / fade);
    const float out = Smooth((lit - sinceOn) / fade);
    return (std::min)(in, out);
}

float DaylightGateFactor(const DaylightGate& gate) {
    if (!gate.enabled || !g_settings.enabled) return 1.0f;
    // No sky to follow the clock, so no daytime to switch lights off for: a
    // street light dark at noon under a sky that never changed would just look
    // broken.
    if (RemixApiAvailable() && !RemixApiHasAtmosphere()) return 1.0f;
    return DaylightGateFactorAtHour(gate, g_hour);
}

void TimeOfDayAngles(float* elevationDeg, float* rotationDeg) {
    if (elevationDeg) *elevationDeg = g_elevation;
    if (rotationDeg) *rotationDeg = g_rotation;
}

bool TimeOfDayPushed() { return g_pushed; }
int TimeOfDayPushCount() { return g_pushes; }
const char* TimeOfDayStatus() { return g_status; }

}  // namespace gta2dx9
