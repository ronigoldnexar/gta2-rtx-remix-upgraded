// Wet roads for the plain renderer's post chain (src/post_fx.cpp, src/weather_fx.h,
// docs/weather.md): after the night lights are added and before the bloom, faces
// that look up darken and reflect the street - a screen-space reflection marched
// against the scene's depth, the sky where the ray leaves the frame - more in
// puddles (a tiling noise in world space), rippled while it rains. Walls darken a
// little. Fogged distance is left alone.
//
// Shader model 3, compiled offline by tools/build_weather_shader.sh into
// src/shaders/weather_gen.h. Loop-free (the march is written out by a macro) so
// Wine 9's d3dcompiler in the gta2-remixbox image builds it.

struct QuadOut { float4 pos : POSITION; float2 uv : TEXCOORD0; };

float4 cProj       : register(c0);   // P33, P43, 1/P11, 1/P22
float4 cScreen     : register(c1);   // 1/W, 1/H, W, H
float4 cUp         : register(c2);   // world up in view space; w: wetness 0..1
float4 cToWorldX   : register(c3);   // view -> world x: dot(float4(p, 1), c3)
float4 cToWorldZ   : register(c4);   // view -> world z
float4 cHorizon    : register(c5);   // sky at the horizon; w: seconds (wrapped)
float4 cZenith     : register(c6);   // sky overhead; w: reflection strength
float4 cWet        : register(c7);   // fog start, 1/(fog end - start), puddle threshold, rain (ripples)
// Numbers the march uses, as a uniform: Wine 9's compiler writes a fresh def for every
// literal in every unrolled step and the shader ran past ps_3_0's 224 constants.
float4 cK          : register(c8);   // 0.5, 1, 0, 1e6
float4 cK2         : register(c9);   // 1.5 (hit thickness, in steps), 0.15 (plus blocks), 1.25 (step growth), 0.05 (near)

sampler2D sLit    : register(s4);
sampler2D sDepth  : register(s1);
sampler2D sPuddle : register(s2);

// step() as arithmetic: this compiler has no comparisons in shader model 3 yet.
float St(float edge, float x) { return saturate((x - edge) * cK.w); }

float LinearZ(float d) { return cProj.y / (d - cProj.x); }
float3 ViewPos(float2 uv, float d) {
    float z = LinearZ(d);
    return float3((uv.x * 2.0 - 1.0) * z * cProj.z, (1.0 - uv.y * 2.0) * z * cProj.w, z);
}
float DepthAt(float2 uv) { return tex2Dlod(sDepth, float4(uv, 0, 0)).r; }
float3 ViewNormal(float2 uv, float3 p) {
    float2 dx = float2(cScreen.x, 0), dy = float2(0, cScreen.y);
    float3 pl = ViewPos(uv - dx, DepthAt(uv - dx));
    float3 pr = ViewPos(uv + dx, DepthAt(uv + dx));
    float3 pu = ViewPos(uv - dy, DepthAt(uv - dy));
    float3 pd = ViewPos(uv + dy, DepthAt(uv + dy));
    float3 ex = lerp(p - pl, pr - p, St(abs(pr.z - p.z), abs(p.z - pl.z)));
    float3 ey = lerp(p - pu, pd - p, St(abs(pd.z - p.z), abs(p.z - pu.z)));
    return normalize(cross(ex, ey));
}

// One step of the march: advance, project, compare with the depth there; the first
// hit (the ray just went behind a surface, by less than this step's length) wins.
#define MARCH_STEP                                                                          \
    q += r * stepLen;                                                                       \
    suv = cK.xx + cK.xx * float2(q.x / (q.z * cProj.z), -q.y / (q.z * cProj.w));            \
    sz = LinearZ(DepthAt(suv));                                                             \
    edge4 = saturate(float4(suv, cK.yy - suv) * cK.w);                                      \
    inside = edge4.x * edge4.y * edge4.z * edge4.w * St(cK2.w, q.z);                        \
    hit = inside * St(sz, q.z) * St(q.z - sz, stepLen * cK2.x + cK2.y) * (cK.y - found);   \
    hitUv += (suv - hitUv) * hit;                                                           \
    found = max(found, hit);                                                                \
    stepLen *= cK2.z;

float4 ps_wet(QuadOut i) : COLOR0 {
    float4 lit = tex2Dlod(sLit, float4(i.uv, 0, 0));
    float d = DepthAt(i.uv);
    float sky0 = St(0.999999, d);   // the sky: left as it is (no branches in this compiler)
    d = min(d, 0.999);
    float3 p = ViewPos(i.uv, d);
    float3 n = ViewNormal(i.uv, p);
    float up = dot(n, cUp.xyz);
    float flat = smoothstep(0.80, 0.95, up);
    float fog = saturate((p.z - cWet.x) * cWet.y);
    float wet = cUp.w * (1.0 - fog);

    float2 wxz = float2(dot(float4(p, 1.0), cToWorldX), dot(float4(p, 1.0), cToWorldZ));
    float2 pn = tex2Dlod(sPuddle, float4(wxz / 32.0, 0, 0)).rg;
    float puddle = smoothstep(cWet.z, cWet.z + 0.10, pn.x) * flat;

    // Wet surfaces are darker: more on the ground, much more in a puddle's dark water.
    float3 col = lit.rgb * (1.0 - wet * (lerp(0.10, 0.38, flat) + 0.12 * puddle));

    // Rain on the water: two drifting noise layers bend the reflection.
    float t = cHorizon.w;
    float2 rip = (tex2Dlod(sPuddle, float4(wxz * 0.85 + t * float2(0.31, 0.17), 0, 0)).gr - 0.5) +
                 (tex2Dlod(sPuddle, float4(wxz * 1.9 - t * float2(0.23, 0.41), 0, 0)).rg - 0.5);
    rip *= cWet.w * lerp(0.010, 0.025, puddle);

    float3 v = normalize(p);
    float3 r = reflect(v, n);
    float3 q = p + n * 0.03;
    float stepLen = 0.15 + p.z * 0.03;
    float2 suv = i.uv, hitUv = i.uv;
    float sz = 0, inside = 1, hit = 0, found = 0;
    float4 edge4 = 0;
    MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP
    MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP

    float2 e = min(hitUv, 1.0 - hitUv);
    float edge = saturate(e.x * 10.0) * saturate(e.y * 10.0);
    float3 refl = tex2Dlod(sLit, float4(saturate(hitUv + rip), 0, 0)).rgb;
    float3 sky = lerp(cHorizon.rgb, cZenith.rgb, saturate(dot(r, cUp.xyz)));
    // A ray that hit nothing went up past the frame: the sky; one that hit is the street.
    float3 reflCol = lerp(sky, refl, found * edge);
    // Asphalt is no mirror: from the chase camera's height the true Fresnel term is a
    // few percent; a floor keeps the wet sheen readable, puddles reflect most.
    float cosv = saturate(dot(-v, n));
    float f = 0.04 + 0.96 * pow(1.0 - cosv, 5.0);
    float gloss = wet * flat * lerp(0.28, 0.85, puddle) * cZenith.w;
    float amount = saturate(gloss * (0.40 + 0.60 * f));
    col = lerp(col, reflCol, amount);
    return float4(lerp(col, lit.rgb, sky0), lit.a);
}
