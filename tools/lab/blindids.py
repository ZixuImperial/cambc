"""blindids: game ids a blind grill is walking right now (critgame brief --grill step 1: ID/blind_N/ exists, walk.txt not yet
written), plus CRIT_BLIND=ID[,ID]. card.py and ask.py drop doc and board lines that name one (Econ/Combat 6 Nov: a board post about
02gift_wrapping W2 reached its blind grill through card.py's HISTORY). Prefixes of 8+ characters match, as the board writes short ids."""
import glob
import os

ROOT = os.environ.get("CRIT_ROOT", "/data/zw4424/st/crit")


def ids():
    out = {x.strip() for x in os.environ.get("CRIT_BLIND", "").split(",") if x.strip()}
    import time
    for b in glob.glob(f"{ROOT}/*/blind_*"):
        n = b.rsplit("_", 1)[-1]
        g = f"{os.path.dirname(b)}/window_{n}.grill"
        t = os.path.getmtime(b)
        if (not os.path.exists(f"{b}/walk.txt") and time.time() - t < 6 * 3600
                and not (os.path.exists(g) and os.path.getmtime(g) > t)):  # still walking: no walk, no newer grill, < 6 h
            out.add(os.path.basename(os.path.dirname(b)))
    return out


def game_map(i):
    """the map a flagged game was played on (meta 'map', else the 'on MAP to/v' in its 'why'), or None"""
    import json
    import re
    try:
        m = json.load(open(f"{ROOT}/{i}/meta.json"))
    except (OSError, ValueError):
        return None
    if m.get("map"):
        return m["map"]
    x = re.search(r"\bon ([0-9A-Za-z][\w-]{3,})\b", m.get("why", ""))
    return x.group(1) if x else None


def keys():
    """the strings a line must not contain: each id's first 8 and 13 characters and the full id, and the game's map name (8 Nov,
    Deep: a board line naming '00crater W5' reached a blind grill through card.py's HISTORY: posts name games by map and window,
    not by id). Hiding every line about that map also hides other games on it: a blind grill loses some context, never gains a leak."""
    k = set()
    for i in ids():
        k |= {i[:8], i[:13], i} if len(i) >= 8 else set()
        mp = game_map(i)
        if mp and len(mp) >= 5:
            k |= {mp, mp.replace("-", "_"), mp.replace("_", "-")}
    return k


def hidden(line, ks=None):
    ks = keys() if ks is None else ks
    return any(k in line for k in ks)
