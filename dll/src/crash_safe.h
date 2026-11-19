// FIX-HANG-1: last words that cannot hang, a stall watchdog, and the fix of the hang itself. See docs/hang-miles-suspend.md.
//
// The 5090 release blocker (QA r52: the game thread without a frame for 5.4 minutes, process alive; the same stack in
// tdr/h2_rc_drizzle and in the old Wine freezes) was first read as "the game thread is inside our vectored handler waiting on
// the CRT heap". The stack words that reading came from are stale ones. The cause is mss32.dll's (Miles Sound System) service
// thread, which suspends the game thread about 200 times a second: when that lands inside the process heap the game thread keeps
// the heap's lock while suspended and the Miles thread, which then allocates, waits for it for ever. This file:
//   1. hooks NtSuspendThread/NtResumeThread: a Miles suspension of the game thread is made safe (not while the game thread owns
//      a heap, loader or PEB lock) and a suspension that outlasts 400 ms is broken from the watchdog;
//   2. a watchdog on a thread that never touches the process heap ends the process with a report when the game thread draws no
//      frame for hang_kill_ms, for whatever reason;
//   3. a fatal fault, std::terminate or abort ends the process with a report too. Everything that runs at such a time uses no
//      CRT heap, no malloc, no stdio, no C++ runtime and no lock another thread could hold: static buffers, our own number
//      formatting, WriteFile on handles opened up front, a minidump helper process created (suspended) at start-up.
// The report goes to gta2dx9_fatal.log beside the game and to the end of gta2dx9.log through the log's own OS handle.
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

// One line for the log (Log(), so not from a handler): how often the Miles thread suspended the game thread, how many of those
// suspensions were retried because the game thread held a heap/loader/PEB lock, how many gave up, how many the watchdog broke.
void LogSuspendCounters();

// DbgPrint text from the heap manager ("HEAP[gta2.exe]: Heap block at ... modified at ... past requested size of ...")
// arrives as a DBG_PRINTEXCEPTION_C exception; the vectored handler hands it here (the first 60 are written).
void NoteDebugString(EXCEPTION_POINTERS* info);

}  // namespace crash
}  // namespace gta2dx9
