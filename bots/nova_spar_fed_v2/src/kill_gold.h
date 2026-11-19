#pragma once
// kill_gold.h: Kill-gold rules: when a kill's gold changes what we buy or chase. Int switches only (never #if on a float). EMB_MAP
// (econ_*.cc upitm_post): emblem families from map features, never the map's identity. On a gold-free map (every camp is a gem
// cluster: draft_prism.cc's own test) no camp pays gold, so Treasure (+10% gold, GameRules.md:306) only adds 10-11 gold a kill
// (BalanceChanges.md:1207-1219). There a Treasure entry of the build becomes Hunter (+50 a champion kill before gold bonuses,
// GameRules.md:313) for every non-healer; a family already in the build is not added twice (the entry is dropped). Prospector
// entries are untouched: its gem bonus is paid in engine 2.0.0 (holders x1.14 on gem-cluster gems). Prism's carry build (prism_carrier_shop_build)
// already takes Hunter on these maps.
