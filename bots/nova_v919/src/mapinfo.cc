// mapinfo.cc: Static map analysis shared by the draft and the champions. Computed once per bot instance, in fuel-bounded,
#include "mapinfo.h"

namespace nova {

MapInfo M;
std::uint16_t MapInfo::group_dist(const distance_field& f, const GroupI& g) const
{
	const FView v = fview(f);
	std::uint16_t best = UNREACH;
	for (int ci : g.members)
	{
		const std::uint16_t d = v(camps[static_cast<std::size_t>(ci)].pos);
		if (d < best)
			best = d;
	}
	return best;
}
std::uint16_t MapInfo::group_dist_blocked(const distance_field& f, const GroupI& g) const
{
	const FView v = fview(f);
	std::uint16_t best = UNREACH;
	for (const vec2 p : g.approach)
	{
		const std::uint16_t d = v(p);
		if (d < best)
			best = d;
	}
	return best == UNREACH ? UNREACH : static_cast<std::uint16_t>(best + 1);
}
void MapInfo::stage_terrain()
{
	PROF("terrain0");
	init_grid();
	PROF("grid");
	w = G.w;
	h = G.h;
	walls = cambc::map::walls();
	holes = cambc::map::holes();
	altars_bb = cambc::map::altars();
	bushes = cambc::map::bushes();
	my_spawn = cambc::map::spawn_region(team::ally);
	enemy_spawn = cambc::map::spawn_region(team::enemy);
	block = walls | holes | altars_bb | enemy_spawn;
	altars.clear();
	na = 0;
	bbforeach(altars_bb, [&](vec2 p) { AltarI a; a.pos = p; altars.push_back(a); ++na; });
	// Anchors: the spawn tile nearest the region's centre.
	auto anchor = [&](const bitboard& b)
	{
		long sx = 0, sy = 0, n = 0;
		bbforeach(b, [&](vec2 p) { sx += p.x; sy += p.y; ++n; });
		if (n == 0)
			return vec2{ 0, 0 };
		const vec2 c{ static_cast<int>(sx / n), static_cast<int>(sy / n) };
		vec2 best = c;
		int bd = BIG;
		bbforeach(b, [&](vec2 p) { const int d = cheb(p, c); if (d < bd) { bd = d; best = p; } });
		return best;
	};
	// MSY bit 1 (caller read the flag): each anchor coordinate is its mean rounded toward the map centre (a floor breaks the mirror).
	auto msy_round_anchors = [&](long sx, long sy, long ex, long ey, long n)
	{
		auto rc = [&](long s, int len) { const long q = s / n; return static_cast<int>((s % n != 0 && 2 * s < static_cast<long>(len - 1) * n) ? q + 1 : q); };
		home_anchor = vec2{ rc(sx, w), rc(sy, h) };
		enemy_anchor = vec2{ rc(ex, w), rc(ey, h) };
	};
	// A rectangle's anchor is its centroid, the enemy's the mirrored rectangle's.
	auto ssu_anchors = [&]() -> bool
	{
		long sx = 0, sy = 0, n = 0;
		int x0 = BIG, x1 = -1, y0 = BIG, y1 = -1;
		bbforeach(my_spawn, [&](vec2 p) {
			sx += p.x;
			sy += p.y;
			++n;
			x0 = std::min(x0, p.x);
			x1 = std::max(x1, p.x);
			y0 = std::min(y0, p.y);
			y1 = std::max(y1, p.y);
		});
		if (n == 0 || n != static_cast<long>(x1 - x0 + 1) * static_cast<long>(y1 - y0 + 1))
			return false;
		const auto sym = cambc::map::symmetry();
		const bool fx = sym != cambc::symmetry::vertical, fy = sym != cambc::symmetry::horizontal;
		const int ex0 = fx ? w - 1 - x1 : x0, ey0 = fy ? h - 1 - y1 : y0;
		const int ex1 = ex0 + (x1 - x0), ey1 = ey0 + (y1 - y0);
		if (ex0 < 0 || ey0 < 0 || ex1 >= w || ey1 >= h || static_cast<long>(enemy_spawn.count()) != n)
			return false;
		const BView ve = bview(enemy_spawn);
		long ex = 0, ey = 0;
		for (int y = ey0; y <= ey1; ++y)
			for (int x = ex0; x <= ex1; ++x)
			{
				if (!ve(vec2{ x, y }))
					return false;
				ex += x;
				ey += y;
			}
		ssu_x0 = x0;
		ssu_x1 = x1;
		ssu_y0 = y0;
		ssu_y1 = y1;
		home_anchor = vec2{ static_cast<int>(sx / n), static_cast<int>(sy / n) };
		enemy_anchor = vec2{ static_cast<int>(ex / n), static_cast<int>(ey / n) };
		msy_round_anchors(sx, sy, ex, ey, n); // MSY bit 1: round toward the centre, so the two anchors mirror
		return true;
	};
	if (!ssu_anchors())
	{
		home_anchor = anchor(my_spawn);
		enemy_anchor = anchor(enemy_spawn);
	}
	PROF("terrain");
}

// map::camp_groups() spends ~190-300 fuel a camp building SDK objects (31k to 56k on big maps) around one batched engine read of
// ~0.3-0.5k. These are the same words, parsed as the SDK's camp-group loader parses them, in light records.
cambc::camp_stats MapInfo::FxCamp::base_stats() const
{
	cambc::detail::camp_design value{};
	cambc::detail::check(cambc::detail::sdk_camp_design(static_cast<std::int32_t>(kind()), &value));
	return value.base_stats;
}
// X3I bits 8 LCX1 / 16 LCP1 (X207): load_camp_groups_raw without the zero-filled vector and without the counting pass.
void MapInfo::load_camp_groups_raw_x2i()
{
	std::vector<std::uint32_t> words;
	std::unique_ptr<std::uint32_t[]> lcx_w; // X3I bit 8 LCX1: the words, not zero-filled
	const std::uint32_t* wp = nullptr;
	std::uint32_t count{};
	{
		std::uint32_t probe[1];
		cambc::detail::check(cambc::detail::sdk_map_camp_layout(probe, 0, &count));
		lcx_w.reset(new std::uint32_t[count > 0 ? count : 1]);
		if (count > 0)
			cambc::detail::check(cambc::detail::sdk_map_camp_layout(lcx_w.get(), count, &count));
		wp = lcx_w.get();
	}
	fx_groups_.clear();
	fx_camps_.clear();
	fx_groups_.reserve(count / 5);
	fx_camps_.reserve(count / 4);
	const std::uint32_t* const lcw = wp;
	for (std::size_t i = 0; i + 5 <= count;)
	{
		FxGroup g;
		g.h = lcw[i];
		g.gold = lcw[i + 1];
		g.gems = lcw[i + 2];
		g.respawn = static_cast<std::int32_t>(lcw[i + 3]);
		const std::uint32_t size = lcw[i + 4];
		i += 5;
		const std::size_t first = fx_camps_.size();
		for (std::uint32_t m = 0; m < size && i + 4 <= count; ++m, i += 4)
		{
			FxCamp c;
			c.h = lcw[i];
			c.t = lcw[i + 1];
			c.x = static_cast<std::int32_t>(lcw[i + 2]);
			c.y = static_cast<std::int32_t>(lcw[i + 3]);
			fx_camps_.push_back(c);
		}
		g.cs = std::span<const FxCamp>(fx_camps_.data() + first, fx_camps_.size() - first);
		fx_groups_.push_back(g);
	}
}

void MapInfo::load_camp_groups_raw()
{
	return load_camp_groups_raw_x2i();
}

bool MapInfo::step_groups(long reserve)
{
	if (fx_raw_)
		return step_groups_t(fx_groups_, reserve);
	return step_groups_t(raw_, reserve);
}
template <class GV>
bool MapInfo::step_groups_t(const GV& raw, long reserve)
{
	if (cursor_ == 0)
	{
		camp_at.assign(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), -1);
		camps.clear();
		groups.clear();
		ng = 0;
		nc = 0;
		std::size_t total = 0;
		for (const auto& g : raw)
			total += g.camps().size();
		camps.reserve(total);
		groups.reserve(raw.size());
		camp_tiles = bitboard{};
		total_gems = total_gold = 0;
	}
	auto& t_hp = t_hp_;
	auto& t_str = t_str_;
	auto& t_reach = t_reach_;
	auto& t_known = t_known_;
	const BView vb = bview(block);
	while (cursor_ < raw.size())
	{
		if (fuel() < reserve) // Checked for every group: on a map with 96 camps, four groups between checks would overrun the reserve.
			return false;     // cost over the 39k margin and emptied the first play turn (each body then lost a turn)
		const auto& g = raw[cursor_];
		groups.emplace_back();
		++ng;
		GroupI& gi = groups.back();
		gi.idx = static_cast<int>(cursor_);
		gi.handle = static_cast<std::uint32_t>(static_cast<cambc::handle_camp_group_t>(g));
		gi.gems = static_cast<int>(g.gem_value());
		gi.gold = static_cast<int>(g.gold_value());
		gi.respawn = g.max_respawn_timer();
		const auto members = g.camps();
		gi.members.reserve(members.size());
		gi.approach.reserve(8);
		float best_str = -1;
		for (const auto& c : members)
		{
			const int idx = static_cast<int>(camps.size());
			camps.emplace_back();
			++nc;
			CampI& ci = camps.back();
			ci.group = gi.idx;
			ci.type = c.kind();
			ci.pos = c.spawn_position();
			ci.handle = static_cast<std::uint32_t>(static_cast<cambc::handle_camp_t>(c));
			const auto ti = static_cast<std::size_t>(ci.type);
			if (ti < t_known.size())
			{
				if (!t_known[ti])
				{
					const auto st = c.base_stats();
					t_hp[ti] = st.base_health;
					t_str[ti] = st.base_strength;
					t_reach[ti] = st.base_attack_range;
					t_known[ti] = true;
				}
				ci.hp = t_hp[ti];
				ci.str = t_str[ti];
				ci.reach = ci.str > 0 ? t_reach[ti] : 0;
			}
			gi.members.push_back(idx);
			++gi.nm;
			gi.bx0 = std::min(gi.bx0, ci.pos.x);
			gi.by0 = std::min(gi.by0, ci.pos.y);
			gi.bx1 = std::max(gi.bx1, ci.pos.x);
			gi.by1 = std::max(gi.by1, ci.pos.y);
			if (inb(ci.pos))
			{
				camp_at[static_cast<std::size_t>(ci.pos.y * w + ci.pos.x)] = static_cast<std::int16_t>(idx);
				bbset(camp_tiles, ci.pos);
			}
			gi.hp += ci.hp;
			if (ci.str > 0)
			{
				gi.str_sum += ci.str;
				if (ci.str > gi.str_max)
					gi.str_max = ci.str;
				if (ci.reach > gi.reach_max)
					gi.reach_max = ci.reach;
				++gi.n_att;
				gi.att.emplace_back(ci.hp, ci.str);
			}
			else
				++gi.n_clu;
			switch (ci.type)
			{
			case cambc::camp_type::monolith: ++gi.n_mono; break;
			case cambc::camp_type::golem: ++gi.n_golem; break;
			case cambc::camp_type::elk: ++gi.n_elk; break;
			case cambc::camp_type::wolf: ++gi.n_wolf; break;
			default: break;
			}
			if (ci.str > best_str)
			{
				best_str = ci.str;
				gi.anchor = ci.pos;
			}
			// Approach tiles (static terrain only; other camps filtered later): the first members suffice.
			if (gi.members.size() <= 2)
				for (const vec2 d : DIRS)
				{
					const vec2 q = ci.pos + d;
					if (inb(q) && !vb(q))
						gi.approach.push_back(q);
				}
		}
		if (gi.att.size() > 1)
			std::sort(gi.att.begin(), gi.att.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
		const std::size_t nm = gi.members.size();
		if (nm <= 6)
			for (std::size_t a = 0; a < nm; ++a)
			{
				int n = 0;
				const vec2 pa = camps[static_cast<std::size_t>(gi.members[a])].pos;
				for (std::size_t b = 0; b < nm; ++b)
					if (cheb(pa, camps[static_cast<std::size_t>(gi.members[b])].pos) <= 1)
						++n;
				if (n > gi.pack)
					gi.pack = n;
			}
		else
			gi.pack = 4;
		total_gems += static_cast<float>(gi.gems);
		total_gold += static_cast<float>(gi.gold);
		++cursor_;
	}
	return true;
}
bool MapInfo::step_approach(long reserve)
{
	// Drop approach tiles that are other camps' tiles (camps block walking while alive).
	const BView vc = bview(camp_tiles);
	while (cursor_ < groups.size())
	{
		if (fuel() < reserve)
			return false;
		auto& g = groups[cursor_];
		std::size_t k = 0;
		for (std::size_t i = 0; i < g.approach.size(); ++i)
			if (!vc(g.approach[i]))
				g.approach[k++] = g.approach[i];
		g.approach.resize(k);
		++cursor_;
	}
	altar_adj = bitboard{};
	altar_adj_all = bitboard{};
	gate_groups.clear();
	gate_mask.clear(); // b2402 GTM1
	if (static_cast<int>(altars.size()) >= APF_TAB[1])
	{
		if (fuel() < 12000) // the boards below; resumes next turn (cursor_ is past the filter)
			return false;
		bitboard nb = altars_bb.shift_right(1) | altars_bb.shift_right(-1) | altars_bb;
		nb |= nb.shift_up(1) | nb.shift_up(-1);
		altar_adj_all = nb & ~block;
		altar_adj = altar_adj_all & ~block_camps;
		const bitboard gt = altar_adj_all & camp_tiles;
		if (bbany(gt))
		{
			bitboard ga = gt.shift_right(1) | gt.shift_right(-1) | gt;
			ga |= ga.shift_up(1) | ga.shift_up(-1);
			ga &= altars_bb;
			const BView vga = bview(ga), vgt = bview(gt);
			for (const auto& a : altars)
			{
				if (!vga(a.pos))
					continue;
				if (fuel() < 5000)
					return false; // resumes next turn from a clean gate_groups (the next call clears it)
				for (const vec2 d : DIRS)
				{
					const vec2 p = a.pos + d;
					if (!inb(p) || !vgt(p))
						continue;
					const int ci = camp_index(p);
					if (ci >= 0)
					{
						const int gi = camps[static_cast<std::size_t>(ci)].group;
						if (GTM_ON(1) && GTM_ON(2) && gi >= 0 ? !gtm_has(gi) : std::find(gate_groups.begin(), gate_groups.end(), gi) == gate_groups.end()) // b2402 GTM2
						{
							gate_groups.push_back(gi);
							if (gi >= 0)
								gtm_put(gi); // b2402 GTM1
						}
					}
				}
			}
		}
		return true;
	}
	const BView vb = bview(block_camps), vblock = bview(block);
	for (const auto& a : altars)
		for (const vec2 d : DIRS)
		{
			const vec2 p = a.pos + d;
			if (!inb(p) || vblock(p))
				continue;
			bbset(altar_adj_all, p);
			if (!vb(p))
				bbset(altar_adj, p);
			else
			{
				const int ci = camp_index(p);
				if (ci >= 0)
				{
					const int gi = camps[static_cast<std::size_t>(ci)].group;
					if (GTM_ON(1) && GTM_ON(2) && gi >= 0 ? !gtm_has(gi) : std::find(gate_groups.begin(), gate_groups.end(), gi) == gate_groups.end()) // b2402 GTM2
					{
						gate_groups.push_back(gi);
						if (gi >= 0)
							gtm_put(gi); // b2402 GTM1
					}
				}
			}
		}
	return true;
}
bool MapInfo::step_distances(long reserve)
{
	if (phase_ == 0)
	{
		if (!distances_known_)
			while (cursor_ < groups.size())
			{
				if ((cursor_ & 3) == 0 && fuel() < reserve)
					return false;
				auto& g = groups[cursor_];
				if (has_home)
					g.d_home = group_dist(f_home, g);
				if (has_enemy)
					g.d_enemy = group_dist(f_enemy, g);
				if (!has_home)
					g.access = ACC_WALK;
				else if (g.d_home != UNREACH)
					g.access = ACC_WALK;
				else if (has_dash && group_dist(f_home_dash, g) != UNREACH)
					g.access = ACC_DASH;
				else
					g.access = ACC_TP;
				if (g.d_home != UNREACH && g.d_enemy != UNREACH)
					g.contest = static_cast<float>(g.d_home) / std::max(1.0f, static_cast<float>(g.d_home + g.d_enemy));
				else if (g.d_home != UNREACH)
					g.contest = has_enemy ? 0.0f : 0.5f;
				else
					g.contest = 1.0f;
				++cursor_;
			}
		cursor_ = 0;
		phase_ = 1;
	}
	if (phase_ == 1)
	{
		if (!distances_known_)
		{
			if (fuel() < reserve + 400L * static_cast<long>(altars.size()))
				return false;
			const FView vh = fview(f_home), ve = fview(f_enemy), vcb = fview(f_home_cb), vd = fview(f_home_dash);
			for (auto& a : altars)
			{
				std::uint16_t dh = UNREACH, de = UNREACH, dcb = UNREACH, dd = UNREACH;
				for (const vec2 d : DIRS)
				{
					const vec2 p = a.pos + d;
					if (!inb(p))
						continue;
					if (has_home)
						dh = std::min(dh, vh(p));
					if (has_enemy)
						de = std::min(de, ve(p));
					if (has_home_cb)
						dcb = std::min(dcb, vcb(p));
					if (has_dash)
						dd = std::min(dd, vd(p));
				}
				a.d_home = dh;
				a.d_enemy = de;
				a.gated = has_home_cb && dh != UNREACH && dcb == UNREACH;
				a.access = dh != UNREACH ? ACC_WALK : (dd != UNREACH ? ACC_DASH : ACC_TP);
			}
		}
		phase_ = 2;
	}
	while (cursor_ < groups.size())
	{
		if ((cursor_ & 7) == 0 && fuel() < reserve)
			return false;
		auto& g = groups[cursor_];
		if (!want_dash && has_altar) // want_dash: set only by the draft's analysis, so this is play only
		{
			const std::uint16_t d0 = group_dist_blocked(f_altar, g); // Only groups the approach misses.
			if (d0 != UNREACH)
			{
				g.d_altar = d0;
				++cursor_;
				continue;
			}
			if (g.members.size() > 16 && fuel() < reserve + 300L * static_cast<long>(g.members.size()))
				return false;
			const FView va = fview(f_altar);
			const BView vbc = bview(block_camps);
			std::uint16_t best = UNREACH;
			for (const int ci : g.members)
			{
				const vec2 c = camps[static_cast<std::size_t>(ci)].pos;
				for (const vec2 d : DIRS)
				{
					const vec2 q = c + d;
					if (!inb(q) || vbc(q))
						continue;
					const std::uint16_t v = va(q);
					if (v < best)
						best = v;
				}
			}
			g.d_altar = best == UNREACH ? UNREACH : static_cast<std::uint16_t>(best + 1);
		}
		else
			g.d_altar = has_altar ? group_dist_blocked(f_altar, g) : UNREACH;
		++cursor_;
	}
	return true;
}
bool MapInfo::init(long reserve)
{
	try
	{
		while (stage_ < ST_DONE)
		{
			const long f = fuel();
			bitboard visited;
			switch (stage_)
			{
			case ST_NONE:
				if (f < reserve + 30000)
					return ready();
				stage_terrain();
				stage_ = ST_TERRAIN;
				break;
			case ST_TERRAIN:
				if (f < reserve + 45000)
					return ready();
				fx_raw_ = true; // Light camp records.
				if (fx_raw_)
					load_camp_groups_raw();
				else
					raw_ = cambc::map::camp_groups();
				PROF("camp_groups");
				cursor_ = 0;
				stage_ = ST_LOADED;
				break;
			case ST_LOADED:
				if (!step_groups(reserve + 4000))
					return ready();
				PROF("groups");
				raw_.clear();
				raw_.shrink_to_fit();
				if (fx_raw_)
				{
					std::vector<FxGroup>().swap(fx_groups_);
					std::vector<FxCamp>().swap(fx_camps_);
				}
				block_camps = block | camp_tiles;
				cursor_ = 0;
				stage_ = ST_GROUPS;
				break;
			case ST_GROUPS:
				if (!step_approach(reserve + 3000))
					return ready();
				PROF("approach");
				stage_ = ST_APPROACH;
				break;
			case ST_APPROACH:
				if (!has_altar) // Once (the stage resumes on a later call until the gating work is done).
				{
					if (f < reserve + field_cost())
						return ready();
					f_altar.compute(block_camps, altar_adj, visited);
					PROF("f_altar");
					has_altar = true;
					any_altar = false;
					{
						const FView va = fview(f_altar);
						bbforeach(my_spawn, [&](vec2 p) { if (va(p) != UNREACH) any_altar = true; });
					}
					ring_todo = !any_altar && gate_groups.empty() && bbany(altar_adj);
					open_todo = !any_altar;
				}
				// The ring scan and the open field (one field each), resumed on the next call when the fuel is short, never skipped (on a 69x69
				// map a skipped scan meant the ring was never found).
				if (!gate_step(reserve))
					return ready();
				stage_ = ST_READY;
				break;
			case ST_READY:
				if (pause_at_ready || f < reserve + field_cost())
					return ready();
				f_home.compute(block, my_spawn, visited);
				PROF("f_home");
				has_home = true;
				stage_ = ST_HOME;
				break;
			case ST_HOME:
				if (!distances_known_ && !lean)
				{
					if (f < reserve + field_cost())
						return ready();
					f_enemy.compute(walls | holes | altars_bb | my_spawn, enemy_spawn, visited);
					PROF("f_enemy");
					has_enemy = true;
				}
				stage_ = ST_ENEMY;
				break;
			case ST_ENEMY:
				if (!distances_known_ && !lean)
				{
					if (f < reserve + field_cost())
						return ready();
					f_home_cb.compute(block_camps, my_spawn, visited);
					PROF("f_home_cb");
					has_home_cb = true;
				}
				stage_ = ST_HOMECB;
				break;
			case ST_HOMECB:
				if (lean && bbany(holes) && !bbany(thin_holes))
				{
					// A champion's map (distances from draft memory) gets the thin holes too, so the hole-shortcut and dash-route checks can fire;
					// bitboard operations only (has_dash stays false).
					const bitboard W = ~(walls | holes | altars_bb);
					bitboard pairs = W.shift_right(1) & W.shift_right(-1);
					pairs |= W.shift_up(1) & W.shift_up(-1);
					pairs |= W.shift_right(1).shift_up(1) & W.shift_right(-1).shift_up(-1);
					pairs |= W.shift_right(1).shift_up(-1) & W.shift_right(-1).shift_up(1);
					thin_holes = holes & pairs;
					has_thin = bbany(thin_holes);
				}
				if (want_dash && !distances_known_ && bbany(holes))
				{
					if (f < reserve + field_cost() + 12000)
						return ready();
					// Holes with walkable tiles on both sides along some axis: a two-step dash crosses them.
					const bitboard W = ~(walls | holes | altars_bb);
					bitboard pairs = W.shift_right(1) & W.shift_right(-1);
					pairs |= W.shift_up(1) & W.shift_up(-1);
					pairs |= W.shift_right(1).shift_up(1) & W.shift_right(-1).shift_up(-1);
					pairs |= W.shift_right(1).shift_up(-1) & W.shift_right(-1).shift_up(1);
					thin_holes = holes & pairs;
					has_thin = bbany(thin_holes);
					bitboard bhc_ta; // BHC bit 2: altars with walkable tiles on both sides along some axis (a dash middle)
					bitboard pa = W.shift_right(1) & W.shift_right(-1);
					pa |= W.shift_up(1) & W.shift_up(-1);
					pa |= W.shift_right(1).shift_up(1) & W.shift_right(-1).shift_up(-1);
					pa |= W.shift_right(1).shift_up(-1) & W.shift_right(-1).shift_up(1);
					bhc_ta = altars_bb & pa;
					f_home_dash.compute(walls | ((altars_bb & ~bhc_ta)) | enemy_spawn | (holes & ~thin_holes), my_spawn, visited);
					PROF("f_dash");
					has_dash = true;
				}
				cursor_ = 0;
				phase_ = 0;
				stage_ = ST_DASH;
				break;
			case ST_DASH:
				if (!step_distances(reserve + 3000))
					return ready();
				PROF("distances");
				stage_ = ST_DONE;
				break;
			default:
				stage_ = ST_DONE;
				break;
			}
		}
	}
	catch (const std::exception& e)
	{
		NLOG("mapinfo init error stage %d: %s\n", stage_, e.what());
		// Skip a failing stage rather than retrying it forever.
		cursor_ = 0;
		++stage_;
	}
	return ready();
}
// The enclosure is where f_altar (camps blocked) reaches; a camp next to it and next to a tile our spawn reaches with camps blocked
// is a one-camp breach. Then the camps-passable field to every altar neighbour (gated maps).
bool MapInfo::gate_step(long reserve)
{
	bitboard visited;
	if (ring_todo)
	{
		// Resumable: the camp loop costs ~0.9k a camp (~85k on 96 camps).
		if (!ring_fo_ok)
		{
			if (fuel() < reserve + field_cost() + 4000)
				return false;
			ring_fo.compute(block_camps, my_spawn, visited);
			ring_fo_ok = true;
			ring_ci = 0;
		}
		const FView va = fview(f_altar), vo = fview(ring_fo);
		for (std::size_t ci = ring_ci; ci < camps.size(); ++ci)
		{
			if ((ci & 7) == 0 && fuel() < reserve + 12000)
			{
				ring_ci = ci;
				return false;
			}
			bool in = false, out = false;
			for (const vec2 d : DIRS)
			{
				const vec2 q = camps[ci].pos + d;
				if (!inb(q))
					continue;
				in = in || va(q) != UNREACH;
				out = out || vo(q) != UNREACH;
			}
			if (!in || !out)
				continue;
			ring_camps.push_back(static_cast<int>(ci));
			const int gi = camps[ci].group;
			if (gi >= 0 && (!gtm_has(gi))) // b2402 GTM2
			{
				gate_groups.push_back(gi);
				gtm_put(gi); // b2402 GTM1
			}
		}
		ring_todo = false;
		ring = !ring_camps.empty();
	}
	if (open_todo)
	{
		if (gate_groups.empty())
		{
			open_todo = false;
			return true;
		}
		if (fuel() < reserve + field_cost())
			return false;
		f_altar_open.compute(block, altar_adj_all, visited);
		has_altar_open = true;
		open_todo = false;
	}
	return true;
}

} // namespace nova
