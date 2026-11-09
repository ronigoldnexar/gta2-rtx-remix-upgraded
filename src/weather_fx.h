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

#include <vector>

#include "math3d.h"

namespace gta2 {

struct WorldShading;   // renderer.h
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
    float windDir[2] = {0.6f, 0.8f};   // unit, world x/z
    float reflection = 1.0f;           // wet-road reflection strength
    bool streaks = true;
    bool wetRoads = true;
    int drops = 1600;                  // streaks at full rain
    double seconds = 0.0;
};

// Set by the DLL side each frame (before the sky is drawn); read by the renderer.
WeatherState& WeatherNow();
using WeatherPollFn = void (*)();
void SetWeatherPoll(WeatherPollFn fn);
void WeatherPoll();

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
    // After the cars, people and props; before the post resolves. light: the
    // scene's ambient level (so streaks are not brighter than the night).
    void DrawRain(const WorldShading& shading);
    // The puddle noise for the wet pass (L8, tiling).
    IDirect3DTexture9* Puddles();

private:
    struct RainVertex { float x, y, z; DWORD colour; };
    IDirect3DDevice9* device_ = nullptr;
    IDirect3DTexture9* puddles_ = nullptr;
    IDirect3DStateBlock9* saved_ = nullptr;
    bool remix_ = false;
    bool haveCamera_ = false;
    Mat4 view_, proj_;
    Vec3 eye_;
    std::vector<RainVertex> verts_;
};

}  // namespace gta2
