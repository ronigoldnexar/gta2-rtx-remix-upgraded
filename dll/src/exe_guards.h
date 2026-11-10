// Guards over gta2.exe's own null-pointer crashes (FIX-CRASH-2, docs/stability.md).
#pragma once

namespace gta2dx9 {

// Detours the faulting sites once, at load, after checking their bytes.
void ExeGuardsInstall();
// Once a frame: logs when a guard has turned a crash into the game's own early exit.
void ExeGuardsUpdate();

}  // namespace gta2dx9
