#!/usr/bin/env python3
"""closedby: how solid is a closure? (Tool Builder, 12 Nov; owner via the Coordinator: "ideas should always be tested before writing them off";
evidence_checklist_1112.md item 13: never close on argument, a prior, an estimate or a model; a count of the mechanism firing below its
pre-stated bar IS a test; a blind yardstick = 'untestable locally', not closed.)

kind(text) -> None when TEXT is not a closure, else one of:
  "played read"  a shipcheck / gate / inforead / screen with numbers (FAIL/PASS rows, n NNN, .5xxx points, h2h, fresh, LOS)
  "Step 0 count" a firing count against its pre-stated bar (Step 0, fires, firing, /g)
  "shadow"       a shadow or counterfactual row
  "untestable"   marked untestable locally (blind yardstick)
  "argument"     none of the above: closed on reasoning, a prior or an estimate (owner: these get a played test first)
An explicit "closed by: X" (or "CLOSED by X") in the text wins over the guess; the guess is marked "(auto)".

usage: python3 -I tools/lab/closedby.py "TEXT"            -> the kind
       python3 -I tools/lab/closedby.py --ledger [--argument]   every closure in bq/failure_chains.md with its kind (--argument: only those)
       python3 -I tools/lab/closedby.py --triage   writes condor-work/reports/closedby_triage_1112.md (post-triage status; daystate runs it)"""
import re
import sys

LEDGER = "/data/USER/st/bq/failure_chains.md"
CLOSE = re.compile(r"\bCLOSED\b|\bclosed\b|\bclose[sd]? (?:it|the line|for good)|\bKILL(?:ED)?\b|\bdropped\b|\bwritten off\b", re.I)
EXPL = re.compile(r"closed by[:\s]+([^;|]{3,60}?)(?=\s*(?:[;|]|$|\. |, ))", re.I)
PLAYED = re.compile(r"shipcheck|\bgate\b|inforead|\bscreen\b|\bh2h\b|\bfresh\b|\bLOS\b|\bFAIL\b|\bPASS\b|\bn ?\d{3,}|(?<![\d.])0?\.[3-6]\d{2,3}\b|\bz ?[+-]?\d|\bread\b.*\d|\bmaps\b"
                    r"|\b\d{2,5} (?:new|NEW|fresh)\b|\bx ?2\b|\bspar\b|nova_spar|\bre-?test\b|\bpuppet\b|\bdiag\b", re.I)  # 12 Nov (Coordinator): MSR '150 new msr-class x2 v nova_spar_fish' read as argument
STEP0 = re.compile(r"step ?0|\bfir(?:es|ing|ed)\b|/g\b|per game|count|\d(?:\.\d+)?%|\b(?:GO|KILL) row|prereg|cut stacks|cutprof|lineprof|fuelprof|measured", re.I)
SHADOW = re.compile(r"\bshadow\b|counterfactual|flag-on row", re.I)
UNTEST = re.compile(r"untestable|blind yardstick", re.I)


def kind(text):
    if not CLOSE.search(text):
        return None
    m = EXPL.search(text)
    if m:
        return m.group(1).strip()
    def said(rx, what):  # 12 Nov (owner via the Coordinator: the tag must say what test was played): quote the evidence it matched
        m = rx.search(text)
        if not m:
            return None
        a, b = max(0, m.start() - 25), min(len(text), m.end() + 25)
        return f"{what} (auto: '{' '.join(text[a:b].split())[:70]}')"
    for rx, what in ((UNTEST, "untestable"), (PLAYED, "played read"), (SHADOW, "shadow"), (STEP0, "Step 0 count")):
        k = said(rx, what)
        if k:
            return k
    return "argument (auto: no played test, count, shadow or diag found in the line)"


def is_argument(k):
    return bool(k) and k.lower().startswith("argument")


TRIAGE_SRC = "/homes/USER/condor-work/reports/untested_closes_1112.md"  # Planner's triage (A rows keyed by ledger line)
TRIAGE_AT = "2026-11-12T03:53"  # the Planner's triage of the 103 argument-closes (72 false hits, 14 superseded, 2 obsolete, 15 real = A1-A14)
TRIAGE_OUT = "/homes/USER/condor-work/reports/closedby_triage_1112.md"


def triage_report(out=TRIAGE_OUT):
    """12 Nov (Coordinator): the standing post-triage view, rewritten on each daystate refresh. Argument-closes in the ledger, each with its
    triage status: an A row of untested_closes_1112.md (by ledger line), 'triaged 03:53Z: not a real argument close' for older lines the
    Planner cleared, or UNTRIAGED for lines logged after the triage."""
    import os
    import time
    arows = {}
    try:
        for ln in open(TRIAGE_SRC, errors="replace"):
            m = re.match(r"\|\s*(A\d+)\s*\|\s*([\d/]+)\s+([^|]*)\|", ln)
            if m:
                for x in m.group(2).split("/"):
                    arows[int(x)] = (m.group(1), m.group(3).strip()[:70])
    except OSError:
        pass
    rows, un, ta, tc = [], 0, 0, 0
    for i, ln in enumerate(open(LEDGER, errors="replace"), 1):
        k = kind(ln)
        if not is_argument(k):
            continue
        st = re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d", ln)
        if i in arows:
            status = f"REAL argument close -> {arows[i][0]} (untested_closes_1112.md: {arows[i][1]})"
            ta += 1
        elif st and st.group(0) > TRIAGE_AT:
            status = "UNTRIAGED (logged after the 03:53Z triage)"
            un += 1
        else:
            status = "triaged 03:53Z (Planner): false hit / superseded / obsolete"
            tc += 1
        rows.append(f"| {i} | {status} | {ln.strip()[:150].replace('|', '/')} |")
    txt = [f"# Argument-closes in the failure ledger, post-triage (generated {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())} by tools/lab/closedby.py; daystate refresh)", "",
           f"Planner triage {TRIAGE_AT}Z of 103 lines: 72 false hits, 14 superseded, 2 obsolete, 15 real = A1-A14 (condor-work/reports/untested_closes_1112.md has each A row's test).",
           f"Now: {ta} line(s) on an A row, {tc} cleared by the triage, {un} UNTRIAGED (new since the triage: an analyst reads each; real ones get an A row).", "",
           "| ledger line | status | text |", "|---|---|---|"] + sorted(rows, key=lambda r: ("UNTRIAGED" not in r, "REAL" not in r))
    open(out + ".tmp", "w").write("\n".join(txt) + "\n")
    os.replace(out + ".tmp", out)
    return ta, tc, un


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "--triage":
        print(triage_report())
        return
    if a[0] == "--ledger":
        n = 0
        for i, ln in enumerate(open(LEDGER, errors="replace"), 1):
            k = kind(ln)
            if k and (not a[1:] or is_argument(k)):
                n += 1
                print(f"{i}: [{k}] {ln.strip()[:220]}")
        print(f"# {n} closure line(s)")
        return
    print(kind(" ".join(a)) or "not a closure")


if __name__ == "__main__":
    main()
