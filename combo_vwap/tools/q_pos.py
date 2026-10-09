# -*- coding: utf-8 -*-
"""READ-ONLY position + cash dump for every stock account. Places no orders.

There is not a single passorder in this file, by design: it exists only to tell
the two trading scripts what the account actually holds before their targets
are edited.
"""
import os
import sys
import time

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
from xtquant import xtdata

xt = XtQuantTrader(os.path.join(TERMINAL, "userdata_mini"),
                   int(time.time()) % 1000000000)
xt.start()
if xt.connect() != 0:
    print("connect failed -- is miniQMT running and model trading closed?")
    sys.exit(1)


def is_stock(c):
    stk, mkt = c.split(".")
    if mkt == "SH":
        return stk.startswith(("60", "68"))
    if mkt == "SZ":
        return stk.startswith(("00", "30"))
    if mkt == "BJ":
        return stk.startswith(("43", "83", "87", "92"))
    return False


accs = sorted(set(a.account_id for a in xt.query_account_infos()
                  if a.account_type == 2))
print("stock accounts: %s" % accs)

for aid in accs:
    acc = StockAccount(aid)
    if xt.subscribe(acc) != 0:
        print("\n### %s subscribe FAILED" % aid)
        continue
    try:
        ast = xt.query_stock_asset(acc)
        cash, total = ast.cash, ast.total_asset
    except Exception:
        cash = total = -1.0
    rows = []
    for p in xt.query_stock_positions(acc) or []:
        c = p.stock_code
        v = int(getattr(p, "volume", 0) or 0)
        cu = int(getattr(p, "can_use_volume", 0) or 0)
        if v <= 0 or not is_stock(c) or v > 200000:
            continue
        try:
            nm = (xtdata.get_instrument_detail(c) or {}).get("InstrumentName", "?")
            last = float(xtdata.get_full_tick([c]).get(c, {}).get("lastPrice", 0) or 0)
        except Exception:
            nm, last = "?", 0.0
        rows.append((v * last, c, nm, v, cu, last))
    rows.sort(reverse=True)
    print("\n=== %s  cash %.2f  total %.2f  holdings %d ===" % (aid, cash, total, len(rows)))
    print("%-11s %-10s %9s %10s %8s %12s" % ("code", "name", "volume", "can_use", "last", "value"))
    tv = 0.0
    for val, c, nm, v, cu, last in rows:
        print("%-11s %-10s %9d %10d %8.2f %12.0f" % (c, nm[:10], v, cu, last, val))
        tv += val
    print("%-11s %-10s %9s %10s %8s %12.0f" % ("TOTAL", "", "", "", "", tv))

xt.stop()
print("\nDONE. read-only, no orders placed.")
