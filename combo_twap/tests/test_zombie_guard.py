#coding:utf-8
"""Direct tests of the un-cancellable-order guard, for BOTH dual scripts.

The sell script has a full session replay (test_sell_model_offline.py); the buy
script has none, and the buy side is where the damage was measured -- 25 stuck
orders froze 8,341 shares on 2026-08-24 against a 9,151-share shortfall. So the
new logic is exercised directly here, on both modules, rather than trusted
because the sell replay is green.

    python test_zombie_guard.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The suite lives in tests/ and the strategies live one level up. ROOT is
# what everything else in this file means by "the project directory".
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-58s %-12s %s" % (name, repr(got), "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


def fresh(M):
    """A state object with just the fields the guard touches."""
    # The sell script's log() writes to a per-day file it opens in init(); False
    # is its "no file, print only" sentinel, which is what a unit test wants.
    M.S.runlog = False
    M.S.cx_tries = {}
    M.S.cx_sig = {}
    M.S.cx_first = {}
    M.S.zombies = set()
    M.S.zombie_credited = set()


def cancel_round(M, remark, status, left, now_m):
    """One bar: judge, then (if still alive) record a cancel going out."""
    if M._zombie(remark, status, left, now_m):
        return "written-off"
    M.S.cx_tries[remark] = M.S.cx_tries.get(remark, 0) + 1
    M.S.cx_sig[remark] = (status, left)
    M.S.cx_first.setdefault(remark, now_m)
    return "cancelled"


for name in ("combo_sell_dual_model", "combo_buy_dual_model"):
    M = __import__(name)
    print()
    print("=" * 88)
    print(name)
    print("=" * 88)

    # --- an order the counter refuses to cancel, over and over ---------------
    fresh(M)
    r = "x_600533SH_112400"
    acts = []
    # The LIVE cadence: the cooldown lets one cancel through every
    # STALE_ORDER_MIN bars, so six tries span half an hour and the try count is
    # the binding gate. Driving it every bar instead would make the 15-minute
    # age gate bind first and the assertion below would be measuring the wrong
    # thing -- status 50, 400 unfilled, never moving is exactly what a 251020
    # leaves behind either way.
    for i in range(0, 200, M.STALE_ORDER_MIN):
        acts.append(cancel_round(M, r, 50, 400, i))
    tries = acts.count("cancelled")
    check("stuck order stops being cancelled", acts[-1], "written-off")
    check("...after exactly the threshold number of tries",
          tries, M.ZOMBIE_CANCEL_TRIES)
    check("...and is flagged", r in M.S.zombies, True)

    # The age test must bind too: a burst of cancels inside one minute is not
    # evidence of anything, and condemning on the count alone would write off an
    # order that is merely being retried through a slow patch.
    fresh(M)
    r2 = "x_burst"
    for i in range(40):
        cancel_round(M, r2, 50, 400, 0)          # all in the same bar minute
    check("a burst inside one minute is NOT written off", r2 in M.S.zombies, False)

    # --- it comes back if it ever moves --------------------------------------
    fresh(M)
    r3 = "x_recovers"
    for i in range(20):
        cancel_round(M, r3, 50, 400, i)
    was = r3 in M.S.zombies
    # A partial fill lands: remainder 400 -> 300. The order is demonstrably
    # alive, so the verdict has to be withdrawn or the name loses that quantity
    # from its schedule for the rest of the day.
    still = M._zombie(r3, 50, 300, 21)
    check("was written off first", was, True)
    check("...but a fill brings it back", still, False)
    check("...and it is no longer flagged", r3 in M.S.zombies, False)

    # A successful cancel is also movement (status 50 -> 54).
    fresh(M)
    r4 = "x_cancel_took"
    for i in range(20):
        cancel_round(M, r4, 50, 400, i)
    check("a cancel that finally lands also clears it",
          M._zombie(r4, 54, 400, 21), False)

    # --- the wall clock is the exchange's, not the bar label's ---------------
    M.S.wall_override = None
    w = M._wall_hhmmss()
    check("wall clock reads as HHMMSS", len(w) == 6 and w.isdigit(), True)
    M.S.wall_override = "145500"
    check("...and can be driven for testing", M._wall_hhmmss(), "145500")
    M.S.wall_override = None

    # The boundary the 2026-08-24 loss turned on: bar 145700 is delivered at
    # wall 14:55:58, and at that moment the closing auction is NOT open.
    gate = getattr(M, "AUCTION_AT", None) or getattr(M, "NO_CANCEL_AFTER")
    check("bar-145700 delivery time is before the auction opens",
          "145558" < gate, True)
    check("...one bar later is not", "145658" < gate, True)
    check("...two bars later is inside the auction", "145758" >= gate, True)

print()
print("=" * 88)
if fails:
    print("FAILED %d check(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CHECKS PASSED")
print("=" * 88)
sys.exit(1 if fails else 0)
