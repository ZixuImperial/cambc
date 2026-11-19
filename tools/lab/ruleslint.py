#!/usr/bin/env python3
"""ruleslint: rule numbers written by hand where a single-source helper exists (Tool builder, 6 Nov; owner: "fix inconsistencies with helper
functions or constants so one change is consistent across the code base"; primer RULE SINGLE-SOURCE). WARN only: a hit is a line to look at,
not a proven bug (a literal can be policy, e.g. a 16-round give-up). Sources: Econ's timer census (condor-work/reports/econ/timer_census.md),
Combat's killq list.

usage: python3 -I tools/lab/ruleslint.py ratchet BASE NEW exit 1 when NEW has more hand-written rule numbers than BASE (allow-list:
       tools/lab/ruleslint_allow.txt, 'RULE<TAB>file<TAB>line text substring'); mergecheck FAILs on it
       python3 -I tools/lab/ruleslint.py diff BASE NEW   ADDED lines of NEW v BASE (bots or src dirs): file:line rule -> the helper to call
       python3 -I tools/lab/ruleslint.py census BOT      every line of BOT: per-rule counts, then the sites (--top N per rule, default 40)
mergecheck (WARN rows) and armq preflight (notes) run the diff mode on every candidate/donor. Exit 0 always (a lint, not a gate).

Rules (comments and string text are ignored; rs.h, the rules header, and each helper's own definition are exempt; a line that already
calls the rule's helper is skipped):
  TRIB   gem count / 10 (ceil(G/10), (G + 9) / 10)                 -> rs::tribute_turns(gems, holder)  (Tribute holder x0.67)
  RECALL recall/home/back arithmetic with a bare 3/4/5/7             -> csx_recall_t()  (measured 3/4/5 by spin state)
  CAPT   capture/cap_start/respawn_at arithmetic with 5/6/7/8        -> rs::capture_pay(holder)  (1+5, or 1+3 with a Capture holder)
  DEATH  death/respawn arithmetic with 60/61                         -> rs::rules().respawn  (D+60 or D+61 by turn order)
  CD     cooldown arithmetic with 8 (spell cycle)                    -> the cooldown constant / slot read (8 owner turn ends)
  MULT   0.7/0.9/1.1/1.15/1.25/1.5 multiplied into damage/HP/gold    -> passive_mult / lbe_mult / rs::monster_mult / rs::kill_gold
  EFFHP  hp + shield summed by hand                                  -> eff_hp(b)
  DEF    a new definition whose name looks like a helper's           -> reuse the existing helper
  FENEMY a read of M.f_enemy / M.d_enemy with no M.has_enemy guard     -> guard it (or a fallback): unbuilt for lean draft-memory champions"""
import difflib
import os
import re
import sys
from collections import Counter, defaultdict

REPO = "/homes/USER/cambc"
NUM = r"(?:[-+<>]=?\s*(?:%s)(?![\w.])|(?<![\w.])(?:%s)\s*[-+](?!=))"  # the literal sits in additive / comparison arithmetic
RULES = [
    ("TRIB", re.compile(r"(?:ceil\w*\s*\([^;]*?/\s*10(?:\.0?f?)?\b|\+\s*9\s*\)\s*/\s*10\b)"), None,
     "rs::tribute_turns(gems, holder)", ("tribute_turns",)),
    ("RECALL", re.compile(NUM % ("3|4|5|7", "3|4|5|7")), re.compile(r"\b(recall|rec_t|home|back|rcl|hs|home_steps|walk_home)\w*", re.I),
     "csx_recall_t()", ("csx_recall_t", "recall_t(", "RECALL_T")),
    ("CAPT", re.compile(NUM % ("5|6|7|8", "5|6|7|8")), re.compile(r"\b(capture|cap_start|cap_t|respawn_at|cap_pay)\w*", re.I),
     "rs::capture_pay(holder)", ("capture_pay", "enemy_cap_pay")),
    ("DEATH", re.compile(NUM % ("60|61", "60|61")), re.compile(r"\b(died|dead|death|respawn|revive)\w*", re.I),
     "rs::rules().respawn", ("rules().respawn", ".respawn")),
    ("CD", re.compile(NUM % ("8", "8")), re.compile(r"\b(cooldown|cd|slot_cd|spell_cd)\w*\b", re.I),
     "the slot's cooldown read / cooldown constant (8 owner turn ends)", ("cooldown(", "COOLDOWN")),
    ("MULT", re.compile(r"(?<![\w.])(0\.7|0\.9|1\.1|1\.15|1\.25|1\.5)f?(?![\w.])"), re.compile(r"\b(dmg|damage|hp|gold|str|atk|burst|dps)\w*", re.I),
     "passive_mult / lbe_mult / rs::monster_mult / rs::kill_gold", ("passive_mult", "lbe_mult", "monster_mult", "kill_gold")),
    ("EFFHP", re.compile(r"\.hp\s*\+\s*\w+(?:\.|->)shield"), None, "eff_hp(b)", ("eff_hp",)),
]
HELPERS = ("passive_mult", "lbe_mult", "eff_hp", "csx_recall_t", "tribute_turns", "capture_pay", "monster_mult", "kill_gold")
DEFN = re.compile(r"^\s*(?:static\s+|inline\s+)*(?:float|int|double|bool|long)\s+(\w*(?:_mult|eff_hp|recall_t|tribute_t\w*|capture_t\w*|kill_gold)\w*)\s*\(")


def strip(line, state):
    """the code part of a line (// and /* */ comments and string contents removed); state[0] = inside a block comment"""
    out, i, n = [], 0, len(line)
    while i < n:
        if state[0]:
            j = line.find("*/", i)
            if j < 0:
                return "".join(out)
            state[0], i = False, j + 2
        elif line.startswith("//", i):
            break
        elif line.startswith("/*", i):
            state[0], i = True, i + 2
        elif line[i] in "\"'":
            q, j = line[i], i + 1
            while j < n and line[j] != q:
                j += 2 if line[j] == "\\" else 1
            out.append(q + q)
            i = j + 1
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


def src(x):
    d = x if os.path.isdir(os.path.join(x, "src")) or x.endswith("/src") else os.path.realpath(f"{REPO}/bots/{x}")
    return d if d.endswith("/src") else d + "/src"


def files(d):
    return sorted(f for f in os.listdir(d) if f.endswith((".h", ".cpp", ".cc")) and f not in ("rs.h", "rules.h", "nova_all.cpp"))


def check(code):
    """-> [(rule, helper)] for one code line"""
    hits = []
    if not re.search(r"[-+*/<>=]", code) or re.search(r"\b[A-Z][A-Z0-9_]*_TAB\s*\[[^\]]*\]\s*=\s*\{", code):  # flag-table initializers: data, not rules
        return hits
    for name, pat, ctx, helper, skip in RULES:
        if any(s in code for s in skip):
            continue
        for m in pat.finditer(code):  # the context word within 24 characters of the literal (not anywhere on the line)
            if ctx is None or ctx.search(code[max(0, m.start() - 24):m.end() + 24]):
                hits.append((name, helper))
                break
    m = DEFN.match(code)
    if m and m.group(1) not in HELPERS:
        hits.append(("DEF", f"existing helper ({', '.join(h for h in HELPERS if h.split('_')[-1] in m.group(1)) or 'see HELPERS'})"))
    return hits


FENEMY = re.compile(r"\bM\s*\.\s*(f_enemy|d_enemy)\b")


def scan(lines, only=None):
    """-> [(line no, rule, helper, text)] over lines (1-based numbers); only: the set of line numbers to report"""
    st, out, recent = [False], [], []
    for k, ln in enumerate(lines, 1):
        code = strip(ln, st)
        guarded = any("has_enemy" in x for x in recent[-3:] + [code])
        if code.strip():
            recent.append(code)
        if only is not None and k not in only:
            continue
        for rule, helper in check(code):
            out.append((k, rule, helper, ln.strip()[:150]))
        # 10 Nov (Rule Checker's f_enemy audit, via the Builder): M.f_enemy / M.d_enemy are built only when M.has_enemy, which lean
        # champions on draft-memory distances never set; a read needs that guard (this line or the 3 code lines above) or a fallback
        if FENEMY.search(code) and not guarded:
            out.append((k, "FENEMY", "guard with M.has_enemy (or a fallback distance): M.f_enemy/d_enemy are unbuilt without it", ln.strip()[:150]))
    return out


def diff(base, new):
    """-> [(file, line, rule, helper, text)] on NEW's added lines"""
    b, n = src(base), src(new)
    res = []
    for f in files(n):
        A = open(os.path.join(b, f), errors="replace").read().split("\n") if os.path.exists(os.path.join(b, f)) else []
        B = open(os.path.join(n, f), errors="replace").read().split("\n")
        added = set()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, A, B, autojunk=False).get_opcodes():
            if tag in ("replace", "insert"):
                added |= set(range(j1 + 1, j2 + 1))
        if added:
            res += [(f, k, r, h, t) for k, r, h, t in scan(B, added)]
    return res


ALLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ruleslint_allow.txt")


def allowed():
    """(rule, file, text) entries of deliberate policy constants: 'RULE<TAB>file<TAB>a substring of the line' (line numbers shift)"""
    out = []
    if os.path.exists(ALLOW):
        for ln in open(ALLOW):
            x = ln.rstrip("\n").split("\t")
            if len(x) == 3 and not ln.startswith("#"):
                out.append(tuple(x))
    return out


def census(bot):
    """-> [(rule, file, line no, text)] of every site, allow-listed ones removed"""
    d, al, res = src(bot), allowed(), []
    for f in files(d):
        for k, r, h, t in scan(open(os.path.join(d, f), errors="replace").read().split("\n")):
            if not any(r == ar and f == af and at in t for ar, af, at in al):
                res.append((r, f, k, t))
    return res


def ratchet(base, new):
    """-> (base count, new count, Counter of the rules that grew): a merge may not add hand-written rule numbers (owner 6 Nov)"""
    cb, cn = Counter(r for r, *_ in census(base)), Counter(r for r, *_ in census(new))
    return sum(cb.values()), sum(cn.values()), Counter({r: cn[r] - cb[r] for r in cn if cn[r] > cb[r]})


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "ratchet":
        nb, nn, grew = ratchet(a[1], a[2])
        print(f"ruleslint ratchet {a[1]} -> {a[2]}: {nb} -> {nn} hand-written rule numbers" + (f"; GREW: {dict(grew)} (FAIL in mergecheck; a policy "
              f"constant goes in {ALLOW})" if nn > nb else " (ok)"))
        return 1 if nn > nb else 0
    if len(a) < 2 or a[0] not in ("diff", "census"):
        sys.exit(__doc__)
    if a[0] == "diff":
        hits = diff(a[1], a[2])
        print(f"ruleslint {a[1]} -> {a[2]}: {len(hits)} added line(s) with a hand-written rule number" + (" (WARN, primer RULE SINGLE-SOURCE)" if hits else ""))
        for f, k, r, h, t in hits:
            print(f"  WARN {f}:{k} {r}: call {h}  | {t}")
        return 0
    top = int(a[a.index("--top") + 1]) if "--top" in a else 40
    d = src(a[1])
    by = defaultdict(list)
    for f in files(d):
        for k, r, h, t in scan(open(os.path.join(d, f), errors="replace").read().split("\n")):
            by[r].append((f, k, h, t))
    c = Counter({r: len(v) for r, v in by.items()})
    print(f"ruleslint census {a[1]}: {sum(c.values())} sites; " + ", ".join(f"{r} {n}" for r, n in c.most_common()))
    for r, _ in c.most_common():
        print(f"\n== {r} ({len(by[r])}): call {by[r][0][2]}")
        for f, k, h, t in by[r][:top]:
            print(f"  {f}:{k}  {t}")
        if len(by[r]) > top:
            print(f"  ... {len(by[r]) - top} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
