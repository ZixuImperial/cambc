#!/usr/bin/env python3
"""deathreset: persistent per-champion state that a death does not reset (Tool Builder, 10 Nov; Coordinator / Rule Checker: the DRS rows,
a spawn-crystal trip, region clock and hole-shortcut commit that outlived a death and steered the first live turns after respawn).

Each champion is its own bot instance, so every namespace-scope variable and every function-local `static` persists across turns, and
across a death. This lists those variables and says which ones the dead-turn path resets: the bodies reachable from the dead-turn entry
(default brain::dead_turn, which calls econ::death_reset and the dead shop) through calls up to --depth (default 4) levels, scanning
for assignments (x = / x[..] = / x.f = / x op= / x.clear() / x = {} / memset/fill of x). A variable is only a CANDIDATE: many are
meant to persist (learned map facts, foe models, draft memory). The ranking puts names that look like per-life state first: round,
pos, target/tgt, commit, trip, hold, clock, latch, since, last, pending, plan, step, prev.
usage: python3 -I tools/lab/deathreset.py BOT [--entry dead_turn] [--depth 4] [--all] [--tsv OUT]
  default output: the ranked unreset candidates (top 60); --all also lists the reset ones; --tsv writes every variable."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codeindex as CI  # noqa: E402

REPO = "/homes/USER/cambc"
DECL = re.compile(r"^\s*(?:static\s+|inline\s+|thread_local\s+)*(?!const\b|constexpr\b|using\b|typedef\b|template\b|struct\b|class\b|enum\b|"
                  r"namespace\b|return\b|extern\b|friend\b|static_assert\b|public\b|private\b)"
                  r"([A-Za-z_][\w:<>,\s\*&]*?)\s+\**([A-Za-z_]\w*)\s*(\[[^\]]*\])*\s*(=[^;]*|\{[^;]*\})?\s*;")
LOCAL_STATIC = re.compile(r"^\s*static\s+(?!const\b|constexpr\b)([A-Za-z_][\w:<>,\s\*&]*?)\s+\**([A-Za-z_]\w*)\s*(\[[^\]]*\])*\s*(=[^;]*|\{[^;]*\})?\s*;")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*(?:<[^<>;()]*>)?\s*\(")
ASSIGN = re.compile(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*(?:\.\s*\w+\s*)*(?:=(?!=)|\+=|-=|\|=|&=|\^=|<<=|>>=)")
MEMBER_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(clear|reset|fill|assign|resize)\s*\(")
FILL = re.compile(r"\b(?:memset|std::fill|fill|std::memset)\s*\(\s*&?\s*([A-Za-z_]\w*)")
ONELINE = re.compile(r"^\s*(?:[\w:<>,\*&]+\s+)+\**([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{.*\}\s*$")
HINT = re.compile(r"round|pos|target|tgt|commit|trip|hold|clock|latch|since|last|pending|plan|step|prev|until|_r$|_rd|goal|dest|lock", re.I)
SKIPTYPES = {"return", "else", "delete", "goto", "case", "throw", "co_return"}


def load(bot):
    src = os.path.join(REPO, "bots", bot, "src") if not os.path.isdir(bot) else os.path.join(bot, "src") if os.path.isdir(os.path.join(bot, "src")) else bot
    files = {}
    for fn in sorted(os.listdir(src)):
        if fn.endswith((".cc", ".cpp", ".h", ".hpp")):
            files[fn] = open(os.path.join(src, fn), encoding="utf-8", errors="replace").read().split("\n")
    return src, files


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    bot, entry, depth = a[0], opt("--entry", "dead_turn,turn_senses"), int(opt("--depth", "4"))  # 10 Nov (Rule Checker): combat::observe resets on dead turns too
    src, files = load(bot)
    funcs = {}  # name -> [(file, start, end)]
    ranges = {}
    for fn in files:
        idx = CI.index_file(os.path.join(src, fn))
        ranges[fn] = [(s, e) for s, e, *_ in idx]
        for s, e, ns, name, sig, com in idx:
            funcs.setdefault(name.split("::")[-1].split("<")[0], []).append((fn, s, e))
        for i, ln in enumerate(files[fn], 1):  # one-line functions (`void sc_end() { SC = SCTrip{}; }`): codeindex wants '{' on its own line
            m = ONELINE.match(CI.code(ln))
            if m and m.group(1) not in ("if", "for", "while", "switch", "return"):
                funcs.setdefault(m.group(1), []).append((fn, i, i))
    # persistent variables
    vars_ = {}  # name -> (file, line, kind, text)
    for fn, ls in files.items():
        inside = set()
        for s, e in ranges[fn]:
            inside.update(range(s, e + 1))
        agg, d = set(), 0  # 10 Nov (Rule Checker): struct/class bodies hold fields, not persistent variables
        for i, ln in enumerate(ls, 1):
            c = CI.code(ln)
            if d == 0 and re.match(r"^\s*(?:template\s*<[^>]*>\s*)?(?:struct|class|union)\s+\w+[^;]*$", c) and i not in inside:
                d = max(1, c.count("{") - c.count("}")) if "{" in c else -1  # -1: the body's '{' is on a later line
                agg.add(i)
                continue
            if d != 0:
                if d == -1 and "{" in c:
                    d = 0
                d += c.count("{") - c.count("}")
                agg.add(i)
                if d <= 0:
                    d = 0
                continue
        for i, ln in enumerate(ls, 1):
            if i in agg:
                continue
            c = CI.code(ln)
            if not c.strip() or c.lstrip().startswith(("#", "//", "*", "/*")) or "(" in c.split("=")[0]:
                continue
            if i in inside:
                m = LOCAL_STATIC.match(c)
                kind = "local static"
            else:
                m = DECL.match(c) if not c.startswith(("\t\t", "        ")) else None
                kind = "namespace"
            if m and not ({"const", "constexpr", "consteval"} & set(re.split(r"[\s\*&]+", m.group(1)))) \
                    and m.group(1).split()[-1] not in SKIPTYPES and m.group(2) not in vars_:
                vars_[m.group(2)] = (fn, i, kind, c.strip()[:110])
    # reset set: the dead-turn path
    entries = [e for e in entry.split(",") if e]
    seen, todo, reset = set(), [(e, 0) for e in entries], {}
    while todo:
        name, d = todo.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        for fn, s, e in funcs[name]:
            body = "\n".join(CI.code(x) for x in files[fn][s - 1:e])
            for rx in (ASSIGN, MEMBER_CALL, FILL):
                for m in rx.finditer(body):
                    reset.setdefault(m.group(1), name)
            if d < depth:
                for m in CALL.finditer(body):
                    if m.group(1) not in seen and m.group(1) in funcs:
                        todo.append((m.group(1), d + 1))
    if not any(e in seen for e in entries):
        sys.exit(f"deathreset: none of the entry functions {entry} found in {src}")
    rows = []
    for v, (fn, ln, kind, txt) in vars_.items():
        rows.append((v in reset, 0 if HINT.search(v) else 1, fn, ln, v, kind, reset.get(v, ""), txt))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    nr = sum(1 for r in rows if not r[0])
    print(f"deathreset {bot}: {len(vars_)} persistent variables; the dead-turn path ({entry}, {len(seen)} functions to depth {depth}) "
          f"resets {len(rows) - nr}; {nr} never reset on death ({sum(1 for r in rows if not r[0] and r[1] == 0)} with per-life names)")
    print("CANDIDATES (not reset on death; per-life names first; many are meant to persist: judge each)")
    for r in [x for x in rows if not x[0]][:60 if "--all" not in a else None]:
        print(f"  {'*' if r[1] == 0 else ' '} {r[2]}:{r[3]:<5} {r[4]:<28} {r[5]:<12} {r[7]}")
    if "--all" in a:
        print("RESET on death")
        for r in [x for x in rows if x[0]]:
            print(f"    {r[2]}:{r[3]:<5} {r[4]:<28} by {r[6]}")
    if "--tsv" in a:
        with open(opt("--tsv", ""), "w") as f:
            f.write("reset\tper_life_name\tfile\tline\tvar\tkind\treset_by\tdecl\n")
            for r in rows:
                f.write("\t".join(str(x) for x in (int(r[0]), int(r[1] == 0), *r[2:])) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
