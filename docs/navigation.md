# Navigation in the street views: how the camera and the controls work

GTA2 turns its pedestrian about-face in a few frames (the game's own heading
changes at 300-350 degrees a second). The first street-level camera followed
that heading one to one, so every turn whirled the whole picture: the thing
players called dizzying. The views are now built the way a modern engine builds
them, and the game's own movement is untouched: it still moves the pedestrian
and the cars, with its own speeds and collisions; only what is asked of it, and
what the camera does with the result, changed.

## One knob: `turn_speed`

Every rate below (the camera, the keyboard look, the mouse, the drawn figure)
is scaled by `turn_speed`, a percentage in `[camera]` of gta2dx9.ini and on
the F4 Camera tab. 100 is the console-style default; 50 halves them all.

## Third person on foot: a held orbit camera

- The camera does not follow where the player faces, and by default it does
  not turn while he walks either: he walks toward, away from or across the
  frame and the picture stays put. Only an explicit look input (the mouse)
  orbits it.
- A slow re-centre: once he has walked straight away from the camera (within
  30 degrees of its yaw) for `ThirdRecentreDelay` (2 s), the yaw eases round
  behind him on a critically damped spring with a 4 s time constant
  (`ThirdRecentreTau`), never faster than `ThirdRecentreRate` (30 degrees a
  second). Stopping or walking any other way cancels it.
- `orbit_follow=1` is the earlier behaviour: the camera drifts round behind
  whichever way he walks over `ThirdOrbitTau` (1.5 s), capped at
  `turn_rate_foot` (120 degrees a second).
- The drawn figure: the game snaps the player's heading in a few frames, so
  his model in the chase view turns under its own rule, no faster than
  `PedTurnRate` (240 degrees a second) with a 120 ms ease (`PedTurnEase`).
  The game's heading, movement and collisions are untouched; only the drawn
  yaw lags.
- Position: the eye moves with him and eases onto its spot (a spring over
  90 ms), with the wall, railing and prop clearances as before.

## Camera-relative controls (`nav_map=1`)

The arrows mean "walk that way as the camera sees it": Up toward where the
camera looks, Left and Right to its sides, Down back toward it, diagonals in
between. The renderer steers the pedestrian onto that heading through the
game's *own* turn and walk keys:

1. GTA2 reads its keyboard through DirectInput 8 as buffered events
   (`GetDeviceData` on the keyboard device). The renderer creates a keyboard
   device of its own from the same `dinput8.dll`, which shares the game's
   vtable, and patches `GetDeviceState`/`GetDeviceData` there. While a street
   view is up on foot the arrows' events are taken out of the buffer the game
   asked for (it never sees them), and the controller's own press and release
   events are put in. Nothing is sent to the system, no hook sits in the input
   chain, and every other key is untouched. (A `WH_KEYBOARD_LL` hook was tried
   first; under Wine the game's keyboard does not come through it.)
2. Once a frame the controller computes the wanted heading from the camera's
   yaw and the keys, compares it with the game's heading (predicted 100 ms
   ahead from the measured turn rate, `NavLatency`, because the game turns a
   pedestrian at 300-350 degrees a second and a held key overshoots), and
   presses the game's Left or Right in one-frame pulses while the error is
   outside a dead band (`NavDeadband`, 8 degrees), and Up while the error is
   under 100 degrees, so he arcs into a new direction rather than stopping to
   turn. Standing still with no key held, nothing is pressed.
3. In a car nothing is mapped: the game's driving keys are its own.

`nav_turn_sign=-1` mirrors the turn keys if a control scheme ever has them the
other way round; `nav_map=0` gives the arrows back to the game unchanged.

## First person

- On foot the view heading belongs to the player. Left and Right turn it on
  an acceleration ramp: 25 degrees a second the moment the key goes down
  (`FirstTurnKeyStart`), winding up to `first_turn_key_rate` (70) over 0.8 s
  (`FirstTurnKeyRamp`); on release the turn dies away over 0.15 s
  (`FirstTurnKeyDecay`). The mouse adds to it (sensitivity 0.5: an eighth of a
  turn across the window), and the pedestrian is steered to follow the view
  by the controller. What the game does with his heading (a bump, a stumble)
  never swings the picture; the controller brings him back.
- In a car the view is fixed to the car with a 120 ms ease (`FirstSmooth`) and
  a gentle lean toward where the car is going.
- Head bob is half what it was, lean and dip off, impact shake off, field of
  view 70 (60 in third person), the stretch at speed 4 degrees.

## Driving

- The chase camera's yaw is damped over `ThirdChaseTau` (0.8 s), aligned with
  the velocity when the car slides, capped at `turn_rate_car` (90 degrees a
  second); the chase distance scales with the car's roof height.

## Mouse over a remote session

A VNC or remote-desktop pointer is placed, not moved, so the warp-to-centre
scheme sees jumps. A frame's look is clamped to `MouseMaxStep` (25 counts) and
a jump eight times that is ignored as the pointer being parked. The browser
play container sets `mouse_look=0` (keys only) unless `PLAY_MOUSE=1`.

## Measuring it

`gamerun/novnc_capture.py <url> <out.mp4> <keys>` records what the browser
player sees: a headless Chromium (Playwright, in `~/.cache/pw-venv`) opens
the play page, the keys go through noVNC's own keyboard path, and the page is
recorded from the client side. `camera_feel_test.py` runs it as one of its
phases when the venv exists.

`gamerun/camera_feel_test.py <container> <vnc> <label>` drives a play
container through a real VNC connection (held keys: the game reads its
keyboard once a frame, a zero-length tap is missed on a loaded host), captures
each turn at 30 fps and copies the renderer log; with `GTA2DX9_LOG_CAMERA=1`
in the container the log carries every frame's camera yaw (`cam:` lines) and
the controller's state (`nav:` lines). `gamerun/camera_feel_rates.py` turns a
run into peak and mean turn rates, the largest per-frame step and the count of
frames over 4 degrees; `gamerun/camera_feel_sheet.py` makes the before/after
strips. Results are in `out/camera_feel_sheet.png` and the report that goes
with it. The play container needs `PLAY_DEVTOOLS=1` for the F9 warp the car
phases use.

Measured (run v11, 7 Nov 2026, keys over VNC, 30 fps captures): on foot no
frame moved the camera more than 3.1 degrees (third person, orbit peak
73 deg/s) or 3.0 degrees (first person, 90 deg/s while Left is held); at the
wheel 1.4 and 0.6 degrees. Before the rebuild the picture turned with the
pedestrian at about 340 degrees a second.

## Camera polish 2 (8 Nov 2026): long vehicles, the driver's eye, robustness

Code: `dll/src/view_modes.cpp/.h`; in `dll/src/car_bodies.cpp/.h` only the cabin the
first-person eye uses (and a new read-only `CarBodiesExtent`). Probe:
`linux/docker/camera_polish.py` (`keys_camera_polish.sh`, items in `CP_ITEMS`), run as
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 600 keys_camera_polish.sh -e GTA2DX9_LOG_CAMERA=1 -e GTA2DX9_LOG_VEHICLES=1 -e GTA2DX9_SCENE_NO_CAR=1`.
With `GTA2DX9_LOG_CAMERA=1` every `cam:` line now also carries the eye, the point
followed, the distance behind it and the wanted distance (`eye= at= back= x=`).
Sheet: `out/camera_polish_sheet.png` (local).

**What "the camera trails far behind the fire truck for the first seconds" was.** Not the
camera: after a devtools warp the game's own camera travels to the player at about ten
blocks a second, and until it arrives the game draws no car sprites at all, so there is
no 3D body to draw, the driven one included (runs `cp2_new7`/`cp2_new8`: zero cars for
14-21 s after a 150-190 block warp; the `a33_fire2` chase frames were taken in that
window). In play, without warps, it does not happen. The probe now waits
`distance / 8 + 3` seconds after each warp.

**Chase framing from the body (`CarBodiesExtent`).** The camera's distance, height, the
point looked at and the collision pivot follow the drawn body's length and full height:
`+0.5 x (length - 1.2)` and `+1.0 x (height - 0.45)` blocks of distance, `+0.8 x` the extra
height (and a tenth of the extra length) of height, the look point half the extra length
further ahead and half the extra height higher, the pivot just over the roof. A sedan
(about a block long, under 0.45 tall) gets nothing extra: its framing is byte for byte the
tuned one. The extras ease over 0.4 s, so a body that becomes known late never pops.
Fire truck (1.93 x 1.20 blocks): 4.6 blocks behind at rest instead of 6.1 with the old
roof factor, framed from the first frame at the wheel (`cp2_new11` `ft_drive_t_*`).

**The driver's eye from the model.** For a body taller than 0.45 or longer than 1.3
blocks, `car_bodies.cpp` reads the model's side profile once (the height of the middle
band in 32 slices): the hood is the run of slices from the nose within an eighth of the
height of the nose; the windscreen is where it ends; the cab roof is the highest point
within 0.35 block behind it; a flat front (bus, cab-over, train) puts the windscreen at the
nose and the deck at 0.55 of the cab. The eye is then placed exactly as before (0.62 of the
way from deck to roof, 0.12 behind the windscreen, 0.45 of the half width to the left).
Logged once per model as `car bodies: cab of model N ...` (fire truck: hood 0.48 long at
0.61, windscreen +0.48, cab roof 1.06; CARI's windscreen line put the eye inside the box
body behind the ladder before). Sedans keep the old rule (and the hood eye push).

**Robustness.**
- Walls behind the chase camera: the camera no longer goes through a wall that is nearer
  than its minimum distance (it used to: "never closer than a stride from a car"). It swings
  up over the player on an arc at the same distance, up to 75 degrees, to the first height
  that clears, eased (up in 0.15 s, down in 0.6 s); under a roof it stays in front of the
  wall. The eased eye is checked again against the pivot (no corner cut) and kept 0.1 block
  clear of any block, so the near plane never enters a wall. A pivot inside a wall's block
  (a car shoved against a building) moves up and toward the nose until it is in the open
  (`cp2_new8` showed the camera inside the van; `cp2_new9` `rev_t_*` looks over its roof).
- In or out of a car, thrown out: a 1.2 s blend in which the chase eye eases over up to
  0.44 s and may lag up to 6 blocks, and the pitch eases; in first person the eye keeps where
  it was shown and the difference dies away over 0.12 s (never through a wall).
- Down on the ground (ped state 8/9 for 0.8 s: knocked over, dead, arrested): the chase
  camera eases back and up over the body (2.8 behind, 2.3 up, turning 6 degrees a second); in
  first person the eye sinks to the road and the head tips 35 degrees onto its side.
- Lost (killed in a car that blew up, between the body and WASTED / BUSTED): for up to 6 s
  the camera holds a third of a second, then rises and draws back over the last spot
  (3.2 back, 2.8 up), turning slowly, instead of freezing inside the fireball (`cp2_new9`
  `exp_t_035..045` were white; `cp2_new11` `exp_t_010..035` show WASTED over the street).
  Found again far away (the hospital), it cuts, as the game does.

Devtools added (all `[devtools]`, re-read twice a second, -1 off): `set_car_damage=N` writes
the damage word of the car he drives (31995 and a knock blows it up; the word alone does not
set it alight), `set_player_health=N` his health word (ped+0x216).
`GTA2DX9_SCENE_MODELS="11,86,7"` makes the scene warp take the nearest driverless vehicle of
those models anywhere (with `GTA2DX9_SCENE_NO_CAR=0`) and log every one it saw.

Not verified in this pass: the hood-only cut from the driver's seat under RTX Remix (run
`cp2_remix1` path traced, but the scripted car was left before the first-person frames, so
only the on-foot eye was seen); a bus at the wheel (no bus stands parked in Downtown: the
scene-model warp found only truck cabs, model 63, framed in `cp2_mdl1`); the on-foot death
camera and the first-person down eye (three stars with health 3 brought no police within
50 s, `cp2_new11` `bust_*`); the tank and train cab at the wheel.
