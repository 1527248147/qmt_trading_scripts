"""Causal, nonuniform VWAP and QMT data-adapter regressions; no broker access."""
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vwap_schedule as V

DAY = '20260924'
CODE = '600000.SH'


def rows_for(day, volumes):
    return [(day + V._vw_clock(i + 1), v) for i, v in enumerate(volumes)]


def history(curve=None, n=20):
    curve = curve if curve is not None else [100.0] * 180
    # Actual exchange calendar is not an input to this unit fixture.
    day = dt.datetime.strptime(DAY, '%Y%m%d')
    return [row for d in range(n, 0, -1)
            for row in rows_for((day - dt.timedelta(days=d)).strftime('%Y%m%d'), curve)]


class Series:
    def __init__(self, rows):
        self.rows = rows

    def items(self):
        return iter(self.rows)


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, field):
        assert field == 'volume'
        return Series(self.rows)


class Context:
    def __init__(self, hist=None, today=None):
        self.hist = history() if hist is None else hist
        self.today = rows_for(DAY, [100.] * 180) if today is None else today
        self.calls = []
        self.fail_current = False

    def get_market_data_ex(self, fields, codes, **kwargs):
        self.calls.append(kwargs)
        old = kwargs['end_time'][:8] < DAY
        if not old and self.fail_current:
            raise RuntimeError('feed unavailable')
        # Deliberately ignores end_time, to exercise adapter-side lookahead guard.
        return {code: Frame(self.hist if old else self.today) for code in codes}


class ScheduleTests(unittest.TestCase):
    def test_volume_shape_not_elapsed_time(self):
        p = V.build_vwap_profile(history([400.] * 60 + [100.] * 120), DAY)
        f, _ = V.vwap_progress(p, 60, dynamic=False)
        self.assertAlmostEqual(f, 2. / 3)
        self.assertNotAlmostEqual(f, 60. / 180)

    def test_today_future_history_is_excluded(self):
        rows = history() + rows_for(DAY, [1e12] * 180)
        rows += rows_for('20260925', [1e15] * 180)
        self.assertEqual(V.build_vwap_profile(rows, DAY),
                         V.build_vwap_profile(history(), DAY))

    def test_equal_day_weights_not_event_volume_weights(self):
        rows = history(n=19)
        rows += rows_for('20260904', [1e10] * 60 + [0.] * 120)
        p = V.build_vwap_profile(rows, DAY)
        self.assertAlmostEqual(p['cumulative'][60] / p['total'], (19. / 3 + 1) / 20)

    def test_sparse_zero_duplicate_negative_nan_rejected(self):
        bad_curves = ([0.] * 180, [float('nan')] + [100.] * 179,
                      [-1.] + [100.] * 179, [100.] * 80)
        for curve in bad_curves:
            with self.assertRaises(ValueError):
                V.build_vwap_profile(history(curve), DAY)
        with self.assertRaises(ValueError):
            rows = history()
            V.build_vwap_profile(rows + rows, DAY)

    def test_small_gaps_allowed_only_in_historical_profile(self):
        rows = [(s, v) for s, v in history() if s[8:] != '100000']
        p = V.build_vwap_profile(rows, DAY)
        f, mode = V.vwap_progress(p, 60, rows_for(DAY, [100.] * 59))
        self.assertTrue(0 < f < 1)
        self.assertEqual(mode, 'DYNAMIC')
        incomplete = [(s, v) for s, v in rows_for(DAY, [100.] * 180)
                      if s[8:] != '093100']
        _, mode = V.vwap_progress(p, 60, incomplete)
        self.assertEqual(mode, 'STATIC_NO_INTRADAY')

    def test_too_few_and_stale_history_block(self):
        with self.assertRaises(ValueError):
            V.build_vwap_profile(history(n=9), DAY)
        with self.assertRaises(ValueError):
            V.build_vwap_profile(history(), '20261101')

    def test_auction_and_lunch_do_not_pollute_curve(self):
        rows = history()
        for day in sorted(set(s[:8] for s, _ in rows)):
            rows.extend([(day + '093000', 1e15), (day + '120000', 1e15),
                         (day + '150000', 1e15)])
        self.assertEqual(V.build_vwap_profile(rows, DAY),
                         V.build_vwap_profile(history(), DAY))
        self.assertEqual(V._vw_minute('123000'), 120)
        self.assertEqual(V._vw_clock(121), '130100')

    def test_later_and_offset_window(self):
        p = V.build_vwap_profile(history([100.] * 225), DAY, end='144500')
        self.assertAlmostEqual(V.vwap_progress(p, 180, dynamic=False)[0], 0.8)
        p = V.build_vwap_profile(history(), DAY, start='100000')
        self.assertEqual(p['first'], 30)
        self.assertEqual(len(p['expected']), 150)

    def test_dynamic_reacts_to_observed_volume(self):
        p = V.build_vwap_profile(history(), DAY)
        slow = rows_for(DAY, [20.] * 180)
        fast = rows_for(DAY, [500.] * 180)
        s = V.vwap_progress(p, 60, slow)[0]
        f = V.vwap_progress(p, 60, fast)[0]
        self.assertLess(s, 1. / 3)
        self.assertGreater(f, 1. / 3)
        self.assertLessEqual(f, 1. / 3 + .15)

    def test_dynamic_no_lookahead(self):
        p = V.build_vwap_profile(history(), DAY)
        prefix = rows_for(DAY, [150.] * 55)
        full = prefix + rows_for(DAY, [0.] * 55 + [1e12] * 125)[55:]
        self.assertEqual(V.vwap_progress(p, 60, prefix), V.vwap_progress(p, 60, full))

    def test_monotonic_and_complete_with_changing_volume(self):
        p = V.build_vwap_profile(history(), DAY)
        rows = rows_for(DAY, [1000.] * 30 + [0.] * 90 + [100.] * 60)
        values = [V.vwap_progress(p, i, rows)[0] for i in range(181)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0.)
        self.assertEqual(values[-1], 1.)

    def test_timestamp_formats_and_timezone(self):
        stamp = dt.datetime(2026, 9, 23, 1, 31, tzinfo=dt.timezone.utc)
        ms = int(stamp.timestamp() * 1000)
        for x in ('20260923093100', 20260923093100, ms, stamp,
                  '2026-09-23 09:31:00'):
            self.assertEqual(V._vw_stamp(x), '20260923093100')
        with self.assertRaises(ValueError):
            V._vw_stamp(42)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.adapter = V.QmtVwapSchedule(self.messages.append)
        self.c = Context()

    def fraction(self, t, wall=None):
        return self.adapter.fraction(self.c, CODE, DAY, t, wall or t,
                                     '093000', '140000')

    def test_daily_cache_and_five_minute_refresh(self):
        self.fraction('100000')
        self.fraction('100000')
        self.fraction('100100')
        self.fraction('100200')
        self.assertEqual(sum(not q['subscribe'] for q in self.c.calls), 1)
        self.assertEqual(sum(q['subscribe'] for q in self.c.calls), 2)
        self.assertTrue(all(q['fill_data'] is False for q in self.c.calls))
        self.assertEqual(self.c.calls[0]['end_time'], '20260923235959')

    def test_restart_reconstructs_same_progress(self):
        self.c.today = rows_for(DAY, [1000.] * 30 + [0.] * 150)
        for m in range(1, 81):
            old = self.fraction(V._vw_clock(m))
        fresh = V.QmtVwapSchedule(lambda msg: None)
        new = fresh.fraction(self.c, CODE, DAY, '105000', '105000', '093000', '140000')
        self.assertAlmostEqual(old, new)

    def test_wall_clock_limits_forming_bar(self):
        a = self.fraction('100200', '100000')
        b = V.QmtVwapSchedule(lambda msg: None).fraction(
            self.c, CODE, DAY, '100000', '100000', '093000', '140000')
        self.assertEqual(a, b)
        # The query window is deliberately wide -- the client may read its
        # start/end in the PC's zone, twelve hours off Beijing on this machine
        # -- so the guarantee lives in the filter, and that is what is checked:
        # nothing past the last COMPLETED minute reaches the schedule.
        intraday = [q for q in self.c.calls if q['subscribe']]
        self.assertTrue(intraday)
        self.assertLessEqual(intraday[0]['start_time'], DAY + '093000')
        self.assertGreaterEqual(intraday[0]['end_time'], DAY + '095500')
        seen = self.adapter.observed[(CODE, DAY, '093000', '140000')]
        self.assertTrue(seen)
        self.assertLessEqual(max(V._vw_stamp(s) for s, _ in seen), DAY + '095500')

    def test_missing_history_blocks_even_at_auction(self):
        self.c.hist = []
        self.assertIsNone(self.fraction('100000'))
        self.assertIsNone(self.fraction('145800'))
        self.assertTrue(any('VWAP BLOCK' in m for m in self.messages))

    def test_history_retry_after_download(self):
        self.c.hist = []
        self.assertIsNone(self.fraction('100000'))
        self.c.hist = history()
        self.assertIsNone(self.fraction('100100'))
        self.assertIsNotNone(self.fraction('100500'))

    def test_missing_current_volume_uses_static_not_twap(self):
        self.c.hist = history([400.] * 60 + [100.] * 120)
        self.c.fail_current = True
        f = self.fraction('103000')
        self.assertAlmostEqual(f, 2. / 3)
        self.assertTrue(any('STATIC_NO_INTRADAY' in m for m in self.messages))


if __name__ == '__main__':
    unittest.main(verbosity=2)
