import sys,re,os,glob
from PIL import Image; import numpy as np
# For each run: the blast's log time, the shots taken within 0..1.6 s after it (keys.log times, 1 s
# resolution, so -1 s margin), the worst flash share (lum>200 or hot orange inside the letterbox).
def flash(f):
    a=np.asarray(Image.open(f).convert('RGB')).astype(float)[90:630]
    lum=a.mean(2); return ((lum>200)|((a[:,:,0]>220)&(a[:,:,1]>150))).mean()
def secs(t): h,m,s=t.split(':'); return int(h)*3600+int(m)*60+float(s)
for r in sys.argv[1:]:
    log=open(r+'/gta2dx9.log',errors='replace').read() if os.path.exists(r+'/gta2dx9.log') else ''
    m=re.search(r'\[(\d\d:\d\d:\d\d\.\d+)\] explosions: blast',log)
    if not m: print(r,'no blast'); continue
    tb=secs(m.group(1))
    sc=re.search(r'blast probe: age 0\.0\d.*additive ([\d.]+) x ([\d.]+)',log)
    shots=[]
    for line in open(r+'/keys.log',errors='replace'):
        mm=re.match(r'(\d\d:\d\d:\d\d) shot (\S+)',line)
        if mm and -1.0<=secs(mm.group(1))-tb<=1.6 and os.path.exists(f'{r}/qa_{mm.group(2)}.png'): shots.append(mm.group(2))
    vals=[(s,flash(f'{r}/qa_{s}.png')) for s in shots]
    w=max(vals,key=lambda v:v[1]) if vals else ('-',0)
    print('%s blast %s | %d frames in 0-1.6 s | worst %s %.2f | %s'%(r,m.group(1),len(vals),w[0],w[1],('first-frame additive %s x %s'%sc.groups()) if sc else 'no probe'))
