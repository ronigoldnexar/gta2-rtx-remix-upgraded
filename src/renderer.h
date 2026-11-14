// D3D9 fixed-function renderer for GTA2 world geometry.
//
// Deliberately fixed-function and untransformed: RTX Remix path traces draws
// whose vertices are in object/world space and whose projection is perspective,
// and skips anything using pre-transformed (D3DFVF_XYZRHW) vertices. Lighting
// and shadowing are left to Remix.
#pragma once

#include <d3d9.h>

#include <map>
#include <string>
#include <vector>

#include "camera.h"
#include "gta2_style.h"
#include "post_fx.h"
#include "kit_stream.h"
#include "water.h"
#include "sky.h"
#include "weather_fx.h"
#include "world_mesh.h"

namespace gta2 {

struct RenderStats {
    int drawCalls = 0;
    int triangles = 0;
};

// How the world is shaded in the street-level views (see sky.h): distance fog
// in the horizon's colour, and a directional sun with an ambient term applied
// through fixed-function lighting over the mesh's face normals. Everything off
// is the classic view: unlit texture, no fog, as it always was.
struct WorldShading {
    bool fog = false;
    Vec3 fogColour;
    float fogStart = 30.0f;
    float fogEnd = 140.0f;
    bool sun = false;
    Vec3 sunDir{0.0f, 1.0f, 0.0f};   // toward the sun
    Vec3 sunColour;                   // the sun's contribution on a face squarely facing it
    Vec3 ambient{1.0f, 1.0f, 1.0f};   // the rest
};

// Optional trace sink for device bring-up. The in-process DLL points it at
// gta2dx9.log so each D3D9 call can be timestamped and lined up against RTX
// Remix's own bridge logs; the standalone viewer leaves it null.
void SetRendererTrace(void (*sink)(const char*));

// How a cutout's edge is resolved. Alpha test is the default and is what a path
// tracer wants - a blended surface has no single depth for a ray to hit - but
// now that transparent texels carry a sensible colour (see alpha_bleed.h) it is
// worth being able to compare them by eye rather than by argument.
enum class AlphaMode { Test, Blend };
void SetAlphaMode(AlphaMode mode);
AlphaMode GetAlphaMode();
void SetAlphaRef(int ref);   // 1..254, the alpha-test cutoff
int  GetAlphaRef();

// High-resolution tile artwork. With a folder set, a tile whose
// `<folder>\tile_NNNN.tga` exists (32-bit uncompressed TGA, any size) is
// uploaded at that size instead of the game's 64x64; tools/upscale_textures.py
// makes those on a GPU from a dump. A dump folder set makes UploadWorld write
// every tile it uses there as tile_NNNN.tga, once per world. Empty disables.
void SetHdTextureDir(const char* dir);
// Photo-material tiles (tools/photoreal_tiles.py), loaded before the HD folder's, per style
// subfolder; ignored on an RTX Remix device. Empty disables.
void SetPhotoTextureDir(const char* dir);
// Re-authored road-marking tiles (tools/reauthor_road_markings.py over the photo set), per
// style; street views only like the photo tiles, and loaded before them.
void SetRoadTextureDir(const char* dir);
// Street views: ground tiles tinted toward the game tile's mean (DdsTint), on by default.
void SetToneMatch(bool on);
void SetTileDumpDir(const char* dir);
// Tile numbers are per style file (wil.sty, bil.sty, ste.sty), so both folders
// hold one subfolder per style, named by this: the style file's name without
// its extension. Set before UploadWorld.
void SetTileStyleName(const char* name);
// The street views' water surface effect (ripples and a sky tint on the water
// tiles); on by default, off leaves the water the flat animated tile.
void SetWaterEffect(bool on);
void SetWindowGlow(bool on);
// The largest size a high-resolution tile is uploaded at; larger files are
// box-filtered down to it on load. 800 tiles at 256x256 cost the game's 32-bit
// process half a gigabyte of textures, which it does not have; 128 is 2x the
// game's own and a quarter of that.
void SetHdTileMaxSize(int size);
// Anisotropic filtering level for the HD tiles: 0 picks 8 on a GPU and 1 (plain
// trilinear) when the Direct3D adapter is a software renderer, where 8x costs
// most of the frame.
void SetAnisotropy(int level);

class Renderer {
public:
    ~Renderer();

    bool Initialize(HWND window, int width, int height, std::string* error);
    bool UploadWorld(const WorldMesh& mesh, const Style& style, std::string* error);

    // Split so the screen-space pass (HUD, menus, sprites) can be drawn between
    // the world and the present.
    bool BeginFrame();
    void DrawWorld(const Camera& camera);
    void EndFrame();

    // The sky dome, sun and clouds, drawn around the camera over the cleared
    // frame and before the world, weighted by blend (0 draws nothing).
    void DrawSky(const Camera& camera, const SkySettings& settings, const SkyColours& colours, float blend,
                 double seconds);
    // The fog and sun for DrawWorld and for the live geometry drawn after it,
    // which inherits the fog state; EndWorldShading turns both off again before
    // the screen-space passes.
    //
    // In a street view with [visuals] on (and no RTX Remix) this also switches the
    // frame to the post targets (post_fx.h) and rebalances the sun and ambient for
    // the shadows; EndWorldShading then resolves the post onto the back buffer.
    void SetWorldShading(const WorldShading& shading);
    const WorldShading& Shading() const { return shading_; }
    void EndWorldShading();
    void SetWetTiles(const std::vector<uint8_t>& tiles) { wetTile_ = tiles; }
    void SetWetLevel(int level) { wetLevel_ = level < 0 ? 0 : (level > 3 ? 3 : level); }
    int WetLevel() const { return wetLevel_; }
    // Logs every wet tile's three variant hashes ("wet variant:" lines) for tools/remix_wet_levels.py.
    int DumpWetManifest();
    // Makes every wet variant (3 per wet tile) of the texture the street views bind; level load only.
    int PreloadWetVariants();
    // WEATHER-V2: the rain's camera and view weight on a Remix device (see WeatherFx::SetRemixFrame).
    void SetRemixWeatherFrame(const Camera& camera, float blend);
    void SetPuddleField(const std::vector<uint8_t>& t, int size) { weather_.SetPuddleField(t, size); }
    void DrawScreenRain(float streetWeight) { weather_.DrawScreenRain(width_, height_, streetWeight); }
    void DrawLensDrops(float firstPersonWeight) { weather_.DrawLensDrops(width_, height_, firstPersonWeight, remixDevice_ ? nullptr : savedTarget_); }

    // GTA2 animates a tile - ceiling fans, screens, water - by changing the
    // artwork behind its number while the map itself stays put, so the world
    // mesh never changes but its textures have to be refreshed.
    bool HasTileTexture(int tile) const {
        return tile >= 0 && tile < static_cast<int>(textures_.size()) && textures_[tile] != nullptr;
    }
    void UpdateTileTexture(int tile, const uint32_t* pixels);
    // The photo-material tiles (photo_tiles) belong to the street views only: the
    // classic view keeps the plain HD set, byte-for-byte as before the photo set
    // existed (and the one Remix's hashes are keyed on). The caller says each
    // frame whether a street view is showing.
    // on: the street presentation (its street-only fill drawn); photoMix: how far the
    // ground's material has gone from the plain HD set (0) to the photo set (1). Between
    // the two, DrawWorld cross-fades a tile's two textures on the same triangles
    // (FIX-SMOOTH-SWITCH, the camera move between the views). The settled classic view
    // is (false, 0): exactly the draws it had before.
    // roadMix (FIX-TRANSITION-ART): the same for the tiles whose street copy is a re-authored
    // road-marking tile (gta2dx9_textures_hd/roads): their plain HD art is the noisy upscale
    // (zebra stripes as black-and-white worms), so the caller brings the clean paint in on a
    // ramp near the classic end of the move rather than the middle. Negative: as photoMix.
    void SetStreetView(bool on, float photoMix, float roadMix = -1.0f) {
        streetView_ = on;
        photoMix_ = photoMix < 0.0f ? 0.0f : (photoMix > 1.0f ? 1.0f : photoMix);
        roadMix_ = roadMix < 0.0f ? photoMix_ : (roadMix > 1.0f ? 1.0f : roadMix);
    }
    // FIX-WORLD-16 qav59: in first person (and only there) a sparse see-through lattice (pylon girders:
    // keyed side tiles under 30 % opaque) nearer the eye than `ahead` blocks along the view is clipped
    // away, so an eye that stands inside a pylon's lattice block does not see one of its faces edge-on
    // as a flat black slab down the frame edge. 0 (the default, every other view): no clip.
    // FIX-CAMERA-20: lids too (the third-person lens: a truss's lattice deck between it and him); first person leaves them
    // DISTRICTS-POC: the facade kit's batches (TileBatch::kit) are drawn at this opacity (the street
    // extras' ramp over the move from the classic view: below 1 they go through the see-through pass, as
    // the fading street lights do, so nothing pops), and not at all when !visible (a live A/B).
    // DISTRICTS streaming (kit_stream.h): load <style>.kit2 for this level (after UploadWorld); its chunks are
    // streamed around the eye and drawn after the world's batches, faded by SetKitPresentation as the static kit is.
    bool LoadKitStream(const std::string& path, const Style& style);
    KitStreamStats KitStreamStatus() const { return kitStream_.Stats(); }
    bool KitStreaming() const { return kitStream_.Loaded(); }
    // DISTRICTS round 5: how lit each of the kit's 32 sign switch-on buckets is now, 0..1 (the DLL's staggered
    // street-light clock, time_of_day.h); emissive kit groups get their "_lit" material added at that share
    void SetKitSignLights(const float* share32) { for (int k = 0; k < 32; ++k) kitSign_[k] = share32[k]; }
    void SetKitPresentation(float alpha, bool visible) {
        kitAlpha_ = alpha < 0.0f ? 0.0f : (alpha > 1.0f ? 1.0f : alpha); kitVisible_ = visible;
        post_.SetKitShadow(visible && streetView_ ? kitAlpha_ : 0.0f);
    }
    void SetSeeThroughNearClip(float ahead, bool lids = false) { seeThroughClip_ = ahead > 0.0f ? ahead : 0.0f; seeThroughClipLids_ = lids; }
    // FIX-PERF-9 (14p3): the street views leave out the world's tile batches (and the ends of a batch's
    // index range) whose triangles lie wholly outside the view frustum. Exact: a triangle outside a
    // frustum plane rasterises nothing. Never in the classic view, never under Remix (its draws are
    // hashed by their ranges and it sees off-screen geometry). [renderer] world_view_cull.
    void SetWorldViewCull(bool on) { worldViewCull_ = on; }
    bool WorldViewCull() const { return worldViewCull_; }
    // The clock the street-level water effect scrolls by (seconds); any
    // monotonic clock, the sky's is used.
    void SetWaterClock(double seconds) { waterClock_ = seconds; }
    int TileTextureCount() const { return static_cast<int>(textures_.size()); }
    // Uploads up to perFrame not-yet-drawn tile textures (no visible draw); returns how many remain.
    int WarmTileTextures(int perFrame);
    // FIX-PERF-VSWITCH: a street frame drawn where nothing shows, so the driver builds the GL
    // programs the street views need (wined3d makes one per fixed-function state and one per
    // shader, on first use: most of the first V's freeze) while the classic view is up.
    // BeginGhostFrame points the device at targets of its own with every state captured;
    // EndGhostFrame puts back the targets, the states, the street flag and the shading.
    bool BeginGhostFrame();
    void EndGhostFrame();

    bool HasWorld() const { return vertexBuffer_ != nullptr; }
    // How many tiles of the current world came from the high-resolution folder.
    int HdTileCount() const { return hdTiles_; }
    int HdDdsTileCount() const { return hdDdsTiles_; }   // of those, block-compressed with mips
    int HdFailedCount() const { return hdFailed_; }      // HD files found but not loadable (memory, format)

    // Drop the level's geometry without touching the device, the window or the
    // tile textures. The game frees its map when it returns to the menu, and
    // without this the last level goes on being drawn - and path traced - behind
    // the menu.
    void ReleaseWorld();

    // --- The 2D layer ------------------------------------------------------
    //
    // GTA2's menu is an incremental painter. gta2.exe!0x00461960 draws the
    // menu, flips, and then clears the screen *only* if one of five repaint
    // flags is set (0x5EAD9C, 0x5EAD8C, 0x5EAD5F, 0x5EAD67, 0x5EAD59) - and
    // otherwise returns without clearing. So the front end sends its background
    // once, its animated panel now and then, and its text every frame, on the
    // understanding that whatever it drew before is still on screen.
    //
    // A pass that rebuilds from an empty list every frame therefore shows each
    // of those for exactly the frame it arrives on. These give the 2D stream the
    // surface it thinks it has: an offscreen target that is kept between frames
    // and cleared only when the game says to.
    bool BeginUiLayer(bool clearNow);
    void EndUiLayer();
    void NoteScreenClear() { uiClearPending_ = true; }
    bool HasUiLayer() const { return uiTexture_ != nullptr; }

    // How RTX Remix tells UI from world, on NVIDIA's runtime and Remix Plus alike
    // (d3d9_rtx.cpp, isRenderingUI): a fixed-function draw with an orthographic
    // projection - D3DTS_PROJECTION[3][3] == 1 - and Z writes off. The first such
    // draw of a frame is where the path traced image is put down; everything
    // after it is rasterized on top, with our own blend and texture states.
    //
    // Pre-transformed vertices ignore the projection entirely, so this changes
    // what Remix concludes and nothing about what is drawn. Screen: the draws
    // that follow are the frame's UI. Layer: they are not, whatever the target.
    void MarkDrawsAsScreenUi();
    void MarkDrawsAsNotUi();

    int Width() const { return width_; }
    int Height() const { return height_; }

    // Releases the device and every resource. Must run before the game tears its
    // window down: a live device on a destroyed window keeps the process alive.
    void Shutdown();

    void ToggleWireframe() { wireframe_ = !wireframe_; }
    // The classic-to-street dissolve (BEV-PURITY, docs/bev-parity.md "BEV purity at the switch"):
    // KeepFrame copies the finished back buffer (one GPU blit) on every settled classic
    // frame; DrawKeptFrame lays that copy over the frame being drawn. At alpha 1 the draw
    // is an unblended point-sampled copy, so the first frame of the camera move is the
    // last classic frame bit for bit. Plain renderer only: under RTX Remix the back
    // buffer does not hold the path-traced picture, so KeepFrame keeps nothing.
    void KeepFrame();
    // LIGHTING-V1: the classic frame graded toward night (post_fx.h PostFx::ClassicNight); never on a Remix device.
    bool ClassicNight(const float tint[3], float amount, const std::vector<PostFx::ClassicPool>& pools) {
        return !remixDevice_ && post_.ClassicNight(tint, amount, pools);
    }
    bool HasKeptFrame() const { return keptValid_; }
    void DropKeptFrame() { keptValid_ = false; }
    void DrawKeptFrame(float alpha);
    // Verification (GTA2DX9_DISSOLVE_VERIFY=1): how many pixels of the back buffer as drawn
    // so far differ from the kept frame (-1 when it cannot be read back).
    long KeptFrameDifference();
    void CycleCullMode();
    const RenderStats& Stats() const { return stats_; }
    IDirect3DDevice9* Device() const { return device_; }
    PostFx& Post() { return post_; }
    // The device came from RTX Remix's d3d9 (the bridge client): Remix lights the scene,
    // so the plain renderer's shadows and post passes never run.
    bool IsRemixDevice() const { return remixDevice_; }

private:
    IDirect3DSurface9* ghostRt_ = nullptr;
    IDirect3DSurface9* ghostDepth_ = nullptr;
    IDirect3DSurface9* ghostSavedRt_ = nullptr;
    IDirect3DSurface9* ghostSavedDepth_ = nullptr;
    IDirect3DStateBlock9* ghostState_ = nullptr;
    WorldShading ghostShading_;
    bool ghostStreet_ = false;
    float ghostPhotoMix_ = 0.0f;   // FIX-SMOOTH-SWITCH: the material mix, restored with streetView_
    float ghostRoadMix_ = 0.0f;
    void ApplyFixedFunctionState();
    void ReleaseResources();

    IDirect3D9* d3d_ = nullptr;
    IDirect3DDevice9* device_ = nullptr;
    IDirect3DTexture9* uiTexture_ = nullptr;
    IDirect3DSurface9* uiSurface_ = nullptr;
    IDirect3DSurface9* savedTarget_ = nullptr;
    bool uiClearPending_ = true;
    IDirect3DTexture9* keptTexture_ = nullptr;   // KeepFrame's copy of the last classic frame
    IDirect3DSurface9* keptSurface_ = nullptr;
    bool keptValid_ = false;
    bool keptFailed_ = false;

    IDirect3DVertexBuffer9* vertexBuffer_ = nullptr;
    IDirect3DIndexBuffer9* indexBuffer_ = nullptr;
    std::vector<IDirect3DTexture9*> textures_;  // indexed by tile id, may contain nulls
    // Every distinct frame of tile artwork, keyed by content, and the owner of
    // all of them. An animated tile swaps textures_[tile] to point at a
    // different one of these rather than rewriting the pixels of the one it has,
    // which is what gives each frame its own Remix hash. See UpdateTileTexture.
    std::map<uint64_t, IDirect3DTexture9*> tileFrames_;
    // Every tile of the style by the same content hash, so a frame the game
    // uploads for an animated tile can be recognised as "tile N of the style"
    // and shown with tile N's high-resolution artwork (UpdateTileTexture).
    std::map<uint64_t, int> tileByContent_;
    std::map<uint64_t, int> photoByContent_;   // the same, only tiles with a photo variant
    std::string hdDir_;                // the style's HD folder, "" when none
    std::string photoDir_;             // the style's photo-material folder, "" when off
    int photoTiles_ = 0;
    std::string roadDir_;              // the style's re-authored road-marking folder, "" when off
    int roadTiles_ = 0;
    std::vector<float> streetTint_;    // per tile, 3 factors for its street-view copy (1 = as shipped)
    int toneTiles_ = 0;
    // Per tile: the photo-material variant, bound instead of textures_[tile] while
    // streetView_. An animated tile's slot points at its frames; while a frame that is
    // itself a tile with a photo variant shows, that variant is bound instead, and stays
    // bound through frames that match no tile (animatedPhotoFrame_: the last such frame's
    // tile, -1 for none; never for water). The Industrial LIVE SHOW neon (412/413) (pm21).
    std::vector<IDirect3DTexture9*> photoTextures_;
    std::vector<uint8_t> tileAnimated_;
    std::vector<int> animatedPhotoFrame_;
    bool streetView_ = false;
    // FIX-TRANSITION-ART (pmab5-bil lamp masts): the map's street-light poles and arms (world_mesh.h
    // StreetPole), grouped per street light (the stacked segments of one pole and its arm), with each
    // group's alpha. While the camera moves between the views (SetMoveOccluders) a light standing
    // nearer the lens than the hero whose post would be drawn wide, or across a large part of the
    // frame, fades out (about six frames) and back once it no longer would or the move has ended;
    // DrawWorld draws those batches around it and the fading ones blended after the rest.
    // GTA2DX9_MOVE_POLE_FADE=0: off. Never on a Remix device (its draws are hashed by their ranges).
    std::vector<StreetPole> streetPoles_;
    std::vector<int> poleGroup_;                 // per pole: its street light
    struct PoleGroup { float x, z, lo, hi, r; float alpha = 1.0f; };
    std::vector<PoleGroup> poleGroups_;
    std::vector<std::vector<int>> polesOfBatch_; // per batch: its poles, by index start
    bool moveOccMoving_ = false;
    Vec3 moveOccHero_{0.0f, 0.0f, 0.0f};
    bool anyPoleFaded_ = false;
    int poleFadeLogs_ = 0;
    void UpdatePoleFades(const Camera& camera);
public:
    void SetMoveOccluders(bool moving, const Vec3& hero) { moveOccMoving_ = moving; moveOccHero_ = hero; }
private:
    float photoMix_ = 0.0f;
    float kitAlpha_ = 1.0f;             // see SetKitPresentation
    KitStream kitStream_;
    std::vector<PostFx::StreamCaster> kitCasters_;
    float kitSign_[32] = {};   // DISTRICTS round 5: the night share of each sign switch-on bucket (SetKitSignLights)   // the resident chunks as shadow casters (post_fx), refilled each frame
    void DrawKitStream(const Camera& camera);
    IDirect3DTexture9* KitMaterialTexture(const Style& style, int tile);
    bool kitVisible_ = true;
    float roadMix_ = 0.0f;              // see SetStreetView
    std::vector<uint8_t> roadTile_;     // per tile: 1 when its street copy came from the roads set
    float TileMix(int tile) const {
        return (tile >= 0 && tile < static_cast<int>(roadTile_.size()) && roadTile_[static_cast<size_t>(tile)]) ? roadMix_ : photoMix_;
    }
    IDirect3DTexture9* LoadPhotoTileTexture(int tile, int wetVariant = 0);
    // WEATHER-V2 (C, stepped wet materials): under Remix, in the street views, a road or pavement
    // lid tile is drawn with a wet variant of its photo texture at wetness levels 1-3 (damp, wet,
    // soaked): the same texels with one byte of the top mip changed, so Remix keys a material of
    // its own (gta2hd's wet prims, tools/remix_wet_levels.py). The DLL logs each variant's hash.
    std::vector<uint8_t> wetTile_;
    std::vector<IDirect3DTexture9*> wetPhoto_;   // tile * 3 + level - 1
    int wetLevel_ = 0;
    IDirect3DTexture9* WetBoundTileTexture(int tile);
    IDirect3DTexture9* LoadHdTileVariant(int tile, int wetVariant);
    std::vector<IDirect3DTexture9*> wetHd_;   // tile * 3 + level - 1, for tiles bound with their HD texture
    IDirect3DTexture9* PhotoTileTexture(int tile) const {
        if (tile < 0 || tile >= static_cast<int>(photoTextures_.size())) return nullptr;
        if (!tileAnimated_[tile]) return photoTextures_[tile];
        // An animated tile: its current frame's photo copy, if the frame has one (pm21).
        if (tile < static_cast<int>(animatedPhotoFrame_.size()) && animatedPhotoFrame_[tile] >= 0)
            return photoTextures_[static_cast<size_t>(animatedPhotoFrame_[tile])];
        return nullptr;
    }
    // The one texture a tile is drawn with where no cross-fade is done: the photo set
    // from half way through the material's change-over.
    IDirect3DTexture9* BoundTileTexture(int tile) const {
        if (TileMix(tile) >= 0.5f)
            if (IDirect3DTexture9* photo = PhotoTileTexture(tile)) return photo;
        return textures_[tile];
    }
    std::vector<uint8_t> waterTile_;   // per tile: 1 when it is the water surface
    std::vector<uint8_t> sparseLattice_;   // per tile: 1 for a keyed tile under 30 % opaque (SetSeeThroughNearClip)
    float seeThroughClip_ = 0.0f;
    bool seeThroughClipLids_ = false;   // FIX-CAMERA-20
    // Window tiles of the street views: a glow texture per tile (the room's
    // light behind the glass, black elsewhere), added over the wall when the
    // sun is low. Null for tiles without windows. See MakeWindowGlow.
    std::vector<IDirect3DTexture9*> windowGlow_;
    std::vector<IDirect3DTexture9*> windowSky_;   // FIX-WORLD-7 (pm12): the same glass by day, reflecting the sky
    IDirect3DTexture9* waterNoise_ = nullptr;   // tileable noise for the water's ripples
    double waterClock_ = 0.0;
    IDirect3DTexture9* LoadHdTileTexture(int tile);
    std::vector<TileBatch> batches_;
    // FIX-PERF-9: runs of 64 consecutive triangles of each batch's index range with their box (world space),
    // [0] for the classic range, [1] for the street range (TileBatch::streetIndices); per batch its first
    // chunk and chunk count in cullChunks_. Built once in UploadWorld.
    struct CullChunk { float cx, cy, cz, ex, ey, ez; uint32_t start, count; };
    std::vector<CullChunk> cullChunks_;
    std::vector<std::pair<uint32_t, uint32_t>> batchChunks_[2];
    bool worldViewCull_ = true;
    int worldCullLogEvery_ = -1;
    uint32_t worldCullFrames_ = 0;

    int width_ = 0;
    int height_ = 0;
    int deviceAttempts_ = 0;  // Initialize is retried until the device takes
    bool wireframe_ = false;
    DWORD cullMode_ = D3DCULL_CCW;
    size_t warmCursor_ = 0;   // next tile texture to upload ahead of use (WarmTileTextures)
    int hdTiles_ = 0;
    int hdDdsTiles_ = 0;
    int hdFailed_ = 0;
    bool hdFailLogged_ = false;
    RenderStats stats_;
    WorldShading shading_;
    Sky sky_;
    PostFx post_;
    WeatherFx weather_;   // rain streaks and the wet-road pass's puddles (weather_fx.h)
    WaterFx water_;   // the street views' water shader (water.h)
    std::vector<const TileBatch*> waterDeferred_;   // this frame's water batches for water_
    bool remixDevice_ = false;
};

}  // namespace gta2
