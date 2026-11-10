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
