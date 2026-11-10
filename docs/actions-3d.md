# Actions in the street-level views (7 Nov 2026)

What the game does, how the renderer learns of it, and how it is drawn in third
and first person. "Verified" means seen in a frame of a scripted run on the L4
build; "mechanism" means the code path exists but the game state that triggers
it was not reached in a run. The classic top-down view is untouched by all of it.

| action | the game's signal | drawn as | status |
|---|---|---|---|
| walk, run, idle | the drawn figure's own ground covered per frame (not the game's frames) | Rocketbox walk/run + generated `sprint`, blended by pace, cycle advanced by signed distance, settle on stop, `turn_step` on the spot (ACTIONS-3D-4) | verified (ACTIONS-3D-4 section) |
| punch | frames 115-130, state 7 sub 0xe | `punch` (right cross) / `punch2` (left jab) combo, upper-body layer; the victim's `hit_head` + stagger on the game's health drop (ACTIONS-3D-4) | verified (ACTIONS-3D-4 section) |
| knocked down, get up, dead | corpse flag, state 8/9 | `fall` held lying, played back out on recovery | verified (earlier passes) |
| get in / out of a car | state 3 (sub 4 walk / reach, sub 6 climb frames 24-35), state 4 sub 7 | `enter_car` / `exit_car` (0.7 s) upper-body layers over legs stepping the game's motion; `grab_door_r/_l` running beside a moving car (ACTIONS-3D-4) | verified for the player (ACTIONS-3D-4 section) |
| aim / fire, one-handed | frames 36-47 in state 7 (not fists) | `aim` clip + the pistol pickup model in the right hand | mechanism; see the run notes below |
| aim / fire, two-handed | frames 48-52, state 7 or 0 | new `aim_heavy` clip + the machine-gun pickup model in the hand | mechanism; see the run notes below |
| muzzle flash, sparks | base-4 effect sprites the game lays flat | stood up to face the camera, centred at gun height (0.30 block) | see the run notes below |
| bullets in flight | small effect sprites that moved since last frame | a streak from the previous to the current position, a hand wide, facing the eye | see the run notes below |
| fire, explosions, smoke | base-4 effect sprites | the existing flame stacks; every large effect quad now stands up facing the camera on the spot it lay | mechanism (no explosion in this pass's runs; earlier respawn runs had flat ones) |
| swimming | state 8 sub 0x14, frames 131-135 | new `swim` clip (front crawl, prone), figure sunk 0.14 block | mechanism (no water reached) |
| hands up / arrested | busted: punched down to state 8 sub 0x16 (frame 72) while wanted (POLICE-3D) | `handsup`, then `cuffed` walking to the police car | verified in play (pol_arrest3, pol_arrest6; see the POLICE-3D section) |
| burning | corpse/fall + the game's fire sprites | fall clip, fire sprites now upright | mechanism |
| headlamps, tail lamps | `[renderer] car_lamps`: dark = the sky's sun below 6 deg; 2 = always | additive radial glows at the body's ends (3D models and sprite-built bodies alike), none on wrecks | see the run notes below |
| brake lamps | the body's own speed frame to frame: a car losing > 1.5 blocks/s^2 | the tail glows flare red and grow while braking, day or night | see the run notes below |
| helicopter rotors | object animation `rotor` (base 4 frame 0) | a synthetic spin clip on the `rotor_5` node (mast, 7 rev/s) and `tailrotor_7` (hub) | mechanism: no helicopter appeared in the runs |
| car doors opening | a pedestrian in state 3 (getting in) or 4 (getting out) next to the car, matched by the ped's vehicle word or by distance; `[devtools] force_car_door` for checks | the body is split once per (model, side, door rows from CARI) into a hull without the door panel and the panel itself, which swings 60° about its front edge at 2.5/s and shuts at 1.7/s; the inside of the panel is lit like the outside; not on wrecks nor on the own car from the seat (`car_bodies.cpp` DoorSplitFor, DoorState) | verified: the split is built and the door opened at every entry and exit of three runs (`out/dd1..dd4`); frames in `out/doors_dents_sheet.png` |
| car damage, dents | the vehicle damage byte (+0x74: 0 fresh, rising with every knock, the car burns past about 200), in four steps of 64; `[devtools] force_car_damage` for checks | a dented copy per (model, step): three octaves of value noise over the car's frame press the shell in along normals smoothed across every seam (both paint-split halves move together), at most 2 % of the body length at the top step, normals rebuilt from the moved faces; the paint dulls 6 % a step; the smoke and fire over a badly damaged car are the game's own sprites, stood upright (`car_bodies.cpp` DentedModelFor) | verified at forced steps 0 / 96 / 160 / 255 from the chase camera and the driver's seat (`out/dd3`, `out/dd_steps_sheet.png`): no tearing, no light through the shell, a fresh car unchanged; the first version (per-vertex normals) tore the hull and showed white through it (`out/pd3_ste4/shot_1685.png`, build of 18:01), replaced |
| trains, buses, tank, bank van | ordinary vehicles | their models (bus and bank van seen driving in QA2 / the master demo) | bus and army tanks verified in play (POLICE-3D); trains verified at the elevated station (ACTIONS-3D-3) |
| horn, phone pose, pickup flash, score popups | HUD / sound | left to the game | n/a |

### Shooting pass (7 Nov 2026 evening, SHOOT-ANIM)

Statuses below are from the `shoot_probe2` / `shoot_ab*` runs of 7 Nov evening, all with `nav_map=0` (see the pass notes at the end). NPC gunfire was not reached (the police never came: wanted stayed 0 through the street shooting; one NPC carried a two-handed weapon on frames 48-52 and took the rifle stance).

| action | the game's signal | drawn as | status |
|---|---|---|---|
| the weapon held | the player's: a word of his ped (`game::kPlayerWeaponOffset`, found by the `GTA2DX9_LOG_PED_WORDS` probe; `GTA2DX9_WEAPON_OFFSET=0x..` tries a candidate); a stranger's: one-handed frames 36-47 = pistol, two-handed 48-52 = machine gun, a 0.15-0.3 block flash = shotgun | `weapon_*` models (tools/gen_weapons.py: pistol, machine gun, silenced machine gun, shotgun, rocket launcher, flamethrower, electro gun, grenade, molotov; grip at the origin, barrel +z) at the right-hand joint; two-handed weapons laid along the line from the right hand to the left so the stance's hands place them; dual pistols one in each hand; logged as `weapon=` in the `view: mission` line | verified: pistol model in the hand (`shoot_probe2` gen43/flamethrower/molotov frames, `weapon in hand` log); the game's weapon word not found (see notes), so every player weapon is inferred and the kill-frenzy weapons drew as the pistol |
| pistol aim / fire | state 7 + a fresh flash/bullet sprite within 0.8 block of the figure | `aim` clip: two-handed isosceles grip, bladed, head down the sights; each shot restarts the clip from its kick key (arms up 9 deg, shoulders back) which settles over 0.12 s | verified: stance in frames (`shoot_probe2` pistol strip, `shoot_ab4` mg_t1: arms forward; from straight behind the chase camera hides them against the torso), recoil restarts in the `player figure` log (t 1.13 -> 0.17 on a shot) |
| dual pistols | weapon 2 | `aim_dual`: both arms out, spread 10 deg, a pistol in each hand, the same kick | untested (no dual pistols reached; weapon type not readable) |
| machine gun, silenced MG, shotgun | weapon 3/4/9 or the two-handed frames | `aim_heavy` rewritten as a rifle stance: stock in the shoulder, right hand at the pistol grip by the chest, left arm out on the fore-end, cheek on the stock; kick: the forearm pulls back 8 deg, shoulders back 5 deg, settles in 0.14 s | stance seen only as the two-handed carry (NPC on frames 48-52, log); firing with it untested: the kill-frenzy machine gun drew as a pistol (weapon type not readable) |
| rocket launcher | weapon 5 | `aim_launcher`: tube on the right shoulder, right hand at the grip beside the cheek, left arm out under the tube, head tilted to it; the kick is the shoulder check (torso jolts right and back 7 deg, 0.16 s); the rocket's own sprite leaves a smoke trail (a flying small sprite over 0.16 block) | untested: the kill-frenzy launcher fired (explosions in the log) but the figure drew the pistol stance; the rocket sprite did not pass the small-sprite path, no trail seen |
| flamethrower | weapon 10 | `aim_flame`: fired from the hip, left hand on the front grip, slight crouch and lean, a slow sway; an orange glow and light at the nozzle per flame sprite; the game's flame sprites stand upright as before | untested (same: weapon type not readable, drew as pistol) |
| electro gun | weapon 6 | the rifle stance; a jagged arc of 14 short-lived cyan sparks a block and a half out of the muzzle per bolt | mechanism (no pickup reached by the probe script) |
| grenade, molotov | weapon 7/8 + a shot seen | `throw` (0.62 s one-shot underarm lob: shoulders turn away, arm swings back, through and up, follow-through); the grenade/bottle model in the hand until 0.34 s, then the game's projectile | untested (same) |
| muzzle flash | the shot event (the game's flash sprite appearing) | besides the game's sprite stood up at gun height: a per-weapon additive glow at the drawn muzzle (two layers, 0.045 block silenced .. 0.28 rocket, per-weapon colour) and a Remix point light there for two frames (`ShotLightsSubmit`); the game's own muzzle/bullet lights are lifted 0.25 block in the street views | verified in frames: glow at the pistol's muzzle (gen43, molotov rows), `shot fx: kind 4` spawns; the Remix light path compiled and submitted (`ShotLightsSubmit`), its effect not checked on a Remix build |
| shell ejection | the shot event, weapons with cases | one brass case out of the right side of the receiver, tumbling under gravity for 0.7 s | verified (cases on the ground around the player in the pistol strips; `shoot_ab4` first person) |
| tracers | unchanged | the bullet sprite streak | verified earlier |
| impacts | a fresh small effect sprite nobody claimed as a shot and that does not fly | seven orange sparks + a short glow at 0.30 over the spot (a wall); a dark-red puff when a figure stands within 0.3 block (or a bullet in flight ends beside one): blood | sparks verified on the park wall (pistol strip); blood untested (nobody hit in the runs) |
| aiming while moving | an aim stance with the drawn figure moving | legs face the way he moves (within 100 deg of the aim), the torso twisted onto the aim (`ModelSetTorsoTwist`, "Bip01 Spine1", 3 deg steps in the pose cache), both eased over 0.12 s; the turn lean as before | untested: the scripts fired standing still (twist stayed 0 in the log) |
| first person weapon | the view mode + a fresh flash/bullet within 1.2 block ahead of the eye (this frame's or last frame's) | the weapon model lower right of the eye (0.155 block ahead, 0.075 right, 0.066 down; two-handed 0.20/0.055/0.075), its barrel aimed at the point 5 blocks along the view (on the crosshair), held by first-person hands (`fp_arm_right` closed round the grip; `fp_arm_left_cup` cupping the fist for the pistol, `fp_arm_left` on the fore grip of the long guns; bare forearms to the striped short sleeve, tools/gen_weapons.py), lit by a key light from above-left with the textures modulated, drawn in a squeezed depth range (viewport 0..0.002) so the parts cover each other and the world never cuts in; the kick rises over two frames and settles over ~0.15 s (back by the weapon's kick, muzzle up, a few degrees of roll); one flash: the game's own flash/bullet sprites within half a block of the eye are not drawn in first person on foot (FIX-FIGURE) | verified (FIX-FIGURE, `ff_gun_fix2`/`ff_gun_fix3` vs `ff_gun_base`): textured pistol in both hands, one flash at the muzzle on the shot frame, no sprite at the bottom edge, kick back in ~0.1 s; earlier: kick logged, cases (`shoot_probe2`); FIX-FP-2 (feel17/feel21 first person): bare hands (the game's weapon 0, e.g. the pistol fired dry) are two fists (the right fist and its reflection) in a low guard with a slow breath, the game's punch frames (115-122 of the hidden player sprite) throw them alternately; a weapon change is a holster and draw (0.15 s down out of the view with the muzzle tipped, the new weapon 0.15 s up; a change asked during the rise goes back down from where it is), logged `view model: switch A -> B`; the kick also fires on the game's ammunition drop, not only on a flash sprite near the eye. Verified run fixfp2_f21f (pistol fired dry to fists, punches, Z cycle through launcher and machine gun at 30 fps). FIX-FIGURE-7 (pf2feel, pfeel50): bare hands are a closed-fist mesh (`fp_fist_right`, tools/gen_weapons.py `fp_fist`: curled fingers, knuckles ahead, the thumb folded over the index and middle fingers; the left is its reflection), rolled a quarter toward palm-down; every view model has a walk bob (down at each footfall, across once a stride, scaled by his speed over the ground) and a turn sway (the hands lag the yaw and settle, tau 0.12 s). The shot kick runs on a clock advanced by the real frame time capped at 1/20 s (3/4 on the shot frame, full by 0.03 s, a critically damped return, tau 0.045 s: ~6 frames at 30 fps), so a slow frame cannot swallow it; the muzzle flash is drawn at least once whatever the frame time (`shown`), lights the gun and hands (a warm point light, always enabled and black between shots so no shader variant compiles at the first shot) and pulses on the walls by day too (`visuals.cpp` muzzle share); the particle blend paths and the light path are drawn once invisibly at the first street-view frame (the first shot stalled 0.2 s, fig7_c). Log: `view model: shot seen (...)`, `view model kick: t= kick= flash=`, `shot fx: blend paths warmed`. Verified fig7_b (fists, walk bob), fig7_d (three shots, kick and return, no stall). Not done: a camera kick (the camera's owner) |

## Run notes

Scenario `gamerun/actions3d.py` (`qa_run.sh actions3d`, GPU image, `car_lamps=2`,
`GTA2DX9_LOG_PED_FRAMES=1`): the player is warped to the COLLECT_02 machine-gun pickup in the
walled Downtown park (154.5,129.5), fires bursts in third and first person with 4 fps frame
strips, then stands at the carriageway kerb (164.5,147.6) and photographs passing cars within
three blocks. Runs `out/qa_actions3d` (full), `out/qa_actions3d_b` (bursts only, final build);
0 faults, 0 locator losses. Sheet: `out/actions3d_sheet.png`.

Verified in frames:
- Bullets in flight as streaks ahead of the player in third person and across the park in first
  person; muzzle/impact flashes stood upright at gun height beside the player and on the fence
  (before this pass the same artwork lay flat on the grass as a sliver).
- A pedestrian hit by the burst goes down with the fall clip (`qa_c_fire_third2_01`).
- Headlamps: white glows at the nose of a passing sedan and of oncoming traffic at a distance;
  tail lamps red at a van's rear in first person (`car_lamps=2`). Brake flare: the mechanism
  runs on every car (speed loss > 1.5 blocks/s^2) but a braking car was not caught in a frame.
- The two-handed stance clip (`aim_heavy`) triggered on an NPC on frames 48 (log), not seen
  in a frame.

What the runs showed about the game, and what is still open:
- The machine gun is fired on frames 53-60 in state 7 sub 0xe, the same frames and words as the
  fists-ready stance, so the frames alone cannot tell shooting from boxing. The renderer now
  treats a figure in that stance as shooting when a tiny sprite (a flash, a bullet, a spark) was
  drawn within a block of him in the previous frame, and holds the `aim` clip and the weapon for
  1.5 s after. With the pickup's five rounds the shooting lasts about a second and the aim
  triggered once (log `action 2`, player object) but no frame caught the raised arm or the
  pistol model in the hand: unverified. A weapon with more ammunition (the respawn scripts
  found none reachable) or NPC gunfire (police) is the way to verify it.
- Which weapon a figure holds is not known to the renderer (no weapon field in the ped struct
  has been found; the HUD only shows the player's): the one-handed stance draws the pistol
  pickup model, the two-handed stance the machine gun.
- Impact flashes on a wall appear near the top of the wall rather than at the bullet's height
  in some frames (`qa_c_fire_third2_*`): the lay height of those sprites may be the shooter's
  level, so the +0.30 lift over-shoots at a lower wall base. To check with a level camera.
- The tracer is the game's bullet sprite stretched between its last two positions (capped at
  half a block); in first person a fast bullet can read as a short arc.

Files: `dll/src/live_geometry.cpp/.h` (effect billboards, streaks, shot detection, weapon in the
hand, swim/heavy actions, lamp switch), `dll/src/model_store.cpp/.h` (`ModelNodeWorld`,
`ModelSpinAnimation`), `dll/src/map_objects.cpp` (rotor spin), `dll/src/car_bodies.cpp/.h`
(lamps), `dll/src/dllmain.cpp` + `package/gta2dx9.ini` (`car_lamps`), `tools/gen_ped_clips.py`
(+`aim_heavy`, `swim`), `assets-src/humans/clips/ped_clips.json`, the 41 avatars re-imported
into `assets/models` (not in git: ship a fresh `gta2dx9_models_people.zip`), `gamerun/actions3d.py`
+ `keys_qa_actions3d.sh` (mirrored in `linux/docker/`).

## Shooting pass notes (7 Nov 2026 evening, SHOOT-ANIM)

Scenario `gamerun/shoot_probe.py` (`keys_shoot_probe.sh`; runs `out/shoot_probe`, `out/shoot_probe2`):
the player is warped to a pistol pickup (obj1, 166.5,140.5), the COLLECT_02 machine gun, the
Downtown kill-frenzy pickups (machine gun 88.5,27.5; rocket 214.5,50.5 and 181.5,145.5;
flamethrower 125.5,82.5; molotov 130.5,109.5; silenced machine gun 198.5,245.5) and three
COLLECT_04/08/09 generators, fires each in third person (two strips, Tab between) and first
person, then shoots up a street at 150.5,133.5 for the police. `gamerun/shoot_ab.py` is the
fire-key A/B (below). Sheet: `gamerun/shoot_sheet.py` -> `out/shoot_anim_sheet.png`.

What the runs showed about the game:
- **The fire key dies under the navigation hook.** `shoot_ab` at the COLLECT_02 machine gun:
  `nav_map=0` 536 bullets and 40 muzzle particles; `nav_map=1` (default) 1 bullet. The game reads
  its keyboard only through buffered `GetDeviceData` (the hook counted 0 `GetDeviceState` reads);
  `NavGetDeviceData` (dll/src/view_modes.cpp) injects the camera-relative arrows with
  `dwSequence` from 0x40000000, so once the player has walked, every later real event (the
  fire key's) carries an older sequence than the injected ones and the game drops it. The
  shooting runs here were made with `nav_map=0` (INI_SED); the hook needs its injected
  sequence numbers to continue from the last real event's (camera agent's file, not changed here).
- The player's firing frame is 139 (sprite 297, the second body), interleaved with the ready
  frames 53-56 in state 7 sub 0xe for the pistol and the machine gun alike; a kill-frenzy weapon
  is carried on frames 45-52 while walking (state 0). The frames do not tell the weapons apart.
- The player's ped (0x800 bytes probed, `GTA2DX9_LOG_PED_WORDS=1`) holds the selected weapon
  *slot* at +0x254 (1 with a pistol, 2 after the machine gun; back to 1 when a kill frenzy
  replaces the inventory) and the frames-the-fire-key-is-held counter in the high half of +0x20C;
  the weapon types and ammunition live elsewhere (the inventory array was not within 0x800 bytes
  of the ped), so `game::kPlayerWeaponOffset` stays -1 and the renderer infers the weapon:
  one-handed frames or a shot with nothing known = pistol, two-handed carry frames = machine
  gun, a 0.15-0.3 block flash = shotgun. `GTA2DX9_WEAPON_OFFSET=0x..` / `GTA2DX9_AMMO_OFFSET`
  try a candidate without a rebuild; `GTA2DX9_WEAPON_RAW=1` logs the raw word.
- Effect sprites (`GTA2DX9_LOG_FX=1`, base 8): the muzzle flash is numbers 410-415 (0.25 block
  shrinking to 0.19 over six frames), bullets 472/473 (0.125, flying), the pickup flash 503-505,
  an explosion 453-464 (0.14 rising to 0.5 while climbing). A bullet is above the renderer's
  "small" bound only on the flash's last two frames, so a shot is detected by its bullet.
- Another agent's `make stage` (which removes and recopies `stage/gta2dx9_models`) during a
  run leaves every figure and car white (textures "could not be read") until the next run:
  the white silhouettes in `out/shoot_ab2` are that, not the renderer.

## Weapon field (8 Nov, WEAPON-OFFSET pass)

The game's weapon word is now read, so the "weapon type not readable" rows above are superseded:

- `ped+0x15C` -> inventory: 28 weapon-object pointers at `+0x718` (one per type), int16 selected slot at `+0x788` (-1 bare hands).
- `ped+0x170` -> the weapon object in the hands (null with none): int16 ammo `+0`, int16 reload timer `+2`, type `+0x1C` (equals the slot).
- Types verified against pickups and the HUD icon: 0 pistol, 1 machine gun, 2 rocket launcher, 3 electro gun, 4 molotov, 5 grenade, 6 shotgun, 8 flamethrower, 9 silenced MG; from the GTAMP table, unverified: 7 electro baton, 10 dual pistols. COLLECT_nn fills slot nn; a kill frenzy sets ammo -1 and locks the selection. HUD ammo = stored/10.
- `ped+0x254` is not a weapon field (earlier reading was wrong). Z cycles weapons; Tab is the special key.
- `game_access.h`: `PedWeaponOf`, `PedWeaponFromGame`, `PedWeaponRaw`. Player and NPC figures both read it; frame/flash inference only when the game is unreadable. The first-person view model follows it (nothing with bare hands). `GTA2DX9_LOG_PED_WORDS=1` logs a `weapon probe:` line. The `GTA2DX9_WEAPON_OFFSET/AMMO_OFFSET/WEAPON_RAW` overrides are gone.
- Verified: `out/weapon_offset_sheet.png` (runs weapon_offset_wil2/ste2, `linux/docker/weapon_probe2.py`): mission-line weapon matched the HUD icon at all 13 weapon stops; nine distinct first-person models. Scene warps need the INI_SED that sets `scene_key=F10`.
- Still open: third-person frames show the hip carry rather than the aim stance because the stance keys off firing frames (shooting side).

## Vehicle fields (8 Nov 2026, PLAYTHROUGH-7)

The car object (the vehicle list at `[0x5E4CA0]+4`, next at `+0x4C`) is 0xBC bytes. Found
with a probe (`GTA2DX9_LOG_CAR_WORDS=1`: every changed word of the player's car, or of the
car nearest him on foot, every third frame; `gamerun/car_probe.py`, runs `out/pt7_carprobe1..6`)
and read back in `gta2.exe`'s damage routine (`FUN_00427180`):

| offset | type | meaning |
|---|---|---|
| `+0x74` | int16 | **damage**, 0 fresh. `FUN_00427180` adds the hit, clamps to 0..32000, then: at >= 16000 (0x3E80) the stage byte goes to 3 and the car is set alight (`FUN_004226C0(1)`); at >= 25000 (0x61A8) stage 4 and a second fire effect (`FUN_004226C0(2)`, `FUN_004BEB70`); at >= 31500 (0x7B0C) its lamps go out (`FUN_00426F60`); at 32000 (0x7D00) it explodes (`FUN_00426FA0`). 32001 marks a wreck (`FUN_0040F890`). |
| `+0x76` | int16 | a counter that runs up after a car is created or entered (not damage) |
| `+0x8C` | byte | damage stage: 0, 3 burning (from 16000), 4 burning hard (from 25000) |
| `+0x00` | ptr | the car's effect list: gets its first entry when the fire starts, another at stage 4 |
| `+0x60` | ptr | an object the car owns, released when it explodes or is removed (`FUN_00426730`, `FUN_00426FA0`) |
| `+0x90`/`+0x94` | int | set to 1 / 0x130 on a hard knock and counted down (a shake), not damage |

**A burning car keeps burning:** from 16000 on the damage also rises by itself, one point a
game frame (measured: +3 every 3 frames between every hit, `pt7_carprobe5`), so a car that has
just caught fire explodes 16000 frames (533 game seconds) later unless more hits shorten it,
and `(32000 - damage) / 30` is the game seconds left. The driver dies in the explosion
(`pt7_carprobe5/6`: lives 5 -> 4).

**The old readings were wrong:** the mission line's `cardmg` and the dents in
`car_bodies.cpp` (`DentStepFor`, "damage byte +0x74, 0..255") read the low byte of this word,
which wraps every 256 points. The "counts up 15 a sample and wraps" of pt5_le2g is exactly
the self-rise of a burning car (one point a frame, a sample every 15 frames): that car was
already on fire. For the cars agent: dent steps should come
from the int16 (e.g. step = damage / 8000), not the byte.

The renderer now logs, in the `view: mission` line, `cardmg=` (the int16), `carhp=` (32000 -
damage, 0 for a wreck, -1 on foot), `carfire=` (0 none, 1 burning, 2 burning hard; from the
stage byte) and the same for the mission's target car: `tcarhp= tcarfire= tcar=x,y`, taken
from the first objective arrow of kind 3 (a vehicle) whose `+0x34` names a live car (-1 when
there is none). Verified against frames (`out/pt7_carfields_sheet.png`, run `pt7_carprobe6`,
wall hits at full throttle, no forced damage): carfire 0 and no flames at carhp 18463,
carfire 1 at carhp 15893 with the first flames on the next frame, carfire 2 at 6898 with
bigger flames, the explosion and a lost life as carhp reached 0. The probe can start the
player's car at a given damage (`GTA2DX9_PROBE_CARDMG=N`, probe only) to see the stages in a
few hits.

`GTA2DX9_STATE_EVERY=N` (environment) logs the `view: player` line every N frames instead of
15, for a script driving fast. Every scripted runner that steers, aims or walks from that line should pass
`-e GTA2DX9_STATE_EVERY=3` (MISSIONS-BATCH2: at the default 15 the facing and position are half a
second stale; lateral error on a jetty walk 0.45 -> 0.1 block, rockets on target).

## Actions pass (8 Nov 2026, ACTIONS-3D)

The stance now keys off the weapon the game puts in the hands (`PedWeaponOf`), and the
states the earlier passes left as "mechanism" got clips of their own. All new clips are
in `tools/gen_ped_clips.py` (regenerate `assets-src/humans/clips/ped_clips.json`, then
re-import the 41 avatars: `tools/import_assets.py ../assets-src/manifest.json assets/models --only human_...`;
the avatars are not in git, ship a fresh people archive). Code: `dll/src/live_geometry.cpp/.h`
(`PedActionFor`, the weapon block and the action layer of `DrawPedFigures`, `ActionProbes`).

How it works now:

- **Upper-body layers.** The aim, carry, throw, hands-up, cuffed and burn clips have channels
  only for `Bip01 Spine1` and below it (chest, neck, head, arms). The renderer draws them at
  just under full weight over the walk, run or idle; a joint the second clip has no channel
  for keeps the first clip's value (`model_store.cpp` `SampleClip` writes over a copy of the
  first pose), so the legs keep walking under an aim or a carry. Before, an aim froze the legs
  in the idle pose.
- **Armed, by the game's word.** With a weapon object in the hands: a shot is the weapon
  object's ammunition (+0) dropping or its reload timer (+2) restarting (a kill frenzy's
  ammunition never drops), or a flash/bullet beside him, or the firing frame 139. A shot
  raises the weapon's stance (`aim`, `aim_dual`, `aim_heavy`, `aim_launcher`, `aim_flame`)
  and holds it a second past the last shot; a grenade or molotov plays `throw` once per shot.
  Otherwise the weapon is carried at low ready: `carry` (pistol, grenade, molotov in the right
  hand), `carry_dual`, `carry_heavy` (machine gun, silenced MG, shotgun, electro gun: across the
  body, muzzle ahead and down), `carry_launcher` (tube on the shoulder), `carry_flame` (at the
  hip). The player always carries what he has selected; anyone else carries for three seconds
  after he fired (a gang member walking his beat does not wave a gun). The weapon model is
  drawn in the hands in every carry, as in the stances. Measured on the way: the attack state
  word (7, sub 0xe) is not a shot: an armed or bare-handed player standing still sits in it on
  frames 53-56, which is why the first build of this pass raised the aim whenever he stood.
- **Burning.** The game's flames on a figure (a fire spot within 0.18 block, three frames
  running, not his own flamethrower's) switch on `burn`, both arms beating about the head as a
  layer over his run. Dying soon after, he gets the `burnt` lying clip.
- **Falling from a height** (state 8 sub 0x13, measured on the player off the roof at 160,141:
  frames 81-96) plays `fall_air` (arms windmilling, legs cycling), then the lying clip.
- **Water** (state 8 sub 0x14 or frames 131-135) plays `drown` (upright, head back, arms reaching
  and slapping, legs treading), sunk to the chest at once and under over three seconds; a body
  in the water stays under.
- **Lying clips by cause.** `game::kPedDamageCause` (ped+0x290) and the knock-down sub-state pick
  the clip when he goes down: fire seen on him in the last three seconds or cause 11 -> `burnt`
  (onto the knees, over onto the side, curled); cause 4 (explosion) -> `blown` (thrown up and
  back, landing spread-eagled); cause 1/3 or sub-state 0x18-0x1A (struck or run over by a car)
  -> `runover` (knocked up and over, landing face down sprawled); otherwise `fall` (onto the
  back) or `fall_front` (onto the face) by his own seed. A knock-down plays the same clip
  backwards to get up. Logged as `ped anim: down <obj> cause C state S sub X -> lying clip N`.
- **Arrest.** `handsup` (now a layer) and the new `cuffed` (hands behind the back, head down,
  over the walk) exist; neither is wired to a game signal, because no run produced an arrest
  (see below), so the frames and states of the busted player are still unknown.
- **Weapon size.** Weapons are scaled by their largest extent: the molotov and grenade
  models stand upright, and scaling them by their length made them three times too big.

Probes (environment, off by default; `ActionProbes`, `ForcedAction` in `live_geometry.cpp`):
`GTA2DX9_FORCE_ACTION_FILE=<file>` plays "action lying weapon" from the file (re-read twice a
second) on the player's figure, the showcase used for the clip frames;
`GTA2DX9_LOG_VEHICLES=1` lists the live trains, tank, fire truck, ambulance, buses, SWAT van and
cop cars with position, heading and driver every two seconds; `GTA2DX9_LOG_POLICE=1` logs the
changed words of the police manager ([0x66B7A0]) and the player object ([0x5EB4FC]);
`GTA2DX9_POKE="police:0x4D4=0x300,player:0x64=3"` holds words there; `GTA2DX9_FORCE_WANTED=N` now holds the player's cop points (ped+0x20A, see the POLICE-3D section), not the manager's +0x654.

Scripts (`linux/docker`, mirrored in `gamerun`): `a3_lib.py` (shared), `a3_weapons.py` (the six
Downtown pickups, carry/fire/after frames per Z stop from the side), `a3_showcase.py` (every clip
forced on the player, back/side/front; `A3_ITEMS` picks), `a3_mayhem.py` (flamethrower and rockets
into crowds, roof, pool), `a3_falls.py`, `a3_water.py`, `a3_wanted.py`, `a3_cops.py`, `a3_cops2.py`,
`a3_police.py`, `a3_arrest.py` (the police attempts), `a3_vehicles.py`, `a3_train.py`,
`a3_tile.py` (contact strips), `a3_sheet.py` (the sheet). Run with
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> <secs> keys_a3_<name>.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1`
(add `s/^nav_map=.*/nav_map=0/` for the scripts that steer with `drive_lib.goto`, which assumes tank controls).
Sheet: `out/actions_3d_sheet.png` (local, not in git).

What the runs showed about the game:

- Police (superseded by the POLICE-3D section: the level is the ped's cop points, +0x654 is an output): the wanted level could not be raised on demand. Rockets into the kerb traffic gave
  wanted 1 once in three tries (a3m1, a3q2; never above 1); the machine gun into the plaza crowd
  never did. When it rose, the police manager's +0x468 went 0 -> 1, +0x4D4 0 -> 0x100 and +0x654
  (the level the mission line logs) 0 -> 1, and the player object's +0x64 0 -> 1 and +0x60 gained
  0x20000. Holding +0x654 (with or without +0x468/+0x4D4, or the player's +0x60/+0x64) makes the
  manager dispatch (its unit list at +0x664.. fills) but the game puts the level back to 0 every
  frame and no policeman came; in the one natural wanted-1 run (a3q2) no officer reached the
  player in three minutes either. So no police gunfire and no arrest were seen.
- Drowning: the developer warp into the water by the tank (225.0,241.5) leaves the player at z 0;
  the game shows WASTED at once and draws no ped sprite while he is in the water (no frame or
  state words logged), then respawns him. With no sprite there is no figure to animate, so
  `drown` is only reachable for a ped the game keeps drawing in state 8 sub 0x14; none was seen.
- Trains run at level 1 (in the cuttings and tunnels) as well as level 3 (the elevated line); the
  renderer draws the cab and its carriages with their models (`model draw: 060_train_cab`,
  `059_train` at the game's height) but no frame caught one: the warp ahead of a train lands the
  player at a street spot the devtools pick, and the train had not reached it while the frames ran.
  The tank (model 54) and fire truck (17) the vehicle log lists stand parked at 226.5,238.5 /
  3.5,164.5 and 5.5,26.5; frames from beside those spots show no vehicle, so they are not where
  the log puts them in view, or are hidden by the game until used. A bus (model 11) was listed
  driving at 174.5,119.0. Turret aim, the fire-truck ladder and ambulance lights belong to
  `car_bodies.cpp` (the cars agent's file) and are not done here.

### Status (8 Nov 2026)

"Verified" = seen in a frame of these runs; "log" = the trigger seen in the renderer's log but the
figure not caught in a frame; "showcase" = the clip seen on the player's figure in the game when
forced, its game trigger not reached; "untested" = neither.

| action | trigger | clip(s) | status | evidence |
|---|---|---|---|---|
| carry, game weapon, not firing (player) | weapon object in hand, no shot | carry / carry_heavy / carry_flame / carry_launcher | verified for silenced MG, flamethrower, molotov, rocket launcher | a3w2 `w01_*_carry_walk_side`, `w02_*`, `w03_*`; a3m3 (launcher, `player figure: action 17`) |
| carry, pistol / dual pistols / shotgun / electro gun | same | carry, carry_dual, carry_heavy | carry_heavy showcase (shotgun, MG: a3s2, a3s3); the one-handed `carry` is the molotov one verified in play, the pistol model in it was not framed; carry_dual not framed (the camera lost the figure in both showcase tries) | a3s2/a3s3 `s_carry_*` |
| rifle stance on a shot (MG, silenced MG) | ammo drop / reload restart | aim_heavy + kick | verified | a3w2 `w01_silenced_mg_fire_side_*` (rifle at the shoulder, cases), back to the carry 1 s after (`settled_side`) |
| flamethrower stance | same | aim_flame | verified | a3w2 `w02_flamethrower_fire_side_00` |
| launcher stance | same | aim_launcher | verified (log + frame) | a3m3 `m_rocket0_00`, `player figure: action 11` |
| throw (molotov) | ammo drop | throw | verified | a3w2 `w03_molotov_fire_side_01` |
| pistol, dual, electro gun stances | same | aim, aim_dual, aim_heavy | showcase | a3s2 `s_aim_*` |
| aiming while walking (legs walk under the aim) | stance + motion | upper layer + torso twist | showcase (aim_mg_walk) | a3s2 |
| NPC gunfire: stance, muzzle, tracers | his weapon object's words / a shot beside him | as the player | police (4 stars, beside a cop car with the MG): pistol aim stance in frame, the player shot dead, 9 `npc shot` lines (reload timer restarts, ammo 990 never drops); FBI (5 stars): 16 shots logged (silenced MG, shotgun), the agents framed getting out of their car, not mid-shot; soldiers (6 stars): rifle aim stance in frame in third and first person; the NPC muzzle glow and streaks not singled out in a frame | a33_pol4 `shot_200`, a33_pol5 `qa_f_006`, a33_types1 `army1_t_12`, a33_types2 `army0_f_05` (ACTIONS-3D-3) |
| burning (on his feet) | game flames on him 3 frames | burn layer | verified (player, set alight by his own rocket blast); NPC burning in the log | a3m3 `m_blown1_00`; `action 19` for NPC 30dbc240 |
| falling from a height | state 8 sub 0x13 | fall_air | verified | a3f1 `f_fall1_00`, log frames 81-96 |
| dead / knocked down: shot | cause 0 | fall, fall_front | verified (landing face down after the fall: a3f1 `f_fall1_02`); both clips in the showcase | 281 `lying clip 0/1` log lines over the runs |
| run over / struck by a car | cause 1/3, sub 0x18-0x1A | runover | log (17 bodies) + showcase | a3m1/a3m3 log, a3s2 `s_dead_runover_getup` |
| blown up | cause 4 | blown | log (15 bodies) + showcase | a3m1/a3m3 log, a3s2 `s_dead_blown_side` |
| burnt | fire before death, cause 11 | burnt | log (3 bodies) + showcase | a3m3 log, a3s2 `s_dead_burnt_getup` |
| getting up from a knock-down | leaving state 8 | the lying clip backwards | showcase | a3s2 `*_getup` |
| drowning | state 8 sub 0x14 | drown, sunk | showcase only; the player has no sprite in the water (game), not reached for NPCs | a3d1, a3s2 `s_drown_front` |
| wanted level | the player ped's cop points, int16 ped+0x20A (stars at 600/1600/3000/5000/8000/12000) | `[devtools] force_wanted=N` holds it (QA, off by default) | verified in play: police in 10-50 s at 2-4 stars beside a cop car, army with tanks in 26-30 s at 6 | pol_arrest3..7, pol_fight2/3, pol_army1/2; `wanted:` log lines |
| arrest: hands up, cuffed, led to the car | knock-down to state 8 sub 0x16 while wanted (or the cop points cleared while he lives) | lying clip backwards, handsup, cuffed over the walk towards the nearest cop car (up to 1.5 blocks, drawn offset) | verified in play | pol_arrest3 `a_037`-`a_045`, pol_arrest6 `a_045`-`a_048`, pol_arrest7 log |
| trains | ordinary vehicles, models 59-61 | car models | verified: cab and carriages on the elevated track at track height, wheels on the rails, cab leading (+y), stopping at and leaving the station at 99.5,97.7 (ACTIONS-3D-3) | a33_train1 `tr_t_005`, `tr_f_032`; a33_train2 `tr_t_002`, `tr_f_010` |
| bus | model 11 | car model | verified in play: driving past the arrest | pol_arrest6 `a_046`-`a_048`, vehicle log m11 at 174.6,143->126 |
| tank turret | the game's turret sprite heading over the hull | model split at 56 % of the roof, turned to it (`TurretSplitFor`) | verified in play for the army tanks (turret off the hull's line, aimed his way); the exact barrel bearing judged by eye only | pol_rescue1 `r17_01_05/10`, pol_veh3; `turret turned N deg` |
| fire-truck water cannon (the "ladder") | its sprite (0.44 x 0.19 tiles) over the truck | the roof gear behind the cab turned the same way | truck and roof gear verified from the chase camera with the player at the wheel; the water jet (the game's spray sprite, stood up) seen in first person and classic; the gear's turn not judged | a33_fire2 `ft_cannon_04_01`, `ft_cannon_08_01`, `ft_cannon_09_01` |
| siren beacons (cop car, SWAT van, ambulance, fire truck) | delta mask bits 15..18 (vehicle+0x08) | two flashing roof glows by model (`DrawBeacons`); `[devtools] force_sirens=1` | cop car verified in play; fire truck verified (the siren switched on with Tab at the wheel, delta mask 0x00810040, glows over the truck in the chase view); ambulance: beacons logged on a driven ambulance (12 lines, a33_resc1) but not framed in three tries | pol_arrest3 `a_037` crop; a33_fire2 `ft_cannon_04_01`, `ft_end_t_00` |
| first-person view model per weapon | game weapon | weapon models | verified earlier (WEAPON-OFFSET pass) | out/weapon_offset_sheet.png |

## Police and special vehicles (8 Nov 2026, POLICE-3D)

### The wanted level: the game's own field

- **The field is the player ped's cop points, int16 at `ped+0x20A`** (`game::kPedCopPoints`), read off
  gta2.exe v9.6: `FUN_00434C00` turns them into stars at 600 / 1600 / 3000 / 5000 / 8000 / 12000 (1..6),
  `FUN_004353D0` adds to them for a crime (clamped to 0..12000), `FUN_00434CD0` sets a star level
  outright (the mission script's and the cheat's path), and the death/arrest code clears them
  (`0x00441394`). Unwatched points decay: released after 25 s at 1 star they were back to 0 in 16 s
  (`pol_arrest1`).
- **Why writing the mission line's `wanted` never stuck:** that value is the police manager's
  `[0x66B7A0]+0x654`, the highest *response* level of this frame. The manager keeps up to four
  pursued peds at `+0x464` (stride 0x7C, the ped at +0), asks each one's stars every frame
  (`FUN_004AA030`) and rebuilds `+0x654` from zero each frame (`0x004AEF88`). It is an output.
- **QA switch:** `[devtools] force_wanted=N` (1..6, `-1` default off, re-read once a second;
  `GTA2DX9_FORCE_WANTED=N` does the same from the environment) keeps the player's cop points at least
  at N stars' threshold. The police manager then picks him up exactly as after a crime: the mission
  line's wanted level follows within two seconds, police cars and officers come, and at 6 stars the
  army with tanks (first tank listed 26 s after the switch in `pol_army1`, 30 s in `pol_army2`).
  Holding pauses for ten seconds after a bust. The renderer logs `wanted: player cop points P = S
  stars (police response R)` on every change. The player's ped is taken from his own sprite object
  as the camera's locator last found it (`LocatedPlayerPed()` in `view_modes.h`, valid in every view
  and at the wheel), else from his own sprite object (owner +0x08 -> physics +0x7C -> ped, checked
  back through ped+0x168) or the driven car's driver word.
- **Reliable probe:** `linux/docker/pol_probe.py` (`keys_pol_probe.sh`) with `POL_COPCAR=1` sets the
  level and stands the player three blocks ahead of the nearest driven cop car (from the
  `GTA2DX9_LOG_VEHICLES=1` line). At 2-4 stars the police reached and arrested him in 10-50 s in five
  runs out of five (`pol_fight2`, `pol_fight3`, `pol_arrest3..6`). In the walled plaza (159.5,139.5)
  nobody came in 2.5 minutes at 1 or 3 stars, and at 1 star even beside a cop car no officer
  arrested him (`pol_arrest2`): officers on foot come from 2 stars on.

### The arrest

- **What the game does** (log `GTA2DX9_LOG_PED_FRAMES=1`, runs `pol_fight2`, `pol_arrest3..6`): GTA2
  has no hands-up or cuffing animation. Officers punch the wanted player (health 100 -> 90 -> 50 ->
  20, ped state 7 sub 0xE as for any fist fight), the last punch puts him down in **state 8, sub-state
  0x16, frame 72** (damage cause 10, the same as any punch knock-down), the game shows BUSTED and
  takes his weapons, and 2.5-6 s later he is moved to the police station (`state 0`, walking out of
  the door). His cop points are cleared either at the knock-down or at the move to the station
  (both orders were seen); at the bust the game may put a new player ped in his place, lying in the
  same state.
- **Wired** (`live_geometry.cpp`, `g_bustFrame`, `ArrestWalk`): a knock-down to state 8 sub 0x16 while
  his cop points are at least one star (or the points cleared while he lives) starts the arrest.
  For up to twelve seconds, while the game keeps him in that state, his figure gets up from the
  knock-down (the lying clip played back), raises his hands (`handsup`, to 1.3 s after the bust),
  then is cuffed (`cuffed`, hands behind the back, head down, over the walk) and walks towards the
  nearest police car (model 12 within three blocks, chosen once) at 0.6 blocks/s until he is within
  0.75 of it or 1.5 blocks from where he lies; his drawn position is offset from the game's for
  that walk only. The game's move to the station ends it. Logged as `wanted: busted: ...` and
  `arrest: busted N s ago, figure at ..., police car at ...`.
- **Seen in play:** `pol_arrest3` frames `a_037` (the officer at him), `a_039`-`a_041` (BUSTED, hands
  up), `a_042`-`a_045` (cuffed, walking, the cop car's door open beside him); `pol_arrest6`
  `a_045`-`a_048` (hands up among three officers, BUSTED).

### Police and NPC gunfire

Not reached for the police. At 2, 3 and 4 stars the officers arrest instead of shooting: they run
up and punch, armed player or not (`pol_fight2`, `pol_fight3`: busted with the machine gun in hand
within 10 s of reaching the cop cars; the bust takes the weapons, so `pol_fight4` could not keep
shooting at them). With the player at the wheel of a parked car at 3 stars for 150 s no police
came at all (`pol_car4`; `pol_car1..3` held no level because the ped lookup missed a player who got
in a car in the classic view, fixed by the locator accessor below). At 6 stars the army fights:
tanks fire their cannon at him (frames `pol_army1` `tank10_04`, `pol_veh3` `tank03_04`: the shot's
streak and flame) and soldiers walk up with rifles in the two-handed carry (`action 8/16` in the log;
one framed, `pol_army2` `tank10_09`), but no soldier's own shot was claimed by the renderer's
shooter detection in these runs, so the NPC stance-with-muzzle-flash path is still log-only from the
earlier passes. Next try: 4-5 stars with the player driving away through traffic (the game's police
fire at a fleeing car), which needs a drivable start, not the plaza car `pol_car*` got.

### Special vehicles

- **Tank** (model 54). The parked tanks the vehicle log lists (226.5,238.5 and 3.5,164.5) stand
  behind garage doors (the warp to 226.5,240.1 lands in a closed courtyard facing a shuttered
  door, `pol_veh1`); the fire truck at 5.5,26.5 is the Downtown "FIRE TRUCK" kill frenzy (entering it
  starts "knock down 20 people in 60 seconds"). The way to tanks in the street is the game's own:
  wanted level 6 brings the army, jeeps and tanks driving and firing at the player (`pol_army1`,
  `pol_army2`, `pol_veh3`, `pol_rescue1`).
- **Turret follows the aim** (`car_bodies.cpp` `TurretSplitFor`, `CarBodiesSetTurret`; the sprite pass in
  `live_geometry.cpp`): the turret is a sprite of the game's own (1.44 x 0.50 tiles for the tank,
  0.44 x 0.19 for the fire truck's water cannon) laid over the hull with its own heading. The sprite
  pass finds it over a model-54/17 car (centre within 0.6 block, 0.2-2.4 tiles), hands its direction
  to the car bodies and does not draw the flat sprite; the model is split once into the hull and the
  part above 56 % of the roof height (fire truck: above 80 % and behind 5 % of the length ahead of
  the middle), which is turned about its own middle by the aim against the hull's nose. The turret
  artwork's top edge is the back of the turret: every tank driving straight read exactly 180 deg off
  its hull until the direction was reversed. Logged as `turret: model ...` and `car bodies: model 54
  turret turned N deg`.
- **Emergency lights** (`car_bodies.cpp` `DrawBeacons`): a 3D model hides the sprite, so the roof
  lamps the game lights as deltas 15..18 (the car's delta mask at vehicle+0x08) while the siren runs
  were lost in the street views. A cop car (12), SWAT van (52), ambulance (34) or fire truck (17)
  with any of those bits set now gets two roof beacons (a core and a halo, two crossed quads each)
  that flash in turn: red/blue (police), red/white over the cab (ambulance), red/amber over the cab
  (fire truck). `[devtools] force_sirens=1` lights them on every such model.
- **Trains, bus, fire truck, ambulance:** see the table.

### Fix on the way

`GTA2DX9_LOG_PED_FRAMES=1` crashed the game (`FAULT C0000005 ... reading 00220278` in `AddSprite`) when a
sprite of another base had an owner whose +0x7C word looked like a pointer (the fire truck's water
spray read 0x00220000, `pol_veh1`): the probe's read of that "ped" state is now guarded. Off by
default, so players never hit it.

### Not mine, seen on the way

Army soldiers (6 stars) are drawn as flat bright-yellow figures in the street views (`pol_army2`
`tank10_09`, `pol_army1` `tank10_03`). Fixed in ACTIONS-3D-3 (below).

### Scripts

`linux/docker/pol_probe.py` (`keys_pol_probe.sh`; `POL_MODE=arrest|fight|car`, `POL_STARS`, `POL_COPCAR`,
`POL_HOLD`, `POL_SECS`, `POL_REWARP`), `pol_vehicles.py` (`keys_pol_vehicles.sh`; `POL_VEH="tank firetruck
train bus army rescue"`), `pol_sheet.py` (the sheet), mirrored in `gamerun/`. Run with
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 260 keys_pol_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_LOG_VEHICLES=1 -e POL_MODE=arrest -e POL_STARS=2 -e POL_COPCAR=1 -e POL_HOLD=600`.
Sheet: `out/police_3d_sheet.png` (local, not in git).

## ACTIONS-3D-3 (8 Nov 2026): soldiers, every ped type, police gunfire, trains, fire truck

Runs `out/a33_*` (L4 GPU build, private stage `stage_a33`), probe `linux/docker/a33_probe.py`
(`keys_a33_probe.sh`; `A33_ITEMS="types army gunfire train firetruck ambulance"`), police runs with
`pol_probe.py` (`POL_MODE=fight POL_COPCAR=1 POL_STARS=4|5`), rescue with `pol_vehicles.py`
(`POL_VEH=rescue`). Sheet `out/actions_3d_3_sheet.png` from `linux/docker/a33_sheet.py out linux/docker/a33_tiles.json`.
Run with `STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 330 keys_a33_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_LOG_VEHICLES=1 -e GTA2DX9_PED_REMAP_FILE=a33_remap.txt -e A33_ITEMS=...`
(the train with `GTA2_SPEED=3 CPUS=4`).

**Why the soldiers were flat yellow.** Not the ped type, the remap or a sprite path: the army remap (4)
maps to the three Rocketbox military avatars, and the 3D figure was drawn. Their body, helmet and
equipment textures were never fetched: Rocketbox ships the military colour maps only as
`*_color_acu.tga` (and medic 02's body as `m154_body_color_blue.tga`), and both fetch scripts kept only
names ending in `_color.tga`. With no texture the importer gives a material its 1x1 fallback
(`00 FF FF 7F` BGRA: yellow), so every soldier was a yellow silhouette with his rifle. The same gap
left `human_medical_male_02`'s body and `human_police_male_03`'s kit (its FBX material is spelt
`m172_equpiment`) yellow. Fixed in the asset pipeline: `tools/fetch_rocketbox_pro.sh` takes any
`*_color*.tga`; `tools/make_ped_manifest.py` maps `<mat>_color[_variant].tga` to the material (plain,
then `_od`, then any variant) and gives a misspelt material the nearest texture name;
`tools/army_olive.py` (new) writes olive-drab copies (`*_color_od.tga`) of the grey ACU camo, so
GTA2's army reads green (skin and coloured patches kept). The five avatars were re-imported
(`tools/import_assets.py ../assets-src/manifest.json assets/models --only human_military_male_01,human_military_male_02,human_military_female_01,human_medical_male_02,human_police_male_03`);
the avatars are not in git, so ship a fresh people archive. No placeholder texture is left on any human model.

**Peds without a remap palette.** SWAT and FBI (DMA's EMERG_GRAPHIC) and the Zaibatsu gang graphic are
drawn from their own sprite sets, not a remap of the common body, so `PedRemapForPalette` returned -1 and
they got random civilian avatars (`a33_pol4 shot_200`: SWAT firing pistols in plain clothes). Now a figure
with no remap palette takes its type from its sprite body (frame / 158): body 2 or later -> the police
avatars, body 1 -> the suits (`live_geometry.cpp`, logged once per body as `models: pedestrian without a
remap palette on body N`). Built and staged, **not yet seen in a run** (no SWAT came in `a33_pol4b`); which
body SWAT/FBI really use is the log line's to confirm.

**Showcase switch.** `GTA2DX9_PED_REMAP_FILE=<file>` (re-read every 15 frames, `-1` off) sets
`ped_remap_override` while the game runs; with an override on, the player's own figure is drawn as that
type too, so the sheet shows each type on a figure the camera follows.

**The driven car in the chase view.** A car whose box holds the camera was skipped (meant for the camera
beside a parked car) unless it was the "own" car, which is only set in first person. A long vehicle at the
wheel (fire truck, bus) could vanish from the chase view (`a33_fire1`: no truck in any chase frame). The
car the located player ped is in (`ped+kPedVehicle`) is now never skipped (`CarBodyUse::driven`). In
`a33_fire2` the truck is in the chase frames; that this guard is what changed it is not isolated.

**NPC shots logged:** `GTA2DX9_LOG_PED_FRAMES=1` adds `npc shot: object weapon (game|flash) ammo reload` (up to 80).
Police and FBI weapons never lose ammunition (990); a shot shows as the reload timer restarting.

### Status (ACTIONS-3D-3)

| item | status | evidence |
|---|---|---|
| army soldiers: green uniform, helmet, rifle | verified in third and first person (game-driven, 6 stars); classic is the game's sprite, untouched | a33_types1 `army1_t_07`, `army1_t_12`; a33_types2 `army0_f_05`, `army0_tx_13` |
| every remap type as a textured 3D figure (police 0/1, army 4, redneck 5, scientist 7, zaibatsu 8, krishna 9, russian 10, loony 11, elvis 12, yakuza 13, fireman 14, medic 16, mugger 17, prisoner 22, civilians 15/27/52) | verified as a showcase (forced remap, player and crowd), no flat figure left | a33_types2 `type_*_side` |
| game's own types in play | verified: army, police (remap 0), FBI as suits, civilians, zaibatsu, mugger, elvis (log) | a33_types1/2, a33_gun1, a33_pol4/5 logs |
| hulk (23, 24), naked dummy (26) | no type in the manifest: plain civilians | sheet |
| prostitutes | GTA2 has no such ped type in DMA's remap table; none drawn | ped_types.json |
| SWAT / FBI / Zaibatsu-graphic peds (no remap palette) | mapping built, unverified in a run | log line to check |
| police gunfire at 4 stars | verified: officers with pistols in the aim stance, player shot dead; 9 game shots logged | a33_pol4 `shot_200` |
| FBI gunfire at 5 stars | log (16 shots: silenced MG, shotgun); agents framed beside their car, not mid-shot | a33_pol5 `qa_f_006` |
| NPC muzzle glow / streaks in a frame | not singled out in a frame (the shots fell between the probe's frames or behind the camera) | - |
| driving away at 4-5 stars | the van stuck in a dead end (a33_gun2); at 5 stars FBI dragged him out and busted him (a33_gun1); no shots at the car | a33_gun1/2 |
| trains | verified: cab and carriages at track height, moving forward, stopping at the station | a33_train1/2 |
| fire truck: in, drive, beacons, water cannon | verified (siren by Tab; beacons over the cab and roof; jet in first person and classic) | a33_fire2 |
| fire truck first person | open: the eye sits behind the roof gear (the cabin placement for model 17) | a33_fire2 `ft_drive_06` |
| chase camera on a long vehicle | the camera trails far behind the truck for the first seconds (camera file, not changed) | a33_fire2 `ft_drive_03` |
| ambulance | not framed: beacons logged on a driven one (a33_resc1, 12 lines), it had left before each warp; none came in a33_fire2 / a33_amb1 | a33_resc1 log |

## Ped and car log lines (8 Nov 2026, PLAYTHROUGH-9)

Two renderer log lines give a script every pedestrian and car round the player, so a runner
has targets: "run over N gang members", "shoot the marked characters", "follow that car",
"is someone about to pull me out of the car". Written by `LogPedsAndCars` in
`dll/src/world_view.cpp`, every `GTA2DX9_PEDS_EVERY` frames (default 10; 0 turns them off),
parsed by `mission_lib.peds()` / `mission_lib.cars()` (`gamerun/`, mirrored in `linux/docker/`).

**Where the peds come from.** The game's ped pool, not the drawn sprites (a ped in a car or
behind the camera is not drawn). In 9.6 the `PedPool*` is at **`0x5E5BBC`**: the pool object
has the free list at `+0`, the live list at `+4`, and `Ped[200]` from `+8` at a stride of
`0x294`; a ped's next is `+0x160`. Found at run time on 8 Nov (a scan of the exe's writable
sections for a word whose object's `+4` chain reaches the player's ped, then checked: the
player's ped is pool record 0, `id 1`, occupation 0) and kept as a fallback scan
(`FindPedPool`, logs `view: peds: ped pool at 005E5BBC`). The layout and the field names are
those of the GTA2 decompilation (`CriminalRETeam/gta2_re`, `Ped.hpp`, `Char_Pool.hpp`), which
targets a later exe: its global addresses are not ours, but its structures are (its car
offsets `+0x4C` next, `+0x50` sprite, `+0x54` driver, `+0x74` damage, `+0x84` model are the
ones this renderer found by probing 9.6). Ped fields used:

| offset | type | field |
|---|---|---|
| `+0x160` | ptr | next live ped |
| `+0x168` | ptr | the ped's game object (null while in a car) |
| `+0x16C` | ptr | the car he is in |
| `+0x17C` | ptr | his gang (null: not a gang member) |
| `+0x1AC/0x1B0/0x1B4` | 16.14 | x, y, z (stale while in a car: the car's position is logged instead) |
| `+0x200` | u32 | ped id (the player is 1) |
| `+0x216` | int16 | health (peds 50, the player 100) |
| `+0x240` | int32 | occupation (`gta2_re` `ped_ocupation_enum`: 0 player, 3 dummy, 4 the traffic's shared driver, 10-13 robbed driver / angry / armed, 14 psycho, 15 mugger, 16 car thief, 17 bank robber, 19 armed gang member, 22 Elvis, 23 paramedic, 24 police, 25 SWAT, 26 FBI, 27 army, 37 roadblock cop, 38 fireman, ...) |
| `+0x244` | int8 | remap (the palette: 0 police, 4 army, 5 redneck, 7 scientist, 8 zaibatsu, 9 krishna, 10 russian, 11 loony, 12 elvis, 13 yakuza, ...; -1 none; the player 25) |
| `+0x278/+0x27C` | int32 | state, sub-state (as `view: player`: 9 dead, 8 knocked down with the sub-states of `game_access.h`, 10 in a car) |

**`view: peds frame=F live=N near=K` then one item per ped** within 24 blocks of the player,
nearest first, at most 28:

    id:type/gang:remap:occupation:x,y,z:state:sub:health:car:mark

`type` is `gang` when the gang pointer is set, else from the occupation (`cop`, `swat`, `fbi`,
`army`, `emerg`, `elvis`, `mugger`, `crim`, `guard`, `civ`); `gang` names the remap
(`russian`, `scientist`, `zaibatsu`, ... or `civ`); `car` is `m<model>` while he is in a car
(the position is then the car's), `-` on foot; `mark` is `a<slot>` when an objective arrow of
kind 2 (a character) names him (the arrow slot's target words `+0x30/+0x34/+0x38/+0x5C` hold
the ped or his game object) or stands within 0.6 blocks of him, else `-`. `frame` is the
renderer's frame count (one game step per frame).

**`view: cars frame=F near=K` then one item per car** within 30 blocks (the vehicle list,
nearest first, at most 20), the player's own included:

    id:m<model>:x,y,z:hx,hy:v:hp:fire:driver:mark

`hx,hy` the heading (the game's sin/cos of the sprite's angle), `v` the speed in blocks per
game second from the car's own last positions (frame-count based), `hp`/`fire` as `carhp`/
`carfire` in the mission line (32000 - damage; 0, 1 burning, 2 burning hard), `driver` `P`
for the player, `-` empty, else `type/gang` of the ped at `+0x54`; `mark` `a<slot>` for a
kind-3 arrow on it.

## ACTIONS-3D-4 (8 Nov 2026): feet that do not slide, fists with weight

Reported in play: "the punching animations don't look realistic, and occasionally, for instance when
exiting a vehicle, the character appears to slide across the ground."

**Why the figure slid.** The walk cycle only advanced when the drawn figure was faster than 0.45
blocks a second, and then at most 2.6 cycles a second; below the threshold, or above the cap, the
game moved the figure and its feet did not follow. Getting out of a car is exactly that case: the
game slides the ped out of the door sideways at 0.15-0.6 blocks a second for 0.8 s (state 4 sub 7,
sprite frames 36 down to 28, then 28-31, measured with the new `GTA2DX9_LOG_FIGURES=1` trace,
`out/a34_before`), while the figure played Rocketbox's 4.5 s "crouch out" on the spot and kept
crouching for two seconds after. Getting in was the mirror (state 3 sub 6, frames 24-35: the game
backs him 0.15 off the door, then moves him 0.3 into the seat). The game's player runs at 1.9
blocks a second, four body heights; the run clip covers 0.52 blocks a cycle, so the cap cost a third
of the stride. And the walk and run clips were blended at the same phase although the run puts the
other foot forward (the walk's phase 0 is the run's 0.5): a walk/run blend cancelled the legs.

**Locomotion now (`DrawPedFigures`, `live_geometry.cpp`).**
- The legs are driven by the drawn figure's own displacement each frame (spring-followed position
  plus any stagger or arrest offset), projected on the legs' heading and signed: pushed back, he
  steps back. No cap. Idle below 0.04 blocks/s, moving above 0.08 (hysteresis).
- Walk, run and a new `sprint` blend by that pace (run from 0.6 to 0.9 blocks/s, sprint 1.2 to 1.7).
  `sprint` is the run with the legs' swing widened 1.45x about its mean (arms 1.1x, a little out from
  the hips); its stride is the run's x1.405 (measured from the feet's reach by the generator,
  `kSprintStrideOverRun`), so at 1.9 blocks/s the legs cycle 2.5 times a second instead of 3.6.
  The run and sprint are played half a cycle on from the walk so blends agree.
- Stopping settles: the cycle runs on (or back) to the nearest phase where the feet pass each other,
  in 0.2 s, while the idle fades in.
- Turning on the spot steps the feet: `turn_step`, a legs-only layer over the idle (thighs and
  below), one cycle per 100 degrees turned, finishing to feet-together when the turn stops.
- The action is a third clip over the locomotion pair (`ModelSetOverlay`, `model_store.cpp`; part of
  the pose cache key), so every upper-body action has walking legs under it and an action that ends
  fades out from where it stopped instead of popping (`fadeClip`).
- Fixed in the model store: a blend at full weight sampled the second clip over the bind pose, so a
  clip without channels for some joints left them in the T/A pose (seen as the arms flung out while
  turning in the first build of this pass).

**Cars.** New upper-body clips `enter_car` (reach for the handle, pull the door, duck under the roof
with a hand on the roof edge, fold in; its reach and pull are held while the game backs him off the
door, frames 24-31, the duck runs once it moves him in, 32-35) and `exit_car` (from the duck, a hand on
the frame and one on the door, standing up over 0.7 s - inside the game's 0.8 s exit - then done: no
crouch is held after, and if the game keeps him there he stands in the idle beside the door). While
getting in the figure faces the car, while getting out it faces away from it (the car's middle is
followed every frame); the legs step whatever the game moves him meanwhile.

**Boarding a moving car.** The game carries the ped along with the car in state 3 (sub 4, sprite
frames 8-23) until the climb (sub 6, frames 24-35). The car's own pace is measured from its body
frame to frame; while it moves (over 0.3 blocks/s) and he covers ground faster than a walk, he
runs beside it: heading along his motion, legs cycling at the pace the game moves him (walk, run
or sprint by speed), with `grab_door_r` / `grab_door_l` over the run (the near hand on the door
handle at waist height, the torso leaning to the car, the head turned to it; the far arm keeps the
run's swing; the hand is chosen once, by which side the car is on). The climb then starts
`enter_car` at its duck (0.65 s), the pull-in. A parked car's boarding is the walk to the door
and the reach as before.

**Fists.** `punch` (right cross, 0.8 s: the wind-up turns the shoulders and the right fist back, the
strike leads with the torso turning 50 degrees and leaning in, the arm straightens last, a
follow-through, back to the guard) and `punch2` (left jab), alternated on every repeat of the game's
swing (sprite frames 115-122, 0.1 s each, repeated while the key is held; a swing within 1.2 s of the
last continues the combo), the other fist guarding the chin throughout; upper-body layers, so the
legs walk or stand under them. A swing restarts only when the game's frame goes back to 115-116
after 0.5 s of it (the first build restarted on the jumps between the swing and recovery frames the
game makes while he walks with the key held, cutting punches off at 0.4 s). The blow lands when the
game says so: a figure whose health word (ped+0x216) drops while a figure within 0.7 block is
mid-swing takes `hit_head` / `hit_head2` (the head snaps back and away from the fist, the chest
recoils, the hands come up, 0.55 s; which way by the puncher's hand) and a 7 cm stagger along the
blow over 0.15 s, back over 0.6 s, which his legs step; if the game knocks him down (state 8 sub
0x16) the lying clip takes over as before. (A first build hit whoever stood ahead at the strike key;
most of the player's swings miss in the game, so that made people flinch at misses.) GTA2 has no kick: no kick frame range is in the ped sheet (`assets-src/humans/ped_states.json`)
and none was seen in the runs, so none was made.

**Arms through the torso.** `tools/gen_ped_clips.py` now checks every clip at its keys and halfway
between them (elbows, mid-forearms and hands against an elliptic cylinder from the pelvis to the neck,
13 x 10 cm plus a 3.5 cm limb radius) and prints offenders. It found eight existing clips with a limb
inside the body: `fall` (both arms folded across the chest when lying: now out to the sides),
`aim_heavy`, `aim_launcher`, `carry_launcher`, `carry_heavy` (right elbow in the chest: now out at the
side), `throw` (both forearms through the hip and chest on the swing), `runover` (arms swept through
the body mid-air) and the derived sprint. Left after the fixes: `punch`, `punch2`, `hit_head2` touch
by 2 % (an elbow against the ribs in the guard), which is contact, not passing through.

Files: `dll/src/live_geometry.cpp/.h`, `dll/src/model_store.cpp/.h`, `tools/gen_ped_clips.py`,
`assets-src/humans/clips/ped_clips.json` (outside the repo), the 41 avatars re-imported
(`assets/models/manifest.json` committed; the avatars are not in git: ship a fresh people archive),
`linux/docker/a34_probe.py` + `keys_a34_probe.sh` (bursts at 15 fps per item), `a34_sheet.py`,
`a34_tiles.json`, mirrored in `gamerun/`. Probe:
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 330 keys_a34_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_LOG_FIGURES=1`.
Sheet `out/actions_3d_4_sheet.png`, clip `out/actions_3d_4.mp4` (local, not in git).

### Status (ACTIONS-3D-4)

Runs `out/a34_before` / `a34_before2` (the build before this pass, with only the trace added) and
`a34_after1..8` (this pass's builds), private stages, L4 GPU, 15 fps bursts. Sheet
`out/actions_3d_4_sheet.png`, clip `out/actions_3d_4.mp4` (25 s).

| item | status | evidence |
|---|---|---|
| getting out of a parked car (third person) | verified: stands up from the duck in 0.7 s while the game slides him out, faces out, legs step the 0.3-block slide (trace: cycle advances with the drawn motion), then idle beside the door; no crouch held (before: Rocketbox crouch_out, 2 s of crouch after the state ended) | a34_after6 `exit_third`, a34_after1 trace frames 568-607 |
| getting out (first person) | not judged: from the eye the own figure is hidden; nothing to see in the bursts | a34_after6 `exit_first` |
| getting into a parked car | verified: the reach and the door pull, stepping back as the door opens, then in | a34_after6 `enter_third` |
| boarding a moving car | verified: runs beside it (legs at the pace the game carries him, heading along the motion), near hand on the door, `enter_car` duck as the climb starts; seen on a carjack of a car still rolling. Before: an upright figure carried along | a34_after8 `moving_1` (grey picture: another agent's work-in-progress grading in the shared tree at build time, not this pass), a34_after7 `moving_1`; before a34_before2 `moving_3` |
| feet on the ground, walk/run/sprint | verified: no cadence cap, run and sprint blended by pace, run half a cycle on from the walk; sprint at 1.87 blocks/s (trace `sw=1.00 leg=1.87`) | a34_after7 `walk_0`, a34_after1 trace frames 1816-1870 |
| stopping | verified: cycle settles to the feet-passing phase in 0.2 s while the idle fades in | a34_after1 trace frames 1878-1918, a34_after7 `walk_0` |
| turning on the spot | verified: turn_step at full weight while the heading turns 3 rad/s, arms down (the first build left the arms in the bind pose: fixed in the model store) | a34_after7 `turn_2`, a34_after1 trace frames 1950-1990 |
| punch combo | verified: cross/jab alternate on every repeat of the game's swing (log `fig: punch ... cross/jab`), guard hand at the chin, torso-led strike; the target knocked down by the game falls with the lying clip | a34_after3 `punch_0` |
| taking a punch | log + showcase: `fig: hit ... health 50 -> 20` on an NPC fist fight (a34_after3, a34_after5); the clip seen on the forced player. Most of the player's punches knock the target down (lying clip) or miss, so a non-knock-down hit was not caught in a burst | a34_after6 `hitshow_side` |
| kick | none: GTA2 has no kick frames | ped_states.json |
| arms through the torso | checked in the generator for every clip; 8 fixed, 3 at 2 % contact | `gen_ped_clips.py` output |
| NPC peds | same code path; NPC walkers seen stepping in the bursts; NPC boarding a moving car not singled out | bursts |

## Reloading (8 Nov 2026, QB-29)

GTA2 has no magazines: a weapon fires until its ammunition (`+0` of the weapon object, stored x10 of
the HUD count) is gone, and the `+2` word is a per-shot cooldown, not a reload. The renderer gives each
gun a notional magazine and plays a reload when it is spent and he stops firing:

- **Magazines** (`kReloads` in `dll/src/live_geometry.cpp`): pistol 6 (a pickup is 10 shots), dual
  pistols 12, machine gun and silenced MG 30, shotgun 6, rocket launcher 1. None for the electro gun,
  flamethrower, molotov, grenade. A shot is the existing `gameShot` (ammunition dropping or the cooldown
  restarting, so police with 990 rounds reload too); a new gun starts full; ammunition going up (a
  pickup) after shots fired reloads too.
- **When:** the magazine spent and 9 frames since the last shot (while the attack is held the game sits
  in the firing frame, so a continuous burst never reloads; letting go does). A shot during the reload
  cuts it off (the game fires regardless). `GTA2DX9_RELOAD=0` turns it off.
- **Clips** (`tools/gen_ped_clips.py`, upper-body layers, one shot, starting and ending on the weapon's
  carry pose): `reload` 1.40 s (pistol up to the chest, mag tipped out 0.30 s, left hand to the belt,
  into the grip 0.80 s, racks the slide 0.98 s), `reload_heavy` 1.55 s (gun rolled, left hand pulls the
  mag 0.35 s, a fresh one from the chest pouch, seated 0.95 s, charging handle 1.12 s), `reload_launcher`
  1.20 s (tube down off the shoulder, a rocket from over the left shoulder 0.40 s, into the tube 0.85 s).
  Actions 24-26. All pass the generator's arm/torso check. An avatar imported before these clips drops
  the action (no stuck pose).
- **The gun while the left hand is away:** a long gun is normally laid from the right hand to the left;
  during a reload it keeps the line it last had in the right hand's frame (`gripLocal`, taken every frame
  both hands hold it), so it moves with the right hand.
- **Magazine:** a dark particle (kind 6) drops from the magazine well at the clip's drop time and lies on
  the ground for 2.5 s; the fresh one rides in the left hand from the pouch to the gun.
- **First person** (the own figure is not drawn): the same count off the player's ammunition word, timed
  in real seconds; the view model dips, tips its muzzle up and rolls, a jolt back on the slide, the spent
  magazine drops and the fresh one rises into the well.
- **Sound:** three synthesized clicks (magazine out, seated, slide), 22.05 kHz through `waveOut` so they
  mix with the game and do not cut the voice-over (`PlaySound` plays one sound at a time); the player's
  reloads only. `GTA2DX9_RELOAD_SOUND=0` turns them off.
- **Log:** `reload: <object> (player) <weapon> starts`, `... magazine out/in at t=`, `reload: first
  person ...`, `reload: click N` (capped).
- **Assets:** the 41 avatars re-imported with the three clips (`tools/import_assets.py ../assets-src/manifest.json
  <dir> --only human_...`; only the `.mesh` files change, the textures are byte-identical). The clips JSON
  was regenerated from `Male_Adult_01` + `idle_breathe` (that pair reproduces the previous file byte for byte).

### Status (QB-29)

Runs `qb29_r3`..`qb29_r9` (private stage: this build + the re-imported avatars, L4, the host at load
15-35, so clips ran slow in wall time); probe `gamerun/qb29_reload.py` (collect pistol, MG, launcher;
burst, let go, 8 fps frames for 7 s, then first person).

| item | status | evidence |
|---|---|---|
| MG reload, third person | verified: log `starts` 9 frames after the last of 53 shots, `magazine out at t=0.37`, `in at t=0.97`; frames: the left hand leaves the gun, drops, goes to the chest pouch, back under the gun, carry again. Seen from behind (the chase camera swings behind a shooter), the gun half hidden by the body | qb29_r8 `r_machine_gun_reload_third_06..30`, qb29_r9 |
| MG reload, first person | verified: the view model drops low and left, muzzle up, rolled, back to the carry; mag out 0.38 s, in 0.95 s | qb29_r8 `r_machine_gun_reload_fp_04..28` |
| launcher reload, third person | verified: tube down off the shoulder and back; `rocket in at t=0.87`; a shot during the reload cuts it off (log) | qb29_r5 `r_rocket_launcher_reload_third`, qb29_r9 log |
| launcher, first person | log only (`first person magazine in at t=0.87`) | qb29_r5, r9 |
| pistol reload | log only (six aimed shots, `starts`, out 0.30, in 0.80); the frame burst came too late | qb29_r9 |
| falling magazine, held magazine | spawned (log times), not singled out in a frame (a small dark particle) | - |
| clicks | `reload: click 0/1/2` logged at the events; not heard (no audio capture in the runs) | logs |
| NPCs (police 990 rounds) | same code path (their cooldown restarts count as shots); not filmed | - |

## CROWD (8 Nov 2026): people's own clothes and builds, heads that follow the player, glances

Street views only (third and first person); the classic view is untouched. `[crowd]` in
`package/gta2dx9.ini` (`variety`, `look_at`, `look_range`), `GTA2DX9_CROWD=0` turns all of it
off for a run.

- **Clothes** (`CrowdLookFor`, `live_geometry.cpp`): a civilian (no remap, remap 15 or 18-52
  except 22: the manifest's `civilian_*` types) three times in four gets an everyday clothing
  colour from a palette of 20 (navy, charcoal, beige, olive, burgundy, denim, mustard, teal...):
  the avatar's `_paint` half multiplied 85% of the way toward it (the existing paint-tint stage,
  so it costs no pose and no texture). With 4 avatars per civilian remap, 20 colours plus the
  avatar's own and the builds below, one avatar is now ~80 different-looking people. Uniforms
  (police, army, medics, firemen, suits) and gang colours are unchanged; the player is unchanged.
- **Builds**: height x0.94-1.06 and width x0.95-1.05 per person (the placement's fit matrix), for
  everyone but the player. Fixed by the ped's object, like the avatar choice.
- **Look-at**: a person with no action clip on, the player within `look_range` blocks (default
  5; doubled for 3 s after the player fires) and within 110 degrees of the way he faces, turns
  his head to the player: `ModelSetHeadTurn` (`model_store.cpp`) turns `Bip01 Neck` 40% and
  `Bip01 Head` 60% about the model's vertical, clamped to 70 degrees (50 walking), eased over
  0.25 s at up to 230 deg/s. One passer-by in four does not look (unless the player is shooting).
- **Glances** (idle behaviour): otherwise a standing person glances left or right every 3-8 s
  for 1-2.5 s (up to 70 degrees), a walker every 5-12 s (up to 35). Over the existing three idle
  clips (`idle`, `idle2`, `idle3`, picked per person).
- **Cost**: the head turn is part of the pose-cache key, quantised to 6 degrees for the nearest
  figures (LOD 0), 12 for LOD 1, none beyond 18 blocks.
- **Log**: every 300 drawn frames, `crowd: N figures drawn, N in clothes of their own, ...` and
  `crowd: last 300 frames: N figure-frames within look_range, N passed over, N with the player
  behind them, N looking`.

Verified (plain renderer, L4 host, private stage, `gamerun/crowd_probe.py` via
`keys_crowd_probe.sh`: warp to the Downtown pavement at 165.5,140.5, first then third person):
run `crowd_r5` logged 6-10 of 7-12 drawn figures in clothes of their own, and 144-407
figure-frames looking at the player per 300 frames while people were within 5 blocks; frames
show passers-by in varied clothes and a walker's head turned toward the player; no faults. Run
`crowd_r6_off` (`GTA2DX9_CROWD=0`) logged `variety 0, look_at 0` and 0 of each. Frame times
unchanged in kind (the one 59 s frame in `crowd_r5` is the governor's pause of the container,
23:11-23:12).

Not done (rows 23/39): no children or elderly avatars and no carried props (bags, phones,
umbrellas) — they need new Rocketbox imports, which stay out of git; no stop/settle clip and no
fidget clips (new clips in `tools/gen_ped_clips.py` mean re-importing the avatars). Untested:
the look-at under RTX Remix (Remix down on this host), and the gunfire range doubling (the
probe did not fire).

## QB-16 (8 Nov 2026): hit reactions in real fights (shot, punched; peds and the player)

Quality-bar row 16 said a shot ped "keeps walking until the game puts him down". The punch
reaction (ACTIONS-3D-4) only fired when a figure within 0.7 block was mid-swing, so a bullet
never moved anyone, and a reaction over a carry or an aim was cut off the next frame.

**Mechanism.** `DrawPedFigures` (`dll/src/live_geometry.cpp`): every figure's health word
(ped+0x216) is compared with last frame's. A drop with a puncher beside him is the punch
reaction as before. A drop with nobody mid-swing is put to a shooter: each drawn figure now
leaves its last shot frame (`muzzleFrame`: the game's own ammunition/reload words, or a
flash beside him), its facing and its weapon in `FigureSpot`; the shooter is the figure that
fired in the last 0.7 s within 12 blocks whose facing is within 60 degrees of the line to
the victim (the best aligned and nearest). The bullet's direction against the victim's own
facing picks one of four new upper-body clips (`tools/gen_ped_clips.py`, 0.6 s, one shot):
`hit_shot_front` (thrown back at the chest, then folding over the wound, a hand to it),
`hit_shot_back` (pitched forward, head and arms flung back), `hit_shot_l` / `hit_shot_r` (the
struck shoulder driven back, bent away, the hand clutching it). The whole figure staggers
along the bullet (8 cm for a pistol, 10 for a machine gun, 16 for a shotgun; out over 0.15 s,
back over 0.6 s; the legs step it). The layer is upper body, so a running or walking man
keeps his legs going under it. The reaction (shot or punched) is now held to its end over the
walk, the carry and, for a bullet, the aim; a man shot as he squares up to fight (the game
starts his swing frames the instant he is hit) takes the jolt for 0.35 s before his swing. A
second hit restarts it. A hit that kills goes straight to the lying clip as before (a pistol
bullet kills a pedestrian outright in GTA2; the machine gun's take 25 of a ped's health, so a
short burst leaves him standing). Avatars from before this fall back to `hit_head`.
`GTA2DX9_SHOT_HITS=0` turns the shot reactions off.

**Log** (`GTA2DX9_LOG_PED_FRAMES=1`): `fig: shot <victim>[ (player)] by <shooter> (weapon N,
D blocks, front|back|left|right) health a -> b`, then `ped anim: object ... action 22`. An
unexplained drop: `fig: health ... nobody mid-swing within 0.7 or firing at him (... cause C;
nearest shooter D blocks facing F)`. Probe aid: `GTA2DX9_LOG_NEAR_PED=1` logs the nearest
figure to the player (`qb16: near ped d= bearing=`) three times a second, for scripts that
turn onto someone.

**Probe.** `linux/docker/qb16_hits.py` + `keys_qb16_hits.sh` (mirrored in `gamerun/`):
pistol and machine gun pickups, then on QB-6's busy pavements it turns onto the nearest
person, closes in and fires two 0.1 s taps (about two bullets each), with frame bursts at
10 fps (`/out/qb16_marks.txt` holds each burst's start). `QB16_VIEW` (first) picks the view,
`QB16_ARMY_SECS` (150) a 6-star wait for soldiers. Run:
`STAGE=<stage> GTA2_DIRECT_KEYS=1 INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> 480 keys_qb16_hits.sh -e GTA2DX9_LOG_PED_FRAMES=1 -e SCENE_KEY=F11 -e GTA2DX9_LOG_NEAR_PED=1 -e GTA2DX9_SCENE_NO_CAR=1`.

**Verified (plain renderer, Downtown, runs `qb16_r3`, `r6`, `r8`, `r9`; a heavily loaded host, so
the governor paused most runs for minutes and each produced one or two hits).** Five real shot hits
were logged on pedestrians who survived them, all from the player's machine gun: `fig: shot ...
(weapon 4, 0.2 blocks, front) 50 -> 25` (r3), `0.9 blocks, back` (r6), `3.2 blocks, back` (r8, first
person, through the eye stand-in), `1.5 blocks, left` and `3.8 blocks, back` (r9); each followed by
`action 22` on the victim in the same frame, and QB-6's `aim: hit` line agreeing on the victim and
the health. Frames: `out/qb16_r9/qb_st2_machine_gun_0_025..048.png` (third person, the player in the
striped shirt firing at a man in a navy shirt 1.5 blocks away: the hit marker at frame 36, his
shoulders turning over 36-40, then the game turns him to run). In r3 the victim squared up to punch
0.11 s after the bullet and the swing took the layer back: fixed (the 0.35 s hold above). Seen as a
limit: at chase-camera distance the flinch reads as a short shoulder jolt, not a big one.
**Not verified:** the player being shot. In 4.5 min at 3, 4 and 6 stars no officer or soldier hit
him: at 3-4 stars the police punch and arrest (his punch reactions fired: `fig: hit <player> by
<cop> (cross) 100 -> 90`, r2/r3), and the army did not reach him at the plaza (r4-r6). The code path
is the same (the player's figure has the same health word and track), untested. A shotgun's larger
stagger: untested. Both machine-gun hits whose log line carries the cause word (`ped+0x290`) had cause 11, so
the lying-clip rule that reads 11 as burnt (ACTIONS-3D-3) may give a man shot dead the burnt pose:
for QB-17 (death) to check.

## Jacking a driver (9 Nov 2026, QB-14)

What the game does (probe runs `qb14_before2`, `qb14_after3`, `gamerun/qb14_probe.py`, dense
`GTA2DX9_PEDS_EVERY=2` ped lines): the jacker boards with exactly the states of an empty car (state 3:
sub 4 the walk and reach, frames 12-19; sub 6 the climb, frames 24-35, ~1.4 s). The driver, out of
sight in the car until then, appears beside the door about 0.6 s into the climb in state 8 sub 0x11
(thrown, 0.5 s, sliding ~0.45 blocks off the car), lies knocked down (sub 0x19, then 0x16, ~2.3 s),
then gets up and walks or runs off with full health. Sometimes the game lets the driver step out
instead (state 4 sub 7, the ordinary exit) as the jacker reaches the door. Before this pass the
jacker played `enter_car` and the thrown driver played the `hit` stagger and then the `runover`
lying clip (sub 0x19 is in the car knock-down range), so he flew up and over as if run down.

Now (`dll/src/live_geometry.cpp`, `tools/gen_ped_clips.py`):

- **Telling a jack.** Every car drawn records where it is and whether its driver word (`+0x54`) is
  set (`g_carSeats`). A ped in state 3 at the door (reach or early climb frames 16-27) with the
  nearest car within a block having a driver is jacking (`PedTrack::jacking`), and his `enter_car`
  layer becomes `jack_pull` (same action 5).
- **`jack_pull`** (upper-body layer, 1.95 s): the hand to the handle (0.30), the door yanked wide with
  the shoulders thrown round (0.50), both hands into the doorway (0.80), the grip (0.95), the haul
  leaning back with the fists to the chest (1.20), the fling to his left (1.40), and `enter_car`'s duck
  (1.65, 1.95). Timed by the game: held at 0.50 until the climb starts, held at 0.95 until the driver
  is seen coming out beside him (thrown or stepping out), then real time, faster once the game moves
  him in (frames 32+). From a run beside a moving car (`grab_door_*`) it picks up at 0.50.
- **The driver.** A fresh track in state 8 sub 0x11 within 1.2 blocks of a ped in state 3 is the jacked
  driver (`PedTrack::jacked`): he is turned to face the car and plays lying clip 5, `jacked` (whole
  body, 1.0 s: still folded as if seated with the arms reaching back for the wheel, the feet swung
  out, two stumbling steps back with the arms windmilling, over onto his back, a bounce), held lying
  through the knock-down; its last pose is exactly `fall`'s, so getting up is `fall` played backwards
  like any knock-down. A driver who steps out keeps `exit_car`.
- Logged with `GTA2DX9_LOG_PED_FRAMES=1`: `jack: <ped> boarding a car with a driver`, `jack: driver
  <ped> thrown out` / `stepping out`.
- Avatars imported before this pass fall back to `enter_car` and `fall`. The 41 avatars were
  re-imported (`assets/models`, not in git; manifest report updated).

### Status (QB-14)

Runs `qb14_after1`..`qb14_after5` (private stage: this build plus the re-imported avatars, plain
renderer on the L4, the host at load 15-40 with governor pauses). Remix not tried (down on this host).

| item | status | evidence |
|---|---|---|
| player jacks a stopped car, third person | verified: `jack_pull` held at t=0.95 (hands in) until the driver was thrown at climb frame 28, then 1.51 by frame 33; frames show the reach and yank, the driver hauled out arms up, stumbling back and onto his back, lying while the player ducks in | qb14_after5 `b_jack_3.mp4`, `qb14_jack_sheet.png`, log `player figure` lines |
| AI carjackers | same path: driver thrown out next to the boarding ped, `jacked` from the throw (two in qb14_after5, one in qb14_after1) | logs |
| getting up after `jacked` | log only (qb14_after1: the driver back to action 0 in state 1 after the knock-down); not filmed (the player drove off) | qb14_after1 log |
| driver steps out (state 4) | the jacker's haul is released by it (code); seen once in qb14_after3, before that release was added | qb14_after3 log |
| jacking a moving car | not filmed: traffic at the probe kerb did not come close enough in the after runs; code path is `grab_door_*` -> `jack_pull` at 0.50 | - |
| a passenger boarding an occupied car | untested: would show the reach and the hands-in hold, then the duck (no throw seen) | - |
| classic top-down view | untouched (figures are drawn only in the street views) | - |
## QB-27 (9 Nov 2026): ragdolls for people run over or blown off their feet

Quality-bar row 27: the `runover` lying clip was the same canned arc whatever the car's speed or
side. Now a person struck or run over by a car (lying clip 2: cause 1/3, sub-states 0x18-0x1A) or
blown off his feet (lying clip 3: cause 4) goes down as a ragdoll in the street views.

- Solver (`dll/src/ragdoll.cpp/.h`): position-based (Verlet, 120 Hz substeps, 6 iterations), 17
  particles on the Bip01 joints (pelvis, chest, neck, head, a head-top point, shoulders, elbows,
  hands, hips, knees, feet). Torso rigid (all pairs of pelvis/chest/neck/shoulders/hips), limbs at
  their seed lengths, ranges that stop a knee or elbow folding flat, the head sinking into the
  chest or the legs passing through each other, hinges (knees bend forward, elbows back), gravity
  3 blocks/s^2, ground at the victim's floor with friction and a 0.15 bounce, the map's walls
  (`ViewQueries::blocked`), at most 3 blocks of travel. Settles when every joint is under
  0.06 blocks/s for 0.4 s (or after 6 s); a settled body keeps one cached pose.
- Seed and throw: the pose being drawn on the frame he goes down (walk, run, idle), so there is
  no snap. Run over: the hitting car is the nearest car body drawn this or last frame (velocity
  from its positions); every joint gets the car's velocity, the upper body less (x0.45: he folds
  back over the bonnet), lift 0.3 x speed at speed, a little sideways jitter. The car is a moving
  box for the first 0.6 s (sills at 0.05, bonnet 0.20, cabin 0.34 blocks). The game reports the
  hit once the car already overlaps him, so at the seed the whole body is moved out of the box in
  one piece. Later contacts push out by the face the joint came through, at most 3 cm an
  iteration, without adding speed; the car's pace is given by friction. Blast: away from the
  nearest scorch noted in the last second within 3 blocks, the upper body first (onto his back),
  lift 0.75 x strength.
- Skeleton: the torso nodes follow the torso frame (hips, shoulders), each limb bone (neck, head,
  upper arms, forearms, thighs, calves) is aimed at its particle, every other node is carried by
  its parent as in the seed. Written to model space through a pose hook in `model_store`
  (`ModelSetPoseHook`, the pose cache keyed by ragdoll id and generation, a ragdoll's older poses
  dropped from the cache).
- Getting up (the game stands a knocked-down person up, often after 0.37 s): the ragdoll's pose is
  blended into the clip's get-up over 0.3 s, not dropped in a frame.
- `[renderer] ragdoll=1` (default) in `gta2dx9.ini`; `GTA2DX9_RAGDOLL=0/1` overrides. Log lines
  `ragdoll: start|settled|gets up` (always, first 200).

Probe: `gamerun/qb27_probe.py` (`keys_qb27.sh`): F10 scene warp to the Downtown carriageway with
`GTA2DX9_SCENE_NO_CAR=1`, third person, pacing across the traffic lanes until cars hit him; one
continuous 15 fps recording, and the log's wall-clock `ragdoll: start` lines give the offsets.
`STAGE=<stage> FPS=0 GTA2_DIRECT_KEYS=1 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <run> 300 keys_qb27.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 -e QB27_SECS=200`.

| item | status | evidence |
|---|---|---|
| player run over (truck, slow) | verified in frames: knocked back from the truck's line, folds and falls away from it over 0.4 s; the game stands him up at 0.37 s and the blend brings him upright with no pop | `out/qb27_r9/fr/p1z.png` (b_lane.mp4 at 15.9 s) |
| a body seeded inside the car | fixed: the first builds stood him on his head within 0.1 s (legs pushed out on their own, then a Verlet push adding speed); seen in `qb27_r4`, `qb27_r6`, `qb27_r8` | `out/qb27_r8/fr/p1z.png` (before) |
| NPCs run over | log: 8 NPC ragdolls over the runs settle in 1.4-1.8 s, 0.27-0.52 blocks from the hit, pelvis peaking 0.23-0.24; a fast hit (4.9 blocks/s) threw one 3.06 blocks, pelvis peaking 0.51. These were off camera (the far lane or 14 blocks away), so no frames | `qb27_r4/r6/r8/r9` logs |
| blast victims | untested in a run (`gamerun/qb27_blast.py` written, not run): same solver, throw from the scorch note | - |
| cost | not measured: the host was at load 20-90 during every run; one skinning a frame per moving ragdoll, none once settled | - |
| first person | same code path; not filmed | - |

Known limits: the solver is not stepped while the body is out of view (frustum/behind culling);
no collision with other people, props or parked cars after the first 0.6 s; a body thrown onto
higher ground (a kerb) is held at the hit's floor height.

## QB-20/21/39 (9 Nov 2026): mocap locomotion, retargeted onto the Rocketbox avatars

The quality-bar rows "walk/run cycles" (QB-20), "turning in place" (QB-21) and "stopping and idle" (QB-39).

### What was wrong
- Every avatar, male or female, walked the **women's** walk (`anim/walk_neutral.glb` is Rocketbox's
  `f_walk_neutral`), and the clip's **bone translations** were merged too, so a man's calves and thighs took the
  female recording's lengths (0.426 instead of 0.399 for the calf, and so on).
- No starts and no stops: the idle cross-faded into the cycle in 0.1 s; a stop settled the cycle to the
  nearest feet-together phase and faded to one idle loop. No lean into acceleration. No idle variety.

### What changed
- **Source**: Rocketbox's own motion capture (github.com/microsoft/Microsoft-Rocketbox, `Assets/Animations`,
  MIT, the same library and licence as the avatars): men's and women's walks (two each), run, fast run,
  walk start/stop, run start/stop, idles and fidgets (look around, scratch head, shift a leg, touch hair,
  waiting). Fetched into `assets-src/humans/rocketbox/anim_loco/` (`*_motextr_xy` for the moving clips,
  `*_static` for the idles), converted with FBX2glTF.
- **Retarget** (`tools/import_assets.py`, `"retarget": true` in `animations_from`): the clip's joint
  rotations are copied by joint name (Biped joint frames agree across the library); its joint translations
  are dropped, so the avatar keeps its own bones; the root's height and the ground covered are scaled by the
  hip-height ratio (avatar / recording). Men get the men's clips, women the women's. Each avatar gets one of
  two walks by a hash of its folder name (variety in a crowd). `"max_len"` trims a long capture (fidgets to 9 s).
  The meshes stay the same size (3.84 MB for human_male_01, was 3.75 MB): dropping the translations paid for
  the new clips.
- **Locomotion tables** (`tools/locomotion_meta.py`, the manifest's `"loco"` string, `Model::Loco` in
  `dll/src/model_store.*`): per clip at 15 Hz the ground its root covered and its foot phase on a reference
  cycle (the phase whose left-minus-right foot and calf offsets match best, forward kinematics on the
  recording's own bones). They line the run up with the walk and the fast run with the run (measured, not the
  old fixed half cycle), carry the fast run's own stride, and drive the transitions.
- **Renderer** (`dll/src/live_geometry.cpp`, the figure's locomotion block; state in `PedTrack`):
  - *Start*: from standing, `walk_start` or `run_start` (a walk start becomes the run start if he is
    running within 0.25 s), played at the pace of the ground he covers, between 1x and 2x real time (the game is
    at full speed at once, the capture accelerates); the idle fades into it over 0.15 s; the cycle is held
    on the start's own foot phase, so the last 0.25 s hands over to the walk or run in step.
  - *Stop*: `walk_stop` or `run_stop` (by his recent top pace), entered at the frame of its walking part whose
    feet match the cycle's, played in real time, faded into the idle over its last 0.45 s.
  - *Fidgets*: after 5-13 s standing still (hash per person), one of four fidgets over the idle (0.6 s in,
    0.7 s out); any movement, action or turn ends it.
  - *Lean*: the figure tips forward with acceleration and back with deceleration (critically damped spring,
    at most 6 degrees forward and 3 back), pivoting on the feet; none during actions other than aiming and carrying.
  - The turn on the spot stays the procedural `turn_step` layer (see ACTIONS-3D-4): the Rocketbox library has
    no turn clips (see below).
  - Log: `loco: <obj> walk_start|run_start|walk_stop|run_stop|fidget|cycle/idle ...` with
    `GTA2DX9_LOG_FIGURES=1` or `GTA2DX9_LOG_PED_FRAMES=1`; the `fig:` line gained `tr trt trw lean`.

### Regenerate
`python3 tools/make_ped_manifest.py` from `assets-src/humans/` (writes the clip lists), then
`gen3d/venv/bin/python tools/import_assets.py assets-src/manifest.json assets/models --only <human_ names>`.

### Verification (runs qb20_r1..r3, private stage, L4, 15 fps bursts)
Probe: `linux/docker/qb20_probe.py` + `keys_qb20.sh` (items idle, side, start, tap, turn, curve);
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 170 keys_qb20.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_FIGURES=1`;
strips with `linux/docker/qb20_strip.py`.

| item | result | evidence |
|---|---|---|
| run start, side-on | verified: quarter turn, push-off with forward lean, men's run stride, stop step, settle into idle | qb20_r2 `b_side2` (sheet `qb20_side2.png`) |
| run from behind | verified: men's run, arms and stride; stands after the stop | qb20_r1 `b_start` |
| start choice | log: the player's starts go walk_start -> run_start in the first frame of running | qb20_r2 log |
| stop choice after a run | fixed after r2 (the stop always took walk_stop: the run weight had faded before the stop fired); r3: every stop after a run is run_stop (log), braking stance then upright in frames (camera unsettled after the warp) | qb20_r3 `b_side2` (sheet `qb20_r3_side2.png`) |
| turn on the spot | the feet step (procedural turn_step, unchanged) | qb20_r1 `b_turn` |
| fidget | log only: `loco: fidget` after 9-12 s standing, ended at 6.7 s; from behind the camera it is not clear in the frames | qb20_r1/r2 log |
| NPCs | log: NPC walk starts, run starts, walk stops and a fidget near the player | qb20_r2 log |
| faults | none in r1, r2, r3 | logs |

### Not done / open
- **QB-21, turning in place**: still the procedural step layer. The Rocketbox library (MIT) has no turn or
  pivot clips. CMU mocap has turns but its licence is not CC0/MIT-class, so it was not used; adding turn clips
  needs a licence decision by the owner (or an MIT/CC0 capture).
- A stop has no root motion (the game stops at once), so the stop's remaining steps slide the feet a little
  (up to about one walking cycle, 0.1-0.3 block).
- Remix not tested; the women's clips seen in log only (the player is male).

## Weapon handling (9 Nov 2026, ANIM-WEAPONS)

Builds on QB-29 (reload clips) and QB-6 (aim camera). Before this pass the hands only went where
the hand-authored clips put them: the support hand an open palm in the air beside the gun, the long
guns laid on whatever line the two hands made (low, across the forearm), no fingers closed on anything,
and the recoil a 4-9 degree flick of the arms in the clip.

**The gun is the master** (`dll/src/weapon_rig.cpp/.h`, run as model_store's pose hook after the clips,
so the skin, the weapon draw and QB-29's magazine all see the result):

- **Placed from the body, per class and mode**, at the weapon models' real geometry (`tools/gen_weapons.py`:
  origin the pistol grip, bore, stock heel, fore grip/fore-end, magazine well, slide/charging handle, tube):
  pistol on the eye line 0.34 m out in a two-handed grip; machine gun, silenced MG, shotgun, electro gun
  with the stock's heel in the right shoulder pocket and the body bladed 8 degrees more than the clip;
  the launcher's tube on top of the right shoulder; the flamethrower at the hip. Carry (low ready): the
  long gun pivoted down 38 degrees and in 18 about the stock in the shoulder; the launcher tipped up;
  the flamethrower lower. The pistol carry and the dual pistols stay on the clip's hands.
- **Hands on the gun:** two-bone IK per arm (elbows down and out), the wrist turned so the fingers wrap
  the grip (60 % of the turn given to the forearm's roll, not the wrist), the right hand high on the
  pistol grip, the left on the real fore grip (MG, launcher, flamethrower: palm on its side), under the
  fore-end (shotgun, silenced MG, electro gun: palm up), or over the right hand's fingers (pistol).
- **Fingers:** closed round the grip (68/85/40 degrees per joint), the trigger finger straight along the
  frame until he fires (then on the trigger for 0.45 s), the support hand wrapped, the thumbs in.
- **Head:** down the sights (a long gun: cheek on the stock, rolled 9 degrees); during a reload it
  watches the magazine well and comes up at the end.
- **Recoil moves the character:** a spring per figure (per weapon frequency and damping), an impulse
  per shot (the game's own shot: `track.muzzleFrame`). It drives the gun back and the muzzle up about
  the grip with a random lateral jitter, the chest pitched back about Spine1, the right shoulder driven
  back (the upper body turned), the head nodding, and the whole figure pushed back along the line of
  fire (`weaponrig::Shove`). Per weapon (gun back m / muzzle deg / chest deg / shoulder deg / figure m):
  pistol 0.035/10/2.5/2/0.012, MG 0.028/4.5/2.2/4/0.007 per shot (bursts stack), silenced MG
  0.018/3/1.5/2.5/0.004, shotgun 0.065/14/7/10/0.04, launcher 0.05/5/6/7/0.045, flamethrower a
  slight shudder. The arms follow the gun through the IK, so they flex with the kick.
- **Reload (QB-29's clips and times, `kReloads`):** the gun pulled in and canted toward the left hand;
  the left hand on the magazine until the drop, handed to the clip for the trip to the pouch, brought
  back by IK into the real magazine well (pistol and silenced MG: the bottom of the grip; MG: the
  drum), then onto the slide / charging handle, a 7 cm pull and release at the rack, and back to the
  fore grip. The shotgun model is a side-by-side double: no magazine drops any more (`kReloads`
  shotgun drop -1), it is broken open (muzzle down 32 degrees), two shells go into the breech by hand,
  and it snaps shut at the insert time. The launcher: tube brought down in front of the belly, the
  rocket pushed into the rear of the tube.
- **Transitions:** mode changes (carry, aim, reload) blend the gun frame and the hand targets over
  0.18 s; the rig fades in over 0.1 s and out over 0.15 s (hit reactions, punches, the throw keep
  their clips).
- **Switches and probes:** `GTA2DX9_WEAPON_RIG=0` (the clips alone, as before). `GTA2DX9_RIG_TEST_FILE`
  names a file "yaw period [off]": the player's drawn figure turned on the spot by yaw degrees (the
  camera stays: side and front views), a synthetic shot every period seconds, `off`=1 the rig off for
  an A/B in the same run. Log: `weapon rig: skeleton ok`, `begin`, `shot`, and a `pose` line every 90
  poses with how far each hand ended up from its target (metres) and the recoil state.
- **Units:** the avatars are about 2 m to a model unit (0.9 units tall); the hook works in metres
  (positions scaled by the arm's length against 0.53 m) and the weapon geometry in blocks times the
  figure's model units per block.

Probes: `gamerun/aw_rig_probe.py` + `keys_aw_rig.sh` (forced clip and weapon on the player at the
plaza 159.5,139.5, stills at four yaws, an A/B still with the rig off, 15 fps bursts of firing and of
the reload), `gamerun/aw_play_probe.py` + `keys_aw_play.sh` (game-driven: pickups, Z stops, the fire key,
release for the reload), `gamerun/aw_sheet.py` (sheets), `gamerun/aw_grun.sh` (grun on GPU
`$GTA2_GPU`); mirrored in `linux/docker/`. Note: the old showcase spot (166.5,19.5) now leaves the
player under cover in the game, so his sprite (and figure) are not drawn there.

### Status (ANIM-WEAPONS)

Runs `aw_r3`..`aw_r6` (forced clip + weapon on the player, plaza 159.5,139.5, the rig's showcase yaw,
close camera via `SETTINGS_EXTRA=/work/aw_settings_close.ini`), private stage (this build + the
QB-20 avatars with the QB-29 clips), GPU 7, host load 10-30 (runs paused by the governor at times).
Frames in `out/aw_r6` (local): `qa_aw_<weapon>_aim_y90/y150` (rig on), `..._off_y90` (rig off, the
same moment), bursts `b_<weapon>_aim_fire_y90.mp4`, `b_<weapon>_aim_reload_y90/y150.mp4`.

| item | status | evidence |
|---|---|---|
| hands on the grips | verified: the `pose` log puts both wrists on their targets (0.000 m) for pistol, MG, shotgun in aim and carry; frames show closed hands on the grip and fore grip / fore-end where the rig-off frame of the same moment has an open palm in the air | aw_r6 log, `qa_aw_*_aim_y150` vs `_off_y90` |
| pistol | verified: two-handed, the left wrapped over the right, at the eye line | aw_r6 `pistol_aim_y90/y150` |
| MG, silenced MG, shotgun | verified: stock in the shoulder, level at the eye line, head bowed onto the stock (cheek weld), support hand on the fore grip / under the fore-end | aw_r6 `mg/shotgun/silenced_aim_y90` |
| launcher | verified: tube on the right shoulder, grip hands below it | aw_r6 `launcher_aim_y90/y150` |
| flamethrower | verified, weakest stance: at the hip, level; the left forearm reaches across the chest to the fore grip | aw_r6 `flame_aim_y90/y150` |
| dual pistols | arms out, a pistol in each hand (rig: wrists only, the guns ride on the hands) | aw_r6 `dual_aim_*` |
| trigger finger | index straight along the frame when not firing (seen on the shotgun); on the trigger within 0.45 s of a shot (log state only, too small to see) | aw_r5 hands crop |
| recoil through the body | verified: shotgun, every shot: muzzle up ~14 deg, chest back, head off the stock, settles in ~0.25 s; MG: a held shoulder stance with a small climb and shudder per shot | aw_r6 `b_shotgun_aim_fire_y90`, `b_mg_aim_fire_y90` |
| figure pushed back | by the spring (shotgun 4 cm, launcher 4.5 cm, pistol 1.2 cm at the peak); not measured in pixels | code + spring maths |
| reload, MG / pistol | verified: gun in and canted, head down on it, the left hand off to fetch, into the well, over the top for the handle / slide, head up again | aw_r5 `b_mg_aim_reload_y150`, aw_r6 `b_pistol_aim_reload_y150` |
| reload, shotgun (break-open) | verified: muzzle dropped, hand at the breech, snapped shut, back to the shoulder | aw_r6 `b_shotgun_aim_reload_y90` |
| reload, launcher | weak: from the front the tube is end-on, the rocket going into the rear is hidden; the fetch over the shoulder reads | aw_r6 `b_launcher_aim_reload_y150` |
| faults | 0 in aw_r4..r6 (aw_r3's one fault was this pass's: the hook ran on the weapon model with the human's indices; fixed) | logs |
| game-driven (real pickups, fire key, release) | verified by log on QB-29's probe (`gamerun/qb29_reload.py`, run aw_q1): 58 player shots, the rig took them as recoil impulses (`weapon rig: shot`), the MG and pistol reloads started on the spent magazines and ran their events (out 0.37 / in 0.97 s; out 0.30 / in 0.80 s), 0 FAULT. In frames only from behind: the chase camera swings behind a shooter, so the gun is hidden by the body (as QB-29 found); the side-on detail is the showcase's | aw_q1 log, `qa_r_*_reload_third_*` |
| `aw_play_probe.py` | not usable yet: after its pickup warps the game does not hand the player's sprite to the renderer (`player seen -1`), so nothing is drawn; with the close camera, QB-6's aim framing also pulls the camera inside the near fade. Left for a fix of the probe | aw_p1, aw_p2 |
| NPC shooters | same code path (rig keyed by object); not filmed | - |
| first person | unchanged (the view model is QB-29's / SHOOT-ANIM's) | - |
| Remix | not tested | - |

## First-person entry, exit and the driver's arms (9 Nov 2026, FIX-FP-ENTRY)

feel15 (first-person jack), feel11 (first-person exit), pfeel32 (arms under a cabin roll), pm10 (arm proportions).

- **The eye rides the boarding plan.** From the player's eyes his sprite used to be dropped at capture, so no
  boarding plan ran in first person: the eye stood at the game's spot (in the lane during a jack, cars through
  the lens) and cut to the cockpit. On the plain renderer his sprite is now kept as `planOnly` (never drawn,
  no contact shadow; `live_geometry.cpp` `OwnPlanOnly`), the plan runs, and `BoardingPlayerEye` (boarding.h) hands
  the camera the plan's figure: approach, the hold at a yanked-open door while the driver is hauled out, the climb;
  out over the sill, the turn and the shove that shuts the door. The eye is that figure's head (foot eye height
  less the sink, at most 0.16), kept 0.14 block outside the boarded car's footprint, its yaw the figure's heading
  (out of the car: 60 % / 80 % of the way round toward the car, so the door is seen shutting), a 10 degree glance
  down while climbing in or out. The pm3 car clearance skips the boarded car. A plan whose car is more than 1.5
  blocks from his game position (a guess at a passing car) is not ridden.
- **Into and out of the seat**: the hand-over is a timed, eased glide (0.6 s in, 0.5 s out, longer for a long
  hand-over so no frame moves more than ~0.25 block) instead of the 0.12 s decay that read as a cut; a late step
  of the seat eye (the cab measured a frame after the hand-over) is absorbed into it. Leaving, his car stays
  drawn as from the seat (hidden object 1: the cut hull and cab) for 14 frames (`world_view.cpp`), so the eye
  never sits inside a whole body (which drew nothing: the car vanished at the exit).
- **The seat eye follows the posed body** (`view_modes.h` `FirstPersonSeatEyeRaw` / `SetFirstPersonSeatCorrection`):
  car_bodies learns the eye's point in the car's own frame while the body is level and answers each frame with
  where that point is in the posed body; the camera adds the difference (eased, at most 0.3 block). On a kerb the
  body tilted 25 degrees about its wheels while the eye stayed level and dropped through the dashboard (pfeel32:
  the hands hung over a black slab).
- **Hands on the wheel** (`cab_interior.cpp` DrawCabHands): each forearm points from its grip on the rim to a
  shoulder fixed by the seat eye (2 fists to the side, 2.5 under, 1 behind), the grip's axis along the rim the
  same way round for the whole turn. Before, the forearm lay along the rim's tangent with a sign flip at the top,
  so at full lock one arm was a stick across the dash and the other pointed at the roof.
- **Arm model** (`tools/gen_weapons.py` `_forearm`, all three `fp_arm_*`): the bare forearm was ~12 fists long
  (a thin tube, its sleeve never in frame); now ~3.3 fists from wrist to elbow, swelling to the muscle and
  narrowing to an elbow, then the upper arm out and down inside the hero's dark short sleeve (hem, cloth wider
  than the arm) leaving the frame. The sleeve's colour is still the identity record's shirt (`ModelSetNodeTint`).
  Regenerated with `python3 tools/gen_weapons.py <dir>` then `tools/import_assets.py` on a manifest of the three
  arm entries (a python with trimesh: `gen3d/venv`).
- A/B switch: `GTA2DX9_FP_BOARD_EYE=0` (no plan in first person, the old glide, no seat correction).
- Log lines: `view: fp ride on|off (mode m t s)`, `view: fp seat glide in|out D blocks over T s`,
  `car bodies: fp seat eye follows the tilted body D (level L)`.

### Figure contact shadow (FIX-FIGURE-7, pm20)

A figure's contact patch (`LiveGeometry::DrawContactShadows`) has its own texture half: round, its darkest 0.6 of the pass's opacity, falling off as (1 - d^2)^2 with no rim, radius 0.11 block (was the cars' rounded square, solid to 0.55 of the radius, 0.21 block: a near-black disc twice a body wide). Measured at the plaza (fig7_k before, fig7_j after, same spot, pavement luminance across the feet): before 114 -> 19 over +-40 px, after 117 -> 69 over +-20 px. Cars' and props' patches unchanged (left texture half, same texels).

FIX-FIGURE-13 (coord contact-shadow-gone, 10 Nov): pm20 overshot. Its (1 - d^2)^2 profile put the darkness in the
middle, under the shoes; the ring that shows round them stayed under a fifth of the pass, so at the vreg
`spawn_portrait_front` pose and at the chase distance the hero and the peds read as floating (bisected on the vreg
history: the last run without 794c936 has the dark patch, FIX-FIGURE-7's own run with it already shows the bare feet;
nothing later changed it; a debug build drawing the cars' texture half at 0.3 block put a dark patch under him, so the
pass, its depth and its position were fine). Now: radius 0.16 block, flat core to 0.4 of the radius at 0.85 of the
pass (60 % at the default 70), a smoothstep fall to nothing at the edge. Smaller and lighter than the pre-pm20
near-black disc (the vreg golden is still that disc, so `spawn_portrait_front` stays FAIL until a reseed), the paving
reads through it. `GTA2DX9_FIG_SHADOW_PM20=1` restores 794c936's patch for A/B. Cost unchanged (~0.06 ms a frame).
`tools/vreg/run_capture.sh` takes `VREG_DOCKER_ENV` (extra docker args, e.g. `-e GTA2DX9_FIG_SHADOW_PM20=1`) and
`VREG_SHOTS` (a reduced shot list) for quick A/B captures.

### pfl50: the electro gun is an electro rifle in both hands (FIX-FIGURE-13)

- Cause (frames at HEAD, out of the probe below): the old `gen_weapons.py electro_gun` was a 0.10-block box with two prongs
  and a coil, drawn 1.6x up to the weapon table's 0.16 block, while the rig's points on it (`GeoFor wElectro`: the butt at
  z -0.005, i.e. the grip) stayed at model scale: the long-gun hold put the grip into the shoulder pocket, so the gun sat at
  his face (aim) or hung across his chest with the prongs at his hip (carry), the hands off it (`weapon rig: ... right hand
  off its grip 0.384 m` on the first frames). First person drew the box gun at HEAD (the filer's "no view model" did not
  reproduce on 8437686+; the game's purple bolt was drawn on the target).
- Model: `tools/gen_weapons.py electro_gun`, a 1950s tesla rifle: a round battery cell in copper bands behind the grip as the
  stock (butt pad z -0.060), a teal enamel receiver with a glowing glass capacitor in brass caps along its top, five copper
  coil rings round the barrel, two ceramic insulators, a brass emitter fork with glowing tips at z 0.113, a pistol grip at
  the origin and a vertical fore grip at z 0.052; 1202 triangles, span 0.170 (table length 0.170: model scale 1). Imported
  with `tools/import_assets.py` on a one-entry manifest (gen3d venv) into /tmp and copied (weapon_electro_gun.mesh and
  _0.._6.tga; the manifest's report entry patched by hand). Remix: the weapon_electro_gun textures changed content (_3.._6 new).
- Rig: `GeoFor wElectro` = bore 0.017, butt (-0.060, 0.012), a vertical fore grip (fore 1) at z 0.052; first person
  `fore[]` z 0.052. Third person: low ready with the butt in the right shoulder, the muzzle forward and down, the left
  hand on the fore grip; aimed, at the shoulder with the cheek on it, the game's bolt from it.
- Probe: gamerun/keys_fig13_el.sh + fig13_el.py (the ste kill-frenzy skull at 147.5,43.5, then stand at F13_AT, regress
  camera poses front / front2 / side / back from his facing, F13_SIDE picks the open side, three fire taps per pose, then
  first person). Runs fig13_el1/el2 (HEAD), fig13_el3/el4 (this); fig13_mg1 the machine gun at the same offsets (wil plaza).

### pfl51: the last rocket keeps the launcher; the launch smoke off his legs (FIX-FIGURE-13)

- Last round: the game sets his weapon to none on the frame the last round leaves (the launcher counts in tens:
  `player shot: ammo 10 -> 0`, then none), before the shot's flash, so the launcher vanished as the rocket left and the
  aim clip played on empty hands. Now the gun the last round came from stays drawn in its aim 0.9 s (27 frames: the
  shot and its recoil; log `last round: ... drawn on to f=N` with GTA2DX9_LOG_PED_FRAMES=1), only when the count was at
  its last round (0/1, or <= 10 with a shot in the last 3 frames); a kill frenzy's -1 taken at its end, a switch and a
  death let go at once. Bare hands by the game's word (weapon none) never take an aim stance from the game's firing
  frame 139 (held ~1 s after the last round: one arm out, an empty hand); they stand at idle.
- The cyan blob on his hips: the game launches the rocket from his ground position, so its launch smoke and first sprites
  (code objects 8/410-415, 8/469-473, 8/503-505 under GTA2DX9_LOG_FX=1, all at his feet) were drawn by DrawGamePuffs as
  soft sky-tinted puffs on the paving and rising past his legs. For 2.5 s after a figure's rocket shot (NoteRocketLaunch),
  a game puff within 0.8 block of it and under the tube's height is drawn at the tube's height (0.36 over his ground) at
  0.7 of its alpha; the launch's muzzle light within 0.8 block in the 6 frames after is a third, half its reach
  (visuals.cpp RocketLaunchNear, as 797c987 did for the suppressed MG). The rocket's trail and the blast are unchanged.
- A/B: GTA2DX9_LAST_ROUND_OLD=1 (both last-round changes), GTA2DX9_ROCKET_PUFF_OLD=1 (puffs and light).
- Probe: gamerun/keys_fig13_el.sh with F13_PICK=154.5,129.5,2 F13_AT=159.5,139.5,2 (wil launcher, plaza), runs
  fig13_rk1/rk2 (before), fig13_rk4/rk5 (after; the side pose catches the last rocket). Not done: a recoil kick and a
  backblast puff of our own at the breech; the head behind the tube from the chase camera.

### Draw-only figure separation (FIX-FIGURE-7, pm24 / pm3)

GTA2 walks its people through each other and over parked cars' footprints; the flat sprites never showed it, the bodies do.
In `DrawPedFigures`, each figure on its feet (not the player, not entering/leaving a car, not knocked down, arrested,
climbing or dead) is offset for the draw only (`PedTrack::sepX/sepZ`; the game's positions untouched):
- from every other person within 0.14 block (centre to centre), along the line between them, half each (all of it when
  the other is the player, who never moves: the camera rides him), measured between the positions as DRAWN (the smoothed
  track, which trails the game by up to 0.1 block), capped at 0.2 block;
- out of a car body at rest (moving under ~0.45 block/s; `CarBodiesFootprints`, the drawn footprint with the body's own
  push), by the edge it entered through (kept while inside, so it walks round the car instead of flipping at the middle),
  capped at 0.6 block. A moving car is left to the game (dodge, knock-down, run-over): sliding a figure ahead of a bumper
  looked worse than the overlap (FIX-FIGURE-6's fig6_pm24a).
- Moving apart is a sidestep at up to 1.5 block/s; settling back eases over 0.25 s.
- `GTA2DX9_NO_FIGURE_SEP=1` turns it off (A/B). Every 300 frames: `figure sep: <ms> a frame ... pairs closer than 0.10: N by
  the game, M drawn`; `figure sep pair:` lines (first 60) name any pair still drawn that close; with
  `GTA2DX9_LOG_PED_FRAMES=1`, `figure sep: ... inside parked car ...` lines.
- Measured (keys_pm24.sh at wil, 170 s): cost 0.008-0.02 ms a frame, no growth; pairs closer than 0.10 block: fig7_r 11 by the
  game, 2 drawn (one crossing, two frames); the eased version before it left 5 of 8 (fig7_p) and 27 of 53 (fig7_q, game
  positions).

## FIX-FIGURE-8 (10 Nov 2026): the S-Uzi view model, the pistol at arm's length, the wheel arms under a roll

- **pm24 / pm10, the machine gun is the S-Uzi** (`tools/gen_weapons.py machine_gun`): the HUD names the game's weapon 1
  (renderer 4) "Machine Gun" with the S-Uzi icon, and the view model and third-person carry were a Thompson with a drum and
  a wooden brick stock. Now a compact SMG: squared receiver with a top cover (`bevel_box`, chamfered edges), short barrel
  and nut, the magazine up through an olive polymer grip, a handguard under the front, the folding stock folded (struts
  along the receiver, the chamfered butt plate under the barrel nut; opened, its plate filled the first-person view's lower
  right corner). Span 0.110 block = `kWeapons` length, so the model draws at scale 1 and the rig's `GeoFor(wMg)` points
  (handguard z 0.058, magazine foot, charging knob on the cover) are on the drawn gun; the first-person left hand is under
  the handguard (`fore` z 0.052). Remix: `weapon_machine_gun_0/1/2.tga` changed content (steel, polymer, rubber).
  Log: `view model: weapon id N (game word W) -> name, model M` at every change of the first-person weapon.
- **pfl16, the third-person pistol aim** (`weapon_rig.cpp HoldFor`): the grip 0.56 m ahead of the shoulders' midpoint,
  0.12 m over them, 0.04 m to the right (arms nearly straight, an isosceles stance); it was 0.34 m ahead of the eye on its
  line (forearms folded, the gun behind the head from the chase camera). The rig log puts the gun at 1.42 m, 0.49-0.52 m
  ahead on the shot frames (was 1.44 m, 0.39). A/B in one session: the rig test file
  (`GTA2DX9_RIG_TEST_FILE`, "yaw period off stance") takes a fourth number, 0 the old eye-line hold.
  Probe: `gamerun/fig8_gun2.py` + `keys_fig8_gun2.sh` (pickups, plaza, side view by the test yaw, new then old stance,
  from behind, the MG side-on, first person MG and pistol). Directly behind him the torso still hides the arms and most of
  the flash: that view needs the camera's aim offset (pfl16-third-mg-fire, camera).
- **pfeel32, the wheel arms under a roll** (`cab_interior.cpp`): `GTA2DX9_FP_ARM_LOG=1` logs per frame the camera's eye in
  the posed car's frame against the eye the cab was built for, the body's up axis and each grip's distance to its shoulder.
  Probe `gamerun/fig8_roll.py` (`[devtools] force_body_roll_deg` live, CRLF kept): a forced 12/25/-25 degree roll is drawn
  bounded by the wheels (level 0.994, ~6 degrees, FIX-VEHICLE-FEEL-2), the eye stays within 0.02 of the cab's eye, both
  fists stay on the rim (the arm model is rigid: constant forearm), no dark slab. The 20 degree roll with the dash over two
  thirds of the frame in the old take (fpentry_c) predates the wheel bound.

## FIX-ACTIONS-3 (10 Nov 2026): the owner demo's punch and jack (pfl15)

Two playtest defects on the owner demo's first two beats (pfl15, third person).

**The punch** (pfl15-third-punch-open-palms-aimed-70deg-off-victim-who-then-dives-prone):
- *Fists.* The punch clips (`tools/gen_ped_clips.py`) key only the arms and torso, so the fingers kept
  the bind pose: two flat open palms by the face, read as "stop". While a punch clip is on and no gun
  is rigged, `weaponrig::BeginFists` sets a pose hook that rolls fingers 1-4 into the palm (88/100/62
  degrees per joint) and folds the thumb across them, blended by the clip's weight. Lod 0-1 only.
- *Aim.* GTA2 lands the blow at the swing's first frame on whoever is in reach of its own facing, and the
  scripted (or player's) facing can be 50-70 degrees off the ped hit. While the fists fly, the drawn
  figure turns onto the nearest figure within 1 block and 100 degrees of the game's facing, at 24 rad/s
  (about 2 frames for 70 degrees), bypassing the chase view's soft-turn rule for those frames. The
  `fig: punch` strike line now logs how far his facing is off that mark.
- *The victim.* A punch knock-down sets the corpse flag in the same frame as the health drop (or 1-2
  frames later), and the hit detection skipped corpses: no reaction, and the lying clip came from the
  ped's seed (often `fall_front`, the face-down dive). Now a health drop on the frame he goes down
  counts as the blow, and a knock-down within 6 frames of a punch is that punch's. He plays `hit_head`
  for 8 frames (0.27 s) from the blow, turning toward the puncher, then `fall` (onto his back, away from
  the fist). The stagger is held while he lies instead of walking back (a 7 cm prone slide), and eases
  out as he gets up. Log: `fig: knock-down <ped> by <puncher>'s blow` / `... N frames after the blow`.

**The jack** (pfl15-third-jack-hero-vaults-over-canopy-glass-victim-thrown-t-pose-and-glued-to-car):
- *Approach.* GTA2 walks the boarding ped straight to the door it picked, through the car when he
  comes at its nose or from the far side (pfl15: across the 036 Schmidt's deck and canopy). In the
  boarding plan's approach (`boarding.cpp`, state 3 before the climb), while the game's spot is inside
  the hull grown by 0.06 block, he is drawn on that outline, moving at up to 2.4 blocks a second toward
  the outline point nearest the game's spot. He walks round the nose or the tail and leaves the outline
  where the game has him. Offline check: replaying the pfl15 and fa3_fix3 paths through a 1-block body
  gives 0 frames inside the hull. `GTA2DX9_LOG_BOARD_HULL=1` logs `board: ... approach round the car`
  for the player.
- *The thrown driver.* The game leaves him on the car's centre line (0.2 block from its middle in
  pfl15), so the lying figure lay with his legs in the wing and turned with the camera as if glued
  on. `BoardingJackVictim` now lands him 0.16 block outside the hull on the door side (he faces the car,
  so the fall's body runs away from it), and holds that offset after the car leaves (no car there). The
  offset eases back onto the game's spot over 0.5 s once he is up.

| check | result | evidence |
|---|---|---|
| fists closed through the burst, arm toward the victim | verified: the guard is two balled fists at the chin, the cross goes out at the woman after a ~150 degree turn in 5 frames | fa3_fix1 36.00-36.87 s (base: fa3_base1 38.9-40.9 s, open palms) |
| victim reacts at contact, falls onto the back | verified: hands up at the contact frame, spun toward him, on her back by +0.5 s; lying clip 0 in the log for both knock-down timings | fa3_fix1, fa3_fix3, fa3_fix4 logs (`fig: knock-down`) |
| hero never on the car | verified: entered at the nose, drawn round the front end and down the side, beside the door on the ground | fa3_fix4 log (10 `approach round the car` frames) and 46.9-49.0 s |
| driver beside the car, not carried with it | verified: lands clear on the road, left behind as the car pulls away; drawn spot fixed while the car drove 1+ block | fa3_fix4 48.6-53.0 s, fa3_fix3 log |
| not done | the driver is still hauled up through the closed canopy glass on the 036 (the door is under the glass); the lying end pose is `fall`'s (arms spread 45 degrees) | - |

Probe (FIX-ACTIONS-3): `linux/docker/keys_fa3.sh` + `fa3_demo.py` (copy into gamerun/): warp to the wil pavement, the
owner demo's punch_sequence in third person, a kerb-lane jack, drive off (`FA3_DRIVE_WAIT` seconds after the jack).
`STAGE=<stage> GTA2_DIRECT_KEYS=1 FPS=30 PRIO=1 INI_SED='s/^scene_key=.*/scene_key=F11/; s/^force_car_model=.*/force_car_model=36/'
gamerun/grun.sh <run> 330 keys_fa3.sh -e GTA2DX9_STATE_EVERY=3 -e GTA2DX9_PEDS_EVERY=3 -e GTA2DX9_LOG_PED_FRAMES=1
-e GTA2DX9_LOG_BOARD_HULL=1 -e FA3_DRIVE_WAIT=0.2` (about 70 s of game). `tools/boarding_hull_test.cpp` replays two
paths through a car body against `boarding.cpp` offline (0 frames inside the hull).

## FIX-AIM-1 (10 Nov 2026): why punches did not land, and the aim assist (owner10nov B9)

The owner (two sessions on 10 Nov): "punches often simply fail to work - they don't land". The counter quoted with
the filing (`aim: shots=36 with_target=13 hits=9 ...`) counts **gun** shots only (`AimState::armed` is weapon > 0):
fists were never counted. Measured first, then fixed.

**What decides a punch (read off gta2.exe).** The player's blow is `FUN_00444B50` (20 health off a civilian, the
knock-down). Its victim comes from `FUN_00433D00`: the collision grid (`FUN_00447540`) is asked for a ped
**overlapping the puncher's own sprite** - nothing is moved ahead, there is no facing arc - and that ped must stand
within `[0x5E5D64]` = 4096 (0.250 block, read in the running game) of him. The test runs on the press frame. Two
people standing apart do not overlap, whichever way he faces; walking into someone presses the bodies together.
So the 3D views, where a figure reads as within arm's reach at 0.5-0.9 block, invite presses the game can never land.

**Measurement** (`GTA2DX9_LOG_AIM=1`, one `aim: swing N` line at each press the game is told of with his heading and
every person within reach + 1 block (distance, bearing off his facing, height, verdict), one `aim: swing N ->` line
with the game's own outcome: whose health dropped or who went down; the tally `aim: fists swings= with_target= hits=
miss_with_target= | gun presses= ...` every 10 s). Gate: `linux/docker/fixaim1_gate.py` (keys `keys_fixaim1.sh`):
10 single taps of the fist at a civilian on the wil Downtown pavement, turned to within 20 degrees and walked up to
0.45 or 0.7 block, in third then first person; a swing lands when a civilian within 1.8 blocks loses health or goes
down within 0.9 s (`view: peds`).

| run | build | third | first | note |
|---|---|---|---|---|
| fixaim1_base1 | HEAD + log only | 0/10 | 1/10 | misses at 0.39 block 6 degrees off; the one hit at 0.18 |
| fixaim1_sweep1 | HEAD + log only | 3/24 | - | approach 0.28-0.75, hold 0.12/0.6 s: misses at 0.29 block 0 degrees off |
| fixaim1_as1..as6 | assist iterations | 5-8/10 | 5-9/10 | as6 found the cause of the rest: presses held back were lost (the game reads one buffered event at a time, ~8 reads a second; a timed 90 ms tap expired undelivered) |
| fixaim1_as7 | assist, event-based tap | 8/10 | 9/9 | every held press reached the game (19 of 19) |
| fixaim1_rb2 | assist on fork HEAD 7d16bbe3, fire key first in the read | 9/9 | 9/10 | `melee: swings=19 with_target=14 contacts=18 (95%) ... no_contact=1`; the one miss: the 0.7 s bound, heading 47 degrees off as the man walked away |

| fixaim1_rb4 / rb3f | 73e52e47 (pushed) | 9/10 | 10/10 | `melee: swings=10 ... contacts=10 (100%)` in first person; third's one miss `no_contact` |

Every miss has its line (`aim: assist ... let go: <why>`, `melee: swing N MISS: <reason>`). Frames (rb2, timed from the
`fig: hit` lines): third person, the hero on the victim and the victim staggering at contact; first person, the fists
thrown at contact but the victim **not in the picture**: a body within 0.25 block is under the first-person view
(short of a shipping frame: the victim should be seen taking the blow). Classic: vreg spawn_classic 0 tiles.

**Guns (B9b), measured, not solved.** `linux/docker/fixaim1_fight.py` (keys `keys_fixaim1_fight.sh`): 3 minutes in
third person with a gun (set_player_ammo=300), turned toward the nearest civilian to within about 20 degrees (as
coarse as the camera-relative arrows allow), single taps; re-arms after a bust. The owner's counter at the end:

| run | assist | shots | with_target | hits | on_highlighted |
|---|---|---|---|---|---|
| fixaim1_gun0 | off | 37 | 17 (46 %) | 4 | 1 (25 %) |
| fixaim1_gun2 | on | 22 | 15 (68 %) | 4 | 3 (75 %) |
| fixaim1_gun3 | on + lead (not shipped) | 29 | 28 (97 %) | 3 | 3 (100 %) |

The assist turns him onto the person (within the angle of a quarter block) and the reticle brackets that person, so
the shots now go at someone; but at 3-6 blocks against a man running from the first shot most still miss while aimed
within 2 degrees (hits came at 1-3.3 blocks: `aim: hit ... 0.53 s after the shot, 3.3 along`). Leading him by his
measured velocity at ~6.5 blocks a second of bullet flight (gun3) did not raise the hits and is not shipped. Open:
the game's bullet range and spread (read the fire routine as FUN_00433D00 was read for the fist), then lead or range-gate.
gun1 was busted 10 s in (its hits brought the police; the runner now re-arms).

`melee:` (owner10nov B9a, always on, every 10 s): `melee: swings= with_target= contacts= (%) misses: nothing_in_range=
outside_arc= no_contact= assist=`, and one `melee: swing N HIT|MISS: <reason>; nearest D block A deg off his facing`
per punch. The gun counter stays `aim: shots=` (QB-6) plus `aim: gun presses= with_target= hits=`.

**The fix: the aim assist** (`[camera] aim_assist=1`, default on; `GTA2DX9_AIM_ASSIST=0` for an A/B). On foot in a
street view (never the classic view), the attack press is judged inside the game's own keyboard read
(`NavGetDeviceData`/`NavGetDeviceState`, `view_modes.cpp`), so the game never sees a press the assist holds back:
- *The pick* (`hud3d.cpp ComputeAimPick`, once a frame from the drawn people): fists - a standing person within 1.2
  blocks and 75 degrees of his facing, nearest by distance and angle; a gun - within its reach and 30 degrees (12 in
  first person), not behind a wall, smallest angle first. The current pick keeps a bonus so it does not flip.
- *Fists:* the press is held while the game's own Left/Right turn him onto the person and Up walks him in; it goes to
  the game once he has been inside 0.28 block (drawn centres; two pressed bodies sit 0.25-0.30 apart) for two frames,
  and Up stays down 0.2 s after it, so the bodies are pressed together on the punch frame. Bound 0.7 s.
- *A gun:* the press is held until his heading is within the angle of a quarter block at the person's distance
  (2.5-8 degrees), at most 0.25 s; while the key stays down he keeps turning onto the person.
- *The reticle* brackets the same person (it highlights what the press goes for).
- Nothing is written into the game: the turn and the step are the game's own keys, pressed by the same DirectInput hook
  the camera-relative controls use. `aim: assist press on <ped> let go after T s: <why>` logs each held press.

**The renderer's hit log** (diag-renderer-fig-hit-log-silent-while-ped-pool-registers-punch): the game takes the
health off on the press frame, before the drawn figure reaches its swing (and the first-person player spot never
swings), so the drop found "nobody mid-swing". A drop on a person within 0.9 block of the player within 8 frames of his
fire press (or while it is held), bare-handed, is now his blow: `fig: hit <victim> by <player> (cross)`. Probes should
trust `fig: hit` for the player's punches again (fixaim1_as1: 10 player `fig: hit` lines for 10 connected punches).

## FIX-FIGURE-9 (10 Nov 2026): the molotov throw without the burn clip, the flamethrower's jet, flames beside him

**Molotov: "both arms up" after a throw was the burn clip** (feel12-molotov). The "on fire" test (a fire spot
within 0.18 block of his feet, three frames running, then clip 19 `burn`, arms thrown up) is flat: a bottle thrown
high passes, then lands, over his head. Log (fig9_h1): `action 19 ... clip burn` 0.4 s after each `action 13`.
The spots measured 1.24-1.29 blocks above his feet (fig9_h3 `burn test` lines). Now:
- `FireSpotsOnFigure`: a spot counts only from 0.25 below to 0.75 above his feet.
- His own bottle or grenade is never a fire on him for 15 frames after the throw.
- Flames that belong to a burning car never count (`FireSpotPublic::onCar`, set for the lifted car-fire spots and the
  own-car path; the same sprite published again unlifted is matched by place), and no spot over any car's body grown
  by 0.12 block counts either. pm22 (ste): the hero stood hands-up beside a burning convertible: the same clip. It was
  reproduced on 3ef784d (fig9_pm22: he had just stepped out of his car, 0.48 block from it, and its tail flame was
  outside the roof test). The footprint rule is not yet proven in a run that discriminates: the forced-burn probe
  (keys_fixfx_burn.sh STAND=1, fig9_burn / fig9_burnold) gave no burn clip with the old test either, and a pm22 re-run's
  car did not burn.
- `GTA2DX9_BURN_TEST_OLD=1`: the flat test, for an A/B. `GTA2DX9_LOG_PED_FRAMES=1` logs `burn test:` when a flat hit
  is not counted, and why.

**Molotov throw: the left arm.** The throw clip raises the left arm out in front for balance. Through the weapon rig
(`weapon_rig.cpp`, `cThrow` while `throwing`), that hand is now IK'd low at his side, a little out and back (weight
0.8, the clip's swing still shows). The rig test file's 4th number 0 leaves the clip alone (A/B in the same session;
it is now part of the pose cache key, so the switch takes effect at once).

**Flamethrower: a jet from the nozzle** (feel12-flamethrower). The game's stream is upright flame sprites of
0.5 block. They start 0.42 block ahead of him and travel straight along his facing at about 0.1 block a frame
(fig9_h4 `flame jet:` lines: across within 0.04). Drawn standing, they read as a teardrop beside his hand. Now, while
a figure fires the flamethrower (shot within 24 frames: the game's flames live 13+ frames, and with 8 a tap's flames came back mid-flight, fig9_h5 f46-55):
- The game's flame sprites within 2.4 blocks of him are left out (street views only, the `fxUpright` path).
- `ShotFxMuzzle` draws the stream: nine glow puffs every other shot frame, spread over their first 2/30 s of flight
  so the stream is continuous, 6-7.6 blocks/s along the barrel with a slight rise, swelling 0.04 to 0.26 and
  reddening over 0.30-0.37 s (about two blocks of reach, where the game's fire takes over), and a wisp of smoke at
  the tip.
- `GTA2DX9_FLAME_JET=0` turns both off (A/B).
- The light the game's flames cast stays (a pool on the ground under the stream). In the rig test's turned views it
  is off to the side, because only the drawn figure turns.

| check | result | evidence |
|---|---|---|
| no arms-up after a molotov throw | verified: 0 `action 19` in fig9_h3 (3 throws); fig9_h1 (HEAD) had the burn clip after 2 of 3 throws | fig9_h1 molotov f46-65 vs fig9_h3 molotov_y90_s1 f30-61 |
| bottle in the hand, one-arm swing, back to the low carry | verified: bottle in the right hand f33-34, arm forward f35-43, low carry with the bottle by the thigh from f44 | fig9_h3 b_h_molotov_y90_s1 |
| left arm at his side during the throw | verified, same-session A/B: clip alone (s0) left arm out in front f35-43; rig (s1) at his side | fig9_h3 molotov_y90_s0 vs _s1 |
| flame from the nozzle along the facing | verified from 45 degrees, from the side and from behind: a continuous stream from the nozzle to about two blocks, no upright teardrop beside him | fig9_h4 flame_y45/y0/y90 f104-135 |
| rocket on the shoulder, both hands | verified (unchanged since 707c344) until his own blast (self-blast is feel12-rocket-self-blast) | fig9_h1 rocket f0-44 |
| not done | the game's bottle is already in flight when the throw is seen (the clip starts at its forward swing, release about 3 frames later); the stream is round glow puffs, not a textured flame; the fire's ground light is very pale; the first-person rocket hand pop (feel12 report) not looked at | - |

**First person: strangers at his shoulder** (pm7-fp-own-head-and-shoulder-fill-left-third-of-view). This was not his own
body. In a real arrest and release (fig9_ar2: `wanted: busted`, then first person), the peds round him stood 0.25-0.30
block from the eye (`view: peds` lines). GTA2 lets a passer-by come within about 0.30 block, and drawn there he is a
head and a shirt cut by the frame's edge (fig9_ar3 f36, fig9_fw2 f1104/f1122). FIX-CAMERA-6's lens rule only covers
0.15. Now, in first person (strangers only):
- The eye is a body in the draw-only separation: a figure whose drawn point is within 0.40 block of the eye is drawn
  stepped out to 0.40, at the separation's sidestep speed (log `figure sep: ... from the first-person eye`).
- A stranger within 0.42 block and beside the eye (more than 35 degrees off the line of sight, or level with it or
  behind it) is not drawn (log `view: figure at his shoulder not drawn`).
- `GTA2DX9_FP_SHOULDER_CLEAR=0` turns both off.
Evidence: fig9_fw3 (plaza walk, 4 pushes, frames 196-350): no cut heads at the edges; a man walking straight at him
still comes to 0.40 (about 1.5 m, his torso a quarter of the frame, f208).

Tried and not shipped: a higher first-person guard with a corkscrew cross (fig9_fist_new vs fig9_fist_old). The rigid
forearm swung diagonally across the frame on each punch, worse than the straight jab. The fists need a bent arm (an
elbow), not a new path for the rigid one.

**First-person muzzle flash core** (FIGURE-8's short-of-AAA list). In first person the white core is 0.7 of the
(0.75-scaled) flash instead of 0.45, with three short star streaks out of the muzzle across the line of sight.
`GTA2DX9_FP_FLASH_OLD=1` gives the old core.

Probe: `linux/docker/fig9_heavy.py` + `keys_fig9_heavy.sh` (copy into gamerun/). Pickups (flamethrower, molotov,
launcher), the plaza, a step so the hero is drawn after the warp, third person. Per pass: the drawn figure turned by
the rig test file, 6.5 s at 30 fps with two taps and a held trigger. `FIG9_WEAPONS=flame,molotov,rocket`,
`FIG9_PASSES="flame=90:1,0:1;molotov=90:1,90:0"` (yaw:stance per pass).
`STAGE=<stage> GTA2_DIRECT_KEYS=1 FPS=30 PRIO=1 gamerun/grun.sh <run> 240 keys_fig9_heavy.sh -e GTA2DX9_STATE_EVERY=3
-e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_RIG_TEST_FILE=/tmp/rigtest -e FIG9_WEAPONS=...`

## FIX-FIGURE-10 (10 Nov 2026): a turn on the spot pivots on planted feet (pfl31)

pfl31: in third person a turn on the spot rotated the whole figure about its root, idle pose held, soles
sliding (a turntable). The old `turn_step` layer only ran above 0.9 rad/s of drawn turn, and even then the
legs turned with the root, so the "planted" foot swung through 1-1.4 cm block per lift (fig10_turn3 figj).

Now (live_geometry.cpp, the twist block and the turn_step layer):
- Standing (no action or a carry, not moving, legs speed under 0.06, walk weight under 0.3, the nearest
  eight within ten blocks), the legs hold a planted heading and the torso takes the turn as the existing
  Spine1 twist (up to 0.70 rad; faster than that the legs are dragged).
- Past 17 degrees of twist, or a residue over 6 degrees 0.3 s after the turn stops, one foot steps: a
  quarter-cycle of `turn_step` (phase 0-0.5 lifts the right foot, 0.5-1 the left, alternating), 0.18-0.28 s
  (shorter for a faster turn), the legs' heading eased to the torso's plus a small lead (a moving target).
- During a step the legs turn about the planted foot: its posed position is measured each frame
  (ModelNodeWorld, lod 0 only), carried round by the change of heading, and the root shifted (`pivX/pivZ`,
  bounded to 0.06 block, taken up over 0.2 s once he walks off) so the sole stays where it was set down.
- `GTA2DX9_TURN_PLANT=0` restores the old turntable (A/B). `figj:` lines (GTA2DX9_LOG_JOINTS=1) carry
  `pl py tw ps tc tw8 tr8` (planted, legs yaw, twist, step time, turn cycle, turn weight, turn rate).

Measured (P31=foot keys_pfl31.sh, 30 fps, the game turns him at ~4.2 rad/s): planted-foot excursion per
lift 0.0027 block mean, 0.0041 max (fig10_turn7) against 0.0067 / 0.0092 with the plant off
(fig10_turn7off, same build); frame by frame the planted sole holds within 0.003-0.005 block (2-3 px at the
chase distance) through each step (fig10_turn5/7 figj). Frames: fig10_turn7 zoom_after.png (the shoulders
turn over feet that stay on the same pixels, then a foot steps), ab_strip.png (off above, on below).
Not done: a mocap turn clip (the Rocketbox set has none under a CC0/MIT-class licence); slow turns
(under 1 rad/s) are covered by the 17-degree trigger but were not filmed (the probe's turn is the game's
fixed rate).

### pfl20: the first-person walk bob in step at any frame rate

The FIX-FIGURE-7 hand bob was there (amp 0.5-0.8 while walking, `fpvm:` lines under GTA2DX9_LOG_JOINTS=1)
but its phase ran on the clock at 1.9 Hz (3.8 Hz footfalls): on a CPU-starved capture (the filer's FPS=0
run, ours at CPUS=2: the game drew ~10 frames a second) it was sampled into a slow drift with no cadence.
Now the phase is driven by the ground covered, one cycle (two footfalls) per 0.76 block, the third-person
run cycle at his pace, plus a little clock time while he creeps; the bob is 30 % larger (down 0.0065, side
0.0045 block at full pace). Measured on the pfl31 walkway (gamerun/keys_fig10_fpw.sh, 30 fps, CPUS=4,
hand-skin centroid at 640x360): HEAD fig10_fpw4b vertical about +-1.7 px; fig10_fpw4 +-4-5 px at a
0.35-0.4 s period and a +-10 px side sway at ~0.73 s. The eye bob in step is the camera's (view_modes.cpp).

### pfl23 (view-model half): no frame without his figure or the gun on V into first person

On the 0.8 s move into his eyes his figure leaves the picture (under the frame's bottom edge, behind the eye,
outside the frustum, or cut at the lens within 0.15 of it) a few frames before it is hidden as his own; the
view model was drawn only once he was hidden: 2 (pfl23a) to ~20 (fig10_v1) frames with neither. Now in first
person any frame on which his own figure is left out, or has its chest and head (0.55 and 0.88 of his
height) off the picture, draws the view model (`g_ownLensFrame`). fig10_v4 (gamerun/keys_fig10_v.sh, two V
presses while firing the machine gun): every frame shows his figure or the gun and hands. The camera's dive
(the hero cropped to a head at the bottom edge before the hand-over) is FIX-CAMERA-10's.

### pmt3: the molotov is a bottle (model, third-person hold, first-person hold)

- `tools/gen_weapons.py molotov`: a round green body with a heel and a shoulder, a round neck and lip (it was a
  4-sided grey box on a cylinder), a rag stuffed in the neck with a strip hanging down its side, the fuel showing
  as a darker band in the lower glass; origin where the fist closes (under the shoulder), +y up; 964 triangles,
  span 0.058. Imported with `tools/import_assets.py` on a one-entry manifest (gen3d venv) into /tmp and copied
  (weapon_molotov.mesh, _0/_1/_2.tga; the manifest's report entry patched by hand). Remix: weapon_molotov_0/1/2.tga
  changed content (glass, fuel, rag; _2 is new).
- Third person, carried (not the throw, action 13): the in-hand attach laid the upright bottle along the fingers (a
  flat green slab against the thigh). Now it hangs upright in the fist, its shoulder in the closed hand 0.011 block
  ahead of the wrist along the fingers, tipped 10 degrees forward, at 1.35x the weapon table's length (a ~30 cm
  bottle; at 1.0 it was a 10 px chip at the chase distance). The grenade gets the same upright hold at its middle.
  `GTA2DX9_BOTTLE_OLD=1` = the old attach (A/B, both views).
- First person: the bottle 0.03 block higher in the view (it sat at the bottom edge with the fist under it and no
  forearm), so the right hand closes round its body with the forearm running out to the lower right.
- Probe: gamerun/keys_fig10_molotov.sh (rig-test yaw 90 side, 180 front, one throw, first person); runs
  fig10_mol1..3. The throw itself is unchanged (FIGURE-9's), including the arm held out ~1.5 s after the release.

## FIX-FIGURE-11 (10 Nov 2026): a car's brush, the shot flinch, the first-person arm textures

### pfl38 (ped half): a moving car's body brushing a pedestrian staggers her
- What the game does on a brush: nothing. pfl38a 04:54:14.9, ped 290 came 0.60 block from the driver's car centre beside
  its flank: health 50, state 1 sub 3 (fleeing) before and after, no knock-down, no damage. Drawn she ran on upright through
  the wing beside the dash. The run-over and knock-down paths stay the game's (he is a corpse then: `ragdoll: on`,
  the lying clips); no damage is invented.
- Now (live_geometry.cpp, before the hit block): this frame's car footprints (CarBodiesFootprints, the drawn body
  with its separation push) with their velocity from the last frame; a car moving 0.8-30 blocks/s whose footprint plus
  0.10 block (a body's half width) holds an upright pedestrian's game point (not boarding, in a car, down or the
  player) starts the shot-hit layer from the side she is struck on (hit_shot_front/back/l/r) and the stagger pushed
  off the flank she is on, along with the car's travel (in front of the nose: along the travel and off to her side),
  0.12 + 0.05 x speed, at most 0.30 block; one per car per second.
- A figure inside the body itself (a seated or boarding figure: the sprite the game reuses for the driver, health 100
  state 7 sub 0xe, 0.11 inside the flank, was "brushed" three times in fig11_br6) is skipped (fixed in the commit after
  c6f9b20; fig11_br7: three in-car segments, no false brush, 0 FAULT).
- A figure moving with the car (relative speed under 0.5 block/s) is skipped: the player's own reused ped sprite in his
  seat was "brushed" by his own car in fig11_br1 (06:09:02, health 100 state 7) before that rule.
- Log: `fig: brushed <ped> by car <obj> at S blocks/s (flank|end D off its right|left|nose|tail, game health H state S
  sub X): <side> jolt, pushed P` (GTA2DX9_LOG_PED_FRAMES=1). A/B: `GTA2DX9_CAR_BRUSH=0`.
- Seen in fig11_br5 (third, traffic): two brushes of fleeing peds 0.06 / 0.09 block off another car's flank at 4.8 / 6.1
  blocks/s, the game's health unchanged. Not yet filmed: both were off camera; the player's own FP brush did not recur in
  5 drives (fig11_br1/br3/br5: the F9 car spawns at a different place each segment).

### pfl37 (flinch half): what the filer's shot did
- The filer's five pistol shots (pfl37b) dealt no damage: no health drop on any ped in the log (a hit logs
  `fig: shot` or `fig: health ... nobody`); the shots went into the church wall while the ped walked past behind him,
  so the ped correctly played no reaction (the red brackets are the game's lock-on, not blood).
- A real hit plays the QB-16 shot reaction: fig11_mg2 (machine gun, third, wil plaza) `fig: shot 00a9 by ac1c
  (weapon 4, 1.8 blocks, left) health 50 -> 25` at 06:06:01.852; b_f11_2_third.mp4 frame 7 of the crop sheet (0.68 s)
  shows her hunched with both hands at her head, the frame of the health drop, then the death fall 0.07 s later.

### ptrmx27: the first-person arms' skin at 256 px
- `assets/models/fp_fist_right_0/_1.tga` (and the three `fp_arm_*` pairs) were 32x32 noise (`grain`, texture_max 32):
  on a fist a fifth of the frame wide each texel was a 4-5 px square of mottle. `tools/gen_weapons.py fine()` now bakes
  the arms' skin at 256 px as soft low-frequency mottling (two Gaussian-blurred noise octaves, faint pores, no per-texel
  noise) and the sleeve as a softened 4 px weave; manifest texture_max 256 for the four arm models; meshes byte-identical,
  weapon textures unchanged. Imported with `tools/import_assets.py` on a four-entry manifest into /tmp and copied (texture
  files and the manifest's texture_max only). Remix: the eight tga change content (new hashes).
- Frames: fig11_fist1 (plaza, first person, still/walk/punch) vs fig10_fpw4 at a 4x crop of the left fist: the square
  blocks are gone; the silhouette still shows the raster's stair-step (no anti-aliasing) and the 10-segment blob facets.

### pfl42: the first-person machine gun's flash on the muzzle, and a kick per shot
- Flash: ShotFxMuzzle and the view model's flash light were placed `boundsMax.z * k` along the barrel from the GRIP's
  axis; the S-Uzi's bore runs 0.017 over the grip (weapon_rig GeoFor bore, now `weaponrig::BoreHeight`), so the glow
  sat ~0.02 block under the barrel and read as coming off the receiver's left flank (pfl42a f42/f60). Both now sit
  on the bore line (`wu * bore * k`). Log: `view model: muzzle machine_gun at x,y,z (bore 0.017 x k 1.199 over the grip,
  0.116 ahead)`. A/B: `GTA2DX9_FP_MUZZLE_OLD=1`.
- Kick: the machine gun fires every ~0.1 s (3 frames); the kick's 0.03 s rise and 0.045 s return never came back below
  0.65 before the next shot, so through a burst the gun sat still, pushed back (pfl42a: gun and hands pixel-identical
  across flash frames). Automatics (machine gun, silenced MG) now peak on the shot's own frame and return with tau
  0.022 s (log `view model kick: t=0.000 kick=1.00`, 0.56 at 0.033 s, 0.20 at 0.066 s) and climb over a burst
  (+0.30 a shot, capped at 1, settling over 0.25 s: the muzzle tipped up 0.10 rad at full climb). Other weapons as
  before. A/B: `GTA2DX9_FP_AUTO_KICK_OLD=1`.
- Frames: fig11_mgk1 (keys_pfl42.sh) vs pfl42a, the first 12 frames of the held burst: the flash at the barrel tip in
  each shot frame; the gun's dark-pixel column centroid over non-flash frames 752-769 px (pfl42a 762-765 px).
- Not changed: the third-person torso (pfl16 family, row 5g) and the camera (no view kick: the camera is the camera
  seat's).

## FIX-FIGURE-12 (10 Nov 2026): the first-person reload keeps both hands, the suppressed flash

### pfl46 first person: the "bare vertical barrel" after a burst is the 30-round reload
- What the filer saw 1.2 s after letting go of the fire key is the QB-29 first-person reload (the renderer's magazine
  count: the silenced MG's 30th round fell in the held burst; log `reload: first person silenced_mg starts (magazine
  30)` 0.2 s after the release, `pose eased out ... (reload cut short)` when fire resumed). Its pose dropped the grip
  0.07 (at the two-handed 0.20 ahead the grip sits on the frame's bottom edge, so the right hand left the picture),
  tipped the muzzle up 0.22 and HID the support hand from the magazine's drop to its insert: a lone barrel, upright.
- Now (`DrawViewModel`): the gun comes in and up (grip 0.005 higher, 0.025 toward the middle, 0.015 nearer, muzzle up
  0.16 and turned in 0.14, rolled 0.55 to show the magazine well); the support hand stays drawn: fore grip -> under
  the well (drop..grab), riding the fresh magazine up from 0.05 below the gun (grab..insert; the magazine's travel is
  0.05 too, was 0.13 from below the frame), back to the fore grip over 0.15 s; its offset eases (tau 0.05 s), so a reload
  cut short by the trigger brings the hand back over a few frames. The pose eases in and out at 1/0.25 s (was 0.3 s).
  A/B: `GTA2DX9_FP_RELOAD_OLD=1`.
- Frames: fig12_p46h (HEAD d4188a4, keys_pfl46.sh) frames 232-264 of b_p46_first.mp4: barrel alone, no hands
  (reproduced). fig12_p46a (fix, keys_fig12_p46.sh, the filer's first-person sequence): frames 224-266 every 3rd at a
  crop: both hands on the gun throughout, the support hand dipping under the well and coming back, the grip in frame.

### pfl46 third person: a suppressed shot is a small dull puff, not a white bloom on the chest
- The silenced MG took the plain flash: an orange glow, a white core, three sparks fanning out and a muzzle light;
  the plain light pass (visuals.cpp) floors a muzzle light at 0.20 with half of it by day, and the game's own flash
  particle carries another (synthetic lights). Pointed at the camera, all of it sat over his chest: a white blob
  with streaks to the sides (fig12_p46o, the old path at the same pose).
- Now (`ShotFxMuzzle`): the silenced MG spawns one small warm puff (alpha 0.6, 0.05 s) and a faint grey smoke wisp,
  no core, no sparks, no light of its own; every frame a figure (or the view model) holds it, its muzzle is noted
  (`NoteSilencedMuzzle`) and the light pass turns any muzzle light within 0.8 block of one in the last 4 frames into a
  faint glow (x0.25, radius 1.2, no day share). In first person the view model's own flash light is x0.3 for it.
  A/B: `GTA2DX9_SILENCED_FLASH_OLD=1` (both).
- Frames: fixed camera in front of him (regress cam), fig12_p46o (old) vs fig12_p46a (new) three-quarter, frames
  104-142: the old white bloom and fanned sparks on shot frames are gone, the shirt no longer flashes; fig12_p46b
  head-on (the filer's pose): a small warm puff over the hands on shot frames.
- Not changed: end-on (the gun pointed straight at the camera) the gun is a dark block at the hands about the width
  of a hand, which is what a 0.17-block gun looks like end-on; against his dark shirt it has little contrast.

### pfl39 third person: the pistol's reload between spaced shots, none once the gun is gone
- The figure's reload (QB-29) waited for `!attacking`, and `attacking` includes the aim frame 139, which he holds
  through taps 0.65 s apart: the 6-round reload never started between spaced shots, and the count went off after the
  LAST shot, with the gun at 0 rounds about to be dropped; once the game's weapon word read none the weapon block no
  longer ran, so nothing ended the clip and he mimed the reload with empty hands.
- Now: only a shot (the ammunition or reload word, or a flash) cuts a reload off; it starts 0.2 s after the magazine's
  last shot, never at 0 rounds; with no weapon in his hands the request ends and the clip fades out from where it is.
  A/B: `GTA2DX9_RELOAD_FIX=0`. The first-person reload already counted shots by the ammunition word.
- Frames: fig12_p39a (keys_pfl39.sh): `reload: ... pistol starts` 0.2 s after shot 6, `magazine out at t=0.30`, cut off by
  shot 7. fig12_p39b (P39=first,third): see the order.

### pm24 (measurement only): one ped is not a pair with himself
- The 300-frame 'pairs closer than 0.10' count (FIGURE-7) counted a ped drawn twice in a frame as a close pair: 57 of 60
  logged pairs in fig12_shot1 were one car occupant's reused seat sprite paired with itself. Such pairs are skipped
  now, so the count measures real overlaps. A single-file step aside (alternate neighbours half a body to either side)
  was tried (fig12_pm24a: it triggered off camera) and left out: two figures of equal rank in a cluster stepped the same
  way and stayed 0.05 apart; see the order's note.

## FIX-KNOCKDOWN (10 Nov 2026): the knock-down plays to its end (owner item 1)

Owner report: a car hit him, he started to fall and then walked on. **Diagnosis** (log before any change,
`out/qb27_r9`, and the first FIX-KNOCKDOWN runs): the clip player was not at fault. A car knock-down of the player is
state 8 sub 0x18 for 11 game frames (**0.37 s**), and then the game puts him back in state 0/7. The corpse flag clears,
`wantAction` leaves 4, the action layer plays the lying clip backwards from wherever it was (mid-air), and the QB-27
ragdoll is blended back into the clips over 0.3 s. The result is a fall reversed before it lands. For a car hit the
reversed clip was `runover`, a somersault back up into the air. In first person nothing showed at all: the
eye's down camera waits for 0.8 s of state 8.

**What it does now** (`live_geometry.cpp` PedTrack `kd*`, `ragdoll.cpp`, `view_modes.cpp`):
- *Down until the body has landed.* For a car or blast knock-down (lying clip 2/3, ragdoll on), the figure stays
  down after the game stands him up: until the ragdoll is still plus a 0.45 s lying beat, at least 1.2 s and at most
  3.0 s from the impact. Once the game has stood him up, the body no longer follows the game's spot. An NPC the game
  walks off more than 0.3 block gets up at once.
- *Never far from the game's spot.* The ragdoll's pelvis is kept within 0.9 block of it. Past that the body is
  carried, as if dragged. (kd_t2: a truck dragged the game's ped 2.7 blocks one way while the throw carried the body
  the other way, so it lay 1.9 blocks off, out of the picture.)
- *Rolls over, then gets up off the front.* On his back he rolls over onto his front through the solver: a turn
  about his long axis toward the side the chest leans to, with a second try if the first leaves him on his back.
  Then he gets up with `fall_front` played backwards at 0.8x (hands under, up, about 0.95 s). If he is still on his
  back after both rolls, `fall` plays backwards. The clip is turned and placed onto the body. Its lying pose is
  measured through the drawn placement on the first get-up frame, so the head lands on the head and the pelvis on
  the pelvis (logged `get-up placed onto the body: turned N deg`; 0.0-0.1 in every run). The ragdoll's pose is
  re-driven into that placement and blended into the clip over 0.3 s.
- *Walks back.* The figure's draw offset onto the body (at most 0.9 block) eases back onto the game's spot over
  about a second while the legs step it.
- *Player's keys.* Movement, fire, enter and jump are not passed to the game while he is down and getting up
  (DirectInput buffered and immediate reads; `knockdown: player keys held/back` in the log). Keys still held when
  the hold lapses are pressed again for the game. Street views only.
- *Cameras.* The subject point of both street cameras is his body (the pelvis while he lies, then the placed
  figure), not the game's spot. First person: the eye rides the ragdoll's head down. The view tips 25 degrees and
  the gaze follows the chest (up at the sky on his back, down at the road on his front). It rises with the get-up.
  The fists or the gun drop out of the view and come back up. His own body is posed but not drawn from his eyes.
- Ini: `[renderer] knockdown_full=1`, `knockdown_hold_input=1`. `GTA2DX9_KNOCKDOWN=0` gives the old behaviour (A/B).
- Classic: not touched. The figure code does not run there, the hold refuses classic, and the camera override is
  gated off classic.

Probe: `gamerun/kd_probe.py` / `keys_kd.sh` (the QB-27 lane, `KD_VIEW=third|first`, one 30 fps recording
`b_lane.mp4`, 7 s with no keys after each impact). Run it with `GTA2_DIRECT_KEYS=1 FPS=0 -e GTA2DX9_STATE_EVERY=3`.
Phase frames come from `gamerun/kd_phases.py <run>` (impact, roll, get-up, standing, walking: v = frame of the
30 fps video).

| run (30 fps) | impact (throw speed) | phases (video frames) |
|---|---|---|
| kd_t4 third #1 | v1114, 0.80 b/s | still v1169, get-up v1184 (front), standing v1221, walking v1271 |
| kd_t4 third #2 | v2128, 1.83 b/s, lifted 0.40 | game down 2.1 s, roll v2240, get-up v2290, standing v2330, walking v2378 |
| kd_t4 third #3 | v2669, 1.01 b/s | still v2736, get-up v2752, standing v2788, walking v2835 |
| kd_t4 third #4 | v3241, 0.34 b/s (slow) | still v3295, roll v3310, get-up v3353, standing v3391, walking v3428 |
| kd_f5 first #1 | v168, 1.77 b/s, lifted 0.38 | roll v265 (rolled twice), get-up v351, standing v388, walking v436 |
| kd_f5 first #2 | v778, 0.80 b/s | roll v850, get-up v893, standing v930, walking v978 |
| kd_f5 first #3 | v1295, 1.02 b/s | get-up v1363, standing v1400, walking v1444 |
| kd_f5 first #4 | v1932, 1.79 b/s, lifted 0.38 | get-up v2001, standing v2039, walking v2090 |

Contact sheets: `out/kd_t4/sheets/t4e1-4.png`, `out/kd_f5/sheets/f5e1-4.png` (every 6th frame). Get-up at every
2nd frame: `out/kd_t2/e1r.png`. The first build's 180-degree flip at the get-up: `out/kd_t1/before_fix_flip.png`.
Pops: a per-frame image-difference trace (`kd_motion.py`) over the get-up blends of kd_t4 #1/#3 and kd_f4 #1 shows
ramps and no lone spike. The steps found were the camera starting to follow him walking (frames opened).
Classic: `keys_kd_classic.sh` (pm18 V-cycle A/B, F11 warp) on this build (kd_c1) and on the shared stage (kd_c0):
0 differing pixels among those static in both runs before any 3D view (638822 px) and after two V cycles
(681734 px).

**What still falls short of the AAA bar:**
- The get-up is the procedural `fall_front` played backwards. He tips up on fairly straight legs, and there is no
  real hands-and-knees push or a get-up off the back. A mocap get-up pair (`getup_front`, `getup_back`) needs new
  clips in `tools/gen_ped_clips.py` and a re-import of the 71 avatars (release archives), which this change does not do.
- The roll is the solver's, not an authored roll: a limb can flail or a knee fold sharply (kd_t2 #1 frames 430-445).
- The figure walks back up to 0.9 block onto the game's spot after he is up, which is a short glide at a walking
  pace.
- In third person the existing camera that pulls back over him (game state 8 for more than 0.8 s, kd_t4 #2) frames
  him small while he lies.

## FIX-KNOCKDOWN-2 (10 Nov 2026): no launch off the ground (pfl65)

pfl65 (on 174f6a7): the knocked-down hero lay still on the road and about 1.5 s later flew a block or more into the air
and cartwheeled, while the log reported a pelvis peak of 0.24. **Diagnosis**: a per-frame trace of the solver
(`GTA2DX9_LOG_KD=1`: `kdtrace:` solver pelvis height, the fastest joint, the upward speed, cars, walls, drift; `kddraw:`
the drawn placement) caught it in `kd2_a` on a lying ped. With no car, wall or drift event, the ground height passed
in moved from 2.016 to 2.042. That is the game's height for the ped, which changes by a few hundredths with its state
(lying vs stood up). The solver's floor clamp lifted every joint 0.026 within one 1/120 s sub-step and left the previous
positions where they were. Verlet reads that as an upward speed of 3 blocks/s, a 1.5-block flight. For the player it
fires just after the game stands him up, which is where pfl65 saw it. The 0.24 peak in the log was the earlier settle,
from before the launch.

Now (`ragdoll.cpp`):
- The floor is the ground he went down on, latched at the seed. Only a real change of level (0.15 to 1 block: a
  kerb, a step the game carries him onto) moves the whole body, with no speed.
- More than 0.6 s after the throw or a roll, no joint rises faster than 0.8 block/s. No pop can throw a lying body.
- Every other car near him shoves the lying body out of its box in one piece. The shove is square to the car's
  travel, toward the side his pelvis is on, at most the car's pace plus 0.5 block/s, and never up onto the car. All
  joints and their previous positions move alike, so no joint gains speed. The first try pushed each joint on its own;
  that fought the links and whipped limbs at 18 blocks/s (kd2_b, kd2_d). While a car shoves him, the 0.9-block leash
  to the game's spot gives to 1.6 and then shortens at 0.4 block/s, so it never drags him back under the car. Before, a
  second car drove through the body. A settled body is woken when a moving car reaches it.
- A/B: `GTA2DX9_KD_GROUND_LATCH=0` turns off all three.

Verified: `kd2_e`, third person, the kd lane, four impacts. Impact #1 is the filer's own throw (-0.79,-1.56 up 0.37 from
the truck), and a police car passes beside the lying body. The rigid shove fired on 66 trace frames. Outside the throw
and the rolls the pelvis never rises above 0.23. Joint speeds above 4 blocks/s occur only in an NPC's impact phase, in
the hitting-car code, which is unchanged. Frames opened at 6 fps from impact to walk, plus a 9 fps crop of the police
car's pass: he lies flat on the road while it passes, then gets up and walks. Classic: `keys_kd_classic.sh` on the shared
stage (kd2_c0) against this build (kd2_c2) gives 0 differing static pixels before any 3D view and after the first V
cycle. After the second cycle 228 differ; all of them are a game pedestrian sprite standing still in one run's window
(crop opened); the tiles are identical.
The played roll (FIX-KNOCKDOWN-2, triage pass 204: the solver roll flipped him through a head-down handstand). The roll
onto his front is no longer a velocity kick into the solver. It is played over 0.7 s: the whole body turns half a turn
about its long axis, through the middle of the torso at the height it lies, and moves 0.12 block toward the side it
rolls to. Elbows, hands, knees and feet are drawn in toward the axis mid-roll (up to 55 %) and are back at their lengths at
the end. Positions and previous positions are set together, so the solver takes over with no speed. kd2_r1 #2 (trace):
pelvis 0.030-0.034 through the roll, highest joint 0.089, no velocity after it, then up from his front. Frames opened at
10 fps (crop on the body): on his back, turns over along the ground, lies prone, gets up. `GTA2DX9_KD_ROLL=0` restores the
solver roll (A/B).
The walk-back of 3 blocks (FIX-KNOCKDOWN-2, kd2_r2 #1). The game walked his ped 3 blocks along his facing at a walk's
pace while his body lay pinned, and the get-up was placed 3.1 blocks off its spot. Cause: the DirectInput hook is
installed lazily, at the first knock-down. The arrow he was walking on had gone down before the hook, so it counted as
"told up": no release was sent as the hold began, and its real release was swallowed by the hold. Now, as a hold
begins, every held key counts as down in the game, so the next buffered read tells the game each one went up (a no-op
for a key that was already up). `view_modes.cpp` ViewHoldPlayerInput; `GTA2DX9_KD_HOLD_RELEASE=0` restores the old
behaviour for A/B. kd2_r3: six knock-downs, every get-up placed within 0.68 block of the game's spot
(before: kd2_r1 up to 1.0, kd2_r2 3.1). Classic kd2_c0 vs kd2_c3: 0 differing static pixels in all three windows.
First person through the played roll (kd2_f1): the eye's gaze followed the chest with no easing, so the view swung
from the sky to the road in 6 frames (0.2 s). The gaze is now eased over 0.25 s (`view_modes.cpp`, the knock-down eye).
kd2_f2: the sweep takes about 18 frames (0.6 s), as one turn. `GTA2DX9_KD_GAZE_EASE=0` restores the old gaze for A/B.
Classic kd2_c0 vs kd2_c4: 0 differing static pixels.
Still short: while he lies, the contact shadow stays at the game's spot, up to a body-length from the body (the shadow
pass, not the knock-down code). The get-up is still the reversed `fall_front`.
- The captures run 30 fps, but the game rendered about 20-25 fps on the loaded host (repeated frames in the
  recording).

## FIX-KNOCKDOWN-3 (10 Nov 2026): no head-down handstand when a car knocks a person over (pfl77)

pfl77 (first person, the F9 van nosing into a plaza pedestrian at ~0.3-1.4 blocks/s): for about half a second the
run-over man stood on his head beside the bonnet, both legs straight up. **Diagnosis** with an offline harness of
the solver (`ragdoll.cpp` compiled natively with stub headers, a synthetic running figure, the car a moving box; 288
hits: 6 speeds x 8 facings x 3 offsets across the car x 2 overlaps): 106 hits had a leg within 35 degrees of
vertical for 3+ frames (worst 32 frames). At low speed the car's friction carried the head along its bonnet past
the pelvis while the feet dragged on the road, so the body somersaulted forward onto its head. A second fault
showed in the lane (kd3_lane1 #2, a taxi from behind at 1.7 blocks/s): the throw lifted the feet 0.23 and gave the
upper body too little pitch, so he glided upright 1.2 blocks for 0.47 s before falling.

Now (`ragdoll.cpp`):
- *No cross-axis somersault.* Inside the solver's iterations the body may roll about its long axis as it likes, but
  the hips-to-feet line rises at most 20 degrees above level, hips-to-knees 50 degrees (knees up on his back), and
  the neck drops at most 30 degrees below the pelvis (draped over a bonnet). Positions only, like the links: the
  speed into the limit is removed, nothing is added (pelvis and head peaks unchanged in the harness). The correction
  only ever lowers joints (the feet, the pelvis end of the torso): the first version also raised the other end, and a
  man pinned between a bonnet and a wall climbed to 0.77 block in the harness.
- *Slow knock.* Below 3 blocks/s the car no longer folds him over its bonnet and does not lift him. He is knocked
  over along the car's travel with a pitch of 4.5 rad/s about his feet (head along the travel, feet held back), so
  he lands on his front (hit from behind) or his back (hit facing the car) in about 0.35 s. From 3 blocks/s the old
  throw (folded over the bonnet, lifted) blends back in. The pitch goes where there is room: along the car's travel
  if the ground a body length that way is clear of walls, else along the wall (never back onto the car). kd3_ro4 #2:
  hit toward a building, the walls stopped the pitch (15 of 17 joints sent back every frame) and she sank into an
  upright crouch and stood up without lying down.
- `kdtrace:` (`GTA2DX9_LOG_KD=1`) also logs `head`, the higher `foot`, the torso's up `tup` (1 upright, -1 on his
  head) and `legup` (legs within 35 degrees of vertical), for every body on camera or not.
- A/B: `GTA2DX9_KD_NO_FLIP=0` (both changes off).

| run | hits | legs-vertical frames | landed (pelvis < 0.07, torso flat) |
|---|---|---|---|
| harness, before / after | 288 | 1310 (106 hits with 3+) / 0 | f10-f11 (0.33-0.37 s) at up to 1.7 blocks/s after |
| kd3_lane0 (lane, GTA2DX9_KD_NO_FLIP=0) | 2 | 0 | 0.53-0.57 s |
| kd3_lane1 (no-flip, before the slow knock) | 5 | 0 | 0.47-0.57 s; #2 upright glide 0.47 s (frames) |
| kd3_lane2 (this change) | 6 | 0 | 0.37-0.40 s |

The get-up of a person the game runs on (pf3, FIX-KNOCKDOWN-3; `live_geometry.cpp`, the knock-down hand-back):
- *Pinned while it plays.* The figure's draw offset onto the body was held fixed relative to the game's spot through
  the get-up, so a fleeing NPC's rising figure slid along at the game's running pace (the skate). The get-up is now
  pinned where the body lies: kd3_ro5 (security guard hit by the own van) the drawn spot stays at 184.01,87.75 for
  every frame of the clip while the game's spot moves 0.5 block (the `kddraw:` trace); frames: up off her back in
  place, then walks off.
- *Walk-off at most a run.* After the get-up the offset is walked off as before (0.35 s ease) but no faster than
  2.5 blocks/s, so the legs step the catch-up instead of the figure gliding.
- *Lands and lies first.* An NPC the game walks off more than 0.3 block got up at once, even mid-fall (the "snaps
  upright" of pf3). Now not before the body is still or 1.0 s from the impact (landing ~0.35 s plus a beat).
- A/B: `GTA2DX9_KD_PIN_GETUP=0` (all three off).
Still short: the get-up is still the procedural `fall`/`fall_front` played backwards (arms flung out on the way up
from the back, kd3_ro5 frames): a mocap get-up is NEEDS OWNER 27. The 1.0 s beat is untested in a run (the runs
filmed the 0.7 s version).

## FIX-FIGURE-14 (10 Nov 2026): first-person fists, the shotgun, the pistol's last round

### pfl67: the first-person bare hands are fists on forearms, held up in a guard, swinging with the stride

- Seen (pfl67b, the 10:39 restage smoke shot_140): the two fists were twisted rope-knot shapes on the
  bottom edge, no wrist or forearm in the frame (the forearm ran back toward the eye under the frame's
  edge), and in a walk both bobbed together.
- Model: `fp_fist2_right` (tools/gen_weapons.py `fp_fist2`) is the pistol hand closed on nothing: the
  same back of the hand and the same wrist, forearm, elbow and sleeve (`_forearm` with fp_arm "right"'s
  points, 20 segments instead of 10), so the bare hands and the armed view model share one arm. The four
  curled fingers are one rounded block (`sblob`, a superellipsoid with grooves between the fingers and
  the knuckle row raised on its back-front edge; normals from the displaced grid), the thumb folded
  across the index and middle fingers. The tube-per-phalanx `fp_fist` read as a knot at view-model size.
  Code object in git (mesh + 2 tga, manifest entry); the left fist is its reflection as before.
- Pose (live_geometry.cpp DrawViewModel, `fist2`): a boxer's guard, palm down: 0.14 ahead, 0.066 to the
  side, 0.042 down (the fists at about two thirds of the frame's height, not on its bottom edge), the
  knuckles ahead and up (+0.6 up, 0.3 in toward the middle), the back of the hand toward the eye, so the
  forearms run out to the bottom corners. Walking, the arms swing opposed once a stride (the walk bob's
  phase): one fist 0.012 forward and a little up as the other goes back; at rest only the breath.
- Offline preview used to choose the shape and pose before any run: the FP placement maths in numpy
  (render of the view-model meshes with the game's 70 degree lens), not in git.
- Verified: fig14_f2 (wil 198.5,178.5, 30 fps burst: rest, straight walk, stop, three punches): both
  fists with wrist and forearm to the frame edge in every frame; the walk frames 33-52 (10 fps) alternate
  right-low/left-high and back (skin-mask centroids 478-529 px against 471-526 px, out of phase); punches
  throw one fist forward. Classic unchanged by construction (first person only); vreg below.
- Short of a shipping frame: the skin is one flat colour (no knuckle or nail detail in the texture); the
  forearm still shows facets in its shading; the left fist and forearm pass under the minimap.
- A/B: `GTA2DX9_FP_FIST_OLD=1` (the old fist, guard and bob).

### pfl72: the kill-frenzy shotgun fires in first person (flash, kick, pump), a pump-action model, no speck column

- Cause (fig14_sg1 log, HEAD behaviour): the first-person shot detector read the ammunition word and a flash
  ahead of the eye; a kill frenzy's weapon never spends a round (HUD "INF") and the shotgun leaves no small
  flash ahead, so the view model never kicked or flashed. The figures already read the weapon object's refire
  word (+2), which jumps on every shot: DrawViewModel now reads it too (`view model: shot seen (refire a -> b)`).
- Model: tools/gen_weapons.py `shotgun` rebuilt as a pump-action at the old span (-0.075..0.175, bore 0.012,
  fore-end middle 0.080, so the rig's points and the table length still fit): receiver, one barrel over the
  magazine tube, a ribbed fore-end as its own node `pump`, pistol-grip wrist, stock, rubber butt pad (548 tris;
  was two tubes over three boxes). Code object in git.
- First person: the shotgun is held lower right and further out (side 0.085, down 0.068: the barrel at ~40
  degrees in the frame instead of 54, the filer's "pointing at the sky"); after each shot, from 0.22 s for
  0.38 s, a pump stroke: the `pump` node (pose hook PumpPoseHook) and the support hand slide 0.045 back and
  forward, the gun canted 0.35 rad, pulled in and tipped up with the pull.
- The "pellets beside the forearm" were the game's impact debris (8/432-435, found with `GTA2DX9_LOG_FX=2`,
  which logs every effect/code-object sprite for 15 frames after a first-person shot): the game fires at his
  body's height, 0.30 under the eye, so at the filer's wall 0.7 block away the hits burst low beside the forearm.
  In first person for 15 frames after his shot that debris is lifted 0.30 (onto the aim line).
- Third person: on HEAD he already shoulders the shotgun and the flash is at the muzzle (fixed poses behind and
  beside him; the filer's front poses are inside the wall). The "dotted vertical column" was the game's gun
  smoke, tiny puffs (0.02 block) rising from his feet; near him for 2 s after his shot they are left out (drawn
  wider they made a pale blob at his feet).
- Verified: fig14_sg7 (FP: flash at the muzzle, kick, the pump cant and hand travel over frames 17-25, debris
  around the crosshair line), fig14_sg8 (third: aim with the flash at the muzzle, no speck column, no blob).
- Short of a shipping frame: no shell ejected on the pump; the stroke is the hand and fore-end, the gun does
  not cycle a shell; the debris still sprays up over the wall (the game's own chips); no smoke wisp at the muzzle.
- A/B: `GTA2DX9_SHOTGUN_FX_OLD=1` (no refire detection, pump, hold, debris lift or puff rule; the model stays).

## FIX-FIGURE-15 (10 Nov 2026): the flamethrower's jet in both views

### pfl76 (first person) + feel12 flamethrower (third person): one flame jet from the nozzle along the line of fire

- Seen (HEAD 05c78dc, fig15_fl0, wil plaza 159.5,139.5): in first person the held fire was one round disc about a
  block out at the middle of the view and nothing between it and the gun; the barrel pointed at the view's middle
  (the point 5 blocks along the eye's line) while the reticle sat lower on the game's line of fire; no movement
  in the hands. Third person: round glow puffs, beads along the stream.
- Causes: the first-person jet was spawned only on the frames the view model's shot clock took (every third
  frame), its puffs flew along the eye's line (foreshortened into one disc); the game's flames (8/381-390,
  `GTA2DX9_LOG_FX=2`) run along his facing at body height (0.30 over his floor, 0.39 under the eye) at about
  3 blocks a second and die ~2.5 blocks out. The reticle's own line test (hud3d, lids count) stopped 0.6 out on
  the plaza, under the nozzle.
- One mechanism (live_geometry.cpp `FlameJetEmit`, `FlameJetReach`): a continuous stream emitted for the
  frame's real time, textured flame tongues (FlameTexture, particle kind 7: turned at random, spinning,
  cooling from white-yellow to red as they fly) that leave the nozzle thin and swell to ~0.17 block at the end,
  out to 2.4-2.6 blocks or the first wall (side faces only: the game's flames run over kerbs and lids); at a
  wall a splash of tongues over the face and a scorch glow at the end of the jet; a hot white root at the
  nozzle; a smoke wisp off the tip. Third person: called on each muzzle frame (every other frame, 300
  tongues a second). First person: every frame while the ammunition word drops (it drops once a frame while
  held), 200 a second; a blue pilot flicker at the nozzle at rest.
- First person aim: the barrel aims at the far end of the game's line of fire (along his facing at his body's
  height, 2.5 blocks or the first wall), the same line the reticle is on; the flamethrower is held from the hip
  (side 0.05, down 0.10) so it rises into the picture toward the crosshair; held fire shudders it a little and
  pushes it back 0.004. The game's flame sprites within 2.7 blocks of him are left out in first person (2.4 in
  third, as before): its dark red stream sprites at the jet's tip read as a second flame.
- Reticle (hud3d): with the flamethrower, at the end of the jet (2.5 blocks, walls only), so the jet crosses it.
- Verified: fig15_fl6/fl7 (FP 10 fps crops through the hold: the jet leaves the nozzle and runs through the
  crosshair into a flame at the line's end, the ground lit by the muzzle light; third person fixed cameras
  behind and beside him: the stream from his hands along his facing). Classic: vreg spawn_classic 0 tiles.
- Short of a shipping frame: the end of the jet still reads as a ball from the eye (a jet seen along its
  length); no heat haze or dripping fuel; the hero's flamethrower in third person is a small dark stub; peds
  in the jet react only as the game makes them (fire on them).
- A/B: `GTA2DX9_FLAME_JET_OLD=1` (FIGURE-9's puff jet, the 5-block aim, the long guns' hold, the 2.4 cut;
  the reticle change stays); `GTA2DX9_FLAME_JET=0` (the game's flame sprites only).

### pfl78 (third person): the machine gun out in both hands at the chest, not stocked at the cheek

- Seen (HEAD, fig15_mg1, wil plaza, fixed cameras): side-on the S-Uzi was stocked at the cheek with both hands
  (a correct rifle hold); from behind the gun is hidden by his head and the right hand at the cheek reads as a
  hand at the ear with the flash beside his head (the filer's chase-camera frames).
- Fix (weapon_rig.cpp HoldFor, `mgOut`): in the aim the S-Uzi (stock folded) is held out ahead of the chest in
  both hands, the grip 0.06 right of his middle, 0.38 m ahead, at the shoulders' height (a compact SMG's
  point-shoulder hold, elbows soft; 0.48 out locked both elbows straight, fig15_mg2); the head looks ahead,
  not rolled onto a stock; the left hand under the handguard as before; carry and reload unchanged. The
  silenced MG and the electro rifle keep the shouldered hold (real stocks).
- Verified: fig15_mg3 side-on (both hands on the gun at the chest, flash at the muzzle, the kick) and behind
  right (the arms forward, the gun beside his right side, no hand at the head); the filer's chase camera (pfl78 probe, fig15_mg4): arms forward from behind, no hand at the head, the flash at chest height beside his right side; the gun itself is mostly behind his torso from straight behind.
- A/B: `GTA2DX9_MG_STANCE_OLD=1`.
- Short of a shipping frame: from straight behind the gun is hidden by his body (GTA5's chase camera sits over the
  right shoulder, which is a camera change); no muzzle-climb spread of the hands across a long burst.

### pfl78 molotov (both views) + feel12 molotov twin: the bottle leaves the throwing hand

- Seen (HEAD, fig15_mo1, wil plaza): third person the game's bottle (code objects 4/300-311 tumbling, its burning
  rag 8/400-410) appears 0.6-0.9 block over his floor, above his head, on the press, a few frames before the throw
  clip's arm comes forward (fig15_mo1 third 15 fps: bottle in flight frames 4-6, arm forward 6-9); held fire threw
  a bottle every few frames with no new swing. First person the bottle in the hand never moved (fig15_mo1 first).
- Fix (live_geometry.cpp `OwnThrowSprite`, `NoteOwnThrow`): from his press (the game lets the bottle go on it) the
  game's bottle and rag near him are left out until his throwing hand passes the release (the throw clip's 0.34 s;
  first person the view model's 0.05 s), then each bottle (by its sprite object) is drawn moved from the hand onto
  its own path, the offset eased out over 0.4 s; a new bottle near him with no press read yet is held back three
  frames (the game draws it before the press is read). Held fire: a press past the release swings again.
- First person: a throw: the hand thrusts forward and up (0.08 s, the release), follows through down out of the
  view empty (to 0.30 s), stays empty to 0.55 s, a fresh bottle comes up by 0.90 s. The bottle's flames ahead of
  the eye no longer count as a throw (each restarted it).
- Verified: fig15_mo4/mo7 third person (side fixed camera, 15-30 fps: bottle in the hand through the wind-up, at
  the hand as the arm comes forward, then away along its path; no bottle over his head before the swing); FP
  fig15_mo3/mo8 (thrust, empty hand, new bottle).
- Short of a shipping frame: the throw clip is the avatar's mocap from its forward swing (no wind-up behind the
  head, the game gives 1 frame); the bottle's arc is the game's (high); the empty FP hand is a fist, not an open
  release; grenades use their own code-object numbers (not mapped, not tested).
- A/B: `GTA2DX9_THROW_SYNC=0`.

## FIX-KNOCKDOWN-4 (10 Nov 2026): a car's near miss and brush, seen from the cab (pfl38 ped half)

pfl38 (first person: the car clips a running woman, she rides on upright beside the dash, no reaction). What the
game did at the filer's contact: nothing (FIX-FIGURE-11: 0.60 block from the car's centre, health and state unchanged),
so every reaction here is draw-only; the game's positions, damage and knock-downs are untouched.

- *Near miss* (`live_geometry.cpp`, the brush test). The filer's woman was a few tenths of a block clear of the
  paint, outside FIX-FIGURE-11's brush (0.10 block). Now a car doing 2+ blocks/s that passes within 0.30 block of a
  person on her feet (beside the flank, or ahead of a car coming at her, not behind one driving away; relative
  speed 1.5+) makes her shy away from it: the same side jolt, a push of 0.06 + 0.02 x speed (at most 0.16) away
  from the body with little along the travel. A real brush right after it still staggers her (the brush may
  follow a shy within the same second). Log: `fig: near miss, shied <ped> by car ...`. A/B: `GTA2DX9_CAR_SHY=0`.
  Seen in kd4_b2 and kd4_l2: a shy fired 0.15-0.25 s before the game's own run-over of the same person (she sees it
  coming, then the knock-down takes over).
- *Shove.* kd4_b1 (before this, first person, the own van at 1 block/s, a woman 0.06 off its nose): the jolt played
  (she turned to the car, a hand up), then the advancing bonnet met her game point and she sank through the dash
  for six frames and vanished under the pillar. For 1.2 s after a brush the car that brushed her keeps her figure
  out of its body as it moves on, through the parked-car slide of FIX-FIGURE-7 (off the flank; only a person square
  in front of the nose, within 0.35 of the half width of the centre line, is pushed ahead of it), at once (8
  blocks/s, not the 1.5 sidestep), capped at 0.6 block like the parked slide. Log: `figure sep: ... inside the
  brushing car ...`. A/B: `GTA2DX9_CAR_SHOVE=0`.
- Probe: `gamerun/keys_kd4_lane.sh` (F11 lane jack of a traffic car, KD4_VIEWS, KD4_SECS, KD4_OFF: the pass beside
  the locked person, KD4_PLAZA) or `keys_kd4_brush.sh` (the F9 van); `-e GTA2DX9_LOG_FIGURES=1` names the own-car
  contacts (a `fig: f=` line puts the person within 1.5 block of the player).

| run | own-car contact | frames |
|---|---|---|
| kd4_b1 (before the shove) | first person, van 1.0 b/s, nose | jolt, then sinks through the dash 6 frames |
| kd4_b4 | third person, van 1.2 b/s, two flank brushes | arms up, staggered back off the corner, no body inside the van |
| kd4_l2 | first person, taxi 1.3 b/s, nose, shove 0.14-0.38 | arms up at the contact, runs off clear of the bonnet (a burning car beside it) |

Still short: no stumble or fall for a glancing hit (the game keeps her running, and a drawn fall would leave the
body behind the game's person); a contact at the bumper of a high-dash van is below the first-person view; the
filer's exact sideswipe along the plaza wall was not re-hit (traffic is not repeatable).

### pfl51 (the free half): the rocket's recoil, a backblast at the breech, the tube beside the head

- Seen (HEAD, fig15_rk1, side fixed camera 30 fps): the launch kick was a small step of the tube, the breech showed
  nothing, and the tube sat across the head's height inboard of the shoulder (from behind it hid the head).
- Fix: weapon_rig.cpp: the tube's butt on top of the right shoulder 0.045 outboard (was 0.03 inboard), so the head
  is beside it; the launch kick harder (0.07 m back, 7 deg climb, shoulder 10 deg, chest 7). live_geometry.cpp
  ShotFxMuzzle: a backblast at the breech (a hot flash, a cone of grey smoke driven out behind him, sparks).
- Verified: fig15_rk3/rk4 side-on (flash, sparks and smoke out of the breech on the launch; tube kicks and settles;
  head beside the tube), fig15_rk2 behind-right (head beside the tube, the flash at the breech).
- Short of a shipping frame: no camera shake; the smoke is the shot particles' grey puffs (no dust kicked off the
  ground behind); FP unchanged (no backblast seen from the eye).
- A/B: `GTA2DX9_ROCKET_FX_OLD=1`.

## FIX-KNOCKDOWN-4 (continued): pmw2 / pm3, two identical gang men in a parked convertible's deck; a person inside a parked ambulance
- pmw2's filer log: the "two" red-haired men were one person handed in twice in the same frame (`figure sep pair`
  of 3e24b600 with itself, 0.016-0.05 apart), both copies drawn and both stepping his one track. The same ped slot
  (...b600, the shotgun redneck beside the car at the ste start) came in twice again in kd4_pmw2a (two `fig:` lines
  a frame at one game point, f=125-136, 211-215). Now each person is drawn once a frame (`fig: f=N <obj> handed in
  twice this frame: drawn once`; A/B `GTA2DX9_PED_DEDUPE=0`). kd4_pmw2b: 40 duplicates dropped, no duplicated
  `fig:` line left; frames r1_c/r1_d show one redneck beside the convertible's flank and nobody in the deck.
- The at-rest slide (FIGURE-7) does cover the open-top 044: kd4_pmw2a, the same redneck `inside parked car ...
  out by 0.33`. The pm3 ambulance walk (keys_pm4.sh) no longer reaches the ambulance from the HEAD ste start; a
  warp probe (gamerun/keys_kd4_amb.sh: the player walked into the parked ambulance's nose and flank, third and first
  person) stopped him beside its rear quarter, outside the body (kd4_amb2).

## FIX-KNOCKDOWN-4 (continued): pm24, a gang in single file
FIGURE-7's separation pushes each close pair apart half each, which cancels in the middle of a file (the member
behind pushes him forward, the one ahead pushes him back: FIGURE-12's finding), and its 0.14 block centre to centre
is a shoulder's width, not a stride. Now (`DrawPedFigures`, the separation): two people walking the same way
(facings within ~37 degrees, both above 0.4 block/s), one ahead of the other along the walk and within 0.22, are a
file: only the follower yields, dropping back to 0.22 behind the leader as drawn (last frame's, the leader's own
yield in it), so a file opens from its head back, a member a frame; the deepest leader counts, at most 0.3 (the
brush stagger's reach). The leader keeps his place. A/B `GTA2DX9_FILE_SEP=0`.
Measure: the 300-frame `figure sep:` line adds `in file closer than 0.16: N by the game, M drawn`. kd4_gang1 (wil
Loonie street, 64-66 people): 3/2/3 by the game, 1/0/1 drawn; kd4_pm24a (keys_pm24.sh): no file pair formed. Not
caught on camera yet (a warp hides figures until the game's camera arrives: the gang bursts framed a wall).
## FIX-FIGURE-16 (10 Nov 2026): pm24 separation residuals, the overarm bottle
Separation (`DrawPedFigures`), measured on fixed-camera films of real files (`gamerun/keys_fig16_file.sh`,
fig16_file.py: finds two walkers within F_D heading the same way in the `view: peds` list and points the regress
camera behind them; G_SPOTS 49.5,23.5 and 80.5,36.5 = the wil loony files):
- The pair push is measured between the two figures' points BEFORE their separation (half each when both can move,
  all of it when the other cannot). From his own unmoved point to the other's already-moved one at half each it
  settled at (d + 0.28) / 3: a pair the game walks 0.02 apart was drawn 0.09-0.10 apart, shoulders inside each other.
- The file yield never backs a follower into someone behind him, and no push is kept that puts a figure closer than a
  body (0.14) to anyone he was further from by the unmoved points (halved up to four times, else dropped): the yield
  and the pushes had drawn people the game kept 0.12-0.23 apart 0.02-0.07 apart.
- A/B `GTA2DX9_SEP_PAIR_OLD=1` (all three). Measure (300-frame `figure sep:` sums): closer than 0.10 drawn / by the
  game: fig16_file2 (before) 32/69, fig16_file4 (after) 10/142; in file closer than 0.16: 4/19 -> 7/61.

Overarm throw (`weapon_rig.cpp` HoldFor, cThrow): the right wrist IK follows keys on the throw clip's time (live_geometry
passes `throwT`): from the low hold up and behind the head (0.20), over the shoulder (0.28), ahead and high at the
release (0.34, FIGURE-15's bottle release), through and down across the body (0.44), back to the hold (0.62); the free
arm forward for balance on the wind-up. A/B `GTA2DX9_THROW_OVERARM=0` (the clip's underarm lob). fig16_mo1 backR:
the hand with the bottle up behind the head for the wind-up; at a 10 fps game the release and follow-through fall
between frames (not yet seen on film).

First-person open hand after the release: `fp_hand_open_right` (tools/gen_weapons.py `fp_hand_open`: fp_fist2's back of
the hand, wrist and sleeve, four fingers fanned out ahead and a little back-bent, the thumb out to the palm side; a
code object in git) replaces the grip hand closed on nothing for the throw's empty follow-through (`thHide`, 0.08-0.55 s
after the throw) until the new bottle rises. Log `view model: open hand after the release`. A/B `GTA2DX9_FP_OPEN_HAND=0`.
fig16_mofp2 fr/hands3.png: bottle in the hand / the open hand thrust out ahead / gone down out of the view.

## FIX-ENTRY-1 (10 Nov 2026): what the game needs for an entry, the Return trace, `enter_key`

Filing `ped-state-7-blocks-vehicle-entry` (S1, the 5090 operator): Return beside a parked car (0.59) with a
stopped driven car nearer (0.46), facing 0,-1 along both cars, never boarded; ped state 7 sub 0xE throughout.

**State 7 / 0xE is the ordinary on-foot state** (FUN_00433580 mode 4 sets exactly 7/0xE; boarding is mode 6,
state 3 sub 4; the objective walking to a door shows state 2). It is not a lock; nothing has to leave it.

**What the game does on Return** (read off gta2.exe 9.6, then measured):
- The player object is `[[0x5EB4FC]+0x38]`, his ped at `+0x2C4`. The control read (0x004A4B7C) turns the
  keys into bytes: `+0x7D` enter held, `+0x89` changed this frame. The player update calls FUN_004A76D0 unless
  `+0x2F` is set.
- FUN_004A76D0, on the press: in a car, objective 0x24 (get out). On foot, unless already leaving (objective
  0x24), FUN_00424E70 (on the vehicle pool `0x5E4CA4`) looks for a car with his sprite moved 0.5 block (the
  16.14 word at `0x5E4F38`) ahead along his heading, through the collision grid (FUN_00447540, called with
  2, 2: a search of cells round that point). Driven or parked makes no difference (a driven car is a jack).
- Found: FUN_00436920(ped, 0, 9999), objective 0x23 (0x25 as a passenger for 59..61) through FUN_0043BBC0,
  the target car at `ped+0x150`, `+0x248 = 0`, byte `+0x24C = 0`. The objective runs him to the door
  (state 2, then 3/4) and boards him. Not found: nothing, no state change.
- **Measured** (runs ent1_b, ent1_sw1, ent1_f8a, Downtown, plain GL, nav_map 0 and 1, all three views): every
  single Return of 70-120 ms boarded: at the driver's door facing along the car, 0.25-0.7 block ahead of the door
  facing along it (up to 1.48 from the car's centre), behind it facing back, and 2.5 blocks away FACING AWAY. A
  passing driven car ahead is taken too (a jack, ent1_b). So neither facing nor a driven car nearer explains a
  refusal beside a car at 0.59: there the game's handler did not run, or the key did not reach it.

**`GTA2DX9_LOG_ENTRY=1`** (env; for the 5090 box) traces exactly that:
- `entry: Return down reached the game's keyboard`: every Return the game's own DirectInput read returns (logged
  inside that read), then `entry: Return on foot (before the game's handler): ...` with his position, sprite
  heading, state/sub/vehicle, objective and target car, the player object's `locked` (`+0x2F`) and `enter_held`,
  the probe point and every car within 2.5 tiles in the car's frame (`probe along/across`), and then
  `entry: the game acted: objective a -> b, state ...` or `entry: watch ended ...` (45 frames).
- `entry: Windows reported Return down but the game's keyboard did not within 15 frames (foreground ...)`:
  the key is not reaching the game (its DirectInput device, the focus): an input-path fault, not a game rule.
- `entry: the game's keyboard read failed (hr ...)`: the game's device is not acquired; no key reaches it.
- `entry: Return down withheld from (knock-down hold)`: FIX-KNOCKDOWN's hold while he is down (by design).

**`[devtools] enter_key`** (e.g. `enter_key=B`: a letter, an F-key or a virtual-key code; off by default; not F8,
which GTA2 takes for its Options entry and so opens the F4 panel): runs the handler's own steps above on the
nearest driverless ordinary car on his level within 8 tiles, whichever way he faces and whatever traffic stands
nearer, without the keyboard path or `+0x2F`. The game's objective runs him to the door and boards him, so the
vehicle pointer, his state and the driver are the game's own and a Return afterwards gets him out (unlike
`scene_key`, which only moves him). Read like the other devtools keys (GetAsyncKeyState, this process in front,
the same path as V and C). Ignored in a car, while boarding/leaving (state 3/4), down (8), dead (9) or seated
(10); logs `devtools: enter_key: the game's entry objective 35 on the parked car ...`. `warp_key` is unchanged.
Probes: `gamerun/ent1_probe.py`, `ent1_sweep.py`, `ent1_nav.py`, `ent1_f8.py` (keys_ent1*.sh; mirrored in linux/docker/).

## FIX-FIGURE-17 (10 Nov 2026): fig4 (5a), every figure was its own mirror image: the gun in the left hand

**Cause** (FIX-FIGURE-5's reading, confirmed in frames). The avatars and their clips come from right-handed glTF (a body's
right at -x) and were placed in the left-handed D3D world without conversion: every skinned figure was drawn mirrored, so
the rig's "Bip01 R Hand" showed as his left and the pistol sat in his left hand; the shirt's pockets and any logo too.
`model->forward` negates x and z together (a turn, not a mirror), so nothing undid it.

**Fix** (live_geometry.cpp DrawPedFigures, the one figure placement). x of the fit matrix is negated: the mesh, its bones,
the held weapon, the shadow and the ragdoll all go through `world`. Figures are drawn without culling, so the flipped
winding costs nothing; the weapon's frame is rebuilt from the grip (a proper rotation: the gun is not mirrored). The
knock-down get-up placement (which measured the lying clip in model space with one scale for x and z) takes the model's
x as drawn (`kdMirror`). Classic untouched (no figures there). `GTA2DX9_FIG_HANDED=0` draws them as before (A/B). Cars,
props and the first-person arms (their own view model) are not changed.

**Measured** (runs `fig17_hand0b` old, `fig17_hand1` new; `gamerun/keys_fig17_hand.sh`: pistol, the plaza, four headings,
a classic frame and fixed regress-camera frames in front of and behind him, still and firing; frames opened). Facing the
camera: old, the pistol hangs in the hand on screen-right (his left); new, on screen-left (his right). From behind: old
screen-left, new screen-right, in every heading whose camera was not inside a wall (h0 front/back, h1/h2/h3 back). The
two-handed firing stance stays centred and forward. Evidence sheets: defects/evidence/fig17/fig4_hand_old_vs_new_4headings.png,
fig4_hand_zoom_front_back_old_new.png, fig4_fire_front_old_new.png. The classic sprite at 1:1 is ~20 px: in the
east-facing frames the dark pistol sits forward on his right (screen-south) side, the same hand; too small to call in
every heading.

**Not checked yet**: the boarding door grab (grab_door_l/_r) and the jack side, the punch combo sides, Remix figure layer
prims (the geometry's hash is unchanged, only the world matrix differs), crowd peds with long guns.
