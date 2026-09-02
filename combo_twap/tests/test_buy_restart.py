#coding:utf-8
"""The restart fallback: does the buy side still know what it bought today?

2026-08-26 is the case this exists for. The buy script restarted at 13:00 and
re-ran its entire schedule, because all three of its "how much have I bought"
sources read zero at the same moment:

    cur = position - baseline   the 09:44 baseline put 002133.SZ at 3,300; the
                                account read 2,800 at 13:01 after we had bought
                                1,800 (a shared simulation account, edited by
                                things that are not us), and max(0, -500) is 0
    filled_today (DEAL query)   empty after a restart
    S.sent_qty                  in memory, so zero by definition

The trades CSV could not save it either: _log_trade runs straight after
passorder, so it holds SENT quantity -- 36,608 shares that day against 13,100
actually filled.

    python test_buy_restart.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The suite lives in tests/ and the strategies live one level up. ROOT is
# what everything else in this file means by "the project directory".
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import combo_buy_dual_model as M

# The offline harness binds a fake account; the live-account whitelist
# would block every replay here. The guard itself is tested separately.
M.ALLOWED_ACCOUNTS = ()

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-58s %-14s %s" % (name, repr(got), "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


DAY = "29991231"                      # far future: never collides with a real run
PATH = None


def clean():
    global PATH
    M.S.runlog_dir = ROOT
    PATH = M._fills_path(DAY)
    try:
        os.remove(PATH)
    except OSError:
        pass


print("=" * 88)
print("RESTART FALLBACK  (durable fill record)")
print("=" * 88)

clean()
check("no file yet -> nothing claimed", M._fills_from_disk(DAY), {})

# A fill is recorded once, by _exec_close, which has already popped the order
# out of S.exec_open -- so replaying the file cannot double-count it.
M._fill_append(DAY, "002133.SZ", 800, "r1")
M._fill_append(DAY, "002133.SZ", 1000, "r2")
M._fill_append(DAY, "600533.SH", 1600, "r3")
check("fills accumulate per name", M._fills_from_disk(DAY),
      {"002133.SZ": 1800, "600533.SH": 1600})

# Reading is a pure replay: it must not mutate or grow the file.
before = M._fills_from_disk(DAY)
after = M._fills_from_disk(DAY)
check("replaying twice reads the same numbers", before, after)

# The header is written once, not on every append.
_txt = open(PATH).read()
check("exactly one header line", _txt.count("code,filled,remark"), 1)
check("one data line per fill", len(_txt.strip().split("\n")) - 1, 3)

# --- the moment that broke on 2026-08-26 -----------------------------------
# Rebuild the arithmetic the sizing loop runs, with every live source at zero,
# and check that the floor alone stops the schedule being re-run.
_tgt, _twap = 3500, 2300
_cur, _pend, _sent, _dealt = 0, 0, 0, 0          # all three sources: zero
_floor = M._fills_from_disk(DAY).get("002133.SZ", 0)

_delta_old = _twap - max(_cur + _pend, _sent, _dealt)
_delta_new = _twap - max(_cur + _pend, _sent, max(_dealt, _floor))
print("  target %d, schedule %d, already filled today %d" % (_tgt, _twap, _floor))
print("  delta before the fix: %d      after: %d" % (_delta_old, _delta_new))
check("the old arithmetic re-buys the whole schedule", _delta_old, 2300)
check("the floor cuts it to the genuine shortfall", _delta_new, 500)

# --- it must never REDUCE what a healthy account already knows -------------
# On a real account cur is right and larger; the floor has to lose the max().
_cur_ok = 1800
_delta_healthy = _twap - max(_cur_ok + 0, 0, max(0, _floor))
check("a healthy account is unaffected by the floor", _delta_healthy, 500)

_cur_ahead = 2400                       # position ahead of our own record
_d = _twap - max(_cur_ahead + 0, 0, max(0, _floor))
check("...and a larger cur still wins", _d, -100)

# --- a fresh day starts empty ----------------------------------------------
check("yesterday's file is not read for today", M._fills_from_disk("29991230"), {})

# --- a corrupt line must not take the strategy down ------------------------
f = open(PATH, "a")
f.write("this is not a row\n")
f.write("600533.SH,notanumber,r4\n")
f.write("601398.SH,300,r5\n")
f.close()
_got = M._fills_from_disk(DAY)
check("junk lines are skipped, good ones still counted",
      _got.get("601398.SH"), 300)
check("...and the earlier totals survive", _got.get("002133.SZ"), 1800)

try:
    os.remove(PATH)
except OSError:
    pass

print()
print("=" * 88)

# ---------------------------------------------------------------------------
# A REJECTED ORDER MUST GIVE ITS QUANTITY BACK TO sent_qty.
#
# 2026-08-31 10:11, live. 002573.SZ sent 700, refused by the counter with
# [COUNTER][250253] before the order reached the market, and the next bar read
#     cur 0 pend 0 sent 700 dealt 0 | tgt 3000 twap 700 delta 0
#     -> delta 0 < one lot 100
# sent_qty is a floor under `delta`, so a share that never existed was holding
# the slot shut until the TWAP schedule crawled past it. A cancel already gives
# its remainder back; a rejection has strictly more right to.
# ---------------------------------------------------------------------------
class _Ord(object):
    def __init__(self, code, exch, remark, orig, traded, status, info=""):
        self.m_strInstrumentID = code
        self.m_strExchangeID = exch
        self.m_strRemark = remark
        self.m_nVolumeTotalOriginal = orig
        self.m_nVolumeTraded = traded
        self.m_nOrderStatus = status
        self.m_strCancelInfo = info
        self.m_strStatusMsg = ""


def _reject_round(rows):
    """One pass of _cancel_stale_orders over a fixed broker order list.

    wall_override is REQUIRED, not decoration. _cancel_stale_orders returns
    immediately once the real Beijing clock passes NO_CANCEL_AFTER, so without
    it this whole block silently passes in the morning and silently fails
    after 14:57 -- which is exactly what it did on 2026-08-31, when the same
    unchanged code went from green at 13:40 to three failures at 15:20. A test
    that only holds before lunch is worse than no test: it reports success at
    the moment you most need it to report failure.

    Every piece of state _cancel_stale_orders touches is seeded here for the
    same reason -- a missing attribute is swallowed by the per-row try/except
    and the row is skipped, which looks identical to "the logic did nothing".
    """
    M.S.wall_override = "101200"
    M.S.zombies = set()
    M.S.zombie_credited = set()
    M.S.cancel_inflight = set()
    M.S.floor_orders = {}
    M.S.exec_open = {}
    M.S.pend_released = set()
    M.get_trade_detail_data = lambda *a, **k: rows
    M._exec_close = lambda *a, **k: None
    try:
        M._cancel_stale_orders(None, "20260831", "101200")
    finally:
        M.S.wall_override = None


_R = "%s_002573.SZ_101200" % M.STRATEGY
M.S.preview = False
M.S.acct = "1000003"
M.S.acct_type = "STOCK"
M.S.now = "20260831101200"
M.S.rejected_seen = set()
M.S.sent_qty = {"002573.SZ": 700}
M.S.order_time = {_R: 0}
_rows = [_Ord("002573", "SZ", _R, 700, 0, 57, "[COUNTER][250253][...]")]

_reject_round(_rows)
check("a rejected order gives its quantity back", M.S.sent_qty.get("002573.SZ"), 0)
# The broker re-serves the same terminal row on every later bar. Crediting it
# twice would walk sent_qty below what really is outstanding and let the next
# slice double up.
_reject_round(_rows)
_reject_round(_rows)
check("...and is not credited again on later bars", M.S.sent_qty.get("002573.SZ"), 0)

# A PARTIAL fill that was then rejected keeps the filled part counted.
M.S.rejected_seen = set()
M.S.sent_qty = {"600533.SH": 400}
_p = "%s_600533.SH_101200" % M.STRATEGY
M.S.order_time = {_p: 0}
_reject_round([_Ord("600533", "SH", _p, 400, 300, 57, "[COUNTER][251005][...]")])
check("a partly filled rejection keeps the filled part", M.S.sent_qty.get("600533.SH"), 300)

# A code we never sent must not be credited into existence.
M.S.rejected_seen = set()
M.S.sent_qty = {}
_u = "%s_000001.SZ_101200" % M.STRATEGY
M.S.order_time = {_u: 0}
_reject_round([_Ord("000001", "SZ", _u, 500, 0, 57, "[COUNTER][250253][...]")])
check("an unknown code is not credited", M.S.sent_qty.get("000001.SZ"), None)


# ---------------------------------------------------------------------------
# SEALED LIMIT-DOWN ON A NAME WE ARE TOLD TO BUY.
#
# QUEUE quotes at bid-1. A sealed limit-down board has NO bid, so the mode
# cannot ask for a stock the market is desperate to hand over. _sealed_up was
# written to stop us buying what cannot be bought; nothing was ever written
# for the mirror, and the gap was found on 2026-08-31.
#
# The fix prices at the FLOOR with prType 11. A limit buy cannot execute above
# its own limit and the floor is the day's legal minimum, so it fills at the
# floor or not at all -- which is what makes a false positive free.
# ---------------------------------------------------------------------------
class _Q(dict):
    pass


def _mk(bid, ask, floor, got=True):
    M.S.floor_cache = {"000001.SZ": floor}
    M._touch_raw = lambda C, code: (bid, ask, got)
    return M._sealed_down(None, "000001.SZ", _Q(preclose=10.0))


# Sealed: no bid at all, offers stacked on the floor.
check("no bid + offers at the floor is sealed", _mk(0.0, 9.00, 9.00)[0], True)
check("...and it reports the floor as the price", _mk(0.0, 9.00, 9.00)[1], 9.00)
# One tick of tolerance, because the touch and the floor are read separately.
check("half a tick of tolerance is allowed", _mk(0.0, 9.005, 9.00)[0], True)

# NOT sealed: a bid exists, so QUEUE has something to quote at. Down a lot is
# not the same as sealed, and this is the common case that must stay in QUEUE.
check("a live bid means not sealed", _mk(8.99, 9.00, 9.00)[0], False)
# NOT sealed: no offers either. That is a halt or an untouched name, and
# buying into a halt is not possible -- sending a floor-priced order there
# would just leave a live order sitting in a stock nobody is trading.
check("an empty book is a halt, not a seal", _mk(0.0, 0.0, 9.00)[0], False)
# NOT sealed: offers above the floor, so the board is open.
check("offers above the floor mean open", _mk(0.0, 9.50, 9.00)[0], False)
# No floor known -> never claim a seal. Guessing a floor too HIGH would send a
# limit buy at a price the market never reached.
check("no floor known is never sealed", _mk(0.0, 9.00, None)[0], False)
# Unreadable touch -> never claim a seal.
check("an unreadable touch is never sealed", _mk(0.0, 9.00, 9.00, got=False)[0], False)

# The floor fallback must land LOW, not high: a too-high floor would make an
# open book look sealed. _board_rate is the wide value, so preclose*(1-rate)
# is conservative in exactly the right direction.
check("ChiNext floor uses the wide 20%", M._board_rate("300001.SZ"), 0.20)
check("Beijing floor uses the wide 30%", M._board_rate("920002.BJ"), 0.30)
check("main board uses 10%", M._board_rate("600000.SH"), 0.10)


# ---------------------------------------------------------------------------
# AN ORDER WE SENT MUST COUNT AS PENDING BEFORE THE BROKER CAN SEE IT.
#
# 2026-08-31, 688567.SH. Three bars, each reading "cur 663 pend 0", each
# ordering the same 218-share gap, all three filling: 1,340 held against a
# 1,078 target. The shares were in neither the position nor the broker's order
# list for the tens of seconds between passorder and acknowledgement, so the
# script concluded it had not ordered yet.
# ---------------------------------------------------------------------------
import datetime as _dt


class _ORow(object):
    def __init__(self, code, exch, remark, orig, traded, status, direction=48):
        self.m_strInstrumentID = code
        self.m_strExchangeID = exch
        self.m_strRemark = remark
        self.m_nVolumeTotalOriginal = orig
        self.m_nVolumeTraded = traded
        self.m_nOrderStatus = status
        self.m_nDirection = direction


def _pend(rows, exec_open):
    M.S.preview = False
    M.S.acct = "1000003"
    M.S.acct_type = "STOCK"
    M.S.zombies = set()
    M.S.pend_released = set()
    M.S.exec_open = exec_open
    M.get_trade_detail_data = lambda *a, **k: rows
    return M._open_buy_qty(None)


_NOW = _dt.datetime.utcnow()
_R1 = "%s_688567.SH_132700" % M.STRATEGY
_rec = {"code": "688567.SH", "side": "buy", "qty": 218, "rt": _NOW}

# The exact failure: we sent it, the broker's list is still empty.
check("a sent-but-invisible order counts as pending",
      _pend([], {_R1: dict(_rec)}).get("688567.SH"), 218)
# Once the broker HAS it, the list is authoritative -- counting both would
# double it and stall the slot just as badly as missing it under-counts.
check("...and is not double counted once the broker has it",
      _pend([_ORow("688567", "SH", _R1, 218, 0, 50)], {_R1: dict(_rec)}).get("688567.SH"), 218)
# A terminal row must not be resurrected by exec_open. `seen` is built from
# EVERY row, before the terminal skip, precisely for this.
check("a filled order is not added back as pending",
      _pend([_ORow("688567", "SH", _R1, 218, 218, 56)], {_R1: dict(_rec)}).get("688567.SH"), None)
check("a rejected order is not added back either",
      _pend([_ORow("688567", "SH", _R1, 218, 0, 57)], {_R1: dict(_rec)}).get("688567.SH"), None)
# Two invisible orders on one name accumulate -- this is the case that would
# have stopped the third order on 08-31.
_R2 = "%s_688567.SH_132800" % M.STRATEGY
check("two invisible orders accumulate",
      _pend([], {_R1: dict(_rec),
                 _R2: {"code": "688567.SH", "side": "buy", "qty": 224, "rt": _NOW}}
            ).get("688567.SH"), 442)
# A sell record must never leak into the buy side's pending.
check("a sell record is ignored",
      _pend([], {_R1: {"code": "688567.SH", "side": "sell", "qty": 218, "rt": _NOW}}
            ).get("688567.SH"), None)
# The backstop: an order that never appears must eventually be released, or it
# pins the slot shut for the rest of the day -- the opposite failure.
_OLD = _NOW - _dt.timedelta(seconds=M.PEND_INVISIBLE_MAX_SEC + 1)
check("an order invisible past the backstop is released",
      _pend([], {_R1: {"code": "688567.SH", "side": "buy", "qty": 218, "rt": _OLD}}
            ).get("688567.SH"), None)
check("...but one just inside it still counts",
      _pend([], {_R1: {"code": "688567.SH", "side": "buy",
                       "qty": 218,
                       "rt": _NOW - _dt.timedelta(seconds=M.PEND_INVISIBLE_MAX_SEC - 30)}}
            ).get("688567.SH"), 218)
check("the backstop is much longer than the pause timeout",
      M.PEND_INVISIBLE_MAX_SEC > M.UNCONFIRMED_TIMEOUT_SEC * 3, True)


# ---------------------------------------------------------------------------
# THE RESTART HARDENING PORTED FROM THE SELL SIDE ON 2026-09-01.
# ---------------------------------------------------------------------------
import datetime as _dtB
import os as _osB

# --- filenames vary inside the directory, never the directory --------------
_TB = _osB.path.join(_osB.environ.get("TEMP", ROOT), "buyio")
try:
    _osB.makedirs(_TB)
except Exception:
    pass
for _fn in _osB.listdir(_TB):
    try:
        _osB.remove(_osB.path.join(_TB, _fn))
    except Exception:
        pass

_hb1, _pb1, _db1 = M._open_varying((_TB,), "run_b", ".log", "a")
check("the plain name is used first", _osB.path.basename(_pb1), "run_b.log")
import builtins as _biB
_boB = _biB.open


def _pickyB(path, mode="r", *a, **k):
    """Refuse a file that already exists -- the observed LIVE behaviour."""
    if _osB.path.exists(path) and "w" not in mode:
        raise IOError("live sandbox: pre-existing file")
    return _boB(path, mode, *a, **k)


_biB.open = _pickyB
try:
    M.S.session_tag = "101500"
    _hb2, _pb2, _db2 = M._open_varying((_TB,), "run_b", ".log", "a")
finally:
    _biB.open = _boB
    for _h in (_hb1, _hb2):
        try:
            _h.close()
        except Exception:
            pass
check("a blocked name falls to a tagged one", _osB.path.basename(_pb2), "run_b_101500.log")
check("...and stays in the same directory", _db2, _db1)
M.S.session_tag = None

# --- the settle window -----------------------------------------------------
_swB = getattr(M.S, "wall_override", None)


def _settleB(in_hours, start, now):
    M.S.session_in_hours = in_hours
    M.S.session_started = start
    M.S.settle_said = False
    M.S.wall_override = now
    return M._in_settle()


check("a pre-open session never settles", _settleB(False, "060000", "093000"), False)
check("a fresh mid-session restart holds", _settleB(True, "100000", "100005"), True)
check("...releases past the window", _settleB(True, "100000", "100136"), False)
check("the window outlasts the ack timeout",
      M.RESTART_SETTLE_SEC > M.UNCONFIRMED_TIMEOUT_SEC, True)
M.S.session_in_hours = False
M.S.wall_override = _swB

# --- filled-today rebuilt from the ORDER list ------------------------------
# This matters MORE on the buy side. When the DEAL query comes back empty after
# a restart, _load_or_snapshot_baseline falls into the branch that treats the
# whole current position as pre-existing, reads cur as 0 for every name, and
# buys the basket a second time. That is 2026-08-26.
class _OB(object):
    def __init__(self, code, exch, remark, traded, direction=48):
        self.m_strInstrumentID = code
        self.m_strExchangeID = exch
        self.m_strRemark = remark
        self.m_nVolumeTraded = traded
        self.m_nDirection = direction


_gtdB = M.get_trade_detail_data
M.S.acct = "1000003"
M.S.acct_type = "STOCK"
_RB = M.STRATEGY


def _foB(rows):
    M.get_trade_detail_data = lambda *a, **k: rows
    return M._fills_from_orders()


check("three orders on one name sum",
      _foB([_OB("600533", "SH", _RB + "_a", 100),
            _OB("600533", "SH", _RB + "_b", 200)]).get("600533.SH"), 300)
check("a re-served row is not double counted",
      _foB([_OB("600533", "SH", _RB + "_a", 100),
            _OB("600533", "SH", _RB + "_a", 100)]).get("600533.SH"), 100)
check("a SELL row is ignored on the buy side",
      _foB([_OB("600533", "SH", _RB + "_a", 100),
            _OB("600533", "SH", _RB + "_s", 900, direction=49)]).get("600533.SH"), 100)
check("another strategy's order is ignored",
      _foB([_OB("600533", "SH", "someone_else", 9999)]).get("600533.SH"), None)


def _boomB(*a, **k):
    raise RuntimeError("ORDER query unavailable")


M.get_trade_detail_data = _boomB
check("a failed query returns nothing, not zero", M._fills_from_orders(), {})
M.get_trade_detail_data = _gtdB


# ---------------------------------------------------------------------------
# THE LAST THREE 2026-09-01 SELL-SIDE FIXES, MIRRORED HERE.
# All three are the same thing: a cancel that re-quotes at the price the order
# is ALREADY resting at can only lose queue position.
# ---------------------------------------------------------------------------
import io as _io_sync   # this file did not import io; the sync checks below need it
_srcS = _io_sync.open(_osB.path.join(ROOT, "combo_buy_dual_model.py")).read()

# 1. the QUEUE branch must have no age backstop. COMPETE keeps one: an order
#    resting at a counterparty price from minutes ago really can go stale.
_qb = _srcS.split("outbid at the touch")[1].split("elif (now_m - placed) >= STALE_ORDER_MIN")[0]
# Look for the CODE, not the name: the comment explaining why the backstop
# was removed mentions CANCEL_BACKSTOP_MIN, and a bare substring test
# matched that and failed on correct code.
check("the QUEUE branch has no age backstop",
      "elif (now_m - placed) >= CANCEL_BACKSTOP_MIN:" in _qb, False)
check("...and COMPETE still has one", _srcS.count("touch unchanged but"), 1)

# 2. ADOPT must recover the price, not just the age. Without it _ref stays 0
#    and every order surviving a restart is pulled as "no reference price".
check("_order_price exists", hasattr(M, "_order_price"), True)


class _P1(object):
    m_dLimitPrice = 13.44


class _P2(object):
    pass


class _P3(object):
    m_dLimitPrice = 0
    m_dOrderPrice = 13.43


check("a limit price is read", M._order_price(_P1()), 13.44)
# 0.0 means UNKNOWN, and the caller must not treat it as a price of zero.
check("no usable field returns 0.0", M._order_price(_P2()), 0.0)
check("a zero first field falls through", M._order_price(_P3()), 13.43)
_adopt = _srcS.split("ADOPT pre-restart order")[0][-1400:]
check("ADOPT records the price", "_order_price(o)" in _adopt, True)
check("...and reads the code off the row, not _ocode",
      "_acode = (getattr(o" in _adopt, True)

# 3. MODE_OVERRIDE: a per-name mode set at paste time, for the days the file
#    channel cannot be read at all.
check("MODE_OVERRIDE exists", hasattr(M, "MODE_OVERRIDE"), True)
check("...and is empty by default", M.MODE_OVERRIDE, {})
check("...and wins over the file", "S.mode_by_code.update(MODE_OVERRIDE)" in _srcS, True)

if fails:
    print("FAILED %d check(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CHECKS PASSED")
print("=" * 88)
sys.exit(1 if fails else 0)
