#pragma once
// DISTRICTS: per-district style rows at run time (tools/districts/styles.json, baked by tools/districts/dstyle.py
// into gta2dx9_districts\<lvl>.dstyle at stage time): which row each map cell belongs to, and per row a subtle grade
// for the street views (fog and ambient multipliers, eased as the camera crosses districts), multipliers on the
// street prop rules (live_geometry.cpp DrawProps) and Remix options pushed when the camera enters the district.
// No file (the default, or [districts] facade_kit=0): every row is the identity and nothing is pushed.
#include <cstdint>
#include <string>
#include "../../src/math3d.h"

namespace districts {

enum Prop { kFurniture = 0, kTrees, kMeters, kRoofProps, kContainers, kPropKinds };

bool LoadStyles(const std::string& path);   // false: no file or a bad one (then everything is the identity)
void ClearStyles();
bool StylesLoaded();
int RowAt(int mapX, int mapY);               // 0 = the default row
float PropScale(int mapX, int mapY, Prop p);
// A street prop rule's decision scaled by the cell's district: `base` is the rule's own outcome and `rate` its
// share (1 in 4: 0.25). A multiplier of 1 returns `base` unchanged (the same props as without districts); under 1
// keeps a stable subset of them, over 1 adds cells the rule did not pick, from a second hash of `h`.
bool Keep(int mapX, int mapY, Prop p, uint32_t h, bool base, float rate);
// Once a frame from the street views: eases the grade toward the eye cell's row (about 2 s) and pushes the row's
// Remix options when the row changes (street = false: the classic view, the default row's options).
void Update(float eyeX, float eyeZ, bool street, double now);
gta2::Vec3 FogScale();
gta2::Vec3 AmbientScale();
const char* RowName(int row);

}  // namespace districts
