#!/usr/bin/env python3
"""reopen: which CLOSED ideas are worth one retest after a big change, ranked. Tool builder, 3 Nov (owner: "sometimes we need to reopen
ideas as we have made big changes; how should we go about this?"). Read-only: prints to stdout, writes nothing.

usage: python3 -I tools/lab/reopen.py [--since vNNN] [--change FLAG,FLAG,...] [-k 15] [--all]
  Ideas: the closed rows of bq/failure_chains.md (state closed; 9 Nov) and the old CLAUDE.md / docs/claude_archive.md tables. Reads: shipcheck outputs (bq/shipwatch_*.out) and
  gate verdicts (st/gate/TAG/verdict.txt, not tc*/drift*/h2h*), joined to a row by its FLAG=V tokens (the candidate's own flips: FLIP file's
  FLIPS minus LIVEVALS), by a 'shipcheck NNNN' or 'gate TAG' it cites, or else by its agent number in the candidate's name. Latest read counts.
  The big change: default, per idea, every function that differs between the live version at its last read and live now (text changed,
  new or deleted, plus the users of every #define whose value changed); --since vNNN: the same from vNNN for every idea; --change: the
  functions in live that use those flags or their tables.
  Per idea: miss = (.503 - point) / SE of the pooled row (else BIG and fresh pooled by maps, 'pooled*', else fresh, else BIG),
  floored at 0; reads of a change that later shipped (all own flips in a PASS shipcheck) are dropped; overlap = share of the idea's functions
  (those using its flags, their table slots or one level of #define on them; live's src, else the candidate's) inside the change; ceiling
  tier from the row's 'ceiling ...' phrase (about 0 / under +.1 / null / no lever / small .3, other phrase 1, none .7).
  score = 1/(1+miss) x overlap x ceiling, halved when the read was a bundle whose other part shipped later. Cost: 'data flip on live' (volatile table in live), 'un-bake' (baked or #define only), 'rebase'.
  --all also prints every row that was not scored and why. About 25 s by default, 8 s with --since or --change."""
import calendar
import glob
import os
import re
import sys
import time

REPO = "/homes/zw4424/cambc"
BQ = "/data/zw4424/st/bq"
REP = "/homes/zw4424/condor-work/reports"
sys.path.insert(0, REPO + "/tools/lab")
from codeindex import code, index_file  # noqa: E402

TOK = re.compile(r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9])=(-?\d+)\b")
BITS = re.compile(r"\b([A-Z][A-Z0-9]*_BITS)\b")
NUM = r"([\d.]+) \[([\d.]+), ([\d.]+)\]"
DEF = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)$")
TAB = re.compile(r"\b(?:inline\s+)?(const\s+volatile|constexpr|const)\s+int\s+(\w+_TAB)\s*\[[^\]]*\]\s*=\s*\{")
BAR = 0.503


def closed_rows():
    """closed-idea table rows ('**Closed on ...' to the next '**In flight'), from CLAUDE.md and, since 5 Nov, docs/claude_archive.md"""
    out = []
    for p in (f"{REPO}/CLAUDE.md", f"{REPO}/docs/claude_archive.md"):
        if not os.path.exists(p):
            continue
        lines = open(p, errors="replace").read().splitlines()
        for a in [i for i, x in enumerate(lines) if x.startswith("**Closed on")]:
            b = next((i for i, x in enumerate(lines) if i > a and x.startswith("**In flight")), len(lines))
            for i in range(a, b):
                c = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if lines[i].startswith("| ") and len(c) >= 2 and c[0] != "Agent" and not c[0].startswith("---"):
                    out.append((f"{os.path.basename(p)}:{i + 1}", c[0], " | ".join(c[1:])))
    # 9 Nov (Combat: reopen printed '0 closed rows' since CLAUDE.md section 8 moved to the ledgers): the failure-chain ledger's closed ideas, table
    # rows whose state column says closed and bullet lines that say closed (their FLAG=V tokens ride in the text)
    fc = "/data/zw4424/st/bq/failure_chains.md"
    try:
        for i, ln in enumerate(open(fc, errors="replace").read().splitlines()):
            if ln.startswith("| "):
                c = [x.strip() for x in ln.strip().strip("|").split("|")]
                if len(c) >= 3 and c[0] not in ("chain",) and not c[0].startswith("---") and re.search(r"\bclosed\b", c[-1], re.I):
                    out.append((f"bq/failure_chains.md:{i + 1}", c[0], " | ".join(c[1:])))
            elif ln.startswith("- ") and re.search(r"\bCLOSED\b|\bclosed\b", ln):
                m = re.search(r"\b([A-Z][A-Z0-9_]{2,})\b", ln[2:])
                out.append((f"bq/failure_chains.md:{i + 1}", m.group(1) if m else ln[2:40], ln[2:]))
    except OSError:
        pass
    return out


def versions():
    """[(vNNN, bot, epoch)] newest first."""
    out = []
    for line in open(f"{BQ}/live.txt", errors="replace"):
        m = re.match(r"^(v\d+) (\S+) (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", line)
        if m:
            out.append((m.group(1), m.group(2), calendar.timegm(time.strptime(m.group(3), "%Y-%m-%dT%H:%M:%SZ"))))
    return out


def src_dir(bot):
    s = os.path.realpath(f"{REPO}/bots/{bot}/src")
    return s if bot and os.path.isdir(s) else None


def kv(s):
    return set(TOK.findall(s or ""))


def marker(bot, key):
    for name in ("FLIP", "SHIPCHECK"):
        try:
            m = re.search(rf"^{key}=(.*)$", open(f"{REPO}/bots/{bot}/{name}").read(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).strip()
    return None


def num(m, n_grp=4):
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(n_grp))) if m else None


def reads():
    """[dict] one per shipcheck output or gate verdict."""
    out = []
    for f in glob.glob(f"{BQ}/shipwatch_*.out"):
        t = open(f, errors="replace").read()
        hs = list(re.finditer(r"^SHIPCHECK (\S+): (\S+) vs live (\S+),", t, re.M))
        if not hs:
            continue
        h = hs[-1]
        blk = t[h.start():]
        cand = h.group(2)
        v = re.search(r"shipcheck \S+: \S+ vs live \S+ \((v\d+)\)", t)
        tm = re.findall(r"TRUNK mode: flip of \S+ \(([^;)]*)[;)].*?(?:LIVEVALS ([^)]*)\))?", t)
        flips = kv(marker(cand, "FLIPS")) or (kv(tm[-1][0]) if tm else set())
        live = kv(marker(cand, "LIVEVALS")) | (kv(tm[-1][1]) if tm else set())
        rows = {"pooled": num(re.search(r"pooled BIG \+ fresh\s+" + NUM + r" n (\d+)", blk)),
                "fresh": num(re.search(r"fresh maps\s+CAND vs LIVE " + NUM + r" over (\d+)", blk)),
                "BIG": num(re.search(r"live h2h\s+" + NUM + r" n (\d+)", blk))}
        ov = re.search(r"OVERALL: (\w+)", blk)
        out.append(dict(kind="shipcheck", tag=h.group(1), cand=cand, t=os.path.getmtime(f), v=v.group(1) if v else None,
                        own=own(flips - live, h.group(3)), rows=rows, verdict=ov.group(1) if ov else "?"))
    for f in glob.glob("/data/zw4424/st/gate/*/verdict.txt"):
        tag = f.split("/")[-2]
        if tag.startswith(("tc", "drift", "h2h")):
            continue
        t = open(f, errors="replace").read()
        h = re.search(r"^GATE \S+: (\S+) vs (\S+), lane \w+, (\d{4}-\d\d-\d\d \d\d:\d\d) UTC", t, re.M)
        if not h:
            continue
        cand = h.group(1)
        rows = {"pooled": num(re.search(r"pooled BIG\+fresh\s+" + NUM + r" n (\d+)", t)),
                "fresh": num(re.search(r"fresh maps\s+CAND vs LIVE " + NUM + r" over (\d+)", t)),
                "BIG": num(re.search(r"BIG \(killgate\)\s+\w+: " + NUM + r" LOS \d+% \((\d+) maps", t))}
        ov = re.search(r"OVERALL: (\w+)", t)
        out.append(dict(kind="gate", tag=tag, cand=cand, t=calendar.timegm(time.strptime(h.group(3), "%Y-%m-%d %H:%M")), v=None,
                        own=own(kv(marker(cand, "FLIPS")) - kv(marker(cand, "LIVEVALS")), h.group(2)), rows=rows,
                        verdict=ov.group(1) if ov else "?"))
    for r in out:
        b, fr = r["rows"]["BIG"], r["rows"]["fresh"]
        if not r["rows"]["pooled"] and b and fr:  # no pooled row (older reads, fix lane): pool BIG and fresh by maps
            n = b[3] + fr[3]
            p = (b[0] * b[3] + fr[0] * fr[3]) / n
            se = ((b[3] * (b[2] - b[1])) ** 2 + (fr[3] * (fr[2] - fr[1])) ** 2) ** 0.5 / n / 3.92
            r["rows"]["pooled*"] = (p, p - 1.96 * se, p + 1.96 * se, n)
    return out


_defs = {}


def own(flips, base):
    """The flips whose value differs from the read's base bot (a FLIP file also lists live values its trunk lacked)."""
    s = src_dir(base)
    if not s:
        return flips
    if s not in _defs:
        d = {}
        for f in glob.glob(s + "/*.h"):
            for x in open(f, errors="replace"):
                m = DEF.match(x)
                if m:
                    d[m.group(1)] = code(m.group(3)).strip()
        _defs[s] = d
    return {(f, v) for f, v in flips if _defs[s].get(f) != v}


_src = {}


def src_info(src):
    """Per src dir: functions {ns::name: (code text, file:line)}, #defines {name: (args, body)}, tables {name: (kind, [elements])}."""
    if src in _src:
        return _src[src]
    funcs, defs, tabs = {}, {}, {}
    for f in sorted(os.listdir(src)):
        if not f.endswith((".cpp", ".cc", ".h")):
            continue
        p = os.path.join(src, f)
        lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
        for a, b, ns, name, sig, com in index_file(p):
            k = f"{ns}::{name}" if ns else name
            txt = "\n".join(code(x) for x in lines[a - 1:b])
            old = funcs.get(k)
            funcs[k] = (old[0] + "\n" + txt if old else txt, old[1] if old else f"{f}:{a}")
        for i, x in enumerate(lines):
            m = DEF.match(x)
            if m:
                defs[m.group(1)] = (m.group(2) or "", code(m.group(3)).strip())
            m = TAB.search(x)
            if m:
                body, j = code(x[m.end():]), i
                while "}" not in body and j + 1 < len(lines) and j - i < 40:
                    j += 1
                    body += " " + code(lines[j])
                body = re.sub(r"/\*.*?\*/", "", body.split("}")[0])
                tabs[m.group(2)] = ("volatile" if "volatile" in m.group(1) else "baked", [e.strip() for e in body.split(",")])
    _src[src] = (funcs, defs, tabs)
    return _src[src]


def flag_funcs(src, flags):
    """({ns::name: hits}, cost) of the functions that use the flags, their table slots or one level of #define on them;
    cost 'flip' (a volatile table holds a flag), 'baked' (only baked or #define), None (no flag here)."""
    funcs, defs, tabs = src_info(src)
    pats, cost = [], None
    for fl in flags:
        p = [rf"\b{fl}\b"]
        seen = fl in defs
        for t, (kind, el) in tabs.items():
            for i, e in enumerate(el):
                if re.search(rf"\b{fl}\b", e):
                    p.append(rf"\b{t}\s*\[\s*{i}\s*\]")
                    seen = True
                    cost = "flip" if kind == "volatile" else cost or "baked"
        if not seen:
            continue
        cost = cost or "baked"
        one = re.compile("|".join(p))
        for d, (args, body) in defs.items():
            if d != fl and one.search(body):
                p.append(rf"\b{d}\b")
        pats += p
    if not pats:
        return {}, None
    rx = re.compile("|".join(pats))
    hits = {}
    for k, (txt, where) in funcs.items():
        n = len(rx.findall(txt))
        if n:
            hits[k] = n
    # 11 Nov (b2018: BLX reads its flag through blx_r(), so tank_bail_out never counted): one level of callers of the small helpers
    # (<= 12 lines) that use the flag
    done = set()
    for _lvl in range(2):  # helper of a helper (blx_r -> blx_bail_line -> tank_bail_out)
        helpers = [k.split("::")[-1] for k in hits if k not in done and funcs[k][0].count("\n") <= 12
                   and re.match(r"^[A-Za-z_]\w*$", k.split("::")[-1])]
        done |= set(hits)
        if not helpers:
            break
        cx = re.compile(r"\b(?:" + "|".join(map(re.escape, helpers)) + r")\s*\(")
        for k, (txt, where) in list(funcs.items()):
            if k not in hits:
                n = len(cx.findall(txt))
                if n:
                    hits[k] = n
    return hits, cost


_chg = {}


def change_funcs(base_src, live_src):
    """Functions of live that differ from base (text, new, deleted) plus users of every #define whose value differs."""
    key = (base_src, live_src)
    if key not in _chg:
        fb, db, _ = src_info(base_src)
        fl, dl, _ = src_info(live_src)
        ch = {k for k in set(fb) | set(fl) if fb.get(k, (None,))[0] != fl.get(k, (None,))[0]}
        moved = [d for d in set(db) | set(dl) if db.get(d) != dl.get(d) and not d.endswith("_H")]
        ch |= set(flag_funcs(live_src, moved)[0]) if moved else set()
        _chg[key] = ch
    return _chg[key]


CEIL = re.compile(r"ceiling\b(?! ledger)((?:(?!;|\. |, |\||\)).){3,80}?)(?=;|\. |, |\||\)|$)", re.I | re.M)


def ceiling(key, text):
    ok = lambda m: m and not m.group(1).strip().startswith("(") and re.search(r"\d|about|under|near|null|small|lever", m.group(1), re.I)  # noqa: E731
    m = next((x for x in CEIL.finditer(text) if ok(x)), None)
    if not m:
        n = re.match(r"b(\d+)", key)
        for f in glob.glob(f"{REP}/build_b{n.group(1)}_*.md") if n else ():
            m = next((x for x in CEIL.finditer(open(f, errors="replace").read()) if ok(x)), None)
            if m:
                break
    if not m:
        return None, 0.7
    ph = ("ceiling" + m.group(1)).strip()
    low = re.search(r"(?:about|near) 0\b|about \+?0?\.00|(?:under|<) \+?0?\.(?:0\d*|1)\b|\+\.00|\bnull\b|no lever|\bsmall\b|\b0 to\b", ph, re.I)
    return ph, 0.3 if low else 1.0


def main():
    t0 = time.time()
    a = sys.argv[1:]
    if "-h" in a or "--help" in a:
        print(__doc__)
        return
    k = int(a[a.index("-k") + 1]) if "-k" in a else 15
    since = a[a.index("--since") + 1] if "--since" in a else None
    change = a[a.index("--change") + 1].split(",") if "--change" in a else None
    vs = versions()
    live_v, live_bot = vs[0][0], vs[0][1]
    live_src = src_dir(live_bot)
    _, live_defs, _ = src_info(live_src)
    vsrc = {v: src_dir(b) for v, b, _ in vs}

    def base_of(v):
        """(src, label): that version's bot, else the nearest newer one still on disk (a smaller change: label '~vNNN')."""
        i = next((j for j, x in enumerate(vs) if x[0] == v), None)
        if i is None:
            return None, v
        for j in range(i, -1, -1):
            if vsrc[vs[j][0]]:
                return vsrc[vs[j][0]], (vs[j][0] if j == i else "~" + vs[j][0])
        return None, v

    def version_at(t):
        return next((v for v, b, tv in vs if tv <= t), vs[-1][0])

    fixed = None
    if change:
        fixed = (set(flag_funcs(live_src, change)[0]), "by --change " + ",".join(change))
    elif since:
        s, lab = base_of(since)
        if not s:
            sys.exit(f"reopen: no bot on disk for {since} or any later version")
        fixed = (change_funcs(s, live_src), f"since {lab}")
    rd = reads()
    shipped = {x for r in rd if r["kind"] == "shipcheck" and r["verdict"] == "PASS" for x in r["own"]}
    rd = [r for r in rd if not (r["own"] and r["own"] <= shipped)]  # reads of what later shipped are not about a closed idea
    scored, skipped, seen = [], [], {}
    for ln, key, text in closed_rows():
        toks = {(f, v) for f, v in TOK.findall(text) if live_defs.get(f, ("", ""))[1] != v and (f, v) not in shipped}
        cites = set(re.findall(r"shipcheck (\d{3,5})", text)) | set(re.findall(r"\bgate (\w+)", text))
        agents = set(re.findall(r"\bb(\d{3,4})\b", key))
        m = [r for r in rd if (toks & r["own"]) or r["tag"] in cites]
        if not m and agents:
            m = [r for r in rd if (re.match(r"nova_b(\d+)[a-z]*_", r["cand"]) or [None, None])[1] in agents]
        if not m:
            skipped.append((ln, key, "no FLAG=V tokens" if not toks and not cites else "no read found", text))
            continue
        m.sort(key=lambda r: r["t"])
        withnum = [r for r in m if any(r["rows"].values())]
        if not withnum:
            skipped.append((ln, key, f"{len(m)} reads, none with a number", text))
            continue
        last = withnum[-1]
        row = next(n for n in ("pooled", "pooled*", "fresh", "BIG") if last["rows"].get(n))
        p, lo, hi, n = last["rows"][row]
        se = max((hi - lo) / 3.92, 1e-6)
        miss = max(0.0, (BAR - p) / se)
        flags = sorted({f for f, v in toks} or {f for r in m for f, v in r["own"]} | set(BITS.findall(text)))
        dup = last["tag"]  # rows that land on one read (b936 and b936 DLK) are one idea
        if dup in seen:
            seen[dup][1] += " / " + key
            continue
        hits, cost = flag_funcs(live_src, flags)
        where = "live"
        if not hits:
            s = src_dir(last["cand"]) or src_dir(marker(last["cand"], "TRUNK"))
            hits, cost = flag_funcs(s, flags) if s else ({}, None)
            where, cost = "not in live", "rebase"
        if not hits:
            skipped.append((ln, key, "no code found for " + (" ".join(flags) or "its flags"), text))
            continue
        bv = last["v"] or version_at(last["t"])
        if fixed:
            ch, blab = fixed
        else:
            s, lab = base_of(bv)
            ch, blab = (change_funcs(s, live_src), f"since {lab}") if s else (set(), f"{bv} gone")
        inter = sorted(set(hits) & ch, key=lambda f: -hits[f])
        ov = len(inter) / len(hits)
        ph, ct = ceiling(key, text)
        conf = sorted(last["own"] & shipped)  # a bundle read whose other part shipped later (b764's 31b with 31a): half weight
        score = 1 / (1 + miss) * ov * ct * (0.5 if conf else 1)
        cost = {"flip": "data flip on live", "baked": "un-bake"}.get(cost, "rebase")
        why = ("near miss" if miss < 1 else "missed" if miss < 3 else "clear fail") + f" ({miss:.1f} SE)"
        why += f"; {len(inter)} of its {len(hits)} functions changed {blab}" + ("" if where == "live" else "; code not in live")
        why += "; read also carried later-shipped " + " ".join(f"{f}={v}" for f, v in conf) + " (x.5)" if conf else ""
        scored.append([score, key, flags, last, row, p, n, miss, bv, len(m), inter, hits, ph, cost, why, ln])
        seen[dup] = scored[-1]
    # 11 Nov (Builder/b2018: 500 of 690 closed rows have no FLAG=V read, mostly Step-0 closes): with --change or --since, match those rows
    # by the functions their flags touch. Flags = *_BITS names in the row + KEY_BITS/_ON/_TAB; code = live, else the row's agents' bots.
    step0 = []
    if fixed:
        ch0, blab0 = fixed
        for ln, key, why0, text in skipped:
            if not why0.startswith(("no FLAG=V", "no read found")):
                continue
            ks = {t for t in re.findall(r"\b([A-Z][A-Z0-9]{1,5})\b", key + " " + text[:80]) if not t.isdigit()}
            flags = sorted(set(BITS.findall(text)) | {f"{t}_{x}" for t in ks for x in ("BITS", "ON", "TAB")})
            hits, _ = flag_funcs(live_src, flags)
            where = "live"
            if not hits:
                for ag in sorted(set(re.findall(r"\bb(\d{3,4})\b", key + " " + text)))[:4]:
                    for sd in sorted(glob.glob(f"/data/zw4424/st/new/bots/nova_b{ag}_*/src"))[-6:]:
                        hits, _ = flag_funcs(sd, flags)
                        if hits:
                            where = os.path.basename(os.path.dirname(sd))
                            break
                    if hits:
                        break
            if not hits:
                continue
            inter = sorted(set(hits) & ch0, key=lambda f: -hits[f])
            if inter:
                step0.append((len(inter) / len(hits), key, inter, hits, where, ln, text))
        step0.sort(key=lambda x: (-x[0], -len(x[2])))
    scored.sort(key=lambda x: -x[0])
    show = scored if "--all" in a else scored[:k]
    for i, (score, key, flags, last, row, p, n, miss, bv, nr, inter, hits, ph, cost, why, ln) in enumerate(show, 1):
        own = " ".join(f"{f}={v}" for f, v in sorted(last["own"])) or " ".join(flags[:3])
        print(f"{i:2d}. {key} [{own}] score {score:.3f} | last {last['kind']} {last['tag']} {last['verdict']}: {row} {p:.4f} n{n} "
              f"miss {miss:.1f} SE on {bv} ({nr} read{'s' if nr > 1 else ''}) | overlap {len(inter)}/{len(hits)} "
              f"{','.join(inter[:3]) or '-'} | {ph or 'no ceiling stated'} | {cost} | {why} ({ln})")
    if step0:
        print(f"# Step-0 / unread closes whose flags' functions the change touches ({fixed[1]}; no read, so no score: overlap only)")
        for i, (ov, key, inter, hits, where, ln, text) in enumerate(step0[:k if "--all" not in a else None], 1):
            print(f"s{i:d}. {key} overlap {len(inter)}/{len(hits)} {','.join(inter[:4])} | code in {where} | {text[:90]} ({ln})")
    if "--all" in a:
        for ln, key, why, text in skipped:
            print(f"--. {key}: skipped, {why} | {text[:90]} ({ln})")
    why = {}
    for s in skipped:
        w = s[2].split(" for ")[0] if s[2].startswith("no code") else re.sub(r"^\d+ reads", "reads", s[2])
        why[w] = why.get(w, 0) + 1
    print(f"# {len(scored) + len(skipped)} closed rows: {len(scored)} scored ({sum(1 for s in scored if s[0] > 0)} > 0), "
          f"{len(skipped)} skipped ({', '.join(f'{w} {c}' for w, c in sorted(why.items()))}); live {live_v} {live_bot}; "
          f"change: {fixed[1] if fixed else 'per idea, since its last read version'}; {len(rd)} reads; {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
