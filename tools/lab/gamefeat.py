"""Per-game features from a cambc statistics JSON: the raw material of tools/lab/gamerep.py.

Works on local games (`cambc run-batch --statistics --json`: abl.sh's st/<id>.json, which ablsum.py turns into
games_rich.jsonl before abl.sh deletes them) and on platform match summaries (tools/lab/diag.sh: <matchId>.json).

usage: python3 -I tools/lab/gamefeat.py STATS.json [MAP.map26a]          print one game's features
       python3 -I tools/lab/gamefeat.py --run RUNDIR [--jobs N]           write RUNDIR/games_rich.jsonl from RUNDIR/st/

extract(stats_path, map_path=None) -> dict:
  rounds, outcome ("A"/"B"), ended ("race": a team reached 1000 tributed gems; "limit": round-2000 tiebreak),
  W, H, draft {A: [...], B: [...]}, A and B (team features below), groups (per camp group), champs (per champion).
Team features (zones need the map: own / mid / enemy by walk distance from the two spawns, ratio < 0.4 / > 0.6;
offwalk = dash or crystal islands):
  score, max_lead, lead_for_good (round from which the final leader never trailed, on the winner's side),
  sub_rR, col_rR, gold_rR (tributed, collected, earned gold at round R, R in CPS; "end" too),
  cap_n (captures; one shared by several champions counts once), cap_gems, cap_own / cap_mid / cap_enemy,
  cap_early / cap_midgame / cap_late (<= 500 / <= 1000 / later),
  loot_gems (gems taken from champions we killed), first_cap,
  kills, deaths, deaths_camp, deaths_own / deaths_mid / deaths_enemy, deaths_early / deaths_midgame / deaths_late,
  bag_lost_champ (carried gems handed to enemy champions by our deaths), bag_lost_camp (carried gems destroyed by
  monsters), dead_share (share of champion-rounds spent dead), sub_n, sub_mean (mean tribute), first_sub,
  carried_end, clears, groups_capped, stolen (groups we cleared that the enemy captured within 20 rounds),
  steals (groups the enemy cleared that we captured), wards, wards_100, first_item, spent_gold, gold_end,
  locks (altar locks bought), crystals, fuel (exhaustions), faults.
check: problems found by comparing kills, deaths, captures + loot and tributes with the statistics' totals (empty
  when they agree).
Amounts the events do not carry (gems per capture, loot, bags) come from the per-round champion timelines, as in
tools/lab/liveres.py.
"""
import bisect
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map26a  # noqa: E402

CPS = (150, 300, 500, 800, 1000, 1500)
# platform summaries name champions by number: bodies by champion_type, picks by champion_draft (SDK 3.0.4 cambc.h)
BODY = ["Ryth", "Vesper Vale", "Vendetta", "Cassi", "Issac", "Stellar", "Prism", "Marcella", "Willow", "Ren", "Varg",
        "Tavi", "Heart of Ruin"]
DRAFT = ["Ryth", "Vesper Vale", "Vendetta", "Cassi & Issac", "Stellar", "Prism", "Marcella", "Willow", "Ren", "Varg",
         "Tavi", "Heart of Ruin"]
DIRS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
DEAD_ROUNDS = 60
_fields = {}


class Series:
    """A run-length encoded timeline: value at sample r (sample 0 = before round 1)."""

    def __init__(self, runs):
        self.starts, self.vals, s = [], [], 0
        for r in runs:
            self.starts.append(s)
            self.vals.append(float(r["value"]))
            s += int(r["duration"])

    def at(self, r):
        if not self.vals:
            return 0.0
        return self.vals[max(0, bisect.bisect_right(self.starts, r) - 1)]


def walk_fields(map_path):
    """{'A': {tile: walk distance from team A's spawn}, 'B': ...}; walls and holes block, 8 directions."""
    if not map_path or not os.path.exists(map_path):
        return None
    if map_path in _fields:
        return _fields[map_path]
    m = map26a.load(map_path)
    W, H = m["W"], m["H"]
    blocked = set(m["wall"]) | set(m["hole"])
    out = {}
    for side, src in (("A", m["spawnA"]), ("B", m["spawnB"])):
        d = {p: 0 for p in src}
        q = collections.deque(src)
        while q:
            x, y = q.popleft()
            for dx, dy in DIRS:
                p = (x + dx, y + dy)
                if 0 <= p[0] < W and 0 <= p[1] < H and p not in blocked and p not in d:
                    d[p] = d[(x, y)] + 1
                    q.append(p)
        out[side] = d
    _fields[map_path] = out
    return out


def zone(df, x, y, side):
    """own / mid / enemy for the team on `side`; 'offwalk' when the tile cannot be walked to from both spawns
    (dash or crystal islands); 'nomap' without the map file."""
    if df is None:
        return "nomap"
    me, them = df[side], df["B" if side == "A" else "A"]
    for dx, dy in ((0, 0),) + tuple(DIRS):
        p = (x + dx, y + dy)
        if p in me and p in them:
            r = me[p] / max(1, me[p] + them[p])
            return "own" if r < 0.4 else ("enemy" if r > 0.6 else "mid")
    return "offwalk"


def champ_name(n):
    """'Unknown champion (12)' -> 'Heart of Ruin', 'Unknown draft champion (3)' -> 'Cassi & Issac'; names pass through."""
    if n and n.startswith("Unknown") and n.endswith(")"):
        try:
            k = int(n[n.rindex("(") + 1:-1])
            return (DRAFT if "draft" in n else BODY)[k]
        except (ValueError, IndexError):
            pass
    return n


ENTITY = {1: "champion", 2: "camp", 6: "altar_lock"}  # entity_kind in cambc.h


def ctx(x):
    """An event entry's context; platform summaries write entity kinds as 'Unknown entity kind (2)' (= camp)."""
    c = x.get("context")
    if isinstance(c, str) and c.startswith("Unknown entity kind (") and c.endswith(")"):
        try:
            return ENTITY.get(int(c[c.rindex("(") + 1:-1]), c)
        except ValueError:
            return c
    return c


def phase(r):
    return "early" if r <= 500 else ("midgame" if r <= 1000 else "late")


def extract(stats_path, map_path=None):
    d = json.load(open(stats_path))
    m = d["match"]
    rounds = int(m.get("roundsCompleted") or m.get("roundsStarted") or 0)
    # the last timeline sample: the final round can be partial (a team reached 1000 mid-round), and its captures count
    last = max([t.get("sampleCount", rounds + 1) for t in d["championTimelines"][:1]] + [rounds + 1]) - 1
    tl = collections.defaultdict(dict)  # champion id -> metric -> Series
    team_of, name_of = {}, {}
    for t in d["championTimelines"]:
        cid = t["owner"]["id"]
        team_of[cid] = t["owner"]["team"][-1]
        name_of[cid] = champ_name(t["owner"].get("name", "?"))
        tl[cid][t["metric"]] = Series(t["runs"])
    sub = {t["owner"][-1]: Series(t["runs"]) for t in d["teamTimelines"] if t["metric"] == "submittedGems"}
    final = {x["team"][-1]: int(float(x["submittedGems"])) for x in d["teams"]}
    df = walk_fields(map_path)
    g = {"rounds": rounds, "outcome": {"teamA": "A", "teamB": "B"}.get(m.get("outcome"), "?"),
         "W": m.get("width"), "H": m.get("height"),
         "draft": {"A": [champ_name(x["champion"]) for x in d["roster"]["draft"] if x["team"] == "teamA"],
                   "B": [champ_name(x["champion"]) for x in d["roster"]["draft"] if x["team"] == "teamB"]}}
    g["ended"] = "race" if max(final.values() or [0]) >= 1000 else "limit"
    T = {s: collections.Counter() for s in "AB"}
    for s in "AB":
        T[s]["score"] = final.get(s, 0)

    # the race in tributed gems
    lead = [sub.get("A", Series([])).at(r) - sub.get("B", Series([])).at(r) for r in range(last + 1)]
    T["A"]["max_lead"] = max([0.0] + lead)
    T["B"]["max_lead"] = max([0.0] + [-x for x in lead])
    win = g["outcome"]
    if win in "AB":
        sign = 1 if win == "A" else -1
        k = last
        while k > 0 and lead[k - 1] * sign > 0:
            k -= 1
        T[win]["lead_for_good"] = k

    def team_at(s, metric, r):
        return sum(tl[c][metric].at(r) for c in tl if team_of[c] == s and metric in tl[c])

    for r in CPS + ("end",):
        rr = last if r == "end" else min(r, last)
        for s in "AB":
            T[s][f"sub_r{r}"] = sub[s].at(rr) if s in sub else team_at(s, "submittedGems", rr)
            T[s][f"col_r{r}"] = team_at(s, "collectedGems", rr)
            T[s][f"gold_r{r}"] = team_at(s, "earnedGold", rr)
    for s in "AB":
        T[s]["carried_end"] = team_at(s, "gems", last)
        T[s]["spent_gold"] = team_at(s, "spentGold", last)
        T[s]["gold_end"] = team_at(s, "gold", last)

    # events. The collection events carry no amounts, so each champion's per-round gain in collectedGems is split:
    # its loot that round is the carried gems of the champions it killed that round (the killer receives the whole
    # bag), capped at the gain; the rest is shared equally by its capture entries of that round.
    n_cap = collections.Counter()  # (champion, round) -> capture entries
    n_loot = collections.Counter()  # (champion, round) -> loot entries
    bag = {}  # (victim, round) -> carried gems lost
    victim_ctx = {}  # victim -> {round: True} for bags lost to champions

    def bag_of(cid, r):
        """Carried gems champion cid lost by dying in round r: its bag at the end of round r - 1, plus what it collected
        in round r before dying (a capture pays before the camps attack), minus what it tributed in round r, minus
        what it still carries at the end of the round (Ren keeps the bags of a mutual kill)."""
        s = tl.get(cid, {})
        if "gems" not in s or r <= 0:
            return 0.0
        dlt = lambda m: s[m].at(r) - s[m].at(r - 1) if m in s else 0.0  # noqa: E731
        return max(0.0, s["gems"].at(r - 1) + dlt("collectedGems") - dlt("submittedGems") - s["gems"].at(r))
    for e in d["events"]:
        cid = e["owner"].get("id") if isinstance(e["owner"], dict) else None
        for x in e["entries"]:
            r = x["timestamp"]["round"]
            if e["kind"] == "gemCollection":
                (n_cap if x.get("context") == "campGroup" else n_loot)[(cid, r)] += 1
            elif e["kind"] == "gemLoss":
                bag[(cid, r)] = bag_of(cid, r)
                if ctx(x) != "camp":  # camp kills destroy the bag; champion kills hand it over
                    victim_ctx.setdefault(cid, {})[r] = True

    def gain_of(cid, r):
        ser = tl.get(cid, {}).get("collectedGems")
        return max(0.0, ser.at(r) - ser.at(r - 1)) if ser and r > 0 else 0.0

    # a round's dropped bags go to that round's looters on the other team (the kill event does not always name
    # the champion that receives the gems, so match by team and round, not by killer)
    pool = collections.Counter()  # (victims' team, round) -> carried gems dropped to champions
    for (v, r), b in bag.items():
        if v in team_of and r in victim_ctx.get(v, {}):
            pool[(team_of[v], r)] += b
    loot_of = {}
    for (cid, r) in sorted(n_loot):
        if cid not in team_of:
            continue
        key = ("B" if team_of[cid] == "A" else "A", r)
        take = min(gain_of(cid, r), pool[key])
        pool[key] -= take
        loot_of[(cid, r)] = take

    def gains(cid, r):
        """(gems per capture entry, gems per loot entry) of champion cid in round r."""
        gain = gain_of(cid, r)
        loot = loot_of.get((cid, r), 0.0) if n_loot[(cid, r)] else 0.0
        if not n_cap[(cid, r)]:
            loot = gain  # nothing else to explain the gain
        return (gain - loot) / max(1, n_cap[(cid, r)]), loot / max(1, n_loot[(cid, r)])
    groups = collections.defaultdict(lambda: {"cap": collections.Counter(), "gems": collections.Counter(),
                                              "first": {}, "clear": collections.Counter()})
    clears, caps = [], []
    seen_cap = set()  # (round, group, team): the platform writes one capture entry per champion sharing the reward
    champ = {c: collections.Counter() for c in tl}
    for e in d["events"]:
        o = e["owner"] if isinstance(e["owner"], dict) else {}
        cid, s = o.get("id"), (o.get("team") or "?")[-1]
        if s not in "AB":
            continue
        other = "B" if s == "A" else "A"
        for x in e["entries"]:
            r = x["timestamp"]["round"]
            k = e["kind"]
            if k == "gemCollection":
                per_cap, per_loot = gains(cid, r)
                amt = per_cap if x.get("context") == "campGroup" else per_loot
                if x.get("context") == "campGroup":
                    gid = (x.get("target") or {}).get("id")
                    new = (r, gid, s) not in seen_cap
                    seen_cap.add((r, gid, s))
                    T[s]["cap_n"] += new
                    T[s]["cap_gems"] += amt
                    T[s][f"cap_{zone(df, x['x'], x['y'], s)}"] += amt
                    T[s][f"cap_{phase(r)}"] += amt
                    T[s]["first_cap"] = min(T[s]["first_cap"] or 10 ** 9, r)
                    grp = groups[gid]
                    grp["cap"][s] += new
                    grp["gems"][s] += amt
                    grp["first"][s] = min(grp["first"].get(s, 10 ** 9), r)
                    grp.setdefault("x", x["x"])
                    grp.setdefault("y", x["y"])
                    if new:
                        caps.append((r, gid, s))
                    champ[cid]["cap_gems"] += amt
                else:
                    T[s]["loot_gems"] += amt
            elif k == "gemLoss":
                amt = bag_of(cid, r)
                T[s]["bag_lost_camp" if ctx(x) == "camp" else "bag_lost_champ"] += amt
                champ[cid]["bag_lost"] += amt
            elif k == "death":
                T[s]["deaths"] += 1
                T[s][f"deaths_{zone(df, x['x'], x['y'], s)}"] += 1
                T[s][f"deaths_{phase(r)}"] += 1
                T[s]["dead_rounds"] += min(DEAD_ROUNDS, max(0, rounds - r))
                champ[cid]["deaths"] += 1
                if ctx(x) == "camp":
                    T[s]["deaths_camp"] += 1
                    champ[cid]["deaths_camp"] += 1
            elif k == "kill":
                T[s]["kills"] += 1
                champ[cid]["kills"] += 1
            elif k == "gemSubmission":
                v = float(x.get("value") or 0)
                T[s]["sub_n"] += 1
                T[s]["sub_gems"] += v
                T[s]["first_sub"] = min(T[s]["first_sub"] or 10 ** 9, r)
            elif k == "campClear":
                gid = (x.get("target") or {}).get("id")
                T[s]["clears"] += 1
                groups[gid]["clear"][s] += 1
                clears.append((r, gid, s))
            elif k == "wardPlacement":
                T[s]["wards"] += 1
            elif k == "buyItem":
                T[s]["first_item"] = min(T[s]["first_item"] or 10 ** 9, r)
                T[s]["items"] += 1
            elif k == "buyConsumable":
                nm = ((x.get("target") or {}).get("name") or "").lower()
                if nm.startswith("unknown consumable ("):  # platform summaries: engine consumable 2 = lock, 0 = crystal
                    nm = {"2": "altar lock", "0": "teleport crystal"}.get(nm[nm.rindex("(") + 1:-1], nm)
                T[s]["locks" if "lock" in nm else "crystals"] += 1
            elif k == "fuelExhausted":
                T[s]["fuel"] += 1
            elif k == "botFault":
                T[s]["faults"] += 1
    for s in "AB":
        T[s]["faults"] = max(T[s]["faults"], int(d.get("diagnostics", {}).get("botFaults", {}).get("team" + s, 0)))
    # clears whose capture went to the other team (the enemy stood in the region after we killed the camps)
    caps.sort()
    for r, gid, s in clears:
        nxt = next((c for c in caps if c[1] == gid and r <= c[0] <= r + 20), None)
        if nxt and nxt[2] != s:
            T[s]["stolen"] += 1
            T[nxt[2]]["steals"] += 1
    n_champ = {s: sum(1 for c in team_of if team_of[c] == s) for s in "AB"}
    for s in "AB":
        t = T[s]
        t["dead_share"] = t["dead_rounds"] / max(1, n_champ[s] * rounds)
        t["sub_mean"] = t["sub_gems"] / t["sub_n"] if t["sub_n"] else 0.0
        t["wards_100"] = 100.0 * t["wards"] / max(1, rounds)
        t["groups_capped"] = sum(1 for gr in groups.values() if gr["cap"][s])
        for k in ("first_cap", "first_sub", "first_item"):
            if not t[k]:
                t[k] = None
    # self-check against the statistics' own totals: an upstream format change shows here, not as wrong numbers
    chk, met = [], {s: collections.Counter() for s in "AB"}
    for c in d.get("champions", []):
        if (c.get("team") or "?")[-1] in met:
            for k in ("kills", "deaths", "collectedGems"):
                met[c["team"][-1]][k] += int(float((c.get("metrics") or {}).get(k) or 0))
    for s in "AB":
        for k, v in (("kills", T[s]["kills"]), ("deaths", T[s]["deaths"]),
                     ("collectedGems", T[s]["cap_gems"] + T[s]["loot_gems"])):
            if d.get("champions") and abs(v - met[s][k]) > 1:
                chk.append(f"{s} {k} {v:g} vs statistics {met[s][k]}")
        if T[s]["sub_gems"] != final.get(s, 0):
            chk.append(f"{s} tributes {T[s]['sub_gems']:g} vs score {final.get(s, 0)}")
    g["check"] = chk
    # gem and gold amounts to 0.1; dead_share is a fraction (0.0-1.0) and keeps 4 decimals
    g["A"] = {k: (round(v, 4 if k == "dead_share" else 1) if isinstance(v, float) else v) for k, v in T["A"].items()}
    g["B"] = {k: (round(v, 4 if k == "dead_share" else 1) if isinstance(v, float) else v) for k, v in T["B"].items()}
    g["groups"] = {str(gid): {"x": gr.get("x"), "y": gr.get("y"),
                              "zone_A": zone(df, gr["x"], gr["y"], "A") if "x" in gr else "nomap",
                              "cap_A": gr["cap"]["A"], "cap_B": gr["cap"]["B"],
                              "clear_A": gr["clear"]["A"], "clear_B": gr["clear"]["B"],
                              "gems_A": round(gr["gems"]["A"], 1), "gems_B": round(gr["gems"]["B"], 1),
                              "first_A": gr["first"].get("A"), "first_B": gr["first"].get("B")}
                   for gid, gr in groups.items()}
    g["champs"] = [{"team": team_of[c], "name": name_of[c], **{k: round(v, 1) for k, v in champ[c].items()},
                    "collected": tl[c]["collectedGems"].at(last) if "collectedGems" in tl[c] else 0,
                    "tributed": tl[c]["submittedGems"].at(last) if "submittedGems" in tl[c] else 0}
                   for c in sorted(tl)]
    return g


def _job(args):
    gid, st, mp = args
    try:
        return gid, extract(st, mp)
    except Exception as e:  # noqa: BLE001 (one bad file must not lose the run)
        return gid, {"error": str(e)[:200]}


def extract_run(rundir, jobs=8):
    """games_rich.jsonl for an abl.sh run dir whose st/ still exists: one line {id, a, b, map, ...features}."""
    man = open(os.path.join(rundir, "manifest.txt")).read().split("\n")
    rows = []
    for line in open(os.path.join(rundir, "games.list")):
        p = line.split()
        if len(p) < 4:
            continue
        st = os.path.join(rundir, "st", p[0] + ".json")
        if os.path.exists(st):
            f = man[int(p[0]) - 1].split()
            rows.append((p, st, f[2] if len(f) > 2 else None))
    work = [(p[0], st, mp) for p, st, mp in rows]
    if jobs > 1 and len(work) > 8:
        import multiprocessing
        # fork, not Python 3.14's default forkserver: forkserver re-imports the caller's main module in every
        # worker, and ablsum.py is a script whose top level rewrites the run dir
        with multiprocessing.get_context("fork").Pool(min(jobs, len(work))) as pool:
            res = dict(pool.map(_job, work))
    else:
        res = dict(map(_job, work))
    with open(os.path.join(rundir, "games_rich.jsonl.tmp"), "w") as f:
        for p, st, mp in rows:
            f.write(json.dumps(dict(id=p[0], a=p[1], b=p[2], map=p[3], **res[p[0]]), separators=(",", ":")) + "\n")
    os.replace(os.path.join(rundir, "games_rich.jsonl.tmp"), os.path.join(rundir, "games_rich.jsonl"))
    return len(rows)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--run":
        jobs = int(a[a.index("--jobs") + 1]) if "--jobs" in a else 8
        print(f"{extract_run(a[1], jobs)} games -> {os.path.join(a[1], 'games_rich.jsonl')}")
    elif a:
        print(json.dumps(extract(a[0], a[1] if len(a) > 1 else None), indent=1))
    else:
        print(__doc__)
