#!/usr/bin/env python3
"""flip.py - runtime data flags of a nova trunk (NULLSW/RSW tables): list them, check a flag is data-only, predict a flip's wasm.

  flip.py list   SRC                      every `inline const volatile int X_TAB[..] = {..}` table: magic, slots, value, the
                                          #define names each slot reads, and whether each name is data-only (FLIPPABLE)
  flip.py check  SRC "FLAG=VAL ..."       refuse unless each FLAG is `#define FLAG <int>` once and every non-comment use of FLAG
                                          sits in a table initializer (so a new value changes data bytes only, never code)
  flip.py patch  SRC_OLD SRC_NEW OLD.wasm OUT.wasm
                                          evaluate every table in both sources, check OLD.wasm holds SRC_OLD's values at each
                                          table's magic (the evaluator agrees with the compiler), write OLD.wasm with SRC_NEW's
                                          values to OUT.wasm; prints the changed tables and the number of data bytes
Trunk 1 Nov 2026 (bots/nova_trunk1). Tables are found by their slot-0 magic, which must occur exactly once in the wasm."""
import os, re, sys, struct

TAB_RE = re.compile(r'inline\s+const\s+volatile\s+int\s+(\w+)\s*\[([^\]]*)\]\s*=\s*\{(.*?)\}\s*;', re.S)
DEF_RE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+(\w+)[ \t]+(.*?)[ \t]*$', re.M)
CEX_RE = re.compile(r'inline\s+constexpr\s+int\s+(\w+)\s*=\s*([^;]+);')
IDENT = re.compile(r'\b[A-Za-z_]\w*\b')


def strip_comments(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if s[j] == '\\' else 1
            out.append(c + re.sub(r'[^\n]', ' ', s[i + 1:j]) + c); i = j + 1  # string contents blanked (no flag use there)
        elif s.startswith('//', i):
            j = s.find('\n', i); j = n if j < 0 else j
            out.append(' ' * (j - i)); i = j
        elif s.startswith('/*', i):
            j = s.find('*/', i + 2); j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', s[i:j])); i = j
        else:
            out.append(c); i += 1
    return ''.join(out)


def load(src):
    files = {}
    for f in sorted(os.listdir(src)):
        if f.endswith(('.h', '.cpp', '.cc', '.hpp')):
            files[f] = strip_comments(open(os.path.join(src, f), encoding='utf8', errors='replace').read())
    return files


def defines(files):
    d = {}
    for f, s in files.items():
        for m in DEF_RE.finditer(s):
            d.setdefault(m.group(1), []).append((f, m.group(2).strip()))
        for m in CEX_RE.finditer(s):
            d.setdefault(m.group(1), []).append((f, m.group(2).strip()))
    return d


TOK = re.compile(r'\s*(0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*|<<|>>|&&|\|\||==|!=|<=|>=|[-+*/%()?:!~<>&|^])')
BIN = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5, '==': 6, '!=': 6, '<': 7, '>': 7, '<=': 7, '>=': 7, '<<': 8, '>>': 8,
       '+': 9, '-': 9, '*': 10, '/': 10, '%': 10}


class Ev:
    def __init__(self, defs):
        self.defs, self.used = defs, set()

    def name(self, nm, depth):
        if depth > 20 or nm not in self.defs:
            raise ValueError(f'unknown name {nm}')
        vals = {v for _, v in self.defs[nm]}
        if len(vals) != 1:
            raise ValueError(f'{nm} defined {len(self.defs[nm])} times with different values')
        self.used.add(nm)
        return self.expr(vals.pop(), depth + 1)

    def expr(self, s, depth=0):
        s = re.sub(r'\b(\d+)[uUlL]+\b', r'\1', s.strip())
        toks, i = [], 0
        while i < len(s):
            m = TOK.match(s, i)
            if not m:
                raise ValueError(f'cannot parse {s!r}')
            toks.append(m.group(1)); i = m.end()
            while i < len(s) and s[i].isspace():
                i += 1
        self.t, self.p, self.d = toks, 0, depth
        v = self.cond()
        if self.p != len(self.t):
            raise ValueError(f'trailing tokens in {s!r}')
        return v

    def peek(self):
        return self.t[self.p] if self.p < len(self.t) else None

    def cond(self):
        c = self.bin(1)
        if self.peek() == '?':
            self.p += 1; a = self.cond()
            if self.peek() != ':':
                raise ValueError('expected :')
            self.p += 1; b = self.cond()
            return a if c else b
        return c

    def bin(self, lvl):
        v = self.un()
        while self.peek() in BIN and BIN[self.peek()] >= lvl:
            op = self.t[self.p]; self.p += 1
            r = self.bin(BIN[op] + 1)
            v = {'||': lambda: int(bool(v) or bool(r)), '&&': lambda: int(bool(v) and bool(r)), '|': lambda: v | r,
                 '^': lambda: v ^ r, '&': lambda: v & r, '==': lambda: int(v == r), '!=': lambda: int(v != r),
                 '<': lambda: int(v < r), '>': lambda: int(v > r), '<=': lambda: int(v <= r), '>=': lambda: int(v >= r),
                 '<<': lambda: v << r, '>>': lambda: v >> r, '+': lambda: v + r, '-': lambda: v - r, '*': lambda: v * r,
                 '/': lambda: int(v / r), '%': lambda: v % r}[op]()
        return v

    def un(self):
        t = self.peek(); self.p += 1
        if t == '(':
            v = self.cond()
            if self.peek() != ')':
                raise ValueError('expected )')
            self.p += 1; return v
        if t == '!':
            return int(not self.un())
        if t == '-':
            return -self.un()
        if t == '~':
            return ~self.un()
        if t == '+':
            return self.un()
        if t is None:
            raise ValueError('unexpected end')
        if re.fullmatch(r'0[xX][0-9a-fA-F]+', t):
            return int(t, 16)
        if t.isdigit():
            return int(t)
        save = (self.t, self.p, self.d)
        v = Ev.name(self, t, self.d)
        self.t, self.p, self.d = save
        return v


def split_top(s):
    out, depth, cur = [], 0, ''
    for c in s:
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += c
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out]


def tables(files, defs):
    res = []
    for f, s in files.items():
        for m in TAB_RE.finditer(s):
            name, elems = m.group(1), split_top(m.group(3))
            vals, names = [], []
            for e in elems:
                ev = Ev(defs)
                vals.append(ev.expr(e) & 0xffffffff)
                names.append(sorted(ev.used))
            res.append(dict(file=f, line=s[:m.start()].count('\n') + 1, name=name, vals=vals, names=names))
    return res


def uses(files, nm):
    """non-comment uses of nm outside `#define nm` lines and table initializers"""
    bad = []
    for f, s in files.items():
        spans = [(m.start(), m.end()) for m in TAB_RE.finditer(s)]
        for m in re.finditer(r'\b%s\b' % re.escape(nm), s):
            pos = m.start()
            if any(a <= pos < b for a, b in spans):
                continue
            ls = s.rfind('\n', 0, pos) + 1; le = s.find('\n', pos); le = len(s) if le < 0 else le
            line = s[ls:le]
            if re.match(r'^\s*#\s*define\s+%s\b' % re.escape(nm), line):
                continue
            bad.append(f'{f}:{s[:pos].count(chr(10)) + 1}: {line.strip()[:120]}')
    return bad


def flippable(files, defs, nm):
    if nm not in defs or len(defs[nm]) != 1 or not re.fullmatch(r'-?(0[xX][0-9a-fA-F]+|\d+)', defs[nm][0][1]):
        return False, f'{nm}: not exactly one `#define {nm} <int literal>`'
    bad = uses(files, nm)
    if bad:
        return False, f'{nm}: used outside table initializers (a new value would change code): ' + '; '.join(bad[:4])
    return True, ''


def _arg(s, i):
    """the text inside the parentheses that open at s[i] ('('), or None"""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == '(':
            depth += 1
        elif s[j] == ')':
            depth -= 1
            if depth == 0:
                return s[i + 1:j]
    return None


def nocode_bits(files, defs, tab, slot, old, new):
    """8 Nov (Builder, Rule Checker R1): bits of a *_BITS flip that no code tests in this source (a bake/strip pass removed their code,
    so the flip is a silent no-op). The masks tested: STEM_ON(mask) (STEM_ON reads slot k of TAB) and TAB[k] & mask / mask & TAB[k].
    -> list of changed bits nothing tests, or None when a tested mask can't be evaluated (then nothing can be said)."""
    stem = tab[:-4] if tab.endswith('_TAB') else tab
    on_slot = 1
    for _, v in defs.get(stem + '_ON', []):
        m = re.search(re.escape(tab) + r'\s*\[\s*(\d+)\s*\]', v)
        if m:
            on_slot = int(m.group(1))
    masks = []

    def on_define(s, pos):  # the macro's own #define line is not a test
        ls = s.rfind('\n', 0, pos) + 1
        return re.match(r'\s*#\s*define\b', s[ls:pos]) is not None

    for s in files.values():
        if on_slot == slot:
            for m in re.finditer(r'\b' + re.escape(stem) + r'_ON\s*\(', s):
                if on_define(s, m.start()):
                    continue
                masks.append(_arg(s, m.end() - 1))
        for m in re.finditer(re.escape(tab) + r'\s*\[\s*(\d+)\s*\]\s*&\s*(\(|[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)', s):
            if int(m.group(1)) != slot or on_define(s, m.start()):
                continue
            masks.append(_arg(s, m.start(2)) if m.group(2) == '(' else m.group(2))
        for m in re.finditer(r'([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+|\))\s*&\s*' + re.escape(tab) + r'\s*\[\s*(\d+)\s*\]', s):
            if int(m.group(2)) != slot or on_define(s, m.start()):
                continue
            if m.group(1) == ')':
                return None  # a parenthesised mask before the table: not parsed here
            masks.append(m.group(1))
    # 10 Nov (Rule Checker flag-table audit): only claim 'no code' when every read of TAB[slot] is one of the mask tests above. A cached read
    # (int b = X_TAB[1]; ... b & 4), a read passed on, or a named bit macro whose body reads the slot and is used somewhere -> unknown (None).
    slot_re = re.compile(r'\b' + re.escape(tab) + r'\s*\[\s*' + str(slot) + r'\s*\]')
    for name, vals in defs.items():
        if name == stem + '_ON' or not any(slot_re.search(v) for _, v in vals):
            continue
        use = re.compile(r'\b' + re.escape(name) + r'\b')
        for s in files.values():
            if any(not on_define(s, m.start()) for m in use.finditer(s)):
                return None
    for s in files.values():
        for m in slot_re.finditer(s):
            if on_define(s, m.start()):
                # 11 Nov (b1870/b1883: FMB_BAG(live) reads FMB_TAB[1] as a VALUE): a read inside a macro (function-like too) that code
                # uses somewhere is a real read we can't mask-check: unknown, never 'no code'
                ls = s.rfind('\n', 0, m.start()) + 1
                dm = re.match(r'\s*#\s*define\s+(\w+)', s[ls:m.start()])
                if dm and dm.group(1) != stem + '_ON':
                    use = re.compile(r'\b' + re.escape(dm.group(1)) + r'\b')
                    if any(not on_define(x, u.start()) for x in files.values() for u in use.finditer(x)):
                        return None
                continue
            ls = s.rfind('\n', 0, m.start()) + 1
            if re.search(r'\binline\b.*\bvolatile\b', s[ls:m.start()]):
                continue  # the table's own definition
            after, before = s[m.end():m.end() + 3].lstrip(), s[max(0, m.start() - 3):m.start()].rstrip()
            if not (after.startswith('&') and not after.startswith('&&')) and not (before.endswith('&') and not before.endswith('&&')):
                return None  # a read that is not a mask test
    tested = 0
    for mk in masks:
        if mk is None:
            return None
        try:
            tested |= Ev(defs).expr(mk) & 0xffffffff
        except ValueError:
            return None  # a run-time mask (a variable): can't tell which bits have code
    changed = (old ^ new) & 0xffffffff
    return [1 << b for b in range(32) if changed >> b & 1 and not tested >> b & 1]


def magic_off(wasm, magic):
    k = struct.pack('<I', magic)
    i = wasm.find(k)
    if i < 0 or wasm.find(k, i + 1) >= 0:
        return None
    return i


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(2)
    cmd = sys.argv[1]
    if cmd == 'list':
        files = load(sys.argv[2]); defs = defines(files)
        for t in tables(files, defs):
            flags = sorted({n for ns in t['names'][1:] for n in ns})
            fl = ' '.join(f"{n}={defs[n][0][1]}{'' if flippable(files, defs, n)[0] else '(CODE)'}" for n in flags)
            print(f"{t['name']:<18} {t['file']}:{t['line']:<5} magic 0x{t['vals'][0]:08X} slots {t['vals'][1:]}  {fl}")
    elif cmd == 'check':
        files = load(sys.argv[2]); defs = defines(files); ok = True
        for kv in sys.argv[3].split():
            nm, _, val = kv.partition('=')
            if not re.fullmatch(r'-?\d+', val):
                print(f'REFUSE {kv}: the value must be an integer'); ok = False; continue
            baked = [m.group(1) for f_ in files.values() for m in re.finditer(r'inline\s+constexpr\s+int\s+(\w+)\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}', f_)
                     if re.search(r'\b%s\b' % re.escape(nm), m.group(2))]
            if baked:  # 8 Nov (Builder, Rule Checker R1): a baked table can't be flipped; its off branches may be stripped as well
                print(f'REFUSE {nm}: its table {baked[0]} is baked (constexpr) in this source, so a flip changes nothing. Make it volatile again '
                      f'(one line) and restore any stripped off-branch code from the ideastore, or test on the version before the bake'); ok = False
                continue
            good, why = flippable(files, defs, nm)
            if not good:
                print('REFUSE ' + why); ok = False
            elif not any(nm in ns for t in tables(files, defs) for ns in t['names']):
                print(f'REFUSE {nm}: no table reads it'); ok = False
            else:  # 6 Nov (Builder: MFB_TAB made volatile to flip one bit, 1.28x fuel cut-offs on the trunk-code row): a volatile read costs fuel
                for t in tables(files, defs):
                    if any(nm in ns for ns in t['names']) and nm.endswith('_BITS'):
                        slot = next(i for i, ns in enumerate(t['names']) if nm in ns)
                        try:
                            oldv = Ev(defs).expr(defs[nm][0][1]) & 0xffffffff
                        except ValueError:
                            oldv = None
                        nc = nocode_bits(files, defs, t['name'], slot, oldv, int(val) & 0xffffffff) if oldv is not None else None
                        if nc:  # 10 Nov (Rule Checker: CI2_BITS and 42 '0 = off' tables with no reader): a flip that changes no play fails loudly
                            allow = os.environ.get("FLIP_ALLOW_NOCODE") == "1"
                            print(f"{'WARN' if allow else 'REFUSE'} NOCODE {nm}={val}: bit(s) {', '.join(str(b) for b in nc)} of {t['name']} are tested "
                                  f"nowhere in this source: that part of the flip changes no play (its code was stripped or baked, or never existed; "
                                  f"restore it from the ideastore first){'' if allow else '. FLIP_ALLOW_NOCODE=1 to arm it anyway'}")
                            ok = ok and allow
                    if any(nm in ns for ns in t['names']):
                        stem = t['name'][:-4] if t['name'].endswith('_TAB') else t['name']
                        nread = sum(len(re.findall(r'\b' + re.escape(t['name']) + r'\s*\[', x)) + len(re.findall(r'\b' + re.escape(stem) + r'_ON\s*\(', x)) for x in files.values())
                        if nread >= 20:
                            print(f'WARN {nm}: its table {t["name"]} is read at {nread} sites; every read of a volatile table costs fuel (MFB_TAB: 1.28x cut-offs). '
                                  'For a one-bit change on a hot table, ship a compile-time constant instead, or check the capped-fuel row')
        sys.exit(0 if ok else 1)
    elif cmd == 'patch':
        so, sn, wo, out = sys.argv[2:6]
        fo, fn = load(so), load(sn)
        to, tn = tables(fo, defines(fo)), tables(fn, defines(fn))
        if [t['name'] for t in to] != [t['name'] for t in tn] or [len(t['vals']) for t in to] != [len(t['vals']) for t in tn]:
            print('FAIL: the two sources hold different tables'); sys.exit(1)
        w = bytearray(open(wo, 'rb').read()); nb = 0
        for a, b in zip(to, tn):
            off = magic_off(w, a['vals'][0])
            if off is None and a['vals'] == b['vals']:  # 8 Nov (v631 arms): a table no code reads any more (baked base) is dropped by the linker; this flip does not change it
                continue
            if off is None:
                print(f"FAIL: magic of {a['name']} not found exactly once in {wo}"); sys.exit(1)
            got = list(struct.unpack_from('<%dI' % len(a['vals']), w, off))
            if got != a['vals']:
                print(f"FAIL: {a['name']} in the wasm {got} != source {a['vals']} (rebuild the trunk wasm)"); sys.exit(1)
            if a['vals'] != b['vals']:
                new = struct.pack('<%dI' % len(b['vals']), *b['vals'])
                nb += sum(1 for i in range(len(new)) if new[i] != w[off + i])
                w[off:off + len(new)] = new
                print(f"  {b['name']} ({b['file']}:{b['line']}): {a['vals'][1:]} -> {b['vals'][1:]}")
        open(out, 'wb').write(w)
        print(f'data bytes changed: {nb}')
        if nb == 0:
            print('WARN NOCODE: this flip changes no data bytes: the new wasm is the old one (the flags already had these values, or the table is baked)')
    else:
        print(__doc__); sys.exit(2)


if __name__ == '__main__':
    main()
