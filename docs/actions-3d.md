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
| hands up / arrested | frames unknown (`g_pedHandsUpFrames` -1) | `handsup` clip exists, disabled until the frames are measured | open: no arrest provoked by any script yet |
| burning | corpse/fall + the game's fire sprites | fall clip, fire sprites now upright | mechanism |
| headlamps, tail lamps | `[renderer] car_lamps`: dark = the sky's sun below 6 deg; 2 = always | additive radial glows at the body's ends (3D models and sprite-built bodies alike), none on wrecks | see the run notes below |
| brake lamps | the body's own speed frame to frame: a car losing > 1.5 blocks/s^2 | the tail glows flare red and grow while braking, day or night | see the run notes below |
| helicopter rotors | object animation `rotor` (base 4 frame 0) | a synthetic spin clip on the `rotor_5` node (mast, 7 rev/s) and `tailrotor_7` (hub) | mechanism: no helicopter appeared in the runs |
| car doors opening | a pedestrian in state 3 (getting in) or 4 (getting out) next to the car, matched by the ped's vehicle word or by distance; `[devtools] force_car_door` for checks | the body is split once per (model, side, door rows from CARI) into a hull without the door panel and the panel itself, which swings 60° about its front edge at 2.5/s and shuts at 1.7/s; the inside of the panel is lit like the outside; not on wrecks nor on the own car from the seat (`car_bodies.cpp` DoorSplitFor, DoorState) | verified: the split is built and the door opened at every entry and exit of three runs (`out/dd1..dd4`); frames in `out/doors_dents_sheet.png` |
| car damage, dents | the vehicle damage byte (+0x74: 0 fresh, rising with every knock, the car burns past about 200), in four steps of 64; `[devtools] force_car_damage` for checks | a dented copy per (model, step): three octaves of value noise over the car's frame press the shell in along normals smoothed across every seam (both paint-split halves move together), at most 2 % of the body length at the top step, normals rebuilt from the moved faces; the paint dulls 6 % a step; the smoke and fire over a badly damaged car are the game's own sprites, stood upright (`car_bodies.cpp` DentedModelFor) | verified at forced steps 0 / 96 / 160 / 255 from the chase camera and the driver's seat (`out/dd3`, `out/dd_steps_sheet.png`): no tearing, no light through the shell, a fresh car unchanged; the first version (per-vertex normals) tore the hull and showed white through it (`out/pd3_ste4/shot_1685.png`, build of 18:01), replaced |
| trains, buses, tank, bank van | ordinary vehicles | their models (bus and bank van seen driving in QA2 / the master demo) | trains and tank not seen in a frame |
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
