#include "model_store.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <array>
#include <map>

#include "log.h"

namespace gta2dx9 {
namespace {

std::vector<Model> g_models;
std::map<std::string, size_t> g_byName;
std::vector<std::string> g_carDefault;    // cycled by sprite number
std::map<int, std::string> g_carBySprite;
std::map<int, std::string> g_carByModel;   // by the game's vehicle model number
float g_paintTint[3] = {1.0f, 1.0f, 1.0f};
bool g_paintTintOn = false;

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
};
std::vector<PedType> g_pedTypes;
int g_pedTypeByRemap[64];                 // index into g_pedTypes, -1 none
float g_pedRemapColour[64][3];            // the remap's clothing colour (0-255), 0 when unknown
std::map<int, int> g_pedRemapByPalette;   // physical palette -> remap, from the loaded style
std::map<std::string, std::string> g_props;
std::vector<gta2::Vec3> g_mapLamps;
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
            done[i] = true;
        }
    }
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

// Poses a skinned mesh on the CPU: every vertex blended by its four joints.
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

IDirect3DTexture9* TextureFor(IDirect3DDevice9* device, const std::string& file) {
    if (file.empty()) return nullptr;
    auto it = g_textures.find(file);
    if (it != g_textures.end()) return it->second;
    IDirect3DTexture9* texture = nullptr;
    std::vector<uint8_t> tga;
    if (ReadAll(g_folder + "\\" + file, &tga) && tga.size() > 18 && tga[2] == 2 && tga[16] == 32) {
        const int w = tga[12] | (tga[13] << 8), h = tga[14] | (tga[15] << 8);
        const bool topDown = (tga[17] & 0x20) != 0;
        if (w > 0 && h > 0 && tga.size() >= 18u + static_cast<size_t>(w) * h * 4 &&
            SUCCEEDED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) {
            g_textureBytes += static_cast<size_t>(w) * h * 4;
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

}  // namespace

const ModelAnimation* Model::Animation(const char* name) const {
    for (const ModelAnimation& a : animations) if (a.name == name) return &a;
    return nullptr;
}

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
        for (const ModelMesh& mesh : model.meshes) if (mesh.texture.find("_paint") != std::string::npos) model.splitPaint = true;
        g_byName[name] = g_models.size();
        g_models.push_back(std::move(model));
        const Model& m = g_models.back();
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
}

bool ModelsAvailable() { return !g_models.empty(); }

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

void ModelSetPaintTint(const float* rgb) {
    g_paintTintOn = rgb != nullptr;
    if (rgb) for (int i = 0; i < 3; ++i) g_paintTint[i] = (std::max)(0.0f, (std::min)(2.0f, rgb[i]));
}

const Model* ModelForProp(const char* role) {
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

void SetMapLamps(const std::vector<gta2::Vec3>& lamps) { g_mapLamps = lamps; }
const std::vector<gta2::Vec3>& MapLamps() { return g_mapLamps; }

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
void ModelsBeginFrame() { g_drawn = 0; for (double& v : g_modelStats) v = 0.0; }

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
    float time = -1.0f, secondTime = -1.0f, weight = 0.0f;
    bool operator==(const PoseKey& o) const {
        return model == o.model && animation == o.animation && second == o.second && std::fabs(time - o.time) < 1e-4f &&
               std::fabs(secondTime - o.secondTime) < 1e-4f && std::fabs(weight - o.weight) < 1e-3f;
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
unsigned g_skinClock = 0;
constexpr size_t kSkinBuffersMax = 96;

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
        if (oldest->second.vb) oldest->second.vb->Release();
        g_skinBuffers.erase(oldest);
    }
    IDirect3DVertexBuffer9* vb = nullptr;
    const UINT vbytes = static_cast<UINT>(mesh.vertices.size() * sizeof(ModelVertex));
    if (FAILED(device->CreateVertexBuffer(vbytes, D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &vb, nullptr)) ||
        !vb) {
        return nullptr;
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
        if (FAILED(device->CreateVertexBuffer(vbytes, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &b.vb, nullptr)) ||
            FAILED(device->CreateIndexBuffer(ibytes, D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_MANAGED, &b.ib,
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
        if (FAILED(b.ib->Lock(0, ibytes, &idata, 0)) || !idata) {
            b.failed = true;
            return nullptr;
        }
        memcpy(idata, mesh.indices.data(), ibytes);
        b.ib->Unlock();
        if (!FillVertices(b.vb, verts, mesh.vertices.size())) {
            b.failed = true;
            return nullptr;
        }
        b.pose = pose;
    } else if (skinned && b.pose != pose) {
        // The managed buffer keeps the first pose it was given; later poses come
        // from SkinBufferFor (see there), so this rewrite is never reached.
        if (!FillVertices(b.vb, verts, mesh.vertices.size())) return nullptr;
        b.pose = pose;
    }
    return &b;
}

// The cached pose for a key, skinned now if it was not there.
const PosedCache& PoseFor(const Model& model, const PoseKey& key, const std::vector<gta2::Mat4>& worlds) {
    ++g_poseClock;
    for (PosedCache& p : g_poses) {
        if (p.key == key) {
            p.used = g_poseClock;
            return p;
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
        posed = &PoseFor(model, key, worlds);
    }
    QueryPerformanceCounter(&t1);
    g_modelStats[0] += ModelMs(t0, t1);
    g_modelStats[3] += 1.0;
    if (model.skinned) g_modelStats[4] += 1.0;
    IDirect3DTexture9* bound = nullptr;
    bool first = true;
    bool streams = false;
    for (size_t i = 0; i < model.nodes.size(); ++i) {
        const int mi = model.nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& mesh = model.meshes[mi];
        if (mesh.indices.size() < 3) continue;
        IDirect3DTexture9* texture = TextureFor(device, mesh.texture);
        if (first || texture != bound) {
            device->SetTexture(0, texture);
            bound = texture;
            first = false;
        }
        // A car's paint: the second stage multiplies the painted meshes by the tint.
        if (g_paintTintOn) {
            const bool paint = mesh.texture.find("_paint") != std::string::npos;
            if (paint) {
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
    if (g_paintTintOn) device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    QueryPerformanceCounter(&t2);
    g_modelStats[2] += ModelMs(t0, t2);
    ++g_drawn;
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

size_t g_warmModelCursor = 0;

int ModelsWarmTextures(IDirect3DDevice9* device, int perFrame) {
    if (!device || !g_loaded) return 0;
    if (g_warmList.empty()) {
        for (const Model& m : g_models) {
            for (const ModelMesh& mesh : m.meshes) {
                if (!mesh.texture.empty() && std::find(g_warmList.begin(), g_warmList.end(), mesh.texture) == g_warmList.end()) {
                    g_warmList.push_back(mesh.texture);
                }
            }
        }
    }
    int done = 0;
    while (g_warmCursor < g_warmList.size() && done < perFrame) {
        WarmTexture(device, TextureFor(device, g_warmList[g_warmCursor]));
        ++g_warmCursor;
        ++done;
    }
    // Then the meshes, one model a frame.
    if (done == 0 && g_warmModelCursor < g_models.size()) {
        WarmModelBuffers(device, g_models[g_warmModelCursor]);
        ++g_warmModelCursor;
        ++done;
    }
    return static_cast<int>(g_warmList.size() - g_warmCursor) + static_cast<int>(g_models.size() - g_warmModelCursor);
}

void ModelsReleaseDevice() {
    for (auto& t : g_textures) if (t.second) t.second->Release();
    g_textures.clear();
    for (auto& b : g_skinBuffers) if (b.second.vb) b.second.vb->Release();
    g_skinBuffers.clear();
    g_warmCursor = 0;
    g_warmModelCursor = 0;
    for (auto& b : g_buffers) {
        if (b.second.vb) b.second.vb->Release();
        if (b.second.ib) b.second.ib->Release();
    }
    g_buffers.clear();
}

}  // namespace gta2dx9
