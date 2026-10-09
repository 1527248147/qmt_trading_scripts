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


# ---------------------------------------------------------------------------
# THE AUCTION STILL FILLS, AND A FILL STILL HAS TO BE RECORDED.
#
# _cancel_stale_orders is the only place this script calls _exec_close, and it
# used to `return` at NO_CANCEL_AFTER -- so from 14:57 the buy side observed
# nothing. Every closing-auction fill was missing from the exec CSV, from the
# durable fill record and from the achieved-average summary, and the auction is
# where a TWAP puts whatever it could not work during the session. Any VWAP
# comparison drawn from that file would silently omit the last three minutes.
print()
print("=" * 88)
print("RECORDING DURING THE CLOSING AUCTION")
print("=" * 88)


class _AOrd(object):
    def __init__(self, status, traded=300, orig=300):
        self.m_strInstrumentID = "600620"
        self.m_strExchangeID = "SH"
        self.m_strRemark = M.STRATEGY + "_600620.SH_145600"
        self.m_nOrderStatus = status
        self.m_nVolumeTraded = traded
        self.m_nVolumeTotalOriginal = orig
        self.m_dTradedPrice = 7.71
        self.m_dLimitPrice = 7.71


def _scan(wall, status=56):
    seen, cancelled = [], []
    # cancel/can_cancel_order/get_trade_detail_data are injected by QMT at
    # runtime, so offline they are absent rather than merely different. _MISS
    # marks that, and the restore deletes instead of assigning back.
    _MISS = object()
    _saved = dict((k, getattr(M, k, _MISS)) for k in
                  ("_exec_close", "cancel", "can_cancel_order",
                   "get_trade_detail_data"))
    _sw = getattr(M.S, "wall_override", None)
    M._exec_close = lambda o, remark, t: seen.append(remark)
    M.cancel = lambda *a, **k: cancelled.append(a)
    M.can_cancel_order = lambda *a, **k: True
    M.get_trade_detail_data = lambda *a, **k: [_AOrd(status)]
    M.S.preview = False
    M.S.acct = "507085"
    M.S.acct_type = "STOCK"
    M.S.now = "20260902145800"
    M.S.wall_override = wall
    try:
        M._cancel_stale_orders(None, "20260902", "145800")
    finally:
        for _k, _v in _saved.items():
            if _v is _MISS:
                delattr(M, _k)
            else:
                setattr(M, _k, _v)
        M.S.wall_override = _sw
    return seen, cancelled


_seen, _cx = _scan("145800")
check("an auction fill is still recorded", len(_seen), 1)
check("...and no cancel is sent into the auction", _cx, [])
# A live order during the auction must not be cancelled either -- the exchange
# refuses it, and every attempt is a counter message we pay for.
_seen2, _cx2 = _scan("145800", status=50)
check("a resting order is left alone in the auction", _cx2, [])
# Before the auction the scan behaves exactly as it always did.
_seen3, _cx3 = _scan("143000")
check("before 14:57 a terminal order is still recorded", len(_seen3), 1)


# ---------------------------------------------------------------------------
# THE FINAL SWEEP, AND THE COVERAGE LINE.
#
# The closing auction settles at 15:00, after the last bar the strategy is
# given, so a fill there is only written down if a later bar happens to arrive.
# And on both live days the exec CSV turned out to hold a fraction of the day
# -- 21,782 of 26,128 shares on 2026-09-01, 2,504 of 19,623 on 2026-09-02 --
# which was discovered days later by hand rather than from the log.
print()
print("=" * 88)
print("FINAL SWEEP AND EXEC COVERAGE")
print("=" * 88)


def _sweep(rows, recorded, exec_shares):
    """Run _sweep_final over `rows` and return (late remarks, printed lines)."""
    out, late = [], []
    _MISS = object()
    _saved = dict((k, getattr(M, k, _MISS)) for k in
                  ("_exec_close", "get_trade_detail_data"))
    M.get_trade_detail_data = lambda *a, **k: rows
    M._exec_close = lambda o, remark, t: late.append(remark)
    M.S.preview = False
    M.S.acct = "507085"
    M.S.acct_type = "STOCK"
    M.S.now = "20260902150000"
    M.S.exec_recorded = set(recorded)
    M.S.exec_shares = exec_shares
    # Coverage now reads the WHOLE day's exec CSV (see _exec_day_totals),
    # not the in-memory counter a restart zeroes -- so the day's recorded
    # total is supplied the way the script now obtains it.
    _saved_edt = M._exec_day_totals
    M._exec_day_totals = lambda: ({'600620.SH': [exec_shares, exec_shares * 7.71]}, [])
    # The strategy defines its OWN print, which tees to the run log -- so
    # patching builtins.print captures nothing. Patch the module's.
    _hadp = "print" in M.__dict__
    _oldp = M.__dict__.get("print")
    M.print = lambda *a, **k: out.append(" ".join(str(x) for x in a))
    try:
        M._sweep_final()
    finally:
        M._exec_day_totals = _saved_edt
        if _hadp:
            M.print = _oldp
        else:
            del M.print
        for _k, _v in _saved.items():
            if _v is _MISS:
                delattr(M, _k)
            else:
                setattr(M, _k, _v)
    return late, out


_R = M.STRATEGY + "_600620.SH_145600"


class _SOrd(object):
    def __init__(self, remark, traded):
        self.m_strInstrumentID = "600620"
        self.m_strExchangeID = "SH"
        self.m_strRemark = remark
        self.m_nOrderStatus = 56
        self.m_nVolumeTraded = traded
        self.m_nVolumeTotalOriginal = traded
        self.m_dTradedPrice = 7.71


# An auction fill nobody has seen yet is picked up and reported.
_late, _out = _sweep([_SOrd(_R, 300)], recorded=[], exec_shares=300)
check("a fill missed by the last bar is swept up", _late, [_R])
check("...and said so", any("had filled without being recorded" in l for l in _out), True)
check("...with complete coverage reported",
      any("EXEC COVERAGE: 300 / 300" in l for l in _out), True)

# Another strategy's order in a shared account is never touched.
_late2, _out2 = _sweep([_SOrd("someone_else_600620", 500)], recorded=[], exec_shares=0)
check("another strategy's order is left alone", _late2, [])

# Already recorded: nothing is 'late', and _exec_close is still safe to call
# because its own guard drops it.
_late3, _out3 = _sweep([_SOrd(_R, 300)], recorded=[_R], exec_shares=300)
check("an order already recorded is not reported late",
      any("had filled without being recorded" in l for l in _out3), False)

# THE CASE THAT MATTERS: the file holds less than the day.
_late4, _out4 = _sweep([_SOrd(_R, 19623)], recorded=[_R], exec_shares=2504)
check("a short exec CSV is called out, not passed over",
      any("only 2504 of 19623" in l for l in _out4), True)
check("...and says the VWAP comparison would be a fragment",
      any("FRAGMENT" in l for l in _out4), True)

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
