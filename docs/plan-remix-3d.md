# Plan: gta2-rtx-remix-3d, a GTA 6 class experience built on GTA 2

Written 8 Nov 2026 with the owner. Goal: a flawless, spectacular, smooth 3D experience that stays true to the
original and matches what the classic top-down view shows, switchable to that view at any moment, with the game's
own mechanics untouched. This document is the plan; progress lives in the GitHub issues (#1 tracking).

## 1. What "flawless" requires, layer by layer

| Layer | Where we are | What the bar needs | How much is automatic |
|---|---|---|---|
| Lighting | Remix path tracing works (night, neon, clear-coat); plain renderer flat, shadows/SSAO/bloom in progress | Path-traced play as the default, with a modern forward renderer as the smooth fallback | Remix does the lighting; presets are config |
| Materials | Albedo + one roughness per texture | Full PBR per texture: normal, roughness, metallic, height, emissive; wet/dry variants | 95 %: generated from the albedo (detail-aware normals, class-based roughness, height for parallax); hand review by eye on contact sheets |
| World geometry | Map boxes with one texture per face; props placed by rules; 0 holes | Facades with depth (recessed windows, sills, cornices, shop interiors), roof furniture, street clutter, modelled hedges and railings, water with reflection | 80 %: segment the tile art (windows/doors/signs) and extrude or displace; Remix displacement from height maps; rules for clutter |
| Vehicles | 60 generated + 13 procedural models, doors, dents, lamps, turrets; body roll/wheels/FX in progress | Sprung bodies, turning wheels, lamps lighting the road, smoke, skids, sparks, debris, crumple, glass | 90 %: all visual, driven by the game's state words |
| People | 41 Rocketbox avatars, procedural clips, weapon stances, death poses, arrest | Mocap-quality locomotion, enter/exit/jack, strikes with weight, hit reactions, ragdoll on death and run-over, crowd variety and idle life | 70 %: licensed mocap libraries (Mixamo, CMU) retargeted automatically; blend trees; a small ragdoll solver; variety generated |
| Camera and feel | Soft follow, chase, first person, wall avoidance | Player always framed, continuous blends through every transition, cinematics on JOB COMPLETE / WASTED / BUSTED, aim camera and reticle, hit-stop | Code, verified by metrics (head in frame %, yaw continuity) |
| HUD and text | Original sprites over 3D (modern HUD in progress) | Minimal modern HUD with mini-map, readable subtitles, world-space markers; classic HUD one key away | Code + one font |
| Sound | Game mixer pans for the top-down camera | Positional audio relative to our camera, reverb, stingers on the new cinematics; radio untouched | Code: a DirectSound proxy next to the D3D9 one |
| City life | The game's own spawn window (widened) | Dense, varied streets as seen from the ground | Spawn window and LOD tuning; variety is generated; behaviour stays the game's |
| Missions | 7 of 67 complete in 3D; catalogue of all jobs and skills | Every job playable and completed in 3D; nothing in the game unreachable | Skill modules per objective type, one agent each, verified on real jobs |
| Fidelity to the BEV | Ground mesh from the map; HD tiles are upscales of the originals | Everything the top-down view shows is what the 3D view shows: same art, same colours, same objects | 100 %: automated BEV parity check (orthographic render of our 3D vs the classic frame) |

## 2. Technologies to integrate

- RTX Remix runtime and toolkit (path tracing, DLSS/Ray Reconstruction on Ada, USD material layers). Our layer is hash-keyed and generated; keep it that way.
- Material generation: detail-aware normal/height from albedo (bilateral/frequency split, Marigold or Depth-Anything for large-scale relief), class-based roughness/metallic, emissive from colour and position. One pipeline for tiles, cars, props, avatars.
- Geometry generation: tile-art segmentation (windows/doors/signs) to facade depth; Remix height-map displacement where geometry would be too heavy; procedural clutter from rules; TRELLIS/Hunyuan3D for one-off props from sprite references (already proven on cars).
- Animation: Mixamo / CMU mocap retargeted onto the Rocketbox skeleton (automatic), blend trees with root motion, additive hit layers, a lightweight ragdoll (Jolt or a hand-rolled solver) for death, run-over and explosions; motion matching only if the budget allows.
- Audio: DirectSound hook for positional panning, distance and reverb relative to our camera; stingers from the game's own sound bank.
- Weather and time: Remix presets (noon, golden hour, dusk, night, rain); the plain renderer's own sky, fog and wet-road pass.
- QA automation: frame metrics (saturation, player-in-frame, frame-time percentiles, pop-in counts), the city sweep, the BEV parity check, and a vision-model review of contact sheets that ranks defects without a human in the loop. Humans look only at ranked sheets.

## 3. Minimising manual work, and parallelising what remains

- Everything that can be generated is generated and scored; a human (or the vision model) judges contact sheets, never individual files.
- Work is broken down by catalogues: the mission catalogue (67 jobs by skill), the quality-bar list (52 defects, 26 feel proposals), the asset audit. Each row is one single-objective agent with its own owned files and its own verification.
- Shared libraries are frozen while per-objective agents run; results merge through commits to the branch; the shared play build is produced only from committed HEAD.
- Hardware is the parallelism ceiling: 8 CPUs serve 4 game sessions plus one GPU job plus builds. A second machine dedicated to scripted game runs (16-32 cores, no GPU) would roughly triple mission and QA throughput; a burst GPU (A100/H100 for a few hours) would finish all material and model generation in one pass. Without them the plan still works, at the pace of about 4 sessions and one GPU job at a time.

## 4. Phases and acceptance

- Phase A (now, days): feel and fidelity foundations. Soft camera, exit/enter/jack animations, weighty combat, vehicle feel, modern HUD, tile and car PBR maps, Remix presets, plain-renderer lighting, the top 25 of the quality bar. Acceptance: every top-25 row closed with frames; the user plays the page and raises nothing from that list again.
- Phase B (weeks): depth and life. Facade depth from tile art, mocap locomotion and ragdoll, positional audio, cinematics, weather, crowd variety, all skill modules and the full 3D playthrough (67 jobs, kill frenzies, bonus levels). Acceptance: every job complete in 3D with a frame; BEV parity check green city-wide; vision-model review finds no severity-4+ defect.
- Phase C (week): spectacle and release. 1440p/60 showcase, Remix as the default play mode where the hardware allows, release gta2-rtx-remix-3d with archives, docs and a fresh-machine install verified on Windows and Linux.

## 5. What stays sacred

The game's code, physics, AI, missions, scoring, radio, voices, mission text and the classic view are untouched. The 3D experience is a renderer and a camera over the original game, and the top-down view is always one key away.
