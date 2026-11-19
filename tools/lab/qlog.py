#!/usr/bin/env python3
"""qlog: append one timestamped line to a Builder log, so logging is one allowlisted command (owner 7 Nov: fewer permission prompts).
Restored 10 Nov by the Tool Builder (the 7 Nov file was lost; ~160 agent calls hit "qlog.py doesn't exist" since).

  python3 -I tools/lab/qlog.py queue  "TEXT"        -> condor-work/reports/builder_queue.md   ("- STAMP TEXT")
  python3 -I tools/lab/qlog.py prereg bNNN "TEXT"   -> /data/zw4424/st/bNNN/prereg.md (CLAUDE.md §3) AND builder_queue.md ("- STAMP bNNN PREREG: TEXT")
  python3 -I tools/lab/qlog.py chains "TEXT"        -> /data/zw4424/st/bq/failure_chains.md   ("| STAMP | TEXT")  TEXT holds the rest of the row
    (12 Nov: a chains/queue line that closes an idea gets " | closed by: KIND" (closedby.py) unless it names one itself)
  python3 -I tools/lab/qlog.py ideas  "TEXT"        -> condor-work/reports/idea_queue.md      ("| STAMP | TEXT")
  python3 -I tools/lab/qlog.py errors "TEXT"        -> docs/bot_errors.md                     ("| STAMP | TEXT")

Only appends; never rewrites. The stamp comes from the clock (CLAUDE.md: never type time stamps).
"""
import datetime
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUEUE = os.path.join(REPO, "condor-work", "reports", "builder_queue.md")
LOGS = {
    "queue": (QUEUE, "- {s} {t}"),
    "chains": ("/data/zw4424/st/bq/failure_chains.md", "| {s} | {t}"),
    "ideas": (os.path.join(REPO, "condor-work", "reports", "idea_queue.md"), "| {s} | {t}"),
    "errors": (os.path.join(REPO, "docs", "bot_errors.md"), "| {s} | {t}"),
}


def append(path, line):
    with open(path, "a") as f:
        f.write(line + "\n")


def main():
    a = sys.argv[1:]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if len(a) == 3 and a[0] == "prereg" and re.fullmatch(r"b\d+", a[1]) and a[2].strip():
        text = " ".join(a[2].split("\n")).strip()
        d = f"/data/zw4424/st/{a[1]}"
        os.makedirs(d, exist_ok=True)
        append(f"{d}/prereg.md", f"- {stamp} {text}")
        append(QUEUE, f"- {stamp} {a[1]} PREREG: {text}")
        print(f"qlog prereg: {d}/prereg.md + builder_queue.md, {len(text)} chars, {stamp}")
        return 0
    if len(a) != 2 or a[0] not in LOGS or not a[1].strip():
        sys.stderr.write(__doc__)
        return 2
    path, fmt = LOGS[a[0]]
    if not os.path.exists(path):
        sys.stderr.write(f"qlog: {path} missing\n")
        return 1
    text = " ".join(a[1].split("\n")).strip()
    if a[0] in ("chains", "queue"):  # 12 Nov (owner: "ideas should always be tested before writing them off"): a closure names how it closed
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import closedby
            kd = closedby.kind(text)
            if kd and not closedby.EXPL.search(text):
                text += f" | closed by: {kd}"
            if closedby.is_argument(kd):
                sys.stderr.write("qlog: this closure names no played test (closed by: argument). Owner 12 Nov: run the smallest real test first "
                                 "(Step 0 count, shadow, local read or shipcheck) or write 'untestable locally' (evidence_checklist item 13).\n")
        except Exception:  # noqa: BLE001  logging never fails on the classifier
            pass
    append(path, fmt.format(s=stamp, t=text))
    print(f"qlog {a[0]}: {len(text)} chars, {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
