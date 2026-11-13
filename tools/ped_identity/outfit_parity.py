#!/usr/bin/env python3
"""PEDS-VARIETY: identity.cpp CivilianOutfit (compiled natively with g++) against outfits.outfit() for 20 000 seeds
x (men, women, formal). Usage: python3 tools/ped_identity/outfit_parity.py   (exit 1 on any mismatch)"""
import os, subprocess, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(here, '..', '..', 'dll', 'src', 'identity.cpp')).read()
tmp = tempfile.mkdtemp()
body = s[s.index('struct Garment'):s.index('constexpr uint32_t kOutfitSalt')] + s[s.index('constexpr Garment kModestTops'):s.index('void ModestOutfit')] + s[s.index('void ModestOutfit'):s.index('\n}\n', s.index('void ModestOutfit')) + 3] + s[s.index('constexpr uint32_t kFaceSalt'):s.index('void FaceVariety')] + s[s.index('constexpr uint32_t kDetailSalt'):s.index('constexpr const char* kDetailSuffix')] + s[s.index('int DetailPick'):s.index('\n}\n', s.index('int DetailPick')) + 3]
t = r'''#include <cstdint>
#include <cstdio>
#include <cmath>
#include <algorithm>
#include <iterator>
uint32_t Mix(uint32_t x) { x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16; return x; }
''' + body + r'''
int main() { for (uint32_t s = 0; s < 20000; ++s) for (int f = 0; f < 4; ++f) { Garment t, b;
  bool ok = CivilianOutfit(s * 2654435761u, f == 1, f == 2, f == 3, &t, &b);
  { FaceChoice fc = FacePick(s * 2654435761u, s % 2, s % 5, (s / 5) % 4, (s / 20) % 4, (s / 80) % 4); printf("f %u %d %d %d %d %d\n", s, fc.hair, fc.facial, fc.eye, fc.head, fc.colour); }
  { Garment mt, mb; ModestOutfit(s * 2654435761u, &mt, &mb); printf("m %u %d %d %d %d %d %d\n", s, mt.r, mt.g, mt.b, mb.r, mb.g, mb.b); }
  for (int n = 0; n < 4; ++n) printf("d %u %d %d\n", s, n, DetailPick(s * 2654435761u, n));
  if (ok) printf("%u %d %d %d %d %d %d %d\n", s, f, t.r, t.g, t.b, b.r, b.g, b.b); else printf("%u %d -\n", s, f); } }
'''
open(os.path.join(tmp, 't.cpp'), 'w').write(t)
subprocess.run(['g++', '-std=c++17', '-O1', '-o', os.path.join(tmp, 't'), os.path.join(tmp, 't.cpp')], check=True)
c = subprocess.run([os.path.join(tmp, 't')], capture_output=True, text=True, check=True).stdout.splitlines()
sys.path.insert(0, here); from outfits import outfit, detail_pick, modest_outfit, face_pick
p = []
for s_ in range(20000):
    for f in range(4):
        o = outfit((s_ * 2654435761) & 0xffffffff, f == 1, f == 2, f == 3)
        _f = face_pick((s_ * 2654435761) & 0xffffffff, bool(s_ % 2), s_ % 5, (s_ // 5) % 4, (s_ // 20) % 4, (s_ // 80) % 4); p.append(f'f {s_} ' + ' '.join(map(str, _f)))
        _m = modest_outfit((s_ * 2654435761) & 0xffffffff); p.append(f'm {s_} ' + ' '.join(map(str, _m[0][1] + _m[1][1])))
        p.extend(f'd {s_} {n} {detail_pick((s_ * 2654435761) & 0xffffffff, n)}' for n in range(4))
        p.append(f'{s_} {f} -' if not o else f'{s_} {f} ' + ' '.join(map(str, o[0][1] + o[1][1])))
bad = [(x, y) for x, y in zip(c, p) if x != y]
print('lines', len(c), len(p), 'mismatch', len(bad), bad[:3])
for f in range(4):
    rows = [x for x in c if not x.startswith(('d ', 'm ', 'f ')) and x.split()[1] == str(f)]
    print('kind', f, 'kept own', sum(x.endswith('-') for x in rows) / len(rows))
sys.exit(1 if bad else 0)
