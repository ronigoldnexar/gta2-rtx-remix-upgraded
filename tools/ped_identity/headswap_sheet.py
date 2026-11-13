import sys, glob, os
sys.path.insert(0, '/mnt/gta2/gta2-linux/wt_faces/tools/ped_identity'); import render
from PIL import Image, ImageDraw
M = '/mnt/gta2/gta2-linux/repo/stage/gta2dx9_models/'; D = '/home/roni_goldshmidt/headswap/'
pairs = [os.path.basename(f)[:-5] for f in sorted(glob.glob(D + '*__*.mesh'))]
CW, CH = 150, 240
cols = ['A body', 'B head', 'swap front', 'swap 3/4', 'neck front', 'neck back', 'neck side']
sheet = Image.new('RGB', (len(cols) * CW, len(pairs) * (CH + 18)), (40, 42, 46)); d = ImageDraw.Draw(sheet)
def neck(path, yaw, af):
    big = render.render(path, [(yaw, 4)], size=(CW * 6, CH * 6), anim_from=af, tex_dirs=(M,))[0]
    return big.crop((int(CW * 2.4), int(CH * 0.45), int(CW * 3.6), int(CH * 0.45) + int(CH * 1.2))).resize((CW, CH))
for r, p in enumerate(pairs):
    A, B = p.split('__')
    ims = [render.render(M + A + '.mesh', [(25, 6)], size=(CW, CH))[0], render.render(M + B + '.mesh', [(25, 6)], size=(CW, CH))[0],
           render.render(D + p + '.mesh', [(0, 6)], size=(CW, CH), anim_from=M + A + '.mesh', tex_dirs=(M,))[0],
           render.render(D + p + '.mesh', [(35, 6)], size=(CW, CH), anim_from=M + A + '.mesh', tex_dirs=(M,))[0],
           neck(D + p + '.mesh', 0, M + A + '.mesh'), neck(D + p + '.mesh', 180, M + A + '.mesh'), neck(D + p + '.mesh', 90, M + A + '.mesh')]
    for c, im in enumerate(ims): sheet.paste(im, (c * CW, r * (CH + 18)))
    d.text((3, r * (CH + 18) + CH + 3), f"{A.replace('human_', '')} <- head of {B.replace('human_', '')}", fill=(250, 200, 120))
for c, lab in enumerate(cols): d.text((c * CW + 3, 3), lab, fill=(255, 255, 0))
sheet.save('/home/roni_goldshmidt/peds_out/headswap.jpg', quality=88); print(sheet.size)
