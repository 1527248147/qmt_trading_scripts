#coding:utf-8
"""Run the VWAP buy-side suites against combo_vwap/combo_buy_fill_model.py instead of the original.

The fill script is a copy of combo_buy_dual_model.py with one addition, so every
buy-side check written for the original must hold for it too. Each suite runs in
its own process with the module name redirected:

    python run_fill_variant.py            # FILL_REALLOCATE as shipped (True)
    python run_fill_variant.py off        # FILL_REALLOCATE = False

Exit status is non-zero if any suite fails.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_buy_auction.py", "test_buy_restart.py", "test_close_fixes.py",
          "test_file_io.py", "test_fill_realloc.py"]
BOOT = r'''
import importlib.util, sys, os, io, contextlib, runpy
root = os.path.dirname(os.path.abspath(%(here)r))
sys.path.insert(0, %(here)r); sys.path.insert(0, root)
spec = importlib.util.spec_from_file_location("combo_buy_dual_model",
                                              os.path.join(root, "combo_buy_fill_model.py"))
m = importlib.util.module_from_spec(spec)
sys.modules["combo_buy_dual_model"] = m
spec.loader.exec_module(m)
m.FILL_REALLOCATE = %(on)s
sys.argv = [%(suite)r]
runpy.run_path(os.path.join(%(here)r, %(suite)r), run_name="__main__")
'''
on = not (len(sys.argv) > 1 and sys.argv[1] == "off")
bad = []
for suite in SUITES:
    if suite == "test_fill_realloc.py" and not on:
        continue
    code = BOOT % {"here": HERE, "on": on, "suite": suite}
    r = subprocess.run([sys.executable, "-c", code], cwd=HERE,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ok = r.returncode == 0
    print("%-24s %s" % (suite, "PASS" if ok else "FAIL"))
    if not ok:
        bad.append(suite)
        print(r.stdout.decode("utf-8", "replace")[-4000:])
print("fill variant (FILL_REALLOCATE=%s): %s" % (on, "ALL PASS" if not bad else "FAILED " + ", ".join(bad)))
sys.exit(1 if bad else 0)
