// Guards over gta2.exe's own null-pointer crashes (FIX-CRASH-2, docs/stability.md).
#pragma once

namespace gta2dx9 {

// Detours the faulting sites once, at load, after checking their bytes.
void ExeGuardsInstall();
// Once a frame: logs when a guard has turned a crash into the game's own early exit.
void ExeGuardsUpdate();
// A developer warp (F9 door warp, F10 scene warp) just wrote the player's position. Test aid only
// (GTA2DX9_TEST_DEATH_AFTER_WARP_MS=<ms>, off by default): that long after the warp the player's ped is killed through
// the game's own death handler, as a car hit does, to run warp-then-die in a loop (docs/warp-crash.md).
void ExeGuardsNoteWarp();
// FIX-PERF-9: the object grid pools' growth on empty ([density] grid_pool_grow); blocks added so far
// (0: the 8-byte cell pool, 1: the 12-byte column pool); whether p is a node of an added block.
void ExeGuardsSetGridPoolGrow(bool on);
int ExeGuardsGridPoolGrown(int which);
bool ExeGuardsGridNode(const void* p, int which);

}  // namespace gta2dx9
