"""In-game sheet: each remap's probe frames (RUN dir, REMAPS list, BOX crop) beside its sprite. Needs the gen3d venv (PIL)."""
import sys, json, os
sys.path.insert(0, '/mnt/gta2/gta2-linux/assets-src/cars'); import parse_sty
from PIL import Image, ImageDraw
R=os.environ.get('RUN','/mnt/gta2/gta2-linux/out/ap_r1/')
st=parse_sty.parse('/mnt/gta2/gta2-linux/game/data/wil.sty')
names=json.load(open('/mnt/gta2/gta2-linux/assets-src/humans/pedtypes/ped_types.json'))['remaps']
def spr(i, remap=None):
    abs_i=st['sprb'][0]+i
    virt=st['bases']['sprite']+abs_i if remap is None else st['bases']['ped_remap']+remap
    return st['sprite_rgba'](abs_i, st['palette'](st['phys'](virt)))
box=tuple(int(x) for x in os.environ.get('BOX','470,360,750,620').split(','))
CW,CH=200,186
cells=[]
order=[int(x) for x in os.environ.get('REMAPS','0,4,5').split(',')]
for r in order:
    cell=Image.new('RGB',(90+CW*3,CH+16),(40,40,40)); d=ImageDraw.Draw(cell)
    sp=spr(113+ (316 if r==53 else 0), None if r==53 else r)
    big=sp.resize((sp.width*4,sp.height*4),Image.NEAREST); cell.paste(big,(4,4),big)
    for k,s in enumerate('abc'):
        p=f'{R}qa_r{r:02d}_{s}.png'
        if os.path.exists(p): cell.paste(Image.open(p).convert('RGB').crop(box).resize((CW,CH)),(90+k*CW,0))
    d.text((2,CH+2),f"{r} {names.get(str(r),{}).get('name','SWAT/FBI body')}"[:40],fill=(255,255,0))
    cells.append(cell)
cols=3; per=27
for p in range(0,len(cells),per):
    sub=cells[p:p+per]; rows=(len(sub)+cols-1)//cols
    sh=Image.new('RGB',(cols*sub[0].width,rows*sub[0].height),(0,0,0))
    for i,c in enumerate(sub): sh.paste(c,((i%cols)*c.width,(i//cols)*c.height))
    sh.save(os.environ.get('OUT','ingame')+f'_{p//per}.jpg',quality=88); print(sh.size)
