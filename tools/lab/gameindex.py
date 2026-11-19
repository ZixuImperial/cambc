#!/usr/bin/env python3
"""COLUMNS (pinned 10 Nov; read by header name, not position): gameindex.tsv and --out's all.tsv have a header row:
  id path our_seat version foe map result lane created dup_key form foe_epoch
  margin, end_round (13 Nov, VV: find thin wins without loading replays): our final submitted gems minus theirs, and the last round,
           from the replay's final record (decoded once per dup_key, cached in /data/zw4424/st/gameindex.outcome.tsv; a build decodes at
           most GI_OUTCOME_MAX (400) new replays, `gameindex.py outcomes` fills the rest). '?' with no replay copy, unknown seat or not yet read.
  foe_epoch (12 Nov): the foe's bot generation, tools/lab/foeepoch.py (e0, e1, ...; '?' inside a change window; '-' no window known)
  `lookup` prints, without a header: version id our_seat result path map foe lane
  deaths.py takes all.tsv directly: `deaths.py --from-tsv DIR/all.tsv --out FILE` (seat per row, both seats in one run).
One index of every live/ladder game on disk, so readers stop globbing /data/zw4424/plat by hand.

usage:
  python3 -I tools/lab/gameindex.py build [--if-older SECS] [--quiet]
  python3 -I tools/lab/gameindex.py lookup IDS... | --file F | --critgame-open | --losses [--from 704] [--foe X] [--lane L] [--foe-epoch eN|new|old]
                                    [--out DIR] [--all-cols]

build: writes /data/zw4424/st/gameindex.tsv (atomic), one row per FULL match id (never a prefix), columns
  id path our_seat version foe map result lane created dup_key form
  path     best copy: <set>/x_<id>/replay.repl26a, else the downloads.tsv register's path, else <set>/<id>.zip, else '-'
  form     replay | zip | missing
  our_seat a|b|?    result win|loss|draw|?    created: UTC from the id (UUIDv7 time), else '?'
  lane     top3 / side / ranked / unranked / critgame / other. Order of evidence: st/climb_top3 -> top3, st/climb_side* ->
           side, st/climb (main climb) -> unranked; then the plat set holding it (rk_ ranked, unr_ unranked, top3_ top3);
           then st/crit/all_losses.tsv's lane (and st/crit/<id>/meta.json for version/seat); then plat/crit_auto -> critgame; else other.
  meta     (seat/version/foe/map/result) from, in order: climb games.tsv, the set's matches.txt (foe '_' -> ' '),
           all_losses.tsv, set-dir name *_vNNN (version), team-[ab] log names in x_<id>/ (seat).
  dup_key  SIZE:CRC32 of the replay.repl26a bytes (for a zip: the member's size and CRC from the zip directory, no
           decompression; for an extracted replay: crc32 of the file, cached by inode/size/mtime in
           /data/zw4424/st/gameindex.crc.tsv, so a rebuild reads only new files). Two ids with one dup_key are byte-identical
           replays: the same game re-played. '-' when there is no copy.
lookup: prints TSV `version id our_seat result path map foe lane` (header on stderr); unknown ids print '?' rows.
  --critgame-open   ids from the OPEN lines of `critgame.py status`
  --losses          ids from /data/zw4424/st/crit/all_losses.tsv, filtered by --from N (version >= vN), --foe (substring,
                    case and '_'/' ' insensitive), --lane (all_losses lane prefix, e.g. top3, side, ranked)
  --dedup           keep the first id of each dup_key
  --ranked-only     keep only ranked-lane games (lane 'ranked'); kind = ranked | unranked (top3, side, unranked) | unknown
  --include-unranked  keep unranked games while /data/zw4424/st/bq/UNRANKED_OFF exists (owner 11 Nov: they are dropped by default)
  --out DIR         also writes DIR/a.lst and DIR/b.lst (replay/zip paths where we were seat a / b; for deaths.py
                    `--us A|B`) and DIR/all.tsv (full index rows with header)
"""
import json
import os
import re
import subprocess
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))  # 12 Nov (Combat): under -I, 'import teamalias' needs the script dir
import time
import zipfile
import zlib

PLAT = "/data/zw4424/plat"
ST = "/data/zw4424/st"
OUT = os.path.join(ST, "gameindex.tsv")
CRC = os.path.join(ST, "gameindex.crc.tsv")
LOSSES = os.path.join(ST, "crit", "all_losses.tsv")
REG = os.path.join(PLAT, "downloads.tsv")
HERE = os.path.dirname(os.path.abspath(__file__))
FULL = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FULL_RE = re.compile(r"^" + FULL.pattern + r"$")
COLS = ["id", "path", "our_seat", "version", "foe", "map", "result", "lane", "created", "dup_key", "form", "foe_epoch", "margin", "end_round", "foe_id"]
OUTC = os.path.join(ST, "gameindex.outcome.tsv")


def load_outc():
    c = {}
    try:
        with open(OUTC) as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == 4:
                    c[p[0]] = p[1:]
    except OSError:
        pass
    return c


def outcome(path, key, cache, budget):
    """[end_round, submitted_a, submitted_b] of a replay (cached by dup_key), or None when not read (budget spent, a zip, a bad file)"""
    if key in cache:
        return cache[key]
    if key == "-" or budget[0] <= 0 or not path.endswith("replay.repl26a"):
        return None
    budget[0] -= 1
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import replay as R
        fin = R.decode_bytes(R._raw_replay(path), src=path).get("final") or {}
        sub = fin.get("submitted") or []
        v = [str(int(fin["round"])), str(int(sub[0])), str(int(sub[1]))]
    except (Exception, SystemExit):  # noqa: BLE001  a bad replay stays '?'
        v = ["?", "?", "?"]
    cache[key] = v
    return v
RESULTS = {"win", "loss", "draw"}


def created(mid):
    """UUIDv7: the first 48 bits are unix milliseconds."""
    try:
        ms = int(mid.replace("-", "")[:12], 16)
        if 1.7e12 < ms < 2.0e12:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))
    except ValueError:
        pass
    return "?"


def vnum(v):
    m = re.match(r"v(\d+)$", v or "")
    return int(m.group(1)) if m else -1


class Rec:
    __slots__ = ("seat", "version", "foe", "map", "result", "lane", "xs", "zips", "reg", "foe_id")

    def __init__(self):
        self.seat = self.version = self.foe = self.map = self.result = self.lane = self.foe_id = None
        self.xs, self.zips, self.reg = [], [], None

    def fill(self, **kw):
        for k, v in kw.items():
            if v in (None, "", "?", "-"):
                continue
            if k == "foe":  # 12 Nov: a renamed team keeps one name (teamalias: 'prism best fih' = 'stellar best girl')
                import teamalias
                v = teamalias.canonical(v)
            if getattr(self, k) is None:
                setattr(self, k, v)


def load_crc():
    c = {}
    try:
        with open(CRC) as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == 2:
                    c[p[0]] = p[1]
    except OSError:
        pass
    return c


def file_key(path, cache, used):
    st = os.stat(path)
    k = f"{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}"
    if k not in cache:
        crc = 0
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                crc = zlib.crc32(blk, crc)
        cache[k] = f"{st.st_size}:{crc & 0xffffffff:08x}"
    used[k] = cache[k]
    return cache[k]


def zip_key(path):
    try:
        with zipfile.ZipFile(path) as z:
            i = z.getinfo("replay.repl26a")
            return f"{i.file_size}:{i.CRC & 0xffffffff:08x}"
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def build(quiet=False):
    t0 = time.time()
    recs = {}

    def rec(mid):
        r = recs.get(mid)
        if r is None:
            r = recs[mid] = Rec()
        return r

    # 1. ladderclimb tables (the most specific lane)
    for d in sorted(os.listdir(ST)):
        if not d.startswith("climb"):
            continue
        lane = "top3" if d == "climb_top3" else "side" if d.startswith("climb_side") else "unranked" if d == "climb" else "other"
        try:
            f = open(os.path.join(ST, d, "games.tsv"))
        except OSError:
            continue
        with f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 7 and FULL_RE.match(p[3]):
                    rec(p[3]).fill(version=p[0], foe=p[1], map=p[4], seat=p[5].lower(), result=p[6].lower(), lane=lane,
                                   foe_id=p[8] if len(p) > 8 else None)
    # 2. plat sets: replays, zips, matches.txt
    for sd in sorted(os.listdir(PLAT)):
        d = os.path.join(PLAT, sd)
        if not os.path.isdir(d):
            continue
        lane = ("ranked" if sd.startswith("rk_") else "unranked" if sd.startswith("unr_") else
                "top3" if sd.startswith("top3_") else "side" if sd.startswith("sidewin_") else None)
        m = re.search(r"_(v\d+)$", sd)
        setv = m.group(1) if m else None
        mf = os.path.join(d, "matches.txt")
        if os.path.exists(mf):
            with open(mf) as f:
                for line in f:
                    p = line.split()
                    if len(p) >= 5 and FULL_RE.match(p[0]):
                        rec(p[0]).fill(map=p[1], seat=p[2].lower(), result=p[3].lower(), foe=" ".join(p[4:]).replace("_", " "),
                                       version=setv, lane=lane)
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            n = e.name
            if n.startswith("x_") and FULL_RE.match(n[2:]):
                rp = os.path.join(d, n, "replay.repl26a")
                if os.path.isfile(rp):
                    r = rec(n[2:])
                    r.xs.append(rp)
                    r.fill(version=setv, lane=lane)
            elif n.endswith(".zip") and FULL_RE.match(n[:-4]):
                r = rec(n[:-4])
                r.zips.append(e.path)
                r.fill(version=setv, lane=lane)
    # 3. all_losses.tsv
    try:
        with open(LOSSES) as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 6 and FULL_RE.match(p[0]):
                    ln = "side" if p[1].startswith("side") else p[1] if p[1] in ("top3", "ranked", "unranked") else None
                    rec(p[0]).fill(lane=ln, version=p[2], foe=p[3], map=p[4], seat=p[5].lower(), result="loss")
    except OSError:
        pass
    # 3b. critgame dirs: st/crit/<id>/meta.json (version, our seat; 'why' names a loss)
    cd = os.path.join(ST, "crit")
    for n in os.listdir(cd) if os.path.isdir(cd) else []:
        if FULL_RE.match(n) and n in recs:
            try:
                with open(os.path.join(cd, n, "meta.json")) as f:
                    mj = json.load(f)
            except (OSError, ValueError):
                continue
            why = str(mj.get("why", ""))
            recs[n].fill(version=mj.get("version"), seat=str(mj.get("us", "")).lower(),
                         result="loss" if re.search(r"\bloss\b|\blost\b", why) else None)
    # 4. the download register (copies outside plat, e.g. scout2)
    try:
        with open(REG) as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2 and p[0] in recs and recs[p[0]].reg is None:
                    recs[p[0]].reg = p[1]
                elif len(p) >= 2 and FULL_RE.match(p[0]) and p[1].endswith("replay.repl26a") and os.path.isfile(p[1]):
                    rec(p[0]).reg = p[1]
    except OSError:
        pass
    # 5. rows
    cache, used = load_crc(), {}
    outc, budget = load_outc(), [int(os.environ.get("GI_OUTCOME_MAX", "400"))]
    rows, nread = [], 0
    for mid in sorted(recs):
        r = recs[mid]
        if r.lane is None:
            r.lane = "critgame" if any("/crit_auto/" in p for p in r.xs + r.zips) else "other"
        path, form, key = "-", "missing", "-"
        xs = sorted(r.xs, key=lambda p: (not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(p)), "matches.txt")), p))
        if not xs and r.reg and r.reg.endswith("replay.repl26a") and os.path.isfile(r.reg):
            xs = [r.reg]
        if xs:
            path, form = xs[0], "replay"
            try:
                had = len(cache)
                key = file_key(path, cache, used)
                nread += len(cache) > had
            except OSError:
                key = "-"
        elif r.zips:
            path, form = sorted(r.zips)[0], "zip"
            key = zip_key(path) or "-"
        if r.seat not in ("a", "b") and xs:
            try:
                own = {f[5] for f in os.listdir(os.path.dirname(path)) if f.startswith("team-") and len(f) > 6}
                if len(own) == 1 and own <= {"a", "b"}:
                    r.seat = own.pop()
            except OSError:
                pass
        res = r.result if r.result in RESULTS else "?"
        oc = outcome(path, key, outc, budget) if form == "replay" else None
        mg = er = "?"
        if oc and oc[0] != "?":
            er = oc[0]
            if r.seat in ("a", "b"):
                mg = str((int(oc[1]) - int(oc[2])) * (1 if r.seat == "a" else -1))
        rows.append([mid, path, r.seat if r.seat in ("a", "b") else "?", r.version or "?", r.foe or "?", r.map or "?", res,
                     r.lane, created(mid), key, form, foe_epoch(r.foe, mid), mg, er, _fid(r)])
    tmp = f"{OUT}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("\t".join(COLS) + "\n")
        for row in rows:
            f.write("\t".join(x.replace("\t", " ") for x in row) + "\n")
    os.replace(tmp, OUT)
    tmp = f"{CRC}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        for k, v in used.items():
            f.write(f"{k}\t{v}\n")
    os.replace(tmp, CRC)
    tmp = f"{OUTC}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.writelines(f"{k}\t" + "\t".join(v) + "\n" for k, v in outc.items())
    os.replace(tmp, OUTC)
    if not quiet:
        forms, lanes = {}, {}
        for row in rows:
            forms[row[10]] = forms.get(row[10], 0) + 1
            lanes[row[7]] = lanes.get(row[7], 0) + 1
        dups = {}
        for row in rows:
            if row[9] != "-":
                dups[row[9]] = dups.get(row[9], 0) + 1
        nd = sum(v - 1 for v in dups.values() if v > 1)
        print(f"gameindex: {len(rows)} ids -> {OUT} in {time.time() - t0:.1f}s ({nread} replays hashed)")
        print("  form " + " ".join(f"{k} {v}" for k, v in sorted(forms.items())))
        print("  lane " + " ".join(f"{k} {v}" for k, v in sorted(lanes.items())))
        print(f"  {nd} ids are byte-identical re-plays of another id (dup_key)")


def _tid_of(name):
    try:
        import teamalias
        return teamalias.any_id(name)
    except Exception:  # noqa: BLE001
        return None


def _fid(r):
    """13 Nov (Coordinator: filters on team ids; SBG renames): the foe's teamId (games.tsv column 9, else teamalias.any_id(name)), '?' unknown."""
    if getattr(r, "foe_id", None):
        return r.foe_id
    try:
        import teamalias
        return teamalias.any_id(r.foe) or "?"
    except Exception:  # noqa: BLE001
        return "?"


def load_index():
    if not os.path.exists(OUT):
        sys.exit(f"gameindex: no {OUT}; run `python3 -I tools/lab/gameindex.py build`")
    idx = {}
    with open(OUT) as f:
        hdr = f.readline().rstrip("\n").split("\t")
        for line in f:
            p = line.rstrip("\n").split("\t")
            idx[p[0]] = dict(zip(hdr, p))
    return idx


def norm(s):
    import teamalias
    return teamalias.canonical(s.lower().replace("_", " ")).lower()


_FE = None


def foe_epoch(foe, mid):
    """12 Nov (Coordinator: Fish resubmitted): the foe's bot generation at this game, from tools/lab/foeepoch.py's windows in
    bq/foe_epochs.tsv (inferred from draft changes; the platform has no foe upload times): e0, e1, ... ('?' inside a change window;
    '-' when the foe has no window: one known generation)."""
    global _FE
    if not foe or foe == "?":
        return "?"
    if _FE is None:
        try:
            sys.path.insert(0, HERE)
            import foeepoch
            _FE = ({norm(k): v for k, v in foeepoch.load().items()}, foeepoch)
        except Exception:  # noqa: BLE001
            _FE = ({}, None)
    W, mod = _FE
    w = W.get(norm(foe))
    if not w or mod is None:
        return "-"
    try:
        return mod.label(w, mod.t_of(mid))
    except (ValueError, IndexError):
        return "?"


UNRANKED_OFF = "/data/zw4424/st/bq/UNRANKED_OFF"
UNRANKED_LANES = ("top3", "side", "unranked")  # our ladder-climb lanes and unranked groups (lane column above)


def kind_of(lane):
    """ranked | unranked | unknown, from the lane column (or all_losses' lane: 'top3...', 'side...', 'ranked...')"""
    lane = lane or ""
    if lane.startswith("ranked"):
        return "ranked"
    if lane.startswith(UNRANKED_LANES):
        return "unranked"
    return "unknown"


def lookup(args):
    ids, out, dedup, frm, foe, lane, fep = [], None, False, None, None, None, None
    foe_tid = None
    # 11 Nov (owner: "do not use our unranked games for now"; Coordinator: so analysts cannot mix lanes by accident): while
    # bq/UNRANKED_OFF exists, unranked games are dropped unless --include-unranked; --ranked-only also drops unknown-lane games
    incl_unr, ranked_only = "--include-unranked" in args, "--ranked-only" in args
    first = "--first" in args
    args = [x for x in args if x not in ("--include-unranked", "--ranked-only", "--first")]
    mode = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--file":
            with open(args[i + 1]) as f:
                ids += [ln.split()[0] for ln in f if ln.strip() and not ln.startswith("#")]
            i += 1
        elif a == "--out":
            out = args[i + 1]; i += 1
        elif a == "--from":
            frm = int(args[i + 1].lstrip("v")); i += 1
        elif a == "--foe":
            foe = norm(args[i + 1])
            try:  # 13 Nov: a label, id or any known name of a team matches all its names (by teamId)
                import teamalias
                foe_tid = teamalias.any_id(args[i + 1])
            except Exception:  # noqa: BLE001
                foe_tid = None
            i += 1
        elif a == "--lane":
            lane = args[i + 1]; i += 1
        elif a == "--foe-epoch":  # 12 Nov (Coordinator): eN, 'new' (each foe's latest epoch) or 'old' (before it); '?' games are dropped by new/old
            fep = args[i + 1]; i += 1
        elif a == "--dedup":
            dedup = True
        elif a in ("--critgame-open", "--losses"):
            mode = a
        elif a.startswith("-"):
            sys.exit(f"gameindex: unknown option {a}")
        else:
            ids.append(a)
        i += 1
    if mode == "--critgame-open":
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "critgame.py"), "status"], capture_output=True, text=True,
                           timeout=300)
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) >= 2 and p[0] == "OPEN" and FULL_RE.match(p[1]):
                ids.append(p[1])
    elif mode == "--losses":
        with open(LOSSES) as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) < 6 or not FULL_RE.match(p[0]):
                    continue
                if frm is not None and vnum(p[2]) < frm:
                    continue
                if foe and foe not in norm(p[3]) and not (foe_tid and _tid_of(p[3]) == foe_tid):
                    continue
                if lane and not p[1].startswith(lane):
                    continue
                ids.append(p[0])
    idx = load_index()
    # 12 Nov (Coordinator, the 01a1cbfb-3c35 collision): a short id resolves only when ONE indexed game starts with it; several -> the full
    # ids and the count, exit 2, unless --first (then the earliest-created match)
    out_ids = []
    for x in ids:
        if FULL_RE.match(x):
            out_ids.append(x)
            continue
        hits = sorted(k for k in idx if k.startswith(x))
        if not hits:
            sys.exit(f"gameindex: no indexed game starts with {x!r}")
        if len(hits) > 1 and not first:
            sys.stderr.write(f"gameindex: {x!r} matches {len(hits)} games (a prefix collision): give the full id, or --first\n")
            for k in hits[:20]:
                r = idx[k]
                sys.stderr.write(f"  {k}  {r.get('version', '?')}  {r.get('map', '?')}  {r.get('lane', '?')}  {r.get('created', '?')}\n")
            sys.exit(2)
        out_ids.append(hits[0])
    ids = out_ids
    seen, keys, rows = set(), set(), []
    for x in ids:
        if x in seen:
            continue
        seen.add(x)
        r = idx.get(x) or {c: "?" for c in COLS} | {"id": x, "path": "-", "form": "missing", "dup_key": "-",
                                                     "created": created(x)}
        if dedup and r["dup_key"] != "-":
            if r["dup_key"] in keys:
                continue
            keys.add(r["dup_key"])
        rows.append(r)
    if fep:
        last = {}
        for r in idx.values():
            e = r.get("foe_epoch", "-")
            if e.startswith("e"):
                last[norm(r.get("foe", "?"))] = max(last.get(norm(r.get("foe", "?")), 0), int(e[1:]))
        def fe_ok(r):
            e = r.get("foe_epoch") or foe_epoch(r.get("foe"), r["id"])
            if fep in ("new", "old"):
                if e == "-":
                    return fep == "new"  # one generation known: it is the current one
                if not e.startswith("e"):
                    return False
                top = last.get(norm(r.get("foe", "?")), 0)
                return (int(e[1:]) == top) == (fep == "new")
            return e == fep
        n1 = len(rows)
        rows = [r for r in rows if fe_ok(r)]
        print(f"gameindex: --foe-epoch {fep}: kept {len(rows)} of {n1}", file=sys.stderr)
    drop_unr = os.path.exists(UNRANKED_OFF) and not incl_unr
    n0 = len(rows)
    rows = [r for r in rows if not (drop_unr and kind_of(r["lane"]) == "unranked") and not (ranked_only and kind_of(r["lane"]) != "ranked")]
    if len(rows) < n0:
        print(f"gameindex: dropped {n0 - len(rows)} of {n0} games: " + ("unranked (owner 11 Nov: bq/UNRANKED_OFF; --include-unranked keeps them)"
              if drop_unr else "") + (" not ranked (--ranked-only)" if ranked_only else ""), file=sys.stderr)
    print("version\tid\tour_seat\tresult\tpath\tmap\tfoe\tlane", file=sys.stderr)
    for r in rows:
        print("\t".join(r[c] for c in ("version", "id", "our_seat", "result", "path", "map", "foe", "lane")))
    miss = sum(r["path"] == "-" for r in rows)
    print(f"gameindex: {len(rows)} ids, {miss} with no copy on disk, {sum(r['our_seat'] == '?' for r in rows)} seat unknown",
          file=sys.stderr)
    if out:
        os.makedirs(out, exist_ok=True)
        for s in ("a", "b"):
            with open(os.path.join(out, f"{s}.lst"), "w") as f:
                f.writelines(r["path"] + "\n" for r in rows if r["our_seat"] == s and r["path"] != "-")
        with open(os.path.join(out, "all.tsv"), "w") as f:
            f.write("\t".join(COLS) + "\n")
            f.writelines("\t".join(r.get(c, "?") for c in COLS) + "\n" for r in rows)
        print(f"gameindex: wrote {out}/a.lst b.lst all.tsv", file=sys.stderr)


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    if a[0] == "build":
        if "--if-older" in a:
            age = int(a[a.index("--if-older") + 1])
            try:
                if time.time() - os.path.getmtime(OUT) < age:
                    return
            except OSError:
                pass
        build(quiet="--quiet" in a)
    elif a[0] == "outcomes":  # 13 Nov: fill margin/end_round for every replay on disk (a build caps new decodes at GI_OUTCOME_MAX)
        os.environ["GI_OUTCOME_MAX"] = "1000000000"
        build(quiet="--quiet" in a)
    elif a[0] == "resolve":  # 10 Nov (Combat: a 13-char prefix matched 5 games; grep | head -1 picked the wrong one)
        if len(a) != 2:
            sys.exit("usage: gameindex.py resolve ID_PREFIX   -> the one full id, or exit 2 listing every match")
        idx = load_index()
        hits = sorted(k for k in idx if k.startswith(a[1]))
        if len(hits) == 1:
            print(hits[0])
        else:
            for k in hits[:20]:
                r = idx[k]
                print(f"{k}\t{r.get('version', '?')}\t{r.get('map', '?')}\t{r.get('foe', '?')}\t{r.get('our_seat', '?')}", file=sys.stderr)
            sys.exit(f"gameindex resolve: {len(hits)} games match {a[1]!r}; give more characters")
    elif a[0] == "lookup":
        lookup(a[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
