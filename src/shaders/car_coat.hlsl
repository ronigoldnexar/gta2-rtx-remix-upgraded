// FIX-CAR-SHADING-1: the car paint's coat (dll/src/model_store.cpp CarCoat*, docs/vehicle-shading.md).
//
// A second pass over each car body mesh, drawn right after the fixed-function draw that lit and tinted it,
// blended ONE, SRCALPHA: frame = coat.rgb + frame * coat.a. It adds what the fixed-function light cannot:
//   - a clear coat: Fresnel (Schlick, F0 ~0.04) reflection of the sky above a horizon line and the street
//     below it, the reflection taking (1 - F) of the base, and a sharp sun highlight per pixel;
//   - the base coat's own broad sheen in the paint's colour, with a faint flake grain;
//   - edge definition from the surface's curvature (screen-space derivatives of the normal against the
//     position): concave creases (panel joins, arches, window seals) darken, convex edges catch the sky.
// The base colour (identity.cpp's paint tint) is the fixed-function draw's: on a lid seen from above F is
// F0 and the coat changes the paint's level by a few percent at most (the paint gate measures it).
//
// Plain renderer only (never under RTX Remix: the path tracer has the layer's PBR maps). Shader model 3,
// compiled offline by tools/build_car_coat_shader.sh into src/shaders/car_coat_gen.h; loop-free.
// World space: x east, y up, z north, one unit per block. Matrices row_major, row vectors (math3d.h).

row_major float4x4 cWvp   : register(c0);
row_major float4x4 cWorld : register(c4);
row_major float3x3 cNrm   : register(c8);    // inverse transpose of the world's 3x3 (rows c8..c10)
float4 cViewZ             : register(c11);   // view-space depth = dot(world pos, cViewZ.xyz) + cViewZ.w

struct CoatVsIn  { float3 pos : POSITION; float3 nrm : NORMAL; float2 uv : TEXCOORD0; };
struct CoatVsOut { float4 pos : POSITION; float3 w : TEXCOORD0; float3 n : TEXCOORD1; float3 uvd : TEXCOORD2; float3 o : TEXCOORD3; };
struct CoatPsIn  { float3 w : TEXCOORD0; float3 n : TEXCOORD1; float3 uvd : TEXCOORD2; float3 o : TEXCOORD3; };

CoatVsOut vs_coat(CoatVsIn i) {
    CoatVsOut o;
    o.pos = mul(float4(i.pos, 1.0), cWvp);
    float4 w = mul(float4(i.pos, 1.0), cWorld);
    o.w = w.xyz;
    o.n = mul(i.nrm, cNrm);
    o.uvd = float3(i.uv, dot(w.xyz, cViewZ.xyz) + cViewZ.w);
    o.o = i.pos;
    return o;
}

sampler2D sBody : register(s0);   // the mesh's own texture (paint or rest half)
sampler2D sMask : register(s1);   // VEHICLE-GLASS's cut mask (alpha 0 on glass), when cMode.z = 1

float4 cCam     : register(c0);   // xyz camera
float4 cSun     : register(c1);   // xyz toward the sun, w sun highlight strength (0 at night)
float4 cSunCol  : register(c2);   // rgb sun colour (the body pass's sun x the hour)
float4 cZenith  : register(c3);   // rgb sky overhead (as reflected)
float4 cHorizon : register(c4);   // rgb sky at the horizon
float4 cGround  : register(c5);   // rgb street below the horizon, w the sky's radiance over the paint (HDR)
float4 cFog     : register(c6);   // rgb fog colour, w 1 when the fog is on
float4 cFogR    : register(c7);   // x start, y end, z 1/(end-start)
float4 cTint    : register(c8);   // rgb the paint's tint (x2 stage), w the coat's weight on this mesh
float4 cTune    : register(c9);   // x F0, y reflection strength, z coat highlight power, w curvature strength
float4 cMode    : register(c10);  // x alpha-tested, y soft paint (coverage = paint), z glass mask bound, w flake
float4 cTune2   : register(c11);  // x base sheen power, y base sheen strength, z curvature scale (blocks), w rest-half weight
float4 cDebug   : register(c12);  // x 1: show the curvature
float4 cTex     : register(c13);
float4 cWet     : register(c14);  // WEATHER-V2: x wetness 0..1 ([weather] on, street views; 0 = the dry coat exactly)  // xy one texel of sBody (u, v), z groove strength (0: none), w groove threshold

float hash3(float3 p) { return frac(sin(dot(p, float3(12.9898, 78.233, 37.719))) * 43758.5453); }

float4 ps_coat(CoatPsIn i) : COLOR0 {
    float4 tex = tex2D(sBody, i.uvd.xy);
    float alpha = cMode.y > 0.5 ? 1.0 : tex.a;
    if (cMode.z > 0.5) alpha *= tex2D(sMask, i.uvd.xy).a;
    if (cMode.x > 0.5 || cMode.z > 0.5) clip(alpha - 0.5);
    // Paint (1) or the rest of the body (trim, lamps, baked glass): the coat is thinner on the rest.
    float paint = cMode.y > 0.5 ? tex.a : 1.0;
    float weight = cTint.w * lerp(cTune2.w, 1.0, paint);

    float3 v = cCam.xyz - i.w;
    float dist = length(v);
    v = v / max(dist, 1e-4);
    // A zero normal (a degenerate vertex of a generated mesh) would make the pass NaN: the eye's direction then.
    float nl = length(i.n);
    float3 n0 = nl > 1e-5 ? i.n / nl : v;
    // Curvature: the normal's change against the position's along both screen axes (1/radius, blocks),
    // taken before any flip so the 2x2 quad agrees.
    float3 dnx = ddx(n0), dny = ddy(n0), dpx = ddx(i.w), dpy = ddy(i.w);
    float k = dot(dnx, dpx) / max(dot(dpx, dpx), 1e-10) + dot(dny, dpy) / max(dot(dpy, dpy), 1e-10);
    // A face seen from behind (the generated meshes' winding is not reliable): its other side.
    float side = dot(n0, v) < 0.0 ? -1.0 : 1.0;
    float3 n = n0 * side;
    k *= side;
    float ndv = dot(n, v);
    float kc = clamp(k * cTune2.z, -1.0, 1.0);   // > 0 convex edge, < 0 concave crease
    float crease = saturate(-kc) * cTune.w;
    float edge = saturate(kc) * cTune.w;

    // Clear coat: Schlick Fresnel, reflection of the street (below the horizon), a skyline of buildings (a
    // blocky band whose height steps with the reflection's bearing, so it slides across the body as the car
    // turns) and the sky's gradient above it. The sky is brighter than any paint (cTune2.y's radiance).
    float fr = cTune.x + (1.0 - cTune.x) * pow(1.0 - saturate(ndv), 5.0);
    fr = saturate(fr + edge * 0.06);
    // Wet paint (WEATHER-V2): a film of water on the coat - more reflection at every angle.
    fr = saturate(fr + cWet.x * 0.15 * (1.0 - fr));
    float3 r = reflect(-v, n);
    float up = r.y;
    float bearing = atan2(r.x, r.z) * 3.0;   // ~19 blocks of skyline around the compass
    float cellB = floor(bearing * 2.0);
    float skyline = 0.10 + 0.32 * hash3(float3(cellB, 1.7, 3.1)) * hash3(float3(cellB, 5.3, 0.9));
    // The zenith is the darker part of the sky (half the horizon's radiance), and the reflection keeps half
    // of the sky's colour: a lid seen from above (the classic camera) keeps the sprite's hue and level.
    float3 sky = lerp(cHorizon.rgb, cZenith.rgb * 0.5, sqrt(saturate(up))) * cGround.w;
    float3 town = cHorizon.rgb * (0.42 + 0.18 * hash3(float3(cellB, 2.3, 7.7)));
    float3 env = lerp(town, sky, smoothstep(skyline - 0.015, skyline + 0.015, up));
    env = lerp(cGround.rgb, env, smoothstep(-0.03, 0.01, up));
    env = lerp(dot(env, float3(0.2126, 0.7152, 0.0722)).xxx, env, 0.5);

    // Sun: a sharp coat glint, a softer coat halo, and the base coat's broad sheen in the paint's colour.
    float3 l = cSun.xyz;
    float ndl = saturate(dot(n, l));
    float3 h = normalize(l + v);
    float ndh = saturate(dot(n, h));
    float coatSpec = (pow(ndh, cTune.z) * (cTune.z + 8.0) * 0.0398 * ndl + pow(ndh, 48.0) * 0.35 * ndl) * (1.0 + cWet.x * 0.8);
    float3 albedo = tex.rgb * cTint.rgb;
    // Flake: a per-cell glint in the sheen, faded out where a cell is smaller than about a pixel.
    float cell = 900.0;
    float fw = length(fwidth(i.o)) * cell;
    float flake = (hash3(floor(i.o * cell)) - 0.5) * cMode.w * saturate(1.5 - fw);
    float sheen = pow(ndh, cTune2.x) * cTune2.y * ndl * (1.0 + flake * 2.0);
    float3 add = env * fr * cTune.y + cSunCol.rgb * (coatSpec * cSun.w * (fr + 0.04) * 6.0 + sheen * albedo * 2.0);
    add += cHorizon.rgb * edge * 0.10 * paint;   // a convex edge catches the light from all around

    // Panel gaps: the seams the texture paints (door, bonnet and boot lines, the generated atlases' and the kits'
    // own) are thin dark valleys of the luminance: a 4-tap Laplacian against the local level finds them. A gap
    // is darker still and breaks the coat's reflection (the cue that makes a line read as a cut in the metal).
    // Faded where a texel is smaller than a pixel (no crawling at range).
    float3 lw = float3(0.2126, 0.7152, 0.0722);
    float l0 = dot(tex.rgb, lw);
    float ln = dot(tex2D(sBody, i.uvd.xy + float2(cTex.x, 0.0)).rgb, lw) + dot(tex2D(sBody, i.uvd.xy - float2(cTex.x, 0.0)).rgb, lw) +
               dot(tex2D(sBody, i.uvd.xy + float2(0.0, cTex.y)).rgb, lw) + dot(tex2D(sBody, i.uvd.xy - float2(0.0, cTex.y)).rgb, lw);
    float lap = (ln * 0.25 - l0) / max(ln * 0.25, 0.04);
    float texelPx = length(fwidth(i.uvd.xy) / max(cTex.xy, 1e-6));
    float gap = saturate((lap - cTex.w) * 4.0) * cTex.z * saturate(2.0 - texelPx);

    float keep = (1.0 - fr * weight) * (1.0 - crease * 0.55 * paint) * (1.0 - 0.45 * gap) * (1.0 - cWet.x * 0.03 * paint * weight);
    add *= weight * (1.0 - gap);

    // The fixed-function frame under it is fogged (table fog, linear in view depth): fog the coat's own
    // light and take the base's part of the fog colour with the base it scales.
    float fogK = cFog.w > 0.5 ? saturate((cFogR.y - i.uvd.z) * cFogR.z) : 1.0;
    float3 rgb = add * fogK + cFog.rgb * (1.0 - fogK) * (1.0 - keep);
    // [devtools] car_coat=2: the curvature (red convex, blue concave) over a grey body.
    if (cDebug.x > 0.5) return float4(saturate(kc), 0.25, saturate(-kc), 0.0);
    return float4(rgb, keep);
}
