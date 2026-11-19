#!/usr/bin/env python3
"""closedq: queued pilot batches that belong to CLOSED ideas (Tool Builder, 10 Nov; Coordinator: "closed ideas must not keep eating the pool").
  python3 -I tools/lab/closedq.py [--cancel]
Closed set: pipe.py --json rows with stage FAIL / closed (last 48 h). For each queued/claimed pilot batch, the text searched is its id, its owner
process's cmdline + cwd and its stage manifest's bot names; a batch matches a closed code when the code appears as a whole token (case-insensitive,
e.g. nova_dg_b1813hcf -> HCF). Never matched: batches of a running shipcheck, pilot_top lines, or anything named in a PENDING line of
pending_reads.txt. Prints: code | batch | items | owner pid | why. --cancel: pilotd.cancel(batch) for each match (queued items deleted, running ones
killed by pilotd) and logs to bq/closedq.log. Hourly unit nova-closedq runs it WITHOUT --cancel and writes bq/closedq.alarm when matches exist."""
import glob
import json
import os
import re
import subprocess
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
Q = "/homes/zw4424/condor-runs/pilotq"
BQ = "/data/zw4424/st/bq"


def closed_codes():
    r = subprocess.run([sys.executable, "-I", os.path.join(LAB, "pipe.py"), "--json", "--since", "48", "--all"], capture_output=True, text=True, timeout=120)
    try:
        rows = json.loads(r.stdout)
        rows = rows.get("rows", []) if isinstance(rows, dict) else rows
    except ValueError:
        return {}
    return {x["idea"]: x for x in rows if str(x.get("stage", "")).upper().startswith(("FAIL", "CLOSED"))}


def reopened(codes):
    """10 Nov (TB 6ad907: FWV armed again, PEEL retest arms running, both flagged): codes with newer activity than their close. Signals:
    a waiting armq line, an armq 'arming' line or a builder_queue PREREG/ARMED line in the last 6 h, or a running shipcheck of a bot whose
    slug carries the code. Such a code is treated as open."""
    txt = []
    cut = time.time() - 6 * 3600
    for p in ("/data/zw4424/st/bq/armq.txt",):
        try:
            txt.append(open(p, errors="replace").read())
        except OSError:
            pass
    for p, pat in (("/data/zw4424/st/bq/armq.log", "arming:"), ("/homes/zw4424/cambc/condor-work/reports/builder_queue.md", "PREREG")):
        try:
            with open(p, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 400000))
                for ln in fh.read().decode(errors="replace").splitlines():
                    m = re.match(r"(?:- )?(\d{4}-\d\d-\d\dT\d\d:\d\d)", ln)
                    if (pat in ln or "ARMED" in ln) and m and time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M")) - time.timezone >= cut:
                        txt.append(ln)
        except OSError:
            pass
    for c in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            a = open(c).read().split("\0")
            if any(x.endswith(("shipcheck.py", "prearm.py", "armq.py")) for x in a):
                txt.append(" ".join(a))
        except OSError:
            pass
    low = re.sub(r"[_\-./:]", " ", "\n".join(txt).lower())
    return {k for k in codes if re.search(r"(?<![a-z])" + re.escape(k.lower()) + r"\d*[a-z]{0,3}\b", low)}


def batches():
    B = {}
    for sub in ("queue", "claimed"):
        for n in os.listdir(os.path.join(Q, sub)):
            if n.startswith("."):
                continue
            b = re.sub(r"_\d+(_g)?(\..*)?$", "", re.sub(r"^\d+_\d+_", "", n))
            e = B.setdefault(b, dict(n=0, run="", pid="", txt="" if b.startswith(("stage-", "prun-")) else b))  # hex ids gave false hits (stage-593ece -> ECE)
            e["n"] += 1
            if e["run"]:
                continue
            try:
                run = json.load(open(os.path.join(Q, sub, n))).get("run", "")
            except (OSError, ValueError):
                continue
            e["run"] = run
            m = re.search(r"/(?:cf_|\d{8}T\d{6}Z?_)(\d+)(?:_\w+)?$", run)
            if m:
                e["pid"] = m[1]
                try:
                    e["txt"] += " " + open(f"/proc/{m[1]}/cmdline").read().replace("\0", " ") + " " + os.readlink(f"/proc/{m[1]}/cwd")
                except OSError:
                    pass
            for mf in glob.glob(run + "/manifest_0.txt")[:1]:
                try:
                    e["txt"] += " " + " ".join(re.findall(r"bots/(\S+)", open(mf).read()[:3000]))
                except OSError:
                    pass
    return B


def last_claim(bid):
    """UTC HH:MM of the batch's newest run/done line in the pilot logs, or 'never'."""
    best = ""
    for p in glob.glob(os.path.join(Q, "logs", "*")):
        try:
            for ln in open(p, errors="replace"):
                if bid in ln and (" run " in ln or " done " in ln) and ln[:20] > best:
                    best = ln[:20]
        except OSError:
            pass
    return best[11:16] + "Z" if best else "never claimed"


def protected():
    txt = ""
    for p in (os.path.join(BQ, "pending_reads.txt"), os.path.join(BQ, "pilot_top.txt")):
        try:
            txt += "\n".join(ln for ln in open(p, errors="replace") if not ln.startswith("DONE")) + "\n"
        except OSError:
            pass
    tags = set()
    for c in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            a = open(c).read().split("\0")
            if any(x.endswith("shipcheck.py") for x in a):
                tags.update(x for x in a if re.fullmatch(r"\d{4,6}", x))
        except OSError:
            pass
    # 12 Nov (Builder: 'TCD stage-7b1dd1' was tte5s's trunk-code gate, tag tcd2ef..., flagged as a closed idea): a running shipcheck's
    # trunk-code gate runs under its own tc tag; those tags (named in the check's .out) protect the batches whose owner text holds them
    for t in list(tags):
        for o in glob.glob(os.path.join(BQ, f"shipwatch_*_{t}.out")):
            try:
                tags.update(re.findall(r"gate (tc[0-9a-f]{20})", open(o, errors="replace").read(30000)))
            except OSError:
                pass
    return txt, tags


def main():
    cancel = "--cancel" in sys.argv
    codes = closed_codes()
    reop = reopened(codes)
    codes = {k: v for k, v in codes.items() if k not in reop}
    ptxt, tags = protected()
    hits = []
    for b, e in batches().items():
        if any(t in b or (t.startswith("tc") and t in e["txt"]) for t in tags):
            continue
        low = e["txt"].lower()
        # 11 Nov: batch-id hash suffixes (6 hex, e.g. ...-932afd, ...-21ce19) and gate hashes (12+ hex) matched closed codes AFD, CE1:
        # a token of 6 or 12+ hex characters with both a digit and a letter is a hash, never an idea code
        low = re.sub(r"(?<![0-9a-z])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])([0-9a-f]{6}|[0-9a-f]{12,})(?![0-9a-z])", " ", low)
        for code in codes:
            c = code.lower()
            if len(c) < 3 or not re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", re.sub(r"[_\-./]", " ", low).replace(" b1", " b1 ")) \
                    and not re.search(r"(?:b\d{4}|dg_?)" + re.escape(c) + r"(?![a-z])", low):
                continue
            if b in ptxt or (e["pid"] and e["pid"] in ptxt):
                continue
            own = re.search(r"/data/zw4424/st/([A-Za-z0-9_]+)/", e["txt"]) or re.search(r"nova_(?:dg_|dgfc_)?(b1\d{3})_", e["txt"])
            if own and own.group(1).startswith(("climb", "crit", "plat", "tb", "gamesum", "livepipe")):
                break  # infrastructure runs (ladder climb puppets, triage, tool tests) are never an idea's batch
            hits.append((code, b, e["n"], e["pid"], (own.group(1) if own else "?"), last_claim(b), codes[code].get("last", "")[:70]))
            break
    for h in hits:
        print(" | ".join(map(str, h)))
    print(f"closedq: {len(hits)} batch(es), {sum(h[2] for h in hits)} item(s) of closed ideas ({len(codes)} closed codes in 48 h)")
    al = os.path.join(BQ, "closedq.alarm")
    if hits and not cancel:
        open(al, "w").write(f"ALARM closedq: {len(hits)} queued batch(es) of closed ideas ({sum(h[2] for h in hits)} items; report only, a human confirms): "
                            + ", ".join(f"{h[0]} {h[1]} ({h[2]} items, owner {h[4]}, last claim {h[5]})" for h in hits[:6])
                            + "  (cancel one: tools/lab/closedq.py --cancel --only BATCH)\n")
    elif os.path.exists(al):
        os.remove(al)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    if cancel and only:  # 10 Nov (Coordinator): cancel only the batch a human confirmed
        hits = [h for h in hits if h[1] == only]
    elif cancel:
        sys.exit("closedq: --cancel needs --only BATCH (a human confirms each one)")
    if cancel and hits:
        sys.path.insert(0, LAB)
        import pilotd
        with open(os.path.join(BQ, "closedq.log"), "a") as f:
            for h in hits:
                pilotd.cancel(h[1])
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} cancelled {h[1]} ({h[2]} items) of closed {h[0]}\n")
        print("cancelled", len(hits))


if __name__ == "__main__":
    main()
