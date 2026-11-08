#!/usr/bin/env python3
"""Before/after sheet of the model PBR maps (docs/remix-materials.md, "Model PBR maps").
  remix_carprops_sheet.py <out.png> <preview dir> [<frame.png>=<caption> ...]
Top: for each subject the maps remix_model_materials.py --preview wrote (albedo, normal,
roughness, metallic, emissive) and the albedo lit by one raking light: before (flat, no
maps) and after (normal map, roughness and metallic). Below: Remix frames, captioned, in
pairs (before, after) or as given."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

SUBJECTS = [("cop car 012", "012_cop_car_0"), ("taxi 056", "056_taxi_0"), ("Schmidt sedan 036", "036_schmidt_0"),
            ("fire truck 017", "017_fire_truck_0"), ("phone booth", "code_phone_1"), ("booth sign (__lit)", "code_phone__lit_0"),
            ("street lamp", "street_lamp_1"), ("traffic light lens", "light_red__lit_0"),
            ("pedestrian body", "human_police_male_01_m220_body"), ("pedestrian head", "human_police_male_01_m220_head")]
# 2x crops of the car atlases (x0, y0, size in texels), where panel lines and badges are
ZOOM = [("cop car 012, doors (2x)", "012_cop_car_0", (40, 290, 110)), ("taxi 056, side (2x)", "056_taxi_0", (300, 380, 110)),
        ("fire truck 017 (2x)", "017_fire_truck_0", (60, 60, 110))]
COLS = ["albedo", "normal (DX)", "roughness", "metallic", "emissive", "before: flat", "after: maps"]

def font(n):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f): return ImageFont.truetype(f, n)
    return ImageFont.load_default()

def main():
    out, prev = sys.argv[1], sys.argv[2]
    cell, lab = 220, 210
    rows = [(c, os.path.join(prev, f + "_maps.png"), None) for c, f in SUBJECTS if os.path.exists(os.path.join(prev, f + "_maps.png"))]
    rows += [(c, os.path.join(prev, f + "_maps.png"), z) for c, f, z in ZOOM if os.path.exists(os.path.join(prev, f + "_maps.png"))]
    frames = [a.split("=", 1) for a in sys.argv[3:]]
    fw = 640; fh = 360
    fcols = 2
    frows = (len(frames) + fcols - 1) // fcols
    W = lab + cell * len(COLS)
    H = 40 + len(rows) * cell + (frows * (fh + 26) + 40 if frames else 0)
    S = Image.new("RGB", (max(W, fcols * fw), H), (24, 24, 24)); d = ImageDraw.Draw(S)
    f1, f2 = font(16), font(14)
    for i, c in enumerate(COLS): d.text((lab + i * cell + 6, 12), c, fill=(230, 230, 230), font=f1)
    y = 40
    for cap, p, z in rows:
        im = Image.open(p).convert("RGB"); w, h = im.size; cw = w // len(COLS)
        for i in range(len(COLS)):
            c = im.crop((i * cw, 0, (i + 1) * cw, h)) if z is None else im.crop((i * cw + z[0], z[1], i * cw + z[0] + z[2], z[1] + z[2]))
            f_ = (cell - 4) / max(c.size)
            c = c.resize((max(1, round(c.size[0] * f_)), max(1, round(c.size[1] * f_))), Image.NEAREST if max(c.size) < 64 else Image.LANCZOS)
            S.paste(c, (lab + i * cell + 2, y + 2))
        d.text((8, y + cell // 2 - 10), cap, fill=(240, 240, 240), font=f1)
        y += cell
    if frames:
        y += 20
        for k, (p, cap) in enumerate(frames):
            im = Image.open(p).convert("RGB"); im.thumbnail((fw - 4, fh))
            x0 = (k % fcols) * fw; y0 = y + (k // fcols) * (fh + 26)
            S.paste(im, (x0 + 2, y0 + 22)); d.text((x0 + 6, y0 + 2), cap, fill=(240, 240, 240), font=f2)
    S.save(out); print(out, S.size)

if __name__ == "__main__":
    main()
