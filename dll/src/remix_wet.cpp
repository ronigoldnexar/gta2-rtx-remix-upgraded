// WEATHER-V2 phase 0 experiment: wet film and puddles on the ground lids under RTX Remix.
// See remix_wet.h. Settings ([devtools], re-read once a second, so one session A/Bs them):
//   wx_wet_mode     0 off | 1 opaque film as a decal | 2 translucent water film | 3 opaque film, blended, not a decal
//   wx_wet_alpha    0..255 the film's alpha (the fade)          wx_wet_rough    film roughness, percent
//   wx_wet_albedo   film albedo, percent (black = darkening)    wx_puddle_alpha 0..255 puddles (0 none)
//   wx_puddle_rough puddle roughness, percent                   wx_decal_bits   category bits for the decal draws
//   wx_tfactor_blend 1: isTextureFactorBlend on the film's draw
#include "remix_wet.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "log.h"
#include "remix_api.h"

#include "../../src/gta2_map.h"

namespace gta2dx9 {
namespace {

struct Settings {
    int mode = 0, alpha = 160, rough = 8, albedo = 0, puddleAlpha = 0, puddleRough = 2;
    int decalBits = 1 << 11, tfBlend = 0;
    int alphaSrc = 3, vcolorAlpha = 255, filmStatic = 0;
    int waterIor = 133, waterTrans = 80;
    int liftMilli = 4;
};
Settings g_set;
float g_lift = 0.004f;   // blocks over the lid ([devtools] wx_lift_milli)
DWORD g_lastRead = 0;
char g_ini[MAX_PATH] = "";
int g_generation = 1;   // bumps when a material setting changes: meshes are rebuilt

remixapi_MaterialHandle g_film = nullptr, g_water = nullptr, g_puddle = nullptr;
int g_filmGen = 0, g_waterGen = 0, g_puddleGen = 0;
std::map<uint64_t, remixapi_MeshHandle> g_meshes;   // (kind, chunk, generation) -> mesh
std::wstring g_puddlePath;

int Dev(const char* key, int def) { return GetPrivateProfileIntA("devtools", key, def, g_ini); }

void ReadSettings() {
    if (!g_ini[0]) {
        GetModuleFileNameA(nullptr, g_ini, MAX_PATH);
        char* slash = strrchr(g_ini, '\\');
        if (slash) strcpy(slash + 1, "gta2dx9.ini"); else strcpy(g_ini, "gta2dx9.ini");
    }
    Settings s;
    s.mode = Dev("wx_wet_mode", 0);
    s.alpha = (std::max)(0, (std::min)(255, Dev("wx_wet_alpha", 160)));
    s.rough = Dev("wx_wet_rough", 8);
    s.albedo = Dev("wx_wet_albedo", 0);
    s.puddleAlpha = (std::max)(0, (std::min)(255, Dev("wx_puddle_alpha", 0)));
    s.puddleRough = Dev("wx_puddle_rough", 2);
    s.decalBits = Dev("wx_decal_bits", 1 << 11);
    s.tfBlend = Dev("wx_tfactor_blend", 0);
    s.alphaSrc = Dev("wx_alpha_src", 3);
    s.vcolorAlpha = (std::max)(0, (std::min)(255, Dev("wx_vcolor_alpha", 255)));
    s.filmStatic = Dev("wx_film_static", 0);
    s.waterIor = Dev("wx_water_ior", 133);
    s.liftMilli = Dev("wx_lift_milli", 4);
    s.waterTrans = Dev("wx_water_trans", 80);
    if (memcmp(&s, &g_set, sizeof s) != 0) {
        if (s.rough != g_set.rough || s.albedo != g_set.albedo || s.puddleRough != g_set.puddleRough || s.mode != g_set.mode ||
            s.vcolorAlpha != g_set.vcolorAlpha || s.filmStatic != g_set.filmStatic || (s.filmStatic && s.alpha != g_set.alpha) ||
            s.waterIor != g_set.waterIor || s.liftMilli != g_set.liftMilli || s.waterTrans != g_set.waterTrans) ++g_generation;
        Log("remix wet: mode %d alpha %d rough %d%% albedo %d%% puddles %d (rough %d%%) decal bits %X tfblend %d alpha src %d vcolor a %d static %d (gen %d)",
            s.mode, s.alpha, s.rough, s.albedo, s.puddleAlpha, s.puddleRough, s.decalBits, s.tfBlend, s.alphaSrc, s.vcolorAlpha, s.filmStatic, g_generation);
        g_set = s;
        g_lift = s.liftMilli / 1000.0f;
    }
}

float Hash2(int x, int y) {
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return static_cast<float>((h ^ (h >> 16)) & 0xFFFFFF) / 16777215.0f;
}
float Noise(float x, float y, int period) {
    const int xi = static_cast<int>(std::floor(x)), yi = static_cast<int>(std::floor(y));
    const float fx = x - xi, fy = y - yi;
    auto h = [&](int a, int b) { return Hash2(((a % period) + period) % period, ((b % period) + period) % period); };
    const float u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    return (h(xi, yi) * (1 - u) + h(xi + 1, yi) * u) * (1 - v) + (h(xi, yi + 1) * (1 - u) + h(xi + 1, yi + 1) * u) * v;
}

// The puddle mask: tiling fbm, alpha 1 inside a puddle with a soft rim; RGB near black.
bool WritePuddleDds(const std::wstring& path) {
    const int n = 256;
    std::vector<uint8_t> px(static_cast<size_t>(n) * n * 4);
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            float f = 0, a = 0.5f; int p = 4;
            for (int o = 0; o < 4; ++o, a *= 0.5f, p *= 2) f += a * Noise(x * p / static_cast<float>(n), y * p / static_cast<float>(n), p);
            const float t = (std::max)(0.0f, (std::min)(1.0f, (f - 0.52f) / 0.08f));
            uint8_t* q = &px[(static_cast<size_t>(y) * n + x) * 4];
            q[0] = 10; q[1] = 9; q[2] = 8; q[3] = static_cast<uint8_t>(t * t * (3 - 2 * t) * 255.0f + 0.5f);
        }
    }
    uint32_t header[32] = {};
    header[0] = 0x20534444; header[1] = 124; header[2] = 0x100F; header[3] = n; header[4] = n; header[5] = n * 4;
    header[19] = 32; header[20] = 0x41; header[22] = 32;
    header[23] = 0x00FF0000; header[24] = 0x0000FF00; header[25] = 0x000000FF; header[26] = 0xFF000000;
    header[27] = 0x1000;
    FILE* f = _wfopen(path.c_str(), L"wb");
    if (!f) return false;
    const bool ok = fwrite(header, 4, 32, f) == 32 && fwrite(px.data(), 1, px.size(), f) == px.size();
    fclose(f);
    return ok;
}

remixapi_MaterialHandle MakeOpaque(uint64_t hash, float albedo, float rough, const wchar_t* texture, float staticOpacity = -1.0f) {
    remixapi_MaterialInfoOpaqueEXT opaque = {};
    opaque.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant = {albedo, albedo, albedo};
    opaque.opacityConstant = 1.0f;
    opaque.roughnessConstant = rough;
    opaque.metallicConstant = 0.0f;
    opaque.useDrawCallAlphaState = 1;
    if (staticOpacity >= 0.0f) {   // the material's own alpha state: blended at a fixed opacity
        opaque.useDrawCallAlphaState = 0;
        opaque.opacityConstant = staticOpacity;
        opaque.blendType_hasvalue = 1;
        opaque.blendType_value = 0;   // alpha
    }
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &opaque;
    info.hash = hash;
    info.albedoTexture = texture;
    info.filterMode = 1;
    info.wrapModeU = texture ? 0 : 2;   // the mask repeats; constants clamp like the probe cubes
    info.wrapModeV = texture ? 0 : 2;
    info.emissiveColorConstant = {0.0f, 0.0f, 0.0f};
    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMaterial(&info, &handle);
    Log("remix wet: opaque material %016llx albedo %.2f rough %.2f%s -> %d", static_cast<unsigned long long>(hash), albedo, rough,
        texture ? " (puddle mask)" : "", static_cast<int>(rc));
    return rc == REMIXAPI_ERROR_CODE_SUCCESS ? handle : nullptr;
}

remixapi_MaterialHandle MakeWater(uint64_t hash) {
    remixapi_MaterialInfoTranslucentEXT tr = {};
    tr.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT;
    tr.refractiveIndex = g_set.waterIor / 100.0f;
    const float tc = g_set.waterTrans / 100.0f;
    tr.transmittanceColor = {tc, tc, tc * 1.02f > 1.0f ? 1.0f : tc * 1.02f};
    tr.transmittanceMeasurementDistance = 1.0f;
    tr.thinWallThickness_hasvalue = 1;
    tr.thinWallThickness_value = 0.1f;
    tr.useDiffuseLayer = 0;
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &tr;
    info.hash = hash;
    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMaterial(&info, &handle);
    Log("remix wet: water-film material %016llx -> %d", static_cast<unsigned long long>(hash), static_cast<int>(rc));
    return rc == REMIXAPI_ERROR_CODE_SUCCESS ? handle : nullptr;
}

constexpr int kChunk = 16;

// A chunk's open ground lids (road 1, pavement 2; flat; the column's top block) as quads.
remixapi_MeshHandle ChunkMesh(const gta2::Map& map, int chunkX, int chunkZ, int kind, remixapi_MaterialHandle material) {
    const uint64_t key = (static_cast<uint64_t>(kind) << 56) | (static_cast<uint64_t>(g_generation & 0xFFFF) << 32) |
                         (static_cast<uint64_t>(chunkX & 0xFF) << 8) | static_cast<uint64_t>(chunkZ & 0xFF);
    auto it = g_meshes.find(key);
    if (it != g_meshes.end()) return it->second;
    g_meshes[key] = nullptr;
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    for (int cz = chunkZ * kChunk; cz < chunkZ * kChunk + kChunk; ++cz) {
        for (int cx = chunkX * kChunk; cx < chunkX * kChunk + kChunk; ++cx) {
            const int my = gta2::kMapHeight - 1 - cz;
            if (cx < 0 || cx >= gta2::kMapWidth || my < 0 || my >= gta2::kMapHeight) continue;
            const gta2::Column& c = map.ColumnAt(cx, my);
            // The highest flat road or pavement lid of the column, open to the sky: a block above it
            // with a lid of a real ground type (a deck, a roof) keeps it dry; thin structures over a
            // street (sign gantries, lamp heads: ground type 0) do not (the first rule took the
            // column's top block only and left the road under every gantry dry).
            int found = -1;
            for (int i = static_cast<int>(c.blocks.size()) - 1; i >= 0; --i) {
                if (c.blocks[i] >= map.BlockCount()) break;
                const gta2::Block& b = map.BlockAt(c.blocks[i]);
                const int g = b.GroundType();
                if (b.lid && b.SlopeType() == 0 && (g == 1 || g == 2)) { found = i; break; }
                if (b.lid && g != 0) break;   // covered by a deck or a roof
            }
            if (found < 0) continue;
            const float y = static_cast<float>(c.offset + found + 1) + g_lift;
            const uint32_t base = static_cast<uint32_t>(verts.size());
            const float xs[4] = {0, 1, 1, 0}, zs[4] = {0, 0, 1, 1};
            for (int k = 0; k < 4; ++k) {
                remixapi_HardcodedVertex v = {};
                v.position[0] = cx + xs[k]; v.position[1] = y; v.position[2] = cz + zs[k];
                v.normal[1] = 1.0f;
                v.texcoord[0] = (cx + xs[k]) / 6.0f; v.texcoord[1] = (cz + zs[k]) / 6.0f;
                v.color = (static_cast<uint32_t>(g_set.vcolorAlpha) << 24) | 0x00FFFFFFu;
                verts.push_back(v);
            }
            const uint32_t q[6] = {0, 2, 1, 0, 3, 2};
            for (uint32_t k : q) idx.push_back(base + k);
        }
    }
    if (verts.empty()) return nullptr;
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data();
    surface.vertices_count = verts.size();
    surface.indices_values = idx.data();
    surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0;
    surface.material = material;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO;
    mesh.hash = key ^ 0x5745540000000000ull;
    mesh.surfaces_values = &surface;
    mesh.surfaces_count = 1;
    remixapi_MeshHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMesh(&mesh, &handle);
    static int logs = 0;
    if (logs++ < 12) Log("remix wet: chunk %d,%d kind %d: %zu quads -> %d", chunkX, chunkZ, kind, verts.size() / 4, static_cast<int>(rc));
    if (rc != REMIXAPI_ERROR_CODE_SUCCESS) return nullptr;
    g_meshes[key] = handle;
    return handle;
}

void Draw(remixapi_MeshHandle mesh, uint32_t categories, bool blend, int alphaArg1, int alphaArg2, int alphaOp, int alpha) {
    // The instance state of the probe board's cubes that render (p1a): colour = texture modulate,
    // blend factors ONE/ZERO unless blending, alpha test on (ref 1) when not blending.
    remixapi_InstanceInfo instance = {};
    instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
    instance.categoryFlags = categories;
    remixapi_InstanceInfoBlendEXT b = {};
    b.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
    const bool legacy = Dev("wx_legacy_draw", 0) != 0;   // A/B: the p0 state that rendered nothing opaque
    b.alphaTestEnabled = (!blend && !legacy) ? 1 : 0;
    b.alphaTestReferenceValue = 1;
    b.alphaTestCompareOp = 6;
    b.alphaBlendEnabled = blend ? 1 : 0;
    b.srcColorBlendFactor = blend ? 6 : 1;
    b.dstColorBlendFactor = blend ? 7 : 0;
    b.colorBlendOp = 0;
    b.srcAlphaBlendFactor = 1;
    b.dstAlphaBlendFactor = legacy ? 7 : 0;
    b.alphaBlendOp = 0;
    b.writeMask = 0xFFFFFFFFu;
    b.textureColorArg1Source = 1;
    b.textureColorArg2Source = 0;
    b.textureColorOperation = legacy ? 1 : 3;
    b.textureAlphaArg1Source = static_cast<uint32_t>(alphaArg1);
    b.textureAlphaArg2Source = static_cast<uint32_t>(alphaArg2);
    b.textureAlphaOperation = static_cast<uint32_t>(alphaOp);
    b.tFactor = (static_cast<uint32_t>(alpha) << 24) | 0x00FFFFFFu;
    b.isTextureFactorBlend = g_set.tfBlend ? 1 : 0;
    b.isVertexColorBakedLighting = 0;
    instance.pNext = &b;
    instance.mesh = mesh;
    instance.doubleSided = static_cast<remixapi_Bool>(Dev("wx_double_sided", 1));
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 4; ++c) instance.transform.matrix[r][c] = (r == c) ? 1.0f : 0.0f;
    RemixApi()->DrawInstance(&instance);
}


// ---- Probe board (WEATHER-V2 gate 1, priority 1): which opaque API configurations render ----
// [devtools] wx_probe_board=1: eight 0.4-block cubes in a ring of radius 2.5 around where the eye
// was when the key went to 1, each a different material / blend configuration (colour coded).
struct ProbeVariant { const char* name; float r, g, b; bool texture; int alphaTest; int blend; int alphaSrc; uint32_t cats; bool translucent; bool flat; };
const ProbeVariant kProbe[8] = {
    {"car-like white tex, alpha test", 1, 1, 1, true, 1, 0, 1, 0, false, false},
    {"red const, car blend ext", 1, 0.1f, 0.1f, false, 1, 0, 1, 0, false, false},
    {"green const, no test", 0.1f, 1, 0.1f, false, 0, 0, 1, 0, false, false},
    {"blue tex, blend tfactor(3) a128", 0.1f, 0.1f, 1, true, 0, 1, 3, 0, false, false},
    {"yellow tex, blend tfactor(4) a128", 1, 1, 0.1f, true, 0, 1, 4, 0, false, false},
    {"magenta tex, decal static", 1, 0.1f, 1, true, 1, 0, 1, 1u << 11, false, false},
    {"translucent control", 1, 1, 1, false, 0, 0, 1, 0, true, false},
    {"cyan tex, flat on ground +0.004", 0.1f, 1, 1, true, 1, 0, 1, 0, false, true},
};
bool g_probeOn = false;
float g_probeX = 0, g_probeY = 0, g_probeZ = 0;
remixapi_MeshHandle g_probeMesh[8] = {};
std::wstring g_whitePath;

bool WriteWhiteDds(const std::wstring& path) {
    const int n = 16;
    std::vector<uint8_t> px(static_cast<size_t>(n) * n * 4, 255);
    uint32_t header[32] = {};
    header[0] = 0x20534444; header[1] = 124; header[2] = 0x100F; header[3] = n; header[4] = n; header[5] = n * 4;
    header[19] = 32; header[20] = 0x41; header[22] = 32;
    header[23] = 0x00FF0000; header[24] = 0x0000FF00; header[25] = 0x000000FF; header[26] = 0xFF000000;
    header[27] = 0x1000;
    FILE* f = _wfopen(path.c_str(), L"wb");
    if (!f) return false;
    const bool ok = fwrite(header, 4, 32, f) == 32 && fwrite(px.data(), 1, px.size(), f) == px.size();
    fclose(f);
    return ok;
}

remixapi_MeshHandle ProbeMesh(int i) {
    const ProbeVariant& v = kProbe[i];
    if (g_whitePath.empty()) {
        wchar_t exe[MAX_PATH] = {};
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        std::wstring dir = exe;
        dir = dir.substr(0, dir.find_last_of(L"\\/")) + L"\\gta2dx9_cache";
        CreateDirectoryW(dir.c_str(), nullptr);
        g_whitePath = dir + L"\\wx_white.dds";
        Log("remix wet probe: white texture %s", WriteWhiteDds(g_whitePath) ? "written" : "NOT written");
    }
    remixapi_MaterialHandle mat = nullptr;
    const uint64_t mhash = 0x5750524F42000000ull + i * 2 + 1;
    if (v.translucent) {
        remixapi_MaterialInfoTranslucentEXT tr = {};
        tr.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT;
        tr.refractiveIndex = 1.5f; tr.transmittanceColor = {0.5f, 0.9f, 0.5f}; tr.transmittanceMeasurementDistance = 1.0f;
        tr.thinWallThickness_hasvalue = 1; tr.thinWallThickness_value = 0.1f;
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &tr; info.hash = mhash;
        RemixApi()->CreateMaterial(&info, &mat);
    } else {
        remixapi_MaterialInfoOpaqueEXT op = {};
        op.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
        op.albedoConstant = {v.r, v.g, v.b};
        op.opacityConstant = 1.0f;
        op.roughnessConstant = 0.5f;
        op.useDrawCallAlphaState = 1;
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &op; info.hash = mhash;
        info.albedoTexture = v.texture ? g_whitePath.c_str() : nullptr;
        info.emissiveColorConstant = {0, 0, 0};
        info.filterMode = 1; info.wrapModeU = 2; info.wrapModeV = 2;
        const remixapi_ErrorCode rc = RemixApi()->CreateMaterial(&info, &mat);
        Log("remix wet probe: %d %s material -> %d", i, v.name, static_cast<int>(rc));
    }
    if (!mat) return nullptr;
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    auto face = [&](const float* p0, const float* p1, const float* p2, const float* p3, const float* n) {
        const uint32_t b = static_cast<uint32_t>(verts.size());
        const float* ps[4] = {p0, p1, p2, p3};
        const float uv[4][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
        for (int k = 0; k < 4; ++k) {
            remixapi_HardcodedVertex vx = {};
            for (int c = 0; c < 3; ++c) { vx.position[c] = ps[k][c]; vx.normal[c] = n[c]; }
            vx.texcoord[0] = uv[k][0]; vx.texcoord[1] = uv[k][1]; vx.color = 0xFFFFFFFFu;
            verts.push_back(vx);
        }
        const uint32_t q[6] = {0, 1, 2, 0, 2, 3};
        for (uint32_t k : q) idx.push_back(b + k);
    };
    const float a = static_cast<float>(i) * 0.785398f;
    const float cx = g_probeX + 2.5f * std::cos(a), cz = g_probeZ + 2.5f * std::sin(a);
    if (v.flat) {
        const float y = g_probeY + 0.004f, h = 0.6f;
        const float p0[3] = {cx - h, y, cz - h}, p1[3] = {cx + h, y, cz - h}, p2[3] = {cx + h, y, cz + h}, p3[3] = {cx - h, y, cz + h};
        const float up[3] = {0, 1, 0};
        face(p0, p1, p2, p3, up);
    } else {
        const float h = 0.2f, y0 = g_probeY + 0.3f, y1 = y0 + 0.4f;
        const float c[8][3] = {{cx - h, y0, cz - h}, {cx + h, y0, cz - h}, {cx + h, y0, cz + h}, {cx - h, y0, cz + h},
                               {cx - h, y1, cz - h}, {cx + h, y1, cz - h}, {cx + h, y1, cz + h}, {cx - h, y1, cz + h}};
        const float nu[3] = {0, 1, 0}, nd[3] = {0, -1, 0}, nx[3] = {1, 0, 0}, nX[3] = {-1, 0, 0}, nz[3] = {0, 0, 1}, nZ[3] = {0, 0, -1};
        face(c[4], c[5], c[6], c[7], nu); face(c[3], c[2], c[1], c[0], nd);
        face(c[1], c[2], c[6], c[5], nx); face(c[3], c[0], c[4], c[7], nX);
        face(c[2], c[3], c[7], c[6], nz); face(c[0], c[1], c[5], c[4], nZ);
    }
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data(); surface.vertices_count = verts.size();
    surface.indices_values = idx.data(); surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0; surface.material = mat;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO; mesh.hash = 0x5750524F424D0000ull + i;
    mesh.surfaces_values = &surface; mesh.surfaces_count = 1;
    remixapi_MeshHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMesh(&mesh, &handle);
    Log("remix wet probe: %d mesh at %.2f,%.2f,%.2f -> %d", i, cx, g_probeY, cz, static_cast<int>(rc));
    return rc == REMIXAPI_ERROR_CODE_SUCCESS ? handle : nullptr;
}

void DrawProbeBoard(const gta2::Map& map, float ex, float ey, float ez) {
    const bool on = Dev("wx_probe_board", 0) != 0;
    if (on && !g_probeOn) {
        g_probeX = ex; g_probeZ = ez; g_probeY = std::floor(ey);
        const int cx = static_cast<int>(std::floor(ex)), cz = static_cast<int>(std::floor(ez)), my = gta2::kMapHeight - 1 - cz;
        if (cx >= 0 && cx < gta2::kMapWidth && my >= 0 && my < gta2::kMapHeight) {
            const gta2::Column& c = map.ColumnAt(cx, my);
            if (!c.blocks.empty()) g_probeY = static_cast<float>(c.offset + static_cast<int>(c.blocks.size()));
        }
        Log("remix wet probe: board at %.2f,%.2f,%.2f (eye y %.2f)", g_probeX, g_probeY, g_probeZ, ey);
        for (auto& m : g_probeMesh) m = nullptr;
        for (int i = 0; i < 8; ++i) g_probeMesh[i] = ProbeMesh(i);
    }
    g_probeOn = on;
    if (!on) return;
    for (int i = 0; i < 8; ++i) {
        if (!g_probeMesh[i]) continue;
        const ProbeVariant& v = kProbe[i];
        remixapi_InstanceInfo instance = {};
        instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
        instance.categoryFlags = v.cats;
        remixapi_InstanceInfoBlendEXT b = {};
        b.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
        b.alphaTestEnabled = v.alphaTest; b.alphaTestReferenceValue = 1; b.alphaTestCompareOp = 6;
        b.alphaBlendEnabled = v.blend;
        b.srcColorBlendFactor = v.blend ? 6 : 1; b.dstColorBlendFactor = v.blend ? 7 : 0; b.colorBlendOp = 0;
        b.srcAlphaBlendFactor = 1; b.dstAlphaBlendFactor = 0; b.alphaBlendOp = 0; b.writeMask = 0xFFFFFFFFu;
        b.textureColorArg1Source = 1; b.textureColorArg2Source = 0; b.textureColorOperation = 3;
        b.textureAlphaArg1Source = static_cast<uint32_t>(v.alphaSrc); b.textureAlphaArg2Source = 0; b.textureAlphaOperation = 1;
        b.tFactor = v.blend ? 0x80FFFFFFu : 0xFFFFFFFFu;
        instance.pNext = v.translucent ? nullptr : &b;
        instance.mesh = g_probeMesh[i];
        instance.doubleSided = 1;
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 4; ++c) instance.transform.matrix[r][c] = (r == c) ? 1.0f : 0.0f;
        RemixApi()->DrawInstance(&instance);
    }
}
}  // namespace

void RemixWetFrame(const gta2::Map& map, float eyeX, float eyeY, float eyeZ, float viewMix) {
    const DWORD now = GetTickCount();
    if (!g_ini[0] || now - g_lastRead >= 1000) { g_lastRead = now; ReadSettings(); }
    if (!RemixApiHasInstances() || map.Empty() || viewMix < 0.01f) return;
    DrawProbeBoard(map, eyeX, eyeY, eyeZ);
    if (g_set.mode == 0 && g_set.puddleAlpha == 0) return;
    const uint64_t salt = static_cast<uint64_t>(g_generation) << 20;
    if ((g_set.mode == 4 || g_set.mode == 5) && g_filmGen != g_generation) {
        if (g_set.mode == 5 && g_puddlePath.empty()) {
            wchar_t exe[MAX_PATH] = {};
            GetModuleFileNameW(nullptr, exe, MAX_PATH);
            std::wstring dir = exe;
            dir = dir.substr(0, dir.find_last_of(L"\\/")) + L"\\gta2dx9_cache";
            CreateDirectoryW(dir.c_str(), nullptr);
            g_puddlePath = dir + L"\\wx_puddle_mask.dds";
            WritePuddleDds(g_puddlePath);
        }
        g_film = MakeOpaque(0x5745540400000001ull ^ salt, g_set.albedo / 100.0f, g_set.rough / 100.0f,
                            g_set.mode == 5 ? g_puddlePath.c_str() : nullptr);
        g_filmGen = g_generation;
    }
    if (g_set.mode == 1 || g_set.mode == 3 || g_set.mode == 6) {
        if (g_filmGen != g_generation) { g_film = MakeOpaque(0x5745540100000001ull ^ salt, g_set.albedo / 100.0f, g_set.rough / 100.0f, nullptr,
                                                         g_set.filmStatic ? g_set.alpha / 255.0f : -1.0f); g_filmGen = g_generation; }
    }
    if ((g_set.mode == 2 || g_set.mode == 6) && g_waterGen != g_generation) {
        g_water = MakeWater(0x5745540200000001ull ^ salt); g_waterGen = g_generation;
    }
    if (g_set.puddleAlpha > 0 && g_puddleGen != g_generation) {
        if (g_puddlePath.empty()) {
            wchar_t exe[MAX_PATH] = {};
            GetModuleFileNameW(nullptr, exe, MAX_PATH);
            std::wstring dir = exe;
            dir = dir.substr(0, dir.find_last_of(L"\\/")) + L"\\gta2dx9_cache";
            CreateDirectoryW(dir.c_str(), nullptr);
            g_puddlePath = dir + L"\\wx_puddle_mask.dds";
            Log("remix wet: puddle mask %s", WritePuddleDds(g_puddlePath) ? "written" : "NOT written");
        }
        g_puddle = MakeOpaque(0x5745540300000001ull ^ salt, 0.03f, g_set.puddleRough / 100.0f, g_puddlePath.c_str());
        g_puddleGen = g_generation;
    }
    const int cx0 = static_cast<int>(std::floor((eyeX - 48.0f) / kChunk)), cx1 = static_cast<int>(std::floor((eyeX + 48.0f) / kChunk));
    const int cz0 = static_cast<int>(std::floor((eyeZ - 48.0f) / kChunk)), cz1 = static_cast<int>(std::floor((eyeZ + 48.0f) / kChunk));
    const int alpha = static_cast<int>(g_set.alpha * viewMix + 0.5f);
    const int palpha = static_cast<int>(g_set.puddleAlpha * viewMix + 0.5f);
    for (int z = cz0; z <= cz1; ++z) {
        for (int x = cx0; x <= cx1; ++x) {
            if (x < 0 || z < 0 || x >= gta2::kMapWidth / kChunk || z >= gta2::kMapHeight / kChunk) continue;
            if (g_set.mode == 1 && g_film) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 1, g_film)) Draw(m, static_cast<uint32_t>(g_set.decalBits), !g_set.filmStatic, g_set.alphaSrc, 0, 1, alpha);
            } else if ((g_set.mode == 3 || g_set.mode == 6) && g_film) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 1, g_film)) Draw(m, 0, !g_set.filmStatic, g_set.alphaSrc, 0, 1, alpha);
                if (g_set.mode == 6 && g_water && viewMix > 0.99f) {
                    const float keep = g_lift; g_lift += 0.004f;
                    if (remixapi_MeshHandle w = ChunkMesh(map, x, z, 2, g_water)) Draw(w, 0, false, 1, 0, 1, 255);
                    g_lift = keep;
                }
            } else if ((g_set.mode == 4 || g_set.mode == 5) && g_film) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 4, g_film)) Draw(m, 0, false, 1, 0, 1, 255);
            } else if (g_set.mode == 2 && g_water && viewMix > 0.99f) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 2, g_water)) Draw(m, 0, false, 1, 0, 1, 255);
            }
            if (palpha > 0 && g_puddle) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 3, g_puddle)) Draw(m, static_cast<uint32_t>(g_set.decalBits), true, 1, 3, 3, palpha);
            }
        }
    }
}

}  // namespace gta2dx9
