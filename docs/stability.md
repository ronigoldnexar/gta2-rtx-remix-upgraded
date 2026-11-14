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

## The focus-loss pause that never ended (FIX-FOCUS-HANG, 5090 release blocker, 14 Nov)

**Symptom (5090, native Windows).** After our picture window got the focus (a script focusing it, then a click),
or after any alt-tab, popup or toast, the picture froze for good (GPU 0 %, audio on). Stack of the game thread:
`win32u < USER32 < gta2.exe+0xD150B < +0xD8681 < +0xD8511` (WinMain). It resumed only when GTA2's own small
window, normally hidden, was focused. On 13 Nov a 113 ms `WM_ACTIVATEAPP 0 -> 1` blip left it hung for 18.5 h.
FIX-STABILITY-2's log line "the game keeps running behind the window that took the focus" was wrong.

**Root cause (disassembly of gta2.exe).** The window procedure is at `0x4D0A00`; messages 2..8 go through the jump
table at `0x4D0E10`:

- `WM_KILLFOCUS` -> `0x4D0B2B`: input off (`0x4D09D0(0)`), then, if the video device's record has bit 0 clear
  (`0x4CB6F0`, our `Vid_FindDevice` record has flags 0 like the original), `Vid_CloseScreen`, **`mov byte
  [0x6735A5], 1`** (`0x4D0BA7`) and `ShowWindow(game, SW_SHOWMINNOACTIVE)`.
- `WM_SETFOCUS` -> `0x4D0A39`: input on, `0x4CC5C0` (sets the video mode again), **`mov byte [0x6735A5], 0`**
  (`0x4D0B0B`). The only other place that clears it is the top of a WinMain pass (`0x4CC6C1`).
- `WM_ACTIVATE` (`0x4D0BB9`) only acquires or releases input; `WM_ACTIVATEAPP` is not handled (DefWindowProc).
- WinMain's inner loop `0x4D14FB..0x4D1546`: `PeekMessageA(PM_REMOVE)` (returns to `0x4D150B` = gta2.exe+0xD150B),
  Translate, Dispatch, and back to `0x4D14FB` while `bl != 0` **or `[0x673F50] == 2`** (minimised, the case
  FIX-STABILITY-2 fixed) **or `[0x6735A5] != 0`**. No frame runs until then.

So the game waits for `WM_SETFOCUS` on its own window, not for the activation. Under `own_window=2` the picture is
our window; when it (via `SetForegroundWindow`, which ignores `WS_EX_NOACTIVATE`), nothing, or another program
ended up with the focus, nothing ever focused the game window again. Our own `active_` flag followed
`WM_ACTIVATEAPP 1`, so after a blip a click on the picture was refused too (`WM_MOUSEACTIVATE` only helped while
`active_` was false). On Wine the bug never showed: Wine hands the focus back to a window restored with
`SW_SHOWNOACTIVATE` (our un-minimise), so GTA2 got a `WM_SETFOCUS` within ~20 ms every time.

**Fix (message flow only, gta2.exe untouched; `[renderer] focus_watchdog=1`, default).**

- Policy: switching to another program pauses the game, as GTA2 always did (DirectInput is lost anyway); the moment
  the foreground is ours again it resumes.
- The present window never keeps the activation or the focus: on `WM_ACTIVATE` / `WM_SETFOCUS` it posts itself a
  message that runs `GiveGameForeground` (foreground plus `SetFocus` on the game window), so GTA2 runs its own
  `WM_ACTIVATE` + `WM_SETFOCUS` resume path (input re-acquired, video mode re-set).
- A click on the picture brings the game back while GTA2's flag is set, whatever our `active_` says.
- Watchdog on the stall sampler thread (4 Hz): flag set for 500 ms and the foreground is the game window or our
  picture window -> ask for the game focus (posted, runs inside GTA2's loop); still set a second later with the game
  window the foreground -> post the missed `WM_SETFOCUS`. Back-off up to 5 s. It never acts while the foreground is
  another program's or another window of ours (a dialog).
- Diagnostics: `focus: <msg> to GTA2: its paused flag a -> b` for every activation message; `focus: GTA2 paused
  itself` / `resumed after N ms`; stall stacks for the first 3 samples of every stall (session cap 600) with
  `[GTA2 paused for focus loss: ...]`; the misleading line now says GTA2 stays paused until it gets the focus back.

**Proof on Wine** (`[devtools] simulate_focus_loss_mode=3`: `WM_KILLFOCUS` with every `WM_SETFOCUS` dropped for
600 ms, which is what Windows does; private stage, own_window=2, 2 cycles):

| run | focus_watchdog | result |
|---|---|---|
| focus_m3_off | 0 | flag 1, frames 492 -> 492 for good; stall stack `user32 < gta2.exe+0xD150B < +0xD8681 < +0xD8511` = the 5090's; FAIL both cycles |
| focus_m3_on | 1 | watchdog asks at 501 ms, posts WM_SETFOCUS at 1001 ms, GTA2 resumed after 1252 / 1247 ms; frames 496 -> 642, then 30 fps; PASS both |

Mode 1 (our picture window made the foreground for real) hands the focus back in ~35 ms; Wine also recovers
without the fix there (see above).

**Native Windows (the 5090, 14 Nov):** `tools/focus_verify.ps1` (run in the interactive session with the game up;
`-Only` picks steps) passed all 9 steps; the negative control with `focus_watchdog=0` froze, as before the fix.

## The no-input AV at +0x140380: a car-paint worker reading freed memory (FIX-STABILITY-2)

The owner's night round died 80 s after launch, at clock 23:00, with no input, on a plain C0000005 at
gta2dx9.dll+0x140380. Disassembled in the owner's DLL (8437686, the same bytes as the maps in
/mnt/gta2/gta2-linux/symbols), that address is `CarJobThread()+0x5d0`, the car-paint worker thread, with
`MeasurePaintGain` inlined: `cmpb $0,(%edx,%edi,1)`, i.e. `skip[i]`, the door/dent footprint of the sprite.

The job held that footprint as a pointer into `g_deltaFootprint`. `SetCarDeltaArt` clears that map on the
game thread every time the world is uploaded (a level load: the attract demo's level, then the player's). A
paint job still measuring a car from the level before then reads freed memory.

Car-paint jobs only start under an RTX Remix runtime (`CarMaterialFor` needs the Remix API). That is why
only the 5090 saw it, with no input and no view switch.

The fix (live_geometry.cpp, the smallest hunk):

- the job owns a copy of the footprint, a few KB per sprite;
- `MeasurePaintGain` ignores a footprint whose size is not the sprite's, since the cache is keyed by sprite
  alone.

Verified here: plain run fs2_night_idle (22:50, clock 1 game minute/s, no input, 135 s) and Remix take
fs2_rmx_night (GPU 3, 22:50 with the clock running, car-paint jobs running, three street entries): 0 FAULT and
0 guarded faults in both. The race needs a level load during a paint job, so neither run is a deterministic
repro; the fix removes the shared pointer outright.

## The camera locator's stale ped (FIX-STABILITY-2)

`LocatedPlayerPed()` (view_modes.cpp) handed live_geometry, explosion_fx and ActionProbes the last ped the
locator had seen, even after its memory was gone. That was 0x4849D5B0 through a V move on the 5090: 168
guarded faults at +0x11D348, and the move stalled at 0.524. Now:

- `LocatedPlayerPed()` asks the page table (VirtualQuery, not `KnownReadable`'s cache) before handing the
  pointer out;
- `LocatePlayer` drops a remembered ped whose pages are gone, logs
  `view: the player's last ped ... is no longer mapped memory: dropped`, and empties the readable-region cache.

## gta2dx9_settings.ini no longer wins in silence (FIX-STABILITY-2, settings-ini-silently-overrides-gta2dx9-ini)

The F4 menu's Save file is read after gta2dx9.ini, and where the two overlap it wins. On the 5090 it held
StartHour=2, MinutesPerSecond=1.0, FpsCap, AlphaMode, Sprite* and the light gates, so values set in
gta2dx9.ini never ran. Now (settings.cpp):

- **Loud at load.** One line per value the file changes:
  `settings override: [lights] ConeSoftness ini=0.35000 settings=0.42000 (... wins; [renderer] ignore_saved_settings=1 skips it)`,
  then `settings: loaded ...: N value(s) differ from gta2dx9.ini`. The release's own settings file, as every
  scripted run here gets it, overrides 5 values: ConeSoftness, EngineVolumePercent, SpriteHeight, SpriteLift
  and HideStageArrow (run fs2_night_idle).
- **Save writes only what the menu changed.** A value equal to what gta2dx9.ini and the defaults give is left
  out, so it keeps following gta2dx9.ini on the next start. The log says how many values were written and
  how many were left to the ini.
- **An opt-out for tests.** `[renderer] ignore_saved_settings=1` does not read the file at all.

Save, the override lines and the rule all read one value list (`CurrentValues`), so they cannot disagree.

Note for QA here: every scripted run gets upstream-release/files/gta2dx9_settings.ini, which says
StartHour=2 and MinutesPerSecond=1. `[timeofday] start_hhmm` in a stage ini is overridden unless the run
sets `SETTINGS_SED` (grun.sh) as well. The override lines now show it in each run's log.

## d3d9.dll+0x941fe 0xc0000409: the RTX Remix runtime's fast-fail on entering the street view (for an upstream report)

This is not our code: it is the Remix runtime (Remix Plus 1.5.1 on the 5090) failing fast, through
`__fastfail` or a stack-cookie check, on the first street frame. What we submit at that moment, measured
under the Remix runtime here with the frame log (`GTA2DX9_FRAME_LOG=<path>`; take fs2_rmx_night, wil, 22:50,
the clock running, third person):

| frame | what | draws | primitives | created in that frame |
|---|---|---|---|---|
| 1635 | last classic-presentation frame of the move (V pressed) | 938 (world 878, sprites 33, ui 27) | 441 922 | - |
| 1636 | **first street frame** | 1334 (world 1260, props 12, peds 13, sprites 19, ui 30) | 526 931 | 18 textures (16 of them model textures), 20 vertex buffers, 16 index buffers, 27 texture uploads, 3 skinned figures |
| 1637-1640 | the next four | ~1320 | ~527 000 | 10 textures, 10-17 VBs and 10 IBs a frame |
| 1700 | settled street | 1635 (props 266, peds 47) | 740 617 | 2 textures |

The device is the same one classic used: no Reset, no new swap chain, the same present window and size
(own_window=2). What changes on that frame is a burst of resource creation (model textures and buffers,
skinned figure buffers) and about 400 more draws. A report upstream should carry:

- the Remix log of the crashing session (remix-logs);
- the frame log rows around the `view: presentation street` frame of our log;
- the RTX runtime version.

On the owner box: run with `GTA2DX9_FRAME_LOG=C:\gta2\frames.tsv` and send the rows around the frame number
of the last `view: presentation street` line, with the Remix log.

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

## Large-address-aware gta2.exe: the prepared install step (FIX-PERF-6; PROPOSED, the owner decides)

GTA2 9.6's gta2.exe has `Characteristics 0x010F`: no `IMAGE_FILE_LARGE_ADDRESS_AWARE` (0x0020). On 64-bit
Windows such a process gets 2 GB of address space; with the bit, 4 GB. The operator's 5090 measurement
(defect `LARGEADDRESSAWARE-one-bit-fixes-the-crash`): without the bit `largest_free=0.6MB` and a bad_alloc,
with it `largest_free=1767.8MB` and no FAULT on a long drive. Every run on the Linux host has always used a
marked copy (`linux/laa.sh` in the Wine prefix), so every number in `docs/performance.md` is a 4 GB process.

**The step, ready to ship but not shipped** (the release does not carry it until the owner says so):
`tools/laa/gta2dx9_laa.cpp`, built by `make laa-tool` into `linux/build/gta2dx9_laa.exe` (MinGW, static;
`cl /O2 gta2dx9_laa.cpp` builds it with Visual Studio). Dropped beside gta2.exe:

    gta2dx9_laa.exe status     says whether the bit is set (and whether the backup exists)
    gta2dx9_laa.exe on         copies gta2.exe to gta2.exe.no-laa (once; never overwritten), then sets the bit
    gta2dx9_laa.exe off        puts gta2.exe.no-laa back (uninstall); without a backup it clears the bit

One byte is written (offset 0x11E in 9.6: 0x0F -> 0x2F); the PE checksum is left alone (Windows does not
check it for an executable). Checked here under Wine on a copy of the game's exe: `on` gives a file
byte-identical to `tools/set_laa.py`'s output (which is byte-identical to `laa.sh`'s), `on` twice writes
nothing, `off` gives back a file byte-identical to the original.

**To ship it** (owner's call): add `copy /y linux\build\gta2dx9_laa.exe "%OUT%\"` (or the MSVC build) to
`package.bat` and `"gta2dx9_laa.exe"` to `STAGE_FILES` in `tools/pack_release.py`, and the two lines
"Installing: 3. run `gta2dx9_laa.exe on`" / "Uninstalling: run `gta2dx9_laa.exe off`" to
`package/gta2dx9_README.txt`. The Linux runner already does the same in the prefix.

**Risks and what was checked:**
- A game or DLL that keeps flags in a pointer's high bit breaks above 2 GB. The DLL was made LAA-safe on
  9 Nov (7b36ca7: `PlausiblePointer` accepts the large-address-aware range); gta2.exe itself has run marked
  in every scripted run on this host since the first Linux port, through 20-minute soaks with VmSize up to
  3.4 GB (FIX-PERF-4 `fp4_sw_fix1`) and pools landing above 2 GB (the `player-not-found` blocker, fixed).
- Not tested here: Windows itself, and the RTX Remix launcher (NvRemixLauncher32) on Windows starting a
  marked exe. The Remix bridge under Wine runs the marked exe in every Remix run here.
- Steam/GOG copies of GTA2 are not 9.6; the tool refuses anything that is not a 32-bit x86 PE but does
  not check the version: run `status` first.

**For the 5090 box:** `gta2dx9_laa.exe on` in the game folder (or `python tools\set_laa.py` as in
docs/performance.md FIX-PERF-5), play 10 minutes, send the `mem: minute` lines: `free=` near 2 GB higher,
`largest_free` in the hundreds of MB. `gta2dx9_laa.exe off` undoes it.

## The flamethrower fired while boarding: gta2.exe's flame emitter loses its shooter (FIX-CRASH-2)

Work order `qaf57-third-first-flamethrower-fired-while-re-boarding-own-car-crashes-gta2-exe-c0000005-at-0x35C2A`.
With the flamethrower, press Return beside a car and hold fire while the entry animation runs (ped state 3
sub 6): `FAULT: code C0000005 at 00435C2A (gta2.exe+0x35C2A), reading 00000098`, ecx 0, and the Wine crash
dialog. **The game crashes in classic too** (same sequence, no V press, same address): it is gta2.exe's own bug,
not a renderer one. No stack word lies inside gta2dx9.dll; none of our hooks is on the path.

**What faults.** A flamethrower's flame is an emitter object that the particle update's switch
(FUN_00490760) hands to FUN_00490130 every frame. For an emitter fired by a pedestrian it takes the owner
object at `[emitter+0x28]+8`, the ped at `[object+0x7C]`, checks them, then at 0x4902D6 calls FUN_00435C20
(`*out = [[ped+0x168]+0x98], [..+0x9C]`: where the ped's object stands). While the ped climbs into the car,
`ped+0x168` is already null, and FUN_00435C20 reads 0x98. The molotov has no emitter, so it never gets there.

**The fix** (`dll/src/exe_guards.cpp`, installed at `gbh_InitDLL` in every mode, before the proxy/takeover
split): 18 bytes at 0x4902D6 are checked against this build (`mov ecx,[ebp+0x7C]; lea edx,[esp+0x50]; push
edx; call 0x435C20; jmp 0x490403`). The first 13 become a jump to a thunk that does the same when the ped and
his object are there, and otherwise takes FUN_00490130's own exit at 0x49074E (al=1, the emitter ends): the exit
its earlier checks already take for a missing owner object or ped. Log lines: `patch: flame emitter owner guard
... at 004902D6 applied` (or `bytes differ, not applied` on another exe build) once, and `guard: flame emitter
whose ped has no object (boarding) ended instead of crashing (N so far)` on the frame it fires. Nothing else in
the game changes: a flame whose shooter is there runs the same instructions as before. On the frame it fires the
flame stops, and he finishes boarding.

**Verified** (wil kerb, plain GL, filer's runner `gamerun/qaf57_a.py` and its weapon-parametrised copy
`gamerun/xc2_a.py` with `XC2_WPN`): the unmodified e169092e stage crashes in third and in classic. On the fix,
three seated flamethrower runs in third/first give 0 FAULT lines, the guard fires on the boarding frame (5-20
emitters ended there) and he is seated in the car after the boarding burst (frames opened: the cab view
with the wheel, flamethrower HUD, the game running). Classic on the fix: same, 0 faults, guard fired, seated,
no crash dialog. The pistol through the same sequence: 0 faults, seated (the guard does not fire: a pistol has no
emitter). The rebased build (on f4b1dea1) re-run twice: 0 faults, the guard fired, seated. `tools/vreg/vreg.sh stage`:
`spawn_classic` PASS, 0 tiles changed (the 3D shots differ from the b89b95a goldens only in the HUD tiles, the
newer game-font HUD and round minimap). A 300 s plain `long` run: 0 FAULT, 0 `guard:`, 0 `guarded fault` lines.

**Untested:** the machine gun and rocket launcher variants (both runs died or were busted before the boarding
step: inconclusive, 0 faults); the Windows build (the thunk has an MSVC `__asm` twin that was never compiled
here); whether anything in gta2.exe besides this emitter reads `ped+0x168` unchecked during boarding (none
seen in 8 runs). Seating through the scripted F10 scene car fails about 1 run in 3 (`MARK never seated`).
