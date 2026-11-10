// FIX-PERF-4: where the process's memory goes, and a loud, survivable allocation failure.
//
// gta2.exe is a 32-bit (large-address-aware) process that lives near its address-space
// ceiling. This module
//  - counts every C++ allocation the DLL makes (operator new/delete are replaced in
//    mem_stats.cpp: live bytes, live blocks, peak), cheap enough to stay on always;
//  - surveys the address space (VirtualQuery: committed private/mapped/image, reserved,
//    free and the largest free block, which is what a big allocation needs) and reads the
//    process's own VmSize/VmRSS from /proc/self/status under Wine;
//  - asks the modules for their cache sizes (entries, and bytes where they are known), and
//    logs it all as `mem:` lines: once a minute, at each view change (short form) and on demand;
//  - on an allocation failure releases an emergency reserve, logs a FAULT line with the
//    counters, and sets MemoryEmergency(): the view is dropped to classic and held there,
//    instead of std::bad_alloc terminating the process with no message.
// Env: GTA2DX9_MEM_LOG=0 turns the periodic and per-view lines off (the FAULT path stays).
#pragma once

#include <cstddef>

namespace gta2dx9 {

// The DLL's C++ heap (operator new) as counted since load.
struct HeapCounters {
    long long liveBytes, liveBlocks, peakBytes, totalAllocs;
};
HeapCounters HeapCountersNow();

// A module reports one cache: entries and (when known, else < 0) bytes.
void MemGauge(const char* name, double entries, double bytes = -1.0);

// Logs a `mem:` line. full 0: the heap counters; 1: also the address-space survey and
// /proc status (any thread); 2: also every module's gauges (render thread only).
void MemStatsLog(const char* why, int full);
// Called once a frame from the render thread: the per-minute line, the emergency check.
void MemStatsTick();
// A view change was made (short line, plus a full one every 32 changes).
void MemStatsViewChange(int fromMode, int toMode);

// Set (and logged as a FAULT) once an allocation has failed; the view is held at classic.
bool MemoryEmergency();
// Arms the emergency reserve; called once at DLL start.
void MemStatsInit();

// Per-module gauge reporters (each defined in its module, called by MemStatsLog(full)).
void ModelStoreMemGauges();
void CarBodiesMemGauges();
void TextureStoreMemGauges();
void LiveGeometryMemGauges();
void RagdollMemGauges();
void VehicleFxMemGauges();
void CarGlassMemGauges();
void MapObjectsMemGauges();

}  // namespace gta2dx9
