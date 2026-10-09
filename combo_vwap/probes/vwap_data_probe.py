#coding:gbk
# Paste into a QMT 1m MODEL to check data only. No account binding is required.
# No orders, cancels, native algo calls or subscriptions. It may DOWNLOAD 1m
# market data for names that lack it (PROBE_DOWNLOAD_MISSING). It writes exactly
# one file: a copy of its own output, in combo_vwap\logs (see PROBE_LOG_DIR).
# Update this basket and date when the execution plan changes.
PROBE_DAY = ''  # blank = Beijing calendar date; YYYYMMDD for the intended day
PROBE_CODES = ['000063.SZ', '000548.SZ', '000590.SZ', '000702.SZ', '000952.SZ', '000972.SZ', '002016.SZ', '002344.SZ', '002381.SZ', '002732.SZ', '003008.SZ', '300363.SZ', '300500.SZ', '300625.SZ', '300644.SZ', '300673.SZ', '300691.SZ', '300732.SZ', '300800.SZ', '300949.SZ', '301009.SZ', '301102.SZ', '301167.SZ', '301170.SZ', '301298.SZ', '301429.SZ', '301515.SZ', '301519.SZ', '600050.SH', '600051.SH', '600097.SH', '600283.SH', '600463.SH', '600620.SH', '600628.SH', '600816.SH', '600968.SH', '600981.SH', '601318.SH', '601398.SH', '603096.SH', '603214.SH', '603291.SH', '603810.SH', '603826.SH', '603860.SH', '603908.SH', '603982.SH', '605088.SH', '688217.SH', '688236.SH', '688267.SH', '688273.SH', '688357.SH', '688377.SH', '688393.SH', '688466.SH', '688468.SH', '688533.SH', '688659.SH', '688737.SH', '688800.SH']
PROBE_START, PROBE_END = '093000', '140000'
PROBE_LOOKBACK, PROBE_MIN_DAYS = 20, 10
# Fetch 1m history for every name that fails, from inside this client, then
# check those names again. MARKET DATA ONLY -- no account, no orders.
#
# Why inside the model: the simulation install keeps TWO data stores.
# miniQMT reads userdata_mini\datadir, the model client reads datadir. On
# 2026-09-28 history downloaded through miniQMT went into the first, and this
# probe -- reading the second -- still found 47 of 62 names empty. Calling the
# client's own download_history_data writes where the trading models read.
PROBE_DOWNLOAD_MISSING = True
PROBE_DOWNLOAD_DAYS = 100           # calendar days of history to request

# BEGIN EMBEDDED VWAP SCHEDULE
# Pure Python 3.6+; embedded verbatim in each standalone QMT model.
# Research-inspired volume scheduling, not a reproduction of an optimal-control
# paper or of the broker's proprietary VWAP. No broker/order APIs in this file.
import datetime as _vd
import math as _vm
import statistics as _vs


def _vw_minute(hhmmss):
    h, m = int(hhmmss[:2]), int(hhmmss[2:4])
    clock = h * 60 + m
    if clock <= 690:
        return max(0, min(120, clock - 570))
    return max(120, min(240, 120 + clock - 780))


def _vw_clock(minute):
    clock = 570 + minute if minute <= 120 else 780 + minute - 120
    return '%02d%02d00' % (clock // 60, clock % 60)


def _vw_stamp(value):
    """QMT frame index: YYYYMMDDhhmmss, Timestamp, or Unix milliseconds."""
    s = str(value)
    if len(s) == 14 and s.isdigit():
        _vd.datetime.strptime(s, '%Y%m%d%H%M%S')
        return s
    if hasattr(value, 'strftime'):
        # A timezone-aware index is converted to Beijing; naive QMT indexes
        # already represent exchange local time.
        if getattr(value, 'tzinfo', None) is not None:
            value = value.astimezone(_vd.timezone(_vd.timedelta(hours=8)))
        return value.strftime('%Y%m%d%H%M%S')
    if s.isdigit() and len(s) in (10, 13):
        n = int(s) / (1000.0 if len(s) == 13 else 1.0)
        return (_vd.datetime.utcfromtimestamp(n) +
                _vd.timedelta(hours=8)).strftime('%Y%m%d%H%M%S')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return _vd.datetime.strptime(s[:19], fmt).strftime('%Y%m%d%H%M%S')
        except ValueError:
            pass
    raise ValueError('unsupported minute timestamp: %r' % (value,))


def _vw_rows(frame):
    if frame is None or len(frame) == 0:
        return []
    # iterating a single Series avoids copying whole OHLCV frames.
    vols = list(frame['volume'].items())
    # PREFER THE EPOCH 'time' FIELD TO THE INDEX LABELS.
    #
    # QMT renders the index in the time zone of the PC it runs on, and this PC
    # runs US Eastern. On 2026-09-28 every label read twelve hours behind
    # Beijing -- 09:30 came out as 21:30 the evening before -- so the
    # 09:31-14:54 filter below matched nothing and all 62 names reported "only
    # 0 valid historical sessions". A millisecond epoch has no zone to get
    # wrong; _vw_stamp converts it to Beijing explicitly.
    #
    # Falls back to the labels when the field is absent or unusable, which is
    # what every offline frame and any QMT build without 'time' provides.
    try:
        times = list(frame['time'])
    except Exception:
        return vols
    if len(times) != len(vols):
        return vols
    out = []
    for t, (_, v) in zip(times, vols):
        try:
            t = int(t)
        except (TypeError, ValueError, OverflowError):
            return vols
        # Must look like an epoch, in ms or s. Anything else is not a time
        # this code understands, and the labels are the better guess.
        if not (10 ** 12 <= t < 10 ** 13 or 10 ** 9 <= t < 10 ** 10):
            return vols
        out.append((t, v))
    return out


def _vw_days(rows, first, last):
    """Use close-labelled continuous-session bars only; never forward fill."""
    days, bad = {}, set()
    for stamp, volume in rows:
        stamp = _vw_stamp(stamp)
        day, clock = stamp[:8], stamp[8:]
        # Exclude opening auction and lunch. 15:00 includes closing auction;
        # this scheduler only supports continuous windows ending <=14:54.
        if not ('093100' <= clock <= '113000' or
                '130100' <= clock <= '145400'):
            continue
        minute = _vw_minute(clock)
        if not first < minute <= last:
            continue
        vals = days.setdefault(day, {})
        v = float(volume)
        if clock[-2:] != '00' or not _vm.isfinite(v) or v < 0 or minute in vals:
            bad.add(day)
        vals[minute] = v
    return days, bad


def build_vwap_profile(rows, trade_day, start='093000', end='140000',
                       lookback=20, min_days=10, coverage=0.95, max_age=14):
    first, last = _vw_minute(start), _vw_minute(end)
    if not ('093000' <= start < end <= '145400') or last <= first:
        raise ValueError('VWAP window must be within 09:30-14:54')
    if not (0 < min_days <= lookback and 0 < coverage <= 1):
        raise ValueError('invalid historical profile parameters')
    days, bad = _vw_days(rows, first, last)
    accepted = []
    width = last - first
    for day in sorted(days):
        if day >= trade_day or day in bad:
            continue
        vals = days[day]
        # Explicitly sparse/incomplete days are not zero-volume sessions.
        if len(vals) < _vm.ceil(width * coverage):
            continue
        if min(vals) > first + 5 or max(vals) < last:
            continue
        curve = [vals.get(i, 0.0) for i in range(first + 1, last + 1)]
        total = sum(curve)
        if total > 0:
            accepted.append((day, curve, total))
    accepted = accepted[-lookback:]
    if len(accepted) < min_days:
        raise ValueError('only %d valid historical sessions; need %d' %
                         (len(accepted), min_days))
    age = (_vd.datetime.strptime(trade_day, '%Y%m%d') -
           _vd.datetime.strptime(accepted[-1][0], '%Y%m%d')).days
    if age > max_age:
        raise ValueError('historical profile stale: %d calendar days' % age)
    # Equal weight per DAY after normalisation: one event/huge-volume day
    # cannot dominate the shape. Median total supplies the volume scale.
    scale = _vs.median([x[2] for x in accepted])
    expected = [sum(x[1][i] / x[2] for x in accepted) * scale / len(accepted)
                for i in range(width)]
    cumulative = [0.0]
    for v in expected:
        cumulative.append(cumulative[-1] + v)
    return {'day': trade_day, 'start': start, 'end': end, 'first': first,
            'last': last, 'dates': [x[0] for x in accepted],
            'expected': expected, 'cumulative': cumulative,
            'total': cumulative[-1]}


def vwap_progress(profile, elapsed, today_rows=(), dynamic=True,
                  refresh=5, prior_minutes=60.0, max_deviation=0.15):
    """Causal cumulative target, reconstructed from the full observed prefix.

    A=observed volume, H=historical expected volume, R=expected remainder.
    scale=(A + prior)/(H + prior), clipped to [0.25, 4].
    F=(A + scale*expected_since_observation)/(A + scale*R).
    Replaying all previous minute targets makes F monotone and restart-safe
    without saving a separate mutable schedule. No future volume is used.
    """
    width = profile['last'] - profile['first']
    elapsed = max(0, min(width, int(elapsed)))
    cum, total = profile['cumulative'], profile['total']
    if elapsed == width:
        return 1.0, 'COMPLETE'
    if elapsed == 0:
        return 0.0, 'STATIC'
    static = cum[elapsed] / total
    if not dynamic:
        return static, 'STATIC'
    if refresh < 1 or prior_minutes <= 0 or not 0 <= max_deviation <= 1:
        raise ValueError('invalid dynamic parameters')
    days, bad = _vw_days(today_rows, profile['first'], profile['last'])
    vals = days.get(profile['day'], {})
    if profile['day'] in bad:
        return static, 'STATIC_BAD_INTRADAY'
    actual, complete = [0.0], [True]
    for m in range(profile['first'] + 1, profile['last'] + 1):
        actual.append(actual[-1] + vals.get(m, 0.0))
        complete.append(complete[-1] and m in vals)
    prior = total * prior_minutes / width
    highwater, mode = 0.0, 'STATIC_NO_INTRADAY'
    # At minute t, only bars ending <=t-1 can feed the dynamic estimate.
    # A deterministic 5-min grid makes reload/restart use the same prefixes.
    for t in range(1, elapsed + 1):
        baseline = cum[t] / total
        observed = ((t - 1) // refresh) * refresh
        f = baseline
        if observed >= refresh and complete[observed]:
            a, h = actual[observed], cum[observed]
            scale = max(0.25, min(4.0, (a + prior) / (h + prior)))
            denom = a + scale * (total - h)
            if denom > 0:
                f = (a + scale * (cum[t] - h)) / denom
                f = max(baseline - max_deviation,
                        min(baseline + max_deviation, f))
                mode = 'DYNAMIC'
        elif t == elapsed:
            mode = 'STATIC_NO_INTRADAY'
        highwater = max(highwater, f)
    return max(0.0, min(1.0, highwater)), mode


class QmtVwapSchedule(object):
    """Read-only ContextInfo adapter. Cache history daily; refresh today's
    completed prefix once per five session minutes. Missing history BLOCKS
    that name, including the completion/auction branch. No silent TWAP.
    """
    def __init__(self, emit, lookback=20, min_days=10, dynamic=True,
                 downloader=None, download_days=100):
        self.emit = emit
        self.lookback, self.min_days, self.dynamic = lookback, min_days, dynamic
        self.profiles, self.history_try = {}, {}
        self.observed, self.current_try = {}, {}
        self.status, self.highwater = {}, {}
        # Optional: a callable(code, period, start_yyyymmdd, end_yyyymmdd) that
        # fetches history into the store get_market_data_ex reads -- in QMT,
        # the client's own download_history_data. Passed in rather than looked
        # up, so this file still touches no broker API of its own.
        self.downloader, self.download_days = downloader, download_days
        self.downloaded = set()

    def _load_profile(self, context, code, day, start, end):
        d = _vd.datetime.strptime(day, '%Y%m%d')
        result = context.get_market_data_ex(
            ['time', 'volume'], [code], period='1m',
            start_time=(d - _vd.timedelta(days=90)).strftime('%Y%m%d') + '000000',
            end_time=(d - _vd.timedelta(days=1)).strftime('%Y%m%d') + '235959',
            count=-1, dividend_type='none', fill_data=False, subscribe=False)
        return build_vwap_profile(_vw_rows(result.get(code)), day, start, end,
                                  self.lookback, self.min_days)

    def _fetch(self, code, day, why):
        """Download 1m history for `code` ONCE per session, then report."""
        self.downloaded.add(code)
        d = _vd.datetime.strptime(day, '%Y%m%d')
        s0 = (d - _vd.timedelta(days=self.download_days)).strftime('%Y%m%d')
        e0 = (d - _vd.timedelta(days=1)).strftime('%Y%m%d')
        self.emit('VWAP DOWNLOAD %s: %s -- fetching 1m history %s..%s'
                  % (code, why, s0, e0))
        self.downloader(code, '1m', s0, e0)

    def _notice(self, key, status, msg):
        if self.status.get(key) != status:
            self.status[key] = status
            self.emit(msg)

    def fraction(self, context, code, day, bar, wall, start, end):
        key = (code, day, start, end)
        # Never let QMT's ahead-of-clock forming bar advance the VWAP target.
        clock = min(bar, wall)
        minute = _vw_minute(clock)
        slot = minute // 5
        if key not in self.profiles and self.history_try.get(key) != slot:
            self.history_try[key] = slot
            self._ensure_profile(context, code, day, start, end)
        p = self.profiles.get(key)
        return self._progress(context, code, day, start, end, key, clock,
                              minute, p)

    def prefetch(self, context, code, day, start, end):
        """Load -- and, with a downloader, fetch -- one profile NOW.

        For the start-up pass: outside the five-minute cadence fraction()
        keeps, and without computing a target. True when the name is ready.
        """
        key = (code, day, start, end)
        if key in self.profiles:
            return True
        return self._ensure_profile(context, code, day, start, end)

    def _ensure_profile(self, context, code, day, start, end):
        key = (code, day, start, end)
        try:
            try:
                p = self._load_profile(context, code, day, start, end)
            except Exception as first:
                # FETCH ONCE, THEN LOOK AGAIN.
                #
                # 2026-09-29: the live client had none of this history --
                # 0 of 62 names ready -- and it has no miniQMT to fetch it
                # with. The client's own download_history_data, called
                # from inside a model, filled all 62 in about a minute. So
                # a name that cannot build its profile gets that one call
                # and one more look, instead of a whole day blocked for
                # want of a separate paste. Once per name per session: a
                # server with nothing more to give would otherwise be
                # asked again every five minutes.
                if self.downloader is None or code in self.downloaded:
                    raise
                try:
                    self._fetch(code, day, str(first))
                except Exception as dex:
                    raise ValueError('%s; download failed: %r' % (first, dex))
                p = self._load_profile(context, code, day, start, end)
            self.profiles[key] = p
            self.emit('VWAP PROFILE %s %s: %d sessions %s..%s window %s-%s'
                      % (code, day, len(p['dates']), p['dates'][0],
                         p['dates'][-1], start, end))
        except Exception as exc:
            self._notice(key, 'BLOCK', 'VWAP BLOCK %s: %s; download 1m history'
                         % (code, str(exc)))
        return key in self.profiles

    def _progress(self, context, code, day, start, end, key, clock, minute, p):
        if p is None:
            return None
        elapsed = max(0, min(p['last'] - p['first'], minute - p['first']))
        cutoff = p['first'] + max(0, ((elapsed - 1) // 5) * 5)
        if self.dynamic and elapsed > 5 and elapsed < p['last'] - p['first']:
            if self.current_try.get(key) != cutoff:
                self.current_try[key] = cutoff
                try:
                    # A WIDE query, filtered below by Beijing time. The
                    # client may read start/end in the zone of the PC, which
                    # here is twelve hours off; asking for the Beijing day
                    # plus a day either side cannot miss, and the filter
                    # below still cuts at the completed-minute cutoff.
                    _dd = _vd.datetime.strptime(day, '%Y%m%d')
                    result = context.get_market_data_ex(
                        ['time', 'volume'], [code], period='1m',
                        start_time=(_dd - _vd.timedelta(days=1)).strftime('%Y%m%d') + '000000',
                        end_time=(_dd + _vd.timedelta(days=1)).strftime('%Y%m%d') + '235959',
                        count=-1, dividend_type='none', fill_data=False, subscribe=True)
                    rows = _vw_rows(result.get(code))
                    # Filter even if a data provider ignores end_time.
                    self.observed[key] = [(s, v) for s, v in rows
                                          if _vw_stamp(s)[:8] == day and
                                          _vw_stamp(s)[8:] <= _vw_clock(cutoff)]
                except Exception:
                    # An old prefix is safe, but cannot stand in for newer data.
                    self.observed[key] = []
        f, mode = vwap_progress(p, elapsed, self.observed.get(key, ()), self.dynamic)
        f = max(f, self.highwater.get(key, 0.0))
        self.highwater[key] = f
        self._notice(key, mode, 'VWAP %s %s target %.2f%% (%s)' %
                     (code, clock, f * 100.0, mode))
        return f
# END EMBEDDED VWAP SCHEDULE



# ---- a copy of everything printed, readable without a screenshot ----------
#
# ONE directory, ONE new file per run:
#     combo_vwap\logs\probe_vwap_data_<Beijing date>_<time>.txt
# A fresh name every run, because the live client refuses to open a file that
# already exists. No fallback directories: if this one cannot be written, the
# screen says so and nothing lands anywhere else.
PROBE_LOG_DIR = "C:\\AI_STOCK\\qmt_trading_scripts\\combo_vwap\\logs"
_probe_fh = [None]
_screen_print = print


def print(*args, **kwargs):     # noqa - module-local shadow, tees to the file
    _screen_print(*args, **kwargs)
    fh = _probe_fh[0]
    if fh is None:
        return
    try:
        fh.write(" ".join(str(a) for a in args) + chr(10))
        fh.flush()
    except Exception:
        _probe_fh[0] = None


def _open_probe_log():
    stamp = (_vd.datetime.utcnow() + _vd.timedelta(hours=8)).strftime("%Y%m%d_%H%M%S")
    path = PROBE_LOG_DIR + chr(92) + "probe_vwap_data_" + stamp + ".txt"
    try:
        _probe_fh[0] = open(path, "w")
        _screen_print("probe log ->", path)
    except Exception as e:
        _probe_fh[0] = None
        _screen_print("probe log file NOT written (%r); output is on screen only" % (e,))


def init(C):
    _open_probe_log()
    C.vwap_probe_done = False
    print('VWAP DATA PROBE: read-only; evaluates local 1m history, not fills')
    print('Native smart_algo_passorder symbol present:',
          callable(globals().get('smart_algo_passorder')),
          '(account permission NOT tested)')


def handlebar(C):
    if getattr(C, 'vwap_probe_done', False):
        return
    C.vwap_probe_done = True
    day = PROBE_DAY or (_vd.datetime.utcnow() +
                        _vd.timedelta(hours=8)).strftime('%Y%m%d')
    scheduler = QmtVwapSchedule(print, PROBE_LOOKBACK, PROBE_MIN_DAYS, False)
    # RAW SHAPE, once: what the client actually returns for one name. On
    # 2026-09-28 the first run reported 0 ready with nothing to say why; the
    # cause was index labels in the PC's zone. Whatever goes wrong next time,
    # these lines show the labels, the epoch field, and how both convert.
    try:
        _c0 = sorted(set(PROBE_CODES))[0]
        _d0 = _vd.datetime.strptime(day, '%Y%m%d')
        _r0 = C.get_market_data_ex(
            ['time', 'volume'], [_c0], period='1m',
            start_time=(_d0 - _vd.timedelta(days=10)).strftime('%Y%m%d') + '000000',
            end_time=(_d0 - _vd.timedelta(days=1)).strftime('%Y%m%d') + '235959',
            count=-1, dividend_type='none', fill_data=False, subscribe=False)
        _f0 = _r0.get(_c0)
        print('RAW %s: %d rows' % (_c0, 0 if _f0 is None else len(_f0)))
        if _f0 is not None and len(_f0):
            _ix = list(_f0.index)
            print('RAW index first %r last %r' % (_ix[0], _ix[-1]))
            try:
                _tm = list(_f0['time'])
                print('RAW time  first %r last %r' % (_tm[0], _tm[-1]))
            except Exception as _e:
                print('RAW time field unavailable: %r' % (_e,))
            _rw = _vw_rows(_f0)
            print('RAW as Beijing: first %s last %s'
                  % (_vw_stamp(_rw[0][0]), _vw_stamp(_rw[-1][0])))
    except Exception as _e:
        print('RAW probe failed: %r' % (_e,))
    good, bad = _evaluate(C, scheduler, day, sorted(set(PROBE_CODES)))
    print('PROBE RESULT: %d ready / %d total; blocked=%s' %
          (len(good), len(good) + len(bad), ','.join(bad) or 'none'))
    if bad and PROBE_DOWNLOAD_MISSING:
        _download(bad, day)
        # A NEW scheduler: the old one remembers each failure for five
        # minutes and would not look again.
        again = QmtVwapSchedule(print, PROBE_LOOKBACK, PROBE_MIN_DAYS, False)
        fixed, bad = _evaluate(C, again, day, bad)
        good += fixed
        print('AFTER DOWNLOAD: %d ready / %d total; blocked=%s' %
              (len(good), len(good) + len(bad), ','.join(bad) or 'none'))
    if bad:
        print('Use QMT data management to download 1m history for blocked names,')
        print('then restart this probe. Production models never replace this')
        print('missing history with a silent TWAP or an auction-sized order.')


def _download(codes, day):
    """download_history_data for each name, into this client's own store."""
    dl = globals().get('download_history_data')
    if not callable(dl):
        print('DOWNLOAD skipped: download_history_data is not available in this'
              ' client -- use QMT data management instead')
        return
    d = _vd.datetime.strptime(day, '%Y%m%d')
    start = (d - _vd.timedelta(days=PROBE_DOWNLOAD_DAYS)).strftime('%Y%m%d')
    end = (d - _vd.timedelta(days=1)).strftime('%Y%m%d')
    print('DOWNLOAD 1m history %s..%s for %d name(s)' % (start, end, len(codes)))
    failed = []
    for i, code in enumerate(codes, 1):
        try:
            dl(code, '1m', start, end)
        except Exception as e:
            failed.append('%s(%r)' % (code, e))
        if i % 10 == 0 or i == len(codes):
            print('DOWNLOAD %d/%d' % (i, len(codes)))
    if failed:
        print('DOWNLOAD failed for: ' + ', '.join(failed))


def _evaluate(C, scheduler, day, codes):
    good, bad = [], []
    for code in codes:
        # At the start there is no current-day query or subscription. Only
        # completed historical sessions strictly BEFORE the requested day.
        f = scheduler.fraction(C, code, day, PROBE_START, PROBE_START,
                               PROBE_START, PROBE_END)
        if f is None:
            bad.append(code)
            continue
        p = scheduler.profiles[(code, day, PROBE_START, PROBE_END)]
        good.append(code)
        samples = []
        for clock in ('100000', '103000', '110000', '113000', '133000', PROBE_END):
            elapsed = _vw_minute(clock) - p['first']
            frac, _ = vwap_progress(p, elapsed, dynamic=False)
            samples.append('%s=%.1f%%' % (clock, 100 * frac))
        print('CURVE', code, ' '.join(samples))
    return good, bad
