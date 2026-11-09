"""ASSET-PEDS. Per ped remap outfit read from GTA2's own sprite palettes (wil.sty): colour of each body part
(torso shirt, forearms, thighs, shins, hair, skin, shoes), weighted by how many pixels of the
shared ped sprite set use each palette index. Writes outfits.json.

    ped_sprite_outfits.py <game>/data/wil.sty assets-src/humans/pedtypes/outfits.json
"""
import os, sys, json, collections, colorsys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assets-src', 'cars'))
sys.path.insert(0, '/mnt/gta2/gta2-linux/assets-src/cars')
import parse_sty
st = parse_sty.parse(sys.argv[1] if len(sys.argv)>1 else '/mnt/gta2/gta2-linux/game/data/wil.sty')
base=st['sprb'][0]
cnt=collections.Counter()
for f in range(158):
    w,h,rows=st['sprite'](base+f)
    for r in rows:
        for v in r:
            if v: cnt[v]+=1
G={'top':range(74,87),'forearm':range(224,233),'thigh':range(206,213),'shin':range(215,224),
   'hair':range(240,248),'skin':range(176,183),'shoe':range(192,197)}
import os
names=json.load(open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[2])) if len(sys.argv)>2 else '.', 'ped_types.json'))).get('remaps', {}) if len(sys.argv)>2 else {}
def mean(pal, rg):
    s=[0,0,0]; n=0
    for v in rg:
        c=cnt[v]
        if not c: continue
        b,g,r,_=pal[v]; s[0]+=r*c; s[1]+=g*c; s[2]+=b*c; n+=c
    return [round(x/n) for x in s]
def dist(a,b): return sum((x-y)**2 for x,y in zip(a,b))**.5
out={}
for r in range(st['palb'][3]):
    pal=st['palette'](st['phys'](st['bases']['ped_remap']+r))
    o={k:mean(pal,g) for k,g in G.items()}
    o['short_sleeves']=dist(o['forearm'],o['skin'])<dist(o['forearm'],o['top'])
    o['shorts']=dist(o['shin'],o['skin'])<dist(o['shin'],o['thigh'])
    o['bald']=dist(o['hair'],o['skin'])<40
    o['name']=names.get(str(r),{}).get('name','?')
    out[r]=o
    print(f"{r:2d} {o['name'][:26]:26s} top{o['top']} arm{o['forearm']} thigh{o['thigh']} shin{o['shin']} hair{o['hair']} skin{o['skin']} ss={int(o['short_sleeves'])} sh={int(o['shorts'])} bald={int(o['bald'])}")
json.dump(out,open(sys.argv[2] if len(sys.argv)>2 else 'outfits.json','w'),indent=1)
