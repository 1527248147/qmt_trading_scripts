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
