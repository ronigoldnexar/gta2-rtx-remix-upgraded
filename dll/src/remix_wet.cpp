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
#include "remix_lights.h"

#include "time_of_day.h"

#include "../../src/gta2_map.h"
#include "../../src/weather_fx.h"

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
Settings g_dev;   // the [devtools] wx_* keys as read; g_set is what is drawn (production when wx_wet_mode < 0)
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
    s.mode = Dev("wx_wet_mode", -1);
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
    if (memcmp(&s, &g_dev, sizeof s) != 0) {
        Log("remix wet: devtools mode %d alpha %d rough %d%% albedo %d%% puddles %d lift %d", s.mode, s.alpha, s.rough, s.albedo,
            s.puddleAlpha, s.liftMilli);
        g_dev = s;
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

// ---- Puddles (WEATHER-V2 A): water patches cut from a world-space noise field ----
// The field is the puddle mask's fbm sampled in world space (period 6 blocks per noise cell);
// each 1/8-block grid square of an open road/pavement lid is clipped against field > thr
// (linear crossing on its edges) and the inside fanned into triangles. Puddles are the
// translucent water (a mirror); the damp rim is the same cut at two lower thresholds drawn with
// the darkening film, so the puddle's edge steps down into the wet road instead of ending hard.
float PuddleField(float x, float z) {
    float f = 0.0f, a = 0.5f, scale = 3.0f;   // noise cells a third of a block (~1.3 m): puddles 0.5-2 m
    for (int o = 0; o < 3; ++o, a *= 0.5f, scale *= 2.0f) f += a * Noise(x * scale, z * scale, 1 << 20);
    return 0.45f * f;
}

// Where water collects on a road cell: the gutter along any edge that meets a non-road cell (the kerb),
// two wheel ruts per lane along the traffic arrows, a little more at junctions.
struct CellBias { float gutter[4]; bool rutsAlongZ, rutsAlongX, junction, road; };
CellBias BiasFor(const gta2::Map& map, int cx, int cz) {
    CellBias b = {};
    auto ground = [&](int x, int z) -> int {
        const int my = gta2::kMapHeight - 1 - z;
        if (x < 0 || x >= gta2::kMapWidth || my < 0 || my >= gta2::kMapHeight) return -1;
        const gta2::Column& c = map.ColumnAt(x, my);
        // The highest lid of a real ground type: a sign gantry or lamp head (type 0) over the road is not a kerb.
        for (int i = static_cast<int>(c.blocks.size()) - 1; i >= 0; --i) {
            if (c.blocks[i] >= map.BlockCount()) return -1;
            const gta2::Block& bl = map.BlockAt(c.blocks[i]);
            if (bl.lid && bl.GroundType() != 0) return bl.GroundType();
        }
        return -1;
    };
    b.road = ground(cx, cz) == 1;
    if (!b.road) return b;
    const int nx[4] = {-1, 1, 0, 0}, nz[4] = {0, 0, -1, 1};
    for (int e = 0; e < 4; ++e) b.gutter[e] = ground(cx + nx[e], cz + nz[e]) != 1 ? 1.0f : 0.0f;
    const int my = gta2::kMapHeight - 1 - cz;
    const gta2::Column& c = map.ColumnAt(cx, my);
    uint8_t arrows = 0;
    for (uint32_t i : c.blocks) if (i < map.BlockCount()) arrows |= map.BlockAt(i).arrows;
    const bool vertical = (arrows & 0x0C) != 0, horizontal = (arrows & 0x03) != 0;
    b.rutsAlongZ = vertical && !horizontal;
    b.rutsAlongX = horizontal && !vertical;
    b.junction = vertical && horizontal;
    return b;
}

float Bias(const CellBias& b, float fx, float fz) {
    if (!b.road) return 0.0f;
    auto band = [](float d, float w) { const float t = d / w; return t >= 1.0f ? 0.0f : (1.0f - t) * (1.0f - t); };
    float g = 0.0f;
    g = (std::max)(g, b.gutter[0] * band(fx, 0.22f));
    g = (std::max)(g, b.gutter[1] * band(1.0f - fx, 0.22f));
    g = (std::max)(g, b.gutter[2] * band(fz, 0.22f));
    g = (std::max)(g, b.gutter[3] * band(1.0f - fz, 0.22f));
    float r = 0.0f;
    auto rut = [](float t) { const float a = (t - 0.28f) / 0.06f, c = (t - 0.72f) / 0.06f; return std::exp(-a * a) + std::exp(-c * c); };
    if (b.rutsAlongZ) r = rut(fx);
    if (b.rutsAlongX) r = rut(fz);
    return 0.30f * g + 0.12f * r + (b.junction ? 0.04f : 0.0f);
}

bool OpenGroundLid(const gta2::Map& map, int cx, int cz, float* y) {
    const int my = gta2::kMapHeight - 1 - cz;
    if (cx < 0 || cx >= gta2::kMapWidth || my < 0 || my >= gta2::kMapHeight) return false;
    const gta2::Column& c = map.ColumnAt(cx, my);
    for (int i = static_cast<int>(c.blocks.size()) - 1; i >= 0; --i) {
        if (c.blocks[i] >= map.BlockCount()) return false;
        const gta2::Block& b = map.BlockAt(c.blocks[i]);
        const int g = b.GroundType();
        if (b.lid && b.SlopeType() == 0 && (g == 1 || g == 2)) { *y = static_cast<float>(c.offset + i + 1); return true; }
        if (b.lid && g != 0) return false;
    }
    return false;
}

remixapi_MeshHandle PuddleMesh(const gta2::Map& map, int chunkX, int chunkZ, int kind, float thr, float lift,
                               remixapi_MaterialHandle material, int level) {
    const uint64_t key = (static_cast<uint64_t>(kind) << 56) | (static_cast<uint64_t>(level & 0xFF) << 48) |
                         (static_cast<uint64_t>(g_generation & 0xFFFF) << 32) | (static_cast<uint64_t>(chunkX & 0xFF) << 8) |
                         static_cast<uint64_t>(chunkZ & 0xFF);
    auto it = g_meshes.find(key);
    if (it != g_meshes.end()) return it->second;
    g_meshes[key] = nullptr;
    constexpr int kSub = 6;
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    for (int cz = chunkZ * kChunk; cz < chunkZ * kChunk + kChunk; ++cz) {
        for (int cx = chunkX * kChunk; cx < chunkX * kChunk + kChunk; ++cx) {
            float y = 0.0f;
            if (!OpenGroundLid(map, cx, cz, &y)) continue;
            y += lift;
            float f[kSub + 1][kSub + 1];
            bool any = false;
            const CellBias bias = BiasFor(map, cx, cz);
            for (int j = 0; j <= kSub; ++j)
                for (int i = 0; i <= kSub; ++i) {
                    const float fx = i / static_cast<float>(kSub), fz = j / static_cast<float>(kSub);
                    f[j][i] = PuddleField(cx + fx, cz + fz) + Bias(bias, fx, fz) - thr;
                    any = any || f[j][i] > 0.0f;
                }
            if (!any) continue;
            for (int j = 0; j < kSub; ++j) {
                for (int i = 0; i < kSub; ++i) {
                    const float px[4] = {cx + i / 6.0f, cx + (i + 1) / 6.0f, cx + (i + 1) / 6.0f, cx + i / 6.0f};
                    const float pz[4] = {cz + j / 6.0f, cz + j / 6.0f, cz + (j + 1) / 6.0f, cz + (j + 1) / 6.0f};
                    const float v[4] = {f[j][i], f[j][i + 1], f[j + 1][i + 1], f[j + 1][i]};
                    if (v[0] <= 0 && v[1] <= 0 && v[2] <= 0 && v[3] <= 0) continue;
                    float ox[8], oz[8];
                    int n = 0;
                    for (int e = 0; e < 4; ++e) {
                        const int q = (e + 1) & 3;
                        if (v[e] > 0) { ox[n] = px[e]; oz[n] = pz[e]; ++n; }
                        if ((v[e] > 0) != (v[q] > 0)) {
                            const float t = v[e] / (v[e] - v[q]);
                            ox[n] = px[e] + (px[q] - px[e]) * t; oz[n] = pz[e] + (pz[q] - pz[e]) * t; ++n;
                        }
                    }
                    if (n < 3) continue;
                    const uint32_t base = static_cast<uint32_t>(verts.size());
                    for (int k = 0; k < n; ++k) {
                        remixapi_HardcodedVertex vx = {};
                        vx.position[0] = ox[k]; vx.position[1] = y; vx.position[2] = oz[k];
                        vx.normal[1] = 1.0f;
                        vx.texcoord[0] = ox[k] / 6.0f; vx.texcoord[1] = oz[k] / 6.0f;
                        vx.color = 0xFFFFFFFFu;
                        verts.push_back(vx);
                    }
                    for (int k = 1; k + 1 < n; ++k) { idx.push_back(base); idx.push_back(base + k + 1); idx.push_back(base + k); }
                }
            }
        }
    }
    if (verts.empty()) return nullptr;
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data(); surface.vertices_count = verts.size();
    surface.indices_values = idx.data(); surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0; surface.material = material;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO; mesh.hash = key ^ 0x5055444C00000000ull;
    mesh.surfaces_values = &surface; mesh.surfaces_count = 1;
    remixapi_MeshHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMesh(&mesh, &handle);
    static int logs = 0;
    if (logs++ < 6) Log("remix wet: puddle chunk %d,%d kind %d level %d: %zu tris -> %d", chunkX, chunkZ, kind, level, idx.size() / 3, static_cast<int>(rc));
    if (rc != REMIXAPI_ERROR_CODE_SUCCESS) return nullptr;
    g_meshes[key] = handle;
    return handle;
}
remixapi_MaterialHandle g_puddleWater = nullptr;

// ---- Rain under Remix (WEATHER-V2): water drops as API geometry ----
// A drop is two crossed vertical quads (thin water, IOR 1.33, almost clear), so the path tracer gives
// it the sky's sheen by day and the glint of lamps and head lamps by night. kRainMeshes boxes of drops
// (kRainBox blocks wide, kRainH tall) with different seeds, anchored to the world and tiled 3 x 3 round
// the eye; two stacked layers fall with time (the layer offset wraps by the box height); the wind is a
// shear of the instance transform. More rain draws more of the meshes.
constexpr int kRainMeshes = 4, kRainDrops = 700;
constexpr float kRainBox = 12.0f, kRainH = 8.0f;
remixapi_MaterialHandle g_rainMat = nullptr;
int g_rainParticle = 0, g_rainAlpha = 45;
remixapi_MeshHandle g_rainMesh[kRainMeshes] = {};
float g_rainLen = -1.0f;

remixapi_MeshHandle RainMesh(int m, float len) {
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    verts.reserve(kRainDrops * 8);
    const float w = g_rainParticle ? 0.0025f : 0.006f;   // ~1 cm (a particle) or ~2.4 cm (water)
    for (int d = 0; d < kRainDrops; ++d) {
        const float x = Hash2(d, m * 7 + 1) * kRainBox, z = Hash2(d, m * 7 + 2) * kRainBox, y = Hash2(d, m * 7 + 3) * kRainH;
        const float l = len * (0.7f + 0.6f * Hash2(d, m * 7 + 4));
        for (int q = 0; q < 2; ++q) {
            const float dx = q == 0 ? w : 0.0f, dz = q == 0 ? 0.0f : w;
            const uint32_t b = static_cast<uint32_t>(verts.size());
            const float px[4] = {x - dx, x + dx, x + dx, x - dx}, pz[4] = {z - dz, z + dz, z + dz, z - dz}, py[4] = {y, y, y + l, y + l};
            for (int k = 0; k < 4; ++k) {
                remixapi_HardcodedVertex v = {};
                v.position[0] = px[k]; v.position[1] = py[k]; v.position[2] = pz[k];
                v.normal[0] = q == 0 ? 0.0f : 1.0f; v.normal[2] = q == 0 ? 1.0f : 0.0f;
                v.texcoord[0] = (k == 1 || k == 2) ? 1.0f : 0.0f; v.texcoord[1] = k >= 2 ? 1.0f : 0.0f;
                v.color = 0xFFFFFFFFu;
                verts.push_back(v);
            }
            const uint32_t t[6] = {0, 1, 2, 0, 2, 3};
            for (uint32_t k : t) idx.push_back(b + k);
        }
    }
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data(); surface.vertices_count = verts.size();
    surface.indices_values = idx.data(); surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0; surface.material = g_rainMat;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO;
    mesh.hash = 0x5241494E00000000ull ^ (static_cast<uint64_t>(m) << 16) ^ static_cast<uint64_t>(len * 1000.0f);
    mesh.surfaces_values = &surface; mesh.surfaces_count = 1;
    remixapi_MeshHandle handle = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMesh(&mesh, &handle);
    if (m == 0) Log("remix rain: drop meshes (%d drops each, length %.2f) -> %d", kRainDrops, len, static_cast<int>(rc));
    return rc == REMIXAPI_ERROR_CODE_SUCCESS ? handle : nullptr;
}

void DrawRemixRain(float ex, float ey, float ez, float viewMix) {
    const gta2::WeatherState& w = gta2::WeatherNow();
    if (!w.active || !w.remixRainApi || w.rain < 0.03f || viewMix < 0.99f) return;
    // [weather] remix_drop_trans (percent, 97) / remix_drop_ior (x100, 133): the drop material, re-read once a second.
    static int dropTrans = 97, dropIor = 133;
    static DWORD dropRead = 0;
    if (GetTickCount() - dropRead >= 1000) {
        dropRead = GetTickCount();
        const int t = GetPrivateProfileIntA("weather", "remix_drop_trans", 97, g_ini), i = GetPrivateProfileIntA("weather", "remix_drop_ior", 133, g_ini);
        const int pm = GetPrivateProfileIntA("weather", "remix_rain_particle", 0, g_ini);   // 1: particle drops (pr1: not seen with RR on either)
        const int pa = GetPrivateProfileIntA("weather", "remix_rain_alpha", 45, g_ini);
        if (pm != g_rainParticle || pa != g_rainAlpha) { g_rainParticle = pm; g_rainAlpha = pa; g_rainMat = nullptr; for (auto& m : g_rainMesh) m = nullptr; g_rainLen = -1.0f;
            Log("remix rain: %s drops, alpha %d%%", pm ? "particle (opaque, blended)" : "translucent water", pa); }
        if (t != dropTrans || i != dropIor) { dropTrans = t; dropIor = i; g_rainMat = nullptr; for (auto& m : g_rainMesh) m = nullptr; g_rainLen = -1.0f;
            Log("remix rain: drop material transmittance %d%% ior %.2f", t, i / 100.0f); }
    }
    if (!g_rainMat && g_rainParticle) {
        remixapi_MaterialInfoOpaqueEXT op = {};
        op.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
        op.albedoConstant = {0.85f, 0.88f, 0.92f};
        op.opacityConstant = 1.0f;
        op.roughnessConstant = 0.15f;
        op.metallicConstant = 0.0f;
        op.useDrawCallAlphaState = 1;
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &op; info.hash = 0x5241494E50415254ull;
        info.emissiveColorConstant = {0.0f, 0.0f, 0.0f};
        info.filterMode = 1; info.wrapModeU = 2; info.wrapModeV = 2;
        RemixApi()->CreateMaterial(&info, &g_rainMat);
        Log("remix rain: particle drop material %s", g_rainMat ? "made" : "refused");
        if (!g_rainMat) return;
    }
    if (!g_rainMat) {
        remixapi_MaterialInfoTranslucentEXT tr = {};
        tr.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT;
        const float tc = dropTrans / 100.0f;
        tr.refractiveIndex = dropIor / 100.0f; tr.transmittanceColor = {tc, tc, tc}; tr.transmittanceMeasurementDistance = 1.0f;
        tr.thinWallThickness_hasvalue = 1; tr.thinWallThickness_value = 0.05f;
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &tr; info.hash = 0x5241494E4D415401ull ^ (static_cast<uint64_t>(dropTrans) << 16) ^ static_cast<uint64_t>(dropIor);
        RemixApi()->CreateMaterial(&info, &g_rainMat);
        Log("remix rain: drop material %s", g_rainMat ? "made" : "refused");
        if (!g_rainMat) return;
    }
    // The streak's length: a drop's travel in a frame or two plus the drop, longer in wind (blocks).
    const float len = std::floor((0.18f + 0.22f * w.wind) * 20.0f + 0.5f) / 20.0f;
    if (len != g_rainLen) {
        for (auto& m : g_rainMesh) { if (m && RemixApi()->DestroyMesh) RemixApi()->DestroyMesh(m); m = nullptr; }
        for (int m = 0; m < kRainMeshes; ++m) g_rainMesh[m] = RainMesh(m, len);
        g_rainLen = len;
    }
    const int meshes = (std::max)(1, (std::min)(kRainMeshes, static_cast<int>(std::ceil(w.rain * kRainMeshes))));
    const float speed = 7.5f;   // blocks per second (~30 m/s scaled to the city's blocks; reads as heavy rain)
    const float t = static_cast<float>(std::fmod(w.seconds, 3600.0));
    const float fall = std::fmod(t * speed, kRainH);
    const float sx = w.windDir[0] * w.wind * 3.5f / speed, sz = w.windDir[1] * w.wind * 3.5f / speed;
    const int bx = static_cast<int>(std::floor(ex / kRainBox)), bz = static_cast<int>(std::floor(ez / kRainBox));
    const int layer0 = static_cast<int>(std::floor((ey - 3.0f + fall) / kRainH));
    for (int m = 0; m < meshes; ++m) {
        if (!g_rainMesh[m]) continue;
        for (int L = layer0; L <= layer0 + 1; ++L) {
            const float oy = L * kRainH - fall;
            for (int gz = bz - 1; gz <= bz + 1; ++gz) {
                for (int gx = bx - 1; gx <= bx + 1; ++gx) {
                    if (gta2::WeatherCovered((gx + 0.5f) * kRainBox, ey + 1.0f, (gz + 0.5f) * kRainBox) &&
                        gta2::WeatherCovered(ex, ey + 0.2f, ez)) continue;   // a tunnel or a covered street: no rain
                    remixapi_InstanceInfo instance = {};
                    instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
                    instance.mesh = g_rainMesh[m];
                    instance.doubleSided = 1;
                    remixapi_InstanceInfoBlendEXT b = {};
                    if (g_rainParticle) {
                        // A particle: Ray Reconstruction's separate particle buffer (rtx.rayreconstruction.particleBufferMode),
                        // alpha-blended by the instance's texture factor.
                        instance.categoryFlags = REMIXAPI_INSTANCE_CATEGORY_BIT_PARTICLE;
                        b.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
                        b.alphaBlendEnabled = 1;
                        b.srcColorBlendFactor = 6; b.dstColorBlendFactor = 7; b.colorBlendOp = 0;
                        b.srcAlphaBlendFactor = 1; b.dstAlphaBlendFactor = 7; b.alphaBlendOp = 0;
                        b.writeMask = 0xFFFFFFFFu;
                        b.textureColorArg1Source = 1; b.textureColorArg2Source = 0; b.textureColorOperation = 3;
                        b.textureAlphaArg1Source = 3; b.textureAlphaArg2Source = 0; b.textureAlphaOperation = 1;
                        b.tFactor = (static_cast<uint32_t>((std::max)(0, (std::min)(100, g_rainAlpha)) * 255 / 100) << 24) | 0x00FFFFFFu;
                        instance.pNext = &b;
                    }
                    // x' = x + sx*y + ox, y' = y + oy, z' = z + sz*y + oz (the shear slants the fall downwind)
                    remixapi_Transform& T = instance.transform;
                    T.matrix[0][0] = 1; T.matrix[0][1] = -sx; T.matrix[0][2] = 0; T.matrix[0][3] = gx * kRainBox + sx * oy;
                    T.matrix[1][0] = 0; T.matrix[1][1] = 1;   T.matrix[1][2] = 0; T.matrix[1][3] = oy;
                    T.matrix[2][0] = 0; T.matrix[2][1] = -sz; T.matrix[2][2] = 1; T.matrix[2][3] = gz * kRainBox + sz * oy;
                    RemixApi()->DrawInstance(&instance);
                }
            }
        }
    }
}

// ---- WEATHER-V2: rain proxies Ray Reconstruction keeps (emissive) --------------------------------------------
// With RR on the path-traced drops and the volumetric fog are not seen (docs/weather.md). Emissive surfaces are, so
// rain is shown where light would catch it: clusters of thin emissive streaks round each nearby lamp and along each
// head lamp's beam (brightness by distance to the light), and a soft emissive haze cone in each head lamp in the
// rain. Only while it rains and the sun is down; [weather] remix_rain_proxies=0 turns all of it off.
constexpr int kStreakLevels = 4, kStreakClusterDrops = 70;
remixapi_MaterialHandle g_streakMat[kStreakLevels] = {};
remixapi_MeshHandle g_streakMesh[kStreakLevels] = {};
remixapi_MaterialHandle g_hazeMat = nullptr;
remixapi_MeshHandle g_hazeMesh = nullptr;
std::wstring g_hazePath;

remixapi_MaterialHandle EmissiveMaterial(uint64_t hash, float intensity, const wchar_t* tex, bool blendTex) {
    remixapi_MaterialInfoOpaqueEXT op = {};
    op.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    op.albedoConstant = {0.0f, 0.0f, 0.0f};
    op.opacityConstant = 1.0f;
    op.roughnessConstant = 1.0f;
    op.useDrawCallAlphaState = blendTex ? 1 : 0;
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &op; info.hash = hash;
    info.emissiveColorConstant = {0.95f, 0.93f, 0.88f};
    info.emissiveIntensity = intensity;
    info.albedoTexture = tex;
    info.emissiveTexture = tex;
    info.filterMode = 1; info.wrapModeU = 2; info.wrapModeV = 2;
    remixapi_MaterialHandle h = nullptr;
    const remixapi_ErrorCode rc = RemixApi()->CreateMaterial(&info, &h);
    Log("rain proxies: emissive material %.2f%s -> %d", intensity, tex ? " (haze texture)" : "", static_cast<int>(rc));
    return rc == REMIXAPI_ERROR_CODE_SUCCESS ? h : nullptr;
}

// A unit cluster: streaks spread through a sphere of radius 1 and a fall height of 2 (y -1..1).
remixapi_MeshHandle StreakCluster(int level, remixapi_MaterialHandle mat) {
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    for (int d = 0; d < kStreakClusterDrops; ++d) {
        float x, y, z;
        do { x = Hash2(d, level * 11 + 1) * 2 - 1; y = Hash2(d, level * 11 + 2) * 2 - 1; z = Hash2(d, level * 11 + 3) * 2 - 1; } while (x * x + z * z > 1.0f);
        const float len = 0.10f + 0.06f * Hash2(d, level * 11 + 4), w = 0.006f;   // cluster units: ~1-2 px at 1080p once scaled
        for (int q = 0; q < 2; ++q) {
            const float dx = q == 0 ? w : 0.0f, dz = q == 0 ? 0.0f : w;
            const uint32_t b = static_cast<uint32_t>(verts.size());
            const float px[4] = {x - dx, x + dx, x + dx, x - dx}, pz[4] = {z - dz, z + dz, z + dz, z - dz}, py[4] = {y, y, y + len, y + len};
            for (int k = 0; k < 4; ++k) {
                remixapi_HardcodedVertex v = {};
                v.position[0] = px[k]; v.position[1] = py[k]; v.position[2] = pz[k];
                v.normal[0] = q == 0 ? 0.0f : 1.0f; v.normal[2] = q == 0 ? 1.0f : 0.0f;
                v.color = 0xFFFFFFFFu;
                verts.push_back(v);
            }
            const uint32_t t[6] = {0, 1, 2, 0, 2, 3};
            for (uint32_t k : t) idx.push_back(b + k);
        }
    }
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data(); surface.vertices_count = verts.size();
    surface.indices_values = idx.data(); surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0; surface.material = mat;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO; mesh.hash = 0x5354524B00000100ull + level;
    mesh.surfaces_values = &surface; mesh.surfaces_count = 1;
    remixapi_MeshHandle h = nullptr;
    return RemixApi()->CreateMesh(&mesh, &h) == REMIXAPI_ERROR_CODE_SUCCESS ? h : nullptr;
}

// The haze: a cone along +z (apex at 0, length 1, radius 1 at z=1), a texture whose alpha and emission fade along
// the beam (v) and to the sides (u): no edges.
bool WriteHazeDds(const std::wstring& path) {
    const int n = 64;
    std::vector<uint8_t> px(static_cast<size_t>(n) * n * 4);
    for (int y = 0; y < n; ++y) for (int x = 0; x < n; ++x) {
        const float u = (x + 0.5f) / n, v = (y + 0.5f) / n;   // u round the cone, v along it
        const float across = std::sin(u * 3.14159265f);        // 0 at the seam edges of the visible half
        const float along = std::pow(1.0f - v, 1.6f) * (std::min)(1.0f, v * 8.0f);
        const float a = across * across * along;
        uint8_t* q = &px[(static_cast<size_t>(y) * n + x) * 4];
        const uint8_t l = static_cast<uint8_t>(a * 255.0f + 0.5f);
        q[0] = l; q[1] = l; q[2] = l; q[3] = static_cast<uint8_t>(a * 0.35f * 255.0f + 0.5f);
    }
    uint32_t header[32] = {};
    header[0] = 0x20534444; header[1] = 124; header[2] = 0x100F; header[3] = n; header[4] = n; header[5] = n * 4;
    header[19] = 32; header[20] = 0x41; header[22] = 32;
    header[23] = 0x00FF0000; header[24] = 0x0000FF00; header[25] = 0x000000FF; header[26] = 0xFF000000; header[27] = 0x1000;
    FILE* f = _wfopen(path.c_str(), L"wb");
    if (!f) return false;
    const bool ok = fwrite(header, 4, 32, f) == 32 && fwrite(px.data(), 1, px.size(), f) == px.size();
    fclose(f);
    return ok;
}

remixapi_MeshHandle HazeCone(remixapi_MaterialHandle mat) {
    std::vector<remixapi_HardcodedVertex> verts;
    std::vector<uint32_t> idx;
    const int seg = 16, rings = 8;
    for (int r = 0; r <= rings; ++r) for (int sgm = 0; sgm <= seg; ++sgm) {
        const float v = static_cast<float>(r) / rings, a = static_cast<float>(sgm) / seg * 6.2831853f;
        remixapi_HardcodedVertex vx = {};
        vx.position[0] = std::cos(a) * v; vx.position[1] = std::sin(a) * v; vx.position[2] = v;
        vx.normal[0] = std::cos(a); vx.normal[1] = std::sin(a);
        vx.texcoord[0] = std::fabs(static_cast<float>(sgm) / seg * 2.0f - 1.0f) * 0.5f + 0.25f;   // brightest along the middle
        vx.texcoord[1] = v;
        vx.color = 0xFFFFFFFFu;
        verts.push_back(vx);
    }
    for (int r = 0; r < rings; ++r) for (int sgm = 0; sgm < seg; ++sgm) {
        const uint32_t a = r * (seg + 1) + sgm, b = a + seg + 1;
        const uint32_t t[6] = {a, b, a + 1, a + 1, b, b + 1};
        for (uint32_t k : t) idx.push_back(k);
    }
    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data(); surface.vertices_count = verts.size();
    surface.indices_values = idx.data(); surface.indices_count = idx.size();
    surface.skinning_hasvalue = 0; surface.material = mat;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO; mesh.hash = 0x48415A4500000001ull;
    mesh.surfaces_values = &surface; mesh.surfaces_count = 1;
    remixapi_MeshHandle h = nullptr;
    return RemixApi()->CreateMesh(&mesh, &h) == REMIXAPI_ERROR_CODE_SUCCESS ? h : nullptr;
}

void DrawXf(remixapi_MeshHandle mesh, const float ax[3], const float ay[3], const float az[3], const float o[3], bool blend, int alpha255) {
    remixapi_InstanceInfo inst = {};
    inst.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
    inst.mesh = mesh; inst.doubleSided = 1;
    remixapi_InstanceInfoBlendEXT b = {};
    if (blend) {
        b.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
        b.alphaBlendEnabled = 1; b.srcColorBlendFactor = 6; b.dstColorBlendFactor = 7;
        b.srcAlphaBlendFactor = 1; b.dstAlphaBlendFactor = 7; b.writeMask = 0xFFFFFFFFu;
        b.textureColorArg1Source = 1; b.textureColorOperation = 3;
        b.textureAlphaArg1Source = 1; b.textureAlphaArg2Source = 3; b.textureAlphaOperation = 3;   // texture x factor
        b.tFactor = (static_cast<uint32_t>(alpha255) << 24) | 0x00FFFFFFu;
        inst.pNext = &b;
    }
    remixapi_Transform& T = inst.transform;
    for (int r = 0; r < 3; ++r) { T.matrix[r][0] = ax[r]; T.matrix[r][1] = ay[r]; T.matrix[r][2] = az[r]; T.matrix[r][3] = o[r]; }
    RemixApi()->DrawInstance(&inst);
}

void DrawRainProxies(float ex, float ey, float ez, float viewMix) {
    const gta2::WeatherState& w = gta2::WeatherNow();
    static int enabled = 0; static DWORD read = 0;
    if (GetTickCount() - read >= 1000) { read = GetTickCount(); enabled = GetPrivateProfileIntA("weather", "remix_rain_proxies", 0, g_ini); }
    if (!enabled || !w.active || w.rain < 0.05f || viewMix < 0.99f) return;
    float el = 0.0f, az = 0.0f;
    TimeOfDayAngles(&el, &az);
    const float night = (std::max)(0.0f, (std::min)(1.0f, (-el + 2.0f) / 8.0f));   // 0 above +2 deg .. 1 below -6 deg
    if (night < 0.02f) return;
    if (!g_streakMat[0]) {
        static const float kI[kStreakLevels] = {0.6f, 1.2f, 2.4f, 4.5f};
        for (int l = 0; l < kStreakLevels; ++l) {
            g_streakMat[l] = EmissiveMaterial(0x5354524B4D000000ull + l, kI[l], nullptr, false);
            g_streakMesh[l] = g_streakMat[l] ? StreakCluster(l, g_streakMat[l]) : nullptr;
        }
        wchar_t exe[MAX_PATH] = {};
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        std::wstring dir = exe; dir = dir.substr(0, dir.find_last_of(L"\\/")) + L"\\gta2dx9_cache";
        CreateDirectoryW(dir.c_str(), nullptr);
        g_hazePath = dir + L"\\wx_haze.dds";
        if (WriteHazeDds(g_hazePath)) { g_hazeMat = EmissiveMaterial(0x48415A454D415401ull, 1.2f, g_hazePath.c_str(), true); if (g_hazeMat) g_hazeMesh = HazeCone(g_hazeMat); }
    }
    // The nearest lights that reach the street: up to 20 point lamps and 12 head-lamp spots.
    struct L { float d; const RemixLightDesc* desc; };
    std::vector<L> pts, spots;
    for (const RemixTrackedLight& t : LightsTracked()) {
        if (!t.drawn || t.def.intensity <= 0.02f) continue;
        const float dx = t.def.pos[0] - ex, dy = t.def.pos[1] - ey, dz = t.def.pos[2] - ez, d = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (d > 28.0f) continue;
        (t.def.spot ? spots : pts).push_back({d, &t.def});
    }
    {
        static DWORD logT = 0;
        if (GetTickCount() - logT >= 5000) {
            logT = GetTickCount();
            int spotN = 0;
            for (const RemixTrackedLight& tl : LightsTracked()) if (tl.drawn && tl.def.spot) ++spotN;
            Log("rain proxies: %zu lamps and %zu spots within 28 (of %zu tracked, %d drawn spots), rain %.2f night %.2f",
                pts.size(), spots.size(), LightsTracked().size(), spotN, w.rain, night);
        }
    }
    std::sort(pts.begin(), pts.end(), [](const L& a, const L& b) { return a.d < b.d; });
    std::sort(spots.begin(), spots.end(), [](const L& a, const L& b) { return a.d < b.d; });
    if (pts.size() > 20) pts.resize(20);
    if (spots.size() > 12) spots.resize(12);
    const float t = static_cast<float>(std::fmod(w.seconds, 3600.0));
    const float rainK = w.rain * night;
    auto fall = [&](float scale) { return std::fmod(t * 7.5f / scale, 2.0f); };   // in cluster units
    // Clusters are drawn in two layers offset by the fall height so the fall wraps unseen.
    auto cluster = [&](int level, const float c[3], float sx, float sy, float sz) {
        if (!g_streakMesh[level]) return;
        const float f = fall(sy);
        for (int layer = 0; layer < 2; ++layer) {
            const float ax[3] = {sx, 0, 0}, ay[3] = {0, sy, 0}, azv[3] = {0, 0, sz};
            const float o[3] = {c[0], c[1] - (f - layer * 2.0f) * sy, c[2]};
            DrawXf(g_streakMesh[level], ax, ay, azv, o, false, 255);
        }
    };
    for (const L& l : pts) {
        const float k = l.desc->intensity * rainK * (1.0f - l.d / 28.0f);
        if (k < 0.05f) continue;
        const float* p = l.desc->pos;
        const int lv = k > 0.6f ? 3 : k > 0.35f ? 2 : k > 0.15f ? 1 : 0;
        cluster(lv, p, 0.7f, 0.7f, 0.7f);
        cluster((std::max)(0, lv - 1), p, 1.5f, 1.5f, 1.5f);
        cluster((std::max)(0, lv - 2), p, 2.6f, 2.6f, 2.6f);
    }
    for (const L& l : spots) {
        const float k = l.desc->intensity * rainK * (1.0f - l.d / 28.0f);
        if (k < 0.05f) continue;
        float dir[3] = {l.desc->dir[0], l.desc->dir[1], l.desc->dir[2]};
        const float dl = std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
        if (dl < 1e-4f) continue;
        for (float& v : dir) v /= dl;
        const int lv = k > 0.5f ? 3 : k > 0.25f ? 2 : 1;
        // Streaks along the beam: near (bright), mid, far (dim).
        for (int s = 0; s < 3; ++s) {
            const float along = 0.6f + 1.4f * s, c[3] = {l.desc->pos[0] + dir[0] * along, l.desc->pos[1] + dir[1] * along, l.desc->pos[2] + dir[2] * along};
            cluster((std::max)(0, lv - s), c, 0.35f + 0.3f * s, 0.5f, 0.35f + 0.3f * s);
        }
        // The haze cone: along the beam, 5 blocks, the cone's half angle.
        if (g_hazeMesh) {
            const float len = 5.0f, rad = len * std::tan((std::max)(10.0f, (std::min)(40.0f, l.desc->coneAngleDeg > 0 ? l.desc->coneAngleDeg : 25.0f)) * 0.0174533f);
            float up[3] = {0, 1, 0};
            if (std::fabs(dir[1]) > 0.9f) { up[0] = 1; up[1] = 0; }
            float sx[3] = {up[1] * dir[2] - up[2] * dir[1], up[2] * dir[0] - up[0] * dir[2], up[0] * dir[1] - up[1] * dir[0]};
            const float sl = std::sqrt(sx[0] * sx[0] + sx[1] * sx[1] + sx[2] * sx[2]);
            for (float& v : sx) v /= sl;
            const float sy[3] = {dir[1] * sx[2] - dir[2] * sx[1], dir[2] * sx[0] - dir[0] * sx[2], dir[0] * sx[1] - dir[1] * sx[0]};
            const float ax[3] = {sx[0] * rad, sx[1] * rad, sx[2] * rad}, ay[3] = {sy[0] * rad, sy[1] * rad, sy[2] * rad};
            const float azv[3] = {dir[0] * len, dir[1] * len, dir[2] * len};
            const int a = static_cast<int>((std::min)(1.0f, k) * 255.0f);
            DrawXf(g_hazeMesh, ax, ay, azv, l.desc->pos, true, a);
        }
    }
}
}  // namespace

void RemixWetFrame(const gta2::Map& map, float eyeX, float eyeY, float eyeZ, float viewMix) {
    const DWORD now = GetTickCount();
    if (!g_ini[0] || now - g_lastRead >= 1000) { g_lastRead = now; ReadSettings(); }
    if (!RemixApiHasInstances() || map.Empty() || viewMix < 0.01f) return;
    DrawProbeBoard(map, eyeX, eyeY, eyeZ);
    DrawRemixRain(eyeX, eyeY, eyeZ, viewMix);
    DrawRainProxies(eyeX, eyeY, eyeZ, viewMix);
    {
        // The lights near the eye, for the screen-space rain (weather_fx DrawScreenRain).
        std::vector<gta2::ScreenRainLight> sl;
        for (const RemixTrackedLight& t : LightsTracked()) {
            if (!t.drawn || t.def.intensity <= 0.02f) continue;
            const float dx = t.def.pos[0] - eyeX, dy = t.def.pos[1] - eyeY, dz = t.def.pos[2] - eyeZ;
            const float reach = (std::min)(4.0f, (std::max)(1.0f, t.def.radius * 0.6f));
            if (dx * dx + dy * dy + dz * dz > (reach + 3.0f) * (reach + 3.0f)) continue;
            gta2::ScreenRainLight L;
            for (int k = 0; k < 3; ++k) { L.pos[k] = t.def.pos[k]; L.rgb[k] = t.def.rgb[k]; }
            L.intensity = t.def.intensity; L.radius = reach;
            sl.push_back(L);
            if (sl.size() >= 24) break;
        }
        gta2::SetScreenRainLights(sl);
    }
    {
        Settings e = g_dev;
        if (e.mode < 0) {
            // Production (WEATHER-V2 A): the darkening film follows the wetness; by night a
            // low-reflection water film fades in by steps of its refractive index (1.0 .. 1.10).
            const gta2::WeatherState& w = gta2::WeatherNow();
            const float wet = w.active ? w.wet : 0.0f;
            float el = 0.0f, az = 0.0f;
            TimeOfDayAngles(&el, &az);
            const float n = (std::max)(0.0f, (std::min)(1.0f, (-el - 2.0f) / 8.0f));   // 0 above -2 deg .. 1 below -10 deg
            static int dark = 100, nightFilm = 0;
            static DWORD darkRead = 0;
            if (GetTickCount() - darkRead >= 1000) {
                darkRead = GetTickCount();
                dark = GetPrivateProfileIntA("weather", "remix_wet_dark", 100, g_ini);
                nightFilm = GetPrivateProfileIntA("weather", "remix_night_film", 0, g_ini);   // off: it mirrored the gantry signs as sharp ghosts (p1l); the wet roughness gives the streaks
            }
            const int k = nightFilm ? static_cast<int>(std::lround(8.0f * n * wet)) : 0;
            e.mode = wet < 0.02f ? 0 : (k > 0 ? 6 : 3);
            // By night the darkening halves, so the lamp pools keep their light (the water film carries the wet look).
            e.alpha = static_cast<int>(std::lround(wet * dark * (1.0f - 0.5f * n)));
            e.rough = 8; e.albedo = 0; e.filmStatic = 0; e.alphaSrc = 3; e.decalBits = 0; e.puddleAlpha = 0;
            e.waterIor = 100 + static_cast<int>(std::lround(1.25f * k));
            e.waterTrans = 100 - static_cast<int>(std::lround(0.75f * k));
        }
        const bool material = e.mode != g_set.mode || e.rough != g_set.rough || e.albedo != g_set.albedo || e.filmStatic != g_set.filmStatic ||
                               e.waterIor != g_set.waterIor || e.waterTrans != g_set.waterTrans || e.puddleRough != g_set.puddleRough ||
                               e.vcolorAlpha != g_set.vcolorAlpha || e.liftMilli != g_set.liftMilli || (e.filmStatic && e.alpha != g_set.alpha);
        if (material) {
            ++g_generation;
            Log("remix wet: mode %d alpha %d water ior %.3f (gen %d)", e.mode, e.alpha, e.waterIor / 100.0f, g_generation);
        }
        g_set = e;
    }
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
    // Puddles: production (wx_wet_mode < 0) from the wetness, or [devtools] wx_puddle_level 1-4.
    static int puddleForce = -1;
    static DWORD puddleRead = 0;
    if (GetTickCount() - puddleRead >= 1000) { puddleRead = GetTickCount(); puddleForce = Dev("wx_puddle_level", -1); }
    int puddleLevel = 0;
    if (puddleForce >= 0) puddleLevel = (std::min)(8, puddleForce);
    else if (g_dev.mode < 0) {
        const float wet = gta2::WeatherNow().active ? gta2::WeatherNow().wet : 0.0f;
        // 8 sizes from wetness 0.30 up: the first threshold is above almost every point of the field,
        // so a puddle grows out of nothing instead of appearing at its size.
        puddleLevel = wet < 0.3f ? 0 : (std::min)(8, 1 + static_cast<int>((wet - 0.3f) / 0.7f * 8.0f));
    }
    if (puddleLevel > 0 && !g_puddleWater) {
        remixapi_MaterialInfoTranslucentEXT tr = {};
        tr.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT;
        tr.refractiveIndex = 1.33f; tr.transmittanceColor = {0.95f, 0.95f, 0.96f};   // thin water: the asphalt shows through steeply tr.transmittanceMeasurementDistance = 1.0f;
        tr.thinWallThickness_hasvalue = 1; tr.thinWallThickness_value = 0.1f;
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO; info.pNext = &tr; info.hash = 0x5745540500000001ull;
        RemixApi()->CreateMaterial(&info, &g_puddleWater);
        Log("remix wet: puddle water material %s", g_puddleWater ? "made" : "refused");
    }
    if (puddleLevel > 0 && !g_film) {
        g_film = MakeOpaque(0x5745540100000001ull ^ salt, 0.0f, 0.08f, nullptr);
        g_filmGen = g_generation;
    }
    const float puddleThr = 0.62f - 0.02f * puddleLevel;   // level 1 0.60 (gutter peaks only) .. level 8 0.46
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
            if (puddleLevel > 0 && g_puddleWater && g_film) {
                // Rim first (lower thresholds, larger), then the water on top.
                // The damp rim: three faint steps, each a little smaller and on top, so the edge darkens gradually.
                if (remixapi_MeshHandle m = PuddleMesh(map, x, z, 10, puddleThr - 0.045f, 0.0050f, g_film, puddleLevel)) Draw(m, 0, true, 3, 0, 1, static_cast<int>(12 * viewMix));
                if (remixapi_MeshHandle m = PuddleMesh(map, x, z, 11, puddleThr - 0.030f, 0.0052f, g_film, puddleLevel)) Draw(m, 0, true, 3, 0, 1, static_cast<int>(12 * viewMix));
                if (remixapi_MeshHandle m = PuddleMesh(map, x, z, 12, puddleThr - 0.015f, 0.0054f, g_film, puddleLevel)) Draw(m, 0, true, 3, 0, 1, static_cast<int>(12 * viewMix));
                if (viewMix > 0.99f)
                    if (remixapi_MeshHandle m = PuddleMesh(map, x, z, 13, puddleThr, 0.006f, g_puddleWater, puddleLevel)) Draw(m, 0, false, 1, 0, 1, 255);
            }
            if (palpha > 0 && g_puddle) {
                if (remixapi_MeshHandle m = ChunkMesh(map, x, z, 3, g_puddle)) Draw(m, static_cast<uint32_t>(g_set.decalBits), true, 1, 3, 3, palpha);
            }
        }
    }
}

}  // namespace gta2dx9
