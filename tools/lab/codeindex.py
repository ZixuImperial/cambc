"""Function index of a bot: codeindex.py BOTDIR [FILE...] [--grep WORD]

Lists every function definition in BOTDIR/src as "file:first-last  namespace::name(...)  | comment", where the
comment is the // block right above the definition, plus the compile-time switches (#define NAME value) of the
headers. Agents read this first and then only the line ranges they need (Read with offset/limit), instead of
whole files. --grep keeps only functions whose name, signature or comment contains WORD (case-insensitive).

Heuristic for the code style used here (Allman braces): a definition is a line ending in ')' or ') const' (or a
signature continued over lines) followed by a line holding only '{', at any namespace depth; its end is the
matching '}'. Lambdas and control blocks are skipped because their '{' lines follow if/for/while/switch/else.
"""
import os, re, sys

CONTROL = re.compile(r"^\s*(if|for|while|switch|else|do|try|catch|case|return|namespace|struct|class|enum|union)\b")
NS_OPEN = re.compile(r"^\s*namespace\s+([\w:]*)\s*\{")


def code(s):
    """The line without a trailing // comment (outside string and character literals)."""
    q, i = None, 0
    while i < len(s):
        c = s[i]
        if q:
            if c == "\\":
                i += 1
            elif c == q:
                q = None
        elif c in "\"'":
            q = c
        elif s.startswith("//", i):
            return s[:i].rstrip()
        i += 1
    return s


def index_file(path):
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    out, ns_stack, depth, ns_depths = [], [], 0, []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = NS_OPEN.match(ln)
        if m:
            ns_stack.append(m.group(1) or "(anon)")
            ns_depths.append(depth)
            depth += ln.count("{") - ln.count("}")
            i += 1
            continue
        if ln.strip() == "{" and i > 0:
            # collect the signature: previous non-empty lines back to one that starts the declaration
            j = i - 1
            sig_lines = []
            # (trailing // comments are left out: "long floor = PLAN_EVAL_FLOOR) // PLANNER: ..." ends best_group's)
            while j >= 0 and code(lines[j]).strip() and not code(lines[j]).strip().endswith((";", "}", "{")) and len(sig_lines) < 6:
                sig_lines.insert(0, code(lines[j]).strip())
                if re.match(r"^[\w:<>,\s\*&~\[\]]+\(", lines[j].strip()) and not lines[j].startswith((" ", "\t")):
                    break
                j -= 1
            sig = " ".join(sig_lines)
            is_func = bool(sig) and "(" in sig and not CONTROL.match(sig) and not sig.startswith(("//", "#", "[", "=")) \
                and re.search(r"\)\s*(const)?\s*(noexcept)?\s*(override)?\s*$", sig) and "=" not in sig.split("(")[0]
            if is_func and (lines[j].startswith((" ", "\t")) is False or depth == (ns_depths[-1] + 1 if ns_depths else 0)):
                # find the matching closing brace
                d, k = 0, i
                while k < len(lines):
                    d += lines[k].count("{") - lines[k].count("}")
                    if d == 0:
                        break
                    k += 1
                # comment block above the signature
                c, cj = [], j - 1
                while cj >= 0 and lines[cj].strip().startswith("//"):
                    c.insert(0, lines[cj].strip().lstrip("/").strip())
                    cj -= 1
                # 11 Nov (b2018): `static __attribute__((always_inline)) inline T f(...)` was indexed as a function named
                # __attribute__ (its first '(' is the attribute's), so every always_inline function looked changed in reopen
                nsig = re.sub(r"\b(__attribute__|__declspec|alignas)\s*\(\(?[^()]*(\([^()]*\)[^()]*)*\)?\)\s*", "", sig)
                name = nsig.split("(")[0].split()[-1] if nsig.split("(")[0].split() else sig
                ns = "::".join(x for x in ns_stack if x != "(anon)")
                out.append((j + 1, k + 1, ns, name, sig, " ".join(c)))
                depth += sum(l.count("{") - l.count("}") for l in lines[i:k + 1])
                i = k + 1
                continue
        depth += ln.count("{") - ln.count("}")
        while ns_depths and depth <= ns_depths[-1]:
            ns_depths.pop(); ns_stack.pop()
        i += 1
    return out


def switches(src):
    res = []
    for f in sorted(os.listdir(src)):
        if not f.endswith((".h", ".cpp", ".cc")):
            continue
        for n, ln in enumerate(open(os.path.join(src, f), encoding="utf-8", errors="replace"), 1):
            m = re.match(r"^\s*#define\s+([A-Z][A-Z0-9_]{2,})\s+(\S.*)?$", ln)
            if m and not m.group(1).endswith("_H"):
                res.append(f"{f}:{n}  {m.group(1)} {(m.group(2) or '').strip()[:60]}")
    return res


def main():
    args = [a for a in sys.argv[1:]]
    word = None
    if "--grep" in args:
        k = args.index("--grep"); word = args[k + 1].lower(); del args[k:k + 2]
    bot = args[0].rstrip("/")
    src = os.path.join(bot, "src") if os.path.isdir(os.path.join(bot, "src")) else bot
    files = args[1:] or sorted(f for f in os.listdir(src) if f.endswith((".cpp", ".cc", ".h")))
    total = 0
    for f in files:
        p = os.path.join(src, f)
        if not os.path.isfile(p):
            continue
        n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        items = index_file(p)
        if word:
            items = [it for it in items if word in (it[3] + it[4] + it[5]).lower()]
        if not items and word:
            continue
        print(f"== {f} ({n} lines, {len(items)} functions)")
        for a, b, ns, name, sig, com in items:
            total += 1
            s = sig if len(sig) <= 110 else sig[:107] + "..."
            print(f"  {f}:{a}-{b}  {s}" + (f"  | {com[:160]}" if com else ""))
    if not word:
        sw = switches(src)
        if sw:
            print("== compile-time switches (#define)")
            for s in sw:
                print("  " + s)
    print(f"({total} functions listed)")


if __name__ == "__main__":
    main()
