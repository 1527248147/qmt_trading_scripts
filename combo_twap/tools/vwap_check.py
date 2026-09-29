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


def _fills(paths):
    """code -> (shares, sum(qty*px), first HHMM, last HHMM, side), pooled.

    Takes EVERY file of the day at once, because de-duplication has to see
    across them. Until 2026-09-02 _exec_close recorded each order twice -- once
    correctly, then once more a bar later through the orphan branch, tagged
    "adopted" with the slippage columns blank -- and a restart or a directory
    fallback could put the two halves in different files. The strategy no
    longer does that, but the files it already wrote still say it, and this
    tool has to read them honestly.

    An order is identified by what the counter reported about it: the day, the
    time the fill was observed, the code, the size sent, the size filled and
    the price. The adopted twin carries no t_place, so the real row is kept in
    preference to it.
    """
    seen = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(io.open(path)):
            # The order's remark, where the file carries one, is the exact
            # identity: a restart's "adopted" re-record of an earlier fill has
            # a different t_done, so the tuple below cannot pair the two.
            key = (r.get("remark") or None) or (
                   r.get("date", ""), r.get("t_done", ""), r.get("code", ""),
                   r.get("qty_sent", ""), r.get("qty_filled", ""),
                   r.get("price_filled", ""))
            if key in seen and not seen[key].get("t_place"):
                seen[key] = r        # prefer the row that knows when it went out
            elif key not in seen:
                seen[key] = r
    out = {}
    for r in seen.values():
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


def run(label, paths, day):
    # POOL THE WHOLE DAY. Scoring each file on its own produced one
    # mini-report per fragment, each with its own "volume-weighted"
    # line -- six partial answers to a question about the day.
    fills = _fills(paths)
    if not fills:
        print("=== %s: no fills for %s" % (label, day))
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


# WHERE THE DAY'S EXEC ROWS ACTUALLY ARE.
#
# Two things scattered them. The strategy falls back through a chain of
# directories when the preferred one refuses an open, and it appends a session
# tag to the filename when a restart finds the plain name already taken. On
# 2026-09-02 one morning's execution record ended up in six files across three
# directories, and this tool -- which globbed a single directory for a single
# exact name -- read 2 of the 12 rows that existed, out of 94 orders.
#
# So: every directory the strategy can write to, and a wildcard for the session
# tag. The account tag is matched the same way; the buy side went without one
# until 2026-09-02.
EXEC_DIRS = (LOGS,
             # Forward slashes: glob and os.path.join take them on
             # Windows, and they cannot be mangled by an escape.
             "C:/QMTGTHT/local_run/combo_top20_twap",
             "C:/QMTGTHT/local_run/combo_top20_twap/logs",
             "C:/Users/Public/Documents")


def _exec_paths(prefix, day):
    """Every exec CSV for one side and one day, in every fallback directory."""
    out = []
    for d in EXEC_DIRS:
        for pat in (prefix + "_" + day + ".csv",
                    prefix + "_" + day + "_*.csv",
                    prefix + "_*_" + day + ".csv",
                    prefix + "_*_" + day + "_*.csv"):
            out += glob.glob(os.path.join(d, pat))
    return sorted(set(out))


if __name__ == "__main__":
    day = DAY
    if not day:
        cands = []
        for d in EXEC_DIRS:
            cands += glob.glob(os.path.join(d, "exec_combo_*_dual_*.csv"))
        days = set()
        for c in cands:
            for tok in os.path.basename(c)[:-4].split("_"):
                if len(tok) == 8 and tok.isdigit() and tok.startswith("20"):
                    days.add(tok)
        day = max(days) if days else None
    if not day:
        print("no exec CSV found under %s" % (", ".join(EXEC_DIRS)))
        sys.exit(1)
    print("day %s   logs %s" % (day, LOGS))
    for label, prefix in (("SELL", "exec_combo_sell_dual"),
                          ("BUY", "exec_combo_buy_dual")):
        paths = _exec_paths(prefix, day)
        if paths:
            for p in paths:
                print("  reading %s" % p)
            run(label, paths, day)
    print("DONE. read-only, no orders placed.")
