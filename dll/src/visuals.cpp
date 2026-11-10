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
#include <cmath>
#include <cstring>
#include <vector>

#include "log.h"
#include "remix_lights.h"
#include "explosion_fx.h"
#include "world_view.h"   // StreetPresentation (FIX-REMIX-NIGHT-8)

#include "../../src/post_fx.h"
#include "../../src/sky.h"

namespace gta2dx9 {
bool SilencedMuzzleNear(const float* pos);   // live_geometry.cpp (FIX-FIGURE-12)
bool RocketLaunchNear(const float* pos);     // live_geometry.cpp (FIX-FIGURE-13)
namespace {

char g_ini[MAX_PATH] = "";
unsigned g_polls = 0;

int ReadInt(const char* key, int def) { return GetPrivateProfileIntA("visuals", key, def, g_ini); }

void ReadSettings(bool first) {
    gta2::VisualsSettings& v = gta2::VisualsConfig();
    const gta2::VisualsSettings before = v;
    v.enabled = ReadInt("enabled", 0) != 0;   // off until the shadows are verified (docs/visuals-plain.md)
    v.shadows = ReadInt("shadows", 1) != 0;
    v.ssao = ReadInt("ssao", 1) != 0;
    v.bloom = ReadInt("bloom", 1) != 0;
    v.tonemap = ReadInt("tonemap", 1) != 0;
    v.lights = ReadInt("lights", 1) != 0;
    v.hemisphere = ReadInt("hemisphere", 1) != 0;
    v.hdr = ReadInt("hdr", 1);
    v.shadowStagger = ReadInt("shadow_stagger", 1) != 0;
    v.carShadowBlend = ReadInt("car_shadow_blend", 1) != 0;   // feel29: the driven car's shadow eased (live A/B)
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
    // debug=32: one sample of the list per 20 s while the pass runs (the lamp-pool tuning read it).
    static DWORD lastDump = 0;
    const DWORD nowTick = GetTickCount();
    const bool dump = gta2::VisualsConfig().debug == 32 && nowTick - lastDump > 20000u;
    if (dump) lastDump = nowTick;
    int dumped = 0;
    // Fire (FIX-FX, ptm14/fire-fx): the game's flames come as a light per flame particle, a dozen
    // over one burning car, and their sum blew a wall out to a flat disc. They are gathered here
    // into one warm point light per blaze (within 1.5 blocks), bounded, with a slow flicker, and
    // kept at 45 % by day so a burning car lights the road and the wall beside it.
    struct Blaze { float pos[3]; float weight; float peak; };
    std::vector<Blaze> blazes;
    for (const RemixTrackedLight& t : LightsTracked()) {
        const RemixLightDesc& d = t.def;
        if (d.source != kLightSourceFire) continue;
        if (d.intensity < 0.02f) continue;
        Blaze* into = nullptr;
        for (Blaze& b : blazes) {
            const float dx = b.pos[0] / b.weight - d.pos[0], dz = b.pos[2] / b.weight - d.pos[2];
            if (dx * dx + dz * dz < 1.5f * 1.5f) { into = &b; break; }
        }
        if (!into) { blazes.push_back(Blaze{{0, 0, 0}, 0.0f, 0.0f}); into = &blazes.back(); }
        for (int i = 0; i < 3; ++i) into->pos[i] += d.pos[i];
        into->weight += 1.0f;
        into->peak = into->peak > d.intensity ? into->peak : d.intensity;
    }
    const float secs = static_cast<float>(nowTick % 100000u) / 1000.0f;
    for (size_t i = 0; i < blazes.size(); ++i) {
        const Blaze& b = blazes[i];
        gta2::VisualLight l = {};
        for (int c = 0; c < 3; ++c) l.pos[c] = b.pos[c] / b.weight;
        l.pos[1] += 0.35f;   // over the flames, so the ground round the car is lit too
        l.rgb[0] = 1.0f; l.rgb[1] = 0.52f; l.rgb[2] = 0.18f;
        const float size = b.weight < 6.0f ? b.weight / 6.0f : 1.0f;
        const float flicker = 0.86f + 0.08f * std::sin(secs * 7.3f + i * 1.7f) + 0.06f * std::sin(secs * 13.1f + i * 0.9f);
        // FIX-FX-2 (fire-fx 3d): stronger, and more of it by day: the pool beside a burning car was
        // faint on dark asphalt (the light sum is still bounded, so it tints, never clips).
        l.intensity = (0.70f + 0.50f * size) * flicker;
        // ... but not round an eye inside the blaze (first person at the wheel, the death camera a
        // block off a blast): there the summed fire lights turned the whole sunlit street cream.
        {
            float eye[3];
            if (ExplosionFxEye(eye)) {
                const float dx = l.pos[0] - eye[0], dy = l.pos[1] - eye[1], dz = l.pos[2] - eye[2];
                float k = (std::sqrt(dx * dx + dy * dy + dz * dz) - 0.8f) / 2.2f;
                k = k < 0.0f ? 0.0f : (k > 1.0f ? 1.0f : k);
                l.intensity *= 0.3f + 0.7f * k * k * (3.0f - 2.0f * k);
            }
            // A blast's own fire lights: a dozen at once, on top of explosion_fx's flash and ground
            // light; by day their sum doubled every sunlit surface round it (the death camera's
            // cream frame). Held to a quarter while the blast is fresh.
            l.intensity *= 1.0f - 0.75f * ExplosionFxBlastShare(l.pos[0], l.pos[2], 3.0f);
        }
        l.radius = 3.4f;
        l.day = 0.65f;
        out->push_back(l);
    }
    {   // GTA2DX9_BLAST_PROBE=1 (FIX-FX-3): the fire lights round the eye while a blast is young.
        static const bool probe = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_BLAST_PROBE", b, sizeof b) && b[0] == '1'; }();
        float eye[3];
        if (probe && !blazes.empty() && ExplosionFxEye(eye) && ExplosionFxBlastShare(eye[0], eye[2], 12.0f) > 0.25f) {
            float sum = 0.0f, nearest = 99.0f;
            for (const gta2::VisualLight& l : *out) {
                const float dx = l.pos[0] - eye[0], dy = l.pos[1] - eye[1], dz = l.pos[2] - eye[2];
                const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
                nearest = nearest < d ? nearest : d;
                if (d < l.radius + 4.0f) sum += l.intensity * l.day;
            }
            Log("blast probe: fire lights %d (from %d flames), day-weighted sum within reach of the eye %.2f, nearest %.2f blocks",
                static_cast<int>(out->size()), static_cast<int>(LightsTracked().size()), sum, nearest);
        }
    }
    for (const RemixTrackedLight& t : LightsTracked()) {
        const RemixLightDesc& d = t.def;
        if (d.source == kLightSourceFire) continue;
        if (dump && dumped < 8 && (d.source == kLightSourceGame || dumped < 3)) {
            ++dumped;
            Log("visuals: light src %d at %.2f %.2f %.2f r %.2f i %.2f rgb %.2f %.2f %.2f spot %d", d.source, d.pos[0], d.pos[1],
                d.pos[2], d.radius, d.intensity, d.rgb[0], d.rgb[1], d.rgb[2], d.spot ? 1 : 0);
        }
        if (d.intensity < 0.02f || d.radius <= 0.0f) continue;
        // Short-lived sparks and bullets would flicker; flames and muzzle flashes stay.
        if (d.source == kLightSourceBullet || d.source == kLightSourceSpark || d.source == kLightSourceCigarette) continue;
        gta2::VisualLight l = {};
        for (int i = 0; i < 3; ++i) { l.pos[i] = d.pos[i]; l.rgb[i] = d.rgb[i]; l.dir[i] = d.dir[i]; }
        // FIX-REMIX-NIGHT-8 (qav1 ste lime flood): a wide (radius >= 3) saturated sign light of the map (the neon
        // class: greens, cyans, blues, magentas; never the sodium lamps) flooded the whole street in its colour, a
        // #80FF00 radius-4 light at ste 99.5,96.5 turning the pavement and the people lime from dusk to dawn. In the
        // street views it keeps 30 % of its hue over a warm white of the same luminance, as Remix's wide-neon rule
        // does (remix_lights.cpp). GTA2DX9_WIDE_NEON_OLD=1: the game's colour, as before.
        {
            static const bool wideOld = [] { const char* e = getenv("GTA2DX9_WIDE_NEON_OLD"); return e && e[0] == '1'; }();
            if (!wideOld && d.source == kLightSourceGame && !t.moving && d.radius >= 3.0f && StreetPresentation() &&
                ClassifyGameLight(d, false) == kGameLightNeon) {
                static const float kWarm[3] = {1.0f, 0.86f, 0.66f};
                const float lum = 0.2126f * d.rgb[0] + 0.7152f * d.rgb[1] + 0.0722f * d.rgb[2];
                const float wl = 0.2126f * kWarm[0] + 0.7152f * kWarm[1] + 0.0722f * kWarm[2];
                for (int i = 0; i < 3; ++i) l.rgb[i] = 0.3f * d.rgb[i] + 0.7f * kWarm[i] * lum / wl;
            }
        }
        // The game's radius is a reach in tiles that Remix turns into brightness; here it
        // is a distance with a soft end, a little wider so a lamp makes a pool.
        float r = d.radius * 1.35f;
        r = r < 1.5f ? 1.5f : (r > 6.0f ? 6.0f : r);
        l.radius = r;
        // Bounded per light (FIX-FX): siren and head-lamp lights carry Remix radiances (~10), which
        // made a point light of 2.6 that flooded a wall pure red or blue.
        l.intensity = 0.12f + 0.25f * (d.intensity < 3.5f ? d.intensity : 3.5f);
        l.spot = d.spot && d.coneAngleDeg > 1.0f;
        l.coneDeg = d.coneAngleDeg;
        // Headlamp beams reach down the road, softer: at x0.6 a beam read as a blown yellow-white
        // bar on the asphalt at night (out/vp2_look, tier_night_high).
        // Head lamps and sirens carry Remix radiances (10, synthetic_lights.cpp): 0.12 + 0.25 * 10
        // times 0.3 still left two overlapping beams a blown white-yellow pool across the road at
        // night (QB-35, out/qb35_look1 t_w_third_night_clear). A beam is now 0.22 at most.
        if (l.spot) { l.radius = r < 6.0f ? 6.0f : r; l.intensity = 0.22f * (d.intensity < 4.0f ? d.intensity / 4.0f : 1.0f); }
        // FIX-FIGURE-6 pfeel50: a muzzle flash pulses on the walls by day too (half its night
        // strength), a short warm reach round the shooter.
        if (d.source == kLightSourceMuzzle) { l.day = 0.5f; l.radius = 2.6f; l.intensity = 0.20f + 0.35f * (d.intensity < 1.0f ? d.intensity : 1.0f); }
        // FIX-FIGURE-12 (pfl46 third): a suppressed shot's flash light (the game's flash particle) is a
        // faint glow, no day share: at 0.20+ by day it lit his shirt and face on every shot.
        if (d.source == kLightSourceMuzzle && SilencedMuzzleNear(d.pos)) { l.day = 0.0f; l.intensity *= 0.25f; l.radius = 1.2f; }
        // FIX-FIGURE-13 (pfl51): the rocket's launch flash light sits at the shooter's hips (the game fires it
        // from his feet): a third of it, half its reach, so it does not light his own legs.
        if (d.source == kLightSourceMuzzle && RocketLaunchNear(d.pos)) { l.intensity *= 0.33f; l.radius *= 0.5f; }
        out->push_back(l);
        // A pool under each of the map's lamps (QB-35): a GTA2 lamp sits 1.5-3 blocks over the
        // street, and with the soft falloff above only ~3 % of it reached the pavement, so the
        // night had no lamp pools. A second, shorter light a block under the lamp head lays a
        // pool on the ground and the foot of the walls beside it.
        if (d.source == kLightSourceGame && !l.spot && d.radius >= 2.5f) {
            gta2::VisualLight pool = l;
            pool.pos[1] -= 1.0f;
            pool.radius = 3.6f;
            pool.intensity = 0.30f * (d.intensity < 1.5f ? d.intensity : 1.5f);
            out->push_back(pool);
        }
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
