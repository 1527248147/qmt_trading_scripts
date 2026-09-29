#coding:utf-8
"""Regression tests for three faults seen in the 2026-09-24 simulation.

1. The buy side counted other users' resting buys as its own pending orders
   (301170.SZ was never bought because of a stranger's 1,200-share order).
2. Nothing recorded the close unless stop() ran, and on 09-24 no trace of
   stop() reached either log.
3. The sell auction offered shares that a live order still held (688800.SH's
   178 shares sat in a zombie order; 601398.SH offered 4,600 against 2,800).

Runs against whichever copy of the scripts sits one directory up, so the same
file serves combo_twap and combo_vwap.

    python test_close_fixes.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import combo_buy_dual_model as B
import combo_sell_dual_model as SL

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-62s %-16s %s" % (name, repr(got)[:16], "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


class Row(object):
    def __init__(self, code, remark, orig, traded, status, direction=48):
        self.m_strInstrumentID, self.m_strExchangeID = code.split(".")
        self.m_strRemark = remark
        self.m_nVolumeTotalOriginal = orig
        self.m_nVolumeTraded = traded
        self.m_nOrderStatus = status
        self.m_nDirection = direction
        self.m_dTradedPrice = 10.0


def swap(mod, **kw):
    """Set attributes on a module, returning a restore function. QMT injects
    some of these at runtime, so offline they may be absent altogether."""
    miss = object()
    saved = dict((k, getattr(mod, k, miss)) for k in kw)
    for k, v in kw.items():
        setattr(mod, k, v)

    def restore():
        for k, v in saved.items():
            if v is miss:
                delattr(mod, k)
            else:
                setattr(mod, k, v)
    return restore


# ============================================================================
print("=" * 90)
print("1. BUY: another user's resting buy is not our pending order")
print("=" * 90)
B.S.preview = False
B.S.acct, B.S.acct_type = "1000003", "STOCK"
B.S.exec_open, B.S.zombies, B.S.pend_released = {}, set(), set()
_rows = [Row("301170.SZ", B.STRATEGY + "_301170.SZ_100000", 300, 0, 50),
         Row("301170.SZ", "someone_else_manual", 1200, 0, 50)]
r = swap(B, get_trade_detail_data=lambda *a, **k: _rows)
try:
    got = B._open_buy_qty(None)
finally:
    r()
check("only our own 300 count as pending, not the stranger's 1200",
      got.get("301170.SZ"), 300)
_rows2 = [Row("301170.SZ", "someone_else_manual", 1200, 0, 50)]
r = swap(B, get_trade_detail_data=lambda *a, **k: _rows2)
try:
    got2 = B._open_buy_qty(None)
finally:
    r()
check("a name with only a stranger's order has nothing pending", got2.get("301170.SZ"), None)


# ============================================================================
print()
print("=" * 90)
print("2. THE CLOSE IS RECORDED FROM handlebar, NOT ONLY FROM stop()")
print("=" * 90)
for M, label in ((B, "buy"), (SL, "sell")):
    calls = []
    r = swap(M, _sweep_final=lambda final=True: calls.append(final))
    try:
        # Only the BUY script has a preview mode. Setting S.preview on the
        # sell module here is exactly what hid, until the 2026-09-28 paste,
        # that its sweep read an attribute the real script never creates.
        if M is B:
            M.S.preview = False
        elif hasattr(M.S, "preview"):
            delattr(M.S, "preview")
        M.S.acct = "X"
        M.S.order_time = {"r": 1}
        for w in ("143000", "145800", "145805", "150030", "160500"):
            M.S.sweep_rt = None if w in ("143000", "145800", "150030", "160500") else M.S.sweep_rt
            M.S.wall_override = w
            M._closing_sweep()
        seen = list(calls)
        M.S.order_time = {}
        M.S.sweep_rt = None
        M.S.wall_override = "145900"
        M._closing_sweep()
    finally:
        r()
        M.S.wall_override = None
    check("%s: runs at 14:58 and 15:00:30, not 14:30 or 16:05" % label, seen, [False, False])
    check("%s: a second call inside 20 s is throttled" % label, len(seen), 2)
    check("%s: nothing sent this session -> no sweep" % label, len(calls), 2)

# The sweep from handlebar records FINISHED orders only, and says the
# coverage once per change.
out, closed = [], []
_rows3 = [Row("600620.SH", B.STRATEGY + "_600620.SH_140000", 500, 100, 55),   # live partial
          Row("600463.SH", B.STRATEGY + "_600463.SH_140000", 200, 200, 56)]   # finished
r = swap(B, get_trade_detail_data=lambda *a, **k: _rows3,
         _exec_close=lambda o, remark, t: closed.append(remark),
         print=lambda *a, **k: out.append(" ".join(str(x) for x in a)))
try:
    B.S.preview, B.S.acct, B.S.now = False, "X", "20260928145900"
    B.S.exec_recorded, B.S.exec_shares, B.S.cov_last = set(), 200, None
    B._sweep_final(final=False)
    first = [l for l in out if "EXEC COVERAGE" in l]
    B._sweep_final(final=False)
    second = [l for l in out if "EXEC COVERAGE" in l]
    closed_live = list(closed)
    del closed[:]
    B._sweep_final(final=True)
finally:
    r()
# A set: the stub does not mark orders recorded, so both passes close it.
check("closing sweep records the finished order only",
      sorted(set(closed_live)), [B.STRATEGY + "_600463.SH_140000"])
check("...and says the coverage once", len(first), 1)
check("...not again while nothing has changed", len(second), 1)
check("the FINAL sweep in stop() takes the live partial too", len(closed), 2)


# ============================================================================
print()
print("=" * 90)
print("2b. stop() survives a failing sweep, and says it ran")
print("=" * 90)
out = []


def _boom(final=True):
    raise RuntimeError("counter gone")


r = swap(B, _sweep_final=_boom, _stop_run_log=lambda: None,
         print=lambda *a, **k: out.append(" ".join(str(x) for x in a)))
try:
    B.S.buy_state = {"filled": set(), "active": [], "rank_of": {}, "queue_i": 0}
    B.S.blotter, B.S.suspend, B.S.fill_px = [], [], {}
    B.stop(None)
finally:
    r()
check("buy stop(): the first line says it was called",
      bool(out) and out[0].startswith("STOP called"), True)
check("buy stop(): the failure is reported",
      any("final sweep failed" in l for l in out), True)
check("buy stop(): and the summary still prints",
      any(l.startswith("STOP buy-open") for l in out), True)

out = []
r = swap(SL, _sweep_final=_boom, log=lambda s: out.append(s))
try:
    SL.S.stopped = True
    SL.stop(None)
finally:
    r()
check("sell stop(): says it was called, reports the failure",
      (bool(out) and out[0].startswith("STOP called"),
       any("final sweep failed" in l for l in out)), (True, True))


# ============================================================================
print()
print("=" * 90)
print("2c. every S attribute the sweep reads exists in THAT script")
print("=" * 90)
# 2026-09-28: the sell script's first paste logged
#     closing sweep failed: AttributeError('_S' has no attribute 'preview')
# The sweep had been written against the buy script, which has S.preview and
# S.now; the sell script has neither. On 2026-09-24 the same error, raised as
# the first act of stop(), took the whole sell summary with it. Tests passed
# because they set the attributes themselves. So check the source instead:
# anything read as S.<name> in these functions must be ASSIGNED somewhere in
# the same file, or be read through getattr.
import inspect
import re
for M, label in ((B, "buy"), (SL, "sell")):
    src = inspect.getsource(M)
    missing = []
    for fn in (M._sweep_final, M._closing_sweep):
        body = inspect.getsource(fn)
        body = re.sub(r"#.*", "", body)                     # comments do not count
        body = re.sub(r"getattr\(S,[^)]*\)", "", body)       # guarded reads are fine
        for name in sorted(set(re.findall(r"\bS\.([A-Za-z_]+)\b(?!\s*=[^=])", body))):
            if not re.search(r"\bS\.%s\s*=[^=]" % name, src):
                missing.append("%s.%s" % (fn.__name__, name))
    check("%s: no S attribute read that the script never sets" % label, missing, [])

# The sell sweep on an S shaped like the real one: no preview, no now.
for _a in ("preview", "now"):
    if hasattr(SL.S, _a):
        delattr(SL.S, _a)
closed, out = [], []
_rows4 = [Row("600816.SH", SL.STRATEGY + "_600816SH_145900", 24, 24, 56, direction=49)]
r = swap(SL, get_trade_detail_data=lambda *a, **k: _rows4,
         _exec_close=lambda o, remark, t: closed.append((remark, t)),
         log=lambda s: out.append(s))
try:
    SL.S.acct, SL.S.acct_type = "1000310", "STOCK"
    SL.S.exec_recorded, SL.S.exec_shares = set(), 0
    SL.S.wall_override = "150030"
    SL._sweep_final()
    SL.S.stopped = True
    SL.stop(None)
finally:
    r()
    SL.S.wall_override = None
check("sell: the final sweep runs on a realistic S and records the fill",
      [c[0] for c in closed][:1], [SL.STRATEGY + "_600816SH_145900"])
check("sell: stop() with the REAL sweep reports no failure",
      any("final sweep failed" in l for l in out), False)
check("sell: and says it was called",
      any(l.startswith("STOP called") for l in out), True)


# ============================================================================
print()
print("=" * 90)
print("3. SELL AUCTION: shares held by a live order are not offered again")
print("=" * 90)


def auction(code, held, opened, target, sold, rows):
    sent, out = [], []
    # The VWAP copy refuses the auction for a name with no volume profile.
    # That gate has its own tests; here it must pass so the lock logic is
    # what is being exercised.
    extra = {}
    if hasattr(SL, "_vwap_fraction"):
        extra["_vwap_fraction"] = lambda *a, **k: 1.0
    r = swap(SL,
             SELL_TARGETS={code: target},
             get_trade_detail_data=lambda *a, **k: rows,
             _in_settle=lambda: False,
             _load_or_snapshot_baseline=lambda pos: {code: opened},
             _effective_can_use=lambda c, v, cu, ye, s, p: (0, None, None),
             _cu_alert=lambda *a: None,
             _bar=lambda *a: {"close": 10.0},
             _limit_down=lambda *a: 9.0,
             _order_sell=lambda C, c, q, h, limit_px=None: sent.append((c, q)) or True,
             log=lambda s: out.append(s), **extra)
    try:
        SL.S.auction_done = False
        SL.S.gave_up = set()
        SL.S.acct, SL.S.acct_type, SL.S.today_str = "1000310", "STOCK", "20260928"
        SL._run_auction(None, {code: (held, 0, opened)}, {code: sold}, {}, "145900")
    finally:
        r()
    return sent, out


# 601398.SH on 09-24: 4,600 held, 1,800 of them still in a live sell.
sent, out = auction("601398.SH", 4600, 8500, 8500, 3900,
                    [Row("601398.SH", "anyone", 1800, 0, 50, direction=49)])
check("601398: offers the 2,800 the counter can release, not 4,600",
      sent, [("601398.SH", 2800)])
check("...and says why", any("still held by a live order" in l for l in out), True)

# 688800.SH on 09-24: 178 held, all 178 in a zombie (status 55, part-filled).
sent, out = auction("688800.SH", 178, 50000, 50000, 49822,
                    [Row("688800.SH", SL.STRATEGY + "_688800SH_140000", 1000, 822, 55,
                         direction=49)])
check("688800: nothing offered when a live order holds every share", sent, [])

# Nothing resting: unchanged behaviour, the whole remainder goes in.
sent, out = auction("601398.SH", 4600, 8500, 8500, 3900, [])
check("no live order: the full 4,600 as before", sent, [("601398.SH", 4600)])

# A resting BUY locks cash, not shares.
sent, out = auction("601398.SH", 4600, 8500, 8500, 3900,
                    [Row("601398.SH", "anyone", 1000, 0, 50, direction=48)])
check("a resting buy does not reduce what can be sold", sent, [("601398.SH", 4600)])

# A finished order locks nothing.
sent, out = auction("601398.SH", 4600, 8500, 8500, 3900,
                    [Row("601398.SH", "anyone", 1800, 0, 54, direction=49)])
check("a cancelled order does not reduce it either", sent, [("601398.SH", 4600)])


# ============================================================================
print()
print("=" * 90)
print("4. AFTER A RESTART: the sold count and the fallback switch-off")
print("=" * 90)
# 2026-09-28 14:14, a reboot mid-RUSH on the shared simulation account.
# 600050.SH had sold 700 and been written off; its position read -1299.
check("DEAL 0 after a restart vs ours 700: ours is used",
      SL._two_source_sold({"deal": 0, "ours": 700}), 700)
check("DEAL over-reporting (08-28) vs ours: ours is used, as min() did",
      SL._two_source_sold({"deal": 50000, "ours": 44244}), 44244)
check("no fill record of ours: the lower of the two, unchanged",
      SL._two_source_sold({"deal": 1000, "position": 800}), 800)

SL.S.cu_fb_off, SL.S.cu_fb_on = set(), set()
eff, why, kind = SL._effective_can_use("600050.SH", -1299, 0, 1301, 700, 0)
check("negative position, NOT written off: falls back to yesterday - sold",
      (eff, kind), (601, "negpos"))
SL.S.cu_fb_off.add("600050.SH")
SL.S.cu_fb_on = set()
eff, why, kind = SL._effective_can_use("600050.SH", -1299, 0, 1301, 700, 0)
check("negative position, written off: nothing to send", eff, 0)
check("...and the name is not re-tagged as fallback-sized",
      "600050.SH" in SL.S.cu_fb_on, False)
SL.S.cu_fb_off, SL.S.cu_fb_on = set(), set()


# ============================================================================
print()
print("=" * 90)
print("5. CLOSING FIGURES AFTER A RESTART come from disk, not memory")
print("=" * 90)
# 2026-09-28: a reboot at 14:14. Afterwards DEAL read 0, S.fill_px and
# S.exec_shares were empty, and the sell summary said "total 0 / 91724" for a
# day that had sold 64,424 -- every share of it recorded, priced, in the exec
# CSV. The buy side printed no average price at all.
import tempfile, shutil
_tmp = tempfile.mkdtemp()
_HDR = ("date,t_place,t_done,code,side,qty_sent,qty_filled,price_filled,bid1,"
        "ask1,mid,bar_close,slip_vs_mid_bp,slip_vs_close_bp,spread_bp,status,price_mode")


def _write(path, rows):
    f = open(path, "w")
    f.write(_HDR + chr(10))
    for r in rows:
        f.write(r + chr(10))
    f.close()


try:
    # ---- sell: the first session's file, and the restarted session's own
    base = _tmp + chr(92) + "exec_" + SL.STRATEGY + "_1000310_20260928"
    _write(base + ".csv", [
        "20260928,101100,101200,688800.SH,sell,1000,1000,56.6300,,,,,,,,56,QUEUE",
        "20260928,101100,101200,601398.SH,sell,200,200,8.1700,,,,,,,,56,QUEUE",
        "20260928,101100,101200,300363.SZ,sell,9800,0,,,,,,,,,57,QUEUE"])
    _write(base + "_141416.csv", [])
    _cur = open(base + "_141416.csv", "a")
    r = swap(SL, _today_str=lambda: "20260928", _sold_today=lambda C: {},
             SELL_TARGETS={"688800.SH": 50000, "601398.SH": 8500, "300363.SZ": 20000},
             get_trade_detail_data=lambda *a, **k: [])
    out = []
    r2 = swap(SL, log=lambda s: out.append(s))
    try:
        SL.S.acct, SL.S.acct_type = "1000310", "STOCK"
        SL.S.runlog_dir = _tmp
        SL.S.execfh = _cur
        SL.S.fill_px, SL.S.exec_shares = {}, 0          # zeroed by the restart
        SL.S.exec_recorded = set()
        per, unread = SL._exec_day_totals()
        check("the whole day is read back from disk",
              (per.get("688800.SH", [0])[0], per.get("601398.SH", [0])[0], unread),
              (1000, 200, []))
        check("...priced", round(per["688800.SH"][1], 2), 56630.0)

        # The summary: DEAL says 0 after the restart; the session's own
        # consensus does not.
        SL.S.sold_agreed = {"688800.SH": 50000, "601398.SH": 5200, "300363.SZ": 0}
        SL.S.gave_up, SL.S.cu_notes, SL.S.cu_alerts = {}, [], []
        SL._summary()
        check("summary uses the count the session traded on, not DEAL's 0",
              any("688800.SH" in l and "sold  50000" in l for l in out), True)
        check("...and its total is not zero",
              any(l.strip().startswith("total 55200 /") for l in out), True)
        check("...and the average-price section is there, from disk",
              any("whole day, from the exec CSV" in l for l in out), True)

        # Nothing in the counter's order list to compare with: still say
        # what the file holds.
        del out[:]
        SL.S.wall_override = "150500"
        SL._sweep_final(final=True)
        check("coverage with an empty order list still reports the day",
              any("EXEC CSV: 1200 share(s) recorded today" in l for l in out), True)

        # The live client refuses to reopen files: the session's OWN file is
        # then covered from memory, and anything else unreadable is named.
        def _deny(p, *a, **k):
            if p.endswith("_141416.csv") or p.endswith("20260928.csv"):
                raise IOError("Foribdden FileIO")
            return io.open(p, *a, **k)
        r3 = swap(SL, open=_deny)
        try:
            SL.S.fill_px = {"688800.SH": [300, 300 * 56.0]}
            per, unread = SL._exec_day_totals()
        finally:
            r3()
        check("unreadable files are named, not guessed at", len(unread), 2)
        check("...and this session's fills come from memory instead",
              per.get("688800.SH", [0])[0], 300)
    finally:
        r2()
        r()
        _cur.close()
        SL.S.execfh = None
        SL.S.wall_override = None

    # ---- buy: stop() after a restart prints the day's prices from disk
    bbase = _tmp + chr(92) + "exec_" + B.STRATEGY + "_1000003_20260928"
    _write(bbase + ".csv", [
        "20260928,101100,101200,002381.SZ,buy,700,700,5.5400,,,,,,,,56,QUEUE"])
    out = []
    # EVERY directory the buy side writes exec to, not just runlog_dir: the
    # reader scans them all, and on 2026-09-28 the real combo_vwap\logs held a
    # genuine exec file for this very account and day -- the first version of
    # this check read it and counted 2,400 shares of 002381.SZ, not 700.
    r = swap(B, _today_str=lambda: "20260928", _stop_run_log=lambda: None,
             RUN_LOG_DIR=_tmp, TRADE_LOG_DIR=_tmp, LEGACY_DIR=_tmp, LEGACY_LOGS=_tmp,
             get_trade_detail_data=lambda *a, **k: [],
             print=lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    try:
        B.S.acct, B.S.acct_type, B.S.preview = "1000003", "STOCK", False
        B.S.runlog_dir = _tmp
        B.S.execfh = None
        B.S.fill_px, B.S.exec_shares = {}, 0
        B.S.buy_state = {"filled": set(), "active": [], "rank_of": {}, "queue_i": 0}
        B.S.blotter, B.S.suspend = [], []
        B.stop(None)
    finally:
        r()
    check("buy stop() after a restart: the day's average price is printed",
          any("002381.SZ" in l and "700 shares @ 5.5400" in l for l in out), True)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ============================================================================
print()
print("=" * 90)
print("6. A RESTART'S RE-RECORDED FILLS COUNT ONCE")
print("=" * 90)
# On the live client the counter's order list still holds the whole day after
# a restart, and the new session -- nothing in memory -- writes every earlier
# fill again as an "adopted" line. Those lines now carry the order's remark,
# and everything that sums fills counts one order once.
import io, tempfile, shutil, ast as _ast, contextlib
_t6 = tempfile.mkdtemp()
try:
    for M, acct in ((SL, "1000310"), (B, "1000003")):
        R1, R2 = M.STRATEGY + "_688800SH_101100", M.STRATEGY + "_688800SH_141800"
        # -- the durable fill record the script replays for sizing
        fp = _t6 + chr(92) + "fills_%s.csv" % M.STRATEGY
        f = open(fp, "w")
        f.write("code,filled,remark" + chr(10))
        f.write("688800.SH,1000,%s" % R1 + chr(10))      # first session
        f.write("688800.SH,1000,%s" % R1 + chr(10))      # adopted again after the restart
        f.write("688800.SH,300,%s" % R2 + chr(10))       # a genuine new fill
        f.write("600000.SH,200" + chr(10))               # an old line with no remark
        f.close()
        r = swap(M, _today_str=lambda: "20260929")
        try:
            M.S.fills_path, M.S.fills_path_day = fp, "20260929"
            got = M._fills_from_disk("20260929")
        finally:
            r()
            M.S.fills_path = M.S.fills_path_day = None
        check("%s: fill replay counts the adopted duplicate once" % M.STRATEGY,
              (got.get("688800.SH"), got.get("600000.SH")), (1300, 200))

        # -- the exec record the closing figures read
        base = _t6 + chr(92) + "exec_%s_%s_20260929" % (M.STRATEGY, acct)
        H = _HDR + ",remark"
        f = open(base + ".csv", "w")
        f.write(H + chr(10))
        f.write("20260929,101100,101200,688800.SH,sell,1000,1000,56.6000,,,,,,,,56,QUEUE,%s" % R1 + chr(10))
        f.close()
        f = open(base + "_141600.csv", "w")
        f.write(H + chr(10))
        f.write("20260929,,141700,688800.SH,sell,1000,1000,56.6000,,,,,,,,56,adopted,%s" % R1 + chr(10))
        f.write("20260929,141800,141900,688800.SH,sell,300,300,55.0000,,,,,,,,56,QUEUE,%s" % R2 + chr(10))
        f.close()
        r = swap(M, _today_str=lambda: "20260929",
                 **(dict(RUN_LOG_DIR=_t6, TRADE_LOG_DIR=_t6, LEGACY_DIR=_t6, LEGACY_LOGS=_t6)
                    if M is B else {}))
        try:
            M.S.acct, M.S.runlog_dir, M.S.execfh, M.S.fill_px = acct, _t6, None, {}
            per, unread = M._exec_day_totals()
        finally:
            r()
        check("%s: exec totals across both files count the order once" % M.STRATEGY,
              (per.get("688800.SH", [0])[0], round(per.get("688800.SH", [0, 0])[1], 2)),
              (1300, round(1000 * 56.6 + 300 * 55.0, 2)))

    # -- and vwap_check, the offline scorer, pairs them the same way
    _vsrc = io.open(os.path.join(ROOT, "tools", "vwap_check.py"), encoding="utf-8").read()
    _fn = [n for n in _ast.parse(_vsrc).body
           if isinstance(n, _ast.FunctionDef) and n.name == "_fills"][0]
    _ns = {}
    exec("import csv, io, os" + chr(10) + _ast.get_source_segment(_vsrc, _fn), _ns)
    _vf = _ns["_fills"]([base + ".csv", base + "_141600.csv"])
    check("vwap_check pairs the adopted twin by remark",
          _vf.get("688800.SH", [0])[0], 1300)
finally:
    shutil.rmtree(_t6, ignore_errors=True)


# ============================================================================
print()
print("=" * 90)
print("7. BUY: a lost order gives its shares back; TOPUP trusts our own fills")
print("=" * 90)
# 2026-09-29, shared simulation account 1000003.
# (a) 688466.SH sent 203 at 09:48; the counter never listed it. Released from
#     pending after ten minutes -- but left in sent_qty, so the name finished at
#     401 of 699 believing it held 604.
_rec7 = {"code": "688466.SH", "side": "buy", "qty": 203,
         "rt": __import__("datetime").datetime.utcnow()
               - __import__("datetime").timedelta(seconds=B.PEND_INVISIBLE_MAX_SEC + 5)}
r = swap(B, get_trade_detail_data=lambda *a, **k: [])
try:
    B.S.preview, B.S.acct, B.S.acct_type = False, "1000003", "STOCK"
    B.S.zombies, B.S.pend_released = set(), set()
    B.S.exec_open = {B.STRATEGY + "_688466.SH_094800": dict(_rec7)}
    B.S.sent_qty = {"688466.SH": 604}
    B._open_buy_qty(None)
    after1 = B.S.sent_qty["688466.SH"]
    B._open_buy_qty(None)
    after2 = B.S.sent_qty["688466.SH"]
finally:
    r()
check("a released lost order gives its 203 back to sent", after1, 401)
check("...once only", after2, 401)

# (b) 688217.SH at 14:40: bought 200 of a 392 target, 192 short of a 200-share
#     STAR minimum -- TOPUP's exact case -- but the shared account's position
#     read 0 for it, and TOPUP keyed on that.
def _topup_run(pend):
    sent = []
    code = "688217.SH"
    stubs = dict(
        _positions=lambda c: {}, _own=lambda h, c: 0,
        _total_value=lambda c: 10000.0, _available_cash=lambda *a: 10000.0,
        _open_buy_qty=lambda c: dict(pend), _filled_today=lambda c: {code: 200},
        _fills_from_orders=lambda: {code: 200}, _fills_from_disk=lambda d: {code: 200},
        _quote=lambda *a: {"close": 25.5, "volume": 100000.0, "preclose": 25.5,
                           "high": 26.0, "low": 25.0},
        _is_st=lambda *a: False, _sealed_up=lambda *a: (False, ""),
        _sealed_down=lambda *a: (False, 0.0), _spread_wide=lambda *a: (False, ""),
        _in_settle=lambda: False, _log_trade=lambda *a: None,
        _limit_up=lambda *a: 28.0, _today_str=lambda: "20260929",
        _wall_hhmmss=lambda: "144000", _refresh_price_mode=lambda: set(),
        _adopt_existing=lambda c: None, _reconcile_waiting=lambda c: True,
        _cancel_stale_orders=lambda *a: None, _traded_since_open=lambda *a: True,
        _order_buy=lambda C, c, q, remark, limit_px=None: sent.append((c, q, remark)) or True,
        print=lambda *a, **k: None,
        TARGETS=[code], SLOTS=1, BUY_BUDGET=10000.0)
    if hasattr(B, "_vwap_fraction"):
        stubs["_vwap_fraction"] = lambda *a: 1.0
    class _Any(object):
        """A ContextInfo that answers anything with nothing."""
        def __getattr__(self, name):
            return lambda *a, **k: None
    stubs.update(account="FAKE", accountType="STOCK", ALLOWED_ACCOUNTS=(),
                 _start_run_log=lambda *a, **k: None)
    r = swap(B, **stubs)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            B.init(_Any())            # the script's own start-up state
        B.S.preview, B.S.acct, B.S.acct_type = False, "FAKE", "STOCK"
        B.S.buy_state = {"filled": set(), "active": [code], "rank_of": {code: 1},
                         "queue_i": 1}
        B.S.sent_qty = {code: 200}
        B.S.waiting = []
        B._run_buys(None, "20260929", "144100")
    finally:
        r()
    return sent


try:
    s1 = _topup_run({})
    check("TOPUP fires on our own fills when the account reads 0",
          [(c, q) for c, q, _ in s1], [("688217.SH", 200)])
    check("...tagged as a top-up", bool(s1) and "_topup_" in s1[0][2], True)
    s2 = _topup_run({"688217.SH": 100})
    check("...but not while an order of ours is still resting", s2, [])
except Exception as e:
    import traceback; traceback.print_exc()
    check("TOPUP harness ran", repr(e), None)


print()
print("=" * 90)
if fails:
    print("FAILED %d check(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CHECKS PASSED")
print("=" * 90)
sys.exit(1 if fails else 0)
