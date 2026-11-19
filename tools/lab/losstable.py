#!/usr/bin/env python3
"""losstable: every loss in one table, refreshed continuously, so analysts see patterns across ALL losses, not only the walked ones
(owner 9 Nov: "make sure the analysers can analyse ... all our losses", "make sure it is continuous"). Tool Builder.

Sources: critgame's triage table (/data/USER/st/crit/triage.jsonl: every ranked and unranked loss critgame has read, any version, with its
fall measurements and cause kind) and the climb lanes' game lists (/data/USER/st/climb_*/games.tsv: lane, version, foe, map, side, result).
Per loss: lane (top3 / side lanes / ranked / unranked), version, foe, map, our side, and a cause tag from the triage measurements:
  collapse-early  the worst fall began before round 300       blown-lead   we led by 300+ and still lost
  bag-death       a carried bag of 200+ lost inside the fall   fault        a bot fault or two fuel cut-offs before the fall
  foe-capture / foe-tribute / ...  critgame's own kind of the decisive swing (mkind)        untriaged   in a lane list, not read yet
Each pass also fetches the replays of the highest-severity losses that have none on disk (into /data/USER/plat/crit_auto, at most
LT_FETCH per pass, through plat_fetch: shared, rate-limited) and writes the backlog numbers healthwatch alarms on.
usage: python3 -I tools/lab/losstable.py [--loop [--every 600]] [--no-fetch]
Out: condor-work/reports/live/all_losses.md (summary: by lane x version, by cause, by map, the backlog, the top unwalked losses),
     /data/USER/st/crit/all_losses.tsv (one row per loss), /data/USER/st/crit/losstable.json (backlog stats for healthwatch)."""
import collections
import glob
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
CRIT = "/data/USER/st/crit"
OUT_MD = "/homes/USER/condor-work/reports/live/all_losses.md"
OUT_TSV = f"{CRIT}/all_losses.tsv"
STATS = f"{CRIT}/losstable.json"
FETCH_N = int(os.environ.get("LT_FETCH", "20"))
sys.path.insert(0, os.path.join(REPO, "tools/lab"))


def have_replay(mid):
    return bool(glob.glob(f"/data/USER/plat/*/x_{mid}*/replay.repl26a"))


def lanes():
    """match id -> (lane, version, foe, map, side, result) from the climb lanes' game lists"""
    out = {}
    for f in glob.glob("/data/USER/st/climb*/games.tsv"):
        lane = os.path.basename(os.path.dirname(f)).replace("climb_", "").replace("climb", "main")
        for ln in open(f, errors="replace"):
            p = ln.rstrip("\n").split("\t")
            if len(p) >= 7:
                out[p[3]] = (lane, p[0], p[1], p[4], p[5], p[6])
    return out


def cause(t):
    tags = []
    # 11 Nov (Coordinator: two v717 SBG losses tagged 'fault' were fuel cut-offs): 'fault' = a bot error (replay end 2) only; fuel cut-offs
    # (end 1) tag 'fuelcut'. Older triage rows carry only 'faults' (end 1 or 2), so they read as fuelcut unless 'errors' says otherwise.
    if t.get("errors", 0) > 0:
        tags.append("fault")
    elif t.get("fuelcuts", t.get("faults", 0)) > 0:
        tags.append("fuelcut")
    if t.get("worst_r", 9999) < 300 and t.get("worst", 0) <= -150:
        tags.append("collapse-early")
    if t.get("lead", 0) >= 300:
        tags.append("blown-lead")
    if t.get("bag", 0) >= 200:
        tags.append("bag-death")
    if t.get("mkind"):
        tags.append(str(t["mkind"]).replace(" ", "-"))
    return ",".join(tags) or "unclassified"


def open_unclaimed():
    """(unowned count, oldest unowned age h, claimed-but-untouched count) of open flagged games. 9 Nov 20:08Z (Econ via Coordinator): this
    counted every game whose windows were all OPEN, Combat's and Deep's claimed games included (64 at 19:59 when only 1 had no owner).
    Unowned: no owner in meta.json. Claimed but untouched: an owner, every window still OPEN, claimed more than LT_STALE_H (4) h ago."""
    try:
        import critgame as C
        import datetime
        n, oldest, stale = 0, 0.0, []
        lim = float(os.environ.get("LT_STALE_H", "4")) * 3600
        vmin = int(os.environ.get("LT_OPEN_VMIN", "641"))  # 10 Nov (Econ via Coordinator): pre-v641 history and Supaswag games are left alone by rule
        for _, _, m, d, st in C.open_games():
            age = time.time() - os.path.getmtime(f"{d}/meta.json")
            try:
                ver = int(str(m.get("version", "")).lstrip("v").split("-")[0])
            except ValueError:
                ver = 0
            held = "supaswag" in str(m.get("why", "")).lower() or os.path.exists(f"{d}/STAY_OPEN")
            if not m.get("owner") and (ver < vmin or held):
                continue  # not work: the unowned count shows only current games someone should take
            if not m.get("owner"):
                n += 1
                oldest = max(oldest, age / 3600)
            elif all(x == "OPEN" for x in st) and "supaswag" not in str(m.get("why", "")).lower() and not os.path.exists(f"{d}/STAY_OPEN"):
                # 9 Nov (Coordinator): Supaswag losses stay OPEN on purpose (owner: no batch close until a fix ships); a STAY_OPEN file does the same
                ot = m.get("owner_t")
                try:
                    ts = float(ot) if isinstance(ot, (int, float)) else datetime.datetime.fromisoformat(str(ot).replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    ts = None
                if ts is not None and time.time() - ts > lim:
                    stale.append((m.get("owner"), m.get("spec"), round((time.time() - ts) / 3600, 1)))
        return n, round(oldest, 1), stale
    except Exception:  # noqa: BLE001  the table must not die on critgame's internals
        return None, None, None


def one_pass(fetch=True):
    tri = {}
    try:
        for ln in open(f"{CRIT}/triage.jsonl", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("result") == "loss" and d.get("id"):
                tri[d["id"]] = d
    except OSError:
        pass
    ln_ = lanes()
    rows = []
    for mid, t in tri.items():
        lane = ln_[mid][0] if mid in ln_ else t.get("kind", "?")
        rows.append(dict(id=mid, lane=lane, version=t.get("version", "?"), foe=t.get("foe", "?"), map=t.get("map", "?"),
                         side=ln_[mid][4] if mid in ln_ else "", cause=cause(t), sev=t.get("sev", 0), worst=t.get("worst", ""),
                         worst_r=t.get("worst_r", ""), lead=t.get("lead", ""), bag=t.get("bag", ""), t=t.get("t", ""), triaged=1))
    untri = [(mid, v) for mid, v in ln_.items() if v[5] not in ("win", "draw") and mid not in tri]
    for mid, (lane, ver, foe, mp, side, _r) in untri:
        rows.append(dict(id=mid, lane=lane, version=ver, foe=foe, map=mp, side=side, cause="untriaged", sev=0, worst="", worst_r="", lead="",
                         bag="", t="", triaged=0))
    # missing replays: highest severity first, at most FETCH_N a pass
    # 10 Nov (Coordinator + Planner, owner priority: flaws in losses to lower-ranked teams): losses to teams other than the top 3 first,
    # then the newest version, then severity
    top3 = ("mite", "sbg", "fish")
    def _vnum(v):
        m = re.search(r"(\d+)", str(v or ""))
        return int(m.group(1)) if m else 0
    # 13 Nov (TB; owner 'delete old replays and bots': plat sets before v850 were deleted to free /data): losses of versions under
    # LT_MIN_V (850) are neither re-fetched nor counted as missing, else the back-fill re-downloads what was deleted on purpose
    minv = int(os.environ.get("LT_MIN_V", "850"))
    missing = sorted((r for r in rows if r["triaged"] and _vnum(r["version"]) >= minv and not have_replay(r["id"])),
                     key=lambda r: (any(t in str(r["foe"]).lower() for t in top3), -_vnum(r["version"]), -float(r["sev"] or 0)))
    fetched = 0
    # 9 Nov 19:58Z (Coordinator: all_losses.md 1 h old): the fetch ran BEFORE the table was written, and since back-fill downloads yield to
    # critgame (PLAT_HI_DEFER 900) a pass waited hours. The fetch now runs DETACHED (one at a time: flock), the table is written every pass.
    if fetch and missing:
        ids = [r["id"] for r in missing[:FETCH_N]]
        lst = f"{CRIT}/.lt_fetch.txt"
        lk = f"{CRIT}/.lt_fetch.lock"
        if subprocess.run(["flock", "-n", lk, "true"], capture_output=True).returncode == 0:  # no fetch running
            open(lst, "w").write("\n".join(ids) + "\n")
            subprocess.Popen(["flock", "-n", lk, "timeout", "7200", "sh", os.path.join(REPO, "tools/lab/plat_fetch.sh"), lst, "--dest",
                              "/data/USER/plat/crit_auto"], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, CAMBC_WHO="losstable"), start_new_session=True)
    for r in rows:
        r["replay"] = int(have_replay(r["id"])) if r["triaged"] else 0
    cols = ["id", "lane", "version", "foe", "map", "side", "cause", "sev", "worst", "worst_r", "lead", "bag", "replay", "t"]
    with open(OUT_TSV + ".new", "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in sorted(rows, key=lambda r: (r["version"], r["lane"], -float(r["sev"] or 0))):
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    os.replace(OUT_TSV + ".new", OUT_TSV)
    unc, oldest, stale_l = open_unclaimed()
    stale = len(stale_l) if stale_l is not None else None
    st = dict(t=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), losses=len(rows), triaged=len(tri), untriaged=len(untri),
              no_replay=len(missing) - fetched, fetched=fetched, open_unclaimed=unc, oldest_unclaimed_h=oldest, claimed_stale=stale)
    json.dump(st, open(STATS + ".new", "w"))
    os.replace(STATS + ".new", STATS)
    # the summary
    vers = sorted({r["version"] for r in rows}, key=lambda v: int(v[1:]) if v[1:].isdigit() else 0)[-6:]
    by = collections.Counter((r["lane"], r["version"]) for r in rows)
    lanes_ = sorted({r["lane"] for r in rows})
    L = [f"# All losses ({st['t']}): {len(rows)} losses, {len(tri)} triaged, {len(untri)} untriaged, {st['no_replay']} without a replay "
         f"({fetched} fetched this pass); flagged with no owner: {unc} (oldest {oldest} h); claimed but untouched > 4 h: {stale}",
         "Refreshed every 10 min by tools/lab/losstable.py (unit nova-losstable). Rows: /data/USER/st/crit/all_losses.tsv. Causes from "
         "critgame's triage measurements; 'untriaged' = in a climb lane's list, not read yet.", "",
         "## Losses by lane and version (newest 6 versions)", "", "| lane | " + " | ".join(vers) + " |", "|---|" + "---|" * len(vers)]
    for ln in lanes_:
        L.append(f"| {ln} | " + " | ".join(str(by.get((ln, v), 0)) for v in vers) + " |")
    if stale_l:
        L += ["", "## Claimed but untouched > 4 h (Supaswag / STAY_OPEN games left out), by owner", ""]
        for ow in sorted({o for o, _, _ in stale_l}):
            L.append(f"- {ow}: " + ", ".join(f"{s} ({h} h)" for o, s, h in sorted(stale_l, key=lambda x: -x[2]) if o == ow))
    L += ["", "## Causes (newest 3 versions)", ""]
    recent = [r for r in rows if r["version"] in vers[-3:]]
    cc = collections.Counter(c for r in recent for c in r["cause"].split(","))
    L += [f"- {c}: {n}" for c, n in cc.most_common(12)]
    L += ["", "## Maps with the most losses (newest 3 versions)", ""]
    mc = collections.Counter(r["map"] for r in recent)
    L += [f"- {m}: {n}" for m, n in mc.most_common(12)]
    L += ["", "## Highest-severity losses of the newest version (walk these first)", "",
          "| id | lane | foe | map | cause | sev | worst@r | replay |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in rows if r["version"] == (vers[-1] if vers else "")), key=lambda r: -float(r["sev"] or 0))[:15]:
        L.append(f"| {r['id']} | {r['lane']} | {r['foe']} | {r['map']} | {r['cause']} | {r['sev']} | {r['worst']}@{r['worst_r']} | "
                 f"{'yes' if r['replay'] else 'no'} |")
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD + ".new", "w").write("\n".join(L) + "\n")
    os.replace(OUT_MD + ".new", OUT_MD)
    return st


def missing(a):
    """10 Nov (Coordinator): `losstable.py missing [--all] [--from 704]`: triaged losses with no replay on disk, lower-ranked foes only (not
    Mite/SBG/Fish) unless --all, versions >= --from (default 704); one line each: id version foe map. Reads the table the loop writes."""
    import csv
    vmin = int(a[a.index("--from") + 1]) if "--from" in a else 704
    rows = list(csv.DictReader(open(OUT_TSV), delimiter="\t"))
    out = []
    for r in rows:
        if r.get("cause") == "untriaged" or r.get("replay") != "0":
            continue
        m = re.search(r"(\d+)", r.get("version", ""))
        if not m or int(m.group(1)) < vmin:
            continue
        if "--all" not in a and any(t in r.get("foe", "").lower() for t in ("mite", "sbg", "fish")):
            continue
        out.append(f"{r['id']} {r['version']} {r['foe']} {r['map']}")
    print(f"{len(out)} triaged losses without a replay ({'all foes' if '--all' in a else 'lower-ranked foes'}, v{vmin}+):")
    print("\n".join(out))


def main():
    a = sys.argv[1:]
    if a[:1] == ["missing"]:
        return missing(a)
    fetch = "--no-fetch" not in a
    if "--loop" not in a:
        print(json.dumps(one_pass(fetch)))
        return 0
    every = int(a[a.index("--every") + 1]) if "--every" in a else 600
    while True:
        try:
            one_pass(fetch)
        except Exception as e:  # noqa: BLE001  keep the loop alive
            print(f"losstable: pass failed: {e!r}"[:300], flush=True)
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
