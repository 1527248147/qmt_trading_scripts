"""Real volume adapter + actual buy sizing and full sell lifecycle.

All broker-facing calls are fakes. No QMT library is imported.
"""
import ast
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_vwap_schedule import Context, Frame, history, rows_for, DAY
import vwap_schedule as V

with contextlib.redirect_stdout(io.StringIO()):
    import test_sell_model_offline as T

SELL = T.M
REAL_SELL_FRACTION = SELL._production_vwap_fraction


def close_fake_handles():
    for name in ('runlog', 'tradelog', 'execfh', 'fillfh'):
        handle = getattr(SELL.S, name, None)
        if handle and hasattr(handle, 'close'):
            handle.close()
        setattr(SELL.S, name, None)


close_fake_handles()


def fresh_buy():
    spec = importlib.util.spec_from_file_location('vwap_buy_fixture', ROOT / 'combo_buy_dual_model.py')
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m)
    return m


class BuyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.m = fresh_buy()
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.addCleanup(self.stack.close)
        m = self.m
        self.c = Context(hist=history([400.] * 60 + [100.] * 120))
        self.held, self.fills, self.sent = {}, {}, []
        self.clock = '103000'
        m.TARGETS = ['600000.SH']
        m.SLOTS = 1
        m.BUY_BUDGET = 100000.
        m.ALLOWED_ACCOUNTS = ()
        m.account, m.accountType = 'FAKE', 'STOCK'
        m._start_run_log = lambda: None
        m._refresh_price_mode = lambda: set()
        m._today_str = lambda: DAY
        m._wall_hhmmss = lambda: self.clock
        m.init(self.c)
        m.VWAP_DYNAMIC = False
        m._adopt_existing = lambda c: None
        m._positions = lambda c: dict(self.held)
        m._own = lambda held, code: held.get(code, 0)
        m._total_value = lambda c: 100000.
        m._open_buy_qty = lambda c: {}
        m._filled_today = lambda c: dict(self.fills)
        m._fills_from_orders = lambda: {}
        m._fills_from_disk = lambda day: {}
        m._quote = lambda *a: {'close': 10., 'volume': 100000., 'preclose': 10.}
        m._is_st = lambda *a: False
        m._sealed_up = lambda *a: (False, '')
        m._sealed_down = lambda *a: (False, 0.)
        m._spread_wide = lambda *a: (False, '')
        m._in_settle = lambda: False
        m._log_trade = lambda *a: None
        m._available_cash = lambda *a: 100000.
        m._limit_up = lambda *a: 11.

        def place(c, code, qty, remark, limit_px=None):
            self.sent.append((code, qty, remark))
            self.held[code] = self.held.get(code, 0) + qty
            self.fills[code] = self.fills.get(code, 0) + qty
        m._order_buy = place

    def test_nonuniform_volume_drives_buy_quantity_and_no_duplicate(self):
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 6600)
        self.assertTrue(all(x[2].startswith('combo_buy_vwap') for x in self.sent))
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 6600)
        # Simulate loss of in-memory schedule and sent quantity; broker fills
        # survive. The schedule rebuild must not re-buy earlier slices.
        self.m.S.vwap_scheduler = None
        self.m.S.sent_qty = {}
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 6600)
        self.clock = '140000'
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 10000)

    def test_no_history_blocks_buy_and_auction(self):
        self.c.hist = []
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(self.sent, [])
        self.clock = '145800'
        self.m._run_auction(self.c, DAY, self.clock)
        self.assertEqual(self.sent, [])

    def test_no_history_blocks_topup_path(self):
        # STAR 200 minimum / 1-share step: this would top up before the old
        # placement of the VWAP guard. It must also respect missing history.
        code = '688001.SH'
        self.m.TARGETS = [code]
        self.m.S.buy_state = {'queue_i': 0, 'active': [], 'filled': set(),
                             'rank_of': {code: 1}}
        self.m._total_value = lambda c: 3500.
        self.held[code] = 200
        self.clock, self.c.hist = '140000', []
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(self.sent, [])

    def test_participation_and_pending_still_bound_slice(self):
        self.m._quote = lambda *a: {'close': 10., 'volume': 50., 'preclose': 10.}
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 500)
        self.m._open_buy_qty = lambda c: {'600000.SH': 6100}
        self.m._run_buys(self.c, DAY, self.clock)
        self.assertEqual(sum(x[1] for x in self.sent), 500)

    def test_disabled_does_not_even_query_context(self):
        self.m.VWAP_ENABLE_TRADING = False
        self.m.handlebar(None)
        self.assertEqual(self.sent, [])


class SellIntegrationTests(unittest.TestCase):
    def run_case(self, valid=True, end='140000'):
        base_c = T.FakeC

        class VolumeC(base_c):
            def get_market_data_ex(self, fields, codes, **kwargs):
                if set(fields) <= {'time', 'volume'} and 'volume' in fields:
                    if kwargs['end_time'][:8] < DAY:
                        rows = history([400.] * 60 + [100.] * 165) if valid else []
                    else:
                        rows = rows_for(DAY, [400.] * 60 + [100.] * 165)
                    return {code: Frame(rows) for code in codes}
                return super().get_market_data_ex(fields, codes, **kwargs)

        bars = {'600000.SH': {'close': 10., 'preclose': 10., 'high': 10.1,
                             'low': 9.9, 'volume': 100000}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for obj, name, val in (
                    (T, 'FakeC', VolumeC), (T, 'BARS', bars),
                    (SELL, 'SELL_TARGETS', {'600000.SH': 10000}),
                    (SELL, 'CLOSE_DATE', DAY), (SELL, 'CLOSE_UNTIL', DAY),
                    (SELL, '_today_str', lambda: DAY), (SELL, 'SELL_END', end),
                    (SELL, 'VWAP_DYNAMIC', False),
                    (SELL, '_vwap_fraction', REAL_SELL_FRACTION),
                    (SELL, 'STALE_BAR_MAX_MIN', 100000)):
                stack.enter_context(patch.object(obj, name, val))
            book = T.Book({'600000.SH': (10000, 10000)})
            try:
                sent = T.run_session(T.all_minutes(), book)
            finally:
                close_fake_handles()
            return sent

    def test_volume_schedule_through_full_sell_lifecycle(self):
        sent = self.run_case()
        early = sum(x[2] for x in sent if x[0] <= '103200')
        self.assertGreater(early, 6000)
        self.assertEqual(sum(x[2] for x in sent), 10000)
        self.assertTrue(all(x[4] == 24 for x in sent))

    def test_missing_history_does_not_dump_in_rush_or_auction(self):
        self.assertEqual(self.run_case(valid=False), [])

    def test_extended_window_still_completes(self):
        sent = self.run_case(end='144500')
        self.assertEqual(sum(x[2] for x in sent), 10000)
        before_14 = sum(x[2] for x in sent if x[0] <= '140000')
        self.assertLess(before_14, 10000)


class IsolationTests(unittest.TestCase):
    def test_probe_and_tools_cannot_submit_or_cancel(self):
        forbidden = {'passorder', 'algo_passorder', 'smart_algo_passorder',
                     'cancel', 'cancel_task', 'order_stock', 'order_stock_async'}
        for directory in ('probes', 'tools'):
            for path in (ROOT / directory).glob('*.py'):
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
                        self.assertNotIn(name, forbidden, str(path))

    def test_names_paths_and_default_activation(self):
        for side in ('buy', 'sell'):
            text = (ROOT / ('combo_%s_dual_model.py' % side)).read_text(encoding='ascii')
            tree = ast.parse(text)
            constants = {}
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        constants[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
            self.assertEqual(constants['STRATEGY'], 'combo_%s_vwap' % side)
            # An operational switch, edited per session like OPEN_DATE and
            # ALLOWED_ACCOUNTS -- so the checked-in value is not pinned. What
            # must hold is that it is a plain bool the paste can read, and
            # that False really stops everything (see
            # test_disabled_does_not_even_query_context).
            self.assertIsInstance(constants['VWAP_ENABLE_TRADING'], bool)
            for name, value in constants.items():
                if isinstance(value, str) and ('DIR' in name or 'LOG' in name or 'FILE' in name or 'ROOT' in name):
                    self.assertNotIn('combo_twap', value)
                    self.assertNotIn('combo_top20_twap', value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
