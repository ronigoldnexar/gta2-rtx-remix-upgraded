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

// No POSITION in the pixel shader's input: Wine 9's compiler declares it (dcl_position0) and
// wined3d refuses such a ps_3_0 shader (D3DERR_INVALIDCALL), as the water shader found.
struct WetIn { float2 uv : TEXCOORD0; };

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
float4 cK          : register(c8);   // 0.5, 1, the in-frame miss fallback (1, qav9), 1e6
float4 cK2         : register(c9);   // 1.5 (hit thickness, in steps), 0.15 (plus blocks), 1.25 (step growth), 0.05 (near)
// qav20 (FIX-WORLD-14): view -> world height (lids lie at whole blocks), and the reflection's softening:
float4 cToWorldY   : register(c10);  // view -> world y (height, blocks)
float4 cK3         : register(c11);  // blur per block of ray (uv), blur cap (uv), hit fade start (share of the march), 1/(fade length)
float4 cK4         : register(c12);  // x: 1 = the mirror on ground lids only (0 = every face that looks up), y: least blur (uv),
                                     // z: Fresnel floor (0.40 before), w: gloss in a puddle (0.85 before)
float4 cK5         : register(c13);  // x: depth tolerance (blocks) of the cover test (qav28, 0.30; -1 = off, before)

sampler2D sLit    : register(s4);
sampler2D sDepth  : register(s1);
sampler2D sPuddle : register(s2);
sampler2D sField  : register(s3);   // WEATHER-V2: whole-map puddle field (L8), 8 texels per block (2048 for a 256-block map)

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
    travel += stepLen;                                                                      \
    suv = cK.xx + cK.xx * float2(q.x / (q.z * cProj.z), -q.y / (q.z * cProj.w));            \
    sz = LinearZ(DepthAt(suv));                                                             \
    edge4 = saturate(float4(suv, cK.yy - suv) * cK.w);                                      \
    inside = edge4.x * edge4.y * edge4.z * edge4.w * St(cK2.w, q.z);                        \
    hit = inside * St(sz, q.z) * St(q.z - sz, stepLen * cK2.x + cK2.y) * (cK.y - found);   \
    hitUv += (suv - hitUv) * hit;                                                           \
    hitT += (travel - hitT) * hit;                                                          \
    found = max(found, hit);                                                                \
    stepLen *= cK2.z;

float4 ps_wet(WetIn i) : COLOR0 {
    float4 lit = tex2Dlod(sLit, float4(i.uv, 0, 0));
    float d = DepthAt(i.uv);
    d = min(d, 0.999);
    float3 p = ViewPos(i.uv, d);
    // qav28 (FIX-WORLD-15): a floor with a surface one block above it (the Downtown plaza's pit
    // floor under its lattice grates, a lid under a gantry deck) is covered, no open puddle: its
    // mirror rays went up into the grate and came back as pale sky and wall blobs in every hole.
    // The point a block above the floor, projected: a surface drawn there at that depth covers it.
    float3 cv = p + cUp.xyz * 0.95;   // (before the normal: fewer live temporaries, r31 limit)
    float cz = LinearZ(DepthAt(cK.xx + cK.xx * float2(cv.x / (cv.z * cProj.z), -cv.y / (cv.z * cProj.w))));
    float open = St(cK5.x, abs(cz - cv.z));
    float3 n = ViewNormal(i.uv, p);
    float up = dot(n, cUp.xyz);
    float flat = smoothstep(0.80, 0.95, up);
    // qav20 (FIX-WORLD-14): only the ground is a wet road. Every lid of the map lies at a whole block
    // height; a car's boot or roof, a prop's top, faces at a fraction of a block, took the puddle
    // mirror too (the burning car at a bil wall showed the wall through its own boot). Those keep
    // the light darkening of a wet wall and no mirror. cK4.x = 0 (with the rest: [visuals] debug 128) = old.
    float hW = dot(float4(p, 1.0), cToWorldY);
    float ground = saturate(1.0 - (abs(frac(hW + 0.5) - 0.5) - 0.03) * 14.0);
    flat *= lerp(1.0, ground, cK4.x) * open;
    float fog = saturate((p.z - cWet.x) * cWet.y);
    float wet = cUp.w * (1.0 - fog);

    float2 wxz = float2(dot(float4(p, 1.0), cToWorldX), dot(float4(p, 1.0), cToWorldZ));
    float2 pn = tex2Dlod(sField, float4(wxz / 256.0 + 0.000244, 0, 0)).rg;   // + half a texel: texels hold grid vertices
    // Far off the puddle map is minified with no mips and turns to grain: fade the puddles
    // (and below, the reflection) out between 25 and 60 blocks.
    float near = 1.0 - saturate((p.z - 25.0) / 35.0);
    float puddle = smoothstep(cWet.z, cWet.z + 0.10, pn.x) * flat * near;

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
    float sz = 0, inside = 1, hit = 0, found = 0, travel = 0, hitT = 0;
    float4 edge4 = 0;
    MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP
    MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP MARCH_STEP

    float2 e = min(hitUv, 1.0 - hitUv);
    float edge = saturate(e.x * 10.0) * saturate(e.y * 10.0);
    // qav20 (FIX-WORLD-14): wet asphalt is no mirror. The reflection was one sharp tap, so a wall's
    // corner continued into the pavement as a hard straight edge and a stopped car stood mirrored
    // under its bumper. Four taps spread with the ray's length soften it the farther the reflected
    // thing is; and a hit fades out over the last part of the march, so the line where hits give
    // out (the qav9 seam's cousin under the bumper) is a gradient into the fallback, not an edge.
    float blur = min(cK4.y + hitT * cK3.x, cK3.y);
    float2 hb = saturate(hitUv + rip);
    float3 refl = 0.25 * (tex2Dlod(sLit, float4(saturate(hb + float2(blur, blur * 0.5)), 0, 0)).rgb +
                          tex2Dlod(sLit, float4(saturate(hb - float2(blur, blur * 0.5)), 0, 0)).rgb +
                          tex2Dlod(sLit, float4(saturate(hb + float2(-blur * 0.5, blur)), 0, 0)).rgb +
                          tex2Dlod(sLit, float4(saturate(hb + float2(blur * 0.5, -blur)), 0, 0)).rgb);
    float hitFade = 1.0 - saturate((hitT / travel - cK3.z) * cK3.w);
    float3 sky = lerp(cHorizon.rgb, cZenith.rgb, saturate(dot(r, cUp.xyz)));
    // qav9 (FIX-WORLD-13): the march is ten steps whose length grows with the pixel's distance, so
    // from the ground just in front of the lens it ends a few blocks out, short of the walls that the
    // pixels farther up the road do reach; those near pixels took the flat sky colour and the line
    // where hits gave out was a hard, step-shaped seam with a "dry slab" before it. A ray that ends
    // still inside the frame without a hit now takes the scene where it ended (what lies on along
    // it, the wall or the sky beyond), so both sides of that line sample the same place. Only a ray
    // that left the frame gets the sky colour. cK.z = 1 (0 = the old fallback, [visuals] debug 64).
    float2 eL = min(suv, cK.yy - suv);
    float endIn = saturate(eL.x * 10.0) * saturate(eL.y * 10.0) * inside * cK.z;
    float3 farCol = tex2Dlod(sLit, float4(saturate(suv + rip), 0, 0)).rgb;
    float3 reflCol = lerp(lerp(sky, farCol, endIn), refl, found * edge * hitFade);
    // Asphalt is no mirror: from the chase camera's height the true Fresnel term is a
    // few percent; a floor keeps the wet sheen readable, puddles reflect most.
    float cosv = saturate(dot(-v, n));
    float f = 0.04 + 0.96 * pow(1.0 - cosv, 5.0);
    float gloss = wet * flat * lerp(0.10, cK4.w, puddle) * cZenith.w * (0.5 + 0.5 * near);
    float amount = saturate(gloss * (cK4.z + (1.0 - cK4.z) * f));
    col = lerp(col, reflCol, amount);
    // the sky: left as it is (no branches in this compiler); its test re-reads the depth here instead of
    // holding a temporary through the march (FIX-WORLD-15: room for the cover test under the r31 limit)
    float sky0 = St(0.999999, DepthAt(i.uv));
    return float4(lerp(col, lit.rgb, sky0), lit.a);
}
