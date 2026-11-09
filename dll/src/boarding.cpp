#include "boarding.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <map>

#include "log.h"

// See boarding.h. Distances are in blocks (a car is about one block long, an adult
// figure 0.46 tall), times in seconds. "u" is across the car, outward on the door's
// side (u = side * x), "z" along it, forward; both in the car's own frame.

namespace gta2dx9 {
namespace {

constexpr float kPi = 3.14159265f;
constexpr float kDoorMaxAngle = 60.0f * kPi / 180.0f;   // car_bodies swings the door this far

struct Car {
    gta2::Mat4 m;              // car to world
    float inv[3][3] = {};      // world to car (the 3x3 part's inverse)
    float halfW = 0.2f, zFront = 0.2f, zRear = -0.05f, roof = 0.35f;
    int doorSide = 1;
    float doorOpen = 0.0f;
    uint32_t frame = 0;
    float speed = 0.0f;        // blocks a second, eased
    float lastX = 0.0f, lastZ = 0.0f;
    bool warm = false;
    float steer = 0.0f;        // the front wheels (BoardingPublishSteer), radians, + to the left
    bool openTop = false;      // FIX-JACK-SEAT (pm19): BoardingPublishOpenTop
};
std::map<uintptr_t, Car> g_cars;

enum Mode { kNone = 0, kApproach, kClimb, kExit, kShut, kSeated };   // kShut: after an exit, a hand swings the door shut
                                                                    // kSeated (FIX-SEATED): at the wheel, for the drive

struct Board {
    int mode = kNone;
    uintptr_t car = 0;
    int side = 1;
    float t = 0.0f;            // seconds into the climb or the exit
    uint32_t seen = 0;         // the last frame it was updated
    bool ended = false;
    // where the figure was when the plan took over, car frame (u, z) and heading (car frame, radians)
    float u0 = 0.0f, z0 = 0.0f, h0 = 0.0f;
    // the exit: where the game had him on the first frame, car frame
    float gu0 = 0.0f, gz0 = 0.0f;
    // which hand holds the door, which foot goes first (0 left, 1 right)
    int doorHand = 1, firstFoot = 0;
    // the planted outer foot while entering, car frame
    float plantU = 0.0f, plantZ = 0.0f, innerU = 0.0f, innerZ = 0.0f;
    bool planted = false, innerSet = false;
    // the plan's segments: which one, where it began, where the figure was last frame (car frame)
    int seg = -1;
    float segU = 0.0f, segZ = 0.0f, lastU = 0.0f, lastZ = 0.0f;
    // door control
    bool doorOwn = false;
    float doorTarget = 0.0f, doorRate = 2.5f;
    // limb targets (world) for the figure this frame
    bool limbOn[4] = {};
    gta2::Vec3 limbT[4], limbPole[4];
    float limbW[4] = {};
    // the last output, for a ghost and for the trace; where the figure was drawn last frame
    BoardingOut out;
    float px = 0.0f, pz = 0.0f;
    bool havePrev = false;
    // reach assist: the body moved toward a hand's target it could not reach last frame (world x/z)
    float ax = 0.0f, az = 0.0f, rx = 0.0f, rz = 0.0f;
    // the climb's incoming velocity (car frame, per second), the exit's smoothed game position
    float v0u = 0.0f, v0z = 0.0f, fu = 0.0f, fz = 0.0f;
    bool fSet = false;
    float lastOutX = 0.0f, lastOutZ = 0.0f;
    bool haveOut = false;
    float tox = 0.0f, toz = 0.0f;   // the tether's pull, eased (0.12 s) so a hand taking hold never yanks the body
    bool player = false;       // the player's own figure (kept through the ghost frames)
    bool jacking = false;      // QB-14: a driver is hauled out (jack_pull keeps its own timing)
    float shutW = 0.0f;        // kShut: the hand on the door's edge, eased
    int shutHand = -1;         // kShut: which hand (chosen once)
    bool released = false;     // kShut: the shove is over, the door swings on by itself
    float st = 0.0f, shutOff = 0.0f, shutAt = -1.0f;   // kShut: its time, the step-back weight, when the door was shut
    float lgx = 0.0f, lgz = 0.0f;                       // kShut: the game's position last frame
    bool haveGame = false, walkedOff = false;
    float bu = 0.0f, bz = 0.0f; bool haveBase = false;   // kShut: the filtered game spot (car frame)
    float shutH0 = 99.0f;                                // kShut: his heading as it began
    float held = 0.0f;         // QB-14: seconds the climb waited for the driver
    float rush = 0.0f;         // FIX-JACK-SEAT: the climb's clock rate once the game has him inside (0: not yet)
    // kSeated: the feet's targets as the climb left them (car frame), eased onto the pedals
    float footFrom[2][3] = {};
    bool footFromSet = false;
    float sink0 = 0.0f;        // the climb's sink as it ended
    float headYaw = 0.0f;      // eased
};
std::map<uintptr_t, Board> g_boards;
// GTA2DX9_BOARDING_CAM=1 (verification only): the player's last boarding, for a fixed side camera.
uintptr_t g_camCar = 0;
int g_camSide = 1;
uint32_t g_camFrame = 0, g_now = 0;
int g_enabled = -1;
bool g_log = false;

float Clamp01(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
float Smooth(float e0, float e1, float x) {
    const float t = Clamp01((x - e0) / (e1 - e0));
    return t * t * (3.0f - 2.0f * t);
}
float Lerp(float a, float b, float t) { return a + (b - a) * t; }
float AngleLerp(float a, float b, float t) {
    float d = b - a;
    while (d > kPi) d -= 2.0f * kPi;
    while (d < -kPi) d += 2.0f * kPi;
    return a + d * t;
}

void Invert3(const gta2::Mat4& m, float out[3][3]) {
    const float a = m.m[0][0], b = m.m[0][1], c = m.m[0][2];
    const float d = m.m[1][0], e = m.m[1][1], f = m.m[1][2];
    const float g = m.m[2][0], h = m.m[2][1], i = m.m[2][2];
    const float A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
    float det = a * A + b * B + c * C;
    if (std::fabs(det) < 1e-9f) det = 1e-9f;
    const float k = 1.0f / det;
    // Row-vector convention: p_world = p_local * M, so p_local = (p_world - T) * M^-1.
    out[0][0] = A * k; out[0][1] = -(b * i - c * h) * k; out[0][2] = (b * f - c * e) * k;
    out[1][0] = B * k; out[1][1] = (a * i - c * g) * k;  out[1][2] = -(a * f - c * d) * k;
    out[2][0] = C * k; out[2][1] = -(a * h - b * g) * k; out[2][2] = (a * e - b * d) * k;
}

gta2::Vec3 ToWorld(const Car& c, float x, float y, float z) {
    const float (*m)[4] = c.m.m;
    return {x * m[0][0] + y * m[1][0] + z * m[2][0] + m[3][0], x * m[0][1] + y * m[1][1] + z * m[2][1] + m[3][1],
            x * m[0][2] + y * m[1][2] + z * m[2][2] + m[3][2]};
}
void ToLocal(const Car& c, float wx, float wy, float wz, float* x, float* y, float* z) {
    const float px = wx - c.m.m[3][0], py = wy - c.m.m[3][1], pz = wz - c.m.m[3][2];
    *x = px * c.inv[0][0] + py * c.inv[1][0] + pz * c.inv[2][0];
    *y = px * c.inv[0][1] + py * c.inv[1][1] + pz * c.inv[2][1];
    *z = px * c.inv[0][2] + py * c.inv[1][2] + pz * c.inv[2][2];
}
// A heading (world, atan2(x, z)) from a direction in the car's frame.
float HeadingOfLocal(const Car& c, float dx, float dz) {
    const float wx = dx * c.m.m[0][0] + dz * c.m.m[2][0], wz = dx * c.m.m[0][2] + dz * c.m.m[2][2];
    return std::atan2(wx, wz);
}
// A world heading as a direction in the car's frame, as an angle atan2(x, z) there.
float LocalHeading(const Car& c, float h) {
    const float wx = std::sin(h), wz = std::cos(h);
    const float x = wx * c.inv[0][0] + wz * c.inv[2][0], z = wx * c.inv[0][2] + wz * c.inv[2][2];
    return std::atan2(x, z);
}

// The door's geometry, car frame. A point (x, z) of the shut door, swung open by `open`.
void Swing(const Car& c, int side, float open, float x, float z, float* ox, float* oz) {
    const float hx = static_cast<float>(side) * 0.92f * c.halfW, hz = c.zFront;
    const float th = -static_cast<float>(side) * open * kDoorMaxAngle;
    const float cs = std::cos(th), sn = std::sin(th);
    *ox = hx + (x - hx) * cs + (z - hz) * sn;
    *oz = hz - (x - hx) * sn + (z - hz) * cs;
}
float DoorLen(const Car& c) { return (std::max)(0.12f, c.zFront - c.zRear); }
float HandleY(const Car& c) { return (std::max)(0.19f, (std::min)(0.26f, 0.62f * c.roof)); }
float SeatZ(const Car& c) { return c.zRear + 0.38f * DoorLen(c); }
// The driver sits about 0.13 block in from the door's skin, whatever the car's width;
// the feet in the footwell either side of that line.
// The half width is the sprite's footprint, mirrors included; the panel is a little in from it.
float SeatU(const Car& c) { return 0.5f * c.halfW; }
float WellDoorU(const Car& c) { return 0.62f * c.halfW; }
float WellFarU(const Car& c) { return 0.32f * c.halfW; }
// Where a hand grips the roof edge over the opening: the edge itself, or (a van taller
// than he can reach) the door frame at about head height.
float RoofGripY(const Car& c) { return (std::min)(c.roof * 0.93f, 0.40f); }   // the edge, a little under the crown (0.98 floated over the Minx's rounded roof)
float RoofGripU(const Car& c) { return c.roof * 0.98f > 0.40f ? c.halfW - 0.01f : c.halfW * 0.93f; }
// How far inside the footprint's edge the door's inner trim is (the footprint takes in the
// mirrors: a hand at the edge less a few centimetres showed through a shut van door).
float InsideOut(const Car& c) { return -(0.12f * c.halfW + 0.035f); }
// Where a hand holds the door from inside (its handle, its armrest): 2.5 cm deeper again. On a
// rounded body (013 Minx, aee_v2b) the skin is further in than the footprint suggests and the
// hand showed through the door's outer face as it began to open; a hand a little deeper is
// hidden by the door, one through it is not.
float HandInside(const Car& c) { return InsideOut(c) - 0.025f; }
constexpr float kDoorOpen = 0.75f;   // leaving: 45 degrees, room to step out
constexpr float kDoorEnter = 0.55f;  // getting in: 33 degrees, so its armrest is within an arm of the seat
constexpr float kFootwell = 0.12f;   // the feet ahead of the hips when seated
// The cab floor and the seat by the vehicle's height (a van's cab floor is well off the
// road), and how far the figure sinks to sit: its hip is 0.234 up standing (the avatars'
// skeleton), the seat cushion about 0.10 over the floor.
float FloorY(const Car& c) { return (std::max)(0.035f, (std::min)(0.10f, 0.18f * c.roof)); }
float SitSink(const Car& c) { return (std::max)(0.04f, (std::min)(0.11f, 0.234f - (FloorY(c) + 0.10f))); }
// FIX-SEATED: at the wheel for the drive he sits lower than the climb leaves him (a driver's hip
// is about 0.10 block over the road in a saloon, not the cushion's 0.16): low enough that his
// head (0.46 standing, 0.47 for the tallest look) clears the roof's inside by 2.5 cm, at most
// 0.14 (an open-top body's low "roof" is its windscreen: he shows over it, as he should).
// FIX-JACK-SEAT (pm19): an open-top body has no roof to clear: sunk to 0.14 under its windscreen "roof" the
// hero's head sat below the seat backs and the roadster read as driven by nobody; he sits on the cushion.
float DriveSink(const Car& c) {
    if (c.openTop) return SitSink(c);
    return (std::max)(SitSink(c), (std::min)(0.14f, 0.47f - (c.roof - 0.025f)));
}
// The steering wheel's hub, car frame: in line with the seat, 0.085 ahead of the hips' line and
// 0.06 under the shoulder (0.34 standing, less the sink): the hands reach it with the elbows bent
// (the arm is 0.124 to the wrist). Its rim 0.032 (a 0.3 m wheel at 4.8 m a block), raked 25 deg.
constexpr float kWheelAhead = 0.085f, kWheelUnder = 0.06f, kWheelR = 0.032f, kWheelRake = 0.44f;
constexpr float kPedalAhead = 0.17f;   // seated: the feet on the pedals, ahead of the hips

// A point on the door, given as a fraction along it from the hinge (0) to the rear
// edge (1), a height, and how far out of its outer skin (negative: inside), world.
gta2::Vec3 DoorPoint(const Car& c, int side, float open, float along, float y, float out) {
    const float s = static_cast<float>(side);
    const float x = s * (c.halfW + out), z = c.zFront - along * DoorLen(c);
    float ox, oz;
    Swing(c, side, open, x, z, &ox, &oz);
    return ToWorld(c, ox, y, oz);
}
gta2::Vec3 CarPoint(const Car& c, int side, float u, float y, float z) {
    return ToWorld(c, static_cast<float>(side) * u, y, z);
}

// Where a figure that got out stands clear of the open door's swing: outside the hull by
// 6 cm and 7 cm behind the door's rear edge (open as an exit leaves it), at most 0.09 block
// off the game's spot (gu, gz: car frame, u outward). Standing where the game puts him (u
// 0.45 of a 0.24 half-width Minx, z at the seat) is right on that edge: the panel crossed
// his chest as he rose and its frame his face as it shut (aee_v2b, aee_v4b).
void ClearSpot(const Car& c, float gu, float gz, float* su, float* sz);
// An arc from a to b lifted by `lift` at its middle (a foot over the sill).
gta2::Vec3 Arc(const gta2::Vec3& a, const gta2::Vec3& b, float t, float lift) {
    const float s = t * t * (3.0f - 2.0f * t);
    gta2::Vec3 p = a + (b - a) * s;
    p.y += lift * 4.0f * t * (1.0f - t);
    return p;
}

void ClearSpot(const Car& c, float gu, float gz, float* su, float* sz) {
    const float edgeZ = c.zFront - DoorLen(c) * std::cos(kDoorOpen * kDoorMaxAngle);
    float ou = (std::max)(gu, c.halfW + 0.06f) - gu, oz = (std::min)(gz, edgeZ - 0.07f) - gz;
    const float ol = std::sqrt(ou * ou + oz * oz);
    if (ol > 0.09f) { ou *= 0.09f / ol; oz *= 0.09f / ol; }
    *su = gu + ou; *sz = gz + oz;
}

const Car* NearestCar(float x, float z, uint32_t now, uintptr_t* object) {
    const Car* best = nullptr;
    float bd = 1.3f * 1.3f;
    for (auto& e : g_cars) {
        if (now - e.second.frame > 3) continue;
        const float dx = e.second.m.m[3][0] - x, dz = e.second.m.m[3][2] - z;
        const float d2 = dx * dx + dz * dz;
        if (d2 < bd) { bd = d2; best = &e.second; *object = e.first; }
    }
    return best;
}

void SetLimb(Board& b, int limb, const gta2::Vec3& t, const gta2::Vec3& pole, float w) {
    if (w <= 0.01f) { b.limbOn[limb] = false; b.limbW[limb] = 0.0f; return; }
    b.limbOn[limb] = true; b.limbT[limb] = t; b.limbPole[limb] = pole; b.limbW[limb] = Clamp01(w);
}

}  // namespace

void BoardingWorldToModel(const gta2::Mat4& world, const gta2::Vec3& p, bool dir, float out[3]) {
    float inv[3][3];
    Invert3(world, inv);
    const float px = dir ? p.x : p.x - world.m[3][0], py = dir ? p.y : p.y - world.m[3][1], pz = dir ? p.z : p.z - world.m[3][2];
    for (int k = 0; k < 3; ++k) out[k] = px * inv[0][k] + py * inv[1][k] + pz * inv[2][k];
}

bool BoardingDebugCamera(gta2::Vec3* eye, float* yaw, float* pitch) {
    static int on = -1;
    if (on < 0) { const char* v = std::getenv("GTA2DX9_BOARDING_CAM"); on = v && (v[0] == '1' || v[0] == '2') ? v[0] - '0' : 0; }
    if (!on || !g_camCar || g_now - g_camFrame > 45) return false;
    auto it = g_cars.find(g_camCar);
    if (it == g_cars.end()) return false;
    const Car& c = it->second;
    const float seatZ = SeatZ(c);
    // 1: behind the door (rear quarter); 2: ahead of it (front quarter: the door's swing
    // and the figure behind it are both seen, for the shut after an exit).
    const gta2::Vec3 e = on == 2 ? CarPoint(c, g_camSide, c.halfW + 0.80f, 0.42f, seatZ + 0.60f)
                                 : CarPoint(c, g_camSide, c.halfW + 0.85f, 0.42f, seatZ - 0.35f);
    const gta2::Vec3 t = on == 2 ? CarPoint(c, g_camSide, c.halfW + 0.08f, 0.2f, seatZ - 0.08f)
                                 : CarPoint(c, g_camSide, c.halfW + 0.05f, 0.2f, seatZ + 0.02f);
    const float dx = t.x - e.x, dy = t.y - e.y, dz = t.z - e.z;
    *eye = e;
    *yaw = std::atan2(dx, dz);
    *pitch = std::atan2(dy, std::sqrt(dx * dx + dz * dz));
    return true;
}

bool BoardingEnabled() {
    if (g_enabled < 0) {
        const char* v = std::getenv("GTA2DX9_BOARDING");
        g_enabled = (v && v[0] == '0') ? 0 : 1;
        Log("boarding: %s (GTA2DX9_BOARDING)", g_enabled ? "on" : "off");
    }
    return g_enabled != 0;
}
void BoardingSetLog(bool on) { g_log = on; }

void BoardingPublishCar(uintptr_t carObject, const gta2::Mat4& carToWorld, float halfW, float zFront, float zRear,
                        float roof, int doorSide, float doorOpen, uint32_t frame) {
    Car& c = g_cars[carObject];
    if (c.frame && frame > c.frame && frame - c.frame < 6) {
        const float dx = carToWorld.m[3][0] - c.lastX, dz = carToWorld.m[3][2] - c.lastZ;
        const float v = std::sqrt(dx * dx + dz * dz) * 30.0f / static_cast<float>(frame - c.frame);
        c.speed += (v - c.speed) * 0.3f;
    }
    c.lastX = carToWorld.m[3][0]; c.lastZ = carToWorld.m[3][2];
    c.m = carToWorld;
    Invert3(carToWorld, c.inv);
    c.halfW = halfW; c.zFront = zFront; c.zRear = zRear; c.roof = roof;
    c.doorSide = doorSide; c.doorOpen = doorOpen;
    c.frame = frame;
    if (g_cars.size() > 256) {
        for (auto it = g_cars.begin(); it != g_cars.end();) it = frame - it->second.frame > 120 ? g_cars.erase(it) : std::next(it);
    }
}

void BoardingPublishOpenTop(uintptr_t carObject, bool openTop) {
    auto it = g_cars.find(carObject);
    if (it != g_cars.end()) it->second.openTop = openTop;
}

void BoardingPublishSteer(uintptr_t carObject, float steer) {
    auto it = g_cars.find(carObject);
    if (it != g_cars.end()) it->second.steer = steer;
}

bool BoardingDoor(uintptr_t carObject, int* side, float* target, float* rate) {
    if (!BoardingEnabled()) return false;
    for (auto& e : g_boards) {
        const Board& b = e.second;
        if (b.car != carObject || !b.doorOwn || b.ended) continue;
        *side = b.side; *target = b.doorTarget; *rate = b.doorRate;
        return true;
    }
    return false;
}

bool BoardingWarmDoors(uintptr_t carObject) {
    (void)carObject;
    return BoardingEnabled();
}

bool BoardingUpdate(const BoardingIn& in, BoardingOut* out) {
    if (!BoardingEnabled()) return false;
    Board& b = g_boards[in.ped];
    const uint32_t gap = b.seen ? in.now - b.seen : 0;
    // A boarding left for a while (the ped gone, or drawn again after a gap) is over;
    // so is a finished one once the game starts the other act (in after out, out after in).
    if (b.mode != kNone && b.mode != kSeated && gap > 8) b = Board{};   // (seated: kept while his car is drawn, see below)
    if ((b.ended && ((b.mode == kExit && in.state == 3) || (b.mode == kClimb && in.state == 4))) ||
        (b.mode == kShut && (in.state == 3 || in.state == 4)) ||
        (b.mode == kSeated && !in.ghost && in.state != 3)) {   // seated, and the game draws him again: an exit (planned below
                                                               // from kNone), a jack, a dive (state 3: the climb's last sprites)
        const float px = b.px, pz = b.pz; const bool hp = b.havePrev;
        b = Board{}; b.px = px; b.pz = pz; b.havePrev = hp;
    }
    // Where the figure was drawn last frame: the plan starts from there, not from where
    // the renderer's spring put it this frame (the game moves him to the door in a jump).
    const bool prevOk = b.havePrev && gap == 1;
    const float startX = prevOk ? b.px : in.drawnX, startZ = prevOk ? b.pz : in.drawnZ;
    b.seen = in.now;
    g_now = in.now;
    if (in.own) b.player = true;
    if (in.jacking) b.jacking = true;
    // A new figure's first frame comes with the renderer's capped catch-up step (0.2 s).
    const float dt = gap == 1 ? (std::min)(in.dt, 2.0f / 30.0f) : 1.0f / 30.0f;
    for (bool& on : b.limbOn) on = false;

    const bool climbing = in.state == 3 && in.frame >= 24 && in.frame <= 35;
    const bool approaching = in.state == 3 && !climbing;
    const bool exiting = in.state == 4;

    // Mode changes from the game's words.
    if (b.mode == kNone || b.mode == kApproach) {
        if (climbing || approaching || exiting) {
            uintptr_t carObj = 0;
            const Car* c = (b.car && g_cars.count(b.car) && in.now - g_cars[b.car].frame <= 3) ? &g_cars[b.car]
                                                                                              : NearestCar(in.gameX, in.gameZ, in.now, &carObj);
            if (c && !b.car) b.car = carObj;
            // An exit from a car on the move is a different act (a dive): left to the clips.
            if (c && !(exiting && c->speed > 0.6f)) {
                float lx, ly, lz;
                ToLocal(*c, in.gameX, in.groundY, in.gameZ, &lx, &ly, &lz);
                const int side = lx >= 0.0f ? 1 : -1;
                if (exiting) {
                    b.mode = kExit; b.t = 0.0f; b.side = side; b.ended = false;
                    b.gu0 = lx * side; b.gz0 = lz;
                    // The hand on the door's side opens it; the foot on the door's side goes out first.
                    const float hl = HeadingOfLocal(*c, static_cast<float>(side), 0.0f);   // facing out
                    (void)hl;
                } else if (climbing) {
                    b.mode = kClimb; b.t = 0.0f; b.side = side; b.ended = false; b.planted = false; b.innerSet = false; b.seg = -1;
                    float dx, dy, dz;
                    ToLocal(*c, startX, in.groundY, startZ, &dx, &dy, &dz);
                    b.u0 = dx * side; b.z0 = dz;
                    // How fast he was going (the renderer's figure, this frame against last).
                    float nx, ny, nz;
                    ToLocal(*c, in.drawnX, in.groundY, in.drawnZ, &nx, &ny, &nz);
                    const float span = (std::max)(in.dt, 1.0f / 30.0f);
                    b.v0u = prevOk ? (nx - dx) * side / span : 0.0f; b.v0z = prevOk ? (nz - dz) / span : 0.0f;
                    b.h0 = LocalHeading(*c, in.heading);
                } else {
                    b.mode = kApproach; b.side = side;
                }
            } else if (!c) {
                b.mode = kNone; b.car = 0;
            }
        } else if (b.mode == kApproach) {
            b = Board{};
        }
    } else if (b.mode == kExit && !exiting && b.t < 0.2f && in.state != 0 && in.state != 7) {
        // knocked out of the exit by something else (a jack, a fall): let go.
        b.ended = true;
    }
    if (b.mode == kNone || b.ended) {
        if (b.ended) { b.doorOwn = false; }
        b.px = in.drawnX; b.pz = in.drawnZ; b.havePrev = true;
        return false;
    }
    auto found = g_cars.find(b.car);
    if (found == g_cars.end() || in.now - found->second.frame > 6) { b = Board{}; return false; }
    const Car& c = found->second;
    const int s = b.side;
    if (b.player) { g_camCar = b.car; g_camSide = b.side; g_camFrame = in.now; }
    const float sf = static_cast<float>(s);
    const float hw = c.halfW, Ld = DoorLen(c), seatZ = SeatZ(c), hy = HandleY(c);
    const float open = c.doorSide == s ? c.doorOpen : 0.0f;
    // The figure's right for a heading h: (cos h, -sin h); its forward (sin h, cos h).
    auto rightOf = [](float h) { return gta2::Vec3{std::cos(h), 0.0f, -std::sin(h)}; };
    auto fwdOf = [](float h) { return gta2::Vec3{std::sin(h), 0.0f, std::cos(h)}; };
    const gta2::Vec3 up{0.0f, 1.0f, 0.0f};
    const gta2::Vec3 carFwd = gta2::Normalize(gta2::Vec3{c.m.m[2][0], 0.0f, c.m.m[2][2]});
    const gta2::Vec3 outward = gta2::Normalize(gta2::Vec3{c.m.m[0][0] * sf, 0.0f, c.m.m[0][2] * sf});
    // Elbow poles: back, out to the hand's side and down; knee poles: ahead and up.
    auto elbowPole = [&](int limb, float h) {
        const gta2::Vec3 r = rightOf(h) * (limb == 1 ? 1.0f : -1.0f);
        return gta2::Normalize(r * 0.6f - fwdOf(h) * 0.6f - up * 0.5f);
    };
    auto kneePole = [&](float h) { return gta2::Normalize(fwdOf(h) + up * 0.4f); };
    // A hand holding the door from inside (its handle, its armrest): the elbow bent in and
    // down, into the cab. Bent out to the hand's side, the forearm came through the door's
    // outer face while he pulled it shut (aee_h2front frames 52-72).
    auto insidePole = [&](float h) { return gta2::Normalize(outward * -0.7f - up * 0.6f - fwdOf(h) * 0.2f); };

    float u = 0.0f, z = 0.0f, sink = 0.0f, hLocal = 0.0f;   // the plan, car frame
    bool usePlanPos = true;
    out->action = 0;
    out->clipT = 0.0f;
    b.doorOwn = true;

    if (b.mode == kSeated) {
        // ---- At the wheel (FIX-SEATED) -----------------------------------------
        // Hips on the seat, facing the car's nose, sunk to DriveSink; both hands on the wheel's
        // rim at ten to two, turned with the front wheels; the feet on the pedals; the head
        // into the turn. From the climb's end everything eases over 0.5 s (the hands come off
        // the clip onto the rim, the feet slide from the footwell to the pedals, he settles).
        b.t += dt;
        const float k = Smooth(0.0f, 0.5f, b.t);
        const float sink = Lerp(b.sink0, DriveSink(c), k);
        const float seatU = SeatU(c);
        const gta2::Vec3 p = CarPoint(c, s, seatU, 0.0f, seatZ);
        const float h = HeadingOfLocal(c, 0.0f, 1.0f);
        const gta2::Vec3 fwd = fwdOf(h), right = rightOf(h);
        // The wheel turns with the front wheels (+ to the car's left: the rim's top goes left),
        // about 3:1 (a hand never crosses the top), at most 100 degrees.
        const float wheelA = (std::max)(-1.75f, (std::min)(1.75f, -3.0f * c.steer));
        const float shoulderY = 0.34f - sink;
        const gta2::Vec3 hub = CarPoint(c, s, seatU, shoulderY - kWheelUnder, seatZ + kWheelAhead);
        const gta2::Vec3 rimUp = up * std::cos(kWheelRake) - fwd * std::sin(kWheelRake);
        for (int limb = 0; limb < 2; ++limb) {
            const float a = (limb == 1 ? 1.05f : -1.05f) + wheelA;   // 60 degrees either side of the top
            const gta2::Vec3 grip = hub + right * (kWheelR * std::sin(a)) + rimUp * (kWheelR * std::cos(a));
            const gta2::Vec3 r = right * (limb == 1 ? 1.0f : -1.0f);
            SetLimb(b, limb, grip, gta2::Normalize(r * 0.7f - up * 0.7f - fwd * 0.15f), Smooth(0.1f, 0.5f, b.t));
        }
        // Feet: the one on the door's side by the door, the other toward the middle.
        for (int f = 0; f < 2; ++f) {
            const int limb = 2 + f;
            const bool doorSide = gta2::Dot(right * (limb == 3 ? 1.0f : -1.0f), outward) > 0.0f;
            gta2::Vec3 pedal = CarPoint(c, s, doorSide ? WellDoorU(c) * 0.9f : WellFarU(c), FloorY(c), seatZ + kPedalAhead);
            if (b.footFromSet && k < 1.0f) {
                const gta2::Vec3 from = ToWorld(c, b.footFrom[f][0], b.footFrom[f][1], b.footFrom[f][2]);
                pedal = from + (pedal - from) * k;
            }
            SetLimb(b, limb, pedal, kneePole(h), 1.0f);
        }
        b.headYaw += ((std::max)(-0.5f, (std::min)(0.5f, -0.6f * c.steer * 3.0f)) - b.headYaw) * (std::min)(1.0f, dt / 0.3f);
        out->x = p.x; out->z = p.z; out->sink = sink; out->heading = h;
        out->action = 5; out->clipT = 1.3f;             // enter_car's fold (seated) ...
        out->clipW = Lerp(1.0f, 0.15f, k);              // ... eased off to a slight lean: upright against the seat back
        out->seated = true; out->headYaw = b.headYaw;
        out->vx = b.haveOut ? (out->x - b.lastOutX) / dt : 0.0f;
        out->vz = b.haveOut ? (out->z - b.lastOutZ) / dt : 0.0f;
        b.lastOutX = out->x; b.lastOutZ = out->z; b.haveOut = true;
        b.out = *out;
        b.px = out->x; b.pz = out->z; b.havePrev = true;
        if (g_log && (in.now % 15u) == 0)
            Log("board: f=%u ped=%04x seated t=%.2f side=%d sink=%.3f roof=%.3f steer=%.2f wheel=%.2f head=%.2f pos=%.3f,%.3f hd=%.2f",
                in.now, static_cast<unsigned>((in.ped >> 2) & 0xFFFF), b.t, s, sink, c.roof, c.steer, wheelA, b.headYaw, out->x, out->z, h);
        return true;
    }
    if (b.mode == kShut) {
        // ---- Shutting the door behind him --------------------------------------
        // Standing up out of the seat leaves him inside the door's swing (0.21 from the
        // hinge of a 0.25 door, aee_v2b: its frame crossed his face as it shut). So: a short
        // step back along the car, clear of the door's rear edge (eased in over 0.3 s, at most
        // 0.09 block off the game's spot, which the legs step), turned toward that edge; the
        // hand toward the hinge takes it at handle height and shoves: the door swings at 1.5
        // a second while the hand is on it, and once it is out of his reach the hand lets go
        // and it carries on by itself (2.2 a second) to shut. Then the step back to the
        // game's spot (0.35 s). If the game walks him off meanwhile, all of it lets go.
        b.t += dt;
        b.st += dt;
        if (b.player) { g_camCar = b.car; g_camSide = b.side; g_camFrame = in.now; }
        float gu, gz;
        {
            float lx, ly, lz;
            ToLocal(c, in.gameX, in.groundY, in.gameZ, &lx, &ly, &lz);
            gu = lx * sf; gz = lz;
        }
        float gameV = 0.0f;
        if (b.haveGame) gameV = std::sqrt((in.gameX - b.lgx) * (in.gameX - b.lgx) + (in.gameZ - b.lgz) * (in.gameZ - b.lgz)) / dt;
        b.lgx = in.gameX; b.lgz = in.gameZ; b.haveGame = true;
        if (gameV > 0.3f) b.walkedOff = true;
        // Where to stand: clear of the door's swing (the exit already ended there).
        float su, sz;
        ClearSpot(c, gu, gz, &su, &sz);
        const bool doorShut = open < 0.02f && b.st > 0.2f;
        if (doorShut && b.shutAt < 0.0f) b.shutAt = b.st;
        const float offTarget = (b.walkedOff || b.shutAt >= 0.0f) ? 0.0f : 1.0f;
        const float offRate = b.walkedOff ? dt / 0.12f : (offTarget > b.shutOff ? dt / 0.3f : dt / 0.35f);
        b.shutOff += (offTarget - b.shutOff) * (std::min)(1.0f, offRate * 2.0f);
        const float k = b.shutOff * b.shutOff * (3.0f - 2.0f * b.shutOff);
        // The base: the game's spot, followed through a 0.1 s filter from where the figure
        // stood at the hand-off (not the renderer's follow, which starts each frame from this
        // module's last output and would compound the offset); plus the offset.
        if (!b.haveBase) {
            // (the hand-off position already stands off by the clear-spot offset)
            float lx, ly, lz;
            ToLocal(c, startX, in.groundY, startZ, &lx, &ly, &lz);
            b.bu = lx * sf - (su - gu) * b.shutOff; b.bz = lz - (sz - gz) * b.shutOff; b.haveBase = true;
        }
        b.bu += (gu - b.bu) * (std::min)(1.0f, dt / 0.1f);
        b.bz += (gz - b.bz) * (std::min)(1.0f, dt / 0.1f);
        const float du = b.bu, dzl = b.bz;
        const float u1 = du + (su - gu) * k, z1 = dzl + (sz - gz) * k;
        const gta2::Vec3 p = CarPoint(c, s, u1, 0.0f, z1);
        // Turned half way from facing out toward the car's front (the door's edge is ahead of
        // him and a little in): turning to face the edge squarely was a 150 degree turn and
        // back, which the stepping legs made read as a walk round (aee_v4b). The hand on the
        // edge's side takes it.
        const gta2::Vec3 edge = DoorPoint(c, s, open, 0.97f, hy, 0.0f);
        const float faceShut = HeadingOfLocal(c, sf * 0.7f, 0.7f);
        if (b.shutH0 > 9.0f) b.shutH0 = in.heading;
        const float h = AngleLerp(b.shutH0, faceShut, k * Smooth(0.0f, 0.3f, b.st));
        if (b.shutHand < 0) {
            const gta2::Vec3 toEdge{edge.x - p.x, 0.0f, edge.z - p.z};
            b.shutHand = gta2::Dot(rightOf(faceShut), toEdge) >= 0.0f ? 1 : 0;
        }
        const int limb = b.shutHand;
        const float dx = edge.x - p.x, dz = edge.z - p.z;
        const float d = std::sqrt(dx * dx + dz * dz);
        // The hand holds within 0.10 block of the feet's line (the edge at handle height is then
        // within the arm's 0.124 from a shoulder 0.043 to the side; past 0.11 it fell 3-9 cm
        // short in aee_v1a/b) and lets go by 0.14; only once he has stepped clear.
        const bool ready = b.st > 0.15f;   // half the turn first
        const float want = (b.released || b.walkedOff || !ready) ? 0.0f : Smooth(0.14f, 0.10f, d);
        if (b.shutW > 0.6f && want < 0.5f) b.released = true;
        b.shutW += (want - b.shutW) * (std::min)(1.0f, dt / 0.05f);
        if (b.shutW > 0.02f) SetLimb(b, limb, edge, elbowPole(limb, h), b.shutW);
        const bool push = b.shutW > 0.6f || b.released || b.walkedOff || b.st > 1.2f;
        b.doorTarget = push ? 0.0f : kDoorOpen;
        b.doorRate = (b.released || b.walkedOff || b.st > 1.2f) ? 2.2f : 1.5f;
        if ((b.shutAt >= 0.0f && b.shutOff < 0.01f) || b.st > 3.0f) {
            b.ended = true; b.doorOwn = false;
            for (bool& on : b.limbOn) on = false;
            b.px = in.drawnX; b.pz = in.drawnZ; b.havePrev = true;
            return false;
        }
        out->x = p.x; out->z = p.z; out->sink = 0.0f; out->heading = h; out->action = 0; out->clipT = 0.0f;
        out->vx = b.haveOut ? (out->x - b.lastOutX) / dt : 0.0f;
        out->vz = b.haveOut ? (out->z - b.lastOutZ) / dt : 0.0f;
        b.lastOutX = out->x; b.lastOutZ = out->z; b.haveOut = true;
        b.out = *out;
        b.px = out->x; b.pz = out->z; b.havePrev = true;
        if (g_log) Log("board: f=%u ped=%04x mode=%d t=%.2f side=%d shut st=%.2f off=%.2f hand=%d w=%.2f d=%.3f door=%.2f->%.0f gv=%.2f pos=%.3f,%.3f hd=%.2f",
                       in.now, static_cast<unsigned>((in.ped >> 2) & 0xFFFF), b.mode, b.t, s, b.st, k, limb, b.shutW, d, open, b.doorTarget,
                       gameV, out->x, out->z, h);
        return true;
    }
    if (b.mode == kApproach) {
        // Walking to the door: the game places him; the hand on the door's side
        // reaches for the handle once he is within an arm of it.
        usePlanPos = false;
        // FIX-JACK-SEAT: the side he is on now (the game walks him round the back to the door it
        // chose: the near door, opened as he came, stayed open on the wrong side of a truck).
        {
            float lx, ly, lz;
            ToLocal(c, in.gameX, in.groundY, in.gameZ, &lx, &ly, &lz);
            b.side = lx >= 0.0f ? 1 : -1;
        }
        const int s = b.side;
        const float open = c.doorSide == s ? c.doorOpen : 0.0f;
        const gta2::Vec3 handle = DoorPoint(c, s, open, 0.93f, hy, 0.015f);
        const float dx = handle.x - in.drawnX, dz = handle.z - in.drawnZ;
        const float d = std::sqrt(dx * dx + dz * dz);
        const float h = in.heading;
        const int hand = gta2::Dot(rightOf(h), carFwd) >= 0.0f ? 1 : 0;   // the hand toward the hinge
        b.doorHand = hand;
        const float reach = c.speed < 0.3f ? Smooth(0.30f, 0.14f, d) : 0.0f;
        if (reach > 0.0f) SetLimb(b, hand, handle, elbowPole(hand, h), reach);
        // The door stays shut until his hand is on it (an already open one is not shut again).
        b.doorOwn = c.speed < 0.3f;
        b.doorTarget = (reach > 0.85f || open > 0.05f) ? kDoorOpen : 0.0f;
        b.doorRate = 2.5f;
        out->x = in.drawnX; out->z = in.drawnZ; out->sink = 0.0f; out->heading = in.heading;
        b.out = *out;
        b.px = in.drawnX; b.pz = in.drawnZ; b.havePrev = true;
        return false;   // position and clips stay the renderer's; only the hand (BoardingLimb)
    }

    // QB-14: a jacker waits at the door he has yanked open until the driver is out of it,
    // so he never steps into the opening through him. FIX-JACK-SEAT (feel14): for as long as
    // the game keeps him there (a jammed or creeping car holds him at the door for seconds;
    // with the old 1.5 s cap the figure sat down in a seat the driver still filled), until the
    // game starts moving him in (frames 32+) or stops drawing him; 10 s at most.
    // FIX-JACK-SEAT (feel13): once the game stops drawing him he is in its car - often already
    // driving off - so the rest of the climb (the step in, the sit, the door pulled shut) is
    // played inside 0.6 s (0.4 s on the move) instead of the plan's own 2.1 s, which left a
    // standing figure carried along beside the car with its door open.
    out->held = false;
    out->rate = 1.0f;
    if (b.mode == kClimb && in.ghost && b.t < 2.1f && b.rush <= 0.0f) {
        b.rush = (std::max)(1.0f, (2.1f - b.t) / (c.speed > 0.3f ? 0.4f : 0.6f));
        if (g_log || in.own) Log("board: f=%u ped=%04x in per the game at t=%.2f: the rest at x%.1f (car %.2f b/s)", in.now,
                       static_cast<unsigned>((in.ped >> 2) & 0xFFFF), b.t, b.rush, c.speed);
    }
    const float rate = b.mode == kClimb && b.rush > 0.0f ? b.rush : 1.0f;
    const bool gameHolds = in.state == 3 && !in.ghost && in.frame < 32;
    if (b.mode == kClimb && b.jacking && in.driverIn && gameHolds && b.t >= 0.45f && b.held < 10.0f) {
        b.held += dt; out->held = true;
    } else {
        b.t += dt * rate;
    }
    out->rate = rate;
    const float t = b.t;
    const float rx = sf;   // u to x

    if (b.mode == kClimb) {
        // ---- In --------------------------------------------------------------
        // 0.00-0.25 to the handle; 0.15-0.45 the door pulled open (to 45 degrees), a step
        // back with it; 0.45-0.60 the hand lets go; 0.50-0.85 round the door's end into
        // the opening, the inner foot over the sill; 0.85-1.30 duck and sit, the outer foot
        // in, the outer hand on the door's inside handle pulling it shut (1.0-1.5).
        const float handleU = hw + 0.015f;
        float hdU, hdZ;   // the handle now (car frame, u/z)
        {
            float ox, oz;
            Swing(c, s, open, sf * handleU, c.zFront - 0.93f * Ld, &ox, &oz);
            hdU = ox * sf; hdZ = oz;
        }
        const float s1u = handleU + 0.06f, s1z = c.zRear - 0.05f;             // at the shut door's handle
        // Following it as it swings, a step further back than the handle (0.06 out, 0.07 back):
        // at 0.045/0.05 the door's rear edge swept through his chest (aee_v5c frames 47-53).
        const float pullU = hdU + 0.06f, pullZ = hdZ - 0.07f;
        const float s2u = hw + 0.0f, s2z = c.zRear + 0.30f * Ld;              // in the opening
        const float seatU = SeatU(c);
        int seg = t < 0.25f ? 0 : t < 0.5f ? 1 : t < 0.85f ? 2 : 3;
        if (seg != b.seg) { b.seg = seg; b.segU = b.lastU; b.segZ = b.lastZ; if (seg == 0) { b.segU = b.u0; b.segZ = b.z0; } }
        if (seg == 0) {
            // A Hermite curve that leaves with the speed he arrived at (no stop in one frame).
            const float k = Clamp01(t / 0.25f), k2 = k * k, k3 = k2 * k;
            const float h00 = 2 * k3 - 3 * k2 + 1, h10 = k3 - 2 * k2 + k, h01 = -2 * k3 + 3 * k2;
            float mu = b.v0u * 0.25f, mz = b.v0z * 0.25f;
            const float ml = std::sqrt(mu * mu + mz * mz);
            // (up to a run's 1.8 blocks a second: a cap of 1.0 popped a runner at the door, aee_v1b)
            if (ml > 0.45f) { mu *= 0.45f / ml; mz *= 0.45f / ml; }
            u = h00 * b.segU + h10 * mu + h01 * s1u; z = h00 * b.segZ + h10 * mz + h01 * s1z;
        } else if (seg == 1) {
            const float k = Smooth(0.25f, 0.5f, t);
            u = Lerp(b.segU, (std::max)(s1u, pullU), k); z = Lerp(b.segZ, (std::min)(s1z, pullZ), k);
        } else if (seg == 2) {
            // Into the opening through the middle of the wedge between the open door and the
            // body (a curve through it, not the straight line, which clipped the door's rear end:
            // at 33 degrees the wedge's mouth is about 0.12 block wide).
            const float k = Smooth(0.5f, 0.85f, t);
            const float ang = kDoorEnter * kDoorMaxAngle;
            const float wz = c.zFront - Ld * std::cos(ang) + 0.01f;                      // just inside the door's end
            const float wu = 0.5f * (hw + 0.92f * hw + (c.zFront - wz) * std::tan(ang));  // half way across the wedge there
            const float cu = 2.0f * wu - 0.5f * (b.segU + s2u), cz = 2.0f * wz - 0.5f * (b.segZ + s2z);
            const float a0 = (1.0f - k) * (1.0f - k), a1 = 2.0f * k * (1.0f - k), a2 = k * k;
            u = a0 * b.segU + a1 * cu + a2 * s2u; z = a0 * b.segZ + a1 * cz + a2 * s2z;
        } else {
            const float k = Smooth(0.85f, 1.25f, t);
            u = Lerp(b.segU, seatU, k); z = Lerp(b.segZ, seatZ, k);
            sink = SitSink(c) * k;
        }
        b.lastU = u; b.lastZ = z;
        // Heading: facing the handle (into the car, turned toward the front), then
        // turning to face forward as he steps in.
        const float faceIn = std::atan2(-rx * 0.8f, 0.6f);    // local: inward and forward
        hLocal = AngleLerp(AngleLerp(b.h0, faceIn, Smooth(0.0f, 0.25f, t)), 0.0f, Smooth(0.55f, 1.15f, t));
        // The door: open to 33 degrees and left open while he gets in; pulled shut from
        // 1.45 by its armrest (1.6 a second: shut at 1.8).
        b.doorTarget = t < 1.45f ? (b.jacking ? kDoorOpen : kDoorEnter) : 0.0f;
        b.doorRate = (t < 1.45f ? 2.5f : 1.6f) * rate;
        // The clip (enter_car, 1.3 s: reach 0.35, pull 0.65, duck 0.95, folded 1.3).
        out->action = 5;
        out->clipT = t < 0.2f ? 0.15f + t : t < 0.5f ? 0.35f + (t - 0.2f) * 1.0f
                   : t < 0.85f ? 0.65f + (t - 0.5f) * 0.43f : (std::min)(1.3f, 0.8f + (t - 0.85f) * 1.1f);
        // Limbs.
        const float h = HeadingOfLocal(c, std::sin(hLocal), std::cos(hLocal));
        const gta2::Vec3 inward = outward * -1.0f;
        if (t < 0.05f) b.doorHand = gta2::Dot(rightOf(h), carFwd) >= 0.0f ? 1 : 0;   // the hand toward the hinge
        // The door hand: on the handle while the door opens (let go at 0.45-0.6); seated, on
        // the armrest half way along it (1.25-1.45), pulling it shut, let go once it is.
        {
            const gta2::Vec3 handle = DoorPoint(c, s, open, 0.93f, hy, 0.015f);
            const gta2::Vec3 arm = DoorPoint(c, s, open, 0.4f, (std::max)(hy * 0.9f, FloorY(c) + 0.17f), HandInside(c));
            const bool second = t > 0.9f;
            const float w = second ? Smooth(1.2f, 1.42f, t) * (1.0f - Smooth(1.85f, 2.0f, t))
                                   : Smooth(0.0f, 0.18f, t) * (1.0f - Smooth(0.45f, 0.6f, t));
            SetLimb(b, b.doorHand, second ? arm : handle, second ? insidePole(h) : elbowPole(b.doorHand, h), w);
        }
        // The other hand on the roof edge (or a van's door frame) while he ducks in.
        if (t >= 0.6f && !b.jacking) {
            const int roofHand = 1 - b.doorHand;
            const gta2::Vec3 roofEdge = CarPoint(c, s, RoofGripU(c), RoofGripY(c), c.zRear + 0.62f * Ld);
            SetLimb(b, roofHand, roofEdge, elbowPole(roofHand, h), Smooth(0.65f, 0.82f, t) * (1.0f - Smooth(1.0f, 1.2f, t)));
        }
        // Feet: the inner one (on the car's side of him) over the sill onto the floor by the
        // door (0.56-0.85), then into the footwell as he sits (0.9-1.25); the outer one planted
        // on the road, then in (1.0-1.3).
        {
            const int inner = gta2::Dot(rightOf(h), inward) >= 0.0f ? 3 : 2;
            const int outer = inner == 3 ? 2 : 3;
            const gta2::Vec3 kp = kneePole(h);
            const gta2::Vec3 here = CarPoint(c, s, u, 0.0f, z);
            const gta2::Vec3 sill = CarPoint(c, s, hw - 0.07f, FloorY(c), (std::min)(seatZ + 0.03f, s2z + 0.06f));
            const gta2::Vec3 wellIn = CarPoint(c, s, WellDoorU(c), FloorY(c), seatZ + kFootwell);
            const gta2::Vec3 wellOut = CarPoint(c, s, WellFarU(c), FloorY(c), seatZ + kFootwell);
            if (t >= 0.53f) {
                if (!b.innerSet) {
                    const gta2::Vec3 p = here + rightOf(h) * (inner == 3 ? 0.035f : -0.035f);
                    float lx, ly, lz;
                    ToLocal(c, p.x, p.y, p.z, &lx, &ly, &lz);
                    b.innerU = lx * sf; b.innerZ = lz; b.innerSet = true;
                }
                const gta2::Vec3 start = CarPoint(c, s, b.innerU, 0.0f, b.innerZ);
                gta2::Vec3 target = Arc(start, sill, Clamp01((t - 0.56f) / 0.29f), 0.06f + FloorY(c));
                target = target + (wellIn - target) * Smooth(0.9f, 1.25f, t);
                SetLimb(b, inner, target, kp, Smooth(0.53f, 0.58f, t));
            }
            if (t >= 0.85f) {
                if (!b.planted) {
                    const gta2::Vec3 p = here + rightOf(h) * (outer == 3 ? 0.035f : -0.035f);
                    float lx, ly, lz;
                    ToLocal(c, p.x, p.y, p.z, &lx, &ly, &lz);
                    b.plantU = lx * sf; b.plantZ = lz; b.planted = true;
                }
                const gta2::Vec3 plant = CarPoint(c, s, b.plantU, 0.0f, b.plantZ);
                SetLimb(b, outer, Arc(plant, wellOut, Clamp01((t - 1.0f) / 0.3f), 0.07f + FloorY(c)), kp, Smooth(0.85f, 0.9f, t));
            }
        }
        if (t > 2.1f) {
            // FIX-SEATED: in his seat for the drive (it was `ended` here, and the ghost with it:
            // the cockpit stayed empty until he got out again).
            b.mode = kSeated; b.t = 0.0f; b.doorOwn = false; b.sink0 = sink; b.footFromSet = false;
            for (int f = 0; f < 2; ++f) {
                if (!b.limbOn[2 + f]) continue;
                float lx, ly, lz;
                ToLocal(c, b.limbT[2 + f].x, b.limbT[2 + f].y, b.limbT[2 + f].z, &lx, &ly, &lz);
                b.footFrom[f][0] = lx; b.footFrom[f][1] = ly; b.footFrom[f][2] = lz; b.footFromSet = true;
            }
        }
    } else {
        // ---- Out -------------------------------------------------------------
        // 0.00-0.30 the door pushed open from inside; 0.10-0.40 the outer foot over the
        // sill to the road, turning out; 0.20-0.80 a hand on the roof edge, up out of
        // the seat and onto the game's own position; free at 0.85.
        const float seatU = SeatU(c);
        const float midU = hw * 0.85f, midZ = seatZ - 0.01f;
        float gu = b.gu0, gz = b.gz0;   // the game's position now, car frame
        {
            float lx, ly, lz;
            ToLocal(c, in.gameX, in.groundY, in.gameZ, &lx, &ly, &lz);
            gu = lx * sf; gz = lz;
        }
        // Where he will stand: the game slides him 0.15 out over its exit state.
        // The game slides him out in 5 cm steps every few frames: followed through a 0.1 s filter.
        if (!b.fSet) { b.fu = b.gu0 + 0.15f; b.fz = b.gz0; b.fSet = true; }
        b.fu += (gu - b.fu) * (std::min)(1.0f, dt / 0.1f);
        b.fz += (gz - b.fz) * (std::min)(1.0f, dt / 0.1f);
        // ... and clear of the door's swing (ClearSpot): the shut that follows starts there.
        float endU, endZ;
        ClearSpot(c, b.fu, b.fz, &endU, &endZ);
        if (t < 0.15f) {
            u = seatU; z = seatZ; sink = SitSink(c);
        } else if (t < 0.45f) {
            const float k = Smooth(0.15f, 0.45f, t);
            u = Lerp(seatU, midU, k); z = Lerp(seatZ, midZ, k); sink = Lerp(SitSink(c), SitSink(c) * 0.75f, k);
        } else {
            const float k = Smooth(0.45f, 0.8f, t);
            // Onto where the game will have him (it slides him out in steps; following those
            // would step the figure), clear of the door: back along the car a little ahead of
            // the step out (z by 0.70, u by 0.80), so he rounds the door's rear edge instead
            // of passing through it.
            const float kz = Smooth(0.45f, 0.70f, t);
            u = Lerp(midU, endU, k); z = Lerp(midZ, endZ, kz); sink = Lerp(SitSink(c) * 0.75f, 0.0f, k);
        }
        const float faceOut = std::atan2(rx, 0.0f);
        hLocal = AngleLerp(0.0f, faceOut, Smooth(0.1f, 0.55f, t));
        b.doorRate = 3.0f;
        b.doorTarget = t < 0.95f ? kDoorOpen : 0.0f;
        if (t >= 0.95f) b.doorRate = 1.7f;
        out->action = 6;
        out->clipT = t < 0.25f ? 0.0f : (std::min)(0.7f, (t - 0.25f) * 1.27f);
        const float h = HeadingOfLocal(c, std::sin(hLocal), std::cos(hLocal));
        const int doorHand = gta2::Dot(rightOf(h), outward) >= 0.0f ? 1 : 0;   // the hand on the door's side
        if (t < 0.02f) b.doorHand = doorHand;
        const int farHand = 1 - b.doorHand;
        {
            // Pushing it open by the inside handle while it is near, then (standing) a hand
            // on its top edge.
            // The push lets go as the door swings away (past a third open); standing,
            // the hand takes the door's top rear corner.
            const gta2::Vec3 inside = DoorPoint(c, s, open, 0.80f, hy * 0.95f, HandInside(c));
            const gta2::Vec3 top = DoorPoint(c, s, open, 0.95f, (std::min)(c.roof * 0.80f, 0.36f), 0.0f);
            const float push = 1.0f - Smooth(0.2f, 0.4f, open);
            const float hold = 0.0f;   // standing, the hand lets the door be (holding its corner yanked him back)
            const gta2::Vec3 target = hold > push ? top : inside;
            const float w = t < 0.45f ? push : hold;
            SetLimb(b, b.doorHand, target, insidePole(h), w);
        }
        {
            // Pulling himself up by the door frame's rear pillar, at chest height while he is
            // still seated (shoulder 0.34 less the sink): higher read as a wave (ent_v10).
            const float gripY = (std::min)(RoofGripY(c), 0.29f - 0.5f * sink);
            const gta2::Vec3 roofEdge = CarPoint(c, s, hw - 0.02f, gripY, seatZ - 0.04f);
            const float w = Smooth(0.2f, 0.35f, t) * (1.0f - Smooth(0.55f, 0.75f, t));
            SetLimb(b, farHand, roofEdge, elbowPole(farHand, h), w);
        }
        {
            const int doorFoot = gta2::Dot(rightOf(h), outward) >= 0.0f ? 3 : 2;
            const int otherFoot = doorFoot == 3 ? 2 : 3;
            const gta2::Vec3 kp = kneePole(h);
            const gta2::Vec3 wellDoor = CarPoint(c, s, WellDoorU(c), FloorY(c), seatZ + kFootwell);
            const gta2::Vec3 wellFar = CarPoint(c, s, WellFarU(c), FloorY(c), seatZ + kFootwell);
            // Where the feet end: either side of where he will stand, across his outward heading.
            const float hOut = HeadingOfLocal(c, rx, 0.0f);
            const gta2::Vec3 stand = CarPoint(c, s, endU, 0.0f, endZ);
            const gta2::Vec3 r = rightOf(hOut);
            const gta2::Vec3 landDoor = stand + r * (doorFoot == 3 ? 0.035f : -0.035f) + outward * 0.02f;
            const gta2::Vec3 landFar = stand + r * (otherFoot == 3 ? 0.035f : -0.035f);
            const float k1 = Clamp01((t - 0.1f) / 0.3f), k2 = Clamp01((t - 0.42f) / 0.28f);
            SetLimb(b, doorFoot, Arc(wellDoor, landDoor, k1, 0.1f), kp, 1.0f - Smooth(0.72f, 0.86f, t));
            SetLimb(b, otherFoot, Arc(wellFar, landFar, k2, 0.1f), kp, 1.0f - Smooth(0.72f, 0.86f, t));
        }
        if (t > 0.86f && (in.state != 4 || t > 1.3f)) {
            // Free: the renderer's figure from here; the door hand then swings the door
            // shut behind him (kShut) while the legs are his own again.
            b.mode = kShut; b.shutW = 0.0f; b.st = 0.0f; b.shutOff = 1.0f; b.doorOwn = true; b.doorTarget = kDoorOpen; b.doorRate = 3.0f;
            // Free: the renderer's own figure from here, at the game's position.
            out->x = in.gameX; out->z = in.gameZ; out->sink = 0.0f; out->heading = h; out->action = 0;
            out->vx = out->vz = 0.0f;
            b.out = *out;
            b.px = in.drawnX; b.pz = in.drawnZ; b.havePrev = true;
            for (bool& on : b.limbOn) on = false;
            return false;
        }
    }

    // Reach assist: last frame's unreached part of the hands' targets (BoardingReportResidual)
    // moves the body toward them, at most 6 cm, eased; it lets go as the hands do.
    {
        const float gain = 0.35f;
        b.ax += b.rx * gain; b.az += b.rz * gain;
        const bool holding = (b.limbOn[0] && b.limbW[0] > 0.3f) || (b.limbOn[1] && b.limbW[1] > 0.3f);
        b.ax *= holding ? 0.92f : 0.8f; b.az *= holding ? 0.92f : 0.8f;
        const float a = std::sqrt(b.ax * b.ax + b.az * b.az);
        if (a > 0.06f) { b.ax *= 0.06f / a; b.az *= 0.06f / a; }
        b.rx = b.rz = 0.0f;
    }
    if (usePlanPos) {
        gta2::Vec3 p = CarPoint(c, s, u, 0.0f, z);
        // Tether: a hand holding something keeps the body within an arm of it (the shoulder
        // 0.34 above the feet less the sink, 0.043 to the side; the arm 0.124 to the wrist,
        // measured on the avatars' skeleton): he stays at the sill until the door comes in.
        const float shoulderY = 0.34f - sink;
        const gta2::Vec3 p0 = p;
        for (int limb = 0; limb < 2; ++limb) {
            if (!b.limbOn[limb] || b.limbW[limb] < 0.3f) continue;
            const gta2::Vec3& tg = b.limbT[limb];
            const float dy = shoulderY - (tg.y - in.groundY);
            const float reach = 0.035f + std::sqrt((std::max)(0.0f, 0.118f * 0.118f - dy * dy));
            const float ex = tg.x - p.x, ez = tg.z - p.z, d = std::sqrt(ex * ex + ez * ez);
            if (d > reach && d > 1e-4f) {
                const float pull = (d - reach) * Smooth(0.3f, 0.8f, b.limbW[limb]);
                p.x += ex / d * pull; p.z += ez / d * pull;
            }
        }
        b.tox += (p.x - p0.x - b.tox) * (std::min)(1.0f, dt / 0.12f);
        b.toz += (p.z - p0.z - b.toz) * (std::min)(1.0f, dt / 0.12f);
        out->x = p0.x + b.tox + b.ax; out->z = p0.z + b.toz + b.az;
        if (b.mode == kClimb && t > 1.0f) {
            // In his seat: however far a hand reaches, the body stays inside the panel - or,
            // while the door is open, leaning out of the doorway toward it at most.
            float lx, ly, lz;
            ToLocal(c, out->x, in.groundY, out->z, &lx, &ly, &lz);
            const float seated = 0.62f * hw + 0.14f * hw * Clamp01(open / 0.3f);
            const float lim = Lerp(hw + 0.2f, seated, Smooth(1.0f, 1.3f, t));
            if (lx * sf > lim) {
                const gta2::Vec3 q = ToWorld(c, lim * sf, ly, lz);
                out->x = q.x; out->z = q.z;
            }
        }
    }
    if (b.haveOut) {
        out->vx = (out->x - b.lastOutX) / dt; out->vz = (out->z - b.lastOutZ) / dt;
    }
    b.lastOutX = out->x; b.lastOutZ = out->z; b.haveOut = true;
    out->sink = sink;
    out->heading = HeadingOfLocal(c, std::sin(hLocal), std::cos(hLocal));
    b.out = *out;
    b.px = out->x; b.pz = out->z; b.havePrev = true;
    if (g_log && (in.own || true)) {
        Log("board: f=%u ped=%04x mode=%d t=%.2f side=%d u=%.3f z=%.3f sink=%.3f hl=%.2f door=%.2f->%.0f clip=%d@%.2f "
            "L=%d%.2f R=%d%.2f LF=%d%.2f RF=%d%.2f car=%.2f,%.2f hw=%.3f zf=%.3f zr=%.3f roof=%.3f ghost=%d pos=%.3f,%.3f hd=%.2f assist=%.3f",
            in.now, static_cast<unsigned>((in.ped >> 2) & 0xFFFF), b.mode, t, s, u, z, sink, hLocal, open, b.doorTarget,
            out->action, out->clipT, b.limbOn[0], b.limbW[0], b.limbOn[1], b.limbW[1], b.limbOn[2], b.limbW[2], b.limbOn[3],
            b.limbW[3], c.m.m[3][0], c.m.m[3][2], hw, c.zFront, c.zRear, c.roof, in.ghost ? 1 : 0, out->x, out->z, out->heading, std::sqrt(b.ax * b.ax + b.az * b.az));
    }
    return true;
}

bool BoardingLimb(uintptr_t ped, int limb, gta2::Vec3* target, gta2::Vec3* pole, float* weight) {
    if (limb < 0 || limb > 3) return false;
    auto it = g_boards.find(ped);
    if (it == g_boards.end() || !it->second.limbOn[limb]) return false;
    *target = it->second.limbT[limb];
    *pole = it->second.limbPole[limb];
    *weight = it->second.limbW[limb];
    return true;
}

void BoardingReportResidual(uintptr_t ped, int limb, const gta2::Vec3& r) {
    if (limb < 0 || limb > 1) return;   // the hands; feet that fall short stay short
    auto it = g_boards.find(ped);
    if (it == g_boards.end()) return;
    it->second.rx += r.x * it->second.limbW[limb];
    it->second.rz += r.z * it->second.limbW[limb];
}

bool BoardingIsPlayer(uintptr_t ped) {
    auto it = g_boards.find(ped);
    return it != g_boards.end() && it->second.player;
}

bool BoardingWantsGhost(uintptr_t ped, uint32_t now) {
    if (!BoardingEnabled()) return false;
    auto it = g_boards.find(ped);
    if (it == g_boards.end()) return false;
    const Board& b = it->second;
    if (b.mode == kSeated) {
        // seated: for as long as his car is drawn as a body (car_bodies publishes it each frame)
        auto c = g_cars.find(b.car);
        return c != g_cars.end() && now - c->second.frame <= 2;   // (not b.seen: the classic view draws no figures)
    }
    // (from 0.1 s: a jack the game finishes while the plan still holds at the door must not
    // drop the figure for the frames the catch-up needs)
    return b.mode == kClimb && !b.ended && b.t > 0.1f && now - b.seen <= 2;
}

bool BoardingSeat(uintptr_t ped, uintptr_t car, uint32_t now) {
    if (!BoardingEnabled()) return false;
    auto cf = g_cars.find(car);
    if (cf == g_cars.end() || now - cf->second.frame > 1) return false;
    auto it = g_boards.find(ped);
    if (it != g_boards.end()) {
        const Board& b = it->second;
        if (b.mode == kSeated) {
            // the game has him in another car than the boarding guessed (two parked side by side):
            // his seat follows the car he drives
            if (b.car != car) { it->second.car = car; it->second.side = 1; }
            return true;
        }
        if (b.mode != kNone && !b.ended) return false;   // a boarding (or an exit) still plays
    }
    Board b;
    b.mode = kSeated; b.car = car; b.player = true; b.t = 1.0f;   // settled at once
    b.side = 1;   // the driver's door (the player boards by it, aee runs: side=1)
    b.sink0 = DriveSink(cf->second);
    b.seen = now - 1;
    g_boards[ped] = b;
    if (g_log) Log("board: ped=%04x seated in %p without a boarding (f=%u)", static_cast<unsigned>((ped >> 2) & 0xFFFF),
                   reinterpret_cast<const void*>(car), now);
    return true;
}

void BoardingRekey(uintptr_t from, uintptr_t to) {
    auto it = g_boards.find(from);
    if (it == g_boards.end() || from == to) return;
    const Board b = it->second;
    g_boards.erase(it);
    g_boards[to] = b;
}

void BoardingForget(uintptr_t ped) { g_boards.erase(ped); }

bool BoardingBusy(uintptr_t ped) {
    auto it = g_boards.find(ped);
    if (it == g_boards.end()) return false;
    const Board& b = it->second;
    return b.mode != kNone && b.mode != kSeated && !b.ended && g_now - b.seen <= 8;
}

bool BoardingCarSeated(uintptr_t carObject) {
    if (!BoardingEnabled()) return false;
    for (const auto& e : g_boards)
        if (e.second.mode == kSeated && e.second.car == carObject && g_now - e.second.seen <= 3) return true;
    return false;
}

bool BoardingSeatSpot(uintptr_t ped, float* x, float* y, float* z) {
    auto it = g_boards.find(ped);
    if (it == g_boards.end() || it->second.mode != kSeated) return false;
    auto c = g_cars.find(it->second.car);
    if (c == g_cars.end()) return false;
    const gta2::Vec3 p = CarPoint(c->second, it->second.side, SeatU(c->second), 0.0f, SeatZ(c->second));
    *x = p.x; *y = p.y; *z = p.z;
    return true;
}

bool BoardingJackVictim(float gameX, float gameZ, float carX, float carZ, float age, uint32_t now, float* x, float* z, float* sink) {
    if (!BoardingEnabled() || age < 0.0f || age >= 0.9f) return false;
    const Car* c = nullptr;
    float bd = 0.7f * 0.7f;
    for (const auto& e : g_cars) {
        if (now - e.second.frame > 3) continue;
        const float dx = e.second.m.m[3][0] - carX, dz = e.second.m.m[3][2] - carZ;
        if (dx * dx + dz * dz < bd) { bd = dx * dx + dz * dz; c = &e.second; }
    }
    if (!c) return false;
    float lx, ly, lz;
    ToLocal(*c, gameX, c->m.m[3][1], gameZ, &lx, &ly, &lz);
    const int s = c->doorOpen > 0.05f ? c->doorSide : (lx >= 0.0f ? 1 : -1);
    const float hw = c->halfW, Ld = DoorLen(*c);
    // The open door's rear edge (car frame, u outward), as car_bodies swings it.
    float ex, ez;
    Swing(*c, s, (std::max)(c->doorOpen, 0.3f), static_cast<float>(s) * c->halfW, c->zFront - Ld, &ex, &ez);
    const float edgeU = ex * static_cast<float>(s);
    // Waypoints: the seat, the sill at the door frame's rear, then back along the body, between it
    // and the jacker (who stands at the open door's edge, 0.06 out and 0.07 behind its handle), to
    // behind him: 0.14 out of the body, 0.28 behind the door's edge.
    (void)edgeU;
    const float u0 = SeatU(*c), z0 = SeatZ(*c);
    const float u1 = hw + 0.03f, z1 = (std::min)(z0, c->zRear + 0.04f);
    const float u2 = hw + 0.14f, z2 = (std::min)(c->zRear - 0.18f, ez - 0.28f);
    float u, zz, sk;
    if (age < 0.25f) {
        const float k = Smooth(0.0f, 0.25f, age);
        u = Lerp(u0, u1, k); zz = Lerp(z0, z1, k); sk = Lerp(SitSink(*c), 0.04f, k);
    } else {
        const float k = Smooth(0.25f, 0.55f, age);
        u = Lerp(u1, u2, k); zz = Lerp(z1, z2, Smooth(0.25f, 0.45f, age)); sk = Lerp(0.04f, 0.0f, k);
    }
    const gta2::Vec3 p = CarPoint(*c, s, u, 0.0f, zz);
    const float g = Smooth(0.55f, 0.9f, age);
    *x = Lerp(p.x, gameX, g); *z = Lerp(p.z, gameZ, g); *sink = sk * (1.0f - g);
    if (g_log) Log("board: jacked driver age=%.2f side=%d u=%.3f z=%.3f edge=%.3f,%.3f open=%.2f pos=%.3f,%.3f game=%.3f,%.3f",
                   age, s, u, zz, edgeU, ez, c->doorOpen, *x, *z, gameX, gameZ);
    return true;
}

void BoardingEndFrame(uint32_t now) {
    for (auto it = g_boards.begin(); it != g_boards.end();) {
        Board& b = it->second;
        bool stale = now - b.seen > 60;
        if (b.mode == kSeated) {   // seated: for as long as his car is drawn (not after a spell in the classic view)
            auto c = g_cars.find(b.car);
            stale = c == g_cars.end() || now - c->second.frame > 6;
            if (stale && g_log) Log("board: ped=%04x seat let go: car %p %s", static_cast<unsigned>((it->first >> 2) & 0xFFFF),
                                    reinterpret_cast<const void*>(b.car), c == g_cars.end() ? "gone" : "not drawn");
        }
        if (stale || (b.mode == kNone && now - b.seen > 2)) { it = g_boards.erase(it); continue; }
        if (b.ended && !(b.doorOwn && b.doorTarget > 0.5f)) {
            // A finished exit keeps shutting its door for a moment, then is forgotten.
            if (now - b.seen > 30) { it = g_boards.erase(it); continue; }
        }
        ++it;
    }
}

}  // namespace gta2dx9
