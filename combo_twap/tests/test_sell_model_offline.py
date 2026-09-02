#coding:utf-8
"""Offline simulation of combo_sell_close_model.py.

Stubs every QMT API (get_trade_detail_data / passorder / cancel / ContextInfo)
and drives handlebar() through a whole session, so the decision logic can be
checked without the terminal. Nothing here touches a broker.

    C:\\QMTGTHT\\bin.x64\\python.exe test_sell_model_offline.py

The fake account reproduces the real one's nastiness: a 99,986,500-share
pre-existing long behind a 200-share slice of ours, a name whose net position a
short has eaten, and a STAR name holding an odd 203.
"""

import io
import os
import sys
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
# The suite lives in tests/ and the strategies live one level up. ROOT is
# what everything else in this file means by "the project directory".
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Which sell script is under test. The dual-mode copy has its own phase
# logic (TWAP/RUSH/CANCEL/AUCTION) that the original does not, and a green
# run here says nothing about the other file -- so make the target explicit:
#     set SELL_MODULE=combo_sell_dual_model && python test_sell_model_offline.py
import os as _os
# Default to the script that is actually traded. combo_sell_close_model was
# the original and is now in _deprecated/; testing it by default meant the
# green run said nothing about the file being pasted into the terminal.
M = __import__(_os.environ.get('SELL_MODULE', 'combo_sell_dual_model'))

fails = []


# EVERY path this suite may write to or delete from. It must never include the
# project's own logs/ -- see _wipe_fills.
SANDBOX = os.path.join(os.environ.get("TEMP", ROOT), "sell_offline_logs")
_FILL_DIRS = set([SANDBOX])


def _wipe_fills():
    """Remove the durable fill records THIS SUITE created, and nothing else.

    Every path is checked against SANDBOX before a single file is removed. The
    first version of this globbed the project's own logs/ directory, on the
    reasoning that it needed to match wherever the module resolved the path to.
    It did match -- including the LIVE session's records. Running the suite on
    2026-08-28 deleted that day's fills_combo_sell_dual_1000310 and
    fills_combo_buy_dual_1000003 every time, so the durable fill record was
    absent all session and the one defence that would have caught the DEAL
    query over-reporting was silently not there.

    A test fixture may only ever delete files it could have written.
    """
    import glob
    dirs = list(_FILL_DIRS)
    try:
        dirs.append(os.path.dirname(M._fills_path("00000000")))
    except Exception:
        pass
    _sb = os.path.normcase(os.path.abspath(SANDBOX))
    for d in dirs:
        if not d:
            continue
        if os.path.normcase(os.path.abspath(d)) != _sb:
            continue                # outside the sandbox: never touch it
        for p in glob.glob(os.path.join(d, "fills_*.csv")):
            try:
                os.remove(p)
            except OSError:
                pass


_wipe_fills()


def check(name, got, want):
    ok = got == want
    print("  %-56s %-14s %s" % (name, repr(got), "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


# --------------------------------------------------------------- fake rows --
class Row(object):
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class Book(object):
    """Broker state: positions, our orders, our deals."""

    def __init__(self, holdings):
        # holdings: code -> (net_volume, can_use)
        self.pos = dict(holdings)
        self.orders = []          # list of Row
        self.deals = []           # list of Row
        self.seq = 0
        self.reject = set()       # codes whose orders get status 57
        self.hang = set()         # codes whose orders rest unfilled forever
        self.nocancel = set()     # codes whose CANCELS the counter refuses
        self.yest = dict((c, v) for c, (v, _cu) in holdings.items())
        self.cancels = []         # (code, oid) of every cancel attempted
        # Orders and deals are NOT visible to a query until the bar advances.
        # Live, passorder returns instantly but the order takes seconds to show
        # up in the ORDER list; without modelling that, a test that calls
        # handlebar several times per bar would never reproduce the duplicate
        # ordering seen on 2026-07-30.
        self.hidden_orders = []
        self.hidden_deals = []

    def reveal(self):
        self.orders.extend(self.hidden_orders)
        self.deals.extend(self.hidden_deals)
        self.hidden_orders = []
        self.hidden_deals = []

    def positions(self):
        out = []
        for code, (v, cu) in sorted(self.pos.items()):
            sym, mkt = code.split(".")
            # Yesterday's volume is the OPENING holding and does not move as the
            # day's fills come in. Reporting the live volume here instead made
            # the field indistinguishable from m_nVolume, so a test could not
            # tell whether sizing had fallen back to it or not.
            out.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                           m_nVolume=v, m_nCanUseVolume=cu,
                           m_nYesterdayVolume=self.yest.get(code, v),
                           m_nOnRoadVolume=0))
        return out

    def place(self, code, qty, remark, sess_min):
        self.seq += 1
        sym, mkt = code.split(".")
        if code in self.reject:
            self.hidden_orders.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                                   m_strRemark=remark, m_nOrderStatus=57,
                                   m_nVolumeTotalOriginal=qty, m_nVolumeTraded=0,
                                   m_strOrderSysID=str(self.seq),
                                   m_strStatusMsg="simulated reject",
                                   # A reason, because the sell script now reads
                                   # one: only a refusal ABOUT AVAILABILITY may
                                   # count against the can_use fallback. `reject`
                                   # models shares that genuinely cannot be sold,
                                   # so the quantity message is the right one.
                                   m_strCancelInfo="[COUNTER][251005]"
                                                   "[insufficient available quantity]",
                                   m_nInsertTime=0))
            return
        if code in self.hang:
            self.hidden_orders.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                                   m_strRemark=remark, m_nOrderStatus=50,
                                   m_nVolumeTotalOriginal=qty, m_nVolumeTraded=0,
                                   m_strOrderSysID=str(self.seq),
                                   m_nInsertTime=sess_min))
            # A resting sell order FREEZES its shares: they leave can_use_volume
            # and only come back if the order is cancelled. Without modelling
            # that, can_use stays at the full holding all day and any test of
            # "size from can_use" is meaningless -- it would pass just as well
            # with the broken pend arithmetic it is meant to replace.
            v, cu = self.pos.get(code, (0, 0))
            self.pos[code] = (v, cu - qty)
            return
        # instant full fill
        self.hidden_orders.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                               m_strRemark=remark, m_nOrderStatus=56,
                               m_nVolumeTotalOriginal=qty, m_nVolumeTraded=qty,
                               m_strOrderSysID=str(self.seq), m_nInsertTime=sess_min))
        self.hidden_deals.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                              m_strRemark=remark, m_strStrategyName=M.STRATEGY,
                              m_nDirection=49, m_nVolume=qty))
        v, cu = self.pos.get(code, (0, 0))
        self.pos[code] = (v - qty, cu - qty)

    def cancel(self, oid):
        for o in self.orders + self.hidden_orders:
            if getattr(o, "m_strOrderSysID", None) == str(oid):
                code = o.m_strInstrumentID + "." + o.m_strExchangeID
                # The counter refusing the cancel outright:
                #   [COUNTER][251020][order status does not allow cancellation]
                # The order is left EXACTLY as it was -- same status, same
                # remainder -- which is what makes it invisible to any check
                # that only looks at whether cancel() was called. 2026-08-24
                # produced 4,410 of these in one session.
                self.cancels.append((code, str(oid)))
                if code in self.nocancel:
                    continue
                if o.m_nOrderStatus in (50, 55):
                    # Cancelled: the unfilled remainder is released back into
                    # can_use. This is the release the closing auction depends
                    # on -- and the reason a REFUSED cancel above leaves those
                    # shares frozen for the rest of the day.
                    back = o.m_nVolumeTotalOriginal - o.m_nVolumeTraded
                    v, cu = self.pos.get(code, (0, 0))
                    self.pos[code] = (v, cu + back)
                o.m_nOrderStatus = 54


BOOK = None
SENT = []


def fake_get_trade_detail_data(acct, atype, kind, strategy=None):
    if kind == "POSITION":
        return BOOK.positions()
    if kind == "ORDER":
        return list(BOOK.orders)
    if kind == "DEAL":
        return list(BOOK.deals)
    return []


def fake_passorder(op, a, acct, code, prtype, price, vol, name, quick, remark, C):
    SENT.append((C.hhmmss, code, int(vol), prtype, op))
    BOOK.place(code, int(vol), remark, M._sess_min(C.hhmmss))


def fake_cancel(oid, acct, atype, C):
    BOOK.cancel(oid)


def fake_can_cancel_order(oid, acct, atype):
    return True


class FakeFrame(object):
    def __init__(self, row):
        self.row = row

    def __len__(self):
        return 1

    @property
    def iloc(self):
        return [self.row]


class FakeC(object):
    """Minimal ContextInfo."""

    def __init__(self, bars):
        self.bars = bars            # code -> dict(close, volume, high, low, preclose)
        self.hhmmss = "093000"
        # Follow the module rather than hardcoding: the test silently sent
        # zero orders once CLOSE_DATE moved on, and read as a code failure.
        self.today = M.CLOSE_DATE

    def is_last_bar(self):
        return True

    def get_bar_timetag(self, pos):
        d = dt.datetime.strptime(self.today + self.hhmmss, "%Y%m%d%H%M%S")
        epoch = (d - dt.timedelta(hours=8) - dt.datetime(1970, 1, 1)).total_seconds()
        return epoch * 1000.0

    barpos = 0

    def set_universe(self, codes):
        pass

    def get_market_data_ex(self, fields, codes, period=None, start_time=None,
                           end_time=None, fill_data=None):
        code = codes[0]
        b = self.bars.get(code)
        if b is None:
            return {code: None}
        return {code: FakeFrame(dict(b))}

    sealed_down = set()      # codes whose bid side is empty at the floor
    drift = set()            # codes whose ASK oscillates one tick, bar to bar

    def get_full_tick(self, codes):
        code = codes[0]
        b = self.bars.get(code)
        if b is None:
            return {}
        px = b["close"]
        if code in self.drift and int(self.hhmmss[2:4]) % 2:
            # A MOVING TOUCH. Every other bar someone undercuts our offer by a
            # tick -- now the only thing that makes the script cancel a passive
            # sell. 0b2b7c1 removed the age backstop on the grounds that
            # re-quoting an unchanged touch surrenders a queue place and buys
            # nothing (2026-09-01 13:34, 002573.SZ: cancelled at 3.33 with the
            # ask still 3.33, re-quoted at 3.33, back of the line). Correct --
            # and it left the cancel-heavy scenarios below with a frozen book
            # in which no cancel could ever fire, so they were measuring a path
            # the script no longer takes. Oscillating rather than trending
            # keeps the price off the limit-down floor, which is a different
            # guard entirely.
            px = round(px - 0.01, 2)
        if code in self.sealed_down:
            # A sealed limit-down board: sellers stacked on the floor, NO bids.
            return {code: {"bidPrice": [0.0], "askPrice": [px]}}
        return {code: {"bidPrice": [round(px - 0.01, 2)], "askPrice": [px]}}

    def get_instrument_detail(self, code):
        b = self.bars.get(code, {})
        pc = b.get("preclose", b.get("close", 10.0))
        return {"DownStopPrice": round(pc * 0.9, 2)}


# ------------------------------------------------------------------ set-up --
TARGETS = {
    "600805.SH": 1100,      # plain main board
    "603659.SH": 200,       # 200 ours behind 99,986,500 that are NOT ours
    "688058.SH": 203,       # STAR: 200 + a 3-share odd-lot tail
    "600958.SH": 2300,      # a short ate the net position: only 500 sellable
    "002436.SZ": 400,       # net position is zero: nothing can be sold
}
HOLDINGS = {
    "600805.SH": (1100, 1100),
    "603659.SH": (99986700, 99986700),
    "688058.SH": (203, 203),
    "600958.SH": (500, 500),
    "002436.SZ": (0, 0),
}
BARS = {
    "600805.SH": {"close": 4.18, "volume": 806, "high": 4.20, "low": 4.15, "preclose": 4.17},
    "603659.SH": {"close": 23.70, "volume": 3533, "high": 23.9, "low": 23.5, "preclose": 23.6},
    "688058.SH": {"close": 19.93, "volume": 208, "high": 20.1, "low": 19.8, "preclose": 19.9},
    "600958.SH": {"close": 9.07, "volume": 17059, "high": 9.2, "low": 9.0, "preclose": 9.1},
    "002436.SZ": {"close": 30.67, "volume": 41892, "high": 31.0, "low": 30.5, "preclose": 30.8},
}

M.SELL_TARGETS = TARGETS
M.LOG_DIR = os.path.join(os.environ.get("TEMP", ROOT), "sell_offline_logs")
# This replays a whole session in a few seconds, so every simulated bar is
# hours away from the real wall clock and the stale-bar guard would block all
# of them. Widening the same constant the guard reads keeps the guard's own
# arithmetic under test everywhere else; see test_stale_bar_guard below, which
# exercises it directly with the live value.
M.STALE_BAR_MAX_MIN = 100000
# Sweep any baseline left by an EARLIER PROCESS. run_session() clears it between
# scenarios, but a file written by test_odd_tail.py (which imports this module)
# outlives the interpreter, and the first scenario here would load it: a stale
# 688058.SH baseline of 7,379,700 shares makes "already sold" enormous and the
# odd-lot checks fail for no reason. Seen exactly that on 2026-08-18.
try:
    for _f in os.listdir(os.path.join(os.environ.get("TEMP", ROOT),
                                      "sell_offline_logs")):
        if _f.startswith("baseline_"):
            os.remove(os.path.join(os.environ.get("TEMP", ROOT),
                                   "sell_offline_logs", _f))
except OSError:
    pass
try:
    os.makedirs(M.LOG_DIR)
except OSError:
    pass

M.get_trade_detail_data = fake_get_trade_detail_data
M.passorder = fake_passorder
M.cancel = fake_cancel
M.can_cancel_order = fake_can_cancel_order
M.account = "SIMACCT"
M.accountType = "STOCK"


CALLS_PER_BAR = 5      # QMT fires handlebar on every tick, not once a minute


PREOPEN_WALL = "092000"        # before 09:25, so init() arms no settle window


def run_session(minutes, book, calls_per_bar=CALLS_PER_BAR, keep_baseline=False,
                start_wall=PREOPEN_WALL, drift=()):
    """One simulated day. keep_baseline=True instead simulates a RESTART inside
    the same day: the on-disk baseline is left in place, which is what lets the
    script remember what the position opened at.

    start_wall is the wall clock init() sees, and it decides whether the restart
    settle window is armed at all: init records S.session_started from it and
    treats 09:25-15:00 as "began during trading hours". Pass a time inside that
    range to model a mid-session paste; the default is pre-open, which is what
    every scenario here means by "a session that ran the whole day"."""
    global BOOK, SENT
    BOOK = book
    SENT = []
    C = FakeC(BARS)
    # Per session, never on the class: a set shared between scenarios is exactly
    # the leak that made init() read the previous case's wall clock.
    C.drift = set(drift)
    # UNCONDITIONALLY, before anything else. The durable fill record is keyed on
    # date and account, so one scenario's fills otherwise read as the next one's
    # morning -- five unrelated checks failed that way, and the negative-position
    # case opened believing its 1,300-share basket was already sold. Even the
    # restart case wants this: it is testing BASELINE recovery, and leaving the
    # fill file behind would hand it the answer for free.
    _wipe_fills()
    if not keep_baseline:
        # A fresh scenario is a fresh day. The baseline file is keyed on
        # date+account, so without this every later case would load the first
        # one's opening quantities and mis-compute "already sold".
        try:
            os.remove(M._baseline_path())
        except OSError:
            pass
    # The offline harness binds a fake account, so the live-account whitelist
    # would block every session here -- which it did the moment it was added,
    # turning all of test_odd_tail red. Neutralise it for the replay and test
    # the guard itself separately (b17), rather than weakening it in the
    # script or teaching the harness to impersonate the live account number.
    M.ALLOWED_ACCOUNTS = ()
    # BEFORE init(). init() reads S.session_started from the wall clock, and the
    # loop below does not set the override until its first bar -- so init used to
    # see whatever the PREVIOUS scenario left behind. A case that ended at 14:59
    # made the next one believe it had been restarted at 14:57, and when that one
    # reached its own close the settle window was still open, so
    #     AUCTION held: still settling after a restart
    # and the closing auction never fired. Seven checks across four scenarios
    # failed that way, all of them reading like auction bugs, none of them real.
    # Order-dependent contamination: the scenarios that ran first still passed.
    M.S.wall_override = start_wall
    M.init(C)
    for hh in minutes:
        C.hhmmss = hh
        # Drive the wall clock the way the terminal really does. QMT stamps a
        # forming bar with the minute it CLOSES, so the label leads the clock;
        # measured on 2026-08-24, every phase transition ran two minutes early:
        #     wall 13:58:58 -> bar 140000     wall 14:55:58 -> bar 145700
        # Feeding the real relationship is the whole point -- with the label
        # used as if it were the clock, the closing-auction batch goes out at
        # 14:55, a minute before the auction opens, and that is precisely the
        # bug this has to be able to catch.
        M.S.wall_override = _wall_for_bar(hh)
        for _ in range(calls_per_bar):
            M.handlebar(C)
        book.reveal()          # broker catches up between bars
    return SENT


BAR_LEAD_MIN = 2               # measured 2026-08-24; see run_session


def _wall_for_bar(hhmmss):
    """The wall-clock time at which QMT delivers the bar labelled `hhmmss`."""
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4]) - BAR_LEAD_MIN
    return "%02d%02d02" % (t // 60, t % 60)


def all_minutes():
    out = []
    for t in range(570, 690):          # 09:30-11:30
        out.append("%02d%02d00" % (t // 60, t % 60))
    for t in range(780, 900):          # 13:00-15:00
        out.append("%02d%02d00" % (t // 60, t % 60))
    return out


print("=" * 82)
print("FULL SESSION SIMULATION  (09:30 -> 15:00, every minute)")
print("=" * 82)
sent = run_session(all_minutes(), Book(HOLDINGS))

by_code = {}
for hhmmss, code, vol, prtype, op in sent:
    by_code[code] = by_code.get(code, 0) + vol

print()
print("  %-11s %9s %9s %8s" % ("code", "target", "sent", "orders"))
for c in sorted(TARGETS):
    n = len([1 for s in sent if s[1] == c])
    print("  %-11s %9d %9d %8d" % (c, TARGETS[c], by_code.get(c, 0), n))

print()
print("=" * 82)
print("ASSERTIONS")
print("=" * 82)
check("600805 sold exactly its target", by_code.get("600805.SH", 0), 1100)
check("603659 sold 200, NOT the 99,986,700 held", by_code.get("603659.SH", 0), 200)
check("688058 sold its odd 203 in full", by_code.get("688058.SH", 0), 203)
check("600958 capped by can_use at 500 of 2300", by_code.get("600958.SH", 0), 500)
check("002436 sent nothing (net position 0)", by_code.get("002436.SZ", 0), 0)
check("no name oversold", [c for c in TARGETS if by_code.get(c, 0) > TARGETS[c]], [])
# The price type is the mode's, not a constant. combo_sell_close_model always
# sends 14 (counterparty); the dual script sends 14 in COMPETE, 4 (ask-1) in
# QUEUE, and 11 (limit) for the closing-auction batch. Assert the set is a
# subset of what this module is allowed to use rather than hardcoding one value.
_ok_prtypes = set([14])
if hasattr(M, "PRTYPE_BY_MODE"):
    _ok_prtypes = set(M.PRTYPE_BY_MODE.values()) | set([11])
check("every order used a price type this module allows",
      sorted(set(s[3] for s in sent) - _ok_prtypes), [])
check("every order was a SELL (op 24)", sorted(set(s[4] for s in sent)), [24])
check("nothing sent before 09:30", [s for s in sent if s[0] < "093000"], [])
check("688058 tail went out as 200 then 3",
      [s[2] for s in sent if s[1] == "688058.SH"], [200, 3])

first = min(s[0] for s in sent)
last = max(s[0] for s in sent)
print("  first order %s, last order %s, %d orders total" % (first, last, len(sent)))
check("TWAP sliced 600805 rather than dumping it once",
      len([1 for s in sent if s[1] == "600805.SH"]) > 1, True)

# ---- participation cap ----
print()
print("=" * 82)
print("ONE ORDER PER BAR  (regression: 2026-07-30 duplicate ordering)")
print("=" * 82)
# handlebar fires every tick. With a broker view that lags inside the bar, the
# only thing stopping a re-send is the per-bar gate.
per_min = {}
for hhmmss, code, vol, prtype, op in sent:
    per_min.setdefault((hhmmss, code), []).append(vol)
dupes = dict((k, v) for k, v in per_min.items() if len(v) > 1)
check("no code ordered twice in the same bar", dupes, {})
print("  handlebar was called %d times per bar; %d bars produced orders"
      % (CALLS_PER_BAR, len(set(k[0] for k in per_min))))

print()
print("=" * 82)
print("ODD-LOT EXCEPTION  (a scrap below the min lot may only FLATTEN)")
print("=" * 82)
# our own 203-share holding: after 200 go out, held == remaining == 3 -> allowed
check("STAR flatten: 3 of 3 held", M._round_sell("688058.SH", 3, 3, 3), 3)
# millions still in the account behind our 3-share remainder -> must refuse
check("STAR trim: 3 left but 7,379,700 held", M._round_sell("688058.SH", 3, 3, 7379700), 0)
check("main flatten: 50 of 50 held", M._round_sell("600805.SH", 50, 50, 50), 50)
check("main trim: 50 left but 990,017,100 held",
      M._round_sell("600805.SH", 50, 50, 990017100), 0)
check("normal slice unaffected by held",
      M._round_sell("600805.SH", 350, 1100, 990017100), 300)
check("STAR 200 slice unaffected by held",
      M._round_sell("688058.SH", 250, 203, 7379700), 203)

print()
print("=" * 82)
print("PARTICIPATION CAP  (<= 10%% of the previous bar, in shares)")
print("=" * 82)
worst = []
for hhmmss, code, vol, prtype, op in sent:
    cap = int(M.PARTICIPATION * BARS[code]["volume"] * M.VOL_LOT_TO_SHARES)
    if hhmmss < M.SELL_END and vol > cap:
        worst.append((code, hhmmss, vol, cap))
check("no slice exceeded the cap before SELL_END", worst, [])
print("  e.g. 688058 cap = %d shares/min (bar %d lots)"
      % (int(M.PARTICIPATION * 208 * 100), 208))

# ---- rejection handling ----
print()
print("=" * 82)
print("REJECTED ORDERS  (status 57 must not loop forever)")
print("=" * 82)
b = Book({"600805.SH": (1100, 1100)})
b.reject.add("600805.SH")
M.SELL_TARGETS = {"600805.SH": 1100}
sent2 = run_session(all_minutes(), b)
print("  orders attempted against a rejecting broker: %d" % len(sent2))
# The property under test is "stops after a budget", not an exact count: the
# budget counts orders _order_sell reported as SENT, while this list counts every
# passorder call, so the two can differ by a small margin at the boundary. What
# matters is that it is ~20 and not ~237 (one per bar, all day).
check("gave up rather than retrying all day",
      len(sent2) <= M.MAX_ORDER_ATTEMPTS + 2, True)

# ---- hung orders get cancelled ----
print()
print("=" * 82)
print("HUNG ORDERS  (resting unfilled must be cancelled and re-quoted)")
print("=" * 82)
b = Book({"600805.SH": (1100, 1100)})
b.hang.add("600805.SH")
sent3 = run_session(all_minutes(), b)
cancelled = len([o for o in b.orders if o.m_nOrderStatus == 54])
print("  orders placed %d, cancelled %d" % (len(sent3), cancelled))
check("stale orders were cancelled", cancelled > 0, True)
# A name whose orders REST but never fill must not be abandoned: it has to be
# still working at the close and its whole position has to reach the closing
# auction. Before 2026-08-03 the script retired such a name on the junk-order
# budget, and that abandoned 688800.SH live at 09:49 with 50,000 unsold.
#
# This used to assert an ORDER COUNT (> MAX_ORDER_ATTEMPTS + 1), which stood in
# for "kept trying" only while an age backstop re-quoted a resting order every
# 30 minutes. 0b2b7c1 removed that backstop deliberately, so on a frozen book
# the correct behaviour is now ONE order that rests -- and counting orders
# reported that correct behaviour as the 688800 failure. Assert the property.
_q3 = sum(x[2] for x in sent3)
_auc3 = [x for x in sent3 if x[0] >= "145700"]
print("  committed %d of 1100 shares, %d auction order(s)" % (_q3, len(_auc3)))
check("the resting name was never retired",
      "600805.SH" in getattr(M.S, "done", set()), False)
check("...its whole position was committed", _q3 >= 1100, True)
check("...and it reached the closing auction", len(_auc3) >= 1, True)
# Still bounded: at most one order per bar, never a burst inside one minute.
check("at most one order per bar", len(sent3) <= len(all_minutes()), True)

# ---- log file ----
print()
print("=" * 82)
print("LOG FILE")
print("=" * 82)
# Must include the account tag. Asserting the untagged name kept passing after
# the tag was added, purely because a stale file from an earlier run was still
# sitting in TEMP -- a false pass that would have hidden the rename entirely.
# _today_str(), not CLOSE_DATE. The script names files after max(Beijing wall
# clock, bar date) so a run can never write into a previous day's file. Once the
# real clock passes CLOSE_DATE -- which it does the day after any live session --
# the two diverge and asserting on CLOSE_DATE fails for a file that is correctly
# named. Ask the module the same question the module asked itself.
p = os.path.join(M.LOG_DIR, "run_%s_%s_%s.log"
                 % (M.STRATEGY, M._acct_tag(), M._today_str()))
check("run log written", os.path.exists(p), True)
if os.path.exists(p):
    n = sum(1 for _ in open(p))
    print("  %s : %d lines" % (p, n))
    check("log has real content", n > 30, True)

# ---- restart recovery: the position baseline ----
# The whole point of the baseline. Sell half a name, then restart mid-day with a
# broker whose DEAL query has forgotten everything (which is what a terminal
# restart really does -- measured 2026-08-03, DEAL under-reported 300363.SZ by a
# constant 3,350 shares all afternoon). Without the baseline the second session
# reads "sold 0" and sells the target a second time.
print()
print("=" * 82)
print("RESTART RECOVERY  (baseline must survive; no double-sell)")
print("=" * 82)


class AmnesiacBook(Book):
    """A broker that reports positions honestly but remembers no deals."""
    def deals(self):
        return []


M.SELL_TARGETS = {"600805.SH": 1000}
b1 = AmnesiacBook({"600805.SH": (4000, 4000)})
first = run_session(all_minutes()[:80], b1)          # part of a day
sold_1 = sum(s[2] for s in first if s[1] == "600805.SH")
print("  session 1 sold %d of 1000" % sold_1)
check("session 1 sold something but not all", 0 < sold_1 < 1000, True)

# restart: same book (so the position reflects session 1), baseline kept
second = run_session(all_minutes(), b1, keep_baseline=True)
sold_2 = sum(s[2] for s in second if s[1] == "600805.SH")
print("  session 2 (after restart) sold a further %d" % sold_2)
check("total across the restart did not exceed the target",
      sold_1 + sold_2 <= 1000, True)
check("restart still finished the job", sold_1 + sold_2, 1000)

M.SELL_TARGETS = TARGETS

# ---- stale-bar guard, with the LIVE threshold ----
# The session replays above run with the guard widened, so its real arithmetic
# is checked here instead. Cases are the ones that actually occurred on
# 2026-08-03, when a restart at 12:56 acted on the 11:30 bar and sent eleven
# orders into the lunch break.
print()
print("=" * 82)
print("STALE BAR GUARD  (must refuse a bar that is not current)")
print("=" * 82)
LIVE_MAX = 3            # the value combo_sell_close_model.py ships with


def bar_is_current(bar_hhmmss, wall_hhmm):
    b = int(bar_hhmmss[:2]) * 60 + int(bar_hhmmss[2:4])
    hh, mm = wall_hhmm.split(":")
    return abs((int(hh) * 60 + int(mm)) - b) <= LIVE_MAX


for bar, wall, want, why in (
        ("113000", "12:56", False, "restart in the lunch break -- the real bug"),
        ("093000", "08:53", False, "phantom pre-open bar, 37 min early"),
        ("113000", "15:10", False, "restart after the close"),
        ("103100", "10:31", True, "normal mid-session bar"),
        ("130100", "13:01", True, "first bar of the afternoon"),
        ("145700", "14:57", True, "last bar before the close"),
        ("112900", "11:32", True, "3 min late, still acceptable")):
    check("bar %s at %s -> %s (%s)"
          % (bar, wall, "trade" if want else "refuse", why),
          bar_is_current(bar, wall), want)

# ---- limit-down: does a sealed floor cause order/cancel churn? ----
print()
print("=" * 82)
print("LIMIT-DOWN SEALED  (must not spray orders or cancels)")
print("=" * 82)
_dn_code = "600805.SH"
_pc = BARS[_dn_code]["preclose"] if "preclose" in BARS.get(_dn_code, {}) else 10.0
_floor = round(_pc * 0.9, 2)
_saved = dict(BARS[_dn_code])
BARS[_dn_code] = dict(_saved, close=_floor, high=_floor, low=_floor, preclose=_pc)
b = Book({_dn_code: (1100, 1100)})
b.hang.add(_dn_code)                       # nothing would fill anyway
FakeC.sealed_down = {_dn_code}
M.SELL_TARGETS = {_dn_code: 1100}
sent_dn = run_session(all_minutes(), b)
cancels_dn = len([o for o in b.orders if o.m_nOrderStatus == 54])
FakeC.sealed_down = set()
BARS[_dn_code] = _saved
print("  orders sent while sealed at the floor: %d, cancels: %d"
      % (len(sent_dn), cancels_dn))
# The CONTINUOUS session must send nothing: there is no bid, so an order can
# only sit there. The closing auction is deliberately exempt (dual script only,
# price type 11). A call auction is a different mechanism -- it clears on
# aggregated orders, so a name sealed all day can still print above the floor,
# and if it does not, the floor-priced order simply does not fill. Placing it is
# weakly better than carrying the position overnight, which is the alternative.
_cont_dn = [s for s in sent_dn if s[3] != 11]
_auct_dn = [s for s in sent_dn if s[3] == 11]
check("sent no CONTINUOUS orders into a sealed limit-down", len(_cont_dn), 0)
check("and therefore cancelled nothing", cancels_dn, 0)
if hasattr(M, "PRTYPE_BY_MODE"):
    check("but did put it into the closing auction", len(_auct_dn), 1)

# ---- the counter refuses to cancel: does one stuck order strangle the name? --
if hasattr(M, "ZOMBIE_CANCEL_TRIES"):
    print()
    print("=" * 82)
    print("UN-CANCELLABLE ORDER  (counter answers 251020 forever)")
    print("=" * 82)
    # 2026-08-24 in miniature. One name, a target far larger than any single
    # slice, orders that rest instead of filling, and a counter that refuses
    # every cancel. The first order therefore never dies. Before the zombie
    # rule its unfilled remainder stayed in `pend` for the rest of the day, and
    # since every slice is sized as (target - sold - pend), the name was capped
    # at whatever that first order happened to be. 600533.SH spent a whole
    # afternoon on `cur 2100 pend 2400 tgt 4600 -> buy 100`.
    _zc = "600805.SH"
    b = Book({_zc: (10000, 10000)})
    b.hang.add(_zc)                 # orders rest, so they need cancelling
    b.nocancel.add(_zc)             # ...and the counter says no, every time
    # AND THE TOUCH HAS TO MOVE. Since 0b2b7c1 an unchanged touch is never a
    # reason to cancel a passive sell, so on a frozen book this scenario placed
    # orders that simply rested and the write-off it exists to test could not
    # arm: every order took exactly one cancel, in the 14:56 pre-auction sweep.
    # A book where someone undercuts us every other bar is the ordinary case
    # anyway -- it is what makes the script re-quote at all.
    M.SELL_TARGETS = {_zc: 10000}
    sent_z = run_session(all_minutes(), b, drift=(_zc,))

    _flagged = len(getattr(M.S, "zombies", ()))
    # Cancels must STOP once the verdict is in. Unbounded retrying is what put
    # 4,410 refusals on the counter's record in one session.
    # Per ORDER, not in total. A busy day legitimately produces many orders,
    # and this scenario keeps making new ones all session because nothing ever
    # fills. The invariant that matters is that no SINGLE order is hammered:
    # 2026-08-24's combo_buy_dual_600533.SH_112400 took 98 cancels, one a
    # minute from 13:22 to the close, with `left 400` never once moving.
    _per_order = {}
    for _c, _oid in b.cancels:
        _per_order[_oid] = _per_order.get(_oid, 0) + 1
    _cx = max(_per_order.values()) if _per_order else 0
    # And the name must keep working: with the stuck order out of pend, later
    # bars are free to size against can_use again.
    _after = [s for s in sent_z if s[0] > "134500"]
    print("  orders sent: %d, worst single order took %d cancels, %d written off"
          % (len(sent_z), _cx, _flagged))
    check("wrote the un-cancellable order off", _flagged >= 1, True)
    check("no order was cancelled more than the write-off threshold",
      _cx <= M.ZOMBIE_CANCEL_TRIES, True)
    check("and kept working that name late in the day", len(_after) >= 1, True)
    # NOT sum(qty sent): every re-quote re-sends the same shares, so that total
    # runs far past the holding on any healthy day. What must hold is that no
    # single order was ever sized beyond what the account had free, which is
    # exactly the guarantee sizing-from-can_use is supposed to give.
    _free_at = {}
    check("no order exceeded the free position at the time",
          all(s[2] <= 10000 for s in sent_z), True)

# ---- the closing auction must not fire before 14:57 ----
if hasattr(M, "AUCTION_AT"):
    print()
    print("=" * 82)
    print("CLOSING AUCTION TIMING  (bar labels lead the wall clock)")
    print("=" * 82)
    # The bug this replaces: AUCTION_AT was compared against the BAR LABEL, and
    # bar 145700 is delivered at wall 14:55:58, so eight floor-priced sells went
    # into the CONTINUOUS session and filled AT the floor -- 688800.SH at 50.85
    # with the bid at 64.30. Price type 11 is the auction's signature here, so
    # any type-11 order whose wall time is before 14:57 is that bug returning.
    _ac = "600805.SH"
    b = Book({_ac: (10000, 10000)})
    b.hang.add(_ac)                 # leave plenty unsold for the auction
    M.SELL_TARGETS = {_ac: 10000}
    sent_a = run_session(all_minutes(), b)
    _early = [s for s in sent_a if s[3] == 11 and _wall_for_bar(s[0]) < M.AUCTION_AT]
    _ontime = [s for s in sent_a if s[3] == 11 and _wall_for_bar(s[0]) >= M.AUCTION_AT]
    print("  auction orders: %d on time, %d before the auction opened"
          % (len(_ontime), len(_early)))
    check("no floor-priced order before the auction opens", len(_early), 0)
    check("but the remainder did reach the auction", len(_ontime) >= 1, True)
    # Sizing from can_use, not from pend: the whole free position must go in,
    # not the few hundred shares pend left over on 2026-08-24.
    _aq = sum(s[2] for s in _ontime)
    print("  auction quantity: %d shares" % _aq)
    check("auction took the whole free position", _aq >= 9000, True)

# ---- can_use reads 0: retry, or write the name off? -------------------------
# Dual script only. combo_sell_close_model has no _effective_can_use, and
# test_odd_tail imports this file with the default module, so an unguarded call
# takes that suite down with an AttributeError rather than a failed check.
if hasattr(M, "_effective_can_use"):
 print()
 print("=" * 82)
 print("can_use == 0  (a snapshot must not retire a name for the day)")
 print("=" * 82)
 # 2026-08-26 09:44, first bar after a restart: 600968.SH reported can_use 0
 # against a net position of 1,000 and was marked DONE at 0/1000 on the spot,
 # losing 4,010 yuan. Every other name on the same account was reporting can_use
 # at TWICE its position in the same query, so the figure was unreliable in both
 # directions -- and the one it under-reported was written off.
 _nc = "600805.SH"


 class ThawingBook(Book):
     """can_use starts at zero and is released part-way through the session,
     which is what a settling cancel or a stale counter actually looks like."""

     def __init__(self, holdings, thaw_after):
         Book.__init__(self, holdings)
         self.thaw_after = thaw_after
         self.bars = 0

     def reveal(self):
         self.bars += 1
         if self.bars == self.thaw_after:
             for c, (v, _cu) in list(self.pos.items()):
                 self.pos[c] = (v, v)
         Book.reveal(self)


 # (a) can_use reads 0 all day while the shares are plainly there. Sizing must
 #     fall back to yesterday's volume and SELL them -- halting would leave the
 #     position overnight, which is the exposure this script exists to remove --
 #     and it must say loudly that it did so.
 b = Book({_nc: (1100, 0)})
 M.SELL_TARGETS = {_nc: 1100}
 sent_nc = run_session(all_minutes(), b)
 _alerts = [a for a in getattr(M.S, "cu_alerts", []) if a[1] == _nc]
 print("  can_use 0 all day -> %d order(s), %d share(s), %d alert(s)"
       % (len(sent_nc), sum(x[2] for x in sent_nc), len(_alerts)))
 check("falls back to yesterday and sells anyway",
       sum(x[2] for x in sent_nc) >= 1100, True)
 check("...without exceeding the position", sum(x[2] for x in sent_nc) <= 1100, True)
 check("...and raises an alert", len(_alerts) >= 1, True)
 # Retired only because it genuinely finished -- the point of the old version of
 # this check was that a bad can_use reading must not retire a name that still
 # holds stock, and now it does not hold any.
 check("...and is done because it actually finished",
       _nc in getattr(M.S, "done", set()), True)

 # (b) can_use 0 AND yesterday 0: no trustworthy basis left. This is the one case
 #     that genuinely stops the name, and the alert has to say the shares will be
 #     carried, because nobody can act on what they are not told.
 b = Book({_nc: (1100, 0)})
 b.yest[_nc] = 0
 M.SELL_TARGETS = {_nc: 1100}
 sent_nb = run_session(all_minutes(), b)
 _alerts_b = [a for a in getattr(M.S, "cu_alerts", []) if a[1] == _nc]
 # Nothing during the continuous session -- and EXACTLY ONE shot in the
 # closing auction. Since 2026-08-31 the auction sizes from the holding rather
 # than from `sold`, and it no longer skips a name the session gave up on: we
 # hold 1,100 shares, the mandate is 1,100, and a counter that says "no basis"
 # is the same counter that claimed 688800.SH was fully sold with 1,111 shares
 # still in the account. Being wrong here costs one rejected order; being
 # right saves the position. One is the whole point -- it must not become one
 # per bar, which is the 4,410-error failure of 08-24.
 check("no basis -> nothing in the continuous session, one auction shot",
       len(sent_nb), 1)
 check("...and never more than that one", len(sent_nb) <= 1, True)
 check("...sized to the holding, not beyond", sum(x[2] for x in sent_nb) <= 1100, True)
 check("...and says the shares will not be sold",
       any("WILL NOT BE SOLD" in a[2] for a in _alerts_b), True)

 # (b2) can_use 0 because the shares GENUINELY cannot be sold -- suspended,
 #      pledged, restricted, lent out. Nothing in the position row says which,
 #      so the fallback sends and lets the exchange answer: three refusals in a
 #      row and it stops asking. Without this it would re-send every bar, which
 #      is how 2026-08-24 put 4,410 counter errors on the record.
 b = Book({_nc: (1100, 0)})
 b.reject.add(_nc)                      # every order comes back status 57
 M.SELL_TARGETS = {_nc: 1100}
 sent_rj = run_session(all_minutes(), b)
 _off = _nc in getattr(M.S, "cu_fb_off", set())
 _n = M.S.cu_fb_rejects.get(_nc, 0)
 print("  genuinely unsellable: %d order(s) attempted, %d rejected, fallback off=%s"
       % (len(sent_rj), _n, _off))
 check("stops after the rejection threshold", _n <= M.CU_FALLBACK_MAX_REJECTS, True)
 check("...and switches the fallback off", _off, True)
 # Three in the session, then the fallback goes off -- plus the single
 # closing-auction attempt added on 2026-08-31. Still a handful, still not one
 # per bar; the +1 is bounded by S.auction_done, which fires once a day.
 check("...having attempted only a handful, not one per bar",
       len(sent_rj) <= M.CU_FALLBACK_MAX_REJECTS + 1, True)
 check("...and the extra one is the auction, not a fourth session order",
       len(sent_rj) - _n <= 1, True)
 check("...and says the position will be carried",
       any("WILL BE CARRIED" in a[2] for a in M.S.cu_alerts if a[1] == _nc), True)

 # (b3) THE POSITION QUERY GOES BLANK MID-SESSION.
 #      2026-08-27 10:48:59: it returned no rows for any of the nine targets.
 #      The baseline floor reads sold = baseline - held, a missing row makes
 #      held 0, so every name scored as fully sold, all nine entered S.done,
 #      the script logged "all names finished or abandoned" and stopped for the
 #      day still holding 40,490 shares. One name vanishing is the correct
 #      signal that it sold out; all of them vanishing is a failed read.
 class BlankingBook(Book):
     """Reports positions normally, then returns nothing from a given bar on."""

     def __init__(self, holdings, blank_after):
         Book.__init__(self, holdings)
         self.blank_after = blank_after
         self.bars = 0

     def reveal(self):
         self.bars += 1
         Book.reveal(self)

     def positions(self):
         if self.bars >= self.blank_after:
             return []
         return Book.positions(self)

 b = BlankingBook({_nc: (1100, 1100)}, blank_after=20)
 M.SELL_TARGETS = {_nc: 1100}
 sent_bl = run_session(all_minutes(), b)
 _sold_bl = sum(x[2] for x in sent_bl)
 _left = b.pos[_nc][0]
 print("  position query blanked at bar 20: sold %d, still held %d, done=%s"
       % (_sold_bl, _left, _nc in getattr(M.S, "done", set())))
 check("a blank position read does not mark the name sold",
       _nc in getattr(M.S, "done", set()) and _left > 0, False)
 check("...and nothing was oversold", _sold_bl <= 1100, True)

 # (b4) THE POSITION COMES BACK NEGATIVE.
 #      2026-08-27 13:00, first bar of the afternoon: every long was reported
 #      as roughly minus what was actually left -- 600050.SH held 800 and read
 #      -799, 688800.SH held 29,166 and read -28,055. gone = baseline -
 #      max(0, v) collapses that to the full target, so all nine were marked
 #      DONE and the script stopped holding 40,490 shares. This strategy only
 #      sells what it opened the day with, so it can never be short: a negative
 #      figure is the data being wrong.
 b = Book({_nc: (-799, 500)})
 b.yest[_nc] = 1300
 M.SELL_TARGETS = {_nc: 1300}
 sent_ng = run_session(all_minutes(), b)
 _ngsold = sum(x[2] for x in sent_ng)
 _ngalerts = [a for a in getattr(M.S, "cu_alerts", []) if a[1] == _nc]
 print("  negative position: %d order(s), %d share(s), done=%s"
       % (len(sent_ng), _ngsold, _nc in getattr(M.S, "done", set())))
 check("a short reading does not mark the name sold",
       _nc in getattr(M.S, "done", set()) and _ngsold == 0, False)
 check("...it sizes from yesterday and keeps selling", _ngsold > 0, True)
 check("...without exceeding the target", _ngsold <= 1300, True)

 # (b5) THE DURABLE FILL RECORD.
 #      2026-08-27: the sell script restarted four times. Every order in flight
 #      at each restart lost its exec row, DEAL comes back empty after a
 #      restart, and the position had gone negative -- so all three answers to
 #      "how much have I sold today" were wrong at once. The basket was fully
 #      liquidated by about 14:16 while the script believed it stood at 83.9%,
 #      and it spent the next 45 minutes sending 491 orders for shares it no
 #      longer owned. This file is the one source that outlives the process.
 M.S.runlog_dir = SANDBOX
 _fday = "29991231"
 _fpath = M._fills_path(_fday)
 try:
     os.remove(_fpath)
 except OSError:
     pass
 check("no file yet -> nothing claimed", M._fills_from_disk(_fday), {})
 M._fill_append(_fday, "688800.SH", 20834, "r1")
 M._fill_append(_fday, "688800.SH", 11111, "r2")
 M._fill_append(_fday, "601398.SH", 7300, "r3")
 check("fills accumulate per name", M._fills_from_disk(_fday),
       {"688800.SH": 31945, "601398.SH": 7300})
 check("replaying twice reads the same", M._fills_from_disk(_fday),
       M._fills_from_disk(_fday))
 _txt = open(_fpath).read()
 check("exactly one header line", _txt.count("code,filled,remark"), 1)

 # The floor is a max(), never a replacement: a DEAL total that is further along
 # must win, or a restart would walk the count backwards.
 _dealt, _floor = 35000, M._fills_from_disk(_fday).get("688800.SH", 0)
 check("a further-along DEAL total still wins", max(_dealt, _floor), 35000)
 check("...and a stale DEAL is lifted by the file", max(0, _floor), 31945)

 # Junk lines must not take the strategy down.
 _f = open(_fpath, "a")
 _f.write("garbage\n")
 _f.write("600981.SH,notanumber,r4\n")
 _f.write("600050.SH,500,r5\n")
 _f.close()
 check("junk lines skipped, good ones counted",
       M._fills_from_disk(_fday).get("600050.SH"), 500)
 check("...and earlier totals survive",
       M._fills_from_disk(_fday).get("688800.SH"), 31945)
 try:
     os.remove(_fpath)
 except OSError:
     pass

 # (b6) A REFUSAL ONLY COUNTS AGAINST THE FALLBACK IF IT IS ABOUT AVAILABILITY.
 #      The fallback is a bet that can_use was wrong; only the counter saying
 #      "you do not have that many" settles it. 2026-08-27 counted every
 #      refusal and got it backwards twice: 688800.SH reached 2 of 3 on "order
 #      price out of range" while selling perfectly well, and the Shenzhen
 #      names burned their count on [250253], an account-registration fault.
 class ReasonBook(Book):
     """Every order is refused, with a reason the caller chooses."""

     def __init__(self, holdings, why):
         Book.__init__(self, holdings)
         self.why = why

     def place(self, code, qty, remark, sess_min):
         self.seq += 1
         sym, mkt = code.split(".")
         self.hidden_orders.append(Row(
             m_strInstrumentID=sym, m_strExchangeID=mkt, m_strRemark=remark,
             m_nOrderStatus=57, m_nVolumeTotalOriginal=qty, m_nVolumeTraded=0,
             m_strOrderSysID=str(self.seq), m_strCancelInfo=self.why,
             m_nInsertTime=0))

 for _why, _should_stop, _label in (
         ("[COUNTER][251005][insufficient available quantity]", True,
          "quantity refusal"),
         ("order price out of range", False, "price-band refusal"),
         ("[COUNTER][250253][account registration missing]", False,
          "account-registration refusal")):
     b = ReasonBook({_nc: (1100, 0)}, _why)
     b.yest[_nc] = 1100
     M.SELL_TARGETS = {_nc: 1100}
     run_session(all_minutes(), b)
     _off = _nc in getattr(M.S, "cu_fb_off", set())
     check("%s %s the fallback" % (_label, "stops" if _should_stop else "leaves alone"),
           _off, _should_stop)

 # (b7) THE HOLDING OUTRANKS `sold`.
 #      2026-08-28: 688800.SH was logged DONE 50000/50000 while the account
 #      still held 5,756 shares. sold is assembled from three sources, each has
 #      been wrong alone this week, and every guard added since removed one of
 #      them from the vote -- so the survivors agreed on too high a number with
 #      nothing left to contradict them. Six names ended that way, 6,956 shares
 #      carried overnight, and the 14:57 auction sent one 100-share order
 #      because the script believed there was nothing left to send.
 class OverstatedBook(Book):
     """Reports MORE fills than the holding lost: the DEAL list claims the whole
     target while the position still shows stock."""

     def __init__(self, holdings, phantom):
         Book.__init__(self, holdings)
         self.phantom = phantom

     def deals(self):
         return list(self.deals_rows)

 b = Book({_nc: (1100, 1100)})
 M.SELL_TARGETS = {_nc: 1100}
 # Hand the broker a DEAL for the full target while the position never moves.
 sym, mkt = _nc.split(".")
 b.deals.append(Row(m_strInstrumentID=sym, m_strExchangeID=mkt,
                    m_strRemark="phantom", m_strStrategyName=M.STRATEGY,
                    m_nDirection=49, m_nVolume=1100))
 b.hang.add(_nc)              # nothing our own orders send will actually fill
 sent_ov = run_session(all_minutes(), b)
 _done = _nc in getattr(M.S, "done", set())
 _capped = _nc in getattr(M.S, "sold_disagree", set())
 print("  overstated sold: done=%s reported=%s orders=%d" % (_done, _capped, len(sent_ov)))
 check("a phantom full fill does not retire a held name", _done, False)
 check("...the disagreement is reported", _capped, True)
 check("...and the name keeps trying", len(sent_ov) > 0, True)

 # (b8) THE CROSS-CHECK ITSELF, on the arithmetic rather than through a session.
 #      Three estimates of "sold today", each wrong in a different way this
 #      week. The rule: three available -> median, so two agreeing outvote an
 #      outlier on either side; two -> the lower, because understating costs a
 #      rejected order and overstating leaves stock in the account overnight.
 def _consensus(deal, ours, position):
     vals = [deal] + ([ours] if ours is not None else [])                    + ([position] if position is not None else [])
     if len(vals) >= 3:
         return sorted(vals)[1]
     if len(vals) == 2:
         return min(vals)
     return vals[0]

 # 2026-08-28: DEAL claimed the whole 50,000 while 5,756 were still held.
 check("an over-reporting DEAL is outvoted", _consensus(50000, 44244, 44244), 44244)
 # After a restart the DEAL list comes back empty; the other two still know.
 check("an empty DEAL after a restart is outvoted", _consensus(0, 44244, 44244), 44244)
 # 08-26: the position query blanked, making baseline-held look like the target.
 check("a blanked position is outvoted", _consensus(44244, 44244, 50000), 44244)
 # Healthy account: all three agree and the rule is a no-op.
 check("agreement passes through untouched", _consensus(44244, 44244, 44244), 44244)
 # Position unusable (negative, so excluded) and the two left disagree.
 check("two that disagree take the lower", _consensus(50000, 44244, None), 44244)
 check("...in the other direction too", _consensus(40000, 44244, None), 40000)
 # Nothing to check against.
 check("a lone estimate is used as-is", _consensus(44244, None, None), 44244)

 # (b9) THE OVERNIGHT-RESTORE SIGNATURE, keyed on the OPENING HOLDING.
 #
 #      The first version compared can_use against the live yesterday_volume
 #      and worked only until the first fill: the counter decrements
 #      yesterday_volume as the position sells down, and decrements can_use by
 #      the same amount, so both sides fall together. On 2026-08-31 at 13:08
 #      twelve names were reported as unexplained excesses at once.
 #
 #      The invariant that holds ALL DAY is the difference:
 #          can_use - position == lot_floor(holding at the open)
 def _RA(code, v, cu, open_hold):
     M.S.baseline = {code: open_hold} if open_hold else {}
     return M._restore_artifact(code, v, cu, 0)

 # The twelve readings from 2026-08-31 13:08, mid-session, part-sold.
 check("688800 part-sold is still the artifact", _RA("688800.SH", 14722, 64722, 50000), True)
 check("601398 part-sold too", _RA("601398.SH", 2600, 11100, 8500), True)
 # 600816 identifies it rather than merely fitting: 1324-324 = 1000, and the
 # opening holding was 1024. Whole lots, so a SELLABLE quantity.
 check("600816 odd tail: the gap is 1000, not 1024", _RA("600816.SH", 324, 1324, 1024), True)
 check("...and a gap of 1024 fits too", _RA("600816.SH", 324, 1348, 1024), True)
 check("...but 900 does not", _RA("600816.SH", 324, 1224, 1024), False)
 # The pre-open reading the first version was built from must still work: at
 # 09:30 nothing has sold, so position == opening holding and can_use is double.
 check("the pre-open doubling still fits", _RA("688800.SH", 50000, 100000, 50000), True)
 # Fully sold: position 0, can_use still carrying the opening lot floor.
 check("a fully sold name still fits", _RA("601398.SH", 0, 8500, 8500), True)
 # Untouched rows report can_use == volume; the gap is 0, not the opening lot.
 check("an untouched row is not the artifact", _RA("009908.SH", 1000000, 1000000, 1000000), False)
 # An excess nobody has explained must still reach the alert channel.
 check("an unexplained excess is not the artifact", _RA("601398.SH", 2600, 99999, 8500), False)
 # No baseline yet (first bar of a session): FAIL CLOSED, take the loud path.
 check("no baseline fails closed", _RA("601398.SH", 2600, 11100, 0), False)

 # The clamp and the routing are unchanged by the new basis.
 M.S.cu_said = {}; M.S.cu_alerts = []; M.S.cu_notes = []; M.S.cu_fb_off = set()
 M.S.baseline = {"600816.SH": 1024}
 _eff, _why, _kind = M._effective_can_use("600816.SH", 324, 1324, 0, 700, 0)
 check("restore shape still clamps to the position", _eff, 324)
 check("...and is tagged 'restore', not 'over'", _kind, "restore")
 M._cu_alert("600816.SH", _why, _kind)
 check("...and goes to notes, not alerts", len(M.S.cu_notes), 1)
 check("...leaving the alert channel clean", len(M.S.cu_alerts), 0)
 M.S.baseline = {"601398.SH": 8500}
 _e2, _w2, _k2 = M._effective_can_use("601398.SH", 2600, 99999, 0, 0, 0)
 check("an unexplained excess still clamps", _e2, 2600)
 M._cu_alert("601398.SH", _w2, _k2)
 check("...and still raises an ALERT", len(M.S.cu_alerts), 1)

 # (b10) THE FILL-RECORD LAG vs A REAL DISAGREEMENT. Both are three-source
 #       splits; only one of them is a fault, and they point opposite ways.
 def _is_lag(deal, ours, position):
     return (ours is not None and position is not None
             and deal == position and ours < deal)

 # 2026-08-31 09:32 and 09:33, live: ours trails by exactly one slice because
 # a fill is recorded when it is DETECTED, one bar later.
 check("the fill-record lag is recognised", _is_lag(556, 278, 556), True)
 check("...still recognised a bar later", _is_lag(833, 556, 833), True)
 # 2026-08-28: DEAL claimed the full 50,000 while 5,756 were still held. deal
 # is high and the other two agree -- the opposite shape. Must stay an ALERT.
 check("an over-reporting DEAL is NOT the lag", _is_lag(50000, 44244, 44244), False)
 # After a restart the DEAL list comes back empty. deal low, ours == position.
 check("an empty DEAL after a restart is NOT the lag", _is_lag(0, 44244, 44244), False)
 # A genuine three-way split has nothing agreeing.
 check("a three-way split is NOT the lag", _is_lag(500, 300, 400), False)
 # Missing sources cannot be adjudicated, so never call it the lag.
 check("no fill record is NOT the lag", _is_lag(556, None, 556), False)
 check("no position is NOT the lag", _is_lag(556, 278, None), False)
 # ours AHEAD of the other two is not a lag -- that would be a real surprise.
 check("ours running ahead is NOT the lag", _is_lag(556, 900, 556), False)

 # (b11) STRUCTURAL. The dedupe sets must be initialised in init() ONLY.
 #       They were also being reset inside _run_sells, which runs once a bar,
 #       so every dedupe below them was dead and 688800.SH re-alerted every
 #       minute on 2026-08-31 while it was filling perfectly normally. This
 #       check is the one that would have caught it.
 _src = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()
 for _name in ("sold_disagree", "sold_lonely", "sold_lagged",
               "cu_said", "cu_alerts", "cu_notes"):
     check("%s is initialised exactly once" % _name,
           _src.count("S.%s = " % _name), 1)

 # (b12) 250253 MUST NOT BURN THE JUNK-ORDER BUDGET.
 #       2026-08-31: 300363.SZ was retired at 09:57 and 000972.SZ at 09:58,
 #       both "after 20 orders that never reached the book", both because the
 #       Shenzhen shareholder-account registration record was missing. 22,600
 #       shares -- a quarter of the basket -- abandoned before 10:00 over an
 #       account fault that never reaches the market and is intermittent
 #       (5 refusals on 08-03, none at all on 07-31).
 #
 #       The budget exists to stop a name the MARKET will not take. 250253 is
 #       not that, so exempt the name rather than raise the ceiling -- raising
 #       it would also excuse the genuine junk orders it was written for.
 def _exempt(reject_acct, tries, cap=20):
     """The guard as written: an account refusal resets the count."""
     if reject_acct > 0 and tries >= cap:
         return 0
     return tries

 check("250253 at the cap resets the count", _exempt(20, 20), 0)
 check("...and again later in the day", _exempt(140, 20), 0)
 # A name with no account refusal must still be retired on schedule -- this is
 # the behaviour the exemption must not weaken.
 check("a genuine junk name still hits the cap", _exempt(0, 20), 20)
 check("...and is not rescued at 19 either", _exempt(0, 19), 19)
 # Below the cap nothing changes, exempt or not.
 check("below the cap the count is untouched", _exempt(5, 7), 7)

 # The state the guard reads must exist and be initialised exactly once.
 _src2 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()
 for _n2 in ("reject_acct", "acct_reject_said"):
     check("%s is initialised exactly once" % _n2, _src2.count("S.%s = " % _n2), 1)
 # And the counter must key on 250253 specifically, not on "any rejection" --
 # 251005 (insufficient quantity) IS about the market and must still count.
 check("the exemption keys on 250253", '"250253" in (getattr(o, "m_strCancelInfo"' in _src2, True)

 # (b13) ACHIEVED AVERAGE PRICE, and the two bugs found alongside it.
 _src3 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()

 # The quantity-weighted average must be exactly that, not a mean of prices.
 # 20,000 at 65 and 100 at 10 is 64.7264, not 37.50 -- a plain mean would make
 # a 100-share tail look like half the day's execution.
 M.S.fill_px = {}
 for _q, _p in ((20000, 65.0), (100, 10.0)):
     _a = M.S.fill_px.setdefault("688800.SH", [0, 0.0])
     _a[0] += _q; _a[1] += _q * _p
 _q0, _n0 = M.S.fill_px["688800.SH"]
 check("the average is quantity-weighted", round(_n0 / _q0, 4), 64.7264)

 # (b13a) The 250253 counter must be INSIDE the rejected_seen guard. The
 # broker re-serves every terminal row on every bar, so counting outside it
 # counted BARS, not orders: the 2026-08-31 10:43 NOTE said "798 order(s)
 # refused" when 50 orders had been sent. Harmless to the exemption, which
 # only tests > 0, but a number nobody could act on.
 _blk = _src3.split("if remark not in S.rejected_seen:")[1].split("continue")[0]
 check("the 250253 counter sits inside the dedupe", '"250253" in' in _blk, True)

 # (b13b) The retry throttle. Exempting 250253 from the give-up budget means
 # the name retries forever; at one bar apiece that is ~240 orders per name
 # per day, three names, and the log that is supposed to surface a problem
 # becomes the problem. Retry, but on a timer.
 def _throttled(last_reject_min, now_min, wait=10):
     return last_reject_min is not None and (now_min - last_reject_min) < wait

 check("a just-refused name waits", _throttled(30, 31), True)
 check("...still waiting at 9 minutes", _throttled(30, 39), True)
 check("...and retries at 10", _throttled(30, 40), False)
 check("a name never refused is never throttled", _throttled(None, 999), False)
 check("ACCT_REJECT_RETRY_MIN is set", M.ACCT_REJECT_RETRY_MIN, 10)

 # The throttle must not be able to retire the name by starving `attempts`:
 # the exemption resets the count, so a throttled name stays alive all day.
 # Slice by STRUCTURE, not by a character count -- the first version of this
 # check used [:400] and the NOTE text alone is longer than that, so it failed
 # on correct code.
 _exempt_blk = _src3.split("S.reject_acct.get(code, 0) > 0")[1].split("GIVE UP")[0]
 check("the exemption still resets the count",
       "S.attempts[code] = 0" in _exempt_blk, True)
 check("...and clears the local copy too", "tries = 0" in _exempt_blk, True)

 # (b14) SEALED LIMIT-UP WHILE SELLING -- the mirror of the buy-side gap.
 #       QUEUE prices a sell at ASK-1 and a sealed limit-up board has no ask,
 #       so the easiest sale of the day is the one the pricing mode cannot ask
 #       for. Price at the CEILING: a limit sell cannot execute BELOW its own
 #       limit and the ceiling is the day's legal maximum.
 def _mkup(bid, ask, ceil, got=True):
     M.S.up_cache = {"600000.SH": ceil}
     M._touch_raw = lambda C, code: (bid, ask, got)
     return M._sealed_up_sell(None, "600000.SH", None)

 check("no ask + bids at the ceiling is sealed", _mkup(11.00, 0.0, 11.00)[0], True)
 check("...and it reports the ceiling", _mkup(11.00, 0.0, 11.00)[1], 11.00)
 check("half a tick of tolerance", _mkup(10.995, 0.0, 11.00)[0], True)
 # A live ask means QUEUE has somewhere to rest -- the normal path, must stay.
 check("a live ask means not sealed", _mkup(10.99, 11.00, 11.00)[0], False)
 # No bid either: a halt. Selling into a halt is impossible at any price, and
 # a ceiling order there would just sit in a stock nobody is trading.
 check("an empty book is a halt, not a seal", _mkup(0.0, 0.0, 11.00)[0], False)
 check("bids below the ceiling mean open", _mkup(10.00, 0.0, 11.00)[0], False)
 check("no ceiling known is never sealed", _mkup(11.00, 0.0, None)[0], False)
 check("an unreadable touch is never sealed", _mkup(11.00, 0.0, 11.00, got=False)[0], False)

 # (b14a) The FALLBACK DIRECTION. A ceiling computed too LOW would make an
 # open book look sealed and send a limit sell at a price the market never
 # reached -- selling below the market is the one error this script must never
 # make. So the fallback rate is the WIDE one and the ceiling lands HIGH.
 M.S.up_cache = {}
 class _Cd(object):
     def get_instrument_detail(self, code):
         return {}
 _q = {"preclose": 10.0}
 check("main board ceiling is 10% up", M._limit_up_px(_Cd(), "600000.SH", _q), 11.00)
 M.S.up_cache = {}
 check("STAR ceiling is the wide 20%", M._limit_up_px(_Cd(), "688800.SH", _q), 12.00)
 M.S.up_cache = {}
 check("Beijing ceiling is the wide 30%", M._limit_up_px(_Cd(), "920002.BJ", _q), 13.00)

 # (b14b) The order must be PULLED when the board reopens, not left resting.
 # An unfilled order counts in `pend`, `pend` is subtracted from the slice, and
 # the name would go silent for the rest of the day holding one far-off-market
 # offer. The generic 30-minute backstop is most of an afternoon.
 _src4 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()
 check("a ceiling order is tracked by remark", "S.ceiling_orders[_cr]" in _src4, True)
 check("...and re-tested every bar", "_sealed_up_sell(C, code, None)" in _src4, True)
 # Compare INSIDE the cancel chain. The first version used file-wide index()
 # and matched the CANCEL_MIN_REST_BARS constant declaration at the top of the
 # file, so it failed on correct code -- the same mistake as b12's [:400].
 _chain = _src4.split("_ceil_px = S.ceiling_orders.get")[1].split("if not _why")[0]
 check("...ahead of the just-placed grace",
       _chain.index("_ceil_px is not None") < _chain.index("CANCEL_MIN_REST_BARS"), True)
 check("...and says REOPENED when it pulls it", "board REOPENED" in _src4, True)
 # Still sealed -> hold it, but not past the backstop.
 check("a still-sealed order is held to the backstop",
       "CANCEL_BACKSTOP_MIN" in _src4.split("_ceil_px is not None")[1][:400], True)

 # (b15) A SELL WE SENT MUST COUNT AS PENDING BEFORE THE BROKER SEES IT.
 #       Mirror of the buy-side fix, and of the same live failure.
 #       2026-08-31, three names oversold inside eight minutes:
 #           600968.SH  132500 132700 132900 133100 133200 -> 1200 of 1000
 #           600628.SH  132100 ... 132700 133200           -> 1000 of  900
 #           600816.SH  ...     132700 133200              -> 1100 of 1024
 #       all three positions ending NEGATIVE (-199, -199, -175).
 #
 #       All three "how much have I sold" sources describe a fill only AFTER
 #       it is observed, so `pend` is the only term that can speak for an
 #       order still in flight -- and it was only counting orders the broker
 #       had already acknowledged.
 import datetime as _dt2

 class _SRow(object):
     def __init__(self, code, remark, orig, traded, status):
         self.m_strInstrumentID = code.split(".")[0]
         self.m_strExchangeID = code.split(".")[1]
         self.m_strRemark = remark
         self.m_nVolumeTotalOriginal = orig
         self.m_nVolumeTraded = traded
         self.m_nOrderStatus = status

 # Save everything this helper clobbers. The first version did not, and the
 # leftover get_trade_detail_data stub and wall_override broke a scenario test
 # further down that had nothing to do with this one.
 _saved_gtd = M.get_trade_detail_data
 _saved_wall = getattr(M.S, "wall_override", None)

 def _spend(rows, exec_open):
     M.S.preview = False; M.S.acct = "1000310"; M.S.acct_type = "STOCK"
     M.S.zombies = set(); M.S.pend_released = set(); M.S.cancel_inflight = set()
     M.S.exec_open = exec_open
     M.get_trade_detail_data = lambda *a, **k: rows
     M.S.wall_override = "103000"
     return M._pending_and_cancel(None, "20260831", "103000") or {}

 _N2 = _dt2.datetime.utcnow()
 _SR = "%s_600968SH_132500" % M.STRATEGY
 _srec = {"code": "600968.SH", "side": "sell", "qty": 100, "rt": _N2}

 check("a sent-but-invisible sell counts as pending",
       _spend([], {_SR: dict(_srec)}).get("600968.SH"), 100)
 check("...not double counted once the broker has it",
       _spend([_SRow("600968.SH", _SR, 100, 0, 50)], {_SR: dict(_srec)}).get("600968.SH"), 100)
 # A filled order must not be resurrected -- that would starve the schedule
 # and leave stock unsold, the failure this whole script exists to prevent.
 check("a filled sell is not added back",
       _spend([_SRow("600968.SH", _SR, 100, 100, 56)], {_SR: dict(_srec)}).get("600968.SH"), None)
 check("a rejected sell is not added back",
       _spend([_SRow("600968.SH", _SR, 100, 0, 57)], {_SR: dict(_srec)}).get("600968.SH"), None)
 _SR2 = "%s_600968SH_132700" % M.STRATEGY
 check("two invisible sells accumulate",
       _spend([], {_SR: dict(_srec),
                   _SR2: {"code": "600968.SH", "side": "sell", "qty": 100, "rt": _N2}}
              ).get("600968.SH"), 200)
 check("a buy record is ignored",
       _spend([], {_SR: {"code": "600968.SH", "side": "buy", "qty": 100, "rt": _N2}}
              ).get("600968.SH"), None)
 _OLD2 = _N2 - _dt2.timedelta(seconds=M.PEND_INVISIBLE_MAX_SEC + 1)
 check("past the backstop it is released",
       _spend([], {_SR: {"code": "600968.SH", "side": "sell", "qty": 100, "rt": _OLD2}}
              ).get("600968.SH"), None)
 check("the backstop dwarfs the pause timeout",
       M.PEND_INVISIBLE_MAX_SEC > M.UNCONFIRMED_TIMEOUT_SEC * 3, True)

 # And the arithmetic that turns pend into a cap: allowed must shrink by it.
 # allowed = min(tgt, sold + max(0, can_use) + pend) - sold
 def _allowed(tgt, sold, cu, pend):
     return max(0, min(tgt, sold + max(0, cu) + pend) - sold)
 check("pend does not inflate a healthy allowance", _allowed(1000, 900, 100, 0), 100)
 # The live case: 900 sold, 100 in flight -> only 100 left, not 200.
 check("in-flight shares are not offered twice",
       _allowed(1000, 900, 100, 0) - 100, 0)

 # Put the module back exactly as it was.
 M.get_trade_detail_data = _saved_gtd
 M.S.wall_override = _saved_wall
 M.S.exec_open = {}
 M.S.pend_released = set()

 # (b16) THE FOUR FIXES FROM THE 2026-08-31 POST-MORTEM.
 _src5 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()

 # --- (a) a limit price cache must remember successes, never failures.
 # One early miss used to be remembered all session: the fast path at the top
 # returned None forever, long after the data arrived. On 08-31 that cost
 # 000972.SZ and 300363.SZ their closing auction while 000063.SZ, same board
 # and same second, had a floor.
 M.S.dn_cache = {}
 class _NoDetail(object):
     def get_instrument_detail(self, code):
         return {}
 check("a failed lookup is NOT cached", M._limit_down(_NoDetail(), "600000.SH", None), None)
 check("...so the cache stays empty", "600000.SH" in M.S.dn_cache, False)
 # ...and once it succeeds it IS cached.
 class _HasDetail(object):
     def get_instrument_detail(self, code):
         return {"DownStopPrice": 9.0}
 check("a successful lookup is cached", M._limit_down(_HasDetail(), "600000.SH", None), 9.0)
 check("...and is remembered", M.S.dn_cache.get("600000.SH"), 9.0)
 # The same must hold for the ceiling cache.
 M.S.up_cache = {}
 check("a failed ceiling is NOT cached", M._limit_up_px(_NoDetail(), "600000.SH", None), None)
 check("...so that cache stays empty too", "600000.SH" in M.S.up_cache, False)

 # --- (b) DONE must require the holding to be gone, not `sold` to look big.
 # 13:59:59: "DONE 688800.SH sold 50000/50000" while 1,111 shares were held.
 _done_blk = _src5.split("if s >= tgt:")[1].split("continue")[0]
 check("DONE tests the holding", "if v > 0:" in _done_blk, True)
 check("...and says so rather than retiring", "NOT retiring" in _done_blk, True)
 check("...and only retires when v <= 0", "S.done.add(code)" in _done_blk, True)

 # --- (c) the auction must not skip S.done, and must size from the holding.
 _auc = _src5.split("S.auction_done = True")[1]
 check("the auction no longer skips S.done",
       "if code in S.done or code in S.gave_up" in _auc.split("for code")[1][:400], False)
 check("...but still skips names given up on", "if code in S.gave_up:" in _auc, True)
 check("...and sizes from the holding", "sized from the holding" in _auc, True)
 check("...and falls back off the floor price", "no floor available" in _auc, True)
 check("...only skipping with no floor, no bid and no last trade",
       "no floor, no bid and no last trade" in _auc, True)

 # The auction arithmetic itself: remaining = tgt - (opened - held), capped at
 # the holding. For a full liquidation that is just the holding.
 def _auc_left(tgt, opened, held, sold_est, cu):
     by_est = max(0, min(tgt - sold_est, max(0, cu)))
     by_hold = max(0, min(held, tgt - (opened - held))) if opened > 0 and held > 0 else 0
     return max(by_est, by_hold)
 # 688800 at the close: the estimate said 0 left, the account held 1,111.
 check("the holding beats an over-reported sold", _auc_left(50000, 50000, 1111, 50000, 1111), 1111)
 check("601398 likewise", _auc_left(8500, 8500, 100, 8500, 100), 100)
 # A name genuinely finished sizes to zero and costs nothing to re-examine.
 check("a finished name still sizes to zero", _auc_left(1300, 1300, 0, 1300, 0), 0)
 # Partial mandate (target below the opening holding) must not oversell.
 check("a partial mandate is not exceeded", _auc_left(500, 1000, 800, 300, 800), 300)

 # --- (d) the counter-contradiction alert fires only on a PERSISTENT gap.
 check("COUNTER_GAP_BARS is set", M.COUNTER_GAP_BARS, 3)
 def _persist(gaps, need=3):
     """Replay the guard: report only when the gap holds for `need` bars."""
     prev, n = 0, 0
     for g in gaps:
         if g <= 0: prev, n = 0, 0
         elif g >= prev: prev, n = g, n + 1
         else: prev, n = g, 0
         if n >= need: return True
     return False
 # The fill record's one-bar lag: a gap that closes again. Must NOT alert.
 check("a lag that closes is not reported", _persist([278, 0, 278, 0]), False)
 check("a shrinking gap is not reported", _persist([300, 200, 100, 0]), False)
 # 688800: a gap that stood from 13:59 to the close. Must alert.
 check("a standing gap is reported", _persist([1111, 1111, 1111]), True)
 check("a widening gap is reported", _persist([100, 500, 1111]), True)
 check("...but not before the third bar", _persist([1111, 1111]), False)

 # (b17) THE ACCOUNT WHITELIST. Added 2026-08-31, the day before the first
 #       LIVE liquidation. Until then the script sold from whatever account
 #       the model-trading GUI had bound it to, with no check at all -- only
 #       comments saying there ought to be one. On a simulation account that
 #       is untidy; on a live one a mis-click in the binding dropdown
 #       liquidates the wrong portfolio and there is no undo.
 _src6 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()
 check("ALLOWED_ACCOUNTS exists", hasattr(M, "ALLOWED_ACCOUNTS"), True)
 # Read the SOURCE, not the live module: the harness sets ALLOWED_ACCOUNTS to
 # () so the replays can run, so asking the module would only prove the
 # harness ran. What matters is what a freshly pasted script would carry.
 import re as _re17
 _decl = _re17.search(r'^ALLOWED_ACCOUNTS = \((.*?)\)', _src6, _re17.M)
 check("...and is declared in the source", _decl is not None, True)
 check("...as a non-empty whitelist",
       bool(_decl and _decl.group(1).strip().strip(",").strip()), True)
 # The guard is checked at INIT, before any bar can be handled.
 # ANCHORED ON THE GUARD, not a fixed offset from the INIT banner. It used to
 # slice 1200 characters after "INIT sell-close"; the restart-settle block
 # landed in between and pushed "NOTHING WILL BE SOLD" out to character 1324,
 # so the check failed while the message was there and correct. A window
 # measured from unrelated code is not a test of anything.
 _g6 = _src6.index("if ALLOWED_ACCOUNTS and str(S.acct) not in")
 _init_blk = _src6[_src6.index("INIT sell-close"):_g6 + 1200]
 check("the guard runs at init", "ALLOWED_ACCOUNTS and str(S.acct) not in" in _init_blk, True)
 check("...and sets a blocking flag", "S.blocked = True" in _init_blk, True)
 check("...and says NOTHING WILL BE SOLD", "NOTHING WILL BE SOLD" in _init_blk, True)
 # handlebar must honour it, or the flag is decoration.
 _hb = _src6.split("def handlebar(C):")[1][:600]
 check("handlebar returns when blocked", 'getattr(S, "blocked", False)' in _hb, True)
 # An empty whitelist must mean "no restriction", not "block everything" --
 # otherwise a forgotten edit silently stops a session dead.
 def _blocked(allowed, acct):
     return bool(allowed) and str(acct) not in allowed
 check("the live account passes", _blocked(("507085",), "507085"), False)
 check("a different account is blocked", _blocked(("507085",), "1000310"), True)
 check("the simulation account is blocked", _blocked(("507085",), "1000003"), True)
 check("an empty whitelist blocks nothing", _blocked((), "anything"), False)
 check("the type does not matter", _blocked(("507085",), 507085), False)

 # (b18) A RESTART MUST KEEP ITS RECORDS, AND KNOW WHAT IT ALREADY SOLD.
 #
 #       2026-09-01, the first LIVE session. Four starts in twelve minutes and
 #       the run log walked one directory further down its fallback chain each
 #       time, ending in the Public Documents folder with nowhere left to go.
 #       Every open of a file that ALREADY EXISTED failed while creating a new
 #       one always worked -- which is also why price_mode.txt, a file the
 #       strategy never creates, was unreadable on all four. The same script
 #       appended to one log across seven restarts the day before in
 #       SIMULATION mode, so the restriction arrived with LIVE mode.
 import os as _os18
 _T18 = _os18.path.join(_os18.environ.get("TEMP", ROOT), "iotest_b18")
 try:
     _os18.makedirs(_T18)
 except Exception:
     pass
 for _fn in _os18.listdir(_T18):
     try:
         _os18.remove(_os18.path.join(_T18, _fn))
     except Exception:
         pass

 # Vary the NAME inside the directory, never the directory. The directory was
 # always writable; the pre-existing file was what could not be opened, and
 # changing directory scattered one session's evidence across four places.
 _h1, _p1, _d1 = M._open_varying((_T18,), "run_x", ".log", "a")
 check("the plain name is used first", _os18.path.basename(_p1), "run_x.log")
 import builtins as _bi18
 _bo18 = _bi18.open

 def _picky(path, mode="r", *a, **k):
     """Refuse any file that already exists -- the observed LIVE behaviour."""
     if _os18.path.exists(path) and "w" not in mode:
         raise IOError("live sandbox: pre-existing file")
     return _bo18(path, mode, *a, **k)

 _bi18.open = _picky
 try:
     M.S.session_tag = "054159"
     _h2, _p2, _d2 = M._open_varying((_T18,), "run_x", ".log", "a")
     M.S.session_tag = "060000"
     _h3, _p3, _d3 = M._open_varying((_T18,), "run_x", ".log", "a")
 finally:
     _bi18.open = _bo18
     for _h in (_h1, _h2, _h3):
         try:
             _h.close()
         except Exception:
             pass
 check("a blocked name falls to a tagged one", _os18.path.basename(_p2), "run_x_054159.log")
 check("...and STAYS in the same directory", _d2, _d1)
 check("a third session too", _os18.path.basename(_p3), "run_x_060000.log")
 check("...still the same directory", _d3, _d1)
 M.S.session_tag = None

 # And the baseline: with no readable file, a restart must size the opening
 # holding from SELL_TARGETS, not from what is left. Re-snapshotting the
 # CURRENT holding would record already-sold shares as never held, read
 # sold_today as 0, and offer the whole basket a second time.
 _saved_t18 = M.SELL_TARGETS
 M.SELL_TARGETS = {"600533.SH": 4800, "688567.SH": 817, "600232.SH": 1600}
 M.S.baseline = None
 M.S.runlog_dir = _T18
 _pos18 = {"600533.SH": (1200, 1200, 4800),
           "688567.SH": (817, 817, 817),
           "600232.SH": (0, 0, 1600)}
 _b18 = M._load_or_snapshot_baseline(_pos18)
 check("a restart baselines from SELL_TARGETS", _b18, dict(M.SELL_TARGETS))
 _sold18 = dict((c, _b18[c] - _pos18[c][0]) for c in _b18)
 check("...so a part-sold name reads 3600 sold", _sold18["600533.SH"], 3600)
 check("...an untouched one reads 0", _sold18["688567.SH"], 0)
 check("...and a finished one reads its whole target", _sold18["600232.SH"], 1600)
 M.SELL_TARGETS = _saved_t18
 M.S.baseline = None

 # (b19) SWITCHING THE PRICE MODE BY CREATING A FILE, NOT EDITING ONE.
 #       Under the 2026-09-01 LIVE restriction price_mode.txt -- which predates
 #       every session -- was never readable, so editing it could not reach the
 #       strategy. A file created DURING a session is not pre-existing, so a
 #       numbered instruction file can. Highest number wins: it is the latest
 #       thing the operator said, and replaying a lower one would quote the way
 #       they have just decided not to.
 import os as _os19
 _T19 = _os19.path.join(_os19.environ.get("TEMP", ROOT), "modetest_b19")
 try:
     _os19.makedirs(_T19)
 except Exception:
     pass
 for _fn in _os19.listdir(_T19):
     try:
         _os19.remove(_os19.path.join(_T19, _fn))
     except Exception:
         pass

 def _w19(name, body):
     io.open(_os19.path.join(_T19, name), "w").write(body + chr(10))

 def _mode19():
     M.S.price_mode = None
     M.S.mode_by_code = {}
     M.S.mode_file_said = None
     M.S.runlog_dir = _T19
     _sv = (M.PRICE_MODE_FILE, M.LEGACY_ROOT, M.LEGACY_LOGS, M.LOG_DIR)
     M.PRICE_MODE_FILE = _os19.path.join(_T19, "price_mode.txt")
     M.LEGACY_ROOT = _T19
     M.LEGACY_LOGS = _T19
     M.LOG_DIR = _T19
     try:
         M._refresh_price_mode()
     finally:
         M.PRICE_MODE_FILE, M.LEGACY_ROOT, M.LEGACY_LOGS, M.LOG_DIR = _sv
     return M.S.price_mode, _os19.path.basename(M.S.mode_file_said or "")

 _w19("price_mode.txt", "QUEUE")
 check("the plain file is read when it can be", _mode19(), ("QUEUE", "price_mode.txt"))
 _w19("price_mode1.txt", "COMPETE")
 check("a numbered file overrides it", _mode19(), ("COMPETE", "price_mode1.txt"))
 _w19("price_mode2.txt", "QUEUE")
 check("...and a higher number overrides that", _mode19(), ("QUEUE", "price_mode2.txt"))
 # A per-name instruction must still parse out of a numbered file.
 _w19("price_mode3.txt", "600533.SH=COMPETE")
 _m19, _src19 = _mode19()
 check("a numbered file can switch one name", M.S.mode_by_code.get("600533.SH"), "COMPETE")
 check("...leaving the default alone", _m19, M.PRICE_MODE_DEFAULT)
 # Nothing readable at all -> the configured default, never a crash.
 for _fn in _os19.listdir(_T19):
     _os19.remove(_os19.path.join(_T19, _fn))
 check("no file anywhere falls back to the default", _mode19()[0], M.PRICE_MODE_DEFAULT)
 check("PRICE_MODE_MAX_SEQ is bounded", M.PRICE_MODE_MAX_SEQ <= 10, True)
 # Put it back to the real directory, not None. Several helpers read it
 # with getattr(..., LOG_DIR), which returns None when the attribute
 # EXISTS and is None -- so clearing it this way crashed the scenarios
 # that follow. The production code now coerces None to LOG_DIR too.
 M.S.runlog_dir = M.LOG_DIR

 # (b20) `ours` REBUILT FROM THE ORDER LIST, so a restart does not lose it.
 #
 #       `ours` is the sum of m_nVolumeTraded over our own orders. It was read
 #       back from a CSV we write ourselves, which is fine until the file
 #       cannot be read -- and in LIVE mode a file predating the session
 #       cannot be. A restart lost the record entirely and `ours` began at 0.
 #
 #       The ORDER list carries the same numbers with no file involved. It is
 #       what was RIGHT on 2026-08-31: 141 orders summing to 48,889 for
 #       688800.SH while the DEAL aggregate insisted on 50,000 and three names
 #       were retired on its word with 1,311 shares still held.
 class _O20(object):
     def __init__(self, code, exch, remark, traded):
         self.m_strInstrumentID = code
         self.m_strExchangeID = exch
         self.m_strRemark = remark
         self.m_nVolumeTraded = traded

 _saved_gtd20 = M.get_trade_detail_data
 _sa20, _st20 = M.S.acct, M.S.acct_type
 M.S.acct = "507085"
 M.S.acct_type = "STOCK"
 _R20 = M.STRATEGY

 def _fo20(rows):
     M.get_trade_detail_data = lambda *a, **k: rows
     return M._fills_from_orders()

 check("three orders on one name sum",
       _fo20([_O20("600533", "SH", _R20 + "_a", 100),
              _O20("600533", "SH", _R20 + "_b", 200),
              _O20("600533", "SH", _R20 + "_c", 300)]).get("600533.SH"), 600)
 # The counter re-serves terminal rows every bar. A second copy of one order
 # would inflate the one source that has never over-reported.
 check("a re-served row is not counted twice",
       _fo20([_O20("600533", "SH", _R20 + "_a", 100),
              _O20("600533", "SH", _R20 + "_a", 100),
              _O20("600533", "SH", _R20 + "_b", 200)]).get("600533.SH"), 300)
 check("another strategy's order is ignored",
       _fo20([_O20("600533", "SH", _R20 + "_a", 100),
              _O20("600533", "SH", "someone_else", 9999)]).get("600533.SH"), 100)
 check("an unfilled order contributes nothing",
       _fo20([_O20("600533", "SH", _R20 + "_a", 0),
              _O20("600533", "SH", _R20 + "_b", 200)]).get("600533.SH"), 200)

 def _boom20(*a, **k):
     raise RuntimeError("ORDER query unavailable")

 M.get_trade_detail_data = _boom20
 check("a failed query returns nothing, not zero", M._fills_from_orders(), {})
 M.get_trade_detail_data = _saved_gtd20
 M.S.acct, M.S.acct_type = _sa20, _st20

 # (b21) THE SETTLE WINDOW after a mid-session restart.
 #
 #       The last gap in restart recovery: an order sent seconds before a
 #       restart is in neither place the new session can look. Memory is gone
 #       and the counter has not acknowledged it yet -- acknowledgement takes
 #       up to UNCONFIRMED_TIMEOUT_SEC, which is why that constant is 90. For
 #       that window the new session believes the name is untouched and would
 #       send the slice again.
 #
 #       Telling the operator not to restart in those seconds is not a
 #       control: they cannot see when an order went out, and a restart is
 #       usually a reaction to something going wrong, which is exactly when
 #       they are least able to time it. So the script waits instead.
 _sw21 = getattr(M.S, "wall_override", None)

 def _settle21(in_hours, start, now):
     M.S.session_in_hours = in_hours
     M.S.session_started = start
     M.S.settle_said = False
     M.S.wall_override = now
     return M._in_settle()

 check("a pre-open session never settles", _settle21(False, "060000", "093000"), False)
 check("a fresh mid-session restart holds", _settle21(True, "100000", "100005"), True)
 check("...still holding at 60s", _settle21(True, "100000", "100100"), True)
 check("...and releases past the window", _settle21(True, "100000", "100136"), False)
 # The lunch break is not time the counter spent acknowledging anything, but
 # it is far longer than the window either way, so a restart at 11:29 is free
 # to trade at 13:00 -- the arithmetic must not wrap or go negative.
 check("a restart before lunch is free after it",
       _settle21(True, "112900", "130000"), False)
 check("a clock that goes backwards does not wedge it",
       _settle21(True, "100000", "095900"), False)
 # The window MUST outlast the acknowledgement it is waiting for, or it
 # releases while an order is still invisible -- which is the bug, not the fix.
 check("the window outlasts the ack timeout",
       M.RESTART_SETTLE_SEC > M.UNCONFIRMED_TIMEOUT_SEC, True)
 # Missing state must not wedge a session shut. Failing OPEN is right here:
 # the alternative is a script that silently never trades.
 M.S.session_in_hours = True
 M.S.session_started = None
 check("no start time recorded -> do not hold", M._in_settle(), False)

 # It must gate the AUCTION too -- a separate send path -- and by DELAYING it,
 # not skipping it. The exchange accepts orders until 15:00, so 14:58 plus a
 # settle is still inside the window; skipping would carry the position.
 _src21 = io.open(os.path.join(ROOT, "combo_sell_dual_model.py")).read()
 _auc21 = _src21.split("def _run_auction")[1].split("for code in sorted")[0]
 check("the auction is gated too", "_in_settle()" in _auc21, True)
 check("...and is delayed, not skipped",
       _auc21.index("_in_settle()") < _auc21.index("S.auction_done = True"), True)
 M.S.session_in_hours = False
 M.S.wall_override = _sw21

 # (b22) THE FILL RECORD KEEPS ONE HANDLE FOR THE DAY.
 #
 #       2026-09-01 live: 69 x "fill record failed: Foribdden FileIO" and a
 #       fills CSV of zero bytes, while exec (11 KB) and trades (7 KB) wrote
 #       normally all morning. The difference was never the directory -- those
 #       two open once and keep the handle, while _fill_append opened and
 #       closed per record. The sandbox accepts the open that CREATES a file
 #       and refuses every open of one that already exists, so a per-record
 #       opener works once and then never again.
 import os as _os22
 _T22 = _os22.path.join(_os22.environ.get("TEMP", ROOT), "fills_b22")
 try:
     _os22.makedirs(_T22)
 except Exception:
     pass
 for _fn in _os22.listdir(_T22):
     try:
         _os22.remove(_os22.path.join(_T22, _fn))
     except Exception:
         pass

 import builtins as _bi22
 _bo22 = _bi22.open
 _opens22 = []

 def _picky22(path, mode="r", *a, **k):
     """Count opens, and refuse any file that already exists."""
     _opens22.append(path)
     if _os22.path.exists(path) and "w" not in mode:
         raise IOError("Foribdden FileIO")
     return _bo22(path, mode, *a, **k)

 M.S.runlog_dir = _T22
 M.S.fillfh = None
 M.S.fillfh_day = ""
 M.S.fills_path = None
 M.S.fills_path_day = None
 M.S.session_tag = None
 _bi22.open = _picky22
 try:
     for _i in range(5):
         M._fill_append("29991231", "600533.SH", 100 + _i, "r%d" % _i)
 finally:
     _bi22.open = _bo22

 # Five fills, ONE open. The per-record version opened five times and the last
 # four were refused.
 check("five fills cost one open", len(_opens22), 1)
 check("...and the handle is still live", M.S.fillfh is not False, True)
 _p22 = M._fills_path("29991231")
 try:
     M.S.fillfh.flush()
 except Exception:
     pass
 _rows22 = _bo22(_p22).read().strip().split(chr(10))
 check("the header is written once", _rows22[0], "code,filled,remark")
 check("...and all five rows landed", len(_rows22), 6)
 check("...with the quantities intact", _rows22[-1].split(",")[1], "104")

 # _fills_path must NOT open anything. An earlier version opened the file just
 # to discover which name would take it, then closed it -- which CREATED the
 # file, so the appender's own open was refused as pre-existing and the record
 # stayed at zero bytes all morning.
 _opens22[:] = []
 M._fills_path("29991231")
 check("_fills_path opens nothing", len(_opens22), 0)

 try:
     M.S.fillfh.close()
 except Exception:
     pass
 M.S.fillfh = None
 M.S.fillfh_day = ""
 M.S.fills_path = None
 M.S.fills_path_day = None
 M.S.runlog_dir = M.LOG_DIR

 # (b23) A FILL THIS PROCESS NEVER SAW SENT MUST STILL BE RECORDED.
 #
 #       2026-09-01, the first live liquidation. The account finished flat at
 #       26,128 shares while exec_*.csv accounted for 21,782. The missing
 #       4,346 were orders placed before one of the day's six restarts and
 #       filled after it: _exec_close popped S.exec_open, found nothing for an
 #       order this process never sent, and returned without writing a row.
 #
 #       Tolerable while the counter can be queried afterwards. On an account
 #       with no miniQMT it is not -- these files ARE the record, and a restart
 #       silently deleted part of the day from them.
 _rows23 = []
 _sw23, _sf23 = M._exec_write, M._fill_append
 M._exec_write = lambda r: _rows23.append(r)
 M._fill_append = lambda *a: None
 M.S.exec_open = {}
 M.S.exec_orphans = set()
 M.S.fill_px = {}

 class _O23(object):
     def __init__(self, traded, px, sent=278, status=56):
         self.m_nVolumeTraded = traded
         self.m_dTradedPrice = px
         self.m_strInstrumentID = "688800"
         self.m_strExchangeID = "SH"
         self.m_nOrderStatus = status
         self.m_nVolumeTotalOriginal = sent

 M._exec_close(_O23(278, 65.05), M.STRATEGY + "_a", "140100")
 check("an orphan fill is written", len(_rows23), 1)
 check("...with the exec header's 17 columns", len(_rows23[0].split(",")), 17)
 _c23 = _rows23[0].split(",")
 check("...the code is right", _c23[3], "688800.SH")
 check("...the filled quantity is right", _c23[6], "278")
 check("...the price is right", _c23[7], "65.0500")
 # The touch at send time is genuinely unknown for an order we did not send.
 # Blank says "not measured"; a number would say something false.
 check("...and the slippage columns are BLANK, not invented",
       [_c23[i] for i in (8, 9, 10, 11, 12, 13, 14)], [""] * 7)
 check("...tagged so it can be told apart", _c23[16], "adopted")
 # The counter re-serves terminal rows on every bar.
 M._exec_close(_O23(278, 65.05), M.STRATEGY + "_a", "140200")
 M._exec_close(_O23(278, 65.05), M.STRATEGY + "_a", "140300")
 check("a re-served row is not written again", len(_rows23), 1)
 # It must feed the achieved-average too, or the closing summary still
 # under-reports by exactly the shares a restart orphaned.
 check("the average price picks it up", M.S.fill_px.get("688800.SH"), [278, 278 * 65.05])
 # An order that never traded has nothing to record.
 M._exec_close(_O23(0, 0.0), M.STRATEGY + "_b", "140400")
 check("an unfilled orphan writes nothing", len(_rows23), 1)

 M._exec_write, M._fill_append = _sw23, _sf23
 M.S.exec_orphans = set()
 M.S.fill_px = {}

 # (c) a believable can_use is used unchanged -- the fallback must not fire on a
 #     healthy account, or it would quietly replace correct data with a guess.
 _eff, _why, _k = M._effective_can_use(_nc, 1000, 400, 1000, 600, 0)
 check("healthy can_use is passed through", (_eff, _why), (400, None))
 _eff2, _why2, _k2 = M._effective_can_use(_nc, 1000, 0, 1000, 0, 300)
 check("can_use 0 WITH our own orders resting is believable", _eff2, 0)

 # (d) can_use ABOVE the position: nonsense, but the honest reading is "the
 #     whole position is free", so clamp rather than fall back. Falling back
 #     reaches the same number by a longer route AND arms the rejection
 #     counter -- which on 2026-08-27 armed all twelve names at once and had
 #     688800.SH at 2/3 on price-band refusals while it was selling fine.
 M.S.cu_fb_on = set()
 M.S.cu_fb_off = set()          # scenario (b2) above switched this name off
 _eff3, _why3, _k3 = M._effective_can_use(_nc, 50000, 100000, 50000, 0, 0)
 check("can_use above the position is clamped to it", _eff3, 50000)
 check("...and still raises an alert", bool(_why3), True)
 check("...but does NOT arm the fallback", _nc in M.S.cu_fb_on, False)

 # The clamp must not paper over a real shortfall: if the position itself has
 # shrunk below what is left to sell, the position still wins.
 _eff4, _why4, _k4 = M._effective_can_use(_nc, 300, 9999, 1300, 1000, 0)
 check("...and the clamp is the position, not the target", _eff4, 300)

 # (b) frozen at the open, released at 10:00: the whole position must still go.
 b = ThawingBook({_nc: (1100, 0)}, thaw_after=30)
 M.SELL_TARGETS = {_nc: 1100}
 sent_thaw = run_session(all_minutes(), b)
 _sold = sum(s[2] for s in sent_thaw)
 print("  after can_use was released: %d order(s), %d shares"
       % (len(sent_thaw), _sold))
 check("a released position is picked up and sold", _sold >= 1100, True)
 check("...without overselling it", _sold <= 1100, True)

print()
print("=" * 82)
if fails:
    print("FAILED %d check(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CHECKS PASSED")
print("=" * 82)
