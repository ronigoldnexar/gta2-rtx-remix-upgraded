# Stability: owner-box crashes, focus loss and the process's last words

FIX-STABILITY-1, 10 Nov 2026. Work orders: `owner-5090-minimize-fatal` (S0), `owner-5090-crash` (S1),
`owner-5090-daynight-too-fast` (S2), all from the owner's RTX 5090 Windows box.

## Reading a crash offset

Every build now links a map beside the DLL:

- Linux (mingw) build: `dll/build/gta2dx9.map`, staged as `stage/gta2dx9.map`, shipped in the linux
  release archive (`tools/pack_release.py`).
- Windows build (`dll\build.bat`): `build\gta2dx9.map` and `build\gta2dx9.pdb` (`/Zi /DEBUG /OPT:REF
  /OPT:ICF /MAP`); `package.bat` copies both.

A Windows event-log "Fault offset" or a log line `gta2dx9.dll+0xNNNN` is an RVA. In the mingw map the
addresses are image base (`0x712c0000` for the mingw builds so far: check `ImageBase` in the map's header)
plus RVA. Static functions are not in the map; `i686-w64-mingw32-nm -C --numeric-sort gta2dx9.dll` lists
them all (the DLL is not stripped). The mingw build is reproducible: the same commit and toolchain give the
same bytes apart from the PE timestamp and checksum, so a DLL with no map can be symbolised by rebuilding its
commit with `-Wl,-Map`. That is how the owner's 10 Nov DLL (6077518 bytes, timestamp 0x6AF2D78E, commit
8437686) was named.

Which build is it? The `guarded fault` lines in the log only come from the mingw build (compat.cpp's
vectored handler); an MSVC build's `__except` never logs them.

## What the owner's offsets were

| Offset (8437686 build) | Function | Meaning |
|---|---|---|
| `+0x381c50` | `__gnu_cxx::__verbose_terminate_handler()+0x78` (its call to `abort`) | a C++ exception nobody caught: `std::terminate` then `abort`, which gives 0x40000015 STATUS_FATAL_APP_EXIT with no dump. Not a deliberate fail-fast. |
| `+0x1CB6E5` | `synthetic_lights.cpp ReadDword()+0x55` from `Capture()` | the developer structure probe, which ran by itself 400 frames into every level and read through every field of 48 vehicles and particles that passed `PlausiblePointer` |
| `+0x11D348` | `live_geometry.cpp ActionProbes()+0xa18` | `wantedPed + kPedState` on a stale ped pointer the camera locator still held during a V move |

Why any exception is fatal in the mingw DLL: it unwinds with DWARF tables, and the unwinder stops at the first
frame that is not ours (gta2.exe calling `gbh_EndScene`, USER32 calling a window procedure). An exception that
leaves our code always ends in `std::terminate`, and libstdc++ writes its type to stderr, which a GUI process
does not have.

## What changed

- **Last words.** `InstallLastWords` (dllmain.cpp, at DLL attach) sets a `std::terminate` handler, a SIGABRT
  handler and an unhandled-exception filter (MSVC: a pure-call handler too, and no abort message box). Each
  writes one `FAULT:` line before the process ends: the exception's type and `what()`, the game window's state
  (iconic, visible, foreground), parked/active, the last window message to the game window and how long ago,
  device up or not, the frame number, then the call stack.
- **Entry points catch.** `gbh_BeginScene` and `gbh_EndScene` catch any C++ exception, log
  `FAULT: C++ exception out of gbh_EndScene (<type>: <what>) ... frame dropped, game goes on` (the first 5,
  then every 100th), close the scene and carry on.
- **Minimise path.** The game window's procedure (`ClosingWndProc`) feeds `WorldView::SetGameParked` and
  `SetGameActive`:
  - WM_SIZE SIZE_MINIMIZED parks: `RenderFrame` pumps our window's messages and returns, with no scene and no
    Present. There is no Reset and no teardown, and both windows stay. It unparks on SIZE_RESTORED or
    SIZE_MAXIMIZED, or on WM_SETFOCUS when the window is not iconic. It also unparks the first frame the
    window is found not iconic, in case no restore message comes.
  - WM_KILLFOCUS and WM_ACTIVATEAPP 0 take our `own_window=2` topmost window out of the topmost band, so what
    took the focus is not covered by a frozen frame. WM_SETFOCUS and WM_ACTIVATEAPP 1 put it back. The
    64-frame re-assert of topmost waits for the focus too. A click on our window while the game is away
    gives the game the foreground (restoring it), where before the click was refused.
  - The stall sampler does not suspend and walk the game thread while it is parked.
  - The focus and size lines are logged for the first 200 messages of each kind, not 12.
- **Structure probe.** It no longer runs by itself; the F4 menu's "Run structure probe" button still runs it.
  When it runs, it checks a child pointer against the page table before reading it, and stops after 32 guarded
  faults.
- **Stale ped.** `ActionProbes` checks the wanted ped's page before reading it.
- **follow_clock=auto.** `[sky] follow_clock=auto` is the shipped default and what a missing key means. It is
  0 until the RTX Remix API answers, then 1 (log: `sky: follow_clock=auto: RTX Remix runtime detected`).
  Plain GL keeps the fixed sun. 0 and 1 still force either.

## The freeze itself: GTA2's paused-while-minimised loop (FIX-STABILITY-2)

The operator proved on the 5090 that every freeze is GTA2's own loop and that restoring its window ends it.
In gta2.exe 9.6:

- The window procedure (0x4D0A00), on WM_KILLFOCUS (0x4D0B2B), in a fullscreen video mode (the mode record's
  bit 0 clear, which our video DLL reports as the original does), calls `Vid_CloseScreen` and
  `ShowWindow(game, SW_SHOWMINNOACTIVE)`. **GTA2 minimises itself.**
- On WM_SIZE (0x4D0BFC) it sets the byte at **0x673F50** to 2 for SIZE_MINIMIZED, and to 0 for SIZE_RESTORED
  or SIZE_MAXIMIZED.
- WinMain's loop (0x4D14FB..0x4D153D, the PeekMessage call at **gta2.exe+0xD150B**) goes on calling
  PeekMessage and dispatching for as long as that byte is 2 and no message is waiting. It draws no frame, and
  it spins one core at 100 percent.

Under own_window=2 the user sees our window, not GTA2's, so nothing ever restores GTA2's window and the loop
never returns. c7d3c7c5 parked our presenter, but the game stayed in its loop.

The fix (dllmain.cpp `ClosingWndProc`, own_window=2 only, `[renderer] keep_game_window_restored=1`, the default):

- **WM_SIZE SIZE_MINIMIZED is withheld from GTA2.** It never sees it, so its byte never becomes 2 and WinMain
  never enters the loop. The window is restored at once with `ShowWindow(SW_SHOWNOACTIVATE)`. That is a
  restore that does not take the focus back from the window the user switched to; SW_RESTORE would, and
  alt-tab would bounce. Then `SetWindowPos(HWND_BOTTOM)`, so the restored GTA2 window does not cover that
  other window. Our presenter is parked around the restore (c7d3c7c5) and unparked as soon as the window is
  not iconic, so the game keeps rendering behind the other window. Log:
  `focus: WM_SIZE SIZE_MINIMIZED withheld from GTA2` and
  `focus: game window kept un-minimised (...): iconic 1 -> 0 in N ms, gta2 minimised flag 0`.
- **WM_SYSCOMMAND SC_MINIMIZE is refused** (return 0). Log: `focus: WM_SYSCOMMAND SC_MINIMIZE refused`.
- **WM_ACTIVATEAPP 0 keeps rendering.** GTA2's procedure ignores it anyway; our presenter only leaves the topmost
  band.
- **A backstop on the stall sampler's thread, 4 times a second.** If the game window has been iconic, or
  GTA2's byte has been 2, for 500 ms, it calls `ShowWindowAsync(SW_SHOWNOACTIVATE)` and posts a WM_SIZE
  SIZE_RESTORED. Neither waits for the game thread. This is the operator's guard3.ps1 done from inside the
  process. Log: `stall sampler: game window minimised (iconic=1, gta2 minimised flag 2) for 500 ms: restoring it`.
- **The stall line says what it is.** A stall sample taken while the window is iconic or the byte is 2 carries
  `[game window minimised: iconic=1, gta2 minimised flag 2: GTA2's paused pump]` instead of a bare
  win32u address.

### Proof here (Wine does run GTA2's self-minimise)

`[devtools] simulate_focus_loss=5`, `simulate_focus_loss_restore=0`: no restore is sent at all, which is the
owner box. Each cycle logs the window's iconic state, GTA2's byte and the frames drawn over the next 2 s and 8 s.

| run | keep_game_window_restored | what the 5 cycles log | frames |
|---|---|---|---|
| fs2_ab_off_norestore | 0 (the old code) | iconic=1, gta2 minimised flag 2, frames 559 -> 559 for 50 s | shot_050 .. shot_120 byte-identical: frozen |
| fs2_keep_norestore2 | 1 | iconic 1 -> 0 in 5-43 ms, flag never 2, frames 282 -> 349, 353 -> 399, ... | in colour, hero walking, every frame different |
| fs2_rebased_keep (same, rebased on 3a3c5828) | 1 | iconic 1 -> 0 in 4-33 ms, flag never 2, frames 610 -> 777, 791 -> 995, ... | in colour, hero walking |

0 FAULT and 0 guarded faults in all three. vreg on the fix: spawn_classic 0 changed tiles (29 PASS; spawn_first FAIL
= the first-person fist pose of other commits, spawn_third WARN). The before/after is the owner's freeze reproduced and cured on one build.

## What GTA2 does on a focus loss (seen in the test run)

GTA2 stops calling frames while its window is minimised (it minimises itself on WM_KILLFOCUS; see above). Its
thread sits in its own message loop, which is the "game thread idle ... at win32u" the owner's log shows. Under
own_window=2 that is the freeze; FIX-STABILITY-2 keeps the window from staying minimised. On reactivation it restyles its
window (WM_STYLECHANGED twice, WM_SIZE) and goes on. It does not call `gbh_CloseScreen` on either.

## The test hook and its result

`[devtools] simulate_focus_loss=N` (documented in `package/gta2dx9.ini`): a thread sends the game window,
N times, WM_KILLFOCUS, WM_ACTIVATEAPP 0 and WM_SIZE SIZE_MINIMIZED, then 3 s later SIZE_RESTORED,
WM_ACTIVATEAPP 1 and WM_SETFOCUS. Wine never minimises the window, so this is the only way to drive the path
here.

Run `fixstab1_focus` (plain GL, third person, own_window=2, 02:00 at 10 tenths, 600 s, 5 cycles):

- every cycle logged park, then restore after 3005 ms, with the device kept;
- the frame log is continuous apart from the five 3.07 s gaps where the game paused itself;
- frames before, during and after each cycle are in colour, and the hero walks on afterwards;
- 0 `FAULT`, 0 guarded faults (log and the frame log's `guarded_faults` column), no
  "not disposed" line, over 8067 frames.

Not verifiable here: the owner box itself (real minimise, MSCTF, the Remix bridge on Windows). See "For the
5090 box" in the work orders.

## For the 5090 box (FIX-STABILITY-2; the owner box itself is untested from here)

Build: camera-modes at or after the FIX-STABILITY-2 "keep GTA2's window from staying minimised" commit.
gta2dx9.ini, in the first [renderer] block:

    [renderer]
    mode=takeover
    own_window=2
    keep_game_window_restored=1     ; the default; 0 brings the freeze back (A/B only)

Steps: reach the street, press V to third person and play for 30 s. Then alt-tab to the desktop, wait 10 s
and come back. Do that three times, then once more with Win+D and back. Leave the operator's guard3.ps1
running: it is the witness.

For each alt-tab, gta2dx9.log must show:

    focus: game window lost the focus (WM_KILLFOCUS); present window leaves the topmost band
    focus: game window minimised (WM_SIZE SIZE_MINIMIZED): presenting paused ...
    focus: WM_SIZE SIZE_MINIMIZED withheld from GTA2 (own_window=2: ...)
    focus: game window restored (WM_SIZE restored): presenting again after N ms ...
    focus: game window kept un-minimised (WM_SIZE SIZE_MINIMIZED): iconic 1 -> 0 in N ms, gta2 minimised flag 0 ...

For Win+D, either the same lines or `focus: WM_SYSCOMMAND SC_MINIMIZE refused`.

It must NOT show any of these:

- `stall sampler: game thread idle ... at win32u.dll+0x11AC`;
- `[game window minimised: ...GTA2's paused pump]`;
- a FAULT line.

guard3.ps1 must log no `RESTORED` line, and the CPU of gta2.exe must not sit at one full core while you are
away. If the backstop line `stall sampler: game window minimised ... restoring it` appears, the minimise came
by a path the window procedure did not see. Send the lines around it.
