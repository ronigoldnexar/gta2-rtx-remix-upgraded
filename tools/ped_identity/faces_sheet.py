"""PEDS-FACES review: per avatar, head close-ups: plain, each accessory, each hair colour (with a facial hair)."""
import sys, json, os
sys.path.insert(0, '/mnt/gta2/gta2-linux/wt_faces/tools/ped_identity'); import render
from PIL import Image, ImageDraw
out, M, A = sys.argv[1], sys.argv[2].rstrip('/') + '/', sys.argv[3].rstrip('/') + '/'
names = sys.argv[4].split(',')
rep = json.load(open(A + 'faces_report.json'))
man = {e['name']: e for e in json.load(open(M + 'manifest.json'))['imported']}
CW, CH = 120, 140
rows = []
for n in names:
    r = rep[n]; ref = man[n].get('zone_ref', 128.0)
    tf = lambda tex, node: [c / ref for c in (60, 70, 96)] if '#pt' in node else [c / ref for c in (40, 44, 56)] if '#pb' in node else None
    head_tex = [t for t in man[n]['textures'] if t.endswith('_head.tga')][0]
    op = [t for t in man[n]['textures'] if '_opacity' in t]
    cells = [('plain', [], {})]
    for k in r['accessories']:
        sw = {f'acc_{k}.tga': f'acc_{k}~c1.tga'} if k in ('cap', 'beanie', 'flatcap') else {}
        if k in ('cap', 'beanie', 'flatcap') and op: sw[op[0]] = 'acc_clear.tga'   # as the DLL: no hair cards under headwear
        cells.append((k, [A + f'{n}~{k}.mesh'], sw))
    for i, c in enumerate(r['hair'], 1):
        sw = {head_tex: head_tex[:-4] + f'~hc{i}.tga', f'{n}~hair.tga': f'{n}~hair~hc{i}.tga', f'{n}~stubble.tga': f'{n}~stubble~hc{i}.tga'}
        if op: sw[op[0]] = op[0][:-4] + f'~hc{i}.tga'
        fac = [A + f'{n}~goatee.mesh'] if 'goatee' in r['accessories'] else []
        cells.append(('hair ' + c, fac, sw))
    row = Image.new('RGB', (len(cells) * CW, CH + 16), (40, 42, 46)); d = ImageDraw.Draw(row)
    for j, (lab, att, sw) in enumerate(cells):
        big = render.render(M + n + '.mesh', [(25, 6)], tints=tf, size=(CW * 5, CH * 5), attach=att, swap=sw, tex_dirs=(A,))[0]
        im = big.crop((int(CW * 1.9), int(CH * 0.15), int(CW * 1.9) + int(CW * 1.2), int(CH * 0.15) + int(CH * 1.2))).resize((CW, CH))
        row.paste(im, (j * CW, 0)); d.text((j * CW + 2, CH + 2), lab[:18], fill=(230, 230, 230))
    d.text((2, 2), n.replace('human_', ''), fill=(250, 200, 120)); rows.append(row)
W = max(r.width for r in rows); sheet = Image.new('RGB', (W, sum(r.height for r in rows)), (30, 30, 30)); y = 0
for r in rows: sheet.paste(r, (0, y)); y += r.height
sheet.save(out, quality=88); print(sheet.size)
