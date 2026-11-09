# Missions batch 3 (Wave M, MISSIONS-BATCH3, 9 Nov 2026)

Three jobs nobody had started, each played by the Wave M skill modules. The runners live in
`gamerun/missions/` (mirrored in `linux/docker/missions/`). The claims are in
`/mnt/gta2/agents/MISSIONS-CLAIMS.txt`.

| job | runner | skills | state |
|---|---|---|---|
| `ste_ze1` SCIENCE FRICTION! | `science_friction.py`, `keys_science_friction.sh` | rooftop_access (walk), car_bomb, steal_car (carriers), mission_lib.run_over | see Sessions |
| `wil_yh1` SWAT VAN SWIPE! | `swat_van_swipe.py`, `keys_swat_van_swipe.sh`, `mb3_respect.c/.exe` | rooftop_access, steal_car, deliver_intact | phone answered (svs2-svs4); a SWAT van comes at four stars; arrested by its troops |
| `bil_ke2` COP CAR SCRAP! | `cop_car_scrap.py`, `keys_cop_car_scrap.sh` | rooftop_access, steal_car, crusher_crane (crane5 to crane6 pair) | phone answered by the climb on foot (ccs2, ccs3); no Cop Car taken yet |

GANG CAR BANG! (`ste_rh1`) was claimed first and then handed to MISSIONS-BATCH2, which was already
running it (`b2_gang_car_bang.py`). ARMORED CAR CLASH! (`wil_zh1`) was looked at and released: its two
Miuras are bullet-, rocket- and flame-proof and locked, so only ramming works, and ramming is the
weakest of the skills (docs/skill-destroy.md).

## SCIENCE FRICTION! (ste_ze1)

What the script wants (`assets-src/missions/ste_m/ste_ze1.mis`):
- 2464 title, 2551 brief. Montana's Pickup (model 41) is at 24.0,41.5 with four Rednecks guarding it:
  Molotovs on the roof at z 4 and two machine guns on the street.
- In the Pickup, he gets the car bomb. The block is `IS_CAR_IN_BLOCK (179.5,234.5, 3 x 1)`, south of
  the SRS Clone Test Center (177-180 x 229-233). Keys: 2553 drive, 2555 parked, 2554 left, 2558 out
  un-armed, 2556 armed. Wrecked in the block gives `EXPLODE_LARGE` over the lab, then 2999 and
  $30,000. Wrecked anywhere else gives 2552 / 2559 and 2998.
- The block is a 5 x 2 field pocket (176-180 x 234-235). It is walled on three sides, and the only
  way in is a one-cell field lane down column 176 from row 228. The car comes down the lane and
  turns east (`line`). The escape is a fixed route back west, up the lane, and west along row 228.
  The computed routes refuse the lane because it passes the lab's blast points.

Geography learned in the sessions:
- The Zaibatsu phone stands on the north-east plateau, whose streets are level 2. The road column
  167-168 passes it. A climb planned from the river road at L1 crosses 138-140,24 by the water, and he
  drowned twice there (sf1).
- The plateau has almost no traffic. In sf3 and sf6 no car stopped, and none could be jacked, in 6-10
  game minutes.
- Driving from the plateau to the Pickup failed three ways:
  - sf4: a car pinned at the 118,39 crossing burned.
  - sf5: a jacked Zaibatsu gang car was shot to pieces by their gunmen by the HQ.
  - sf8: a hand-made avenue at x 72 is broken near row 100, and the Pickup was pinned at 88,22.

Developer aids (marked `WARP` / `DEV AID` in `marks.txt`):
- `SF_WARP_PHONE=1`: to the L2 road 8 blocks south of the phone.
- `SF_WARP_CAR=1`: from the phone to the road 13 blocks south of the Pickup (30.5,54.5).

Everything from the Pickup on is played: the guards, boarding, the 250-block drive, parking, arming
and the escape.

### Sessions

All sessions: `SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0`, the shared `repo/stage`, and
`CB_DRIVER=old GTA2DX9_STATE_EVERY=3`.

| session | reached | ended because | fixed in |
|---|---|---|---|
| sf1 | climbing to the phone | the climb from the river road walked by the water at 138,24; he drowned twice (respawned at 195,140) | warp to the L2 road 167.5,27.5 |
| sf2 | **phone answered (2551)** | `rooftop_access.descend` toward the Pickup walked him over the river bridge (rows 21-24); he died there, JOB FAILED | no descend: the terrace is the street level |
| sf3 | phone | no car stopped on the L2 road (4 kerb waits). `clear_guards` saw no guards (they were outside the 30-block peds window), so the skill walked 140 blocks and he died | main road for a car; no handover more than 25 blocks off |
| sf4 | phone, a car | the car was hit repeatedly at a standstill at 118.5,39 and burned; 5 kerb waits failed | `steal_car` for carriers; road stand-off point 30.5,54.5 |
| sf5 | phone, a jacked car | the car was a Zaibatsu gang car: their gunmen burned it in 10 s and killed him | gang models excluded from carriers |
| sf6 | phone | no traffic at all on the plateau in 10 game minutes; stopped by me | `SF_WARP_CAR=1` |
| sf7 | **phone; both street gunners run over (one borrowed car burned); Pickup boarded at carhp 32000; 120 blocks driven (23450)** | a wanted level at 143,117 (by the spawn and the police station); he was pulled out of the Pickup | via points |
| sf8 | phone, guards, Pickup boarded (32000) | my hand-made via route was broken; the Pickup was pinned at 88,22 and burned | router way, vias only for the last approach |
| sf9 | phone; borrowed car burned during the run-over; two gunners left | shot dead at the Pickup's door | the gunner count only at the two GUARD_SPOT posts; 360 s of run-over with replacement cars |
| sf10 | phone | the run-over car burned in 50 s (Molotovs) and the gunners shot him | `SF_GUARDS=0`: straight to the Pickup |
| sf11 | - | the phone warp was not taken (its own state read was stale under load); the climb from the start walked over the river again; stopped by me | `warp_verified`: a fresh position 3 s after each press |
| sf12 | **phone; Pickup boarded at 32000 in 8 game-s with no fight** | the slow precious drive north through the Rednecks' zone (60-75 x 25-50) took hit after hit, down to 15938 and burning, 185 blocks short; stopped by me | a fast exit leg east along row 34 |
| sf13 | phone, Pickup boarded | the fast leg's smooth driver stalled in the Pickup's shelter and backed west into the gunners (32000 -> 2372 in 3 s) | the old driver for the fast leg |
| sf14 | phone | shot at the Pickup's door again; respawned at the hospital, and `enter_parked` took that as "a passing car" | (open) |

### Result and what is open

**No JOB COMPLETE in 14 sessions.** Verified in game:
- The phone is answered (sf2 on).
- Both street gunners were run over once (sf7).
- Montana's Pickup was boarded at full health (sf7, sf8, sf12, sf13).
- The Pickup was driven 120 blocks toward the lab (sf7).

Never reached: the lab block, parking, arming and the escape.

What blocks it:
1. **The two machine-gunners at the Pickup.** Boarding with them standing is a coin toss: survived in sf7, sf8 and sf12; shot dead in sf9 and sf14. Running them over burns the borrowed car (the roof Molotovs). The robust way is a gun first and the gunfight skill. No machine-gun pickups are catalogued for `ste` (`mission_lib.GUN_PICKUPS`), so that needs a pickup survey.
2. **The 250-block fragile drive.** The Pickup takes fire leaving the Rednecks' zone, and the router's way passes the police station by the spawn (a wanted level and a pull-out in sf7).

## SWAT VAN SWIPE! (wil_yh1)

What the script wants (`assets-src/missions/wil_m/wil_yh1.mis`):
- 1980 title, 1341 brief.
- `IS_CHARACTER_IN_MODEL (p1, SWATVAN)` gives 1342 and the arrow at Johnny Zoo's garage 43.5,249.5. Out of the van gives 1343.
- The van in `IS_CAR_IN_BLOCK (43.5,249.5, 3 x 1)` makes the game PARK it, then 1350, 1124 and $60,000.
- No timer.

The phone is on a roof at 97.5,245.5. The rooftop skill climbs to it from the street at 100.5,241.5 in one flight (3 game-s).

Developer aids:
- The red phone wants Yakuza respect 4. `skills/gang_respect.exe yaku` matched no gang (svs1, refused 1092), because gang 0 reads back with an unprintable name (MISSIONS-BATCH2 found the same in Residential). `missions/mb3_respect.c` is a copy of BATCH2's `b2_respect.c`, which accepts an index; it sets gang 0 (the Yakuza) to 100.
- `[devtools] force_wanted=N` brings the police. It is set off again the moment a SWAT van is listed.

| session | reached | ended because |
|---|---|---|
| svs1 | climb (3 game-s) | phone refused 1092: respect by name matched no gang |
| svs2 | **phone answered (1341)**; three stars for 7 game minutes | only cop cars came (the HUD showed the three heads); stopped by me |
| svs3 | phone; four stars; **a SWAT van came** (model 52, driver `swat`, id 179 at 89.5,241.5, later empty at 62,246.5 by the waiting road) | arrested by the troops walking to its door, then shot dead |
| svs4 | phone; four stars; the van at 89.5,241.5 and the aid off at once | arrested by the troops 9 s later |

Open: the van comes, but its troops arrest him on foot. Next: wait in a car with the doors to the road, take the van only once its troops are away from it (`view: peds` type `swat` near it), and drive off before the four stars decay.

## COP CAR SCRAP! (bil_ke2)

What the script wants (`assets-src/missions/bil_m/bil_ke2.mis`):
- 3841 title, 3480 brief.
- Three Cop Cars into the Krishna crane yard: `LOCATE_CHARACTER_BY_CAR (176.5,249.5, 7 x 7)` gives 3484.
- crane5 passes each car to crane6. Each Cop Car drop counts: 3485, 3486, then 3488 and 3100 with $40,000.

| session | reached | ended because |
|---|---|---|
| ccs1 | - | the scene warp was refused at 238.5,192.5 L1 (the renderer: no road or pavement within six blocks) |
| ccs2 | **phone answered (3480) by the roof climb on foot from the road at 222.5,189.5 (two flights, 15 game-s), then down again** | he came down into the Krishna temple's walled courtyard. steal_car's ring tour round him found no road and no car for 11 game minutes, with one star from `force_wanted` for 7 of them |
| ccs3 | phone answered; to the road at 220.5,187.5. No Cop Car taken from traffic in 240 s, so one star was called. **steal_car took a standing Cop Car** (carhp 32000) after 402 s (10 seen, 2 carriers, 1 jack), the aid off. The crane step began (crane5 hook 177.4,251.8 L2, lane mouth 179.0,250.0) | message 4207, then a 100-block jump to 120,121 on foot (arrested at the game's own one star on the way to the yard); the runner did not detect it and walked back; stopped by me |

Open: the arrest on the way to the yard. Next: `shake_police` before the crane leg (or a respray), and the runner's own jump detection, as in swat_van_swipe.py. Never reached: the crane pair taking a Cop Car.
