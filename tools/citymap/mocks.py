import math, sys, time, os
from PIL import Image
import gmp, mapart, roadgraph as rg, ui

HERE = os.path.dirname(os.path.abspath(__file__))
# Paths: CITYMAP_GAME (the game's data folder, default <repo>/../game/data), CITYMAP_OUT (where the
# pictures go, default /tmp/citymap), CITYMAP_REF (stock game frames for the backdrops: third.png,
# third_nohud.png, plain15.png, chase.png; optional).
G = os.environ.get("CITYMAP_GAME", os.path.join(HERE, "..", "..", "..", "game", "data"))
OUT = os.environ.get("CITYMAP_OUT", "/tmp/citymap")
REF = os.environ.get("CITYMAP_REF", os.path.join(OUT, "ref"))
os.makedirs(OUT, exist_ok=True)
gxt = gmp.read_gxt(os.path.join(G, "e.gxt"))
PPC = 12

def fmt_m(cells):
    m = cells * ui.MPB
    return f"{m / 1000:.2f} KM" if m >= 1000 else f"{int(round(m / 10) * 10)} M"

def zone_rect(L, key_or_name, typ=None):
    for t, x, y, w, h, k in L.zones:
        if (k == key_or_name or gxt.get(k) == key_or_name) and (typ is None or t == typ):
            return x, y, w, h
    raise KeyError(key_or_name)

def plan(lv, origin, heading, dest_name, mode="car"):
    L = gmp.Level(os.path.join(G, lv + ".gmp"))
    g = rg.Graph(L)
    x, y, w, h = zone_rect(L, dest_name, 15)
    dn = g.snap(x + w / 2, y + h / 2, None, (1,) if mode == "car" else (1, 2, 3), radius=20)
    t = time.time(); dist, nxt = g.cost_to(dn, mode); t1 = time.time() - t
    sn = g.start_node(origin[0], origin[1], 2.0, heading, dist, mode)
    origin = (g.nodes[sn][0] + 0.5, g.nodes[sn][1] + 0.5)
    path = g.path(sn, nxt)
    raw = g.polyline(path, centre=(mode == "car"), want=(1,) if mode == "car" else (1, 2, 3))
    pts = rg.fillet(raw, 1.4)
    plan.raw = raw
    return L, g, dn, sn, path, pts, t1, origin

def info_for(L, g, origin, dest_name, pts, extra_keys=True):
    nt = rg.next_turn(plan.raw)
    info = {"here": ui.zone_at(L, gxt, origin[0], origin[1]) or "", "dest": dest_name,
            "dist": fmt_m(rg.length(pts)),
            "turn": (fmt_m(nt[0]), nt[1]) if nt else None,
            "keys": [(["M"], "CLOSE"), (["ARROWS"], "CURSOR"), (["DRAG"], "PAN"),
                     (["WHEEL", "+", "-"], "ZOOM"), (["CLICK", "ENTER"], "SET WAYPOINT"),
                     (["RMB", "DEL"], "CLEAR"), (["HOME"], "FIND ME")]}
    return info

def main():
    p = os.path.join(REF, "third_nohud.png")
    backdrop = Image.open(p) if os.path.exists(p) else None   # the modern HUD steps aside while the map is open
    cases = {
        # level: origin (the player's spot, cells), heading (rad, 0 north), destination landmark
        "wil": ((150.5, 168.5), 0.0, "Zaibatsu HQ"),
        "ste": ((60.0, 120.5), math.pi / 2, "The Mall"),
        "bil": ((118.0, 118.0), math.pi, "Tower Square"),
    }
    size = (1280, 720)
    for lv, (origin, heading, dname) in cases.items():
        L, g, dn, sn, path, pts, t1, origin = plan(lv, origin, heading, dname)
        r0 = plan.raw
        heading = math.atan2(r0[1][0] - r0[0][0], -(r0[1][1] - r0[0][1]))   # along the first leg
        origin = pts[0]
        base_np, _ = mapart.bake(L, PPC, g)
        base = Image.fromarray(base_np)
        level = {"name": lv, "L": L}
        info = info_for(L, g, origin, dname, pts)
        dest = pts[-1]   # the pin stands where the line ends (the road's middle by the snapped lane)
        rect = (0, 58, 1280, 680)
        # whole city
        s_fit = (rect[3] - rect[1] - 24) / 256
        v = ui.View(rect, 128, 128, s_fit)
        img = ui.frame(level, gxt, base, PPC, size, v, origin, heading, dest, pts,
                       cursor={"xy": (dest[0] + 2.2, dest[1] - 3.0), "snap": dest, "label": "SET WAYPOINT  ·  " + dname.upper()},
                       backdrop=backdrop, info=info)
        img.save(os.path.join(OUT, f"mock_{lv}_city.png"))
        # zoomed on the player
        v2 = ui.View(rect, (origin[0] + dest[0]) / 2, (origin[1] + dest[1]) / 2, min(7.0, max(3.6, 0.8 * min(1280 / max(1, abs(origin[0] - dest[0])), 600 / max(1, abs(origin[1] - dest[1]))))))
        img2 = ui.frame(level, gxt, base, PPC, size, v2, origin, heading, dest, pts, cursor=None,
                        backdrop=backdrop, info=info)
        img2.save(os.path.join(OUT, f"mock_{lv}_zoom.png"))
        print(lv, "route", len(path), "nodes", f"{rg.length(pts):.0f} cells", f"search {t1 * 1000:.1f} ms", info["turn"])

if __name__ == "__main__":
    main()
