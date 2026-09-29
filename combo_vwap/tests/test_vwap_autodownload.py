#coding:utf-8
"""A name short of 1m history fetches it from inside the model, once.

2026-09-29: the live client had none of this history (0 of 62 names ready)
and the live account has no miniQMT. download_history_data, called from inside
a model, filled all 62 in about a minute. The trading scripts now make that
call themselves the first time a name cannot build its volume profile.

    python test_vwap_autodownload.py
"""
import datetime as dt
import importlib.util
import io
import contextlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
from test_vwap_schedule import Frame, history, rows_for, DAY, CODE
import vwap_schedule as V

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-62s %-16s %s" % (name, repr(got)[:16], "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


class Ctx(object):
    """History is empty until `fill()` is called -- as the live client was."""
    def __init__(self):
        self.hist, self.calls = [], []

    def fill(self):
        self.hist = history()

    def get_market_data_ex(self, fields, codes, **kw):
        self.calls.append(kw.get("end_time", ""))
        old = kw["end_time"][:8] < DAY
        return dict((c, Frame(self.hist if old else rows_for(DAY, [100.] * 180)))
                    for c in codes)


def run(sched, ctx, clocks=("100000",)):
    out = None
    for clk in clocks:
        out = sched.fraction(ctx, CODE, DAY, clk, clk, "093000", "140000")
    return out


print("=" * 90)
print("ENGINE")
print("=" * 90)
# 1. No downloader: unchanged behaviour -- the name blocks.
msgs = []
ctx = Ctx()
f = run(V.QmtVwapSchedule(msgs.append, dynamic=False), ctx)
check("no downloader: a name short of history blocks", f, None)
check("...and says so", any("VWAP BLOCK" in m for m in msgs), True)

# 2. A downloader that works: one call, then the profile builds.
msgs, dl = [], []
ctx = Ctx()


def good_dl(code, period, start, end):
    dl.append((code, period, start, end))
    ctx.fill()


f = run(V.QmtVwapSchedule(msgs.append, dynamic=False, downloader=good_dl), ctx)
d0 = dt.datetime.strptime(DAY, "%Y%m%d")
check("the download is asked for once, 1m, day-100 .. day-1",
      dl, [(CODE, "1m", (d0 - dt.timedelta(days=100)).strftime("%Y%m%d"),
            (d0 - dt.timedelta(days=1)).strftime("%Y%m%d"))])
check("...and the name is then ready", f is not None, True)
check("...with the download and the profile both in the log",
      (any("VWAP DOWNLOAD" in m for m in msgs), any("VWAP PROFILE" in m for m in msgs)),
      (True, True))
check("...and no BLOCK at all", any("VWAP BLOCK" in m for m in msgs), False)

# 3. A downloader that brings nothing: once only, however long the day.
msgs, dl = [], []
ctx = Ctx()
sched = V.QmtVwapSchedule(msgs.append, dynamic=False,
                          downloader=lambda *a: dl.append(a))
f = run(sched, ctx, clocks=("100000", "100500", "101000", "103000", "133000"))
check("a download that brings nothing is not repeated", len(dl), 1)
check("...the name stays blocked", f, None)

# 4. A downloader that raises: blocked, reported, no crash.
msgs = []
ctx = Ctx()


def bad_dl(*a):
    raise RuntimeError("server refused")


f = run(V.QmtVwapSchedule(msgs.append, dynamic=False, downloader=bad_dl), ctx)
check("a failing download blocks the name without raising", f, None)
check("...and the BLOCK line names the failure",
      any("VWAP BLOCK" in m and "download failed" in m for m in msgs), True)

# 5. History already present: nothing is downloaded.
dl = []
ctx = Ctx()
ctx.fill()
f = run(V.QmtVwapSchedule(lambda m: None, dynamic=False,
                          downloader=lambda *a: dl.append(a)), ctx)
check("enough history already: no download at all", (f is not None, dl), (True, []))

print()
print("=" * 90)
print("WIRING IN THE TWO TRADING SCRIPTS")
print("=" * 90)
for name in ("combo_buy_dual_model", "combo_sell_dual_model"):
    for on, present in ((True, True), (False, True), (True, False)):
        spec = importlib.util.spec_from_file_location(name + "_w", os.path.join(ROOT, name + ".py"))
        M = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(M)
        said = []
        M.print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
        M.log = lambda s: said.append(s)
        fake = lambda *a: None
        if present:
            M.download_history_data = fake
        M.VWAP_AUTO_DOWNLOAD = on
        M.S.vwap_scheduler = None
        M.S.wall_override = "100000"
        ctx = Ctx()
        ctx.fill()
        M._vwap_fraction(ctx, CODE, DAY, "100000")
        got = M.S.vwap_scheduler.downloader
        want = fake if (on and present) else None
        check("%s: switch %s, function %s -> downloader %s"
              % (name.split("_")[1], "on" if on else "off", "present" if present else "absent",
                 "wired" if want else "none"), got is want, True)
        check("...and the log says which", any("auto-download" in s for s in said), True)

print()
print("=" * 90)
print("PREFETCH: every profile loaded at start-up, not at the open")
print("=" * 90)
# Engine: prefetch loads -- and fetches -- NOW, and fraction() then reuses it.
msgs, dl = [], []
ctx = Ctx()
sched = V.QmtVwapSchedule(msgs.append, dynamic=False,
                          downloader=lambda *a: (dl.append(a), ctx.fill()))
check("prefetch fetches and loads a name short of history",
      sched.prefetch(ctx, CODE, DAY, "093000", "140000"), True)
n_calls = len(ctx.calls)
f = run(sched, ctx)
check("...and the open reuses it: no second load, no second fetch",
      (f is not None, len(dl), len(ctx.calls) - n_calls), (True, 1, 0))
ctx2 = Ctx()
check("prefetch without a downloader on a short name: not ready",
      V.QmtVwapSchedule(lambda m: None, dynamic=False).prefetch(
          ctx2, CODE, DAY, "093000", "140000"), False)

# Scripts: the start-up pass itself.
for name, targets_attr in (("combo_buy_dual_model", "TARGETS"),
                           ("combo_sell_dual_model", "SELL_TARGETS")):
    spec = importlib.util.spec_from_file_location(name + "_p", os.path.join(ROOT, name + ".py"))
    M = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(M)
    said = []
    M.print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
    M.log = lambda s: said.append(s)
    codes = ["600000.SH", "600001.SH", "600002.SH"]
    setattr(M, targets_attr, list(codes) if targets_attr == "TARGETS" else dict((c, 100) for c in codes))
    if name.startswith("combo_buy"):
        M.OPEN_DATE = DAY
    else:
        M.CLOSE_DATE = M.CLOSE_UNTIL = DAY
    fetched = []

    class PCtx(object):
        """600002.SH has nothing to give even after a fetch."""
        def __init__(self):
            self.have = set()

        def get_market_data_ex(self, fields, cs, **kw):
            c = cs[0]
            return {c: Frame(history() if c in self.have else [])}
    pc = PCtx()

    def fake_dl(code, period, s0, s1):
        fetched.append(code)
        if code != "600002.SH":
            pc.have.add(code)
    pc.have.add("600000.SH")                  # already on disk
    M.download_history_data = fake_dl
    M.VWAP_AUTO_DOWNLOAD = True
    M.S.vwap_scheduler = None
    M.S.vwap_prefetched = False
    M._today_str = lambda: "20260101"            # NOT the trading day
    M._vwap_prefetch(pc)
    check("%s: the evening before, nothing is loaded" % name.split("_")[1],
          (M.S.vwap_scheduler is None, fetched), (True, []))
    M._today_str = lambda: DAY
    M._vwap_prefetch(pc)
    line = [x for x in said if "VWAP PREFETCH" in x]
    check("%s: on the day, every target is tried once" % name.split("_")[1],
          sorted(fetched), ["600001.SH", "600002.SH"])
    check("...and one line says what is ready and what is not",
          (len(line) == 1 and "2/3 ready" in line[0] and "fetched 1m history for 2" in line[0]
           and "BLOCKED" in line[0] and "600002.SH" in line[0]), True)
    M._vwap_prefetch(pc)
    check("...and it runs once per session", len([x for x in said if "VWAP PREFETCH" in x]), 1)

# Wiring: handlebar runs it while it is still waiting for the open.
for name in ("combo_buy_dual_model", "combo_sell_dual_model"):
    spec = importlib.util.spec_from_file_location(name + "_h", os.path.join(ROOT, name + ".py"))
    M = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(M)
    M.print = lambda *a, **k: None
    M.log = lambda s: None
    calls, orders = [], []
    M._vwap_prefetch = lambda C: calls.append(1)
    M.passorder = lambda *a, **k: orders.append(a)
    M._bar_datetime = lambda C: ("20260928", "150000")      # yesterday's last bar
    if name.startswith("combo_buy"):
        M.OPEN_DATE = "20260929"
    else:
        M.CLOSE_DATE = M.CLOSE_UNTIL = "20260929"
    for a, v in (("stopped", False), ("blocked", False), ("said_wait", False),
                 ("said_passed", False), ("date_reported", None), ("order_time", {}),
                 ("preview", False), ("acct", "X")):
        setattr(M.S, a, v)
    M.S.wall_override = "073000"

    class HC(object):
        def is_last_bar(self):
            return True
    M.handlebar(HC())
    check("%s: handlebar runs the prefetch during the pre-open wait" % name.split("_")[1],
          (len(calls), orders), (1, []))

print()
print("ALL CHECKS PASSED" if not fails else "FAILED %d check(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
