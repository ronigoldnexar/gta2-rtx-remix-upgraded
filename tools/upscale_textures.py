#!/usr/bin/env python3
"""Upscales GTA2's tile artwork 4x with Real-ESRGAN on CUDA GPUs.

    upscale_textures.py <tiles dir> <out dir> [--weights RealESRGAN_x4plus.pth] [--gpus 0,1,2,3]

Input: the 64x64 32-bit TGAs gta2dx9.dll writes to gta2dx9_tiles\\ with
dump_tiles=1 in gta2dx9.ini. Output: 256x256 TGAs, same names, that the
renderer picks up from gta2dx9_textures_hd\\ beside the game.

The network is RRDBNet (23 blocks, 64 features, growth 32), written out here
in plain PyTorch so the only dependency is torch itself; the weights are the
published RealESRGAN_x4plus.pth (BSD-3, github.com/xinntao/Real-ESRGAN).

Alpha is a cutout in GTA2 (one bit): the colour is upscaled by the network with
the transparent texels first filled from their opaque neighbours (so no dark
fringe is learned into the edge), and the alpha is upscaled by nearest
neighbour and kept hard. A tile is padded by wrapping before the network sees
it and cropped after, so a repeating tile stays seamless.

One process per GPU; the tiles are split between them.
"""
import argparse, os, struct, sys, time
import numpy as np

def read_tga(path):
    data = open(path, "rb").read()
    h = data[:18]
    w, hgt, bpp, desc = h[12] | (h[13] << 8), h[14] | (h[15] << 8), h[16], h[17]
    assert h[2] == 2 and bpp == 32, path
    px = np.frombuffer(data, dtype=np.uint8, count=w * hgt * 4, offset=18 + h[0]).reshape(hgt, w, 4)
    if not desc & 0x20: px = px[::-1]          # bottom-up file -> top-down
    return px[:, :, [2, 1, 0, 3]].copy()        # BGRA -> RGBA

def write_tga(path, rgba):
    hgt, w = rgba.shape[:2]
    bgra = rgba[:, :, [2, 1, 0, 3]].astype(np.uint8)
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, hgt, 32, 0x28)   # top-down, 8 alpha bits
    with open(path, "wb") as f:
        f.write(header); f.write(bgra.tobytes())

def build_net(torch):
    import torch.nn as nn
    import torch.nn.functional as F
    class RDB(nn.Module):
        def __init__(self, nf=64, gc=32):
            super().__init__()
            self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1); self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
            self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1); self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
            self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1); self.lrelu = nn.LeakyReLU(0.2, True)
        def forward(self, x):
            x1 = self.lrelu(self.conv1(x)); x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1))); x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x
    class RRDB(nn.Module):
        def __init__(self, nf, gc=32):
            super().__init__(); self.rdb1 = RDB(nf, gc); self.rdb2 = RDB(nf, gc); self.rdb3 = RDB(nf, gc)
        def forward(self, x):
            return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x
    class RRDBNet(nn.Module):
        def __init__(self, nb=23, nf=64, gc=32):
            super().__init__()
            self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
            self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1); self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
            self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1); self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, True)
        def forward(self, x):
            fea = self.conv_first(x)
            fea = fea + self.conv_body(self.body(fea))
            fea = self.lrelu(self.conv_up1(F.interpolate(fea, scale_factor=2, mode="nearest")))
            fea = self.lrelu(self.conv_up2(F.interpolate(fea, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(fea)))
    return RRDBNet()

def fill_transparent(rgb, alpha, passes=8):
    """colour for transparent texels from their opaque neighbours, so the edge the network sees is the artwork's"""
    rgb = rgb.astype(np.float32); known = alpha > 0
    for _ in range(passes):
        if known.all(): break
        acc = np.zeros_like(rgb); cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = np.roll(known, (dy, dx), (0, 1)); c = np.roll(rgb, (dy, dx), (0, 1))
            acc += c * k[:, :, None]; cnt += k
        fill = (~known) & (cnt > 0)
        rgb[fill] = (acc[fill] / cnt[fill][:, None]); known = known | fill
    return rgb

def worker(gpu, files, out_dir, weights, pad):
    import torch
    torch.backends.cudnn.benchmark = True
    dev = torch.device(f"cuda:{gpu}")
    net = build_net(torch).to(dev).eval()
    sd = torch.load(weights, map_location="cpu", weights_only=True)
    net.load_state_dict(sd.get("params_ema", sd.get("params", sd)), strict=True)
    net = net.half()
    t0 = time.time(); n = 0
    with torch.no_grad():
        for path in files:
            px = read_tga(path)
            rgb = fill_transparent(px[:, :, :3], px[:, :, 3]) / 255.0
            alpha = px[:, :, 3]
            # wrap-pad so the edges continue the tile's own pattern
            rgb = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="wrap")
            x = torch.from_numpy(rgb.transpose(2, 0, 1)[None]).to(dev).half()
            y = net(x).float().clamp(0, 1)[0].cpu().numpy().transpose(1, 2, 0)
            y = y[pad * 4:-pad * 4 or None, pad * 4:-pad * 4 or None]
            out = np.empty((y.shape[0], y.shape[1], 4), np.uint8)
            out[:, :, :3] = (y * 255.0 + 0.5).astype(np.uint8)
            a = np.repeat(np.repeat(alpha, 4, 0), 4, 1)
            out[:, :, 3] = np.where(a > 127, 255, 0)
            write_tga(os.path.join(out_dir, os.path.basename(path)), out)
            n += 1
    print(f"gpu {gpu}: {n} tiles in {time.time() - t0:.1f} s", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tiles"); ap.add_argument("out")
    ap.add_argument("--weights", default=os.path.join(os.path.dirname(__file__), "..", "..", "upscale", "RealESRGAN_x4plus.pth"))
    ap.add_argument("--gpus", default="0")
    ap.add_argument("--pad", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    files = sorted(os.path.join(a.tiles, f) for f in os.listdir(a.tiles) if f.lower().endswith(".tga"))
    gpus = [int(g) for g in a.gpus.split(",") if g != ""]
    print(f"{len(files)} tiles on GPUs {gpus}", flush=True)
    import torch.multiprocessing as mp
    mp.set_start_method("spawn")
    procs = []
    for i, gpu in enumerate(gpus):
        chunk = files[i::len(gpus)]
        p = mp.Process(target=worker, args=(gpu, chunk, a.out, a.weights, a.pad)); p.start(); procs.append(p)
    for p in procs: p.join()
    print("done", flush=True)
