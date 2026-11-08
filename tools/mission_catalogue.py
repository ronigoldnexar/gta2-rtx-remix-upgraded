#!/usr/bin/env python3
"""GTA2 mission catalogue: every phone job, final job, tutorial, kill frenzy and
bonus stage of the three districts, with the runner skills each one needs.

    mission_catalogue.py dump  [--game DIR] [--mis DIR]            job names + briefs to stdout
    mission_catalogue.py build [--game DIR] [--mis DIR] [--repo DIR]
        -> <repo>/docs/missions-catalogue.json and docs/missions-catalogue.md

Sources, all read in place (nothing is copied out of the game folder):
  - <game>/data/e.gxt: the English text (GBL file: TKEY = 12-byte entries of
    TDAT offset + 8-char key, TDAT = UTF-16LE strings). Titles and briefs.
  - <game>/data/{wil,ste,bil}.gmp: the maps, for the phone's standing level
    (raised phones = rooftop / terrace access).
  - <mis>/{wil,ste,bil}.mis and <mis>/<d>_m/*.mis: the scripts decompiled with
    T.M.'s decompiler (github.com/Valps/gta2-tm-scr-decompiler), see
    docs/missions.md. Phones, phone triggers, prerequisites (respect), kill
    frenzies (START_BASIC_KF_TEMPLATE + START_BONUS_CHECK), finish score and
    level-end point; per mission: title, briefs, reward, cars created, and the
    script features the skill tags are derived from.
  - CURATED below: the objective summary, skills and hazards per job, written
    from the briefs + scripts (and checked against community lists, URLs in
    SOURCES); STATUS: our 3D playthrough status from docs/playthrough-*.md.

District files: wil = Downtown, ste = Residential, bil = Industrial (finish
scores 1M / 3M / 5M).
"""
import argparse, json, os, re, struct, sys
from collections import OrderedDict, Counter

HOME = os.path.expanduser("~/gta2-linux")
DISTRICTS = [("wil", "Downtown"), ("ste", "Residential"), ("bil", "Industrial")]
GANG_NAMES = {"yakuzagang": "Yakuza", "zaibatsugang": "Zaibatsu", "looniegang": "Loonies",
              "sciegang": "SRS Scientists", "zaibgang": "Zaibatsu", "redngang": "Rednecks",
              "krisgang": "Hare Krishna", "russgang": "Russian Mafia"}
PHONE_COLOUR = {"GREEN_PHONE": "green", "YELLOW_PHONE": "yellow", "RED_PHONE": "red", "PHONE": "plain"}

SOURCES = {
    "scripts": "game scripts decompiled with https://github.com/Valps/gta2-tm-scr-decompiler (assets-src/missions, see docs/missions.md)",
    "missions_list": "https://gta.wiki/w/Missions_in_GTA_2",
    "kill_frenzies": "https://gta.wiki/w/Kill_Frenzies_in_GTA_2",
    "bonus_levels": "https://www.grandtheftwiki.com/Bonus_Levels_in_GTA_2",
    "bonus_levels_readme": "https://gtamp.com/mapscript/_maplump/_02_recent/bonus-levels.zip/data/readme-bonus-levels.txt",
    "bonuses": "https://en.wikigta.org/wiki/Bonuses_(GTA2)",
}

# ---------------------------------------------------------------- GXT text
def read_gxt(path):
    data = open(path, "rb").read()
    assert data[:3] == b"GBL", "not a GBL text file"
    off = 6; keys = []; tdat = None
    while off + 8 <= len(data):
        tag = data[off:off + 4]; size = struct.unpack_from("<I", data, off + 4)[0]
        body = off + 8
        if tag == b"TKEY":
            for i in range(size // 12):
                o = struct.unpack_from("<I", data, body + i * 12)[0]
                k = data[body + i * 12 + 4: body + i * 12 + 12].split(b"\0")[0].decode("latin-1")
                keys.append((k, o))
        elif tag == b"TDAT":
            tdat = data[body: body + size]
        off = body + size
    out = {}
    for k, o in keys:
        end = o
        while end + 1 < len(tdat) and tdat[end:end + 2] != b"\0\0": end += 2
        out[k] = tdat[o:end].decode("utf-16-le", "replace")
    return out

def clean(s):
    """drop the leading speaker glyph and the colour marks (#)"""
    s = re.sub(r"^[^\x20-\x7e]+", "", s or "")
    return re.sub(r"\s+", " ", s.replace("#", "")).strip()

# ---------------------------------------------------------------- map (phone level)
def map_levels(gmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "linux", "docker"))
    try:
        import gmp
    except ImportError:
        return None
    blocks, columns = gmp.load(gmp_path)
    def top(x, y):
        best = None
        for lvl in range(0, 8):
            b = gmp.block_at(blocks, columns, int(x), int(y), lvl)
            if b and b[4]: best = lvl + 1
        return best
    return top

# ---------------------------------------------------------------- base script
OBJ = re.compile(r"^\s*OBJ_DATA (\w+) = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\) (\d+) (\w+)")
CAR = re.compile(r"^\s*(?:PARKED_)?CAR_DATA (\w+) = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\) \S+ \S+ (\w+)")
TRIG = re.compile(r"^THREAD_TRIGGER (\w+) = (\w+) \((.*), (\w+):\)")
TEMPLATE = re.compile(r"DO_(EASY_)?PHONE_TEMPLATE \((\d+), (\w+)\.mis(?:, (\w+)\.mis)?,.*?, (\w+gang), (\d+)\)")
KF = re.compile(r"START_BASIC_KF_TEMPLATE \(\w+, (\d+), (\w+), p1, (\w+)\)")
BONUS = re.compile(r"START_BONUS_CHECK \((\w+), (\d+), (\d+), \d+, (\w+), \w+, (\w+), (\w+), (\w+)(?:, ([-\w]+))?\)")
DOKF = re.compile(r"DO_BASIC_KF_TEMPLATE \(\w+, \w+, (\d+), \w+, \w+, (\d+), (\d+), p1, (\w+), (\d+)\)")

def functions(lines):
    """label -> list of body lines"""
    out, cur = {}, None
    for ln in lines:
        m = re.match(r"^(function\d+):\s*$", ln)
        if m: cur = m.group(1); out[cur] = []; continue
        if cur is not None:
            if ln.startswith("RETURN"): cur = None; continue
            out[cur].append(ln)
    return out

def parse_base(path):
    lines = open(path, encoding="latin-1").read().splitlines()
    objs, cars, trigs = {}, {}, []
    for ln in lines:
        m = OBJ.match(ln)
        if m: objs[m.group(1)] = dict(x=float(m.group(2)), y=float(m.group(3)), z=float(m.group(4)), kind=m.group(6))
        m = CAR.match(ln)
        if m: cars[m.group(1)] = dict(x=float(m.group(2)), y=float(m.group(3)), z=float(m.group(4)), model=m.group(5))
        m = TRIG.match(ln)
        if m: trigs.append((m.group(2), m.group(3), m.group(4)))
    funcs = functions(lines)
    text = "\n".join(lines)
    fs = re.search(r"DECLARE_FINISH_SCORE \((\d+)\)", text)
    le = re.search(r"LEVEL_END_POINT_ARROW_AT \(\w+, ([-\d.]+), ([-\d.]+), ([-\d.]+)\)", text)
    start = re.search(r"PLAYER_PED \w+ = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)", text)
    return dict(objs=objs, cars=cars, trigs=trigs, funcs=funcs,
                finish_score=int(fs.group(1)) if fs else None,
                level_end=[float(v) for v in le.groups()] if le else None,
                start=[float(v) for v in start.groups()] if start else None)

# ---------------------------------------------------------------- mission script features
FEATURES = OrderedDict([
    ("enter_mission_car", r"IS_CHARACTER_IN_CAR\s*\(p1, m_\w+auto"),
    ("steal_model", r"IS_CHARACTER_IN_MODEL\s*\(p1|CHECK_CAR_MODEL"),
    ("destroy_model", r"SETUP_MODELCHECK_DESTROY|HAS_MODELCHECK_HAPPENED"),
    ("locate_by_car", r"LOCATE_CHARACTER_BY_CAR|LOCATE_ANOTHER_CHARACTER_BY_CAR"),
    ("locate_on_foot", r"LOCATE_CHARACTER_ON_FOOT|LOCATE_ANOTHER_CHARACTER_ON_FOOT"),
    ("locate_any", r"LOCATE_CHARACTER_ANY_MEANS|LOCATE_ANOTHER_CHARACTER_ANY_MEANS"),
    ("car_in_block", r"IS_CAR_IN_BLOCK"),
    ("park", r"\bPARK\b|HAS_PARK_FINISHED"),
    ("horn", r"IS_CHAR_PRESSING_HORN"),
    ("timer", r"DISPLAY_TIMER"),
    ("counter", r"ADD_ONSCREEN_COUNTER"),
    ("kill_count_bonus", r"START_BONUS_CHECK"),
    ("char_died", r"HAS_CHARACTER_DIED"),
    ("car_wrecked", r"IS_CAR_WRECKED|CHECK_CAR_WRECKED_IN_AREA"),
    ("weapon_hit_car", r"CHECK_(ANY_)?WEAPON_TYPE_HIT_CAR"),
    ("crusher", r"IS_CAR_CRUSHED"),
    ("crane_trailer", r"ENABLE_CRANE|IS_TRAILER_ATTACHED|IS_CAR_ON_TRAILER|PUT_CAR_ON_TRAILER|GET_CAR_INFO_FROM_CRANE"),
    ("passengers_group", r"ADD_GROUP_TO_CHARACTER|IS_GROUP_IN_CAR|ENTER_CAR_AS_PASSENGER|CHECK_NUMBER_ALIVE_IN_GROUP"),
    ("follow_car", r"FOLLOW_CAR_IN_CAR|FOLLOW_CAR_ON_FOOT"),
    ("bus", r"IS_BUS_FULL|\bBUS\b|KRSNABUS|STOP_CHARS_GETTING_OFF_BUS"),
    ("tank", r"\bTANK\b"),
    ("boat", r"\b(BOAT|SPEEDER|YACHT)\b"),
    ("car_bomb", r"IS_CARBOMB_ACTIVE|HAS_CAR_GOT_WEAPON|CAR_BOMB"),
    ("remote_control", r"TAKE_REMOTE_CONTROL_OF_CAR"),
    ("emerg_lights", r"ARE_EMERG_LIGHTS_ON"),
    ("gang_zone", r"IS_CHAR_IN_GANGZONE|IS_CHAR_IN_ZONE"),
    ("sinks_fail", r"HAS_CAR_JUST_SUNK"),
    ("muggers", r"MAKE_ALL_CHARS_MUGGERS \(ON\)"),
    ("wanted_up", r"ALTER_WANTED_LEVEL|CHANGE_POLICE_LEVEL"),
    ("score_check", r"CHECK_SCORE_GREATER"),
    ("heads_check", r"CHECK_HEADS_GREATER"),
    ("launch_sub", r"LAUNCH_MISSION"),
])

def parse_mission(path, t):
    txt = open(path, encoding="latin-1").read()
    msgs = re.findall(r"DISPLAY_MESSAGE \((\d+)\)", txt)
    title_key = next((k for k in msgs if k not in ("1124", "1125") and clean(t.get(k, "")).rstrip().endswith(("!", "?"))), None)
    briefs = []
    for k in re.findall(r"DISPLAY_BRIEF(?:_NOW|_SOON)? \((\d+)\)", txt):
        if k not in briefs: briefs.append(k)
    scores = [int(v) for v in re.findall(r"ADD_SCORE(?:_NO_MULT)? \(p1, (\d+)\)", txt)]
    cars = [m for m in re.findall(r"CREATE_(?:GANG_)?CAR \([^)]*\) \S+ \S+ (\w+)", txt)]
    cars += re.findall(r"CREATE_CHAR_INSIDE_CAR[^\n]*?(?:\)) \S+ \S+ (\w+)", txt)
    models_req = sorted(set(re.findall(r"IS_CHARACTER_IN_MODEL\s*\(p1, (\w+)\)", txt)))
    destroy_models = sorted(set(re.findall(r"SETUP_MODELCHECK_DESTROY \((\w+)\)", txt)))
    bonus = [dict(zip(("zone", "frames", "count", "target", "method", "vehicle", "occupation", "gang"), b))
             for b in BONUS.findall(txt)]
    timers = [int(v) for v in re.findall(r"DISPLAY_TIMER \(\w+, (\d+)\)", txt)]
    feats = [f for f, rx in FEATURES.items() if re.search(rx, txt)]
    zs = sorted({float(z) for z in re.findall(r"LOCATE_\w+\(\w+, [-\d.]+, [-\d.]+, ([-\d.]+),", txt)})
    return dict(title_key=title_key, title=clean(t.get(title_key, "")) if title_key else None,
                brief_keys=briefs, reward=max(scores) if scores else None,
                cars_created=sorted(Counter(cars)), models_required=models_req,
                destroy_models=destroy_models, bonus_checks=bonus, timers_s=timers,
                features=feats, locate_levels=zs)

def first_brief(t, keys):
    for k in keys:
        s = clean(t.get(k, ""))
        if len(s) > 40: return k, s
    return None, None

# ---------------------------------------------------------------- gathering
def gather(game, misdir):
    t = read_gxt(os.path.join(game, "data", "e.gxt"))
    out = OrderedDict()
    for d, dname in DISTRICTS:
        base = parse_base(os.path.join(misdir, d + ".mis"))
        gmp_path = os.path.join(game, "data", d + ".gmp")
        top = map_levels(gmp_path) if os.path.exists(gmp_path) else None
        jobs = OrderedDict()   # mission id -> record
        phones_by_job = {}
        own_counter, rival_counter = {}, {}
        for kind, args, fn in base["trigs"]:
            body = "\n".join(base["funcs"].get(fn, []))
            if kind == "THREAD_WAIT_FOR_ANSWER_PHONE":
                obj = args.split(", ")[1]; ph = base["objs"].get(obj, {})
                phone = dict(obj=obj, x=ph.get("x"), y=ph.get("y"), colour=PHONE_COLOUR.get(ph.get("kind"), ph.get("kind")))
                if ph: phone["level"] = ph["z"] if ph["z"] < 100 else (top(ph["x"], ph["y"]) if top else None)
                m = TEMPLATE.search(body)
                ta = re.search(r"DO_(?:EASY_)?PHONE_TEMPLATE \(([^)]*)\)", body)
                if ta:
                    args_ = [x.strip() for x in ta.group(1).split(",")]
                    own_counter[args_[-2]] = args_[-5]; rival_counter[args_[-2]] = args_[-4]
                if m:
                    easy, refusal, mis, follow, gang, resp = m.groups()
                    phones_by_job.setdefault(mis, []).append(dict(phone, respect=int(resp), gang=gang, refusal_key=refusal))
                    if follow:
                        phones_by_job.setdefault(follow, []).append(dict(phone, respect=int(resp), gang=gang,
                                                                         refusal_key=refusal, after=mis))
                for lm in re.findall(r"LAUNCH_MISSION \((\w+)\.mis\)", body):
                    if lm.endswith("_tra"):
                        phones_by_job.setdefault(lm, []).append(dict(phone, respect=None, gang=None))
        # kill frenzies
        kfs = []
        for kind, args, fn in base["trigs"]:
            body = "\n".join(base["funcs"].get(fn, []))
            m = KF.search(body)
            if not m: continue
            key, item, weapon = m.groups()
            b = BONUS.search(body); dk = DOKF.search(body)
            rec = dict(id=f"{d}_kf{len(kfs)+1:02d}", text_key=key, text=clean(t.get(key, "")),
                       weapon=weapon, trigger=kind.replace("THREAD_WAIT_FOR_", "").lower())
            if item in base["objs"]:
                o = base["objs"][item]; rec.update(x=o["x"], y=o["y"], z=o["z"], start="walk onto the kill-frenzy skull")
            elif item in base["cars"]:
                c = base["cars"][item]; rec.update(x=c["x"], y=c["y"], z=c["z"], vehicle=c["model"], start=f"enter the parked {c['model']}")
            if b:
                zone, frames, count, target, method, veh, occ, gang = b.groups()
                rec.update(count=int(count), target=target, method=method, vehicle_req=veh, occupation=occ,
                           target_gang=gang)
            if dk:
                rec.update(time_s=int(dk.group(1)), reward=f"{dk.group(4)} x{dk.group(5)}")
            kfs.append(rec)
        # missions
        mdir = os.path.join(misdir, d + "_m")
        for f in sorted(os.listdir(mdir)):
            if not f.endswith(".mis"): continue
            mid = f[:-4]
            rec = parse_mission(os.path.join(mdir, f), t)
            rec["id"] = mid; rec["phones"] = phones_by_job.get(mid, [])
            k, s = first_brief(t, rec["brief_keys"]); rec["first_brief"] = s
            rec["briefs"] = [clean(t.get(k, "")) for k in rec["brief_keys"]]
            jobs[mid] = rec
        counter_gang = {v: k for k, v in own_counter.items()}
        rivals = {g: counter_gang.get(rival_counter[g]) for g in rival_counter}
        for rec in kfs:
            if top and rec.get("z", 0) > 100: rec["z"] = top(rec["x"], rec["y"])
        out[d] = dict(name=dname, rivals=rivals, start=base["start"], finish_score=base["finish_score"],
                      level_end=base["level_end"], jobs=jobs, kill_frenzies=kfs,
                      bonus_tokens=sum(1 for o in base["objs"].values() if o["kind"] == "BONUS_TOKEN"),
                      info_phones=[dict(x=o["x"], y=o["y"]) for n, o in base["objs"].items() if o["kind"] == "PHONE"
                                   and not any(p["x"] == o["x"] and p["y"] == o["y"] for ps in phones_by_job.values() for p in ps)])
    return t, out

def cmd_dump(a):
    t, data = gather(a.game, a.mis)
    for d, dd in data.items():
        print(f"######## {d} {dd['name']} finish={dd['finish_score']} end={dd['level_end']} tokens={dd['bonus_tokens']}")
        for mid, r in dd["jobs"].items():
            ph = "; ".join(f"{p['colour']} {p['x']},{p['y']} L{p.get('level')} {GANG_NAMES.get(p['gang'], p['gang'])} r{p['respect']}"
                           + (f" after {p['after']}" if p.get('after') else "") for p in r["phones"])
            print(f"\n=== {mid} {r['title']} reward={r['reward']} | {ph}")
            print(f"  cars={r['cars_created']} models={r['models_required']} destroy={r['destroy_models']} timers={r['timers_s']} levels={r['locate_levels']}")
            print(f"  feats={r['features']}")
            for b in r["bonus_checks"]: print(f"  bonus={b}")
            if a.full:
                for s in r["briefs"]: print(f"   - {s}")
            else:
                print(f"   - {r['first_brief']}")
        for k in dd["kill_frenzies"]:
            print(f"  KF {k}")


# ---------------------------------------------------------------- curated knowledge
SKILLS = OrderedDict([
    ("drive_to_point", "drive a car to a scripted point/box (LOCATE_*_BY_CAR, IS_CAR_IN_BLOCK)"),
    ("walk_to_point", "reach a point on foot, incl. stairs, interiors, narrow walkways"),
    ("enter_mission_car", "walk to and enter the scripted mission car"),
    ("steal_model", "find a given car model (parked or in traffic) and jack it"),
    ("deliver_intact", "deliver/park a fragile or valued vehicle in a garage/box without wrecking it"),
    ("timed", "beat an on-screen clock"),
    ("horn_pickup", "sound the horn at a box so NPCs board, then carry them"),
    ("escort_protect", "keep NPC passengers/followers alive, wait for them, lead them"),
    ("tail_unseen", "follow a target without being spotted or losing it"),
    ("kill_marked", "kill specific marked characters (arrows on peds)"),
    ("kill_count", "kill N peds of a gang/zone on foot (counter)"),
    ("run_over_count", "run over N peds of a gang with a given vehicle (counter)"),
    ("destroy_vehicle", "destroy marked or roaming vehicles (guns/ramming)"),
    ("destroy_objects", "shoot/blow up static targets (generators, turbines, tanks, doors)"),
    ("car_bomb", "rig a car at a bomb shop or arm a pre-rigged car, park it, escape the blast"),
    ("plant_on_foot", "carry explosives on foot to a spot and run before the fuse"),
    ("crusher_crane", "drive into a crusher/crane box, step out, let the crane take the car"),
    ("truck_trailer", "truck cab + trailer: hook up, tow, drop at a crane"),
    ("bus", "drive a bus (stops, boarding, capacity)"),
    ("tank", "drive/steal/fight a tank"),
    ("boat", "drive a boat (none of the phone jobs needs one)"),
    ("rooftop_access", "phone or objective on a raised roof/terrace (stairs, ramps, rooftop jumps)"),
    ("wanted_evasion", "survive or shake police (wanted level, respray, timed evasion)"),
    ("money_needed", "needs cash on hand mid-job (bomb shop / bribe), may need a killing spree"),
    ("remote_control", "drive a remote-controlled car"),
    ("defend_area", "defend objects/area or survive in a zone for a time"),
    ("cop_siren", "use a cop car and its siren (emergency lights)"),
    ("gang_zone", "objective counts only inside a gang zone / area"),
    ("combat_on_foot", "sustained on-foot gunfights with armed guards"),
])

# id: (objective summary, skills, hazards)
CURATED = {
 # ------------------------------------------------ Downtown (wil)
 "wil_tra": ("Get in the Messer (pistol inside), follow the pink marker through the Zaibatsu, Loonies and Yakuza zones and back to the spawn phone.",
             ["enter_mission_car", "drive_to_point"], "car wrecked or sunk fails it; plain phone at spawn"),
 "wil_ye1": ("Take the Miura from City University, horn in the 3x1 hospital box so Dr ZitZaki boards, deliver him to the J-Lab garage.",
             ["enter_mission_car", "drive_to_point", "horn_pickup", "deliver_intact", "escort_protect"], "doctor can die; car wreck/sink fails; hospital box is small (pt9)"),
 "wil_ye2": ("Drive the Graham to the City Bank, kill the 2 bank guards, Hiroshi boards; wanted level rises: respray ($5,000 given) or bribe, then the Safehouse.",
             ["enter_mission_car", "drive_to_point", "kill_marked", "escort_protect", "wanted_evasion"], "shooting at the bank raises wanted level, arrest on the spot (pt9_wil6); Hiroshi must live"),
 "wil_ym1": ("Get a car to City University, horn to meet the Loonies (deal turns into a fight: kill them); steal an Ice-Cream Van, money for the rig, drive into the Asylum, arm the van bomb by the Happy Gas tanks and escape.",
             ["drive_to_point", "horn_pickup", "kill_marked", "steal_model", "money_needed", "car_bomb"], "need cash to rig the van (killing spree); Loony ambush; police contact fails"),
 "wil_ym2": ("Steal a Medicar, collect Gama Rei at City Hospital, deliver him to the Safehouse while Loony assassins attack.",
             ["steal_model", "drive_to_point", "escort_protect", "deliver_intact"], "Medicar must not be destroyed; Gama Rei must live; assassins en route"),
 "wil_ym3": ("Tail the traitor on foot without being seen; at the hideout meet Refried Noodle (weapon), kill the traitor and his men.",
             ["tail_unseen", "walk_to_point", "kill_marked", "combat_on_foot"], "losing him or being seen fails; Noodle must live"),
 "wil_yh1": ("Steal a SWAT Van (any) and park it in Johnny Zoo's garage.",
             ["steal_model", "deliver_intact", "wanted_evasion"], "SWAT vans only appear at high wanted levels: needs 4+ stars"),
 "wil_yh2": ("A Tank and ground troops roll to destroy Johnny Zoo's exotic cars: stop the Tank (and troops) before the cars are wrecked.",
             ["destroy_vehicle", "tank", "kill_count"], "tank is armoured: needs rockets/explosives or a hijack; failure if his cars die"),
 "wil_ze1": ("Steal the Cop Car at the Zarelli station, drive to the Avalon train station, horn for Shady, take him to the Zaibatsu crusher (NE Zarelli), get out under the crane.",
             ["enter_mission_car", "drive_to_point", "horn_pickup", "crusher_crane"], "phone on the Zaibatsu HQ level-4 terrace; Cop Car wreck fails; Shady must not die early"),
 "wil_ze2": ("Pick up the briefcase and serve four dealers on foot/by car in 180 s.",
             ["timed", "walk_to_point", "drive_to_point"], "180 s clock; dealers must not die; terrace phone"),
 "wil_zm1": ("Steal a Loony Dementia, earn $5,000, rig it at the bomb shop, take the Van to collect the Z-Men (horn), then dump the rigged Dementia in the Loony garage and set it off.",
             ["steal_model", "money_needed", "car_bomb", "horn_pickup", "escort_protect", "drive_to_point"], "twitchy Loony guards; burning Dementia fails; Z-Men must live"),
 "wil_zm2": ("Beat (not kill) snitch Lefty by the Casino until he talks, steal the Yute car at South Docks, horn at the Easy Rider for the Yute boss, drive to Zaibatsu HQ, then the South Docks crusher.",
             ["kill_marked", "steal_model", "horn_pickup", "deliver_intact", "crusher_crane", "drive_to_point"], "punch only: killing Lefty fails; Yute car and boss must survive"),
 "wil_zm3": ("Steal the circling Third World Bank Van, horn for the Z-Men, drive through the bank clearance, grab the briefcase, swap cash with Rollo Tomassi, hand the package to the Cop, back to the Safehouse.",
             ["destroy_vehicle", "steal_model", "horn_pickup", "escort_protect", "drive_to_point", "walk_to_point", "wanted_evasion"], "Bank Van is moving; Z-Men and Rollo must live; wanted level"),
 "wil_zh1": ("Destroy the two Yakuza cars circling the city (Dr Cubana inside) within 6 minutes.",
             ["destroy_vehicle", "timed"], "360 s clock; moving targets, need heavy weapon or ramming"),
 "wil_zh2": ("Wait for the guard to board, steal the Bank Van unseen (do not kill the guard), shake the Yakuza tail, park at the Safehouse.",
             ["enter_mission_car", "tail_unseen", "deliver_intact", "kill_marked", "drive_to_point"], "being seen or killing the guard fails; Yakuza chasers"),
 "wil_le1": ("Get explosives, sneak in the back of the Zaibatsu site, drop them by the generator (5 s fuse), then at the Futuro FM riot kill the DJ. Every ped is a mugger (MAKE_ALL_CHARS_MUGGERS).",
             ["walk_to_point", "plant_on_foot", "kill_marked", "timed"], "all peds mug: a stopped car is lost (pt9_wil1/2/7); 5 s fuse"),
 "wil_le2": ("Pick up explosives at City University, drop them at Pizza Cake (5 s fuse), then destroy the Pizza Cake delivery van.",
             ["walk_to_point", "plant_on_foot", "destroy_vehicle", "timed"], "the van is fragile only to guns: ramming kills the player (pt6); 5 s fuse"),
 "wil_lm1": ("WHO'S MAD?: go meet Cosmo Trouble (a hoax); three hitmen come for you: kill them.",
             ["drive_to_point", "kill_marked", "combat_on_foot"], "three armed hitmen hunt the player"),
 "wil_lm2": ("Collect explosives at University, enter J-Lab, kill the short Yakuza guard, plant the explosives in his place, climb the stairs to watch.",
             ["walk_to_point", "kill_marked", "plant_on_foot", "combat_on_foot"], "interior with levels 3-6; guards inside"),
 "wil_lm3": ("Meet Dodo (University), pick up gun+bombs behind Harman Hotel, pay Lance $1,000 and drop him at the Cop Car Compound to distract the guard, sneak in, kill the other guard, Molotov the door locks, steal the Dementia Limo and drive it to the Asylum.",
             ["walk_to_point", "money_needed", "horn_pickup", "escort_protect", "kill_marked", "destroy_objects", "enter_mission_car", "deliver_intact"], "Dodo/Lance must live; killing the nice cop fails; spotted makes it hard"),
 "wil_lh1": ("Three taxis in turn: steal the taxi, kill its driver(s)/passengers, take it to the South Docks crusher (right one), get out.",
             ["enter_mission_car", "kill_marked", "crusher_crane", "drive_to_point"], "wrong crusher fails; taxi wreck/sink fails"),
 "wil_lh2": ("Steal a Zaibatsu Z-Type and run over Johnny Zoo's 3 top Yakuza in Yakuza town; then a Yakuza Miara and run over Trey Welsh's 3 Z-Lieutenants in the Zaibatsu quarter.",
             ["steal_model", "run_over_count", "kill_marked", "gang_zone"], "targets flee: any escape fails; must use the named model"),
 "wil_end": ("THE FINAL JOB: after 21 jobs; the three bosses (Trey Welsh, Elmo, Johnny Zoo) come for you: kill all three.",
             ["kill_marked", "combat_on_foot", "destroy_vehicle"], "bosses in cars (Miura/Z-Type/Isetta) with escorts; not required to finish the district"),
 # ------------------------------------------------ Residential (ste)
 "ste_se1": ("Steal a taxi (STYPECAB) undamaged, horn-pick up 3 Zaibatsu operatives (Clock Tower first), drive them to the SE Dock crane and get out.",
             ["steal_model", "horn_pickup", "drive_to_point", "crusher_crane", "deliver_intact"], "too much damage alerts cops and fails; killing a Z-operative fails"),
 "ste_se2": ("Collect the Factory Bus, horn-pick up Rednecks at Cobbs Store and The Ol' Banjo, Zaibatsu at the Village (two groups), bring all to the SRS Research Center, get off.",
             ["enter_mission_car", "bus", "horn_pickup", "drive_to_point", "deliver_intact"], "bus must survive; four stops across the district"),
 "ste_sm1": ("LABRAT'S PLAN: kill 47 Zaibatsu in The Village (any weapon).",
             ["kill_count", "gang_zone", "combat_on_foot"], "Zaibatsu fight back; must stay in the Village"),
 "ste_sm2": ("Meet Dirk at the Opry car park, pick a car, race to kill 3 escaped Loonies in 240 s (doors locked), win the Pickup, horn for Gran'pa at The Ol' Banjo, take him to the Research Center.",
             ["timed", "run_over_count", "kill_marked", "horn_pickup", "escort_protect", "deliver_intact"], "240 s race; killing Rednecks/wrecking their cars fails; Rednecks chase"),
 "ste_sm3": ("REDNECK ATTACK: defend the SRS generators against Rednecks for 2 minutes (at least one must survive).",
             ["defend_area", "timed", "kill_count", "combat_on_foot"], "reward drops with every generator lost"),
 "ste_sh1": ("TAXI TRAITOR TEST: 5 laps of the test track in the remote-control taxi under the record (120 s), then pick up 3 SRS traitors with it and blow it up each time.",
             ["remote_control", "timed", "horn_pickup", "destroy_vehicle"], "lap record; control is remote (player stands still)"),
 "ste_sh2": ("WATER CARRY ON: with SRS clones, get into the H2000 Water Company, destroy 4 turbines and then the generator, escape the guards.",
             ["walk_to_point", "destroy_objects", "combat_on_foot"], "levels 5-6 walkways; guards"),
 "ste_ze1": ("SCIENCE FRICTION: steal Montana's rigged Pickup, park it at the south end of the Clone Test Center, arm it, get out before it blows.",
             ["enter_mission_car", "car_bomb", "deliver_intact", "drive_to_point"], "rigged Pickup burns easily"),
 "ste_ze2": ("FIRE TRUCK FUN: steal a Cop Car (uniform), stop the SRS Security Van, take it to the Village garage; steal a Fire Truck, bring it to the Village, then flame 30 Rednecks in Mobile RV.",
             ["steal_model", "cop_siren", "deliver_intact", "run_over_count", "kill_count", "gang_zone"], "flamethrower prototype must survive; Fire Truck must survive"),
 "ste_zm1": ("OPERATION Z: deliver 4 loaded vehicles to the Village garage: the pill Pickup (Bowling Alley), a moving Meteor, Bean's red Limo (Disgracelands), and a Cop Car on a trailer (truck cab, trailer behind the cop station, crane).",
             ["steal_model", "destroy_vehicle", "deliver_intact", "truck_trailer", "crusher_crane"], "phone on level 6; Disgracelands guards; fragile cargo cars"),
 "ste_zm2": ("VALDEZ ALERT: with Z-Men, drive over rooftop ramps and along the old railway into the SRS Research Center, then on foot (anti-blast suits) rocket the 2 Cold Fusion generators.",
             ["drive_to_point", "walk_to_point", "destroy_objects", "combat_on_foot"], "rooftop ramp jumps; SRS guards"),
 "ste_zm3": ("LAW ENFORCEMENT LARCENY: steal a SWAT Van, then a Special Agent car, park each at Valdez's garage.",
             ["steal_model", "deliver_intact", "wanted_evasion"], "needs high wanted level for SWAT/FBI cars"),
 "ste_zh1": ("MURDER IN THE MALL: with Z-Men, kill 100 Scientists in The Mall on foot (no vehicles).",
             ["kill_count", "gang_zone", "combat_on_foot"], "on foot only; leaving the Mall"),
 "ste_zh2": ("DISTRACTION ACTION: from the video store climb the steps and pipes into the cop station, destroy the rooftop generator, take the truck with the Special Agent car trailer, then evade arrest for 60 s.",
             ["walk_to_point", "destroy_objects", "truck_trailer", "wanted_evasion", "timed"], "detaching the trailer fails; arrest"),
 "ste_re1": ("BLOW JOB: take the rigged Pickup to Fat Boy Jim's trailer, park, arm, run; then the second Pickup to the Zaibatsu barricade, park, arm, run.",
             ["enter_mission_car", "car_bomb", "deliver_intact", "drive_to_point"], "rigged Pickups burn from wall hits (pt6); 2nd Pickup is a gang car that can drive off (pt9_ste5); fenced phone approach"),
 "ste_re2": ("DOUBLE-CROSS CRUSH: steal a Zaibatsu Z-Type, run over 50 Scientists in the SRS zone; steal an SRS Meteor, run over 50 Zaibatsu in the Village (no time limit).",
             ["steal_model", "run_over_count", "gang_zone"], "gang gunfire burns borrowed cars (pt9); Z-Types are moving gang cars"),
 "ste_rm1": ("GREATEST HITS: assassinate the Zaibatsu hitmen, then Flambo Cortez in his protected Z-car at the Grand Central car park: rig a car bomb and park it beside him.",
             ["kill_marked", "car_bomb", "money_needed", "combat_on_foot"], "Flambo's car is weapon-proof except a car bomb; phone on level 4"),
 "ste_rm2": ("BENSON BURNER: steal a Benson, take it to Buckwheat's crane; get a truck cab, fetch Dwight T's trailer, load the Benson, pay Montana $5,000 for the bomb, deliver near the Cop crane.",
             ["steal_model", "truck_trailer", "crusher_crane", "money_needed", "car_bomb", "deliver_intact"], "destroying the trailer/Benson fails"),
 "ste_rm3": ("TANKS-GIVING: break into the Army Base, steal a Tank, drive it to Mobile RV.",
             ["tank", "steal_model", "deliver_intact", "wanted_evasion", "combat_on_foot"], "Army base guards and army wanted level"),
 "ste_rh1": ("GANG CAR BANG: destroy 5 SRS Meteors in SRS territory, then 5 Z-Types in the Village.",
             ["destroy_vehicle", "gang_zone"], "gang counter-fire"),
 "ste_rh2": ("PENAL TIES: meet the Liquor-Man by the strip club to get arrested into Alma Mater, find The Hump, get uniform + S-Uzi, start the riot and kill all 8 guards, keycard the gates, jump the raised bridge in a vehicle, change clothes at Disgracelands.",
             ["walk_to_point", "kill_count", "combat_on_foot", "drive_to_point", "wanted_evasion", "timed"], "deliberate arrest step; bridge gap jump"),
 "ste_end": ("THE FINAL JOB: after 21 jobs; Red Valdez, Billy Bob Bean and Dr LaBrat come for you: kill all three (every ped a mugger).",
             ["kill_marked", "combat_on_foot"], "all peds muggers; not required to finish the district"),
 # ------------------------------------------------ Industrial (bil)
 "bil_ke1": ("DECONSTRUCTION YARD: find Leo the Locksmith at the Water Towers, destroy the generator he cannot hit, lead him to the yard gateway, kill the Zaibatsu Construction Manager, then destroy a Zaibatsu truck.",
             ["walk_to_point", "destroy_objects", "escort_protect", "kill_marked", "destroy_vehicle", "combat_on_foot"], "Leo must live; yard guards; phone on level 5"),
 "bil_ke2": ("COP CAR SCRAP: steal Cop Cars and deliver three to the Krishna cranes (get out for the crane).",
             ["steal_model", "crusher_crane", "drive_to_point", "wanted_evasion"], "stealing cop cars raises wanted level"),
 "bil_km1": ("COSSACK CONVERSION: steal a truck from the Lubyanka Warehouses, horn for Russian workers at Mad Island Docks (4 groups), drive them to the Conversion House by Krishna Krushers.",
             ["enter_mission_car", "horn_pickup", "escort_protect", "deliver_intact"], "vicious warehouse guards; truck must survive"),
 "bil_km2": ("SUNBEAM CONTRACT: meet the Krishna converts, kill Russians in their territory to draw out waves of Russian assassins, kill all assassins.",
             ["kill_count", "kill_marked", "gang_zone", "combat_on_foot"], "deliberately lowers Russian respect"),
 "bil_km3": ("CONVERSION EVASION: break into the Z-Lab complex (Special Armored Vehicle offered), destroy the tanks, get a Krishna Karma Bus, let the Krishna board, take them to the Vedic Temple.",
             ["destroy_vehicle", "tank", "steal_model", "bus", "escort_protect", "drive_to_point"], "tanks around the lab; Krishna must live"),
 "bil_kh1": ("ROOFTOP RESCUE: destroy 3 generators above the Zaibatsu Power Plant containment block, follow the freed Krishna to two limos, clear the Z-guards blocking the way, lead them in the other limo to the Safehouse.",
             ["destroy_objects", "escort_protect", "kill_marked", "drive_to_point"], "both limos and the Krishna must survive; Zaibatsu chase"),
 "bil_kh2": ("POWER STATION: meet Krishna helpers, kill each Russian guard at the Kovski Power Station and plant a bomb where he stood (4), then watch from high ground.",
             ["kill_marked", "plant_on_foot", "walk_to_point", "combat_on_foot"], "bomb must be dropped exactly on the guard's spot"),
 "bil_re1": ("HOT DOG HOMICIDE: steal a Bus, fill it at bus stops, drive to the meat plant, stand on top of The Cage while passengers are processed, then drive the Hot Dog Van to the Kovski Diner.",
             ["steal_model", "bus", "drive_to_point", "walk_to_point", "deliver_intact"], "must stay on The Cage; rooftop phone (level 6)"),
 "bil_re2": ("MMM, RUSSIAN SAILORS: take the parked Z-Type, horn-pick up 4 Z-dealers (Bayano station, Bayano hospital, Escobar Power Cores, Sennora), drive them to the crane by the river, get out.",
             ["enter_mission_car", "horn_pickup", "drive_to_point", "crusher_crane", "deliver_intact"], "Z-Type burns over ~1000 blocks of traffic (pt7-pt9); killing dealers fails; rooftop phone (level 6)"),
 "bil_rm1": ("OFFICER DOWN: in 5 minutes destroy 2 Cop Cars, then a SWAT Van, then 2 Special Agent cars.",
             ["destroy_vehicle", "timed", "wanted_evasion"], "SWAT/FBI cars appear only with high wanted level"),
 "bil_rm2": ("KARMA ASSASSINS: protect Jerkov: kill 8 Karma assassins, then destroy Nova Bright's armoured Karma Bus (only a car bomb works).",
             ["kill_marked", "combat_on_foot", "car_bomb", "destroy_vehicle", "money_needed"], "bus immune to guns"),
 "bil_rm3": ("TANKS A LOT: destroy the 3 Zaibatsu tanks before they crush Jerkov's Kovski cars.",
             ["destroy_vehicle", "tank", "defend_area"], "tanks; protected cars must survive"),
 "bil_rh1": ("VEDIC MASSACRE: find Ivan and 3 soldiers, get a vehicle big enough, drive to the Vedic Temple, on foot kill Krishna and survive 2 minutes inside.",
             ["escort_protect", "steal_model", "drive_to_point", "kill_count", "timed", "combat_on_foot"], "using a vehicle or leaving the temple fails"),
 "bil_rh2": ("SUPER GRASS RESCUE: bomb 3 generators to open the Zaibatsu Power Core door, protect the freed Kovski from 3 assassins, take them to Uncle Vanka, steal a Cop Car, siren on, stop the informant's car, get him into the Cop Car, deliver to Lubyanka Docks, and back.",
             ["destroy_objects", "escort_protect", "kill_marked", "steal_model", "cop_siren", "drive_to_point"], "informant flees; Kovski/Vanka must live"),
 "bil_ze1": ("IT WAS AN ACCIDENT: collect the unstable package, deliver to Bilovski; get a Hot Dog Van, load poisoned hot dogs, serve target two; drive the remote-rigged Kovski limo into the Russian area and lead the Russians into the Krishna quarter.",
             ["walk_to_point", "deliver_intact", "steal_model", "drive_to_point", "escort_protect"], "package unstable; killing targets early fails; Russians must follow"),
 "bil_ze2": ("GRAND THEFT AUTO: steal and park at the Zaibatsu Power Cores: the Jefferson (Krishna Krushers), a Kovski Bulwark (smash and grab), an unmarked car on an island reached via rooftops, a Cop Car on a trailer (truck cab, crane).",
             ["steal_model", "deliver_intact", "truck_trailer", "crusher_crane"], "owners fight back; rooftop route to the island"),
 "bil_zm1": ("PAYBACK: meet Ziggy Pole in a Kovski car (Bulwark), visit 3 more dealers (kill the Kovski cash-dodger and gang), then at the Brown-Eye Sewage Works go round the back, destroy the Soviet generators and drive the unstable reactor-fuel truck to the Safehouse.",
             ["steal_model", "drive_to_point", "kill_marked", "destroy_objects", "deliver_intact", "combat_on_foot"], "killing the wrong dealer fails; unstable truck"),
 "bil_zm2": ("LOCK-OUT: back door at Tedium Docks, fetch Satchmo the Safecracker (slow walker; dies to a booby trap), steal a Kovski Bulwark to bluff the door, inside take the AI Brain truck, blow the 2 generators over the door, drive to the Safehouse.",
             ["escort_protect", "steal_model", "drive_to_point", "destroy_objects", "deliver_intact", "combat_on_foot"], "the Safecracker's death is scripted; truck must survive"),
 "bil_zm3": ("GANG WAR: steal a Russian Bulwark, run over 50 Krishna in their quarter; steal a Krishna Karma Bus, run over 50 Russians in the Russian area.",
             ["steal_model", "run_over_count", "bus", "gang_zone"], "must use the named vehicles"),
 "bil_zh1": ("I'D LIKE A TANK PLEASE, BOB!: steal and park at Uno Carb's garage a SWAT Van, a Special Agent car, then a Tank.",
             ["steal_model", "deliver_intact", "tank", "wanted_evasion"], "SWAT/FBI/army need high wanted levels"),
 "bil_zh2": ("ARMY BASE ALERT: get into the Army Base, steal a Tank, bring it to the garage.",
             ["tank", "steal_model", "deliver_intact", "combat_on_foot", "wanted_evasion"], "army guards"),
 "bil_end": ("FINAL JOB: after 21 jobs; Uno Carb, Sunbeam and Jerkov come for you: kill all three.",
             ["kill_marked", "combat_on_foot"], "all peds muggers; not required to finish the district"),
}

# rooftop/raised routes named in the briefs (besides raised phones and LOCATE boxes at z >= 4, added automatically)
BRIEF_ROOFTOP = {"wil_lm2": "climb the stairs in J-Lab", "ste_zm2": "rooftop ramps then the old railway",
                 "ste_zh2": "steps and pipes into the cop station, rooftop generator", "ste_sh2": "walkways at z 5-6",
                 "bil_ze1": "Z-contact on the roof", "bil_ze2": "island reached via rooftops",
                 "bil_kh1": "generators above the containment block", "bil_kh2": "higher ground to watch",
                 "bil_re1": "stand on top of The Cage", "bil_rh1": "walkways in the temple"}

# our 3D playthrough status (docs/playthrough-downtown.md, docs/playthrough-districts.md, 8 Nov 2026)
STATUS = {
    "wil_tra": ("completed", "TUTORIAL complete (playthrough-downtown.md part 2 runs)"),
    "wil_ze1": ("completed", "COP CAR CRUSH JOB COMPLETE pt4_wil15"),
    "wil_ze2": ("completed", "WHEELER-DEALING JOB COMPLETE pt8_ze2f (GTA2_SPEED=2), after 17 short sessions"),
    "wil_le2": ("completed", "PIZZA CAKE JOB COMPLETE pt6_le2a, pt7_le2e (chase view)"),
    "wil_le1": ("completed", "RADIO ZA-ZA JOB COMPLETE pt7_le2e; failed 3x in part 8 (muggers)"),
    "wil_ye1": ("completed", "GET ZITZAKI JOB COMPLETE pt8_chain1, pt9_wil3/4/5/6"),
    "wil_ye2": ("attempted", "BANK ROBBERY: guards found and shot, arrested at the bank (pt9_wil6)"),
    "ste_re1": ("completed", "BLOW JOB Mission Complete pt7_ste5; stage 1 again pt9_ste5"),
    "ste_re2": ("attempted", "DOUBLE-CROSS CRUSH: phone answered pt8_ste3, pt9_ste2/3/4/6; Z-Type never jacked"),
    "bil_re2": ("attempted", "RUSSIAN SAILORS: 16+ sessions, furthest all 4 dealers aboard (pt7_bil9, pt8_bil11), Z-Type burns"),
    "bil_re1": ("attempted", "HOT DOG HOMICIDE: phone only, refused 3104 after a failed RUSSIAN SAILORS (pt8_bil5)"),
    "bil_ze1": ("attempted", "IT WAS AN ACCIDENT: tour take 3 (tour_bil_phone), JOB FAILED before the package"),
}

BONUS_LEVELS = [
    # (files, kind, objective) -- kind from the scripts' zone names + community pages; letters uncertain
    ("lorne2", "ice-cream vans", "Stinger with vehicle machine guns: destroy as many of the 12 ice-cream vans as possible; time extends every 4 vans (community: Bonus A-C)"),
    ("mike1", "race", "three-lap timed race in a Furore GT; running over roadside peds adds time/points (script zones Green_Park, Race_Island; community: Bonus D-F)"),
    ("mike2", "massacre", "S-Uzi massacre: kill as many (gang) peds as possible in 30 s, +time every 15 kills (script gang EVILGANG; community: Bonus G-I)"),
]
BONUS_SKILLS = {"ice-cream vans": ["destroy_vehicle", "timed", "drive_to_point"],
                "race": ["drive_to_point", "timed", "run_over_count"],
                "massacre": ["kill_count", "timed", "combat_on_foot"]}

GANG_ORDER = {"wil": ["yakuzagang", "zaibatsugang", "looniegang"],
              "ste": ["sciegang", "zaibgang", "redngang"],
              "bil": ["krisgang", "zaibgang", "russgang"]}
TIER = {"green": 1, "yellow": 2, "red": 3, "plain": 0}

def kf_skills(k):
    sk = ["timed"]
    if k.get("vehicle"):
        sk.append("tank" if k["vehicle"] == "TANK" else "enter_mission_car")
    if k.get("method") == "BY_VEHICLE" or (k.get("weapon") == "NO_WEAPON"):
        sk.append("run_over_count")
    elif k.get("target") == "CAR":
        sk.append("destroy_vehicle")
    else:
        sk.append("kill_count")
    if k.get("z") and k["z"] >= 4: sk.append("rooftop_access")
    return sk

def build(game, misdir, repo):
    t, data = gather(game, misdir)
    cat = OrderedDict(generated_by="tools/mission_catalogue.py", sources=SOURCES, skills=SKILLS,
                      district_files={d: n for d, n in DISTRICTS}, districts=OrderedDict())
    totals = Counter(); skill_need = Counter(); skill_need_open = Counter()
    sk_jobs = Counter(); sk_jobs_open = Counter(); sk_kf = Counter(); sk_bonus = Counter()
    for d, dd in data.items():
        jobs_out = []
        for mid, r in dd["jobs"].items():
            cur = CURATED.get(mid)
            ph = r["phones"]
            gang = ph[0]["gang"] if ph and ph[0].get("gang") else None
            colour = ph[0]["colour"] if ph else None
            if mid.endswith("_end"): kind = "final"
            elif mid.endswith("_tra"): kind = "tutorial"
            else: kind = "phone"
            skills = list(cur[1]) if cur else []
            lvl = max([p.get("level") or 0 for p in ph] or [0])
            raised = lvl >= 4 or any(z >= 4 for z in r["locate_levels"]) or mid in BRIEF_ROOFTOP
            if raised and "rooftop_access" not in skills: skills.append("rooftop_access")
            if not raised and "rooftop_access" in skills and lvl < 4:
                pass  # curated from the briefs (rooftop routes inside the job)
            st = STATUS.get(mid, ("not attempted", ""))
            follow_of = sorted({p["after"] for p in ph if p.get("after")})
            if kind == "phone":
                resp = ph[0]["respect"]
                prereq = f"{GANG_NAMES.get(gang, gang)} respect >= {resp} ({colour} phone)"
                if follow_of:
                    prereq += "; offered on the same phone(s) after " + " / ".join(follow_of) + " (follow-up job)"
                rv = dd["rivals"].get(gang)
                if rv: prereq += f"; passing it lowers {GANG_NAMES.get(rv, rv)} respect"
            elif kind == "final":
                prereq = "all 21 phone jobs passed (missions-passed counter = 21); launched by the base script, not a phone. Optional: the district ends at the finish score + level-end point"
            else:
                prereq = "none (plain phone at the spawn)"
            job = OrderedDict(
                id=mid, title=r["title"] or (cur[0].split(":")[0] if cur else mid), kind=kind,
                gang=GANG_NAMES.get(gang, gang) if gang else None, tier=colour,
                phones=[OrderedDict(x=p["x"], y=p["y"], level=p.get("level"), colour=p["colour"]) for p in ph],
                prerequisite=prereq, follow_up_of=follow_of or None,
                reward=r["reward"], objective=cur[0] if cur else r["first_brief"],
                skills=skills, hazards=cur[2] if cur else "",
                status=st[0], status_evidence=st[1],
                first_brief=r["first_brief"], title_key=r["title_key"],
                cars_created=[c for c in r["cars_created"] if c != "END"],
                models_required=r["models_required"], destroy_models=r["destroy_models"],
                bonus_checks=r["bonus_checks"], timers_s=r["timers_s"], script_features=r["features"],
                script=f"assets-src/missions/{d}_m/{mid}.mis")
            jobs_out.append(job)
            totals[(d, "jobs")] += 1; totals[(d, st[0])] += 1
            for s_ in skills:
                skill_need[s_] += 1; sk_jobs[s_] += 1
                if st[0] != "completed": skill_need_open[s_] += 1; sk_jobs_open[s_] += 1
        order = {g: i for i, g in enumerate(GANG_ORDER[d])}
        def key(j):
            g = next((k for k, v in GANG_NAMES.items() if v == j["gang"] and k in order), None)
            return (0 if j["kind"] == "tutorial" else 2 if j["kind"] == "final" else 1,
                    order.get(g, 9), TIER.get(j["tier"] or "plain", 0), 1 if j["follow_up_of"] else 0, j["id"])
        jobs_out.sort(key=key)
        kfs = []
        for k in dd["kill_frenzies"]:
            k = OrderedDict(k); k["skills"] = kf_skills(k); k["status"] = "not attempted"; k["kind"] = "kill_frenzy"
            kfs.append(k)
            totals[(d, "kf")] += 1
            for s_ in k["skills"]: skill_need[s_] += 1; skill_need_open[s_] += 1; sk_kf[s_] += 1
        cat["districts"][d] = OrderedDict(name=dd["name"], start=dd["start"], finish_score=dd["finish_score"],
            level_end=dd["level_end"], bonus_tokens=dd["bonus_tokens"], info_phones=dd["info_phones"],
            rivals={GANG_NAMES[g]: GANG_NAMES.get(v, v) for g, v in dd["rivals"].items()},
            jobs=jobs_out, kill_frenzies=kfs)
    bl = []
    for f, kind, obj in BONUS_LEVELS:
        for diff in ("e", "m", "h"):
            have = os.path.exists(os.path.join(game, "data", f + diff + ".SCR"))
            bl.append(OrderedDict(id=f + diff, files=[f + diff + ".gmp", f + diff + ".SCR"], present=have, kind=kind,
                                  difficulty={"e": "easy", "m": "medium", "h": "hard"}[diff], objective=obj,
                                  skills=BONUS_SKILLS[kind], status="not attempted",
                                  prerequisite="engine-side: each district script ends with FINISH_LEVEL (BONUS_1) at the level-end point; "
                                               "which bonus level follows, and the token rule, are not in the scripts (unverified). "
                                               "Can be loaded directly (SWAP_LEVEL)"))
            for s_ in BONUS_SKILLS[kind]: skill_need[s_] += 1; skill_need_open[s_] += 1; sk_bonus[s_] += 1
    cat["bonus_levels"] = bl
    cat["totals"] = OrderedDict(
        per_district={d: OrderedDict(jobs=totals[(d, "jobs")], completed=totals[(d, "completed")],
                                     attempted=totals[(d, "attempted")], not_attempted=totals[(d, "not attempted")],
                                     kill_frenzies=totals[(d, "kf")]) for d, _ in DISTRICTS},
        bonus_levels=len(bl),
        skill_counts_all=OrderedDict(sorted(skill_need.items(), key=lambda kv: -kv[1])),
        skill_counts_not_completed=OrderedDict(sorted(skill_need_open.items(), key=lambda kv: -kv[1])),
        skill_counts_jobs=OrderedDict(sorted(sk_jobs.items(), key=lambda kv: -kv[1])),
        skill_counts_jobs_not_completed=OrderedDict(sorted(sk_jobs_open.items(), key=lambda kv: -kv[1])),
        skill_counts_kill_frenzies=OrderedDict(sorted(sk_kf.items(), key=lambda kv: -kv[1])),
        skill_counts_bonus_levels=OrderedDict(sorted(sk_bonus.items(), key=lambda kv: -kv[1])))
    os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
    with open(os.path.join(repo, "docs", "missions-catalogue.json"), "w") as f:
        json.dump(cat, f, indent=1, ensure_ascii=False)
    with open(os.path.join(repo, "docs", "missions-catalogue.md"), "w") as f:
        f.write(markdown(cat))
    return cat

def fmt_phone(j):
    if not j["phones"]: return "(no phone)"
    return " / ".join(f"{p['colour']} {p['x']:g},{p['y']:g} L{p['level'] if p['level'] is None else format(p['level'], 'g')}" for p in j["phones"])

def md_escape(s):
    return (s or "").replace("|", "/").replace("\n", " ")

def markdown(cat):
    L = []
    w = L.append
    w("# GTA2 mission catalogue (all districts)\n")
    w("Generated by `tools/mission_catalogue.py build` from the game's own text (`data/e.gxt`, read in place), "
      "the decompiled scripts (`assets-src/missions`, see `docs/missions.md`) and the maps (phone levels); "
      "objectives and skills curated from the briefs, cross-checked with community lists. "
      "Machine-readable twin: `docs/missions-catalogue.json` (one record per job, kill frenzy and bonus level, "
      "with the script path, cars, required models, kill counters and timers, for spawning per-mission agents).\n")
    w("District files: `wil` = Downtown, `ste` = Residential, `bil` = Industrial. Coordinates are map blocks; "
      "`L` is the standing height z of the phone (the script's z, or for z=255 (on top) the highest floor in the map column; street = 2; L4+ = raised terrace/roof). "
      "Prerequisite respect is the `DO_PHONE_TEMPLATE` argument (green 0, yellow 2, red 4); each yellow phone pair "
      "offers a third job and each red phone a second job after the first (`follow-up`). Status is our 3D "
      "playthrough status from `docs/playthrough-downtown.md` and `docs/playthrough-districts.md` (8 Nov 2026).\n")
    T = cat["totals"]
    w("## Totals\n")
    w("| district | jobs (incl. tutorial/final) | completed in 3D | attempted | not attempted | kill frenzies |")
    w("|---|---|---|---|---|---|")
    for d, v in T["per_district"].items():
        w(f"| {cat['district_files'][d]} (`{d}`) | {v['jobs']} | {v['completed']} | {v['attempted']} | {v['not_attempted']} | {v['kill_frenzies']} |")
    w(f"\nBonus levels: {T['bonus_levels']} (3 kinds x 3 difficulties), none attempted.\n")
    w("### Skills needed (how many items need each)\n")
    w("| skill | what it means | phone/tutorial/final jobs (67) | of those not completed | kill frenzies (60) | bonus levels (9) |")
    w("|---|---|---|---|---|---|")
    for s in sorted(cat["skills"], key=lambda s: (-T["skill_counts_jobs"].get(s, 0), -T["skill_counts_all"].get(s, 0))):
        w(f"| `{s}` | {cat['skills'][s]} | {T['skill_counts_jobs'].get(s, 0)} | {T['skill_counts_jobs_not_completed'].get(s, 0)} | "
          f"{T['skill_counts_kill_frenzies'].get(s, 0)} | {T['skill_counts_bonus_levels'].get(s, 0)} |")
    w("")
    for d, dd in cat["districts"].items():
        w(f"## {dd['name']} (`{d}`)\n")
        w(f"Start {dd['start'][0]:g},{dd['start'][1]:g}; finish score ${dd['finish_score']:,}, then the level-end arrow at "
          f"{dd['level_end'][0]:g},{dd['level_end'][1]:g} (`FINISH_LEVEL (BONUS_1)`); {dd['bonus_tokens']} bonus tokens; "
          f"info phones: " + ", ".join(f"{p['x']:g},{p['y']:g}" for p in dd["info_phones"]) + ".")
        w("Respect: passing a job lowers the rival's respect: " +
          "; ".join(f"{g} -> {r}" for g, r in dd["rivals"].items()) + ".\n")
        groups = OrderedDict()
        for j in dd["jobs"]:
            g = j["gang"] or ("Tutorial / final job")
            groups.setdefault(g, []).append(j)
        for g, js in groups.items():
            w(f"### {dd['name']}: {g}\n")
            w("| id | job | phone (x,y level) | prerequisite | reward | objective | skills | hazards | status |")
            w("|---|---|---|---|---|---|---|---|---|")
            for j in js:
                st = j["status"] + (f" ({md_escape(j['status_evidence'])})" if j["status_evidence"] else "")
                w(f"| `{j['id']}` | {md_escape(j['title'])} | {fmt_phone(j)} | {md_escape(j['prerequisite'])} | "
                  f"{'$' + format(j['reward'], ',') if j['reward'] else ''} | {md_escape(j['objective'])} | "
                  f"{', '.join('`'+s+'`' for s in j['skills'])} | {md_escape(j['hazards'])} | {st} |")
            w("")
        w(f"### {dd['name']}: kill frenzies ({len(dd['kill_frenzies'])})\n")
        w("Start by walking onto the skull or entering the parked vehicle; prerequisite: none (always available). "
          "Text from `e.gxt`; counts/timers from `START_BONUS_CHECK` / `DO_BASIC_KF_TEMPLATE`.\n")
        w("| id | at (x,y level) | start | weapon | task | target | count | time | skills | status |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for k in dd["kill_frenzies"]:
            w(f"| `{k['id']}` | {k['x']:g},{k['y']:g} L{k.get('z') and int(k['z'])} | {k.get('start','')} | {k['weapon']} | "
              f"{md_escape(k['text'])} | {k.get('target','')}{' / ' + k['occupation'] if k.get('occupation') not in (None, 'NONE', 'NO_OCCUPATION') else ''} | "
              f"{k.get('count','')} | {k.get('time_s','')} s | {', '.join('`'+s+'`' for s in k['skills'])} | {k['status']} |")
        w("")
    w("## Bonus levels\n")
    w("Separate maps in `data/` (`<name><e|m|h>.gmp/.SCR`). The kind is read from the scripts' zone/gang names "
      "and the community pages; the A-I letters and the unlock rule are community claims not visible in the scripts.\n")
    w("| id | files | kind | difficulty | objective | skills | prerequisite | status |")
    w("|---|---|---|---|---|---|---|---|")
    for b in cat["bonus_levels"]:
        w(f"| `{b['id']}` | {', '.join(b['files'])} | {b['kind']} | {b['difficulty']} | {md_escape(b['objective'])} | "
          f"{', '.join('`'+s+'`' for s in b['skills'])} | {md_escape(b['prerequisite'])} | {b['status']} |")
    w("\n## Sources\n")
    for k, v in cat["sources"].items():
        w(f"- {k}: {v}")
    w("\n## Uncertainties\n")
    w("- Skills/objectives are curated from the briefs and script features (`script_features` in the JSON); a job's "
      "full branch logic is only in its `.mis`. Rooftop access is set automatically when the phone stands at L4+ or "
      "a `LOCATE_*` box is at z >= 4.\n"
      "- Rival-respect pairs are inferred from the template's counter arguments (consistent with pt4_wil15: a "
      "Zaibatsu job made the Loonies refuse).\n"
      "- Follow-up jobs (`*m3`, `*h2`) are attached to the phones whose template names them; whether the m3 job "
      "needs both m1 and m2 first is engine logic (`DO_PHONE_TEMPLATE`), not visible in the decompile.\n"
      "- SWAT/FBI/army vehicles are assumed to need a high wanted level (game behaviour, not in the job scripts).\n"
      "- Bonus-level letters (A-I) and the token unlock rule come from community pages and are unverified.\n"
      "- Community names differ for PC/PlayStation (e.g. WHO'S MAD? / Who's Behind You!); titles here are the PC "
      "`e.gxt` strings.\n")
    return "\n".join(L) + "\n"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "build"])
    ap.add_argument("--game", default=os.path.join(HOME, "game"))
    ap.add_argument("--mis", default=os.path.join(HOME, "assets-src", "missions"))
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    if a.cmd == "dump": cmd_dump(a)
    else:
        cat = build(a.game, a.mis, a.repo)
        print(json.dumps(cat["totals"], indent=1))

if __name__ == "__main__":
    main()
