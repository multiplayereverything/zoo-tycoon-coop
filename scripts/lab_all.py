"""Runs the whole co-op lab: lab_coop.py normally, then once per mutant, one copy pair at a time.

A run passes when every check passes, or, for a mutant, when exactly the checks that mutant breaks
fail (lab_coop's EXPECTED_FAIL). Writes private/lab-results/<timestamp>-summary.md (one row per run,
one column per check) and exits 0 only if every run met its expectation.

  python scripts/lab_all.py [--normal N] [--only no_place,no_remove]
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_coop  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(lab_coop.ROOT, "private", "lab-results")


def run_one(mutant):
    before = set(glob.glob(os.path.join(RESULTS, "*.json")))
    cmd = [sys.executable, os.path.join(HERE, "lab_coop.py"), "--shots"] + (["--mutant", mutant] if mutant else [])
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    new = sorted(set(glob.glob(os.path.join(RESULTS, "*.json"))) - before)
    if not new:
        return {"mutant": mutant, "checks": {}, "error": "no result file: " + proc.stderr[-300:], "expectation_met": False}
    with open(new[-1]) as f:
        r = json.load(f)
    r["seconds"] = round(time.time() - t0)
    r["file"] = os.path.basename(new[-1])
    return r


def cell(check, value, expect_fail):
    if check not in value:
        return "—"
    ok = value[check] is False if check in expect_fail else value[check] is True
    mark = "pass" if value[check] else "FAIL"
    return f"{mark}{'' if ok else ' ⚠'}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--normal", type=int, default=2, help="number of normal runs")
    ap.add_argument("--only", default="", help="comma-separated mutants (default: all)")
    args = ap.parse_args()
    mutants = [m for m in lab_coop.EXPECTED_FAIL if m] if not args.only else args.only.split(",")

    runs = [run_one(None) for _ in range(args.normal)] + [run_one(m) for m in mutants]

    lines = [f"# ZooTogether lab summary {time.strftime('%Y-%m-%d %H:%M')}", "",
             "Each cell is the check's result; ⚠ marks a result that differs from what the run expects "
             "(mutant runs expect the checks they break to FAIL).", "",
             "| run | " + " | ".join(lab_coop.ALL_CHECKS) + " | verdict |",
             "|---|" + "---|" * (len(lab_coop.ALL_CHECKS) + 1)]
    for r in runs:
        expect_fail = lab_coop.EXPECTED_FAIL.get(r["mutant"], set())
        cells = [cell(c, r["checks"], expect_fail) for c in lab_coop.ALL_CHECKS]
        verdict = "PASS" if r.get("expectation_met") else "FAIL" + (f" ({r['error']})" if r.get("error") else "")
        lines.append(f"| {r['mutant'] or 'normal'} | " + " | ".join(cells) + f" | {verdict} |")
    lines += ["", "Result files: " + ", ".join(r.get("file", "?") for r in runs)]
    report = "\n".join(lines) + "\n"
    path = os.path.join(RESULTS, time.strftime("%Y%m%d-%H%M%S") + "-summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    ok = all(r.get("expectation_met") for r in runs)
    print("LAB:", "PASS" if ok else "FAIL", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
