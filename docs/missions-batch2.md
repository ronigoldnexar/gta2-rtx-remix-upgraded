# MISSIONS-BATCH2 (Wave M, 9 Nov 2026): GANG CAR BANG, TAXI DRIVERS MUST DIE, COSSACK CONVERSION

Claimed in `/mnt/gta2/agents/MISSIONS-claims.txt` at 07:07 (BATCH1 had ARMORED CAR CLASH; BATCH3
released GANG CAR BANG to this batch). Runners in `linux/docker/missions/` (mirrored from
`gamerun/missions/`): `b2_gang_car_bang.py`, `b2_taxi_drivers.py`, `b2_cossack.py`, shared helpers
`b2_common.py`, keys scripts `keys_b2_*.sh`, and `b2_respect.c` (gang_respect.c taking a gang index).

**Result: no JOB COMPLETE on any of the three.** GANG CAR BANG reached its first stage's pass
(five Meteors, message 2163) once in 25 sessions; TAXI DRIVERS jacked the first taxi once in two
sessions; COSSACK CONVERSION was never run (the one-run-per-agent rule and 25-40 minute sessions
left no slot for it). What follows is what each session taught, so the next agent starts from it.

## GANG CAR BANG! (`ste_rh1`, Residential, Rednecks' red phone 4.5,5.5)

Script (`assets-src/missions/ste_m/ste_rh1.mis`): 10 rockets (`ammo` 100 in the mission line), a
Redneck with a machine gun and his group of six made the player's followers; wreck 5 SRS Meteors
(model 48) inside the Scientists' zone (2161 in, 2162 out, 2163 passed), then 5 Z-Types (model 70)
inside the Zaibatsu zone (2165/2166/2167), $70,000 and 2999. No clock. Death or arrest shows the
Rednecks' brief 6150+n (`DECLARE_GANG_ONE_DEATH_BASE_BRIEF`) and ends the job.

Run: `SWAP_LEVEL=ste GTA2_SPEED=1 GTA2_DIRECT_KEYS=1 FPS=0 STAGE=<private stage>
INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <name> 3600
missions/keys_b2_gang_car_bang.sh -e DISTRICT=ste -e WARP_OK=0 -e GTA2DX9_SCENE_NO_CAR=1
-e GTA2DX9_STATE_EVERY=3`. Developer aids, marked in `marks.txt`: Rednecks respect 80 (gang index 0:
its name reads back unprintable, so `gang_respect.exe redn` matched nothing); a scene warp to the
road 17 blocks south of the phone (`B2_WARP_PHONE=1`).

What it takes, in the order it was learnt:

| sessions | what happened | fix in the runner |
|---|---|---|
| gcb1 | respect not set (`redn` matched no gang) | `b2_respect.exe 0 80` |
| gcb2-4 | the phone stands on a field reached only by a one-block wooden jetty (column 6, rows 7-16) over water; the shared walker's unstick turn and later a held walk drifted off it: drowned three times | `careful_walk`: pure-pursuit steering on a point 0.6 blocks ahead on the jetty's centre line, short pulses, stop and re-face when 0.2 off the line |
| gcb5-6 | three borrowed cars burned on the 250-block drive to the SRS zone; one exploded beside him; a kerb wait of 4 minutes | the travel on foot (`B2_GCB_TRAVEL=walk`): the escort keeps up and nothing burns |
| gcb7, gcb12 | four rockets each at standing Meteors from 9-11 and 5 blocks, no damage | the player line is logged every 15 frames by default: facing and position half a second stale. `GTA2DX9_STATE_EVERY=3` (lateral error on the jetty 0.45 -> 0.1, rockets on target) |
| gcb8, gcb10 | the escort spawns at 11.5,2.5 and crowds the new leader: pushed off the jetty on the way back | straight back over the jetty the moment the title shows, still in the classic view (no 7 s of view changes) |
| gcb9 | the governor paused the container right after the warp key; the warp was read against a stale position | re-read the position after a settle; refuse to walk the jetty unless at the road |
| gcb12 | a rocket fired down an alley hit the wall in front of him | `gunfight.clear_shot` before the trigger |
| gcb13 | arrested beside a cop car after the second Meteor (`6156`) | `lie_low`: away from the police on foot until the wanted level is gone; no shot with police within 20 blocks |
| gcb14 | the router crossed the raised station plaza (116-125 x 120-137); the escort crowded him onto the tracks | those cells in `M.BLOCKED` for this job |
| **gcb15** | **stage 1 passed** (2163, 4 Meteors by rocket + 1 credited, 5 rockets used); on the way into Zaibatsu Village a patrol leg walked off the bridge pavement at 142.6,25.6 into the water | stage 2 hunts on the zone's ground roads (rows 62-77, x 160-250); the bridge and deck edge (134-159 x 19-31) blocked |
| gcb16 | 9 minutes circling one Meteor without a shot | a target with no shot in 40 s is skipped for 90 s |
| gcb17-18 | `gta2.exe` crashed (`C0000005 at gta2.exe+0x25486, reading 0000004C`) on the stage restaged at 12:45 (reported on #9) | private stage `stage_b2` (the 02:30 DLL); frozen-game watchdog (no rendered frames for 60 s ends the run) |
| gcb17 | killed by his own rocket: an escort stood in the line of fire | no shot while a ped stands within 0.8 of the line |
| gcb19 | a miss at a moving Meteor raised the wanted level; a cop on foot shot him to 10 | rockets only at targets slower than 1 block/s; lie low when wanted with police near |
| gcb20-21 | turning on the spot and requiring a standing target with the escort out of line: no shot in 40 s at any target | back to the gcb15 way (fire while walking at it) with the line-of-fire and police checks |
| gcb22, gcb24 | wanted 1 that never decayed (17 minutes) with a cop car tailing at 3-10 blocks; on foot it cannot be shaken; died | open: a respray needs a car; killing the cop raises the level |
| gcb23 | a rocket at a burning Meteor (1739 hp) from 6 blocks: its blast killed him | burning cars (fire, or hp under 16000) are no targets and are kept 7 blocks off |

Frames: `out/b2_gcb15/` (the Meteor hunt in the chase view, the counter going 5 -> 0, `m_gcb_meteors_*`),
`out/b2_gcb12/shot_665.png` (a rocket fired 100 degrees off on the stale facing),
`out/b2_gcb10/shot_150.png`/`155` (the escort crowding him on the jetty), `out/b2_gcb17/shot_1100.png`
and `out/b2_gcb18/shot_610.png` (the Wine crash dialog).

Next: the police after a rocket hit is now the main loss. Ideas not tried: a car for the Zaibatsu
stage and the respray at the nearest shop (`skills/shake_police.respray`), or a stand-off spot out of
the police routes before each shot; the 5-for-5 rocket budget of stage 2 needs every shot to hit
(the escort's own kills seem to be credited: gcb13's counter fell 2 for 1 rocket).

## TAXI DRIVERS MUST DIE! (`wil_lh1`, Downtown, Loonies' red phone 58.5,20.5)

Script: three taxis in turn (132.5,55.5 with an aggressive criminal driver; 243.5,181.5 with a driver
and one gunman; 162.5,149.5 with a driver and four gunmen); in the taxi the arrow moves to the driver,
who must die (with his group for taxis 2-3); then the South Docks crusher (crane3, the right crusher
block 244.5,243.5); 1124 after the third. `b2_taxi_drivers.py` uses `steal_car` restricted to the
marked taxi, `crusher_crane.crush(world, "wil", "crane3")` and, for the crew, first running them down
from the taxi (`run_down`), then the gunfight skill on foot.

| session | outcome |
|---|---|
| tx1 | phone, machine gun from the Loonies' yard, the first taxi jacked after 13 minutes of chase (1748); stepped out beside two officers (wanted 1 for the jacking) and died in 1.5 s. Fix: stay in the taxi, evade the police, run the driver down |
| tx2 | 15 minutes behind the aggressive taxi without a jack (`steal_car` lost it at every turn); the carrier burned once |

Untested: `run_down`, the crusher step, taxis 2 and 3.

## COSSACK CONVERSION! (`bil_km1`, Industrial, Krishna yellow phone 233.5,132.5)

`b2_cossack.py` is written against the script (box truck in the Lubyanka yard at 165,43.5 guarded by
six pistols that raise an alarm; horn in the 2 x 2 box at 8.5,83.5 for four groups that board one after
another; the Conversion House box 239,112 where the game parks the truck itself; 3100) with
`horn_pickup.pickup` (horn brief 3245 added, boarding wait 420 s) and `horn_pickup.drop_off`. **Never
run.**

## Host notes

- `cpu_governor.sh` still has the 8-CPU thresholds (hold at load 22, release at 15) and `runq.sh` the
  default `GTA2_LOAD_MAX=12`: on the 96-CPU host the queue stood still for 20-40 minutes at a time
  with a dozen tickets waiting, then started them all at once (load 86), and the governor paused the
  newest containers mid-run (gcb9's stale warp).
- A `docker stop` leaves no `gta2dx9.log` in the run folder: let a run end by itself when its log matters.
