#!/usr/bin/env python3
"""DISTRICTS-POC: where to look at a building from, worked out from the catalogue (no hand framing).

    frame_plan.py <work> <lvl> [id]   -> prints the JSON point list for linux/docker/districts_capture.py

The front is the building's longest straight run of street-level wall facing a road or pavement; the warp
point stands 1.5 cells out from its middle on the street; fixed poses (game frame: x east, y south, z up,
offsets from the point) look at it from the street (eye height), at a grazing angle close in (shows the
recess depth), obliquely from across the street and from above the roof line (cornice, parapet, roof plant)."""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap

OUT = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


def plan(work, lvl, bid):
    m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
    b = {x["id"]: x for x in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}[bid]
    runs = defaultdict(list)
    for f in b["faces"]:
        if f["lo"] > b["street"]:
            continue
        ox, oy = OUT[f["side"]]
        nx, ny = f["x"] + ox, f["y"] + oy
        if not (0 <= nx < 256 and 0 <= ny < 256) or m.top(nx, ny)[2] not in (1, 2):
            continue
        runs[(f["side"], f["y"] if f["side"] in "NS" else f["x"])].append(f)
    (side, line), fs = max(runs.items(), key=lambda kv: (len(kv[1]), sum(len(f["levels"]) for f in kv[1])))
    fs.sort(key=lambda f: (f["x"], f["y"]))
    mid = fs[len(fs) // 2]
    ox, oy = OUT[side]
    along = (oy, -ox) if side in "NS" else (-oy, ox)   # perpendicular in the map plane
    along = (1, 0) if side in "NS" else (0, 1)
    wx, wy = mid["x"] + 0.5 + ox * 0.5, mid["y"] + 0.5 + oy * 0.5        # the wall's middle, map frame
    OFF = 2.5                                                          # the warp point, out from the wall
    px, py = wx + ox * OFF, wy + oy * OFF
    z = float(b["street"])
    rise = b["roof"] - b["street"]
    def pose(name, out, side_, up, at_out, at_side, at_up, fov=60):
        return {"name": name, "eye": [round(ox * out + along[0] * side_ - ox * OFF, 3), round(oy * out + along[1] * side_ - oy * OFF, 3), up],
                "at": [round(ox * at_out + along[0] * at_side - ox * OFF, 3), round(oy * at_out + along[1] * at_side - oy * OFF, 3), at_up], "fov": fov}
    def free(gx, gy, gz):
        cx, cy = int(gx // 1), int(gy // 1)
        if not (0 <= cx < 256 and 0 <= cy < 256):
            return False
        return m.top(cx, cy)[0] <= gz - 0.2

    def fit(p_):
        """pull an eye that stands inside a building back toward the point until it is in the open"""
        for k in range(11):
            f = 1.0 - k * 0.08
            ex, ey = p_["eye"][0] * f, p_["eye"][1] * f
            if free(px + ex, py + ey, z + p_["eye"][2]):
                p_["eye"][0], p_["eye"][1] = round(ex, 3), round(ey, 3)
                return p_
        return p_

    poses = [
        pose("street", 4.0, 2.2, 0.45, 0.0, -0.4, min(rise, 3.0) * 0.55),
        pose("graze", 1.3, 1.6, 0.9, 0.05, -1.4, 1.3),
        pose("across", 5.5, -3.5, 2.2, 0.0, 0.5, rise * 0.5),
        pose("roof", 3.5, 1.5, rise + 1.6, 0.0, -0.5, rise - 0.3),
    ]
    poses = [fit(p_) for p_ in poses]
    return {"name": f"{lvl}_{bid}", "level": lvl, "building": bid, "front": side, "x": round(px, 2), "y": round(py, 2), "z": z,
            "face": [round(wx, 2), round(wy, 2)],
            "approach": [round(wx + ox * 2.0, 2), round(wy + oy * 2.0, 2)], "poses": poses}


if __name__ == "__main__":
    work, lvl = sys.argv[1], sys.argv[2]
    bid = int(sys.argv[3]) if len(sys.argv) > 3 else json.load(open(os.path.join(work, f"{lvl}_pick.json")))["id"]
    print(json.dumps([plan(work, lvl, bid)]))
