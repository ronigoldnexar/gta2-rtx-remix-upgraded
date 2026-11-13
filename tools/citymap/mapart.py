"""CITYMAP-1 prototype: the full map's picture (what the DLL draws as rectangles), at a high
resolution once per level; views are crops of it."""
import numpy as np
from PIL import Image, ImageFilter
import gmp

W = H = 256

# On-screen colours (sRGB). The DLL feeds ImGui their 1/2.2 power (the HUD's display path squares them).
VOID = (7, 9, 13)
WATER = (14, 44, 66)
WATER_LINE = (22, 60, 86)
PAVE = (31, 36, 46)
PARK = (24, 50, 34)
BLD = [(45, 52, 67), (54, 63, 81), (64, 75, 96), (64, 75, 96), (64, 75, 96)]   # low, mid, tall
ROAD = (198, 203, 212)
ROAD_EDGE = (120, 126, 138)
TUNNEL = (92, 98, 112)
RAIL = (92, 74, 58)

def classify(L):
    # lid tile 1023 is the overhead cables' (the long diagonal wires): not a surface
    has = (L.lid > 0) & (L.lid != 1023)
    # the overhead wires: stacks of sideless 45-degree slope blocks of air ground strung across the city
    nosides = ~(L.side['l'] > 0) & ~(L.side['r'] > 0) & ~(L.side['t'] > 0) & ~(L.side['b'] > 0)
    below_empty = np.ones_like(nosides)
    below_empty[1:] = ~((L.lid[:-1] > 0) | ~nosides[:-1])
    # strung high over the streets, one cell wide, of air ground, held by nothing below
    wires = nosides & below_empty & ((L.slopetype >= 41) | (L.ground == 0))
    wires[:3] = False
    has &= ~wires
    top = np.where(has.any(0), 7 - np.argmax(has[::-1], axis=0), -1)
    yy, xx = np.indices((H, W))
    tz = np.clip(top, 0, 7)
    g = L.ground[tz, yy, xx]
    lid = L.lid[tz, yy, xx]
    water = ((lid >= 608) & (lid <= 619)) | (top <= 0)
    cls = np.zeros((H, W), np.uint8)      # 0 void, 1 water, 2 pave, 3 park, 4 building, 5 road
    height = np.zeros((H, W), np.int8)
    cls[(g == 2) & (top <= 2)] = 2
    cls[(g == 0) & (top <= 1)] = 2
    cls[(g == 3) & (top <= 2)] = 3
    bld = ((g == 0) & (top >= 2)) | ((g == 2) & (top >= 3)) | ((g == 3) & (top >= 3))
    cls[bld] = 4
    height[bld] = np.clip(top[bld] - 2, 0, 4)
    cls[g == 1] = 5
    cls[water] = 1
    cls[top < 0] = 1
    # roads under something (tunnels, under decks): a road lid below the top that is not built over
    road_any = ((L.ground == 1) & has)
    lower = road_any.copy()
    for y, x in zip(*np.nonzero(road_any.any(0))):
        pass
    under = np.zeros((H, W), bool)
    for z in range(7):
        under |= road_any[z] & (z < top)
    under &= cls != 5
    elevated = (cls == 5) & (top >= 2)
    # one-cell speckle (a lamp, a pillar, a vent) merged into its surroundings, as the mini-map does
    for _ in range(2):
        c2 = cls.copy()
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                t = cls[y, x]
                if t == 5 or t == 1:
                    continue
                if cls[y - 1, x] == t or cls[y + 1, x] == t or cls[y, x - 1] == t or cls[y, x + 1] == t:
                    continue
                nb = cls[y - 1:y + 2, x - 1:x + 2].ravel().tolist(); nb.pop(4)
                best = max(set(nb), key=nb.count)
                if nb.count(best) >= 5 and best != 5:
                    c2[y, x] = best
        cls = c2
    # roads that something passes over (a viaduct, a deck, a tunnel's roof): drawn as road under it
    roadbase = np.zeros((H, W), bool)
    for z in range(1, 7):
        rz = (L.ground[z] == 1) & (L.lid[z] > 0)
        if z + 1 < 8:
            built = L.valid[z + 1] & (L.lid[z + 1] > 0) & (L.ground[z + 1] == 0) & \
                (L.wall['l'][z + 1] | L.wall['r'][z + 1] | L.wall['t'][z + 1] | L.wall['b'][z + 1])
            rz &= ~built
        roadbase |= rz
    cover = roadbase & (cls != 5)
    # a lamp head or a sign over the kerb is not an overpass: covers of under 4 cells are dropped
    from collections import deque
    seen = np.zeros_like(cover)
    for sy, sx in zip(*np.nonzero(cover)):
        if seen[sy, sx]:
            continue
        comp = []; q = deque([(sy, sx)]); seen[sy, sx] = True
        while q:
            y, x = q.popleft(); comp.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W and cover[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; q.append((ny, nx))
        if len(comp) < 4:
            for y, x in comp:
                cover[y, x] = False
                cls[y, x] = 5
    # building heights in three steps, smoothed by a 3x3 majority so a roof reads as one plate
    hq = np.where(cls == 4, np.minimum(height, 4) // 2 + 1, 0).astype(np.int8)   # 1 low, 2 mid, 3 tall
    pad = np.pad(hq, 1)
    votes = np.stack([pad[1 + dy:H + 1 + dy, 1 + dx:W + 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    counts = np.stack([(votes == k).sum(0) for k in range(4)])
    maj = counts[1:].argmax(0) + 1
    height = np.where(cls == 4, np.where(counts[1:].max(0) >= 5, maj, hq), 0).astype(np.int8) - 1
    # the railway: flood from the map's track zones over the track band of lid tiles (540..600),
    # as world_view.cpp seeds the girders
    rail = np.zeros((H, W), bool)
    tl = L.lid[np.clip(top, 0, 7), yy, xx]
    seeds = [(x, y) for t, zx, zy, zw, zh, n in L.zones if n.lower().startswith('trak')
             for y in range(zy, zy + zh) for x in range(zx, zx + zw)]
    stack = list(seeds)
    seen = np.zeros((H, W), bool)
    while stack:
        x, y = stack.pop()
        if not (0 <= x < W and 0 <= y < H) or seen[y, x]:
            continue
        seen[y, x] = True
        if not (540 <= tl[y, x] <= 600):
            continue
        rail[y, x] = True
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and 540 <= tl[ny, nx] <= 600 and abs(int(top[ny, nx]) - int(top[y, x])) <= 1:
                stack.append((nx, ny))
    return cls, height, top, cover, elevated, rail

def bake(L, ppc=12, graph=None):
    """the map at ppc pixels a cell (RGB numpy)"""
    cls, hgt, top, cover, elevated, rail = classify(L)
    if graph is not None:
        # road lids no car can reach and no arrow runs on, up in the air: the elevated railway's bed
        for i, n in enumerate(graph.nodes):
            x, y, z, gr, sl, ar = n[:6]
            if gr == 1 and ar == 0 and z >= 3 and not graph.main['car'][i] and top[y, x] == z:
                rail[y, x] = True
                cls[y, x] = 2
    S = ppc
    up = lambda a: np.repeat(np.repeat(a, S, 0), S, 1)
    C = up(cls); Hh = up(hgt)
    img = np.zeros((H * S, W * S, 3), np.float32)
    img[:] = VOID
    img[C == 1] = WATER
    # water: faint horizontal scan lines, the retro screen look
    ys = np.arange(H * S)[:, None]
    wl = (C == 1) & ((ys % 6) == 0)
    img[wl] = WATER_LINE
    img[C == 2] = PAVE
    img[C == 3] = PARK
    # tunnels: a darker road through whatever covers them, drawn under the buildings' shadow
    # building shadow toward the bottom right, longer for taller blocks
    bmask = C == 4
    shadow = np.zeros(bmask.shape, np.float32)
    for h in range(5):
        m = (bmask & (Hh == h)).astype(np.float32)
        off = int(S * (0.25 + 0.12 * h))
        sh = np.zeros_like(m)
        sh[off:, off:] = m[:-off, :-off]
        shadow = np.maximum(shadow, sh * (0.55 + 0.06 * h))
    shadow[bmask] = 0
    sh_img = Image.fromarray((shadow * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(S * 0.18))
    shadow = np.asarray(sh_img).astype(np.float32) / 255
    shadow[bmask | (C == 5)] = 0          # roads stay clean
    img *= (1 - 0.6 * shadow[..., None])
    for h in range(5):
        img[bmask & (Hh == h)] = BLD[h]
    # building top edges: a lighter rim on the lit (top/left) side, a darker one opposite
    key = np.where(bmask, 10 + Hh, 0)
    edge_w = max(1, S // 8)
    lit = np.zeros(bmask.shape, bool); dark = np.zeros(bmask.shape, bool)
    for k in range(1, edge_w + 1):
        lit[k:, :] |= bmask[k:, :] & (key[k:, :] > key[:-k, :])
        lit[:, k:] |= bmask[:, k:] & (key[:, k:] > key[:, :-k])
        dark[:-k, :] |= bmask[:-k, :] & (key[:-k, :] > key[k:, :])
        dark[:, :-k] |= bmask[:, :-k] & (key[:, :-k] > key[:, k:])
    img[lit] = np.minimum(255, img[lit] * 1.28 + 6)
    img[dark & ~lit] *= 0.78
    # roads, with a thin darker kerb line where a road meets anything else
    COV = up(cover)
    R = (C == 5) | COV
    under_col = img.copy()
    img[R] = ROAD
    kerb = np.zeros(R.shape, bool)
    kw = max(1, S // 10)
    for k in range(1, kw + 1):
        kerb[k:, :] |= R[k:, :] & ~R[:-k, :]
        kerb[:-k, :] |= R[:-k, :] & ~R[k:, :]
        kerb[:, k:] |= R[:, k:] & ~R[:, :-k]
        kerb[:, :-k] |= R[:, :-k] & ~R[:, k:]
    img[kerb] = ROAD_EDGE
    # what passes over a road: its own colour at half strength, rimmed, so the road reads through
    img[COV] = img[COV] * 0.42 + under_col[COV] * 0.58
    rim = np.zeros(COV.shape, bool)
    for k in range(1, max(1, S // 8) + 1):
        rim[k:, :] |= COV[k:, :] & ~COV[:-k, :]
        rim[:-k, :] |= COV[:-k, :] & ~COV[k:, :]
        rim[:, k:] |= COV[:, k:] & ~COV[:, :-k]
        rim[:, :-k] |= COV[:, :-k] & ~COV[:, k:]
    img[rim & R] = (24, 28, 36)
    # elevated decks: a dark casing outside the deck (it reads as crossing over)
    E = up(elevated)
    case = np.zeros(E.shape, bool)
    cw = max(1, S // 6)
    for k in range(1, cw + 1):
        case[k:, :] |= ~R[k:, :] & E[:-k, :]
        case[:-k, :] |= ~R[:-k, :] & E[k:, :]
        case[:, k:] |= ~R[:, k:] & E[:, :-k]
        case[:, :-k] |= ~R[:, :-k] & E[:, k:]
    img[case] = (10, 12, 16)
    # railway: a dark bed with a lighter rail line, over everything (it runs on viaducts)
    RL = up(rail)
    img[RL] = img[RL] * 0.35 + np.array(RAIL) * 0.65
    edge = np.zeros(RL.shape, bool)
    for k in range(1, max(1, S // 8) + 1):
        edge[k:, :] |= RL[k:, :] & ~RL[:-k, :]
        edge[:-k, :] |= RL[:-k, :] & ~RL[k:, :]
        edge[:, k:] |= RL[:, k:] & ~RL[:, :-k]
        edge[:, :-k] |= RL[:, :-k] & ~RL[:, k:]
    img[edge] = (16, 14, 14)
    self_rail = rail
    return np.clip(img, 0, 255).astype(np.uint8), cls
