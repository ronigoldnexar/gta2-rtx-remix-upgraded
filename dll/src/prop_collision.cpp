#include "prop_collision.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include "log.h"
#include "model_store.h"
#include "../../src/gta2_map.h"

namespace gta2dx9 {
namespace {

// The player's body on foot, in blocks: an adult is 0.46 tall (live_geometry kPedHeight),
// his shoulders about a quarter of that across. A touch more than the half-width, since
// the frame the game drew him in was a step (up to 0.06 block running) before the push.
constexpr float kBodyRadius = 0.085f;
constexpr float kBodyHeight = 0.46f;
// First person: the eye stands ahead of the body (the view's FirstForwardFoot) and the
// near plane is 0.05 from it, its corners ~0.07 at the view's angle; it keeps this clear,
// with a hand to spare, so a wall of bench or trunk never fills the whole picture.
constexpr float kEyeClear = 0.11f;
constexpr float kEyeHeight = 0.43f;

struct Footprint {
    // In model units, before the placement's yaw and scale.
    struct Piece { float cx, cz, ha, hb; bool circle; };
    std::vector<Piece> pieces;
    float height = 0.5f;   // model units
};

std::map<const Model*, Footprint> g_footprints;
std::vector<CollisionShape> g_props, g_objects;

struct Pushable {
    float baseX, baseY, baseZ, radius, height;
    float dx = 0.0f, dz = 0.0f, vx = 0.0f, vz = 0.0f, yaw = 0.0f, spin = 0.0f;
    bool live = false;   // published this frame or last
};
std::unordered_map<uint32_t, Pushable> g_pushables;

int g_enabled = -1;
int g_logNear = -1;

uint32_t KeyOf(float x, float z) {
    const int32_t qx = static_cast<int32_t>(std::lround(x * 64.0f)), qz = static_cast<int32_t>(std::lround(z * 64.0f));
    return (static_cast<uint32_t>(qx) * 73856093u) ^ (static_cast<uint32_t>(qz) * 19349663u);
}

bool StartsWith(const std::string& s, const char* p) { return s.compare(0, strlen(p), p) == 0; }

// The model's footprint: what of it stands in the band a person's body occupies.
const Footprint& FootprintOf(const Model* model, float scale) {
    auto it = g_footprints.find(model);
    if (it != g_footprints.end()) return it->second;
    Footprint fp;
    fp.height = model->Height();
    std::string name = model->name;
    const size_t hash = name.find('#');
    if (hash != std::string::npos) name.resize(hash);
    if (name == "bus_shelter") {
        // tools/gen_env2.py build_bus_shelter (FIX-PROPS-3, at the figures' scale: 3.4 m long,
        // 1.4 m deep): open toward -x (the road), the back glass along +x, the end glass at +z
        // (bus_shelter__glass), the seat along the back, the five posts and the stop's sign post.
        constexpr float X = 0.184f, Z = 0.447f;
        for (float z : {-Z, Z})
            for (float x : {-X, X}) fp.pieces.push_back({x, z, 0.016f, 0.0f, true});
        fp.pieces.push_back({X, 0.0f, 0.012f, Z, false});
        fp.pieces.push_back({0.0f, Z, X, 0.012f, false});
        fp.pieces.push_back({0.121f, 0.0f, 0.053f, 0.263f, false});
        fp.pieces.push_back({-0.244f, -0.547f, 0.012f, 0.0f, true});
    } else if (name == "crane") {
        for (float x : {-0.45f, 0.45f})
            for (float z : {-0.35f, 0.35f}) fp.pieces.push_back({x, z, 0.05f, 0.05f, false});
    } else {
        // The vertices in the body's band (the bottom 0.5 block in the world; a tree's
        // trunk below its crown: the bottom 0.3), in the model's own frame.
        const bool tree = StartsWith(name, "tree");
        // A sign's or a meter's post only (FIX-PROPS-3: at their real size the plate or the
        // meter's head comes down into a 0.5 block band; it is above a figure's waist).
        const bool post = StartsWith(name, "sign_") || name == "parking_meter";
        const float band = (tree ? 0.3f : (post ? 0.25f : 0.5f)) / (std::max)(scale, 0.05f);
        std::vector<gta2::Mat4> worlds;
        ModelRestNodeWorlds(*model, &worlds);
        float x0 = 1e9f, x1 = -1e9f, z0 = 1e9f, z1 = -1e9f;
        std::vector<std::pair<float, float>> pts;
        for (size_t i = 0; i < model->nodes.size() && i < worlds.size(); ++i) {
            const int mi = model->nodes[i].mesh;
            if (mi < 0 || mi >= static_cast<int>(model->meshes.size())) continue;
            const gta2::Mat4& w = worlds[i];
            for (const ModelVertex& v : model->meshes[mi].vertices) {
                const float x = v.x * w.m[0][0] + v.y * w.m[1][0] + v.z * w.m[2][0] + w.m[3][0];
                const float y = v.x * w.m[0][1] + v.y * w.m[1][1] + v.z * w.m[2][1] + w.m[3][1];
                const float z = v.x * w.m[0][2] + v.y * w.m[1][2] + v.z * w.m[2][2] + w.m[3][2];
                if (y > model->boundsMin.y + band) continue;
                x0 = (std::min)(x0, x); x1 = (std::max)(x1, x); z0 = (std::min)(z0, z); z1 = (std::max)(z1, z);
                pts.push_back({x, z});
            }
        }
        if (pts.empty()) {
            x0 = model->boundsMin.x; x1 = model->boundsMax.x; z0 = model->boundsMin.z; z1 = model->boundsMax.z;
        }
        const float cx = 0.5f * (x0 + x1), cz = 0.5f * (z0 + z1);
        const bool round = tree || name == "street_lamp" || name == "fire_hydrant" || name == "trash_can" ||
                           StartsWith(name, "sign_") || name == "parking_meter";
        if (round) {
            float r = 0.0f;
            for (const auto& p : pts) r = (std::max)(r, std::hypot(p.first - cx, p.second - cz));
            if (pts.empty()) r = 0.5f * (std::max)(x1 - x0, z1 - z0);
            fp.pieces.push_back({cx, cz, r, 0.0f, true});
        } else {
            fp.pieces.push_back({cx, cz, 0.5f * (x1 - x0), 0.5f * (z1 - z0), false});
        }
    }
    {
        char line[512];
        int n = snprintf(line, sizeof line, "collide: footprint %s (scale %.2f, height %.2f):", model->name.c_str(), scale, fp.height);
        for (const Footprint::Piece& p : fp.pieces) {
            if (n >= static_cast<int>(sizeof line) - 48) break;
            n += p.circle ? snprintf(line + n, sizeof line - n, " circle %.2f,%.2f r %.3f", p.cx, p.cz, p.ha * scale)
                          : snprintf(line + n, sizeof line - n, " box %.2f,%.2f %.3fx%.3f", p.cx, p.cz, 2 * p.ha * scale, 2 * p.hb * scale);
        }
        Log("%s", line);
    }
    return g_footprints.emplace(model, std::move(fp)).first->second;
}

// The shortest move of a circle (x, z, r) out of a shape; false when clear.
bool Penetration(const CollisionShape& s, float x, float z, float r, float* outX, float* outZ, float* depth) {
    if (s.hb < 0.0f) {
        float dx = x - s.cx, dz = z - s.cz;
        const float d = std::hypot(dx, dz), want = s.ha + r;
        if (d >= want) return false;
        if (d < 1e-4f) { dx = 1.0f; dz = 0.0f; } else { dx /= d; dz /= d; }
        *outX = dx * (want - d); *outZ = dz * (want - d); *depth = want - d;
        return true;
    }
    const float bx = -s.az, bz = s.ax;
    const float vx = x - s.cx, vz = z - s.cz;
    const float a = vx * s.ax + vz * s.az, b = vx * bx + vz * bz;
    const float ca = (std::max)(-s.ha, (std::min)(s.ha, a)), cb = (std::max)(-s.hb, (std::min)(s.hb, b));
    float na = a - ca, nb = b - cb;
    const float d = std::hypot(na, nb);
    if (d >= r) return false;
    float push;
    if (d > 1e-4f) {
        na /= d; nb /= d; push = r - d;
    } else {
        // The centre inside the box: out through the nearer side.
        const float ia = s.ha - std::fabs(a), ib = s.hb - std::fabs(b);
        if (ia < ib) { na = a < 0.0f ? -1.0f : 1.0f; nb = 0.0f; push = ia + r; }
        else { na = 0.0f; nb = b < 0.0f ? -1.0f : 1.0f; push = ib + r; }
    }
    *outX = (na * s.ax + nb * bx) * push;
    *outZ = (na * s.az + nb * bz) * push;
    *depth = push;
    return true;
}

struct Stats {
    int frames = 0, contactFrames = 0, pushedFrames = 0, shoves = 0, wallHolds = 0, pedContacts = 0, pedMoves = 0;
    float maxDepth = 0.0f;
    std::map<std::string, int> kinds;
} g_stats;
std::set<std::string> g_firstContact;

// A light prop's move from (x0, z0) to (x1, z1) runs into a wall: its leading rim point is
// walled at the new place (it may stand with its back to a wall already; that is no reason
// it cannot be shoved away from it).
bool MoveWalled(bool (*walled)(void*, float, float, float), void* ctx, float x0, float z0, float x1, float z1, float y, float r) {
    if (!walled) return false;
    float dx = x1 - x0, dz = z1 - z0;
    const float len = std::hypot(dx, dz);
    if (len < 1e-6f) return false;
    dx /= len; dz /= len;
    if (walled(ctx, x1, y + 0.25f, z1) && !walled(ctx, x0, y + 0.25f, z0)) return true;
    return walled(ctx, x1 + dx * r, y + 0.25f, z1 + dz * r) && !walled(ctx, x0 + dx * r, y + 0.25f, z0 + dz * r);
}

bool WalledAt(bool (*walled)(void*, float, float, float), void* ctx, float x, float y, float z, float r) {
    if (!walled) return false;
    if (walled(ctx, x, y + 0.25f, z)) return true;
    if (r <= 0.0f) return false;
    for (int k = 0; k < 4; ++k) {
        const float px = x + r * ((k == 0) - (k == 1)), pz = z + r * ((k == 2) - (k == 3));
        if (walled(ctx, px, y + 0.25f, pz)) return true;
    }
    return false;
}

float g_corrX = 0.0f, g_corrZ = 0.0f;
bool g_corr = false;

}  // namespace

bool PropCollisionPlayerCorrection(float* dx, float* dz) {
    if (!g_corr) return false;
    *dx = g_corrX; *dz = g_corrZ;
    return true;
}
void PropCollisionSetPlayerCorrection(float dx, float dz) {
    g_corrX = dx; g_corrZ = dz;
    g_corr = std::fabs(dx) + std::fabs(dz) > 1e-6f;
}

bool PropCollisionEnabled() {
    if (g_enabled < 0) {
        char v[8] = {};
        g_enabled = (GetEnvironmentVariableA("GTA2DX9_PROP_COLLIDE", v, sizeof v) && v[0] == '0') ? 0 : 1;
        Log("collide: street props %s for the player on foot in the 3D views (GTA2DX9_PROP_COLLIDE)", g_enabled ? "solid" : "off");
    }
    return g_enabled == 1;
}

void PropCollisionBeginFrame() { g_props.clear(); }

namespace {
std::vector<CollisionShape> g_objectsNext;
void AddShapes(std::vector<CollisionShape>* list, const Model* model, float x, float y, float z, float yaw, float scale,
               int pushIndex) {
    const Footprint& fp = FootprintOf(model, scale);
    const float c = std::cos(yaw), sn = std::sin(yaw);
    for (const Footprint::Piece& p : fp.pieces) {
        CollisionShape s;
        s.cx = x + (p.cx * c + p.cz * sn) * scale;
        s.cz = z + (-p.cx * sn + p.cz * c) * scale;
        s.ax = c; s.az = -sn;
        s.ha = p.ha * scale;
        s.hb = p.circle ? -1.0f : p.hb * scale;
        s.y0 = y - 0.05f;
        s.y1 = y + (std::max)(0.15f, fp.height * scale);
        s.pushable = pushIndex;
        s.kind = model->name.c_str();
        list->push_back(s);
    }
}
}  // namespace

void PropCollisionAddPlaced(const Model* model, float x, float y, float z, float yaw, float scale, bool pushable, int pushIndex) {
    if (model) AddShapes(&g_props, model, x, y, z, yaw, scale, pushable ? pushIndex : -1);
}

bool PropCollisionSolidObject(const char* name) {
    // The game's own objects drawn as models that stand in the way: a phone box, a
    // traffic light's post, a bench, planters, barriers, sandbags, crates, a girder,
    // an upright drum. Not the pickups (walked over), nor what the game itself knocks
    // about (cones, tyres, boxes, footballs, extinguishers, lying drums).
    static const char* const kSolid[] = {"code_phone", "light_mount", "obj_bench", "obj_planter", "obj_barrier",
                                         "obj_sandbag", "obj_crate", "obj_girder"};
    if (!name) return false;
    std::string n = name;
    const size_t hash = n.find('#');
    if (hash != std::string::npos) n.resize(hash);
    if (n == "obj_drum") return true;
    for (const char* k : kSolid) if (n.compare(0, strlen(k), k) == 0) return true;
    return false;
}

void PropCollisionAddObject(const Model* model, float x, float y, float z, float yaw, float scale) {
    if (model) AddShapes(&g_objectsNext, model, x, y, z, yaw, scale, -1);
}
void PropCollisionObjectsDone() { g_objects.swap(g_objectsNext); g_objectsNext.clear(); }

int PropPushableAt(float baseX, float baseY, float baseZ, float radius, float height, float* dx, float* dz, float* dyaw) {
    const uint32_t key = KeyOf(baseX, baseZ) & 0x7FFFFFFF;
    auto it = g_pushables.find(key);
    if (it == g_pushables.end()) {
        Pushable p;
        p.baseX = baseX; p.baseY = baseY; p.baseZ = baseZ; p.radius = radius; p.height = height;
        it = g_pushables.emplace(key, p).first;
    }
    it->second.live = true;
    *dx = it->second.dx; *dz = it->second.dz; *dyaw = it->second.yaw;
    return static_cast<int>(key);
}

void PropCollisionStepPushables(float dt, bool (*walled)(void*, float, float, float), void* context) {
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    for (auto& kv : g_pushables) {
        Pushable& p = kv.second;
        if (std::fabs(p.vx) + std::fabs(p.vz) < 1e-3f && std::fabs(p.spin) < 1e-3f) { p.vx = p.vz = p.spin = 0.0f; continue; }
        const float nx = p.dx + p.vx * dt, nz = p.dz + p.vz * dt;
        bool hold = MoveWalled(walled, context, p.baseX + p.dx, p.baseZ + p.dz, p.baseX + nx, p.baseZ + nz, p.baseY, p.radius);
        if (!hold) {
            // Not into a fixed prop either.
            for (const CollisionShape& s : g_props) {
                if (s.pushable >= 0) continue;
                float ox, oz, d;
                if (Penetration(s, p.baseX + nx, p.baseZ + nz, p.radius, &ox, &oz, &d)) { hold = true; break; }
            }
        }
        if (hold) { p.vx = p.vz = 0.0f; p.spin *= 0.5f; }
        else { p.dx = nx; p.dz = nz; }
        p.yaw += p.spin * dt;
        // Rolling friction: a shoved bin slides on a hand or two and stops in about half a second.
        const float k = std::exp(-dt / 0.16f);
        p.vx *= k; p.vz *= k; p.spin *= std::exp(-dt / 0.22f);
    }
}

namespace {
bool ResolveBody(float* x, float* z, float y, float fx, float fz, bool firstPerson, float eyeAhead, float bodyRadius,
                 bool player, float dt, bool (*walled)(void*, float, float, float), void* context);
}

bool PropCollisionResolvePlayer(float* x, float* z, float y, float fx, float fz, bool firstPerson, float eyeAhead,
                                float dt, bool (*walled)(void*, float, float, float), void* context) {
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    PropCollisionStepPushables(dt, walled, context);
    g_corr = false;
    ++g_stats.frames;
    return ResolveBody(x, z, y, fx, fz, firstPerson, eyeAhead, kBodyRadius, true, dt, walled, context);
}

namespace {
std::vector<PedBody> g_peds;
}
void PropCollisionNotePed(void* ped, float x, float y, float z) {
    if (g_peds.size() < 96) g_peds.push_back({ped, x, y, z});
}
std::vector<PedBody> PropCollisionTakePeds() {
    std::vector<PedBody> out;
    out.swap(g_peds);
    return out;
}
bool PropCollisionResolvePed(float* x, float* z, float y, float dt, bool (*walled)(void*, float, float, float), void* context) {
    if (dt <= 0.0f || dt > 0.25f) dt = 1.0f / 30.0f;
    // A passer-by's body: a touch narrower than the player's (no step to make up, he is
    // drawn trailing his position).
    return ResolveBody(x, z, y, 0.0f, 0.0f, false, 0.0f, 0.07f, false, dt, walled, context);
}

namespace {
bool ResolveBody(float* x, float* z, float y, float fx, float fz, bool firstPerson, float eyeAhead, float bodyRadius,
                 bool player, float dt, bool (*walled)(void*, float, float, float), void* context) {
    const float x0 = *x, z0 = *z;
    float px = *x, pz = *z;
    const float flen = std::hypot(fx, fz);
    const float ex = flen > 1e-4f ? fx / flen : 0.0f, ez = flen > 1e-4f ? fz / flen : 0.0f;
    bool contact = false, pushed = false;
    float deepest = 0.0f;
    std::set<int> shovedNow;   // a shape still stands where the bin was this frame
    for (int iter = 0; iter < 4; ++iter) {
        bool any = false;
        for (const std::vector<CollisionShape>* list : {&g_props, &g_objects}) {
            for (const CollisionShape& s : *list) {
                if (std::fabs(s.cx - px) > 2.5f || std::fabs(s.cz - pz) > 2.5f) continue;
                // The body's band against the shape's.
                const bool bodyBand = y + kBodyHeight > s.y0 && y + 0.05f < s.y1;
                const bool eyeBand = firstPerson && y + kEyeHeight > s.y0 - 0.05f && y + kEyeHeight < s.y1 + 0.1f;
                if (!bodyBand && !eyeBand) continue;
                float ox = 0.0f, oz = 0.0f, d = 0.0f;
                bool hit = bodyBand && Penetration(s, px, pz, bodyRadius, &ox, &oz, &d);
                if (eyeBand) {
                    float ex2, ez2, d2;
                    if (Penetration(s, px + ex * eyeAhead, pz + ez * eyeAhead, kEyeClear, &ex2, &ez2, &d2) && d2 > d) {
                        ox = ex2; oz = ez2; d = d2; hit = true;
                    }
                }
                if (!hit) continue;
                if (s.pushable >= 0 && shovedNow.count(s.pushable)) continue;
                contact = true;
                deepest = (std::max)(deepest, d);
                if (player) ++g_stats.kinds[s.kind ? s.kind : "?"];
                else ++g_stats.pedContacts;
                if (player && s.kind && g_firstContact.insert(s.kind).second)
                    Log("collide: first contact with %s at %.2f,%.2f (player %.2f,%.2f level %.2f, depth %.3f, %s)", s.kind, s.cx,
                        s.cz, px, pz, y, d, s.pushable >= 0 ? "shoved" : "blocked");
                if (s.pushable >= 0) {
                    // A light prop: it goes, along the push, at the speed he came in with.
                    auto it = g_pushables.find(static_cast<uint32_t>(s.pushable));
                    if (it != g_pushables.end()) {
                        Pushable& p = it->second;
                        const float mx = -ox * 1.02f, mz = -oz * 1.02f;
                        const float nx = p.dx + mx, nz = p.dz + mz;
                        bool hold = MoveWalled(walled, context, p.baseX + p.dx, p.baseZ + p.dz, p.baseX + nx, p.baseZ + nz, p.baseY, p.radius);
                        for (const CollisionShape& f : g_props) {
                            if (hold) break;
                            if (f.pushable >= 0) continue;
                            float a, b, c;
                            if (Penetration(f, p.baseX + nx, p.baseZ + nz, p.radius, &a, &b, &c)) hold = true;
                        }
                        if (!hold) {
                            p.dx = nx; p.dz = nz;
                            const float speed = (std::min)(2.5f, d / dt);
                            const float len = std::hypot(mx, mz);
                            if (len > 1e-5f) {
                                const float vx = mx / len * speed, vz = mz / len * speed;
                                if (vx * vx + vz * vz > p.vx * p.vx + p.vz * p.vz) { p.vx = vx; p.vz = vz; }
                                // Struck off its centre line it turns a little.
                                const float side = (s.cx - px) * mz - (s.cz - pz) * mx;
                                p.spin += (side > 0.0f ? 1.0f : -1.0f) * (std::min)(2.0f, speed * 1.5f);
                            }
                            ++g_stats.shoves;
                            shovedNow.insert(s.pushable);
                            // He moves the bin: it does not stop him (the shape moves next frame).
                            any = true;
                            continue;
                        }
                    }
                }
                px += ox * 1.001f;
                pz += oz * 1.001f;
                pushed = true;
                any = true;
            }
        }
        if (!any) break;
    }
    if (contact && player) ++g_stats.contactFrames;
    if (player) g_stats.maxDepth = (std::max)(g_stats.maxDepth, deepest);
    bool moved = false;
    if (pushed && (std::fabs(px - x0) > 1e-5f || std::fabs(pz - z0) > 1e-5f)) {
        // Never into the map's walls: the whole move, else one axis of it, else none.
        if (!WalledAt(walled, context, px, y, pz, 0.0f)) { *x = px; *z = pz; moved = true; }
        else if (!WalledAt(walled, context, px, y, z0, 0.0f)) { *x = px; moved = true; }
        else if (!WalledAt(walled, context, x0, y, pz, 0.0f)) { *z = pz; moved = true; }
        else ++g_stats.wallHolds;
        if (moved && player) ++g_stats.pushedFrames;
        if (moved && !player) ++g_stats.pedMoves;
    }
    if (!player) return moved;
    if (g_stats.frames >= 300) {
        if (g_stats.contactFrames || g_stats.shoves || g_stats.pedContacts) {
            char kinds[256] = {};
            int n = 0;
            for (const auto& kv : g_stats.kinds) {
                if (n >= static_cast<int>(sizeof kinds) - 40) break;
                n += snprintf(kinds + n, sizeof kinds - n, " %s %d", kv.first.c_str(), kv.second);
            }
            Log("collide: over 300 frames %d with contact, %d moved out, %d shoves, %d held by a wall, deepest %.3f;%s; "
                "passers-by %d contacts, %d moved out",
                g_stats.contactFrames, g_stats.pushedFrames, g_stats.shoves, g_stats.wallHolds, g_stats.maxDepth, kinds,
                g_stats.pedContacts, g_stats.pedMoves);
        }
        g_stats = Stats();
    }
    // Forget the shoved props far away and at rest (they come back where they were placed).
    if (g_pushables.size() > 512) {
        for (auto it = g_pushables.begin(); it != g_pushables.end();) {
            const Pushable& p = it->second;
            if (std::fabs(p.baseX - *x) + std::fabs(p.baseZ - *z) > 80.0f) it = g_pushables.erase(it); else ++it;
        }
    }
    return moved;
}

}  // namespace

void PropCollisionLogNear(float x, float z, float y) {
    if (g_logNear < 0) {
        char v[8] = {};
        g_logNear = (GetEnvironmentVariableA("GTA2DX9_LOG_PROPS_NEAR", v, sizeof v) && v[0] == '1') ? 1 : 0;
    }
    if (!g_logNear) return;
    static int s_frame = 0;
    if (++s_frame % 60) return;
    char line[2048];
    int n = snprintf(line, sizeof line, "collide: near %.2f,%.2f level %.2f:", x, static_cast<float>(gta2::kMapHeight) - z, y);
    for (const std::vector<CollisionShape>* list : {&g_props, &g_objects}) {
        for (const CollisionShape& s : *list) {
            if (std::fabs(s.cx - x) > 5.0f || std::fabs(s.cz - z) > 5.0f || std::fabs(s.y0 - y) > 1.0f) continue;
            if (n >= static_cast<int>(sizeof line) - 64) break;
            // Game frame (x east, y south) for the probes.
            n += snprintf(line + n, sizeof line - n, " %s@%.2f,%.2f/%.2f", s.kind ? s.kind : "?", s.cx, static_cast<float>(gta2::kMapHeight) - s.cz,
                          s.hb < 0.0f ? s.ha : (std::max)(s.ha, s.hb));
        }
    }
    Log("%s", line);
}

}  // namespace gta2dx9
