// See car_bodies.h.
#include "mem_stats.h"
#include "thread_watch.h"
#include "car_bodies.h"

#include "live_geometry.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <initializer_list>
#include <map>
#include <mutex>
#include <set>
#include <unordered_map>
#include <tuple>

#include "cab_interior.h"
#include "cockpit_mode.h"
#include "car_glass.h"   // VEHICLE-GLASS
#include "boarding.h"
#include "compat.h"
#include "log.h"
#include "model_store.h"
#include "identity.h"   // IDENTITY-SYSTEM
#include "view_modes.h"
#include "world_view.h"   // SeatMoveEye (FIX-SEAT-ENTRY-2)
#include "remix_api.h"
#include "synthetic_lights.h"
#include "texture_store.h"
#include "time_of_day.h"
#include "vehicle_fx.h"
#include "explosion_fx.h"
#include "../../src/sky.h"
#include "../../src/post_fx.h"   // VisualsConfig (feel29 car_shadow_blend)
#include "../../src/weather_fx.h"   // WeatherAdjustSky (FIX-CAR-IDENTITY-6 paint sky cast)

namespace gta2dx9 {
bool FigureTimeOfDayLight(float out[3]);   // live_geometry.cpp (ptm14): the figures' hour light, 1 by day
namespace {

constexpr float kPi = 3.14159265358979f;
constexpr int kStations = 26;        // cross-sections along the length
constexpr int kAtlasScale = 4;       // the sprite is scaled up this much for the roof
constexpr int kBandRows = 32;        // the side strip under the sprite in the atlas
constexpr int kBlockRows = 16;       // the caps, rubber and hub blocks under that
constexpr int kWheelSegments = 14;
constexpr size_t kCacheMax = 96;

std::map<int, gta2::CarInfo> g_info;
int g_built = 0, g_drawn = 0;
bool g_wreckTest = false;   // [devtools] wreck_models=1: every car drawn as a wreck, to check the models
int g_forceModel = -1;      // [devtools] force_car_model=N: every traffic car drawn as model N (re-read once a second)
int g_cabInterior = 1;     // [devtools] cab_interior=0: QB-5's plain dashboard instead of the QB-31 cab
int g_driverGlass = 1;     // [devtools] driver_glass=0: FIX-SEATED's see-through window band off
int g_tyreContactDev = 1;  // [devtools] tyre_shadows=0: no tyre contact patches (A/B)
int g_glassSeat = 1;      // FIX-DRIVER-GEOM [devtools] glass_seat=0: a generated body's driver on the sprite's seat (pfl74 A/B)
int g_bandInterior = 1;    // [devtools] band_interior=0: no dark cabin behind that band (feel20 A/B)
int g_forceOwnModel = -1;   // [devtools] force_own_car_model=N: the player's car drawn as model N (QB-5 seat checks)
int g_forceCarPaint[3] = {-1, -1, -1};   // [devtools] force_car_paint=R,G,B: every non-livery car's live paint (QA of dark paint)
int g_forceCarPaintBright[3] = {-1, -1, -1};   // ...=R,G,B,r,g,b: and its brighter-half paint (the dark floor's test)
float g_paintLumFloor = 77.0f;   // [renderer] car_paint_floor_percent (default 30 of white; 0 off)
// FIX-CAR-IDENTITY-4 (feel25): the paint's sun sheen. At 26 the lobe was broad enough to lay ~+20 of white over
// a whole lid seen from the classic camera (half-angle ~19 deg: 0.33 x cos^26 = 0.08), a pastel wash on every
// saturated paint; at 50 it is a highlight. [devtools] paint_spec_power for A/B.
float g_paintSpecPower = 50.0f;
int g_paintRefDev = 1;        // [devtools] paint_ref (FIX-CAR-IDENTITY-4 A/B)
// FIX-CAR-IDENTITY-5: the sprite's paint from its clean style art in the drawn palette (1, default) or from the drawn
// record's pixels as before (GTA2DX9_CLEAN_PAINT=0, for A/B runs).
const bool g_cleanPaint = [] { char v[8] = {}; return !(GetEnvironmentVariableA("GTA2DX9_CLEAN_PAINT", v, sizeof v) && v[0] == '0'); }();
bool g_paintSkyCast = true;   // [devtools] paint_sky_cast: the tint takes out the post's hemisphere cast (FIX-CAR-IDENTITY-6)
float g_paintGainDev = 1.25f; // [devtools] paint_gain_percent: the paint's gain at the lid light it was measured under
int g_forceDamage = -1;     // [devtools] force_car_damage=N: every car body drawn at damage word N, 0..32000 (re-read once a second)
int g_doorExactCut = 1;    // [devtools] door_exact_cut=0: FIX-SEAT-ENTRY-3's exact door outline off (A/B)
int g_doorInterior = 1;    // [devtools] door_interior=0: no cab interior drawn behind an open door (A/B)
int g_seatedSep = 0;      // [devtools] seated_sep=1: a seated driver pushed out of his car like a ped on foot (the old way, pmt6 A/B)
int g_forceOwnLift = 0;   // [devtools] force_own_lift=N: the driven car drawn N/100 block higher (tri11 probe)
int g_fpSeatLock = 1;     // [devtools] fp_seat_lock=0 / GTA2DX9_FP_SEAT_LOCK=0: FIX-INCAR-1's same-frame body-to-eye lock off (tri11 A/B)
// FIX-FP-ENTRY's learned seat point (the first-person eye in the driven body's posed frame), per driven car.
struct SeatRef { float x = 0.0f, y = 0.0f, z = 0.0f; uintptr_t car = 0; int frames = 0; };
SeatRef g_seatRef;
static int FpSeatLockDefault() {
    static int v = -1;
    if (v < 0) { char b[8] = {}; v = GetEnvironmentVariableA("GTA2DX9_FP_SEAT_LOCK", b, sizeof b) && atoi(b) == 0 ? 0 : 1; }
    return v;
}
int g_fpSeatFreeze = 1;   // [devtools] fp_seat_freeze=0: FIX-SEAT-ENTRY-4's once-learned seat point off (tri11 A/B)
int g_doorTopCut = 1;      // [devtools] door_top_cut=0: FIX-SEAT-ENTRY-4's cut of the shoulder faces across the door's top off (A/B)
int g_forceDoor = 0;        // [devtools] force_car_door=1|-1: every car body drawn with its right|left door open (re-read once a second)
char g_devIni[260] = {};
// FIX-VEHICLES (car-bodies-interpenetrate-in-traffic): each car's drawn footprint (its
// model's bounds after the fit, in the car's frame, placed by the game) is kept for the next
// frame; a car whose footprint overlaps another's is drawn moved apart by its share of the
// overlap (the game's placement and boxes untouched). GTA2DX9_LOG_CAR_OVERLAP=1 logs the
// pairs; [renderer] car_separation=0 turns it off.
struct CarFoot {
    uintptr_t object = 0;
    float cx = 0, cy = 0, cz = 0;   // the car frame's origin, world
    float ground = 0;               // VEHICLE-GLASS: the body's lowest point, world y
    float rx = 1, rz = 0;        // its x (across) axis, world xz, unit
    float fx = 0, fz = 1;        // its z (nose) axis, world xz, unit
    float x0 = 0, x1 = 0, z0 = 0, z1 = 0;   // the drawn footprint in the car frame
    float boxHalfL = 0, boxHalfW = 0;       // the game's box (the sprite's footprint)
    bool pinned = false;         // never moved (the player's car seen from the seat)
    bool linked = false;         // a train carriage, a tractor or its trailer: they overlap at the coupling by design
    // VEHICLE-ART-5: where each tyre meets the road (world x, z) and its radius, for the contact shadow.
    int wheels = 0;
    float wx[6] = {}, wz[6] = {}, wr[6] = {};
};
std::vector<CarFoot> g_feetPrev, g_feetCur;
uint32_t g_feetFrame = 0;
struct CarPush { float x = 0, z = 0; uint32_t frame = 0; };
std::unordered_map<uintptr_t, CarPush> g_push;
std::set<std::pair<int, int>> g_fitLogged;   // (model, sprite) whose overhang is logged
int g_logOverlap = -1;
int g_separate = 1;
int g_logNoses = -1;        // GTA2DX9_LOG_CAR_NOSES=1: a line per drawn car every 15 frames, for tools/check_car_noses.py
// Where the cars stage's time went in the last call: measuring artwork, building
// bodies, drawing models, drawing sprite-built bodies (ms), and the counts.
double g_carStats[8] = {};
LARGE_INTEGER g_carFreq = {};
double CarNowMs() {
    if (!g_carFreq.QuadPart) QueryPerformanceFrequency(&g_carFreq);
    LARGE_INTEGER t; QueryPerformanceCounter(&t);
    return 1000.0 * static_cast<double>(t.QuadPart) / static_cast<double>(g_carFreq.QuadPart);
}
// FIX-PERF-3: the model-drawn cars' time by part (ms, this call), for the hitch detail's "car parts" line:
// which first-use derivation (glass, cab, hood, bonnet, wheels, doors, buffers) a slow cars stage paid for.
enum CarPart { kPartIdentity, kPartCabin, kPartWear, kPartHood, kPartWheels, kPartFeel, kPartDoor, kPartGlass,
               kPartHull, kPartSeatBonnet, kPartBonnetDraw, kPartCab, kPartGlassInside, kPartLamps, kPartCount };
const char* const kCarPartNames[kPartCount] = {"identity", "cabin", "wear", "hood", "wheels", "feel", "door", "glass",
                                               "hull draws", "seat bonnet", "bonnet draw", "cab interior", "glass inside", "lamps"};
double g_carParts[kPartCount] = {};
struct CarPartTimer {
    int part; double t0;
    explicit CarPartTimer(int p) : part(p), t0(CarNowMs()) {}
    ~CarPartTimer() { g_carParts[part] += CarNowMs() - t0; }
};

struct Rgb { float r, g, b; };

inline uint32_t Pack(Rgb c) {
    auto q = [](float v) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(255.0f, v + 0.5f))); };
    return 0xFF000000u | (q(c.r) << 16) | (q(c.g) << 8) | q(c.b);
}
inline Rgb Unpack(uint32_t c) {
    return {static_cast<float>((c >> 16) & 0xFF), static_cast<float>((c >> 8) & 0xFF), static_cast<float>(c & 0xFF)};
}
inline Rgb Scale(Rgb c, float k) { return {c.r * k, c.g * k, c.b * k}; }
inline Rgb Mix(Rgb a, Rgb b, float t) { return {a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t}; }
inline float Luma(Rgb c) { return 0.299f * c.r + 0.587f * c.g + 0.114f * c.b; }
inline float Smooth(float t) { t = (std::max)(0.0f, (std::min)(1.0f, t)); return t * t * (3.0f - 2.0f * t); }

// Scale2x (EPX): doubles a picture, rounding the staircases of the pixel art
// without blurring it. Whole ARGB values, so the cutout keeps its shape.
std::vector<uint32_t> Scale2x(const std::vector<uint32_t>& src, int w, int h) {
    std::vector<uint32_t> out(static_cast<size_t>(w) * h * 4);
    auto at = [&](int x, int y) {
        x = (std::max)(0, (std::min)(w - 1, x));
        y = (std::max)(0, (std::min)(h - 1, y));
        return src[static_cast<size_t>(y) * w + x];
    };
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const uint32_t p = at(x, y), a = at(x, y - 1), b = at(x + 1, y), c = at(x - 1, y), d = at(x, y + 1);
            uint32_t e0 = p, e1 = p, e2 = p, e3 = p;
            if (c == a && c != d && a != b) e0 = a;
            if (a == b && a != c && b != d) e1 = b;
            if (d == c && d != b && c != a) e2 = c;
            if (b == d && b != a && d != c) e3 = d;
            uint32_t* row0 = &out[static_cast<size_t>(y * 2) * w * 2 + x * 2];
            uint32_t* row1 = row0 + static_cast<size_t>(w) * 2;
            row0[0] = e0; row0[1] = e1; row1[0] = e2; row1[1] = e3;
        }
    }
    return out;
}

// Transparent texels take the colour of their nearest opaque neighbour, so
// bilinear sampling at the outline never pulls in black.
void ExtendEdges(std::vector<uint32_t>* px, int w, int h, int passes) {
    std::vector<uint32_t> next;
    for (int pass = 0; pass < passes; ++pass) {
        next = *px;
        bool any = false;
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                uint32_t& p = next[static_cast<size_t>(y) * w + x];
                if (p >> 24) continue;
                const int dx[4] = {1, -1, 0, 0}, dy[4] = {0, 0, 1, -1};
                for (int k = 0; k < 4; ++k) {
                    const int nx = x + dx[k], ny = y + dy[k];
                    if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
                    const uint32_t q = (*px)[static_cast<size_t>(ny) * w + nx];
                    if (q >> 24) { p = q; any = true; break; }
                }
            }
        }
        px->swap(next);
        if (!any) break;
    }
}

struct Measure {
    int w = 0, h = 0;             // sprite canvas
    int top = 0, bottom = 0;      // opaque rows: tail .. nose (inclusive)
    std::vector<float> halfW;     // per canvas row, pixels, 0 where empty
    float maxHalfW = 0.0f;
    float cabinRear = 0.0f, cabinFront = 0.0f;   // rows (nose is larger)
    float wheelFront = 0.0f, wheelRear = 0.0f;   // rows
    int doors = 2;
    Rgb paint{128, 128, 128};
    std::vector<Rgb> rowPaint;   // per canvas row
    bool hasInfo = false;
};

struct Built {
    IDirect3DTexture9* atlas = nullptr;
    std::vector<CarBodyVertex> verts;
    std::vector<uint16_t> indices;
    std::vector<CarBodyVertex> wheelVerts;
    std::vector<uint16_t> wheelIndices;
    // Managed buffers of the two meshes, filled once (see model_store.cpp for
    // why not DrawIndexedPrimitiveUP); null when the device gave none.
    IDirect3DVertexBuffer9* vb = nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    IDirect3DVertexBuffer9* wvb = nullptr;
    IDirect3DIndexBuffer9* wib = nullptr;
    bool buffersTried = false;
    // What any hand-made model of this car needs: its paint and its footprint.
    Rgb paint{128, 128, 128};
    bool paintMasked = false;   // paint = the mean of the remap's texels (else MeasureSprite's brighter half)
    int palette = -1;           // FIX-CAR-IDENTITY-5: the palette the measured artwork is drawn in (the remap)
    float bodyLength = 1.0f, bodyWidth = 0.5f;   // tiles
    float scale = 1.0f / 64.0f;                  // tiles per sprite pixel
    bool measured = false;
    Measure measure;
    std::vector<uint32_t> px;
    bool meshBuilt = false;
    float wheelZ[2] = {0.0f, 0.0f};   // front, rear
    float wheelX = 0.0f;              // half track
    float wheelY = 0.0f;              // axle height
    float wheelbase = 0.3f;
    float deckY = 0.0f, roofY = 0.0f;   // the hood line and the roof, blocks
    uint32_t used = 0;
    bool ok = false;
};
void ReleaseBuffers(Built* b) {
    if (b->vb) b->vb->Release();
    if (b->ib) b->ib->Release();
    if (b->wvb) b->wvb->Release();
    if (b->wib) b->wib->Release();
    b->vb = nullptr; b->ib = nullptr; b->wvb = nullptr; b->wib = nullptr;
}

struct Key {
    int sprite;
    IDirect3DTexture9* art;
    bool operator<(const Key& o) const { return sprite != o.sprite ? sprite < o.sprite : art < o.art; }
};
std::map<Key, Built> g_cache;
// ANIM-ENTRY-EXIT: each car object's last measured artwork and the frame it was last drawn
// with. While the game plays a car's door animation its sprite is a new texture every frame;
// since PERF-4 builds car artwork on a worker, those frames' artwork is often not ready (or
// not measurable) on the frame it is first drawn, and the car was skipped: the whole 3D car
// vanished for ~15 frames as someone walked up to it and popped back with the door open (runs
// aee_g2front/g3rear). The body does not change with the door frames: the last good one
// stands in, for up to 3 s. Entries in g_cache live while used (evicted after 300 unused
// frames), and both maps are cleared together on a device release.
// FIX-CAR-IDENTITY (pm33): the last body measured per sprite object, with the sprite and model it was
// measured for: the game re-uses a sprite object for another car within seconds, and the stand-in must
// never lend one car's body and paint to the next (a ped at the new car's door would have kept it).
struct LastBuilt { Built* first = nullptr; uint32_t second = 0; int sprite = -1, model = -1; };
std::map<uintptr_t, LastBuilt> g_lastBuilt;
IDirect3DDevice9* g_device = nullptr;

struct Steer {
    float x = 0, z = 0, yaw = 0, angle = 0;
    uint32_t frame = 0;
};
std::map<uintptr_t, Steer> g_steer;

struct Cabin {
    float deck, roof, windscreen, halfWidth;
    uint32_t frame;
    float length, height;   // the body as drawn: blocks along it and its full height (roof gear included)
    bool flat = false;      // QB-31: a flat front (bus, cab-over): the cab interior's class
};
std::map<uintptr_t, Cabin> g_cabins;

float WrapAngle(float a) {
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

// The texels of the car's artwork as the game has it right now, its repaint
// included: read back from the device texture the sprite pass made.
bool ReadArt(IDirect3DTexture9* art, std::vector<uint32_t>* px, int* w, int* h) {
    D3DSURFACE_DESC desc;
    if (FAILED(art->GetLevelDesc(0, &desc)) || desc.Format != D3DFMT_A8R8G8B8) return false;
    if (desc.Width < 4 || desc.Height < 4 || desc.Width > 256 || desc.Height > 256) return false;
    *w = static_cast<int>(desc.Width);
    *h = static_cast<int>(desc.Height);
    px->assign(static_cast<size_t>(*w) * *h, 0);
    D3DLOCKED_RECT locked;
    if (FAILED(art->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) return false;
    for (int y = 0; y < *h; ++y) {
        memcpy(&(*px)[static_cast<size_t>(y) * *w], static_cast<const uint8_t*>(locked.pBits) + y * locked.Pitch,
               static_cast<size_t>(*w) * 4);
    }
    art->UnlockRect(0);
    return true;
}

// The atlas: the sprite scaled up on top, then the side band, then the blocks.
struct Atlas {
    int w = 0, h = 0;
    std::vector<uint32_t> px;
    int spriteH = 0;   // rows the scaled sprite takes
    void Put(int x, int y, Rgb c) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        px[static_cast<size_t>(y) * w + x] = Pack(c);
    }
};

bool MeasureSprite(const std::vector<uint32_t>& px, int w, int h, int sprite, Measure* m) {
    m->w = w; m->h = h;
    m->halfW.assign(h, 0.0f);
    m->rowPaint.assign(h, Rgb{128, 128, 128});
    int top = -1, bottom = -1;
    const float cx = 0.5f * w;
    std::vector<float> lum;
    for (int y = 0; y < h; ++y) {
        int x0 = -1, x1 = -1;
        for (int x = 0; x < w; ++x) {
            if ((px[static_cast<size_t>(y) * w + x] >> 24) < 128) continue;
            if (x0 < 0) x0 = x;
            x1 = x;
        }
        if (x0 < 0) continue;
        if (top < 0) top = y;
        bottom = y;
        // Half-width about the canvas centre, which is what the game turns the sprite about.
        m->halfW[y] = (std::max)(cx - x0, x1 + 1 - cx);
    }
    if (top < 0 || bottom - top < 6) return false;
    m->top = top; m->bottom = bottom;
    const gta2::CarInfo* info = nullptr;
    const auto found = g_info.find(sprite);
    if (found != g_info.end()) info = &found->second;
    m->hasInfo = info != nullptr;
    // An open door sticks out of the outline: the body is no wider than CARI says.
    float cap = 1e9f;
    if (info && info->width > 4) cap = 0.5f * info->width + 1.0f;
    // Median of five, then the cap.
    std::vector<float> smooth(h, 0.0f);
    for (int y = top; y <= bottom; ++y) {
        float v[5];
        int n = 0;
        for (int k = -2; k <= 2; ++k) {
            const int yy = y + k;
            if (yy < top || yy > bottom) continue;
            v[n++] = m->halfW[yy];
        }
        std::sort(v, v + n);
        smooth[y] = (std::min)(v[n / 2], cap);
    }
    m->halfW = smooth;
    m->maxHalfW = 0.0f;
    for (int y = top; y <= bottom; ++y) m->maxHalfW = (std::max)(m->maxHalfW, m->halfW[y]);
    if (m->maxHalfW < 2.0f) return false;

    const float cy = 0.5f * h;
    const float len = static_cast<float>(bottom - top + 1);
    if (info) {
        m->cabinFront = cy + info->frontWindow;
        m->cabinRear = cy + info->rearWindow;
        m->wheelFront = cy + info->frontWheel;
        m->wheelRear = cy + info->rearWheel;
        m->doors = info->doors;
    } else {
        m->cabinFront = top + 0.72f * len;
        m->cabinRear = top + 0.30f * len;
        m->wheelFront = top + 0.80f * len;
        m->wheelRear = top + 0.20f * len;
    }
    m->cabinFront = (std::max)(static_cast<float>(top) + 2.0f, (std::min)(static_cast<float>(bottom) - 1.0f, m->cabinFront));
    m->cabinRear = (std::max)(static_cast<float>(top) + 1.0f, (std::min)(m->cabinFront - 2.0f, m->cabinRear));
    m->wheelFront = (std::max)(static_cast<float>(top) + 3.0f, (std::min)(static_cast<float>(bottom) - 3.0f, m->wheelFront));
    m->wheelRear = (std::max)(static_cast<float>(top) + 3.0f, (std::min)(m->wheelFront - 4.0f, m->wheelRear));

    // Paint: per row, the mean of the brighter half of the opaque texels (the
    // lit metal, not the outline or the glass); the car's paint overall from the
    // hood and trunk rows, which have no glass in them.
    Rgb sum{0, 0, 0};
    float count = 0.0f;
    for (int y = top; y <= bottom; ++y) {
        std::vector<std::pair<float, Rgb>> row;
        for (int x = 0; x < w; ++x) {
            const uint32_t c = px[static_cast<size_t>(y) * w + x];
            if ((c >> 24) < 128) continue;
            const Rgb rgb = Unpack(c);
            row.push_back({Luma(rgb), rgb});
        }
        if (row.empty()) continue;
        std::sort(row.begin(), row.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        Rgb s{0, 0, 0};
        int n = 0;
        for (size_t i = row.size() / 2; i < row.size(); ++i) { s.r += row[i].second.r; s.g += row[i].second.g; s.b += row[i].second.b; ++n; }
        if (n) m->rowPaint[y] = Scale(s, 1.0f / n);
        const bool deck = y > m->cabinFront + 1 || y < m->cabinRear - 1;
        if (deck && n) { sum.r += m->rowPaint[y].r; sum.g += m->rowPaint[y].g; sum.b += m->rowPaint[y].b; count += 1.0f; }
    }
    if (count > 0.0f) m->paint = Scale(sum, 1.0f / count);
    else {
        Rgb s{0, 0, 0}; int n = 0;
        for (int y = top; y <= bottom; ++y) { s.r += m->rowPaint[y].r; s.g += m->rowPaint[y].g; s.b += m->rowPaint[y].b; ++n; }
        if (n) m->paint = Scale(s, 1.0f / n);
    }
    // Smooth the row paint a little so the side does not stripe with the artwork's rows.
    std::vector<Rgb> rp = m->rowPaint;
    for (int y = top; y <= bottom; ++y) {
        Rgb s{0, 0, 0}; int n = 0;
        for (int k = -2; k <= 2; ++k) {
            const int yy = y + k;
            if (yy < top || yy > bottom) continue;
            s.r += m->rowPaint[yy].r; s.g += m->rowPaint[yy].g; s.b += m->rowPaint[yy].b; ++n;
        }
        rp[y] = Scale(s, 1.0f / n);
    }
    m->rowPaint = rp;
    return true;
}

// The texture: the sprite scaled up and edge-extended on top; under it the side
// band (glass over paint, by column along the length) and the small blocks for
// the nose, the tail, the rubber and the hubs.
IDirect3DTexture9* MakeAtlas(IDirect3DDevice9* device, const std::vector<uint32_t>& px, const Measure& m, Atlas* out) {
    const int sw = m.w * kAtlasScale, sh = m.h * kAtlasScale;
    out->w = (std::max)(sw, 192);
    out->h = sh + kBandRows + kBlockRows;
    out->spriteH = sh;
    out->px.assign(static_cast<size_t>(out->w) * out->h, 0xFF000000u);
    // The sprite, 4x.
    std::vector<uint32_t> big = Scale2x(Scale2x(px, m.w, m.h), m.w * 2, m.h * 2);
    ExtendEdges(&big, sw, sh, 12);
    // A light blur, so the enlarged pixels read as paint rather than tiles.
    {
        std::vector<uint32_t> soft(big.size());
        for (int y = 0; y < sh; ++y) {
            for (int x = 0; x < sw; ++x) {
                float r = 0, g = 0, b = 0, wsum = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int xx = (std::max)(0, (std::min)(sw - 1, x + dx)), yy = (std::max)(0, (std::min)(sh - 1, y + dy));
                        const uint32_t c = big[static_cast<size_t>(yy) * sw + xx];
                        if (!(c >> 24)) continue;
                        const float wgt = (dx == 0 && dy == 0) ? 2.0f : 1.0f;
                        const Rgb k = Unpack(c);
                        r += k.r * wgt; g += k.g * wgt; b += k.b * wgt; wsum += wgt;
                    }
                }
                const uint32_t c = big[static_cast<size_t>(y) * sw + x];
                soft[static_cast<size_t>(y) * sw + x] = (wsum > 0.0f && (c >> 24)) ? Pack(Rgb{r / wsum, g / wsum, b / wsum}) : c;
            }
        }
        big.swap(soft);
    }
    for (int y = 0; y < sh; ++y) {
        for (int x = 0; x < sw; ++x) {
            const uint32_t c = big[static_cast<size_t>(y) * sw + x];
            out->px[static_cast<size_t>(y) * out->w + x] = c | 0xFF000000u;
        }
    }
    // The band: column X runs tail -> nose along the car; rows 0..15 are the
    // glass zone, rows 16..31 the lower side down to the sill.
    const float len = static_cast<float>(m.bottom - m.top + 1);
    const float cabinLen = m.cabinFront - m.cabinRear;
    const Rgb glassTop{92, 112, 130}, glassBottom{26, 32, 40};
    for (int X = 0; X < out->w; ++X) {
        const float f = (X + 0.5f) / out->w;
        const float row = m.top + f * len;
        const int ry = (std::max)(m.top, (std::min)(m.bottom, static_cast<int>(row)));
        Rgb paint = Mix(m.rowPaint[ry], m.paint, 0.35f);
        const bool cabin = row >= m.cabinRear && row <= m.cabinFront;
        // Pillars: at both ends of the glass, and in the middle of a four-door.
        const float pillar = (std::max)(1.2f, 0.06f * cabinLen);
        bool isPillar = cabin && (row - m.cabinRear < pillar || m.cabinFront - row < pillar);
        if (cabin && m.doors >= 4 && std::fabs(row - 0.5f * (m.cabinRear + m.cabinFront)) < 0.5f * pillar) isPillar = true;
        for (int r = 0; r < kBandRows; ++r) {
            Rgb c;
            if (r < 16) {
                if (cabin && !isPillar) {
                    const float t = r / 15.0f;
                    c = Mix(glassTop, glassBottom, t);
                    // A pale reflection band near the top, as glass has.
                    if (r >= 2 && r <= 5) c = Mix(c, Rgb{200, 215, 230}, 0.25f);
                } else {
                    c = Scale(paint, isPillar ? 0.55f : 1.0f);
                }
            } else if (r < 20) {
                c = Scale(paint, 1.10f);   // the shoulder catches the sky
            } else if (r < 28) {
                c = paint;
            } else {
                c = Scale(paint, 0.55f);   // the sill, in shadow
            }
            out->Put(X, sh + r, c);
        }
    }
    // The blocks: nose [0,64), tail [64,128), rubber [128,144), hub [144,160).
    const int by = sh + kBandRows;
    for (int y = 0; y < kBlockRows; ++y) {
        for (int x = 0; x < 64; ++x) {
            Rgb c = Scale(m.paint, y < 3 ? 1.05f : 1.0f);
            const bool side = x < 6 || x >= 58;
            if (y >= 7 && y <= 11 && ((x >= 7 && x <= 17) || (x >= 46 && x <= 56))) c = Rgb{255, 248, 215};   // headlamps
            else if (y >= 9 && y <= 12 && x >= 22 && x <= 41) c = Scale(m.paint, 0.28f);               // grille
            else if (y >= 13) c = Scale(m.paint, side ? 0.6f : 0.5f);                                    // bumper
            out->Put(x, by + y, c);
            Rgb t = Scale(m.paint, y < 3 ? 1.05f : 1.0f);
            if (y >= 7 && y <= 11 && ((x >= 5 && x <= 16) || (x >= 47 && x <= 58))) t = Rgb{205, 28, 24};   // tail lamps
            else if (y >= 8 && y <= 12 && x >= 26 && x <= 37) t = Rgb{225, 225, 212};                      // the plate
            else if (y >= 13) t = Scale(m.paint, 0.5f);
            out->Put(64 + x, by + y, t);
        }
        for (int x = 0; x < 16; ++x) {
            const float n = 0.9f + 0.1f * static_cast<float>((x * 7 + y * 13) % 5) / 4.0f;
            out->Put(128 + x, by + y, Scale(Rgb{30, 30, 32}, n));
            const float dx = x - 7.5f, dy = y - 7.5f;
            const float d = std::sqrt(dx * dx + dy * dy);
            Rgb hub = d > 7.2f ? Rgb{24, 24, 26} : (d > 5.0f ? Rgb{150, 152, 158} : (d > 1.5f ? Rgb{118, 120, 126} : Rgb{60, 60, 64}));
            out->Put(144 + x, by + y, hub);
        }
    }
    IDirect3DTexture9* tex = nullptr;
    if (FAILED(device->CreateTexture(out->w, out->h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    D3DLOCKED_RECT locked;
    if (FAILED(tex->LockRect(0, &locked, nullptr, 0))) { tex->Release(); return nullptr; }
    for (int y = 0; y < out->h; ++y) {
        memcpy(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch, &out->px[static_cast<size_t>(y) * out->w],
               static_cast<size_t>(out->w) * 4);
    }
    tex->UnlockRect(0);
    return tex;
}

// Builds the body and the wheel in car space: x across (right positive), y up,
// z along the length toward the nose, in tiles; the origin under the sprite's
// centre on the ground. `scale` is tiles per sprite pixel.
void BuildMesh(const Measure& m, const Atlas& atlas, float scale, Built* b) {
    const float W = 2.0f * m.maxHalfW * scale;                          // the body's width in tiles
    const float cy = 0.5f * m.h;
    const float zTail = (m.top - cy) * scale, zNose = (m.bottom + 1 - cy) * scale;
    const float L = zNose - zTail;
    const float zCabinRear = (m.cabinRear - cy) * scale, zCabinFront = (m.cabinFront - cy) * scale;
    const float cabinFrac = (zCabinFront - zCabinRear) / L;
    // Proportions. A sedan's roof is four fifths of its width up; a van or bus
    // is taller, with a nearly upright windscreen.
    const float tall = Smooth((cabinFrac - 0.58f) / 0.25f);
    const float hSill = 0.14f * W, hBelt = 0.38f * W;
    const float hTail = 0.42f * W, hTrunk = 0.49f * W, hHood = 0.51f * W, hNose = 0.40f * W;
    const float hRoof = W * (0.76f + 0.50f * tall);
    const float rakeFront = L * (0.15f - 0.10f * tall), rakeRear = L * (0.11f - 0.07f * tall);
    // The roof texture: the sprite's u runs across the canvas, v down it (tail to nose).
    const float atlasW = static_cast<float>(atlas.w), atlasH = static_cast<float>(atlas.h);
    const float spriteU = static_cast<float>(m.w * kAtlasScale) / atlasW;   // the sprite's share of the atlas width
    const float spriteV = static_cast<float>(atlas.spriteH) / atlasH;
    auto topUv = [&](float x, float z, float* u, float* v) {
        *u = (0.5f + x / (m.w * scale)) * spriteU;
        *v = ((z / scale + cy) / m.h) * spriteV;
    };
    const float bandV0 = static_cast<float>(atlas.spriteH) / atlasH;
    const float bandV1 = static_cast<float>(atlas.spriteH + kBandRows) / atlasH;
    auto bandUv = [&](float z, float heightFrac /* 0 sill .. 1 roof */, float* u, float* v) {
        *u = (z - zTail) / L;
        // Rows 16..31 (the lower side) are heights 0..0.5 of the way up; rows 0..15 the glass, 0.5..1.
        *v = bandV0 + (bandV1 - bandV0) * (1.0f - heightFrac) ;
    };
    const float blockV0 = static_cast<float>(atlas.spriteH + kBandRows) / atlasH;
    const float blockV1 = static_cast<float>(atlas.spriteH + kBandRows + kBlockRows) / atlasH;

    auto halfWidthAt = [&](float z) {
        const float row = z / scale + cy;
        const float fy = row - 0.5f;
        int y0 = static_cast<int>(std::floor(fy));
        const float t = fy - y0;
        y0 = (std::max)(m.top, (std::min)(m.bottom, y0));
        const int y1 = (std::max)(m.top, (std::min)(m.bottom, y0 + 1));
        float hw = m.halfW[y0] * (1 - t) + m.halfW[y1] * t;
        return (std::max)(hw * scale, 0.08f * W);
    };
    auto deckHeight = [&](float z) {
        if (z <= zCabinRear) {
            const float t = (z - zTail) / (std::max)(zCabinRear - zTail, 1e-3f);
            return hTail + (hTrunk - hTail) * Smooth(t);
        }
        if (z >= zCabinFront) {
            const float t = (z - zCabinFront) / (std::max)(zNose - zCabinFront, 1e-3f);
            return hHood + (hNose - hHood) * t * t;
        }
        return hHood + (hTrunk - hHood) * (zCabinFront - z) / (std::max)(zCabinFront - zCabinRear, 1e-3f);
    };
    auto roofHeight = [&](float z, float deck) {
        if (z < zCabinRear || z > zCabinFront) return deck;
        float t = 1.0f;
        if (z > zCabinFront - rakeFront) t = (std::min)(t, (zCabinFront - z) / rakeFront);
        if (z < zCabinRear + rakeRear) t = (std::min)(t, (z - zCabinRear) / rakeRear);
        return deck + (hRoof - deck) * Smooth(t);
    };

    // Four strips a side, each its own vertices so the creases between them stay.
    struct Pt { float x, y; };
    enum Family { kSide, kDeck, kGlass, kRoof, kFamilies };
    const int counts[kFamilies] = {5, 2, 2, 3};
    b->verts.clear();
    b->indices.clear();
    // verts laid out: [side][family][station][k]
    int base[2][kFamilies];
    for (int side = 0; side < 2; ++side) {
        const float sx = side == 0 ? -1.0f : 1.0f;
        for (int fam = 0; fam < kFamilies; ++fam) {
            base[side][fam] = static_cast<int>(b->verts.size());
            for (int i = 0; i <= kStations; ++i) {
                const float z = zTail + (zNose - zTail) * i / kStations;
                const float hw = halfWidthAt(z);
                const float deck = deckHeight(z), roof = roofHeight(z, deck);
                const bool cabin = z >= zCabinRear && z <= zCabinFront;
                Pt pts[5];
                int n = counts[fam];
                switch (fam) {
                    case kSide:
                        pts[0] = {hw * 0.95f, hSill};
                        pts[1] = {hw * 1.00f, hSill + 0.45f * (hBelt - hSill)};
                        pts[2] = {hw * 1.00f, hBelt};
                        pts[3] = {hw * 0.985f, deck - 0.05f * W};
                        pts[4] = {hw * 0.94f, deck};
                        break;
                    case kDeck:
                        pts[0] = {hw * 0.94f, deck};
                        pts[1] = {hw * 0.86f, deck + 0.012f * W};
                        break;
                    case kGlass:
                        pts[0] = {hw * 0.86f, deck + 0.012f * W};
                        pts[1] = {hw * (cabin ? 0.78f : 0.84f), (std::max)(roof - 0.015f * W, deck + 0.012f * W)};
                        break;
                    default:
                        pts[0] = {hw * (cabin ? 0.78f : 0.84f), (std::max)(roof - 0.015f * W, deck + 0.012f * W)};
                        pts[1] = {hw * (cabin ? 0.66f : 0.60f), roof + (cabin ? 0.0f : 0.012f * W)};
                        pts[2] = {0.0f, roof + 0.014f * W};
                        break;
                }
                for (int k = 0; k < n; ++k) {
                    CarBodyVertex v = {};
                    v.x = sx * pts[k].x;
                    v.y = pts[k].y;
                    v.z = z;
                    if (fam == kSide) {
                        bandUv(z, 0.5f * static_cast<float>(k) / (n - 1), &v.u, &v.v);
                    } else if (fam == kGlass) {
                        bandUv(z, k == 0 ? 0.52f : 0.98f, &v.u, &v.v);
                    } else {
                        topUv(v.x, z, &v.u, &v.v);
                    }
                    b->verts.push_back(v);
                }
            }
        }
    }
    auto quad = [&](int a, int bq, int c, int d) {
        b->indices.insert(b->indices.end(), {static_cast<uint16_t>(a), static_cast<uint16_t>(bq), static_cast<uint16_t>(c),
                                             static_cast<uint16_t>(a), static_cast<uint16_t>(c), static_cast<uint16_t>(d)});
    };
    for (int side = 0; side < 2; ++side) {
        for (int fam = 0; fam < kFamilies; ++fam) {
            const int n = counts[fam];
            for (int i = 0; i < kStations; ++i) {
                for (int k = 0; k + 1 < n; ++k) {
                    const int p00 = base[side][fam] + i * n + k, p01 = p00 + 1;
                    const int p10 = p00 + n, p11 = p10 + 1;
                    quad(p00, p10, p11, p01);
                }
            }
        }
    }
    // Normals from the faces, averaged per vertex, turned outward.
    std::vector<float> acc(b->verts.size() * 3, 0.0f);
    for (size_t t = 0; t + 2 < b->indices.size(); t += 3) {
        const CarBodyVertex &p = b->verts[b->indices[t]], &q = b->verts[b->indices[t + 1]], &r = b->verts[b->indices[t + 2]];
        const float ax = q.x - p.x, ay = q.y - p.y, az = q.z - p.z;
        const float bx = r.x - p.x, byy = r.y - p.y, bz = r.z - p.z;
        float nx = ay * bz - az * byy, ny = az * bx - ax * bz, nz = ax * byy - ay * bx;
        // Outward: away from the body's axis at this height.
        const float mx = (p.x + q.x + r.x) / 3.0f, my = (p.y + q.y + r.y) / 3.0f;
        if (nx * mx + ny * (my - 0.5f * hBelt) < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
        for (int k = 0; k < 3; ++k) {
            const uint16_t idx = b->indices[t + k];
            acc[idx * 3] += nx; acc[idx * 3 + 1] += ny; acc[idx * 3 + 2] += nz;
        }
    }
    for (size_t i = 0; i < b->verts.size(); ++i) {
        float nx = acc[i * 3], ny = acc[i * 3 + 1], nz = acc[i * 3 + 2];
        const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len < 1e-9f) { nx = 0; ny = 1; nz = 0; } else { nx /= len; ny /= len; nz /= len; }
        b->verts[i].nx = nx; b->verts[i].ny = ny; b->verts[i].nz = nz;
    }
    // The caps: a fan over the end ring, textured from the nose or tail block.
    for (int end = 0; end < 2; ++end) {
        const int station = end == 0 ? 0 : kStations;
        const float z = end == 0 ? zTail : zNose;
        const float hw = halfWidthAt(z);
        const float deck = deckHeight(z), roof = roofHeight(z, deck);
        const float topY = (std::max)(roof, deck) + 0.02f * W;
        const float u0 = (end == 0 ? 64.0f : 0.0f) / atlasW, u1 = (end == 0 ? 128.0f : 64.0f) / atlasW;
        auto capUv = [&](float x, float y, float* u, float* v) {
            *u = u0 + (u1 - u0) * (0.5f + 0.5f * x / (std::max)(hw, 1e-3f));
            *v = blockV0 + (blockV1 - blockV0) * (1.0f - (y - hSill) / (std::max)(topY - hSill, 1e-3f));
        };
        std::vector<int> ring;   // indices into the new cap vertices
        const int centre = static_cast<int>(b->verts.size());
        {
            CarBodyVertex c = {};
            c.x = 0; c.y = 0.5f * (hSill + deck); c.z = z;
            c.nz = end == 0 ? -1.0f : 1.0f;
            capUv(c.x, c.y, &c.u, &c.v);
            b->verts.push_back(c);
        }
        // Left side up, over the top, right side down.
        auto add = [&](int side, int fam, int k) {
            const CarBodyVertex& src = b->verts[base[side][fam] + station * counts[fam] + k];
            CarBodyVertex v = src;
            v.nx = 0; v.ny = 0; v.nz = end == 0 ? -1.0f : 1.0f;
            capUv(v.x, v.y, &v.u, &v.v);
            ring.push_back(static_cast<int>(b->verts.size()));
            b->verts.push_back(v);
        };
        for (int fam = 0; fam < kFamilies; ++fam) for (int k = 0; k < counts[fam]; ++k) add(0, fam, k);
        for (int fam = kFamilies - 1; fam >= 0; --fam) for (int k = counts[fam] - 1; k >= 0; --k) add(1, fam, k);
        for (size_t i = 0; i + 1 < ring.size(); ++i) {
            b->indices.insert(b->indices.end(), {static_cast<uint16_t>(centre), static_cast<uint16_t>(ring[i]),
                                                 static_cast<uint16_t>(ring[i + 1])});
        }
    }

    // The wheel, at its own origin, axle along x.
    const float r = (std::min)(0.21f * W, 0.09f * L);
    const float ww = 0.13f * W;
    b->wheelVerts.clear();
    b->wheelIndices.clear();
    const float ru0 = 128.0f / atlasW, ru1 = 144.0f / atlasW, hu0 = 144.0f / atlasW, hu1 = 160.0f / atlasW;
    for (int s = 0; s <= kWheelSegments; ++s) {
        const float a = 2.0f * kPi * s / kWheelSegments;
        const float cy_ = std::cos(a), sz_ = std::sin(a);
        for (int side = 0; side < 2; ++side) {
            CarBodyVertex v = {};
            v.x = side == 0 ? -0.5f * ww : 0.5f * ww;
            v.y = r * cy_;
            v.z = r * sz_;
            v.nx = 0; v.ny = cy_; v.nz = sz_;
            v.u = ru0 + (ru1 - ru0) * (static_cast<float>(s) / kWheelSegments) * 3.0f;
            v.u = ru0 + std::fmod(v.u - ru0, ru1 - ru0);
            v.v = blockV0 + (blockV1 - blockV0) * (side == 0 ? 0.05f : 0.95f);
            b->wheelVerts.push_back(v);
        }
    }
    for (int s = 0; s < kWheelSegments; ++s) {
        const int p = s * 2;
        b->wheelIndices.insert(b->wheelIndices.end(), {static_cast<uint16_t>(p), static_cast<uint16_t>(p + 2), static_cast<uint16_t>(p + 3),
                                                       static_cast<uint16_t>(p), static_cast<uint16_t>(p + 3), static_cast<uint16_t>(p + 1)});
    }
    for (int side = 0; side < 2; ++side) {
        const int centre = static_cast<int>(b->wheelVerts.size());
        const float x = side == 0 ? -0.5f * ww : 0.5f * ww;
        CarBodyVertex c = {};
        c.x = x; c.nx = side == 0 ? -1.0f : 1.0f;
        c.u = 0.5f * (hu0 + hu1); c.v = 0.5f * (blockV0 + blockV1);
        b->wheelVerts.push_back(c);
        for (int s = 0; s <= kWheelSegments; ++s) {
            const float a = 2.0f * kPi * s / kWheelSegments;
            CarBodyVertex v = {};
            v.x = x; v.y = r * std::cos(a); v.z = r * std::sin(a);
            v.nx = c.nx;
            v.u = hu0 + (hu1 - hu0) * (0.5f + 0.5f * std::cos(a));
            v.v = blockV0 + (blockV1 - blockV0) * (0.5f + 0.5f * std::sin(a));
            b->wheelVerts.push_back(v);
        }
        for (int s = 0; s < kWheelSegments; ++s) {
            b->wheelIndices.insert(b->wheelIndices.end(), {static_cast<uint16_t>(centre), static_cast<uint16_t>(centre + 1 + s),
                                                           static_cast<uint16_t>(centre + 2 + s)});
        }
    }
    b->deckY = hHood;
    b->roofY = hRoof;
    b->wheelZ[0] = (m.wheelFront - cy) * scale;
    b->wheelZ[1] = (m.wheelRear - cy) * scale;
    b->wheelX = (std::max)(halfWidthAt(b->wheelZ[0]), halfWidthAt(b->wheelZ[1])) * 0.96f - 0.5f * ww;
    b->wheelY = r;
    b->wheelbase = (std::max)(b->wheelZ[0] - b->wheelZ[1], 0.05f);
}

// Tiles per sprite pixel, from the quad: its length along v over the texture's rows.
float PixelScale(const CarBodyUse& use, int h) {
    const CarBodyVertex* c = use.local;
    const float ax = c[1].x - c[0].x, az = c[1].z - c[0].z, bx = c[3].x - c[0].x, bz = c[3].z - c[0].z;
    const float dvA = c[1].v - c[0].v, dvB = c[3].v - c[0].v;
    const bool lengthIsB = std::fabs(dvB) >= std::fabs(dvA);
    const float edge = lengthIsB ? std::sqrt(bx * bx + bz * bz) : std::sqrt(ax * ax + az * az);
    const float dv = std::fabs(lengthIsB ? dvB : dvA);
    return dv > 1e-6f && h > 0 ? edge / dv / static_cast<float>(h) : 1.0f / 64.0f;
}

// Models painted in a fixed livery (CARI numbers): the bank van, bus, cop car,
// fire truck, army jeep, hot-dog and ice-cream vans, medicar, the two taxis, SWAT
// van, tank, the trains, TV van, special agent car and karma bus.
bool LiveryModel(int m) {
    switch (m) {
        case 4: case 11: case 12: case 17: case 22: case 23: case 24: case 25: case 26: case 27:
        case 34: case 51: case 52: case 54: case 56: case 59: case 60: case 61: case 67:
        case 84: case 85: case 86: return true;
        default: return false;
    }
}

// The car's measurements (paint, footprint) from its artwork: what both a
// hand-made model and a body built here need. The body mesh itself is built
// only when it is going to be drawn (BodyMesh).

// From the driver's seat the model is a solid hull: on the plain D3D9 path two
// user clip planes cut it just below the eye and at the windscreen. RTX Remix
// ignores user clip planes (the hull then shows as a bright cut surface across
// the view), so under Remix the same cut is made on the CPU: a copy of the model
// keeping only the triangles whose centre, in the car's own frame after the fit,
// lies below `yCut` and ahead of `zCut` (the hood, the fenders, the cowl). Each
// (model, cuts) pair is built once and registered with the store.
struct HoodKey {
    const Model* model; int yq, zq, xq;
    bool operator<(const HoodKey& o) const { return std::tie(model, yq, zq, xq) < std::tie(o.model, o.yq, o.zq, o.xq); }
};
// QB-5: with the copy, the dashboard that closes it (see DrawDash): the top of what
// is kept in the first 0.08 block ahead of the windscreen cut, and its width there.
struct HoodCopy { const Model* model; float dashTop, dashX0, dashX1; bool dash; };
std::map<HoodKey, HoodCopy> g_hoods;

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b);   // defined below
inline gta2::Vec3 PointBy(const gta2::Mat4& m, float x, float y, float z) {
    return {x * m.m[0][0] + y * m.m[1][0] + z * m.m[2][0] + m.m[3][0],
            x * m.m[0][1] + y * m.m[1][1] + z * m.m[2][1] + m.m[3][1],
            x * m.m[0][2] + y * m.m[1][2] + z * m.m[2][2] + m.m[3][2]};
}

// The ten burnt-out wrecks are CARI models 72..81; 82..86 (Jagular XK, Furore GT, the special
// agent car, ...) are whole cars. FIX-CAR-RENDER: "< 72" took those five for wrecks: no cab from
// the seat, no dents, wheels or doors (pt-fp-cab-jagular-xk-torn-black-shards).
inline bool WreckModelNumber(int m) { return m >= 72 && m <= 81; }
bool g_hoodDropDark = true;   // [devtools] hood_drop_dark=0 keeps the seat copy's near-black faces (A/B checks)
const HoodCopy& HoodModelFor(const Model& model, const gta2::Mat4& fit, float yCut, float zCut, float eyeX) {
    // 0.04-block steps: the eye bobs and leans a little, the cache stays small.
    const HoodKey key{&model, static_cast<int>(std::floor(yCut * 25.0f)), static_cast<int>(std::floor(zCut * 25.0f)),
                      static_cast<int>(std::floor(eyeX * 25.0f))};
    auto it = g_hoods.find(key);
    if (it != g_hoods.end()) return it->second;
    if (g_hoods.size() > 96) g_hoods.clear();   // the store keeps the models; only the lookup is dropped
    float dashTop = -1.0f, dashX0 = 1e9f, dashX1 = -1e9f;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model hood;
    hood.name = model.name + "#hood";
    hood.nodes = model.nodes;
    hood.forward = model.forward;
    hood.boundsMin = model.boundsMin; hood.boundsMax = model.boundsMax;
    for (int k = 0; k < 3; ++k) hood.paintRgb[k] = model.paintRgb[k];
    hood.splitPaint = model.splitPaint;
    hood.meshes.resize(model.meshes.size());
    size_t kept = 0, all = 0, darkDropped = 0;
    const bool dropDark = g_hoodDropDark && 0.30f * model.paintRgb[0] + 0.59f * model.paintRgb[1] + 0.11f * model.paintRgb[2] >= 50.0f;
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& dst = hood.meshes[static_cast<size_t>(mi)];
        dst.vertices = src.vertices;
        dst.texture = src.texture;
        dst.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        // A vertex with its signed distances inside the two cuts: below the eye
        // plane (yCut - y) and ahead of the windscreen plane (z - zCut); the mesh
        // is clipped against both, so the hood's edge is the plane itself rather
        // than a stair of dropped triangles.
        struct CV { ModelVertex v; float dy, dz; };
        auto lerpV = [](const ModelVertex& a, const ModelVertex& b, float t) {
            ModelVertex o;
            o.x = a.x + (b.x - a.x) * t; o.y = a.y + (b.y - a.y) * t; o.z = a.z + (b.z - a.z) * t;
            o.nx = a.nx + (b.nx - a.nx) * t; o.ny = a.ny + (b.ny - a.ny) * t; o.nz = a.nz + (b.nz - a.nz) * t;
            o.u = a.u + (b.u - a.u) * t; o.v = a.v + (b.v - a.v) * t;
            return o;
        };
        // Sutherland-Hodgman against one plane: keep where d >= 0.
        auto clipPoly = [&](std::vector<CV>& poly, int which) {
            std::vector<CV> out;
            const size_t n = poly.size();
            for (size_t i = 0; i < n; ++i) {
                const CV& a = poly[i];
                const CV& b = poly[(i + 1) % n];
                const float da = which == 0 ? a.dy : a.dz, db = which == 0 ? b.dy : b.dz;
                if (da >= 0.0f) out.push_back(a);
                if ((da >= 0.0f) != (db >= 0.0f)) {
                    const float t = da / (da - db);
                    CV c;
                    c.v = lerpV(a.v, b.v, t);
                    c.dy = a.dy + (b.dy - a.dy) * t;
                    c.dz = a.dz + (b.dz - a.dz) * t;
                    out.push_back(c);
                }
            }
            poly.swap(out);
        };
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            ++all;
            gta2::Vec3 q[3];
            std::vector<CV> poly(3);
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                poly[static_cast<size_t>(c)] = {v, yCut - q[c].y, q[c].z - zCut};
            }
            // Only faces the eye sees from their front, as back-face culling would
            // show them: the hood's top, the fender tops, the cowl. The engine bay's
            // inner walls, the body's sides and the faces that look down (the hood's
            // underside, the floor pan and the underbody ahead of the seat) are seen
            // from inside the hull from their back, and the path tracer draws back
            // faces: run remix3_b showed them as black shreds across the view of a
            // Schmidt (REMIX-3). Which way a face looks comes from its vertex normals
            // in the car's frame, not the winding, which the fit's mirror (forward -1)
            // reverses; a face that looks down by more than a little is dropped too.
            gta2::Vec3 nrm{0.0f, 0.0f, 0.0f};
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                nrm.x += v.nx * toCar.m[0][0] + v.ny * toCar.m[1][0] + v.nz * toCar.m[2][0];
                nrm.y += v.nx * toCar.m[0][1] + v.ny * toCar.m[1][1] + v.nz * toCar.m[2][1];
                nrm.z += v.nx * toCar.m[0][2] + v.ny * toCar.m[1][2] + v.nz * toCar.m[2][2];
            }
            const float nl = std::sqrt(gta2::Dot(nrm, nrm));
            const gta2::Vec3 centre{(q[0].x + q[1].x + q[2].x) / 3.0f, (q[0].y + q[1].y + q[2].y) / 3.0f, (q[0].z + q[1].z + q[2].z) / 3.0f};
            const gta2::Vec3 toEye{eyeX - centre.x, yCut + 0.035f - centre.y, zCut - 0.10f - centre.z};
            const bool seen = nl > 1e-9f && nrm.y / nl > -0.2f && gta2::Dot(nrm, toEye) > 0.0f;
            if (!seen) continue;
            // FIX-CAR-RENDER (pt-fp-cab-jagular-xk-torn-black-shards): an image-to-3D shell maps its
            // inner wings, cowl and engine-bay walls onto the atlas's black background; from the seat
            // those faces read as torn black shards past the dash. A face whose texture is near black
            // where it is not paint is dropped from the seat's copy (not for a dark-painted model,
            // whose black is its paint).
            if (dropDark) {
                float lum = 0.0f, cover = 0.0f;
                int got = 0;
                const bool paintTex = src.texture.find("_paint") != std::string::npos;
                for (int c = 0; c < 4; ++c) {
                    float u = 0.0f, v = 0.0f;
                    if (c < 3) { const ModelVertex& mv = src.vertices[src.indices[t + static_cast<size_t>(c)]]; u = mv.u; v = mv.v; }
                    else {
                        for (int k = 0; k < 3; ++k) { const ModelVertex& mv = src.vertices[src.indices[t + static_cast<size_t>(k)]]; u += mv.u / 3.0f; v += mv.v / 3.0f; }
                    }
                    float l = 0.0f, a = 0.0f;
                    if (ModelTextureSample(src.texture, u, v, &l, &a)) { lum += l; cover += paintTex ? a : 255.0f - a; ++got; }
                }
                if (got && lum / got < 16.0f && cover / got < 128.0f) { ++darkDropped; continue; }
            }
            // The dashboard's top and width: what is kept just ahead of the cut.
            for (int c = 0; c < 3; ++c) {
                if (q[c].z < zCut - 0.01f || q[c].z > zCut + 0.08f) continue;
                dashTop = (std::max)(dashTop, (std::min)(q[c].y, yCut - 0.008f));   // under the clip plane, springs and all
                dashX0 = (std::min)(dashX0, q[c].x); dashX1 = (std::max)(dashX1, q[c].x);
            }
            const bool allIn = poly[0].dy >= 0 && poly[1].dy >= 0 && poly[2].dy >= 0 && poly[0].dz >= 0 && poly[1].dz >= 0 && poly[2].dz >= 0;
            if (allIn) {
                dst.indices.push_back(src.indices[t]);
                dst.indices.push_back(src.indices[t + 1]);
                dst.indices.push_back(src.indices[t + 2]);
                ++kept;
                continue;
            }
            clipPoly(poly, 0);
            if (poly.size() >= 3) clipPoly(poly, 1);
            if (poly.size() < 3) continue;
            // The clipped polygon as a fan of new vertices.
            const uint32_t base = static_cast<uint32_t>(dst.vertices.size());
            for (const CV& c : poly) dst.vertices.push_back(c.v);
            for (size_t i = 1; i + 1 < poly.size(); ++i) {
                dst.indices.push_back(base);
                dst.indices.push_back(base + static_cast<uint32_t>(i));
                dst.indices.push_back(base + static_cast<uint32_t>(i + 1));
            }
            ++kept;
        }
    }
    const Model* stored = ModelRegisterDerived(std::move(hood));
    HoodCopy& copy = g_hoods[key];
    copy.model = stored;
    copy.dash = dashTop > 0.0f && dashX1 > dashX0;
    copy.dashTop = dashTop; copy.dashX0 = dashX0; copy.dashX1 = dashX1;
    Log("car bodies: hood copy of %s for the driver's seat: %zu of %zu triangles (y < %.2f, z > %.2f; %zu near-black dropped), dashboard %s top %.3f x %.2f..%.2f",
        model.name.c_str(), kept, all, yCut, zCut, darkDropped, copy.dash ? "at" : "none,", dashTop, copy.dash ? dashX0 : 0.0f, copy.dash ? dashX1 : 0.0f);
    return copy;
}

// FIX-PERF-3: the dashboard numbers of the hood copy without the copy. On the plain renderer the seat
// draws the seat bonnet (BonnetSurfaceFor) or, for a flat front, only the cab, and the hood copy was
// built (all of the hull clipped, its near-black faces sampled, a model registered: ~30 ms for the 063
// cab, again at each 0.04 step the eye crosses: six in the seat view's first 0.2 s) only for its dash top and width. The same faces count
// (seen from the eye, not near black where not paint), but only those within the dash's band are
// tested, so this is a pass over the vertices. model is null: nothing to draw.
std::map<HoodKey, HoodCopy> g_hoodDashes;
const HoodCopy& HoodDashFor(const Model& model, const gta2::Mat4& fit, float yCut, float zCut, float eyeX) {
    const HoodKey key{&model, static_cast<int>(std::floor(yCut * 25.0f)), static_cast<int>(std::floor(zCut * 25.0f)),
                      static_cast<int>(std::floor(eyeX * 25.0f))};
    auto full = g_hoods.find(key);
    if (full != g_hoods.end()) return full->second;
    auto it = g_hoodDashes.find(key);
    if (it != g_hoodDashes.end()) return it->second;
    if (g_hoodDashes.size() > 96) g_hoodDashes.clear();
    const double t0 = CarNowMs();
    float dashTop = -1.0f, dashX0 = 1e9f, dashX1 = -1e9f;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    const bool dropDark = g_hoodDropDark && 0.30f * model.paintRgb[0] + 0.59f * model.paintRgb[1] + 0.11f * model.paintRgb[2] >= 50.0f;
    size_t tested = 0;
    for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        const bool paintTex = src.texture.find("_paint") != std::string::npos;
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            gta2::Vec3 q[3];
            bool inBand = false;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                inBand = inBand || (q[c].z >= zCut - 0.01f && q[c].z <= zCut + 0.08f);
            }
            if (!inBand) continue;
            // as HoodModelFor: seen from the eye
            gta2::Vec3 nrm{0.0f, 0.0f, 0.0f};
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                nrm.x += v.nx * toCar.m[0][0] + v.ny * toCar.m[1][0] + v.nz * toCar.m[2][0];
                nrm.y += v.nx * toCar.m[0][1] + v.ny * toCar.m[1][1] + v.nz * toCar.m[2][1];
                nrm.z += v.nx * toCar.m[0][2] + v.ny * toCar.m[1][2] + v.nz * toCar.m[2][2];
            }
            const float nl = std::sqrt(gta2::Dot(nrm, nrm));
            const gta2::Vec3 centre{(q[0].x + q[1].x + q[2].x) / 3.0f, (q[0].y + q[1].y + q[2].y) / 3.0f, (q[0].z + q[1].z + q[2].z) / 3.0f};
            const gta2::Vec3 toEye{eyeX - centre.x, yCut + 0.035f - centre.y, zCut - 0.10f - centre.z};
            if (!(nl > 1e-9f && nrm.y / nl > -0.2f && gta2::Dot(nrm, toEye) > 0.0f)) continue;
            ++tested;
            // and not near black where it is not paint
            if (dropDark) {
                float lum = 0.0f, cover = 0.0f;
                int got = 0;
                for (int c = 0; c < 4; ++c) {
                    float u = 0.0f, v = 0.0f;
                    if (c < 3) { const ModelVertex& mv = src.vertices[src.indices[t + static_cast<size_t>(c)]]; u = mv.u; v = mv.v; }
                    else {
                        for (int k = 0; k < 3; ++k) { const ModelVertex& mv = src.vertices[src.indices[t + static_cast<size_t>(k)]]; u += mv.u / 3.0f; v += mv.v / 3.0f; }
                    }
                    float l = 0.0f, a = 0.0f;
                    if (ModelTextureSample(src.texture, u, v, &l, &a)) { lum += l; cover += paintTex ? a : 255.0f - a; ++got; }
                }
                if (got && lum / got < 16.0f && cover / got < 128.0f) continue;
            }
            for (int c = 0; c < 3; ++c) {
                if (q[c].z < zCut - 0.01f || q[c].z > zCut + 0.08f) continue;
                dashTop = (std::max)(dashTop, (std::min)(q[c].y, yCut - 0.008f));
                dashX0 = (std::min)(dashX0, q[c].x); dashX1 = (std::max)(dashX1, q[c].x);
            }
        }
    }
    HoodCopy& copy = g_hoodDashes[key];
    copy.model = nullptr;
    copy.dash = dashTop > 0.0f && dashX1 > dashX0;
    copy.dashTop = dashTop; copy.dashX0 = dashX0; copy.dashX1 = dashX1;
    static int logged = 0;
    if (logged < 60) {
        ++logged;
        Log("car bodies: hood dash of %s for the driver's seat (no copy drawn): %zu faces at the cut (y < %.2f, z > %.2f), dashboard %s top %.3f x %.2f..%.2f, %.1f ms",
            model.name.c_str(), tested, yCut, zCut, copy.dash ? "at" : "none,", dashTop, copy.dash ? dashX0 : 0.0f, copy.dash ? dashX1 : 0.0f, CarNowMs() - t0);
    }
    return copy;
}

// The driver's cab of a tall or long model (truck, bus, van, fire truck), in the
// car's own frame after the fit (blocks; y up from the road, +z the nose): where
// the hood ends and the windscreen starts, the hood's top (the deck) and the
// cab's roof over the driver. A sedan's numbers come from its roof alone (deck
// 0.62 of it, the windscreen from CARI); a truck's roof is often a box body or
// roof gear behind the cab, and CARI's windscreen line on those long sprites
// lies inside that body, so the eye sat behind the fire truck's ladder (run
// a33_fire2 ft_drive_06). The model's own side profile says where the cab is:
// the height of the middle band of the body in 32 slices from tail to nose; the
// hood is the run of slices from the nose that stay within an eighth of the
// height of the nose; the windscreen is where that run ends. A flat front (bus,
// cab-over truck, train) has no hood: the windscreen is at the nose and the
// deck a little over half the cab's height. Built once per model and fit.
struct CabShape {
    bool valid = false, flat = false;
    float length = 0, height = 0, deck = 0, roof = 0, windscreen = 0;
};
struct CabKey {
    const Model* model; int xq, yq, zq;
    bool operator<(const CabKey& o) const { return std::tie(model, xq, yq, zq) < std::tie(o.model, o.xq, o.yq, o.zq); }
};
std::map<CabKey, CabShape> g_cabShapes;

CabShape CabShapeFor(const Model& model, const gta2::Mat4& fit, int modelNumber) {
    const CabKey key{&model, static_cast<int>(std::lround(std::fabs(fit.m[0][0] + fit.m[2][0]) * 100.0f)),
                     static_cast<int>(std::lround(fit.m[1][1] * 100.0f)),
                     static_cast<int>(std::lround(std::fabs(fit.m[2][2] + fit.m[0][2]) * 100.0f))};
    auto it = g_cabShapes.find(key);
    if (it != g_cabShapes.end()) return it->second;
    if (g_cabShapes.size() > 256) g_cabShapes.clear();
    CabShape cab;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    float minX = 1e9f, maxX = -1e9f, minY = 1e9f, maxY = -1e9f, minZ = 1e9f, maxZ = -1e9f;
    auto each = [&](auto&& fn) {
        for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
            const int mi = model.nodes[n].mesh;
            if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
            const gta2::Mat4 toCar = Mul(worlds[n], fit);
            for (const ModelVertex& v : model.meshes[static_cast<size_t>(mi)].vertices) fn(PointBy(toCar, v.x, v.y, v.z));
        }
    };
    each([&](const gta2::Vec3& q) {
        minX = (std::min)(minX, q.x); maxX = (std::max)(maxX, q.x);
        minY = (std::min)(minY, q.y); maxY = (std::max)(maxY, q.y);
        minZ = (std::min)(minZ, q.z); maxZ = (std::max)(maxZ, q.z);
    });
    const float L = maxZ - minZ, H = maxY - minY, W = maxX - minX, cx = 0.5f * (minX + maxX);
    if (!(L > 0.05f && H > 0.05f && W > 0.05f)) {
        g_cabShapes[key] = cab;
        return cab;
    }
    constexpr int kSlices = 32;
    float h[kSlices];
    for (float& v : h) v = -1.0f;
    each([&](const gta2::Vec3& q) {
        if (std::fabs(q.x - cx) > 0.35f * W) return;
        const int b = (std::min)(kSlices - 1, (std::max)(0, static_cast<int>((q.z - minZ) / L * kSlices)));
        h[b] = (std::max)(h[b], q.y - minY);
    });
    for (int b = 1; b < kSlices; ++b) if (h[b] < 0.0f) h[b] = h[b - 1];
    for (int b = kSlices - 2; b >= 0; --b) if (h[b] < 0.0f) h[b] = h[b + 1];
    const float slice = L / kSlices;
    const float nose = (std::max)(h[kSlices - 1], h[kSlices - 2]);
    int end = kSlices - 1;   // the last slice of the hood run, counting from the nose
    while (end > 0 && h[end - 1] <= nose + 0.125f * H) --end;
    const float runLength = (kSlices - end) * slice;
    const bool flat = nose >= 0.85f * H || runLength > 0.45f * L;
    cab.windscreen = flat ? maxZ - 0.06f * L : minZ + end * slice;
    float roof = 0.0f;
    for (int b = 0; b < kSlices; ++b) {
        const float z0 = minZ + b * slice, z1 = z0 + slice;
        if (z1 > cab.windscreen - 0.35f && z0 < cab.windscreen + 0.02f) roof = (std::max)(roof, h[b]);
    }
    cab.roof = roof;
    cab.deck = flat ? 0.55f * roof : nose;
    if (cab.roof < cab.deck + 0.08f) cab.roof = cab.deck + 0.08f;
    cab.length = L;
    cab.height = H;
    cab.flat = flat;
    cab.valid = true;
    g_cabShapes[key] = cab;
    Log("car bodies: cab of model %d (%s): %.2f x %.2f x %.2f blocks, %s front, hood %.2f long at %.2f, windscreen %+.2f, cab roof %.2f",
        modelNumber, model.name.c_str(), L, W, H, flat ? "flat" : "hooded", runLength, cab.deck, cab.windscreen, cab.roof);
    return cab;
}

// QB-5: the dashboard. The hood copy is the hull cut open at the windscreen plane;
// from the seat the eye looks down through that open face into the hull, and what
// it saw there - the inside of the wings and the underbody, from their back, and
// whatever faces of a generated mesh the copy's facing test let through - read as
// black shards and pale ribbons across the lower half of the view (runs qa_qb5base2,
// qa_qb5fix: the Schmidt, the Aniston BD4). A panel across the cut, from the floor
// to the top of what the copy keeps just ahead of the cut, and a shelf back toward
// the eye at that height, close it: a dashboard in the body's colour, darker, as the
// metal dashboards of these cars were. Lit by the scene's lights (it darkens at
// night with the body), drawn untextured in the car's frame on its springs.
void DrawDash(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const HoodCopy& hood, float zCut, const float paint[3],
              const D3DMATERIAL9& restore) {
    struct V { float x, y, z, nx, ny, nz; };
    const float x0 = hood.dashX0 - 0.01f, x1 = hood.dashX1 + 0.01f;
    const float top = hood.dashTop, floorY = 0.03f;
    const float zf = zCut - 0.004f, zb = zCut - 0.065f;
    const V local[8] = {
        // the panel, facing the seat (-z)
        {x0, floorY, zf, 0, 0, -1}, {x1, floorY, zf, 0, 0, -1}, {x1, top, zf, 0, 0, -1}, {x0, top, zf, 0, 0, -1},
        // the shelf, facing up
        {x0, top, zb, 0, 1, 0}, {x1, top, zb, 0, 1, 0}, {x1, top, zf, 0, 1, 0}, {x0, top, zf, 0, 1, 0},
    };
    V world[8];
    for (int i = 0; i < 8; ++i) {
        const gta2::Vec3 p = PointBy(carToWorld, local[i].x, local[i].y, local[i].z);
        const float nx = local[i].nx * carToWorld.m[0][0] + local[i].ny * carToWorld.m[1][0] + local[i].nz * carToWorld.m[2][0];
        const float ny = local[i].nx * carToWorld.m[0][1] + local[i].ny * carToWorld.m[1][1] + local[i].nz * carToWorld.m[2][1];
        const float nz = local[i].nx * carToWorld.m[0][2] + local[i].ny * carToWorld.m[1][2] + local[i].nz * carToWorld.m[2][2];
        const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
        world[i] = {p.x, p.y, p.z, nl > 1e-6f ? nx / nl : 0.0f, nl > 1e-6f ? ny / nl : 1.0f, nl > 1e-6f ? nz / nl : 0.0f};
    }
    const uint16_t idx[12] = {0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7};
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    D3DMATERIAL9 m = restore;
    const float k = 0.38f;   // a darker shade of the paint, never a black hole on a dark car
    m.Diffuse = {0.10f + k * paint[0], 0.10f + k * paint[1], 0.10f + k * paint[2], 1.0f};
    m.Ambient = m.Diffuse;
    m.Specular = {0.0f, 0.0f, 0.0f, 0.0f};
    device->SetMaterial(&m);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 8, 4, idx, D3DFMT_INDEX16, world, sizeof(V));
    device->SetMaterial(&restore);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
}

// QB-5: the bonnet's top, in blocks over the road, of a model at `fit`: the 99th
// percentile of the heights of the vertices ahead of the windscreen (`windscreen`
// + 0.02, in the car's frame after the fit) across the body's width. The first-
// person eye stands on the cabin deck (view_modes: deck + 0.62 of the way to the
// roof), and the own car seen from the seat is cut a hand below the eye
// (HoodModelFor, the clip plane). Where the deck from the sprite (0.62 of the
// roof for a car) lies under the bonnet, as on the Schmidt's tall bonnet and
// raised lamps, that cut sliced the bonnet's lumpy top into black islands and
// pale ribbons across the lower half of the view (run qa_qb5base2). The deck is
// kept above this height, so the eye looks over the bonnet as a driver does.
// A percentile, so a mascot or an aerial does not lift the eye. Cached per model and fit.
struct BonnetKey {
    const Model* model; int xq, yq, zq, wq;
    bool operator<(const BonnetKey& o) const { return std::tie(model, xq, yq, zq, wq) < std::tie(o.model, o.xq, o.yq, o.zq, o.wq); }
};
std::map<BonnetKey, float> g_bonnets;

float BonnetTopFor(const Model& model, const gta2::Mat4& fit, float windscreen) {
    const BonnetKey key{&model, static_cast<int>(std::lround(std::fabs(fit.m[0][0] + fit.m[2][0]) * 100.0f)),
                        static_cast<int>(std::lround(fit.m[1][1] * 100.0f)),
                        static_cast<int>(std::lround(std::fabs(fit.m[2][2] + fit.m[0][2]) * 100.0f)),
                        static_cast<int>(std::lround(windscreen * 100.0f))};
    auto it = g_bonnets.find(key);
    if (it != g_bonnets.end()) return it->second;
    if (g_bonnets.size() > 256) g_bonnets.clear();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    std::vector<float> ys;
    for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (const ModelVertex& v : model.meshes[static_cast<size_t>(mi)].vertices) {
            const gta2::Vec3 q = PointBy(toCar, v.x, v.y, v.z);
            if (q.z > windscreen + 0.02f) ys.push_back(q.y);
        }
    }
    float top = 0.0f;
    if (ys.size() >= 16) {
        const size_t k = (ys.size() * 99) / 100;
        std::nth_element(ys.begin(), ys.begin() + static_cast<std::ptrdiff_t>(k), ys.end());
        top = ys[k];
    }
    g_bonnets[key] = top;
    Log("car bodies: bonnet of %s ahead of the windscreen %+.2f: top %.3f (%zu vertices)", model.name.c_str(), windscreen, top, ys.size());
    return top;
}

// FIX-FP (pm8-fp-bonnet-shredded-slivers-and-grey-header-bar, pm16-ste-fp-convertible-...-spiky-bonnet):
// the bonnet seen from the driver's seat, rebuilt as a clean surface. The hood copy (HoodModelFor)
// is the hull cut at the eye; on the image-to-3D meshes its facing test drops a random half of the
// bonnet's noisy triangles (holes, "shredded" maroon), and the windscreen's and A-pillars' faces
// between the cut and the real windscreen survive as slivers standing up into the view. Here the
// body's top is sampled instead: rows across the car from the windscreen's foot to the nose, each
// row's outline found by bisection, the height under a ceiling (the bonnet's top, so glass and
// pillars never rise into the view) by a ray down onto the hull, median-filtered and smoothed. The
// surface is drawn in the paint with skirts down its sides and nose; the cowl back to the dash is
// added at draw time (the cut moves with the eye). Built once per model and fit.
struct BonnetSurface {
    bool valid = false;
    int rows = 0, cols = 0;
    std::vector<float> z, xl, xr, h;   // per row: z, outline; per row*cols: height
    std::vector<float> rgb, cov;       // per row*cols: the texel colour (0..1) and how much of it is paint
};
// A 64x64 colour copy of a model texture (its file beside the models), averaged; the alpha is
// kept as its mean. The paint split (import_assets.py) leaves the base texture transparent where
// its "_paint" twin is paint, so (1 - alpha) of the base is the paint's share there.
// FIX-CAR-IDENTITY-2: rgbA, the colour of each cell's opaque texels (weighted by alpha), and 256 cells across
// (was 64: an 8x8 texel cell of an image-to-3D atlas took in the black gaps between its islands).
struct RgbMap { int n = 0; std::vector<float> rgb, a, rgbA; };
std::map<std::string, RgbMap> g_rgbMaps;
std::mutex g_rgbLock;   // FIX-PERF-3: the seat bonnet is built on the wear thread too (never erased: pointers stay)
const RgbMap* RgbFor(const std::string& file) {
    std::lock_guard<std::mutex> lock(g_rgbLock);
    auto it = g_rgbMaps.find(file);
    if (it != g_rgbMaps.end()) return it->second.n ? &it->second : nullptr;
    RgbMap& m = g_rgbMaps[file];
    const std::string path = std::string(ModelsFolder()) + "\\" + file;
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return nullptr;
    std::vector<uint8_t> tga;
    uint8_t buf[65536];
    size_t got;
    while ((got = std::fread(buf, 1, sizeof(buf), f)) > 0) tga.insert(tga.end(), buf, buf + got);
    std::fclose(f);
    if (tga.size() <= 18 || tga[2] != 2 || tga[16] != 32) return nullptr;
    const int w = tga[12] | (tga[13] << 8), h = tga[14] | (tga[15] << 8);
    if (w <= 0 || h <= 0 || tga.size() < 18u + static_cast<size_t>(w) * h * 4) return nullptr;
    const bool topDown = (tga[17] & 0x20) != 0;
    constexpr int kN = 256;
    std::vector<float> sum(kN * kN * 3, 0.0f), as(kN * kN, 0.0f), cnt(kN * kN, 0.0f), suma(kN * kN * 3, 0.0f);
    for (int y = 0; y < h; ++y) {
        const uint8_t* row = &tga[18 + static_cast<size_t>(topDown ? y : (h - 1 - y)) * w * 4];
        const int cy = y * kN / h;
        for (int x = 0; x < w; ++x) {
            const uint8_t* px = row + x * 4;
            const int c = cy * kN + x * kN / w;
            sum[c * 3] += px[2]; sum[c * 3 + 1] += px[1]; sum[c * 3 + 2] += px[0];
            suma[c * 3] += px[2] * px[3]; suma[c * 3 + 1] += px[1] * px[3]; suma[c * 3 + 2] += px[0] * px[3];
            as[c] += px[3]; cnt[c] += 1.0f;
        }
    }
    m.n = kN; m.rgb.resize(kN * kN * 3); m.a.resize(kN * kN); m.rgbA.resize(kN * kN * 3);
    for (int i = 0; i < kN * kN; ++i) {
        const float k = cnt[i] > 0 ? 1.0f / (255.0f * cnt[i]) : 0.0f;
        for (int c = 0; c < 3; ++c) m.rgb[i * 3 + c] = sum[i * 3 + c] * k;
        for (int c = 0; c < 3; ++c) m.rgbA[i * 3 + c] = as[i] > 0.0f ? suma[i * 3 + c] / (255.0f * as[i]) : m.rgb[i * 3 + c];
        m.a[i] = as[i] * k;
    }
    return &m;
}
struct BonnetSurfKey {
    const Model* model; int xq, yq, zq, wq;
    bool operator<(const BonnetSurfKey& o) const { return std::tie(model, xq, yq, zq, wq) < std::tie(o.model, o.xq, o.yq, o.zq, o.wq); }
};
std::map<BonnetSurfKey, BonnetSurface> g_bonnetSurfs;
int g_fpBonnet = 1;   // [devtools] fp_bonnet=0: the hood copy from the seat instead (A/B checks)
int g_hoodDash = 1;   // [devtools] hood_dash=0: the full hood copy built for its dash as before FIX-PERF-3 (A/B checks)
bool g_cabRemixAlbedo = true;   // [devtools] remix_cab_albedo (FIX-REMIX-NIGHT-2)

BonnetSurfKey BonnetSurfKeyFor(const Model& model, const gta2::Mat4& fit, float windscreen) {
    return BonnetSurfKey{&model, static_cast<int>(std::lround(std::fabs(fit.m[0][0] + fit.m[2][0]) * 100.0f)),
                         static_cast<int>(std::lround(fit.m[1][1] * 100.0f)),
                         static_cast<int>(std::lround(std::fabs(fit.m[2][2] + fit.m[0][2]) * 100.0f)),
                         static_cast<int>(std::lround(windscreen * 100.0f))};
}
// The surface itself: reads only the model (immutable once loaded) and RgbFor (locked), so the wear thread
// can build it ahead of the first frame in the seat (FIX-PERF-3; 45 ms for the 063 cab on the render thread).
void BuildBonnetSurface(const Model& model, const gta2::Mat4& fit, float windscreen, float ceiling, BonnetSurface& s) {
    const double t0 = CarNowMs();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    struct Tri { gta2::Vec3 a, b, c; float z0, z1; const std::string* tex; float ua, va, ub, vb, uc, vc; };
    std::vector<Tri> tris;
    const float zStart = windscreen + 0.02f;
    float minX = 1e9f, maxX = -1e9f, maxZ = -1e9f;
    for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& m = model.meshes[static_cast<size_t>(mi)];
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (size_t t = 0; t + 2 < m.indices.size(); t += 3) {
            Tri tr;
            const ModelVertex& va = m.vertices[m.indices[t]];
            const ModelVertex& vb = m.vertices[m.indices[t + 1]];
            const ModelVertex& vc = m.vertices[m.indices[t + 2]];
            tr.a = PointBy(toCar, va.x, va.y, va.z); tr.b = PointBy(toCar, vb.x, vb.y, vb.z); tr.c = PointBy(toCar, vc.x, vc.y, vc.z);
            tr.z0 = (std::min)((std::min)(tr.a.z, tr.b.z), tr.c.z); tr.z1 = (std::max)((std::max)(tr.a.z, tr.b.z), tr.c.z);
            tr.tex = &m.texture; tr.ua = va.u; tr.va = va.v; tr.ub = vb.u; tr.vb = vb.v; tr.uc = vc.u; tr.vc = vc.v;
            if (tr.z1 < zStart - 0.01f) continue;
            if ((std::min)((std::min)(tr.a.y, tr.b.y), tr.c.y) > ceiling) continue;
            for (const gta2::Vec3* q : {&tr.a, &tr.b, &tr.c}) { minX = (std::min)(minX, q->x); maxX = (std::max)(maxX, q->x); maxZ = (std::max)(maxZ, q->z); }
            tris.push_back(tr);
        }
    }
    if (tris.size() < 16 || maxZ < zStart + 0.05f || maxX - minX < 0.1f) {
        Log("car bodies: seat bonnet of %s: nothing ahead of the windscreen %+.2f (%zu faces); the hood copy stands in", model.name.c_str(), windscreen, tris.size());
        return;
    }
    // The highest point of the hull at (x, z) at or under the ceiling, -1 for none.
    std::vector<const Tri*> row;
    const Tri* hitTri = nullptr; float hitU = 0.0f, hitV = 0.0f;
    auto ray = [&](float x, float z) {
        float best = -1.0f;
        hitTri = nullptr;
        for (const Tri* t : row) {
            const float d = (t->b.x - t->a.x) * (t->c.z - t->a.z) - (t->c.x - t->a.x) * (t->b.z - t->a.z);
            if (std::fabs(d) < 1e-10f) continue;
            const float u = ((x - t->a.x) * (t->c.z - t->a.z) - (t->c.x - t->a.x) * (z - t->a.z)) / d;
            const float v = ((t->b.x - t->a.x) * (z - t->a.z) - (x - t->a.x) * (t->b.z - t->a.z)) / d;
            if (u < -1e-4f || v < -1e-4f || u + v > 1.0001f) continue;
            const float y = t->a.y + u * (t->b.y - t->a.y) + v * (t->c.y - t->a.y);
            if (y <= ceiling + 1e-4f && y > best) { best = y; hitTri = t; hitU = u; hitV = v; }
        }
        return best;
    };
    // The colour where the last ray hit: the texel and its paint share (see RgbFor).
    auto hitColour = [&](float out[4]) {
        out[0] = out[1] = out[2] = 0.5f; out[3] = 1.0f;
        if (!hitTri) return;
        const float u = hitTri->ua + hitU * (hitTri->ub - hitTri->ua) + hitV * (hitTri->uc - hitTri->ua);
        const float v = hitTri->va + hitU * (hitTri->vb - hitTri->va) + hitV * (hitTri->vc - hitTri->va);
        std::string base = *hitTri->tex;
        const size_t pp = base.find("_paint");
        if (pp != std::string::npos) base.erase(pp, 6);
        const RgbMap* m = RgbFor(base);
        if (!m) return;
        const float uu = u - std::floor(u), vv = v - std::floor(v);
        const int i = (std::min)(m->n - 1, static_cast<int>(vv * m->n)) * m->n + (std::min)(m->n - 1, static_cast<int>(uu * m->n));
        // where the base is see-through, its _paint twin's texels are the paint
        out[3] = 1.0f - m->a[static_cast<size_t>(i)];
        // FIX-CABIN-DOME: a hit on the "_paint" texture is paint by its own alpha. On the split
        // image-to-3D bodies that is exactly 1 - the base's alpha (no change); the authored carkit
        // bodies (063, 013, 068) import an opaque base twin of their paint, so the share above came
        // out 0 and the bonnet drew untinted in the neutral 235: a pale dome filling the seat view.
        std::string twin = base;
        const size_t dot = twin.rfind('.');
        twin.insert(dot == std::string::npos ? twin.size() : dot, "_paint");
        const RgbMap* pm = RgbFor(twin);
        if (pp != std::string::npos && pm) out[3] = pm->a[static_cast<size_t>(i)];
        // FIX-CAR-IDENTITY-2 (the first-person bonnet that read dark maroon on a car whose body was right):
        // the colour is the base's opaque texels and the paint twin's own texels, mixed by the paint share.
        // The base's see-through texels do not hold the paint: tools/car_paint_resplit.py leaves the
        // generator's old colour there (its paint is the neutral twin), so the bonnet was that old colour
        // times the tint (teal x red = maroon).
        for (int c = 0; c < 3; ++c) {
            const float rest = m->rgbA[static_cast<size_t>(i) * 3 + c];
            const float paint = pm ? pm->rgbA[static_cast<size_t>(i) * 3 + c] : rest;
            out[c] = rest * (1.0f - out[3]) + paint * out[3];
        }
    };
    constexpr int kRows = 22, kScan = 48, kCols = 17;
    const float zEnd = maxZ - 0.004f;
    std::vector<float> hs;
    for (int r = 0; r < kRows; ++r) {
        const float z = zStart + (zEnd - zStart) * static_cast<float>(r) / (kRows - 1);
        row.clear();
        for (const Tri& t : tris) if (t.z0 <= z && t.z1 >= z) row.push_back(&t);
        const float dx = (maxX - minX + 0.02f) / (kScan - 1);
        int iL = -1, iR = -1;
        for (int i = 0; i < kScan; ++i) if (ray(minX - 0.01f + dx * i, z) > 0.02f) { if (iL < 0) iL = i; iR = i; }
        if (iL < 0) break;
        auto edge = [&](int hit, int miss) {
            float a = minX - 0.01f + dx * hit, b2 = minX - 0.01f + dx * miss;
            if (miss < 0 || miss >= kScan) return a;
            for (int k = 0; k < 7; ++k) { const float m = 0.5f * (a + b2); if (ray(m, z) > 0.02f) a = m; else b2 = m; }
            return a;
        };
        const float xl = edge(iL, iL - 1), xr = edge(iR, iR + 1);
        if (xr - xl < 0.06f) break;
        float line[kCols], col[kCols][4];
        for (int c = 0; c < kCols; ++c) {
            // a hair inside the outline, so the edge columns hit the body rather than its silhouette
            const float x = xl + (xr - xl) * (0.004f + 0.992f * static_cast<float>(c) / (kCols - 1));
            line[c] = ray(x, z);
            hitColour(col[c]);
        }
        // misses inside the outline (a gap in a generated shell): the nearest hit's height
        for (int c = 0; c < kCols; ++c) {
            if (line[c] > 0.02f) continue;
            for (int d = 1; d < kCols; ++d) {
                if (c - d >= 0 && line[c - d] > 0.02f) { line[c] = line[c - d]; for (int k = 0; k < 4; ++k) col[c][k] = col[c - d][k]; break; }
                if (c + d < kCols && line[c + d] > 0.02f) { line[c] = line[c + d]; for (int k = 0; k < 4; ++k) col[c][k] = col[c + d][k]; break; }
            }
        }
        s.z.push_back(z); s.xl.push_back(xl); s.xr.push_back(xr);
        for (float v : line) hs.push_back(v);
        for (int c = 0; c < kCols; ++c) { for (int k = 0; k < 3; ++k) s.rgb.push_back(col[c][k]); s.cov.push_back(col[c][3]); }
    }
    const int R = static_cast<int>(s.z.size());
    if (R < 3) {
        Log("car bodies: seat bonnet of %s: %d rows ahead of the windscreen %+.2f; the hood copy stands in", model.name.c_str(), R, windscreen);
        s.z.clear(); s.xl.clear(); s.xr.clear(); s.rgb.clear(); s.cov.clear();
        return;
    }
    // A 3x3 median (a generated shell's lone spikes and pits), then two 1-2-1 passes each way.
    auto at = [&](std::vector<float>& g, int r, int c) -> float& {
        r = (std::max)(0, (std::min)(R - 1, r)); c = (std::max)(0, (std::min)(kCols - 1, c));
        return g[static_cast<size_t>(r * kCols + c)];
    };
    std::vector<float> med(hs.size());
    for (int r = 0; r < R; ++r)
        for (int c = 0; c < kCols; ++c) {
            float w[9]; int k = 0;
            for (int i = -1; i <= 1; ++i) for (int j = -1; j <= 1; ++j) w[k++] = at(hs, r + i, c + j);
            std::nth_element(w, w + 4, w + 9);
            at(med, r, c) = w[4];
        }
    for (int pass = 0; pass < 2; ++pass) {
        std::vector<float> tmp(med.size());
        for (int r = 0; r < R; ++r) for (int c = 0; c < kCols; ++c) at(tmp, r, c) = 0.25f * at(med, r, c - 1) + 0.5f * at(med, r, c) + 0.25f * at(med, r, c + 1);
        for (int r = 0; r < R; ++r) for (int c = 0; c < kCols; ++c) at(med, r, c) = 0.25f * at(tmp, r - 1, c) + 0.5f * at(tmp, r, c) + 0.25f * at(tmp, r + 1, c);
    }
    // and the outline smoothed along the car (no zigzag from the bisection's last step)
    for (std::vector<float>* e : {&s.xl, &s.xr}) {
        std::vector<float> o = *e;
        for (int r = 1; r + 1 < R; ++r) (*e)[static_cast<size_t>(r)] = 0.25f * o[static_cast<size_t>(r - 1)] + 0.5f * o[static_cast<size_t>(r)] + 0.25f * o[static_cast<size_t>(r + 1)];
    }
    s.h.swap(med);
    {
        std::vector<float> o = s.rgb, oc = s.cov;
        for (int r = 0; r < R; ++r)
            for (int c = 0; c < kCols; ++c) {
                float acc[4] = {0, 0, 0, 0}; float n = 0.0f;
                for (int i = -1; i <= 1; ++i) for (int j = -1; j <= 1; ++j) {
                    const int rr = r + i, cc = c + j;
                    if (rr < 0 || rr >= R || cc < 0 || cc >= kCols) continue;
                    const size_t q = static_cast<size_t>(rr * kCols + cc);
                    for (int k = 0; k < 3; ++k) acc[k] += o[q * 3 + k];
                    acc[3] += oc[q]; n += 1.0f;
                }
                const size_t q = static_cast<size_t>(r * kCols + c);
                for (int k = 0; k < 3; ++k) s.rgb[q * 3 + k] = acc[k] / n;
                s.cov[q] = acc[3] / n;
            }
    }
    s.rows = R; s.cols = kCols;
    s.valid = true;
    Log("car bodies: seat bonnet of %s: %d x %d from %+.2f to %+.2f, x %.2f..%.2f at the windscreen, under %.3f (%zu faces, %.1f ms)",
        model.name.c_str(), R, kCols, s.z.front(), s.z.back(), s.xl.front(), s.xr.front(), ceiling, tris.size(), CarNowMs() - t0);
    return;
}

const BonnetSurface& BonnetSurfaceFor(const Model& model, const gta2::Mat4& fit, float windscreen, float ceiling) {
    const BonnetSurfKey key = BonnetSurfKeyFor(model, fit, windscreen);
    auto it = g_bonnetSurfs.find(key);
    if (it != g_bonnetSurfs.end()) return it->second;
    if (g_bonnetSurfs.size() > 64) g_bonnetSurfs.clear();
    BonnetSurface& s = g_bonnetSurfs[key];
    BuildBonnetSurface(model, fit, windscreen, ceiling, s);
    return s;
}

// The bonnet surface from the seat in the car's frame on its springs: the cowl from the cut
// (`zCut`, under the dash) to the first row, the rows, skirts down its sides and nose. Lit, in the
// paint (a dark paint held at a floor, as the body is), with a sheen.
// FIX-REMIX-NIGHT-2: under Remix (which reads neither vertex nor material colour) the samples' colours
// go into a small texture, a texel per sample, and the vertices carry its UVs. Cached per surface and
// colour; released with the device.
IDirect3DTexture9* g_bonnetTex = nullptr;
const BonnetSurface* g_bonnetTexFor = nullptr;
uint32_t g_bonnetTexKey = 0;
int g_bonnetTexW = 1, g_bonnetTexH = 1;
void BonnetTextureRelease() { if (g_bonnetTex) g_bonnetTex->Release(); g_bonnetTex = nullptr; g_bonnetTexFor = nullptr; }
IDirect3DTexture9* BonnetTexture(IDirect3DDevice9* device, const BonnetSurface& s, const float tint[3], float dull) {
    uint32_t key = static_cast<uint32_t>((std::max)(0.0f, (std::min)(1.0f, dull)) * 63.0f + 0.5f);
    for (int k = 0; k < 3; ++k) key = key << 8 | static_cast<uint32_t>((std::max)(0.0f, (std::min)(2.0f, tint[k])) * 127.0f + 0.5f);
    if (g_bonnetTex && g_bonnetTexFor == &s && g_bonnetTexKey == key) return g_bonnetTex;
    BonnetTextureRelease();
    int w = 1, h = 1;
    while (w < s.cols) w <<= 1;
    while (h < s.rows) h <<= 1;
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(t->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < h; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < w; ++x) {
                const size_t q = static_cast<size_t>((std::min)(y, s.rows - 1) * s.cols + (std::min)(x, s.cols - 1));
                uint32_t col = 0xff000000u;
                for (int k = 0; k < 3; ++k) {
                    const float v = s.rgb[q * 3 + static_cast<size_t>(k)] * (1.0f + s.cov[q] * (tint[k] - 1.0f)) * dull;
                    col |= static_cast<uint32_t>((std::max)(0.0f, (std::min)(1.0f, v)) * 255.0f + 0.5f) << (16 - 8 * k);
                }
                row[x] = col;
            }
        }
        t->UnlockRect(0);
    }
    g_bonnetTex = t; g_bonnetTexFor = &s; g_bonnetTexKey = key; g_bonnetTexW = w; g_bonnetTexH = h;
    return t;
}

void DrawBonnet(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const BonnetSurface& s, float zCut, float cowlTop, float maxY,
                const float tint[3], float dull, const D3DMATERIAL9& body, const D3DMATERIAL9& restore, bool remix = false, float paintLift = 1.0f) {
    struct V { float x, y, z, nx, ny, nz; DWORD c; };
    struct L { float x, y, z, nx, ny, nz; int q; };   // q: the sample whose colour it takes
    static const bool gainOldEnv = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_BONNET_GAIN_OLD", b, sizeof b) && b[0] == '1'; }();
    const bool gainOld = gainOldEnv || remix;
    const int C = s.cols;
    std::vector<L> local;
    std::vector<uint16_t> idx;
    // rows, with the cowl row prepended when the cut lies behind the first row
    std::vector<float> rz, rl, rr, rh;
    std::vector<int> rsrc;   // the surface row each drawn row takes its colours from
    if (zCut < s.z[0] - 0.005f) {
        rz.push_back(zCut - 0.01f); rl.push_back(s.xl[0]); rr.push_back(s.xr[0]); rsrc.push_back(0);
        for (int c = 0; c < C; ++c) rh.push_back((std::min)(s.h[static_cast<size_t>(c)], cowlTop));
    }
    for (int r = 0; r < s.rows; ++r) {
        if (s.z[static_cast<size_t>(r)] < zCut - 0.01f) continue;
        rz.push_back(s.z[static_cast<size_t>(r)]); rl.push_back(s.xl[static_cast<size_t>(r)]); rr.push_back(s.xr[static_cast<size_t>(r)]); rsrc.push_back(r);
        for (int c = 0; c < C; ++c) rh.push_back((std::min)(s.h[static_cast<size_t>(r * C + c)], maxY));
    }
    const int R = static_cast<int>(rz.size());
    if (R < 2) return;
    auto X = [&](int r, int c) { return rl[static_cast<size_t>(r)] + (rr[static_cast<size_t>(r)] - rl[static_cast<size_t>(r)]) * static_cast<float>(c) / (C - 1); };
    auto H = [&](int r, int c) { return rh[static_cast<size_t>(r * C + c)]; };
    for (int r = 0; r < R; ++r)
        for (int c = 0; c < C; ++c) {
            const int r0 = (std::max)(0, r - 1), r1 = (std::min)(R - 1, r + 1), c0 = (std::max)(0, c - 1), c1 = (std::min)(C - 1, c + 1);
            const gta2::Vec3 du{X(r, c1) - X(r, c0), H(r, c1) - H(r, c0), 0.0f};
            const gta2::Vec3 dv{X(r1, c) - X(r0, c), H(r1, c) - H(r0, c), rz[static_cast<size_t>(r1)] - rz[static_cast<size_t>(r0)]};
            gta2::Vec3 n = gta2::Cross(dv, du);
            if (n.y < 0.0f) n = n * -1.0f;
            n = gta2::Normalize(n);
            local.push_back({X(r, c), H(r, c), rz[static_cast<size_t>(r)], n.x, n.y, n.z, rsrc[static_cast<size_t>(r)] * C + c});
        }
    for (int r = 0; r + 1 < R; ++r)
        for (int c = 0; c + 1 < C; ++c) {
            const uint16_t a = static_cast<uint16_t>(r * C + c), b = static_cast<uint16_t>(a + 1), d = static_cast<uint16_t>(a + C), e = static_cast<uint16_t>(d + 1);
            idx.insert(idx.end(), {a, b, e, a, e, d});
        }
    // skirts: each side's edge and the nose's, 0.12 block down
    auto skirt = [&](int r0, int c0, int r1, int c1, float nx, float nz) {
        const uint16_t base = static_cast<uint16_t>(local.size());
        for (const auto& rc : {std::make_pair(r0, c0), std::make_pair(r1, c1)}) {
            const float x = X(rc.first, rc.second), y = H(rc.first, rc.second), z = rz[static_cast<size_t>(rc.first)];
            const int q = rsrc[static_cast<size_t>(rc.first)] * C + rc.second;
            local.push_back({x, y - 0.002f, z, nx, 0.0f, nz, q});
            local.push_back({x, (std::max)(0.02f, y - 0.12f), z, nx, 0.0f, nz, q});
        }
        idx.insert(idx.end(), {base, static_cast<uint16_t>(base + 2), static_cast<uint16_t>(base + 3), base, static_cast<uint16_t>(base + 3), static_cast<uint16_t>(base + 1)});
    };
    for (int r = 0; r + 1 < R; ++r) { skirt(r, 0, r + 1, 0, -1.0f, 0.0f); skirt(r, C - 1, r + 1, C - 1, 1.0f, 0.0f); }
    for (int c = 0; c + 1 < C; ++c) skirt(R - 1, c, R - 1, c + 1, 0.0f, 1.0f);
    std::vector<V> world(local.size());
    for (size_t i = 0; i < local.size(); ++i) {
        const L& l = local[i];
        const gta2::Vec3 p = PointBy(carToWorld, l.x, l.y, l.z);
        const float nx = l.nx * carToWorld.m[0][0] + l.ny * carToWorld.m[1][0] + l.nz * carToWorld.m[2][0];
        const float ny = l.nx * carToWorld.m[0][1] + l.ny * carToWorld.m[1][1] + l.nz * carToWorld.m[2][1];
        const float nz = l.nx * carToWorld.m[0][2] + l.ny * carToWorld.m[1][2] + l.nz * carToWorld.m[2][2];
        const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
        // the body's colour there: the texel, its paint share multiplied by the car's tint, the wear
        // FIX-COCKPIT-CAB-3 (qav12: the seat's bonnet 2-2.4x darker than the same body in third at dawn): the tint carries the
        // paint's lid-light gain (identity.cpp, ~2.7 at a low sun) and the body applies it after the light (model_store: stage 1
        // MODULATE2X, the tint up to 2); a vertex colour clamped at 1 before the light lost it on any pale paint. Half here,
        // doubled after the light below (the tint held at 2 as the body's). GTA2DX9_FP_BONNET_GAIN_OLD=1: the clamp (A/B).
        const size_t q = static_cast<size_t>(l.q);
        DWORD col = 0xff000000u;
        for (int k = 0; k < 3; ++k) {
            const float tk = gainOld ? tint[k] : (std::min)(2.0f, tint[k]);
            const float t = s.rgb[q * 3 + static_cast<size_t>(k)] * (1.0f + s.cov[q] * (paintLift - 1.0f)) * (1.0f + s.cov[q] * (tk - 1.0f)) * dull *
                            (gainOld ? 1.0f : 0.5f);
            col |= static_cast<DWORD>((std::max)(0.0f, (std::min)(1.0f, t)) * 255.0f + 0.5f) << (16 - 8 * k);
        }
        world[i] = {p.x, p.y, p.z, nl > 1e-6f ? nx / nl : 0.0f, nl > 1e-6f ? ny / nl : 1.0f, nl > 1e-6f ? nz / nl : 0.0f, col};
    }
    {   // FIX-COCKPIT-CAB-3 (qav12): the bonnet's light terms, once per surface, against the body's
        static const BonnetSurface* logged = nullptr;
        if (logged != &s) {
            logged = &s;
            double m[3] = {0, 0, 0}, w = 0;
            for (size_t q = 0; q < s.cov.size(); ++q) if (s.cov[q] > 0.5f) { for (int k = 0; k < 3; ++k) m[k] += s.rgb[q * 3 + k]; w += 1; }
            DWORD lighting = 0, l0 = 0; device->GetRenderState(D3DRS_LIGHTING, &lighting); device->GetLightEnable(0, reinterpret_cast<BOOL*>(&l0));
            D3DCOLORVALUE amb{}; DWORD ambient = 0; device->GetRenderState(D3DRS_AMBIENT, &ambient);
            (void)amb;
            Log("car bodies: seat bonnet light: tint %.2f,%.2f,%.2f dull %.2f, paint texels %.0f mean %.2f,%.2f,%.2f, body diffuse %.2f,%.2f,%.2f ambient %.2f,%.2f,%.2f emissive %.2f, lighting %lu light0 %lu ambient %08lx, %s",
                tint[0], tint[1], tint[2], dull, w, w ? m[0] / w : 0, w ? m[1] / w : 0, w ? m[2] / w : 0, body.Diffuse.r, body.Diffuse.g, body.Diffuse.b,
                body.Ambient.r, body.Ambient.g, body.Ambient.b, body.Emissive.r, lighting, l0, ambient, gainOld ? "clamped (old)" : "gain after the light");
        }
    }
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    if (remix) {
        IDirect3DTexture9* tex = BonnetTexture(device, s, tint, dull);
        if (!tex) return;
        struct VT { float x, y, z, nx, ny, nz, u, v; };
        std::vector<VT> tv(world.size());
        for (size_t i = 0; i < world.size(); ++i) {
            const int q = local[i].q;
            tv[i] = {world[i].x, world[i].y, world[i].z, world[i].nx, world[i].ny, world[i].nz,
                     (static_cast<float>(q % s.cols) + 0.5f) / static_cast<float>(g_bonnetTexW),
                     (static_cast<float>(q / s.cols) + 0.5f) / static_cast<float>(g_bonnetTexH)};
        }
        DWORD addrU = 0, addrV = 0;
        device->GetSamplerState(0, D3DSAMP_ADDRESSU, &addrU);
        device->GetSamplerState(0, D3DSAMP_ADDRESSV, &addrV);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device->SetMaterial(&body);
        device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
        device->SetTexture(0, tex);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
        device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(tv.size()), static_cast<UINT>(idx.size() / 3), idx.data(),
                                       D3DFMT_INDEX16, tv.data(), sizeof(VT));
        device->SetTexture(0, nullptr);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, addrU);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, addrV);
        device->SetMaterial(&restore);
        return;
    }
    // The body's own material (its dark-paint sheen and wear), the colour from the vertices.
    D3DMATERIAL9 m = body;
    device->SetMaterial(&m);
    DWORD colorVertex = 0, diffSrc = 0, ambSrc = 0;
    device->GetRenderState(D3DRS_COLORVERTEX, &colorVertex);
    device->GetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, &diffSrc);
    device->GetRenderState(D3DRS_AMBIENTMATERIALSOURCE, &ambSrc);
    device->SetRenderState(D3DRS_COLORVERTEX, TRUE);
    device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_COLOR1);
    device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_COLOR1);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTexture(0, nullptr);
    DWORD tfactor = 0;
    device->GetRenderState(D3DRS_TEXTUREFACTOR, &tfactor);
    device->SetRenderState(D3DRS_TEXTUREFACTOR, 0xFFFFFFFFu);
    device->SetTextureStageState(0, D3DTSS_COLOROP, gainOld ? D3DTOP_SELECTARG1 : D3DTOP_MODULATE2X);   // the half colour, doubled after the light
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_DIFFUSE);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(world.size()), static_cast<UINT>(idx.size() / 3), idx.data(),
                                   D3DFMT_INDEX16, world.data(), sizeof(V));
    device->SetRenderState(D3DRS_COLORVERTEX, colorVertex);
    device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, diffSrc);
    device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, ambSrc);
    device->SetRenderState(D3DRS_TEXTUREFACTOR, tfactor);
    device->SetMaterial(&restore);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
}

// Dents. The game keeps a damage word per vehicle (int16 at +0x74: 0 fresh, rising
// with every knock, on fire from 16000, burning hard from 25000, exploding at 32000;
// docs/actions-3d.md "Vehicle fields") and paints dents into the sprite; a
// model shows the same wear as a copy whose shell is pressed in by a smooth,
// low-frequency field (three octaves of value noise over the car's own frame)
// along normals smoothed across every seam, at most 2 % of the body length at
// the top step, with the normals recomputed afterwards. No vertex moves on its
// own, so nothing tears and nothing shows light through; the two paint-split
// halves share positions, so they move together. Cached per (model, step).
//
// PERF-3: the dented copies and the door splits below are built on a worker
// thread (WearThread), never on the render thread, where each cost 20-70 ms the
// first time a car reached a new dent step or opened a door. The render thread
// asks (DentReady / DoorReady), draws the previous dent step or the shut door
// until the copy is there, and registers finished copies with the model store at
// the start of the next cars stage. All four dent steps of a car model are
// queued (at low priority) the first time that model is drawn, so a crash
// normally finds its step already built.
struct DentKey {
    const Model* model; int step;
    bool operator<(const DentKey& o) const { return std::tie(model, step) < std::tie(o.model, o.step); }
};
std::map<DentKey, const Model*> g_dents;
constexpr int kDentSteps = 4;
// The four steps from the 16-bit damage: 4000, 8000, 16000 (the game sets the car
// alight) and 25000 (burning hard); a car under 4000 keeps its fresh shell.
int DentStepFor(int damage) {
    return damage >= 25000 ? 4 : damage >= 16000 ? 3 : damage >= 8000 ? 2 : damage >= 4000 ? 1 : 0;
}

uint32_t DentHash(int32_t x, int32_t y, int32_t z, uint32_t seed) {
    uint32_t h = static_cast<uint32_t>(x) * 73856093u ^ static_cast<uint32_t>(y) * 19349663u ^ static_cast<uint32_t>(z) * 83492791u ^ seed * 2654435761u;
    h ^= h >> 13; h *= 0x5bd1e995u; h ^= h >> 15;
    return h;
}
// Value noise in [0,1]: a hashed lattice, smoothstep interpolation.
float DentNoise(float x, float y, float z, uint32_t seed) {
    const float fx = std::floor(x), fy = std::floor(y), fz = std::floor(z);
    const int32_t ix = static_cast<int32_t>(fx), iy = static_cast<int32_t>(fy), iz = static_cast<int32_t>(fz);
    float tx = x - fx, ty = y - fy, tz = z - fz;
    tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty); tz = tz * tz * (3.0f - 2.0f * tz);
    auto at = [&](int dx, int dy, int dz) { return static_cast<float>(DentHash(ix + dx, iy + dy, iz + dz, seed) & 0xFFFF) / 65535.0f; };
    const float c00 = at(0, 0, 0) + (at(1, 0, 0) - at(0, 0, 0)) * tx, c10 = at(0, 1, 0) + (at(1, 1, 0) - at(0, 1, 0)) * tx;
    const float c01 = at(0, 0, 1) + (at(1, 0, 1) - at(0, 0, 1)) * tx, c11 = at(0, 1, 1) + (at(1, 1, 1) - at(0, 1, 1)) * tx;
    const float c0 = c00 + (c10 - c00) * ty, c1 = c01 + (c11 - c01) * ty;
    return c0 + (c1 - c0) * tz;
}

// Vertices keyed by their quantised position (hashed: the accumulation order per
// key is the vertex order either way, so the result is the same as an ordered map's).
struct PosKey {
    int32_t x, y, z;
    bool operator==(const PosKey& o) const { return x == o.x && y == o.y && z == o.z; }
};
struct PosKeyHash {
    size_t operator()(const PosKey& k) const {
        return static_cast<size_t>(static_cast<uint32_t>(k.x) * 73856093u ^ static_cast<uint32_t>(k.y) * 19349663u ^ static_cast<uint32_t>(k.z) * 83492791u);
    }
};

// The dented copy of `model` at `step`, built without touching anything shared
// (runs on the worker thread). `moved` gets the count of vertices pressed in.
Model BuildDented(const Model& model, int step, size_t* moved) {
    Model dented = model;
    dented.name = model.name + "#dent" + std::to_string(step);
    const float height = (std::max)(model.Height(), 0.05f);
    const float length = (std::max)(model.Length(), 0.05f);
    const float sill = model.boundsMin.y + 0.20f * height;
    const float amplitude = 0.02f * length * static_cast<float>(step) / static_cast<float>(kDentSteps);
    // Positions are shared by the paint-split halves and across mesh seams:
    // key every vertex by its quantised position, and smooth the normals over
    // that key before displacing, then rebuild them from the moved faces.
    auto keyOf = [&](const ModelVertex& v) {
        const float q = 2000.0f / length;
        return PosKey{static_cast<int32_t>(std::lround(v.x * q)), static_cast<int32_t>(std::lround(v.y * q)), static_cast<int32_t>(std::lround(v.z * q))};
    };
    size_t vertexCount = 0;
    for (const ModelMesh& mesh : dented.meshes) vertexCount += mesh.vertices.size();
    std::unordered_map<PosKey, gta2::Vec3, PosKeyHash> smooth;
    smooth.reserve(vertexCount);
    for (const ModelMesh& mesh : dented.meshes)
        for (const ModelVertex& v : mesh.vertices) {
            gta2::Vec3& n = smooth[keyOf(v)];
            n.x += v.nx; n.y += v.ny; n.z += v.nz;
        }
    for (auto& kv : smooth) {
        const float l = std::sqrt(gta2::Dot(kv.second, kv.second));
        if (l > 1e-8f) { kv.second.x /= l; kv.second.y /= l; kv.second.z /= l; }
    }
    *moved = 0;
    const uint32_t seed = static_cast<uint32_t>(std::hash<std::string>{}(model.name) & 0xFFFF);
    const float sx = 1.0f / (std::max)(model.Width(), 0.05f);
    for (ModelMesh& mesh : dented.meshes) {
        for (ModelVertex& v : mesh.vertices) {
            // Fade in above the sill so the sill is not a crease.
            const float wSill = (std::min)(1.0f, (std::max)(0.0f, (v.y - sill) / (0.12f * height)));
            if (wSill <= 0.0f) continue;
            const float px = v.x * sx, py = v.y / height, pz = v.z / length;   // -0.5..0.5 about the body
            float n = 0.60f * DentNoise(px * 2.6f, py * 2.0f, pz * 4.0f, seed)
                    + 0.28f * DentNoise(px * 5.2f + 3.1f, py * 4.0f, pz * 8.0f + 1.7f, seed + 1)
                    + 0.12f * DentNoise(px * 10.4f + 7.9f, py * 8.0f, pz * 16.0f + 5.3f, seed + 2);
            // Only the peaks dent: most of the shell stays as it was.
            const float f = (std::max)(0.0f, n - 0.42f) / 0.58f;
            if (f <= 0.0f) continue;
            const gta2::Vec3& sn = smooth[keyOf(v)];
            const float depth = amplitude * f * f * wSill;
            v.x -= sn.x * depth; v.y -= sn.y * depth; v.z -= sn.z * depth;
            ++*moved;
        }
    }
    // Normals from the moved faces, accumulated per shared position.
    std::unordered_map<PosKey, gta2::Vec3, PosKeyHash> rebuilt;
    rebuilt.reserve(vertexCount);
    for (const ModelMesh& mesh : dented.meshes) {
        for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
            const ModelVertex& a = mesh.vertices[mesh.indices[t]];
            const ModelVertex& b = mesh.vertices[mesh.indices[t + 1]];
            const ModelVertex& c = mesh.vertices[mesh.indices[t + 2]];
            const gta2::Vec3 e1{b.x - a.x, b.y - a.y, b.z - a.z}, e2{c.x - a.x, c.y - a.y, c.z - a.z};
            const gta2::Vec3 fn = gta2::Cross(e1, e2);
            for (const ModelVertex* v : {&a, &b, &c}) {
                gta2::Vec3& acc = rebuilt[keyOf(*v)];
                acc.x += fn.x; acc.y += fn.y; acc.z += fn.z;
            }
        }
    }
    for (ModelMesh& mesh : dented.meshes) {
        for (ModelVertex& v : mesh.vertices) {
            auto r = rebuilt.find(keyOf(v));
            if (r == rebuilt.end()) continue;
            const float l = std::sqrt(gta2::Dot(r->second, r->second));
            if (l <= 1e-10f) continue;
            // Keep the original facing where the rebuilt one disagrees (a flipped sliver).
            gta2::Vec3 nn{r->second.x / l, r->second.y / l, r->second.z / l};
            if (nn.x * v.nx + nn.y * v.ny + nn.z * v.nz < 0.0f) { nn.x = -nn.x; nn.y = -nn.y; nn.z = -nn.z; }
            v.nx = nn.x; v.ny = nn.y; v.nz = nn.z;
        }
    }
    return dented;
}

// Doors. A car's model is a sealed hull; when someone gets in or out the game
// draws the door open on the sprite, so the body copy here loses the door's
// panel (the outer skin between the windscreen base and a door's length back,
// on the boarding side) and that panel is drawn on its own, swung about its
// front edge. Both copies are cached per (model, side, position).
struct DoorKey {
    const Model* model; int side, zf, zr, exact;
    bool operator<(const DoorKey& o) const { return std::tie(model, side, zf, zr, exact) < std::tie(o.model, o.side, o.zf, o.zr, o.exact); }
};
struct DoorSplit { const Model* body; const Model* door; };
std::map<DoorKey, DoorSplit> g_doorSplits;

DoorKey DoorKeyFor(const Model& model, int side, float zFront, float zRear) {
    return DoorKey{&model, side, static_cast<int>(std::floor(zFront * 20.0f)), static_cast<int>(std::floor(zRear * 20.0f)), g_doorExactCut ? (g_doorTopCut ? 2 : 1) : 0};
}

// The split of `model` into the body without the door panel and the panel (with
// its inner face), built without touching anything shared (worker thread).
void BuildDoorSplit(const Model& model, const gta2::Mat4& fit, int side, float zFront, float zRear, float roof, float halfW,
                    int exactMode, Model* bodyOut, Model* doorOut, size_t* doorTrisOut) {
    const bool exactCut = exactMode != 0, topCut = exactMode == 2;   // DoorKey::exact: 0 old split, 1 exact, 2 exact + top
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model& body = *bodyOut;
    Model& door = *doorOut;
    for (Model* m : {&body, &door}) {
        m->nodes = model.nodes; m->forward = model.forward;
        m->boundsMin = model.boundsMin; m->boundsMax = model.boundsMax;
        for (int k = 0; k < 3; ++k) m->paintRgb[k] = model.paintRgb[k];
        m->splitPaint = model.splitPaint;
        m->meshes.resize(model.meshes.size());
    }
    body.name = model.name + "#nodoor"; door.name = model.name + "#door";
    size_t doorTris = 0;
    size_t clippedTris = 0, linerTris = 0, cutTris = 0;
    // FIX-SEAT-ENTRY-4 (pfl18): the door's top at the side wall's own top. A body whose side meets a
    // ribbed or stepped roof edge (the 068 van's corrugated roof) has the ribs' end caps, facing out, in
    // the box's top band up to 0.95 of the roof: they went with the door, so the swung door's top edge and
    // the hole's top were two rows of teeth (40 cm tall from the eye beside the van in first person).
    // On the van the side wall's skin runs evenly to exactly 0.95 of the roof, then a lip and the ribs: the
    // box's 1.5 cm margin above 0.95 reached them. The side skin's area per height band (faces turned out,
    // in the door's length) is measured; where the wall runs up to the old top, the box ends at the wall's
    // top with no margin: the cut is straight under the lip. [devtools] door_top_cut=0: the old box.
    constexpr float kDoorMargin = 0.015f;   // the box margin below (m)
    float boxTop = 0.95f * roof;
    bool topMeasured = false;
    if (topCut && roof > 1e-4f) {
        constexpr int kBands = 40;   // 0.5 .. 1.0 of the roof
        float area[kBands] = {};
        const float sg = static_cast<float>(side);
        for (size_t n = 0; n < model.nodes.size(); ++n) {
            const int mi = model.nodes[n].mesh;
            if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
            const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
            const gta2::Mat4 toCar = Mul(worlds[n], fit);
            for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
                gta2::Vec3 q[3];
                for (int c = 0; c < 3; ++c) {
                    const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                    q[c] = PointBy(toCar, v.x, v.y, v.z);
                }
                const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
                const float nl = std::sqrt(gta2::Dot(nrm, nrm));
                if (nl < 1e-9f || std::fabs(nrm.x) / nl < 0.45f) continue;
                const float cx = (q[0].x + q[1].x + q[2].x) / 3.0f, cz = (q[0].z + q[1].z + q[2].z) / 3.0f;
                if (sg * cx < 0.5f * halfW || cz < zRear || cz > zFront) continue;
                float y0 = (std::min)((std::min)(q[0].y, q[1].y), q[2].y), y1 = (std::max)((std::max)(q[0].y, q[1].y), q[2].y);
                const float a = 0.5f * std::fabs(nrm.x);
                const float span = (std::max)(y1 - y0, 1e-6f);
                for (int k = 0; k < kBands; ++k) {
                    const float b0 = (0.5f + 0.5f * k / kBands) * roof, b1 = (0.5f + 0.5f * (k + 1) / kBands) * roof;
                    const float o = (std::min)(y1, b1) - (std::max)(y0, b0);
                    if (o > 0.0f) area[k] += a * o / span;
                }
            }
        }
        // The wall's share: the median band between 0.5 and 0.8 of the roof. Up from 0.6 of the roof while
        // each band carries a wall's share (60..140 %): a lip or the ribs' caps end the run.
        std::vector<float> wall(area, area + kBands * 6 / 10);
        std::sort(wall.begin(), wall.end());
        const float ref = wall[wall.size() / 2];
        int k = kBands / 5;
        while (ref > 0.0f && k < kBands && area[k] >= 0.6f * ref && area[k] <= 1.4f * ref) ++k;
        const float wallTop = (0.5f + 0.5f * k / kBands) * roof;
        // Only where the wall runs up to the old top: the box's margin above it is what reached the ribs.
        // A body whose wall ends lower (a curved shoulder) keeps the old box.
        if (ref > 0.0f && wallTop >= 0.90f * roof && wallTop <= 0.95f * roof + 1e-4f) { boxTop = wallTop - kDoorMargin; topMeasured = true; }
        if (topMeasured)
            Log("car bodies: door of %s, side %d: top at the side wall's top, %.3f of the roof (was 0.95 + margin)", model.name.c_str(), side, (boxTop + kDoorMargin) / roof);
    }
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& db = body.meshes[static_cast<size_t>(mi)];
        ModelMesh& dd = door.meshes[static_cast<size_t>(mi)];
        db.vertices = src.vertices; db.texture = src.texture; db.skin = -1;
        dd.vertices = src.vertices; dd.texture = src.texture; dd.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            gta2::Vec3 q[3];
            float cx = 0.0f, cy = 0.0f, cz = 0.0f;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                cx += q[c].x; cy += q[c].y; cz += q[c].z;
            }
            cx /= 3.0f; cy /= 3.0f; cz /= 3.0f;
            const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
            const float nl = std::sqrt(gta2::Dot(nrm, nrm));
            const bool lateral = nl > 1e-9f && std::fabs(nrm.x) / nl > 0.45f;
            const float m = 0.015f, sgn = static_cast<float>(side);
            auto inside = [&](const gta2::Vec3& p) {
                return sgn * p.x >= 0.5f * halfW - m && p.y >= 0.10f * roof - m && p.y <= boxTop + m &&
                       p.z >= zRear - m && p.z <= zFront + m;
            };
            const bool in0 = inside(q[0]), in1 = inside(q[1]), in2 = inside(q[2]);
            const bool centred = static_cast<float>(side) * cx > 0.5f * halfW && cy > 0.10f * roof && cy < boxTop &&
                                 cz > zRear && cz < zFront;
            // FIX-SEAT-ENTRY-3 (pfl16 van entry): a side triangle that crosses the door's outline is cut
            // along it, not only its centroid's piece given to the door (g_doorExactCut, [devtools]
            // door_exact_cut=0 for the old split). The old body kept such triangles whole, so the hole
            // the open door left ended in the hull's triangle edges: on the 068 van a row of teeth down
            // the door's rear edge and along the roof line, with the dark cabin behind them.
            // How far the triangle faces out of this side, by its vertex normals (an image-to-3D shell
            // has faces wound either way): 1 straight out, -1 into the cabin (a liner).
            float outward = 0.0f;
            {
                float nxSum = 0.0f;
                for (int c = 0; c < 3; ++c) {
                    const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                    nxSum += v.nx * toCar.m[0][0] + v.ny * toCar.m[1][0] + v.nz * toCar.m[2][0];
                }
                outward = static_cast<float>(side) * nxSum / (3.0f * (std::max)(1e-6f, std::fabs(toCar.m[0][0]) + std::fabs(toCar.m[2][0])));
            }
            // Exact cut: the panel is every outward-facing face in the box, not only the steep ones; the
            // roof shoulder's faces between steep and flat left a second row of teeth along the door's top.
            const bool sideFace = lateral || (exactCut && outward > 0.05f);
            const bool crosses = exactCut && sideFace && !(in0 && in1 && in2) && (in0 || in1 || in2 || centred);
            const bool isDoor = sideFace && (centred || crosses);
            // VEHICLE-ART-4 (feel19): an authored body's cabin liner (its normals into the cabin, a
            // near-black interior texture: 188 of the 068 van's door faces) lay in the door's box and
            // swung out with it: the open door, seen from inside, was a flat black slab. Those faces go
            // with neither piece while the door is open: the door shows its own skin from inside (the
            // inner copy below, painted and lit as the panel), the opening the cabin behind it. By the
            // vertex normals, not the winding (an image-to-3D shell has faces wound either way).
            bool liner = false;
            if (isDoor) {
                liner = outward < -0.3f;
                if (liner && !crosses) { ++linerTris; continue; }
            }
            // ANIM-ENTRY-EXIT: the image-to-3D shells have long thin triangles whose centroid lies
            // on the door while a corner reaches the sill, the wheel arch or the road. Swung whole
            // with the door they hung below it as black shards that crossed the person getting out
            // (aee_base1, aee_v1b); left on the body the door had holes the arm behind showed
            // through (aee_i2front); corners pulled onto the box left gaps too (aee_j2front). Such
            // a triangle is clipped to the door's box (1.5 cm margin, car frame): the door gets
            // exactly its part inside. FIX-SEAT-ENTRY-3: the body gets exactly its part outside
            // (before, it kept the triangle whole: the teeth above); a liner's inside part goes to neither.
            if (isDoor && !(in0 && in1 && in2)) {
                struct CV { gta2::Vec3 p; ModelVertex v; };
                std::vector<CV> poly, next, outPart;
                for (int c = 0; c < 3; ++c) poly.push_back({q[c], src.vertices[src.indices[t + static_cast<size_t>(c)]]});
                // Planes as (signed distance >= 0 inside): sgn*x - (0.5 hw - m), y - lo, hi - y, z - zr, zf - z.
                auto dist = [&](int plane, const gta2::Vec3& p) {
                    switch (plane) {
                        case 0: return sgn * p.x - (0.5f * halfW - m);
                        case 1: return p.y - (0.10f * roof - m);
                        case 2: return (boxTop + m) - p.y;
                        case 3: return p.z - (zRear - m);
                        default: return (zFront + m) - p.z;
                    }
                };
                auto lerpV = [](const ModelVertex& a, const ModelVertex& b, float k) {
                    ModelVertex r;
                    r.x = a.x + (b.x - a.x) * k; r.y = a.y + (b.y - a.y) * k; r.z = a.z + (b.z - a.z) * k;
                    r.nx = a.nx + (b.nx - a.nx) * k; r.ny = a.ny + (b.ny - a.ny) * k; r.nz = a.nz + (b.nz - a.nz) * k;
                    r.u = a.u + (b.u - a.u) * k; r.v = a.v + (b.v - a.v) * k;
                    return r;
                };
                // Sutherland-Hodgman against one plane, keeping sign * dist >= 0.
                auto clip = [&](const std::vector<CV>& in, int plane, float sign, std::vector<CV>* out) {
                    out->clear();
                    for (size_t i = 0; i < in.size(); ++i) {
                        const CV& A = in[i];
                        const CV& B = in[(i + 1) % in.size()];
                        const float da = sign * dist(plane, A.p), dbb = sign * dist(plane, B.p);
                        if (da >= 0.0f) out->push_back(A);
                        if ((da >= 0.0f) != (dbb >= 0.0f)) {
                            const float k = da / (da - dbb);
                            out->push_back({A.p + (B.p - A.p) * k, lerpV(A.v, B.v, k)});
                        }
                    }
                };
                auto emit = [&](ModelMesh& mesh, const std::vector<CV>& pg, bool countDoor) {
                    if (pg.size() < 3) return;
                    const uint32_t base = static_cast<uint32_t>(mesh.vertices.size());
                    for (const CV& cv : pg) mesh.vertices.push_back(cv.v);
                    for (size_t i = 1; i + 1 < pg.size(); ++i) {
                        // Same winding as the source triangle (the clip keeps the polygon's order).
                        mesh.indices.push_back(base); mesh.indices.push_back(base + static_cast<uint32_t>(i));
                        mesh.indices.push_back(base + static_cast<uint32_t>(i + 1));
                        if (countDoor) ++doorTris;
                    }
                };
                const bool exact = crosses;
                for (int plane = 0; plane < 5 && poly.size() >= 3; ++plane) {
                    // The part beyond this plane (and inside the planes before it) is outside the box: the body's.
                    if (exact) { clip(poly, plane, -1.0f, &outPart); emit(db, outPart, false); }
                    clip(poly, plane, 1.0f, &next);
                    poly.swap(next);
                }
                if (liner) ++linerTris;
                else if (poly.size() >= 3) { emit(dd, poly, true); ++clippedTris; }
                if (!exact) { db.indices.push_back(src.indices[t]); db.indices.push_back(src.indices[t + 1]); db.indices.push_back(src.indices[t + 2]); }
                else ++cutTris;
                continue;
            }
            ModelMesh& dst = isDoor ? dd : db;
            dst.indices.push_back(src.indices[t]); dst.indices.push_back(src.indices[t + 1]); dst.indices.push_back(src.indices[t + 2]);
            if (isDoor) ++doorTris;
        }
    }
    // The door keeps only the vertices its triangles use (PERF-3: a full copy of
    // the hull's vertices per door was most of a split's memory).
    for (ModelMesh& mesh : door.meshes) {
        if (mesh.indices.empty()) { mesh.vertices.clear(); continue; }
        std::vector<uint32_t> remap(mesh.vertices.size(), UINT32_MAX);
        std::vector<ModelVertex> used;
        for (uint32_t& index : mesh.indices) {
            if (remap[index] == UINT32_MAX) { remap[index] = static_cast<uint32_t>(used.size()); used.push_back(mesh.vertices[index]); }
            index = remap[index];
        }
        mesh.vertices.swap(used);
    }
    // The door's inner face is seen once it swings out: the same triangles again,
    // wound the other way with their normals flipped, so the inside is lit too.
    for (ModelMesh& mesh : door.meshes) {
        if (mesh.indices.empty()) continue;
        const uint32_t base = static_cast<uint32_t>(mesh.vertices.size());
        std::vector<ModelVertex> inner = mesh.vertices;
        // Normals kept as the outer skin's: the inside of a swung door takes the
        // same light as the panel, not the dark of a face turned from the sun.
        mesh.vertices.insert(mesh.vertices.end(), inner.begin(), inner.end());
        const size_t n = mesh.indices.size();
        for (size_t t = 0; t + 2 < n; t += 3) {
            mesh.indices.push_back(base + mesh.indices[t + 2]);
            mesh.indices.push_back(base + mesh.indices[t + 1]);
            mesh.indices.push_back(base + mesh.indices[t]);
        }
    }
    if (clippedTris) Log("car bodies: door of %s, side %d: %zu triangles clipped to the door's outline (%zu cut along it, body keeps the outside)", model.name.c_str(), side, clippedTris, cutTris);
    if (linerTris) Log("car bodies: door of %s, side %d: %zu cabin-liner triangles left out while it is open", model.name.c_str(), side, linerTris);
    *doorTrisOut = doorTris;
}

// Wheels (VEHICLE-FEEL). A car model is one sealed shell with its wheels in it, so the
// wheels are cut out of it the way the door is: every triangle that lies wholly inside
// a wheel's disc (the wheel-arch bounds: a circle of the tyre's radius about the axle,
// on the outer part of that side) goes to that wheel, the rest is the hull. The
// parametric models carry their wheel centres as marker nodes (wheel_fl, ...); for the
// image-to-3D shells the axles come from the CARI wheel rows, refined by where the
// shell touches the road, and the radius from the body's height. Each wheel then turns
// about its own axle and the front pair steers.
struct WheelKey {
    const Model* model; int zf, zr, hw;
    int shellMode = 1;   // VEHICLE-ART-5 [devtools] shell_wheels: 1 hub only for marker-less shells, 0 the whole guessed wheel
    bool operator<(const WheelKey& o) const { return std::tie(model, zf, zr, hw, shellMode) < std::tie(o.model, o.zf, o.zr, o.hw, o.shellMode); }
};
int g_shellWheels = 1;
int g_forceSteerDeg = 0;   // VEHICLE-ART-6 [devtools] force_steer_deg=N: every car's front wheels at N degrees (probe frames of a stopped car)
constexpr int kMaxWheels = 6;
struct WheelSplit {
    const Model* hull = nullptr;   // null: the model has no wheels to cut (drawn whole)
    int n = 0;
    const Model* wheel[kMaxWheels] = {};
    const Model* ring[kMaxWheels] = {};   // VEHICLE-ART-6: a shell's tyre ring (steers, never spins); null for marker bodies
    gta2::Vec3 centre[kMaxWheels];
    float radius[kMaxWheels] = {};
    bool shell = false;   // a marker-less shell's hubs: they spin in the hull's own frame (see BuildWheelSplit)
};
std::map<WheelKey, WheelSplit> g_wheelSplits;
WheelKey WheelKeyFor(const Model& model, float zF, float zR, float halfW) {
    return WheelKey{&model, static_cast<int>(std::floor(zF * 20.0f)), static_cast<int>(std::floor(zR * 20.0f)), static_cast<int>(std::floor(halfW * 40.0f)),
                    g_shellWheels};
}

// VEHICLE-ART-6: a shell texture's paint share and opaque luminance at 128 x 128 cells, for the
// worker thread only (BuildWheelSplit; RgbFor's cache belongs to the render thread). The split
// image-to-3D bodies leave the base texture see-through where its "_paint" twin is paint.
struct ShellTexels { int n = 0; std::vector<float> paint, lum; };
const ShellTexels* ShellTexelsFor(const std::string& texture) {
    static std::map<std::string, ShellTexels> cache;
    std::string base = texture;
    const size_t pp = base.find("_paint");
    if (pp != std::string::npos) base.erase(pp, 6);
    auto it = cache.find(base);
    if (it != cache.end()) return it->second.n ? &it->second : nullptr;
    if (cache.size() > 64) cache.clear();
    ShellTexels& m = cache[base];
    FILE* f = std::fopen((std::string(ModelsFolder()) + "\\" + base).c_str(), "rb");
    if (!f) return nullptr;
    std::vector<uint8_t> tga;
    uint8_t buf[65536];
    size_t got;
    while ((got = std::fread(buf, 1, sizeof(buf), f)) > 0) tga.insert(tga.end(), buf, buf + got);
    std::fclose(f);
    if (tga.size() <= 18 || tga[2] != 2 || tga[16] != 32) return nullptr;
    const int w = tga[12] | (tga[13] << 8), h = tga[14] | (tga[15] << 8);
    if (w <= 0 || h <= 0 || tga.size() < 18u + static_cast<size_t>(w) * h * 4) return nullptr;
    const bool topDown = (tga[17] & 0x20) != 0;
    constexpr int kN = 128;
    std::vector<float> as(kN * kN, 0.0f), ls(kN * kN, 0.0f), cnt(kN * kN, 0.0f);
    for (int y = 0; y < h; ++y) {
        const uint8_t* row = &tga[18 + static_cast<size_t>(topDown ? y : (h - 1 - y)) * w * 4];
        const int cy = y * kN / h;
        for (int x = 0; x < w; ++x) {
            const uint8_t* px = row + x * 4;
            const int c = cy * kN + x * kN / w;
            as[c] += px[3];
            ls[c] += (0.2126f * px[2] + 0.7152f * px[1] + 0.0722f * px[0]) * px[3];
            cnt[c] += 1.0f;
        }
    }
    m.n = kN; m.paint.resize(kN * kN); m.lum.resize(kN * kN);
    for (int i = 0; i < kN * kN; ++i) {
        m.paint[i] = cnt[i] > 0 ? 1.0f - as[i] / (255.0f * cnt[i]) : 1.0f;
        m.lum[i] = as[i] > 0 ? ls[i] / (255.0f * as[i]) : 0.5f;
    }
    return &m;
}

void BuildWheelSplit(const Model& model, const gta2::Mat4& fit, float zF, float zR, float halfW, float roof, int shellMode,
                     Model* hullOut, std::vector<Model>* wheelsOut, std::vector<gta2::Vec3>* centresOut, std::vector<float>* radiiOut,
                     bool* shellOut, std::vector<Model>* ringsOut) {
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    struct Wheel { gta2::Vec3 c; float r; float xin; };
    std::vector<Wheel> wheels;
    // Marker nodes first (the parametric bodies and the wrecks).
    for (size_t n = 0; n < model.nodes.size() && wheels.size() < static_cast<size_t>(kMaxWheels); ++n) {
        if (strncmp(model.nodes[n].name, "wheel_", 6) != 0) continue;
        const gta2::Vec3 c = PointBy(Mul(worlds[n], fit), 0.0f, 0.0f, 0.0f);
        const float r = (std::max)(0.03f, c.y);
        wheels.push_back(Wheel{c, r, (std::max)(0.25f * halfW, std::fabs(c.x) - 1.2f * r)});
    }
    // VEHICLE-ART-5 (pm-van 5h, pm2 5i): a marker-less shell's wheel circle is a guess from the CARI axle and
    // the body's height; the whole disc cut from it took the arch lips and fender skirts with the wheel
    // (crescents, a skirt hanging off the turning wheel) and left tread on the sprung hull (black shards
    // beside it). For those only the hub turns: the faces within half the radius, kept in the hull as well
    // (so its edge can never open a hole), drawn spinning in the hull's own frame a hair outboard.
    const bool shell = wheels.empty() && shellMode == 1;
    *shellOut = shell;
    if (wheels.empty()) {
        // The shell: where it touches the road, near each CARI axle.
        float minY = 1e9f;
        std::vector<gta2::Vec3> pts;
        for (size_t n = 0; n < model.nodes.size(); ++n) {
            const int mi = model.nodes[n].mesh;
            if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
            const gta2::Mat4 toCar = Mul(worlds[n], fit);
            for (const ModelVertex& v : model.meshes[static_cast<size_t>(mi)].vertices) {
                const gta2::Vec3 q = PointBy(toCar, v.x, v.y, v.z);
                pts.push_back(q);
                minY = (std::min)(minY, q.y);
            }
        }
        const float r = (std::max)(0.055f, (std::min)(0.13f, 0.21f * roof));
        const float mid = 0.5f * (zF + zR);
        float sum[2] = {0, 0}; int cnt[2] = {0, 0};
        for (const gta2::Vec3& q : pts) {
            if (q.y > minY + 0.02f) continue;
            const int k = q.z > mid ? 0 : 1;
            const float hint = k ? zR : zF;
            if (std::fabs(q.z - hint) > 2.0f * r) continue;
            sum[k] += q.z; ++cnt[k];
        }
        const float zc[2] = {cnt[0] >= 3 ? sum[0] / cnt[0] : zF, cnt[1] >= 3 ? sum[1] / cnt[1] : zR};
        for (int k = 0; k < 2; ++k) {
            for (int side = -1; side <= 1; side += 2) {
                float outer = 0.0f;
                for (const gta2::Vec3& q : pts) {
                    if (q.y < minY + 1.6f * r && std::fabs(q.z - zc[k]) < 0.8f * r) outer = (std::max)(outer, static_cast<float>(side) * q.x);
                }
                if (outer < 0.3f * halfW) outer = 0.85f * halfW;
                const gta2::Vec3 c{static_cast<float>(side) * (outer - 0.3f * r), minY + r, zc[k]};
                wheels.push_back(Wheel{c, r, (std::max)(0.35f * halfW, outer - 0.9f * r)});
            }
        }
    }
    Model& hull = *hullOut;
    hull.nodes = model.nodes; hull.forward = model.forward;
    hull.boundsMin = model.boundsMin; hull.boundsMax = model.boundsMax;
    for (int k = 0; k < 3; ++k) hull.paintRgb[k] = model.paintRgb[k];
    hull.splitPaint = model.splitPaint;
    hull.meshes.resize(model.meshes.size());
    hull.name = model.name + "#nowheels";
    std::vector<Model> parts(wheels.size()), rings(wheels.size());
    for (size_t w = 0; w < parts.size(); ++w) {
        Model& m = parts[w];
        m.nodes = model.nodes; m.forward = model.forward;
        m.boundsMin = model.boundsMin; m.boundsMax = model.boundsMax;
        for (int k = 0; k < 3; ++k) m.paintRgb[k] = model.paintRgb[k];
        m.splitPaint = model.splitPaint;
        m.meshes.resize(model.meshes.size());
        m.name = model.name + "#wheel" + std::to_string(w);
        rings[w] = m;
        rings[w].name = model.name + "#ring" + std::to_string(w);
    }
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& hm = hull.meshes[static_cast<size_t>(mi)];
        hm.vertices = src.vertices; hm.texture = src.texture; hm.skin = -1;
        for (Model& m : parts) { m.meshes[static_cast<size_t>(mi)].vertices = src.vertices; m.meshes[static_cast<size_t>(mi)].texture = src.texture; m.meshes[static_cast<size_t>(mi)].skin = -1; }
        if (shell) for (Model& m : rings) { m.meshes[static_cast<size_t>(mi)].vertices = src.vertices; m.meshes[static_cast<size_t>(mi)].texture = src.texture; m.meshes[static_cast<size_t>(mi)].skin = -1; }
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        std::vector<gta2::Vec3> q(src.vertices.size());
        for (size_t i = 0; i < src.vertices.size(); ++i) q[i] = PointBy(toCar, src.vertices[i].x, src.vertices[i].y, src.vertices[i].z);
        const ShellTexels* tex = shell ? ShellTexelsFor(src.texture) : nullptr;
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            int owner = -1;
            bool ringFace = false;
            for (size_t w = 0; w < wheels.size() && owner < 0; ++w) {
                const Wheel& wh = wheels[w];
                const float side = wh.c.x >= 0.0f ? 1.0f : -1.0f;
                // VEHICLE-ART-6: a shell's wheel is its tyre and hub: the faces in the disc that are not
                // body paint (the arch lips and fender skirts that crossed the guessed circle are paint
                // and stay on the hull), so the front pair steers again (4201906 spun only the hubs).
                const float rr = (shell ? 0.98f : 1.06f) * wh.r;
                bool in = true;
                float dmax = 0.0f;
                for (int c = 0; c < 3 && in; ++c) {
                    const gta2::Vec3& p = q[src.indices[t + static_cast<size_t>(c)]];
                    const float dy = p.y - wh.c.y, dz = p.z - wh.c.z;
                    const float d2 = dy * dy + dz * dz;
                    dmax = (std::max)(dmax, d2);
                    in = side * p.x > wh.xin && d2 < rr * rr;
                }
                if (in && shell && dmax > 0.25f * wh.r * wh.r) {
                    // outside the hub: tyre only (not paint, and dark unless it is the whitewall/hubcap ring)
                    float paint = 0.0f, lum = 0.0f;
                    if (tex) {
                        for (int c = 0; c < 4; ++c) {
                            float u = 0.0f, v = 0.0f;
                            if (c < 3) { u = src.vertices[src.indices[t + c]].u; v = src.vertices[src.indices[t + c]].v; }
                            else for (int k = 0; k < 3; ++k) { u += src.vertices[src.indices[t + k]].u / 3.0f; v += src.vertices[src.indices[t + k]].v / 3.0f; }
                            const float uu = u - std::floor(u), vv = v - std::floor(v);
                            const int i = (std::min)(tex->n - 1, static_cast<int>(vv * tex->n)) * tex->n + (std::min)(tex->n - 1, static_cast<int>(uu * tex->n));
                            paint += 0.25f * tex->paint[static_cast<size_t>(i)];
                            lum += 0.25f * tex->lum[static_cast<size_t>(i)];
                        }
                    }
                    const bool ring = dmax < 0.64f * wh.r * wh.r;   // within 0.8 r: hubcap / whitewall
                    in = tex && paint < 0.35f && (lum < 0.30f || ring);
                    ringFace = in;
                }
                if (in) owner = static_cast<int>(w);
            }
            ModelMesh& dst = owner < 0 ? hm : (ringFace ? rings : parts)[static_cast<size_t>(owner)].meshes[static_cast<size_t>(mi)];
            dst.indices.push_back(src.indices[t]); dst.indices.push_back(src.indices[t + 1]); dst.indices.push_back(src.indices[t + 2]);
            if (shell && owner >= 0) { hm.indices.push_back(src.indices[t]); hm.indices.push_back(src.indices[t + 1]); hm.indices.push_back(src.indices[t + 2]); }
        }
    }
    // Each wheel keeps only the vertices it uses; a wheel with nothing in it is dropped.
    auto compact = [](Model& m) {
        size_t tris = 0;
        for (ModelMesh& mesh : m.meshes) {
            if (mesh.indices.empty()) { mesh.vertices.clear(); continue; }
            std::vector<uint32_t> remap(mesh.vertices.size(), UINT32_MAX);
            std::vector<ModelVertex> used;
            for (uint32_t& index : mesh.indices) {
                if (remap[index] == UINT32_MAX) { remap[index] = static_cast<uint32_t>(used.size()); used.push_back(mesh.vertices[index]); }
                index = remap[index];
            }
            mesh.vertices.swap(used);
            tris += mesh.indices.size() / 3;
        }
        return tris;
    };
    for (size_t w = 0; w < parts.size(); ++w) {
        const size_t tris = compact(parts[w]);
        const size_t ringTris = shell ? compact(rings[w]) : 0;
        if (tris + ringTris < 4) continue;
        ringsOut->push_back(std::move(rings[w]));
        wheelsOut->push_back(std::move(parts[w]));
        centresOut->push_back(wheels[w].c);
        radiiOut->push_back(wheels[w].r);
    }
}

// The worker. Jobs come in two queues (urgent: a car on screen wants it now;
// idle: the dent steps of a model seen, built ahead) and finished copies wait in
// g_wearDone until the render thread registers them (WearCollect).
struct WearJob {
    bool door = false;
    bool wheels = false;                // a wheel split (VEHICLE-FEEL); `door` is false then
    bool bonnet = false;                // FIX-PERF-3: the seat bonnet of the player's car, ahead of the seat view
    BonnetSurfKey bkey{};
    float windscreen = 0, ceiling = 0;
    WheelKey wkey{};
    const Model* model = nullptr;
    int step = 0;                       // dent
    DoorKey key{};                      // door
    gta2::Mat4 fit;
    int side = 1;
    float zFront = 0, zRear = 0, roof = 0, halfW = 0;
};
struct WearResult {
    WearJob job;
    Model a, b;                         // dented copy | body without the door, and the door
    size_t count = 0;                   // vertices moved | door triangles
    double ms = 0.0;
    std::vector<Model> wheels;          // a wheel split: the hull is `a`
    std::vector<Model> rings;           // VEHICLE-ART-6: a shell's tyre rings, one per wheel (may be empty)
    std::vector<gta2::Vec3> centres;
    std::vector<float> radii;
    bool shell = false;
    BonnetSurface bonnet;
};
CRITICAL_SECTION g_wearLock;
HANDLE g_wearWake = nullptr;
bool g_wearStarted = false, g_wearFailed = false;
std::deque<WearJob> g_wearUrgent, g_wearIdle;      // under g_wearLock
std::vector<WearResult*> g_wearDone;               // under g_wearLock
// Render thread only: what has been asked for and not collected yet, the models
// whose dent steps were queued ahead, and what the copies hold.
std::set<DentKey> g_dentAsked;
std::set<DoorKey> g_doorAsked;
std::set<WheelKey> g_wheelAsked;
std::set<BonnetSurfKey> g_bonnetAsked;   // FIX-PERF-3: seat bonnets on the worker
size_t g_wheelBytes = 0;
int g_wheelLate = 0;
// Wheel splits are per (model, dent step, sprite footprint); past this much memory no
// new one is made and the car is drawn whole (its wheels do not turn).
constexpr size_t kWheelSplitBytes = 64u << 20;
std::set<const Model*> g_dentQueued;
size_t g_wearBytes = 0, g_dentBytes = 0, g_doorBytes = 0;
int g_wearCollected = 0, g_dentLate = 0, g_doorLate = 0;
double g_wearWorkMs = 0.0;
// Ahead-of-need dent copies stop being queued past this much memory (the
// urgent ones are always built). 68 car models x 4 steps would be ~125 MB.
// FIX-PERF-4: 160 -> 48 MB. The ahead copies were ~100 MB of a 32-bit process's address space
// by minute 6 of a session, most never shown; a model past the budget gets its step built when
// a car of it is first dented (the previous step shows for the frames the worker takes).
constexpr size_t kDentAheadBytes = 48u << 20;
// Door splits are per (model, dent step, side, sprite); past this much memory the
// dented ones are no longer made (see the door in CarBodiesDraw).
constexpr size_t kDoorSplitBytes = 64u << 20;

// A copy's first draw creates its vertex and index buffers (dynamic, default pool, see
// ModelRegisterDerived): cheap alone, but a forced door on every car in view finished a
// dozen copies at once, and twelve buffer creations in one frame cost 170 ms on a busy
// host (p3_fin4_wil). One new copy a frame goes on screen; the rest wait a frame or two
// with the previous step or the shut door.
std::set<const Model*> g_wearShown;
uint32_t g_wearShowFrame = 0;
int g_wearBuffersLeft = 0;
// FIX-PERF-3: one copy a frame was not enough: a wheel split is a hull and four wheels of up to 21 meshes
// each (008 Bug), and the first V of the owner's demo created 33-58 vertex buffers a frame for them
// (demo_rc3t f673-674). A copy (with its siblings) goes on screen once all its buffers exist, made at
// most kWearBuffersPerFrame meshes a frame; the car is drawn as it was until then.
constexpr int kWearBuffersPerFrame = 4;
bool WearMayShow(const Model* const* copies, size_t n, uint32_t frame) {
    bool shown = true;
    for (size_t i = 0; i < n; ++i) shown = shown && (!copies[i] || g_wearShown.count(copies[i]));
    if (shown) return true;
    if (frame != g_wearShowFrame) { g_wearShowFrame = frame; g_wearBuffersLeft = kWearBuffersPerFrame; }
    if (g_wearBuffersLeft <= 0 || !g_device) return false;
    for (size_t i = 0; i < n; ++i) {
        if (!copies[i]) continue;
        int made = 0;
        const bool ready = ModelPrepareBuffers(g_device, *copies[i], g_wearBuffersLeft, &made);
        g_wearBuffersLeft -= made;
        if (!ready) return false;
    }
    for (size_t i = 0; i < n; ++i) if (copies[i]) g_wearShown.insert(copies[i]);
    return true;
}
bool WearMayShow(std::initializer_list<const Model*> copies, uint32_t frame) { return WearMayShow(copies.begin(), copies.size(), frame); }
uint32_t g_wearFrame = 0;   // the cars stage's frame, for WearMayShow

size_t ModelBytes(const Model& m) {
    size_t n = sizeof(Model) + m.nodes.size() * sizeof(ModelNode);
    for (const ModelMesh& mesh : m.meshes) n += sizeof(ModelMesh) + mesh.vertices.size() * sizeof(ModelVertex) + mesh.indices.size() * sizeof(uint32_t);
    return n;
}

DWORD WINAPI WearThread(void*) {
    NameThisThread("wear");
    for (;;) {
        WearJob job;
        bool have = false, ahead = false;
        EnterCriticalSection(&g_wearLock);
        if (!g_wearUrgent.empty()) { job = g_wearUrgent.front(); g_wearUrgent.pop_front(); have = true; }
        else if (!g_wearIdle.empty()) { job = g_wearIdle.front(); g_wearIdle.pop_front(); have = true; ahead = true; }
        LeaveCriticalSection(&g_wearLock);
        if (!have) { WaitForSingleObject(g_wearWake, 200); continue; }
        WearResult* r = new WearResult;
        r->job = job;
        const double t0 = CarNowMs();
        if (job.bonnet) {
            BuildBonnetSurface(*job.model, job.fit, job.windscreen, job.ceiling, r->bonnet);
            ModelTextureSampleWarm(*job.model);   // the hood dash's texture samples (HoodDashFor)
        } else if (job.wheels) BuildWheelSplit(*job.model, job.fit, job.zFront, job.zRear, job.halfW, job.roof, job.wkey.shellMode, &r->a, &r->wheels, &r->centres, &r->radii, &r->shell, &r->rings);
        else if (!job.door) r->a = BuildDented(*job.model, job.step, &r->count);
        else BuildDoorSplit(*job.model, job.fit, job.side, job.zFront, job.zRear, job.roof, job.halfW, job.key.exact, &r->a, &r->b, &r->count);
        r->ms = CarNowMs() - t0;
        const double ms = r->ms;
        EnterCriticalSection(&g_wearLock);
        g_wearDone.push_back(r);
        LeaveCriticalSection(&g_wearLock);
        // Work ahead of need takes at most half of one CPU: the play container has
        // three, shared with the game's own thread, Wine's and the VNC encoder.
        if (ahead) Sleep(static_cast<DWORD>((std::max)(5.0, ms)));
    }
}

bool WearStart() {
    if (g_wearStarted) return true;
    if (g_wearFailed) return false;
    InitializeCriticalSection(&g_wearLock);
    g_wearWake = CreateEventA(nullptr, FALSE, FALSE, nullptr);
    HANDLE thread = g_wearWake ? CreateThread(nullptr, 0, WearThread, nullptr, 0, nullptr) : nullptr;
    if (!thread) {
        g_wearFailed = true;
        Log("car bodies: no wear thread; dents and door splits are built on the render thread");
        return false;
    }
    SetThreadPriority(thread, THREAD_PRIORITY_LOWEST);
    CloseHandle(thread);
    g_wearStarted = true;
    Log("car bodies: dents and door splits are built on a thread of their own");
    return true;
}

void WearPush(const WearJob& job, bool urgent) {
    EnterCriticalSection(&g_wearLock);
    if (urgent) g_wearUrgent.push_back(job); else g_wearIdle.push_back(job);
    LeaveCriticalSection(&g_wearLock);
    SetEvent(g_wearWake);
}

// Finished copies into the model store and the caches (render thread, the start
// of every cars stage; a move each, no copying).
void WearCollect() {
    if (!g_wearStarted) return;
    // At most ~2 ms of it a frame (each copy is a log line and a few set inserts; a
    // forced door on every car in view finishes a dozen at once): the rest wait.
    std::vector<WearResult*> done;
    const double t0 = CarNowMs();
    EnterCriticalSection(&g_wearLock);
    done.swap(g_wearDone);
    LeaveCriticalSection(&g_wearLock);
    for (size_t i = 0; i < done.size(); ++i) {
        if (i > 0 && CarNowMs() - t0 > 2.0) {
            EnterCriticalSection(&g_wearLock);
            g_wearDone.insert(g_wearDone.begin(), done.begin() + static_cast<std::ptrdiff_t>(i), done.end());
            LeaveCriticalSection(&g_wearLock);
            break;
        }
        WearResult* r = done[i];
        ++g_wearCollected;
        g_wearWorkMs += r->ms;
        if (r->job.bonnet) {
            g_bonnetAsked.erase(r->job.bkey);
            if (!g_bonnetSurfs.count(r->job.bkey)) {
                if (g_bonnetSurfs.size() > 64) g_bonnetSurfs.clear();
                g_bonnetSurfs[r->job.bkey] = std::move(r->bonnet);
            }
            Log("car bodies: seat bonnet of %s made ahead of the seat view (worker %.1f ms, with its texture samples)", r->job.model->name.c_str(), r->ms);
        } else if (r->job.wheels) {
            size_t bytes = ModelBytes(r->a);
            for (const Model& m : r->wheels) bytes += ModelBytes(m);
            for (const Model& m : r->rings) bytes += ModelBytes(m);
            WheelSplit split;
            if (!r->wheels.empty()) {
                g_wheelBytes += bytes;
                g_wearBytes += bytes;
                split.hull = ModelRegisterDerived(std::move(r->a), true);
                split.shell = r->shell;
                for (size_t w = 0; w < r->wheels.size() && w < static_cast<size_t>(kMaxWheels); ++w) {
                    split.wheel[w] = ModelRegisterDerived(std::move(r->wheels[w]), true);
                    if (r->shell && w < r->rings.size()) {
                        size_t rt = 0;
                        for (const ModelMesh& mm : r->rings[w].meshes) rt += mm.indices.size();
                        if (rt) split.ring[w] = ModelRegisterDerived(std::move(r->rings[w]), true);
                    }
                    split.centre[w] = r->centres[w];
                    split.radius[w] = r->radii[w];
                    ++split.n;
                }
            }
            g_wheelSplits[r->job.wkey] = split;
            g_wheelAsked.erase(r->job.wkey);
            if (g_wearCollected <= 400)
                Log("car bodies: wheel split of %s: %d wheels%s, radius %.3f, axles at %.2f/%.2f (CARI %.2f/%.2f), track %.2f (worker %.1f ms, %.1f MB of wheel splits)",
                    r->job.model->name.c_str(), split.n, split.shell ? " (shell: tyres and hubs, steered)" : "", split.n ? split.radius[0] : 0.0f, split.n ? split.centre[0].z : 0.0f,
                    split.n ? split.centre[split.n - 1].z : 0.0f, r->job.zFront, r->job.zRear, split.n ? std::fabs(split.centre[0].x) * 2.0f : 0.0f,
                    r->ms, static_cast<double>(g_wheelBytes) / (1 << 20));
        } else if (!r->job.door) {
            const DentKey key{r->job.model, r->job.step};
            const size_t bytes = ModelBytes(r->a);
            g_dentBytes += bytes;
            g_wearBytes += bytes;
            g_dents[key] = ModelRegisterDerived(std::move(r->a), true);
            g_dentAsked.erase(key);
            if (g_wearCollected <= 400)
                Log("car bodies: dented copy of %s, step %d of %d: %zu vertices pressed in, up to %.3f of the length (worker %.1f ms, %.1f MB of copies)",
                    r->job.model->name.c_str(), r->job.step, kDentSteps, r->count, 0.02f * static_cast<float>(r->job.step) / static_cast<float>(kDentSteps),
                    r->ms, static_cast<double>(g_wearBytes) / (1 << 20));
        } else {
            const size_t bytes = ModelBytes(r->a) + ModelBytes(r->b);
            g_doorBytes += bytes;
            g_wearBytes += bytes;
            DoorSplit split{ModelRegisterDerived(std::move(r->a), true), ModelRegisterDerived(std::move(r->b), true)};
            g_doorSplits[r->job.key] = split;
            g_doorAsked.erase(r->job.key);
            if (g_wearCollected <= 400)
                Log("car bodies: door split of %s, side %d: %zu door triangles between z %.2f and %.2f (worker %.1f ms, %.1f MB of copies)",
                    r->job.model->name.c_str(), r->job.side, r->count, r->job.zRear, r->job.zFront, r->ms, static_cast<double>(g_wearBytes) / (1 << 20));
        }
        delete r;
    }
}

// FIX-PERF-3: the seat bonnet of the car the player drives, built on the worker while he drives in the
// chase view, so the first frame from the driver's seat finds it (it was 45 ms on the render thread there).
void SeatBonnetAhead(const Model& model, const gta2::Mat4& fit, float windscreen, float ceiling) {
    const BonnetSurfKey key = BonnetSurfKeyFor(model, fit, windscreen);
    if (g_bonnetSurfs.count(key) || g_bonnetAsked.count(key) || !WearStart()) return;
    g_bonnetAsked.insert(key);
    WearJob job;
    job.bonnet = true;
    job.bkey = key;
    job.model = &model;
    job.fit = fit;
    job.windscreen = windscreen;
    job.ceiling = ceiling;
    WearPush(job, true);
}

// The four dent steps of a model, queued ahead of need the first time it is drawn.
void DentQueueAhead(const Model& model) {
    if (!g_wearStarted || !g_dentQueued.insert(&model).second) return;
    if (g_dentBytes + 4 * ModelBytes(model) > kDentAheadBytes) return;
    for (int step = 1; step <= kDentSteps; ++step) {
        const DentKey key{&model, step};
        if (g_dents.count(key) || !g_dentAsked.insert(key).second) continue;
        WearJob job;
        job.model = &model;
        job.step = step;
        WearPush(job, false);
    }
}

// The dented copy when it is built; otherwise it is asked for (first in line)
// and null comes back.
const Model* DentReady(const Model& model, int step) {
    const DentKey key{&model, step};
    auto it = g_dents.find(key);
    if (it != g_dents.end()) return WearMayShow({it->second}, g_wearFrame) ? it->second : nullptr;
    if (!WearStart()) {
        // No thread: build here, as before PERF-3.
        size_t moved = 0;
        const double t0 = CarNowMs();
        Model dented = BuildDented(model, step, &moved);
        g_wearWorkMs += CarNowMs() - t0;
        g_dentBytes += ModelBytes(dented);
        g_wearBytes += ModelBytes(dented);
        return g_dents[key] = ModelRegisterDerived(std::move(dented), true);
    }
    if (g_dentAsked.insert(key).second) {
        WearJob job;
        job.model = &model;
        job.step = step;
        WearPush(job, true);
    } else {
        // Already queued ahead: move it to the front.
        EnterCriticalSection(&g_wearLock);
        for (auto q = g_wearIdle.begin(); q != g_wearIdle.end(); ++q) {
            if (!q->door && !q->wheels && q->model == &model && q->step == step) { g_wearUrgent.push_front(*q); g_wearIdle.erase(q); break; }
        }
        LeaveCriticalSection(&g_wearLock);
    }
    ++g_dentLate;
    return nullptr;
}

// The best dented copy there is for a car that wants `step`: that step, else the
// highest lower step already built, else the model itself.
const Model* DentedModelFor(const Model& model, int step) {
    if (const Model* m = DentReady(model, step)) return m;
    for (int s = step - 1; s >= 1; --s) {
        auto it = g_dents.find(DentKey{&model, s});
        if (it != g_dents.end() && g_wearShown.count(it->second)) return it->second;
    }
    return &model;
}

// The door split when it is built; otherwise it is asked for and false comes back.
bool DoorReady(const Model& model, const gta2::Mat4& fit, int side, float zFront, float zRear, float roof, float halfW, DoorSplit* out) {
    const DoorKey key = DoorKeyFor(model, side, zFront, zRear);
    auto it = g_doorSplits.find(key);
    if (it != g_doorSplits.end()) {
        // Both halves count as one copy on screen (the door half is a few hundred triangles).
        if (!WearMayShow({it->second.body, it->second.door}, g_wearFrame)) return false;
        *out = it->second;
        return true;
    }
    WearJob job;
    job.door = true;
    job.model = &model;
    job.key = key;
    job.fit = fit;
    job.side = side;
    job.zFront = zFront; job.zRear = zRear; job.roof = roof; job.halfW = halfW;
    if (!WearStart()) {
        Model body, door;
        size_t tris = 0;
        BuildDoorSplit(model, fit, side, zFront, zRear, roof, halfW, key.exact, &body, &door, &tris);
        g_doorBytes += ModelBytes(body) + ModelBytes(door);
        g_wearBytes += ModelBytes(body) + ModelBytes(door);
        *out = g_doorSplits[key] = DoorSplit{ModelRegisterDerived(std::move(body), true), ModelRegisterDerived(std::move(door), true)};
        return true;
    }
    if (g_doorAsked.insert(key).second) WearPush(job, true);
    ++g_doorLate;
    return false;
}

// The wheel split when it is built (hull null: nothing to cut); otherwise it is asked
// for and false comes back.
bool WheelReady(const Model& model, const gta2::Mat4& fit, float zF, float zR, float halfW, float roof, WheelSplit* out) {
    const WheelKey key = WheelKeyFor(model, zF, zR, halfW);
    auto it = g_wheelSplits.find(key);
    if (it != g_wheelSplits.end()) {
        if (!it->second.hull) return false;
        // the hull, the wheels and (VEHICLE-ART-6) a shell's tyre rings: all their buffers before any is shown
        const WheelSplit& ws = it->second;
        const Model* parts[1 + 2 * kMaxWheels] = {ws.hull};
        size_t np = 1;
        for (int w = 0; w < ws.n && w < kMaxWheels; ++w) { parts[np++] = ws.wheel[w]; parts[np++] = ws.ring[w]; }
        if (!WearMayShow(parts, np, g_wearFrame)) return false;
        *out = it->second;
        return true;
    }
    if (!WearStart() || g_wheelBytes > kWheelSplitBytes) return false;   // no thread: never on the render thread
    if (g_wheelAsked.insert(key).second) {
        WearJob job;
        job.wheels = true;
        job.model = &model;
        job.wkey = key;
        job.fit = fit;
        job.zFront = zF; job.zRear = zR; job.roof = roof; job.halfW = halfW;
        WearPush(job, true);
    }
    ++g_wheelLate;
    return false;
}

// Turrets (POLICE-3D). The tank's gun turret and the fire truck's roof gear
// (the water cannon on its ladder deck) are part of each model's one sealed
// mesh, and the game aims them on their own: the turret is a sprite object of
// its own over the hull, with a heading of its own (CarBodiesSetTurret). The
// model is split once into the hull and the part above a height cut (`cut` of
// the roof; for the fire truck only behind `zMax` along the body), and that part
// is turned about the vertical through its own middle by the turret's heading
// against the hull's.
struct TurretKey {
    const Model* model; int cut, zMax;
    bool operator<(const TurretKey& o) const { return std::tie(model, cut, zMax) < std::tie(o.model, o.cut, o.zMax); }
};
struct TurretSplit { const Model* hull; const Model* turret; float pivotX, pivotZ; };
std::map<TurretKey, TurretSplit> g_turretSplits;
struct TurretAim { float dirX = 0.0f, dirZ = 1.0f; uint32_t frame = 0; };
std::map<uintptr_t, TurretAim> g_turretAims;   // by the car's sprite object
int g_turretLogged = 0;

// FIX-REMIX-MATERIALS-7 (ptrmx31): the shared floor pan (<NNN>_underpan.tga, VEHICLE-ART-13/14) under Remix.
// The pan hangs 15-20 cm over the road and reaches close to the bumpers; car bodies draw with no culling, so
// from the raised third-person camera its UPPER side showed past a shell's higher valance by parallax. The plain
// renderer lights that back face from below (it reads as the car's shadow); the path tracer lit it from the
// sky and the low sun: a flat grey board at noon, a brown one with brass-gold axle and exhaust at dawn. Under
// Remix the pan is drawn on its own, opaque (Remix never culls alpha-tested draws) with back faces culled
// (rtx.enableCulling: primary rays only), so the camera sees only its downward side while it still shades
// the road in the shadow rays. [devtools] remix_underpan: 3 (default) = culled D3DCULL_CW (the side that
// hides the pan's top: out/fm7_ab1), 2 = culled D3DCULL_CCW (the slab stays), 1 = one draw as before, 0 = no pan
// (no slab, but the road under the car loses the pan's shade).
int g_remixUnderpan = 3;
struct PanSplit { const Model* rest; const Model* pan; };
std::map<const Model*, PanSplit> g_panSplits;

PanSplit PanSplitFor(const Model& model) {
    auto it = g_panSplits.find(&model);
    if (it != g_panSplits.end()) return it->second;
    PanSplit split{nullptr, nullptr};
    bool any = false;
    for (const ModelMesh& m : model.meshes) any = any || m.texture.find("_underpan") != std::string::npos;
    if (any && !model.skinned) {
        Model rest, pan;
        for (Model* m : {&rest, &pan}) {
            m->nodes = model.nodes; m->forward = model.forward;
            m->boundsMin = model.boundsMin; m->boundsMax = model.boundsMax;
            for (int k = 0; k < 3; ++k) m->paintRgb[k] = model.paintRgb[k];
            m->splitPaint = model.splitPaint;
            m->hasDriverSeat = model.hasDriverSeat;
            for (int k = 0; k < 4; ++k) m->driverSeat[k] = model.driverSeat[k];
            m->meshes.resize(model.meshes.size());
        }
        rest.name = model.name + "#nopan"; pan.name = model.name + "#pan";
        for (size_t i = 0; i < model.meshes.size(); ++i) {
            const ModelMesh& src = model.meshes[i];
            ModelMesh& dst = src.texture.find("_underpan") != std::string::npos ? pan.meshes[i] : rest.meshes[i];
            dst.vertices = src.vertices; dst.indices = src.indices; dst.texture = src.texture; dst.skin = -1;
        }
        split.rest = ModelRegisterDerived(std::move(rest));
        split.pan = ModelRegisterDerived(std::move(pan));
        Log("car bodies: Remix floor-pan split of %s", model.name.c_str());
    }
    g_panSplits[&model] = split;
    return split;
}

// The hull under Remix, the pan by g_remixUnderpan (see above). False: not split, draw it whole.
bool RemixHullDraw(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& place) {
    if (!RemixApiAvailable() || g_remixUnderpan == 1) return false;
    const PanSplit split = PanSplitFor(model);
    if (!split.rest) return false;
    ModelDraw(device, *split.rest, place, nullptr, 0.0f);
    if (g_remixUnderpan == 0) return true;
    DWORD cull = 0, aTest = 0;
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &aTest);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, g_remixUnderpan == 3 ? D3DCULL_CW : D3DCULL_CCW);
    ModelDraw(device, *split.pan, place, nullptr, 0.0f);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, aTest);
    return true;
}

TurretSplit TurretSplitFor(const Model& model, const gta2::Mat4& fit, float roof, float cut, float zMax) {
    const TurretKey key{&model, static_cast<int>(cut * 100.0f), static_cast<int>(std::floor(zMax * 50.0f))};
    auto it = g_turretSplits.find(key);
    if (it != g_turretSplits.end()) return it->second;
    if (g_turretSplits.size() > 16) g_turretSplits.clear();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    Model hull, top;
    for (Model* m : {&hull, &top}) {
        m->nodes = model.nodes; m->forward = model.forward;
        m->boundsMin = model.boundsMin; m->boundsMax = model.boundsMax;
        for (int k = 0; k < 3; ++k) m->paintRgb[k] = model.paintRgb[k];
        m->splitPaint = model.splitPaint;
        m->meshes.resize(model.meshes.size());
    }
    hull.name = model.name + "#hull"; top.name = model.name + "#turret";
    size_t topTris = 0;
    double ax = 0.0, az = 0.0, aw = 0.0;
    for (size_t n = 0; n < model.nodes.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const ModelMesh& src = model.meshes[static_cast<size_t>(mi)];
        ModelMesh& dh = hull.meshes[static_cast<size_t>(mi)];
        ModelMesh& dt = top.meshes[static_cast<size_t>(mi)];
        dh.vertices = src.vertices; dh.texture = src.texture; dh.skin = -1;
        dt.vertices = src.vertices; dt.texture = src.texture; dt.skin = -1;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (size_t t = 0; t + 2 < src.indices.size(); t += 3) {
            gta2::Vec3 q[3];
            float cx = 0.0f, cy = 0.0f, cz = 0.0f;
            for (int c = 0; c < 3; ++c) {
                const ModelVertex& v = src.vertices[src.indices[t + static_cast<size_t>(c)]];
                q[c] = PointBy(toCar, v.x, v.y, v.z);
                cx += q[c].x; cy += q[c].y; cz += q[c].z;
            }
            cx /= 3.0f; cy /= 3.0f; cz /= 3.0f;
            const bool isTop = cy > cut * roof && cz < zMax;
            ModelMesh& dst = isTop ? dt : dh;
            dst.indices.push_back(src.indices[t]); dst.indices.push_back(src.indices[t + 1]); dst.indices.push_back(src.indices[t + 2]);
            if (isTop) {
                ++topTris;
                const gta2::Vec3 nrm = gta2::Cross(q[1] - q[0], q[2] - q[0]);
                const double area = std::sqrt(gta2::Dot(nrm, nrm));
                ax += area * cx; az += area * cz; aw += area;
            }
        }
    }
    TurretSplit split{nullptr, nullptr, 0.0f, 0.0f};
    if (topTris >= 8 && aw > 0.0) {
        split.pivotX = static_cast<float>(ax / aw); split.pivotZ = static_cast<float>(az / aw);
        split.hull = ModelRegisterDerived(std::move(hull));
        split.turret = ModelRegisterDerived(std::move(top));
    }
    g_turretSplits[key] = split;
    Log("car bodies: turret split of %s above %.2f of the roof (z < %.2f): %zu triangles, pivot %.3f,%.3f", model.name.c_str(), cut, zMax, topTris,
        split.pivotX, split.pivotZ);
    return split;
}

// How far each car's door stands open (0 shut, 1 fully), by sprite object.
struct DoorState { float open = 0.0f; int side = 1; uint32_t frame = 0; DoorSplit last{nullptr, nullptr}; int lastSide = 0; };
std::map<uintptr_t, DoorState> g_doors;
std::map<uintptr_t, int> g_doorWarm;   // ANIM-VEHICLE-ENTRY: door splits built ahead for the driven car (bit 1 left, 2 right)
int g_damageLogged = 0;

Built* Measured(IDirect3DDevice9* device, const CarBodyUse& use, IDirect3DTexture9* art, uint32_t frame) {
    (void)device;
    const Key key{use.sprite, art};
    auto found = g_cache.find(key);
    if (found != g_cache.end()) {
        found->second.used = frame;
        return found->second.measured ? &found->second : nullptr;
    }
    if (g_cache.size() >= kCacheMax) {
        for (auto it = g_cache.begin(); it != g_cache.end();) {
            if (frame - it->second.used > 300) {
                if (it->second.atlas) it->second.atlas->Release();
                ReleaseBuffers(&it->second);
                it = g_cache.erase(it);
            } else {
                ++it;
            }
        }
    }
    Built& b = g_cache[key];
    b.used = frame;
    int w = 0, h = 0;
    const double t0 = CarNowMs();
    // The game's own palette indices decoded on the CPU: a device readback of a
    // texture the driver has just uploaded stalls the whole pipeline on a GPU
    // (hundreds of milliseconds at a car's door animation, which is a new
    // texture every frame); the readback is kept only as the fallback.
    const bool decoded = SpriteImageFor(use.texture, &b.px, &w, &h) && w >= 4 && h >= 4 && w <= 256 && h <= 256;
    const bool ok = (decoded || ReadArt(art, &b.px, &w, &h)) && MeasureSprite(b.px, w, h, use.sprite, &b.measure);
    g_carStats[0] += CarNowMs() - t0;
    g_carStats[4] += 1;
    if (!ok) {
        static int logged = 0;
        if (logged++ < 10) Log("car body: sprite %d has no usable artwork (%dx%d)", use.sprite, w, h);
        b.px.clear();
        return nullptr;
    }
    b.scale = PixelScale(use, h);
    b.paint = b.measure.paint;
    if (decoded) {
        // FIX-CAR-IDENTITY-2 (feel25, pm40): the paint is the texels the game's remaps recolour (the sprite
        // decoded in another of its palettes: the texels that change). Their mean is the body colour the
        // classic view shows. The brighter half of each row (MeasureSprite's rule, kept for a sprite with no
        // remap) took in the sprite's painted highlight: the Minx's deep red body measured 189,109,108 and
        // the 3D car came out salmon pink. Of those texels the saturated ones are the body's colour ramp
        // (a remap also moves pale trim: the bank van's roof panels, a highlight); they are the paint when
        // they are at least 30 % of them, else (a white, silver or grey car) all of them. Saturated in
        // either palette, so the same texels count whichever palette the car is drawn in.
        // FIX-CAR-IDENTITY-5 (pmt4): from the sprite's CLEAN style art in the palette it is drawn in, not from the
        // drawn record's pixels (dents, door frames, lamps, damage): the paint is then a pure function of (sprite,
        // palette), the same for every car in that remap, every frame and every session. The record keys on the
        // palette too (identity.cpp), so a re-used game object with another remap is a new car at once.
        std::vector<uint32_t> other, cleanDrawn;
        bool remapped = false, clean = false;
        int cw = 0, ch = 0;
        const int palette = static_cast<const TextureRecord*>(use.texture)->palette;
        b.palette = palette;
        if (g_cleanPaint && CarSpriteCleanImages(use.sprite, palette, &cleanDrawn, &other, &cw, &ch, &remapped) && cw >= 4 && ch >= 4) {
            clean = true;
            Measure cm;
            if (MeasureSprite(cleanDrawn, cw, ch, use.sprite, &cm)) { b.measure.paint = cm.paint; b.paint = cm.paint; }
        } else if (!CarSpriteOtherImageFor(use.texture, use.sprite, &other, &remapped) || other.size() != b.px.size()) {
            other.clear();
        }
        const std::vector<uint32_t>& drawnPx = clean ? cleanDrawn : b.px;
        if (!other.empty()) {
            double all[3] = {0, 0, 0}, sat[3] = {0, 0, 0};
            int n = 0, ns = 0, opaque = 0;
            for (size_t i = 0; i < other.size(); ++i) {
                const uint32_t c = drawnPx[i], o = other[i];
                if ((c >> 24) < 128) continue;
                ++opaque;
                if ((c & 0xFFFFFFu) == (o & 0xFFFFFFu)) continue;
                const int r = (c >> 16) & 0xFF, g = (c >> 8) & 0xFF, bl = c & 0xFF;
                const int ro = (o >> 16) & 0xFF, go = (o >> 8) & 0xFF, bo = o & 0xFF;
                const int mx = (std::max)({r, g, bl}), mn = (std::min)({r, g, bl});
                const int mxo = (std::max)({ro, go, bo}), mno = (std::min)({ro, go, bo});
                all[0] += r; all[1] += g; all[2] += bl; ++n;
                // saturated in either palette: the same texels whichever palette the car is drawn in
                if ((mx > 0 && (mx - mn) >= 0.3f * mx) || (mxo > 0 && (mxo - mno) >= 0.3f * mxo)) { sat[0] += r; sat[1] += g; sat[2] += bl; ++ns; }
            }
            if (n >= 16) {
                const bool useSat = ns >= 16 && ns * 10 >= n * 3;
                const double* sum = useSat ? sat : all;
                const double cnt = useSat ? ns : n;
                b.paintMasked = true;
                b.paint = Rgb{static_cast<float>(sum[0] / cnt), static_cast<float>(sum[1] / cnt), static_cast<float>(sum[2] / cnt)};
            }
            static int logged = 0;
            if (logged++ < 60)
                Log("car body: sprite %d palette %d paint from its remap texels (%s, %d of %d opaque, %d saturated, %s): %.0f,%.0f,%.0f (brighter-half rule %.0f,%.0f,%.0f)",
                    use.sprite, palette, clean ? "clean style art" : "drawn art", n, opaque, ns, remapped ? "drawn in a remap" : "own palette", b.paint.r, b.paint.g, b.paint.b,
                    b.measure.paint.r, b.measure.paint.g, b.measure.paint.b);
        }
    }
    const gta2::CarInfo* info = g_info.count(use.sprite) ? &g_info[use.sprite] : nullptr;
    b.bodyLength = (info && info->height > 4 ? info->height : (b.measure.bottom - b.measure.top + 1)) * b.scale;
    b.bodyWidth = (info && info->width > 4 ? info->width : 2.0f * b.measure.maxHalfW) * b.scale;
    b.measured = true;
    return &b;
}

// The body built from the artwork, made on first use.
bool BodyMesh(IDirect3DDevice9* device, const CarBodyUse& use, Built* b) {
    if (b->meshBuilt) return b->ok;
    b->meshBuilt = true;
    Atlas atlas;
    b->atlas = MakeAtlas(device, b->px, b->measure, &atlas);
    if (!b->atlas) return false;
    BuildMesh(b->measure, atlas, b->scale, b);
    b->ok = !b->verts.empty() && b->verts.size() < 65000;
    b->px.clear();
    b->px.shrink_to_fit();
    ++g_built;
    static int logged = 0;
    if (logged++ < 40) {
        const Measure& m = b->measure;
        Log("car body: sprite %d (model %d) built from %dx%d art, body rows %d..%d, cabin %.0f..%.0f, wheels %.0f/%.0f, "
            "%u vertices, %s", use.sprite, use.model, m.w, m.h, m.top, m.bottom, m.cabinRear, m.cabinFront, m.wheelRear,
            m.wheelFront, static_cast<unsigned>(b->verts.size()),
            m.hasInfo ? "measured from CARI" : "no CARI entry, proportions guessed");
    }
    return b->ok;
}

// The buffers of a body, made once; false when the device gives none (then
// the body is drawn from memory).
bool Buffers(IDirect3DDevice9* device, Built* b) {
    if (b->buffersTried) return b->vb != nullptr;
    b->buffersTried = true;
    auto make = [&](const std::vector<CarBodyVertex>& v, const std::vector<uint16_t>& i, IDirect3DVertexBuffer9** vb,
                    IDirect3DIndexBuffer9** ib) {
        const UINT vbytes = static_cast<UINT>(v.size() * sizeof(CarBodyVertex)), ibytes = static_cast<UINT>(i.size() * 2);
        if (FAILED(device->CreateVertexBuffer(vbytes, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, vb, nullptr))) return false;
        if (FAILED(device->CreateIndexBuffer(ibytes, D3DUSAGE_WRITEONLY, D3DFMT_INDEX16, D3DPOOL_MANAGED, ib, nullptr))) return false;
        void* data = nullptr;
        if (FAILED((*vb)->Lock(0, vbytes, &data, 0)) || !data) return false;
        memcpy(data, v.data(), vbytes);
        (*vb)->Unlock();
        if (FAILED((*ib)->Lock(0, ibytes, &data, 0)) || !data) return false;
        memcpy(data, i.data(), ibytes);
        (*ib)->Unlock();
        return true;
    };
    if (!make(b->verts, b->indices, &b->vb, &b->ib) || !make(b->wheelVerts, b->wheelIndices, &b->wvb, &b->wib)) {
        ReleaseBuffers(b);
        Log("car body: no vertex buffers; drawing from memory");
        return false;
    }
    return true;
}

// Car space into the quad's own space: x across, y up (which way the quad's
// normal points), z toward the nose (larger v), origin at the canvas centre.
gta2::Mat4 CarToLocal(const CarBodyUse& use) {
    const CarBodyVertex* c = use.local;
    const float ax = c[1].x - c[0].x, ay = c[1].y - c[0].y, az = c[1].z - c[0].z;
    const float bx = c[3].x - c[0].x, by = c[3].y - c[0].y, bz = c[3].z - c[0].z;
    const float duA = c[1].u - c[0].u, dvA = c[1].v - c[0].v, duB = c[3].u - c[0].u, dvB = c[3].v - c[0].v;
    const float det = duA * dvB - duB * dvA;
    gta2::Mat4 out;
    out.m[3][3] = 1.0f;
    if (std::fabs(det) < 1e-9f) {
        out.m[0][0] = out.m[1][1] = out.m[2][2] = 1.0f;
        return out;
    }
    // s, t from u, v: [s t] = inv([duA duB; dvA dvB]) [u-u0 v-v0]
    const float i00 = dvB / det, i01 = -duB / det, i10 = -dvA / det, i11 = duA / det;
    // d local / d u and d local / d v (per unit of u and v).
    const float dux = ax * i00 + bx * i10, duy = ay * i00 + by * i10, duz = az * i00 + bz * i10;
    const float dvx = ax * i01 + bx * i11, dvy = ay * i01 + by * i11, dvz = az * i01 + bz * i11;
    float ex = dux, ey = duy, ez = duz;
    float fx = dvx, fy = dvy, fz = dvz;
    const float el = std::sqrt(ex * ex + ey * ey + ez * ez), fl = std::sqrt(fx * fx + fy * fy + fz * fz);
    if (el > 1e-9f) { ex /= el; ey /= el; ez /= el; }
    if (fl > 1e-9f) { fx /= fl; fy /= fl; fz /= fl; }
    // Up: the quad's normal, signed by which way the world calls up.
    float nx = ey * fz - ez * fy, ny = ez * fx - ex * fz, nz = ex * fy - ey * fx;
    const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
    if (nl > 1e-9f) { nx /= nl; ny /= nl; nz /= nl; } else { nx = 0; ny = 1; nz = 0; }
    // The world's up through the placement: the local axis whose image points up.
    const gta2::Mat4& o = use.objectToWorld;
    const float upWorld = nx * o.m[0][1] + ny * o.m[1][1] + nz * o.m[2][1];
    if (upWorld < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
    // Origin: the canvas centre (u, v = 0.5) on the quad.
    const float s = i00 * (0.5f - c[0].u) + i01 * (0.5f - c[0].v);
    const float t = i10 * (0.5f - c[0].u) + i11 * (0.5f - c[0].v);
    out.m[0][0] = ex; out.m[0][1] = ey; out.m[0][2] = ez;
    out.m[1][0] = nx; out.m[1][1] = ny; out.m[1][2] = nz;
    out.m[2][0] = fx; out.m[2][1] = fy; out.m[2][2] = fz;
    out.m[3][0] = c[0].x + s * ax + t * bx;
    out.m[3][1] = c[0].y + s * ay + t * by;
    out.m[3][2] = c[0].z + s * az + t * bz;
    return out;
}

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b) {
    gta2::Mat4 out;
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float s = 0.0f;
        for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
        out.m[r][c] = s;
    }
    return out;
}

float SteerFor(const CarBodyUse& use, const gta2::Mat4& world, float wheelbase, uint32_t frame) {
    if (!use.object) return 0.0f;
    // The nose in the world.
    float fx = world.m[2][0], fz = world.m[2][2];
    const float fl = std::sqrt(fx * fx + fz * fz);
    if (fl < 1e-6f) return 0.0f;
    fx /= fl; fz /= fl;
    const float x = world.m[3][0], z = world.m[3][2];
    const float yaw = std::atan2(fz, fx);
    Steer& st = g_steer[use.object];
    if (frame - st.frame > 30) {
        st = Steer{};
        st.x = x; st.z = z; st.yaw = yaw; st.frame = frame;
    } else if (st.frame != frame) {
        const float ds = (x - st.x) * fx + (z - st.z) * fz;
        const float dyaw = WrapAngle(yaw - st.yaw);
        float target = st.angle * 0.92f;
        if (std::fabs(ds) > 0.004f && std::fabs(ds) < 1.0f) {
            target = std::atan(wheelbase * dyaw / ds);
            target = (std::max)(-0.6f, (std::min)(0.6f, target));
        }
        st.angle += (target - st.angle) * 0.3f;
        st.x = x; st.z = z; st.yaw = yaw; st.frame = frame;
    }
    if (g_steer.size() > 256) {
        for (auto it = g_steer.begin(); it != g_steer.end();) {
            it = (frame - it->second.frame > 600) ? g_steer.erase(it) : std::next(it);
        }
    }
    return st.angle;
}

// feel20: the dark inside of a seated car's driver band. The band (drawHull below) is the hull at
// 40 % with no depth written so the seated figure shows through it; behind it there was nothing,
// so the street behind the car showed through the roof and the props and walls drawn after the
// cars painted over it. This draws the far walls and floor of a box inside the cabin (the faces
// turned away from the eye: the near ones would hide the driver), opaque, dark, depth written, in
// the band's clip planes (still set by the caller). Box in the car's posed frame (x across, y up,
// z forward).
// feel20: the cabin box for DrawBandInterior, inside the hull: its half width at the band's heights
// (the lower quartile of the widest point per slice along the cabin, so a stack, a mirror or a lamp
// at one station does not widen it) and its length under the roof (the hull's extent along the car
// near the roof, where the screens have raked in). Car's posed frame. Cached per model and fit.
struct BandBox { float halfW = 0.0f, z0 = 0.0f, z1 = 0.0f, roof = 0.0f; bool ok = false; };
BandBox MeasureBandBox(const Model& model, const gta2::Mat4& fit, float roofY, float zLo, float zHi) {
    struct Key { const Model* m; int a, b; bool operator<(const Key& o) const { return m != o.m ? m < o.m : a != o.a ? a < o.a : b < o.b; } };
    static std::map<Key, BandBox> cache;
    const Key key{&model, static_cast<int>(fit.m[0][0] * 4096.0f), static_cast<int>(zHi * 4096.0f)};
    auto it = cache.find(key);
    if (it != cache.end()) return it->second;
    if (cache.size() > 256) cache.clear();
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(model, &worlds);
    constexpr int kSlices = 10;
    float sliceMax[kSlices] = {};
    float topMin = 1e9f, topMax = -1e9f;
    std::vector<gta2::Vec3> pts;
    for (size_t n = 0; n < model.nodes.size() && n < worlds.size(); ++n) {
        const int mi = model.nodes[n].mesh;
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const gta2::Mat4 toCar = Mul(worlds[n], fit);
        for (const ModelVertex& v : model.meshes[static_cast<size_t>(mi)].vertices) pts.push_back(PointBy(toCar, v.x, v.y, v.z));
    }
    for (const gta2::Vec3& q : pts) {
        if (q.z < zLo || q.z > zHi) continue;
        if (q.y >= 0.60f * roofY && q.y <= 0.90f * roofY) {
            const int k = (std::max)(0, (std::min)(kSlices - 1, static_cast<int>((q.z - zLo) / (zHi - zLo + 1e-6f) * kSlices)));
            sliceMax[k] = (std::max)(sliceMax[k], std::fabs(q.x));
        }
    }
    std::vector<float> widths;
    for (float w : sliceMax) if (w > 0.0f) widths.push_back(w);
    BandBox box;
    if (!widths.empty()) {
        std::sort(widths.begin(), widths.end());
        box.halfW = 0.90f * widths[widths.size() / 4];
        for (const gta2::Vec3& q : pts)
            if (q.y >= 0.85f * roofY && std::fabs(q.x) <= box.halfW) { topMin = (std::min)(topMin, q.z); topMax = (std::max)(topMax, q.z); }
        const float inset = 0.03f * (zHi - zLo) + 0.01f;
        box.z0 = (std::max)(zLo, topMin + inset);
        box.z1 = (std::min)(zHi, topMax - inset);
        // Its top under the cabin's own roof: the model's height can be a stack's or a lamp's (the 063
        // cab's stacks stand 0.15 over its roof), so the median over the box's length of the highest
        // point within its inner width, less the roof skin.
        std::vector<float> tops;
        float sliceTop[kSlices];
        for (float& t : sliceTop) t = -1e9f;
        for (const gta2::Vec3& q : pts) {
            if (q.z < box.z0 || q.z > box.z1 || std::fabs(q.x) > 0.8f * box.halfW || q.y < 0.5f * roofY) continue;
            const int k = (std::max)(0, (std::min)(kSlices - 1, static_cast<int>((q.z - box.z0) / (box.z1 - box.z0 + 1e-6f) * kSlices)));
            sliceTop[k] = (std::max)(sliceTop[k], q.y);
        }
        for (float t : sliceTop) if (t > -1e8f) tops.push_back(t);
        box.roof = roofY;
        if (!tops.empty()) {
            std::sort(tops.begin(), tops.end());
            box.roof = (std::min)(roofY, tops[tops.size() / 2]);
        }
        box.ok = box.halfW > 0.02f && box.z1 > box.z0 + 0.05f && box.roof > 0.70f * roofY;
    }
    Log("band box %s: half width %.3f (of %zu slices), z %.3f..%.3f (band %.3f..%.3f), cabin roof %.3f of %.3f%s", model.name.c_str(), box.halfW,
        widths.size(), box.z0, box.z1, zLo, zHi, box.roof, roofY, box.ok ? "" : " (none)");
    cache[key] = box;
    return box;
}

void DrawBandInterior(IDirect3DDevice9* device, const gta2::Mat4& posed, float halfW, float y0, float y1, float z0, float z1,
                      uint32_t colour) {
    struct V { float x, y, z; uint32_t c; };
    const float x0 = -halfW, x1 = halfW;
    // Faces with their outward normal; wound so the cross product points outward (a front face in
    // D3D's left-handed frame), then drawn with CULL_CW so only the far, inward-seen ones remain.
    const float c[8][3] = {{x0, y0, z0}, {x1, y0, z0}, {x1, y1, z0}, {x0, y1, z0}, {x0, y0, z1}, {x1, y0, z1}, {x1, y1, z1}, {x0, y1, z1}};
    const int faces[6][4] = {{0, 1, 2, 3}, {5, 4, 7, 6}, {4, 0, 3, 7}, {1, 5, 6, 2}, {4, 5, 1, 0}, {3, 2, 6, 7}};
    const float out[6][3] = {{0, 0, -1}, {0, 0, 1}, {-1, 0, 0}, {1, 0, 0}, {0, -1, 0}, {0, 1, 0}};
    const float det = posed.m[0][0] * (posed.m[1][1] * posed.m[2][2] - posed.m[1][2] * posed.m[2][1]) -
                      posed.m[0][1] * (posed.m[1][0] * posed.m[2][2] - posed.m[1][2] * posed.m[2][0]) +
                      posed.m[0][2] * (posed.m[1][0] * posed.m[2][1] - posed.m[1][1] * posed.m[2][0]);
    V verts[36];
    int n = 0;
    for (int f = 0; f < 6; ++f) {
        const float* a = c[faces[f][0]]; const float* b = c[faces[f][1]]; const float* d = c[faces[f][2]];
        const float e1[3] = {b[0] - a[0], b[1] - a[1], b[2] - a[2]}, e2[3] = {d[0] - a[0], d[1] - a[1], d[2] - a[2]};
        const float wn[3] = {e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]};
        bool flip = wn[0] * out[f][0] + wn[1] * out[f][1] + wn[2] * out[f][2] < 0.0f;
        if (det < 0.0f) flip = !flip;
        const int order[6] = {0, 1, 2, 0, 2, 3}, rev[6] = {0, 2, 1, 0, 3, 2};
        for (int k = 0; k < 6; ++k) {
            const float* p = c[faces[f][flip ? rev[k] : order[k]]];
            // VEHICLE-ART-6: not one flat tone: the walls lighter towards the headlining (light from the
            // windows), the floor darkest, the back wall (seat backs) a touch warmer than the sides.
            float k0 = f == 4 ? 0.55f : (p[1] > 0.5f * (y0 + y1) ? 1.45f : 0.75f);
            const bool back = f == 0;
            auto ch = [&](int sh, float warm) {
                const float v = static_cast<float>((colour >> sh) & 0xFF) * k0 * warm;
                return static_cast<uint32_t>((std::min)(255.0f, v));
            };
            const uint32_t col = 0xFF000000u | (ch(16, back ? 1.18f : 1.0f) << 16) | (ch(8, back ? 1.05f : 1.0f) << 8) | ch(0, back ? 0.92f : 1.0f);
            verts[n++] = {p[0], p[1], p[2], col};
        }
    }
    DWORD lighting, cull, fvf, aTest, aBlend, zw, c0op, c0a1, a0op, a0a1, c1op, a1op, spec;
    IDirect3DBaseTexture9* tex0 = nullptr;
    D3DMATRIX world;
    device->GetTransform(D3DTS_WORLD, &world);
    device->GetRenderState(D3DRS_LIGHTING, &lighting);
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &aTest);
    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &aBlend);
    device->GetRenderState(D3DRS_ZWRITEENABLE, &zw);
    device->GetRenderState(D3DRS_SPECULARENABLE, &spec);
    device->GetFVF(&fvf);
    device->GetTextureStageState(0, D3DTSS_COLOROP, &c0op);
    device->GetTextureStageState(0, D3DTSS_COLORARG1, &c0a1);
    device->GetTextureStageState(0, D3DTSS_ALPHAOP, &a0op);
    device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &a0a1);
    device->GetTextureStageState(1, D3DTSS_COLOROP, &c1op);
    device->GetTextureStageState(1, D3DTSS_ALPHAOP, &a1op);
    device->GetTexture(0, &tex0);
    D3DMATRIX m;
    memcpy(&m, posed.m, sizeof m);
    device->SetTransform(D3DTS_WORLD, &m);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_CW);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(n / 3), verts, sizeof(V));
    device->SetTransform(D3DTS_WORLD, &world);
    device->SetRenderState(D3DRS_LIGHTING, lighting);
    device->SetRenderState(D3DRS_SPECULARENABLE, spec);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, aTest);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, aBlend);
    device->SetRenderState(D3DRS_ZWRITEENABLE, zw);
    device->SetFVF(fvf);
    device->SetTexture(0, tex0);
    if (tex0) tex0->Release();
    device->SetTextureStageState(0, D3DTSS_COLOROP, c0op);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, c0a1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, a0op);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, a0a1);
    device->SetTextureStageState(1, D3DTSS_COLOROP, c1op);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, a1op);
}

}  // namespace

void CarBodiesSetInfo(const std::vector<gta2::CarInfo>& infos) {
    g_info.clear();
    for (const gta2::CarInfo& c : infos) {
        if (g_info.find(c.sprite) == g_info.end()) g_info[c.sprite] = c;
    }
    Log("car bodies: %u car models measured for %u sprites", static_cast<unsigned>(infos.size()),
        static_cast<unsigned>(g_info.size()));
    if (ModelsAvailable()) WearStart();
    if (g_wearCollected || g_dentLate || g_doorLate)
        Log("car bodies: wear copies so far: %d built on the worker (%.0f ms of its time), %.1f MB (dents %.1f, doors %.1f); frames a car waited: dent %d, door %d",
            g_wearCollected, g_wearWorkMs, static_cast<double>(g_wearBytes) / (1 << 20), static_cast<double>(g_dentBytes) / (1 << 20),
            static_cast<double>(g_doorBytes) / (1 << 20), g_dentLate, g_doorLate);
}

bool CarBodiesSeatedSep() { return g_seatedSep != 0; }

bool CarBodiesCabin(const void* object, float* deck, float* roof, float* windscreen, float* halfWidth) {
    const auto it = g_cabins.find(reinterpret_cast<uintptr_t>(object));
    if (it == g_cabins.end()) return false;
    *deck = it->second.deck;
    *roof = it->second.roof;
    *windscreen = it->second.windscreen;
    *halfWidth = it->second.halfWidth;
    return true;
}

bool CarBodiesExtent(const void* object, float* length, float* height, float* halfWidth) {
    const auto it = g_cabins.find(reinterpret_cast<uintptr_t>(object));
    if (it == g_cabins.end()) return false;
    *length = it->second.length;
    *height = it->second.height;
    *halfWidth = it->second.halfWidth;
    return true;
}

bool CarBodiesGround(const void* object, float* y) {
    for (const CarFoot& f : g_feetCur)
        if (f.object == reinterpret_cast<uintptr_t>(object)) { *y = f.ground; return true; }
    return false;
}

int CarBodiesFootprints(CarFootprint* out, int max) {
    int n = 0;
    for (const CarFoot& f : g_feetCur) {
        if (n >= max) break;
        const float lx = 0.5f * (f.x0 + f.x1), lz = 0.5f * (f.z0 + f.z1);
        CarFootprint& o = out[n++];
        o.object = f.object;
        o.cx = f.cx + f.rx * lx + f.fx * lz; o.cz = f.cz + f.rz * lx + f.fz * lz; o.cy = f.ground;
        const auto p = g_push.find(f.object);
        if (p != g_push.end() && g_feetFrame - p->second.frame < 3) { o.cx += p->second.x; o.cz += p->second.z; }
        o.rx = f.rx; o.rz = f.rz; o.fx = f.fx; o.fz = f.fz;
        o.hx = 0.5f * (f.x1 - f.x0); o.hz = 0.5f * (f.z1 - f.z0);
    }
    return n;
}

bool CarBodiesTyreShadowsOn() { return g_tyreContactDev != 0; }

int CarBodiesWheelContacts(const void* object, float* x, float* z, float* r, float* ax, float* az, int max) {
    if (!g_tyreContactDev) return 0;
    for (const CarFoot& f : g_feetCur) {
        if (f.object != reinterpret_cast<uintptr_t>(object)) continue;
        const int n = (std::min)(f.wheels, max);
        for (int i = 0; i < n; ++i) { x[i] = f.wx[i]; z[i] = f.wz[i]; r[i] = f.wr[i]; }
        *ax = f.fx; *az = f.fz;
        return n;
    }
    return 0;
}

int CarBodiesBuilt() { return g_built; }
const double* CarBodiesStats() { return g_carStats; }
int CarBodiesPartStats(const double** ms, const char* const** names) { *ms = g_carParts; *names = kCarPartNames; return kPartCount; }
int CarBodiesDrawn() { return g_drawn; }

// ---------------------------------------------------------------------------
// Lamps. Headlamps and tail lamps as additive glows at the body's ends when it
// is dark, and brake lamps (brighter, larger red) while the car is losing
// speed, by day too. A radial glow texture, made once.
int g_lampMode = 1;
bool g_lampDark = false;
IDirect3DTexture9* g_glow = nullptr;
struct Motion { float x, z, speed; uint32_t frame; float brake; };
std::map<uintptr_t, Motion> g_motion;

// The beacon bulb under Remix: the glow with its colour in the texels. Remix drops the
// vertex colour (rtx.ignoreAllVertexColorBakedLighting) and takes an additive draw as
// emissive, so the vertex-coloured white glow showed as a white flare (REMIX-3); with the
// colour in the texture the bulb glows red, blue, white or amber. One per siren colour.
IDirect3DTexture9* g_beaconGlow[4] = {};
IDirect3DTexture9* BeaconGlowTexture(IDirect3DDevice9* device, int colour) {
    if (colour < 0 || colour > 3) colour = 0;
    if (g_beaconGlow[colour]) return g_beaconGlow[colour];
    const float* rgb = SyntheticSirenColour(colour);
    const int n = 32;
    IDirect3DTexture9* tex = nullptr;
    if (FAILED(device->CreateTexture(n, n, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(tex->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < n; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < n; ++x) {
                const float dx = (x + 0.5f) / n - 0.5f, dy = (y + 0.5f) / n - 0.5f;
                const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
                // A lens: full colour across most of the disc, a short soft edge.
                const float a = (std::max)(0.0f, (std::min)(1.0f, (1.0f - r) * 4.0f));
                uint32_t c[3];
                for (int k = 0; k < 3; ++k) c[k] = static_cast<uint32_t>((std::min)(1.0f, (std::max)(0.0f, rgb[k])) * a * 255.0f + 0.5f);
                row[x] = (static_cast<uint32_t>(a * 255.0f + 0.5f) << 24) | (c[0] << 16) | (c[1] << 8) | c[2];
            }
        }
        tex->UnlockRect(0);
    }
    g_beaconGlow[colour] = tex;
    return tex;
}

IDirect3DTexture9* GlowTexture(IDirect3DDevice9* device) {
    if (g_glow) return g_glow;
    const int n = 32;
    if (FAILED(device->CreateTexture(n, n, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_glow, nullptr))) { g_glow = nullptr; return nullptr; }
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(g_glow->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < n; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < n; ++x) {
                const float dx = (x + 0.5f) / n - 0.5f, dy = (y + 0.5f) / n - 0.5f;
                const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
                const float a = (std::max)(0.0f, 1.0f - r);
                const int v = static_cast<int>(a * a * 255.0f + 0.5f);
                row[x] = (static_cast<uint32_t>(v) << 24) | (static_cast<uint32_t>(v) << 16) | (static_cast<uint32_t>(v) << 8) | static_cast<uint32_t>(v);
            }
        }
        g_glow->UnlockRect(0);
    }
    return g_glow;
}

struct LampVertex { float x, y, z; DWORD color; float u, v; };
constexpr DWORD kLampFvf = D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1;

// `carToWorld`: the body's frame (x across, y up, z along, nose +z); `length`,
// `width`, `roof` in blocks. Leaves the states it changes as it found them.
// `feel` (VEHICLE-FEEL, null when off): its brake and reverse levels replace the
// measure here, reverse lamps join the tail lamps, and lit head lamps lay a pool on the road.
void DrawLamps(IDirect3DDevice9* device, const CarBodyUse& use, const gta2::Mat4& carToWorld, float length,
               float width, float roof, uint32_t frame, bool wreck, const VehicleFeel* feel = nullptr) {
    if (g_lampMode == 0 || wreck) return;
    // How fast, and is it slowing: the body's position frame to frame.
    Motion& mo = g_motion[use.object];
    const float x = carToWorld.m[3][0], z = carToWorld.m[3][2];
    if (mo.frame && frame > mo.frame && frame - mo.frame < 10) {
        const float dt = static_cast<float>(frame - mo.frame) / 30.0f;
        const float speed = std::sqrt((x - mo.x) * (x - mo.x) + (z - mo.z) * (z - mo.z)) / dt;
        const float decel = (mo.speed - speed) / dt;   // blocks/s^2
        const float want = (mo.speed > 0.6f && decel > 1.5f) ? 1.0f : 0.0f;
        mo.brake += (want - mo.brake) * (std::min)(1.0f, dt / (want > mo.brake ? 0.05f : 0.35f));
        mo.speed = speed;
    } else {
        mo.speed = 0.0f; mo.brake = 0.0f;
    }
    mo.x = x; mo.z = z; mo.frame = frame;
    if (g_motion.size() > 2048) { const Motion keep = mo; g_motion.clear(); g_motion[use.object] = keep; }
    const bool lit = g_lampMode == 2 || g_lampDark;
    const bool useFeel = feel && feel->on;
    const float brake = useFeel ? feel->brake : mo.brake;
    const float reverse = useFeel ? feel->reverse : 0.0f;
    if (lit && useFeel) VehicleFxQueueHeadlamps(carToWorld, length, width);
    if (!lit && brake < 0.05f && reverse < 0.05f) return;
    IDirect3DTexture9* glow = GlowTexture(device);
    if (!glow) return;
    const float hx = 0.34f * width, hy = (std::max)(0.05f, 0.30f * roof), nose = 0.5f * length + 0.006f;
    struct Lamp { float x, y, z; float size; DWORD color; };
    Lamp lamps[6]; int n = 0;
    if (lit) {
        lamps[n++] = {-hx, hy, nose, 0.11f, 0xFFFFF0C8u};
        lamps[n++] = {hx, hy, nose, 0.11f, 0xFFFFF0C8u};
    }
    if (reverse > 0.05f) {
        // Reverse lamps: white, inboard of the tail lamps.
        const int k = static_cast<int>(reverse * 235.0f);
        const DWORD col = D3DCOLOR_ARGB(255, k, k, (k * 15) / 16);
        lamps[n++] = {-0.55f * hx, hy, -nose, 0.065f, col};
        lamps[n++] = {0.55f * hx, hy, -nose, 0.065f, col};
    }
    {
        const float b = brake;
        const int r = static_cast<int>((lit ? 150.0f : 0.0f) + b * 105.0f), g = static_cast<int>(lit ? 30.0f : 0.0f);
        if (r > 0) {
            const DWORD col = D3DCOLOR_ARGB(255, r, g, g / 2);
            const float sz = 0.07f + 0.05f * b;
            lamps[n++] = {-hx, hy, -nose, sz, col};
            lamps[n++] = {hx, hy, -nose, sz, col};
        }
    }
    if (!n) return;
    // Camera-facing quads: the car's axes give "across" and "up" of the body; a
    // lamp glow is round, so its own quad is spanned by the car's x and y.
    LampVertex v[24];
    int count = 0;
    for (int i = 0; i < n; ++i) {
        const Lamp& l = lamps[i];
        const float ax[3] = {carToWorld.m[0][0], carToWorld.m[0][1], carToWorld.m[0][2]};
        const float ay[3] = {carToWorld.m[1][0], carToWorld.m[1][1], carToWorld.m[1][2]};
        const float az[3] = {carToWorld.m[2][0], carToWorld.m[2][1], carToWorld.m[2][2]};
        float c[3];
        for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + l.x * ax[j] + l.y * ay[j] + l.z * az[j];
        const float s = l.size;
        const float corners[4][2] = {{-s, -s}, {s, -s}, {s, s}, {-s, s}};
        const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
        for (int k = 0; k < 4; ++k) {
            LampVertex& o = v[count++];
            o.x = c[0] + corners[k][0] * ax[0] + corners[k][1] * ay[0];
            o.y = c[1] + corners[k][0] * ax[1] + corners[k][1] * ay[1];
            o.z = c[2] + corners[k][0] * ax[2] + corners[k][1] * ay[2];
            o.color = l.color; o.u = uv[k][0]; o.v = uv[k][1];
        }
    }
    static const uint16_t idx[36] = {0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7, 8, 9, 10, 8, 10, 11, 12, 13, 14, 12, 14, 15,
                                     16, 17, 18, 16, 18, 19, 20, 21, 22, 20, 22, 23};
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, glow);
    device->SetFVF(kLampFvf);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(count), static_cast<UINT>(n * 2), idx,
                                   D3DFMT_INDEX16, v, sizeof(LampVertex));
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
}

// Emergency lights on the 3D bodies (POLICE-3D). The game lights a siren car's
// roof lamps as sprite deltas 15..18 (the car's delta mask, vehicle +0x08) while
// its siren runs; a 3D model hides the sprite, so those lamps were lost in the
// street views. A car of a siren model (cop car 12, ambulance 34, fire truck 17,
// SWAT van 52) with any of those bits set gets two
// beacons on its roof that flash in turn, the colours by model; with the siren
// off the bar is dark. Drawn day and night, whatever car_lamps says.
// `[devtools] force_sirens=1` lights them on every siren model for checks.
int g_forceSirens = 0;
// FIX-REMIX-NIGHT-7 (ptrx-remix-first-siren-beacon-flat-saturated-disc-floats-beside-car): under Remix no glow quads
// at the bulbs. The three crossed additive BeaconGlowTexture quads per bulb were drawn by Remix as a wheel-sized flat
// saturated disc with a cross through it floating beside the roof (it stayed with all our lights off: a draw, not a
// light). The lit roof lamp is the model's lens plus the siren lights (synthetic_lights.cpp: the glow round the bulb
// and the rotating spot). [devtools] remix_beacon_quads=1 restores the old draw (A/B); the plain renderer is untouched.
int g_remixBeaconQuads = 0;
// In their place, per lit bulb, one small glow cap facing the eye on the top of the model's own light bar (the
// highest part of the body, found once per model in BeaconLampSpot), so the lamp itself reads lit and alternates.
// [devtools] remix_beacon_cap_milli: the cap's half-size in tiles x1000 (default 22; 0 = no cap).
int g_remixBeaconCapMilli = 22;
struct BeaconLamp { bool ok = false; float x[2] = {}, y[2] = {}, z[2] = {}; };   // per side: -x (A, red) and +x (B)
std::map<const Model*, BeaconLamp> g_beaconLamps;
// The light bar's top in the model's frame: the vertices within the top 5 % of the body's height, split at the
// band's middle into the red (-x) and blue (+x) halves (one dome a side, or the two ends of one bar). A body whose
// top band is wide (a flat roof) has no distinct bar: no cap.
const BeaconLamp& BeaconLampSpot(const Model* model) {
    auto it = g_beaconLamps.find(model);
    if (it != g_beaconLamps.end()) return it->second;
    BeaconLamp lamp;
    std::vector<gta2::Mat4> worlds;
    ModelRestNodeWorlds(*model, &worlds);
    const float h = model->Height(), w = model->Width(), l = model->Length();
    const float band = model->boundsMax.y - 0.05f * h;
    float x0 = 1e9f, x1 = -1e9f, z0 = 1e9f, z1 = -1e9f;
    std::vector<gta2::Vec3> top;
    for (size_t i = 0; i < model->nodes.size() && i < worlds.size(); ++i) {
        const int mi = model->nodes[i].mesh;
        if (mi < 0 || mi >= static_cast<int>(model->meshes.size()) || model->meshes[mi].skin >= 0) continue;
        const gta2::Mat4& m = worlds[i];
        for (const ModelVertex& v : model->meshes[mi].vertices) {
            const float y = v.x * m.m[0][1] + v.y * m.m[1][1] + v.z * m.m[2][1] + m.m[3][1];
            if (y < band) continue;
            const float x = v.x * m.m[0][0] + v.y * m.m[1][0] + v.z * m.m[2][0] + m.m[3][0];
            const float z = v.x * m.m[0][2] + v.y * m.m[1][2] + v.z * m.m[2][2] + m.m[3][2];
            x0 = (std::min)(x0, x); x1 = (std::max)(x1, x); z0 = (std::min)(z0, z); z1 = (std::max)(z1, z);
            top.push_back({x, y, z});
        }
    }
    const int n = static_cast<int>(top.size());
    if (n >= 3 && x1 - x0 < 0.75f * w && z1 - z0 < 0.30f * l) {
        // Each half of the bar (a dome a side, or the two ends of one bar): its vertices' mean x and z, its top.
        const float mid = 0.5f * (x0 + x1);
        float sx[2] = {}, sz[2] = {}, ty[2] = {-1e9f, -1e9f};
        int cnt[2] = {};
        for (const gta2::Vec3& v : top) {
            const int k = v.x < mid ? 0 : 1;
            sx[k] += v.x; sz[k] += v.z; ty[k] = (std::max)(ty[k], v.y); ++cnt[k];
        }
        lamp.ok = cnt[0] > 0 && cnt[1] > 0;
        for (int k = 0; k < 2 && lamp.ok; ++k) { lamp.x[k] = sx[k] / cnt[k]; lamp.z[k] = sz[k] / cnt[k]; lamp.y[k] = ty[k]; }
    }
    Log("car bodies: Remix beacon cap for %s: %s (bar x %.3f..%.3f z %.3f..%.3f of %.3f x %.3f, %d vertices; caps at x %.3f / %.3f)",
        model->name.c_str(), lamp.ok ? "on the bar" : "none (no distinct bar)", x0, x1, z0, z1, w, l, n, lamp.x[0], lamp.x[1]);
    return g_beaconLamps.emplace(model, lamp).first->second;
}
int g_carWorldSunDev = -1;   // FIX-FX-3: [devtools] car_world_sun (-1: GTA2DX9_CAR_WORLD_SUN, default on)
int g_beaconLogged = 0;
void DrawBeacons(IDirect3DDevice9* device, const CarBodyUse& use, const gta2::Mat4& carToWorld, float length, float width,
                 float roof, uint32_t frame, int modelNumber, const Model* model = nullptr, const gta2::Mat4* fit = nullptr) {
    DWORD colA = 0, colB = 0;
    int kindA = kSirenRed, kindB = kSirenBlue;   // SirenColour, for the lights and the Remix bulbs
    float along = 0.0f;
    switch (modelNumber) {
        case 12: case 52: colA = 0xFFFF2010u; colB = 0xFF1040FFu; along = -0.05f; break;   // police: red, blue
        case 34: colA = 0xFFFF2010u; colB = 0xFFFFF4E0u; kindB = kSirenWhite; along = 0.30f; break;   // ambulance: red, white, over the cab
        case 17: colA = 0xFFFF2010u; colB = 0xFFFF7010u; kindB = kSirenAmber; along = 0.36f; break;   // fire truck: red, amber, over the cab
        default: return;
    }
    uint32_t mask = 0;
    uintptr_t vehicle = use.object;
    {
        const uint8_t* object = reinterpret_cast<const uint8_t*>(use.object);
        const uint8_t* car = object ? *reinterpret_cast<const uint8_t* const*>(object + 0x08) : nullptr;   // sprite owner -> vehicle
        if (car && reinterpret_cast<uintptr_t>(car) > 0x10000) {
            mask = *reinterpret_cast<const uint32_t*>(car + 0x08);
            vehicle = reinterpret_cast<uintptr_t>(car);
        }
    }
    const uint32_t sirenBits = (0xFu << 15) | (0xFu << (15 + 17));   // deltas 15..18 and their mirrored copies
    const bool on = (mask & sirenBits) != 0 || g_forceSirens != 0;
    if (!on) return;
    const bool remix = RemixApiAvailable();
    IDirect3DTexture9* glow = GlowTexture(device);
    if (!glow) return;
    if (g_beaconLogged < 12) {
        ++g_beaconLogged;
        Log("car bodies: beacons on model %d object %p (delta mask %08x%s)", modelNumber, reinterpret_cast<const void*>(use.object), mask,
            g_forceSirens ? ", forced" : "");
    }
    // The game's own lamps alternate; where it holds them all lit the flash is ours: 2.5 Hz.
    const bool phase = ((frame / 6u) & 1u) != 0;
    const bool litA = (mask & ((1u << 15) | (1u << 17))) ? true : phase;
    const bool litB = (mask & ((1u << 16) | (1u << 18))) ? true : !phase;
    const bool aOn = ((mask & sirenBits) == sirenBits || g_forceSirens) ? phase : litA;
    const bool bOn = ((mask & sirenBits) == sirenBits || g_forceSirens) ? !phase : litB;
    struct Beacon { float x; DWORD color; float size; };
    Beacon beacons[4]; int n = 0;
    const float hx = 0.22f * width, y = roof + 0.02f, z = along * length;
    const float ax[3] = {carToWorld.m[0][0], carToWorld.m[0][1], carToWorld.m[0][2]};
    const float ay[3] = {carToWorld.m[1][0], carToWorld.m[1][1], carToWorld.m[1][2]};
    const float az[3] = {carToWorld.m[2][0], carToWorld.m[2][1], carToWorld.m[2][2]};
    // Each lamp is also a light of its colour (synthetic_lights.cpp: a glow round the bulb and
    // a rotating spot), lit while the bulb is, queued for the next frame's lights.
    for (int i = 0; i < 2; ++i) {
        const float bx = i ? hx : -hx;
        float c[3];
        for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + bx * ax[j] + y * ay[j] + z * az[j];
        SyntheticQueueBeacon(vehicle, i, c, i ? kindB : kindA, i ? bOn : aOn);
    }
    if (remix) {
        if (!g_remixBeaconQuads) {   // FIX-REMIX-NIGHT-7: a cap on the model's bar, not quads in the air
            if (!model || !fit || g_remixBeaconCapMilli <= 0 || !(aOn || bOn)) return;
            const BeaconLamp& lamp = BeaconLampSpot(model);
            if (!lamp.ok) return;
            D3DMATRIX view;
            if (FAILED(device->GetTransform(D3DTS_VIEW, &view))) return;
            const float right[3] = {view._11, view._21, view._31}, up[3] = {view._12, view._22, view._32};
            const float s = static_cast<float>(g_remixBeaconCapMilli) / 1000.0f;
            const gta2::Mat4& f = *fit;
            LampVertex cv[4];
            D3DMATRIX identity = {};
            identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
            device->SetTransform(D3DTS_WORLD, &identity);
            device->SetRenderState(D3DRS_LIGHTING, FALSE);
            device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
            device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
            device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
            device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
            device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
            device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
            device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
            device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
            device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
            device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
            device->SetFVF(kLampFvf);
            for (int k = 0; k < 2; ++k) {
                if (!(k ? bOn : aOn)) continue;
                // Model frame: the bar's top, the red (A) half at -x and the blue (B) half at +x, then the body's fit.
                const float mx = lamp.x[k], my = lamp.y[k] - 0.4f * s / (std::max)(1e-4f, f.m[1][1]), mz = lamp.z[k];
                const float px = mx * f.m[0][0] + my * f.m[1][0] + mz * f.m[2][0] + f.m[3][0];
                const float py = mx * f.m[0][1] + my * f.m[1][1] + mz * f.m[2][1] + f.m[3][1];
                const float pz = mx * f.m[0][2] + my * f.m[1][2] + mz * f.m[2][2] + f.m[3][2];
                float c[3];
                for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + px * ax[j] + py * ay[j] + pz * az[j];
                const float corners[4][2] = {{-s, -s}, {s, -s}, {s, s}, {-s, s}};
                const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
                for (int q = 0; q < 4; ++q) {
                    LampVertex& o = cv[q];
                    o.x = c[0] + corners[q][0] * right[0] + corners[q][1] * up[0];
                    o.y = c[1] + corners[q][0] * right[1] + corners[q][1] * up[1];
                    o.z = c[2] + corners[q][0] * right[2] + corners[q][1] * up[2];
                    o.color = 0xFFFFFFFFu; o.u = uv[q][0]; o.v = uv[q][1];
                }
                const uint16_t idx[6] = {0, 1, 2, 0, 2, 3};
                device->SetTexture(0, BeaconGlowTexture(device, k ? kindB : kindA));
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, idx, D3DFMT_INDEX16, cv, sizeof(LampVertex));
            }
            device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
            device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
            device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
            device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
            device->SetRenderState(D3DRS_LIGHTING, TRUE);
            return;
        }
        // Under Remix: the bulb alone, in its own colour (BeaconGlowTexture); the halo is
        // the path tracer's (the light round the bulb and the bloom), and a 0.36 flat
        // emissive cross would be a glowing plate.
        if (aOn) beacons[n++] = {-hx, 0xFFFFFFFFu, 0.045f};
        if (bOn) beacons[n++] = {hx, 0xFFFFFFFFu, 0.045f};
    } else {
        // A lit beacon is a bright core and a wide soft halo.
        if (aOn) { beacons[n++] = {-hx, colA, 0.07f}; beacons[n++] = {-hx, (colA & 0x00FFFFFFu) | 0xFF000000u, 0.18f}; }
        if (bOn) { beacons[n++] = {hx, colB, 0.07f}; beacons[n++] = {hx, (colB & 0x00FFFFFFu) | 0xFF000000u, 0.18f}; }
    }
    if (!n) return;
    LampVertex v[48];
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetFVF(kLampFvf);
    // Billboards facing the eye would need the camera here; the glows are spanned
    // by the car's across and along axes (seen from above) and by across and up
    // (seen from the street): two crossed quads per beacon. Under Remix a third, along
    // and up, so the bulb is not edge-on from the side; and one draw per bulb, as each
    // has its own texture there.
    const int planes = remix ? 3 : 2;
    auto draw = [&](int first, int last, IDirect3DTexture9* tex) {
        int count = 0;
        for (int i = first; i < last; ++i) {
            const Beacon& bc = beacons[i];
            const float s = bc.size;
            DWORD col = bc.color;
            if (s > 0.1f) {   // the halo dimmer than the core
                const int r = static_cast<int>(((col >> 16) & 0xFF) * 0.45f), g = static_cast<int>(((col >> 8) & 0xFF) * 0.45f),
                          b = static_cast<int>((col & 0xFF) * 0.45f);
                col = D3DCOLOR_ARGB(255, r, g, b);
            }
            float c[3];
            for (int j = 0; j < 3; ++j) c[j] = carToWorld.m[3][j] + bc.x * ax[j] + y * ay[j] + z * az[j];
            const float corners[4][2] = {{-s, -s}, {s, -s}, {s, s}, {-s, s}};
            const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
            const float* first2[3] = {ax, ax, az};
            const float* second[3] = {ay, az, ay};
            for (int q = 0; q < planes && count + 4 <= 48; ++q) {
                const float* b1 = first2[q];
                const float* b2 = second[q];
                for (int k = 0; k < 4; ++k) {
                    LampVertex& o = v[count++];
                    o.x = c[0] + corners[k][0] * b1[0] + corners[k][1] * b2[0];
                    o.y = c[1] + corners[k][0] * b1[1] + corners[k][1] * b2[1];
                    o.z = c[2] + corners[k][0] * b1[2] + corners[k][1] * b2[2];
                    o.color = col; o.u = uv[k][0]; o.v = uv[k][1];
                }
            }
        }
        if (!count || !tex) return;
        uint16_t idx[72];
        for (int q = 0; q < count / 4; ++q) {
            const uint16_t b0 = static_cast<uint16_t>(q * 4);
            const uint16_t t[6] = {b0, static_cast<uint16_t>(b0 + 1), static_cast<uint16_t>(b0 + 2), b0, static_cast<uint16_t>(b0 + 2), static_cast<uint16_t>(b0 + 3)};
            memcpy(idx + q * 6, t, sizeof t);
        }
        device->SetTexture(0, tex);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(count), static_cast<UINT>(count / 2), idx,
                                       D3DFMT_INDEX16, v, sizeof(LampVertex));
    };
    if (remix) {
        for (int i = 0; i < n; ++i) draw(i, i + 1, BeaconGlowTexture(device, beacons[i].x < 0.0f ? kindA : kindB));
    } else {
        draw(0, n, glow);
    }
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
}

void CarBodiesSetLamps(int mode, bool dark) {
    g_lampMode = mode;
    g_lampDark = dark;
    // The caller judges dark by the sky's fixed sun; with [sky] follow_clock=1 the sun
    // is the clock's, so a night street had unlit cars. The clock's sun decides then.
    const gta2::SkySettings& sky = gta2::SkyConfig();
    if (sky.followClock) {
        float elevation = sky.sunElevationDeg, azimuth = sky.sunAzimuthDeg;
        TimeOfDayAngles(&elevation, &azimuth);
        g_lampDark = elevation < 6.0f;
    }
}

void CarBodiesReleaseDevice() {
    CabInteriorReleaseDevice();
    BonnetTextureRelease();
    CarGlassReleaseDevice();
    for (auto& e : g_cache) {
        if (e.second.atlas) e.second.atlas->Release();
        ReleaseBuffers(&e.second);
    }
    g_cache.clear();
    g_lastBuilt.clear();
    if (g_glow) { g_glow->Release(); g_glow = nullptr; }
    VehicleFxReleaseDevice();
    for (IDirect3DTexture9*& t : g_beaconGlow) {
        if (t) { t->Release(); t = nullptr; }
    }
    g_device = nullptr;
}

// Whether a point of the world lies inside the car's box (car space, a little margin).
bool Inside(const gta2::Mat4& carToWorld, const gta2::Vec3& p, float halfW, float halfL, float height) {
    // Invert the rigid part: rows are the car's axes in the world.
    const float dx = p.x - carToWorld.m[3][0], dy = p.y - carToWorld.m[3][1], dz = p.z - carToWorld.m[3][2];
    const float x = dx * carToWorld.m[0][0] + dy * carToWorld.m[0][1] + dz * carToWorld.m[0][2];
    const float y = dx * carToWorld.m[1][0] + dy * carToWorld.m[1][1] + dz * carToWorld.m[1][2];
    const float z = dx * carToWorld.m[2][0] + dy * carToWorld.m[2][1] + dz * carToWorld.m[2][2];
    return std::fabs(x) < halfW + 0.15f && std::fabs(z) < halfL + 0.15f && y > -0.2f && y < height + 0.15f;
}

// VEHICLE-FEEL: the wheels each car last turned (for the one that flies off when it
// blows up), and which corners a wreck model has lost (bit 0 front-left, 1 front-right,
// 2 rear-left, 3 rear-right: its wheel_* markers are the wheels it kept).
struct LastWheels { WheelSplit split; gta2::Mat4 fit; uint32_t frame = 0; };
std::unordered_map<uintptr_t, LastWheels> g_lastWheels;
std::map<const Model*, int> g_wreckLost;
int WreckLostCorners(const Model& model) {
    auto it = g_wreckLost.find(&model);
    if (it != g_wreckLost.end()) return it->second;
    static const char* names[4] = {"wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"};
    int present = 0;
    bool any = false;
    for (const ModelNode& n : model.nodes) {
        if (strncmp(n.name, "wheel_", 6) != 0) continue;
        any = true;
        for (int k = 0; k < 4; ++k) if (strcmp(n.name, names[k]) == 0) present |= 1 << k;
    }
    // The markers are in the model's own frame: with forward -1 its front is our rear.
    int lost = any ? (~present & 0xF) : 0;
    if (model.forward < 0.0f) lost = ((lost & 3) << 2) | ((lost >> 2) & 3);
    return g_wreckLost[&model] = lost;
}
bool g_feelIniSet = false;

void CarBodiesDraw(IDirect3DDevice9* device, const std::vector<CarBodyUse>& cars, uint32_t frame, const gta2::Vec3& eye) {
    g_built = 0;
    g_drawn = 0;
    for (double& v : g_carStats) v = 0.0;
    for (double& v : g_carParts) v = 0.0;
    g_wearFrame = frame;
    {
        const double tw = CarNowMs();
        WearCollect();
        const double ms = CarNowMs() - tw;
        static int slowCollectLogged = 0;
        if (ms > 4.0 && slowCollectLogged < 40) { ++slowCollectLogged; Log("car bodies: collecting the worker's copies took %.1f ms", ms); }
    }
    if (cars.empty()) return;
    if (g_device != device) {
        CarBodiesReleaseDevice();
        g_device = device;
    }
    // Lit, so the body has shape: one sun from high in front and to the side,
    // some ambient, and a modest specular lobe for the paint.
    D3DLIGHT9 sun = {};
    sun.Type = D3DLIGHT_DIRECTIONAL;
    sun.Diffuse = {0.78f, 0.78f, 0.78f, 1.0f};   // neutral: the paint tint must not pick up a cast
    sun.Specular = {0.55f, 0.55f, 0.55f, 1.0f};
    float dx = 0.38f, dy = -0.78f, dz = 0.50f;
    // FIX-FX-3 (feel29): from the world's sun when the sky draws one (plain renderer). The fixed
    // sun above came from another side than the [sky] sun the shadow mask (post_fx.cpp) darkens
    // by: a face lit by it but turned from the world's sun was never shadowed, and a few degrees
    // of steering flipped that test, so a van along a wall in the wall's shadow went from dark
    // to pale in two frames. Same direction as the shadow maps (never flatter than 10 degrees);
    // the levels (and so the paint's look) are unchanged. GTA2DX9_CAR_WORLD_SUN=0: the old sun.
    {
        static int s_worldSun = -1;
        if (s_worldSun < 0) {
            char v[8] = {};
            s_worldSun = (GetEnvironmentVariableA("GTA2DX9_CAR_WORLD_SUN", v, sizeof v) && v[0] == '0') ? 0 : 1;
            Log("car bodies: sun %s", s_worldSun ? "from the world's sun (GTA2DX9_CAR_WORLD_SUN)" : "fixed (GTA2DX9_CAR_WORLD_SUN=0)");
        }
        const gta2::SkySettings& sky = gta2::SkyConfig();
        // [devtools] car_world_sun=0|1 (re-read with the other devtools keys) for same-session A/B frames.
        const int worldSun = g_carWorldSunDev >= 0 ? g_carWorldSunDev : s_worldSun;
        if (worldSun && sky.enabled && !RemixApiAvailable()) {
            float elevation = sky.sunElevationDeg, azimuth = sky.sunAzimuthDeg;
            if (sky.followClock) TimeOfDayAngles(&elevation, &azimuth);
            gta2::Vec3 s = gta2::ComputeSkyColours(elevation, azimuth).sunDir;   // toward the sun
            const float minY = std::sin(10.0f * 3.14159265f / 180.0f);
            if (s.y < minY) {
                const float h = (std::max)(1e-6f, std::sqrt(s.x * s.x + s.z * s.z));
                const float c = std::sqrt(1.0f - minY * minY);
                s = gta2::Vec3{s.x / h * c, minY, s.z / h * c};
            }
            dx = -s.x; dy = -s.y; dz = -s.z;
        }
    }
    const float dl = std::sqrt(dx * dx + dy * dy + dz * dz);
    sun.Direction = {dx / dl, dy / dl, dz / dl};
    // FIX-REMIX-NIGHT-8 (qav1 night cars at daylight brightness): the bodies' sun and ambient are the hour's light the
    // figures take (FigureTimeOfDayLight, ptm14): exactly 1 by day, with the sky off or under Remix; at night the ratio the
    // walls fall by. GTA2DX9_CAR_NIGHT=0: the day's levels at every hour (before).
    float carTod[3] = {1.0f, 1.0f, 1.0f};
    {
        static int s_carNight = -1;
        if (s_carNight < 0) { const char* e = getenv("GTA2DX9_CAR_NIGHT"); s_carNight = (e && e[0] == '0') ? 0 : 1; }
        if (s_carNight && FigureTimeOfDayLight(carTod)) {
            sun.Diffuse = {0.78f * carTod[0], 0.78f * carTod[1], 0.78f * carTod[2], 1.0f};
            sun.Specular = {0.55f * carTod[0], 0.55f * carTod[1], 0.55f * carTod[2], 1.0f};
        }
    }
    device->SetLight(0, &sun);
    device->LightEnable(0, TRUE);
    {
        // FIX-CAR-IDENTITY-4: the paint's gain (identity.cpp DeriveVehicle) gives back what the 3D light takes
        // from a lid seen from the classic camera. It was measured (1.25) under the fixed sun 51 degrees up,
        // which lit a lid 0.35 ambient + 0.78 x 0.78 = 0.96; with the world's sun (FIX-FX-3, 4ecf174: 24
        // degrees by default) a lid gets 0.67 and every body drew ~0.7 as bright as its sprite. The gain
        // follows the lid's light so the lids keep the sprite's level at any sun (shadow and the faces'
        // shading stay the light's). Under Remix the tint is albedo for the path tracer: no gain.
        const bool remix = RemixApiAvailable();
        float lid = (std::max)(0.45f, 0.353f + 0.78f * (std::max)(0.0f, -sun.Direction.y));
        lid = std::round(lid * 50.0f) / 50.0f;   // a slowly moving clock sun does not re-derive every frame
        IdentitySetPaintRef(g_paintRefDev, remix ? 1.0f : g_paintGainDev * 0.96f / lid, remix ? 1.0f : (std::min)(1.0f, lid));
        // FIX-CAR-IDENTITY-6: the cast the post's hemisphere term lays over a lid (src/post_fx.cpp SetSky + ps_composite:
        // lerp(1, skyTint, 0.30) at a face looking straight up, skyTint from the same weather-adjusted zenith and
        // horizon the sky dome is drawn with), luminance 1, for the paint tint to take out (identity.cpp). The van's
        // remap-36 green drew 16 degrees toward teal with it, at the sprite's hue without it (hemisphere=0, fci6_hemi1).
        // Rounded so a slowly moving clock does not re-derive every car each frame. [devtools] paint_sky_cast=0: off.
        float cast[3] = {1.0f, 1.0f, 1.0f};
        const gta2::VisualsSettings& vs = gta2::VisualsConfig();
        const gta2::SkySettings& skyCfg = gta2::SkyConfig();
        if (!remix && g_paintSkyCast && vs.enabled && vs.hemisphere && skyCfg.enabled) {
            float elevation = skyCfg.sunElevationDeg, azimuth = skyCfg.sunAzimuthDeg;
            if (skyCfg.followClock) TimeOfDayAngles(&elevation, &azimuth);
            gta2::SkyColours sc = gta2::ComputeSkyColours(elevation, azimuth);
            gta2::SkySettings ss = skyCfg;
            gta2::WeatherAdjustSky(&sc, &ss);
            const gta2::Vec3 skyMix = sc.zenith * 0.6f + sc.horizon * 0.4f;
            const float l = (std::max)(0.02f, 0.2126f * skyMix.x + 0.7152f * skyMix.y + 0.0722f * skyMix.z);
            const float tintSky[3] = {(0.55f + 0.45f * skyMix.x / l) * 1.04f, (0.55f + 0.45f * skyMix.y / l) * 1.04f,
                                      (0.55f + 0.45f * skyMix.z / l) * 1.04f};
            for (int k = 0; k < 3; ++k) cast[k] = 1.0f + 0.30f * (tintSky[k] - 1.0f);
            const float cl = 0.2126f * cast[0] + 0.7152f * cast[1] + 0.0722f * cast[2];
            for (int k = 0; k < 3; ++k) cast[k] = std::round(cast[k] / (std::max)(0.05f, cl) * 100.0f) / 100.0f;
        }
        static float lastCast[3] = {-1.0f, -1.0f, -1.0f};
        if (cast[0] != lastCast[0] || cast[1] != lastCast[1] || cast[2] != lastCast[2]) {
            static int castLogs = 0;
            if (castLogs++ < 40) Log("car bodies: paint sky cast %.2f,%.2f,%.2f (the post's hemisphere term on a lid; the tint takes it out)", cast[0], cast[1], cast[2]);
            for (int k = 0; k < 3; ++k) lastCast[k] = cast[k];
        }
        IdentitySetPaintCast(cast);
    }
    // QB-19: a blast nearby lights the bodies orange while it flashes (plain renderer only;
    // under Remix the fireball's emissive particles do it).
    bool blastLit = false;
    {
        float lp[3], lc[3], range = 0.0f;
        if (!RemixApiAvailable() && ExplosionFxLight(lp, lc, &range)) {
            D3DLIGHT9 blast = {};
            blast.Type = D3DLIGHT_POINT;
            blast.Diffuse = {lc[0], lc[1], lc[2], 1.0f};
            blast.Position = {lp[0], lp[1], lp[2]};
            blast.Range = range;
            blast.Attenuation0 = 1.0f;
            blast.Attenuation2 = 16.0f / (range * range);
            device->SetLight(1, &blast);
            device->LightEnable(1, TRUE);
            blastLit = true;
        }
    }
    D3DMATERIAL9 material = {};
    material.Diffuse = {1.0f, 1.0f, 1.0f, 1.0f};
    material.Ambient = {1.0f, 1.0f, 1.0f, 1.0f};
    material.Specular = {0.6f, 0.6f, 0.6f, 1.0f};
    material.Power = g_paintSpecPower;
    device->SetMaterial(&material);
    device->SetRenderState(D3DRS_LIGHTING, TRUE);
    device->SetRenderState(D3DRS_AMBIENT, D3DCOLOR_XRGB(static_cast<int>(0x5A * carTod[0] + 0.5f), static_cast<int>(0x5A * carTod[1] + 0.5f),
                                                       static_cast<int>(0x5A * carTod[2] + 0.5f)));
    device->SetRenderState(D3DRS_SPECULARENABLE, TRUE);
    device->SetRenderState(D3DRS_LOCALVIEWER, TRUE);
    device->SetRenderState(D3DRS_NORMALIZENORMALS, TRUE);
    device->SetRenderState(D3DRS_COLORVERTEX, FALSE);
    device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_SPECULARMATERIALSOURCE, D3DMCS_MATERIAL);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);

    int builtThisFrame = 0;
    if (g_devIni[0] && frame % 60 == 0) {
        g_forceModel = GetPrivateProfileIntA("devtools", "force_car_model", -1, g_devIni);
        g_forceOwnModel = GetPrivateProfileIntA("devtools", "force_own_car_model", -1, g_devIni);
        g_cabInterior = GetPrivateProfileIntA("devtools", "cab_interior", 1, g_devIni);
        g_driverGlass = GetPrivateProfileIntA("devtools", "driver_glass", 1, g_devIni);
        g_bandInterior = GetPrivateProfileIntA("devtools", "band_interior", 1, g_devIni);
        g_glassSeat = GetPrivateProfileIntA("devtools", "glass_seat", 1, g_devIni);
        g_tyreContactDev = GetPrivateProfileIntA("devtools", "tyre_shadows", 1, g_devIni);
        g_shellWheels = GetPrivateProfileIntA("devtools", "shell_wheels", 1, g_devIni);
        g_forceSteerDeg = GetPrivateProfileIntA("devtools", "force_steer_deg", 0, g_devIni);
        g_forceDamage = GetPrivateProfileIntA("devtools", "force_car_damage", -1, g_devIni);
        g_hoodDropDark = GetPrivateProfileIntA("devtools", "hood_drop_dark", 1, g_devIni) != 0;
        g_fpBonnet = GetPrivateProfileIntA("devtools", "fp_bonnet", 1, g_devIni);
        g_hoodDash = GetPrivateProfileIntA("devtools", "hood_dash", 1, g_devIni);
        // FIX-REMIX-NIGHT-2: remix_cab_albedo=0 draws the cab the old way under Remix (same-session A/B).
        g_cabRemixAlbedo = GetPrivateProfileIntA("devtools", "remix_cab_albedo", 1, g_devIni) != 0;
        // FIX-REMIX-MATERIALS-7: the floor pan under Remix (PanSplitFor; 1 = as before).
        g_remixUnderpan = GetPrivateProfileIntA("devtools", "remix_underpan", 3, g_devIni);
        {
            char fp[64] = {};
            GetPrivateProfileStringA("devtools", "force_car_paint", "", fp, sizeof(fp), g_devIni);
            int r = -1, g = -1, bl = -1, r2 = -1, g2 = -1, b2 = -1;
            const int got = sscanf(fp, "%d,%d,%d,%d,%d,%d", &r, &g, &bl, &r2, &g2, &b2);
            if (got < 3) r = g = bl = -1;
            if (got < 6) { r2 = r; g2 = g; b2 = bl; }
            g_forceCarPaint[0] = r; g_forceCarPaint[1] = g; g_forceCarPaint[2] = bl;
            g_forceCarPaintBright[0] = r2; g_forceCarPaintBright[1] = g2; g_forceCarPaintBright[2] = b2;
        }
        // FIX-CAR-IDENTITY-4: the paint's reference (1 the model's panels with no clip, 0 the c8ba78f mean) for
        // same-spot A/B frames; re-derives every car record when it changes.
        g_paintRefDev = GetPrivateProfileIntA("devtools", "paint_ref", 1, g_devIni);
        IdentitySetLiveryGain(GetPrivateProfileIntA("devtools", "livery_gain", 1, g_devIni) != 0);
        IdentitySetPaintSatHold(static_cast<float>(GetPrivateProfileIntA("devtools", "paint_sat_hold", 40, g_devIni)));
        g_paintGainDev = static_cast<float>(GetPrivateProfileIntA("devtools", "paint_gain_percent", 125, g_devIni)) / 100.0f;
        g_paintSkyCast = GetPrivateProfileIntA("devtools", "paint_sky_cast", 1, g_devIni) != 0;   // FIX-CAR-IDENTITY-6 A/B
        g_paintSpecPower = static_cast<float>((std::max)(4, static_cast<int>(GetPrivateProfileIntA("devtools", "paint_spec_power", 50, g_devIni))));
        g_forceDoor = GetPrivateProfileIntA("devtools", "force_car_door", 0, g_devIni);
        g_doorExactCut = GetPrivateProfileIntA("devtools", "door_exact_cut", 1, g_devIni);
        g_doorInterior = GetPrivateProfileIntA("devtools", "door_interior", 1, g_devIni);
        g_doorTopCut = GetPrivateProfileIntA("devtools", "door_top_cut", 1, g_devIni);
        g_fpSeatFreeze = GetPrivateProfileIntA("devtools", "fp_seat_freeze", 1, g_devIni);
        g_fpSeatLock = GetPrivateProfileIntA("devtools", "fp_seat_lock", FpSeatLockDefault(), g_devIni);
        g_forceOwnLift = GetPrivateProfileIntA("devtools", "force_own_lift", 0, g_devIni);
        g_seatedSep = GetPrivateProfileIntA("devtools", "seated_sep", 0, g_devIni);
        {   // VEHICLE-GLASS: the glass on/off within one session, for same-spot before/after frames.
            const int glassKey = GetPrivateProfileIntA("devtools", "car_glass", -1, g_devIni);
            if (glassKey >= 0) CarGlassSetEnabled(glassKey);
        }
        g_forceSirens = GetPrivateProfileIntA("devtools", "force_sirens", 0, g_devIni);
        {
            const int quads = GetPrivateProfileIntA("devtools", "remix_beacon_quads", 0, g_devIni);
            if (quads != g_remixBeaconQuads) { g_remixBeaconQuads = quads; Log("devtools: Remix siren beacon glow quads %s", quads ? "on (old)" : "off"); }
            const int cap = GetPrivateProfileIntA("devtools", "remix_beacon_cap_milli", 22, g_devIni);
            if (cap != g_remixBeaconCapMilli) { g_remixBeaconCapMilli = cap; Log("devtools: Remix siren beacon cap %d/1000 tile", cap); }
        }
        g_carWorldSunDev = GetPrivateProfileIntA("devtools", "car_world_sun", -1, g_devIni);
        // [devtools] vehicle_feel=0|1 (VEHICLE-FEEL): the feel off or on while the game
        // runs, for before/after frames of one scene; absent leaves it as it is.
        const int feelKey = GetPrivateProfileIntA("devtools", "vehicle_feel", -1, g_devIni);
        if (feelKey >= 0) { VehicleFxSetEnabled(feelKey != 0); g_feelIniSet = true; }
        VehicleFxSetPhysics(GetPrivateProfileIntA("devtools", "vehicle_physics", -1, g_devIni));
        VehicleFxSetFeel2(GetPrivateProfileIntA("devtools", "vehicle_feel2", -1, g_devIni));
        VehicleFxForceLean(GetPrivateProfileIntA("devtools", "force_body_pitch_deg", 0, g_devIni),
                           GetPrivateProfileIntA("devtools", "force_body_roll_deg", 0, g_devIni));
        VehicleFxSetLean(GetPrivateProfileIntA("renderer", "car_body_pitch", 220, g_devIni),
                         GetPrivateProfileIntA("renderer", "car_body_roll", 170, g_devIni));
    }
    VehicleFxSetDark(g_lampDark);
    const bool feelOn = VehicleFxEnabled();
    if (g_logNoses < 0) { char v[8] = {}; g_logNoses = GetEnvironmentVariableA("GTA2DX9_LOG_CAR_NOSES", v, sizeof v) ? atoi(v) : 0; }
    if (g_logOverlap < 0) { char v[8] = {}; g_logOverlap = GetEnvironmentVariableA("GTA2DX9_LOG_CAR_OVERLAP", v, sizeof v) ? atoi(v) : 0; }
    if (g_devIni[0] && frame % 60 == 0) {
        const int sep = GetPrivateProfileIntA("renderer", "car_separation", 1, g_devIni);
        if (sep != g_separate) Log("car bodies: separation %s (%s)", sep ? "on" : "off", g_devIni);
        g_separate = sep;
    }
    if (frame != g_feetFrame) { g_feetPrev.swap(g_feetCur); g_feetCur.clear(); g_feetFrame = frame; }
    for (const CarBodyUse& use : cars) {
        bool effect = false;
        const double ta = CarNowMs();
        IDirect3DTexture9* art = DeviceTextureFor(device, use.texture, &effect, true);
        {
            const double ms = CarNowMs() - ta;
            static int slowArtLogged = 0;
            if (ms > 8.0 && slowArtLogged < 60) { ++slowArtLogged; Log("car bodies: the sprite artwork of a car took %.1f ms to fetch (sprite %d)", ms, use.sprite); }
        }
        // While its door is busy (a ped at it, or a boarding driving it) the car keeps the body
        // measured before the door started: the door-animation frames' artwork is not ready, not
        // measurable, or (aee_k2front) measured in another palette, which painted the car orange
        // for 8 frames. A respray or a dent happens with the door idle and is measured as before.
        int busySide = 0; float busyTarget = 0.0f, busyRate = 0.0f;
        const bool doorBusy = use.doorPed || BoardingDoor(use.object, &busySide, &busyTarget, &busyRate);
        auto last = g_lastBuilt.find(use.object);
        const bool haveLast = last != g_lastBuilt.end() && frame - last->second.second < 90 && last->second.first->measured &&
                              last->second.sprite == use.sprite && last->second.model == use.model;
        Built* b = nullptr;
        if (doorBusy && haveLast) {
            b = last->second.first;
        } else {
            b = art ? Measured(device, use, art, frame) : nullptr;
            if (b && !doorBusy) {
                g_lastBuilt[use.object] = {b, frame, use.sprite, use.model};
            } else if (!b && haveLast) {
                b = last->second.first;
                static int logged = 0;
                if (logged++ < 20) Log("car bodies: sprite %d's artwork not ready (%s); its last measured body stands in", use.sprite, art ? "unmeasured" : "building");
            }
        }
        if (b && haveLast && b == last->second.first) { b->used = frame; last->second.second = frame; }
        if (g_lastBuilt.size() > 512) {
            for (auto it = g_lastBuilt.begin(); it != g_lastBuilt.end();) it = frame - it->second.second > 90 ? g_lastBuilt.erase(it) : std::next(it);
        }
        if (!b) continue;
        gta2::Mat4 carToWorldM = Mul(CarToLocal(use), use.objectToWorld);
        // FIX-SEAT-ENTRY-4 (tri11 probe): [devtools] force_own_lift=N raises the driven car's drawn body N
        // hundredths of a block (a body standing on what it reversed into), for same-spot seat checks.
        if (g_forceOwnLift && use.driven) carToWorldM.m[3][1] += 0.01f * static_cast<float>(g_forceOwnLift);
        const gta2::Mat4 carToWorld = carToWorldM;
        if (g_logNoses && frame % 15 == 0) {
            // The placement's nose (+z of the car frame) in the world, before any
            // model's own `forward`; the checker pairs consecutive samples of one
            // object into a velocity and compares it with this direction.
            const Model* lm = (use.sprite >= 65 && use.sprite <= 74) ? nullptr : ModelForVehicle(g_forceModel >= 0 && !use.own ? g_forceModel : use.model, use.sprite);
            Log("car nose: obj=%08x sprite=%d model=%d f=%+d x=%.3f z=%.3f nx=%.3f nz=%.3f own=%d frame=%u",
                static_cast<unsigned>(use.object), use.sprite, use.model, lm ? (lm->forward < 0 ? -1 : 1) : 0,
                carToWorld.m[3][0], carToWorld.m[3][2], carToWorld.m[2][0], carToWorld.m[2][2], use.own ? 1 : 0, frame);
        }
        // A car behind the camera costs its whole transform and clip on the
        // software driver for nothing on screen; the margin covers a bus.
        if (!use.own && BehindView(carToWorld.m[3][0], carToWorld.m[3][1], carToWorld.m[3][2], 2.5f)) continue;
        // feel29 (FIX-SEAT-ENTRY-3): the driven car's pixels carry stencil bit 0x80, where the post pass eases
        // the sun-shadow mask over ~10 frames ([visuals] car_shadow_blend). Only the plain renderer's post
        // target has a stencil the pass reads; elsewhere the mark is never read.
        {
            const bool markIt = use.driven && gta2::VisualsConfig().carShadowBlend && !RemixApiAvailable();
            device->SetRenderState(D3DRS_STENCILENABLE, markIt ? TRUE : FALSE);
            if (markIt) {
                device->SetRenderState(D3DRS_STENCILFUNC, D3DCMP_ALWAYS);
                device->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_REPLACE);
                device->SetRenderState(D3DRS_STENCILFAIL, D3DSTENCILOP_KEEP);
                device->SetRenderState(D3DRS_STENCILZFAIL, D3DSTENCILOP_KEEP);
                device->SetRenderState(D3DRS_STENCILREF, 0x80u);
                device->SetRenderState(D3DRS_STENCILWRITEMASK, 0x80u);
            }
        }
        D3DMATRIX wm;
        // The camera inside this car (standing at a parked car's door in the chase
        // view): the body would fill the screen with its underside. Not the own car:
        // from the driver's seat the models are solid hulls with painted windows, so
        // everything above a hand's breadth below the eye is clipped away and what
        // is left - hood, fenders, the cowl - is the view over a dashboard.
        const bool inside = Inside(carToWorld, eye, 0.5f * b->bodyWidth, 0.5f * b->bodyLength, 1.4f * b->bodyWidth);
        // Nor the car he drives: a chase camera at the sedan distance sits inside a
        // fire truck or a bus (run a33_fire1: the truck vanished from the chase view).
        if (inside && !use.own && !use.driven) continue;
        bool clipped = false;
        // The hood-only copy is drawn on both paths (Remix ignores user clip planes;
        // on plain D3D9 the plane below still trims the copy's edge exactly).
        const bool cpuCut = inside && use.own;
        {
            // FIX-SEAT-ENTRY-4 (tri11): GTA2DX9_LOG_SEAT=1, a line per frame for the driven car: the seat
            // view's gate (eye inside the box, the own flag) and the eye in the car's frame.
            static int logSeat = -1;
            if (logSeat < 0) { char v[8] = {}; logSeat = GetEnvironmentVariableA("GTA2DX9_LOG_SEAT", v, sizeof v) ? atoi(v) : 0; }
            if (logSeat && (use.driven || use.own)) {
                const float dx = eye.x - carToWorld.m[3][0], dy = eye.y - carToWorld.m[3][1], dz = eye.z - carToWorld.m[3][2];
                Log("seat gate: f=%u obj=%p driven=%d own=%d inside=%d eye car-frame x=%.3f y=%.3f z=%.3f (half w %.3f l %.3f) view=%d",
                    frame, reinterpret_cast<const void*>(use.object), use.driven ? 1 : 0, use.own ? 1 : 0, inside ? 1 : 0,
                    dx * carToWorld.m[0][0] + dy * carToWorld.m[0][1] + dz * carToWorld.m[0][2],
                    dx * carToWorld.m[1][0] + dy * carToWorld.m[1][1] + dz * carToWorld.m[1][2],
                    dx * carToWorld.m[2][0] + dy * carToWorld.m[2][1] + dz * carToWorld.m[2][2],
                    0.5f * b->bodyWidth, 0.5f * b->bodyLength, static_cast<int>(CurrentViewMode()));
            }
        }
        float eyeLocalX = 0.0f, eyeLocalY = 0.0f, eyeLocalZ = 0.0f;
        if (cpuCut) {
            // The eye in the car's own frame: along its right, up and forward axes.
            const float rx = carToWorld.m[0][0], ry = carToWorld.m[0][1], rz = carToWorld.m[0][2];
            const float ux = carToWorld.m[1][0], uy = carToWorld.m[1][1], uz = carToWorld.m[1][2];
            const float fx = carToWorld.m[2][0], fy = carToWorld.m[2][1], fz = carToWorld.m[2][2];
            const float dx = eye.x - carToWorld.m[3][0], dy = eye.y - carToWorld.m[3][1], dz = eye.z - carToWorld.m[3][2];
            const float ul = ux * ux + uy * uy + uz * uz, fl = fx * fx + fy * fy + fz * fz;
            eyeLocalY = ul > 1e-8f ? (dx * ux + dy * uy + dz * uz) / ul : 0.0f;
            eyeLocalZ = fl > 1e-8f ? (dx * fx + dy * fy + dz * fz) / fl : 0.0f;
            const float rl = rx * rx + ry * ry + rz * rz;
            eyeLocalX = rl > 1e-8f ? (dx * rx + dy * ry + dz * rz) / rl : 0.0f;
            // FIX-INCAR-1 (tri11, pfl25): with the seat lock (below) the eye is at the learned seat point of the posed
            // body every frame, so the cuts of the hood dash, the bonnet and the dash are made there, not at the eye
            // measured in the unposed frame (that moved with the body's pose and the seat correction, and the hood dash
            // rebuilt on a dent step at a hit was cut ~15 degrees low for half a second: run cam9_p28a f63-f64).
            if (g_fpSeatLock && use.own && g_seatRef.car == use.object && g_seatRef.frames >= 5 && CurrentViewMode() == ViewMode::FirstPerson) {
                eyeLocalX = g_seatRef.x; eyeLocalY = g_seatRef.y; eyeLocalZ = g_seatRef.z;
            }
        }
        if (inside && use.own && !RemixApiAvailable()) {
            const float ux = carToWorld.m[1][0], uy = carToWorld.m[1][1], uz = carToWorld.m[1][2];
            const float ul = std::sqrt(ux * ux + uy * uy + uz * uz);
            if (ul > 1e-6f) {
                const float nx = -ux / ul, ny = -uy / ul, nz = -uz / ul;   // keep what lies below
                const float margin = 0.035f;
                const float px_ = eye.x + ux / ul * -margin, py_ = eye.y + uy / ul * -margin, pz_ = eye.z + uz / ul * -margin;
                // Fixed-function clip planes are given in world space when no vertex shader is bound.
                const float plane[4] = {nx, ny, nz, -(nx * px_ + ny * py_ + nz * pz_)};
                device->SetClipPlane(0, plane);
                device->SetRenderState(D3DRS_CLIPPLANEENABLE, 1u);
                clipped = true;
            }
        }
        struct ClipOff {
            IDirect3DDevice9* device; bool on;
            ~ClipOff() { if (on) device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0u); }
        } clipOff{device, clipped};

        // A hand-made model for this vehicle: placed on the sprite's footprint,
        // its painted parts in the car's own colour.
        // IDENTITY-SYSTEM: model and paint are the vehicle's identity record (identity.cpp),
        // derived from what the classic view draws: the game's model number (a burnt-out car's
        // wreck sprite 65..74 standing for CARI 72..81) and the paint measured from its sprite.
        const bool forcedModel = !g_wreckTest && ((g_forceModel >= 0 && !use.own) ||
                                                  (g_forceOwnModel >= 0 && !WreckModelNumber(g_forceOwnModel) && use.own));
        const int modelNumber = (use.sprite >= 65 && use.sprite <= 74) ? IdentityVehicleModelNumber(use.model, use.sprite)
                                : g_wreckTest ? 72 + (use.sprite % 10)
                                : (g_forceModel >= 0 && !use.own) ? g_forceModel
                                : (g_forceOwnModel >= 0 && !WreckModelNumber(g_forceOwnModel) && use.own) ? g_forceOwnModel : use.model;
        SpriteRef vref;
        vref.carModel = modelNumber;
        vref.carSprite = use.sprite;
        // VEHICLE-ART-3: the game's own model number while the car is whole (identity remembers it
        // for the wreck it may become; a devtools-forced model is not the car's).
        vref.wholeModel = (use.sprite >= 65 && use.sprite <= 74) || WreckModelNumber(use.model) ? -1 : use.model;
        const bool forcedPaint = g_forceCarPaint[0] >= 0;   // devtools force_car_paint (a livery keeps its own)
        // A model forced by the devtools keeps its own paint, unless a paint is forced too.
        vref.forcedModel = forcedModel && !forcedPaint && !(use.sprite >= 65 && use.sprite <= 74);
        {
            vref.paint[0] = forcedPaint ? static_cast<float>(g_forceCarPaint[0]) : b->paint.r;
            vref.paint[1] = forcedPaint ? static_cast<float>(g_forceCarPaint[1]) : b->paint.g;
            vref.paint[2] = forcedPaint ? static_cast<float>(g_forceCarPaint[2]) : b->paint.b;
        }
        // A forced paint stands for a body's mean paint (the remap rule every remapped sprite has since c8ba78f), so
        // force_car_paint=133,65,65 on model 13 is the wil red Minx's record (FIX-CAR-IDENTITY-4's probe).
        vref.paintMean = b->paintMasked || forcedPaint;
        vref.palette = forcedPaint ? -1 : b->palette;
        for (int k = 0; k < 3; ++k)
            vref.paintBright[k] = forcedPaint ? static_cast<float>(g_forceCarPaintBright[k]) : vref.paintMean ? (&b->measure.paint.r)[k] : vref.paint[k];
        if (use.driven && use.texture) {
            // FIX-CAR-IDENTITY-5 (pmt4): what the driven car's paint input is, each time it changes.
            static uintptr_t lastObj = 0; static const void* lastPx = nullptr; static int lastPal = -1; static const Built* lastB = nullptr;
            const TextureRecord* rec = static_cast<const TextureRecord*>(use.texture);
            if (lastObj != use.object || lastPx != rec->pixels || lastPal != rec->palette || lastB != b) {
                static int n = 0;
                if (n++ < 200)
                    Log("identity: driven car art obj %08x sprite %d palette %d pixels %p art %p measured %.0f,%.0f,%.0f damage %d fire %d",
                        static_cast<unsigned>(use.object), use.sprite, rec->palette, rec->pixels, static_cast<const void*>(art), b->paint.r, b->paint.g,
                        b->paint.b, use.damage, use.fireStage);
                lastObj = use.object; lastPx = rec->pixels; lastPal = rec->palette; lastB = b;
            }
        }
        IdentitySetPaintFloor(g_paintLumFloor);
        const double tIdent = CarNowMs();
        const IdentityRecord& ident = IdentityForVehicle(use.object, vref, use.driven);
        g_carParts[kPartIdentity] += CarNowMs() - tIdent;
        if (const Model* model = ident.model) {
            const float modelLen = (std::max)(model->Length(), 0.01f), modelWid = (std::max)(model->Width(), 0.01f);
            const bool sideways = modelWid > modelLen * 1.3f;   // modelled along x rather than z
            const float along = sideways ? modelWid : modelLen, across = sideways ? modelLen : modelWid;
            float sz = b->bodyLength / along, sx = b->bodyWidth / across;
            {
                // The footprint is the sprite's; a model with different proportions
                // would be stretched one way. Keep its shape: the aspect may change
                // by 15 % at most, the rest overhangs or falls short of the sprite.
                constexpr float kMaxAspect = 1.15f;
                const float s = std::sqrt(sx * sz);
                float r = sx / sz;
                r = (std::max)(1.0f / kMaxAspect, (std::min)(kMaxAspect, r));
                sx = s * std::sqrt(r);
                sz = s / std::sqrt(r);
            }
            const float sy = std::sqrt(sx * sz);
            gta2::Mat4 fit;
            const float f = model->forward;
            if (!sideways) {
                fit.m[0][0] = sx; fit.m[1][1] = sy; fit.m[2][2] = sz * f;
            } else {
                fit.m[0][2] = sz * f; fit.m[1][1] = sy; fit.m[2][0] = -sx;
            }
            fit.m[3][1] = -model->boundsMin.y * sy;
            fit.m[3][3] = 1.0f;
            // The car's paint over the model's own (the record's): what its painted textures are
            // multiplied by. Not for a livery (cop car, taxi, ambulance, fire truck, buses, the
            // service vans, the army's): its model is painted in the livery, which a remap would
            // recolour (REMIX-3: under Remix the tint is applied too,
            // rtx.enableMultiStageTextureFactorBlending). Nor for a model forced by the devtools.
            // FIX-CAR-RENDER (pm3-dark-vehicle-bodies): a near-black paint is held at a luminance
            // floor (hue kept), and a dark body gets a broader, stronger sheen below.
            // FIX-CAR-IDENTITY-5 (pmt5): a livery with the lid-light gain (identity.cpp) is drawn through the tint stage
            // like painted cars (a uniform factor: its colours kept); a livery at tint 1 (Remix, livery_gain=0) as before.
            const bool keepOwnPaint = ident.livery && ident.paintTint[0] == 1.0f && ident.paintTint[1] == 1.0f && ident.paintTint[2] == 1.0f;
            const float* tint = ident.paintTint;
            const float darkness = ident.darkness;
            D3DMATERIAL9 carMaterial = material;
            if (darkness > 0.0f) {
                // A sky-tinted sheen (added after the texture, so a dark albedo cannot swallow it).
                carMaterial.Specular = {0.6f + 0.35f * darkness, 0.6f + 0.40f * darkness, 0.6f + 0.50f * darkness, 1.0f};
                carMaterial.Power = material.Power + (12.0f - material.Power) * darkness;
                // and more of the sky on the faces turned from the sun.
                const float amb = 1.0f + 0.3f * darkness;
                carMaterial.Ambient = {amb, amb, amb, 1.0f};
            }
            {
                CarPartTimer partTimer(kPartCabin);
                const float roof = model->Height() * sy;
                const float cy = 0.5f * b->measure.h;
                Cabin cabin{0.62f * roof, roof, (b->measure.cabinFront - cy) * b->scale, 0.5f * b->bodyWidth, frame,
                            b->bodyLength, roof};
                // A tall or long body (taller than a sedan's roof by a quarter, or a
                // third longer): the driver's cab from the model's own profile.
                if ((roof > 0.45f || b->bodyLength > 1.3f) && !WreckModelNumber(modelNumber)) {
                    const CabShape cab = CabShapeFor(*model, fit, modelNumber);
                    if (cab.valid) {
                        cabin.deck = cab.deck;
                        cabin.roof = cab.roof;
                        cabin.windscreen = cab.windscreen;
                        cabin.length = (std::max)(cab.length, b->bodyLength);
                        cabin.height = cab.height;
                        cabin.flat = cab.flat;
                    }
                }
                // QB-5: the eye over the bonnet (see BonnetTopFor). Only the player's car
                // is measured (the eye sits in no other), only for whole models.
                // FIX-SEAT-ENTRY-2 (fp-first-entry black frames): the car he drives, in every view, not
                // only once it is drawn from the seat. The first-person eye is placed from last frame's
                // cabin (CarBodiesCabin), and the chase view's cabin had no lift, so the move into the
                // seat and its first frames put the eye at the unlifted height: in the 068 van 0.47,
                // under the dashboard's top (0.506), and the dash filled the screen black for 3-4 frames
                // until the seat's own cabin (0.57) came through.
                if ((use.own || use.driven) && !WreckModelNumber(modelNumber)) {
                    const float bonnet = BonnetTopFor(*model, fit, cabin.windscreen);
                    // eye = deck + 0.62 (roof - deck); the cut is 0.035 under it: a deck
                    // 0.03 over the bonnet leaves the bonnet whole under the cut.
                    if (bonnet + 0.03f > cabin.deck) {
                        cabin.deck = bonnet + 0.03f;
                        cabin.roof = (std::max)(cabin.roof, cabin.deck + 0.08f);
                    }
                }
                g_cabins[use.object] = cabin;
            }
            // A livery is drawn with no tint stage at all (the same picture as a tint of 1).
            ModelSetPaintTint(keepOwnPaint ? nullptr : tint);
            // A baked texture split into paint and the rest (import_assets.py's
            // paint_split) is two alpha-tested draws of the same mesh.
            device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
            device->SetRenderState(D3DRS_ALPHAREF, 128u);
            device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
            const double tm = CarNowMs();
            // Under Remix the own car is its hood-only copy (see HoodModelFor); the
            // same cuts the clip planes make elsewhere: a hand below the eye, a hand
            // ahead of it.
            // Wear: the damage byte in four steps, dents and a duller paint.
            const int damageWord = g_forceDamage >= 0 ? g_forceDamage : use.damage;
            const int dentStep = DentStepFor(damageWord);
            // Burning (stage 3, from 16000) and burning hard (stage 4, from 25000): the paint
            // scorched toward soot, on top of the dents' dulling.
            // From the word too: the game sets the stage only when a hit crosses 16000.
            const int fireStage = (std::max)(g_forceDamage >= 0 ? 0 : use.fireStage, damageWord >= 25000 ? 4 : damageWord >= 16000 ? 3 : 0);
            // VEHICLE-ART-3: a burning car is about to be a wreck: its charred copy (and that copy's textures,
            // one a frame, and its glass masks) is made now, not in the frame it blows up.
            if (fireStage >= 3 && !WreckModelNumber(modelNumber) && !forcedModel)
                if (const Model* charred = CarWreckCopyOf(*model)) ModelPrepareOneTexture(device, *charred);
            if (use.driven) {
                // The player's car: a line whenever its wear changes (the 40-line budget
                // above is spent by the traffic in seconds).
                static int lastStep = -1, lastFire = -1;
                if (dentStep != lastStep || fireStage != lastFire) {
                    Log("car bodies: the player's car (model %d) at damage %d: dent step %d, fire stage %d", modelNumber, damageWord, dentStep, fireStage);
                    lastStep = dentStep; lastFire = fireStage;
                }
            }
            const double tWear = CarNowMs();
            if (!WreckModelNumber(modelNumber)) DentQueueAhead(*model);
            const Model* worn = dentStep > 0 && !WreckModelNumber(modelNumber) ? DentedModelFor(*model, dentStep) : model;
            g_carParts[kPartWear] += CarNowMs() - tWear;
            if ((dentStep > 0 || fireStage >= 3) && !ident.wreck) {
                const float dull = (1.0f - 0.06f * static_cast<float>(dentStep)) * (fireStage >= 4 ? 0.45f : fireStage >= 3 ? 0.70f : 1.0f);
                if (ModelSoftPaintActive()) {
                    // Soft paint: the wear darkens the whole body (paint, trim and glass), not only
                    // the paint texels (two tones on a burning car otherwise).
                    carMaterial.Diffuse = {dull, dull, dull, 1.0f};
                    carMaterial.Ambient = {carMaterial.Ambient.r * dull, carMaterial.Ambient.g * dull, carMaterial.Ambient.b * dull, 1.0f};
                } else {
                    const float tintWorn[3] = {tint[0] * dull, tint[1] * dull, tint[2] * dull};
                    ModelSetPaintTint(tintWorn);
                }
                if (g_damageLogged < 40) { ++g_damageLogged; Log("car bodies: object %p damage %d (fire stage %d) -> dent step %d", reinterpret_cast<const void*>(use.object), damageWord, fireStage, dentStep); }
            }
            if (ident.wreck) {
                // Burnt paint and bare metal: matte, a faint dull sheen only.
                carMaterial.Specular = {0.10f, 0.09f, 0.08f, 1.0f};
                carMaterial.Power = 6.0f;
            }
            const bool carMaterialSet = memcmp(&carMaterial, &material, sizeof(material)) != 0;
            if (carMaterialSet) device->SetMaterial(&carMaterial);
            const Model* drawn = worn;
            const HoodCopy* hood = nullptr;
            const BonnetSurface* seatBonnet = nullptr;
            if (cpuCut) {
                const Cabin& cab = g_cabins[use.object];
                static int seatLogged = 0, seatModel = -1;
                if (seatModel != modelNumber && seatLogged < 100) {
                    ++seatLogged; seatModel = modelNumber;
                    Log("car bodies: driver's seat of model %d: eye x=%.3f y=%.3f z=%.3f, deck %.3f, roof %.3f, windscreen %+.3f",
                        modelNumber, eyeLocalX, eyeLocalY, eyeLocalZ, cab.deck, cab.roof, cab.windscreen);
                }
                // FIX-FP: the seat's bonnet as a clean surface (BonnetSurfaceFor) on the plain renderer
                // (FIX-PERF-3: decided before the hood, which is then only measured for its dash).
                const bool flatSeat = g_cabInterior && !WreckModelNumber(modelNumber) && CabClassFor(modelNumber, cab.flat) == CabClass::Bus;
                if (!flatSeat && g_fpBonnet && (!RemixApiAvailable() || g_cabRemixAlbedo) && !WreckModelNumber(modelNumber)) {
                    CarPartTimer partTimer(kPartSeatBonnet);
                    const float top = BonnetTopFor(*worn, fit, cab.windscreen);
                    if (top > 0.02f) {
                        const BonnetSurface& bs = BonnetSurfaceFor(*worn, fit, cab.windscreen, top + 0.005f);
                        if (bs.valid) seatBonnet = &bs;
                    }
                }
                CarPartTimer partTimer(kPartHood);
                if ((seatBonnet || flatSeat) && g_hoodDash) {
                    // The hood copy would not be drawn (the bonnet, or the cab alone): its dash only.
                    hood = &HoodDashFor(*worn, fit, eyeLocalY - 0.035f, eyeLocalZ + 0.10f, eyeLocalX);
                } else {
                    hood = &HoodModelFor(*worn, fit, eyeLocalY - 0.035f, eyeLocalZ + 0.10f, eyeLocalX);
                    drawn = hood->model;
                }
            } else if (use.driven && g_fpBonnet && (!RemixApiAvailable() || g_cabRemixAlbedo) && !WreckModelNumber(modelNumber) &&
                       !(g_cabInterior && CabClassFor(modelNumber, g_cabins[use.object].flat) == CabClass::Bus)) {
                // FIX-PERF-3: at the wheel in another view: the seat's bonnet made ahead on the worker.
                CarPartTimer partTimer(kPartSeatBonnet);
                const Cabin& cab = g_cabins[use.object];
                const float top = BonnetTopFor(*worn, fit, cab.windscreen);
                if (top > 0.02f) SeatBonnetAhead(*worn, fit, cab.windscreen, top + 0.005f);
            }
            // FIX-SEAT-ENTRY-2 (fp-first-entry): while the camera moves down into the driver's seat, the
            // seat view's parts are made ahead for the seat's eye, once per model: the hood copy or its
            // dash, and one unseen draw of the cab (colour and depth writes off), which loads the hands'
            // model and its textures and has the cab's states compiled by the driver. The first frame in
            // the seat built them on the render thread (213 ms on the 068 van, run seat2_van2: the frame
            // before held for 0.2 s). Plain renderer only (Remix would capture the unseen draw).
            gta2::Vec3 seatEye{};
            if (!cpuCut && use.driven && g_cabInterior && !RemixApiAvailable() && !WreckModelNumber(modelNumber) &&
                SeatMoveEye(&seatEye)) {
                static std::set<int> warmed;
                if (warmed.size() < 128 && warmed.insert(modelNumber).second) {
                    const double tw = CarNowMs();
                    const float* r = carToWorld.m[0]; const float* u = carToWorld.m[1]; const float* f = carToWorld.m[2];
                    const float rl = r[0] * r[0] + r[1] * r[1] + r[2] * r[2], ul = u[0] * u[0] + u[1] * u[1] + u[2] * u[2],
                                fl = f[0] * f[0] + f[1] * f[1] + f[2] * f[2];
                    const float dx = seatEye.x - carToWorld.m[3][0], dy = seatEye.y - carToWorld.m[3][1], dz = seatEye.z - carToWorld.m[3][2];
                    const float sx2 = rl > 1e-8f ? (dx * r[0] + dy * r[1] + dz * r[2]) / rl : 0.0f;
                    const float sy2 = ul > 1e-8f ? (dx * u[0] + dy * u[1] + dz * u[2]) / ul : 0.0f;
                    const float sz2 = fl > 1e-8f ? (dx * f[0] + dy * f[1] + dz * f[2]) / fl : 0.0f;
                    const Cabin& cab = g_cabins[use.object];
                    const bool flatSeat = CabClassFor(modelNumber, cab.flat) == CabClass::Bus;
                    const bool bonnetSeat = !flatSeat && g_fpBonnet && BonnetTopFor(*worn, fit, cab.windscreen) > 0.02f;
                    const HoodCopy& wh = (bonnetSeat || flatSeat) && g_hoodDash ? HoodDashFor(*worn, fit, sy2 - 0.035f, sz2 + 0.10f, sx2)
                                                                                 : HoodModelFor(*worn, fit, sy2 - 0.035f, sz2 + 0.10f, sx2);
                    const double th = CarNowMs();
                    CabInteriorParams cp;
                    cp.cls = CabClassFor(modelNumber, cab.flat);
                    cp.eyeX = sx2; cp.eyeY = sy2; cp.eyeZ = sz2;
                    cp.zCut = sz2 + 0.10f;
                    cp.dashTop = wh.dash ? wh.dashTop : sy2 - 0.043f;
                    cp.dashX0 = wh.dash ? wh.dashX0 : -0.45f * b->bodyWidth;
                    cp.dashX1 = wh.dash ? wh.dashX1 : 0.45f * b->bodyWidth;
                    cp.night = g_lampDark;
                    cp.openTop = CabOpenTop(modelNumber);
                    cp.taxi = modelNumber == 51 || modelNumber == 56;
                    cp.warm = true;
                    DWORD colourWrite = 0, zWrite = 0;
                    device->GetRenderState(D3DRS_COLORWRITEENABLE, &colourWrite);
                    device->GetRenderState(D3DRS_ZWRITEENABLE, &zWrite);
                    device->SetRenderState(D3DRS_COLORWRITEENABLE, 0u);
                    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
                    DrawCabInterior(device, carToWorld, cp, material);
                    device->SetRenderState(D3DRS_COLORWRITEENABLE, colourWrite);
                    device->SetRenderState(D3DRS_ZWRITEENABLE, zWrite);
                    device->SetMaterial(carMaterialSet ? &carMaterial : &material);
                    Log("car bodies: seat move: the seat view of %s made ahead (hood %.1f ms, cab %.1f ms)", worn->name.c_str(), th - tw,
                        CarNowMs() - th);
                }
            }
            // VEHICLE-FEEL: the sprung body and the turning wheels (see vehicle_fx.h).
            const float roofH = model->Height() * sy;
            const bool wreckModel = WreckModelNumber(modelNumber);
            // The CARI axles along the body (b->wheelZ is only set for the sprite-built bodies).
            const float axleF = (b->measure.wheelFront - 0.5f * b->measure.h) * b->scale;
            const float axleR = (b->measure.wheelRear - 0.5f * b->measure.h) * b->scale;
            WheelSplit wheels;
            bool haveWheels = false;
            if (feelOn && !wreckModel && !cpuCut && modelNumber != 54 && modelNumber != 17) {
                const float ex = carToWorld.m[3][0] - eye.x, ez = carToWorld.m[3][2] - eye.z;
                if (ex * ex + ez * ez < 22.0f * 22.0f || use.driven) {
                    CarPartTimer partTimer(kPartWheels);
                    haveWheels = WheelReady(*worn, fit, axleF, axleR, 0.5f * b->bodyWidth, roofH, &wheels);
                }
            }
            VehicleFxCar fxCar;
            fxCar.object = use.object;
            fxCar.carToWorld = &carToWorld;
            fxCar.length = b->bodyLength; fxCar.width = b->bodyWidth; fxCar.roof = roofH;
            fxCar.wheelbase = (std::max)(axleF - axleR, 0.3f * b->bodyLength);
            fxCar.wheelRadius = haveWheels && wheels.n ? wheels.radius[0] : (std::max)(0.055f, (std::min)(0.13f, 0.21f * roofH));
            fxCar.rigidWheels = !(haveWheels && !wheels.shell);   // FIX-VEHICLE-FEEL-2: cut wheels hang from the body
            fxCar.damage = use.damage;
            fxCar.wreck = wreckModel;
            fxCar.driven = use.driven;
            fxCar.paint[0] = b->paint.r / 255.0f; fxCar.paint[1] = b->paint.g / 255.0f; fxCar.paint[2] = b->paint.b / 255.0f;
            if (fireStage >= 3) for (float& c : fxCar.paint) c *= 0.5f;
            if (haveWheels) {
                LastWheels& lw = g_lastWheels[use.object];
                lw.split = wheels; lw.fit = fit; lw.frame = frame;
            }
            if (wreckModel) {
                // The wheel that flies off: one of the car's own, from a corner the wreck has lost.
                auto lw = g_lastWheels.find(use.object);
                if (lw != g_lastWheels.end() && frame - lw->second.frame < 60) {
                    const int lost = WreckLostCorners(*model);
                    for (int w = 0; w < lw->second.split.n; ++w) {
                        const gta2::Vec3& c = lw->second.split.centre[w];
                        const int corner = (c.z >= 0.0f ? 0 : 2) + (c.x >= 0.0f ? 1 : 0);
                        if (!lost || (lost & (1 << corner))) {
                            fxCar.wheelPart = lw->second.split.wheel[w];
                            fxCar.fit = lw->second.fit;
                            fxCar.wheelCentre = c;
                            break;
                        }
                    }
                }
            }
            const double tFeel = CarNowMs();
            const VehicleFeel& feel = VehicleFxUpdate(fxCar, frame);
            g_carParts[kPartFeel] += CarNowMs() - tFeel;
            // The drawn footprint: the model's bounds through the fit, in the car frame.
            CarFoot foot;
            {
                float xs[4], zs[4];
                const gta2::Vec3& lo = model->boundsMin; const gta2::Vec3& hi = model->boundsMax;
                for (int k = 0; k < 4; ++k) {
                    const float px_ = (k & 1) ? hi.x : lo.x, pz_ = (k & 2) ? hi.z : lo.z;
                    xs[k] = px_ * fit.m[0][0] + pz_ * fit.m[2][0] + fit.m[3][0];
                    zs[k] = px_ * fit.m[0][2] + pz_ * fit.m[2][2] + fit.m[3][2];
                }
                foot.object = use.object;
                foot.x0 = (std::min)((std::min)(xs[0], xs[1]), (std::min)(xs[2], xs[3]));
                foot.x1 = (std::max)((std::max)(xs[0], xs[1]), (std::max)(xs[2], xs[3]));
                foot.z0 = (std::min)((std::min)(zs[0], zs[1]), (std::min)(zs[2], zs[3]));
                foot.z1 = (std::max)((std::max)(zs[0], zs[1]), (std::max)(zs[2], zs[3]));
                foot.cx = carToWorld.m[3][0]; foot.cy = carToWorld.m[3][1]; foot.cz = carToWorld.m[3][2];
                // VEHICLE-GLASS: where the drawn body meets the road (its lowest point through the fit), for
                // the contact shadow; the game's sprite plane is the car's own height, inside the body.
                foot.ground = (model->boundsMin.y * fit.m[1][1] + fit.m[3][1]) * carToWorld.m[1][1] + carToWorld.m[3][1];
                const float rl = std::sqrt(carToWorld.m[0][0] * carToWorld.m[0][0] + carToWorld.m[0][2] * carToWorld.m[0][2]);
                const float fl = std::sqrt(carToWorld.m[2][0] * carToWorld.m[2][0] + carToWorld.m[2][2] * carToWorld.m[2][2]);
                if (rl > 1e-6f) { foot.rx = carToWorld.m[0][0] / rl; foot.rz = carToWorld.m[0][2] / rl; }
                if (fl > 1e-6f) { foot.fx = carToWorld.m[2][0] / fl; foot.fz = carToWorld.m[2][2] / fl; }
                foot.boxHalfL = 0.5f * b->bodyLength; foot.boxHalfW = 0.5f * b->bodyWidth;
                foot.pinned = cpuCut;
                // GTA2's train (59-61) runs as cars overlapping by 0.41 block at each
                // coupling (fv_ov_after1); a truck cab (63, 64) and its trailer (55 tanker,
                // 65 container, 66 transporter) overlap at the hitch.
                foot.linked = (modelNumber >= 59 && modelNumber <= 61) || modelNumber == 63 || modelNumber == 64 ||
                              modelNumber == 55 || modelNumber == 65 || modelNumber == 66;
                if (haveWheels)
                    for (int w = 0; w < wheels.n && foot.wheels < 6; ++w) {
                        const gta2::Vec3& c = wheels.centre[w];
                        const gta2::Vec3 g = PointBy(carToWorld, c.x, c.y - wheels.radius[w], c.z);
                        foot.wx[foot.wheels] = g.x; foot.wz[foot.wheels] = g.z; foot.wr[foot.wheels] = wheels.radius[w];
                        ++foot.wheels;
                    }
                g_feetCur.push_back(foot);
                if (g_fitLogged.insert({modelNumber, use.sprite}).second && g_fitLogged.size() < 400)
                    Log("car fit: model %d sprite %d: drawn %.3f x %.3f (front %+.3f, back %+.3f, sides %+.3f %+.3f) over the game's box %.3f x %.3f blocks",
                        modelNumber, use.sprite, foot.z1 - foot.z0, foot.x1 - foot.x0, foot.z1 - foot.boxHalfL, -foot.z0 - foot.boxHalfL,
                        -foot.x0 - foot.boxHalfW, foot.x1 - foot.boxHalfW, b->bodyLength, b->bodyWidth);
            }
            // Separation: against last frame's footprints of the cars near this one, the
            // least push that clears each overlap (2D separating axes), this car taking half
            // (all of it against the pinned own car, none when pinned itself); eased, capped.
            gta2::Mat4 sepMove = gta2::Identity();
            if ((g_separate || g_logOverlap > 0) && !wreckModel) {
                float tx = 0.0f, tz = 0.0f;
                auto centre = [](const CarFoot& c, float* x, float* z, float* hx, float* hz) {
                    const float lx = 0.5f * (c.x0 + c.x1), lz = 0.5f * (c.z0 + c.z1);
                    *x = c.cx + c.rx * lx + c.fx * lz; *z = c.cz + c.rz * lx + c.fz * lz;
                    *hx = 0.5f * (c.x1 - c.x0); *hz = 0.5f * (c.z1 - c.z0);
                };
                float ax_, az_, ahx, ahz;
                centre(foot, &ax_, &az_, &ahx, &ahz);
                for (const CarFoot& o : g_feetPrev) {
                    if (o.object == use.object || (foot.linked && o.linked)) continue;
                    // Another level: the elevated train over the street, a car on a ramp or bridge
                    // above (fv_ov_dense0: cars "inside" the train overhead by 0.5 block in plan).
                    if (std::fabs(foot.cy - o.cy) > 0.45f) continue;
                    float bx_, bz_, bhx, bhz;
                    centre(o, &bx_, &bz_, &bhx, &bhz);
                    const float dx = ax_ - bx_, dz = az_ - bz_;
                    if (dx * dx + dz * dz > 9.0f) continue;
                    const float axes[4][2] = {{foot.rx, foot.rz}, {foot.fx, foot.fz}, {o.rx, o.rz}, {o.fx, o.fz}};
                    float best = 1e9f, nx = 0.0f, nz = 0.0f;
                    for (const auto& n : axes) {
                        const float ra = ahx * std::fabs(foot.rx * n[0] + foot.rz * n[1]) + ahz * std::fabs(foot.fx * n[0] + foot.fz * n[1]);
                        const float rb = bhx * std::fabs(o.rx * n[0] + o.rz * n[1]) + bhz * std::fabs(o.fx * n[0] + o.fz * n[1]);
                        const float d = dx * n[0] + dz * n[1];
                        const float pen = ra + rb - std::fabs(d);
                        if (pen <= 0.0f) { best = 0.0f; break; }
                        if (pen < best) { best = pen; nx = d >= 0.0f ? n[0] : -n[0]; nz = d >= 0.0f ? n[1] : -n[1]; }
                    }
                    if (best <= 0.0f || best > 1e8f) continue;
                    const float share = !g_separate || foot.pinned || foot.linked ? 0.0f : (o.pinned || o.linked) ? 1.0f : 0.5f;
                    tx += nx * best * share; tz += nz * best * share;
                    if (g_logOverlap > 0 && frame % 15 == 0) {
                        // The game's own boxes, for comparison: how much of it they overlap themselves.
                        float gbest = 1e9f;
                        for (const auto& n : axes) {
                            const float ra = foot.boxHalfW * std::fabs(foot.rx * n[0] + foot.rz * n[1]) + foot.boxHalfL * std::fabs(foot.fx * n[0] + foot.fz * n[1]);
                            const float rb = o.boxHalfW * std::fabs(o.rx * n[0] + o.rz * n[1]) + o.boxHalfL * std::fabs(o.fx * n[0] + o.fz * n[1]);
                            const float d = (foot.cx - o.cx) * n[0] + (foot.cz - o.cz) * n[1];
                            gbest = (std::min)(gbest, ra + rb - std::fabs(d));
                        }
                        // What is left on screen with both cars' current pushes (last frame's eased values).
                        const auto pa = g_push.find(use.object), pb = g_push.find(o.object);
                        const float sa = pa != g_push.end() && frame - pa->second.frame < 3 ? pa->second.x * nx + pa->second.z * nz : 0.0f;
                        const float sb = pb != g_push.end() && frame - pb->second.frame < 3 ? pb->second.x * nx + pb->second.z * nz : 0.0f;
                        Log("car overlap: %08x (model %d) with %08x: drawn %.3f blocks, game boxes %.3f, push %.3f,%.3f, left on screen %.3f",
                            static_cast<unsigned>(use.object), modelNumber, static_cast<unsigned>(o.object), best, gbest, nx * best * share, nz * best * share,
                            (std::max)(0.0f, best - sa + sb));
                    }
                }
                const float tl = std::sqrt(tx * tx + tz * tz);
                if (tl > 0.35f) { tx *= 0.35f / tl; tz *= 0.35f / tl; }
                CarPush& ps = g_push[use.object];
                if (frame - ps.frame > 10) { ps.x = tx; ps.z = tz; }
                const float kE = (std::min)(1.0f, static_cast<float>((std::max)(1u, frame - ps.frame)) / 3.0f);
                ps.x += (tx - ps.x) * kE; ps.z += (tz - ps.z) * kE;
                ps.frame = frame;
                sepMove.m[3][0] = ps.x; sepMove.m[3][2] = ps.z;
                if (g_push.size() > 512)
                    for (auto it = g_push.begin(); it != g_push.end();) it = frame - it->second.frame > 90 ? g_push.erase(it) : std::next(it);
            }
            gta2::Mat4 posed = carToWorld;
            if (feel.on) {
                if (wreckModel) posed = Mul(VehicleFxWreckPose(WreckLostCorners(*model), b->bodyLength, b->bodyWidth, 0.075f), carToWorld);
                else if (cpuCut) {
                    // QB-5: from the driver's seat the eye does not ride the springs, so a
                    // knock's full lean (up to 0.10 rad of pitch and 0.05 of heave) lifted
                    // the bonnet through the cut a hand under the eye. A third of the
                    // pose (small angles: the matrix lerped toward the identity) still
                    // shows the jolt and keeps the bonnet under the cut.
                    // FIX-VEHICLES: the eye now rides the body (VehicleFxFirstRide, [camera]
                    // first_body_ride), so the cockpit takes the same share and the
                    // bonnet holds still under the eye while the street tilts.
                    const float share = (std::max)(0.33f, VehicleFxFirstRide());
                    gta2::Mat4 soft = gta2::Identity();
                    for (int r = 0; r < 4; ++r)
                        for (int c = 0; c < 4; ++c) soft.m[r][c] += (feel.pose.m[r][c] - soft.m[r][c]) * share;
                    posed = Mul(soft, carToWorld);
                } else posed = Mul(feel.pose, carToWorld);
            }
            posed = Mul(posed, sepMove);
            if (use.own) {
                // FIX-FP-ENTRY (pfeel32): where the first-person eye sits in this posed body. The seat point
                // (the raw eye in the car's frame) is learned while the body is level and kept while it tilts;
                // the camera is told how far the posed seat point is from its raw eye (view_modes.h).
                float& refX = g_seatRef.x; float& refY = g_seatRef.y; float& refZ = g_seatRef.z;
                uintptr_t& refCar = g_seatRef.car;
                int& refFrames = g_seatRef.frames;
                gta2::Vec3 raw;
                if (FirstPersonSeatEyeRaw(&raw)) {
                    const float* r = posed.m[0]; const float* u = posed.m[1]; const float* f = posed.m[2];
                    const float rl = r[0] * r[0] + r[1] * r[1] + r[2] * r[2], ul = u[0] * u[0] + u[1] * u[1] + u[2] * u[2],
                                fl = f[0] * f[0] + f[1] * f[1] + f[2] * f[2];
                    const float dx = raw.x - posed.m[3][0], dy = raw.y - posed.m[3][1], dz = raw.z - posed.m[3][2];
                    if (rl > 1e-8f && ul > 1e-8f && fl > 1e-8f) {
                        const float lx = (dx * r[0] + dy * r[1] + dz * r[2]) / rl, ly = (dx * u[0] + dy * u[1] + dz * u[2]) / ul,
                                    lz = (dx * f[0] + dy * f[1] + dz * f[2]) / fl;
                        const float level = u[1] / std::sqrt(ul);   // 1: upright
                        if (refCar != use.object) { refCar = use.object; refFrames = 0; }
                        // FIX-SEAT-ENTRY-4 (tri11): the seat point is learned once per car (30 level frames) and then
                        // kept. Learned on, it followed the raw eye whenever the body was level: a body standing
                        // lifted on what it reversed into (the drawn hull 0.15-0.3 block over the game's floor,
                        // level, held after the stop) taught it the low seat, the correction decayed to nothing in a
                        // second and the eye stayed under the dash, the wheel and hands out of view, the bonnet
                        // filling it. [devtools] fp_seat_freeze=0: the old learning.
                        if (level > 0.995f && !(g_fpSeatFreeze && refFrames >= 30)) {
                            const float k = refFrames < 5 ? 1.0f : 0.1f;
                            refX += (lx - refX) * k; refY += (ly - refY) * k; refZ += (lz - refZ) * k;
                            ++refFrames;
                        }
                        if (refFrames > 0) {
                            const gta2::Vec3 seat{refX * r[0] + refY * u[0] + refZ * f[0] + posed.m[3][0],
                                                  refX * r[1] + refY * u[1] + refZ * f[1] + posed.m[3][1],
                                                  refX * r[2] + refY * u[2] + refZ * f[2] + posed.m[3][2]};
                            gta2::Vec3 d{seat.x - raw.x, seat.y - raw.y, seat.z - raw.z};
                            const float len = std::sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
                            const float maxLen = g_fpSeatFreeze ? 0.5f : 0.3f;
                            if (len > maxLen) d = gta2::Vec3{d.x * maxLen / len, d.y * maxLen / len, d.z * maxLen / len};
                            SetFirstPersonSeatCorrection(d);
                            // FIX-INCAR-1 (tri11): the correction reaches the eye a frame late and eased, and over a kerb
                            // ridden in reverse the body and the eye separated by up to 0.5 block in a frame (the game
                            // lifting the car onto the kerb's lid, the eye on its eased floor; the terrain fit pitching
                            // the body 20 degrees): the wheel, the hands and the dash left the frame for ~5 s (run
                            // tri14_plates f1284-f1400). What is left this frame (the shown eye against the posed seat)
                            // moves the drawn own body so its seat is at the eye: the cockpit is where the eye is in
                            // every frame; the eye still glides to the body (above), so the shift stays a transient.
                            // [devtools] fp_seat_lock=0 (or GTA2DX9_FP_SEAT_LOCK=0): as before (A/B).
                            if (cpuCut && g_fpSeatLock && refFrames >= 5 && CurrentViewMode() == ViewMode::FirstPerson) {
                                // The drawn body's tilt beyond the eye's: riding a kerb in reverse the posed body stood
                                // 20 degrees off upright in 1.2 s cycles (level 0.937, run incar1_t11a 06:05:11-16) while
                                // the eye took 2 (VehicleFxPlayerMotion's sprung pitch and roll; the eye never takes the
                                // game's own tilt of the car): the body is turned about the seat point toward upright by
                                // the excess, so the cockpit keeps its place round the eye and the street tilts instead.
                                float tiltDeg = 0.0f;
                                {
                                    const float px = posed.m[1][0], py = posed.m[1][1], pz = posed.m[1][2];
                                    const float qx = 0.0f, qy = 1.0f, qz = 0.0f;   // the eye stands upright but for the sprung pitch and roll it takes
                                    const float pl = std::sqrt(px * px + py * py + pz * pz), ql = std::sqrt(qx * qx + qy * qy + qz * qz);
                                    if (pl > 1e-6f && ql > 1e-6f) {
                                        const float ax = px / pl, ay = py / pl, az = pz / pl, bx = qx / ql, by = qy / ql, bz = qz / ql;
                                        float kx = ay * bz - az * by, ky = az * bx - ax * bz, kz = ax * by - ay * bx;
                                        const float sn = std::sqrt(kx * kx + ky * ky + kz * kz), cs = ax * bx + ay * by + az * bz;
                                        const float theta = std::atan2(sn, cs);
                                        VehicleFxMotion vm;
                                        const float allowed = VehicleFxPlayerMotion(&vm) ? std::sqrt(vm.pitch * vm.pitch + vm.roll * vm.roll) : 0.0f;
                                        const float phi = theta - allowed;
                                        if (sn > 1e-6f && phi > 0.0035f) {
                                            tiltDeg = phi * 57.29578f;
                                            kx /= sn; ky /= sn; kz /= sn;
                                            const float c = std::cos(phi), si = std::sin(phi), t = 1.0f - c;
                                            const float rc[3][3] = {{c + t * kx * kx, t * kx * ky - si * kz, t * kx * kz + si * ky},
                                                                    {t * kx * ky + si * kz, c + t * ky * ky, t * ky * kz - si * kx},
                                                                    {t * kx * kz - si * ky, t * ky * kz + si * kx, c + t * kz * kz}};
                                            gta2::Mat4 R = gta2::Identity();
                                            for (int i2 = 0; i2 < 3; ++i2)
                                                for (int j2 = 0; j2 < 3; ++j2) R.m[i2][j2] = rc[j2][i2];
                                            gta2::Mat4 toSeat = gta2::Identity(), back = gta2::Identity();
                                            toSeat.m[3][0] = -seat.x; toSeat.m[3][1] = -seat.y; toSeat.m[3][2] = -seat.z;
                                            back.m[3][0] = seat.x; back.m[3][1] = seat.y; back.m[3][2] = seat.z;
                                            posed = Mul(Mul(Mul(posed, toSeat), R), back);
                                        }
                                    }
                                }
                                gta2::Vec3 rs{eye.x - seat.x, eye.y - seat.y, eye.z - seat.z};
                                const float rl2 = std::sqrt(rs.x * rs.x + rs.y * rs.y + rs.z * rs.z);
                                // FIX-COCKPIT-CAB-4 (qar7 O2i: the cab seen from under its dash for two frames at a wall impact): in the
                                // impact frame the game moves the car up to ~0.65 block from the eased eye (cab3_dgh_hands 15:53:19.35,
                                // 'follows the tilted body 0.647, 0.612'); the 0.6 cap left the drawn seat short of the eye, under the
                                // dash. Cap 1.5 (GTA2DX9_FP_SEAT_LOCK_MAX=<milli> A/B; 600 = before).
                                static const float lockMax = [] { char v[12] = {}; const int m = GetEnvironmentVariableA("GTA2DX9_FP_SEAT_LOCK_MAX", v, sizeof v) ? atoi(v) : 0;
                                                                  return m > 0 ? m / 1000.0f : 1.5f; }();
                                if (rl2 > lockMax) rs = gta2::Vec3{rs.x * lockMax / rl2, rs.y * lockMax / rl2, rs.z * lockMax / rl2};
                                posed.m[3][0] += rs.x; posed.m[3][1] += rs.y; posed.m[3][2] += rs.z;
                                static int logLock = -1;
                                if (logLock < 0) { char v[8] = {}; logLock = GetEnvironmentVariableA("GTA2DX9_LOG_SEAT", v, sizeof v) ? atoi(v) : 0; }
                                if (logLock) Log("seat lock: f=%u body moved %.3f,%.3f,%.3f (len %.3f) to the eye, tilt %.1f deg beyond the eye's taken out", frame, rs.x, rs.y, rs.z, rl2, tiltDeg);
                            }
                            static int logSeatD = -1;
                            if (logSeatD < 0) { char v[8] = {}; logSeatD = GetEnvironmentVariableA("GTA2DX9_LOG_SEAT", v, sizeof v) ? atoi(v) : 0; }
                            if (logSeatD)
                                Log("seat pose: f=%u level=%.4f (unposed %.4f) heave=%.3f delta=%.3f,%.3f,%.3f (len %.3f) ref=%.3f,%.3f,%.3f frames %d",
                                    frame, level, carToWorld.m[1][1] / (std::max)(1e-6f, std::sqrt(carToWorld.m[1][0] * carToWorld.m[1][0] + carToWorld.m[1][1] * carToWorld.m[1][1] + carToWorld.m[1][2] * carToWorld.m[1][2])), posed.m[3][1] - carToWorld.m[3][1], d.x, d.y, d.z, len, refX, refY, refZ, refFrames);
                            static int logs = 0;
                            if (len > 0.03f && logs < 30) { ++logs; Log("car bodies: fp seat eye follows the tilted body %.3f (level %.3f)", len, level); }
                        }
                    }
                }
            }
            // The door: swings open while someone boards or leaves, shuts after.
            const double tDoor = CarNowMs();
            DoorState& ds = g_doors[use.object];
            const float dt = (std::min)(5u, (std::max)(1u, frame - ds.frame)) / 30.0f;
            ds.frame = frame;
            if (use.doorPed && ds.open < 0.02f) {
                // Which side he stands on, in the car's frame.
                const float rx = carToWorld.m[0][0], ry = carToWorld.m[0][1], rz = carToWorld.m[0][2];
                const float dxp = use.doorPedX - carToWorld.m[3][0], dzp = use.doorPedZ - carToWorld.m[3][2];
                const float lateral = dxp * rx + 0.0f * ry + dzp * rz;
                ds.side = lateral >= 0.0f ? 1 : -1;
            }
            if (g_forceDoor != 0 && ds.open < 0.02f) ds.side = g_forceDoor > 0 ? 1 : -1;
            float target = (use.doorPed || g_forceDoor != 0) ? 1.0f : 0.0f;
            // ANIM-VEHICLE-ENTRY: a boarding figure drives the door (boarding.h): its side,
            // how far and how fast, so it opens before a leaving figure passes through it.
            float doorRate = 0.0f;
            {
                int bSide = 0; float bTarget = 0.0f;
                if (BoardingDoor(use.object, &bSide, &bTarget, &doorRate)) {
                    if (ds.open < 0.02f || bSide == ds.side) { ds.side = bSide; target = bTarget; }
                    // FIX-JACK-SEAT: the other side's door (opened for a passer-by near the car) shuts
                    // first; then the boarding's side opens. It kept the far door open through a jack.
                    else { target = 0.0f; doorRate = 3.0f; }
                } else {
                    doorRate = 0.0f;
                }
            }
            // The split comes from the worker (DoorReady): until it is there the door
            // stays shut, and a split made for an earlier dent step stands in for the
            // current one rather than shutting a door that is already open.
            DoorSplit split{nullptr, nullptr};
            bool haveSplit = false;
            float zFront = 0.0f;
            if (!cpuCut && !WreckModelNumber(modelNumber) && (target > 0.0f || ds.open > 0.02f)) {
                const float roofY = model->Height() * sy, halfW = 0.5f * b->bodyWidth;
                zFront = (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale;
                zFront = (std::min)(zFront, 0.42f * b->bodyLength);
                const float zRear = zFront - 0.27f * b->bodyLength;
                // Past kDoorSplitBytes of splits a dented car opens the door of its undented
                // copy (the store never frees a model, so the splits are capped).
                const Model* doorSource = g_doorBytes > kDoorSplitBytes ? model : worn;
                haveSplit = DoorReady(*doorSource, fit, ds.side, zFront, zRear, roofY, halfW, &split);
                if (haveSplit) { ds.last = split; ds.lastSide = ds.side; }
                else if (ds.last.body && ds.lastSide == ds.side && ModelIsKnown(ds.last.body)) { split = ds.last; haveSplit = true; }
            }
            if (target > ds.open) { if (haveSplit) ds.open = (std::min)(target, ds.open + dt * (doorRate > 0.0f ? doorRate : 2.5f)); }
            else ds.open = (std::max)(target, ds.open - dt * (doorRate > 0.0f ? doorRate : 1.7f));
            // FIX-SEAT-ENTRY-3: GTA2DX9_LOG_DOOR=1 prints every frame a door is moving or open (per-frame
            // diagnosis of an entry: which split, how far, whether the sprite's door frame had art).
            {
                static int logDoor = -1;
                if (logDoor < 0) { char v[8] = {}; logDoor = GetEnvironmentVariableA("GTA2DX9_LOG_DOOR", v, sizeof v) ? atoi(v) : 0; }
                if (logDoor && (target > 0.0f || ds.open > 0.0f))
                    Log("door: obj=%08x model=%s side=%+d open=%.3f target=%.2f rate=%.2f split=%d ped=%d sprite=%d art=%d frame=%u",
                        static_cast<unsigned>(use.object), model->name.c_str(), ds.side, ds.open, target, doorRate, haveSplit ? 1 : 0,
                        use.doorPed ? 1 : 0, use.sprite, art ? 1 : 0, frame);
            }
            // FIX-COCKPIT-BODY: from the seat (cpuCut, first person) too: boarding lets a seated figure go once its
            // car has not been published for 6 frames, a climb whose car stopped being published (the eye glides
            // inside before the plan sits him down) never reached the seat, and the seat without a boarding (a
            // warp, a start at the wheel) needs the car published this frame; his body is drawn from the eye now
            // (live_geometry). Not while he gets out of it: the exit plays on the car as it was, as before.
            if ((!cpuCut || !BoardingCarLeaving(use.object)) && !WreckModelNumber(modelNumber)) {
                const float roofY = model->Height() * sy, halfW = 0.5f * b->bodyWidth;
                float zf = (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale;
                zf = (std::min)(zf, 0.42f * b->bodyLength);
                BoardingPublishCar(use.object, posed, halfW, zf, zf - 0.27f * b->bodyLength, roofY, ds.side,
                                   haveSplit ? ds.open : 0.0f, frame);
                BoardingPublishSteer(use.object, feel.on ? feel.steer : 0.0f);   // FIX-SEATED: the driver's hands on the wheel
                BoardingPublishOpenTop(use.object, CabOpenTop(modelNumber));   // FIX-JACK-SEAT (pm19)
                // VEHICLE-ART-4 (playfeel1): an authored body's own seat, through the same fit as its mesh
                // (the 036 Schmidt's central tandem seat under the bubble, not the sprite's rear deck).
                // FIX-DRIVER-GEOM (pfl74): a generated body (no manifest seat) seats him on the front seat of the
                // cabin car_glass built behind its glass, the seat drawn through the windows (the sprite's window
                // rows put the 001 Wellard's driver on the rear deck, outside the glass). [devtools] glass_seat=0: the sprite's.
                float glassSeat[4];
                const bool fromGlass = g_glassSeat != 0 && !model->hasDriverSeat && CarGlassDriverSeat(*model, glassSeat);
                const bool ownSeat = (model->hasDriverSeat || fromGlass) && !sideways;
                const float* ms = fromGlass ? glassSeat : model->driverSeat;
                BoardingPublishSeat(use.object, ownSeat, std::fabs(ms[0]) * sx, ms[2] * sz * f, ms[1] * sy, ms[3] * sy);
                if (ownSeat) {
                    static std::set<const Model*> seatPubLogged;
                    if (seatPubLogged.size() < 40 && seatPubLogged.insert(model).second) {
                        Log("car bodies: driver's seat of %s (%s): u %.3f z %+.3f cushion %.3f headliner %.3f (the sprite's: u %.3f z %+.3f roof %.3f)",
                            model->name.c_str(), fromGlass ? "glass cabin" : "manifest", std::fabs(ms[0]) * sx, ms[2] * sz * f, ms[1] * sy, ms[3] * sy, 0.25f * b->bodyWidth,
                            zf - 0.27f * b->bodyLength + 0.38f * (std::max)(0.12f, 0.27f * b->bodyLength), roofY);
                    }
                }
                // The player's own car: both doors' splits built ahead, so the exit's door
                // opens on its first frame instead of after the worker's latency.
                if (use.driven && BoardingWarmDoors(use.object)) {
                    const Model* doorSource = g_doorBytes > kDoorSplitBytes ? model : worn;
                    DoorSplit warm{nullptr, nullptr};
                    for (int side = -1; side <= 1; side += 2) {
                        if (side == ds.side && haveSplit) continue;
                        auto& done = g_doorWarm[use.object];
                        if (done & (side > 0 ? 2 : 1)) continue;
                        if (DoorReady(*doorSource, fit, side, zf, zf - 0.27f * b->bodyLength, roofY, halfW, &warm)) done |= side > 0 ? 2 : 1;
                    }
                }
            }
            // FIX-SEATED: the models are sealed hulls with painted windows, so a driver seated in
            // one (boarding.h kSeated) was hidden. A closed car with a seated figure, seen from
            // outside (not the first-person own car; not under Remix, which ignores clip planes),
            // is drawn with clip planes in its own frame: opaque everywhere but the glasshouse - the
            // band from the belt line (0.60 of the roof) to the glass's top (0.90), from the
            // windscreen's foot to the rear window's (the game's own window rows) - which is drawn
            // at 40 % with no depth written, so the figure drawn after the cars shows through it.
            // Open-top bodies need none (he shows over the door tops).
            // VEHICLE-GLASS: a closed body with its glass found draws real windows (car_glass.h): its
            // glass texels cut from the hull, a cabin behind them, the glass after the figures.
            g_carParts[kPartDoor] += CarNowMs() - tDoor;
            const double tGlass = CarNowMs();
            const float glassDx = carToWorld.m[3][0] - eye.x, glassDz = carToWorld.m[3][2] - eye.z;
            const float glassDist = std::sqrt(glassDx * glassDx + glassDz * glassDz);
            // A seated car whose rear screen was not found keeps FIX-SEATED's band, so the driver still
            // shows from the chase camera behind it.
            // VEHICLE-GLASS-3: a game open-top whose generated body has a hard top (030) takes glass too.
            const bool glassCar = !cpuCut && !clipped && !WreckModelNumber(modelNumber) &&
                                  CarGlassReady(device, *model) && (!CabOpenTop(modelNumber) || CarGlassClosedRoof(*model)) &&
                                  (!BoardingCarSeated(use.object) || CarGlassHasRear(*model));
            if (glassCar) CarGlassBeginCut(*model, glassDist);
            bool glassCut = false;
            for (const ModelMesh& gm : model->meshes) glassCut = glassCut || (glassCar && CarGlassCutMask(gm.texture) != nullptr);
            if (!glassCut) CarGlassEndCut();   // out of range, or no cabin to show through it
            // FIX-CAR-TEX (pm70): an authored body models its own glass and cabin ("_glass" meshes, drawn
            // translucent with the seated driver behind them); FIX-SEATED's 40 % band would ghost its whole
            // glasshouse, roof pillars and all (the 040 Maurice's roof read as a see-through bubble).
            bool ownGlass = false;
            for (const ModelMesh& gm : model->meshes) ownGlass = ownGlass || gm.texture.find("_glass") != std::string::npos;
            const bool glassy = g_driverGlass && !glassCut && !ownGlass && !use.own && !cpuCut && !clipped && !WreckModelNumber(modelNumber) && !CabOpenTop(modelNumber) &&
                                !RemixApiAvailable() && BoardingCarSeated(use.object);
            g_carParts[kPartGlass] += CarNowMs() - tGlass;
            auto drawHull = [&](const Model& m, const gta2::Mat4& place) {
                CarPartTimer partTimer(kPartHull);
                if (!glassy) { if (!RemixHullDraw(device, m, place)) ModelDraw(device, m, place, nullptr, 0.0f); return; }
                const float roofY = model->Height() * sy;
                const float zA = (b->measure.cabinRear - 0.5f * b->measure.h) * b->scale, zB = (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale;
                const float zLo = (std::min)(zA, zB) - 0.02f, zHi = (std::max)(zA, zB) + 0.02f;
                // A plane across the car's axis `row` (1 up, 2 forward) at `h` along it, keeping sign * (t - h) >= 0.
                bool ok = true;
                auto plane = [&](int row, float h, float sign, float out[4]) {
                    const float ax = posed.m[row][0], ay = posed.m[row][1], az = posed.m[row][2];
                    const float al = std::sqrt(ax * ax + ay * ay + az * az);
                    if (al < 1e-6f) { ok = false; return; }
                    const float px = posed.m[3][0] + ax * h, py = posed.m[3][1] + ay * h, pz = posed.m[3][2] + az * h;
                    out[0] = sign * ax / al; out[1] = sign * ay / al; out[2] = sign * az / al;
                    out[3] = -(out[0] * px + out[1] * py + out[2] * pz);
                };
                // feel20: the band's heights from the cabin's own roof, not the model's height (the 063 cab's
                // stacks put 0.90 of it over the roof: the roof was drawn see-through).
                const BandBox bb = g_bandInterior ? MeasureBandBox(m, fit, roofY, zLo, zHi) : BandBox{};
                const float cabRoof = bb.ok ? bb.roof : roofY;
                float outside[4][4], band[4][4];
                plane(1, 0.60f * cabRoof, -1.0f, outside[0]); plane(1, 0.90f * cabRoof, 1.0f, outside[1]);
                plane(2, zLo, -1.0f, outside[2]);           plane(2, zHi, 1.0f, outside[3]);
                plane(1, 0.60f * cabRoof, 1.0f, band[0]);     plane(1, 0.90f * cabRoof, -1.0f, band[1]);
                plane(2, zLo, 1.0f, band[2]);               plane(2, zHi, -1.0f, band[3]);
                if (!ok) { ModelDraw(device, m, place, nullptr, 0.0f); return; }
                // Opaque: below the belt, above the glass, behind the rear window, ahead of the windscreen
                // (overlapping where they meet: the same surface twice at equal depth).
                for (int k = 0; k < 4; ++k) {
                    device->SetClipPlane(0, outside[k]);
                    device->SetRenderState(D3DRS_CLIPPLANEENABLE, 1u);
                    ModelDraw(device, m, place, nullptr, 0.0f);
                }
                DWORD blend = 0, src = 0, dst = 0, zw = 0, factor = 0;
                device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
                device->GetRenderState(D3DRS_SRCBLEND, &src);
                device->GetRenderState(D3DRS_DESTBLEND, &dst);
                device->GetRenderState(D3DRS_ZWRITEENABLE, &zw);
                device->GetRenderState(D3DRS_BLENDFACTOR, &factor);
                for (int k = 0; k < 4; ++k) device->SetClipPlane(k, band[k]);
                device->SetRenderState(D3DRS_CLIPPLANEENABLE, 15u);
                // feel20: an opaque dark cabin behind the band, so the street behind the car does not show
                // through it and the props drawn after the cars stay hidden behind it.
                if (g_bandInterior == 1) {
                    // The box is the band's own volume, inset into the hull; drawn without the clip planes
                    // (its far walls and floor are the band's edges).
                    if (bb.ok) {
                        device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0u);
                        DrawBandInterior(device, posed, bb.halfW, 0.60f * cabRoof, 0.90f * cabRoof, bb.z0, bb.z1, 0xFF1A1C21u);
                        device->SetRenderState(D3DRS_CLIPPLANEENABLE, 15u);
                    }
                }
                device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
                device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_BLENDFACTOR);
                device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVBLENDFACTOR);
                device->SetRenderState(D3DRS_BLENDFACTOR, 0x66666666u);
                device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
                ModelDraw(device, m, place, nullptr, 0.0f);
                device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0u);
                device->SetRenderState(D3DRS_ALPHABLENDENABLE, blend);
                device->SetRenderState(D3DRS_SRCBLEND, src);
                device->SetRenderState(D3DRS_DESTBLEND, dst);
                device->SetRenderState(D3DRS_ZWRITEENABLE, zw);
                device->SetRenderState(D3DRS_BLENDFACTOR, factor);
            };
            if (IdentityProbeOn())   // IDENTITY-SYSTEM parity probe: every car on screen, the player's as "mycar"
                IdentityProbeModel(device, use.driven ? "mycar" : "car", reinterpret_cast<const void*>(use.object), ident, *model,
                                   Mul(fit, posed).m, static_cast<int>(CurrentViewMode()));
            if (ds.open > 0.02f && haveSplit) {
                const float halfW = 0.5f * b->bodyWidth;
                drawHull(*split.body, Mul(fit, posed));
                // FIX-SEAT-ENTRY-3 (pfl16): the opening shows a cabin, not the black of the far side's liner
                // (or the street through a shell with no liner): a dark box the door's height and length,
                // only its inward-seen walls drawn (the hull hides it everywhere but the opening), and on
                // its far wall the door's own panel mirrored across the car, in the body's own textures,
                // dimmed: the far side's door seen from inside. [devtools] door_interior=0 for A/B.
                if (g_doorInterior && ds.open > 0.04f) {
                    const float roofI = model->Height() * sy;
                    const float zFrontI = zFront, zRearI = zFront - 0.27f * b->bodyLength;
                    // FIX-SEAT-ENTRY-4 (pfl18): by day a lighter tone: from the eye at the door (first person) the old
                    // one read as a black hole filling the doorway. Unlit, so the night keeps the dark one.
                    // [devtools] door_interior=2: the old tone by day too (A/B).
                    const uint32_t cabTone = g_lampDark || g_doorInterior == 2 ? 0xFF2E2B27u : 0xFF4A453Eu;
                    DrawBandInterior(device, posed, 0.80f * halfW, 0.14f * roofI, 0.88f * roofI, zRearI, zFrontI, cabTone);
                    D3DMATERIAL9 keep;
                    device->GetMaterial(&keep);
                    D3DMATERIAL9 dim = keep;
                    dim.Diffuse = {0.28f, 0.28f, 0.28f, 1.0f};
                    dim.Ambient = {0.30f, 0.30f, 0.30f, 1.0f};
                    dim.Specular = {0.0f, 0.0f, 0.0f, 1.0f};
                    dim.Emissive = {0.0f, 0.0f, 0.0f, 0.0f};
                    device->SetMaterial(&dim);
                    gta2::Mat4 mirror;
                    mirror.m[0][0] = -0.76f; mirror.m[1][1] = 1.0f; mirror.m[2][2] = 1.0f; mirror.m[3][3] = 1.0f;
                    ModelDraw(device, *split.door, Mul(Mul(fit, mirror), posed), nullptr, 0.0f);
                    device->SetMaterial(&keep);
                }
                // Swing about the vertical through the door's front edge, outward.
                const float theta = -static_cast<float>(ds.side) * ds.open * (60.0f * kPi / 180.0f);
                const float cs = std::cos(theta), sn = std::sin(theta);
                const float hx = static_cast<float>(ds.side) * 0.92f * halfW, hz = zFront;
                gta2::Mat4 hinge;
                hinge.m[0][0] = cs; hinge.m[0][2] = -sn; hinge.m[1][1] = 1.0f; hinge.m[2][0] = sn; hinge.m[2][2] = cs;
                hinge.m[3][0] = hx - (hx * cs + hz * sn); hinge.m[3][2] = hz - (-hx * sn + hz * cs); hinge.m[3][3] = 1.0f;
                ModelDraw(device, *split.door, Mul(Mul(fit, hinge), posed), nullptr, 0.0f);   // (swung: its own frame)
            } else if ((modelNumber == 54 || modelNumber == 17) && !cpuCut) {
                // The turret turned to the game's aim (see TurretSplitFor); without an
                // aim seen in the last second it stays straight ahead.
                const float roofY = model->Height() * sy;
                const TurretSplit split = modelNumber == 54 ? TurretSplitFor(*worn, fit, roofY, 0.56f, 99.0f)
                                                            : TurretSplitFor(*worn, fit, roofY, 0.80f, 0.05f * b->bodyLength);
                auto aim = g_turretAims.find(use.object);
                float yaw = 0.0f;
                if (aim != g_turretAims.end() && frame - aim->second.frame < 30) {
                    // The aim in the car's own frame: across (x) and along (z), from its world axes.
                    const float ax = carToWorld.m[0][0], az = carToWorld.m[0][2], fx = carToWorld.m[2][0], fz = carToWorld.m[2][2];
                    const float across = aim->second.dirX * ax + aim->second.dirZ * az, along = aim->second.dirX * fx + aim->second.dirZ * fz;
                    if (across * across + along * along > 1e-8f) yaw = std::atan2(across, along);
                }
                if (split.turret) {
                    ModelDraw(device, *split.hull, Mul(fit, posed), nullptr, 0.0f);
                    const float cs = std::cos(yaw), sn = std::sin(yaw);
                    const float px = split.pivotX, pz = split.pivotZ;
                    gta2::Mat4 turn;
                    turn.m[0][0] = cs; turn.m[0][2] = -sn; turn.m[1][1] = 1.0f; turn.m[2][0] = sn; turn.m[2][2] = cs;
                    turn.m[3][0] = px - (px * cs + pz * sn); turn.m[3][2] = pz - (-px * sn + pz * cs); turn.m[3][3] = 1.0f;
                    ModelDraw(device, *split.turret, Mul(Mul(fit, turn), posed), nullptr, 0.0f);
                    if (g_turretLogged < 30 && (frame % 30u) == 0 && std::fabs(yaw) > 0.05f) {
                        ++g_turretLogged;
                        Log("car bodies: model %d turret turned %.0f deg (object %p)", modelNumber, yaw * 180.0f / kPi, reinterpret_cast<const void*>(use.object));
                    }
                } else {
                    drawHull(*drawn, Mul(fit, posed));
                }
            } else if (haveWheels) {
                // The hull on its springs, the wheels on the road: each about its own axle,
                // the front pair steered.
                drawHull(*wheels.hull, Mul(fit, posed));
                for (int w = 0; w < wheels.n; ++w) {
                    const gta2::Vec3& c = wheels.centre[w];
                    gta2::Mat4 spin = gta2::Identity();
                    const float cs = std::cos(feel.spin), sn = std::sin(feel.spin);
                    spin.m[1][1] = cs; spin.m[1][2] = sn; spin.m[2][1] = -sn; spin.m[2][2] = cs;
                    if (wheels.shell) {
                        // A shell's tyre and hub (its copy stays in the hull, so nothing opens): spin about
                        // its centre and, VEHICLE-ART-6, the front pair steers about its upright again,
                        // in the hull's own frame a hair outboard.
                        const float st = c.z > 0.0f ? (g_forceSteerDeg ? static_cast<float>(g_forceSteerDeg) * kPi / 180.0f : feel.steer) : 0.0f;
                        gta2::Mat4 m = spin;
                        if (st != 0.0f) {
                            gta2::Mat4 steer = gta2::Identity();
                            const float cst = std::cos(st), snt = std::sin(st);
                            steer.m[0][0] = cst; steer.m[0][2] = snt; steer.m[2][0] = -snt; steer.m[2][2] = cst;
                            m = Mul(spin, steer);
                        }
                        m.m[3][0] = c.x - (c.x * m.m[0][0] + c.y * m.m[1][0] + c.z * m.m[2][0]) + (c.x >= 0.0f ? 1.0f : -1.0f) * 0.004f;
                        m.m[3][1] = c.y - (c.x * m.m[0][1] + c.y * m.m[1][1] + c.z * m.m[2][1]);
                        m.m[3][2] = c.z - (c.x * m.m[0][2] + c.y * m.m[1][2] + c.z * m.m[2][2]);
                        ModelDraw(device, *wheels.wheel[w], Mul(Mul(fit, m), posed), nullptr, 0.0f);
                        if (wheels.ring[w] && st != 0.0f) {
                            // the tyre ring steers only: an image-to-3D tyre has no tread to show a spin, and a
                            // spun ring would swing the dark arch pieces caught in it round the wheel
                            gta2::Mat4 r = gta2::Identity();
                            const float cst = std::cos(st), snt = std::sin(st);
                            r.m[0][0] = cst; r.m[0][2] = snt; r.m[2][0] = -snt; r.m[2][2] = cst;
                            r.m[3][0] = c.x - (c.x * cst - c.z * snt) + (c.x >= 0.0f ? 1.0f : -1.0f) * 0.004f;
                            r.m[3][2] = c.z - (c.x * snt + c.z * cst);
                            ModelDraw(device, *wheels.ring[w], Mul(Mul(fit, r), posed), nullptr, 0.0f);
                        }
                        continue;
                    }
                    // VEHICLE-PHYSICS: each corner's own lift (kerb strike, off the
                    // ground), camber and toe (a bent corner) on top of spin and steer.
                    const int corner = (c.z >= 0.0f ? 0 : 2) + (c.x >= 0.0f ? 1 : 0);
                    const float steerA = (c.z > 0.0f ? (g_forceSteerDeg ? static_cast<float>(g_forceSteerDeg) * kPi / 180.0f : feel.steer) : 0.0f) + feel.wheelToe[corner];
                    gta2::Mat4 steer = gta2::Identity();
                    if (steerA != 0.0f) {
                        const float cst = std::cos(steerA), snt = std::sin(steerA);
                        steer.m[0][0] = cst; steer.m[0][2] = snt; steer.m[2][0] = -snt; steer.m[2][2] = cst;
                    }
                    gta2::Mat4 m = Mul(spin, steer);
                    if (feel.wheelCamber[corner] != 0.0f) {
                        // Top outward: about the car's z axis, away from the centre line.
                        const float ca = (c.x >= 0.0f ? -1.0f : 1.0f) * feel.wheelCamber[corner];
                        const float cc = std::cos(ca), sc = std::sin(ca);
                        gta2::Mat4 camber = gta2::Identity();
                        camber.m[0][0] = cc; camber.m[0][1] = sc; camber.m[1][0] = -sc; camber.m[1][1] = cc;
                        m = Mul(m, camber);
                    }
                    m.m[3][0] = c.x - (c.x * m.m[0][0] + c.y * m.m[1][0] + c.z * m.m[2][0]);
                    m.m[3][1] = c.y - (c.x * m.m[0][1] + c.y * m.m[1][1] + c.z * m.m[2][1]) + feel.wheelLift[corner];
                    m.m[3][2] = c.z - (c.x * m.m[0][2] + c.y * m.m[1][2] + c.z * m.m[2][2]);
                    // FIX-VEHICLE-FEEL-2 (pmy1): the wheel hangs from the posed body (it rolls and pitches with
                    // it, under its arch) and its spring takes it back toward the road, at most the travel
                    // the pose was bounded by: on a kerb or in a hard stop it never stands outside its arch
                    // or hangs below the sill, and it stays on the road.
                    gta2::Mat4 hang = carToWorld;
                    if (feel.wheelTravel > 0.0f) {
                        const gta2::Mat4& P = feel.pose;
                        const float arch = c.x * P.m[0][1] + c.y * P.m[1][1] + c.z * P.m[2][1] + P.m[3][1];
                        const float lim = feel.wheelTravel + 0.004f;
                        const float dy = (std::max)(-lim, (std::min)(lim, c.y + feel.wheelLift[corner] - arch));
                        gta2::Mat4 drop = gta2::Identity();
                        drop.m[3][1] = dy;
                        hang = Mul(Mul(P, drop), carToWorld);
                    }
                    ModelDraw(device, *wheels.wheel[w], Mul(Mul(Mul(fit, m), hang), sepMove), nullptr, 0.0f);
                }
            } else {
                // QB-31: from the seat of a flat-fronted body (bus, cab-over, train) the hood copy
                // is only the front panel under the windscreen, seen through the cut as a dark
                // slab past the dashboard; the cab's dashboard is all there is ahead of the glass.
                const bool flatCab = hood && g_cabInterior && !WreckModelNumber(modelNumber) &&
                                     CabClassFor(modelNumber, g_cabins[use.object].flat) == CabClass::Bus;
                // FIX-FP: the seat's bonnet (seatBonnet, found with the hood above).
                if (seatBonnet && !flatCab) {
                    const float dull = (1.0f - 0.06f * static_cast<float>(dentStep)) * (fireStage >= 4 ? 0.45f : fireStage >= 3 ? 0.70f : 1.0f);
                    const float one[3] = {1.0f, 1.0f, 1.0f};
                    const float cowl = hood->dash ? hood->dashTop : eyeLocalY - 0.045f;
                    {
                        CarPartTimer partTimer(kPartBonnetDraw);
                        // FIX-COCKPIT-CAB-3 (qav12): the seat bonnet's paint texels, sampled per ray hit from a box-filtered map,
                        // came out darker than the model's own paint (046: 0.48 against its measured mean 0.80, cab3_dawn4), so
                        // the bonnet from the seat read 2-3x darker than the same body in third. Its paint share is lifted to the
                        // model's measured paint mean (only up, at most 2.5x; once per surface). GTA2DX9_FP_BONNET_LIFT=0: off.
                        static const bool liftOn = [] { char b[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_FP_BONNET_LIFT", b, sizeof b) && b[0] == '0'); }();
                        static std::map<const BonnetSurface*, float> lifts;
                        float lift = 1.0f;
                        if (liftOn && !RemixApiAvailable()) {
                            auto li = lifts.find(seatBonnet);
                            if (li != lifts.end()) lift = li->second;
                            else {
                                const BonnetSurface& sb = *seatBonnet;
                                double sl = 0.0, sc = 0.0;
                                for (size_t q = 0; q < sb.cov.size(); ++q) {
                                    sl += sb.cov[q] * (0.30 * sb.rgb[q * 3] + 0.59 * sb.rgb[q * 3 + 1] + 0.11 * sb.rgb[q * 3 + 2]);
                                    sc += sb.cov[q];
                                }
                                float own[3], ownMean[3];
                                const bool measured = ModelOwnPaint(*worn, own, ownMean);   // false until the model's paint is measured
                                if (sc > 4.0 && sl > 1e-3 && measured) {
                                    const float want = (0.30f * ownMean[0] + 0.59f * ownMean[1] + 0.11f * ownMean[2]) / 255.0f;
                                    lift = (std::max)(1.0f, (std::min)(2.5f, static_cast<float>(want / (sl / sc))));
                                    Log("car bodies: seat bonnet of %s: paint texels %.2f against the model's paint %.2f: lifted x%.2f",
                                        worn->name.c_str(), sl / sc, want, lift);
                                }
                                if (lifts.size() > 64) lifts.clear();
                                if (measured) lifts[seatBonnet] = lift;
                            }
                        }
                        DrawBonnet(device, posed, *seatBonnet, eyeLocalZ + 0.10f, (std::min)(cowl, eyeLocalY - 0.045f), eyeLocalY - 0.04f,
                                   keepOwnPaint ? one : tint, dull, carMaterial, material, RemixApiAvailable(), lift);
                    }
                    if (IdentityProbeOn()) {
                        // FIX-CAR-IDENTITY-2: the seat's bonnet as the player's car in first person for the parity
                        // check (tools/identity_parity.py): the outline of its rows ahead of the cut, on screen.
                        std::vector<float> pts;
                        const BonnetSurface& sb = *seatBonnet;
                        // the far part only: the near rows lie behind the dash and wheel in the picture
                        const float zFar = sb.rows ? sb.z[static_cast<size_t>(sb.rows - 1)] : 0.0f;
                        const float zFrom = eyeLocalZ + 0.10f + 0.45f * (std::max)(0.0f, zFar - (eyeLocalZ + 0.10f));
                        for (int r = 0; r < sb.rows; ++r) {
                            if (sb.z[static_cast<size_t>(r)] < zFrom) continue;
                            for (float x : {sb.xl[static_cast<size_t>(r)], sb.xr[static_cast<size_t>(r)]}) {
                                const float hh = (std::min)(sb.h[static_cast<size_t>(r * sb.cols + sb.cols / 2)], eyeLocalY - 0.04f);
                                const gta2::Vec3 w = PointBy(posed, x, hh, sb.z[static_cast<size_t>(r)]);
                                pts.insert(pts.end(), {w.x, w.y, w.z});
                            }
                        }
                        IdentityProbePoints(device, "mycar", reinterpret_cast<const void*>(use.object), ident, pts.data(), static_cast<int>(pts.size() / 3), 2);
                    }
                } else if (!flatCab) {
                    drawHull(*drawn, Mul(fit, posed));
                }
                if (hood && (hood->dash || (g_cabInterior && !WreckModelNumber(modelNumber)))) {
                    const float dull = (1.0f - 0.06f * static_cast<float>(dentStep)) * (fireStage >= 4 ? 0.45f : fireStage >= 3 ? 0.70f : 1.0f);
                    const float paint[3] = {b->paint.r / 255.0f * dull, b->paint.g / 255.0f * dull, b->paint.b / 255.0f * dull};
                    if (g_cabInterior && !WreckModelNumber(modelNumber)) {
                        // QB-31: the cab from the seat, per vehicle class (cab_interior.h).
                        CabInteriorParams cp;
                        cp.cls = CabClassFor(modelNumber, g_cabins[use.object].flat);
                        cp.eyeX = eyeLocalX; cp.eyeY = eyeLocalY; cp.eyeZ = eyeLocalZ;
                        cp.zCut = eyeLocalZ + 0.10f;
                        // No dashboard line from the copy (nothing kept just ahead of the cut): the
                        // body's width, the dash just under the cut.
                        const float halfW = 0.5f * b->bodyWidth;
                        cp.dashTop = hood->dash ? hood->dashTop : eyeLocalY - 0.043f;
                        cp.dashX0 = hood->dash ? hood->dashX0 : -0.9f * halfW;
                        cp.dashX1 = hood->dash ? hood->dashX1 : 0.9f * halfW;
                        // FIX-FP-2 (pm30): the dash in the colour the car shows (its identity record's
                        // shown paint, as the classic sprite and the third-person body); b->paint is
                        // the neutral 235 every car carries at run time.
                        for (int k = 0; k < 3; ++k)
                            cp.paint[k] = (ident.shownTop[0] + ident.shownTop[1] + ident.shownTop[2] > 1.0f ? ident.shownTop[k] / 255.0f : paint[k] / dull) * dull;
                        cp.steer = feel.on ? feel.steer : 0.0f;
                        {   // FIX-COCKPIT-CAB-4 (CAB-3 order 6, DRIVER-GEOM-2 order 4): the rim and the tank's levers turn from the
                            // game's own steering keys: held, they ease to a lock in that direction (+ = left), released they
                            // hand back to the measured steer (yaw over distance), which pinned against a wall flipped sign
                            // several times a second and showed no pull for a tank pivoting in place. GTA2DX9_FP_KEY_STEER=0: off.
                            static const bool keyOn = [] { char v[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_FP_KEY_STEER", v, sizeof v) && v[0] == '0'); }();
                            static float keySteer = 0.0f;
                            constexpr float kLock = 0.45f;
                            const int keys = keyOn ? GameSteerKeys() : 0;
                            const float want = keys < 0 ? kLock : (keys > 0 ? -kLock : 0.0f);
                            keySteer += (want - keySteer) * 0.25f;
                            const float w = (std::min)(1.0f, std::fabs(keySteer) / kLock);
                            if (keyOn) cp.steer = cp.steer * (1.0f - w) + keySteer;
                            static int lastKeys = 0;
                            if (keys != lastKeys) { lastKeys = keys; Log("cab: steer keys %s (measured steer %+.3f)", keys < 0 ? "Left" : keys > 0 ? "Right" : "none", feel.steer); }
                        }
                        // FIX-DRIVER-GEOM: [devtools] force_steer_deg turns the cab's wheel too (a stopped car's hands at a fixed lock)
                        if (g_forceSteerDeg) cp.steer = static_cast<float>(g_forceSteerDeg) * kPi / 180.0f;
                        cp.speed = feel.speed;
                        cp.night = g_lampDark;
                        cp.openTop = CabOpenTop(modelNumber);
                        cp.taxi = modelNumber == 51 || modelNumber == 56;   // Taxi Xpress, Taxi
                        cp.dashcam = DashcamHidesCockpit();   // FIX-COCKPIT-BODY: the dashcam: no wheel, no hands
                        static int cabLogged = -1;
                        if (cabLogged != modelNumber) {
                            cabLogged = modelNumber;
                            Log("car bodies: cab interior of model %d: %s class, dash top %.3f (eye %.3f), x %.2f..%.2f", modelNumber,
                                CabClassName(cp.cls), cp.dashTop, eyeLocalY, cp.dashX0, cp.dashX1);
                        }
                        CarPartTimer partTimer(kPartCab);
                        CabInteriorSetRemixAlbedo(g_cabRemixAlbedo && RemixApiAvailable());
                        DrawCabInterior(device, posed, cp, material);
                    } else {
                        DrawDash(device, posed, *hood, eyeLocalZ + 0.10f, paint, material);
                    }
                }
            }
            if (glassCut) { CarPartTimer partTimer(kPartGlassInside); CarGlassDrawInterior(device, *model, Mul(fit, posed), g_lampDark); }
            CarGlassEndCut();
            g_carStats[2] += CarNowMs() - tm;
            g_carStats[6] += 1;
            device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
            ModelSetPaintTint(nullptr);
            if (carMaterialSet) device->SetMaterial(&material);
            device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
            const double tLamps = CarNowMs();
            DrawLamps(device, use, posed, b->bodyLength, b->bodyWidth, model->Height() * sy, frame, WreckModelNumber(modelNumber), feel.on ? &feel : nullptr);
            g_carParts[kPartLamps] += CarNowMs() - tLamps;
            if (!WreckModelNumber(modelNumber)) {
                GTA2_TRY {
                    DrawBeacons(device, use, posed, b->bodyLength, b->bodyWidth, model->Height() * sy, frame, modelNumber, model, &fit);
                } GTA2_EXCEPT {
                }
            }
            ++g_drawn;
            continue;
        }

        // Otherwise the body from the sprite. Building is a few milliseconds
        // each; a street of new cars is spread over frames.
        if (!b->meshBuilt && builtThisFrame >= 3) continue;
        if (!b->meshBuilt) ++builtThisFrame;
        const double tb = CarNowMs();
        const bool fresh = !b->meshBuilt;
        const bool built = BodyMesh(device, use, b);
        if (fresh) { g_carStats[1] += CarNowMs() - tb; g_carStats[5] += 1; }
        if (!built) continue;
        const double td = CarNowMs();
        const bool buffered = Buffers(device, b);
        // VEHICLE-FEEL on the sprite-built body: the same springs and turning wheels.
        VehicleFxCar fxCar;
        fxCar.object = use.object;
        fxCar.carToWorld = &carToWorld;
        fxCar.length = b->bodyLength; fxCar.width = b->bodyWidth; fxCar.roof = b->roofY;
        fxCar.wheelbase = b->wheelbase;
        fxCar.wheelRadius = (std::max)(0.03f, b->wheelY);
        fxCar.damage = use.damage;
        fxCar.wreck = use.sprite >= 65 && use.sprite <= 74;
        fxCar.driven = use.driven;
        fxCar.paint[0] = b->paint.r / 255.0f; fxCar.paint[1] = b->paint.g / 255.0f; fxCar.paint[2] = b->paint.b / 255.0f;
        const VehicleFeel& feel = VehicleFxUpdate(fxCar, frame);
        const gta2::Mat4 posed = feel.on ? Mul(feel.pose, carToWorld) : carToWorld;
        memcpy(&wm, posed.m, sizeof(wm));
        device->SetTexture(0, b->atlas);
        device->SetTransform(D3DTS_WORLD, &wm);
        if (buffered) {
            device->SetStreamSource(0, b->vb, 0, sizeof(CarBodyVertex));
            device->SetIndices(b->ib);
            device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(b->verts.size()), 0,
                                         static_cast<UINT>(b->indices.size() / 3));
            device->SetStreamSource(0, b->wvb, 0, sizeof(CarBodyVertex));
            device->SetIndices(b->wib);
        } else {
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(b->verts.size()),
                                           static_cast<UINT>(b->indices.size() / 3), b->indices.data(), D3DFMT_INDEX16,
                                           b->verts.data(), sizeof(CarBodyVertex));
        }
        g_cabins[use.object] = {b->deckY, b->roofY, (b->measure.cabinFront - 0.5f * b->measure.h) * b->scale,
                                0.5f * b->bodyWidth, frame};
        const float steer = feel.on ? feel.steer : SteerFor(use, carToWorld, b->wheelbase, frame);
        const float roll = feel.on ? feel.spin : 0.0f;
        for (int w = 0; w < 4; ++w) {
            const bool front = w < 2;
            const float x = (w & 1) ? b->wheelX : -b->wheelX;
            const float phi = front ? steer : 0.0f;
            const float cs = std::cos(phi), sn = std::sin(phi);
            const float cr = std::cos(roll), sr = std::sin(roll);
            // Rolling about the axle (x), then steered (y): [1 0 0; 0 cr sr; 0 -sr cr] x [cs 0 sn; 0 1 0; -sn 0 cs].
            gta2::Mat4 local;
            local.m[0][0] = cs;  local.m[0][2] = sn;
            local.m[1][0] = -sr * sn; local.m[1][1] = cr; local.m[1][2] = sr * cs;
            local.m[2][0] = -cr * sn; local.m[2][1] = -sr; local.m[2][2] = cr * cs;
            local.m[3][0] = x; local.m[3][1] = b->wheelY; local.m[3][2] = b->wheelZ[front ? 0 : 1]; local.m[3][3] = 1.0f;
            const gta2::Mat4 ww = Mul(local, carToWorld);
            memcpy(&wm, ww.m, sizeof(wm));
            device->SetTransform(D3DTS_WORLD, &wm);
            if (buffered) {
                device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, static_cast<UINT>(b->wheelVerts.size()), 0,
                                             static_cast<UINT>(b->wheelIndices.size() / 3));
            } else {
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(b->wheelVerts.size()),
                                               static_cast<UINT>(b->wheelIndices.size() / 3), b->wheelIndices.data(),
                                               D3DFMT_INDEX16, b->wheelVerts.data(), sizeof(CarBodyVertex));
            }
        }
        if (buffered) {
            device->SetStreamSource(0, nullptr, 0, 0);
            device->SetIndices(nullptr);
        }
        DrawLamps(device, use, posed, b->bodyLength, b->bodyWidth, b->roofY, frame, use.sprite >= 65 && use.sprite <= 74, feel.on ? &feel : nullptr);
        g_carStats[3] += CarNowMs() - td;
        g_carStats[7] += 1;
        ++g_drawn;
    }
    device->SetRenderState(D3DRS_STENCILENABLE, FALSE);   // feel29: the driven car's stencil mark ends with the cars
    // The texture budget, now and then: the game is a 32-bit process.
    if (frame % 900 == 0) {
        int count = 0;
        const size_t modelBytes = ModelsTextureBytes(&count);
        size_t atlasBytes = 0;
        for (const auto& e : g_cache) if (e.second.atlas) atlasBytes += e.second.measure.w * kAtlasScale * static_cast<size_t>(e.second.measure.h * kAtlasScale + kBandRows + kBlockRows) * 4;
        Log("car models: %d textures, %.1f MB in the managed pool; %u sprite-built atlases, %.1f MB; %d cars drawn this frame",
            count, modelBytes / 1048576.0, static_cast<unsigned>(g_cache.size()), atlasBytes / 1048576.0, g_drawn);
        Log("car wear: %d copies built on the worker (%.0f ms of its time), %.1f MB (dents %.1f in %zu copies, doors %.1f in %zu splits); frames a car waited for its copy: dent %d, door %d",
            g_wearCollected, g_wearWorkMs, static_cast<double>(g_wearBytes) / (1 << 20), static_cast<double>(g_dentBytes) / (1 << 20), g_dents.size(),
            static_cast<double>(g_doorBytes) / (1 << 20), g_doorSplits.size(), g_dentLate, g_doorLate);
        Log("car wheels: %zu wheel splits, %.1f MB; frames a car waited for its wheels: %d", g_wheelSplits.size(), static_cast<double>(g_wheelBytes) / (1 << 20), g_wheelLate);
    }
    if (g_doors.size() > 256) {
        for (auto it = g_doors.begin(); it != g_doors.end();) it = (frame - it->second.frame > 600) ? g_doors.erase(it) : std::next(it);
    }
    if (g_lastWheels.size() > 256) {
        for (auto it = g_lastWheels.begin(); it != g_lastWheels.end();) it = (frame - it->second.frame > 600) ? g_lastWheels.erase(it) : std::next(it);
    }
    // VEHICLE-FEEL: smoke, sparks, debris, skid marks, lamp pools and flying wheels.
    {
        const double tf = CarNowMs();
        VehicleFxDraw(device, eye, frame, RemixApiAvailable());
        g_carStats[3] += CarNowMs() - tf;
    }
    if (g_cabins.size() > 128) {
        for (auto it = g_cabins.begin(); it != g_cabins.end();) {
            it = (frame - it->second.frame > 600) ? g_cabins.erase(it) : std::next(it);
        }
    }
    device->LightEnable(0, FALSE);
    if (blastLit) device->LightEnable(1, FALSE);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
    device->SetRenderState(D3DRS_NORMALIZENORMALS, FALSE);
    device->SetRenderState(D3DRS_COLORVERTEX, TRUE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_CURRENT);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTexture(0, nullptr);
}

// VEHICLE-ART-3 (vr-wrecks-flat-dark-pancakes-no-car-shape): the burnt-out copy of a whole car's
// model, drawn for its wreck (identity.cpp DeriveWreck). The shape stays the car's - cabin,
// pillars, arches, wheels and tyres - on the same footprint (x and z untouched, so it never leaves
// the wreck's collision box), with:
//  - the dents of the worst damage step (BuildDented), deeper;
//  - the cabin sagged: everything above the waist pressed toward it, the roof's middle most
//    (the roof top 25-35 % lower: a burnt car's roof drops as the pillars soften);
//  - the paint split merged into one opaque surface and every texture swapped for its charred copy
//    (model_store.cpp, "wreck|" names: soot to rust over the texture's own light and shade, glass
//    burnt out to black, no paint stage at all).
Model BuildWreck(const Model& model) {
    size_t moved = 0;
    Model w = BuildDented(model, kDentSteps, &moved);
    w.name = model.name + "#wreck";
    w.splitPaint = false;
    w.paintRgb[0] = w.paintRgb[1] = w.paintRgb[2] = 235.0f;
    const float minY = model.boundsMin.y, height = (std::max)(model.Height(), 0.05f);
    const float waist = minY + 0.50f * height;
    const bool sideways = model.Width() > model.Length() * 1.3f;
    const float cx = 0.5f * (model.boundsMin.x + model.boundsMax.x), cz = 0.5f * (model.boundsMin.z + model.boundsMax.z);
    const float hx = (std::max)(0.5f * model.Width(), 0.02f), hz = (std::max)(0.5f * model.Length(), 0.02f);
    float maxY = minY;
    for (ModelMesh& mesh : w.meshes) {
        for (ModelVertex& v : mesh.vertices) {
            if (v.y > waist) {
                // 0 at the body's edges, 1 over its middle (along the car more than across).
                const float a = sideways ? (v.z - cz) / hz : (v.x - cx) / hx;   // across
                const float l = sideways ? (v.x - cx) / hx : (v.z - cz) / hz;   // along
                const float mid = (std::max)(0.0f, 1.0f - a * a) * (std::max)(0.0f, 1.0f - l * l);
                const float keep = 0.66f - 0.14f * mid;   // of the height above the waist
                const float t = (std::min)(1.0f, (v.y - waist) / (0.10f * height));   // no crease at the waist
                v.y = waist + (v.y - waist) * (1.0f - t * (1.0f - keep));
            }
            maxY = (std::max)(maxY, v.y);
        }
    }
    w.boundsMax.y = (std::max)(maxY, minY + 0.05f);
    // One opaque surface: the paint half of a split pair is merged into its rest half's charred copy.
    auto ends = [](const std::string& s, const char* tail) {
        const size_t n = strlen(tail);
        return s.size() >= n && s.compare(s.size() - n, n, tail) == 0;
    };
    std::set<std::string> rests;
    for (const ModelMesh& mesh : w.meshes) if (!ends(mesh.texture, "_paint.tga")) rests.insert(mesh.texture);
    std::vector<char> drop(w.meshes.size(), 0);
    for (size_t i = 0; i < w.meshes.size(); ++i) {
        ModelMesh& mesh = w.meshes[i];
        if (mesh.texture.empty()) continue;
        if (ends(mesh.texture, "_paint.tga")) {
            const std::string rest = mesh.texture.substr(0, mesh.texture.size() - 10) + ".tga";
            if (rests.count(rest)) { drop[i] = 1; continue; }
            mesh.texture = "wreck|" + mesh.texture;
        } else {
            const std::string paint = mesh.texture.substr(0, mesh.texture.size() - 4) + "_paint.tga";
            bool paired = false;
            for (const ModelMesh& m : model.meshes) if (m.texture == paint) { paired = true; break; }
            mesh.texture = (paired ? "wreckp|" : "wreck|") + mesh.texture;
        }
    }
    for (ModelNode& n : w.nodes) if (n.mesh >= 0 && n.mesh < static_cast<int>(drop.size()) && drop[n.mesh]) n.mesh = -1;
    return w;
}

const Model* CarWreckCopyOf(const Model& model) {
    static std::map<const Model*, const Model*> s_copies;
    auto it = s_copies.find(&model);
    if (it != s_copies.end()) return it->second;
    if (model.skinned || model.meshes.empty()) return s_copies[&model] = nullptr;
    const double t0 = CarNowMs();
    Model w = BuildWreck(model);
    size_t verts = 0;
    for (const ModelMesh& m : w.meshes) verts += m.vertices.size();
    const float h0 = model.Height(), h1 = w.Height();
    const Model* out = ModelRegisterDerived(std::move(w), true);
    CarGlassRequestMasks(model);   // its windows, burnt out in the charred textures
    Log("car bodies: wreck copy of %s: %zu vertices, height %.3f -> %.3f (%.0f %%), %.1f ms", model.name.c_str(), verts, h0, h1,
        h0 > 0.0f ? 100.0f * h1 / h0 : 0.0f, CarNowMs() - t0);
    return s_copies[&model] = out;
}

void CarBodiesSetWreckTest(bool on) { g_wreckTest = on; }
void CarBodiesSetDevIni(const char* ini) {
    if (!ini) { g_devIni[0] = 0; return; }
    strncpy(g_devIni, ini, sizeof(g_devIni) - 1);
    g_forceModel = GetPrivateProfileIntA("devtools", "force_car_model", -1, g_devIni);
    g_forceOwnModel = GetPrivateProfileIntA("devtools", "force_own_car_model", -1, g_devIni);
    g_forceDamage = GetPrivateProfileIntA("devtools", "force_car_damage", -1, g_devIni);
    g_forceDoor = GetPrivateProfileIntA("devtools", "force_car_door", 0, g_devIni);
    g_doorExactCut = GetPrivateProfileIntA("devtools", "door_exact_cut", 1, g_devIni);
    g_doorInterior = GetPrivateProfileIntA("devtools", "door_interior", 1, g_devIni);
    g_doorTopCut = GetPrivateProfileIntA("devtools", "door_top_cut", 1, g_devIni);
    g_fpSeatFreeze = GetPrivateProfileIntA("devtools", "fp_seat_freeze", 1, g_devIni);
    g_fpSeatLock = GetPrivateProfileIntA("devtools", "fp_seat_lock", FpSeatLockDefault(), g_devIni);
    g_forceOwnLift = GetPrivateProfileIntA("devtools", "force_own_lift", 0, g_devIni);
    g_seatedSep = GetPrivateProfileIntA("devtools", "seated_sep", 0, g_devIni);
}
const char* CarBodiesDevIni() { return g_devIni; }
void CarBodiesSetTurret(uintptr_t carObject, float dirX, float dirZ, uint32_t frame) {
    TurretAim& a = g_turretAims[carObject];
    a.dirX = dirX; a.dirZ = dirZ; a.frame = frame;
    if (g_turretAims.size() > 64) {
        for (auto it = g_turretAims.begin(); it != g_turretAims.end();) it = (frame - it->second.frame > 300) ? g_turretAims.erase(it) : std::next(it);
    }
}

void SetCarPaintFloor(float fraction) { g_paintLumFloor = fraction < 0.0f ? 0.0f : (fraction > 0.5f ? 0.5f : fraction) * 255.0f; }

// FIX-PERF-4: this module's caches for the `mem:` lines (mem_stats.h).
void CarBodiesMemGauges() {
    MemGauge("cb.dents", static_cast<double>(g_dents.size()), static_cast<double>(g_dentBytes));
    MemGauge("cb.doors", static_cast<double>(g_doorSplits.size()), static_cast<double>(g_doorBytes));
    MemGauge("cb.wheels", static_cast<double>(g_wheelSplits.size()), static_cast<double>(g_wheelBytes));
    // FIX-PERF-5: cb.wear is the SUM of the three above (dents + doors + wheels), not a pool of its own; all of
    // them are derived models registered with the model store, so their bytes are also inside ms.models.
    MemGauge("cb.wear", static_cast<double>(g_dents.size() + g_doorSplits.size() + g_wheelSplits.size()), static_cast<double>(g_wearBytes));
    MemGauge("cb.cache", static_cast<double>(g_cache.size()));
    MemGauge("cb.hoods", static_cast<double>(g_hoods.size() + g_hoodDashes.size()));
    MemGauge("cb.bonnets", static_cast<double>(g_bonnetSurfs.size() + g_bonnets.size()));
    MemGauge("cb.cabshapes", static_cast<double>(g_cabShapes.size()));
    MemGauge("cb.rgbmaps", static_cast<double>(g_rgbMaps.size()));
    MemGauge("cb.turrets", static_cast<double>(g_turretSplits.size() + g_panSplits.size()));
    MemGauge("cb.percar", static_cast<double>(g_lastBuilt.size() + g_steer.size() + g_cabins.size() + g_doors.size() + g_push.size() +
                                              g_turretAims.size()));
    MemGauge("cb.asked", static_cast<double>(g_dentAsked.size() + g_doorAsked.size() + g_wheelAsked.size() + g_bonnetAsked.size()));
}

}  // namespace gta2dx9
