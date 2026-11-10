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

## What GTA2 does on a focus loss (seen in the test run)

GTA2 stops calling frames while it is inactive. Its thread sits in its own message loop, which is the
"game thread idle ... at win32u" the owner's log shows, and it is normal. On reactivation it restyles its
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
