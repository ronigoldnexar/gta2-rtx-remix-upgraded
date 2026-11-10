// FIX-DEADLOCK-1: what every thread of the process is doing when the game thread stays stuck.
// See thread_watch.cpp.
#pragma once
#include <cstdint>

namespace gta2dx9 {

// Gives the calling thread a name for the stall dump (a literal: the pointer is kept).
// Cheap, no allocation; 32 long-lived names (later ones are ignored) and a ring of 32 for
// threads that live for one job (shortLived).
void NameThisThread(const char* name, bool shortLived = false);

// Called by the GTA2_TRY vectored handler (compat.cpp) when it swallows a fault: kept in a
// small ring (no allocation, no lock) and written out by the next stall dump. A fault taken
// inside system code (ntdll, msvcrt) while a lock of it is held leaves that lock held for good.
void NoteGuardedFault(uint32_t code, uintptr_t at, uintptr_t reading);

// The sampler's one-shot dump when the game thread has been stuck at the same place for
// seconds: the owner of the critical section it waits on (found on its stack), every thread
// of the process with its name, start address and stack (each suspended only while its
// registers and stack words are copied into static memory; nothing is allocated or logged
// while another thread is held), and the guarded faults swallowed so far.
// gameStack/gameWords: the game thread's stack words the sampler already copied.
void DumpAllThreads(uint32_t gameThread, const uintptr_t* gameStack, int gameWords);

// [devtools] stall_dump_test=1 (re-read by the sampler once a second; off by default): a test
// thread takes a critical section and keeps it 10 s, and the game thread enters it at its next
// frame, so the game thread stalls in a lock wait and the dump has to name the test thread as
// the owner.
void StallDumpTestPoll();
// The game thread's side of the test (gbh_BeginScene).
void StallDumpTestFrame();
// Sampler thread, every pass: one line per fault a GTA2_TRY swallowed since the last pass
// (thread, module+offset), at most 200 a session.
void GuardedFaultsReport();

}  // namespace gta2dx9
