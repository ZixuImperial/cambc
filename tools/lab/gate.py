#!/usr/bin/env python3
"""gate: one-shot no-harm / improvement gate. Tool builder, 1 Nov (owner: faster iterations; Builder: agents ran the legs one
after another). Launches IN PARALLEL on Condor
  - killgate CAND BASE TAG --lane LANE   (stage A, then the sequential BIG leg on the 2,621 BIG maps; reused by a later shipcheck)
  - stylepanel CAND BASE TAG --fresh-only --n 600   (two unseen fresh-pool sets of 300, half normal, half genweird pathological families, kind-labelled; single use)
waits for both, and prints ONE verdict block with shipcheck's bars:
  BIG     killgate's verdict: KILL = FAIL. fix lane: as shipcheck's change-size bands (eff_lane), by the last look's changed share: CI upper >= 0.5
          and point >= FIX_BIG_LH (0.50), or BUGBAR_PT (0.495) with --bugbar or --trunk-code (owner 7 Nov). behaviour lane: BIG point >= POOL_NOHARM (0.50), the pooled row decides.
  FRESH   stylepanel's FRESH row: CI upper >= 0.5; a kind (>= 10 maps) at z <= -2.5 starts a second fresh set and blocks only if negative again (stylepanel's SECOND
          READ, owner 2 Nov), and the bars then read both sets pooled; behaviour lane, and fix lane with > 50% of maps changed, also pooled >= FRESH_MIN (0.50; .495 with --bugbar or --trunk-code) (shipcheck's
          FRESH DECIDES bar; 2 Nov: a gate read PASS at 0.494 that shipcheck would fail).
  FUEL    shipcheck.fuel_paired: exhaustions capped at 5 per side per game, map-paired over every CAND vs BASE game on record;
          FAIL when CAND - BASE > max(5% of BASE, 1.645 SE, 5).
  DEATHS  shipcheck.death_row: FAIL when the BIG z >= 2.5 (CAND dies more) and the fresh difference has the same sign.
  FAULTS  CAND bot faults in the BIG leg (killgate) and the fresh leg: any = FAIL.
  STYLE   CAND and BASE each vs the opponent-style spars (nova_spar_aggro, nova_spar_sbg, nova_spar_fish) on the same fresh maps: CAND - BASE
          pooled CI upper >= 0 and no spar at z <= -2.5 (stylepanel's PANEL bar). --no-style skips it (fresh only, half the games).
          --full-panel plays stylepanel's whole panel, which shipcheck plays on every lane anyway (2 Nov: 13 spars in every gate
          flooded the pilot queue on the home quota); shipcheck adopts what a gate played on these maps.
A KILL from killgate stops the fresh leg at once (its partial read is still shown). Ctrl-C / SIGTERM stops both.
One leg after another (2 Nov, owner: faster iterations): fresh, then the style panel, then BIG, each only if the one before did not FAIL, so a failing
candidate costs 1,196 games, not 13,000-16,000. A passing one takes longer on an empty pool. --keep-fresh plays them all in parallel, as a split needs.

usage: python3 -I tools/lab/gate.py CAND BASE --lane fix|behaviour [--tag TAG] [--trigger LIST] [--no-a] [--fresh-n 600] [--trunk-code] [--bugbar] [--class COND]
  --class 'heavy_ge:>=0.5' (10 Nov, Planner): the fresh leg draws only maps of that class (stylepanel/stratmaps --class); BIG is unchanged.
  --bugbar: fix lane, for a line that will arm with BUGBAR=1: shipcheck's bug bar, BIG point >= 0.50 (owner 9 Nov; was .495) and CI upper >= 0.50, and the fresh floor .50 above 50% changed. Every other row stays.
  --trunk-code: shipcheck's "trunk code vs live" row: BIG and fresh pooled, no-harm point >= 0.495 and CI upper >= 0.50, with the trunk's 20/20 null identity (registry) as a precondition (3 Nov, Builder).
Files: /data/zw4424/st/gate/TAG/ (verdict.txt, kg.log, sp.log); killgate's own files in /data/zw4424/st/kg/TAG/, stylepanel's
in /data/zw4424/st/bq/spTAG.txt and /data/zw4424/st/panel/TAG/. Exit 0 = PASS, 1 = FAIL, 2 = INCONCLUSIVE.
A PASS is not a ship by itself: shipcheck (or a hand submit under the owner's bars) still ships. With BASE = the live bot and
the same CAND source, shipcheck replays nothing of this: its live h2h reuses the BIG games (game index) and its fresh leg adopts
this fresh read (stylepanel --reuse-fresh auto: maps kept, single use), so only ubaudit / anchor / panel legs play."""
import argparse
import atexit
import json
import math
import os
import re
import signal
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
sys.path.insert(0, os.path.join(REPO, "tools/lab"))
import shipcheck as S  # noqa: E402  (bars: fuel_paired, death_row, panel_rows)
STYLE = ["nova_spar_aggro", "nova_spar_sbg", "nova_spar_fish"]  # owner 8 Nov (spec_panel3_1108). Before: ["nova_spar_alldash", "nova_spar_sustain", "nova_spar_hunter2", "nova_spar_hd126", "nova_spar_neet", "nova_spar_centre", "nova_ft_lobl1", "nova_ft_lobl2"]  # lobl1/2: 5 Nov, Econ LOB (gem-poor 5-pick no-monolith live loss class)
#  # centre: b1164, 4 Nov  # opponent-style spars (1 Nov; nova_spar_neet 3 Nov, b946: a NEETCoders-like lineup and banking, our biggest loss source): all-dash and C&I/Willow sustain lineups; 2 Nov (owner: spars must hound us): a hunter

GATE = "/data/zw4424/st/gate"
KG = "/data/zw4424/st/kg"


TRUNK_ONLY = [False]  # 9 Nov: --trunk-code keeps shipcheck's TRUNK_PT (.495); --bugbar uses BUGBAR_PT (.50 since the owner's 9 Nov rule)

def now():
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def read(p):
    try:
        return open(p, errors="replace").read()
    except OSError:
        return ""


def big_row(tag, lane, bands=True, bugbar=False):
    v = read(f"{KG}/{tag}/verdict.txt")
    m = re.search(r"^VERDICT: (\w+)\s*(.*)$", v, re.M)
    looks = re.findall(r"^\s+(\d+) ([\d.]+) \[([\d.]+), ([\d.]+)\]\s+([\d.]+)%\s+([-+\d.]+)\s+([\d.]+)%", v, re.M)
    faults = re.search(r"faults CAND (\d+) BASE (\d+)", v)
    if not m:
        return ("BIG (killgate)", "no verdict (killgate did not finish)", "", "INCONCLUSIVE"), None, None
    verdict = m.group(1)
    val = verdict
    los = changed = None
    bar = "not KILL" if lane == "fix" else "PROMOTE or LOS>=90%"
    if looks:
        n, sc, lo, hi, los, z, ch = looks[-1]
        los = float(los)
        changed = float(ch)
        val = f"{verdict}: {sc} [{lo}, {hi}] LOS {los:.0f}% ({n} maps, {ch}% changed)"
    elif "STAGE A" in v:
        a = re.search(r"^STAGE A:.*$", v, re.M)
        val = f"{verdict}: {a.group(0)[:70] if a else ''}"
    if verdict == "KILL":
        res = "FAIL"
    elif lane == "fix":
        res = "PASS"
        if looks and bands:
            pt = (S.TRUNK_PT if TRUNK_ONLY[0] else S.BUGBAR_PT) if bugbar else S.FIX_BIG_LH
            bb = bugbar and not TRUNK_ONLY[0]  # 9 Nov ~22:40Z, owner: a bug-bar line also needs CI lower >= S.BUGBAR_LO (.4975)
            bar = f"{'BUG BAR ' if bugbar else ''}pt>={pt:g}, up>=0.5" + (f", lo>={S.BUGBAR_LO:g}" if bb else "")
            res = "PASS" if float(sc) >= pt and float(hi) >= 0.5 and (not bb or float(lo) >= S.BUGBAR_LO) else "FAIL"
    else:  # behaviour, owner 3 Nov: BIG is no-harm (point >= 0.495); the pooled BIG + fresh row decides
        bar = f"pt>={S.POOL_NOHARM:g} (no-harm)"
        res = "PASS" if verdict != "KILL" and looks and float(sc) >= S.POOL_NOHARM else "FAIL"
    return ("BIG (killgate)", val, bar, res), (int(faults.group(1)) if faults else None), changed


def pooled(rows, noharm=False):
    """The behaviour lane's deciding row (owner 3 Nov ~03:20Z): BIG and fresh pooled, map-weighted: point >= 0.503 and LOS >= 90%.
    noharm (trunk code): point >= 0.495 and CI upper >= 0.50."""
    b = next((r for r in rows if r[0] == "BIG (killgate)"), None)
    f = next((r for r in rows if r[0] == "fresh maps"), None)
    mb = re.search(r"([\d.]+) \[([\d.]+), ([\d.]+)\] LOS \d+% \((\d+) maps", b[1]) if b else None
    bar = "pt>=0.495, up>=0.50 (no-harm)" if noharm else "pt>=0.503, LOS>=90%"
    mf = re.search(r"CAND vs LIVE ([\d.]+) \[([\d.]+), ([\d.]+)\] over (\d+) maps", f[1]) if f else None
    if not mb or not mf:
        return ("pooled BIG+fresh", "no read (a leg has no result)", bar, "INCONCLUSIVE")
    (p1, l1, h1, n1), (p2, l2, h2, n2) = [(float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4))) for m in (mb, mf)]
    pt = (n1 * p1 + n2 * p2) / (n1 + n2)
    se = math.sqrt((n1 * (h1 - l1) / 3.92) ** 2 + (n2 * (h2 - l2) / 3.92) ** 2) / (n1 + n2)
    los = 0.5 * (1 + math.erf((pt - 0.5) / max(se, 1e-9) / math.sqrt(2)))
    ok = (pt >= 0.495 and pt + 1.96 * se >= 0.50) if noharm else (pt >= 0.503 and los >= 0.90)
    return ("pooled BIG+fresh", f"{pt:.4f} [{pt - 1.96 * se:.4f}, {pt + 1.96 * se:.4f}] n {n1 + n2} LOS {100 * los:.0f}%", bar, "PASS" if ok else "FAIL")


def fresh_fix_bar(row, changed, bugbar=False):
    """The fresh row on the fix lane: shipcheck's FRESH DECIDES point when > 50% of maps changed (its "fresh decides (fix)" row)."""
    m = re.search(r"([\d.]+) \[", row[1])
    fm = (S.TRUNK_PT if TRUNK_ONLY[0] else S.BUGBAR_PT) if bugbar else float(S.FRESH_MIN)
    if changed is None or changed <= 50 or row[3] != "PASS" or not m or float(m.group(1)) >= fm:
        return row
    return (row[0], row[1], f">={fm:g}, >50% changed", "FAIL")


def fresh_faults(tag, cand):
    n = f = 0
    for ln in read(f"/data/zw4424/st/panel/{tag}/fp_games.jsonl").splitlines():
        try:
            g = json.loads(ln)
        except ValueError:
            continue
        if cand in (g["a"], g["b"]):
            s = g["sa"] if g["a"] == cand else g["sb"]
            f += int(s.get("faults", 0))
            n += 1
    return f, n


def wait_turn(tag):
    """2 Nov (owner: a shipcheck verdict every 15 min): at most GATE_CAP gates play at once, the rest wait first come, first served."""
    cap = int(os.environ.get("GATE_CAP", 4))
    d = f"{GATE}/.turns"
    os.makedirs(d, exist_ok=True)
    me = f"{time.time():.3f}_{os.getpid()}"
    open(f"{d}/{me}", "w").close()
    atexit.register(lambda: os.path.exists(f"{d}/{me}") and os.remove(f"{d}/{me}"))
    said = False
    while True:
        turns = []
        for n in sorted(os.listdir(d)):
            if os.path.exists(f"/proc/{n.split('_')[-1]}"):
                turns.append(n)
            else:
                try:
                    os.remove(f"{d}/{n}")
                except OSError:
                    pass
        k = turns.index(me)
        if k < cap:
            return
        if not said:
            print(f"[gate {tag}] waiting: {k - cap + 1} ahead of it, {cap} gates playing (GATE_CAP)", flush=True)
            said = True
        time.sleep(15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("base")
    ap.add_argument("--lane", choices=("fix", "behaviour"), required=True)
    ap.add_argument("--trunk-code", action="store_true")
    ap.add_argument("--bugbar", action="store_true", help="fix lane: shipcheck's BUGBAR=1 bar (BIG point >= 0.495, CI upper >= 0.50; fresh floor .495 above 50%% changed)")
    ap.add_argument("--tag", default=None, help="[A-Za-z0-9]+ (default: g + the candidate's bNNN number + 4 hex)")
    ap.add_argument("--trigger", default=None, help="killgate --trigger LIST (stage A on the maps where the change fires)")
    ap.add_argument("--no-a", action="store_true", help="killgate stage B only")
    ap.add_argument("--fresh-n", type=int, default=None, help="default 1,200 on the behaviour lane (panel 600), 600 on the fix lane")
    ap.add_argument("--keep-fresh", action="store_true", help="neither leg stops the other: no stop on a killgate KILL or on a failed fresh read (a split needs both reads)")
    ap.add_argument("--class", dest="cls", default=None, help="NAME:OPvalue (e.g. heavy_ge:>=0.5; tools/lab/mapclass.py): the fresh leg (and its style "
                    "spars) plays only maps of that class (stylepanel --class); BIG is unchanged. The fresh and pooled rows then mean class maps")
    ap.add_argument("--no-style", action="store_true", help="skip the opponent-style spar legs (all-dash, C&I/Willow sustain)")
    ap.add_argument("--full-panel", action="store_true", help="only with GATE_FULL=1 in the environment: shipcheck's whole spar panel instead of the style spars (2 Nov: agents' full panels filled the queue, and shipcheck plays it on anything that passes)")
    a = ap.parse_args()
    if not any(os.path.isdir(f"{REPO}/bots/{b}/src") for b in STYLE):  # the style opponents were deleted (owner 8 Nov)
        a.no_style = True
    if a.bugbar and a.lane != "fix":
        sys.exit("--bugbar needs --lane fix")
    if (a.cand.startswith("nova_base_v")) != (a.base.startswith("nova_base_v")) and not os.environ.get("GATE_MIXED_BAKE_OK"):
        # 10 Nov ~22:30Z (Builder's drift chain): a baked base plays a different game from its shipped bot at 100k (35-67% of games
        # differ; memory baked-base-not-identical-100k-1110). A trunk built on a base v that base is fine; a drift read is not.
        print(f"[gate] WARNING: {a.cand} v {a.base} mixes a baked nova_base_* with an unbaked bot: they differ at 100k through fuel-gated "
              f"bars, so a drift read is confounded. Use the shipped names in bq/live.txt / baseline.txt (GATE_MIXED_BAKE_OK=1 silences this).",
              flush=True)
    for b in (a.cand, a.base):
        if not os.path.isdir(os.path.join(REPO, "bots", b)):
            sys.exit(f"no bot bots/{b}")
    num = re.search(r"b(\d+)", a.cand)
    tag = a.tag or f"g{num.group(1) if num else ''}{os.urandom(2).hex()}"
    if not re.fullmatch(r"[A-Za-z0-9]+", tag):
        sys.exit("TAG must be [A-Za-z0-9]+")
    d = f"{GATE}/{tag}"
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    if a.cls:  # a bad condition exits here, before any leg starts
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import mapclass
        mapclass.parse(a.cls)
    if a.fresh_n is None:
        a.fresh_n = 1200 if a.lane == "behaviour" else 600
    kg = ["python3", "-I", "tools/lab/killgate.py", a.cand, a.base, tag, "--lane", a.lane]
    if a.trigger:
        kg += ["--trigger", a.trigger]
    if a.no_a:
        kg += ["--no-a"]
    sp = ["python3", "-I", "tools/lab/stylepanel.py", a.cand, a.base, tag, "--n", str(a.fresh_n), "--keep-maps",
          "--parent", str(os.getpid())]  # --keep-maps: a complete read is REUSABLE by shipcheck (same sources: no replay)
    full = a.full_panel and os.environ.get("GATE_FULL") == "1"
    if a.full_panel and not full:
        print(f"[gate {tag}] --full-panel ignored without GATE_FULL=1: style spars only; shipcheck plays the whole panel", flush=True)
    sp += ["--fresh-only"] if a.no_style else ["--par", str(S.PANEL_PAR)] if full else ["--panel", ",".join(STYLE)]  # same maps (CAND and BASE)
    if not a.keep_fresh:
        sp += ["--fresh-first"]
    if a.fresh_n > 600:
        sp += ["--panel-n", "600"]
    if a.lane == "behaviour":
        sp += ["--fresh-min", S.FRESH_MIN]
    if a.cls:
        sp += ["--class", a.cls]
    if not a.trunk_code:  # shipcheck's own code row never waits
        wait_turn(tag)
    print(f"[gate {tag}] {a.cand} vs {a.base}, lane {a.lane}: {'killgate + fresh ' + str(a.fresh_n) + ' in parallel' if a.keep_fresh else 'fresh ' + str(a.fresh_n) + ', panel, then killgate'}; files {d}", flush=True)
    procs = {}
    with open(f"{d}/sp.log", "w") as ls:
        if a.keep_fresh:
            with open(f"{d}/kg.log", "w") as lk:
                procs["kg"] = subprocess.Popen(kg, cwd=REPO, stdout=lk, stderr=subprocess.STDOUT)
        procs["sp"] = subprocess.Popen(sp, cwd=REPO, stdout=ls, stderr=subprocess.STDOUT)

    def stop(*_):
        for p in procs.values():
            if p.poll() is None:
                p.terminate()  # killgate / stylepanel stop their condab legs (which remove their Condor clusters)
        sys.exit(2)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    killed = big_skipped = False
    while any(p.poll() is None for p in procs.values()) or ("kg" not in procs and not big_skipped):
        if "kg" not in procs and procs["sp"].poll() is not None:
            if any(r[0] in ("fresh maps", "playstyle panel") and r[3] == "FAIL" for r in S.panel_rows(tag)):
                big_skipped = True
                print(f"[gate {tag}] fresh or panel FAIL: BIG not played", flush=True)
            else:
                print(f"[gate {tag}] fresh and panel did not fail: BIG starts", flush=True)
                with open(f"{d}/kg.log", "w") as lk:
                    procs["kg"] = subprocess.Popen(kg, cwd=REPO, stdout=lk, stderr=subprocess.STDOUT)
            continue
        if not killed and not a.keep_fresh and "kg" in procs and procs["kg"].poll() is not None and re.search(r"^VERDICT: KILL", read(f"{KG}/{tag}/verdict.txt"), re.M):
            killed = True
            if procs["sp"].poll() is None:
                print(f"[gate {tag}] killgate KILL: stopping the fresh leg", flush=True)
                procs["sp"].terminate()
        time.sleep(10)
    rows = []
    bug = a.bugbar or a.trunk_code  # owner 7 Nov: bugs and play-identical changes use .495; owner 9 Nov: bug bar .50, trunk code keeps .495
    TRUNK_ONLY[0] = bool(a.trunk_code and not a.bugbar)
    br, kf, changed = big_row(tag, a.lane, bands=True, bugbar=bug)  # 3 Nov (b935 audit): trunk code gets the fix lane's change-size bars too, not just 'not KILL'
    rows.append(("BIG (killgate)", "not played: fresh or panel failed first", "", "SKIPPED") if big_skipped else br)
    prs = S.panel_rows(tag)
    pr = [r for r in prs if r[0] == "fresh maps"]
    if a.lane == "fix":
        pr = [fresh_fix_bar(r, changed, bug) for r in pr]
    rows += pr or [("fresh maps", "no result (stylepanel did not finish)", "", "INCONCLUSIVE")]
    if not a.no_style:  # CAND - BASE vs the panel on the fresh maps (stylepanel's PANEL bar: pooled CI upper >= 0, no bot z <= -2.5)
        rows += [r for r in prs if r[0] == "playstyle panel"] or [("playstyle panel", "no result", "", "INCONCLUSIVE")]
    f = S.fuel_paired(a.cand, a.base)
    if f is None:
        rows.append(("fuel exhaustions", "no CAND vs BASE games on record", "", "INCONCLUSIVE"))
    else:
        rows.append(("fuel exhaustions", f"cap{S.FUEL_CAP} {f['c']} vs {f['b']} ({f['c'] / max(1, f['b']):.2f}x, z {f['z']:+.1f}, "
                     f"{f['maps']} maps)", f"<= max(5%, {S.FUEL_Z:g} SE)", "FAIL" if f["fail"] else "PASS"))
    dr = S.death_row(a.cand, a.base, tag)
    if dr:
        rows.append(dr)
    ff, fn = fresh_faults(tag, a.cand)
    if kf is None and not fn:
        rows.append(("bot faults", "no games read", "0", "INCONCLUSIVE"))
    else:
        tot = (kf or 0) + ff
        rows.append(("bot faults", f"CAND {tot} (BIG {kf if kf is not None else '?'}, fresh {ff} in {fn} games)", "0",
                     "FAIL" if tot else "PASS"))
    if big_skipped:  # not played by design (fresh, then panel, then BIG): not a fault to read past
        rows = [(x, "not played: an earlier leg failed", "", "SKIPPED") if w == "INCONCLUSIVE" else (x, y, z, w) for x, y, z, w in rows]
    if a.lane == "behaviour" and not big_skipped:
        rows.append(pooled(rows))
    if a.trunk_code:  # 3 Nov (Builder, the owner's bug bar for play-identical code): pooled no-harm decides, the null identity is a precondition
        rows = [(x, y, z, "info" if x in ("BIG (killgate)", "fresh maps") and w in ("PASS", "FAIL") else w) for x, y, z, w in rows]
        rows.append(pooled(rows, noharm=True))
        rows.append(S.identity_row(a.cand))
    if not big_skipped:
        rows = S.fuel_ratio(rows, a.cand, a.base, tag)[0]
    res = [r[3] for r in rows]
    overall = "FAIL" if "FAIL" in res else ("INCONCLUSIVE" if "INCONCLUSIVE" in res else "PASS")
    L = [f"GATE {tag}: {a.cand} vs {a.base}, lane {a.lane}, {now()}, wall {(time.time() - t0) / 60:.1f} min",
         f"  {'leg':18s} {'value':66s} {'bar':22s} verdict"]
    L += [f"  {x:18s} {y[:66]:66s} {z[:22]:22s} {w}" for x, y, z, w in rows]
    L.append(f"  OVERALL: {overall}" + ("  (killgate KILL stopped the fresh leg early)" if killed else "  (BIG not played: fresh or panel failed first)" if big_skipped else ""))
    L.append(f"  files: {d}/ ; killgate {KG}/{tag}/verdict.txt ; fresh {S.Q}/sp{tag}.txt")
    txt = "\n".join(L)
    with open(f"{d}/verdict.txt", "w") as o:
        o.write(txt + "\n")
    print(txt)
    return {"PASS": 0, "FAIL": 1}.get(overall, 2)


if __name__ == "__main__":
    sys.exit(main())
