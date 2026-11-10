// ANIM-WEAPONS: weapon handling on the street-view figures (see weapon_rig.h).
#include "weapon_rig.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <unordered_map>
#include <vector>

#include "log.h"
#include "model_store.h"

namespace gta2dx9 {
namespace weaponrig {
namespace {

using gta2::Mat4;
using gta2::Vec3;

constexpr float kDeg = 3.14159265f / 180.0f;

// PedWeapon numbering (live_geometry.cpp kWeapons).
enum { wPistol = 1, wDual = 2, wSilenced = 3, wMg = 4, wRocket = 5, wElectro = 6, wMolotov = 7, wGrenade = 8, wShotgun = 9, wFlame = 10 };
enum Class { cNone, cPistol, cDual, cRifle, cShotgun, cLauncher, cFlame, cThrow };

int ClassOf(int weapon) {
    switch (weapon) {
        case wPistol: return cPistol;
        case wDual: return cDual;
        case wSilenced: case wMg: case wElectro: return cRifle;
        case wShotgun: return cShotgun;
        case wRocket: return cLauncher;
        case wFlame: return cFlame;
        case wMolotov: case wGrenade: return cThrow;
        default: return cNone;
    }
}

// ---- small vector maths (column vectors, v' = M v) -------------------------
Vec3 V(float x, float y, float z) { return {x, y, z}; }
float Len(const Vec3& v) { return std::sqrt(gta2::Dot(v, v)); }
Vec3 Nrm(const Vec3& v) { const float l = Len(v); return l > 1e-8f ? v * (1.0f / l) : V(0, 0, 0); }
Vec3 Mix(const Vec3& a, const Vec3& b, float t) { return a + (b - a) * t; }
float Smooth(float t) { t = (std::max)(0.0f, (std::min)(1.0f, t)); return t * t * (3.0f - 2.0f * t); }

struct M3 { float m[3][3]; };
M3 Ident() { M3 q{}; q.m[0][0] = q.m[1][1] = q.m[2][2] = 1.0f; return q; }
Vec3 Mul(const M3& q, const Vec3& v) {
    return V(q.m[0][0] * v.x + q.m[0][1] * v.y + q.m[0][2] * v.z,
             q.m[1][0] * v.x + q.m[1][1] * v.y + q.m[1][2] * v.z,
             q.m[2][0] * v.x + q.m[2][1] * v.y + q.m[2][2] * v.z);
}
M3 Mul(const M3& a, const M3& b) {
    M3 o{};
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c)
        for (int k = 0; k < 3; ++k) o.m[r][c] += a.m[r][k] * b.m[k][c];
    return o;
}
// Rodrigues: about the unit axis k by a radians (k x v is the direction a small
// positive turn moves v).
M3 AxisAngle(const Vec3& k, float a) {
    const float c = std::cos(a), s = std::sin(a), t = 1.0f - c;
    M3 q;
    q.m[0][0] = c + t * k.x * k.x;       q.m[0][1] = t * k.x * k.y - s * k.z; q.m[0][2] = t * k.x * k.z + s * k.y;
    q.m[1][0] = t * k.y * k.x + s * k.z; q.m[1][1] = c + t * k.y * k.y;       q.m[1][2] = t * k.y * k.z - s * k.x;
    q.m[2][0] = t * k.z * k.x - s * k.y; q.m[2][1] = t * k.z * k.y + s * k.x; q.m[2][2] = c + t * k.z * k.z;
    return q;
}
// The turn that takes direction a toward direction b by the angle `a` (radians).
M3 Toward(const Vec3& a, const Vec3& b, float angle) {
    const Vec3 k = Nrm(gta2::Cross(a, b));
    if (Len(k) < 0.5f) return Ident();
    return AxisAngle(k, angle);
}
// The shortest turn taking unit a onto unit b.
M3 FromTo(const Vec3& a, const Vec3& b) {
    const Vec3 c = gta2::Cross(a, b);
    const float s = Len(c), d = gta2::Dot(a, b);
    if (s < 1e-6f) return Ident();   // parallel (anti-parallel never asked for here)
    return AxisAngle(c * (1.0f / s), std::atan2(s, d));
}
// The basis (columns x, y, x cross y) of a direction and a second one made square to it.
M3 Basis(const Vec3& x, const Vec3& y) {
    const Vec3 a = Nrm(x);
    const Vec3 b = Nrm(y - a * gta2::Dot(a, y));
    const Vec3 c = gta2::Cross(a, b);
    M3 q;
    q.m[0][0] = a.x; q.m[1][0] = a.y; q.m[2][0] = a.z;
    q.m[0][1] = b.x; q.m[1][1] = b.y; q.m[2][1] = b.z;
    q.m[0][2] = c.x; q.m[1][2] = c.y; q.m[2][2] = c.z;
    return q;
}
M3 Transpose(const M3& q) { M3 t; for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) t.m[r][c] = q.m[c][r]; return t; }
// The turn that takes the pair (x, y) onto (x2, y2).
M3 Align(const Vec3& x, const Vec3& y, const Vec3& x2, const Vec3& y2) { return Mul(Basis(x2, y2), Transpose(Basis(x, y))); }
// A fraction of a turn (axis-angle scaled).
M3 Part(const M3& q, float w) {
    if (w >= 0.999f) return q;
    if (w <= 0.001f) return Ident();
    const float tr = q.m[0][0] + q.m[1][1] + q.m[2][2];
    const float ang = std::acos((std::max)(-1.0f, (std::min)(1.0f, 0.5f * (tr - 1.0f))));
    if (ang < 1e-4f) return Ident();
    Vec3 k = V(q.m[2][1] - q.m[1][2], q.m[0][2] - q.m[2][0], q.m[1][0] - q.m[0][1]);
    if (Len(k) < 1e-5f) return w > 0.5f ? q : Ident();   // a half turn: no unique axis
    return AxisAngle(Nrm(k), ang * w);
}

Vec3 Pos(const std::vector<Mat4>& W, int i) { return V(W[i].m[3][0], W[i].m[3][1], W[i].m[3][2]); }
Vec3 Row(const std::vector<Mat4>& W, int i, int r) { return Nrm(V(W[i].m[r][0], W[i].m[r][1], W[i].m[r][2])); }

// ---- the skeleton, once per model -----------------------------------------
struct Skel {
    bool ok = false;
    int sp1 = -1, sp2 = -1, neck = -1, head = -1;
    int clav[2] = {-1, -1}, up[2] = {-1, -1}, fo[2] = {-1, -1}, hand[2] = {-1, -1};   // [0] right, [1] left
    int fing[2][5][3];
    std::vector<std::vector<int>> sub;   // each node's subtree (itself first)
    Vec3 right{1, 0, 0}, fwd{0, 0, 1}, up3{0, 1, 0};
    int headAxis = 1; float headSign = 1.0f;
    float armLen = 0.5f;
    float upm = 1.0f;   // model units per metre (the arm measured against 0.53 m)
};
std::unordered_map<const Model*, Skel> g_skels;

int Find(const Model& m, const char* name) {
    for (size_t i = 0; i < m.nodes.size(); ++i) if (strcmp(m.nodes[i].name, name) == 0) return static_cast<int>(i);
    return -1;
}

const Skel& SkelFor(const Model& model) {
    auto it = g_skels.find(&model);
    if (it != g_skels.end()) return it->second;
    Skel& s = g_skels[&model];
    const char* side[2] = {"R", "L"};
    char buf[48];
    s.sp1 = Find(model, "Bip01 Spine1"); s.sp2 = Find(model, "Bip01 Spine2");
    s.neck = Find(model, "Bip01 Neck"); s.head = Find(model, "Bip01 Head");
    bool ok = s.sp1 >= 0 && s.sp2 >= 0 && s.head >= 0;
    for (int h = 0; h < 2; ++h) {
        snprintf(buf, sizeof buf, "Bip01 %s Clavicle", side[h]); s.clav[h] = Find(model, buf);
        snprintf(buf, sizeof buf, "Bip01 %s UpperArm", side[h]); s.up[h] = Find(model, buf);
        snprintf(buf, sizeof buf, "Bip01 %s Forearm", side[h]); s.fo[h] = Find(model, buf);
        snprintf(buf, sizeof buf, "Bip01 %s Hand", side[h]); s.hand[h] = Find(model, buf);
        ok = ok && s.up[h] >= 0 && s.fo[h] >= 0 && s.hand[h] >= 0;
        for (int f = 0; f < 5; ++f) {
            snprintf(buf, sizeof buf, "Bip01 %s Finger%d", side[h], f); s.fing[h][f][0] = Find(model, buf);
            snprintf(buf, sizeof buf, "Bip01 %s Finger%d1", side[h], f); s.fing[h][f][1] = Find(model, buf);
            snprintf(buf, sizeof buf, "Bip01 %s Finger%d2", side[h], f); s.fing[h][f][2] = Find(model, buf);
        }
    }
    const size_t n = model.nodes.size();
    std::vector<std::vector<int>> kids(n);
    for (size_t i = 0; i < n; ++i) {
        const int p = model.nodes[i].parent;
        if (p >= 0 && p < static_cast<int>(n)) kids[p].push_back(static_cast<int>(i));
    }
    s.sub.resize(n);
    for (size_t i = 0; i < n; ++i) {
        std::vector<int>& out = s.sub[i];
        out.push_back(static_cast<int>(i));
        for (size_t k = 0; k < out.size(); ++k) for (int c : kids[out[k]]) out.push_back(c);
    }
    if (ok) {
        std::vector<Mat4> rest;
        ModelRestNodeWorlds(model, &rest);
        Vec3 r = Pos(rest, s.up[0]) - Pos(rest, s.up[1]);
        r.y = 0.0f;
        s.right = Nrm(r);
        s.fwd = V(0, 0, model.forward);
        s.up3 = V(0, 1, 0);
        // The head's own axis that looks ahead.
        float best = 0.0f;
        for (int a = 0; a < 3; ++a) {
            const float d = gta2::Dot(Row(rest, s.head, a), s.fwd);
            if (std::fabs(d) > best) { best = std::fabs(d); s.headAxis = a; s.headSign = d < 0.0f ? -1.0f : 1.0f; }
        }
        s.armLen = Len(Pos(rest, s.fo[0]) - Pos(rest, s.up[0])) + Len(Pos(rest, s.hand[0]) - Pos(rest, s.fo[0]));
        s.upm = s.armLen > 1e-3f ? s.armLen / 0.53f : 1.0f;
        static int logged = 0;
        if (logged < 4) {
            ++logged;
            Log("weapon rig: skeleton ok, right %.2f,%.2f,%.2f fwd %.0f head axis %d%s arm %.3f, fingers %d", s.right.x, s.right.y, s.right.z,
                model.forward, s.headAxis, s.headSign < 0 ? "-" : "+", s.armLen, s.fing[0][1][0] >= 0 ? 1 : 0);
        }
    } else {
        Log("weapon rig: a model without the Biped arms (%zu nodes): not rigged", n);
    }
    s.ok = ok;
    return s;
}

void Turn(std::vector<Mat4>& W, const Skel& s, int node, const Vec3& pivot, const M3& q) {
    if (node < 0) return;
    for (int i : s.sub[node]) {
        Mat4& m = W[i];
        for (int r = 0; r < 3; ++r) {
            const Vec3 a = Mul(q, V(m.m[r][0], m.m[r][1], m.m[r][2]));
            m.m[r][0] = a.x; m.m[r][1] = a.y; m.m[r][2] = a.z;
        }
        const Vec3 p = pivot + Mul(q, V(m.m[3][0], m.m[3][1], m.m[3][2]) - pivot);
        m.m[3][0] = p.x; m.m[3][1] = p.y; m.m[3][2] = p.z;
    }
}

// The neck joint and the head turned, not the clavicles (in the Biped they hang off the
// neck: turning its whole subtree would carry the arms off the gun).
void TurnNeck(std::vector<Mat4>& W, const Skel& s, const M3& q) {
    if (s.neck < 0) return;
    const Vec3 pv = Pos(W, s.neck);
    std::vector<int> nodes{s.neck};
    if (s.head >= 0) nodes.insert(nodes.end(), s.sub[s.head].begin(), s.sub[s.head].end());
    for (int i : nodes) {
        Mat4& m = W[i];
        for (int r = 0; r < 3; ++r) {
            const Vec3 a = Mul(q, V(m.m[r][0], m.m[r][1], m.m[r][2]));
            m.m[r][0] = a.x; m.m[r][1] = a.y; m.m[r][2] = a.z;
        }
        const Vec3 p = pv + Mul(q, V(m.m[3][0], m.m[3][1], m.m[3][2]) - pv);
        m.m[3][0] = p.x; m.m[3][1] = p.y; m.m[3][2] = p.z;
    }
}

// Two-bone IK: the wrist of side h to `target`, the elbow toward `pole`, then the
// hand turned so its fingers (x) run along `fingers` and its palm (y) faces `palm`.
void SolveArm(std::vector<Mat4>& W, const Skel& s, int h, Vec3 target, const Vec3& pole, const Vec3& fingers, const Vec3& palm, float w) {
    if (w <= 0.01f) return;
    const int u = s.up[h], f = s.fo[h], k = s.hand[h];
    const Vec3 S = Pos(W, u), E = Pos(W, f), H = Pos(W, k);
    target = Mix(H, target, w);
    const float a = Len(E - S), b = Len(H - E);
    Vec3 d = target - S;
    float dl = Len(d);
    if (dl < 1e-4f || a < 1e-4f || b < 1e-4f) return;
    const Vec3 dir = d * (1.0f / dl);
    dl = (std::max)(std::fabs(a - b) + 0.01f, (std::min)(dl, (a + b) * 0.995f));
    Vec3 pv = pole - dir * gta2::Dot(pole, dir);
    if (Len(pv) < 1e-4f) pv = (E - S) - dir * gta2::Dot(E - S, dir);
    pv = Nrm(pv);
    const float cosA = (std::max)(-1.0f, (std::min)(1.0f, (a * a + dl * dl - b * b) / (2.0f * a * dl)));
    const Vec3 E2 = S + (dir * cosA + pv * std::sqrt((std::max)(0.0f, 1.0f - cosA * cosA))) * a;
    Turn(W, s, u, S, FromTo(Nrm(E - S), Nrm(E2 - S)));
    const Vec3 Ew = Pos(W, f), Hw = Pos(W, k);
    const Vec3 T2 = S + dir * dl;
    Turn(W, s, f, Ew, FromTo(Nrm(Hw - Ew), Nrm(T2 - Ew)));
    // The hand: most of its turn about the forearm's axis is the forearm's own
    // (the wrist does not twist), the rest a bend at the wrist.
    const Vec3 hx = Row(W, k, 0), hy = Row(W, k, 1);
    const M3 full = Part(Align(hx, hy, fingers, palm), w);
    const Vec3 axis = Nrm(Pos(W, k) - Pos(W, f));
    // Twist part of `full` about the forearm (swing-twist), 60 % of it given to the forearm.
    const Vec3 ref = Nrm(hy - axis * gta2::Dot(hy, axis));
    Vec3 moved = Mul(full, hy);
    moved = Nrm(moved - axis * gta2::Dot(moved, axis));
    if (Len(ref) > 0.5f && Len(moved) > 0.5f) {
        const float tw = std::atan2(gta2::Dot(gta2::Cross(ref, moved), axis), gta2::Dot(ref, moved));
        Turn(W, s, f, Pos(W, f), AxisAngle(axis, 0.6f * tw));
    }
    const Vec3 hx2 = Row(W, k, 0), hy2 = Row(W, k, 1);
    Turn(W, s, k, Pos(W, k), Part(Align(hx2, hy2, fingers, palm), w));
}

// Each finger joint bent to an angle (degrees) off its parent, in the parent's bending
// plane (its x toward its y: toward the palm), blended by w.
void Curl(std::vector<Mat4>& W, const Skel& s, int h, int finger, const float deg[3], float w) {
    for (int seg = 0; seg < 3; ++seg) {
        const int c = s.fing[h][finger][seg];
        const int p = seg == 0 ? s.hand[h] : s.fing[h][finger][seg - 1];
        if (c < 0 || p < 0) return;
        const Vec3 px = Row(W, p, 0), py = Row(W, p, 1), cx = Row(W, c, 0);
        const float now = std::atan2(gta2::Dot(cx, py), gta2::Dot(cx, px));
        const float want = deg[seg] * kDeg;
        const Vec3 k = Nrm(gta2::Cross(px, py));
        Turn(W, s, c, Pos(W, c), AxisAngle(k, (want - now) * w));
    }
}
void Thumb(std::vector<Mat4>& W, const Skel& s, int h, const float deg[3], float w) {
    for (int seg = 0; seg < 3; ++seg) {
        const int c = s.fing[h][0][seg];
        if (c < 0) return;
        Turn(W, s, c, Pos(W, c), Toward(Row(W, c, 0), Row(W, c, 1), deg[seg] * kDeg * w));
    }
}

// The head turned to look at a point (its forward axis toward it), share w.
void LookAt(std::vector<Mat4>& W, const Skel& s, const Vec3& target, float w, float rollDeg, const Vec3& rollAxisHint) {
    if (s.head < 0 || w <= 0.01f) return;
    const Vec3 hp = Pos(W, s.head);
    const Vec3 cur = Row(W, s.head, s.headAxis) * s.headSign;
    const Vec3 want = Nrm(target - hp);
    M3 q = Part(FromTo(cur, want), w);
    if (s.neck >= 0) {
        // 35 % in the neck, the rest in the head.
        TurnNeck(W, s, Part(q, 0.35f));
        const Vec3 cur2 = Row(W, s.head, s.headAxis) * s.headSign;
        q = Part(FromTo(cur2, want), w);
    }
    Turn(W, s, s.head, Pos(W, s.head), q);
    if (std::fabs(rollDeg) > 0.1f) Turn(W, s, s.head, Pos(W, s.head), AxisAngle(Nrm(rollAxisHint), rollDeg * kDeg * w));
}

// ---- per figure ---------------------------------------------------------------
struct Params {   // recoil, per class
    float freq, damp, impulse;
    float back, rise, side;          // gun: metres back, degrees of muzzle climb, degrees of lateral jitter
    float spine, shoulder, head;     // degrees: chest back, right shoulder driven back, head nod
    float shove;                     // metres the figure is pushed back
};
Params ParamsFor(int weapon) {
    switch (weapon) {
        case wPistol: case wDual: return {24.0f, 0.42f, 1.0f, 0.035f, 10.0f, 1.0f, 2.5f, 2.0f, 2.5f, 0.012f};
        case wSilenced:          return {30.0f, 0.55f, 0.6f, 0.018f, 3.0f, 1.2f, 1.5f, 2.5f, 1.0f, 0.004f};
        case wMg:                return {30.0f, 0.55f, 0.75f, 0.028f, 4.5f, 1.8f, 2.2f, 4.0f, 1.5f, 0.007f};
        case wElectro:           return {30.0f, 0.60f, 0.35f, 0.012f, 2.0f, 0.8f, 1.0f, 1.5f, 0.5f, 0.002f};
        case wShotgun:           return {17.0f, 0.38f, 1.0f, 0.065f, 14.0f, 1.5f, 7.0f, 10.0f, 5.0f, 0.040f};
        case wRocket:            return {13.0f, 0.50f, 1.0f, 0.050f, 5.0f, 0.5f, 6.0f, 7.0f, 3.0f, 0.045f};
        case wFlame:             return {20.0f, 0.70f, 0.12f, 0.010f, 1.0f, 1.5f, 0.5f, 0.5f, 0.0f, 0.0f};
        default:                 return {20.0f, 0.60f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    }
}

struct State {
    uint32_t seen = 0;
    uint32_t muzzleFrame = 0;
    float x = 0.0f, v = 0.0f;   // the recoil spring (about 1 at the peak of one shot)
    float side = 0.0f;          // this shot's lateral jitter, -1..1
    float sinceShot = 10.0f;    // seconds
    int mode = kOff, prevMode = kOff;
    float blend = 1.0f;         // prevMode -> mode
    float weight = 0.0f;        // the rig's own weight (fades in and out)
    int weapon = 0;
    uint32_t rng = 1;
};
std::unordered_map<uintptr_t, State> g_states;

// What the hook needs for the figure being drawn.
struct Ctx {
    const Skel* skel = nullptr;
    const Model* model = nullptr;   // the figure the hook is for (the weapon drawn meanwhile is not)
    int weapon = 0, cls = cNone;
    int mode = kOff, prevMode = kOff;
    float blend = 1.0f, weight = 0.0f;
    float x = 0.0f, side = 0.0f;
    bool trigger = false;
    float reloadT = -1.0f;
    ReloadTimes rl;
    float lenM = 0.5f;
    float mpb = 3.8f;          // model units per block
    bool closeUp = true;
    bool throwing = false;
    Params p{};
    // out
    bool gunValid = false;
    Mat4 gun{};
};
Ctx g_ctx;
bool g_hookOn = false;
// FIX-FIGURE-3: the gun frame each posed key placed. A figure whose pose comes back
// out of model_store's pose cache (the same key as a frame before: a still aim, a
// pose shared within the budget) is drawn without the hook running, so the gun the
// hook placed for that key is looked up here (the nearest-pose budget reuse matches
// the hook key too, so it is within 0.12 s of the clip); without it the weapon fell
// back to the old in-hand attach for that frame while the arms were the rig's.
uint64_t g_curKey = 0;
std::unordered_map<uint64_t, Mat4> g_gunByKey;
int g_gunSource = 0;   // the last GunFrame: 0 none, 1 the hook, 2 the cache

// A gun frame and where the hands go on it.
struct Hold {
    bool gun = false;            // the rig places the gun (else it rides in the right hand)
    Vec3 o, r, u, f;             // the gun: rear of the bore line and its axes
    Vec3 rw, rx, ry;             // right wrist, fingers, palm
    Vec3 lw, lx, ly;             // left wrist, fingers, palm
    float rW = 0.0f, lW = 0.0f;  // IK weights
    Vec3 look; float lookW = 0.0f; float roll = 0.0f;
    float lGrip = 1.0f;          // the left hand closed on something (0: the clip's own hand)
};

void TurnGun(Hold& g, const M3& q, const Vec3& pivot) {
    g.o = pivot + Mul(q, g.o - pivot);
    g.r = Mul(q, g.r); g.u = Mul(q, g.u); g.f = Mul(q, g.f);
}

// Where things are on each weapon model (tools/gen_weapons.py: blocks, +z the barrel,
// +y up, the origin the pistol grip). fore: 0 none (pistol), 1 a vertical fore grip,
// 2 a fore-end the left hand cups from below (z, the underside's y).
struct Geo {
    float bore;                 // the bore line's height over the grip
    float buttZ, buttY;         // the stock's heel (into the shoulder pocket)
    int fore; float foreZ, foreY;
    float wellZ, wellY;         // where the magazine / shell / rocket goes in
    float rackZ, rackY;         // the slide or charging handle (rackZ > 1: none)
};
int g_pistolStance = 1;   // FIX-FIGURE-8 (pfl16): 1 arms out along the aim line, 0 the old eye-line hold (test file A/B)

Geo GeoFor(int weapon) {
    switch (weapon) {
        case wPistol: case wDual: return {0.012f, 0.0f, 0.0f, 0, 0.0f, 0.0f, 0.0f, -0.025f, -0.004f, 0.018f};
        case wSilenced:           return {0.014f, -0.045f, 0.010f, 2, 0.050f, 0.004f, 0.012f, -0.025f, 0.030f, 0.021f};
        // FIX-FIGURE-8 (pm24): the S-Uzi (tools/gen_weapons.py machine_gun): the left hand under the handguard,
        // the magazine up the grip, the charging knob on the top cover, the folding stock's butt plate.
        case wMg:                 return {0.017f, -0.078f, 0.004f, 2, 0.058f, -0.002f, 0.000f, -0.056f, 0.050f, 0.028f};
        case wElectro:            return {0.014f, -0.005f, 0.012f, 2, 0.032f, 0.002f, 0.0f, 0.0f, 9.0f, 0.0f};
        case wShotgun:            return {0.012f, -0.075f, -0.004f, 2, 0.080f, -0.002f, 0.012f, 0.018f, 9.0f, 0.0f};
        case wRocket:             return {0.030f, -0.030f, 0.010f, 1, 0.060f, 0.004f, -0.067f, 0.030f, 9.0f, 0.0f};
        case wFlame:              return {0.012f, 0.0f, 0.0f, 1, 0.060f, 0.000f, 0.0f, 0.0f, 9.0f, 0.0f};
        default:                  return {0.012f, 0.0f, 0.0f, 0, 0.0f, 0.0f, 0.0f, 0.0f, 9.0f, 0.0f};
    }
}

// The hold for one mode, from the body as posed (F, U, R: the aim's forward, up and
// right in the model). The gun frame's origin is the weapon model's own (the grip).
Hold HoldFor(const Ctx& c, int mode, const std::vector<Mat4>& W, const Vec3& F, const Vec3& U, const Vec3& R) {
    const Skel& s = *c.skel;
    Hold g;
    const float k = c.mpb / c.skel->upm;   // weapon units (blocks) -> metres (the hook works in metres)
    const Geo geo = GeoFor(c.weapon);
    const Vec3 shR = Pos(W, s.up[0]), shL = Pos(W, s.up[1]);
    const Vec3 headP = Pos(W, s.head), chest = Pos(W, s.sp2);
    const Vec3 eye = headP + U * 0.075f + F * 0.085f;
    const Vec3 pocket = shR - R * 0.055f + F * 0.035f;
    g.r = R; g.u = U; g.f = F;
    // A point on the gun (weapon units, along z and y) in the model, for the frame as it is.
    auto at = [&](float z, float y) { return g.o + g.f * (z * k) + g.u * (y * k); };
    // Put the gun's point (z, y) at p, the frame's axes as they are.
    auto put = [&](float z, float y, const Vec3& p) { g.o = p - g.f * (z * k) - g.u * (y * k); };
    auto turn = [&](const M3& q, const Vec3& pivot) { TurnGun(g, q, pivot); };
    auto pitchAt = [&](float deg, const Vec3& pv) { turn(Toward(g.f, g.u, deg * kDeg), pv); };
    auto yawInAt = [&](float deg, const Vec3& pv) { turn(Toward(g.f, g.r * -1.0f, deg * kDeg), pv); };
    auto cantAt = [&](float deg, const Vec3& pv) { turn(Toward(g.u, g.r, deg * kDeg), pv); };   // top toward his right
    const int cls = c.cls;
    if (cls == cThrow && mode == kCarry && !c.throwing) {
        // FIX-FIGURE-3 (feel12 molotov): a grenade or a bottle carried low in the right
        // hand by the thigh (the carry clip it shares with the pistol holds it up by
        // the ear); the bottle rides in the hand. The throw itself is the clip's.
        g.rw = shR - U * 0.50f + F * 0.10f + R * 0.03f;
        g.rx = Nrm(F * 0.35f - U * 0.94f);
        g.ry = R * -1.0f;
        g.rW = 1.0f;
        return g;
    }
    if (cls == cThrow && c.throwing && g_pistolStance) {   // test file 4th number 0: the clip alone (A/B)
        // FIX-FIGURE-9 (feel12 molotov): the throw is the clip's right arm; the left, which the clip
        // raises out in front for balance, hangs low and a little out and back (it read as both arms
        // thrown up with the bottle). Soft (0.8), so the clip's swing still moves it.
        g.lw = shL - U * 0.46f - R * 0.10f - F * 0.04f;
        g.lx = Nrm(U * -0.95f - R * 0.20f);
        g.ly = R;
        g.lW = 0.8f;
        g.lGrip = 0.0f;
        return g;
    }
    if (mode == kOff || cls == cNone || cls == cThrow) return g;
    if (cls == cDual) {
        if (mode != kAim) return g;
        // Each pistol out ahead of its own shoulder, a little in, at the eye line's height.
        const float y = eye.y - 0.10f;
        Vec3 a = shR + F * 0.47f - R * 0.07f; a.y = y;
        Vec3 b = shL + F * 0.47f + R * 0.07f; b.y = y;
        g.rw = a; g.rx = F; g.ry = R * -1.0f; g.rW = 1.0f;
        g.lw = b; g.lx = F; g.ly = R; g.lW = 1.0f;
        g.look = eye + F * 4.0f; g.lookW = 0.5f;
        return g;
    }
    // FIX-FIGURE-3 (feel11, feel18): the pistol's carry is the rig's too. The avatars'
    // own carry clip holds it up by the ear (high ready), and with the old in-hand
    // attach it dangled from the fingertips on the walk; now a one-handed low ready:
    // the grip in the right palm by the thigh, the muzzle forward and down, the left
    // hand the clip's.
    const bool pistolLow = cls == cPistol && mode == kCarry;
    g.gun = true;
    const bool longGun = cls == cRifle || cls == cShotgun;
    // ---- the gun in the aim (the base of the carry and the reload too) ----
    const Vec3 shoulderTop = shR + U * 0.065f - R * 0.03f;
    // FIX-FIGURE-8 (pfl16): the pistol out at arm's length along the aim line, the grip centred between
    // the shoulders a hand over their height (an isosceles stance, the arms nearly straight). It was on
    // the eye line 0.34 m ahead of the eye: forearms folded, the gun hidden behind his head from the
    // chase camera ("a phone call").
    // A/B: the rig test file's fourth number 0 puts it back on the eye line (GTA2DX9_RIG_TEST_FILE).
    if (cls == cPistol) {
        if (g_pistolStance) put(0.0f, geo.bore, (shR + shL) * 0.5f + R * 0.04f + F * 0.56f + U * 0.12f);
        else put(0.0f, geo.bore, eye + F * 0.34f - U * 0.05f);
    }
    else if (longGun) put(geo.buttZ, geo.buttY, pocket + U * 0.065f);
    else if (cls == cLauncher) put(geo.buttZ, geo.buttY, shoulderTop);
    else if (cls == cFlame) { g.o = shR - U * 0.30f + F * 0.22f + R * 0.02f; pitchAt(-5.0f, g.o); }
    const Vec3 butt = at(geo.buttZ, geo.buttY);
    float reloadPitch = 0.0f;
    if (mode == kCarry) {
        // Low ready: the stock stays in the shoulder, the muzzle down and in.
        if (longGun) { pitchAt(-38.0f, butt); yawInAt(18.0f, butt); }
        else if (pistolLow) { g.o = shR - U * 0.47f + F * 0.16f + R * 0.015f; pitchAt(-48.0f, g.o); yawInAt(6.0f, g.o); }
        else if (cls == cLauncher) pitchAt(6.0f, butt);
        else if (cls == cFlame) pitchAt(-20.0f, g.o);
    } else if (mode == kReload) {
        // Pulled in and canted so the well faces the left hand.
        if (cls == cPistol) { g.o = chest + F * 0.30f + U * 0.02f; pitchAt(15.0f, g.o); cantAt(30.0f, g.o); }
        else if (c.weapon == wSilenced) { g.o = pocket - U * 0.14f + F * 0.10f; pitchAt(10.0f, g.o); cantAt(25.0f, g.o); }
        else if (cls == cRifle) { g.o = g.o - U * 0.10f - R * 0.02f; pitchAt(10.0f, g.o); cantAt(25.0f, g.o); }
        else if (cls == cShotgun) {
            // Broken open: the stock under the arm, the muzzle dropped, snapped shut at the end.
            const float shut = c.reloadT >= 0.0f ? Smooth((c.reloadT - c.rl.insert) / 0.12f) : 0.0f;
            g.o = g.o - U * 0.12f - R * 0.03f;
            reloadPitch = -32.0f * (1.0f - shut);
            pitchAt(reloadPitch, g.o);
        } else if (cls == cLauncher) { g.o = chest - U * 0.22f + F * 0.24f; yawInAt(-35.0f, g.o); pitchAt(8.0f, g.o); }
        else if (cls == cFlame) pitchAt(-20.0f, g.o);
    }
    const Vec3 o = g.o, r = g.r, u = g.u, f = g.f;
    // ---- the right hand round the pistol grip: the web high on its back, the
    //      fingers round the front, the palm on its right side ----
    g.rw = o - f * 0.05f + u * 0.03f + r * 0.012f;
    g.rx = Nrm(f * 0.75f - u * 0.65f);
    g.ry = r * -1.0f;
    g.rW = 1.0f;
    // ---- the left hand ----
    Vec3 supW, supX, supY;
    if (cls == cPistol || geo.fore == 0) {
        // Wrapped over the right hand's fingers from the left, the thumbs along the frame.
        supW = g.rw - r * 0.05f - u * 0.035f + f * 0.01f; supX = Nrm(f * 0.55f - u * 0.6f + r * 0.55f); supY = Nrm(r * 0.85f + u * 0.3f);
    } else if (geo.fore == 1) {
        const Vec3 P = at(geo.foreZ, geo.foreY);
        supW = P - f * 0.05f + u * 0.03f - r * 0.012f; supX = Nrm(f * 0.75f - u * 0.65f); supY = r;
    } else {
        const Vec3 P = at(geo.foreZ, geo.foreY);
        supW = P - u * 0.035f - f * 0.06f - r * 0.025f; supX = Nrm(f * 0.8f + r * 0.45f + u * 0.2f); supY = Nrm(u * 0.9f + r * 0.35f);
    }
    g.lw = supW; g.lx = supX; g.ly = supY; g.lW = 1.0f;
    if (pistolLow) { g.lW = 0.0f; g.lGrip = 0.0f; }
    // The head down the sights (a long gun: the cheek on the stock).
    g.look = (cls == cPistol || longGun) ? at(0.0f, geo.bore) + f * 4.0f + u * 0.05f : eye + F * 4.0f;
    g.lookW = mode == kAim ? 0.8f : 0.0f;
    g.roll = (mode == kAim && longGun) ? 9.0f : 0.0f;
    (void)shL;
    if (mode == kReload && c.reloadT >= 0.0f) {
        const float t = c.reloadT;
        const ReloadTimes& rl = c.rl;
        // The well (the hand that brings the magazine, shell or rocket) and the rack.
        const Vec3 well = at(geo.wellZ, geo.wellY);
        Vec3 wellW, wellX, wellY, rackW = supW, rackX = supX, rackY = supY;
        if (cls == cShotgun) {        // shells pushed down into the open breech
            wellW = well + u * 0.04f - f * 0.06f - r * 0.03f; wellX = Nrm(f * 0.7f + r * 0.5f - u * 0.3f); wellY = Nrm(u * -0.8f + r * 0.3f);
        } else if (cls == cLauncher) { // the rocket into the rear of the tube
            wellW = well - f * 0.07f - r * 0.03f; wellX = f; wellY = r;
        } else {                       // a magazine pushed up into the well
            wellW = well - u * 0.035f - f * 0.05f - r * 0.02f; wellX = Nrm(f * 0.8f + r * 0.4f); wellY = Nrm(u * 0.8f + r * 0.4f);
        }
        if (geo.rackZ < 1.0f) {        // over the top: the slide, the charging handle
            const Vec3 rk = at(geo.rackZ, geo.rackY);
            rackW = rk + u * 0.035f - f * 0.03f - r * 0.04f; rackX = Nrm(f * 0.5f + r * 0.7f - u * 0.4f); rackY = Nrm(u * -0.9f + r * 0.3f);
        }
        float w = 1.0f; Vec3 tw = supW, tx = supX, ty = supY;
        const float grab = rl.grab, ins = rl.insert;
        const float drop = rl.drop >= 0.0f ? rl.drop : 0.0f;
        if (cls == cShotgun && grab >= 0.0f && ins > grab) {
            // Two shells: the hand goes from the belt (the clip's) to the breech twice.
            tw = wellW; tx = wellX; ty = wellY;
            if (t < grab) w = 1.0f - Smooth((t - 0.05f) / 0.2f);
            else if (t < ins) w = Smooth(0.5f - 0.5f * std::cos((t - grab) / (ins - grab) * 2.0f * 2.0f * 3.14159265f - 3.14159265f));
            else { const float kk = Smooth((t - ins) / 0.15f); tw = Mix(wellW, supW, kk); tx = Nrm(Mix(wellX, supX, kk)); ty = Nrm(Mix(wellY, supY, kk)); }
        } else if (cls == cLauncher) {
            tw = wellW; tx = wellX; ty = wellY;
            if (t < grab) w = 1.0f - Smooth(t / 0.15f);
            else if (t < ins) w = Smooth((t - (grab + 0.45f * (ins - grab))) / (0.55f * (ins - grab)));
            else { const float kk = Smooth((t - ins) / 0.2f); tw = Mix(wellW, supW, kk); tx = Nrm(Mix(wellX, supX, kk)); ty = Nrm(Mix(wellY, supY, kk)); }
        } else {
            if (t < drop + 0.02f) { tw = wellW; tx = wellX; ty = wellY; }
            else if (grab >= 0.0f && t < grab) { tw = wellW; tx = wellX; ty = wellY; w = 1.0f - Smooth((t - drop) / 0.15f); g.lGrip = 0.6f; }
            else if (ins >= 0.0f && t < ins) {
                tw = wellW; tx = wellX; ty = wellY;
                w = Smooth((t - (grab + 0.45f * (ins - grab))) / (0.55f * (ins - grab)));
            } else if (rl.rack >= 0.0f && t < rl.rack + 0.06f) {
                const float kk = Smooth((t - ins) / 0.1f);
                tw = Mix(wellW, rackW, kk); tx = Nrm(Mix(wellX, rackX, kk)); ty = Nrm(Mix(wellY, rackY, kk));
                const float pull = Smooth((t - (rl.rack - 0.1f)) / 0.08f) * (1.0f - Smooth((t - rl.rack) / 0.05f));
                tw = tw - f * (0.07f * pull);
            } else {
                const float from = rl.rack >= 0.0f ? rl.rack + 0.06f : ins;
                const float kk = Smooth((t - from) / 0.2f);
                tw = Mix(rackW, supW, kk); tx = Nrm(Mix(rackX, supX, kk)); ty = Nrm(Mix(rackY, supY, kk));
            }
        }
        g.lw = tw; g.lx = tx; g.ly = ty; g.lW = w;
        // He watches the well, and looks up again as it ends.
        g.look = well; g.lookW = 0.75f * (1.0f - Smooth((t - (rl.len - 0.3f)) / 0.25f));
    }
    (void)reloadPitch;
    return g;
}

Hold MixHold(const Hold& a, const Hold& b, float t) {
    if (t >= 0.999f) return b;
    if (t <= 0.001f) return a;
    Hold g = b;
    if (a.gun && b.gun) {
        g.o = Mix(a.o, b.o, t);
        const M3 q = Part(Align(a.f, a.u, b.f, b.u), t);
        g.f = Mul(q, a.f); g.u = Mul(q, a.u); g.r = Mul(q, a.r);
    }
    g.gun = a.gun || b.gun;
    if (!b.gun && a.gun) { g.o = a.o; g.f = a.f; g.u = a.u; g.r = a.r; }
    auto mixHand = [t](const Vec3& wa, const Vec3& xa, const Vec3& ya, float Wa, const Vec3& wb, const Vec3& xb, const Vec3& yb, float Wb,
                       Vec3* w, Vec3* x, Vec3* y, float* W) {
        if (Wa <= 0.01f) { *w = wb; *x = xb; *y = yb; *W = Wb * t; return; }
        if (Wb <= 0.01f) { *w = wa; *x = xa; *y = ya; *W = Wa * (1.0f - t); return; }
        *w = Mix(wa, wb, t); *x = Nrm(Mix(xa, xb, t)); *y = Nrm(Mix(ya, yb, t)); *W = Wa + (Wb - Wa) * t;
    };
    mixHand(a.rw, a.rx, a.ry, a.rW, b.rw, b.rx, b.ry, b.rW, &g.rw, &g.rx, &g.ry, &g.rW);
    mixHand(a.lw, a.lx, a.ly, a.lW, b.lw, b.lx, b.ly, b.lW, &g.lw, &g.lx, &g.ly, &g.lW);
    if (a.lookW > 0.01f && b.lookW > 0.01f) g.look = Mix(a.look, b.look, t);
    else if (b.lookW <= 0.01f) g.look = a.look;
    g.lookW = a.lookW + (b.lookW - a.lookW) * t;
    g.roll = a.roll + (b.roll - a.roll) * t;
    g.lGrip = a.lGrip + (b.lGrip - a.lGrip) * t;
    return g;
}

void Hook(const Model& model, std::vector<Mat4>* worlds, void* context) {
    Ctx& c = *static_cast<Ctx*>(context);
    if (&model != c.model) return;   // the weapon model drawn under the same hook: not ours
    c.gunValid = false;
    const Skel& s = *c.skel;
    if (!s.ok || worlds->size() != model.nodes.size() || s.sub.size() != model.nodes.size()) return;
    std::vector<Mat4>& W = *worlds;
    // Worked in metres (the avatars are about two metres to a model unit): positions
    // scaled down here and back at the end; the turns are about pivots, so unchanged.
    static std::vector<Mat4> before;
    before = W;
    const float upm = s.upm;
    for (Mat4& m : W) for (int i = 0; i < 3; ++i) m.m[3][i] /= upm;
    struct Back {
        std::vector<Mat4>& W; Ctx& c; float upm;
        ~Back() {
            for (Mat4& m : W) for (int i = 0; i < 3; ++i) m.m[3][i] *= upm;
            if (c.gunValid) for (int i = 0; i < 3; ++i) c.gun.m[3][i] *= upm;
            bool finite = true;
            for (const Mat4& m : W) for (int r = 0; r < 4 && finite; ++r) for (int q = 0; q < 4; ++q) if (!std::isfinite(m.m[r][q])) { finite = false; break; }
            if (!finite) {
                W = before; c.gunValid = false;
                static int logged = 0;
                if (logged < 20) { ++logged; Log("weapon rig: a non-finite pose (weapon %d mode %d), the clip's kept", c.weapon, c.mode); }
            }
        }
    } back{W, c, upm};
    // The aim's frame: the model's forward turned by the torso twist (as model_store turns Spine1).
    const float tw = ModelTorsoTwist();
    const float ct = std::cos(tw), st = std::sin(tw);
    auto twist = [&](const Vec3& v) { return V(v.x * ct - v.z * st, v.y, v.x * st + v.z * ct); };
    const Vec3 U = s.up3, F = Nrm(twist(s.fwd)), R = Nrm(twist(s.right));
    const float wr = c.weight;
    const Params& p = c.p;
    const float x = c.x * wr;
    // 1. The body takes the recoil: the chest rocks back (about Spine1) and the right
    //    shoulder is driven back (the upper body turned about the vertical).
    if (std::fabs(x) > 1e-3f && (c.mode == kAim || c.prevMode == kAim)) {
        const Vec3 piv = Pos(W, s.sp1);
        Turn(W, s, s.sp1, piv, Toward(U, F * -1.0f, p.spine * kDeg * x));
        Turn(W, s, s.sp1, piv, Toward(R, F * -1.0f, p.shoulder * kDeg * x));
    }
    // 1b. A long gun in the aim: the body bladed 8 degrees more than the clip has it (the
    //     left shoulder forward), so the support arm reaches the fore grip with its elbow soft.
    {
        auto blade = [&](int m) { return (m == kAim && (c.cls == cRifle || c.cls == cShotgun)) ? 8.0f : 0.0f; };
        const float deg = (blade(c.prevMode) + (blade(c.mode) - blade(c.prevMode)) * Smooth(c.blend)) * wr;
        if (deg > 0.1f) Turn(W, s, s.sp1, Pos(W, s.sp1), Toward(R, F * -1.0f, deg * kDeg));
    }
    // 2. The gun and the hands, for this mode and the one it is blending from.
    Hold h = HoldFor(c, c.mode, W, F, U, R);
    if (c.blend < 0.999f && c.prevMode != c.mode) h = MixHold(HoldFor(c, c.prevMode, W, F, U, R), h, Smooth(c.blend));
    // 3. The gun's own kick: back along the bore, the muzzle climbing about the grip,
    //    a little to one side; the hands go with it.
    if (h.gun && std::fabs(x) > 1e-3f) {
        const Vec3 back = h.f * (-p.back * x);
        h.o = h.o + back; h.rw = h.rw + back; h.lw = h.lw + back;
        const Vec3 piv = h.rw;
        const M3 q = Mul(Toward(h.f, h.u, p.rise * kDeg * x), Toward(h.f, h.r, p.side * c.side * kDeg * x));
        Hold k = h;
        TurnGun(k, q, piv);
        h.o = k.o; h.f = k.f; h.u = k.u; h.r = k.r;
        h.lw = piv + Mul(q, h.lw - piv);
        h.rx = Mul(q, h.rx); h.ry = Mul(q, h.ry); h.lx = Mul(q, h.lx); h.ly = Mul(q, h.ly);
    } else if (!h.gun && std::fabs(x) > 1e-3f) {   // the dual pistols: each hand kicks up and back
        const M3 q = Toward(F, U, p.rise * kDeg * x);
        h.rw = h.rw - F * (p.back * x); h.lw = h.lw - F * (p.back * x);
        h.rx = Mul(q, h.rx); h.lx = Mul(q, h.lx);
    }
    if (h.gun) {
        c.gunValid = true;
        Mat4& G = c.gun;
        G = Mat4{};
        G.m[0][0] = h.r.x; G.m[0][1] = h.r.y; G.m[0][2] = h.r.z;
        G.m[1][0] = h.u.x; G.m[1][1] = h.u.y; G.m[1][2] = h.u.z;
        G.m[2][0] = h.f.x; G.m[2][1] = h.f.y; G.m[2][2] = h.f.z;
        G.m[3][0] = h.o.x; G.m[3][1] = h.o.y; G.m[3][2] = h.o.z; G.m[3][3] = 1.0f;
    }
    // 4a. The head first (the arms hang off the neck in the Biped, so they are solved after
    //     it): down the sights; a long gun, the cheek down onto the stock - the neck and head
    //     bowed and leaning over toward the right shoulder.
    if (c.closeUp) {
        if (h.lookW > 0.01f) LookAt(W, s, h.look, h.lookW * wr, h.roll, F);
        if (h.roll > 0.1f) {
            const float k2 = (h.roll / 9.0f) * wr;
            TurnNeck(W, s, Toward(U, F, 9.0f * kDeg * k2));
            TurnNeck(W, s, Toward(U, R, 10.0f * kDeg * k2));
            Turn(W, s, s.head, Pos(W, s.head), Toward(U, F, 7.0f * kDeg * k2));
        }
    }
    // 4. The arms onto the grips (elbows down and out).
    const Vec3 poleR = Nrm(U * -1.0f + R * 0.55f - F * 0.15f), poleL = Nrm(U * -1.0f - R * 0.45f);
    if (h.rW > 0.01f) SolveArm(W, s, 0, h.rw, poleR, h.rx, h.ry, h.rW * wr);
    if (h.lW > 0.01f) SolveArm(W, s, 1, h.lw, poleL, h.lx, h.ly, h.lW * wr);
    {
        // The first three poses of every weapon and mode pair, then every 90th (at most 400 lines).
        static unsigned n = 0, lines = 0;
        static unsigned char seen[16][4][4] = {};
        unsigned char& k = seen[c.weapon & 15][c.prevMode & 3][c.mode & 3];
        const bool first = k < 3;
        if (first) ++k;
        if (((++n % 90u) == 1u || first) && lines++ < 400u)
            Log("weapon rig: pose weapon %d mode %d->%d b %.2f w %.2f x %.2f gun %d at %.2f,%.2f,%.2f m, right hand off its grip %.3f m, left %.3f m (lW %.2f), upm %.3f",
                c.weapon, c.prevMode, c.mode, c.blend, wr, c.x, h.gun ? 1 : 0, h.o.x, h.o.y, h.o.z,
                Len(Pos(W, s.hand[0]) - h.rw), Len(Pos(W, s.hand[1]) - h.lw), h.lW, s.upm);
    }
    // 5. The fingers: closed round the grip, the trigger finger along the frame
    //    until he fires; the support hand wrapped; the head to the sights.
    if (c.closeUp && s.fing[0][1][0] >= 0) {
        static const float grip[3] = {68.0f, 85.0f, 40.0f}, trig[3] = {38.0f, 58.0f, 30.0f}, off[3] = {6.0f, 10.0f, 6.0f};
        static const float sup[3] = {48.0f, 62.0f, 35.0f}, thumbGrip[3] = {14.0f, 26.0f, 20.0f}, thumbSup[3] = {8.0f, 14.0f, 10.0f};
        static const float hold[3] = {55.0f, 70.0f, 40.0f};
        const bool armed = c.cls != cNone;
        if (armed) {
            const float fw = wr;
            if (c.cls == cThrow) {
                for (int f = 1; f <= 4; ++f) Curl(W, s, 0, f, hold, fw);
                Thumb(W, s, 0, thumbGrip, fw);
            } else {
                Curl(W, s, 0, 1, c.trigger ? trig : off, fw);
                for (int f = 2; f <= 4; ++f) Curl(W, s, 0, f, grip, fw);
                Thumb(W, s, 0, thumbGrip, fw);
                if (c.cls == cDual) {
                    Curl(W, s, 1, 1, c.trigger ? trig : off, fw);
                    for (int f = 2; f <= 4; ++f) Curl(W, s, 1, f, grip, fw);
                    Thumb(W, s, 1, thumbGrip, fw);
                } else if (h.lW > 0.3f) {
                    const float lw = fw * (std::min)(1.0f, h.lW) * h.lGrip;
                    for (int f = 1; f <= 4; ++f) Curl(W, s, 1, f, sup, lw);
                    Thumb(W, s, 1, thumbSup, lw);
                }
            }
        }
    }
    // The head nods with the kick.
    if (std::fabs(x) > 1e-3f && s.head >= 0 && p.head > 0.0f)
        Turn(W, s, s.head, Pos(W, s.head), Toward(U, F * -1.0f, p.head * kDeg * x));
}

int g_enabled = -1;

// The showcase file (GTA2DX9_RIG_TEST_FILE).
float g_testYaw = 0.0f, g_testPeriod = 0.0f; int g_testOff = 0;
uint32_t g_testRead = 0, g_testLastFire = 0;
void ReadTest(uint32_t frame) {
    static int checked = 0;
    static char path[MAX_PATH] = {};
    if (!checked) { checked = 1; if (!GetEnvironmentVariableA("GTA2DX9_RIG_TEST_FILE", path, sizeof path)) path[0] = 0; }
    if (!path[0]) return;
    if (g_testRead && frame - g_testRead < 15) return;
    g_testRead = frame ? frame : 1;
    float yaw = 0.0f, period = 0.0f; int off = 0, stance = 1;
    if (FILE* f = fopen(path, "r")) {
        if (fscanf(f, "%f %f %d %d", &yaw, &period, &off, &stance) < 1) { yaw = 0.0f; period = 0.0f; off = 0; stance = 1; }
        fclose(f);
    }
    if (yaw != g_testYaw || period != g_testPeriod || off != g_testOff || stance != g_pistolStance)
        Log("weapon rig: test yaw %.0f fire every %.2f s rig %s, pistol stance %s", yaw, period, off ? "off" : "on", stance ? "arms out" : "eye line (old)");
    g_testYaw = yaw; g_testPeriod = period; g_testOff = off; g_pistolStance = stance;
}

// FIX-ACTIONS-3 (pfl15): bare fists. The punch clips (tools/gen_ped_clips.py) key only the arms and
// the torso, so the fingers kept the bind pose: two flat open palms by the face, read as "stop" / hands
// up. While a fist clip is on, both hands are closed: the fingers rolled into the palm, the thumb
// folded across them. Blended by the clip's weight (fw), so the hands open as the guard fades.
struct FistCtx { const Model* model = nullptr; const Skel* skel = nullptr; float w = 0.0f; };
FistCtx g_fist;
void FistHook(const Model& model, std::vector<Mat4>* worlds, void* context) {
    FistCtx& c = *static_cast<FistCtx*>(context);
    if (&model != c.model || !c.skel) return;   // another model drawn under the hook
    const Skel& s = *c.skel;
    if (!s.ok || worlds->size() != model.nodes.size() || s.sub.size() != model.nodes.size()) return;
    static const float fist[3] = {88.0f, 100.0f, 62.0f}, thumb[3] = {22.0f, 38.0f, 30.0f};
    for (int h = 0; h < 2; ++h) {
        for (int f = 1; f <= 4; ++f) Curl(*worlds, s, h, f, fist, c.w);
        Thumb(*worlds, s, h, thumb, c.w);
    }
}
}  // namespace

bool Enabled() {
    if (g_enabled < 0) { char buf[8] = {}; g_enabled = !(GetEnvironmentVariableA("GTA2DX9_WEAPON_RIG", buf, sizeof buf) && buf[0] == '0'); }
    return g_enabled != 0;
}

int ModeForAction(int action) {
    switch (action) {
        case 2: case 8: case 10: case 11: case 12: return kAim;
        case 14: case 15: case 16: case 17: case 18: return kCarry;
        case 24: case 25: case 26: return kReload;
        case 13: return kCarry;   // the throw: only the fingers (cThrow)
        default: return kOff;
    }
}

bool Begin(const Model& model, const Inputs& in) {
    if (!Enabled() || !model.skinned || g_testOff) return false;
    const Skel& s = SkelFor(model);
    if (!s.ok) return false;
    State& st = g_states[in.object];
    if (st.seen + 1 < in.frame || st.weapon != in.weapon) {   // not drawn last frame / a new gun: start still
        if (st.seen + 1 < in.frame) { st.x = 0.0f; st.v = 0.0f; st.weight = 0.0f; st.mode = kOff; st.blend = 1.0f; }
        st.weapon = in.weapon;
        st.muzzleFrame = in.muzzleFrame;
    }
    st.seen = in.frame;
    const float dt = (std::max)(0.0f, (std::min)(in.dt, 0.1f));
    const Params p = ParamsFor(in.weapon);
    // A shot: the impulse and a fresh lateral jitter.
    st.sinceShot += dt;
    if (in.muzzleFrame && in.muzzleFrame != st.muzzleFrame) {
        st.muzzleFrame = in.muzzleFrame;
        st.v += p.impulse * p.freq * 1.6f;
        st.rng = st.rng * 1664525u + 1013904223u + static_cast<uint32_t>(in.object);
        st.side = static_cast<float>((st.rng >> 9) & 0xFFFF) / 32767.5f - 1.0f;
        st.sinceShot = 0.0f;
        // FIX-FIGURE-3: the game fires on the key press, so a shot from the carry is
        // already in the aim (no 0.18 s raise with the flash leaving a lowered gun).
        if (in.mode == kAim && st.mode != kAim) { st.prevMode = kAim; st.mode = kAim; st.blend = 1.0f; st.weight = 1.0f; }
        static int logged = 0;
        if (logged < 40) { ++logged; Log("weapon rig: shot %p weapon %d mode %d", reinterpret_cast<const void*>(in.object), in.weapon, in.mode); }
    }
    // The spring, in small steps.
    for (float left = dt; left > 1e-5f;) {
        const float h = (std::min)(left, 1.0f / 240.0f);
        const float a = -p.freq * p.freq * st.x - 2.0f * p.damp * p.freq * st.v;
        st.v += a * h; st.x += st.v * h;
        left -= h;
    }
    st.x = (std::max)(-0.5f, (std::min)(1.8f, st.x));
    // The mode, blended over 0.18 s; the rig's weight in over 0.1 s, out over 0.15 s.
    if (in.mode != st.mode) {
        if (in.mode != kOff) { st.prevMode = st.mode == kOff ? in.mode : st.mode; st.blend = st.mode == kOff ? 1.0f : 0.0f; st.mode = in.mode; }
        else { st.prevMode = st.mode; st.blend = 1.0f; }
    }
    st.blend = (std::min)(1.0f, st.blend + dt / 0.18f);
    const bool on = in.mode != kOff;
    st.weight += ((on ? 1.0f : 0.0f) - st.weight) * (std::min)(1.0f, dt / (on ? 0.1f : 0.15f));
    if (!on && st.weight < 0.04f) { st.weight = 0.0f; return false; }
    // The context for the hook.
    Ctx& c = g_ctx;
    c.skel = &s;
    c.model = &model;
    c.weapon = in.weapon;
    c.cls = ClassOf(in.weapon);
    c.mode = on ? st.mode : st.prevMode;
    c.prevMode = st.prevMode;
    c.blend = st.blend;
    c.weight = std::floor(st.weight * 10.0f + 0.5f) / 10.0f;
    c.x = std::floor(st.x * 20.0f + 0.5f) / 20.0f;
    c.side = std::floor(st.side * 4.0f + 0.5f) / 4.0f;
    c.trigger = c.mode == kAim && st.sinceShot < 0.45f;
    c.reloadT = c.mode == kReload ? std::floor(in.reloadT * 30.0f) / 30.0f : -1.0f;
    c.rl = in.reload;
    c.lenM = in.lengthBlocks * in.modelPerBlock;
    c.mpb = in.modelPerBlock;
    c.closeUp = in.closeUp;
    c.throwing = in.throwing;
    c.p = p;
    c.gunValid = false;
    // The pose cache key: this figure (bits 24-62) and what the hook reads.
    uint32_t hsh = 2166136261u;
    auto mix = [&hsh](uint32_t v) { hsh = (hsh ^ v) * 16777619u; };
    mix(static_cast<uint32_t>(c.weapon)); mix(static_cast<uint32_t>(c.mode)); mix(static_cast<uint32_t>(c.prevMode));
    mix(static_cast<uint32_t>(c.blend * 16.0f)); mix(static_cast<uint32_t>(c.weight * 10.0f));
    mix(static_cast<uint32_t>(static_cast<int>(c.x * 20.0f) + 64)); mix(static_cast<uint32_t>(static_cast<int>(c.side * 4.0f) + 8));
    mix(c.trigger ? 1u : 0u); mix(static_cast<uint32_t>(static_cast<int>(c.reloadT * 30.0f) + 4));
    mix(c.closeUp ? 1u : 0u); mix(c.throwing ? 1u : 0u);
    mix(static_cast<uint32_t>(g_pistolStance));   // the test file's A/B switch
    const uint64_t key = (1ull << 63) | ((static_cast<uint64_t>(in.object >> 2) & 0x7FFFFFFFFFull) << 24) | (hsh & 0xFFFFFFu);
    ModelSetPoseHook(&Hook, &g_ctx, key | 1u);
    g_curKey = key | 1u;
    {
        static int logged = 0;
        if (logged < 12) { ++logged; Log("weapon rig: begin %p weapon %d mode %d weight %.2f", reinterpret_cast<const void*>(in.object), in.weapon, c.mode, c.weight); }
    }
    g_hookOn = true;
    // Forget figures not drawn for ten seconds.
    if ((in.frame % 300u) == 0) {
        for (auto it = g_states.begin(); it != g_states.end();) {
            if (in.frame - it->second.seen > 300u) it = g_states.erase(it); else ++it;
        }
    }
    return true;
}

void End() {
    if (g_hookOn) ModelSetPoseHook(nullptr, nullptr, 0);
    g_hookOn = false;
}

bool BeginFists(const Model& model, uintptr_t object, float weight) {
    if (!Enabled() || !model.skinned || g_testOff || weight < 0.05f) return false;
    const Skel& s = SkelFor(model);
    if (!s.ok || s.fing[0][1][0] < 0) return false;
    g_fist.model = &model; g_fist.skel = &s;
    g_fist.w = std::floor((std::min)(1.0f, weight) * 8.0f + 0.5f) / 8.0f;
    // The pose cache key: this figure (bits 24-61, bit 62 apart from the gun rig's) and the weight.
    const uint64_t key = (1ull << 62) | ((static_cast<uint64_t>(object >> 2) & 0x3FFFFFFFFFull) << 24) |
                         static_cast<uint64_t>(g_fist.w * 8.0f + 1.0f);
    ModelSetPoseHook(&FistHook, &g_fist, key);
    g_hookOn = true;   // End() clears it like the gun rig's
    return true;
}

float Shove(uintptr_t object, float dir[3]) {
    auto it = g_states.find(object);
    if (it == g_states.end() || !g_ctx.skel) return 0.0f;
    const State& st = it->second;
    const float tw = ModelTorsoTwist();
    const Vec3 f = g_ctx.skel->fwd;
    dir[0] = f.x * std::cos(tw) - f.z * std::sin(tw); dir[1] = 0.0f; dir[2] = f.x * std::sin(tw) + f.z * std::cos(tw);
    if (st.mode != kAim) return 0.0f;
    return -ParamsFor(st.weapon).shove * g_ctx.skel->upm * (std::max)(0.0f, st.x) * st.weight;   // model units
}

bool GunFrame(Mat4* out, float* lengthModel) {
    g_gunSource = 0;
    if (!g_hookOn) return false;
    if (g_ctx.gunValid) {
        g_gunSource = 1;
        if (g_gunByKey.size() > 4096) g_gunByKey.clear();
        g_gunByKey[g_curKey] = g_ctx.gun;
        *out = g_ctx.gun;
    } else {
        const auto it = g_gunByKey.find(g_curKey);   // the pose came from the cache: the hook did not run
        if (it == g_gunByKey.end()) return false;
        *out = it->second;
        g_gunSource = 2;
    }
    *lengthModel = g_ctx.lenM;
    return true;
}

int GunSource() { return g_gunSource; }

float TestYaw() { return g_testYaw; }
// FIX-FIGURE-11 (pfl42): for the first-person muzzle.
float BoreHeight(int weapon) { return GeoFor(weapon).bore; }

bool TestFire(uint32_t frame) {
    ReadTest(frame);
    if (g_testPeriod <= 0.0f) return false;
    const uint32_t every = static_cast<uint32_t>((std::max)(1.0f, g_testPeriod * 30.0f));
    if (frame - g_testLastFire >= every) { g_testLastFire = frame; return true; }
    return false;
}

}  // namespace weaponrig
}  // namespace gta2dx9
