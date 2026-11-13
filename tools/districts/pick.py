#!/usr/bin/env python3
"""DISTRICTS-POC step 3: pick the representative, visible building of a level from the catalogue.

    pick.py <work> <lvl> [n]   -> prints the ranking, writes <work>/<lvl>_pick.json (the best one)

Score: the level's target archetypes (Downtown: brick tenement / brownstone / office tower; Residential:
brownstone / tenement / house; Industrial: warehouse / factory), times how much wall with openings faces a
road or pavement at street level (what a player walking or driving sees), times a height term (3-6 levels),
times (1 + 0.15 per street door, up to 6) and halved under 4 upper windows (what the kit builds on), times 0.6 inside a landmark (local-nav) zone, times the square of how complete that wall is (faces present), plus a bonus near a point the QA harness already frames (tools/vreg/shots.json, Downtown)."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap

TARGET = {"wil": {"brick_tenement": 1.0, "brownstone": 0.9, "office_tower": 0.8},
          "ste": {"brownstone": 1.0, "brick_tenement": 0.9, "house": 0.7},
          "bil": {"warehouse": 1.0, "factory": 1.0}}


def main():
    work, lvl = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    here = os.path.dirname(os.path.abspath(__file__))
    cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    tiles = an["tiles"]
    m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
    qa = []
    sp = os.path.join(here, "..", "vreg", "shots.json")
    if lvl == "wil" and os.path.exists(sp):
        qa = [(p["x"], p["y"], p["name"]) for p in json.load(open(sp))["points"]]
    dists = json.load(open(os.path.join(work, f"{lvl}_districts.json")))["districts"]
    rows = []
    for a in an["buildings"]:
        w = TARGET[lvl].get(a["archetype"], 0.0)
        if not w:
            continue
        b = cat[a["id"]]
        seen = 0
        street_fl, tiled, doors, uppers = 0, 0, 0, 0
        for f in b["faces"]:
            dx, dy = gmap.SIDES[f["side"]][3]
            nx, ny = f["x"] + dx, f["y"] + dy
            if not (0 <= nx < 256 and 0 <= ny < 256):
                continue
            r, lid, g, st = m.top(nx, ny)
            if g not in (1, 2) or f["lo"] > b["street"]:
                continue
            street_fl += len(f["levels"]); tiled += sum(1 for l in f["levels"] if l["tile"])
            ops = lambda l: [o for o in tiles.get(str(l["tile"]), {}).get("openings", []) if o.get("conf", 1.0) >= 0.45]
            seen += sum(1 for l in f["levels"] if l["tile"] and l["slope"] == 0 and ops(l))
            # what the kit can build here: street doors (stoops, docks) and upper windows (bays, balconies, escapes)
            doors += sum(1 for l in f["levels"][:1] for o in ops(l) if o["kind"] in ("door", "loading_door", "shop window"))
            uppers += sum(1 for l in f["levels"][1:] if any(o["kind"] == "window" for o in ops(l)))
        hterm = 1.0 if 3 <= b["levels"] <= 6 else 0.5
        cx = (b["bbox"][0] + b["bbox"][2] + 1) / 2; cy = (b["bbox"][1] + b["bbox"][3] + 1) / 2
        near = min([(math.hypot(cx - x, cy - y), nm) for x, y, nm in qa] or [(999, "")])
        # complete walls: a front with missing faces (holes the street fill covers) is no showcase
        complete = tiled / max(1, street_fl)
        # representative: an ordinary street of a gang or neighbourhood district, not a landmark compound
        # (a local-nav zone names one place: the prison, the army base, a mission yard)
        typical = 0.6 if dists[b["district"]]["kind"] == "local_nav" else 1.0
        score = w * min(seen, 60) * hterm * complete ** 2 * typical * (1.5 if near[0] < 14 else 1.0) * (1.0 + 0.15 * min(doors, 6)) * (1.0 if uppers >= 4 else 0.5)
        rows.append((score, a["id"], a["archetype"], b["levels"], b["area"], seen, b["bbox"], near))
    rows.sort(reverse=True)
    for r in rows[:n]:
        print(f"score {r[0]:6.1f} #{r[1]:5d} {r[2]:15s} lv{r[3]} area {r[4]:3d} seen {r[5]:3d} bbox {r[6]} near {r[7][1]} {r[7][0]:.0f}")
    best = rows[0]
    json.dump({"level": lvl, "id": best[1], "archetype": best[2], "score": best[0], "ranking": [r[1] for r in rows[:n]]},
              open(os.path.join(work, f"{lvl}_pick.json"), "w"))


if __name__ == "__main__":
    main()
