#coding:gbk
# ============================================================================
# BUY-OPEN model script  (QMT model trading; no miniQMT / independent-trade perm)
# ----------------------------------------------------------------------------
# Run this on the OPEN day. It TWAP-builds a target basket over 09:30-14:00 with
# rank-fallthrough (shunyan): hold the first SLOTS names; if one cannot fill
# (one-word limit-up till 13:00 / halt / cannot afford one lot) fall through to
# the next name in TARGETS.  Counterparty price (passorder prType=14).  Async
# fills reconciled each bar via positions + open orders; waiting_list prevents
# over-ordering.  ASCII-only + no file IO so it loads in the QMT sandbox.
#
# Account is injected by the model GUI (bind it there); NOT hardcoded.
#
# ############################################################################
# EDIT THIS each rebalance: paste your ranked buy list.
#   - order = rank (best first)
#   - first SLOTS names are the held basket; the rest are fallthrough reserves
# ############################################################################
# --- 2026-09-02 rebalance ---------------------------------------------------
# Source, regenerated 2026-09-02 08:41 Beijing (after a retrain that same
# morning -- the pre-retrain signal is archived as
# _engine_signals_archive/20260901_pre_retrain_20260901_201715.parquet) from
# the 2026-09-01 close:
#   ...forecast_v2\automatically_plan_generate\picks\picks_20260901_all.csv
# NOTE the _v2 directory. Earlier baskets came from the non-v2 one.
#
# There is NO orders_20260901_all.csv this time -- picks/ alone. So the plan's
# own per-name allocation is not available to cross-check against, and
# BUY_BUDGET / SLOTS below is the only sizing input.
#
# Rank order is picks' `rank` column, SORTED. The rows in that file are not in
# rank order where signals tie (rank 3 is written above rank 2, and 6 above 5),
# so reading it top-to-bottom would silently reorder the queue.
#
# 30 names are tagged buy and 20 reserve, same shape as before. We hold the
# top SLOTS=20; ranks 21-50 are fallthrough reserves for a name that cannot be
# filled (limit-up, halted, rejected).
#
# Against the basket this script previously held: the top 20 are the SAME 20
# NAMES, only reordered among themselves -- which changes nothing, since all
# 20 enter the book regardless of the order they are pulled in. All 11
# additions and 11 removals are in the 21-50 reserves, where order is a real
# priority. So this is a reserves-only change.
#
# Four STAR names are in the held 20: 688217, 688357, 688466, 688659 (and
# 688393/688468/688273 sit at 23/25/30). An account without STAR buy
# permission rejects them with [COUNTER][251259] and they fall through to the
# reserves; on an account that has it they trade normally.
SLOTS = 20
# --- 2026-09-02 rebalance ---------------------------------------------
# Source: signals/signal_20260901.csv from the 18-model v2 panel,
# generated 2026-09-01 14:11 from that day's close. Ranked by signal;
# the first SLOTS names are the basket and the rest are fallthrough
# reserves for anything that cannot be filled.
#
# Four STAR names sit in the top twenty (688217, 688357, 688466,
# 688659). Their minimum order is 200 shares against a per-name budget
# of 11,518, so any of them priced above ~57.59 cannot afford one lot
# and will be skipped as unaffordable, falling through to a reserve --
# ten more STAR names are among ranks 21-50, so several may go the same
# way. That is the design working, not a fault.
TARGETS = [
    "603810.SH", "300625.SZ", "301515.SZ", "301298.SZ", "688217.SH", "002732.SZ",
    "300800.SZ", "002381.SZ", "301519.SZ", "688357.SH", "300691.SZ", "301170.SZ",
    "688466.SH", "600463.SH", "603214.SH", "605088.SH", "300673.SZ", "000702.SZ",
    "600620.SH", "688659.SH", "600097.SH", "300732.SZ", "688393.SH", "300500.SZ",
    "688468.SH", "000548.SZ", "003008.SZ", "603982.SH", "603291.SH", "688273.SH",
    "603908.SH", "603826.SH", "301102.SZ", "301009.SZ", "688377.SH", "300949.SZ",
    "603096.SH", "688737.SH", "000952.SZ", "688533.SH", "000590.SZ", "688267.SH",
    "603860.SH", "002016.SZ", "688236.SH", "600051.SH", "301167.SZ", "301429.SZ",
    "002344.SZ", "300644.SZ",
]

# ==== EDIT each rebalance: the trading day (Beijing, YYYYMMDD) to build this basket ====
# today < OPEN_DATE -> stand by (wait);  today == OPEN_DATE -> run buy TWAP;
# today > OPEN_DATE -> declare passed, do nothing.
OPEN_DATE = "20260902"

BUY_START, BUY_END = "093000", "140000"
PARTICIPATION = 0.10            # per bar, at most 10% of that bar's volume
                                # (lowered from 0.20: cost is ~0.03% so we can
                                #  afford to trade slower for less impact)
MIN_ORDER_AMT = 2000.0
LIMIT_UP_CUTOFF = "130000"
NO_TRADE_CUTOFF = "100000"
TICK = 0.01
# ---------------------------------------------------------------- price mode --
# Two ways to price a buy, switchable WHILE THE SCRIPT RUNS:
#
#   COMPETE  prType 14, counterparty price -> lifts the ask. Fills now, pays the
#            half-spread. 2026-08-04 live: 100% filled inside the minute, cost
#            4.8 bp on a 10.37 name and 24.0 bp on a 2.09 one.
#   QUEUE    prType  6, bid-1 price -> posts at the bid and waits. Costs ~0 or
#            better against mid, but may not fill at all.
#
# Read from a one-line text file every bar, so a switch needs a text editor
# rather than a re-paste. The point is state: this script carries a day of it --
# the pre-existing-holdings baseline, per-name sent quantities, the junk-order
# budget, every resting order's timestamp -- and every bit is keyed on STRATEGY.
# Swapping in a second script with a different STRATEGY to change the price
# would restart that bookkeeping with the basket already half built.
PRICE_MODE_FILE = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\price_mode.txt"
# How many numbered instruction files to look for (price_mode1.txt ..).
# EDIT: per-name price mode, applied at paste time and independent of
# price_mode.txt. The file channel is the normal way to do this, but in LIVE
# mode it was unreadable all of 2026-09-01 -- the file predates every session --
# so without this there is no way to make ONE name cross the spread short of
# changing the default for the whole basket.
#
#     MODE_OVERRIDE = {"002573.SZ": "COMPETE"}
MODE_OVERRIDE = {}
PRICE_MODE_MAX_SEQ = 6
PRICE_MODE_DEFAULT = "QUEUE"    # used until the file is read successfully
PRTYPE_BY_MODE = {"COMPETE": 14, "QUEUE": 6}
# The spread filter INVERTS with the mode rather than merely relaxing: it exists
# to avoid crossing a wide touch, and QUEUE crosses nothing, so a wide touch is
# the edge being harvested.
MIN_SPREAD_TICKS_BY_MODE = {"COMPETE": 3, "QUEUE": 0}


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
    txt = None
    try:
        f = None
        _cands = []
        _dirs = []
        _rd = getattr(S, "runlog_dir", None)
        if _rd:
            _dirs.append(_rd)
        for _d in (RUN_LOG_DIR, TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS):
            if _d not in _dirs:
                _dirs.append(_d)
        # Numbered files first, HIGHEST wins: it is the latest instruction, and
        # replaying a lower one would quote the way the operator has just
        # decided not to. Editing price_mode.txt is still tried, and still
        # works wherever a pre-existing file can be opened.
        for _sq in range(PRICE_MODE_MAX_SEQ, 0, -1):
            for _d in _dirs:
                _cands.append(_d + "\\price_mode%d.txt" % _sq)
        for _d in _dirs:
            _cands.append(_d + "\\price_mode.txt")
        if PRICE_MODE_FILE not in _cands:
            _cands.append(PRICE_MODE_FILE)
        txt = None
        for _p in _cands:
            try:
                f = open(_p, "r")
                txt = f.read()
                f.close()
                if _p != getattr(S, "mode_file_said", None):
                    S.mode_file_said = _p
                    print("  price mode file -> " + _p)
                break
            except Exception:
                continue
        if txt is None:
            raise IOError("no readable price mode file")
    except Exception:
        txt = None                  # unreadable -> hold what we have
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
            print("  MODE_OVERRIDE in effect:",
                  ", ".join("%s=%s" % kv for kv in sorted(MODE_OVERRIDE.items())))
        print("  PRICE MODE: %s (prType %d)%s%s"
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
            print("  PRICE MODE default: %s -> %s (prType %d -> %d)"
                % (old_default, new_default,
                   PRTYPE_BY_MODE[old_default], PRTYPE_BY_MODE[new_default]))
        else:
            print("  PRICE MODE %s: %s -> %s"
                % (c, old_per.get(c, old_default), new_per.get(c, new_default)))
    return changed


PRTYPE_COMPETE = 14            # kept for reference; PRTYPE_BY_MODE is what runs
STRATEGY = "combo_buy_dual"
# QMT 1m bar volume for stocks is in LOTS (shou), while orders are in SHARES.
# Verified live: e.g. 600958.SH showed bar volume ~1253 at 10:20 (=125,300 shares).
# Without this the 20% participation cap would be 100x too tight.
VOL_LOT_TO_SHARES = 100
# ############################################################################
# EDIT: how much cash THIS run may deploy in total, across all SLOTS names.
#   per-name budget = BUY_BUDGET / SLOTS   (e.g. 200000 / 20 = 10000 each)
#   Applies to both PREVIEW and LIVE, so what you preview is what you trade.
#   0 -> fall back to the account's total asset. Only safe when the account
#        holds nothing but this strategy: any unrelated holding inflates the
#        total, every slot is sized too big, and you over-invest.
# ############################################################################
BUY_BUDGET = 230356.79

# EDIT: the ONLY account this basket may be BOUGHT into. Same guard as the sell
# script, and it matters more here: a sell script bound to the wrong account
# liquidates something, which is at least visible afterwards; a buy script
# bound to the wrong account SPENDS money there.
#
# Deliberately pinned to the simulation account. 2026-09-01 is a live
# liquidation on 507085 and this script must not run that day at all --
# binding it to 507085 by mistake would start buying back the very basket
# being sold. OPEN_DATE is also left in the past as a second, independent
# stop: even bound correctly, the date gate refuses to trade.
ALLOWED_ACCOUNTS = ("507085",)
# Slot adoption from broker positions is OFF by design (user preference).
# NOTE: this only disables *slot accounting* from positions. LIVE still reads the
# real position of each name for the delta maths -- without that the strategy
# would have no idea what it holds and would re-buy the full target every bar.
# Restart safety: after a mid-day restart the slot bookkeeping is empty, so a
# name bought via fallthrough (rank 21+) would not occupy its slot and the
# strategy would open a full 20 more on top of it. With this on, names THIS run
# already bought (per _own, i.e. net of the baseline) reclaim their slots.
ADOPT_EXISTING_POSITIONS = True
# A-share positions carry no owner tag, so a name this account already holds for
# ANY other reason (last month's leftover, another strategy, a manual trade) looks
# to the delta maths like "I already bought it" -- and the name is then skipped.
# With this on, the open day snapshots the pre-existing holding once and counts
# only what THIS run adds on top, so other holdings are ignored rather than
# absorbed. The snapshot is persisted, because losing it across a restart would
# turn our own fills into "someone else's" and buy the whole target a second time.
# If it cannot be persisted the script falls back to the old absorb behaviour,
# which under-buys but can never double-buy.
IGNORE_PREEXISTING = True
# Local trade log (audit + restart recovery). If the QMT sandbox blocks file IO
# the script says so once and keeps trading -- logging is never fatal.
# Trade log, durable fills and baseline all live under logs/ with everything
# else. They used to be written to the project root, which is why that folder
# filled up with a trades_*.csv and a baseline_*.csv from every session.
TRADE_LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"
# The old location, kept ONLY as somewhere to look. A restart part-way through a
# day whose files were written before this change still has to find them.
LEGACY_DIR = "C:\\QMTGTHT\\local_run\\combo_top20_twap"
# ...and its logs/ subfolder, where they actually lived between
# 2026-08-27 and the move to C:\\AI_STOCK on 2026-08-29.
LEGACY_LOGS = "C:\\QMTGTHT\\local_run\\combo_top20_twap\\logs"
# Full console mirror, next to the sell script's run log so the two can be read
# side by side when both strategies run on the same day.
RUN_LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_twap\\logs"
RESTORE_FROM_LOG = True       # on restart, rebuild what was already bought today
# LIVE only: a counterparty-price order that does not fill (price ran away) would
# otherwise sit in the book forever and stall the TWAP, because the pending qty
# makes the strategy think it is already buying. Cancel it after this many
# minutes; the next bar re-quotes at the fresh counterparty price.
STALE_ORDER_MIN = 5             # fallback only: used when the touch is unreadable
# Minimum age, in BAR minutes, before an order may be cancelled at all.
# Bar minutes, not real seconds: this script acts once per bar, so "one bar" is
# the natural unit, and a real-clock version cannot be exercised offline -- the
# regression replays a whole session in a few real seconds, so every order
# looked newborn and nothing was ever cancelled.
CANCEL_MIN_REST_BARS = 1
# Long backstop, in BAR minutes. An order whose touch genuinely has not moved is
# left to hold its queue slot, but not forever.
CANCEL_BACKSTOP_MIN = 30

# Minimum REAL seconds between two cancels of the SAME order. The sell script
# has had this since 2026-08-03; this script never got it, and on 2026-08-24
# that showed: combo_buy_dual_600533.SH_112400 was cancelled once a minute from
# 13:22 to the close, its age climbing 30, 31, 32 ... while `left 400` never
# moved. 1,769 cancel commands went out against 25 orders. Exchanges police
# cancel rates and the broker records every rejection.
# BAR minutes, not real seconds: a real-clock cooldown cannot be exercised
# offline, where a whole session replays in seconds and every order would get
# exactly one attempt. Live the two measures agree.
CANCEL_COOLDOWN_MIN = STALE_ORDER_MIN

# No cancellation is possible once the closing call auction opens: the exchange
# accepts new orders from 14:57 but refuses every cancel until 15:00. Wall
# clock, not the bar label -- see _wall_hhmmss.
NO_CANCEL_AFTER = "145700"

# The closing call auction opens at 14:57 and clears at 15:00. Anything a slot
# is still short at that moment goes in at the limit-UP price -- see
# _run_auction for why that is not the same as paying limit-up. WALL CLOCK.
AUCTION_AT = "145700"

# --- un-cancellable ("zombie") orders -------------------------------------
# The counter can refuse a cancel outright, with
#     [COUNTER][251020][order status does not allow cancellation]
# leaving the order exactly as it was: same status, same unfilled remainder.
# Our books still call those shares pending, and pending quantity is subtracted
# from every later slice, so one stuck order quietly eats its name's schedule.
#
# 2026-08-24: 25 stuck orders froze 8,341 shares against a 9,151-share
# shortfall -- essentially the entire miss. 600533.SH spent the afternoon on
#     sizing 600533.SH cur 2100 pend 2400 tgt 4600 twap 4600 -> buy 100
# trickling 100 shares a bar because over half its target was locked in orders
# that could neither fill nor die. The basket finished at 65% of target.
#
# A stuck order's cash is still frozen, so dropping it from `pend` does not
# conjure buying power -- the budget check still binds. What it does is stop
# the SCHEDULE from believing that quantity is already working.
#
# The one real risk: if a written-off order later fills after we have replaced
# it, that name overshoots by up to the stuck quantity. Accepted, because `cur`
# is re-read every bar and the next slice self-corrects, and because the
# alternative measured out at a third of the basket left unbought.
# How often a name that is parked may repeat itself, in BAR minutes. Its
# reason rarely changes, but silence is what let four names vanish from the
# 2026-08-25 log without explanation, so a parked name says so periodically.
HOLD_REPEAT_MIN = 30

ZOMBIE_CANCEL_TRIES = 6         # cancels that changed neither status nor remainder
ZOMBIE_MIN_AGE_MIN = 15         # ...spread over at least this many BAR minutes
# Bar minutes, like CANCEL_MIN_REST_BARS and CANCEL_BACKSTOP_MIN, not real
# seconds: a real-clock threshold cannot be exercised offline, where a whole
# session replays in a few seconds and no order is ever old enough. Live, the
# five-minute real cooldown between cancels already makes six tries span half
# an hour, so this is the looser constraint either way.
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
# broker's order list before treating it as rejected. Real seconds, not bar
# minutes: a suspended PC makes bar time jump and would age this out instantly.
# Seconds a session started DURING trading hours must observe before sending.
# Tied to UNCONFIRMED_TIMEOUT_SEC because it answers the same question from the
# other side: that one is how long we wait for the counter to acknowledge an
# order, this is how long a NEW session must wait for the counter to tell it
# about orders it never saw sent.
RESTART_SETTLE_SEC = 95.0
UNCONFIRMED_TIMEOUT_SEC = 90.0
# How long an order we sent may stay invisible to the broker and still
# count as pending. Deliberately far longer than UNCONFIRMED_TIMEOUT_SEC:
# that one decides whether to keep PAUSING the whole script, this one
# decides whether the shares still exist. Releasing early over-buys;
# never releasing stalls the slot -- so there is a backstop either way.
PEND_INVISIBLE_MAX_SEC = 600.0
# Finished order states (xtconstant): 53 part-cancelled, 54 cancelled,
# 56 filled, 57 junk. 53 was missing before -- its unfilled remainder is
# dead, so counting it as pending would block that name for the rest of
# the day. 50/51/52/55 are still live and must stay "pending".
TERMINAL_STATUS = (53, 54, 56, 57)
# Cancel already accepted and working through the exchange: 51 reported-
# cancelling, 52 part-filled-cancelling. Still pending, but re-sending a cancel
# achieves nothing -- the sell script re-cancelled two such orders once a minute
# for half an hour on 2026-07-31 before this was understood.
CANCEL_PENDING_STATUS = (51, 52)
# Statuses the exchange will accept a cancellation for: 50 reported,
# 55 part-filled. NOT 48 (not reported) or 49 (waiting to be reported) --
# those are still inside the counter, and asking to cancel one comes back
# as [COUNTER][251020][order status does not allow cancellation].
CANCELLABLE_STATUS = (50, 55)
# Final top-up may exceed the per-name budget by at most this fraction.
# Only used to close a sub-minimum-lot gap after BUY_END (mainly STAR/BJ,
# where the minimum order is 200 shares).
TOPUP_OVERSHOOT = 0.15
# Give up on a name after this many orders that produced neither a fill nor a
# resting order. Observed 2026-07-29 in sim: 600958.SH was re-ordered every
# minute (102400/102500/102600/102700, same 300 shares) because each order died
# without filling, so cur and pend both stayed 0 and delta never shrank. Without
# a cap that repeats until 14:00 and piles up rejected orders, which exchanges
# do police.
# Budget of consecutive orders that produce NO fill before a name is abandoned.
# The counter resets on any fill, so this measures a dry spell, not total volume.
# Raised from 6 on 2026-07-31: at STALE_ORDER_MIN=5 six attempts is only a
# thirty-minute dry spell, and that abandoned 601398.SH at 600 of 2000 with
# three and a half hours of window left -- its orders were resting and filling,
# just slowly against a thin touch. Twenty attempts is a ~100-minute dry spell
# before giving up, while still capping a genuinely dead name at 20 orders a day
# instead of the 156 that removing the guard produced in the offline run.
MAX_ORDER_ATTEMPTS = 20
# How far the bar label may sit from the Beijing wall clock before the bar is
# treated as stale and NOT acted on. Live, QMT stamps the forming bar with its
# closing minute so the gap stays under a minute; anything larger means a
# restart replaying history, or a shut market.
STALE_BAR_MAX_MIN = 3
# Field surveys were only needed to learn the QMT object layout. The names are
# now known (m_nVolume / m_nCanUseVolume / m_nOnRoadVolume / m_nYesterdayVolume
# / m_bIsToday), so keep the 60-line dumps off unless something needs re-checking.
DEBUG_DUMP_FIELDS = False
# Print EVERY position row for this one code, raw. 600958.SH reported 200 shares
# while ~2300 had filled, yet 600805.SH (no pre-existing lot) reported its 500
# correctly -- so the code either appears on several rows that cancel out, or its
# same-day shares live somewhere m_nVolume does not cover. Set to "" to disable.
DEBUG_CODE = ""
# ---- spread filter ------------------------------------------------------
# A counterparty-price order crosses the spread, so a wide touch is paid in full.
# Standard practice in TWAP algos is to pause the slice and retry next interval.
# A-share tick is a flat 0.01 CNY, so cheap stocks are mechanically wide in bps
# (1 tick on a 4 CNY stock is already 25bp). Require BOTH conditions so a
# minimum-tick spread is never treated as wide.
MAX_SPREAD_BPS = 50.0        # (ask-bid)/mid*10000 above this = wide ...
MIN_SPREAD_TICKS = 3         # ... and at least this many ticks. 0 disables the filter.
SPREAD_GUARD_UNTIL = "144500"   # after this, take what is available and complete

import sys
import datetime as dt


class _State(object):
    pass

S = _State()
S.logfh = None
S.logfh_day = ""

_console_print = print          # the real builtin, captured before shadowing


def print(*args, **kwargs):     # noqa - deliberate module-local shadow
    """Console AND run log, for THIS MODULE only.

    Replacing sys.stdout was the obvious way to mirror every print without
    editing hundreds of call sites, and it worked -- but QMT runs both
    model-trading strategies in ONE Python process, sharing sys.stdout, so on
    2026-07-31 the sell script's output landed in the buy script's log with two
    stacked timestamps. Shadowing the name at module level captures exactly this
    file's prints and leaves every other module alone.

    Never fatal: if the file handle dies, logging switches off and the strategy
    keeps trading.
    """
    _console_print(*args, **kwargs)
    if S.logfh is not None and S.logfh_day != _today_str():
        _start_run_log()
    fh = S.logfh
    if fh is None:
        return
    try:
        sep = kwargs.get("sep", " ")
        fh.write("[" + _china_now() + "] " + sep.join(str(a) for a in args) + "\n")
        fh.flush()
    except Exception:
        S.logfh = None


print("MODULE combo_buy_open imported OK")


# ---- board / lot ----
def _split(code):
    stk, mkt = code.split("."); return stk, mkt.upper()


def _buy_unit(code):
    stk, mkt = _split(code)
    if mkt == "SH" and stk.startswith("688"):
        return (200, 1)
    if mkt == "BJ":
        return (100, 1)
    return (100, 100)


def finishing_window(hhmmss):
    """True once the TWAP schedule is over and every remaining share is a
    genuine shortfall. Before BUY_END a quiet minute means nothing; after it,
    each one is a minute the slot did not get filled in."""
    return hhmmss >= BUY_END


def _round_buy(code, shares):
    mn, step = _buy_unit(code)
    shares = int(shares)
    if shares < mn:
        return 0
    return mn + ((shares - mn) // step) * step


def _board_rate(code):
    """Board limit fraction. NOTE: this is the FALLBACK only -- the real ceiling
    comes from the broker's UpStopPrice, which already accounts for ST. This is
    used when that lookup fails, and it cannot see ST, so it is deliberately the
    WIDE value: a too-wide ceiling means "we never think it is limit-up", i.e.
    we keep trying, which merely wastes orders. A too-narrow one would make us
    skip minutes we could have traded."""
    stk, mkt = _split(code)
    if mkt == "BJ":
        return 0.30
    if mkt == "SH" and stk.startswith("688"):
        return 0.20
    if mkt == "SZ" and (stk.startswith("300") or stk.startswith("301")):
        return 0.20
    return 0.10


def _sess_min(hhmmss):
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    if t <= 690:
        return min(120, max(0, t - 570))
    return min(240, 120 + (t - 780))


def _bar_datetime(C):
    # date/time come from the BAR (exchange time), never the PC clock:
    # this PC may run a non-Beijing timezone, so wall-clock date would be wrong.
    timetag = C.get_bar_timetag(C.barpos)
    china = dt.datetime.utcfromtimestamp(timetag / 1000.0) + dt.timedelta(hours=8)
    return china.strftime("%Y%m%d"), china.strftime("%H%M%S")


def _china_now():
    # Beijing wall clock, timezone-safe (utcnow + 8h); for logging only.
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d %H:%M:%S")


def _wall_hhmmss():
    """Beijing wall clock as HHMMSS -- the real time, not the bar label.

    QMT stamps a forming bar with the minute it CLOSES, so the label runs 1-2
    minutes ahead of the clock. Measured on 2026-08-24: bar 145700 arrived at
    wall 14:55:58. Anything gated on the EXCHANGE's clock -- may I still
    cancel, is the auction open -- has to use this. Schedule position (how far
    through the TWAP we are) still uses bar time, which is its proper clock.

    S.wall_override lets the offline regression reach these branches at all: a
    session replays in seconds of real time, so the true clock never enters the
    afternoon. Never set in live trading.
    """
    ov = getattr(S, "wall_override", None)
    if ov:
        return ov
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%H%M%S")


def _zombie(remark, status, left, now_m):
    """True when this order has refused every cancel we have sent it.

    Called from the order scan, the only place that sees the order's CURRENT
    (status, left). That pair is compared against the one recorded when we last
    sent a cancel: if either has moved, the order is alive -- a fill landed, or
    the cancel took -- so the counter resets and a written-off order comes back.

    See ZOMBIE_CANCEL_TRIES for what this defends against.
    """
    moved = S.cx_sig.get(remark) != (status, left)
    if moved:
        S.cx_tries[remark] = 0
        S.cx_first.pop(remark, None)
        if remark in S.zombies:
            S.zombies.discard(remark)
            print("  ZOMBIE CLEARED", remark, "status/remainder moved, back in the book")
        return False
    if remark in S.zombies:
        return True
    if S.cx_tries.get(remark, 0) < ZOMBIE_CANCEL_TRIES:
        return False
    t0 = S.cx_first.get(remark)
    if t0 is None or (now_m - t0) < ZOMBIE_MIN_AGE_MIN:
        return False
    S.zombies.add(remark)
    print("  ZOMBIE %s: %d cancels over %d min changed nothing (status %d,"
          " %d shares stuck). Dropping it from pend and leaving it alone."
          % (remark, S.cx_tries.get(remark, 0), now_m - t0, status, left))
    return True


# ---- market ----
def _quote(C, code, today, hhmmss):
    try:
        data = C.get_market_data_ex(["open", "high", "low", "close", "volume", "preclose"],
                                    [code], period="1m", start_time=today + hhmmss,
                                    end_time=today + hhmmss, fill_data=False)
        frame = data.get(code)
        if frame is None or len(frame) == 0:
            return None
        return frame.iloc[-1]
    except Exception:
        return None


def _limit_up(C, code, q):
    if code in S.limit_cache:
        return S.limit_cache[code]
    up = None
    try:
        d = C.get_instrument_detail(code) or {}
        up = d.get("UpStopPrice")
    except Exception:
        up = None
    if not up:
        try:
            pc = float(q["preclose"])
            up = round(round(pc * (1 + _board_rate(code)) / TICK) * TICK, 2)
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
        S.limit_cache[code] = up
    return up


def _is_st(C, code, q=None):
    """Is this name ST / *ST today, asked of the BROKER rather than a data file.

    Primary test is the instrument name: the exchange puts ST or *ST in front of
    it, and QMT hands that straight through, so it is always current -- no list
    to export, refresh or get stale.

    Fallback is the price band. A +-5% ceiling on a name that is not on the STAR
    or ChiNext board can only be ST, so UpStopPrice/PreClose ~= 1.05 gives the
    same answer without the name. Kept because it is not yet confirmed that
    InstrumentName is populated in the model-trading sandbox (it is under
    miniQMT's xtdata); whichever test fires is logged once per name so the
    question gets settled by evidence on the first live day.

    Unknown -> False. Refusing to buy on a failed lookup would silently drop
    names for a reason that has nothing to do with the stock.
    """
    if code in S.st_cache:
        return S.st_cache[code]
    st = False
    why = ""
    known = False               # did the broker actually answer?
    try:
        d = C.get_instrument_detail(code) or {}
        nm = str(d.get("InstrumentName", "") or "").strip().upper()
        up = d.get("UpStopPrice")
        pc = d.get("PreClose") or (q or {}).get("preclose")
        if nm:
            known = True
            if nm.startswith("ST") or nm.startswith("*ST"):
                st, why = True, "name %r" % nm
        elif up and pc and float(pc) > 0:
            known = True
            ratio = float(up) / float(pc)
            if 1.045 <= ratio <= 1.055 and _board_rate(code) > 0.05:
                st, why = True, "band %.3f (no name from broker)" % ratio
    except Exception:
        known = False
    # Cache only a REAL answer. At 09:30 get_instrument_detail often has nothing
    # yet; caching that "no" would fix the name as non-ST for the whole day and
    # let a genuine overnight ST straight through -- the one case this guard
    # exists for. Unknown -> return False for this bar (do not block a name over
    # a data hiccup) and ask again on the next one.
    if known:
        S.st_cache[code] = st
    if st and code not in S.st_said:
        S.st_said.add(code)
        print("  ST detected %s (%s)" % (code, why))
    return st


def _touch_raw(C, code):
    """(bid1, ask1, got_book) -- like _touch but WITHOUT requiring both sides.

    _touch returns (0,0) unless bid AND ask are both positive, which is right
    for the spread filter but destroys the one thing we need here: a sealed
    limit-up board has NO offers at all, so ask1 is 0. Collapsing that to (0,0)
    makes "sealed" and "no data" indistinguishable, and a ceiling test built on
    _touch would therefore never fire on the very case it exists for.

    got_book says the feed answered, even one-sided. False means no data, and
    the caller must fall back to the bar.
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


def _limit_down(C, code, q):
    """The day's legal floor, or None.

    Mirror of _limit_up. The FALLBACK DIRECTION IS THE OPPOSITE ONE, and that
    is deliberate: _limit_up wants a ceiling that is too HIGH (so we rarely
    believe a name is limit-up and keep trying, which only wastes orders). Here
    a floor that is too HIGH would make an open book look sealed and send a
    limit buy at a price the market never reached. _board_rate is already the
    wide value, so preclose*(1-rate) lands LOW -- we then simply fail to
    recognise a seal and stay in QUEUE, which is exactly today's behaviour.
    """
    if code in S.floor_cache:
        return S.floor_cache[code]
    dn = None
    try:
        d = C.get_instrument_detail(code) or {}
        dn = d.get("DownStopPrice")
    except Exception:
        dn = None
    if not dn:
        try:
            pc = float(q["preclose"])
            dn = round(round(pc * (1 - _board_rate(code)) / TICK) * TICK, 2)
        except Exception:
            dn = None
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
        S.floor_cache[code] = dn
    return dn


def _sealed_down(C, code, q):
    """Is the BID side empty with the offers parked on the floor? -> (bool, px).

    The case this exists for: a name we are told to BUY is sealed limit-down.
    The sell queue at the floor is enormous and the bid side is empty -- so the
    stock is trivially buyable, but QUEUE mode quotes at BID-1 and there is no
    bid to quote at. The strategy wants the name; the pricing mode cannot ask
    for it. That is a gap, not a decision: _sealed_up exists to stop us buying
    what cannot be bought, and nothing was ever written for the mirror case.

    Both conditions are required. "No bid" alone is also what a halted or
    untouched name looks like, and buying into a halt is not possible; "offers
    at the floor" alone happens on an open book that is merely down a lot.
    """
    dn = _limit_down(C, code, q)
    if not dn:
        return False, None
    bid, ask, got = _touch_raw(C, code)
    if not got or bid > 0 or ask <= 0:
        return False, None
    if ask <= dn + TICK / 2:
        return True, dn
    return False, None


def _sealed_up(C, code, q):
    """Is the OFFER side sealed at the ceiling right now? -> (bool, why).

    Live touch first, previous bar only as a fallback. The bar test asks "was
    the whole of LAST minute at the ceiling", which is a guess about now made
    from a minute ago: it skips a minute in which the board has already opened,
    and it lets an order go out into a board that has already re-sealed. The
    touch answers about THIS moment, and the script is already pulling it for
    the spread filter, so it costs nothing extra.
    """
    up = _limit_up(C, code, q)
    if not up:
        return False, ""                    # no ceiling known -> never block
    bid, ask, got = _touch_raw(C, code)
    if got:
        if ask <= 0:
            # No offers at all. That is limit-up only if the bid is parked at
            # the ceiling; an empty book on a halted or untraded name is not.
            if bid >= up - TICK / 2:
                return True, "touch: no offer, bid at ceiling %.2f" % up
            return False, "touch: empty offer side, bid %.2f" % bid
        return (ask >= up - TICK / 2), "touch: ask %.2f vs ceiling %.2f" % (ask, up)
    if q is not None and q["volume"] > 0 and q["low"] >= up - TICK / 2:
        return True, "bar(no tick): prev-minute low %.2f at ceiling" % q["low"]
    return False, "bar(no tick)"


def _prev_min(hhmmss):
    """Previous minute label, skipping the 11:30-13:00 lunch gap."""
    t = int(hhmmss[:2]) * 60 + int(hhmmss[2:4]) - 1
    if 11 * 60 + 30 < t < 13 * 60:          # inside lunch -> last morning bar
        t = 11 * 60 + 30
    return "%02d%02d00" % (t // 60, t % 60)


def _cap_volume(C, code, today, hhmmss):
    """Volume (in LOTS) of the last COMPLETED bar. The bar labelled `hhmmss` is
    still forming (QMT stamps a forming bar with its closing minute), so using it
    would throttle the participation cap to a few seconds of trading."""
    q = _quote(C, code, today, _prev_min(hhmmss))
    if q is not None and q["volume"] > 0:
        return int(q["volume"])
    q = _quote(C, code, today, hhmmss)      # fallback: forming bar
    return int(q["volume"]) if q is not None else 0


def _bar_price(C, code, today, hhmmss):
    """Close of the last completed bar, or 0. Reference price for slippage."""
    try:
        q = _quote(C, code, today, _prev_min(hhmmss))
        if q is None:
            q = _quote(C, code, today, hhmmss)
        return float(q["close"]) if q is not None else 0.0
    except Exception:
        return 0.0


def _exec_write(row):
    """One line per completed order into the execution-quality CSV.

    The slippage used in the backtest is an ASSUMPTION -- half a tick, then a
    whole tick, derived from the median fill price -- and it leaves out market
    impact entirely. This file replaces the assumption with data: for every
    order it stores the touch as it stood when the decision was made and the
    price actually obtained, so the real cost in bps can be computed instead of
    guessed. That matters most before scaling capital, since impact is the one
    term that grows with size and the one the estimate omits.
    """
    if S.execfh is False:
        return
    if S.execfh is not None and S.execfh_day != _today_str():
        try:
            S.execfh.flush(); S.execfh.close()
        except Exception:
            pass
        S.execfh = None
        # INSIDE the branch. Unconditionally blanking execfh_day made the very
        # next call see "" != today, close the handle and reopen -- so the file
        # was reopened on every other row. Harmless where a file can be
        # reopened; here it cannot, so _open_varying had to invent a new name or
        # directory each time and 2026-09-02 scattered one morning's execution
        # record over six files. Ten name/dir combinations exist; once they are
        # used up S.execfh goes False and exec logging stops for the day.
        # The sell script never had this line.
        S.execfh_day = ""
    if S.execfh is None:
        d = (getattr(S, "runlog_dir", None) or RUN_LOG_DIR)
        for cand in (d, TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS, "C:\\Users\\Public\\Documents"):
            try:
                day = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
                fh, _xp, _xd = _open_varying(
                    (cand,), "exec_" + STRATEGY + "_" + day, ".csv", "a")
                if fh is None:
                    raise IOError("no writable exec path")
                if fh.tell() == 0:
                    fh.write("date,t_place,t_done,code,side,qty_sent,qty_filled,"
                             "price_filled,bid1,ask1,mid,bar_close,"
                             "slip_vs_mid_bp,slip_vs_close_bp,spread_bp,"
                             "status,price_mode\n")
                fh.flush()
                S.execfh = fh
                S.execfh_day = day
                break
            except Exception:
                continue
        if S.execfh is None:
            S.execfh = False
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
                _today_str(), "", hhmmss or "", _ocode, "buy",
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
        _bpx = float(getattr(o, "m_dTradedPrice", 0) or 0)
        # Same reason as the sell side: the exec CSV scores the order, this
        # scores the day. _exec_close runs once per order.
        if filled > 0 and _bpx > 0:
            _bc = (getattr(o, "m_strInstrumentID", "") + "."
                   + getattr(o, "m_strExchangeID", ""))
            _ba = S.fill_px.setdefault(_bc, [0, 0.0])
            _ba[0] += filled
            _ba[1] += filled * _bpx
        px = float(getattr(o, "m_dTradedPrice", 0) or 0)
        st = int(getattr(o, "m_nOrderStatus", 0) or 0)
        bid, ask, bar = rec["bid"], rec["ask"], rec["bar"]
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
        # Buying above the reference costs us, so the sign is (fill - ref).
        smid = ((px - mid) / mid * 1e4) if (mid > 0 and px > 0) else ""
        sclose = ((px - bar) / bar * 1e4) if (bar > 0 and px > 0) else ""
        spread = ((ask - bid) / mid * 1e4) if mid > 0 else ""
        day = _today_str()
        _exec_write("%s,%s,%s,%s,%s,%d,%d,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s" % (
            day, rec["t"], hhmmss, rec["code"], rec["side"],
            rec["qty"], filled,
            ("%.4f" % px) if px else "", ("%.4f" % bid) if bid else "",
            ("%.4f" % ask) if ask else "", ("%.4f" % mid) if mid else "",
            ("%.4f" % bar) if bar else "",
            ("%.2f" % smid) if smid != "" else "",
            ("%.2f" % sclose) if sclose != "" else "",
            ("%.2f" % spread) if spread != "" else "", st,
            rec.get("mode", "")))
        # DURABLE FILL RECORD -- the only source that survives a restart when
        # every other one reads zero. See _fills_from_disk.
        if filled > 0:
            _fill_append(day, rec["code"], filled, remark)
    except Exception as e:
        print("  exec record failed:", repr(e))


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
        d = (getattr(S, "runlog_dir", None) or RUN_LOG_DIR)
        base = "fills_" + STRATEGY + "_" + _acct_tag() + "_" + day
        fh, p, _fd = _open_varying((d,), base, ".csv", "a")
        if fh is None:
            S.fillfh = False
            S.fills_path = d + "\\" + base + ".csv"
            print("  fill record unavailable: no writable path under", d,
                  "-- the durable per-fill record is OFF for today. ours is"
                  " still rebuilt from the order list, so the cross-check"
                  " keeps all three sources.")
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
    d = (getattr(S, "runlog_dir", None) or RUN_LOG_DIR)
    return d + "\\fills_" + STRATEGY + "_" + _acct_tag() + "_" + day + ".csv"


def _fill_append(day, code, filled, remark):
    """One line per order that actually traded. Written from _exec_close, which
    pops the order out of S.exec_open first, so each order is recorded once."""
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
        print("  fill record unavailable:", repr(e))


def _fills_from_disk(day):
    """{code: shares filled today}, rebuilt from our own record.

    THE RESTART FALLBACK. Sizing asks "how much have I already bought today?"
    and had three ways to answer, all of which can read zero at the same time:

      cur = position - baseline   the position belongs to the BROKER, and on a
                                  shared simulation account other things edit
                                  it. 2026-08-26: the 09:44 baseline snapshot
                                  put 002133.SZ at 3,300, the account read
                                  2,800 at 13:01 after we had bought 1,800, and
                                  max(0, 2800 - 3300) is 0.
      filled_today (DEAL query)   comes back empty after a restart -- the query
                                  appears to be scoped to the strategy instance.
      S.sent_qty                  lives in memory, so zero by definition.

    All three read 0, delta became the entire schedule, and the script re-ran
    its whole day. The existing trades CSV cannot stand in for this: _log_trade
    is called straight after passorder, so it records what was SENT -- 36,608
    shares that day against 13,100 actually filled, because QUEUE re-quotes
    constantly.

    This file records fills, once each, and outlives the process. On a healthy
    account it changes nothing: cur is the larger number and wins the max().
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
        print("  fill replay failed:", repr(e))
    return out


def _touch(C, code):
    """(bid1, ask1) from the live tick, or (0,0) when unavailable.
    get_full_tick returns either {'askPrice': [p1..p5]} or {'askPrice1': p1};
    handle both, and degrade to (0,0) in backtest where there is no tick."""
    # get_market_data_ex(period='tick') first: it serves every board, including
    # BJ, where get_full_tick returned five levels of zeros with a timetag frozen
    # at the previous day (verified 2026-07-30 on 920002/920018/920931). Main
    # board returns the same book either way, so this costs nothing.
    try:
        data = C.get_market_data_ex(["bidPrice", "askPrice"], [code],
                                    period="tick", count=1)
        f = data.get(code)
        if f is not None and len(f) > 0:
            row = f.iloc[-1]
            b, a = row["bidPrice"], row["askPrice"]
            bid = float(b[0]) if isinstance(b, (list, tuple)) and b else float(b or 0)
            ask = float(a[0]) if isinstance(a, (list, tuple)) and a else float(a or 0)
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
    """True when the touch is unusually wide, so this minute's slice should wait.
    Returns (is_wide, description). Never fires without tick data, on a
    one-sided book (limit up/down is handled elsewhere), or past the guard time."""
    if MIN_SPREAD_TICKS_BY_MODE[_price_mode(code)] <= 0 or \
            hhmmss >= SPREAD_GUARD_UNTIL:
        return False, ""
    bid, ask = _touch(C, code)
    # Report the TRANSITION, not just the first call. The old flag was set to
    # True on success as well as on failure, so a feed that worked at 09:30 and
    # died at 10:00 silently disabled this filter for the rest of the day with
    # nothing in the log. S.tick_ok is None until the first call, then True or
    # False, and only a change prints.
    if bid <= 0 or ask <= 0 or ask <= bid:
        if S.tick_ok is not False:
            S.tick_ok = False
            print("  NOTE: no usable tick/touch data -> SPREAD FILTER INACTIVE"
                  " (buying continues, unprotected against a wide touch)")
        return False, ""
    if S.tick_ok is not True:
        S.tick_ok = True
        print("  tick/touch OK -> spread filter live (%s bid %.2f ask %.2f)"
              % (code, bid, ask))
    spread = ask - bid
    ticks = int(round(spread / TICK))
    bps = spread / ((ask + bid) / 2.0) * 10000.0
    if ticks >= MIN_SPREAD_TICKS_BY_MODE[_price_mode(code)] and bps > MAX_SPREAD_BPS:
        return True, "bid %.2f ask %.2f = %d ticks / %.0f bps" % (bid, ask, ticks, bps)
    return False, ""


def _traded_since_open(C, code, today, hhmmss):
    if code in S.data_today:
        return True
    try:
        data = C.get_market_data_ex(["close"], [code], period="1m",
                                    start_time=today + "093000", end_time=today + hhmmss,
                                    fill_data=False)
        frame = data.get(code)
        has = frame is not None and len(frame) > 0
    except Exception:
        has = False
    if has:
        S.data_today.add(code)
    return has


def _dump_obj(label, o):
    """One field per line. A single-line list is what the QMT log truncates,
    and the field we needed (the share count of a same-day buy) was always in
    the cut-off tail."""
    print("=" * 60)
    print(label)
    try:
        attrs = sorted(a for a in dir(o) if a.startswith("m_"))
    except Exception:
        print("  <cannot enumerate>")
        return
    for a in attrs:
        try:
            v = getattr(o, a)
        except Exception as e:
            v = "<err " + type(e).__name__ + ">"
        if callable(v):
            continue
        print("  %-30s = %r" % (a, v))
    print("=" * 60)


# ---- account ----
def _total_value(C):
    if BUY_BUDGET > 0:            # explicit budget: immune to unrelated holdings
        return float(BUY_BUDGET)
    if S.preview:
        return 0.0                # no budget and no account -> nothing to size with
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ACCOUNT")
        if rows:
            v = getattr(rows[0], "m_dBalance", None)
            if v and v > 0:
                return float(v)
    except Exception:
        pass
    return float(getattr(C, "capital", 0) or 0)


def _positions(C):
    if S.preview:
        return dict(S.paper_pos)
    out = {}
    rows = 0
    try:
        for o in get_trade_detail_data(S.acct, S.acct_type, "POSITION"):
            rows += 1
            # Dump every integer/bool field WITH ITS VALUE for a target we know we
            # bought. The share count has to be in one of them; printing names
            # alone was not enough (2026-07-29: guessed on-road field names all
            # missed, so a name bought at 10:29 still read cur=0 and was bought
            # again after a restart).
            # Dump a name THIS run actually bought. Picking any target hit
            # 600183 first -- someone else's -399 short in this shared account --
            # which shows nothing about how a same-day buy is represented.
            if (not S.pos_fields_dumped
                    and getattr(o, "m_strInstrumentID", "") + "." + getattr(o, "m_strExchangeID", "") in S.bought_today):
                S.pos_fields_dumped = True
                if DEBUG_DUMP_FIELDS:
                    _dump_obj("POSITION row for " + getattr(o, "m_strInstrumentID", ""), o)
                else:
                    print("  POS sample %s vol=%s canuse=%s onroad=%s yest=%s today=%s"
                          % (getattr(o, "m_strInstrumentID", ""),
                             getattr(o, "m_nVolume", "?"), getattr(o, "m_nCanUseVolume", "?"),
                             getattr(o, "m_nOnRoadVolume", "?"),
                             getattr(o, "m_nYesterdayVolume", "?"),
                             getattr(o, "m_bIsToday", "?")))
            code = getattr(o, "m_strInstrumentID", "")
            mkt = getattr(o, "m_strExchangeID", "")
            if DEBUG_CODE and code + "." + mkt == DEBUG_CODE:
                # EVERY row for this code, so multiple/cancelling rows are visible
                print("  DBG %s row#%d vol=%r canuse=%r onroad=%r yest=%r today=%r"
                      " frozen=%r holder=%r"
                      % (DEBUG_CODE, rows, getattr(o, "m_nVolume", None),
                         getattr(o, "m_nCanUseVolume", None),
                         getattr(o, "m_nOnRoadVolume", None),
                         getattr(o, "m_nYesterdayVolume", None),
                         getattr(o, "m_bIsToday", None),
                         getattr(o, "m_nFrozenVolume", None),
                         getattr(o, "m_strStockHolder", None)))
            # A name we bought but that reads zero is the open question, so show
            # its raw row instead of silently dropping it by the `vol` filter.
            if code + "." + mkt in S.bought_today and not S.zero_reported.get(code + "." + mkt):
                v0 = getattr(o, "m_nVolume", None)
                if not v0:
                    S.zero_reported[code + "." + mkt] = True
                    print("  ZERO-VOL row for %s.%s: vol=%r canuse=%r onroad=%r yest=%r today=%r"
                          % (code, mkt, v0, getattr(o, "m_nCanUseVolume", None),
                             getattr(o, "m_nOnRoadVolume", None),
                             getattr(o, "m_nYesterdayVolume", None),
                             getattr(o, "m_bIsToday", None)))
            # m_nVolume is the TOTAL and already includes today's unsettled buys;
            # m_nOnRoadVolume is a subset flag, not an addition. Measured
            # 2026-07-29: 600805 showed vol=500 onroad=500 yest=0 for a 500-share
            # buy, and adding them made every position read double, so the
            # strategy stopped buying at half the target.
            vol = int(getattr(o, "m_nVolume", 0) or 0)
            if code and mkt and vol:
                key = code + "." + mkt
                # ACCUMULATE. One code can appear on several rows (old lot vs
                # today's, different shareholder account, normal vs margin...).
                # Assigning would keep only the last row and understate the
                # holding, which again means repeated orders.
                out[key] = out.get(key, 0) + vol
    except Exception as e:
        # A partial list is worse than none: names after the failure point look
        # unheld and get bought again. Say so loudly instead of silently
        # returning a truncated dict.
        print("POSITION query FAILED after", rows, "row(s):", repr(e),
              "-> holdings incomplete this bar, orders suppressed")
        S.pos_ok = False
        return out
    S.pos_ok = True
    if not S.pos_rows_reported:
        S.pos_rows_reported = True
        print("POSITION query returned", rows, "row(s) ->", len(out), "distinct code(s)")
        # Name them. 002436.SZ kept reading cur=0 after real fills, so knowing
        # exactly which targets the broker does not report is the whole question.
        missing = [c for c in TARGETS[:SLOTS] if c not in out]
        print("  of the first", SLOTS, "targets,", len(missing),
              "NOT in the position list:", ", ".join(missing) if missing else "(none)")
    return out


def _open_buy_qty(C):
    if S.preview:
        return {}
    out = {}
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ORDER")
    except Exception:
        return out
    seen = set()
    for o in rows:
        try:
            # EVERY row, terminal ones included, and BEFORE any skip. This set
            # tells the block below which of our orders the broker has taken
            # charge of; a terminal row missing from it would be added back as
            # pending and pin the slot shut for the rest of the day.
            seen.add(getattr(o, "m_strRemark", "") or "")
            if getattr(o, "m_nOrderStatus", 0) in TERMINAL_STATUS:
                continue
            if getattr(o, "m_nDirection", None) != 48:      # buy only
                continue
            # Read-only membership test, deliberately: _cancel_stale_orders is
            # the one that sends the cancels and therefore the one that judges.
            # Judging here as well would re-run the reset on the same rows in
            # the same bar and log the verdict twice.
            if (getattr(o, "m_strRemark", "") or "") in S.zombies:
                continue
            code = getattr(o, "m_strInstrumentID", "") + "." + getattr(o, "m_strExchangeID", "")
            left = int(getattr(o, "m_nVolumeTotalOriginal", 0)) - int(getattr(o, "m_nVolumeTraded", 0))
            if left > 0:
                out[code] = out.get(code, 0) + left
        except Exception:
            continue

    # ---- OUR OWN ORDERS THE BROKER CANNOT SEE YET -----------------------
    # Tens of seconds pass between passorder returning and the order appearing
    # in the counter's ORDER list. In that window the shares are in NEITHER
    # place: nothing has filled, so they are not in the position, and the list
    # above does not have them. The script looks, sees nothing, and concludes
    # it has not ordered yet.
    #
    # 2026-08-31, 688567.SH. Three bars, each reading "cur 663 pend 0":
    #     13:25:59  short 218 -> buy 218
    #     13:27:32  short 224 -> buy 224     <- 218 already sent, invisible
    #     13:29:05  short 235 -> buy 235     <- 442 already sent, invisible
    #     13:30:35  cur 1340 against a target of 1078
    # 262 shares over, a quarter of the slot, from ordering one gap three
    # times. The 93-second spacing is not a coincidence: UNCONFIRMED_TIMEOUT_SEC
    # is 90, so each order was declared "likely rejected" and dropped from
    # S.waiting just before the next bar sized itself.
    #
    # S.sent_qty did not save it. `delta` takes max(cur + pend, sent, dealt),
    # and `sent` counts THIS SESSION while `cur` counts the whole holding --
    # after the 13:00 restart sent was 0 against cur 663, so it could not bind
    # until it had grown past 663, i.e. until 663 shares had been over-ordered.
    # Comparing a session total with a lifetime total is the actual defect
    # there; this block removes the need for that comparison to work.
    #
    # S.exec_open is the right source: an order goes in when it is SENT and
    # comes out only via _exec_close, i.e. only once the broker has returned a
    # VERDICT. The 90-second timeout does not touch it.
    _now = dt.datetime.utcnow()
    for _r, _rec in list(S.exec_open.items()):
        if (_rec or {}).get("side") != "buy" or _r in seen:
            continue
        _rt = _rec.get("rt")
        if _rt is not None and (_now - _rt).total_seconds() >= PEND_INVISIBLE_MAX_SEC:
            # Never showed up at all. Holding it in `pend` forever would stall
            # the slot for the rest of the day -- the opposite failure, and
            # just as expensive. Release it, loudly.
            if _r not in S.pend_released:
                S.pend_released.add(_r)
                print("WARN %s never reached the broker's order list in %.0f"
                      " min -- releasing it from pending so the slot can trade"
                      % (_r, PEND_INVISIBLE_MAX_SEC / 60.0))
            continue
        _c = _rec.get("code")
        _q = int(_rec.get("qty") or 0)
        if _c and _q > 0:
            out[_c] = out.get(_c, 0) + _q
    return out


def _reconcile_waiting(C):
    if S.preview:
        return True
    if not S.waiting:
        return True
    found = set()
    try:
        for o in get_trade_detail_data(S.acct, S.acct_type, "ORDER"):
            r = getattr(o, "m_strRemark", "")
            if r in S.waiting:
                found.add(r)
    except Exception:
        pass
    S.waiting = [r for r in S.waiting if r not in found]
    # Safety: an order that was rejected outright never shows up in the order
    # book, so age waiting entries out instead of pausing the strategy forever.
    #
    # Aged on the REAL clock, not bar time. Bar time is not monotonic with wall
    # time: when the PC suspended for six seconds on 2026-07-30, QMT delivered
    # the backlog on resume and the bar label jumped fifteen minutes in three
    # real seconds. The sell script, which had the identical check, then
    # declared three just-sent orders "never appeared, likely rejected" and
    # re-sent them, ending 251 shares ahead of schedule. STALE_ORDER_MIN stays
    # in bar minutes for the cancel path below, which compares against the
    # broker's own timestamp.
    if S.waiting:
        now = dt.datetime.utcnow()
        for r in list(S.waiting):
            placed = S.order_real_time.get(r)
            if placed is None:
                S.order_real_time[r] = now
                continue
            age = (now - placed).total_seconds()
            if age >= UNCONFIRMED_TIMEOUT_SEC:
                print("WARN order not seen by the broker after %.0fs (likely"
                      " rejected): %s -> giving up on it" % (age, r))
                S.waiting.remove(r)
                S.order_time.pop(r, None)
                S.order_real_time.pop(r, None)
    return not S.waiting


def _order_id(o):
    """Order id for cancel(); field name varies across QMT builds."""
    for attr in ("m_strOrderSysID", "m_nOrderID", "m_strOrderID", "m_nOrderSysID"):
        v = getattr(o, attr, None)
        if v not in (None, "", 0):
            return v
    return None


def _order_price(o):
    """The price an order is resting at, from the broker's own row.

    Field names vary across QMT builds, hence the list -- the same reason
    _order_id has one. Returns 0.0 when none carries a usable price, which the
    caller must treat as "unknown", never as "zero".
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
    """Session-minute the broker says the order was placed, or None.

    Field name differs across QMT builds, so try the usual candidates. With a
    real timestamp we know how long an order has ACTUALLY been hanging -- after
    a restart that beats assuming it is brand new."""
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


def _dump_order_fields(o):
    """Once per run: show what the ORDER object actually exposes, so the field
    guesses above (and the id/status ones) can be verified on a sim account."""
    if S.order_fields_dumped:
        return
    S.order_fields_dumped = True
    try:
        if DEBUG_DUMP_FIELDS:
            _dump_obj("ORDER row (field survey)", o)
    except Exception:
        pass


def _cancel_stale_orders(C, today, hhmmss):
    """LIVE only: cancel unfilled orders older than STALE_ORDER_MIN minutes so the
    next bar can re-quote at the current counterparty price."""
    if S.preview or not S.acct:
        return
    # The exchange refuses every cancellation from 14:57 to 15:00 while the
    # closing call auction runs. On 2026-08-24 this script was still sending
    # them at wall 14:58:58 -- all refused, all logged by the counter. Wall
    # clock, because the bar label reads 1-2 minutes ahead of it.
    if _wall_hhmmss() >= NO_CANCEL_AFTER:
        return
    now_m = _sess_min(hhmmss)
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ORDER")
    except Exception:
        return
    for o in rows:
        try:
            remark = getattr(o, "m_strRemark", "") or ""
            if not remark.startswith(STRATEGY):
                continue        # another strategy's order -- never touch or log it
            _st = int(getattr(o, "m_nOrderStatus", 0) or 0)
            # Rejections must be reported BEFORE the terminal skip: 57 is itself
            # a terminal status, so a `continue` above this swallowed every one
            # of them. 23 STAR orders died silently on 2026-07-31 because of it.
            if _st == 57:
                _exec_close(o, remark, S.now[8:] if S.now else "")
                _r = getattr(o, "m_strRemark", "") or ""
                if _r not in S.rejected_seen:
                    S.rejected_seen.add(_r)
                    # GIVE THE REJECTED QUANTITY BACK TO sent_qty, exactly as a
                    # cancel does a few lines down. sent_qty is a FLOOR under
                    # `delta`, so a rejected order that stays counted throttles
                    # the name until the TWAP schedule crawls past it.
                    #
                    # 2026-08-31 10:11, live: 002573.SZ sent 700, refused by the
                    # counter with 250253, and the next bar read
                    #     cur 0 pend 0 sent 700 dealt 0 -> tgt 3000 twap 700
                    #     delta 0 -> delta 0 < one lot 100
                    # A share that was refused before reaching the book was
                    # holding the slot shut. Rejections must not count like
                    # fills. Inside the rejected_seen guard so it can only ever
                    # be credited once, however many bars the row is re-read on.
                    _rc = (getattr(o, "m_strInstrumentID", "") + "."
                           + getattr(o, "m_strExchangeID", ""))
                    _rback = (int(getattr(o, "m_nVolumeTotalOriginal", 0) or 0)
                              - int(getattr(o, "m_nVolumeTraded", 0) or 0))
                    if _rback > 0 and _rc and _rc in S.sent_qty:
                        S.sent_qty[_rc] = max(0, S.sent_qty.get(_rc, 0) - _rback)
                    print("  REJECTED", _r, "qty",
                          getattr(o, "m_nVolumeTotalOriginal", "?"),
                          "| gave", _rback, "back to sent",
                          "| cancelInfo", repr(getattr(o, "m_strCancelInfo", "")))
                continue
            if _st in TERMINAL_STATUS:                                 # terminal
                _exec_close(o, remark, S.now[8:] if S.now else "")
                continue
            left = int(getattr(o, "m_nVolumeTotalOriginal", 0)) - int(getattr(o, "m_nVolumeTraded", 0))
            if left <= 0:
                continue
            # Judge it here, where the cancels are sent. A verdict of "stuck"
            # takes it out of _open_buy_qty (hence out of `pend`) and stops any
            # further cancel; _zombie un-flags it the moment it moves.
            if _zombie(remark, _st, left, now_m):
                # Hand the frozen remainder back to sent_qty for the same reason
                # a successful cancel does: sent_qty floors `delta`, so leaving
                # a dead order's shares in it caps the schedule just as hard as
                # leaving them in pend. On 2026-08-24, 600533.SH was pinned by
                # BOTH at once -- max(cur+pend, sent) = max(4500, 4000) -- so
                # clearing only one of the two would have moved nothing.
                #
                # ONCE per order. _zombie() answers True on every later bar too,
                # and crediting it each time would walk sent_qty down to zero and
                # turn a stalled name into a runaway one.
                if remark not in S.zombie_credited:
                    S.zombie_credited.add(remark)
                    _zcode = (getattr(o, "m_strInstrumentID", "") + "."
                              + getattr(o, "m_strExchangeID", ""))
                    if left > 0 and _zcode != ".":
                        S.sent_qty[_zcode] = max(
                            0, S.sent_qty.get(_zcode, 0) - left)
                continue
            if _st in CANCEL_PENDING_STATUS:
                _r = remark
                if _r not in S.cancel_inflight:
                    S.cancel_inflight.add(_r)
                    print("  cancel already in flight for", _r, "(status", _st,
                          ", left", left, ") -- not re-sending")
                continue
            # Not at the exchange yet -> the counter refuses the cancel. Same
            # guard as the sell script; see its comment for the 251020 message.
            # Skipping costs nothing: the status turns 50 within a second or two
            # and the next bar cancels it normally.
            if _st not in CANCELLABLE_STATUS:
                continue
            _dump_order_fields(o)
            remark = getattr(o, "m_strRemark", "")
            placed = S.order_time.get(remark)
            if placed is None:
                # Unknown order: after a restart our own pre-restart orders look
                # like this. Never touch manual / other strategies' orders.
                if not remark.startswith(STRATEGY):
                    continue
                # Prefer the broker's own timestamp -- the order may already have
                # been hanging for an hour, and waiting another STALE_ORDER_MIN
                # from "now" would delay the re-quote for no reason.
                placed = _order_insert_min(o)
                if placed is None:
                    placed = now_m                                  # unknown age -> age from now
                S.order_time[remark] = placed
                # RECOVER THE PRICE TOO, not just the age. Without it _ref
                # stays 0, the price test below is skipped for the fallback
                # that cancels anything older than STALE_ORDER_MIN, and every
                # order that survived a restart is pulled regardless of where
                # the touch is. The broker knows where it rests; reconstructing
                # S.exec_open from that lets the ordinary test -- has the touch
                # moved away from MY price? -- apply to a pre-restart order
                # exactly as to one we placed ourselves.
                _apx = _order_price(o)
                # _ocode is not bound yet at this point in the loop -- it is
                # computed further down -- so read the code straight off the row.
                _acode = (getattr(o, "m_strInstrumentID", "") + "."
                          + getattr(o, "m_strExchangeID", ""))
                if _apx > 0 and _acode != "." and remark not in S.exec_open:
                    _amode = _price_mode(_acode)
                    S.exec_open[remark] = {
                        "code": _acode, "side": "buy",
                        "qty": int(getattr(o, "m_nVolumeTotalOriginal", 0) or 0),
                        "t": S.now[8:] if S.now else "", "rt": dt.datetime.utcnow(),
                        # A QUEUE buy rests at the bid, a COMPETE buy at the
                        # ask. Record the order's own price on the side its mode
                        # reads, so the comparison below is like for like.
                        "bid": _apx if _amode != "COMPETE" else 0.0,
                        "ask": _apx if _amode == "COMPETE" else 0.0,
                        "bar": 0.0, "mode": _amode, "adopted": True}
                print("ADOPT pre-restart order", remark, "left", left,
                      "age", max(0, now_m - placed), "min",
                      ("resting at %.2f" % _apx) if _apx > 0 else "(price unknown)")
            # ---- cancel on PRICE, not on a stopwatch --------------------
            # A counterparty-price order becomes a resting LIMIT order at the touch we saw
            # when we sent it. It goes bad in BOTH directions:
            #   ask rises above our price  -> it can never fill, it just blocks
            #   ask falls below our price  -> it still fills, at OUR price,
            #                                 because A-shares execute at the
            #                                 price of whichever order was
            #                                 entered first. We overpay.
            # Only an UNCHANGED touch makes resting free, and then it is pure
            # gain: the queue position is worth having, and re-quoting the same
            # price just sends us to the back of the line.
            #
            # The old rule was a flat STALE_ORDER_MIN stopwatch, which is worse
            # on every axis: on a thin name whose price has not moved it threw
            # the queue position away every 5 minutes (156 orders / 151 cancels
            # on one name in the 08-05 sim), and when the price DID move it let
            # us sit wrong -- or overpaying -- for up to five minutes.
            _ocode = (getattr(o, "m_strInstrumentID", "") + "."
                      + getattr(o, "m_strExchangeID", ""))
            _rec = S.exec_open.get(remark)
            # Compare against the side the order is RESTING ON, which depends on
            # the mode it was priced under:
            #   COMPETE  prType 14 -> the order sits at the ASK we saw
            #   QUEUE    prType  6 -> it sits at the BID we saw
            # Mirror of the fix made to the sell script the same day, where
            # using one side for both modes made QUEUE cancel itself to death:
            # a bid walking toward a resting passive offer is the fill arriving,
            # not a reason to pull the order and go to the back of the queue.
            _omode = (_rec or {}).get("mode") or _price_mode(_ocode)
            _ref = float((_rec or {}).get(
                "ask" if _omode == "COMPETE" else "bid") or 0)
            # A mode change overrides every price test below, including the
            # just-placed grace: this order carries the OLD pricing and
            # cannot re-price itself, so it goes regardless of the touch.
            # A FLOOR-PRICED ORDER IS NOT IN EITHER MODE. It rests at the
            # limit-down price, so neither the COMPETE nor the QUEUE test below
            # describes it, and _ref would be the bid -- which is zero in the
            # very board this order was written for.
            #
            # It also cannot be left alone if the board reopens. An unfilled
            # order still counts in `pend`, `pend` floors `delta`, and the slot
            # then stops receiving slices entirely: the name would go quiet for
            # the rest of the day holding one far-off-market bid. The generic
            # backstop would eventually take it, but 30 minutes of a dead slot
            # is most of an afternoon. So test the board itself, every bar, and
            # pull it the moment it is no longer sealed -- ahead of the
            # just-placed grace, because a reopening is a real state change and
            # not the churn that grace exists to damp.
            _floor_px = S.floor_orders.get(remark)
            _stale_mode = bool(_rec) and _rec.get("mode") not in (None, _price_mode(_ocode))
            if _floor_px is not None:
                _sd_now, _ = _sealed_down(C, _ocode, None)
                if _sd_now and (now_m - placed) < CANCEL_BACKSTOP_MIN:
                    continue            # still sealed -> the floor is still right
                _why = (("limit-down board REOPENED; a %.2f floor order cannot"
                         " fill and blocks the slot" % _floor_px) if not _sd_now
                        else ("floor order unfilled for %d min"
                              % (now_m - placed)))
            elif _stale_mode:
                _why = "price mode changed (%s -> %s)" % (_rec.get("mode"),
                                                          _price_mode(_ocode))
            elif (now_m - placed) < CANCEL_MIN_REST_BARS:
                continue                    # just placed: let it queue first
            else:
                _why = ""
            if not _why and _ref > 0:
                _b, _a, _got = _touch_raw(C, _ocode)
                _now_px = _a if _omode == "COMPETE" else _b
                if _got and _now_px > 0:
                    if _omode == "COMPETE":
                        if _a > _ref + TICK / 2:
                            _why = "ask %.2f -> %.2f, cannot fill" % (_ref, _a)
                        elif _a < _ref - TICK / 2:
                            _why = "ask %.2f -> %.2f, would overpay" % (_ref, _a)
                        elif (now_m - placed) >= CANCEL_BACKSTOP_MIN:
                            _why = "touch unchanged but %d min old" % (now_m - placed)
                        else:
                            continue        # price has not moved -> hold the slot
                    else:
                        # QUEUE: our bid rests at the bid we saw.
                        #   bid ROSE -> someone outbid us; we are behind the
                        #               touch and will not trade. Move.
                        #   bid FELL -> our bid is now the best in the book.
                        #               Hold: we are first in line to be hit.
                        if _b > _ref + TICK / 2:
                            _why = "bid %.2f -> %.2f, outbid at the touch" \
                                   % (_ref, _b)
                        else:
                            # NO AGE BACKSTOP HERE. It used to cancel after
                            # CANCEL_BACKSTOP_MIN with the touch unchanged, and
                            # the re-quote went back in at the SAME price --
                            # surrendering our place in the queue and buying
                            # nothing with it.
                            #
                            # 2026-09-01 on the sell side, 002573.SZ at 13:34:
                            # cancelled at 3.33 with the ask still 3.33,
                            # re-quoted at 3.33, back of the line.
                            #
                            # Bid ROSE -> the branch above moves us. Bid FELL ->
                            # we are the best bid and should hold. UNCHANGED ->
                            # we are AT the touch, and re-quoting there cannot
                            # improve a queue position, only give one up. The
                            # backstop belongs to COMPETE, where an order
                            # resting at a counterparty price from minutes ago
                            # really can go stale.
                            #
                            # A name stuck behind a long queue needs to CROSS
                            # the spread, not rejoin the same queue -- that is
                            # what MODE_OVERRIDE and price_mode are for.
                            continue        # at or better than the touch -> wait
                elif (now_m - placed) >= STALE_ORDER_MIN:
                    _why = "no touch data, %d min old" % (now_m - placed)
                else:
                    continue
            elif (now_m - placed) >= STALE_ORDER_MIN:
                _why = "no reference price, %d min old" % (now_m - placed)
            else:
                continue
            # Same order, too soon. Without this the loop cancels once per bar
            # forever -- see CANCEL_COOLDOWN_MIN. A cooldown rather than a
            # one-shot, because a cancel CAN simply be dropped and an order that
            # never dies would otherwise hold its name's pend all day.
            _last_cx = S.cancel_sent.get(remark)
            if _last_cx is not None and (now_m - _last_cx) < CANCEL_COOLDOWN_MIN:
                continue
            oid = _order_id(o)
            if oid is None:
                continue
            try:
                if not can_cancel_order(oid, S.acct, S.acct_type):
                    continue
            except Exception:
                pass                                                # helper absent -> just try
            cancel(oid, S.acct, S.acct_type, C)
            S.cancel_sent[remark] = now_m
            # Signature at the moment of the cancel. If the next scan still sees
            # this pair, the cancel achieved nothing.
            S.cx_tries[remark] = S.cx_tries.get(remark, 0) + 1
            S.cx_sig[remark] = (_st, left)
            S.cx_first.setdefault(remark, now_m)
            S.cancel_inflight.add(remark)
            S.waiting = [r for r in S.waiting if r != remark]
            # GIVE THE CANCELLED REMAINDER BACK TO sent_qty.
            #
            # sent_qty is a floor under `delta` so that an order which filled
            # instantly -- terminal, hence out of `pend`, while the position
            # query still lags -- cannot be sent twice. That is right for
            # COMPETE, where sent and filled are nearly the same number. It is
            # ruinous in QUEUE, where most orders rest and are then cancelled:
            # every cancelled share stayed in sent_qty forever and permanently
            # ate the schedule.
            #
            # 2026-08-18, 002573.SZ: eight orders, 3,800 shares sent against a
            # 3,100 target, only 1,000 actually filled. delta = 3100 -
            # max(cur+pend, 3800, 1000) went negative, so the name never
            # ordered again and finished at a third of its slot. Ten of twenty
            # slots sat like that from 14:03 to the close, which is why the
            # wind-down looked stalled and looked like a cash problem.
            #
            # `left` is the unfilled remainder the broker is returning to us, so
            # subtracting exactly that keeps the double-send protection for the
            # part that DID fill.
            # _ocode, not `code`: this loop walks the broker's order list and
            # `code` is not bound in _cancel_stale_orders at all. Writing it
            # would have been a NameError at best and, had an outer binding
            # existed, a silent credit to the wrong stock.
            _left_back = int(left or 0)
            if _left_back > 0 and _ocode:
                S.sent_qty[_ocode] = max(0, S.sent_qty.get(_ocode, 0) - _left_back)
            print("CANCEL", remark, "left", left, "age", now_m - placed,
                  "min ->", _why, "-> re-quote (spread filter still applies)")
        except Exception as e:
            print("cancel fail", repr(e))


def _order_buy(C, code, vol, remark, limit_px=None):
    if S.preview:
        # simulate immediate fill in-memory (no real order); caller already capped by volume ratio
        S.paper_pos[code] = S.paper_pos.get(code, 0) + int(vol)
        S.blotter.append((S.now, "buy(preview)", code, int(vol)))
        _log_trade(S.now[:8], S.now[8:], "buy_preview", code, vol, remark)
        print("PREVIEW BUY", code, int(vol), "@", S.now)
        return
    # Snapshot the touch BEFORE sending -- reading it after the fill would
    # already contain our own impact.
    _bid, _ask = _touch(C, code)
    _bar = _bar_price(C, code, S.now[:8], S.now[8:])
    try:
        if limit_px is not None:
            # fun.xml prType 11 = model/limit price, and PRICE is only read for
            # 11. Every other type makes QMT pick the price itself and ignores
            # whatever is passed here, which is why the normal path sends -1.
            passorder(S.buy_code, 1101, S.acct, code, 11, float(limit_px),
                      int(vol), STRATEGY, 1, remark, C)
        else:
            passorder(S.buy_code, 1101, S.acct, code,
                      PRTYPE_BY_MODE[_price_mode(code)], -1, int(vol),
                      STRATEGY, 1, remark, C)
        S.waiting.append(remark)
        S.order_time[remark] = _sess_min(S.now[8:])      # bar minutes, for stale-order cancel
        S.order_real_time[remark] = dt.datetime.utcnow()  # real clock, for the unconfirmed gate
        S.blotter.append((S.now, "buy", code, int(vol)))
        S.bought_today.add(code)
        S.sent_qty[code] = S.sent_qty.get(code, 0) + int(vol)
        S.exec_open[remark] = {"code": code, "side": "buy",
                               "qty": int(vol), "t": S.now[8:],
                               "rt": dt.datetime.utcnow(),
                               "bid": _bid, "ask": _ask, "bar": _bar,
                               "mode": _price_mode(code)}
        _log_trade(S.now[:8], S.now[8:], "buy", code, vol, remark)
        print("BUY", code, int(vol), remark)
    except Exception as e:
        print("passorder fail", code, vol, repr(e))


def _skip(hhmmss, rank, code, reason):
    S.suspend.append((hhmmss, rank, code, reason))
    print("SKIP", code, "rank", rank, reason)          # visible fallthrough reason


def _session_tag():
    """HHMMSS of this session's start, to make a filename unique."""
    t = getattr(S, "session_tag", None)
    if not t:
        t = _wall_hhmmss()
        S.session_tag = t
    return t


def _hhmmss_secs(t):
    """HHMMSS -> seconds since midnight. 0 if it cannot be read."""
    try:
        t = str(t)
        return int(t[0:2]) * 3600 + int(t[2:4]) * 60 + int(t[4:6])
    except Exception:
        return 0


def _open_varying(dirs, prefix, ext, mode):
    """Open prefix+ext in the first directory that will take it.

    Plain name first, so an ordinary day keeps one file per day; then a
    session-tagged name IN THE SAME DIRECTORY; only then the next directory.

    The old order tried directories only, which answers the wrong question. On
    2026-09-01 four LIVE starts of the sell script produced four logs in four
    different places because each new session could not re-open the previous
    one's file. The directory was always writable; the existing FILE was what
    could not be opened.

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
    """Filename suffix so per-account state never leaks between accounts.

    The baseline and the trade log describe ONE account's holdings. Keying them
    on the date alone meant that switching from 1000003 to 1000310 on 2026-07-31
    loaded 1000003's baseline -- which carried negative pre-existing positions --
    against 1000310's book. `_own = held - baseline` then read those negatives as
    "we already own 199 shares", and seven names were silently skipped.
    """
    a = str(getattr(S, "acct", "") or "noacct")
    return "".join(ch for ch in a if ch.isalnum()) or "noacct"


def _log_path(day):
    return (TRADE_LOG_DIR + "\\trades_" + STRATEGY + "_" + _acct_tag()
            + "_" + day + ".csv")


def _probe_fileio_paths(day):
    """One-shot survey: is ANY directory writable from inside the QMT sandbox?
    Reading and writing were both observed blocked in backtest and simulation,
    but only one directory was tested. Try a few candidates and report, so the
    answer is settled by evidence instead of assumption."""
    cands = [TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS,
             "C:\\QMTGTHT\\userdata",
             "C:\\QMTGTHT\\userdata_mini",
             "C:\\QMTGTHT\\python",
             "C:\\QMTGTHT",
             "C:\\Users\\Public",
             "C:\\Users\\Public\\Documents"]
    if DEBUG_DUMP_FIELDS:
        print("FILE IO SURVEY (write test, one line each):")
    winner = None
    for d in cands:
        p = d + "\\_qmt_write_probe_" + day + ".txt"
        try:
            f = open(p, "a")
            f.write("probe" + chr(10))
            f.flush()
            f.close()
            if DEBUG_DUMP_FIELDS:
                print("   WRITABLE  ", d)
            if winner is None:
                winner = d
        except Exception as e:
            if DEBUG_DUMP_FIELDS:
                print("   blocked   ", d, "|", type(e).__name__)
    if winner:
        print("   -> at least one writable dir found:", winner)
    else:
        print("   -> no writable directory; trade logging stays off (not fatal)")
    return winner


def _probe_fileio(day):
    """Can this QMT python actually write files? Backtest mode is sandboxed
    ('Forbidden FileIO'); local-python simulation may not be. Decide once."""
    path = _log_path(day)
    try:
        # Must actually WRITE and FLUSH: the QMT sandbox lets open() through but
        # blocks the write, so probing with open() alone reports a false OK.
        f = open(path, "a")
        if f.tell() == 0:
            f.write("bar_time,side,code,shares,price_or_remark\n")
        else:
            f.write("")
        f.flush()
        # KEEP IT OPEN. Closing here left _log_trade to open this same path
        # again on the first order, and this client refuses any open of a file
        # that already exists -- so the probe's own success is what pushed the
        # trade log into the legacy directory on 2026-09-02 ("preferred dir
        # refused" at 10:01:59, while the same loop opened the not-yet-existing
        # legacy path microseconds later). Handing the handle over means the
        # file is opened exactly once, like the run log and the fill record.
        S.tradefh = f
        S.tradefh_path = path
        S.fileio = True
        print("FILE IO: OK -> trade log", path)
    except Exception as e:
        S.fileio = False
        print("FILE IO: BLOCKED by sandbox ->", repr(e))
        print("  trades will NOT be written to disk; everything else still works")
    return S.fileio


def _log_trade(day, bar_time, side, code, shares, extra):
    """Append one sent order to the trade CSV, on a handle held open all day.

    It used to open() and close() the file per record. On 2026-08-04, the first
    live day, the header written at 09:29 succeeded and the very first order at
    10:07 failed with QMT's own PermissionError('Foribdden FileIO') -- the
    sandbox blocks the open(), not the write. One failure then set S.fileio
    False and the log was dead for the rest of the day, which is what feeds
    _restore_from_log after a restart.

    Two changes. Keep ONE handle, so the day costs a single open() instead of
    one per order. And on failure retry later instead of giving up forever:
    the block was intermittent (the run log and exec CSV, both of which hold
    handles, kept writing normally from the same directory the whole time).

    Still never fatal. Every path here swallows its exception and returns; the
    caller places its order either way.
    """
    if S.tradefh is False:
        return
    now = dt.datetime.utcnow()
    if S.tradefh is None:
        # Retry cooldown, so a permanently blocked sandbox costs one open() a
        # minute rather than one per order.
        if S.tradefh_retry and (now - S.tradefh_retry).total_seconds() < 60.0:
            return
        S.tradefh_retry = now
        _why = None                 # why the preferred directory was refused
        for d in (TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS, RUN_LOG_DIR, "C:\\Users\\Public\\Documents"):
            try:
                p = (d + "\\trades_" + STRATEGY + "_" + _acct_tag()
                     + "_" + day + ".csv")
                fh = open(p, "a")
                if fh.tell() == 0:
                    fh.write("bar_time,side,code,shares,price_or_remark\n")
                fh.flush()
                S.tradefh = fh
                S.tradefh_path = p
                if p != _log_path(day):
                    print("  trade log -> " + p + " (preferred dir refused: "
                          + repr(_why) + ")")
                break
            except Exception as e:
                if _why is None:
                    _why = e        # the FIRST refusal is the one worth naming
                continue
        if S.tradefh is None:
            return                      # try again after the cooldown
    try:
        S.tradefh.write("%s,%s,%s,%d,%s\n"
                        % (bar_time, side, code, int(shares), extra))
        S.tradefh.flush()
    except Exception as e:
        print("trade log write failed, will reopen:", repr(e))
        try:
            S.tradefh.close()
        except Exception:
            pass
        S.tradefh = None


def _restore_from_log(C, day):
    """Restart recovery WITHOUT reading broker positions: replay today's own
    trade log to learn how much of each name this strategy already bought.

    Caveat, stated plainly: the log records what was SENT, not what actually
    FILLED. In LIVE the broker position is the authority and is still used for
    the delta maths; this restore only re-seeds the PREVIEW paper book and
    reports what the log says."""
    if not RESTORE_FROM_LOG:
        return
    bought = {}
    lines = []
    # Search every directory _log_trade may have fallen back to. Reading only
    # the preferred path would miss the whole day's records whenever the
    # sandbox pushed the writer elsewhere -- which is exactly the case a
    # restart needs to recover from.
    for d in (TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS, RUN_LOG_DIR, "C:\\Users\\Public\\Documents"):
        try:
            # A plain read of a file a PREVIOUS session wrote. _open_varying
            # is for creating and appending and returns a tuple, so it does not
            # belong here -- an earlier version of this patch put it here and
            # the TypeError was swallowed by the except below, silently
            # emptying restore. Restart safety for this data now comes from
            # _fills_from_orders, which needs no file at all.
            f = open(d + "\trades_" + STRATEGY + "_" + _acct_tag()
                     + "_" + day + ".csv", "r")
            got = f.readlines()
            f.close()
            if len(got) > len(lines):
                lines = got
        except Exception:
            continue
    if not lines:
        return
    for ln in lines[1:]:
        parts = ln.strip().split(",")
        if len(parts) < 4:
            continue
        try:
            code = parts[2]
            bought[code] = bought.get(code, 0) + int(parts[3])
        except Exception:
            continue
    if not bought:
        return
    print("RESTORE from trade log:", len(bought), "name(s) bought today:",
          ", ".join("%s=%d" % (c, bought[c]) for c in sorted(bought)))
    S.bought_today |= set(bought)
    if S.preview:
        S.paper_pos = dict(bought)
        print("   -> PREVIEW paper book restored (no double-buy on restart)")
    else:
        print("   -> LIVE: broker position remains the authority for sizing")


def _fills_from_orders():
    """{code: shares filled today}, rebuilt from the broker's ORDER list.

    The same quantity the DEAL query answers, but per-order and with no file
    and no aggregate in the way -- so it survives a restart, and it does not
    inherit the DEAL list's habit of over-reporting (2026-08-31: DEAL claimed
    50,000 on 688800.SH while 141 order rows summed to the true 48,889).

    It matters more here than on the sell side. When DEAL comes back EMPTY
    after a restart -- observed 2026-08-26 -- _load_or_snapshot_baseline falls
    into the branch that treats the entire current position as pre-existing,
    reads cur as 0 for every name, and buys the whole basket a second time.

    Deduplicated by remark: the counter re-serves terminal rows every bar.
    Returns {} when the query is unavailable, which the caller must read as
    "no information", never as "nothing bought".
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
                continue
            if getattr(o, "m_nDirection", 48) != 48:
                continue                # buy side only
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


def _in_settle():
    """True while a mid-session restart is still observing.

    An order sent seconds before a restart is in neither place the new session
    can look: memory is gone and the counter has not acknowledged it yet.
    Everything else in the bar still runs, so the picture completes itself
    while this is True; only new orders are withheld.

    Measured on the wall clock, the same one every end-of-day boundary here
    uses, because a real-seconds version cannot be exercised offline -- the
    replay runs a whole session in a few real seconds.
    """
    if not getattr(S, "session_in_hours", False):
        return False                    # started pre-open: nothing in flight
    started = getattr(S, "session_started", None)
    if not started:
        return False
    age = _hhmmss_secs(_wall_hhmmss()) - _hhmmss_secs(started)
    if age < 0:
        return False                    # clock went backwards -> do not hold
    if age >= RESTART_SETTLE_SEC:
        if not getattr(S, "settle_said", False):
            S.settle_said = True
            print("  SETTLE COMPLETE after %.0fs -- any order in flight at the"
                  " restart is now in the counter's list and counted as"
                  " pending; sending resumes" % age)
        S.session_in_hours = False
        return False
    return True


def _filled_today(C):
    """Shares THIS strategy actually filled today, straight from the broker's
    DEAL list. fun.xml: strategyName filters ORDER and DEAL, and passorder was
    given STRATEGY, so this is proper attribution -- not "what we sent" but
    "what actually traded". Returns None when the query is unavailable."""
    # Unfiltered first; see the sell script's _sold_today for why. Every row is
    # re-checked against STRATEGY below, so the strategyName filter adds nothing,
    # and after a restart it appears to be scoped to the current strategy
    # instance and comes back EMPTY. Breaking out on a non-raising call then
    # reads "nothing filled today", which restarts the TWAP schedule from zero.
    # The buy side survived the 2026-08-03 restart only because
    # RESTORE_FROM_LOG rebuilt the same numbers from the trade CSV.
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
            if not S.deal_fields_dumped:
                S.deal_fields_dumped = True
                if DEBUG_DUMP_FIELDS:
                    _dump_obj("DEAL row (field survey)", o)
            # if the query was not strategy-filtered, fall back to our remark prefix
            rem = getattr(o, "m_strRemark", "") or ""
            nm = getattr(o, "m_strStrategyName", "") or ""
            if STRATEGY not in rem and STRATEGY not in nm:
                continue
            code = getattr(o, "m_strInstrumentID", "") + "." + getattr(o, "m_strExchangeID", "")
            vol = 0
            for a in ("m_nVolume", "m_nTradedVolume", "m_nVolumeTraded"):
                v = getattr(o, a, None)
                if v:
                    vol = int(v); break
            if code and vol:
                out[code] = out.get(code, 0) + vol
        except Exception:
            continue
    return out


def _baseline_path(day):
    return (TRADE_LOG_DIR + "\\baseline_" + STRATEGY + "_" + _acct_tag()
            + "_" + day + ".csv")


def _load_or_snapshot_baseline(C, day):
    """Pre-existing holdings of the TARGET names, so they are excluded from the
    delta maths. Loaded from disk if this is a restart, otherwise snapshotted now
    and written out. Returns None when it cannot be trusted (no file IO), in which
    case the caller keeps the safe absorb behaviour."""
    if not IGNORE_PREEXISTING or S.preview:
        return None
    path = _baseline_path(day)
    # restart: a baseline for today already exists -> reuse it, never re-snapshot
    try:
        f = open(path, "r")
        lines = f.readlines()
        f.close()
        base = {}
        for ln in lines[1:]:
            p = ln.strip().split(",")
            if len(p) >= 2:
                base[p[0]] = int(p[1])
        print("BASELINE loaded from disk:", len(base), "name(s) held before this run")
        return base
    except Exception:
        pass
    # No baseline file. That is EITHER a genuine first run, OR a restart whose
    # file was lost -- and snapshotting in the second case would swallow our own
    # fills into the baseline and buy the whole basket a second time. Ask the
    # broker what this strategy already filled today and subtract it.
    held = _positions(C)
    filled = _filled_today(C)
    _from_orders = _fills_from_orders()
    if _from_orders:
        # Merge, taking the larger per name. A DEAL list that came back empty
        # after a restart is exactly the case that made the branch below treat
        # today's purchases as pre-existing holdings.
        filled = dict(filled or {})
        for _c, _q in _from_orders.items():
            if _q > filled.get(_c, 0):
                filled[_c] = _q
    if filled:
        base = {}
        for c in TARGETS:
            h = held.get(c, 0)
            if h != 0:                      # keep shorts: see the != 0 note above
                base[c] = h - filled.get(c, 0)
        print("BASELINE rebuilt from broker fills (no file):",
              ", ".join("%s=%d" % (c, v) for c, v in sorted(filled.items()) if v))
    else:
        # != 0, not > 0. m_nVolume is a NET position, so a pre-existing SHORT
        # silently cancels our buying: 600958.SH showed vol=500 from
        # yest=-1800 + onroad=2300, and skipping the negative baseline made the
        # strategy read 500 instead of the 2300 it had actually bought -- so it
        # kept buying. 002436.SZ was the same story against a -399 short.
        base = dict((c, held.get(c, 0)) for c in TARGETS if held.get(c, 0) != 0)
        if filled is None:
            print("BASELINE: DEAL query unavailable -> snapshot taken WITHOUT a"
                  " fills cross-check. Safe on a genuine first run; if this is a"
                  " restart with a lost baseline file, stop and check positions.")
    try:
        f = open(path, "w")
        f.write("code,shares" + chr(10))
        for c in sorted(base):
            f.write("%s,%d" % (c, base[c]) + chr(10))
        f.flush()
        f.close()
    except Exception as e:
        print("BASELINE could not be persisted:", repr(e))
        print("  -> falling back to absorbing existing holdings (under-buy, never double-buy)")
        return None
    if base:
        print("BASELINE snapshot:", len(base), "target(s) pre-held (not ours):",
              ", ".join("%s=%d" % (c, base[c]) for c in sorted(base)))
    else:
        print("BASELINE snapshot: none of the targets are currently held (clean start)")
    return base


def _own(held, code):
    """Shares of `code` that belong to THIS strategy run."""
    if S.baseline is None:
        return held.get(code, 0)
    return max(0, held.get(code, 0) - S.baseline.get(code, 0))


def _adopt_existing(C):
    """One-time on the open day: adopt what the account ALREADY holds.

    Why: after a mid-day restart the strategy state is empty but the broker still
    holds the shares. The per-name maths is already safe (delta = target - held,
    so a name is never bought twice), but slot accounting was not: a name bought
    via fallthrough (say rank 22) is not among the first SLOTS names, so the
    strategy would open 20 *more* positions on top of it and over-invest.
    Adopting held names into `active` makes them occupy their slot; the top-up
    loop then only opens as many new names as are still missing.

    PREVIEW has no broker state, so this is a no-op there unless PREVIEW_SEED is set.
    """
    if S.adopted or not ADOPT_EXISTING_POSITIONS:
        return
    S.adopted = True
    held = _positions(C)
    if not held:
        return
    st = S.buy_state
    # _own(), not raw held: a shared account may hold a target name for reasons
    # of its own (this sim account held 969m shares of 601988). Adopting that
    # into a slot would hand the slot to someone else's position.
    mine = [c for c in TARGETS if _own(held, c) > 0]
    for code in mine:
        if code not in st["active"] and code not in st["filled"]:
            st["active"].append(code)
    if mine:
        print("ADOPT", len(mine), "position(s) into slots:",
              ", ".join("%s=%d" % (c, _own(held, c)) for c in sorted(mine)))
    extra = [c for c in held if c not in set(TARGETS)]
    if extra:
        # Only ever print a sample. This was written for "a few leftovers from
        # last month"; a shared account with 1191 positions turned it into 1180
        # codes on one line.
        print("  NOTE:", len(extra), "other held name(s) not managed by this script")


# ---- BUY TWAP + fallthrough ----
def _available_cash(C):
    """Broker's available cash, or None when the query fails.

    None means "unknown", NOT "zero": the auction must still go out on an
    unreadable balance, because refusing to buy on a failed query is the same
    outcome as having no fallback at all. rows[0] is not reliably the stock
    account -- on 2026-07-30 it reported 10,857 while miniQMT showed
    101,455,281 for the same account in the same minute -- so match on id.
    """
    try:
        rows = get_trade_detail_data(S.acct, S.acct_type, "ACCOUNT") or []
    except Exception:
        return None
    pick = None
    for o in rows:
        if str(getattr(o, "m_strAccountID", "")) == str(S.acct):
            pick = o
            break
    if pick is None and rows:
        pick = rows[0]
    if pick is None:
        return None
    try:
        return float(getattr(pick, "m_dAvailable", 0) or 0)
    except Exception:
        return None


def _run_auction(C, today, hhmmss):
    """Last resort: put every slot's remaining shortfall into the closing call
    auction, priced at the limit-UP price. Sent ONCE.

    Mirrors the sell script's floor-priced auction, and rests on the same fact:
    a call auction clears every matched order at ONE price set by maximum
    volume, so a ceiling-priced buy means "fill me at whatever that price turns
    out to be", not "pay limit-up". It only ever pays the ceiling if the stock
    is sealed limit-up -- and a sealed name has no sellers, so it would not fill
    at any price.

    Why the buy side needs this at all: 2026-08-25 finished at 93.9% of target
    with four names stopping 700 shares short while filling 100% of everything
    they sent. Passive bids simply stop getting hit near the close. The sell
    side has had this fallback since 2026-08-24; the buy side had nothing, so a
    shortfall just stood.

    Sent once, deliberately. handlebar fires for 14:57, 14:58 and 14:59, the
    exchange refuses cancellation throughout, and a second pass would be a
    second position going out with no way to take it back.
    """
    if S.auction_done:
        return
    if _in_settle():
        # Delayed, not skipped: auction_done stays False so the next bar tries
        # again. The exchange takes orders until 15:00, so 14:58 plus a settle
        # is still inside the window, while skipping would leave the slot
        # unbuilt for the day.
        print("  AUCTION held: still settling after a restart")
        return
    S.auction_done = True
    st = S.buy_state
    names = sorted(set(list(st["filled"]) + list(st["active"])))
    if not names:
        print("  AUCTION: no slots to finish")
        return
    held = _positions(C)
    nav = _total_value(C)
    open_buy = _open_buy_qty(C)
    filled_today = dict(_filled_today(C) or {})
    for _c, _q in _fills_from_orders().items():
        if _q > filled_today.get(_c, 0):
            filled_today[_c] = _q
    # Floor it with our own durable record. max() per name, never a replace:
    # the broker's DEAL list is the finer-grained of the two while the process
    # lives, and this file is the only one that survives it dying.
    for _c, _v in _fills_from_disk(_today_str()).items():
        if _v > filled_today.get(_c, 0):
            filled_today[_c] = _v
    cash = _available_cash(C)
    w = 1.0 / SLOTS
    sent = 0
    committed = 0.0
    for code in names:
        # max(), not either alone: the position query lags a fill that has
        # already reached the DEAL list, and taking the smaller of the two here
        # would buy the same shares twice with no chance to cancel.
        cur = max(_own(held, code), int(filled_today.get(code, 0) or 0))
        pend = open_buy.get(code, 0)
        q = _quote(C, code, today, _prev_min(hhmmss))
        if q is None or q["close"] <= 0:
            continue
        tgt = _round_buy(code, nav * w / q["close"])
        left = tgt - cur - pend
        if left <= 0:
            continue
        up = _limit_up(C, code, q)
        if not up:
            print("  AUCTION skip %s: no limit-up price available" % code)
            continue
        qty = _round_buy(code, left)
        unit = _buy_unit(code)[0]
        if qty < unit:
            # No odd-lot exception on the buy side -- that concession exists for
            # LIQUIDATING a position, never for opening or topping one up. A
            # sub-lot buy is simply a rejected order.
            print("  AUCTION skip %s: %d short is under the %d-share minimum"
                  % (code, left, unit))
            continue
        # Cash is frozen at the price we name, so budget at the ceiling even
        # though the auction will almost certainly clear far below it. Shrink
        # rather than skip: a partial top-up beats none.
        if cash is not None and cash > 0:
            room = cash - committed
            if qty * up > room:
                qty = _round_buy(code, int(room / up))
                if qty < unit:
                    print("  AUCTION skip %s: %.0f cash left will not cover one"
                          " lot at the %.2f ceiling" % (code, room, up))
                    continue
                print("  AUCTION %s trimmed to %d by available cash" % (code, qty))
        committed += qty * up
        _order_buy(C, code, qty, "%s_auction_%s_%s" % (STRATEGY, code, hhmmss),
                   limit_px=up)
        sent += 1
        print("  AUCTION %s %d shares at the ceiling %.2f (clears at the auction"
              " price, not the ceiling)" % (code, qty, up))
    print("  AUCTION: %d order(s) placed, %.0f yuan committed at the ceiling;"
          " no cancellation is possible until 15:00" % (sent, committed))


def _run_buys(C, today, hhmmss):
    if S.buy_done:
        return
    # Poll the mode file first, so the price type and the spread filter agree
    # within this pass.
    _changed = _refresh_price_mode()
    if _changed:
        # Resting orders were priced under the OLD mode and cannot re-price
        # themselves, so they get pulled -- but only on the names that actually
        # changed. Disturbing the rest of the book would defeat the purpose of
        # making the switch per-name.
        print("  price mode changed for %s -> resting orders on those names"
              " will be cancelled and re-quoted"
              % ("every name" if "*" in _changed else ", ".join(sorted(_changed))))
    slots = SLOTS
    w = 1.0 / slots
    st = S.buy_state
    _adopt_existing(C)          # restart-safe: held names occupy their slots first
    held = _positions(C)
    nav = _total_value(C)
    open_buy = _open_buy_qty(C)
    # What the BROKER says this strategy has filled today. Used as a floor on
    # the delta maths below, alongside the session-scoped S.sent_qty.
    #
    # S.sent_qty resets on restart, and the gap it covers does not: an order
    # that fills instantly reaches status 56, which is terminal, so it leaves
    # `open_buy`, while the position query has not caught up and `cur` is still
    # 0. Both read zero and the whole slice goes out again -- that is how
    # 003816.SZ was sent 1900 shares against a 700-share schedule this morning.
    # The DEAL query is broker-side and day-scoped, so it survives a restart and
    # closes the window that S.sent_qty alone leaves open. None means the query
    # was unavailable; fall back rather than treating it as "nothing filled".
    filled_today = dict(_filled_today(C) or {})
    for _c, _q in _fills_from_orders().items():
        if _q > filled_today.get(_c, 0):
            filled_today[_c] = _q
    # Floor it with our own durable record. max() per name, never a replace:
    # the broker's DEAL list is the finer-grained of the two while the process
    # lives, and this file is the only one that survives it dying.
    for _c, _v in _fills_from_disk(_today_str()).items():
        if _v > filled_today.get(_c, 0):
            filled_today[_c] = _v
    frac = 1.0 if _sess_min(hhmmss) >= _sess_min(BUY_END) else max(0.0, _sess_min(hhmmss) / float(_sess_min(BUY_END)))
    eod = hhmmss >= "150000"

    def pull_next():
        i = st["queue_i"]
        while i < len(TARGETS):
            code = TARGETS[i]; i += 1
            if code in st["filled"] or code in st["active"]:
                continue
            st["queue_i"] = i; return code
        st["queue_i"] = i; return None

    while len(st["filled"]) + len(st["active"]) < slots:
        nxt = pull_next()
        if nxt is None:
            break
        st["active"].append(nxt)

    for code in list(st["active"]):
        cur = _own(held, code)      # only what THIS run bought, not pre-existing
        pend = open_buy.get(code, 0)
        rank = st["rank_of"].get(code, -1)
        unit = _buy_unit(code)[0]
        # Use the last COMPLETED bar for price AND volume. The bar labelled
        # `hhmmss` is still forming (QMT stamps it with its closing minute) and
        # has zero volume at the moment we act, which would skip every name.
        # This also matches the backtest, which always saw completed bars.
        q = _quote(C, code, today, _prev_min(hhmmss))

        # (1) NO QUOTE / NO VOLUME must be judged FIRST. A missing bar is NOT
        # "unaffordable" -- at 09:30 most names have no print yet. Keep waiting;
        # only fall through after 10:00 if the name never traded since the open.
        # (0) NEVER OPEN A NEW POSITION IN AN ST NAME. Fall through to the next
        # rank instead. Only when we hold nothing: if this run already bought
        # some -- the tag can appear intraday -- keep the name and let the
        # normal path finish it, because a half-built slot is worse than a full
        # one and the SELL script will clear it on the close day either way.
        #
        # Measured before adding this: across all four plan files, 217,453 rows
        # in total, the number that were ST on their own trade date is ZERO. The
        # upstream universe already excludes them, so this changes nothing about
        # historical behaviour and needs no re-backtest -- it is insurance for
        # the day that upstream filter breaks, not a strategy change.
        if cur <= 0 and _is_st(C, code, q):
            st["active"].remove(code); _skip(hhmmss, rank, code, "st_no_new_position")
            continue

        if q is None or q["close"] <= 0 or q["volume"] == 0:
            # The third silent path, and the one that leaves no trace at all: a
            # bar with no volume is skipped with no line, so a thin name can
            # spend the whole last hour here and look, in the log, exactly like
            # a name that was already finished. Only report it after BUY_END,
            # where it actually costs something, and only once per name --
            # before that a quiet minute is unremarkable.
            _prev0 = S.hold_said.get(code)
            _nm0 = _sess_min(hhmmss)
            if finishing_window(hhmmss) and (
                    _prev0 is None or _prev0[0] != "novol"
                    or (_nm0 - _prev0[1]) >= HOLD_REPEAT_MIN):
                S.hold_said[code] = ("novol", _nm0)
                print("  HOLD", code, "cur", int(cur),
                      "-> bar has no volume, cannot size a slice this minute")
            if cur <= 0 and hhmmss >= NO_TRADE_CUTOFF and not _traded_since_open(C, code, today, hhmmss):
                st["active"].remove(code); _skip(hhmmss, rank, code, "no_trade_by_1000")
            elif eod:
                st["active"].remove(code)
                if cur > 0:
                    st["filled"].add(code)
                else:
                    _skip(hhmmss, rank, code, "no_trade")
            continue                      # otherwise just wait for the next bar

        # (2) from here the quote is valid, so the target is meaningful
        tgt = _round_buy(code, nav * w / q["close"])
        # Remember the first target so the RETIRE line can show how far it
        # drifted. nav*w is a fixed yuan budget, so the SHARE target moves
        # inversely with price all day; a name that rallies needs fewer
        # shares to hold the same money, and "short 300 shares" at 10:00 can
        # legitimately be "short 0" by 14:00 without a single extra fill.
        S.tgt_first.setdefault(code, tgt)

        # Short by less than one tradable lot: normally that means "done". But on
        # STAR/BJ the minimum order is 200 shares while the step is 1, so a
        # volume-capped partial fill can leave the name up to 199 shares short --
        # on a 24 CNY stock that is ~40% of the slot. Once the TWAP window is
        # over, top it up by one minimum lot, as long as the overshoot stays
        # within TOPUP_OVERSHOOT of the per-name budget.
        # Worth it only when the shortfall exceeds the overshoot the top-up would
        # create: buying one lot leaves us (unit - short) over, so top up only if
        # short > unit/2. Observed 2026-07-28: a 2-share gap triggered a 200-share
        # lot, overshooting the slot by 14% to fix a 0.14% shortfall.
        short = tgt - cur
        if (cur > 0 and short > unit / 2 and short < unit and hhmmss >= BUY_END
                and (cur + unit) * q["close"] <= (nav * w) * (1.0 + TOPUP_OVERSHOOT)):
            print("  TOPUP", code, "short", int(short), "of min lot", unit,
                  "-> buying one lot (short > half a lot, so worth the overshoot)")
            if _in_settle():
                continue        # settling: the top-up can wait a bar
            _order_buy(C, code, unit, "%s_topup_%s_%s" % (STRATEGY, code, hhmmss))
            st["filled"].add(code); st["active"].remove(code); continue
        # ONLY after BUY_END. Without the time test this fires the moment a name
        # is short by less than one lot -- and it sits BEFORE the TOPUP branch
        # above, which needs hhmmss >= BUY_END. So the name was retired from
        # st["active"] hours early and TOPUP, written for exactly this case,
        # never got a chance to run. 2026-08-04, first live day: 688357.SH was
        # marked done at 11:12 holding 200 of 372 (short 172, more than half a
        # 200-share lot -> TOPUP would have bought one), and 688567.SH the same
        # at 817 of 968. 6,166 CNY of the 200,000 budget never got invested.
        # Leaving them in the queue costs nothing: the slice arithmetic below
        # yields 0 for a sub-lot gap anyway, so they simply idle until 14:00 and
        # then either top up or retire here.
        if cur > 0 and (tgt - cur) < unit and hhmmss >= BUY_END:
            # Say so. This branch retired names SILENTLY, which on 2026-08-25
            # made four of them impossible to account for after the close:
            # 002133.SZ stopped at 3,300 of a 3,600 target having filled 100%
            # of everything it ever sent, and the log carried not one line
            # explaining it. `tgt` is recomputed every bar from nav*weight/price,
            # so a name whose price rose during the session sees its target
            # SHRINK -- which is very likely what closed that gap -- but nothing
            # printed the numbers, so it stayed a guess. Print them.
            print("  RETIRE", code, "cur", int(cur), "tgt", int(tgt),
                  "short", int(tgt - cur), "< one lot", unit,
                  "| sent", int(S.sent_qty.get(code, 0)),
                  "-> slot complete (target moves with price; it was",
                  S.tgt_first.get(code, tgt), "at its first sizing)")
            st["filled"].add(code); st["active"].remove(code); continue
        if cur <= 0 and tgt <= 0:         # genuinely cannot afford one lot
            st["active"].remove(code); _skip(hhmmss, rank, code, "unaffordable"); continue
        sealed, why = _sealed_up(C, code, q)
        if sealed:
            if code not in S.sealed_said:
                S.sealed_said.add(code)
                print("  LIMIT-UP %s -> not sending (%s)" % (code, why))
            if cur <= 0 and hhmmss >= LIMIT_UP_CUTOFF:
                st["active"].remove(code); _skip(hhmmss, rank, code, "limit_up_13h")
            elif cur > 0 and eod:
                st["filled"].add(code); st["active"].remove(code)
            continue
        elif code in S.sealed_said:
            S.sealed_said.discard(code)
            print("  LIMIT-UP RELEASED %s -> resuming (%s)" % (code, why))

        twap_target = _round_buy(code, tgt * frac)
        # Never size a slice as if nothing had been sent. An order that fills
        # instantly reaches status 56, which is TERMINAL, so it drops out of
        # `pend` -- while the position query still lags, leaving `cur` at 0 too.
        # Both read zero and the whole slice goes out again. On 2026-07-31 that
        # sent 003816.SZ 1900 shares against a schedule of 700, and one more
        # pass would have overshot its 2400 target. What we have sent this
        # session is a floor on what we hold, so take the larger of the two.
        # If an order genuinely dies, this under-buys, and MAX_ORDER_ATTEMPTS
        # plus rank-fallthrough already handle that -- under-buying is the safe
        # direction, over-buying is not.
        sent = S.sent_qty.get(code, 0)
        delta = twap_target - max(cur + pend, sent, filled_today.get(code, 0))
        # After BUY_END the TWAP schedule is over and the target is full, so stop
        # enforcing the min-slice size -- otherwise a name that is short by less
        # than MIN_ORDER_AMT would wait for the 15:00 eod branch, i.e. never fill
        # in live trading. finishing = "just complete the order".
        finishing = hhmmss >= BUY_END
        if delta < unit or (delta * q["close"] < MIN_ORDER_AMT and not finishing):
            # Also silent until now, and it is the branch a name sits in for
            # hours: 002133.SZ went 10:54 -> 13:04 without a single line,
            # because delta*price stayed under MIN_ORDER_AMT (100 shares at
            # 2.75 is 275 yuan against a 2,000 floor) so it waited to
            # accumulate a worthwhile slice. Correct behaviour, invisible
            # behaviour. Report it once per name per reason, not once per bar:
            # twenty names times 240 bars would bury the log.
            # Dedupe on the KIND of hold, not on the numbers in it. `delta`
            # moves every bar as the TWAP target grows, so keying the dedupe on
            # the rendered string made it print once a minute for every waiting
            # name -- 24 lines in the first two minutes of 2026-08-26, on course
            # for thousands. The kind changes maybe twice a session.
            #
            # Still re-report every HOLD_REPEAT_MIN so a name that has been
            # parked for an hour is visibly still parked rather than silently
            # forgotten, which is the failure this logging exists to prevent.
            _kind = "sublot" if delta < unit else "minamt"
            _why = ("delta %d < one lot %d" % (int(delta), unit)
                    if delta < unit else
                    "slice %d x %.2f = %.0f yuan < MIN_ORDER_AMT %.0f, waiting"
                    % (int(delta), float(q["close"]), delta * q["close"],
                       MIN_ORDER_AMT))
            _now_m = _sess_min(hhmmss)
            _prev = S.hold_said.get(code)
            if _prev is None or _prev[0] != _kind or \
                    (_now_m - _prev[1]) >= HOLD_REPEAT_MIN:
                S.hold_said[code] = (_kind, _now_m)
                # ALL FOUR terms of the delta, not just cur and pend.
                #
                # delta = twap - max(cur + pend, sent, filled_today), and on
                # 2026-08-25 four names stopped 700 shares short with the first
                # version of this line printing only cur/pend/tgt/twap. Those
                # numbers said delta should have been 100-300 -- comfortably
                # over a lot -- so the binding term had to be `sent` or
                # `filled_today`, and neither was on the line. Two other
                # explanations were checked against the tape and ruled out:
                # the bars had volume (60-71 of 77 could have funded a slice),
                # and no price came near the level where the share target
                # collapses. Print the whole expression or this repeats.
                _mx = max(cur + pend, sent, int(filled_today.get(code, 0) or 0))
                print("  HOLD", code, "cur", int(cur), "pend", int(pend),
                      "sent", int(sent), "dealt",
                      int(filled_today.get(code, 0) or 0),
                      "-> max", int(_mx), "| tgt", int(tgt),
                      "twap", int(twap_target), "delta", int(delta), "->", _why)
            if eod and cur > 0:
                st["filled"].add(code); st["active"].remove(code)
            continue
        S.hold_said.pop(code, None)
        capvol = int(q["volume"])                                    # completed bar, in lots
        cap = int(PARTICIPATION * capvol * VOL_LOT_TO_SHARES)        # lots -> shares
        buy_qty = _round_buy(code, min(delta, cap))
        if buy_qty < delta:               # diagnostic: is the volume cap binding?
            print("  CAPPED", code, "want", int(delta), "-> cap", cap,
                  "(prev bar", capvol, "lots, px %.2f)" % float(q["close"]))
        if buy_qty < unit:
            if eod and cur > 0:
                st["filled"].add(code); st["active"].remove(code)
            continue
        wide, info = _spread_wide(C, code, hhmmss)
        if wide:
            print("  WIDE SPREAD skip", code, info, "-> retry next bar")
            continue                       # stays active; TWAP catches up later

        # Progress check: an order that neither fills nor rests leaves cur+pend
        # unchanged, so the same slice would be re-sent every bar forever.
        # Progress must be measured on FILLS, not on the position query alone.
        # `cur` comes from POSITION, which lags: all morning it read 0 while
        # orders were filling, so a name could look stalled while it was quietly
        # working -- exactly the false give-up that cost 601398.SH on the sell
        # side. The sell script already keys this off its DEAL-sourced `sold`;
        # this brings the buy side level. `pend` is deliberately NOT included:
        # a newly resting order is not acquisition, and counting it would reset
        # the counter every bar and disarm the guard completely.
        got = max(cur, filled_today.get(code, 0))
        if got > S.progress.get(code, -1):
            S.progress[code] = got
            S.attempts[code] = 0           # we moved -> forgive earlier failures
        tries = S.attempts.get(code, 0)
        if tries >= MAX_ORDER_ATTEMPTS:
            st["active"].remove(code)
            _skip(hhmmss, rank, code, "no_progress_after_%d_orders" % tries)
            continue                       # slot freed -> fall through to next name

        # Show what the strategy believes it holds. 600958 was bought six times
        # on 2026-07-29 because cur read 0 on every bar while the fills were
        # real; printing cur/pend/target makes that visible immediately.
        if _in_settle():
            print("  SETTLING", code, "-- holding new orders until the counter"
                  " has reported anything in flight at the restart")
            continue
        print("  sizing %s cur %d pend %d tgt %d twap %d -> buy %d (try %d)"
              % (code, cur, pend, tgt, twap_target, buy_qty, tries + 1))
        # Sealed limit-down: QUEUE quotes at bid-1 and there is no bid, so the
        # configured mode cannot ask for a stock the strategy wants and the
        # market is desperate to hand over. Price it AT THE FLOOR instead.
        #
        # A limit buy can never execute above its own limit, and the floor is
        # the lowest price the day permits -- so this either fills at the floor
        # or does not fill at all. If the read is wrong and the board is
        # actually open, the order simply rests unfilled and the next bar goes
        # back to QUEUE: being wrong costs nothing, which is why this is safe
        # to do automatically rather than by flipping price_mode by hand.
        #
        # Deliberately NOT the counterparty price. prType 14 resolves ask-1 at
        # the instant the order lands, so a board that unseals in that moment
        # would have us lifting offers above the floor -- paying up for the
        # one case where paying up is least justified.
        _sd, _floor = _sealed_down(C, code, q)
        if _sd:
            if code not in S.sealed_down_said:
                S.sealed_down_said.add(code)
                print("  SEALED LIMIT-DOWN %s -> buying AT THE FLOOR %.2f"
                      " (no bid to queue behind; a limit there cannot fill"
                      " higher)" % (code, _floor))
            _fr = "%s_%s_%s" % (STRATEGY, code, hhmmss)
            S.floor_orders[_fr] = _floor
            _order_buy(C, code, buy_qty, _fr, limit_px=_floor)
        else:
            if code in S.sealed_down_said:
                S.sealed_down_said.discard(code)
                print("  LIMIT-DOWN RELEASED %s -> back to %s"
                      % (code, _price_mode(code)))
            _order_buy(C, code, buy_qty, "%s_%s_%s" % (STRATEGY, code, hhmmss))
        S.attempts[code] = tries + 1
        if eod:
            st["active"].remove(code)
            if cur > 0:
                st["filled"].add(code)
            else:
                _skip(hhmmss, rank, code, "order_fail")

    while len(st["filled"]) + len(st["active"]) < slots:
        nxt = pull_next()
        if nxt is None:
            break
        st["active"].append(nxt)

    if len(st["filled"]) >= slots or (not st["active"] and st["queue_i"] >= len(TARGETS)):
        S.buy_done = True
        print("BUY DONE", today, hhmmss, "filled", len(st["filled"]), "slots", slots)


# ---- lifecycle ----
def _today_str():
    """The EXCHANGE date, for naming per-day files.

    The LATER of the Beijing wall clock and the bar date -- never either alone.

    Bar date alone is wrong BEFORE THE OPEN, when the newest completed bar still
    belongs to the previous session. On 2026-08-03 at 08:29 that made this
    script append its start-up lines to run_combo_buy_open_20260731.log,
    merging two trading days into one file -- the exact thing these per-day
    names exist to prevent. Wall clock alone is wrong if this PC's timezone is
    off (it runs US Eastern, so every date here is utcnow()+8h). Taking the
    later of the two is right in both directions.

    Never OPEN_DATE: that constant is hand-edited, so a stale value would merge
    two trading days into one file.
    """
    wall = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
    n = getattr(S, "now", "")
    bar = n[:8] if (n and len(n) >= 8) else ""
    return bar if bar > wall else wall


def _start_run_log():
    """Open the run log. Never fatal: without it the strategy still trades."""
    if S.logfh is not None and S.logfh_day != _today_str():
        try:
            S.logfh.flush(); S.logfh.close()
        except Exception:
            pass
        S.logfh = None
    if S.logfh is not None:
        return
    day = _today_str()
    fh, path, d = _open_varying(
        (RUN_LOG_DIR, TRADE_LOG_DIR, LEGACY_DIR, LEGACY_LOGS,
         "C:\\Users\\Public\\Documents"),
        "run_" + STRATEGY + "_" + day, ".log", "a")
    if fh is not None:
        fh.write("=== session start " + _china_now() + " ===\n")
        fh.flush()
        S.logfh = fh
        S.logfh_day = day
        S.runlog_dir = d
        S.runlog_path = path
        print("RUN LOG -> " + path)
        return
    print("NOTE: no writable directory for the run log; console only")


def init(C):
    _start_run_log()
    try:
        S.acct = account
        S.acct_type = accountType
    except NameError:
        S.acct = ""; S.acct_type = "STOCK"
        print("WARN: no injected account; bind an account in the QMT model GUI")
    S.buy_code = 23 if S.acct_type == "STOCK" else 33
    S.preview = (not S.acct)                 # no bound account -> PREVIEW (simulate, no real order)
    S.paper_pos = {}
    S.buy_state = {"queue_i": 0, "active": [], "filled": set(),
                   "rank_of": dict((c, i + 1) for i, c in enumerate(TARGETS))}
    S.buy_done = False
    S.data_today = set()
    S.limit_cache = {}
    S.waiting = []
    S.order_time = {}
    S.blotter = []
    S.suspend = []
    S.cur_day = None
    S.universe_set = False
    S.now = ""
    S.stale_bar_said = ""
    S.st_cache = {}         # code -> is ST today (asked of the broker once)
    S.st_said = set()       # codes already announced, so the log says it once
    S.sealed_said = set()   # codes currently reported as limit-up sealed
    S.tradefh = None        # trade CSV handle, held open all day
    S.tradefh_path = ""
    S.tradefh_retry = None  # last open() attempt, for the retry cooldown
    S.date_reported = None
    S.preopen_reported = False
    S.hb_min = None
    S.last_acted_bar = None
    S.adopted = False
    S.baseline = None
    S.order_fields_dumped = False
    S.deal_fields_dumped = False
    S.pos_rows_reported = False
    S.pos_fields_dumped = False
    S.bought_today = set()
    S.zero_reported = {}
    S.pos_ok = True
    S.attempts = {}
    S.progress = {}
    S.tick_ok = None            # None = not probed yet, True/False = last state
    S.order_real_time = {}      # remark -> real placement time
    S.cancel_inflight = set()
    S.tgt_first = {}           # code -> target at its first valid quote
    S.auction_done = False     # the closing-auction top-up is sent once
    S.hold_said = {}           # code -> (reason kind, bar minute last said)
    S.cancel_sent = {}         # remark -> utcnow() of the last cancel we sent
    S.cx_tries = {}            # remark -> cancels sent that changed nothing
    S.cx_sig = {}              # remark -> (status, left) when the last one went
    S.cx_first = {}            # remark -> utcnow() of the first such cancel
    S.zombies = set()          # remarks the counter will not let us cancel
    S.zombie_credited = set()  # ...whose remainder was already given back
    S.rejected_seen = set()
    S.sent_qty = {}             # code -> shares sent this session (floor for delta)
    S.fill_px = {}              # code -> [shares, sum(shares*price)] for the summary
    S.pend_released = set()     # orders released from pend after PEND_INVISIBLE_MAX_SEC
    S.waiting_said = None       # last waiting set reported, to stop the pause spam
    S.floor_cache = {}          # code -> the day's limit-down price
    S.sealed_down_said = set()  # codes already reported as sealed limit-down
    S.floor_orders = {}         # remark -> floor price, for orders priced there
    S.price_mode = None         # default mode; set on the first refresh
    S.mode_by_code = {}         # per-name overrides read from PRICE_MODE_FILE
    S.exec_open = {}            # remark -> touch snapshot at placement
    S.execfh = None
    S.exec_orphans = set()  # orders recorded without a local record, once each
    S.fillfh = None         # ONE handle for the day, like execfh.
                            # Opening per record is what emptied
                            # the fill record on 2026-09-01: the
                            # sandbox takes the open that CREATES
                            # a file and refuses every open of one
                            # that already exists.
    S.fillfh_day = ""
    S.fileio = False
    try:
        C.set_universe(["000001.SZ"])
    except Exception:
        pass
    print("INIT buy-open | OPEN_DATE", OPEN_DATE, "| account", repr(S.acct), S.acct_type,
          "| targets", len(TARGETS), "slots", SLOTS,
          "| MODE:", "PREVIEW (no account: simulate in-memory, NO real orders)" if S.preview else "LIVE")
    # WHERE THE FILES ACTUALLY WENT. The chooser prints its verdict to the QMT
    # console only, which is not where anyone looks afterwards; on 2026-09-01
    # finding the sell script's log meant searching the disk.
    print("  FILES ->", (getattr(S, "runlog_dir", None) or RUN_LOG_DIR),
          "" if (getattr(S, "runlog_dir", None) or RUN_LOG_DIR) == RUN_LOG_DIR
          else "   <-- NOT the configured RUN_LOG_DIR (" + RUN_LOG_DIR + ")")
    # Wall clock at init, for the settle window. An order sent seconds before a
    # restart is in neither memory nor the counter's order list until it is
    # acknowledged, so a session that begins mid-day must observe before it
    # sends. A session that began pre-open has already waited hours.
    S.session_started = _wall_hhmmss()
    S.session_in_hours = ("092500" <= S.session_started <= "150000")
    S.settle_said = False
    if S.session_in_hours:
        print("  RESTART SETTLE: this session began during trading hours, so it"
              " will observe for %.0fs before sending anything."
              % RESTART_SETTLE_SEC)
    # REFUSE TO RUN AGAINST AN ACCOUNT THIS BASKET WAS NOT WRITTEN FOR.
    S.blocked = bool(ALLOWED_ACCOUNTS) and str(S.acct) not in ALLOWED_ACCOUNTS
    if S.blocked:
        print("  " + "!" * 70)
        print("  !! WRONG ACCOUNT. Bound to", repr(S.acct), "but this basket"
              " belongs to", ", ".join(ALLOWED_ACCOUNTS))
        print("  !! NOTHING WILL BE BOUGHT. Re-bind the strategy, or edit"
              " ALLOWED_ACCOUNTS if the binding is correct.")
        print("  " + "!" * 70)
    # Report the price mode at INIT, not only on the first trading bar.
    # _run_buys polls the file, but the date gate returns before it on any day
    # that is not OPEN_DATE -- so on 2026-08-18 the log carried no PRICE MODE
    # line at all and there was no way to confirm, before the open, which
    # pricing the script would use. That is precisely what you want to check
    # while there is still time to change it.
    _refresh_price_mode()


def _ensure_universe(C):
    if S.universe_set:
        return
    # TARGETS only. Subscribing every held name floods set_universe with codes
    # this script never quotes -- a shared sim account held 1191 of them, many
    # bonds/repos/ETFs, and QMT logged them all as invalid.
    codes = list(TARGETS)
    codes.append("000001.SZ")
    try:
        C.set_universe(sorted(set(codes)))
    except Exception:
        pass
    S.universe_set = True


def handlebar(C):
    if getattr(S, "blocked", False):
        if not getattr(S, "blocked_said", False):
            S.blocked_said = True
            print("!! ALERT bound to account", repr(S.acct), "which is not in"
                  " ALLOWED_ACCOUNTS -- this script will not trade today")
        return
    if not C.is_last_bar():
        return
    today, hhmmss = _bar_datetime(C)
    S.now = today + hhmmss
    # ---- date verdict FIRST, so a pre-open run still says something ---------
    # This has to come before the freshness guard below. Before the open the
    # newest bar belongs to the PREVIOUS session, so the guard fires and returns
    # -- and "standing by, waiting for OPEN_DATE" is the single line that says
    # the script is alive and pointed at the right date. Losing it would have
    # made this morning's pre-open check impossible.
    if today != OPEN_DATE:
        if today != S.date_reported:
            S.date_reported = today
            if today < OPEN_DATE:
                print("WAIT buy-open | bar date", today, "< OPEN_DATE", OPEN_DATE,
                      "-> standing by, no buy | Beijing now", _china_now())
            else:
                print("PASSED buy-open | bar date", today, ">", OPEN_DATE,
                      "-> open date passed, no buy | Beijing now", _china_now())
        return
    # ---- the bar must be CURRENT, not whatever QMT had lying around ----------
    # QMT hands a restarting strategy its last bar, and that bar's label alone
    # satisfies every gate below. The sell script proved the consequence on
    # 2026-08-03: restarted at 12:56 in the lunch break, it saw bar 113000,
    # judged it inside the trading window, and sent eleven orders into a closed
    # market at 11:30's counterparty prices. This script was simply not
    # restarted at that moment; the exposure is identical.
    #
    # Raw minutes-of-day against the Beijing wall clock. A session-minute
    # comparison cannot see it: over the lunch break both 11:30 and 12:56 clamp
    # to the same elapsed-session minute.
    _bar_mod = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    _wall = dt.datetime.utcnow() + dt.timedelta(hours=8)
    _gap = abs((_wall.hour * 60 + _wall.minute) - _bar_mod)
    if _gap > STALE_BAR_MAX_MIN:
        if S.stale_bar_said != hhmmss:
            S.stale_bar_said = hhmmss
            print("STALE BAR %s vs Beijing %s (%d min apart) -- not trading."
                  " Market is closed or the feed is behind; waiting for a live bar."
                  % (hhmmss, _wall.strftime("%H:%M:%S"), _gap))
        return
    # ---- date gate: only act on OPEN_DATE; wait before, declare passed after ----
    if today != S.date_reported:
        S.date_reported = today
        # today == OPEN_DATE here; the other two cases already returned above.
        if today == OPEN_DATE:
            print("OPEN-DATE", OPEN_DATE, "| bar", today, hhmmss, "| building basket | MODE:",
                  "PREVIEW" if S.preview else "LIVE", "| account bound?", "YES" if S.acct else "NO",
                  "| Beijing now", _china_now())
            nav = _total_value(C)
            print("  BUDGET: %s = %.0f total -> %.0f per name x %d names"
                  % ("BUY_BUDGET (explicit)" if BUY_BUDGET > 0 else "account total asset",
                     nav, nav / SLOTS, SLOTS))
            if BUY_BUDGET <= 0:
                print("  !! no explicit BUY_BUDGET: sizing off the ACCOUNT TOTAL, which any"
                      " unrelated holding inflates. Set BUY_BUDGET at the top of this script.")
            if not S.preview:
                # BUY_BUDGET is a target market value; capital already stuck in
                # unsold leftovers is NOT deducted from it, so check the cash is
                # actually there before the last names get rejected at 14:00.
                cash = 0.0
                try:
                    rows = get_trade_detail_data(S.acct, S.acct_type, "ACCOUNT")
                    # Show EVERY row, not just rows[0]. On 2026-07-30 this
                    # reported 10,857 available while miniQMT read 101,455,281
                    # for the same account in the same minute, which suggests
                    # rows[0] is not the stock account. One line each settles it.
                    for _i, _o in enumerate(rows or []):
                        print("  ACCOUNT row %d: id=%r type=%r avail=%r bal=%r"
                              " asset=%r" % (_i,
                              getattr(_o, "m_strAccountID", None),
                              getattr(_o, "m_nAccountType", None),
                              getattr(_o, "m_dAvailable", None),
                              getattr(_o, "m_dBalance", None),
                              getattr(_o, "m_dAssureAsset", None)))
                    if rows:
                        # Prefer the row whose id matches the bound account.
                        pick = None
                        for _o in rows:
                            if str(getattr(_o, "m_strAccountID", "")) == str(S.acct):
                                pick = _o
                                break
                        if pick is None:
                            pick = rows[0]
                        cash = float(getattr(pick, "m_dAvailable", 0) or 0)
                except Exception:
                    pass
                held_now = _positions(C)
                print("  CASH CHECK: available %.0f vs budget %.0f | already holding %d name(s)"
                      % (cash, nav, len(held_now)))
                if cash > 0 and cash < nav:
                    print("  !! available cash < BUY_BUDGET: the last names will be rejected."
                          " Lower BUY_BUDGET, or free up capital stuck in unsold positions.")
            _probe_fileio_paths(today)     # survey: any writable dir at all?
            _probe_fileio(today)
            S.baseline = _load_or_snapshot_baseline(C, today)
            _restore_from_log(C, today)
    if today != OPEN_DATE:
        return
    if today != S.cur_day:
        S.cur_day = today; S.data_today = set(); S.limit_cache = {}
        S.universe_set = False; S.preopen_reported = False
    _ensure_universe(C)
    if not S.acct and not S.preview:         # no account and not preview -> nothing to do
        return
    if not _reconcile_waiting(C):
        # Once per distinct waiting set. handlebar fires on every tick of the
        # forming bar, so the undeduped version put out about 135 copies per
        # order and 1,482 lines on 2026-08-31 alone.
        _wkey = tuple(sorted(S.waiting))
        if _wkey != S.waiting_said:
            S.waiting_said = _wkey
            print("waiting unconfirmed orders, pause", S.waiting)
        return
    # hard guard: never order before 09:30 (call auction 09:15-09:25 is excluded)
    if hhmmss < BUY_START:
        if not S.preopen_reported:
            S.preopen_reported = True
            print("PRE-OPEN bar", hhmmss, "< BUY_START", BUY_START,
                  "-> NO order (call auction excluded)")
        return
    # act ONCE per bar. handlebar fires on every tick of the forming bar; the
    # backtest ran once per minute, so throttle here to match it and to avoid
    # slicing each minute into many tiny orders.
    if hhmmss == S.last_acted_bar:
        return
    S.last_acted_bar = hhmmss
    _cancel_stale_orders(C, today, hhmmss)    # free up stuck quotes before re-quoting
    # WALL CLOCK, not the bar label. The label runs 1-2 minutes ahead -- bar
    # 145700 was delivered at wall 14:55:58 on 2026-08-25 -- and gating on it
    # put the sell script's ceiling-priced batch into the CONTINUOUS session a
    # minute early on 2026-08-24, where a limit order at the band is just a
    # market order. Eight of them filled AT the floor for 4,017 yuan.
    if _wall_hhmmss() >= AUCTION_AT:
        _run_auction(C, today, hhmmss)
    else:
        _run_buys(C, today, hhmmss)
    # heartbeat once per minute so a quiet TWAP run is still visibly alive
    if hhmmss[:4] != S.hb_min:
        S.hb_min = hhmmss[:4]
        st = S.buy_state
        print("HB", hhmmss, "filled", len(st["filled"]), "active", len(st["active"]),
              "queue_i", st["queue_i"], "skipped", len(S.suspend))


def _stop_run_log():
    """Close the run log."""
    fh = S.logfh
    if fh is None:
        return
    S.logfh = None
    try:
        fh.flush()
        fh.close()
    except Exception:
        pass


def stop(C):
    st = S.buy_state
    filled = sorted(st["filled"])
    print("STOP buy-open | OPEN_DATE", OPEN_DATE, "| orders", len(S.blotter),
          "| filled", len(filled), "/", SLOTS, "| skipped", len(S.suspend))
    if S.suspend:
        print("  -- skipped (fell through) --")
        for hhmmss, rank, code, reason in S.suspend:
            print("   SKIP rank %-3s %-11s %s @%s" % (rank, code, reason, hhmmss))
    if getattr(S, "fill_px", None):
        # Quantity-weighted achieved price, to be scored against the session
        # VWAP afterwards. The exec CSV's slip_vs_mid measures each ORDER
        # against the touch it was sent into; this measures the DAY.
        print("  -- achieved average price (quantity-weighted) --")
        _tq = 0
        _tn = 0.0
        for _c in sorted(S.fill_px, key=lambda k: -S.fill_px[k][0]):
            _q, _nt = S.fill_px[_c]
            if _q <= 0:
                continue
            _tq += _q
            _tn += _nt
            print("   %-11s %7d shares @ %.4f" % (_c, _q, _nt / _q))
        if _tq:
            print("   %-11s %7d shares, notional %.2f (blended %.4f)"
                  % ("ALL", _tq, _tn, _tn / _tq))
    short = SLOTS - len(filled)
    if short > 0:
        print("  !! UNDER-FILLED: %d slot(s) not built. Held: %s" % (short, ", ".join(filled)))
    else:
        print("  OK: basket complete ->", ", ".join(filled))
    _stop_run_log()
