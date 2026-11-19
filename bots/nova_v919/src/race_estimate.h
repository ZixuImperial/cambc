// race_estimate.h: Estimate of when the race to the winning gem count ends. The foe team's finish predictor, pure (no game state).
// Time is in rounds from now to the round the foe's 1000th gem is CREDITED (the tribute that crosses 1000 executes at its owner's
// next turn start after rs::tribute_rounds(bag) own turn ends).
#pragma once
#include <algorithm>
#include "rules.h"
namespace nova::prism::rfe {
// BAGS (solved exactly instead of 30 bisection steps): the smallest t in [0, 2000] with got(t) = sum of val[i] over bags with at[i]
// <= t + qrate x max(0, t - lag) >= need, else 1e9. at[] = k x Chebyshev(last-seen tile, nearest altar) + tribute rounds of the bag;
// val[] = p x bag. at[] / val[] are sorted by at[] here (insertion sort; n is the foe roster size, <= 16).
// hz: the horizon in rounds from now (BB8 bit 2: rounds left to round 2000; else 2000).
inline double bags_time_to_need(double need, double* at, double* val, int n, double qrate, double lag, double hz = 2000.0) // hz: BB8_ON(2)
{
	for (int i = 1; i < n; ++i)
		for (int j = i; j > 0 && at[j] < at[j - 1]; --j)
		{
			std::swap(at[j], at[j - 1]);
			std::swap(val[j], val[j - 1]);
		}
	if (need <= 0.0)
		return 0.0;
	double cum = 0.0, from = 0.0;
	for (int i = 0;; ++i)
	{
		const bool last = i >= n || at[i] > hz; // BB8_ON(2) horizon
		const double to = last ? hz : at[i]; // BB8_ON(2) horizon
		if (qrate > 0.0) // the continuous part on [from, to]: cum + qrate x (t - lag) >= need
		{
			const double t = std::max(from, lag + (need - cum) / qrate);
			if (t <= to)
				return t;
		}
		if (last)
			return 1e9;
		cum += val[i];
		from = to;
		if (cum + qrate * std::max(0.0, from - lag) >= need)
			return from;
	}
}
// LINEAR (foe_finishes_before_bank's rate test): (1000 - them) / rate, 1e9 without a rate.
inline double linear_eta(int them, double rate) { return rate > 0.0 ? static_cast<double>(rs::WIN_TRIBUTE - them) / rate : 1e9; }
} // namespace nova::prism::rfe
