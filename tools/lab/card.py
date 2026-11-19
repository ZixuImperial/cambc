#!/usr/bin/env python3
"""card: everything we know about one bot function in ONE call (Tool builder 2, 5 Nov; owner: subagents spend ~36% of their calls
on grep/sed lookups, and each call re-reads the whole context, so answer a code question in one call without losing detail).

usage: python3 -I tools/lab/card.py NAME [NAME ...] [--bot BOT] [--code] [--max N (6)]
  NAME: a function name (econ::rate_for or rate_for; templates match too), or a flag/table (FH_BITS, PS_TAB).
  --bot: default the live bot (line 1 of /data/zw4424/st/bq/live.txt).  --code: append the function body (<= 220 lines).
Prints, all with file:line so you can open exactly what you need:
  WHERE      definition(s): file:first-last, lines, signature, the // comment above it
  FLAGS      flags/tables/defines the body reads, with their value in this bot
  CALLS      other bot functions it calls;  CALLED BY  functions that call it
  ASSUMES    docs/assumptions entries naming it (id, file:line, the assumption)
  DOCS       docs/modules + codemap lines naming it
  HISTORY    closed-idea rows (docs/claude_archive.md, CLAUDE.md) and report/board/queue lines naming it, newest first
For a flag NAME: where it is defined and its value, which functions read it, and the HISTORY lines.
Reads only text files (a fraction of a second; the per-bot index is cached in /data/zw4424/st/card/)."""
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from codeindex import code, index_file  # noqa: E402

REP = "/homes/zw4424/condor-work/reports"
CACHE = "/data/zw4424/st/card"
KW = set("if for while switch return sizeof static_cast reinterpret_cast const_cast decltype alignof catch else case new delete "
         "defined int long short char unsigned bool void auto float double".split())


def live_bot():
    try:
        return open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    except (OSError, IndexError):
        sys.exit("card: no live.txt; pass --bot")


def load_index(src):
    files = sorted(f for f in os.listdir(src) if f.endswith((".cpp", ".cc", ".h")))
    key = "|".join(f"{f}:{os.path.getmtime(os.path.join(src, f)):.0f}:{os.path.getsize(os.path.join(src, f))}" for f in files)
    import zlib  # 11 Nov: str hash() is salted per process, so the cache was never reused; crc32 is stable
    cf = f"{CACHE}/{os.path.basename(os.path.dirname(os.path.realpath(src)))}_{zlib.crc32(src.encode()) % 10**8}.json"
    try:
        c = json.load(open(cf))
        if c["key"] == key:
            return c["fns"], c["defs"]
    except (OSError, ValueError, KeyError):
        pass
    fns, defs = [], {}
    tab = re.compile(r"\b(?:inline\s+)?(?:static\s+)?(constexpr|const\s+volatile|const)\s+(?:int|int64_t|long long|short)\s+(\w+)\s*\[[^\]]*\]\s*=\s*\{([^}]*)\}")
    for f in files:
        p = os.path.join(src, f)
        for a, b, ns, name, sig, com in index_file(p):
            fns.append([f, a, b, ns, re.sub(r"<.*", "", name), sig, com])
        for n, ln in enumerate(open(p, errors="replace"), 1):
            m = re.match(r"^\s*#define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)$", ln)
            if m and not m.group(1).endswith("_H"):
                defs.setdefault(m.group(1), [f, n, code(m.group(3)).strip()[:80]])
            for m in tab.finditer(code(ln)):
                defs.setdefault(m.group(2), [f, n, f"{'volatile' if 'volatile' in m.group(1) else m.group(1)} {{{m.group(3).strip()[:70]}}}"])
    os.makedirs(CACHE, exist_ok=True)
    try:
        json.dump({"key": key, "fns": fns, "defs": defs}, open(cf + f".{os.getpid()}", "w"))
        os.replace(cf + f".{os.getpid()}", cf)
    except OSError:
        pass
    return fns, defs


def body(src, fn, cache={}):
    p = os.path.join(src, fn[0])
    if p not in cache:
        cache[p] = open(p, errors="replace").read().split("\n")
    return cache[p][fn[1] - 1:fn[2]]


def history(name, mx):
    pat = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
    out = []
    fixed = [f"{REPO}/docs/claude_archive.md", f"{REPO}/CLAUDE.md", f"{REPO}/docs/issues_log.md"]
    rec = [f for f in glob.glob(f"{REP}/build_*.md") + glob.glob(f"{REP}/analysts/*.md") +
           [f"{REP}/builder_queue.md", f"{REP}/idea_queue.md", f"{REP}/subagent_primer.md"]
           if os.path.exists(f) and time.time() - os.path.getmtime(f) < 14 * 86400]
    for f in fixed + sorted(rec, key=os.path.getmtime, reverse=True):
        if not os.path.exists(f):
            continue
        try:
            head = ""  # 8 Nov (Deep: a blind grill saw '  - **W1:** our 136-gem Marcella ...', a sub-bullet whose game is named only in
            # its post's top line): an indented line is checked by the blind filter together with the top-level line it hangs under
            for n, ln in enumerate(open(f, errors="replace"), 1):
                if ln.strip() and not ln[0].isspace():
                    head = ln
                if pat.search(ln):
                    closed = ln.startswith("| ") and f.endswith(("claude_archive.md", "CLAUDE.md"))
                    out.append((0 if closed else 1, -os.path.getmtime(f), f, n, ln.strip(), head if ln[:1].isspace() else ""))
        except OSError:
            pass
    out.sort(key=lambda x: (x[0], x[1], -x[3]))
    try:  # a blind grill must not read a line about the game it walks (blindids.py)
        import blindids
        ks = blindids.keys()
        out = [o for o in out if not blindids.hidden(o[4] + " " + o[5], ks)]
    except ImportError:
        pass
    seen, res = set(), []
    for k, _, f, n, ln, _h in out:
        if (f, ln[:80]) in seen:
            continue
        seen.add((f, ln[:80]))
        res.append(f"  {'closed ' if k == 0 else ''}{f.replace('/homes/zw4424/', '~/')}:{n}  {short(ln, name, 230)}")
        if len(res) >= mx:
            break
    return res


def short(ln, name, w):
    """a window of the line around the name"""
    i = ln.find(name)
    if len(ln) <= w or i < 0:
        return ln[:w]
    a = max(0, i - w // 3)
    return ("..." if a else "") + ln[a:a + w] + "..."


def assumes(name, mx):
    res = []
    pat = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
    for f in sorted(glob.glob(f"{REPO}/docs/assumptions/*.md")):
        lines = open(f, errors="replace").read().split("\n")
        i = 0
        while i < len(lines):
            m = re.match(r"^(?:- |\d+\. )\*\*(A-[A-Z]+-\d+)\*\*", lines[i])
            if m:
                j = i + 1
                while j < len(lines) and lines[j].startswith((" ", "\t")) and lines[j].strip():
                    j += 1
                txt = " ".join(x.strip() for x in lines[i:j])
                if pat.search(txt) and not any(m.group(1) in r for r in res):
                    a = re.search(r"ASSUMES (.*?)(?: VALUE | KIND |$)", txt)
                    st = re.search(r"STATUS (\S+(?: \([^)]*\))?)", txt)
                    loc = re.search(r"`([\w./]+:\d+)`", txt)
                    res.append(f"  {m.group(1)} {loc.group(1) if loc else ''} ({os.path.basename(f)}:{i + 1}) "
                               f"{(a.group(1) if a else txt[len(m.group(0)):])[:170]}" + (f" STATUS {st.group(1)[:60]}" if st else ""))
                i = j
            else:
                i += 1
    return res[:mx * 2]


def docs(name, mx):
    res = []
    pat = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
    for f in sorted(glob.glob(f"{REPO}/docs/modules/*.md")) + [f"{REPO}/docs/nova-codemap.md"]:
        if os.path.exists(f):
            for n, ln in enumerate(open(f, errors="replace"), 1):
                if pat.search(ln):
                    res.append(f"  {os.path.relpath(f, REPO)}:{n}  {short(ln.strip(), name, 200)}")
    return res[:mx]


def card(name, src, fns, defs, a):
    mx = int(a[a.index("--max") + 1]) if "--max" in a else 6
    bare = name.split("::")[-1]
    hits = [fn for fn in fns if fn[4] == bare and (("::" not in name) or fn[3].endswith(name.rsplit("::", 1)[0]))]
    names = {fn[4] for fn in fns}
    print(f"=== {name}  ({os.path.relpath(os.path.dirname(src), REPO)})")
    if hits:
        print("WHERE")
        for fn in hits:
            print(f"  {fn[0]}:{fn[1]}-{fn[2]} ({fn[2] - fn[1] + 1} lines)  {fn[5][:150]}"
                  + (f"\n    // {fn[6][:220]}" if fn[6] else ""))
        txt = "\n".join(code(x) for fn in hits for x in body(src, fn))
        ids = re.findall(r"\b([A-Za-z_]\w*)\b", txt)
        fl = []
        for i in dict.fromkeys(ids):
            if i in defs and (i.isupper() or i.endswith("_TAB")) and i != bare:
                d = defs[i]
                fl.append(f"{i}={d[2][:50]} ({d[0]}:{d[1]})")
        if fl:
            print("FLAGS  " + "; ".join(fl[:30]) + (f"; +{len(fl) - 30} more" if len(fl) > 30 else ""))
        calls = [c for c in dict.fromkeys(re.findall(r"\b([A-Za-z_]\w*)\s*(?:<[^<>()]*>)?\s*\(", txt)) if c in names and c != bare and c not in KW]
        if calls:
            print("CALLS  " + " ".join(calls[:40]) + (f" +{len(calls) - 40}" if len(calls) > 40 else ""))
    elif name in defs:
        d = defs[name]
        print(f"DEFINED  {d[0]}:{d[1]}  {d[2]}")
    else:
        print("  (no function or define of that name in this bot)")
    pat = re.compile(r"(?<![\w.>])" + re.escape(bare) + (r"\s*(?:<[^<>()]*>)?\s*\(" if hits else r"(?![\w])"))
    by = []
    for fn in fns:
        if fn in hits:
            continue
        if any(pat.search(code(x)) for x in body(src, fn)):
            by.append(f"{fn[4]} ({fn[0]}:{fn[1]})")
    if by:
        print(("CALLED BY  " if hits else "READ BY  ") + "; ".join(by[:30]) + (f"; +{len(by) - 30} more" if len(by) > 30 else ""))
    try:  # 8 Nov (Deep): the blind filter covers every section, not only HISTORY (blindids: the game's ids and its map)
        import blindids
        bks = blindids.keys()
    except ImportError:
        bks = set()
    for title, rows in (("ASSUMES", assumes(bare, mx)), ("DOCS", docs(bare, mx)), ("HISTORY", history(bare, mx + 2))):
        rows = [r for r in rows if not any(k in r for k in bks)]
        if rows:
            print(title)
            print("\n".join(rows))
    if "--code" in a and hits:
        for fn in hits:
            b = body(src, fn)
            print(f"--- {fn[0]}:{fn[1]}-{fn[2]}")
            for k, x in enumerate(b[:220]):
                print(f"{fn[1] + k:6d}  {x}")
            if len(b) > 220:
                print(f"  ... {len(b) - 220} more lines: sed -n {fn[1] + 220},{fn[2]}p")


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    bot = a[a.index("--bot") + 1] if "--bot" in a else live_bot()
    src = os.path.join(REPO, "bots", bot, "src")
    if not os.path.isdir(src):
        sys.exit(f"card: no {src}")
    try:  # 11 Nov (RC X325: a ship moved live mid-read): name the bot every card reads, and its version when it is live
        lv = open("/data/zw4424/st/bq/live.txt").readline().split()
        tag = f"live {lv[0]}, since {lv[2]}" if lv[1:2] == [bot] else f"NOT live; live is {lv[0]} {lv[1]}"
    except (OSError, IndexError):
        tag = "live unknown"
    print(f"[card: bot {bot} ({tag})]")
    fns, defs = load_index(src)
    skip = {a.index(k) + 1 for k in ("--bot", "--max") if k in a}
    for i, n in enumerate(a):
        if not n.startswith("--") and i not in skip:
            card(n, src, fns, defs, a)


if __name__ == "__main__":
    main()
