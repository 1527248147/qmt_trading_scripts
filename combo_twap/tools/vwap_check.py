# -*- coding: utf-8 -*-
"""READ-ONLY. What did we actually pay, against what the market traded at?

The exec CSV already scores every fill against the touch at the moment it went
out (slip_vs_mid_bp). That measures the ORDER -- did we cross the spread or
earn it. It cannot tell you whether the DAY was well traded: a TWAP that
finishes its whole basket in the worst hour beats the touch on every single
fill and still does badly.

VWAP is the benchmark that answers that. This computes, per name:

    achieved   = sum(qty * price) / sum(qty)          from the exec CSV
    vwap_win   = VWAP over the span we actually traded in
    vwap_day   = VWAP over the whole session

vwap_win is the execution benchmark -- it is the price a perfectly-paced
participant in the same window would have got, so the gap is what our slicing
and queuing earned or cost. vwap_day answers a different question: whether the
window itself was the right one. They can disagree sharply, and when they do
that IS the finding: a good number against the window and a bad one against
the day means the schedule, not the execution, is what to change.

SIGN CONVENTION, matching slip_vs_mid_bp in the exec CSV: this is a COST, so
NEGATIVE IS BETTER. Selling above the benchmark and buying below it both come
out negative.

Needs miniQMT running (xtdata), so run it AFTER the close -- model trading and
miniQMT cannot be up at the same time.

    C:\\QMTGTHT\\bin.x64\\python.exe tools\\vwap_check.py [YYYYMMDD]
"""
import csv
import datetime as dt
import glob
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGS = os.path.join(ROOT, "logs")

TERMINAL = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
            u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df")
sys.path.insert(0, os.path.join(TERMINAL, "bin.x64", "Lib", "site-packages"))
from xtquant import xtdata

DAY = sys.argv[1] if len(sys.argv) > 1 else None


def _fills(path):
    """code -> (shares, sum(qty*px), first HHMM, last HHMM, side)."""
    out = {}
    if not os.path.exists(path):
        return out
    for r in csv.DictReader(io.open(path)):
        q = int(r.get("qty_filled") or 0)
        if q <= 0:
            continue
        try:
            px = float(r.get("price_filled") or 0)
        except ValueError:
            continue
        if px <= 0:
            continue
        # t_done is when the fill was OBSERVED, one bar after it happened;
        # t_place is when the order went out. The traded span is bounded by
        # the placements, so use those.
        t = (r.get("t_place") or "")[:4]
        a = out.setdefault(r["code"], [0, 0.0, "9999", "0000", r.get("side", "")])
        a[0] += q
        a[1] += q * px
        if t and t < a[2]:
            a[2] = t
        if t and t > a[3]:
            a[3] = t
    return out


def _bars(code, day):
    """[(HHMM, close, volume, amount_or_None)] for the day, Beijing time."""
    try:
        xtdata.download_history_data(code, "1m", day, day)
        fields = ["close", "volume", "amount", "time"]
        d = xtdata.get_market_data_ex(fields, [code], period="1m",
                                      start_time=day, end_time=day)
        df = d.get(code)
    except Exception:
        df = None
    if df is None or not len(df):
        return []
    has_amt = "amount" in getattr(df, "columns", [])
    out = []
    for i, ms in enumerate(list(df["time"])):
        bj = dt.datetime.utcfromtimestamp(ms / 1000.0) + dt.timedelta(hours=8)
        out.append((bj.strftime("%H%M"),
                    float(list(df["close"])[i]),
                    float(list(df["volume"])[i]),
                    float(list(df["amount"])[i]) if has_amt else None))
    return out


def _vwap(bars, lo=None, hi=None):
    """VWAP over [lo, hi], or the whole list. None when there is no volume.

    amount/volume is exact when both are present, but their UNITS differ
    between feeds -- volume is often in lots (100 shares) while amount is in
    yuan, which would put the VWAP out by 100x. So compute it, compare against
    the close of the same bars, and fall back to the close-weighted estimate if
    the ratio is not within a factor of two. Getting this silently wrong would
    report a 10,000 bp slippage and look like a catastrophe.
    """
    sel = [b for b in bars
           if (lo is None or b[0] >= lo) and (hi is None or b[0] <= hi)]
    vol = sum(b[2] for b in sel)
    if vol <= 0:
        return None, "no volume in the window"
    est = sum(b[1] * b[2] for b in sel) / vol         # close-weighted
    if all(b[3] is not None for b in sel):
        amt = sum(b[3] for b in sel)
        exact = amt / vol
        for mult in (1.0, 0.01, 100.0):
            v = exact * mult
            if est > 0 and 0.5 < v / est < 2.0:
                return v, ("amount/volume" if mult == 1.0
                           else "amount/volume x%g" % mult)
    return est, "close-weighted (amount unusable)"


def _bp(achieved, bench, side):
    """Cost in bp. Negative is better, for both sides."""
    if not bench:
        return None
    d = (bench - achieved) if side == "sell" else (achieved - bench)
    return d / bench * 10000.0


def run(label, path, day):
    fills = _fills(path)
    if not fills:
        print("\n=== %s: no fills in %s" % (label, os.path.basename(path)))
        return
    print("\n" + "=" * 100)
    print("%s  %s   (cost in bp, NEGATIVE IS BETTER)" % (label, day))
    print("=" * 100)
    print("  %-11s %8s %10s %10s %9s %10s %9s  %s"
          % ("code", "shares", "achieved", "vwap_win", "vs win", "vwap_day",
             "vs day", "window"))
    tq = 0
    tw = 0.0
    td = 0.0
    td_n = 0
    for c in sorted(fills, key=lambda k: -fills[k][0]):
        q, pv, t0, t1, side = fills[c]
        achieved = pv / q
        bars = _bars(c, day)
        if not bars:
            print("  %-11s %8d %10.4f  -- no market data --" % (c, q, achieved))
            continue
        vw, how = _vwap(bars, t0, t1)
        vd, _ = _vwap(bars)
        bw = _bp(achieved, vw, side)
        bd = _bp(achieved, vd, side)
        tq += q
        if bw is not None:
            tw += bw * q
        if bd is not None:
            td += bd * q
            td_n += q
        print("  %-11s %8d %10.4f %10.4f %8s %10.4f %8s  %s-%s %s"
              % (c, q, achieved,
                 vw or 0, ("%.1f" % bw) if bw is not None else "-",
                 vd or 0, ("%.1f" % bd) if bd is not None else "-",
                 t0, t1, "" if how.startswith("amount/volume") else "[" + how + "]"))
    if tq:
        print("  %-11s %8d %10s %10s %8.1f %10s %8s   <- volume-weighted"
              % ("ALL", tq, "", "", tw / tq, "",
                 ("%.1f" % (td / td_n)) if td_n else "-"))


if __name__ == "__main__":
    day = DAY
    if not day:
        cands = sorted(glob.glob(os.path.join(LOGS, "exec_combo_sell_dual_*.csv")))
        day = os.path.basename(cands[-1])[-12:-4] if cands else None
    if not day:
        print("no exec CSV found in %s" % LOGS)
        sys.exit(1)
    print("day %s   logs %s" % (day, LOGS))
    for label, pat in (("SELL", "exec_combo_sell_dual_*_%s.csv"),
                       ("BUY", "exec_combo_buy_dual_%s.csv")):
        for p in sorted(glob.glob(os.path.join(LOGS, pat % day))):
            run(label, p, day)
    print("\nDONE. read-only, no orders placed.")
