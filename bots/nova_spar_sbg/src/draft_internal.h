#pragma once
// draft_internal.h: what every draft_*.cc file needs in scope: the headers it uses and its file-local macros. Draft design: maps
// first, the lineup judged as a whole, every pick with an explicit reason. Table: draft_value_table.h (generated, do not edit by
// hand). Lineup value in win-rate points, for our team size k on this map: u_c = A[k][c] + mt_c, mt_c = sum_f B[c][f] * z_f
// (team-size value + play shift, plus the replicated map slopes); V(L) = sum_{c in L} u_c + composition(L). z_f are the nine REPL
// map features (mapfeat.cc: gem and gold rate, groups, game length, attackers per group, altar walk, trip, solo-clearable share,
// Marcella's splash), clipped to the fit maps' range and standardised. Composition (pool + dev-twin joint fit, x0.75): no tank,
// Willow without a tank, Varg + HoR, Vendetta + Vesper Vale, 2+ economy carriers, Willow + HoR, and at 5v5 the roles covered times
// (b0 + b1 * game length). One hard rule (a mechanism, not a fit): at least 2 dash kits (HoR, VV, Ve, Re, CI) when no altar is
// walkable. No Marcella gate, no counter terms (enemy picks are read and logged only), no map identity, no fixed lineup or core.
// REACH: reachability overrides the fitted table. From fitfeat's reach classes (walk, dash closure, crystal, none) and the altars
// each class can bank at: V_W, V_D = value a walker / a dasher can turn into score (bankable gem rate + 0.1 x gold rate, farmable
// groups), s = 1 - V_W / V_D (the share only dashers realise), n_D = groups whose value only a dasher realises. (a) Dashers
// required: max(the old rule, min(k, n_D, round(k s))): the dash-only share needs its share of the team, one solo dasher per
// dash-only group at most. (b) Picks that cannot reach the map's resources lose their value: when walkers realise under REACH_EPS of
// what dashers realise and the spawns do not meet on foot (no fights), every non-dasher is a null pick (value 0, no map term, no
// roles, no composition term), and dashers beyond the dash-only groups are not admissible (they would only compete for the same solo
// trips and narrow routes). Null picks are ordered by their fitted value, a follower kit (ally heal: it walks after its partner and
// parks on routes it cannot cross) last. Four table terms that head to head on 89 fixed maps contradicted each other are 0 in
// draft_value_table.h: Willow's gem-rate slope, Willow + HoR (4v4, 5v5), Stellar's solo-share slope and Vendetta + Vesper Vale.
// Draft adjustments (switches in common.h): Willow - 1 pp; Marcella's team-size value - 6 pp (it was measured mostly against our own
// Marcella-less bots); Cassi & Issac + up to 9 pp by centrality (the share of the walkable value in one area both teams walk to
// alike: the extra body wins the first team fight); Vendetta + up to 3 pp by the chain share (value in groups of >= 2 members, all
// clusters, which she kills hit after hit, each kill resetting her cooldowns). The two features come from MapInfo (centrality_chain_features, turn
// 1, before mapfeat); not in REACH null mode. Pick rule: every lineup is enumerated once (792 at 5v5) and cached. The target T is,
// among admissible lineups within 1 pp of the best value (a near-tie the data cannot separate), the one with the largest validated
// map term. Each pick is T's open member with the largest explicit regret = V(T) - V(best admissible lineup with our picks but
// without it); the most irreplaceable champion goes first, the band's flexible members last. Values do not depend on the enemy, so
// turn 1 decides the whole order (make_plan) and later turns follow it, re-planning from the cache only when one of our picks left
// the plan. Fuel. A draft turn that runs out of fuel lets the engine pick the rest AT RANDOM, so every turn picks first and runs
// optional work only under measured guards. Turn 1 (about 1M): map analysis, features, the lineup cache, the plan, pick, draft
// memory encoded and submitted. Later turns (100k): the plan's next pick and the cached memory with the picks patched in. Fallbacks:
// team-size values without map features; then a greedy marginal value order with the dash rule (never a fixed list, never a random
// pick).
#include "draft.h"
#include "strategy.h"

#include "draft_value_table.h"
#include "draft_fit_features.h"
#include "mapfeat.h"
#include "mapinfo.h"
#include "plan.h"
#include "contest_zone.h"
#include "champ_prism.h"
#include "champions.h" // Kit layers (draft flags and hooks).
#include "rules.h" // For slot_cooldown.
namespace nova::econ { void om_write(std::vector<std::uint8_t>& mem); }

