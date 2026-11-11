// Guards over gta2.exe's own null-pointer crashes (FIX-CRASH-2, docs/stability.md).
#pragma once

namespace gta2dx9 {

// Detours the faulting sites once, at load, after checking their bytes.
void ExeGuardsInstall();
// Once a frame: logs when a guard has turned a crash into the game's own early exit.
void ExeGuardsUpdate();
// FIX-PERF-9: the object grid pools' growth on empty ([density] grid_pool_grow); blocks added so far
// (0: the 8-byte cell pool, 1: the 12-byte column pool); whether p is a node of an added block.
void ExeGuardsSetGridPoolGrow(bool on);
int ExeGuardsGridPoolGrown(int which);
bool ExeGuardsGridNode(const void* p, int which);

}  // namespace gta2dx9
