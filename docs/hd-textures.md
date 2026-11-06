# High-resolution tiles: 512 px, block-compressed, in a 32-bit game

GTA2 draws its world from 64x64 tiles. In first person they fill the screen, so this is
where the picture quality is decided. The pipeline below turns every tile a level uses
into a 512 px, mipmapped, block-compressed texture that the game loads in real time.

## Pipeline

1. **Dump** the tiles the level uses: `dump_tiles=1` in `gta2dx9.ini` writes
   `gta2dx9_tiles\<style>\tile_NNNN.tga` (64 px) when the level loads. `<style>` is
   `wil` for Downtown, `bil` for the Residential district, `ste` for Industrial.
2. **Real-ESRGAN x4** (`tools/upscale_textures.py`, CUDA, one process per GPU): a clean
   256 px upscale, run a second time on its own output for 1024 px, wrap-padded so a
   repeating tile stays seamless.
3. **Stable Diffusion 1.5 + ControlNet Tile** (`tools/enhance_textures_sd.py enhance
   <ESRGAN 256 px folder> <out> --size 512 --out-size 512 --strength 0.45 --steps 28`):
   real surface detail (brick courses, mortar, weathering, asphalt aggregate) guided by
   the tile's own pixels, with circular padding in the UNet, VAE and ControlNet so the
   result wraps. Feed it the ESRGAN tiles, not the 64 px originals: from a 64 px init
   SD's 512 px output is soft and grainy, from the 256 px ESRGAN init it is sharp. Then
   run `tools/upscale_textures.py` once more over the SD output (to 2048 px) as a
   sharpening pass; the packer resamples it to 512. All of it takes about four minutes
   for 1 710 tiles on eight B200s.
4. **Select and pack** (`tools/pack_textures_dds.py <64 px dump> <out> --esrgan <1024 px
   ESRGAN> --sd <2048 px SD>`): per tile, the SD rendering wins when it is still faithful
   to the original (SSIM against the 64 px tile >= 0.70 and within 0.12 of the ESRGAN
   upscale) and at least 60 % as sharp (variance of the Laplacian), otherwise the ESRGAN
   upscale is used, so signs, windows and road markings never turn into something else
   and a soft rendering never replaces a crisp one (Downtown: 623 SD, 195 ESRGAN;
   Residential: 614 SD, 278 ESRGAN; Industrial: 550 SD, 292 ESRGAN). The chosen image gets a Lanczos mip chain down to
   1x1 and is encoded DXT1 (DXT5 when the tile has a cutout) into
   `assets/textures_hd/<style>/tile_NNNN.dds`. The selection is logged in `choices.txt`
   and `<style>_sheet.png` shows original, ESRGAN, SD and the decoded DDS side by side.
5. `make stage` ships the folder as `gta2dx9_textures_hd/`; the Linux installer and the
   container runner copy it beside the game.

### Completing the set from the style file (animated tiles)

The in-game dump only sees what the game uploads, and for an animated tile
(water, fans, neon, screens, traffic lights: the map's `ANIM` groups) that is one
frame of several. `tools/dump_style_tiles.py <game/data> <style> <out> --missing
<hd dir>` writes, straight from the style file's `TILE` pages, every tile the map
uses or animates that has no DDS yet (byte-identical to the game's own dump, checked
on tiles 1, 100, 300 and 608), so the pipeline above can be run on those alone. The
100 tiles that were missing across the three districts were all animation frames;
they are packed from the Real-ESRGAN upscale only, not the SD rendering, so the
frames of one animation stay consistent and the water does not flicker. The sets are
now complete: Downtown 846, Residential 930, Industrial 876 DDS.

The renderer plays those animations in high resolution: the frame the game uploads
for an animated tile is recognised by its content hash as "tile N of the style"
(`tileByContent_`, built at level load) and tile N's DDS is shown in its place
(`UpdateTileTexture`), instead of the 64 px frame texture that used to replace the
HD base tile as soon as the animation started.

### Water

In the street views the water tiles (the animated group at tile 608, the same in
every district) are drawn with two layers of tileable noise drifting across each
other (texture stages 1 and 2, signed-added, texture matrices scrolled by the sky's
clock) and then pulled a quarter of the way toward the sky's horizon colour: ripples
and a reflection tint for the cost of two texture stages. `[renderer] water_effect=0`
turns it off; the classic view never uses it.

The ready-made set for all three districts (wil, bil, ste; 2 652 tiles, 570 MB, about 245 MB zipped) is a release asset,
`textures_hd_dds.zip`; unzip it into `gta2dx9_textures_hd/` beside `gta2.exe`.

## Memory, and why DDS

GTA2 is a 32-bit process with a 2 GB address space, and Wine's Direct3D keeps a copy
of every texture it uploads. Uncompressed tiles did not fit above 128 px:

| tile format                     | one tile | 818 tiles (Downtown) |
|---------------------------------|---------:|---------------------:|
| 256 px A8R8G8B8, no mips (old)  |   1.0 MB |              0.8 GB  |
| 512 px A8R8G8B8 with mips       |   1.4 MB |              1.1 GB  |
| 512 px DXT1 with mips           |   175 KB |              143 MB  |
| 512 px DXT5 with mips           |   350 KB |             (cutouts)|

`src/renderer.cpp` reads the DDS, creates a default-pool compressed texture with the
mip count of the file and fills it level by level through a system-memory staging
texture that is released at once. `hd_tile_max` (default 512) skips the levels above
the cap instead of resampling, so a 256 px or 128 px setting costs nothing to switch
to. The log line `hd tiles: N loaded (N block-compressed DDS with mips, cap 512 px),
0 failed` confirms the upload.

`linux/laa.sh` additionally marks the installed copy of `gta2.exe` large-address-aware
(the `IMAGE_FILE_LARGE_ADDRESS_AWARE` bit in the PE header; the original file is never
touched), which gives the process 4 GB under 64-bit Wine. `linux/install.sh` and the
container runner apply it; set `LAA=0` to skip it.

## Filtering

With HD artwork present the world sampler uses linear magnification, anisotropic
minification (8x) and linear mip filtering; without it the game's own 64 px tiles keep
their point-sampled look.

## Measured

Downtown, Wine 9 on CPU (llvmpipe), 1280x720, frame cap 30 fps, `frame times` log:
world draw 0.3 ms before and 0.4 ms after; both runs sit at the cap (`wait 32.0 ms`),
so the 512 px set costs nothing visible at this resolution. 818 of 818 Downtown tiles
loaded at 512 px, none failed. Before/after frames: `out/textures_sheet.png` in the
working folder (first person at the same spot, same key timings).

Industrial was dumped without playing to it: the container runner's `SWAP_LEVEL=ste`
copies `ste.gmp/.sty/.SCR` over Downtown's in the prefix copy, so "level 1" loads the
Industrial district (the renderer detects the style from the map and names the folder
`ste` itself), and `DUMP_TILES=1` switches the dump on for that run. 842 of 842
Industrial tiles loaded at 512 px in the check run (`out/ste_hd`), none failed; frame
cap still met (world draw 0.7 ms, `wait 27.6 ms`). The 3D models' own textures
(assets/models) are already 512 to 1024 px and were left alone. Untested: a real GPU
and RTX Remix with the DDS set.
