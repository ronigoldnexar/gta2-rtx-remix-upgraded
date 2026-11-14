#!/usr/bin/env python3
"""PEDS-VARIETY / PEDS-CONSISTENT: identity.cpp's outfit code (compiled natively with g++) against outfits.py:
CivilianOutfit with and without the sprite's colours (every civilian remap's ped_outfits row x men, women, formal,
jumpsuit), ModestOutfit, FacePick, HeadPick, DetailPick for 3000 seeds; then the consistency check: every civilian
remap x avatar of its pool x 200 seeds through outfits.crowd() (the DLL's CrowdVariety, the +-6% shade included):
the CIEDE2000 colour difference between the sprite's colour (the remap's ped_outfits row, what the classic view
shows) and the shown 3D colour, top and bottom, must be at most DE_MAX (12) for every zoned avatar; the outliers are
listed, and the fixed looks must be dealt only in the dark, neutral pools. Usage: python3 tools/ped_identity/outfit_parity.py [manifest]   (exit 1 on any mismatch or outlier)"""
import json, os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(here, '..', '..', 'dll', 'src', 'identity.cpp')).read()
man = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', '..', 'assets', 'models', 'manifest.json')))
rows = man['ped_outfits']
civ = sorted({r for t in man['ped_types'] if t['name'].startswith('civilian') for r in t['remaps']})
tmp = tempfile.mkdtemp()
body = s[s.index('struct Garment'):s.index('constexpr uint32_t kOutfitSalt')] + s[s.index('constexpr Garment kModestTops'):s.index('void ModestOutfit')] + s[s.index('void ModestOutfit'):s.index('\n}\n', s.index('void ModestOutfit')) + 3] + s[s.index('constexpr uint32_t kFaceSalt'):s.index('void FaceVariety')] + s[s.index('constexpr uint32_t kHeadSalt'):s.index('int DetailPick')] + s[s.index('constexpr uint32_t kDetailSalt'):s.index('constexpr const char* kDetailSuffix')] + s[s.index('int DetailPick'):s.index('\n}\n', s.index('int DetailPick')) + 3]
N = 3000
rowc = ',\n'.join('{' + ','.join(f'{float(v)}f' for v in rows[r][:9]) + '}' for r in civ)
t = r'''#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <algorithm>
#include <iterator>
#include <utility>
uint32_t Mix(uint32_t x) { x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16; return x; }
''' + body + r'''
const float kRows[][9] = {''' + rowc + r'''};
int main() { for (uint32_t s = 0; s < ''' + str(N) + r'''; ++s) { const uint32_t seed = s * 2654435761u;
  for (int f = 0; f < 4; ++f) { Garment t, b;
    bool ok = CivilianOutfit(seed, f == 1, f == 2, f == 3, nullptr, &t, &b);
    if (ok) printf("%u %d %d %d %d %d %d %d\n", s, f, t.r, t.g, t.b, b.r, b.g, b.b); else printf("%u %d -\n", s, f);
    for (uint32_t r = 0; r < std::size(kRows); ++r) { CivilianOutfit(seed, f == 1, f == 2, f == 3, kRows[r], &t, &b);
      printf("c %u %d %u %d %d %d %d %d %d\n", s, f, r, t.r, t.g, t.b, b.r, b.g, b.b); } }
  { FaceChoice fc = FacePick(seed, s % 2, s % 5, (s / 5) % 4, (s / 20) % 4, (s / 80) % 4); printf("f %u %d %d %d %d %d\n", s, fc.hair, fc.facial, fc.eye, fc.head, fc.colour); }
  { Garment mt, mb; ModestOutfit(seed, nullptr, &mt, &mb); printf("m %u %d %d %d %d %d %d\n", s, mt.r, mt.g, mt.b, mb.r, mb.g, mb.b);
    ModestOutfit(seed, kRows[s % std::size(kRows)], &mt, &mb); printf("ms %u %d %d %d %d %d %d\n", s, mt.r, mt.g, mt.b, mb.r, mb.g, mb.b); }
  for (int n = 0; n < 4; ++n) printf("h %u %d %d\n", s, n, HeadPick(seed, n * 7));
  for (int n = 0; n < 4; ++n) printf("d %u %d %d\n", s, n, DetailPick(seed, n)); } }
'''
open(os.path.join(tmp, 't.cpp'), 'w').write(t)
subprocess.run(['g++', '-std=c++17', '-O1', '-o', os.path.join(tmp, 't'), os.path.join(tmp, 't.cpp')], check=True)
c = subprocess.run([os.path.join(tmp, 't')], capture_output=True, text=True, check=True).stdout.splitlines()
sys.path.insert(0, here)
from outfits import outfit, detail_pick, modest_outfit, face_pick, head_pick, crowd, sprite_colours
from consistent_pools import dark_neutral, PARTIAL, partial_ok
p = []
for s_ in range(N):
    seed = (s_ * 2654435761) & 0xffffffff
    for f in range(4):
        o = outfit(seed, f == 1, f == 2, f == 3)
        p.append(f'{s_} {f} -' if not o else f'{s_} {f} ' + ' '.join(map(str, o[0][1] + o[1][1])))
        for i, r in enumerate(civ):
            o = outfit(seed, f == 1, f == 2, f == 3, rows[r])
            p.append(f'c {s_} {f} {i} ' + ' '.join(map(str, o[0][1] + o[1][1])))
    _f = face_pick(seed, bool(s_ % 2), s_ % 5, (s_ // 5) % 4, (s_ // 20) % 4, (s_ // 80) % 4); p.append(f'f {s_} ' + ' '.join(map(str, _f)))
    _m = modest_outfit(seed); p.append(f'm {s_} ' + ' '.join(map(str, _m[0][1] + _m[1][1])))
    _m = modest_outfit(seed, rows[civ[s_ % len(civ)]]); p.append(f'ms {s_} ' + ' '.join(map(str, _m[0][1] + _m[1][1])))
    p.extend(f'h {s_} {n} {head_pick(seed, n * 7)}' for n in range(4))
    p.extend(f'd {s_} {n} {detail_pick(seed, n)}' for n in range(4))
bad = [(x, y) for x, y in zip(c, p) if x != y]
print('parity: lines', len(c), len(p), 'mismatch', len(bad), bad[:3])
# the consistency check (PEDS-CONSISTENT): CIEDE2000 between the sprite's colour and the shown 3D colour
sys.path.insert(0, here); from outfit_parity_de import de2000
DE_MAX = 12.0
imp = {e['name']: e for e in man['imported']}
out, n, worst, des = [], 0, (0.0, None), []
for t in man['ped_types']:
    if not t['name'].startswith('civilian'): continue
    for r in t['remaps']:
        sc = sprite_colours(rows[r])
        for name in sorted(set(t['models'])):
            e = imp.get(name)
            if not e or not e.get('ped_zones'): continue   # the fixed looks (no zones): their pools are checked below
            ref = max(8.0, e.get('zone_ref') or 128.0)
            for k in range(200):
                seed = (k * 2654435761 + r * 40503) & 0xffffffff
                rec = crowd(seed, r, name, e, rows[r], True)
                shown = [tuple(int(min(255.0, z * ref) + 0.5) for z in rec['zone'][j]) for j in range(2)]
                n += 1
                for j in range(2):
                    d = de2000(sc[j], shown[j]); des.append(d)
                    if d > worst[0]: worst = (d, (r, name, 'top' if j == 0 else 'bottom', sc[j], shown[j]))
                    if d > DE_MAX: out.append((r, name, seed, 'top' if j == 0 else 'bottom', sc[j], shown[j], d))
fixed = ['human_haredi_male_01', 'human_haredi_male_02', 'human_haredi_female_01', 'human_female_adult_06', 'human_female_adult_10', 'human_business_female_01']
fixed_pools = {x: [r for t in man['ped_types'] if t['name'].startswith('civilian') and x in t['models'] for r in t['remaps']] for x in fixed}
loose = {x: [r for r in rs if not dark_neutral(rows[r])] for x, rs in fixed_pools.items()}
des.sort()
print('consistency: %d zoned civilians (remap x avatar x seed); CIEDE2000 sprite -> 3D: median %.2f, 95%% %.2f, max %.2f %s; %d over %.0f' %
      (n, des[len(des) // 2], des[int(len(des) * 0.95)], worst[0], worst[1], len(out), DE_MAX))
for o in out[:20]: print('  outlier remap %d %s seed %08x %s: sprite %s -> 3D %s, dE %.1f' % o)
print('fixed looks dealt in:', fixed_pools, '| in a pool that is not dark and neutral:', {x: rs for x, rs in loose.items() if rs})
part_pools = {x: [r for t in man['ped_types'] if t['name'].startswith('civilian') and x in t['models'] for r in t['remaps']] for x in PARTIAL}
loose.update({x: [r for r in rs if not partial_ok(x, rows[r])] for x, rs in part_pools.items()})
print('partly tinted avatars dealt in:', part_pools, '| where the sprite does not suit the untinted garment:', {x: [r for r in rs if not partial_ok(x, rows[r])] for x, rs in part_pools.items() if any(not partial_ok(x, rows[r]) for r in rs)})
sys.exit(1 if bad or out or any(loose.values()) else 0)
