# Decision trace (dgtrace)

WHY our bot did what it did, which replays don't record (Tool builder 2, 4 Nov; asked for by Top, Econ, Combat and Deep research).
Debug builds only: every record is written inside debug_block, so the RELEASE code is identical to the base (checked with wsec).
Trace games are games of the trace build itself (debug timing differs from release): use them to EXPLAIN, never to score.

## Quick start

Ready-made full trace bot: **nova_tb2t_full1** = nova_trunk_clean2 (= live v499 + play-identical cleanup) + every part below.

    # play your maps (Condor pilots, debug build, both seats; MAPLIST = one map name per line)
    python3 -I tools/lab/dgkit.py run nova_tb2t_full1 nova_spar_mite MAPLIST DIR
    # read: one reader per family, each with --us A|B --from R --to R and records_table(path, seat) for your own code
    python3 -I tools/lab/dgtrace/econ_read.py  DIR/rep/MAP__a.repl26a --us A [--tags et,er,eb,ec,...]   # targets, bank, recalls, crew waits
    python3 -I tools/lab/dgtrace/combat_read.py DIR/rep/MAP__a.repl26a --us A [--tags cb,cc,ck,cv,...]  # steps + branch chain, casts, foe knowledge, vetoes
    python3 -I tools/lab/dgtrace/mem_read.py    DIR/rep/MAP__a.repl26a --us A                          # team memory, knew v truth
    python3 -I tools/lab/tracejoin.py show DIR/rep/MAP__a.repl26a A nova_tb2t_full1                      # stance (as/tt) joined to turns
    # the same game's replay: rtable.py (tables), rvision.py / rmap.py (fog), replay.py
    # on a newer base: python3 -I tools/lab/dgkit.py make NEWBASE NEWNAME tools/lab/dgspec_full.py, then check the release
    #   code with pilotbuild.py + /data/USER/rswproj/wsec.py against NEWBASE's wasm (must say code IDENTICAL)
    # local engine instead of Condor (CPU-light): tools/cxe/dbgso.py BOT, games with CXE_STDOUT=1 (records in OUT.team-X.stdout)
Example run dirs: /data/USER/st/tb2t/econ/full1_nc2 (12 games v nochase2), full1_mite (00gemfight v the Mite spar).

## mem

Team memory (the 8 shared bytes) per body-turn: what each body read, wrote and came to believe. Replays hold actions only, so this trace is the only record.
Spec `tools/lab/dgtrace/mem.py` (written on nova_trunk_clean2 = live layout: PK_BITS 3, TM_BITS 1, TM2_BITS 159, CMP_BITS 1, FL_BITS 23; TMS, SH9, PG9, BCN, QKW bit 128 off). Reader `tools/lab/dgtrace/mem_read.py`.

    python3 -I tools/lab/dgkit.py make nova_trunk_clean2 NEWBOT tools/lab/dgtrace/mem.py
    python3 -I tools/lab/dgkit.py run NEWBOT nova_spar_nochase2 MAPLIST DIR
    python3 -I tools/lab/dgtrace/mem_read.py DIR                                  # per game: layout + sanity checks
    python3 -I tools/lab/dgtrace/mem_read.py DIR/rep/MAP__a.repl26a --from 180 --to 200 [--age 30]   # per round, knew v truth
    # Python: mem_read.records_table(path, 'A'|'B') -> decoded dicts in turn order; mem_read.Truth(replay.load(...)).state(g, r)

Release code stays identical (every hook in debug_block; wsec.py: code IDENTICAL). Debug timing differs from release: explain with it, never score.
Group indices are the engine's camp_groups() order (= replay gid; checked on 12 games by gems/gold/respawn).

### Records (values in order)
| tag | when (hook) | fields |
|---|---|---|
| ml | once per body, cmp_turn after cmp_init (econ.cpp) | ver=1, on (packed), ng, ns (= ng + altars), cells (HELP grid), hc (HELP cell size), ek, ebits (event bits; 0 under TM2 bit 16), cb (claim width), c2 (claim v2), ev2 (events in channel), var (TMS), top, spare_top (lowest bit used by spare fields), n, my_slot, t2, k (channel entries), ew (entry width), f_off, f_w (channel field), t2_ng, t2_rc, t2_rr, t2_c6, t2_rcrew, t2_rnews (code range starts), exact, cw, gw (CMP-only forms), qk_rbase, sh_rpos, groups, W, H, TM2, CMP, FL, TMS, PK (flag values), type0-5 (champion_type per slot), off0-5, wd0-5 (TMS widths) |
| mg | right after ml, one per group | g, gems, gold, respawn, anchor x, y |
| mr | every turn incl. dead, brain.cpp turn() right after comms::read() + econ::cmp_turn() | word (host 8 bytes, int64; byte 0 = low bits), alive, n, ev subject/type/stamp (comms::ev(): this body's own last legacy event), camp_n, camp_g0, camp_r0, camp_g1, camp_r1 (V.camp_*: group and respawn round of entries decoded this turn), touched (V.touched mask), fl_cell, fl_call, fl_r, fl_mine (comms::fl_call), then per slot 0-5: cg (group, -1), ce (engaged), ck (0 idle 1 dead 2 heading 3 engaged 4 fight 5 coming), cv (bucket: dead 1-3, ETA/forecast 0-3, stance x4 + HP band, ETA x16 + octant x2 + HP) |
| mw | every write: comms.cpp put_bits (packed) or the old byte writes | off, width, value, before, after (words; -1 on the old byte path) |
| me | econ.cpp t2_read, an entry that changed since this body's last decode | entry, raw (bit 0 parity, code = raw >> 1) |
| mt | econ.cpp t2_apply: a CAMP message into the team belief (tb_kind/tb_asof/post_lo = tm2_kind, tm2_asof, cmp_respawn) | g, kind (1 alive, 2 cleared & free, 3 timed), r_lo, r_hi (2^28 = open), p (post round from parity) |
| mk | econ.cpp t2_apply: the message also overwrote my own group memory (econ mem[g]) | g, kind, status (0 unknown 1 alive 2 cleared 3 respawn), respawn_at, is_target |

### Layout (nova_trunk_clean2; lines in bots/nova_trunk_clean2/src)
Host word, low bits first. Built by comms.cpp pk_init (109-189) from draft memory's group/altar counts, the same on every body all game.
- **Packed + TM2 (live, all team sizes):** no event slot (TM2 bit 16: ebits 0, comms.cpp 125-130). Claims from bit 0: n slots x cb bits, cb = bit_width(8 ng + 63) when n x cb + one channel entry fits (claim v2, 175-179), else bit_width(2 ng) (old code: 0 none, g+1 free, ng+g+1 engaged; 118). v2 code (comms.h 46-50, c2_view comms.cpp 86-106): 0 idle; 1-3 dead (respawn > 30, 11-30, <= 10); 4 + 4g + b heading to g (ETA here, <= 5, <= 15, > 15); 4 + 4ng + 4g + b engaged on g (forecast <= 3, <= 8, <= 20, > 20); 4 + 8ng + k in a fight (k = stance commit/hold/retreat x 4 + HP band); 16 + 8ng + k coming (ETA x 16 + octant x 2 + HP).
- **Channel** (econ.cpp cmp_init 14278-14330): K entries of ew = w + 1 bits, the top of the word (allocated down from bit 63: f_off = 64 - K ew), w = bits for t2_codes(ng) = 1 + 24 ng + 4 c6 + ng + 4 ns codes (comms.cpp 361; c6 = 6x6-tile cells). K = min(2, free bits / ew) (TM2 bit 128). Entry: bit 0 = parity of the post round (p = latest round <= now with that parity), code = rest (t2_read 14451-14544): 0 empty; 1 + 8g + s CAPTURE g, s 0-5 = pays in s rounds (respawn p + s + group respawn), 6 cleared & free, 7 alive; t2_rc + 16g + b RESPAWNING g in [p + T2_LO[b], p + T2_HI[b]] (econ.cpp 14372-14373); t2_rr + 4 cell + call FIGHT on the 6x6 grid (0 rally = HELP, 1 commit, 2 hold, 3 retreat); t2_rcrew + g CREW; t2_rnews + 4 subject + type old news (0 ENEMY, 1 ENEMIES, 2 TAKEN, 3 CLEARED; subject < ng group, else altar). Writers: t2_write (14895), t2_legacy_post (15111), fl_post (15164), cmp_write (15326); all go through spare_put -> put_bits (comms.cpp 202).
- **Measured on the 6 test maps:** T3 01gold-rush ng15: claims 3x8 at 0, K2 x 11 at 42, 18 free; T3 03ultrastarvation ng6: 3x7, K2 x 11 at 42, 21 free; T4 00vault ng7: 4x7, K2 x 10 at 44, 16 free; T5 00eight ng8: 5x7, K2 x 10 at 44, 9 free; T5 01elk-arena ng29 / 03fan ng32: 5x9, K1 x 12 at 52, 7 free.
- **C&I:** Cassi and Issac each hold a body slot, so a C&I team is laid out as its body count (n = team size + 1); TMS (off) would give Issac 1 bit and the healer bit_width(n). No C&I game in the test set.
- **Old byte layout** (no valid draft memory or > 126 groups): bytes 0-5 claim per slot (group + 1, bit 7 engaged), byte 6 event subject + 1, byte 7 type << 5 | round & 31 (comms.h 1-24).

### Checks (mem_read.py, 12 games v nochase2, nova_tb2t_mem1, /data/USER/st/tb2t/mem/r1)
- Every body of a team reads the same word in a round, given the writes before it: 50,697 of the 50,700 mr that follow another match the team word; 2 are 'mr_late' and 1 follows from them (a fuel-cut turn drains its records at the body's next turn start, so they sit later in the stream).
- Claims point at real groups (0 bad of 135,496). CLEARED/free beliefs v replay: 2,062 of 2,062 right (state at the start of r or r + 1).
- Timed beliefs v replay: 277 of 4,453 (6.2%) wrong; mostly capture countdowns posted at capture start whose capture then reset or ran shorter (03fan g28 r185: posted 'pays r190, respawn r230', real pay r188, respawn r228; re-posted right at r186).

### Not decoded / limits
Team belief is per body (each body's tb table, V.ev and fl_call come from its own decodes since its last turn; mr shows them as that body holds them). Writer-side state (t2_write priorities, pend_e re-send, intel news ranking) is not logged: mw shows only the bits written; mem_read names the field from its offset. CMP-only entry forms (CMP bit 8 / log, no TM2) decode in mem_read but their mk overwrite is not hooked (not live). SH9/QKW/PG9/BCN fields are off on this trunk (ml carries sh_rpos/qk_rbase; mem_read prints such codes raw).

## econ

WHY each body chose, dropped or kept a camp-group target, banked or didn't, and waited for a crew (replays hold only the actions).
Spec `tools/lab/dgtrace/econ.py` (written on nova_trunk_clean2), reader `tools/lab/dgtrace/econ_read.py`.

    python3 -I tools/lab/dgkit.py make nova_trunk_clean2 NEWBOT tools/lab/dgtrace/econ.py
    python3 -I tools/lab/dgkit.py run NEWBOT nova_spar_nochase2 MAPLIST DIR
    python3 -I tools/lab/dgtrace/econ_read.py DIR --check                         # per game: counts, ids, slot -> champion, drop/target reasons
    python3 -I tools/lab/dgtrace/econ_read.py DIR/rep/MAP__a.repl26a [--slot N] [--from R --to R] [--tags et,ed,eb,...]   # per-body timeline
    # Python: econ_read.records_table(path, 'A'|'B'|None) -> dicts (tag, r, slot, named fields, *_label for every site field)

Release code stays identical (every hook in debug_block; returns rewritten as `{ const bool dge_rv = (X); debug_block(...); return dge_rv; }`;
wsec.py on the release wasm: every section IDENTICAL, code and data). Debug timing differs from release: explain with it, never score.
Group ids are econ's M.groups index (= replay gid; the reader names them from the replay: gems/gold@centre).

**Sites.** A reason is a SITE: 300000 + the base econ.cpp line of the deciding `set_target`/`drop_target` call or `return`.
bots/NEWBOT/econ_sites.tsv names each (function, guarding condition, source); the reader finds it through DIR/man.txt.
Most used on the test set: set @7192 refresh_target `if (T.target < 0)` (new target after a drop/capture), @7218 rate switch
(`r > cur x sw`), @5789 contest zone crew, @11394 redirect_to_gate, @11776 SG3 sg_take, @7094 squad partner, @7199 squad stick,
@12860 respawn filler; drop @9854 capture done (bag/gold grew or group respawning), @12887 group seen dead, @12835 respawn wait
too long, @19188 threat_seen blacklist, @9625 cr_handoff, @10484 tank bail.

### Records (values in order; rates x1000 gem units/round, value x100, times x10, factors x1000)
| tag | when (hook) | fields |
|---|---|---|
| et | set_target with a new group | new, new_rate, crew, old, old_rate (stored at its last eval; -1 none), held, cur (old re-rated this turn; -1 not), sw (switch bar x100; -1), site, trig (refresh_target's due: 1 no target, 2 interval, 4 claims moved, 8 CMP/TM2; -1 not this turn), opening, ru, ru_rate (runner-up of this turn's best_group; -1), n_rated, n_cand, x, y, gems |
| er | after et: role 0 new, 1 old, 2 runner-up | role, g, age (rounds since that group's last rate_for by me; > 1000 = never), rate, crew, trav, wait (respawn), clear x10, value x100 (per body), t x10, pen x1000 (all factors), contest_f, seen_f (enemy-seen factor), others (claimants), recruits, rej (site of the rate_for `return -1`, 0 = rated), contest x100, status (0 unknown 1 alive 2 cleared 3 respawn), respawn_in, travel, ax, ay |
| ed | drop_target with a target | g, fail_rounds, site, status, respawn_in, engaged, capturing, waited, held, x, y, gems, hp_permille |
| ek | refresh_target refused a switch (best above the target, below cur x sw); once per (best, target) | best, best_rate, target, cur, sw, held |
| eo | opening simulation, my own row, top 5 | rank, g, rate, crew, walk, wait, clear, value, t, pen, contest_f, seen_f, others |
| es | opening row summary | slot_sim, best, best_rate, crew, n_rated, n_rej, n_cand, k |
| ep | opening result for me | choice, rate, crew, how (0 own row, 1 drafted by an earlier body's crew, 2 OP_JOIN), by_slot |
| eb | turn end, with a bag, when want_bank / bank_i / bs_turn ran or win_bank / bank_first acted; once per change of bag or sites | gems, wb_site, wb_res, d (altar walk), thr0 (route bar x10), thr1 (after LTB), thr2 (after Prism keep + QKW), td (DBK bar), p (DBK loss hazard x1000), thrD (after DBK), thr3 (after the threat cut = final bar unless C&I pair / latch), bi_site, bi_res (bank_i: walk or tribute; its TRIB_GUARD / TRIB_DOOM / PC_CHAN / lock returns are the 'why no tribute'), wn_site, wn_res, bf_site, bf_res, bs_site, target, capturing, prism, tributed_us, hp_permille, dbk_rate (own farm rate x1000) |
| ew | turn end: a crew wait starts or changes kind (target_turn) | g, kind (1 CF_RALLY gather, 2 SG3 gather, 3 crew incomplete, 4 crew ok, tank not started), waited, limit, claimants, away, here, ok, coming, started, rally_x, rally_y, x, y |
| ex | turn end: the wait stopped | g, kind, rounds, outcome (1 engaged, 2 left the target, 3 still the target), target, engaged |
| ec | econ.cpp start_recall, success path (after on_recall): every REAL recall start; SPIN_SELF display spins never pass there | rc_site (start_recall call; 2xxxxx = brain.cpp base line), gh_site (go_home caller this round, 0 none), cr_flags (capture_recall's reasons: 1 shop, 2 heal, 4 bank; -1 not a capture recall), hp_permille, gold, gems, target, target_rate, target_travel, target_status, target_respawn_in, target_d_home, home_dist, nearest_foe (-1 none), since_hurt, capturing, x, y. The reader adds `reason`: capture-timed (shop/heal/bank), shop, heal, low hp, travel (RECALL_TRAVEL / RT_SHOP / RTM / recall hop), bank, flee, stranded, idle (walled in / COVER heal), spawn chip, end hold |
| eC | turn end after an ec | out (1 home, 2 not home after 7 rounds = cancelled, 3 died, 4 another recall started), rounds, site, x, y |
| eg | once per game (slot 0, after its first choice) | g, gems, gold, respawn, ax, ay, hp, n_att, n_elk, n_heavy, d_home, d_enemy, d_altar (-1 unreachable), contest x100, access (0 walk 1 dash 2 crystal) |

### Checks (econ_read.py --check, 12 games v nochase2, nova_tb2t_econ5, /data/USER/st/tb2t/econ/run5)
- Release wasm of nova_tb2t_econ5 v nova_trunk_clean2: every section IDENTICAL (code 1,684,669 B, data too).
- ~500-1,500 econ records per team-game (et 100-410, er 200-730, eb 35-285, ed 64-283, ew/ex 4-30, eo/es/ep at the opening, eg = groups).
- Group ids: 0 beyond the map's groups; eg gems/gold/anchor match the replay's groups on all 6 maps; et (x, y) maps every slot to one champion.
- Capture drops (@9854) v replay captures: 670/824 within 1 round of our team's capture of that group, most of the rest 2-3 rounds after it (a crew mate seeing the respawn).
- Hand walk 00packs A Marcella r24-47: target g3 crew 2 (with Vendetta), Vendetta clears r24-30, she captures r42-47, drop @9854 r47 with bag 36, next target r48.

- Full bot nova_tb2t_full1 (dgspec_full.py: stance + econ + combat + mem): release code and data IDENTICAL to nova_trunk_clean2;
  14 games (/data/USER/st/tb2t/econ/full1_mite: 00gemfight v nova_spar_mite; full1_nc2: 6 maps v nova_spar_nochase2); econ_read,
  combat_read and mem_read all read them. Recalls: 602 ec, every one classed (no 'other'), 597 home, 4 superseded, 1 cancelled.
  Of the 121 capture-timed shop recalls at HP >= 90%, 26 bought nothing within 13 rounds (the 'no shop' recalls).

### Not traced / limits
Per-body only (each body logs its own choice; other bodies' rows of the opening simulation are not logged). A rate's parts come from that
body's last rate_for of the group (age field); bounds-pruned groups (never rated this turn) appear only as n_cand. hold_capture /
finish_first are not traced; recalls are (ec/eC), shop purchases are not (read them from the replay's gold). The turn-end hook joins dgkit's drain line right after the line holding planner::stat_turn_end (plain, or wrapped by
dgspec_trace.py: econ.py runs alone and inside dgspec_full.py); the recall marks are `(dge::rcw(CODE), start_recall())` /
`(dge::ghw(CODE), go_home())` comma calls of empty-in-release inline functions (4 in brain.cpp, 19 in econ.cpp); nothing is anchored in combat.cpp or comms.cpp.

## combat

WHY each body fought, fled, stepped, cast or held (replays hold only the actions). Spec `tools/lab/dgtrace/combat.py` (written on
nova_trunk_clean2), reader `tools/lab/dgtrace/combat_read.py`.

    python3 -I tools/lab/dgkit.py make nova_trunk_clean2 NEWBOT tools/lab/dgtrace/combat.py
    python3 -I tools/lab/dgkit.py run NEWBOT nova_spar_nochase2 MAPLIST DIR
    python3 -I tools/lab/dgtrace/combat_read.py DIR/rep/MAP__a.repl26a [--from R --to R] [--slot N] [--tags cb,cc,ck,...]   # per-turn fight timeline
    python3 -I tools/lab/dgtrace/combat_read.py sites NEWBOT CODE...      # what a site code is (function, line, label, source)
    # Python: combat_read.records_table(path, 'a'|'b') -> dicts (r, slot, tag, named fields; chain = call chain for actions)

**Release identity.** Hooks sit in debug_block, and the source wrappers (DGC_G, DGC_VT, DGC_WD, DGC_EMIT, DGC_RET in dgt_combat.h)
expand to the original tokens without CAMBC_DEBUG, so the release build compiles BASE's code (plus parentheses/braces): wsec.py on the
release wasm: every section IDENTICAL. (A first build that kept the wrappers as empty inline objects in release changed 68 functions:
inlining shifted. Keep new wrappers macro-gated.) Debug timing differs from release: explain with it, never score.

**Sites.** file*100000 + BASE line (1 combat.cpp, 2 brain.cpp, 3 move.cpp, 4 ward.cpp; 1/2 agree with dgspec_trace's codes).
bots/NEWBOT/combat_sites.tsv: code, kind (call / ret / veto / ward), file, line, function, callee, label, source.
- call: every call to an ACTING function (call-graph closure over BASE's .cpp: anything that reaches move_absolute, sdk_cast,
  sdk_attack, sdk_use_consumable or place_ward; 186 functions) is wrapped so it pushes its site on a per-turn stack while it runs.
  Action records carry the top 6 (s0 = innermost); the reader keeps the chain where each call's callee encloses the next
  (e.g. turn:1745>fight / fight:6342>step_to / step_to:1326>step_to_set / ... > try_move).
- ret: the returns of watched decision functions (fight, flee, lb_turn, ed_turn, crx_turn, parting_stun, xc_parting_stun, react_guard,
  hd_try, free_cast, spell_poke, kite_shot, continue_retreat, ffg_act, hidden_fire (false returns kept), ...; brain handle_low_hp, hold_capture, finish_first, help_join,
  ...; move escape, escape_toward, retreat_step, step_away, ring_escape, px_exit, fr1_step), and try_move / raw_cast / raw_attack /
  game_deny-family returns (their site = the refusal reason: BSH hold, LATCH_GUARD, EOX keep-out, engine refused, not ready, LB bit 32 ...).
- veto: nw_bad (NO_WAKE), hx_veto, di_land_bad, lb_land_bad (LETHAL_BURST bit 32), foe_guarded (LATCH_GUARD / lb zones), low_start_blocked,
  rtc_step_dies, mfb_mis_hold, eox_keep_out, bgx_dash_ok / hkl_mid_ok (false = veto): counted per turn when they fire.

### Records (values in order; only on hot turns = a foe in sight or in assess's foe list this round, or my health dropped this round (took_damage(1): hits from fog); cw always)
| tag | when (hook) | fields |
|---|---|---|
| cb | every try_move return (move.cpp) | site (ret: reason), ok, from x, y, to x, y, goal kind (1 step_to, 2 step_greedy, 3 retreat_step rally, 4 escape_toward rally, 5 fr1_step rally, 6 escape, 7 step_away, 8 ring_escape), goal x, y (-1 none), bsh_hold (BSH bit 1 held after a refused step revealed a foe), n refused tiles this turn, last refused x, y, lb_here, lb_dest, lb_alt (LETHAL_BURST sum of VISIBLE foes' next-turn damage on my tile / the step / the best other free neighbour), alt x, y, lb_cap (= the lethal bar), my ehp, stack depth, s0-s5 |
| cc | every raw_cast return | site (ret: reason), ok, slot, role mask (1 reset 2 dmg 4 aoe 8 cc 16 heal 32 dash 64 shield), kind (1 champion 2 camp 0 tile), target (0-99 enemy turn rank, 100+slot mate, 200 self, 1000+camp index, -1 tile), target x, y, target ehp, assess focus rank, my x, y, depth, s0-s5 |
| ca | every raw_attack return | site, ok, kind, target, x, y, ehp, focus, my x, y, depth, s0-s5 |
| cr | watched function returns: every true return; false returns only for fight, flee and the move.cpp escape family (others are cheap pre-checks: 10k/game) | site, value, depth, s0-s3 |
| ck | each foe in assess's list (before LOW_START's ls_ratio_near line, after the stance rules) | src (0 visible, 1 remembered sighting <= 4 rounds), enemy turn rank, champion_type (-1 remembered), x, y, age, hp, shield, maxhp, ehp, dps, burst, reach (remembered: as assess ages it, -1 = no threat), melee, gems, cd0, cd1 (-1 unknown), stunned, state bits, lb (lb_hit on me), lb_cast, d |
| cl | after the ck rows; also from an assess with no foe at all on a turn I was hit (nvis = nrem = 0: hit from fog) | n visible, n remembered, n shared (SH9), lb_here, lb_cast, lb_cap, my ehp, focus rank, stance, nearest, in_reach, caught, incoming, ratio x100, x, y |
| cf | fight(), after its step part (before `if (phm_stay)`) | focus rank, d, hold (the no-free-volley step guard), phm_stay, fsh_over, path_failed, acted, moved, cast, attacked, hd_now, focus ehp, danger_at(here) |
| ch | camp_abilities, a champion spell hold on | spell_hold (SPELL_HOLD), hold_nuke (MA_FOCUS / PO_HOLD_NUKE), cu_free, n seen, focus camp, ready0, ready1 |
| ce | turn end (next to planner::stat_turn_end); on hot turns, which include any turn I took damage this round (took_damage(1), so hits from fog are traced) | my champion_type, moved, attacked, cast, per slot 0/1: role, cooldown, ready (combat::ready), range, n targets in range (heal: hurt mates), nearest foe, ward cooldown, n vetoes, stack depth (0 = balanced), last watched return site, stance, focus, ehp, x, y, rdy0s, rdy1s (ready() per slot at the turn's FIRST assess, before its steps; -1 no assess). rdyN is ready() at turn END: 0 for a walk-excluding spell (Marcella's nuke, ...) once the body moved, so 'ready but walked instead' shows rdyN 0, cdN 0, rdyNs 1; the reader's NO CAST uses rdyNs |
| cv | turn end, when a veto fired | n, then (veto site, count) x 8 |
| cg | game_deny / gate_lock / deny_tribute / gd_follow / gd_stun_now / place_lock returns, with a visible foe tribute | site, value, foe rank, type, bag, channel rounds left, d, foe x, y, locks carried, tributed them, us, me channelling, stance, depth, s0-s5 |
| cw | every place_ward (ward.cpp) | site (bush_place / scout / react = WARD_REACT / bsx_ward / act pin), x, y, ok, my x, y, depth, s0-s3 |

### Checks (nova_tb2t_cmb4, 12 games v nochase2 on 00packs 03the-front 00eight 00anvil 03colosseum 00gemfight; /data/USER/st/tb2t/combat/run4)
- Release wasm of nova_tb2t_cmb4 v nova_trunk_clean2: all 14 sections IDENTICAL; also combined with dgspec_trace + mem (nova_tb2t_fullc1).
- 2,300-11,500 combat records per team-game (ck 17k, ce 11k, cl 9.5k, cr 7.7k, cb 7.5k, cf 3.5k, ca 3k, cw 1.6k, cc 1.3k over 12).
- Stack balanced: depth 0 at every turn end (10,995 of 10,995 ce).
- Foe knowledge v engine vision (rvision, the body's own turn-start view): visible ck sets inside the engine's view 2,788 of 2,793
  body-turns on 4 games of run3 (nova_tb2t_cmb3, same hooks; the 5 others: a second assess after a step in the same turn, vision has moved).
- Hand walk 00anvil A Ryth r84-89 v replay.py track: steps, hits and the stun-refused hit (raw_attack `!W.can_attack()`) match;
  r87-88 'NO CAST' aoe ready with Marcella alone in range is MIS1's veto (fight:6184, area stun held for stun-immune Marcella).

### Not traced / limits
Calls made from econ.cpp (farming steps, bank walks) are not marked, so their chains start at the move.cpp helper (econ's own trace
covers why). A NO CAST line names the last watched return, not always the gate: fight()'s inline cast conditions have no return of
their own (cf + cv + ch narrow it down). lb_* sums count VISIBLE foes only (as LETHAL_BURST does); remembered foes carry ehp/burst/
reach but no cooldowns or lb. game_deny's bag reads 0 for a far foe whose bag the engine hides (WDB reads it only beyond 9).
The stack can over-include a sibling call of the same full expression; the reader keeps only callee-encloses-next links.
In combined mode tools/lab/dgspec_full.py currently fails in econ.py (its turn-end anchor `planner::stat_turn_end(planned);\ndebug_block(drain)`
no longer exists after dgspec_trace wraps that line); combat + trace + mem combine cleanly.
- 4 Nov late (nova_tb2t_full3 = full spec: trace + econ + combat + mem; release all 14 sections IDENTICAL to clean2; runs
  /data/USER/st/tb2t/combat/runf3 (6 maps v nochase2) and runf3m (00gemfight v nova_spar_mite)): hit turns with no foe known
  (cl nvis = nrem = 0) now traced, 169-505 per team-game (3,889 over 14; most are camp hits, since took_damage counts any HP drop),
  each with ce + cl plus its ca/cb/cc/cr. 'Ready at turn start, not at turn end, no cast' slot-turns: 3,480 (the rdyNs fields).
  The champion-only FOG check could not run: rvision.js reads only replay version 2 and the 23:37Z cqbatch replays are version 3.
