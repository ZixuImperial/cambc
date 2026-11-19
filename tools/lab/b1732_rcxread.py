"""b1732 RCX sweep reader (readmany READER contract): for BOTH teams of a game ('A', 'B'): drafted kits, each kit's earned gold
(end stats; earned = all gold), the team's earned gold at r300 and r600 (turn rows' 'earned' column, each champion's last turn at or
before the round; end statistics are empty for a capped game, so the replay rows are used)."""
import replay


def side(g, team):
    mine = {b["id"]: b for b in g.d["bodies"] if b["team"] == team}
    kits = sorted({str(b.get("name", "?")).lower() for b in mine.values()})
    gold = {}
    for b in (g.d.get("stats") or {}).get("bodies", []):
        if b["id"] in mine:
            k = str(mine[b["id"]].get("name", "?")).lower()
            gold[k] = gold.get(k, 0) + int(b.get("earnedGold", 0))
    out = {"kits": kits, "gold": gold}
    ec = g.ci.get("earned")
    for r in (300, 600):
        tot, seen = 0, False
        if ec is not None and g.last_round >= r:
            for cid in mine:
                last = None
                for t in g.by_champ.get(cid, []):
                    if t[0] <= r:
                        last = t
                    else:
                        break
                if last is not None:
                    tot += int(last[ec] or 0)
                    seen = True
        out[f"g{r}"] = tot if seen else None
    return out


def read(path, meta):
    g = replay.load(path, us="A")
    return {"last": g.last_round, "A": side(g, 0), "B": side(g, 1)}
