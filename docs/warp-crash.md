# Warp crash: `gta2.exe+0x35FDF reading 0x80` (FIX-CRASH-WARP)

Seen in the city sweep (3 runs, `docs/city-sweep.md`) and 5090 release QA r80 (soakB, 250th warp cycle).

## What happens

`FUN_00435FA0` (gta2.exe+0x35FA0, `__thiscall` on the player's ped, only caller `0x4A7B4F`) is the player's respawn,
run when the "wasted" countdown (player object `+0x28` set, `+0x2C` = 70 ticks) reaches 0. It saves
`edi = [ped+0x168]` (the ped's physics object), resets the ped (`FUN_00435720`), puts edi back and at `0x435FDF`
(`mov eax,[edi+0x80]`) reads the sprite object. It never tests edi.

The physics object is gone because the game removed the player's dead ped during the countdown:

1. `FUN_004454E0` (per-ped update) for a ped in state 9 (dead): if `[ped+0x20E] > 200`, `[+0x240] != 0x17`,
   `[+0x238] != 5` it calls `FUN_0043E650` (kill-and-remove) at `0x4457C6`: corpse timeout.
2. `FUN_0043E650` clears the alive bit (`[+0x21C]` bit 0), sets `[+0x234] = 2`, state 9 / sub 0xF.
3. Two or three ticks later the update returns 1 and the ped-list loop `FUN_00445960` calls `FUN_00435F70`
   (physics back to the pool at `0x66A3B4`, `[ped+0x168] = 0`).
4. The countdown ends: `FUN_00435FA0` reads `[0+0x80]`.

The player's `[+0x238]` is 2 and `[+0x240]` 0 (trace), so the corpse-timeout exemptions do not cover him.
`[ped+0x20E]` is a state timer the AI routines count up and is NOT reset at death. A player who stood about for
130+ ticks before dying starts the countdown at 130+ and crosses 200 before the 70 ticks are up. After a devtools
warp he stands in state 2 for seconds (r80: 3.7 s from warp to fault), so warp-then-die hits it; vanilla play can too
(die after idling ~2 s), it is just rare there because walking resets the timer.

## Evidence

Test knob `GTA2DX9_TEST_DEATH_AFTER_WARP_MS=3000` kills the player through the death handler `FUN_004411B0`
(cause 1, car hit) 3 s after each warp and keeps lives up. `GTA2DX9_PED_TRACE=1` logs kill-and-remove / physics
release on the player's ped with callers. Trace (guard off): `kill-and-remove ... +0x20E 201 +0x238 2 ... callers
gta2.exe+0x457CB < 0x4598E < 0x45A72`, 100 ms later `physics release ... callers 0x45999`, then
`FAULT ... gta2.exe+0x35FDF reading 00000080`. Timer at death was 89 and 144 in the two deaths of one run.

## Fixes (`dll/src/exe_guards.cpp`)

- Source: while the wasted countdown runs and the player's ped is dead, `[ped+0x20E]` is held at 120
  (`GTA2DX9_CORPSE_CLAMP=0` disables). The ped is never removed, physics stays.
- Defence in depth (`GTA2DX9_RESPAWN_GUARD=0` disables): at `0x435FA0` entry a ped with null physics gets one from the
  game's allocator `FUN_004360C0` (x, y, z from `+0x1AC/+0x1B0/+0x1B4`); at `0x435FDF` a still-null edi skips the position
  copy (`0x435FDF-0x43600A`, then `push 0x64; mov ecx,esi; jmp 0x436010`).

## Other paths

Only the Wasted path calls `FUN_00435FA0`. Any player death (traffic, fire, explosion, mission) with a timer above
~130 reached it, not only devtools. Busted (`0x4A7DEE`) kills the body clone `[player+0x2C8]`, not the player's ped;
mission teleports do not touch the physics object.

## Numbers

Loop: F10 scene warp, F9 door warp, kill 3000 ms later (test knob), `gamerun/wf_warploop.py` (`WF_MODE=walk` on foot, `board`
= the soak's Return/drive cycle), one Tokyo container per row, plain renderer.

| run | corpse clamp | respawn guard | mode | deaths | FAULT |
|---|---|---|---|---|---|
| wf_c / wf_d (no clamp, no guard) | - | off | board / walk | 5 and 3 cycles | `0x35FDF reading 0x80` both runs, first or second death |
| wf_e | - | off | walk | 2 | `0x35FDF reading 0x80` |
| wf_h | off | off | board | 1 | `0x35FDF reading 0x80` |
| wf_g | on | off | walk | 60 | 0 (timer held 20 times, logged) |
| wf_f | - | on | walk | 4 | guard fired once and the respawn went on; then `0x3ED37 reading 0x64` at the next death |
| wf_i | on | on | board | 2 | guard fired twice; `0x3ED37 reading 0x64` |

Clamp alone fixes the repro (60 of 60). Open: in `board` mode the test kills a ped that is boarding a car (physics already
null by design while seated); the guard then allocates at 0,0,0 and a later death faults at `0x3ED37` (a second
`FUN_0043E650` on the respawned player, whose `+0x238/+0x240` the reset leaves at 3, so he is an ordinary ped for the
corpse rules). Not reached without the test knob killing a boarding ped; not fixed here.
The glass gate (`CarGlassSplitPending`, item 2 of the r80 list) cannot run in the plain renderer: 5090 verification pending
(look for `cg.splithere` staying flat and no `render thread` split lines over 8 ms).
