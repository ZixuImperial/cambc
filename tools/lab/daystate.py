#!/usr/bin/env python3
"""daystate: one generated page of the pipeline's current facts, so sessions stop relaying stale ones (Tool Builder, 12 Nov; Coordinator:
"disk '19G' after the prune, v791-v793 unreported, EMO's closure not relayed for 2 h").

usage: python3 -I tools/lab/daystate.py [--loop --every 1800]     writes condor-work/reports/live/daystate.md (atomic)
Sections: live version + its ship line, ships in the last 24 h, running / waiting shipchecks v the cap, armq queue, closed lines in the
last 24 h (failure_chains.md), parked handoffs, open owner questions (owner_*question*.md), disk / home / load, kerberos.
Read-only on everything else; every fact names its source file."""
import glob
import os
import re
import subprocess
import sys
import time

BQ = "/data/USER/st/bq"
REP = "/homes/USER/condor-work/reports"
OUT = f"{REP}/live/daystate.md"
REPO = "/homes/USER/cambc"


def sh(cmd, t=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t, shell=isinstance(cmd, str)).stdout
    except Exception:  # noqa: BLE001
        return ""


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(t))


def build():
    now = time.time()
    L = [f"# Pipeline state (generated {iso(now)} by tools/lab/daystate.py; refreshed every 30 min; do not edit)", ""]
    live = [ln.split() for ln in open(f"{BQ}/live.txt") if ln.strip()]
    L.append(f"## Live: {live[0][0]} {live[0][1]} (shipped {live[0][2]}) (bq/live.txt)")
    bm = ""
    try:
        bm = next((ln.strip() for ln in open(f"{BQ}/best_model.txt") if ln.startswith(live[0][0] + " ")), "")
    except OSError:
        pass
    if bm:
        L.append("- " + bm[:400])
    def shipped_at(x):
        try:
            return time.mktime(time.strptime(x[2][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except (IndexError, ValueError):
            return 0.0  # a live.txt line without a time (older formats)
    day = [x for x in live if shipped_at(x) > now - 86400]
    try:  # 12 Nov (Coordinator): one alarm line when a foe's bot changed today (tools/lab/foeepoch.py windows, inferred from draft changes)
        import datetime as _dt
        subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "foeepoch.py"), "detect", "--quiet"],
                       capture_output=True, timeout=300)
        today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        fe = [x.rstrip("\n").split("\t") for x in open("/data/USER/st/bq/foe_epochs.tsv") if not x.startswith(("#", "foe\t"))]
        ch = [f"{x[0]} ({x[1][11:16]}-{x[2][11:16]}Z, {x[3]} cells)" for x in fe if x[2][:10] == today and x[0] in ("Mite", "Intercontinental Fish", "stellar best girl", "Team Kungarna")]  # 12 Nov (Coordinator): all four watched foes
        if ch:
            L.append(f"- ALARM foe changes today (draft-inferred, tools/lab/foeepoch.py; split records with gameindex --foe-epoch new/old): {'; '.join(ch)}")
    except Exception as e:  # noqa: BLE001
        L.append(f"- foe changes: not read ({e!r})"[:160])
    L += ["", f"## Ships in the last 24 h: {len(day)}"] + [f"- {x[0]} {x[1]} {x[2]}{' (hand)' if 'hand' in x else ''}" for x in day[:40]]
    ps = sh(["ps", "-u", str(os.getuid()), "-o", "etimes=,args="])
    run = [ln.split() for ln in ps.splitlines() if "tools/lab/shipcheck.py" in ln]
    try:
        cap = open(f"{BQ}/max_running").read().strip()
    except OSError:
        cap = "?"
    L += ["", f"## Shipchecks running: {len(run)} (cap {cap}, bq/max_running)"]
    for r in run:
        L.append(f"- TAG {r[-1]} {r[-2]} running {int(r[0]) // 60} min")
    waits = [ln for ln in open(f"{BQ}/shipwatch.log", errors="replace").readlines()[-400:] if " queue nova_b" in ln]
    seen = {}
    for ln in waits:
        m = re.search(r"queue (nova_\S+): (.*)", ln)
        if m:
            seen[m.group(1).rstrip(":")] = (ln[:20], m.group(2)[:150])
    L += ["", f"## Waiting to start (last queue lines, shipwatch.log): {len(seen)}"] + [f"- {k}: {v[1]} (at {v[0]})" for k, v in list(seen.items())[-10:]]
    aq = sh([sys.executable, "-I", f"{REPO}/tools/lab/armq.py", "list"]).strip().splitlines()
    L += ["", f"## armq queue (armq.py list): {len(aq)} line(s)"] + ["- " + x[:200] for x in aq[:10]]
    ends = [ln.strip() for ln in open(f"{BQ}/shipwatch.log", errors="replace").readlines()[-3000:] if " ended " in ln]
    recent = [e for e in ends if e[:19] >= time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - 6 * 3600))]
    vc = {}
    for e in recent:
        v = e.rsplit(":", 1)[-1].strip().split()[0]
        vc[v] = vc.get(v, 0) + 1
    L += ["", f"## Shipcheck endings, last 6 h: {len(recent)} ({', '.join(f'{k} {v}' for k, v in sorted(vc.items()))})"] + ["- " + e[:130] for e in recent[-12:]]
    try:
        fc = [ln.strip() for ln in open(f"{BQ}/failure_chains.md", errors="replace") if re.search(r"CLOSED|closed", ln)]
        cut = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - 86400))
        stamp = lambda x: (re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d", x) or re.match("", "")).group(0)  # noqa: E731  ('' when none)
        fc = [x for x in fc if stamp(x) >= cut]
    except OSError:
        fc = []
    L += ["", f"## Lines closed in the last 24 h (bq/failure_chains.md): {len(fc)}"] + ["- " + x[:200] for x in fc[-15:]]
    pk = sorted(glob.glob(f"{REP}/parked/*.md"), key=os.path.getmtime, reverse=True)
    L += ["", f"## Parked (condor-work/reports/parked/): {len(pk)}"] + [f"- {os.path.basename(p)} ({iso(os.path.getmtime(p))})" for p in pk[:12]]
    try:
        ml = open("/data/USER/st/sharedmem/state_line.txt").read().strip()  # Shared Mem, 12 Nov: one line, carries its own time
    except OSError:
        ml = ""
    if ml:
        L += ["", "## Memory side (st/sharedmem/state_line.txt)", "- " + ml[:900]]
    lanes = []
    for d in ["climb", "climb_side", "climb_side1", "climb_side2", "climb_side3", "climb_side4", "climb_top3"]:
        p = f"/data/USER/st/{d}"
        g = os.path.join(p, "games.tsv")
        if os.path.exists(g):
            try:
                n = sum(1 for _ in open(g, errors="replace"))
            except OSError:
                n = -1
            lanes.append(f"- {d}: games.tsv {n} lines, updated {iso(os.path.getmtime(g))}")
    L += ["", f"## Unranked climb lanes (st/climb*/games.tsv): {len(lanes)}"] + lanes
    try:  # 12 Nov (Coordinator): the standing post-triage view of argument-closes, rewritten here each refresh
        sys.path.insert(0, f"{REPO}/tools/lab")
        import closedby
        ta, tc, un = closedby.triage_report()
        L += ["", f"## Argument-closes (closedby_triage_1112.md): {ta} on A rows, {tc} cleared, {un} UNTRIAGED"]
    except Exception as e:  # noqa: BLE001
        L += ["", f"## Argument-closes: triage report failed ({e!r})"]
    # 12 Nov (Combat, Coordinator's ask): untested_closes row 59's pre-registered re-test (combat_tools/midarr.py) runs on the next 150 Mite games
    try:
        sh([sys.executable, "-I", f"{REPO}/tools/lab/gameindex.py", "build", "--if-older", "1800", "--quiet"], t=600)
        since, nr, nt = "2026-11-12T07:00", 0, 0
        for ln in open("/data/USER/st/gameindex.tsv", errors="replace"):
            x = ln.rstrip("\n").split("\t")
            if len(x) > 8 and x[4] == "Mite" and x[8][:16] >= since:
                nr += x[7] == "ranked"
                nt += x[7] == "top3"
        L += ["", f"## Mite games since {since}Z: ranked {nr}, top3 {nt} (sum {nr + nt} of 150 for untested_closes row 59; gameindex.tsv)"
              + ("  REACHED: tell Combat Analyser" if nr + nt >= 150 else "")]
    except Exception as e:  # noqa: BLE001
        L += ["", f"## Mite games since 2026-11-12T07:00Z: count failed ({e!r})"]
    oq = sorted(glob.glob(f"{REP}/**/owner_*question*.md", recursive=True), key=os.path.getmtime, reverse=True)
    L += ["", f"## Owner question files (owner_*question*.md): {len(oq)}"] + [f"- {p.replace(REP + '/', '')} ({iso(os.path.getmtime(p))})" for p in oq[:8]]
    df = sh("df -BG --output=avail,pcent /data /var | tail -2").split()
    hq = sh([sys.executable, "-I", f"{REPO}/tools/lab/homequota.py"]).strip().splitlines()[-1:] or ["?"]
    L += ["", "## Machine", f"- /data free {df[0] if df else '?'} ({df[1] if len(df) > 1 else '?'}); /var free {df[2] if len(df) > 2 else '?'} ({df[3] if len(df) > 3 else '?'})",
          f"- home (files used, soft, hard, MB, MB soft): {hq[0]}", f"- load {open('/proc/loadavg').read().split()[0]}"]
    kl = sh("KRB5CCNAME=FILE:/tmp/krb5cc_16910_sDVb1L klist 2>/dev/null | grep -m1 'renew until'").strip()
    try:
        td = [x.strip() for x in open("/data/USER/st/nudge/owner_todo.md") if x.strip().startswith("- ")]
    except OSError:
        td = []
    if td:
        L += ["", f"## Owner to-do (st/nudge/owner_todo.md): {len(td)}"] + [x[:250] for x in td[-6:]]
    try:
        ff = open(f"{BQ}/fix_form.log").read().split("\n")[-6:]
        L += ["", "## Fix-lane form (bq/fix_form.log: LEAN = BIG2-only h2h, no panel; STRICT when armq is empty)"] + ["- " + x for x in ff if x]
    except OSError:
        pass
    if kl:
        L.append(f"- kerberos {kl} (the owner runs kinit before then)")
    return "\n".join(L) + "\n"


def main():
    a = sys.argv[1:]
    every = int(a[a.index("--every") + 1]) if "--every" in a else 1800
    while True:
        try:
            txt = build()
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            open(OUT + ".tmp", "w").write(txt)
            os.replace(OUT + ".tmp", OUT)
        except Exception as e:  # noqa: BLE001
            print(f"daystate: {e!r}", file=sys.stderr, flush=True)
        if "--loop" not in a:
            return
        time.sleep(every)


if __name__ == "__main__":
    main()
