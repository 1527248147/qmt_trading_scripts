"""Run each offline suite in its own process. No terminal/broker connections."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('combo_buy_dual_model.py', 'combo_sell_dual_model.py', 'vwap_schedule.py',
           'probes/vwap_data_probe.py')


def main():
    for name in SOURCES:
        text = (ROOT / name).read_bytes().decode('ascii')
        ast.parse(text, filename=name, feature_version=(3, 6))
    subprocess.run([sys.executable, str(ROOT / 'tools/sync_vwap_engine.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'tools/update_probe_targets.py')], check=True)
    logs = ROOT / 'logs' / 'offline_tests'
    logs.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted((ROOT / 'tests').glob('test_*.py')):
        out = subprocess.run([sys.executable, '-X', 'utf8', str(path)],
                             cwd=str(ROOT), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=180)
        (logs / (path.stem + '.log')).write_bytes(out.stdout)
        results.append({'suite': path.name, 'exit_code': out.returncode})
        print(('%-38s %s' % (path.name, 'PASS' if out.returncode == 0 else 'FAIL')), flush=True)
        if out.returncode:
            print(out.stdout.decode('utf-8', errors='replace')[-7000:])
    manifest = json.loads((ROOT / 'docs/TWAP_SOURCE_SHA256.json').read_text())
    changes = [name for name, sha in manifest.items()
               if hashlib.sha256((ROOT.parent / 'combo_twap' / name).read_bytes()).hexdigest() != sha]
    (logs / 'summary.json').write_text(json.dumps(
        {'results': results, 'twap_source_changes': changes,
         'python': sys.version, 'ascii_python36_parse': True}, indent=2))
    print('Original TWAP source unchanged:', not changes)
    if changes or any(x['exit_code'] for x in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
