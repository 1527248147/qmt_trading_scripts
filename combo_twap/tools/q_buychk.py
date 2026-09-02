# -*- coding: utf-8 -*-
"""READ-ONLY. Did the BUY script's idea of "bought today" match the account?

The sell side's `sold` overstated by 5,756 on 688800.SH today because the DEAL
query over-reported. The buy side derives its progress the same way -- from
max(position-baseline, sent, DEAL) -- so it is exposed to the same fault. This
compares, per name: what the account gained since the opening baseline, against
what the exec CSV recorded as filled.
"""
import csv
import io
import os
import sys
import time

ROOT = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap"
TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

# Opening baseline, written by the buy script at its first bar.
base = {}
for d in (os.path.join(ROOT, "logs"), ROOT, os.path.join(ROOT, "archive", "2026-08")):
    p = os.path.join(d, "baseline_combo_buy_dual_1000003_20260828.csv")
    if os.path.exists(p):
        for ln in io.open(p).readlines()[1:]:
            q = ln.strip().split(",")
            if len(q) >= 2:
                try:
                    base[q[0]] = int(q[1])
                except ValueError:
                    pass
        print("baseline from %s: %d name(s)" % (d, len(base)))
        break
if not base:
    print("no buy baseline found -- cannot compare")

ex = {}
p = os.path.join(ROOT, "logs", "exec_combo_buy_dual_20260828.csv")
for x in csv.DictReader(open(p)):
    ex[x['code']] = ex.get(x['code'], 0) + int(x['qty_filled'] or 0)

xt = XtQuantTrader(os.path.join(TERMINAL, "userdata_mini"),
                   int(time.time()) % 1000000000)
xt.start()
if xt.connect() != 0:
    print("connect failed")
    sys.exit(1)
acc = StockAccount("1000003")
xt.subscribe(acc)
pos = {}
for pp in (xt.query_stock_positions(acc) or []):
    pos[pp.stock_code] = int(getattr(pp, "volume", 0) or 0)

print("%-11s %10s %10s %10s %10s  %s"
      % ("code", "baseline", "now", "gained", "exec", "verdict"))
bad = 0
for c in sorted(ex, key=lambda k: -ex[k]):
    b = base.get(c)
    n = pos.get(c, 0)
    if b is None:
        print("%-11s %10s %10d %10s %10d  no baseline row" % (c, "-", n, "-", ex[c]))
        continue
    gained = n - b
    ok = abs(gained - ex[c]) <= 0
    if not ok:
        bad += 1
    print("%-11s %10d %10d %10d %10d  %s"
          % (c, b, n, gained, ex[c], "" if ok else "MISMATCH %+d" % (gained - ex[c])))
print("\n%d name(s) where the account disagrees with exec" % bad)
xt.stop()
print("DONE. read-only.")
