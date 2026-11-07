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
