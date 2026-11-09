# RTX Remix in the 3D views against the classic view (REMIX-3D-PARITY, 9 Nov 2026)

Upstream (gebdag/gta2-rtx-remix, our base) makes the classic top-down view a path-traced scene:
the map rebuilt as real 3D geometry, the game's lamps and events as Remix lights, emissive maps,
animated water, Remix Plus's sun and sky from the game clock, 16:9. This fork adds third and first
person. This pass asks, feature by feature, whether the 3D views get the same Remix treatment,
closes what it can in the 3D path only (the classic view's draws and light set are unchanged), and
checks continuity: the same moment path traced in every view, and no pop or reload at the V press.

Code base: `camera-modes` 16fcaf8 (the merge of `night-skills-2026-11-09`), cherry-picked onto
`night-skills-2026-11-09` for the push. Runs: `out/r3d_2` and `out/r3d_1` (after), `out/r3d_0` (before,
the old far-lamp switch), all on GPU 1 (REMIX-BEV's per-GPU-lock copy of `gamerun/remix_l4.sh`;
`REMIX_GPU=1 gamerun/remix_l4.sh` is the committed equivalent, holding the one global GPU lock), the play preset
(`rtx_play.conf.extra`) and the gta2hd layer (`MODS_HD=1`); local, not in git (game art).

## 1. Feature audit: what the classic view gets under Remix, and the 3D views

Read from the code (file:function) and checked in the frames of section 3.

| Remix feature | Classic view (upstream path) | Third / first person | Verdict |
|---|---|---|---|
| World geometry and tile materials | the GMP mesh, one batch per tile texture; the gta2hd layer keyed by the HD tiles' top-mip hash | the same mesh, the same textures, so the same hashes and materials | same |
| Street-view shading of the plain renderer (D3D fog, a D3D directional "sun", water noise stages 1-3, lit-window glow stage) | none | **off under Remix**: `WorldView::DrawSkyAndShading` passes an empty `WorldShading` when `RemixApiHasAtmosphere()`, so `Renderer::DrawWorld` sets no fog, no D3D light and no extra texture stages; the water shader (`WaterFx::Init`), the post stack and the weather pass do not start on a Remix device | same draws as the classic view (no extra D3D light for Remix to translate, no stage that would change a material) |
| Sky, sun, time of day | Remix Plus atmosphere, sun from the `[timeofday]` clock (`time_of_day.cpp`) | the same atmosphere and clock; the renderer's own dome is left out under Remix | same; only the 3D views see the sky |
| Water (tiles 608-619) | world mesh tiles with the layer's material | the same tiles | same |
| Emissive maps | gta2hd: 64 curated sign/neon tiles. Upstream `gta2rtx`: 328 emissives, of which 23 are 64 px tile uploads (matched only with `NO_HD=1`, in either view: 64 px tile hashes computed from the style files, `/tmp/r3d/up_tile_hits.txt`) and 305 are other textures | the same tile emissives; sprites still drawn in 3D (signs, objects without a model) keep their texture and hash | same for tiles; sprites replaced by models (cars, people, mapped objects) use the model's material instead |
| The game's lamps (LGHT, neon, traffic lights) | the lamps the game lists inside its top-down window | the same, **plus the map's steady lamps within 36 tiles of the eye** (up to 120, `LightsSubmitMapLampsNear`) because the ground camera sees past that window | 3D has more, by design; the switch between the two sets was a pop, **fixed** (section 2) |
| Synthetic lights (headlights, brake, sirens, muzzle flashes, fire, explosions) | from the game's vehicle and particle lists | the same lists; muzzle flashes lifted 0.25 to chest height with upright figures; siren beacons from the 3D body's beacons | same set; positions follow the 3D bodies |
| Car lamps | the renderer's own lamp quads on the sprite body with an emissive Remix material (`AddCarLamps`) | the 3D model's lamp emission (REMIX-3 car layer); the lamp quads stay on the hidden sprite plane | different source, see frames |
| Car paint | the game's sprite (and upstream's HD car maps) | `_paint` mesh x texture factor (stage 1, `MODULATE2X`); Remix's `enableMultiStageTextureFactorBlending` takes one extra stage | see frames (BEV-PARITY saw wrong paint on some cars with the plain renderer) |
| Post (bloom, tone mapping, auto exposure) | `rtx.conf` | the same options; the auto exposure meters a frame with sky in it | inherent: exposure adapts over `darkAdaptTau`/`lightAdaptTau` after a switch |
| Motion blur | off | `[camera] MotionBlur`: 0 off (shipped), 1 on in the 3D views only (`ViewModePushRemixOptions`) | off by default in both |
| The player's own shadow and reflection | the sprite casts a shadow | third person: the avatar does. First person on foot: the body is hidden (`fpHideOwnBody`), so no shadow or reflection | **open** (section 4) |

## 2. Fixed: the far lamps switched on and off in one frame

`WorldView::RenderFrame` submitted the far lamps only while `g_viewActive && CurrentViewMode() !=
Classic`. Pressing V into a 3D view added up to 120 lights in the first frame, while the camera was
still at the classic height; pressing V back to classic removed them in the frame of the key press,
before the 1.4 s camera move back up had started. At night that is a visible change of lighting on
the street at the key press, in both directions.

Now the far lamps follow the transition's blend (`skyBlend_`, the weight the sky and fog of the plain
renderer use: smoothstep 0 -> 1 as the eye comes down, 1 -> 0 as it goes back up), as an intensity
weight in `LightsSubmitMapLampsNear(eye, radius, cap, weight)`. They fade in over the move into a 3D
view and fade out over the move back. `skyBlend_` is 0 whenever the classic view is settled, so the
classic view's light set is what it was. `GTA2DX9_FAR_LAMP_FADE=0` puts back the old switch (for a
before/after run). `GTA2DX9_LOG_LIGHTS_EVERY=N` writes the light-set line every N frames (default
256, as before) with the far-lamp count and weight, for the check below.

## 3. Verification

Runs on GPU 1, Downtown, 1280x720, the play preset, gta2hd layer, 0 `FAULT` in all three logs:

| run | build | what it shows |
|---|---|---|
| `out/r3d_2` | after (fade) | the kept evidence: frames of the same moment in every view (14:00 and 22:30, the spawn and the plaza), the move both ways, the log checks. 10-30 fps |
| `out/r3d_0` | before (`GTA2DX9_FAR_LAMP_FADE=0`, 22:30 only) | the log checks for the old switch; its recording ran out (700 s) before the take, so no frames |
| `out/r3d_1` | after (fade) | the first take, with wall-clock waits: the session ran 2-11 fps under host load, so its "third"/"first" frames are mid-move (it is what made the take count rendered frames); log checks valid |

Sheets (local, game art): `out/r3d_2/r3d/side_by_side.png` (per moment: classic | third | first |
classic again), `out/r3d_2/r3d/switch_<moment>.png` (classic -> third at V +5, 11, 18, 27, 42 frames,
and first -> classic the same), the frames in `out/r3d_2/r3d/frames/`, reports
`out/<run>/r3d/report.md` (and `/tmp/r3d/r3d_0/` for the before run).

**Far lamps across the V press** (the far lamps' summed weight, count x fade, in the last logged frame
before V and the first after it; logged every 2 frames):

| switch | before (`r3d_0`) | after (`r3d_2`) |
|---|---|---|
| classic -> third, night, spawn | 0 -> 111 | 0 -> 1.1, then the fade over 20 logged frames |
| classic -> third, night, plaza | 0 -> 75 | 0 -> 0.0, fade over 19 |
| first -> classic, night, spawn | 120 -> 0 | 120 -> 120, fade over 19 |
| first -> classic, night, plaza | 84 -> 0 | 84 -> 84, fade over 19 |

The day switches in `r3d_2` (and all 12 in `r3d_1`) fade the same way (by day the lamps are gated off
by the daylight test either way). Remix's own light count still steps (the lamps are submitted from
the first frame at weight ~0, and the runtime drops those under `minIntensity`); what lights the scene
ramps.

**Objects across the V press** (BEV-PARITY's check, on the take's events): no logged car, ped or the
player stepped more than 0.6 blocks a frame within 3 s of any of the 12 switches in `r3d_2` (largest
0.4, a car at speed; 19-50 objects tracked) or of the 12 in `r3d_1` (largest 0.135). The live ped count
around a switch moves with the 2.6x spawn window of the 3D views (BEV-PARITY: by design).

**The same moment, path traced** (`side_by_side.png`, `r3d_2`): the night spawn is the clearest: the
JESUS SAVES neon throws the same red light on the paving in classic, third and first person and classic
again, the lamp posts are lit in all of them, the sky is the same Remix night sky. The day plaza: the
same sun direction and shadow side in third person, first person and classic again; the parked van's
tail lamps glow in third person by day and night. The camera move (`switch_*.png`) is continuous in
both directions: no black frame and no blank frame in any switch window of `r3d_2` after the shaders
had compiled (the brightness steps in the switch windows, up to 53 of 255 in one frame, are the
composition changing: the neon sign entering the frame, not a lighting change).

**Not a clean pass:**
- The first moment of `r3d_2` (day, spawn) is black in every view: Remix was still compiling shaders
  ("Compiling shaders (N remaining)") after the 120 s warm-up. A start-up cost, not a view one; the take
  needs a longer `R3_WARM` or a warm shader cache.
- Classic again against classic before: the one moment where the game's camera was the same before and
  after (day, spawn) matches (4.0 % of pixels over 24, all at moving traffic; shift 0,0). In the three
  others the game's own camera was still zooming after the warp when the first classic frame was taken
  (`camera_same False`), so the check says nothing there; BEV-PARITY's plain-renderer runs cover it.
- The sprites -> models swap happens at the key press: from V +5 frames the cars, people and props are
  the 3D ones while the camera is still overhead, and the other way round on the way back (section 4).

## 4. Gaps that remain

1. **Sprites and models swap at the V press.** Under Remix the classic view draws the game's sprites
   (upstream's path) and the 3D views draw models, avatars and props; the swap is one frame, while the
   camera is still overhead going in and at the start of the move going out. Closing it means the classic
   view drawing the 3D content under Remix, i.e. a change to the classic view's draw: REMIX-BEV's
   `[remix] classic_3d` (uncommitted at the time of writing, `/tmp/wt_remixbev`) does that; it is
   outside this pass's rule (classic view untouched). The light set is no longer part of the pop.
2. **No player shadow or reflection in first person on foot.** The own avatar is hidden
   (`fpHideOwnBody`); in the classic view the sprite casts one. Remix has the mechanism
   (`rtx.playerModelTextures` + `rtx.playerModel.enableInPrimarySpace=False`: hidden from the eye, in
   shadows), but the player's avatar `human_male_01` was also 14 civilian ped types' avatar (since FIX-AVATAR-IDENTITY the hero,
   now `human_male_adult_11`, is his alone: docs/ped-identity.md), so tagging its
   textures would hide those civilians too. It needs a player-only copy of the avatar's textures (a
   different hash), their hashes in the runtime's options, and the option switched per view (on in first
   person, off in third). Not done: each check is a Remix session on the shared GPU.
3. **Car lamp quads in the 3D views.** `AddCarLamps` still lays the glowing lamp quads (Remix API
   instances with an emissive material) on the sprite plane lifted to the dome height, under the 3D car
   model that has its own lamp emission. In the frames here (the van by day and night) the lamps read
   right; not checked on low or long cars, where the quads could show through or float.
4. **Frame rate.** The three sessions ran 2-30 fps on the shared host (GPU 1, 4 CPUs, the governor
   pausing containers), the 3D segments not consistently slower than classic (`r3d_2`: third 13-25 fps,
   classic 7-29). Because the camera is step-locked to the game (one 1/30 s step per rendered frame), at
   low fps the whole game and the 1.4 s move slow down together; that is consistent, but it is not
   real time. A measurement on a quiet GPU is still owed (`docs/performance.md`).
5. **Exposure.** The auto exposure meters the frame: the 3D views have sky in it, the classic view does
   not, so the same lighting reads brighter or darker per view and adapts over `darkAdaptTau` (2 s) /
   `lightAdaptTau` after a switch. Inherent to a metered exposure; a fixed exposure per time of day
   would remove it, at the cost of the night/day range the play preset tunes.
6. **Headlight bulb position.** `SyntheticHeadlightTuning().lead` (-0.188) puts the bulb behind the
   artwork's lamp, tuned for the classic dome; with a 3D model that point can be inside the hull. The
   frames show the beam on the road around cars, so it is not shadowed out, but the beam's origin was
   not checked against each model's nose.
7. **Upstream's tile emissives.** 23 of the `gta2rtx` layer's 328 emissive maps key 64 px tile uploads;
   with the HD tiles installed they match in neither view (the gta2hd layer has its own 64 sign
   emissives). The other 305 key other textures (sprite art); where a model replaces the sprite in 3D
   (cars, people, mapped objects) those emissives do not apply and the model's material does. Not
   audited per texture.
8. Test harness: `qa_lib.set_view` gives up after four V taps 0.6 s apart; at 2-5 fps that is too short
   (`r3d_1` warm-up). The take's own waits now count frames.

## Run it

```
# the take (Downtown; day 14:00 and night 22:30 at the spawn and the plaza)
STAGE=<private stage> REMIX_GPU=1 gamerun/remix_l4.sh r3d_2 1500 /work/keys_remix3d.sh \
  -e MODS_HD=1 -e LEVEL_WAIT=30 -e RTX_EXTRA=/work/rtx_play.conf.extra -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/" \
  -e GTA2DX9_LOG_LIGHTS_EVERY=2 -e GTA2DX9_PEDS_EVERY=2 -e GTA2DX9_STATE_EVERY=2 \
  -e "R3_SPOTS=start;plaza:198.5,188.5,2"
# the report, sheets and frames (python3 with numpy and Pillow, ffmpeg)
python3 tools/remix_3d_parity.py out/r3d_2 1500
```

`linux/docker/remix3d_take.py` and `keys_remix3d.sh` go to `gamerun/`. Env of the take: `R3_HOURS`
(`day=14.0,night=22.5`), `R3_SPOTS` (`name:x,y[,z];...`, `start` = where the level begins),
`R3_WARM` (seconds of view cycling first, so Remix has compiled its pipelines). The take writes
`bev_events.json` in BEV-PARITY's shape, so `tools/bev_parity.py`'s switch check (no object jumps at
a V press) runs on it unchanged.
