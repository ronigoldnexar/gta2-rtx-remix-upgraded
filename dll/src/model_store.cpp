#include "model_store.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <array>
#include <deque>
#include <map>
#include <tuple>
#include <unordered_set>
#include <set>

#include "frame_log.h"
#include "log.h"
#include "remix_api.h"

#define XXH_INLINE_ALL
#include "../deps/xxhash/xxhash.h"

namespace gta2dx9 {
namespace {

// A deque, not a vector: every Model* handed out (sprites keep one across a
// frame, car bodies and map objects key caches by it) must stay valid for the
// process's life, and a deque never moves its elements when it grows.
std::deque<Model> g_models;
std::unordered_set<const Model*> g_known;   // every address the store ever handed out
// Meshes of derived models registered with dynamicBuffers (PERF-3): their buffers are
// dynamic default-pool buffers written with DISCARD (see BuffersFor).
std::unordered_set<const ModelMesh*> g_dynamicMeshes;
std::map<std::string, size_t> g_byName;
std::vector<std::string> g_carDefault;    // cycled by sprite number
std::map<int, std::string> g_carBySprite;
std::map<int, std::string> g_carByModel;   // by the game's vehicle model number
float g_paintTint[3] = {1.0f, 1.0f, 1.0f};
bool g_paintTintOn = false;
// FIX-CAR-RENDER: soft car paint masks. The importer's paint split is a binary texel mask
// (hue/saturation threshold) drawn as two alpha-tested halves; a repaint far from the
// model's own paint then showed as two flat tones with speckled, stair-stepped borders.
// With soft masks on, a car's "_paint" texture gets an 8-bit coverage alpha (the binary
// mask widened by chroma similarity, then blurred) and the car is one draw of the paint
// half: colour = texel * lerp(1, tint, coverage). The rest half is skipped. Off under
// Remix (which keeps the alpha-tested pair) and on devices without the TEMP stage argument.
bool g_softPaintSetting = true;
int g_softPaintCaps = -1;                       // -1 unknown, 0 no, 1 yes
std::unordered_set<std::string> g_softPaintTex;  // "_paint" textures given a soft mask
std::unordered_set<std::string> g_paintRests;    // the other half of a split texture

// A JSON object of "number": "name" pairs, as the cars maps are written.
std::map<int, std::string> NumberMap(const std::string& text, const char* key) {
    std::map<int, std::string> out;
    const std::string quoted = std::string("\"") + key + "\"";
    const size_t at = text.find(quoted);
    if (at == std::string::npos) return out;
    const size_t open = text.find('{', at);
    const size_t close = text.find('}', open);
    if (open == std::string::npos || close == std::string::npos) return out;
    const std::string block = text.substr(open + 1, close - open - 1);
    size_t pos = 0;
    while (true) {
        const size_t q1 = block.find('"', pos);
        if (q1 == std::string::npos) break;
        const size_t q2 = block.find('"', q1 + 1);
        const size_t q3 = block.find('"', q2 + 1);
        const size_t q4 = block.find('"', q3 + 1);
        if (q2 == std::string::npos || q3 == std::string::npos || q4 == std::string::npos) break;
        const std::string number = block.substr(q1 + 1, q2 - q1 - 1), name = block.substr(q3 + 1, q4 - q3 - 1);
        if (!number.empty() && isdigit(static_cast<unsigned char>(number[0]))) out[atoi(number.c_str())] = name;
        pos = q4 + 1;
    }
    return out;
}
std::string g_pedestrian;
std::vector<std::string> g_pedestrians;  // the "pedestrians" list, g_pedestrian when there is none
// Pedestrian types from the manifest: which remaps, which models, tinted or not.
struct PedType {
    std::string name;
    std::vector<int> remaps;
    std::vector<std::string> models;
    bool tint = false;
    float scale = 1.0f, width = 1.0f;       // ASSET-PEDS-2: the type's build (the Hulks), 1 = the crowd's
};
std::vector<PedType> g_pedTypes;
int g_pedTypeByRemap[64];                 // index into g_pedTypes, -1 none
float g_pedRemapColour[64][3];            // the remap's clothing colour (0-255), 0 when unknown
float g_pedOutfit[64][9];                 // ASSET-PEDS: top, bottom, hair (0-255) by remap, 0 = keep the avatar's
bool g_zoneOn = false;
float g_zoneTint[3][3] = {};
bool g_zoneHair = false;
std::map<int, int> g_pedRemapByPalette;   // physical palette -> remap, from the loaded style
std::map<std::string, std::string> g_props;
std::vector<gta2::Vec3> g_mapLamps;
std::vector<gta2::Vec3> g_mapLampPosts;   // see MapLampPosts
std::string g_folder;
bool g_loaded = false;
int g_drawn = 0;

std::map<std::string, IDirect3DTexture9*> g_textures;
size_t g_textureBytes = 0;

bool ReadAll(const std::string& path, std::vector<uint8_t>* out) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    out->resize(size > 0 ? static_cast<size_t>(size) : 0);
    const bool ok = size > 0 && fread(out->data(), 1, out->size(), f) == out->size();
    fclose(f);
    return ok;
}

// The model textures' files, read ahead on a thread of their own (PERF-2). The warm-up
// below creates and uploads every model texture in the first seconds of a level; with
// 73 car models that is ~680 TGA files, and reading them on the render thread put
// 10-100 ms spikes into those seconds. The reader keeps at most kPrefetchBytes of
// files waiting; TextureFor takes a file from here when it is ready and reads it
// itself otherwise, so nothing ever waits on the thread.
constexpr size_t kPrefetchBytes = 96u << 20;
CRITICAL_SECTION g_prefetchLock;
std::map<std::string, std::vector<uint8_t>> g_prefetched;
size_t g_prefetchedBytes = 0;
std::vector<std::string> g_prefetchList;   // read in this order; fixed once the thread starts
volatile LONG g_prefetchStarted = 0;
volatile LONG g_prefetchSoften = 0;           // FIX-PERF-VSWITCH: the reader softens car paint masks
std::set<std::string> g_prefetchSoftened;     // files the reader softened (under g_prefetchLock)
bool CarTextureName(const std::string& file);
void SoftenPaintMask(uint8_t* px, int w, int h);

DWORD WINAPI PrefetchThread(void*) {
    for (const std::string& file : g_prefetchList) {
        for (;;) {
            EnterCriticalSection(&g_prefetchLock);
            const size_t waiting = g_prefetchedBytes;
            LeaveCriticalSection(&g_prefetchLock);
            if (waiting < kPrefetchBytes) break;
            Sleep(5);
        }
        std::vector<uint8_t> data;
        if (!ReadAll(g_folder + "\\" + file, &data)) continue;
        // FIX-PERF-VSWITCH: a car's soft paint mask is worked out here rather than on the render
        // thread (SoftenPaintMask is tens of ms a picture), once the render thread has said it
        // applies (g_prefetchSoften: the setting, the device's stages, no Remix).
        bool softened = false;
        if (g_prefetchSoften && data.size() > 18 && data[2] == 2 && data[16] == 32 && file.size() > 10 &&
            file.compare(file.size() - 10, 10, "_paint.tga") == 0 && CarTextureName(file)) {
            const int w = data[12] | (data[13] << 8), h = data[14] | (data[15] << 8);
            if (w > 0 && h > 0 && data.size() >= 18u + static_cast<size_t>(w) * h * 4) {
                SoftenPaintMask(&data[18], w, h);
                softened = true;
            }
        }
        EnterCriticalSection(&g_prefetchLock);
        g_prefetchedBytes += data.size();
        g_prefetched[file] = std::move(data);
        if (softened) g_prefetchSoftened.insert(file);
        LeaveCriticalSection(&g_prefetchLock);
    }
    return 0;
}

// The prefetched file, moved out; false when the reader has not got to it (or never will).
bool TakePrefetched(const std::string& file, std::vector<uint8_t>* out, bool* softened = nullptr) {
    if (!g_prefetchStarted) return false;
    EnterCriticalSection(&g_prefetchLock);
    auto it = g_prefetched.find(file);
    const bool found = it != g_prefetched.end();
    if (found) {
        g_prefetchedBytes -= it->second.size();
        out->swap(it->second);
        g_prefetched.erase(it);
        if (softened) *softened = g_prefetchSoftened.erase(file) != 0;
    }
    LeaveCriticalSection(&g_prefetchLock);
    return found;
}

bool PrefetchReady(const std::string& file) {
    if (!g_prefetchStarted) return true;
    EnterCriticalSection(&g_prefetchLock);
    const bool found = g_prefetched.count(file) != 0;
    LeaveCriticalSection(&g_prefetchLock);
    return found;
}

struct Reader {
    const uint8_t* p;
    const uint8_t* end;
    bool ok = true;
    template <typename T> T Get() {
        T v{};
        if (p + sizeof(T) > end) { ok = false; return v; }
        memcpy(&v, p, sizeof(T));
        p += sizeof(T);
        return v;
    }
    void Bytes(void* out, size_t n) {
        if (p + n > end) { ok = false; memset(out, 0, n); return; }
        memcpy(out, p, n);
        p += n;
    }
};

bool LoadModel(const std::string& path, Model* model) {
    std::vector<uint8_t> data;
    if (!ReadAll(path, &data) || data.size() < 20 || memcmp(data.data(), "GMSH", 4) != 0) return false;
    Reader r{data.data() + 4, data.data() + data.size()};
    const uint32_t version = r.Get<uint32_t>();
    const uint32_t nodes = r.Get<uint32_t>(), meshes = r.Get<uint32_t>(), anims = r.Get<uint32_t>();
    const uint32_t skins = version >= 2 ? r.Get<uint32_t>() : 0;
    if ((version != 1 && version != 2) || nodes > 4096 || meshes > 4096 || anims > 256 || skins > 64) return false;
    model->nodes.resize(nodes);
    for (ModelNode& n : model->nodes) {
        r.Bytes(n.name, 32);
        n.name[31] = '\0';
        n.parent = r.Get<int32_t>();
        n.translation = {r.Get<float>(), r.Get<float>(), r.Get<float>()};
        for (float& q : n.rotation) q = r.Get<float>();
        n.scale = {r.Get<float>(), r.Get<float>(), r.Get<float>()};
        n.mesh = r.Get<int32_t>();
    }
    model->meshes.resize(meshes);
    for (ModelMesh& m : model->meshes) {
        const uint32_t vertices = r.Get<uint32_t>(), indices = r.Get<uint32_t>();
        char texture[64];
        r.Bytes(texture, 64);
        texture[63] = '\0';
        m.texture = texture;
        m.skin = version >= 2 ? r.Get<int32_t>() : -1;
        if (vertices > 2000000 || indices > 6000000 || !r.ok) return false;
        m.vertices.resize(vertices);
        r.Bytes(m.vertices.data(), vertices * sizeof(ModelVertex));
        if (m.skin >= 0) {
            m.weights.resize(vertices);
            for (ModelSkinWeight& w : m.weights) {
                for (uint16_t& j : w.joint) j = r.Get<uint16_t>();
                for (float& f : w.weight) f = r.Get<float>();
            }
            model->skinned = true;
        }
        m.indices.resize(indices);
        r.Bytes(m.indices.data(), indices * sizeof(uint32_t));
        for (uint32_t& i : m.indices) if (i >= vertices) i = 0;
    }
    model->animations.resize(anims);
    for (ModelAnimation& a : model->animations) {
        char name[32];
        r.Bytes(name, 32);
        name[31] = '\0';
        a.name = name;
        const uint32_t channels = r.Get<uint32_t>();
        if (channels > 4096 || !r.ok) return false;
        a.channels.resize(channels);
        for (ModelChannel& c : a.channels) {
            c.node = r.Get<int32_t>();
            c.path = static_cast<int>(r.Get<uint32_t>());
            const uint32_t keys = r.Get<uint32_t>();
            if (keys > 100000 || !r.ok) return false;
            c.times.resize(keys);
            r.Bytes(c.times.data(), keys * sizeof(float));
            const uint32_t per = c.path == 1 ? 4 : 3;
            c.values.resize(keys * per);
            r.Bytes(c.values.data(), keys * per * sizeof(float));
            if (!c.times.empty()) a.length = (std::max)(a.length, c.times.back());
        }
    }
    model->skins.resize(skins);
    for (ModelSkin& sk : model->skins) {
        const uint32_t joints = r.Get<uint32_t>();
        if (joints > 1024 || !r.ok) return false;
        sk.joints.resize(joints);
        for (int& j : sk.joints) j = r.Get<int32_t>();
        sk.inverseBind.resize(joints);
        for (gta2::Mat4& m : sk.inverseBind) r.Bytes(m.m, sizeof(m.m));
    }
    for (ModelMesh& m : model->meshes) {
        if (m.skin >= static_cast<int>(model->skins.size())) m.skin = -1;
        for (ModelSkinWeight& w : m.weights)
            for (uint16_t& j : w.joint)
                if (m.skin >= 0 && j >= model->skins[m.skin].joints.size()) j = 0;
    }
    if (!r.ok) return false;
    // Bounds of the rest pose, through the node transforms.
    model->boundsMin = {1e9f, 1e9f, 1e9f};
    model->boundsMax = {-1e9f, -1e9f, -1e9f};
    return true;
}

gta2::Mat4 Multiply(const gta2::Mat4& a, const gta2::Mat4& b) {
    gta2::Mat4 out;
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
            out.m[r][c] = s;
        }
    return out;
}

// Row-vector S * R * T from a translation, a unit quaternion and a scale.
gta2::Mat4 Compose(const gta2::Vec3& t, const float* q, const gta2::Vec3& s) {
    const float x = q[0], y = q[1], z = q[2], w = q[3];
    gta2::Mat4 m;
    m.m[0][0] = (1 - 2 * (y * y + z * z)) * s.x; m.m[0][1] = (2 * (x * y + z * w)) * s.x; m.m[0][2] = (2 * (x * z - y * w)) * s.x;
    m.m[1][0] = (2 * (x * y - z * w)) * s.y;     m.m[1][1] = (1 - 2 * (x * x + z * z)) * s.y; m.m[1][2] = (2 * (y * z + x * w)) * s.y;
    m.m[2][0] = (2 * (x * z + y * w)) * s.z;     m.m[2][1] = (2 * (y * z - x * w)) * s.z;     m.m[2][2] = (1 - 2 * (x * x + y * y)) * s.z;
    m.m[3][0] = t.x; m.m[3][1] = t.y; m.m[3][2] = t.z; m.m[3][3] = 1.0f;
    return m;
}

// One clip's pose at `time`, written over the rest pose already in t/q/s.
void SampleClip(const Model& model, const ModelAnimation* animation, float time, std::vector<gta2::Vec3>* t,
                std::vector<std::array<float, 4>>* q, std::vector<gta2::Vec3>* s) {
    const size_t n = model.nodes.size();
    if (!animation || animation->length <= 0.0f) return;
    const float at = std::fmod(time, animation->length);
    for (const ModelChannel& c : animation->channels) {
        if (c.node < 0 || c.node >= static_cast<int>(n) || c.times.empty()) continue;
        const int per = c.path == 1 ? 4 : 3;
        // The keys either side of `at`, and where between them it falls.
        size_t k = 0;
        while (k + 1 < c.times.size() && c.times[k + 1] <= at) ++k;
        const size_t k2 = (std::min)(k + 1, c.times.size() - 1);
        const float span = c.times[k2] - c.times[k];
        const float f = span > 1e-6f ? (at - c.times[k]) / span : 0.0f;
        const float* a = &c.values[k * per];
        const float* b = &c.values[k2 * per];
        if (c.path == 1) {
            // Normalised linear blend of the quaternions, the short way.
            float dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
            const float sign = dot < 0.0f ? -1.0f : 1.0f;
            float r[4];
            for (int i = 0; i < 4; ++i) r[i] = a[i] * (1 - f) + b[i] * sign * f;
            const float len = std::sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2] + r[3] * r[3]);
            if (len > 1e-6f) for (float& v : r) v /= len;
            memcpy((*q)[c.node].data(), r, sizeof(r));
        } else {
            gta2::Vec3 v{a[0] * (1 - f) + b[0] * f, a[1] * (1 - f) + b[1] * f, a[2] * (1 - f) + b[2] * f};
            (c.path == 0 ? (*t)[c.node] : (*s)[c.node]) = v;
        }
    }
}

// The node world matrices of a pose: `animation` at `time`, blended toward
// `second` at `secondTime` by `weight` (nlerp on the rotations, lerp on the
// rest), then composed down the parent chain.
static float g_torsoTwist = 0.0f;   // see ModelSetTorsoTwist
static float g_headTurn = 0.0f;     // see ModelSetHeadTurn
// A node's world matrix turned about the model's vertical through its own
// origin (its children compose from it and turn with it).
static void TurnAboutUp(gta2::Mat4& M, float radians) {
    const float c = std::cos(radians), sn = std::sin(radians);
    const float px = M.m[3][0], pz = M.m[3][2];
    for (int r = 0; r < 4; ++r) {
        const float x = M.m[r][0], z = M.m[r][2];
        M.m[r][0] = x * c - z * sn;
        M.m[r][2] = x * sn + z * c;
    }
    M.m[3][0] += px - (px * c - pz * sn);
    M.m[3][2] += pz - (px * sn + pz * c);
}
// QB-27: the pose hook (see ModelSetPoseHook).
static ModelPoseHookFn g_poseHook = nullptr;
static void* g_poseHookContext = nullptr;
static uint64_t g_poseHookKey = 0;
// ANIM-VEHICLE-ENTRY: two-bone limb IK over the composed pose (see ModelSetLimbTarget).
// Limbs 0 left arm, 1 right arm, 2 left leg, 3 right leg; targets and poles in model space.
struct LimbIk { bool on = false; float t[3] = {}; float pole[3] = {}; float w = 0.0f; };
static LimbIk g_limbIk[4];
static uint64_t g_limbIkKey = 0;   // a hash of the quantised targets (the pose cache key)
static float g_limbResidual[4][3] = {};   // the part of each target out of reach last pose (model space)
struct LimbChain { int a = -1, b = -1, c = -1; std::vector<int> subA, subB, subC; };
static std::map<const Model*, std::array<LimbChain, 4>> g_limbChains;
static const std::array<LimbChain, 4>& LimbChainsFor(const Model& model) {
    auto it = g_limbChains.find(&model);
    if (it != g_limbChains.end()) return it->second;
    static const char* const kNames[4][3] = {{"Bip01 L UpperArm", "Bip01 L Forearm", "Bip01 L Hand"},
                                             {"Bip01 R UpperArm", "Bip01 R Forearm", "Bip01 R Hand"},
                                             {"Bip01 L Thigh", "Bip01 L Calf", "Bip01 L Foot"},
                                             {"Bip01 R Thigh", "Bip01 R Calf", "Bip01 R Foot"}};
    std::array<LimbChain, 4> chains;
    const int n = static_cast<int>(model.nodes.size());
    auto find = [&](const char* name) { for (int i = 0; i < n; ++i) if (strcmp(model.nodes[i].name, name) == 0) return i; return -1; };
    auto under = [&](int root, std::vector<int>* out) {
        for (int i = 0; i < n; ++i) {
            for (int k = i, guard = 0; k >= 0 && k < n && guard < 64; k = model.nodes[k].parent, ++guard) {
                if (k == root) { out->push_back(i); break; }
            }
        }
    };
    for (int l = 0; l < 4; ++l) {
        LimbChain& c = chains[l];
        c.a = find(kNames[l][0]); c.b = find(kNames[l][1]); c.c = find(kNames[l][2]);
        if (c.a < 0 || c.b < 0 || c.c < 0) { c.a = -1; continue; }
        under(c.a, &c.subA); under(c.b, &c.subB); under(c.c, &c.subC);
    }
    return g_limbChains.emplace(&model, chains).first->second;
}
// Rotates the nodes `sub` of `w` by the rotation taking direction u onto v, about `pivot`.
static void RotateNodes(std::vector<gta2::Mat4>* w, const std::vector<int>& sub, const gta2::Vec3& pivot,
                        gta2::Vec3 u, gta2::Vec3 v) {
    u = gta2::Normalize(u); v = gta2::Normalize(v);
    gta2::Vec3 axis = gta2::Cross(u, v);
    const float sn = std::sqrt(gta2::Dot(axis, axis)), cs = gta2::Dot(u, v);
    if (sn < 1e-6f) return;
    axis = axis * (1.0f / sn);
    const float k = 1.0f - cs;
    // Rodrigues, as a matrix R applied to column vectors: v' = R v.
    const float x = axis.x, y = axis.y, z = axis.z;
    const float R[3][3] = {{cs + x * x * k, x * y * k - z * sn, x * z * k + y * sn},
                           {y * x * k + z * sn, cs + y * y * k, y * z * k - x * sn},
                           {z * x * k - y * sn, z * y * k + x * sn, cs + z * z * k}};
    auto rot = [&](float* p) {
        const float a = p[0], b = p[1], c = p[2];
        p[0] = R[0][0] * a + R[0][1] * b + R[0][2] * c;
        p[1] = R[1][0] * a + R[1][1] * b + R[1][2] * c;
        p[2] = R[2][0] * a + R[2][1] * b + R[2][2] * c;
    };
    for (int i : sub) {
        gta2::Mat4& M = (*w)[i];
        for (int r = 0; r < 3; ++r) rot(M.m[r]);
        float p[3] = {M.m[3][0] - pivot.x, M.m[3][1] - pivot.y, M.m[3][2] - pivot.z};
        rot(p);
        M.m[3][0] = pivot.x + p[0]; M.m[3][1] = pivot.y + p[1]; M.m[3][2] = pivot.z + p[2];
    }
}
static void ApplyLimbIk(const Model& model, std::vector<gta2::Mat4>* w) {
    for (auto& r : g_limbResidual) r[0] = r[1] = r[2] = 0.0f;
    bool any = false;
    for (const LimbIk& l : g_limbIk) any = any || (l.on && l.w > 1e-3f);
    if (!any) return;
    const std::array<LimbChain, 4>& chains = LimbChainsFor(model);
    auto pos = [&](int i) { const gta2::Mat4& M = (*w)[i]; return gta2::Vec3{M.m[3][0], M.m[3][1], M.m[3][2]}; };
    for (int l = 0; l < 4; ++l) {
        const LimbIk& ik = g_limbIk[l];
        const LimbChain& ch = chains[l];
        if (!ik.on || ik.w <= 1e-3f || ch.a < 0) continue;
        // The end joint keeps the orientation the clip gave it (a foot stays flat,
        // a hand keeps its grip): remembered here, put back after the two turns.
        std::vector<gta2::Mat4> endRows;
        endRows.reserve(ch.subC.size());
        for (int i : ch.subC) endRows.push_back((*w)[i]);
        const gta2::Vec3 cOld = pos(ch.c);
        const gta2::Vec3 A = pos(ch.a), B = pos(ch.b), C = cOld;
        const float wgt = (std::min)(1.0f, ik.w);
        const gta2::Vec3 T{C.x + (ik.t[0] - C.x) * wgt, C.y + (ik.t[1] - C.y) * wgt, C.z + (ik.t[2] - C.z) * wgt};
        const gta2::Vec3 AB = B - A, BC = C - B, AT = T - A;
        const float la = std::sqrt(gta2::Dot(AB, AB)), lb = std::sqrt(gta2::Dot(BC, BC));
        {
            static std::set<std::pair<const Model*, int>> logged;
            if (logged.size() < 16 && logged.insert({&model, l}).second)
                Log("limb ik: %s limb %d upper %.3f lower %.3f (model height %.3f) root %.3f,%.3f,%.3f", model.name.c_str(), l, la, lb,
                    model.Height(), A.x, A.y, A.z);
        }
        float d = std::sqrt(gta2::Dot(AT, AT));
        if (la < 1e-5f || lb < 1e-5f || d < 1e-5f) continue;
        const gta2::Vec3 nrm = AT * (1.0f / d);
        d = (std::max)(std::fabs(la - lb) * 1.02f + 1e-4f, (std::min)(d, (la + lb) * 0.999f));
        // The bend: toward the pole, else the way the clip already bends it.
        gta2::Vec3 pole{ik.pole[0], ik.pole[1], ik.pole[2]};
        if (gta2::Dot(pole, pole) < 1e-8f) pole = AB;
        gta2::Vec3 bend = pole - nrm * gta2::Dot(pole, nrm);
        if (gta2::Dot(bend, bend) < 1e-10f) bend = AB - nrm * gta2::Dot(AB, nrm);
        if (gta2::Dot(bend, bend) < 1e-10f) continue;
        bend = gta2::Normalize(bend);
        const float cosA = (std::max)(-1.0f, (std::min)(1.0f, (la * la + d * d - lb * lb) / (2.0f * la * d)));
        const float sinA = std::sqrt((std::max)(0.0f, 1.0f - cosA * cosA));
        const gta2::Vec3 Bn = A + nrm * (la * cosA) + bend * (la * sinA);
        const gta2::Vec3 Tn = A + nrm * d;
        g_limbResidual[l][0] = T.x - Tn.x; g_limbResidual[l][1] = T.y - Tn.y; g_limbResidual[l][2] = T.z - Tn.z;
        RotateNodes(w, ch.subA, A, AB, Bn - A);
        const gta2::Vec3 C1 = pos(ch.c);
        RotateNodes(w, ch.subB, Bn, C1 - Bn, Tn - Bn);
        // The end joint and what hangs off it: moved with it, turned back to its own.
        const gta2::Vec3 cNew = pos(ch.c);
        for (size_t k = 0; k < ch.subC.size(); ++k) {
            gta2::Mat4& M = (*w)[ch.subC[k]];
            const gta2::Mat4& O = endRows[k];
            for (int r = 0; r < 3; ++r) for (int c = 0; c < 4; ++c) M.m[r][c] = O.m[r][c];
            M.m[3][0] = O.m[3][0] + (cNew.x - cOld.x);
            M.m[3][1] = O.m[3][1] + (cNew.y - cOld.y);
            M.m[3][2] = O.m[3][2] + (cNew.z - cOld.z);
        }
    }
}
// The overlay: a third clip blended over the pair (see ModelSetOverlay).
static const ModelAnimation* g_overlay = nullptr;
static float g_overlayTime = 0.0f, g_overlayWeight = 0.0f;
// ANIM-BLEND-AUDIT: more clips blended over the pair before the overlay, for one model
// (see ModelSetLayers).
static const Model* g_layerModel = nullptr;
static int g_layerCount = 0;
static const ModelAnimation* g_layerClip[kModelLayers] = {};
static float g_layerTime[kModelLayers] = {}, g_layerWeight[kModelLayers] = {};
// `clip` at `time` written over a copy of the pose so far (a joint the clip has no channel
// for keeps it), then blended into the pose by `weight` (lerp, nlerp on the rotations).
static void BlendOver(const Model& model, const ModelAnimation* clip, float time, float weight, std::vector<gta2::Vec3>& t,
                      std::vector<std::array<float, 4>>& q, std::vector<gta2::Vec3>& s) {
    const size_t n = model.nodes.size();
    std::vector<gta2::Vec3> t3(t), s3(s);
    std::vector<std::array<float, 4>> q3(q);
    SampleClip(model, clip, time, &t3, &q3, &s3);
    const float w = (std::min)(1.0f, weight), v = 1.0f - w;
    for (size_t i = 0; i < n; ++i) {
        t[i] = {t[i].x * v + t3[i].x * w, t[i].y * v + t3[i].y * w, t[i].z * v + t3[i].z * w};
        s[i] = {s[i].x * v + s3[i].x * w, s[i].y * v + s3[i].y * w, s[i].z * v + s3[i].z * w};
        const float* a = q[i].data();
        const float* b = q3[i].data();
        const float sign = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]) < 0.0f ? -1.0f : 1.0f;
        float r[4];
        for (int k = 0; k < 4; ++k) r[k] = a[k] * v + b[k] * sign * w;
        const float len = std::sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2] + r[3] * r[3]);
        if (len > 1e-6f) for (float& x : r) x /= len;
        memcpy(q[i].data(), r, sizeof(r));
    }
}
void NodeWorldsBlend(const Model& model, const ModelAnimation* animation, float time, const ModelAnimation* second,
                     float secondTime, float weight, std::vector<gta2::Mat4>* out) {
    const size_t n = model.nodes.size();
    std::vector<gta2::Vec3> t(n), s(n);
    std::vector<std::array<float, 4>> q(n);
    for (size_t i = 0; i < n; ++i) {
        t[i] = model.nodes[i].translation;
        s[i] = model.nodes[i].scale;
        memcpy(q[i].data(), model.nodes[i].rotation, sizeof(float) * 4);
    }
    const bool blend = second && second->length > 0.0f && weight > 1e-3f;
    if (blend && weight >= 0.999f) {
        // The second clip alone, but over the first: a clip with channels for only
        // some joints (a legs-only layer, ACTIONS-3D-4's turn_step) must not leave
        // the rest in the bind pose (the arms of the T/A pose).
        SampleClip(model, animation, time, &t, &q, &s);
        SampleClip(model, second, secondTime, &t, &q, &s);
    } else {
        SampleClip(model, animation, time, &t, &q, &s);
        if (blend) {
            std::vector<gta2::Vec3> t2(t), s2(s);
            std::vector<std::array<float, 4>> q2(q);
            SampleClip(model, second, secondTime, &t2, &q2, &s2);
            const float w = weight, v = 1.0f - weight;
            for (size_t i = 0; i < n; ++i) {
                t[i] = {t[i].x * v + t2[i].x * w, t[i].y * v + t2[i].y * w, t[i].z * v + t2[i].z * w};
                s[i] = {s[i].x * v + s2[i].x * w, s[i].y * v + s2[i].y * w, s[i].z * v + s2[i].z * w};
                const float* a = q[i].data();
                const float* b = q2[i].data();
                const float sign = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]) < 0.0f ? -1.0f : 1.0f;
                float r[4];
                for (int k = 0; k < 4; ++k) r[k] = a[k] * v + b[k] * sign * w;
                const float len = std::sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2] + r[3] * r[3]);
                if (len > 1e-6f) for (float& x : r) x /= len;
                memcpy(q[i].data(), r, sizeof(r));
            }
        }
    }
    if (g_layerModel == &model) {
        for (int k = 0; k < g_layerCount; ++k)
            if (g_layerClip[k] && g_layerClip[k]->length > 0.0f && g_layerWeight[k] > 1e-3f)
                BlendOver(model, g_layerClip[k], g_layerTime[k], g_layerWeight[k], t, q, s);
    }
    if (g_overlay && g_overlay->length > 0.0f && g_overlayWeight > 1e-3f) {
        // Written over a copy of the pose so far (a joint the overlay has no
        // channel for keeps it: an upper-body layer leaves the legs walking),
        // then blended in by its weight.
        std::vector<gta2::Vec3> t3(t), s3(s);
        std::vector<std::array<float, 4>> q3(q);
        SampleClip(model, g_overlay, g_overlayTime, &t3, &q3, &s3);
        const float w = (std::min)(1.0f, g_overlayWeight), v = 1.0f - w;
        for (size_t i = 0; i < n; ++i) {
            t[i] = {t[i].x * v + t3[i].x * w, t[i].y * v + t3[i].y * w, t[i].z * v + t3[i].z * w};
            s[i] = {s[i].x * v + s3[i].x * w, s[i].y * v + s3[i].y * w, s[i].z * v + s3[i].z * w};
            const float* a = q[i].data();
            const float* b = q3[i].data();
            const float sign = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]) < 0.0f ? -1.0f : 1.0f;
            float r[4];
            for (int k = 0; k < 4; ++k) r[k] = a[k] * v + b[k] * sign * w;
            const float len = std::sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2] + r[3] * r[3]);
            if (len > 1e-6f) for (float& x : r) x /= len;
            memcpy(q[i].data(), r, sizeof(r));
        }
    }
    out->resize(n);
    // Parents come before children in glTF order in Kenney's kits; walk in
    // order and fall back to a second pass if not.
    std::vector<bool> done(n, false);
    for (int pass = 0; pass < 2; ++pass) {
        for (size_t i = 0; i < n; ++i) {
            if (done[i]) continue;
            const int p = model.nodes[i].parent;
            if (p >= 0 && p < static_cast<int>(n) && !done[p] && pass == 0) continue;
            const gta2::Mat4 local = Compose(t[i], q[i].data(), s[i]);
            (*out)[i] = (p >= 0 && p < static_cast<int>(n)) ? Multiply(local, (*out)[p]) : local;
            if (g_torsoTwist != 0.0f && model.nodes[i].name[0] == 'B' && strcmp(model.nodes[i].name, "Bip01 Spine1") == 0) {
                // Turned about the model's vertical through the joint; the
                // children (chest, arms, head) compose from it and turn with it.
                gta2::Mat4& M = (*out)[i];
                const float c = std::cos(g_torsoTwist), sn = std::sin(g_torsoTwist);
                const float px = M.m[3][0], pz = M.m[3][2];
                for (int r = 0; r < 4; ++r) {
                    const float x = M.m[r][0], z = M.m[r][2];
                    M.m[r][0] = x * c - z * sn;
                    M.m[r][2] = x * sn + z * c;
                }
                M.m[3][0] += px - (px * c - pz * sn);
                M.m[3][2] += pz - (px * sn + pz * c);
            }
            if (g_headTurn != 0.0f && model.nodes[i].name[0] == 'B') {
                if (strcmp(model.nodes[i].name, "Bip01 Neck") == 0) TurnAboutUp((*out)[i], 0.4f * g_headTurn);
                else if (strcmp(model.nodes[i].name, "Bip01 Head") == 0) TurnAboutUp((*out)[i], 0.6f * g_headTurn);
            }
            done[i] = true;
        }
    }
    ApplyLimbIk(model, out);
    if (g_poseHook) g_poseHook(model, out, g_poseHookContext);
}

void NodeWorlds(const Model& model, const ModelAnimation* animation, float time, std::vector<gta2::Mat4>* out) {
    NodeWorldsBlend(model, animation, time, nullptr, 0.0f, 0.0f, out);
}

// The matrices a skin's joints apply this pose: inverse bind, then the joint's
// world (row vectors, so inverseBind * world).
void SkinMatrices(const Model& model, const ModelSkin& skin, const std::vector<gta2::Mat4>& worlds,
                  std::vector<gta2::Mat4>* out) {
    out->resize(skin.joints.size());
    for (size_t j = 0; j < skin.joints.size(); ++j) {
        const int node = skin.joints[j];
        if (node < 0 || node >= static_cast<int>(worlds.size())) { (*out)[j] = gta2::Identity(); continue; }
        (*out)[j] = Multiply(skin.inverseBind[j], worlds[node]);
    }
}

// Poses a skinned mesh on the CPU: every vertex blended by its four joints. Built for
// SSE2 under GCC (the rest of the DLL is plain i686 x87 code): the inner loop is the
// pedestrians' largest cost, 1.3 ms per new pose of a 13k-vertex avatar (PERF-2).
#if defined(__GNUC__) && !defined(__clang__)
__attribute__((target("sse2"), optimize("O3")))
#endif
void SkinMesh(const ModelMesh& mesh, const std::vector<gta2::Mat4>& joints, std::vector<ModelVertex>* out) {
    out->resize(mesh.vertices.size());
    for (size_t i = 0; i < mesh.vertices.size(); ++i) {
        const ModelVertex& v = mesh.vertices[i];
        const ModelSkinWeight& w = mesh.weights[i];
        float px = 0, py = 0, pz = 0, nx = 0, ny = 0, nz = 0;
        for (int k = 0; k < 4; ++k) {
            const float wk = w.weight[k];
            if (wk <= 0.0f || w.joint[k] >= joints.size()) continue;
            const gta2::Mat4& m = joints[w.joint[k]];
            px += wk * (v.x * m.m[0][0] + v.y * m.m[1][0] + v.z * m.m[2][0] + m.m[3][0]);
            py += wk * (v.x * m.m[0][1] + v.y * m.m[1][1] + v.z * m.m[2][1] + m.m[3][1]);
            pz += wk * (v.x * m.m[0][2] + v.y * m.m[1][2] + v.z * m.m[2][2] + m.m[3][2]);
            nx += wk * (v.nx * m.m[0][0] + v.ny * m.m[1][0] + v.nz * m.m[2][0]);
            ny += wk * (v.nx * m.m[0][1] + v.ny * m.m[1][1] + v.nz * m.m[2][1]);
            nz += wk * (v.nx * m.m[0][2] + v.ny * m.m[1][2] + v.nz * m.m[2][2]);
        }
        const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len > 1e-6f) { nx /= len; ny /= len; nz /= len; }
        (*out)[i] = {px, py, pz, nx, ny, nz, v.u, v.v};
    }
}

void ComputeBounds(Model* model) {
    std::vector<gta2::Mat4> worlds;
    NodeWorlds(*model, nullptr, 0.0f, &worlds);
    for (size_t i = 0; i < model->nodes.size(); ++i) {
        const int mi = model->nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model->meshes.size())) continue;
        const ModelMesh& mesh = model->meshes[mi];
        std::vector<ModelVertex> posed;
        if (mesh.skin >= 0) {
            std::vector<gta2::Mat4> joints;
            SkinMatrices(*model, model->skins[mesh.skin], worlds, &joints);
            SkinMesh(mesh, joints, &posed);
        }
        // A skinned mesh's vertices are in the skeleton's space, not its node's.
        const gta2::Mat4 w = mesh.skin >= 0 ? gta2::Identity() : worlds[i];
        for (const ModelVertex& v : (mesh.skin >= 0 ? posed : mesh.vertices)) {
            const float x = v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0];
            const float y = v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1];
            const float z = v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2];
            model->boundsMin = {(std::min)(model->boundsMin.x, x), (std::min)(model->boundsMin.y, y), (std::min)(model->boundsMin.z, z)};
            model->boundsMax = {(std::max)(model->boundsMax.x, x), (std::max)(model->boundsMax.y, y), (std::max)(model->boundsMax.z, z)};
        }
    }
    // Which way is forward: the front wheels, if the nodes are named so.
    float front = 0.0f, back = 0.0f;
    int nf = 0, nb = 0;
    for (size_t i = 0; i < model->nodes.size(); ++i) {
        const char* name = model->nodes[i].name;
        if (strstr(name, "front")) { front += worlds[i].m[3][2]; ++nf; }
        if (strstr(name, "back") || strstr(name, "rear")) { back += worlds[i].m[3][2]; ++nb; }
    }
    if (nf && nb) model->forward = (front / nf) >= (back / nb) ? 1.0f : -1.0f;
}

// A manifest field, the cheap way: the file is small and written by our own
// importer, so the values are looked up by key without a JSON parser.
std::string Field(const std::string& text, const char* key) {
    const std::string k = std::string("\"") + key + "\"";
    size_t at = text.find(k);
    if (at == std::string::npos) return "";
    at = text.find(':', at);
    if (at == std::string::npos) return "";
    size_t start = text.find_first_not_of(" \t\n\r", at + 1);
    if (start == std::string::npos) return "";
    if (text[start] == '"') {
        const size_t end = text.find('"', start + 1);
        return end == std::string::npos ? "" : text.substr(start + 1, end - start - 1);
    }
    if (text[start] == '[') {
        const size_t end = text.find(']', start);
        return end == std::string::npos ? "" : text.substr(start, end - start + 1);
    }
    const size_t end = text.find_first_of(",}\n", start);
    return text.substr(start, end - start);
}

std::vector<std::string> Strings(const std::string& list) {
    std::vector<std::string> out;
    size_t at = 0;
    while ((at = list.find('"', at)) != std::string::npos) {
        const size_t end = list.find('"', at + 1);
        if (end == std::string::npos) break;
        out.push_back(list.substr(at + 1, end - at - 1));
        at = end + 1;
    }
    return out;
}

// A car model texture (the image-to-3D cars are named 0NN_...).
bool CarTextureName(const std::string& file) {
    return file.size() > 4 && isdigit(static_cast<unsigned char>(file[0])) && isdigit(static_cast<unsigned char>(file[1])) &&
           isdigit(static_cast<unsigned char>(file[2])) && file[3] == '_';
}

// VEHICLE-ART-2: the parametric car bodies (tools/vehicle_art2/carkit.py) name each texture
// after its surface: "_glass" is drawn blended over the rest (the body's glass meshes come last
// in the file), "_chrome" gets a tight bright highlight, rubber, seals, underbody and the cab's
// trim a dull one. Only car textures (a "NNN_" name); everything else draws as before.
enum CarSurface { kCarSurfDefault = 0, kCarSurfGlass, kCarSurfChrome, kCarSurfMatte };
int CarSurfaceFor(const std::string& file) {
    if (!CarTextureName(file)) return kCarSurfDefault;
    if (file.find("_glass") != std::string::npos) return kCarSurfGlass;
    if (file.find("_chrome") != std::string::npos) return kCarSurfChrome;
    if (file.find("_tyre") != std::string::npos || file.find("_seal") != std::string::npos ||
        file.find("_underbody") != std::string::npos || file.find("_interior") != std::string::npos ||
        file.find("_seat") != std::string::npos || file.find("_whitewall") != std::string::npos ||
        file.find("_rubber") != std::string::npos)
        return kCarSurfMatte;
    return kCarSurfDefault;
}

bool SoftPaintCaps(IDirect3DDevice9* device) {
    if (g_softPaintCaps < 0) {
        D3DCAPS9 caps = {};
        const bool ok = SUCCEEDED(device->GetDeviceCaps(&caps)) && (caps.PrimitiveMiscCaps & D3DPMISCCAPS_TSSARGTEMP) &&
                        (caps.TextureOpCaps & D3DTEXOPCAPS_LERP) && caps.MaxTextureBlendStages >= 3;
        g_softPaintCaps = ok ? 1 : 0;
        Log("models: soft car paint masks %s (setting %d, Remix %d, TEMP %d, LERP %d, stages %lu)",
            ok && g_softPaintSetting && !RemixApiAvailable() ? "on" : "off", g_softPaintSetting ? 1 : 0, RemixApiAvailable() ? 1 : 0,
            (caps.PrimitiveMiscCaps & D3DPMISCCAPS_TSSARGTEMP) ? 1 : 0, (caps.TextureOpCaps & D3DTEXOPCAPS_LERP) ? 1 : 0,
            static_cast<unsigned long>(caps.MaxTextureBlendStages));
    }
    return g_softPaintCaps == 1;
}

inline float SmoothStep(float a, float b, float x) {
    float t = (x - a) / (b - a);
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    return t * t * (3.0f - 2.0f * t);
}

// Rewrites the alpha of a BGRA "_paint" picture (binary paint mask) as a soft coverage:
// the texels whose chromaticity is near the mask's own median paint chroma (or, for a
// coloured paint, lie along the same hue direction: its pale highlights and dark
// shadows) join it, weighted by brightness (chroma is noise in the near-black), and the
// result is blurred twice with a 3x3 box. tools/ prototype: docs/car-3d-pipeline.md.
void SoftenPaintMask(uint8_t* px, int w, int h) {
    const size_t n = static_cast<size_t>(w) * h;
    std::vector<float> cr, cg, cb, sat;
    cr.reserve(n / 4); cg.reserve(n / 4); cb.reserve(n / 4); sat.reserve(n / 4);
    for (size_t i = 0; i < n; ++i) {
        const uint8_t* p = px + i * 4;
        if (p[3] < 128) continue;
        const float b = p[0], g = p[1], r = p[2], s = r + g + b + 1.0f;
        const float mx = (std::max)(r, (std::max)(g, b)), mn = (std::min)(r, (std::min)(g, b));
        cr.push_back(r / s); cg.push_back(g / s); cb.push_back(b / s);
        sat.push_back((mx - mn) / (std::max)(mx, 1.0f));
    }
    if (cr.size() < 64) return;
    auto median = [](std::vector<float>& v) { std::nth_element(v.begin(), v.begin() + v.size() / 2, v.end()); return v[v.size() / 2]; };
    const float ref[3] = {median(cr), median(cg), median(cb)};
    const bool coloured = median(sat) >= 0.2f;
    const float third = 1.0f / 3.0f;
    const float v[3] = {ref[0] - third, ref[1] - third, ref[2] - third};
    const float vv = (std::max)(1e-6f, v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    std::vector<float> m(n), t(n);
    for (size_t i = 0; i < n; ++i) {
        const uint8_t* p = px + i * 4;
        const float b = p[0], g = p[1], r = p[2], s = r + g + b + 1.0f;
        const float c[3] = {r / s, g / s, b / s};
        const float mx = (std::max)(r, (std::max)(g, b));
        const float d = std::fabs(c[0] - ref[0]) + std::fabs(c[1] - ref[1]) + std::fabs(c[2] - ref[2]);
        float wc = 1.0f - SmoothStep(0.06f, 0.14f, d);
        float wl;
        if (coloured) {
            const float k = ((c[0] - third) * v[0] + (c[1] - third) * v[1] + (c[2] - third) * v[2]) / vv;
            const float perp = std::fabs(c[0] - third - k * v[0]) + std::fabs(c[1] - third - k * v[1]) + std::fabs(c[2] - third - k * v[2]);
            wc = (std::max)(wc, SmoothStep(0.1f, 0.55f, k) * (1.0f - SmoothStep(0.03f, 0.07f, perp)));
            wl = SmoothStep(25.0f, 55.0f, mx);
        } else {
            wl = SmoothStep(55.0f, 105.0f, mx);
        }
        m[i] = (std::max)(p[3] >= 128 ? 1.0f : 0.0f, wc * wl);
    }
    for (int pass = 0; pass < 2; ++pass) {
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x) {
                const size_t row = static_cast<size_t>(y) * w;
                t[row + x] = (m[row + (std::max)(0, x - 1)] + m[row + x] + m[row + (std::min)(w - 1, x + 1)]) * third;
            }
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x)
                m[static_cast<size_t>(y) * w + x] = (t[static_cast<size_t>((std::max)(0, y - 1)) * w + x] + t[static_cast<size_t>(y) * w + x] +
                                                    t[static_cast<size_t>((std::min)(h - 1, y + 1)) * w + x]) * third;
    }
    for (size_t i = 0; i < n; ++i) px[i * 4 + 3] = static_cast<uint8_t>((std::min)(255.0f, m[i] * 255.0f + 0.5f));
}

double g_texNewMs = 0.0;
int g_texNew = 0;
bool g_modelGhost = false;   // FIX-PERF-VSWITCH: ModelsGhostDraws is drawing (no logs, no stats)
IDirect3DTexture9* BaseTextureForImpl(IDirect3DDevice9* device, const std::string& file);
IDirect3DTexture9* BaseTextureFor(IDirect3DDevice9* device, const std::string& file) {
    if (file.empty()) return nullptr;
    auto it = g_textures.find(file);
    if (it != g_textures.end()) return it->second;
    LARGE_INTEGER a, b;
    QueryPerformanceCounter(&a);
    IDirect3DTexture9* t = BaseTextureForImpl(device, file);
    QueryPerformanceCounter(&b);
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    g_texNewMs += 1000.0 * static_cast<double>(b.QuadPart - a.QuadPart) / static_cast<double>(f.QuadPart);
    ++g_texNew;
    return t;
}
IDirect3DTexture9* BaseTextureForImpl(IDirect3DDevice9* device, const std::string& file) {
    IDirect3DTexture9* texture = nullptr;
    std::vector<uint8_t> tga;
    bool softened = false;
    if (!TakePrefetched(file, &tga, &softened)) { tga.clear(); softened = false; }
    const bool softWanted = g_softPaintSetting && !RemixApiAvailable() && file.size() > 10 &&
                            file.compare(file.size() - 10, 10, "_paint.tga") == 0 && CarTextureName(file) && SoftPaintCaps(device);
    if (softened && !softWanted) { tga.clear(); softened = false; }   // the reader's guess no longer holds: the file as it is
    if ((!tga.empty() || ReadAll(g_folder + "\\" + file, &tga)) && tga.size() > 18 && tga[2] == 2 && tga[16] == 32) {
        const int w = tga[12] | (tga[13] << 8), h = tga[14] | (tga[15] << 8);
        const bool topDown = (tga[17] & 0x20) != 0;
        if (w > 0 && h > 0 && tga.size() >= 18u + static_cast<size_t>(w) * h * 4 && softWanted) {
            if (!softened) SoftenPaintMask(&tga[18], w, h);
            g_softPaintTex.insert(file);
        }
        if (w > 0 && h > 0 && tga.size() >= 18u + static_cast<size_t>(w) * h * 4 &&
            SUCCEEDED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) {
            g_textureBytes += static_cast<size_t>(w) * h * 4;
            FrameLogNote(kFcModelTexture);
            D3DLOCKED_RECT lr;
            if (SUCCEEDED(texture->LockRect(0, &lr, nullptr, 0))) {
                for (int y = 0; y < h; ++y) {
                    const int src = topDown ? y : (h - 1 - y);
                    memcpy(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch, &tga[18 + static_cast<size_t>(src) * w * 4], w * 4);
                }
                texture->UnlockRect(0);
            }
        }
    }
    if (!texture) Log("models: texture %s could not be read", file.c_str());
    g_textures[file] = texture;
    return texture;
}

// REMIX-3D-QUALITY: the player's own figure in first person under Remix.
//
// From his own eyes he is not drawn (fpHideOwnBody), so under Remix he cast no
// shadow and had no reflection, where in the classic view his sprite does. Remix
// has the mechanism: an instance whose texture is in rtx.playerModelTextures gets
// the player-model ray mask - not seen by primary rays (rtx.playerModel.
// enableInPrimarySpace, off by default) but in shadows (enablePrimaryShadows, on).
// His avatar is also many civilians' avatar, so tagging its textures would hide
// them too: while the flag below is on, every model texture is swapped for a copy
// that differs in one bit of the first texel (invisible, but another hash), and
// the copies' hashes are what is tagged. The hash is Remix's own: XXH3_64bits of
// mip 0's bytes (dxvk-remix d3d9_common_texture.cpp), packed rows as uploaded.
bool g_playerTextures = false;
std::map<std::string, IDirect3DTexture9*> g_playerCopies;
std::vector<uint64_t> g_playerHashes;

void PushPlayerHashes() {
    std::string list;
    char one[24];
    for (uint64_t h : g_playerHashes) {
        snprintf(one, sizeof(one), "0x%016llX", static_cast<unsigned long long>(h));
        if (!list.empty()) list += ", ";
        list += one;
    }
    const bool ok = RemixSetConfig("rtx.playerModelTextures", list.c_str());
    Log("remix: own figure: %zu player-model texture%s tagged (%s), last %s", g_playerHashes.size(),
        g_playerHashes.size() == 1 ? "" : "s", ok ? "taken" : "REFUSED", one);
}

IDirect3DTexture9* PlayerCopyFor(IDirect3DDevice9* device, const std::string& file, IDirect3DTexture9* base) {
    auto it = g_playerCopies.find(file);
    if (it != g_playerCopies.end()) return it->second;
    IDirect3DTexture9* copy = nullptr;
    D3DSURFACE_DESC desc;
    if (base && SUCCEEDED(base->GetLevelDesc(0, &desc)) && desc.Format == D3DFMT_A8R8G8B8 &&
        SUCCEEDED(device->CreateTexture(desc.Width, desc.Height, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &copy, nullptr))) {
        const size_t row = static_cast<size_t>(desc.Width) * 4;
        std::vector<uint8_t> pixels(row * desc.Height);
        D3DLOCKED_RECT src, dst;
        bool done = false;
        if (SUCCEEDED(base->LockRect(0, &src, nullptr, D3DLOCK_READONLY))) {
            for (UINT y = 0; y < desc.Height; ++y)
                memcpy(&pixels[y * row], static_cast<const uint8_t*>(src.pBits) + y * src.Pitch, row);
            base->UnlockRect(0);
            pixels[0] ^= 1u;   // blue's lowest bit of the first texel
            if (SUCCEEDED(copy->LockRect(0, &dst, nullptr, 0))) {
                for (UINT y = 0; y < desc.Height; ++y)
                    memcpy(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch, &pixels[y * row], row);
                copy->UnlockRect(0);
                done = true;
            }
        }
        if (done) {
            g_playerHashes.push_back(XXH3_64bits(pixels.data(), pixels.size()));
            {
                // Other ways the runtime could key this texture, logged for a QA check that tries
                // each under rtx.hideInstanceTextures (REMIX-3D-QUALITY, r3dq_7): XXH64, rows
                // bottom-up, red and blue swapped, and the empty texture (hashed before the fill).
                std::vector<uint8_t> alt(pixels.size());
                for (UINT y = 0; y < desc.Height; ++y) memcpy(&alt[y * row], &pixels[(desc.Height - 1 - y) * row], row);
                const uint64_t flipped = XXH3_64bits(alt.data(), alt.size());
                for (size_t k = 0; k + 3 < pixels.size(); k += 4) {
                    alt[k] = pixels[k + 2]; alt[k + 1] = pixels[k + 1]; alt[k + 2] = pixels[k]; alt[k + 3] = pixels[k + 3];
                }
                const uint64_t swapped = XXH3_64bits(alt.data(), alt.size());
                std::fill(alt.begin(), alt.end(), 0);
                const uint64_t empty = XXH3_64bits(alt.data(), alt.size());
                Log("remix: own figure hash candidates %s %ux%u: xxh3 0x%016llX xxh64 0x%016llX flipped 0x%016llX swapped 0x%016llX empty 0x%016llX",
                    file.c_str(), desc.Width, desc.Height, static_cast<unsigned long long>(g_playerHashes.back()),
                    static_cast<unsigned long long>(XXH64(pixels.data(), pixels.size(), 0)), static_cast<unsigned long long>(flipped),
                    static_cast<unsigned long long>(swapped), static_cast<unsigned long long>(empty));
            }
            PushPlayerHashes();
        } else {
            copy->Release();
            copy = nullptr;
        }
    }
    if (!copy) Log("remix: own figure: no player copy of %s (drawn with the shared texture)", file.c_str());
    g_playerCopies[file] = copy ? copy : base;
    if (copy) g_textureBytes += static_cast<size_t>(desc.Width) * desc.Height * 4;
    return g_playerCopies[file];
}

IDirect3DTexture9* TextureFor(IDirect3DDevice9* device, const std::string& file) {
    IDirect3DTexture9* base = BaseTextureFor(device, file);
    if (!g_playerTextures || !base) return base;
    return PlayerCopyFor(device, file, base);
}

}  // namespace

const Model::Loco* Model::LocoFor(const char* name) const {
    for (const Loco& l : loco) if (l.name == name) return &l;
    return nullptr;
}

float Model::Loco::PhaseAt(float t) const {
    if (phase.empty()) return 0.0f;
    const float x = (std::max)(0.0f, t * 15.0f);
    const size_t i = (std::min)(static_cast<size_t>(x), phase.size() - 1);
    const size_t j = (std::min)(i + 1, phase.size() - 1);
    const float f = (std::min)(1.0f, x - static_cast<float>(i));
    float a = phase[i], b = phase[j];
    if (b - a > 0.5f) b -= 1.0f;
    if (a - b > 0.5f) b += 1.0f;
    float p = a + (b - a) * f;
    return p - std::floor(p);
}

float Model::Loco::TimeAtDist(float d) const {
    for (size_t i = 1; i < dist.size(); ++i) {
        if (dist[i] >= d) {
            const float span = dist[i] - dist[i - 1];
            const float f = span > 1e-6f ? (d - dist[i - 1]) / span : 1.0f;
            return (static_cast<float>(i - 1) + (std::max)(0.0f, (std::min)(1.0f, f))) / 15.0f;
        }
    }
    return Length();
}

const ModelAnimation* Model::Animation(const char* name) const {
    for (const ModelAnimation& a : animations) if (a.name == name) return &a;
    return nullptr;
}

void StartTexturePrefetch();
void MergeProps();

void ModelsLoad(const char* folder) {
    if (g_loaded) return;
    g_loaded = true;
    g_folder = folder;
    std::vector<uint8_t> raw;
    if (!ReadAll(g_folder + "\\manifest.json", &raw)) {
        Log("models: no %s\\manifest.json; cars and pedestrians keep the game's own look", folder);
        return;
    }
    const std::string text(raw.begin(), raw.end());
    // Every "name" in the models list.
    size_t at = text.find("\"models\"");
    // The list ends where the next top-level key begins (entries hold lists of
    // their own, so the first ']' is not it).
    size_t listEnd = std::string::npos;
    for (const char* key : {"\"cars\"", "\"pedestrian\"", "\"props\"", "\"imported\""}) {
        const size_t k = at == std::string::npos ? std::string::npos : text.find(key, at);
        if (k != std::string::npos && k < listEnd) listEnd = k;
    }
    while (at != std::string::npos && (at = text.find("\"name\"", at)) != std::string::npos && at < listEnd) {
        const std::string name = Field(text.substr(at), "name");
        at += 6;
        if (name.empty() || g_byName.count(name)) continue;
        Model model;
        model.name = name;
        if (!LoadModel(g_folder + "\\" + name + ".mesh", &model)) {
            Log("models: %s.mesh could not be read", name.c_str());
            continue;
        }
        ComputeBounds(&model);
        for (const ModelMesh& mesh : model.meshes) {
            const size_t k = mesh.texture.find("_paint");
            if (k == std::string::npos) continue;
            model.splitPaint = true;
            g_paintRests.insert(mesh.texture.substr(0, k) + mesh.texture.substr(k + 6));
        }
        g_byName[name] = g_models.size();
        g_models.push_back(std::move(model));
        const Model& m = g_models.back();
        g_known.insert(&m);
        Log("models: %s: %zu nodes, %zu meshes, %zu animations, %.2f x %.2f x %.2f blocks, faces %s",
            m.name.c_str(), m.nodes.size(), m.meshes.size(), m.animations.size(), m.Width(), m.Height(), m.Length(),
            m.forward > 0 ? "+z" : "-z");
    }
    // The importer's flat report says which way each model faces, when the
    // manifest said so: "imported": [{"name": ..., "forward": "+z"}, ...].
    size_t rep = text.find("\"imported\"");
    while (rep != std::string::npos && (rep = text.find("\"name\"", rep)) != std::string::npos) {
        const size_t next = text.find("\"name\"", rep + 6);
        const std::string entry = text.substr(rep, next == std::string::npos ? std::string::npos : next - rep);
        const std::string name = Field(entry, "name");
        const std::string forward = Field(entry, "forward");
        auto it = g_byName.find(name);
        if (it != g_byName.end() && (forward == "+z" || forward == "-z")) g_models[it->second].forward = forward == "+z" ? 1.0f : -1.0f;
        const std::string stride = Field(entry, "stride");
        if (it != g_byName.end() && !stride.empty()) g_models[it->second].stride = static_cast<float>(atof(stride.c_str()));
        const std::string runStride = Field(entry, "run_stride");
        if (it != g_byName.end() && !runStride.empty()) g_models[it->second].runStride = static_cast<float>(atof(runStride.c_str()));
        // "loco": "name:d,d,...:ph,ph,...;name:..." (tools/locomotion_meta.py)
        const std::string loco = it != g_byName.end() ? Field(entry, "loco") : std::string();
        for (size_t s0 = 0; s0 < loco.size();) {
            size_t s1 = loco.find(';', s0);
            if (s1 == std::string::npos) s1 = loco.size();
            const std::string one = loco.substr(s0, s1 - s0);
            s0 = s1 + 1;
            const size_t c1 = one.find(':'), c2 = c1 == std::string::npos ? c1 : one.find(':', c1 + 1);
            if (c2 == std::string::npos) continue;
            Model::Loco l;
            l.name = one.substr(0, c1);
            auto floats = [](const std::string& list, std::vector<float>* out) {
                for (size_t a = 0; a < list.size();) {
                    size_t b = list.find(',', a);
                    if (b == std::string::npos) b = list.size();
                    if (b > a) out->push_back(static_cast<float>(atof(list.substr(a, b - a).c_str())));
                    a = b + 1;
                }
            };
            floats(one.substr(c1 + 1, c2 - c1 - 1), &l.dist);
            floats(one.substr(c2 + 1), &l.phase);
            if (l.dist.size() >= 2) g_models[it->second].loco.push_back(std::move(l));
        }
        // ASSET-PEDS: "ped_zones": 1, "zone_ref": 128, "zone_rgb_t"/"_b"/"_h": [r, g, b] (or null)
        if (it != g_byName.end() && Field(entry, "ped_zones") == "1") {
            Model& zm = g_models[it->second];
            zm.pedZones = true;
            const std::string ref = Field(entry, "zone_ref");
            if (!ref.empty()) zm.zoneRef = (std::max)(8.0f, static_cast<float>(atof(ref.c_str())));
            const char* keys[3] = {"\"zone_rgb_t\"", "\"zone_rgb_b\"", "\"zone_rgb_h\""};
            for (int z = 0; z < 3; ++z) {
                const size_t kz = entry.find(keys[z]);
                if (kz == std::string::npos) continue;
                const size_t colon = entry.find(':', kz);
                const size_t open = colon == std::string::npos ? colon : entry.find_first_not_of(" \t\r\n", colon + 1);
                if (open == std::string::npos || entry[open] != '[') continue;   // null: unknown
                float v[3] = {0, 0, 0};
                if (sscanf(entry.c_str() + open, "[%f,%f,%f", &v[0], &v[1], &v[2]) == 3 ||
                    sscanf(entry.c_str() + open, "[ %f , %f , %f", &v[0], &v[1], &v[2]) == 3)
                    for (int k = 0; k < 3; ++k) zm.zoneRgb[z][k] = v[k];
            }
        }
        // "paint_rgb": [r, g, b]
        const size_t paint = entry.find("\"paint_rgb\"");
        if (it != g_byName.end() && paint != std::string::npos) {
            const size_t open = entry.find('[', paint);
            if (open != std::string::npos) {
                float rgb[3] = {235.0f, 235.0f, 235.0f};
                if (sscanf(entry.c_str() + open, "[%f,%f,%f", &rgb[0], &rgb[1], &rgb[2]) == 3 ||
                    sscanf(entry.c_str() + open, "[ %f , %f , %f", &rgb[0], &rgb[1], &rgb[2]) == 3) {
                    for (int k = 0; k < 3; ++k) g_models[it->second].paintRgb[k] = (std::max)(8.0f, (std::min)(255.0f, rgb[k]));
                }
            }
        }
        rep += 6;
    }
    const size_t cars = text.find("\"cars\"");
    if (cars != std::string::npos) {
        const std::string block = text.substr(cars, text.find('}', cars) - cars + 1);
        g_carDefault = Strings(Field(block, "default"));
        // "cars": {"by_model": {"12": "taxi", ...}, "by_sprite": {"45": "taxi", ...}}
        const std::string rest = text.substr(cars);
        g_carByModel = NumberMap(rest, "by_model");
        g_carBySprite = NumberMap(rest, "by_sprite");
        for (auto it = g_carByModel.begin(); it != g_carByModel.end();) {
            if (!g_byName.count(it->second)) { Log("models: cars.by_model %d names '%s', which is not loaded", it->first, it->second.c_str()); it = g_carByModel.erase(it); }
            else ++it;
        }
        for (auto it = g_carBySprite.begin(); it != g_carBySprite.end();) {
            if (!g_byName.count(it->second)) { Log("models: cars.by_sprite %d names '%s', which is not loaded", it->first, it->second.c_str()); it = g_carBySprite.erase(it); }
            else ++it;
        }
        Log("models: cars mapped for %zu model numbers and %zu sprites", g_carByModel.size(), g_carBySprite.size());
    }
    g_pedestrian = Field(text, "pedestrian");
    for (const std::string& name : Strings(Field(text, "pedestrians")))
        if (g_byName.count(name)) g_pedestrians.push_back(name);
    if (g_pedestrians.empty() && g_byName.count(g_pedestrian)) g_pedestrians.push_back(g_pedestrian);
    // "ped_types": [{"name": "police", "remaps": [0, 1, 2, 3], "models": ["..."], "tint": 0}, ...]
    for (int i = 0; i < 64; ++i) { g_pedTypeByRemap[i] = -1; g_pedRemapColour[i][0] = g_pedRemapColour[i][1] = g_pedRemapColour[i][2] = 0.0f; }
    g_pedTypes.clear();
    {
        const size_t key = text.find("\"ped_types\"");
        size_t at = key == std::string::npos ? std::string::npos : text.find('[', key);
        while (at != std::string::npos) {
            const size_t open = text.find('{', at);
            const size_t closeList = text.find(']', at);
            if (open == std::string::npos || (closeList != std::string::npos && closeList < open)) break;
            const size_t close = text.find('}', open);
            if (close == std::string::npos) break;
            const std::string entry = text.substr(open, close - open + 1);
            PedType type;
            type.name = Field(entry, "name");
            type.tint = Field(entry, "tint") == "1" || Field(entry, "tint") == "true";
            if (!Field(entry, "scale").empty()) type.scale = (std::max)(0.5f, (std::min)(2.0f, static_cast<float>(atof(Field(entry, "scale").c_str()))));
            if (!Field(entry, "width").empty()) type.width = (std::max)(0.5f, (std::min)(2.0f, static_cast<float>(atof(Field(entry, "width").c_str()))));
            for (const std::string& name : Strings(Field(entry, "models")))
                if (g_byName.count(name)) type.models.push_back(name);
                else Log("models: ped type '%s' names '%s', which is not loaded", type.name.c_str(), name.c_str());
            const std::string remaps = Field(entry, "remaps");
            for (size_t i = 0; i < remaps.size();) {
                if (remaps[i] < '0' || remaps[i] > '9') { ++i; continue; }
                const int r = atoi(remaps.c_str() + i);
                while (i < remaps.size() && remaps[i] >= '0' && remaps[i] <= '9') ++i;
                if (r >= 0 && r < 64) { type.remaps.push_back(r); if (!type.models.empty()) g_pedTypeByRemap[r] = static_cast<int>(g_pedTypes.size()); }
            }
            g_pedTypes.push_back(type);
            at = close + 1;
            const size_t next = text.find_first_not_of(" \t\r\n,", at);
            if (next == std::string::npos || text[next] == ']') break;
        }
    }
    // FIX-AVATAR-IDENTITY: the protagonist's avatar ("pedestrian") is his alone. A manifest that
    // also deals it to the crowd (the plain list, a civilian type) put his face, hair and build on
    // passers-by and, when his own figure ever fell to a pick, someone else's clothes on him.
    // Kept out of every pick but his own type's (and a list that would be left empty).
    if (g_byName.count(g_pedestrian)) {
        int dropped = 0;
        auto drop = [&](std::vector<std::string>& list) {
            if (list.size() < 2) return;
            const size_t before = list.size();
            list.erase(std::remove(list.begin(), list.end(), g_pedestrian), list.end());
            dropped += static_cast<int>(before - list.size());
        };
        drop(g_pedestrians);
        for (PedType& type : g_pedTypes)
            if (std::find(type.remaps.begin(), type.remaps.end(), 25) == type.remaps.end()) drop(type.models);
        Log("models: player avatar '%s' (remap 25), kept out of %d crowd picks", g_pedestrian.c_str(), dropped);
    }
    // "ped_remap_colours": [[r, g, b], ...] by remap: the sprite's clothing colour.
    {
        const size_t key = text.find("\"ped_remap_colours\"");
        if (key != std::string::npos) {
            size_t at = text.find('[', key);
            int remap = 0;
            while (at != std::string::npos && remap < 64) {
                const size_t open = text.find('[', at + 1);
                if (open == std::string::npos) break;
                const size_t close = text.find(']', open);
                if (close == std::string::npos) break;
                const std::string triple = text.substr(open + 1, close - open - 1);
                float v[3] = {0, 0, 0};
                if (sscanf(triple.c_str(), "%f , %f , %f", &v[0], &v[1], &v[2]) == 3 || sscanf(triple.c_str(), "%f,%f,%f", &v[0], &v[1], &v[2]) == 3)
                    for (int k = 0; k < 3; ++k) g_pedRemapColour[remap][k] = v[k];
                ++remap;
                at = close;
                const size_t next = text.find_first_not_of(" \t\r\n,", at + 1);
                if (next == std::string::npos || text[next] == ']') break;
            }
        }
    }
    // ASSET-PEDS: "ped_outfits": [[top r g b, bottom r g b, hair r g b], ...] by remap
    // (tools/make_ped_manifest.py, from the sprite palettes); zeros keep the avatar's.
    for (int i = 0; i < 64; ++i) for (int k = 0; k < 9; ++k) g_pedOutfit[i][k] = 0.0f;
    {
        const size_t key = text.find("\"ped_outfits\"");
        int remap = 0;
        size_t at = key == std::string::npos ? std::string::npos : text.find('[', key);
        while (at != std::string::npos && remap < 64) {
            const size_t open = text.find('[', at + 1);
            if (open == std::string::npos) break;
            const size_t close = text.find(']', open);
            if (close == std::string::npos) break;
            const std::string row = text.substr(open + 1, close - open - 1);
            int k = 0;
            for (size_t p = 0; p < row.size() && k < 9;) {
                const size_t q = row.find(',', p);
                const std::string num = row.substr(p, q == std::string::npos ? std::string::npos : q - p);
                g_pedOutfit[remap][k++] = static_cast<float>(atof(num.c_str()));
                if (q == std::string::npos) break;
                p = q + 1;
            }
            ++remap;
            at = close;
            const size_t next = text.find_first_not_of(" \t\r\n,", at + 1);
            if (next == std::string::npos || text[next] == ']') break;
        }
        if (remap) Log("models: %d pedestrian outfits (ASSET-PEDS zones)", remap);
    }
    if (!g_pedTypes.empty()) {
        int mapped = 0;
        for (int i = 0; i < 64; ++i) if (g_pedTypeByRemap[i] >= 0) ++mapped;
        Log("models: %zu pedestrian types cover %d remaps", g_pedTypes.size(), mapped);
    }
    const size_t props = text.find("\"props\"");
    if (props != std::string::npos) {
        const std::string block = text.substr(props, text.find('}', props) - props + 1);
        // Every "role": "model" pair in the block, whatever the role is called,
        // so a new prop (the park trees' tree1..tree3, say) needs no change here.
        size_t at = block.find('{');
        while (at != std::string::npos) {
            const size_t q1 = block.find('"', at + 1);
            if (q1 == std::string::npos) break;
            const size_t q2 = block.find('"', q1 + 1);
            if (q2 == std::string::npos) break;
            const std::string role = block.substr(q1 + 1, q2 - q1 - 1);
            const size_t colon = block.find(':', q2);
            if (colon == std::string::npos) break;
            const size_t v1 = block.find('"', colon);
            if (v1 == std::string::npos) break;
            const size_t v2 = block.find('"', v1 + 1);
            if (v2 == std::string::npos) break;
            const std::string name = block.substr(v1 + 1, v2 - v1 - 1);
            if (!role.empty() && !name.empty()) g_props[role] = name;
            at = block.find(',', v2);
        }
    }
    Log("models: %zu loaded, %zu car models, pedestrian '%s' (%zu pedestrian models)", g_models.size(),
        g_carDefault.size(), g_pedestrian.c_str(), g_pedestrians.size());
    MergeProps();
    StartTexturePrefetch();
}

bool ModelsAvailable() { return !g_models.empty(); }
bool ModelIsKnown(const Model* model) { return model && g_known.count(model) != 0; }
void ModelRestNodeWorlds(const Model& model, std::vector<gta2::Mat4>* out) { NodeWorlds(model, nullptr, 0.0f, out); }
const Model* ModelRegisterDerived(Model&& model, bool dynamicBuffers) {
    g_models.push_back(std::move(model));
    const Model& m = g_models.back();
    g_known.insert(&m);
    if (dynamicBuffers) for (const ModelMesh& mesh : m.meshes) g_dynamicMeshes.insert(&mesh);
    return &m;
}

const Model* ModelForCar(int sprite) {
    // Only a model the manifest names for this very sprite: anything else is
    // built from the game's own artwork (car_bodies.cpp), which keeps every
    // car the car it is. The manifest's default list is no longer used.
    auto by = g_carBySprite.find(sprite);
    if (by == g_carBySprite.end()) return nullptr;
    auto it = g_byName.find(by->second);
    return it == g_byName.end() ? nullptr : &g_models[it->second];
}

const Model* ModelForVehicle(int modelNumber, int sprite) {
    auto by = g_carByModel.find(modelNumber);
    if (by != g_carByModel.end()) {
        auto it = g_byName.find(by->second);
        if (it != g_byName.end()) return &g_models[it->second];
    }
    return ModelForCar(sprite);
}

size_t ModelsTextureBytes(int* count) {
    if (count) *count = static_cast<int>(g_textures.size());
    return g_textureBytes;
}

// The torso twist for the next poses: radians about the model's up axis at
// "Bip01 Spine1", so a figure's upper body can face one way (the aim) while
// its legs walk another. Part of the pose cache key (quantised by the caller).
void ModelSetTorsoTwist(float radians) { g_torsoTwist = radians; }
void ModelSetPoseHook(ModelPoseHookFn fn, void* context, uint64_t key) {
    g_poseHook = fn;
    g_poseHookContext = context;
    g_poseHookKey = fn ? key : 0;
}
void ModelPoseWorlds(const Model& model, const ModelAnimation* animation, float time, const ModelAnimation* second,
                     float secondTime, float weight, std::vector<gta2::Mat4>* out) {
    const ModelPoseHookFn hook = g_poseHook;
    g_poseHook = nullptr;
    NodeWorldsBlend(model, animation, time, second, secondTime, weight, out);
    g_poseHook = hook;
}
void ModelSetOverlay(const ModelAnimation* clip, float time, float weight) {
    if (!clip || weight <= 1e-3f) { g_overlay = nullptr; g_overlayTime = 0.0f; g_overlayWeight = 0.0f; return; }
    g_overlay = clip; g_overlayTime = time; g_overlayWeight = weight;
}
void ModelSetLayers(const Model* model, const ModelAnimation* const* clips, const float* times, const float* weights, int count) {
    g_layerModel = nullptr; g_layerCount = 0;
    if (!model || count <= 0) return;
    for (int k = 0; k < count && g_layerCount < kModelLayers; ++k) {
        if (!clips[k] || weights[k] <= 1e-3f) continue;
        g_layerClip[g_layerCount] = clips[k]; g_layerTime[g_layerCount] = times[k];
        g_layerWeight[g_layerCount] = (std::min)(1.0f, weights[k]); ++g_layerCount;
    }
    if (g_layerCount) g_layerModel = model;
}
float ModelTorsoTwist() { return g_torsoTwist; }
void ModelSetHeadTurn(float radians) { g_headTurn = radians; }
static void LimbIkRekey() {
    uint64_t h = 1469598103934665603ull;
    auto mix = [&](int32_t v) { h ^= static_cast<uint32_t>(v); h *= 1099511628211ull; };
    for (const LimbIk& l : g_limbIk) {
        if (!l.on || l.w <= 1e-3f) { mix(0); continue; }
        mix(1);
        for (int k = 0; k < 3; ++k) mix(static_cast<int32_t>(std::floor(l.t[k] * 400.0f + 0.5f)));
        for (int k = 0; k < 3; ++k) mix(static_cast<int32_t>(std::floor(l.pole[k] * 50.0f + 0.5f)));
        mix(static_cast<int32_t>(std::floor(l.w * 64.0f + 0.5f)));
    }
    g_limbIkKey = h;
}
void ModelSetLimbTarget(int limb, const float* target, const float* pole, float weight) {
    if (limb < 0 || limb > 3) return;
    LimbIk& l = g_limbIk[limb];
    if (!target || weight <= 1e-3f) { l.on = false; l.w = 0.0f; LimbIkRekey(); return; }
    l.on = true; l.w = weight;
    for (int k = 0; k < 3; ++k) { l.t[k] = target[k]; l.pole[k] = pole ? pole[k] : 0.0f; }
    LimbIkRekey();
}
bool ModelLimbResidual(int limb, float out[3]) {
    if (limb < 0 || limb > 3 || !g_limbIk[limb].on) return false;
    for (int k = 0; k < 3; ++k) out[k] = g_limbResidual[limb][k];
    return true;
}
void ModelClearLimbTargets() {
    for (LimbIk& l : g_limbIk) { l.on = false; l.w = 0.0f; }
    g_limbIkKey = 0;
}

void ModelSetZoneTints(const float* top, const float* bottom, const float* hair) {
    g_zoneOn = top != nullptr && bottom != nullptr;
    g_zoneHair = g_zoneOn && hair != nullptr;
    if (!g_zoneOn) return;
    const float* src[3] = {top, bottom, hair};
    for (int z = 0; z < 3; ++z)
        for (int k = 0; k < 3; ++k) g_zoneTint[z][k] = src[z] ? (std::max)(0.0f, (std::min)(2.0f, src[z][k])) : 1.0f;
}

// IDENTITY-SYSTEM: see model_store.h.
bool g_nodeTintOn = false;
char g_nodeTintPrefix[32] = {};
float g_nodeTint[3] = {1.0f, 1.0f, 1.0f};
void ModelSetNodeTint(const char* nodePrefix, const float* rgb) {
    g_nodeTintOn = nodePrefix && *nodePrefix && rgb;
    if (!g_nodeTintOn) return;
    snprintf(g_nodeTintPrefix, sizeof g_nodeTintPrefix, "%s", nodePrefix);
    for (int k = 0; k < 3; ++k) g_nodeTint[k] = (std::max)(0.0f, (std::min)(2.0f, rgb[k]));
}
bool ModelNodeTextureMean(IDirect3DDevice9* device, const Model& model, const char* nodePrefix, float rgb[3]) {
    static std::map<std::string, std::array<float, 4>> s_means;   // texture -> mean rgb, valid
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        if (strncmp(model.nodes[i].name, nodePrefix, strlen(nodePrefix)) != 0) continue;
        const std::string& file = model.meshes[mi].texture;
        auto it = s_means.find(file);
        if (it == s_means.end()) {
            std::array<float, 4> m = {0.0f, 0.0f, 0.0f, 0.0f};
            if (IDirect3DTexture9* tex = TextureFor(device, file)) {
                D3DSURFACE_DESC desc;
                D3DLOCKED_RECT locked;
                if (SUCCEEDED(tex->GetLevelDesc(0, &desc)) && desc.Format == D3DFMT_A8R8G8B8 &&
                    SUCCEEDED(tex->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) {
                    double sum[3] = {0, 0, 0}; double n = 0;
                    for (UINT y = 0; y < desc.Height; ++y) {
                        const uint32_t* row = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(locked.pBits) + y * locked.Pitch);
                        for (UINT x = 0; x < desc.Width; ++x) {
                            if ((row[x] >> 24) < 128) continue;
                            sum[0] += (row[x] >> 16) & 255; sum[1] += (row[x] >> 8) & 255; sum[2] += row[x] & 255; n += 1;
                        }
                    }
                    tex->UnlockRect(0);
                    if (n > 0) m = {static_cast<float>(sum[0] / n), static_cast<float>(sum[1] / n), static_cast<float>(sum[2] / n), 1.0f};
                }
            }
            it = s_means.emplace(file, m).first;
            Log("models: %s node %s texture %s mean %.0f,%.0f,%.0f", model.name.c_str(), nodePrefix, file.c_str(), m[0], m[1], m[2]);
        }
        if (it->second[3] <= 0.0f) return false;
        for (int k = 0; k < 3; ++k) rgb[k] = it->second[k];
        return true;
    }
    return false;
}

// IDENTITY-SYSTEM (docs/identity-system.md 2.4): under RTX Remix a figure's tinted cloth is not
// trusted to the stage-1 texture factor (pt-remix-third-figure-*: grey clay, then torso and legs
// not drawn): the identity record's tint is baked into a copy of the texture, so Remix sees an
// ordinary textured draw whose albedo is the record's colours. Cached by texture and tint (1/64).
bool g_bakeTints = false;
void ModelSetBakeTints(bool on) { g_bakeTints = on; }
IDirect3DTexture9* BakedTint(IDirect3DDevice9* device, const std::string& file, const float tint[3]) {
    struct Key { std::string file; int t[3]; bool operator<(const Key& o) const {
        return std::tie(file, t[0], t[1], t[2]) < std::tie(o.file, o.t[0], o.t[1], o.t[2]); } };
    static std::map<Key, IDirect3DTexture9*> s_baked;
    static IDirect3DDevice9* s_device = nullptr;
    if (s_device != device) { for (auto& b : s_baked) if (b.second) b.second->Release(); s_baked.clear(); s_device = device; }
    Key key{file, {static_cast<int>(std::lround(tint[0] * 64.0f)), static_cast<int>(std::lround(tint[1] * 64.0f)),
                   static_cast<int>(std::lround(tint[2] * 64.0f))}};
    auto it = s_baked.find(key);
    if (it != s_baked.end()) return it->second;
    if (s_baked.size() >= 256) return nullptr;   // the stage-1 factor then, as before
    IDirect3DTexture9* src = TextureFor(device, file);
    IDirect3DTexture9* out = nullptr;
    D3DSURFACE_DESC desc;
    if (src && SUCCEEDED(src->GetLevelDesc(0, &desc)) && desc.Format == D3DFMT_A8R8G8B8 &&
        SUCCEEDED(device->CreateTexture(desc.Width, desc.Height, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &out, nullptr))) {
        D3DLOCKED_RECT a, b;
        if (SUCCEEDED(src->LockRect(0, &a, nullptr, D3DLOCK_READONLY))) {
            if (SUCCEEDED(out->LockRect(0, &b, nullptr, 0))) {
                const float k[3] = {key.t[0] / 64.0f, key.t[1] / 64.0f, key.t[2] / 64.0f};
                for (UINT y = 0; y < desc.Height; ++y) {
                    const uint32_t* r = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(a.pBits) + y * a.Pitch);
                    uint32_t* w = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(b.pBits) + y * b.Pitch);
                    for (UINT x = 0; x < desc.Width; ++x) {
                        const uint32_t c = r[x];
                        const uint32_t cr = (std::min)(255u, static_cast<uint32_t>(((c >> 16) & 255) * k[0] + 0.5f));
                        const uint32_t cg = (std::min)(255u, static_cast<uint32_t>(((c >> 8) & 255) * k[1] + 0.5f));
                        const uint32_t cb = (std::min)(255u, static_cast<uint32_t>((c & 255) * k[2] + 0.5f));
                        w[x] = (c & 0xFF000000u) | (cr << 16) | (cg << 8) | cb;
                    }
                }
                out->UnlockRect(0);
            } else { out->Release(); out = nullptr; }
            src->UnlockRect(0);
        } else { out->Release(); out = nullptr; }
    }
    s_baked[key] = out;
    static int logged = 0;
    if (logged++ < 40) Log("models: identity tint baked: %s x %.2f,%.2f,%.2f -> %s (%zu baked)", file.c_str(), key.t[0] / 64.0f, key.t[1] / 64.0f,
                           key.t[2] / 64.0f, out ? "ok" : "failed", s_baked.size());
    return out;
}

// IDENTITY-SYSTEM: a figure's split pair under RTX Remix. The importer draws a person's clothing
// as a second mesh over the same triangles (ped zones "#pt"/"#pb", or the "_paint" half), each half
// alpha-tested. Remix takes the second draw of the same surface as a duplicate (docs/remix-materials.md,
// "Car paint"): the clothing half was never path traced (pt-remix-third-figure-*: grey clay, then a
// floating head, forearms and shoes). Under the bake the rest mesh is drawn once with one merged
// texture - its own texels, and where it is cut out the paint half's texels in the identity record's
// tint for that texel's zone (top / bottom, rasterised from the zone meshes' UVs) - and the paint
// meshes are not drawn. The plain renderer keeps the two halves (same colours: same texels, same tint).
namespace {
void RasterUv(std::vector<uint8_t>* map, int w, int h, const ModelMesh& mesh, uint8_t value) {
    for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
        float px[3], py[3];
        for (int k = 0; k < 3; ++k) {
            const ModelVertex& v = mesh.vertices[mesh.indices[t + k]];
            px[k] = v.u * w; py[k] = v.v * h;
        }
        const int x0 = (std::max)(0, static_cast<int>(std::floor((std::min)({px[0], px[1], px[2]})))) ,
                  x1 = (std::min)(w - 1, static_cast<int>(std::ceil((std::max)({px[0], px[1], px[2]}))));
        const int y0 = (std::max)(0, static_cast<int>(std::floor((std::min)({py[0], py[1], py[2]})))),
                  y1 = (std::min)(h - 1, static_cast<int>(std::ceil((std::max)({py[0], py[1], py[2]}))));
        const float d = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2]);
        if (std::fabs(d) < 1e-6f) continue;
        for (int y = y0; y <= y1; ++y)
            for (int x = x0; x <= x1; ++x) {
                const float cx = x + 0.5f, cy = y + 0.5f;
                const float a = ((py[1] - py[2]) * (cx - px[2]) + (px[2] - px[1]) * (cy - py[2])) / d;
                const float b = ((py[2] - py[0]) * (cx - px[2]) + (px[0] - px[2]) * (cy - py[2])) / d;
                const float c = 1.0f - a - b;
                const float e = -0.02f;   // a texel's width of slack on the edges
                if (a >= e && b >= e && c >= e) (*map)[static_cast<size_t>(y) * w + x] = value;
            }
    }
}
}  // namespace

bool FigurePairPaintSkipped(const Model& model, const ModelMesh& mesh) {
    if (!g_bakeTints || mesh.texture.size() < 11 || mesh.texture.compare(mesh.texture.size() - 10, 10, "_paint.tga") != 0) return false;
    const std::string rest = mesh.texture.substr(0, mesh.texture.size() - 10) + ".tga";
    for (const ModelMesh& m : model.meshes) if (m.texture == rest) return true;   // drawn in the rest mesh's merged texture
    return false;
}

IDirect3DTexture9* FigurePairMerged(IDirect3DDevice9* device, const Model& model, const ModelMesh& mesh) {
    if (!g_bakeTints || !g_paintRests.count(mesh.texture)) return nullptr;
    const std::string paintFile = mesh.texture.substr(0, mesh.texture.size() - 4) + "_paint.tga";
    // The tints: per zone (top, bottom) for a zoned avatar, one for a tinted one, none for an untinted split.
    float tint[2][3] = {{1, 1, 1}, {1, 1, 1}};
    const bool zones = g_zoneOn && model.pedZones;
    if (zones) { for (int z = 0; z < 2; ++z) for (int k = 0; k < 3; ++k) tint[z][k] = g_zoneTint[z][k]; }
    else if (g_paintTintOn) { for (int z = 0; z < 2; ++z) for (int k = 0; k < 3; ++k) tint[z][k] = g_paintTint[k]; }
    int q[6];
    for (int z = 0; z < 2; ++z) for (int k = 0; k < 3; ++k) q[z * 3 + k] = static_cast<int>(std::lround(tint[z][k] * 64.0f));
    struct Key { const Model* m; std::string file; int q[6]; bool operator<(const Key& o) const {
        return std::tie(m, file, q[0], q[1], q[2], q[3], q[4], q[5]) < std::tie(o.m, o.file, o.q[0], o.q[1], o.q[2], o.q[3], o.q[4], o.q[5]); } };
    static std::map<Key, IDirect3DTexture9*> s_merged;
    static std::map<std::pair<const Model*, std::string>, std::vector<uint8_t>> s_zoneMaps;
    static IDirect3DDevice9* s_device = nullptr;
    if (s_device != device) { for (auto& b : s_merged) if (b.second) b.second->Release(); s_merged.clear(); s_device = device; }
    Key key{&model, mesh.texture, {q[0], q[1], q[2], q[3], q[4], q[5]}};
    auto it = s_merged.find(key);
    if (it != s_merged.end()) return it->second;
    if (s_merged.size() >= 256) return nullptr;
    IDirect3DTexture9* rest = TextureFor(device, mesh.texture);
    IDirect3DTexture9* paint = TextureFor(device, paintFile);
    IDirect3DTexture9* out = nullptr;
    D3DSURFACE_DESC dr, dp;
    if (rest && paint && SUCCEEDED(rest->GetLevelDesc(0, &dr)) && SUCCEEDED(paint->GetLevelDesc(0, &dp)) && dr.Format == D3DFMT_A8R8G8B8 &&
        dp.Format == D3DFMT_A8R8G8B8 && dr.Width == dp.Width && dr.Height == dp.Height &&
        SUCCEEDED(device->CreateTexture(dr.Width, dr.Height, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &out, nullptr))) {
        const int w = static_cast<int>(dr.Width), h = static_cast<int>(dr.Height);
        // The texel zones: 1 top, 2 bottom, from the zone meshes' triangles in UV space.
        std::vector<uint8_t>& zmap = s_zoneMaps[{&model, paintFile}];
        if (zones && zmap.empty()) {
            zmap.assign(static_cast<size_t>(w) * h, 0);
            for (const ModelNode& node : model.nodes) {
                if (node.mesh < 0 || node.mesh >= static_cast<int>(model.meshes.size())) continue;
                const ModelMesh& zm = model.meshes[node.mesh];
                if (zm.texture != paintFile) continue;
                if (strstr(node.name, "#pt")) RasterUv(&zmap, w, h, zm, 1);
                else if (strstr(node.name, "#pb")) RasterUv(&zmap, w, h, zm, 2);
            }
        }
        D3DLOCKED_RECT lr, lp, lo;
        const bool okR = SUCCEEDED(rest->LockRect(0, &lr, nullptr, D3DLOCK_READONLY));
        const bool okP = SUCCEEDED(paint->LockRect(0, &lp, nullptr, D3DLOCK_READONLY));
        const bool okO = SUCCEEDED(out->LockRect(0, &lo, nullptr, 0));
        if (okR && okP && okO) {
            for (int y = 0; y < h; ++y) {
                const uint32_t* r = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(lr.pBits) + y * lr.Pitch);
                const uint32_t* p = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(lp.pBits) + y * lp.Pitch);
                uint32_t* o = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lo.pBits) + y * lo.Pitch);
                for (int x = 0; x < w; ++x) {
                    if ((r[x] >> 24) >= 128 || (p[x] >> 24) < 128) { o[x] = r[x]; continue; }
                    const int z = zones ? (zmap[static_cast<size_t>(y) * w + x] == 2 ? 1 : 0) : 0;
                    const uint32_t c = p[x];
                    const uint32_t cr = (std::min)(255u, static_cast<uint32_t>(((c >> 16) & 255) * q[z * 3 + 0] / 64.0f + 0.5f));
                    const uint32_t cg = (std::min)(255u, static_cast<uint32_t>(((c >> 8) & 255) * q[z * 3 + 1] / 64.0f + 0.5f));
                    const uint32_t cb = (std::min)(255u, static_cast<uint32_t>((c & 255) * q[z * 3 + 2] / 64.0f + 0.5f));
                    o[x] = 0xFF000000u | (cr << 16) | (cg << 8) | cb;
                }
            }
        }
        if (okO) out->UnlockRect(0);
        if (okP) paint->UnlockRect(0);
        if (okR) rest->UnlockRect(0);
        if (!(okR && okP && okO)) { out->Release(); out = nullptr; }
    }
    s_merged[key] = out;
    static int logged = 0;
    if (logged++ < 40) Log("models: identity figure pair merged for Remix: %s + %s, top x %.2f,%.2f,%.2f bottom x %.2f,%.2f,%.2f -> %s", mesh.texture.c_str(),
                           paintFile.c_str(), q[0] / 64.0f, q[1] / 64.0f, q[2] / 64.0f, q[3] / 64.0f, q[4] / 64.0f, q[5] / 64.0f, out ? "ok" : "failed");
    return out;
}

void ModelSetPlayerTextures(bool on) { g_playerTextures = on; }

void ModelSetPaintTint(const float* rgb) {
    g_paintTintOn = rgb != nullptr;
    if (rgb) for (int i = 0; i < 3; ++i) g_paintTint[i] = (std::max)(0.0f, (std::min)(2.0f, rgb[i]));
}

std::map<std::string, const Model*> g_propMerged;   // role -> the merged copy (MergeStatic)

// A rigid, unanimated model as one mesh per texture, its node transforms baked into the
// vertices: the same triangles, the same picture, but a street lamp is 2 draws instead of
// 8 and a hydrant 2-3 instead of 20 (PERF-2: props were ~800 of ~1550 draw calls a frame).
// Null when the model is skinned or animated, or merging would not save a draw.
const Model* MergeStatic(const Model& model) {
    if (model.skinned || !model.animations.empty()) return nullptr;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model merged;
    merged.name = model.name + "#merged";
    merged.boundsMin = model.boundsMin;
    merged.boundsMax = model.boundsMax;
    merged.forward = model.forward;
    for (int k = 0; k < 3; ++k) merged.paintRgb[k] = model.paintRgb[k];
    merged.splitPaint = model.splitPaint;
    std::map<std::string, size_t> byTexture;
    size_t drawsBefore = 0;
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[mi];
        if (src.indices.size() < 3) continue;
        ++drawsBefore;
        auto at = byTexture.find(src.texture);
        if (at == byTexture.end()) {
            at = byTexture.emplace(src.texture, merged.meshes.size()).first;
            merged.meshes.emplace_back();
            merged.meshes.back().texture = src.texture;
        }
        ModelMesh& dst = merged.meshes[at->second];
        const gta2::Mat4& w = worlds[i];
        const uint32_t base = static_cast<uint32_t>(dst.vertices.size());
        for (const ModelVertex& v : src.vertices) {
            ModelVertex o = v;
            o.x = v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0];
            o.y = v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1];
            o.z = v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2];
            float nx = v.nx * w.m[0][0] + v.ny * w.m[1][0] + v.nz * w.m[2][0];
            float ny = v.nx * w.m[0][1] + v.ny * w.m[1][1] + v.nz * w.m[2][1];
            float nz = v.nx * w.m[0][2] + v.ny * w.m[1][2] + v.nz * w.m[2][2];
            const float n = std::sqrt(nx * nx + ny * ny + nz * nz);
            if (n > 1e-8f) { nx /= n; ny /= n; nz /= n; }
            o.nx = nx; o.ny = ny; o.nz = nz;
            dst.vertices.push_back(o);
        }
        for (uint32_t idx : src.indices) dst.indices.push_back(base + idx);
    }
    if (merged.meshes.empty() || merged.meshes.size() >= drawsBefore) return nullptr;
    for (size_t mi = 0; mi < merged.meshes.size(); ++mi) {
        ModelNode node = {};
        snprintf(node.name, sizeof node.name, "merged%zu", mi);
        node.parent = -1;
        node.rotation[3] = 1.0f;
        node.scale = {1.0f, 1.0f, 1.0f};
        node.mesh = static_cast<int>(mi);
        merged.nodes.push_back(node);
    }
    Log("models: prop %s merged for drawing, %zu draws -> %zu", model.name.c_str(), drawsBefore, merged.meshes.size());
    return ModelRegisterDerived(std::move(merged));
}

void MergeProps() {
    for (const auto& role : g_props) {
        auto m = g_byName.find(role.second);
        if (m == g_byName.end()) continue;
        if (const Model* merged = MergeStatic(g_models[m->second])) g_propMerged[role.first] = merged;
    }
}

const Model* ModelForProp(const char* role) {
    auto merged = g_propMerged.find(role);
    if (merged != g_propMerged.end()) return merged->second;
    auto it = g_props.find(role);
    if (it == g_props.end()) return nullptr;
    auto m = g_byName.find(it->second);
    return m == g_byName.end() ? nullptr : &g_models[m->second];
}

const Model* ModelByName(const char* name) {
    auto m = g_byName.find(name ? name : "");
    return m == g_byName.end() ? nullptr : &g_models[m->second];
}
const char* ModelsFolder() { return g_folder.c_str(); }

void SetMapLamps(const std::vector<gta2::Vec3>& lamps) { g_mapLamps = lamps; g_mapLampPosts.clear(); }
const std::vector<gta2::Vec3>& MapLamps() { return g_mapLamps; }
void SetMapLampPosts(const std::vector<gta2::Vec3>& posts) { g_mapLampPosts = posts; }
const std::vector<gta2::Vec3>& MapLampPosts() { return g_mapLampPosts; }

bool LampPostScale(const Model& lamp, float lampY, float floor, float* scale) {
    // A GTA2 street lamp sits well above the road; the post stands under it, its
    // top a little over the lamp (the lamp is the bulb inside the lantern).
    const float above = lampY - floor;
    if (above > 3.5f || above < 0.3f) return false;
    *scale = (above + 0.3f) / (std::max)(lamp.Height(), 0.1f);
    return true;
}

bool LampPostHead(const Model& lamp, const gta2::Vec3& at, float floor, LampHead* out) {
    // The lantern of the lamp model, in its own space, measured once. tools/gen_objects.py
    // build_lamp writes the post (with the dish, roof and bulb on its atlas) and then the
    // glass: two meshes, the glass the second. Anything else has no lantern to speak of.
    struct Lantern { bool valid = false; float cx = 0, cy = 0, cz = 0, radius = 0, dishBottom = 0; };
    static const Model* s_model = nullptr;
    static Lantern s_lantern;
    if (s_model != &lamp) {
        s_model = &lamp;
        s_lantern = Lantern();
        std::vector<gta2::Mat4> worlds;
        NodeWorlds(lamp, nullptr, 0.0f, &worlds);
        auto posed = [&](int meshIndex, std::vector<gta2::Vec3>* pts) {
            for (size_t i = 0; i < lamp.nodes.size(); ++i) {
                if (lamp.nodes[i].mesh != meshIndex || lamp.meshes[meshIndex].skin >= 0) continue;
                const gta2::Mat4& w = worlds[i];
                for (const ModelVertex& v : lamp.meshes[meshIndex].vertices) {
                    pts->push_back({v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0],
                                    v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1],
                                    v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2]});
                }
            }
        };
        std::vector<gta2::Vec3> glass, post;
        if (lamp.meshes.size() == 2) { posed(1, &glass); posed(0, &post); }
        if (!glass.empty() && !post.empty()) {
            gta2::Vec3 lo = glass[0], hi = glass[0];
            for (const gta2::Vec3& p : glass) {
                lo = {(std::min)(lo.x, p.x), (std::min)(lo.y, p.y), (std::min)(lo.z, p.z)};
                hi = {(std::max)(hi.x, p.x), (std::max)(hi.y, p.y), (std::max)(hi.z, p.z)};
            }
            Lantern l;
            l.cx = 0.5f * (lo.x + hi.x); l.cy = 0.5f * (lo.y + hi.y); l.cz = 0.5f * (lo.z + hi.z);
            l.radius = 0.5f * (std::min)(hi.x - lo.x, hi.z - lo.z);
            // The dish the glass stands on: the post's widest part just under the glass.
            l.dishBottom = lo.y;
            const float band = 0.1f * lamp.Height();
            for (const gta2::Vec3& p : post) {
                if (p.y < lo.y - band || p.y > lo.y) continue;
                if (std::hypot(p.x - l.cx, p.z - l.cz) < 0.5f * l.radius) continue;
                l.dishBottom = (std::min)(l.dishBottom, p.y);
            }
            l.valid = l.radius > 0.0f;
            s_lantern = l;
            Log("lamp post: lantern glass %.3f across at %.2f of %.2f, dish from %.2f", 2.0f * l.radius, l.cy,
                lamp.Height(), l.dishBottom);
        }
    }
    float scale = 0.0f;
    if (!s_lantern.valid || !LampPostScale(lamp, at.y, floor, &scale)) return false;
    // The draw: yaw 0 (DrawProps), the foot on the floor.
    const float base = floor - lamp.boundsMin.y * scale;
    out->centre = {at.x + s_lantern.cx * scale, base + s_lantern.cy * scale, at.z + s_lantern.cz * scale};
    out->glassRadius = s_lantern.radius * scale;
    out->dishBottom = base + s_lantern.dishBottom * scale;
    return true;
}

const Model* ModelForPedestrian() {
    auto it = g_byName.find(g_pedestrian);
    return it == g_byName.end() ? nullptr : &g_models[it->second];
}

static uint32_t ScrambleSeed(uint32_t seed) {
    seed ^= seed >> 16;
    seed *= 0x7feb352dU;
    seed ^= seed >> 15;
    seed *= 0x846ca68bU;
    seed ^= seed >> 16;
    return seed;
}

const Model* ModelForPedestrian(uint32_t seed, int remap) {
    static bool seen[65] = {};
    const int slot = remap >= 0 && remap < 64 ? remap : 64;
    if (remap >= 0 && remap < 64 && g_pedTypeByRemap[remap] >= 0) {
        const PedType& type = g_pedTypes[g_pedTypeByRemap[remap]];
        if (!type.models.empty()) {
            const Model* model = &g_models[g_byName[type.models[ScrambleSeed(seed) % type.models.size()]]];
            if (!seen[slot]) { seen[slot] = true; Log("models: pedestrian remap %d -> type '%s' (first: %s%s)", remap, type.name.c_str(), model->name.c_str(), type.tint ? ", tinted" : ""); }
            return model;
        }
    }
    if (!seen[slot]) { seen[slot] = true; Log("models: pedestrian remap %d -> no type, plain list", remap); }
    return ModelForPedestrian(seed);
}

void PedRemapsSetPalettes(const std::vector<int>& physicalByRemap) {
    g_pedRemapByPalette.clear();
    for (size_t r = 0; r < physicalByRemap.size(); ++r)
        if (physicalByRemap[r] >= 0 && !g_pedRemapByPalette.count(physicalByRemap[r])) g_pedRemapByPalette[physicalByRemap[r]] = static_cast<int>(r);
    Log("models: %zu pedestrian remap palettes known", g_pedRemapByPalette.size());
}

int g_pedRemapOverride = -1;
void PedRemapOverride(int mode) { g_pedRemapOverride = mode; }
int PedRemapEffective(int remap, uint32_t seed) {
    if (g_pedRemapOverride >= 0 && g_pedRemapOverride < 64) return g_pedRemapOverride;
    if (g_pedRemapOverride == -2) {
        static const int kTyped[] = {0, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 22, 27, 52};
        return kTyped[ScrambleSeed(seed) % (sizeof(kTyped) / sizeof(kTyped[0]))];
    }
    return remap;
}

int PedRemapForPalette(int physicalPalette) {
    const auto it = g_pedRemapByPalette.find(physicalPalette);
    return it == g_pedRemapByPalette.end() ? -1 : it->second;
}

bool PedRemapTint(int remap, const Model& model, float rgb[3]) {
    if (remap < 0 || remap >= 64 || g_pedTypeByRemap[remap] < 0) return false;
    if (!g_pedTypes[g_pedTypeByRemap[remap]].tint) return false;
    const float* c = g_pedRemapColour[remap];
    if (c[0] + c[1] + c[2] < 1.0f) return false;
    for (int k = 0; k < 3; ++k) rgb[k] = (std::max)(0.0f, (std::min)(2.0f, c[k] / (std::max)(8.0f, model.paintRgb[k])));
    return true;
}

bool PedTypeBuild(int remap, float* scale, float* width) {
    *scale = *width = 1.0f;
    if (remap < 0 || remap >= 64 || g_pedTypeByRemap[remap] < 0) return false;
    const PedType& t = g_pedTypes[g_pedTypeByRemap[remap]];
    *scale = t.scale; *width = t.width;
    return t.scale != 1.0f || t.width != 1.0f;
}

bool PedRemapHasType(int remap) { return remap >= 0 && remap < 64 && g_pedTypeByRemap[remap] >= 0; }

bool PedZoneTints(int remap, const Model& model, float tints[3][3], bool* hairTint) {
    if (hairTint) *hairTint = false;
    if (!model.pedZones || remap < 0 || remap >= 64 || g_pedTypeByRemap[remap] < 0) return false;
    if (!g_pedTypes[g_pedTypeByRemap[remap]].tint) return false;
    const float* o = g_pedOutfit[remap];
    for (int z = 0; z < 2; ++z) {
        const float* want = o[z * 3] + o[z * 3 + 1] + o[z * 3 + 2] >= 1.0f ? o + z * 3 : model.zoneRgb[z];
        for (int k = 0; k < 3; ++k) tints[z][k] = (std::max)(0.0f, (std::min)(2.0f, want[k] / (std::max)(8.0f, model.zoneRef)));
    }
    const bool hair = o[6] + o[7] + o[8] >= 1.0f && model.zoneRgb[2][0] + model.zoneRgb[2][1] + model.zoneRgb[2][2] >= 1.0f;
    for (int k = 0; k < 3; ++k) tints[2][k] = hair ? (std::max)(0.0f, (std::min)(2.0f, o[6 + k] / (std::max)(8.0f, model.zoneRgb[2][k]))) : 1.0f;
    if (hairTint) *hairTint = hair;
    return true;
}

const Model* ModelForPedestrian(uint32_t seed) {
    if (g_pedestrians.empty()) return nullptr;
    // Scramble the seed so near-by values (addresses, indices) spread out.
    seed ^= seed >> 16;
    seed *= 0x7feb352dU;
    seed ^= seed >> 15;
    seed *= 0x846ca68bU;
    seed ^= seed >> 16;
    return &g_models[g_byName[g_pedestrians[seed % g_pedestrians.size()]]];
}

// Where ModelDraw's time goes this frame: node worlds + posing (skinning),
// buffer fills (a skinned mesh's pose written to its managed buffer), the whole
// of ModelDraw; then counts of draws and skinned draws.
double g_modelStats[6] = {};
LARGE_INTEGER g_modelFreq = {};
double ModelMs(const LARGE_INTEGER& a, const LARGE_INTEGER& b) {
    if (!g_modelFreq.QuadPart) QueryPerformanceFrequency(&g_modelFreq);
    return 1000.0 * static_cast<double>(b.QuadPart - a.QuadPart) / static_cast<double>(g_modelFreq.QuadPart);
}
int g_newPosesThisFrame = 0;   // see PoseFor
void ModelsBeginFrame() { g_drawn = 0; g_newPosesThisFrame = 0; for (double& v : g_modelStats) v = 0.0; }

size_t g_warmCursor = 0;
std::vector<std::string> g_warmList;

// Binds `texture` in a two-triangle draw with colour and depth writes off: no
// pixel changes, but wined3d loads the texture into GL for it, which is the
// 20-100 ms a first use would otherwise cost in the middle of play.
void WarmTexture(IDirect3DDevice9* device, IDirect3DTexture9* texture) {
    if (!device || !texture) return;
    struct V { float x, y, z, rhw, u, v; };
    const V quad[4] = {{0.0f, 0.0f, 0.5f, 1.0f, 0.0f, 0.0f}, {2.0f, 0.0f, 0.5f, 1.0f, 1.0f, 0.0f},
                       {0.0f, 2.0f, 0.5f, 1.0f, 0.0f, 1.0f}, {2.0f, 2.0f, 0.5f, 1.0f, 1.0f, 1.0f}};
    DWORD colorWrite = 0xF, zWrite = TRUE, zEnable = TRUE, fvf = 0;
    device->GetRenderState(D3DRS_COLORWRITEENABLE, &colorWrite);
    device->GetRenderState(D3DRS_ZWRITEENABLE, &zWrite);
    device->GetRenderState(D3DRS_ZENABLE, &zEnable);
    device->GetFVF(&fvf);
    device->SetRenderState(D3DRS_COLORWRITEENABLE, 0);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_ZENABLE, FALSE);
    device->SetTexture(0, texture);
    device->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
    device->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(V));
    device->SetTexture(0, nullptr);
    device->SetFVF(fvf);
    device->SetRenderState(D3DRS_COLORWRITEENABLE, colorWrite);
    device->SetRenderState(D3DRS_ZWRITEENABLE, zWrite);
    device->SetRenderState(D3DRS_ZENABLE, zEnable);
}

int ModelsDrawnThisFrame() { return g_drawn; }
const double* ModelDrawStats() { return g_modelStats; }

// The posed vertices of each skinned mesh, kept from one draw to the next: many
// pedestrians share a model, and two at the same point of the same animation
// cost one skinning, not two. Several poses are kept (walk cycles quantised by
// the caller land on the same keys), the least recently used dropped first.
struct PoseKey {
    const Model* model = nullptr;
    const ModelAnimation* animation = nullptr;
    const ModelAnimation* second = nullptr;
    float time = -1.0f, secondTime = -1.0f, weight = 0.0f, twist = 0.0f, head = 0.0f;
    const ModelAnimation* overlay = nullptr;
    float overlayTime = 0.0f, overlayWeight = 0.0f;
    int layers = 0;      // ANIM-BLEND-AUDIT: ModelSetLayers
    const ModelAnimation* layer[kModelLayers] = {};
    float layerT[kModelLayers] = {}, layerW[kModelLayers] = {};
    bool LayersEqual(const PoseKey& o) const {
        if (layers != o.layers) return false;
        for (int k = 0; k < layers; ++k)
            if (layer[k] != o.layer[k] || std::fabs(layerT[k] - o.layerT[k]) >= 1e-4f || std::fabs(layerW[k] - o.layerW[k]) >= 1e-3f) return false;
        return true;
    }
    uint64_t ik = 0;   // ANIM-VEHICLE-ENTRY: the limb targets (LimbIkRekey)
    uint64_t hook = 0;   // QB-27: a ragdoll's pose (its id and generation), 0 for a clip pose
    bool operator==(const PoseKey& o) const {
        return model == o.model && hook == o.hook && ik == o.ik && LayersEqual(o) && animation == o.animation && second == o.second && overlay == o.overlay &&
               std::fabs(overlayTime - o.overlayTime) < 1e-4f && std::fabs(overlayWeight - o.overlayWeight) < 1e-3f &&
               std::fabs(time - o.time) < 1e-4f &&
               std::fabs(secondTime - o.secondTime) < 1e-4f && std::fabs(weight - o.weight) < 1e-3f &&
               std::fabs(twist - o.twist) < 1e-3f && std::fabs(head - o.head) < 1e-3f;
    }
};
struct PosedCache {
    PoseKey key;
    uint64_t id = 0;   // unique per cached pose: what the vertex buffers remember holding
    unsigned used = 0;
    std::vector<std::vector<ModelVertex>> meshes;
};
constexpr size_t kPoseCacheMax = 160;   // ~5k vertices x 32 bytes x 160 = 26 MB at most
std::vector<PosedCache> g_poses;
uint64_t g_poseNext = 1;
unsigned g_poseClock = 0;
const PosedCache* g_posedNow = nullptr;   // the pose the draw in progress uses

// The vertex and index buffers of one mesh. Meshes used to be drawn straight
// from memory (DrawIndexedPrimitiveUP), which has wined3d copy every vertex
// into its upload heap each frame; with the larger props that heap ran dry and
// the copy went to a null pointer. Managed buffers are filled once for a rigid
// mesh and rewritten only when a skinned mesh's pose changes.
struct MeshBuffers {
    IDirect3DVertexBuffer9* vb = nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    uint64_t pose = 0;    // the cached pose held by vb, skinned meshes only
    bool failed = false;  // creation failed once: draw from memory instead
};
std::map<const ModelMesh*, MeshBuffers> g_buffers;

bool FillVertices(IDirect3DVertexBuffer9* vb, const ModelVertex* verts, size_t count, DWORD flags = 0) {
    void* data = nullptr;
    if (FAILED(vb->Lock(0, static_cast<UINT>(count * sizeof(ModelVertex)), &data, flags)) || !data) return false;
    memcpy(data, verts, count * sizeof(ModelVertex));
    vb->Unlock();
    return true;
}

// A skinned mesh's posed vertices, one vertex buffer per cached pose. Rewriting
// a managed buffer that was drawn from this frame makes wined3d wait for the
// GL stream to drain and upload the whole buffer again, which cost 25 ms per
// pedestrian on the software driver (203 ms a frame for eight people). These
// are dynamic buffers in the default pool, written once with DISCARD when the
// pose is first seen and kept while the pose stays in the cache; the oldest go
// when there are too many. Released with the device (ModelsReleaseDevice).
struct SkinBuffer {
    IDirect3DVertexBuffer9* vb = nullptr;
    unsigned used = 0;
};
struct SkinKey {
    const ModelMesh* mesh;
    uint64_t pose;
    bool operator<(const SkinKey& o) const { return mesh != o.mesh ? mesh < o.mesh : pose < o.pose; }
};
std::map<SkinKey, SkinBuffer> g_skinBuffers;
// Buffers of evicted poses, by size, kept for the next new pose of that size: creating
// a default-pool buffer is a driver round trip, and a crowd needs ~5 new ones a frame
// (PERF-2). Rewritten with DISCARD, so reuse never waits on a draw in flight.
std::multimap<UINT, IDirect3DVertexBuffer9*> g_skinFree;
unsigned g_skinClock = 0;
constexpr size_t kSkinBuffersMax = 256;   // ~70 KB each on average: ~18 MB (was 96, which a crowd cycling 24 walk poses thrashed)

IDirect3DVertexBuffer9* SkinBufferFor(IDirect3DDevice9* device, const ModelMesh& mesh, const ModelVertex* verts,
                                      uint64_t pose) {
    ++g_skinClock;
    const SkinKey key{&mesh, pose};
    auto it = g_skinBuffers.find(key);
    if (it != g_skinBuffers.end()) {
        it->second.used = g_skinClock;
        return it->second.vb;
    }
    if (g_skinBuffers.size() >= kSkinBuffersMax) {
        auto oldest = g_skinBuffers.begin();
        for (auto i = g_skinBuffers.begin(); i != g_skinBuffers.end(); ++i) if (i->second.used < oldest->second.used) oldest = i;
        if (oldest->second.vb) {
            D3DVERTEXBUFFER_DESC desc;
            if (SUCCEEDED(oldest->second.vb->GetDesc(&desc)) && g_skinFree.size() < 32) g_skinFree.emplace(desc.Size, oldest->second.vb);
            else oldest->second.vb->Release();
        }
        g_skinBuffers.erase(oldest);
    }
    IDirect3DVertexBuffer9* vb = nullptr;
    const UINT vbytes = static_cast<UINT>(mesh.vertices.size() * sizeof(ModelVertex));
    auto spare = g_skinFree.lower_bound(vbytes);   // the same size, or a larger one (the spares made ahead are the largest)
    if (spare != g_skinFree.end()) {
        vb = spare->second;
        g_skinFree.erase(spare);
    } else {
        if (FAILED(device->CreateVertexBuffer(vbytes, D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &vb, nullptr)) ||
            !vb) {
            return nullptr;
        }
        FrameLogNote(kFcSkinBuffer);
    }
    if (!FillVertices(vb, verts, mesh.vertices.size(), D3DLOCK_DISCARD)) {
        vb->Release();
        return nullptr;
    }
    g_skinBuffers[key] = {vb, g_skinClock};
    return vb;
}

// The buffers of a mesh, created and filled on first use; null when the device
// would not give them (the caller then draws from memory).
MeshBuffers* BuffersFor(IDirect3DDevice9* device, const ModelMesh& mesh, bool skinned, const ModelVertex* verts,
                        uint64_t pose) {
    MeshBuffers& b = g_buffers[&mesh];
    if (b.failed) return nullptr;
    if (!b.vb) {
        const UINT vbytes = static_cast<UINT>(mesh.vertices.size() * sizeof(ModelVertex));
        const UINT ibytes = static_cast<UINT>(mesh.indices.size() * sizeof(uint32_t));
        // A mesh made while the game runs (a car's dented copy or door split) is
        // first drawn mid-frame: locking a new managed buffer there makes wined3d
        // wait for the frame's queued GL work (50-210 ms a copy, PERF-3), so those
        // get dynamic default-pool buffers written with DISCARD, which do not wait.
        const bool dynamic = !skinned && g_dynamicMeshes.count(&mesh) != 0;
        const DWORD usage = dynamic ? (D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY) : D3DUSAGE_WRITEONLY;
        const D3DPOOL pool = dynamic ? D3DPOOL_DEFAULT : D3DPOOL_MANAGED;
        const DWORD lockFlags = dynamic ? D3DLOCK_DISCARD : 0;
        if (FAILED(device->CreateVertexBuffer(vbytes, usage, 0, pool, &b.vb, nullptr)) ||
            FAILED(device->CreateIndexBuffer(ibytes, usage, D3DFMT_INDEX32, pool, &b.ib,
                                             nullptr))) {
            if (b.vb) b.vb->Release();
            if (b.ib) b.ib->Release();
            b.vb = nullptr;
            b.ib = nullptr;
            b.failed = true;
            Log("models: no buffers for a mesh of %u vertices, drawing it from memory",
                static_cast<unsigned>(mesh.vertices.size()));
            return nullptr;
        }
        void* idata = nullptr;
        if (FAILED(b.ib->Lock(0, ibytes, &idata, lockFlags)) || !idata) {
            b.failed = true;
            return nullptr;
        }
        memcpy(idata, mesh.indices.data(), ibytes);
        b.ib->Unlock();
        if (!FillVertices(b.vb, verts, mesh.vertices.size(), lockFlags)) {
            b.failed = true;
            return nullptr;
        }
        b.pose = pose;
        FrameLogNote(kFcModelBuffers);
    } else if (skinned && b.pose != pose) {
        // The managed buffer keeps the first pose it was given; later poses come
        // from SkinBufferFor (see there), so this rewrite is never reached.
        if (!FillVertices(b.vb, verts, mesh.vertices.size())) return nullptr;
        b.pose = pose;
    }
    return &b;
}

// New poses skinned this frame, and the most a frame may skin (PERF-2: a crowd in
// Residential needed up to 14 new poses in one frame, 18 ms). Past the budget a
// figure takes the cached pose of the same model and clips nearest in time, a few
// hundredths of a second of the cycle off for that one frame.
constexpr int kNewPoseBudget = 5;

// The cached pose for a key, skinned now if it was not there.
const PosedCache& PoseFor(const Model& model, const PoseKey& key, const std::vector<gta2::Mat4>& worlds) {
    ++g_poseClock;
    for (PosedCache& p : g_poses) {
        if (p.key == key) {
            p.used = g_poseClock;
            return p;
        }
    }
    if (g_newPosesThisFrame >= kNewPoseBudget) {
        PosedCache* nearest = nullptr;
        float best = 0.12f;   // seconds of the clip: beyond this, skin it anyway
        for (PosedCache& p : g_poses) {
            if (p.key.model != key.model || p.key.animation != key.animation || p.key.second != key.second ||
                p.key.overlay != key.overlay || p.key.hook != key.hook) continue;
            if (std::fabs(p.key.weight - key.weight) > 0.15f || std::fabs(p.key.twist - key.twist) > 0.05f || std::fabs(p.key.head - key.head) > 0.1f ||
                std::fabs(p.key.overlayWeight - key.overlayWeight) > 0.15f) continue;
            const float d = std::fabs(p.key.time - key.time) + std::fabs(p.key.secondTime - key.secondTime) +
                            std::fabs(p.key.overlayTime - key.overlayTime);
            if (d < best) { best = d; nearest = &p; }
        }
        if (nearest) {
            nearest->used = g_poseClock;
            return *nearest;
        }
    }
    ++g_newPosesThisFrame;
    if (key.hook) {
        // A ragdoll's earlier poses are never drawn again: dropped, not left to age out.
        for (size_t i = 0; i < g_poses.size();) {
            if (g_poses[i].key.hook && (g_poses[i].key.hook >> 24) == (key.hook >> 24)) {
                g_poses[i] = std::move(g_poses.back());
                g_poses.pop_back();
            } else {
                ++i;
            }
        }
    }
    if (g_poses.size() >= kPoseCacheMax) {
        size_t oldest = 0;
        for (size_t i = 1; i < g_poses.size(); ++i) if (g_poses[i].used < g_poses[oldest].used) oldest = i;
        g_poses.erase(g_poses.begin() + static_cast<ptrdiff_t>(oldest));
    }
    g_poses.emplace_back();
    PosedCache& p = g_poses.back();
    p.key = key;
    p.id = g_poseNext++;
    p.used = g_poseClock;
    FrameLogNote(kFcNewPose);
    std::vector<std::vector<gta2::Mat4>> joints(model.skins.size());
    for (size_t sk = 0; sk < model.skins.size(); ++sk) SkinMatrices(model, model.skins[sk], worlds, &joints[sk]);
    p.meshes.resize(model.meshes.size());
    for (size_t mi = 0; mi < model.meshes.size(); ++mi) {
        const ModelMesh& mesh = model.meshes[mi];
        if (mesh.skin >= 0) SkinMesh(mesh, joints[mesh.skin], &p.meshes[mi]);
        else p.meshes[mi].clear();
    }
    return p;
}

namespace {
void ResetSoftStages(IDirect3DDevice9* device) {
    device->SetTextureStageState(1, D3DTSS_RESULTARG, D3DTA_CURRENT);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
}
}  // namespace

void ModelSetSoftPaintMasks(bool on) { g_softPaintSetting = on; }

// FIX-CAR-RENDER: a 64x64 luminance map (box mean, 0..255) and paint-mask map of a
// model texture, read from its file on the CPU (no device), cached for the process.
namespace {
struct LumaMap { int w = 0, h = 0; std::vector<uint8_t> luma, mask; };
std::map<std::string, LumaMap> g_lumaMaps;
const LumaMap* LumaFor(const std::string& file) {
    auto it = g_lumaMaps.find(file);
    if (it != g_lumaMaps.end()) return it->second.w ? &it->second : nullptr;
    LumaMap& m = g_lumaMaps[file];
    std::vector<uint8_t> tga;
    if (!ReadAll(g_folder + "\\" + file, &tga) || tga.size() <= 18 || tga[2] != 2 || tga[16] != 32) return nullptr;
    const int w = tga[12] | (tga[13] << 8), h = tga[14] | (tga[15] << 8);
    if (w <= 0 || h <= 0 || tga.size() < 18u + static_cast<size_t>(w) * h * 4) return nullptr;
    const bool topDown = (tga[17] & 0x20) != 0;
    constexpr int kN = 64;
    std::vector<float> sum(kN * kN, 0.0f), msum(kN * kN, 0.0f), cnt(kN * kN, 0.0f);
    for (int y = 0; y < h; ++y) {
        const int src = topDown ? y : (h - 1 - y);
        const uint8_t* row = &tga[18 + static_cast<size_t>(src) * w * 4];
        const int cy = y * kN / h;
        for (int x = 0; x < w; ++x) {
            const uint8_t* px = row + x * 4;
            const int c = cy * kN + x * kN / w;
            sum[c] += 0.114f * px[0] + 0.587f * px[1] + 0.299f * px[2];
            msum[c] += px[3];
            cnt[c] += 1.0f;
        }
    }
    m.w = kN; m.h = kN; m.luma.resize(kN * kN); m.mask.resize(kN * kN);
    for (int i = 0; i < kN * kN; ++i) {
        m.luma[i] = static_cast<uint8_t>(cnt[i] > 0 ? sum[i] / cnt[i] : 0);
        m.mask[i] = static_cast<uint8_t>(cnt[i] > 0 ? msum[i] / cnt[i] : 0);
    }
    return &m;
}
}  // namespace

bool ModelTextureSample(const std::string& file, float u, float v, float* luma, float* alpha) {
    const LumaMap* m = LumaFor(file);
    if (!m) return false;
    u -= std::floor(u); v -= std::floor(v);
    const int x = (std::min)(m->w - 1, static_cast<int>(u * m->w)), y = (std::min)(m->h - 1, static_cast<int>(v * m->h));
    if (luma) *luma = m->luma[static_cast<size_t>(y) * m->w + x];
    if (alpha) *alpha = m->mask[static_cast<size_t>(y) * m->w + x];
    return true;
}
bool ModelSoftPaintActive() { return g_softPaintSetting && g_softPaintCaps == 1 && !RemixApiAvailable(); }

void ModelDraw(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement,
               const ModelAnimation* animation, float time) {
    ModelDrawBlend(device, model, placement, animation, time, nullptr, 0.0f, 0.0f);
}

void ModelDrawBlend(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement,
                    const ModelAnimation* animation, float time, const ModelAnimation* second,
                    float secondTime, float weight) {
    if (!second || weight <= 1e-3f) { second = nullptr; secondTime = 0.0f; weight = 0.0f; }
    LARGE_INTEGER t0, t1, t2;
    QueryPerformanceCounter(&t0);
    const double probeTex0 = g_texNewMs, probeFill0 = g_modelStats[1];
    const int probeTexN0 = g_texNew;
    std::vector<gta2::Mat4> worlds;
    NodeWorldsBlend(model, animation, time, second, secondTime, weight, &worlds);
    // The posed meshes, from the cache when this pose was skinned before.
    const PosedCache* posed = nullptr;
    if (model.skinned) {
        PoseKey key;
        key.model = &model;
        key.animation = animation;
        key.second = second;
        key.time = time;
        key.secondTime = secondTime;
        key.weight = weight;
        key.twist = g_torsoTwist;
        key.head = g_headTurn;
        key.ik = g_limbIkKey;
        key.overlay = g_overlay;
        key.overlayTime = g_overlay ? g_overlayTime : 0.0f;
        key.overlayWeight = g_overlay ? g_overlayWeight : 0.0f;
        if (g_layerModel == &model) {
            key.layers = g_layerCount;
            for (int k = 0; k < g_layerCount; ++k) { key.layer[k] = g_layerClip[k]; key.layerT[k] = g_layerTime[k]; key.layerW[k] = g_layerWeight[k]; }
        }
        key.hook = g_poseHookKey;
        posed = &PoseFor(model, key, worlds);
    }
    QueryPerformanceCounter(&t1);
    const LARGE_INTEGER tPosed = t1;
    g_modelStats[0] += ModelMs(t0, t1);
    g_modelStats[3] += 1.0;
    if (model.skinned) g_modelStats[4] += 1.0;
    IDirect3DTexture9* bound = nullptr;
    bool first = true;
    bool streams = false;
    bool softStages = false;
    int carSurf = kCarSurfDefault;
    bool carSurfSaved = false;
    D3DMATERIAL9 carSurfMaterial = {};
    DWORD carSurfState[5] = {};
    {
        // Once per model: the placement it is first drawn with, so a model that
        // comes out the wrong size or way up can be traced to its matrix.
        static std::set<const Model*> logged;
        if (!g_modelGhost && logged.size() < 96 && logged.insert(&model).second) {
            const gta2::Mat4& w = placement;
            Log("model draw: %s rows (%.3f %.3f %.3f) (%.3f %.3f %.3f) (%.3f %.3f %.3f) at %.2f,%.2f,%.2f nodes %zu bounds %.2f..%.2f y",
                model.name.c_str(), w.m[0][0], w.m[0][1], w.m[0][2], w.m[1][0], w.m[1][1], w.m[1][2], w.m[2][0], w.m[2][1], w.m[2][2],
                w.m[3][0], w.m[3][1], w.m[3][2], model.nodes.size(), model.boundsMin.y, model.boundsMax.y);
        }
    }
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& mesh = model.meshes[mi];
        if (mesh.indices.size() < 3) continue;
        // Soft paint: the rest half of a softened split is not drawn (the paint half is the whole surface).
        bool softPaint = false;
        if (!g_softPaintTex.empty() && model.splitPaint) {
            if (mesh.texture.find("_paint") != std::string::npos) {
                TextureFor(device, mesh.texture);
                softPaint = g_softPaintTex.count(mesh.texture) != 0;
            } else if (g_paintRests.count(mesh.texture)) {
                const std::string paintTex = mesh.texture.substr(0, mesh.texture.size() - 4) + "_paint.tga";
                TextureFor(device, paintTex);
                if (g_softPaintTex.count(paintTex)) continue;
            }
        }
        if (softStages && !softPaint) {
            ResetSoftStages(device);
            softStages = false;
        }
        // IDENTITY-SYSTEM: a figure's split pair under the bake (Remix): the rest mesh carries both halves.
        if (FigurePairPaintSkipped(model, mesh)) continue;
        // VEHICLE-ART-2: a parametric car's glass, chrome and rubber (see CarSurfaceFor).
        {
            const int surf = CarSurfaceFor(mesh.texture);
            if (surf != carSurf) {
                if (!carSurfSaved) {
                    device->GetMaterial(&carSurfMaterial);
                    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &carSurfState[0]);
                    device->GetRenderState(D3DRS_SRCBLEND, &carSurfState[1]);
                    device->GetRenderState(D3DRS_DESTBLEND, &carSurfState[2]);
                    device->GetRenderState(D3DRS_ZWRITEENABLE, &carSurfState[3]);
                    device->GetRenderState(D3DRS_ALPHATESTENABLE, &carSurfState[4]);
                    carSurfSaved = true;
                }
                D3DMATERIAL9 m = carSurfMaterial;
                if (surf == kCarSurfGlass) { m.Specular = {1.0f, 1.0f, 1.0f, 1.0f}; m.Power = 90.0f; }
                else if (surf == kCarSurfChrome) { m.Specular = {1.0f, 1.0f, 1.0f, 1.0f}; m.Power = 60.0f; }
                else if (surf == kCarSurfMatte) { m.Specular = {0.06f, 0.06f, 0.06f, 1.0f}; m.Power = 8.0f; }
                device->SetMaterial(&m);
                const bool glass = surf == kCarSurfGlass;
                device->SetRenderState(D3DRS_ALPHABLENDENABLE, glass ? TRUE : carSurfState[0]);
                device->SetRenderState(D3DRS_SRCBLEND, glass ? D3DBLEND_SRCALPHA : carSurfState[1]);
                device->SetRenderState(D3DRS_DESTBLEND, glass ? D3DBLEND_INVSRCALPHA : carSurfState[2]);
                device->SetRenderState(D3DRS_ZWRITEENABLE, glass ? FALSE : carSurfState[3]);
                device->SetRenderState(D3DRS_ALPHATESTENABLE, glass ? FALSE : carSurfState[4]);
                carSurf = surf;
            }
        }
        IDirect3DTexture9* merged = FigurePairMerged(device, model, mesh);
        IDirect3DTexture9* texture = merged ? merged : TextureFor(device, mesh.texture);
        if (first || texture != bound) {
            device->SetTexture(0, texture);
            bound = texture;
            first = false;
        }
        // IDENTITY-SYSTEM: the nodes named by ModelSetNodeTint (the first-person sleeves) in the
        // player record's shirt colour, a factor over their own texture.
        if (g_nodeTintOn) {
            if (strncmp(model.nodes[i].name, g_nodeTintPrefix, strlen(g_nodeTintPrefix)) == 0) {
                const DWORD t = 0xFF000000u | (static_cast<DWORD>(g_nodeTint[0] * 127.5f) << 16) |
                                (static_cast<DWORD>(g_nodeTint[1] * 127.5f) << 8) | static_cast<DWORD>(g_nodeTint[2] * 127.5f);
                device->SetRenderState(D3DRS_TEXTUREFACTOR, t);
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE2X);
                device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
                device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
            } else {
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            }
        } else
        // ASSET-PEDS: a zoned pedestrian's top, bottom and hair, each its own factor.
        if (g_zoneOn && model.pedZones) {
            const char* nn = model.nodes[i].name;
            const int zone = strstr(nn, "#pt") ? 0 : strstr(nn, "#pb") ? 1
                           : (g_zoneHair && mesh.texture.find("_opacity") != std::string::npos) ? 2 : -1;
            IDirect3DTexture9* baked = zone >= 0 && g_bakeTints ? BakedTint(device, mesh.texture, g_zoneTint[zone]) : nullptr;
            if (baked) {
                device->SetTexture(0, baked);
                bound = baked;
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            } else if (zone >= 0) {
                const float* zt = g_zoneTint[zone];
                const DWORD t = 0xFF000000u | (static_cast<DWORD>(zt[0] * 127.5f) << 16) |
                                (static_cast<DWORD>(zt[1] * 127.5f) << 8) | static_cast<DWORD>(zt[2] * 127.5f);
                device->SetRenderState(D3DRS_TEXTUREFACTOR, t);
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE2X);
                device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
                device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
            } else {
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            }
        } else if (softPaint) {
            // colour = lit texel * lerp(1, 2 * factor, coverage): stage 1 puts the tinted
            // colour in TEMP, stage 2 blends CURRENT toward it by the texture's coverage
            // alpha. Opaque (the coverage is not a cut-out).
            const float* tn = g_paintTintOn ? g_paintTint : nullptr;
            const DWORD t = tn ? (0xFF000000u | (static_cast<DWORD>(tn[0] * 127.5f) << 16) |
                                  (static_cast<DWORD>(tn[1] * 127.5f) << 8) | static_cast<DWORD>(tn[2] * 127.5f))
                               : 0xFF808080u;
            device->SetRenderState(D3DRS_TEXTUREFACTOR, t);
            device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE2X);
            device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
            device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_TFACTOR);
            device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
            device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
            device->SetTextureStageState(1, D3DTSS_RESULTARG, D3DTA_TEMP);
            device->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_LERP);
            device->SetTextureStageState(2, D3DTSS_COLORARG0, D3DTA_CURRENT | D3DTA_ALPHAREPLICATE);
            device->SetTextureStageState(2, D3DTSS_COLORARG1, D3DTA_TEMP);
            device->SetTextureStageState(2, D3DTSS_COLORARG2, D3DTA_CURRENT);
            device->SetTextureStageState(2, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
            device->SetTextureStageState(2, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
            device->SetTextureStageState(3, D3DTSS_COLOROP, D3DTOP_DISABLE);
            softStages = true;
        } else
        // A car's paint: the second stage multiplies the painted meshes by the tint.
        if (g_paintTintOn) {
            const bool paint = mesh.texture.find("_paint") != std::string::npos;
            IDirect3DTexture9* baked = paint && g_bakeTints ? BakedTint(device, mesh.texture, g_paintTint) : nullptr;
            if (baked) {
                device->SetTexture(0, baked);
                bound = baked;
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            } else if (paint) {
                // The factor is half the tint and the stage doubles it, so a repaint
                // brighter than the model's own paint still gets there.
                const DWORD t = 0xFF000000u | (static_cast<DWORD>(g_paintTint[0] * 127.5f) << 16) |
                                (static_cast<DWORD>(g_paintTint[1] * 127.5f) << 8) | static_cast<DWORD>(g_paintTint[2] * 127.5f);
                device->SetRenderState(D3DRS_TEXTUREFACTOR, t);
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE2X);
                device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
                device->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
            } else {
                device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
            }
        }
        const bool skinned = mesh.skin >= 0 && posed && posed->meshes.size() > static_cast<size_t>(mi) &&
                             posed->meshes[mi].size() == mesh.vertices.size();
        const gta2::Mat4 world = skinned ? placement : Multiply(worlds[i], placement);
        D3DMATRIX m;
        memcpy(&m, world.m, sizeof(m));
        device->SetTransform(D3DTS_WORLD, &m);
        const ModelVertex* verts = skinned ? posed->meshes[mi].data() : mesh.vertices.data();
        QueryPerformanceCounter(&t1);
        // Rigid: the mesh's own managed buffers. Skinned: the index buffer from
        // those, the vertices from the per-pose dynamic buffer.
        MeshBuffers* b = BuffersFor(device, mesh, false, mesh.vertices.data(), 0);
        IDirect3DVertexBuffer9* vb = b ? b->vb : nullptr;
        if (b && skinned) vb = SkinBufferFor(device, mesh, verts, posed->id);
        QueryPerformanceCounter(&t2);
        g_modelStats[1] += ModelMs(t1, t2);
        if (b && vb) {
            device->SetStreamSource(0, vb, 0, sizeof(ModelVertex));
            device->SetIndices(b->ib);
            device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(mesh.vertices.size()), 0,
                                         static_cast<UINT>(mesh.indices.size() / 3));
            streams = true;
        } else {
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(mesh.vertices.size()),
                                           static_cast<UINT>(mesh.indices.size() / 3), mesh.indices.data(),
                                           D3DFMT_INDEX32, verts, sizeof(ModelVertex));
        }
    }
    if (streams) {
        // Leave the device as the UP draws elsewhere expect it: no stream bound.
        device->SetStreamSource(0, nullptr, 0, 0);
        device->SetIndices(nullptr);
    }
    if (carSurfSaved) {
        device->SetMaterial(&carSurfMaterial);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, carSurfState[0]);
        device->SetRenderState(D3DRS_SRCBLEND, carSurfState[1]);
        device->SetRenderState(D3DRS_DESTBLEND, carSurfState[2]);
        device->SetRenderState(D3DRS_ZWRITEENABLE, carSurfState[3]);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, carSurfState[4]);
    }
    if (softStages) ResetSoftStages(device);
    if (g_paintTintOn || g_nodeTintOn || (g_zoneOn && model.pedZones)) device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    QueryPerformanceCounter(&t2);
    g_modelStats[2] += ModelMs(t0, t2);
    ++g_drawn;
    {
        // FIX-PERF-VSWITCH: what a model's first draw cost (its textures, buffers and any wait on the
        // driver's queue), once per model, for the first-switch hitch.
        static std::set<const Model*> timed;
        if (!g_modelGhost && timed.size() < 160 && timed.insert(&model).second) {
            const double ms = ModelMs(t0, t2);
            if (ms > 4.0) Log("model first draw: %s %.1f ms (pose %.1f, buffers %.1f, %d new textures %.1f ms)", model.name.c_str(), ms,
                              ModelMs(t0, tPosed), g_modelStats[1] - probeFill0, g_texNew - probeTexN0, g_texNewMs - probeTex0);
        }
    }
}

// A model's vertex and index buffers, created, filled and drawn once with
// colour and depth writes off: the managed buffers reach the GL driver now
// (their first real draw cost 550 ms for the props at the first view switch).
void WarmModelBuffers(IDirect3DDevice9* device, const Model& model) {
    DWORD colorWrite = 0xF, zWrite = TRUE, zEnable = TRUE, fvf = 0;
    device->GetRenderState(D3DRS_COLORWRITEENABLE, &colorWrite);
    device->GetRenderState(D3DRS_ZWRITEENABLE, &zWrite);
    device->GetRenderState(D3DRS_ZENABLE, &zEnable);
    device->GetFVF(&fvf);
    device->SetRenderState(D3DRS_COLORWRITEENABLE, 0);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_ZENABLE, FALSE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);   // ModelVertex, as the callers set it
    device->SetTexture(0, nullptr);
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    bool streams = false;
    for (const ModelMesh& mesh : model.meshes) {
        if (mesh.indices.size() < 3) continue;
        if (MeshBuffers* b = BuffersFor(device, mesh, false, mesh.vertices.data(), 0)) {
            device->SetStreamSource(0, b->vb, 0, sizeof(ModelVertex));
            device->SetIndices(b->ib);
            device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(mesh.vertices.size()), 0,
                                         static_cast<UINT>(mesh.indices.size() / 3));
            streams = true;
        }
    }
    if (streams) {
        device->SetStreamSource(0, nullptr, 0, 0);
        device->SetIndices(nullptr);
    }
    device->SetFVF(fvf);
    device->SetRenderState(D3DRS_COLORWRITEENABLE, colorWrite);
    device->SetRenderState(D3DRS_ZWRITEENABLE, zWrite);
    device->SetRenderState(D3DRS_ZENABLE, zEnable);
}

size_t g_warmModelCursor = 0;   // unused since FIX-PERF-VSWITCH (kept for ModelsReleaseDevice)

// FIX-PERF-VSWITCH: the warm-up as an ordered list of steps, a model at a time (its textures,
// then its buffers), in the order the street views need them: the street furniture and map
// objects first (all of them are in the first street frame), then the people (the crowd round
// the player is), then the cars (the traffic arrives over seconds). Before, every texture of
// every model came first in manifest order (the 70 cars before the people), then every
// model's buffers: 30-40 s of a level, so the first V usually found the people cold.
struct WarmStep {
    uint32_t model;      // index into g_models
    int8_t kind;         // 0 texture (file), 1 the model's buffers, 2 spare skin buffers
    std::string file;
};
std::vector<WarmStep> g_warmSteps;
size_t g_warmStep = 0;
std::vector<uint32_t> g_warmBumped;      // models asked for first (ModelsWarmFirst), not yet queued
IDirect3DQuery9* g_warmQuery = nullptr;  // the last batch's end, so the next waits for the driver
bool g_warmQueryPending = false;
LARGE_INTEGER g_warmStart = {};
int g_warmDoneTextures = 0;
size_t g_warmDoneBytes = 0;
UINT g_skinSpareBytes = 0;               // the largest skinned mesh's vertex bytes (spare skin buffers)
int g_skinSpares = 0;

int WarmGroup(const Model& m) {
    const std::string& n = m.name;
    if (!n.empty() && n[0] >= '0' && n[0] <= '9') return 2;   // 0NN_* cars
    if (n.compare(0, 5, "human") == 0 || n.compare(0, 9, "character") == 0 || m.skinned) return 1;
    return 0;
}

void AppendModelSteps(uint32_t index, std::vector<char>* queued) {
    if (index >= g_models.size() || (*queued)[index]) return;
    (*queued)[index] = 1;
    const Model& m = g_models[index];
    for (const ModelMesh& mesh : m.meshes)
        if (!mesh.texture.empty()) g_warmSteps.push_back({index, 0, mesh.texture});
    g_warmSteps.push_back({index, 1, std::string()});
}

void BuildWarmList() {
    if (!g_warmSteps.empty() || g_models.empty()) return;
    std::vector<char> queued(g_models.size(), 0);
    for (int group = 0; group < 3; ++group) {
        for (uint32_t i = 0; i < g_models.size(); ++i) {
            if (WarmGroup(g_models[i]) != group) continue;
            AppendModelSteps(i, &queued);
            if (group == 1 && g_models[i].skinned) {
                for (const ModelMesh& mesh : g_models[i].meshes)
                    if (mesh.skin >= 0) g_skinSpareBytes = (std::max)(g_skinSpareBytes, static_cast<UINT>(mesh.vertices.size() * sizeof(ModelVertex)));
            }
        }
        // The spare skin buffers once the people's own resources are up (before the cars).
        if (group == 1 && g_skinSpareBytes) g_warmSteps.push_back({0, 2, std::string()});
    }
    // The texture files in the same order for the reader thread, each once.
    std::set<std::string> seen;
    for (const WarmStep& st : g_warmSteps)
        if (st.kind == 0 && seen.insert(st.file).second) g_warmList.push_back(st.file);
}

void StartTexturePrefetch() {
    if (g_prefetchStarted || g_models.empty()) return;
    BuildWarmList();
    InitializeCriticalSection(&g_prefetchLock);
    g_prefetchList = g_warmList;
    if (HANDLE thread = CreateThread(nullptr, 0, PrefetchThread, nullptr, 0, nullptr)) {
        SetThreadPriority(thread, THREAD_PRIORITY_BELOW_NORMAL);
        CloseHandle(thread);
        InterlockedExchange(&g_prefetchStarted, 1);
        Log("models: reading %zu model textures ahead on a thread of their own", g_prefetchList.size());
    } else {
        DeleteCriticalSection(&g_prefetchLock);
    }
}

void ModelsWarmFirst(const Model* model) {
    if (!model || !g_loaded) return;
    for (uint32_t i = 0; i < g_models.size(); ++i)
        if (&g_models[i] == model) { g_warmBumped.push_back(i); return; }
}

// Spare skin buffers, made and written once ahead of the first street frame: the first lock of a
// new dynamic buffer waits for everything the driver has queued (285 ms for the first person drawn
// at the first V, out/vsw_probe3), so the crowd's first poses take these instead (SkinBufferFor).
constexpr int kSkinSpares = 40;
void MakeSkinSpares(IDirect3DDevice9* device, int count) {
    if (!g_skinSpareBytes) return;
    std::vector<uint8_t> zero(g_skinSpareBytes, 0);
    for (int k = 0; k < count && g_skinSpares < kSkinSpares; ++k) {
        IDirect3DVertexBuffer9* vb = nullptr;
        if (FAILED(device->CreateVertexBuffer(g_skinSpareBytes, D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &vb, nullptr)) || !vb) {
            g_skinSpares = kSkinSpares;
            return;
        }
        void* data = nullptr;
        if (SUCCEEDED(vb->Lock(0, g_skinSpareBytes, &data, D3DLOCK_DISCARD)) && data) {
            memcpy(data, zero.data(), g_skinSpareBytes);
            vb->Unlock();
        }
        g_skinFree.emplace(g_skinSpareBytes, vb);
        ++g_skinSpares;
    }
}

// FIX-PERF-VSWITCH: a street prop, the player's avatar (zone tints) and a car (paint tint, soft
// paint when on) drawn once with the caller's states (the ghost street frame's lighting and fog,
// world_view.cpp), so the driver builds the GL programs those draws need before the first V.
// The caller has pointed the device at targets nothing shows.
void ModelsGhostDraws(IDirect3DDevice9* device, const gta2::Mat4& at) {
    if (!device || !g_loaded || g_models.empty()) return;
    g_modelGhost = true;
    const double stats[6] = {g_modelStats[0], g_modelStats[1], g_modelStats[2], g_modelStats[3], g_modelStats[4], g_modelStats[5]};
    const int drawn = g_drawn;
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    if (const Model* lamp = ModelForProp("lamp")) ModelDraw(device, *lamp, at, nullptr, 0.0f);
    if (const Model* hero = ModelForPedestrian()) {
        const float top[3] = {1.0f, 1.0f, 1.0f}, bottom[3] = {1.0f, 1.0f, 1.0f}, hair[3] = {1.0f, 1.0f, 1.0f};
        ModelSetZoneTints(top, bottom, hair);
        ModelDraw(device, *hero, at, hero->animations.empty() ? nullptr : &hero->animations.front(), 0.0f);
        ModelSetZoneTints(nullptr, nullptr, nullptr);
        ModelDraw(device, *hero, at, hero->animations.empty() ? nullptr : &hero->animations.front(), 0.0f);
    }
    for (const Model& m : g_models) {
        if (WarmGroup(m) != 2) continue;
        const float paint[3] = {1.0f, 1.0f, 1.0f};
        ModelSetPaintTint(paint);
        ModelDraw(device, m, at, nullptr, 0.0f);
        ModelSetPaintTint(nullptr);
        ModelDraw(device, m, at, nullptr, 0.0f);
        break;
    }
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    for (int i = 0; i < 6; ++i) g_modelStats[i] = stats[i];
    g_drawn = drawn;
    g_modelGhost = false;
}

// Every model texture created and uploaded, and every model's buffers, ahead of their first use,
// a model at a time in the order above. Bounded by time rather than by count (PERF-2: two
// textures a frame cost 5 ms typically and up to 98 ms in one frame): steps are taken while the
// frame's warm-up has used less than budgetMs, at most `perFrame` textures and a byte budget,
// and a texture whose file the reader thread has not delivered yet waits for a later frame.
// FIX-PERF-VSWITCH: and never ahead of the driver. The budget counted only the time to queue the
// work, not the driver's time to do it; the queue grew through the classic view and whatever
// frame next waited on the driver paid for all of it (the first V). An event query after each
// batch holds the next batch until the driver has finished the last.
int ModelsWarmTextures(IDirect3DDevice9* device, int perFrame, double kWarmBudgetMs) {
    if (!device || !g_loaded) return 0;
    BuildWarmList();
    if (!g_prefetchSoften && g_softPaintSetting && !RemixApiAvailable() && SoftPaintCaps(device)) InterlockedExchange(&g_prefetchSoften, 1);
    const int remaining = static_cast<int>(g_warmSteps.size() - (std::min)(g_warmStep, g_warmSteps.size())) +
                          static_cast<int>(g_warmBumped.size());
    if (remaining == 0) return 0;
    if (!g_warmStart.QuadPart) QueryPerformanceCounter(&g_warmStart);
    if (g_warmQueryPending && g_warmQuery) {
        const HRESULT r = g_warmQuery->GetData(nullptr, 0, 0);
        if (r == S_FALSE) return remaining;   // the driver is still on the last batch
        g_warmQueryPending = false;
    }
    // A model asked for first: its steps go in front of the queue (each step is idempotent, so
    // the ones met again later in the queue cost a map lookup).
    if (!g_warmBumped.empty()) {
        std::vector<WarmStep> front;
        for (uint32_t i : g_warmBumped) {
            const Model& m = g_models[i];
            for (const ModelMesh& mesh : m.meshes)
                if (!mesh.texture.empty() && !g_textures.count(mesh.texture)) front.push_back({i, 0, mesh.texture});
            front.push_back({i, 1, std::string()});
        }
        g_warmBumped.clear();
        g_warmSteps.insert(g_warmSteps.begin() + static_cast<std::ptrdiff_t>((std::min)(g_warmStep, g_warmSteps.size())), front.begin(), front.end());
    }
    const size_t byteBudget = perFrame >= 8 ? (12u << 20) : (3u << 20);
    LARGE_INTEGER t0, now;
    QueryPerformanceCounter(&t0);
    int done = 0;
    size_t bytes = 0;
    bool issued = false;
    while (g_warmStep < g_warmSteps.size() && done < perFrame && bytes < byteBudget) {
        const WarmStep& st = g_warmSteps[g_warmStep];
        if (st.kind == 0) {
            if (!g_textures.count(st.file)) {
                if (!PrefetchReady(st.file)) break;   // the reader's next; not this frame
                IDirect3DTexture9* tex = TextureFor(device, st.file);
                WarmTexture(device, tex);
                D3DSURFACE_DESC desc = {};
                if (tex && SUCCEEDED(tex->GetLevelDesc(0, &desc))) bytes += static_cast<size_t>(desc.Width) * desc.Height * 4;
                ++done;
                ++g_warmDoneTextures;
                issued = true;
            }
        } else if (st.kind == 1) {
            const Model& m = g_models[st.model];
            bool cold = false;
            for (const ModelMesh& mesh : m.meshes)
                if (mesh.indices.size() >= 3 && !g_buffers.count(&mesh)) { cold = true; break; }
            if (cold) {
                WarmModelBuffers(device, m);
                for (const ModelMesh& mesh : m.meshes) bytes += mesh.vertices.size() * sizeof(ModelVertex) + mesh.indices.size() * 4;
                issued = true;
            }
        } else {
            if (g_skinSpares < kSkinSpares) {
                MakeSkinSpares(device, 8);
                bytes += static_cast<size_t>(g_skinSpareBytes) * 8;
                issued = true;
                if (g_skinSpares < kSkinSpares) { QueryPerformanceCounter(&now); if (ModelMs(t0, now) > kWarmBudgetMs) break; continue; }
            }
        }
        ++g_warmStep;
        QueryPerformanceCounter(&now);
        if (ModelMs(t0, now) > kWarmBudgetMs) break;
    }
    g_warmDoneBytes += bytes;
    if (issued) {
        if (!g_warmQuery && FAILED(device->CreateQuery(D3DQUERYTYPE_EVENT, &g_warmQuery))) g_warmQuery = nullptr;
        if (g_warmQuery && SUCCEEDED(g_warmQuery->Issue(D3DISSUE_END))) g_warmQueryPending = true;
    }
    const int left = static_cast<int>(g_warmSteps.size() - (std::min)(g_warmStep, g_warmSteps.size()));
    // Progress, a line per group finished and at the end: how far the warm-up was at the first V.
    static int lastGroup = 0;
    int group = 3;   // the lowest group with steps still to do
    for (size_t k = g_warmStep; k < g_warmSteps.size() && group > lastGroup; ++k) group = (std::min)(group, WarmGroup(g_models[g_warmSteps[k].model]));
    if (group > lastGroup) {
        QueryPerformanceCounter(&now);
        static const char* kNames[] = {"street furniture and objects", "people", "cars"};
        for (int g = lastGroup; g < group && g < 3; ++g)
            Log("models: warm-up: %s ready, %.1f s after it began (%d textures, %zu MB so far)", kNames[g], ModelMs(g_warmStart, now) / 1000.0,
                g_warmDoneTextures, g_warmDoneBytes >> 20);
        lastGroup = group;
    }
    return left;
}

bool ModelNodeWorld(const Model& model, const char* name, const ModelAnimation* animation, float time,
                    const ModelAnimation* second, float secondTime, float weight, gta2::Mat4* out) {
    int index = -1;
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        if (strcmp(model.nodes[i].name, name) == 0) { index = static_cast<int>(i); break; }
    }
    if (index < 0) return false;
    if (!second || weight <= 1e-3f) { second = nullptr; secondTime = 0.0f; weight = 0.0f; }
    std::vector<gta2::Mat4> worlds;
    NodeWorldsBlend(model, animation, time, second, secondTime, weight, &worlds);
    *out = worlds[static_cast<size_t>(index)];
    return true;
}

const ModelAnimation* ModelSpinAnimation(const Model& model, const char* nodeSubstring, int axis, float period) {
    std::string animName = std::string("spin:") + nodeSubstring;
    if (const ModelAnimation* have = model.Animation(animName.c_str())) return have;
    std::vector<int> nodes;
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        if (strstr(model.nodes[i].name, nodeSubstring)) nodes.push_back(static_cast<int>(i));
    }
    if (nodes.empty()) return nullptr;
    // The models are owned by the store; a synthetic clip is as much part of
    // the model as an imported one, so it is added in place.
    Model& m = const_cast<Model&>(model);
    // Clips are held by pointer (map_objects keeps the main rotor's while it asks
    // for the tail's): the vector must not move when a second one is added.
    if (m.animations.capacity() < m.animations.size() + 1) m.animations.reserve(m.animations.size() + 8);
    ModelAnimation anim;
    anim.name = animName;
    anim.length = (std::max)(period, 0.02f);
    for (int n : nodes) {
        ModelChannel ch;
        ch.node = n;
        ch.path = 1;
        // Eight keys round the circle, composed over the node's own rotation,
        // so the slerp between neighbours stays well inside a quarter turn.
        const float* base = model.nodes[static_cast<size_t>(n)].rotation;
        for (int k = 0; k <= 8; ++k) {
            const float a = 6.2831853f * static_cast<float>(k) / 8.0f;
            float spin[4] = {0, 0, 0, std::cos(0.5f * a)};
            spin[axis] = std::sin(0.5f * a);
            // q = base * spin (row-vector order: the spin is applied first, in
            // the node's own frame, then the node's rest rotation).
            const float bx = base[0], by = base[1], bz = base[2], bw = base[3];
            const float sx = spin[0], sy = spin[1], sz = spin[2], sw = spin[3];
            const float q[4] = {bw * sx + bx * sw + by * sz - bz * sy,
                                bw * sy - bx * sz + by * sw + bz * sx,
                                bw * sz + bx * sy - by * sx + bz * sw,
                                bw * sw - bx * sx - by * sy - bz * sz};
            ch.times.push_back(anim.length * static_cast<float>(k) / 8.0f);
            for (float v : q) ch.values.push_back(v);
        }
        anim.channels.push_back(ch);
    }
    m.animations.push_back(anim);
    return &m.animations.back();
}

void ModelsReleaseDevice() {
    // The player copies first; one that fell back to the shared texture is not its own.
    for (auto& t : g_playerCopies) {
        auto shared = g_textures.find(t.first);
        if (t.second && (shared == g_textures.end() || shared->second != t.second)) t.second->Release();
    }
    g_playerCopies.clear();
    for (auto& t : g_textures) if (t.second) t.second->Release();
    g_textures.clear();
    for (auto& b : g_skinBuffers) if (b.second.vb) b.second.vb->Release();
    g_skinBuffers.clear();
    for (auto& b : g_skinFree) b.second->Release();
    g_skinFree.clear();
    g_warmCursor = 0;
    g_warmModelCursor = 0;
    g_warmStep = 0;
    g_skinSpares = 0;
    if (g_warmQuery) { g_warmQuery->Release(); g_warmQuery = nullptr; }
    g_warmQueryPending = false;
    for (auto& b : g_buffers) {
        if (b.second.vb) b.second.vb->Release();
        if (b.second.ib) b.second.ib->Release();
    }
    g_buffers.clear();
}

}  // namespace gta2dx9
