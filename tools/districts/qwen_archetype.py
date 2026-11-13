#!/usr/bin/env python3
"""DISTRICTS: Qwen3-VL archetype pass for the buildings the rules leave generic ("block").

    qwen_archetype.py <work> <lvl> <hd dir> [--model Qwen/Qwen3-VL-8B-Instruct] [--batch 8] [--limit N]

Shows the model each generic building's longest street-level wall as an elevation (the tiles as the renderer maps
them, tools/districts/sheet.py) and asks for one archetype from the kit's list plus a confidence. Writes
<work>/<lvl>_qwen_archetypes.json ({id: {archetype, confidence, raw}}), resumable; analyze.py --qwen merges answers
with confidence >= 0.6 into the catalogue (evidence source "qwen"). Offline, once per map. Qwen3-VL-8B-Instruct is
Apache-2.0 and in the host's Hugging Face cache. Host rules: CUDA_VISIBLE_DEVICES=0 flock /tmp/gta2-gen.lock
taskset -c 0-4 nice -n 10."""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet

CHOICES = ["brick_tenement", "brownstone", "office_tower", "shopfront_row", "warehouse", "factory", "house", "civic"]
PROMPT = ("This is one wall of a building from a 1990s top-down crime game city, drawn as a facade elevation. "
          "Classify the building. Answer with JSON only: {\"archetype\": one of " + json.dumps(CHOICES) +
          ", \"confidence\": 0.0-1.0}. brick_tenement: brick apartment block with many small windows; brownstone: "
          "3-4 storey stone or brick row house; office_tower: tall glazed or stone office building; shopfront_row: "
          "low building with shop windows at street level; warehouse: big plain or ribbed industrial shed; factory: "
          "industrial building with windows in bands and big doors; house: small 1-2 storey dwelling; civic: police "
          "station, hospital, church, bank or other public building. Always pick the closest one; give a low confidence when unsure.")


def main():
    work, lvl, hd = sys.argv[1:4]
    model_id = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "Qwen/Qwen3-VL-8B-Instruct"
    batch = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 8
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
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor
    t0 = time.time()
    proc = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")
    proc.tokenizer.padding_side = "left"
    print(f"model loaded in {time.time() - t0:.0f} s", flush=True)
    cache = {}
    t1 = time.time()
    for i in range(0, len(todo), batch):
        ids, ims = [], []
        for bid in todo[i:i + batch]:
            rs = sheet.runs(cat[bid])
            if not rs:
                done[str(bid)] = {"archetype": "block", "confidence": 0.0, "raw": "no wall"}; continue
            r = max(rs, key=lambda r: len(r[1]) * max(1, len(r[1][0]["levels"])))
            r = (r[0], r[1][:8])
            im = sheet.elevation(r, lvl, hd, tiles, cache)
            im.thumbnail((448, 448))
            ids.append(bid); ims.append(im.convert("RGB"))
        if not ims:
            continue
        texts = [proc.apply_chat_template([{"role": "user", "content": [{"type": "image", "image": im}, {"type": "text", "text": PROMPT}]}],
                                          tokenize=False, add_generation_prompt=True) for im in ims]
        inp = proc(text=texts, images=ims, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            gen = model.generate(**inp, max_new_tokens=40, do_sample=False)
        outs = proc.batch_decode(gen[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)
        for bid, txt in zip(ids, outs):
            arch, conf = "block", 0.0
            m = re.search(r"\{.*\}", txt, re.S)
            try:
                j = json.loads(m.group(0)) if m else {}
                arch = j.get("archetype") if j.get("archetype") in CHOICES else "block"
                conf = float(j.get("confidence", 0.0))
            except Exception:
                pass
            done[str(bid)] = {"archetype": arch, "confidence": round(conf, 2), "raw": txt.strip()[:120]}
        json.dump(done, open(outp, "w"))
        print(f"  {i + len(ims)}/{len(todo)}  {time.time() - t1:.0f} s", flush=True)
    print(f"{lvl}: {len(todo)} buildings in {time.time() - t1:.0f} s ({(time.time() - t1) / max(1, len(todo)):.2f} s each), load {t1 - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
