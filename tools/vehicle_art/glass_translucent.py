#!/usr/bin/env python3
"""VEHICLE-ART-11: translucent glass for the carkit bodies (063 Truck Cab, 013 Minx, 068 Van).

tools/vehicle_art/carkit.py bakes each body's windows into their own draw group ("glass") with its
own atlas (assets-src/cars/models_art/<name>_glass.png: the tinted pane, sky streaks, rubber edge),
and models the cab behind them (an inset liner, seats, dash, wheel). The importer named that
texture by image index (<name>_4.tga), so the renderer drew it opaque: a dark slab over a cabin
nobody could see, and VEHICLE-GLASS's mask pass (car_glass.cpp) then cut stepped holes into the
hull texels it took for glass (pmx11: black sawtooth shards round the truck's window and mirror).

A texture whose name holds "_glass" is drawn blended with z-write off (model_store.cpp
CarSurfaceFor) and marks the body as one with its own glass (car_glass.cpp leaves it uncut). So
this writes <name>_glass_t.png: the baked pane's colours with a constant alpha, lifted a little
toward the sky tint so the pane still reads as glass where the cabin behind it is black; the
manifest maps the "glass" material to it ("material_textures": {"glass": ...}), and the import
writes <name>_glass.tga.

  python3 tools/vehicle_art/glass_translucent.py <assets-src/cars/models_art> <name> [--alpha 0.56]
"""
import argparse, os
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("src_dir")
ap.add_argument("name")
ap.add_argument("--alpha", type=float, default=0.56)
ap.add_argument("--lift", type=float, default=0.15, help="mix toward the sky tint (0 = the baked colours)")
a = ap.parse_args()

src = os.path.join(a.src_dir, f"{a.name}_glass.png")
rgb = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
sky = np.array([118.0, 132.0, 148.0], np.float32)
rgb = rgb * (1.0 - a.lift) + sky * a.lift
alpha = np.full(rgb.shape[:2] + (1,), 255.0 * a.alpha, np.float32)
out = np.concatenate([rgb, alpha], axis=2).clip(0, 255).astype(np.uint8)
dst = os.path.join(a.src_dir, f"{a.name}_glass_t.png")
Image.fromarray(out, "RGBA").save(dst)
print(f"{dst}: {out.shape[1]}x{out.shape[0]}, mean {out.reshape(-1, 4).mean(0).round(1).tolist()}")
print(f'manifest: "material_textures": {{"glass": "cars/models_art/{a.name}_glass_t.png"}}')
