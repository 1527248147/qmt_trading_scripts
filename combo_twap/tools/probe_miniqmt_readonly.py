#coding:utf-8
# ============================================================================
# miniQMT READ-ONLY PROBE
# ----------------------------------------------------------------------------
# Connects to the running QMT terminal over the xtquant "independent trading"
# channel and dumps account / position / order / trade state.
#
# IT PLACES NO ORDERS AND CANCELS NOTHING. Every call used here is a query.
# The only side effect is a subscribe(), which starts a push feed.
#
# Run with the terminal's bundled CPython 3.6 (the xtquant .pyd is cp36):
#   C:\QMTGTHT\bin.x64\python.exe probe_miniqmt_readonly.py
#
# What it settles:
#   1. Is the independent-trading channel actually open (connect() == 0)?
#   2. Which account ids exist, and is the account subscribable?
#   3. Real field names / values on XtPosition, XtOrder, XtTrade, XtAsset.
#   4. T+1 state: can_use_volume vs volume vs yesterday_volume for OUR names,
#      which is what the sell script must key off.
# ============================================================================

import os
import sys
import time

# --- which terminal to talk to -------------------------------------------
TERMINAL = u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df"
MINI_DIR = os.path.join(TERMINAL, "userdata_mini")
XTQ_SITE = os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages")

# Names the buy script filled on 2026-07-29. Used only to report T+1 state.
OUR_NAMES = [
    "000590.SZ", "002436.SZ", "003816.SZ", "300490.SZ", "300583.SZ",
    "300919.SZ", "301009.SZ", "301065.SZ", "301166.SZ", "600805.SH",
    "600958.SH", "603168.SH", "603659.SH", "688058.SH", "688152.SH",
    "688217.SH", "688357.SH", "688779.SH",
]
STRATEGY_PREFIX = "combo_buy_open"     # remark prefix our buy script stamps


def main():
    print("=" * 78)
    print("miniQMT READ-ONLY PROBE  (no orders, no cancels)")
    print("terminal :", TERMINAL.encode("utf-8", "replace").decode("utf-8", "replace"))
    print("mini dir :", MINI_DIR.encode("utf-8", "replace").decode("utf-8", "replace"))
    print("python   :", sys.version.split()[0])
    print("=" * 78)

    if not os.path.isdir(MINI_DIR):
        print("FATAL: userdata_mini not found -> wrong terminal path")
        return
    if XTQ_SITE not in sys.path:
        sys.path.insert(0, XTQ_SITE)

    try:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount
        from xtquant import xtconstant
    except Exception as e:
        print("FATAL: cannot import xtquant:", repr(e))
        print("  -> the .pyd is built for cp36-cp311; this python is",
              sys.version.split()[0])
        return
    print("import xtquant OK ->", os.path.dirname(
        sys.modules["xtquant.xttrader"].__file__))

    # ---- connect -----------------------------------------------------------
    session = int(time.time()) % 1000000000
    xt = XtQuantTrader(MINI_DIR, session)
    xt.start()
    rc = xt.connect()
    print("connect() ->", rc, "(0 = connected)")
    if rc != 0:
        print("FAILED. Checklist:")
        print("  * terminal running and logged in")
        print("  * the terminal's independent-trading (\u72ec\u7acb\u4ea4\u6613) switch is ON")
        print("  * only ONE python client per session id")
        return

    # ---- which accounts exist ---------------------------------------------
    try:
        infos = xt.query_account_infos() or []
        print("\nquery_account_infos ->", len(infos), "account(s)")
        for a in infos:
            attrs = [k for k in dir(a) if not k.startswith("_")]
            vals = []
            for k in sorted(attrs):
                v = getattr(a, k, None)
                if not callable(v):
                    vals.append("%s=%r" % (k, v))
            print("   ", ", ".join(vals))
    except Exception as e:
        print("query_account_infos FAILED:", repr(e))
        infos = []

    acct_ids = []
    for a in infos:
        aid = getattr(a, "account_id", None)
        atype = getattr(a, "account_type", None)
        if aid and atype == getattr(xtconstant, "SECURITY_ACCOUNT", 2):
            acct_ids.append(aid)
    if not acct_ids:
        acct_ids = [getattr(a, "account_id", None) for a in infos]
        acct_ids = [a for a in acct_ids if a]
    print("\nSTOCK account ids:", acct_ids)

    for aid in acct_ids:
        probe_account(xt, StockAccount(aid), aid)

    print("\n" + "=" * 78)
    print("PROBE COMPLETE. Nothing was ordered or cancelled.")
    xt.stop()


def dump_obj(label, o):
    keys = sorted(k for k in dir(o) if not k.startswith("_"))
    parts = []
    for k in keys:
        v = getattr(o, k, None)
        if callable(v):
            continue
        parts.append("%s=%r" % (k, v))
    print("  %s: %s" % (label, ", ".join(parts)))


def probe_account(xt, acc, aid):
    print("\n" + "-" * 78)
    print("ACCOUNT", aid)
    print("-" * 78)
    sub = xt.subscribe(acc)
    print("subscribe() ->", sub, "(0 = ok)")

    try:
        asset = xt.query_stock_asset(acc)
        if asset is None:
            print("asset: None")
        else:
            dump_obj("ASSET", asset)
    except Exception as e:
        print("query_stock_asset FAILED:", repr(e))

    try:
        pos = xt.query_stock_positions(acc) or []
    except Exception as e:
        print("query_stock_positions FAILED:", repr(e))
        pos = []
    print("\nPOSITIONS:", len(pos), "row(s)")
    if pos:
        dump_obj("first row (all fields)", pos[0])

    by_code = {}
    for p in pos:
        c = getattr(p, "stock_code", "")
        if c:
            by_code.setdefault(c, []).append(p)

    print("\nT+1 STATE for the 18 names bought 2026-07-29")
    print("  %-11s %9s %11s %10s %9s %8s" % (
        "code", "volume", "can_use", "yesterday", "on_road", "frozen"))
    tradable = 0
    for c in OUR_NAMES:
        rows = by_code.get(c)
        if not rows:
            print("  %-11s %9s   NOT IN POSITION LIST" % (c, "-"))
            continue
        for p in rows:
            cu = int(getattr(p, "can_use_volume", 0) or 0)
            tradable += max(0, cu)
            print("  %-11s %9d %11d %10d %9d %8d" % (
                c,
                int(getattr(p, "volume", 0) or 0),
                cu,
                int(getattr(p, "yesterday_volume", 0) or 0),
                int(getattr(p, "on_road_volume", 0) or 0),
                int(getattr(p, "frozen_volume", 0) or 0),
            ))
    print("  -> total can_use across our names:", tradable)
    print("     can_use == 0 everywhere means T+1 still locks them (expected")
    print("     before the next session's settlement).")

    try:
        orders = xt.query_stock_orders(acc) or []
    except Exception as e:
        print("query_stock_orders FAILED:", repr(e))
        orders = []
    print("\nORDERS:", len(orders), "row(s)")
    if orders:
        dump_obj("first row (all fields)", orders[0])
    mine = [o for o in orders
            if str(getattr(o, "order_remark", "") or "").startswith(STRATEGY_PREFIX)]
    print("  with remark starting %r: %d" % (STRATEGY_PREFIX, len(mine)))
    if mine:
        dump_obj("first OURS", mine[0])

    try:
        trades = xt.query_stock_trades(acc) or []
    except Exception as e:
        print("query_stock_trades FAILED:", repr(e))
        trades = []
    print("\nTRADES (today):", len(trades), "row(s)")
    if trades:
        dump_obj("first row (all fields)", trades[0])
    mt = [t for t in trades
          if str(getattr(t, "order_remark", "") or "").startswith(STRATEGY_PREFIX)]
    print("  with remark starting %r: %d" % (STRATEGY_PREFIX, len(mt)))
    agg = {}
    for t in mt:
        c = getattr(t, "stock_code", "")
        agg[c] = agg.get(c, 0) + int(getattr(t, "traded_volume", 0) or 0)
    if agg:
        print("  our fills by code:",
              ", ".join("%s=%d" % (k, agg[k]) for k in sorted(agg)))
        print("  -> compare against the model-trading DEAL numbers; they should match")


if __name__ == "__main__":
    main()
