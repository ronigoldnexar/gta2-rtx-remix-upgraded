#!/usr/bin/env python3
"""out/polish3_sheet.png: the three warp spots (third + first person) and the soak's exit frames."""
import glob, os
from PIL import Image, ImageDraw
rows = []
for tag, name in (("p3wil", "Downtown terrace 166.5,139.5"), ("p3bil", "Residential default 164.5,149.5"), ("p3ste", "Industrial default 164.5,149.5")):
    d = f"out/qa_p3warp_{tag[2:]}"
    fs = [f"{d}/{tag}_01_third.png", f"{d}/{tag}_02_third_turned.png", f"{d}/{tag}_03_first.png", f"{d}/{tag}_05_first_turned_back.png"]
    rows.append((f"scene warp, {name}: third | third turned | first | first after walking", fs))
ex = sorted(glob.glob("out/qa_p3soak_wil/p3soak_*_exit_*.png"))[:4]
if ex: rows.append(("Downtown soak after the change: first/third person right after leaving the car at the kerb", ex))
W, H = 480, 270
img = Image.new("RGB", (4 * W, len(rows) * (H + 22)), (0, 0, 0))
dr = ImageDraw.Draw(img)
for r, (label, fs) in enumerate(rows):
    y0 = r * (H + 22)
    dr.text((4, y0 + 4), label, fill=(255, 255, 255))
    for c, f in enumerate(fs[:4]):
        if os.path.exists(f):
            img.paste(Image.open(f).convert("RGB").resize((W, H)), (c * W, y0 + 22))
img.save("out/polish3_sheet.png")
print("out/polish3_sheet.png", img.size)
