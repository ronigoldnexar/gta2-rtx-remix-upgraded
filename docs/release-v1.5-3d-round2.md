# Release v1.5-3d-round2 (notes as published)

Third milestone of the camera-modes work (6-9 Nov 2026), built and verified on Linux (Wine in Docker, NVIDIA L4 via VirtualGL; RTX Remix path tracing on the L4). Branch `camera-modes` at `16fcaf8` (the unified tree: the 8 Nov handover line plus the night of 8-9 Nov). Handover for another machine: `docs/HANDOVER.md` section 0; state of every stream: `docs/STATUS-2026-11-08.md`.

**Since v1.4 (6-8 Nov)**
- **RTX Remix path tracing runs** on the L4: PBR layer for all 2 649 HD tiles and every car, prop, code-object and avatar texture (normal, roughness, height, metallic, wet variant), clear-coat car paint with chrome trim, liveries kept, play and showcase presets with time-of-day overlays.
- **Cars (rounds 4-6):** 73 models; doors swing, dents and fire from the game's 16-bit damage word, wrecks, siren beacons, tank turret and fire-truck cannon follow the game's aim, trains at track height, body roll and pitch, steering wheels, lamps with road pools, tyre smoke, skid marks.
- **People act out the game:** weapon read from the game (stances, recoil, muzzle flash, shells, first-person weapons), locomotion from real ground speed, car exits and moving-car boarding, deaths by cause, every ped type as a textured avatar.
- **Police:** wanted level from the game, arrest acted out, police/FBI gunfire, army with tanks at 6 stars.
- **Camera and HUD:** orbit chase camera, camera-relative controls on foot, GTA V style soft follow, camera cranes over walls; modern HUD (`[hud] modern=0` restores the original).
- **Performance:** p99 frame cost 40 ms per district (from 75-93), worst frames 60-80 ms (from 600-800); browser play p99 23-30 ms.

**New in this round (night of 8-9 Nov)**

*Remix, verified in frame on the 8x L4 host*
- Remix runs again on the new host: Wine waits for the headless wineserver; the NVIDIA device nodes are passed as `--device` on every GPU launcher, because the CPU governor's `docker update` dropped them and broke Vulkan fences (REMIX-VERIFY `953dd09`, `68bec1e`; GPU-DEVICE-FIX `2c92ef4`).
- Presets and PBR layer seen in frame: play preset (TAA-U, no motion blur) with no regression against the old look; wet overlay with lamp reflections; cop car clear-coat and chrome; paving relief with no seams in stills; the 8082 Remix play page uses the play preset (`6d83e4d`, `1b48278`, `691e5f3`).
- Police beacons under Remix: separate red and blue bulbs on the cop car, red and white on the ambulance, lighting the road at night (LIGHTBAR-2/2B `c523243`, `069bbf9`).
- **Showcase pass across Downtown, Industrial and Residential** (REMIX-SHOWCASE `65032c3`/`dccdf20`): four path-traced sessions with the play preset at five hours (noon, golden, dusk, night, wet). Neon signs light the walls and paving; wet streets reflect lamps and neon; golden hour in Industrial with back-lit clouds; frame cost about 45 ms on a shared GPU, no faults. Write-up: `docs/remix-materials.md`, "Showcase pass".

*Rendering (plain renderer)*
- Explosions as volumetric sprites with light, smoke column, shock ring and debris (QB-19 `51f43f7`).
- Water surface shader: drifting waves, Fresnel sky reflection, sun glint, shore foam (QB-37 `7b10f45`).
- Railings rebuilt as geometry on their panels (QB-11 `7dc716d`).
- Street lamp 30 610 -> 1 656 triangles; prop triangles per frame 1.01 M -> 88 k; the missing hydrant, bin and girder textures are committed (PROPS-SLIM `58193fc`).
- Near fade of objects close to the eye, first-person wall clearance, pickup labels and score pops (QB-49/50 `56b2f9d`).
- Sun shadows from buildings and the whole world, staggered far cascades (medium drive p99 53 -> 26 ms) (VISUALS-PLAIN-2 `615dc43`, `a74d25b`). **Off by default.**
- Weather and time of day in the plain renderer (QB-35/43 `b683582`, `2615950`). **Off by default.**
- Car fleet in one era: 047/048 Meteor, 083 Furore GT, 064 Truck Cab SX and 016 Panto regenerated as 1960s bodies (CAR-ERA `004f65e`, round 8).

*Camera, cars and people*
- Chase camera in a car sized from the car's body: low and close, speed FOV and pull-back, looks into turns (QB-22 `b276863`).
- First person in a car: eye over the bonnet, a dashboard over the cut (QB-5 `7bc109a`), and cab interiors per vehicle class (car, van, truck, bus) with gauges and a steering wheel that turns (QB-31 `d68edfb`).
- Aim reticle, target brackets, hit and kill markers, over-the-shoulder aim camera (QB-6 `853b6a2`).
- Weapon reload clips in third and first person (QB-29 `daf59e4`); hit reactions by bullet direction (QB-16 `9cdea58`); jacking a driver acted out (QB-14 `5545d72`); ragdolls for people run over or blown off their feet (QB-27 `13c119a`).
- Crowd variety: everyday clothes, builds, heads that follow the player (CROWD `56eaab5`).
- Framed beats for WASTED, BUSTED and JOB COMPLETE: camera move, letterbox, tint, title (QB-17/18 `4227371`).

*Missions played by script in the 3D chase view (Wave M skill modules)*
- New jobs complete: **SINK OR SWIM** (Residential, steal_car skill: 2 of 3 sessions), **WHO'S MAD?** (gunfight skill: 3 of 4).
- Re-proven through the skill modules: COP CAR CRUSH (crusher/crane, 3 of 3), PIZZA CAKE (destroy_vehicle, 3 of 3), GET ZITZAKI (deliver_intact 2 of 3, escort 5 of 5, horn pick-up), BANK ROBBERY (getaway reworked, 2 of 3), BLOW JOB (car bomb, 2 of 3), COP CAR CRUSH on the rooftop-access skill with no warp.
- 10 of 67 jobs now complete in the 3D views. In progress, not complete: FAKE TRUCE (2 of 4 groups), Downtown tank frenzy (best 9 of 20 cars), GET GAMA REI (blocked on BANK ROBBERY's respray leg), bus and truck-and-trailer jobs (no JOB COMPLETE yet).
- Records: `docs/playthrough-downtown.md`, `docs/skill-*.md`.

*Checks and tooling*
- Classic view parity: walking speed, turn rate and the game's code are identical in all views; the 3D views' wider spawn window is the one deliberate difference (BEV-PARITY `2a72f3e`, `docs/bev-parity.md`).
- Industrial and Residential city sweeps rerun with the verified level swap: 333 of 333 points, 1 998 frames, 0 holes (SWEEP-DISTRICTS `a2a1c33`).
- Play page audio: Opus over a websocket, headless probe (PLAY-AUDIO `3cb20a2`, `a13c6f8`).
- `tools/pack_release.py --stage/--rev`: DLLs from a clean worktree of the release commit, `BUILD.txt` with the commit and SHA-256 of each file (RELEASE-1.5 `c79eab9`).
- The two lines of work from the 8 Nov handover (`camera-modes` and `night-skills-2026-11-09`) are merged without rewriting either branch; the stray build folder and `__pycache__` of the night's WIP commit are dropped from the tree (MERGE-RECONCILE `16fcaf8`).

**Release assets** (layouts in `docs/HANDOVER.md` section 0; the game's own artwork is in them, so they are not in git)
- `gta2dx9-x86-linux-built.zip` (**rebuilt**): the DLLs built with mingw-w64 from a clean worktree of `16fcaf8` (`BUILD.txt` in the zip gives the commit and the SHA-256 of each file; `gta2dx9.dll` `da7f3fea...`), their `d3ddll`/`Dmavideo`/`DMAGlide` copies, `gta2dx9.ini`, the reg files and the `linux/` scripts as committed at `16fcaf8`.
- `gta2dx9_models_people.zip` (**rebuilt**): 41 Rocketbox avatars (MIT) with the new clips: reloads (QB-29), shot reactions (QB-16), jacking (QB-14). The DLL plays these clips, so use this archive with this DLL. Unpack at the repository root.
- `gta2dx9_models_cars.zip` (**rebuilt**): the 73 car models, with the five round-8 bodies of CAR-ERA (016, 047, 048, 064, 083); the other 68 are unchanged. Unpack at the repository root.
- `textures_hd_dds.zip`: HD tiles for all three districts, unchanged since v1.4 (see the known items for QB-24's road tiles).
- `remix_mod_gta2hd.zip` (**rebuilt**, 2.12 GB, store-only): the Remix material layer `gta2hd/` with the full PBR maps (12 694 textures), the layer REMIX-VERIFY and REMIX-SHOWCASE saw in frame. Unpack into `rtx-remix/mods/` beside the game or `package/rtx-remix/mods/` in the repository.

**Checks on this build:** `make stage` at `16fcaf8` from a clean worktree; the assembled stage (these DLLs, the committed props, these model archives and the HD tiles) passes `stage_check.py` (1894 model files, 2652 HD tiles); a scripted 150 s run (the play-page gate's `fight` scenario, third and first person, Downtown) ended with 0 `FAULT` lines, 0 model or texture read errors, all 41 avatars loaded with 50 animations each, colour frames with textured people, props and the modern HUD. Not run on this build: a Remix session (the Remix layer was verified on the 8 Nov evening build), the city sweep and the QA3 scenarios, the Windows/MSVC build.

**Known open items**
- Off by default, so not part of the default look: sun shadows (VISUALS-PLAIN-2; the high tier's p99 is 48.5 ms) and weather/time of day in the plain renderer (QB-35/43; lamp pools not seen in frame).
- QB-24's 60 re-authored road tiles are not in `textures_hd_dds.zip` yet: they change the tiles' hashes, and the Remix layer still keys the old ones, so they ship together once the Remix layer is rebuilt.
- The Remix layer has no PBR replacement for the slim lamp/hydrant/bin atlases (PROPS-SLIM) or the five round-8 car bodies yet; those draw with their plain textures under Remix.
- Remix: sessions started with car lamps on by day (`EFFECTS_SED`) came out sunless and flat by day (a correlation over five runs, not a bisected cause); the dusk overlay at 18:21 already reads as night; the taxi's chequer strip reads as speckled chrome; an over-bright emissive in a Downtown doorway; Residential has some low-resolution wall tiles; frame cost about 45 ms (p99 81 ms in one take, CPU-bound on pedestrians), not measured on a free GPU.
- Camera: after a warp the first-person switch sometimes fails; the chase camera can sit inside geometry at Residential (11,33); a death in a swapped district loses the player in the scripted harness.
- Missions: 10 of 67 jobs complete in 3D; FAKE TRUCE, the tank frenzy, GET GAMA REI, the bus and truck-and-trailer jobs are not.
- Not caught in a frame this round: an NPC muzzle flash, the fire truck's amber beacon, blast-victim ragdolls, the magazine particle and reload clicks.
- The night's WIP commit `14ae447` (now in the branch history) contains the generated HD tiles and models under `stage_candidate/`; the merge dropped them from the tree, but the blobs are still in the history.
- `make check` (`sehcheck.exe`) and the Windows build are untested at `16fcaf8`.
- Details: `docs/STATUS-2026-11-08.md`, `docs/qa-report.md`, `docs/remix-materials.md`.

