"""Refresh the read-only probe basket from the two model files, without importing them."""
import argparse
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def literal(path, name):
    for node in ast.parse(path.read_text(encoding='ascii')).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('missing literal ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    codes = sorted(set(literal(ROOT / 'combo_buy_dual_model.py', 'TARGETS')) |
                   set(literal(ROOT / 'combo_sell_dual_model.py', 'SELL_TARGETS')))
    path = ROOT / 'probes/vwap_data_probe.py'
    current = literal(path, 'PROBE_CODES')
    if codes != current:
        if not args.write:
            raise SystemExit('Probe basket is stale; use --write to sync')
        text = path.read_text(encoding='ascii')
        text, n = re.subn(r'^PROBE_CODES = \[[\s\S]*?\]\n',
                          'PROBE_CODES = ' + repr(codes) + '\n', text,
                          count=1, flags=re.MULTILINE)
        if n != 1:
            raise RuntimeError('probe basket anchor missing')
        path.write_text(text, encoding='ascii')
    print('Probe basket verified: %d unique names' % len(codes))


if __name__ == '__main__':
    main()
