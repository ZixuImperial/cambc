#!/usr/bin/env python3
"""digest: any result in 1-3 lines, so sessions don't read raw verdicts and logs (owner 5 Nov: spend fewer tokens).
usage: python3 -I tools/lab/digest.py WHAT [WHAT ...] [--rows]
  WHAT: a shipcheck TAG (1422), a gate/killgate/inforead TAG (tc8f..., irb1201_05030913, driftv503), a condab run NAME
        (nullbrn1big), or a file path (a shipwatch_*.out, verdict.txt, result.txt, *.condor.txt, or any log).
  --rows: also print every non-PASS row in full (still one line each). --full: no compaction (nova_ prefixes, timestamps,
          inforead per-spar detail kept).
Reads: shipcheck/gate tables (OVERALL + the rows that did not pass + the main scores), killgate verdicts (verdict + last
look), inforead results (their summary line), condab summaries (ALL row, changed maps, games), other logs (the last '!!'
line and the last line). Used by tools/lab/since.py."""
import glob
import os
import re
import sys

BQ = "/data/USER/st/bq"
ST = "/data/USER/st"
W = 220  # max characters a line


def cut(s, w=W):
    s = re.sub(r"\s+", " ", s.strip())
    return s if len(s) <= w else s[:w - 3] + "..."


def resolve(what):
    """-> path of the result file for WHAT, or None."""
    if os.path.exists(what):
        return what
    c = []
    if what.isdigit():
        c += sorted(glob.glob(f"{BQ}/shipwatch_*_{what}.out"), key=os.path.getmtime)[-1:]
    c += [f"{ST}/gate/{what}/verdict.txt", f"{ST}/kg/{what}/verdict.txt", f"{ST}/info/{what}/result.txt",
          f"{BQ}/{what}.condor.txt", f"{ST}/gate/{what}.log"]
    for p in c:
        if os.path.exists(p):
            return p
    return None


TABLE_ROW = re.compile(r"^  (\S.*\S)\s+(PASS|FAIL|INCONCLUSIVE|info|EXT|SKIP)\s*$")


def table(lines, head, rows_too):
    """shipcheck / gate verdict table -> lines."""
    overall = next((m.group(1) for ln in lines if (m := re.match(r"^\s*OVERALL: *(\S+)", ln))), "running")
    rows = []
    for ln in lines:
        m = TABLE_ROW.match(ln)
        if not m or m.group(1).startswith(("leg ", "OVERALL")):
            continue
        body = m.group(1)
        k = re.search(r"\s{2,}", body) or re.search(r" (?=[+-]?\d)", body)  # name, then 2+ spaces or the first number
        name, val = (body[:k.start()], body[k.end():]) if k else (body, "")
        rows.append((name.strip(), val, m.group(2)))
    key = {}
    for name, val, _ in rows:
        n = name.lower()
        nums = re.findall(r"\d\.\d{3,4}", val)
        if not nums:
            continue
        if n.startswith(("live h2h", "big")):
            key["BIG"] = nums[0]
        elif n.startswith("fresh"):
            key["fresh"] = nums[0] + (f" n{m.group(1)}" if (m := re.search(r"over (\d+) maps", val)) else "")
        elif n.startswith("pooled"):
            key["pooled"] = nums[0] + (f" z{z.group(1)}" if (z := re.search(r"z ([+-]?\d+\.\d+)", val)) else "")
        elif n.startswith("playstyle"):
            d = re.search(r"D ([+-]\d\.\d{3})", val)
            if d:
                key["panel"] = d.group(1)
    bad = [(n, v, s) for n, v, s in rows if s in ("FAIL", "INCONCLUSIVE")]
    out = [cut(f"{head}: {overall}" + (" | " + ", ".join(f"{k} {v}" for k, v in key.items()) if key else "")
               + (" | not passed: " + "; ".join(f"{n} {s}" for n, _, s in bad) if bad else ""))]
    for n, v, s in (bad if rows_too else bad[:2]):
        out.append(cut(f"  {n}: {v} -> {s}"))
    return out


def short(ln):
    """compact a digest line: no 'nova_' prefixes, no timestamps, inforead lines cut to h2h / third-party D / fuel."""
    ln = re.sub(r"\bnova_", "", ln)
    ln = re.sub(r" \(20\d\d-\d\d-\d\dT[0-9:]+Z\)", "", ln)
    ln = ln.replace(" vs live ", " v ").replace(" vs ", " v ").replace("INFO READ ", "read ")
    m = re.match(r"(read \S+: \S+ v \S+): h2h (\S+ \[\S+ \S+\]) (n\d+); third-party D (\S+) \[\S+ \S+\] n\d+; fuel (\S+( FAIL)?)", ln)
    if m:
        ln = f"{m.group(1)}: h2h {m.group(2)} {m.group(3)}, D {m.group(4)}, fuel {m.group(5)}"
    return ln


def digest(path, rows_too=False, full=False):
    if not full:
        return [short(x) for x in digest(path, rows_too, True)]
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError as e:
        return [f"{path}: {e}"]
    if not lines:
        return [f"{os.path.basename(path)}: empty"]
    base = os.path.basename(path)
    sc = next((ln for ln in lines if ln.startswith("SHIPCHECK ")), None)
    if sc:
        head = re.sub(r",? wall .*", "", sc)
        out = table(lines, head, rows_too)
        sub = next((ln for ln in reversed(lines) if re.search(r"^SUBMITTED|no submit|submit exit [1-9]|NOT SUBMITTED", ln)), None)
        if sub:
            out[0] = cut(out[0] + " | " + re.sub(r"^\d\d:\d\d:\d\d ", "", sub), W + 60)
        return out
    if lines[0].startswith("GATE "):
        return table(lines, re.sub(r", \d{4}-\d\d-\d\d .*", "", lines[0]), rows_too)
    if lines[0].startswith("# INFO READ") or base == "result.txt":
        return [cut(lines[0].lstrip("# ") + ": " + (lines[1] if len(lines) > 1 else ""), W + 80)]
    kg = next((ln for ln in lines if ln.startswith("KILLGATE ")), None)
    if kg:
        v = next((ln for ln in lines if ln.startswith("VERDICT")), "VERDICT: running")
        look = [ln for ln in lines if re.match(r"^ +\d+ 0\.\d+ \[", ln)]
        g = next((ln for ln in lines if ln.startswith("games:")), "")
        return [cut(f"{re.sub(r' *[(].*', '', kg)}: {v[8:].strip()}"
                    + (f" | last look {look[-1].split()[0]} maps {look[-1].split()[1]} {look[-1].split()[2]}{look[-1].split()[3]}" if look else "")
                    + (f" | {g.split(';')[0][7:]}" if g else ""))]
    if lines[0].startswith("# condab "):
        allr = next((ln for ln in lines if re.match(r"^  ALL ", ln)), "")
        ch = next((ln for ln in lines if ln.strip().startswith("changed")), "")
        gm = next((ln for ln in lines if ln.startswith("games:")), "")
        sc_ = re.search(r"score (\S+ \[\S+ \S+\])", allr)
        return [cut(f"{re.sub(r' *[(].*?[)]|, SET .*', '', lines[0][2:])}: ALL {sc_.group(1) if sc_ else '?'}"
                    + (f" over {re.search(r'ALL +(\d+) maps', allr).group(1)} maps" if allr else "")
                    + (f" | {ch.strip().split(' (')[0]}" if ch else "") + (f" | {gm.split(';')[0][7:]}" if gm else ""))]
    bang = [ln for ln in lines if "!!" in ln]
    out = [cut(f"{base}: {lines[-1]}")]
    if bang and bang[-1] != lines[-1]:
        out.append(cut(f"  last !!: {bang[-1]}"))
    return out


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    rows_too, full = "--rows" in a, "--full" in a
    for w in [x for x in a if not x.startswith("--")]:
        p = resolve(w)
        print("\n".join(digest(p, rows_too, full)) if p else f"{w}: no result file found")


if __name__ == "__main__":
    main()
