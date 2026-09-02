#coding:utf-8
"""Direct tests of the buy script's closing-auction fallback.

The buy side has no session replay, and this branch fires for three minutes a
day with no way to cancel a mistake, so it is exercised here against stubbed
helpers rather than trusted on inspection.

    python test_buy_auction.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The suite lives in tests/ and the strategies live one level up. ROOT is
# what everything else in this file means by "the project directory".
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import combo_buy_dual_model as M

M.ALLOWED_ACCOUNTS = ()

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-58s %-14s %s" % (name, repr(got), "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


SENT = []


def stub(held, filled=None, pend=None, cash=None, prices=None, nav=200000.0):
    """Point every broker-facing helper at a fixed picture of the account."""
    del SENT[:]
    prices = prices or {}
    filled = filled or {}
    pend = pend or {}

    M.S.auction_done = False
    M.S.buy_state = {"filled": set(held), "active": [], "rank_of": {}, "queue_i": 0}
    M.S.limit_cache = {}

    M._positions = lambda C: dict(held)
    M._own = lambda h, code: h.get(code, 0)
    M._total_value = lambda C: nav
    M._open_buy_qty = lambda C: dict(pend)
    M._filled_today = lambda C: dict(filled)
    M._available_cash = lambda C: cash
    M._quote = lambda C, code, today, mn: (
        {"close": prices.get(code, (0, 0))[0],
         "preclose": prices.get(code, (0, 0))[0],
         "volume": 1000} if code in prices else None)
    M._limit_up = lambda C, code, q: prices.get(code, (0, 0))[1]
    M._prev_min = lambda h: h

    def fake_order(C, code, vol, remark, limit_px=None):
        SENT.append((code, int(vol), limit_px))
    M._order_buy = fake_order


print("=" * 88)
print("BUY CLOSING-AUCTION FALLBACK")
print("=" * 88)

# --- the ordinary case: a slot left short late in the day --------------------
# 2026-08-25 in miniature. nav 200,000 over 20 slots is 10,000 a slot; at 2.50
# that is a 4,000-share target, and the slot holds 3,300.
stub(held={"002133.SZ": 3300}, prices={"002133.SZ": (2.50, 2.75)})
M.SLOTS = 20
M._run_auction(None, "20260825", "145900")
check("short slot is topped up", SENT, [("002133.SZ", 700, 2.75)])
check("priced at the CEILING, not the last trade", SENT[0][2], 2.75)

# --- already at target: nothing to do ---------------------------------------
stub(held={"002133.SZ": 4000}, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("a full slot sends nothing", SENT, [])

# --- resting orders still count ---------------------------------------------
# An order working in the book will fill or not, but it is not a shortfall, and
# double-counting it here cannot be undone -- the exchange refuses cancellation
# for the whole auction.
stub(held={"002133.SZ": 3300}, pend={"002133.SZ": 700},
     prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("pending shares are not bought twice", SENT, [])

# --- the DEAL list leads the position query ---------------------------------
stub(held={"002133.SZ": 3300}, filled={"002133.SZ": 4000},
     prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("takes the LARGER of position and filled-today", SENT, [])

# --- sub-lot shortfall: no odd-lot exception when buying --------------------
# The exception exists for liquidating a position. A 50-share buy is a rejected
# order, and on STAR the minimum is 200 rather than 100.
stub(held={"002133.SZ": 3950}, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("refuses a sub-lot buy (50 short of a 100 lot)", SENT, [])

stub(held={"688162.SH": 300}, prices={"688162.SH": (25.00, 27.50)})
M._run_auction(None, "20260825", "145900")
check("STAR: 100 short of a 200-share lot is refused", SENT, [])

# --- cash is frozen at the price we name ------------------------------------
# 700 shares at the 2.75 ceiling needs 1,925; with 1,000 available only 300
# shares fit (825), and a partial top-up beats none.
stub(held={"002133.SZ": 3300}, cash=1000.0, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("trimmed to what the cash actually covers", SENT, [("002133.SZ", 300, 2.75)])

stub(held={"002133.SZ": 3300}, cash=100.0, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("skipped when not even one lot fits", SENT, [])

# An unreadable balance must not block the fallback: refusing to buy on a failed
# query is the same outcome as having no fallback at all.
stub(held={"002133.SZ": 3300}, cash=None, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145900")
check("unknown cash still sends", SENT, [("002133.SZ", 700, 2.75)])

# --- cash is shared across names --------------------------------------------
stub(held={"002133.SZ": 3300, "600018.SH": 1600}, cash=2000.0,
     prices={"002133.SZ": (2.50, 2.75), "600018.SH": (5.00, 5.50)})
M._run_auction(None, "20260825", "145900")
_spend = sum(q * px for _, q, px in SENT)
check("total committed stays inside the balance", _spend <= 2000.0, True)

# --- sent ONCE --------------------------------------------------------------
# handlebar fires at 14:57, 14:58 and 14:59 and the exchange refuses every
# cancellation in between, so a second pass is a second position with no way back.
stub(held={"002133.SZ": 3300}, prices={"002133.SZ": (2.50, 2.75)})
M._run_auction(None, "20260825", "145700")
M._run_auction(None, "20260825", "145800")
M._run_auction(None, "20260825", "145900")
check("three bars produce exactly one batch", len(SENT), 1)

# --- no quote, no order -----------------------------------------------------
stub(held={"002133.SZ": 3300}, prices={})
M._run_auction(None, "20260825", "145900")
check("a name with no quote is skipped, not guessed at", SENT, [])

# --- the timing the sell side got wrong on 2026-08-24 -----------------------
check("bar-145700 delivery time is before the auction opens",
      "145558" < M.AUCTION_AT, True)
check("two bars later is inside the auction", "145758" >= M.AUCTION_AT, True)
check("cancels are already blocked by then", M.NO_CANCEL_AFTER <= M.AUCTION_AT, True)

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
