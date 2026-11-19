#pragma once
// champions.h: one file pair per champion: champ_NAME.h (rule card, passive, hooks and flags) and, when it has rules of its own,
// champ_NAME.cc. BASE: econ, combat, brain, move and plan hold the rules every body runs. A change there applies to every kit.
// CHAMPION FILE: a passive is defined here and shared code calls it; where a kit behaves differently the base asks a hook here. Hook
// groups, named the same in every file: WHO, BANK, RECALL, RETREAT, TARGETS, SHOP, FIGHT. To change a champion's rule, edit its
// file. Draft scores for champions live in draft_*.cc (draft decisions compare champions).
#include "champ_prism.h"
#include "champ_ci.h"
#include "champ_vesper.h"
#include "champ_tavi.h"
#include "champ_ryth.h"
#include "champ_marcella.h"
#include "champ_varg.h"
#include "champ_heart.h"
#include "champ_vendetta.h"
#include "champ_willow.h"
#include "champ_ren.h"
#include "champ_stellar.h"
