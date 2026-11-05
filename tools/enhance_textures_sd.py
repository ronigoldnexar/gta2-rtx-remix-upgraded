#!/usr/bin/env python3
"""Realistic high-resolution versions of GTA2's 64x64 tiles with Stable Diffusion.

Three steps, each a subcommand:

  extract  <style.sty> <out dir>          the tiles out of a GTA2 style file, as
                                          tile_%04d.tga (64x64, 32-bit) - the same
                                          numbering the renderer's own dump and
                                          gta2dx9_textures_hd/ use.
  enhance  <tiles dir> <out dir> [opts]   SD 1.5 img2img with ControlNet Tile: each
                                          tile is upscaled, then re-rendered with a
                                          texture prompt at low denoising strength so
                                          its structure (road markings, kerbs, brick
                                          courses) survives while real detail is
                                          added. One process per GPU.
  sheet    <tiles dir> <out dir> <png>    a before/after contact sheet.

Seamlessness: the tiles repeat across the map, so the UNet's and VAE's convolutions
are switched to circular padding, which makes the generated detail wrap round the
tile edges exactly as the source does.

Models (downloaded from Hugging Face on first use):
  stable-diffusion-v1-5/stable-diffusion-v1-5   CreativeML OpenRAIL-M licence
  lllyasviel/control_v11f1e_sd15_tile           Apache-2.0
Output textures inherit SD 1.5's OpenRAIL-M use restrictions; see the model card.
"""
import argparse, os, struct, sys, time

TILE = 64
PAGE = 256
TILES_PER_PAGE = 16
PAL_PAGE_BYTES = 256 * 64 * 4

# ----------------------------------------------------------------------------
# extract
# ----------------------------------------------------------------------------
def read_u16(b, o): return struct.unpack_from("<H", b, o)[0]
def read_u32(b, o): return struct.unpack_from("<I", b, o)[0]

def style_tiles(path):
    """Yields (index, bytes RGBA 64x64) for every tile of a GBST style file, decoded
    the way the renderer's parser does it (src/gta2_style.cpp)."""
    data = open(path, "rb").read()
    assert data[:4] == b"GBST", "not a GBST style file"
    off = 6
    chunks = {}
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin-1"); size = read_u32(data, off + 4)
        chunks[tag] = (off + 8, size); off += 8 + size
    tile_off, tile_size = chunks["TILE"]
    pal_off, _ = chunks["PPAL"]
    palx_off, palx_size = chunks["PALX"]
    pages = tile_size // (PAGE * PAGE)
    for index in range(pages * TILES_PER_PAGE):
        page, slot = divmod(index, TILES_PER_PAGE)
        pixel_base = tile_off + page * PAGE * PAGE + (slot // 4) * TILE * PAGE + (slot % 4) * TILE
        palette = read_u16(data, palx_off + index * 2) if index * 2 + 2 <= palx_size else 0
        pal_base = pal_off + (palette // 64) * PAL_PAGE_BYTES + (palette % 64) * 4
        out = bytearray(TILE * TILE * 4)
        blank = True
        for y in range(TILE):
            row = pixel_base + y * PAGE
            for x in range(TILE):
                ci = data[row + x]
                o = (y * TILE + x) * 4
                if ci == 0:
                    out[o:o + 4] = b"\0\0\0\0"
                else:
                    c = pal_base + ci * 256
                    out[o:o + 4] = bytes((data[c + 2], data[c + 1], data[c], 255))
                    blank = False
        if not blank:
            yield index, bytes(out)

def write_tga(path, rgba, w, h):
    rows = [rgba[y * w * 4:(y + 1) * w * 4] for y in range(h)][::-1]
    body = bytearray()
    for row in rows:
        for i in range(0, len(row), 4):
            body += bytes((row[i + 2], row[i + 1], row[i], row[i + 3]))
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(body)

def read_tga(path):
    from PIL import Image
    return Image.open(path).convert("RGBA")

def cmd_extract(args):
    os.makedirs(args.out, exist_ok=True)
    n = 0
    for index, rgba in style_tiles(args.style):
        write_tga(os.path.join(args.out, f"tile_{index:04d}.tga"), rgba, TILE, TILE)
        n += 1
    print(f"{n} tiles from {args.style} -> {args.out}")

# ----------------------------------------------------------------------------
# enhance
# ----------------------------------------------------------------------------
def describe(im):
    """A prompt from the tile's own colours: the style file says nothing about
    what a tile is, but its palette gives the material away well enough."""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(float) / 255.0
    r, g, b = a[..., 0].mean(), a[..., 1].mean(), a[..., 2].mean()
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    sat = (a.max(-1) - a.min(-1)).mean()
    edge = float(np.abs(np.diff(a.mean(-1), axis=0)).mean() + np.abs(np.diff(a.mean(-1), axis=1)).mean())
    if g > r * 1.15 and g > b * 1.15 and sat > 0.15:
        return "photorealistic grass and soil ground texture"
    if b > r * 1.2 and b > g * 1.05:
        return "photorealistic water surface texture, ripples"
    if sat < 0.12 and lum < 0.35:
        return "photorealistic asphalt road surface texture, fine aggregate"
    if sat < 0.15 and lum >= 0.35:
        return "photorealistic concrete pavement texture, weathered"
    if r > g * 1.15 and r > b * 1.3:
        return "photorealistic brick wall texture, mortar joints"
    if edge > 0.12:
        return "photorealistic building facade texture, windows and masonry"
    return "photorealistic urban surface texture"

def make_circular(module):
    import torch
    for m in module.modules():
        if isinstance(m, torch.nn.Conv2d) and m.padding[0] > 0:
            m.padding_mode = "circular"

def worker(gpu, files, src, out, opts):
    import torch
    from PIL import Image
    from diffusers import StableDiffusionControlNetImg2ImgPipeline, ControlNetModel, DDIMScheduler
    torch.cuda.set_device(gpu)
    dtype = torch.float16
    controlnet = ControlNetModel.from_pretrained("lllyasviel/control_v11f1e_sd15_tile", torch_dtype=dtype)
    pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
        "stable-diffusion-v1-5/stable-diffusion-v1-5", controlnet=controlnet, torch_dtype=dtype,
        safety_checker=None, requires_safety_checker=False)
    pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    if opts.seamless:
        make_circular(pipe.unet); make_circular(pipe.vae); make_circular(pipe.controlnet)
    pipe = pipe.to(f"cuda:{gpu}")
    size = opts.size
    gen = torch.Generator(device=f"cuda:{gpu}")
    t0 = time.time(); done = 0
    batch = opts.batch
    for i in range(0, len(files), batch):
        names = files[i:i + batch]
        srcs = [read_tga(os.path.join(src, n)) for n in names]
        # Alpha: the cutout stays what it was, upscaled nearest; SD sees the colour only.
        alphas = [im.split()[3].resize((size, size), Image.NEAREST) for im in srcs]
        rgbs = [im.convert("RGB").resize((size, size), Image.BICUBIC) for im in srcs]
        # The control image keeps the hard pixel structure; the init image is the soft one.
        controls = [im.convert("RGB").resize((size, size), Image.NEAREST) for im in srcs]
        prompts = [describe(im) + ", high detail, PBR albedo, seamless, top-down, photo" for im in srcs]
        gen.manual_seed(opts.seed)
        result = pipe(prompt=prompts, negative_prompt=["blurry, cartoon, text, watermark, people, vehicles"] * len(names),
                      image=rgbs, control_image=controls, strength=opts.strength, num_inference_steps=opts.steps,
                      guidance_scale=opts.guidance, controlnet_conditioning_scale=opts.control, generator=gen,
                      output_type="pil").images
        for n, im, al in zip(names, result, alphas):
            if opts.out_size and opts.out_size != size:
                im = im.resize((opts.out_size, opts.out_size), Image.LANCZOS)
                al = al.resize((opts.out_size, opts.out_size), Image.NEAREST)
            im = im.convert("RGBA"); im.putalpha(al)
            write_tga(os.path.join(out, n), im.tobytes(), im.size[0], im.size[1])
        done += len(names)
    print(f"gpu {gpu}: {done} tiles in {time.time() - t0:.0f} s", flush=True)

def cmd_enhance(args):
    import torch.multiprocessing as mp
    os.makedirs(args.out, exist_ok=True)
    files = sorted(f for f in os.listdir(args.tiles) if f.lower().endswith(".tga"))
    if args.every > 1: files = files[::args.every]
    if args.limit: files = files[:args.limit]
    if args.skip_done: files = [f for f in files if not os.path.exists(os.path.join(args.out, f))]
    gpus = args.gpus
    shards = [files[i::gpus] for i in range(gpus)]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=worker, args=(g, shards[g], args.tiles, args.out, args)) for g in range(gpus) if shards[g]]
    for p in procs: p.start()
    for p in procs: p.join()
    print(f"{len(files)} tiles on {len(procs)} GPUs in {time.time() - t0:.0f} s -> {args.out}")

# ----------------------------------------------------------------------------
# sheet
# ----------------------------------------------------------------------------
def cmd_sheet(args):
    from PIL import Image
    files = sorted(f for f in os.listdir(args.out) if f.lower().endswith(".tga"))
    if args.limit: files = files[:args.limit]
    cell = 128; cols = 8
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell * 2, rows * cell), (40, 40, 40))
    for i, f in enumerate(files):
        a = read_tga(os.path.join(args.tiles, f)).convert("RGB").resize((cell, cell), Image.NEAREST)
        b = read_tga(os.path.join(args.out, f)).convert("RGB").resize((cell, cell), Image.LANCZOS)
        x, y = (i % cols) * cell * 2, (i // cols) * cell
        sheet.paste(a, (x, y)); sheet.paste(b, (x + cell, y))
    sheet.save(args.png); print(args.png, len(files), "pairs")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("style"); e.add_argument("out")
    h = sub.add_parser("enhance"); h.add_argument("tiles"); h.add_argument("out")
    h.add_argument("--size", type=int, default=512); h.add_argument("--out-size", type=int, default=256)
    h.add_argument("--strength", type=float, default=0.3)
    h.add_argument("--steps", type=int, default=24); h.add_argument("--guidance", type=float, default=6.0)
    h.add_argument("--control", type=float, default=1.0); h.add_argument("--gpus", type=int, default=8)
    h.add_argument("--batch", type=int, default=8); h.add_argument("--seed", type=int, default=7)
    h.add_argument("--limit", type=int, default=0); h.add_argument("--every", type=int, default=1)
    h.add_argument("--skip-done", action="store_true")
    h.add_argument("--no-seamless", dest="seamless", action="store_false")
    s = sub.add_parser("sheet"); s.add_argument("tiles"); s.add_argument("out"); s.add_argument("png"); s.add_argument("--limit", type=int, default=64)
    args = ap.parse_args()
    {"extract": cmd_extract, "enhance": cmd_enhance, "sheet": cmd_sheet}[args.cmd](args)
