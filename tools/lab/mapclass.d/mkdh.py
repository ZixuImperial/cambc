"""mkdh (13 Nov, b2384 MKD, spec_mkd_1113.md): count of golem + monolith camp tiles on the map (camp types 4 monolith, 5 golem).
MKD's read class is 'heavy monster present': --class 'mkdh:>=1'. Draft-time map feature only, no map identity."""
import sys

sys.path.insert(0, "/homes/USER/cambc/tools/lab")
import map26a  # noqa: E402


def mkdh(path):
    return float(sum(1 for t in map26a.load(path)["camps"].values() if t in (4, 5)))


CLASSES = {"mkdh": mkdh}
