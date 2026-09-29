# -*- coding: utf-8 -*-
"""Print the QMT terminal's own 交易消息 / 报警信息 for a given day.

Those popups never reach our strategy logs: passorder and cancel are
fire-and-forget, so a counter rejection like

    entrust[182] cancel failed, err -54
    [COUNTER][251020][order status does not allow cancellation]

only ever appears on screen. But the terminal writes every one of them to
    <install>\\userdata\\log\\XtClient_Message_<date>.log
so nothing needs to be added to the strategies -- the record already exists and
just has to be read.

Two traps in that file:
  * it is GBK, not UTF-8
  * its name carries the PC's LOCAL date, and this machine runs US Eastern,
    so a Beijing trading day lands in the file named for the previous day

    python read_qmt_messages.py            # today's Beijing session
    python read_qmt_messages.py 20260824   # a specific Beijing date
    python read_qmt_messages.py 20260824 1000310    # only that account
"""
import datetime as dt
import glob
import io
import os
import re
import sys

LOG_DIR = (u"C:\\\u8fc5\u6295\u6781\u901f\u7b56\u7565\u4ea4\u6613\u7cfb\u7edf"
           u"\u4ea4\u6613\u7ec8\u7aef \u534e\u6cf0\u8bc1\u5238QMT\u6a21\u62df"
           u"\\userdata\\log")

# lines worth surfacing: anything that reports a failure or a counter message
INTERESTING = re.compile(
    u"COUNTER|\u5931\u8d25|\u5f02\u5e38|\u9519\u8bef|\u5e9f\u5355|\u62d2\u7edd"
    u"|\u8fc7\u671f|err|ERROR|reject")


def emit(text):
    """Print without dying on a byte the console cannot represent.

    The message log is GBK and occasionally carries a corrupt byte, which
    decodes to U+FFFD; writing that straight to a GBK console raises
    UnicodeEncodeError and kills the whole read. The messages are the point --
    losing all of them because one byte is bad is the wrong trade.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")


def beijing_today():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")


def candidate_files(day):
    """The Beijing day may sit in the file named for it OR the local-date one."""
    d = dt.datetime.strptime(day, "%Y%m%d")
    names = [day, (d - dt.timedelta(days=1)).strftime("%Y%m%d")]
    out = []
    for n in names:
        p = os.path.join(LOG_DIR, "XtClient_Message_%s.log" % n)
        if os.path.exists(p):
            out.append(p)
    return out or sorted(glob.glob(os.path.join(LOG_DIR, "XtClient_Message_*.log")))[-1:]


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else beijing_today()
    acct = sys.argv[2] if len(sys.argv) > 2 else None
    files = candidate_files(day)
    if not files:
        emit("no message log found under %s" % LOG_DIR)
        return
    hits = 0
    for path in files:
        emit("=== %s ===" % os.path.basename(path))
        with io.open(path, "r", encoding="gbk", errors="replace") as f:
            for line in f:
                if acct and acct not in line:
                    continue
                if not INTERESTING.search(line):
                    continue
                # keep the timestamp and the message body, drop the thread ids
                m = re.match(r"^(\S+ \S+).*?msg: (.*)$", line.strip())
                emit(u"  %s  %s" % (m.group(1), m.group(2)) if m
                     else u"  " + line.strip())
                hits += 1
    emit("---- %d message(s)" % hits)


if __name__ == "__main__":
    main()
