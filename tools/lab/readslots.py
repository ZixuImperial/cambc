#!/usr/bin/env python3
"""readslots: a cap on concurrent BIG score reads across agents (Builder 7 Nov, owner yes: speed change 2). Many 2,000-map screens at
once share 13 daytime pilots, so every one of them finishes late; with a cap the first ones finish soon and the rest start in order.
Ship legs are not capped (shipcheck never calls this) and keep their pilot priority.

    import readslots
    h = readslots.acquire(tag, maps, who, say)   # blocks until a slot is free (FIFO); None when the read is small (no cap)
    ... play ...                                  # the slot is a flock: it is freed when the process ends, even on a crash

big = more than SLOT_MAPS maps (bq/bigread_maps, default 600) or a changed-map probe. Slots: bq/bigread_max (default 5; 0 = no cap).
Admission (11 Nov): bq/bigread_reserve (3) big reads always run; past that, a new one waits while the pilot queue needs more than
bq/bigread_drain_min (20) minutes to drain at the last 2 minutes' rate (no rate: more than bq/bigread_qmax (1500) items).
Waiters queue in arrival order (bq/bigread/wait/<time>_<pid>_<tag>); a dead waiter is pruned. Escape for one read: READSLOTS=0.
usage: python3 -I tools/lab/readslots.py status      who holds a slot, who waits
"""
import fcntl
import os
import sys
import time

Q = "/data/zw4424/st/bq"
D = os.path.join(Q, "bigread")
W = os.path.join(D, "wait")


def _num(p, d):
    try:
        return int(open(p).read().split()[0])
    except (OSError, ValueError, IndexError):
        return d


def slots():
    return _num(os.path.join(Q, "bigread_max"), 5)


def big_maps():
    return _num(os.path.join(Q, "bigread_maps"), 600)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _waiters():
    out = []
    for f in os.listdir(W):
        try:
            t, pid, tag = f.split("_", 2)
            pid = int(pid)
        except ValueError:
            continue
        if not _alive(pid):
            try:
                os.unlink(os.path.join(W, f))
            except OSError:
                pass
            continue
        out.append((t, pid, tag, f))
    return sorted(out)


def qdepth():
    try:
        return len(os.listdir("/homes/zw4424/condor-runs/pilotq/queue"))
    except OSError:
        return 0


def qmax():
    return _num(os.path.join(Q, "bigread_qmax"), 1500)


def drain_min():
    """Minutes the pilot queue takes to drain at the last 2 minutes' rate (done markers' mtimes); None when nothing finished."""
    d = "/homes/zw4424/condor-runs/pilotq/done"
    try:
        now = time.time()
        k = sum(1 for f in os.listdir(d) if now - os.path.getmtime(os.path.join(d, f)) < 120)
    except OSError:
        return None
    return qdepth() / (k / 2.0) if k else None


def admit_full():
    """11 Nov (Builder, owner check-in: a 6k-item queue held b1839's draft read 1 h+ behind a 1,500-item line, though ~100 pilots drain short
    ship-leg items in minutes): full only while (a) bq/bigread_reserve (3) big reads already run AND (b) the queue is deep: more than
    bq/bigread_drain_min (20) minutes to drain at the current rate, or, with no rate, more than bq/bigread_qmax items."""
    if os.path.exists(os.path.join(Q, "reads_hold")):  # 11 Nov: varguard's /var step (< 3 GB free): no new big read starts
        return True
    h = held()
    if h < _num(os.path.join(Q, "bigread_reserve"), 3):
        return False
    dm = drain_min()
    return dm > _num(os.path.join(Q, "bigread_drain_min"), 20) if dm is not None else qdepth() > qmax()


def held():
    """slots held now"""
    n = 0
    for f in os.listdir(D) if os.path.isdir(D) else []:
        if not f.startswith("slot"):
            continue
        fd = os.open(os.path.join(D, f), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            n += 1
        finally:
            os.close(fd)
    return n


def acquire(tag, maps, who="", say=print, changed=False):
    n = slots()
    if os.environ.get("READSLOTS") == "0" or n <= 0 or (maps <= big_maps() and not changed):
        return None
    os.makedirs(W, exist_ok=True)
    me = f"{time.time():.3f}_{os.getpid()}_{tag}"
    open(os.path.join(W, me), "w").write(f"{who} {maps} maps{' (changed probe)' if changed else ''}\n")
    t0, said = time.time(), 0
    try:
        while True:
            ws = _waiters()
            full = admit_full()  # 7 Nov: a deep pilot queue admits no new big read; 11 Nov: by drain time, with a reserve
            if ws and ws[0][3] == me and not full:  # head of the queue: take any free slot
                for i in range(n):
                    fd = os.open(os.path.join(D, f"slot{i}.lock"), os.O_RDWR | os.O_CREAT, 0o644)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError:
                        os.close(fd)
                        continue
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{os.getpid()} {tag} {who} {maps} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n".encode())
                    if time.time() - t0 > 5:
                        say(f"readslots: big-read slot {i + 1}/{n} after {time.time() - t0:.0f} s waiting")
                    return fd
            if time.time() - said > 600:
                pos = next((k for k, w in enumerate(ws) if w[3] == me), -1) + 1
                say(f"readslots: waiting for a big-read slot ({held()} of {n} held; pilot queue {qdepth()} items (admits at <= {qmax()}); "
                    f"place {pos} of {len(ws)}; READSLOTS=0 skips the cap)")
                said = time.time()
            time.sleep(5)
    finally:
        try:
            os.unlink(os.path.join(W, me))
        except OSError:
            pass


def status():
    n = slots()
    print(f"big-read slots: {n} (bq/bigread_max), big = > {big_maps()} maps or a changed probe; pilot queue {qdepth()} items, "
          f"new big reads wait above {qmax()} (bq/bigread_qmax) while one runs")
    for i in range(max(n, len([f for f in os.listdir(D) if f.startswith('slot')]) if os.path.isdir(D) else n)):
        p = os.path.join(D, f"slot{i}.lock")
        if not os.path.exists(p):
            print(f"  slot {i + 1}: free")
            continue
        fd = os.open(p, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            print(f"  slot {i + 1}: free")
        except OSError:
            print(f"  slot {i + 1}: {open(p).read().strip()}")
        finally:
            os.close(fd)
    if os.path.isdir(W):
        for k, (t, pid, tag, f) in enumerate(_waiters()):
            print(f"  wait {k + 1}: {tag} pid {pid} since {time.strftime('%H:%M:%SZ', time.gmtime(float(t)))}: {open(os.path.join(W, f)).read().strip()}")


if __name__ == "__main__":
    if sys.argv[1:] == ["status"]:
        status()
    else:
        sys.exit(__doc__)
