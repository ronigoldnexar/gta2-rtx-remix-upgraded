import sys
from PIL import Image, ImageDraw
d, m, out = sys.argv[1], sys.argv[2], sys.argv[3]
names = ["front34", "side", "rear34", "eye", "close", "high", "chase", "seat"]
ims = []
for n in names:
    try: ims.append(Image.open(f"{d}/t_show_{n}_{m}.png").convert("RGB"))
    except OSError: ims.append(Image.new("RGB", (1280, 720), (40, 0, 0)))
W, H = 640, 360
o = Image.new("RGB", (W * 4, H * 2))
for i, im in enumerate(ims):
    o.paste(im.resize((W, H), Image.LANCZOS), ((i % 4) * W, (i // 4) * H))
    ImageDraw.Draw(o).text(((i % 4) * W + 6, (i // 4) * H + 4), names[i], fill=(255, 255, 0))
o.save(out)
