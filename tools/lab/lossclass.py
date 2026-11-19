#!/usr/bin/env python3
"""lossclass: automatic class screen for a lost game, so only NEW kinds of loss reach an analyser (Tool Builder, 11 Nov; brief: 6
batches of top-3 losses, ~24 Mite climb losses, each cost an analyser round and closed as already-known classes).

usage: python3 -I tools/lab/lossclass.py MATCH_ID_OR_REPLAY... [--us A|B]      one TSV row per game (header first)
       python3 -I tools/lab/lossclass.py --self-test                          re-classify Combat's sbg739 screen rows, report agreement
       python3 -I tools/lab/lossclass.py --annotate MATCH_ID --us A|B [--foe NAME] [--dry]
           (the intake hook, ladderclimb.flag): write the class into that game's critgame record /data/zw4424/st/crit/<id>/meta.json
           (key "lossclass") and, for class pace / heavy / midgem, close it there as auto-closed-to-class (status and the open cap skip
           it). Best-effort: any error writes nothing and the game stays open (needs an analyst), exit 0 either way.

Seat, map and foe come from tools/lab/gameindex.tsv (via `gameindex.py lookup`) when an id is given without --us. The replay is
read from disk only (replay.load: the decoded copy in /data/zw4424/rdec_cache when there is one, else one rdec decode); this tool
never downloads. At most 2 decodes run at once (flock slots /data/zw4424/st/lossclass/slot{0,1}.lock), under nice 10.

Columns: id map foe us result gold_us_r300 gold_them_r300 gold_behind_r300 (ours - theirs, earned gold) gold_ratio_r300
  kills_us kills_them deaths_us deaths_them (replay stats, per champion summed, as Combat's screen) gems_us_r600 gems_them_r600
  (capture gems to r600) heavy_gap_r600 mid_gap_r600 (theirs - ours on heavy groups / on mid-zone groups) heavy_ge heavy_ge2
  (tools/lab/mapclass.py on <map>.map26a from maps/, cambc500/proj/maps or ablproj_4.0.0/maps; from the replay's groups when the map file is missing) class needs_analyst why

Class rules, first match wins (a loss only; a win or draw is class 'win', needs_analyst false):
  pace       gold_ratio_r300 < 1.00. Combat's screen (/data/zw4424/st/combat_py/sbg739_screen.py -> sbg739_mine_screen.tsv, board
             11 Nov 09:10Z): the 20 v739 SBG losses with our earned gold behind at r300 (ratio .00-.97) were class-closed as
             economy / Prism snowball without a walk; the 4 at >= 1.10 were walked. The cut sits between .97 and 1.10, at 1.00 (=
             gold_behind_r300 < 0). Planner's Mite pace census (board 10:28Z) supports it: r300 gold us-Mite in losses -472 [-607,-343],
             in wins +148.
  fight-lost (only when not behind in gold at r300; pace first: Combat closed 15 behind-on-gold games with lopsided kills as pace, kills follow pace) kills_them >= kills_us + FIGHT_MARGIN (5) and kills_them >= 2 x kills_us.
             Not from Combat's screen (its 4 walked games read 3-14, 3-6, 2-3, 1-3; only 00quarry's 3-14 was a fight carry): our cut,
             chosen so a single trade does not count. Needs an analyst.
  heavy      heavy_gap_r600 >= GAP_MIN (100 gems) and (map heavy_ge2 >= .50 or heavy_gap_r600 >= half the total gem gap). HEAVY_SHARE
             class (owner/Econ 10 Nov: elk/golem gem share >= .5, no monolith; mapclass heavy_ge2 'class >= .50'), Econ's class table
             (board 10:43Z: 'GEM-GAP heavy (HEAVY/HTO family)'). Closed family: Econ HEAVY/HTO.
  midgem     mid_gap_r600 >= GAP_MIN and mid_gap_r600 >= half the total gem gap. Econ's 'GEM-GAP middle (MIDGEM)' class and the
             intake's r600 home/mid split (econ_work_1109/intake_*/split.out). Mid = replay.Game.zone of the group centre from our
             side (walk-distance share .4-.6). Closed family: MIDGEM.
  other      anything else (led then lost, close race, new shape). Needs an analyst.
  GAP_MIN 100 gems: about the mean gem deficit to r400 in Mite losses (Econ 10:41Z: 271 v 383, -114 +- 23).
needs_analyst: true for fight-lost and other (and when the class cannot be computed)."""
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

FIGHT_MARGIN = 5
GAP_MIN = 100
PACE_RATIO = 1.00
CLOSED = ("pace", "heavy", "midgem")
SLOTS = "/data/zw4424/st/lossclass"
CRIT = os.environ.get("CRIT_ROOT", "/data/zw4424/st/crit")
SCREEN = "/data/zw4424/st/combat_py/sbg739_mine_screen.tsv"
ECONCLOSE = "/data/zw4424/st/combat_py/sbg739_econclose.txt"
MAPDIRS = (f"{REPO}/maps", "/data/zw4424/cambc500/proj/maps", "/data/zw4424/ablproj_4.0.0/maps")
COLS = ("id map foe us result gold_us_r300 gold_them_r300 gold_behind_r300 gold_ratio_r300 kills_us kills_them deaths_us deaths_them "
        "gems_us_r600 gems_them_r600 heavy_gap_r600 mid_gap_r600 heavy_ge heavy_ge2 class needs_analyst why").split()


@contextlib.contextmanager
def slot(wait=600):
    """one of 2 decode slots (flock); after `wait` s without one, go on anyway (a stuck holder must not block the intake)"""
    fh = None
    try:
        os.makedirs(SLOTS, exist_ok=True)
        t0 = time.time()
        while fh is None and time.time() - t0 < wait:
            for i in (0, 1):
                f = open(f"{SLOTS}/slot{i}.lock", "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fh = f
                    break
                except OSError:
                    f.close()
            if fh is None:
                time.sleep(2)
    except OSError:
        pass
    try:
        yield
    finally:
        if fh:
            fh.close()


def lookup(mid):
    """gameindex row -> dict(version, id, seat, result, path, map, foe) or None"""
    p = subprocess.run([sys.executable, "-I", f"{HERE}/gameindex.py", "lookup", mid], capture_output=True, text=True, timeout=120)
    for ln in p.stdout.splitlines():
        f = ln.split("\t")
        if len(f) >= 7 and f[0].startswith("v") and f[1] == mid:
            return dict(version=f[0], id=f[1], seat=f[2].upper(), result=f[3], path=f[4], map=f[5], foe=f[6])
    return None


def heavy_shares(g, mp):
    """(heavy_ge, heavy_ge2): mapclass on maps/<map>.map26a, else from the replay's camp groups (whole groups, no reachability)"""
    path = next((p for p in (f"{d}/{mp}.map26a" for d in MAPDIRS) if os.path.exists(p)), None) if mp else None
    if path:
        try:
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                import mapclass
                v = mapclass.values(path, ["heavy_ge", "heavy_ge2"])
            return v.get("heavy_ge"), v.get("heavy_ge2")
        except Exception:  # noqa: BLE001
            pass
    tot = sum(gr["gems"] for gr in g.groups.values())
    if not tot:
        return None, None
    hv = sum(gr["gems"] for gr in g.groups.values() if is_heavy(gr))
    return round(hv / tot, 4), None


def is_heavy(gr):
    t = gr["types"]
    return (t.get("elk") or t.get("golem")) and not t.get("monolith")


def compute(g, mp=None, foe=None, gid=None):
    us, them = g.us, 1 - g.us
    f = g.final or {}
    won = {1: 0, 2: 1}.get(f.get("outcome"))
    result = "draw" if won is None else ("win" if won == us else "loss")
    row = g.round_row(min(300, g.last_round)) or [0] * 11
    gu, gt = row[5 + us], row[5 + them]
    ku = kt = du = dt = 0
    for b in (g.d.get("stats") or {}).get("bodies", []):
        if b["team"] == us:
            ku, du = ku + b["kills"], du + b["deaths"]
        else:
            kt, dt = kt + b["kills"], dt + b["deaths"]
    cap = {0: [0, 0, 0], 1: [0, 0, 0]}  # team -> [gems, heavy gems, mid gems] to r600
    for e in g.events:
        if e[0] > 600:
            continue
        if e[1] != "capture" or e[3] not in (0, 1):
            continue
        gems = sum(x[2] for x in e[4])
        for gi in (e[2] if isinstance(e[2], list) else [e[2]]):
            gr = g.groups.get(gi)
            if not gr:
                continue
            c = cap[e[3]]
            c[0] += gems
            if is_heavy(gr):
                c[1] += gems
            if g.zone(round(gr["cx"]), round(gr["cy"]), us) == "mid":
                c[2] += gems
            break
    gap = cap[them][0] - cap[us][0]
    hgap = cap[them][1] - cap[us][1]
    mgap = cap[them][2] - cap[us][2]
    mp = mp or g.meta.get("map", "")
    hge, hge2 = heavy_shares(g, mp)
    ratio = gu / max(1, gt)
    if result != "loss":
        cls, why = "win" if result == "win" else "draw", result
    elif ratio < PACE_RATIO:
        cls, why = "pace", f"gold {gu}-{gt} at r300 (x{ratio:.2f} < {PACE_RATIO:.2f})"
    elif kt >= ku + FIGHT_MARGIN and kt >= 2 * ku:
        cls, why = "fight-lost", f"not behind in gold at r300 (x{ratio:.2f}) but kills {ku}-{kt}"
    elif hgap >= GAP_MIN and ((hge2 is not None and hge2 >= 0.5) or hgap >= gap / 2):
        cls, why = "heavy", f"heavy-group gems to r600 {cap[us][1]}-{cap[them][1]} (gap {hgap} of {gap}), heavy_ge2 {None if hge2 is None else round(hge2, 2)}"
    elif mgap >= GAP_MIN and mgap >= gap / 2:
        cls, why = "midgem", f"mid-zone gems to r600 {cap[us][2]}-{cap[them][2]} (gap {mgap} of {gap})"
    else:
        cls, why = "other", f"x{ratio:.2f} gold at r300, kills {ku}-{kt}, gem gap r600 {gap} (heavy {hgap}, mid {mgap})"
    return dict(id=gid or g.meta.get("match", ""), map=mp, foe=foe or g.meta.get("opponent", ""), us="AB"[us], result=result,
                gold_us_r300=gu, gold_them_r300=gt, gold_behind_r300=gu - gt, gold_ratio_r300=round(ratio, 2), kills_us=ku, kills_them=kt,
                deaths_us=du, deaths_them=dt, gems_us_r600=cap[us][0], gems_them_r600=cap[them][0], heavy_gap_r600=hgap,
                mid_gap_r600=mgap, heavy_ge=hge, heavy_ge2=None if hge2 is None else round(hge2, 4), **{"class": cls},
                needs_analyst=cls not in CLOSED + ("win", "draw"), why=why)


def classify(spec, us=None, foe=None):
    """spec: a full match id or a replay path -> the row dict (raises on any failure)"""
    import replay as R
    mp = gid = None
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", spec):
        gid = spec
        if us is None or foe is None:
            lk = lookup(spec)
            if lk:
                us = us or (lk["seat"] if lk["seat"] in "AB" else None)
                foe, mp = foe or lk["foe"], lk["map"]
                if lk["path"] not in ("-", "") and os.path.exists(lk["path"]):
                    spec = lk["path"]
    with slot():
        g = R.load(spec, us)
    return compute(g, mp, foe, gid)


def fmt(r):
    return "\t".join("" if r.get(c) is None else str(r.get(c)).lower() if isinstance(r.get(c), bool) else str(r.get(c)) for c in COLS)


def annotate(a):
    """the intake hook: best-effort, never raises, never exits non-zero"""
    try:
        mid = a[0]
        opt = lambda k: a[a.index(k) + 1] if k in a else None  # noqa: E731
        r = classify(mid, opt("--us"), opt("--foe"))
        mp = f"{CRIT}/{mid}/meta.json"
        m = json.load(open(mp))
        rec = {k: r[k] for k in ("class", "needs_analyst", "gold_behind_r300", "gold_ratio_r300", "kills_us", "kills_them", "deaths_us",
                                 "deaths_them", "heavy_gap_r600", "mid_gap_r600", "heavy_ge2", "why")}
        rec["t"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        m["lossclass"] = rec
        if not r["needs_analyst"] and not m.get("closed"):
            m.update(closed=f"auto-closed-to-class {r['class']}: {r['why']} (lossclass.py)", closed_by="lossclass", closed_t=rec["t"])
        if "--dry" in a:
            print(json.dumps(rec))
            return 0
        tmp = f"{mp}.{os.getpid()}"
        json.dump(m, open(tmp, "w"), indent=1)
        os.replace(tmp, mp)
        print(f"lossclass {mid}: {r['class']}" + (" (auto-closed-to-class)" if not r["needs_analyst"] else " (needs analyst)"))
    except (Exception, SystemExit) as e:  # noqa: BLE001
        print(f"lossclass {a[:1]}: not classified ({type(e).__name__}: {str(e)[:120]}); left for an analyst")
    return 0


def self_test():
    """Combat's tags: an id in sbg739_econclose.txt = class-closed (pace) without a walk; the other screen rows were walked (needs
    analyst). Also checks our gold ratio against the screen's g300 column."""
    closed = {ln.strip() for ln in open(ECONCLOSE) if ln.strip()}
    conf = {}
    bad_ratio, rows = 0, []
    for ln in open(SCREEN):
        f = ln.rstrip("\n").split("\t")
        if len(f) < 8:
            continue
        gid, mp, g300 = f[0], f[1], float(f[7])
        truth = "closed" if gid in closed else "analyst"
        try:
            r = classify(gid)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"{gid}\t{mp}\tERROR {type(e).__name__}: {str(e)[:100]}")
            conf[(truth, "error")] = conf.get((truth, "error"), 0) + 1
            continue
        mine = "analyst" if r["needs_analyst"] else "closed"
        conf[(truth, mine)] = conf.get((truth, mine), 0) + 1
        if abs(r["gold_ratio_r300"] - g300) > 0.011:
            bad_ratio += 1
        rows.append((gid, mp, truth, r["class"], g300, r["gold_ratio_r300"], f"{r['kills_us']}-{r['kills_them']}", r["why"]))
    print("id\tmap\tcombat\tlossclass\tg300_combat\tg300_ours\tkills\twhy")
    for x in rows:
        print("\t".join(map(str, x)))
    n = sum(conf.values())
    agree = conf.get(("closed", "closed"), 0) + conf.get(("analyst", "analyst"), 0)
    print(f"\nconfusion (Combat tag -> lossclass): " + ", ".join(f"{a}->{b} {v}" for (a, b), v in sorted(conf.items())))
    print(f"agreement {agree}/{n}; gold ratio r300 mismatches v the screen's column: {bad_ratio}")
    return 0 if agree == n else 1


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] == "--self-test":
        return self_test()
    if a[0] == "--annotate":
        return annotate(a[1:])
    us = a[a.index("--us") + 1] if "--us" in a else None
    ids = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--us")]
    print("\t".join(COLS))
    rc = 0
    for x in ids:
        try:
            print(fmt(classify(x, us)), flush=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"{x}\t" + "\t" * (len(COLS) - 4) + f"error\ttrue\t{type(e).__name__}: {str(e)[:120]}", flush=True)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
