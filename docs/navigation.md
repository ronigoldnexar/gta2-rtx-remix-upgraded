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

## Third person on foot: an orbit camera that follows softly

- The camera never turns with the game's heading frame by frame. Since
  CAMERA-FEEL-3 (8 Nov 2026) it follows the way he walks, softly, as GTA V's
  does: see "Soft follow on foot" below. Standing still with no key held it
  holds its yaw; the mouse orbits it.
- With the follow off (`follow_tau_walk=0`), the earlier held orbit: he walks
  toward, away from or across the frame and the picture stays put, with a slow
  re-centre: once he has walked straight away from the camera (within
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

## Soft follow on foot

What players said of the held orbit: turning the character left the camera
looking the old way, so he walked sideways across the frame. Now, as in GTA V:

- **While he walks**, the camera's yaw eases round behind the way he is going
  (his smoothed velocity) on the same critically damped spring as the other
  cameras (`SpringTurn`, no overshoot), with a time constant of
  `follow_tau_walk` (1.5 s) at a walk and `follow_tau_run` (1.0 s) at a run
  (blended by speed between 0.8 and 2.6 blocks a second; GTA2's player runs at
  about 2.6), never faster than `turn_rate_foot` (120 degrees a second). The
  per-frame cap on the shown yaw and the step-locked camera (one game step per
  frame with the frame limiter, PERF-2) are unchanged.
- **Each turn waits `follow_delay` (0.4 s)** before the camera starts after it
  (a step or a tap does not stir the picture), then the swing starts from rest.
- **Standing**, a turn key turns him (the controller presses the game's turn
  key; he takes a step as he turns) and the camera follows his new facing after
  the same delay, finishing the turn after the key is let go. With no key held
  it holds: a bump or a shove never swings it. A follow under way when he stops
  dies away over 0.2 s instead of stopping dead.
- **About-face** (Down: he walks toward the camera): the camera swings round
  behind him the way it started, never dithering at 180 degrees.
- **The mouse** orbits as before; the follow waits `ThirdReturnDelay` (1.5 s)
  after the mouse last moved.
- **The controls and the follow do not fight.** The arrows are read against the
  camera yaw *latched when the set of arrows held changes* (a press or a
  release), moved afterwards only by the mouse orbit. Reading the camera every
  frame, a held Right would chase a camera that chases him: he would circle at
  the camera's top rate. Latched, a held Right walks him straight to the right
  of where the camera looked while the camera settles behind him, and Up then
  carries on straight ahead (re-latched behind him); a further Right is
  another 90-degree turn. So a square is Up, Right, Right, Right, Right.
- **In and out of a car**: the chase camera's spring (`ThirdChaseTau`, 0.8 s,
  `turn_rate_car`) at the wheel; on getting out the yaw is the car's and the
  on-foot follow starts from there, from rest, under the existing 1.2 s glide of
  the eye. Nothing is reset, so nothing jumps.
- `orbit_follow=0` (default) means this follow, holding the yaw when idle;
  `orbit_follow=1` is the older drift; `follow_tau_walk=0` the held orbit.
  Saved in the F4 settings as `ThirdFollowTauWalk`, `ThirdFollowTauRun`,
  `ThirdFollowDelay` (Camera tab: "Follow at a walk / at a run / waits").

With `GTA2DX9_LOG_CAMERA=1` every on-foot frame logs a `foot:` line (camera
yaw, the target it follows, his heading and walking direction, speed, whether
it follows, whether a key is held), and the `nav:` lines carry `ref`, the
latched yaw the arrows are read against.

Measuring it: `gamerun/cam3_feel.py` (`keys_cam3_feel.sh`; nav_map=1, the shipped
controls) walks a square (Up, then four Right presses), stop-turn-go (a 0.25 s Right tap
standing, then Left, then Up), a circle (Up+Right pressed again every 1.5 s) and in/out of a
car, in third person, run as `STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F11/;
s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> 300 keys_cam3_feel.sh -e
GTA2DX9_LOG_CAMERA=1 -e GTA2DX9_SCENE_NO_CAR=1 -e SCENE_KEY=F11`;
`gamerun/cam3_sheet.py <run dir> <png>` plots the yaws against the game clock (the sum of
the step-locked camera's dt: on a loaded host a hitch stalls game and camera alike) and
cuts frame strips from the square's recording. Sheet `out/camera_feel3_sheet.png`, clip
`out/camera_feel3.mp4` (local).

Measured (run `cam3_r3`, 8 Nov 2026, defaults, a loaded host at 0.95 game seconds per wall
second): the square's four Right presses turned him 83-85 degrees each; the camera settled
within 5 degrees of his new heading 3.1-3.3 game seconds after the press (of which about
0.3 s is the key reaching the game and 0.4 s the delay), with no overshoot and no reversal
of the follow, peaking at 52 degrees a second. One turn showed 8.8 degrees past the heading
and one reversal in the *shown* yaw: he brushed a building and the wall clearance moved the
eye; the follow's own yaw stayed monotonic. Stop-turn-go: a 0.25 s Right tap standing
turned him 62 degrees and the camera followed from rest after the delay, peaking at 42
degrees a second; the Left tap brought both back. Circle: monotonic, 24 degrees a second
peak. Car: in, the chase spring swung round to the car's heading (unchanged); out, the yaw
was held where the car left it, no jump. No frame turned the picture more than 4.0 degrees
(the 120 degrees a second cap at 30 fps). Not measured here: the mouse orbit with the follow
(no mouse in the scripted runs), the browser play page, Down (the about-face rule).

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

## Camera and props, walls, getting in (CAMERA-PROPS, 8 Nov 2026)

QA3 findings 2-4 and QUALITY-BAR rows 2 and 7. Code: `dll/src/view_modes.cpp/.h`; in
`dll/src/map_objects.cpp/.h` one read-only accessor, `MapObjectObstacles()`: the footprint of
every standing game object drawn this frame, including those outside the picture (the existing
`MapObjectFootprints()` lists only those inside it, so an object behind the chase camera, where it
was about to go, was missing). Probe: `gamerun/camprops.py` (`keys_camprops.sh`, items in
`CPR_ITEMS`: `car booth shop lamp mouse`), run as `GTA2_DIRECT_KEYS=1 STAGE=<stage> FPS=0
INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> 420
keys_camprops.sh -e GTA2DX9_LOG_CAMERA=1 -e GTA2DX9_SCENE_NO_CAR=1`; sheet
`gamerun/cpr_sheet.py <before run> <after run> <png>`, `out/camera_props_sheet.png` (local).

- **Phone boxes and the game's objects** (QA3 2: the camera inside the tutorial phone box). The
  chase camera keeps 0.15 block clear of every game object standing at his level, as an upright
  cylinder round its footprint widened to the box's corners (x1.42). Over a low one (phone box,
  bin, cone, crate) it rises to 0.3 above the roof at the same spot; a tall one, or one with no
  room above, it stands in front of, toward him; when he stands at it, round its side. Applied to
  the wanted spot and again to the eased eye. Hanging objects (a traffic light's head over the
  road) are left out, so a car never hops over one. Lamp posts and the rule-placed furniture were
  already in `PanelDistance`. Not covered: the park trees (placed inside `DrawProps`, no accessor).
- **His own cell is not a wall** (QA3 4, QUALITY-BAR row 2 "stares at paving", "wall after leaving
  a car"). GTA2 often puts a shop front's solid face on the pavement block in front of it, and
  `Blocked()` calls that block solid, so with his back to the shop every ray from him was blocked
  at once; the pivot was then moved up to 0.9 block *in front of him* and the camera looked down at
  the paving ahead (before: all four headings at the QA3 exit spot, map 118.24,156.84, framed paving
  and no player). On foot the march now ignores his own cell. Pulled in within a block of his head
  by a wall the arc cannot clear, the camera *used to* crane straight up over him and swing round
  him 30-120 degrees; both are gone since FIX-CAMERA (below): it stays on the boom's line. Close in (under 1.1 block), the point looked at comes
  back from ahead of him toward his chest (up to 80 %), so the frame holds him and not the wall.
- **First person by a post or a car** (QA3 3). The "lamp post" bar of `qa_crash_10` is the Truck
  Cab's exhaust stack: the frame before it (`qa_crash_09`) shows the stack beside the eye, and the
  probe found no lamp within 1.5 blocks of that spot (`view: fp eye ... post 99`). The eye is kept
  0.3 block outside the box of the car he last drove (its body's extent remembered from the wheel;
  a sedan's box for any other car) and 0.3 block from a lamp post's axis, 0.1 clear of a game
  object's box: a continuous sideways slide, never into a wall. The once-a-second `view: fp eye`
  line now ends with the distance to the nearest post.
- **Getting in** (QUALITY-BAR row 7). Getting into a car loses the player for up to a second while
  the locator re-scans (`lost` 20 per entry); after 0.3 s the "lost" camera used to crane up and
  back 3 blocks, and the chase rig then started from there: the hard cut to a high, far camera. On
  foot and on his feet the lost camera now holds for 1.5 s (killed, or in a car that blew up, it
  still cranes after 0.3 s). Otherwise the entry was already one glide (eye ease 0.44 s, lag up to
  6 blocks, the chase yaw at its 90 degrees a second cap).
- **The mouse and the soft follow** (CAMERA-FEEL-3). A mouse movement now also stops whatever swing
  the follow had under way (before, it ran on for up to 0.2 s against the hand); the follow waits
  `ThirdReturnDelay` (1.5 s) after the last movement, then starts again from rest.
- **Measuring the framing.** With `GTA2DX9_LOG_CAMERA=1` the chase camera on foot counts, every
  frame, whether his head (0.42 above the floor) projects inside the 16:9 picture and whether the
  line to it is clear of walls (his own cell excepted): `view: framing third on foot frames= head_in=
  head_seen=` every 300 frames, and a `view: framing miss` line (eye, head) for one miss in five.

Measured (runs `cpr_before2`, DLL before these changes, and `cpr_after4`, 8 Nov 2026, on a
loaded host, `GTA2_DIRECT_KEYS=1`; sheet `out/camera_props_sheet.png`, local):
- Phone box, standing 0.8 / 1.4 block south of it facing away and 0.9 east of it facing away:
  before, the camera stood in or on the box (its roof filled the frame, no player in three of
  four); after, he is framed over the box's roof in all four.
- QA3 shop front (map 118.24,156.84), facing away from the wall, along it both ways and into it:
  before, all four framed paving or the glass with no player; after, all four frame him.
- Framing counter (after): his head inside the picture in 1800 of 1800 third-person on-foot
  frames of the probe, and not behind a wall in 1800 (the QUALITY-BAR target is 99.5 %). The
  count does not test cars or people as occluders, and the run is one district's few spots.
- Getting in (F9 to a parked van, Return, 4 s logged): no cut in either run (largest eye step
  0.16 / 0.22 block per frame, largest yaw step 3.0 degrees per frame, the 90 degrees a second
  cap at 30 fps); no `cam: lost` frame in either, so the lost-camera crane that made the QA cut
  was not reproduced here and its fix is untested in play.
- Mouse with the soft follow, walking: a 3 s mouse sweep turned the camera 27 degrees right and,
  later, 29 degrees left with the hand alone (monotonic, no pull back while the mouse moved); after
  each sweep the yaw held for 1.5 s, then eased back behind him with no overshoot. Standing, a
  sweep is held (by design: standing with no key the follow holds). No fight.
- First person beside the van he had just left (`cpr_after3` `car_fp_*`): the eye kept 0.3 block
  outside its box, so its side fills the frame when he faces it but no part of it sits a hand from
  the eye. Not reproduced: the QA3 Truck Cab stack itself, and a lamp post (none within 1.5 blocks
  of the QA3 spot). The park trees are not covered (no accessor).

## The boom as a state (FIX-CAMERA, 9 Nov 2026)

Defects chase-cam-foot-snap-cuts, pt-chase-camera-pumps-against-wall, pt-third-exit-car-camera-overhead,
feel-armed-third-camera-collapses-to-eye-looking-down. Code: `ViewCameraSolver::Solve`, "the boom filter"
(`boom_`, `boomClear_`, `armDir*_` in `dll/src/view_modes.h`).

- The wall solve (pivot march, arc lift, overhead, second pass on the eased eye) still says how long the
  boom *may* be. What is shown sits on that line from the pivot at `boom_`, a length with a capped rate:
  it shortens at most 9 blocks a second (0.3 a frame at 30 fps) and lengthens only after the solve has
  left it alone for 0.3 s, then eased (0.3 s) and at most 2.2 blocks a second. Before, the solve moved
  the eye from 2.2 blocks to his head in one frame and back out the next (`cam: third back=2.18 -> 0.01`),
  and a car grinding a wall pumped the boom a block every two seconds.
- Never shorter than 0.6 block from his head on foot (measured flat, so a boom lifted over a wall still
  stays 0.6 behind him), and outside the car's own body at the wheel (its
  half length + 0.15 from the body centre): the eye no longer ends up inside the van's roof.
- The orientation is the rig's along the boom (a spring arm): a pull-in slides the camera toward his
  head and turns nothing, so his head stays where the rig puts it in the frame. The crane up over him
  and the 30-120 degree swing round him when pulled in close are removed (they changed the view by tens
  of degrees within a frame or two and looked down at the paving).
- Pulled in to under 0.35 block the boom's direction turns toward the rig's own at 2.5 rad/s instead of
  following the solved eye (whose direction from the pivot is noise there).
- After a warp, a respawn or a level cut the first frame puts the eye straight onto the solved rig (it
  used to start on his head and ease out: the armed-warp case framed the paving for 2.7 s).
- In or out of a car the boom restarts from where the eye is, so the hand-over stays continuous.
- Log (`GTA2DX9_LOG_CAMERA=1`): `cam: boom foot|car len= solved= want= rig= min= clear=` on every pulled
  frame and every 15th otherwise, next to the `cam: third ... back=` lines.
- Measured (feel probe foot/punch/gun, Downtown plaza and railed enclosure, 30 fps): one-frame `back`
  changes over 0.35 block 13 before (`fixcam_feel_base`), 0 after; a car held against a wall: before
  1.44 -> 0.00 in one frame and the inside of the roof (`fixcam_wall_base` wall_1 f270), after no frame
  over 0.30 (`fixcam_wall2`).

## Cars and wrecks at the chase camera's lens (FIX-CAMERA-2, 9 Nov 2026)

Defect feel7-third-chase-camera-inside-car-or-wreck-body. Code: `ViewCameraSolver::Solve` ("the lens never in
or against another car's or a wreck's body", `carLift_`), the car list `LiveCameraCars()` (`live_geometry.cpp`,
filled with the contact-shadow footprints in `RaiseCarBody`: four corners, ground y, body height from
`CarBodiesExtent`, one frame old).

- The boom used to pass through traffic and wrecks level with him; the hull's inside or flank filled the
  frame. Now the shown eye rises over any car or wreck whose footprint comes within 0.55 block of it (seen
  from above) to 0.2 block over its roof, at most 6 blocks a second (0.2 a frame at 30 fps), and comes
  down eased (0.5 s) once it has passed; at most 1.2 blocks, and never into a ceiling. The car he drives and
  one he stands in or against are not obstacles. Third person only; the wall solve and the boom filter
  (above) are unchanged.
- Not through the wall solve: making cars solid there was tried first, and a car crossing behind his van
  pulled the boom in and craned it up at once, the van's own roof filling the frame (run `fc2_drive_c1`).
- `GTA2DX9_CAM_CARS=0` turns it off (A/B). With `GTA2DX9_LOG_CAMERA=1`: `cam: car near d=` on each
  third-person frame with another body within 0.4 block of the eye, and `cam: car near summary` every 900.
- Measured on `keys_pf_jack.sh` (QB14_VIEW=third, kerb in Downtown traffic, 4 jacks): off, 407 of 2700
  third-person frames had another car's body within 0.1 block of the eye (`fc2_jack3_c0`); on, 0 of 3600
  (`fc2_jack3_c1`), nearest 0.20.

## A wall behind the car: no shot straight down onto the roof (FIX-CAMERA-2, 9 Nov 2026)

Defect feel8-third-reverse-into-wall-camera-straight-down-onto-roof. Code: `ViewCameraSolver::Solve`, the arc
lift's `aMax` and the pitch hold after `camPitch`.

- At the wheel the arc lift over a wall behind the car stops at 40 degrees (it was 75; on foot 45 since
  FIX-CAMERA); past that the boom shortens instead (the boom filter's rate limits as before).
- The look pitch at the wheel is never steeper than 35 degrees down (or the mouse orbit's own pitch plus
  the chase pitch, when the player looks down himself), so the horizon stays in the picture.
- `GTA2DX9_CAM_PITCHCAP=0` restores the old lift and drops the hold (A/B). With `GTA2DX9_LOG_CAMERA=1`:
  `cam: pitch P raw=R car|foot` every frame at the wheel (every 15th on foot), R before the hold.
- Probe `gamerun/keys_fc2_rev.sh` (`fc2_rev.py`: the parked car at the wall-grind spot, three reverse-and-turn
  passes held against the building): off, 82 frames steeper than 30 degrees, down to 47, roof only in the
  picture (`fc2_rev2_p0`); on, never steeper than 29, horizon in every frame (`fc2_rev2_p1`). Largest eye
  step 0.28 / 0.12 block a frame, yaw 3.0 / 1.5 degrees a frame.

## The move into a street view keeps him in the picture (FIX-CAMERA-2, 9 Nov 2026)

Defect pm11-classic-to-third-switch-camera-rolls-and-lands-behind-wall-player-hidden. Code: `WorldView::ApplyTransition`
(`dll/src/world_view.cpp`, `transitionAimYaw_`). Moves into classic are unchanged.

- Into third or first person the moving camera looks at the destination's look point (2.4 blocks along the
  destination's view: him, from the chase camera), and that turn is finished in the first 60 % of the move.
  The position is still the arc and the FIX-OCCLUSION clearance (which, at the Industrial start yard, holds
  the camera where it was for most of the move). Before, pitch and heading were eased blindly from straight
  down to the chase pose: the camera, held up above the yard, tilted up to look level at its walls and roofs
  with him out of the picture below.
- The turn's direction is chosen once and the aim heading unwrapped frame to frame: with the destination heading
  at +-180 degrees "the short way" flipped between frames (one frame turned 76.7 degrees back).
- `GTA2DX9_MOVE_AIM=0` restores the old easing (A/B). With `GTA2DX9_LOG_CAMERA=1`: `view move: t= ... off= ystep=`
  for 3 s after a switch (shown pose, the view's own pose, the angle from the look point, the heading step).
- Probe `gamerun/keys_fc2_sw.sh` (bil start, walk into a V press, four switches, 9 s clips): him more than 30 degrees
  off the view axis in 72 of 164 move frames before (`fc2_sw2_a0`), 18 after (`fc2_sw3_a1`, all in the first
  35 % of a move, where the classic camera's wide view still holds him); largest heading step 76.7 -> 10.6
  degrees a frame. Measured from the `view move` lines against the `cam: third ... at=` position.
- Still: mid-move the held camera can sit a hand from the yard's wall (half the picture one wall, him in the
  other half): the hold's position, not changed here.

## The whole figure in the frame on foot; the boom against the mesh (FIX-CAMERA-3, 9 Nov 2026)

Defects feel16-armed-third-hero-sinks-off-bottom-edge-while-firing, feel17-third-alley-camera-crops-hero-legs-at-hip-or-knee,
feel17-armed-third-camera-inside-hero-screen-filled-with-blurred-cloth. Code: `ViewCameraSolver::Solve` in
`dll/src/view_modes.cpp` (`reachTo`/`meshSolve`, the boom filter's mesh cap, `bodyLift_`, the frame clamp after the
turn-rate cap). Third person on foot only: in a car, first person and the classic view nothing changes.

- The frame clamp. The orientation is the rig's, taken from the full-length boom; when a wall pulled the eye in
  to 0.6 block the camera kept looking out over him (pitch -11 with his feet 47 degrees down, the alley by the
  phone box at wil 159.5,139.5), and the armed rig's look-ahead turning with him put him under the bottom edge
  while firing. Now, from the eye that is shown, the pitch and then the yaw move only as far as keeps his feet and
  the top of his head (0.48) inside the middle 76 % of the frame (the acceptance box is 80 %; the rest is room
  for shake and recoil). A figure too big for the frame is centred. Not while the mouse has the camera
  (`tpReturnDelay`), nor on the death camera. `GTA2DX9_CAM_FRAME=0` turns it off.
- The boom against the drawn mesh. The wall solve asked the map's cells only; the iron staircase by the phone box
  is not in them, and the camera stood behind its rail: the bars a blurred olive smear over most of the frame,
  him hidden (the "cloth" of the feel17 report). On foot `reachTo` also ray-casts `eyecol::SegmentHit` and stops
  0.15 short of the first surface; the arc lift over a wall uses the same test; the boom's 0.6 minimum no longer
  pushes the shown eye through a surface the mesh puts in the way.
- Never inside the figure: a boom pulled in under 0.4 block (flat) from his centre line, below his head plus 0.3,
  rises over his head (cells and mesh permitting, eased 0.08 s up / 0.4 s down), and the clamp looks down at him.
  `GTA2DX9_CAM_MESH=0` turns the mesh solve and this lift off.
- Log (`GTA2DX9_LOG_CAMERA=1`): `cam: frame clamp pitch A -> B yaw +Y (feet F head H margin M, flat D)`,
  `cam: over the figure lift=`, `cam: figure cut eye= at=` (a frame whose figure leaves the 80 % box); always:
  `view: framing third on foot ... whole=N` (frames with the whole figure in the box, out of `frames`).
- Probe `gamerun/keys_fc3.sh` (`fc3_probe.py`, FC3_SEGS=shoot,bump,pistol: the feel16 MG burst while tracking a
  ped, the feel17 walk into the alley, the feel17 pistol burst at the stair; one step back after each warp, since
  the game does not draw him after a devtools warp until he moves). Same build, same script: whole figure in
  900 of 900 on-foot third-person frames with both on (`fc3_ab_on`), 207 of 1200 with both off (`fc3_ab_off`:
  cut at the waist on the bottom edge, the stair rail over the lens).
- Still: in a tight corner the clamp keeps him whole by looking steeply down from 0.6 block (a top-down-ish
  shot, not a shoulder shot); the first-use hitch on a V into a street view (a 3.6 s frame in `sprites`) still
  freezes the move high over the plaza (performance stream, not the camera's end pose).

## Railings as sheets for the camera; the boom swings round before it rises (FIX-CAMERA-4, 9 Nov 2026)

Defects feel25-third-camera-pressed-into-iron-fence-9s-punch-and-knockdown-never-visible,
pm26-wil-fp-eye-inside-iron-fence-black-bars, pm26-wil-third-first-v-hero-cut-off-by-bottom-edge. Code:
`src/world_mesh.*` (`WorldMesh::railingPanels`), `dll/src/eye_collision.cpp` (the sheets, `PushPanels`),
`ViewCameraSolver::Solve` in `dll/src/view_modes.cpp` (`swingAngle_`, the panel step, `kRailClear`).
Nothing is drawn differently: the classic view and every draw call are as before.

- Railings as sheets. QB-11 builds a railing tile as bars and rails; a ray or the eye's sphere slips between
  the bars. The mesh builder now also records each railing panel's plane (12 floats, never drawn) and the eye
  collision bins it as a two-sided face: the boom's ray-cast, the first-person `eyecol::Clear` and the safety
  net treat a railing as one solid sheet. 233 panels in wil (log: `eye collision: ... N railing panels as
  sheets`). `GTA2DX9_RAILING_SHEETS=0` leaves them out.
- The cell-based panel step (a camera within 0.35 of a railing's cell panel went on through to the far side,
  the design from before the bars were modelled) is skipped on foot with the mesh solve: it is what put the
  camera behind the plaza fence corner (wil 167,148) looking through its posts for 9 s in the owner demo.
- The swing. On foot, when the line behind him reaches less than max(0.9, 0.6 x rig length), the boom turns
  about him (15 degree steps up to 90, the side it already swung to first, eased 0.25 s out / 0.6 s back) to
  the smallest yaw that reaches that far; the lift arc over a wall still applies after it. At the plaza fence
  corner the camera goes round the corner instead of collapsing over his head; on the first V at the wil spawn
  it swings 60 degrees round the iron staircase instead of looking steeply down over its rail.
  `GTA2DX9_CAM_SWING=0` turns the swing and the railing berth off. Log: `cam: swing S want W deg`.
- Railing berth: the shown eye is kept 0.45 off a railing sheet sideways (`eyecol::PushPanels`; at 0.12 the
  spear tops were a dark band over a quarter of the frame), never through anything on the way.
- Probe `gamerun/keys_fc4.sh` (`fc4_probe.py`, FC4_X/FC4_Y, default the fence corner at 167.4,147.8).

## The swing holds its heading; a side berth; the V move rides the car (FIX-CAMERA-5, 9 Nov 2026)

Defects feel24-third-armed-turn-to-target-camera-swings-through-wall-hero-lost-1p6s-returns-cropped,
feel23-v-third-to-first-while-driving-camera-trails-3s-van-drives-off-then-cockpit-arrives-tilted,
pm15-third-camera-flush-with-wall-corner-half-frame-blur-player-sliced. Code: `ViewCameraSolver::Solve` in
`dll/src/view_modes.cpp` (the swing, `swingRigYaw_`; the side berth in the boom filter) and `WorldView::ApplyTransition`
in `dll/src/world_view.cpp` (`transitionTarget0_`, `transitionSeconds_`). The classic view is untouched
(tools/vreg classic shot: 0 changed tiles).

- The swing holds its heading. The armed rig turns with him at up to 240 degrees a second (QB-6), and the swing
  (FIX-CAMERA-4) was an offset from the rig eased over 0.25 s: on a turn on the spot by a wall corner the camera
  was dragged into the corner and the boom filter pulled it from 1.5 to 0.6 block in five frames (him 2.5 times
  bigger, seen steeply from above). Now, on foot, when the way the swing would go from the camera's present
  heading to the one the rig wants crosses a walled sector (sampled every 15 degrees with the boom's reach), the
  camera holds its heading in the world and he turns in the picture; it follows once the way round is open.
  Otherwise the swing may take up the rig's own turn at once (anywhere between following the rig and holding still
  is no extra motion) and eases only the rest. `GTA2DX9_CAM_SWING_HOLD=0` restores the plain ease. Log:
  `cam: swing S want W deg (holding: the way round is walled)`.
- Side berth. The boom stops 0.15 short of what is on its own line; a wall beside the line could still come to a
  hair from the lens at a corner. The shown eye on foot is now kept 0.25 off every surface (`eyecol::Push`), never
  through anything on the way from his head. `GTA2DX9_CAM_SIDE=0` turns it off. Log: `cam: side berth moved D`.
- The V move rides its destination. The move's start was a world point fixed at the key press: in a car at speed
  the van drove out of the picture while the camera eased off that point, and the cockpit came 3 s later. The start
  pose is now carried with the destination (moved with it, and between the two street views turned with its
  heading), so the move happens in the car's (or his) frame. Between third and first person the move takes 0.8 s
  (it was 1.4). Into first person at the wheel the move ends where the eye passes below the roof line of the car
  the destination sits in (`LiveCameraCars`): flown on down it showed the dash's black top, and a level approach
  from behind crossed a van's closed cargo box for twelve dark frames. Log: `view: moving the camera to M over S s
  (anchor=...)`, `view: move into the cab: arrived at t=T`.
- Probe `gamerun/keys_fc5.sh` (`fc5_probe.py`, FC5_SEGS=spinwall,turnplaza,vdesc,vact,vfp,cornerwalk; 30 fps bursts).
  Pistol, three fast turns on the spot by the wall corners at wil 163.5,137.5 and 157.5,144.5: shortest boom
  0.55/0.41 block and 12/8 frames pitched past 25 degrees down before (`fc5_all_base`), 0.94/0.94 and none after
  (`fc5_all_v3`); nearest surface to the lens 0.12 before, 0.25 after (`fc5_all_v4`). V at speed in the van:
  the van in frame throughout and the cockpit level about 20 frames after the press (before: the van left the
  frame and the cockpit arrived about 40 frames after the press, rolled some 20 degrees in the turn that followed;
  `fc5_all_base` against `fc5_vfp6`, `fc5_final3`).
- Still: a full turn on the spot in a corner still changes his size about 1.6-2x as the boom shortens round the
  corner (the acceptance asks for 30 %); walking into a corner pocket the mesh cap still drops the boom to 0 in one frame
  and the camera looks down over his head for under a second (`cam: figure cut`, as on HEAD); the first time in a
  session the first-person view is entered in a given car, its first two frames are black (the seat view's roof
  cut comes in a frame late: car bodies, not the move); the cockpit's roll in a hard turn is the first-person body
  roll, not the move.

## No cut at a punch, the V to the map rides the car, no figure at the lens (FIX-CAMERA-6, 9 Nov 2026)

Defects pfeel3-third-punch-contact-camera-cuts-in-one-frame-to-overhead, pfeel4-third-to-classic-while-driving-
camera-loses-van-and-climbs-facade, pm43-bil-fp-respawn-at-hospital-eye-inside-ped-face-fills-frame,
pfeel32-v-first-to-third-parked-camera-stays-steep-60deg-car-cropped-at-bottom-edge. Code: the boom filter and the
end of `ViewCameraSolver::Solve` (`dll/src/view_modes.cpp`), the first-person eye in the same function,
`WorldView::ApplyTransition` (`dll/src/world_view.cpp`), the bar faces in `dll/src/eye_collision.cpp`, the lens
cull of the figures in `dll/src/live_geometry.cpp`. The classic view is untouched (see the vreg line below).

- Measuring. `GTA2DX9_LOG_CAMERA=1` now also writes one `cam: pose` line per street frame (and per frame of a
  move): the eye, yaw, pitch, field of view, the eye's step and the pitch's step since the last frame, and where
  his axis (on foot: feet, head, his width at the chest) or his car's footprint box lands on the screen (0..1).
  The tables below are read off these lines (`/tmp`-style script: per 30 fps burst, the largest pitch step, the
  largest eye step, the frames with a pitch step over 10 degrees or an eye step over 0.35 block, the frames with
  him outside 5..95 % of the frame). Probe: `gamerun/keys_cam6.sh` (`cam6_probe.py`, CAM6_SEGS=punch,pocket,
  spinwall,corner,vpress,parkv: punches at the plaza fence pocket, FIX-CAMERA-4's pocket, FIX-CAMERA-5's corner
  spin and corner walks, V while driving, V first -> third with the van stopped by a wall).
- The shown orientation turns at a capped rate (pfeel3). The frame clamp (FIX-CAMERA-3) set the yaw and the pitch
  outright: when the boom was pulled into him at the fence the view turned 122 degrees and 26 down in one frame,
  and with the eye over his axis the pitch swung 30 degrees a frame. Now no frame turns the shown view more than
  280 degrees a second of pitch (9 a frame at 30 fps) or 300 of yaw, the clamp's correction included (not the mouse, not the first frame
  of a view, not the death camera's glide). `GTA2DX9_CAM_RATE=0` turns it off. Log: `cam: turn capped`.
- The boom eases in at a railing (pfeel3). The plaza fence is two-sided sheets (FIX-CAMERA-4) plus its 3D bars,
  which the collision had as walls: the boom's mesh cap took the eye from 2.14 block behind him into his head in one
  frame (2.49 block). The bars, rails and finials on a railing sheet's plane are now marked (`eye collision: ... N
  bar faces on them`, 33150 in wil) and a sheet or a bar pulls the boom in at the boom's own rate (9 blocks a
  second); a wall still stops it at once, unless the slower eye is in clear air (then at the same rate).
  `GTA2DX9_CAM_SOFT_PANELS=0` cuts as before. Logs: `cam: boom eased in at a sheet`, `... at a wall edge`.
- The V to the map rides the car (pfeel4). Into the classic view the move's start stayed where the chase eye was
  at the press, and the orientation was a plain blend: at speed the van left the picture for about 1.2 s while the
  view swung round onto the facades. Now the start moves with him (the player located every frame; the classic
  camera, which leads the car at speed, when he is not found), the view looks at the car's look point as it rises (2.4 ahead of a chase eye, the nose 0.8 ahead of a
  driver's eye) and turns to the classic orientation only over the second half of the move, and near the car the
  rising camera keeps the mesh clearance seen from the car. `GTA2DX9_MOVE_RIDE_CLASSIC=0` restores the old move.
- No figure at the lens (pm43). After WASTED the first-person eye was put at the hospital door with a figure
  standing there: a face and a shirt cut by the near plane filled the frame. On foot the first-person eye now keeps
  0.30 block (about 1.2 m) from every other drawn figure (moved straight out from it, at most 0.4 from his centre,
  never into a wall or the mesh; a move over a quarter block glides), and the renderer leaves undrawn any figure
  whose axis is within 0.15 block of the eye at the eye's height (in first person his own as well, in third person
  never him). Logs: `view: fp eye: figure D from the eye, eye moved M`, `view: figure at the lens not drawn (...)`.
- Pulled in at the wheel, the eye rises over the roof (pfeel32). With the car stopped and a building close behind,
  the boom came to rest on the body's rear edge at roof height looking level: the roof filled the lower 60 % of the
  frame for as long as he sat there. Pulled in (stopped or creeping), the eye now rises over the roof by most of what
  the boom lost (at most 0.8 block, eased, as far as the cells over it are open) and tips down toward the car within
  the 35 degree cap. `GTA2DX9_CAM_CAR_RAISE=0` turns it off. Log: `cam: car raise R (boom S short of L)`.
- Measured (wil, `keys_cam6.sh`, 30 fps bursts; HEAD + the pose line `cam6_tp_base` against the fix builds
  `cam6_tp_fix4`/`cam6_tp_fix5`; the takes wander, so the punch spot and the cars differ between runs):

  | burst | before: max pitch step / max eye step / frames he is out | after |
  |---|---|---|
  | punch at the fence (punch_1) | 29.8 deg / 2.49 block / 57 (box from 0.12 corners) | 6.7 deg / 0.47 / 7 (axis box) |
  | punch at the fence (punch_2) | 28.5 / 1.86 / 41 | 6.7 / 0.46 / 6 |
  | FIX-CAMERA-5 corner spin (spinwall) | 1.8 / 0.20; figure height 0.25..0.58 of the frame | 4.4 / 0.19; 0.23..0.49 |
  | FIX-CAMERA-5 corner walks | 7.9 / 0.36; 0.23..0.76 | 0.1 / 0.18; 0.17..0.23 (fix5) |

  The eye's largest steps after are the boom's 9 blocks a second on 50 ms frames (the host at load 40-50). In frames
  (base against fix4, punch_1): before, a cut from the street view to a close top-down at the fence, about 0.4 s
  with no hero in the picture, and a cut back out; after, one continuous move in past the fence's spears to a high
  look-down and back out. V first -> classic while driving: before, the van out of the picture for about 1.2 s
  while the view looked at a facade; after, out for 2-3 frames as the view dives from the cab, then in frame to
  the classic pose. First-person death and respawn at the bil hospital (`cam6_bil_fix4`): a clean forecourt, and
  during the blast the eye stepped 0.06-0.14 off a figure 0.16-0.24 from it.
- Still: in a pocket with a solid wall right behind him the boom still comes in over his head and the view looks
  down steeply for about a second (now a continuous crane move, not a cut); 2 frames without him were seen at the
  fence before the 280 degree cap. The face of pm43 was not reproduced on HEAD in two takes (the respawn was clean
  both times): the lens cull and the eye push are checked in the log, not on that face. The arrival into the cab at
  the end of a third -> first move still pitches 12 degrees in one frame (the roof-line arrival, FIX-CAMERA-5) and
  the end of a classic -> third descent 10-12 degrees a frame for two frames.

## Reversing at the wheel, the cab to the map, the lean sheet (FIX-CAMERA-7B, 10 Nov 2026)

- **Reversing: the cells' false walls are asked of the mesh** (pf2feel-third-reverse-open-street-camera-stays-put-van-
  backs-under-it). At the wheel the chase boom was solved against the map's cells only, and `WorldView::Blocked` calls a
  whole block solid when it has a lid: a ramp's block, air over the slope included. Reversing the scene van toward the
  ramp at wil 198.5,61 (the ramp's face 2.8 blocks behind at the camera's height, `world_raycast ray`), the eye stopped
  dead 1.5 blocks early, the boom fell from 1.47 to 0.70 in 0.3 s and the van backed under the lens, its roof filling
  the frame (run cam7b_rev1). Now, in a car, a point in a blocked cell that is in no closed block of the drawn mesh
  (`eyecol::InsideSolid`) and 0.2 or more from every drawn surface (`eyecol::Nearest`) is air, and the boom's line is
  stopped by the mesh's walls (`SegmentHitSolid`; a railing's sheets and bars are see-through, as the cells' flat
  panels always were). Same spot after: the boom stays 1.42-1.47 through the reverse, the van whole in every frame;
  forward 2.2 s, reverse 4 s, forward again: whole in every frame (runs cam7b_rev2, cam7b_p1 rev2_third).
  `GTA2DX9_CAM_CAR_MESH=0` restores the cells alone (A/B). Still short: having backed into a one-block gap between
  two buildings, a forward turn out of it pulls the boom to 0.7-1.0 at 20-28 degrees down for ~2 s (real walls).
- **First person -> classic while driving: up out of the seat, then across** (pfeel33). The move's path drifted
  toward the classic camera (which leads the car at speed by blocks) from the first frame and its aim was the nose 0.8
  ahead: the eye left through the windscreen in 0.3 s, one frame showed the street with no car, then the van sat at
  the bottom edge for ten frames (cam7b_p1 vfpc_0). Now (`fpRise`, from first person only) the eye pops up out of
  the seat (1.4 blocks over 0.5 s, ease-out, then on at 1.5 a second until the old path is higher) and backs off over
  the car's rear a little after it (2.2 blocks, given back as the drift to the classic pose comes in), the drift
  across waits for 25 % of the move, the heading stays the cab's until the turn to the classic pose, and the pitch
  turns onto the car's middle (0.35 ahead of the seat, 0.45 down) over the first 0.3 s of the move. Iterations: straight
  up with the pitch tied to the height whipped 72 degrees down in two frames (cam7b_p3); straight up with a timed
  pitch left the van under the picture for 0.45 s (cam7b_p4); 1.6 back / 2.2 up, 8 frames (cam7b_p5); the pitch over 0.05-0.45 s, a sliver of roof at the bottom edge for
  0.25 s (cam7b_p6).
  `GTA2DX9_MOVE_FP_RISE=0` restores the old path.
  The `cam: pose` and `view move:` lines are now written during a move into the classic view too (the car box in them
  is stale there: the chase solver does not run in classic).
- **Ported from FIX-CAMERA-7 (died 23:20 with the diff uncommitted)**: the lean sheet (`eyecol::SetNearSoftSkip`: on
  foot a two-sided sheet or a railing's bar crossed within 0.25 of the boom's start is one he leans on, not one in the
  way; OFF by default, `GTA2DX9_CAM_LEAN_SHEET=1` turns it on: with it on, run cam7b_p3 punch_1 still slid the lens
  through the fence's finials for 3 frames, so it is not yet shown to help) and the move turn cap (into a street view the shown pose turns at most 240 degrees a
  second, through the move and up to 0.6 s after it; `view: move turn capped` log line; `GTA2DX9_MOVE_TURN_CAP=0`).
- Probe: `gamerun/keys_cam7b.sh` + `cam7b_probe.py` (cam6's segments plus `vfpc` (first -> classic driving, x
  `CAM7B_VFPC`), `rev` (reverse 3 s then forward), `rev2` (forward, reverse 4 s, forward), `exit` (exit at speed)).
  `keys_pf2.sh PF2_SEGS=rev` is the filer's repro (the scene van at wil 198.5,188.5 game coordinates).

## Respawn and re-arm: the first frame is the chase pose (FIX-CAMERA-8, 10 Nov 2026)

- **pfl11** (third person, after BUSTED/WASTED the camera opened looking down at his head and craned out over
  1.2 s). Pose log of a real BUSTED at the wil station door (run cam8_p11base): the rig re-armed on the 60-block
  jump with a sheet 0.5 behind him; the swing it wanted (30 degrees round it) was eased from 0, so the first
  drawn frame had a boom of 0.36 and pitch -46, then craned out. Now, on the frame the rig re-arms (snapEye_:
  a respawn, a warp, a level cut), the wanted swing is taken at once, so the boom starts clear round what
  stands behind him. `GTA2DX9_CAM_REARM_SWING=0` eases it as before (A/B). Log: `cam: re-armed with the swing
  it wants: <deg>`.
- A street view that lost the player for longer than the hold (150 frames) falls back to the classic camera;
  found again, it used to enter by the full classic -> street descent (pitch -90 at the start). It now cuts to
  the solved pose (`view: found again after the classic fallback: cut to ...`). `GTA2DX9_RESPAWN_CUT=0`
  restores the descent. A V into classic clears the flag (a later V is a V move as before).
- The `cam: pose` line now ends with `roll=<deg>` (the drawn camera roll).
- **pfl14** (on foot at the wil iron staircase, 159.5,139.5: the boom lunges in and the view looks 50-60 degrees
  down; the "roll" in the report is that pitch's perspective, `roll=` stays 0 in every run). Not fixed; three causes
  found in the per-frame log (`GTA2DX9_LOG_CAMERA=2`: `cam: swingv`, `cam: sheet ease test`): (1) the stair's rail
  sheet 0.2-0.45 from his centre crosses the boom's line as he steps and turns, and every crossing pulls the boom
  in at kBoomIn (9 blocks/s); (2) the stair's map cells are solid where the drawn stair is air, so the solve reads
  reach 0 at his feet; (3) the staircase body is a real wall to a large swing, and the 280 deg/s pitch cap cranes
  -11 -> -60 in five frames. Knobs added, all OFF by default (HEAD behaviour): `GTA2DX9_CAM_SHEET_EASE=1` (a sheet
  with the lens 0.45+ beyond it pulls in at 2.5 blocks/s), `GTA2DX9_CAM_LEAN_SHEET=2` (skip sheets within 0.45 of
  him), `GTA2DX9_CAM_FOOT_CELL_MESH=1` (on foot a solid cell is asked of the mesh, as 7B does at the wheel),
  `GTA2DX9_CAM_FOOT_PITCH_RATE=<deg/s>`. With all four on, 6 of 10 runs had max 2-frame distance change 8-18% and
  pitch <5 degrees (filer's acceptance), but run cam8_p14H held the lens beyond the rail sheet filming the stair's
  treads with him hidden for ~10 frames (treads seen from below are no wall to `SegmentHitSolid`), worse than the
  lunge. A shipping fix needs the stair as a solid volume to the boom (or the treads two-sided in eye_collision).
- Probes: `gamerun/keys_cam8_bust.sh` (machine gun in the wil crowd, `force_wanted=6` set live, waits for the
  beat's `respawned` line, then walks on) and `gamerun/keys_cam8_resp.sh` (F11 scene warps in third person
  between a far spot and the station door / pole corner: the rig re-arms on a 60-block jump without the
  classic cut). The hero is not drawn after a developer warp, so judge the warp legs from the log; the real
  respawns from frames.

## The car boom turns aside, the cab cut, the rise out of the seat, the seat's shudder (FIX-CAMERA-9, 10 Nov 2026)

Probes (untracked, `gamerun/`): `keys_pfl28.sh` (a van: launch, hard turn, reverse; first person the same, its
launch hits a wall), `keys_pfl21.sh` (V third -> first -> classic while driving), `keys_cam9_gun2.sh`
(`cam9_gun2_probe.py`: pfl16's gun segment with one step after the warp), `keys_cam9_ram.sh`. All with
`GTA2DX9_LOG_CAMERA=1 -e GTA2DX9_STATE_EVERY=3`, 30 fps. Tables: the `cam: pose` car/hero `box=` per burst.

- **The in-car boom turns aside** (pfl28). Reversing toward a wall the boom fell to its minimum (0.72: the lens
  0.15 off the rear bumper) and rose over the roof looking down 35 degrees; at the wil plaza corner (199,81) a lid
  at 3.0 over the pavement also stopped the arc. Now, at the wheel, when neither the line behind the car nor the
  arc over what stands there keeps the car arc's minimum pull, the boom turns about the car to the smallest angle
  (20-degree steps, one side out to 120 before the other) that keeps 90 % of the boom, else the pull; reversing,
  the line is tested as far as the car backs in 1.2 s. Out at ~0.12 s (at most 200 degrees/s), back over ~0.8 s
  once the line behind holds the pull with room. Turned aside, the chase looks at the car's middle (whole at 60
  degrees), not down the road ahead. `cam: car swing` logs it; `GTA2DX9_CAM_CAR_SWING=0` is the A/B. Run cam9_p28e:
  no frame with the lens over the roof (base cam9_p28a: the roof over 50-65 % for ~2 s), the van side-on and whole
  from 3.0 s; for ~0.8 s mid-turn it still fills about half the frame with its end cut at the side.
- **Into the seat** (pfl21): the move from the chase eye ends (the cut to the cockpit) once the eye is over the
  car's footprint within 0.6 of its roof (was 0.3): the arc carried it 0.5 over a van's roof at the rear edge, so it
  crossed the whole roof first (7 game frames of roof slab, cam9_v21a). cam9_v21b: 2 game frames (3 video frames).
- **Out of the seat to the map** (pfeel33 residual): on the rise the car stays drawn from the seat (cut hull and
  cab) until the eye is 0.25 over the roof (was 0.02): the first rise frame, 0.15 over the roof looking 7 degrees
  down, had the roof under the frame's edge and showed the street with no car (held 0.4 s by a hitch, cam9_v21a
  f1121). cam9_v21b: the held cab for one frame, then the roof. And the rise's clearance anchor (FIX-CAMERA-6's "over
  the car, 1.2 ahead" of the press eye) stops short of the first surface ahead of the seat: with the van's nose at a
  wall it lay beyond the wall and the first rise frame's eye went 1.37 block through it (cam9_v21c f1174). Still
  open: nose-on to a wall (cam9_v21d) the first 3-4 rise frames show the wall before the roof comes into view (the
  pitch eases over 0.3 s).
- **Off a raised level** (pm33, the camera half): at the wheel the rig's base is never under the car's own height.
  Driven off bil's raised road (z 4.0 -> 2.2) the lid under the car was the street's, the base dropped there in
  0.08 s and the chase eye filmed the car's floor pan from below. `cam: car above its floor` logs it;
  `GTA2DX9_CAM_CAR_Z=0` is the A/B. cam9_pm33a pm_044 (the filer's frame): the car from behind and above.
- **The seat's shudder** (pfl25, the camera half): at the wheel in first person the impact shake (the eye's only;
  the cockpit does not take it) is capped at 1.0 with 1.2/1.5/2 degrees of yaw/pitch/roll a unit (was 2.5/2/2 with
  the shake at 1.5); `GTA2DX9_FP_CAR_SHAKE=0` is the A/B. `cam: fp car pitch= body= lean= shake= roll= heave=
  seatfix=` logs the eye's parts per frame: across a wall hit the eye pitch is -3.5..-4.9 (the body's dip). The
  15-degree "dive" in pfl25 is the cockpit redrawn in one frame when the hood dash is rebuilt for a dent step
  (`car bodies: hood dash of ...` on the hit frame), not the eye: open in car_bodies/cab_interior.
- **The WASTED/BUSTED shot** (pm9/pm10, the camera halves): the beat camera's line (FreeFraction) also stops at the
  drawn mesh and at car bodies (the car the body lies in skipped); it used the map cells only, so from the wil spawn
  yard the first-person BUSTED shot was framed through the iron stair's rail sheet, the hero hidden (fh3_beat1), and a
  WASTED shot could stand inside a truck. cam9_bt1 (keys_fh3_beat.sh): the orbit starts 60 degrees round, the hero in
  the open with his hands up. `GTA2DX9_BEAT_CAM_MESH=0` is the A/B. The truck case is untested.
- **pfl16 (MG fight, hero missing 4.4 s)**: the developer warp, not the aim rig: `cam: pose` holds him inside the
  frame throughout; he is not drawn until he first moves after a T.warp (player-invisible-until-game-camera-arrives).
  With one step after the warp: hero in the 5..95 % box on 942 of 943 armed frames over three runs (the one: feet 1 % under the edge at the
  iron stair, the on-foot boom).

## The swing goes round first at the iron staircase (FIX-CAMERA-10, 10 Nov 2026)

- **pfl14** (on foot at the wil iron staircase, 159.5,139.5: the boom lunged into his head and the view craned to
  55-60 degrees down). Per-frame log on HEAD (run cam10_p24a punch_1): he stands 0.2 from the stair's side (a
  two-sided railing face on z=116 over the ramp), the line behind him crosses it as he steps, the solve's reach falls
  from 1.37 to 0.07 in one frame; the swing to the open side was eased over 0.25 s while the boom came in at 9
  blocks/s, so the camera reached his head before it went round. Now (`ViewCameraSolver::Solve`, the swing and the
  boom filter):
  - **Swing first.** When the heading the swing is at reaches under the swing's "good" length and the heading it
    wants reaches it, the swing turns there at up to 360 degrees a second, and the eye state turns about him by the
    same step (the camera orbits; eased along the chord it cut through him and crossed the stair). The way round
    is the short one unless a heading on it reaches under half the good length and the long one's do not.
  - **A cut when neither way round is open** (the stair one way, the wall the other: both 0.07 in run cam10_p15c):
    the solved pose at once, same distance and pitch, logged `cam: swing first: neither way round is open, cut A -> B`.
    One or two per run at the stair foot; frames (cam10_p16a punch_1 4.6 s) show a clean cut from the west view of
    him to the east one, whole in both.
  - **The boom eases while it goes round.** During the fast swing, and for up to 0.6 s after while the shown boom
    still trails the solved direction by more than 8 degrees (it then turns at 7 rad/s, not 4), a see-through sheet
    pulls the boom in at 2.5 blocks/s (FIX-CAMERA-8's sheet ease, now on in this case only); a wall still cuts.
    Meanwhile the lens is kept 0.45 over the floor beneath it (`cam: swing first: lens lifted`), never skimming the
    treads (cam8_p14H was 0.2 over them).
  - **The stair's false-wall cells.** FIX-CAMERA-8's `GTA2DX9_CAM_FOOT_CELL_MESH` is now on by default with this:
    on foot a cell the map calls solid is asked of the mesh (air when 0.2 from every surface and in no closed block);
    otherwise his own-cell exemption flipping at x=160.0 made every heading read blocked for a frame (cam10_p14h).
  - `GTA2DX9_CAM_SWING_FIRST=0` restores HEAD (all of the above, the cell check included unless
    `GTA2DX9_CAM_FOOT_CELL_MESH=1` is set). Logs: `cam: swing first A -> B want W`, `cam: swing first route: short S
    long L` (LOG_CAMERA=2).
  - Measured (filer's `keys_feel74.sh FEEL74_SEGS=punch2` and `keys_pfl24.sh PFL24_SEGS=punch2`, 30 fps, host load
    30-48; per burst the largest 2-frame change of eye-to-hero distance and of pitch): HEAD cam10_p24a 47 % / 18.7
    deg, pitch down to -59, 7 violations in one burst. Final build: runs cam10_p16a..g, 12 pfl24 bursts and 3 feel74
    bursts, pitch steps <= 2.4 deg, hero inside 5..95 % in every frame; one burst (p16b punch_1, him already on the
    stair) has a 34 % distance step, an ordinary 9 blocks/s pull-in at the stair with no pitch change. The
    intermediate builds' runs (cam10_p14*, cam10_p15*) are the iterations listed in the order file.
- **pmt2** (third person at the wil plaza phone box: its blue panes and mirrored PHONE sign over a quarter of the
  frame). The solve kept the solved eye out of street objects (`clearOfObstacles`), but the shown lens sits on the
  boom's own line at its eased length and trailing direction, which nothing checked. Now the shown line stops 0.05
  short of the first object it enters (cylinder widened by 0.12; eased at the boom's rate while the slower lens is
  clear of every object), and a lens inside an object's widened cylinder below its roof moves straight out from its
  axis (never through the mesh). `GTA2DX9_CAM_PROP_BOOM=0` turns both off. Logs: `cam: prop on the boom at D`,
  `cam: prop berth moved M`, `cam: props by the boom` (once a second). The filer's keys_pt2_weapons.sh (six weapon
  stops at the plaza), pose log against the box at 158.50,117.50: HEAD cam10_pmt2a 27 frames with the lens within
  0.45 of its axis below the roof and 10 with the box between lens and him; fix cam10_pmt2d 2 and 0. Still: the box
  can sit large at a frame edge seen from outside when he stands beside it, and the lens may hop 0.3 over its roof
  (the solve's rule for a low object).
- **pfl24** (camera "8-10 blocks away, hero 45 px"): not reproduced on HEAD. The boom is the designed 2.1 blocks
  (3.4 x 0.62), the hero 18-24 % of the frame height; the filer's 45 px was measured on the 1/3-scale sheet tiles and
  he never climbed (z=2.00 in every player line). A >= 25 % hero would need a closer on-foot default (owner's call).

## Near fade and the first-person eye at walls (QB-49, 8 Nov 2026)

QUALITY-BAR row 49 ("a lamp post / wall fills the frame"). Code: `dll/src/map_objects.cpp/.h`
(the fade), `dll/src/view_modes.cpp` (the wall clearance).

- **Near fade.** Every game object drawn as a model (phone box, traffic-light pole and head, bin,
  cone, crate, the pickups) whose upright box (footprint radius, foot to top) comes within
  0.5 block of the eye is drawn see-through: alpha 1 at 0.5 block down to 0.18 at 0.1 block
  (smoothstep), after the opaque objects, blended, without depth writes, so the street and a
  person behind it show through. Applies in both street views (the chase camera beside a box
  too). The eye is read back from the device's view matrix at the top of `MapObjectsDraw`.
  `GTA2DX9_NEAR_FADE=0` turns it off (before/after runs). Log: `objects: near fade: N object(s)
  see-through this frame, the nearest at alpha A` every 150 frames while any is faded.
- **Wall clearance.** On foot in first person the eye sits 0.12 ahead of his centre, so walking
  into a shop front put it at the bricks (one magnified tile filled the frame). When a wall is
  closer than 0.2 block along the view, the eye steps back along the view by up to 0.18 (never
  into a wall behind). A wall 0.2 block ahead still fills the picture, as in any first-person
  game; it is no longer seen from inside. Log: `view: fp eye: wall D ahead, eye stepped back B`
  (first 20).
- **Not covered:** the rule-placed lamp posts and the park trees are drawn by
  `LiveGeometry::DrawProps` (`live_geometry.cpp`, outside this row's files) and are not faded;
  the eye is still only kept 0.3 block from a post's axis (section above), so a post at
  0.6 block still shows as a dark bar at the frame's edge (seen in the probe). The same fade could
  be applied there with the helper's approach (TFACTOR alpha, deferred, no depth writes).

Probe: `gamerun/qb49_probe.py` (`keys_qb49.sh`, items in `QB_ITEMS`: `booth pickup`), run as
`GTA2_DIRECT_KEYS=1 STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/;
s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> 150 keys_qb49.sh -e GTA2DX9_SCENE_NO_CAR=1`
(add `-e GTA2DX9_NEAR_FADE=0 -e GTA2DX9_PICKUP_LABELS=0` for the before run).

Measured (runs `qb49_before`, `qb49_after`, `qb49_after5`, 8 Nov 2026, plain renderer, loaded
host; the governor paused some runs for minutes, so a few frames were taken mid camera blend):
- Phone box (map 158.5,138.5), first person 0.6 block south facing it: before, its opaque back
  panel covers about half the frame; after, the box is see-through (the phone, the wall and the
  lamp post behind it visible), log `near fade: 3 object(s) see-through, the nearest at alpha
  0.51`. At 0.35 block the existing push-out puts the eye at the same place, same picture.
- Walking north through the box and into the shop front behind it: the box never fills the frame;
  at the wall the eye was stepped back 0.06-0.18 (`wall 0.02-0.14 ahead`), the bricks are seen
  from 0.2 block instead of from inside. A lamp post 0.63 block from the eye showed at the left
  edge (not faded, see above).
- No `FAULT` in any run.

## The reversing turn aside, earlier; the cockpit held round the eye (FIX-INCAR-1, 10 Nov 2026)

- **pfl28, the car boom's turn aside (view_modes.cpp, 8372ddd).** FIX-CAMERA-9's turn tested 1.2 s ahead but the
  look-ahead was capped at 2 blocks (0.7 s at full reversing speed), and the arc over the wall counted as a way out
  while the car closed on it, so the turn tripped ~0.5 s before impact with the boom already collapsed (triage
  tri15_p28). Now: look-ahead to 3.6 blocks; the arc is no way while backing (> 0.3 block/s) or once turned (the
  turn holds until the line behind keeps the pull, so the drive-off no longer swings back over the roof); the eye
  turns about the car with the boom (it eased along the chord through the car); the view's yaw cap admits the
  turn's own step (capped at the car rate the car slid off the frame edge); the side it turned to is kept while
  it reaches half the pull (an angled reverse flipped sides and crossed the blocked line behind); 140 deg/s.
  `GTA2DX9_CAM_CAR_SWING_EARLY=0` restores FIX-CAMERA-9's turn. Probe: `gamerun/keys_incar1_rev.sh`
  (`INI_SED='s/^scene_xy=.*/scene_xy=179.5,181.5/'`, wil: the scene car 4.5 blocks east of a building face, a
  straight and an angled full-throttle reverse into it, 30 fps bursts).
- **tri11 / pfl25, the first-person cockpit (car_bodies.cpp).** The seat correction (FIX-FP-ENTRY) moves the eye
  to the posed body's seat a frame late and eased. Riding a kerb or a slope the game stands the car's sprite up to
  25 degrees (unposed level 0.90) and lifts it up to 0.5 block in a frame, while the eye takes only the sprung
  pitch and roll: wheel, hands and dash left the frame. Now, in first person at the wheel, the drawn own body is
  turned about the seat point by its tilt beyond the eye's (VehicleFxPlayerMotion) and moved so its seat is at
  this frame's eye (at most 0.6 block): the cockpit keeps its place round the eye every frame and the street tilts.
  The hood dash, bonnet and dash cuts are made at the learned seat point, not at the eye measured in the unposed
  frame (that moved with the pose and the correction: the hood dash rebuilt on a dent step at a hit was cut low).
  `[devtools] fp_seat_lock=0` (or `GTA2DX9_FP_SEAT_LOCK=0`) for A/B; `GTA2DX9_LOG_SEAT=1` logs `seat lock:` per frame.

## The armed boom's catch-up, eased (FIX-CAMERA-11, 10 Nov 2026)

- **pfl37** (third person, pistol, a passer-by: the view whipped ~100 degrees in 0.3 s, the hero left the frame and
  returned cropped). He is not turned by the camera: the whip is the QB-6 aim follow, which while firing swings the
  camera round behind his facing on a 0.15 s spring capped at twice `turn_rate_foot` (240 deg/s). When he fires facing
  well off the camera (turned on the spot with the soft follow still waiting, or turned by the game's lock-on) that
  spring closed 100-140 degrees in well under a second; the eased eye cut the chord past him and the shown view trailed
  until he sat at the frame's edge. Now (`ViewCameraSolver::Solve`, the aim-follow branch) the catch-up is capped at
  110 deg/s (33 degrees in any 0.3 s), accelerates at most 440 deg/s^2 (no jerk at the shot), and settles in about a
  second (0.45 s spring). Peds are not obstacles for the boom (a passer-by never swings it); the renderer still leaves
  a figure at the lens undrawn (FIX-CAMERA-6). `GTA2DX9_CAM_AIM_RATE=0` restores the old spring. Log (LOG_CAMERA):
  `cam: aim follow D deg off his facing, turning R deg/s` (twice a second while over 20 degrees off).
- Measured (probe `gamerun/keys_cam11_p37.sh`, `cam11_p37_probe.py`: pistol, plaza, warp beside a ped, third,
  he is turned on the spot with Left/Right and fires five times at once; 30 fps bursts, `cam: pose` per frame, the
  largest yaw change in any 0.3 s window): old spring (`GTA2DX9_CAM_AIM_RATE=0`, run cam11_p37b0) 55.5 / 65.0 / 26.6
  degrees, his box between 0.13 and 0.86 of the frame width; fix (cam11_p37b1) 32.4 / 33.2 / 1.8, his box inside
  0.29..0.54 in every frame (frames opened every 4th, 0.8-2.4 s of each burst). The ped's head at the lens of the
  filer's clip was not reproduced in either run (it came from the chord the fast swing cut; the swing no longer cuts it).
- **pfl28, the angled reverse at a building corner (partial).** DEFECT-TRIAGE pass 198 found 8372ddd's turn aside put
  the lens inside the corner pillar (0.3 s of black frames): the car backed along a wall, the turned eye was rotated
  about the car with no check (FIX-INCAR-1's "the eye goes round with the turn"), and at the wheel the shown eye had no
  berth from the faces beside its line (the on-foot side berth, FIX-CAMERA-5, is on foot only), so it sat 0.0-0.15 from
  the bricks and the near plane cut the wall open. Now (`ViewCameraSolver::Solve`, the car swing and the boom filter):
  the turned eye stays where it is when the mesh stops the line from the car to it; turned aside already, a heading on
  its own side is taken only when the way round to it keeps 0.35 block of boom every 10 degrees; and the in-car shown
  eye keeps 0.25 off every drawn wall (`eyecol::Push`; a lens already past a face is first backed along its line),
  never through anything from the car. `GTA2DX9_CAM_CAR_ARC=0` (the turn) and `GTA2DX9_CAM_CAR_BERTH=0` (the berth)
  restore 8372ddd. Log: `cam: car berth moved M (near N after)`.
  - Measured (`gamerun/keys_cam11_rev.sh`, `cam11_rev.py`, `C11_REV=straight,angled,angledR,angled2`, wil scene car
    at 179.5,181.5, 30 fps bursts; the paths after the first reverse wander run to run, so two runs each): black
    frames (mean luma under 30 below the HUD) base 4 + 3 (cam11_rev3base, cam11_rev6base) vs fix 0 + 0 (cam11_rev4,
    cam11_rev6); frames with the car box over half the frame 42 + 36 vs 12 + 20; frames with the box more than 5 %
    past the left/right/top edge 51 + 53 vs 52 + 48 (unchanged). Frames opened at the same corner (base
    rev6base f72-120: the lens inside the pillar, black; fix rev6: the pillar a grey wall at the left, no black, the
    car close and cut at the frame's left/bottom edge for ~0.5 s).
  - Tried and left out: a cut to the far side when the way round is walled (cam11_rev3: the car turns on the impact and
    the heading cut to is walled a frame later, the eye over the roof for 1.5 s), turning on round to the front while
    backing (cam11_rev2: the look point ahead of the car put it off the frame), aiming from the shown eye when pulled
    short (cam11_rev5: the view lost the car to the sky after a turn).
  - Still short: in a corner pocket the boom stays pulled in and the car can sit cut at a frame edge for about half a
    second; frames past an edge are as many as before.
- **pfl23, third -> first V on foot while firing: the dive through him (dll/src/world_view.cpp).** During the 0.8 s
  move into first person his figure stayed drawn until t = 0.8 (`SetHiddenObjects(nullptr, nullptr)` while the eye
  "is not yet in his head"). From t ~0.45 the moving view already pitches toward the eye's while the eye is still
  ~0.9 behind his head, so his figure sank out of the frame's bottom: 5-7 frames of only his head and the barrel at
  the bottom edge before FIX-FIGURE-10's view model took over (triage tri17_v23 f47-51). Now on foot, from t 0.05,
  his figure is left out (and so the view model drawn) as soon as his feet project below the frame's bottom edge:
  he is whole until the hand-over. `GTA2DX9_MOVE_FP_HIDE_NEAR=0` restores the t < 0.8 rule alone. Log:
  `view: move into first person: his feet at Y of the frame height (eye D from them) at t=T, his figure left out`.
  Measured (FIX-FIGURE-10's `gamerun/keys_fig10_v.sh`: machine gun, plaza, two V presses while firing, 30 fps):
  base cam11_v23b burst 0 frames 46-51 his head alone at the bottom edge, then the gun; fix cam11_v23e and (rebased build) cam11_v23g, both
  bursts, frames 40-63 every frame opened: him whole, then the gun in hands, no head-only and no empty frame. Still: on the
  hand-over frame both are drawn once (his figure is collected before the hide is set that frame; the view model is
  drawn after it), and the in-car third -> first move keeps its own rule (FIX-CAMERA-9 pfl21).
- **feel15, the pistol runs dry (camera half).** The last round fired, the game takes the weapon away and the QB-6
  framing dropped to the unarmed one at once: the camera eased 1.4x further out within about a second of the last
  shot (base cam11_dry0b: 1.53 -> 2.17 block, starting at the emptying), read as a zoom-out at the moment he runs dry.
  Now (`UpdateAim`) standing with the weapon gone inside the 2.5 s firing window, the camera's mix holds until 2.5 s
  after the last shot, then eases out on a 2.5 s time constant (the figure's armed state is the game's: the aim pose
  is FIX-FIGURE's half). `GTA2DX9_CAM_DRY_HOLD=0` restores the drop. Log: `cam: weapon gone T s after the last shot`.
  Measured (`gamerun/keys_cam11_dry.sh`, the filer's repro: pistol, Ctrl every 0.5 s until empty, 30 fps, pose log):
  fix cam11_dry2 no change for 2.5 s after the emptying, then at most 11 % in any second (1.41x in all over ~9 s);
  frames opened across the emptying (base: pulled back within a second; fix: steady, then a slow back-off).
- **pfeel33 residual, first person -> classic while driving: street with no car after the cockpit
  (dll/src/world_view.cpp).** The rise out of the seat leaves at ~0.17 block a frame while FIX-CAMERA-7B's pitch ease
  onto the car's middle starts slowly (0.3 s smoothstep), so for 3-5 frames after the last cockpit frame the roof was
  under (or a sliver at) the frame's bottom edge (cam11_vfpc1, cam11_vfpc2b). Now during that rise the pitch is never
  so high that the car's middle falls below 85 % of the frame height: it follows the rise, which is gradual, so no whip.
  `GTA2DX9_MOVE_RISE_KEEP_CAR=0` turns it off. Log: `view: rise from the seat: pitch A -> B deg to keep the car in the
  frame`. Measured (`gamerun/keys_cam7b.sh CAM6_SEGS=vfpc`, two presses, 30 fps, every frame 1.8-3.4 s opened):
  A/B off (cam11_vfpc2b) 5 frames of street with the roof a sliver at the bottom; fix (cam11_vfpc2) the cockpit, the
  held cab tipping down, then the roof in frame from the first rise frame in both presses.


## The chase view fades a street object at the lens; the death beat under a deck; the first-person exit keeps his facing (FIX-CAMERA-12, 10 Nov 2026)

- **Chase-view near fade (pmt2, `dll/src/map_objects.cpp`).** QB-49's near fade (0.50 block from the
  object's rim, down to alpha 0.18) left the wil plaza phone box (map 158.5,138.5) at alpha 0.3-1.0 when
  the chase lens stood 0.2-1.0 block from it, and its blue frame and panes washed a sixth to a third of the
  frame (triage pass 198: tri18_fc3 11.4 %, tri18_pmt2 shots up to 9 %). In the chase view (the share
  follows the eye's distance from him: 0 under 0.35 block, 1 over 0.85, so a V move eases it and a settled
  first-person view keeps QB-49's values exactly):
  - the range is 1.30 block, down to alpha 0.07;
  - an object whose nearest box corner is no farther ahead than he is and whose projected box covers more
    than 2.5 % of the frame is a foreground occluder: it fades with that share, to 0.15 at 9 % (the box
    a block from a short boom beside him, or between the lens and him); not during a move between views;
  - the alpha is eased per object (out over ~0.05 s, back over ~0.15 s), so neither rule steps it between
    frames (a box corner passing the eye's plane jumped it 0.73 -> 0.15 in one frame before the ease);
  - the booth's lit PHONE sign fades with the box in the chase view (nearest face only, so never mirrored);
    first person keeps it at 0.9.
  `GTA2DX9_CHASE_FADE=0` restores QB-49's values in every view (A/B); `GTA2DX9_LOG_FADE=1` logs one
  `fade: alpha A obj X,Z (range rule R d D) eye ... mix M` line a frame for the most faded object.
  Classic draws no map-object models, so nothing of it reaches the classic view.
- **Death beat in a walled spot (pmq77, `view_modes.cpp` beatcam).** The orbit's start was chosen on the
  shot's mid pose only (74 % clear where the start pose was 18 %), the pull-in floor (0.45 block) left the
  eye behind the wall, and under the ste passage's deck (116.5,123.5, where pmq77's car blew up) the high
  WASTED shot rose into the deck slab. Now: the start search scores the whole path (start, mid and end
  pose, the orbit turned); the eye keeps 0.15 under the first solid cell over him or over itself; and the
  line from the eye actually shown is tested every frame: under half clear for 0.15 s, the orbit is
  searched again round him (24 angles x 3 radii x 2 heights) and cut to the clearest place if it is at
  least 60 % clear, else the beat hands the frame back to the chase camera (eased over ~0.12 s, still
  looking at him). `GTA2DX9_BEAT_CAM_GUARD=0` = before (A/B). Log: `beat cam: ... from the eye N% clear,
  handed back K`, `... cut to D deg`, `... the chase camera keeps the frame`.
- **First-person exit (pfl48, `view_modes.cpp` first person, the boarding ride).** Out of the seat the
  eye rode the exit figure's turn (away from the car, round to shut the door) with its eyes held on the
  door: a ~300 degree sweep along the van's flank to its grille over ~3 s while his facing stayed put. On
  every first-person exit with a boarding plan (ride modes 3 and 4) the view now keeps his facing, with at
  most a glance of under 20 degrees toward the door while he climbs out. `GTA2DX9_FP_EXIT_FACING=0` = the
  old ride turn. Log: `view: fp exit keeps his facing`.

## The driver's body, the wheel's sign and the dashcam (FIX-COCKPIT-BODY, 10 Nov 2026)

Owner items 2 and 3 (`defects/open/owner-fp-cockpit-no-driver-body-and-wheel-counter-rotates.md`,
`owner-feature-dashcam-camera-mode.md`).

- **The wheel "turned the wrong way" (cab_interior.cpp).** The cab turns the rim by `6 x steer`, steer + to the
  car's left (vehicle_fx: `atan(wheelbase * dyaw / ds)`, the sign that steers the drawn front wheels); a + turn takes
  the rim's top toward the car's -x, the screen's left from the seat. The sign was right: with a pale band now at the
  rim's twelve o'clock, run `cb_rec1` (sign flipped as a trial) showed the band going RIGHT on a left turn (heading
  162 -> 47 degrees, turn -1.75), and the original sign takes it left. What read as the wrong way: the rim turned up to
  150 degrees with nothing on it to follow (a three-spoke hub past 90 degrees reads as turning back) while the hands
  slid on it, held to 40 degrees. Now the rim turns at most 100 degrees, carries the twelve o'clock band, and the hands
  (his body's, or the old fists when the body is off) go round with it. `GTA2DX9_FP_ARM_LOG=1` logs the turn per frame
  for the fists, `GTA2DX9_FP_BODY_LOG=1` for the body (compare with the `view: player` heading, `GTA2DX9_STATE_EVERY=3`).
- **The wheel's sign, re-verified (FIX-COCKPIT-BODY-2, 10 Nov).** On HEAD 5c0ee78 the rim still turned the wrong
  way: run `cb2_v1` (keys_cbody.sh, sedan 013, van 068, truck 021), the 30 fps capture of the van shows the twelve
  o'clock band going clockwise from the first frame of the held Left and anticlockwise on the held Right, on all
  three cars. The cab's +x is the screen's LEFT from the seat (with the rim held at +1 rad by
  `GTA2DX9_FP_WHEEL_TURN_MILLI=1000`, run `cb2_t1`, the +x grip rose to the top just left of the hub), so the note
  above had the frame's side wrong. The rim now turns by `-6 x steer` (steer + is a left turn: the log's `turn` is
  negative through every held Left and positive through every held Right, run `cb2_v2`), the top going left on a
  left turn. `GTA2DX9_FP_WHEEL_OLD_SIGN=1` is the 5c0ee78 sign.
- **The driver's body (live_geometry.cpp, model_store.cpp, weapon_rig.cpp).** In first person at the wheel his
  seated figure (the boarding's seated ghost, FIX-SEATED 4393335: his identity record's avatar and clothes, the
  same figure the chase view shows at the wheel) was skipped (and flagged plan-only). It is drawn now: lined up
  with the car's axes, the head's joint 2 cm behind and 9 cm under the eye, scaled about it to the cab (the cab is
  drawn at about a third of the street's scale; the rim's radius against a real 0.19 m first, then per frame the
  scale at which his shoulder-to-grip distance is 0.92 of his arm, at most 0.75 of his own size), the head subtree
  shrunk into its joint (`ModelSetHideHead`, part of the pose cache key). The arms are the avatar's own from the
  shoulders, two-bone IK onto the cab's grips (`CabLastDriverPose`: a quarter to three, the rim's nearest stretch,
  turned with the rim), elbows out; a pose hook (`DriverHandsHook`) closes the fingers (`weaponrig::CurlFists`) and
  turns each hand about the wrist so the knuckles point at the grip. The feet go onto two pedals and the cab now
  has a carpeted floor 0.20 under the eye and a seat cushion under his hips (looking down showed the road through
  the cab). With the body drawn the cab's floating fists (`fp_arm_right`) are not. `[camera] fp_driver_body=0` (or
  `GTA2DX9_FP_BODY=0`) leaves the body out; `GTA2DX9_FP_BODY_LOG=1` logs the gate, scale, reach and joints.
- **The hands grip the rim (FIX-COCKPIT-BODY-2, pfl54 "two fat lumpy blobs hovering over the gauges").** The
  body is drawn bigger than the rim's own scale so his arms reach the cab's wheel (0.61 of his size on the sedan
  against the rim's 0.39, 0.73 against 0.58 on the van), so his hands came out as big as the rim's radius, curled
  into fists whose knuckle line only was aimed at the grip: the rim ran through the backs of the hands. Now
  (`DriverGripHook`, live_geometry.cpp) each hand is turned whole into a grip: the palm on the rim's outer side
  facing the hub, the fingers round its front (the knuckle row along the rim's tangent), closed to 80 % of the
  punch's fist (a fist with a hole), scaled about the wrist to the rim's scale (k = rim scale / body scale), the
  upper arm and forearm thinned by k across their bones (the IK's joints stay put), and the next frame's wrist
  target puts the closed fingers' hole on the rim. The grips sit at ten to two (0.52 rad over the rim's
  horizontal; 5c0ee78 had a quarter to three) and go round with the rim, each held to about 100 degrees of travel
  (past that the rim slides through the hand instead of taking it down behind the binnacle, where it floated over
  the gauges). `GTA2DX9_FP_GRIP=0` is the 5c0ee78 fists; live `[devtools]` keys `fp_grip_tilt` (90), `fp_grip_deg`
  (30), `fp_grip_curl` (80), `fp_hand_scale` (100; 0 = the body's own hand size). Probe `gamerun/keys_cb2grip.sh`
  (`cb2grip_probe.py`: the sweep on the sedan, then held turns on 013/068/021). Runs cb2_g1, cb2_g2, cb2_p54a, cb2_v3.
- **The windscreen frame per body (FIX-COCKPIT-BODY-2, pfl54 "thin flat sticks and a wide roof slab, the same on
  every car; pillars end in the hood").** The header stood 0.02 beyond the windscreen's foot on every class (the
  pillars leaned forward) and each A-pillar was one flat strip. Now the screen rakes per class (the header at
  0.52 of the foot's distance on a sports car, 0.64 a car, 0.86 a van, 0.93 a truck, 0.96 a bus; at least 0.70
  open-top), the header kept at the class's angle over the eye and the rear-view mirror scaled to keep its size
  on screen; each pillar is a tapered post (a face toward the eye in the lining's colour, a darker side toward
  the cabin, a rubber seal on the glass edge and the door frame's edge, a gusset at the foot), standing on the
  cowl (a dark lip along the screen's base between the feet) and joined to the door's top rail: the passenger's
  side now has a door sill and card from the pillar's foot back past the eye like the driver's. The van and truck
  read as near-vertical posts at the frame's edges, the sedan's as raked posts. `GTA2DX9_FP_PILLARS_OLD=1` is the
  5c0ee78 frame. Still short: the class sets the rake (the model's own glass is not read: the cab draws from the
  hood copy's dash line), the header is a flat lining with no visor, the far pillar shows mostly its dark side.
- **The seat in first person (car_bodies.cpp, boarding.cpp).** car_bodies never published the own car to boarding
  from the seat (cpuCut), so a seated figure was let go 6 frames into first person and a climb into the car never
  reached the seat once the eye glided inside. The own car is now published in first person too, except while an
  exit plays from it (`BoardingCarLeaving`): first-person exits run as before.
- **The dashcam (cockpit_mode.cpp, view_modes.cpp).** `[camera] dashcam_key` (default C, free in GTA2's controls)
  switches between the cockpit and a dashcam while at the wheel in first person: no wheel, column, gauge binnacle,
  hands or body; the eye `dashcam_up`/`dashcam_ahead` thousandths of a block higher and further forward and
  `dashcam_centre` percent of the way to the car's middle; no head lean and no body roll (a level horizon; the
  body's pitch and heave stay). The eye eases over 0.4 s (smoothstep) and the cockpit parts give way at the
  switch's midpoint. The choice is kept through a view cycle and a get-out/get-in and only shows in first person
  in a car; `[camera] dashcam=1` starts with it. The two looks are separate flags: the dashcam never changes the
  cockpit's drawing and the cockpit's body never draws in the dashcam. Log lines `cockpit: dashcam (key)` /
  `cockpit: cockpit (key)`.
- **The dashcam is clean (FIX-COCKPIT-BODY-2).** The dashcam sits on the glass behind the mirror: in it the cab draws no
  header lining, no rear-view mirror, no A-pillars and no door mirrors (cb2_v3 `t_dc_dashcam` showed thick posts at
  both edges and the lining across the top; cb2_v4 shows only the bonnet and the road). `GTA2DX9_DASHCAM_FRAME=1`
  draws the frame as 5c0ee78 did. A first-person near pass for the arms cut when looking far down is designed (not
  built) in `defects/assigned/owner-fp-cockpit-no-driver-body-and-wheel-counter-rotates.FIX-COCKPIT-BODY-2-NEAR-PASS-DESIGN.md`.
- **His head and neck from his eyes under Remix (FIX-COCKPIT-BODY-2).** Remix does not cut at the raster's 0.05
  near plane, so a look-down shows the upper arms whole to the shoulders, but the head shrunk into its own joint
  left a pinched skin cone just under the eye that filled the bottom of the frame (run cb2_rmx1). The shrunk head
  now goes to the neck's base and the neck shrinks into it (`[devtools] fp_neck_pct`, 5): a V-neck collar at the
  bottom of the look-down (cb2_rmx4). `GTA2DX9_FP_HEAD_TO_NECK=0` is the 5c0ee78 head. The Remix check of the cockpit
  and the dashcam: `defects/assigned/owner-fp-cockpit-no-driver-body-and-wheel-counter-rotates.REMIX-NOTE-FIX-COCKPIT-BODY-2.md`
  (launcher `gamerun/cb2_remix.sh` = playtest_remix.sh with `RKEYS=keys_cb2_remix.sh`).
- **What still falls short of the bar.** The renderer's near plane is 0.05 block (about 25 cm at the cab's scale):
  his shoulders are always behind it, so looking steeply down (past ~45 degrees) the upper arms end in a flat cut
  where they cross it; a real fix is a separate first-person pass with its own near plane (cab and body together),
  which also needs Remix's capture to accept it. The cab's wheel sits further ahead of the eye than a real seat has
  it, so the body is scaled up to reach it and the hands read a little large against the rim. The hands are the
  avatar's mesh posed by a fist curl and a wrist turn, not hand-authored grips. Remix: the body uses the ordinary
  figure draw (unverified under path tracing in this pass).
- Probe: `gamerun/keys_cbody.sh` (`cbody_probe.py`, copies in `linux/docker/`; F11 scene car, `CAB_MODELS` forced
  before he gets in, out and in again so the boarding seats him; per model: still, a held left, a held right, a full
  lock, a mouse look down; `DASHCAM=1` adds cockpit -> dashcam -> V cycle -> out/in -> cockpit). Run with
  `GTA2_DIRECT_KEYS=1`, `GTA2DX9_SCENE_NO_CAR=1`, `GTA2DX9_STATE_EVERY=3`.

### The hands hold the rim hand over hand; each arm keeps its own grip (FIX-DRIVER-GEOM, 10 Nov 2026)

pmab1 and pfl71 were regressions of 5c0ee78 (its grips and arm assignment); cd5bb11 (FIX-COCKPIT-BODY-2) gave the
fists a real grip round the tube and a hand's size, and let the lower hand slide at -0.2 rad, but the upper one still
followed the rim to 2.3 rad. Measured on HEAD with `gamerun/keys_dghands.sh` (warp, F9 into the parked car, first
person, `[devtools] force_steer_deg` 0, +-4, +-8, +-12, +-17 held 3 s each, then two drives into a wall with a turn
held), run dgh_head: from 8 degrees of steer (about 50 degrees of rim) one fist rode onto the rim's top (on the van
068's and the fire truck 017's flat wheel, the stretch nearest the eye: a palm as wide as the gauges) and the other
went to the frame's bottom edge (A-Type 042) or down over the gauges.

- **Hand over hand** (cab_interior, the grips): each hand holds the rim at its own place and turns with it while it
  stays in its arc, 0.30..1.05 rad over the rim's horizontal on its own side; leaving it, it lets go and takes the rim
  again at home (ten to two, `fp_grip_deg`) over 0.22 s, a little off the rim on the way. One hand moves at a time,
  each at most every 0.35 s; one waiting is held at its arc's end; near the middle a hand away from home goes back.
  The arc was found on three classes (dgh_4: -0.30..1.35 left the 042's low hand out of the frame and the van's high
  fist a flat palm; dgh_5: 0.05..1.05 left a drooping palm over a flat wheel's gauges). `GTA2DX9_FP_REGRIP=0`: cd5bb11's
  grips. `GTA2DX9_FP_GRIP_LOG=1`: the grips every 10th draw; every regrip is logged (`cab: regrip hand ...`).
- **Each arm keeps its grip** (live_geometry): which arm takes which grip was chosen from where the grips were that
  frame, so a turn that carried one past the other (a steer spike off a wall) swapped them: the left arm dropped to the
  low grip on the gauges as a stub and the right reached across, its wrist twisted see-through (pfl71). Now from each
  grip's home side (`CabDriverPose::grip0Right`).
- `[devtools] force_steer_deg` turns the cab's wheel too (d7be9a8), for fixed-lock frames of a stopped car.
- Verified on the final build (private stage, fbea4df..d7be9a8 with cd5bb11): dgh_7 (30 fps): both hands on the rim at
  every lock on 042, 068 and 017 and through the wall impacts of b_dgh_crash_42/68/17.mp4; dgh_ste (SWAP_LEVEL=ste,
  NOWARP=1: the pmab1 convertible 044) every lock and its crash clip; the filer's pfl71 probe (dg_pfl71b, keys_pfl71.sh,
  18 impacts): no swap, no stub, no see-through hand. The regrip's lift is outward only: toward the eye it met the 0.05
  near plane on the van's flat wheel and was cut open, see-through (dg_pfl71), the look pfl71 filed.
- Still short of the bar: a hand mid-regrip (0.22 s) or held at its arc's end on a flat wheel can read as a large flat
  palm for a few frames (van s-8 in dgh_7, truck s8; about 4 of 27 frames at 3 fps in dg_pfl71b while the car is pinned
  against the wall and the steer is noisy); hands shuffle often on a long turn; the fists are the avatar's
  curled hand, not an authored grip; at s4/s8 on the 017 the cockpit was not drawn in the probe (seen on HEAD too, not
  a hands issue, not chased).

## The player is not a recycled ped; round a car that hides him; the car kept in frame at the wheel (FIX-CAMERA-13, 10 Nov 2026)

- **pmv10, first person "at the wheel" with no cab for 33 s after a BUSTED (view_modes.cpp `LocatePlayer`).** After
  the arrest the game frees the hero's ped and soon hands the same struct to a new pedestrian. In run pmv10a_bil the
  new one (ped 269, occupation 23, a medic) was driving an ambulance away 0.4 s later, and the locator's
  "driver of a car" fallback (the last player ped named by a car's driver word) took it for the hero at the wheel.
  The views followed a stranger's ambulance for 33 s. First person drew no cab because the hero's car was not the
  one being followed, and the scan that finds the real hero at the station never ran, because the fallback
  already had a ped. Now the fallback also checks the ped's id word (+0x200, the id the `view: peds` lines print)
  against the one the slots last saw on him (the hero's is 1 in every run measured). A struct holding another id is
  dropped (`view: the player's last ped struct now holds ped N (occupation O), not him`) and the scan finds him
  again. `view: player ped id N (was M)` logs each change of the remembered id. `GTA2DX9_PLAYER_ID_CHECK=0` turns
  the check off (A/B).
  - Seen once in all run logs on disk (pmv10a_bil). Three tries at a real arrest (cam13_bust1: F10 car,
    cam13_bust2: force_wanted=3 at the wheel, cam13_bust3: force_wanted=2 on foot; 60-90 s each) got none, so the
    recycled-struct case is argued from the filer's log, not filmed. Regression: the filer's keys_pmv10.sh drive on
    this build (cam13_pmv10): ped id 1 throughout, no rejection line, and the cab (dash, wheel, hands) is drawn in
    every first-person frame.
- **pfl28 residual: the car kept in frame at the wheel, the lens guard, the drive-off cut (partial; view_modes.cpp
  `ViewCameraSolver::Solve`).** Three parts:
  - The car frame clamp: at the wheel in third person, the drawn body's footprint (8 corners, `LiveCameraCars`, the
    same box the `cam: pose ... box=` line logs) stays inside the middle 90 % of the frame's width, measured from the
    eye that is shown. The yaw moves only as far as the box needs; a box too wide for the frame is centred. The pitch
    moves only up, so the top edge clears the roof, by at most 8 degrees and only with every corner 0.6 or more ahead
    of the lens. The chase framing keeps the near bumper under the bottom edge by design. Log: `cam: car frame clamp`.
    `GTA2DX9_CAM_CAR_FRAME=0` turns it off.
  - The lens guard: backing with the wheel over along a wall, the car's rear corner swept into a lens the wall held
    while the line straight behind still reached the pull. When the eye's gap to the car's footprint closes fast
    enough to reach 0.1 within 0.3 s, the turn aside is looked for at once and held for 0.8 s while it still backs.
    Log: `cam: car at the lens`. `GTA2DX9_CAM_CAR_LENS_GUARD=0` turns it off.
  - The drive-off cut: turned past 100 degrees, the eye is ahead of the car. Driving forward (over 0.3 block/s)
    with the line behind reaching half the pull, it cuts to behind the car instead of easing back over 0.8 s into a
    car driving at the lens. Log: `... cut to behind`. `GTA2DX9_CAM_CAR_DRIVEOFF_CUT=0` turns it off.
  - Measured with FIX-CAMERA-11's probe (`keys_cam11_rev.sh`, `C11_REV=straight,angled,angledR,angled2`, wil scene
    car at 179.5,181.5, 30 fps bursts, LOG_CAMERA=1). The metric is over the pose lines of the four bursts: frames
    with the box more than 5 % past the left/right/top edge, and frames with over half the frame covered. HEAD: 53,
    48, 45 (FIX-CAMERA-11's cam11_rev6base/6/7) and 64 (cam13_rev1base); over-half 36, 20, 34, 29. This build:
    cam13_rev5 19 / 19, cam13_rev6 1 / 15, cam13_rev7 31 / 36. Runs with the angled reverse first are clean on both
    builds (cam13_rev2, cam13_rev2base: 0 / 0).
  - Still short (frames opened): the car backing into the corner pocket can still put its canopy over the lower
    frame for ~0.5 s when the guard trips late (cam13_rev7 angled f81-98). After the drive-off cut the boom can stay
    pulled in along a wall for ~1 s, with the car's rear cut at the bottom edge (cam13_rev7 angled2 f121-147). In
    cam13_rev6 the turn to the car's nose in the pocket shows the car whole in every frame.

## The car against a wall beside it; the drive-off cut lands where there is room (FIX-CAMERA-14, 10 Nov 2026)

- **pfl28 residual: the boom's pivot moved off a wall beside the car (view_modes.cpp `ViewCameraSolver::Solve`).**
  Backing with the car's flank scraping a wall (wil x=182.0: the car's middle 0.23 from the bricks, run cam13_rev8
  angled2), every line out of the car's middle runs inside the lens berth (0.25) of the wall: the solve wanted a boom of
  0.22-0.35, the shown eye sat on its 0.57 minimum and the car's rear hung past the bottom edge for ~2 s (pose-line box
  bottom 1.4-1.98 of the frame height, f88-144). The pivot the boom is solved and shown from now moves level off every
  drawn surface out to 0.5 block (at most 0.4 block, never through anything, never into a solid cell), out over 0.1 s
  and back over 0.5 s, so the boom runs clear of the wall and keeps its length. Log: `cam: car pivot off the wall`.
  `GTA2DX9_CAM_CAR_PIVOT_SIDE=0` turns it off (A/B).
- **The drive-off cut lands where there is room.** With the car's rear against the wall it had backed into (wil
  x=187), the line behind reached 0.45 of a 0.86 pull, FIX-CAMERA-13's half-pull test passed and the cut landed 0.2
  behind the car's middle: four frames with the lens inside the car (cam14_rev1 angledR f1152-1157, box 5.7 x 19.5
  frames). The cut now goes to the smallest turn with the whole pull: behind first, then side-on out to 100 degrees
  (its own side first); only when none has it, behind at half the pull as before. Log: `... cut to N (behind reaches
  ...)`. `GTA2DX9_CAM_CAR_CUT_ROOM=0` restores FIX-CAMERA-13's cut.
  - Metric (`gamerun/cam14_box.py`: CAMERA-13's cam13_box.py plus frames with the box bottom past 1.3 of the frame
    height, the rear cut at the bottom edge, and "lens" frames with the box wider than 1.5 frames or deeper than 2.5)
    on `keys_cam11_rev.sh` `C11_REV=straight,angled,angledR,angled2`: past-edge / over-half / bottom / lens. HEAD
    fbea4df cam13_rev8 13/12/109/6, cam13_rev7 31/36/72/15; same build, both switches off, cam14_rev3base 14/0/26/8;
    the pivot alone cam14_rev1 13/12/42/7 (angled2 62 -> 0 bottom frames; its angledR 35/7 = the cut, fixed next);
    both cam14_rev2 0/0/0/0, cam14_rev3 0/0/0/0. Paths wander between runs (not same-spot).
- **The lens cut and the hold after a cut (second commit).** Backing at 3 blocks a second toward an eye turned to 140
  degrees, the lens guard tripped with the gap 0.49 closing at 3.1/s; the turn (140 degrees a second, 2 blocks a
  second at the lens) could not get away, the side it looked for flipped +-80 frame to frame, and the lens slid over
  the car's flank for 9 frames (cam14_rev4 angled f902-910). When the car will reach the lens within 0.15 s and a turn
  with the whole pull lies more than 30 degrees away, it cuts there. Log: `cam: car at the lens: cut A -> B`.
  `GTA2DX9_CAM_CAR_LENS_CUT=0` turns it off. After any cut (this one or the drive-off cut) the turn holds where the cut
  put it for 1 s unless that heading loses half the pull: the car driving off along the x=186 wall with its middle 0.28
  off it was cut to behind at half the pull, the turn set off again toward the wall the next frame and the eye sat on
  the wall's berth 0.45 behind the car for ~1.5 s, the lens on the car (cam14_rev8 angled f867-899: 58 past-edge, 49
  lens frames). Log: `cam: car swing held`. `GTA2DX9_CAM_CAR_CUT_HOLD=0` turns it off.
  - Only a turn that sets off again is held (|want| growing or the other side): a hold at -40 kept the eye on a wall's
    berth while the car drove off with the line behind open (cam14_rev11 angledR f117-205). One cut at a time: no cut
    within 0.6 s of the last, and the drive-off cut's side targets end at 80 degrees (a cut to 100 passed the > 100 test
    again and cut every frame, cam14_rev10).
  - With all four parts: cam14_rev9 0/0/0/0 (both cuts fired: the lens cut 19.5 -> 60 and 47 -> 140, the drive-off cut
    to -60 with the hold); frames opened (every 5th frame of angled and angledR): the car whole in every tile, each cut
    a single cut to a side-on view. vreg stage_cam14 31 PASS, spawn_classic 0 of 144 tiles (cam14_vreg2).
  - Runs on a GPU shared with a Remix take ran at ~11 fps (cam14_rev6/7: 400 pose lines instead of ~3800) and the
    scripted reverses did not reach the walls: not counted.
  - Final build cam14_rev12: 14/0/25/10, all in angledR f71-95: the car stopped in a corner (its middle on the x=186
    wall line) and spun in place after the impact; the line behind closed from 1.06 to 0.36 as its heading turned, the
    rig followed the heading and the turn went over the car for ~0.5 s. Not fixed: the rig should hold the world
    heading while a stopped car spins (a change to the chase yaw, not to these parts).
  - Still short: paths wander per run, so no same-spot A/B; the filer's plaza-corner van case (tri15_p28, keys_pfl28.sh)
    is not re-reached by this probe; a cut is a cut (an AAA chase rig would blend 0.2 s), and the car in a dark pocket
    after the side cut reads small.

## The beat's hand-back at the wheel in first person; warp probes and the game's camera (FIX-CAMERA-15, 10 Nov 2026)

- cam14-fp-at-the-wheel-beat-hand-back-fades-in-with-no-cab-wheel-or-hands-for-0p7s: a BUSTED or WASTED beat
  (beats.cpp) lasts 0.9 s past its hand-back: its camera share is already 0 and the first-person eye back in the
  seat while the picture fades in from black. The own car and figure were hidden from the seat only once the beat
  had ended (`!BeatActive()` in world_view.cpp), so for ~27 frames the car was drawn whole round the seat's eye
  (the bare bonnet, no dash, wheel or hands), then the whole cockpit popped in. Now the beat holds the own-body
  gate only while its camera share is above 0 (or in its first 0.5 s): from the hand-back the car is drawn from
  the seat (`seat gate ... own=1` from the first hand-back frame, run cam15_bust2; before: own=0 for 0.9 s, run
  cam15_bust1). Probe: gamerun/keys_cam14_bust.sh (forced BUSTED at the wheel, [devtools] force_big_message).
  `GTA2DX9_CAM_BEAT_SEAT_HIDE=0` restores the old gate (A/B).
- qaexp5 (third person, the Downtown fire truck at the fire station "camera inside the body for 9 s") was a probe
  artefact, not the camera: after an F9/F10 warp the game's own top-down camera scrolls to the player at about
  6 blocks a second (`cam[N] bounds=` lines, every 64 frames), and the game submits no sprite outside its window,
  so no car body and no figure reach the renderer until it arrives (190 blocks: 20 s). The eye stood 1.4-1.5
  blocks behind the 1.92-block truck's centre, outside it. gamerun/cam15_fire.py waits for the bounds to hold the
  player before boarding: the truck is drawn in every frame from the boarding to the drive-off. Any probe that
  warps must settle the game camera this way before filming cars or figures.
- pfl28 residual (a car stopped in a pocket): pinned at a building's corner or turning in place against a wall, the
  car leaves the chase eye no place behind it; the walls and the car berth put the shown eye over the car's own body
  (0.2-0.5 from its centre), raised a block but capped at 35 degrees down, so the car sat under the frame's bottom
  edge or out of the frame for up to 0.5 s (cam14_rev12, tri32_rev; cam15_pk2: the frame held only pavement). Now,
  when the shown eye is nearer the car's centre than half its length plus 0.45 and the car is slow (under 2 b/s,
  full under 1), the camera cranes up over the car (to 0.9 + half its length over the roof, as far as cells and the
  mesh over it are open) and looks down at it past the 35 degree cap (to 80), eased in over ~0.12 s and out over
  ~0.5 s. Log: `cam: car pocket <share> lift <l> flat <d> (need <n>) pitch <deg>`. `GTA2DX9_CAM_CAR_POCKET=0` turns it
  off (A/B). Probe: gamerun/keys_cam15_pocket.sh (cam15_pocket.py: warp, settle the game camera, F10 scene car at
  wil 187.5,197.5, reverse into the building behind with the wheel over, shuffle, drive off; INI_SED
  scene_xy=186.0,200.4) and keys_cam11_rev.sh, both measured with gamerun/cam14_box.py (past-edge / over-half /
  bottom / lens). Before (cam15_pk2) 30/22/98/39; after (cam15_pk3) 0/1/50/0; the four wall reverses (cam15_rev1)
  0/1/17/0. The paths still wander per run (the pocket is reached at a different spot each time), so these are not
  same-spot A/Bs. Short of AAA: in a pocket the view is a steep look-down (55-75 degrees) rather than a chase view; an
  AAA rig would pass the lens through the building or fade it.
- pfl65 camera half (a parked vehicle between the lens and him on foot): the chase lens trailing him past a parked
  truck stood behind it, and the truck hid him whole for as long as he stood there (cam15_occ9base: every sampled
  frame for 5 s). FIX-CAMERA-14's unshipped rise (gamerun/cam14_carrise_wip.patch) is now in, changed in two ways:
  only cars standing or creeping (under 0.6 b/s, measured per car from its footprint frame to frame,
  `CarMotionUpdate`) count, so a car passing in traffic is not craned over; and the test is asked of the eye with
  the wall's lift only, not of the risen eye (from the risen eye the car no longer hid him, the hold ran out and the
  lens came back down behind the cab, cam15_occ6). When such a car crosses the line from the eye to his chest for
  0.3 s, the boom rises on its arc (same length, up to the on-foot 45 degrees) to the smallest lift that sees his
  chest, else his head; kept 1 s after, then eased down. Log: `cam: car hides him (<s>): rise <deg>`; with
  GTA2DX9_LOG_CAMERA=1 also `cam: car hides him from the eye` per frame (a line test from the solve's eye, not the
  shown one: it over-counts). `GTA2DX9_CAM_CAR_RISE=0` turns it off (A/B). Probe gamerun/keys_cam15_occl.sh
  (cam15_occl.py: the parked Downtown fire truck at wil 5.5,26.5 drawn as the 007 box truck via INI_SED
  force_car_model=7, him warped 0.9 beside its flank, the game camera settled, turned away from it with a
  self-calibrating turn (feel_probe's face turns mirrored under direct keys), a step away and back so the lens
  trails behind him across the truck). Frames (2 fps, 20 tiles): rise off, hidden in 15 of 15 tiles after the
  swing; rise on (cam15_occ8), seen over the roof in 15 of 15. Frame times unchanged (game 2.4-2.8 ms avg vs
  2.3-2.7). The renderer fade of the occluding car (a depth pre-pass in car_bodies.cpp) was not built: the rise
  shows him on this probe without touching the car draw. Short of AAA: he is seen over the truck's roof from up to
  45 degrees, small at the far edge of the roof; a moving car that stops beside him is craned over only once
  measured still (~1 s); a truck crossing slowly at under 0.6 b/s still counts as standing.

## Trees and the chase boom; warp probes hide the hero (FIX-CAMERA-16, 10 Nov 2026)

- qav5 (wil park, third person on foot: a tree's trunk and a bare branch filled the lens, the hero hidden). The
  street props' trees (DrawProps: the map's tree blocks and the park trees, models tree_01..03) were unknown to the
  camera: not in eye_collision's mesh, not in the street objects the boom keeps clear of. Now DrawProps hands the
  trees within 12 blocks of the player to view_modes (`SetChaseTrees`: foot point, height, crown radius = half the
  model's width, trunk radius 0.12 x scale) and on foot:
  - the trunk is a street object (`GatherObstacles`, flag `tree`) up to the crown's top: the shown boom stops short of
    a trunk on its line (`cam: prop on the boom ...`), pulled in at 4 blocks/s at a tree (about 0.3 s for the usual
    1.2 block; the street objects keep 9), never hopped over (the hop over a low object would put the lens in the
    crown), and the eye keeps the berth off it;
  - `ChaseTreeAlpha` fades a tree (the props' overlap-fade state: gone or whole over ~6 frames, held 0.4 s after the
    last reason) whose crown holds the lens (from 45 % of its height up, out to its radius + 0.3), whose branch rods
    are round the lens (30-45 % of its height, within 0.8 of the crown radius), whose trunk stands within 0.45 of the
    lens, or whose trunk or crown still crosses one of the lines from the lens to his feet, chest and head. Log
    (GTA2DX9_LOG_CAMERA=1): `cam: tree faded (<why>) at x,y h crown trunk, eye ...`.
  `GTA2DX9_CAM_TREES=0` turns both off (A/B). First person and the cars are untouched (the player's body is already
  kept out of the trunk by prop_collision). Probe: gamerun/keys_qa_cam16.sh + cam16_spots.py (CAM16_SPOTS="x,y;...":
  warp, wait for the game camera's bounds to hold him, classic, third person through 8 headings, three short walks).
- pfl28 1w4 residual (a car pinned along a wall: the hard cut to the side-on view parked the lens 0.25 from the
  building's corner, a dark, magnified near-plane slab down the left of the frame for ~3 s; DEFECT-TRIAGE tri37_pk):
  the car berth (FIX-CAMERA-9's `cam: car berth`) keeps the chase lens 0.4 off every drawn wall, was 0.25.
  `GTA2DX9_CAM_CAR_BERTH_R` (blocks, 0.25 = before). keys_cam15_pocket.sh, measured by the clearance line and
  gamerun/cam14_box.py: before (cam16_pk0) nearest surface 0.252, past-edge/over-half/bottom/lens 2/0/42/1, the
  corner a dark band down the left 10-15 % of the side-on frames; after (cam16_pk1, cam16_pk2) nearest 0.389 / 0.396,
  0/0/20/0 and 0/0/0/0, the pinned side-on frames with the wall at a normal distance. In a tight pocket the wider
  berth cost the lens room from the car (cam16_pk3 pin: the eye held 0.9 from its centre, 3 past-edge / 9 over-half
  frames as the crane began), so the 0.4 berth is taken only where it keeps the lens as far from the car as 0.25 would,
  or beyond the pocket's reach (half the car's length + 0.75): cam16_pk4 0/0/0/0 with the crane engaged. The pocket
  each run reaches varies. At the wheel the tree fade's line runs to the car (cam16_pk1: the game drove the car through a park
  tree's trunk, which cut it in two).
- qaexp8 (ste: riding the elevated train the 3D views lost him: camera on the platform, classic fallback, floor and
  girder close-ups). Aboard a train the game keeps no player ped (`player not found` for the whole ride) and its own
  camera rides the train. LocatePlayer now returns him as the train's rider: when the normal lookups fail and the
  game's camera is on a train (vehicle models 59-61, within 3 blocks) that he was beside when last found (4 blocks,
  20 s), that carriage is his vehicle (as a car he drives: placement, facing, sprite; no ped), kept while it is a live
  train within 18 blocks of the game's camera (which leads a train at 8 b/s by ~10 and zooms out), never another
  carriage; while riding, a passer-by at the camera is not taken for him. The position and height come from the
  train's body as drawn the frame before (log once a second: `view: train ride: body drawn at ..., placement ...`).
  Logs: `view: the player rides train <ptr> ...`, `view: the train ride ends (...)`, source `rider of a train at the
  camera`. `GTA2DX9_CAM_TRAIN_RIDE=0` turns it off (A/B). Probe gamerun/keys_qa_cam16_train.sh + cam16_train.py (ste:
  warp onto the east platform, settle, Return every 3 s until aboard: the train runs a loop and is not always there;
  then third / first / classic / third). Runs cam16_tr5/tr6: followed from boarding to the end of filming (~45 s,
  two corners at speed), third person behind and above the carriages, first person the cab (dash, hands, the line
  ahead through the window). Still short: where the line runs into a tunnel (the train's body at z 2 or 1 under the
  park, The Village) the chase eye stays above the tunnel's roof (a lawn frame) or in its wall for a moment: the
  in-car boom does not dive into a tunnel after the car.
- qav18 (bil south edge under the truss deck, and the alley at 240.5,4.5: "hero not drawn in any of 8 headings") and
  the hidden hero in qav5's own recipe were the warp artefact of FIX-CAMERA-15's qaexp5: the filers' third-person
  frames were all taken before the game's camera had scrolled to him (bounds reached him 13-45 s after the warp),
  and the game submits no sprite outside its window. Settled (cam16_spots.py), the hero is drawn in every heading
  at both bil spots, except the very first frame after a warp before he has moved (the post-warp "no sprite until he
  moves" state; the pose line then has him centred in the box with a clear line).

### No see-through fists at full lock or on a wheel near the eye (FIX-DRIVER-GEOM-2, 10 Nov 2026)

The owner demo's dependency run (pfl71 recipe on the a0dcb09 stage: the 068 van driven into a wall twice, then a held
Left and Right against it) showed both fists as tan, balled, see-through shapes with the rim and gauges visible
through them during the held turn. Reproduced on HEAD 05c78dc (run dg2_rep1, 6 fps strip): the hand moving or held
at its arc's end on the rim's top. The steer was not the cause (the rim went to -1.75 on the held Left and +1.75 on the
held Right, as it should); `cockpit: arms as drawn` put that wrist 0.050 ahead of the eye, on the 0.05 near plane:
the fist was cut open. Two things took it there on a raked wheel (van, truck): the rim's top is its stretch nearest
the eye, and a0dcb09's regrip lifted the hand radially outward, which at the top is toward the driver. On the 042
A-Type (a steep wheel close to the eye) both wrists sat at 0.050..0.052 even at ten to two, and a hand at 1.0 rad
was a pale ball (dg2_dgh1).

- Each hand's arc ends where its grip would come nearer the eye (along the car's forward) than its home grip by
  more than 0.003 block (`cab: grip arc 0.30..0.65` on the 068, 0.70 on the 017, unchanged 1.04 on the 042).
- A regrip lifts the hand along the column, away from the eye, not radially.
- live_geometry reports where each wrist was put (`CabReportWristFwd`); a hand whose wrist came within 0.0495 of
  the eye above its home ends its arc there for the seat (`cab: hand N wrist ... its arc ends at`).
- The wheel (rim, hub, column) moves along its column, away from the driver, by what the seat needs to put the
  nearer wrist 0.058 ahead of the eye at home, learned while both hands are at home, eased, at most 0.012
  (`cab: wheel moved`): 0.0077 on the 042, 0 on the 068, 0.002 on the 017.
- `GTA2DX9_FP_GRIP_NEAR_OLD=1`: a0dcb09's arc, radial lift and no wheel move (A/B).

Verified: dg2_fix3 (the demo2_dep recipe, 162 samples at 6 fps through both impacts and the held turns: both hands
opaque and on the rim in every sample), dg2_dgh3 (dghands probe: locks 0/+-8/+-17 and wall crashes on 042, 068,
017). Not this change: with `[visuals] enabled=1` the post pass's shadow mask/AO reads the dash behind his forearm,
so a forearm crossing the dash's top edge shows a faint band of the dash's shading (gone with visuals off, run
dg2_nv1); filed for the visuals owner. The 017 draws no cab at +8 degrees of forced steer (filed separately).

**Stand-in fists held back at a seat's start (FIX-DRIVER-GEOM-2, qaf3).** The cab is built before the figures in a
frame, so on the first seat-view frames his body had not been drawn yet and the cab's stand-in fists (fp_arm_right,
the pfl54 fat lumps) showed for a sample (V pressed 0.3 s after Return on the van; also the first cab frames of the
cbody probe, dg2_cb1 t_cb_013_still). They are not drawn in a seat view's first 0.6 s; where his body never comes
(no avatar, driver body off) they come back after that. `GTA2DX9_FP_STANDIN_HOLD=0`: no hold. Runs: qa_dg2_qaf3
(tile 2 now the cab without hands while he is still boarding, tiles 3-7 his arms on the rim), dg2_cb2 (013 and 021
cab arrival at 12 fps: his body's hands from the first cab frame).

### One cab per vehicle class from the identity record: the tank's slit and levers, the bus in its paint (FIX-COCKPIT-CAB-3, 10 Nov 2026)

qaf1 (the wil dock tank's first-person seat was the sedan's: a thin wheel, three round gauges, a car's A-pillars)
and qaexp6 (the Karma bus's seat: the sedan dash under a flat pale-white header and white pillars, the bus yellow in
the other views). The cab class now comes from the vehicle's identity record: `IdentityCabFor(model)` in
identity.cpp owns the per-model table (sedan, sports, van, truck, bus, tank, and the open-top flag; it was two
lists in cab_interior.cpp), `IdentityRecord::cab` carries it, and `CabClassFor` / `CabOpenTop` read it (a measured
flat front still makes a bus, never a tank). Adding a vehicle means one table entry.

- **Tank (054).** The driver looks out through a wide slit: the hatch coaming at the dash line, 0.12 ahead of the
  eye; a deep armour brow over it, its lower edge 15 degrees over the eye and arched toward the sides like a hatch
  rim, with a round steel lip and a rivet row; thick armour cheeks either side (the pillars at 0.030/0.034). Coaming,
  brow and cheeks are the hull's own paint on an armour-plate surface (texture kind 6: worn coat, weld seams,
  rivets). No wheel, no binnacle, no mirrors, no vents, no glovebox: two steering levers from boots on the floor to
  rubber grips a hand's width either side of the eye, and two small gauges on a panel to the right. A left turn
  (+ steer, eased like the rim) pulls the left lever back up to 0.008 and lets the right one forward 0.003. His body's
  hands take the grips through `CabLastDriverPose` (each grip a stretch of "rim" running up the lever: the fist
  holds it as it holds a wheel at three o'clock); no stand-in fists (`g_wheel` unset). Log: `cab: tank levers, pull`.
- **Bus (011, 086, the trains).** The header and the pillars' faces in the body's own paint (luminance held
  0.36..0.62), painted metal instead of the headliner weave.
- Warp probes and the cab: `gamerun/cab3_dgh_probe.py` is dghands_probe with the game camera settled after the
  warp (tri-fp-fire-truck-017: the "no cab at steer 4 and 8" frames were taken before the game camera reached him,
  so the game submitted no sprite for his truck; settled, every steer step draws the cab). `gamerun/cab3_seat.py`
  (`keys_cab3_seat.sh`, PROBE_X/PROBE_Y/TAG): warp, settle, board, first person still/left/right/drive, third.

### The seat lock through a hard hit, the rim from the steering keys (FIX-COCKPIT-CAB-4, 10 Nov 2026)

* **Seat lock cap (qar7 O2i).** In a hard wall hit the game can move the car about 0.65 block from the eased
  first-person eye within one frame (logged as `fp seat eye follows the tilted body 0.647`). The seat lock
  (FIX-INCAR-1) moves the drawn own body so its seat sits at the eye, but it capped that move at 0.6 block.
  For the two frames over the cap the cockpit stood about 0.05 block off the eye: the eye sat under the dash,
  and the rim and hands were seen from below (the filed "blob / flat slab" hands). The cap is now 1.5 block;
  `GTA2DX9_FP_SEAT_LOCK_MAX=<milli>` sets it for A/B (600 = before). `GTA2DX9_LOG_SEAT=1` logs each frame's
  `seat lock: ... (len L)`.
* **Rim and levers from the game's steering keys.** `view_modes GameSteerKeys()` returns the Left/Right the
  game is told this frame: the camera-relative controller's injected keys, else what the device reported,
  else the physical arrows before the DirectInput hook is installed (it goes in late with `nav_map=0`). It
  returns 0 during the knock-down hold. While a key is held, the cab's steer eases to a 0.45 lock that way
  (+ = left; the cab's +x is the screen's left). On release it hands back to the measured steer (yaw over
  distance). So a stopped car turns its rim, a car pinned against a wall no longer flips it, and a tank
  pivoting in place pulls its levers. Log `cab: steer keys Left|Right|none`; `GTA2DX9_FP_KEY_STEER=0` turns it
  off. Probe: `gamerun/keys_cab4_steer.sh` (stopped 2 s holds, then holds while driving).
* **The look-down near plane (owner O2g).** His shoulders sit about 0.045 block from the eye, inside the
  0.05 near plane, so looking down the arms ended in the plane's cut; looking straight down, forearm fragments
  floated at the top of the frame. In first person in a vehicle the near plane eases from 0.05 to 0.028 between
  28° and 42° of look-down. By then the frame's top edge is at the horizon, so no distant depth precision is
  lost. From 42° to 72° (straight down) it eases back out to 0.030, which still clips his collar and chin
  under the eye. Sweeps showed a chin sliver at 0.020-0.028 and an arm cut into a floating elbow at 0.034+.
  Every other view keeps 0.05. `GTA2DX9_FP_NEAR_LOOKDOWN=0` turns it off; `[devtools] fp_near_min_milli` and
  `fp_near_deep_milli` set the two floors live; the log line is `view: near plane`. Probe:
  `gamerun/keys_cab4_near.sh` (the in-car mouse look recentres within ~2 s, so it looks down and shoots at
  once; `NEAR_KEY`, `NEAR_FLOORS`, `DEPTHS`). Residual: around 30° the end of a forearm can still meet the
  0.05 plane inside the frame; straight down, a thin sliver of neck shows between the collar's edges. Remix
  ignores the near plane, so its look-down does not change.
* **The post pass skips the cockpit's AO and hemisphere (qav12, dg2 forearm band).** At dawn the
  first-person bonnet read 0.75 of the same paint in third (bil 06:45, 046: 62 vs 83 luma), mottled. The
  bonnet's own light was not the cause: bending its normals up or lighting it on the CPU moved the mean by
  under 2 %. The cause was ps_composite's AO and hemisphere tint, whose normals are rebuilt from the depth
  buffer and are noise at the cockpit's range and grazing angles. The same terms laid the dash edge's
  crease over the forearm. world_view hands the post the cockpit's reach (0.6 block, `cUpView.w`) in first
  person at the wheel, and nearer pixels take no AO and no hemisphere. The shadow mask stays, so a wall's
  shadow still falls on the bonnet. Result: dawn 62 -> 68 against 83 in third (0.82), noon 79 -> 87.5
  against 87; the forearm is one colour over the dash edge in the held turns. `GTA2DX9_FP_POST_REACH=<milli>`
  (0 = the old composite). Probe: `gamerun/keys_cab4_bonnet.sh` (stopped car, third then first per hour,
  `CAB4_TOGGLES` live ini sweeps). `src/shaders/visuals_gen.h` was rebuilt by `tools/build_shaders.sh` with
  `SHC_IMAGE` set to a plain Ubuntu 25.10 Wine 10 image (`linux/docker/Dockerfile.shc-wine10`: `apt-get install wine
  wine32:i386 wine64`), because gta2-wine2510 is not on the 8x L4 host. That image reproduces HEAD's
  `visuals_gen.h` byte for byte from the unchanged HLSL.

### The seated hero kept through a stranger's jack; no stand-in fists while his body is on (FIX-COCKPIT-CAB-5, 10 Nov 2026)

- **qaexp34 / qar11 / qar13 (brown faceted stand-in fists for seconds in first person).** The cab's stand-in fists
  (`fp_arm_right`, `DrawCabHands`) draw whenever his seated body has not been drawn for 250 ms. In the filer's run
  (qaexp34_wil2, 18:51:44-18:52:00) the game had handed the player's old sprite object to a passer-by (FIX-SEATED's
  known reuse); that passer-by jacked the car parked beside the van (`jack: 210a201c boarding a car with a driver`,
  the object is the player's: rig gate `o=8807`), and when he sat down live_geometry rekeyed his board to
  `object | 1`, which was the player's own seat key. The rekey overwrote the player's seated record with the
  stranger's (`player=false`, another car): the hands vanished for two samples (his body drawn in the other car),
  then the body gate (`BoardingIsPlayer`) stayed shut and the stand-in fists drew for 13 s until the stranger's
  record went. Now:
  - a stranger whose seat key already holds the player's seat is keyed `object | 3` (log `seat: ... took the
    player's old object`);
  - `BoardingSeat` takes back a stranger's seat found under the player's key (log `board: ... taken back`);
  - while the game has the player in a car, a driver thrown out or a passer-by knocked down within 0.7 block of his
    seat no longer counts as "his sprite is back" (that test stays for NPC drivers);
  - with the driver body on (`[camera] fp_driver_body=1`, an avatar), the stand-in fists are never drawn: a frame his
    body misses shows the rim without hands. Every such frame is counted: `cab: his body not drawn N frames (M in
    all)` once a second.
  A/B: `GTA2DX9_SEAT_KEY_OLD=1` (the old keying and let-go), `GTA2DX9_FP_STANDIN=1` (fists fill any gap).
- **Tall cabs (the 017 fire truck in pfl54): no body at the wheel for the whole first-person leg** (the stand-in fists on
  HEAD before, triage run tri49_pfl54). The body gate was open but the figure loop culled it: its origin (the seat on the
  floor, 0.68 under the eye and behind it) fell past the frustum's bottom plane by more than the 0.75 margin. The body at
  the wheel no longer goes through `BehindView` / `OutsideViewFrustum`. A/B `GTA2DX9_FP_BODY_CULL_OLD=1`.
- Probes: the filer's `gamerun/qaexp34_hunt.py` (qa_run, 3 views x 30 s, add `-e GTA2DX9_FP_BODY_LOG=1 -e
  GTA2DX9_LOG_FIGURES=1`: `cockpit: body gate` every 15 frames, `seat:` lines) and `/mnt/gta2/qa/scenarios/dgh_hands`.
  The jack beside him is traffic-dependent: most hunt runs do not hit it; read `seat:`/`jack:` lines to know if a run
  exercised it.

### The open tops' drivers in their cockpits; the fire truck's late cab was the warp (FIX-COCKPIT-CAB-6, 10 Nov 2026)

- qav51 (the 031 Jefferson's driver on its long bonnet, seats empty): a generated body with no manifest `driver_seat`
  takes car_glass's cabin seat, and an open top has no cabin behind glass, so it fell back to the sprite's window
  rows (boarding.cpp `SeatZ`), which for the 031's sprites put the hip anywhere from +0.04 (on the bonnet, forced
  sprite 4) to -0.16 (behind the cockpit, natural sprite 25). The same for the 045 Spritzer (head on the bonnet) and
  the 022 armed Land Roamer (sunk under its windscreen frame). Not a stale seat: `BoardingPublishSeat` runs every
  frame from the model drawn, the forced and the natural car both took the sprite's guess.
- Fix 1, `dll/src/seat_well.cpp`: an open top (the cab table's) with neither a manifest seat nor a glass cabin
  finds its seat in its own mesh: the top surface rasterised 24 x 64, per row against the row's own width (the
  bounds' mirrors made the sides vanish on the 045), the windscreen (the first row at 85 % of the height), the
  cockpit well (the driver's band under 55 % of the height and under the doors' tops by 12 %, or under the bonnet
  by 12 %, the jeep's flat tub), the first run of well rows within ten rows behind the windscreen (a pickup bed
  behind a closed cab is further back). The hip is half the run behind its front (4-14 % of the length), the
  cushion the band's low 30 %. Logged once per model: `seat well: <model>: cockpit well ...` and the
  `driver's seat of <model> (cockpit well)` line. Offline twin of the rule: the same logic in Python matched
  031 / 045 / 022 and found no well on 001, 030, 053, 062. `[devtools] seat_well=0` (re-read each second) or
  `GTA2DX9_SEAT_WELL=0`: the sprite's seat.
- Fix 2, boarding.cpp `DriveSink`: an open top's named seat with nothing over it (the headliner at the body's full
  height: 039 Morton and 044 Arachnid from the manifest, the well's seats) seats him on the cushion; before, the
  clamp under the body's top sank the hips 0.07-0.10 under the cushion and the 031's driver was hidden below the
  door line from the side. Both the cab table's open top and the body's open seat are needed: the 053 Michelli
  is "open" in the table but its body has a roof (headliner 0.94 of its height), the 036 Schmidt's bubble reaches
  its full height but is not open; both keep the clamp. `GTA2DX9_OPEN_SEAT_ROOF_OLD=1`: as before.
- Verified (plain GL, frames opened): the filer's repro (wil 164.5,147.6, 22:30, the hero's car forced
  62 -> 29 -> 30 -> 31, then 45, 22, 53, 36, 44, 39; high, front 3/4 and side fixed cameras, `seat_well` 1 then 0
  at each pose): 031, 045, 022 in the left seat at the wheel with the new seat, on the bonnet / ahead with the
  old; 053 and 036 heads under their roofs; 044 and 039 head and shoulders over the door. A natural 031 (bil
  44.5,89.5, the parked one the level places there, boarded with Return, no forcing) at noon and 22:30: the old
  sprite seat had him high behind the windscreen, leaning into its frame; the new one in the seat. Traffic 031s
  with their own drivers take the same per-model seat (same publish call), not filmed.
- qar22 (fire truck 017: no cab for 3-5 s after V): not the cab. The filer's probe warps from the level start to
  the truck (150 blocks) and the game camera scrolls after him at ~6 blocks a second; the game submits no
  sprites outside its window, so no 3D body (and no cab) is drawn until it arrives (the 017's first `identity:`
  and `cab of model 17` lines come 13-17 s after the warp in all three filer runs, as the `cam[N] bounds=` lines
  reach him). Same probe with the game camera settled first (gamerun/fire017_settled.py, keys_fire017s.sh): the
  first first-person frame has the header, pillars, dash, gauges and both hands (one frame of open hands closing
  on the rim). In play the camera is always on him: no code change.
- Classic top-down: see the vreg line in the commit.

## The third-person turn budget; no swing cut ping-pong; the boom past a phone box; peds at the lens (FIX-CAMERA-17, 10 Nov 2026)

Owner, playtest 2 (RTX 5090): "standing near a phone booth can cause camera jitter; jitter also occurs when a large
vehicle passes by" (work order owner10nov-B10, plan section B10), and qav26 (standing peds fill the chase lens).

- **What the owner's log lines meant.** `view: camera clearance (...): nearest surface 0.600` is the world-mesh probe's
  own search radius: `eyecol::Nearest(p, 0.6)` returns 0.6 when no face of the static map mesh is nearer, and that mesh
  holds no street objects, cars or people, so the line could never see a phone box or a bus; "safety net moved 0
  frames" is the 0.12 near-plane push, which only acts inside 0.12 of a map face. The line now also reports the nearest
  street object (MapObjectObstacles), car or wreck (LiveCameraCars, his own excluded) and person (LiveAimPeds, him
  excluded) and the frames the lens was inside one: `street object A car B person C (9 = none within 3), lens inside one
  N frames`. `view: move turn capped: yaw -159.7` was never a 160-degree frame: it is what a view move still had to turn
  after a jump of its target, logged every fifth frame while the 8-degree-a-frame cap closed it (-159.7, -121.5, -81.5,
  -41.5 are 40 degrees = 5 frames apart); the line now says "still to turn (this frame at most 8.0)".
- **What did jump** (probe `gamerun/cam17_probe.py`, `keys_cam17.sh`, CAM17_SEGS=booth,bus,lane; `force_car_model=11`
  draws every traffic car as the bus; GTA2DX9_LOG_CAMERA=1, the `cam: pose` line now ends in `ystep=`, the yaw turned
  since the last frame). Run cam17_b0 (HEAD): the largest per-frame yaw 139.2 degrees, 34 frames over 8. Every frame over
  20 degrees was FIX-CAMERA-10's `cam: swing first: neither way round is open, cut` (the boom cut round him to the open
  side in one frame): by the wil plaza phone box, which stands at the iron stair (map 158.5,138.5), and on the kerb at
  164.5,147.6 between the wall and the railing, where it cut 116 -> -30 and 0.3 s later -13 -> 105, then -15 -> -150.
  Between the cuts the 360-degree-a-second fast swing showed as 10-degree frames for half a second.
- **The turn budget** (`[camera] turn_budget`, degrees a frame at 30 fps, default 8 = 240/s; `GTA2DX9_CAM_TURN_BUDGET`
  overrides, 0 = all of the below off). In third person on foot: the solver's final rate cap is the budget (was 300 deg/s
  of yaw, 280 of pitch); the fast swing turns at most three quarters of it; the swing's cut happens at most once in 2 s
  (between, it swings: `cam: swing first: cut wanted N s after the last, swung instead`), and for 1 s after a fast swing
  none starts the other way unless the line where it is has collapsed (`cam: swing first held`); after all of the camera,
  world_view checks the shown pose against the frame before and logs every frame whose camera wanted more than the
  budget (`view: turn over budget`), showing it at the budget; a frame whose lens moved 0.6 block or more is a cut, not
  a turn (`view: camera cut (not a turn)`). The frame clamp leaves the yaw alone from within 0.3 block of his axis (seen
  from above the bearing to him is noise: it asked for 87-136 degrees a frame) and keeps its pitch part down to the axis
  (it switched off under 0.05 and the pitch sawed between -62 and -11).
- **Past a phone box** (FIX-CAMERA-10's prop boom, under the budget): an object only between the lens and him no longer
  shortens the boom (it fades as a foreground occluder, FIX-CAMERA-12): the shortening put the lens on his shoulder at
  0.30 with the pitch flipping every frame (run cam17_f1). A lens that would stand in the object's widened cylinder still
  stops short of it from 0.6 out; nearer him the berth moves the lens aside, eased at 2.5 blocks/s as an offset
  (`cam: prop berth moved ... eased`), at once only inside the object's body itself.
- **Measured** (same probe, same spots, the scripted walk loops differ run to run): HEAD cam17_b0 / fix cam17_f5:
  largest per-frame yaw 139.2 / 8.0 outside the one cut frame (11.5, logged as a cut); frames over 8 degrees 34 / 1;
  swing cuts 5 / 1; yaw reversals over 2 degrees 7 / 3; `turn over budget` 0; the clearance line varies (29 / 38
  distinct world-mesh values over 2 min, street object down to 0.12-0.15, person 0.13-0.18); lens inside a street object,
  car or person 0 frames in both; hero off the frame (pose box) 1 / 4 frames. Intermediate builds without the cut
  (cam17_f2-f4) put 35-81 frames off the frame in the pockets (the slow swing dragged the boom across the rail onto his
  axis), which is why the cut stays, rate-limited. Bus pass: standing in the kerb lane at 165.5,149.45 (traffic halts at
  him, the boom over the road): buses to 0.22 block of the lens, lens inside 0 frames, largest yaw 1.0 and pitch 4.6
  degrees a frame with the budget on (cam17_f6) and off (cam17_b1) alike: a passing bus did not shake the camera in this
  repro; the owner's jitter reproduced as the pocket cuts above.
- **Pedestrians at the lens** (qav26, `dll/src/live_geometry.cpp` beside FIX-CAMERA-6's lens rule): in third person a
  pedestrian nearer the lens than he is, within 0.6 block of it (seen from above) or across the line to him within a
  block of it (0.22 off the line), is not drawn, held 12 frames after the last reason; `view: pedestrian by the chase
  lens not drawn (...)`. `[camera] chase_hide_near_peds=0` or `GTA2DX9_CAM_PED_LENS=0` draws them (A/B).
  Filer's repro on a HEAD stage (`qa_run.sh qav26c17`, both spots, four weathers): 200 hides in the log (133 at the
  lens, 43 across the line), people to 0.23 block of the lens, and none of the 40 third-person frames has a figure
  filling the lens. The order's 8-heading check at a standing crowd was not run separately.
- Short of a shipping frame: a pocket with no way open still cuts (at most every 2 s); a hidden pedestrian pops rather
  than dithers out; vehicles between the lens and him are not faded.

## The pocket memory instead of a cut; peds and cars at the lens fade; the level opens at the hero (FIX-CAMERA-18, 10 Nov 2026)

- **The kerb pocket (CAMERA-17's residual).** The wil kerb at 164.5,147.6 is an L-shaped strip round a building's corner,
  railings on its outside; walking loops there the on-foot boom cut round him every 2.7-9 s (cam17_f7: 7 cuts in the booth
  and kerb segments). A probe logged at each cut (`cam: pocket probe at the cut (swing:mesh/walls/lift30/lift60 ...)`,
  run cam18_k2) showed what closes each heading: on the road side only the railing's sheet, 0.05-0.75 from his centre (the
  walls-only reach is the full boom); on the walled side only the strip's two ends are open, so a swing between them has to
  pass the building or the railing, and the 45-degree lift does not clear the railing that close to him (60 does, looking
  steeply down). Now (`[camera] pocket_lift`, `GTA2DX9_CAM_POCKET_LIFT`, default on, under the turn budget):
  - **pocket memory**: the first time a cut is wanted, a sheet or bar crossed within 0.9 of him (FIX-CAMERA-7's lean-sheet
    skip, `eyecol::SetNearSoftSkip`) stops counting for the boom for 20 s while he stays within 2.5 blocks of that spot
    (`cam: pocket: a cut wanted at ...`): the swing then finds the heading over the road and looks at him through the bars;
  - **lift before a cut**: neither way round open, the arc over what closes the line where the boom is (up to the on-foot 45
    degrees) is tried first; if it opens the line the swing holds and the boom rises (`cam: pocket: no way round is open,
    the boom rises N deg ...`);
  - only then CAMERA-17's cut (at most one in 2 s).
- **Peds at the lens fade** (`[camera] chase_ped_fade`, `GTA2DX9_CAM_PED_FADE`): CAMERA-17's hidden pedestrian goes out and
  comes back at 0.17 alpha a frame (six frames), drawn see-through as the street objects' overlap fade (texture alpha x the
  fade, blended, no depth writes); log `view: pedestrian by the chase lens fading|not drawn (..., alpha A)`.
- **Cars between the lens and him fade** (same key; `GTA2DX9_CAM_CAR_FADE=0` turns only the cars off): a car or wreck (not
  his own or the one he drives) whose body crosses both lines from the shown eye to his chest and head within 3 blocks of
  the eye fades out over six frames, held 8 frames after the last reason, and back in; drawn with constant-alpha blending
  (`D3DBLEND_BLENDFACTOR`) over every pass of the body. Log `view: car between the lens and him fading|held|back`.
  Depth writes stay on for a fading car (off, the van read as a dark see-through box with its cab and insides for five
  frames: cam18_k4 b_lane 15.2 s). Pedestrians are blended with the same constant factor, no depth writes (a
  texture-factor alpha never reached the picture: the figure's draw sets the texture factor for its clothes' tint).
  Probe aid: `GTA2DX9_CAM_FADE_TEST=<percent>` draws every pedestrian and every other car at that alpha (cam18_ft3 at 25:
  the fence bars through the passers-by, a clean see-through truck, him whole).
- **qaexp32: the level opens at the hero** (`[camera] level_start_cut`, `GTA2DX9_LEVEL_START_CUT`). A street view kept
  through PLAYER QUIT -> main menu -> a new game opened the level with the 1.4 s classic -> street move from the game's
  camera high over the city (run qa_qaexp32b_main: `moving the camera to First person over 1.4 s` on the level's first
  placed frame). After a level load the first street frame is cut to, as after a respawn (FIX-CAMERA-8): `view: the level's
  first street frame: cut to ...`. A classic frame wanted by the player, or 10 s without a street frame, ends it.
- **Measured** (cam17_probe.py, same spots; walking loops differ run to run). Booth + kerb: cam17_f7 (567c11c3) 7 swing
  cuts, hero off the frame 10 frames; cam18_k3 4 cuts (2 booth, 2 kerb), hero off 0; kerb with the 0.9 skip, cam18_k4: 2
  cuts in 50 s (cam18_k1/k2 at 0.45 or none: 4 each), hero off 0. Every run: largest yaw outside cuts 8.0 a frame, `turn
  over budget` 0, lens inside a prop/car/person 0, lens never below his feet. Car fade (cam18_k4, kerb lane, real traffic):
  model 67 between the lens and him 0.83 -> 0 over six frames, held, 0.17 -> 1.00 over six. qaexp32 (qa_cam18_q32, the
  filer's recipe): GET READY, then the first-person spawn view from the first drawn frame (game.mp4 63.5-67.5 s at 6 fps),
  no classic HUD frame, no aerial. vreg spawn_classic 0 tiles (vreg_stage_cam18_1110_194724); the other shots differ from
  the stored goldens by the same 14-35 tiles as other agents' HEAD runs (vreg_fig17_a).
- Short of a shipping frame: the pockets still cut about twice a minute of walking loops where the walls (not a railing)
  close every way round (the iron-stair booth) or he stands mid-strip (filed: defects/open
  cam18-third-pocket-residual-cut-...); the looks through the bars over the road are a choice, not tested with an owner.
