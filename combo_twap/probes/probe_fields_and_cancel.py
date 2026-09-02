#coding:gbk
# ============================================================================
# ZERO-COST PROBE  --  QMT model trading
# ----------------------------------------------------------------------------
# Purpose: settle the two biggest unknowns in the live trading path WITHOUT
# spending money, by placing ONE limit buy order priced far BELOW the market so
# it can never fill, then cancelling it.
#
#   1. Field names. Everything the TWAP scripts read from ACCOUNT / POSITION /
#      ORDER objects (m_dBalance, m_dAvailable, m_nVolume, m_nCanUseVolume,
#      m_nOrderStatus, m_nDirection, m_strRemark, order id, insert time...) is
#      currently GUESSED from common QMT naming. This dumps what really exists.
#   2. Cancelling. cancel() / can_cancel_order() have never been executed. A
#      counterparty-price order fills instantly so it can never exercise them;
#      a deliberately unfillable order can.
#
# Cost: the order never fills, so there is no commission, no stamp tax and no
# position. Only the (usually free) cancelled-order flow fee, if your broker
# charges one.
#
# HOW TO RUN
#   1. Set TEST_CODE below to a cheap MAIN-BOARD stock you are allowed to trade
#      (no STAR/ChiNext/BJ permission needed). 100 shares is enough.
#   2. Load in QMT -> model trading, period 1 minute, BIND YOUR ACCOUNT, run
#      during trading hours.
#   3. It acts once, prints the field dumps, waits CANCEL_AFTER_MIN, cancels,
#      and stops acting. Send me the log.
#
# SAFETY
#   * Buy price = last close * PRICE_DISCOUNT (default 0.90) and is additionally
#     clamped to >= the down-limit, so it rests far from the touch. Verify in
#     the log that "limit px" really is well below "last px" before trusting it.
#   * ONE order per run, guarded by a latch. Re-running places one more.
#   * If anything looks wrong, press the STOP button and cancel manually in the GUI.
# ============================================================================

TEST_CODE = "688538.SH"      # <-- EDIT: the code to probe
TEST_SHARES = 200            # <-- EDIT: 100 for main/ChiNext, 200 for STAR(688)/BJ
                             #     Sending 100 on a 688 name is rejected for LOT SIZE,
                             #     which looks identical to a permission rejection.
PRICE_DISCOUNT = 0.90        # limit price = last * this (far below market)
CANCEL_AFTER_MIN = 2         # cancel this many minutes after placing
PRTYPE_FIX = 11              # QMT fun.xml: 11 = model/limit price; PRICE is used only then
PRTYPE_COMPETE = 14          # (reference) 14 = counterparty price, used by the TWAP scripts
STRATEGY = "probe_fields"
TICK = 0.01

import datetime as dt


class _S(object):
    pass

S = _S()
print("MODULE probe_fields_and_cancel imported OK")


def _bar_datetime(C):
    tt = C.get_bar_timetag(C.barpos)
    china = dt.datetime.utcfromtimestamp(tt / 1000.0) + dt.timedelta(hours=8)
    return china.strftime("%Y%m%d"), china.strftime("%H%M%S")


def _sess_min(hhmmss):
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    if t <= 690:
        return min(120, max(0, t - 570))
    return min(240, 120 + (t - 780))


def _dump(label, objs, limit=2):
    """Print every m_* attribute of the first `limit` objects."""
    print("-" * 70)
    if not objs:
        print(label, ": EMPTY (no rows returned)")
        return
    print(label, ":", len(objs), "row(s)")
    for i, o in enumerate(objs[:limit]):
        attrs = [a for a in dir(o) if a.startswith("m_")]
        print("  --- row", i, "has", len(attrs), "fields ---")
        for a in sorted(attrs):
            try:
                v = getattr(o, a)
            except Exception as e:
                v = "<err " + type(e).__name__ + ">"
            if callable(v):
                continue
            print("     %-32s = %r" % (a, v))


def _query(kind):
    try:
        return list(get_trade_detail_data(S.acct, S.acct_type, kind) or [])
    except Exception as e:
        print("query", kind, "FAILED:", repr(e))
        return []


def _last_price(C, today, hhmmss):
    """Last traded price from the most recent completed 1m bar."""
    for back in range(0, 30):
        t = _sess_min(hhmmss) - back
        if t < 0:
            break
        mm = 570 + t if t <= 120 else 780 + (t - 120)
        lab = "%02d%02d00" % (mm // 60, mm % 60)
        try:
            d = C.get_market_data_ex(["close"], [TEST_CODE], period="1m",
                                     start_time=today + lab, end_time=today + lab,
                                     fill_data=False)
            f = d.get(TEST_CODE)
            if f is not None and len(f) > 0:
                px = float(f.iloc[-1]["close"])
                if px > 0:
                    return px, lab
        except Exception:
            pass
    return 0.0, ""


def _order_id(o):
    for a in ("m_strOrderSysID", "m_nOrderID", "m_strOrderID", "m_nOrderSysID"):
        v = getattr(o, a, None)
        if v not in (None, "", 0):
            return a, v
    return None, None


def init(C):
    try:
        S.acct = account
        S.acct_type = accountType
    except NameError:
        S.acct = ""
        S.acct_type = "STOCK"
        print("WARN: no injected account -> bind an account in the model GUI."
              " Without it this probe cannot place or query anything.")
    S.buy_code = 23 if S.acct_type == "STOCK" else 33
    S.placed = False
    S.placed_min = None
    S.cancelled = False
    S.remark = ""
    S.done = False
    try:
        C.set_universe([TEST_CODE, "000001.SZ"])
    except Exception:
        pass
    print("INIT probe | account", repr(S.acct), S.acct_type,
          "| code", TEST_CODE, "| shares", TEST_SHARES,
          "| discount", PRICE_DISCOUNT, "| cancel after", CANCEL_AFTER_MIN, "min")


def handlebar(C):
    if not C.is_last_bar() or S.done:
        return
    today, hhmmss = _bar_datetime(C)
    if hhmmss < "093100" or hhmmss > "145000":
        return
    if not S.acct:
        return

    # ---------- step 1: place ONE unfillable limit order ----------
    if not S.placed:
        S.placed = True
        print("=" * 70)
        print("STEP 1  place an unfillable limit order |", today, hhmmss)

        _dump("ACCOUNT (before)", _query("ACCOUNT"))
        _dump("POSITION (before)", _query("POSITION"), limit=3)

        last, lab = _last_price(C, today, hhmmss)
        if last <= 0:
            print("  no price for", TEST_CODE, "-> aborting probe")
            S.done = True
            return
        px = round(round(last * PRICE_DISCOUNT / TICK) * TICK, 2)
        try:
            d = C.get_instrument_detail(TEST_CODE) or {}
            down = float(d.get("DownStopPrice") or 0)
            if down > 0 and px < down:
                px = down            # never price through the down limit
                print("  clamped to down-limit")
        except Exception:
            pass
        print("  last px %.2f (bar %s) -> limit px %.2f  (%.0f%% below)"
              % (last, lab, px, (1 - px / last) * 100))
        if px >= last:
            print("  limit price is NOT below market -> aborting to avoid a fill")
            S.done = True
            return

        S.remark = "%s_%s_%s" % (STRATEGY, TEST_CODE.replace(".", "_"), hhmmss)
        S.placed_min = _sess_min(hhmmss)
        print("  passorder(op=%d, 1101, acct, %s, prType=%d FIX, price=%.2f, vol=%d, remark=%s)"
              % (S.buy_code, TEST_CODE, PRTYPE_FIX, px, TEST_SHARES, S.remark))
        try:
            passorder(S.buy_code, 1101, S.acct, TEST_CODE, PRTYPE_FIX, px,
                      TEST_SHARES, STRATEGY, 1, S.remark, C)
            print("  passorder returned without exception")
        except Exception as e:
            print("  passorder FAILED:", repr(e))
            S.done = True
        return

    # ---------- step 2: next bar, dump the ORDER object ----------
    if S.placed and not S.cancelled:
        orders = _query("ORDER")
        _dump("ORDER (after placing)", orders, limit=3)
        mine = [o for o in orders if getattr(o, "m_strRemark", "") == S.remark]
        print("  orders matching our remark %r : %d" % (S.remark, len(mine)))
        if not mine:
            print("  !! our order is NOT in the ORDER list. Either the remark field"
                  " differs, or the order was rejected. Check the GUI order list.")
        else:
            # Dump OUR order specifically. The generic dump above shows whatever is
            # first in the list (often a stale order from an earlier run), which
            # hides the error message when our own order was rejected.
            _dump("OUR ORDER (matched by remark)", mine, limit=1)
            o0 = mine[0]
            stt = getattr(o0, "m_nOrderStatus", None)
            if stt == 57:
                print("  !! STATUS 57 = REJECTED (junk order). Reason fields:")
                for a in ("m_strErrorMsg", "m_nErrorID", "m_strCancelInfo",
                          "m_strLocalInfo", "m_strOptName"):
                    print("     %-18s = %r" % (a, getattr(o0, a, None)))
                print("     shares sent    =", getattr(o0, "m_nVolumeTotalOriginal", None),
                      "(STAR/688 needs >= 200, main/ChiNext >= 100)")

        age = _sess_min(hhmmss) - (S.placed_min or 0)
        if age < CANCEL_AFTER_MIN:
            print("  age %d min < %d, waiting before cancel" % (age, CANCEL_AFTER_MIN))
            return

        # ---------- step 3: cancel ----------
        print("=" * 70)
        print("STEP 3  cancel |", today, hhmmss, "| age", age, "min")
        if not mine:
            print("  nothing matched our remark -> cannot test cancel by remark;"
                  " cancel manually in the GUI if an order is resting.")
            S.done = True
            return
        o = mine[0]
        attr, oid = _order_id(o)
        print("  order id field:", attr, "=", repr(oid))
        if oid is None:
            print("  !! no usable order id -> cancel() cannot be called."
                  " Send me the ORDER dump so I can pick the right field.")
            S.done = True
            return
        try:
            ok = can_cancel_order(oid, S.acct, S.acct_type)
            print("  can_cancel_order ->", repr(ok))
        except Exception as e:
            print("  can_cancel_order FAILED:", repr(e))
        try:
            r = cancel(oid, S.acct, S.acct_type, C)
            print("  cancel() returned", repr(r))
        except Exception as e:
            print("  cancel() FAILED:", repr(e))
        S.cancelled = True
        return

    # ---------- step 4: confirm it is gone ----------
    if S.cancelled:
        orders = _query("ORDER")
        mine = [o for o in orders if getattr(o, "m_strRemark", "") == S.remark]
        print("=" * 70)
        print("STEP 4  after cancel | matching orders:", len(mine))
        for o in mine:
            print("   status =", getattr(o, "m_nOrderStatus", "?"),
                  " traded =", getattr(o, "m_nVolumeTraded", "?"),
                  " total =", getattr(o, "m_nVolumeTotalOriginal", "?"))
        _dump("POSITION (after)", _query("POSITION"), limit=3)
        print("PROBE COMPLETE -- send this whole log back.")
        S.done = True


def stop(C):
    if S.placed and not S.cancelled:
        print("STOP: an order may still be resting -- check the GUI and cancel it.")
    print("STOP probe | placed", S.placed, "| cancelled", S.cancelled)
