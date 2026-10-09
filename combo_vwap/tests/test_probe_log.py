#coding:utf-8
"""The data probe writes a copy of its output to ONE file in ONE directory.

Runs the probe's init/handlebar against a fake client, with PROBE_LOG_DIR
pointed at a temporary directory, and checks what lands there.

    python test_probe_log.py
"""
import io
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
fails = []


def check(name, got, want):
    ok = got == want
    print("  %-58s %-18s %s" % (name, repr(got)[:18], "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


def load_probe():
    src = io.open(os.path.join(ROOT, "probes", "vwap_data_probe.py"), encoding="ascii").read()
    m = types.ModuleType("probe")
    exec(compile(src, "vwap_data_probe.py", "exec"), m.__dict__)
    return m


class FakeC(object):
    def get_market_data_ex(self, fields, codes, **kw):
        return {c: None for c in codes}          # no history: every name blocks


check("the configured directory is combo_vwap\\logs and nothing else",
      load_probe().PROBE_LOG_DIR,
      "C:\\AI_STOCK\\qmt_trading_scripts\\combo_vwap\\logs")

tmp = tempfile.mkdtemp()
try:
    for run in (1, 2):
        m = load_probe()
        m.PROBE_LOG_DIR = tmp
        # silence the screen copy; the file is what is under test
        m._screen_print = lambda *a, **k: None
        c = FakeC()
        m.init(c)
        m.handlebar(c)
        m.handlebar(c)                        # later bars print nothing more
        if m._probe_fh[0] is not None:
            m._probe_fh[0].close()
        if run == 1:
            import time
            time.sleep(1.1)                   # distinct second -> distinct name
    names = sorted(os.listdir(tmp))
    check("each run leaves its own new file", len(names), 2)
    check("...named probe_vwap_data_<date>_<time>.txt",
          all(n.startswith("probe_vwap_data_") and n.endswith(".txt") for n in names), True)
    text = io.open(os.path.join(tmp, names[-1]), encoding="ascii").read()
    check("the file holds the PROBE RESULT line", "PROBE RESULT: 0 ready / 62 total" in text, True)
    check("...and the RAW diagnostic", "RAW " in text, True)
    check("...once, though handlebar ran twice", text.count("PROBE RESULT"), 1)

    # An unwritable directory: say so, write nowhere else, still run.
    m = load_probe()
    m.PROBE_LOG_DIR = os.path.join(tmp, "does", "not", "exist")
    said = []
    m._screen_print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
    m.init(FakeC())
    m.handlebar(FakeC())
    check("an unwritable directory is reported on screen",
          any("NOT written" in s for s in said), True)
    check("...and the probe still reports its result",
          any("PROBE RESULT" in s for s in said), True)
    check("...and no file appears anywhere in the temp tree but the two runs",
          sum(len(f) for _, _, f in os.walk(tmp)), 2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ---- the download step --------------------------------------------------
import calendar
import datetime as dt


class Col(object):
    def __init__(self, idx, vals):
        self.idx, self.vals = idx, vals

    def items(self):
        return list(zip(self.idx, self.vals))

    def __iter__(self):
        return iter(self.vals)


class Fr(object):
    def __init__(self, ms, vol):
        self.index = [str(x) for x in ms]
        self.cols = {"time": ms, "volume": vol}

    def __len__(self):
        return len(self.index)

    def __getitem__(self, k):
        return Col(self.index, self.cols[k])


def good_frame():
    ms, vol = [], []
    d = dt.date(2026, 8, 20)
    while d <= dt.date(2026, 9, 24):
        if d.weekday() < 5:
            for h, a, b in ((9, 31, 60), (10, 0, 60), (11, 0, 31), (13, 1, 60), (14, 0, 60)):
                for mnt in range(a, b):
                    utc = dt.datetime(d.year, d.month, d.day, h, mnt) - dt.timedelta(hours=8)
                    ms.append(calendar.timegm(utc.timetuple()) * 1000)
                    vol.append(1000.0)
        d += dt.timedelta(days=1)
    return Fr(ms, vol)


GOOD = good_frame()


class DlC(object):
    """Empty until a name has been downloaded, then full history."""
    def __init__(self):
        self.have = set()

    def get_market_data_ex(self, fields, codes, **kw):
        return dict((c, GOOD if c in self.have else None) for c in codes)


m = load_probe()
m._probe_fh[0] = None
m._open_probe_log = lambda: None
said = []
m._screen_print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
c = DlC()
calls = []


def fake_dl(code, period, start, end):
    calls.append((code, period))
    if code != "688533.SH":               # one name the server has nothing for
        c.have.add(code)


m.download_history_data = fake_dl
m.PROBE_DAY = "20260928"
m.init(c)
m.handlebar(c)
check("download asked for every blocked name, 1m only",
      (len(calls), set(p for _, p in calls)), (62, {"1m"}))
check("the first pass reports 0 ready",
      any("PROBE RESULT: 0 ready / 62" in x for x in said), True)
check("after the download the rest are ready",
      any("AFTER DOWNLOAD: 61 ready / 62 total; blocked=688533.SH" in x for x in said), True)

m = load_probe()
m._open_probe_log = lambda: None
said = []
m._screen_print = lambda *a, **k: said.append(" ".join(str(x) for x in a))
m.PROBE_DAY = "20260928"
m.init(FakeC())
m.handlebar(FakeC())
check("no download function in the client: says so, does not crash",
      any("DOWNLOAD skipped" in x for x in said), True)

print()
print("ALL CHECKS PASSED" if not fails else "FAILED %d check(s): %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
