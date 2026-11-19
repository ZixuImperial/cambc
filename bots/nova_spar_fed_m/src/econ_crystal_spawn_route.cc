// econ_crystal_spawn_route.cc: The spawn crystal route: preparing, walking and landing it.
#include "econ_internal.h"
namespace nova::econ {
namespace {
bool spawn_crystal_prep_vec(long reserve)
{
	if (sc_stage >= 4)
		return sc_stage == 4;
	if (!M.has_home || !M.groups_ready() || G.w <= 0 || G.h <= 0)
		return false;
	const int w = G.w, h = G.h, n = std::max(w, h);
	static std::vector<std::uint16_t> pad, t2, t4, out;
	try
	{
		if (sc_stage == 0)
		{
			if (fuel() < reserve + 20000)
				return false;
			const std::size_t wh = static_cast<std::size_t>(w) * static_cast<std::size_t>(h);
			fx_buf.reset(new std::uint16_t[wh]);
			fx_win.reset(new std::uint16_t[wh]);
			M.f_home.export_linear_buffer(std::span<std::uint16_t>(fx_buf.get(), wh));
			for (const auto& c : M.camps) // a living camp holds its tile: no launch or landing there
				if (inb(c.pos))
					fx_buf[static_cast<std::size_t>(c.pos.y * w + c.pos.x)] = UNREACH;
			pad.assign(static_cast<std::size_t>(n + 6), UNREACH);
			t2.assign(static_cast<std::size_t>(n + 6), UNREACH);
			t4.assign(static_cast<std::size_t>(n + 6), UNREACH);
			out.assign(static_cast<std::size_t>(n + 6), UNREACH);
			sc_cur = 0;
			sc_stage = 1;
		}
		std::uint16_t* const buf = fx_buf.get();
		std::uint16_t* const win = fx_win.get();
		while (sc_stage == 1 && fuel() > reserve + 9000) // rows: the minimum along y (rows y-3..y+3 on the map)
		{
			const int y = sc_cur;
			const int y0 = std::max(0, y - 3), y1 = std::min(h - 1, y + 3);
			std::uint16_t* const o = win + static_cast<std::size_t>(y) * static_cast<std::size_t>(w);
			int x = 0;
			for (; x + 8 <= w; x += 8)
			{
				v128_t m = wasm_v128_load(buf + static_cast<std::size_t>(y0) * static_cast<std::size_t>(w) + x);
				for (int yy = y0 + 1; yy <= y1; ++yy)
					m = wasm_u16x8_min(m, wasm_v128_load(buf + static_cast<std::size_t>(yy) * static_cast<std::size_t>(w) + x));
				wasm_v128_store(o + x, m);
			}
			for (; x < w; ++x)
			{
				std::uint16_t m = buf[static_cast<std::size_t>(y0) * static_cast<std::size_t>(w) + x];
				for (int yy = y0 + 1; yy <= y1; ++yy)
					m = std::min(m, buf[static_cast<std::size_t>(yy) * static_cast<std::size_t>(w) + x]);
				o[x] = m;
			}
			if (++sc_cur >= h)
			{
				sc_cur = 0;
				sc_stage = 2;
			}
		}
		while (sc_stage == 2 && fuel() > reserve + 9000) // rows: then along x (spawn_crystal_prep's row pass, in place)
		{
			const int y = sc_cur;
			std::uint16_t* const row = win + static_cast<std::size_t>(y) * static_cast<std::size_t>(w);
			pad[0] = pad[1] = pad[2] = UNREACH;
			std::memcpy(pad.data() + 3, row, static_cast<std::size_t>(w) * sizeof(std::uint16_t));
			pad[static_cast<std::size_t>(w + 3)] = pad[static_cast<std::size_t>(w + 4)] = pad[static_cast<std::size_t>(w + 5)] = UNREACH;
			window_min_7(pad.data(), out.data(), w, t2.data(), t4.data());
			std::memcpy(row, out.data(), static_cast<std::size_t>(w) * sizeof(std::uint16_t));
			if (++sc_cur >= h)
			{
				sc_cur = 0;
				sc_land.clear();
				sc_stage = 3;
			}
		}
		const v128_t unr = wasm_i16x8_splat(static_cast<std::int16_t>(UNREACH));
		const v128_t need = wasm_i16x8_splat(static_cast<std::int16_t>(sc_hop0() + SC_CRY_MIN));
		while (sc_stage == 3 && fuel() > reserve + 9000) // the landing tiles: a row of tiles between fuel checks, and one before each candidate
		{
			const int total = w * h;
			const int stop = std::min(total, sc_cur + w);
			while (sc_cur < stop)
			{
				if (sc_cur + 8 <= stop)
				{
					// skip unless ft != UNREACH, hm != UNREACH and ft >= hm + 4 + SC_CRY_MIN (a saturated hm + 12 is UNREACH, which no ft other
					// than UNREACH reaches, so hm == UNREACH and hm near the top both drop out as in the scalar test)
					const v128_t ft = wasm_v128_load(buf + sc_cur), hm = wasm_v128_load(win + sc_cur);
					const v128_t ok = wasm_v128_andnot(wasm_u16x8_ge(ft, wasm_u16x8_add_sat(hm, need)), wasm_i16x8_eq(ft, unr));
					const std::uint32_t bits = wasm_i16x8_bitmask(ok);
					if (bits == 0)
					{
						sc_cur += 8;
						continue;
					}
					sc_cur += static_cast<int>(__builtin_ctz(bits));
				}
				const int x = sc_cur % w, y = sc_cur / w;
				const std::size_t i = static_cast<std::size_t>(sc_cur);
				const int ft = buf[i], hm = win[i];
				if (ft == UNREACH || hm == UNREACH || ft < hm + sc_hop0() + SC_CRY_MIN)
				{
					++sc_cur;
					continue;
				}
				if (fuel() < reserve + 5000)
					return false; // resumes at this tile
				bool dom = false;
#pragma clang loop unroll(full)
				for (const vec2 d : DIRS)
				{
					const vec2 q{ x + d.x, y + d.y };
					if (!inb(q))
						continue;
					const std::size_t k = static_cast<std::size_t>(q.y * w + q.x);
					if (buf[k] != UNREACH && static_cast<int>(win[k]) + 1 <= hm)
					{
						dom = true;
						break;
					}
				}
				++sc_cur;
				if (dom)
					continue;
				vec2 L{ -1, -1 };
				for (int dy = -3; dy <= 3 && L.x < 0; ++dy)
					for (int dx = -3; dx <= 3; ++dx)
					{
						const vec2 q{ x + dx, y + dy };
						if (inb(q) && static_cast<int>(buf[static_cast<std::size_t>(q.y * w + q.x)]) == hm)
						{
							L = q;
							break;
						}
					}
				if (L.x >= 0 && sc_land.size() < 2 * static_cast<std::size_t>(SC_LAND_CAP))
					sc_land.push_back({ vec2{ x, y }, L, static_cast<std::uint16_t>(hm), static_cast<std::uint16_t>(ft - hm) });
			}
			if (sc_cur >= total)
			{
				if (sc_land.size() > static_cast<std::size_t>(SC_LAND_CAP))
				{
					if (fuel() < reserve + 40000)
						return false; // the selection waits for a turn with the fuel
					std::nth_element(sc_land.begin(), sc_land.begin() + SC_LAND_CAP, sc_land.end(),
						[](const SCLand& a, const SCLand& b) { return a.gain > b.gain; });
					sc_land.resize(static_cast<std::size_t>(SC_LAND_CAP));
				}
				fx_buf.reset();
				fx_win.reset();
				sc_stage = 4;
				NLOG("r%d slot %d spawn crystal: %d landing tiles\n", now(), P.my_slot, static_cast<int>(sc_land.size()));
			}
		}
	}
	catch (...)
	{
		FXR_PASS();
		sc_land.clear();
		fx_buf.reset();
		fx_win.reset();
		sc_stage = 5; // the export failed: no routes this game
	}
	return sc_stage == 4;
}
// The landing list, resumable by rows and columns while more than `reserve` fuel remains; true once it is final. Stage 0 exports the
// spawn field (camps passable, as the spawn walks of the groups); 1 and 2 take its 7x7 window minimum (the nearest launch within 3);
// 3 keeps the landings 4 + SC_CRY_MIN+ walk rounds past their launch, minus those a neighbouring landing with a launch 1+ nearer
// reaches no later for every target.
bool spawn_crystal_prep(long reserve)
{
	if (sc_stage >= 4)
		return sc_stage == 4;
	return spawn_crystal_prep_vec(reserve);
}
// The best crystal route from our spawn toward field f (walk distances to the target), kept when it saves SC_CRY_MIN rounds over the
// spawn's walk on the same field (or the spawn has no walk there).
SCRoute spawn_crystal_route_on(const distance_field& f)
{
	SCRoute r;
	r.done = true;
	const FView v = fview(f);
	int walk = UNREACH;
	bbforeach(M.my_spawn, [&](vec2 p) { walk = std::min<int>(walk, v(p)); });
	int best = UNREACH;
	for (const auto& s : sc_land)
	{
		const int dt = v(s.T);
		if (dt == UNREACH)
			continue;
		const int c = static_cast<int>(s.off) + sc_hop(dt);
		if (c < best)
		{
			best = c;
			r.L = s.L;
			r.T = s.T;
			r.off = s.off;
		}
	}
	if (best != UNREACH && (walk == UNREACH || walk - best >= SC_CRY_MIN))
		r.cost = best;
	if (best != UNREACH)
	{
		r.save = walk == UNREACH ? 60000 : walk - best; // rounds this route saves over the spawn's own walk
		rh_any = rh_any || (r.cost != UNREACH && r.save >= RWK_TAB[3]);
	}
	return r;
}
// spawn_crystal_prep's landings are tiles the walk also reaches (it prices saved walk); on a map with no walkable altar the altar's side is
// reached by no walk, so its landings are added here once: each tile the altar walk reaches and the home walk does not, launched
// from the nearest home-walk tile within 3 (Chebyshev). The 8 cheapest (launch walk + hop + altar walk) are kept.
static bool nwc_land_done = false;
static void add_altar_side_landings(long reserve)
{
	static int row = 0; // resumes at this row on a later turn when the fuel is short
	static int fgr_col = 0; // BB14 FGR: resumes at this tile of the row
	static std::array<SCLand, 8> best{};
	static std::array<int, 8> bc{ UNREACH, UNREACH, UNREACH, UNREACH, UNREACH, UNREACH, UNREACH, UNREACH };
	if (nwc_land_done || !nwc_map() || !M.has_home)
		return;
	for (; row < G.h; ++row)
	{
		if (fuel() < reserve + 12000)
			return;
		const int y = row;
		for (int x = fgr_col; x < G.w; ++x)
		{
			if ((x & 7) == 0 && x > fgr_col && fuel() < reserve + 12000) // BB14 FGR: a check every 8 tiles (each up to ~1.5k)
			{
				BB14_CNT(4, true);
				fgr_col = x;
				return;
			}
			const vec2 T{ x, y };
			const std::uint16_t dt = dfget(M.f_altar, T);
			if (dt == UNREACH || dfget(M.f_home, T) != UNREACH)
				continue;
			vec2 L{ -1, -1 };
			int off = UNREACH;
			for (int dy = -3; dy <= 3; ++dy)
				for (int dx = -3; dx <= 3; ++dx)
				{
					const vec2 q{ x + dx, y + dy };
					if (!inb(q))
						continue;
					const int h = dfget(M.f_home, q);
					if (h < off && !bbget(M.block_camps, q))
					{
						off = h;
						L = q;
					}
				}
			if (L.x < 0)
				continue;
			const int c = off + sc_hop(dt);
			int wi = 0;
			for (int k = 1; k < 8; ++k)
				if (bc[static_cast<std::size_t>(k)] > bc[static_cast<std::size_t>(wi)])
					wi = k;
			if (c < bc[static_cast<std::size_t>(wi)])
			{
				bc[static_cast<std::size_t>(wi)] = c;
				best[static_cast<std::size_t>(wi)] = SCLand{ T, L, static_cast<std::uint16_t>(off), static_cast<std::uint16_t>(UNREACH - 1) };
			}
		}
		fgr_col = 0; // BB14 FGR: the next row starts at its first tile
	}
	nwc_land_done = true;
	for (int k = 0; k < 8; ++k)
		if (bc[static_cast<std::size_t>(k)] != UNREACH)
			sc_land.push_back(best[static_cast<std::size_t>(k)]);
}
void spawn_crystal_routes(long reserve)
{
	if (sc_stage == 4)
		add_altar_side_landings(reserve);
	if (sc_stage != 4 || sc_land.empty())
		return;
	if (sc_grp.size() != static_cast<std::size_t>(M.ng))
		sc_grp.assign(static_cast<std::size_t>(M.ng), SCRoute{});
	if (sc_rt_all_n == sc_grp.size() && (!(M.has_altar && (M.any_altar || (nwc_map() && nwc_land_done))) || sc_bank_f == &bank_field()))
		return; // the loop and both bank blocks below would do nothing
	const long per = 3000 + 25L * static_cast<long>(sc_land.size());
	if (recall_hop_early() && M.has_altar && (M.any_altar || (nwc_map() && nwc_land_done)) && sc_bank_f != &bank_field() && fuel() > reserve + per)
	{
		sc_bank_r = spawn_crystal_route_on(bank_field()); // the bank route first, not after every group's
		sc_bank_f = &bank_field();
		sc_any_r |= sc_bank_r.cost != UNREACH;
	}
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng) && fuel() > reserve + per; ++gi)
	{
		auto& r = sc_grp[gi];
		const auto& g = M.groups[gi];
		if (r.done || g.access != ACC_WALK || g.gems + g.gold <= 0)
			continue;
		const distance_field* f = mv::group_field_raw(static_cast<int>(gi));
		if (!f)
			continue;
		r = spawn_crystal_route_on(*f);
		sc_any_r |= r.cost != UNREACH;
	}
	if (M.has_altar && (M.any_altar || (nwc_map() && nwc_land_done)) && sc_bank_f != &bank_field() && fuel() > reserve + per)
	{
		sc_bank_r = spawn_crystal_route_on(bank_field());
		sc_bank_f = &bank_field();
		sc_any_r |= sc_bank_r.cost != UNREACH;
	}
	if (sc_rt_all_n != sc_grp.size())
	{
		bool all = true;
		for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng) && all; ++gi)
		{
			const auto& g = M.groups[gi];
			all = sc_grp[gi].done || g.access != ACC_WALK || g.gems + g.gold <= 0;
		}
		if (all)
			sc_rt_all_n = sc_grp.size();
	}
}
bool sc_can() { return crystals_carried() > 0 || W.gold >= 10; }
// On the spawn and able to hold a crystal: the choice prices the routes.
bool sc_choice_ok() { return sc_any_r && W.alive && W.on_spawn && now() >= sc_skip_until && sc_can(); }
bool sc_trip_live(int kind) { return SC.on && SC.kind == kind && !SC.used && now() - SC.last <= 2; }
void sc_end() { SC = SCTrip{}; }
// the last recall completed (not cancelled) and I am off the spawn with no trip started (no hop, judged once the trip ends) since:
// block recall.
static bool recall_hop_blocked()
{
	if (rhl_rec >= 0 && !S.recalling && !W.on_spawn && !(SC.on && !SC.used))
	{
		if (S.recall_cancel < rhl_rec)
			rhl_until = now() + RHL_TAB[2];
		rhl_rec = -1;
	}
	return now() < rhl_until;
}
// Rounds from here by a recall (7 with the arrival) plus the crystal hop on route r; UNREACH when it cannot start.
static int recall_hop_cost(const SCRoute& r, int psy)
{
	if (!rh_any || r.cost == UNREACH || r.save < RWK_TAB[3] || !W.alive || W.on_spawn || (SC.on && !SC.used) || now() < sc_skip_until || !sc_can())
		return UNREACH;
	if (now() - mf2_land_r <= 8 && (!prism_layer::recall_rhg_skip() || (PSY_TAB[1] & psy) != 0)) // MF2 bit 2 RHG (common.h): no change to Prism banking (owner rule); hop, recall, hop is a loop
		return UNREACH;
	return CSX_RCT() + static_cast<int>(r.cost); // the measured recall
}
// Walk rounds from here to a launch for the trip's landing (the launch field when built, else Chebyshev to L).
int spawn_crystal_walk_to_launch(vec2 L)
{
	if (sc_fl && sc_fl_at.x == SC.T.x && sc_fl_at.y == SC.T.y)
	{
		const int v = dfget_me(*sc_fl);
		if (v != UNREACH)
			return v;
	}
	return cheb(W.me.pos, L);
}
// compute_travel: 1 on the spawn (every route priced), 2 with a group trip under way (its group only), else 0.
int spawn_crystal_travel_mode()
{
	int mode = 0;
	if (W.alive)
		mode = sc_choice_ok() ? 1 : (sc_trip_live(0) ? 2 : 0);
	if (rh_any && mode == 0 && sc_any_r && W.alive && !W.on_spawn && !W.me.channeling() && !T.capturing && !T.engaged && now() >= sc_skip_until && sc_can() && !(recall_hop_blocked()) && recall_safe())
		mode = 3; // the groups a recall + hop reaches sooner
	if (mode)
		sc_wtrav.assign(static_cast<std::size_t>(M.ng), 0);
	else if (!sc_wtrav.empty())
		sc_wtrav.clear();
	return mode;
}
std::uint16_t spawn_crystal_travel(int gi, std::uint16_t v, int mode)
{
	int c = UNREACH;
	if (sc_trip_live(0) && SC.gi == gi)
		c = spawn_crystal_walk_to_launch(SC.L) + SC.rest;
	else if (mode == 1 && static_cast<std::size_t>(gi) < sc_grp.size() && sc_grp[static_cast<std::size_t>(gi)].cost != UNREACH)
	{
		const SCRoute& r = sc_grp[static_cast<std::size_t>(gi)];
		c = std::max(r.off, cheb(W.me.pos, r.L)) + r.cost - r.off;
	}
	else if (mode == 3 && static_cast<std::size_t>(gi) < sc_grp.size() && sc_grp[static_cast<std::size_t>(gi)].cost != UNREACH)
	{
		const int rc = CSX_RCT() + static_cast<int>(sc_grp[static_cast<std::size_t>(gi)].cost);
		if (sc_grp[static_cast<std::size_t>(gi)].save >= RWK_TAB[3] && rc + RWK_TAB[2] <= static_cast<int>(v))
			c = rc;
	}
	if (c >= static_cast<int>(v))
		return v;
	if (static_cast<std::size_t>(gi) < sc_wtrav.size())
		sc_wtrav[static_cast<std::size_t>(gi)] = v;
	return static_cast<std::uint16_t>(c);
}
// rate_for: a crew target is priced by my walk (the crew walks; my hop only makes me wait for it).
std::uint16_t spawn_crystal_crew_trav(int gi, std::uint16_t trav)
{
	const std::size_t i = static_cast<std::size_t>(gi);
	if (i < sc_wtrav.size() && sc_wtrav[i] > trav && i < travel.size() && travel[i] == trav)
		return sc_wtrav[i];
	return trav;
}
static std::uint16_t crystal_crew_travel(int gi, int self, std::uint16_t trav, std::uint16_t wt, const std::array<int, 8>& cl)
{
	int e = trav;
	const int sup = TM.sup;
	for (int s = 0; s < TM.n; ++s)
		if (s != self && s != sup && cl[static_cast<std::size_t>(s)] == gi)
			e = std::max(e, siege_slot_arrival_eta(s, gi));
	return static_cast<std::uint16_t>(std::min<int>(e, wt));
}
// want_bank's walk to the altar: on the spawn (or on a bank trip) the crystal route when it is shorter.
std::uint16_t spawn_crystal_bank_dist(std::uint16_t d)
{
	if ((!M.any_altar && !nwc_map()) || sc_bank_f != &bank_field())
		return d;
	int c = UNREACH;
	if (sc_trip_live(1))
		c = spawn_crystal_walk_to_launch(SC.L) + SC.rest;
	else if (sc_bank_r.cost != UNREACH && sc_choice_ok())
		c = std::max(sc_bank_r.off, cheb(W.me.pos, sc_bank_r.L)) + sc_bank_r.cost - sc_bank_r.off;
	return c < static_cast<int>(d) ? static_cast<std::uint16_t>(c) : d;
}
bool spawn_crystal_buy()
{
	if (crystals_carried() > 0)
		return true;
	if (!W.on_spawn || W.gold < 10 || cambc::detail::sdk_buy_consumable(RAW_CRYSTAL) != 0)
		return false;
	W.gold -= 10;
	crystal_count = 1;
	crystal_checked = now();
	return true;
}
// Start a trip from my spawn tile along route r toward field f (kind 0: group gi; 1: the bank) when it still saves SC_CRY_MIN over
// my walk and no dash route is as fast; buys the crystal.
bool spawn_crystal_start(int kind, int gi, const SCRoute& r, const distance_field& f)
{
	if (r.cost == UNREACH || !W.on_spawn || now() < sc_skip_until)
		return false;
	const vec2 me = W.me.pos;
	const int walk = dfget(f, me), dt = dfget(f, r.T);
	if (dt == UNREACH)
		return false;
	const int toL = std::max(r.off, cheb(me, r.L));
	const int c = toL + sc_hop(dt);
	if (walk != UNREACH && walk - c < SC_CRY_MIN)
		return false;
	if (cdx_hot_landing(r.T))
		return false; // CDX bit 4: no crystal bought for a contested landing
	if (dn::dasher())
	{
		if ((kind == 0 && M.has_thin && fuel() > 45000 && (walk == UNREACH))) // layer 0 = the walk
		{
			const bool cdx_ok = dn::prepare(kind == 0 ? gi : dn::GOAL_ALTAR, me, 30000); // CDX bit 1: every buy (the walk test above passed), group or bank
		}
		const int rl = dn::route_len(kind == 0 ? gi : dn::GOAL_ALTAR, me);
		if (rl != UNREACH && rl <= c)
			return false; // the dash route is as fast
		vec2 ca{ -1, -1 }, ct{ -1, -1 };
		if (walk != UNREACH && mv::thin_hole_plan(f, kind == 0 ? gi : -1, ca, ct, toL + 3) <= c) // The plan window reaches the hop launch.
		{
			CDW_CNT(0, true);
			mv::thin_hole_skip_crystal_set(&f, ca); // the walk on f takes the skip (step_field)
			return false; // a thin-hole skip (walk, dash, walk) arrives no later than the hop
		}
	}
	if (!spawn_crystal_buy())
		return false;
	sc_end();
	SC.on = true;
	SC.kind = kind;
	SC.gi = gi;
	SC.L = r.L;
	SC.T = r.T;
	SC.rest = sc_hop(dt);
	SC.last = now();
	SC.until = now() + 2 * toL + 8;
	NLOG("r%d slot %d spawn crystal trip %d g%d L %d,%d T %d,%d cost %d walk %d\n", now(), P.my_slot, kind, gi, r.L.x, r.L.y, r.T.x, r.T.y, c, walk);
	return true;
}
static void spawn_crystal_fail_mark()
{
	if (!SC.used)
		sc_skip_until = std::max(sc_skip_until, now() + RCL_SC_SKIP);
}
bool spawn_crystal_step(const distance_field& f)
{
	SC.last = now();
	if (SC.used || crystals_carried() <= 0 || now() > SC.until)
	{
		if (now() > SC.until)
			spawn_crystal_fail_mark(); // timed out with the crystal unused
		sc_end();
		return false;
	}
	const vec2 me = W.me.pos;
	auto foe_near = [&](vec2 p)
	{
		for (const auto* v : { &W.enemies, &W.enemies_far })
			for (const auto& e : *v)
				if (cheb(e.pos, p) <= 4)
					return true;
		return false;
	};
	if (cheb(me, SC.T) <= 3 && cdx_hot_landing(SC.T))
	{
		sc_end(); // CDX bit 4: a contested landing: the trip ends, the walk goes on
		return false;
	}
	if (cheb(me, SC.T) <= 3)
	{
		bool cxf_foe = false, cxf_me = false;   // a foe-near check fired this turn; a foe within 4 of me (no channel here now)
		if (cxf_key != SC.until)
		{
			cxf_key = SC.until; // a new trip: its own hold budget
			cxf_holds = 0;
		}
		cxf_me = foe_near(me); // A stun cancels the channel.
		cxf_foe = cxf_me || foe_near(SC.T);
		const FView v = fview(f);
		const int here = v(me);
		std::array<vec2, 3> tried{};
		int nt = 0;
		for (int a = 0; a < 3 && !cxf_me; ++a) // no channel with a foe within 4 of me (hold and re-check)
		{
			vec2 best{ -1, -1 };
			int bv = UNREACH;
			if (a == 0 && !bbget(M.block_camps, SC.T) && mv::free_tile(SC.T) && !(cxf_foe && foe_near(SC.T)))
			{
				best = SC.T;
				bv = v(SC.T);
			}
			else
				for (int dy = -3; dy <= 3; ++dy)
					for (int dx = -3; dx <= 3; ++dx)
					{
						const vec2 t{ me.x + dx, me.y + dy };
						if ((dx == 0 && dy == 0) || !inb(t) || bbget(M.block_camps, t) || !mv::free_tile(t))
							continue;
						if (cxf_foe && foe_near(t))
							continue; // foe-near landings are skipped, not the trip
						bool seen = false;
						for (int k = 0; k < nt; ++k)
							seen |= tried[static_cast<std::size_t>(k)].x == t.x && tried[static_cast<std::size_t>(k)].y == t.y;
						const int dv = v(t);
						if (!seen && dv < bv)
						{
							bv = dv;
							best = t;
						}
					}
			if (best.x < 0 || bv == UNREACH || (here != UNREACH && here - sc_hop(bv) < SC_CRY_MIN) || foe_near(best))
				break;
			tried[static_cast<std::size_t>(nt++)] = best;
			std::int32_t ok = 0;
			cancel_spin_before_action();
			if (cambc::detail::sdk_use_consumable(RAW_CRYSTAL, best.x, best.y, &ok) == 0 && ok)
			{
				crystal_count = 0;
				crystal_checked = now();
				mf2_land_r = now() + 3;
				SC.used = true;
				rhl_rec = -1; // the hop happened
				refresh_self(); // the channel: later steps of this turn see it
				NLOG("r%d slot %d spawn crystal %d,%d -> %d,%d\n", now(), P.my_slot, me.x, me.y, best.x, best.y);
				return true;
			}
		}
		if (cxf_foe)
		{
			// No foe-free landing pays now: hold at the launch and re-check next turn while the planned hop still saves SC_CRY_MIN after the
			// wait; then the foe abort (its block keeps a recall from coming back to the same foe).
			const int vt = v(SC.T);
			if (nt == 0 && cxf_holds < CXF_TAB[2] && W.can_move() && vt != UNREACH && (here == UNREACH || here - sc_hop(vt) - (cxf_holds + 1) >= SC_CRY_MIN))
			{
				++cxf_holds;
				return true;
			}
			sc_skip_until = now() + (RWK_TAB[1] != 0 && rh_any ? 30 : 10);
			sc_end();
			return false;
		}
		spawn_crystal_fail_mark(); // no landing
		sc_end();
		return false;
	}
	// Walk to the nearest tile within 3 of the landing (L, or any other free one): the launch field when it is built.
	bitboard goals;
	goals.draw_chebyshev(SC.T, 3.0f);
	goals &= ~M.block_camps;
	const bool ready = sc_fl && sc_fl_at.x == SC.T.x && sc_fl_at.y == SC.T.y;
	if (!ready && fuel() > 3L * G.w * G.h + 30000)
	{
		auto fl = std::make_unique<distance_field>();
		bitboard visited;
		fl->compute(M.block_camps & ~goals, goals, visited);
		sc_fl = std::move(fl);
		sc_fl_at = SC.T;
	}
	if (sc_fl && sc_fl_at.x == SC.T.x && sc_fl_at.y == SC.T.y && dfget(*sc_fl, me) != UNREACH && dfget(*sc_fl, me) > 0 && mv::step_field(*sc_fl))
		return true;
	if (mv::step_to_set(goals, 40))
		return true;
	if (now() < SC.until && W.can_move())
		return true; // no step this turn (fuel for the launch field, or a body in the way): hold rather than walk off
	if (now() >= SC.until)
		spawn_crystal_fail_mark(); // the hold ran out (not a turn I could not move in)
	sc_end(); // walk instead
	return false;
}
// target_turn's low-fuel cheap step waits: group gi's crystal trip runs, or may start from this spawn tile.
template <int DM>
bool spawn_crystal_hold(int gi)
{
	if (gi < 0)
		return false;
	if (sc_trip_live(0) && SC.gi == gi)
		return true;
	const bool hold = sc_choice_ok() && gi == T.target && T.crew <= 1 && static_cast<std::size_t>(gi) < sc_grp.size() &&
		   sc_grp[static_cast<std::size_t>(gi)].cost != UNREACH && M.groups[static_cast<std::size_t>(gi)].access == ACC_WALK;
	if (hold) // Hold only where a trip can start (spawn_crystal_start's own tests).
	{
		if (!W.on_spawn)
			return false;
		const SCRoute& r = sc_grp[static_cast<std::size_t>(gi)];
		const distance_field* f = mv::group_field_ready(gi);
		if (!f)
			return false;
		const int walk = dfget_me(*f), dt = dfget(*f, r.T);
		if (dt == UNREACH)
			return false;
		const int c = std::max(r.off, cheb(W.me.pos, r.L)) + sc_hop(dt);
		if (walk != UNREACH && walk - c < SC_CRY_MIN)
			return false;
		if (cdx_hot_landing(r.T))
			return false; // CDX bit 4: no hold for a contested landing
		if (dn::dasher())
		{
			const int rl = dn::route_len(gi, W.me.pos);
			if (rl != UNREACH && rl <= c)
				return false;
			vec2 ca{ -1, -1 }, ct{ -1, -1 };
			if (walk != UNREACH && mv::thin_hole_plan(*f, gi, ca, ct, std::max(r.off, cheb(W.me.pos, r.L)) + 3) <= c)
				return false;
		}
	}
	return hold;
}
// approach_group: a crystal trip to walkable group gi, started on the spawn when its route saves SC_CRY_MIN.
bool spawn_crystal_group_trip(int gi, const distance_field& f)
{
	if (SC.on && (SC.kind != 0 || SC.gi != gi || now() - SC.last > 2))
		sc_end();
	if (!SC.on && !(sc_any_r && W.on_spawn && gi == T.target && (T.crew <= 1) && static_cast<std::size_t>(gi) < sc_grp.size() && sc_can() && spawn_crystal_start(0, gi, sc_grp[static_cast<std::size_t>(gi)], f)))
	{
		return false; // CDX bit 2: hold on the spawn this turn
	}
	return spawn_crystal_step(f);
}
} // namespace
} // namespace nova::econ
