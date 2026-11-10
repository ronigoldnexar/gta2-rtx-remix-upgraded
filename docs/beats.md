# Framed beats: WASTED, BUSTED, JOB COMPLETE (QB-17/18)

Quality-bar rows 17 (death and respawn) and 18 (cinematics on JOB COMPLETE / WASTED /
BUSTED). Street views only (third and first person); the classic view keeps the game's own
message over its own camera, unchanged.

Code: `dll/src/beats.{h,cpp}` (detection, timing, sting hook, devtools trigger), the camera
in `dll/src/view_modes.cpp` (`namespace beatcam`, applied after the chase solver and after
the "lost player" solver), the screen treatment in `dll/src/hud3d.cpp` (`DrawBeat`), one
line in `dll/src/world_view.cpp` (first person draws the player's own body during a beat).
Settings: `[beats]` in `package/gta2dx9.ini`.

## How a beat is recognised

All three are the game's **big message**: the HUD object at `[0x672F40]+0x2854`, drawn by
HUD part 15 (`FUN_004C8A40`). Its setter `FUN_004C6060` (`__thiscall`, text and priority)
copies the UTF-16 text to `+2` and sets the countdown byte at `+0` to 90; it counts down
to 0 while the message shows.

- Death and arrest: `FUN_004A4E10` picks the key from the player's death kind (`+0x44`):
  0/1 `wasted` ("WASTED!"), 2 `fried` ("TOASTED!"), 3 `nicked` ("BUSTED!"), 4 `shocked`
  ("SHOCKING!"), and passes it through the text lookup `FUN_004C23A0` to the setter
  (`0x4A79F8`, `0x4A7BFA`).
- JOB COMPLETE: a script message (`0x479478`, the key in the `0x5E9808` buffer): `1124`
  Downtown, `3100` Industrial, `2999` Residential ("Mission Complete!").

`BeatsUpdate` (once a frame, from the camera solver) reads the countdown and the text. A
beat starts when a fresh message appears (countdown >= 75, so a view switch in the middle of
one does not start a late beat) whose letters equal one of those keys' texts in the
player's own `data\e.gxt` (any language). Other big messages (KILL FRENZY!, GAME OVER!,
JOB FAILED!) are logged and left alone.

## What a beat does

| | camera | screen | ends |
|---|---|---|---|
| WASTED | starts where the chase camera is, high over the body (r 1.7 -> 1.05 blocks, h 1.7 -> 0.75), craning down and in while it turns 10 deg/s round him, looking at the body | letterbox bars to 2.39:1, a drained dark-red wash and darkened edges, the game's words ("WASTED!") in the classic big-message colours (yellow-to-orange fill, indigo outline, FIX-HUD-3) in the HUD's heavy face in the upper third, a red rule drawn out under it | from 1.6 s (game time) fades to black, black by 2.1 s: the game moves him about 70 frames after its message (measured on real arrests, run `qb17_beats6`). When he has been found more than 6 blocks away for 10 frames running (the hospital) it fades in over 0.7 s on the chase camera |
| BUSTED | eye level, close (r 1.5 -> 1.0, h 0.65 -> 0.5), turning the other way: him and the officers on him | the same bars, a cold blue cast, the edges lit red/blue in turn (beacons), "BUSTED!" in the same classic colours, a blue rule | the same, at the police station |
| JOB COMPLETE | swings round in front of him, low, looking a little up at him (r 1.5 -> 0.95, h 0.36), 6 deg/s | bars, a light warm cast, "JOB COMPLETE!" in the same classic colours; the modern HUD steps two thirds aside (the money still ticks) | after 4.2 s it swings back behind him and hands over to the chase camera |

The beat is anchored where he was on the frame *before* the message: on the message's own
frame the locator can report the new body the game has already placed at the hospital or
the station (run `qb17_beats3`: "WASTED start at 50.50,2.00,77.50", the body at 134,153),
and the chase camera may already have jumped there; if the chase camera is more than 6
blocks from him the beat cuts to its shot instead of sweeping across the city. The anchor's
height is the floor the solver measured under him (a stair or a raised plaza stands above
the game's own z), and it follows the body while it stays within 2.5 blocks.

The camera is blended in polar terms about the spot where he was when the beat began: the
angle, radius and height go from the chase camera's to the beat's, so the move swings round
him and never passes through him, and at share 0 it is exactly the chase camera. The orbit
starts at the clearest of 24 angles near the preferred one, and each frame the line from
him to the eye is checked against solid blocks and against flat panels (railings, fences,
signs - see-through for the chase camera, but a shot through one is a shot of the
railing); the radius pulls in to the free part (fast in, slow out) and lifts a little. In a
car the shot is twice as far and higher.

While a beat is up the game's own part-15 draw (its big text) is dropped; the title is the
game's own words, re-set.

## Music sting hook

At each beat's start `Sting()` runs once: a program hook set with `BeatsSetStingHook`
(`dll/src/beats.h`) if there is one, otherwise `[beats] sting_wasted` / `sting_busted` /
`sting_complete` name a `.wav` played asynchronously (`PlaySound`). Empty by default: no
audio asset is shipped (the log says `beat: sting <kind>: hook point (...)`).

## Not done

- **Slow motion.** GTA2 advances one simulation step per rendered frame
  (`dll/src/frame_limiter.h`), so slowing the game means dropping the frame rate, which
  makes the beat choppy. Left out; the camera's own push-in carries the beat.
- **Desaturation** is a wash, not a shader: the modern HUD draws with ImGui over the
  finished frame. A real grade belongs in `src/post_fx.cpp`.
- The respawn is still the game's cut, only hidden under the fade; there is no walk-out.

## Checking it

`[devtools] force_big_message=<key>` puts a message up through the game's own calls
(lookup `FUN_004C23A0`, setter `FUN_004C6060`), once per change: `1124` checks JOB
COMPLETE without a mission. `gamerun/qb17_beats.py` (keys `keys_qb17_beats.sh`) does that,
then a real arrest and a real death (armed at the plaza with the police held at 4 stars),
then JOB COMPLETE again in the open. Log lines: `beat: <KIND> start "<text>" at x,y,z`,
`beat cam: ... orbit starts at <deg>, <n>% clear`, `beat cam: <KIND> t=.. share .. eye ..`
twice a second, `beat: <KIND>: respawned after <s> (moved <n> blocks)`, `beat: <KIND> end`.
