#!/usr/bin/env python3
"""draftcls: the bot's OWN draft-time map columns (41: fitfeat F_*, mapfeat x[], dash plan, plan flags, strategy) for a set of maps, and a
class split on them (Tool Builder, 12 Nov; Deep's N1ACC acceptance read: keep 150 class + 150 non-class maps from one fresh draw).

usage: python3 -I tools/lab/draftcls.py MAPS OUT [--class "COL<V,COL>=V,..."] [--keep N] [--par 6]
  MAPS   a directory of .map26a (e.g. a stratmaps output dir) or a file with one map path per line
  OUT    output dir: cols.tsv (maphash, weird, in_class, 41 bot_* columns), class.lst / nonclass.lst (map paths),
         and with --keep N: class_keep.lst / nonclass_keep.lst (the first N of each, weird and standard alternating)
  --class  AND of conditions on bot_* columns, ops < <= > >= ; default Deep's N1 class: bot_mf_d_altar<11.83,bot_mf_solo_share<0.2224
How: tools/lab/draftdiag.py plays each map for 1 round in self-play with nova_tbdg_dfeat, a RELEASE dglog copy of live v815's draft code
(map_features() records tags 100-104; draft code unchanged through v817). That copy is a diag bot: never arm or submit it. Seat A is used.
weird = otf.json labels.pool == "weird" (stratmaps' genweird families) from the otf.json beside each map; NA when there is none. Key = sha1(map file)[:16]; no map names in cols.tsv.
Cost: ~1 min per 1,000 maps at --par 6 (local cxe, nice 10). Re-check the columns on a new live with a draft change: rebuild the copy."""
import csv
import hashlib
import os
import re
import subprocess
import sys

REPO = "/homes/USER/cambc"
BOT = "nova_tbdg_dfeat"
FIT = ["k", "gem_pc", "gold_pc", "clu_gem", "clu_gold", "heavy", "mono", "dash_only", "tp_only", "no_walk_altar", "dash_altar", "recall", "s2s",
       "central", "density", "n_altar", "safe_altar", "near_altar", "gem_total_pc", "fight", "gated"]
DV3 = ["gem_rate_pc", "gold_rate_pc", "groups_pc", "len_est", "att_mean", "d_altar", "trip", "solo_share", "SPLASH"]
COLS = (["bot_fit_ok"] + ["bot_" + n for n in FIT] + ["bot_mf_ok", "bot_mf_tier"] + ["bot_mf_" + n for n in DV3]
        + ["bot_reach_s", "bot_min_dash", "bot_max_dash", "bot_reach_null", "bot_plan_flags", "bot_strategy", "bot_n_farm", "bot_max_members"])
N1 = "bot_mf_d_altar<11.83,bot_mf_solo_share<0.2224"


def records(path):
    out = {}
    for r in csv.DictReader(open(path), delimiter="\t"):
        d = out.setdefault((r["map"], r["seat"]), {})
        tag = int(r["tag"])
        a, b, c, dd = (int(r[k]) for k in "abcd")
        d.setdefault((tag, a) if tag in (101, 102) else (tag,), (a, b, c, dd))
    return out


def row(d):
    o = {}
    t = d.get((100,))
    o["bot_fit_ok"] = t[0] if t else None
    for i, n in enumerate(FIT):
        x = d.get((101, i))
        o["bot_" + n] = x[1] / 1000 if x else None
    x = d.get((102, 0))
    o["bot_mf_ok"], o["bot_mf_tier"] = (x[2], x[3]) if x else (None, None)
    for i, n in enumerate(DV3):
        x = d.get((102, i))
        o["bot_mf_" + n] = x[1] / 1000 if x else None
    x = d.get((103,))
    for k, j in (("bot_reach_s", 0), ("bot_min_dash", 1), ("bot_max_dash", 2), ("bot_reach_null", 3)):
        o[k] = ((x[j] / 1000) if j == 0 else x[j]) if x else None
    x = d.get((104,))
    for k, j in (("bot_plan_flags", 0), ("bot_strategy", 1), ("bot_n_farm", 2), ("bot_max_members", 3)):
        o[k] = x[j] if x else None
    return o


def parse_class(s):
    conds = []
    for part in s.split(","):
        m = re.match(r"^\s*(bot_\w+)\s*(<=|>=|<|>)\s*(-?[\d.]+)\s*$", part)
        if not m or m.group(1) not in COLS:
            sys.exit(f"draftcls: bad condition {part!r} (bot_* column, op < <= > >=, number)")
        conds.append((m.group(1), m.group(2), float(m.group(3))))
    return conds


def in_class(o, conds):
    ops = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
    if any(o[c] is None for c, _, _ in conds):
        return None
    return all(ops[op](o[c], v) for c, op, v in conds)


POOL = {}  # map path -> 1 weird / 0 standard, from otf.json beside the map


def load_pools(paths):
    import json
    for d in sorted({os.path.dirname(p) for p in paths}):
        try:
            j = json.load(open(os.path.join(d, "otf.json")))
        except (OSError, ValueError):
            continue
        for e in (j.get("maps") or []) if isinstance(j, dict) else []:
            pool = (e.get("labels") or {}).get("pool")
            if e.get("name") and pool:
                POOL[os.path.join(d, e["name"] + ".map26a")] = int(pool == "weird")


def isw(p):
    return POOL.get(p)


def interleave(paths, n):
    w = [p for p in paths if isw(p) == 1]
    s = [p for p in paths if isw(p) != 1]
    out = []
    while len(out) < n and (w or s):
        for side in (w, s):
            if side and len(out) < n:
                out.append(side.pop(0))
    return out


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    src, out = a[0], a[1]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    conds, keep, par = parse_class(opt("--class", N1)), int(opt("--keep", "0")), opt("--par", "6")
    paths = (sorted(os.path.join(src, f) for f in os.listdir(src) if f.endswith(".map26a")) if os.path.isdir(src)
             else [ln.strip() for ln in open(src) if ln.strip() and not ln.startswith("#")])
    load_pools(paths)
    os.makedirs(out, exist_ok=True)
    lst = os.path.join(out, "maps.lst")
    open(lst, "w").write("\n".join(paths) + "\n")
    dg = os.path.join(out, "dg")
    r = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tools/lab/draftdiag.py"), BOT, lst, dg, "--rounds", "1", "--par", par],
                       cwd=REPO, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-400:] + r.stderr[-400:])
    rec = records(os.path.join(dg, "records.tsv"))
    cls, non, miss = [], [], 0
    with open(os.path.join(out, "cols.tsv.tmp"), "w") as f:
        f.write("maphash\tweird\tin_class\t" + "\t".join(COLS) + "\n")
        for p in paths:
            nm = os.path.basename(p)[:-len(".map26a")]
            d = rec.get((nm, "a")) or rec.get((nm, "b"))
            if not d:
                miss += 1
                continue
            o = row(d)
            ic = in_class(o, conds)
            (cls if ic else non).append(p) if ic is not None else None
            h = hashlib.sha1(open(p, "rb").read()).hexdigest()[:16]
            f.write(f"{h}\t{'NA' if isw(p) is None else isw(p)}\t{'NA' if ic is None else int(ic)}\t"
                    + "\t".join("NA" if o[c] is None else str(o[c]) for c in COLS) + "\n")
    os.replace(os.path.join(out, "cols.tsv.tmp"), os.path.join(out, "cols.tsv"))
    open(os.path.join(out, "class.lst"), "w").write("".join(p + "\n" for p in cls))
    open(os.path.join(out, "nonclass.lst"), "w").write("".join(p + "\n" for p in non))
    wk = lambda L: sum(isw(p) == 1 for p in L)  # noqa: E731
    n = len(cls) + len(non)
    print(f"draftcls: {len(paths)} maps, {miss} without records; class ({opt('--class', N1)}): {len(cls)} of {n} = "
          f"{100 * len(cls) / max(1, n):.1f}% (weird {wk(cls)}/{wk(cls) + wk(non)} = {100 * wk(cls) / max(1, wk(cls) + wk(non)):.1f}%, "
          f"standard {len(cls) - wk(cls)}/{n - wk(cls) - wk(non)} = {100 * (len(cls) - wk(cls)) / max(1, n - wk(cls) - wk(non)):.1f}%) -> {out}")
    if keep:
        for nm, L in (("class_keep.lst", cls), ("nonclass_keep.lst", non)):
            k = interleave(list(L), keep)
            open(os.path.join(out, nm), "w").write("".join(p + "\n" for p in k))
            if len(k) < keep:
                print(f"draftcls: only {len(k)} of {keep} for {nm}: draw more maps")


if __name__ == "__main__":
    main()
