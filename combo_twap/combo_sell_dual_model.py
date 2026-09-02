#coding:gbk
# ============================================================================
# TWAP SELL -- QMT MODEL TRADING (paste into the QMT editor, 1 minute period)
# ----------------------------------------------------------------------------
# Liquidates an EXPLICIT list of positions on CLOSE_DATE, sliced TWAP over
# SELL_START..SELL_END with a volume-participation cap and a spread filter.
# Mirrors qmt_combo_top20_twap.py (the backtested strategy) on the sell side.
#
# ASCII ONLY. The QMT editor saves as GBK; any non-ASCII byte here has broken
# this file before. Keep every comment in English.
#
# ----------------------------------------------------------------------------
# EVERYTHING IS MIRRORED TO A LOG FILE
# Console output in the QMT window cannot be read by anyone who is not sitting
# at the machine, and it is lost when the window closes. Every line printed here
# is also appended (and flushed) to
#     LOG_DIR\run_combo_sell_close_<CLOSE_DATE>.log
# File IO is blocked in the editor's backtest/simulation sandbox but works in
# real model trading -- proved on 2026-07-29, when the buy script wrote both its
# baseline and its trade CSV.
#
# ----------------------------------------------------------------------------
# WHY SELL_TARGETS IS AN EXPLICIT SHARE COUNT, NOT "SELL EVERYTHING"
# The account used for testing holds 1395 positions that are not ours, some of
# them enormous: 603659.SH shows 99,986,700 shares of which 200 are ours, and
# 003816.SZ shows 23,500 of which 1,100 are ours. A "flatten what we hold"
# script pointed at that account would dump 100 million shares belonging to
# someone else. Quantities are stated in full below and never exceeded.
#
# Two independent caps apply to every name:
#     1. SELL_TARGETS[code]          -- what we believe we bought
#     2. max(0, m_nCanUseVolume)     -- what the broker will actually release
# The lesser wins. can_use is NEGATIVE on several names in this account because
# it carries short positions and m_nVolume is a NET figure, so the clamp at zero
# is load-bearing, not defensive dressing.
# ============================================================================

import datetime as dt

# ------------------------------------------------------------------ config --
# EDIT: the day this script may act. Any other date -> it says so and waits.
CLOSE_DATE = "20260901"
CLOSE_UNTIL = "20260901"        # keep retrying names left unsold, up to this date

# EDIT: exact share counts to liquidate. This is the ONLY thing that changes
# between runs -- point it at whatever the strategy needs to close out.
#
# --- 2026-08-03: FULL LIQUIDATION, the last rehearsal before going live -----
# Every earlier basket sold a SLICE of a position, because a slice was all the
# account could be trusted to release. This one is different: it is a genuine
# sell-everything, which is what the strategy actually does on a close day
# (qmt_combo_top20_twap.py _plan_sells sets every held name to target 0).
#
# Read live from account 1000310 via miniQMT at 08:20 Beijing, minutes before
# this edit -- not carried over from an earlier scan. The account holds 18 rows
# with a positive volume; the 5 below are excluded and the other 13 are the
# basket, each at its FULL held quantity:
#
#   009908.SH  1,000,000  no name, no quote  -- a bond, not a stock
#   112285.SH     50,000  no name, no quote  -- corporate bond
#   110075.SZ      5,000  no name, no quote  -- convertible, and the .SZ suffix
#                                               on a 110xxx code is itself wrong
#   510050.SH    601,300  SSE50 ETF          -- ETF lot rules differ
#   512480.SH  1,000,000  Semiconductor ETF  -- ETF lot rules differ
#
# The 13 that ARE sold, with the branch each one exercises:
#
#   688800.SH  50,000  STAR     48.60   min lot 200 step 1
#   300363.SZ  20,000  ChiNext  15.54   Shenzhen leg
#   601398.SH   8,500  main SH   7.99
#   600981.SH   5,000  main SH   2.33
#   000972.SZ   2,000  main SZ   3.27   Shenzhen leg
#   600050.SH   1,300  main SH   4.46
#   600283.SH   1,200  main SH   7.89   thinnest name -> PARTICIPATION CAP binds
#   600816.SH   1,024  main SH   2.56   <-- ODD-LOT FLATTEN, see below
#   600968.SH   1,000  main SH   3.90
#   600628.SH     900  main SH   6.09
#   000063.SZ     600  main SZ  33.81   Shenzhen leg
#   601318.SH     200  main SH  54.90
#   601336.SH     100  main SH  63.14   <-- NEGATIVE can_use, see below
#
# 600816.SH is the test that has never been run. 1,024 shares = 10 lots plus a
# 24-share remainder, and selling all 1,024 FLATTENS the position, so the
# exchange must ACCEPT the 24. Every previous run only proved the opposite case
# (688800.SH's 3-share trim was correctly refused). Expect a 24-share order to
# go out and fill -- if instead it logs "UNSELLABLE 600816.SH 24 shares left",
# the flattening branch at line ~322 is wrong and live trading would strand a
# tail on every name.
#
# 601336.SH holds 100 shares but can_use is -99. allowed = min(tgt, s + max(0,
# cu)) = min(100, 0) = 0, so the dual cap must refuse it outright and send NO
# order. It is in the basket precisely to prove that guard fires.
#
# Capacity checked against the last 5 sessions' average volume: at 10%
# participation the slowest name (688800.SH) needs 9 minutes and every other
# name under 3. Nothing here can fail to finish for want of liquidity, so any
# name left unsold at 14:57 is a real defect, not a capacity excuse.
# --- 2026-08-18, account 1000003, QUEUE-mode execution test -----------------
# Read live via miniQMT at 09:56 Beijing. This account holds 1,318 position rows
# of which only 26 are ordinary A-share stocks with a positive can_use, so the
# basket is picked from a short list, not from anything the strategy bought.
#
# These are SLICES of large holdings, never a flatten. The account's stock is
# not ours -- 603171.SH alone shows 2,000,000 shares -- and this script sells
# exactly SELL_TARGETS and no more, which is the whole reason it takes explicit
# share counts instead of "sell everything".
#
#   603171.SH    200  main SH  44.85  can_use 2,000,000
#   600011.SH  2,000  main SH   6.89  can_use    22,190  <- can_use is the binding
#                                                           cap here, not volume
#   688387.SH  1,000  STAR     14.63  can_use   611,751  min lot 200, step 1
#   920047.BJ  1,000  Beijing  17.70  can_use    47,000  min lot 100, step 1
#   920000.BJ    500  Beijing  14.08  can_use     1,900
#   002418.SZ  1,000  main SZ   3.92  can_use     8,100  <- see below
#
# 002418.SZ is a CONTROL, not an expectation. This account could not trade
# Shenzhen on 07-31 or on 08-03 -- 4,617 rejections, all
# [COUNTER][250253][Shenzhen securities account control record missing] with
# p_stock_account=0050900003. Two weeks have passed; one Shenzhen name settles
# whether it still holds, at the cost of a handful of logged rejections and no
# fills. If it goes through, the Shenzhen leg is back.
#
# No Shanghai name here is small enough to flatten, so the odd-lot exception is
# NOT exercised today -- every target is a clean multiple of its board's step.
# --- 2026-08-24, account 1000310, FULL LIQUIDATION -------------------------
# Read live via miniQMT at 08:45 Beijing. Every ordinary A-share this account
# can actually sell, each at its FULL held quantity -- so this is the real
# rebalance shape (sell everything) rather than the slice-of-someone-else's-
# position shape the 08-18 test had to use on 1000003.
#
# That distinction is the whole point today. A trim can never exercise the
# odd-lot exception, because the exchange grants it only to a sale that
# FLATTENS a position; every previous live run was a trim, so the branch has
# only ever been seen refusing (UNSELLABLE ... not being flattened).
#
#   600816.SH  1,024  <-- THE TEST. 1,024 = 10 lots + 24 shares, and the
#                         account holds exactly 1,024. Once 1,000 have gone,
#                         held and remaining are both 24, so the 24 MUST go out
#                         as its own order and fill. If the log instead says
#                         "UNSELLABLE 600816.SH 24 shares left", the flattening
#                         branch is wrong and live rebalancing would strand a
#                         tail on every single name.
#
#   688800.SH 50,000  STAR, 63.56 -- 84% of the basket's value on its own
#   300363.SZ 20,000  ChiNext
#   601398.SH  8,500  main SH
#   600981.SH  5,000  main SH
#   000972.SZ  2,000  main SZ
#   600050.SH  1,300  main SH
#   600283.SH  1,200  main SH
#   600968.SH  1,000  main SH
#   600628.SH    900  main SH
#   000063.SZ    600  main SZ
#   601318.SH    200  main SH
#
# 601336.SH is NOT here: its can_use is <= 0 (a short has eaten the net
# position), so the dual cap would refuse it anyway. It was in the 08-03 basket
# purely to prove that guard fires, and it did.
# SHENZHEN IS BACK IN, 2026-08-28. It was pulled yesterday because the counter
# refused every Shenzhen order on this account with
#   [COUNTER][250253] "Shenzhen shareholder-account control record not found"
#   p_exchange_type=2, p_stock_account=0050900310
# 51 refusals, not one share sold, and a re-login did not clear it. But the same
# code has come and gone before -- 5 refusals on 2026-08-03, none at all on
# 2026-07-31 -- so it is intermittent rather than permanent, and 22,600 shares
# is a quarter of the basket to abandon on an assumption.
#
# If it recurs, the cost is log noise, not money: the orders are refused before
# they reach the market. Pull these three again if the first bars show 250253:
#     "300363.SZ": 20000, "000972.SZ": 2000, "000063.SZ": 600
# --- 2026-08-31 (Mon): the account reset overnight, basket unchanged ---------
# Read live from 1000310 via miniQMT at 06:50 Beijing. Every name is back at
# its FULL Friday-morning quantity -- 688800.SH is 50,000 again, though 44,244
# of it traded on 08-28. The simulation account is restored to a fixed snapshot
# every night, buys and sells both reversed, so the basket below is identical
# to Friday's and today is a clean re-run rather than a continuation.
#
# can_use is exactly 2x volume on all 13 rows. That is the counter defect, not
# a real figure; the dual cap takes min(target, can_use) so it changes nothing.
#
# 601336.SH is held (100 shares, can_use -99) and is again NOT in the basket:
# can_use <= 0 means the dual cap refuses it anyway. It was in the 08-03 run
# only to prove that guard fires, and it did.
#
# Shenzhen (300363, 000972, 000063 = 22,600 shares) stays IN. It was blocked by
# [COUNTER][250253] on 08-27 and 08-28, but the code is intermittent -- 5
# refusals on 08-03, none on 07-31 -- and a refusal costs log noise, not money,
# because it happens before the order reaches the market. Watch the first bars:
# if 250253 shows up again, these three will not sell and that is the reason.
SELL_TARGETS = {
    "600533.SH": 4800,      # Xixia Construction
    "002573.SZ": 3000,      # Sunrise Environmental
    "002133.SZ": 3800,      # Guangyu Group
    "600018.SH": 1900,      # Shanghai Port
    "600232.SH": 1600,      # Jinying
    "603028.SH": 1500,      # Saifutian
    "601886.SH": 1100,      # Jianghe Group
    "300625.SZ": 1000,      # Sanxiong Aurora
    "605577.SH": 1000,      # Longban Media
    "300614.SZ":  900,      # Baichuan Changyin
    "603585.SH":  900,      # Suli
    "688567.SH":  817,      # Farasis Energy      <- STAR, odd tail
    "300583.SZ":  800,      # Saito Bio
    "603282.SH":  600,      # Yaguang
    "003029.SZ":  500,      # Jida Zhengyuan
    "001231.SZ":  500,      # Nongxin Technology
    "688533.SH":  411,      # Shangsheng Electronics <- STAR, odd tail
    "688162.SH":  400,      # Juyi Technology     <- STAR
    "301503.SZ":  400,      # Zhidi Technology
    "688357.SH":  200,      # Jianlong Weina      <- STAR, exactly the minimum
}
# Baskets used earlier, kept for reference:
# 07-31 pm (1000310): {"601398.SH": 2000, "600050.SH": 2000, "000063.SZ": 1000,
#                      "300363.SZ": 1000, "688800.SH": 603, "600283.SH": 1000}
# 07-31 am (1000003): {"601012.SH": 2000, "603888.SH": 2000, "300883.SZ": 2000,
#                      "688001.SH": 1000, "920002.BJ": 500, "688373.SH": 203}
# 07-30    (1000003): {"600004.SH": 1000, "000002.SZ": 1000, "300006.SZ": 1000,
#                      "688538.SH": 1000, "688373.SH": 203, "920018.BJ": 1000}

# Fat-finger guard: refuse to start if any single target exceeds this.
# Raised from 20,000 on 08-03: 688800.SH's real holding is 50,000 and this is a
# full liquidation, so the old ceiling would have refused to start. Still well
# under any quantity this account could reach by accident.
MAX_TARGET_SHARES = 60000

# EDIT: the ONLY account this basket may be sold from. The model-trading GUI
# injects whatever account the strategy is bound to, and until 2026-08-31 this
# script sold from whichever one that was -- there was no check at all, only
# comments saying there should be. On a simulation account that is untidy; on
# a live one it means a mis-click in the binding dropdown liquidates the wrong
# portfolio, and there is no undo.
#
# The basket below is stated in absolute share counts for the same reason, and
# the two guards are independent: the whitelist says WHOSE stock this is, the
# share counts say HOW MUCH of it. Either one alone can be defeated by an
# honest mistake; together they cannot.
#
# Empty tuple = no restriction (the pre-2026-08-31 behaviour). Do not leave it
# empty on a live account.
ALLOWED_ACCOUNTS = ("507085",)

# Window. Must match the backtest, qmt_combo_top20_twap.py line 42:
#     SELL_START, SELL_END = "093000", "145700"
# 14:57, not 14:00 -- 14:00 is the BUY window's end. The sell side deliberately
# runs almost to the close so a name that cannot fill gets the whole day.
SELL_START = "093000"           # never earlier; keeps out of the opening auction
# ------------------------------------------------------------ day structure --
# Four phases, because "slice evenly until 14:57 and hope" left 799 shares
# unsold on 2026-08-18 -- 459 of them cancelled at 14:58 with no bar left to
# re-quote into.
#
#   TWAP     09:30-14:00   schedule as before, at whatever price_mode says
#   RUSH     14:00-14:56   target is now FULL; min-slice dropped and the
#                          participation cap widened, but still price_mode --
#                          this stays passive on purpose, it is a bigger slice,
#                          not a worse price
#   CANCEL   14:56         pull every resting order. Send nothing.
#   AUCTION  14:57-15:00   whatever is left goes in ONCE at the limit-DOWN
#                          price, into the closing call auction
#
# Why the cancel must land at 14:56 and not inside the auction: SSE and SZSE
# (and BSE) run the closing call auction 14:57-15:00 and accept NEW orders only
# -- CANCELLATION IS REFUSED for those three minutes. Cancelling at 14:57 would
# be rejected, the old passive orders would still be live, and the limit-down
# order would stack ON TOP of them. That is a double sell, not a clean-up.
#
# Why limit-down is not "selling at limit-down": a call auction clears every
# matched order at ONE price, set by maximum volume. An order priced at the
# floor says "fill me at whatever the clearing price turns out to be" and
# executes AT THE CLEARING PRICE. The only case it really trades at the floor
# is a stock already sealed limit-down, which could not have been sold anyway.
# THESE THREE ARE WALL-CLOCK, NOT BAR LABELS. QMT stamps a forming bar with
# its CLOSING minute, so the bar labelled 145700 is delivered at about 14:55:58
# Beijing -- measured on 2026-08-24, where every phase ran 1-2 minutes early:
#
#     wall 13:58:58 -> bar 140000      wall 14:54:58 -> bar 145600
#     wall 14:55:58 -> bar 145700
#
# Gating the auction on the bar label therefore fired it at 14:55:58, a full
# minute before the closing auction opens at 14:57. Eight floor-priced sells
# went into the CONTINUOUS session, where a floor-priced limit sell is simply a
# market order, and all eight came back filled AT the floor: 688800.SH sold 222
# shares at 50.85 with the bid at 64.30. 4,017 yuan on a 23,092-yuan slice.
SELL_END = "140000"             # end of the TWAP schedule (was 145700)
RUSH_END = "145400"             # last minute that may send a continuous-session
                                # order; the sweep then has three clear minutes
                                # to settle before the auction
AUCTION_AT = "145700"           # closing auction opens; place the remainder here
PARTICIPATION_RUSH = 0.30       # cap during RUSH. Not unlimited: a thin name
                                # would otherwise take the whole book in one bar.

PARTICIPATION = 0.10            # <= 10% of the previous COMPLETED 1m bar
# Minimum slice, in SHARES. The backtest's sell side gates on shares, not value
# (qmt_combo_top20_twap.py line 270: `if want_sell < 100 and frac < 1.0`).
# MIN_ORDER_AMT = 2000 yuan belongs to the BUY side only -- it appears exactly
# once in the backtest, at line 365, inside _run_buys. Copying it here delayed
# the first sell of a 4,600 yuan position to 11:14 and cut the whole
# liquidation to three orders, which defeats the point of slicing.
# Raised from 100 on 2026-09-02. The 09-01 liquidation sent 363 orders and
# 137 cancels for 26,128 shares -- 500 exchange messages at 0.1 yuan each,
# and an average of 72 shares per order because the slice floor was one
# lot. Two lots roughly halves the message count. The cost is a coarser
# slice and a later start for small positions, which the RUSH phase and
# the closing auction already backstop.
MIN_SELL_SHARES = 200
MAX_SPREAD_BPS = 50.0           # skip the minute when the touch is wider than...
MIN_SPREAD_TICKS = 3            # ...this many bps AND this many ticks. 0 = off.
SPREAD_GUARD_UNTIL = "144500"   # after this, take what is there and finish
STALE_ORDER_MIN = 5             # fallback only: used when the touch is unreadable
# Minimum age, in BAR minutes, before an order may be cancelled at all.
# Bar minutes, not real seconds: this script acts once per bar, so "one bar" is
# the natural unit, and a real-clock version cannot be exercised offline -- the
# regression replays a whole session in a few real seconds, so every order
# looked newborn and nothing was ever cancelled.
CANCEL_MIN_REST_BARS = 1
# Long backstop, in BAR minutes. An order whose touch genuinely has not moved
# keeps its queue slot, but not forever.
CANCEL_BACKSTOP_MIN = 30

# --- un-cancellable ("zombie") orders -------------------------------------
# The counter can refuse a cancel outright, with
#     [COUNTER][251020][order status does not allow cancellation]
# and the order is then left exactly as it was: same status, same unfilled
# remainder, cancel after cancel. It is still "pending" as far as our books are
# concerned, and pending quantity is subtracted from every later slice, so one
# stuck order silently eats its own name's schedule for the rest of the day.
#
# 2026-08-24 measured both sides of this:
#   BUY  25 stuck orders froze 8,341 shares against a 9,151-share shortfall --
#        essentially the entire miss. 600533.SH spent the afternoon on
#        `cur 2100 pend 2400 tgt 4600 -> buy 100`, trickling 100 shares a bar
#        because over half its target was locked in orders that could neither
#        fill nor die. 4,410 of the day's 8,385 counter messages were 251020.
#   SELL the closing-auction slice computed `left = allowed - sold - pend` while
#        pend still held orders the 14:54 sweep had just killed, so 222 shares
#        went into the auction instead of 19,378.
#
# Once an order is judged stuck it is dropped from `pend` and no longer
# cancelled. Dropping it from pend cannot oversell: the exchange has those
# shares frozen, so they are already absent from can_use_volume, and sizing
# from can_use is sizing from what is genuinely free.
#
# Both tests are needed. The count alone would condemn an order merely being
# retried across a slow patch; the elapsed time alone would condemn a resting
# order nobody has tried to cancel yet.
# How many REJECTED fallback orders it takes to conclude that can_use was
# telling the truth after all. See _effective_can_use: a zero there can mean the
# broker's data is wrong (2026-08-26, and the fallback rescues the position) or
# that the shares genuinely cannot be sold -- suspended, pledged, restricted,
# lent out. Nothing in the position row distinguishes those, so instead of
# guessing the reason, send and watch: the exchange refusing three times is the
# answer. Three, not one: a single rejection can be a price band or a transient
# counter state, and giving up on one would strand a sellable position.
CU_FALLBACK_MAX_REJECTS = 3

ZOMBIE_CANCEL_TRIES = 6         # cancels that changed neither status nor remainder
ZOMBIE_MIN_AGE_MIN = 15         # ...spread over at least this many BAR minutes
# Bar minutes, like CANCEL_MIN_REST_BARS and CANCEL_BACKSTOP_MIN, not real
# seconds. A real-clock threshold cannot be exercised offline at all: the
# regression replays a whole session in a few seconds of wall time, so no order
# is ever old enough and the entire branch goes untested. Live, the 5-minute
# real cooldown between cancels already means six tries span half an hour, so
# this is the looser of the two constraints either way.
# Raised from 2 on 2026-07-31. A counterparty-price order only takes what is
# sitting at the touch: a 300-share slice against a 100-share bid fills 100 and
# leaves 200 resting at a price the market has already left behind. That
# remainder counts as `pend` and blocks the next slice, so it has to be
# cancelled -- but at 2 minutes the cycle ran once per order, giving a 100%
# cancel ratio (16 orders, 16 cancels in nine minutes). Exchanges monitor cancel
# ratios and the broker charges per order, so the churn costs both goodwill and
# roughly 13 CNY a day per name. Five minutes cuts it to about 40% of that and
# costs only a slower tail; the backtest has no cancel logic at all, so this
# parameter is not constrained by it.
# How long to wait, in REAL seconds, for an order we sent to appear in the
# broker's ORDER list before treating it as rejected. Deliberately generous:
# a genuine rejection is rare, whereas giving up early re-sends the slice.
# Seconds a session started DURING trading hours must observe before it may
# send anything. Tied to UNCONFIRMED_TIMEOUT_SEC because it answers the same
# question from the other side: that one is how long we wait for the counter to
# acknowledge an order, this is how long a NEW session must wait for the
# counter to tell it about orders it never saw sent.
RESTART_SETTLE_SEC = 95.0
UNCONFIRMED_TIMEOUT_SEC = 90.0
PEND_INVISIBLE_MAX_SEC = 600.0  # an order we sent may stay invisible to the
                                # broker this long and still count as pending;
                                # far longer than UNCONFIRMED_TIMEOUT_SEC, which
                                # answers a different question (keep waiting?)
                                # rather than (do these shares still exist?)

# How long a name may go WITHOUT A SINGLE FILL before it is abandoned, in real
# minutes. The clock resets on any fill, so this measures a dry spell.
#
# This replaces MAX_ORDER_ATTEMPTS, a COUNT of no-fill orders, which was wrong.
# Its comment claimed "twenty attempts is a ~100-minute dry spell", reasoning
# from STALE_ORDER_MIN=5 as if one order went out per cancel cycle. It does not:
# an order goes out EVERY BAR, so 20 attempts is a 20-MINUTE dry spell. On
# 2026-08-03 that abandoned 688800.SH at 09:49 -- try 1 at 09:29, try 20 at
# 09:48 -- with 50,000 of 50,000 shares unsold and five hours of session left,
# in flat contradiction to the rule this script exists to honour: a name that
# cannot be sold keeps being retried until 15:00.
#
# Real minutes, not bar minutes, for the same reason UNCONFIRMED_TIMEOUT_SEC is:
# a suspended PC makes bar time jump and would age this out instantly.
#
# 120 minutes is what the old comment believed it was buying. A name that has
# not filled one share in two hours is genuinely dead (halted, limit-locked, or
# a counter that is refusing it silently) and re-quoting it every minute until
# the close only piles up cancels.
NO_FILL_GIVEUP_MIN = 120.0
# The count-based guard is KEPT, but narrowed to what it was actually built for:
# orders that never reach the book at all. 2026-07-29, 600958.SH was re-ordered
# every minute because each order died without filling AND without resting, so
# cur and pend both stayed 0 and the delta never shrank -- a junk-order loop
# that exchanges penalise. That is a different failure from 688800.SH's, whose
# orders DID rest (pend reached 4,008) and were merely cancelled for age.
#
# So: this counter resets whenever the name has resting quantity, which means
# only a name whose orders vanish can exhaust it. A resting-but-unfilled name is
# retired by NO_FILL_GIVEUP_MIN instead, two hours later.
MAX_ORDER_ATTEMPTS = 20
# Bars a position-vs-fill-record gap must survive before it is called a
# counter contradiction rather than the fill record's one-bar lag.
COUNTER_GAP_BARS = 3
# Minutes to wait before re-trying a name the counter refused with 250253
# (Shenzhen shareholder-account registration). Not zero -- the fault is
# intermittent and we want an intraday recovery -- and not the whole day.
ACCT_REJECT_RETRY_MIN = 10
# How far the bar's own label may sit from the Beijing wall clock before the bar
# is treated as stale and NOT acted on. During live trading QMT stamps the
# forming bar with its closing minute, so the gap is under a minute; anything
# larger means the feed is replaying history (a restart) or the market is shut.
# Three minutes leaves room for a slow bar without letting a lunch-break or
# pre-open bar through.
STALE_BAR_MAX_MIN = 3

# ---------------------------------------------------------------- price mode --
# Two ways to price a sell, switchable WHILE THE SCRIPT RUNS:
#
#   COMPETE  prType 14, counterparty price -> hits the bid. Fills now, pays the
#            half-spread. 2026-08-04 live: 100% filled inside the minute, cost
#            4.8 bp on a 10.37 name and 24.0 bp on a 2.09 one.
#   QUEUE    prType  4, ask-1 price -> posts at the ask and waits. Costs ~0 or
#            better against mid, but may not fill at all.
#
# The mode is read from a one-line text file every bar, so switching needs a
# text editor, not a re-paste. That matters more than convenience: this script
# carries a day of state -- the opening baseline, per-name progress, the
# junk-order budget, every resting order's timestamp -- and all of it is keyed
# on STRATEGY. Running a second script with a different STRATEGY to change the
# price would start that bookkeeping from zero with the position already half
# sold. Same script, same STRATEGY, one continuous log.
PRICE_MODE_FILE = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\price_mode.txt"
# How many numbered instruction files to look for (price_mode1.txt ..).
# Small on purpose: this is a per-bar poll, and every miss is a failed open.
PRICE_MODE_MAX_SEQ = 6
# EDIT: per-name price mode, applied at paste time and independent of
# price_mode.txt. The file channel is the normal way to do this, but in LIVE
# mode it has been unreadable all of 2026-09-01 -- the file predates every
# session -- so without this there is no way to make ONE name cross the spread
# short of changing the default for the whole basket.
#
# Only for a name that is genuinely stuck: crossing costs the half-spread on
# every remaining share, while a passive quote earns it.
#
#     MODE_OVERRIDE = {"002573.SZ": "COMPETE"}
MODE_OVERRIDE = {}
PRICE_MODE_DEFAULT = "QUEUE"    # used until the file is read successfully
PRTYPE_BY_MODE = {"COMPETE": 14, "QUEUE": 4}
# The spread filter INVERTS with the mode, it does not merely relax. It exists
# to avoid crossing a wide touch; QUEUE crosses nothing, so a wide touch is the
# edge being harvested and standing down would be backwards.
MIN_SPREAD_TICKS_BY_MODE = {"COMPETE": 3, "QUEUE": 0}
# A name that has not filled in this long is treated as dead. In QUEUE that is
# the wrong reflex -- waiting hours for a buyer is the strategy, not a failure --
# so the dry spell is effectively disabled there.
NO_FILL_GIVEUP_MIN_BY_MODE = {"COMPETE": 120.0, "QUEUE": 100000.0}


def _price_mode(code=None):
    """Effective mode for one name: its own override, else the file default.

    Per-name, because a single global switch is the wrong granularity. On
    2026-08-24, 688800.SH was filling steadily in QUEUE while 300363.SZ was
    cancelled twenty times without selling a share -- one wanted patience, the
    other wanted to cross the spread, and there was no way to say so.
    """
    if code:
        m = getattr(S, "mode_by_code", None)
        if m and code in m:
            return m[code]
    return getattr(S, "price_mode", PRICE_MODE_DEFAULT)


def _parse_mode_file(txt):
    """(default_mode_or_None, {code: mode}) from PRICE_MODE_FILE.

    Format, hand-editable while the strategy runs:

        COMPETE              <- bare word: the default for every name
        300363.SZ=QUEUE      <- override for one name
        # anything after a hash is a comment

    A malformed line is IGNORED rather than guessed at: this file decides how
    real orders are priced, so a typo must never silently re-price the book.
    """
    default = None
    per = {}
    for raw in (txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" in line:
            code, _, mode = line.partition("=")
            code = code.strip().upper()
            mode = mode.strip().upper()
            if mode in PRTYPE_BY_MODE and "." in code:
                per[code] = mode
            continue
        if line.upper() in PRTYPE_BY_MODE:
            default = line.upper()
    return default, per


def _refresh_price_mode():
    """Poll PRICE_MODE_FILE. Returns the set of names whose EFFECTIVE mode
    changed ("*" stands for the default, i.e. every name without an override).
    Empty set when nothing changed."""
    # FOLLOW THE DIRECTORY THAT ACTUALLY WORKED, then the configured path,
    # then the legacy ones.
    #
    # Every other file this script touches -- the run log, exec, trades, fills,
    # baseline -- is anchored on S.runlog_dir, which is whichever directory the
    # log could actually be opened in. price_mode.txt was the one orphan: a
    # single hard-coded path with no fallback at all.
    #
    # 2026-09-01, the first LIVE session. Three starts in five minutes, and the
    # run log walked one step down its fallback chain each time --
    #     05:29:47  C:\AI_STOCK\...\combo_twap\logs
    #     05:33:59  C:\QMTGTHT\local_run\combo_top20_twap\logs
    #     05:34:48  C:\QMTGTHT\local_run\combo_top20_twap
    # -- while price_mode.txt, having nowhere to fall back to, reported
    # "unreadable" on all three. The same file, the same machine and the same
    # script had been read 13 times without a miss the previous day; the one
    # variable that changed was the strategy running in LIVE mode rather than
    # simulation. Whatever that restriction really is, following the directory
    # that demonstrably works is the answer to it that does not require knowing.
    #
    # Reads only. Nothing here writes, so a wrong guess costs one failed open.
    txt = None
    _from = None
    # NUMBERED FILES FIRST, HIGHEST WINS.
    #
    # Editing price_mode.txt is how this was meant to work and is still the
    # first thing tried. Under the 2026-09-01 LIVE restriction it never
    # succeeds -- the file predates the session -- so the operator needs a way
    # to say something the strategy can actually hear. Creating a NEW file is
    # that way: price_mode1.txt, then price_mode2.txt for the next change.
    #
    # Highest number first because it is the latest instruction. Reading a
    # lower one after a higher exists would replay an order already
    # superseded, which on a pricing switch means quoting the way the operator
    # has just decided NOT to.
    _dirs = []
    _rd = getattr(S, "runlog_dir", None)
    if _rd:
        _dirs.append(_rd)
    for _d in (LOG_DIR, LEGACY_ROOT, LEGACY_LOGS):
        if _d not in _dirs:
            _dirs.append(_d)
    _cands = []
    for _n in range(PRICE_MODE_MAX_SEQ, 0, -1):
        for _d in _dirs:
            _cands.append(_d + "\\price_mode%d.txt" % _n)
    for _d in _dirs:
        _cands.append(_d + "\\price_mode.txt")
    if PRICE_MODE_FILE not in _cands:
        _cands.append(PRICE_MODE_FILE)
    for _p in _cands:
        try:
            f = open(_p, "r")
            txt = f.read()
            f.close()
            _from = _p
            break
        except Exception:
            continue                # unreadable -> try the next one
    if txt is not None and _from != getattr(S, "mode_file_said", None):
        S.mode_file_said = _from
        log("  price mode file -> %s" % _from)
    default, per = _parse_mode_file(txt) if txt is not None else (None, None)

    first = getattr(S, "price_mode", None) is None
    if first:
        S.price_mode = default or PRICE_MODE_DEFAULT
        S.mode_by_code = dict(per or {})
        # The paste-time override wins over the file: it is the more recent
        # instruction, and on a day when the file cannot be read at all it is
        # the ONLY one that arrives.
        S.mode_by_code.update(MODE_OVERRIDE)
        if MODE_OVERRIDE:
            log("  MODE_OVERRIDE in effect: %s"
                % ", ".join("%s=%s" % kv for kv in sorted(MODE_OVERRIDE.items())))
        log("  PRICE MODE: %s (prType %d)%s%s"
            % (S.price_mode, PRTYPE_BY_MODE[S.price_mode],
               "" if txt is not None else " -- mode file unreadable, using the default",
               (" | per-name: " + ", ".join("%s=%s" % kv
                                            for kv in sorted(S.mode_by_code.items())))
               if S.mode_by_code else ""))
        return set()
    if txt is None:
        return set()

    old_default = S.price_mode
    old_per = dict(getattr(S, "mode_by_code", {}) or {})
    new_default = default or old_default
    new_per = dict(per or {})

    changed = set()
    if new_default != old_default:
        changed.add("*")
    for c in set(old_per) | set(new_per):
        before = old_per.get(c, old_default)
        after = new_per.get(c, new_default)
        if before != after:
            changed.add(c)
    if not changed:
        return set()
    S.price_mode = new_default
    S.mode_by_code = new_per
    for c in sorted(changed):
        if c == "*":
            log("  PRICE MODE default: %s -> %s (prType %d -> %d)"
                % (old_default, new_default,
                   PRTYPE_BY_MODE[old_default], PRTYPE_BY_MODE[new_default]))
        else:
            log("  PRICE MODE %s: %s -> %s"
                % (c, old_per.get(c, old_default), new_per.get(c, new_default)))
    return changed


PRTYPE_COMPETE = 14             # fun.xml: 14 = counterparty price (NOT 44; that
                                # is miniQMT's constant for the same thing)
TERMINAL_STATUS = (53, 54, 56, 57)   # 53 part-cancelled counts as terminal
# Cancel already accepted and in flight: 51 reported-cancelling, 52 part-filled
# -cancelling. Still pending (the remainder may return) but must NOT be
# re-cancelled -- see _pending_and_cancel.
CANCEL_PENDING_STATUS = (51, 52)
# Statuses the exchange will accept a cancellation for: 50 reported,
# 55 part-filled. NOT 48 (not reported) or 49 (waiting to be reported) --
# those are still inside the counter, and asking to cancel one comes back
# as [COUNTER][251020][order status does not allow cancellation].
CANCELLABLE_STATUS = (50, 55)
STRATEGY = "combo_sell_dual"
VOL_LOT_TO_SHARES = 100         # 1m bar volume is in LOTS, orders are in SHARES
TICK = 0.01

LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"
# The pre-2026-08-29 home of these files, kept ONLY as somewhere to look.
# A restart part-way through a day whose files were written before the move
# to C:\\AI_STOCK still has to find them, or it re-sells what it sold.
LEGACY_LOGS = "C:\\QMTGTHT\\local_run\\combo_top20_twap\\logs"
LEGACY_ROOT = "C:\\QMTGTHT\\local_run\\combo_top20_twap"
DEBUG_DUMP_FIELDS = False       # True = dump every m_* field of the first row


class _S(object):
    pass


S = _S()
print("MODULE combo_sell_close imported OK")


# ------------------------------------------------------------------ logging --
def log(msg):
    """Print to the QMT console AND append to the run log, flushed each line.

    Flushing every line matters: the interesting case is inspecting the file
    while the strategy is still running, and a buffered handle would show
    nothing until it closed.
    """
    line = "[" + _china_now() + "] " + str(msg)
    print(line)
    if S.runlog is False:
        return
    # Roll the file when the exchange date changes. CLOSE_UNTIL lets a run span
    # more than one day, and naming the file after the CLOSE_DATE constant --
    # which is hand-edited and easily stale -- would pile several trading days
    # into one file and label them all with a date that may not even be today's.
    if S.runlog is not None and S.runlog_day != _today_str():
        try:
            S.runlog.flush()
            S.runlog.close()
        except Exception:
            pass
        S.runlog = None
    if S.runlog is None:
        _day = _today_str()
        f, _p, _d = _open_varying(
            (LOG_DIR, LEGACY_LOGS, LEGACY_ROOT, "C:\\Users\\Public\\Documents"),
            "run_" + STRATEGY + "_" + _acct_tag() + "_" + _day, ".log", "a")
        if f is not None:
            f.write("=== session start " + _china_now() + " ===\n")
            f.flush()
            S.runlog = f
            S.runlog_day = _day
            S.runlog_dir = _d
            S.runlog_path = _p
            print("  run log -> " + _p)
        if S.runlog is None:
            S.runlog = False
            print("  NOTE: no writable log directory; console only")
            return
    try:
        S.runlog.write(line + "\n")
        S.runlog.flush()
    except Exception:
        S.runlog = False


def _log_trade(bar_time, code, qty, remark):
    if S.tradelog is False:
        return
    if S.tradelog is not None and S.tradelog_day != _today_str():
        try:
            S.tradelog.flush()
            S.tradelog.close()
        except Exception:
            pass
        S.tradelog = None
    if S.tradelog is None:
        # Retry cooldown + directory fallback, both learned from the buy script
        # on 2026-08-04: QMT's sandbox refused an open() with its own
        # PermissionError('Foribdden FileIO'), and the old code latched the log
        # off for the rest of the day on that single failure. The block was
        # intermittent -- other handles in the same directory kept writing all
        # day -- so one refusal must not be permanent. This file is what a
        # restart reads to learn what today already sold; losing it is not
        # cosmetic.
        if S.tradelog_retry is not None and (
                dt.datetime.utcnow() - S.tradelog_retry).total_seconds() < 60.0:
            return
        S.tradelog_retry = dt.datetime.utcnow()
        # NOT TRADE_LOG_DIR -- that constant belongs to the BUY script. Naming it
        # here compiled fine and then raised NameError on the first order of the
        # 2026-08-18 session, killing _run_sells every bar. py_compile cannot see
        # this; only running the module does.
        for _d in ((getattr(S, "runlog_dir", None) or LOG_DIR),
                   LEGACY_LOGS, LEGACY_ROOT,
                   "C:\\Users\\Public\\Documents"):
            try:
                f, _p, _ignored = _open_varying(
                    (_d,), "trades_" + STRATEGY + "_" + _acct_tag()
                    + "_" + _today_str(), ".csv", "a")
                if f is None:
                    continue
                if f.tell() == 0:
                    f.write("date,time,code,shares,remark\n")
                f.flush()
                S.tradelog = f
                S.tradelog_day = _today_str()
                S.tradelog_path = _p
                break
            except Exception:
                continue
        if S.tradelog is None:
            return                      # try again after the cooldown
    try:
        # _today_str(), NOT CLOSE_DATE. CLOSE_DATE is hand-edited, so stamping
        # rows with it lets a stale constant mislabel a whole session -- the
        # exact failure the per-day filenames already guard against.
        S.tradelog.write("%s,%s,%s,%d,%s\n"
                         % (_today_str(), bar_time, code, int(qty), remark))
        S.tradelog.flush()
    except Exception as e:
        log("  trade CSV write failed, will reopen: " + repr(e))
        try:
            S.tradelog.close()
        except Exception:
            pass
        S.tradelog = None


def _dump_obj(label, o):
    names = [a for a in dir(o) if a.startswith("m_")]
    parts = []
    for a in sorted(names):
        try:
            v = getattr(o, a)
        except Exception:
            continue
        if not callable(v):
            parts.append("%s=%r" % (a, v))
    log("  " + label + ": " + ", ".join(parts))


# ------------------------------------------------------------- lot / time ----
def _min_lot(code):
    """Smallest order the exchange will accept."""
    if code.startswith("688"):
        return 200                      # STAR market
    return 100                          # main board / ChiNext / BJ


def _lot_step(code):
    """Share increment above the minimum.

    BJ is matched on the .BJ suffix, not on the leading digit. The old test
    `code[0] in ("4", "8")` covered 43xxxx/83xxxx/87xxxx/88xxxx but missed the
    newer 920xxx range, which then got a 100-share step. That is still legal --
    a multiple of 100 is a valid BJ order -- but it rounds every slice down and
    can strand a remainder that is too small to sell on its own.
    """
    if code.startswith("688"):
        return 1                        # STAR: 200 minimum, 1-share increments
    if code.endswith(".BJ"):
        return 1                        # BJ: 100 minimum, 1-share increments
    return 100                          # main board and ChiNext


def _restore_artifact(code, v, cu, yest):
    """True if can_use has the exact shape the overnight restore leaves behind.

    Measured 2026-08-31 pre-open on 1000310, all thirteen rows:

        can_use == volume + lot_floor(yesterday_volume)

    600816.SH is the case that identifies it rather than merely fitting it:
    1024 shares held, can_use 2024, NOT 2048. The added term is rounded down
    to whole lots, which is a SELLABLE-quantity calculation -- so the counter
    computes "what may be sold from yesterday" correctly and then adds it to
    the position instead of using it on its own. The same batch of shares,
    counted twice.

    Three bonds the restore never touched (009908.SH, 112285.SH, 110075.SZ)
    reported can_use == volume on the same query, in the same minute, on the
    same account. That is what rules out an account-level setting or a
    misread field: only the rows the restore wrote are doubled.

    Recognising it is worth a function because the alternative is what we had
    -- twelve identical '!! ALERT ... clamped to the position' lines every
    morning, which is a known artifact wearing the costume of a surprise. The
    handling does not change (the caller still clamps to the position); only
    how loudly it is reported.

    Both roundings are accepted. Only a main-board name with an odd tail can
    tell them apart, and on 08-31 that was 600816.SH alone; asserting the
    per-board step for STAR and BJ would be guessing from one observation.
    """
    # THE BASIS IS THE OPENING HOLDING, NOT THE LIVE yesterday_volume.
    #
    # The first version of this test compared against `yest` and worked only
    # until the first fill. The counter decrements m_nYesterdayVolume as the
    # position is sold -- it is selling yesterday's shares, after all -- and it
    # decrements can_use by the same amount, so both sides fall together and
    # `cu == v + yest` stops holding. Measured 2026-08-31 13:08, twelve names
    # at once, every one of them reported as an unexplained excess:
    #
    #     688800.SH  can_use 64722  position 14722   64722-14722 = 50000
    #     601398.SH  can_use 11100  position  2600   11100- 2600 =  8500
    #     600816.SH  can_use  1324  position   324    1324-  324 =  1000
    #
    # The right invariant is the DIFFERENCE, and it is constant all day:
    #
    #     can_use - position == lot_floor(holding at the open)
    #
    # 600816.SH identifies it as before: 1000, not 1024. Twelve of twelve fit.
    # At pre-open the position still equals the opening holding, so this also
    # reproduces the 09:30 reading the first version was built from -- one
    # formula for the whole session instead of one that decays after the first
    # fill.
    #
    # S.baseline is the opening snapshot and is reloaded from disk on restart,
    # so this survives the re-pastes that `yest` did not. If it is missing the
    # test fails closed and the generic alert fires, which is the old behaviour.
    _open = int((S.baseline or {}).get(code, 0) or 0)
    if _open <= 0:
        return False
    step = _lot_step(code)
    _diff = cu - v
    return _diff in (_open, (_open // 100) * 100, (_open // step) * step)


def _round_sell(code, qty, remaining, held):
    """Round a desired slice down to a legal size.

    A partial sell must be a whole multiple of the step. The exception is the
    final scrap: an odd lot below the minimum order may be sold, but only in one
    go AND only when it liquidates the position. 688058.SH holding exactly 203
    goes out as 200 then 3.

    `held` is what the account actually owns, and it is the whole point of this
    argument. The exchange grants the odd-lot exception for flattening a
    position, not for trimming one. Judging it on our own target remainder would
    send a 3-share order on a STAR name while millions of shares remain in the
    account -- a guaranteed junk order, repeated until MAX_ORDER_ATTEMPTS ran
    out. Our own 203-share holding still works: after 200 go out, held and
    remaining are both 3.
    """
    qty = int(qty)
    if qty <= 0 or remaining <= 0:
        return 0
    if remaining < _min_lot(code):
        if held <= remaining and qty >= remaining:
            return remaining        # flattening: odd lot allowed
        return 0                    # trimming: exchange would reject it
    st = _lot_step(code)
    qty = (qty // st) * st
    if qty > remaining:
        qty = (remaining // st) * st
    return qty if qty >= _min_lot(code) else 0


def _sess_min(hhmmss):
    """Minutes into the continuous session. 09:30 -> 0, 11:30/13:00 -> 120."""
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    if t <= 690:
        return min(120, max(0, t - 570))
    return min(240, 120 + max(0, t - 780))


def _bar_datetime(C):
    """Exchange date/time from the BAR, never the PC clock.

    This machine runs US Eastern, so the wall-clock date is a day off for most
    of the Beijing session.
    """
    timetag = C.get_bar_timetag(C.barpos)
    china = dt.datetime.utcfromtimestamp(timetag / 1000.0) + dt.timedelta(hours=8)
    return china.strftime("%Y%m%d"), china.strftime("%H%M%S")


def _china_now():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _wall_hhmmss():
    """Beijing wall clock as HHMMSS -- the real time, not the bar label.

    Phase boundaries near the close must use this. A bar label is stamped with
    the minute the bar CLOSES, so it runs 1-2 minutes ahead of the wall clock,
    and gating the closing auction on it sent the orders before the auction
    opened. Everything that is a *schedule* position (how far through the TWAP
    we are) still uses bar time, which is the right clock for that.

    S.wall_override exists so the offline regression can exercise this at all.
    A whole session replays in a few real seconds, so the true clock reads
    02:30 and no end-of-day phase would ever be reached -- the same blindness
    that kept CANCEL_MIN_REST_BARS on bar minutes. The harness feeds the bar
    label minus the measured two-minute lead, which is what the terminal
    actually does, so the test sees the real relationship rather than a fiction.
    It is never set in live trading.
    """
    ov = getattr(S, "wall_override", None)
    if ov:
        return ov
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%H%M%S")


def _zombie(remark, status, left, now_m):
    """True when this order has refused every cancel we have sent it.

    Called from the order scan, which is the only place that sees the order's
    CURRENT (status, left). The signature recorded when we last sent a cancel
    is compared against it: if either has moved, the order is alive -- a fill
    landed, or the cancel took -- so the counter resets and a name that was
    written off comes back.

    See ZOMBIE_CANCEL_TRIES for what this is defending against.
    """
    moved = S.cx_sig.get(remark) != (status, left)
    if moved:
        S.cx_tries[remark] = 0
        S.cx_first.pop(remark, None)
        if remark in S.zombies:
            S.zombies.discard(remark)
            log("  ZOMBIE CLEARED %s: status/remainder moved, back in the book"
                % remark)
        return False
    if remark in S.zombies:
        return True
    if S.cx_tries.get(remark, 0) < ZOMBIE_CANCEL_TRIES:
        return False
    t0 = S.cx_first.get(remark)
    if t0 is None or (now_m - t0) < ZOMBIE_MIN_AGE_MIN:
        return False
    S.zombies.add(remark)
    log("  ZOMBIE %s: %d cancels over %d min changed nothing (status %d,"
        " %d shares stuck). Dropping it from pend and leaving it alone."
        % (remark, S.cx_tries.get(remark, 0), now_m - t0, status, left))
    return True


def _today_str():
    """The EXCHANGE date, for naming per-day files.

    The LATER of the Beijing wall clock and the bar date -- never either alone.

    Bar date alone is wrong BEFORE THE OPEN, when the newest completed bar still
    belongs to the previous session; the buy script hit exactly that on
    2026-08-03 and appended its start-up lines to the 07-31 log. Wall clock
    alone is wrong if this PC's timezone is off (it runs US Eastern, so every
    date here is utcnow()+8h). Taking the later of the two is right both ways.

    Never CLOSE_DATE: that is a hand-edited constant, so a stale value would
    name today's file after some earlier day and merge the two.
    """
    wall = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
    d = getattr(S, "today_str", "")
    bar = d[:8] if (d and len(d) >= 8) else ""
    return bar if bar > wall else wall


def _session_tag():
    """HHMMSS of this session's start, used to make a filename unique."""
    t = getattr(S, "session_tag", None)
    if not t:
        t = _china_now()[11:].replace(":", "")
        S.session_tag = t
    return t


def _open_varying(dirs, prefix, ext, mode):
    """Open prefix+ext in the first directory that will take it.

    Tries the plain name first, so an ordinary day still keeps one file per
    day, then a session-tagged name IN THE SAME DIRECTORY, and only then the
    next directory.

    The old order was directories only, which answered the wrong question. On
    2026-09-01 four LIVE starts produced four logs in four different places --
    the last one in C:\\Users\\Public\\Documents -- because each new session
    could not re-open the previous session's file. The directory was always
    writable; the existing FILE was what could not be opened. Varying the name
    keeps a restart's records next to the ones it is continuing.

    Returns (handle, path, dir), or (None, None, None).
    """
    for d in dirs:
        for name in (prefix + ext, prefix + "_" + _session_tag() + ext):
            try:
                p = d + "\\" + name
                return open(p, mode), p, d
            except Exception:
                continue
    return None, None, None


def _acct_tag():
    """Filename suffix so per-account records never leak between accounts.

    The buy script has had this since 2026-07-31; the sell script did not, so
    all three of its files were keyed on the DATE alone. Running the same day
    against two accounts -- exactly what switching away from 1000310 means --
    would have appended both books to one run log, one trade CSV and one exec
    CSV, with nothing in the rows to say which account each line came from.
    That is the same failure as naming files after a stale CLOSE_DATE, just on
    the other axis.
    """
    a = str(getattr(S, "acct", "") or "noacct")
    return "".join(ch for ch in a if ch.isalnum()) or "noacct"


def _prev_min(hhmmss):
    """Label of the previous minute, hopping the 11:30-13:00 lunch gap."""
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4]) - 1
    if 11 * 60 + 30 < t < 13 * 60:
        t = 11 * 60 + 30
    return "%02d%02d00" % (t // 60, t % 60)


# ---------------------------------------------------------------- market -----
def _quote(C, code, today, hhmmss):
    try:
        data = C.get_market_data_ex(
            ["open", "high", "low", "close", "volume", "preclose"],
            [code], period="1m", start_time=today + hhmmss,
            end_time=today + hhmmss, fill_data=False)
        frame = data.get(code)
        if frame is None or len(frame) == 0:
            return None
        return frame.iloc[-1]
    except Exception:
        return None


def _bar(C, code, today, hhmmss):
    """The last COMPLETED 1m bar.

    QMT stamps a forming bar with its closing minute, so the bar labelled with
    the current minute is still filling and reads volume 0. Using it throttled
    the buy script's participation cap to a few seconds of trading.
    """
    q = _quote(C, code, today, _prev_min(hhmmss))
    if q is not None and q["close"] > 0 and q["volume"] > 0:
        return q
    return None


def _limit_down(C, code, q):
    if code in S.dn_cache:
        return S.dn_cache[code]
    dn = None
    try:
        d = C.get_instrument_detail(code) or {}
        dn = d.get("DownStopPrice")
    except Exception:
        dn = None
    if not dn:
        try:
            pc = float(q["preclose"])
            # BEIJING WAS MISSING. The old line was
            #     0.20 if (300/301/688) else 0.10
            # so every .BJ name fell into the 10% branch while its real band is
            # 30%. On a 10.00 preclose that puts the computed floor at 9.00
            # instead of 7.00, and the caller's test is `high <= floor` -- so
            # ANY Beijing name down more than 10% on the day was read as "sealed
            # limit-down" and skipped on every bar, all day, while it was in fact
            # perfectly sellable. Past baskets held 920018.BJ and 920002.BJ.
            #
            # Deliberately WIDE (no ST narrowing): this is the fallback used only
            # when the broker's DownStopPrice is unavailable, and DownStopPrice
            # already knows about ST. A too-wide floor means we never think a
            # name is sealed, so we keep trying -- the safe direction for a
            # script whose job is to get out. A too-narrow one stops us selling.
            if code.endswith(".BJ"):
                rate = 0.30
            elif code[:3] in ("300", "301") or code.startswith("688"):
                rate = 0.20
            else:
                rate = 0.10
            dn = round(round(pc * (1 - rate) / TICK) * TICK, 2)
            log("  NOTE %s: broker gave no DownStopPrice, using computed %.2f"
                " (band %.0f%%)" % (code, dn, rate * 100))
        except Exception:
            dn = None
    if dn is None and code not in S.dn_said:
        S.dn_said.add(code)
        log("  WARN %s: no limit-down price available -- the limit-down guard is"
            " OFF for this name (it will keep trying, which is the safe side)"
            % code)
    # CACHE THE SUCCESS, NEVER THE FAILURE.
    #
    # This used to write dn unconditionally, so a single early miss was
    # remembered for the whole session: every later call took the fast path at
    # the top and returned None without re-asking, long after the data had
    # arrived. 2026-08-31, the closing auction:
    #     AUCTION skip 000972.SZ: no limit-down price available
    #     AUCTION skip 300363.SZ: no limit-down price available
    # while 000063.SZ, the same board and the same query one line earlier, got
    # its floor. The only difference was whether the FIRST call of the day
    # happened to land on a bar with a usable preclose -- these names are
    # refused by the counter all day, so their bars are frequently empty.
    #
    # A limit price does not change during a session, so caching a real one is
    # right. Caching its absence turns one bad minute into a whole lost day.
    if dn is not None:
        S.dn_cache[code] = dn
    return dn


def _limit_up_px(C, code, q):
    """The day's legal ceiling, or None. Mirror of _limit_down.

    Fallback direction: WIDE, the same as the floor and for the same shape of
    reason. A ceiling computed too LOW would make an open book look sealed and
    send a limit SELL at a price the market never reached -- selling below the
    market is the one error this script must never make. Too high merely means
    we fail to recognise a seal and keep quoting normally, which is exactly
    today's behaviour.
    """
    if code in S.up_cache:
        return S.up_cache[code]
    up = None
    try:
        d = C.get_instrument_detail(code) or {}
        up = d.get("UpStopPrice")
    except Exception:
        up = None
    if not up:
        try:
            pc = float(q["preclose"])
            if code.endswith(".BJ"):
                rate = 0.30
            elif code[:3] in ("300", "301") or code.startswith("688"):
                rate = 0.20
            else:
                rate = 0.10
            up = round(round(pc * (1 + rate) / TICK) * TICK, 2)
        except Exception:
            up = None
    # CACHE THE SUCCESS, NEVER THE FAILURE.
    #
    # This used to write up unconditionally, so a single early miss was
    # remembered for the whole session: every later call took the fast path at
    # the top and returned None without re-asking, long after the data had
    # arrived. 2026-08-31, the closing auction:
    #     AUCTION skip 000972.SZ: no limit-down price available
    #     AUCTION skip 300363.SZ: no limit-down price available
    # while 000063.SZ, the same board and the same query one line earlier, got
    # its floor. The only difference was whether the FIRST call of the day
    # happened to land on a bar with a usable preclose -- these names are
    # refused by the counter all day, so their bars are frequently empty.
    #
    # A limit price does not change during a session, so caching a real one is
    # right. Caching its absence turns one bad minute into a whole lost day.
    if up is not None:
        S.up_cache[code] = up
    return up


def _sealed_up_sell(C, code, q):
    """Is the OFFER side empty with bids parked on the ceiling? -> (bool, px).

    The mirror of the limit-down guard, and the mirror of the gap found on the
    buy side on 2026-08-31. A name sealed limit-UP is trivially SELLABLE -- the
    bid queue at the ceiling is enormous -- but QUEUE prices a sell at ASK-1
    and a sealed board has no ask to quote at. So the easiest sale of the day
    is the one the pricing mode cannot ask for.

    Both conditions required. No ask alone is also what a halt looks like, and
    a halted name cannot be sold at any price; bids at the ceiling alone can
    happen on an open book that is merely up a lot.
    """
    up = _limit_up_px(C, code, q)
    if not up:
        return False, None
    bid, ask, got = _touch_raw(C, code)
    if not got or ask > 0 or bid <= 0:
        return False, None
    if bid >= up - TICK / 2:
        return True, up
    return False, None


def _first_level(v):
    """Level-1 price out of either a depth list or a bare scalar."""
    try:
        if isinstance(v, (list, tuple)):
            return float(v[0]) if v else 0.0
        return float(v or 0)
    except Exception:
        return 0.0


def _bar_price(C, code, today, hhmmss):
    """Close of the last completed bar, or 0. Reference price for slippage."""
    try:
        q = _bar(C, code, today, hhmmss)
        return float(q["close"]) if q is not None else 0.0
    except Exception:
        return 0.0


def _exec_write(row):
    """One line per completed order into the execution-quality CSV.

    The slippage number in the backtest is an ASSUMPTION (half a tick, then a
    whole tick), not a measurement -- and it omits market impact entirely. This
    file is what replaces the assumption with data: for every order it records
    the touch as it stood when the decision was made and the price actually
    obtained, so slippage in bps can be computed after the fact rather than
    guessed.
    """
    if S.execfh is False:
        return
    if S.execfh is not None and S.execfh_day != _today_str():
        try:
            S.execfh.flush()
            S.execfh.close()
        except Exception:
            pass
        S.execfh = None
    if S.execfh is None:
        d = (getattr(S, "runlog_dir", None) or LOG_DIR)
        try:
            fh, _xp, _xd = _open_varying(
                (d,), "exec_" + STRATEGY + "_" + _acct_tag()
                + "_" + _today_str(), ".csv", "a")
            if fh is None:
                raise IOError("no writable exec path")
            if fh.tell() == 0:
                fh.write("date,t_place,t_done,code,side,qty_sent,qty_filled,"
                         "price_filled,bid1,ask1,mid,bar_close,"
                         "slip_vs_mid_bp,slip_vs_close_bp,spread_bp,status,"
                         "price_mode\n")
            fh.flush()
            S.execfh = fh
            S.execfh_day = _today_str()
        except Exception as e:
            S.execfh = False
            log("  exec CSV unavailable: " + repr(e))
            return
    try:
        S.execfh.write(row + "\n")
        S.execfh.flush()
    except Exception:
        S.execfh = False


def _exec_close(o, remark, hhmmss):
    """Record an order whose fate is now known. Called once per order."""
    rec = S.exec_open.pop(remark, None)
    if rec is None:
        # AN ORDER THIS PROCESS NEVER SAW SENT.
        #
        # After a restart S.exec_open is empty, so anything placed before it
        # and filled after arrives here with no record. Returning silently
        # dropped it from the exec CSV entirely: on 2026-09-01 the account
        # finished flat at 26,128 shares while the file accounted for 21,782,
        # the 4,346 difference being six restarts' worth of in-flight orders.
        #
        # On an account with no miniQMT these files ARE the record -- there is
        # nothing to reconcile against afterwards -- so a restart must not be
        # able to delete part of the day from them.
        #
        # Write what the broker's row actually says. The touch at send time is
        # unknown for an order we did not send, so the slippage columns are
        # left EMPTY rather than filled with a guess: a blank says "not
        # measured", a fabricated number would say something false.
        _ofilled = int(getattr(o, "m_nVolumeTraded", 0) or 0)
        if _ofilled <= 0:
            return                      # nothing traded: nothing to record
        if remark in S.exec_orphans:
            return                      # the counter re-serves terminal rows
        S.exec_orphans.add(remark)
        try:
            _opx = float(getattr(o, "m_dTradedPrice", 0) or 0)
            _ocode = (getattr(o, "m_strInstrumentID", "") + "."
                      + getattr(o, "m_strExchangeID", ""))
            _ost = int(getattr(o, "m_nOrderStatus", 0) or 0)
            _osent = int(getattr(o, "m_nVolumeTotalOriginal", 0) or 0)
            if _opx > 0:
                _acc = S.fill_px.setdefault(_ocode, [0, 0.0])
                _acc[0] += _ofilled
                _acc[1] += _ofilled * _opx
            _fill_append(_today_str(), _ocode, _ofilled, remark)
            _exec_write(",".join([
                _today_str(), "", hhmmss or "", _ocode, "sell",
                str(_osent), str(_ofilled),
                ("%.4f" % _opx) if _opx > 0 else "",
                "", "", "", "",             # bid1, ask1, mid, bar_close
                "", "", "",                 # the three slippage columns
                str(_ost), "adopted"]))
        except Exception:
            pass
        return
    try:
        filled = int(getattr(o, "m_nVolumeTraded", 0) or 0)
        px = float(getattr(o, "m_dTradedPrice", 0) or 0)
        st = int(getattr(o, "m_nOrderStatus", 0) or 0)
        # Quantity-weighted achieved price, for the closing summary. The exec
        # CSV already scores every fill against the touch it was sent into,
        # which measures the ORDER. It cannot say whether the DAY was well
        # traded -- a schedule that does the whole basket in the worst hour
        # beats the touch on every fill and still does badly. The average is
        # what gets compared against the session VWAP afterwards.
        # _exec_close runs once per order, so this cannot double-count.
        if filled > 0 and px > 0:
            _acc = S.fill_px.setdefault(rec.get("code") or "", [0, 0.0])
            _acc[0] += filled
            _acc[1] += filled * px
        # 57 = rejected. Counted here rather than at the rejection log, because
        # this is where the order's own record is still in hand and can say
        # whether the can_use fallback sized it.
        # ...and only for a refusal that is ABOUT availability. The fallback is
        # a bet that can_use was wrong; only the counter answering "you do not
        # have that many" settles that bet. 2026-08-27 counted everything and
        # got it backwards twice over: 688800.SH reached 2 of 3 on two "order
        # price out of range" refusals while it was selling perfectly well, and
        # the Shenzhen names burned their count on [250253], an account
        # registration fault that says nothing about any single holding.
        # [251005] is the quantity message on this counter.
        _why57 = getattr(o, "m_strCancelInfo", "") or ""
        _about_qty = ("251005" in _why57
                      or "insufficient" in _why57.lower())
        if st == 57 and rec.get("fb") and filled <= 0 and _about_qty:
            _c = rec["code"]
            S.cu_fb_rejects[_c] = S.cu_fb_rejects.get(_c, 0) + 1
            n = S.cu_fb_rejects[_c]
            if n >= CU_FALLBACK_MAX_REJECTS and _c not in S.cu_fb_off:
                S.cu_fb_off.add(_c)
                S.cu_fb_on.discard(_c)
                _cu_alert(_c, "the exchange rejected %d fallback orders in a"
                              " row, so can_use 0 was correct after all --"
                              " these shares cannot be sold today (suspended,"
                              " pledged, restricted or lent). Fallback OFF for"
                              " %s; the position WILL BE CARRIED." % (n, _c),
                          "fbreject")
            else:
                log("  fallback order rejected for %s (%d/%d before it is"
                    " switched off)" % (_c, n, CU_FALLBACK_MAX_REJECTS))
        bid, ask, bar = rec["bid"], rec["ask"], rec["bar"]
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
        # Selling below the reference costs us, so the sign is (ref - fill).
        smid = ((mid - px) / mid * 1e4) if (mid > 0 and px > 0) else ""
        sclose = ((bar - px) / bar * 1e4) if (bar > 0 and px > 0) else ""
        spread = ((ask - bid) / mid * 1e4) if mid > 0 else ""
        _exec_write("%s,%s,%s,%s,%s,%d,%d,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s" % (
            _today_str(), rec["t"], hhmmss, rec["code"], rec["side"],
            rec["qty"], filled,
            ("%.4f" % px) if px else "", ("%.4f" % bid) if bid else "",
            ("%.4f" % ask) if ask else "", ("%.4f" % mid) if mid else "",
            ("%.4f" % bar) if bar else "",
            ("%.2f" % smid) if smid != "" else "",
            ("%.2f" % sclose) if sclose != "" else "",
            ("%.2f" % spread) if spread != "" else "", st,
            rec.get("mode", "")))
        # DURABLE FILL RECORD -- see _fills_from_disk.
        if filled > 0:
            _fill_append(_today_str(), rec["code"], filled, remark)
    except Exception as e:
        log("  exec record failed: " + repr(e))


def _fills_handle(day):
    """The open handle for today's fill record, or False if it is unusable.

    ONE handle for the day, exactly as the exec and trades records do. Opening
    and closing per record is what broke this on 2026-09-01: the sandbox
    accepts the open that CREATES a file and refuses every open of one that
    already exists, so per-record opens work once and then never again.
    """
    if getattr(S, "fillfh", None) is False:
        return False
    if getattr(S, "fillfh", None) is not None and S.fillfh_day != day:
        try:
            S.fillfh.flush()
            S.fillfh.close()
        except Exception:
            pass
        S.fillfh = None
    if getattr(S, "fillfh", None) is None:
        d = (getattr(S, "runlog_dir", None) or LOG_DIR)
        base = "fills_" + STRATEGY + "_" + _acct_tag() + "_" + day
        fh, p, _fd = _open_varying((d,), base, ".csv", "a")
        if fh is None:
            S.fillfh = False
            S.fills_path = d + "\\" + base + ".csv"
            log("  fill record unavailable: no writable path under "
                + d + " -- the durable per-fill record is OFF for today."
                " ours is still rebuilt from the order list, so the"
                " cross-check keeps all three sources.")
            return False
        try:
            if fh.tell() == 0:
                fh.write("code,filled,remark" + chr(10))
            fh.flush()
        except Exception:
            pass
        S.fillfh = fh
        S.fillfh_day = day
        S.fills_path = p
        S.fills_path_day = day
    return S.fillfh


def _fills_path(day):
    """Where the fill record IS -- it does not open anything.

    An earlier version opened the file here just to discover which name would
    take it, then closed it. That created the file, so the appender's own open
    was then refused as pre-existing and the record stayed at zero bytes all
    morning. Acquiring the handle is _fills_handle's job; this only reports.
    """
    p = getattr(S, "fills_path", None)
    if p and getattr(S, "fills_path_day", None) == day:
        return p
    d = (getattr(S, "runlog_dir", None) or LOG_DIR)
    return d + "\\fills_" + STRATEGY + "_" + _acct_tag() + "_" + day + ".csv"


def _fill_append(day, code, filled, remark):
    """One line per order that actually traded. Called from _exec_close, which
    has already popped the order out of S.exec_open, so each is written once.

    No os.path: this module never imports os. Append mode creates the file when
    it is missing and tell() distinguishes a fresh one.
    """
    fh = _fills_handle(day)
    if fh is False:
        return
    try:
        fh.write("%s,%d,%s" % (code, int(filled), remark) + chr(10))
        fh.flush()
    except Exception as e:
        # Once. The per-record version reported every failure and put 69
        # identical lines into one morning's log, which buries the one line
        # that says what actually went wrong.
        S.fillfh = False
        log("  fill record unavailable: " + repr(e))


def _fills_from_orders():
    """{code: shares filled today}, rebuilt from the broker's ORDER list.

    Same quantity as the durable CSV and from the same field -- per-order
    m_nVolumeTraded -- but with no file in the path, so a restart does not lose
    it. This is the number that was RIGHT on 2026-08-31: 141 orders summing to
    48,889 for 688800.SH while the DEAL aggregate insisted on 50,000 and three
    names were retired on its word with 1,311 shares still held.

    Deduplicated by remark. The counter re-serves terminal rows on every bar,
    and a second copy of one order would inflate the count of the one source
    that has never over-reported.

    Returns {} when the query is unavailable, which the caller must read as "no
    information", never as "nothing sold".
    """
    out = {}
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ORDER")
    except Exception:
        return out
    seen = {}
    for o in rows or []:
        try:
            remark = getattr(o, "m_strRemark", "") or ""
            if not remark.startswith(STRATEGY):
                continue            # another strategy's order, or a manual one
            traded = int(getattr(o, "m_nVolumeTraded", 0) or 0)
            if traded <= 0:
                continue
            code = (getattr(o, "m_strInstrumentID", "") + "."
                    + getattr(o, "m_strExchangeID", ""))
            if code == ".":
                continue
            seen[remark] = (code, traded)
        except Exception:
            continue
    for code, traded in seen.values():
        out[code] = out.get(code, 0) + traded
    return out


def _fills_from_disk(day):
    """{code: shares filled today}, rebuilt from our own record.

    HOW MUCH HAVE I SOLD TODAY? Three answers existed and every one of them
    failed on 2026-08-27:

      DEAL query        authoritative inside one run of the terminal, blind to
                        everything before a restart, and slow to catch up
                        within one.
      baseline - held   the position went NEGATIVE all afternoon (-49,888 on a
                        50,000 target), so this had to be abandoned entirely.
      exec CSV          only records orders THIS process was tracking. The sell
                        script restarted four times; every order in flight at
                        each restart lost its row.

    The account settled it after the close: all nine Shanghai names were at
    zero. The basket had been fully liquidated by about 14:16, while the script
    believed it stood at 83.9% and spent the last three quarters of an hour
    sending 491 orders for shares it no longer owned -- every one refused with
    [COUNTER][251005] "insufficient available quantity", which was the truth.

    Undercounting `sold` is not a harmless error. It also starved the
    junk-order budget: `attempts` only resets when `sold` advances or an order
    rests, so a stalled count plus a stream of rejections retired all nine
    names three separate times today.

    This file records fills, once each, and outlives the process. It is a floor
    under `sold`, never a replacement -- max(), so whichever source is furthest
    along wins.
    """
    out = {}
    try:
        try:
            f = open(_fills_path(day))
        except IOError:
            return out              # nothing has filled yet today
        rows = f.readlines()
        f.close()
        for ln in rows[1:]:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                try:
                    out[parts[0]] = out.get(parts[0], 0) + int(parts[1])
                except ValueError:
                    continue
    except Exception as e:
        log("  fill replay failed: " + repr(e))
    return out


def _touch_raw(C, code):
    """(bid1, ask1, got_book) -- like _touch but WITHOUT requiring both sides.

    _touch below returns (0,0) unless bid AND ask are both positive. That is
    right for the spread filter and fatal here: a sealed limit-DOWN board has no
    BIDS at all, so bid1 is 0, and collapsing that to (0,0) makes "sealed" and
    "no data" the same value. The ceiling/floor test has to see the one-sided
    book, which is precisely the state it is asked about.

    got_book False means the feed said nothing; the caller falls back to the bar.
    """
    try:
        data = C.get_market_data_ex(["bidPrice", "askPrice"], [code],
                                    period="tick", count=1)
        f = data.get(code)
        if f is not None and len(f) > 0:
            row = f.iloc[-1]
            b, a = row["bidPrice"], row["askPrice"]
            bid = float(b[0]) if isinstance(b, (list, tuple)) and b else float(b or 0)
            ask = float(a[0]) if isinstance(a, (list, tuple)) and a else float(a or 0)
            if bid > 0 or ask > 0:
                return bid, ask, True
    except Exception:
        pass
    try:
        t = C.get_full_tick([code])
        d = t.get(code) if isinstance(t, dict) else None
        if isinstance(d, dict):
            def _lvl1(base):
                v = d.get(base)
                if isinstance(v, (list, tuple)) and v:
                    return float(v[0] or 0)
                v1 = d.get(base + "1")
                return float(v1 or 0) if v1 is not None else 0.0
            bid, ask = _lvl1("bidPrice"), _lvl1("askPrice")
            if bid > 0 or ask > 0:
                return bid, ask, True
    except Exception:
        pass
    return 0.0, 0.0, False


def _sealed_down(C, code, q):
    """Is the BID side gone at the floor right now? -> (bool, why).

    Mirror of the buy script's _sealed_up, with one deliberate difference in
    where the line is drawn.

    This script's mandate is to GET OUT. So it stops only when an order provably
    cannot fill -- when there is no bid at all. If a bid exists, even parked on
    the floor, a sell CAN hit it and we take it: a bad price is still an exit,
    and the alternative is carrying the position to the next session. That is a
    touch more permissive than the backtest, which treats "closed at the floor"
    as unsellable; the difference only ever makes the live script try harder to
    liquidate, never less hard.

    Live book first, previous bar only when the feed says nothing.
    """
    dn = _limit_down(C, code, q)
    if not dn:
        return False, ""                    # no floor known -> never block
    bid, ask, got = _touch_raw(C, code)
    if got:
        if bid <= 0:
            # No bids. Sealed only if the offers are stacked on the floor; an
            # empty book on a halted or untraded name is not limit-down.
            if ask > 0 and ask <= dn + TICK / 2:
                return True, "touch: no bid, offers at floor %.2f" % dn
            return False, "touch: empty bid side, ask %.2f" % ask
        return False, "touch: bid %.2f (floor %.2f) -- sellable" % (bid, dn)
    if q is not None and float(q["high"]) <= dn + TICK / 2:
        return True, "bar(no tick): prev-minute high %.2f at floor" % float(q["high"])
    return False, "bar(no tick)"


def _touch(C, code):
    """(bid1, ask1) from the live book, or (0,0).

    get_market_data_ex(period='tick') is tried FIRST because it serves every
    board. get_full_tick does not: on 2026-07-30 it returned five levels of
    zeros with a timetag frozen at the previous day for all three BJ names
    probed, while get_market_data_ex gave a live book for the same codes in the
    same second --

        920002.BJ  get_full_tick        bidPrice [0.0, 0.0, 0.0, 0.0, 0.0]
                   get_market_data_ex   bidPrice [51.51, 51.49, 51.47, ...]

    The spread filter was therefore dead on BJ names and the log said so, but
    the cause was the call, not the data. Main-board codes return the same book
    either way, so the new order costs nothing and get_full_tick stays as a
    fallback for builds where the tick period is unavailable.
    """
    try:
        data = C.get_market_data_ex(["bidPrice", "askPrice"], [code],
                                    period="tick", count=1)
        f = data.get(code)
        if f is not None and len(f) > 0:
            row = f.iloc[-1]
            bid = _first_level(row["bidPrice"])
            ask = _first_level(row["askPrice"])
            if bid > 0 and ask > 0:
                return bid, ask
    except Exception:
        pass
    try:
        t = C.get_full_tick([code])
    except Exception:
        return 0.0, 0.0
    d = t.get(code) if isinstance(t, dict) else None
    if not isinstance(d, dict):
        return 0.0, 0.0

    def _lvl1(base):
        v = d.get(base)
        if isinstance(v, (list, tuple)) and v:
            return float(v[0] or 0)
        v1 = d.get(base + "1")
        return float(v1 or 0) if v1 is not None else 0.0

    try:
        return _lvl1("bidPrice"), _lvl1("askPrice")
    except Exception:
        return 0.0, 0.0


def _spread_wide(C, code, hhmmss):
    """(is_wide, description). Fails open: no usable touch -> not wide.

    Reports the TRANSITION between usable and unusable tick data. A flag that is
    only set on the first call cannot tell you that a feed which worked at 09:30
    died at 10:00, which would disable this filter for the rest of the day with
    nothing in the log.
    """
    if MIN_SPREAD_TICKS_BY_MODE[_price_mode(code)] <= 0 or \
            hhmmss >= SPREAD_GUARD_UNTIL:
        return False, ""
    bid, ask = _touch(C, code)
    # Tracked PER CODE. A single global flag flapped between the two messages on
    # every bar, because 920002.BJ has no book through get_full_tick while the
    # main-board names do -- turning a real warning into noise. Report each code
    # once, and only again if its own state changes.
    prev = S.tick_ok.get(code)
    if bid <= 0 or ask <= 0 or ask <= bid:
        if prev is not False:
            S.tick_ok[code] = False
            log("  NOTE: %s has no usable tick/touch -> SPREAD FILTER INACTIVE"
                " FOR THIS NAME (it still sells, unprotected against a wide"
                " touch)" % code)
        return False, ""
    if prev is not True:
        S.tick_ok[code] = True
        log("  tick/touch OK %s -> spread filter live (bid %.2f ask %.2f)"
            % (code, bid, ask))
    spread = ask - bid
    ticks = int(round(spread / TICK))
    bps = spread / ((ask + bid) / 2.0) * 10000.0
    if ticks >= MIN_SPREAD_TICKS_BY_MODE[_price_mode(code)] and bps > MAX_SPREAD_BPS:
        return True, "bid %.2f ask %.2f = %d ticks / %.0f bps" % (bid, ask, ticks, bps)
    return False, ""


# -------------------------------------------------------------- account ------
def _positions(C):
    """code -> (net volume, can_use). Duplicate rows are ACCUMULATED.

    Assigning instead of accumulating double-counted every position in the buy
    script: this account returns 1395 rows for 1127 distinct codes.
    """
    out = {}
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "POSITION")
    except Exception as e:
        log("POSITION query FAILED: " + repr(e))
        return None
    n = 0
    for o in rows:
        n += 1
        code = getattr(o, "m_strInstrumentID", "")
        mkt = getattr(o, "m_strExchangeID", "")
        if not code or not mkt:
            continue
        key = code + "." + mkt
        if key not in SELL_TARGETS:
            continue
        v = int(getattr(o, "m_nVolume", 0) or 0)
        cu = int(getattr(o, "m_nCanUseVolume", 0) or 0)
        # Yesterday's volume is carried alongside as the fallback basis for
        # sizing; see _effective_can_use for why it is worth having.
        ye = int(getattr(o, "m_nYesterdayVolume", 0) or 0)
        if not S.pos_dumped and key in SELL_TARGETS:
            S.pos_dumped = True
            if DEBUG_DUMP_FIELDS:
                _dump_obj("POSITION row " + key, o)
            else:
                log("  POS sample %s vol=%s canuse=%s yest=%s onroad=%s"
                    % (key, v, cu, getattr(o, "m_nYesterdayVolume", "?"),
                       getattr(o, "m_nOnRoadVolume", "?")))
        pv, pc, py = out.get(key, (0, 0, 0))
        out[key] = (pv + v, pc + cu, py + ye)
    S.pos_rows = n
    return out


def _cu_alert(code, why, kind=None):
    """Report a can_use anomaly once per name per distinct reason, and keep it
    for the closing summary.

    Loudly, and twice over. A line that scrolls past in a 700-line session log
    is not an alert: on 2026-08-26 the NO AVAIL lines DID print, all afternoon,
    and the basket still went quiet for 45 minutes. The prefix makes it
    greppable and the end-of-session list makes it impossible to finish the day
    without seeing it.
    """
    if not why:
        return
    # Dedupe on the KIND the caller names, not on the sentence. The sentence
    # carries the live position, which moves with every fill, so keying on it
    # printed a fresh alert every bar -- and deriving the kind by chopping the
    # string up was no better, because the number sits inside the first clause.
    # Key on the KIND ALONE when the caller names one. The sentence carries the
    # live position and can_use, both of which move with every fill, so falling
    # back to the sentence made the dedupe a no-op: 2026-08-28 printed 129
    # copies of the same "clamped to the position" for twelve names. A kind
    # changes at most a couple of times a session.
    _key = kind if kind else why
    if S.cu_said.get(code) == _key:
        return
    S.cu_said[code] = _key
    if kind == "restore":
        # Diagnosed, not anomalous. Keep it in the log -- if the counter is
        # ever fixed the line stops appearing, and that is worth noticing --
        # but out of the alert channel, which exists for things nobody has
        # explained yet.
        S.cu_notes.append((_china_now(), code, why))
        log("  NOTE can_use %s: %s" % (code, why))
        return
    S.cu_alerts.append((_china_now(), code, why))
    log("!! ALERT can_use %s: %s" % (code, why))


def _effective_can_use(code, v, cu, yest, sold, pend):
    """How many shares we may actually send, when can_use cannot be believed.

    can_use is read verbatim from the broker's POSITION row
    (m_nCanUseVolume). On 2026-08-26 that field was wrong all day, in a way
    that is arithmetically impossible rather than merely surprising:

        09:44  vol 1300  can_use 2600  yesterday 1300
        12:59  vol  900  can_use 1800  yesterday 1300
        13:31  vol  700  can_use 1400  yesterday 1300
        14:44  vol  300  can_use    0  yesterday 1300

    can_use held at exactly TWICE the position for five hours -- available
    quantity is by definition a subset of the holding, so it can never exceed
    it -- and then collapsed to zero on every name at once while the shares
    plainly still existed. Both readings came back identical through two
    unrelated API paths (model trading's get_trade_detail_data and miniQMT's
    query_stock_positions), so the error is upstream of this script.

    The zero cost 7,198 shares that day: sizing multiplies by can_use, so the
    whole basket went quiet from 13:58 to the close and the position carried
    overnight -- the exact exposure this script exists to remove.

    Yesterday's volume was the one field that stayed correct through all of it,
    steady at 1300 across five samples, five restarts and a reboot. It is also
    the RIGHT basis on a healthy account: A-shares settle T+1, so what may be
    sold today is precisely what was held overnight, less what has already gone
    out today.

    Falling back rather than halting is deliberate. A buy script that stops on
    bad data simply buys less; a LIQUIDATION script that stops keeps a position
    it was told to be rid of, which is the worse failure. The target cap in the
    caller still bounds everything: nothing here can sell beyond the plan.
    """
    if v < 0:
        # Same bad read as above. Clamping to a negative position would hand
        # back a negative quantity; yesterday's volume is the only figure left
        # that has not gone strange.
        if yest > 0:
            eff = max(0, yest - sold - pend)
            if eff > 0:
                S.cu_fb_on.add(code)
            return eff, ("position reads %d, which is short and impossible for"
                         " this strategy; sizing from yesterday %d - sold %d -"
                         " resting %d = %d" % (v, yest, sold, pend, eff)), "negpos"
        return 0, ("position reads %d and yesterday is 0 too, so there is no"
                   " basis left and %s WILL NOT BE SOLD" % (v, code)), "nobasis"
    if cu > v:
        # CLAMP, do not fall back. can_use above the position is nonsense, but
        # the honest reading of it is "at least the whole position is free" --
        # so the position IS the answer, and yesterday's volume would only
        # arrive at the same number by a longer route.
        #
        # Keeping this out of the fallback matters more than the arithmetic.
        # Every order sized by the fallback is tagged, and three tagged
        # rejections switch the fallback off for that name. On 2026-08-27 this
        # branch fired for all twelve names at once -- the account reported
        # exactly twice the position on every one -- so every name in the
        # basket was carrying an armed rejection counter, and 688800.SH reached
        # 2/3 on two "price out of range" refusals that had nothing to do with
        # availability while it was selling perfectly well. The fallback is for
        # the case that actually needs rescuing: can_use 0 against real stock.
        if _restore_artifact(code, v, cu, yest):
            # Known and fully explained -- see _restore_artifact. Same clamp,
            # quieter report, so that a can_use we genuinely do not understand
            # is not buried under twelve copies of one we do.
            return min(cu, v), ("can_use %d = position %d + yesterday's sellable"
                                " %d -- the overnight restore counts the same"
                                " shares twice; clamped to the position"
                                % (cu, v, cu - v)), "restore"
        return min(cu, v), ("can_use exceeds the position, which is impossible"
                            " (can_use %d vs %d); clamped to the position"
                            % (cu, v)), "over"
    if code in S.cu_fb_off:
        # Written off earlier today: the exchange refused enough fallback orders
        # that can_use is now taken at face value. Deliberately BELOW the clamp
        # above -- clamping is not the fallback, it is arithmetic sanity, and a
        # written-off name must not start sizing from a figure larger than the
        # position it holds.
        return cu, None, None
    if cu <= 0 and v > 0 and pend <= 0:
        kind = "zero"
        why = ("can_use 0 with a real position and nothing of ours resting"
               " (position %d)" % v)
    else:
        return cu, None, None               # believable: use it unchanged
    if yest <= 0:
        # No trustworthy basis left. Say so loudly -- this is the one case that
        # really does stop the name, and it leaves shares overnight.
        return 0, (why + "; yesterday's volume is 0 too, so there is no basis"
                        " left and %s WILL NOT BE SOLD" % code), "nobasis"
    eff = max(0, min(v, yest - sold - pend))
    if eff > 0:
        S.cu_fb_on.add(code)     # tag orders from here as fallback-sized
    return eff, (why + "; falling back to yesterday %d - sold %d - resting %d"
                       " = %d" % (yest, sold, pend, eff)), kind


def _sold_today(C):
    """Shares this strategy actually SOLD today, from the broker's DEAL list.

    fun.xml documents strategyName as a filter on ORDER and DEAL, and passorder
    is given STRATEGY, so this is real attribution -- what traded, not what was
    sent. Returns None when the query is unavailable, which the caller must
    treat as "do not act", never as "nothing sold".
    """
    # Query WITHOUT the strategyName filter first, and only fall back to the
    # filtered form. Every row is re-checked against STRATEGY below anyway, so
    # the filter adds nothing -- and after a restart it appears to be scoped to
    # the CURRENT strategy instance: on 2026-08-03 the PC shut down at 10:16 and
    # the resumed run read `sold 0` for all 13 names while positions plainly
    # showed 3,350 shares of 300363.SZ already gone. The old loop broke out on
    # the first call that did not RAISE, so an empty filtered list was taken as
    # "nothing sold" and the whole TWAP schedule restarted from zero.
    rows = None
    for args in ((S.acct, S.acct_type, "DEAL"),
                 (S.acct, S.acct_type, "DEAL", STRATEGY)):
        try:
            got = list(get_trade_detail_data(*args) or [])
        except Exception:
            continue
        if rows is None or len(got) > len(rows):
            rows = got
        if rows:
            break
    if rows is None:
        return None
    out = {}
    for o in rows:
        try:
            if not S.deal_dumped:
                S.deal_dumped = True
                if DEBUG_DUMP_FIELDS:
                    _dump_obj("DEAL row", o)
            rem = getattr(o, "m_strRemark", "") or ""
            nm = getattr(o, "m_strStrategyName", "") or ""
            if STRATEGY not in rem and STRATEGY not in nm:
                continue
            # No direction filter here, deliberately. The buy script's
            # _filled_today has none and is proven -- it recovered 600958.SH's
            # 2300 shares correctly on 2026-07-29. A filter on m_nDirection was
            # added here "defensively" without ever confirming that a DEAL row
            # even carries that field, or that a sell is encoded as 49 rather
            # than as the 24 used for order_type. If the guess is wrong every
            # row is discarded, `sold` reads 0 forever, and the strategy sells
            # the full target again on the next bar. The STRATEGY tag already
            # isolates our deals and this script only ever sells, so the filter
            # bought nothing and risked a silent double-sell.
            code = getattr(o, "m_strInstrumentID", "") + "." + getattr(o, "m_strExchangeID", "")
            vol = 0
            for a in ("m_nVolume", "m_nTradedVolume", "m_nVolumeTraded"):
                v = getattr(o, a, None)
                if v:
                    vol = int(v)
                    break
            if code and vol:
                out[code] = out.get(code, 0) + vol
        except Exception:
            continue
    return out


def _order_id(o):
    for attr in ("m_strOrderSysID", "m_nOrderID", "m_strOrderID", "m_nOrderSysID"):
        v = getattr(o, attr, None)
        if v not in (None, "", 0):
            return v
    return None


def _order_price(o):
    """The price an order is resting at, from the broker's own row.

    Field names vary across QMT builds, hence the list -- the same reason
    _order_id has one. Returns 0.0 when none of them carries a usable price,
    which the caller must treat as "unknown", never as "zero".
    """
    for attr in ("m_dLimitPrice", "m_dOrderPrice", "m_dPrice",
                 "m_dLimitPrice1", "m_dOrderPrice1"):
        try:
            v = float(getattr(o, attr, 0) or 0)
        except Exception:
            continue
        if v > 0:
            return v
    return 0.0


def _order_insert_min(o):
    """Session minute the broker says the order was placed, or None."""
    for attr in ("m_strInsertTime", "m_strOrderTime", "m_nInsertTime", "m_nOrderTime"):
        v = getattr(o, attr, None)
        if v in (None, "", 0):
            continue
        t = str(v).replace(":", "").strip()
        if len(t) >= 4 and t[:4].isdigit():
            try:
                return _sess_min(t[:6].ljust(6, "0"))
            except Exception:
                continue
    return None


def _pending_and_cancel(C, today, hhmmss):
    """Return code -> unfilled shares resting, cancelling anything too old.

    Only orders whose remark starts with STRATEGY are touched. Manual orders and
    other strategies' orders in this shared account are left strictly alone.
    """
    pend = {}
    # Every remark the broker's ORDER list carries this bar, collected
    # before any skip so that a terminal row is never re-added as
    # pending by the block at the end of this function.
    _seen_remarks = set()
    now_m = _sess_min(hhmmss)
    # Phase drives what this scan is allowed to do:
    #   CANCEL  (14:56)      pull EVERYTHING, price tests do not apply -- the
    #                        book has to be empty before the auction opens
    #   AUCTION (14:57+)     cancel NOTHING. The exchange refuses cancellation
    #                        during the closing call auction, so every attempt
    #                        would be rejected and would only fill the log with
    #                        noise while the orders stayed live anyway.
    # Wall clock, not the bar label: the exchange stops accepting cancellations
    # at 14:57 by ITS clock, and the bar label runs 1-2 minutes ahead of it. On
    # 2026-08-24 the buy script was still sending cancels at wall 14:58:58 --
    # every one of them refused, and every one a counter message.
    _wall = _wall_hhmmss()
    _sweep_all = (SELL_END <= hhmmss) and _wall >= RUSH_END and _wall < AUCTION_AT
    _no_cancel = _wall >= AUCTION_AT
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ORDER")
    except Exception as e:
        log("ORDER query FAILED: " + repr(e))
        return None
    for o in rows:
        try:
            remark = getattr(o, "m_strRemark", "") or ""
            if not remark.startswith(STRATEGY):
                continue
            if not S.order_dumped:
                S.order_dumped = True
                if DEBUG_DUMP_FIELDS:
                    _dump_obj("ORDER row", o)
            status = int(getattr(o, "m_nOrderStatus", 0) or 0)
            total = int(getattr(o, "m_nVolumeTotalOriginal", 0) or 0)
            traded = int(getattr(o, "m_nVolumeTraded", 0) or 0)
            code = getattr(o, "m_strInstrumentID", "") + "." + getattr(o, "m_strExchangeID", "")
            if status == 57:
                _exec_close(o, remark, hhmmss)
                if remark not in S.rejected_seen:
                    S.rejected_seen.add(remark)
                    # The reason is in m_strCancelInfo, NOT m_strStatusMsg or
                    # m_strErrorMsg -- both of those came back empty on
                    # 2026-07-31 while cancelInfo carried the counter's actual
                    # message, e.g. "[COUNTER][251005][...]".
                    log("  REJECTED %s qty %d | statusMsg %r | cancelInfo %r"
                        % (code, total, getattr(o, "m_strStatusMsg", ""),
                           getattr(o, "m_strCancelInfo", "")))
                    # Remember WHY. This MUST sit inside the rejected_seen
                    # guard: the counter re-serves every terminal row on every
                    # bar, so counting outside it turned 50 rejected orders
                    # into "798 order(s) refused" in the 2026-08-31 10:43 NOTE.
                    # The guard is what makes this one-per-ORDER.
                    if "250253" in (getattr(o, "m_strCancelInfo", "") or ""):
                        S.reject_acct[code] = S.reject_acct.get(code, 0) + 1
                        S.acct_reject_at[code] = _sess_min(hhmmss)
                # 250253 is the Shenzhen
                # shareholder-account registration record; it has nothing to do
                # with this name being hard to sell, and the order is refused
                # before it reaches the market, so it costs nothing to keep
                # trying. Counting it as a junk order retired 300363.SZ at
                # 09:57 and 000972.SZ at 09:58 on 2026-08-31 -- 22,600 shares
                # abandoned by 10:00 over an account fault that is intermittent
                # and might have cleared by lunch.
                continue
            _seen_remarks.add(remark)
            if status in TERMINAL_STATUS:
                _exec_close(o, remark, hhmmss)
                continue
            left = total - traded
            if left <= 0:
                continue
            # A stuck order's shares are frozen at the exchange, so they are
            # already missing from can_use_volume. Counting them here as well
            # would subtract them a second time and starve the schedule.
            if _zombie(remark, status, left, now_m):
                continue
            pend[code] = pend.get(code, 0) + left

            # 51 = reported, cancel pending; 52 = part-filled, cancel pending.
            # The cancel has ALREADY been accepted and is working its way
            # through the exchange -- sending another achieves nothing. Without
            # this, two orders sat in status 51 for half an hour on 2026-07-31
            # and were re-cancelled once a minute, roughly thirty redundant
            # cancels per name. Exchanges do police cancel rates. The order
            # still counts as pending above, because its unfilled remainder can
            # come back if the cancel loses the race.
            if status in CANCEL_PENDING_STATUS:
                if remark not in S.cancel_inflight:
                    S.cancel_inflight.add(remark)
                    log("  cancel already in flight for %s (status %d, left %d)"
                        " -- not re-sending" % (code, status, left))
                continue

            # An order that has not REACHED the exchange yet cannot be cancelled.
            # 48 = not reported, 49 = waiting to be reported: the counter still
            # has it. Only 50 (reported) and 55 (part-filled) are cancellable.
            #
            # 2026-08-24, first minutes of the session: QMT popped
            #   entrust[182] cancel failed, err -54
            #   [COUNTER][251020][order status does not allow cancellation]
            #   [old_entrust_status=1]      <- 1 = being reported
            # because QUEUE mode in a falling market re-quotes at the
            # CANCEL_MIN_REST_BARS floor of one bar, which is short enough to
            # catch an order still in transit. The cancel is simply refused, so
            # nothing is lost -- but it raises a dialog on the terminal and puts
            # a rejected cancel on the counter's record, and the order we wanted
            # gone stays live for another bar anyway.
            #
            # Skipping is free: the status becomes 50 within a second or two and
            # the next bar cancels it normally.
            if status not in CANCELLABLE_STATUS:
                continue

            placed = S.order_time.get(remark)
            if placed is None:
                # After a restart our own earlier orders look unknown. Use the
                # broker's timestamp so a genuinely old order is cancelled at
                # once instead of being given another STALE_ORDER_MIN grace.
                placed = _order_insert_min(o)
                if placed is None:
                    placed = now_m
                S.order_time[remark] = placed
                # RECOVER THE PRICE TOO, not just the age.
                #
                # Without it _ref stays 0 and the price test below is skipped
                # for the fallback that cancels anything older than
                # STALE_ORDER_MIN -- so every order that survived a restart is
                # pulled regardless of where the touch is. 2026-09-01 13:46:
                # eight orders adopted, eight cancelled in the same second, the
                # touch unmoved, and the re-quotes went back in at the same
                # price. 500 shares of 002573.SZ lost their place for nothing.
                #
                # The broker knows where the order rests. Reconstructing
                # S.exec_open from it lets the ordinary test -- has the touch
                # moved away from MY price? -- apply to a pre-restart order
                # exactly as to one we placed ourselves.
                _apx = _order_price(o)
                if _apx > 0 and remark not in S.exec_open:
                    _amode = _price_mode(code)
                    S.exec_open[remark] = {
                        "code": code, "side": "sell", "qty": int(total),
                        "t": hhmmss, "rt": dt.datetime.utcnow(),
                        # A QUEUE sell rests at the ask, a COMPETE sell at the
                        # bid. Record the order's own price on the side its
                        # mode reads, so the comparison below is like for like.
                        "bid": _apx if _amode == "COMPETE" else 0.0,
                        "ask": _apx if _amode != "COMPETE" else 0.0,
                        "bar": 0.0, "mode": _amode, "fb": False, "adopted": True}
                log("  ADOPT pre-restart order %s %s left %d age %dmin%s"
                    % (code, remark, left, max(0, now_m - placed),
                       (" resting at %.2f" % _apx) if _apx > 0
                       else " (price unknown)"))
            # ---- cancel on PRICE, not on a stopwatch --------------------
            # Mirror of the buy script. A counterparty-price SELL becomes a
            # resting LIMIT order at the bid we saw when we sent it, and it goes
            # bad in BOTH directions:
            #   bid falls below our price -> it can never fill, it just blocks
            #   bid rises above our price -> it still fills, at OUR price,
            #                                because A-shares execute at the
            #                                price of whichever order was
            #                                entered first. We sell too cheap.
            # Only an UNCHANGED touch makes resting free, and then it is pure
            # gain: re-quoting the same price only sends us to the back of the
            # queue, which on a thin name is the whole game.
            _rec = S.exec_open.get(remark)
            # Compare against the side the order is RESTING ON, which depends on
            # the mode it was priced under:
            #   COMPETE  prType 14 -> the order sits at the BID we saw
            #   QUEUE    prType  4 -> it sits at the ASK we saw
            # Using "bid" for both made QUEUE cancel itself to death. Live,
            # 2026-08-18: 920047.BJ sent six orders, 937 shares, and filled
            # nothing, because every minute the bid ticked UP toward our resting
            # ask and the "would undersell" test fired --
            #     bid 17.72 -> 17.75 ... 17.72 -> 17.77 ... 17.73 -> 17.79
            # -- so we pulled the order and re-posted at the back of the queue
            # exactly when the market was walking into it. That test is correct
            # for COMPETE, where a rising bid really would fill us too cheap; on
            # a passive offer a rising bid is the fill arriving.
            _omode = (_rec or {}).get("mode") or _price_mode(code)
            _ref = float((_rec or {}).get(
                "bid" if _omode == "COMPETE" else "ask") or 0)
            # A mode change overrides every price test below, including the
            # just-placed grace: this order carries the OLD pricing and cannot
            # re-price itself, so it has to go regardless of where the touch is.
            _stale_mode = bool(_rec) and _rec.get("mode") not in (None, _price_mode(code))
            # A CEILING-PRICED ORDER IS IN NEITHER MODE. It rests at the
            # limit-up price, so neither branch below describes it, and _ref
            # would be the ask -- zero in the very board it was written for.
            #
            # And it must not be left resting once the board reopens: an
            # unfilled order still counts in `pend`, `pend` is subtracted from
            # the slice, and the name would go quiet for the rest of the day
            # holding one far-off-market offer. Tested every bar, ahead of the
            # just-placed grace, because a reopening is a real state change
            # rather than the churn that grace exists to damp.
            _ceil_px = S.ceiling_orders.get(remark)
            if _no_cancel:
                continue        # closing auction: the exchange refuses cancels
            elif _ceil_px is not None:
                _su_now, _ = _sealed_up_sell(C, code, None)
                if _su_now and (now_m - placed) < CANCEL_BACKSTOP_MIN:
                    continue        # still sealed -> the ceiling is still right
                _why = (("limit-up board REOPENED; a %.2f ceiling order cannot"
                         " fill and blocks the name" % _ceil_px) if not _su_now
                        else "ceiling order unfilled for %d min" % (now_m - placed))
            elif _sweep_all:
                _why = "clearing the book before the 14:57 closing auction"
            elif _stale_mode:
                # No global one-shot flag any more: the order carries the mode
                # it was priced under, so comparing it with this NAME's current
                # effective mode is the whole test. It is also self-clearing --
                # once re-quoted the recorded mode matches again.
                _why = "price mode changed (%s -> %s)" % (_rec.get("mode"),
                                                          _price_mode(code))
            elif (now_m - placed) < CANCEL_MIN_REST_BARS:
                continue                    # just placed: let it queue first
            else:
                _why = ""
            # Only consult the touch when the mode change has not already
            # condemned this order -- otherwise an unchanged bid would `continue`
            # and the stale-mode order would survive the switch.
            if not _why:
                if _ref > 0:
                    _b, _a, _got = _touch_raw(C, code)
                    _now_px = _b if _omode == "COMPETE" else _a
                    if _got and _now_px > 0:
                        if _omode == "COMPETE":
                            if _b < _ref - TICK / 2:
                                _why = "bid %.2f -> %.2f, cannot fill" % (_ref, _b)
                            elif _b > _ref + TICK / 2:
                                _why = "bid %.2f -> %.2f, would undersell" % (_ref, _b)
                            elif (now_m - placed) >= CANCEL_BACKSTOP_MIN:
                                _why = "touch unchanged but %d min old" % (now_m - placed)
                            else:
                                continue    # price has not moved -> hold the slot
                        else:
                            # QUEUE: our offer rests at the ask we saw.
                            #   ask FELL  -> someone undercut us; we are behind
                            #                the touch and will not trade. Move.
                            #   ask ROSE  -> our offer is now the best one in the
                            #                book. Hold: we are first in line and
                            #                about to be lifted.
                            if _a < _ref - TICK / 2:
                                _why = "ask %.2f -> %.2f, undercut at the touch" \
                                       % (_ref, _a)
                            else:
                                # NO AGE BACKSTOP HERE. It used to cancel after
                                # CANCEL_BACKSTOP_MIN even with the touch
                                # unchanged, and the re-quote then went back in
                                # at the SAME price -- surrendering our place in
                                # the queue and buying nothing with it.
                                #
                                # 2026-09-01 13:34, 002573.SZ: cancelled at 3.33
                                # with the ask still 3.33, re-quoted at 3.33,
                                # back of the line.
                                #
                                # There is no case where it helps. Ask FELL ->
                                # the branch above moves us. Ask ROSE -> we are
                                # the best offer and should hold. UNCHANGED ->
                                # we are AT the touch, and re-quoting at the
                                # touch cannot improve a queue position, only
                                # give one up. The backstop belongs to COMPETE,
                                # where an order resting at a counterparty price
                                # from minutes ago really can go stale; it does
                                # not transfer to a passive quote.
                                #
                                # A name that is stuck because the queue ahead
                                # of it is long needs to CROSS the spread, not
                                # to rejoin the same queue -- that is what
                                # MODE_OVERRIDE and price_mode are for.
                                continue    # at or better than the touch -> wait
                    elif (now_m - placed) >= STALE_ORDER_MIN:
                        _why = "no touch data, %d min old" % (now_m - placed)
                    else:
                        continue
                elif (now_m - placed) >= STALE_ORDER_MIN:
                    _why = "no reference price, %d min old" % (now_m - placed)
                else:
                    continue
            # Do not re-send a cancel we already sent moments ago. The 51/52
            # guard above only catches orders the broker has moved INTO a
            # cancel-pending state; an order that stays in 50 (reported) or 55
            # (part-filled) is still "cancellable", so without this the same
            # order is cancelled once per bar forever. On 2026-08-03,
            # combo_sell_close_300363SZ_105300 was cancelled 33 times over 33
            # minutes -- the age in the log climbed 5, 6, 7 ... 33 min on ONE
            # order. Exchanges police cancel rates and the broker bills per
            # order, so this is a cost, not just noise.
            #
            # A cooldown rather than a one-shot: a cancel CAN be dropped, and an
            # order that never dies would then block its name's `pend` for the
            # rest of the day. Retrying every STALE_ORDER_MIN turns 33 cancels
            # into 6 while still guaranteeing another attempt.
            # Written off: every cancel we sent bounced. Sending more only
            # feeds the 251020 storm; the order dies at 15:00 with everything
            # else. _zombie() un-flags it the moment its status or remainder
            # moves, so this is not a permanent sentence.
            if remark in S.zombies:
                continue
            # BAR minutes, not real seconds. A real-clock cooldown cannot be
            # exercised offline: a whole session replays in a few seconds, so
            # every order gets exactly one cancel attempt and the retry path --
            # along with the zombie rule that counts those retries -- goes
            # untested. Bar minutes are what CANCEL_MIN_REST_BARS and
            # CANCEL_BACKSTOP_MIN already use, and live the two agree.
            last_cx = S.cancel_sent.get(remark)
            if last_cx is not None and (now_m - last_cx) < STALE_ORDER_MIN:
                continue
            oid = _order_id(o)
            if oid is None:
                continue
            try:
                if not can_cancel_order(oid, S.acct, S.acct_type):
                    continue
            except Exception:
                pass
            cancel(oid, S.acct, S.acct_type, C)
            S.cancel_sent[remark] = now_m
            # Signature at the moment of the cancel. If the next scan sees the
            # same pair, this cancel achieved nothing.
            S.cx_tries[remark] = S.cx_tries.get(remark, 0) + 1
            S.cx_sig[remark] = (status, left)
            S.cx_first.setdefault(remark, now_m)
            # Keep order_time. Popping it made the next bar treat this same
            # order as an unknown pre-restart one and ADOPT it again, which is
            # why the log filled with ADOPT/CANCEL pairs for one order.
            S.cancel_inflight.add(remark)
            # Include the remark: without it, "CANCEL stale 601398.SH age 2min"
            # every other minute is indistinguishable from a cancel that keeps
            # failing on ONE order and from the healthy place/cancel/re-quote
            # cycle. Only the growing age gave it away on 2026-07-31.
            log("  CANCEL %s %s left %d age %dmin -> %s -> re-quote"
                % (code, remark, left, now_m - placed, _why))
        except Exception as e:
            log("  order scan error: " + repr(e))

    # ---- OUR OWN ORDERS THE BROKER CANNOT SEE YET -----------------------
    # Mirror of the buy side, and of the same failure. Tens of seconds pass
    # between passorder returning and the order appearing in the ORDER list.
    # In that window the shares are in NEITHER place: nothing has filled, so
    # the position has not moved, and the loop above cannot see them. The
    # script looks, sees nothing, and sizes the next slice as though it had
    # not sold anything.
    #
    # 2026-08-31, three names oversold inside eight minutes:
    #     600968.SH  132500 132700 132900 133100 133200  -> 1200 of a 1000 target
    #     600628.SH  132100 ... 132700 133200            -> 1000 of a  900 target
    #     600816.SH  ... 132700 133200                   -> 1100 of a 1024 target
    # and all three positions went NEGATIVE (-199, -199, -175), which is what
    # overselling looks like on an account whose volume is a net figure.
    #
    # It did not show in the morning because the bars were more than two
    # minutes apart and the counter kept up. After 13:20 the tick cadence
    # tightened to a few seconds and the window opened.
    #
    # Every one of the three "how much have I sold" sources lags -- the DEAL
    # query, the durable fill record, and baseline-minus-holding all describe
    # a fill only AFTER it is observed. `pend` is the only term that can
    # describe an order that has not filled yet, so it is the one that has to
    # know about orders the broker has not acknowledged.
    #
    # S.exec_open is the right source: entered when the order is SENT, removed
    # only by _exec_close, i.e. only once the broker has returned a verdict.
    _now_rt = dt.datetime.utcnow()
    for _r, _rec in list(S.exec_open.items()):
        if (_rec or {}).get("side") != "sell" or _r in _seen_remarks:
            continue
        _rt = _rec.get("rt")
        if _rt is not None and (_now_rt - _rt).total_seconds() >= PEND_INVISIBLE_MAX_SEC:
            # Never showed up. Holding it in pend forever would starve the
            # schedule and leave stock unsold overnight -- the opposite
            # failure, and the one this whole script exists to prevent.
            if _r not in S.pend_released:
                S.pend_released.add(_r)
                log("  WARN %s never reached the broker's order list in %.0f"
                    " min -- releasing it from pending" 
                    % (_r, PEND_INVISIBLE_MAX_SEC / 60.0))
            continue
        _c = _rec.get("code")
        _q = int(_rec.get("qty") or 0)
        if _c and _q > 0:
            pend[_c] = pend.get(_c, 0) + _q
    return pend


def _reconcile_waiting(C, hhmmss):
    """True when every order we sent has been seen by the broker.

    passorder returns immediately but the order takes seconds to appear in the
    ORDER query, so `pend` reads 0 in the meantime. Holding off on a new slice
    until the previous one is visible closes that window.

    Ages entries out on the REAL clock, not on bar time. Bar time is not
    monotonic with wall time: when the PC suspended at 13:24:59 on 2026-07-30
    and resumed six seconds later, QMT delivered the backlog and the bar label
    jumped from 131100 to 132600 -- fifteen bar-minutes in three real seconds.
    Aging on bar time therefore declared three orders "never appeared, likely
    rejected" three seconds after sending them, which dropped this guard
    entirely and let the same slice go out again. Those orders had not been
    rejected; the broker simply had not caught up. 601012.SH ended up 251 shares
    ahead of its schedule as a result.
    """
    if not S.waiting:
        return True
    found = set()
    try:
        for o in get_trade_detail_data(S.acct, S.acct_type, "ORDER"):
            r = getattr(o, "m_strRemark", "") or ""
            if r in S.waiting:
                found.add(r)
    except Exception:
        pass
    for r in found:
        S.waiting.pop(r, None)
    # An order rejected outright never appears at all, so age entries out rather
    # than pausing the strategy for the rest of the session -- but on real
    # seconds, and generously: a rejection is rare and waiting is cheap, while
    # giving up too early costs a duplicate order.
    if S.waiting:
        now = dt.datetime.utcnow()
        for r in list(S.waiting):
            code, qty, placed = S.waiting[r]
            age = (now - placed).total_seconds()
            if age >= UNCONFIRMED_TIMEOUT_SEC:
                log("  WARN %s order not seen by the broker after %.0fs"
                    " (likely rejected) -> giving up on it" % (r, age))
                S.waiting.pop(r, None)
                S.order_time.pop(r, None)
    if S.waiting:
        pend = {}
        for r, (code, qty, placed) in S.waiting.items():
            pend[code] = pend.get(code, 0) + qty
        S.unconfirmed = pend
    else:
        S.unconfirmed = {}
    return not S.waiting


def _run_auction(C, pos, sold, pend, hhmmss):
    """Put whatever is still unsold into the closing call auction, once.

    Priced at the limit-DOWN price. A call auction clears every matched order at
    a single price set by maximum volume, so a floor-priced sell says "fill me
    at whatever that price turns out to be" and executes AT THE CLEARING PRICE.
    It only ever trades at the floor if the stock is already sealed there, and
    then nothing could have been sold anyway.

    Sent ONCE. handlebar fires for 14:57, 14:58 and 14:59, and the exchange will
    not let us cancel a mistake during those three minutes, so a second pass
    would be a second position going out with no way back.
    """
    if S.auction_done:
        return
    if _in_settle():
        # Do not skip the auction, delay it. S.auction_done stays False so the
        # next bar tries again; the exchange accepts orders until 15:00, and
        # 14:58 plus a settle is still inside the window.
        log("  AUCTION held: still settling after a restart")
        return
    S.auction_done = True
    sent = 0
    _base_open = _load_or_snapshot_baseline(pos)
    for code in sorted(SELL_TARGETS):
        # DELIBERATELY NOT SKIPPING S.done.
        #
        # This is the last chance of the day, and S.done was decided from `s`,
        # the number that has been wrong. On 2026-08-31 it retired
        # 688800/601398/600981 at 13:59:59 while 1,311 shares were still held,
        # and this loop then walked past all three. A name with nothing left
        # sizes to zero here anyway, so re-examining it costs one arithmetic
        # step; skipping it costs the position.
        if code in S.gave_up:
            continue
        tgt = SELL_TARGETS[code]
        v, cu, _ye = pos.get(code, (0, 0, 0))
        s = sold.get(code, 0)
        cu, _alert, _akind = _effective_can_use(code, v, cu, _ye, s,
                                                pend.get(code, 0))
        _cu_alert(code, _alert, _akind)
        # SIZE FROM can_use_volume, NOT from pend.
        #
        # The old form was `allowed = min(tgt, s + cu + pend); left = allowed -
        # s - pend`, meant to avoid double-selling anything the sweep failed to
        # kill. It backfired on 2026-08-24: the sweep HAD killed them, but at
        # auction time they were still sitting in status 51 (reported,
        # cancel pending), so pend was ~30,000 shares and `left` came out at a
        # few hundred. 688800.SH sent 222 shares into the auction with 19,378
        # unsold, and the basket closed at two thirds done.
        #
        # can_use_volume answers the same question without the race, because the
        # exchange maintains it: shares locked in a live order are not in it,
        # and shares released by a cancel are. Selling min(target remainder,
        # can_use) can therefore never double-sell -- if a cancel has not
        # settled, those shares are simply still frozen and we do not touch
        # them -- and it cannot be starved by a stuck order either.
        left = max(0, min(tgt - s, max(0, cu)))
        # WHAT IS ACTUALLY LEFT IS WHAT IS STILL HELD.
        #
        # `tgt - s` inherits every error in `s`; the holding does not. Total
        # sold is (opening holding - held now) by definition of the account, so
        # what remains of the mandate is tgt - (base - v), and for a full
        # liquidation that is simply v. Take the LARGER of the two readings:
        # this is the last order of the day, an over-estimate costs a rejected
        # order, and an under-estimate costs an overnight position.
        _open0 = int(_base_open.get(code, 0) or 0)
        if _open0 > 0 and v > 0:
            _by_hold = max(0, min(v, tgt - (_open0 - v)))
            if _by_hold > left:
                log("  AUCTION %s: sized from the holding, %d not %d"
                    " (opened %d, holds %d, sold-estimate %d)"
                    % (code, _by_hold, left, _open0, v, s))
                left = _by_hold
        if left <= 0:
            continue
        q = _bar(C, code, S.today_str, hhmmss)
        dn = _limit_down(C, code, q)
        _px_why = "the floor"
        if not dn:
            # NOT a reason to skip. Mid-session a missing floor merely turns the
            # limit-down GUARD off and the name keeps selling -- the safe
            # direction for a script whose job is to get out. Here the same
            # missing number used to abandon the name outright, the opposite
            # choice from the same fact. 2026-08-31 lost 000972.SZ and
            # 300363.SZ to it while 000063.SZ, same board, same second, had a
            # floor.
            #
            # Any legal price low enough will do: a call auction fills a sell
            # whenever the clearing price is at or above its limit, so the bid
            # is nearly always good enough and the last trade is the next best
            # guess. Both are prices the market has shown, so neither can be
            # refused as out of range.
            _b, _a = _touch(C, code)
            if _b and _b > 0:
                dn, _px_why = _b, "the bid (no floor available)"
            elif q is not None:
                try:
                    dn, _px_why = float(q["close"]), "the last trade (no floor)"
                except Exception:
                    dn = None
            if not dn:
                log("  AUCTION skip %s: no floor, no bid and no last trade" % code)
                continue
        qty = _round_sell(code, left, left, v)
        if qty <= 0:
            log("  AUCTION skip %s: %d shares left is below the %d-share minimum"
                % (code, left, _min_lot(code)))
            continue
        if _order_sell(C, code, qty, hhmmss, limit_px=dn):
            sent += 1
            log("  AUCTION %s %d shares at %s %.2f (clears at the auction"
                " price, not at this one)" % (code, qty, _px_why, dn))
    log("  AUCTION: %d order(s) placed; no cancellation is possible until 15:00"
        % sent)


def _order_sell(C, code, qty, hhmmss, limit_px=None):
    remark = "%s_%s_%s" % (STRATEGY, code.replace(".", ""), hhmmss)
    # Snapshot the touch BEFORE sending. Execution quality can only be measured
    # against the market as it stood when the decision was made; reading the
    # book after the fill would already include our own impact.
    _bid, _ask = _touch(C, code)
    _bar = _bar_price(C, code, S.today_str, hhmmss)
    try:
        if limit_px is not None:
            # fun.xml prType 11 = model/limit price, and PRICE is only read for
            # 11. Used by the closing auction, where a price type derived from
            # the touch is meaningless: there is no touch during a call auction.
            passorder(S.sell_code, 1101, S.acct, code, 11, float(limit_px),
                      int(qty), STRATEGY, 1, remark, C)
        else:
            passorder(S.sell_code, 1101, S.acct, code,
                      PRTYPE_BY_MODE[_price_mode(code)], -1,
                      int(qty), STRATEGY, 1, remark, C)
    except Exception as e:
        log("  passorder FAILED %s %d: %s" % (code, qty, repr(e)))
        return False
    S.order_time[remark] = _sess_min(hhmmss)
    # REAL clock too. The cancel test ages orders in real seconds because bar
    # time is not monotonic with wall time -- a PC suspend makes it jump.
    S.order_real_time[remark] = dt.datetime.utcnow()
    S.waiting[remark] = (code, int(qty), dt.datetime.utcnow())
    # Stamp the mode this order was priced under. Without it the exec CSV is a
    # pile of fills with no way to say which pricing produced which cost, and
    # comparing the two modes -- the whole reason the switch exists -- is
    # impossible after the fact.
    S.exec_open[remark] = {"code": code, "side": "sell", "qty": int(qty),
                           "t": hhmmss, "rt": dt.datetime.utcnow(), "bid": _bid, "ask": _ask, "bar": _bar,
                           "mode": _price_mode(code),
                           # Was this slice sized by the can_use fallback? Only
                           # those orders may count against it -- 2026-08-26
                           # also produced 25 "price out of range" rejections
                           # that had nothing to do with can_use, and letting
                           # those disable the fallback would punish the wrong
                           # thing.
                           "fb": code in S.cu_fb_on}
    _log_trade(hhmmss, code, qty, remark)
    log("  SELL %s %d shares (%s)" % (code, int(qty), remark))
    return True


# ----------------------------------------------------------------- engine ----
def _hhmmss_secs(t):
    """HHMMSS -> seconds since midnight. 0 if it cannot be read."""
    try:
        t = str(t)
        return int(t[0:2]) * 3600 + int(t[2:4]) * 60 + int(t[4:6])
    except Exception:
        return 0


def _in_settle():
    """True while a mid-session restart is still observing.

    Everything else in the bar still runs -- positions, fills, pending orders,
    cancels -- so the picture completes itself while this is True. Only new
    orders are withheld.
    """
    if not getattr(S, "session_in_hours", False):
        return False                    # started pre-open: nothing in flight
    started = getattr(S, "session_started", None)
    if not started:
        return False
    # THE SAME CLOCK THE REST OF THE SCRIPT USES.
    #
    # An earlier version measured this in real seconds off utcnow(). That is
    # arguably the truer reading -- the counter's acknowledgement latency is
    # real time -- but it makes the window untestable: the offline replay runs
    # a whole session in a few real seconds, so every bar fell inside a 95
    # second window and nothing was ever sold. A guard that cannot be exercised
    # offline is a guard nobody can trust.
    #
    # The wall clock is what every other end-of-day boundary in this script is
    # gated on, the harness drives it, and in production the two agree.
    age = _hhmmss_secs(_wall_hhmmss()) - _hhmmss_secs(started)
    if age < 0:
        return False                    # clock went backwards -> do not hold
    if age >= RESTART_SETTLE_SEC:
        if getattr(S, "session_in_hours", False) and not S.settle_said:
            S.settle_said = True
            log("  SETTLE COMPLETE after %.0fs -- any order in flight at the"
                " restart is now in the counter's list and counted as pending;"
                " sending resumes" % age)
        S.session_in_hours = False      # done for good, stop re-checking
        return False
    return True


def _validate():
    bad = dict((c, q) for c, q in SELL_TARGETS.items()
               if q <= 0 or q > MAX_TARGET_SHARES)
    if bad:
        log("FATAL: SELL_TARGETS out of range (max %d): %r" % (MAX_TARGET_SHARES, bad))
        return False
    if not SELL_TARGETS:
        log("FATAL: SELL_TARGETS is empty")
        return False
    return True


def _report_plan(pos, sold, pend):
    log("-" * 74)
    log("PLAN  %-11s %8s %7s %9s %9s %9s"
        % ("code", "target", "sold", "held", "can_use", "to_sell"))
    tot = 0
    for c in sorted(SELL_TARGETS):
        tgt = SELL_TARGETS[c]
        v, cu, _ye = pos.get(c, (0, 0, 0))
        s = sold.get(c, 0)
        # Same sum as the sizing loop: pending shares are frozen out of
        # can_use but are still ours, so they count toward what is sellable.
        eff = max(0, min(tgt, s + max(0, cu) + pend.get(c, 0)) - s)
        tot += eff
        note = ""
        if s + eff < tgt:
            note = "  <-- can_use caps us %d short" % (tgt - s - eff)
        log("      %-11s %8d %7d %9d %9d %9d%s" % (c, tgt, s, v, cu, eff, note))
    log("  sold so far %d | sellable now %d | targeted %d"
        % (sum(sold.get(c, 0) for c in SELL_TARGETS), tot,
           sum(SELL_TARGETS.values())))
    log("-" * 74)


def _baseline_path():
    d = (getattr(S, "runlog_dir", None) or LOG_DIR)
    return (d + "\\baseline_" + STRATEGY + "_" + _acct_tag()
            + "_" + _today_str() + ".csv")


def _load_or_snapshot_baseline(pos):
    """Holding of each target at the START of today, persisted to disk.

    This is the sell side's restart recovery, and it deliberately does NOT copy
    the buy script's _restore_from_log. That replays the trade CSV, which
    records orders SENT. On the sell side sent and filled diverge badly -- on
    2026-08-03 the script sent far more than it ever filled because counterparty
    orders kept resting and being cancelled (one name was cancelled 33 times).
    Treating sends as sales would have read "already done" and stopped selling.

    A position baseline has no such gap: sold_today = baseline - held_now is the
    actual share count that left the account, whatever the broker's DEAL query
    remembers. That query is the thing being backstopped -- it silently loses
    every fill from before a terminal restart. Measured the same day, after the
    PC rebooted at 10:16: 300363.SZ opened at 20,000 and held 11,300, so 8,700
    had really gone, while DEAL reported 5,350. The 3,350 gap stayed constant
    all afternoon, and on a PARTIAL sell (target below the holding) it would
    have sold that much a second time.

    Written once per day. A restart finds the file and loads it, so the morning's
    starting quantity survives. If the sandbox refuses the write, we fall back to
    the in-memory snapshot -- correct until a restart, which is what we had
    before.
    """
    if S.baseline is not None:
        return S.baseline
    p = _baseline_path()
    try:
        f = open(p, "r")
        rows = f.readlines()
        f.close()
        base = {}
        for ln in rows[1:]:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                try:
                    base[parts[0]] = int(parts[1])
                except ValueError:
                    continue
        if base:
            S.baseline = base
            log("  BASELINE loaded from disk: %d name(s), opened with %d shares"
                % (len(base), sum(base.values())))
            return S.baseline
    except Exception:
        pass
    # NO FILE. Was this a fresh start, or a restart whose baseline we simply
    # cannot read? On 2026-09-01 LIVE mode refused to open any pre-existing
    # file, so a restart lands here with shares already sold -- and snapshotting
    # the CURRENT holding would record them as never held, making sold_today
    # read 0 and offering the whole basket a second time.
    #
    # SELL_TARGETS is the answer, and it needs no file: this basket was read off
    # the account at the open, so for a full liquidation it IS the opening
    # holding. Where it is not (a partial mandate, or an account holding more
    # than we were told to sell) it is LOWER than the true opening holding,
    # which understates sold_today -- and understating is the safe direction:
    # it offers stock we may no longer have, costing a rejected order, while
    # overstating stops early and carries the position overnight.
    #
    # The holding still bounds everything downstream: allowed is capped by
    # can_use, DONE is decided on the holding, and the auction sizes from it.
    base = {}
    _short = []
    for code in SELL_TARGETS:
        v, _cu, _ye = pos.get(code, (0, 0, 0))
        _tgt = int(SELL_TARGETS[code])
        base[code] = max(0, int(v))
        if int(v) < _tgt:
            base[code] = _tgt
            _short.append("%s %d<%d" % (code, int(v), _tgt))
    if _short:
        log("  BASELINE: no readable file and %d name(s) hold less than their"
            " target, so this is a RESTART -- sizing the opening holding from"
            " SELL_TARGETS, not from what is left. %s"
            % (len(_short), ", ".join(_short[:6])))
    S.baseline = base
    try:
        f = open(p, "w")
        f.write("code,shares\n")
        for code in sorted(base):
            f.write("%s,%d\n" % (code, base[code]))
        f.flush()
        f.close()
        log("  BASELINE snapshot written: %d name(s), %d shares"
            % (len(base), sum(base.values())))
    except Exception as e:
        log("  BASELINE could not be persisted (%r) -- in-memory only, so a"
            " restart would fall back to the DEAL query alone" % (e,))
    return S.baseline


def _run_sells(C, today, hhmmss):
    S.today_str = today
    # Poll the mode file before anything else this bar, so the price type, the
    # spread filter and the dry-spell budget all agree within one pass.
    _changed = _refresh_price_mode()
    if _changed:
        # Orders already resting were priced under the OLD mode and cannot
        # re-price themselves, so they have to be pulled. But only for the names
        # that actually changed: a per-name switch must not disturb the rest of
        # the book, which is the entire point of making it per-name.
        log("  price mode changed for %s -> resting orders on those names will"
            " be cancelled and re-quoted"
            % ("every name" if "*" in _changed else ", ".join(sorted(_changed))))
    pos = _positions(C)
    if pos is None:
        return
    # AN EMPTY POSITION RESULT IS NOT AN EMPTY ACCOUNT.
    #
    # The baseline floor below reads `sold = baseline - held`, and a missing row
    # makes held 0, which makes sold the entire target. One name vanishing is
    # the normal, correct signal that it sold out. EVERY name vanishing at once
    # is a failed read -- a basket does not go from 41% to 100% between two
    # bars, the participation cap alone forbids it.
    #
    # 2026-08-27 10:48:59: the query came back with no rows for any of the nine
    # targets. Every one was scored as fully sold, all nine went into S.done,
    # the script logged "all names finished or abandoned" and stopped working
    # for the day -- holding 40,490 shares it believed it had already sold. The
    # summary printed one second later still said 22,856 / 69,124.
    #
    # Skipping the bar is safe in both directions: if the account really has
    # emptied there is nothing left to sell anyway, and if it has not, the next
    # bar re-reads and carries on.
    if not pos and S.pos_ever:
        if not S.pos_empty_said:
            S.pos_empty_said = True
            log("!! ALERT POSITION query returned no rows for ANY target while"
                " %d name(s) were held moments ago. Treating it as a failed read,"
                " NOT as a cleared account, and skipping this bar." % S.pos_ever)
        return
    if pos:
        S.pos_ever = len(pos)
        S.pos_empty_said = False
    # NOTE: sold_disagree / sold_lonely are initialised in init(), NOT here.
    # They were here too until 2026-08-31, and _run_sells runs once a bar, so
    # every bar wiped the dedupe and 688800.SH re-alerted every minute while it
    # was filling normally.
    sold = _sold_today(C)
    if sold is None:
        log("!! DEAL query unavailable -> cannot tell what we already sold."
            " Skipping this bar rather than risk selling twice.")
        return
    # Floor `sold` with what the position actually lost since this morning. The
    # DEAL query is authoritative WITHIN one run of the terminal and blind to
    # everything before a restart; the baseline covers exactly that blind spot.
    # max(), not replace: DEAL is the finer-grained of the two intraday, and the
    # baseline can only under-report (never over-report) our own selling.
    # HOW MUCH HAVE WE SOLD TODAY -- three independent answers, cross-checked.
    #
    # Each source has been wrong on its own this week, and each is wrong in a
    # different way, which is exactly what makes them worth comparing:
    #
    #   DEAL query      asks the counter what the ACCOUNT traded. Over-reported
    #                   688800.SH by 5,756 on 2026-08-28 and comes back empty
    #                   after a restart.
    #   position        asks the counter what the account HOLDS. Read negative
    #                   all afternoon on 08-27, zero for every name at 10:48 on
    #                   08-26, and twice the holding most days.
    #   our fill record a line per order, written from the broker's report on
    #                   THAT order, kept on disk. Independent of both queries.
    #
    # On a healthy account all three agree and this is silent. When they do not,
    # two agreeing outvote one, and the odd one out is reported rather than
    # quietly used. This replaces three separate patches that each tried to
    # decide, on its own, which single source to believe.
    # OUR OWN FILLS, from the file AND from the counter's order list.
    #
    # The file is lost to a restart in LIVE mode, where a pre-existing file
    # cannot be opened; the order list is not, and carries the same per-order
    # numbers. Take the LARGER per name -- neither source can over-report,
    # since both are per-order traded quantities rather than an aggregate, so
    # the larger is just the more complete one. The file may still hold orders
    # the counter has dropped from its list, which is why it is kept.
    _mine_all = dict(_fills_from_disk(_today_str()))
    for _c, _q in _fills_from_orders().items():
        if _q > _mine_all.get(_c, 0):
            _mine_all[_c] = _q
    base = _load_or_snapshot_baseline(pos)
    for code in SELL_TARGETS:
        v, _cu, _ye = pos.get(code, (0, 0, 0))
        _deal = int(sold.get(code, 0))
        cand = [("deal", _deal)]
        if code in _mine_all:
            cand.append(("ours", int(_mine_all[code])))
        # The position only speaks when it is saying something possible. This
        # strategy sells what it opened the day holding and can never go short.
        if int(v) >= 0 and int(base.get(code, 0)) > 0:
            cand.append(("position", int(base.get(code, 0)) - int(v)))
        vals = [x[1] for x in cand]
        if len(vals) >= 3:
            # Median: two that agree carry it, and an outlier on either side is
            # discarded. 08-28's {deal 50000, ours 44244, position 44244} gives
            # 44244, and a post-restart {deal 0, ours 44244, position 44244}
            # gives 44244 too -- the two failure modes point opposite ways and
            # the middle value survives both.
            agreed = sorted(vals)[1]
        elif len(vals) == 2:
            # Nothing to break the tie, so take the lower. Understating means we
            # keep offering stock we may no longer hold, which costs a rejected
            # order; overstating means we stop with stock still in the account,
            # which is what left 6,956 shares overnight on 08-28.
            agreed = min(vals)
        else:
            agreed = vals[0]
        # ---- IS THE COUNTER CONTRADICTING ITSELF? -----------------------
        # Not a vote between three estimates -- an IDENTITY that must hold if
        # the counter is healthy:
        #
        #     opening holding - held now  ==  sum of per-order fills  ==  DEAL
        #
        # 2026-08-31 it held exactly for 600050/600283/601318 and broke by
        # 1,111 shares on 688800.SH, where DEAL claimed 50,000 against 48,889
        # of per-order fills. Same counter, same second, two answers.
        #
        # The fill record trails a fill by one bar, so an instantaneous
        # equality test would fire on every name that is trading. A lag closes
        # by itself within a bar or two; a contradiction does not -- 688800's
        # gap stood from 13:59 to the close. So only a gap that SURVIVES
        # several bars is reported.
        _by_src = dict(cand)
        if "ours" in _by_src and "position" in _by_src:
            _gap = abs(_by_src["position"] - _by_src["ours"])
            _prev_gap, _n_bars = S.gap_seen.get(code, (0, 0))
            if _gap <= 0:
                S.gap_seen[code] = (0, 0)
            elif _gap >= _prev_gap:
                S.gap_seen[code] = (_gap, _n_bars + 1)
                if _n_bars + 1 >= COUNTER_GAP_BARS and code not in S.gap_said:
                    S.gap_said.add(code)
                    log("!! COUNTER INCONSISTENT %s: the account says %d sold"
                        " (opened %d, holds %d) but our per-order fills total"
                        " %d -- a gap of %d that has not closed in %d bars."
                        " DEAL says %d. This name's sold count is unreliable;"
                        " retirement and the auction size from the holding."
                        % (code, _by_src["position"],
                           int(base.get(code, 0)), int(v), _by_src["ours"],
                           _gap, _n_bars + 1, _by_src["deal"]))
            else:
                S.gap_seen[code] = (_gap, 0)   # shrinking -> it is the lag
        _spread = max(vals) - min(vals)
        # The fill record is written when a fill is DETECTED, which is the bar
        # after it happened, so on any name that is actively filling `ours`
        # trails the other two by exactly one slice. Measured 2026-08-31:
        # {deal 556, ours 278, position 556} then {deal 833, ours 556,
        # position 833} -- it catches up every bar and is never equal.
        #
        # That is a known lag, not a disagreement, and it would otherwise alert
        # for every filling name on every bar and bury the real thing. The
        # 08-28 fault points the OTHER WAY -- {deal 50000, ours 44244,
        # position 44244}, deal high with the other two agreeing -- so the two
        # shapes are distinguishable and that one still alerts.
        _by = dict(cand)
        _lag = (len(vals) >= 3 and "ours" in _by and "position" in _by
                and _by["deal"] == _by["position"] and _by["ours"] < _by["deal"])
        if _lag:
            if code not in S.sold_lagged:
                S.sold_lagged.add(code)
                log("  NOTE %s: the fill record trails by one slice (deal %d,"
                    " ours %d, position %d) -- expected, it is written when a"
                    " fill is detected. Using %d."
                    % (code, _by["deal"], _by["ours"], _by["position"], agreed))
        elif _spread > 0 and code not in S.sold_disagree:
            S.sold_disagree.add(code)
            log("!! ALERT %s: the three sold estimates disagree -- %s. Using %d."
                " %s" % (code, ", ".join("%s %d" % kv for kv in cand), agreed,
                         "Only one source available, so this is unchecked."
                         if len(vals) < 2 else
                         "Two agree; the outlier is not being used."))
        elif len(vals) == 1 and code not in S.sold_lonely:
            S.sold_lonely.add(code)
            log("!! ALERT %s: only the DEAL query is available for the sold"
                " count (position %d, no fill record yet). Nothing to check it"
                " against." % (code, int(v)))
        sold[code] = agreed
    pend = _pending_and_cancel(C, today, hhmmss)
    if pend is None:
        return

    if not S.plan_shown:
        S.plan_shown = True
        _report_plan(pos, sold, pend)

    denom = float(_sess_min(SELL_END)) or 1.0
    frac = min(1.0, _sess_min(hhmmss) / denom)
    # finishing == "the schedule is over, the target is the whole position".
    # True for RUSH and everything after it, so the min-slice and cap relaxations
    # that used to start at 14:57 now start at 14:00.
    finishing = hhmmss >= SELL_END
    # TWAP position is a SCHEDULE question -> bar time. The three end-of-day
    # boundaries are EXCHANGE-CLOCK questions (may I still trade continuously,
    # may I still cancel, is the auction open) -> wall clock. Mixing the two is
    # what put the 2026-08-24 auction batch into the continuous session.
    _wall = _wall_hhmmss()
    phase = ("TWAP" if hhmmss < SELL_END else
             "RUSH" if _wall < RUSH_END else
             "CANCEL" if _wall < AUCTION_AT else "AUCTION")
    if phase != S.phase_said:
        S.phase_said = phase
        log("  PHASE -> %s (bar %s)" % (phase, hhmmss))

    if phase == "CANCEL":
        # One bar with a single job: get the book clean before the auction opens,
        # because after 14:57 the exchange will not let us cancel at all.
        # _pending_and_cancel already ran above and pulled everything (it sees
        # the same phase), so there is nothing else to do this bar. Sending a
        # continuous-session order now would just have to be cancelled again.
        return

    if phase == "AUCTION":
        _run_auction(C, pos, sold, pend, hhmmss)
        return

    # Why each name did nothing this bar. Four paths below `continue` without a
    # word, so a total stall and "correctly nothing to do" produce the SAME
    # empty log. On 2026-08-03 the script sent no order for fourteen minutes
    # across two restarts and the log could not say which it was -- the whole
    # afternoon's diagnosis stalled on a missing print, not on a missing fact.
    idle = []

    for code in sorted(SELL_TARGETS):
        if code in S.done or code in S.gave_up:
            continue
        tgt = SELL_TARGETS[code]
        v, cu, _ye = pos.get(code, (0, 0, 0))
        s = sold.get(code, 0)
        cu, _alert, _akind = _effective_can_use(code, v, cu, _ye, s,
                                                pend.get(code, 0))
        _cu_alert(code, _alert, _akind)
        # Two hard caps: what is ours, and what the broker will release.
        #
        # `pend` belongs in this sum. Shares sitting in a resting order have
        # already been FROZEN out of can_use by the broker, so leaving them out
        # here charges for them twice: once by shrinking `allowed` (and with it
        # twap_qty), and again when `delta` subtracts pend below. The more
        # orders are working, the smaller the next slice is allowed to be --
        # which is backwards, and self-reinforcing once orders stop clearing.
        #
        # 2026-08-03 13:26, every name in the basket was frozen out this way:
        #   300363.SZ twap 8187, sold 5350, pend 3000  -> delta -163
        #   601398.SH twap 1613, sold    0, pend 4300  -> delta -2687
        #   688800.SH twap 15461, sold   0, pend 20854 -> delta -5393
        # Nothing was sent for twenty minutes across three restarts. With pend
        # in the sum, 300363.SZ's allowed goes 13,200 -> 16,200 and its delta
        # goes -163 -> +1,697.
        #
        # Pending shares are still ours: they either fill (moving into `s`) or
        # come back (moving into `cu`). Counting them is what makes `allowed`
        # mean "how much of the target we may end up having sold".
        allowed = min(tgt, s + max(0, cu) + pend.get(code, 0))
        remaining = allowed - s
        if remaining <= 0:
            if s >= tgt:
                # RETIRE ON THE HOLDING, NOT ON `s`.
                #
                # `s` is an ESTIMATE -- the median of three sources, every one
                # of which has been wrong this month. Retiring on it is
                # irreversible: the name leaves this loop AND the closing
                # auction skips S.done, so one over-reported number ends the
                # day for that stock.
                #
                # 2026-08-31 13:59:59, on the counter's word alone:
                #     DONE 688800.SH sold 50000/50000
                #     DONE 601398.SH sold  8500/8500
                #     DONE 600981.SH sold  5000/5000
                # while the account still held 1,111 + 100 + 100 shares. All
                # three went overnight.
                #
                # "Is there stock left?" is a FACT. "Have I sold enough?" is
                # arithmetic over suspect inputs. The failure modes are not
                # symmetric either: a holding that over-reads costs one
                # rejected order, which is free, while an over-reported `s`
                # costs an unsold position.
                #
                # v < 0 is oversold, which is also finished. And the
                # empty-position guard earlier has already returned for this
                # bar if the query gave nothing, so v here is a real reading.
                if v > 0:
                    idle.append("%s says sold %d/%d but %d shares are still"
                                " held -- NOT retiring" % (code, s, tgt, v))
                else:
                    log("  DONE %s sold %d/%d (holding %d)" % (code, s, tgt, v))
                    S.done.add(code)
                continue
            # SHORT OF TARGET WITH NOTHING AVAILABLE -- retry, do not retire.
            #
            # can_use_volume is a SNAPSHOT. Retiring a name on one reading of it
            # assumes the block is permanent, which is true for a genuine short
            # offset and false for everything else: shares locked in an order
            # that has not settled its cancel, a counter that has not refreshed
            # after an overnight reset, a position query that simply lags.
            #
            # 2026-08-26 09:44, the first bar after a restart: 600968.SH read
            # can_use 0 against a net position of 1,000 and was marked DONE at
            # 0/1000 on the spot. Every other name on the same account was
            # reporting can_use at TWICE its position in the same query, so the
            # number was plainly unreliable in both directions -- and the one
            # name it happened to under-report was written off for the day.
            #
            # Retrying is free: with cu at 0 the sizing below yields 0, so the
            # name simply idles and no junk order goes out. If can_use ever
            # comes back, the schedule picks it up where it left off. Only the
            # end-of-day give-up should retire a name for good.
            if S.no_avail_said.get(code) != cu:
                S.no_avail_said[code] = cu
                log("  NO AVAIL %s sold %d/%d -- can_use %d against net position"
                    " %d. Holding the name open and re-checking each bar; a"
                    " genuine short offset stays at 0 and costs nothing to"
                    " re-read." % (code, s, tgt, cu, v))
            continue

        q = _bar(C, code, today, hhmmss)
        if q is None:
            idle.append("%s NO-BAR" % code)
            continue                       # no completed print yet; wait

        sealed_dn, why_dn = _sealed_down(C, code, q)
        if sealed_dn:
            if code not in S.sealed_said:
                S.sealed_said.add(code)
                log("  LIMIT-DOWN %s -> cannot sell (%s)" % (code, why_dn))
            idle.append("%s limit-down" % code)
            continue                       # locked at the floor, cannot sell
        elif code in S.sealed_said:
            S.sealed_said.discard(code)
            log("  LIMIT-DOWN RELEASED %s -> resuming (%s)" % (code, why_dn))

        twap_qty = int(round(allowed * frac))
        # Anything we sent that the broker has not shown us yet counts as
        # pending too. Without this a stale ORDER/DEAL view makes the script
        # believe a slice was never sent and size the next one from scratch.
        delta = twap_qty - s - pend.get(code, 0) - S.unconfirmed.get(code, 0)
        if delta <= 0:
            idle.append("%s ahead-of-plan (twap %d, sold %d, pend %d)"
                        % (code, twap_qty, s, pend.get(code, 0)))
            continue
        if delta < MIN_SELL_SHARES and not finishing:
            idle.append("%s delta %d < %d" % (code, delta, MIN_SELL_SHARES))
            continue

        # The cap is NEVER dropped in the continuous session now. It used to be,
        # from 14:57, on the theory that a thin name would otherwise never
        # finish -- but leftovers now go into the closing auction instead, so
        # there is no reason to take an unbounded bite of a quiet book at 14:56.
        # RUSH widens the cap from 10% to 30%; it does not remove it.
        _part = PARTICIPATION_RUSH if phase == "RUSH" else PARTICIPATION
        cap = int(_part * int(q["volume"]) * VOL_LOT_TO_SHARES)
        qty = _round_sell(code, min(delta, cap), remaining, v)
        # Only blame the participation cap when it actually bound. A slice of
        # 219 becoming 200 on the main board is the 100-share step, not the cap
        # -- reporting that as CAPPED alongside "prev bar 15448 lots" reads as
        # though liquidity were the constraint when the cap was 154,480 shares
        # and never came close.
        if 0 < qty < delta:
            if cap < delta:
                log("  CAPPED %s want %d -> %d (%s cap %.0f%%, prev bar %d lots"
                    " = %d shares)" % (code, delta, qty, phase, _part * 100,
                                       int(q["volume"]), cap))
            else:
                log("  LOT-ROUNDED %s want %d -> %d (step %d)"
                    % (code, delta, qty, _lot_step(code)))
        if qty <= 0:
            # A remainder below the minimum lot that cannot use the odd-lot
            # exception can never be sold. Say so once and stop retrying, rather
            # than spinning on it until the close.
            if remaining < _min_lot(code) and v > remaining and finishing:
                log("  UNSELLABLE %s %d shares left: below the %d-share minimum"
                    " and the position (%d) is not being flattened"
                    % (code, remaining, _min_lot(code), v))
                S.done.add(code)
            else:
                idle.append("%s rounded to 0 (delta %d, cap/lot)" % (code, delta))
            continue

        wide, info = _spread_wide(C, code, hhmmss)
        if wide:
            log("  WIDE SPREAD skip %s %s -> retry next bar" % (code, info))
            continue

        # Progress check: an order that neither fills nor rests would otherwise
        # be re-sent every bar forever.
        # Real clock, matching _age_waiting: bar time is not monotonic with wall
        # time (a PC suspend makes it jump) and would age this out instantly.
        now_t = dt.datetime.utcnow()
        if s > S.progress.get(code, -1):
            S.progress[code] = s
            S.attempts[code] = 0
            S.dry_since[code] = now_t
        elif pend.get(code, 0) > 0:
            # The order reached the book and is resting. Not a junk order, so it
            # must not burn the junk-order budget; only the two-hour dry-spell
            # test may retire this name.
            S.attempts[code] = 0
        tries = S.attempts.get(code, 0)
        # An account-registration refusal is not a junk order. Exempt the name
        # rather than raise the ceiling: the budget exists to stop a name that
        # the MARKET will not take, and 250253 never reaches the market.
        if S.reject_acct.get(code, 0) > 0 and tries >= MAX_ORDER_ATTEMPTS:
            if code not in S.acct_reject_said:
                S.acct_reject_said.add(code)
                log("  NOTE %s: %d order(s) refused with 250253 (account"
                    " registration, not availability). NOT counting them against"
                    " the %d-order budget -- it is refused before the market"
                    " sees it, so retrying is free and it may clear intraday."
                    % (code, S.reject_acct[code], MAX_ORDER_ATTEMPTS))
            S.attempts[code] = 0
            tries = 0
        if tries >= MAX_ORDER_ATTEMPTS:
            log("  GIVE UP %s after %d orders that never reached the book"
                " (sold %d/%d)" % (code, tries, s, tgt))
            S.gave_up[code] = s
            continue
        since = S.dry_since.setdefault(code, now_t)
        dry_min = (now_t - since).total_seconds() / 60.0
        if dry_min >= NO_FILL_GIVEUP_MIN_BY_MODE[_price_mode(code)]:
            log("  GIVE UP %s after %.0f min with no fill (%d orders, sold %d/%d)"
                % (code, dry_min, tries, s, tgt))
            S.gave_up[code] = s
            continue

        # Blocked by the account-registration fault: keep trying, because it
        # is intermittent and might clear, but not once a MINUTE. Every attempt
        # is refused before it reaches the market, so the only cost is log
        # noise -- and 240 bars x 3 names would be 700 lines that bury whatever
        # else went wrong. Every ACCT_REJECT_RETRY_MIN is often enough to catch
        # a recovery well inside the session.
        _ar = S.acct_reject_at.get(code)
        if _ar is not None and (_sess_min(hhmmss) - _ar) < ACCT_REJECT_RETRY_MIN:
            idle.append("%s 250253-blocked, retrying in %d min"
                        % (code, ACCT_REJECT_RETRY_MIN - (_sess_min(hhmmss) - _ar)))
            continue
        if _in_settle():
            idle.append("%s settling after restart" % code)
            continue
        log("  sizing %s sold %d pend %d allowed %d twap %d -> sell %d (try %d)"
            % (code, s, pend.get(code, 0), allowed, twap_qty, qty, tries + 1))
        # Sealed limit-UP: the bid queue at the ceiling is enormous and there is
        # no ask for QUEUE to quote at. Price it AT THE CEILING instead. A limit
        # sell can never execute BELOW its own limit, and the ceiling is the
        # highest price the day permits -- so this fills at the ceiling or not
        # at all, and a false positive costs nothing but an unfilled order that
        # the next bar pulls. Deliberately not the counterparty price: prType 14
        # resolves bid-1 as the order lands, so a board unsealing in that
        # instant would have us hitting bids BELOW the ceiling.
        _su, _ceil = _sealed_up_sell(C, code, q)
        if _su:
            if code not in S.sealed_up_said:
                S.sealed_up_said.add(code)
                log("  SEALED LIMIT-UP %s -> selling AT THE CEILING %.2f"
                    " (no ask to queue behind; a limit there cannot fill lower)"
                    % (code, _ceil))
            _cr = "%s_%s_%s" % (STRATEGY, code.replace(".", ""), hhmmss)
            S.ceiling_orders[_cr] = _ceil
            if _order_sell(C, code, qty, hhmmss, limit_px=_ceil):
                S.attempts[code] = tries + 1
            continue
        if code in S.sealed_up_said:
            S.sealed_up_said.discard(code)
            log("  LIMIT-UP RELEASED %s -> back to %s" % (code, _price_mode(code)))
        if _order_sell(C, code, qty, hhmmss):
            S.attempts[code] = tries + 1

    if idle:
        log("  idle %s: %s" % (hhmmss, " | ".join(idle)))


# ------------------------------------------------------------- QMT hooks -----
def init(C):
    S.runlog = None
    S.tradelog = None
    S.runlog_dir = LOG_DIR
    S.done = set()
    S.gave_up = {}
    S.attempts = {}         # kept for the log only; the give-up test is time-based
    S.progress = {}
    S.dry_since = {}        # code -> utcnow() of the last fill (or first order)
    S.order_time = {}
    S.order_real_time = {}   # remark -> utcnow() at submission
    S.waiting = {}
    S.unconfirmed = {}
    S.last_acted_bar = None
    S.rejected_seen = set()
    S.cancel_inflight = set()
    S.cancel_sent = {}      # remark -> utcnow() of the last cancel we sent
    S.cx_tries = {}         # remark -> cancels sent that changed nothing
    S.cx_sig = {}           # remark -> (status, left) when the last cancel went
    S.cx_first = {}         # remark -> utcnow() of the first such cancel
    S.zombies = set()       # remarks the counter will not let us cancel
    S.no_avail_said = {}    # code -> the can_use last reported as zero
    S.cu_said = {}          # code -> last can_use anomaly reported
    S.cu_alerts = []        # (time, code, why) for the closing summary
    S.cu_notes = []         # ...and the ones already diagnosed
    S.cu_fb_on = set()      # codes whose slices are currently fallback-sized
    S.cu_fb_rejects = {}    # code -> fallback orders the exchange refused
    S.cu_fb_off = set()     # codes where the fallback has been switched off
    S.pos_ever = 0          # how many target rows the POSITION query last had
    S.pos_empty_said = False
    S.sold_disagree = set() # codes whose three sold estimates diverged
    S.sold_lonely = set()   # codes with only one usable sold estimate
    S.sold_lagged = set()   # ...and the ones showing the known fill-record lag
    S.gap_seen = {}         # code -> (gap, bars it has persisted)
    S.gap_said = set()      # codes already reported as counter-inconsistent
    S.reject_acct = {}      # code -> count of 250253 account-registration refusals
    S.acct_reject_said = set()   # codes already told about the exemption
    S.acct_reject_at = {}   # code -> bar minute of its last 250253 refusal
    S.fill_px = {}          # code -> [shares, sum(shares*price)]
    S.price_mode = None     # default mode; set on the first refresh
    S.mode_by_code = {}     # per-name overrides read from PRICE_MODE_FILE
    S.phase_said = ""       # last phase announced, so PHASE logs once
    S.auction_done = False  # the closing-auction batch goes out exactly once
    S.stale_bar_said = ""   # last bar label we complained about, to log once
    S.exec_open = {}
    S.execfh = None
    S.exec_orphans = set()  # orders recorded without a local record, once each
    S.fillfh = None         # ONE handle for the day, like execfh.
                            # Opening per record is what emptied
                            # the fill record on 2026-09-01: the
                            # sandbox takes the open that CREATES
                            # a file and refuses every open of one
                            # that already exists.
    S.fillfh_day = ""
    S.execfh_day = ""
    S.runlog_day = ""
    S.tradelog_day = ""
    S.tradelog_path = ""
    S.tradelog_retry = None   # last open() attempt, for the retry cooldown
    # NOT CLOSE_DATE. Seeding it with the hand-edited constant would name every
    # file after a stale value the moment someone forgets to update it -- the
    # one failure _today_str() exists to rule out. Empty means "no bar yet", so
    # _today_str() falls back to the Beijing wall clock, which is correct.
    S.today_str = ""
    S.dn_cache = {}
    S.up_cache = {}
    S.pend_released = set()   # sells released from pend after the backstop
    S.sealed_up_said = set()  # codes reported as sealed limit-up while selling
    S.ceiling_orders = {}     # remark -> ceiling price, for orders priced there
    S.dn_said = set()       # codes already warned about a missing limit-down
    S.sealed_said = set()   # codes currently reported as limit-down sealed
    S.tick_ok = {}
    S.pos_dumped = False
    S.order_dumped = False
    S.deal_dumped = False
    S.plan_shown = False
    S.baseline = None         # code -> holding at the start of today
    S.universe_set = False
    S.pos_rows = 0
    S.stopped = False
    S.checked = False
    S.said_wait = False
    S.said_passed = False
    try:
        S.acct = account
        S.acct_type = accountType
    except NameError:
        S.acct = ""
        S.acct_type = "STOCK"
    # 24 = sell for a normal stock account; 34 is the credit-account equivalent.
    S.sell_code = 24 if S.acct_type == "STOCK" else 34
    try:
        C.set_universe(["000001.SZ"])
    except Exception:
        pass
    log("=" * 74)
    log("INIT sell-close | CLOSE_DATE %s (retry to %s) | account %r %s"
        % (CLOSE_DATE, CLOSE_UNTIL, S.acct, S.acct_type))
    # REFUSE TO RUN AGAINST AN ACCOUNT THIS BASKET WAS NOT WRITTEN FOR.
    # Checked here, at init, so a wrong binding is caught before the first bar
    # rather than after the first order. S.blocked makes handlebar a no-op.
    # Wall clock at init, for the settle window below. Real seconds, not bar
    # minutes: bar time is not monotonic with the clock and a restart is
    # precisely when the two disagree most.
    S.session_started = _wall_hhmmss()
    S.session_in_hours = ("092500" <= S.session_started <= "150000")
    S.settle_said = False
    if S.session_in_hours:
        log("  RESTART SETTLE: this session began during trading hours, so it"
            " will observe for %.0fs before sending anything. An order placed"
            " just before a restart is in neither memory nor the counter's"
            " order list until it is acknowledged." % RESTART_SETTLE_SEC)
    S.blocked = False
    if ALLOWED_ACCOUNTS and str(S.acct) not in ALLOWED_ACCOUNTS:
        S.blocked = True
        log("  " + "!" * 70)
        log("  !! WRONG ACCOUNT. This script is bound to %r, but the basket"
            " below belongs to %s." % (S.acct, ", ".join(ALLOWED_ACCOUNTS)))
        log("  !! NOTHING WILL BE SOLD. Re-bind the strategy to the right"
            " account, or edit ALLOWED_ACCOUNTS if the binding is correct.")
        log("  " + "!" * 70)
    # WHERE THE FILES ACTUALLY WENT. The chooser prints this to the QMT console
    # only, which is not where anyone looks afterwards -- on 2026-09-01 the log
    # had fallen back two directories and finding it meant searching the disk.
    # Every other record (exec, trades, fills, baseline) is anchored on the same
    # directory, so this one line says where the whole session's evidence is.
    log("  FILES -> %s%s" % (getattr(S, "runlog_dir", "?"),
                             "" if getattr(S, "runlog_dir", None) == LOG_DIR
                             else "   <-- NOT the configured LOG_DIR (" + LOG_DIR + ")"))
    log("  TWAP %s-%s | participation %.2f | min slice %d shares | targets"
        " %d names %d shares"
        % (SELL_START, SELL_END, PARTICIPATION, MIN_SELL_SHARES,
           len(SELL_TARGETS), sum(SELL_TARGETS.values())))
    # Report the price mode at INIT, not only on the first trading bar.
    # _run_sells polls the file, but the date gate returns before it on any day
    # that is not CLOSE_DATE, leaving no way to confirm which pricing is armed
    # while there is still time to change it.
    _refresh_price_mode()
    if not S.acct:
        log("  !! NO ACCOUNT BOUND -- bind one in the model-trading dialog."
            " Nothing can be queried or sent until you do.")
    log("=" * 74)


def _ensure_universe(C):
    if S.universe_set:
        return
    codes = list(SELL_TARGETS)
    codes.append("000001.SZ")
    try:
        C.set_universe(sorted(set(codes)))
    except Exception:
        pass
    S.universe_set = True


def handlebar(C):
    if S.stopped:
        return
    # Wrong account -> do nothing, ever. Re-stated once a session so the log
    # cannot be mistaken for a quiet market.
    if getattr(S, "blocked", False):
        if not getattr(S, "blocked_said", False):
            S.blocked_said = True
            log("!! ALERT bound to account %r which is not in ALLOWED_ACCOUNTS"
                " -- this script will not trade today" % (S.acct,))
        return
    try:
        if not C.is_last_bar():
            return
    except Exception:
        pass
    today, hhmmss = _bar_datetime(C)

    if today < CLOSE_DATE:
        if not S.said_wait:
            S.said_wait = True
            log("WAIT: bar date %s is before CLOSE_DATE %s -- standing by"
                % (today, CLOSE_DATE))
        return
    if today > CLOSE_UNTIL:
        if not S.said_passed:
            S.said_passed = True
            log("PASSED: bar date %s is after CLOSE_UNTIL %s -- nothing to do"
                % (today, CLOSE_UNTIL))
        return
    if hhmmss < SELL_START:
        return                              # keeps out of the opening auction
    if hhmmss > "150000":
        return
    # The bar must be CURRENT. QMT hands a restarting strategy the last bar it
    # has, and that bar's label alone passes every test above.
    #
    # 2026-08-03, restarted at 12:56 during the lunch break: the newest bar was
    # 113000, which sits inside SELL_START..SELL_END, so the schedule was built
    # and ELEVEN orders went out into a closed market -- priced at 11:30's
    # counterparty quote, to be released at 13:00 against whatever the market
    # had become. The same morning, a bar labelled 093000 arrived at 08:53 and
    # was only harmless because the TWAP fraction was still zero.
    #
    # Compare against the Beijing wall clock, not against the session: during
    # the lunch break _sess_min clamps both 11:30 and 12:56 to the same 120, so
    # a session-minute test cannot see this at all. Raw minutes-of-day can.
    _bar_mod = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    _wall = dt.datetime.utcnow() + dt.timedelta(hours=8)
    _wall_mod = _wall.hour * 60 + _wall.minute
    if abs(_wall_mod - _bar_mod) > STALE_BAR_MAX_MIN:
        if S.stale_bar_said != hhmmss:
            S.stale_bar_said = hhmmss
            log("STALE BAR %s vs Beijing %s (%d min apart) -- not trading."
                " Market is closed or the feed is behind; waiting for a live bar."
                % (hhmmss, _wall.strftime("%H:%M:%S"), abs(_wall_mod - _bar_mod)))
        return
    if not S.acct:
        return
    if not S.checked:
        S.checked = True
        if not _validate():
            S.stopped = True
            return
        log("ACTIVE: %s %s | building the sell schedule" % (today, hhmmss))
    _ensure_universe(C)

    # Act ONCE per bar. handlebar fires on every tick of the forming bar, not
    # once a minute. Without this gate the strategy re-ran roughly every second
    # on 2026-07-30 and, because a fresh order takes several seconds to appear
    # in the ORDER query, every pass read `sold 0 pend 0` and sent the slice
    # again -- six duplicate orders per name in twelve seconds before
    # MAX_ORDER_ATTEMPTS stopped it. The buy script has carried this same gate
    # since it was written; it was lost porting the sell logic across from the
    # miniQMT version, which paces itself with its own sleep loop instead.
    if hhmmss == S.last_acted_bar:
        return
    S.last_acted_bar = hhmmss

    # Second line of defence: never size a new slice while an order we just sent
    # has not yet been seen by the broker. Aged out on the REAL clock after
    # UNCONFIRMED_TIMEOUT_SEC so a rejected order cannot freeze the strategy.
    if not _reconcile_waiting(C, hhmmss):
        log("  waiting for %d unconfirmed order(s) -> no new slice this bar: %s"
            % (len(S.waiting),
               ", ".join("%s %d" % (v[0], v[1]) for v in S.waiting.values())))
        return

    try:
        _run_sells(C, today, hhmmss)
    except Exception as e:
        log("!! run_sells error: " + repr(e))
    if len(S.done) + len(S.gave_up) >= len(SELL_TARGETS):
        if not S.stopped:
            S.stopped = True
            log("all names finished or abandoned")
            _summary()


def _summary():
    log("=" * 74)
    log("SUMMARY sell-close " + CLOSE_DATE)
    sold = None
    try:
        sold = _sold_today(None)
    except Exception:
        sold = None
    if sold is None:
        sold = {}
    tot_t = tot_s = 0
    for c in sorted(SELL_TARGETS):
        s = sold.get(c, 0)
        t = SELL_TARGETS[c]
        tot_t += t
        tot_s += s
        flag = "" if s >= t else "   UNSOLD %d" % (t - s)
        log("  %-11s sold %6d / %6d%s" % (c, s, t, flag))
    log("  total %d / %d shares" % (tot_s, tot_t))
    if getattr(S, "fill_px", None):
        # Quantity-weighted, per name and overall. Compare against the session
        # VWAP for the same window to score the schedule, not just the orders.
        log("  achieved average price (quantity-weighted):")
        _tq = 0
        _tn = 0.0
        for _c in sorted(S.fill_px, key=lambda k: -S.fill_px[k][0]):
            _q, _nt = S.fill_px[_c]
            if _q <= 0:
                continue
            _tq += _q
            _tn += _nt
            log("    %-11s %7d shares @ %.4f" % (_c, _q, _nt / _q))
        if _tq:
            log("    %-11s %7d shares, notional %.2f (blended %.4f)"
                % ("ALL", _tq, _tn, _tn / _tq))
    if S.gave_up:
        log("  abandoned: %r" % (S.gave_up,))
    if tot_s < tot_t:
        log("  unsold names roll to the next session (CLOSE_UNTIL %s)" % CLOSE_UNTIL)
    # The day cannot end without these being seen. Bad broker data is the one
    # class of fault the script cannot fix from inside, so it has to leave the
    # building attached to the result rather than buried mid-log.
    if getattr(S, "cu_notes", None):
        # One line, not one per name. This is a counter defect we understand;
        # it earns a mention so a change in it is visible, not a paragraph.
        log("  note: %d name(s) showed the known overnight-restore can_use"
            " (position + yesterday's sellable, counted twice): %s"
            % (len(S.cu_notes), ", ".join(c for _t, c, _w in S.cu_notes)))
    if getattr(S, "cu_alerts", None):
        log("  " + "!" * 70)
        log("  !! %d can_use ANOMALY(S) TODAY -- the broker's available-quantity"
            " field was not usable and sizing fell back to yesterday's volume:"
            % len(S.cu_alerts))
        for t, code, why in S.cu_alerts:
            log("  !!   %s  %-11s %s" % (t, code, why))
        log("  !! Verify this field on the real account before trading it.")
        log("  " + "!" * 70)
    log("=" * 74)


def stop(C):
    if not S.stopped:
        _summary()
    for h in (getattr(S, "tradelog", None), getattr(S, "runlog", None)):
        try:
            if h:
                h.flush()
                h.close()
        except Exception:
            pass
    print("STOP sell-close")
