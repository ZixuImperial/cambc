#!/usr/bin/env python3
"""teams: the one table of opponent team ids, and name -> teamId resolution from the ladder. Tool builder, 4 Nov (owner via the
Builder: "top teams are identified by platform teamId, because team names change often").

usage: python3 -I tools/lab/teams.py resolve ARG [ARG ...]   one line per team: teamId <TAB> current name <TAB> rank <TAB> label
       python3 -I tools/lab/teams.py ids ARG [ARG ...]       the team ids only, one per line (for shell scripts)
       python3 -I tools/lab/teams.py list                    the id table and groups with each team's current ladder name
  ARG     a teamId (full, or its first 8 characters), a key of TEAMS (fish, mite, pantheon), a group (TOP3), a comma list of any
          of these, or a name as the ladder shows it now (case and punctuation do not matter). Names resolve through the ladder.
  --fresh refresh the cached ladder first (the cache is /data/USER/st/teams/ladder.json, shared with teamdata.py, kept 1 h).
From Python: sys.path.insert(0, <tools/lab>); import teams; teams.resolve('Mite') -> (id, name, rank); teams.expand('TOP3') ->
[ids]; teams.name_of(id); teams.label(id) (a file-name-safe label that stays the same when the team renames).
Platform calls only through tools/lab/platlock.sh (one ladder read per hour at most)."""
import datetime
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = "/data/USER/cambc400/bin/cambc400"
CACHE = "/data/USER/st/teams/ladder.json"  # teamdata.py's ladder cache: {utc, teams: [{teamId, name, rank, rating, ...}]}

US = "BattleCats"
US_ID = "285f4eb5-e97f-4ea4-93c5-19e1590a1e5a"  # BattleCats

# Keyed by a short stable label; the platform teamId is the identity. Names in comments are the names seen when added.
TEAMS = {
    "fish": "1890540d-1ffc-4847-adbf-d0d08772f268",      # Intercontinental Fish
    "mite": "ee83f5e5-bcad-4923-86b4-b79ea6083d2e",      # Mite
    "pantheon": "547efb5b-57e5-4355-8501-3b331f506d62",  # Pantheon (was 'newer team')
}
GROUPS = {
    "TOP3": [TEAMS["fish"], TEAMS["mite"], TEAMS["pantheon"]],
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _plat(args, timeout=120):
    return subprocess.run(["sh", f"{REPO}/tools/lab/platlock.sh", CLI, *args], capture_output=True, text=True, timeout=timeout)


def ladder(force=False, max_age=3600):
    """The ladder (up to 400 teams), cached in CACHE for max_age seconds. A failed read falls back to the old cache."""
    try:
        if not force and time.time() - os.path.getmtime(CACHE) < max_age:
            with open(CACHE) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    teams, page = [], 1
    while page <= 4:
        try:
            r = _plat(["ladder", "--limit", "100", "--page", str(page), "--json"])
            x = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, ValueError):
            break
        teams += x.get("teams", [])
        if len(teams) >= x.get("total", 0) or not x.get("teams"):
            break
        page += 1
    if teams:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        t = f"{CACHE}.new.{os.getpid()}"
        with open(t, "w") as f:
            json.dump(dict(utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), teams=teams), f, indent=0, sort_keys=True)
        os.replace(t, CACHE)
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def is_id(s):
    return bool(UUID.fullmatch((s or "").strip().lower()))


def _by_id(lad):
    return {t["teamId"]: t for t in lad.get("teams", []) if t.get("teamId")}


def expand(arg):
    """ARG (group, key, id, id prefix, name, or a comma list of these) -> [teamId, ...] without resolving names on the ladder
    unless needed."""
    out = []
    for a in [x.strip() for x in str(arg).split(",") if x.strip()]:
        g = next((v for k, v in GROUPS.items() if k.lower() == a.lower()), None)
        out += g if g else [resolve(a)[0]]
    return list(dict.fromkeys(out))


def resolve(arg, lad=None):
    """One team -> (teamId, current ladder name or None, rank or None). Raises KeyError if it can't be found."""
    a = (arg or "").strip()
    key = TEAMS.get(a.lower())
    tid = a.lower() if is_id(a) else key
    lad = lad if lad is not None else ladder()
    by = _by_id(lad)
    if not tid and re.fullmatch(r"[0-9a-f]{8}", a.lower()):
        tid = next((i for i in list(by) + list(TEAMS.values()) if i.startswith(a.lower())), None)
    if not tid:
        hit = [t for t in lad.get("teams", []) if (t.get("name") or "").lower() == a.lower()] or \
              [t for t in lad.get("teams", []) if slug(t.get("name")) == slug(a)]
        if not hit:  # a name not on the cached ladder: it may have just renamed, so read the ladder once more
            lad = ladder(force=True)
            by = _by_id(lad)
            hit = [t for t in lad.get("teams", []) if (t.get("name") or "").lower() == a.lower() or slug(t.get("name")) == slug(a)]
        if not hit:
            near = [t["name"] for t in lad.get("teams", []) if slug(a) and slug(a) in slug(t.get("name"))]
            raise KeyError(f"no team {a!r} on the ladder ({len(lad.get('teams', []))} teams)" + (f"; did you mean: {', '.join(near[:6])}" if near else ""))
        tid = hit[0]["teamId"]
    t = by.get(tid, {})
    return tid, t.get("name"), t.get("rank")


def name_of(tid, lad=None):
    """The team's current ladder name (falls back to its TEAMS key, then the id's first 8 characters)."""
    t = _by_id(lad if lad is not None else ladder()).get(tid)
    if t and t.get("name"):
        return t["name"]
    return next((k for k, v in TEAMS.items() if v == tid), tid[:8])


def label(tid, lad=None):
    """A file-name label that does not change when the team renames: its TEAMS key if it has one, else the current name's slug
    plus the id's first 8 characters (the id part keeps it unique and findable after a rename)."""
    k = next((k for k, v in TEAMS.items() if v == tid), None)
    return k if k else f"{slug(name_of(tid, lad))[:32] or 'team'}_{tid[:8]}"


def main():
    a = sys.argv[1:]
    if "--fresh" in a:
        a.remove("--fresh")
        ladder(force=True)
    if not a or a[0] not in ("resolve", "ids", "list"):
        sys.exit(__doc__)
    lad = ladder()
    if a[0] == "list":
        print(f"ladder cache {lad.get('utc', '?')}")
        for k, v in TEAMS.items():
            t = _by_id(lad).get(v, {})
            print(f"{k}\t{v}\t{t.get('name', '(not on the ladder)')}\trank {t.get('rank', '?')}")
        for g, ids in GROUPS.items():
            print(f"{g}\t" + ", ".join(f"{label(i, lad)}={i[:8]}" for i in ids))
        return
    try:
        ids = [i for x in a[1:] for i in expand(x)]
    except KeyError as e:
        sys.exit(f"teams: {e.args[0]}")
    if not ids:
        sys.exit(__doc__)
    for i in ids:
        if a[0] == "ids":
            print(i)
        else:
            t = _by_id(lad).get(i, {})
            print(f"{i}\t{t.get('name') or name_of(i, lad)}\t{t.get('rank', '?')}\t{label(i, lad)}")


if __name__ == "__main__":
    main()
