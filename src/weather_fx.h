// Weather in the street views of the plain renderer (QB-43, docs/weather.md):
// rain streaks around the camera, an overcast sky, fog banks, and wet roads that
// darken and reflect the street (a screen-space reflection pass in the post chain,
// post_fx.cpp, so it needs [visuals] on). Never under RTX Remix and never in the
// classic top-down view: the renderer only calls this with the street shading on.
//
// The [weather] ini section is read by the DLL side (dll/src/weather.cpp), which
// also steps the state each frame (fades between settings, the roads drying after
// the rain, the optional weather cycle) and drives the sun from the clock for the
// time-of-day half of the row (QB-35).
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <vector>

#include "math3d.h"

namespace gta2 {

struct WorldShading;   // renderer.h
struct VisualLight;    // post_fx.h
struct SkyColours;     // sky.h
struct SkySettings;    // sky.h

// This frame's weather, 0..1 each. All zero (and active false) leaves every
// picture exactly as it was without this file.
struct WeatherState {
    bool active = false;
    float rain = 0.0f;      // falling rain: streaks, darker light
    float cloud = 0.0f;     // overcast: grey sky, the sun hidden
    float fog = 0.0f;       // fog bank: the haze pulled in to a few blocks
    float wind = 0.0f;      // slants the rain, drifts it
    float wet = 0.0f;       // the roads' wetness (lags the rain, dries after it)
    float night = 0.0f;     // WEATHER-V2: 0 day .. 1 night (sun from +2 down to -6 deg)
    float storm = 0.0f;     // WEATHER-V2 phase 2: 0..1, heavy rain in a strong wind (lightning comes with it)
    float flash = 0.0f;     // WEATHER-V2 phase 2: this frame's lightning, 0..~1.5 (a strike's pulses)
    float flashDir[3] = {0.3f, -0.8f, 0.5f};   // unit, world: the light of the current strike, from the sky down
    float windDir[2] = {0.6f, 0.8f};   // unit, world x/z
    float reflection = 1.0f;           // wet-road reflection strength
    bool streaks = true;
    bool wetRoads = true;
    bool remixStreaks = false;         // WEATHER-V2: the D3D9 streaks on a Remix device ([weather] remix_rain=1)
    bool remixRainApi = false;
    bool remixScreenRain = true;      // WEATHER-V2: near-field rain in the UI layer under Remix ([weather] remix_screen_rain)         // WEATHER-V2: Remix API water drops ([weather] remix_rain=2, the default)
    int drops = 1600;                  // streaks at full rain
    double seconds = 0.0;
};

// Set by the DLL side each frame (before the sky is drawn); read by the renderer.
WeatherState& WeatherNow();
using WeatherPollFn = void (*)();
void SetWeatherPoll(WeatherPollFn fn);
void WeatherPoll();
// WEATHER-V2: is the point (world blocks, y up) under a roof, a deck or a bridge? Set by the DLL (the map's
// columns); null = never covered. Rain streaks, the Remix drops and new lens drops leave covered places out.
using WeatherCoverFn = bool (*)(float x, float y, float z);
void SetWeatherCover(WeatherCoverFn fn);
bool WeatherCovered(float x, float y, float z);
// WEATHER-V2: lights near the eye for the screen-space rain under Remix (set by the DLL each frame).
struct ScreenRainLight { float pos[3]; float rgb[3]; float intensity; float radius; bool spot; float dir[3]; float coneDeg; };
void SetScreenRainLights(const std::vector<ScreenRainLight>& lights);

// The sky and the world's light under this weather (both no-ops when inactive).
void WeatherAdjustSky(SkyColours* colours, SkySettings* settings);
// blend: the view transition's weight (0 classic .. 1 street view).
void WeatherAdjustShading(WorldShading* shading, float blend);

// The rain streaks: camera-facing quads in a box that travels with the eye,
// alpha-blended over the finished 3D frame, depth-tested, no depth write.
class WeatherFx {
public:
    void Init(IDirect3DDevice9* device, bool remix);
    void Release();
    void SetCamera(const Mat4& view, const Mat4& proj, const Vec3& eye);
    // WEATHER-V2: the frame's night lights (plain renderer): streaks near them catch their light.
    void SetLights(const std::vector<VisualLight>* lights) { lights_ = lights; }
    // Under Remix the sky pass (which sets the camera) and the shading weight do not run: the
    // world view hands both over here once a frame.
    void SetRemixFrame(const Mat4& view, const Mat4& proj, const Vec3& eye, float blend);
    // After the cars, people and props; before the post resolves. light: the
    // scene's ambient level (so streaks are not brighter than the night).
    void DrawRain(const WorldShading& shading);
    // The puddle noise for the wet pass (L8, tiling).
    IDirect3DTexture9* Puddles();
    IDirect3DTexture9* PuddleField();
    // WEATHER-V2: a whole-map puddle field (size x size ARGB, 256 blocks across) in place of the tiling noise.
    void SetPuddleField(const std::vector<uint8_t>& texels, int size);
    bool HasPuddleField() const { return fieldSize_ > 0; }

private:
    struct RainVertex { float x, y, z; DWORD colour; };
    // Under RTX Remix (WEATHER-V2): Remix drops vertex colour and draws untextured quads as
    // nothing, so the streaks there are textured: the streak's shape, colour and opacity baked
    // into a fixed texture (three opacity levels, one fixed Remix hash each), blended.
    struct RainTexVertex { float x, y, z, u, v; };
    static constexpr int kRemixRainLevels = 3;
    IDirect3DTexture9* remixRain_[kRemixRainLevels] = {};
    std::vector<RainTexVertex> texVerts_[kRemixRainLevels];
    void DrawRainRemix(const WeatherState& w);
public:
    // WEATHER-V2: rain drops on the lens in the first-person views, drawn into the UI layer before the HUD
    // (both renderers: screen space, never path traced). weight: the first-person view's share (0 none).
    // scene: the frame under the UI (plain renderer: the drops refract it), or null (Remix: a shaded drop).
    void DrawLensDrops(int width, int height, float weight, IDirect3DSurface9* scene = nullptr);
    // Under Remix: rain near the eye (0.6-3 blocks) drawn in screen space into the UI layer, lit by nearby lights.
    void DrawScreenRain(int width, int height, float weight);
private:
    struct LensDrop { float x, y, r, born, life, slide, vy; };
    std::vector<LensDrop> lensDrops_;
    IDirect3DTexture9* dropTex_ = nullptr;
    IDirect3DTexture9* dropMask_ = nullptr;
    IDirect3DTexture9* sceneCopy_ = nullptr;
    int sceneW_ = 0, sceneH_ = 0;
    double lensClock_ = -1.0;
    float lensSpawn_ = 0.0f;
    uint32_t lensSeed_ = 0x51ED270Bu;
    IDirect3DDevice9* device_ = nullptr;
    IDirect3DTexture9* puddles_ = nullptr;
    std::vector<uint8_t> field_;
    IDirect3DTexture9* fieldTex_ = nullptr;
    int fieldSize_ = 0;
    IDirect3DStateBlock9* saved_ = nullptr;
    bool remix_ = false;
    const std::vector<VisualLight>* lights_ = nullptr;
    bool haveCamera_ = false;
    Mat4 view_, proj_;
    Vec3 eye_;
    std::vector<RainVertex> verts_;
};

}  // namespace gta2
