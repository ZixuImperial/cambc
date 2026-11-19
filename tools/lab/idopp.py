#!/usr/bin/env python3
"""The fixed opponent for byte-identity and reference games: nochase2 while its folder exists, else the live bot (the owner deleted the spars on 8 Nov)."""
import os

REPO = "/homes/zw4424/cambc"


def id_opp():
    if os.path.isdir(f"{REPO}/bots/nova_spar_nochase2/src"):
        return "nova_spar_nochase2"
    try:
        return open("/data/zw4424/st/bq/live.txt").readline().split()[1]
    except (OSError, IndexError):  # a Condor node has no /data/zw4424: the shared bots/ folder
        return sorted(n for n in os.listdir(f"{REPO}/bots") if n.startswith("nova_"))[0]
