#!/usr/bin/env python3
"""ideas: ONE board for every idea in flight (owner 7 Nov: "make our workflow cleaner so we have to worry less about parallelised work and still
keep features that show positives"). It only reads; each state comes from the file that owns it:
  queued    armq's queue (bq/armq.txt), in arm order; diff lines arm on the recorded base (bq/diffbase.txt)
  testing   a shipcheck running now (shipwatch.log 'start' without 'ended', and its process alive)
  passed    shipcheck PASS in the window but not live (overtaken by a sibling's ship: re-read on the new base)
  shipped   in bq/live.txt (version)
  failed    shipcheck FAIL in the window, or armq.failed (a diff that does not build on the base, a smoke DISASTER ...)
  banked    an active entry of the failed-positive bank (flagscreen bank.tsv) or the fuel bank (bq/fuelbank.tsv): kept, re-read later
usage: python3 -I tools/lab/ideas.py [status] [--hours 24] [--all]    (--all: every bank entry, not only active)
       python3 -I tools/lab/ideas.py conflicts [--apply]                dry-apply every queued diff onto the current base: which no longer apply
                                                                        (--apply: they leave the queue for armq.failed; shipbake runs this)
"""
import json
import os
import re
import subprocess
import sys
import time

REPO = "/homes/USER/cambc"
LAB = f"{REPO}/tools/lab"
Q = "/data/USER/st/bq"
sys.path.insert(0, LAB)


def rd(p):
    try:
        return open(p, errors="replace").read()
    except OSError:
        return ""


def live_rows():
    out = {}
    for ln in rd(f"{Q}/live.txt").splitlines():
        a = ln.split()
        if len(a) >= 2:
            out.setdefault(a[1], a[0])
    return out


def checks(hours):
    """{bot: (state, tag, lane, when)} from shipwatch.log in the window"""
    since = time.time() - hours * 3600
    run, end = {}, {}
    for ln in rd(f"{Q}/shipwatch.log").splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)Z (start|ended) (\S+?):(?: shipcheck TAG=(\S+) LANE=(\S+))?(?: (\S+))?", ln)
        if not m:
            continue
        t = time.mktime(time.strptime(m[1], "%Y-%m-%d %H:%M:%S")) - time.timezone
        if t < since:
            continue
        if m[2] == "start":
            run[m[3]] = (m[4], m[5], m[1][11:16])
        else:
            end[m[3]] = (m[6] or "?", m[1][11:16])
    alive = subprocess.run(["pgrep", "-af", "[s]hipcheck.py nova_"], capture_output=True, text=True).stdout
    out = {}
    for b, (tag, lane, t0) in run.items():
        if b in end:
            out[b] = (end[b][0], tag, lane, end[b][1])
        elif f"shipcheck.py {b} " in alive:
            out[b] = ("testing", tag, lane, t0)
    return out


def flips_of(bot):
    m = re.search(r"^FLIPS=(.*)$", rd(f"{REPO}/bots/{bot}/FLIP"), re.M)
    return m.group(1).strip() if m else ""


def subject_of(bot):
    m = re.search(r"^SUBJECT=(.*)$", rd(f"{REPO}/bots/{bot}/SHIPCHECK"), re.M)
    return m.group(1).strip() if m else ""


def status(hours, every):
    live = live_rows()
    head = rd(f"{Q}/live.txt").split("\n")[0].split()
    base = rd(f"{Q}/diffbase.txt").split()
    print(f"# ideas board {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: live {head[0] if head else '?'} {head[1] if len(head) > 1 else ''}; "
          f"base {base[1] if len(base) > 1 and base[0] == (head[1] if len(head) > 1 else '') else 'NOT RECORDED for this live (lines wait)'}")
    rows = []
    for i, x in enumerate(rd(f"{Q}/armq.txt").splitlines()):
        try:
            q = json.loads(x)
        except ValueError:
            continue
        rows.append(("queued", f"#{i + 1}", q.get("slug") or "-", q.get("lane", "?"), q.get("flips") or "", q.get("donors", "-"), (q.get("subject") or "")[:60]))
    for b, (st, tag, lane, t) in sorted(checks(hours).items(), key=lambda x: x[1][3]):
        state = {"testing": "testing", "PASS": "shipped" if b in live else "passed", "FAIL": "failed"}.get(st, st.lower())
        ver = live.get(b, "")
        rows.append((state, tag or "", b, lane or "", flips_of(b), ver + (f" {t}" if t else ""), subject_of(b)[:60]))
    since = time.time() - hours * 3600
    for x in rd(f"{Q}/armq.failed").splitlines():
        try:
            q = json.loads(x)
        except ValueError:
            continue
        if q.get("t", 0) >= since:
            rows.append(("failed", "armq", q.get("slug") or "-", q.get("lane", "?"), q.get("flips") or "", q.get("donors", "-"),
                         re.sub(r"\s+", " ", q.get("why", ""))[:60]))
    try:
        import flagscreen
        for e in sorted(flagscreen.bank_load().values(), key=lambda e: -e.get("point", 0)):
            if e.get("state") == "active" or every:
                rows.append((f"banked/{e.get('state')}" if every else "banked", e["id"], e.get("bot") or e.get("donor") or "-", e.get("lane", "?"),
                             " ".join(f"{k}={v}" for k, v in e.get("flips", {}).items()), f"{e.get('point', 0):.4f} n{e.get('n') or 0}",
                             (e.get("cause", "") + " " + (e.get("fail") or ""))[:60]))
    except Exception as ex:  # noqa: BLE001
        rows.append(("banked", "?", f"bank unreadable: {ex}", "", "", "", ""))
    for ln in rd(f"{Q}/fuelbank.tsv").splitlines()[1:]:
        c = ln.split("\t")
        if len(c) > 3:
            rows.append(("banked", "fuel", c[0], c[1] if len(c) > 1 else "", c[2] if len(c) > 2 else "", "", "fuel bank: " + c[-1][:50]))
    order = {"testing": 0, "passed": 1, "queued": 2, "shipped": 3, "failed": 4}
    rows.sort(key=lambda r: (order.get(r[0].split("/")[0], 5),))
    w = [8, 6, 34, 9, 26, 22]
    print("  " + "  ".join(h.ljust(n) for h, n in zip(("state", "tag", "idea/bot", "lane", "flips", "version/read/donors"), w)) + "  subject / why")
    for r in rows:
        print("  " + "  ".join(str(c)[:n].ljust(n) for c, n in zip(r, w)) + "  " + str(r[6]))
    cnt = {}
    for r in rows:
        cnt[r[0].split("/")[0]] = cnt.get(r[0].split("/")[0], 0) + 1
    print("# " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: order.get(x[0], 5))) + f"  (last {hours} h; banks: active entries)")


def conflicts(apply=False):
    """every queued diff, dry-applied onto the recorded base in memory (armq's own 3-way merge): the ones that no longer apply.
    apply=True (shipbake runs it after each new base): those lines leave the queue for armq.failed with the conflicting files, so their
    agents rebase now, not when the line finally reaches the head"""
    import armq
    live = rd(f"{Q}/live.txt").split()[1]
    base = armq.diff_base(live)
    if not base:
        print(f"no base recorded for live {live} yet: nothing to check against")
        return 1
    bad = 0
    for x in rd(f"{Q}/armq.txt").splitlines():
        q = json.loads(x)
        ds = [d for d in (q.get("merged") or q.get("donors") or "-").split(",") if d and d != "-"]
        if not ds:
            continue
        try:
            armq.ensure_bots(ds)
            good, badd = armq.batch_chain(base, ds)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"  {q.get('slug') or '-':20s} not checked: {str(e)[:120]}")
            continue
        if badd:
            bad += 1
            why = f"diff model: does not apply on the new base {base}: " + "; ".join(f"{d}: {', '.join(c)}" for d, c in badd.items()) + " (rebase onto the base)"
            print(f"  {q.get('slug') or '-':20s} CONFLICT on {base}: " + "; ".join(f"{d}: {', '.join(c)}" for d, c in badd.items()))
            if apply:
                armq.edit(lambda ls, q=q: [y for y in ls if json.loads(y) != q])
                armq.fail(q, why)
                print(f"  {'':20s} -> off the queue, to armq.failed")
        else:
            print(f"  {q.get('slug') or '-':20s} applies cleanly on {base}")
    return 1 if bad else 0


def main():
    a = sys.argv[1:]
    hours = float(a[a.index("--hours") + 1]) if "--hours" in a else 24
    if a[:1] == ["conflicts"]:
        return conflicts("--apply" in a)
    status(hours, "--all" in a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
