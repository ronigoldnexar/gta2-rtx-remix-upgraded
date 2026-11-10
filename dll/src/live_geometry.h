// World-space geometry recovered from the game's own draw calls.
//
// GTA2 hands the renderer screen-space vertices, but it does not throw the
// world-space ones away: every vertex it projects also has its **absolute**
// world position written four slots further along the same array, by
// FUN_0046bbf0 for map faces and FUN_004b9990 for sprites. FUN_0046bbf0 adds
// the camera position back in before storing, so these are absolute map
// coordinates, not camera-relative ones.
//
// That makes it possible to place sprites and the odd block shapes as real 3D
// geometry without ever inverting a projection: the numbers here are the input
// to the game's transform, not the output.
//
// Used for sprites - cars, pedestrians, powerups - which are rebuilt each frame
// so they can move. Map geometry is deliberately *not* sourced this way: the
// game only draws what is currently visible, so anything built from its stream
// would pop into existence as the camera reached it.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdint>
#include <d3d9.h>
#include <map>
#include <vector>

#include "../../src/camera.h"
#include "../../src/math3d.h"
#include "car_bodies.h"
#include "ground.h"

namespace gta2dx9 {

// How far a sprite is lifted off the floor when there is no floor to measure -
// off the edge of the map, over a hole, or with conforming switched off. See
// the long note in live_geometry.cpp for why any lift is needed at all and how
// this number was arrived at. It doubles as the ceiling on the extra clearance
// a footprint straddling a kerb is given, so one knob still bounds how far a
// sprite can ever be pushed off the ground. Sprites are rebuilt from the game's
// stream every frame, so a change takes effect on the next one.
constexpr float kDefaultSpriteLift = 0.075f;

void SetSpriteLift(float blocks);

// Stand each sprite on the ground plane under it rather than at a fixed height
// above its own level: the lid is sampled under the four corners, a plane is
// fitted to it, and that plane becomes the sprite's transform. On when the map
// can be read; off restores the fixed lift exactly.
void SetSpriteConform(bool on);
bool SpriteConform();

// Small flat sprites that are not cars or pedestrians - the mission arrows, pick-ups,
// signs - are drawn from textures a few dozen texels across, so under a path tracer
// they show as chunky blocks with stair-stepped edges. With this on they are drawn
// from a 4x smoothed copy of the artwork (edge-aware upscale, then bilinear), which
// keeps the shape and the hard cutout but rounds off the staircase. Cars and
// pedestrians are untouched: their stepping is part of how they look, and cars have
// HD art of their own.
constexpr bool kDefaultSpriteSmooth = true;
void SetSpriteSmooth(bool on);

// Switches for finding what a stray artefact is, from the F4 menu. Each one takes a single part of
// the picture out (or puts one back) while the game runs; none is saved.
enum GhostSwitch {
    kGhostHidePeds = 0,    // draw no pedestrians at all
    kGhostHideDoors,       // draw no car door or dent pieces
    kGhostNoBoardUi,       // a boarding pedestrian is drawn in the world, not the screen layer
    kGhostNoLift,          // pedestrians are not lifted over cars
    kGhostNoRoofSprites,   // small sprites on a car's roof (the gang logos) are not lifted clear of the dome
    kGhostSwitchCount
};
void SetGhostSwitch(int which, bool on);

// The chase and first-person views (see view_modes.h).
//
// Up to two game objects whose sprites are not drawn at all this frame: the
// player's own pedestrian and his car, from his own eyes. Null clears one.
void SetHiddenObjects(const void* first, const void* second);
// REMIX-3D-QUALITY: while on, the first of the hidden objects (the player, from his
// own eyes) is not dropped but drawn as his figure with textures Remix keeps out of
// primary rays (rtx.playerModelTextures): no body in the picture, a shadow on the
// street as his sprite casts in the classic view. Only meaningful under Remix with
// the figures and models on; world_view decides.
void SetOwnFigureShadowOnly(bool on);
bool OwnFigureShadowOnly();
// [remix] own_shadow_first_person (default on): whether world_view may turn it on.
void SetOwnFigureShadowAllowed(bool allowed);
bool OwnFigureShadowAllowed();
// The player's own pedestrian sprite object (null when not located), so he
// keeps one look rather than one hashed from his address.
void SetPlayerObject(const void* object);
// FIX-FP (pm7-fp-own-head-and-shoulder): the player's ped structure as the locator found it. A
// pedestrian sprite whose owner chain leads to this ped is his, whichever sprite object the game
// draws him with (after a BUSTED release the located sprite was not the one drawn, and from his
// own eyes his body was drawn as a stranger's across a third of the view).
void SetPlayerPed(const void* ped);
// The weapon the player holds, as the game numbers them (see PedWeapon in
// live_geometry.cpp: 1 pistol .. 10 flamethrower), -1 when not known. Read
// off the player's ped by world_view each frame; drives the figure's stance,
// the model in its hand and the first-person view model.
void SetPlayerWeapon(int weapon, int ammo);
int PlayerWeapon();
const char* WeaponName(int weapon);
// Submits the muzzle-flash lights of the last frame's shots to the invented
// light list; call after SyntheticLightsUpdate and before LightsReconcile.
void ShotLightsSubmit();
// Flame sprites the last frame showed (world x, y, z and the car shell they sit on),
// so the player log line can say whether his car is burning.
struct FireSpotPublic { float x, y, z; const void* car; bool onCar = false; };   // onCar: a burning car's flame (FIX-FIGURE-9)
extern std::vector<FireSpotPublic> g_fireSpotsLast;
int FireSpotsNear(float x, float z, float radius, const void* carShell);
// Where the player stands this frame (renderer coordinates), for keeping the
// rule-placed street furniture out from under his feet; valid=false clears it.
void SetPlayerPosition(float x, float y, float z, bool valid);
// FIX-FX-2 (fire-fx 3d): the player's own car is on fire (the game's car-fire stage) and the
// view is first person: flames are emitted at the bonnet edge, which the cab shows (renderer
// coordinates; dirX/dirZ the car's heading). on=false clears it.
void SetOwnCarFire(bool on, float x, float y, float z, float dirX, float dirZ, int stage);
// Whether he is in a vehicle (the Remix night fill goes over the roof, not inside the cab).
void SetPlayerInVehicle(bool in);
// A street prop's footprint on the ground, for the camera's clearance queries.
struct PropFootprint { float x, y, z, radius, height; };
// Per style tile: 1 when the tile is grass, for the park trees of the street
// views (set at level load from the style's artwork).
void SetGrassTiles(const std::vector<uint8_t>& grass);
// The map's own elevated rail cells (x, map y, lid level, 1 = runs along x) and
// its bus-stop zone cells (x, map y), found at level load for the street views'
// track girders and shelters. See world_view.cpp.
struct EnvCell { int x, y, level, alongX; };
void SetEnvCells(const std::vector<EnvCell>& rail, const std::vector<EnvCell>& busStops);
// True when a point lies more than `margin` behind the camera's plane this
// frame (set at the top of LiveGeometry::Draw): what the ground views need not
// draw at all.
bool BehindView(float x, float y, float z, float margin);
// FIX-PROPS-3: the street props' and map objects' lighting (the world's sun and ambient,
// world_view.cpp DrawSkyAndShading; plain renderer only, not under Remix nor with
// GTA2DX9_PROP_LIGHT=0). Begin returns false and changes nothing when the props are
// drawn unlit; End undoes what Begin set. With `glass`, a sun highlight too (the
// translucent passes: shelter and booth panes).
bool PropLightingBegin(IDirect3DDevice9* device, bool glass = false);
void PropLightingEnd(IDirect3DDevice9* device);
// True when a sphere (world units, the renderer's frame) lies wholly outside the
// current view frustum's four side planes (PERF-2: props, map objects and people
// outside the picture are not drawn; they were drawn whenever they were in front).
bool OutsideViewFrustum(float x, float y, float z, float radius);
// QB-6 (aim reticle and hit markers, hud3d.cpp): the people the street views drew this
// frame (renderer coordinates, the sprite's origin; the game's health word, -1 unread),
// and the projection of a world point with the camera of the last Draw, as a fraction of
// the window (0..1 across and down); false behind the eye or before the first frame.
struct AimPed { uintptr_t object; float x, y, z; int health; bool corpse; };
const std::vector<AimPed>& LiveAimPeds();
uint32_t LiveAimPedsFrame();   // the draw frame the list belongs to (bumped by every Draw)
uint32_t LiveDrawFrame();
bool LiveWorldToScreen(float x, float y, float z, float* sx, float* sy);
// FIX-CAMERA-2 (feel7-third-chase-camera-inside-car-or-wreck-body): every car and wreck the
// street views drew last frame, as its footprint on the road (four corners, renderer x/z,
// in order round the quad) and its height span, for the chase camera's obstacle test.
// `object` is the car's sprite object (PlayerState::vehicleSprite for the one he drives).
struct CameraCar { float x[4], z[4], y0, y1; uintptr_t object; };
const std::vector<CameraCar>& LiveCameraCars();
bool NearestFigureSpot(float x, float y, float z, float skipX, float skipZ, float* sx, float* sy, float* sz, float* distance);
// Pedestrians on their feet are stood up as billboards facing the camera, for
// a camera that is not above them. Off draws them flat on the road as always.
// FIX-PERF-VSWITCH: the next classic frame's sprites also issued unseen under the street fog (once).
void LiveGeometryGhostSprites();
void SetUprightPeds(bool on);
// Lamps on the 3D car bodies: 0 none, 1 when dark (plus brake lamps), 2 always.
void SetCarLamps(int mode);
// FIX-FX-5: [devtools] remix_flat_lamps=1 lays the game's lamp-delta quads flat under a 3D car model under Remix again (the old white squares on the road); 0 (default) leaves them out in the street views.
void SetRemixFlatLamps(int on);
// FIX-FX-5: [devtools] remix_game_specks=1 draws the game's tiny (< 0.06 block) smoke puffs in the street views under Remix again (the dotted bead columns); 0 (default) leaves them out.
void SetRemixGameSpecks(int on);
// Street views, plain renderer: the soft contact shadow under cars, peds and props, percent opacity (0 off).
void SetContactShadows(int percent);
// Each drawn tyre's own dark contact patch under it, over the car's soft one (1 on, 0 off).
void SetTyreShadows(int on);
bool UprightPeds();
// ... and, instead of a billboard, a small three-dimensional figure that walks:
// head, body, arms and legs, the limbs swinging with the pedestrian's speed.
// GTA2 has no side-on artwork for people, so from the ground this is the
// closest thing to a person the game's own data allows.
void SetPedFigures(bool on);
bool PedFigures();
// ... and imported models in place of both. See model_store.h.
void SetGroundModels(bool on);
bool GroundModels();

// How high above the ground a pedestrian is held while he climbs into or out of a car, as a
// fraction of the car's roof height. The car's body hides whatever of him is higher than its
// own surface there, so low he goes under the car's edge and is gone; around the height of the
// door sill he is seen stepping in over the door and goes under the roof only once inside.
void SetBoardingHeight(float fraction);
float BoardingHeight();
bool GhostSwitchOn(int which);
bool SpriteSmooth();
// The smoothed 4x copy of a small flat texture (see above), for the overlay's world-anchored
// HUD arrows and markers; the texture itself when smoothing is off or it is not small artwork.
IDirect3DTexture9* SmoothedSmallTexture(IDirect3DDevice9* device, IDirect3DTexture9* source);

// How far a sprite is held off the ground once it is conformed to it. A quarter
// of a ground texel: enough to break the coplanarity that has no defined answer
// in a path tracer, and nothing more. The fixed lift had to be twenty times this
// only because a horizontal quad on a ramp needed the headroom.
//
// This is a depth-buffer number, not a visual one. How high the sprite *looks*
// is kDefaultSpriteHeight below, which is a completely different question.
constexpr float kConformClearance = 1.0f / 256.0f;

// How high the object a sprite stands in for sits above the road.
//
// Separate from the clearance above: clearance answers "which surface does the
// ray hit", this answers "is there a car here, or a picture of one painted on
// the road".
//
// This was 0.3 - the mid-height of a car body at GTA2's 2 m block - on the
// reasoning that a flat quad lying on the ground casts its shadow exactly where
// it already is and so shows nothing. That reasoning is right about shadows and
// wrong about the result: at a near-top-down camera the visible effect of ride
// height is not the shadow, it is the parallax, and 60 cm of it reads as the
// sprite hovering rather than as the sprite having depth. Judged by eye at both,
// a tenth of that sits on the road.
//
// So the height is small, and the *clipping* is handled where it belongs - by
// the conform, and by clearance that is computed per sprite rather than budgeted
// for in advance.
constexpr float kDefaultSpriteHeight = 0.03f;

void SetSpriteHeight(float blocks);
float SpriteHeight();

// The most extra clearance a sprite can be given on top of its ride height, for
// ground the fitted plane could not describe. Geometry bounds the real figure
// well below this - the worst case is a footprint across a whole block step -
// so anything reaching the cap is a bad sample rather than a steep street, and
// the cap is what stops it launching a car into the air.
constexpr float kMaxExtraClearance = 1.0f;

// How much of a sideways tilt a sprite keeps, 0..1.
//
// Fitting a plane to the ground and using the whole of it is right for a rigid
// body and wrong for a car. A car crossing a ramp at an angle stands on a plane
// tilted along both of its own axes, so the body rolls as well as pitches and a
// corner lifts - which is not something a car on wheels does. Pitching along the
// direction of travel is the part that looks right, and that part is kept whole.
//
// The sprite's long axis is taken as its direction of travel, which for a car
// quad is the side measuring about two blocks against the other's one. Rotation
// about that axis is the roll, and this scales it. 0 keeps sprites level side to
// side, 1 is the full fitted plane again.
constexpr float kDefaultSpriteRoll = 0.25f;

void SetSpriteRoll(float amount);
float SpriteRoll();

// The steepest ground a sprite is rotated onto. GTA2's 26 degree ramps come in
// under it; its 45 degree blocks, 0.14% of the surfaces a sprite can stand on,
// are clamped here because standing top-down artwork on its edge looks far worse
// than the clipping it would fix. What the clamp leaves behind is picked up as
// clearance.
constexpr float kMaxTiltDegrees = 30.0f;

// How much to soften a sprite's cutout edge, 0..1. GTA2's alpha is 1-bit, so
// this is invented rather than recovered - see FeatherAlpha in alpha_bleed.h.
// Sprites only: the world mesh keeps its hard edges, which is what a fence or a
// wall wants.
void SetSpriteFeather(float strength);
float SpriteFeather();

// How far apart to hold sprites that are stacked on the same spot.
//
// A GTA2 car is not one sprite: the body is drawn, then its lights, then any
// logo, each a separate quad at exactly the same height. The game got away with
// that because it never depth tested - it just painted them in order - but as
// real geometry they are coplanar and the depth test picks a winner per pixel,
// which is the flicker and the dropouts. Each sprite landing on a spot another
// has already taken this frame is lifted one step higher than the last, in the
// order the game drew them, so the painter's order becomes a real stacking
// order. 0 disables it.
void SetSpriteStackStep(float blocks);
float SpriteStackStep();
float SpriteLift();

// Car lamps drawn by us rather than by GTA2.
//
// With lighting on the game draws a car's lit lamps as a second quad the size of
// the whole car, with a texture built for whichever lamps are on - a new texture
// for every car and every combination of lamps, and a quad that could drift off
// the body. Instead that quad is left out and each lit lamp gets a small quad of
// its own, laid on the body exactly over the lamp, textured with that lamp's own
// pixels cut out of the car's artwork. So it looks as the game's does, and each
// lamp of each car model is one small texture that never changes, which an
// emissive can be put on once.
constexpr bool kDefaultOwnCarLamps = true;
// How brightly a lit car lamp glows, as the emissive intensity of the Remix material
// each lamp is drawn with (0 draws it as a plain quad, as before). The lamp's own
// colours at full brightness, so a headlight is a point of light rather than a tan
// smudge on the paint.
constexpr float kDefaultCarLampGlow = 6.0f;
// How big the glowing quad of a lamp is, as a fraction of the lamp's own pixels (it shrinks
// toward the lamp's centre; the lamp's whole picture is still shown, only smaller).
constexpr float kDefaultCarLampSize = 0.60f;
void SetCarLampSize(float fraction);
void SetCarLampGlow(float intensity);
// Blood on the ground (pools, drops, trails) drawn with a material of its own: wet, dark and
// glossy. roughness 0..1 (0 mirror), albedo is a multiplier on the game's red.
void SetBloodLook(bool gloss, float roughness, float albedo);
float CarLampGlow();
void SetOwnCarLamps(bool on);
bool OwnCarLamps();

// Tyres at the four corners of every car, the front pair turned with the steering. The
// sprites are drawn from above and have no wheels to show, so each car gets four small
// dark tyres that sit under its dome and peek out at the rim - and swing outward past the
// body as the front wheels turn. GTA2 does not keep a steering angle the renderer can read,
// so it is worked out from how the car moves: the angle that would give the turn the car
// just made over the distance it just went (a bicycle model). `maxAngle` caps it, in
// degrees. Off draws no tyres.
constexpr bool kDefaultCarWheels = false;
constexpr float kDefaultCarWheelMaxAngle = 32.0f;
// How far out the tyres sit, as a fraction of the body's width from its middle line (0.5 is
// the very edge), and how far in from the nose and tail the axles are, as a fraction of
// the body's length.
constexpr float kDefaultCarWheelSide = 0.41f;
constexpr float kDefaultCarWheelAxleInset = 0.24f;
// The front tyres sit this much further out than the rear ones (same units as the side),
// so they show past the bodywork when they turn.
constexpr float kDefaultCarWheelFrontExtra = 0.09f;
void SetCarWheels(bool on, float maxAngleDegrees, float side = kDefaultCarWheelSide,
                  float axleInset = kDefaultCarWheelAxleInset,
                  float frontExtra = kDefaultCarWheelFrontExtra);
bool CarWheels();

// Cars as bodies rather than flat pictures.
//
// GTA2's cars are one flat sprite each, seen from straight above. Under a path
// tracer a flat quad has nothing to reflect with - a horizontal mirror seen from
// directly overhead reflects only the sky - so however glossy the material, a
// car looks painted on the road. With this on, each car's sprite is lifted to the
// height of its roof and pulled in a little at the edges, and a sloping skirt in
// the car's own paint colour runs from the sprite's edge down to the road. The
// skirt faces sideways and upwards at an angle, which is what gives a glossy
// surface something to reflect: lamps, walls, other cars.
//
// The height and inset are fractions of a block: a car is about one block long.
constexpr bool kDefaultCarBodies = true;
constexpr float kDefaultCarBodyHeight = 0.10f;
constexpr float kDefaultCarBodyInset = 0.12f;
void SetCarBodies(bool on);
// Cars in the ground views as 3D bodies (hand-made models or bodies built from
// their sprites; car_bodies.h) instead of their sprite domes. [renderer] car_models3d.
void SetCarModels3d(bool on);
bool CarBodies();
void SetCarBodyHeight(float blocks);
float CarBodyHeight();
// How square the dome's shoulders are: the exponent its height rises with from the car's outline,
// 0.7 the original rounded hump, lower is boxier (steeper sides, flatter top) so the shadow of the
// car lies against it like a solid object's instead of a dome's.
void SetCarDomeShoulder(float exponent);
float CarDomeShoulder();
void SetCarBodyInset(float fraction);
float CarBodyInset();
// The car's own Remix material: submitted through the Remix API, so it can be
// glossy metal while the rest of the world keeps its rough default. Roughness
// and metallic are 0..1. Without the API, the dome is drawn as plain geometry.
constexpr bool kDefaultCarMaterial = true;
constexpr float kDefaultCarRoughness = 0.25f;
constexpr float kDefaultCarMetallic = 0.40f;
void SetCarMaterial(bool on, float roughness, float metallic);
// Use the hand-made car artwork and maps from gta2dx9_hd\ where there are some.
void SetCarHd(bool hd, bool normalMaps);
// How much of the maps' surface tilt the cars keep, 0..1. 1 is the map as built.
void SetCarNormalStrength(float strength);
// How much of a mirror the cars' glass is made: 0 leaves it as the maps are, 1 is
// the default, above 1 brightens the glass's own colour further.
void SetCarGlassGloss(float gloss);
// How glossy the cars' paint is made on top of what the maps say: 0 leaves the maps
// as they are, 1 (the default) makes paint smoother and a little more metal, so that
// lamps and other cars show in it as crisp reflections rather than a dull smear.
void SetCarPaintGloss(float gloss);
void SetCarPaintGlossFor(int sprite, float gloss);   // 0..1; negative: the global setting
// How far the glass is bulged outwards, 0..1.5: 0 leaves it the flat panel the maps
// make, which reflects the same bit of sky everywhere; 0.6 is the default.
void SetCarGlassCurve(float curve);

// Skid marks and the smoke off the tyres. The game's skid strips are redrawn from a
// soft, translucent copy; every new strip near a car lets off a puff of smoke.
struct SkidSmokeSettings {
    bool  soft = true;            // redraw rubber skid strips soft (off: as GTA2 draws them)
    float skidOpacity = 0.45f;    // peak opacity of the rubber
    float skidSoftness = 1.0f;    // how far the edges and the stipple are blurred
    // The game forgets a skid strip long before it should. With this on the renderer
    // remembers every strip it has drawn, keeps drawing it at full strength for
    // skidHold seconds, and then fades it out gently over skidFade seconds.
    bool  persist = true;
    float skidHold = 60.0f;       // seconds at full strength
    float skidFade = 60.0f;       // seconds to fade away after that
    bool  smoke = false;          // off unless the menu or gta2dx9.ini turns it on
    float smokeAmount = 1.0f;     // puffs per new strip
    bool  smokeGlow = true;       // self-lit white smoke (additive); off: lit like any surface, greyer
    float smokeOpacity = 0.22f;   // a puff's peak opacity
    float smokeSize = 1.0f;
    float smokeLife = 1.5f;       // seconds
    float smokeRise = 1.0f;
    float smokeDrift = 1.0f;
};
SkidSmokeSettings& SkidSmoke();
// Reads the [skids] section of the renderer's ini, and remembers the path for Save.
void SkidSmokeLoad(const char* iniPath);
// Writes it back to the ini it was read from. False if there is none.
bool SkidSmokeSave();

// Burning cars. The game's flame sprite sits at the car's own level, which is under the
// dome that now stands up from the car, so the car is drawn over its own fire. Flames
// over a car are lifted clear of its roof, drawn larger, backed by stacked orange layers
// that flicker, and let off dark smoke. Explosions (sprites bigger than maxSize) are only
// lifted, not enlarged.
struct FireSettings {
    bool  onTop = true;           // lift effect sprites over a car above its roof
    float sizeScale = 1.6f;       // flame size multiplier
    float maxSize = 0.8f;         // tiles; bigger sprites are explosions and are left their size
    int   layers = 3;             // extra flame layers stacked above the sprite
    float layerRise = 0.05f;      // tiles each layer sits higher
    float layerGrow = 0.25f;      // each layer is this much larger than the last
    float layerBright = 0.70f;    // brightness left after each layer
    float tint[3] = {1.0f, 0.55f, 0.18f};   // colour of the extra layers
    float flicker = 0.20f;        // how much the size wanders
    float flickerHz = 13.0f;
    bool  smoke = true;
    float smokeRate = 7.0f;       // puffs per second, per burning car
    float smokeOpacity = 0.35f;
    float smokeSize = 1.0f;
    float smokeLife = 2.5f;       // seconds
    float smokeRise = 1.0f;
    float smokeDrift = 1.0f;
    float smokeGrey = 0.16f;      // 0 black .. 1 white, at birth
    // Flames of our own, drawn as soft additive particles rising off a burning car. The game's
    // flame sprite is one small repeating picture; this is a mass of tongues, hot yellow at
    // the root and red at the tip, that never repeats.
    bool  flames = true;
    float flameRate = 90.0f;      // tongues per second, per burning car
    float flameSize = 1.0f;
    float flameRise = 1.0f;
    float flameLife = 0.7f;       // seconds
    float flameBright = 1.0f;
    float emberRate = 12.0f;      // sparks per second, per burning car
    float spriteBright = 0.5f;    // how much of the game's own flame sprite is kept under them
    bool scorch = true;           // a burnt mark on the ground where something blew up
    float scorchLife = 60.0f;     // seconds from the blast until it has gone
    float scorchOpacity = 0.85f;  // how dark it starts
    float scorchSize = 1.0f;      // against the size of the blast
};
FireSettings& FireEffects();
// CROWD: [crowd] variety / look_at / look_range (people's own clothes and builds,
// heads that follow the player, glances); GTA2DX9_CROWD=0 turns them off.
void CrowdLoad(const char* iniPath);
// Reads and writes the [fire] section of the renderer's ini.
void FireEffectsLoad(const char* iniPath);
bool FireEffectsSave();
// How strongly dents show on a car with hand-made artwork: 0 draws none, 1 is the
// full change the game's damage art makes, the default is a little under that.
void SetCarDamage(float strength);

// One lamp delta of one car sprite, set when a district's style is loaded: its
// pixels cropped to the rectangle they cover (alpha 0 where the delta paints
// nothing), where that rectangle is on the sprite, and the sprite's size.
struct LampArt {
    int x0 = 0, y0 = 0, width = 0, height = 0;
    int spriteWidth = 0, spriteHeight = 0;
    std::vector<uint32_t> argb;
    int opaque = 0;   // how many of the pixels paint anything; set by SetCarDeltaArt
    bool Valid() const { return width > 0 && height > 0 && spriteWidth > 0 && spriteHeight > 0; }
};
void SetCarLampArt(int delta, std::vector<LampArt> bySprite);
// The same for the deltas that are not lamps - dents and doors - which a car with
// hand-made artwork needs drawn over its body, since the game paints them into its
// own low-resolution sprite and the redraw never sees them.
void SetCarDeltaArt(int delta, std::vector<LampArt> bySprite);

// The texture a lamp is drawn with, exactly as it is uploaded: the crop, mirrored
// for a lamp on the far side, with every transparent texel given the mean colour
// of the opaque ones so filtering cannot pull a dark fringe in. Its Remix hash is
// what tools/lamp_emissives.py reproduces to put an emissive on it.
std::vector<uint32_t> LampTexels(const LampArt& art, bool mirrored);

// How many sprites were drawn additively last frame - the fire and explosion
// artwork. A free function because the menu has no handle on the LiveGeometry
// instance. See EffectSpriteSettings in texture_store.h.
int EffectBatchesDrawn();

// How many distinct object-space quads the session has had to keep, and for how
// many sprite textures. This is the health check on the whole scheme below: a
// count that settles is geometry Remix can recognise frame to frame, and one
// that keeps climbing means something is dithering and the motion vectors will
// be no better than they were.
void SpriteShapeCounts(int* shapes, int* textures);

// --- Why each sprite is its own draw call ---------------------------------
//
// Because RTX Remix has to recognise a sprite as the same sprite it saw last
// frame, and it can only do that from what the draw call looks like.
//
// This pass used to hand Remix, once per texture, a bag of world-space vertices
// for every sprite sharing that texture, drawn with an identity world matrix.
// Reading dxvk-remix, that is close to the worst thing to give it:
//
//   * DrawCallCache buckets geometry by its *topological* hash, and
//     hashGeometryDescriptor (rtx_hashing.cpp) mixes in the **vertex count**. A
//     batch grows and shrinks as cars and pedestrians come into view, so its
//     bucket key changed constantly and every such frame allocated a fresh
//     BlasEntry with no history at all.
//
//   * Previous-frame vertex positions only exist when the *same* BlasEntry is
//     matched again (SceneManager::processGeometryInfo keeps them in
//     historyBuffer on kUpdateBVH). Inside a batch, vertex i belongs to whichever
//     sprite the game happened to submit i'th that frame. Two cars swapping draw
//     order silently repointed every vertex at a different object, so the
//     previous positions Remix did have described the wrong sprite - a motion
//     vector from one car to another. That is the flickering copies.
//
//   * With an identity world matrix, InstanceManager::updateInstance sees
//     hasTransformChanged == false; with no usable history hasPreviousPositions
//     is false too, and surface.isStatic is then set, which tells the renderer to
//     skip motion vector calculation for a surface that is visibly moving.
//
// So the geometry has to be the thing that stays still and the transform the
// thing that moves - which is what every other game gives Remix. Each sprite is
// now one draw call of a canonical quad in its own object space, quantised so it
// is bit-identical frame to frame, with the placement in D3DTS_WORLD. Remix then
// matches it by topological hash plus proximity (DrawCallTracker's spatial map)
// and takes the motion straight from objectToWorld against prevObjectToWorld.
//
// The cost is one draw call per sprite instead of per texture - a few hundred
// two-triangle draws, which is nothing for either D3D9 or Remix, and it lets
// every sprite of a kind share one BLAS instead of rebuilding a merged one.

class LiveGeometry {
public:
    // Public only so the object-space shape cache in live_geometry.cpp can name
    // it; nothing outside this pass has any use for it.
    struct Vertex {
        float x, y, z;
        float nx, ny, nz;
        float u, v;
    };

    void BeginFrame();

    // The floor sprites are stood on. Held, not copied; WorldView owns both this
    // and the sampler, so the pointer stays good for the process. Null, or a
    // sampler with no map in it yet, falls back to the fixed lift.
    void SetGround(const GroundSampler* ground) { ground_ = ground; }

    // A sprite quad or triangle. `vertices` is the game's screen-space array;
    // the world positions are read from its shadow slots.
    //
    // `lamps` marks the second quad the game draws for a car, its lit lamps on
    // their own (see kObjectDrawLampsReturn). That one is not placed on its own
    // at all: it takes the car body's placement from the draw just before it.
    void AddSprite(unsigned flags, const void* texture, const float* vertices, int corners,
                   bool lamps = false);

    void Draw(IDirect3DDevice9* device, const gta2::Camera& camera, int width, int height);
    void ReleaseResources();

    int SpriteQuads() const { return spriteQuads_; }
    // Sprites drawn additively last frame - the fire and explosion artwork. See
    // EffectSpriteSettings in texture_store.h.
    int EffectBatches() const { return effectQuads_; }

private:
    // One sprite: a quad in its own object space, and where that space sits in
    // the world. The vertices are the part Remix hashes, so they are quantised
    // and carry no trace of where the sprite is; the matrix is the part Remix
    // differentiates for motion, so it carries all of it.
    struct Sprite {
        const void* texture;
        Vertex local[4];
        int corners;
        gta2::Mat4 objectToWorld;
        // One of our own lamp textures instead of a game texture; see OwnCarLamps.
        const LampArt* lamp = nullptr;
        bool lampMirrored = false;
        // A decal laid with the lamp code but not lit: a car's roof number.
        bool lampPlain = false;
        // Never effect artwork, whatever its outline: a power-up token.
        bool plain = false;
        // A car's flat body, left out when its dome is drawn from hand-made
        // artwork, which would otherwise have the low-resolution sprite under it.
        bool hidden = false;
        // REMIX-3D-QUALITY: the player's own sprite in first person under Remix: never
        // drawn, only kept so his figure is drawn with the player-model textures
        // (unseen by the eye, in the shadows). See SetOwnFigureShadowOnly.
        bool shadowOnly = false;
        // FIX-FP-ENTRY: his own, from his eyes on the plain renderer: kept only so his boarding
        // plan runs (the first-person eye rides it into and out of a car); never drawn.
        bool planOnly = false;
        // A pedestrian on his feet: lifted clear of a car he is over. See Draw.
        bool pedestrian = false;
        // ... that is, or just was, getting into or out of a car: left where it is.
        bool recentlyInCar = false;
        // ... and has a vehicle of his own right now: in the middle of getting in or out.
        bool inVehicleNow = false;
        // ... in the climb into or out of a car, by his animation frame. See Draw.
        bool climbing = false;
        // A pedestrian lying on the road, dead or knocked down. Hidden under a car; see Draw.
        bool corpse = false;
        // The pedestrian's animation frame (the style sprite number within the ped
        // base) and the game's state words, for the figure's own clips. See DrawPedFigures.
        unsigned pedFrame = 0;
        int32_t pedState = -1, pedSub = 0, pedPending = 0;
        int32_t pedId = -1;   // IDENTITY-SYSTEM: the game's ped id (Ped +0x200), the identity record's seed
        // What last hurt him (game::kPedDamageCause: 1 car, 3 run over, 4 explosion, ...),
        // for the death pose; 0 unknown.
        int32_t pedCause = 0;
        // His health word (ped+0x216, int16; -1 unread): a drop with a puncher beside him is the
        // game's own "that punch landed" (ACTIONS-3D-4).
        int32_t pedHealth = -1;
        // The weapon in his hands: its ammunition and reload timer (the weapon
        // object's +0 and +2), -1 with none. A drop in the one or a restart of the
        // other is a shot, whatever the frames say (state 7 is also just standing armed).
        int32_t pedAmmo = -1, pedReload = -1;
        uintptr_t pedWeaponObject = 0;
        // Drawn through the screen-space layer, over everything, while he boards a car.
        bool boardUi = false;
        // Not drawn: a pedestrian over his car as he gets in or out. See Draw.
        bool ghost = false;
        int shell = -1;   // which dome stands in for it, in shells_
        // Small flat artwork drawn from a smoothed, enlarged copy. See SetSpriteSmooth.
        bool smooth = false;
        // The game object this quad belongs to (0: unknown); only used to follow one thing from frame
        // to frame in the flicker diagnostic.
        uintptr_t object = 0;
        // A map object (cone, bin, phone box...) drawn as this model instead of
        // its flat sprite in the street-level views. See map_objects.h.
        const struct Model* objectModel = nullptr;
        // FIX-FX-2 (pm10): the game's draw flags (0x200 additive, 0x100/0x80 blended by the
        // vertex alpha, 0x2000 vertex colour) and the first vertex's diffuse.
        unsigned gameFlags = 0;
        uint32_t gameDiffuse = 0xFFFFFFFFu;
    };
public:
    using SpriteType = Sprite;   // for the skid memory in live_geometry.cpp
private:

    // The lamps of the car drawn last, as quads of their own on its body.
    void AddCarLamps(const Sprite& body);

    // The walking figures, one per pedestrian sprite on his feet. See SetPedFigures.
    void DrawPedFigures(IDirect3DDevice9* device);
    // A car drawn as an imported model this frame, in place of its dome.
    struct CarModelUse {
        const struct Model* model;
        gta2::Mat4 placement;
        uintptr_t object;
    };
    std::vector<CarModelUse> carModels_;
    std::vector<std::pair<uintptr_t, float>> carSeenPrev_, carSeenNow_;   // (object, distance from the eye)   // car objects with a body last frame / this frame, for the pop log
    int carPops_ = 0, carPopsNear_ = 0; float carPopDist_ = 0.0f;
    std::vector<PropFootprint> propFootprints_;   // the props drawn last frame, see DrawProps
    // pm-no-contact-shadows (FIX-FIGURE-2): each car's footprint on the ground this frame
    // (four corners x/z, the ground's y), for DrawContactShadows.
    struct ContactCar { float x[4], z[4], y; bool own; const void* object = nullptr; };
    std::vector<ContactCar> contactCars_;
    std::vector<PropFootprint> contactProps_;   // the placed props' footprints, centred on the model (DrawProps)
    void DrawContactShadows(IDirect3DDevice9* device);
public:
    const std::vector<PropFootprint>& PlacedProps() const { return propFootprints_; }
private:
    void DrawCarModels(IDirect3DDevice9* device);
    // Cars built from their own sprites this frame, in place of their domes. See car_bodies.h.
    std::vector<CarBodyUse> carBodies_;
    gta2::Vec3 lastEye_{0.0f, 0.0f, 0.0f};   // where the camera was last frame, for the cars' distance
    // Street furniture and plants placed by rule from the map, around the camera.
    void DrawProps(IDirect3DDevice9* device, const gta2::Vec3& eye);
    struct PedTrack {
        float x = 0.0f, z = 0.0f;   // where the game had him last frame
        float speed = 0.0f;     // blocks a second, eased, from the game's positions
        float phase = 0.0f;     // walk cycle, radians (the box figures)
        float faceX = 0.0f, faceZ = 1.0f;   // the way the game moves him
        unsigned frame = 0;
        // The drawn figure: the game moves people in jumps and turns them on the
        // spot, so what is drawn follows a little behind, turns at a human rate
        // and plays its cycles from the ground it actually covers.
        bool placed = false;
        float dx = 0.0f, dz = 0.0f;         // drawn position
        // FIX-FIGURE-5 feel18: how far the drawn pose's lowest sole was above the floor (blocks,
        // eased), taken off the figure so a planted foot stands on the ground; and where the
        // figure was last drawn (its contact shadow goes there, not under the game's position).
        float soleDrop = 0.0f;
        float shadowX = 0.0f, shadowY = 0.0f, shadowZ = 0.0f;
        unsigned shadowFrame = 0;
        float vx = 0.0f, vz = 0.0f;         // its velocity (critically damped spring)
        float drawnSpeed = 0.0f;            // blocks a second, from the drawn motion
        float heading = 0.0f;               // drawn heading, radians, atan2(x, z)
        float turnRate = 0.0f;              // radians a second, eased (for the lean)
        float cycle = 0.0f;                 // walk/run cycle position, 0..1
        float walkWeight = 0.0f;            // 0 idle .. 1 walking, eased
        float runWeight = 0.0f;             // 0 walking .. 1 running, eased
        int idleVariant = 0;                // which idle clip he has
        float idleOffset = 0.0f, idleRate = 1.0f;
        // CROWD: where his head is turned (radians off his torso, eased), the
        // glance he is holding (its turn and the frame it ends) and the frame of
        // the next one; whether he is looking at the player now (for the log).
        float headYaw = 0.0f, glanceYaw = 0.0f;
        uint32_t glanceUntil = 0, nextGlance = 0;
        bool lookingAtPlayer = false;
        // The game's other states, as one action clip layered over the walk/idle:
        // 0 none, 1 punch, 2 aim, 3 hands up, 4 fall (held lying), 5 getting into a
        // car, 6 getting out, 7 a stagger. See PedActionFor in DrawPedFigures.
        int action = 0;
        uint32_t shotFrame = 0;   // the last frame a flash or bullet was seen beside him
        // Shooting: the weapon he holds (a PedWeapon, 0 unknown; the player's from
        // the game, a stranger's from his frames and the effects beside him), the
        // frame of his last shot (the recoil kick and muzzle glow run from it) and
        // the torso twist (radians) of an aim carried off the line of his walk.
        int weapon = 0;
        uint32_t muzzleFrame = 0;
        float twist = 0.0f;
        float muzzleX = 0.0f, muzzleY = 0.0f, muzzleZ = 0.0f;   // where his muzzle was last drawn
        float actionTime = 0.0f;            // seconds into the clip
        float actionWeight = 0.0f;          // 0 locomotion .. 1 the action, eased
        bool actionReverse = false;         // getting up: the fall played backwards
        unsigned lastPedFrame = 0;          // his sprite frame last time, to see a cycle restart
        int lastLoggedAction = 0;           // for the GTA2DX9_LOG_PED_FRAMES log
        // Actions beyond the stances (see PedActionFor and DrawPedFigures):
        int lieClip = 0;                    // which lying clip action 4 plays: 0 fall, 1 fall_front, 2 runover, 3 blown, 4 burnt
        uint32_t aimUntil = 0;              // the stance is held to this frame after the last attack or shot
        int32_t lastState = -1;             // his state word last frame (the throw on the attack's rising edge)
        int burnFrames = 0;                 // consecutive frames with the game's fire on him
        uint32_t burnSeen = 0;              // the last frame he burned (a death soon after it is burnt)
        uint32_t waterFrame = 0;            // the frame he went into the water (the drowning sinks him)
        int32_t lastAmmo = -1, lastReload = -1;   // his weapon's words last frame (a shot: see Sprite::pedAmmo)
        uintptr_t lastWeaponObject = 0;
        // QB-29 reloading (kReloads in live_geometry.cpp): the shots since the last
        // reload, the frame of the last, the frame a reload began (0 none), the clip
        // time last frame (its drop/insert events fire as it is crossed), and the
        // long gun's line in the right hand's frame, taken while both hands hold it,
        // which keeps it in the right hand while the left fetches a magazine.
        int magShots = 0;
        uint32_t magLastShot = 0, reloadStart = 0;
        int spentWeapon = 0; uint32_t spentUntil = 0;   // FIX-FIGURE-13 (pfl51): the gun the last round left, still drawn to this frame
        float reloadPrevT = -1.0f;
        float gripLocal[3] = {0.0f, 0.0f, 1.0f};
        bool gripValid = false;
        // Level of detail: his rank by distance from the eye last frame (the
        // nearest eight are posed every frame), and the pose values held for
        // the frames in between when he is further off.
        float eyeD2 = 1e9f;
        int rank = 0;
        unsigned lodFrame = 0;
        float lodU = 0.0f, lodIdleT = 0.0f, lodWalkW = 0.0f, lodRunW = 0.0f, lodActT = 0.0f, lodActW = 0.0f;
        // ACTIONS-3D-4: locomotion from the figure's own drawn motion. Where it was
        // drawn last frame (the legs step by the ground between the two, signed
        // along the legs' heading, so a push back steps back), whether it counts as
        // moving (with hysteresis), the sprint weight over the run, the turn-on-the-
        // spot cycle and weight, and the settle: after he stops, the cycle runs on to
        // the next phase where the feet pass each other before the idle takes over.
        float lastPX = 0.0f, lastPZ = 0.0f;
        bool havePrev = false;
        float legSpeed = 0.0f;              // blocks a second of the drawn figure, eased (0.1 s)
        float stepFwd = 0.0f;               // this frame's drawn ground along the legs' heading, signed
        bool moveOn = false;
        float sprintWeight = 0.0f;
        float turnCycle = 0.0f, turnWeight = 0.0f;
        // FIX-FIGURE-10 pfl31: standing, the legs hold a planted heading while the torso turns
        // (the twist), and catch up in quarter-cycle steps of turn_step (one foot lifts, swings
        // round, sets down): a turn on the spot pivots in steps, not on a turntable.
        bool plantOn = false;
        float plantYaw = 0.0f;              // the planted legs' heading
        float plantStepT = -1.0f;           // seconds into the current step, -1 none
        float plantFrom = 0.0f, plantTo = 0.0f, plantBase = 0.0f, plantRest = 0.0f;
        int plantFoot = 0;                  // the foot of the next step (0: phase 0-0.5, 1: 0.5-1)
        float plantDur = 0.24f;             // this step's length (s): shorter for a faster turn
        float pivX = 0.0f, pivZ = 0.0f;     // the root's shift that keeps the planted foot put while the legs pivot
        bool footHave = false;              // the planted foot measured this step (posed, in the world):
        float footTX = 0.0f, footTZ = 0.0f, footMX = 0.0f, footMZ = 0.0f, footRX = 0.0f, footRZ = 0.0f, footYaw = 0.0f;   // where it was set down, last seen, the root then
        float settleTo = -1.0f;
        float lodSprintW = 0.0f, lodTurnW = 0.0f, lodTurnT = 0.0f;
        // Fists: which hand the current swing throws (false: the right cross,
        // true: the left jab) and the frame of the last swing frame, so a swing
        // within a second of the last one continues the combo.
        bool punchAlt = false;
        uint32_t lastPunchFrame = 0;
        float lastPunchT = 0.0f;
        // Taking a punch: when, from which side (0 a right cross: the head turns
        // to his right; 1 a jab), and the stagger offset of the drawn figure along
        // the blow (eased out and back, the legs step it).
        uint32_t hitFrame = 0;
        int32_t lastHealth = -1;
        int hitSide = 0;   // QB-16: 2-5 shot from his front, back, left, right
        float hitDirX = 0.0f, hitDirZ = 0.0f;
        float hitPush = 0.07f;   // the stagger's reach (QB-16: by the gun)
        // FIX-FIGURE-11 (pfl38): brushed by a moving car's drawn body the game did not knock down: when and
        // by which car (one reaction per car per second).
        uint32_t brushFrame = 0;
        uintptr_t brushCar = 0;
        uint32_t sepShove = 0;   // FIX-KNOCKDOWN-4: the frame the brushing car last shoved her figure out of its body
        bool brushShy = false;   // FIX-KNOCKDOWN-4 (pfl38): that reaction was a near miss's shy (a brush may follow)
        float brushPrevX = 0.0f, brushPrevZ = 0.0f;   // his game point last frame (a figure moving with the car is in it)
        uint32_t brushPrevFrame = 0;
        float staggerX = 0.0f, staggerZ = 0.0f;
        // FIX-KNOCKDOWN (owner item 1): a car or a blast knocks him down; the game stands the player up
        // again 0.37 s later, mid-fall. The drawn knock-down runs to its end instead: impact, fall and
        // landing (the ragdoll), a beat lying down, the get-up (the lying clip that matches how the
        // ragdoll lies, turned and placed onto it), then the walk. kdSecs: time since the impact;
        // kdGameUp: the game has stood him up (his anchor is pinned there, the ragdoll no longer follows
        // the game); kdOX/Z: the figure's draw offset onto where the body lies, held through the get-up,
        // then walked off.
        bool kd = false, kdGameUp = false, kdAlign = false, kdRising = false;
        float kdSecs = 0.0f, kdSettledAt = -1.0f, kdOX = 0.0f, kdOZ = 0.0f, kdAnchorX = 0.0f, kdAnchorZ = 0.0f;
        float kdRiseLen = 0.0f, kdHeadX = 0.0f, kdHeadY = 0.0f, kdHeadZ = 0.0f;
        bool kdFaceUp = true, kdRolled = false;
        int kdRolls = 0;
        float kdRollAt = -1.0f, kdChestUp = 1.0f;
        const void* kdModel = nullptr;   // the avatar drawn last frame and its signed horizontal scale (the get-up's placing)
        float kdScaleS = 0.0f;
        // FIX-KNOCKDOWN-3 (pf3): where the get-up is drawn, pinned in the world while it plays (the game runs an
        // NPC on meanwhile: a held offset slid the rising figure along at the game's pace, a skate).
        bool kdRisePinned = false;
        float kdPinX = 0.0f, kdPinZ = 0.0f;
        // FIX-FIGURE-6 (pm24 gang interpenetrating, pm3 ped inside a parked car): a draw-only offset
        // that keeps the figure out of its neighbours' bodies and out of car bodies, eased; the
        // car it is being kept out of and the side chosen on the way in (no flip at the middle).
        float sepX = 0.0f, sepZ = 0.0f;
        uintptr_t sepCar = 0;
        int sepAxis = 0;      // 0: across the car (out of a flank), 1: along it (out of an end)
        float sepSign = 1.0f;
        float sepDrawnX = 0.0f, sepDrawnZ = 0.0f;   // FIX-FIGURE-7: where it was drawn last (the others separate from this)
        bool sepMovableLast = false;                // FIX-FIGURE-16 (pm24): whether the separation moved it last frame
        uint32_t sepSeenFrame = 0;
        // FIX-ACTIONS-3 (pfl15): a punch that knocked him down (the game sets the knock-down in the
        // frame the health drops): the blow's reaction first (punchDownFrame), then the fall onto his
        // back away from the puncher, the stagger held while he lies (downHold, eased out as he rises).
        uint32_t punchDownFrame = 0;
        float punchByX = 0.0f, punchByZ = 0.0f;
        float downHold = 0.0f;
        // FIX-ACTIONS-3: the puncher's mark (a figure in reach in front of him), for the turn onto it.
        bool punchAim = false;
        float punchAimX = 0.0f, punchAimZ = 0.0f;
        uintptr_t punchAimObj = 0;   // kept through the combo while he stays in reach (no swap mid-swing)
        // FIX-ACTIONS-3: the thrown driver's drawn spot held off the game's (outside the car's body,
        // where he landed) while he lies; eased back onto the game's spot once he is up.
        float jackRestX = 0.0f, jackRestZ = 0.0f;
        bool jackRest = false;
        float jackRestW = 0.0f;
        // Getting into / out of a car: the car's middle (the heading faces it on
        // the way in and away from it on the way out) and when the state began.
        bool carKnown = false;
        float carX = 0.0f, carZ = 0.0f;
        uint32_t carStateFrame = 0;
        int32_t carState = -1;
        bool grabLeft = false;              // running beside a moving car: it is on his left
        // QB-14 jacking: boarding a car with a driver at the wheel (jack_pull for the
        // enter_car layer); the driver thrown out of it (lying clip 5, "jacked") and when.
        bool jacking = false;
        // FIX-JACK-SEAT: the boarding plan's clock rate this frame (it catches up once the game has him
        // in) and whether it holds him at the yanked door (jack_pull tugs meanwhile), seconds of the tug
        float boardRate = 1.0f;
        bool boardHeld = false;
        float tugT = 0.0f;
        bool jacked = false;
        uint32_t jackFrame = 0;
        float jackCarX = 0.0f, jackCarZ = 0.0f;   // FIX-JACK-SEAT: the jacked car's spot at the throw (his way out of it)
        float carSpeed = 0.0f;              // that car's own pace, blocks a second, eased: moving or parked
        uint32_t carSeenFrame = 0;
        // The clip an action ended on and where, faded out over the locomotion
        // instead of dropped in one frame (ends of punches, exits, hits).
        const void* fadeClip = nullptr;
        float fadeT = 0.0f;
        // QB-20/21/39: the mocap transitions over the cycle (Model::Loco tables): 0 none,
        // 1 walk start, 2 run start, 3 walk stop, 4 run stop, 5 a fidget while standing;
        // seconds into its clip, the ground covered since a start began (blocks), its
        // weight; the time he has stood still and his next fidget; the forward lean of
        // acceleration (radians, on a spring) and the pace it is measured from.
        int trans = 0;
        float transT = 0.0f, transDist = 0.0f, transW = 0.0f, transEnd = 0.0f;
        float stillTime = 0.0f, fidgetAt = 0.0f;
        int fidgetNext = 0;
        float lean = 0.0f, leanV = 0.0f, leanSpeed = 0.0f;
        float lodTransT = 0.0f, lodTransW = 0.0f;
        float paceHold = 0.0f;              // his recent top leg pace, falling 2 blocks/s a second (which stop)
        // ANIM-BLEND-AUDIT: the start/stop/fidget drawn last frame (clip, time, weight) and one
        // cut short, fading out from where it stopped over 0.25 s.
        const void* transDrawnClip = nullptr;
        float transDrawnT = 0.0f, transDrawnW = 0.0f;
        const void* transFadeClip = nullptr;
        float transFadeT = 0.0f, transFadeW = 0.0f, transFadeK = 0.0f;   // its weight when cut, and 1 -> 0
        float transAge = 0.0f;              // real seconds since the start/stop/fidget began
        float cycleVis = 1.0f;              // how much of the moving cycle shows (0 while a start comes in)
    };
    std::map<uintptr_t, PedTrack> pedTracks_;
    // ANIM-VEHICLE-ENTRY: the last sprite of each ped boarding a car (state 3) and its
    // frame, drawn on as a ghost after the game stops drawing him (boarding.h).
    std::map<uintptr_t, std::pair<uint32_t, Sprite>> boardSprites_;
    // FIX-SEATED: the player's last real sprite (any state), for his seated ghost when no
    // boarding brought him into the car (a scene warp, a start at the wheel).
    std::pair<uint32_t, Sprite> ownSprite_{0u, Sprite{}};
    // FIX-SEATED: each boarding sprite object's ped (resolved while the game still drew him: the
    // sprite object's owner chain is not kept while he sits in the car).
    std::map<uintptr_t, uintptr_t> boardPeds_;

    // One car's dome: the car's own sprite, drawn a second time as a grid that
    // swells from nothing at its edges to a rounded top, so that the body has
    // surfaces facing every way to reflect with. There are no walls: the dome
    // meets the ground at the sprite's own outline. Same object space and
    // placement as the body, and textured with the same artwork.
    static constexpr int kDomeSegments = 8;
    static constexpr int kDomeVertices = (kDomeSegments + 1) * (kDomeSegments + 1);
    static constexpr int kDoorSegments = 4;
    static constexpr int kDoorVertices = (kDoorSegments + 1) * (kDoorSegments + 1);
    struct CarShell {
        const void* texture;
        int sprite = -1;   // the sprite number within the car base
        uintptr_t object = 0;   // the game object it belongs to
        gta2::Mat4 objectToWorld;
        Vertex local[kDomeVertices];
        // The car's open doors and dents, each a grid laid over the dome where the
        // delta's pixels are. See BuildCarDoors.
        struct Door {
            int delta = 0;
            const LampArt* art = nullptr;
            Vertex local[kDoorVertices];
        };
        std::vector<Door> doors;
        // Four tyres: one shared mesh, centred on its own origin, and where each goes.
        // The front pair's matrices carry the steering, so the mesh itself never
        // changes and Remix sees the same shape every frame.
        static constexpr int kTyreVertices = 20;
        Vertex tyreMesh[kTyreVertices];
        std::vector<gta2::Mat4> tyres;
    };
    std::vector<CarShell> shells_;
    // Fills shell->tyres. `peak` is the dome's height, signed by which way up is.
    void BuildCarTyres(const Sprite& body, CarShell* shell, const void* object, float peak);
    // Fills shell->doors from the car's delta mask. Needs the body's corners.
    void BuildCarDoors(const Sprite& body, CarShell* shell, const void* object);

    // If `body` is a car, builds its skirt and lifts and shrinks the body to sit
    // on it. Everything it changes is a constant of the sprite and the settings,
    // so Remix still sees the same shape every frame.
    void RaiseCarBody(Sprite* body);

    // One entry per sprite already placed this frame, for spotting a stack.
    struct Stack {
        float x, z;
        float area;   // of the quad's footprint, in square blocks
        int layer;
    };
    std::vector<Stack> stacks_;

    // What a sprite was given last frame, so this frame can move toward its
    // answer instead of jumping to it.
    //
    // The ground under a footprint is not a continuous function of where that
    // footprint is: a corner crossing a kerb, or the crest where a ramp meets
    // flat, changes the fitted plane in one step. Applied directly that is a
    // sprite which twitches as it drives, so both the lift and the tilt are
    // eased toward the answer instead of being set to it.
    //
    // Sprites have no identity in this stream - they are rebuilt from scratch
    // every frame - so the match is the same trick the stack finder uses:
    // nearest entry from last frame with the same texture, within a radius wider
    // than anything can travel in one frame. No match means the sprite is new
    // and gets its answer immediately; easing one in from nothing would be the
    // visible pop this exists to remove.
    struct Track {
        const void* texture;
        float x, z;
        float offset;
        float nx, ny, nz;
    };
    std::vector<Track> tracks_;      // last frame
    std::vector<Track> tracksNext_;  // being built this frame

    // Nearest match from last frame, or null.
    const Track* FindTrack(const void* texture, float x, float z) const;

    int StackLayerFor(float cx, float cz, float area);

    bool ReadCorners(const float* vertices, int corners, const void* texture, uintptr_t shadowBase,
                     Vertex* out) const;
    // Splits world-space corners into a canonical object-space quad and the
    // transform that places it. False if the quad has no area to build a frame
    // from.
    //
    // `centre` is where the sprite ends up, which is not the centroid of the
    // corners: the corners are the shape, the centre is the placement. `groundUp`
    // rotates the sprite onto the floor - null, or an exactly vertical one,
    // leaves the frame the corners themselves describe.
    struct Vec3 {
        float x, y, z;
    };
    bool Place(const Vertex* world, int corners, const Vec3& centre, const Vec3* groundUp,
               Sprite* out) const;

    const GroundSampler* ground_ = nullptr;
    std::vector<Sprite> sprites_;
    // The last sprite placed and the game object it was drawn for, so a car's
    // lamp quad can be laid on its body.
    const void* lastObject_ = nullptr;
    size_t lastSprite_ = 0;
    int spriteQuads_ = 0;
    int effectQuads_ = 0;
    int spriteLogs_ = 0;

public:
    // Why sprites the game asked for did not reach the screen. Every one of
    // these is a frame where something the player can see is simply absent.
    struct Drops {
        int accepted = 0;  // quads we took from the game
        int drawn = 0;     // quads that actually reached the device
        int expandFlag = 0;
        // FIX-SPRITES-1: the game's drop shadows (kObjectDrawShadowReturn), dropped on purpose:
        // the street views give figures and models shadows of their own, and the classic view
        // never drew them. Not trouble, so not in Quiet(). (They were all of 'wrongarray'.)
        int gameShadow = 0;
        int notTheSpriteArray = 0;   // any other draw not from the game's sprite array: a real loss
        int notFinite = 0;
        int outOfWorld = 0;
        int degenerate = 0;
        int noTexture = 0;
        // FIX-SPRITES-1: where each sprite LiveGeometry::Draw received went (sum = sprites
        // received, which is 'accepted' in the same window): a 3D model stands in, his own (unseen
        // from his eyes), ghost/debug, lamp, queued to be drawn (a quad, an effect, a soft puff; of those,
        // drawn as a figure), and none of those: 'unplaced' by sprite kind (car = has a dome or model), the candidates for a hole.
        int received = 0, fateModel = 0, fateOwn = 0, fateGhost = 0, fateLamp = 0, fateQueued = 0,
            fateFigure = 0, unplacedPed = 0, unplacedCar = 0, unplacedOther = 0;
        bool Quiet() const {
            return !expandFlag && !notTheSpriteArray && !notFinite && !outOfWorld && !degenerate &&
                   !noTexture;
        }
    };
    const Drops& DropCounts() const { return drops_; }
    void ClearDropCounts() { drops_ = Drops{}; }

    // What the conform actually did, per frame. This is the health check on the
    // whole scheme: `grounded` should be nearly every sprite in a normal street,
    // and a large `maxGap` on a frame with nothing in the air means the game's
    // own level for a sprite disagrees with the lid the map says is under it -
    // which is the one thing that would make conforming pointless rather than
    // wrong, and it is measured here rather than assumed.
    struct Conform {
        int grounded = 0;    // stood and rotated onto a fitted plane
        int airborne = 0;    // above its floor, so left where the game put it
        int noGround = 0;    // nothing under the footprint; fixed lift used
        int capped = 0;      // ground steeper than kMaxTiltDegrees
        int straddled = 0;   // footprint over a step, given extra clearance
        // FIX-SPRITES-1 (B2): 'airborne' is now a car or pedestrian more than kAirborneGap above the
        // highest real floor under its footprint (what it rests on), not above the plane fitted
        // across a step; above the fitted plane but on the upper floor of a step is 'onstep'; an
        // object the game itself holds up (a lamp-post head, a lamp quad, a particle) is 'raised'.
        int onStep = 0;
        int raised = 0;
        float raisedMaxGap = 0.0f;
        float maxGap = 0.0f;       // furthest any car or pedestrian sat above its own floor
        float maxResidual = 0.0f;  // worst a footprint failed to be one plane
    };
    const Conform& ConformCounts() const { return conform_; }
    void ClearConformCounts() { conform_ = Conform{}; }

private:
    mutable Drops drops_;
    mutable Conform conform_;
};

// The last complete frame's conform counts, for the menu. A free function for
// the same reason EffectBatchesDrawn is one: nothing outside WorldView holds the
// LiveGeometry instance.
const LiveGeometry::Conform& SpriteConformCounts();

// FIX-SPRITES-1: the object draw's call site of the sprite about to reach AddSprite (the
// GTA2DX9_LOG_SPRITE_DROPS probe names dropped draws by it).
void SpriteDrawSite(const void* site);

// Milliseconds the last LiveGeometry::Draw spent in each of five stages: setup, the sprite
// loop, remembered skid strips, issuing sprites and smoke, and the cars' domes. For the log.
constexpr int kDrawStages = 9;   // see g_drawStageMs in live_geometry.cpp
const double* LiveDrawStageMs();

}  // namespace gta2dx9
