# -*- coding: utf-8 -*-
"""READ-ONLY. Did the four names that stopped short on 2026-08-25 simply have
no volume in the bars where the script needed to size a slice?

The buy loop skips a name outright when the last completed bar has
q["volume"] == 0, and until last night that skip printed nothing at all. If
those bars really were empty, that branch is the whole explanation.
"""
import datetime as dt
import os
import sys

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant import xtdata

# code -> (held at close, target at close, one lot)
CASES = [("002133.SZ", 3300, 3500, 100),
         ("002573.SZ", 2800, 3100, 100),
         ("300614.SZ", 800, 900, 100),
         ("300625.SZ", 900, 1000, 100),
         ("600533.SH", 4500, 4500, 100)]      # control: this one finished

DAY = "20260825"
PARTICIPATION = 0.10


def minutes(df):
    """[(hhmm Beijing, volume in lots)] for the 13:44-15:00 window.

    The frame's INDEX is the PC's local clock (this machine runs US Eastern, so
    Beijing is local + 12h) -- reading HHMM straight off it lands in the middle
    of the night and matches nothing. The `time` column is a plain UTC epoch in
    milliseconds, which is unambiguous, so use that.
    """
    out = []
    for ms, v in zip(list(df["time"]), list(df["volume"])):
        bj = dt.datetime.utcfromtimestamp(ms / 1000.0) + dt.timedelta(hours=8)
        hhmm = bj.strftime("%H%M")
        if "1344" <= hhmm <= "1500":
            out.append((hhmm, int(v)))
    return out


for code, held, tgt, unit in CASES:
    try:
        xtdata.download_history_data(code, "1m", DAY, DAY)
        d = xtdata.get_market_data_ex(["volume", "time"], [code], period="1m",
                                      start_time=DAY, end_time=DAY)
        df = d.get(code)
    except Exception as e:
        print("  %-11s 行情读取失败 %r" % (code, e))
        continue
    if df is None or not len(df):
        print("  %-11s 无数据" % code)
        continue
    rows = minutes(df)
    if not rows:
        print("  %-11s 该时段无 bar" % code)
        continue
    short = tgt - held
    zero = sum(1 for _, v in rows if v == 0)
    # A bar can only fund a slice if 10% of it reaches one lot.
    thin = sum(1 for _, v in rows if v > 0 and int(PARTICIPATION * v * 100) < unit)
    ok = len(rows) - zero - thin
    print("  %-11s 缺 %4d 股 | 13:44-15:00 共 %d 根 bar:"
          "  零成交 %d,  10%%不够一手 %d,  足够下单 %d"
          % (code, short, len(rows), zero, thin, ok))
