#!/usr/bin/env python3
"""PEDS-VARIETY: a sample crowd as the DLL dresses it (identity.cpp DerivePed / CrowdVariety, emulated by outfits.crowd()).

    CUDA_VISIBLE_DEVICES=0 gen3d/venv/bin/python tools/ped_identity/crowd_sheet.py <models dir> <out.jpg> \
        [--remaps 18,30,41,47] [--seeds 24] [--first 100] [--manifest <manifest.json with ped_types>]

One row per remap: <seeds> consecutive ped ids (the game's ids; a spawned group has consecutive ids), each the
avatar its type's pool deals, in the record's colours (curated outfit, sprite colours, an everyday tint or its
own), labelled with the avatar and the outfit. Needs the gen3d venv (torch, nvdiffrast, PIL) and a GPU."""
import argparse, json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import render
from outfits import crowd, pool_model
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument('models'); ap.add_argument('out')
ap.add_argument('--remaps', default='18,30,41,47'); ap.add_argument('--seeds', type=int, default=24)
ap.add_argument('--first', type=int, default=100); ap.add_argument('--manifest', default=None)
ap.add_argument('--cell', default='110x200')
ap.add_argument('--pitch', type=float, default=8.0, help='camera pitch in degrees: 8 the 3/4 view, 85 top-down (the BEV)')
ap.add_argument('--yaw', type=float, default=25.0)
a = ap.parse_args()
M = a.models.rstrip('/') + '/'
man = json.load(open(M + 'manifest.json'))
types_man = json.load(open(a.manifest)) if a.manifest else man
imported = {e['name']: e for e in man['imported']}
types = {r: t for t in types_man['ped_types'] for r in t['remaps']}
outfits_rows = types_man.get('ped_outfits', [])
CW, CH = (int(x) for x in a.cell.split('x'))
remaps = [int(x) for x in a.remaps.split(',')]
sheet = Image.new('RGB', (a.seeds * CW, len(remaps) * (CH + 26)), (40, 42, 46)); d = ImageDraw.Draw(sheet)
counts = {}
for row, r in enumerate(remaps):
    t = types[r]
    civilian = t['name'].startswith('civilian')
    sprite = outfits_rows[r] if t.get('tint') and r < len(outfits_rows) else None
    for i in range(a.seeds):
        seed = a.first + i
        n = pool_model(seed, t['models'], r)
        e = imported[n]
        rec = crowd(seed, r, n, e, sprite, civilian, models=imported)
        base, n = n, rec.get('model', n)   # PEDS-VARIETY-3: a detail variant (posed with its avatar's clips)
        af = M + base + '.mesh' if n != base else None
        counts[rec['kind']] = counts.get(rec['kind'], 0) + 1
        def tints(tex, node, rec=rec):
            if rec['zone'] is not None:
                if '#pt' in node: return rec['zone'][0]
                if '#pb' in node: return rec['zone'][1]
            if rec['paint'] is not None and '_paint' in tex: return rec['paint']
            return None
        if a.pitch > 60:   # from above the figure fills little of a frame fitted to his height: render big, keep the middle
            big = render.render(M + n + '.mesh', [(a.yaw, a.pitch)], tints=tints, size=(CW * 3, CH * 3), anim_from=af)[0]
            im = big.crop((CW, CH, 2 * CW, 2 * CH)).resize((CW, CH))
        else:
            im = render.render(M + n + '.mesh', [(a.yaw, a.pitch)], tints=tints, size=(CW, CH), anim_from=af)[0]
        x, y = i * CW, row * (CH + 26)
        sheet.paste(im, (x, y))
        d.text((x + 2, y + CH + 1), n.replace('human_', '').replace('business_', 'biz_')[:18], fill=(250, 200, 120))
        d.text((x + 2, y + CH + 13), rec['label'][:19], fill=(225, 225, 225))
    d.text((3, row * (CH + 26) + 2), f"remap {r} {t['name']}", fill=(255, 255, 0))
sheet.save(a.out, quality=88)
print(a.out, sheet.size, counts)
