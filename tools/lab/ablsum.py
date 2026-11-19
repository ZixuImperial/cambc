"""Summarise a local A/B run by tools/lab/abl.sh: ablsum.py OUTDIR BOT_A BOT_B.

Reads OUTDIR/games.list ("<id> <bot a> <bot b> <map>") and the per-game statistics JSON OUTDIR/st/<id>.json
written by `cambc run-batch --statistics`. Writes OUTDIR/games.jsonl (one line of metrics per game),
OUTDIR/run/job_0.out (RESULT lines in the tools/condor/absum.py format) and prints the summary:
wins, gems, kills, deaths, earned gold, wards, Treasure emblems, fuel exhaustions and bot faults per side,
then wins per map slice (playbook slices and the pathological maps) and per map."""
import collections, glob, json, os, re, sys

out, A, B = sys.argv[1], sys.argv[2], sys.argv[3]
TREASURE_IDS = {19, 21, 23}
_st = os.path.join(out, "st")
if not (os.path.isdir(_st) and os.listdir(_st)) and os.path.exists(os.path.join(out, "games.jsonl")) and any(
        json.loads(ln).get("ok") for ln in open(os.path.join(out, "games.jsonl")) if ln.strip()):
    # abl.sh deletes st/ after its summary: rerunning on a finished run would mark every game FAILED and erase the
    # run's results from tools/lab/abindex.py (sprt.py, abstat.py)
    sys.exit(f"ablsum: {_st} is gone but {out}/games.jsonl holds results: refusing to overwrite them "
             f"(read summary.txt, or `abstat.py --run {out}`)")


def item_id(name):
    m = re.search(r"\((\d+)\)", name)
    return int(m.group(1)) if m else None


def is_treasure_emblem(name):
    i = item_id(name)
    if i is not None:
        return i in TREASURE_IDS
    n = name.lower()
    return "treasure" in n and "emblem" in n


def pair_deaths(d, team):
    """9 Nov (owner: a linked C&I pair death counts once, GR :381/:442): {'pair': n} = the side's Cassi+Issac joint deaths (the duo always dies
    together, so n = min of the two bodies' deaths), when every champion carries its design ('name': 'Unknown champion (N)', the platform's
    and, from 9 Nov, cxe's form; 3 = Cassi, 4 = Issac). {} when a record has no designs (older games): the pair count is then unknown."""
    import re as _re
    dd = {}
    for c in d["champions"]:
        if c["team"] != team:
            continue
        nm = str(c.get("name", ""))
        mm = _re.search(r"\((\d+)\)", nm)
        k = int(mm.group(1)) if mm else {"cassi": 3, "issac": 4}.get(nm.strip().lower(), -1 if nm.strip() else None)  # the local CLI names them ("Ryth")
        if k is None:
            return {}
        dd[k] = dd.get(k, 0) + int(float(c["metrics"].get("deaths", 0)))
    return {"pair": min(dd[3], dd[4]) if 3 in dd and 4 in dd else 0, "bodies": len([c for c in d["champions"] if c["team"] == team])}


def side_metrics(d, team):
    m = collections.Counter()
    for c in d["champions"]:
        if c["team"] != team:
            continue
        met = c["metrics"]
        for k in ("kills", "deaths", "earnedGold", "collectedGems"):
            m[k] += int(float(met.get(k, 0)))
        m["treasure"] += sum(int(i["quantity"]) for i in c["items"] if is_treasure_emblem(i["item"]))
    for e in d["events"]:
        if e["owner"].get("team") != team:
            continue
        if e["kind"] == "wardPlacement":
            m["wards"] += len(e["entries"])
        elif e["kind"] == "fuelExhausted":
            m["fuel"] += len(e["entries"])
    m["gems"] = next((int(t["submittedGems"]) for t in d["teams"] if t["team"] == team), 0)
    m.update(pair_deaths(d, team))
    m["faults"] = int(d.get("diagnostics", {}).get("botFaults", {}).get(team, 0))
    return m


games = []
for line in open(os.path.join(out, "games.list")):
    p = line.split()
    if len(p) < 4:
        continue
    gid, a, b, mp = p[0], p[1], p[2], p[3]
    f = os.path.join(out, "st", gid + ".json")
    try:
        d = json.load(open(f))
    except Exception:
        games.append(dict(id=gid, a=a, b=b, map=mp, ok=False))
        continue
    oc = d["match"].get("outcome")
    games.append(dict(id=gid, a=a, b=b, map=mp, ok=True,
                      win="A" if oc == "teamA" else ("B" if oc == "teamB" else "?"),
                      rounds=int(d["match"].get("roundsCompleted", 0)),
                      sa=dict(side_metrics(d, "teamA")), sb=dict(side_metrics(d, "teamB"))))

os.makedirs(os.path.join(out, "run"), exist_ok=True)
with open(os.path.join(out, "games.jsonl.tmp"), "w") as gj, open(os.path.join(out, "run", "job_0.out"), "w") as jo:
    for g in games:
        gj.write(json.dumps(g) + "\n")
        if not g["ok"]:
            continue
        res = f"Team {g['win']} ({g['a'] if g['win'] == 'A' else g['b']}) wins round {g['rounds']}/2000" if g["win"] != "?" else f"draw round {g['rounds']}/2000"
        fa = "{gems}/{kills}/{deaths}/{earnedGold}".format(**collections.defaultdict(int, g["sa"]))
        fb = "{gems}/{kills}/{deaths}/{earnedGold}".format(**collections.defaultdict(int, g["sb"]))
        jo.write(f"RESULT {g['id']} {g['a']} {g['b']} {g['map']} | {res} | A {fa} | B {fb}\n")
os.replace(os.path.join(out, "games.jsonl.tmp"), os.path.join(out, "games.jsonl"))  # readers never see half a file

tot = collections.Counter(); per = collections.defaultdict(lambda: [0, 0]); side = {A: collections.Counter(), B: collections.Counter()}
fails = 0; n_ok = 0
for g in games:
    if not g["ok"] or g["win"] == "?":
        fails += 1
        continue
    n_ok += 1
    winner = g["a"] if g["win"] == "A" else g["b"]
    tot[winner] += 1
    per[g["map"]][0 if winner == A else 1] += 1
    for bot, s in ((g["a"], g["sa"]), (g["b"], g["sb"])):
        side[bot].update(s)
n = sum(tot.values())
print(f"{A} vs {B}: {tot[A]}-{tot[B]} of {n} decided games ({fails} failed/drawn/unparsed)")
sa, sb = side[A], side[B]
share = sa["gems"] / max(1, sa["gems"] + sb["gems"])
print(f"gems {sa['gems']}-{sb['gems']} (share {share:.3f})  kills {sa['kills']}-{sb['kills']}  deaths {sa['deaths']}-{sb['deaths']}  earned gold {sa['earnedGold']}-{sb['earnedGold']}")
k = max(1, n_ok)
print(f"per game: wards {sa['wards']/k:.0f}-{sb['wards']/k:.0f}  treasure emblems {sa['treasure']/k:.1f}-{sb['treasure']/k:.1f}  "
      f"fuel exhaustions {sa['fuel']}-{sb['fuel']} (total)  bot faults {sa['faults']}-{sb['faults']} (total)")
slices = {}
for f in sorted(glob.glob("/homes/zw4424/condor-work/teams/pb2/maplists/*.txt")) + ["/data/zw4424/patho4.txt"]:
    try:
        slices[os.path.basename(f)[:-4]] = {l.strip() for l in open(f) if l.strip()}
    except OSError:
        pass
parts = []
for name, maps in slices.items():
    if name == "all36":
        continue
    w = [0, 0]
    for m, r in per.items():
        if m in maps:
            w[0] += r[0]; w[1] += r[1]
    if sum(w):
        parts.append(f"{name} {w[0]}-{w[1]}")
print("per slice (A wins-B wins):", ", ".join(parts))
print("per map (A wins-B wins):", ", ".join(f"{m} {w[0]}-{w[1]}" for m, w in sorted(per.items())))
try:  # map-pair verdict (tools/lab/abstat.py): both sides of a map are one trial, so splits carry no evidence
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import abstat
    rows, half, _, _ = abstat.rows_from_runs([out], A)
    nmaps = len({g["map"] for g in games})
    st = abstat.summarize(rows)
    if st:
        print(f"map pairs: {A} won both {st['w']}, split {st['d']}, lost both {st['l']} -> score {st['score']:.3f} "
              f"[{st['lo']:.3f}, {st['hi']:.3f}] (95% CI), LOS {st['los'] * 100:.0f}%: {abstat.verdict(st, A, B)}"
              + (f" (!! {nmaps - st['n']} maps with a FAILED game are left out)" if nmaps > st["n"] else ""))
except Exception as e:  # never fail the summary over the extra line
    print(f"map pairs: unavailable ({e})")
try:  # per-game features for tools/lab/gamerep.py, written while st/ still exists (abl.sh deletes it next)
    if os.path.isdir(os.path.join(out, "st")):
        import gamefeat
        print(f"game features: {gamefeat.extract_run(out)} games -> games_rich.jsonl (reports: tools/lab/gamerep.py)")
except Exception as e:  # never fail the summary over the features
    print(f"game features: unavailable ({e})")
try:  # mechanism metrics (tools/lab/mech.py, paired by map) for runs that keep their replays; MECH=0 turns them off
    if os.environ.get("KEEP") == "1" and os.environ.get("MECH", "1") != "0" and os.path.isdir(os.path.join(out, "rep")):
        import mech
        mech.print_run(out, A, jobs=4)
except Exception as e:  # never fail the summary over the mechanism table
    print(f"mechanism metrics: unavailable ({e})")
