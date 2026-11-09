# Realistic 3D cars from the GTA2 sprites (image-to-3D pipeline)

Every GTA2 vehicle gets a textured 3D model that reads as the retro-futuristic
1940s-60s car its top-down sprite shows, with the sprite itself painted onto the
roof, hood and trunk so the car seen from above is still the game's own art.

Pipeline (one car ≈ 100 s on one B200, 4 workers on 2 GPUs in practice):

1. **Catalog** (`assets-src/cars/catalog.json`, from the CATALOG stream): per
   model number the body size in sprite pixels (64 px = 1 block), wheel and window
   rows, doors, remaps with paint colour and a design brief (`design.evokes`,
   `design.silhouette`), plus `sprites_x4/` (Real-ESRGAN x4 sprites).
2. **Concept image** (`gen3d/gen_concept.py`): Stable Diffusion XL base 1.0
   (fp16 VAE fix), 1024², prompt = view + plain light grey background + colour +
   the brief, trimmed to CLIP's 77 tokens. The 3/4 front view feeds step 3; a
   top view is kept for comparison. Colour: the livery for taxis/police/fire/
   ambulance, else the first colour word of the brief, else the nearest named
   colour to the sprite's default paint (`remaps[0].paint_rgb`).
3. **Image-to-3D** (`gen3d/run_trellis.py`): Microsoft TRELLIS
   (`microsoft/TRELLIS-image-large`), 12+12 sampler steps, `formats=
   ['gaussian','mesh']`, then `postprocessing_utils.to_glb` with the simplify
   ratio chosen for an 8 000-face budget and a 1024² baked texture.
4. **Fit to the sprite** (`tools/make_car_model.py`): upright (the painted roof
   is brighter than the underside), long axis to z by PCA, nose to +z by matching
   the cabin position with the sprite's window rows (`--nose keep|flip` overrides
   it; model 63's sleeper cab needs `flip`). GTA2 draws its car sprites
   **nose-down** (the front is the bottom row: cab-forward trucks, the pickup bed
   and tow boom at the top prove it), so +z maps to growing sprite rows; the
   catalog's `windows_px`/`wheels_px` rows are `centre - offset` and therefore
   mirrored, but `centre - mean(rows)` is still the true forward offset, footprint scaled to
   `body_px/64` blocks (height scaled by the geometric mean), wheels on y=0, the
   x4 sprite projected onto every upward-facing texel in UV space (nvdiffrast
   rasterises the mesh in texture space, weights by the normal's y from 0.3 to
   0.75), the remaining texels brightness-matched to the sprite's paint, PBR
   material metallic 0.55 / roughness 0.38. Output: `<nnn>_<name>.glb` + `.json`
   (log, size, `forward: "+z"`).
5. **Proof** (`gen3d/car_pipeline.py`): `proof/<nnn>.png` = sprite | concept |
   3/4 | top | side | front, rendered with `gen3d/render_glb.py` (nvdiffrast,
   no display needed), `status.json` with per-car timings and errors.

Run:

    cd ~/gta2-linux/gen3d
    for w in 0 1 2 3; do CUDA_VISIBLE_DEVICES=$((w%2)) venv/bin/python car_pipeline.py \
        --catalog ../assets-src/cars/catalog.json --out ../assets-src/cars/models3d --all --worker $w/4 & done
    # one car, different seed:
    venv/bin/python car_pipeline.py --catalog ../assets-src/cars/catalog.json --out ../assets-src/cars/models3d --models 10 --seed 7 --redo

Wrecks, trains and trailers are skipped (`cls` wreck/train/trailer) as are
models that share another model's sprite; the integration maps those to the
base model.

## Environment (B200, host torch 2.9.1+cu129, Python 3.12)

    python3 -m venv gen3d/venv --system-site-packages
    gen3d/venv/bin/pip install diffusers transformers accelerate safetensors imageio imageio-ffmpeg easydict \
        rembg onnxruntime opencv-python-headless scipy ninja xatlas pyvista pymeshfix igraph tqdm
    gen3d/venv/bin/pip install --no-deps torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu129  # the host's is broken
    gen3d/venv/bin/pip install "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
    gen3d/venv/bin/pip install --no-deps xformers==0.0.33.post1      # 0.0.35 does not import against torch 2.9.1
    gen3d/venv/bin/pip install spconv-cu126                          # runs on sm_100
    TORCH_CUDA_ARCH_LIST=10.0 gen3d/venv/bin/pip install --no-build-isolation git+https://github.com/NVlabs/nvdiffrast.git
    git clone --recursive https://github.com/autonomousvision/mip-splatting gen3d/ext/mip-splatting
    TORCH_CUDA_ARCH_LIST=10.0 gen3d/venv/bin/pip install --no-build-isolation gen3d/ext/mip-splatting/submodules/diff-gaussian-rasterization/
    git clone --recurse-submodules https://github.com/microsoft/TRELLIS gen3d/TRELLIS

### Rebuilding the CUDA extensions for another GPU (L4 = sm_89)

The venv's compiled extensions only carry the architectures they were built for
(`TORCH_CUDA_ARCH_LIST=10.0` on the B200). On the L4 host nvdiffrast and
diff-gaussian-rasterization failed with "no kernel image" until rebuilt for sm_89
(8 Nov 2026, logs `out/cq_nvdiffrast_build.log`, `out/cq_dgr_build2.log`):

    cd ~/gta2-linux/gen3d
    # stale objects from the old architecture are reused unless removed (literal paths only)
    rm -rf ~/gta2-linux/gen3d/ext/mip-splatting/submodules/diff-gaussian-rasterization/build \
           ~/gta2-linux/gen3d/ext/mip-splatting/submodules/diff-gaussian-rasterization/diff_gaussian_rasterization.egg-info
    TORCH_CUDA_ARCH_LIST=8.9 venv/bin/pip install --no-build-isolation --force-reinstall --no-deps \
        ext/mip-splatting/submodules/diff-gaussian-rasterization/
    TORCH_CUDA_ARCH_LIST=8.9 venv/bin/pip install --no-build-isolation --force-reinstall --no-deps \
        git+https://github.com/NVlabs/nvdiffrast.git
    # check: every .so lists an sm_89 cubin
    cuobjdump --list-elf venv/lib/python3.12/site-packages/diff_gaussian_rasterization/_C*.so

`--no-deps` keeps pip from replacing torch; `--force-reinstall` is needed because the
version number does not change. Use `TORCH_CUDA_ARCH_LIST="8.9;10.0"` for one venv
that runs on both hosts. A check run afterwards (`run_trellis.py` on the cop car's
views) produced a GLB in 2 minutes on the L4 (`out/cq_rebuild.log`).

Patches to TRELLIS (two lines each, in `gen3d/TRELLIS`): the text pipeline
import is wrapped in try/except (open3d needs libEGL, absent here); the kaolin
`check_tensor` import in flexicubes falls back to a no-op. `run_trellis.py`
wraps `xformers.ops.memory_efficient_attention` to run fp32 calls in fp16,
because xformers has no fp32 kernel for sm_100. Environment variables:
`ATTN_BACKEND=xformers`, `SPCONV_ALGO=native`. pymeshlab and open3d do not load
on this host (no libOpenGL/libEGL), so decimation is done by TRELLIS's own
simplification.

## Licences

- Microsoft TRELLIS code and `TRELLIS-image-large` weights: MIT.
- DINOv2 (TRELLIS image encoder): Apache-2.0.
- Stable Diffusion XL base 1.0: CreativeML Open RAIL++-M (commercial use allowed,
  use restrictions apply to outputs). `madebyollin/sdxl-vae-fp16-fix`: MIT.
- nvdiffrast: NVIDIA Source Code License (non-commercial research use for the
  tool itself; it only renders/bakes here, nothing of it ships).
- diff-gaussian-rasterization (mip-splatting fork): Inria/MPII Gaussian
  Splatting licence, non-commercial research; used only for texture baking.
- spconv: Apache-2.0. xformers: BSD-3. utils3d: MIT. rembg: MIT (u2net weights).
- The GTA2 sprites remain Rockstar's: the generated models embed the game's
  own artwork on their roofs, so they are derived assets of the user's game copy
  and are not for redistribution (same rule as the HD tiles).

## Results (5 Nov 2026)

60 of 60 generated models succeeded (`assets-src/cars/models3d/status.json`;
wrecks, trains, trailers and shared-sprite dummies skipped). Mean 88 s per car
on one B200 with 4 workers on 2 GPUs (concept 5 s, TRELLIS 77 s, fit 6 s);
meshes 3 000-8 000 faces, one 1024² texture each, 60 GLBs = 85 MB. Models 17,
21, 58, 63, 64 were regenerated with seed 3 after a visual check (first
attempts kept in `models3d/rejected/`). Contact sheet of every car:
`out/cars3d_contact_sheet.png`; the three-car proof `out/cars3d_proof.png`.

## Known limits

- One concept image per car (seed 1): the quality is good for sedans, coupes
  and trucks; odd shapes (hot dog van, tank, Isetta limousine) may need another
  seed or a hand-picked concept — check `proof/` and rerun with `--seed`.
- The nose test relies on the sprite's window rows; for symmetric bodies with a
  centred cabin the generated orientation is kept as is.
- Heights come from the concept, not the game; the integration can clamp them.

## Nose check and the all-models sheet (7 Nov 2026, CAR-FIDELITY pass)

The user saw "some vehicles moving backward" in play. Two checks now cover the
whole chain from sprite placement to model geometry:

1. **Placement vs travel, in the running game.** With `GTA2DX9_LOG_CAR_NOSES=1`
   the renderer logs every drawn car body every 15 frames (`car nose: obj=…
   model=N f=±1 x z nx nz`: the placement's nose direction in the world and the
   model's own `forward` sign). `tools/check_car_noses.py <gta2dx9.log>` pairs
   consecutive samples of one car into a velocity and compares it with the drawn
   nose; a model is flagged when most of its moving samples travel tail-first
   (cars do reverse out of jams, so single samples do not count). Watching the
   Downtown carriageway for 5.5 minutes from the kerb (`gamerun/car_noses.py`,
   run `out/noses_wil`, 9 335 samples) gave 19 traffic models, all 100 % nose-first:
   the placement convention (sprite nose = larger row = car +z) holds. Sheet:
   `out/car_noses_sheet.png`.
2. **The model's own nose.** A placement-correct car still drives backwards if the
   GLB's grille sits at -z. The decisive view is the generator's post-fit proof
   render (`assets-src/cars/models3d/proof/NNN_name.png`, panel "3D front" = the
   camera at +z): all 60 image-to-3D models were tiled and read
   (`out/proof_fronts_{1,2,3}.png`). One is wrong: **069 U-Jerk Truck** has the
   pickup bed at +z (`out/proof_zoom.png`, middle row). It is also the third most
   frequent car in Downtown traffic, which matches the report. Fixed at the source
   for now by `"forward": "-z"` on its entry in `assets-src/manifest.json` and
   `assets/models/manifest.json` (the runtime reads `forward` from the manifest's
   `imported` list) and `69: 'flip'` in `gen3d/car_pipeline.py`'s `NOSE_OVERRIDE`,
   so a refit (`--fit-only`) re-projects the roof sprite the right way round; until
   that refit (nvdiffrast is built for the B200 and does not run on this L4) the
   roof art of the truck is end-for-end, which only a rooftop camera would notice.
3. **Every model in the game, from the chase camera and from eye height.**
   `[devtools] force_car_model=N` (new, re-read once a second) draws every traffic
   car as model N; `gamerun/car_models_sheet.py` warps the player into the
   Downtown carriageway where the traffic queues up behind him nose-first, steps
   through the model numbers and takes a chase and a first-person frame of the
   stopped car for each (`gamerun/car_models_sheet_make2.py` tiles them). Sheet:
   `out/car_models_ingame_sheet.png` (68 models; the queue faces the camera, so
   every correct model shows its grille).

Also in this pass (`dll/src/car_bodies.cpp`):
- The fit of a model to the sprite's footprint scaled length and width
  independently; a model whose proportions differ from the sprite's was stretched
  one way. The aspect change is now capped at 15 % (the rest overhangs or falls
  short of the footprint). The 60 image-to-3D models were already within the cap
  (measured from their `size_blocks` against the CARI body size), so this is a
  guard for the parametric set.
- The driver's-seat hood copy dropped every triangle that crossed the cut planes,
  leaving a stair-stepped edge on curved bonnets. The triangles are now clipped
  against both planes (Sutherland-Hodgman per triangle, new vertices appended),
  so the edge is the plane itself.

## The driver's seat: eye over the bonnet, a dashboard over the cut (8 Nov 2026, QB-5)

Quality-bar row 5: in first person the own car's bonnet broke up into black spikes filling
the lower half of the view, or into yellow/pale ribbons across it. Reproduced on the plain
renderer with a first-person knock scenario (`gamerun/qa_qb5.py`, 30 fps clips of each
knock): the Schmidt (model 36) and the Aniston BD4 (model 2) showed it **at damage 0**, so
neither the dents nor the knocks caused it; the knocks only made it jump.
A sweep of all 72 models from the seat (`gamerun/qa_qb5sweep.py` with the new
`[devtools] force_own_car_model`) showed the same shards on about a dozen generated models.

Causes (`dll/src/car_bodies.cpp`):
1. The hood copy (`HoodModelFor`) is the hull cut a hand under the eye and just ahead of it.
   From the seat the eye looks down through that open cut face into the hull. What shows
   there is the inside of the wings and the underbody, plus the faces of a generated mesh
   that the facing test lets through (vertex normals on these meshes are noisy): the black shards.
2. On cars whose bonnet stands higher than the generic cabin deck (0.62 of the roof, from
   the sprite), the eye sat below the bonnet top. The horizontal cut at eye height then sliced
   the lumpy bonnet top into islands and strips (the pale/yellow ribbons, the gold wings of the BD4).
3. The eye does not ride the body springs (`vehicle_fx`). A knock's full pitch and heave
   (up to 0.10 rad and 0.05 block) lifted the bonnet through the cut for a moment.

Fixes:
- **Dashboard** (`DrawDash`): a panel across the cut, from the floor to the top of what the
  copy keeps in the first 0.08 block ahead of the cut, and a shelf at that height back
  toward the eye. Its width is that of the kept geometry. It is drawn untextured and lit
  (it darkens at night with the body), in a darker shade of the body paint with a floor of
  0.10, so a dark car does not show a black hole. The top stays 0.008 under the clip plane.
- **Eye over the bonnet** (`BonnetTopFor`): the 99th percentile of the model's vertex
  heights ahead of the windscreen. The own car's cabin deck is kept at least 0.03 over it
  (and the roof 0.08 over the deck), so the eye (`view_modes`: deck + 0.62 (roof - deck))
  looks over the bonnet and the cut never runs through it. Only the player's car, only
  whole models.
- **Springs from the seat**: the hood copy gets a third of the body's spring pose (the
  matrix lerped toward the identity), so the jolt still shows and the bonnet stays under the cut.
- `[devtools] force_own_car_model=N` draws the player's car as CARI model N (0..71),
  fitted to the footprint of the car driven, for checks from the seat.

Verified on the plain renderer (Remix untested: GPU 0's DXVK fence failure). Runs
`out/qa_qb5base2` (before: Schmidt shards), `out/qa_qb5fix` (before the dashboard: BD4
shards and gold ribbons), `out/qa_qb5sw1` / `out/qa_qb5sw2` (72-model sweeps before/after
the dashboard), `out/qa_qb5fix2` (G4 bank van with 4 real knocks, forced damage 6000 to 26000,
forced BD4 and Schmidt with knocks), `out/qa_qb5sw3` (the worst 11 models at damage 26000
and 0). After the fix no frame shows the shards or ribbons. Small dark bits of real
inner-wing faces can still show past the dash on some generated models (model 46).
With a forced model on a long footprint (the Schmidt on the van) the eye can sit high
enough that the short bonnet falls out of view. That case comes only from the devtools key.

## The cab from the driver's seat, per vehicle class (9 Nov 2026, QB-31)

Quality-bar row 31: in first person the van's cab was a dark featureless slab across the
bottom of the view and the truck showed a small green nub for a hood. The slab was QB-5's
dashboard (`DrawDash`): one flat panel in a darker shade of the paint, from the hood copy's
cut back toward the eye. The new `dll/src/cab_interior.cpp` draws a cab in its place,
in the car's own frame around the eye, untextured and lit by the scene's lights:

- **Dashboard**: a shaped top (from the windscreen's foot up to a crest, back to a rolled
  edge toward the driver) with dark defroster slots along the glass.
- **Instrument binnacle** in front of the driver: a plate tilted up toward the eye with
  2 gauges (car, van) or 3 (truck, bus), a visor over its far half. The speedometer
  needle follows the car's speed (`VehicleFeel::speed`), the rev needle rises with it,
  and the faces glow at night (`g_lampDark`). The eye looks down on the dash at about 25 to
  35 degrees, so gauges under an overhanging cowl were hidden (run `qa_qb31b`). The plate
  now faces the eye.
- **Steering wheel**: a rim (torus), three spokes and a hub. The top of the rim sits just
  over the dash's rear edge, at the bottom of the view. It turns with the front wheels
  (6 x `VehicleFeel::steer`, clamped to 2.6 rad).
- **Windscreen header** across the top of the view, with a **rear-view mirror** under it
  toward the middle of the car, the **near A-pillar** at the edge of the view, and the
  **door mirror** on an arm beyond it.
- **Per class** (`CabClassFor`: a table of CARI numbers, and any flat-fronted body from
  `CabShapeFor` counts as a bus):

| class | models (examples) | dash | wheel radius / rake | gauges | door mirror |
|---|---|---|---|---|---|
| car | everything else | dark vinyl, a touch of the paint | 0.019 / 25 deg | 2 | small |
| van | 3, 4, 22-27, 30, 34, 35, 38, 41, 52, 67, 68, 85 | grey plastic | 0.021 / 38 deg | 2 | medium |
| truck | 7, 17, 21, 54, 55, 58, 63-66, 69 | brown-black | 0.025 / 55 deg | 3 | tall west-coast |
| bus | 6, 11, 59-61, 86; flat fronts | grey-green | 0.028 / 62 deg, almost flat | 3 | tall |

Sizes are in blocks around the eye. The dash stands 0.10 ahead of the eye, so they are
roughly a tenth of the real size in metres: the parts keep the angles they have in a real
cab.

- The dash line is the hood copy's (`HoodCopy::dashTop`), but never more than 0.047 under
  the eye. On bodies whose bonnet falls away from the cut (the van 68) or where the eye sits
  high over the bonnet (the Schmidt, QB-5's `BonnetTopFor`), the dash otherwise dropped out
  of the view and the road showed where it should be (runs `qa_qb31b`, `qa_qb31c`). Every
  class now frames the same way. When the copy keeps nothing just ahead of the cut, the cab
  is still drawn, at the body's width.
- **Flat fronts** (class bus): the hood copy is not drawn. From the seat it was only the
  front panel under the windscreen, a dark slab past the dashboard.
- The plain renderer clips the own car a hand under the eye (user clip plane). The cab is
  drawn with that plane off, because the header and mirrors sit above it, and the state is
  restored afterwards.
- `[devtools] cab_interior=0` falls back to QB-5's plain dashboard, for before/after frames.
  It is re-read once a second and documented in `package/gta2dx9.ini`.

Checks: `gamerun/qa_qb31.py` (workspace). It enters the scene car in first person, draws the
player's car as each model in `QB31_MODELS` (`force_own_car_model`) and takes a frame of each.
Models in `QB31_BEFORE` get a second frame with `cab_interior=0`. Models in `QB31_DRIVE`
get a frame while steering and accelerating.

Verified on the plain renderer (L4 GPU container, 1280x720), run `qa_qb31d`, with the
scene car drawn as the Minx 13 (while steering), the Schmidt 36, the van 68, the G4 bank van 4,
the truck cab 63, the garbage truck 21, the bus 11 and the GT-A1 19. Every frame shows the
dash, the gauges, the top of the wheel, the header, the rear-view mirror and the near pillar.
The wheel turns and the speedometer needle rises in the steering frames, and no `FAULT`
appears in the log. Before/after: the van 68 and the truck 63 with `cab_interior=0`.
Earlier runs (`qa_qb31a` to `qa_qb31c`) are the iterations described above.
Untested: RTX Remix (the cab is drawn the same way as `DrawDash`: untextured, lit, fixed
function), the lit gauges at night, and wreck models (no cab at 72+).

### Textured cab, wheel hub and spokes, both pillars, sports and taxi (FIX-FIGURE, defect pm2-fp-cockpit-flat-untextured-placeholder-boxes)

- Every cab surface has a 64x64 texture made at run time (`SurfaceTexture`, no art files): pebbled vinyl
  on the dash, fine-grained plastic, brushed trim, headliner weave, stitched leather on the wheel, and gauge
  faces with a 270-degree tick ring. Planar UVs from the car-frame position (a tile every 0.025 block); the
  texture is modulated by the lit material colour. `CabInteriorReleaseDevice` frees the textures with the car bodies.
- The wheel's rim top is raised by 0.6 x its radius, so the hub (a horn pad), the three metal spokes (left and
  right drooped, and down) and the gauges through the wheel's upper half are in view; before, only the top arc showed.
- The passenger's A-pillar, kept within about 45 degrees of the nose (the seat is compressed, so at its true reach it
  was outside the view), and an inner pillar face on both sides. Centre stack (vents, radio) and glovebox on the dash's
  rear face (mostly below the view).
- `CabClass::Sports` (Aniston BD4, Shark, GT-A1, Miara, Arachnid, Stinger, Meteor, Hachura, Michelli Roadster,
  Trance-Am, Z-Type, Rumbler, Jagular XK, Furore GT, special agent car): dark leather dash, aluminium trim, a small
  thick-rimmed wheel, three dials. A taxi (models 51, 56) has a fare meter with red digits on the dash.
- The hood is still the car's own body copy in its own paint (`HoodModelFor`). The torn black shards seen on the Arachnid
  hood are a separate defect (pt-fp-cab-jagular-xk-torn-black-shards).
- Verified: out/ff_cab_base3 (HEAD a81174f) vs out/ff_cab_fix1 (Arachnid, sports) and out/ff_cab_taxi4 (forced taxi,
  `force_own_car_model=56`), `compare_1280x220.png`, 0 FAULT. Frame cost: on the same script, the tip without this change
  measured 7.7 ms sprite-stage average and with it 6.4 ms, so the change is within run-to-run noise. Both are well above
  a81174f's 2.6 ms, a regression from other commits (not the weapon rig: 7.8 ms with `GTA2DX9_WEAPON_RIG=0`).

## Clean albedo pass (8 Nov 2026, CAR-QUALITY-4)

The user saw the cars as "completely worn out" and the police car with "lighting
smeared across it". Causes found in the v1/v2 models: (1) the SDXL concepts were often
line drawings, poster sheets or several cars on one image (a "black and white" livery
reads to SDXL as a monochrome drawing); (2) the x4 game sprite projected onto every
upward face put its soft, drawn-in highlights across hoods and trunks (the cop car's
blotchy blue-white bonnet); (3) the side-livery option painted the sprite's row colours
along the flanks as vertical streaks; (4) the v2 delighting divided by a global-median
Gaussian low-pass, which turned black trim grey and left grey halos round every dark
part; (5) image-to-3D sees one side of the car and bakes the hidden side into a shadow;
(6) the cabin-position nose test put the v3 cop car tail-first.

The pass, all scripts in `gen3d/` (outside git) plus the tools here:

1. **Concepts** (`gen3d/concepts_v3.py`): "studio product photograph of one single car",
   per-model paint words (cop: white body with dark blue doors, hood and trunk), a
   negative prompt against drawings/text/collages/dirt, several seeds per view, and a
   check on each try's rembg cut-out: one connected car, not touching the frame, not line
   art (paper-white + ink-black share), no hot specular blobs, a sprite palette match
   (k-means colours of the game sprite), and for car classes a front-view test (DINOv2
   against front/rear prototypes, see 4). The best try is `concept/<stem>_3q_v3.png`;
   tries and scores in `concept/v3try/`, `concept/v3_qc.json`, `gen3d/work/cq4_concepts.log`.
2. **TRELLIS** (`gen3d/trellis_v3.py`, one process, the L4 cannot hold SDXL and TRELLIS
   together, so `gen3d/work/cq4_orchestrate.sh` alternates batches): two candidates per
   model, c0 = the 3/4 view, c1 = another seed (or the three views when they exist; with
   separately generated views it blends bodies and is usually blurrier). 8 000 faces at the
   source: pymeshlab's decimation filters do not load on this host.
3. **Fit** (`tools/make_car_model.py` via `gen3d/car_pipeline2.py --stage fit --tag v3c`):
   floating debris dropped (`drop_debris`, connectivity by position since UV seams split
   the mesh), `--delight` with the new bilateral shading estimate
   (`tools/delight_texture.py`: shading = local / regional bilateral low-pass of the
   luminance, so the paint level stays and nothing bleeds across albedo edges; specular
   blobs filled by normalised convolution), `--balance-sides` (the hidden flank's
   low-frequency colour pulled to its mirror on the lit side, per channel, details and
   lettering not mirrored), `--roof-only 0.8` (the sprite only on the cabin roof),
   `--no-paint-match` for liveries and a paint-match clamp of 0.8-1.25 for the rest,
   no side livery, materials left as plain PBR factors for the renderer.
4. **Nose** (`tools/nose_from_concept.py`): the fitted model rendered from the four
   diagonal 3/4 views, compared with the concept cut-out by DINOv2 (ViT-L/14 reg); the end
   that matches is the end the concept shows. SDXL sometimes draws a rear 3/4 view (013
   Minx, 033, 040): the concept's own front/rear margin against prototypes built from the
   59 checked v1 models (`gen3d/work/nose_protos.npz`, `--protos`) flips the verdict for car
   classes, and `proto_margin` (does the +z end look like a front) is kept as a second vote.
   The v1 `NOSE_OVERRIDE` table is not used for v3 candidates.
5. **Score and pick** (`tools/score_car_model.py`): the lighting term is now the bilateral
   highlight share, the bilateral shading variance and the left/right flank balance; v1 was
   re-scored with the same scorer (`out/car_scores_before_cq4.json`). Candidate = best total
   (+0.3 x concept likeness as a tie-break, never a tail-first one); `--stage reselect`
   re-picks from `status.json`, `--add-candidates 2,3` fits extra candidates without redoing
   the others (`gen3d/cq4_round2.py` makes them: another TRELLIS seed, the runner-up concept).
6. **Integrate** only models whose total beats v1 and that pass a look at
   `out/car_quality_sheet.png` (`tools/car_quality_sheet.py` renders v1 and v3 with
   `render_glb.py` from five views incl. the far side): `gen3d/integrate_v2.sh`, which now
   turns 069 end for end (`gen3d/flip_forward.py`) because its manifest entry keeps
   `"forward": "-z"`; `tools/make_car_manifest.py` now carries `forward` over when it rebuilds
   the manifest (it used to drop it).
7. **In game**: `gamerun/car_models_sheet.py` with `GTA2DX9_SCENE_NO_CAR=1`,
   `SHEET_XY=164.5,149.2 FACE_XY=180,149.4` (in the lane, the queue facing the camera) and the
   INI_SED for `scene_key=F10`; the player is run over now and then, so the runner re-warps
   after a respawn and runs go in chunks of 5-10 models. Before frames: a stage copy with the
   v1 models (`stage_cq4_v1`). `tools/car_ingame_sheet.py` -> `out/car_ingame_sheet_v2.png`.

Results (8 Nov 2026, L4): 60 generated models regenerated (90 concept images kept of
~260 tried, 120 + 49 TRELLIS candidates, ~45 s each). Same scorer for both: 35 of 60
beat v1; 33 integrated (0 1 8 10 11 12 14 16 18 30 32 33 34 36 37 42 44 46 47 48 49 51 53
54 56 58 62 63 67 69 71 83 86), mean total 0.859 -> 0.894 and lighting 0.59 -> 0.70 over
those; 005 and 019 scored higher but were rejected on sight (dark smudges on the flank,
a black side). Cop car 0.887 -> 0.901 (navy and white with the door badge, no sprite
smear on the bonnet), taxi 0.912 -> 0.922, medicar 0.910 -> 0.917, karma bus 0.863 ->
0.904; the fire truck (0.848 vs 0.903) and 24 others keep v1 for now. Sheets:
`out/car_quality_sheet.png` (all 60, v1 | v3 from five views), `out/car_ingame_sheet_v2.png`
(33 integrated models, chase camera, before = `stage_cq4_v1`), scores
`out/car_scores_before_cq4.json`, `out/car_scores_after.json` (`integrated`, `better`,
`nose_turned`, `nose_concept_match` per model). In game every integrated model that
came close to the camera drove nose first; 069 shows its bed and tail lamps at the
placement's rear with the turned GLB and `"forward": "-z"`.

Open: models that still lose (2 3 4 7 13 17 21 22 23 27 28 29 31 35 38 39 40 41 45 50 52
57 64 70 82; several by < 0.01); a few concepts are of the wrong era (048, 083 modern, 052
a modern van); the runtime paint tint recolours liveries per remap (taxis in green and
orange as before); vertical light gradients (bright roof, dark flanks) are not removed.

## Round 5: the 27 models that still shipped v1 (8 Nov 2026, CAR-QUALITY-5)

After CAR-QUALITY-4, 27 models still used the worn v1 GLB: the 25 that did not beat v1
(2 3 4 7 13 17 21 22 23 27 28 29 31 35 38 39 40 41 45 50 52 57 64 70 82) and 005/019, which
scored higher but were rejected by eye. Scripts in `gen3d/` (outside git) unless noted.

1. **Delighting: bright roof over dark flanks** (`tools/make_car_model.py`, two new flags used for
   every round-5 fit). `--balance-vertical`: the concept is lit from above, so hood/roof/trunk come
   out brighter than the flanks. Paint faces are the faces whose chromaticity matches the flanks'
   dominant paint (an area-weighted chromaticity histogram peak of the side faces); the median
   luminance of the upward paint faces is brought to the flank level by a smooth gain over the face
   normal's height (tops x sqrt(g), flanks x 1/sqrt(g)). The lift is soft (x*g / (1 + (g-1)*x)), so
   light paint and chrome never clip: a plain multiply clipped the light side and made new
   highlight blobs and unequal flanks in the scorer. A function of the normal only, so liveries keep
   their contrast; two-tone tops (little flank paint on top) are left alone. `--roof-norm` (with
   `--roof-only`): the x4 sprite is drawn bright. On plain cars a sprite roof brighter than the body
   paint takes the paint of the top surfaces (hood/trunk/roof after the vertical balance) with the
   sprite's brightness pattern on it (ratio clamped to 0.35-1.08, so the drawn highlights do not come
   along); a dark sprite roof (vinyl, two-tone: 005) is kept. Liveries keep the sprite's colours,
   scaled to the concept roof's brightness. Both share `_face_colours` / `_apply_face_gain` with the
   side balance.
2. **Concepts** (`gen3d/concepts_r5.py`): a hand-written brief per model from the sprite and the
   name, in two wordings (A = make, model and year, e.g. "1959 Aston Martin DB4 grand tourer coupe";
   B = a generic era/body description), plus a third (C) for the long ladder fire truck and the
   GT40; "modern car, 2000s, SUV, LED headlights, rear view, ..." added to the negative prompt; 4
   seeds per wording, every try checked with `concepts_v3.qc` (+ the DINOv2 front-view test for car
   classes). 228 tries in `concept/r5try/`, checks in `concept/r5_qc.json`. The 2-3 TRELLIS inputs
   per model were picked from contact sheets (`gen3d/r5_contact.py`) by the check score and by eye:
   right era and body (COE trucks for 007/064, a step-side for 041, a long body for 028), the car
   centred, no text, no second object (the hot-dog and ice-cream tries often put a second sausage or
   cone on the floor). Picks: `gen3d/r5/picks1.json`, `picks2.json`.
3. **TRELLIS** (`gen3d/r5_jobs.py`, `run_trellis.py --jobs`): 82 candidates from the picks, then
   seeds 2 and 3 of the best concept for the 18 models still behind, and of the fire truck and the
   Isetta (42 more). `run_trellis.py` now loads DINOv2 from the local torch hub cache:
   `torch.hub.load('facebookresearch/dinov2')` goes to GitHub, and its HTTP 504s killed whole batches.
4. **Fit, score, pick** (`gen3d/fit_r5.py`, `gen3d/r5_choose.py`): the CQ4 fit (debris, bilateral
   delight, side balance, roof-only sprite, concept-based nose turn) plus the two flags, for the new
   candidates and the 95 CQ4 candidates refitted. Status in `models3d_r5/r5_status.json`, renders in
   `models3d_r5/proof/<stem>__<cand>.png` (`gen3d/r5_proofs.py` stacks them); pick = car_pipeline2's
   pick_key minus candidates rejected by eye (`gen3d/r5/rejects.json`: 005 v3c0/v3c1 dark side
   smudges, 029 r5A51 red-smeared windows, 070 r5A53_s2 black far side), copied to
   `models3d_r5/chosen/`. `gen3d/integrate_v2.sh` takes `V2=` to integrate from there.

Results (v1 = the CQ4 v1 scores, same scorer): 10 of 27 now beat v1 and passed the look, and were
integrated: 002 Aniston BD4 0.872 -> 0.941, 005 Beamer 0.883 -> 0.884 (a BMW Neue Klasse now, clean
flanks), 017 Fire Truck 0.903 -> 0.917 (ladder lying along the body), 019 GT-A1 0.838 -> 0.906,
028 Dementia Limousine 0.900 -> 0.921, 029 Dementia 0.940 -> 0.941, 035 Benson 0.894 -> 0.897,
038 Big Bug 0.901 -> 0.912, 057 T-Rex 0.850 -> 0.901, 064 Truck Cab SX 0.827 -> 0.853 (a red
cab-over). Sheets: `out/car_quality_sheet_r5.png` (all 27, v1 | chosen r5 from five views),
`out/car_ingame_sheet_r5.png` (the 10, chase camera, before = `out/cq4_ingame_before_all`); scores
`out/car_scores_after_r5.json` (`candidate`, `candidates`, `cq4_total`, `before_total`, `better`,
`integrated`, `rejected_by_eye`).

Still v1 (17): near misses 013 Minx 0.877/0.882, 021 Garbage Truck 0.893/0.895, 023 Hot Dog Van
0.896/0.905, 045 Spritzer 0.881/0.885, 070 Z-Type 0.910/0.912, 003 Pacifier 0.856/0.865; further
off 004 007 022 027 031 039 040 041 050 052 082. Where they lose: `lumps` (a cab and a taller box,
a gun or a roof rack break the smoothed roof line: 007 0.12 vs 1.00), `texture` (Laplacian variance
of the 1024 atlas plus a penalty for light-grey texels, which hits grey and cream paint), and the
v1 baselines of the small cars are high (027 0.945, 050 0.948). 019 still has a darker lower flank
(a shadow gradient, not the black side of its CQ4 model); 005's far side is a little darker toward
the rear.

## Round 6: scorer biases fixed, the last 17 v1 models replaced (8 Nov 2026, CAR-QUALITY-6)

Round 5 showed the 17 models still on v1 (003 004 007 013 021 022 023 027 031 039 040 041 045 050 052 070
082) lost on the scorer, not by eye. Scripts in `gen3d/` (outside git) unless noted.

1. **Scorer** (`tools/score_car_model.py`, nine terms now; totals are not comparable with earlier rounds):
   - `lumps`: the roof profile is the max height per z-slice of points *sampled over the surface*. It used the
     vertices, and a decimated flat box roof is a few big triangles with no vertex in most slices, so every
     box truck, van and bus roof read as a row of deep dips (the "0.12 box truck"; with samples 007, 004, 052
     score 1.0). The reference is body-type aware (`body_type`): trucks, vans, buses, pickups, emergency,
     special/tank, off-road (`BOXY_CLASSES` + `BOXY_MODELS`) and the open-top jeeps/roadsters
     (`OPEN_TOP_MODELS`) use a 5-slice running median, which keeps steps (cab then a taller box, windscreen
     frame over a cockpit); cars keep the smoothed curve. Models whose sprite carries a roof item (gun,
     turret, light bar, ladder, sign, rack, boom, stacks: `ROOF_ITEM_MODELS`) do not count tops above the
     reference.
   - `texture`: the near-background-grey penalty skips texels within 24 of the model's own flank paint
     (`flank_paint`), so light grey and cream paint are neutral.
   - `smear` (new): the albedo seen without lighting from the left, the right and above (`_view_grids`:
     800 k surface samples, texel through the UVs, a z-buffer per cell; sides = the lower flank panels),
     the dominant-paint region (chroma-histogram peak, closed and hole-filled so dark streaks inside the
     panel stay in), split at crisp colour edges (liveries, two-tone, trim are design) and measured for soft
     variation: band-pass lightness (blotches), low-pass lightness (stains), chroma std (colour smears),
     against a clean level or the sprite's own paint variation where higher (capped at 1.5x); plus a penalty
     when one flank has far less paint than the other (a black far side). v1 means 0.77 on the 17, chosen
     0.90.
   - Known remaining bias: the `texture` sharpness half (Laplacian variance of the atlas) still rewards v1's
     noisy, high-contrast textures over a clean delighted albedo (17 models: 0.96 v1 vs 0.75 chosen), so
     several clean candidates still total below a worn v1 (013 023 027 039 040 041 050 052 082). Not changed
     this round: gradient percentiles show the same ordering, a fair crispness measure needs livery edges.
2. **Re-score** (`gen3d/r6_rescore.py`): v1, shipped and every CQ4 (`models3d_v2`, `raw/*_c*_fit`), round-5
   (`models3d_r5/fit`) and round-6 (`models3d_r6/fit`) candidate of the 60 models, 517 GLBs ->
   `out/car_scores_r6.json` (`candidates` with every term and the nose check, `chosen`, `integrated`).
3. **Look** (`gen3d/r6_contact.py`): one contact sheet per model, a row per GLB from five views (3/4 front,
   top, side, front = +z, 3/4 rear = far side) with the terms, `out/r6_contact/`, `out/r6_contact43/`,
   `out/r6_contact_new/`. Rejected on sight: split meshes (013 cq4/v3c, 045 c2), black far sides (013 r5A53*,
   007 r5, 023 cq4_c3/v3c3, 035 r5_v3c2, 040 r5A51), tail-first (021 cq4/v3c dump bodies), modern vans (052
   cq4), upside-down or cross-shaped fits (013 r6B62_s2, r6A63), black ground plane (031 r5A53).
4. **New concepts** where no candidate was clean (`gen3d/concepts_r6.py`, body-type briefs: a 1940s box truck
   with a box taller than the cab, a streamlined armoured bank van with two roof vents, a rear-loader garbage
   truck with its hopper, the Minx; 30 tries in `concept/r6try/`, checks `concept/r6_qc.json`), TRELLIS from
   the picks (`r6/picks1.json`, `picks2.json`, `r6_jobs.py`, 14 candidates) and `gen3d/fit_r6.py` (the round-5
   fit with `--balance-vertical --roof-norm`). Briefs for 003 022 023 027 031 052 were written but not run:
   their round-5 candidates were already clean.
5. **Pick and integrate** (`gen3d/r6_choose.py r6/final_picks.json` -> `models3d_r6/chosen`,
   `V2=assets-src/cars/models3d_r6/chosen gen3d/integrate_v2.sh ...`): by eye, score as tie-break.

Results: all 17 replaced, plus 2 swaps among the 43 (001 Wellard CQ4 c0 -> c1: even olive paint instead of dark
smears; 042 A-Type c0 -> c1: no grey patches). Picks (v1 -> chosen total, round-6 scorer): 003 Pacifier r5_v3c0
0.828 -> 0.883 (green, turret), 004 G4 Bank Van r6A61 0.846 -> 0.884 (streamlined navy van), 007 Box Truck r6B63
0.895 -> 0.900 (brown cab and taller box), 013 Minx r5A54 0.868 -> 0.865, 021 Garbage Truck r5B53_s2 0.891 ->
0.896 (rounded body, rear hopper), 022 Armed Land Roamer r5B54 0.836 -> 0.868, 023 Hot Dog Van r5B53 0.888 ->
0.862 (hot dog on the roof, awning), 027 Ice-Cream Van r5A51 0.936 -> 0.874 (cone along the roof), 031
Jefferson r5A51_s3 0.884 -> 0.888, 039 Morton r5A53_s3 0.889 -> 0.875, 040 Maurice r5B51 0.918 -> 0.884, 041
Pickup r5B51 0.932 -> 0.885, 045 Spritzer r5_v3c3 0.885 -> 0.908, 050 B-Type r5_v3c0 0.918 -> 0.905, 052 SWAT
Van r5A51_s2 0.893 -> 0.866 (1950s armoured box), 070 Z-Type r5A51 0.894 -> 0.907, 082 Jagular XK r5A54_s2 0.910
-> 0.898. Over all 60 (v1 -> shipped now): total 0.874 -> 0.891, smear 0.78 -> 0.84, lighting 0.60 -> 0.69.
Considered and kept after a look: 011 014 035 036 047 063 064 069 083 (a higher-scoring candidate was not cleaner,
or had a dark far side, or a wrong body). Sheets: `out/car_quality_sheet_r6.png` (all 60, v1 | shipped from five
views), `out/car_ingame_sheet_r6.png` (the 19 changed models, chase camera before/after + first person).
Open: 083 Furore GT and 047/048 Meteor are still modern bodies (replaced in round 8 below); the runtime paint tint recolours per remap.

## Round 8: one era for the whole fleet (9 Nov 2026, CAR-ERA)

Goal: the fleet reads as one 1950s-60s set (`assets-src/cars/design_language.md`: "nothing after ~1972 in
spirit"). A sheet of all 60 generated models from the 3/4 front view (`out/carera/fleet_before.png`) showed five
outliers: 047 Meteor (a 1970s wedge with fins), 048 Meteor (a 1980s hatchback), 083 Furore GT (a modern white
supercar), 064 Truck Cab SX (a 1990s cab-over) and 016 Panto (a 1980s Panda-style hatch). The rest of the fleet
fits; 003 Pacifier (an armoured car that reads as a modern MRAP) is left open, because a military vehicle of the
period is hard to tell from a modern one at chase distance. Scripts are in `gen3d/` (outside git), on the
generation GPU (`CUDA_VISIBLE_DEVICES=2`, `flock /tmp/gta2-gen.lock`).

1. **Concepts** (`gen3d/concepts_r8.py`, a copy of `concepts_r7.py` with new briefs; tries in
   `concept/r8try/`, checks `concept/r8_qc.json`). The CAR-QUALITY-7 Meteor briefs (1969-70 Mustang/Challenger
   muscle cars) gave long sedans that do not fit the short wedge sprite, so the Meteor became a **1960s Italian
   mid-engine coupe**: 047 = "1967 Alfa Romeo 33 Stradale ... ducktail spoiler" (A) / a generic 1960s mid-engine
   coupe (B) / a Dino 206 (C); 048 (the "engine on show" variant) = a Ferrari 330 P4 / Ford GT40 with the rear
   deck open. 064 = a 1958 Kenworth bubble-nose / 1950s cab-over / 1959 Mack cab-over; 016 = a 1960 Austin Mini /
   1960s tiny two-box saloon / Fiat 850. The 083 concepts from round 7 (`concept/r7try/`, a Ferrari 275 GTB and a
   Cobra Daytona with the white centre stripe) were already right and were used as they are. 12 tries per model
   (3 wordings x 4 seeds).
2. **TRELLIS** (`gen3d/r8_jobs.py <picks> <jobs> --seed2`, picks in `gen3d/r8/picks*.json`: a concept dir and
   key per pick, the first pick also with TRELLIS seed 2): 19 candidates, about 25 s each on the L4.
3. **Fit and score** (`gen3d/fit_r8.py --models 47,48,83,64,16`: the round-6 fit with `--balance-vertical
   --roof-norm`, the concept-based nose check, the round-6 scorer; fits and five-view proofs in
   `models3d_r8/fit/`, `models3d_r8/proof/`, scores `models3d_r8/r8_status.json`).
4. **Pick by eye, score as tie-break**, copied to `models3d_r8/chosen/` and over `models3d/`; the shipped
   GLBs before this round are in `models3d_r8/old_shipped/`. Then `make_car_manifest.py` (unchanged output: same
   names) and `import_assets.py ... --only <names>` for the five models only.

| Model | Old (round-6 total) | New pick | Total | Reads as |
|---|---|---|---|---|
| 047 Meteor | 1970s wedge with fins, 0.870 | `r8B82` | 0.906 | 1960s Italian mid-engine bubble coupe with small fins |
| 048 Meteor | 1980s hatchback, 0.894 | `r8A83_s2` | 0.896 | 330 P4-style racer, louvred engine deck |
| 083 Furore GT | modern white supercar, 0.879 | `r8pA71` | 0.911 | Ferrari 275 GTB-style coupe, white centre stripe |
| 064 Truck Cab SX | 1990s cab-over, 0.870 | `r8C83_s2` | 0.916 | 1960s Mack-style tractor, chrome grille, stacks |
| 016 Panto | 1980s Panda-style hatch, 0.878 | `r8A82` | 0.873 | 1960 Mini, even green paint |

Rejected on sight: 048 `r8A83`/`r8C83` (black ground plane under the car), 048 `r8A81` (floating debris, race
roundel), 047 `r8A82`/`_s2` (dark smears on the rear flanks), 016 `r8A84` (0.943, but pink glass and a
yellow-to-green smear along the flank), 064 `r8C82` (tail-first, turned). The 016 pick scores 0.005 below the old
model and was taken for its era and clean paint.

Two traps met on the way, worth knowing for the next round:
- `assets-src/manifest.json` is older than the committed `assets/models/manifest.json` (the street lamp and the
  avatars' `paint_rgb` were changed only in the latter), and `import_assets.py` rewrites the out-dir manifest from
  the source one even with `--only`. Restore the committed manifest after an import (`git show
  HEAD:assets/models/manifest.json`); the car entries need no change when the names stay the same.
- `repo/assets/models` files can be hard-linked into a leftover `stage_candidate/` (or a private `cp -al` stage):
  `import_assets.py` writes in place and changes every link. Import into a temp dir and copy with `cp
  --remove-destination`, or check `find -samefile` first.

**In game** (private stage `stage_carera` = `repo/stage` with the five models swapped in; `gamerun/grun.sh` +
`keys_car_models_sheet.sh`, `MODELS=64,16,47,48,83,10,12`, `GTA2DX9_SCENE_NO_CAR=1`, `SHEET_XY=164.5,149.2
FACE_XY=180,149.4`, runs `carera_after` and `carera_after2`). Verified: all five load (`models: 047_meteor ...
0.50 x 0.31 x 0.98 blocks, faces +z`, no model or texture read errors, no `FAULT`); the wheel split finds four wheels
on the CARI axles (047: axles 0.24/-0.21 = CARI); every model drives nose first in the traffic queue on the
Downtown carriageway, the 064 tractors in the far lanes, 016 Minis, 047 and 048 coupes in the near lane, and an 083
ran the player over (the WASTED frame shows its stripe and wire wheels from a metre away). The `force_car_model`
key is re-read about once a second, so each `drv_model_NNN` frame can still show the previous model; the
first-person `drv_fp_model_NNN` frames, taken a second later, are the reliable ones. Not done: an in-game "before"
run of the same spot (the offline before/after render stands in for it), a Remix take of the five, the release
cars archive (`tools/pack_release.py ... cars`) and the restage of the play page, which take the models from
`assets/models`.

Open: the projected sprite roof keeps the sprite's paint where it is lighter than the body (the 016 Mini drives
with a tan roof over green flanks, as the old model did); 003 Pacifier still reads as a modern armoured car.

Sheets: `out/carera/fleet_before.png`, `out/carera/fleet_after.png` (all 60 generated models, 3/4 front, offline
render), `out/carera/car_era_sheet.png` (per model: sprite | shipped before | round 8 3/4 and side | in-game
traffic crop), frames in `out/carera/after1/`, `out/carera/after2/`.

## Round 9: identity against the sprite (9 Nov 2026, ASSET-VEHICLES)

Goal: each model reads as a street-level interpretation of *that* GTA2 vehicle (silhouette, proportions,
distinctive features, livery from its top-down sprite), not a generic car of the era. Method: an identity sheet
of all 60 generated models beside their sprites (`tools/vehicle_identity_sheet.py`: sprite in the default paint
and one remap | top view at the sprite's orientation, nose-down | 3/4 front | side; `out/asset_vehicles/
identity_before.png`), judged by eye. Seven models were furthest from their sprite:

| Model | Sprite shows | Shipped (round 5/6) | Round 9 brief -> pick | Total |
|---|---|---|---|---|
| 003 Pacifier | boxy olive armoured car, two hatch rings, rear stacks | modern MRAP with remote turret | 1956 Alvis Saracen-style armoured car -> `r9B93` | 0.871 |
| 004 G4 Bank Van | blue armoured box, white roof, two round roof discs | navy streamlined 1930s van | 1950s Brinks-style armoured van, white roof -> `r9C91` | 0.916 |
| 005 Beamer | rounded fastback body, big oval dark glasshouse, fender bulges | boxy 1960s BMW 2002 | 1957 BMW 507 hardtop / 503 -> `r9C91` | 0.875 |
| 019 GT-A1 | low mid-engined racer: stripes, roof disc, rear louvres | Jaguar E-type (front-engined) | 1965-66 Ford GT40 with white stripes -> `r9A93` | 0.926 |
| 022 Armed Land Roamer | jeep, white star on the bonnet, dark rear | Willys jeep without star | WW2 Willys with star and gun -> `r9B91` | 0.830 |
| 052 SWAT Van | white/grey body, dark blue stripes, light bars | plain light-blue box truck | 1960s police armoured truck, white over navy, light bar -> `r9A93_s2` | 0.818 |
| 071 Rumbler | muscle car with twin white stripes nose to tail | brown Charger, no stripes | 1969 Road Runner with twin stripes -> `r9C93` | 0.913 |

Pipeline as round 8 with `r9` copies (in `gen3d/`, outside git; copies of the three scripts in
`out/asset_vehicles/`): `concepts_r9.py --models 3,19,22,71,4,52,5 --seeds 3 --seed0 91` (3 wordings x 3 seeds,
63 SDXL tries, `concept/r9try/`), `r9_jobs.py picks.json jobs.json --seed2` + `run_trellis.py --jobs` (25
candidates), `fit_r9.py` (round-6 fit, nose check, scorer; `models3d_r9/fit|proof`, `r9_status.json`), picks by
eye from `out/asset_vehicles/cand_NNN.png` (sprite | shipped | each candidate from top, 3/4, side, 3/4 rear).
Everything on the generation GPU under `flock /tmp/gta2-gen.lock`. Old GLBs in `models3d_r9/old_shipped/`,
picks in `models3d_r9/chosen/` and over `models3d/`. Import: a 7-entry manifest (`assets-src/manifest_r9.json`)
imported into a temp dir and copied into `assets/models` with `cp --remove-destination` (the files had 31 hard
links into stages); only the seven `imported` report entries of `assets/models/manifest.json` change (vertex
counts). `paint_rgb` is measured from the sprite, so the car entries are unchanged.

Rejected on sight: 003 `r9B91` (open-topped, rear tub reads as a pickup), `r9B93_s2` (tilted, black rear); 019
`r9A91`/`_s2`/`r9C91` (dark red, roof disc lost); 022 `r9C91` (RAF roundel instead of the star), `r9C92` (gun
breaks into spikes); 052 `r9B93` (VW bus body doubled), `r9C93` (Land Rover, too small for the 40x83 px box); 071
`r9A93`/`_s2` (dark, stripes only on the bonnet); 004 `r9C93` (cab-over, darker sides); 005 `r9A91` (upright
1950s saloon: right class, wrong silhouette).

**In game** (private stage `stage_av` = `repo/stage` with the seven models swapped in;
`linux/docker/av_grun.sh` = `grun.sh` pinned to `GTA2_GPU`, `keys_car_models_sheet.sh`, `MODELS=3,4,5,19,22,52,
71,47`, `INI_SED=s/^scene_key=.*/scene_key=F11/` + `-e SCENE_KEY=F11` (without it the warp silently fails),
`GTA2DX9_SCENE_NO_CAR=1`, `SHEET_XY=164.5,149.2 FACE_XY=180,149.4`, run `av_r9_ingame2`). Verified: all seven load
(`models: 003_pacifier ... 0.75 x 0.91 x 1.33 blocks, faces +z` ... `071_rumbler ... 0.50 x 0.33 x 1.00`), 0
`FAULT`, no model or texture read errors; each drives nose first in the Downtown traffic queue and is identifiable
from the first-person frame: the GT40 by its twin stripes and roof disc, the jeep by the bonnet star, the SWAT
truck by its roof light bar (beacons lit), the Rumbler by its stripes, the bank van by its white roof.
Sheet: `out/asset_vehicles/vehicle_identity_r9_sheet.png` (per model: sprite | old top, 3/4 | new top, 3/4 |
in-game crop); frames `out/av_r9_ingame2/drv_*model_NNN.png`.

Still wrong (honest list):
- 003: the new hull narrows to a pointed nose seen from above, where the sprite is a rectangle with two hatch
  rings; it has one turret instead of two hatches. Better era and bulk than the MRAP, not yet the sprite's plan.
- 071 and 019 bake a red/orange body; the runtime tint moves it with the remap but the queue of forced 071s in
  game was all red, not the sprite's copper. The sprite's stripe over the 071 roof is not on the model (stripes
  on bonnet and boot only).
- 005 is a two-door coupe; GTA2's Beamer has four door slots (doors animate on the CARI positions anyway).
- 052: garbled side lettering and red wheels from the concept.
- Remix: the new textures have new hashes, so the 8 Nov car PBR maps (`REMIX-CARPROPS-PBR`) do not
  apply to these seven until they are regenerated; no path-traced frames were taken.
- Not done: restage of the play page and the release cars archive (both take the models from `assets/models`;
  the next `restage.sh` picks them up). The other 53 models were judged recognisable enough on the identity sheet;
  next candidates by eye: 021 Garbage Truck (orange tank vs the sprite's ribbed brown hopper), 029 Dementia
  (Isetta egg vs the sprite's longer one-box body), 069 U-Jerk Truck.

## Round 10: four more identity regenerations (9 Nov 2026, ASSET-VEHICLES-10)

Same pipeline and `tools/vehicle_identity_sheet.py` as round 9; GPU 2 under `flock /tmp/gta2-gen-gpu2.lock`. Targets: the
next three the sheet ranked worst (021, 029, 069) and a retry of 003. Scripts: `tools/vehicle_r10/` (`concepts_r10.py` =
the briefs, `r10_jobs.py`, `fit_r10.py`, `picks.json`; they run from `gen3d/` outside git like the earlier rounds).
36 SDXL concepts (4 models x 3 wordings x 3 seeds, `concept/r10try`), 16 TRELLIS candidates, picks by eye.

| Model | Sprite shows | Shipped before | Round 10 brief -> pick | Total |
|---|---|---|---|---|
| 003 Pacifier | boxy rectangular hull, two hatch rings side by side, rear stacks | Saracen-style, hull narrowing to a point | V-100 Commando / rectangular riot truck -> `r10C102_s2` | 0.837 |
| 021 Garbage Truck | brown cab, long open rear hopper with a black ribbed grille | orange tank body, green cab | 1950s refuse truck, ribbed hopper, rusty brown -> `r10A101` | 0.906 |
| 029 Dementia | Isetta egg, long tan fabric roof | white Isetta with a small roof | Isetta with a long canvas roof, cream/copper -> `r10A103` | 0.939 |
| 069 U-Jerk Truck | tan cab, dark slatted box over the bed | 1930s open flatbed, grey cab | Model AA, tan cab, slatted bed -> `r10B101` | 0.770 |

Rejected on sight: 003 `r10B102` (stubby box with a ramp nose and a long gun), `C101` (cab-over box, doors hang open);
021 `C101`/`C102` (open tipper, the hopper reads as a dump truck); 029 `C101` (open side window hole), `C102` (all copper but
no roof panel); 069 `B102`/`B102_s2` (concept was a REAR view: TRELLIS made the box face the front, the nose check cannot
catch it because it compares against the same rear view; do not feed a rear-view concept), `A101` (light wooden bed).

In game (private stage `stage_av10` = `stage_av` with the four models swapped in; `gamerun/av_grun.sh`, `GTA2_GPU=2`,
`keys_car_models_sheet.sh`, `MODELS=3,21,29,69`, same env as round 9, run `av10_ingame`): the four load (`models: 003_pacifier
... 0.75 x 0.79 x 1.33 blocks, faces +z`, 021 `0.56 x 0.81 x 1.34`, 029 `0.41 x 0.44 x 0.69`, 069 `0.50 x 0.58 x 0.88`), 0 `FAULT`,
no model/texture read errors; each shows up in the third-person scene and drives nose first (frames `drv_model_NNN.png`,
`drv_fp_model_NNN.png`). Sheets: `out/asset_vehicles/vehicle_identity_r10_sheet.png` (sprite | old | new) and
`vehicle_identity_r10_ingame.png` (third-person crops).

Still wrong:
- 003 still has one roof turret with a gun, where the sprite has two plain hatch rings and no weapon; the plan view is now a
  rectangle with a hatch ring, the cab is a truck cab rather than the sprite's low glazed front.
- 021: the roof grille is nearly black from above (reads as a dark slab, not the sprite's tan bins); the hopper is boxy.
- 029: the paint is cream with a dark brown roof; the runtime remap tints it, the sprite's tan roof panel is not matched.
- 069: the bed is slatted wood, not the sprite's black louvred box; the cab is rounder.
- Remix PBR maps are not regenerated for these four; no path-traced frames. Not restaged: the next `restage.sh` takes the
  models from `assets/models` (the four `.mesh` and `_0`/`_0_paint` textures were replaced there with `cp --remove-destination`).
  Models stay out of git.

## Round 11: the four round-10 leftovers (9 Nov 2026, ASSET-VEHICLES-11)

Same pipeline and sheet as round 10, GPU 2 under `flock /tmp/gta2-gen-gpu2.lock`. Scripts: `tools/vehicle_r11/`
(`concepts_r11.py` briefs, `r11_jobs.py`, `fit_r11.py`, `picks.json`, `manifest_r11.json`, plus `car_models_close.py` /
`keys_car_models_close.sh`, the round-10 model sheet script with an extra `close_model_NNN` frame taken when the car is
within ~2.4 blocks of the camera). Rules kept from round 10: 36 SDXL concepts (4 models x 3 wordings x 3 seeds,
`concept/r11try`), only FRONT three-quarter or front concepts go to TRELLIS (no rear view; the 069 B102 mistake), 16
TRELLIS candidates, picks by eye. The negative prompt now also carries `turret, gun barrel, cannon`.

| Model | Round 10 problem | Round 11 pick | Total |
|---|---|---|---|
| 003 Pacifier | one turret with a gun, truck cab | olive boxy armoured van, glazed cab, flat roof with two plain hatches -> `r11A112_s2` | 0.851 |
| 021 Garbage Truck | roof grille near-black from above | rusty brown refuse truck, tan bins and ribbed hopper -> `r11A111` | 0.887 |
| 029 Dementia | cream with a dark roof | tan one-box with a tan roof -> `r11A111_s2` | 0.876 |
| 069 U-Jerk Truck | plain wood bed | Model AA, tan cab, black louvred box bed -> `r11A112` | 0.881 |

The 003 roof comes from the sprite (`--roof-only`), so the two hatches are the sprite's; the hull has no weapon. 029: the
TRELLIS mesh came with a flat black base plate under the car (visible as a dark wedge at the wheels in game); I removed
the faces lying flat at ground level (107 of 4246 triangles, `trimesh`, before the import) and re-ran the game check. 069:
the stale `"forward": "-z"` of the old model was dropped from the manifest entry (the fit already turns the new mesh to +z;
the log says `faces +z`). Rejected on sight: 021 `A112` (fitted upside down), 029 `B111` (grey, a floor plate in the texture),
029 `A113` (dark body), 069 `B112`/`C112` (red bed, no black box). Old GLBs: `models3d_r11/old_shipped/`.

Checked in game (private stage `stage_av11` = `repo/stage` copy with the four models swapped, `av_grun.sh`, `GTA2_GPU=2`,
`MODELS=3,21,29,69`, `GTA2DX9_SCENE_NO_CAR=1`, `GTA2DX9_LOG_VEHICLES=1`, runs `av11_ingame`, `av11_ingame29`): all four load
(`003 0.75 x 0.72 x 1.33`, `021 0.56 x 0.73 x 1.34`, `029 0.41 x 0.44 x 0.69`, `069 0.50 x 0.51 x 0.88`, all `faces +z`),
0 `FAULT`, no model/texture read errors. Frames: `drv_close_model_NNN.png` (car at the camera), `drv_model_NNN.png`,
`drv_fp_model_NNN.png`; sheets `out/asset_vehicles/vehicle_identity_r11_sheet.png` (sprite | old | new) and
`vehicle_identity_r11_ingame.png`.

What reads right now: 003 is a green armoured van with a flat sprite roof carrying two plain hatches; 021 from above shows
the tan bins instead of a black slab; 029 is tan with a tan roof; 069 has a dark slatted box over the bed (from above it is
black and louvred like the sprite).
Still not matching: 003's cab is a Land-Rover-style van front (the sprite has a low wide glazed front); 029 is a boxier
one-box van than the sprite's egg; 069's box sides look red-brown with light stripes from behind rather than black; 021's
hopper is a plain box. Not done: Remix PBR maps for these four, path-traced frames, restage (the models are in `assets/models`
for the next `restage.sh`; `assets/models/manifest.json` vertex counts of these four entries not refreshed). Models stay out of git.

## Soft paint masks (9 Nov 2026, FIX-CAR-RENDER)

Defects pm2-car-body-paint-posterised-jagged-black-patches-hanging-wheel and
pm3-third-sedan-roof-and-rear-window-torn-posterised: a car whose live paint was far from the
model's own (a dark remap over the pale 040 Maurice, a burning car's scorch) showed two flat tones
with single-texel stair-steps and speckle on its flanks, roof and rear window. Cause: the importer's
`paint_split` (`tools/import_assets.py`) is a binary texel mask from a hue/saturation threshold,
drawn as two alpha-tested halves; only the paint half took the tint, so every texel the threshold
missed (shaded paint, pale highlights, noise) stayed in the model's own colour beside it.

Renderer fix (`dll/src/model_store.cpp`, no asset change): when a car's `0NN_*_paint.tga` is read,
its alpha becomes an 8-bit coverage: the binary mask, widened by chroma similarity to the mask's
median paint chroma (and, for a coloured paint, by lying along the same hue direction, which takes
in its pale highlights and dark shadows), weighted by brightness (chroma is noise near black), then
blurred twice with a 3x3 box. The car is then one draw of the paint half (the rest half is skipped):
stage 1 puts lit texel x 2 x factor in TEMP, stage 2 lerps from the lit texel toward it by the
coverage, so colour = texel x lerp(1, tint, coverage), opaque. Wear and fire (`car_bodies.cpp`)
now darken the whole body through the material instead of the paint tint alone.
`[renderer] car_paint_soft_mask=1` (default); 0, a device without D3DTA_TEMP/LERP, or Remix keep
the alpha-tested pair (Remix untested with soft masks, so it is never given them). The log says
`models: soft car paint masks on|off (...)` once. Pale parts of a model's own texture that the
widened mask still does not take (the 040 Maurice's pale lower rear) are the model's art: a repaint
leaves them in the model's colour, now with soft borders (ASSET-VEHICLES, issue #2).

### Dark paint floor (pm3-dark-vehicle-bodies-flat-black-unlit)

A near-black remap (box trucks, dark sedans) multiplied the paint to almost nothing: the side of a
box truck measured 3.5-8.4 mean luminance (0-255) in daylight, a hole in the frame. `car_bodies.cpp`
now holds the live paint's luminance at a floor before it becomes the tint (hue kept;
`[renderer] car_paint_floor_percent=30`, 0 off) and gives a dark body a broader, sky-tinted
specular (power 26 -> 12, specular up to 0.95/1.0/1.1 in blue) and a little more ambient (up to
1.3x), scaled by how far the paint is under 100/255. Liveries keep their own paint. QA probe:
`[devtools] force_car_paint=R,G,B` paints every non-livery car (also the models `force_car_model`
draws). Measured with `force_car_model=7 force_car_paint=18,18,22`, keys_pm4.sh in Industrial: box
side 3.5 / 8.4 before (floor 0, binary mask), 25.1 / 28.2 after, panel edges and a roof highlight
visible (runs `out/fixcar_dark_b6`, `out/fixcar_dark_a4`).

### Models 82-86 are cars, not wrecks; near-black faces dropped from the seat (pt-fp-cab-jagular-xk-torn-black-shards)

`car_bodies.cpp` took every CARI model number from 72 up for a burnt-out wreck (`modelNumber < 72` /
`>= 72`). Only 72..81 are wrecks; 82..86 (Jagular XK, Furore GT, the special agent car, ...) are
whole cars, so they got no cab from the driver's seat, no eye over the bonnet, no dents, wheel split
or doors. `WreckModelNumber()` now tests 72..81. With it the XK from the seat has the sports cab
(log `cab interior of model 82: sports class`), its wheels turn and it dents.
The seat's hood copy also drops faces whose texture is near black (mean under 16/255 around the
face's UVs, from a 64x64 CPU copy of the texture, `ModelTextureSample`) where it is not paint:
an image-to-3D shell maps its inner wings, cowl and engine-bay walls onto the atlas's black
background, and from the seat they read as torn black shards past the dash (046 Stinger: 5040 of
15394 triangles of its dented copy; 082: 514 of 8104). Not for a model whose own paint is dark
(paint_rgb luminance under 50). `[devtools] hood_drop_dark=0` keeps them for A/B checks.
Open: the XK's bonnet centre is still missing from the seat (two green fender ribbons), with or
without the dark-face drop: its faces fail the facing test (vertex normals), model 082 for
ASSET-VEHICLES. No sweep of every model from the seat was made.

## Authored bodies: 036 Schmidt, 008 Bug, 056 Taxi (9 Nov 2026, VEHICLE-ART-2)

The owner judged the 3D cars "really poor"; the review (`docs/vehicle-art-review.md`) ranks 036, 008 and 056 fourth to
sixth by how often they are on screen in Downtown. Their image-to-3D shells (lumpy 5-8k face hulls, one baked
texture: the Schmidt with no canopy and an open hole into the seats, a faceted Bug bonnet, a torn chequer blotch on the
Taxi) were replaced by bodies modelled in code, `tools/vehicle_art2/` (VEHICLE-ART-1 does 063/068/013 the same way in
`tools/vehicle_art/`).

- `carkit.py`: every panel is a parametric surface S(u, v) with analytic-quality normals (smooth, no facets);
  triangles are cut exactly along material regions given as signed distance functions in (u, v), so a window, seal,
  rub strip or chequer band has a smooth edge on the shell. Wheels are surfaces of revolution (tyre with sidewall bulge
  and tread texture, rim, domed hub cap, whitewall on the taxi) at marker nodes `wheel_fl/fr/rl/rr` (the renderer's
  wheel split turns and steers them). Lamps (fluted lens in a chrome bezel), tube bumpers and over-riders, a dark
  interior shell with seats behind the glass, wheel-well liners. Ambient occlusion is ray cast per texel (open3d) into
  the paint textures. All textures are generated (no game or third-party art).
- `car_036.py`: a tandem bubble car (KR200 idiom) from the sprite: front deck with a chrome spine and two lamps, a glass
  teardrop canopy with a hoop between the seats and a spine, tail fins with red lamps. `car_008.py`: a Beetle with
  separate fenders sweeping into running boards, lamps in the front fenders, blade bumpers, a chrome strip and handle
  down the front lid, engine-lid louvres, a small rear window. `car_056.py`: a 1950s four-door cab in the sprite's cab
  yellow with the sprite's roof (a chequer strip down the middle, the TAXI sign box on it), a straight chequer band
  along each side, paired lamps either side of a chrome grille, wraparound bumpers, whitewalls.
- Paint: the tinted cars (036, 008) paint a neutral 235 base and carry `paint_rgb` 235 in the manifest. The renderer's
  tint is live paint / model paint, and the model paint is 235 for every car today (`model_store.cpp` reads
  `paint_rgb` only from the "imported" report entries, which do not carry it; noted on
  `assigned/pm17-ste-player-car-violet-in-classic-wine-red-in-3d.md`), so these bodies show exactly the sprite's live
  colour, and stay right if that parse is ever fixed. The taxi is a livery (untinted).
- Renderer (`model_store.cpp` `CarSurfaceFor`, car textures only): a texture named `*_glass*` is drawn blended
  (src alpha), z-write off, after the rest of the body; `*_chrome*` gets a tight bright highlight (power 60);
  tyres, seals, underbody, interior, seats and rubber a dull one. Image-to-3D cars have no such names and draw as before.
- Build: `gen3d/venv/bin/python tools/vehicle_art2/build.py <out> 036 008 056 --preview` writes the glb + material
  PNGs and imports them into `<out>/models` (copy into `assets/models` with `cp --remove-destination`; models stay out
  of git; sources in `assets-src/cars/vehicle_art2/`). `make_car_manifest.py` now keeps any entry with a
  `generator` as it is. 14.5k / 15.6k / 18.5k vertices, 14-19 meshes each.
- In game: `tools/vehicle_art2/show.py` (copy of `gamerun/va2_show.py`, keys `keys_va2_show.sh`): at the Downtown
  carriageway, every traffic car forced to the model in the sprite's default paint, the regression camera
  (`GTA2DX9_REGRESS_CAM`) set to front 3/4, side, rear 3/4, eye height, close, high and chase poses around the nearest
  car. Runs `out/va2_show_b3` (before, HEAD 46164d3 with the old models) and `out/va2_show_n3` / `n4` (after); sheets
  `out/va2_review/before_after_NNN.png`, offline previews `out/va2_review/preview_NNN.png`. 0 FAULT, no model or
  texture read errors; the wheel split finds the four marker wheels.

Still short of a shipping AAA frame (honest list): fixed-function vertex lighting with no environment reflection
(the paint has a highlight but no sky reflection; chrome and glass reflections are baked); window glass is a flat
tint with baked streaks, the cabin behind it is a dark shell with box seats; no panel gaps in geometry (painted lines);
the Schmidt's fins read a little like horns from the rear 3/4; the open door's inner face is black (the door split
copies the outer skin); the Bug and Schmidt are about 10 % lower than a person-scaled real car (footprint at 5 m a
block); no Remix PBR for the new textures (new hashes) and no path-traced frames; the first-person seat view with
these bodies was not filmed (force_own_car_model) in this pass.

### Wrecks are the burnt-out car they were (VEHICLE-ART-3, vr-wrecks-flat-dark-pancakes-no-car-shape)

The ten wreck models 72..81 were parametric pancakes (a hull a third of a car high with the wreck sprite smeared
over it). The game turns a blown-up car into one of them: the CARI wreck byte of each whole model names the class
(sedans 74, saloons 75, vans 80, trucks 79, truck cabs 73, the 128-long buses/trains 72, limousines 76, the
Jefferson 77, micro cars 78, the tank 81) and the classic view draws that class's wreck sprite. Now:

- `identity.cpp` (the sole resolver) remembers each vehicle's whole model number while it is whole
  (`SpriteRef::wholeModel`, the game's own number, never a devtools override) and resolves a wreck to the charred
  copy of that model (`IdentityRecord::wreck`, `wreckOf`). The class must match (`IdentityWreckClassOf`, the CARI
  table), so a sprite object the game reuses for another car is not taken for it. A wreck never seen whole (a
  mission's parked wreck, a car that blew up off screen, `force_car_model=72..81`, `wreck_models=1`) gets its
  class's stand-in (`IdentityWreckStandIn`: 011 Bus, 063, 000 Romero, 013 Minx, 032, 031, 036, 007, 067, 054).
  The log line says which: `identity: vehicle CHANGED model 73 ... -> 063_truck_cab#wreck livery (wreck of this
  car's own model)` or `(wreck: the class's stand-in)`.
- `car_bodies.cpp` `CarWreckCopyOf` / `BuildWreck`: the model's worst dent step, the cabin sagged toward the waist
  (everything above half height pressed down, the roof's middle most: the copies are 76-80 % of the car's height),
  x and z untouched (the footprint is the car's, inside the game's wreck box; the draw fits it to the wreck sprite's
  footprint as before), the paint split merged into one opaque surface, every texture renamed `wreck|<file>`
  (`wreckp|` for the rest half of a paint pair). The copy is made while the car burns (fire stage 3, damage 16000 on;
  one texture a frame, and its glass masks are asked for), so the explosion frame does not build it.
- `model_store.cpp` `FillCharred`: the charred texture keeps the source texel's luminance (panel lines, grille,
  wheels) over a burnt palette measured from the wreck sprites (mean 32,25,20): soot 22,19,17, umber rust 64,40,21
  in blotches, grey ash in the troughs; `_chrome` goes smoky grey, rubber stays black; glass burns out to near
  black: `_glass` textures, and on the generated bodies the windows VEHICLE-GLASS finds (`CarGlassMaskForTexture`;
  a copy made before its mask is refilled once the mask is in). No paint stage (the record is a livery), a matte
  material, no lamps, glass pass, cabin or wheel spin (the existing wreck branches still key on the model number).
- Classic view: untouched (wrecks are the game's sprites there; nothing here runs in it).

Still short of a shipping AAA frame: the wreck keeps the car's panels whole (no torn-open bonnet, no missing doors,
no exposed seat springs or engine); the rust/soot is a UV-space blotch field, so blotch edges follow the texture
charts on the image-to-3D bodies; the windows of 063 and other bodies whose glass VEHICLE-GLASS does not find stay
body-coloured soot; no smoke or ember decals after the fire dies; under Remix the charred textures are new hashes with
no PBR replacement (roughness from the default material); the stand-ins are one model per class, so two parked wrecks
of a class look alike.
