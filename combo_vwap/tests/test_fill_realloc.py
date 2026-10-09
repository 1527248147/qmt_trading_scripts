#coding:utf-8
"""combo_vwap/combo_buy_fill_model.py (VWAP copy of the TWAP test): money a coarse
name cannot use goes to the fine ones.

    python test_fill_realloc.py
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
with contextlib.redirect_stdout(io.StringIO()):
    import combo_buy_fill_model as F
# Every file this suite makes goes to a temp folder, never the real logs\ (the
# 2026-10-09 run of this suite left PREVIEW run logs next to the live one).
import tempfile as _tf
_TMP = _tf.mkdtemp(prefix="fill_realloc_")
F.TRADE_LOG_DIR = F.RUN_LOG_DIR = F.LOG_DIR_EXTERNAL = _TMP
F.LEGACY_DIR = F.LEGACY_LOGS = _TMP
# VWAP: a name's progress comes from its volume profile, which needs history the
# tests do not have. Replace it with the TWAP clock fraction (minutes elapsed in
# the window / window length) so every scenario below reads as in combo_twap.
def _clock_frac(C, code, today, hhmmss):
    s, e = F._sess_min(hhmmss), F._sess_min(F.BUY_END)
    return 1.0 if s >= e else max(0.0, s / float(e))
F._vwap_fraction = _clock_frac

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-62s %-16s %s" % (name, repr(got)[:16], "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


# The 2026-10-09 basket at the 10-08 close (the held 20 after 300757.SZ, 508
# yuan, falls through to 603306.SH).
PX = {"688147.SH": 89.25, "002655.SZ": 31.07, "300648.SZ": 36.66, "600234.SH": 18.82,
      "301511.SZ": 93.87, "600159.SH": 2.72, "688701.SH": 8.44, "002980.SZ": 104.96,
      "605255.SH": 56.10, "688215.SH": 41.14, "300870.SZ": 165.34, "300567.SZ": 175.19,
      "300614.SZ": 10.38, "600716.SH": 3.70, "688191.SH": 18.42, "300625.SZ": 9.95,
      "002963.SZ": 20.11, "300593.SZ": 28.15, "002222.SZ": 56.58, "603306.SH": 66.91}
NAV = 532360.19
BASE = NAV / 20


def plan(px, nav=NAV, slots=20, on=True, names=None):
    F.SLOTS, F.FILL_REALLOCATE = slots, on
    F.S.fill_last_px, F.S.fill_plan_key = {}, None
    F._quote = lambda C, c, today, hh: ({"close": px[c]} if px.get(c) else None)
    F.print = lambda *a, **k: None
    return F._slot_values(None, "20261009", "093100", nav, list(names or px))


def spend(c, budget, p, topup=False):
    """What the script buys for `budget`. topup=True also counts the extra lot
    the ORIGINAL only adds after 14:00 (and only if that late order fills)."""
    mn, step = F._buy_unit(c)
    sh = F._round_buy(c, budget / p)
    if topup and sh > 0 and (budget / p - sh) > mn / 2.0 \
            and (sh + mn) * p <= budget * (1 + F.TOPUP_OVERSHOOT):
        sh += mn
    return sh * p


print("=" * 90)
print("1. TODAY'S BASKET")
print("=" * 90)
v = plan(PX)
coarse = [c for c in PX if v[c] == BASE]
# the rule itself: one buy step costs at most FILL_COARSE_FRAC of the budget
fine = [c for c in PX if F._buy_unit(c)[1] * PX[c] <= F.FILL_COARSE_FRAC * BASE]
check("...and they all get the same raised budget",
      len(set(round(v[c], 2) for c in fine)) == 1 and v[fine[0]] > BASE, True)
check("the 8 cheap / STAR names are the fine ones", sorted(fine),
      sorted(["300614.SZ", "300625.SZ", "600159.SH", "600716.SH", "688147.SH",
              "688191.SH", "688215.SH", "688701.SH"]))
coarse = [c for c in PX if c not in fine]
check("301511.SZ (93.87) sized to 300 shares inside the window, not 200",
      F._round_buy("301511.SZ", v["301511.SZ"] / PX["301511.SZ"]), 300)
check("300567.SZ (175.19) stays at its one affordable lot",
      F._round_buy("300567.SZ", v["300567.SZ"] / PX["300567.SZ"]), 100)
tot = sum(spend(c, v[c], PX[c]) for c in PX)            # fill script, no TOPUP at all
orig_lots = sum(spend(c, BASE, PX[c]) for c in PX)      # original, if no TOPUP fills
orig_top = sum(spend(c, BASE, PX[c], True) for c in PX)  # original, if every TOPUP fills
print("     original %.1f%% (whole lots) .. %.1f%% (every late TOPUP fills) | fill %.2f%%"
      % (orig_lots / NAV * 100, orig_top / NAV * 100, tot / NAV * 100))
check("original: 89.8% unless the post-14:00 top-ups fill",
      round(orig_lots / NAV * 100, 1), 89.8)
check("fill script: over 99.5% of the budget, all inside the window", tot / NAV > 0.995, True)
check("and never exceeds the budget", tot <= NAV, True)

print("=" * 90)
print("2. SWITCH OFF = THE ORIGINAL SCRIPT")
print("=" * 90)
v = plan(PX, on=False)
check("FILL_REALLOCATE False: every name gets nav / SLOTS", all(abs(x - BASE) < 1e-6 for x in v.values()), True)
v = plan({"300870.SZ": 165.34, "301511.SZ": 93.87}, nav=2 * BASE, slots=2)
check("no fine name to absorb an overshoot: original sizing",
      all(abs(x - BASE) < 1e-6 for x in v.values()), True)

print("=" * 90)
print("3. EDGES")
print("=" * 90)
px = dict(PX)
px["300870.SZ"] = None                              # no quote yet
v = plan(px)
check("a name with no price keeps the base budget", abs(v["300870.SZ"] - BASE) < 1e-6, True)
v2 = plan(PX)
check("...and gives nothing to the pool meanwhile", v[fine[0]] < v2[fine[0]], True)
# one fine name, two very coarse ones: the boost is capped
px = {"600159.SH": 2.72, "300870.SZ": 165.34, "300567.SZ": 175.19}
v = plan(px, nav=3 * BASE, slots=3)
check("the boost is capped at FILL_MAX_BOOST", round(v["600159.SH"] / BASE, 6), 1.0 + F.FILL_MAX_BOOST)
# a name that cannot afford one lot neither gives nor takes
px = {"600159.SH": 2.72, "300757.SZ": 508.0}
v = plan(px, nav=2 * BASE, slots=2)
check("an unaffordable name adds nothing to the pool", abs(v["600159.SH"] - BASE) < 1e-6, True)
# a coarse overshoot is taken back from the fine name, so the pair stays on budget
px = {"600159.SH": 2.72, "301511.SZ": 93.87}       # nearest lot 300 = 28,161 > base
v = plan(px, nav=2 * BASE, slots=2)
check("the coarse overshoot comes out of the fine name",
      round(v["600159.SH"], 2), round(BASE - (300 * 93.87 - BASE), 2))
check("...and the pair never exceeds its budget",
      spend("600159.SH", v["600159.SH"], 2.72) + spend("301511.SZ", v["301511.SZ"], 93.87) <= 2 * BASE, True)

print("=" * 90)
print("4. THE SIZING LOOP USES THE NEW BUDGET")
print("=" * 90)
# Two slots: one coarse (300870.SZ 165.34 -> 100 shares, 10,084 idle) and one
# fine (600159.SH 2.72). After a bar, the fine name's target is sized on
# base + the idle money, not on base.
sent = []
PX2 = {"600159.SH": 2.72, "300870.SZ": 165.34}
stubs = dict(
    _positions=lambda c: {}, _own=lambda h, c: 0,
    _total_value=lambda c: 2 * BASE, _available_cash=lambda *a: 2 * BASE,
    _open_buy_qty=lambda c: {}, _filled_today=lambda c: {},
    _fills_from_orders=lambda: {}, _fills_from_disk=lambda d: {},
    _quote=lambda C, c, *a: {"close": PX2[c], "volume": 100000.0, "preclose": PX2[c],
                             "high": PX2[c] * 1.01, "low": PX2[c] * 0.99},
    _is_st=lambda *a: False, _sealed_up=lambda *a: (False, ""),
    _sealed_down=lambda *a: (False, 0.0), _spread_wide=lambda *a: (False, ""),
    _in_settle=lambda: False, _log_trade=lambda *a: None,
    _limit_up=lambda *a: 99999.0, _today_str=lambda: "20261009",
    _wall_hhmmss=lambda: "100000", _refresh_price_mode=lambda: set(),
    _adopt_existing=lambda c: None, _reconcile_waiting=lambda c: True,
    _cancel_stale_orders=lambda *a: None, _traded_since_open=lambda *a: True,
    _order_buy=lambda C, c, q, remark, limit_px=None: sent.append((c, q)) or True,
    print=lambda *a, **k: None, _start_run_log=lambda *a, **k: None,
    TARGETS=["600159.SH", "300870.SZ"], SLOTS=2, BUY_BUDGET=2 * BASE,
    FILL_REALLOCATE=True, account="FAKE", accountType="STOCK", ALLOWED_ACCOUNTS=())
saved = dict((k, getattr(F, k)) for k in stubs if hasattr(F, k))
for k, val in stubs.items():
    setattr(F, k, val)


class _Any(object):
    def __getattr__(self, name):
        return lambda *a, **k: None


try:
    with contextlib.redirect_stdout(io.StringIO()):
        F.init(_Any())
    F.S.preview, F.S.acct, F.S.acct_type = False, "FAKE", "STOCK"
    F.S.buy_state = {"filled": set(), "active": [], "rank_of": {"600159.SH": 1, "300870.SZ": 2},
                     "queue_i": 0}
    F.S.sent_qty, F.S.waiting = {}, []
    F.S.fill_last_px, F.S.fill_plan_key = {}, None
    F._run_buys(None, "20261009", "100000")
    idle = BASE - 100 * 165.34
    want = F._round_buy("600159.SH", (BASE + idle) / 2.72)
    check("fine name's target is (base + idle) / price", F.S.tgt_first.get("600159.SH"), want)
    check("coarse name's target is unchanged (100 shares)", F.S.tgt_first.get("300870.SZ"), 100)
finally:
    for k, val in saved.items():
        setattr(F, k, val)

print("=" * 90)
print("5. HARD BUDGET GUARD")
print("=" * 90)
# The guard sits in _order_buy, so every order path goes through it.
_sent5 = []
_sv5 = dict((k, getattr(F, k, None)) for k in ("passorder", "_touch", "_bar_price", "_log_trade",
                                         "print", "BUY_BUDGET", "FILL_BUDGET_GUARD"))
F.passorder = lambda *a, **k: _sent5.append((a[3], a[6]))
F._touch = lambda C, c: (None, None)
F._bar_price = lambda *a, **k: None
F._log_trade = lambda *a, **k: None
F.print = lambda *a, **k: None
F.BUY_BUDGET = 100000.0
try:
    with contextlib.redirect_stdout(io.StringIO()):
        F.init(_Any())
    F.S.preview, F.S.acct, F.S.buy_code, F.S.now = False, "FAKE", 23, "20261009100000"
    F.S.fill_last_px = {"600159.SH": 2.72, "300870.SZ": 165.34}
    F.S.fill_committed = 99000.0                    # 1,000 of room left
    F._order_buy(None, "600159.SH", 1000, "r1")       # 2,720 wanted
    check("an order that would cross the budget is shrunk to fit",
          _sent5[-1:] , [("600159.SH", 300)])       # 300 x 2.72 = 816 <= 1,000
    n = len(_sent5)
    F._order_buy(None, "300870.SZ", 100, "r2")        # 16,534 > what is left
    check("...and one where not even a lot fits is not sent", len(_sent5), n)
    F.FILL_BUDGET_GUARD = False
    F.S.fill_committed = 99000.0
    F._order_buy(None, "600159.SH", 1000, "r3")
    check("FILL_BUDGET_GUARD False: the order goes out unchanged", _sent5[-1:], [("600159.SH", 1000)])
finally:
    for k, val in _sv5.items():
        setattr(F, k, val)

# A whole simulated session on today's basket, buying every slice in full the
# moment it is asked for, while the coarse names RALLY 8% from noon -- the case
# the plan alone cannot undo. The basket must stay within BUY_BUDGET.
spent = {}
sent6 = []
px6 = dict(PX)
stubs6 = dict(
    _positions=lambda c: dict(spent), _own=lambda h, c: h.get(c, 0),
    _total_value=lambda c: NAV, _available_cash=lambda *a: 10 * NAV,
    _open_buy_qty=lambda c: {}, _filled_today=lambda c: dict(spent),
    _fills_from_orders=lambda: dict(spent), _fills_from_disk=lambda d: dict(spent),
    _quote=lambda C, c, *a: {"close": px6[c], "volume": 10 ** 7, "preclose": px6[c],
                             "high": px6[c] * 1.01, "low": px6[c] * 0.99},
    _is_st=lambda *a: False, _sealed_up=lambda *a: (False, ""),
    _sealed_down=lambda *a: (False, 0.0), _spread_wide=lambda *a: (False, ""),
    _in_settle=lambda: False, _log_trade=lambda *a: None,
    _limit_up=lambda *a: 99999.0, _today_str=lambda: "20261009",
    _refresh_price_mode=lambda: set(),
    _adopt_existing=lambda c: None, _reconcile_waiting=lambda c: True,
    _cancel_stale_orders=lambda *a: None, _traded_since_open=lambda *a: True,
    _touch=lambda C, c: (None, None), _bar_price=lambda *a, **k: None,
    passorder=lambda *a, **k: (sent6.append((a[3], a[6])),
                               spent.__setitem__(a[3], spent.get(a[3], 0) + int(a[6]))),
    print=lambda *a, **k: None, _start_run_log=lambda *a, **k: None,
    TARGETS=list(PX), SLOTS=20, BUY_BUDGET=NAV, FILL_REALLOCATE=True,
    FILL_BUDGET_GUARD=True, account="FAKE", accountType="STOCK", ALLOWED_ACCOUNTS=())
saved6 = dict((k, getattr(F, k)) for k in stubs6 if hasattr(F, k))
for k, val in stubs6.items():
    setattr(F, k, val)
try:
    with contextlib.redirect_stdout(io.StringIO()):
        F.init(_Any())
    F.S.preview, F.S.acct, F.S.acct_type, F.S.buy_code = False, "FAKE", "STOCK", 23
    F.S.buy_state = {"filled": set(), "active": [], "queue_i": 0,
                     "rank_of": dict((c, i + 1) for i, c in enumerate(PX))}
    F.S.sent_qty, F.S.waiting, F.S.exec_open = {}, [], {}
    F.S.fill_last_px, F.S.fill_plan_key = {}, None
    F.S.price_mode, F.S.mode_by_code = "QUEUE", {}     # the refresh is stubbed out
    coarse6 = [c for c in PX if F._buy_unit(c)[1] * PX[c] > F.FILL_COARSE_FRAC * BASE]
    for t in range(570, 690):
        hh = "%02d%02d00" % (t // 60, t % 60)
        F.S.now = "20261009" + hh
        F._wall_hhmmss = lambda hh=hh: hh
        F._run_buys(None, "20261009", hh)
    for c in coarse6:
        px6[c] = PX[c] * 1.08
    for t in list(range(780, 841)) + [841, 900]:
        hh = "%02d%02d00" % (t // 60, t % 60)
        F.S.now = "20261009" + hh
        F._wall_hhmmss = lambda hh=hh: hh
        F._run_buys(None, "20261009", hh)
    total = sum(q * px6[c] for c, q in spent.items())
    print("     session: %d orders, basket %.0f of %.0f (%.2f%%) at closing prices"
          % (len(sent6), total, NAV, total / NAV * 100))
    check("a full session with a coarse rally stays within BUY_BUDGET", total <= NAV + 1e-6, True)
    check("...and still deploys over 97% of it", total / NAV > 0.97, True)
finally:
    for k, val in saved6.items():
        setattr(F, k, val)

print("=" * 90)
print("6. 2026-10-09 REPLAY: the three gaps that left 16,430 idle")
print("=" * 90)
# The live basket after 300757.SZ fell through, at the day's average fills.
# 002980.SZ trades at 103.5 until 14:02 (so 200 shares is its nearest lot and
# it retires at 14:00), then 98.5 (where the old plan re-priced it to 300). 688147.SH
# is the STAR name that bought 201 and stranded the rest.
PX9 = {"688147.SH": 83.07, "002655.SZ": 29.54, "300648.SZ": 35.70, "600234.SH": 18.33,
       "301511.SZ": 84.58, "600159.SH": 2.70, "688701.SH": 8.13, "002980.SZ": 103.5,
       "605255.SH": 53.97, "688215.SH": 39.93, "300870.SZ": 150.32, "300567.SZ": 166.61,
       "300614.SZ": 9.94, "600716.SH": 3.66, "688191.SH": 17.63, "300625.SZ": 9.71,
       "002963.SZ": 18.94, "300593.SZ": 26.16, "002222.SZ": 53.18, "603306.SH": 63.21}


def _session9(v3=True):
    spent, sent, said = {}, [], []
    px = dict(PX9)
    stubs = dict(
        _positions=lambda c: dict(spent), _own=lambda h, c: h.get(c, 0),
        _total_value=lambda c: NAV, _available_cash=lambda *a: 10 * NAV,
        _open_buy_qty=lambda c: {}, _filled_today=lambda c: dict(spent),
        _fills_from_orders=lambda: dict(spent), _fills_from_disk=lambda d: dict(spent),
        _quote=lambda C, c, *a: {"close": px[c], "volume": 10 ** 7, "preclose": px[c],
                                 "high": px[c] * 1.01, "low": px[c] * 0.99},
        _is_st=lambda *a: False, _sealed_up=lambda *a: (False, ""),
        _sealed_down=lambda *a: (False, 0.0), _spread_wide=lambda *a: (False, ""),
        _in_settle=lambda: False, _log_trade=lambda *a: None,
        _limit_up=lambda *a: 99999.0, _today_str=lambda: "20261009",
        _refresh_price_mode=lambda: set(),
        _adopt_existing=lambda c: None, _reconcile_waiting=lambda c: True,
        _cancel_stale_orders=lambda *a: None, _traded_since_open=lambda *a: True,
        _touch=lambda C, c: (None, None), _bar_price=lambda *a, **k: None,
        passorder=lambda *a, **k: (sent.append((a[3], a[6])),
                                   spent.__setitem__(a[3], spent.get(a[3], 0) + int(a[6]))),
        print=lambda *a, **k: said.append(" ".join(str(x) for x in a)),
        _start_run_log=lambda *a, **k: None,
        TARGETS=list(PX9), SLOTS=20, BUY_BUDGET=NAV, FILL_REALLOCATE=True,
        FILL_BUDGET_GUARD=True, FILL_SWEEP=v3, account="FAKE", accountType="STOCK",
        ALLOWED_ACCOUNTS=())
    saved = dict((k, getattr(F, k, None)) for k in stubs)
    for k, val in stubs.items():
        setattr(F, k, val)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            F.init(_Any())
        F.S.preview, F.S.acct, F.S.acct_type, F.S.buy_code = False, "FAKE", "STOCK", 23
        F.S.price_mode, F.S.mode_by_code = "QUEUE", {}
        F.S.buy_state = {"filled": set(), "active": [], "queue_i": 0,
                         "rank_of": dict((c, i + 1) for i, c in enumerate(PX9))}
        F.S.sent_qty, F.S.waiting = {}, []
        F.S.fill_last_px, F.S.fill_plan_key, F.S.fill_sweeps = {}, None, 0
        bars = (["%02d%02d00" % (t // 60, t % 60) for t in range(571, 691)]
                + ["%02d%02d00" % (t // 60, t % 60) for t in range(781, 900)])
        for hh in bars:
            if hh == "140200":                   # AFTER it retired at its 200
                px["002980.SZ"] = 98.5
            F.S.now = "20261009" + hh
            F._wall_hhmmss = lambda hh=hh: hh
            F._run_buys(None, "20261009", hh)
            if F.S.buy_done:
                break
    finally:
        for k, val in saved.items():
            setattr(F, k, val)
    total = sum(q * px[c] for c, q in spent.items())
    return total, spent, sent, said


tot9, spent9, sent9, said9 = _session9(True)
star = [q for c, q in sent9 if c == "688147.SH"]
print("     v3: deployed %.0f of %.0f (%.2f%%), %d orders; 688147.SH orders %s -> %d shares"
      % (tot9, NAV, tot9 / NAV * 100, len(sent9), star, spent9.get("688147.SH", 0)))
for l in said9:
    if "FILL SWEEP" in l or "STAR-SPLIT" in l:
        print("       " + l[:150])
check("688147.SH: no STAR order leaves a sub-200 remainder it cannot send",
      all(q >= 200 for q in star) and spent9.get("688147.SH", 0) > 300, True)
check("the basket deploys over 99% of the budget", tot9 / NAV > 0.99, True)
check("...and never exceeds it", tot9 <= NAV + 1e-6, True)
check("002980.SZ planned at the 200 it holds, not re-priced to 300",
      spent9.get("002980.SZ", 0), 200)

print("=" * 90)
print("7. FINAL SWEEP AND COST-BASED COMMITMENT")
print("=" * 90)
# Direct: every slot retired at 14:10, the basket 12,000 short of budget ->
# the fine names are re-opened once, buy, and a second sweep with no progress
# does not happen.
said7, sent7 = [], []
held7 = {"600159.SH": 9000, "300870.SZ": 100}
px7 = {"600159.SH": 2.70, "300870.SZ": 150.0}
nav7 = 2 * BASE
stubs7 = dict(
    _positions=lambda c: dict(held7), _own=lambda h, c: h.get(c, 0),
    _total_value=lambda c: nav7, _available_cash=lambda *a: nav7,
    _open_buy_qty=lambda c: {}, _filled_today=lambda c: dict(held7),
    _fills_from_orders=lambda: dict(held7), _fills_from_disk=lambda d: dict(held7),
    _quote=lambda C, c, *a: {"close": px7[c], "volume": 10 ** 7, "preclose": px7[c],
                             "high": px7[c], "low": px7[c]},
    _is_st=lambda *a: False, _sealed_up=lambda *a: (False, ""),
    _sealed_down=lambda *a: (False, 0.0), _spread_wide=lambda *a: (False, ""),
    _in_settle=lambda: False, _log_trade=lambda *a: None,
    _limit_up=lambda *a: 99999.0, _today_str=lambda: "20261009",
    _refresh_price_mode=lambda: set(),
    _adopt_existing=lambda c: None, _reconcile_waiting=lambda c: True,
    _cancel_stale_orders=lambda *a: None, _traded_since_open=lambda *a: True,
    _touch=lambda C, c: (None, None), _bar_price=lambda *a, **k: None,
    passorder=lambda *a, **k: (sent7.append((a[3], a[6])),
                               held7.__setitem__(a[3], held7.get(a[3], 0) + int(a[6]))),
    print=lambda *a, **k: said7.append(" ".join(str(x) for x in a)),
    _start_run_log=lambda *a, **k: None,
    TARGETS=["600159.SH", "300870.SZ"], SLOTS=2, BUY_BUDGET=nav7, FILL_REALLOCATE=True,
    FILL_BUDGET_GUARD=True, FILL_SWEEP=True, account="FAKE", accountType="STOCK",
    ALLOWED_ACCOUNTS=())
saved7 = dict((k, getattr(F, k, None)) for k in stubs7)
for k, val in stubs7.items():
    setattr(F, k, val)
try:
    with contextlib.redirect_stdout(io.StringIO()):
        F.init(_Any())
    F.S.preview, F.S.acct, F.S.acct_type, F.S.buy_code = False, "FAKE", "STOCK", 23
    F.S.price_mode, F.S.mode_by_code = "QUEUE", {}
    F.S.buy_state = {"filled": {"600159.SH", "300870.SZ"}, "active": [], "queue_i": 2,
                     "rank_of": {"600159.SH": 1, "300870.SZ": 2}}
    F.S.sent_qty = dict(held7)
    F.S.waiting, F.S.fill_last_px, F.S.fill_plan_key, F.S.fill_sweeps = [], {}, None, 0
    F.S.fill_fine_last = ["600159.SH"]
    F.S.buy_done = False
    for hh in ("141000", "141100", "141200", "141300"):
        F.S.now = "20261009" + hh
        F._wall_hhmmss = lambda hh=hh: hh
        F._run_buys(None, "20261009", hh)
    sweeps = [l for l in said7 if "FILL SWEEP" in l]
    total7 = sum(q * px7[c] for c, q in held7.items())
    print("     sweeps %d, orders %s, basket %.0f of %.0f" % (len(sweeps), sent7, total7, nav7))
    check("a basket short of budget after 14:00 re-opens the fine name", len(sweeps) >= 1, True)
    check("...which then buys the leftover", any(c == "600159.SH" for c, q in sent7), True)
    check("...without passing the budget", total7 <= nav7 + 1e-6, True)
    check("...and the run then ends (BUY DONE)", F.S.buy_done, True)
finally:
    for k, val in saved7.items():
        setattr(F, k, val)

# Cost-based commitment: 1,000 shares bought at 10.00, now quoted 8.00 -- the
# guard must count 10,000 spent, not 8,000.
F.S.fill_px = {"600000.SH": [1000, 10000.0]}
check("committed money counts what was PAID when the price has fallen",
      F._fill_spent("600000.SH", 1000, 8.0), 10000.0)
check("...and the market value when the price has risen",
      F._fill_spent("600000.SH", 1000, 12.0), 12000.0)
check("...shares beyond the recorded fills are valued at the price",
      F._fill_spent("600000.SH", 1200, 8.0), 10000.0 + 200 * 8.0)
F.S.fill_px = {}

print()
print("ALL CHECKS PASSED" if not fails else "FAILED %d check(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
