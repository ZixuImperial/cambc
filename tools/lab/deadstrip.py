#!/usr/bin/env python3
"""deadstrip: remove code that can't run in a bot whose flags are final (Tool builder 2, 6 Nov; owner via the Builder: "get rid of dead
paths and leave one code path per fix"). A repeatable transform, run LAST, after the keeper's final merge and with the bake, so it never
collides with fixes in flight. It writes a NEW copy; the source bot is only read, and ideastore keeps old versions.

  python3 -I tools/lab/deadstrip.py BOT NEW [--keep X_TAB,Y_TAB] [--keep-file F] [--roots a,b] [--check] [--maps N] [--seed S] [--no-unused] [--report DIR]
  python3 -I tools/lab/deadstrip.py check NEW_bk NEW [--maps N] [--seed S]     verify an existing strip again
  python3 -I tools/lab/deadstrip.py find FLAG [NEW]              what was removed for a flag or table (FLAG, X_TAB or a helper's name)

What it does to the copy, in order, repeated until nothing changes:
  1. bake: every volatile table becomes constexpr (same rule as /data/zw4424/st/b1395/bake.sh), except --keep tables. A kept table stays
     volatile, its reads stay unknown, and every branch on it stays, so a later flip of it still works. Later flips of other tables stop
     working on the copy: keep what a later flip needs (primer RULE FLIP-DECL).
  2. fold: flag tests with known values, through macros and qualified names. An `if`/`while`/`?:` with a known test loses its dead arm;
     `A && B` loses known operands. An operand is dropped only if C would skip it or it has no side effect (`f() && OFF` stays).
     Local `const bool x = FLAG;` values fold too.
  3. unreachable statements after a `return`, `break` or `continue`, and empty `if`s and `else`s.
  4. unused: functions, macros, tables and plain globals nothing live reaches (mark and sweep from main, globals with constructors and
     every token outside these items). Struct members and enums are not touched. Overloads share a name, so they stay or go together.

Records (--report, default /data/zw4424/st/deadstrip/NEW): report.txt (lines removed per file, flags folded, what stayed), removed.json
(each removal: flags behind it, file, function, kind, test, the exact text), by_flag/NAME.txt, full.diff (source -> stripped).
To restore a closed idea: `find` shows what went; its code is in the source bot (`ideastore.py restore SOURCE`) and in removed.json.

--check builds the plain baked copy NEW_bk and NEW and compares the wasm. Byte identity passes at once, but is rare: a helper whose other
callers went dead gets inlined into the last one. Otherwise cxeident at unlimited fuel on --maps maps (default 40, both seats): every game
must match and the same work's fuel must be within .5%. Exit 0 = pass, 1 = fail, 2 = bad use."""
import collections
import difflib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time

REPO = "/homes/zw4424/cambc"
OUT = "/data/zw4424/st/deadstrip"
TOK = re.compile(r"""
 (?P<ws>[ \t\r\n\f\v]+|\\\r?\n)
|(?P<lc>//[^\n]*)
|(?P<bc>/\*.*?\*/)
|(?P<raw>R"(?P<d>[^(\s]*)\(.*?\)(?P=d)")
|(?P<str>(?:u8|u|U|L)?"(?:\\.|[^"\\\n])*")
|(?P<chr>(?:u8|u|U|L)?'(?:\\.|[^'\\\n])*')
|(?P<num>\.?[0-9](?:[eEpP][+-]|[0-9a-zA-Z_.'])*)
|(?P<id>[A-Za-z_][A-Za-z_0-9]*)
|(?P<op><<=|>>=|\.\.\.|->\*|<=>|::|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%=|&=|\|=|\^=|\#\#|[-+*/%&|^~!=<>?:;,.(){}\[\]\#@$\\])
""", re.X | re.S)
OPEN = {"(": ")", "[": "]", "{": "}"}
ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
TYPEKW = {"const", "constexpr", "static", "auto", "int", "float", "bool", "char", "double", "long", "short", "unsigned", "signed", "void"}
NOTDECL = {"return", "if", "else", "for", "while", "do", "switch", "case", "default", "break", "continue", "goto", "delete", "throw", "new",
           "sizeof", "co_return", "using", "typedef"}
PLAIN = {"int", "float", "bool", "char", "double", "long", "short", "unsigned", "signed"} | \
        {f"{p}int{n}_t" for p in ("", "u") for n in (8, 16, 32, 64)} | {"size_t", "vec2"}
BAKE = [(re.compile(r"^(\s*)inline const volatile (int|float|unsigned|std::uint32_t|std::int32_t|short|std::uint8_t|std::int8_t|std::uint16_t) (\w*)"),
         r"\1inline constexpr \2 \3"),
        (re.compile(r"^(\s*)static const volatile (int|float|unsigned) (\w*)"), r"\1static constexpr \2 \3")]


class Unknown(Exception):
    pass


class Seq:
    """code tokens of a span of one file, with bracket matches"""

    def __init__(self, text, lo=0, hi=None, toks=None):
        self.text = text
        self.T, self.K, self.S, self.E = [], [], [], []
        for k, t, s, e in (toks if toks is not None else lex(text, lo, len(text) if hi is None else hi)):
            self.T.append(t), self.K.append(k), self.S.append(s), self.E.append(e)
        self.n = len(self.T)
        self.M, self.P = {}, [-1] * self.n  # M: bracket matches both ways; P: index of the enclosing `{`
        st, br = [], []
        for i, t in enumerate(self.T):
            if self.K[i] != "op":
                self.P[i] = br[-1] if br else -1
                continue
            if t in OPEN:
                self.P[i] = br[-1] if br else -1
                st.append(i)
                if t == "{":
                    br.append(i)
            elif t in (")", "]", "}"):
                if not st or OPEN[self.T[st[-1]]] != t:
                    raise ValueError(f"bracket mismatch at {text.count(chr(10), 0, self.S[i]) + 1}")
                o = st.pop()
                self.M[o], self.M[i] = i, o
                if t == "}":
                    br.pop()
                self.P[i] = br[-1] if br else -1
            else:
                self.P[i] = br[-1] if br else -1
        if st:
            raise ValueError("unclosed bracket")

    def src(self, a, b):
        return self.text[self.S[a]:self.E[b - 1]] if b > a else ""


def lex(text, lo, hi):
    pos = lo
    while pos < hi:
        m = TOK.match(text, pos, hi)
        if not m:
            pos += 1
            continue
        k = m.lastgroup
        if k == "d":
            k = "raw"
        if k not in ("ws", "lc", "bc"):
            yield (k, m.group(), m.start(), m.end())
        pos = m.end()


class Dir:
    __slots__ = ("kind", "name", "params", "body", "s", "e", "bs")


class File:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        self.text = open(path, encoding="utf-8", errors="surrogateescape").read()
        self.parse()

    def parse(self):
        t, toks, dirs = self.text, [], []
        pos, n, bol = 0, len(t), True
        while pos < n:
            m = TOK.match(t, pos)
            if not m:
                pos += 1
                continue
            k = m.lastgroup
            if k == "d":
                k = "raw"
            if k == "ws":
                bol = bol or "\n" in m.group()
            elif k == "lc":
                pass
            elif k == "bc":
                bol = bol or "\n" in m.group()
            elif k == "op" and m.group() == "#" and bol:
                e = m.end()
                while True:
                    j = t.find("\n", e)
                    j = n if j < 0 else j
                    if j > 0 and t[j - 1] == "\\":
                        e = j + 1
                        continue
                    break
                dirs.append(self.directive(m.start(), j))
                pos = j
                continue
            else:
                toks.append((k, m.group(), m.start(), m.end()))
                bol = False
            pos = m.end()
        self.dirs = dirs
        self.code = Seq(t, toks=toks)

    def directive(self, s, e):
        d = Dir()
        d.s, d.e, d.params, d.body, d.name, d.bs = s, e, None, None, "", e
        m = re.compile(r"#[ \t]*(\w+)[ \t]*").match(self.text, s, e)
        d.kind = m.group(1) if m else ""
        if not m:
            return d
        p = m.end()
        if d.kind in ("define", "undef", "ifdef", "ifndef"):
            m2 = re.compile(r"\w+").match(self.text, p, e)
            d.name = m2.group() if m2 else ""
            p = m2.end() if m2 else p
        if d.kind == "define":
            if p < e and self.text[p] == "(":
                c = self.text.find(")", p, e)
                d.params = [x.strip() for x in self.text[p + 1:c].split(",") if x.strip()]
                p = c + 1
            d.bs = p
        else:
            d.bs = p
        d.body = Seq(self.text, p, e) if d.kind in ("define", "if", "elif", "ifdef", "ifndef") else None
        return d


def split_top(T, seps):
    """indices of top-level tokens in seps"""
    d, out = 0, []
    for i, t in enumerate(T):
        if t in ("(", "[", "{"):
            d += 1
        elif t in (")", "]", "}"):
            d -= 1
        elif d == 0 and t in seps:
            out.append(i)
    return out


def strip_parens(T):
    while len(T) >= 2 and T[0] == "(":
        d = 0
        for i, t in enumerate(T):
            d += t in ("(", "[", "{")
            d -= t in (")", "]", "}")
            if d == 0:
                break
        if i != len(T) - 1:
            break
        T = T[1:-1]
    return T


Res = collections.namedtuple("Res", "val pure used")
PREC = {"*": 10, "/": 10, "%": 10, "+": 9, "-": 9, "<<": 8, ">>": 8, "<": 7, ">": 7, "<=": 7, ">=": 7, "==": 6, "!=": 6, "&": 5, "^": 4, "|": 3}


class F32(float):
    """a C float: results round to 32 bits (a plain Python float is a C double)"""


def f32(x):
    return F32(struct.unpack("f", struct.pack("f", x))[0])


def num(t):
    s = t.replace("'", "")
    low = s.lower()
    if low.startswith("0x"):
        return int(low.rstrip("ul"), 16)
    if re.fullmatch(r"[0-9]+[ul]*", low):
        return int(low.rstrip("ul"), 8 if len(low.rstrip("ul")) > 1 and low[0] == "0" else 10)
    try:
        return f32(float(low[:-1])) if low.endswith("f") else float(low.rstrip("l"))
    except (ValueError, OverflowError):
        raise Unknown(t) from None


class Ev:
    """values of macros, tables and constants, and three-valued evaluation of C expressions"""

    def __init__(self, files, keep, only_not=None):
        self.macros, self.tabs, self.consts, self.keep, self.ftab = {}, {}, {}, keep, {}
        self.bad = set(only_not or ())
        seen = collections.Counter()
        for f in files:
            for d in f.dirs:
                if d.kind == "define":
                    v = (tuple(d.params) if d.params is not None else None, tuple(d.body.T))
                    if d.name in self.macros and self.macros[d.name] != v:
                        self.bad.add(d.name)  # two different bodies: unknown
                    self.macros[d.name] = v
            T = f.code.T
            for i, t in enumerate(T):
                if t in ("constexpr", "const") and i + 2 < len(T):
                    self.table_at(f.code, i, seen)
        for f in files:  # a local or parameter with a constant's name hides it there: not a constant anywhere
            T, K = f.code.T, f.code.K
            for i in range(1, f.code.n - 1):
                if T[i] not in self.consts or T[i + 1] not in (",", ")", "=", ";", "[", "{"):
                    continue
                p = T[i - 1]  # `int N`, `Foo N`, `const int& N`; not the `x & N` of an expression
                decl = p in TYPEKW or p in PLAIN or (K[i - 1] == "id" and p not in NOTDECL) or \
                    (p in ("&", "*", "&&") and i > 1 and (T[i - 2] in TYPEKW or T[i - 2] in PLAIN))
                if decl and not Ev.ns_scope(f.code, i):
                    self.bad.add(T[i])
        for k in self.bad:
            self.macros.pop(k, None)
        self.memo = {}
        self.interesting = self.closure()

    def table_at(self, c, i, seen):
        """`constexpr TYPE NAME[n] = { ... };` or `constexpr TYPE NAME = expr;` at namespace scope (an upper-case NAME)"""
        T = c.T
        if c.P[i] != -1 and not self.ns_scope(c, i):
            return
        j = i + 1
        if T[j] == "volatile":
            return
        while j < c.n and (T[j] in PLAIN or T[j] in ("std", "::")):
            j += 1
        if j == i + 1 or j + 1 >= c.n or c.K[j] != "id" or not re.fullmatch(r"[A-Z][A-Z0-9_]*", T[j]):
            return
        name = T[j]
        self.ftab[name] = "float" in T[i:j] or "double" in T[i:j]
        if T[j + 1] == "[" and T[c.M[j + 1] + 1] == "=" and T[c.M[j + 1] + 2] == "{":
            a = c.M[j + 1] + 2
            b = c.M[a]
            inner = T[a + 1:b]
            cuts = [-1] + split_top(inner, {","}) + [len(inner)]
            val = [inner[x + 1:y] for x, y in zip(cuts, cuts[1:])]
            if any("{" in v for v in val):
                self.bad.add(name)
                return
        elif T[j + 1] == "=":
            while True:  # `constexpr int A = 1, B = 2;` declares both
                b = j + 2
                while b < c.n and T[b] not in (";", ","):
                    b = c.M[b] + 1 if T[b] in OPEN else b + 1
                self.add_const(T[j], T[j + 2:b], "[" == T[j + 1], "float" in T[i:j] or "double" in T[i:j])
                if b >= c.n or T[b] == ";" or c.K[b + 1] != "id" or T[b + 2] != "=":
                    return
                j = b + 1
        else:
            return
        if name in self.tabs and list(self.tabs[name]) != list(val):
            self.bad.add(name)
        self.tabs[name] = val
        seen[name] += 1

    def add_const(self, name, val, _arr, flt):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            return
        if name in self.consts and list(self.consts[name]) != list(val):
            self.bad.add(name)
        self.consts[name] = val
        self.ftab[name] = flt

    @staticmethod
    def ns_scope(c, i):
        p = c.P[i]
        while p != -1:
            q = p - 1
            while q >= 0 and (c.K[q] == "id" or c.T[q] == "::") and c.T[q] != "namespace":
                q -= 1
            if q < 0 or c.T[q] != "namespace":
                return False
            p = c.P[p]
        return True

    def closure(self):
        """names whose value can depend on a known table or constant"""
        s = {k for k in self.tabs if k not in self.bad} | {k for k in self.consts if k not in self.bad}
        grew = True
        for k, (_, b) in self.macros.items():
            if len(b) == 1 and b[0][0].isdigit():
                s.add(k)
        while grew:
            grew = False
            for k, (_, b) in self.macros.items():
                if k not in s and any(x in s for x in b):
                    s.add(k)
                    grew = True
        return s

    # expansion
    def expand(self, T, hide=frozenset(), used=None, depth=0):
        if depth > 60:
            raise Unknown("depth")
        out, i, n = [], 0, len(T)
        while i < n:
            t = T[i]
            m = self.macros.get(t) if t not in hide else None
            if m is None:
                out.append(t)
                i += 1
                continue
            params, body = m
            if params is None:
                out += self.expand(list(body), hide | {t}, used, depth + 1)
                i += 1
                continue
            if i + 1 >= n or T[i + 1] != "(":
                out.append(t)
                i += 1
                continue
            d, j, args, cur = 0, i + 1, [], []
            while j < n:
                x = T[j]
                if x in ("(", "[", "{"):
                    d += 1
                    if d > 1:
                        cur.append(x)
                elif x in (")", "]", "}"):
                    d -= 1
                    if d == 0:
                        break
                    cur.append(x)
                elif x == "," and d == 1:
                    args.append(cur)
                    cur = []
                else:
                    cur.append(x)
                j += 1
            if j >= n:
                raise Unknown("macro args")
            args.append(cur)
            if "#" in body or "##" in body or "__VA_ARGS__" in body or (len(args) != len(params) and not (params == [] or params == ())):
                raise Unknown("macro form")
            sub = []
            amap = dict(zip(params, args))
            for x in body:
                if x in amap:
                    sub += self.expand(amap[x], hide, used, depth + 1)
                else:
                    sub.append(x)
            out += self.expand(sub, hide | {t}, used, depth + 1)
            i = j + 1
        return out

    @staticmethod
    def impure(T):
        for i, t in enumerate(T):
            if t in ("++", "--") or t in ASSIGN:
                return True
            if t == "(" and i and (T[i - 1] == ")" or T[i - 1] == "]" or T[i - 1] == ">" or
                                   (re.match(r"[A-Za-z_]", T[i - 1]) and T[i - 1] not in ("sizeof", "static_cast"))):
                return True
        return False

    def ev(self, T):
        """Res for already expanded tokens"""
        T = strip_parens(list(T))
        if not T:
            return Res(None, True, frozenset())
        if split_top(T, {","}) or any(T[i] in ASSIGN for i in split_top(T, ASSIGN)):
            return Res(None, False, frozenset())
        q = split_top(T, {"?"})
        if q:
            c = self.ev(T[:q[0]])
            nest, col = 0, None
            for i in split_top(T, {"?", ":"}):
                if i <= q[0]:
                    continue
                if T[i] == "?":
                    nest += 1
                elif nest:
                    nest -= 1
                else:
                    col = i
                    break
            if col is None:
                return Res(None, False, frozenset())
            a, b = self.ev(T[q[0] + 1:col]), self.ev(T[col + 1:])
            if c.val is None:
                return Res(None, c.pure and a.pure and b.pure, c.used | a.used | b.used)
            r = a if c.val else b
            return Res(r.val, c.pure and r.pure, c.used | r.used)
        for op, stop in (("||", True), ("&&", False)):
            cuts = split_top(T, {op})
            if not cuts:
                continue
            parts = [T[x + 1:y] for x, y in zip([-1] + cuts, cuts + [len(T)])]
            pure, used, unk = True, frozenset(), False
            for p in parts:
                r = self.ev(p)
                used |= r.used
                if r.val is not None and bool(r.val) == stop:  # decides: later operands are never run
                    if unk or not r.pure or not pure:
                        return Res(int(stop) if (pure and r.pure) else None, pure and r.pure, used)
                    return Res(int(stop), True, used)
                pure = pure and r.pure
                unk = unk or r.val is None
            return Res(None if unk else int(not stop), pure, used)
        used = set()
        try:
            v, i = self.arith(T, 0, 0, used)
            if i != len(T):
                raise Unknown("tail")
            return Res(v, True, frozenset(used))
        except (Unknown, IndexError, ZeroDivisionError, OverflowError):
            return Res(None, not self.impure(T), frozenset(used))

    def arith(self, T, i, minp, used):
        v, i = self.unary(T, i, used)
        while i < len(T):
            op = T[i]
            p = PREC.get(op)
            if p is None or p <= minp:
                break
            w, i = self.arith(T, i + 1, p, used)
            single = False
            if isinstance(v, float) or isinstance(w, float):
                if op in ("%", "&", "|", "^", "<<", ">>"):
                    raise Unknown("float op")
                single = not (type(v) is float or type(w) is float)  # no double operand: the arithmetic is in float
            if op == "*":
                v = v * w
            elif op == "/":
                v = v / w if isinstance(v, float) or isinstance(w, float) else int(abs(v) // abs(w)) * (1 if (v < 0) == (w < 0) else -1)
            elif op == "%":
                v = abs(v) % abs(w) * (1 if v >= 0 else -1)
            elif op == "+":
                v = v + w
            elif op == "-":
                v = v - w
            elif op == "<<":
                v = v << w
                if abs(v) >= 1 << 31:
                    raise Unknown("wide shift")
            elif op == ">>":
                v = v >> w
            elif op == "<":
                v = int(v < w)
            elif op == ">":
                v = int(v > w)
            elif op == "<=":
                v = int(v <= w)
            elif op == ">=":
                v = int(v >= w)
            elif op == "==":
                v = int(v == w)
            elif op == "!=":
                v = int(v != w)
            elif op == "&":
                v = v & w
            elif op == "^":
                v = v ^ w
            elif op == "|":
                v = v | w
            if single and op in ("*", "/", "+", "-"):
                v = f32(v)
        return v, i

    def unary(self, T, i, used):
        t = T[i]
        if t == "!":
            v, i = self.unary(T, i + 1, used)
            return int(not v), i
        if t == "~":
            v, i = self.unary(T, i + 1, used)
            if isinstance(v, float):
                raise Unknown("~float")
            return ~v, i
        if t in ("-", "+"):
            v, i = self.unary(T, i + 1, used)
            return (-v if t == "-" else v), i
        if t == "(":
            d, j = 0, i
            while True:
                d += T[j] in ("(", "[", "{")
                d -= T[j] in (")", "]", "}")
                if d == 0:
                    break
                j += 1
            r = self.ev(T[i + 1:j])
            used |= r.used
            if r.val is None or not r.pure:
                raise Unknown("group")
            return r.val, j + 1
        if t == "true":
            return 1, i + 1
        if t == "false":
            return 0, i + 1
        if t == "static_cast" and T[i + 1] == "<":
            j = T.index(">", i)
            ty = T[i + 2:j]
            if T[j + 1] != "(":
                raise Unknown("cast")
            v, k = self.unary(T, j + 1, used)
            if ty and ty[-1] == "float":
                return f32(v), k
            if ty and ty[-1] == "double":
                return float(v), k
            if ty == ["int"]:
                return int(v), k
            raise Unknown("cast type")
        if t[0].isdigit() or t[0] == ".":
            return num(t), i + 1
        if t == "::":
            return self.unary(T, i + 1, used)
        if re.match(r"[A-Za-z_]", t):
            while i + 2 < len(T) and T[i + 1] == "::":
                i += 2
                t = T[i]
            if t in self.bad:
                raise Unknown(t)
            if t in self.tabs and i + 1 < len(T) and T[i + 1] == "[":
                d, j = 0, i + 1
                while True:
                    d += T[j] == "["
                    d -= T[j] == "]"
                    if d == 0:
                        break
                    j += 1
                r = self.ev(T[i + 2:j])
                used |= r.used
                if r.val is None or not isinstance(r.val, int) or not 0 <= r.val < len(self.tabs[t]):
                    raise Unknown("index")
                used.add(t)
                e = self.val(("t", t, r.val), self.tabs[t][r.val])
                return (f32(e) if self.ftab.get(t) else e), j + 1
            if t in self.consts:
                used.add(t)
                e = self.val(("c", t), self.consts[t])
                return (f32(e) if self.ftab.get(t) else e), i + 1
        raise Unknown(t)

    def val(self, key, toks):
        if key not in self.memo:
            self.memo[key] = None
            r = self.ev(self.expand(list(toks))) if toks else Res(None, True, frozenset())
            self.memo[key] = r
        r = self.memo[key]
        if r is None or r.val is None:
            raise Unknown(str(key))
        return r.val

    def eval(self, T):
        try:
            return self.ev(self.expand(list(T)))
        except (Unknown, IndexError, RecursionError):
            return Res(None, not self.impure(T), frozenset())

    def boolish(self, T):
        try:
            X = strip_parens(self.expand(list(T)))
        except (Unknown, IndexError, RecursionError):
            return False
        if split_top(X, {"&", "|", "^", "?", ","}) or "static_cast" in X or "<" in X and ">" in X and "::" in X:
            return False  # the `<` of a cast or template is no comparison
        if split_top(X, {"==", "!=", "<", ">", "<=", ">=", "&&", "||"}):
            return True
        return bool(X) and (X[0] == "!" or X == ["true"] or X == ["false"])


class Edit:
    __slots__ = ("s", "e", "new", "kind", "test", "used", "file", "func", "line", "text", "arm")

    def __init__(self, s, e, new, kind, test="", used=()):
        self.s, self.e, self.new, self.kind, self.test, self.used, self.arm = s, e, new, kind, test, tuple(sorted(used)), None


class Strip:
    def __init__(self, src, keep, roots):
        self.dir = src
        self.keep, self.roots = keep, set(roots) | {"main"}
        self.files = [File(os.path.join(src, x)) for x in sorted(os.listdir(src)) if x.endswith((".h", ".cpp", ".cc"))]
        self.log = []
        self.stayed = collections.Counter()
        self.casts = 0
        self.only_not = None
        self.flags = compile_flags(os.path.dirname(src.rstrip("/")))
        os.makedirs(OUT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix=".tmp_", dir=OUT)

    def reparse(self, changed=None):
        for f in self.files:
            if changed is None or f in changed:
                f.parse()
        self.ev = Ev(self.files, self.keep, self.only_not)

    # statements
    @staticmethod
    def stmt_end(c, i):
        """index just past the statement that starts at token i"""
        T, n = c.T, c.n
        if i >= n:
            raise ValueError("eof")
        t = T[i]
        if t == "{":
            return c.M[i] + 1
        if t == "if":
            j = i + 1
            if T[j] == "constexpr":
                j += 1
            e = Strip.stmt_end(c, Strip.skip_attr(c, c.M[j] + 1))
            if e < n and T[e] == "else":
                e = Strip.stmt_end(c, e + 1)
            return e
        if t in ("for", "while", "switch"):
            return Strip.stmt_end(c, Strip.skip_attr(c, c.M[i + 1] + 1))
        if t == "do":
            e = Strip.stmt_end(c, i + 1)
            return c.M[e + 1] + 2
        if t in ("case", "default"):
            j = i
            while T[j] != ":":
                j += 1
            return Strip.stmt_end(c, j + 1)
        j = i
        while j < n and T[j] != ";":
            if T[j] in OPEN:
                j = c.M[j]
            elif T[j] in (")", "]", "}"):
                raise ValueError("stray closer")
            j += 1
        return j + 1

    @staticmethod
    def skip_attr(c, i):
        while i < c.n and c.T[i] == "[" and c.T[i + 1] == "[":
            i = c.M[i] + 1
        return i

    def bare(self, c, i):
        """is the statement at i the sole body of a control header (so it can't just vanish)?"""
        if i == 0:
            return None
        j = i - 1
        while j > 0 and c.T[j] == "]" and c.T[c.M[j] - 1] == "[":  # [[likely]]
            j = c.M[c.M[j]] - 1 if False else c.M[j] - 2
        p = c.T[j]
        if p in ("else", "do"):
            return p
        if p == ")":
            o = c.M[j]
            if o > 0 and c.T[o - 1] in ("if", "for", "while", "switch", "constexpr"):
                return "ctl"
        return None

    @staticmethod
    def decl_names(c, a, b):
        """names declared directly in the block body (a, b)"""
        names, i = [], a
        while i < b:
            try:
                e = min(Strip.stmt_end(c, i), b)
            except (ValueError, IndexError, KeyError):
                return None
            t = c.T[i]
            if t in TYPEKW or (c.K[i] == "id" and t not in NOTDECL):
                j = i
                while j < e and (c.T[j] in TYPEKW or c.T[j] == "::" or (c.K[j] == "id" and j + 1 < e and c.T[j + 1] in ("::", "<"))):
                    if c.T[j + 1] == "<":
                        d = 0
                        while j < e:
                            d += c.T[j] == "<"
                            d -= c.T[j] == ">"
                            d -= 2 * (c.T[j] == ">>")
                            j += 1
                            if d <= 0:
                                break
                        break
                    j += 1
                if j > i and c.K[j] == "id" and j + 1 < e and c.K[j + 1] == "id" and c.T[j - 1] == "::":
                    j += 1  # 12 Nov (TB: v826 bake, `const std::uint64_t k` in an unwrapped TSZ_ON(8) block was not seen, so the outer `k` clashed): step past a qualified type's last name
                typ = j > i or (c.K[j] == "id" and j + 1 < e and (c.K[j + 1] == "id" or c.T[j + 1] in ("&", "*", "&&")))
                if typ:
                    if c.K[j] == "id" and t not in TYPEKW and j == i:
                        j += 1
                    while j < e and c.T[j] in ("&", "*", "&&", "const"):
                        j += 1
                    if c.T[j] == "[":  # structured binding
                        names += [x for x in c.T[j + 1:c.M[j]] if x != ","]
                    elif j + 1 < e and c.K[j] == "id" and c.T[j + 1] in ("=", ";", "(", "{", "[", ","):
                        names.append(c.T[j])
                        k = j + 1  # int a = 1, b = 2;
                        while k < e:
                            if c.T[k] in OPEN:
                                k = c.M[k]
                            elif c.T[k] == "," and c.K[k + 1] == "id":
                                names.append(c.T[k + 1])
                            k += 1
            i = e
        return names

    def body_text(self, f, c, i, e, indent_of):
        """the text of a kept block's insides, dedented to the replaced statement's indent"""
        a, b = i + 1, e - 1
        s = c.E[i]
        t = f.text
        nl = t.find("\n", s)
        head = t[s:nl].strip() if nl >= 0 else ""
        inner = t[nl + 1:c.S[b]] if nl >= 0 and nl < c.S[b] else t[s:c.S[b]]
        if head and nl < c.S[b]:
            inner = indent_of + "\t" + head + "\n" + inner
        inner = inner.rstrip(" \t")
        if inner.endswith("\n"):
            inner = inner[:-1]
        lines = inner.split("\n")
        pre = None
        for ln in lines:
            if ln.strip():
                w = ln[:len(ln) - len(ln.lstrip())]
                pre = w if pre is None or len(w) < len(pre) else pre
        pre = pre or ""
        out = [indent_of + ln[len(pre):] if ln.strip() else "" for ln in lines]
        return "\n".join(out).lstrip()

    def keep_stmt(self, f, c, s_tok, a, b, bare, nxt_else):
        """text that replaces a statement by its kept arm [a, b)"""
        ls = f.text.rfind("\n", 0, c.S[s_tok]) + 1
        ind = f.text[ls:c.S[s_tok]]
        ind = ind[:len(ind) - len(ind.lstrip())]
        if c.T[a] == "{":
            if bare:
                return self.reindent(c.src(a, b), f, c, a, ind)
            names = self.decl_names(c, a + 1, b - 1)
            if names is None:
                return self.reindent(c.src(a, b), f, c, a, ind)
            if names:
                p = c.P[s_tok]
                lo, hi = (p + 1, c.M[p]) if p >= 0 else (0, c.n)
                outer = set(c.T[lo:a]) | set(c.T[b:hi])
                if outer & set(names):
                    return self.reindent(c.src(a, b), f, c, a, ind)
            return self.body_text(f, c, a, b, ind)
        txt = self.reindent(c.src(a, b), f, c, a, ind)
        if bare and (nxt_else or c.T[a] in ("if", "for", "while")):
            return "{ " + txt + " }"
        return txt

    @staticmethod
    def reindent(txt, f, c, a, ind):
        ls = f.text.rfind("\n", 0, c.S[a]) + 1
        was = f.text[ls:c.S[a]]
        was = was[:len(was) - len(was.lstrip())]
        if was == ind or "\n" not in txt:
            return txt
        lines = txt.split("\n")
        return "\n".join([lines[0]] + [ind + ln[len(was):] if ln.startswith(was) else ln for ln in lines[1:]])

    def label_risk(self, c, a, b):
        T = c.T[a:b]
        return ("case" in T or "default" in T) and "switch" not in T

    # local constants
    def locals_of(self, f):
        c = f.code
        out = collections.defaultdict(list)
        T = c.T
        for i in range(c.n - 3):
            if T[i] not in ("bool", "int") or c.P[i] < 0 or c.K[i + 1] != "id" or T[i + 2] != "=":
                continue
            st = i - 1
            const = False
            if st >= 0 and T[st] in ("const", "constexpr"):
                const = True
                st -= 1
            if st >= 0 and T[st] == "static":
                continue
            if st >= 0 and T[st] not in (";", "{", "}", ")", ":"):
                continue
            if self.is_ns(c, i) or not self.fn_block(c, c.P[i]):
                continue
            j = i + 3
            while j < c.n and T[j] not in (";", ","):
                j = c.M.get(j, j) + 1 if T[j] in OPEN else j + 1
            if j >= c.n or T[j] != ";":
                continue
            rhs = T[i + 3:j]
            if not any(x in self.ev.interesting or x in ("true", "false") for x in rhs):
                continue
            r = self.ev.eval(rhs)
            if r.val is None or not r.pure:
                continue
            nm = T[i + 1]
            p = c.P[i]
            hi = c.M[p]
            ok = True
            for k in range(j + 1, hi):
                if T[k] != nm:
                    continue
                if T[k - 1] in (".", "->", "::"):
                    continue
                if T[k - 1] in TYPEKW or c.K[k - 1] == "id" and T[k - 1] not in NOTDECL:  # shadowed
                    ok = False
                    break
                if not const and (T[k + 1] in ASSIGN or T[k + 1] in ("++", "--") or T[k - 1] in ("++", "--", "&")):
                    ok = False
                    break
                if not const and (T[k - 1] == "&" or (T[k - 1] in ("(", ",") and T[k + 1] in (")", ","))):  # may be taken by reference
                    ok = False
                    break
            if ok:
                out[nm].append((j, hi, int(bool(r.val)) if T[i] == "bool" else int(r.val), r.used, (i - (1 if const else 0), j)))
        return out

    def is_ns(self, c, i):
        return Ev.ns_scope(c, i)

    @staticmethod
    def fn_block(c, p):
        """is the block at `{` p code, not a struct, class, union or enum body (their `bool x = false;` are fields)"""
        q = p - 1
        while q >= 0 and c.T[q] not in (";", "{", "}"):
            if c.T[q] in ("struct", "class", "union", "enum", "namespace"):
                return False
            q -= 1
        return True

    def toks_at(self, c, a, b, loc):
        """source tokens with local constants replaced"""
        out, used = [], set()
        for k in range(a, b):
            t = c.T[k]
            if t in loc and (k == 0 or c.T[k - 1] not in (".", "->", "::")):
                for lo, hi, v, u, _ in loc[t]:
                    if lo < k < hi:
                        t = str(v)
                        used |= set(u)
                        break
            out.append(t)
        return out, used

    def evalr(self, c, a, b, loc):
        T, u = self.toks_at(c, a, b, loc)
        r = self.ev.eval(T)
        return r._replace(used=r.used | u)

    # one pass over a file's code
    def pass_code(self, f):
        c = f.code
        E = []
        loc = self.locals_of(f)
        T = c.T
        keys = self.ev.interesting
        lname = set(loc)

        def hot(a, b):
            for k in range(a, b):
                t = T[k]
                if t in keys or t in lname or t == "true" or t == "false":
                    return True
            return False

        for i, t in enumerate(T):
            try:
                if t == "if" and c.K[i] == "id":
                    self.do_if(f, c, i, E, loc, hot)
                elif t == "while" and T[i + 1] == "(" and not (i and T[i - 1] == "}" and self.is_do(c, i)):
                    self.do_while(f, c, i, E, loc, hot)
                elif t == "?":
                    self.do_ternary(f, c, i, E, loc, hot)
                elif t == "else":
                    self.do_else(f, c, i, E)
                elif t in ("return", "break", "continue"):
                    self.do_unreach(f, c, i, E)
            except (ValueError, KeyError, IndexError):
                self.stayed["unparsed statement"] += 1
        self.do_regions(f, c, 0, c.n, E, loc, hot, top=True)
        macro_read = set(re.findall(r"^[ \t]*#[ \t]*define[ \t]+\w+(?:\([^)]*\))?[ \t]+(.*)$", f.text, re.M))  # 11 Nov (v759 bake: `const bool
        macro_read = {w for body in macro_read for w in re.findall(r"\w+", body)}  # xfb_smx5 = XFB_ON(256);` read only via `#define XFB_SMX5 xfb_smx5` was deleted)
        for nm, xs in loc.items():
            for lo, hi, v, u, (ds, de) in xs:  # a folded local nothing reads any more
                if nm not in T[lo + 1:hi] and hi > lo and nm not in macro_read:
                    E.append(Edit(c.S[ds], c.E[de], "", "local", " ".join(T[ds:de]), u))
        return E

    @staticmethod
    def is_do(c, i):
        o = c.M.get(i - 1)
        return o is not None and o > 0 and c.T[o - 1] == "do"

    def do_if(self, f, c, i, E, loc, hot):
        T = c.T
        h = i + 1
        if T[h] == "constexpr":
            h += 1
        if T[h] != "(":
            return
        ce = c.M[h]
        s = self.skip_attr(c, ce + 1)
        then_e = self.stmt_end(c, s)
        has_else = then_e < c.n and T[then_e] == "else"
        end = self.stmt_end(c, then_e + 1) if has_else else then_e
        bare = self.bare(c, i)
        empty_then = (T[s] == ";" or (T[s] == "{" and c.M[s] == s + 1)) and not has_else
        r = None
        if hot(h + 1, ce) and ";" not in T[h + 1:ce]:
            r = self.evalr(c, h + 1, ce, loc)
            if r.val is None and r.used:
                self.stayed["test still runtime"] += 1
        if r is not None and r.val is None and not r.pure and not has_else and ";" not in T[h + 1:ce] and not self.label_risk(c, i, end):
            ff = self.false_prefix(c, h + 1, ce, loc)
            if ff is not None:  # 9 Nov (Builder, v640's CI2 lines): `if (f() && OFF) S;` is always false but f() may have effects: keep only
                # what C runs, `(void)(f() && OFF);`, and drop S, instead of leaving `if (f() && OFF) S;` with S's real conditions folded away
                E.append(Edit(c.S[i], c.E[end - 1], f"(void)({ff[0]});", "dead if (impure test kept)", c.src(h + 1, ce), ff[1]))
                return
        if r is None or r.val is None or not r.pure:
            if empty_then:
                rr = self.evalr(c, h + 1, ce, loc)
                if rr.pure and ";" not in T[h + 1:ce]:
                    self.emit_del(f, c, i, end, bare, E, "empty if", c.src(h + 1, ce), rr.used)
            return
        test = c.src(h + 1, ce)
        if self.label_risk(c, i, end):
            self.stayed["label in arm"] += 1
            return
        arm = (s, then_e) if r.val else ((then_e + 1, end) if has_else else None)
        if arm and (T[arm[0]] == ";" or (T[arm[0]] == "{" and c.M[arm[0]] == arm[0] + 1)):
            arm = None
        if arm is None:
            self.emit_del(f, c, i, end, bare, E, "dead if", test, r.used)
            return
        nxt = end < c.n and T[end] == "else"
        new = self.keep_stmt(f, c, i, arm[0], arm[1], bare is not None, nxt)
        E.append(Edit(c.S[i], c.E[end - 1], new, "dead arm", test, r.used))

    def false_prefix(self, c, a, b, loc):
        """(text, used) for a top-level `A && B && ... && OFF ...` test [a, b) with a pure operand known false: the text from the test's start through
        that operand (all C evaluates of it), or None"""
        lo, hi = a, b
        while hi - lo >= 2 and c.T[lo] == "(" and c.M[lo] == hi - 1:
            lo, hi = lo + 1, hi - 1
        if self.tops(c, lo, hi, {"?", ",", "||"} | ASSIGN):
            return None
        cuts = self.tops(c, lo, hi, {"&&"})
        if not cuts:
            return None
        for x, y in zip([lo - 1] + cuts, cuts + [hi]):
            r = self.evalr(c, x + 1, y, loc)
            if r.val is not None and r.pure and not r.val:
                return c.src(lo, y), set(r.used)
        return None

    def emit_del(self, f, c, i, end, bare, E, kind, test, used):
        if bare == "else":
            E.append(Edit(c.S[i - 1], c.E[end - 1], "", kind, test, used))
        elif bare:
            E.append(Edit(c.S[i], c.E[end - 1], ";", kind, test, used))
        else:
            E.append(Edit(c.S[i], c.E[end - 1], "", kind, test, used))

    def do_while(self, f, c, i, E, loc, hot):
        T = c.T
        h = i + 1
        ce = c.M[h]
        if not hot(h + 1, ce):
            return
        r = self.evalr(c, h + 1, ce, loc)
        if r.val is not None and r.pure and not r.val:
            e = self.stmt_end(c, ce + 1)
            if not self.label_risk(c, i, e):
                self.emit_del(f, c, i, e, self.bare(c, i), E, "dead while", c.src(h + 1, ce), r.used)

    def do_else(self, f, c, i, E):
        j = i + 1
        if c.T[j] == ";" or (c.T[j] == "{" and c.M[j] == j + 1):
            E.append(Edit(c.S[i], c.E[j if c.T[j] == ";" else j + 1], "", "empty else"))

    def do_unreach(self, f, c, i, E):
        T = c.T
        if i == 0 or T[i - 1] not in (";", "{", "}", ":") or c.P[i] < 0:
            return
        e = self.stmt_end(c, i)
        p = c.P[i]
        hi = c.M[p]
        if e >= hi or T[e] in ("case", "default"):
            return
        k = e
        while k < hi:
            if T[k] in OPEN:
                k = c.M[k] + 1
                continue
            if T[k] in ("case", "default") or (c.K[k] == "id" and T[k + 1] == ":" and T[k - 1] in (";", "}", "{")):
                return  # a label can still be reached
            k += 1
        if self.label_risk(c, e, hi):
            return
        if re.search(r"(?m)^[ \t]*#[ \t]*(?:if|ifdef|ifndef|elif|else|endif)\b", f.text[c.S[i]:c.E[hi - 1]]):
            return  # 10 Nov (Rule Checker): a return under #ifdef __wasm__ does not end the #else branch (v696 lost board_views.h:64)
        E.append(Edit(c.S[e], c.E[hi - 1], "", "unreachable", " ".join(T[i:min(e, i + 6)])))

    def do_ternary(self, f, c, q, E, loc, hot, base=None):
        T = c.T
        a = q - 1
        while a >= 0:
            t = T[a]
            if t in (")", "]", "}"):
                a = c.M[a] - 1
                continue
            if t in ("(", "[", "{", ",", ";", "?", ":", "return", "case") or t in ASSIGN:
                break
            a -= 1
        a += 1
        if a >= q or not hot(a, q):
            return
        r = self.evalr(c, a, q, loc)
        if r.val is None or not r.pure:
            return
        k, nest, col = q + 1, 0, None
        while k < c.n:
            t = T[k]
            if t in OPEN:
                k = c.M[k] + 1
                continue
            if t in (")", "]", "}", ";"):
                return
            if t == "?":
                nest += 1
            elif t == ":":
                if nest == 0:
                    col = k
                    break
                nest -= 1
            k += 1
        if col is None:
            return
        k, nest = col + 1, 0
        while k < c.n:
            t = T[k]
            if t in OPEN:
                k = c.M[k] + 1
                continue
            if t in (")", "]", "}", ";", ","):
                break
            if t == "?":
                nest += 1
            elif t == ":":
                if nest == 0:
                    break
                nest -= 1
            k += 1
        x, y = (q + 1, col) if r.val else (col + 1, k)
        txt = c.src(x, y)
        single = y - x == 1 or (T[x] == "(" and c.M[x] == y - 1)
        whole = (a == 0 or T[a - 1] in ("(", ",", "return", "=", ";")) and (k >= c.n or T[k] in (")", ";", ","))
        e = Edit(c.S[a], c.E[k - 1], txt if single or whole else f"({txt})", "ternary", c.src(a, q), r.used)
        e.arm = txt
        E.append(e)

    # && || and whole boolean values inside expressions
    def do_regions(self, f, c, a, b, E, loc, hot, top=False):
        T = c.T
        i = a
        while i < b:
            t = T[i]
            if t == "(":
                e = c.M[i]
                skip = i and T[i - 1] in ("sizeof", "decltype", "alignof", "__attribute__", "operator", "defined", "for", "static_assert")
                if hot(i + 1, e) and not skip:
                    self.region_list(f, c, i + 1, e, E, loc, hot)
                if i and T[i - 1] == "for" and hot(i + 1, e):
                    cuts = [i] + [k for k in range(i + 1, e) if T[k] == ";" and self.same_depth(c, i + 1, k)] + [e]
                    for x, y in zip(cuts, cuts[1:]):
                        self.region(f, c, x + 1, y, E, loc, hot)
            elif t == "return" or (t == "=" and top):
                j = i + 1
                while j < c.n and T[j] not in (";",):
                    if T[j] in OPEN:
                        j = c.M[j] + 1
                        continue
                    if T[j] in (")", "]", "}") or (T[j] == "," and t == "="):
                        break
                    j += 1
                if hot(i + 1, j):
                    self.region(f, c, i + 1, j, E, loc, hot)
            i += 1

    @staticmethod
    def same_depth(c, a, k):
        d = 0
        for x in range(a, k):
            d += c.T[x] in OPEN
            d -= c.T[x] in (")", "]", "}")
        return d == 0

    def region_list(self, f, c, a, b, E, loc, hot):
        cuts = [a - 1]
        k = a
        while k < b:
            t = c.T[k]
            if t in OPEN:
                k = c.M[k] + 1
                continue
            if t == ",":
                cuts.append(k)
            elif t == ";":
                return
            k += 1
        cuts.append(b)
        for x, y in zip(cuts, cuts[1:]):
            self.region(f, c, x + 1, y, E, loc, hot)

    def region(self, f, c, a, b, E, loc, hot):
        if b <= a or not hot(a, b):
            return
        T = c.T
        if b - a == 1 and T[a] in ("true", "false"):
            return
        r = self.evalr(c, a, b, loc)
        src, _ = self.toks_at(c, a, b, loc)
        if r.val is not None and r.pure and r.used and self.ev.boolish(src):
            new = "true" if r.val else "false"
            if c.src(a, b) != new:
                E.append(Edit(c.S[a], c.E[b - 1], new, "fold", c.src(a, b), r.used))
            return
        res = self.simp(c, a, b, loc)
        if res is not None:
            new, used = res
            if new is not None and re.sub(r"\s+", "", new) != re.sub(r"\s+", "", c.src(a, b)):
                E.append(Edit(c.S[a], c.E[b - 1], new, "test", c.src(a, b), used))

    def tops(self, c, a, b, ops):
        out, k = [], a
        while k < b:
            t = c.T[k]
            if t in OPEN:
                k = c.M[k] + 1
                continue
            if t in ops:
                out.append(k)
            k += 1
        return out

    @staticmethod
    def unwrap(t):
        """t without one outer pair of parentheses when that pair wraps all of it and holds no top-level comma; else t"""
        t = t.strip()
        if len(t) < 2 or t[0] != "(" or t[-1] != ")":
            return t
        d = 0
        for i, ch in enumerate(t):
            d += ch == "("
            d -= ch == ")"
            if d == 0 and i < len(t) - 1:
                return t  # the first '(' closes before the end: `(a) || (b)`
            if d == 1 and ch == "," and i > 0:
                return t
        return t[1:-1].strip()

    def simp(self, c, a, b, loc):
        """new text for a && / || expression [a, b) with known operands gone, or None; a known operand is dropped only when safe"""
        lo, hi = a, b
        while hi - lo >= 2 and c.T[lo] == "(" and c.M[lo] == hi - 1:
            lo, hi = lo + 1, hi - 1
        if self.tops(c, lo, hi, {"?", ","} | ASSIGN):
            return None
        for op, stop in (("||", True), ("&&", False)):
            cuts = self.tops(c, lo, hi, {op})
            if not cuts:
                continue
            parts = list(zip([lo - 1] + cuts, cuts + [hi]))
            kept, used, changed = [], set(), False
            for x, y in parts:
                x += 1
                r = self.evalr(c, x, y, loc)
                if r.val is not None and r.pure:
                    used |= set(r.used)
                    if bool(r.val) == stop:
                        if kept:  # `a && OFF`: the rest never runs, but `a` may have run: keep it and this operand
                            kept.append(c.src(x, y))
                        else:
                            return None
                        changed = changed or (x, y) != parts[-1]
                        break
                    changed = True
                    continue
                sub = self.simp(c, x, y, loc)
                if sub is not None and sub[0] is not None:
                    kept.append(sub[0])
                    used |= sub[1]
                    changed = True
                else:
                    kept.append(c.src(x, y))
            if not changed or not kept:
                return None
            if len(kept) == 1 and a == lo and a > 0 and b < c.n and c.T[a - 1] == "(" and c.T[b] == ")":
                kept[0] = self.unwrap(kept[0])  # 9 Nov (owner saw -Wparentheses-equality): `if (A && (x == y))` -> `if (x == y)`, not `if ((x == y))`
            txt = f" {op} ".join(kept)
            if len(kept) == 1:
                if not self.bool_ctx(c, a, b) and not self.is_bool_text(kept[0]):
                    return f"static_cast<bool>({kept[0]})", used  # `int n = ON && k;` is 0 or 1, not k
                return (txt if a == lo or self.atomic(txt) else f"({txt})"), used
            if a != lo:
                txt = f"({txt})"
            return txt, used
        return None

    @staticmethod
    def atomic(txt):
        return re.fullmatch(r"!?[\w.:>-]*(\([^()]*\))?", txt) is not None

    @staticmethod
    def bool_ctx(c, a, b):
        """does [a, b) sit where only its truth counts?"""
        p = c.T[a - 1] if a else ""
        n = c.T[b] if b < c.n else ""
        if p in ("&&", "||", "!") or n in ("&&", "||", "?"):
            return True
        if p == "(" and n == ")":
            if a >= 2 and c.T[a - 2] in ("if", "while"):
                return True
            if a >= 2 and c.T[a - 2] == "(" or (a >= 2 and c.T[a - 2] in ("!", "&&", "||")):
                return Strip.bool_ctx(c, a - 1, b + 1)
            if b + 1 < c.n and c.T[b + 1] in ("&&", "||", "?"):
                return True
        if p == "=" and a >= 3 and c.T[a - 3] == "bool":
            return True
        return False

    def is_bool_text(self, txt):
        T = [x[1] for x in lex(txt, 0, len(txt))]
        X = strip_parens(T)
        if split_top(X, {"&", "|", "^", "?", ",", "+", "-", "*", "/", "%"}) or "static_cast" in X:
            return False
        return bool(split_top(X, {"==", "!=", "<", ">", "<=", ">=", "&&", "||"})) or (bool(X) and X[0] == "!")

    # macro bodies
    def pass_macros(self, f):
        E = []
        for d in f.dirs:
            if d.kind != "define" or d.body is None or d.body.n == 0 or "#" in d.body.T or "##" in d.body.T:
                continue
            c = d.body
            T = c.T
            keys = self.ev.interesting

            def hot(a, b):
                return any(T[k] in keys or T[k] in ("true", "false") for k in range(a, b))

            for i, t in enumerate(T):
                if t == "?":
                    try:
                        self.do_ternary(f, c, i, E, {}, hot)
                    except (ValueError, KeyError, IndexError):
                        pass
            if not any(x in ("if", "{", ";", "for", "while") for x in T):
                self.region(f, c, 0, c.n, E, {}, hot)
                if any(e.s >= d.s and e.e <= d.e for e in E):
                    continue
                self.do_regions(f, c, 0, c.n, E, {}, hot)
        return E

    # unused items
    def items(self):
        """every namespace-scope item: (kind, name, file, start, end, seq, tokens a..b); the rest of the code is a root"""
        out = []
        for f in self.files:
            c = f.code
            T = c.T
            i, depth = 0, 0
            stack = []
            while i < c.n:
                t = T[i]
                if t == "}":
                    if stack:
                        stack.pop()
                    i += 1
                    if i < c.n and T[i] == ";":
                        i += 1
                    continue
                if t == ";":
                    i += 1
                    continue
                if t == "namespace":
                    j = i + 1
                    while j < c.n and T[j] not in ("{", "=", ";"):
                        j += 1
                    if T[j] == "{":
                        stack.append("ns")
                        i = j + 1
                    else:
                        while T[j] != ";":
                            j += 1
                        i = j + 1
                    continue
                if t == "extern" and c.K[i + 1] == "str":
                    if T[i + 2] == "{":
                        stack.append("c")
                        i += 3
                        continue
                st = i
                if t == "template":
                    d, j = 0, i + 1
                    while j < c.n:
                        d += T[j] == "<"
                        d -= T[j] == ">"
                        d -= 2 * (T[j] == ">>")
                        j += 1
                        if d <= 0:
                            break
                    i = j
                r = self.item_at(c, i, st, bool(stack), f)
                if r is None:
                    i += 1
                    continue
                if r[0]:
                    out.append(r[0])
                i = r[1]
        return out

    def item_at(self, c, i, st, in_ns, f):
        T = c.T
        j = i
        attr = False
        while j < c.n:
            t = T[j]
            if t == "__attribute__":
                x = c.src(j, c.M[j + 1] + 1)
                attr = attr or "export" in x or "used" in x or "constructor" in x
                j = c.M[j + 1] + 1
                continue
            if t in ("struct", "class", "union", "enum", "using", "typedef", "static_assert", "friend"):
                e = self.decl_end(c, j)
                return None, e
            if t == "(":
                if j == i or c.K[j - 1] != "id" or T[j - 1] in ("operator", "__attribute__", "decltype"):
                    return None, self.decl_end(c, j)
                name, q = T[j - 1], j - 2
                qual = []
                while q >= 1 and T[q] == "::":
                    qual.append(T[q - 1])
                    q -= 2
                k = c.M[j] + 1
                while k < c.n and T[k] not in ("{", ";", "=", ":"):
                    if T[k] in OPEN:
                        k = c.M[k]
                    k += 1
                if k >= c.n:
                    return None, c.n
                if T[k] == "{":
                    e = c.M[k] + 1
                    if qual or not in_ns or attr:
                        return None, e
                    return ("fn", name, f, st, e, True), e
                if T[k] == ";":
                    if qual or not in_ns or attr:
                        return None, k + 1
                    return ("fn", name, f, st, k + 1, False), k + 1
                return None, self.decl_end(c, k)
            if t in ("=", ";", "{", "["):
                e = self.decl_end(c, j)
                name = T[j - 1] if j > i and c.K[j - 1] == "id" else None
                head = set(T[i:j])
                plain = name and in_ns and all(x in TYPEKW or x in PLAIN or x in ("std", "::", "inline", "extern", name) for x in T[i:j])
                multi, k = False, j  # `int a = 0, b = 0;` declares more than its last name
                while k < e:
                    if T[k] in OPEN:
                        k = c.M[k]
                    elif T[k] == ",":
                        multi = True
                    k += 1
                init = T[j:e]
                init = init[init.index("=") + 1:] if "=" in init else []
                if plain and not multi and "extern" not in head and "volatile" not in T[i:j] and not Ev.impure(init):
                    return ("var", name, f, st, e, True), e
                return None, e
            if t in ("}", ")"):
                return None, j + 1
            j += 1
        return None, c.n

    @staticmethod
    def decl_end(c, j):
        T = c.T
        while j < c.n:
            t = T[j]
            if t == "{":
                e = c.M[j] + 1
                if e < c.n and T[e] == ";":
                    return e + 1
                if e < c.n and (c.K[e] == "id" or T[e] in ("*", "&")):  # struct X { } x;
                    j = e
                    continue
                if T[j - 1] in (")",) or c.T[j - 1] == "const":
                    return e
                j = e
                continue
            if t in ("(", "["):
                j = c.M[j] + 1
                continue
            if t == ";":
                return j + 1
            if t == "}":
                return j
            j += 1
        return j

    def sweep(self):
        """mark and sweep: returns edits that delete what nothing live reaches"""
        items = self.items()
        nodes = collections.defaultdict(list)
        for it in items:
            nodes[it[1]].append(it)
        for f in self.files:
            for d in f.dirs:
                if d.kind == "define" and d.name:
                    nodes[d.name].append(("mac", d.name, f, d, None, True))
        roots = set(self.roots)
        spans = collections.defaultdict(list)
        for it in items:
            if it[1] not in self.roots:
                spans[it[2].path].append((it[3], it[4]))
        refs = collections.defaultdict(set)
        for it in items:
            refs[it[1]].update(x for x, k in zip(it[2].code.T[it[3]:it[4]], it[2].code.K[it[3]:it[4]]) if k == "id")
        for f in self.files:
            c = f.code
            own = sorted(spans[f.path])
            k, i = 0, 0
            while i < c.n:
                while k < len(own) and own[k][1] <= i:
                    k += 1
                if k < len(own) and own[k][0] <= i < own[k][1]:
                    i = own[k][1]
                    continue
                if c.K[i] == "id":
                    roots.add(c.T[i])
                i += 1
            for d in f.dirs:
                if d.kind == "define" and d.body is not None:
                    refs[d.name].update(x for x, k2 in zip(d.body.T, d.body.K) if k2 == "id")
                elif d.kind in ("if", "elif", "ifdef", "ifndef"):
                    if d.body is not None:
                        roots.update(x for x, k2 in zip(d.body.T, d.body.K) if k2 == "id")
                    if d.name:
                        roots.add(d.name)
        seen, todo = set(), [x for x in roots if x in nodes]
        seen.update(todo)
        while todo:
            x = todo.pop()
            for y in refs.get(x, ()):
                if y in nodes and y not in seen:
                    seen.add(y)
                    todo.append(y)
        E = []
        for name, its in nodes.items():
            if name in seen:
                continue
            if self.keep_name(name):
                continue
            for it in its:
                E.append(self.del_item(it))
        for f in self.files:  # #undef of a macro that is gone
            names = {d.name for d in f.dirs}
            for d in f.dirs:
                if d.kind == "undef" and not any(g.kind == "define" and g.name == d.name for x in self.files for g in x.dirs):
                    E.append((f, Edit(d.s, d.e, "", "undef", d.name)))
        return E

    def keep_name(self, name):
        return name in self.keep or name in self.roots or name.startswith("__")

    def del_item(self, it):
        kind, name, f = it[0], it[1], it[2]
        if kind == "mac":
            d = it[3]
            return f, Edit(d.s, d.e, "", "unused macro", name)
        c = f.code
        return f, Edit(c.S[it[3]], c.E[it[4] - 1], "", "unused fn" if kind == "fn" else "unused var", name)

    # edits
    def select(self, f, E):
        """outermost edits first; ones inside another wait for the next round"""
        E = sorted(E, key=lambda e: (e.s, -e.e))
        keep, last = [], -1
        for e in E:
            if e.s < last:
                continue
            if self.crosses(f, e):
                self.stayed["crosses a preprocessor block"] += 1
                continue
            keep.append(e)
            last = e.e
        return keep

    def type_check(self, plan):
        """`C ? a : b` has the common type of a and b, which `a` alone may not have (`(ON ? n : 0.0f) / m`). Ask clang: each folded
        ternary is wrapped, in a scratch copy, in a template that fails when the kept arm's type differs from the whole's; a differing
        one is folded to a cast to the whole's type."""
        tern = {}
        for f, es in plan.items():
            for e in es:
                if e.kind == "ternary":
                    tern[len(tern)] = (f, e)
        if not tern or not self.flags:
            return
        d = tempfile.mkdtemp(prefix="ds_", dir=self.tmp)
        ids = {id(e): k for k, (_, e) in tern.items()}
        for f in self.files:
            t = f.text
            for e in sorted(plan.get(f, ()), key=lambda x: -x.s):
                if e.kind == "ternary":
                    w = t[e.s:e.e]
                    t = t[:e.s] + f"(::ds_t<{ids[id(e)]}, decltype({e.arm}), decltype({w})>::ds_ok_, ({w}))" + t[e.e:]
            if f.name == "nova_all.cpp":
                t = ("#include <type_traits>\ntemplate <int N, class A, class B> struct ds_t { static_assert(std::is_same_v<std::decay_t<A>, "
                     "std::decay_t<B>>); static constexpr int ds_ok_ = 0; };\n") + t
            open(os.path.join(d, f.name), "w", encoding="utf-8", errors="surrogateescape").write(t)
        r = subprocess.run(self.flags + ["-fsyntax-only", "-ferror-limit=0", "-w", "-fno-diagnostics-color", os.path.join(d, "nova_all.cpp")],
                           capture_output=True, text=True, errors="replace")
        shutil.rmtree(d, ignore_errors=True)
        got = {}
        for m in re.finditer(r"'ds_t<(\d+), (.*?)>' requested here", r.stderr):
            k = int(m.group(1))
            cuts = [i for i, ch in enumerate(m.group(2)) if ch == "," and m.group(2)[:i].count("<") == m.group(2)[:i].count(">")]
            got[k] = m.group(2)[cuts[-1] + 1:].strip() if cuts else ""
        other = [ln for ln in r.stderr.split("\n") if " error: " in ln and "static assertion" not in ln]
        if other:  # unproved, so none fold this round (a macro's error is reported where it is used, so no file can be cleared alone)
            print(f"deadstrip: type check: {other[0][:160]}")
            self.stayed["ternary left: its type check did not compile"] += len(tern)
            for f, e in tern.values():
                plan[f].remove(e)
            return
        for k, ty in got.items():
            e = tern[k][1]
            e.new = f"static_cast<{re.sub(r'^const ', '', ty)}>({e.arm})"
            self.casts += 1

    def apply(self, f, keep):
        t = f.text
        func = self.func_at(f)
        for e in reversed(keep):
            s, en, new = e.s, e.e, e.new
            if new == "":
                s, en = self.whole_lines(t, s, en, e.kind.startswith("unused"))
            e.file, e.line, e.func, e.text = f.name, f.text.count("\n", 0, e.s) + 1, func(e.s), t[s:en]
            t = t[:s] + new + t[en:]
        f.text = t
        self.log += keep
        return len(keep)

    def crosses(self, f, e):
        d = 0
        for x in f.dirs:
            if x.s >= e.e:
                break
            if x.s < e.s:
                continue
            if x.kind in ("if", "ifdef", "ifndef"):
                d += 1
            elif x.kind == "endif":
                d -= 1
                if d < 0:
                    return True
            elif x.kind in ("else", "elif") and d == 0:
                return True
        return d != 0

    @staticmethod
    def whole_lines(t, s, e, comments):
        """widen a deletion to whole lines when nothing else is left on them; an unused item takes the comment lines right above it"""
        a = t.rfind("\n", 0, s) + 1
        b = t.find("\n", e)
        b = len(t) if b < 0 else b
        tail = t[e:b].strip()
        if t[a:s].strip() == "" and (tail == "" or tail.startswith("//")):
            s, e = a, min(b + 1, len(t))
            while comments and s > 0:
                p = t.rfind("\n", 0, s - 1) + 1
                if t[p:s].lstrip().startswith("//"):
                    s = p
                else:
                    break
        return s, e

    @staticmethod
    def func_at(f):
        c = f.code
        tops = [i for i in range(c.n) if c.T[i] == "{" and i and c.T[i - 1] in (")", "const") and c.P[i] < 0 or
                (c.T[i] == "{" and i and c.T[i - 1] in (")", "const") and Ev.ns_scope(c, i))]
        marks = []
        for i in tops:
            j = i - 1
            if c.T[j] == "const":
                j -= 1
            o = c.M.get(j)
            if o and o > 0:
                marks.append((c.S[i], c.E[c.M[i]], c.T[o - 1]))

        def at(pos):
            for a, b, n in marks:
                if a <= pos < b:
                    return n
            return ""
        return at

    def run(self, unused=True, say=print):
        self.reparse()
        start = {f.name: f.text.count("\n") for f in self.files}
        for rnd in range(60):
            n = 0
            changed = set()
            plan = {}
            for f in self.files:
                E = self.pass_code(f) + self.pass_macros(f)
                if E:
                    plan[f] = self.select(f, E)
            self.type_check(plan)
            for f, es in plan.items():
                k = self.apply(f, es) if es else 0
                if k:
                    n += k
                    changed.add(f)
            if changed:
                self.reparse(changed)
            if n == 0 and unused:
                by = collections.defaultdict(list)
                for f, e in self.sweep():
                    by[f].append(e)
                for f, es in by.items():
                    n += self.apply(f, self.select(f, es))
                if by:
                    self.reparse(set(by))
            say(f"deadstrip: round {rnd + 1}: {n} edits")
            if n == 0:
                break
        shutil.rmtree(self.tmp, ignore_errors=True)
        return start

    def attribute(self):
        """flags behind each removal; a helper gets the flags of the removals that called it"""
        name_flags = collections.defaultdict(set)
        for e in self.log:
            if e.used:
                for w in re.findall(r"[A-Za-z_]\w*", e.text + " " + e.test):
                    name_flags[w].update(e.used)
        for _ in range(6):
            for e in self.log:
                if e.kind.startswith("unused") and e.test in name_flags:
                    for w in re.findall(r"[A-Za-z_]\w*", e.text):
                        name_flags[w] |= name_flags[e.test]
        rows = []
        for e in self.log:
            fl = set(e.used) or set(name_flags.get(e.test, ()))
            if not fl and not e.kind.startswith("unused"):  # a flag tested by its macro's name, with no table behind it
                fl = set(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", e.test))
            if e.kind == "unused macro" and not fl:
                m = re.search(r"\b([A-Z][A-Z0-9_]*_TAB\d*)\b", e.text)
                fl = {m.group(1)} if m else fl
            if e.kind == "unused var" and e.test.endswith("_TAB") and not fl:
                fl = {e.test}
            rows.append(dict(flags=sorted(fl), file=e.file, line=e.line, func=e.func, kind=e.kind, test=e.test[:300], text=e.text, new=e.new))
        return rows


def compile_flags(bot):
    """the exact compile command of a bot's sources, for syntax-only checks; [] if it has none"""
    try:
        p = shlex.split(json.load(open(os.path.join(bot, "compile_commands.json")))[0]["command"])
    except (OSError, ValueError, IndexError, KeyError):
        return []
    o, i = [p[0]], 1
    while i < len(p):
        x = p[i]
        if x in ("-o", "-MF", "-MT", "-c"):
            i += 2
        elif x in ("-MD", "-MMD") or x.endswith(".cpp") or (x.startswith("-I") and "bots/" in x):
            i += 1
        else:
            o.append(x)
            i += 1
    return o if os.path.exists(p[0]) else []


def bake(src, keep):
    n = k = 0
    for x in sorted(os.listdir(src)):
        if not x.endswith((".h", ".cpp", ".cc")):
            continue
        p = os.path.join(src, x)
        lines = open(p, encoding="utf-8", errors="surrogateescape").read().split("\n")
        for i, ln in enumerate(lines):
            for rx, sub in BAKE:
                m = rx.match(ln)
                if m:
                    if m.group(3) in keep:
                        k += 1
                    else:
                        lines[i] = rx.sub(sub, ln, 1)
                        n += 1
                    break
        open(p, "w", encoding="utf-8", errors="surrogateescape").write("\n".join(lines))
    return n, k


def botdir(b):
    return os.path.realpath(os.path.join(REPO, "bots", b))


def newbot(src, new):
    r = subprocess.run(["sh", os.path.join(REPO, "tools/lab/newbot.sh"), src, new], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"deadstrip: {r.stdout}{r.stderr}".strip())
    return botdir(new)


def build(bot, out):
    if subprocess.run(["python3", "-I", os.path.join(REPO, "tools/lab/pilotbuild.py"), bot, out], capture_output=True).returncode == 0 and os.path.exists(out):
        return True
    return False


def check(baked, new, rep, maps=40, seed=1, fuel_tol=0.5):
    """wasm byte-identical, else cxeident at unlimited fuel: every game identical and the same work's fuel within fuel_tol %. Byte
    identity is rare: a helper whose other callers went dead gets inlined into the last one (v cbase_19: toh_build into toh_turns)."""
    os.makedirs(rep, exist_ok=True)
    wa, wb = f"{rep}/baked.wasm", f"{rep}/stripped.wasm"
    print(f"deadstrip: building {baked} and {new}", flush=True)
    if not build(baked, wa) or not build(new, wb):
        print("deadstrip: a build failed on the pilots: `cambc400 build` it locally to see the error")
        return 1
    a, b = open(wa, "rb").read(), open(wb, "rb").read()
    if a == b:
        print(f"deadstrip: CHECK PASS wasm byte-identical ({len(a):,} bytes)")
        return 0
    print(f"deadstrip: wasm differs ({len(a):,} v {len(b):,} bytes): cxeident {maps} maps, unlimited fuel", flush=True)
    r = subprocess.run(["python3", "-I", os.path.join(REPO, "tools/cxe/cxeident.py"), baked, new, "--maps", str(maps), "--seed", str(seed)],
                       capture_output=True, text=True)
    txt = r.stdout + r.stderr
    open(f"{rep}/cxeident_{maps}_{seed}.txt", "w").write(txt)
    print("\n".join(x for x in txt.strip().split("\n") if "pilot" not in x)[-900:])
    m = re.search(r"(\d+)/(\d+) games byte-identical", txt)  # the counts decide: cxeident's exit code does not say
    f = re.search(r"same work \(unlimited\).*\(([-+][\d.]+)%\)", txt)
    same = bool(m) and m.group(1) == m.group(2) and int(m.group(2)) >= 2 * maps
    fuel = bool(f) and abs(float(f.group(1))) <= fuel_tol
    print(f"deadstrip: CHECK {'PASS' if same and fuel else 'FAIL'}: games {m.group(0) if m else 'no read'}, same-work fuel {f.group(1) + '%' if f else 'no read'} (bar {fuel_tol}%)")
    return 0 if same and fuel else 1


def write_report(s, src, new, start, rep, keep, srcdir, dst):
    os.makedirs(rep + "/by_flag", exist_ok=True)
    rows = s.attribute()
    json.dump(dict(source=src, new=new, keep=sorted(keep), rows=rows, when=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(rep + "/removed.json", "w"))
    per = collections.defaultdict(list)
    for r in rows:
        for fl in r["flags"] or ["(no flag: unused or unreachable)"]:
            per[fl].append(r)
    for fl, rs in per.items():
        with open(f"{rep}/by_flag/{re.sub(r'[^A-Za-z0-9_]', '_', fl)}.txt", "w", errors="surrogateescape") as g:
            for r in rs:
                g.write(f"--- {r['kind']} {r['file']}:{r['line']} {r['func']}\n    test: {r['test']}\n{r['text']}\n")
                if r["new"]:
                    g.write(f"+++ kept:\n{r['new']}\n")
    with open(rep + "/full.diff", "w", errors="surrogateescape") as g:
        for f in s.files:
            old = open(os.path.join(srcdir, f.name), encoding="utf-8", errors="surrogateescape").read().split("\n")
            g.writelines(x + "\n" for x in difflib.unified_diff(old, f.text.split("\n"), f"a/{f.name}", f"b/{f.name}", lineterm="", n=1))
    L = [f"deadstrip {src} -> {new}", ""]
    tot0 = tot1 = 0
    L.append(f"{'file':18} {'before':>8} {'after':>8} {'removed':>8}")
    for f in s.files:
        a, b = start[f.name], f.text.count("\n")
        tot0, tot1 = tot0 + a, tot1 + b
        if a != b:
            L.append(f"{f.name:18} {a:8} {b:8} {a - b:8}")
    L += [f"{'TOTAL':18} {tot0:8} {tot1:8} {tot0 - tot1:8}", ""]
    kinds = collections.Counter(r["kind"] for r in rows)
    L.append("edits: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    L.append(f"flags with removals: {sum(1 for k in per if not k.startswith('('))}; kept volatile: {len(keep)}")
    L.append(f"ternaries folded with a cast (clang: kept arm's type differed): {s.casts}")
    L.append("not folded: " + (", ".join(f"{k} {v}" for k, v in s.stayed.most_common()) or "none"))
    L.append(f"flags still read after the strip: {sum(1 for t in tables_left(s))}")
    reads = collections.Counter(t for f in s.files for t in f.code.T)
    # 9 Nov 22:50Z (Rule Checker: v673 listed BB12 BB13 CBA FB1 FB6 RGB WCD WDV as unread while ~70 sites read them): most reads go through the
    # table's macros (X_ON(...), X_WAIT_CAP(...)), not the X_TAB token; count those uses too
    def nreads(k):
        stem = k[:-4] if k.endswith("_TAB") else k
        return reads[k] + sum(c for tok, c in reads.items() if tok != k and tok.startswith(stem + "_") and not tok.endswith(("_BITS", "_TAB")))
    dead = sorted(k for k in keep if nreads(k) < 2)  # the declaration is one token: a flip of a table nothing reads changes nothing
    if dead:
        L.append("WARNING kept tables with no reads left (a flip of these does nothing, and flip.sh may not find them): " + " ".join(dead))
    open(rep + "/report.txt", "w").write("\n".join(L) + "\n")
    return "\n".join(L)


def tables_left(s):
    seen = set()
    for f in s.files:
        seen.update(t for t in f.code.T if t.endswith("_TAB"))
    return sorted(seen)


def find(a):
    name = a[0]
    dirs = [os.path.join(OUT, a[1])] if len(a) > 1 else sorted((os.path.join(OUT, x) for x in os.listdir(OUT)), key=os.path.getmtime, reverse=True)
    for d in dirs:
        p = d + "/removed.json"
        if not os.path.exists(p):
            continue
        j = json.load(open(p))
        hit = [r for r in j["rows"] if any(name in fl for fl in r["flags"]) or re.search(rf"\b{re.escape(name)}\b", r["text"] + r["test"])]
        print(f"{os.path.basename(d)} (source {j['source']}): {len(hit)} removals name {name}")
        for r in hit[:60]:
            print(f"  {r['kind']:13} {r['file']}:{r['line']} {r['func']}  {r['test'][:90]!r}  ({len(r['text'].splitlines())} lines)")
        if len(a) == 1 and hit:
            break
    return 0



BAKE_KEEP = os.environ.get("BAKE_KEEP_FILE", "/data/zw4424/st/bq/bake_keep.txt")


def bake_keep():
    """8 Nov (Builder, Rule Checker R1): tables a test still needs flippable, one X_TAB per line (# comments): never baked, their off
    branches never stripped, by bake.py, deadstrip.py or shipbake.py"""
    try:
        return {w for ln in open(BAKE_KEEP) for w in ln.split("#", 1)[0].split() if w}
    except OSError:
        return set()


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if a[0] == "find":
        return find(a[1:])
    if a[0] == "check":
        return check(a[1], a[2], os.path.join(OUT, a[2]), int(a[a.index("--maps") + 1]) if "--maps" in a else 40,
                     int(a[a.index("--seed") + 1]) if "--seed" in a else 1)
    if len(a) < 2 or a[1].startswith("-"):
        print(__doc__)
        return 2
    src, new = a[0], a[1]

    def opt(k, d=""):
        return a[a.index(k) + 1] if k in a else d
    keep = {x for x in opt("--keep").split(",") if x}
    if opt("--keep-file"):
        keep |= set(open(opt("--keep-file")).read().split())
    roots = [x for x in opt("--roots").split(",") if x]
    rep = opt("--report", os.path.join(OUT, new))
    srcdir = botdir(src)
    if not os.path.isdir(srcdir + "/src"):
        print(f"deadstrip: no bot {src}")
        return 2
    miss = [k for k in keep if not any(re.search(rf"\b{k}\b", open(os.path.join(srcdir, 'src', x), errors='replace').read()) for x in os.listdir(srcdir + "/src"))]
    if miss:
        print(f"deadstrip: no such table: {' '.join(miss)}")
        return 2
    allsrc = "\n".join(open(os.path.join(srcdir, "src", x), errors="replace").read() for x in os.listdir(srcdir + "/src"))
    keep |= {k for k in bake_keep() if re.search(rf"\b{k}\b", allsrc)}  # bq/bake_keep.txt: tables under test stay volatile with all their code; one this bot does not carry yet is
    # skipped, not an error (8 Nov: RCK_TAB/WMT_TAB, on the list for tests, failed the bake of v622-v625)
    ing = subprocess.run(["python3", "-I", os.path.join(REPO, "tools/lab/ideastore.py"), "ingest", src], capture_output=True, text=True)
    if ing.returncode:  # the source must stay restorable: no strip without it
        print(f"deadstrip: ideastore ingest {src} failed: {(ing.stdout + ing.stderr).strip()[-200:]}")
        return 1
    dst = newbot(src, new)
    baked = new + "_bk"
    bdir = newbot(src, baked)
    nb = bake(dst + "/src", keep)
    bake(bdir + "/src", keep)
    print(f"deadstrip: baked {nb[0]} tables, kept {nb[1]} volatile", flush=True)
    s = Strip(dst + "/src", keep, roots)
    # before = the unbaked source's size, so the table shows what the owner reads
    start = s.run(unused="--no-unused" not in a)
    for f in s.files:
        with open(f.path, "w", encoding="utf-8", errors="surrogateescape") as g:
            g.write(f.text)
    open(dst + "/STRIPPED", "w").write(f"SOURCE={src}\nKEEP={','.join(sorted(keep))}\nWHEN={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    print(write_report(s, src, new, start, rep, keep, srcdir + "/src", dst))
    print(f"deadstrip: records in {rep}")
    if "--check" in a:
        return check(baked, new, rep, int(opt("--maps", 40)), int(opt("--seed", 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
