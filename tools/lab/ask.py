#!/usr/bin/env python3
"""ask: ranked keyword search over our own notes, so an agent finds "has anything like X been tested and closed" without reading whole files.
Tool builder, 3 Nov (owner asked whether a RAG is worth it: this is the cheap form, BM25, no index on disk, no network).

usage: python3 -I tools/lab/ask.py "query words" [-k 12] [--closed] [--src]
  Searches paragraphs (blank-line blocks, or one table row) of: CLAUDE.md, docs/**/*.md, condor-work/reports/**/*.md (build_bNNN reports,
  board, primer, registry, queue) and /data/USER/st/b*/prereg.md. --closed: only CLAUDE.md section 8's closed rows and the closed tables of
  docs/modules. --src: also the current trunk's src (slow, larger). Prints the top k as file:line, a score, and the block's first 300 chars.
  Newer blocks rank a little higher (file mtime); every hit names its file, so check its date and whether a later line retracted it."""
import glob
import math
import os
import re
import sys
import time

REPO = "/homes/USER/cambc"
REP = "/homes/USER/condor-work/reports"
WORD = re.compile(r"[a-z][a-z0-9_]{1,}|\d+(?:\.\d+)?")
STOP = set("the a an and or of to in on for is it at by with as be was are this that from not no but if we our its".split())


def files(closed, src):
    if closed:
        return [f for f in [f"{REPO}/CLAUDE.md", f"{REPO}/docs/claude_archive.md"] + glob.glob(f"{REPO}/docs/modules/*.md") if os.path.isfile(f)]
    fs = [f"{REPO}/CLAUDE.md"] + glob.glob(f"{REPO}/docs/**/*.md", recursive=True)
    fs += glob.glob(f"{REP}/**/*.md", recursive=True) + glob.glob("/data/USER/st/b*/prereg.md")
    fs.append("/data/USER/st/bq/failure_chains.md")  # 12 Nov: the failure ledger (closures carry a 'closed by' kind, closedby.py)
    if src:
        sys.path.insert(0, REPO + "/tools/lab")
        import fastship
        fs += glob.glob(f"{REPO}/bots/{fastship.current_trunk()}/src/*")
    return [f for f in fs if os.path.isfile(f) and "/reports/live/" not in f and os.path.getsize(f) < 8 << 20]  # live digests: per-game tables, not findings


def blocks(path, closed):
    """(first line number, text) per paragraph; a markdown table row or list item is its own block."""
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return
    if closed and path.endswith(("CLAUDE.md", "claude_archive.md")):  # 5 Nov: the closed table moved to docs/claude_archive.md
        keep = [""] * len(lines)
        for a in [i for i, x in enumerate(lines) if x.startswith("**Closed on")]:
            b = next((i for i, x in enumerate(lines) if i > a and x.startswith("**In flight")), len(lines))
            keep[a:b] = lines[a:b]
        lines = keep
    cur, start = [], 0
    for i, x in enumerate(lines):
        row = x.startswith(("| ", "- ", "* ")) or re.match(r"^\d+\. ", x)
        if not x.strip() or (row and cur):
            if cur:
                yield start + 1, " ".join(cur)
            cur, start = [], i
            if not x.strip():
                continue
        if not cur:
            start = i
        cur.append(x.strip())
        if len(cur) > 12:
            yield start + 1, " ".join(cur)
            cur = []
    if cur:
        yield start + 1, " ".join(cur)


def main():
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    q = [w for w in WORD.findall(a[0].lower()) if w not in STOP]
    k = int(a[a.index("-k") + 1]) if "-k" in a else 12
    closed, src = "--closed" in a, "--src" in a
    docs = []
    for f in files(closed, src):
        age = max(0.0, (time.time() - os.path.getmtime(f)) / 86400)
        for ln, t in blocks(f, closed):
            docs.append((f, ln, t, age))
    tf = [None] * len(docs)
    df = {}
    for i, (_, _, t, _) in enumerate(docs):
        c = {}
        for w in WORD.findall(t.lower()):
            c[w] = c.get(w, 0) + 1
        tf[i] = c
        for w in c:
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    avg = sum(sum(c.values()) for c in tf) / max(1, n)
    res = []
    for i, c in enumerate(tf):
        ln = sum(c.values())
        s = 0.0
        for w in q:
            f = c.get(w, 0)
            if f:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * ln / avg))
        if s > 0:
            res.append((s / (1 + 0.02 * docs[i][3]), i))
    res.sort(reverse=True)
    try:  # a blind grill must not read a block about the game it walks (blindids.py)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import blindids
        ks = blindids.keys()
        res = [r for r in res if not blindids.hidden(docs[r[1]][2], ks)]
    except ImportError:
        pass
    # 12 Nov (owner: "ideas should always be tested before writing them off"; evidence_checklist item 13): every closure shows how it was
    # closed (closedby.py), and closures by argument come first among the hits, so an analyst sees the weakest closes
    try:
        import closedby
    except ImportError:
        closedby = None
    top = [(s, i, closedby.kind(docs[i][2]) if closedby else None) for s, i in res[:k]]
    top.sort(key=lambda x: (not (closedby and closedby.is_argument(x[2])),))
    for s, i, kd in top:
        f, ln, t, _ = docs[i]
        print(f"{f.replace('/homes/USER/', '~/')}:{ln}  [{s:.1f}]" + (f"  [closed by: {kd}]" if kd else "") + f"  {t[:300]}")
    print(f"# {n} blocks searched in {len(set(d[0] for d in docs))} files")


if __name__ == "__main__":
    main()
