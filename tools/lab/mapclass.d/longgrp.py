"""longgrp (b2220, RC C661 TRU oversample): the longest camp group's Chebyshev extent (max over 4-connected camp groups of
max(width, height) - 1). A group this long has members >= 12 tiles from its anchor when >= 12 (proxy: the bot's anchor is one camp).
--class 'longgrp:>=12'"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a


def _longgrp(path, _g=None):
    camps = map26a.load(path)["camps"]
    seen, best = set(), 0
    for c in camps:
        if c in seen:
            continue
        st, xs, ys = [c], [], []
        seen.add(c)
        while st:
            x, y = st.pop()
            xs.append(x)
            ys.append(y)
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in camps and q not in seen:
                    seen.add(q)
                    st.append(q)
        best = max(best, max(xs) - min(xs), max(ys) - min(ys))
    return float(best)


CLASSES = {"longgrp": _longgrp}
