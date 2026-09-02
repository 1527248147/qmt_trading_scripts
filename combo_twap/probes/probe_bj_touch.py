#coding:gbk
# ============================================================================
# READ-ONLY: why does a BJ name have no bid/ask?
# ----------------------------------------------------------------------------
# The sell script logged "no usable tick/touch" for 920002.BJ while main-board
# names were fine. That could be three different things and the log cannot tell
# them apart:
#   (a) the touch really is absent for BJ on this terminal
#   (b) get_full_tick returns it under different keys for BJ
#   (c) _touch() reads the wrong keys
# This dumps the RAW dictionary for BJ names and a main-board control, so the
# answer comes from data rather than assumption.
#
# IT PLACES NO ORDERS. grep this file: there is no passorder and no cancel.
# Safe to run as a SECOND model-trading strategy while the sell script runs.
#
# Paste into the QMT editor, 1 minute period, bind the account, press run.
# Output: C:\AI_STOCK\qmt_trading_scripts\combo_twap\logs\bj_touch_<date>.txt
#
# ASCII ONLY -- the QMT editor saves GBK.
# ============================================================================

import datetime as dt

LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"

# BJ names first, then a main-board control that is known to work.
CODES = ["920002.BJ", "920018.BJ", "920931.BJ", "430005.BJ",
         "601012.SH", "300883.SZ", "688001.SH"]


class _S(object):
    pass


S = _S()
print("MODULE probe_bj_touch imported OK")


def _emit(line):
    print(line)
    if S.fh:
        try:
            S.fh.write(line + "\n")
            S.fh.flush()
        except Exception:
            S.fh = None


def init(C):
    S.done = False
    S.fh = None
    day = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
    for d in (LOG_DIR, "C:\\QMTGTHT\\local_run\\combo_top20_twap",
              "C:\\Users\\Public\\Documents"):
        try:
            S.fh = open(d + "\\bj_touch_" + day + ".txt", "w")
            print("  output -> " + d)
            break
        except Exception:
            continue
    try:
        C.set_universe(sorted(set(CODES + ["000001.SZ"])))
        print("  set_universe OK with %d codes" % (len(CODES) + 1))
    except Exception as e:
        print("  set_universe FAILED: " + repr(e))
    print("INIT probe_bj_touch")


def handlebar(C):
    if S.done:
        return
    try:
        if not C.is_last_bar():
            return
    except Exception:
        pass
    S.done = True
    now = (dt.datetime.utcnow() + dt.timedelta(hours=8))
    today = now.strftime("%Y%m%d")
    hhmmss = now.strftime("%H%M%S")

    _emit("=" * 78)
    _emit("BJ TOUCH PROBE  " + now.strftime("%Y-%m-%d %H:%M:%S"))
    _emit("=" * 78)

    # ---- 1. one call per code -------------------------------------------
    _emit("")
    _emit("--- get_full_tick, ONE code per call ---")
    for c in CODES:
        try:
            t = C.get_full_tick([c])
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))
            continue
        d = t.get(c) if isinstance(t, dict) else None
        if d is None:
            _emit("  %-11s returned %r (code not a key; keys=%r)"
                  % (c, t, list(t.keys()) if isinstance(t, dict) else None))
            continue
        if not isinstance(d, dict):
            _emit("  %-11s value is %s not dict: %r" % (c, type(d).__name__, d))
            continue
        _emit("  %-11s %d field(s)" % (c, len(d)))
        for k in sorted(d.keys()):
            _emit("       %-20s %r" % (k, d[k]))

    # ---- 2. all codes in ONE call ---------------------------------------
    _emit("")
    _emit("--- get_full_tick, ALL codes in ONE call ---")
    try:
        t = C.get_full_tick(CODES)
        _emit("  returned keys: %r" % (sorted(t.keys()) if isinstance(t, dict) else t,))
        missing = [c for c in CODES if c not in (t or {})]
        _emit("  missing: %r" % (missing,))
    except Exception as e:
        _emit("  EXCEPTION %r" % (e,))

    # ---- 3. does the 1m bar work for the same codes? --------------------
    _emit("")
    _emit("--- get_market_data_ex 1m (does bar data work where tick does not?) ---")
    for c in CODES:
        try:
            data = C.get_market_data_ex(["close", "volume"], [c], period="1m",
                                        count=3)
            f = data.get(c)
            if f is None or len(f) == 0:
                _emit("  %-11s NO BAR" % c)
            else:
                r = f.iloc[-1]
                _emit("  %-11s close %s volume %s (%d row(s))"
                      % (c, r["close"], r["volume"], len(f)))
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))

    # ---- 4. tick period through get_market_data_ex ----------------------
    _emit("")
    _emit("--- get_market_data_ex period='tick' (an alternative touch source) ---")
    for c in CODES[:5]:
        try:
            data = C.get_market_data_ex(
                ["bidPrice", "askPrice", "lastPrice"], [c], period="tick", count=2)
            f = data.get(c)
            if f is None or len(f) == 0:
                _emit("  %-11s NO TICK ROWS" % c)
            else:
                _emit("  %-11s cols=%r last=%r"
                      % (c, list(f.columns), dict(f.iloc[-1])))
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))

    # ---- 5. instrument detail: is the contract even known? --------------
    _emit("")
    _emit("--- get_instrument_detail ---")
    for c in CODES:
        try:
            d = C.get_instrument_detail(c) or {}
            keep = ("InstrumentName", "ExchangeID", "UpStopPrice",
                    "DownStopPrice", "PreClose", "VolumeMultiple",
                    "PriceTick", "IsTrading")
            _emit("  %-11s %s" % (c, ", ".join(
                "%s=%r" % (k, d.get(k)) for k in keep if k in d)))
            if not d:
                _emit("       (empty dict -- contract unknown to the terminal)")
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))

    _emit("")
    _emit("PROBE COMPLETE. No orders were placed.")


def stop(C):
    try:
        if S.fh:
            S.fh.flush()
            S.fh.close()
    except Exception:
        pass
    print("STOP probe_bj_touch")
