"""Per-function diff of two bots: funcdiff.py BOT BASE [--full] [FILE...]

Prints, for every changed source file, which functions changed (with their line ranges in BOT) and how many lines
were added and removed (NEW: a function name BASE does not have), the functions BASE has and BOT does not (DELETED, with
their line ranges in BASE), plus new and deleted files; --full also prints the unified diff hunks. Agents use it to
understand a candidate or line from its changes alone instead of re-reading whole files.
Example: python3 -I tools/lab/funcdiff.py bots/nova_m3 bots/nova_m1
"""
import difflib, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from codeindex import index_file  # noqa: E402


def src_of(bot):
    bot = bot.rstrip("/")
    return os.path.join(bot, "src") if os.path.isdir(os.path.join(bot, "src")) else bot


def main():
    args = sys.argv[1:]
    full = "--full" in args
    args = [a for a in args if a != "--full"]
    a_src, b_src = src_of(args[0]), src_of(args[1])
    # 11 Nov (RC: v762 -> v763 read backwards, a new function listed as DELETED): say which way round it reads, and warn when BOT is the
    # OLDER of two shipped versions (live.txt order)
    va = vb = None
    try:
        order = [ln.split()[1] for ln in open("/data/zw4424/st/bq/live.txt") if len(ln.split()) >= 2]
        na, nb = os.path.basename(os.path.normpath(args[0])), os.path.basename(os.path.normpath(args[1]))
        va, vb = (order.index(na) if na in order else None), (order.index(nb) if nb in order else None)
    except OSError:
        pass
    print(f"funcdiff: {args[0]} relative to {args[1]} (+ = in the FIRST bot, DELETED = only in the second)")
    if va is not None and vb is not None and va > vb:
        print(f"funcdiff: WARNING: the first bot is the OLDER shipped version: to review a ship, run funcdiff NEW OLD (signs are inverted here)")
    only = set(args[2:])
    fa = {f for f in os.listdir(a_src) if f.endswith((".cpp", ".cc", ".h"))}
    fb = {f for f in os.listdir(b_src) if f.endswith((".cpp", ".cc", ".h"))}
    if only:
        fa &= only; fb &= only
    for f in sorted(fa - fb):
        n = sum(1 for _ in open(os.path.join(a_src, f), encoding="utf-8", errors="replace"))
        print(f"== NEW FILE {f} ({n} lines)")
        for a, b, ns, name, sig, com in index_file(os.path.join(a_src, f)):
            print(f"  + {f}:{a}-{b}  {sig[:110]}" + (f"  | {com[:120]}" if com else ""))
    for f in sorted(fb - fa):
        print(f"== DELETED FILE {f}")
    for f in sorted(fa & fb):
        la = open(os.path.join(a_src, f), encoding="utf-8", errors="replace").read().split("\n")
        lb = open(os.path.join(b_src, f), encoding="utf-8", errors="replace").read().split("\n")
        if la == lb:
            continue
        sm = difflib.SequenceMatcher(a=lb, b=la, autojunk=False)
        funcs = index_file(os.path.join(a_src, f))
        # functions of BASE whose name is gone from BOT: their removed lines are reported under them (by BASE line
        # numbers), not under whatever BOT function or gap the deletion point falls next to
        names = {(ns, name) for a, b, ns, name, sig, com in funcs}
        base = index_file(os.path.join(b_src, f))
        base_names = {(ns, name) for a, b, ns, name, sig, com in base}
        new_fn = {(a, b) for a, b, ns, name, sig, com in funcs if (ns, name) not in base_names}
        gone = [(a, b, sig) for a, b, ns, name, sig, com in base if (ns, name) not in names]
        changed, deleted = {}, {}
        adds = rems = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            adds += j2 - j1; rems += i2 - i1
            dg = [(a, b, sig) for a, b, sig in gone if i1 < i2 and a <= i2 and i1 + 1 <= b]
            rm = i2 - i1  # removed lines left for BOT's functions
            for a, b, sig in dg:
                k = min(b, i2) - max(a, i1 + 1) + 1
                deleted[(a, b, sig)] = deleted.get((a, b, sig), 0) + k
                rm -= k
            if dg and j1 == j2 and rm <= 0:
                continue  # a pure deletion of whole functions
            lo, hi = j1 + 1, max(j1 + 1, j2)
            hit = False
            for a, b, ns, name, sig, com in funcs:
                if a <= hi and lo <= b:
                    c = changed.setdefault((a, b, sig), [0, 0]); c[0] += j2 - j1; c[1] += rm; hit = True
            if not hit:
                c = changed.setdefault((lo, hi, "(outside functions: declarations, constants, includes)"), [0, 0])
                c[0] += j2 - j1; c[1] += rm
        print(f"== {f}: +{adds} -{rems} lines, {len(changed)} changed places" + (f", {len(deleted)} deleted functions" if deleted else ""))
        for (a, b, sig), (ad, rm) in sorted(changed.items()):
            print(f"  {f}:{a}-{b}  +{ad} -{rm}  {'NEW ' if (a, b) in new_fn else ''}{sig[:110]}")
        for (a, b, sig), rm in sorted(deleted.items()):
            print(f"  {f}:{a}-{b} (in BASE)  -{rm}  DELETED {sig[:100]}")
        if full:
            for line in difflib.unified_diff(lb, la, fromfile=f"base/{f}", tofile=f"bot/{f}", n=2, lineterm=""):
                print("    " + line)


if __name__ == "__main__":
    main()
