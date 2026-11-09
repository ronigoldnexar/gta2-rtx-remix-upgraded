// Weather and time of day for the plain renderer (QB-35, QB-43; docs/weather.md).
//
// The [weather] section of gta2dx9.ini, re-read every two seconds while the game runs
// (so a script, or a player with an editor open, can bring the rain in and move the
// clock), and the per-frame state the renderer draws from (src/weather_fx.h): the
// rain, cloud and fog eased toward their settings, the roads wetting under the rain
// and drying after it, and an optional weather cycle that changes the sky by itself.
//
// Time of day: with [weather] on and time_of_day=1 the street views' sun follows the
// [timeofday] clock (the same clock that drives RTX Remix's sun), so the day runs
// through golden hour, blue hour and night in the plain renderer too; the night's
// lamps, neon, lit windows and car lamps are the [visuals] light pass and the
// renderer's window glow, which follow the sun. hour_hhmm sets the clock live.
//
// Registered with the renderer by a static object (one function pointer); nothing
// here runs under RTX Remix (the renderer leaves the weather out on a Remix device),
// and with enabled=0 (the default) the frame is exactly what it was without this file.
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "log.h"
#include "time_of_day.h"

#include "../../src/sky.h"
#include "../../src/weather_fx.h"

namespace gta2dx9 {
namespace {

struct Settings {
    bool enabled = false;
    bool timeOfDay = true;
    int hourHhmm = -1;
    int clockPaused = -1;
    float rain = 0.0f, cloud = 0.0f, fog = 0.0f, wind = 0.3f;
    bool cycle = false;
    float cycleMinutes = 6.0f;
    float fadeSeconds = 20.0f;
    bool streaks = true;
    int drops = 1600;
    bool wetRoads = true;
    float reflection = 1.0f;
    int wetPercent = -1;
};

char g_ini[MAX_PATH] = "";
unsigned g_polls = 0;
Settings g_set;
bool g_haveSet = false;
LARGE_INTEGER g_freq = {}, g_last = {};
double g_clock = 0.0;
double g_lastStatus = -1e9;

// The sky's own follow_clock, kept to put back when the weather is switched off.
bool g_savedFollow = false;
bool g_followForced = false;
int g_lastHour = -2;

// The cycle.
struct Spell { const char* name; float rain, cloud, fog, wind; int weight; };
const Spell kSpells[] = {
    {"clear", 0.0f, 0.10f, 0.0f, 0.20f, 4},
    {"cloudy", 0.0f, 0.70f, 0.05f, 0.35f, 3},
    {"drizzle", 0.35f, 0.85f, 0.10f, 0.25f, 2},
    {"rain", 0.75f, 1.00f, 0.15f, 0.45f, 2},
    {"storm", 1.00f, 1.00f, 0.20f, 0.90f, 1},
    {"fog", 0.0f, 0.50f, 0.85f, 0.10f, 1},
};
int g_spell = 0;
double g_spellEnds = 0.0;
uint32_t g_seed = 0x9E3779B9u;
float Rand01() { g_seed ^= g_seed << 13; g_seed ^= g_seed >> 17; g_seed ^= g_seed << 5; return (g_seed & 0xFFFFFF) / 16777215.0f; }

int ReadInt(const char* key, int def) { return GetPrivateProfileIntA("weather", key, def, g_ini); }
float Pct(const char* key, int def) {
    const int v = ReadInt(key, def);
    return (v < 0 ? 0 : (v > 100 ? 100 : v)) / 100.0f;
}

void ReadSettings() {
    Settings s;
    memset(&s, 0, sizeof s);   // every field is read below; zeroed so memcmp sees no padding
    s.enabled = ReadInt("enabled", 0) != 0;
    s.timeOfDay = ReadInt("time_of_day", 1) != 0;
    s.hourHhmm = ReadInt("hour_hhmm", -1);
    s.clockPaused = ReadInt("clock_paused", -1);
    s.rain = Pct("rain_percent", 0);
    s.cloud = Pct("cloud_percent", 0);
    s.fog = Pct("fog_percent", 0);
    s.wind = Pct("wind_percent", 30);
    s.cycle = ReadInt("cycle", 0) != 0;
    s.cycleMinutes = (std::max)(1, ReadInt("cycle_minutes", 6)) * 1.0f;
    s.fadeSeconds = (std::max)(0, ReadInt("fade_seconds", 20)) * 1.0f;
    s.streaks = ReadInt("rain_streaks", 1) != 0;
    s.drops = ReadInt("rain_drops", 1600);
    s.wetRoads = ReadInt("wet_roads", 1) != 0;
    s.reflection = ReadInt("reflection_percent", 100) / 100.0f;
    s.wetPercent = ReadInt("wet_percent", -1);
    if (!g_haveSet || memcmp(&s, &g_set, sizeof s) != 0) {
        Log("weather: %s; time of day %s%s; rain %.0f%% cloud %.0f%% fog %.0f%% wind %.0f%%; cycle %s; streaks %d (%d drops), "
            "wet roads %d (reflection %.0f%%%s)",
            s.enabled ? "on" : "off", s.timeOfDay ? "from the clock" : "the [sky] sun",
            s.hourHhmm >= 0 ? " (hour set)" : "", s.rain * 100.0f, s.cloud * 100.0f, s.fog * 100.0f, s.wind * 100.0f,
            s.cycle ? "on" : "off", s.streaks, s.drops, s.wetRoads, s.reflection * 100.0f, s.wetPercent >= 0 ? ", wetness forced" : "");
    }
    memcpy(&g_set, &s, sizeof s);
    g_haveSet = true;
}

void ApplyClock() {
    gta2::SkySettings& sky = gta2::SkyConfig();
    const bool want = g_set.enabled && g_set.timeOfDay;
    if (want && !g_followForced) {
        g_savedFollow = sky.followClock;
        sky.followClock = true;
        g_followForced = true;
    } else if (!want && g_followForced) {
        sky.followClock = g_savedFollow;
        g_followForced = false;
    }
    if (!g_set.enabled) return;
    if (g_set.hourHhmm != g_lastHour) {
        g_lastHour = g_set.hourHhmm;
        if (g_set.hourHhmm >= 0) {
            const float h = static_cast<float>(g_set.hourHhmm / 100) + static_cast<float>(g_set.hourHhmm % 100) / 60.0f;
            TimeOfDaySetHour(h);
            Log("weather: clock set to %02d:%02d", g_set.hourHhmm / 100, g_set.hourHhmm % 100);
        }
    }
    if (g_set.clockPaused >= 0) TimeOfDay().paused = g_set.clockPaused != 0;
}

void Step(double dt) {
    gta2::WeatherState& w = gta2::WeatherNow();
    w.seconds = g_clock;
    w.active = g_set.enabled;
    w.streaks = g_set.streaks;
    w.wetRoads = g_set.wetRoads;
    w.drops = g_set.drops;
    w.reflection = g_set.reflection;
    if (!g_set.enabled) {
        w.rain = w.cloud = w.fog = w.wind = w.wet = 0.0f;
        return;
    }
    float rain = g_set.rain, cloud = g_set.cloud, fog = g_set.fog, wind = g_set.wind;
    if (g_set.cycle) {
        if (g_clock >= g_spellEnds) {
            int total = 0;
            for (const Spell& s : kSpells) total += s.weight;
            int pick = static_cast<int>(Rand01() * total), next = 0;
            for (int i = 0; i < static_cast<int>(sizeof kSpells / sizeof kSpells[0]); ++i) {
                pick -= kSpells[i].weight;
                if (pick < 0) { next = i; break; }
            }
            g_spell = next;
            g_spellEnds = g_clock + g_set.cycleMinutes * 60.0 * (0.6 + 0.8 * Rand01());
            Log("weather: cycle -> %s for %.0f s", kSpells[g_spell].name, g_spellEnds - g_clock);
        }
        const Spell& s = kSpells[g_spell];
        rain = s.rain; cloud = s.cloud; fog = s.fog; wind = s.wind;
    }
    const float k = g_set.fadeSeconds <= 0.0f ? 1.0f : static_cast<float>((std::min)(1.0, dt / g_set.fadeSeconds));
    w.rain += (rain - w.rain) * k;
    w.cloud += (cloud - w.cloud) * k;
    w.fog += (fog - w.fog) * k;
    w.wind += (wind - w.wind) * k;
    // The wind turns slowly.
    const float a = static_cast<float>(0.7 + 0.5 * std::sin(g_clock * 0.013));
    w.windDir[0] = std::cos(a);
    w.windDir[1] = std::sin(a);
    // Roads wet in about half a minute of heavy rain and dry over two and a half.
    if (g_set.wetPercent >= 0) {
        w.wet = (std::min)(100, g_set.wetPercent) / 100.0f;
    } else if (w.rain > 0.12f) {
        w.wet = (std::min)(1.0f, w.wet + static_cast<float>(dt) * w.rain / 25.0f);
    } else {
        w.wet = (std::max)(0.0f, w.wet - static_cast<float>(dt) / 150.0f);
    }
    if (g_clock - g_lastStatus >= 30.0) {
        g_lastStatus = g_clock;
        float el = 0.0f, az = 0.0f;
        TimeOfDayAngles(&el, &az);
        const float h = TimeOfDayHour();
        Log("weather: %02d:%02d sun %.1f deg; rain %.2f cloud %.2f fog %.2f wind %.2f wet %.2f%s%s",
            static_cast<int>(h), static_cast<int>((h - std::floor(h)) * 60.0f), el, w.rain, w.cloud, w.fog, w.wind, w.wet,
            g_set.cycle ? ", spell " : "", g_set.cycle ? kSpells[g_spell].name : "");
    }
}

void Poll() {
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    if (!g_ini[0]) {
        QueryPerformanceFrequency(&g_freq);
        g_last = now;
        g_seed ^= static_cast<uint32_t>(now.QuadPart);
        GetModuleFileNameA(nullptr, g_ini, MAX_PATH);
        char* slash = strrchr(g_ini, '\\');
        if (slash) strcpy(slash + 1, "gta2dx9.ini"); else strcpy(g_ini, "gta2dx9.ini");
        ReadSettings();
    } else if ((++g_polls % 60u) == 0u) {
        ReadSettings();
    }
    double dt = g_freq.QuadPart ? static_cast<double>(now.QuadPart - g_last.QuadPart) / static_cast<double>(g_freq.QuadPart) : 0.0;
    g_last = now;
    if (dt < 0.0) dt = 0.0;
    if (dt > 0.5) dt = 0.5;   // a level load's stall does not jump the weather
    g_clock += dt;
    ApplyClock();
    Step(dt);
}

struct Register {
    Register() { gta2::SetWeatherPoll(&Poll); }
} g_register;

}  // namespace
}  // namespace gta2dx9
