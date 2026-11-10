import sys,subprocess,tempfile,glob,shutil
from PIL import Image; import numpy as np
# Van body (centre crop) vs the ground just behind it, per frame; a "leak" = the van's luma moves >25 % in
# 2 frames while the ground strip moves <10 %. Duplicate frames skipped.
W=np.array([0.299,0.587,0.114])
for mp4 in sys.argv[1:]:
    d=tempfile.mkdtemp(dir='/tmp/fx3')
    subprocess.run(['nice','-n','15','ffmpeg','-loglevel','error','-i',mp4,d+'/f_%03d.png'],check=True)
    V=[];G=[]
    for f in sorted(glob.glob(d+'/f_*.png')):
        a=np.asarray(Image.open(f).convert('RGB')).astype(float)
        V.append((a[330:520,500:740]@W).mean()); G.append((a[615:690,480:780]@W).mean())
    shutil.rmtree(d)
    V=np.array(V);G=np.array(G)
    keep=[0]+[i for i in range(1,len(V)) if abs(V[i]-V[i-1])>1e-6 or abs(G[i]-G[i-1])>1e-6]
    V=V[keep];G=G[keep]
    sv=np.abs(V[2:]/np.maximum(V[:-2],1)-1); sg=np.abs(G[2:]/np.maximum(G[:-2],1)-1)
    leaks=int(((sv>0.25)&(sg<0.10)).sum())
    print('%s frames %d | van 2-frame step p95 %.1f%% max %.1f%% | leak events %d | mean van/ground %.2f'%(mp4.split('/')[-1],len(V),np.percentile(sv,95)*100,sv.max()*100,leaks,(V/np.maximum(G,1)).mean()))
