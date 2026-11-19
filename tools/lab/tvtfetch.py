#!/usr/bin/env python3
"""tvtfetch: ranked games between the top teams themselves (not v us) on the current engine, for the analysts (owner 8 Nov, via the
Coordinator; replaces the deleted scout2/py/tvtfetch.sh).
usage: python3 -I tools/lab/tvtfetch.py list [--top 10] [--engine 3.0.0] [--max-pages 40]   find the games -> manifest.tsv
       python3 -I tools/lab/tvtfetch.py fetch                                               download replays + statistics (plat_fetch, platlock)
       python3 -I tools/lab/tvtfetch.py stats                                               per-team columns from the statistics -> manifest.tsv
Out (/data/zw4424/st/tvt): manifest.tsv (match, created, map, version, team_a, id_a, team_b, id_b, winner, then per team: fuel_cuts,
faults, gems tributed, kills, deaths), matches.txt (readmany's live-set format: id map seat result, seat 'a', result from team a's view),
set/x_ID/ (replay.repl26a and team logs), set/ID.json (statistics). Top = the ladder's top N minus us. Engine: both teams' engineVersion.
Platform calls only through tools/lab/platlock.sh (plat_fetch.py does the downloads, one at a time machine-wide)."""
import json
import os
import subprocess
import sys

REPO = "/homes/zw4424/cambc"
CLI = "/data/zw4424/cambc400/bin/cambc400"
OUT = "/data/zw4424/st/tvt"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
from teams import US_ID  # noqa: E402

COLS = ["match", "created", "map", "version", "team_a", "id_a", "team_b", "id_b", "winner"]
PER = ["fuel_cuts", "faults", "gems_tributed", "kills", "deaths"]


def plat(args):
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/platlock.sh"), CLI] + args, capture_output=True, text=True, timeout=600)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else None


def top_ids(n):
    lad = json.load(open("/data/zw4424/st/teams/ladder.json"))
    t = lad.get("teams", lad)
    return {x["teamId"]: x["name"] for x in sorted(t, key=lambda x: x.get("rank", 999)) if x["teamId"] != US_ID}.__class__(
        list({x["teamId"]: x["name"] for x in sorted(t, key=lambda x: x.get("rank", 999)) if x["teamId"] != US_ID}.items())[:n])


def cmd_list(a):
    n = int(a[a.index("--top") + 1]) if "--top" in a else 10
    eng = a[a.index("--engine") + 1] if "--engine" in a else "3.0.0"
    pages = int(a[a.index("--max-pages") + 1]) if "--max-pages" in a else 40
    top = top_ids(n)
    os.makedirs(OUT, exist_ok=True)
    sp = os.path.join(OUT, "list_state.json")  # resume: teams already paged, and the rows found so far
    st = json.load(open(sp)) if os.path.exists(sp) else dict(done=[], rows={})
    rows = st["rows"]
    for tid, name in top.items():
        if tid in st["done"]:
            continue
        cur, seen_old = None, False
        for _ in range(pages):
            d = plat(["matches", "list", "--team", tid, "--kind", "ranked", "--limit", "100", "--json"] + (["--cursor", cur] if cur else []))
            if not d:
                print(f"tvtfetch: list failed for {name}", file=sys.stderr)
                break
            for m in d.get("matches", []):
                ts = m.get("teams", [])
                if len(ts) != 2 or m.get("status") != "finished":
                    continue
                if any(t.get("engineVersion") != eng for t in ts):
                    seen_old = True
                    continue
                if not all(t.get("teamId") in top for t in ts):
                    continue
                a_, b_ = sorted(ts, key=lambda t: t.get("side"))
                w = a_["name"] if a_.get("result") == "win" else b_["name"] if b_.get("result") == "win" else "draw"
                rows[m["matchId"]] = [m["matchId"], m.get("createdAt", ""), m.get("map", ""), eng, a_["name"], a_["teamId"], b_["name"], b_["teamId"], w]
            cur = d.get("nextCursor")
            if not cur or seen_old:  # newest first: once an older engine shows up, the rest of this team's list is older still
                break
        print(f"{name}: {sum(1 for r in rows.values() if tid in (r[5], r[7]))} games so far", flush=True)
        st["done"].append(tid)
        json.dump(st, open(sp + ".new", "w"))
        os.replace(sp + ".new", sp)
    with open(os.path.join(OUT, "manifest.tsv"), "w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in sorted(rows.values(), key=lambda r: r[1]):
            f.write("\t".join(r) + "\n")
    print(f"tvtfetch: {len(rows)} games between the top {n} (minus us) on engine {eng} -> {OUT}/manifest.tsv")


def read_manifest():
    L = open(os.path.join(OUT, "manifest.tsv")).read().splitlines()
    hdr = L[0].split("\t")
    return hdr, [dict(zip(hdr, x.split("\t"))) for x in L[1:]]


def cmd_fetch(a):
    """9 Nov: about 15,000 top-v-top games exist on 3.0.0, and a replay download keeps 15 s from the last (the owner's visualiser rule):
    statistics for the newest --stats N games (default 2000, ~3 s each), replays for the newest --per-pair K games of each pair (default 20)."""
    hdr, rows = read_manifest()
    nst = int(a[a.index("--stats") + 1]) if "--stats" in a else 2000
    kpp = int(a[a.index("--per-pair") + 1]) if "--per-pair" in a else 20
    new = sorted(rows, key=lambda r: r["created"], reverse=True)
    os.makedirs(os.path.join(OUT, "set"), exist_ok=True)
    got = 0
    for r in new[:nst]:
        p = os.path.join(OUT, "set", r["match"] + ".json")
        if os.path.exists(p):
            continue
        q = subprocess.run(["sh", os.path.join(REPO, "tools/lab/platlock.sh"), CLI, "matches", "summary", r["match"], "--json", "-o", p + ".part"],
                           capture_output=True, text=True, timeout=600)
        if q.returncode == 0 and os.path.exists(p + ".part"):
            os.replace(p + ".part", p)
            got += 1
        if got and got % 100 == 0:
            print(f"tvtfetch: statistics {got}", flush=True)
    print(f"tvtfetch: statistics for {got} more games (newest {nst})", flush=True)
    per, pick = {}, []
    only = set(a[a.index("--pairs-with") + 1].split(",")) if "--pairs-with" in a else None  # 9 Nov (Deep): deeper sets for pairs with these team ids
    for r in new:
        k = tuple(sorted((r["id_a"], r["id_b"])))
        if only and not (only & set(k)):
            continue
        if per.get(k, 0) < kpp:
            per[k] = per.get(k, 0) + 1
            pick.append(r)
    ids = os.path.join(OUT, "ids.txt")
    open(ids, "w").write("\n".join(r["match"] for r in pick) + "\n")
    env = dict(os.environ, CAMBC_WHO="tvtfetch")
    print(f"tvtfetch: replays for {len(pick)} games ({kpp} newest per pair, {len(per)} pairs)", flush=True)
    subprocess.run(["sh", os.path.join(REPO, "tools/lab/plat_fetch.sh"), ids, "--dest", os.path.join(OUT, "set")], env=env)
    with open(os.path.join(OUT, "set", "matches.txt"), "w") as f:
        for r in rows:
            res = "win" if r["winner"] == r["team_a"] else "loss" if r["winner"] == r["team_b"] else "draw"
            f.write(f"{r['match']} {r['map']} a {res}\n")


def team_stats(d, team):
    s = dict(fuel_cuts=0, faults=0, gems_tributed=0, kills=0, deaths=0)
    for e in d.get("events", []):
        if e.get("kind") == "fuelExhausted" and (e.get("owner") or {}).get("team") == team:
            s["fuel_cuts"] += len(e.get("entries", []))
    s["faults"] = int((d.get("diagnostics", {}).get("botFaults") or {}).get(team, 0) or 0)
    for t in d.get("teams", []):
        if t.get("team") == team:
            s["gems_tributed"] = int(t.get("submittedGems", 0) or 0)
    for c in d.get("champions", []):
        if c.get("team") == team:
            m = c.get("metrics", {})
            s["kills"] += int(m.get("kills", 0) or 0)
            s["deaths"] += int(m.get("deaths", 0) or 0)
    return s


def find_json(mid):
    for p in (os.path.join(OUT, "set", mid + ".json"), os.path.join(OUT, mid + ".json")):
        if os.path.exists(p):
            return p
    return None


def cmd_stats(a):
    hdr, rows = read_manifest()
    base = [c for c in hdr if not c.endswith(("_a", "_b")) or c in ("team_a", "id_a", "team_b", "id_b")][:len(COLS)]
    out = []
    for r in rows:
        p = find_json(r["match"])
        if p:
            d = json.load(open(p))
            for side, team in (("a", "teamA"), ("b", "teamB")):
                for k, v in team_stats(d, team).items():
                    r[f"{k}_{side}"] = str(v)
        out.append(r)
    cols = COLS + [f"{k}_{s}" for s in ("a", "b") for k in PER]
    with open(os.path.join(OUT, "manifest.tsv.new"), "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in out:
            f.write("\t".join(r.get(c, "") for c in cols) + "\n")
    os.replace(os.path.join(OUT, "manifest.tsv.new"), os.path.join(OUT, "manifest.tsv"))
    have = sum(1 for r in out if r.get("fuel_cuts_a", "") != "")
    print(f"tvtfetch: stats for {have} of {len(out)} games -> {OUT}/manifest.tsv")


def main():
    a = sys.argv[1:]
    {"list": cmd_list, "fetch": cmd_fetch, "stats": cmd_stats}.get(a[0] if a else "", lambda _: print(__doc__))(a[1:])


if __name__ == "__main__":
    main()
