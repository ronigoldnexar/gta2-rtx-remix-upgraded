"""Review sheet: per avatar front, 3/4, side, back, top-down (pitch 85) and two head close-ups; optional walk frame.
  views_sheet.py <out.jpg> <models dir> name[:tint_top:tint_bottom],..."""
import sys, json
sys.path.insert(0, '/mnt/gta2/gta2-linux/wt_peds3/tools/ped_identity'); import render
from PIL import Image, ImageDraw
out, M = sys.argv[1], sys.argv[2].rstrip('/') + '/'
man = {e['name']: e for e in json.load(open(M + 'manifest.json'))['imported']}
CW, CH = 170, 300
cols = ['front', '3/4', 'side', 'back', 'top-down', 'head front', 'head 3/4', 'walk']
items = sys.argv[3].split(',')
sheet = Image.new('RGB', (len(cols) * CW, len(items) * (CH + 18)), (40, 42, 46)); d = ImageDraw.Draw(sheet)
for r, it in enumerate(items):
    parts = it.split(':'); n = parts[0]; e = man.get(n, {}); ref = e.get('zone_ref', 128.0)
    tf = None
    if len(parts) == 3:
        t = [int(x) for x in parts[1].split('/')]; b = [int(x) for x in parts[2].split('/')]
        tf = lambda tex, node, t=t, b=b: [c / ref for c in t] if '#pt' in node else [c / ref for c in b] if '#pb' in node else None
    p = M + n + '.mesh'
    ims = [render.render(p, [(0, 4)], tints=tf, size=(CW, CH))[0], render.render(p, [(35, 8)], tints=tf, size=(CW, CH))[0],
           render.render(p, [(90, 5)], tints=tf, size=(CW, CH))[0], render.render(p, [(180, 5)], tints=tf, size=(CW, CH))[0]]
    big = render.render(p, [(30, 85)], tints=tf, size=(CW * 2, CH * 2))[0]; ims.append(big.crop((CW // 2, CH // 2, CW // 2 + CW, CH // 2 + CH)))
    for yaw in (0, 35):
        hb = render.render(p, [(yaw, 4)], tints=tf, size=(CW * 4, CH * 4))[0]
        ims.append(hb.crop((int(CW * 1.5), int(CH * 0.08), int(CW * 2.5), int(CH * 0.08) + CH)).resize((CW, CH)))
    ims.append(render.render(p, [(35, 8)], tints=tf, size=(CW, CH), clip='walk', frame=8)[0])
    for c, im in enumerate(ims): sheet.paste(im, (c * CW, r * (CH + 18)))
    d.text((3, r * (CH + 18) + CH + 3), it.replace('human_', ''), fill=(250, 200, 120))
for c, lab in enumerate(cols): d.text((c * CW + 3, 3), lab, fill=(255, 255, 0))
sheet.save(out, quality=88); print(sheet.size)
