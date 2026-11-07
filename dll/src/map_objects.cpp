#include "map_objects.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "game_access.h"
#include "log.h"
#include "live_geometry.h"
#include "model_store.h"

namespace gta2dx9 {
namespace {
double NowSeconds() {
    static LARGE_INTEGER frequency = {};
    if (!frequency.QuadPart) QueryPerformanceFrequency(&frequency);
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    return static_cast<double>(now.QuadPart) / static_cast<double>(frequency.QuadPart);
}
}  // namespace
namespace {
bool g_loaded = false;
std::map<uint32_t, const Model*> g_byKey;   // (base << 16 | number) -> model
std::map<uint32_t, int> g_animByKey;        // 1 spin + float (pickups), 2 rotor
std::map<const Model*, int> g_animByModel;
std::map<uint32_t, float> g_yawByKey;       // extra yaw, degrees, from the manifest ("objects_yaw")
std::set<uint32_t> g_logged;

uint32_t Key(int base, int number) { return (static_cast<uint32_t>(base) << 16) | (static_cast<uint32_t>(number) & 0xFFFF); }

// The manifest's "objects": {"5:12": "traffic_cone", ...} block, read once the
// models are there. Hand parsing like the rest of the manifest reader.
void LoadOnce() {
    if (g_loaded) return;
    g_loaded = true;
    const std::string path = std::string(ModelsFolder()) + "\\manifest.json";
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return;
    std::string text;
    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) text.append(buf, n);
    fclose(f);
    auto readMap = [&](const char* key, auto&& take) {
        const size_t at = text.find(std::string("\"") + key + "\"");
        if (at == std::string::npos) return;
        const size_t open = text.find('{', at), close = text.find('}', open);
        if (open == std::string::npos || close == std::string::npos) return;
        const std::string block = text.substr(open + 1, close - open - 1);
        size_t p = 0;
        while ((p = block.find('"', p)) != std::string::npos) {
            const size_t q = block.find('"', p + 1);
            if (q == std::string::npos) break;
            const std::string k = block.substr(p + 1, q - p - 1);
            const size_t colon = block.find(':', q);
            if (colon == std::string::npos) break;
            size_t v0 = block.find_first_not_of(" \t\r\n", colon + 1);
            std::string v;
            if (v0 != std::string::npos && block[v0] == '"') {
                const size_t v1 = block.find('"', v0 + 1);
                v = block.substr(v0 + 1, v1 - v0 - 1);
                p = v1 + 1;
            } else {
                const size_t v1 = block.find_first_of(",}\r\n", v0);
                v = block.substr(v0, v1 == std::string::npos ? std::string::npos : v1 - v0);
                p = v1 == std::string::npos ? block.size() : v1;
            }
            int base = 0, number = 0;
            if (sscanf(k.c_str(), "%d:%d", &base, &number) == 2) take(Key(base, number), v);
        }
    };
    int mapped = 0;
    readMap("objects", [&](uint32_t key, const std::string& name) {
        if (const Model* m = ModelByName(name.c_str())) { g_byKey[key] = m; ++mapped; }
        else Log("objects: manifest names model %s, which is not loaded", name.c_str());
    });
    readMap("objects_yaw", [&](uint32_t key, const std::string& v) { g_yawByKey[key] = static_cast<float>(atof(v.c_str())); });
    // "objects_anim": {"4:26": "spin"}: a pickup turns slowly about its axis and
    // floats a hand above the ground, the way the game's own frames suggest.
    readMap("objects_anim", [&](uint32_t key, const std::string& v) { g_animByKey[key] = v == "spin" ? 1 : v == "rotor" ? 2 : 0; });
    for (const auto& kv : g_animByKey) {
        auto it = g_byKey.find(kv.first);
        if (it != g_byKey.end()) g_animByModel[it->second] = kv.second;
    }
    Log("objects: %d sprite(s) mapped to models", mapped);
}
}  // namespace

const Model* MapObjectModel(const void* spriteObject, const LiveGeometry::Vertex* local, int corners,
                            const gta2::Mat4& objectToWorld) {
    if (!spriteObject || corners != 4 || !ModelsAvailable()) return nullptr;
    const uint8_t* object = static_cast<const uint8_t*>(spriteObject);
    const int32_t base = *reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase);
    const int number = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
    if (base == game::kSpriteBaseCar || base == game::kSpriteBasePed || base < 0 || base > 15) return nullptr;
    LoadOnce();
    const uint32_t key = Key(base, number);
    if (g_logged.size() < 600 && g_logged.insert(key).second) {
        // The quad's extent along its two edges, in tiles.
        const float ex = std::sqrt((local[1].x - local[0].x) * (local[1].x - local[0].x) +
                                   (local[1].y - local[0].y) * (local[1].y - local[0].y) +
                                   (local[1].z - local[0].z) * (local[1].z - local[0].z));
        const float ey = std::sqrt((local[3].x - local[0].x) * (local[3].x - local[0].x) +
                                   (local[3].y - local[0].y) * (local[3].y - local[0].y) +
                                   (local[3].z - local[0].z) * (local[3].z - local[0].z));
        // Renderer frame: x east, y up, z north; the game's map y runs the other way.
        Log("object sprite: base %d number %d, quad %.2f x %.2f tiles, at x=%.1f y=%.1f (map) height %.2f%s", base, number, ex, ey,
            objectToWorld.m[3][0], 255.0f - objectToWorld.m[3][2], objectToWorld.m[3][1], g_byKey.count(key) ? " (model)" : "");
    }
    auto it = g_byKey.find(key);
    return it == g_byKey.end() ? nullptr : it->second;
}

std::vector<PropFootprint> g_objectFootprints;
const std::vector<PropFootprint>& MapObjectFootprints() { return g_objectFootprints; }

void MapObjectsDraw(IDirect3DDevice9* device, const std::vector<LiveGeometry::SpriteType>& sprites) {
    g_objectFootprints.clear();
    for (const LiveGeometry::SpriteType& s : sprites) {
        if (!s.objectModel) continue;
        const Model& model = *s.objectModel;
        // Fit: the model's footprint length onto the quad's longer edge, standing
        // on the quad's plane, turned to follow the quad's first edge.
        float fx = s.local[1].x - s.local[0].x, fz = s.local[1].z - s.local[0].z;
        float ex = std::sqrt(fx * fx + fz * fz);
        float sx = s.local[3].x - s.local[0].x, sz = s.local[3].z - s.local[0].z;
        float ey = std::sqrt(sx * sx + sz * sz);
        if (ex < 1e-4f || ey < 1e-4f) continue;
        // The sprite's "forward" is down the page (+v): the edge from corner 0 to 3.
        float dirX = sx / ey, dirZ = sz / ey;
        const float longer = (std::max)(ex, ey);
        const float modelLong = (std::max)((std::max)(model.Length(), model.Width()), 0.01f);
        const float scale = longer / modelLong;
        const float f = model.forward;
        gta2::Mat4 fit;
        fit.m[0][0] = dirZ * scale * f;  fit.m[0][1] = 0.0f;  fit.m[0][2] = -dirX * scale * f;
        fit.m[1][0] = 0.0f;              fit.m[1][1] = scale; fit.m[1][2] = 0.0f;
        fit.m[2][0] = dirX * scale * f;  fit.m[2][1] = 0.0f;  fit.m[2][2] = dirZ * scale * f;
        // The quad's centre is where the model's origin goes (its origin is the
        // sprite centre on the ground, by the generator's convention).
        const float cx = 0.25f * (s.local[0].x + s.local[1].x + s.local[2].x + s.local[3].x);
        const float cz = 0.25f * (s.local[0].z + s.local[1].z + s.local[2].z + s.local[3].z);
        const float cy = 0.25f * (s.local[0].y + s.local[1].y + s.local[2].y + s.local[3].y);
        {
            // World position of the quad's centre; nothing drawn behind the camera.
            const gta2::Mat4& w = s.objectToWorld;
            const float wx = cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0];
            const float wy = cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1];
            const float wz = cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2];
            if (BehindView(wx, wy, wz, 1.5f)) continue;
        }
        fit.m[3][0] = cx; fit.m[3][1] = cy - model.boundsMin.y * scale; fit.m[3][2] = cz; fit.m[3][3] = 1.0f;
        {
            // A standing object (a pickup floats and is walked through): its
            // footprint, so a first-person eye inside a phone box is pushed out.
            auto anim = g_animByModel.find(&model);
            if (anim == g_animByModel.end() || anim->second != 1) {
                const gta2::Mat4& w = s.objectToWorld;
                const float wx = cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0];
                const float wy = cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1];
                const float wz = cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2];
                g_objectFootprints.push_back({wx, wy, wz, (std::min)(0.6f, (std::max)(0.12f, 0.5f * longer)), (std::max)(0.3f, model.Height() * scale)});
            }
        }
        {
            // Once per model: the quad and its placement, so a model that comes
            // out lying or oversized can be traced to its transform.
            static std::set<const Model*> g_fitLogged;
            if (g_fitLogged.size() < 64 && g_fitLogged.insert(&model).second) {
                const gta2::Mat4& w = s.objectToWorld;
                Log("object fit: %s quad %.2fx%.2f scale %.2f local0 %.2f,%.2f,%.2f local1 %.2f,%.2f,%.2f local3 %.2f,%.2f,%.2f | place rows (%.2f %.2f %.2f) (%.2f %.2f %.2f) (%.2f %.2f %.2f) at %.1f,%.1f,%.1f",
                    model.name.c_str(), ex, ey, scale, s.local[0].x, s.local[0].y, s.local[0].z, s.local[1].x, s.local[1].y, s.local[1].z,
                    s.local[3].x, s.local[3].y, s.local[3].z, w.m[0][0], w.m[0][1], w.m[0][2], w.m[1][0], w.m[1][1], w.m[1][2],
                    w.m[2][0], w.m[2][1], w.m[2][2], w.m[3][0], w.m[3][1], w.m[3][2]);
            }
        }
        // A pickup turns about its axis and floats, each on its own phase.
        auto anim = g_animByModel.find(&model);
        if (anim != g_animByModel.end() && anim->second == 1) {
            const double now = NowSeconds();
            const float phase = static_cast<float>((reinterpret_cast<uintptr_t>(s.object) >> 4) & 63) * 0.1f;
            const float ang = static_cast<float>(std::fmod(now * 1.3 + phase, 6.283185));
            const float ca = std::cos(ang), sa = std::sin(ang);
            gta2::Mat4 spun;
            for (int c = 0; c < 4; ++c) {
                spun.m[0][c] = ca * fit.m[0][c] + sa * fit.m[2][c];
                spun.m[1][c] = fit.m[1][c];
                spun.m[2][c] = -sa * fit.m[0][c] + ca * fit.m[2][c];
                spun.m[3][c] = fit.m[3][c];
            }
            spun.m[3][1] += 0.025f * std::sin(static_cast<float>(now) * 2.2f + phase);
            fit = spun;
        }
        gta2::Mat4 out;
        for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
            float acc = 0.0f;
            for (int k = 0; k < 4; ++k) acc += fit.m[r][k] * s.objectToWorld.m[k][c];
            out.m[r][c] = acc;
        }
        // The helicopter's rotors turn: a synthetic spin clip on the rotor nodes,
        // the main one about its mast, the tail one about its hub.
        const ModelAnimation* spin = nullptr;
        if (anim != g_animByModel.end() && anim->second == 2) {
            spin = ModelSpinAnimation(model, "rotor", 1, 0.14f);
            if (const ModelAnimation* tail = ModelSpinAnimation(model, "tailrotor", 0, 0.09f)) {
                // One clip carries both: the tail rotor's channel is appended to the
                // main one on first use.
                if (spin && spin != tail) {
                    Model& m = const_cast<Model&>(model);
                    for (ModelAnimation& a : m.animations) {
                        if (a.name == spin->name && a.channels.size() == 1 && tail->channels.size() == 1) {
                            // The tail rotor is also a "rotor" node, so it already spins about
                            // the mast axis in `spin`; replace that channel with the hub spin.
                            for (ModelChannel& ch : a.channels) {
                                if (ch.node == tail->channels[0].node) ch = tail->channels[0];
                            }
                        }
                    }
                }
            }
        }
        if (spin) {
            const float t = static_cast<float>(std::fmod(NowSeconds(), static_cast<double>(spin->length)));
            ModelDraw(device, model, out, spin, t);
        } else {
            ModelDraw(device, model, out, nullptr, 0.0f);
        }
    }
}
}  // namespace gta2dx9
