// QB-27: ragdolls for people run over or blown off their feet. See ragdoll.h.
//
// Units are the renderer's: blocks (a standing adult is 0.46 of one, so a block
// is about 3.9 m), y up, seconds. Matrices are row-vector (p' = p * M), rows 0-2
// the axes, row 3 the origin, like the rest of the renderer.
#include "mem_stats.h"
#include "ragdoll.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>

#include "log.h"
#include "model_store.h"
#include "view_modes.h"

namespace gta2dx9 {

extern ViewQueries g_devQueries;   // view_modes.cpp: the map queries, set every frame with a level

namespace {

using gta2::Mat4;
using gta2::Vec3;

// --- small affine helpers -------------------------------------------------
Mat4 Mul(const Mat4& a, const Mat4& b) {
    Mat4 o;
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
            o.m[r][c] = s;
        }
    return o;
}
// Inverse of an affine row-vector matrix (last column 0 0 0 1).
Mat4 InverseAffine(const Mat4& a) {
    const float (*m)[4] = a.m;
    const float c00 = m[1][1] * m[2][2] - m[1][2] * m[2][1];
    const float c01 = m[1][2] * m[2][0] - m[1][0] * m[2][2];
    const float c02 = m[1][0] * m[2][1] - m[1][1] * m[2][0];
    const float det = m[0][0] * c00 + m[0][1] * c01 + m[0][2] * c02;
    Mat4 o;
    if (std::fabs(det) < 1e-12f) { o.m[0][0] = o.m[1][1] = o.m[2][2] = o.m[3][3] = 1.0f; return o; }
    const float id = 1.0f / det;
    o.m[0][0] = c00 * id;
    o.m[1][0] = c01 * id;
    o.m[2][0] = c02 * id;
    o.m[0][1] = (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * id;
    o.m[1][1] = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * id;
    o.m[2][1] = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * id;
    o.m[0][2] = (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * id;
    o.m[1][2] = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * id;
    o.m[2][2] = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * id;
    for (int c = 0; c < 3; ++c) o.m[3][c] = -(m[3][0] * o.m[0][c] + m[3][1] * o.m[1][c] + m[3][2] * o.m[2][c]);
    o.m[3][3] = 1.0f;
    return o;
}
Vec3 Point(const Vec3& p, const Mat4& m) {
    return {p.x * m.m[0][0] + p.y * m.m[1][0] + p.z * m.m[2][0] + m.m[3][0],
            p.x * m.m[0][1] + p.y * m.m[1][1] + p.z * m.m[2][1] + m.m[3][1],
            p.x * m.m[0][2] + p.y * m.m[1][2] + p.z * m.m[2][2] + m.m[3][2]};
}
Vec3 Origin(const Mat4& m) { return {m.m[3][0], m.m[3][1], m.m[3][2]}; }
float Len(const Vec3& v) { return std::sqrt(gta2::Dot(v, v)); }
// The rotation (row-vector) that turns direction a onto direction b, the short way.
Mat4 FromTo(Vec3 a, Vec3 b) {
    Mat4 r;
    r.m[0][0] = r.m[1][1] = r.m[2][2] = r.m[3][3] = 1.0f;
    const float la = Len(a), lb = Len(b);
    if (la < 1e-6f || lb < 1e-6f) return r;
    a = a * (1.0f / la);
    b = b * (1.0f / lb);
    Vec3 k = gta2::Cross(a, b);
    const float s = Len(k), c = gta2::Dot(a, b);
    if (s < 1e-6f) {
        if (c > 0.0f) return r;
        // Opposite: half a turn about any axis square to a.
        k = std::fabs(a.x) < 0.9f ? gta2::Cross(a, Vec3{1, 0, 0}) : gta2::Cross(a, Vec3{0, 1, 0});
        k = gta2::Normalize(k);
    } else {
        k = k * (1.0f / s);
    }
    const float t = 1.0f - c;
    // Column-vector Rodrigues R; the row-vector form is its transpose.
    const float R[3][3] = {{c + k.x * k.x * t, k.x * k.y * t - k.z * s, k.x * k.z * t + k.y * s},
                           {k.y * k.x * t + k.z * s, c + k.y * k.y * t, k.y * k.z * t - k.x * s},
                           {k.z * k.x * t - k.y * s, k.z * k.y * t + k.x * s, c + k.z * k.z * t}};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) r.m[i][j] = R[j][i];
    return r;
}
// A node's world matrix turned by `rot` about its own origin.
void TurnAboutOrigin(Mat4& w, const Mat4& rot) {
    for (int row = 0; row < 3; ++row) {
        const float x = w.m[row][0], y = w.m[row][1], z = w.m[row][2];
        for (int c = 0; c < 3; ++c) w.m[row][c] = x * rot.m[0][c] + y * rot.m[1][c] + z * rot.m[2][c];
    }
}

// --- the body --------------------------------------------------------------
enum {
    kPelvis, kChest, kNeck, kHead, kHeadTop, kLShoulder, kLElbow, kLHand, kRShoulder, kRElbow, kRHand,
    kLHip, kLKnee, kLFoot, kRHip, kRKnee, kRFoot, kParticles
};
const char* const kNodeNames[kParticles] = {"Bip01 Pelvis", "Bip01 Spine2", "Bip01 Neck", "Bip01 Head", nullptr,
                                            "Bip01 L UpperArm", "Bip01 L Forearm", "Bip01 L Hand",
                                            "Bip01 R UpperArm", "Bip01 R Forearm", "Bip01 R Hand",
                                            "Bip01 L Thigh", "Bip01 L Calf", "Bip01 L Foot",
                                            "Bip01 R Thigh", "Bip01 R Calf", "Bip01 R Foot"};
// Collision radii, blocks (12 cm at the pelvis).
const float kRadius[kParticles] = {0.030f, 0.034f, 0.024f, 0.026f, 0.030f, 0.022f, 0.016f, 0.012f, 0.022f, 0.016f, 0.012f,
                                   0.026f, 0.018f, 0.015f, 0.026f, 0.018f, 0.015f};
const int kTorso[] = {kPelvis, kChest, kNeck, kLShoulder, kRShoulder, kLHip, kRHip};
// Which skeleton node is aimed at which particle (its bone points there).
struct Aim { const char* node; int target; };
const Aim kAims[] = {{"Bip01 Neck", kHead},          {"Bip01 Head", kHeadTop},     {"Bip01 L UpperArm", kLElbow},
                     {"Bip01 L Forearm", kLHand},    {"Bip01 R UpperArm", kRElbow}, {"Bip01 R Forearm", kRHand},
                     {"Bip01 L Thigh", kLKnee},      {"Bip01 L Calf", kLFoot},      {"Bip01 R Thigh", kRKnee},
                     {"Bip01 R Calf", kRFoot}};
constexpr int kAimCount = sizeof(kAims) / sizeof(kAims[0]);

struct Rig {
    bool ok = false;
    int node[kParticles];
    int aimNode[kAimCount];
    std::vector<int> order;   // nodes, parents first
};
std::map<const Model*, Rig> g_rigs;

const Rig& RigFor(const Model& model) {
    auto found = g_rigs.find(&model);
    if (found != g_rigs.end()) return found->second;
    Rig& rig = g_rigs[&model];
    auto byName = [&](const char* name) {
        for (size_t i = 0; i < model.nodes.size(); ++i)
            if (strcmp(model.nodes[i].name, name) == 0) return static_cast<int>(i);
        return -1;
    };
    rig.ok = true;
    for (int p = 0; p < kParticles; ++p) {
        rig.node[p] = kNodeNames[p] ? byName(kNodeNames[p]) : -1;
        if (p == kChest && rig.node[p] < 0) rig.node[p] = byName("Bip01 Spine1");
        if (kNodeNames[p] && rig.node[p] < 0) rig.ok = false;
    }
    for (int a = 0; a < kAimCount; ++a) rig.aimNode[a] = byName(kAims[a].node);
    const size_t n = model.nodes.size();
    std::vector<bool> done(n, false);
    for (int pass = 0; pass < 8 && rig.order.size() < n; ++pass)
        for (size_t i = 0; i < n; ++i) {
            if (done[i]) continue;
            const int p = model.nodes[i].parent;
            if (p >= 0 && p < static_cast<int>(n) && !done[p]) continue;
            done[i] = true;
            rig.order.push_back(static_cast<int>(i));
        }
    if (rig.order.size() != n) rig.ok = false;
    Log("ragdoll: rig for %s %s (%zu nodes)", model.name.c_str(), rig.ok ? "ready" : "MISSING joints: canned clip", n);
    return rig;
}

struct Particle {
    Vec3 p, prev;
};
struct Link {
    int a, b;
    float lo, hi;   // kept between these lengths
};

struct Body {
    uint32_t id = 0;
    int kind = 0;
    const Model* model = nullptr;
    Particle q[kParticles];
    std::vector<Link> links;
    std::vector<Mat4> seedLocal;     // each node in its parent's frame, from the seed pose
    std::vector<Mat4> seedWorld;     // the seed pose in the world
    Mat4 seedTorsoInv;               // the seed torso frame, inverted
    Vec3 aimLocal[kAimCount];        // each aim's target in its node's seed frame
    std::vector<Mat4> pose;          // model-space node matrices for the hook
    float anchorX = 0.0f, anchorZ = 0.0f;   // the game's spot for him: the body follows it if the game moves him
    float startX = 0.0f, startZ = 0.0f;
    float age = 0.0f, still = 0.0f;
    bool settled = false, walls = true;
    uintptr_t car = 0;
    float carVX = 0.0f, carVZ = 0.0f;
    uint32_t gen = 0, seen = 0;
    float maxHeight = 0.0f;
    Mat4 lastWorld;
    float facing = 1.0f;   // the torso frame's forward times this is the way he faces
    float release = 0.0f;  // getting up: seconds left of the blend from the ragdoll back to the clips
    bool rescale = false;  // FIX-KNOCKDOWN: velocities just set per 1/30 s (the roll): rescale on the next step
    // FIX-KNOCKDOWN-2 (pfl65): the ground he lies on, latched at the seed. The game's height for him moves a few
    // hundredths of a block with its state (lying 2.016, stood up 2.042 in kd2_a): taken as the floor every frame,
    // that step pushed every joint up in one 1/120 s sub-step, a 3 blocks/s kick, and the lying body flew 1.5 blocks.
    float groundY = 0.0f;
    float kickAge = 0.0f;   // age at the last deliberate push (the throw at 0, a roll): upward speed free for 0.6 s after
    int dbgWalls = 0, dbgCar = 0;   // FIX-KNOCKDOWN-2 trace: joints the walls sent back, car contacts, this frame
    float dbgDrift = 0.0f, dbgMove = 0.0f;
    // FIX-KNOCKDOWN-2 (triage 204: the solver roll flipped him through a head-down handstand): the roll is played,
    // not thrown: the body turned half a turn about its long axis at the height it lies, limbs drawn in mid-roll.
    float rollLeft = 0.0f, rollDur = 0.0f, rollAngle = 0.0f;
    Vec3 rollAxis{0.0f, 0.0f, 1.0f}, rollCentre{0.0f, 0.0f, 0.0f}, rollShift{0.0f, 0.0f, 0.0f};
    Vec3 rollFrom[kParticles];
    int dbgShove = 0;         // other cars' shoves this frame
    float leash = 0.9f;       // how far from the game's spot he may lie: longer while a car shoves him, eased back
};
constexpr float kReleaseSecs = 0.3f;
std::map<uintptr_t, Body> g_bodies;
uint32_t g_nextId = 1;

struct CarNote {
    float x = 0.0f, z = 0.0f, fx = 1.0f, fz = 0.0f, halfLen = 0.0f, halfWid = 0.0f;
    float vx = 0.0f, vz = 0.0f;
    uint32_t frame = 0;
};
std::map<uintptr_t, CarNote> g_cars;
struct BlastNote { float x, y, z, size; uint32_t frame; };
std::vector<BlastNote> g_blasts;

const Body* g_hookBody = nullptr;
// FIX-KNOCKDOWN-2: the ground latch, the lift cap and the other cars' shove; GTA2DX9_KD_GROUND_LATCH=0 = as before (A/B).
bool Kd2Roll() {
    static int on = -1;
    if (on < 0) { const char* e = getenv("GTA2DX9_KD_ROLL"); on = (e && *e == '0') ? 0 : 1; }
    return on == 1;
}
// The played roll, one frame: positions set (and previous positions with them: no speed of its own).
void RollFrame(Body& b, float dt, float gy) {
    b.rollLeft = (std::max)(0.0f, b.rollLeft - dt);
    const float t = 1.0f - b.rollLeft / b.rollDur;
    const float e = t * t * (3.0f - 2.0f * t);
    const float th = b.rollAngle * e, c = std::cos(th), sn = std::sin(th);
    const float tuck = 0.55f * std::sin(3.14159265f * t);   // limbs drawn in toward the long axis mid-roll
    const Vec3 a = b.rollAxis;
    for (int k = 0; k < kParticles; ++k) {
        Vec3 r = b.rollFrom[k] - b.rollCentre;
        const bool limb = k == kLElbow || k == kLHand || k == kRElbow || k == kRHand || k == kLKnee || k == kLFoot ||
                          k == kRKnee || k == kRFoot;
        if (limb) {
            const Vec3 along = a * gta2::Dot(r, a);
            r = along + (r - along) * (1.0f - tuck);
        }
        const Vec3 rr = r * c + gta2::Cross(a, r) * sn + a * (gta2::Dot(a, r) * (1.0f - c));
        Vec3 p = b.rollCentre + b.rollShift * e + rr;
        if (p.y < gy + kRadius[k]) p.y = gy + kRadius[k];
        b.q[k].p = p;
        b.q[k].prev = p;
    }
    b.age += dt;
    if (b.rollLeft <= 0.0f) { b.settled = false; b.still = 0.0f; }
}
// FIX-KNOCKDOWN-3 (pfl77): no head-down handstand. A slow car carried the head on its bonnet past the pelvis while
// the feet dragged on the road: the body somersaulted forward and stood on its head, legs straight up, for 0.3-1 s
// (the filer's 30 fps frames; the offline harness: 106 of 288 hits with legs vertical for 3+ frames). The body
// may turn about its long axis (roll) as it likes; about the cross axis it is held: the line from the hips to the
// feet rises at most kLegRise above the level, the hips to the knees kKneeRise (knees up on his back), and the
// head falls at most kHeadDrop below the pelvis (draped over a bonnet). GTA2DX9_KD_NO_FLIP=0 = as before (A/B).

constexpr float kKd3Spin = 4.5f;   // the slow knock: rad/s of pitch given at the impact
bool Kd3NoFlip() {
    static int on = -1;
    if (on < 0) { const char* e = getenv("GTA2DX9_KD_NO_FLIP"); on = (e && *e == '0') ? 0 : 1; }
    return on == 1;
}
bool Kd2Fix() {
    static int on = -1;
    if (on < 0) { const char* e = getenv("GTA2DX9_KD_GROUND_LATCH"); on = (e && *e == '0') ? 0 : 1; }
    return on == 1;
}

void PoseHook(const Model& model, std::vector<Mat4>* worlds, void* context) {
    const Body* body = static_cast<const Body*>(context);
    if (!body || body->model != &model || body->pose.size() != worlds->size()) return;
    if (body->release <= 0.0f) { *worlds = body->pose; return; }
    // Getting up: from the ragdoll's pose to the clip's (the game's get-up), each
    // node's axes and origin blended, the axes made square again at their own lengths.
    const float w = body->release / kReleaseSecs;   // 1 all ragdoll .. 0 all clip
    for (size_t i = 0; i < worlds->size(); ++i) {
        Mat4& o = (*worlds)[i];
        const Mat4& r = body->pose[i];
        float len[3];
        Vec3 ax[3];
        for (int k = 0; k < 3; ++k) {
            len[k] = (1.0f - w) * Len(Vec3{o.m[k][0], o.m[k][1], o.m[k][2]}) + w * Len(Vec3{r.m[k][0], r.m[k][1], r.m[k][2]});
            ax[k] = Vec3{o.m[k][0] * (1.0f - w) + r.m[k][0] * w, o.m[k][1] * (1.0f - w) + r.m[k][1] * w,
                         o.m[k][2] * (1.0f - w) + r.m[k][2] * w};
        }
        Vec3 x = gta2::Normalize(ax[0]);
        Vec3 y = ax[1] - x * gta2::Dot(ax[1], x);
        if (Len(y) < 1e-5f) y = gta2::Cross(gta2::Normalize(ax[2]), x);
        y = gta2::Normalize(y);
        Vec3 z = gta2::Cross(x, y);
        if (gta2::Dot(z, ax[2]) < 0.0f) z = z * -1.0f;
        const Vec3 axes[3] = {x * len[0], y * len[1], z * len[2]};
        for (int k = 0; k < 3; ++k) { o.m[k][0] = axes[k].x; o.m[k][1] = axes[k].y; o.m[k][2] = axes[k].z; }
        for (int c = 0; c < 3; ++c) o.m[3][c] = o.m[3][c] * (1.0f - w) + r.m[3][c] * w;
    }
}

int g_enabled = -1;

Vec3 TorsoFrameAxes(const Particle* q, Vec3* side, Vec3* up, Vec3* fwd) {
    const Vec3 hipMid = (q[kLHip].p + q[kRHip].p) * 0.5f;
    const Vec3 shoulderMid = (q[kLShoulder].p + q[kRShoulder].p) * 0.5f;
    *up = gta2::Normalize(shoulderMid - hipMid);
    Vec3 s = (q[kRHip].p - q[kLHip].p) + (q[kRShoulder].p - q[kLShoulder].p);
    s = s - *up * gta2::Dot(s, *up);
    *side = gta2::Normalize(s);
    *fwd = gta2::Cross(*up, *side);
    return q[kPelvis].p;
}
Mat4 TorsoFrame(const Particle* q) {
    Vec3 side, up, fwd;
    const Vec3 o = TorsoFrameAxes(q, &side, &up, &fwd);
    Mat4 f;
    f.m[0][0] = side.x; f.m[0][1] = side.y; f.m[0][2] = side.z;
    f.m[1][0] = up.x;   f.m[1][1] = up.y;   f.m[1][2] = up.z;
    f.m[2][0] = fwd.x;  f.m[2][1] = fwd.y;  f.m[2][2] = fwd.z;
    f.m[3][0] = o.x;    f.m[3][1] = o.y;    f.m[3][2] = o.z;
    f.m[3][3] = 1.0f;
    return f;
}

float Hash01(uint32_t v) {
    v ^= v >> 16; v *= 0x7feb352dU; v ^= v >> 15; v *= 0x846ca68bU; v ^= v >> 16;
    return static_cast<float>(v & 0xFFFFFF) / 16777216.0f;
}

// Seeds the body from the pose the caller is about to draw and throws it.
bool Seed(Body& b, uintptr_t ped, int kind, const Model& model, const Rig& rig, const Mat4& world, float gx, float gy,
          float gz, float heading, uint32_t frame, const ModelAnimation* a, float ta, const ModelAnimation* sb, float tb,
          float w) {
    std::vector<Mat4> modelWorlds;
    ModelPoseWorlds(model, a, ta, sb, tb, w, &modelWorlds);
    const size_t n = model.nodes.size();
    if (modelWorlds.size() != n) return false;
    b = Body();
    b.id = g_nextId++;
    b.kind = kind;
    b.model = &model;
    b.seedWorld.resize(n);
    b.seedLocal.resize(n);
    for (size_t i = 0; i < n; ++i) b.seedWorld[i] = Mul(modelWorlds[i], world);
    for (size_t i = 0; i < n; ++i) {
        const int p = model.nodes[i].parent;
        b.seedLocal[i] = (p >= 0 && p < static_cast<int>(n)) ? Mul(modelWorlds[i], InverseAffine(modelWorlds[p])) : modelWorlds[i];
    }
    for (int k = 0; k < kParticles; ++k) {
        if (rig.node[k] >= 0) b.q[k].p = Origin(b.seedWorld[rig.node[k]]);
    }
    {
        const Vec3 nh = gta2::Normalize(b.q[kHead].p - b.q[kNeck].p);
        b.q[kHeadTop].p = b.q[kHead].p + nh * 0.05f;
    }
    // Feet and hands not below the ground they start on.
    for (int k = 0; k < kParticles; ++k) {
        if (b.q[k].p.y < gy + kRadius[k]) b.q[k].p.y = gy + kRadius[k];
        b.q[k].prev = b.q[k].p;
    }
    // Links: the torso rigid, the limbs at their seed lengths, and the ranges
    // that stop a knee folding flat, a head sinking into the chest, a leg
    // passing through the other.
    auto dist = [&](int i, int j) { return Len(b.q[i].p - b.q[j].p); };
    auto keep = [&](int i, int j, float lo, float hi) { const float d = dist(i, j); b.links.push_back({i, j, d * lo, d * hi}); };
    const int torsoCount = sizeof(kTorso) / sizeof(kTorso[0]);
    for (int i = 0; i < torsoCount; ++i)
        for (int j = i + 1; j < torsoCount; ++j) keep(kTorso[i], kTorso[j], 1.0f, 1.0f);
    const int bones[][2] = {{kNeck, kHead}, {kHead, kHeadTop}, {kLShoulder, kLElbow}, {kLElbow, kLHand}, {kRShoulder, kRElbow},
                            {kRElbow, kRHand}, {kLHip, kLKnee}, {kLKnee, kLFoot}, {kRHip, kRKnee}, {kRKnee, kRFoot}};
    for (const auto& bone : bones) keep(bone[0], bone[1], 1.0f, 1.0f);
    keep(kChest, kHead, 0.85f, 1.04f);
    keep(kChest, kHeadTop, 0.85f, 1.04f);
    keep(kLShoulder, kHeadTop, 0.85f, 1e3f);
    keep(kRShoulder, kHeadTop, 0.85f, 1e3f);
    // Limb spans: the seed is near straight; a folded elbow or knee keeps some span.
    {
        const float armL = dist(kLShoulder, kLElbow) + dist(kLElbow, kLHand);
        const float armR = dist(kRShoulder, kRElbow) + dist(kRElbow, kRHand);
        const float legL = dist(kLHip, kLKnee) + dist(kLKnee, kLFoot);
        const float legR = dist(kRHip, kRKnee) + dist(kRKnee, kRFoot);
        b.links.push_back({kLShoulder, kLHand, armL * 0.40f, armL});
        b.links.push_back({kRShoulder, kRHand, armR * 0.40f, armR});
        b.links.push_back({kLHip, kLFoot, legL * 0.50f, legL});
        b.links.push_back({kRHip, kRFoot, legR * 0.50f, legR});
    }
    keep(kLKnee, kChest, 0.5f, 1e3f);
    keep(kRKnee, kChest, 0.5f, 1e3f);
    keep(kLFoot, kPelvis, 0.45f, 1e3f);
    keep(kRFoot, kPelvis, 0.45f, 1e3f);
    keep(kLHand, kChest, 0.35f, 1e3f);
    keep(kRHand, kChest, 0.35f, 1e3f);
    {
        const float kd = (std::max)(0.04f, dist(kLKnee, kRKnee)), fd = (std::max)(0.04f, dist(kLFoot, kRFoot));
        b.links.push_back({kLKnee, kRKnee, kd * 0.55f, 1e3f});
        b.links.push_back({kLFoot, kRFoot, fd * 0.45f, 1e3f});
    }
    b.seedTorsoInv = InverseAffine(TorsoFrame(b.q));
    {
        Vec3 side, up, fwd;
        TorsoFrameAxes(b.q, &side, &up, &fwd);
        b.facing = fwd.x * std::sin(heading) + fwd.z * std::cos(heading) >= 0.0f ? 1.0f : -1.0f;
    }
    for (int k = 0; k < kAimCount; ++k) {
        const int node = rig.aimNode[k];
        b.aimLocal[k] = node >= 0 ? Point(b.q[kAims[k].target].p, InverseAffine(b.seedWorld[node])) : Vec3{};
    }
    b.anchorX = b.startX = gx;
    b.anchorZ = b.startZ = gz;
    b.groundY = gy;
    b.walls = !(g_devQueries.blocked && g_devQueries.blocked(g_devQueries.context, gx, gy + 0.25f, gz));

    // The throw.
    const float hx = std::sin(heading), hz = std::cos(heading);
    const float jitter = Hash01(static_cast<uint32_t>(ped >> 2) * 2654435761u + frame) - 0.5f;
    float vx = 0.0f, vz = 0.0f, lift = 0.0f, upper = 1.0f, spin = 0.0f;
    if (kind == 1) {
        // The car that hit him: the nearest seen this frame or the last, within 1.6 blocks.
        const CarNote* best = nullptr;
        float bestD = 1.6f * 1.6f;
        uintptr_t bestObj = 0;
        for (const auto& c : g_cars) {
            if (frame - c.second.frame > 2) continue;
            const float dx = c.second.x - gx, dz = c.second.z - gz;
            // Inside the footprint counts as nearest; then by distance to its edge.
            const float lx = std::fabs(dx * c.second.fx + dz * c.second.fz) - c.second.halfLen;
            const float lz = std::fabs(-dx * c.second.fz + dz * c.second.fx) - c.second.halfWid;
            const float ex = (std::max)(0.0f, lx), ez = (std::max)(0.0f, lz);
            const float d2 = ex * ex + ez * ez;
            // A car still and one moving at the same distance: the moving one did it.
            const float sp = std::sqrt(c.second.vx * c.second.vx + c.second.vz * c.second.vz);
            const float score = d2 - (sp > 0.3f ? 0.05f : 0.0f);
            if (score < bestD) { bestD = score; best = &c.second; bestObj = c.first; }
        }
        float sp = 0.0f;
        if (best) {
            b.car = bestObj;
            vx = best->vx; vz = best->vz;
            sp = std::sqrt(vx * vx + vz * vz);
            if (sp < 0.3f) {
                // No pace known: shoved away from the car's middle.
                const float dx = gx - best->x, dz = gz - best->z, d = (std::max)(0.05f, std::sqrt(dx * dx + dz * dz));
                vx = dx / d * 0.8f; vz = dz / d * 0.8f; sp = 0.8f;
            }
        } else {
            vx = -hx * 0.8f; vz = -hz * 0.8f; sp = 0.8f;
        }
        if (sp > 6.0f) { vx *= 6.0f / sp; vz *= 6.0f / sp; sp = 6.0f; }
        b.carVX = vx; b.carVZ = vz;
        if (best) {
            // By the time the game reports the hit the car overlaps him (up to a few tenths
            // of a block): the whole body is moved out of its box in one piece, along the
            // face nearest his pelvis, so the throw turns him, not a shove of his legs alone.
            const CarNote& c = *best;
            const float pdx = b.q[kPelvis].p.x - c.x, pdz = b.q[kPelvis].p.z - c.z;
            const float plx = pdx * c.fx + pdz * c.fz, plz = -pdx * c.fz + pdz * c.fx;
            const bool alongLength = c.halfLen - std::fabs(plx) < c.halfWid - std::fabs(plz);
            const float sgn = (alongLength ? plx : plz) >= 0.0f ? 1.0f : -1.0f;
            float need = 0.0f;
            for (int k = 0; k < kParticles; ++k) {
                const float dx = b.q[k].p.x - c.x, dz = b.q[k].p.z - c.z;
                const float lx = dx * c.fx + dz * c.fz, lz = -dx * c.fz + dz * c.fx;
                const float r = kRadius[k];
                if (std::fabs(lx) >= c.halfLen + r || std::fabs(lz) >= c.halfWid + r) continue;
                if (b.q[k].p.y > gy + 0.34f + r) continue;
                const float pen = alongLength ? c.halfLen + r - lx * sgn : c.halfWid + r - lz * sgn;
                need = (std::max)(need, pen);
            }
            need = (std::min)(need, 0.6f);
            if (need > 0.0f) {
                const float ox = alongLength ? c.fx * sgn : -c.fz * sgn, oz = alongLength ? c.fz * sgn : c.fx * sgn;
                for (Particle& q : b.q) { q.p.x += ox * need; q.p.z += oz * need; }
                b.startX += ox * need; b.startZ += oz * need;
            }
        }
        lift = sp * 0.30f * (std::min)(1.0f, sp / 2.5f);   // at speed, up onto the bonnet
        upper = 0.45f;                                       // the upper body lags: he folds over the bonnet
        // FIX-KNOCKDOWN-3 (pfl77, kd3_lane1 #2): below 3 blocks/s the car does not fold him over its bonnet (a slow
        // van carried the head on its bonnet past the pelvis: a handstand) and does not lift him (a taxi at 1.7
        // lifted the feet 0.23 and he glided upright 1.2 blocks for half a second): he is knocked over along its
        // travel, a pitch of kKd3Spin rad/s about his feet, so he is down on the road in about half a second.
        // From 3 blocks/s the old throw (fold over the bonnet, lifted) as before.
        if (Kd3NoFlip()) {
            const float t = (std::min)(1.0f, (std::max)(0.0f, (sp - 1.5f) / 1.5f));
            spin = kKd3Spin * (1.0f - t);
            upper = 1.0f + (0.45f - 1.0f) * t;
            lift *= t;
        }
    } else {
        // Away from the blast, the nearest within three blocks in the last second.
        const BlastNote* best = nullptr;
        float bestD = 3.0f * 3.0f;
        for (const BlastNote& bl : g_blasts) {
            if (frame - bl.frame > 30) continue;
            const float dx = gx - bl.x, dz = gz - bl.z, d2 = dx * dx + dz * dz;
            if (d2 < bestD) { bestD = d2; best = &bl; }
        }
        float dx = -hx, dz = -hz, d = 1.5f;
        if (best) {
            dx = gx - best->x; dz = gz - best->z;
            d = std::sqrt(dx * dx + dz * dz);
            if (d < 0.05f) { dx = -hx; dz = -hz; d = 0.05f; }
            else { dx /= d; dz /= d; }
        }
        const float strength = 3.0f * (std::min)(1.0f, (std::max)(0.35f, 1.2f - d / 3.0f));
        vx = dx * strength; vz = dz * strength;
        lift = strength * 0.75f;
        upper = 1.35f;                                       // the upper body goes first: thrown onto his back
    }
    // Sideways a little either way, so no two land the same.
    const float sideX = -vz * 0.25f * jitter, sideZ = vx * 0.25f * jitter;
    // FIX-KNOCKDOWN-3 (kd3_ro4 #2): the slow knock pitches him where there is room. Hit toward a building, the
    // walls stopped the pitch every frame (15 of 17 joints sent back) and she sank into an upright crouch, then
    // stood up without ever lying down. Along the car's travel if the ground a body length that way is clear, else
    // along the wall (the side the jitter picks first; never back onto the car: kd3 harness, a wall 0.4 ahead
    // at 1.6 b/s threw him up onto the bonnet, pelvis 0.74).
    float pitchX = 0.0f, pitchZ = 0.0f;
    if (spin > 0.0f) {
        const float vl = (std::max)(0.05f, std::sqrt(vx * vx + vz * vz));
        const float ux = vx / vl, uz = vz / vl, js = jitter >= 0.0f ? 1.0f : -1.0f;
        const float cand[3][2] = {{ux, uz}, {-uz * js, ux * js}, {uz * js, -ux * js}};
        const Vec3 pel = b.q[kPelvis].p;
        int pick = 0;
        bool found = false;
        for (int c = 0; c < 3 && b.walls && g_devQueries.blocked; ++c) {
            bool clear = true;
            for (float d = 0.15f; d <= 0.46f && clear; d += 0.155f)
                clear = !g_devQueries.blocked(g_devQueries.context, pel.x + cand[c][0] * d, gy + 0.25f, pel.z + cand[c][1] * d);
            if (clear) { pick = c; found = true; break; }
        }
        if (!found && b.walls && g_devQueries.blocked) pick = 1;
        pitchX = cand[pick][0]; pitchZ = cand[pick][1];
        if (pick != 0) Log("ragdoll: start %p: no room ahead, pitched %s", reinterpret_cast<const void*>(ped), found ? "along the wall" : "along the wall (no room anywhere)");
    }
    for (int k = 0; k < kParticles; ++k) {
        const float h = (std::min)(1.0f, (std::max)(0.0f, (b.q[k].p.y - gy) / 0.46f));
        const float f = 1.0f + (upper - 1.0f) * h;
        float pvx = (vx + sideX) * f, pvz = (vz + sideZ) * f;
        if (spin > 0.0f) {
            // The pitch: the head along the car's travel, the feet held back (about 0.3 of his height).
            const float add = spin * 0.46f * (h - 0.3f);
            pvx += pitchX * add; pvz += pitchZ * add;
        }
        const float pvy = lift * (0.6f + 0.6f * h) * (kind == 1 ? 1.0f : 1.0f);
        const float h30 = 1.0f / 30.0f;   // velocity is position minus previous over the step: seeded per 1/30 s
        b.q[k].prev = b.q[k].p - Vec3{pvx, pvy, pvz} * h30;
    }
    b.pose.assign(n, Mat4());
    static int logged = 0;
    if (logged < 200) {
        ++logged;
        Log("ragdoll: start %p (%s) %s at %.2f,%.2f,%.2f throw %.2f,%.2f up %.2f car %p%s", reinterpret_cast<const void*>(ped),
            model.name.c_str(), kind == 1 ? "run over" : "blast", gx, gy, gz, vx, vz, lift,
            reinterpret_cast<const void*>(b.car), b.walls ? "" : " (no wall checks: his spot reads solid)");
    }
    return true;
}

// FIX-KNOCKDOWN-3: the cross-axis hold (see Kd3NoFlip). Positions only, as the links: the speed into the limit goes.
// It only ever lowers joints (the feet for the legs, the pelvis end for the torso): a correction that raised the
// other end climbed the body up a wall a little every iteration when the lowered joint was blocked (harness: a man
// pinned between the bonnet and a wall rose to 0.77 block).
void NoFlip(Particle* q) {
    constexpr float kLegRise = 0.34f;    // sin 20 deg: hips -> feet
    constexpr float kKneeRise = 0.77f;   // sin 50 deg: hips -> knees
    constexpr float kHeadDrop = 0.50f;   // sin 30 deg: pelvis -> neck, downward
    auto rise = [&](int root, int end, float most) {
        const Vec3 d = q[end].p - q[root].p;
        const float len = Len(d);
        if (len < 1e-4f) return;
        const float over = d.y - most * len;
        if (over > 0.0f) q[end].p.y -= over;
    };
    rise(kLHip, kLFoot, kLegRise);
    rise(kRHip, kRFoot, kLegRise);
    rise(kLHip, kLKnee, kKneeRise);
    rise(kRHip, kRKnee, kKneeRise);
    // The torso: the pelvis end down, by how near each joint sits to the pelvis along pelvis -> neck.
    const Vec3 axis = q[kNeck].p - q[kPelvis].p;
    const float len = Len(axis);
    if (len < 1e-4f) return;
    const float under = -kHeadDrop * len - axis.y;
    if (under <= 0.0f) return;
    const Vec3 dir = axis * (1.0f / len);
    static const int kUpper[] = {kPelvis, kChest, kNeck, kLShoulder, kRShoulder, kLHip, kRHip};
    for (int k : kUpper) {
        const float t = (std::min)(1.0f, (std::max)(0.0f, gta2::Dot(q[k].p - q[kPelvis].p, dir) / len));
        q[k].p.y -= under * (1.0f - t);
    }
}

void Step(Body& b, float dt, float gy, uint32_t frame) {
    constexpr float kGravity = 3.0f;    // blocks/s^2 (9.8 m/s^2 is 2.5; a little more reads less floaty)
    constexpr float kSub = 1.0f / 120.0f;
    const int steps = (std::max)(1, (std::min)(12, static_cast<int>(std::ceil(dt / kSub - 1e-3f))));
    const float h = dt / static_cast<float>(steps);
    // The velocities were seeded per 1/30 s; rescale to this step on the first frame.
    if (b.age == 0.0f || b.rescale) {
        b.rescale = false;
        const float r = h * 30.0f;
        for (Particle& p : b.q) p.prev = p.p - (p.p - p.prev) * r;
    }
    // The hitting car this frame: where it ends the frame and its velocity.
    const CarNote* car = nullptr;
    if (b.car && b.age < 0.6f) {
        auto found = g_cars.find(b.car);
        if (found != g_cars.end() && frame - found->second.frame <= 2) car = &found->second;
    }
    Vec3 frameStart[kParticles];
    for (int k = 0; k < kParticles; ++k) frameStart[k] = b.q[k].p;
    // FIX-KNOCKDOWN-2 (pfl65): every other car near him this frame. Before, a second car drove through the lying
    // body; now it shoves him out of its way along the ground (never up onto it, no speed of its own).
    const CarNote* others[8];
    int otherCount = 0;
    for (const auto& c : g_cars) {
        if (otherCount >= 8 || !Kd2Fix()) break;
        if (frame - c.second.frame > 2 || &c.second == car) continue;
        const float dx = c.second.x - b.q[kPelvis].p.x, dz = c.second.z - b.q[kPelvis].p.z;
        const float reach = c.second.halfLen + 0.6f;
        if (dx * dx + dz * dz < reach * reach) others[otherCount++] = &c.second;
    }
    for (int s = 0; s < steps; ++s) {
        for (Particle& p : b.q) {
            const Vec3 v = (p.p - p.prev) * 0.998f;
            p.prev = p.p;
            p.p = p.p + v;
            p.p.y -= kGravity * h * h;
        }
        Mat4 torso;
        for (int it = 0; it < 6; ++it) {
            for (const Link& l : b.links) {
                Vec3 d = b.q[l.b].p - b.q[l.a].p;
                const float len = Len(d);
                if (len < 1e-6f) continue;
                float target = len;
                if (len < l.lo) target = l.lo;
                else if (len > l.hi) target = l.hi;
                else continue;
                const Vec3 corr = d * (0.5f * (len - target) / len);
                b.q[l.a].p = b.q[l.a].p + corr;
                b.q[l.b].p = b.q[l.b].p - corr;
            }
            // Hinges: a knee bends forward, an elbow back, never the other way.
            Vec3 side, up, fwd;
            TorsoFrameAxes(b.q, &side, &up, &fwd);
            fwd = fwd * b.facing;
            auto hinge = [&](int root, int mid, int end, float sign) {
                const Vec3 a = b.q[root].p, e = b.q[end].p;
                const Vec3 ae = e - a;
                const float l2 = gta2::Dot(ae, ae);
                if (l2 < 1e-8f) return;
                const float t = gta2::Dot(b.q[mid].p - a, ae) / l2;
                const Vec3 c = a + ae * t;
                const Vec3 o = b.q[mid].p - c;
                const float along = gta2::Dot(o, fwd) * sign;
                if (along < 0.0f) b.q[mid].p = b.q[mid].p - fwd * (along * sign);
            };
            hinge(kLHip, kLKnee, kLFoot, 1.0f);
            hinge(kRHip, kRKnee, kRFoot, 1.0f);
            hinge(kLShoulder, kLElbow, kLHand, -1.0f);
            hinge(kRShoulder, kRElbow, kRHand, -1.0f);
            if (Kd3NoFlip()) NoFlip(b.q);
            // The car: a box from its sills to the bonnet, the cabin higher in the middle,
            // where it is at this point of the frame.
            if (car) {
                const float u = static_cast<float>(s + 1) / static_cast<float>(steps);
                const float cxNow = car->x - car->vx * dt * (1.0f - u), czNow = car->z - car->vz * dt * (1.0f - u);
                for (int k = 0; k < kParticles; ++k) {
                    Particle& p = b.q[k];
                    const float r = kRadius[k];
                    const float dx = p.p.x - cxNow, dz = p.p.z - czNow;
                    const float lx = dx * car->fx + dz * car->fz, lz = -dx * car->fz + dz * car->fx;
                    const float ox = car->halfLen + r - std::fabs(lx), oz = car->halfWid + r - std::fabs(lz);
                    if (ox <= 0.0f || oz <= 0.0f) continue;
                    const bool cabin = std::fabs(lx) < car->halfLen * 0.35f && std::fabs(lz) < car->halfWid * 0.85f;
                    const float top = gy + (cabin ? 0.34f : 0.20f);
                    if (p.p.y > top + r || p.p.y < gy + 0.05f) continue;
                    const float oy = top + r - p.p.y;
                    // Out by the face it came through: onto the bonnet or roof only from
                    // above (a joint already inside when the game reports the hit - the
                    // car overlaps him by then - goes out the side or the front, not up
                    // on top, which stood him on his head); at most 3 cm an iteration,
                    // so a body that starts deep inside eases out instead of popping.
                    constexpr float kMaxPush = 0.03f;
                    // The push moves the previous position too: getting out of the car adds
                    // no speed of its own (a Verlet position push would, 3.6 blocks/s per 3 cm
                    // at 120 Hz, which spun him over); the car's pace is given below.
                    Vec3 d{0.0f, 0.0f, 0.0f};
                    if (p.prev.y >= top + r - 0.01f && oy <= ox + 0.02f && oy <= oz + 0.02f) {
                        d.y = (std::min)(oy, kMaxPush);
                    } else if (ox <= oz) {
                        const float sgn = lx >= 0.0f ? 1.0f : -1.0f, m = (std::min)(ox, kMaxPush);
                        d.x = car->fx * m * sgn; d.z = car->fz * m * sgn;
                    } else {
                        const float sgn = lz >= 0.0f ? 1.0f : -1.0f, m = (std::min)(oz, kMaxPush);
                        d.x = -car->fz * m * sgn; d.z = car->fx * m * sgn;
                    }
                    p.p = p.p + d;
                    p.prev = p.prev + d;
                    ++b.dbgCar;
                    // Carried along with the car (friction on its body): toward its pace,
                    // once a step.
                    if (it != 0) continue;
                    const float vxNow = (p.p.x - p.prev.x) / h, vzNow = (p.p.z - p.prev.z) / h;
                    const float along = vxNow * car->vx + vzNow * car->vz;
                    const float carSp2 = car->vx * car->vx + car->vz * car->vz;
                    if (carSp2 > 1e-4f && along < carSp2) {
                        const float add = (carSp2 - along) / carSp2 * 0.6f;
                        p.prev.x -= car->vx * add * h; p.prev.z -= car->vz * add * h;
                    }
                }
            }
            // The ground.
            for (int k = 0; k < kParticles; ++k) {
                Particle& p = b.q[k];
                const float floorY = gy + kRadius[k];
                if (p.p.y < floorY) p.p.y = floorY;
            }
        }
        // FIX-KNOCKDOWN-2 (pfl65): the other cars shove the lying body out of their box in one piece, square to
        // their travel toward the side his pelvis is on (or out the nearest side of a still car), at most the car's
        // own pace plus 0.5 block/s: positions and previous positions alike, so no joint gains speed from it (a
        // per-joint push fought the links: kd2_b/kd2_d joints at 18 blocks/s).
        for (int o = 0; o < otherCount; ++o) {
            const CarNote& c = *others[o];
            const float u = static_cast<float>(s + 1) / static_cast<float>(steps);
            const float cxNow = c.x - c.vx * dt * (1.0f - u), czNow = c.z - c.vz * dt * (1.0f - u);
            const float pdx = b.q[kPelvis].p.x - cxNow, pdz = b.q[kPelvis].p.z - czNow;
            const float plz = -pdx * c.fz + pdz * c.fx;
            const float side = plz >= 0.0f ? 1.0f : -1.0f;
            const float sx = -c.fz * side, sz = c.fx * side;   // out of the nearest long side
            float need = 0.0f;
            for (int k = 0; k < kParticles; ++k) {
                const Particle& p = b.q[k];
                const float r = kRadius[k];
                if (p.p.y > gy + 0.34f + r) continue;
                const float dx = p.p.x - cxNow, dz = p.p.z - czNow;
                const float lx = dx * c.fx + dz * c.fz, lz = -dx * c.fz + dz * c.fx;
                if (std::fabs(lx) >= c.halfLen + r || std::fabs(lz) >= c.halfWid + r) continue;
                need = (std::max)(need, c.halfWid + r - lz * side);
            }
            if (need <= 0.0f) continue;
            const float most = (std::sqrt(c.vx * c.vx + c.vz * c.vz) + 0.5f) * h;
            const float m = (std::min)(need, most);
            for (Particle& p : b.q) { p.p.x += sx * m; p.p.z += sz * m; p.prev.x += sx * m; p.prev.z += sz * m; }
            b.startX += sx * m; b.startZ += sz * m;
            ++b.dbgCar; ++b.dbgShove;
        }
        // Contact: a little bounce, and friction along the ground.
        for (int k = 0; k < kParticles; ++k) {
            Particle& p = b.q[k];
            const float floorY = gy + kRadius[k];
            if (p.p.y <= floorY + 1e-4f) {
                const float vy = p.p.y - p.prev.y;
                if (vy < 0.0f) p.prev.y = p.p.y + vy * 0.15f;   // the next step moves him up by 0.15 of the fall
                p.prev.x = p.p.x - (p.p.x - p.prev.x) * 0.92f;
                p.prev.z = p.p.z - (p.p.z - p.prev.z) * 0.92f;
            }
        }
        // FIX-KNOCKDOWN-2 (pfl65): away from the throw and a roll, nothing lifts him: a joint rises no faster than
        // 0.8 block/s (a limb folding over), so no solver pop can throw a lying body into the air.
        if (Kd2Fix() && b.age - b.kickAge > 0.6f) {
            const float cap = 0.8f * h;
            for (Particle& p : b.q)
                if (p.p.y - p.prev.y > cap) p.prev.y = p.p.y - cap;
        }
    }
    // The map's walls: a joint that went into a building goes back to where it was.
    if (b.walls && g_devQueries.blocked) {
        for (int k = 0; k < kParticles; ++k) {
            Particle& p = b.q[k];
            if (g_devQueries.blocked(g_devQueries.context, p.p.x, gy + 0.25f, p.p.z)) {
                ++b.dbgWalls;
                p.p.x = frameStart[k].x; p.p.z = frameStart[k].z;
                p.prev.x = p.p.x; p.prev.z = p.p.z;
            }
        }
    }
    // No further than three blocks from where he went down.
    {
        const float dx = b.q[kPelvis].p.x - b.startX, dz = b.q[kPelvis].p.z - b.startZ;
        if (dx * dx + dz * dz > 9.0f)
            for (Particle& p : b.q) { p.prev.x = p.p.x; p.prev.z = p.p.z; }
    }
    b.age += dt;
    float fastest = 0.0f, high = 0.0f;
    for (int k = 0; k < kParticles; ++k) {
        fastest = (std::max)(fastest, Len(b.q[k].p - frameStart[k]) / (std::max)(dt, 1e-3f));
        high = (std::max)(high, b.q[k].p.y - gy);
    }
    b.maxHeight = (std::max)(b.maxHeight, b.q[kPelvis].p.y - gy);
    b.still = fastest < 0.06f ? b.still + dt : 0.0f;
    if ((b.still > 0.4f && b.age > 0.6f) || b.age > 6.0f) {
        b.settled = true;
        static int logged = 0;
        if (logged < 200) {
            ++logged;
            const float dx = b.q[kPelvis].p.x - b.startX, dz = b.q[kPelvis].p.z - b.startZ;
            Log("ragdoll: settled #%u after %.2f s: carried %.2f blocks, pelvis peaked %.2f above the ground, highest joint now %.2f",
                b.id, b.age, std::sqrt(dx * dx + dz * dz), b.maxHeight, high);
        }
    }
}

// The skeleton from the particles: the torso's turn and place from its frame,
// each limb bone aimed at its particle, every other node carried by its parent
// as in the seed. Written to model space for the pose hook.
void Drive(Body& b, const Rig& rig, const Model& model, const Mat4& world) {
    const size_t n = model.nodes.size();
    const Mat4 torsoNow = TorsoFrame(b.q);
    const Mat4 T = Mul(b.seedTorsoInv, torsoNow);
    std::vector<Mat4> W(n);
    for (int i : rig.order) {
        const int p = model.nodes[i].parent;
        W[i] = (p >= 0 && p < static_cast<int>(n)) ? Mul(b.seedLocal[i], W[p]) : Mul(b.seedWorld[i], T);
        for (int a = 0; a < kAimCount; ++a) {
            if (rig.aimNode[a] != i) continue;
            const Vec3 o = Origin(W[i]);
            const Vec3 predicted = Point(b.aimLocal[a], W[i]);
            TurnAboutOrigin(W[i], FromTo(predicted - o, b.q[kAims[a].target].p - o));
        }
    }
    const Mat4 toModel = InverseAffine(world);
    b.pose.resize(n);
    for (size_t i = 0; i < n; ++i) b.pose[i] = Mul(W[i], toModel);
}

}  // namespace

bool RagdollEnabled() {
    if (g_enabled < 0) {
        g_enabled = 1;
        char path[MAX_PATH] = {};
        HMODULE self = nullptr;
        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               reinterpret_cast<LPCSTR>(&RagdollEnabled), &self) &&
            GetModuleFileNameA(self, path, MAX_PATH)) {
            char* slash = strrchr(path, '\\');
            if (!slash) slash = strrchr(path, '/');
            if (slash) {
                strcpy(slash + 1, "gta2dx9.ini");
                g_enabled = GetPrivateProfileIntA("renderer", "ragdoll", 1, path) != 0 ? 1 : 0;
            }
        }
        const char* env = getenv("GTA2DX9_RAGDOLL");
        if (env && *env) g_enabled = atoi(env) != 0 ? 1 : 0;
        Log("ragdoll: %s", g_enabled ? "on (run over, blown off his feet)" : "off ([renderer] ragdoll=0)");
    }
    return g_enabled == 1;
}

namespace {
int g_kdFull = -1, g_kdHold = -1;
void KnockdownSettings() {
    if (g_kdFull >= 0) return;
    g_kdFull = 1; g_kdHold = 1;
    char path[MAX_PATH] = {};
    HMODULE self = nullptr;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(&KnockdownFullEnabled), &self) &&
        GetModuleFileNameA(self, path, MAX_PATH)) {
        char* slash = strrchr(path, '\\');
        if (!slash) slash = strrchr(path, '/');
        if (slash) {
            strcpy(slash + 1, "gta2dx9.ini");
            g_kdFull = GetPrivateProfileIntA("renderer", "knockdown_full", 1, path) != 0 ? 1 : 0;
            g_kdHold = GetPrivateProfileIntA("renderer", "knockdown_hold_input", 1, path) != 0 ? 1 : 0;
        }
    }
    const char* env = getenv("GTA2DX9_KNOCKDOWN");
    if (env && *env) g_kdFull = atoi(env) != 0 ? 1 : 0;
    Log("knockdown: full sequence %s, player keys held while down %s", g_kdFull ? "on" : "off (as before: up when the game says)",
        g_kdHold ? "on" : "off");
}
}  // namespace

KnockdownEye g_kdEye;
ULONGLONG g_kdEyeTick = 0;
void KnockdownSetEye(const KnockdownEye& eye) { g_kdEye = eye; g_kdEyeTick = GetTickCount64(); }
bool KnockdownPlayerEye(KnockdownEye* eye) {
    if (!g_kdEyeTick || GetTickCount64() - g_kdEyeTick > 150 || g_kdEye.weight <= 0.0f) return false;
    if (eye) *eye = g_kdEye;
    return true;
}

float g_kdBodyX = 0.0f, g_kdBodyZ = 0.0f;
ULONGLONG g_kdBodyTick = 0;
void KnockdownSetBody(float x, float z) { g_kdBodyX = x; g_kdBodyZ = z; g_kdBodyTick = GetTickCount64(); }
bool KnockdownPlayerBody(float* x, float* z) {
    if (!g_kdBodyTick || GetTickCount64() - g_kdBodyTick > 150) return false;
    *x = g_kdBodyX; *z = g_kdBodyZ;
    return true;
}

bool KnockdownFullEnabled() { KnockdownSettings(); return g_kdFull == 1; }
bool KnockdownHoldInputEnabled() { KnockdownSettings(); return g_kdFull == 1 && g_kdHold == 1; }

void RagdollNoteCar(uintptr_t object, const float corners[4][3], uint32_t frame) {
    if (!object) return;
    // The quad's two edges: from corner 0, the nearest two others (the far one is the diagonal).
    float d[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    for (int i = 1; i < 4; ++i) {
        const float dx = corners[i][0] - corners[0][0], dz = corners[i][2] - corners[0][2];
        d[i] = dx * dx + dz * dz;
    }
    int diag = 1;
    for (int i = 2; i < 4; ++i) if (d[i] > d[diag]) diag = i;
    int e1 = diag == 1 ? 2 : 1, e2 = 6 - diag - e1;
    if (d[e1] < d[e2]) std::swap(e1, e2);   // e1 the long edge: the car's length
    const float lx = corners[e1][0] - corners[0][0], lz = corners[e1][2] - corners[0][2];
    const float len = std::sqrt(lx * lx + lz * lz), wid = std::sqrt(d[e2]);
    if (len < 0.05f || len > 4.0f) return;
    CarNote& c = g_cars[object];
    const float x = 0.25f * (corners[0][0] + corners[1][0] + corners[2][0] + corners[3][0]);
    const float z = 0.25f * (corners[0][2] + corners[1][2] + corners[2][2] + corners[3][2]);
    if (c.frame && frame > c.frame && frame - c.frame < 6) {
        const float span = static_cast<float>(frame - c.frame) / 30.0f;
        const float vx = (x - c.x) / span, vz = (z - c.z) / span;
        if (vx * vx + vz * vz < 12.0f * 12.0f) {   // not a respawn or a warp
            c.vx += (vx - c.vx) * 0.6f;
            c.vz += (vz - c.vz) * 0.6f;
        }
    } else if (c.frame != frame) {
        c.vx = c.vz = 0.0f;
    }
    c.x = x; c.z = z;
    c.fx = lx / len; c.fz = lz / len;
    c.halfLen = 0.5f * len; c.halfWid = 0.5f * wid;
    c.frame = frame;
}

void RagdollNoteBlast(float x, float y, float z, float size, uint32_t frame) {
    if (g_blasts.size() >= 16) g_blasts.erase(g_blasts.begin());
    g_blasts.push_back({x, y, z, size, frame});
}

bool RagdollFigure(uintptr_t ped, int kind, bool down, const Model& model, const Mat4& world, float gx, float gy,
                   float gz, float heading, float dt, uint32_t frame, const ModelAnimation* a, float ta,
                   const ModelAnimation* sb, float tb, float w) {
    if (!ped) return false;
    auto found = g_bodies.find(ped);
    if (!RagdollEnabled()) return false;
    if (!down) {
        if (found == g_bodies.end()) return false;
        Body& b = found->second;
        if (b.release <= 0.0f) {
            // Up again: the game stands him up (the lying clip played back); the ragdoll's
            // pose is blended into it over 0.3 s instead of dropped in a frame.
            b.release = kReleaseSecs;
            Log("ragdoll: #%u gets up after %.2f s (blended back to the clips over %.1f s)", b.id, b.age, kReleaseSecs);
            // FIX-KNOCKDOWN: the get-up may place and turn the figure onto the body (a new world): the
            // lying pose is carried into it, so the blend starts from where the body is drawn.
            const Rig& rig = RigFor(model);
            if (rig.ok && b.model == &model) { Drive(b, rig, model, world); b.lastWorld = world; }
        } else if (b.seen != frame) {
            b.release -= (std::min)(dt, 0.1f);
        }
        if (b.release <= 0.0f || b.model != &model) { g_bodies.erase(found); return false; }
        b.seen = frame;
        ++b.gen;
        g_hookBody = &b;
        ModelSetPoseHook(&PoseHook, &b, (static_cast<uint64_t>(b.id) << 24) | (b.gen & 0xFFFFFFu));
        return true;
    }
    if (found != g_bodies.end() && found->second.release > 0.0f) { g_bodies.erase(found); found = g_bodies.end(); }
    if (found != g_bodies.end() && found->second.model != &model) { g_bodies.erase(found); found = g_bodies.end(); }
    if (found == g_bodies.end()) {
        if (kind != 1 && kind != 2) return false;
        const Rig& rig = RigFor(model);
        if (!rig.ok) return false;
        Body body;
        if (!Seed(body, ped, kind, model, rig, world, gx, gy, gz, heading, frame, a, ta, sb, tb, w)) return false;
        found = g_bodies.emplace(ped, std::move(body)).first;
    }
    Body& b = found->second;
    const Rig& rig = RigFor(model);
    // The game moved him (the knock-down slide, a body pushed): the ragdoll goes with it.
    const float mx = gx - b.anchorX, mz = gz - b.anchorZ;
    b.dbgWalls = b.dbgCar = b.dbgShove = 0; b.dbgDrift = 0.0f; b.dbgMove = std::sqrt(mx * mx + mz * mz);
    if (mx != 0.0f || mz != 0.0f) {
        if (mx * mx + mz * mz < 1.0f) {
            for (Particle& p : b.q) { p.p.x += mx; p.p.z += mz; p.prev.x += mx; p.prev.z += mz; }
            b.startX += mx; b.startZ += mz;
        }
        b.anchorX = gx; b.anchorZ = gz;
        b.settled = b.settled && mx * mx + mz * mz < 1e-6f;
    }
    // FIX-KNOCKDOWN-2 (pfl65): the floor is the ground he went down on; the game's height for him jitters with its
    // state. A real change of level (the game carried him onto a kerb or a step, 0.15+) moves the body with it.
    const bool s_groundLatch = Kd2Fix();
    if (s_groundLatch) {
        const float dy = gy - b.groundY;
        if (std::fabs(dy) > 0.15f && std::fabs(dy) < 1.0f) {
            for (Particle& p : b.q) { p.p.y += dy; p.prev.y += dy; }
            b.groundY = gy;
            b.settled = false;
        }
        gy = b.groundY;
    }
    // A moving car reaching a still body wakes it (to be shoved out of the way, above).
    if (b.settled && s_groundLatch) {
        for (const auto& c : g_cars) {
            if (frame - c.second.frame > 2 || c.second.vx * c.second.vx + c.second.vz * c.second.vz < 0.09f) continue;
            const float dx = b.q[kPelvis].p.x - c.second.x, dz = b.q[kPelvis].p.z - c.second.z;
            const float lx = dx * c.second.fx + dz * c.second.fz, lz = -dx * c.second.fz + dz * c.second.fx;
            if (std::fabs(lx) < c.second.halfLen + 0.3f && std::fabs(lz) < c.second.halfWid + 0.3f) {
                b.settled = false; b.still = 0.0f;
                break;
            }
        }
    }
    bool stepped = false;
    if (b.rollLeft > 0.0f) {
        if (dt > 0.0f && b.seen != frame) { RollFrame(b, (std::min)(dt, 0.1f), gy); stepped = true; }
    } else if (!b.settled && dt > 0.0f && b.seen != frame) { Step(b, (std::min)(dt, 0.1f), gy, frame); stepped = true; }
    // FIX-KNOCKDOWN (kd_t2 #2): never far from the game's spot for him. A truck dragged the player 2.7 blocks one
    // way while the throw carried the body the other: it lay 1.9 blocks off, out of the camera's picture, and
    // the get-up had to walk all of that back. Past kMaxDrift the whole body is carried along (dragged).
    {
        // FIX-KNOCKDOWN-2: while another car shoves him the leash gives (to 1.6), so it does not pull him back under
        // the car; then it shortens at 0.4 block/s (a slow drag, not a jump).
        const float dx = b.q[kPelvis].p.x - gx, dz = b.q[kPelvis].p.z - gz, d = std::sqrt(dx * dx + dz * dz);
        if (b.dbgShove > 0) b.leash = (std::min)(1.6f, (std::max)(b.leash, d));
        else if (b.leash > 0.9f) b.leash = (std::max)(0.9f, (std::max)(b.leash - 0.4f * (std::min)(dt, 0.1f), (std::min)(d, b.leash)));
        const float kMaxDrift = b.leash;
        if (d > kMaxDrift) {
            const float k = (d - kMaxDrift) / d, sx = -dx * k, sz = -dz * k;
            b.dbgDrift = d - kMaxDrift;
            for (Particle& p : b.q) { p.p.x += sx; p.p.z += sz; p.prev.x += sx; p.prev.z += sz; }
            b.startX += sx; b.startZ += sz;
            stepped = true;
        }
    }
    // FIX-KNOCKDOWN-2 (pfl65): per-frame trace of the solver body (GTA2DX9_LOG_KD=1).
    static const bool kdTrace = [] { const char* e = getenv("GTA2DX9_LOG_KD"); return e && *e == '1'; }();
    if (kdTrace && stepped) {
        float vmax = 0.0f, vup = -1e9f, top = -1e9f;
        const float hd = 1.0f / 120.0f;
        for (int k = 0; k < kParticles; ++k) {
            const Vec3 v = (b.q[k].p - b.q[k].prev) * (1.0f / hd);
            vmax = (std::max)(vmax, Len(v)); vup = (std::max)(vup, v.y); top = (std::max)(top, b.q[k].p.y - gy);
        }
        // FIX-KNOCKDOWN-3: the head, the higher foot, the torso's up (1 upright, -1 on his head) and whether a leg
        // points within 35 deg of straight up (hips -> foot): the handstand measured on every body, on camera or not.
        Vec3 ts, tu, tf;
        TorsoFrameAxes(b.q, &ts, &tu, &tf);
        auto legUp = [&](int hip, int foot) {
            const Vec3 d = b.q[foot].p - b.q[hip].p;
            const float l = Len(d);
            return l > 1e-4f && d.y > 0.819f * l;
        };
        Log("kdtrace: f=%u #%u age %.2f pel %.2f,%.3f,%.2f gy %.3f top %.3f vmax %.2f vup %.2f anchor %.2f,%.2f moved %.3f drift %.3f walls %d car %d settled %d head %.3f foot %.3f tup %.2f legup %d",
            frame, b.id, b.age, b.q[kPelvis].p.x, b.q[kPelvis].p.y - gy, b.q[kPelvis].p.z, gy, top, vmax, vup, gx, gz, b.dbgMove,
            b.dbgDrift, b.dbgWalls, b.dbgCar, b.settled ? 1 : 0, b.q[kHead].p.y - gy,
            (std::max)(b.q[kLFoot].p.y, b.q[kRFoot].p.y) - gy, tu.y, (legUp(kLHip, kLFoot) ? 1 : 0) + (legUp(kRHip, kRFoot) ? 1 : 0));
    }
    bool turned = false;   // the placement changed (it carries the pose to model space)
    for (int r = 0; r < 4 && !turned; ++r)
        for (int c = 0; c < 3; ++c) if (std::fabs(world.m[r][c] - b.lastWorld.m[r][c]) > 1e-4f) { turned = true; break; }
    if (stepped || turned || b.gen == 0) {
        // The pose key changes only while he moves: once still, one cached pose.
        Drive(b, rig, model, world);
        b.lastWorld = world;
        ++b.gen;
    }
    b.seen = frame;
    g_hookBody = &b;
    ModelSetPoseHook(&PoseHook, &b, (static_cast<uint64_t>(b.id) << 24) | (b.gen & 0xFFFFFFu));
    return true;
}

bool RagdollQuery(uintptr_t ped, RagdollInfo* out) {
    auto found = g_bodies.find(ped);
    if (found == g_bodies.end() || !out) return false;
    const Body& b = found->second;
    out->settled = b.settled;
    out->releasing = b.release > 0.0f;
    out->age = b.age;
    out->pelvis[0] = b.q[kPelvis].p.x; out->pelvis[1] = b.q[kPelvis].p.y; out->pelvis[2] = b.q[kPelvis].p.z;
    out->head[0] = b.q[kHead].p.x; out->head[1] = b.q[kHead].p.y; out->head[2] = b.q[kHead].p.z;
    Vec3 side, up, fwd;
    TorsoFrameAxes(b.q, &side, &up, &fwd);
    out->faceUp = fwd.y * b.facing >= 0.0f;
    out->chestUp = fwd.y * b.facing;
    return true;
}

bool RagdollRollOver(uintptr_t ped) {
    auto found = g_bodies.find(ped);
    if (found == g_bodies.end()) return false;
    Body& b = found->second;
    if (b.release > 0.0f) return false;
    Vec3 side, up, fwd;
    TorsoFrameAxes(b.q, &side, &up, &fwd);
    Vec3 axis = b.q[kHead].p - b.q[kPelvis].p;
    axis.y = 0.0f;
    if (Len(axis) < 1e-3f) return false;
    axis = gta2::Normalize(axis);
    // Over the side the chest already leans to (the shorter way over), else his right.
    Vec3 across = gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, axis);   // horizontal, square to the body
    const Vec3 chest = fwd * b.facing;
    const float lean = gta2::Dot(chest, across);
    const float dir = lean >= 0.0f ? 1.0f : -1.0f;
    // Turn rate about the long axis (half a turn in ~0.45 s) about the line along the ground on the side
    // he rolls to, plus a small lift so the shoulder clears the road.
    const float omega = -8.5f * dir;   // axis x up = -across: the chest goes toward +across * dir
    if (Kd2Roll()) {
        // Played: half a turn about the line through the middle of his torso at the height it lies, over 0.7 s,
        // moving 0.12 block toward the side he rolls to; the ground under him, never a lift.
        Vec3 mid = (b.q[kPelvis].p + b.q[kChest].p) * 0.5f;
        b.rollCentre = mid;
        b.rollAxis = axis;
        b.rollAngle = -3.14159265f * dir;
        b.rollShift = across * (0.12f * dir);
        b.rollDur = b.rollLeft = 0.7f;
        for (int k = 0; k < kParticles; ++k) { b.rollFrom[k] = b.q[k].p; b.q[k].prev = b.q[k].p; }
        b.settled = false;
        b.still = 0.0f;
        b.age = (std::max)(b.age, 0.61f);
        Log("ragdoll: #%u rolls over onto his front, played over %.1f s (lean %.2f)", b.id, b.rollDur, lean);
        return true;
    }
    Vec3 centre = (b.q[kPelvis].p + b.q[kChest].p) * 0.5f;
    centre = centre + across * (0.05f * dir);
    const float h30 = 1.0f / 30.0f;
    for (int k = 0; k < kParticles; ++k) {
        const Vec3 r = b.q[k].p - centre;
        Vec3 v = gta2::Cross(axis * omega, r);
        v.y += 0.45f;
        b.q[k].prev = b.q[k].p - v * h30;
    }
    b.settled = false;
    b.still = 0.0f;
    b.age = (std::max)(b.age, 0.61f);
    b.kickAge = b.age;
    b.rescale = true;
    Log("ragdoll: #%u rolls over onto his front (lean %.2f)", b.id, lean);
    return true;
}

void RagdollDone() {
    g_hookBody = nullptr;
    ModelSetPoseHook(nullptr, nullptr, 0);
}

void RagdollEndFrame(uint32_t frame) {
    for (auto it = g_bodies.begin(); it != g_bodies.end();)
        it = frame - it->second.seen > 300 ? g_bodies.erase(it) : std::next(it);
    for (auto it = g_cars.begin(); it != g_cars.end();)
        it = frame - it->second.frame > 90 ? g_cars.erase(it) : std::next(it);
}

// FIX-PERF-4: this module's caches for the `mem:` lines (mem_stats.h).
void RagdollMemGauges() {
    MemGauge("rd.bodies", static_cast<double>(g_bodies.size()));
    MemGauge("rd.cars", static_cast<double>(g_cars.size()));
    MemGauge("rd.rigs", static_cast<double>(g_rigs.size()));
}

}  // namespace gta2dx9
