#!/usr/bin/env python3
"""Builds the mission database from the decompiled scripts.

    missions_db.py <assets-src/missions> <assets-src/e_gxt.json> <out.json> [out.md]

The base script of each district declares the phones (OBJ_DATA ... PHONE
types), the player start and the phone triggers (THREAD_WAIT_FOR_ANSWER_PHONE
-> function -> DO_[EASY_]PHONE_TEMPLATE(brief, mission file, ...)). Each
mission file is reduced to a plan: the ordered CREATE_CAR / CREATE_GANG_CAR,
POINT_ARROW_AT, LOCATE_* / IS_CHARACTER_IN_CAR / IS_CAR_IN_BLOCK / PARK /
IS_CHAR_PRESSING_HORN conditions of the top-level loops, with the brief texts
they show, and the reward (ADD_SCORE). The plan is what mission_lib.py follows;
the decompiled script stays the reference for anything the plan does not catch.
"""
import json, os, re, sys

OBJ = re.compile(r"OBJ_DATA (\w+) = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\) (\d+) (\w*PHONE)")
PLAYER = re.compile(r"PLAYER_PED \w+ = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)")
TRIG = re.compile(r"THREAD_WAIT_FOR_ANSWER_PHONE \(p1, (\w+), (\w+):\)")
TEMPLATE = re.compile(r"DO_(EASY_)?PHONE_TEMPLATE \((\d+), (\w+)\.mis(?:, (\w+)\.mis)?,.*?, (\w+gang), (\d+)\)")
LAUNCH = re.compile(r"LAUNCH_MISSION \((\w+)\.mis\)")
STEP = re.compile(r"^\s*(?:\w+ = )?(CREATE_CAR|CREATE_GANG_CAR|POINT_ARROW_AT|DISPLAY_BRIEF|DISPLAY_BRIEF_NOW|DISPLAY_MESSAGE|ADD_SCORE|PARK|WHILE_EXEC|ENDWHILE|REMOVE_ARROW|DELAY_HERE|CREATE_CHAR|SET_CHAR_OBJECTIVE|GIVE_WEAPON|RETURN|MISSION_HAS_FINISHED)\b(.*)$")
NUM = re.compile(r"[-\d.]+")

def gxt(t, key):
    v = t.get(key, "")
    return re.sub(r"^[^\x20-\x7e]+", "", v).replace("#", "")

def parse_mission(path, t):
    """A flat list of top-level steps (depth 0 inside the first function)."""
    steps, depth = [], 0
    for line in open(path, encoding="latin-1"):
        m = STEP.match(line)
        if not m: continue
        cmd, rest = m.group(1), m.group(2).strip()
        if cmd == "WHILE_EXEC":
            if depth == 0:
                cond = rest
                steps.append({"wait": cond, "numbers": [float(x) for x in NUM.findall(cond)]})
            depth += 1; continue
        if cmd == "ENDWHILE":
            depth -= 1; continue
        if depth > 0: continue   # the loop bodies are failure handling and nagging
        nums = [float(x) for x in NUM.findall(rest)]
        if cmd in ("CREATE_CAR", "CREATE_GANG_CAR"):
            model = rest.split()[-2] if rest.split()[-1] == "END" else rest.split()[-1]
            steps.append({"car": model, "at": nums[:3]})
        elif cmd == "POINT_ARROW_AT":
            steps.append({"arrow": nums[1:4] if len(nums) >= 4 else rest})
        elif cmd in ("DISPLAY_BRIEF", "DISPLAY_BRIEF_NOW", "DISPLAY_MESSAGE"):
            key = rest.strip("() "); steps.append({cmd.lower(): key, "text": gxt(t, key)})
        elif cmd == "ADD_SCORE":
            steps.append({"reward": int(nums[-1])})
        elif cmd == "PARK":
            steps.append({"park": rest})
        elif cmd == "CREATE_CHAR":
            steps.append({"char": rest.split()[-2], "at": nums[:3]})
        elif cmd == "GIVE_WEAPON":
            steps.append({"weapon": rest})
        elif cmd == "RETURN":
            break
    return steps

def main():
    src, gxt_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    t = json.load(open(gxt_path))
    db = {}
    for district in ("wil", "bil", "ste"):
        base = os.path.join(src, district + ".mis")
        text = open(base, encoding="latin-1").read()
        phones = {m.group(1): {"x": float(m.group(2)), "y": float(m.group(3)), "z": float(m.group(4)),
                               "rot": int(m.group(5)), "kind": m.group(6)} for m in OBJ.finditer(text)}
        start = PLAYER.search(text)
        funcs = {}
        for m in re.finditer(r"^(\w+):\n((?:(?!^\w+:\n).*\n)*)", text, re.M):
            funcs[m.group(1)] = m.group(2)
        missions = []
        for m in TRIG.finditer(text):
            obj, fn = m.group(1), m.group(2)
            body = funcs.get(fn, "")
            tm = TEMPLATE.search(body); lm = LAUNCH.search(body)
            entry = {"phone": obj, **phones.get(obj, {}), "function": fn}
            if tm:
                entry.update(gang=tm.group(5), easy=bool(tm.group(1)), done_text=gxt(t, tm.group(2)),
                             mission=tm.group(3), followup=tm.group(4), respect_needed=int(tm.group(6)))
            elif lm:
                entry.update(mission=lm.group(1), gang="none")
            else:
                briefs = re.findall(r"DISPLAY_BRIEF \((\d+)\)", body)
                entry.update(mission=None, briefs=[gxt(t, b) for b in briefs])
            if entry.get("mission"):
                mp = os.path.join(src, district + "_m", entry["mission"] + ".mis")
                if os.path.exists(mp):
                    entry["plan"] = parse_mission(mp, t)
                    msg = [s for s in entry["plan"] if "display_message" in s]
                    entry["title"] = msg[0]["text"] if msg else entry["mission"]
            missions.append(entry)
        db[district] = {"start": [float(start.group(i)) for i in (1, 2, 3)] if start else None,
                        "phones": phones, "missions": missions}
    json.dump(db, open(out, "w"), indent=1)
    if len(sys.argv) > 4:
        with open(sys.argv[4], "w") as f:
            for d, v in db.items():
                f.write(f"\n### {d}: player start {v['start']}, {len(v['phones'])} phones, {len(v['missions'])} phone triggers\n\n")
                f.write("| phone | kind | at | gang | mission | title | needs respect | reward | steps |\n|---|---|---|---|---|---|---|---|---|\n")
                for m in v["missions"]:
                    plan = m.get("plan", [])
                    reward = sum(s.get("reward", 0) for s in plan)
                    f.write(f"| {m['phone']} | {m.get('kind','')} | {m.get('x')},{m.get('y')},{m.get('z')} | {m.get('gang','')} | {m.get('mission') or 'briefs only'} | {m.get('title','')} | {m.get('respect_needed','')} | {reward or ''} | {len(plan)} |\n")
    print({d: (len(v["phones"]), len(v["missions"])) for d, v in db.items()})

if __name__ == "__main__":
    main()
