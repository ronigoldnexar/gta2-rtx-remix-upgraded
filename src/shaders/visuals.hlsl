// The plain renderer's modern passes (src/post_fx.cpp, docs/visuals-plain.md):
// cascaded sun shadows, screen-space ambient occlusion, a hemisphere sky term,
// night lights as screen-space point/spot lights, bloom and a filmic tonemap.
//
// Shader model 3, compiled offline to bytecode (tools/build_shaders.sh, which runs
// tools/shc.cpp under Wine 10's d3dcompiler) into src/shaders/visuals_gen.h, so the
// DLL needs no shader compiler at run time on either Windows or Wine.
//
// Conventions: every pass works in display (gamma) space like the fixed-function
// frame it starts from. View space is the camera's left-handed space (+z forward).
// Matrices are row_major and multiply row vectors, as math3d.h's Mat4 does.

// ---------------------------------------------------------------------------
// Shadow map rendering. The map stores light-space depth 0..1 in an R32F target.

row_major float4x4 cLightVP : register(c0);   // world -> light clip (orthographic)
row_major float4x4 cWorld   : register(c4);   // object -> world (model casters)

struct ShadowWorldIn  { float3 pos : POSITION; float2 uv : TEXCOORD0; float2 cell : TEXCOORD1; };
struct ShadowOut      { float4 pos : POSITION; float3 uvz : TEXCOORD0; float2 cell : TEXCOORD1; };

ShadowOut vs_shadow_world(ShadowWorldIn i) {
    ShadowOut o;
    o.pos = mul(float4(i.pos, 1.0), cLightVP);
    o.uvz = float3(i.uv, o.pos.z);
    o.cell = i.cell;
    return o;
}

struct ShadowModelIn { float3 pos : POSITION; float2 uv : TEXCOORD0; };
ShadowOut vs_shadow_model(ShadowModelIn i) {
    ShadowOut o;
    o.pos = mul(mul(float4(i.pos, 1.0), cWorld), cLightVP);
    o.uvz = float3(i.uv, o.pos.z);
    o.cell = float2(0, 0);
    return o;
}

sampler2D sShadowAlpha : register(s0);
float4 cShadowPs : register(c0);   // x: atlas cell size (uv), y: alpha ref (0..1)

// World geometry: the cutout tiles' alpha lives in an atlas of 64 px cells; cell
// (0,0) is solid, so the opaque tiles pass the same test.
float4 ps_shadow_world(ShadowOut i) : COLOR0 {
    float2 a = (i.cell + clamp(i.uvz.xy, 0.01, 0.99)) * cShadowPs.x;
    clip(tex2D(sShadowAlpha, a).a - 0.5);
    return float4(i.uvz.z, 0, 0, 1);
}
float4 ps_shadow_solid(ShadowOut i) : COLOR0 { return float4(i.uvz.z, 0, 0, 1); }
float4 ps_shadow_cutout(ShadowOut i) : COLOR0 {
    clip(tex2D(sShadowAlpha, i.uvz.xy).a - cShadowPs.y);
    return float4(i.uvz.z, 0, 0, 1);
}

// ---------------------------------------------------------------------------
// Full-screen passes. Positions arrive in clip space with the half-pixel shift
// already applied on the CPU.

struct QuadIn  { float4 pos : POSITION; float2 uv : TEXCOORD0; };
struct QuadOut { float4 pos : POSITION; float2 uv : TEXCOORD0; };
QuadOut vs_quad(QuadIn i) { QuadOut o; o.pos = i.pos; o.uv = i.uv; return o; }

// Shared by the passes that read the scene's depth (INTZ: the hardware depth as a texture).
float4 cProj   : register(c0);   // P33, P43, 1/P11, 1/P22
float4 cScreen : register(c1);   // 1/W, 1/H, W, H of the depth texture

float LinearZ(float d) { return cProj.y / (d - cProj.x); }
float3 ViewPos(float2 uv, float d) {
    float z = LinearZ(d);
    return float3((uv.x * 2.0 - 1.0) * z * cProj.z, (1.0 - uv.y * 2.0) * z * cProj.w, z);
}

sampler2D sScene  : register(s4);
sampler2D sDepth  : register(s1);
sampler2D sShadow : register(s2);
sampler2D sAo     : register(s3);

float DepthAt(float2 uv) { return tex2D(sDepth, uv).r; }

// The face normal from the depth buffer: of the two neighbours on each axis the
// one nearer in depth, so a silhouette edge does not bend the normal.
float3 ViewNormal(float2 uv, float3 p) {
    float2 dx = float2(cScreen.x, 0), dy = float2(0, cScreen.y);
    float3 pl = ViewPos(uv - dx, DepthAt(uv - dx));
    float3 pr = ViewPos(uv + dx, DepthAt(uv + dx));
    float3 pu = ViewPos(uv - dy, DepthAt(uv - dy));
    float3 pd = ViewPos(uv + dy, DepthAt(uv + dy));
    float3 ex = abs(pr.z - p.z) < abs(p.z - pl.z) ? pr - p : p - pl;
    float3 ey = abs(pd.z - p.z) < abs(p.z - pu.z) ? pd - p : p - pu;
    return normalize(cross(ex, ey));
}

// --- Sun shadow mask, one draw per cascade (each clips to its own depth range), into
// a full-resolution 8-bit target: R = what is left of the light (1 lit .. 0 black).
// Kept apart from the composite and small: this compiler copies every uniform into a
// temporary register, and a shader past r31 does not link under Wine's GLSL (the frame
// then went grey: the previous program, the AO blur, was drawn instead).
float4 cSunView    : register(c2);   // xyz: toward the sun, view space
float4 cSlice      : register(c3);   // this cascade's near and far view depth, fade start, 1/fade length
float4 cCascX      : register(c4);   // view -> atlas: columns for x, y, z
float4 cCascY      : register(c5);
float4 cCascZ      : register(c6);
float4 cShadowTex  : register(c7);   // atlas texel size, atlas size, depth bias, normal offset (view units)
float4 cSunAmb     : register(c8);   // ambient level, sun level (fixed-function light), shadow strength, PCF 16 (1) or 4 (0)

float ShadowTap(float2 uv, float z) { return step(z, tex2D(sShadow, uv).r); }

// A 3x3-texel box with bilinear edges: 16 point taps, smooth and stable.
float Pcf16(float3 c) {
    float2 t = c.xy * cShadowTex.y - 0.5;
    float2 b = floor(t);
    float2 f = t - b;
    float2 o = (b + 0.5) * cShadowTex.x;
    float4 wx = float4(1.0 - f.x, 1.0, 1.0, f.x);
    float4 wy = float4(1.0 - f.y, 1.0, 1.0, f.y);
    float s = cShadowTex.x;
    float4 r0 = float4(ShadowTap(o + float2(-s, -s), c.z), ShadowTap(o + float2(0, -s), c.z), ShadowTap(o + float2(s, -s), c.z), ShadowTap(o + float2(2 * s, -s), c.z));
    float4 r1 = float4(ShadowTap(o + float2(-s, 0), c.z), ShadowTap(o, c.z), ShadowTap(o + float2(s, 0), c.z), ShadowTap(o + float2(2 * s, 0), c.z));
    float4 r2 = float4(ShadowTap(o + float2(-s, s), c.z), ShadowTap(o + float2(0, s), c.z), ShadowTap(o + float2(s, s), c.z), ShadowTap(o + float2(2 * s, s), c.z));
    float4 r3 = float4(ShadowTap(o + float2(-s, 2 * s), c.z), ShadowTap(o + float2(0, 2 * s), c.z), ShadowTap(o + float2(s, 2 * s), c.z), ShadowTap(o + float2(2 * s, 2 * s), c.z));
    return (dot(r0, wx) * wy.x + dot(r1, wx) * wy.y + dot(r2, wx) * wy.z + dot(r3, wx) * wy.w) / 9.0;
}
float Pcf4(float3 c) {
    float2 t = c.xy * cShadowTex.y - 0.5;
    float2 b = floor(t);
    float2 f = t - b;
    float2 o = (b + 0.5) * cShadowTex.x;
    float a = ShadowTap(o, c.z), bb = ShadowTap(o + float2(cShadowTex.x, 0), c.z);
    float cc = ShadowTap(o + float2(0, cShadowTex.x), c.z), d = ShadowTap(o + cShadowTex.xx, c.z);
    return lerp(lerp(a, bb, f.x), lerp(cc, d, f.x), f.y);
}

float4 ps_shadowmask(QuadOut i) : COLOR0 {
    float d = DepthAt(i.uv);
    float3 p = ViewPos(i.uv, d);
    clip(p.z - cSlice.x);
    clip(cSlice.y - p.z);
    clip(0.999999 - d);
    float3 n = ViewNormal(i.uv, p);
    float ndl = dot(n, cSunView.xyz);
    float4 v4 = float4(p + n * cShadowTex.w, 1.0);
    float3 q = float3(dot(v4, cCascX), dot(v4, cCascY), dot(v4, cCascZ) - cShadowTex.z);
    float vis = cSunAmb.w > 0.5 ? Pcf16(q) : Pcf4(q);
    vis = lerp(vis, 1.0, saturate((p.z - cSlice.z) * cSlice.w));
    // What the sun added to this face in the fixed-function light, taken away where it is
    // shadowed; a face turned away is already at ambient and is not darkened twice.
    float sunPart = cSunAmb.y * saturate(ndl);
    float dark = saturate(cSunAmb.z * sunPart / max(cSunAmb.x + sunPart, 1e-3));
    float shade = 1.0 - dark * saturate(ndl * 5.0) * (1.0 - vis);
    return float4(shade, shade, shade, 1);
}

// --- Composite: the shadow mask, ambient occlusion and the sky's hemisphere over the frame.
float4 cFog        : register(c2);   // fog start, 1/(end-start), AO strength, effect blend
float4 cSkyTint    : register(c3);   // hemisphere colour from above; w: hemisphere amount
float4 cGroundTint : register(c4);   // ...from below
float4 cUpView     : register(c5);   // world up in view space; w: the first-person cockpit's reach (view depth, 0 none)

float4 ps_composite(QuadOut i) : COLOR0 {
    float4 scene = tex2D(sScene, i.uv);
    float d = DepthAt(i.uv);
    if (d >= 0.999999) return scene;   // the sky
    float3 p = ViewPos(i.uv, d);
    float3 n = ViewNormal(i.uv, p);
    float up = dot(n, cUpView.xyz) * 0.5 + 0.5;
    float3 tint = lerp(float3(1, 1, 1), lerp(cGroundTint.rgb, cSkyTint.rgb, up), cSkyTint.w);
    float ao = lerp(1.0, tex2D(sAo, i.uv).r, cFog.z);
    // FIX-COCKPIT-CAB-4: the cockpit (nearer than its reach) takes no AO and no hemisphere: depth-rebuilt normals are noise there.
    float cab = saturate((cUpView.w - p.z) * 1000.0);
    ao = lerp(ao, 1.0, cab); tint = lerp(tint, float3(1, 1, 1), cab);
    float shade = tex2D(sShadow, i.uv).r;
    float3 m = shade * ao * tint;
    // Fogged distance keeps the fog's colour: the modulation fades out with it.
    float fog = saturate((p.z - cFog.x) * cFog.y);
    m = lerp(m, float3(1, 1, 1), fog);
    m = lerp(float3(1, 1, 1), m, cFog.w);
    return float4(scene.rgb * m, scene.a);
}

// --- Ambient occlusion at half resolution: a normal-oriented hemisphere of samples
// in view space, compared against the depth buffer, with a range check.
float4 cAo : register(c2);   // radius (view units), bias, intensity, max distance
float4 cAoNoise : register(c3);   // x: 1 = the 4x4 stratified rotations (FIX-CAR-SHADING-2), 0 = per-pixel hash (the old pass)

float AoSample(float3 p, float3 sampleDir, float radius, float bias) {
    float3 s = p + sampleDir * radius;
    float2 uv = float2(s.x / (s.z * cProj.z) * 0.5 + 0.5, 0.5 - s.y / (s.z * cProj.w) * 0.5);
    float sz = LinearZ(DepthAt(uv));
    float range = saturate(radius / max(abs(p.z - sz), 1e-4));
    return step(sz, s.z - bias) * range;
}

float Hash(float2 v) { return frac(sin(dot(v, float2(12.9898, 78.233))) * 43758.5453); }

float SsaoAt(float2 uv, float2 vpos, int count) {
    // pmy3 (FIX-WORLD-10): this pass runs at half resolution, so each pixel's uv falls exactly on
    // the edge between two full-resolution depth texels; the point sample took one or the other as
    // float rounding fell, in a pattern repeating every few pixels across the screen. A vertical wall
    // seen by a level camera has one depth down each screen column, so the wrong pick became thin
    // vertical stripes of false occlusion on every wall (strongest on a wall the eye walks along).
    // Snap to one texel's centre, and widen the depth bias by the surface's own depth step per
    // texel: a sample's depth is read at the centre of the texel it lands in, half a texel's
    // slope away from where the sample is, which on a wall seen edge-on beat the fixed bias.
    uv = (floor(uv * cScreen.zw - 0.25) + 0.5) * cScreen.xy;
    float d = DepthAt(uv);
    if (d >= 0.999999) return 1.0;
    float3 p = ViewPos(uv, d);
    if (p.z > cAo.w) return 1.0;
    float3 n = ViewNormal(uv, p);
    float zl = LinearZ(DepthAt(uv - float2(cScreen.x, 0))), zr = LinearZ(DepthAt(uv + float2(cScreen.x, 0)));
    float zu = LinearZ(DepthAt(uv - float2(0, cScreen.y))), zd = LinearZ(DepthAt(uv + float2(0, cScreen.y)));
    float slope = min(abs(zr - p.z), abs(p.z - zl)) + min(abs(zd - p.z), abs(p.z - zu));
    float bias = cAo.y + min(slope, 0.25);
    // FIX-CAR-SHADING-2 (coord82): the kernel's rotation. The per-pixel hash (white noise) left each
    // pixel's 8-12 samples a random subset; where a surface is partly occluded (a car's flank over the
    // road, its bonnet under the screen) the 3x3 blur could not average that out and pale paint showed
    // it as grey clouds. A 4x4 Bayer order of 16 evenly spaced rotations instead, which ps_ao_blur4's
    // 4x4 footprint integrates exactly: every output pixel sees all 16, the noise cancels.
    float2 c4 = fmod(floor(vpos), 4.0), c2 = fmod(c4, 2.0), h2 = floor(c4 * 0.5);
    float bayer = 4.0 * fmod(2.0 * c2.x + 3.0 * c2.y, 4.0) + fmod(2.0 * h2.x + 3.0 * h2.y, 4.0);
    float a = lerp(Hash(floor(vpos)), (bayer + 0.5) / 16.0, cAoNoise.x) * 6.2831853;
    float3 rnd = float3(cos(a), sin(a), 0);
    float3 t = normalize(rnd - n * dot(rnd, n));
    float3 b = cross(n, t);
    // A fixed kernel in the tangent frame, denser near the centre.
    const float3 k[12] = {
        float3( 0.53,  0.18, 0.28), float3(-0.32,  0.44, 0.42), float3(-0.22, -0.48, 0.20), float3( 0.34, -0.31, 0.55),
        float3( 0.14,  0.76, 0.30), float3(-0.71,  0.08, 0.35), float3( 0.08, -0.12, 0.17), float3( 0.82, -0.36, 0.12),
        float3(-0.47, -0.62, 0.40), float3( 0.29,  0.25, 0.80), float3(-0.10,  0.27, 0.12), float3(-0.55,  0.58, 0.18)};
    float occ = 0;
    [unroll] for (int j = 0; j < count; ++j) {
        float3 v = t * k[j].x + b * k[j].y + n * k[j].z;
        occ += AoSample(p, v, cAo.x, bias);
    }
    float ao = 1.0 - occ / count * cAo.z;
    float fade = saturate((cAo.w - p.z) / (cAo.w * 0.25));
    return lerp(1.0, saturate(ao), fade);
}
float4 ps_ssao8(QuadOut i, float2 vpos : VPOS) : COLOR0 { float a = SsaoAt(i.uv, vpos, 8); return float4(a, a, a, 1); }
float4 ps_ssao12(QuadOut i, float2 vpos : VPOS) : COLOR0 { float a = SsaoAt(i.uv, vpos, 12); return float4(a, a, a, 1); }

// Depth-aware 3x3 blur of the half-resolution AO (s0 AO, s1 depth).
float4 cBlur : register(c2);   // texel of the AO target (xy)
sampler2D sAoIn : register(s4);
void BlurTap(float2 uv, float zc, inout float sum, inout float wsum) {
    float z = LinearZ(DepthAt(uv));
    float w = saturate(1.0 / (1e-3 + abs(z - zc) / max(zc, 0.1) * 40.0));
    sum += tex2D(sAoIn, uv).r * w;
    wsum += w;
}
float4 ps_ao_blur(QuadOut i) : COLOR0 {
    float zc = LinearZ(DepthAt(i.uv));
    float sum = 0, wsum = 0;
    float2 t = cBlur.xy;
    BlurTap(i.uv + float2(-t.x, -t.y), zc, sum, wsum); BlurTap(i.uv + float2(0, -t.y), zc, sum, wsum); BlurTap(i.uv + float2(t.x, -t.y), zc, sum, wsum);
    BlurTap(i.uv + float2(-t.x, 0), zc, sum, wsum);    BlurTap(i.uv, zc, sum, wsum);                   BlurTap(i.uv + float2(t.x, 0), zc, sum, wsum);
    BlurTap(i.uv + float2(-t.x, t.y), zc, sum, wsum);  BlurTap(i.uv + float2(0, t.y), zc, sum, wsum);  BlurTap(i.uv + float2(t.x, t.y), zc, sum, wsum);
    float a = sum / max(wsum, 1e-4);
    return float4(a, a, a, 1);
}
// FIX-CAR-SHADING-2: the same depth-aware weights over a 4x4 footprint (texels -2..+1), the period
// of the SSAO's rotation pattern, so a flat or gently curved surface takes the mean of all 16.
float4 ps_ao_blur4(QuadOut i) : COLOR0 {
    float zc = LinearZ(DepthAt(i.uv));
    float sum = 0, wsum = 0;
    float2 t = cBlur.xy;
    BlurTap(i.uv + float2(-2, -2) * t, zc, sum, wsum); BlurTap(i.uv + float2(-1, -2) * t, zc, sum, wsum); BlurTap(i.uv + float2(0, -2) * t, zc, sum, wsum); BlurTap(i.uv + float2(1, -2) * t, zc, sum, wsum);
    BlurTap(i.uv + float2(-2, -1) * t, zc, sum, wsum); BlurTap(i.uv + float2(-1, -1) * t, zc, sum, wsum); BlurTap(i.uv + float2(0, -1) * t, zc, sum, wsum); BlurTap(i.uv + float2(1, -1) * t, zc, sum, wsum);
    BlurTap(i.uv + float2(-2, 0) * t, zc, sum, wsum); BlurTap(i.uv + float2(-1, 0) * t, zc, sum, wsum); BlurTap(i.uv + float2(0, 0) * t, zc, sum, wsum); BlurTap(i.uv + float2(1, 0) * t, zc, sum, wsum);
    BlurTap(i.uv + float2(-2, 1) * t, zc, sum, wsum); BlurTap(i.uv + float2(-1, 1) * t, zc, sum, wsum); BlurTap(i.uv + float2(0, 1) * t, zc, sum, wsum); BlurTap(i.uv + float2(1, 1) * t, zc, sum, wsum);
    float a = sum / max(wsum, 1e-4);
    return float4(a, a, a, 1);
}

// --- Night lights: one quad per light, summed into a light buffer (no albedo); then
// ps_light_apply adds albedo x the sum, the sum bounded first (FIX-FX, pm26/pm31: summed
// additive pools clipped walls to flat white, pure red/blue or saturated yellow). The
// light's parameters ride in the vertices. Albedo is the frame's colour over the ambient
// level it was drawn with.
struct LightIn  { float4 pos : POSITION; float4 posRadius : TEXCOORD0; float4 colour : TEXCOORD1; float4 spot : TEXCOORD2; };
struct LightOut { float4 pos : POSITION; float4 posRadius : TEXCOORD0; float4 colour : TEXCOORD1; float4 spot : TEXCOORD2; };
LightOut vs_light(LightIn i) { LightOut o; o.pos = i.pos; o.posRadius = i.posRadius; o.colour = i.colour; o.spot = i.spot; return o; }

float4 cLight : register(c2);   // 1/ambient level (albedo estimate), albedo cap, fog start, 1/(fog end-start)
float4 ps_light(LightOut i, float2 vpos : VPOS) : COLOR0 {
    float2 uv = (vpos + 0.5) * cScreen.xy;
    float d = DepthAt(uv);
    if (d >= 0.999999) return float4(0, 0, 0, 0);
    float3 p = ViewPos(uv, d);
    float3 l = i.posRadius.xyz - p;
    float dist = length(l);
    float r = i.posRadius.w;
    if (dist >= r) return float4(0, 0, 0, 0);
    l /= max(dist, 1e-4);
    float3 n = ViewNormal(uv, p);
    // Soft falloff that reaches zero at the radius: (1 - (d/r)^2)^2 / (1 + 4 (d/r)^2).
    float x = dist / r;
    float att = (1.0 - x * x);
    att = att * att / (1.0 + 4.0 * x * x);
    // Wrap a little so the ground right under a lamp reads lit even when the depth normal is noisy.
    float ndl = saturate((dot(n, l) + 0.25) / 1.25);
    float cone = 1.0;
    if (i.spot.w > -1.5) {   // a spot: w is cos of the half angle
        float c = dot(-l, i.spot.xyz);
        cone = saturate((c - i.spot.w) / max(1.0 - i.spot.w, 1e-3) * 2.5);
        cone *= cone;
    }
    float fog = 1.0 - saturate((p.z - cLight.z) * cLight.w);
    return float4(i.colour.rgb * (att * ndl * cone * fog), 0);
}

// The light buffer applied: lit += albedo x bound(sum). The bound keeps the hue of the sum
// (a siren still tints red) and rolls its strongest channel off towards cApply.x, so
// overlapping pools never pass it; a saturated light gives up some of its purity as it
// grows (cApply.y) the way a real bright source reads near-white at its core. Albedo
// times light, so brick stays brick under a pool.
sampler2D sLightSum : register(s5);
float4 cApply : register(c3);   // ceiling of the summed light, whitening of a strong light, knee, -
float4 ps_light_apply(QuadOut i) : COLOR0 {
    float3 L = tex2D(sLightSum, i.uv).rgb;
    float m = max(L.r, max(L.g, L.b));
    if (m <= 1e-4) return float4(0, 0, 0, 0);
    float cap = cApply.x, knee = cApply.z;
    // The strongest channel: as it was up to the knee, then an exponential roll-off to the cap.
    float mb = m <= knee ? m : knee + (cap - knee) * (1.0 - exp(-(m - knee) / (cap - knee)));
    float3 hue = L / m;
    float white = cApply.y * saturate(mb / cap);
    float3 paler = 0.5 * hue + 0.5 * dot(hue, float3(0.3, 0.5, 0.2));
    float3 Lb = mb * lerp(hue, paler, white);
    float3 albedo = min(tex2D(sScene, i.uv).rgb * cLight.x, cLight.y);
    // A floor of albedo so black asphalt still shows the pool of light.
    albedo = max(albedo, 0.08);
    return float4(albedo * Lb, 0);
}

// --- Bloom: a soft-knee bright pass at half resolution, a separable Gaussian.
float4 cBright : register(c0);   // threshold, knee, source texel x, source texel y
sampler2D sSrc : register(s4);
float4 ps_bright(QuadOut i) : COLOR0 {
    float2 h = cBright.zw;
    float3 c = tex2D(sSrc, i.uv + float2(-h.x, -h.y)).rgb + tex2D(sSrc, i.uv + float2(h.x, -h.y)).rgb +
               tex2D(sSrc, i.uv + float2(-h.x, h.y)).rgb + tex2D(sSrc, i.uv + float2(h.x, h.y)).rgb;
    c *= 0.25;
    float lum = max(c.r, max(c.g, c.b));
    float soft = clamp(lum - cBright.x + cBright.y, 0, 2 * cBright.y);
    soft = soft * soft / (4 * cBright.y + 1e-4);
    float w = max(soft, lum - cBright.x) / max(lum, 1e-4);
    return float4(c * w, 1);
}
float4 cDir : register(c0);   // texel step along the blur direction (xy)
float4 ps_blur(QuadOut i) : COLOR0 {
    float3 c = tex2D(sSrc, i.uv).rgb * 0.2270270;
    c += (tex2D(sSrc, i.uv + cDir.xy * 1.3846154).rgb + tex2D(sSrc, i.uv - cDir.xy * 1.3846154).rgb) * 0.3162162;
    c += (tex2D(sSrc, i.uv + cDir.xy * 3.2307692).rgb + tex2D(sSrc, i.uv - cDir.xy * 3.2307692).rgb) * 0.0702703;
    return float4(c, 1);
}

// --- Final: exposure, bloom, a filmic shoulder that leaves the mid tones alone,
// a little saturation so the GTA2 palette stays loud; blended with the raw frame
// by the view transition's weight.
float4 cFinal  : register(c0);   // exposure, bloom strength, saturation, effect blend
float4 cCurve  : register(c1);   // shoulder start, toe strength, tonemap on (1/0), bloom2 strength
sampler2D sLit    : register(s4);
sampler2D sBloom  : register(s1);
sampler2D sRaw    : register(s2);
sampler2D sBloom2 : register(s3);
float3 Shoulder(float3 x, float k) {
    float3 over = max(x - k, 0);
    return min(x, k) + (1.0 - k) * (1.0 - exp(-over / (1.0 - k)));
}
float4 ps_final(QuadOut i) : COLOR0 {
    float3 lit = tex2D(sLit, i.uv).rgb;
    float3 c = lit + tex2D(sBloom, i.uv).rgb * cFinal.y + tex2D(sBloom2, i.uv).rgb * cCurve.w;
    c *= cFinal.x;
    if (cCurve.z > 0.5) {
        c = Shoulder(c, cCurve.x);
        // A gentle toe: deepens the darks a little without crushing them.
        float3 s = c * c * (3.0 - 2.0 * c);
        c = lerp(c, s, cCurve.y);
        float lum = dot(c, float3(0.2126, 0.7152, 0.0722));
        c = max(lerp(float3(lum, lum, lum), c, cFinal.z), 0);
    } else {
        c = saturate(c);
    }
    float3 raw = tex2D(sRaw, i.uv).rgb;
    return float4(lerp(saturate(raw), c, cFinal.w), 1);
}
