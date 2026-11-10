#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-4: paint parity per build (docs/identity-system.md section 9.5).

    python3 tools/paint_parity.py out/<run> [--mode new] [--report table.md]

<run> is a session of linux/docker/keys_paint_parity.sh: frames pt_top_<model>_<paint>_<mode>.png of the player's stopped
car forced to each model and painted (force_car_paint) as a sprite of each paint, seen from the classic camera's pose.
FIX-CAR-IDENTITY-5: one row group per body class (generated, authored, authored carkit, remapped, livery, wreck). Liveries
and wrecks keep their own colours: they are found in the painted cars' footprint and compared with their style sprite
(--sprites, assets-src/cars/sprites): a livery's dominant saturated hue (hue FAIL over 15, lightness WARN), a wreck's
dominant colour (paint delta, lightness at half weight, FAIL over 25).
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
          "green": (60, 120, 60), "white": (215, 215, 215), "teal": (60, 93, 102),
          "van36": (70, 99, 85), "vanblue": (59, 82, 115)}
# FIX-CAR-IDENTITY-5: the body class of each model the gate forces (docs/identity-system.md section 10.5). Liveries are
# identity.cpp's Livery() list; wrecks are CARI 72..81. Painted bodies are compared with the paint they were given (the
# sprite's paint by the remap rule); liveries and wrecks keep their own colours and are compared with their style sprite.
LIVERY = {11, 12, 17, 22, 23, 24, 25, 26, 27, 34, 51, 52, 54, 56, 59, 60, 61, 85, 86}
CLASS = {0: "generated", 18: "authored carkit", 13: "authored", 63: "authored", 68: "authored", 4: "remapped (painted)"}
def body_class(m):
    m = int(m)
    return "wreck" if 72 <= m <= 81 else "livery" if m in LIVERY else CLASS.get(m, "painted")
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
    ap.add_argument("--sprites", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets-src", "cars", "sprites"),
                    help="the style's car sprites (assets-src/cars/sprites: <model>_<name>_default.png): liveries' and wrecks' reference")
    a = ap.parse_args()
    # VEHICLE-ART-22: or the probe's POSES=top3 frames (3 blocks up: at the 5-block top pose the street view showed the
    # classic sprite at the 150.5,160.5 gate spot, out/va22pp1), when a run has no top frames
    frames = glob.glob(os.path.join(a.run, "pt_top_*_*_*.png")) or glob.glob(os.path.join(a.run, "pt_top3_*_*_*.png"))
    rx = re.compile(r"pt_top3?_(\d+)_([a-z][a-z0-9]*)_([A-Za-z0-9]+)\.png$")
    have = {}
    for f in frames:
        m = rx.search(f)
        if m: have[(m.group(1), m.group(2), m.group(3))] = f
    modes = sorted({k[2] for k in have if k[2] != "noshade"})
    mode = a.mode or (modes[0] if len(modes) == 1 else "new")
    lines = [f"# Paint parity: {os.path.basename(a.run.rstrip('/'))} (mode {mode})", "",
             "| Model | Class | Paint | Sprite | 3D body | Lit lids | L* 3D vs sprite | dHue | Saturation 3D / sprite | Result |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    fails = warns = 0
    region = None   # the painted cars' footprint on screen (same pose): where a livery or a wreck is looked for
    own_rows = []
    shade = []   # FIX-CAR-IDENTITY-7: (model, paint, lit lids measured / with the sun shadows off)

    def shade_check(model, p, sel):
        # the probe's "noshade" frame (SHADE_CHECK=1): the same car, paint and pose with [visuals] shadows=0. In open sun the
        # lit lids keep 0.94-1.00 of it; a world shadow on the car (since 9b9e646 a park tree's
        # crown at the old spot) leaves 0.51-0.66: then the gate measured the shade, not the paint, and the run is not a verdict.
        if (model, p, "noshade") not in have: return
        lum = lambda q: q @ [0.3, 0.59, 0.11]
        a_, b_ = lum(sel(load(have[(model, p, mode)]))), lum(sel(load(have[(model, p, "noshade")])))
        r = a_[a_ >= np.percentile(a_, 75)].mean() / max(b_[b_ >= np.percentile(b_, 75)].mean(), 1.0)
        shade.append((model, p, r))
    for model in sorted({k[0] for k in have}):
        if body_class(model) in ("livery", "wreck"):
            own_rows.append(model); continue
        keys = [p for p in PAINTS if (model, p, mode) in have]
        pair = [p for p in ("red", "green", "navy", "vanblue") if p in keys]
        if len(pair) < 2:
            lines.append(f"| {model} | {body_class(model)} | - | | | | | | | | SKIP (needs two of red/green/navy for the mask) |")
            continue
        imgs = [load(have[(model, p, mode)]) for p in pair]
        # FIX-CAR-IDENTITY-5: the paint is what changes against the first paint in EVERY other paint's frame (the
        # shortest change over the pairs); the largest took in passers-by and the hero's idle between two shots (the
        # 004 van's mask read 96,103,93 for a 70,99,85 paint, out/fci5_ptm1a).
        diff = np.min([np.abs(imgs[0] - x).sum(2) for x in imgs[1:]], axis=0) if len(imgs) > 2 else np.abs(imgs[0] - imgs[1]).sum(2)
        mask = diff > 60
        ys, xs = np.nonzero(mask)
        if len(ys) < 200:
            lines.append(f"| {model} | {body_class(model)} | - | | | | | | | | SKIP (no car found: {len(ys)} px change) |")
            continue
        cy, cx = np.median(ys), np.median(xs)
        keep = (np.abs(ys - cy) < 220) & (np.abs(xs - cx) < 160)
        mk = np.zeros_like(mask); mk[ys[keep], xs[keep]] = True
        if region is None:
            region = (int(ys[keep].min()), int(ys[keep].max()) + 1, int(xs[keep].min()), int(xs[keep].max()) + 1)
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
            lines.append(f"| {model} | {body_class(model)} | {p} | {f3(s)} | {f3(mean)} | {f3(lit)} | {lb[0]:.0f} vs {ls[0]:.0f} ({dl:+.0f} %) | "
                         f"{'-' if dh is None else f'{dh:.0f}'} | {sat:.2f} / {ssat:.2f} | {res} |")
            shade_check(model, p, lambda im: im[mk])
    # FIX-CAR-IDENTITY-5: liveries and wrecks against their style sprite (the classic view's own picture of that model).
    f3 = lambda c: ",".join(str(int(round(v))) for v in c)
    for model in own_rows:
        cls = body_class(model)
        frames = [have[k] for k in have if k[0] == model and k[2] == mode]
        sp = sorted(glob.glob(os.path.join(a.sprites, f"{int(model):03d}_*_default.png")))
        if not frames or not sp:
            lines.append(f"| {model} | {cls} | - | | | | | | | SKIP (no sprite reference) |"); continue
        if region is None:   # no painted car in the run: the top pose centres the car (the middle 400x400 of 1280x720)
            h_, w_ = load(frames[0]).shape[:2]
            region = (h_ // 2 - h_ * 200 // 720, h_ // 2 + h_ * 200 // 720, w_ // 2 - w_ * 200 // 1280, w_ // 2 + w_ * 200 // 1280)
        spr = np.asarray(Image.open(sp[0]).convert("RGBA")).reshape(-1, 4).astype(float)
        spr = spr[spr[:, 3] >= 128][:, :3]
        y0, y1, x0, x1 = region
        dy, dx = (y1 - y0) // 6, (x1 - x0) // 6
        px = load(frames[0])[max(0, y0 - dy):y1 + dy, max(0, x0 - dx):x1 + dx].reshape(-1, 3)
        if cls == "livery":
            # the livery's body colour: its sprite's dominant saturated hue (10-degree bins), the texels within 15 degrees
            hsv = lambda c: np.array([colorsys.rgb_to_hsv(*(q / 255)) for q in c])
            hs = hsv(spr); ok = (hs[:, 1] >= 0.45) & (hs[:, 2] >= 0.15)
            if ok.sum() < 30:
                lines.append(f"| {model} | {cls} | - | | | | | | | SKIP (an unsaturated livery: no body hue to follow) |"); continue
            hb = (np.argmax(np.histogram(hs[ok, 0] * 360, bins=36, range=(0, 360))[0]) + 0.5) * 10
            near = lambda h: np.abs((h * 360 - hb + 180) % 360 - 180) <= 15
            s = np.median(spr[ok & near(hs[:, 0])], 0)
            hp = hsv(px); body = px[(hp[:, 1] >= 0.45) & (hp[:, 2] >= 0.1) & near(hp[:, 0])]
            if len(body) < 200:
                lines.append(f"| {model} | {cls} | own | {f3(s)} | | | | | | FAIL (no body of the livery's hue on screen: {len(body)} px) |"); fails += 1; continue
            mean = np.median(body, 0); lum = body @ [0.3, 0.59, 0.11]; lit = np.median(body[lum >= np.percentile(lum, 75)], 0)
        else:
            # a wreck: the charred body's dominant colour (k-means in Lab as identity_parity.py) against the wreck sprite's
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import identity_parity as ip
            s = ip.dominant(spr)
            bg = np.median(np.concatenate([px[:200], px[-200:]]), 0)
            body = px[np.linalg.norm(px - bg, axis=1) > 28]
            if len(body) < 200:
                lines.append(f"| {model} | {cls} | own | {f3(s)} | | | | | | FAIL (no wreck on screen) |"); fails += 1; continue
            mean = ip.dominant(body); lum = body @ [0.3, 0.59, 0.11]; lit = np.median(body[lum >= np.percentile(lum, 75)], 0)
        y0_, y1_, x0_, x1_ = max(0, y0 - dy), y1 + dy, max(0, x0 - dx), x1 + dx
        shade_check(model, os.path.basename(frames[0]).split("_")[3], lambda im: im[y0_:y1_, x0_:x1_].reshape(-1, 3))
        ls, lb = lab(s), lab(mean)
        dl = 100 * (lb[0] - ls[0]) / max(ls[0], 1)
        chroma = np.hypot(*ls[1:]) > 10
        hs_ = colorsys.rgb_to_hsv(*(s / 255))[0] * 360; hb_ = colorsys.rgb_to_hsv(*(mean / 255))[0] * 360
        dh = abs((hb_ - hs_ + 180) % 360 - 180) if chroma else None
        de = float(np.sqrt(((ls[0] - lb[0]) / 2) ** 2 + (ls[1] - lb[1]) ** 2 + (ls[2] - lb[2]) ** 2))
        if dh is not None and dh > 15: res = "FAIL hue"
        elif cls == "wreck" and de > 25: res = f"FAIL paint delta {de:.0f}"
        elif abs(dl) > 25: res = "WARN lightness (art: the model's own colours)"
        elif abs(dl) > 10: res = "WARN lightness"
        else: res = "ok"
        fails += res.startswith("FAIL"); warns += res.startswith("WARN")
        sat = colorsys.rgb_to_hsv(*(mean / 255))[1]; ssat = colorsys.rgb_to_hsv(*(s / 255))[1]
        lines.append(f"| {model} | {cls} | own ({os.path.basename(sp[0])}) | {f3(s)} | {f3(mean)} | {f3(lit)} | {lb[0]:.0f} vs {ls[0]:.0f} ({dl:+.0f} %) | "
                     f"{'-' if dh is None else f'{dh:.0f}'} | {sat:.2f} / {ssat:.2f} | {res} |")
    if shade:
        lines += ["", "Gate setup: the car's lit lids with the sun shadows on / off at the same moment (open sun 0.94-1.00; under 0.80 the",
                  "car stands in a world shadow and its rows measure that shade, not the paint: move the spot, BACK_SECS / WX,WY):", ""]
        for model, p, r in shade:
            bad = bool(r < 0.80)
            fails += bad
            lines.append(f"    {model} {p}: {r:.2f}" + ("  FAIL (car in a world shadow)" if bad else "  ok"))
    else:
        lines += ["", "Gate setup: no shadows-off frames (SHADE_CHECK=0 or an older probe): a world shadow on the car is not detected."]
    lines += ["", f"{fails} FAIL, {warns} WARN"]
    out = "\n".join(lines) + "\n"
    print(out)
    if a.report:
        with open(a.report, "w") as f: f.write(out)
    sys.exit(int(min(fails, 100)))


if __name__ == "__main__":
    main()
