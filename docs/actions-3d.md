# Actions in the street-level views (7 Nov 2026)

What the game does, how the renderer learns of it, and how it is drawn in third
and first person. "Verified" means seen in a frame of a scripted run on the L4
build; "mechanism" means the code path exists but the game state that triggers
it was not reached in a run. The classic top-down view is untouched by all of it.

| action | the game's signal | drawn as | status |
|---|---|---|---|
| walk, run, idle | ped position per frame, frames 0-15 | Rocketbox clips, stride-matched, smoothed heading | verified (earlier passes) |
| punch | frames 115-130, state 7 sub 0xe | `punch` clip, one-shot, re-triggered per swing | verified (earlier passes) |
| knocked down, get up, dead | corpse flag, state 8/9 | `fall` held lying, played back out on recovery | verified (earlier passes) |
| get in / out of a car | frames 16-35, state 3/4 | Rocketbox crouch in/out | verified for NPCs; the player's own climb untested |
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
| trains, buses, tank, bank van | ordinary vehicles | their models (bus and bank van seen driving in QA2 / the master demo) | bus and army tanks verified in play (POLICE-3D); trains still not caught in a frame |
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
| NPC gunfire: stance, muzzle, tracers | his weapon object's words / a shot beside him | as the player | police: not done (they arrest rather than shoot at 2-4 stars; POLICE-3D); army: tank cannon shots in frame, soldiers' rifle carry in frame, their own shots log only | pol_army1 `tank10_04`, pol_army2 `tank10_09`; `ped anim: object ... action 2/8/16` |
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
| trains | ordinary vehicles, models 59-61 | car models | log only: six POLICE-3D tries (beside the street-level line: drowned in the harbour twice; under the elevated line facing it in first person: the line in frame, the train never passed while the frames ran) | pol_veh2..6 |
| bus | model 11 | car model | verified in play: driving past the arrest | pol_arrest6 `a_046`-`a_048`, vehicle log m11 at 174.6,143->126 |
| tank turret | the game's turret sprite heading over the hull | model split at 56 % of the roof, turned to it (`TurretSplitFor`) | verified in play for the army tanks (turret off the hull's line, aimed his way); the exact barrel bearing judged by eye only | pol_rescue1 `r17_01_05/10`, pol_veh3; `turret turned N deg` |
| fire-truck water cannon (the "ladder") | its sprite (0.44 x 0.19 tiles) over the truck | the roof gear behind the cab turned the same way | log only: sprite found and the split drawn while a fire truck drove to the carnage, not framed | pol_rescue1 `turret: model 17` |
| siren beacons (cop car, SWAT van, ambulance, fire truck) | delta mask bits 15..18 (vehicle+0x08) | two flashing roof glows by model (`DrawBeacons`); `[devtools] force_sirens=1` | cop car verified in play; fire truck log only (`beacons on model 17`); ambulance not framed (it drove to the carnage, pol_rescue1, not caught) | pol_arrest3 `a_037` crop |
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
`tank10_09`, `pol_army1` `tank10_03`): the army ped type's model or tint (people subsystem).

### Scripts

`linux/docker/pol_probe.py` (`keys_pol_probe.sh`; `POL_MODE=arrest|fight|car`, `POL_STARS`, `POL_COPCAR`,
`POL_HOLD`, `POL_SECS`, `POL_REWARP`), `pol_vehicles.py` (`keys_pol_vehicles.sh`; `POL_VEH="tank firetruck
train bus army rescue"`), `pol_sheet.py` (the sheet), mirrored in `gamerun/`. Run with
`STAGE=<stage> FPS=0 INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' gamerun/grun.sh <run> 260 keys_pol_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_LOG_VEHICLES=1 -e POL_MODE=arrest -e POL_STARS=2 -e POL_COPCAR=1 -e POL_HOLD=600`.
Sheet: `out/police_3d_sheet.png` (local, not in git).
