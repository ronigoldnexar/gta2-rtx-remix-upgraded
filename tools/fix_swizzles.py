#!/usr/bin/env python3
"""Rewrites shader model 3 bytecode so Wine's wined3d and Windows read it the same way.

vkd3d-shader (Wine 10's d3dcompiler) writes source swizzles positionally, as D3D9 defines them:
`mov r0.w, r24.xxxy` takes r24.y. Wine 9's wined3d (the play image) reads a masked swizzle
packed, SM4-style, and takes r24.x - which turned the post's colour into its red channel
(VISUALS-PLAIN, 8 Nov). Masks x, xy, xyz, xyzw read the same either way; every other mask on a
component-wise instruction is split here into one instruction per component with a replicated
swizzle (`mov r0.w, r24.yyyy`), which also reads the same either way. Only the order of writes
changes, so an instruction whose destination is also one of its sources (and has more than one
component) is refused.   fix_swizzles.py <visuals_gen.h>   (rewrites in place)"""
import re, sys

COMPONENTWISE = {1, 2, 3, 4, 5, 10, 11, 12, 13, 18, 19, 34, 35, 46, 86, 87, 88}
SAFE_MASKS = {0x1, 0x3, 0x7, 0xF}

def reg_id(tok):
    return ((tok >> 28) & 7) | (((tok >> 11) & 3) << 3), tok & 0x7FF

def fix(words):
    out, i, n, split = [words[0]], 1, len(words), 0
    while i < n:
        tok = words[i]
        op = tok & 0xFFFF
        if op == 0xFFFE:                       # comment
            ln = (tok >> 16) & 0x7FFF
            out += words[i:i + 1 + ln]; i += 1 + ln; continue
        if op == 0xFFFF:                       # end
            out.append(tok); i += 1; continue
        ln = (tok >> 24) & 0xF
        body = words[i + 1:i + 1 + ln]
        if op in COMPONENTWISE and ln >= 2 and not any(t & (1 << 13) for t in body):
            dst, srcs = body[0], body[1:]
            mask = (dst >> 16) & 0xF
            if mask not in SAFE_MASKS:
                comps = [c for c in range(4) if mask & (1 << c)]
                aliased = [s for s in srcs if reg_id(s) == reg_id(dst)]
                if len(comps) > 1 and aliased:
                    # an order in which no component is read after it has been written
                    import itertools
                    def ok(order):
                        written = set()
                        for c in order:
                            if any(((s >> (16 + 2 * c)) & 3) in written for s in aliased): return False
                            written.add(c)
                        return True
                    order = next((o for o in itertools.permutations(comps) if ok(o)), None)
                    if order is None: raise SystemExit(f"aliasing {op} at word {i}: cannot split safely")
                    comps = list(order)
                for c in comps:
                    nd = (dst & ~(0xF << 16)) | (1 << (16 + c))
                    ns = []
                    for s in srcs:
                        sel = (s >> (16 + 2 * c)) & 3
                        rep = sel | (sel << 2) | (sel << 4) | (sel << 6)
                        ns.append((s & ~(0xFF << 16)) | (rep << 16))
                    out += [tok] + [nd] + ns
                split += 1
                i += 1 + ln; continue
        out += [tok] + body
        i += 1 + ln
    return out, split

path = sys.argv[1]
text = open(path).read()
def repl(m):
    words = [int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]{8}", m.group(2))]
    fixed, split = fix(words)
    print(f"{m.group(1)}: {split} instructions split, {len(words)} -> {len(fixed)} words")
    lines = ",".join(("\n    " if k % 8 == 0 else " ") + f"0x{w:08x}" for k, w in enumerate(fixed))
    return f"static const DWORD {m.group(1)}[] = {{{lines},\n}};"
text = re.sub(r"static const DWORD (\w+)\[\] = \{([^}]*)\};", repl, text)
open(path, "w").write(text)
