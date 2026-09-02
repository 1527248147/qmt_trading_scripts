#coding:utf-8
"""One record per file, on a client that cannot reopen an existing file.

The 507085 QMT client takes the open() that CREATES a file and refuses every
open() of one that already exists. That is not a quirk to work around once --
it is the ground rule, and any code that reopens a path per record silently
loses the record. It has now cost two files:

    2026-09-01  the fill record came out empty: opened per fill, so only the
                very first open (the creating one) ever succeeded
    2026-09-02  the execution-quality CSV scattered over SIX files in three
                directories. _exec_write blanked S.execfh_day unconditionally,
                so the next call saw "" != today, closed the handle and
                reopened -- and each reopen had to invent a new name or
                directory. _open_varying offers ten name/dir combinations;
                after those S.execfh goes False and exec logging is dead for
                the day. The same morning, _probe_fileio's own success pushed
                the trade log into the legacy directory: it created the file,
                wrote the header and CLOSED it, so the first real order could
                no longer open the path the probe had just created.

The rule these tests hold to: a file this strategy writes all day is opened
EXACTLY ONCE, and every row lands in that one file.

    python test_file_io.py
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import combo_buy_dual_model as M

M.ALLOWED_ACCOUNTS = ()

fails = []


def check(name, got, want):
    ok = got == want
    print("  %-58s %-14s %s" % (name, repr(got), "ok" if ok else "FAIL want " + repr(want)))
    if not ok:
        fails.append(name)


# --------------------------------------------------------------------------
# The environment. open() succeeds only when it CREATES the file; a path that
# already exists is refused, exactly as the client behaves. Real files are
# still produced, in a sandbox, so the assertions can read them back.
# --------------------------------------------------------------------------
SANDBOX = os.path.join(os.environ.get("TEMP", ROOT), "buy_fileio_sandbox")
opened = []                 # every path open() was ASKED for
created = []                # every path it actually granted


def fake_open(path, mode="r", *a, **kw):
    opened.append(path)
    exists = os.path.exists(path)
    if exists:
        # QMT's own wording, so a grep of a live log finds this test.
        raise IOError("Foribdden FileIO: " + str(path))
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    created.append(path)
    return _real_open(path, mode, *a, **kw)


_real_open = open


def _close_all():
    """Drop every day-long handle. Windows refuses to unlink a file that is
    still held, and holding them all day is exactly what is under test here."""
    for attr in ("execfh", "tradefh", "fillfh", "runlog"):
        h = getattr(M.S, attr, None)
        if h not in (None, False):
            try:
                h.close()
            except Exception:
                pass
        setattr(M.S, attr, None)


def reset(dirs):
    del opened[:]
    del created[:]
    _close_all()
    if os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX)
    for d in dirs:
        os.makedirs(d)


# Point every candidate directory the module knows about into the sandbox, so
# nothing here can touch a real log. The fallback to C:\Users\Public\Documents
# is left alone deliberately: if a test ever reaches it, the assertion that
# every row is in ONE sandbox file fails, which is the report we want.
D_RUN = os.path.join(SANDBOX, "logs")
D_LEG = os.path.join(SANDBOX, "legacy")
D_LGL = os.path.join(SANDBOX, "legacy_logs")
M.RUN_LOG_DIR = D_RUN
M.TRADE_LOG_DIR = D_RUN
M.LEGACY_DIR = D_LEG
M.LEGACY_LOGS = D_LGL
M.open = fake_open              # module-global shadows the builtin


def sandbox_files():
    out = []
    for root, _dirs, names in os.walk(SANDBOX):
        for n in names:
            out.append(os.path.join(root, n))
    return sorted(out)


def rows(path):
    f = _real_open(path, "r")
    try:
        return [l for l in f.read().split("\n") if l.strip()]
    finally:
        f.close()


# --------------------------------------------------------------------------
print("\n(a) the execution CSV: many rows, ONE file")
# This is the 2026-09-02 failure. Twelve rows is past the ten name/dir
# combinations _open_varying can offer, so a per-row reopen cannot merely
# scatter -- it runs out and starts dropping rows.
reset([D_RUN, D_LEG, D_LGL])
M.S.execfh = None
M.S.execfh_day = ""
M.S.runlog_dir = D_RUN
for i in range(12):
    M._exec_write("20260902,1003%02d,1005%02d,60000%d.SH,buy,100,100,1.00,"
                  "1.00,1.01,1.005,1.00,,,10,56,QUEUE" % (i, i, i))

execs = [p for p in sandbox_files() if os.path.basename(p).startswith("exec_")]
print("    exec files: %d   opens asked for: %d" % (len(execs), len(opened)))
for p in execs:
    print("      %-46s %d row(s)" % (os.path.basename(p), len(rows(p)) - 1))
check("exec rows all land in ONE file", len(execs), 1)
if execs:
    check("...and none of the 12 is missing", len(rows(execs[0])) - 1, 12)
check("...the file was opened exactly once", len(created), 1)


# --------------------------------------------------------------------------
print("\n(b) the probe hands its handle over instead of closing it")
# _probe_fileio created the trade CSV and closed it, so _log_trade could not
# reopen the path the probe had just made, and fell through to the legacy
# directory -- while reporting "preferred dir refused", which read like the
# environment's fault rather than ours.
reset([D_RUN, D_LEG, D_LGL])
M.S.tradefh = None
M.S.tradefh_path = ""
M.S.tradefh_retry = None
M.S.fileio = None
M.S.acct = "507085"

ok = M._probe_fileio("20260902")
check("the probe reports file IO usable", ok, True)
check("...and did NOT close the handle", M.S.tradefh is not None, True)

for i in range(5):
    M._log_trade("20260902", "1005%02d" % i, "buy", "60000%d.SH" % i, 100,
                 "remark_%d" % i)
trades = [p for p in sandbox_files() if os.path.basename(p).startswith("trades_")]
print("    trade files: %d" % len(trades))
for p in trades:
    print("      %-46s %d row(s)" % (os.path.basename(p), len(rows(p)) - 1))
check("trade rows all land in ONE file", len(trades), 1)
if trades:
    check("...in the PREFERRED directory, not the legacy one",
          os.path.dirname(trades[0]), D_RUN)
    check("...with the header plus all 5 orders", len(rows(trades[0])), 6)


# --------------------------------------------------------------------------
print("\n(c) a genuinely unwritable preferred directory still falls back")
# The fallback must survive the fix: it is what kept 2026-09-02's orders on
# disk at all. Here the preferred path is pre-created so it can never be
# opened, standing in for a directory that really is refused.
reset([D_RUN, D_LEG, D_LGL])
M.S.tradefh = None
M.S.tradefh_path = ""
M.S.tradefh_retry = None
M.S.fileio = None
blocked = os.path.join(D_RUN, "trades_" + M.STRATEGY + "_507085_20260902.csv")
f = _real_open(blocked, "w")
f.write("bar_time,side,code,shares,price_or_remark\n")
f.close()

M._log_trade("20260902", "100500", "buy", "600000.SH", 100, "remark")
check("fell back rather than losing the row", M.S.tradefh is not None, True)
check("...to the legacy directory", os.path.dirname(M.S.tradefh_path or ""), D_LEG)


# --------------------------------------------------------------------------
print("\n(d) the reason for a refusal is reported, not swallowed")
# "preferred dir refused" with no reason is what made 2026-09-02 a guess for
# an hour. The except clause kept the first exception; the message must carry
# it. Nothing asserts the wording -- only that the exception text survives.
_said = []
_print = M.print if hasattr(M, "print") else None
import io as _io
_buf = _io.StringIO()
_stdout = sys.stdout
sys.stdout = _buf
try:
    reset([D_RUN, D_LEG, D_LGL])
    M.S.tradefh = None
    M.S.tradefh_path = ""
    M.S.tradefh_retry = None
    f = _real_open(blocked, "w")
    f.write("h\n")
    f.close()
    M._log_trade("20260902", "100500", "buy", "600000.SH", 100, "remark")
finally:
    sys.stdout = _stdout
_out = _buf.getvalue()
print("    " + (_out.strip().split("\n")[-1] if _out.strip() else "(nothing printed)"))
check("the refusal names the exception", "Foribdden FileIO" in _out, True)


# --------------------------------------------------------------------------
M.open = _real_open
_close_all()                    # the handles are held all day by design
if os.path.isdir(SANDBOX):
    shutil.rmtree(SANDBOX)

print("")
if fails:
    print("FAILED %d check(s):" % len(fails))
    for n in fails:
        print("   - " + n)
    sys.exit(1)
print("ALL CHECKS PASSED")
