#coding:utf-8
"""Bar times must be read as Beijing time whatever zone the PC runs in.

2026-09-28, first run of the data probe on this PC: 0 ready / 62, every name
"only 0 valid historical sessions". QMT labels a 1-minute frame's index in the
zone of the machine, and this one runs US Eastern, so Beijing 09:30 arrived as
21:30 the evening before. The engine read the labels as Beijing, its
09:31-14:54 filter matched nothing, and every name was blocked.

The frames below reproduce what xtdata returned on the same machine the same
morning: index labels twelve hours behind Beijing (15:00 on 09-24 came back as
'20260924030000'), and a 'time' field in epoch milliseconds.

    python test_vwap_timezone.py
"""
import calendar
import datetime as dt
import os
import sys
import types
import io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
src = io.open(os.path.join(ROOT, "vwap_schedule.py"), encoding="ascii").read()
E = types.ModuleType("vwap_schedule")
exec(compile(src, "vwap_schedule.py", "exec"), E.__dict__)

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-60s %-18s %s" % (name, repr(got)[:18], "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


class Series(object):
    def __init__(self, index, values):
        self.index, self.values = index, values

    def items(self):
        return list(zip(self.index, self.values))

    def __iter__(self):
        return iter(self.values)


class Frame(object):
    """Just enough of a DataFrame: len, .index, ['volume'], ['time']."""
    def __init__(self, index, cols):
        self.index, self.cols = index, cols

    def __len__(self):
        return len(self.index)

    def __getitem__(self, k):
        return Series(self.index, self.cols[k])


def beijing_minutes(day):
    out = []
    for h, m0, m1 in ((9, 31, 60), (10, 0, 60), (11, 0, 31), (13, 1, 60), (14, 0, 60), (15, 0, 1)):
        for m in range(m0, m1):
            out.append(dt.datetime(day.year, day.month, day.day, h, m))
    return out


def frame(days, zone_hours, with_time=True, bad_time=False):
    idx, vol, tms = [], [], []
    for d in days:
        for i, b in enumerate(beijing_minutes(d)):
            utc = b - dt.timedelta(hours=8)
            local = utc + dt.timedelta(hours=zone_hours)       # the PC's zone
            idx.append(local.strftime("%Y%m%d%H%M%S"))
            vol.append(1000.0 + (300.0 if i < 30 else 0.0))    # a front-loaded curve
            ms = calendar.timegm(utc.timetuple()) * 1000
            tms.append(float("nan") if bad_time else float(ms))
    cols = {"volume": vol}
    if with_time:
        cols["time"] = tms
    return Frame(idx, cols)


# 25 weekdays up to 2026-09-24; 09-25 was the Mid-Autumn holiday.
days, d = [], dt.date(2026, 9, 24)
while len(days) < 25:
    if d.weekday() < 5:
        days.append(d)
    d -= dt.timedelta(days=1)
days.reverse()

print("=" * 90)
print("labels in US Eastern (UTC-4 in September), as on this PC")
print("=" * 90)
f_us = frame(days, -4)
check("reproduces the morning: 15:00 on 09-24 labelled 03:00",
      f_us.index[-1], "20260924030000")

try:
    E.build_vwap_profile(list(f_us["volume"].items()), "20260928")
    old = "profile built"
except ValueError as e:
    old = str(e)
check("reading the LABELS reproduces the probe's failure", old,
      "only 0 valid historical sessions; need 10")

p = E.build_vwap_profile(E._vw_rows(f_us), "20260928")
check("reading the epoch field: 20 sessions", len(p["dates"]), 20)
check("...ending on the last trading day, 09-24", p["dates"][-1], "20260924")
check("...no Mid-Autumn session invented", "20260925" in p["dates"], False)
fr, _ = E.vwap_progress(p, E._vw_minute("100000") - p["first"], dynamic=False)
check("...and the front-loaded curve is ahead of TWAP by 10:00",
      fr > 30.0 / 270.0 * 1.05, True)

print()
print("=" * 90)
print("labels already in Beijing time, and frames without the field")
print("=" * 90)
p2 = E.build_vwap_profile(E._vw_rows(frame(days, 8)), "20260928")
check("Beijing labels + epoch field: same 20 sessions", p2["dates"], p["dates"])
p3 = E.build_vwap_profile(E._vw_rows(frame(days, 8, with_time=False)), "20260928")
check("no 'time' field: falls back to the labels, as before", p3["dates"], p["dates"])
p4 = E.build_vwap_profile(E._vw_rows(frame(days, 8, bad_time=True)), "20260928")
check("unusable 'time' values: falls back to the labels", p4["dates"], p["dates"])

print()
print("=" * 90)
print("intraday: the dynamic query must find today's bars on this PC too")
print("=" * 90)


class Ctx(object):
    """Returns history for the profile query and today's first 40 minutes for
    the intraday one -- the client ignores start/end, as the engine assumes."""
    def __init__(self, hist, today):
        self.hist, self.today, self.calls = hist, today, []

    def get_market_data_ex(self, fields, codes, **kw):
        self.calls.append((list(fields), kw.get("start_time"), kw.get("end_time")))
        return {codes[0]: self.today if kw.get("subscribe") else self.hist}


today = dt.date(2026, 9, 28)
t_full = frame([today], -4)
cut = 40
t = Frame(t_full.index[:cut], dict((k, v[:cut]) for k, v in t_full.cols.items()))
ctx = Ctx(f_us, t)
sched = E.QmtVwapSchedule(lambda s: None, 20, 10, True)
f1 = sched.fraction(ctx, "601398.SH", "20260928", "101500", "101500", "093000", "140000")
obs = sched.observed.get(("601398.SH", "20260928", "093000", "140000"), [])
check("history and intraday both asked for the epoch field",
      all(c[0] == ["time", "volume"] for c in ctx.calls), True)
check("intraday bars are recognised as today's", len(obs) > 0, True)
check("...and none beyond the completed-minute cutoff",
      max(E._vw_stamp(s)[8:] for s, _ in obs) <= "101000", True)

print()
print("=" * 90)
if fails:
    print("FAILED %d check(s):" % len(fails))
    for f in fails:
        print("   - " + f)
else:
    print("ALL CHECKS PASSED")
print("=" * 90)
sys.exit(1 if fails else 0)
