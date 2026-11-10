#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-4: paint parity per build (docs/identity-system.md section 9.5).

    python3 tools/paint_parity.py out/<run> [--mode new] [--report table.md]

<run> is a session of linux/docker/keys_paint_parity.sh: frames pt_top_<model>_<paint>_<mode>.png of the player's stopped
car forced to each model and painted (force_car_paint) as a sprite of each paint, seen from the classic camera's pose.
The car's paint pixels are the ones that change between two paints of the same model (the remap rule the sprite's paint
is measured by); their mean is the 3D body's colour, compared with the sprite paint it was given:
  hue      difference in degrees (paints with chroma): FAIL over 15
  lightness CIE L* relative difference: WARN over 10 %, FAIL over 25 % (chromatic mid paints); black and navy (the
           dark-paint floor lifts them on purpose) and white (a lid can not pass white) are reported, never failed.
Exit status: the number of FAILs (capped at 100). Needs numpy and Pillow (the vreg venv).
"""
import argparse, colorsys, glob, os, re, sys
import numpy as np
from PIL import Image

PAINTS = {"red": (133, 65, 65), "navy": (35, 45, 95), "black": (28, 28, 30), "yellow": (200, 180, 50),
          "green": (60, 120, 60), "white": (215, 215, 215), "teal": (60, 93, 102)}
REPORT_ONLY = {"black", "navy", "white"}


def lab(c):
    c = np.asarray(c, float) / 255
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = m @ c / np.array([0.9505, 1, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def load(p):
    return np.asarray(Image.open(p).convert("RGB")).astype(float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--mode", default=None, help="the MODES label (default: the only one in the run)")
    ap.add_argument("--report")
    a = ap.parse_args()
    frames = glob.glob(os.path.join(a.run, "pt_top_*_*_*.png"))
    rx = re.compile(r"pt_top_(\d+)_([a-z]+)_([A-Za-z0-9]+)\.png$")
    have = {}
    for f in frames:
        m = rx.search(f)
        if m: have[(m.group(1), m.group(2), m.group(3))] = f
    modes = sorted({k[2] for k in have})
    mode = a.mode or (modes[0] if len(modes) == 1 else "new")
    lines = [f"# Paint parity: {os.path.basename(a.run.rstrip('/'))} (mode {mode})", "",
             "| Model | Paint | Sprite | 3D body | Lit lids | L* 3D vs sprite | dHue | Saturation 3D / sprite | Result |",
             "|---|---|---|---|---|---|---|---|---|"]
    fails = warns = 0
    for model in sorted({k[0] for k in have}):
        keys = [p for p in PAINTS if (model, p, mode) in have]
        pair = [p for p in ("red", "green", "navy") if p in keys]
        if len(pair) < 2:
            lines.append(f"| {model} | - | | | | | | | SKIP (needs two of red/green/navy for the mask) |")
            continue
        imgs = [load(have[(model, p, mode)]) for p in pair]
        diff = np.max([np.abs(imgs[0] - x).sum(2) for x in imgs[1:]], axis=0)
        mask = diff > 60
        ys, xs = np.nonzero(mask)
        if len(ys) < 200:
            lines.append(f"| {model} | - | | | | | | | SKIP (no car found: {len(ys)} px change) |")
            continue
        cy, cx = np.median(ys), np.median(xs)
        keep = (np.abs(ys - cy) < 220) & (np.abs(xs - cx) < 160)
        mk = np.zeros_like(mask); mk[ys[keep], xs[keep]] = True
        for p in keys:
            s = np.array(PAINTS[p], float)
            px = load(have[(model, p, mode)])[mk]
            mean = px.mean(0); lum = px @ [0.3, 0.59, 0.11]; lit = px[lum >= np.percentile(lum, 75)].mean(0)
            ls, lb = lab(s), lab(mean)
            dl = 100 * (lb[0] - ls[0]) / max(ls[0], 1)
            chroma = np.hypot(*ls[1:]) > 10
            hs = colorsys.rgb_to_hsv(*(s / 255))[0] * 360; hb = colorsys.rgb_to_hsv(*(mean / 255))[0] * 360
            dh = abs((hb - hs + 180) % 360 - 180) if chroma else None
            res = "ok"
            if dh is not None and dh > 15: res = "FAIL hue"
            elif p not in REPORT_ONLY and abs(dl) > 25: res = "FAIL lightness"
            elif abs(dl) > 10: res = "report" if p in REPORT_ONLY else "WARN lightness"
            fails += res.startswith("FAIL"); warns += res.startswith("WARN")
            sat = colorsys.rgb_to_hsv(*(mean / 255))[1]; ssat = colorsys.rgb_to_hsv(*(s / 255))[1]
            f3 = lambda c: ",".join(str(int(round(v))) for v in c)
            lines.append(f"| {model} | {p} | {f3(s)} | {f3(mean)} | {f3(lit)} | {lb[0]:.0f} vs {ls[0]:.0f} ({dl:+.0f} %) | "
                         f"{'-' if dh is None else f'{dh:.0f}'} | {sat:.2f} / {ssat:.2f} | {res} |")
    lines += ["", f"{fails} FAIL, {warns} WARN"]
    out = "\n".join(lines) + "\n"
    print(out)
    if a.report:
        with open(a.report, "w") as f: f.write(out)
    sys.exit(min(fails, 100))


if __name__ == "__main__":
    main()
