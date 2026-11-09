"""ASSET-PEDS comparison sheet: each GTA2 ped type (remap) as the game's sprite (full body and
top-down frames), beside its avatars rendered on the GPU (nvdiffrast) with the renderer's tint
rules (zones, or the legacy single tint for unzoned models).

    compare_sheet.py <models dir> <out prefix> [remap,remap,...]      (53 = the SWAT/FBI body)

Env: GTA2_ROOT (default /mnt/gta2/gta2-linux) for game/data/wil.sty and assets-src. Needs the
gen3d venv (torch, nvdiffrast, PIL)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import render
ROOT = os.environ.get('GTA2_ROOT', '/mnt/gta2/gta2-linux')
sys.path.insert(0, ROOT + '/assets-src/cars'); import parse_sty
from PIL import Image, ImageDraw, ImageFont
M=sys.argv[1].rstrip('/')+'/'; OUT=sys.argv[2]
man=json.load(open(M+'manifest.json'))
rep={e['name']:e for e in man['imported']}
types=man['ped_types']; outfits=man.get('ped_outfits',[])
by_remap={}
for t in types:
    for r in t['remaps']: by_remap.setdefault(r,t)
st=parse_sty.parse(ROOT + '/game/data/wil.sty')
names=json.load(open(ROOT + '/assets-src/humans/pedtypes/ped_types.json'))['remaps']
def spr(i, remap=None):
    abs_i=st['sprb'][0]+i
    virt=st['bases']['sprite']+abs_i if remap is None else st['bases']['ped_remap']+remap
    return st['sprite_rgba'](abs_i, st['palette'](st['phys'](virt)))
def sprite_of(r):
    if r==53: return [spr(f+316) for f in (113,0)]
    if r==-8: return [spr(f+158) for f in (113,0)]
    return [spr(f,r) for f in (113,0)]
def tints_for(model, r):
    e=rep.get(model,{})
    o=outfits[r] if 0<=r<len(outfits) else [0]*9
    t=by_remap.get(r,{})
    if not e.get('ped_zones') and t.get('tint') and r < len(man.get('ped_remap_colours', [])) and any(man['ped_remap_colours'][r]):
        c = man['ped_remap_colours'][r]   # the legacy single tint: remap colour over paint_rgb (235: not in the report)
        return lambda tex, node: [min(2.0, x / 235.0) for x in c] if '_paint' in tex else None
    if not e.get('ped_zones') or not t.get('tint'): return None
    ref=e.get('zone_ref',128.0)
    def zone(c, orig):
        if any(c): return [x/ref for x in c]
        return [x/ref for x in orig] if orig else [1,1,1]
    top=zone(o[0:3], e.get('zone_rgb_t')); bot=zone(o[3:6], e.get('zone_rgb_b'))
    hair=None
    if any(o[6:9]) and e.get('zone_rgb_h'): hair=[min(2.0, c/max(8.0,h)) for c,h in zip(o[6:9], e['zone_rgb_h'])]
    def f(tex,node):
        if '#pt' in node: return [min(2,x) for x in top]
        if '#pb' in node: return [min(2,x) for x in bot]
        if hair and '_opacity' in tex: return hair
        return None
    return f
remaps=[int(x) for x in sys.argv[3].split(',')] if len(sys.argv)>3 else list(range(53))+[53]
CW,CH=150,250; SPW=110
cells=[]
for r in remaps:
    t=by_remap.get(r); models=(t['models'] if t else man['pedestrians'][:2])[:3]
    sp=sprite_of(r)
    cell=Image.new('RGB',(SPW+CW*3,CH+18),(54,56,58)); d=ImageDraw.Draw(cell)
    big=sp[0].resize((sp[0].width*5,sp[0].height*5),Image.NEAREST); cell.paste(big,(4,10),big)
    sm=sp[1].resize((sp[1].width*3,sp[1].height*3),Image.NEAREST); cell.paste(sm,(30,10+big.height+8),sm)
    for k,mn in enumerate(models):
        im=render.render(M+mn+'.mesh',[(25,10)],tints=tints_for(mn,r),size=(CW,CH))[0]
        cell.paste(im,(SPW+k*CW,0))
        d.text((SPW+k*CW+2,CH+2),mn.replace('human_','')[:22],fill=(200,200,200))
    nm=names.get(str(r),{}).get('name','SWAT/FBI (EMERG body)' if r==53 else '?')
    d.rectangle([0,CH,SPW-2,CH+18],fill=(54,56,58)); d.text((2,CH+3),f'{r} {nm}'[:18],fill=(255,255,0))
    cells.append(cell)
cols=3; per=18
for p in range(0,len(cells),per):
    sub=cells[p:p+per]; rows=(len(sub)+cols-1)//cols
    sheet=Image.new('RGB',(cols*cells[0].width,rows*cells[0].height),(20,20,20))
    for i,c in enumerate(sub): sheet.paste(c,((i%cols)*c.width,(i//cols)*c.height))
    sheet.save(f'{OUT}_{p//per}.jpg',quality=90); print(f'{OUT}_{p//per}.jpg', sheet.size)
