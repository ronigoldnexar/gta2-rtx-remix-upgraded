import json, math, sys
W, lvl, x, y, r = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
extra = [int(v) for v in sys.argv[6:]]
an = {a["id"]: a for a in json.load(open(f"{W}/{lvl}_analysis.json"))["buildings"]}
B = json.load(open(f"{W}/{lvl}_buildings.json"))["buildings"]
ids = [b["id"] for b in B if an[b["id"]]["archetype"] != "structure" and math.hypot((b["bbox"][0] + b["bbox"][2]) / 2 - x, (b["bbox"][1] + b["bbox"][3]) / 2 - y) < r]
print(",".join(map(str, sorted(set(ids + extra)))))
