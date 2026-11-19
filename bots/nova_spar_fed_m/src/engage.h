#pragma once
// engage.h: Engage decisions: when a body starts a fight it can win. Integer switches only (never #if on a float); every switch at 0
// leaves the base behaviour byte for byte. combat_*.cc, econ_*.cc and brain_*.cc include this header. EN_ARRIVE: fights next to a
// worked group (my claim target's nearest camp within EN_NEAR, or a camp hitting me). The power estimate drains every ally's health
// by the awake camps that hit it, not only mine (assess and PEEL). The hysteresis that turns a FLEE back into a FIGHT (ratio 0.6+)
// and PEEL hold a fight there only at EN_HOLD_X100/100 or better, or when idle team mates within EN_HELP_R make it so; then the body
// calls them with the HELP event (FLEE_WISE's help_post) and help_join (called after DEFEND_TOGETHER) sends calm mates within
// EN_HELP_R one step at a time. Otherwise the body leaves at once. caught, CONTEST_HOLD and R3_CHAN are unchanged. TS_KEEP30:
// threat_seen keeps my own claim target of TS_GEMS+ gems while the bodies within TS_R of its camps favour us (combat::group_power,
// p_us^2 / p_them^2 >= TS_MIN_X100/100, both sides drained by the camps that hit them), and marks it for TS_MARK rounds so
// refresh_target does not re-choose it away. Neither fail_until nor enemy_seen is written for it (rate_for would read the group as
// failed, or cut it to x0.6, and the next choice would leave it); the other groups near the foes keep the old marks. CTH_GEOM:
// contested_gem_hold measures from the group's camp tiles (the nearest one), not from its anchor. WM_NOBACK: for WM_NB_ROUNDS after a flee,
// while a foe is in sight within WM_NB_R, target_turn does not take a farm step that closes in on the nearest such foe: a step that
// keeps progress and does not close in is taken instead, else the body holds. Not armed when TS_KEEP30 kept the target on that flee.
// WM_SWITCH: refresh_target's "better group" switch needs a margin of 1.3 + walked / (walked + left), and none is taken once the
// current target is within WM_SW_TRAVEL; the cur <= 0 switches stay. WM_WAIT: a plain group's incomplete crew is waited for at most
// WM_WAIT_CAP rounds unless a claimant is within WM_WAIT_CREW of me (siege and own-side elk crews keep their waits); the respawn
// filler is looked for every 2 rounds, not 4. TS_KEEP30 and WM_NOBACK are decided by one power test at the group: favourable -> the
// target is kept and the walk back is allowed; else the normal drop and no walk back. ENG_DIAG: debug builds only: firing counters,
// printed every 20 rounds as "ENGN r<round> s<slot> n0 .. n15" (a small integer writer, never printf).
#include "common.h"

#define EN_ARRIVE 1
#define EN_HOLD_X100 100 // hold below this ratio x 100 only with help
#define EN_HELP_R 16 // idle mates this close count as help, and answer the HELP call
#define EN_NEAR 8 // a worked group: my claim target's nearest camp within this

static_assert(!EN_ARRIVE || FLEE_WISE, "EN_ARRIVE calls FLEE_WISE's help_post and help_join");

namespace nova::combat {
bool help_called_this_round(); // assess held a fight on the strength of idle mates this round: brain posts HELP
}

#define ENG_CNT(k) ((void)0)
#define ENG_CNT_IF(c, k) ((void)0)
