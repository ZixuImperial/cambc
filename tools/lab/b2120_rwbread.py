"""b2120 RWB/LAM node reader (readmany): compact replay facts for the local join with the diag stdout. Seat from meta/name only."""
import replay

KEEP = ("camp_attack", "capture", "capture_start", "group_respawn", "recall_arrive", "camp_death")


def read(path, meta):
    g = replay.load(path, us=replay.reader_seat(path, meta))
    us = g.us
    ev = []
    for e in g.events:
        if e[1] not in KEEP:
            continue
        if e[1] == "camp_attack" and g.team_of.get(e[3]) != us:
            continue
        ev.append(e)
    return {
        "us": "AB"[us],
        "W": g.W, "H": g.H, "rows": g.rows, "spawn": g.spawn, "altars": g.altars,
        "bodies": [b for b in g.d["bodies"]],
        "groups": [[gid, v["gems"], v["gold"], v["respawn"], v["pts"], v["camps"]] for gid, v in g.groups.items()],
        "camps": [[c, v["x"], v["y"], v["type"], v["group"]] for c, v in g.camps.items()],
        "ev": ev,
        "last": g.last_round,
        "winner": (g.final or {}).get("winner"),
    }
