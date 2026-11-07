import sys
from PIL import Image, ImageDraw
out, cols, W, H = sys.argv[1], 5, 640, 360
items = [a.split("=", 1) for a in sys.argv[2:]]
rows = (len(items) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, H * rows), (20, 20, 20)); d = ImageDraw.Draw(sheet)
for i, (label, p) in enumerate(items):
    try: im = Image.open(p).convert("RGB").resize((W, H))
    except Exception: im = Image.new("RGB", (W, H), (60, 0, 0))
    sheet.paste(im, ((i % cols) * W, (i // cols) * H)); d.text(((i % cols) * W + 6, (i // cols) * H + 6), label, fill=(255, 255, 0))
sheet.save(out)
