#!/usr/bin/env python3
"""Screen calibration: which LOCAL screen metric predicts the LIVE outcome of a ship? Read-only (no platform calls).

usage: python3 -I tools/lab/screencal.py report [--out DIR] [--boot N] [--from v252] [--to v999]
       python3 -I tools/lab/screencal.py pairlive A... -- B... [--kind all|unr|other] [--boot N]
       python3 -I tools/lab/screencal.py live [--kind all|unr|other]          per-version live table
  report   writes DIR/screencal.md (default /homes/USER/condor-work/reports/screencal) and DIR/steps.tsv; the game
           table goes to /data/USER/st/screencal/live_games.tsv (gems cache next to it).
  pairlive A and B are live set dirs (matches.txt "<id> <map> <a|b> <win|loss> <opp>", optional <id>.json) or version
           tags vNNN (that version's games from the live table below). Prints B minus A, opponent-paired.

STEPS. Live versions come from builder_queue.md's version table (bot dir per version) and the "## vNNN live <date>"
  lines of /data/USER/st/bq/unr_*.txt (when the platform showed the version live); never-live versions are skipped.
  A step is two consecutive live versions vN -> vM.

LOCAL METRICS (per step; new bot = vM, base = vN, by source hash through tools/lab/abindex.py: every abl.sh, sprt.py,
  heldout.sh and Condor screen game between the two sources is pooled; only complete map pairs count):
  h2h_<fam>   map-pair score of vM against vN minus 0.5 (abstat.py rows). fam: ALL (the standard screen maps: pool, patho,
              custom, fresh, genpatho, held-out; other generated families left out), pool (hand-made maps), ladder (pool maps
              that appear in the live games on disk), fresh (gen_s), genpatho (gen_p), heldout (gen_NN + gen_u/gen_up + gen_ux,
              the 102-map held-out line), share (h2h gem share of vM minus 0.5, ALL maps).
  nc_<fam>    paired D vs nova_spar_nochase2: per map, score(vM vs nochase2) - score(vN vs nochase2), mean over the maps both
              have complete; CI from pair_d.py's boot() (loaded from /data/USER/st/b86dg/py/pair_d.py without running it).
  otf         condab's "otf N maps ... score X" line of a /data/USER/st/bq/*.condor.txt whose header names exactly
              this step's two sources (on-the-fly maps; none existed before 29 Oct 18:00).

LIVE GAMES. Every match listing on disk (plat/*/meta/list*.json, plat/*/meta/g_*.json, st/bq/ranked*.json,
  st/bq/recent_matches.json: they carry createdAt, kind, groupId) plus every set dir plat/{rk,unr,lv,...}_vNNN/matches.txt
  (and the release sets wk2n_*). A listed game takes the version live at its createdAt (games created within 40 s
  before a version switch are dropped as ambiguous); an unlisted game takes its set's version tag. Kinds:
  ranked (listing), unr (our own unranked groups: groupId in unr_*.txt, unr_vNNN sets, or the 5-game block of an
  lv set holding a group's first match id), chal (unranked groups other teams started, listing), rk? (unlisted lv
  game outside our groups: ranked or a challenge), extra (other set dirs, e.g. skubap_v274), release (wk2n: v252's
  fixed-opponent release set). --kind other = ranked + chal + rk? + extra; unr = our groups only.
  gems: our and their tributed gems (sum of submittedGems by team) from <id>.json when present; share = us/(us+them).

OPPONENT-PAIRED LIVE DELTA (live_paired(games_a, games_b); live_paired_sets(tokens_a, tokens_b, kind) for set dirs or
  vNNN tags; CLI `pairlive`). Import: sys.path.insert(0, "/homes/USER/cambc/tools/lab"); import screencal. For A and B:
  pair on opponent name: common = opponents with >= 1 game against each. Per common opponent o: d_o = winrate_B(o) -
  winrate_A(o), weight w_o = min(n_A(o), n_B(o)); delta = sum w_o d_o / sum w_o. Same for gem share (games with a
  statistics file only). Unmatched raw delta = winrate_B - winrate_A over all games.
  SE (analytic): sqrt(sum w_o^2 p_o(1-p_o)(1/n_A(o) + 1/n_B(o))) / sum w_o with p_o = (wins_A + wins_B + 1) /
  (n_A + n_B + 2) (pooled, so a 5-0 cell still has variance). CI: two-stage bootstrap: resample common opponents
  with replacement (bootstrap unit 1), then games within each (opponent, version) cell (unit 2); 2.5/97.5 percentiles.
  Kinds are pooled inside an opponent cell unless --kind is given (the report shows all, unr and other separately).
FIXED-EFFECTS LIVE DELTA (secondary): ridge logistic regression over all live games of the report's versions,
  logit P(win) = theta_version + beta_opponent + kappa_kind + gamma_side, beta ~ N(0, 1); step delta =
  (theta_M - theta_N) x pbar(1 - pbar) (probability scale), SE from the inverse Hessian. It borrows opponent strength
  from every version, so it uses games against opponents the two versions do not share; it assumes opponents' bots
  did not change over the day.

CALIBRATION. For each local metric x and live delta y over the steps that have both: sign agreement k/n with a
  one-sided binomial p (H0: 50%), Spearman rho with a 95% bootstrap CI over steps, and the z of a 1/SE^2-weighted
  slope of y on x. Reliability of a series = 1 - mean(SE^2) / var(values) (0 = the step-to-step spread is all noise).
"""
import argparse
import ast
import collections
import glob
import json
import math
import os
import random
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abindex  # noqa: E402
import abstat  # noqa: E402

REPO = "/homes/USER/cambc"
PLAT = "/data/USER/plat"
BQ = "/data/USER/st/bq"
QUEUE = "/homes/USER/condor-work/reports/builder_queue.md"
OUT = "/homes/USER/condor-work/reports/screencal"
DATA = "/data/USER/st/screencal"
PAIR_D = "/data/USER/st/b86dg/py/pair_d.py"
NOCHASE = "nova_spar_nochase2"
US = "BattleCats"
LISTINGS = [PLAT + "/*/meta/list*.json", PLAT + "/*/meta/g_*.json", BQ + "/ranked*.json", BQ + "/recent_matches.json"]
SETS = [PLAT + "/*_v[0-9][0-9][0-9]", PLAT + "/wk2n_*"]
# versions the queue table cannot give: v252 ran the pre-trim nova_pzn_wk source; its live time is LR 17:36:09, v253's
# is "~20:36" in the table (no unrsets log for either).
HASH_OVERRIDE = {"v252": "72b2508e8aca"}
LIVE_FALLBACK = {"v252": "2026-10-28T17:36:09Z", "v253": "2026-10-28T20:36:00Z"}
AMBIG_S = 40
H2H_FAMS = ["ALL", "pool", "ladder", "fresh", "genpatho", "heldout"]
NC_FAMS = ["ALL", "pool", "fresh", "heldout"]


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def vnum(v):
    return int(v[1:])


# ------------------------------------------------------------------------------------------------ versions
def versions():
    """{vNNN: dict(bot, hash, live (epoch s), live_src)} for every version that went live, in order."""
    out = {}
    for line in open(QUEUE):
        m = re.match(r"\|\s*(v\d{3})\s*\|\s*([^|]*)\|\s*([^|]*)\|", line)
        if not m or "never live" in m.group(2):
            continue
        out[m.group(1)] = dict(bot=m.group(3).split()[0] if m.group(3).split() else None)
    live = {}
    for f in glob.glob(BQ + "/unr_*.txt"):
        for line in open(f, errors="replace"):
            m = re.match(r"## (v\d{3}) live (.+)$", line.strip())
            if m:
                live[m.group(1)] = (datetime.strptime(m.group(2), "%a %d %b %H:%M:%S UTC %Y")
                                    .replace(tzinfo=timezone.utc).timestamp(), os.path.basename(f))
    for v, d in out.items():
        if v in live:
            d["live"], d["live_src"] = live[v]
        elif v in LIVE_FALLBACK:
            d["live"], d["live_src"] = ts(LIVE_FALLBACK[v]), "fallback"
        d["hash"] = HASH_OVERRIDE.get(v) or (abindex.bot_hash(d["bot"]) if d["bot"] else None)
    return {v: out[v] for v in sorted(out, key=vnum) if "live" in out[v]}


def version_at(t, vers):
    """-> (version, ambiguous) for a game created at epoch t."""
    cur = None
    order = sorted(vers, key=lambda v: vers[v]["live"])
    for i, v in enumerate(order):
        if vers[v]["live"] <= t:
            cur = v
        else:
            return cur, (vers[v]["live"] - t) < AMBIG_S
    return cur, False


# ------------------------------------------------------------------------------------------------ live games
def our_groups():
    """{groupId: version} and {first matchId: (groupId, version)} of our unranked groups (unrsets logs)."""
    groups, first = {}, {}
    for f in glob.glob(BQ + "/unr_*.txt"):
        v, gid = None, None
        for line in open(f, errors="replace"):
            m = re.match(r"## unrsets (v\d{3}) ", line)
            if m:
                v = m.group(1)
            m = re.match(r"group ([0-9a-f-]{36}):", line)
            if m:
                gid = m.group(1)
                groups[gid] = v
            if line.startswith("{") and '"matchId"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                groups[d["groupId"]] = v
                first[d["matchId"]] = (d["groupId"], v)
    return groups, first


def read_listings():
    """{matchId: game} from every listing on disk."""
    out = {}
    for pat in LISTINGS:
        for f in sorted(glob.glob(pat)):
            try:
                d = json.load(open(f))
            except (ValueError, OSError):
                continue
            items = d if isinstance(d, list) else d.get("matches", []) if isinstance(d, dict) else []
            for x in items:
                if not isinstance(x, dict) or "createdAt" not in x:
                    continue
                teams = x.get("teams") or []
                us = [t for t in teams if t.get("name") == US]
                them = [t for t in teams if t.get("name") != US]
                if len(us) != 1 or len(them) != 1 or us[0].get("result") not in ("win", "loss"):
                    continue
                out[x["matchId"]] = dict(id=x["matchId"], created=ts(x["createdAt"]), lkind=x.get("kind"),
                                         group=x.get("groupId"), map=x.get("map"), side=us[0].get("side"),
                                         win=int(us[0]["result"] == "win"), opp=them[0].get("name"), src=os.path.relpath(f, "/data/USER"))
    return out


def read_set(d):
    """[(id, map, side, win, opp)] of a set dir's matches.txt."""
    rows = []
    p = os.path.join(d, "matches.txt")
    if not os.path.exists(p):
        return rows
    for line in open(p, errors="replace"):
        x = line.rstrip("\n").split(" ", 4)
        if len(x) == 5 and x[3] in ("win", "loss"):
            rows.append((x[0], x[1], x[2], int(x[3] == "win"), x[4]))
    return rows


def group_blocks(rows, first):
    """matchIds of an lv set that belong to one of our unranked groups: the 5-line same-opponent block holding a
    group's first match id (lv sets list each group as 5 consecutive lines)."""
    out = {}
    idx = {r[0]: i for i, r in enumerate(rows)}
    for mid, (gid, v) in first.items():
        i = idx.get(mid)
        if i is None:
            continue
        opp = rows[i][4]
        for lo in (i - 4, i):
            blk = rows[max(0, lo):lo + 5]
            if len(blk) == 5 and all(r[4] == opp for r in blk):
                for r in blk:
                    out[r[0]] = (gid, v)
                break
    return out


def lv_set(d, rows, games, first, vers, order, tag, notes):
    """File an lv set's unlisted games. lv sets list games newest first. A game's version is known when it is listed
    (createdAt), in a named set, or in one of our group blocks (created < 1 min after its version went live). An unknown
    game between two known ones of the same version takes it; between a group block of vN (newer) and a game of the
    version just before vN, it takes that older version; newer than every known game it takes the newest known
    version when the set was fetched before the next switch or the set is tagged with that version; anything else
    (older than every known game, or between two versions otherwise) is dropped as ambiguous."""
    name = os.path.basename(d)
    blocks = group_blocks(rows, first)
    known, isblock = [], []
    for r in rows:
        mid = r[0]
        if mid in games and not games[mid].get("pos"):
            known.append(games[mid]["ver"]); isblock.append(games[mid]["kind"] == "unr")
        elif mid in blocks and blocks[mid][1] in vers:
            known.append(blocks[mid][1]); isblock.append(True)
        else:
            known.append(None); isblock.append(False)
    mtime = os.path.getmtime(os.path.join(d, "matches.txt"))
    for i, (mid, mp, side, win, opp) in enumerate(rows):
        if mid in games:
            continue
        if mid in blocks and blocks[mid][1] in vers:
            games[mid] = dict(id=mid, ver=blocks[mid][1], kind="unr", map=mp, side=side, win=win, opp=opp,
                              created=None, src=name)
            continue
        nv = next(((known[j], isblock[j]) for j in range(i - 1, -1, -1) if known[j]), None)   # newer side
        ov = next((known[j] for j in range(i + 1, len(rows)) if known[j]), None)              # older side
        v = why = None
        if nv and ov and nv[0] == ov:
            v, why = ov, "bracketed"
        elif nv and ov and nv[1] and ov in order and order.index(nv[0]) == order.index(ov) + 1:
            v, why = ov, "before the next version's groups"
        elif ov and not nv:
            nxt = order[order.index(ov) + 1] if ov in order and order.index(ov) + 1 < len(order) else None
            if nxt is None or mtime < vers[nxt]["live"]:
                v, why = ov, "newest, fetched before the next switch"
            elif ov == tag:
                v, why = ov, "newest, set tag"
        if v is None:
            notes[f"{name}: unlisted game dropped (version ambiguous)"] += 1
            continue
        notes[f"{name}: unlisted game filed by position ({why})"] += 1
        games[mid] = dict(id=mid, ver=v, kind="rk?", map=mp, side=side, win=win, opp=opp, created=None, src=name,
                          pos=True)


def gems_of(path):
    d = json.load(open(path))
    tot = collections.Counter()
    for c in d.get("champions", []):
        try:
            tot[c.get("team")] += float((c.get("metrics") or {}).get("submittedGems", 0) or 0)
        except (TypeError, ValueError):
            continue
    return tot.get("teamA", 0), tot.get("teamB", 0)


def live_games(vers, gems=True, quiet=False):
    """The live game table: {matchId: dict(id, ver, kind, map, side, win, opp, created, src, gus, gthem)}."""
    groups, first = our_groups()
    listed = read_listings()
    games, notes = {}, collections.Counter()
    for mid, g in listed.items():
        v, amb = version_at(g["created"], vers)
        if v is None or amb:
            notes["listed game dropped (before v-table or within %d s of a switch)" % AMBIG_S] += 1
            continue
        kind = "ranked" if g["lkind"] == "ranked" else ("unr" if g["group"] in groups else
                                                       ("chal" if g["lkind"] == "unranked" else g["lkind"]))
        games[mid] = dict(g, ver=v, kind=kind)
    jpath = {}
    dirs = [d for pat in SETS for d in sorted(glob.glob(pat)) if os.path.isdir(d)]
    dirs.sort(key=lambda d: os.path.basename(d).startswith("lv_"))   # named sets first, then lv sets
    order = sorted(vers, key=lambda v: vers[v]["live"])
    for d in dirs:
        name = os.path.basename(d)
        m = re.search(r"_v(\d{3})$", name)
        sv = "v" + m.group(1) if m else ("v252" if name.startswith("wk2n") else None)
        pre = name.split("_")[0]
        rows = read_set(d)
        for r in rows:
            if os.path.exists(os.path.join(d, r[0] + ".json")):
                jpath.setdefault(r[0], os.path.join(d, r[0] + ".json"))
        if pre == "lv":
            lv_set(d, rows, games, first, vers, order, sv, notes)
            continue
        for mid, mp, side, win, opp in rows:
            if mid in games:
                if games[mid]["ver"] != sv and sv:
                    notes[f"{name}: game filed by its listing time under {games[mid]['ver']}"] += 1
                if pre in ("unr", "wk2n") and games[mid]["kind"] != "ranked":
                    games[mid]["kind"] = "unr" if pre == "unr" else "release"
                continue
            if sv not in vers:
                continue
            kind = {"rk": "ranked", "unr": "unr", "wk2n": "release"}.get(pre, "extra")
            games[mid] = dict(id=mid, ver=sv, kind=kind, map=mp, side=side, win=win, opp=opp, created=None, src=name)
    for mid, g in games.items():
        if mid not in jpath:
            for d in glob.glob(PLAT + "/*/%s.json" % mid)[:1]:
                jpath[mid] = d
    if gems:
        os.makedirs(DATA, exist_ok=True)
        cpath = os.path.join(DATA, "gems.json")
        cache = {}
        if os.path.exists(cpath):
            try:
                cache = json.load(open(cpath))
            except ValueError:
                cache = {}
        new = 0
        for mid, g in games.items():
            if mid not in cache and mid in jpath:
                try:
                    cache[mid] = gems_of(jpath[mid])
                    new += 1
                except (ValueError, OSError):
                    continue
        if new:
            with open(cpath + ".tmp", "w") as f:
                json.dump(cache, f)
            os.replace(cpath + ".tmp", cpath)
        for mid, g in games.items():
            if mid in cache:
                a, b = cache[mid]
                g["gus"], g["gthem"] = (a, b) if g["side"] == "a" else (b, a)
    if not quiet:
        for k, n in notes.items():
            print(f"note: {n} {k}", file=sys.stderr)
    return games, notes


KINDS = {"all": None, "unr": {"unr"}, "other": {"ranked", "chal", "rk?", "extra"}, "ranked": {"ranked"}}


def pick(games, ver=None, kind="all"):
    ks = KINDS[kind]
    return [g for g in games if (ver is None or g["ver"] == ver) and (ks is None or g["kind"] in ks)]


# ------------------------------------------------------------------------------------------------ paired live delta
def share(g):
    if "gus" not in g:
        return None
    t = g["gus"] + g["gthem"]
    return 0.5 if t == 0 else g["gus"] / t


def live_paired(games_a, games_b, boot=2000, seed=1):
    """Opponent-paired live delta, B minus A (see the module docstring).
    games_*: iterables of dicts with 'opp' and 'win' (0/1), optionally 'gus'/'gthem' (gems).
    -> dict(delta, se, lo, hi, n_common, n_a, n_b, raw, raw_se, gs_delta, gs_se, gs_n, rows=[(opp, nA, wrA, nB, wrB, w)])"""
    A, B = collections.defaultdict(list), collections.defaultdict(list)
    for g in games_a:
        A[g["opp"]].append(g)
    for g in games_b:
        B[g["opp"]].append(g)
    na, nb = sum(len(v) for v in A.values()), sum(len(v) for v in B.values())
    out = dict(n_a=na, n_b=nb, n_common=0, delta=None, se=None, lo=None, hi=None, rows=[], raw=None, raw_se=None,
               gs_delta=None, gs_se=None, gs_n=0, games_common=(0, 0))
    if na and nb:
        pa = sum(g["win"] for v in A.values() for g in v) / na
        pb = sum(g["win"] for v in B.values() for g in v) / nb
        out["raw"] = pb - pa
        pp = (pa * na + pb * nb + 1) / (na + nb + 2)
        out["raw_se"] = math.sqrt(pp * (1 - pp) * (1 / na + 1 / nb))
    common = sorted(set(A) & set(B))
    out["n_common"] = len(common)
    out["games_common"] = (sum(len(A[o]) for o in common), sum(len(B[o]) for o in common))
    if not common:
        return out

    def est(cells):
        sw = sum(w for _, _, w in cells)
        return sum(w * (sum(b) / len(b) - sum(a) / len(a)) for a, b, w in cells) / sw if sw else None

    cells = []
    var = 0.0
    for o in common:
        wa, wb = [g["win"] for g in A[o]], [g["win"] for g in B[o]]
        w = min(len(wa), len(wb))
        cells.append((wa, wb, w))
        p = (sum(wa) + sum(wb) + 1) / (len(wa) + len(wb) + 2)
        var += w * w * p * (1 - p) * (1 / len(wa) + 1 / len(wb))
        out["rows"].append((o, len(wa), sum(wa) / len(wa), len(wb), sum(wb) / len(wb), w))
    sw = sum(c[2] for c in cells)
    out["delta"] = est(cells)
    out["se"] = math.sqrt(var) / sw
    rng = random.Random(seed)
    bs = []
    for _ in range(boot):
        pick_ = [cells[rng.randrange(len(cells))] for _ in cells]
        bc = [([a[rng.randrange(len(a))] for _ in a], [b[rng.randrange(len(b))] for _ in b], w) for a, b, w in pick_]
        bs.append(est(bc))
    bs.sort()
    out["lo"], out["hi"] = bs[int(0.025 * boot)], bs[int(0.975 * boot) - 1]
    # gem share, same pairing, games with statistics only
    gcells, gvar = [], 0.0
    for o in common:
        sa = [s for s in map(share, A[o]) if s is not None]
        sb = [s for s in map(share, B[o]) if s is not None]
        if sa and sb:
            w = min(len(sa), len(sb))
            gcells.append((sa, sb, w))
            allv = sa + sb
            m = sum(allv) / len(allv)
            v = max(sum((x - m) ** 2 for x in allv) / max(1, len(allv) - 1), 0.01)
            gvar += w * w * v * (1 / len(sa) + 1 / len(sb))
    if gcells:
        sw = sum(c[2] for c in gcells)
        out["gs_delta"] = est(gcells)
        out["gs_se"] = math.sqrt(gvar) / sw
        out["gs_n"] = len(gcells)
    return out


def fe_deltas(games, vers):
    """Ridge logistic regression (see docstring) -> ({version: (theta, var)}, pbar, cov) ; None if numpy is missing."""
    try:
        import numpy as np
    except ImportError:
        return None
    vl = sorted({g["ver"] for g in games}, key=vnum)
    if len(vl) < 2:
        return None
    ref = max(vl, key=lambda v: sum(1 for g in games if g["ver"] == v))
    vcol = {v: i for i, v in enumerate([v for v in vl if v != ref])}
    opps = sorted({g["opp"] for g in games})
    ocol = {o: len(vcol) + i for i, o in enumerate(opps)}
    kinds = sorted({g["kind"] for g in games} - {"ranked"})
    kcol = {k: len(vcol) + len(opps) + i for i, k in enumerate(kinds)}
    p = len(vcol) + len(opps) + len(kinds) + 2  # + side b + intercept
    X = np.zeros((len(games), p))
    y = np.array([g["win"] for g in games], float)
    for r, g in enumerate(games):
        if g["ver"] in vcol:
            X[r, vcol[g["ver"]]] = 1
        X[r, ocol[g["opp"]]] = 1
        if g["kind"] in kcol:
            X[r, kcol[g["kind"]]] = 1
        X[r, p - 2] = g["side"] == "b"
        X[r, p - 1] = 1
    pen = np.zeros(p)
    pen[len(vcol):len(vcol) + len(opps)] = 1.0      # beta_opponent ~ N(0, 1)
    pen[:len(vcol)] = 1e-4
    pen[len(vcol) + len(opps):] = 1e-4
    b = np.zeros(p)
    for _ in range(50):
        mu = 1 / (1 + np.exp(-X @ b))
        g = X.T @ (y - mu) - pen * b
        H = (X * (mu * (1 - mu))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    cov = np.linalg.inv(H)
    pbar = float(y.mean())
    theta = {ref: (0.0, 0.0)}
    for v, i in vcol.items():
        theta[v] = (float(b[i]), float(cov[i, i]))
    return dict(theta=theta, pbar=pbar, cov=cov, vcol=vcol, ref=ref)


def fe_step(fe, a, b):
    if not fe or a not in fe["theta"] or b not in fe["theta"]:
        return None, None
    ia, ib = fe["vcol"].get(a), fe["vcol"].get(b)
    d = fe["theta"][b][0] - fe["theta"][a][0]
    var = fe["theta"][a][1] + fe["theta"][b][1]
    if ia is not None and ib is not None:
        var -= 2 * fe["cov"][ia, ib]
    k = fe["pbar"] * (1 - fe["pbar"])
    return d * k, math.sqrt(max(var, 0)) * k


# ------------------------------------------------------------------------------------------------ local metrics
def pair_d_funcs():
    """pair_d.py's imports and functions (scores, fam, boot) without running its command line (as condab.py does)."""
    tree = ast.parse(open(PAIR_D).read(), PAIR_D)
    tree.body = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
    ns = {"__name__": "pair_d"}
    exec(compile(tree, PAIR_D, "exec"), ns)
    return ns


def fam_of(name, fam, ladder):
    """our families for a map row -> set of labels."""
    out = set()
    if fam in ("pool", "patho", "custom", "fresh", "genpatho", "heldout", "unseen") or name.startswith("gen_ux"):
        out.add("ALL")
    if fam == "pool":
        out.add("pool")
        if name in ladder:
            out.add("ladder")
    if fam == "fresh":
        out.add("fresh")
    if fam == "genpatho":
        out.add("genpatho")
    if fam in ("heldout", "unseen") or name.startswith("gen_ux"):
        out.add("heldout")
    return out


def local_metrics(ix, hn, ho, hnc, ladder, pd):
    """{metric: (x, se, lo, hi, n)} for new source hn vs base ho (x: score - 0.5 or D)."""
    out = {}
    rows, _ = abindex.map_pairs(ix, hn, ho)
    by = collections.defaultdict(list)
    for r in rows:
        for f in fam_of(r[0], r[1], ladder):
            by[f].append(r)
    for f in H2H_FAMS:
        st = abstat.summarize(by[f], boot=200) if by[f] else None
        if st and st["n"] >= 10:
            out["h2h_" + f] = (st["score"] - 0.5, st["se"], st["lo"] - 0.5, st["hi"] - 0.5, st["n"])
            if f == "ALL":
                out["h2h_share"] = (st["share"] - 0.5, (st["share_hi"] - st["share_lo"]) / 3.92,
                                    st["share_lo"] - 0.5, st["share_hi"] - 0.5, st["n"])
    if hnc:
        rn, _ = abindex.map_pairs(ix, hn, hnc)
        ro, _ = abindex.map_pairs(ix, ho, hnc)
        sn, so = {r[0]: r for r in rn}, {r[0]: r for r in ro}
        byd = collections.defaultdict(list)
        for m in sorted(set(sn) & set(so)):
            for f in fam_of(m, sn[m][1], ladder):
                byd[f].append(sn[m][2] - so[m][2])
        for f in NC_FAMS:
            d = byd[f]
            if len(d) >= 10:
                mu, lo, hi = pd["boot"](d, 2000)
                out["nc_" + f] = (mu, (hi - lo) / 3.92, lo, hi, len(d))
    return out


def otf_metrics(hn, ho):
    """{step: (x, n)} from condab summaries whose header names exactly these two sources."""
    for f in glob.glob(BQ + "/*.condor.txt"):
        try:
            txt = open(f, errors="replace").read()
        except OSError:
            continue
        m = re.match(r"# condab \S+: \S+@([0-9a-f]{12}) vs \S+@([0-9a-f]{12})", txt)
        if not m or (m.group(1), m.group(2)) != (hn, ho):
            continue
        o = re.search(r"^otf (\d+) maps: .*?score ([0-9.]+)", txt, re.M)
        if o:
            return float(o.group(2)) - 0.5, int(o.group(1))
    return None


# ------------------------------------------------------------------------------------------------ statistics
def ranks(x):
    o = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def spearman(x, y):
    return pearson(ranks(x), ranks(y))


def binom_upper(k, n):
    """P(X >= k), X ~ Bin(n, 1/2)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else 1.0


def calibrate(xs, ys, ses, boot=2000, seed=3):
    n = len(xs)
    nz = [(a, b) for a, b in zip(xs, ys) if a != 0 and b != 0]
    k = sum(1 for a, b in nz if (a > 0) == (b > 0))
    rho = spearman(xs, ys)
    rng = random.Random(seed)
    bs = []
    for _ in range(boot):
        idx = [rng.randrange(n) for _ in range(n)]
        r = spearman([xs[i] for i in idx], [ys[i] for i in idx])
        if r is not None:
            bs.append(r)
    bs.sort()
    lo, hi = (bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs)) - 1]) if len(bs) > 20 else (None, None)
    w = [1 / max(s, 1e-3) ** 2 for s in ses]
    sw = sum(w)
    mx = sum(wi * a for wi, a in zip(w, xs)) / sw
    my = sum(wi * b for wi, b in zip(w, ys)) / sw
    sxx = sum(wi * (a - mx) ** 2 for wi, a in zip(w, xs))
    slope = sum(wi * (a - mx) * (b - my) for wi, a, b in zip(w, xs, ys)) / sxx if sxx > 0 else None
    z = slope / math.sqrt(1 / sxx) if slope is not None else None   # known-variance weights: se(slope) = 1/sqrt(Sxx)
    return dict(n=n, k=k, nn=len(nz), p=binom_upper(k, len(nz)), rho=rho, lo=lo, hi=hi, slope=slope, z=z)


def reliability(vals, ses):
    if len(vals) < 3:
        return None
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return 1 - (sum(s * s for s in ses) / len(ses)) / var if var > 0 else None


# ------------------------------------------------------------------------------------------------ report
def f3(x, sign=True):
    return "-" if x is None else (f"{x:+.3f}" if sign else f"{x:.3f}")


def levels(vers, steps, ix, hnc, fe, G):
    """Version LEVELS instead of step differences (adjacent step deltas share a version, so their live noise is
    anti-correlated, and one step's signal is tiny). Per version: nc = map-pair score vs nochase2 on the maps every
    version with 300+ such maps has; cum = running sum of h2h ALL over the longest unbroken chain of steps; live = FE
    theta (probability scale, relative to the FE reference version) and the raw win rate."""
    out = {v: {} for v in vers}
    sc = {}
    for v, d in vers.items():
        if d["hash"] and hnc:
            rows, _ = abindex.map_pairs(ix, d["hash"], hnc)
            if len(rows) >= 300:
                sc[v] = {r[0]: r[2] for r in rows}
    common = set.intersection(*[set(x) for x in sc.values()]) if sc else set()
    for v in sc:
        x = [sc[v][m] for m in common]
        if len(x) > 1:
            mu = sum(x) / len(x)
            out[v]["nc"] = (mu, math.sqrt(sum((a - mu) ** 2 for a in x) / (len(x) - 1) / len(x)), len(x))
    chains, cur = [], None
    for s in steps:
        x = s["loc"].get("h2h_ALL")
        if x is None:
            cur = None
            continue
        if cur is None:
            cur = [(s["a"], 0.0, 0.0)]
            chains.append(cur)
        v0, c0, var0 = cur[-1]
        cur.append((s["b"], c0 + x[0], var0 + x[1] ** 2))
    if chains:
        for v, c, var in max(chains, key=len):
            out[v]["cum"] = (c, math.sqrt(var))
    k = fe["pbar"] * (1 - fe["pbar"]) if fe else None
    for v in vers:
        if fe and v in fe["theta"]:
            th, var = fe["theta"][v]
            out[v]["fe"] = (th * k, math.sqrt(var) * k)
        x = [g["win"] for g in G if g["ver"] == v and g["kind"] != "release"]
        if x:
            out[v]["wr"] = (sum(x) / len(x), len(x))
    cal = {}
    for m in ("nc", "cum"):
        vs = [v for v in vers if m in out[v] and "fe" in out[v]]
        if len(vs) >= 4:
            ses = [out[v]["fe"][1] for v in vs]
            medse = sorted(s for s in ses if s > 0)[len(ses) // 2] if any(s > 0 for s in ses) else 0.1
            cal[m] = calibrate([out[v][m][0] for v in vs], [out[v]["fe"][0] for v in vs],
                               [s if s > 0 else medse for s in ses])
            cal[m]["versions"] = vs
    return out, cal, len(common)


def report(args):
    vers = versions()
    vers = {v: d for v, d in vers.items() if vnum(args.vfrom) <= vnum(v) <= vnum(args.vto)}
    vl = list(vers)
    games, notes = live_games(vers)
    G = list(games.values())
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "live_games.tsv"), "w") as f:
        f.write("matchId\tversion\tkind\tmap\tside\twin\topponent\tgems_us\tgems_them\tsource\n")
        for g in sorted(G, key=lambda g: (vnum(g["ver"]), g["kind"], g["opp"])):
            f.write("\t".join(str(x) for x in (g["id"], g["ver"], g["kind"], g["map"], g["side"], g["win"], g["opp"],
                                               g.get("gus", ""), g.get("gthem", ""), g["src"])) + "\n")
    ladder = {g["map"] for g in G}
    hashes = {d["hash"] for d in vers.values() if d["hash"]}
    hnc = abindex.bot_hash(NOCHASE)
    ix = abindex.Index(hashes | ({hnc} if hnc else set()))
    pd = pair_d_funcs()
    fe = fe_deltas([g for g in G if g["kind"] != "release"], vers)
    steps = []
    for a, b in zip(vl, vl[1:]):
        ha, hb = vers[a]["hash"], vers[b]["hash"]
        loc = local_metrics(ix, hb, ha, hnc, ladder, pd) if ha and hb else {}
        otf = otf_metrics(hb, ha) if ha and hb else None
        if otf:
            loc["otf"] = (otf[0], 0.5 / math.sqrt(otf[1]), None, None, otf[1])
        live = {k: live_paired(pick(G, a, k), pick(G, b, k), boot=args.boot) for k in ("all", "unr", "other")}
        fd, fse = fe_step(fe, a, b)
        steps.append(dict(a=a, b=b, bot=vers[b]["bot"], loc=loc, live=live, fe=(fd, fse)))
    metrics = ["h2h_" + f for f in H2H_FAMS] + ["h2h_share"] + ["nc_" + f for f in NC_FAMS] + ["otf"]
    targets = [("paired", lambda s: (s["live"]["all"]["delta"], s["live"]["all"]["se"])),
               ("paired_unr", lambda s: (s["live"]["unr"]["delta"], s["live"]["unr"]["se"])),
               ("fe", lambda s: s["fe"]),
               ("gemshare", lambda s: (s["live"]["all"]["gs_delta"], s["live"]["all"]["gs_se"]))]
    cal = {}
    for m in metrics:
        for tn, tf in targets:
            xs, ys, ses = [], [], []
            for s in steps:
                if m in s["loc"]:
                    y, se = tf(s)
                    if y is not None and se:
                        xs.append(s["loc"][m][0]); ys.append(y); ses.append(se)
            cal[m, tn] = calibrate(xs, ys, ses) if len(xs) >= 4 else dict(n=len(xs))
    lev = levels(vers, steps, ix, hnc, fe, G)
    os.makedirs(args.out, exist_ok=True)
    write_tsv(os.path.join(args.out, "steps.tsv"), steps, metrics)
    write_md(os.path.join(args.out, "screencal.md"), args, vers, G, notes, steps, metrics, targets, cal, fe, lev)
    print(f"wrote {args.out}/screencal.md, {args.out}/steps.tsv, {DATA}/live_games.tsv")


def write_tsv(path, steps, metrics):
    cols = ["step", "bot"]
    for m in metrics:
        cols += [m, m + "_se", m + "_n"]
    for k in ("all", "unr", "other"):
        cols += [f"live_{k}_delta", f"live_{k}_se", f"live_{k}_lo", f"live_{k}_hi", f"live_{k}_opps",
                 f"live_{k}_nA", f"live_{k}_nB", f"live_{k}_raw", f"live_{k}_raw_se"]
    cols += ["gemshare_delta", "gemshare_se", "fe_delta", "fe_se"]
    with open(path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for s in steps:
            row = [f"{s['a']}->{s['b']}", s["bot"] or ""]
            for m in metrics:
                v = s["loc"].get(m)
                row += [f"{v[0]:.4f}", f"{v[1]:.4f}", str(v[4])] if v else ["", "", ""]
            for k in ("all", "unr", "other"):
                L = s["live"][k]
                row += ["" if L[x] is None else f"{L[x]:.4f}" for x in ("delta", "se", "lo", "hi")]
                row += [str(L["n_common"]), str(L["n_a"]), str(L["n_b"])]
                row += ["" if L[x] is None else f"{L[x]:.4f}" for x in ("raw", "raw_se")]
            L = s["live"]["all"]
            row += ["" if L[x] is None else f"{L[x]:.4f}" for x in ("gs_delta", "gs_se")]
            row += ["" if x is None else f"{x:.4f}" for x in s["fe"]]
            f.write("\t".join(row) + "\n")


def write_md(path, args, vers, G, notes, steps, metrics, targets, cal, fe, lev):
    L = []
    w = L.append
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    w(f"# Screen calibration: local screen metrics vs live outcome per ship ({now})")
    w("")
    w(f"Tool: `python3 -I tools/lab/screencal.py report` (method in its docstring). Versions {vl_str(vers)}. "
      f"Per-step table: steps.tsv; game table: {DATA}/live_games.tsv.")
    w("")
    w("## Live data per version")
    w("")
    w("| version | bot | live from (UTC) | ranked | unr (ours) | chal | rk? | extra | release | with gems |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for v, d in vers.items():
        c = collections.Counter(g["kind"] for g in G if g["ver"] == v)
        ng = sum(1 for g in G if g["ver"] == v and "gus" in g)
        w(f"| {v} | {d['bot']} | {datetime.fromtimestamp(d['live'], timezone.utc).strftime('%d %H:%M:%S')}"
          f"{' (approx)' if d.get('live_src') == 'fallback' else ''} | {c['ranked']} | {c['unr']} | {c['chal']} | "
          f"{c['rk?']} | {c['extra']} | {c['release']} | {ng} |")
    for k, n in notes.items():
        w(f"- note: {n} {k}")
    w("")
    w("## Per step: local metrics (new minus base) and live delta")
    w("")
    w("h2h = map-pair score - 0.5 [n maps]; nc = paired D vs nochase2; live = opponent-paired win-rate delta, all kinds "
      "pooled inside an opponent (SE analytic, CI two-stage bootstrap), opps = common opponents, games A/B; "
      "unr/other = the same on our unranked groups / the rest; raw = unmatched; gems = paired gem-share delta; "
      "FE = fixed-effects logit delta.")
    w("")
    w("| step | h2h ALL | pool | ladder | fresh | genpatho | heldout | nc ALL | nc fresh | nc heldout | live paired (SE) [CI] | opps | games A/B | unr | other | raw | gems | FE |")
    w("|---|" + "---|" * 17)
    for s in steps:
        lo = s["loc"]

        def c(m):
            v = lo.get(m)
            return f"{v[0]:+.3f} [{v[4]}]" if v else "-"
        La, Lu, Lo = s["live"]["all"], s["live"]["unr"], s["live"]["other"]
        lv = (f"{La['delta']:+.3f} ({La['se']:.3f}) [{La['lo']:+.2f}, {La['hi']:+.2f}]" if La["delta"] is not None else "-")
        w(f"| {s['a']}->{s['b']} | {c('h2h_ALL')} | {c('h2h_pool')} | {c('h2h_ladder')} | {c('h2h_fresh')} | "
          f"{c('h2h_genpatho')} | {c('h2h_heldout')} | {c('nc_ALL')} | {c('nc_fresh')} | {c('nc_heldout')} | {lv} | "
          f"{La['n_common']} | {La['games_common'][0]}/{La['games_common'][1]} | "
          f"{pm(Lu['delta'], Lu['se'])} | {pm(Lo['delta'], Lo['se'])} | {pm(La['raw'], La['raw_se'])} | "
          f"{pm(La['gs_delta'], La['gs_se'])} | {pm(*s['fe'])} |")
    w("")
    # per-step live SE and significance
    ok = [s for s in steps if s["live"]["all"]["delta"] is not None]
    sig = [s for s in ok if abs(s["live"]["all"]["delta"]) > 2 * s["live"]["all"]["se"]]
    fes = [s for s in steps if s["fe"][0] is not None]
    fsig = [s for s in fes if abs(s["fe"][0]) > 2 * s["fe"][1]]
    ses = sorted(s["live"]["all"]["se"] for s in ok)
    fses = sorted(s["fe"][1] for s in fes)
    w("## Live SE per step")
    w("")
    w(f"- Opponent-paired (all kinds): {len(ok)} of {len(steps)} steps have a common opponent; SE median "
      f"{med(ses):.3f} (range {ses[0]:.3f} to {ses[-1]:.3f}); |delta| > 2 SE on {len(sig)} step(s)"
      + (": " + ", ".join(f"{s['a']}->{s['b']} {s['live']['all']['delta']:+.3f}" for s in sig) if sig else "") + "."
      if ok else "- no step has a common opponent.")
    if fes:
        w(f"- Fixed-effects: SE median {med(fses):.3f} (range {fses[0]:.3f} to {fses[-1]:.3f}); |delta| > 2 SE on "
          f"{len(fsig)} step(s)" + (": " + ", ".join(f"{s['a']}->{s['b']} {s['fe'][0]:+.3f}" for s in fsig) if fsig else "") + ".")
    miss_loc = [f"{s['a']}->{s['b']}" for s in steps if "h2h_ALL" not in s["loc"]]
    miss_nc = [f"{s['a']}->{s['b']}" for s in steps if "nc_ALL" not in s["loc"]]
    miss_live = [f"{s['a']}->{s['b']}" for s in steps if s["live"]["all"]["delta"] is None]
    w(f"- Missing local h2h (no complete map pair between the two sources in the index): {', '.join(miss_loc) or 'none'}.")
    w(f"- Missing nochase2 D (one side never played nochase2 on 10+ common maps): {', '.join(miss_nc) or 'none'}.")
    w(f"- Missing live paired delta (no common opponent): {', '.join(miss_live) or 'none'}.")
    w("")
    w("## Calibration: does the local metric predict the live delta?")
    w("")
    w("Per metric and live target: steps n, sign agreement k/n' (n' = both non-zero) with one-sided binomial p, "
      "Spearman rho [95% bootstrap CI over steps], z of the 1/SE^2-weighted slope of live on local.")
    w("")
    w("| metric | reliability | " + " | ".join(tn for tn, _ in targets) + " |")
    w("|---|---|" + "---|" * len(targets))
    rel = {}
    for m in metrics:
        vals = [s["loc"][m][0] for s in steps if m in s["loc"]]
        sse = [s["loc"][m][1] for s in steps if m in s["loc"]]
        rel[m] = reliability(vals, sse)
        cells = []
        for tn, _ in targets:
            c = cal[m, tn]
            if c.get("rho") is None and c.get("k") is None:
                cells.append(f"n {c['n']}")
            else:
                cells.append(f"n {c['n']}: {c['k']}/{c['nn']} p {c['p']:.2f}; rho {f3(c['rho'])} "
                             f"[{f3(c['lo'])}, {f3(c['hi'])}]; z {f3(c['z'])}")
        w(f"| {m} | {f3(rel[m], False) if rel[m] is not None else '-'} (n {len(vals)}) | " + " | ".join(cells) + " |")
    w("")
    best = sorted(((cal[m, "paired"].get("rho"), m) for m in metrics if cal[m, "paired"].get("rho") is not None),
                  reverse=True)
    w("Ranked by Spearman rho against the paired live delta: " + ", ".join(f"{m} {r:+.2f}" for r, m in best) + ".")
    anysig = [(m, tn) for (m, tn), c in cal.items() if c.get("p") is not None and c["p"] < 0.05]
    w(f"Sign tests with p < 0.05 (of {sum(1 for c in cal.values() if c.get('p') is not None)} run, no multiplicity "
      f"correction): {', '.join(f'{m} vs {tn}' for m, tn in anysig) or 'none'}.")
    ps = sorted((c["p"], m, tn) for (m, tn), c in cal.items() if c.get("p") is not None)
    nm = len({m for _, m, _ in ps})
    if ps:
        w(f"Smallest sign-test p: {ps[0][0]:.3f} ({ps[0][1]} vs {ps[0][2]}); Bonferroni bar over {nm} metrics x "
          f"{len(targets)} targets = {0.05 / max(1, len(ps)):.4f}: "
          + ("passed" if ps[0][0] < 0.05 / len(ps) else "no metric passes") + ".")
    w("")
    w("Legs NOT predictive in this data (each with its reason; no leg is shown predictive: see the Bonferroni line):")
    for m in metrics:
        why = []
        cp, cf = cal[m, "paired"], cal[m, "fe"]
        if cp.get("n", 0) < 6:
            why.append(f"only {cp.get('n', 0)} steps with local and live data")
        if rel.get(m) is not None and rel[m] <= 0.10:
            why.append(f"local step reliability {rel[m]:.2f}: its step-to-step spread is noise even locally")
        if cp.get("rho") is not None and cf.get("rho") is not None and cp["rho"] <= 0 and cf["rho"] <= 0:
            why.append(f"rho <= 0 against both live targets (paired {cp['rho']:+.2f}, FE {cf['rho']:+.2f})")
        if why:
            w(f"- {m}: " + "; ".join(why) + ".")
    w("")
    out, lcal, ncommon = lev
    w("## Version levels (no differencing): local level vs live FE level")
    w("")
    w(f"nc = map-pair score vs nochase2 on the {ncommon} maps every such version has; cum = running sum of h2h ALL "
      f"along the longest unbroken chain of steps; FE = fixed-effects live level (probability scale, relative to the "
      f"reference version {fe['ref'] if fe else '-'}); wr = raw live win rate (n games, release set excluded).")
    w("")
    w("| version | nc level | cum h2h | FE live | wr (n) |")
    w("|---|---|---|---|---|")
    for v in vers:
        o = out[v]
        wr = f"{o['wr'][0]:.3f} ({o['wr'][1]})" if "wr" in o else "-"
        w(f"| {v} | {pm(*o['nc'][:2]) if 'nc' in o else '-'} | {pm(*o['cum']) if 'cum' in o else '-'} | "
          f"{pm(*o['fe']) if 'fe' in o else '-'} | {wr} |")
    w("")
    both = [v for v in vers if "nc" in out[v] and "cum" in out[v]]
    if len(both) >= 2:
        a, b = both[0], both[-1]
        dn = out[b]["nc"][0] - out[a]["nc"][0]
        dc = out[b]["cum"][0] - out[a]["cum"][0]
        sdn = math.hypot(out[b]["nc"][1], out[a]["nc"][1])
        sdc = math.sqrt(max(out[b]["cum"][1] ** 2 - out[a]["cum"][1] ** 2, 0))
        w(f"- Transfer {a} -> {b}: summed h2h steps {dc:+.3f} +-{sdc:.3f}, measured against nochase2 {dn:+.3f} "
          f"+-{sdn:.3f} (ratio {dn / dc if dc else float('nan'):.2f}): step h2h scores overstate the gain a third "
          f"party sees (shipped steps were also selected on h2h, a winner's curse).")
    for m, lab in (("nc", "nc level"), ("cum", "cum h2h")):
        c = lcal.get(m)
        if c and c.get("rho") is not None:
            w(f"- {lab} vs FE live level over {c['n']} versions: rho {c['rho']:+.3f} [{f3(c['lo'])}, {f3(c['hi'])}], "
              f"weighted slope {f3(c['slope'])} (z {f3(c['z'])}); sign agreement is not meaningful for levels.")
    w("")
    w("## Power")
    w("")
    hv = [s["loc"]["h2h_ALL"][0] for s in steps if "h2h_ALL" in s["loc"]]
    hs = [s["loc"]["h2h_ALL"][1] for s in steps if "h2h_ALL" in s["loc"]]
    if len(hv) >= 3 and ses:
        sd_obs = math.sqrt(sum((v - sum(hv) / len(hv)) ** 2 for v in hv) / (len(hv) - 1))
        sd_true = math.sqrt(max(sd_obs ** 2 - sum(x * x for x in hs) / len(hs), 1e-6))
        se_live = med(ses)
        rel_live = sd_true ** 2 / (sd_true ** 2 + se_live ** 2)
        rl = rel.get("h2h_ALL") or 0
        rho_max = math.sqrt(max(rl, 0) * rel_live)
        k80 = ((1.96 + 0.84) / math.atanh(rho_max)) ** 2 + 3 if rho_max > 0 else float("inf")
        n_needed = 2 * 0.25 / sd_true ** 2
        gpo = [s["live"]["all"]["games_common"] for s in ok]
        w(f"- Spread of the true step effect, estimated from h2h ALL: sd of the step values {sd_obs:.4f}, minus their "
          f"own noise (mean SE {sum(hs) / len(hs):.4f}) -> sd_true ~ {sd_true:.4f} (map-pair score units; assumes a "
          f"1:1 transfer to live win rate, an optimistic assumption).")
        w(f"- Live: median paired SE {se_live:.3f} from a median of {med([min(a, b) for a, b in gpo]):.0f} matched games "
          f"a side -> reliability of a live step delta {rel_live:.4f}; with h2h ALL reliability {rl:.2f}, the largest "
          f"observable rank correlation for a PERFECT local predictor is ~{rho_max:.3f}.")
        w(f"- Steps needed to see that correlation (80% power, 2-sided 5%): ~{k80:,.0f}. Matched live games needed per "
          f"version for a live reliability of 0.5 (SE = sd_true): ~{n_needed:,.0f} a side (ranked play gives ~30 an hour).")
        mstep = sum(hv) / len(hv)
        w(f"- To tell the mean shipped step (h2h ALL {mstep:+.3f}) from 0 at 2 SE live: ~{2 / mstep ** 2:,.0f} matched "
          f"games a side (SE = sqrt(0.5 / n)).")
    lv_nc = [(out[v]["nc"], out[v]["fe"]) for v in vers if "nc" in out[v] and "fe" in out[v]]
    if len(lv_nc) >= 4:
        xs = [a[0] for a, _ in lv_nc]
        mu = sum(xs) / len(xs)
        var_obs = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
        var_true = max(var_obs - sum(a[1] ** 2 for a, _ in lv_nc) / len(lv_nc), 1e-6)
        fse = med([b[1] for _, b in lv_nc if b[1] > 0])
        rel_nc, rel_lv = var_true / var_obs, var_true / (var_true + fse ** 2)
        rho_e = math.sqrt(rel_nc * rel_lv)
        k80 = ((1.96 + 0.84) / math.atanh(rho_e)) ** 2 + 3
        n_fe = med([out[v]["wr"][1] for v in vers if "nc" in out[v] and "wr" in out[v]])
        se08 = math.sqrt(var_true * (1 - 0.8) / 0.8)
        w(f"- Levels (nc vs FE live): sd of the nc levels {math.sqrt(var_obs):.3f} (true ~{math.sqrt(var_true):.3f}), "
          f"median FE SE {fse:.3f} at a median {n_fe:.0f} games a version -> with a 1:1 transfer the expected rho is "
          f"~{rho_e:.2f}; {k80:.0f} versions give 80% power to see it (we have {len(lv_nc)}). A live level SE of "
          f"{se08:.3f} (reliability 0.8) needs ~{n_fe * (fse / se08) ** 2:,.0f} games a version.")
    w("")
    nul = [s for s in steps if s["a"] == "v252" and s["b"] == "v253"]
    if nul:
        s = nul[0]
        w(f"- Null step v252->v253 (trim + UB fix, 247/248 local games identical): live paired "
          f"{pm(s['live']['all']['delta'], s['live']['all']['se'])} ({s['live']['all']['n_common']} common opponents), "
          f"FE {pm(*s['fe'])}" + (": no live null calibration is possible (v252 has only its release set, v253 only "
                                   "ranked games)." if s["live"]["all"]["delta"] is None else "."))
    w("- Caveats: adjacent step deltas share a version, so their live noise is anti-correlated (the step bootstrap "
      "ignores this); opponents resubmit during the day (FE assumes fixed opponents); shipped steps were selected on "
      "the local legs (truncated spread, winner's curse); lv-set games without a listing are filed by position "
      "(notes above).")
    w("")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


def vl_str(vers):
    v = list(vers)
    return f"{v[0]}..{v[-1]} ({len(v)} live versions)" if v else "none"


def med(x):
    x = sorted(x)
    return x[len(x) // 2] if len(x) % 2 else (x[len(x) // 2 - 1] + x[len(x) // 2]) / 2 if x else float("nan")


def pm(d, se):
    return "-" if d is None else f"{d:+.3f}+-{se:.3f}"


# ------------------------------------------------------------------------------------------------ CLI modes
def resolve_side(tokens, G, kind):
    out = []
    for t in tokens:
        if re.fullmatch(r"v\d{3}", t):
            out += pick(G, t, kind)
        elif os.path.isdir(t):
            name = os.path.basename(os.path.normpath(t))
            for mid, mp, side, win, opp in read_set(t):
                g = dict(id=mid, ver=name, kind="set", map=mp, side=side, win=win, opp=opp)
                p = os.path.join(t, mid + ".json")
                if os.path.exists(p):
                    try:
                        a, b = gems_of(p)
                        g["gus"], g["gthem"] = (a, b) if side == "a" else (b, a)
                    except (ValueError, OSError):
                        pass
                out.append(g)
        else:
            sys.exit(f"pairlive: {t} is neither a set dir nor a version tag vNNN")
    seen, uniq = set(), []
    for g in out:
        if g["id"] not in seen:
            seen.add(g["id"])
            uniq.append(g)
    return uniq


def live_paired_sets(a, b, kind="all", boot=2000):
    """live_paired() on two lists of live set dirs and/or version tags vNNN (the rollback rule's entry point):
    live_paired_sets(["/data/USER/plat/lv_v275"], ["v276"]) -> the live_paired() dict, B minus A."""
    G = []
    if any(re.fullmatch(r"v\d{3}", t) for t in list(a) + list(b)):
        G = list(live_games(versions(), gems=True, quiet=True)[0].values())
    return live_paired(resolve_side(a, G, kind), resolve_side(b, G, kind), boot=boot)


def pairlive(argv):
    if "--" not in argv:
        sys.exit("usage: screencal.py pairlive A... -- B... [--kind all|unr|other] [--boot N]")
    kind, boot = "all", 2000
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--kind":
            kind = argv[i + 1]; i += 2
        elif argv[i] == "--boot":
            boot = int(argv[i + 1]); i += 2
        else:
            rest.append(argv[i]); i += 1
    k = rest.index("--")
    ta, tb = rest[:k], rest[k + 1:]
    r = live_paired_sets(ta, tb, kind, boot)
    print(f"A = {' '.join(ta)} ({r['n_a']} games), B = {' '.join(tb)} ({r['n_b']} games), kind {kind}")
    print(f"common opponents {r['n_common']} ({r['games_common'][0]} / {r['games_common'][1]} games)")
    if r["delta"] is not None:
        print(f"paired win-rate delta B-A {r['delta']:+.3f}  SE {r['se']:.3f}  95% bootstrap CI [{r['lo']:+.3f}, {r['hi']:+.3f}]")
    else:
        print("paired win-rate delta: no common opponent")
    if r["gs_delta"] is not None:
        print(f"paired gem-share delta B-A {r['gs_delta']:+.3f}  SE {r['gs_se']:.3f}  ({r['gs_n']} opponents with statistics)")
    if r["raw"] is not None:
        print(f"unmatched win-rate delta B-A {r['raw']:+.3f}  SE {r['raw_se']:.3f}")
    for o, na, wa, nb, wb, wt in sorted(r["rows"], key=lambda x: -x[5]):
        print(f"  {o[:32]:32s} A {wa:.2f} ({na})  B {wb:.2f} ({nb})  w {wt}")


def live_table(argv):
    kind = argv[argv.index("--kind") + 1] if "--kind" in argv else "all"
    vers = versions()
    games, _ = live_games(vers, gems=False)
    G = pick(list(games.values()), None, kind)
    print("version  games  wins  winrate  opponents")
    for v in vers:
        x = [g for g in G if g["ver"] == v]
        if x:
            print(f"{v}  {len(x):5d}  {sum(g['win'] for g in x):4d}  {sum(g['win'] for g in x) / len(x):.3f}  "
                  f"{len({g['opp'] for g in x})}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "pairlive":
        return pairlive(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        return live_table(sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["report"])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--from", dest="vfrom", default="v252")
    ap.add_argument("--to", dest="vto", default="v999")
    report(ap.parse_args())


if __name__ == "__main__":
    main()
