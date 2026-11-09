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
  quarter of the moves, where the classic camera's wide view still holds him); largest heading step 76.7 -> 10.6
  degrees a frame. Measured from the `view move` lines against the `cam: third ... at=` position.
- Still: mid-move the held camera can sit a hand from the yard's wall (half the picture one wall, him in the
  other half): the hold's position, not changed here.

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
