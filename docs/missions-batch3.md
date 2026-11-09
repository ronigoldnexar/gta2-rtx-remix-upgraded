# Missions batch 3 (Wave M, MISSIONS-BATCH3, 9 Nov 2026)

Three jobs nobody had started, each played by the Wave M skill modules. The runners live in
`gamerun/missions/` (mirrored in `linux/docker/missions/`). The claims are in
`/mnt/gta2/agents/MISSIONS-CLAIMS.txt`.

| job | runner | skills | state |
|---|---|---|---|
| `ste_ze1` SCIENCE FRICTION! | `science_friction.py`, `keys_science_friction.sh` | rooftop_access (walk), car_bomb, steal_car (carriers), mission_lib.run_over | see Sessions |
| `wil_yh1` SWAT VAN SWIPE! | `swat_van_swipe.py`, `keys_swat_van_swipe.sh` | rooftop_access, steal_car, deliver_intact | written, not run yet |
| `bil_ke2` COP CAR SCRAP! | `cop_car_scrap.py`, `keys_cop_car_scrap.sh` | rooftop_access, steal_car, crusher_crane (crane5 to crane6 pair) | written, not run yet |

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
