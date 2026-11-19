#!/usr/bin/env python3
"""firecount: how often a feature fires, in one command, before any mechanism story (CLAUDE.md §4: "get a firing count first";
Builder 7 Nov, owner: faster builds).

usage: python3 -I tools/lab/firecount.py BOT "FLAG=V [FLAG2=V2 ...]" [--n 100 | --mapdir DIR] [--vs BOT2] [--tag T] [--keep] [--base BASE (new layout: count the functions new against BASE)]
  1. a diag copy of BOT (tools/lab/dgkit.py make): if BOT's src has no DG(...) lines of its own, a counter DG("fc_<feature>.<function>", 1) goes at
     the entry of every function in its src/feat_*.cpp files (primer RULE OWN-FILE puts a feature's code there); else the agent's DG
     lines are the counters. The flips are set in the copy's #defines.
  2. its cxe DEBUG library (tools/cxe/dbgso.py: DG records exist only in debug builds) v --vs (default live, release), on --n new
     unsaved maps (stratmaps, half pathological), both seats, at the real 100k fuel, on the pilots (cxefarm, CXE_STDOUT=1).
  3. per tag: fires in all, fires per game, and the share of games where it fired at least once (the diag side's records only).
Debug code costs more fuel than release, so a debug bot runs out of fuel sooner on heavy turns: the counts are a firing check, not a
score (never score a diag copy). Results: /data/zw4424/st/firecount/TAG/result.txt; the diag copy and maps go at the end (--keep keeps).
"""
import collections
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "/homes/zw4424/cambc"
LAB = f"{REPO}/tools/lab"
CXE = f"{REPO}/tools/cxe"
ROOT = "/data/zw4424/st/firecount"
sys.path.insert(0, LAB)
sys.path.insert(0, CXE)
FUNC = re.compile(r"^(?!\s)(?!namespace\b|struct\b|class\b|enum\b|using\b|typedef\b|template\b|static_assert\b|#)([^\n;{}()]*?\b(\w+)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?)\n\{\n", re.M)


def say(s):
    print(f"{time.strftime('%H:%M:%S')} {s}", flush=True)


def src_of(bot):
    return os.path.join(os.path.realpath(os.path.join(REPO, "bots", bot)), "src")


def own_dg(src):
    for f in os.listdir(src):
        if f.endswith((".h", ".cpp", ".cc")) and f != "dgkit.h" and re.search(r'\bDG\("', open(os.path.join(src, f), errors="replace").read()):
            return True
    return False


def new_functions(src, base_src):
    """new layout (no feature files): (file, regex match, tag) for each function of a .cc file that BASE does not have"""
    old = "".join(open(os.path.join(base_src, f), errors="replace").read() for f in os.listdir(base_src) if f.endswith((".h", ".cpp", ".cc")))
    for f in sorted(glob.glob(os.path.join(src, "*.cc"))):
        s = open(f, errors="replace").read()
        for m in FUNC.finditer(s):
            if s.count(m.group(0)) == 1 and m.group(0) not in old:
                yield f, m, "fc_" + os.path.basename(f)[:-3][:12] + "." + m.group(2)[:20]


def flag_sites(src, flips):
    """Refactored layout (8 Nov DRY test: a feature inside an existing function has no new function to count): each `if (...)` naming a flipped flag, not negated.
    -> [(file, anchor, replacement, tag)]; the counter is inside the condition, so it counts the turns the flagged branch is really taken."""
    stems = sorted({re.sub(r"_(BITS|TAB|ON)$", "", k) for k in flips})
    if not stems:
        return []
    flag = re.compile(r"(?<!!)\b(" + "|".join(map(re.escape, stems)) + r")_(ON\b|TAB\s*\[)")
    out = []
    for f in sorted(glob.glob(os.path.join(src, "*.cc")) + glob.glob(os.path.join(src, "*.h"))):
        if f.endswith("_flags.h"):
            continue
        s = open(f, errors="replace").read()
        sites = []
        for m in re.finditer(r"\bif\s*\(", s):
            depth, i = 1, m.end()
            while i < len(s) and depth:
                depth += {"(": 1, ")": -1}.get(s[i], 0)
                i += 1
            cond = s[m.end():i - 1]
            if depth or not flag.search(cond):
                continue
            # 9 Nov (Builder, b1753 PHL/CKT: the diag build failed twice): an init-statement `if (INIT; COND)` gets its counter on COND only (where
            # it is valid C++); a declaration condition `if (T x = e)` of any type cannot take `(...) && counter` and is skipped, with a note
            top, dep = -1, 0
            for k, ch in enumerate(cond):
                dep += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
                if ch == ";" and dep == 0:
                    top = k
                    break
            off = 0
            if top >= 0:
                off, cond = top + 1, cond[top + 1:]
                if not flag.search(cond):
                    print(f"firecount: {os.path.basename(f)}:{s.count(chr(10), 0, m.start()) + 1}: flag only in the if's init-statement: no counter", file=sys.stderr)
                    continue
            if re.match(r"\s*(?:(?:const|constexpr|static|volatile|unsigned|signed|struct|class)\s+)*[A-Za-z_][\w:<>,]*(?:\s*[*&]+\s*|\s+)[A-Za-z_]\w*\s*(?:=(?!=)|\{)", cond):
                print(f"firecount: {os.path.basename(f)}:{s.count(chr(10), 0, m.start()) + 1}: declaration condition: no counter (it cannot take '(...) && counter')", file=sys.stderr)
                continue
            ls = s.rfind("\n", 0, m.start()) + 1
            while s.count(s[ls:i]) > 1 and ls > 0:  # widen upward until the anchor is unique in its file
                ls = s.rfind("\n", 0, ls - 1) + 1
            if s.count(s[ls:i]) != 1:
                continue
            tag = f"fc_{flag.search(cond).group(1)[:10]}.{os.path.basename(f).split('.')[0][:14]}_{s.count(chr(10), 0, m.start()) + 1}"
            sites.append((ls, m.end() + off, i, cond, tag))
        sites.sort()
        clusters = []  # 8 Nov (b1714): identical flagged lines widen into overlapping anchors, and the first edit broke the second: one edit per overlapping group
        for z in sites:
            if clusters and z[0] < clusters[-1][-1][2]:
                clusters[-1].append(z)
            else:
                clusters.append([z])
        for c in clusters:
            start, end = c[0][0], max(z[2] for z in c)
            while s.count(s[start:end]) > 1 and start > 0:
                start = s.rfind("\n", 0, start - 1) + 1
            if s.count(s[start:end]) != 1:
                continue
            text = s[start:end]
            for _, me, i, cond, tag in sorted(c, key=lambda z: -z[1]):
                text = text[:me - start] + "(" + cond + ") && [&]{ DG(" + json.dumps(tag) + ", 1); return true; }())" + text[i - start:]
            out.append((os.path.basename(f), s[start:end], text, [z[4] for z in c]))
    return out


def spec_text(src, base_src=None, flips=None):
    """dgkit spec: a counter at the entry of every function in src/feat_*.cpp, or on the new layout of every function new against base_src -> (spec source, [counter tags])"""
    lines, tags = [], []
    if (base_src or flips) and not glob.glob(os.path.join(src, "feat_*.cpp")):
        for f, m, tag in (new_functions(src, base_src) if base_src else []):
            lines.append(f"at({os.path.basename(f)!r}, {m.group(0)!r}, {('	DG(' + json.dumps(tag) + ', 1); // firecount' + chr(10))!r})")
            tags.append(tag)
        for f, old, new, ts in flag_sites(src, flips or {}):
            lines.append(f"at({f!r}, {old!r}, {new!r}, where='replace')")
            tags.extend(ts)
        return "\n".join(lines) + "\n", tags
    for f in sorted(glob.glob(os.path.join(src, "feat_*.cpp"))):
        s = open(f, errors="replace").read()
        for m in FUNC.finditer(s):
            anchor = m.group(0)
            if s.count(anchor) != 1:
                continue
            tag = "fc_" + os.path.basename(f)[5:-4][:12] + "." + m.group(2)[:20]  # fc_<feature>.<function>
            lines.append(f"at({os.path.basename(f)!r}, {anchor!r}, {('	DG(' + json.dumps(tag) + ', 1); // firecount' + chr(10))!r})")
            tags.append(tag)
    return "\n".join(lines) + "\n", tags


def set_flips(src, flips):
    for k, v in flips.items():
        hit = 0
        for f in os.listdir(src):
            if not f.endswith((".h", ".cpp", ".cc")):
                continue
            p = os.path.join(src, f)
            s = open(p, errors="replace").read()
            s2, n = re.subn(rf"^([ \t]*#[ \t]*define[ \t]+{re.escape(k)}[ \t]+)\(?[ \t]*-?\d+[ \t]*\)?", rf"\g<1>{v}", s, flags=re.M)  # [ \t], never \s: \s ate the newline
            if n:
                open(p, "w").write(s2)
                hit += n
        if hit != 1:
            sys.exit(f"firecount: #define {k} found {hit} times in the diag copy (needs exactly 1)")


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    bot, fl = a[0], a[1]
    n = int(a[a.index("--n") + 1]) if "--n" in a else 100
    vs = a[a.index("--vs") + 1] if "--vs" in a else open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    tag = a[a.index("--tag") + 1] if "--tag" in a else "fc" + time.strftime("%m%d%H%M%S", time.gmtime())
    keep = "--keep" in a
    flips = dict(x.split("=", 1) for x in fl.replace(",", " ").split() if "=" in x)
    if not os.path.isdir(src_of(bot)):
        sys.exit(f"firecount: no bot {bot}")
    run = os.path.join(ROOT, tag)
    os.makedirs(run, exist_ok=False)
    t0 = time.time()
    # 1. diag copy
    diag = f"nova_dgfc_{tag}"
    spec = os.path.join(run, "spec.py")
    if own_dg(src_of(bot)):
        open(spec, "w").write("# the bot's own DG lines are the counters\n")
        tags = None
        say("BOT has its own DG lines: they are the counters")
    else:
        txt, tags = spec_text(src_of(bot), src_of(a[a.index("--base") + 1]) if "--base" in a else None, flips)
        if not tags:
            sys.exit("firecount: nothing to count: no DG lines, no function new against --base, and no `if (...)` naming a flipped flag: add DG(\"tag\", ...) at the "
                     "decision (tools/lab/dgkit.py)")
        open(spec, "w").write(txt)
        say(f"counters at {len(tags)} feat function entr{'y' if len(tags) == 1 else 'ies'}: {', '.join(tags)}")
    r = subprocess.run([sys.executable, "-I", f"{LAB}/dgkit.py", "make", bot, diag, spec], capture_output=True, text=True, cwd=REPO)
    if r.returncode:
        sys.exit(f"firecount: dgkit make failed: {(r.stdout + r.stderr).strip()[-400:]}")
    set_flips(src_of(diag), flips)
    import dbgso
    import cxebuild
    import cxefarm
    so = dbgso.build(diag)
    so_vs = cxebuild.build_bot(vs)
    say(f"diag copy {diag} (debug, {fl}) -> {so}; v {vs} (release); {time.time() - t0:.0f} s")
    # 2. maps and games
    md = os.path.join(run, "maps")
    if "--mapdir" in a:  # b1556 8 Nov: a trigger set (copied into the run, so the cleanup removes only the copy)
        os.makedirs(md, exist_ok=True)
        for f in glob.glob(os.path.join(a[a.index("--mapdir") + 1], "*.map26a")):
            shutil.copy(f, md)
        r = subprocess.CompletedProcess([], 0, "", "")
    else:
        r = subprocess.run([sys.executable, "-I", f"{LAB}/stratmaps.py", md, "--n", str(n), "--take", "--who", "firecount", "--weird", "0.5", "--light"],
                           capture_output=True, text=True)
    maps = sorted(glob.glob(os.path.join(md, "*.map26a")))
    if not maps:
        sys.exit(f"firecount: no maps ({(r.stdout + r.stderr).strip()[-300:]})")
    gd = os.path.join(run, "g")
    os.makedirs(gd)
    games = []
    for k, m in enumerate(maps):
        for seat in "AB":
            out = os.path.join(gd, f"g{k}{seat}")
            games.append(dict(id=len(games), a=so if seat == "A" else so_vs, b=so_vs if seat == "A" else so, map=m, args=["--statistics", "@D@/g.json"],
                              env={"CXE_STDOUT": "1"}, files={f"g.team-{seat.lower()}.stdout": out + ".stdout", "g.json": out + ".json"}, digest=True,
                              seat=seat, mapname=os.path.basename(m)))
    t1 = time.time()
    os.environ.setdefault("CXEFARM", "1")  # 8 Nov: under 40 games cxefarm otherwise declines the pilots (returns None) and firecount read 0 games
    got = cxefarm.run(games, say=say, per=24, cpus=8, prio=int(os.environ.get("FIRECOUNT_PRIO", "11")))
    say(f"{got} of {len(games)} games back in {time.time() - t1:.0f} s")
    # 3. counts
    per_game = []
    for g in games:
        p = os.path.join(gd, f"g{g['id'] // 2}{g['seat']}.stdout")
        if not os.path.exists(p):
            continue
        c = collections.Counter()
        for ln in open(p, errors="replace"):
            x = ln.replace("\0", "").split()
            if len(x) >= 4 and x[0] == "D":
                c[x[3]] += 1
        per_game.append((g["mapname"], g["seat"], c))
    played = len(per_game)
    alltags = sorted({t for _, _, c in per_game for t in c} | set(tags or []))
    lines = [f"# firecount {tag} {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}: {bot} with {fl} (diag, debug build) v {vs}, "
             f"{len(maps)} new maps x 2 seats at 100k fuel: {played} of {len(games)} games read; wall {time.time() - t0:.0f} s",
             f"  {'tag':24s} {'fires':>8s} {'per game':>9s} {'games fired':>12s}"]
    for t in alltags:
        tot = sum(c[t] for _, _, c in per_game)
        hit = sum(1 for _, _, c in per_game if c[t])
        lines.append(f"  {t:24s} {tot:8d} {tot / max(1, played):9.2f} {hit:6d} ({100 * hit / max(1, played):4.1f}%)")
    if not alltags:
        lines.append("  no records at all: the counters never ran (check the hook is reached and the flag value turns it on)")
    lines.append("# debug builds spend more fuel than release: a firing check, never a score")
    txt = "\n".join(lines)
    open(os.path.join(run, "result.txt"), "w").write(txt + "\n")
    json.dump([dict(map=m, seat=s, counts=dict(c)) for m, s, c in per_game], open(os.path.join(run, "games.json"), "w"))
    print(txt, flush=True)
    if not keep:
        shutil.rmtree(gd, ignore_errors=True)
        shutil.rmtree(md, ignore_errors=True)
        lst = os.path.join(run, "rm.txt")
        link = os.path.join(REPO, "bots", diag)
        open(lst, "w").write("\n".join([os.path.realpath(link), link]) + "\n")
        subprocess.run(["sh", f"{LAB}/rmdata.sh", lst], capture_output=True, text=True)
    return 0 if played else 1


if __name__ == "__main__":
    sys.exit(main())
