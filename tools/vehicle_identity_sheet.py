#!/usr/bin/env python3
"""Identity sheet: each generated car model beside the GTA2 sprite it must be recognised as.

One row per model: sprite (x4, default paint and one remap) | model top view | 3/4 front | side, for one
model dir and optionally a second (new candidates) drawn after it. The sprite and the top view are both
nose-down (GTA2 draws its car sprites nose-down; the GLBs face +z). For judging recognisability by eye,
not a scorer (ASSET-VEHICLES, docs/car-3d-pipeline.md round 9).

    gen3d/venv/bin/python repo/tools/vehicle_identity_sheet.py --catalog assets-src/cars/catalog.json \
        --dirs assets-src/cars/models3d [--dirs2 <new dir>] --out out/asset_vehicles/identity.png [--models 0,1]
"""
import argparse, json, os, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'gen3d'))
sys.path.insert(0, os.environ.get('GEN3D', os.path.join(os.getcwd(), 'gen3d')))  # run from the workspace root


def glb_for(d, m):
    if not d or not os.path.isdir(d):
        return None
    for f in sorted(os.listdir(d)):
        if f.endswith('.glb') and f[:3] == '%03d' % m:
            return os.path.join(d, f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', required=True); ap.add_argument('--dirs', required=True)
    ap.add_argument('--dirs2', default=None, help='second model dir (new candidates) drawn after the first')
    ap.add_argument('--out', required=True); ap.add_argument('--models', default=None)
    ap.add_argument('--tile', type=int, default=150); ap.add_argument('--cols', type=int, default=2)
    a = ap.parse_args()
    import render_glb as R
    import nvdiffrast.torch as dr
    ctx = dr.RasterizeCudaContext()
    cat = json.load(open(a.catalog)); root = os.path.dirname(os.path.abspath(a.catalog))
    want = {int(m) for m in a.models.split(',')} if a.models else None
    T = a.tile; cells = []
    for c in cat['cars']:
        m = c['model']
        if want is not None and m not in want:
            continue
        g1 = glb_for(a.dirs, m); g2 = glb_for(a.dirs2, m) if a.dirs2 else None
        if g1 is None and g2 is None:
            continue
        rem = c['remaps']
        spr = [Image.open(os.path.join(root, rem[0]['file_x4'])).convert('RGBA')]
        if len(rem) > 2:
            spr.append(Image.open(os.path.join(root, rem[2]['file_x4'])).convert('RGBA'))
        tiles = []
        for s in spr:
            bg = Image.new('RGBA', s.size, (237, 237, 237, 255)); bg.alpha_composite(s)
            s = bg.convert('RGB'); s.thumbnail((T, T)); t = Image.new('RGB', (T, T), (237, 237, 237))
            t.paste(s, ((T - s.width) // 2, (T - s.height) // 2)); tiles.append(t)
        for g in (g1, g2):
            if g is None:
                continue
            meshes = R.load(g)
            for v in ('top', '3q', 'side'):
                tiles.append(Image.fromarray(R.render(meshes, v, T * 2, ctx)).resize((T, T), Image.LANCZOS))
        row = Image.new('RGB', (len(tiles) * T, T + 16), (30, 30, 34))
        for i, t in enumerate(tiles):
            row.paste(t, (i * T, 16))
        ImageDraw.Draw(row).text((4, 2), '%03d %s  (%s)  %s' % (m, c['name'], c['cls'],
                                 '' if g2 is None else 'right: ' + os.path.basename(os.path.dirname(g2))), fill=(255, 220, 120))
        cells.append(row)
        print(m, c['name'], flush=True)
    cw = max(r.width for r in cells); ch = max(r.height for r in cells); cols = a.cols
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (cw + 8), rows * (ch + 6)), (20, 20, 22))
    for i, r in enumerate(cells):
        sheet.paste(r, ((i % cols) * (cw + 8), (i // cols) * (ch + 6)))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out); print(a.out, sheet.size)


if __name__ == '__main__':
    main()
