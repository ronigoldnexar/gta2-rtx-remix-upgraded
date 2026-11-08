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
