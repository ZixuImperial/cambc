"""condab.py --stat through an import, so the 1,800-line module comes from its compiled cache: 42 ms a game, not 77 (2 Nov)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import condab  # noqa: E402

sys.exit(condab.node_stat(*sys.argv[1:6]))
