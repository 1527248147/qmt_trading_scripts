# -*- coding: utf-8 -*-
"""READ-ONLY. What does get_market_data_ex actually hand back?"""
import os
import sys

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant import xtdata

xtdata.download_history_data("002133.SZ", "1m", "20260825", "20260825")
d = xtdata.get_market_data_ex(["volume", "time"], ["002133.SZ"], period="1m",
                              start_time="20260825", end_time="20260825")
df = d.get("002133.SZ")
print("type", type(df), "len", 0 if df is None else len(df))
if df is not None and len(df):
    print("columns", list(df.columns))
    idx = list(df.index)
    print("index head", idx[:3])
    print("index tail", idx[-3:])
    if "time" in df.columns:
        t = list(df["time"])
        print("time head", t[:3])
        print("time tail", t[-3:])
