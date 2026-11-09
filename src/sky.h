// The sky of the street-level views.
//
// GTA2 was drawn from above and has no sky: in the chase and first-person views
// everything past the last block is the colour the frame was cleared to, black.
// This gives those views a sky dome - a gradient from a hazy horizon to the
// zenith, a sun with its glow, a layer of soft clouds - and the two things that
// tie the city to it: distance fog in the horizon's colour, so streets fade into
// the sky instead of ending in black, and a directional sun on the world's
// faces so the side of a building that faces the sun is the brighter one.
//
// All of it is weighted by a blend factor that the view transition drives: 0 in
// the classic top-down view, where nothing here is drawn and the picture is
// exactly what it always was, 1 in the street views, and in between while the
// camera travels, so the sky fades up as the eye comes down.
//
// Fixed-function throughout and cheap on purpose: a dome of some 900 triangles
// with one generated cloud texture and one generated glow texture, drawn with
// depth off before the world.
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <vector>

#include "camera.h"
#include "math3d.h"

namespace gta2 {

struct SkySettings {
    bool enabled = true;          // the dome, the fog and the sun light at all
    // Where the sun is. followClock takes it from the day/night clock in
    // time_of_day.h (so 02:00 is a night sky); otherwise it stands still where
    // these say. Compass azimuth: 0 north (+Z), 90 east (+X).
    bool  followClock = false;
    float sunElevationDeg = 24.0f;
    float sunAzimuthDeg = 235.0f;
    // Distance fog, in blocks: full colour from fogEnd, none before fogStart.
    float fogStart = 30.0f;
    float fogEnd = 140.0f;
    float cloudCover = 0.45f;     // 0 clear .. 1 overcast
    float cloudShade = 0.0f;      // weather (weather_fx.h): 0 white clouds .. 1 dark rain cloud
    // The world's lighting in the street views: ambient as a fraction of the
    // texture's own brightness, plus the sun's contribution on a face that
    // squarely faces it. 0 sun leaves every face at ambient.
    float ambient = 0.80f;
    float sunLight = 0.40f;
};

// The one set of settings, read from the ini and the menu.
SkySettings& SkyConfig();

// What the sun's position implies for this frame's colours.
struct SkyColours {
    Vec3 sunDir;        // unit vector toward the sun
    Vec3 zenith;        // linear 0..1 colours
    Vec3 horizon;
    Vec3 sunColour;
    Vec3 fog;
    Vec3 ambient;       // tint for the world's ambient term
    float day = 1.0f;   // 1 full daylight .. 0 night
};
SkyColours ComputeSkyColours(float sunElevationDeg, float sunAzimuthDeg);

// With [visuals] on (post_fx.h) and no RTX Remix device, the colours above come from a
// richer palette (a deeper day blue, a golden hour, a violet dusk, a navy night) and the
// dome gets stars and an HDR sun disc for the bloom. The renderer says when it is Remix.
void SetSkyRemix(bool remix);

class Sky {
public:
    ~Sky();
    // Draws the dome, the sun and the clouds around the camera, over whatever
    // is in the frame, with the given weight. Leaves depth test and write on.
    void Draw(IDirect3DDevice9* device, const Camera& camera, float aspect, const SkySettings& settings,
              const SkyColours& colours, float blend, double seconds);
    void Release();

    // Builds the cloud and glow textures now (the cloud noise is ~100 ms of CPU), so the
    // first street-view frame does not (PERF-2: the sky phase read 130 ms there).
    void Warm(IDirect3DDevice9* device) { Ensure(device); }
    // The frame goes to an FP16 target (the post is on): the sun's core may exceed 1.
    void SetHdr(bool on) { hdr_ = on; }

private:
    bool Ensure(IDirect3DDevice9* device);
    void BuildDome();

    struct DomeVertex {
        float x, y, z;
        DWORD colour;
        float u, v;
    };
    std::vector<Vec3> domeDirs_;          // unit direction of each dome vertex
    std::vector<float> domeElevation_;    // its elevation, radians
    std::vector<DomeVertex> domeScratch_;  // filled per frame
    std::vector<uint16_t> domeIndices_;
    IDirect3DTexture9* clouds_ = nullptr;
    IDirect3DTexture9* glow_ = nullptr;
    IDirect3DTexture9* stars_ = nullptr;
    IDirect3DDevice9* device_ = nullptr;
    bool hdr_ = false;
};

}  // namespace gta2
