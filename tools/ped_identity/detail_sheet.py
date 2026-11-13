import sys, json
sys.path.insert(0, '/mnt/gta2/gta2-linux/wt_peds3/tools/ped_identity'); import render
from PIL import Image, ImageDraw
out, pitch = sys.argv[1], float(sys.argv[2])
S = '/mnt/gta2/gta2-linux/stage_peds2/gta2dx9_models/'; D = '/home/roni_goldshmidt/peds3_detail/'
man = {e['name']: e for e in json.load(open(S + 'manifest.json'))['imported']}
rows = [('human_female_adult_17', [((140, 172, 206), (38, 46, 66), 'sky / dark denim'), ((40, 128, 134), (62, 64, 68), 'retro teal / charcoal')]),
        ('human_male_07', [((40, 52, 88), (58, 74, 104), 'navy / denim'), ((226, 104, 40), (50, 52, 58), 'retro orange / graphite')]),
        ('human_male_adult_20', [((128, 130, 134), (32, 32, 36), 'grey / black'), ((150, 100, 48), (70, 86, 108), 'retro ochre / slate')])]
vars_ = [('original', S), ('yoke', D + 'yoke/'), ('band', D + 'band/'), ('sleeve', D + 'sleeve/')]
CW, CH = (150, 260) if pitch < 60 else (150, 150)
sheet = Image.new('RGB', (len(vars_) * 2 * CW, len(rows) * (CH + 28)), (40, 42, 46)); d = ImageDraw.Draw(sheet)
for r, (n, outfits) in enumerate(rows):
    ref = man[n].get('zone_ref', 128.0)
    for vi, (vn, vd) in enumerate(vars_):
        for oi, (t, b, lab) in enumerate(outfits):
            tf = lambda tex, node, t=t, b=b: [c / ref for c in t] if '#pt' in node else [c / ref for c in b] if '#pb' in node else None
            if pitch < 60: im = render.render(vd + n + '.mesh', [(30, pitch)], tints=tf, size=(CW, CH))[0]
            else:
                big = render.render(vd + n + '.mesh', [(30, pitch)], tints=tf, size=(CW * 2, CH * 2))[0]; im = big.crop((CW // 2, CH // 2, CW // 2 + CW, CH // 2 + CH))
            x, y = (vi * 2 + oi) * CW, r * (CH + 28)
            sheet.paste(im, (x, y)); d.text((x + 3, y + CH + 2), vn, fill=(255, 255, 0)); d.text((x + 3, y + CH + 14), lab[:24], fill=(225, 225, 225))
    d.text((3, r * (CH + 28) + 3), n.replace('human_', ''), fill=(250, 200, 120))
sheet.save(out, quality=88); print(sheet.size)
