#coding:gbk
# ============================================================================
# READ-ONLY POSITION SCAN -- QMT model trading
# ----------------------------------------------------------------------------
# Lists every holding the account can actually SELL right now (can_use > 0) and
# writes them to a file so they can be read without sitting at the machine.
#
# IT PLACES NO ORDERS. The only calls made are get_trade_detail_data queries.
# There is no passorder anywhere in this file -- grep it.
#
# HOW TO RUN
#   Paste into the QMT model-trading editor, 1 minute period, bind the account,
#   press run. It prints once and stops acting. Output goes to
#       C:\AI_STOCK\qmt_trading_scripts\combo_twap\logs\sellable_<date>.txt
#
# WHY IT EXISTS
#   A positive position does NOT mean a sellable one. In this account
#   003816.SZ holds 22,400 shares with can_use -2,099 and 603659.SH holds
#   99,986,500 with can_use -20,199, because m_nVolume is a NET figure and the
#   account carries shorts. Picking a test name off the position list without
#   checking can_use would pick one that cannot trade.
#
# ASCII ONLY -- the QMT editor saves GBK and non-ASCII bytes have broken files
# in this project before.
# ============================================================================

import datetime as dt

LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"
MIN_CAN_USE = 100       # ignore anything too small to make a legal order
TOP_N = 40              # print at most this many rows


class _S(object):
    pass


S = _S()
print("MODULE probe_sellable imported OK")


def _now():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


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
    try:
        S.acct = account
        S.acct_type = accountType
    except NameError:
        S.acct = ""
        S.acct_type = "STOCK"
    try:
        C.set_universe(["000001.SZ"])
    except Exception:
        pass
    day = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
    for d in (LOG_DIR, "C:\\QMTGTHT\\local_run\\combo_top20_twap",
              "C:\\Users\\Public\\Documents"):
        try:
            S.fh = open(d + "\\sellable_" + day + ".txt", "w")
            print("  output -> " + d)
            break
        except Exception:
            continue
    print("INIT probe_sellable | account %r %s" % (S.acct, S.acct_type))
    if not S.acct:
        print("  !! NO ACCOUNT BOUND -- bind one and re-run.")


def handlebar(C):
    if S.done:
        return
    try:
        if not C.is_last_bar():
            return
    except Exception:
        pass
    if not S.acct:
        return
    S.done = True

    _emit("=" * 78)
    _emit("SELLABLE POSITIONS  " + _now() + "  account " + str(S.acct))
    _emit("=" * 78)

    try:
        rows = list(get_trade_detail_data(S.acct, S.acct_type, "POSITION") or [])
    except Exception as e:
        _emit("POSITION query FAILED: " + repr(e))
        return

    agg = {}
    for o in rows:
        sym = getattr(o, "m_strInstrumentID", "")
        mkt = getattr(o, "m_strExchangeID", "")
        if not sym or not mkt:
            continue
        code = sym + "." + mkt
        v = int(getattr(o, "m_nVolume", 0) or 0)
        cu = int(getattr(o, "m_nCanUseVolume", 0) or 0)
        yv = int(getattr(o, "m_nYesterdayVolume", 0) or 0)
        pv, pc, py = agg.get(code, (0, 0, 0))
        agg[code] = (pv + v, pc + cu, py + yv)     # accumulate duplicate rows

    _emit("rows %d -> distinct codes %d" % (len(rows), len(agg)))

    ok = [(c, v, cu, yv) for c, (v, cu, yv) in agg.items() if cu >= MIN_CAN_USE]
    ok.sort(key=lambda r: -r[2])
    neg = len([1 for c, (v, cu, yv) in agg.items() if cu < 0])

    _emit("sellable (can_use >= %d): %d | negative can_use: %d"
          % (MIN_CAN_USE, len(ok), neg))
    _emit("")
    _emit("%-11s %16s %16s %16s  %s" % ("code", "volume", "can_use", "yesterday", "board"))
    for c, v, cu, yv in ok[:TOP_N]:
        if c.startswith("688"):
            b = "STAR min200"
        elif c[:3] in ("300", "301"):
            b = "ChiNext"
        elif c[0] in ("4", "8"):
            b = "BJ"
        else:
            b = "main"
        _emit("%-11s %16d %16d %16d  %s" % (c, v, cu, yv, b))
    if len(ok) > TOP_N:
        _emit("... and %d more" % (len(ok) - TOP_N))

    _emit("")
    _emit("Pick a MAIN-BOARD name with a large can_use for the sell test:")
    main = [r for r in ok if not r[0].startswith("688")
            and r[0][:3] not in ("300", "301") and r[0][0] not in ("4", "8")]
    for c, v, cu, yv in main[:5]:
        _emit("   SELL_TARGETS = {\"%s\": 100}      # can_use %d" % (c, cu))
    if not main:
        _emit("   none found -- nothing on the main board is sellable right now")
    _emit("=" * 78)
    _emit("PROBE COMPLETE. No orders were placed.")


def stop(C):
    try:
        if S.fh:
            S.fh.flush()
            S.fh.close()
    except Exception:
        pass
    print("STOP probe_sellable")
