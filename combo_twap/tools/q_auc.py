# -*- coding: utf-8 -*-
"""READ-ONLY. Did the 14:57 closing-auction orders fill?

Compares the account's holding against what the buy script had before the
auction, for the two names it topped up, and shows the sell basket's remainder.
No passorder anywhere in this file.
"""
import os
import sys
import time

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

xt = XtQuantTrader(os.path.join(TERMINAL, "userdata_mini"),
                   int(time.time()) % 1000000000)
xt.start()
if xt.connect() != 0:
    print("connect failed")
    sys.exit(1)

# The buy script's own count just before 14:57, from its log.
BUY_BEFORE = {"603028.SH": 1300, "603282.SH": 500}
SELL_TGT = {"688800.SH": 50000, "601398.SH": 8500, "600981.SH": 5000,
            "600050.SH": 1300, "600283.SH": 1200, "600816.SH": 1024,
            "600968.SH": 1000, "600628.SH": 900, "601318.SH": 200}
SZ = {"300363.SZ": 20000, "000972.SZ": 2000, "000063.SZ": 600}

for aid, want in (("1000003", BUY_BEFORE), ("1000310", None)):
    acc = StockAccount(aid)
    if xt.subscribe(acc) != 0:
        print("\n### %s subscribe FAILED" % aid)
        continue
    pos = {}
    for p in (xt.query_stock_positions(acc) or []):
        pos[p.stock_code] = (int(getattr(p, "volume", 0) or 0),
                             int(getattr(p, "can_use_volume", 0) or 0))
    try:
        cash = xt.query_stock_asset(acc).cash
    except Exception:
        cash = -1.0
    print("\n=== %s  cash %.2f ===" % (aid, cash))
    if want:
        print("  BUY auction top-ups:")
        for c, before in sorted(want.items()):
            v = pos.get(c, (0, 0))[0]
            print("     %-11s before 14:57 = %5d   now = %5d   -> %s"
                  % (c, before, v,
                     "FILLED %d" % (v - before) if v > before else "not filled"))
    else:
        print("  SELL basket remainder (Shanghai, target was full liquidation):")
        left = 0
        for c in sorted(SELL_TGT, key=lambda k: -SELL_TGT[k]):
            v = pos.get(c, (0, 0))[0]
            left += max(0, v)
            print("     %-11s holding %6d %s" % (c, v, "CLEAR" if v <= 0 else "<-- left"))
        print("     Shanghai left in total: %d" % left)
        print("  Shenzhen (blocked by 250253 all day):")
        for c in sorted(SZ, key=lambda k: -SZ[k]):
            print("     %-11s holding %6d / target %d" % (c, pos.get(c, (0, 0))[0], SZ[c]))

xt.stop()
print("\nDONE. read-only, no orders placed.")
