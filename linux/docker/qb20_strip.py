"""strip.py <video> <out.png> <t0> <t1> <n> [crop w h]: n frames between t0 and t1 side by side, centre-cropped"""
import subprocess, sys, os, tempfile
from PIL import Image
v, out, t0, t1, n = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
cw, ch = (int(sys.argv[6]), int(sys.argv[7])) if len(sys.argv) > 7 else (420, 560)
d = tempfile.mkdtemp()
ims = []
for k in range(n):
    t = t0 + (t1 - t0) * k / max(1, n - 1)
    f = os.path.join(d, f"{k}.png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", v, "-frames:v", "1", f], check=True)
    im = Image.open(f)
    W, H = im.size
    im = im.crop(((W - cw) // 2, (H - ch) // 2 + 40, (W + cw) // 2, (H + ch) // 2 + 40))
    ims.append((t, im))
sheet = Image.new("RGB", (cw * n, ch + 24), (20, 20, 20))
from PIL import ImageDraw
dr = ImageDraw.Draw(sheet)
for k, (t, im) in enumerate(ims):
    sheet.paste(im, (k * cw, 24)); dr.text((k * cw + 6, 5), f"{os.path.basename(v)} t={t:.2f}", fill=(255, 255, 0))
sheet.save(out)
