// IDENTITY-SYSTEM: see identity.h and docs/identity-system.md.
#include "identity.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <unordered_map>

#include "car_bodies.h"
#include "log.h"
#include "model_store.h"
#include "remix_api.h"

namespace gta2dx9 {
namespace {

bool g_crowdVariety = true;
float g_paintFloor = 77.0f;
int g_paintRef = 1;          // [devtools] paint_ref: 1 the panels + no clip (FIX-CAR-IDENTITY-4), 0 the c8ba78f mean rule
float g_paintGain = 1.25f;   // the panel rule's level (car_bodies.cpp: paint_gain_percent at the lid's light)
float g_paintLid = 0.96f;    // the light on a lid (stage 0 multiplies the texel by it before the tint: the clip test)
uint32_t g_frame = 0;

uint32_t Mix(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}

struct Fnv {
    uint32_t h = 2166136261u;
    void Bytes(const void* p, size_t n) { const uint8_t* b = static_cast<const uint8_t*>(p); for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 16777619u; } }
    void Int(int v) { Bytes(&v, sizeof v); }
    void Float(float v) { Int(static_cast<int>(std::lround(v * 64.0f))); }   // 1/64: float noise never splits a record
    void Str(const char* s) { if (s) Bytes(s, strlen(s)); Int(0); }
};

uint32_t Fingerprint(const IdentityRecord& r) {
    Fnv f;
    f.Int(static_cast<int>(r.kind));
    f.Int(static_cast<int>(r.seed));
    f.Int(r.ref.remap); f.Int(r.ref.body); f.Int(r.ref.carModel); f.Int(r.ref.carSprite);
    for (float c : r.ref.paint) f.Int(static_cast<int>(std::lround(c)));
    f.Int(r.ref.forcedModel ? 1 : 0); f.Int(r.ref.paintMean ? 1 : 0);
    f.Str(r.model ? r.model->name.c_str() : "-");
    f.Int(r.zoned); f.Int(r.zoneHair); f.Int(r.tinted); f.Int(r.clothes); f.Int(r.livery);
    for (const auto& z : r.zone) for (float c : z) f.Float(c);
    for (float c : r.tint) f.Float(c);
    for (float c : r.paintTint) f.Float(c);
    f.Float(r.height); f.Float(r.width); f.Float(r.darkness);
    if (r.wreck) f.Int(1000 + r.wreckOf);
    return f.h;
}

// ---- People ------------------------------------------------------------------------

// The crowd's variety, from the record's seed (was CrowdLookFor in live_geometry.cpp, seeded by
// the sprite object's address): a build (height +-6%, width +-5%), a shade of a zoned outfit
// (+-12%), and for a civilian without zones three times in four an everyday clothes colour.
void CrowdVariety(IdentityRecord* r) {
    if (!g_crowdVariety || !r->model) return;
    const Model& model = *r->model;
    const int remap = r->ref.remap;
    const uint32_t h = Mix(r->seed ^ 0x9e3779b9u);
    r->height = 0.94f + 0.12f * static_cast<float>(h & 255) / 255.0f;
    r->width = 0.95f + 0.10f * static_cast<float>((h >> 8) & 255) / 255.0f;
    const bool civilian = remap < 0 || remap == 15 || (remap >= 18 && remap != 22);
    const float shade = 0.88f + 0.24f * static_cast<float>((h >> 24) & 255) / 255.0f;
    if (r->zoned) {
        for (int z = 0; z < 2; ++z) for (int k = 0; k < 3; ++k) r->zone[z][k] = (std::min)(2.0f, r->zone[z][k] * shade);
        return;
    }
    if (civilian && model.splitPaint && !model.pedZones && ((h >> 16) & 3) != 0 && !r->tinted) {
        static const uint8_t kClothes[][3] = {
            {38, 52, 92},    {60, 62, 66},   {28, 28, 32},   {196, 178, 140}, {92, 100, 58},  {118, 32, 44},
            {70, 104, 150},  {214, 212, 204}, {128, 130, 134}, {110, 76, 50},  {36, 80, 52},   {200, 160, 50},
            {40, 120, 124},  {176, 46, 40},  {210, 140, 160}, {140, 176, 210}, {160, 146, 104}, {90, 60, 110},
            {230, 120, 60},  {84, 40, 34},
        };
        constexpr uint32_t kN = sizeof(kClothes) / sizeof(kClothes[0]);
        const uint8_t* c = kClothes[(h >> 18) % kN];
        for (int k = 0; k < 3; ++k) {
            const float ratio = static_cast<float>(c[k]) / (std::max)(8.0f, model.paintRgb[k]);
            r->tint[k] = (std::max)(0.3f, (std::min)(2.0f, 1.0f + (ratio - 1.0f) * 0.85f));
        }
        r->tinted = true;
        r->clothes = true;
    }
}

// The colours the classic view's sprite shows on the torso and the legs, as the 3D avatar
// renders them with this record (texture reference x tint).
void Shown(IdentityRecord* r) {
    if (!r->model) return;
    const Model& m = *r->model;
    for (int k = 0; k < 3; ++k) {
        if (r->zoned) {
            r->shownTop[k] = r->zone[0][k] * m.zoneRef;
            r->shownBottom[k] = r->zone[1][k] * m.zoneRef;
        } else if (r->tinted) {
            r->shownTop[k] = r->shownBottom[k] = (std::min)(255.0f, r->tint[k] * m.paintRgb[k]);
        } else {
            const bool known = m.zoneRgb[0][0] + m.zoneRgb[0][1] + m.zoneRgb[0][2] >= 1.0f;
            r->shownTop[k] = known ? m.zoneRgb[0][k] : m.paintRgb[k];
            r->shownBottom[k] = known ? m.zoneRgb[1][k] : m.paintRgb[k];
        }
    }
}

void LogPerson(const char* what, uintptr_t cacheKey, const IdentityRecord& r, bool changed) {
    Log("identity: %s%s key %d remap %d body %d -> %s%s%s build %.2fx%.2f top %.0f,%.0f,%.0f bottom %.0f,%.0f,%.0f fp %08x",
        what, changed ? " CHANGED" : "", static_cast<int>(r.seed), r.ref.remap, r.ref.body, r.model ? r.model->name.c_str() : "(none)",
        r.zoned ? " zoned" : "", r.clothes ? " clothes" : r.tinted ? " tinted" : "", r.height, r.width, r.shownTop[0], r.shownTop[1],
        r.shownTop[2], r.shownBottom[0], r.shownBottom[1], r.shownBottom[2], r.fingerprint);
    (void)cacheKey;
}

// The type of person the sprite says he is, and from it the avatar and its colours.
IdentityRecord DerivePed(uint32_t seed, int remap, int body) {
    IdentityRecord r;
    r.kind = IdKind::Ped;
    r.seed = seed;
    r.ref.remap = remap;
    r.ref.body = body;
    const Model* hero = ModelForPedestrian();
    // The avatar within his type, dealt by his seed; never the hero's (the hero is his alone,
    // whatever the manifest's pools say).
    const Model* m = ModelForPedestrian(seed, remap);
    for (uint32_t k = 1; m && m == hero && k < 8; ++k) m = ModelForPedestrian(seed + k * 0x9e3779b9u, remap);
    for (uint32_t k = 1; m && m == hero && k < 16; ++k) m = ModelForPedestrian(seed + k * 0x85ebca6bu);
    r.model = m;
    if (!m) return r;
    float typeScale = 1.0f, typeWidth = 1.0f;
    PedTypeBuild(remap, &typeScale, &typeWidth);   // ASSET-PEDS-2: the Hulks are bigger
    r.tinted = PedRemapTint(remap, *m, r.tint);
    bool hair = false;
    if (m->pedZones && PedZoneTints(remap, *m, r.zone, &hair)) { r.zoned = true; r.zoneHair = hair; r.tinted = false; }
    CrowdVariety(&r);
    r.height *= typeScale;
    r.width *= typeWidth;
    Shown(&r);
    r.fingerprint = Fingerprint(r);
    return r;
}

IdentityRecord DerivePlayer() {
    IdentityRecord r;
    r.kind = IdKind::Player;
    r.seed = 0;
    // A developer remap override ([devtools] ped_remap_override) dresses him as that type too
    // (the showcase's subject); otherwise he is the protagonist: remap 25, the manifest's avatar.
    const int over = PedRemapEffective(-1, 0);
    r.ref.remap = over >= 0 ? over : 25;
    r.model = over >= 0 ? ModelForPedestrian(0u, over) : ModelForPedestrian();
    if (!r.model) return r;
    bool hair = false;
    if (over >= 0) r.tinted = PedRemapTint(over, *r.model, r.tint);
    if (r.model->pedZones && PedZoneTints(r.ref.remap, *r.model, r.zone, &hair)) { r.zoned = true; r.zoneHair = hair; r.tinted = false; }
    Shown(&r);
    r.fingerprint = Fingerprint(r);
    return r;
}

struct PedEntry { IdentityRecord rec; int pedId = -1, palette = -2; unsigned body = 0; uint32_t seen = 0; };
std::unordered_map<uintptr_t, PedEntry> g_peds;
IdentityRecord g_player;
uint32_t g_playerInputs = 0xFFFFFFFFu;
int g_pedLogged = 0;

// ---- Vehicles ----------------------------------------------------------------------

bool Livery(int m) {
    // The models painted in a livery, which a remap would recolour (REMIX-3): bus 11,
    // cop 12, fire truck 17, army jeep 22, hot-dog / ice-cream vans 23-27 and 85, medicar 34,
    // taxis 51 / 56, SWAT 52, tank 54, trains 59-61, TV van 67, special agent 84, karma bus 86.
    switch (m) {
        // FIX-CAR-IDENTITY-2 (pm40): not the G4 bank van (4) any more. The game remaps its body (ste draws it
        // green over the style's navy), so it is a painted car: its paint half is the saturated body only
        // (tools/car_paint_resplit.py --only 004 --min-sat 0.3: the pale roof panels and white band stay
        // in the rest), tinted to the sprite's measured body colour like any other car.
        case 11: case 12: case 17: case 22: case 23: case 24: case 25: case 26: case 27:
        // FIX-CAR-IDENTITY-3: not the TV van (67) nor the special agent car (84) any more. The game draws the TV
        // van one colour in each of six remaps (tan, light blue, red, white, purple, green): its two-tone generated
        // body was re-split as one neutral paint (car_paint_resplit.py --only 067 --hue 70 --hue-tol 60 --min-sat
        // 0.05 --flatten 0.8), tinted to the sprite. 84 draws 014 Eddy's mesh and paint (the same sprite: yellow,
        // dark grey in remap 2), so it is tinted like the Eddy.
        case 34: case 51: case 52: case 54: case 56: case 59: case 60: case 61:
        case 85: case 86: return true;
        default: return false;
    }
}

IdentityRecord DeriveVehicle(const SpriteRef& ref) {
    IdentityRecord r;
    r.kind = IdKind::Vehicle;
    r.ref = ref;
    r.model = ModelForVehicle(ref.carModel, ref.carSprite);
    r.livery = Livery(ref.carModel) || ref.forcedModel;
    const float* live = ref.paint;
    // The floor is tested on the brighter-half paint it was tuned on (the same value as `live` unless the
    // paint is the remap texels' mean, which is darker by the sprite's shading).
    const float* bright = ref.paintMean ? ref.paintBright : live;
    const float lum = 0.30f * bright[0] + 0.59f * bright[1] + 0.11f * bright[2];
    // FIX-CAR-RENDER (pm3-dark-vehicle-bodies): a near-black paint is held at a luminance
    // floor (hue kept), and a dark body gets a broader, stronger sheen.
    float lift = r.livery || lum >= g_paintFloor ? 1.0f : (std::min)(4.0f, g_paintFloor / (std::max)(lum, 8.0f));
    r.darkness = r.livery || g_paintFloor <= 0.0f ? 0.0f : (std::max)(0.0f, (std::min)(1.0f, (100.0f - lum) / 70.0f));
    // FIX-CAR-IDENTITY (2g): the model's own paint is measured from its paint texels
    // (ModelOwnPaint), not the 235 default every car had: tint = live / own makes the body's mean
    // paint the sprite's, for generated and authored bodies alike.
    float ownPaint[3] = {235.0f, 235.0f, 235.0f};
    // FIX-CAR-IDENTITY-2 (feel25): measured by the same rule on both sides. The sprite's paint from its
    // remap's texels is their plain mean, so the model's is the plain mean of its paint texels; a sprite
    // with no remap keeps the brighter-half rule on both.
    // FIX-CAR-IDENTITY-4 (feel25, rejected c8ba78f): the mean of an opaque paint atlas (013, 063, 068) takes
    // in its windows, tyres and trim, so it sits far under the panels the tint lands on: the red Minx's
    // 133,65,65 / 108 = 1.23,0.60,0.60 drove its ~230 panels to 283,139,139, clipped by the texture stage to
    // 255,139,139: salmon pink on every lit face while the record said deep red. The sprite's remap texels
    // are its body panels (lit and shaded), so the model's own reference is its panels too
    // (ModelOwnPaintPanel), and the tint is held under the level that would push the model's brightest
    // panel texel (its 97th percentile) past white in any channel: a saturated paint keeps its hue and
    // saturation on lit faces and loses a little lightness instead of turning pastel.
    float panelTop = 255.0f;
    if (r.model) {
        float brighter[3], mean[3], panel[3];
        ModelOwnPaint(*r.model, brighter, mean);
        const bool havePanel = g_paintRef == 1 && ModelOwnPaintPanel(*r.model, panel, &panelTop);
        for (int k = 0; k < 3; ++k) ownPaint[k] = ref.paintMean ? (havePanel ? panel[k] : mean[k]) : brighter[k];
        if (!havePanel) panelTop = 255.0f;
    }
    // The 3D light (ambient 0.35 + the sun on the lids, the frame's shadow/AO/sky multiply) leaves a body ~0.8
    // of its albedo seen from the classic camera: the red Minx at gain 1 drew 104,49,54 against its sprite's
    // 133,65,65, at 1.25 130,62,68 (lit lids 180,85,93 against the sprite's bonnet 181,92,90; fci4_minx2).
    // Only for the remap-texel paint (a mean against the panels); the brighter-half pair keeps its level.
    const float gain = g_paintRef == 1 && ref.paintMean ? g_paintGain : 1.0f;
    // The dark floor is a least level, not a second multiply on top of the gain (a navy sprite drew +57 % L* when
    // both applied: fci4_paint2): the floor's lift counts the gain already given.
    if (gain > 1.0f && lift > 1.0f) lift = (std::max)(1.0f, lift / gain);
    float cap = 1.0f;
    if (!r.livery && g_paintRef == 1) {
        float most = 0.0f;
        for (int k = 0; k < 3; ++k) most = (std::max)(most, gain * lift * live[k] / ownPaint[k]);
        // The texture stages clip texel x light x tint: the brightest lid texel under the lid's light.
        if (most * panelTop * g_paintLid > 250.0f) cap = 250.0f / (most * panelTop * g_paintLid);
    }
    for (int k = 0; k < 3; ++k) {
        const float own = ownPaint[k];
        r.paintTint[k] = r.livery ? 1.0f : cap * gain * lift * live[k] / own;
        // shown: the colour the lit body reads as (the gain only gives back what the 3D light takes).
        r.shownTop[k] = r.shownBottom[k] = r.livery ? own : (std::min)(255.0f, cap * lift * live[k]);
    }
    r.fingerprint = Fingerprint(r);
    return r;
}

// VEHICLE-ART-3: a wreck as the charred body of the car it was. The game turns a blown-up car
// into one of the ten wreck models (72..81, its CARI wreck byte) and draws the wreck sprite; the
// record remembers the model this vehicle had when last seen whole, and the 3D view draws that
// model's charred copy (CarWreckCopyOf: soot and rust, no paint, roof sagged, windows burnt out).
// A wreck never seen whole (a mission's parked wreck, a car that blew up off screen) gets its
// class's stand-in: a well-modelled car of the same CARI wreck class and size.
IdentityRecord DeriveWreck(const SpriteRef& ref, int whole) {
    IdentityRecord r;
    r.kind = IdKind::Vehicle;
    r.ref = ref;
    r.wreck = true;
    r.wreckOf = whole;
    const Model* base = whole >= 0 ? ModelForVehicle(whole, -1) : nullptr;
    r.model = base ? CarWreckCopyOf(*base) : nullptr;
    if (!r.model) { r.wreckOf = -1; r.model = ModelForVehicle(ref.carModel, ref.carSprite); }   // the old wreck mesh
    // No paint stage: the copy's textures are the charred colours (soot 34,30,28 to rust 96,52,30).
    r.livery = true;
    for (int k = 0; k < 3; ++k) { r.paintTint[k] = 1.0f; r.shownTop[k] = r.shownBottom[k] = k == 0 ? 52.0f : k == 1 ? 40.0f : 33.0f; }
    r.fingerprint = Fingerprint(r);
    return r;
}

// FIX-CAR-IDENTITY (feel9, pm33): the paint is measured from the sprite art the classic view draws, and
// that art changes for a frame or two at a wall hit, a door, a lamp or a dent; each re-measure used to
// re-derive the record (a new tint: the body's colour popped, and a `CHANGED` line per pop). A car keeps
// the paint it has until another one has held, within kPaintHoldTol, for kPaintHoldFrames frames (a
// respray): a flash never reaches the body. A new model, sprite or wreck state (the game re-used the
// object for another car, the car blew up) re-derives at once.
constexpr float kPaintHoldTol = 14.0f;
constexpr uint32_t kPaintHoldFrames = 45;
struct CarEntry { IdentityRecord rec; uint32_t seen = 0; int whole = -1; float cand[3] = {0, 0, 0}; uint32_t candSince = 0; bool candOn = false; };
float PaintDiff(const float* a, const float* b) {
    return (std::max)({std::fabs(a[0] - b[0]), std::fabs(a[1] - b[1]), std::fabs(a[2] - b[2])});
}
std::unordered_map<uintptr_t, CarEntry> g_cars;
std::unordered_map<uint32_t, int> g_carLogged;   // fingerprint -> times logged

// ---- Probe -------------------------------------------------------------------------
int g_probe = -1, g_probeEvery = 15;

}  // namespace

bool IdentityBakeTints() {
    static int forced = -2;
    if (forced == -2) {
        char v[8] = {};
        forced = GetEnvironmentVariableA("GTA2DX9_IDENTITY_BAKE", v, sizeof v) ? (v[0] == '1' ? 1 : 0) : -1;
    }
    const bool on = forced >= 0 ? forced == 1 : RemixApiAvailable();
    static int logged = -1;
    if (logged != (on ? 1 : 0)) { logged = on ? 1 : 0; Log("identity: figure tints %s", on ? "baked into texture copies (Remix or GTA2DX9_IDENTITY_BAKE=1)" : "by the stage-1 texture factor"); }
    return on;
}

void IdentitySetCrowdVariety(bool on) {
    if (g_crowdVariety != on) { g_crowdVariety = on; g_peds.clear(); }
}
void IdentitySetPaintFloor(float floor) {
    if (g_paintFloor != floor) { g_paintFloor = floor; g_cars.clear(); }
}
void IdentitySetPaintRef(int mode, float gain, float lid) {
    if (g_paintRef != mode || g_paintGain != gain || g_paintLid != lid) { g_paintRef = mode; g_paintGain = gain; g_paintLid = lid; g_cars.clear(); }
}

const Model* IdentityHeroModel() { return ModelForPedestrian(); }

const IdentityRecord& IdentityForPlayer() {
    // Inputs: the devtools override and the hero model (a reload of the models re-derives).
    const uint32_t inputs = static_cast<uint32_t>(PedRemapEffective(-1, 0) + 7) * 2654435761u ^
                            static_cast<uint32_t>(reinterpret_cast<uintptr_t>(ModelForPedestrian()));
    if (inputs != g_playerInputs) {
        const bool changed = g_playerInputs != 0xFFFFFFFFu;
        const uint32_t before = g_player.fingerprint;
        g_player = DerivePlayer();
        g_playerInputs = inputs;
        if (!changed || before != g_player.fingerprint) LogPerson("player", 0, g_player, changed);
    }
    return g_player;
}

const IdentityRecord& IdentityForPed(uintptr_t cacheKey, int pedId, int palette, unsigned spriteFrame) {
    PedEntry& e = g_peds[cacheKey];
    const unsigned body = spriteFrame / 158u;
    if (e.seen == 0 || e.pedId != pedId || e.palette != palette || e.body != body) {
        const bool changed = e.seen != 0 && e.pedId == pedId;
        int remap = PedRemapForPalette(palette);
        // The seed: the game's ped id. Without it, the sprite's type alone (no address, ever).
        const uint32_t seed = pedId >= 0 ? static_cast<uint32_t>(pedId) : Mix(static_cast<uint32_t>(remap + 1) * 977u + body);
        remap = PedRemapEffective(remap, seed);
        // No remap palette: the peds the game draws from their own sprite sets rather than a
        // remap of the common body (DMA: EMERG_GRAPHIC = SWAT, FBI; GANG_GRAPHIC = Zaibatsu).
        if (remap < 0) {
            static bool logged[8] = {};
            if (body < 8 && !logged[body]) {
                logged[body] = true;
                Log("models: pedestrian without a remap palette on body %u (frame %u, palette %d) -> %s", body, spriteFrame, palette,
                    body >= 2 ? "police type (SWAT/FBI)" : body == 1 ? "zaibatsu type" : "plain list");
            }
            if (body >= 2) remap = PedRemapHasType(53) ? 53 : 0;
            else if (body == 1) remap = 8;
        }
        const uint32_t before = e.rec.fingerprint;
        e.rec = DerivePed(seed, remap, static_cast<int>(body));
        e.pedId = pedId; e.palette = palette; e.body = body;
        if ((g_pedLogged < 200 && !changed) || (changed && before != e.rec.fingerprint && g_pedLogged < 400)) {
            ++g_pedLogged;
            LogPerson("ped", cacheKey, e.rec, changed);
        }
    }
    e.seen = g_frame | 1u;
    return e.rec;
}

// CARI's wreck byte of every whole car model (wil/ste/bil carry the same table), as model 72 + class.
int IdentityWreckClassOf(int m) {
    static const signed char kClass[87] = {
        // 0..9
        2, 3, 3, 8, 8, 2, 0, 7, 2, -1,
        // 10..19
        3, 0, 2, 3, 2, -1, 6, 7, 2, 3,
        // 20..29
        -1, 7, 2, 8, 8, 8, 8, 8, 4, 6,
        // 30..39
        3, 5, 4, 4, 4, 2, 6, 3, 2, 3,
        // 40..49
        2, 3, 2, -1, 2, 3, 2, 3, 3, 2,
        // 50..59
        2, 3, 8, 3, 9, 0, 2, 3, 8, 0,
        // 60..69
        0, 0, 3, 1, 1, 0, 0, 8, 8, 6,
        // 70..79
        2, 3, -1, -1, -1, -1, -1, -1, -1, -1,
        // 80..86
        -1, -1, 3, 2, 2, 8, 0};
    if (m < 0 || m > 86 || kClass[m] < 0) return -1;
    return 72 + kClass[m];
}

int IdentityWreckStandIn(int w) {
    // A good model of each class's size (docs/vehicle-art-review.md grades): 72 the 128-long
    // bus/train class -> 011 Bus, 73 truck cabs -> 063, 74 sedans -> 000 Romero, 75 saloons -> 013
    // Minx, 76 limousines -> 032, 77 roadster -> 031 Jefferson, 78 micro cars -> 036 Schmidt,
    // 79 trucks -> 007 Box Truck, 80 vans -> 067 TV Van, 81 tank -> 054.
    static const int kStandIn[10] = {11, 63, 0, 13, 32, 31, 36, 7, 67, 54};
    return w >= 72 && w <= 81 ? kStandIn[w - 72] : -1;
}

int IdentityVehicleModelNumber(int gameModel, int sprite) {
    return (sprite >= 65 && sprite <= 74) ? 72 + (sprite - 65) : gameModel;
}

const IdentityRecord& IdentityForVehicle(uintptr_t cacheKey, const SpriteRef& ref, bool driven) {
    CarEntry& e = g_cars[cacheKey];
    const bool wreck = ref.carModel >= 72 && ref.carModel <= 81;
    // The whole car this vehicle was: its own model while it is one (the wreck class must match,
    // so a sprite object the game reuses for another car is not taken for it), else the stand-in.
    // A devtools-forced wreck (the review cards' MODELS=72-81) shows each class's stand-in.
    if (!wreck && ref.wholeModel >= 0 && !ref.forcedModel) e.whole = ref.wholeModel;
    if (wreck && ref.wholeModel >= 0 && !ref.forcedModel && IdentityWreckClassOf(ref.wholeModel) == ref.carModel) e.whole = ref.wholeModel;
    const int whole = !wreck ? -1
                      : (!ref.forcedModel && e.whole >= 0 && IdentityWreckClassOf(e.whole) == ref.carModel) ? e.whole
                      : IdentityWreckStandIn(ref.carModel);
    const SpriteRef& o = e.rec.ref;
    const bool sameCar = e.seen != 0 && o.carModel == ref.carModel && o.carSprite == ref.carSprite && o.forcedModel == ref.forcedModel &&
                         e.rec.wreck == wreck && (!wreck || e.rec.wreckOf == whole || e.rec.wreckOf < 0);
    bool derive = !sameCar;
    if (sameCar) {
        if (PaintDiff(o.paint, ref.paint) <= kPaintHoldTol) {
            e.candOn = false;   // the paint it has (a re-measure within the tolerance changes nothing)
        } else if (!e.candOn || PaintDiff(e.cand, ref.paint) > kPaintHoldTol) {
            e.candOn = true; e.candSince = g_frame;
            for (int k = 0; k < 3; ++k) e.cand[k] = ref.paint[k];
        } else if (g_frame - e.candSince >= kPaintHoldFrames) {
            derive = true;   // held long enough: a respray, not a flash
        }
    }
    if (derive) {
        const bool changed = e.seen != 0;
        const int oldModel = o.carModel;
        e.rec = wreck && whole >= 0 ? DeriveWreck(ref, whole) : DeriveVehicle(ref);
        e.candOn = false;
        int& n = g_carLogged[e.rec.fingerprint];
        if ((n++ == 0 && g_carLogged.size() < 400) || (driven && changed)) {
            const IdentityRecord& r = e.rec;
            char what[48] = "";
            if (changed) snprintf(what, sizeof what, oldModel != ref.carModel ? " CHANGED model %d->%d" : " CHANGED paint", oldModel, ref.carModel);
            Log("identity: vehicle%s obj %08x%s model %d sprite %d paint %.0f,%.0f,%.0f -> %s%s%s tint %.2f,%.2f,%.2f shown %.0f,%.0f,%.0f fp %08x",
                what, static_cast<unsigned>(cacheKey), driven ? " (the player's)" : "", ref.carModel, ref.carSprite, ref.paint[0], ref.paint[1],
                ref.paint[2], r.model ? r.model->name.c_str() : "(built from sprite)", r.livery ? " livery" : "",
                !r.wreck ? "" : r.wreckOf == e.whole ? " (wreck of this car's own model)" : " (wreck: the class's stand-in)", r.paintTint[0], r.paintTint[1],
                r.paintTint[2], r.shownTop[0], r.shownTop[1], r.shownTop[2], r.fingerprint);
        }
    }
    e.seen = g_frame | 1u;
    return e.rec;
}

void IdentityBeginFrame(uint32_t frame) {
    g_frame = frame;
    if (frame % 300u != 0) return;
    for (auto it = g_peds.begin(); it != g_peds.end();) it = frame - it->second.seen > 900u ? g_peds.erase(it) : std::next(it);
    for (auto it = g_cars.begin(); it != g_cars.end();) it = frame - it->second.seen > 900u ? g_cars.erase(it) : std::next(it);
}

bool IdentityProbeOn() {
    if (g_probe < 0) {
        char v[16] = {};
        g_probe = GetEnvironmentVariableA("GTA2DX9_IDENTITY_PROBE", v, sizeof v) && v[0] == '1' ? 1 : 0;
        if (GetEnvironmentVariableA("GTA2DX9_IDENTITY_PROBE_EVERY", v, sizeof v)) g_probeEvery = (std::max)(1, atoi(v));
        if (g_probe) Log("identity: probe on, every %d frames", g_probeEvery);
    }
    return g_probe == 1;
}

// One line per (what, object, view) per probe interval (GTA2DX9_IDENTITY_PROBE_EVERY frames at
// 30 fps, by the wall clock: the classic view runs no frame hook of the 3D path).
bool ProbeDue(const char* what, const void* object, int view) {
    static std::unordered_map<uint64_t, DWORD> last;
    const DWORD now = GetTickCount(), every = static_cast<DWORD>(g_probeEvery) * 33u;
    const uint64_t key = (static_cast<uint64_t>(reinterpret_cast<uintptr_t>(object)) << 8) ^ (static_cast<uint64_t>(what[0]) << 2) ^
                         (static_cast<uint64_t>(strlen(what)) << 4) ^ static_cast<uint64_t>(view);
    auto it = last.find(key);
    if (it != last.end() && now - it->second < every) return false;
    if (last.size() > 4096) last.clear();
    last[key] = now;
    return true;
}

void IdentityProbeRect(const char* what, const void* object, const IdentityRecord& r, int view, float x0, float y0, float x1, float y1) {
    if (!IdentityProbeOn() || !ProbeDue(what, object, view)) return;
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    const unsigned long long ms = ((static_cast<unsigned long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime) - 116444736000000000ULL) / 10000ULL;
    Log("identity probe: %s view %d frame %u t %u.%03u obj %08x rect %.0f %.0f %.0f %.0f fp %08x model %s shown %.0f,%.0f,%.0f %.0f,%.0f,%.0f", what, view, g_frame,
        static_cast<unsigned>(ms / 1000ULL), static_cast<unsigned>(ms % 1000ULL), static_cast<unsigned>(reinterpret_cast<uintptr_t>(object)), x0, y0, x1, y1, r.fingerprint, r.model ? r.model->name.c_str() : "-", r.shownTop[0], r.shownTop[1], r.shownTop[2], r.shownBottom[0],
        r.shownBottom[1], r.shownBottom[2]);
}

namespace {
const void* g_probePlayer = nullptr;
const void* g_probeCar = nullptr;
IdentityRecord g_probeCarRec;
bool g_probeCarRecValid = false;
}  // namespace

void IdentityProbeSetSubjects(const void* playerObject, const void* playerCarObject, const IdentityRecord* playerCar) {
    g_probePlayer = playerObject;
    g_probeCar = playerCarObject;
    if (playerCar) { g_probeCarRec = *playerCar; g_probeCarRecValid = true; }
    else if (!playerCarObject) g_probeCarRecValid = false;
}

void IdentityProbeModel(IDirect3DDevice9* device, const char* what, const void* object, const IdentityRecord& rec, const Model& model,
                        const float world[4][4], int view) {
    if (!IdentityProbeOn()) return;
    if (strcmp(what, "mycar") == 0) { g_probeCarRec = rec; g_probeCarRecValid = true; }   // the classic sprite's line names it too
    if (!device) return;
    D3DMATRIX v, p;
    D3DVIEWPORT9 vp;
    if (FAILED(device->GetTransform(D3DTS_VIEW, &v)) || FAILED(device->GetTransform(D3DTS_PROJECTION, &p)) || FAILED(device->GetViewport(&vp))) return;
    float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
    int in = 0;
    for (int c = 0; c < 8; ++c) {
        const float l[4] = {(c & 1) ? model.boundsMax.x : model.boundsMin.x, (c & 2) ? model.boundsMax.y : model.boundsMin.y,
                            (c & 4) ? model.boundsMax.z : model.boundsMin.z, 1.0f};
        float w4[4], e4[4], c4[4];
        for (int j = 0; j < 4; ++j) w4[j] = l[0] * world[0][j] + l[1] * world[1][j] + l[2] * world[2][j] + l[3] * world[3][j];
        for (int j = 0; j < 4; ++j) e4[j] = w4[0] * v.m[0][j] + w4[1] * v.m[1][j] + w4[2] * v.m[2][j] + w4[3] * v.m[3][j];
        for (int j = 0; j < 4; ++j) c4[j] = e4[0] * p.m[0][j] + e4[1] * p.m[1][j] + e4[2] * p.m[2][j] + e4[3] * p.m[3][j];
        if (c4[3] <= 1e-4f) continue;   // behind the eye
        ++in;
        const float sx = vp.X + (c4[0] / c4[3] * 0.5f + 0.5f) * vp.Width, sy = vp.Y + (0.5f - c4[1] / c4[3] * 0.5f) * vp.Height;
        x0 = (std::min)(x0, sx); y0 = (std::min)(y0, sy); x1 = (std::max)(x1, sx); y1 = (std::max)(y1, sy);
    }
    if (in < 8) return;   // partly behind the eye: no honest rectangle
    IdentityProbeRect(what, object, rec, view, x0, y0, x1, y1);
}

void IdentityProbePoints(IDirect3DDevice9* device, const char* what, const void* object, const IdentityRecord& rec, const float* xyz, int n, int view) {
    // FIX-CAR-IDENTITY-2: world points (no world transform) to a screen rectangle, clipped to the viewport (the
    // first-person bonnet runs off the frame's bottom edge); at least three points in front of the eye.
    if (!IdentityProbeOn() || !device || !xyz || n < 3) return;
    D3DMATRIX v, p;
    D3DVIEWPORT9 vp;
    if (FAILED(device->GetTransform(D3DTS_VIEW, &v)) || FAILED(device->GetTransform(D3DTS_PROJECTION, &p)) || FAILED(device->GetViewport(&vp))) return;
    float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
    int in = 0;
    for (int i = 0; i < n; ++i) {
        const float w4[4] = {xyz[i * 3], xyz[i * 3 + 1], xyz[i * 3 + 2], 1.0f};
        float e4[4], c4[4];
        for (int j = 0; j < 4; ++j) e4[j] = w4[0] * v.m[0][j] + w4[1] * v.m[1][j] + w4[2] * v.m[2][j] + w4[3] * v.m[3][j];
        for (int j = 0; j < 4; ++j) c4[j] = e4[0] * p.m[0][j] + e4[1] * p.m[1][j] + e4[2] * p.m[2][j] + e4[3] * p.m[3][j];
        if (c4[3] <= 1e-4f) continue;
        ++in;
        const float sx = vp.X + (c4[0] / c4[3] * 0.5f + 0.5f) * vp.Width, sy = vp.Y + (0.5f - c4[1] / c4[3] * 0.5f) * vp.Height;
        x0 = (std::min)(x0, sx); y0 = (std::min)(y0, sy); x1 = (std::max)(x1, sx); y1 = (std::max)(y1, sy);
    }
    if (in < 3) return;
    x0 = (std::max)(x0, static_cast<float>(vp.X)); y0 = (std::max)(y0, static_cast<float>(vp.Y));
    x1 = (std::min)(x1, static_cast<float>(vp.X + vp.Width)); y1 = (std::min)(y1, static_cast<float>(vp.Y + vp.Height));
    if (x1 - x0 < 4.0f || y1 - y0 < 4.0f) return;
    IdentityProbeRect(what, object, rec, view, x0, y0, x1, y1);
}

const IdentityRecord* IdentityLookupVehicle(uintptr_t cacheKey) {
    const auto it = g_cars.find(cacheKey);
    return it == g_cars.end() ? nullptr : &it->second.rec;
}

void IdentityProbeSprite(const void* object, bool isCar, const float* vertices, int corners) {
    if (!object || !vertices || corners < 3 || !IdentityProbeOn()) return;
    const bool player = object == g_probePlayer, mine = object == g_probeCar;
    if (!player && !mine && !isCar) return;
    float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
    for (int i = 0; i < corners; ++i) {
        const float* v = vertices + i * 8;   // 0x20 bytes a vertex
        x0 = (std::min)(x0, v[0]); y0 = (std::min)(y0, v[1]); x1 = (std::max)(x1, v[0]); y1 = (std::max)(y1, v[1]);
    }
    static const IdentityRecord kNone;
    if (player) { IdentityProbeRect("player", object, IdentityForPlayer(), 0, x0, y0, x1, y1); return; }
    const IdentityRecord* rec = IdentityLookupVehicle(reinterpret_cast<uintptr_t>(object));
    if (mine && !rec && g_probeCarRecValid) rec = &g_probeCarRec;
    IdentityProbeRect(mine ? "mycar" : "car", object, rec ? *rec : kNone, 0, x0, y0, x1, y1);
}

}  // namespace gta2dx9
