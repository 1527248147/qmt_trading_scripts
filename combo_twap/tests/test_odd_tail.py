#coding:utf-8
"""Can an awkward quantity be fully liquidated, or does a tail get stranded?

The worry: hold 565 shares on the main board, sell 500 in five lots, and the
last 65 are below the 100-share minimum and stick forever.

Drives combo_sell_dual_model.handlebar() through complete sessions for a range
of awkward holdings and asserts the position reaches zero. Reuses the fake
broker from test_sell_model_offline so the same lag and per-bar behaviour apply.

    C:\\QMTGTHT\\bin.x64\\python.exe test_odd_tail.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The suite lives in tests/ and the strategies live one level up. ROOT is
# what everything else in this file means by "the project directory".
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import test_sell_model_offline as T
# Which sell script is under test. The dual-mode copy has its own phase
# logic (TWAP/RUSH/CANCEL/AUCTION) that the original does not, and a green
# run here says nothing about the other file -- so make the target explicit:
#     set SELL_MODULE=combo_sell_dual_model && python test_sell_model_offline.py
import os as _os
M = __import__(_os.environ.get('SELL_MODULE', 'combo_sell_dual_model'))

M.S.run_log = False
fails = []


def run_case(code, held, target, price, lots=5000, extra_held=0):
    """Sell `target` out of a position of `held` + `extra_held` not ours."""
    M.SELL_TARGETS = {code: target}
    M.MAX_TARGET_SHARES = max(20000, target)
    T.BARS = {code: {"close": price, "volume": lots, "high": price * 1.02,
                     "low": price * 0.98, "preclose": price}}
    book = T.Book({code: (held + extra_held, held + extra_held)})
    sent = T.run_session(T.all_minutes(), book)
    got = sum(s[2] for s in sent if s[1] == code)
    slices = [s[2] for s in sent if s[1] == code]
    left_ours = target - got
    return got, slices, left_ours


print("=" * 96)
print("ODD-TAIL LIQUIDATION")
print("=" * 96)
print("%-11s %-9s %7s %7s %8s %8s  %s"
      % ("code", "board", "held", "target", "sold", "stranded", "slices"))

CASES = [
    # code,        held, target, price, extra_held(not ours)
    ("600805.SH",   565,   565,  4.18, 0),   # the exact case asked about
    ("600805.SH",   500,   500,  4.18, 0),   # clean multiple of the lot
    ("600805.SH",    99,    99,  4.18, 0),   # whole position below one lot
    ("600805.SH",   100,   100,  4.18, 0),   # exactly one lot
    ("600805.SH",  1001,  1001,  4.18, 0),   # 1 share over ten lots
    ("688058.SH",   203,   203, 19.93, 0),   # STAR, 200 minimum + 3 tail
    ("688058.SH",   199,   199, 19.93, 0),   # STAR, whole position under 200
    ("920002.BJ",   565,   565, 51.68, 0),   # BJ, 100 minimum, 1-share step
    ("300883.SZ",   565,   565,  5.37, 0),   # ChiNext, same rules as main
]

for code, held, target, price, extra in CASES:
    got, slices, left = run_case(code, held, target, price, extra_held=extra)
    board = ("STAR" if code.startswith("688") else
             "BJ" if code.endswith(".BJ") else
             "ChiNext" if code[:3] in ("300", "301") else "main")
    tag = "" if left == 0 else "  <-- STRANDED"
    print("%-11s %-9s %7d %7d %8d %8d  %s%s"
          % (code, board, held, target, got, left,
             "+".join(str(x) for x in slices), tag))
    if left != 0:
        fails.append("%s left %d of %d unsold" % (code, left, target))

print()
print("=" * 96)
print("TRIM vs FLATTEN  (a tail below the minimum is only legal when it")
print("                  liquidates the position -- these SHOULD strand)")
print("=" * 96)
print("%-11s %-9s %7s %7s %8s %8s  %s"
      % ("code", "board", "held", "target", "sold", "stranded", "note"))
for code, held, target, price, extra in [
        ("600805.SH", 565, 565, 4.18, 10000),
        ("688058.SH", 203, 203, 19.93, 7379497)]:
    got, slices, left = run_case(code, held, target, price, extra_held=extra)
    board = "STAR" if code.startswith("688") else "main"
    expected_left = target % M._min_lot(code) if M._lot_step(code) == 100 else \
        target - (target // M._min_lot(code)) * M._min_lot(code)
    ok = left == expected_left
    print("%-11s %-9s %7d %7d %8d %8d  %s"
          % (code, board, held, target, got, left,
             "expected -- exchange would reject the odd lot" if ok
             else "UNEXPECTED, wanted %d stranded" % expected_left))
    if not ok:
        fails.append("%s stranded %d, expected %d" % (code, left, expected_left))

print()
print("=" * 96)

# ---------------------------------------------------------------------------
# THE TWO ODD TAILS IN THE 2026-09-01 LIVE BASKET.
# 688567.SH holds 817 and 688533.SH holds 411 -- STAR names, where the minimum
# order is 200 but the step is 1. Selling those down leaves a remainder under
# the minimum, and the exchange accepts it ONLY as a flatten. Getting this
# wrong strands ~100 shares of a real position with no way to sell them except
# by hand.
# ---------------------------------------------------------------------------
for _code, _hold in (("688567.SH", 817), ("688533.SH", 411)):
    _left = _hold
    _orders = []
    _guard = 0
    while _left > 0 and _guard < 50:
        _guard += 1
        _q = M._round_sell(_code, _left, _left, _left)   # flattening: held == remaining
        if _q <= 0:
            break
        _orders.append(_q)
        _left -= _q
    print("     %s %-4d -> %s   (%d left)" % (_code, _hold, _orders, _left))
    if _left != 0:
        fails.append("%s %d did not liquidate: %d stranded" % (_code, _hold, _left))
    _bad = [o for o in _orders[:-1] if o < M._min_lot(_code)]
    if _bad:
        fails.append("%s sent sub-minimum orders before the tail: %s" % (_code, _bad))

# And the mirror that must still be refused: the same odd remainder while the
# account holds far more is a TRIM, not a flatten, and the exchange rejects it.
if M._round_sell("688567.SH", 17, 17, 50000) != 0:
    fails.append("an odd TRIM was allowed -- the exchange would reject it")
if M._round_sell("688567.SH", 17, 17, 17) != 17:
    fails.append("the identical FLATTEN was refused -- the tail would strand")
print("     trim-vs-flatten on a 17-share tail: refused / allowed as expected")

if fails:
    print("FAILED %d case(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CASES FULLY LIQUIDATED (except the trim cases, as designed)")
print("=" * 96)
