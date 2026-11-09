# Missions batch 4 (MISSIONS-BATCH4, -2, -3, Wave M)

Runners: `linux/docker/missions/armored_car_clash.py` (BATCH4), `sunbeam_contract.py` (BATCH4-2), with their
`keys_*.sh`. Both on the shared libraries (`mission_lib`, `drive_lib`, `skills/*`), none forked.

## ARMORED CAR CLASH! (wil_zh1): not completable by ramming

Script: two Yakuza Miuras (bulletproof, rocketproof, flameproof, locked) drive round Downtown; destroy both within 360 s
(10 799 frames). The phone (red, Zaibatsu, 4 bars) was answered with the respect aid and the roof climb (`mb4_acc1`).

Evidence of why it cannot be played out with a stock car: in `mb4_acc1` one head-on charge on the Miura (id 222,
speed 4.1) took its damage word from 32000 to 31737, and three more touches to 31472, i.e. 260 to 530 points per
contact, while our own car lost 580 for the same contact. A wreck needs about a hundred such hits per car, within 360 s,
against a car that outruns a chase (it was 100-180 blocks away for most of the run). No heavy vehicle, no wreck from
rounds, rockets or fire (the script blocks all three). Not attempted further: a developer aid that writes the
Miuras' damage would stop being the job. Sessions: `mb4_acc1` only (phone answered, 360 s timer ran out, message 1125).
Status in the catalogue: not completable by the skills (ramming); open for a heavier ram vehicle (tank, bus) if one can
be brought into Downtown.

## SUNBEAM CONTRACT! (bil_km2)

What the script wants (`assets-src/missions/bil_m/bil_km2.mis`): 3843 title, 3148 brief, a Krishna convert at
224,186.5 (stand within 2: he joins, 3120, the arrow to 202.5,34.5, the Russian zone). In the zone (`IS_CHAR_IN_GANGZONE`)
the player's Russian respect drives the job: at -1 bar a pistol assassin is made at 218.5,51.5 (3126), at -3 a molotov
one at 123.5,77.5 (3127), at -5 a shotgun one at 145,77 (3128); each is told to kill the player. Deaths: 3129, 3130
(the script shows nothing for the third, a typo in its message test), all three: 3141, 3100 JOB COMPLETE, $60,000.

Runner: Krishna respect 60 (the yellow phone, developer aid), the scene warp to the street under the terrace (as
COSSACK CONVERSION), the climb on foot, the terrace's machine gun, the convert by car and on foot, the zone by car,
then the Russian respect lowered in the zone through the game's own gang table (developer aid: killing Russians until the
game lowers it is not the job), then `skills/gunfight.gunfight`. All aids are in `marks.txt`.

What was learnt (sessions `mb42_sc1` .. `sc12`, out/ of the host):
- Gang indexes in Industrial: 0 Krishna (name unreadable), 1 Zaibatsu, 2 Russians; `b2_respect.exe` takes an index.
- The respect byte is in bars of 20: the script's -1/-3/-5 are bytes -20/-60/-100. A poke to -1 does nothing; -100
  at once trips only the -1 bar man, so -20, -60, -100 in turn.
- The assassins appear in `view: peds` as `gang/russian` riding Buicks (model 10), like Russian civilians; only the arrow
  (shown while on screen) tells them apart, plus the 15 s after the trigger near a spawn point. Selecting every Buick
  rider shot civilians (wanted level, arrest).
- The pistol man reaches the zone within about 30 s. The molotov and shotgun men came to the zone in one Buick in
  `sc9` (and one of them was run over, 3130 without a shot of ours) but not in `sc11` in 10 minutes.

### SUNBEAM CONTRACT sessions (`mb42_sc1` .. `sc16`)

| session | reached | ended because |
|---|---|---|
| sc1 | refused at the phone (3092) | respect aid matched no gang by name: "kris" finds nothing, the Krishna are gang 0 |
| sc2 | phone 3148, gun, convert joined (3120), car burned on the way, **zone entered (3122)** | -1 poke did nothing (bars of 20); stopped |
| sc3 | same, pistol assassin triggered with -20 (3126), 300 s without a hostile picked | the assassins ride Buicks, no arrow until on screen: selection fixed |
| sc4 | pistol man's car came, fight started | the player was killed at the fight start (6 hits in 4 s, no shots fired: the skill walked onto the raised deck) |
| sc5 | pistol man **killed** (3129) | two Russian civilians in Buicks shot too: wanted level, arrested (4209) |
| sc6, sc7 | sc7: pistol man killed (3129) | molotov and shotgun men never reached the zone in 10 minutes standing still |
| sc8 | -100 in one poke triggers only 3126 | killed by the pistol man at 21 blocks, no rounds fired (anchor and hunt set) |
| sc9 | **3129 and 3130 both seen** (the second man was run over, not shot by us), shotgun man not found at the spawn points | stopped after 240 s at 145,77 with no JOB COMPLETE |
| sc10, sc12, sc13 | pistol man killed (3129) in sc10/sc13 | arrested (sc10, sc12) or killed by the molotov man (sc13) within 30-60 s of the start |
| sc14 | **3129 and 3130 again**; shotgun man killed the player on the 100-block walk between patrol points (outside any fight) | dead (life lost) |
| sc15 | the convert had walked off (no 3120), the job still in its first phase | invalid; convert retry added |
| sc16 | all three triggered | killed 5 s into the fight without a hostile in sight (health 30 at the fight's start) |

Result of BATCH4-2: **no JOB COMPLETE**. At best two of the three assassins' deaths were registered (sc9, sc14).

### BATCH4-3: SUNBEAM CONTRACT complete (`mb43_s1` .. )

Two changes to the runner, no change to the shared skills:
- the gunfight engages from 18 blocks (`SC_ENGAGE`, was 10) with `far` 34 and `close_car` 15: the marked Buicks
  (the on-screen arrow, or the spawn-point rule in the 15 s after the trigger; never an unmarked Buick) are shot
  while still driving up, before the shotgun man is in range;
- the 270-block drive to the Russian zone is played in full (no `SC_WARP_ZONE`): `to_point` takes a new car and
  drives again when a drive ends short (`mb43_s1`: a hit on a cop ended the drive and the 270-block walk got nowhere).
  The runner stops with "never reached the zone" rather than fighting outside it.
Health and arms: the player enters the zone at health 100 with the machine gun (150 rounds) from the terrace; no health
pickup was needed once the fight no longer starts on a long walk under fire (the `sc16` 30 health came from the walk).

| session | reached | ended because |
|---|---|---|
| mb43_s1 | drive ended after a cop hit (wanted 1), 270-block walk stuck at 121,113 | invalid: runner fixed (new car, new drive) |
| mb43_s2 | **JOB COMPLETE** (3126-3128, 3129, 3130, 3100, $60,000, lives 5), 1007 s of game time at speed 2 | complete; fight 28 s, health 100 -> 60, 4 Russians down (the three marked men and one rider), no wanted level |
| mb43_s3 | drive to the zone gridlocked at 165,32 (a standing car, three 420 s drives) | stopped at the wall limit: walk the last stretch (fix) |
| mb43_s4 | convert stage: burned car, then a steal-car chase 150 blocks the wrong way, arrested (3093, 4207) | invalid; the walk-short rule added |
| mb43_s5 | zone reached on foot after the drive, all three triggered, **pistol man killed (3129)** in 2 min; the molotov and shotgun men never came in 8 more minutes | spawn-point patrol added |
| mb43_s6 | the convert died (3149) on the way, the run went on without him; arrested in the zone (4208), gun lost, no assassin made | invalid: 3149 now ends the run, 4207/4208 are arrests |
| mb43_a1 | acceptance 1: the convert died (3149) near the zone and the player died when the car burned in the gridlock at 166,35 | failed |
| mb43_a2 | acceptance 2: the car hit a cop near the phone street (wanted 1), arrested, respawned at the police station | failed (4208) |
| mb43_a3 | acceptance 3: the convert died (3149) 30 s after he joined, then the player died | failed |

Status: **SUNBEAM CONTRACT is not at 2 of 3 acceptance sessions.** One full JOB COMPLETE (`mb43_s2`: the whole job
played from the phone warp, the drive to the Russian zone with no `SC_WARP_ZONE`, 28 s fight, chase-view frames of
JOB COMPLETE and the $60,000 message, health 100 -> 60), and the three acceptance runs after the final changes (`a1`-`a3`)
failed before the fight on the long drive, not in it. Pistol/molotov/shotgun men were all killed from range in `s2`
(engage 18); in `s5` only the pistol man came. The open blockers, in order of cost:
1. the Krishna convert dies in traffic on the 270-block drive to the zone (3149, three of nine sessions): he follows the
   player's car; a drive that keeps the convert alive, or a convert escorted on foot, is not built;
2. the drive itself: standing cars at 165,32 (the lane to the zone), cops hit near the phone street (wanted level, arrest);
3. the molotov and shotgun men often do not reach the zone (s5, sc11): the spawn-point patrol is untried.
The runner's final code is the one in this commit (park 16 at the convert, 40 at the zone, `3149` fails the run, arrests stop it).
The third job (HAPPY GAS SMASH, FIRE TRUCK FUN) was not started: the brief's move-on rule is for a SUNBEAM at 0 of 6, and it had one.

Developer aids used, all in `marks.txt`: Krishna respect 60 (yellow phone), the scene warp to the street below the
terrace (`SC_WARP_PHONE=1`), the warp to the Russian zone (`SC_WARP_ZONE=1`, tuning runs only; sc2-sc4 drove the
170 blocks and burned the car twice, 400 s), the Russian respect pokes. Not used: any damage poke.

Not done: a second ARMORED CAR CLASH session.
