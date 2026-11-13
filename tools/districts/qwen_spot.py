#!/usr/bin/env python3
"""qwen_spot.py <work> <hd> <out.png> [n] [seed]: n random confident Qwen archetype answers over the three levels, each
the elevation the model saw with its label, for a by-eye check"""
import json, os, random, sys
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet
work, hd, out = sys.argv[1:4]; n = int(sys.argv[4]) if len(sys.argv) > 4 else 30
rnd = random.Random(int(sys.argv[5]) if len(sys.argv) > 5 else 7)
here = os.path.dirname(os.path.abspath(__file__))
items = []
for lvl in ("wil", "ste", "bil"):
    q = json.load(open(os.path.join(here, "qwen", f"{lvl}.json")))
    for k, v in q.items():
        if v["confidence"] >= 0.6 and v["archetype"] != "block":
            items.append((lvl, int(k), v["archetype"], v["confidence"]))
pick = rnd.sample(items, n)
cells = []
cache = {}
for lvl, bid, arch, conf in pick:
    cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
    tiles = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))["tiles"]
    r = max(sheet.runs(cat[bid]), key=lambda r: len(r[1]) * max(1, len(r[1][0]["levels"])))
    im = sheet.elevation((r[0], r[1][:8]), lvl, hd, tiles, cache.setdefault(lvl, {}))
    im.thumbnail((300, 220))
    c = Image.new("RGB", (300, 236), (10, 10, 10)); c.paste(im, (0, 16))
    ImageDraw.Draw(c).text((3, 2), f"{len(cells) + 1}: {lvl}#{bid} {arch} {conf}", fill=(255, 255, 0))
    cells.append(c)
cols = 6
s = Image.new("RGB", (cols * 302, (len(cells) + cols - 1) // cols * 238), (0, 0, 0))
for i, c in enumerate(cells):
    s.paste(c, ((i % cols) * 302, (i // cols) * 238))
s.save(out)
