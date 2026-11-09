#!/usr/bin/env python3
"""Before/after sheet for one vehicle model from the review probes (same viewpoints):
gamerun/vr_traffic.py frames (drv_far / drv_close / drv_fp) and gamerun/vr_seat.py frames
(t_own3 chase, t_own1 seat, t_own3drive steering).

    before_after.py NNN --before-traffic out/vr_traffic1 --before-seat out/vr_seat1 \
        --after-traffic out/<run> --after-seat out/<run> --out sheet.png
"""
import argparse, os
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("model", type=int)
ap.add_argument("--before-traffic"); ap.add_argument("--before-seat")
ap.add_argument("--after-traffic"); ap.add_argument("--after-seat")
ap.add_argument("--sprite", default=None)
ap.add_argument("--out", required=True)
ap.add_argument("--w", type=int, default=480)
a = ap.parse_args()
n = f"{a.model:03d}"
cols = [("far (chase cam)", "traffic", f"drv_far_{n}.png"), ("close", "traffic", f"drv_close_{n}.png"),
        ("eye height", "traffic", f"drv_fp_{n}.png"), ("own car, chase", "seat", f"t_own3_{n}.png"),
        ("own car, seat", "seat", f"t_own1_{n}.png"), ("own car, steering", "seat", f"t_own3drive_{n}.png")]
W = a.w; H = W * 9 // 16
S = Image.new("RGB", (W * len(cols) + (W // 3 if a.sprite else 0), 2 * H + 40), (30, 30, 30))
d = ImageDraw.Draw(S)
for r, (label, tdir, sdir) in enumerate((("before", a.before_traffic, a.before_seat), ("after", a.after_traffic, a.after_seat))):
    for c, (name, kind, f) in enumerate(cols):
        p = os.path.join(tdir if kind == "traffic" else sdir, f) if (tdir if kind == "traffic" else sdir) else None
        if p and os.path.exists(p):
            S.paste(Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS), (c * W, 20 + r * (H + 20)))
        else:
            d.text((c * W + 10, 20 + r * (H + 20) + H // 2), "(no frame)", fill=(200, 200, 200))
        d.text((c * W + 6, 4 + r * (H + 20)), f"{label}: {name}", fill=(255, 255, 255))
if a.sprite:
    sp = Image.open(a.sprite).convert("RGBA")
    sp = sp.resize((int(sp.width * (H * 1.6) / sp.height), int(H * 1.6)), Image.NEAREST)
    bg = Image.new("RGBA", sp.size, (30, 30, 30, 255)); bg.alpha_composite(sp)
    S.paste(bg.convert("RGB"), (W * len(cols) + 10, 30))
    d.text((W * len(cols) + 10, 4), f"sprite {n} (nose down)", fill=(255, 255, 255))
S.save(a.out)
print(a.out, S.size)
