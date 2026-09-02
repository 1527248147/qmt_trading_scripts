# -*- coding: utf-8 -*-
"""READ-ONLY. Did the four unexplained names rally enough for their SHARE
target to shrink to zero? tgt = 10000 / price, so a rally shrinks it."""
import os
import sys
import time

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant import xtdata

SLOT = 200000.0 / 20

# code -> (shares held, target at 13:43, price needed for target to drop below
#          held + one lot)
CASES = [("002133.SZ", 3300, 3600, 100),
         ("002573.SZ", 2800, 3100, 100),
         ("300614.SZ", 800, 900, 100),
         ("300625.SZ", 900, 1000, 100),
         ("688162.SH", 401, 411, 200)]

print("  每槽预算 %.0f 元;目标股数 = 预算 / 现价" % SLOT)
print("  %-11s %6s %6s %8s %8s %8s  %s"
      % ("code", "已买", "13:43目标", "13:43价", "收盘价", "收盘目标", "判定"))
for code, held, tgt43, unit in CASES:
    try:
        xtdata.download_history_data(code, "1m", "20260825", "20260825")
        d = xtdata.get_market_data_ex(["close"], [code], period="1m",
                                      start_time="20260825", end_time="20260825")
        df = d.get(code)
        closes = list(df["close"]) if df is not None and len(df) else []
    except Exception as e:
        print("  %-11s 行情读取失败 %r" % (code, e))
        continue
    if not closes:
        print("  %-11s 无行情" % code)
        continue
    last = float(closes[-1])
    px43 = SLOT / tgt43
    tgt_close = int(SLOT / last // 100 * 100) if last > 0 else 0
    short = tgt_close - held
    verdict = ("目标已缩到手上的量以内 -> 退休正确"
               if short < unit else "仍差 %d 股 -> 真缺口" % short)
    print("  %-11s %6d %9d %8.2f %8.2f %8d  %s"
          % (code, held, tgt43, px43, last, tgt_close, verdict))
