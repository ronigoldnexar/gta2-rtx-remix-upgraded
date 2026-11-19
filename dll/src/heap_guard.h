// FIX-HANG-1 diagnostics: see heap_guard.cpp. [devtools] bridge_guard_heap=1.
#pragma once

namespace gta2dx9 {
// Patches the Remix bridge's heap imports once its d3d9.dll is loaded (safe to call repeatedly until it has).
void BridgeGuardHeapInstall();
void BridgeGuardHeapReport();
}  // namespace gta2dx9
