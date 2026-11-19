// FIX-HANG-1: last words that cannot hang.
//
// The 5090 release blocker (QA r52, a game-thread freeze of 5.4 minutes with the process alive, and the same stack
// in tdr/h2_rc_drizzle) was read at first as "the game thread is inside our exception handler, waiting on the CRT
// heap". The stack words the sampler logs are not a call chain; the live part of it was the game thread inside
// ntdll's RtlpAllocateHeap, in the free-list walk, with the other threads queued on the process heap's lock (see
// docs/hang-heap.md). Two things follow:
//   1. whatever the cause, a fatal fault and a stuck game thread must end the process with a log line, never a
//      frozen window. Every function here runs with no CRT heap, no malloc, no stdio, no C++ runtime and no lock
//      another thread could hold: static buffers, our own number formatting, WriteFile on handles opened up front.
//   2. the vectored handler (compat.cpp) ran for every exception of every thread; it must not allocate either
//      (GCC's emulated thread_local mallocs on a thread's first access).
//
// The report goes to gta2dx9_fatal.log beside the game (opened up front, appended) and to the end of gta2dx9.log
// through the log's own OS handle.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace gta2dx9 {
namespace crash {

// Opens the fatal log, reads [devtools] hang_kill_ms / hang_busy_kill_ms / hang_dump from gta2dx9.ini, resolves what
// the report needs. Once the main log is open (after OpenLog). Allocates; call it early, never from a handler.
void Init();

// The game thread's id and the tick-count heartbeat it writes at every frame (dllmain.cpp g_beat), for the header.
void SetGameThread(DWORD tid, volatile DWORD* beat);

// Vectored handler, first-chance access violation nobody guards: the first few written as FAULT lines.
void LogUnguardedFault(EXCEPTION_POINTERS* info);

// An unhandled exception (or terminate / abort: info may be null, why says which). Writes the report and ends the
// process with TerminateProcess; does not return.
void FatalException(const char* why, EXCEPTION_POINTERS* info);

// The game thread has not drawn a frame for idleMs: writes the hang report (registers, repeated samples of the thread,
// the heap locks and their owners, every thread's top of stack), asks for a minidump from a helper process, then
// ends the process. Does not return. gameThread: a handle with suspend/resume/get-context/query rights.
void HangExit(HANDLE gameThread, DWORD idleMs, const char* why);

// The stall watchdog: a thread of its own that never touches the process heap (the sampler thread does, through
// GetPrivateProfileInt and Log, and is as stuck as the game thread in a heap hang). Ends the process with HangExit when
// the heartbeat set by SetGameThread is hang_kill_ms old and byDesign() (a plain function: GTA2 paused for a focus loss,
// minimised ...) is false.
// frames/armAfterFrames: the watchdog is idle until *frames has reached armAfterFrames (the game's frame counter): start-up,
// Remix attach and the first level load are slow by nature and are not watched.
void StartWatchdog(bool (*byDesign)(), volatile LONG* frames, LONG armAfterFrames);
// Stops the watchdog and the unused minidump helper (DLL_PROCESS_DETACH).
void Shutdown();

// [devtools] hang_kill_ms: the stall limit in ms (default 6000, 0 = never end the game for a stall).
DWORD HangKillMs();
// [devtools] hang_busy_kill_ms: the longest a stall may last while the Remix server process is busy (a cold shader cache
// compiles for a long time with the client waiting). Default 60000.
DWORD HangBusyKillMs();

// Sampler thread, while the game is healthy: remembers the Remix server's process id for ServerBusy.
void RefreshServerPid();
// True when the Remix server's CPU time advanced by at least 100 ms over 500 ms (sleeps 500 ms).
bool ServerBusy();

// DbgPrint text from the heap manager ("HEAP[gta2.exe]: Heap block at ... modified at ... past requested size of ...")
// arrives as a DBG_PRINTEXCEPTION_C exception; the vectored handler hands it here (the first 60 are written).
void NoteDebugString(EXCEPTION_POINTERS* info);

}  // namespace crash
}  // namespace gta2dx9
