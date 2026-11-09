#include "map_objects.h"

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
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
std::map<uint32_t, int> g_animByKey;        // 1 spin + float (pickups), 2 rotor, 3 authored size (booth)
std::map<const Model*, int> g_animByModel;
std::map<uint32_t, float> g_yawByKey;       // extra yaw, degrees, from the manifest ("objects_yaw")
// Companion models drawn with a model's placement (PROPS-2): "<name>__lit" unlit,
// so traffic-light lenses, the phone booth's sign and the pickups' rings glow at
// night; "<name>__glass" translucent, after everything else (the booth's panes).
std::map<const Model*, const Model*> g_litOf, g_glassOf;
struct Deferred { const Model* model; gta2::Mat4 out; };
std::vector<Deferred> g_litNow, g_glassNow;
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
    // "authored": a standing object drawn at its size in blocks, not stretched onto the
    // sprite's quad (QB-36: the phone booth's 0.50-block quad made a 1.9 m booth).
    readMap("objects_anim", [&](uint32_t key, const std::string& v) { g_animByKey[key] = v == "spin" ? 1 : v == "rotor" ? 2 : v == "authored" ? 3 : 0; });
    for (const auto& kv : g_animByKey) {
        auto it = g_byKey.find(kv.first);
        if (it != g_byKey.end()) g_animByModel[it->second] = kv.second;
    }
    int companions = 0;
    for (const auto& kv : g_byKey) {
        const Model* m = kv.second;
        if (g_litOf.count(m) || g_glassOf.count(m)) continue;
        if (const Model* lit = ModelByName((m->name + "__lit").c_str())) { g_litOf[m] = lit; ++companions; }
        if (const Model* glass = ModelByName((m->name + "__glass").c_str())) { g_glassOf[m] = glass; ++companions; }
    }
    Log("objects: %d sprite(s) mapped to models, %d lit/glass companion model(s)", mapped, companions);
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
std::vector<PropFootprint> g_objectObstacles;
const std::vector<PropFootprint>& MapObjectObstacles() { return g_objectObstacles; }

// ---- QB-49 near fade, QB-50 pickup list ----------------------------------------------------
namespace {
// The view and projection of the street views' frame, read back from the device at the top
// of MapObjectsDraw (LiveGeometry::Draw has set them by then), and the eye they imply.
float g_viewProj[4][4] = {};
bool g_viewProjValid = false;
float g_eye[3] = {0.0f, 0.0f, 0.0f};
float g_viewDir[3] = {0.0f, 0.0f, 1.0f};
std::vector<PickupSpot> g_pickups;
uint32_t g_pickupsFrame = 0;
std::map<const Model*, std::string> g_pickupLabels;
// An object closer to the eye than kFadeFar (blocks, from its footprint's rim or its top)
// is drawn see-through, down to kFadeMinAlpha at kFadeNear: a phone box or a traffic-light
// pole a hand from the first-person eye no longer fills the frame with a dark slab.
constexpr float kFadeNear = 0.10f, kFadeFar = 0.50f, kFadeMinAlpha = 0.18f;
struct Faded { const Model* model; gta2::Mat4 out; const ModelAnimation* spin; float t, alpha; };
std::vector<Faded> g_fadedNow;
int g_fadedLast = 0;
int g_nearFade = -1;   // GTA2DX9_NEAR_FADE=0 turns the fade off (QA before/after)

void CaptureView(IDirect3DDevice9* device) {
    D3DMATRIX v, p;
    g_viewProjValid = false;
    if (FAILED(device->GetTransform(D3DTS_VIEW, &v)) || FAILED(device->GetTransform(D3DTS_PROJECTION, &p))) return;
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float acc = 0.0f;
        for (int k = 0; k < 4; ++k) acc += v.m[r][k] * p.m[k][c];
        g_viewProj[r][c] = acc;
    }
    // Row vectors: p_view = p_world * V, so V's upper 3x3 holds the camera's axes as
    // columns and the eye is -(t R^T).
    for (int j = 0; j < 3; ++j) g_eye[j] = -(v.m[3][0] * v.m[j][0] + v.m[3][1] * v.m[j][1] + v.m[3][2] * v.m[j][2]);
    for (int j = 0; j < 3; ++j) g_viewDir[j] = v.m[j][2];
    g_viewProjValid = true;
}

// 1 beyond the fade range, down to kFadeMinAlpha at the eye: the gap from the eye to an
// upright box round the object (footprint radius, from its foot up to its top).
float NearFadeAlpha(float x, float footY, float z, float radius, float height) {
    if (g_nearFade < 0) {
        const char* e = getenv("GTA2DX9_NEAR_FADE");
        g_nearFade = (e && e[0] == '0') ? 0 : 1;
        Log("objects: near fade %s (QB-49: %.2f..%.2f blocks, alpha down to %.2f)", g_nearFade ? "on" : "off", kFadeNear, kFadeFar, kFadeMinAlpha);
    }
    if (!g_nearFade || !g_viewProjValid) return 1.0f;
    const float horiz = (std::max)(0.0f, std::hypot(g_eye[0] - x, g_eye[2] - z) - radius);
    const float vert = g_eye[1] < footY ? footY - g_eye[1] : g_eye[1] > footY + height ? g_eye[1] - footY - height : 0.0f;
    const float d = std::sqrt(horiz * horiz + vert * vert);
    if (d >= kFadeFar) return 1.0f;
    float t = (d - kFadeNear) / (kFadeFar - kFadeNear);
    t = (std::min)(1.0f, (std::max)(0.0f, t));
    t = t * t * (3.0f - 2.0f * t);
    return kFadeMinAlpha + (1.0f - kFadeMinAlpha) * t;
}

const char* PickupLabel(const Model& model) {
    auto it = g_pickupLabels.find(&model);
    if (it != g_pickupLabels.end()) return it->second.c_str();
    std::string label;
    const std::string& n = model.name;
    if (n.rfind("pickup_item_", 0) == 0) label = "PICKUP";
    else if (n == "token_briefcase") label = "BRIEFCASE";
    else if (n.rfind("token_", 0) == 0) label = "POWER-UP";   // which power-up a colour is: not mapped
    else if (n.rfind("pickup_", 0) == 0) {
        // The weapon's name from the model's: pickup_machine_gun -> MACHINE GUN.
        for (char c : n.substr(7)) label.push_back(c == '_' ? ' ' : static_cast<char>(toupper(static_cast<unsigned char>(c))));
        if (label == "SILENCED MG") label = "SILENCED MACHINE GUN";
        if (label == "DUAL PISTOL") label = "DUAL PISTOLS";
    } else label = "PICKUP";
    return (g_pickupLabels[&model] = label).c_str();
}
}  // namespace

const std::vector<PickupSpot>& MapObjectPickups() { return g_pickups; }
uint32_t MapObjectPickupsFrame() { return g_pickupsFrame; }
int MapObjectsFadedLastFrame() { return g_fadedLast; }
bool MapObjectsEye(float* eye, float* dir) {
    if (!g_viewProjValid) return false;
    for (int i = 0; i < 3; ++i) { eye[i] = g_eye[i]; dir[i] = g_viewDir[i]; }
    return true;
}
bool MapObjectsProject(float x, float y, float z, float* sx, float* sy, float* depth) {
    if (!g_viewProjValid) return false;
    const float (*m)[4] = g_viewProj;
    const float cx = x * m[0][0] + y * m[1][0] + z * m[2][0] + m[3][0];
    const float cy = x * m[0][1] + y * m[1][1] + z * m[2][1] + m[3][1];
    const float cw = x * m[0][3] + y * m[1][3] + z * m[2][3] + m[3][3];
    if (cw < 0.05f) return false;
    *sx = 0.5f + 0.5f * cx / cw;
    *sy = 0.5f - 0.5f * cy / cw;
    if (depth) *depth = (x - g_eye[0]) * g_viewDir[0] + (y - g_eye[1]) * g_viewDir[1] + (z - g_eye[2]) * g_viewDir[2];
    return true;
}

void MapObjectsDraw(IDirect3DDevice9* device, const std::vector<LiveGeometry::SpriteType>& sprites) {
    g_objectFootprints.clear();
    g_objectObstacles.clear();
    CaptureView(device);
    g_pickups.clear();
    ++g_pickupsFrame;
    g_fadedNow.clear();
    for (const LiveGeometry::SpriteType& s : sprites) {
        if (!s.objectModel) continue;
        if (!ModelIsKnown(s.objectModel)) {
            // Not an address the store ever gave out: a sprite whose field was never
            // set (a copy of stale memory). Drawing through it read garbage once.
            static int badLogged = 0;
            if (badLogged < 8) { ++badLogged; Log("object model: sprite %p carries an unknown model pointer %p, skipped", s.object ? reinterpret_cast<const void*>(s.object) : nullptr, static_cast<const void*>(s.objectModel)); }
            continue;
        }
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
        // A spinning pickup is authored at its size in blocks: fitted to each frame's
        // sprite extent it grew and shrank as the game cycled its turning frames.
        auto animIt = g_animByModel.find(&model);
        const bool spinning = animIt != g_animByModel.end() && animIt->second == 1;
        const bool authored = animIt != g_animByModel.end() && animIt->second == 3;
        const float scale = (spinning || authored) ? 1.0f : longer / modelLong;
        // The clearance radius: the quad's half edge, or the model's own half extent
        // when it is drawn at its authored size.
        const float footR = (std::min)(0.6f, (std::max)(0.12f, authored ? 0.5f * modelLong : 0.5f * longer));
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
        if (!spinning) {
            // Every standing object, drawn or culled, for the chase camera's clearance.
            const gta2::Mat4& w = s.objectToWorld;
            g_objectObstacles.push_back({cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0],
                                         cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1],
                                         cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2],
                                         footR, (std::max)(0.3f, model.Height() * scale)});
        }
        {
            // World position of the quad's centre; nothing drawn behind the camera.
            const gta2::Mat4& w = s.objectToWorld;
            const float wx = cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0];
            const float wy = cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1];
            const float wz = cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2];
            if (BehindView(wx, wy, wz, 1.5f)) continue;
            // beside the picture (PERF-2): the model's bounding sphere round the quad's centre
            const float r = 0.5f * scale * std::sqrt(model.Height() * model.Height() + model.Width() * model.Width() +
                                                     model.Length() * model.Length());
            if (OutsideViewFrustum(wx, wy + 0.5f * model.Height() * scale, wz, r + 0.25f)) continue;
        }
        // A pickup keeps its authored float above the ground (its origin is the ground).
        fit.m[3][0] = cx; fit.m[3][1] = spinning ? cy : cy - model.boundsMin.y * scale; fit.m[3][2] = cz; fit.m[3][3] = 1.0f;
        {
            // A standing object (a pickup floats and is walked through): its
            // footprint, so a first-person eye inside a phone box is pushed out.
            auto anim = g_animByModel.find(&model);
            if (anim == g_animByModel.end() || anim->second != 1) {
                const gta2::Mat4& w = s.objectToWorld;
                const float wx = cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0];
                const float wy = cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1];
                const float wz = cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2];
                g_objectFootprints.push_back({wx, wy, wz, footR, (std::max)(0.3f, model.Height() * scale)});
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
            const ModelAnimation* tail = ModelSpinAnimation(model, "tailrotor", 0, 0.09f);
            spin = ModelSpinAnimation(model, "rotor", 1, 0.14f);   // fetched last: the store keeps it stable
            if (tail) {
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
        const float spinT = spin ? static_cast<float>(std::fmod(NowSeconds(), static_cast<double>(spin->length))) : 0.0f;
        float alpha = 1.0f;
        {
            // World position of the quad's centre (the object's foot), for the near fade and
            // the pickups' labels.
            const gta2::Mat4& w = s.objectToWorld;
            const float wx = cx * w.m[0][0] + cy * w.m[1][0] + cz * w.m[2][0] + w.m[3][0];
            const float wy = cx * w.m[0][1] + cy * w.m[1][1] + cz * w.m[2][1] + w.m[3][1];
            const float wz = cx * w.m[0][2] + cy * w.m[1][2] + cz * w.m[2][2] + w.m[3][2];
            const float h = (std::max)(0.05f, model.Height() * scale);
            const float footY = spinning ? out.m[3][1] + model.boundsMin.y * scale : wy;
            alpha = NearFadeAlpha(wx, footY, wz, spinning ? 0.5f * (std::max)(model.Width(), model.Length()) * scale
                                                           : (std::min)(0.6f, (std::max)(0.12f, 0.5f * longer)), h);
            if (spinning && s.object) {
                // The model's centre, where it floats (its own float, not the bob).
                const float my = out.m[3][1] + 0.5f * (model.boundsMin.y + model.boundsMax.y) * scale;
                const float ed = std::sqrt((wx - g_eye[0]) * (wx - g_eye[0]) + (my - g_eye[1]) * (my - g_eye[1]) + (wz - g_eye[2]) * (wz - g_eye[2]));
                g_pickups.push_back({wx, my, wz, ed, reinterpret_cast<uintptr_t>(s.object), PickupLabel(model)});
            }
        }
        if (alpha < 0.999f) {
            // Drawn after everything else of this pass, see-through (QB-49).
            g_fadedNow.push_back({&model, out, spin, spinT, alpha});
            auto litF = g_litOf.find(&model);
            if (litF != g_litOf.end()) g_fadedNow.push_back({litF->second, out, nullptr, 0.0f, alpha});
            auto glassF = g_glassOf.find(&model);
            if (glassF != g_glassOf.end()) g_fadedNow.push_back({glassF->second, out, nullptr, 0.0f, alpha * 0.6f});
            continue;
        }
        ModelDraw(device, model, out, spin, spinT);
        auto lit = g_litOf.find(&model);
        if (lit != g_litOf.end()) g_litNow.push_back({lit->second, out});
        auto glass = g_glassOf.find(&model);
        if (glass != g_glassOf.end()) g_glassNow.push_back({glass->second, out});
    }
    if (!g_litNow.empty()) {
        // Unlit: the texture as it is, so a lens or a sign reads in the dark. By day
        // the same (a lit lens is as bright at noon); the scene's fog still applies.
        DWORD colorOp = D3DTOP_MODULATE;
        device->GetTextureStageState(0, D3DTSS_COLOROP, &colorOp);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        for (const Deferred& d : g_litNow) ModelDraw(device, *d.model, d.out, nullptr, 0.0f);
        device->SetTextureStageState(0, D3DTSS_COLOROP, colorOp);
        g_litNow.clear();
    }
    if (!g_glassNow.empty()) {
        // Translucent and without depth writes, after every opaque model, so what
        // stands behind a pane (the phone, a person) is drawn and shows through.
        DWORD blend = FALSE, test = FALSE, zwrite = TRUE, src = D3DBLEND_ONE, dst = D3DBLEND_ZERO, alphaOp = D3DTOP_SELECTARG1, alphaArg = D3DTA_TEXTURE;
        device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
        device->GetRenderState(D3DRS_ALPHATESTENABLE, &test);
        device->GetRenderState(D3DRS_ZWRITEENABLE, &zwrite);
        device->GetRenderState(D3DRS_SRCBLEND, &src);
        device->GetRenderState(D3DRS_DESTBLEND, &dst);
        device->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
        device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &alphaArg);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        for (const Deferred& d : g_glassNow) ModelDraw(device, *d.model, d.out, nullptr, 0.0f);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blend);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, test);
        device->SetRenderState(D3DRS_ZWRITEENABLE, zwrite);
        device->SetRenderState(D3DRS_SRCBLEND, src);
        device->SetRenderState(D3DRS_DESTBLEND, dst);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg);
        g_glassNow.clear();
    }
    g_fadedLast = static_cast<int>(g_fadedNow.size());
    if (!g_fadedNow.empty()) {
        // QB-49: the objects a hand from the eye, last and see-through: the texture's alpha
        // times the fade (the texture factor's alpha), blended, no depth writes, so what
        // stands behind (the street, a person drawn after) shows through.
        DWORD blend = FALSE, test = FALSE, zwrite = TRUE, src = D3DBLEND_ONE, dst = D3DBLEND_ZERO, factor = 0xFFFFFFFF;
        DWORD alphaOp = D3DTOP_SELECTARG1, alphaArg1 = D3DTA_TEXTURE, alphaArg2 = D3DTA_CURRENT;
        device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
        device->GetRenderState(D3DRS_ALPHATESTENABLE, &test);
        device->GetRenderState(D3DRS_ZWRITEENABLE, &zwrite);
        device->GetRenderState(D3DRS_SRCBLEND, &src);
        device->GetRenderState(D3DRS_DESTBLEND, &dst);
        device->GetRenderState(D3DRS_TEXTUREFACTOR, &factor);
        device->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
        device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &alphaArg1);
        device->GetTextureStageState(0, D3DTSS_ALPHAARG2, &alphaArg2);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
        // Farthest first, so two faded objects overlap the right way round.
        std::sort(g_fadedNow.begin(), g_fadedNow.end(), [](const Faded& a, const Faded& b) { return a.alpha > b.alpha; });
        for (const Faded& d : g_fadedNow) {
            const DWORD a = static_cast<DWORD>((std::min)(1.0f, (std::max)(0.0f, d.alpha)) * 255.0f + 0.5f);
            device->SetRenderState(D3DRS_TEXTUREFACTOR, (a << 24) | 0x00FFFFFFu);
            ModelDraw(device, *d.model, d.out, d.spin, d.t);
        }
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blend);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, test);
        device->SetRenderState(D3DRS_ZWRITEENABLE, zwrite);
        device->SetRenderState(D3DRS_SRCBLEND, src);
        device->SetRenderState(D3DRS_DESTBLEND, dst);
        device->SetRenderState(D3DRS_TEXTUREFACTOR, factor);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, alphaArg2);
        static uint32_t fadeLogFrame = 0;
        if (((++fadeLogFrame) % 150) == 1) Log("objects: near fade: %d object(s) see-through this frame, the nearest at alpha %.2f", g_fadedLast, g_fadedNow.back().alpha);
        g_fadedNow.clear();
    }
}
}  // namespace gta2dx9
