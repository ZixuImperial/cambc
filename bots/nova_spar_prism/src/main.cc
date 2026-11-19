// main.cc: Bot entry point: runs the draft or a champion turn, catching errors.
// Nova: draft from map analysis, then per-champion turns. Every turn is wrapped so an error never crashes the bot.
#include <cambc.h>

#include "brain.h"
#include "common.h"
#include "draft.h"

int main()
{
	while (true)
	{
		bool play = false; // a play turn (not a draft turn)
		try
		{
			if (cambc::is_draft())
			{
				// A draft turn that runs out of fuel is resumed in the next draft round, and returning from it would end that round without a
				// pick, so the engine draws the rest at random. Our completed picks only grow when a round ends, so more of them now than at the
				// start means a new round began while this call ran: play its pick before ending it (play_draft picks before any background
				// work). A loop (a resumed call can run out too and end a later round), the count read safely.
				auto done_now = []() -> std::size_t
				{
					try
					{
						return cambc::draft::current_draft(cambc::team::ally).size();
					}
					catch (...)
					{
						return 0;
					}
				};
				std::size_t done = done_now();
				nova::drafting::play_draft();
				for (int k = 0; k < 6 && cambc::is_draft(); ++k)
				{
					const std::size_t now_done = done_now();
					if (now_done <= done)
						break;
					done = now_done;
					nova::drafting::play_draft();
				}
			}
			else
			{
				play = true;
				if (!nova::spin_on_turn_start()) // my spin is cancelled before anything else
					nova::play_turn();
			}
		}
		catch (const std::exception& e)
		{
			NLOG("turn error: %s\n", e.what());
			(void)e;
		}
		catch (...)
		{
			NLOG("turn error: unknown\n");
		}
		if (play)
		{
			try
			{
				nova::spin_on_turn_end(); // the last call of the turn
			}
			catch (...)
			{
			}
		}
		cambc::detail::sdk_yield(); // cambc::end_turn() without its fflush(nullptr) (~50 fuel a turn; nothing is printed).
	}
}
