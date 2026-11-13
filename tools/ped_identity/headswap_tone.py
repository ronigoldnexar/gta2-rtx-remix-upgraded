import sys, json, numpy as np
sys.path.insert(0, '/mnt/gta2/gta2-linux/wt_faces2/tools/ped_identity')
import faces, gmsh
from paint_resplit import read_tga, write_tga
M = '/mnt/gta2/gta2-linux/repo/stage/gta2dx9_models/'
C = '/home/roni_goldshmidt/hs2c3/'; combo = 'human_male_07^human_male_10'
mesh = gmsh.load(C + combo + '.mesh'); print([m['tex'] for m in mesh['meshes']])
A = faces.head(M, 'human_male_07'); B = faces.head(M, 'human_male_10')
ta = read_tga(M + A['head_tex']).astype(np.float32); tb = read_tga(M + B['head_tex']).astype(np.float32)
_, sa = faces.hair_mask(ta[..., :3], 0.5); mb, sb = faces.hair_mask(tb[..., :3], 0.5)
# the body's own skin: the neck and hands on the body map are what the head meets; use A's face skin (same avatar)
print('A skin', sa.round(1), 'B skin', sb.round(1))
ratio = sa / sb; print('ratio', ratio.round(3))
# toward A, three quarters of the way (keeps B's own face), not in the hair
k = 0.75; r = 1 + k * (ratio - 1)
skinw = (1 - mb)[..., None]
out = tb.copy(); out[..., :3] = np.clip(tb[..., :3] * (1 - skinw) + tb[..., :3] * r * skinw, 0, 255)
new = B['head_tex'][:-4] + '~s36.tga'
write_tga(out.astype(np.uint8), C + new); print('wrote', new)
raw = open(C + combo + '.mesh', 'rb').read()
old = B['head_tex'].encode(); pad = lambda s: s + b'\0' * (64 - len(s))
assert raw.count(pad(old)) >= 1
raw = raw.replace(pad(old), pad(new.encode())); open(C + combo + '.mesh', 'wb').write(raw)
for mp in (C + 'manifest.json', '/mnt/gta2/gta2-linux/wt_faces2/assets/models/manifest.json'):
    mm = json.load(open(mp))
    for e in mm['imported']:
        if e['name'] == combo: e['textures'] = [new if t == B['head_tex'] else t for t in e['textures']]; print(mp, e['textures'])
    open(mp, 'w').write(json.dumps(mm, indent=1))
rep = json.load(open(C + 'report.json')); rep[combo]['tex'] = [new if t == B['head_tex'] else t for t in rep[combo]['tex']]
json.dump(rep, open(C + 'report.json', 'w'), indent=1)
