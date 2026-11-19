#!/usr/bin/env python3
"""verdict: ONE verdict per idea from every independent read of it, pooled (b1463 audit, 7 Nov: the same evidence shipped and closed
depending on which brief's bar was used; a kill by .0017 on one read; arming on one top read).

usage: python3 -I tools/lab/verdict.py idea KEY [KEY ...] [--since 2026-11-07] [--json OUT]
       python3 -I tools/lab/verdict.py read SPEC [SPEC ...] [--json OUT]
  idea  finds the reads whose candidate matches every KEY (a flip like BH81_BITS=9, matched as a whole token, or a bot name or part):
          smokefarm  /data/zw4424/st/smoke/TAG/rows.json   (row label = BASE+FLIPS)
          inforead   /data/zw4424/st/info/TAG/result.txt   (cand bot name and its FLIP file)
          shipcheck  /data/zw4424/st/bq/shipwatch_BOT_TAG.out  (bot name and its FLIP file; the deciding pooled row, the largest n)
        a bot's FLIP file is read from bots/BOT/FLIP (or the idea store's copy is not looked up: retired bots match by name only).
  read  explicit reads: smoke:TAG[:LABEL-PART]  info:TAG  sc:BOT_TAG (the shipwatch .out stem after 'shipwatch_')
        or raw:POINT,LO,HI,N[,changed]
Pooled = inverse-variance over reads (se from each 95% CI); reads on changed maps only (smokefarm --changed, RARE) are pooled apart
from whole-pool reads: a whole-pool d means d/share on changed maps, so the two scales are not mixed.
Verdict (whole-pool pool, else the changed pool):
  GAIN        pooled lower bound > .50
  HARM        pooled upper bound < .50
  UNRESOLVED  otherwise; 'no harm >= .005 shown' when the lower bound >= .495 (a rule-verified fix then goes to the bank with
              reason POWER, not CLOSED: flagscreen.py bank add ... --reason POWER)
  n80         maps for 80% power at the observed effect (two-sided 5%; sigma .245 a map, the measured map-pair sd)
  het         Cochran Q and I^2 over the reads: I^2 >= 50% says the reads disagree more than chance (different bases, maps or a
              wrong read); look before trusting the pool.
Caveat: reads that share maps (a shipcheck that adopted a gate read, BIG reused by killgate) are not independent; identical
(point, n) reads are counted once, but the pooled se is still a lower bound when maps overlap. Decides nothing by itself: the bars
in shipcheck still ship (primer RULE CONFIRM-READ: a passed screen does not decide).
"""
import glob
import json
import math
import os
import re
import sys
import time

REPO = "/homes/zw4424/cambc"
SMOKE, INFO, BQ = "/data/zw4424/st/smoke", "/data/zw4424/st/info", "/data/zw4424/st/bq"
SIGMA = 0.245
CI = re.compile(r"(0\.\d{3,4}) \[(0\.\d{3,4}), (0\.\d{3,4})\]")


def flips_of(bot):
    try:
        return open(os.path.join(REPO, "bots", bot, "FLIP")).read()
    except OSError:
        return ""


def mk(src, point, lo, hi, n, scale="whole", note=""):
    se = max((hi - lo) / (2 * 1.96), 1e-6)
    return dict(src=src, point=point, lo=lo, hi=hi, n=int(n), se=se, scale=scale, note=note)


def smoke_reads(tag, part=None):
    d = os.path.join(SMOKE, tag)
    try:
        rows = json.load(open(os.path.join(d, "rows.json")))
    except (OSError, ValueError):
        return []
    scale = "changed" if os.path.isdir(os.path.join(d, "changed")) else "whole"
    out = []
    for r in rows:
        if not r.get("n") or "score" not in r or (part and part not in r["label"]):
            continue
        out.append(mk(f"smoke:{tag} {r['label'][:60]}", r["score"], r["lo"], r["hi"], r["n"], scale,
                      ("stopped: " + r["stopped"]) if r.get("stopped") else ""))
    return out


def info_reads(tag):
    try:
        txt = open(os.path.join(INFO, tag, "result.txt")).read()
    except OSError:
        return []
    m = re.search(r"h2h " + CI.pattern + r" n(\d+)", txt)
    if not m:
        return []
    try:
        cmd = json.load(open(os.path.join(INFO, tag, "cmd.json")))
    except (OSError, ValueError):
        cmd = {}
    scale = "changed" if cmd.get("changed") or cmd.get("draft_changed") else "whole"
    return [mk(f"info:{tag} {cmd.get('cand', '?')} v {cmd.get('base', '?')}", float(m[1]), float(m[2]), float(m[3]), m[4], scale)]


def sc_reads(stem):
    p = os.path.join(BQ, f"shipwatch_{stem}.out")
    try:
        lines = open(p, errors="replace").read().splitlines()
    except OSError:
        return []
    best = None
    rare = any("RARE" in x or "changed-map read" in x for x in lines[:80])
    for x in lines:
        if not re.search(r"live h2h|pooled|changed maps", x):
            continue
        m = re.search(CI.pattern + r" n ?(\d+)", x)
        if m and (best is None or int(m[4]) > best[3]):
            best = (float(m[1]), float(m[2]), float(m[3]), int(m[4]))
    if not best:
        return []
    verdict = next((x.split()[-1] for x in reversed(lines) if re.search(r"\b(PASS|FAIL|INCONCLUSIVE|VACUOUS)\b\s*$", x)), "")
    return [mk(f"sc:{stem}", *best, scale="changed" if rare else "whole", note=verdict)]


def parse_spec(s):
    kind, _, rest = s.partition(":")
    if kind == "smoke":
        tag, _, part = rest.partition(":")
        return smoke_reads(tag, part or None)
    if kind == "info":
        return info_reads(rest)
    if kind == "sc":
        return sc_reads(rest)
    if kind == "raw":
        v = rest.split(",")
        return [mk(f"raw:{rest}", float(v[0]), float(v[1]), float(v[2]), int(v[3]), "changed" if len(v) > 4 and v[4] == "changed" else "whole")]
    sys.exit(f"verdict: unknown read {s!r} (smoke:TAG[:PART] info:TAG sc:BOT_TAG raw:P,LO,HI,N[,changed])")


def find(keys, since):
    pats = [re.compile(r"(?<![A-Za-z0-9_])" + re.escape(k) + r"(?![0-9])") if "=" in k else None for k in keys]

    def hit(*texts):  # a flip key (F=V) matches as a whole token: BH81_BITS=1 is not BH81_BITS=12; other keys as substrings
        t = " ".join(texts)
        return all((p.search(t) if p else k in t) for k, p in zip(keys, pats))
    out = []
    for d in glob.glob(os.path.join(SMOKE, "*", "rows.json")):
        if os.path.getmtime(d) < since:
            continue
        tag = d.split("/")[-2]
        for r in smoke_reads(tag):
            if hit(r["src"]):
                out.append(r)
    for d in glob.glob(os.path.join(INFO, "*", "result.txt")):
        if os.path.getmtime(d) < since:
            continue
        tag = d.split("/")[-2]
        try:
            cand = json.load(open(os.path.join(INFO, tag, "cmd.json"))).get("cand", "")
        except (OSError, ValueError):
            cand = ""
        if cand and hit(cand, flips_of(cand)):
            out += info_reads(tag)
    for p in glob.glob(os.path.join(BQ, "shipwatch_nova_*_*.out")):
        if os.path.getmtime(p) < since:
            continue
        stem = os.path.basename(p)[len("shipwatch_"):-len(".out")]
        bot = stem.rsplit("_", 1)[0]
        if hit(bot, flips_of(bot)):
            out += sc_reads(stem)
    return out


def pool(rs):
    if not rs:
        return None
    w = [1 / r["se"] ** 2 for r in rs]
    mu = sum(wi * r["point"] for wi, r in zip(w, rs)) / sum(w)
    se = math.sqrt(1 / sum(w))
    q = sum(wi * (r["point"] - mu) ** 2 for wi, r in zip(w, rs))
    i2 = max(0.0, (q - (len(rs) - 1)) / q) if q > 0 else 0.0
    d = abs(mu - 0.5)
    n80 = math.ceil(((1.96 + 0.8416) * SIGMA / d) ** 2) if d > 1e-9 else None
    return dict(point=mu, lo=mu - 1.96 * se, hi=mu + 1.96 * se, se=se, n=sum(r["n"] for r in rs), reads=len(rs), q=q, i2=i2, n80=n80)


def word(p):
    if p["lo"] > 0.5:
        return "GAIN"
    if p["hi"] < 0.5:
        return "HARM"
    return "UNRESOLVED" + (" (no harm >= .005 shown)" if p["lo"] >= 0.495 else "")


def report(rs, title):
    seen, uniq = set(), []
    for r in rs:
        k = (round(r["point"], 4), r["n"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    print(f"# verdict {title} ({time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}): {len(uniq)} read(s)"
          + (f", {len(rs) - len(uniq)} duplicate(s) dropped" if len(rs) > len(uniq) else ""))
    for r in uniq:
        print(f"  {r['scale']:7s} {r['point']:.4f} [{r['lo']:.4f}, {r['hi']:.4f}] n {r['n']:6d}  {r['src']}" + (f"  ({r['note']})" if r["note"] else ""))
    res = {}
    for sc in ("whole", "changed"):
        p = pool([r for r in uniq if r["scale"] == sc])
        if not p:
            continue
        res[sc] = dict(p, verdict=word(p))
        print(f"POOLED {sc:7s} {p['point']:.4f} [{p['lo']:.4f}, {p['hi']:.4f}] n {p['n']} over {p['reads']} read(s): {word(p)}; "
              f"n80 {p['n80'] if p['n80'] else 'inf'} maps at the observed effect {p['point'] - 0.5:+.4f}; "
              f"het Q {p['q']:.1f} I2 {100 * p['i2']:.0f}%" + ("  READS DISAGREE: look before trusting the pool" if p["i2"] >= 0.5 and p["reads"] > 1 else ""))
    if not res:
        print("no reads found")
    top = res.get("whole") or res.get("changed")
    print(f"VERDICT {top['verdict'] if top else 'NO READS'}")
    return dict(reads=uniq, pooled=res, verdict=top["verdict"] if top else None)


def main():
    a = sys.argv[1:]
    js = None
    if "--json" in a:
        i = a.index("--json")
        js = a[i + 1]
        del a[i:i + 2]
    since = 0.0
    if "--since" in a:
        i = a.index("--since")
        since = time.mktime(time.strptime(a[i + 1][:10], "%Y-%m-%d")) - time.timezone
        del a[i:i + 2]
    if len(a) < 2 or a[0] not in ("idea", "read"):
        sys.exit(__doc__)
    rs = find(a[1:], since) if a[0] == "idea" else [r for s in a[1:] for r in parse_spec(s)]
    out = report(rs, " ".join(a[1:]))
    if js:
        json.dump(out, open(js, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
