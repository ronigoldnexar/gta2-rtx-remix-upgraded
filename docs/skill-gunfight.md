# Skill: on-foot gunfight (`combat_on_foot`, Wave M, SKILL-GUNFIGHT)

`gamerun/skills/gunfight.py` (mirrored in `linux/docker/skills/`) fights armed characters on foot:
men who move, arrive in cars, carry guns and kill the player if he stands in the open. 22 phone jobs
and 3 bonus levels need it (`docs/missions-catalogue.md`). It was proven on **WHO'S MAD?** (`wil_lm1`,
Downtown Loonies, yellow phone). Runner: `gamerun/missions/whos_mad.py`. Keys script:
`gamerun/keys_whos_mad.sh`.

```python
import skills.gunfight as G
G.arm_job()                       # when the job starts: every message read from here on
r = G.gunfight(world, select=lambda p: ..., check=job_check, anchor=(x, y), secs=360)
# "done" | "no gun" | "timeout"; check() raises when the job ends; G.STATS has the numbers
```

## What it does

- **Hostiles** come from the `view: peds` line. A hostile is alive and picked by `select(p)`; with no
  selector, every marked ped counts. Men on foot and men in cars are both covered. Once a man is picked,
  he stays a hostile while alive, even after he leaves his car or the job's arrow goes.
- **Out of the car, gun in hand.** The skill steps away from the car it left, then takes the gun
  (`M.select_gun`), or the nearest pickup if there are no rounds.
- **Target.** The nearest man on foot on the player's level comes first. A man still in his car is shot
  through the car once within `engage`. If the car is still moving, the player stands and faces it
  instead of chasing it on foot.
- **Line of fire on the map** (`clear_shot`, `mission_lib.line_clear` at a bullet's width). The skill
  fires only when no building block or wall face is in the way. When the line is blocked, it walks to a
  nearby spot with a clear line (`firing_spot`), or round by the router in short legs.
- **No blind walking toward armed men.** Every approach in sight is a half-second slice, and the targets
  are read again after each one.
- **Distance.** The skill fires while walking at a man on foot down to `close` blocks. A car is fired at
  from `close_car` or further.
- **Hazards.**
  - Burning cars within `blast` blocks: step away first.
  - Health under `low` with a man close: back off, then turn and fire again.
  - Wanted level and an officer on foot within `cop_r` blocks: the officer is shot first, because an
    arrest ends the job (`police="shoot"|"avoid"|"ignore"`).
- **Losing sight.** A man seen and not yet down who has been out of sight for `hunt` seconds: go to the
  place he was last seen. A man who drops out of the peds list counts as down only if he dropped out
  within 6 blocks, because the list holds the nearest peds only.
- **Stall.** No damage for `stall` seconds: the next fire spot, a side step, or closer.
- **Outcome** (`job_state`). After `arm_job()`, every new line of the log is scanned for JOB COMPLETE,
  JOB FAILED and the arrest messages (`BUSTED!`, 1015 and the gangs' jail briefs, `ARREST_KEYS`).
  A jump of more than 15 blocks across the map also ends the fight (hospital or police station).
- **View.** With `GTA2_DIRECT_KEYS=1` every move and every shot is in the chase view.

## WHO'S MAD? (`wil_m/wil_lm1.mis`)

Title 1970. The player goes to 128.5,195.5 (`LOCATE_CHARACTER_ANY_MEANS`, 2 x 2). Brief 1464 then
announces three Zaibatsu hitmen, created inside VTYPEs at 149.5,192.5 / 168.5,212.5 / 126.5,213.5. Two
carry machine guns and one a pistol, and each has the objective `KILL_CHAR_ANY_MEANS` on the player.
An arrow is put on a hitman only while he is on screen. His car's top speed is 0 while he is on screen
and the player is on foot. Each kill gives 1466 and +$500. All three dead gives 1467 and 1124 JOB
COMPLETE (+$40,000). An arrest or a death ends the job silently (`CHECK_DEATHARREST_EXECUTED`).

### What the runner does

1. **Respect (developer aid, reported).** The yellow phone wants Loonies respect >= 2 bars, and a fresh
   game has 0. `gamerun/skills/gang_respect.exe` sets it to 60 (3 bars) in the game's gang table, and
   the HUD bar shows it (`out/gf_probe1/m_respect.png`).
   - The table is at `[0x5EB898]`: 10 gangs of 0x144 bytes. The name starts at +2. The player's
     respect is a signed byte at +0x11C, and a bar is 20.
   - These were read from the HUD's respect-bar function `FUN_004C74F0` and its getter `0x45DAC0`.
   - The tool is built from `gang_respect.c` with `i686-w64-mingw32-gcc -O2 -s -o gang_respect.exe
     gang_respect.c` and run by `wine` inside the container (Read/WriteProcessMemory).
   - Nothing else in the job is helped.
2. **A car to the Loonies' yard; the machine gun at 41.5,48.5.** The generator beside the phone
   (11.5,47.5) is one block from the DESTROY J-LAB! phone (11.5,46.5). In gf_wm1 that phone answered
   (brief 1500), and WHO'S MAD? then refused with 1103.
3. **The phone from the west.** The walker goes to (9.4,46.6), then nudges onto 10.35,46.5. The J-Lab
   phone is one block east.
4. **A second machine gun at 84.5,184.5** on the way (600-900 rounds at the fight). The car is parked
   at 123.5,190.5, and the player walks the last blocks into the box.
5. **The fight on the open plaza south of the yard** (anchor 125.5,204.5; rows 202-207, columns
   115-139). The meeting box is inside a walled yard (x 126-132, y 193-200), open only to the east and
   south.

### Sessions

All sessions ran on fresh games with `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1`, `FPS=0` and
`GTA2DX9_STATE_EVERY=3`, on the private stage `stage_gunfight` (a hard-linked copy of the shared stage
with no change). Several sessions were paused by the CPU governor for 5-20 wall-minutes; that was not
counted as a failure.

| session | outcome | what happened (and the change it led to) |
|---|---|---|
| gf_probe1 | tool check | Respect read 0/0/0, Loonies set to 60, read back 60; the HUD bar shows 3 segments. |
| gf_wm1 | refused (1103) | Picking up the gun at 11.5,47.5 answered the J-Lab phone. Changed: the gun at 41.5,48.5, and the phone approached from the west. |
| gf_wm2 | stopped | Phone, box and 1464 all worked. The hitmen showed as `gang/zaibatsu` in model-70 cars with no arrow and circled the block; the selector (`crim` or marked) matched none of them in 360 s. Changed: the selector takes Zaibatsu in VTYPEs; a moving car is faced, not chased. |
| gf_wm3 | arrested | Two hitmen down. The player walked to 2.5 blocks of a VTYPE and took a burst (100 -> 10). Shooting had raised wanted to 1, and a cop jailed him (7075, with no JOB FAILED). Changed: arrest messages and jumps across the map end the fight, the officer is shot first, and cars are fired at from further off. |
| gf_wm4 | dead (7072) | A 20-block `walk3` leg toward a far hitman ran blind for 4 s. It ended 0.3 blocks from a hitman who had just left his car, and he shot the player point-blank. Changed: every approach in sight is half-second slices. |
| gf_wm5 | dead (7071) | 37 s of fire, 270 rounds, into the yard's west wall at a hitman 1.5 blocks away on the other side. The player ran out of ammo, left for a gun, and died. Changed: `clear_shot` / `firing_spot`, and the fight is held on the open plaza. |
| gf_wm6 | stopped (2 of 3) | Two hitmen down in 7 s at health 100. The third left his car at the yard's east gate before the fight loop began and matched nothing on foot. Changed: the runner remembers the hitmen; the skill hunts a man's last place and counts "gone" as down only within 6 blocks. |
| **gf_wm7** | **JOB COMPLETE** (1124, +$40,000, multiplier 2) | All three down by game-second 640 (17 s of fight, 9 s of fire). Health stayed at 100. Five steps away from burning cars. The runner's newest-line check missed the 1.7 s of 1124 (then "svdone") and logged "running"; the game's log and the money show the completion. Frame: `out/gf_wm7/shot_475.png` (JOB COMPLETE! in the chase view). Changed: `arm_job()` / sticky message scan. |
| **gf_wm8** | **JOB COMPLETE** (589 s from the level, +$40,000) | All three down within 8 game-seconds of the fight starting (3.4 s of fire). Health stayed at 100. The runner logged `complete`. Frame: `out/gf_wm8/m_wm_end.png` (JOB COMPLETE! in the chase view, a hitman down beside the VTYPEs). |
| gf_wm9 | dead (7073) | The hitmen arrived early. The runner's separate walk from the box to the plaza, with the trigger off and before the fight loop began, cost 60 health (100 -> 40). A `walk3` leg toward a hitman's last place then kept walking through the death (walk3's budget is checked between legs only). Changed: the fight loop starts at brief 1464 and moves him to the plaza itself; every move in the skill is a bounded `route_step` (at most 3 blocks / 2 s). |
| **gf_wm10** | **JOB COMPLETE** (1124, money 1,723 -> 41,729, multiplier 2) | First session with the gf_wm9 changes. The fight started at brief 1464 in the yard; the skill went round its wall twice (`walls` 2) and shot one hitman, and the other two died when their VTYPE blew up beside them. The blast took health to 10, a close call: `blast` 3.2 is not enough clearance for a car that burns out where the player stands. The skill counted one kill, but the game counted three. Frame: `out/gf_wm10/m_wm_end.png` (JOB COMPLETE!, chase view, the three hitmen down beside the VTYPEs). |

**Acceptance: gf_wm7, gf_wm8 and gf_wm9 were three consecutive sessions on the same fight logic.
2 of 3 reached JOB COMPLETE in the chase view.** The only code change between gf_wm7 and gf_wm8 was
the message scan, which affects reporting only. With the gf_wm9 fix, gf_wm8-10 were also 2 of 3, and
gf_wm7-10 were 3 of 4.

No developer warp was used in gf_wm7-10. The shared walker warps itself when pinned
(`WARP_OK`); gf_wm4 shows one, near the phone yard.

Frames are in the chase view and not in git:
- `out/gf_wm3/m_gf_wm_first_down.png`: the first hitman down ("Nicely done, Jumbo!").
- `out/gf_wm8/m_gf_wm_engage.png`
- `out/gf_wm7/shot_475.png` and `out/gf_wm8/m_wm_end.png`: JOB COMPLETE!

## Using it for the other 21 jobs

- **Selector.** Give `select` the job's men by gang and by what the script creates. The peds line
  shows a man as `gang/<gang>` once `ADD_CHAR_TO_GANG` has run, whatever `CREATE_CHAR` type he was
  created with. Marked peds alone are not enough: the arrows come only on screen.
- **Anchor.** Put the `anchor` where the job's men are sent, on open ground. Check it with
  `clear_shot` from the map before a run.
- **Ammunition.** Two machine-gun generators gave 600-900 rounds; one fight used 70-270.
- **Police** are the main risk after the hitmen. With `police="shoot"`, an officer who closes in is
  shot; that raises the wanted level, and the job's `CLEAR_WANTED_LEVEL` at the end clears it.
