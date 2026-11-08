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

sampler2D sScene  : register(s0);
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

// --- Composite: shadows, ambient occlusion and the sky's hemisphere over the frame.
float4 cSunView    : register(c2);   // xyz: toward the sun, view space; w: shadow strength 0..1
float4 cSplits     : register(c3);   // far distance of cascades 0,1,2; w: cascade count
float4 cFog        : register(c4);   // fog start, 1/(end-start), AO strength, effect blend
float4 cSkyTint    : register(c5);   // hemisphere colour from above; w: hemisphere amount
float4 cGroundTint : register(c6);   // ...from below
float4 cUpView     : register(c7);   // world up in view space
row_major float4x4 cCascade[3] : register(c8);   // view -> atlas (uv in xy, depth in z)
float4 cShadowTex  : register(c20);  // atlas texel size, atlas size, depth bias, PCF taps (4 or 16)
float4 cOffsets    : register(c21);  // normal offset (view units) per cascade; w: unused
float4 cSunAmb     : register(c22);  // ambient level, sun level (fixed-function light), shadow strength

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
    float sum = dot(r0, wx) * wy.x + dot(r1, wx) * wy.y + dot(r2, wx) * wy.z + dot(r3, wx) * wy.w;
    return sum / 9.0;
}
// Bilinear PCF only (the low tier).
float Pcf4(float3 c) {
    float2 t = c.xy * cShadowTex.y - 0.5;
    float2 b = floor(t);
    float2 f = t - b;
    float2 o = (b + 0.5) * cShadowTex.x;
    float a = ShadowTap(o, c.z), bb = ShadowTap(o + float2(cShadowTex.x, 0), c.z);
    float cc = ShadowTap(o + float2(0, cShadowTex.x), c.z), d = ShadowTap(o + cShadowTex.xx, c.z);
    return lerp(lerp(a, bb, f.x), lerp(cc, d, f.x), f.y);
}

float SunVisibility(float3 p, float3 n) {
    // Floats only: this compiler's shader model 3 path has no integer or boolean arithmetic.
    float in1 = step(cSplits.x, p.z), in2 = step(cSplits.y, p.z);
    float k = in1 + in2;                                   // cascade 0, 1 or 2
    float off = lerp(lerp(cOffsets.x, cOffsets.y, in1), cOffsets.z, in2);
    float far = lerp(lerp(cSplits.x, cSplits.y, in1), cSplits.z, in2);
    float3 q0 = mul(float4(p + n * off, 1.0), cCascade[0]).xyz;
    float3 q1 = mul(float4(p + n * off, 1.0), cCascade[1]).xyz;
    float3 q2 = mul(float4(p + n * off, 1.0), cCascade[2]).xyz;
    float3 q = lerp(lerp(q0, q1, in1), q2, in2);
    q.z -= cShadowTex.z;
    float v = cShadowTex.w > 8 ? Pcf16(q) : Pcf4(q);
    // Beyond the last cascade: lit. The last one fades out over its final fifth.
    float beyond = step(cSplits.w - 0.5, k);
    float last = step(cSplits.w - 1.5, k);
    v = lerp(v, 1.0, last * saturate((p.z - far * 0.8) / (far * 0.2)));
    return lerp(v, 1.0, beyond);
}

float4 ps_composite(QuadOut i) : COLOR0 {
    float4 scene = tex2D(sScene, i.uv);
    float d = DepthAt(i.uv);
    if (d >= 0.999999) return scene;   // the sky
    float3 p = ViewPos(i.uv, d);
    float3 n = ViewNormal(i.uv, p);
    float ndl = dot(n, cSunView.xyz);
    float shade = 1.0;
    // Sun shadow: only where the face turns toward the sun; a face turned away is
    // already at ambient in the fixed-function light and must not darken twice.
    float facing = saturate(ndl * 5.0);
    float vis = cSunView.w > 0.0 ? SunVisibility(p, n) : 1.0;
    // What the sun added to this face in the fixed-function light, taken away where it is shadowed.
    float sunPart = cSunAmb.y * saturate(ndl);
    float dark = saturate(cSunAmb.z * sunPart / max(cSunAmb.x + sunPart, 1e-3));
    shade *= 1.0 - dark * facing * (1.0 - vis);
    // Hemisphere: a touch of the sky's colour on faces looking up, of the ground's on faces looking down.
    float up = dot(n, cUpView.xyz) * 0.5 + 0.5;
    float3 hemi = lerp(cGroundTint.rgb, cSkyTint.rgb, up);
    float3 tint = lerp(float3(1, 1, 1), hemi, cSkyTint.w);
    float ao = cFog.z > 0.0 ? lerp(1.0, tex2D(sAo, i.uv).r, cFog.z) : 1.0;
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

float AoSample(float3 p, float3 sampleDir, float radius) {
    float3 s = p + sampleDir * radius;
    float2 uv = float2(s.x / (s.z * cProj.z) * 0.5 + 0.5, 0.5 - s.y / (s.z * cProj.w) * 0.5);
    float sz = LinearZ(DepthAt(uv));
    float range = saturate(radius / max(abs(p.z - sz), 1e-4));
    return step(sz, s.z - cAo.y) * range;
}

float Hash(float2 v) { return frac(sin(dot(v, float2(12.9898, 78.233))) * 43758.5453); }

float SsaoAt(float2 uv, float2 vpos, int count) {
    float d = DepthAt(uv);
    if (d >= 0.999999) return 1.0;
    float3 p = ViewPos(uv, d);
    if (p.z > cAo.w) return 1.0;
    float3 n = ViewNormal(uv, p);
    float a = Hash(floor(vpos)) * 6.2831853;
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
        occ += AoSample(p, v, cAo.x);
    }
    float ao = 1.0 - occ / count * cAo.z;
    float fade = saturate((cAo.w - p.z) / (cAo.w * 0.25));
    return lerp(1.0, saturate(ao), fade);
}
float4 ps_ssao8(QuadOut i, float2 vpos : VPOS) : COLOR0 { float a = SsaoAt(i.uv, vpos, 8); return float4(a, a, a, 1); }
float4 ps_ssao12(QuadOut i, float2 vpos : VPOS) : COLOR0 { float a = SsaoAt(i.uv, vpos, 12); return float4(a, a, a, 1); }

// Depth-aware 3x3 blur of the half-resolution AO (s0 AO, s1 depth).
float4 cBlur : register(c2);   // texel of the AO target (xy)
sampler2D sAoIn : register(s0);
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

// --- Night lights: one quad per light, added over the lit frame. The light's
// parameters ride in the vertices. Albedo is the frame's colour over the
// ambient level it was drawn with.
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
    float3 albedo = min(tex2D(sScene, uv).rgb * cLight.x, cLight.y);
    // A floor of albedo so black asphalt still shows the pool of light.
    albedo = max(albedo, 0.08);
    float fog = 1.0 - saturate((p.z - cLight.z) * cLight.w);
    return float4(albedo * i.colour.rgb * (att * ndl * cone * fog), 0);
}

// --- Bloom: a soft-knee bright pass at half resolution, a separable Gaussian.
float4 cBright : register(c0);   // threshold, knee, source texel x, source texel y
sampler2D sSrc : register(s0);
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
sampler2D sLit    : register(s0);
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
