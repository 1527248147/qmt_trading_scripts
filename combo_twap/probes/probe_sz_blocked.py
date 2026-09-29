#coding:gbk
# ============================================================================
# READ-ONLY: why do Shenzhen orders fail while Shanghai orders fill?
# ----------------------------------------------------------------------------
# On 2026-07-31 this account filled 1,767 of 1,767 shares sent to Shanghai and
# 0 of 10,500 sent to Shenzhen. Every SZ order died; every SH order worked.
# The rejection message the sell script reads (m_strStatusMsg) came back empty,
# so the reason must live in a field we are not reading, or the account has no
# usable Shenzhen shareholder code.
#
# This dumps, for one rejected SZ order, EVERY m_* attribute -- so whatever
# carries the reason is found rather than guessed. It also lists the shareholder
# code per exchange, which is the other likely cause.
#
# IT PLACES NO ORDERS. There is no passorder and no cancel in this file.
# Safe to run as a SECOND model-trading strategy alongside the others.
#
# Output: C:\AI_STOCK\qmt_trading_scripts\combo_twap\logs\sz_blocked_<date>.txt
#
# ASCII ONLY -- the QMT editor saves GBK.
# ============================================================================

import datetime as dt

LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"
SZ_PROBE = ["000590.SZ", "003816.SZ", "300583.SZ", "300883.SZ"]
SH_PROBE = ["600805.SH", "603168.SH", "688779.SH"]


class _S(object):
    pass


S = _S()
print("MODULE probe_sz_blocked imported OK")


def _emit(line):
    print(line)
    if S.fh:
        try:
            S.fh.write(line + "\n")
            S.fh.flush()
        except Exception:
            S.fh = None


def _dump_all(label, o):
    _emit("  " + label)
    names = sorted(a for a in dir(o) if a.startswith("m_"))
    for a in names:
        try:
            v = getattr(o, a)
        except Exception:
            continue
        if callable(v):
            continue
        _emit("      %-32s %r" % (a, v))


def init(C):
    S.done = False
    S.fh = None
    try:
        S.acct = account
        S.acct_type = accountType
    except NameError:
        S.acct = ""
        S.acct_type = "STOCK"
    day = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
    for d in (LOG_DIR, "C:\\QMTGTHT\\local_run\\combo_top20_twap",
              "C:\\Users\\Public\\Documents"):
        try:
            S.fh = open(d + "\\sz_blocked_" + day + ".txt", "w")
            print("  output -> " + d)
            break
        except Exception:
            continue
    try:
        C.set_universe(sorted(set(SZ_PROBE + SH_PROBE + ["000001.SZ"])))
    except Exception:
        pass
    print("INIT probe_sz_blocked | account %r %s" % (S.acct, S.acct_type))


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
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)

    _emit("=" * 78)
    _emit("SZ-BLOCKED PROBE  " + now.strftime("%Y-%m-%d %H:%M:%S"))
    _emit("=" * 78)

    # ---- 1. shareholder code per exchange -------------------------------
    _emit("")
    _emit("--- 1. shareholder codes seen in POSITION, by exchange ---")
    try:
        rows = list(get_trade_detail_data(S.acct, S.acct_type, "POSITION") or [])
    except Exception as e:
        rows = []
        _emit("  POSITION query FAILED: " + repr(e))
    holders = {}
    for o in rows:
        mkt = getattr(o, "m_strExchangeID", "") or "?"
        h = getattr(o, "m_strStockHolder", None)
        holders.setdefault(mkt, {})
        holders[mkt][repr(h)] = holders[mkt].get(repr(h), 0) + 1
    for mkt in sorted(holders):
        _emit("  %-4s : %s" % (mkt, ", ".join(
            "%s x%d" % (k, v) for k, v in sorted(holders[mkt].items()))))
    if not holders:
        _emit("  (no position rows)")

    # ---- 2. every field of one SZ order and one SH order -----------------
    _emit("")
    _emit("--- 2. ORDER rows: one Shenzhen, one Shanghai, ALL fields ---")
    try:
        orders = list(get_trade_detail_data(S.acct, S.acct_type, "ORDER") or [])
    except Exception as e:
        orders = []
        _emit("  ORDER query FAILED: " + repr(e))
    _emit("  ORDER rows total: %d" % len(orders))
    sz = [o for o in orders if (getattr(o, "m_strExchangeID", "") == "SZ")]
    sh = [o for o in orders if (getattr(o, "m_strExchangeID", "") == "SH")]
    _emit("  of which SZ: %d, SH: %d" % (len(sz), len(sh)))

    # prefer one of OUR rejected SZ orders
    pick = None
    for o in sz:
        if int(getattr(o, "m_nOrderStatus", 0) or 0) == 57:
            pick = o
            break
    if pick is None and sz:
        pick = sz[0]
    if pick is not None:
        _dump_all("SZ ORDER (status %s, code %s):"
                  % (getattr(pick, "m_nOrderStatus", "?"),
                     getattr(pick, "m_strInstrumentID", "?")), pick)
    else:
        _emit("  no SZ order rows at all -- SZ orders may never reach the book")
    if sh:
        _dump_all("SH ORDER (status %s, code %s):"
                  % (getattr(sh[0], "m_nOrderStatus", "?"),
                     getattr(sh[0], "m_strInstrumentID", "?")), sh[0])

    # ---- 3. status histogram by exchange ---------------------------------
    _emit("")
    _emit("--- 3. order status counts by exchange ---")
    hist = {}
    for o in orders:
        mkt = getattr(o, "m_strExchangeID", "") or "?"
        st = int(getattr(o, "m_nOrderStatus", 0) or 0)
        hist[(mkt, st)] = hist.get((mkt, st), 0) + 1
    names = {48: "unreported", 49: "wait-report", 50: "reported",
             51: "reported-cancelling", 52: "part-cancelling",
             53: "part-cancelled", 54: "cancelled", 55: "part-filled",
             56: "FILLED", 57: "REJECTED", 255: "unknown"}
    for k in sorted(hist):
        _emit("  %-4s status %-3d %-20s x%d"
              % (k[0], k[1], names.get(k[1], "?"), hist[k]))

    # ---- 4. is the contract tradable at all? -----------------------------
    _emit("")
    _emit("--- 4. get_instrument_detail, SZ vs SH ---")
    for c in SZ_PROBE + SH_PROBE:
        try:
            d = C.get_instrument_detail(c) or {}
            keys = ("InstrumentName", "ExchangeID", "IsTrading", "PreClose",
                    "UpStopPrice", "DownStopPrice", "InstrumentStatus")
            _emit("  %-11s %s" % (c, ", ".join(
                "%s=%r" % (k, d.get(k)) for k in keys if k in d)))
            if not d:
                _emit("  %-11s (empty)" % c)
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))

    # ---- 5. can we even quote SZ? ---------------------------------------
    _emit("")
    _emit("--- 5. market data, SZ vs SH ---")
    for c in SZ_PROBE + SH_PROBE:
        try:
            d = C.get_market_data_ex(["close", "volume"], [c], period="1m", count=2)
            f = d.get(c)
            if f is None or len(f) == 0:
                _emit("  %-11s NO BAR" % c)
            else:
                r = f.iloc[-1]
                _emit("  %-11s close %s volume %s" % (c, r["close"], r["volume"]))
        except Exception as e:
            _emit("  %-11s EXCEPTION %r" % (c, e))

    # ---- 6. account rows, all fields -------------------------------------
    _emit("")
    _emit("--- 6. ACCOUNT rows, ALL fields ---")
    try:
        arows = list(get_trade_detail_data(S.acct, S.acct_type, "ACCOUNT") or [])
        _emit("  rows: %d" % len(arows))
        for i, o in enumerate(arows):
            _dump_all("ACCOUNT row %d:" % i, o)
    except Exception as e:
        _emit("  ACCOUNT query FAILED: " + repr(e))

    # ---- 7. OUR OWN rejected orders, and why -----------------------------
    # The first pass dumped whichever rejected order came first, which turned
    # out to belong to another strategy on this shared account -- it had an
    # empty remark and was failing on "insufficient securities", a sell-side
    # error that cannot apply to our buys. Filter to ours.
    _emit("")
    _emit("--- 7. OUR orders (remark starts with combo_), by exchange/status ---")
    mine = [o for o in orders
            if str(getattr(o, "m_strRemark", "") or "").startswith("combo_")]
    _emit("  ours: %d of %d" % (len(mine), len(orders)))
    h2 = {}
    for o in mine:
        k = (getattr(o, "m_strExchangeID", "?"),
             int(getattr(o, "m_nOrderStatus", 0) or 0))
        h2[k] = h2.get(k, 0) + 1
    for k in sorted(h2):
        _emit("  %-4s status %-3d %-20s x%d"
              % (k[0], k[1], names.get(k[1], "?"), h2[k]))

    _emit("")
    _emit("--- 8. cancel reason for OUR rejected orders ---")
    shown = 0
    for o in mine:
        if int(getattr(o, "m_nOrderStatus", 0) or 0) != 57:
            continue
        _emit("  %s %s qty %s dir %s remark %r"
              % (getattr(o, "m_strExchangeID", "?"),
                 getattr(o, "m_strInstrumentID", "?"),
                 getattr(o, "m_nVolumeTotalOriginal", "?"),
                 getattr(o, "m_nDirection", "?"),
                 getattr(o, "m_strRemark", "")))
        _emit("      cancelInfo %r" % (getattr(o, "m_strCancelInfo", None),))
        _emit("      errorMsg   %r  errorID %r  localInfo %r"
              % (getattr(o, "m_strErrorMsg", None),
                 getattr(o, "m_nErrorID", None),
                 getattr(o, "m_strLocalInfo", None)))
        shown += 1
        if shown >= 6:
            break
    if shown == 0:
        _emit("  none of our orders is in status 57 right now")

    _emit("")
    _emit("--- 9. distinct cancel reasons across ALL SZ rejections ---")
    reasons = {}
    for o in orders:
        if getattr(o, "m_strExchangeID", "") != "SZ":
            continue
        if int(getattr(o, "m_nOrderStatus", 0) or 0) != 57:
            continue
        ci = str(getattr(o, "m_strCancelInfo", "") or "")
        # keep only the bracketed reason, drop the per-order parameters
        head = ci.split("][")
        key = "][".join(head[:3]) + "]" if len(head) >= 3 else ci[:80]
        reasons[key] = reasons.get(key, 0) + 1
    for k in sorted(reasons, key=lambda x: -reasons[x])[:8]:
        _emit("  x%-6d %s" % (reasons[k], k))

    _emit("")
    _emit("PROBE COMPLETE. No orders were placed.")


def stop(C):
    try:
        if S.fh:
            S.fh.flush()
            S.fh.close()
    except Exception:
        pass
    print("STOP probe_sz_blocked")
