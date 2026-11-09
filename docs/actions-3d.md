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
| first person weapon | the view mode + a fresh flash/bullet within 1.2 block ahead of the eye | the weapon model lower right of the eye (0.24 block ahead, 0.095 right, 0.085 down; two-handed 0.20/0.055/0.075), barrel on the view, drawn without depth test after the figures; the same kick (back by the weapon's kick, tipped up 10 %), the muzzle glow, light and case at its muzzle; shown while the game names a weapon, else for 5 s around a shot | verified: pistol lower right with the barrel on the view, kick logged (1.0 -> 0.72 -> 0.44 over the frames after a shot), cases and the game's flash in frame (`shoot_probe2` *_f_*, `shoot_ab4` mg_f0) |

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
15, for a script driving fast.

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
