#pragma once
// The visual regression harness's fixed camera (QA-REGRESSION, docs/visual-regression.md).
namespace gta2 { class Camera; }

// With GTA2DX9_REGRESS_CAM=<file> in the environment, the file is re-read a few
// times a second. While it holds
//     cam <eye x> <eye y> <eye z> <target x> <target y> <target z> [fov degrees]
// in game coordinates (x east, y south, z the level, in blocks), the street
// views draw from that eye looking at that target instead of their own
// camera. Anything else ("off", empty, no file) leaves the views' camera
// alone. Returns true when it replaced the camera this frame. Without the
// environment variable it costs one branch a frame.
namespace gta2dx9 {
bool RegressCameraOverride(gta2::Camera* camera);

// The sky's and the water's clock (seconds of the performance counter): with
// GTA2DX9_REGRESS_CAM set, a fixed 1000 s, so clouds and ripples sit in the same place
// on every regression run (they otherwise follow the host's uptime); else unchanged.
double RegressClock(double seconds);
}  // namespace gta2dx9
