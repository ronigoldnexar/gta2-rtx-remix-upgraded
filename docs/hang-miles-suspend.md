# The game-thread hang: Miles suspends the game thread inside the heap (19 Nov 2026, FIX-HANG-1)

Release blocker from 5090 QA r52 (`/mnt/gta2/qa5090/r52/soak2`, build 59f8cbd1): 45.3 minutes into the soak, 4 s after an F9
warp and boarding a car, the game thread stopped drawing for 5.4 minutes with the process alive and no device loss. The same
stack is in `qa5090/tdr/h2_rc_drizzle` (15:53), and the older Wine freezes (`remix-ste-start-game-thread-heap-deadlock-freeze`,
`docs/performance.md`, 17 logs in `out/`) are the same defect.

## What it is not

The first reading was "the game thread is inside our vectored handler (`gta2dx9+0x14DD60` -> msvcrt) waiting on the CRT heap".
That stack was read from the stall sampler's word scan, which lists every return-address-looking word on the stack, stale ones
included (`gta2dx9+0x14DD60` is a return into `Draw()`, `msvcrt+0x9E7E4` the return of an old `hypot`). The exact chain, the
`ebp` walk, is:

    game thread: RtlpAllocateHeap -> RtlAllocateHeap -> bridge malloc (d3d9.dll+0x97EFB) -> operator new -> CreateStateBlock
                 -> gta2dx9 WorldView::RenderFrame

No exception, no handler. (Symbols: `ntdll.pdb` from the symbol server, `d3d9.pdb` from `/mnt/gta2/qa5090/hang`, resolved with
`llvm-pdbutil dump --publics`.) The heap is not corrupt either: with the heap tail/free checks on (`GlobalFlag 0x70`) and a
`HeapValidate` of every heap every 1.5 s, 350+ passes over a 10-minute soak found nothing.

## What it is

The Miles Sound System (`mss32.dll`, the 1999 game's audio) runs a service thread (thread start `mss32+0x1520`, loop at
`mss32+0x155C`) that, 150-230 times a second, does `SuspendThread(game thread)` (`mss32+0x13D2`), runs its timer work (DirectSound
calls that allocate: `DSOUND+0x173E0` -> `ucrtbase` malloc -> `RtlAllocateHeap`) and `ResumeThread`s (`mss32+0x150F`). When the
suspension lands while the game thread is inside the process heap (the Remix bridge allocates from it on every D3D call), the
game thread stays suspended holding the heap's lock, the Miles thread waits for that lock for good, and every other thread that
allocates queues behind them. The `ntdll` pc of the "stuck" game thread is simply wherever it was suspended: `RtlpAllocateHeap+0x76f`
in r52 and h2 (the same address twice: it is a suspension, not a spin), `RtlCompareMemoryUlong` and `NtAllocateVirtualMemory`
in the repros.

How it was found (all on the 5090, `hang_report` below):
1. `[devtools] heap_lock_test=1` (a test thread takes the process heap lock for good) reproduced the symptom and showed that
   the old sampler thread blocks on that lock too (`GetPrivateProfileInt` allocates): the sampler cannot be the watchdog.
2. A watchdog on a thread that never touches the process heap wrote a report with `NtQueryInformationThread(ThreadSuspendCount)`:
   the game thread had **suspend count 1 for the whole stall**, nothing of ours suspended it (`stall_sampler=0`).
3. With the heap flags `GlobalFlag 0x70` (more time spent inside the heap, so the suspension lands there within a minute instead of
   once in two hours) the hang reproduced in under a minute. `NtSuspendThread`/`NtResumeThread` of the 32-bit `ntdll` hooked,
   recording thread and callers: 5906 suspend/resume pairs of the game thread by thread `mss32+0x1520` (callers
   `KERNELBASE!SuspendThread < mss32+0x13D2 < mss32+0x155C`), the last without its resume, and that thread blocked in
   `RtlAllocateHeap` called from `DSOUND+0x173E0`, queued on the process heap lock (`+0x260` in the heap header: count -10,
   recursion 1, **owner the game thread**). In r52 the thread list shows the same thread (`start mss32.dll+0x1520`, DSOUND frames,
   blocked in `RtlAllocateHeap`), and every Wine freeze log lists it too.

Why after a warp and boarding a car: new engine/horn/crash voices are created then, which is DirectSound work with allocations
inside the Miles timer thread's suspension window.

## What changed (`dll/src/crash_safe.cpp`, `compat.cpp`, `dllmain.cpp`)

1. **The cause, safe suspend** (`[devtools] mss_safe_suspend`, default 1). `NtSuspendThread` / `NtResumeThread` of this process are
   hooked. A suspension of the game thread whose caller is in `mss32.dll` is checked once it has really taken effect (a
   `GetThreadContext` on it returns only when it has stopped): if the game thread owns a heap lock, the loader lock or the PEB lock,
   is mid-release of a contended one (owner cleared, waiters pending), or is itself blocked waiting for a critical section / SRW lock
   (`NtWaitForAlertByThreadId`: when the lock is released the releasing thread wakes one waiter, and a woken thread that is suspended
   never takes the lock; this was the second way to the same deadlock, seen in the heavy repro), it is resumed at once, the Miles thread
   yields and tries again (up to ~3 s, then it behaves as before). With heap debugging on, about half of the Miles suspensions are
   retried; the first version of the check (owner only) left 1 deadlock per ~1.5 minutes in that repro, the final one none in 64 000
   suspensions of an 8-minute run.
2. **A backstop**: a game thread that a Miles suspension has held for over 400 ms (a timer tick takes microseconds) is resumed by the
   watchdog; the Miles thread's own `ResumeThread` later finds count 0 and does nothing. Logged as `HANG: BREAK: ...` with the Miles thread's
   chain and the critical sections on its stack. (It fires a few times in a heavy repro: locks other than heap/loader/PEB.)
3. **The watchdog** (goal 2): a thread of its own, no process-heap use (the sampler thread allocates through `GetPrivateProfileInt` and
   `Log` and is as stuck as the game thread). The game thread without a frame for `[devtools] hang_kill_ms` (6000, 0 = off) ends the
   process with a report: registers, the suspend count and history, 12 `eip` samples and its cycle counter (running or blocked), every
   heap's lock and owner (`+0x260`), every thread with name, start address, callers and the critical sections on its stack, the
   `NtSuspendThread` history, and a minidump (`gta2dx9_hang_<pid>.dmp`, `hang_dump=2` for a full one) from a helper process created
   suspended at start-up (creating a process allocates from the process heap, which is the lock a heap hang holds) and woken at the end.
   Not armed until 450 frames (start-up, the Remix attach alone takes up to 40 s); not while GTA2 is paused for a focus loss or
   minimised; a stall inside a kernel handle wait or Sleep while `NvRemixBridge.exe` uses CPU (a cold shader cache) gets
   `hang_busy_kill_ms` (60 s).
4. **Last words that cannot hang** (goal 2): unhandled exception, `std::terminate`, `abort`, pure call write `gta2dx9_fatal.log`
   (and the end of `gta2dx9.log`) from static buffers with `WriteFile` (no CRT heap, `Log`, locks), then `TerminateProcess`.
   `compat.cpp`'s guarded-fault frame moved from `thread_local` (GCC's emulated TLS takes a lock and mallocs on a thread's first
   access, inside a handler that runs for every exception of every thread) to a `TlsAlloc` slot, and its unguarded-fault lines use
   the same writer.

Diagnostics kept, off by default: `heap_check_ms` / `heap_check_abort` (HeapValidate of every heap, DbgPrint heap messages caught),
`bridge_guard_heap` (guard-page heap for the bridge's allocations; DLL-targeted page heap through IFEO `PageHeapTargetDlls` does
nothing on this Windows build, tested with a DLL that overflows a block), `stall_sampler=0`, `fatal_test=1`, `heap_lock_test=1`.

## Reading a report

`gta2dx9_fatal.log` / the end of `gta2dx9.log`: `HANG: game thread ... has drawn no frame for N ms (... why)`, `suspend count now`
(1 = something holds it suspended), `history` (suspend count and Mcycles each 500 ms), `NtSuspendThread calls ... by mss32.dll
(safe suspend ON: R retries ... B broken)`, `last mss32 SUSPEND/RESUME`, `process heap ... lock +0x260: ... owner thread N (HELD ...)`,
the thread lines with `| CS addr at module+off: owner T`. The once-a-minute `mss32 suspend guard (on): ...` line in `gta2dx9.log` has
the counters.
