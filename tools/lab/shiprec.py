#!/usr/bin/env python3
"""shiprec: write every record for the newest ship in one call (owner 7 Nov: fewer shell steps).
usage: python3 -I tools/lab/shiprec.py "WHAT CHANGED"     e.g. "FFW_BITS=5 (refused winning bag fights first)"
Reads line 1-2 of live.txt and the ship test output; updates best_model.txt, docs/version_history.md, CLAUDE.md §1,
the primer LIVE line and builder_queue.md. submissions_log.md is written by shipwatch. Refuses if the version is already recorded."""
import glob, os, re, sys, time

BQ = "/data/zw4424/st/bq"
REPO = "/homes/zw4424/cambc"
REP = "/homes/zw4424/condor-work/reports"


def g(s, k):
    m = re.search(k, s)
    return m.group(1) if m else None


def result(s, tag):
    """'Shipcheck TAG PASS: ...', or for a hand-submit (the newest verdict not PASS) 'HAND (shipcheck TAG INCONCLUSIVE): ...';
    fields the output lacks are left out (8 Nov, Builder: v617 vsr4i was recorded 'Shipcheck 2681 PASS' with '?' fields)"""
    vs = re.findall(r"OVERALL: (\w+)", s)
    verdict = vs[-1] if vs else None
    head = f"Shipcheck {tag} PASS" if verdict == "PASS" else f"HAND (shipcheck {tag} {verdict or 'no verdict'})"
    f = [("h2h", g(s, r"live h2h +([0-9.]+ .[0-9., ]+.)")), ("pooled", g(s, r"pooled BIG \+ fresh +([0-9.]+ .[0-9., ]+. n \d+)")),
         ("rare", g(s, r"rare changed maps +([0-9.]+ .[0-9., ]+. n \d+)")), ("fresh", g(s, r"fresh maps +CAND vs LIVE ([0-9.]+ .[0-9., ]+.)")),
         ("panel D", g(s, r"pooled D ([+-][0-9.]+)")), ("cap5 fuel", g(s, r"fuel exhaustions +cap5 [^(]*.([0-9.]+x)")),
         ("deaths", (g(s, r"death guard +BIG [^(]*.([+-][0-9.]+)") or "") and g(s, r"death guard +BIG [^(]*.([+-][0-9.]+)") + "/g BIG")]
    body = ", ".join(f"{k} {v}" for k, v in f if v)
    return (f"{head}: {body}." if body else f"{head}."), verdict == "PASS"


def main():
    # 8 Nov: `shiprec.py --help` (run to read the usage) wrote "vNNN + --help" into every record, three times (v605, v610, v613)
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help") or sys.argv[1].startswith("-") or not sys.argv[1].strip():
        print(__doc__)
        sys.exit(2)
    what = sys.argv[1]
    k = int(os.environ.get("SHIPREC_SKIP", "0"))  # 1 = record the ship before the newest
    a, b = open(f"{BQ}/live.txt").read().splitlines()[k:k + 2]
    v, bot, t = a.split()[:3]
    pv, pbot = b.split()[:2]
    best = f"{BQ}/best_model.txt"
    if open(best).read().startswith(v + " "):
        sys.exit(f"{v} already recorded")
    fs = sorted(glob.glob(f"{BQ}/shipwatch_{bot}_*.out"), key=os.path.getmtime)
    s = open(fs[-1], errors="replace").read() if fs else ""
    tag = fs[-1].rsplit("_", 1)[1][:-4] if fs else "none"
    tr = g(s, r"flip of (nova_\w+)")
    res, auto = result(s, tag)
    mode = "auto" if auto else "HAND"
    # 11 Nov (Coordinator): shipwatch passes WHAT already starting "vPREV + ", so the records read "v775 + v775 + ..."
    what = re.sub(rf"^\s*{re.escape(pv)}\s*\+\s*", "", what)
    try:  # 12 Nov ~20:5xZ (owner: "put percentage of maps each update affects"): tools/lab/affects.py's newest reading of this bot
        aff = [ln.rstrip("\n").split("\t") for ln in open(f"{BQ}/affects.tsv") if f"\t{bot}\t" in ln]
        aff = [p for p in aff if len(p) >= 6 and p[5]]
        if aff and "% of maps" not in what:
            p_ = aff[-1]  # 13 Nov (owner: "why does it keep saying 0% maps"): a fuel-only change shows its 100k cut-off change
            what = f"{what} [affects {p_[5]}% of maps" + (f"; fuel-only: cut-offs/game {p_[6]} at 100k" if float(p_[5]) == 0 and len(p_) >= 7 and p_[6] else "") + "]"
    except OSError:
        pass
    desc = f"{pv} + {what}"
    rb = pv[1:]
    x = open(best).read()
    open(best + ".new", "w").write(f"{v} {bot} {t} {desc}. {res} Rollback: submissions activate {rb}\n" + x)
    os.replace(best + ".new", best)
    p = f"{REPO}/docs/version_history.md"
    if os.path.exists(p):
        x = open(p).read()
        k = x.index(f"## {pv} ")
        open(p, "w").write(x[:k] + f"## {v} ({t}) bots/{bot}\n{desc}. {('TRUNK ' + tr + '. ') if tr else ''}{res} Rollback: activate {rb}.\n\n" + x[k:])
    p = f"{REPO}/CLAUDE.md"
    x = open(p).read()
    old = f"- **Live: bots/{pbot} = {pv}** ("
    if old in x:
        open(p, "w").write(x.replace(old, f"- **Live: bots/{bot} = {v}** ({mode} {t}{', TRUNK ' + tr if tr else ''}): {desc}. {res} Rollback: submissions activate {rb}.\n- **{pv}** = bots/{pbot} (", 1))
    else:
        # 9 Nov 21:50Z (Planner: §1 stuck at v665 while live was v669): shiprec was not run for v666/v667, so v668's run found no v667 line.
        # Replace whatever live line §1 has, and add a short bullet for every version in between, from live.txt.
        m = re.search(r"- \*\*Live: bots/(\S+) = (v\d+)\*\* \(", x)
        if not m:
            print("CLAUDE.md live line not found: fix by hand")
        else:
            seen = [ln.split() for ln in open("/data/zw4424/st/bq/live.txt") if ln.strip() and not ln.startswith("#")]
            have = int(m.group(2)[1:])
            gap = [s for s in seen if s[0].startswith("v") and s[0][1:].isdigit() and have < int(s[0][1:]) < int(v[1:])]
            mid = "".join(f"- **{s[0]}** = bots/{s[1]} ({s[2] if len(s) > 2 else '?'}; shiprec was not run for it: see builder_queue.md)\n" for s in gap)
            new = (f"- **Live: bots/{bot} = {v}** ({mode} {t}{', TRUNK ' + tr if tr else ''}): {desc}. {res} Rollback: submissions activate {rb}.\n"
                   + mid + f"- **{m.group(2)}** = bots/{m.group(1)} (")
            open(p, "w").write(x[:m.start()] + new + x[m.end():])
            print(f"CLAUDE.md: live line moved from {m.group(2)} to {v}" + (f" ({len(gap)} skipped version(s) added)" if gap else ""))
    # owner 8 Nov: CLAUDE.md keeps only the newest 3 version bullets; the rest are in docs/version_history.md
    p2 = f"{REPO}/CLAUDE.md"
    n, out = 0, []
    for ln in open(p2).read().split("\n"):
        if re.match(r"- \*\*v\d+\*\* = bots/", ln):
            n += 1
            if n > 3:
                continue
        out.append(ln)
    open(p2, "w").write("\n".join(out))
    p = f"{REP}/subagent_primer.md"
    x = trim_primer_live(open(p).read().rstrip("\n"), keep=2)
    open(p, "w").write(x + f"\nLIVE {v} = {bot} ({t}): {desc}{' on TRUNK ' + tr if tr else ''}. Build on it.\n")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    open(f"{REP}/builder_queue.md", "a").write(f"{now} SHIP {v} {bot} ({t}): {desc}. {res}\n")
    print(v, res)


def trim_primer_live(text, keep):
    """8 Nov: every ship appended a LIVE line (123 lines, most naming bots long gone, under a heading that says 'only the newest'). Keep the newest KEEP; the rest go to the archive."""
    lines = text.split("\n")
    live = [i for i, ln in enumerate(lines) if ln.startswith("LIVE v")]
    drop = set(live[:-keep] if keep else live)
    if drop:
        with open(f"{REP}/subagent_primer_full_1105.md", "a") as f:
            f.write("\n".join(lines[i] for i in sorted(drop)) + "\n")
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


def fpsites_bg():
    """12 Nov (Planner, failed-positive bank rule (b)): after each ship, tools/lab/fpsites.py checks in the background whether the ship touched
    a banked idea's functions (hits -> bq/fpsites.alarm, shown by since.py and healthwatch)."""
    import subprocess
    try:
        subprocess.Popen(["nice", "-n", "10", sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fpsites.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


if __name__ == "__main__":
    main()
    fpsites_bg()
