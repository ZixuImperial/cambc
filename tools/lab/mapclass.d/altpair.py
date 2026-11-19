"""altpair (b2002, 11 Nov; TWA1): altpair2 = number of altar-tile pairs at Chebyshev <= 2 (a body can stand within 1 of both).
Draft-time map feature only (altar tiles), no map identity."""
import os
import sys

sys.path.insert(0, '/homes/USER/cambc/tools/lab')
import map26a  # noqa: E402


def altpair2(path):
    a = list(map26a.load(path)['altar'])
    return sum(1 for i in range(len(a)) for j in range(i + 1, len(a))
               if max(abs(a[i][0] - a[j][0]), abs(a[i][1] - a[j][1])) <= 2)


CLASSES = {"altpair2": altpair2}
