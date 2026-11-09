// The street views' water surface (src/water.cpp, docs/water.md).
//
// Shader model 3, compiled offline by tools/build_water_shader.sh into
// src/shaders/water_gen.h. Kept loop-free so Wine 9's d3dcompiler (the
// gta2-remixbox image) builds it as well as Wine 10's.
//
// World space is the renderer's: x east, y up, z north, one unit per block.
// Matrices are row_major and multiply row vectors, as math3d.h's Mat4 does.
// Colours are display (gamma) space like the fixed-function frame around it.

row_major float4x4 cViewProj : register(c0);
float4 cViewZ : register(c4);   // the view matrix's third column: view-space depth = dot(p, cViewZ)

// No NORMAL input: the world's FVF carries one, but Wine 9's compiler gave an unused
// NORMAL the same input register as POSITION (dcl_position0 v0, dcl_normal0 v0).
struct WaterVsIn  { float3 pos : POSITION; float2 uv : TEXCOORD0; };
struct WaterVsOut { float4 pos : POSITION; float3 w : TEXCOORD0; float3 uvd : TEXCOORD1; };
struct WaterPsIn  { float3 w : TEXCOORD0; float3 uvd : TEXCOORD1; };

WaterVsOut vs_water(WaterVsIn i) {
    WaterVsOut o;
    o.pos = mul(float4(i.pos, 1.0), cViewProj);
    o.w = i.pos;
    o.uvd = float3(i.uv, dot(float4(i.pos, 1.0), cViewZ));
    return o;
}

sampler2D sTile  : register(s0);   // the game's water tile (animated by the game, or the HD sheet)
sampler2D sWave  : register(s1);   // rg: wave slope x/z (0.5 = flat), a: wave height
sampler2D sShore : register(s2);   // r: distance to the water's edge, in quarter cells (0 = land)

float4 cCam    : register(c0);   // xyz camera, w seconds
float4 cSun    : register(c1);   // xyz toward the sun, w glint strength (0 at night)
float4 cSunCol : register(c2);   // rgb sun on a face squarely facing it
float4 cAmb    : register(c3);   // rgb ambient
float4 cZenith : register(c4);   // rgb sky overhead
float4 cHorizon: register(c5);   // rgb sky at the horizon
float4 cFog    : register(c6);   // rgb fog colour, w 1 when fog is on, 0 when off
float4 cFogR   : register(c7);   // x start, y end, z 1/(end-start)
float4 cTune   : register(c8);   // x wave strength, y reflection, z foam, w sky brightness

float4 ps_water(WaterPsIn i) : COLOR0 {
    float t = cCam.w;
    float2 p = i.w.xz;

    // Three wave layers drifting different ways: two chop sizes and a slow swell.
    float4 a = tex2D(sWave, p * 0.29 + float2(t * 0.037, t * 0.021));
    float4 b = tex2D(sWave, p * 0.53 + float2(-t * 0.029, t * 0.043));
    float4 c = tex2D(sWave, p * 0.083 + float2(t * 0.011, -t * 0.008));
    float2 slope = (a.xy - 0.5) + (b.xy - 0.5) * 0.8 + (c.xy - 0.5) * 0.9;
    float3 n = normalize(float3(slope.x * cTune.x, 1.0, slope.y * cTune.x));

    float3 v = cCam.xyz - i.w;
    float dist = length(v);
    v = v / max(dist, 0.001);

    // The tile, lit as the fixed-function pass lights an upward face.
    float3 tile = tex2D(sTile, i.uvd.xy).rgb;
    float3 light = saturate(cAmb.rgb + cSunCol.rgb * max(0.0, cSun.y));
    float h = (a.w + b.w) * 0.5;
    float3 body = tile * light * (0.86 + 0.28 * h);

    // Sky reflection with Schlick's Fresnel: little when looking straight down,
    // most of the colour at a grazing angle across the bay.
    float3 r = reflect(-v, n);
    float ndv = saturate(dot(n, v));
    float f = 0.04 + 0.96 * pow(1.0 - ndv, 5.0);
    float3 sky = lerp(cHorizon.rgb, cZenith.rgb, sqrt(saturate(r.y))) * cTune.w;
    float3 col = lerp(body, sky, saturate(f * cTune.y));

    // Sun glint on the wave faces.
    float3 hv = normalize(cSun.xyz + v);
    float spec = pow(saturate(dot(n, hv)), 180.0) * 2.2 + pow(saturate(dot(n, hv)), 24.0) * 0.12;
    col += cSunCol.rgb * spec * cSun.w;

    // Foam where the water meets a quay, a bank or a pier: a thin line at the
    // wall and a lapping band that comes and goes with the waves.
    float shore = tex2D(sShore, p * (1.0 / 256.0)).r * 4.0 - 0.5;   // cells from the edge
    // (A parabolic wave for sin, which Wine 9's compiler lacks: period about 4.5 s.)
    float ph = frac(t * 0.22 + (a.w + c.w) * 0.8);
    float reach = 0.34 + 0.14 * (ph * (1.0 - ph) * 8.0 - 1.0);
    float band = saturate(1.0 - shore / reach);
    float lace = saturate((b.w + a.w * 0.6 - 0.55 + band * 0.7) * 3.0);
    float foam = saturate(band * lace + saturate(1.0 - shore * 7.0) * 0.85) * cTune.z;
    col = lerp(col, light * 0.92, foam);

    // ps_3_0 gets no fixed-function fog: the same linear fog, by view depth.
    float fogK = saturate((cFogR.y - i.uvd.z) * cFogR.z);
    col = lerp(cFog.rgb, col, lerp(1.0, fogK, cFog.w));
    return float4(col, 1.0);
}
