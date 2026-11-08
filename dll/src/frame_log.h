// Per-frame timing log for frame-pacing work (off unless GTA2DX9_FRAME_LOG names a
// file, e.g. GTA2DX9_FRAME_LOG=Z:\out\frames.tsv). One tab-separated line per
// rendered frame: the renderer's phases in ms, the draw calls and the resource
// creations/uploads of that frame, and the player's position. With the log off
// nothing is hooked and every call here is a test of one flag.
#pragma once

#include <cstdint>

namespace gta2dx9 {

// What a module reports into the current frame's line.
enum FrameCounter {
    kFcModelTexture = 0,   // a model texture read and created (model_store TextureFor)
    kFcModelBuffers,       // a mesh's managed vertex/index buffers created
    kFcNewPose,            // a skinned pose computed (not found in the pose cache)
    kFcSkinBuffer,         // a per-pose dynamic vertex buffer created
    kFcCarBody,            // a car body/atlas built (car_bodies)
    kFcGuardedFault,       // a fault caught by a GTA2_TRY guard (compat.cpp): a slow path under Wine
    kFcCount
};

bool FrameLogEnabled();
// The game's side of the frame: gbh_BeginScene stamps the start of its draw stream, and
// the draw exports add their own time (a scope at their top) so "game" splits into the
// game's simulation, its draw stream, and our code inside that stream.
extern int g_frameLogActive;
long long FrameLogNow();
void FrameLogMarkBeginScene();
void FrameLogAddHook(long long start);
struct FrameLogHookScope {
    long long t0 = 0;
    bool counted = false;
    FrameLogHookScope();
    ~FrameLogHookScope();
};
// Hooks the device's draw/create entries for counting (once per device; log on only).
void FrameLogAttachDevice(void* device);
void FrameLogNote(FrameCounter counter, int n = 1);

// The frame's phase times (ms) and context, written as one line by FrameLogEndFrame.
struct FrameLogRecord {
    double whole, game, pre, lights, sky, world, sprites[9], ui, lightsDraw, present, wait;
    double preParts[6];   // load, animtiles, input, camera, menu, timeofday
    int modelDraws, skinned;
    double posing, fills;
    int carMeasured, carBuilt;
    int view;          // 0 classic, 1 third, 2 first
    int driving;
    float px, py, pz;  // the player, game frame (blocks)
    float cx, cy, cz;  // the camera eye, renderer frame
    int spriteQuads;
    long long entryQpc;
    double solver;        // the camera solver, part of pre_camera
    double camLocate, camProbes;   // the player locator; the state lines and probes (pre_camera)   // RenderFrame's entry (QueryPerformanceCounter)
};
void FrameLogEndFrame(uint32_t frame, const FrameLogRecord& r);

}  // namespace gta2dx9
