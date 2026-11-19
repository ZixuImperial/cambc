#!/usr/bin/env python3
"""shipstack: a second shipcheck while the first runs. Tool builder, 2 Nov (Builder: a stacked bundle waited 21-71 min for the slot).

A bundle B armed with STACK_ON=A carries A's flips and plays against A's values (LIVEVALS = A's flips), so its read is B vs A: the
read it would have had if it had waited for A to ship. A chain up to MAX_STACK deep is allowed (C on B on A), never siblings: two bundles read against
A alone could not both ship, since the second would go live on code and flags nobody read together. B's trunk may be newer than A's: flag-0 code, with its own code row.
  - B never submits unless A is the live head, checked again inside the submit lock.
  - A ended without shipping: B's read is void, its legs stop, and B's own flips are armed again as a new bundle on what is live.
  - B's own FAIL stands whatever A does, unless A also failed: B vs A says nothing about B without A.
OFF unless the file stack_enabled exists in the shipcheck queue dir: fastship and shipwatch refuse STACK_ON without it."""
import fcntl
import os
import time

SWITCH = "stack_enabled"
MAX_STACK = 1  # Builder 3 Nov 13:20Z: back to 1 until parallel-vs-live lands (stack VOIDs: fin9x13 voided 4x, ~55% parent fail rate)


def enabled(q):
    return os.path.exists(os.path.join(q, SWITCH))


def parse_flips(s):
    """'K=V K2=V2' -> {K: V}; a lone '-' (armq's code-only line: no flips) is none. 3 Nov: '-' raised in armq's needed_donors on every step."""
    return dict(x.split("=", 1) for x in (s or "").split() if x != "-")


def own_flips(flips, livevals):
    """B's own flips: what it sets beyond the values it plays against."""
    return {k: v for k, v in flips.items() if livevals.get(k) != v}


def check(flips, livevals, a_flips, trunk, a_trunk):
    """-> why B cannot stack on A, or None."""
    lost = [k for k, v in a_flips.items() if flips.get(k) != v]
    if lost:
        return f"does not carry A's flips: {', '.join(lost)}"
    base = [k for k, v in a_flips.items() if livevals.get(k) != v]
    if base:
        return f"LIVEVALS lack A's flips: {', '.join(base)}"
    if not own_flips(flips, livevals):
        return "no flip of its own"
    return None


def chain(bot, repo):
    """The bundles this one stands on, nearest first."""
    out = []
    while True:
        try:
            m = [x.split("=", 1)[1].strip() for x in open(f"{repo}/bots/{bot}/SHIPCHECK") if x.startswith("STACK_ON=")]
        except OSError:
            return out
        if not m:
            return out
        bot = m[0]
        out.append(bot)


def depth(bot, repo, q):
    """How many of the bundles this one stands on are still running: one that has ended no longer limits the chain (2 Nov: a shipped A kept B counted as stacked, so nothing could stack on B)."""
    n = 0
    for a in chain(bot, repo):
        with open(os.path.join(q, f".shipwatch_{a}.lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return n
            except BlockingIOError:
                n += 1
    return n


def a_state(a, head, q):
    """live | running | failed. The lock goes first: A writes live.txt before its shipcheck lets the lock go, so a free lock followed
    by a head that is not A means A did not ship. head: a function, read only after the lock test. A must have started."""
    with open(os.path.join(q, f".shipwatch_{a}.lock"), "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            free = True
        except BlockingIOError:
            free = False
    if head() == a:
        return "live"
    return "failed" if free else "running"


def wait(a, head, q, timeout, poll=30):
    """-> live | failed | timeout: A's end, at most timeout seconds from now."""
    end = time.time() + timeout
    while True:
        st = a_state(a, head, q)
        if st != "running":
            return st
        if time.time() >= end:
            return "timeout"
        time.sleep(poll)


def decide(overall, st):
    """What B does once its legs are read: st is a_state's answer, or wait's when overall is PASS.
    -> submit | void_requeue (A failed: arm B's flips again) | void (no answer from A in time) | plain (B's own result stands)."""
    if st == "failed":
        return "void_requeue"
    if overall != "PASS":
        return "plain"
    return "submit" if st == "live" else "void"
