#!/usr/bin/env python3
"""test_seat: seat regression (10 Nov, Coordinator: a reader took the seat from team_name and mirrored seat-B games). For the newest stored
seat-A and seat-B games in gameindex.tsv: replay.load(path, us=SEAT) and gamesum.load(id) must give g.us == our_seat, team_name(g.us) == "us",
and the replay's own winner must agree with gameindex's result. Exit 1 on any mismatch.
usage: python3 -I tools/lab/test_seat.py"""
import csv
import sys

sys.path.insert(0, "/homes/zw4424/cambc/tools/lab")
import gamesum as GS  # noqa: E402
import replay as R  # noqa: E402

rows = [r for r in csv.DictReader(open("/data/zw4424/st/gameindex.tsv"), delimiter="\t") if r["path"] != "-" and r["our_seat"] in "ab"
        and r["result"] in ("win", "loss")]
bad = 0
for seat in "ab":
    got = 0
    for r in reversed(rows):
        if r["our_seat"] != seat:
            continue
        try:
            gs = GS.load(r["id"])
        except Exception:  # noqa: BLE001  not stored yet: take an older one
            continue
        for name, g in (("replay.load", R.load(r["path"], us=seat.upper())), ("gamesum", gs)):
            win = {1: 0, 2: 1}.get(g.final.get("outcome")) == g.us
            ok = "AB"[g.us] == seat.upper() and g.team_name(g.us) == "us" and win == (r["result"] == "win")
            print(f"{'ok ' if ok else 'BAD'} seat {seat.upper()} {name:11s} {r['id']} us {g.us} name {g.team_name(g.us)} win {win} index {r['result']}")
            bad += not ok
        got += 1
        if got == 2:
            break
sys.exit(1 if bad else 0)
