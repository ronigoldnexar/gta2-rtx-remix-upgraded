#!/usr/bin/env python3
"""DISTRICTS: Qwen3-VL archetype pass for the buildings the rules leave generic ("block"), v2.

    qwen_archetype.py <work> <lvl> <hd dir> [--model Qwen/Qwen3-VL-8B-Instruct] [--batch 4] [--limit N]

v1 answered "brick_tenement" for 597 of 940 buildings; a by-eye check of 30 (tools/districts/qwen_spot.py) found office
towers, girder bands, retaining walls, hedges and fences under that label: a label-order bias, and no answer for "not a
building". v2: the two longest walls side by side (two faces of the building), the choices in a random order per
question (seeded by building and run, reproducible), a "wall_or_structure" choice, and two questions per building
with different orders; the answer is kept only when both agree (and both are confident). Output
<work>/<lvl>_qwen_archetypes.json ({id: {archetype, confidence, raw: [two answers]}}), resumable; analyze.py merges
agreed answers with confidence >= 0.6. Apache-2.0 model from the host cache. Host rules: CUDA_VISIBLE_DEVICES=0
flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10."""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet

CHOICES = {
    "brick_tenement": "brick apartment block, many small windows in rows",
    "brownstone": "3-4 storey stone or brick row house with a stoop and tall windows",
    "office_tower": "tall office building, glass or stone grid of windows",
    "shopfront_row": "low building with shop windows at street level",
    "warehouse": "big plain or ribbed industrial shed with few windows",
    "factory": "industrial building with bands of windows and big doors",
    "house": "small 1-2 storey dwelling",
    "civic": "police station, hospital, church, bank or other public building",
    "wall_or_structure": "not a building: a wall, fence, hedge, bridge, girder or ramp",
}


def prompt(order):
    lines = "\n".join(f"- {k}: {CHOICES[k]}" for k in order)
    return ("These are two walls of one thing in a 1990s top-down crime game city, drawn as facade elevations side by "
            "side. Which one fits best?\n" + lines + "\nAnswer with JSON only: {\"archetype\": <one of the names>, "
            "\"confidence\": 0.0-1.0}.")


def image(cat, bid, lvl, hd, tiles, cache):
    from PIL import Image
    rs = sorted(sheet.runs(cat[bid]), key=lambda r: -len(r[1]) * max(1, len(r[1][0]["levels"])))
    picked = [rs[0]] + [r for r in rs[1:] if r[0] != rs[0][0]][:1] if rs else []
    ims = [sheet.elevation((r[0], r[1][:8]), lvl, hd, tiles, cache) for r in picked]
    if not ims:
        return None
    w = sum(i.width for i in ims) + 12 * (len(ims) - 1); h = max(i.height for i in ims)
    out = Image.new("RGB", (w, h), (0, 0, 0)); x = 0
    for i in ims:
        out.paste(i, (x, h - i.height)); x += i.width + 12
    out.thumbnail((640, 448))
    return out


def main():
    work, lvl, hd = sys.argv[1:4]
    model_id = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "Qwen/Qwen3-VL-8B-Instruct"
    batch = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 4
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    tiles = an["tiles"]
    outp = os.path.join(work, f"{lvl}_qwen_archetypes.json")
    done = json.load(open(outp)) if os.path.exists(outp) else {}
    todo = [a["id"] for a in an["buildings"] if a["archetype"] == "block" and str(a["id"]) not in done
            and a["evidence"]["face_levels"] >= 4][:limit]
    print(f"{lvl}: {len(todo)} generic buildings to ask ({len(done)} done)", flush=True)
    if not todo:
        return
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    t0 = time.time()
    proc = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")
    proc.tokenizer.padding_side = "left"
    print(f"model loaded in {time.time() - t0:.0f} s", flush=True)
    cache, t1 = {}, time.time()
    for i in range(0, len(todo), batch):
        ids, ims, texts = [], [], []
        for bid in todo[i:i + batch]:
            im = image(cat, bid, lvl, hd, tiles, cache)
            if im is None:
                done[str(bid)] = {"archetype": "block", "confidence": 0.0, "raw": ["no wall"]}; continue
            for run in range(2):
                order = sorted(CHOICES); random.Random(bid * 2 + run).shuffle(order)
                texts.append(proc.apply_chat_template([{"role": "user", "content": [{"type": "image", "image": im}, {"type": "text", "text": prompt(order)}]}],
                                                      tokenize=False, add_generation_prompt=True))
                ims.append(im)
            ids.append(bid)
        if not ids:
            continue
        inp = proc(text=texts, images=ims, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            gen = model.generate(**inp, max_new_tokens=40, do_sample=False)
        outs = proc.batch_decode(gen[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)
        for k, bid in enumerate(ids):
            ans = []
            for txt in outs[2 * k: 2 * k + 2]:
                arch, conf = "block", 0.0
                m = re.search(r"\{.*\}", txt, re.S)
                try:
                    j = json.loads(m.group(0)) if m else {}
                    arch = j.get("archetype") if j.get("archetype") in CHOICES else "block"
                    conf = float(j.get("confidence", 0.0))
                except Exception:
                    pass
                ans.append((arch, conf, txt.strip()[:80]))
            agree = ans[0][0] == ans[1][0] and ans[0][0] != "block"
            done[str(bid)] = {"archetype": ans[0][0] if agree else "block", "confidence": round(min(ans[0][1], ans[1][1]), 2) if agree else 0.0,
                              "raw": [a[2] for a in ans]}
        json.dump(done, open(outp, "w"))
        print(f"  {i + len(ids)}/{len(todo)}  {time.time() - t1:.0f} s", flush=True)
    print(f"{lvl}: {len(todo)} buildings in {time.time() - t1:.0f} s ({(time.time() - t1) / max(1, len(todo)):.2f} s each), load {t1 - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
