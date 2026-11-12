"""PEDS-VARIETY: the civilian crowd's curated outfits (top, bottom) drawn per seed with pairing guardrails.

The reviewed prototype; dll/src/identity.cpp CivilianOutfit is a port of outfit() (same palettes in the same
order, same hash, same guardrails): change both together. crowd() emulates the DLL's DerivePed / CrowdVariety
for the sheets (tools/ped_identity/crowd_sheet.py)."""
import colorsys
TOPS_M = {'navy': (40, 52, 88), 'charcoal': (62, 64, 68), 'off-white': (212, 208, 196), 'olive': (92, 98, 60),
          'burgundy': (112, 36, 46), 'sky': (136, 168, 200), 'tan': (176, 150, 112), 'forest': (40, 78, 54),
          'brick': (146, 64, 44), 'mustard': (160, 132, 64), 'slate': (72, 98, 136), 'teal': (44, 112, 118),
          'black': (32, 32, 36), 'grey': (128, 130, 134), 'rust': (132, 76, 48)}
TOPS_F = {'navy': (40, 52, 88), 'off-white': (214, 210, 200), 'burgundy': (118, 38, 52), 'sky': (140, 172, 206),
          'blush': (206, 146, 160), 'coral': (214, 112, 92), 'lavender': (150, 132, 178), 'cream': (224, 212, 184),
          'red': (172, 44, 42), 'plum': (96, 52, 92), 'teal': (44, 116, 122), 'mustard': (164, 134, 66),
          'black': (32, 32, 36), 'forest': (40, 80, 56), 'slate': (76, 100, 138)}
BOTTOMS = {'denim': (58, 74, 104), 'dark denim': (38, 46, 66), 'black': (32, 32, 36), 'charcoal': (62, 64, 68),
           'khaki': (172, 156, 118), 'brown': (92, 68, 50), 'grey': (112, 114, 118), 'navy': (36, 44, 72),
           'olive': (82, 86, 58)}
TOPS_FORMAL = {'white': (218, 216, 210), 'pale blue': (168, 188, 212), 'grey': (140, 142, 146), 'navy': (44, 54, 84),
               'charcoal': (66, 68, 72), 'pale pink': (214, 184, 188)}
BOTTOMS_FORMAL = {'charcoal': (62, 64, 68), 'black': (32, 32, 36), 'navy': (36, 44, 72), 'grey': (112, 114, 118)}
BOTTOMS_F = dict(BOTTOMS, **{'cream': (206, 198, 178), 'burgundy': (100, 34, 44)})

def sat(c):
    h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in c]); return s * (1 - abs(2 * l - 1))   # chroma
def dist(a, b): return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
def mix(seed):
    seed = (seed ^ (seed >> 16)) * 0x7feb352d & 0xffffffff; seed = (seed ^ (seed >> 15)) * 0x846ca68b & 0xffffffff
    return seed ^ (seed >> 16)

def outfit(seed, female, formal=False):
    """None = the avatar's own colours (about 1 in 4)."""
    h = mix(seed)
    if h % 4 == 0: return None
    tops = list((TOPS_FORMAL if formal else TOPS_F if female else TOPS_M).items())
    bots = list((BOTTOMS_FORMAL if formal else BOTTOMS_F if female else BOTTOMS).items())
    for k in range(16):
        t = tops[(h >> 3) % len(tops)]; b = bots[(h >> 11) % len(bots)]
        ok = dist(t[1], b[1]) > (40 if formal else 70) and not (sat(t[1]) > 0.28 and sat(b[1]) > 0.28)   # distinct, at most one strong colour
        if ok: return t, b
        h = mix((h + k + 1) & 0xffffffff)   # uint32 wrap, as the DLL
    return None


# ---- The DLL's derivation of a crowd member (identity.cpp DerivePed + CrowdVariety, model_store.cpp) ----
OUTFIT_SALT = 0x632be5ab


def scramble(x):
    return mix(x & 0xffffffff)


def pool_model(seed, pool, remap):
    """ModelForPedestrian(seed, remap): dealt round the type's pool from a per-type offset."""
    return pool[((seed + scramble(remap + 1)) & 0xffffffff) % len(pool)] if pool else None


def crowd(seed, remap, model, entry, sprite_outfit, civilian=True):
    """The record's colours for a crowd member: dict(kind, top, bottom, label, zone=[t, b] multipliers or None,
    paint=multiplier or None, height, width). entry: the model's 'imported' manifest entry; sprite_outfit: the
    remap's ped_outfits row (9 numbers) or None (a type without tint)."""
    h = mix((seed ^ 0x9e3779b9) & 0xffffffff)
    height = 0.94 + 0.12 * (h & 255) / 255.0
    width = 0.95 + 0.10 * ((h >> 8) & 255) / 255.0
    shade = 0.88 + 0.24 * ((h >> 24) & 255) / 255.0
    ref = max(8.0, entry.get('zone_ref') or 128.0)
    zoned = bool(entry.get('ped_zones'))
    out = dict(height=height, width=width, zone=None, paint=None)
    if zoned and civilian:   # a curated outfit, else the avatar's own colours; shaded +-6% once
        o = outfit(seed ^ OUTFIT_SALT, 'female' in model, 'business' in model)
        s = 1.0 + (shade - 1.0) * 0.5
        own = [entry.get('zone_rgb_t') or [ref] * 3, entry.get('zone_rgb_b') or [ref] * 3]
        cols = [o[0][1], o[1][1]] if o else own
        out.update(kind='outfit' if o else 'own', label=(o[0][0] + ' / ' + o[1][0]) if o else 'own colours',
                   zone=[[max(0.0, min(2.0, s * c / ref)) for c in cols[k]] for k in range(2)])
        return out
    if zoned and sprite_outfit is not None:   # PedZoneTints (the type has tint 1), then the full shade
        own = [entry.get('zone_rgb_t') or [ref] * 3, entry.get('zone_rgb_b') or [ref] * 3]
        z = []
        for k in range(2):
            want = sprite_outfit[3 * k:3 * k + 3] if sum(sprite_outfit[3 * k:3 * k + 3]) >= 1 else own[k]
            z.append([min(2.0, max(0.0, min(2.0, c / ref)) * shade) for c in want])
        out.update(kind='sprite', label='sprite colours', zone=z)
        return out
    if civilian and not zoned and any('_paint' in t for t in entry.get('textures', [])) and ((h >> 16) & 3) != 0:
        c = EVERYDAY[(h >> 18) % len(EVERYDAY)]
        paint = entry.get('paint_rgb') or [235.0] * 3
        out.update(kind='everyday', label='everyday %d,%d,%d' % tuple(c),
                   paint=[max(0.3, min(2.0, 1.0 + (c[k] / max(8.0, paint[k]) - 1.0) * 0.85)) for k in range(3)])
        return out
    out.update(kind='own', label='own colours')
    return out


# identity.cpp kClothes: the old everyday palette, for civilians on avatars with a "_paint" half and no zones
EVERYDAY = [(38, 52, 92), (60, 62, 66), (28, 28, 32), (196, 178, 140), (92, 100, 58), (118, 32, 44),
            (70, 104, 150), (214, 212, 204), (128, 130, 134), (110, 76, 50), (36, 80, 52), (200, 160, 50),
            (40, 120, 124), (176, 46, 40), (210, 140, 160), (140, 176, 210), (160, 146, 104), (90, 60, 110),
            (230, 120, 60), (84, 40, 34)]
