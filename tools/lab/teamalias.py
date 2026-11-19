"""teamalias (12 Nov, Tool Builder): a team's renames map to ONE name in our records, so readers that match a foe by name keep working.
Owner 12 Nov ~17:2xZ (via the Prism Planner): "prism best fih is stellar best girl they changed their name" (team id
547efb5b-57e5-4355-8501-3b331f506d62; first new-name ranked match 01a1d0b3-c025-7aa6-808c-15ecd4a1b3f5, 17:00Z). The canonical name is the
one our history uses. canonical(name) -> the canonical name (case kept for known teams), else name unchanged.
12 Nov ~19:3xZ (Coordinator: id-keyed SBG filters): a team is its platform teamId (tools/lab/teams.py). canonical() also maps
  - the CURRENT ladder name of any id in CANON_BY_ID (teams.py's ladder cache /data/USER/st/teams/ladder.json), so a future rename
    folds into the same name without a code change;
  - a label (sbg, pantheon, mite, fish), a full teamId or its first 8 characters, so filters can say --foe sbg or --foe 547efb5b."""
import json

ALIASES = {"prism best fih": "stellar best girl", "prism best girl": "stellar best girl"}  # 13 Nov (VV): an earlier SBG name (v275-v608 rows)
CASE = {"stellar best girl": "stellar best girl"}
CANON_BY_ID = {  # teamId -> the name our history uses for that team
    "547efb5b-57e5-4355-8501-3b331f506d62": "stellar best girl",  # SBG (teams.py 'pantheon'; renamed 'prism best fih' 12 Nov)
    "ee83f5e5-bcad-4923-86b4-b79ea6083d2e": "Mite",
    "1890540d-1ffc-4847-adbf-d0d08772f268": "Intercontinental Fish",
}
LABELS = {"sbg": "547efb5b-57e5-4355-8501-3b331f506d62", "pantheon": "547efb5b-57e5-4355-8501-3b331f506d62",
          "mite": "ee83f5e5-bcad-4923-86b4-b79ea6083d2e", "fish": "1890540d-1ffc-4847-adbf-d0d08772f268"}
LADDER = "/data/USER/st/teams/ladder.json"
_lad = None


def _ladder_names():
    """lower-case current ladder name -> teamId, for the ids in CANON_BY_ID (read once per process; {} if the cache is unreadable)."""
    global _lad
    if _lad is None:
        _lad = {}
        try:
            d = json.load(open(LADDER))
            for t in (d.get("teams", []) if isinstance(d, dict) else d):
                tid = t.get("teamId", "")
                if tid in CANON_BY_ID and t.get("name"):
                    _lad[t["name"].strip().lower().replace("_", " ")] = tid
        except (OSError, ValueError, AttributeError):
            pass
    return _lad


def team_id(name):
    """teamId for a label, id, id prefix (8+) or a known (old or current) name, else None."""
    if not isinstance(name, str):
        return None
    k = name.strip().lower().replace("_", " ")
    if k in LABELS:
        return LABELS[k]
    if len(k) >= 8:
        for tid in CANON_BY_ID:
            if tid.startswith(k):
                return tid
    k = ALIASES.get(k, k)
    for tid, c in CANON_BY_ID.items():
        if c.lower() == k:
            return tid
    return _ladder_names().get(k)


def canonical(name):
    if not isinstance(name, str):
        return name
    k = name.strip().lower().replace("_", " ")
    if k in ALIASES:
        c = ALIASES[k]
        return CASE.get(c, c)
    tid = team_id(name)
    if tid:
        return CANON_BY_ID[tid]
    return name


_ALL = None


def any_id(name):
    """13 Nov (Coordinator: foe filters on team ids, SBG renames): teamId of ANY team: team_id() first (labels, ids, known renames),
    else the ladder cache's current name of every team (lower-case, '_' -> ' '); None when unknown."""
    global _ALL
    t = team_id(name)
    if t or not isinstance(name, str):
        return t
    if _ALL is None:
        _ALL = {}
        try:
            d = json.load(open(LADDER))
            for x in (d.get("teams", []) if isinstance(d, dict) else d):
                if x.get("teamId") and x.get("name"):
                    _ALL[x["name"].strip().lower().replace("_", " ")] = x["teamId"]
        except (OSError, ValueError, AttributeError):
            pass
    return _ALL.get(name.strip().lower().replace("_", " "))
