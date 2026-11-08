#!/usr/bin/env python3
"""Before/after sheet for regenerated car models, rendered fresh with gen3d/render_glb.py
(nvdiffrast, same camera and light for both): one row per car,
  BEFORE: game sprite | v1 GLB from 3/4 front, top, side, front, 3/4 rear (far side)
  AFTER:  concept     | v3 GLB from the same five views
with the scorer totals (and lighting term) of both.

    car_quality_sheet.py --catalog assets-src/cars/catalog.json --v1 assets-src/cars/models3d_v1_backup,assets-src/cars/models3d \\
        --v2 assets-src/cars/models3d_v2 --before out/car_scores_before_cq4.json --after out/car_scores_after.json \\
        --out out/car_quality_sheet.png [--models 12,56] [--tile 160]
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'gen3d'))
VIEWS = ('3q', 'top', 'side', 'front', '3qr')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', required=True); ap.add_argument('--v1', required=True, help='v1 GLB dirs, first hit wins (the integration backup, then models3d)'); ap.add_argument('--v2', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--before', default=None); ap.add_argument('--after', default=None)
    ap.add_argument('--models', default=None); ap.add_argument('--tile', type=int, default=160)
    ap.add_argument('--label', default='v3', help='name of the new models in the headers (r5 for round 5)')
    a = ap.parse_args()
    import render_glb as R
    import nvdiffrast.torch as dr
    ctx = dr.RasterizeCudaContext()
    cat = json.load(open(a.catalog)); cars = {c['model']: c for c in cat['cars']}; root = os.path.dirname(os.path.abspath(a.catalog))
    def scores(p):
        return {r['model']: r for r in json.load(open(p))} if p and os.path.exists(p) else {}
    before, after = scores(a.before), scores(a.after)
    want = {int(m) for m in a.models.split(',')} if a.models else None
    stems = sorted(f[:-4] for f in os.listdir(a.v2) if f.endswith('.glb') and f[:3].isdigit())
    stems = [s for s in stems if want is None or int(s[:3]) in want]
    T = a.tile; pad = 10; head = 18; n = 1 + len(VIEWS)
    W = 2 * n * T + 3 * pad; H = 30 + len(stems) * (T + head + pad)
    sheet = Image.new('RGB', (W, H), (24, 24, 28)); d = ImageDraw.Draw(sheet)
    d.text((pad, 8), 'BEFORE: sprite | v1 model  (3/4 front, top, side, front, 3/4 rear = far side)', fill=(230, 230, 230))
    d.text((2 * pad + n * T, 8), f'AFTER: concept | {a.label} model (checked concept, TRELLIS, bilateral delight, side balance, roof-only sprite)', fill=(230, 230, 230))

    def tiles(glb):
        ms = R.load(glb)
        return [Image.fromarray(R.render(ms, v, T * 2, ctx)).resize((T, T), Image.LANCZOS) for v in VIEWS]

    def thumb(path):
        im = Image.open(path).convert('RGBA'); bg = Image.new('RGBA', im.size, (236, 236, 236, 255)); bg.alpha_composite(im)
        im = bg.convert('RGB'); im.thumbnail((T, T), Image.LANCZOS)
        t = Image.new('RGB', (T, T), (236, 236, 236)); t.paste(im, ((T - im.width) // 2, (T - im.height) // 2)); return t

    for i, stem in enumerate(stems):
        m = int(stem[:3]); car = cars[m]; y = 30 + i * (T + head + pad) + head
        g1 = next((os.path.join(d, stem + '.glb') for d in a.v1.split(',') if os.path.exists(os.path.join(d, stem + '.glb'))), '')
        g2 = os.path.join(a.v2, stem + '.glb')
        left = [thumb(os.path.join(root, car['remaps'][0]['file_x4']))] + (tiles(g1) if os.path.exists(g1) else [])
        concept = os.path.join(a.v2, 'concept', f"{stem}_3q_v3.png")
        right = ([thumb(concept)] if os.path.exists(concept) else [Image.new('RGB', (T, T), (60, 60, 60))]) + tiles(g2)
        for j, t in enumerate(left):
            sheet.paste(t, (pad + j * T, y))
        for j, t in enumerate(right):
            sheet.paste(t, (2 * pad + n * T + j * T, y))
        b, e = before.get(m), after.get(m)
        txt = f"{m:03d} {car['name']}"
        if b:
            txt += f"   v1 total {b['total']:.2f} (lighting {b.get('lighting', 0):.2f})"
        d.text((pad, y - head + 3), txt, fill=(255, 220, 120))
        if e:
            d.text((2 * pad + n * T, y - head + 3), f"{a.label} total {e['total']:.2f} (lighting {e.get('lighting', 0):.2f})" +
                   ('   INTEGRATED' if e.get('integrated') else ''), fill=(140, 230, 140) if b and e['total'] > b['total'] else (255, 150, 150))
    sheet.save(a.out)
    print(a.out, sheet.size, len(stems), 'rows')


if __name__ == '__main__':
    main()
