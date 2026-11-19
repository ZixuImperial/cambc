#!/usr/bin/env python3
"""changedprobe: the new maps where a rare change changes the game. Tool builder, 7 Nov (owner via the Builder: 'if a change only shows on a tiny portion of maps, we should
generate a bit more maps for it to be properly tested on and skip the invalid ones': FFW 2%, DWK 1/123, GDM 148/4000, mct2 .7%: unchanged maps read exactly .500 and dilute the read).

usage: python3 -I tools/lab/changedprobe.py CAND BASE OUTDIR --n N [--batch 300] [--max-probe 40000] [--wall 10800] [--wfams w_a,w_b] [--tag T]
  CAND must be BASE's code with data flips (a flip, or a flip v its donor at flag 0): any code difference reshuffles most games through fuel timing, so nearly every map reads changed.
  A first batch over NOT_RARE (50%) changed stops the probe and says so: read that candidate the normal way.
How a map is judged: CAND v BASE in both seats, full games, 100k fuel, on the pilots. A map is UNCHANGED when the two replays are byte-identical: neither side's change touched the game,
  so both are the base mirror game. Measured on 649,601 candidate-map pairs in 197 smokefarm runs (7 Nov): the two seats equal <=> both equal live v live, no exception, and all 122,923
  unchanged maps scored exactly .500. So unchanged maps carry no information, and the two games that find a changed map are also its read: no separate probe, no live v live game.
CHANGED IS NOT FIRING: a map counts as changed when any part of a game differs, knock-on fuel timing included. FFW: 2% firing, 14% of BIG and 21-23% of fresh maps changed (8 reads). This share is
  the right one for the effect: only an identical game is exactly .500. A change over 50% stops the probe.
Speed (7 Nov, measured): about 1,500 maps in 21-26 s with the pilot queue free, up to 75 s behind other batches; CP_PAR 6 was no faster than 3. Maps are not the limit: sets are built on the nodes.
  The replay's hash is made on the node (CP_DIGEST=0: the replay comes back): same changed maps and scores on 120 maps, no wall-time gain, 96% fewer bytes through the home server.
  A draw waits up to CP_RESERVE_WAIT (240 s) while the pool has under CP_RESERVE (6) sets, so a long probe leaves sets for shipchecks.
Not done, on purpose: stopping a game at the first difference. Only a full game proves a map unchanged, and a changed map needs its full game for the score, so nothing would be saved.
Stops at N changed maps, or --max-probe maps, or --wall seconds, or after HOPELESS_MIN maps once the share and speed so far would need over 1.5 x --wall. The stop depends only on the count of changed maps, never their scores.
Draws: fresh pool sets (stratmaps --take: unsaved, half pathological), up to CP_PAR (3) batches at once. No per-half quota, unlike draftprobe: the 50/50 draw is the pool, so the changed
  maps it finds are already weighted as the pool's changed maps are, and share x (score - .5) needs no reweighting.
--wfams: every second batch is generated from those genweird families here, to raise the hit rate. It is slow: ~200 s a batch on this machine against ~0 from the pool, holding a batch slot
  meanwhile; FFW on two good families hit 46% v 22%, about 20x fewer changed maps a second. Use it only for a change that almost never fires outside those families.
  Those maps over-represent the change (b1401: 385 of 411 from targeted families), so
  they are marked 'targeted': the changed share, the score behind the implied effect and the unchanged count use the pool draw only, and the report gives the targeted share.
OUTDIR gets otf.json (only the kept changed maps; condab OTF / stylepanel read it as is), their .map26a files, and changed.json (per map: changed, score, labels, targeted).
  Unchanged maps and every game file are removed batch by batch (never saved).
As a module: build(cand, base, outdir, n, tag, ...) -> summary; report(summary) -> lines; implied(summary) -> the pool effect.
STOCK (8 Nov): --stock draws from tools/lab/draftstock.py's map stock, --base-has F (implies --stock) only maps whose stored BASE lineup / labels pass a draft-time filter: a change that needs a kit to fire, e.g. --base-has tavi. Every map played here is a full-game read, so every drawn map is
  consumed. A filtered probe also plays ~DS_OUT_N (300) maps OUTSIDE the filter; coverage under .95 stops the probe INCONCLUSIVE (st['inconclusive'], stylepanel exits 2). Shares in the summary and report are scaled to the pool.
RARE BANK (11 Nov, owner: "store maps you find in common reads that fit one of the rare reads and once you have enough do the rare read with that"):
  env CP_RAREBANK=<bank dir> (shipwatch sets it via tools/lab/rarebank.py gate, with SP_CHANGED_TARGETED_ONLY=1): every --wfams batch is drawn from the
  bank (hard links; drawn maps are consumed for the slug), never the pool or generation. An empty bank before N changed maps stops the probe with
  st.bank_short (stylepanel then saves the probe for a resume and exits 4: RARE BANK SHORT). A saved short read of the same CAND v BASE resumes.
  Without a bank, a shipcheck rare line (env RARE) never generates family maps unless bq/rare_generate_ON or its slug is in bq/rare_generate_ok.txt:
  harvested common-set maps only.
Used by: smokefarm.py screen CAND --changed N, inforead.py CAND BASE --changed N, stylepanel.py ... --changed N."""
import json
import math
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

REPO = "/homes/USER/cambc"
LAB = REPO + "/tools/lab"
sys.path[:0] = [LAB, REPO + "/tools/cxe"]
NOT_RARE = 0.5
def pool_share(bank_dir):
    """12 Nov ~23:5xZ (owner via the Coordinator: a class-bank rare read's 'not rare' is judged on the class's share of the POOL, not on the share
    of the bank's maps that change): the bank slug's longest matching prefix in bq/rarebank_poolshare.tsv -> share (0-1), or None (unknown:
    the bank-share stop applies as before)."""
    slug = os.path.basename(bank_dir.rstrip("/"))
    best = None
    try:
        for ln in open("/data/USER/st/bq/rarebank_poolshare.tsv"):
            p = ln.split("#")[0].rstrip("\n").split("\t")
            if len(p) >= 2 and p[0] and slug.startswith(p[0]) and (best is None or len(p[0]) > len(best[0])):
                best = (p[0], float(p[1]))
    except (OSError, ValueError):
        return None
    return best[1] if best else None


def pool_share_cls(cond):
    """13 Nov (TB, 14031 lce2 stopped 'not rare' at 81% on a live class draw): a class read drawn on the fly (SP_CLASS, no bank) is judged on its
    class's POOL share too: the bq/rarebank_poolshare.tsv row whose condition (3rd column, first word) equals SP_CLASS -> share, or None."""
    cond = (cond or "").strip()
    if not cond:
        return None
    try:
        for ln in open("/data/USER/st/bq/rarebank_poolshare.tsv"):
            p = ln.split("#")[0].rstrip("\n").split("\t")
            if len(p) >= 3 and p[2].split() and p[2].split()[0] == cond:
                return float(p[1])
    except (OSError, ValueError):
        return None
    return None


NEVER_MIN = int(os.environ.get("CP_NEVER_MIN", 100))  # 11 Nov (Builder, rgp1vs: 0 of 301 bank maps changed): a targeted read with 0 changed
# after this many probed maps stops: the flag's clause does not change play on these families
HOPELESS_MIN = int(os.environ.get("CP_HOPELESS_MIN", 6000))  # maps before the probe may give up on reaching N inside 1.5 x --wall


def say(msg):
    print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} changedprobe: {msg}", flush=True)


def half(m):
    return "weird" if (m.get("labels") or {}).get("pool") == "weird" else "std"


def pair_score(ga, gb):
    """CAND on A in ga, on B in gb; a draw is 1/2"""
    return ({"A": 1, "B": 0, "D": 0.5}[ga["win"]] + {"B": 1, "A": 0, "D": 0.5}[gb["win"]]) / 2


def play(cso, bso, bdir, names, log=say, unlimited=False):
    """both seats of every map in BDIR -> {name: (game, game)}; a map with a game missing is left out. unlimited: --fuel 1e9 (no cut-offs)"""
    import pilotcxe
    import smokefarm as SF
    g = f"{bdir}/g"
    os.makedirs(g, exist_ok=True)
    games = []
    for x in names:
        mp = f"{bdir}/{x}.map26a"
        xa = "--statistics @STATS@" + SF.SMOKE_X + (" --fuel 1000000000" if unlimited and "--fuel" not in SF.SMOKE_X else "")
        games.append((cso, bso, mp, f"{g}/{len(games)}", xa))
        games.append((bso, cso, mp, f"{g}/{len(games)}", xa))
    digest = os.environ.get("CP_DIGEST", "1") == "1"  # the replay's hash is made on the node: 150 KB a game stays there
    if not pilotcxe.run(games, say=lambda m: log(m) if "local" in m else None, digest=digest):  # some games missing: those maps count as unread; never played locally
        log(f"{os.path.basename(bdir)}: not every game came back")
    res = [SF.read_game(x[3]) for x in games]
    if digest:
        for x, r in zip(games, res):
            if r:
                try:
                    r["h"] = open(x[3] + ".sha1").read().split()[0]
                except (OSError, IndexError):
                    r["h"] = None
    return {x: (res[2 * i], res[2 * i + 1]) for i, x in enumerate(names) if res[2 * i] and res[2 * i + 1] and res[2 * i]["h"] and res[2 * i + 1]["h"]}


def queue_ahead():
    """'N pilot items queued ahead of ours (key K)': our games run at PILOTCXE_PRIO (key 500 - prio); lower keys are claimed first."""
    try:
        key = 500 - int(os.environ.get("PILOTCXE_PRIO", "9"))
        qd = "/homes/USER/condor-runs/pilotq/queue"
        ks = [int(x.split("_", 1)[0]) for x in os.listdir(qd) if x.split("_", 1)[0].isdigit()]
        return (f"{sum(1 for k in ks if k < key)} pilot items queued ahead of ours (key {key}), {sum(1 for k in ks if k == key)} at our key; "
                f"set PILOTCXE_PRIO higher to jump the queue")
    except OSError as e:
        return f"queue unreadable ({e})"


def pool_room():
    """A long probe must not drain the fresh pool under a shipcheck: wait a while for the nodes to refill it when it is low (CP_RESERVE sets, CP_RESERVE_WAIT s), then go on."""
    import freshpool
    t = time.time()
    while len(freshpool.ready()) < int(os.environ.get("CP_RESERVE", 6)) and time.time() - t < int(os.environ.get("CP_RESERVE_WAIT", 240)):
        time.sleep(10)


def draw(bdir, nn, tag, wfams, own_bot=None, have=(), cls=None):
    if wfams and os.environ.get("CP_RAREBANK"):  # 11 Nov (owner ~02:4xZ): a rare read on its bank (tools/lab/rarebank.py): bank maps only, never pool or generation
        import rarebank
        return rarebank.draw(os.environ["CP_RAREBANK"], bdir, nn, tag, have=have)
    if wfams and os.environ.get("RARE"):  # 11 Nov (owner: "just store maps you find in common reads"): a shipcheck rare line never generates family
        try:                              # maps unless bq/rare_generate_ON, or its slug is in bq/rare_generate_ok.txt; the common sets' maps only
            import rarebank
            import ridealong
            if not rarebank.gen_allowed(ridealong.base_slug(own_bot or "")):
                refuse = lambda d, k: (None, "rare generation off (bq/rare_generate_ON absent, slug not in bq/rare_generate_ok.txt): common-set maps only")  # noqa: E731
                if ridealong.harvest_on() and os.environ.get("CP_HARVEST", "1") != "0":
                    return ridealong.draw_with_harvest(bdir, nn, tag, wfams, refuse, own_bot=own_bot, have=have)
                return refuse(bdir, nn)
        except ImportError:
            pass
    if wfams and os.environ.get("CP_HARVEST", "1") != "0":  # 10 Nov (owner: "don't double generate"): bq/ridealong_ON or bq/rarereuse_ON: family maps
        try:                                                # from the common fresh sets first (tools/lab/ridealong.py harvest), only the shortfall generated
            import ridealong
            if ridealong.harvest_on():
                return ridealong.draw_with_harvest(bdir, nn, tag, wfams, lambda d, k: _draw(d, k, tag, wfams), own_bot=own_bot, have=have)
        except ImportError:
            pass
    return _draw(bdir, nn, tag, wfams, cls=cls)


def _draw(bdir, nn, tag, wfams, cls=None):
    os.makedirs(bdir, exist_ok=True)
    cmd = [sys.executable, "-I", f"{LAB}/stratmaps.py", bdir, "--n", str(nn)]
    cmd += ["--light"] + (["--weird", "1", "--wfams", wfams] if wfams else ["--take", "--who", f"changedprobe:{tag}"])  # --light: if the pool is out, a generation here waits for load
    # 13 Nov (TB; Builder/b2371: pgr58's --class altgrp1 read drew 892 POOL maps, only 77 of 420 kept in the class): a class read (SP_CLASS,
    # set by shipcheck from the line's CLASS marker) draws class maps only, as stylepanel's fresh sets do; before this every --class rare read
    # without a ready bank probed unfiltered pool maps
    # 13 Nov 16:2xZ (TB: heavyfuel inherited SP_CLASS and drew 300 class maps live -> stratmaps SHORT rc 1 -> 'no heavy-turn read' on every
    # class line, swgfms .533 failed on cap5 with no ratio row): cls="" from a caller forces the plain pool draw
    cls = os.environ.get("SP_CLASS", "").strip() if cls is None else cls.strip()
    if cls:
        # 13 Nov (TB, ~05:4xZ: class draws with --take discarded ~90% of the shared fresh pool's maps (an 8% class needs ~3,500 pool maps a
        # batch) and drained it to 2 sets, starving every check): a class draw GENERATES its own maps on the pilots (stratmaps --class, no
        # --take); the pool stays for the pool reads
        cmd = [c for c in cmd if c not in ("--take", "--who", f"changedprobe:{tag}")] + ["--class", cls]
    if not wfams:
        pool_room()
    r = subprocess.run(["nice", "-n", "10"] + cmd, cwd=REPO, capture_output=True, text=True)
    if r.returncode or not os.path.exists(f"{bdir}/otf.json"):
        return None, f"stratmaps rc {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}"
    return json.load(open(f"{bdir}/otf.json")), None


def build(cand, base, outdir, n, tag, batch=300, max_probe=40000, wall=10800, wfams=None, avoid=(), log=say, stock=False, base_has=None):
    """Fill OUTDIR with up to n changed maps -> summary(). A resume keeps what changed.json holds. AVOID: dirs whose maps are never kept (a second read's first read)."""
    import cxebuild
    os.environ["CXEFARM"] = "1"  # once, here: pilotcxe sets and restores it per call, which races between batch threads
    os.environ.setdefault("PILOTCXE_PRIO", "9")
    os.environ.setdefault("PILOTCXE_PER", "8")
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    pj, oj = f"{outdir}/changed.json", f"{outdir}/otf.json"
    bank = os.environ.get("CP_RAREBANK") if wfams else None
    if bank:  # 11 Nov: a saved short bank read of the same CAND v the same BASE goes on from where it stopped (tools/lab/rarebank.py)
        import rarebank
        try:
            rarebank.seed_resume(bank, outdir, cand, base, log=log)
        except Exception as e:  # noqa: BLE001  a broken resume: the read starts whole
            log(f"rare bank: resume not used ({type(e).__name__}: {e})")
    st = json.load(open(pj)) if os.path.exists(pj) else dict(cand=cand, base=base, maps={}, unread=0, batches=0, next_batch=0, games=0)
    meta = json.load(open(oj)) if os.path.exists(oj) else None
    avoid_names = set()
    for d in avoid:
        try:
            avoid_names |= {m["name"] for m in json.load(open(f"{d}/otf.json"))["maps"]}
        except (OSError, ValueError, KeyError):
            pass
    kept = lambda: len(meta["maps"]) if meta else 0  # noqa: E731
    import smokefarm as SF

    def lib(bot):  # a flip's library is patched in ~.2 s; cxebuild's slot waits while load is over its guard (7 Nov: 4 min for one flip)
        so = SF.patch_so(bot) if SF.flipinfo(bot) else None
        return so or cxebuild.build_bot(bot)
    log(f"libraries: {cand} v {base}")
    cso, bso = lib(cand), lib(base)
    log(f"libraries ready in {time.time() - t0:.0f} s; drawing up to {max_probe} maps until {n} changed")
    stockm = bool(stock or base_has)
    DS = flt = lkey = None
    if stockm:
        import draftstock as DS  # noqa: N813
        if wfams:
            sys.exit("changedprobe: --wfams with the stock: not supported")
        flt = DS.parse_filter(base_has)
        DS.check_kits(flt)
        if not st.get("stock"):
            # 13 Nov (TB, 14147 wfo1i: harness INCONCLUSIVE 'the stock has no lineups' 20 min after a ship, while the new live's lineups were
            # being made): wait for them (CP_STOCK_WAIT, 40 min) instead of failing the check
            t_w = time.time()
            while True:
                try:
                    lkey, note = DS.key_for(base)
                    break
                except DS.StockError as e:
                    if time.time() - t_w > int(os.environ.get("CP_STOCK_WAIT", 2400)):
                        raise
                    log(f"stock: {str(e)[:160]}; waiting for the lineups ({(time.time() - t_w) / 60:.0f} min)")
                    time.sleep(120)
            st["stock"] = dict(filter=flt[2], key=lkey, note=note, frac=DS.frac(lkey, flt), root=DS.ROOT)
            if note:
                log(f"stock: {note}")
        lkey = st["stock"]["key"]
        log(f"stock: filter {flt[2] or '(none)'} passes {100 * st['stock']['frac']['mean']:.1f}% of the stock, lineups key {lkey}")
    if cso == bso:
        st.update(done=True, stopped="CAND and BASE are the same library")
        json.dump(st, open(pj, "w"))
        return summary(st, meta)

    def save():
        if meta is not None:
            json.dump(meta, open(oj + ".part", "w"))
            os.replace(oj + ".part", oj)
        json.dump(st, open(pj + ".part", "w"))
        os.replace(pj + ".part", pj)

    def rate():
        ms = [m for m in st["maps"].values() if not m.get("targeted")]
        return max(sum(m["changed"] for m in ms) / len(ms), 0.002) if len(ms) >= 300 else 0.05

    spent = {}

    def run_batch(k, fams):
        bdir = f"{outdir}/probe/b{k}" if k >= 0 else f"{outdir}/probe/out"
        t = time.time()
        if stockm:  # every map drawn here is played to the end: consumed
            nn = DS.OUT_N if k < 0 else batch
            bm = DS.draw(bdir, lkey, flt, nn - nn // 2, nn // 2, f"changedprobe:{tag}", outside=k < 0)
            # 13 Nov (TB, wfo1bs/wfo1bsi: 'stock empty' minutes after a ship while the new live's lineups were still being made): an empty
            # draw waits for more lineups (2 min polls, CP_STOCK_WAIT 40 min) before the probe gives up
            t_e = time.time()
            while not bm["maps"] and k >= 0 and time.time() - t_e < int(os.environ.get("CP_STOCK_WAIT", 2400)):
                time.sleep(120)
                bm = DS.draw(bdir, lkey, flt, nn - nn // 2, nn // 2, f"changedprobe:{tag}", outside=False)
            err = None if bm["maps"] else f"stock empty: no maps left that pass {flt[2] or '(no filter)'} ({bm['stock']['avail']}, {bm['stock']['nolu']} without a lineup)"
            if err and k >= 0:
                bm = None
            elif bm:
                DS.consumed([m["name"] for m in bm["maps"]], f"changedprobe:{tag}", "full games")
        else:
            bm, err = draw(bdir, batch, tag, fams, own_bot=cand, have=set(st["maps"]))
        spent[k] = [time.time() - t, 0.0]
        if bm is None:
            return k, None, err, bool(fams)
        names = [m["name"] for m in bm["maps"] if m["name"] not in st["maps"] and os.path.exists(f"{bdir}/{m['name']}.map26a")]
        t = time.time()
        # 13 Nov (TB, wfo1i/wfo1bs: 42% of maps OUTSIDE the willow filter 'changed' at the 100k budget, only through fuel timing, so the safety
        # row failed every --base-has line with any fuel cost): the outside sample plays at UNLIMITED fuel, where a game differs only if the
        # change's logic acts there (CP_OUTSIDE_UNLIMITED=0 restores the budget games)
        got = play(cso, bso, bdir, names, log, unlimited=(k < 0 and os.environ.get("CP_OUTSIDE_UNLIMITED", "1") == "1"))
        spent[k][1] = time.time() - t
        return k, bm, got, bool(fams)

    stop, inflight, empty = None, {}, 0
    par = max(1, int(os.environ.get("CP_PAR", 3)))

    def coverage_stop():
        """the safety row (a filtered probe, after the outside sample and enough inside maps): -> an INCONCLUSIVE reason or None."""
        if not (stockm and flt[2]) or not (st.get("outside") or {}).get("done") or len(st["maps"]) < int(os.environ.get("DP_COV_MIN", 100)):
            return None
        ok, why = DS.safety_verdict(DS.coverage(st))
        return None if ok else why

    with ThreadPoolExecutor(par + 1) as ex:
        if stockm and flt[2] and not (st.get("outside") or {}).get("done"):
            inflight[ex.submit(run_batch, -1, None)] = -1
        while True:
            while not stop and sum(1 for v in inflight.values() if v >= 0) < par:
                seen = len(st["maps"]) + st["unread"]
                if seen + batch * len(inflight) >= max_probe or time.time() - t0 > wall:
                    if not inflight and kept() < n:
                        st["stopped"] = f"map limit {max_probe}" if seen >= max_probe else f"wall limit {wall // 60} min"
                        stop = "limit"
                    break
                if kept() + rate() * batch * len(inflight) >= n:
                    break
                k = st["next_batch"]
                st["next_batch"] = k + 1
                # 10 Nov: SP_CHANGED_TARGETED_ONLY=1 draws EVERY batch from --wfams (a change that only shows on its class; the rare bar
                # reads changed maps, which are marked targeted, so the pool share stays unread rather than wrong)
                tonly = os.environ.get("SP_CHANGED_TARGETED_ONLY") == "1"
                inflight[ex.submit(run_batch, k, wfams if wfams and (tonly or k % 2) else None)] = k
            if not inflight:
                break
            fin, _ = wait(list(inflight), timeout=int(os.environ.get("CP_BEAT", 300)), return_when=FIRST_COMPLETED)
            if not fin:  # 10 Nov (b1769: CAND v SHADOW probes looked hung 85 min after 'drawing'; their games sat at prio 9 behind ~1,800 queued items)
                log(f"waiting on batch(es) {sorted(v for v in inflight.values())} for {(time.time() - t0) / 60:.0f} min: {queue_ahead()}")
                continue
            for f in fin:
                inflight.pop(f)
                k, bm, got, targeted = f.result()
                if k == -1:  # the safety row: played in full, so spent; only the shares are kept
                    o = dict(done=True, drawn=len(bm["maps"]), probed=0, changed=0, unread=0)
                    for m in bm["maps"]:
                        if m["name"] not in got:
                            o["unread"] += 1
                            continue
                        ga, gb = got[m["name"]]
                        o["probed"] += 1
                        o["changed"] += ga["h"] != gb["h"]
                    st["outside"] = o
                    st["games"] += 2 * len(got)
                    shutil.rmtree(f"{outdir}/probe/out", ignore_errors=True)
                    log(f"outside sample: {o['changed']} of {o['probed']} maps OUTSIDE the filter changed ({o['unread']} unread)")
                    save()
                    why = coverage_stop()
                    if why and not stop:
                        st["inconclusive"], st["stopped"] = why, f"INCONCLUSIVE: {why}"
                        log(f"INCONCLUSIVE: {why}")
                        stop = "coverage"
                    continue
                bdir = f"{outdir}/probe/b{k}"
                if bm is None:
                    log(f"batch {k}: {got}")
                    if bank and str(got).startswith("rare bank exhausted"):
                        st["bank_short"] = True
                        st["stopped"] = st.get("stopped") or f"rare bank exhausted (BANK SHORT): {kept()} of {n} changed maps"
                    if stockm and str(got).startswith("stock empty"):
                        st["stopped"] = got
                    # 13 Nov (TB: 13 class reads ended 'no changed maps' when their waiting draws were stopped): a failed draw (stratmaps rc,
                    # a killed or lost generation) is retried; only an exhausted bank, an empty stock or CP_DRAW_FAILS (4) failures in a row stop
                    elif str(got).startswith("stratmaps rc") and st.get("draw_fails", 0) < int(os.environ.get("CP_DRAW_FAILS", 4)):
                        st["draw_fails"] = st.get("draw_fails", 0) + 1
                        log(f"batch {k}: draw failed ({st['draw_fails']} in a row): another batch is drawn")
                        continue
                    stop = stop or "maps"
                    continue
                if meta is None:
                    meta = dict({a: b for a, b in bm.items() if a != "maps"}, maps=[], changed_probe=dict(cand=cand, base=base))
                st["draw_fails"] = 0  # a batch came back: the failure count starts again
                nch = 0
                for m in bm["maps"]:
                    x = m["name"]
                    if x in st["maps"]:
                        continue
                    if x not in got:
                        st["unread"] += 1
                        continue
                    ga, gb = got[x]
                    ch = ga["h"] != gb["h"]
                    st["maps"][x] = dict(changed=ch, score=pair_score(ga, gb), labels=m.get("labels", {}), targeted=targeted)
                    nch += ch
                    if ch and kept() < n and x not in avoid_names:
                        shutil.copyfile(f"{bdir}/{x}.map26a", f"{outdir}/{x}.map26a")
                        meta["maps"].append(m)
                st["games"] += 2 * len(got)
                st["batches"] += 1
                shutil.rmtree(bdir, ignore_errors=True)  # never-saved maps and game files: read, gone
                if st["batches"] % max(1, len(st["maps"]) // 20000) == 0:  # a time-limited probe can reach 100,000+ maps: the state file must not be rewritten every batch
                    save()
                s = summary(st, meta)
                log(f"batch {k}{' (targeted)' if targeted else ''}: {nch} of {len(got)} changed; kept {kept()}/{n}; pool draw {s['changed']} of {s['probed']} ({100 * s['share']:.2f}%), "
                    f"{s['unread']} unread, {len(inflight)} in flight, draw {spent[k][0]:.0f} s, games {spent[k][1]:.0f} s, {time.time() - t0:.0f} s in all")
                empty = 0 if got else empty + 1
                if empty >= 2:
                    log("two batches in a row came back with no games: stopping (pilots down?)")
                    stop = stop or "nogames"
                    st["stopped"] = "no games from the pilots"
                why = coverage_stop() if not stop else None
                if why:
                    st["inconclusive"], st["stopped"] = why, f"INCONCLUSIVE: {why}"
                    log(f"INCONCLUSIVE: {why}")
                    stop = "coverage"
                el = time.time() - t0
                ins = s.get("inside_share", s["share"])  # the filter's own hit rate: what this probe's next maps will find
                if s["probed"] >= HOPELESS_MIN and el + (n - kept()) / max(ins, 1 / s["probed"]) * el / s["probed"] > 1.5 * wall:
                    st["stopped"] = f"out of time: at {100 * s['share']:.3f}% changed and {s['probed'] / el:.0f} maps/s, {n} maps would take over {1.5 * wall / 3600:.1f} h"
                    stop = stop or "time"  # depends only on the count of changed maps, like every stop here
                tg_n = sum(1 for m in st["maps"].values() if m.get("targeted"))
                tg_c = sum(1 for m in st["maps"].values() if m.get("targeted") and m.get("changed"))
                if (bank or wfams) and tg_n >= NEVER_MIN and tg_c == 0 and not stop:
                    st["never"] = tg_n
                    st["stopped"] = (f"never changes play: 0 of {tg_n} targeted maps changed ({wfams or 'bank'}): the flag's clause does not fire "
                                     f"on these families; count where it fires before another rare read")
                    log(st["stopped"])
                    stop = "never"
                psh = pool_share(os.environ.get("CP_RAREBANK", "")) if bank else pool_share_cls(os.environ.get("SP_CLASS", ""))
                cls_read = bool(bank or os.environ.get("SP_CLASS", "").strip())
                if s["probed"] >= 200 and s["share"] > NOT_RARE and psh is None and cls_read and not st.get("psh_warned"):
                    # 13 Nov (TB: elong8 / zgs32 stopped 'not rare' at 71% / 96% of their CLASS maps with no pool-share row): a class read is
                    # judged on its class's pool share (owner); with no row the share is unknown, so it is not stopped: add the row
                    st["psh_warned"] = 1
                    log(f"class read with {100 * s['share']:.0f}% of class maps changed and no pool-share row in bq/rarebank_poolshare.tsv: not stopped as 'not rare'")
                if s["probed"] >= 200 and s["share"] > NOT_RARE and (psh > float(os.environ.get("CP_POOL_NOT_RARE", "0.30")) if psh is not None else not cls_read):  # 12 Nov ~23:5xZ owner: class-bank reads judge the POOL share (> ~30% = not rare)
                    st["not_rare"] = s["share"]
                    st["stopped"] = f"not a rare change: {100 * s['share']:.0f}% of maps changed (code differs from BASE, or a common change): read it the normal way"
                    stop = stop or "common"
    if stockm and flt[2] and not st.get("inconclusive") and (st.get("outside") or {}).get("done"):  # the row once more on the final counts
        ok, why = DS.safety_verdict(DS.coverage(st))
        if not ok:
            st["inconclusive"], st["stopped"] = why, f"INCONCLUSIVE: {why}"
            log(f"INCONCLUSIVE: {why}")
    st["done"] = True
    st["wall"] = st.get("wall", 0) + time.time() - t0
    if bank and kept() >= n:
        st.pop("bank_short", None)  # a batch found the bank empty, but the read has its n
    save()
    if bank:
        try:
            import rarebank
            rarebank.record_read(bank, tag, cand, base, st, meta)
        except Exception as e:  # noqa: BLE001
            log(f"rare bank: read not recorded ({type(e).__name__}: {e})")
    return summary(st, meta)


def share(c, p):
    sh = c / p if p else 0.0
    se = math.sqrt(sh * (1 - sh) / p) if p else 0.0
    return dict(probed=p, changed=c, share=sh, lo=max(0.0, sh - 1.96 * se), hi=min(1.0, sh + 1.96 * se))


def summary(st, meta=None):
    """share, unchanged count, score and implied effect on the pool draw only; targeted maps counted apart"""
    allm = list(st["maps"].values())
    ms = [m for m in allm if not m.get("targeted")]
    tg = [m for m in allm if m.get("targeted")]
    kept_names = {m["name"] for m in meta["maps"]} if meta else set()
    out = dict(share(sum(m["changed"] for m in ms), len(ms)), unread=st["unread"], unchanged=sum(not m["changed"] for m in ms), kept=len(kept_names), games=st.get("games", 0),
               wall=st.get("wall", 0), stopped=st.get("stopped"), not_rare=st.get("not_rare"), inconclusive=st.get("inconclusive"),
               targeted=dict(probed=len(tg), changed=sum(m["changed"] for m in tg), kept=sum(st["maps"].get(x, {}).get("targeted", False) for x in kept_names)))
    if st.get("stock") and st["stock"].get("frac") and st["stock"].get("filter"):  # filtered: 'share' etc. are scaled to the pool (the implied effect uses them), inside_share is the filter's hit rate
        import draftstock as DS  # noqa: N813
        fr = st["stock"]["frac"]["mean"]
        o = st.get("outside") or {}
        out_rate = o.get("changed", 0) / o["probed"] if o.get("probed") else 0.0
        out["inside_share"] = out["share"]
        out["share"] = out["share"] * fr + out_rate * (1 - fr)
        out["lo"] = out["lo"] * fr
        out["hi"] = out["hi"] * fr + out_rate * (1 - fr)
        c = DS.coverage(dict(st, probed=len(ms), changed=sum(m["changed"] for m in ms)))
        out["stock"] = dict(st["stock"], inside_share=out["inside_share"])
        out["safety"] = dict(c, ok=DS.safety_verdict(c)[0], unread=o.get("unread"))
    for h in ("weird", "std"):
        hs = [m for m in ms if half(m) == h]
        out[h] = share(sum(m["changed"] for m in hs), len(hs))
    ks = [st["maps"][x]["score"] for x in kept_names if x in st["maps"]]
    out["kept_score"] = sum(ks) / len(ks) if ks else None  # the replayed read on the kept maps must equal this: same games
    sc = [m["score"] for m in ms if m["changed"]]
    out["n_score"] = len(sc)
    out["score"] = sum(sc) / len(sc) if sc else None
    out["score_se"] = math.sqrt(sum((x - out["score"]) ** 2 for x in sc) / (len(sc) - 1) / len(sc)) if len(sc) > 1 else None
    fams = {}
    for m in ms:
        f = fams.setdefault((m.get("labels") or {}).get("fam", "?"), [0, 0])
        f[0] += m["changed"]
        f[1] += 1
    out["fams"] = {f: dict(changed=c, probed=p) for f, (c, p) in sorted(fams.items(), key=lambda x: -x[1][0] / max(1, x[1][1]))}
    return out


def implied(s):
    """(point, lo, hi) of the whole-pool h2h effect = share x (changed-map score - .5). Every other map is exactly .500. The share's own error is not in the interval."""
    if s.get("score") is None or s.get("score_se") is None:
        return None
    d = s["score"] - 0.5
    return s["share"] * d, s["share"] * (d - 1.96 * s["score_se"]), s["share"] * (d + 1.96 * s["score_se"])


def report(s):
    L = [f"changed probe: {s['changed']} of {s['probed']} pool maps changed ({100 * s['share']:.2f}% [{100 * s['lo']:.2f}, {100 * s['hi']:.2f}]), {s['unchanged']} unchanged dropped (exactly .500), "
         f"{s['unread']} unread, {s['kept']} kept; {s['games']} games, {s['wall'] / 60:.0f} min"]
    if s.get("stock"):
        L.append(f"  STOCK draw, filter {s['stock'].get('filter')}: {s['changed']} of {s['probed']} inside the filter changed ({100 * s['inside_share']:.1f}%), the filter is {100 * s['stock']['frac']['mean']:.1f}% of the stock; shares above are scaled to the pool")
    if s.get("safety"):
        c = s["safety"]
        cov = f"{c['cov']:.3f}" if c["cov"] is not None else "n/a (nothing fired)"
        L.append(f"  SAFETY ROW (outside the filter): {c['out_changed']} of {c['out_probed']} changed ({100 * (c['outside'] or 0):.1f}%), inside {100 * c['inside']:.1f}%, coverage estimate {cov}")
    if s.get("inconclusive"):
        L.append(f"  !!! INCONCLUSIVE: {s['inconclusive']}")
    if s.get("stopped"):
        L.append(f"  probing stopped: {s['stopped']}: the read uses the {s['kept']} changed maps found")
    t = s["targeted"]
    if t["probed"]:
        L.append(f"  targeted families: {t['changed']} of {t['probed']} changed, {t['kept']} of the {s['kept']} kept maps ({100 * t['kept'] / max(1, s['kept']):.0f}%); they over-represent the change, "
                 "so the share, score and implied effect here use the pool draw only")
    for h in ("weird", "std"):
        x = s[h]
        L.append(f"  {h:5s} {x['changed']:5d} of {x['probed']:6d} changed {100 * x['share']:5.2f}% [{100 * x['lo']:.2f}, {100 * x['hi']:.2f}]")
    fl = [f"{f} {v['changed']}/{v['probed']}" for f, v in s["fams"].items() if v["changed"]]
    L.append("  families that changed (changed/probed): " + (", ".join(fl[:12]) if fl else "none"))
    im = implied(s)
    if im:
        L.append(f"  pool-draw score on changed maps {s['score']:.3f} n {s['n_score']}; implied whole-pool h2h effect = share x (score - .5) = {im[0]:+.4f} [{im[1]:+.4f}, {im[2]:+.4f}] "
                 "(the share's own error not included)")
    return L


def main():
    a = sys.argv[1:]
    if len(a) < 3 or "--n" not in a:
        sys.exit(__doc__)
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    s = build(a[0], a[1], os.path.abspath(a[2]), int(opt("--n", 0)), opt("--tag", time.strftime("%d%H%M%S", time.gmtime())), batch=int(opt("--batch", 300)),
              max_probe=int(opt("--max-probe", 40000)), wall=int(opt("--wall", 10800)), wfams=opt("--wfams", None), stock="--stock" in a, base_has=opt("--base-has", None))
    print("\n".join(report(s)))
    return 0 if s["kept"] else 1


if __name__ == "__main__":
    sys.exit(main())
