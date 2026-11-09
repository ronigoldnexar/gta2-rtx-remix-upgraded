# Positional sound in the street views (quality bar row 13)

## The defect

GTA2 places every world sound (engines, gunfire, sirens, explosions, footsteps, ambient loops) through
one routine of its sound manager, `0x4168E0`: the source's position minus the listener's (the top-down
camera, at `this+0x1468/0x146C/0x1470`), in the game's fixed point (1 block = 2^14). Its two callers are
the start of a sound (`0x417A89`) and the per-frame update of a playing one (`0x4177F0`). After it:

- the 2D mixer (the default; `do_3d_sound` unset) sets the Miles pan from the offset's x alone
  (`0x416E50`, pan 10..117 around 63, dead zone near 0);
- the Miles 3D path (`do_3d_sound=1`, "Microsoft DirectSound3D hardware support") sets the voice at
  `(x, 0, -y)` and never turns the listener (`AIL_set_3D_orientation` is not even imported).

Both mean "east is right, north is ahead", which is what the screen shows from above. In the chase and
first-person views that is wrong whenever the camera does not look north: facing south, everything on
the left was heard on the right; a car behind the camera sounded as if it were on screen.

## The fix (`dll/src/audio3d.cpp`)

Both `call 0x4168E0` sites are pointed at `OffsetHook` (same register and stack contract as the game's
`__thiscall`). It runs the game's routine, then, only when a street view is active:

1. measures the offset from the player instead of the game's listener (the top-down camera leads a fast
   car by a few blocks); it falls back to the game's listener if the two are more than 12 blocks apart;
2. turns the offset into the camera's frame: `right = x cos(yaw) + y sin(yaw)`,
   `ahead = x sin(yaw) - y cos(yaw)` (yaw 0 looks north = game -y), and hands the game
   `(right, -ahead, z)`.

The game's own volume, distance fall-off, pitch, Doppler and the engine-volume and radio patches in
`voice_over.cpp` are untouched; both mixers (2D pan, Miles 3D) take the turned offset. The classic view
is left byte-for-byte as the game had it (the hook returns the game's result unchanged).

`gta2dx9.ini [audio]`: `positional=1` (default; 0 = the game's panning), `listener=player|game`,
`log_every=N` (one `audio3d:` line every N positioned sounds; with `positional=0` the hook is still
installed when a log is asked for, and only logs, which is the baseline for the probe).

## Verification (9 Nov 2026, Downtown start, 2D mixer, Wine + PulseAudio null sink)

Headless probe in the style of PLAY-AUDIO's `play_audio_probe.py`: the keys script records the null
sink's monitor with `parec` while the game runs, and `linux/docker/audio3d_probe.py` compares the
recording's stereo balance `(R-L)/(R+L)` per 0.5 s with a prediction from the logged sources (nearer
sources weigh more): once from the camera-frame offset, once from the game's top-down offset.

Controlled test, `gamerun/keys_qb13_spin.sh` (copy in `linux/docker/`): stand still at the start, where
a looped ambient source sits about 7 blocks west, switch to a street view (V twice; the log reports first person) and turn in place in 16 steps,
holding each heading 2.5 s.

| Run | `positional` | yaw range | measured balance | corr(measured, camera frame) | corr(measured, top-down) |
|---|---|---|---|---|---|
| `qb13_spin1` | 1 | -178..179 | -0.32..+0.33, follows the heading | **+0.68** | +0.06 |
| `qb13_spin0` | 0 | -178..178 | -0.28..+0.11; the loud source always left | +0.09 (same as top-down) | +0.09 |

The loudest quarter of the windows is the looped source: with `positional=1` it is heard left in 9,
right in 9 and centred in 4 of 22 windows (balance -0.32..+0.33); with `positional=0` left in all 22
(-0.28..-0.23), whichever way the view faces. In `qb13_spin1` the balance flips with the heading: facing north-east (yaw 3..78) the source is on the
left (-0.28..-0.32), facing south-west (yaw -105..-168) on the right (+0.28..+0.33). 56 % of the sounds
that sat clearly to one side were on the opposite side in the game's own top-down pan.

Walking run, `gamerun/keys_qb13_audio.sh` (`qb13_a1`, classic then third person): 289 sounds positioned,
yaw -179..180, the player listener never rejected (`far=0`), no faults (0 `FAULT` lines in all three runs). Its stereo correlation was
inconclusive (-0.02 vs -0.02): on the move the mix is dominated by the player's own footsteps, at the
listener.

Not verified: the Miles 3D path (`do_3d_sound=1`; the same offset feeds it, so it should follow, but no
run used it); a car at speed in the chase view; Remix runs (audio is renderer-independent); a Windows
machine with a real sound card.

## Open (rest of row 13)

- Front/back: a stereo pan cannot tell ahead from behind. A rear cue (a few dB down or a low-pass for
  sources behind the camera) needs the volume path (`0x4B6110` callers, already wrapped by the engine
  volume patch in `voice_over.cpp`) or a DirectSound proxy with per-buffer filters.
- Occlusion and reverb, footstep/door/cloth foley for the new animations.

Run the probe: `python3 linux/docker/audio3d_probe.py out/<run> --phase spin --table`.
