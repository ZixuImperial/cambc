"""spawngap (13 Nov, TB for b2375 OSV; owner replay 01a1d286, 00rushbait_v2-like touching spawns): the Chebyshev gap between the two spawn
bounding rects (0 = touching or overlapping), from the map's spawn tiles (spawnA / spawnB). Class 'spawngap:<=5'. Draft-time, seat-free."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import map26a  # noqa: E402


def _rect(tiles):
    xs, ys = [x for x, _ in tiles], [y for _, y in tiles]
    return min(xs), min(ys), max(xs), max(ys)


def spawngap(path, _g=None):
    d = map26a.load(path)
    a, b = list(d.get("spawnA") or []), list(d.get("spawnB") or [])
    if not a or not b:
        return None
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    gx = max(0, max(ax0, bx0) - min(ax1, bx1) - 1)
    gy = max(0, max(ay0, by0) - min(ay1, by1) - 1)
    return max(gx, gy)


CLASSES = {"spawngap": spawngap}
