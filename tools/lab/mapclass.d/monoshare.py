"""monoshare (12 Nov, Builder/Deep KVM, spec_kvm_1112.md): the share of all camp gems that sit on monolith tiles (mapfeat.analyse()['mono'],
the same number mapfeat reports). KVM's class is one altar group AND monoshare >= .5: --class 'altgrp1:>=1,monoshare:>=0.5'.
Draft-time map features only, no map identity."""
import os
import sys

sys.path.insert(0, "/homes/USER/cambc/tools/lab")
import map26a  # noqa: E402
import mapfeat  # noqa: E402


def monoshare(path):
    return float(mapfeat.analyse(map26a.load(path))["mono"])


CLASSES = {"monoshare": monoshare}
