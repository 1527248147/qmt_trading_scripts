"""Embed the audited engine for standalone QMT paste-in models.

Default is read-only validation. Use --write after editing vwap_schedule.py.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = '# BEGIN EMBEDDED VWAP SCHEDULE\n'
END = '# END EMBEDDED VWAP SCHEDULE\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    engine = (ROOT / 'vwap_schedule.py').read_text(encoding='ascii')
    paths = list(ROOT.glob('combo_*_dual_model.py'))
    paths += list((ROOT / 'probes').glob('vwap_data_probe.py'))
    failed = []
    for path in paths:
        text = path.read_text(encoding='ascii')
        if text.count(START) != 1 or text.count(END) != 1:
            raise RuntimeError('invalid embed markers: ' + str(path))
        before, tail = text.split(START)
        old, after = tail.split(END)
        if old != engine:
            if args.write:
                path.write_text(before + START + engine + END + after,
                                encoding='ascii')
            else:
                failed.append(path.name)
    if failed:
        raise SystemExit('Embedded engine differs: ' + ', '.join(failed))
    print('VWAP embedded engine verified in %d standalone files' % len(paths))


if __name__ == '__main__':
    main()
