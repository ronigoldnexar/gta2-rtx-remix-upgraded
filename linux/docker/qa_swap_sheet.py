#!/usr/bin/env python3
"""qa_swap_sheet.py <out.png> <run dir>...: the contact sheet of qa_swapdeath.py runs, one row per
death round: the car he dies in, two frames of the death (WASTED), the respawn found again, the
view after it and the walk. Each row is labelled with the run's district and the CHECK line."""
import glob, os, re, sys
from PIL import Image, ImageDraw, ImageFont

out, runs = sys.argv[1], sys.argv[2:]
W, H = 384, 216
COLS = [("a_car", "in the car"), ("b_death_0", "death"), ("b_death_last", "WASTED"),
        ("d_found", "respawn: found"), ("e_found_view", "found, 3D view"), ("f_walked", "walked on")]
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
except OSError:
    font = ImageFont.load_default()
rows = []
for run in runs:
    keys = open(os.path.join(run, "keys.log"), errors="replace").read()
    dist = "Industrial (bil)" if "bil" in os.path.basename(run.rstrip("/")) else "Residential (ste)"
    for tag in sorted({m for m in re.findall(r"qa_(sd_\d+_\w+?)_a_car\.png", " ".join(os.listdir(run)))}):
        check = re.search(rf"CHECK {tag} (.*)", keys)
        deaths = sorted(glob.glob(os.path.join(run, f"qa_{tag}_b_death_*.png")))
        pick = {"b_death_0": deaths[min(2, len(deaths) - 1)] if deaths else None,
                "b_death_last": deaths[-1] if deaths else None}
        cells = []
        for key, _ in COLS:
            p = pick.get(key) or os.path.join(run, f"qa_{tag}_{key}.png")
            cells.append(p if p and os.path.exists(p) else None)
        rows.append((f"{dist}  {tag}: {check.group(1) if check else 'no CHECK line'}", cells))
sheet = Image.new("RGB", (W * len(COLS), (H + 44) * len(rows) + 26), (24, 24, 24))
d = ImageDraw.Draw(sheet)
for i, (_, name) in enumerate(COLS):
    d.text((i * W + 6, 4), name, fill=(230, 230, 230), font=font)
for r, (label, cells) in enumerate(rows):
    y = 26 + r * (H + 44)
    d.text((6, y + 2), label[:200], fill=(255, 220, 120), font=font)
    for c, p in enumerate(cells):
        if p:
            sheet.paste(Image.open(p).convert("RGB").resize((W, H)), (c * W, y + 22))
        else:
            d.text((c * W + 10, y + 100), "(no frame)", fill=(200, 80, 80), font=font)
sheet.save(out)
print(out, len(rows), "rows")
