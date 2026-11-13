"""PEDS-VARIETY-3: make the rocketbox folder for a built variant (glb from Blender + the base's colour textures,
the tie painted as the white shirt), its manifest entry, and import it. gen3d venv python.
  haredi_build.py <variant folder> <base folder> <built glb> [tie]"""
import json, os, sys, shutil, glob, subprocess, numpy as np
from PIL import Image, ImageDraw
H = '/mnt/gta2/gta2-linux/assets-src/humans/'; R = H + 'rocketbox/'
name, base, glb = sys.argv[1], sys.argv[2], sys.argv[3]; tie = 'tie' in sys.argv[4:]
d = R + name; os.makedirs(d, exist_ok=True)
for t in glob.glob(R + base + '/*_color*.tga'): shutil.copy(t, d)
shutil.copy(glb, d + '/' + name + '.glb')
if tie:
    # The Rocketbox business suits share one body layout: the tie is its own UV island at the bottom centre of the
    # body map and the shirt front a patch in the middle (with the knot painted on it). Both become the white shirt.
    bt = [t for t in glob.glob(d + '/*_body_color.tga')][0]
    a = np.asarray(Image.open(bt).convert('RGB')).astype(np.float32); Hh, W = a.shape[:2]
    lum = a @ np.array([0.3, 0.59, 0.11])
    def rect(u0, v0, u1, v1):
        m = np.zeros(lum.shape, bool); m[int(v0 * Hh):int(v1 * Hh), int(u0 * W):int(u1 * W)] = True; return m
    mx = a.max(2); sat = (mx - a.min(2)) / np.maximum(mx, 1)
    sel = (rect(0.33, 0.82, 0.63, 0.985) & ((sat > 0.12) | (lum > 90)) & (lum > 30)) | (rect(0.42, 0.40, 0.58, 0.64) & (lum > 55))
    shade = np.clip(lum / max(1.0, np.percentile(lum[sel], 90)), 0.62, 1.04)
    a[sel] = np.array([226, 226, 222])[None] * shade[sel][:, None]
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(bt)
    print('tie and shirt texels repainted', int(sel.sum()))
if 'legs' in sys.argv[4:] and os.path.exists(glb + '.legs.npy'):
    # opaque dark stockings: the skin of the lower legs, darkened with its shading kept
    polys = np.load(glb + '.legs.npy')
    bt = [t for t in glob.glob(d + '/*_body_color.tga')][0]
    im = Image.open(bt).convert('RGB'); W, Hh = im.size
    mask = Image.new('L', im.size, 0); dr = ImageDraw.Draw(mask)
    for p in polys: dr.polygon([(u * W, (1 - v) * Hh) for u, v in p], fill=255)
    a = np.asarray(im).astype(np.float32); m = np.asarray(mask) > 0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]; mx = a.max(2); sat = (mx - a.min(2)) / np.maximum(mx, 1)
    skin = m & (r > g) & (g > b) & (sat > 0.12) & (sat < 0.65) & (r > 60)
    lum = a @ np.array([0.3, 0.59, 0.11])
    shade = np.clip(lum / max(1.0, np.percentile(lum[skin], 85)) if skin.any() else 1, 0.55, 1.1)
    a[skin] = np.array([46, 42, 46])[None] * shade[skin][:, None]
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(bt)
    print('stocking texels', int(skin.sum()))
src = open(H + 'make_ped_manifest.py').read(); head = src[:src.index('folders = sorted(')]
dummy = '/tmp/peds3_dummy.json'; json.dump({'models': []}, open(dummy, 'w'))
ns = {'__file__': H + 'make_ped_manifest.py'}; sys_argv = sys.argv; sys.argv = ['x', dummy]
exec(compile(head, 'mpm', 'exec'), ns); sys.argv = sys_argv
e = ns['entry'](name)
if 'zones' in sys.argv[4:]: e['ped_zones'] = 1
mp = '/mnt/gta2/gta2-linux/assets-src/peds3_manifest.json'
man = json.load(open(mp)) if os.path.exists(mp) else {'models': [], 'cars': [], 'pedestrian': '', 'props': []}
man['models'] = [x for x in man['models'] if x['name'] != e['name']] + [e]
json.dump(man, open(mp, 'w'), indent=1)
os.makedirs('/home/roni_goldshmidt/peds3_models', exist_ok=True)
args = [sys.executable, '/mnt/gta2/gta2-linux/wt_peds3/tools/import_assets.py', mp, '/home/roni_goldshmidt/peds3_models']
if os.path.exists('/home/roni_goldshmidt/peds3_models/manifest.json'): args += ['--only', e['name']]
r = subprocess.run(args, capture_output=True, text=True)
print([l[:160] for l in (r.stdout + r.stderr).splitlines() if 'Error' in l or 'name' in l][:3])
print('entry', e['name'], e['material_textures'])
