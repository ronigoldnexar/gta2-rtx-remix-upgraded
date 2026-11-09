#!/usr/bin/env python3
"""Facade element boxes for the wall tiles (QB-25), by a vision-language model.

Asks Qwen3-VL-8B-Instruct (Apache-2.0, from the local Hugging Face cache) to ground the
windows, doors, shop windows and sills in every wall tile's HD texture, as axis-aligned
boxes. The tile is shown once at 448 px, in batches (BATCH, default 8; ~4 s a tile on an
L4); boxes come back in 64 px tile units (a window cut by the tile's edge touches it).
tools/facade_depth.py turns the boxes into height maps.

    facade_ground.py <game/data> <hd root> <out.json> [--styles wil,bil,ste] [--min-side 1]
                     [--only wil:227,...] [--model Qwen/Qwen3-VL-8B-Instruct]

Resumable: tiles already in <out.json> are skipped. Run on a generation GPU under the host
rules (AGENTS.md): CUDA_VISIBLE_DEVICES=N flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10.
Needs torch, transformers >= 4.57, Pillow, numpy.
"""
import json, os, re, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROMPT = ("Building facade texture. Detect each window, door, shop window and window sill. "
          "Output a JSON list of {\"label\": \"window\"|\"door\"|\"shop window\"|\"sill\", \"bbox_2d\": [x1, y1, x2, y2]}. "
          "A window box covers the glass and its glazing bars; a sill is the ledge right under a window. "
          "Plain wall, brick or stone with no openings: output []. Output only the JSON.")

LABELS = ("window", "door", "shop window", "sill", "cornice", "pilaster", "sign", "vent", "balcony", "garage door")

def load(model_id):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    proc = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")
    return proc, model

def ask(proc, model, imgs, max_new=400):
    """one batch of images -> one answer each (greedy)"""
    import torch
    proc.tokenizer.padding_side = "left"
    texts, ims = [], []
    for img in imgs:
        msgs = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": PROMPT}]}]
        texts.append(proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)); ims.append(img)
    inp = proc(text=texts, images=ims, return_tensors="pt", padding=True).to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=max_new, do_sample=False)
    return proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)

def parse(text, W, H, tile_w):
    """model output (Qwen3-VL boxes in 0..1000 of the image) -> boxes in 64 px tile units"""
    m = re.search(r"\[.*\]", text, re.S)
    if not m: return []
    try: items = json.loads(m.group(0))
    except Exception:
        items = [json.loads(x) for x in re.findall(r"\{[^{}]*\}", m.group(0)) if x]
    out = []
    for it in items:
        if not isinstance(it, dict) or "bbox_2d" not in it: continue
        lab = str(it.get("label", "")).lower().strip()
        if lab not in LABELS: continue
        x1, y1, x2, y2 = [float(v) for v in it["bbox_2d"][:4]]
        x1, x2 = sorted((x1 / 1000 * W, x2 / 1000 * W)); y1, y2 = sorted((y1 / 1000 * H, y2 / 1000 * H))
        out.append((lab, x1, y1, x2, y2))
    s = 64.0 / tile_w
    res = [{"label": lab, "box": [round(max(x1, 0) * s, 2), round(max(y1, 0) * s, 2), round(min(x2, W) * s, 2), round(min(y2, H) * s, 2)]}
           for lab, x1, y1, x2, y2 in out]
    # dedupe (the same element seen in two copies)
    ded = []
    for r in res:
        if any(r["label"] == q["label"] and max(abs(r["box"][i] - q["box"][i]) for i in range(4)) < 3 for q in ded): continue
        ded.append(r)
    return ded

def main():
    a = sys.argv[1:]
    data, hd_root, out = a[0], a[1], a[2]
    styles = a[a.index("--styles") + 1].split(",") if "--styles" in a else ["wil", "bil", "ste"]
    min_side = int(a[a.index("--min-side") + 1]) if "--min-side" in a else 1
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    model_id = a[a.index("--model") + 1] if "--model" in a else "Qwen/Qwen3-VL-8B-Instruct"
    import facade_depth as fd
    from PIL import Image
    res = json.load(open(out)) if os.path.exists(out) else {}
    jobs = []
    for sty in styles:
        side, lid, flat = fd.usage(os.path.join(data, sty + ".gmp"))
        for t in sorted(side, key=lambda t: -side[t]):
            key = f"{sty}:{t}"
            if only and key not in only: continue
            if side[t] < min_side or side[t] < 0.5 * lid.get(t, 0): continue
            p = os.path.join(hd_root, sty, f"tile_{t:04d}.dds")
            if not os.path.exists(p) or key in res: continue
            jobs.append((key, p, side[t], lid.get(t, 0)))
    print(len(jobs), "tiles to ground", flush=True)
    if not jobs: return
    proc, model = load(model_id)
    t0 = time.time(); B = int(os.environ.get("BATCH", "8")); N = 448
    for i in range(0, len(jobs), B):
        chunk = jobs[i:i + B]; imgs = []; todo = []
        for key, p, s, l in chunk:
            im = Image.open(p).convert("RGBA")
            if np.asarray(im)[..., 3].min() < 128:
                res[key] = {"boxes": [], "raw": "cut-out tile", "side": s, "lid": l}; continue
            imgs.append(im.convert("RGB").resize((N, N), Image.LANCZOS)); todo.append((key, s, l))
        if imgs:
            for (key, s, l), txt in zip(todo, ask(proc, model, imgs)):
                res[key] = {"boxes": parse(txt, N, N, N), "raw": txt[:2000], "side": s, "lid": l}
        tmp = out + ".tmp"; json.dump(res, open(tmp, "w")); os.replace(tmp, out)
        print(f"{min(i + B, len(jobs))}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
