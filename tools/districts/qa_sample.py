#!/usr/bin/env python3
"""qa_sample.py <work> <lvl> <qa json> <n> [seed]: n random buildings the QA did not flag (kitted ones: not structures,
2+ levels over the street, a street front), each with frame_plan.py's oblique view from across the street; JSON for
linux/docker/districts_sample.py (DK_POINTS). Seeded, so the sample is reproducible."""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_plan
work, lvl, qp, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
rnd = random.Random(int(sys.argv[5]) if len(sys.argv) > 5 else 14)
qa = {o["id"]: o for o in json.load(open(qp))}
cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
ids = sorted(i for i, o in qa.items() if not o["flagged"] and cat[i]["roof"] - cat[i]["street"] >= 2)
rnd.shuffle(ids)
pts = []
for i in ids:
    if len(pts) >= n:
        break
    try:
        p = frame_plan.plan(work, lvl, i)
    except Exception:
        continue
    p["archetype"] = qa[i]["archetype"]
    p["poses"] = [q for q in p["poses"] if q["name"] in ("across", "street")]
    pts.append(p)
print(json.dumps(pts))
