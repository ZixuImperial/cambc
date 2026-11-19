#!/usr/bin/env python3
"""foeepoch: when did a foe upload a new bot? (Tool Builder, 12 Nov; Coordinator/Planner: Fish resubmitted 09:40-10:29Z with a new draft).
The platform gives no foe upload times (ladder and `matches show` carry team ids, drafts and times, no submission id), so a foe 'epoch'
is inferred from its DRAFT: with our draft code fixed, a game's draft on a (map, our seat) cell is deterministic for a fixed foe bot, so the
foe's lineup changing on the same cell means the foe changed between those two games.

usage: python3 -I tools/lab/foeepoch.py detect [--quiet]              write /data/zw4424/st/bq/foe_epochs.tsv (every foe), print the windows
       python3 -I tools/lab/foeepoch.py detect --foe NAME                  one foe's windows to stdout only (the shared table is untouched)
       python3 -I tools/lab/foeepoch.py split CLIMB_DIR [--foe NAME] [--by-version]   a climb lane's record split by foe epoch (and our version)
       python3 -I tools/lab/foeepoch.py of FOE MATCH_ID                   the epoch label of one game
Sources: every ladderclimb lane's games.tsv (climb_top3, climb_side, climb_side1..4; column 8 = foe lineup). Our draft-identical span:
live's baked base back through every stored nova_base_vNNN whose src/draft*, mapfeat*, mapinfo*, strategy*, plan_map* files equal
live's (12 Nov: v783-v822). Only games on versions in that span are compared (no foe-lineup column before 9 Nov either).
Windows: each lineup change gives an interval (last game with the old lineup, first with the new); intervals that overlap are one
change, and its window is [latest old game, earliest new game] across them (when that is empty, the union). A window needs >= MIN_CELLS
(2) changed cells, so one odd cell (a fuel-randomised draft) is not a new bot. Epoch labels per foe: e0 before the first window, e1 after it,
...; a game inside a window is '?'. foe_epochs.tsv: foe, lo, hi (UTC), cells changed, cells compared, example."""
import collections
import datetime
import filecmp
import os
import re
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))  # 12 Nov (Combat): under -I, 'import teamalias' needs the script dir

ST = "/data/zw4424/st"
OUT = f"{ST}/bq/foe_epochs.tsv"
LANES = ["climb_top3", "climb_side", "climb_side1", "climb_side2", "climb_side3", "climb_side4"]
BASES = f"{ST}/new/bots"
MIN_CELLS = 2
DRAFT_RE = re.compile(r"^(draft|mapfeat|mapinfo|strategy|plan_map)")


def t_of(mid):
    return datetime.datetime.fromtimestamp(int(mid.replace("-", "")[:12], 16) / 1000, datetime.timezone.utc)


def draft_span():
    """versions whose stored baked base has live's draft files (contiguous from live backwards)"""
    live = open(f"{ST}/bq/live.txt").readline().split()[0]
    lv = int(live.lstrip("v"))
    ref = f"{BASES}/nova_base_v{lv}/src"
    if not os.path.isdir(ref):
        return {live}
    files = [f for f in os.listdir(ref) if DRAFT_RE.match(f)]
    span = {f"v{lv}"}
    for v in range(lv - 1, lv - 300, -1):
        d = f"{BASES}/nova_base_v{v}/src"
        if not os.path.isdir(d):
            span.add(f"v{v}")  # a version without a stored base sits between two identical ones: keep it (checked at the next stored one)
            continue
        if all(os.path.exists(f"{d}/{f}") and filecmp.cmp(f"{ref}/{f}", f"{d}/{f}", shallow=False) for f in files):
            span.add(f"v{v}")
        else:
            span = {x for x in span if int(x[1:]) > v}
            break
    return span


def rows(span):
    out = []
    for ln in LANES:
        p = f"{ST}/{ln}/games.tsv"
        if not os.path.exists(p):
            continue
        for x in open(p):
            r = x.rstrip("\n").split("\t")
            if len(r) >= 8 and r[7] and r[0] in span:
                import teamalias  # 12 Nov: renamed teams keep one name ('prism best fih' = 'stellar best girl')
                out.append(dict(ver=r[0], foe=teamalias.canonical(r[1]), id=r[3], map=r[4], side=r[5], res=r[6], lu=r[7], t=t_of(r[3]), lane=ln))
    return out


def windows(rs, foe):
    cell = collections.defaultdict(list)
    for r in rs:
        if r["foe"] == foe:
            cell[(r["map"], r["side"])].append(r)
    ev, npairs = [], 0
    for k, v in cell.items():
        v.sort(key=lambda r: r["t"])
        # 12 Nov (Deep, Mite: v803's first batch drafted odd lineups that the next games reverted): a run of lineups bounded on both sides by
        # one same lineup (A, B.., A) is a transient, not a new bot: drop it before reading changes
        i = 1
        while i < len(v) - 1:
            j = i
            while j < len(v) - 1 and v[j]["lu"] != v[i - 1]["lu"]:
                j += 1
            if j > i and v[j]["lu"] == v[i - 1]["lu"]:
                del v[i:j]
            else:
                i += 1
        for a, b in zip(v, v[1:]):
            npairs += 1
            if a["lu"] != b["lu"]:
                run = sum(1 for x in v if x["lu"] == a["lu"] and x["t"] <= a["t"])  # games with the old lineup up to the change
                ev.append((a["t"], b["t"], k, a["lu"], b["lu"], run))
    # 12 Nov (Deep, Mite): overlap-merging let wide intervals bridge two changes; group by STABBING instead (sort by end; the earliest end
    # stabs every interval containing it: one change point, one group); a group whose old side is one game per cell, all within 10 min,
    # is a one-batch transient (v803's first batch drafted odd lineups) and is dropped
    ev.sort(key=lambda e: e[1])
    groups, left = [], list(ev)
    while left:
        t = left[0][1]
        g = [e for e in left if e[0] < t <= e[1]]
        groups.append(g)
        left = [e for e in left if e not in g]
    W = []
    for g in groups:
        cells = {e[2] for e in g}
        if len(cells) < MIN_CELLS:
            continue
        olds = [e[0] for e in g]
        if all(e[5] == 1 for e in g) and (max(olds) - min(olds)).total_seconds() <= 600:
            continue  # one-batch transient
        lo, hi = max(e[0] for e in g), min(e[1] for e in g)
        if lo >= hi:  # 12 Nov (Deep, SBG 12:00-13:09Z read as 09:48-13:09Z): a late old-lineup game on one cell (a repeat of the old pick
            #          after the change) widened the window to the union; take the latest old game BEFORE the earliest new one instead
            before = [e[0] for e in g if e[0] < hi]
            lo, hi = (max(before), hi) if before else (min(e[0] for e in g), max(e[1] for e in g))
        W.append(dict(lo=lo, hi=hi, cells=len(cells), ex=f"{g[0][2][0]} {g[0][2][1]} {g[0][3]} -> {g[0][4]}"))
    W.sort(key=lambda w: w["lo"])
    return W, npairs


def label(W, t):
    k = 0
    for w in W:
        if t >= w["hi"]:
            k += 1
        elif t > w["lo"]:
            return "?"
    return f"e{k}"


def load():
    W = collections.defaultdict(list)
    if os.path.exists(OUT):
        for x in open(OUT):
            if x.startswith("#") or x.startswith("foe\t"):
                continue
            p = x.rstrip("\n").split("\t")
            W[p[0]].append(dict(lo=datetime.datetime.fromisoformat(p[1]), hi=datetime.datetime.fromisoformat(p[2]), cells=int(p[3])))
    return W


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "detect":
        span = draft_span()
        rs = rows(span)
        foes = [a[a.index("--foe") + 1]] if "--foe" in a else sorted({r["foe"] for r in rs})
        lines = [f"# {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%MZ} foeepoch detect: our draft code identical over "
                 f"{min(span, key=lambda v: int(v[1:]))}-{max(span, key=lambda v: int(v[1:]))}; {len(rs)} games", "foe\tlo\thi\tcells\tpairs\texample"]
        for f in foes:
            W, n = windows(rs, f)
            for w in W:
                lines.append(f"{f}\t{w['lo'].isoformat()}\t{w['hi'].isoformat()}\t{w['cells']}\t{n}\t{w['ex']}")
            if "--quiet" not in a:
                print(f"{f}: {n} cell pairs, {len(W)} change window(s)" + "".join(f"\n   {w['lo']:%m-%dT%H:%M} .. {w['hi']:%m-%dT%H:%M}Z  {w['cells']} cells  e.g. {w['ex']}" for w in W))
        if "--foe" in a:  # 12 Nov (Deep: a --foe run overwrote the shared file with one foe): a single-foe run prints, never writes the table
            print("\n".join(lines))
            return
        open(OUT + ".tmp", "w").write("\n".join(lines) + "\n")
        os.replace(OUT + ".tmp", OUT)
        return
    if a[0] == "of":
        print(label(load().get(a[1], []), t_of(a[2])))
        return
    if a[0] == "split":
        d = a[1] if a[1].startswith("/") else f"{ST}/{a[1]}"
        W = load()
        want = a[a.index("--foe") + 1] if "--foe" in a else None
        c = collections.Counter()
        for x in open(f"{d}/games.tsv"):
            r = x.rstrip("\n").split("\t")
            if len(r) < 7 or (want and r[1] != want):
                continue
            ep = label(W.get(r[1], []), t_of(r[3])) + (f" {r[0]}" if "--by-version" in a else "")  # 12 Nov (Coordinator): records by version x epoch
            c[(r[1], ep, r[6])] += 1
        for foe in sorted({k[0] for k in c}):
            for ep in sorted({k[1] for k in c if k[0] == foe}, key=lambda e: (e.split()[0], int(e.split()[1][1:]) if len(e.split()) > 1 and e.split()[1][1:].isdigit() else 0)):
                w, l_, dr = c[(foe, ep, "win")], c[(foe, ep, "loss")], c[(foe, ep, "draw")]
                print(f"{foe:28s} {ep:10s} W {w:4d}  L {l_:4d}" + (f"  D {dr}" if dr else "") + f"  ({w / max(1, w + l_):.2f})")
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
