// The DLL side of the plain renderer's modern look (src/post_fx.h, docs/visuals-plain.md):
// the [visuals] section of gta2dx9.ini, re-read every two seconds so a script (or a
// player with an editor open) can switch passes and quality while the game runs, and the
// night's lights for the screen-space light pass, taken from the list the Remix path
// already keeps (remix_lights.cpp: the game's lamps and neon, the far map lamps, the
// synthetic car head and tail lamps). Nothing here runs under RTX Remix: the renderer
// does not start the post on a Remix device, and it alone calls these.
//
// Registered with the renderer by a static object (two function pointers, nothing else
// at load time), so no other file's code changes for it.
#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "log.h"
#include "remix_lights.h"

#include "../../src/post_fx.h"
#include "../../src/sky.h"

namespace gta2dx9 {
namespace {

char g_ini[MAX_PATH] = "";
unsigned g_polls = 0;

int ReadInt(const char* key, int def) { return GetPrivateProfileIntA("visuals", key, def, g_ini); }

void ReadSettings(bool first) {
    gta2::VisualsSettings& v = gta2::VisualsConfig();
    const gta2::VisualsSettings before = v;
    v.enabled = ReadInt("enabled", 1) != 0;
    v.shadows = ReadInt("shadows", 1) != 0;
    v.ssao = ReadInt("ssao", 1) != 0;
    v.bloom = ReadInt("bloom", 1) != 0;
    v.tonemap = ReadInt("tonemap", 1) != 0;
    v.lights = ReadInt("lights", 1) != 0;
    v.hemisphere = ReadInt("hemisphere", 1) != 0;
    v.hdr = ReadInt("hdr", 1);
    v.debug = ReadInt("debug", 0);
    char q[32] = "";
    GetPrivateProfileStringA("visuals", "quality", "medium", q, sizeof q, g_ini);
    for (char* c = q; *c; ++c) *c = static_cast<char>(tolower(static_cast<unsigned char>(*c)));
    v.quality = (!strncmp(q, "low", 3) || !strcmp(q, "0")) ? 0 : ((!strncmp(q, "high", 4) || !strcmp(q, "2")) ? 2 : 1);
    v.shadowStrength = ReadInt("shadow_strength_percent", 135) / 100.0f;
    v.aoStrength = ReadInt("ao_strength_percent", 75) / 100.0f;
    v.bloomStrength = ReadInt("bloom_strength_percent", 55) / 100.0f;
    v.bloomThreshold = ReadInt("bloom_threshold_percent", 80) / 100.0f;
    v.exposure = ReadInt("exposure_percent", 100) / 100.0f;
    v.saturation = ReadInt("saturation_percent", 110) / 100.0f;
    v.lightIntensity = ReadInt("light_intensity_percent", 100) / 100.0f;
    v.sunBoost = ReadInt("sun_boost_percent", 150) / 100.0f;
    v.ambientScale = ReadInt("ambient_scale_percent", 84) / 100.0f;
    // A developer override of the sun (the [sky] keys are read once at start): any value
    // other than -9999 moves it while the game runs, for day/dusk/night checks in one session.
    const int el = ReadInt("sun_elevation_tenths", -9999), az = ReadInt("sun_azimuth_tenths", -9999);
    gta2::SkySettings& sky = gta2::SkyConfig();
    if (el != -9999) sky.sunElevationDeg = el / 10.0f;
    if (az != -9999) sky.sunAzimuthDeg = az / 10.0f;
    if (first || memcmp(&before, &v, sizeof v) != 0 || el != -9999) {
        static int lastEl = -10000;
        if (first || memcmp(&before, &v, sizeof v) != 0 || el != lastEl) {
            Log("visuals: %s, quality %s, shadows %d ssao %d bloom %d tonemap %d lights %d hemisphere %d%s",
                v.enabled ? "on" : "off", v.quality == 0 ? "low" : (v.quality == 1 ? "medium" : "high"), v.shadows, v.ssao,
                v.bloom, v.tonemap, v.lights, v.hemisphere, el != -9999 ? " (sun override)" : "");
            if (el != -9999) Log("visuals: sun at %.1f deg elevation, %.1f azimuth", sky.sunElevationDeg, sky.sunAzimuthDeg);
        }
        lastEl = el;
    }
}

void Poll() {
    if (!g_ini[0]) {
        GetModuleFileNameA(nullptr, g_ini, MAX_PATH);
        char* slash = strrchr(g_ini, '\\');
        if (slash) strcpy(slash + 1, "gta2dx9.ini"); else strcpy(g_ini, "gta2dx9.ini");
        ReadSettings(true);
    } else if ((++g_polls % 60u) == 0u) {
        ReadSettings(false);
    }
}

void ProvideLights(std::vector<gta2::VisualLight>* out) {
    for (const RemixTrackedLight& t : LightsTracked()) {
        const RemixLightDesc& d = t.def;
        if (d.intensity < 0.02f || d.radius <= 0.0f) continue;
        // Short-lived sparks and bullets would flicker; flames and muzzle flashes stay.
        if (d.source == kLightSourceBullet || d.source == kLightSourceSpark || d.source == kLightSourceCigarette) continue;
        gta2::VisualLight l = {};
        for (int i = 0; i < 3; ++i) { l.pos[i] = d.pos[i]; l.rgb[i] = d.rgb[i]; l.dir[i] = d.dir[i]; }
        // The game's radius is a reach in tiles that Remix turns into brightness; here it
        // is a distance with a soft end, a little wider so a lamp makes a pool.
        float r = d.radius * 1.35f;
        r = r < 1.5f ? 1.5f : (r > 6.0f ? 6.0f : r);
        l.radius = r;
        l.intensity = 0.12f + 0.25f * d.intensity;
        l.spot = d.spot && d.coneAngleDeg > 1.0f;
        l.coneDeg = d.coneAngleDeg;
        if (l.spot) { l.radius = r < 6.0f ? 6.0f : r; l.intensity *= 0.6f; }   // headlamp beams reach down the road, softer
        out->push_back(l);
    }
}

struct Register {
    Register() {
        gta2::SetVisualsPoll(&Poll);
        gta2::SetVisualLightProvider(&ProvideLights);
    }
} g_register;

}  // namespace
}  // namespace gta2dx9
