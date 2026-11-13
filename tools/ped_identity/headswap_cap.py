"""Cap head-only head-swap combos: up to K heads per body, spreading heads (least-used first, then the tighter seam)."""
import sys, json, os, shutil, collections
src, dst, K, man = sys.argv[1].rstrip('/') + '/', sys.argv[2].rstrip('/') + '/', int(sys.argv[3]), sys.argv[4]
rep = json.load(open(src + 'report.json')); os.makedirs(dst, exist_ok=True)
byA = collections.defaultdict(list)
for c in rep: byA[c.split('^')[0]].append(c)
used = collections.Counter(); keep = {}
for rnd in range(K):
    for A in sorted(byA, key=lambda a: len(byA[a])):
        left = [c for c in byA[A] if c not in keep]
        if not left: continue
        c = min(left, key=lambda c: (used[c.split('^')[1]], rep[c]['seam_mm'][1]))
        keep[c] = rep[c]; used[c.split('^')[1]] += 1
for c in keep: shutil.copy(src + c + '.mesh', dst + c + '.mesh')
json.dump(keep, open(dst + 'report.json', 'w'), indent=1)
mm = json.load(open(man))
mm['models'] = [e for e in mm['models'] if '^' not in e['name'] or e['name'] in keep]
mm['imported'] = [e for e in mm['imported'] if '^' not in e['name'] or e['name'] in keep]
open(man, 'w').write(json.dumps(mm, indent=1))
print(len(keep), 'combos,', len(used), 'heads,', len(byA), 'bodies,', sum(os.path.getsize(dst + c + '.mesh') for c in keep) / 1e6, 'MB')
