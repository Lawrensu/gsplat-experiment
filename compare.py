"""Compare gsplat stump runs written by run_stump.bat.

Usage:
    python compare.py [results_dir]

Reads results/<version>/<length>/stump/stats/*.json, where <version> is 153 (gsplat 1.5.3)
or 160 (gsplat 1.6.0) and <length> is 7k or 30k. simple_trainer.py writes two kinds of files:

    val_step<N>.json              psnr, ssim, lpips, ellipse_time (render s/image), num_GS
    train_step<N>_rank0.json      mem (peak GiB allocated), ellipse_time (training s), num_GS

N is the zero based step index, so 6999 means 7000 steps. The val file comes from the
evaluation pass over the saved checkpoint, the train file from the training run.
"""

import glob
import json
import os
import re
import sys


VERSION_NAMES = {"153": "1.5.3", "160": "1.6.0"}



def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("Skipping %s: %s" % (path, e), file=sys.stderr)
        return None



def length_key(length):
    # 7k before 30k
    m = re.match(r"(\d+)k$", length)
    return (int(m.group(1)) if m else 10**9, length)



def collect(results_dir):
    """Return a list of rows, one per (version, length, step)."""
    rows = []
    for stats_dir in sorted(glob.glob(os.path.join(results_dir, "*", "*", "stump", "stats"))):
        parts = os.path.normpath(stats_dir).split(os.sep)
        version, length = parts[-4], parts[-3]
        steps = {}
        for path in glob.glob(os.path.join(stats_dir, "val_step*.json")):
            m = re.search(r"val_step(\d+)\.json$", path)
            if m:
                steps.setdefault(int(m.group(1)), {})["val"] = load_json(path)
        for path in glob.glob(os.path.join(stats_dir, "train_step*_rank0.json")):
            m = re.search(r"train_step(\d+)_rank0\.json$", path)
            if m:
                steps.setdefault(int(m.group(1)), {})["train"] = load_json(path)
        for step in sorted(steps):
            val = steps[step].get("val") or {}
            train = steps[step].get("train") or {}
            rows.append(
                {
                    "version": version,
                    "length": length,
                    "steps": step + 1,
                    "psnr": val.get("psnr"),
                    "ssim": val.get("ssim"),
                    "lpips": val.get("lpips"),
                    "num_gs": val.get("num_GS", train.get("num_GS")),
                    "time": train.get("ellipse_time"),
                    "mem": train.get("mem"),
                }
            )
    rows.sort(key=lambda r: (r["version"], length_key(r["length"]), r["steps"]))
    return rows



def fmt(value, spec, missing="n/a"):
    return missing if value is None else format(value, spec)



def print_table(rows):
    header = "%-8s %-6s %7s %8s %8s %8s %10s %12s %10s" % (
        "version",
        "length",
        "steps",
        "PSNR",
        "SSIM",
        "LPIPS",
        "GS count",
        "train time",
        "peak mem",
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            "%-8s %-6s %7d %8s %8s %8s %10s %12s %10s"
            % (
                VERSION_NAMES.get(r["version"], r["version"]),
                r["length"],
                r["steps"],
                fmt(r["psnr"], ".3f"),
                fmt(r["ssim"], ".4f"),
                fmt(r["lpips"], ".3f"),
                fmt(r["num_gs"], ",d"),
                fmt(r["time"], ".1f") + (" s" if r["time"] is not None else ""),
                fmt(r["mem"], ".2f") + (" GiB" if r["mem"] is not None else ""),
            )
        )
    print()
    print("train time: seconds since the training loop started, up to that step")
    print("peak mem: torch.cuda.max_memory_allocated up to that step")
    print("n/a: the matching val or train json was not found")
    print("30k rows at 7000 steps are the step 7000 checkpoint of the 30000 step run")



def print_differences(rows):
    versions = sorted({r["version"] for r in rows})
    if len(versions) < 2:
        return
    base = versions[0]
    by_key = {(r["version"], r["length"], r["steps"]): r for r in rows}
    lines = []
    for r in rows:
        if r["version"] == base:
            continue
        b = by_key.get((base, r["length"], r["steps"]))
        if b is None:
            continue
        parts = []
        for name, spec in (("psnr", "+.3f"), ("ssim", "+.4f"), ("lpips", "+.3f")):
            if r[name] is not None and b[name] is not None:
                parts.append("%s %s" % (name.upper(), format(r[name] - b[name], spec)))
        if r["num_gs"] and b["num_gs"]:
            parts.append("GS x%.3f" % (r["num_gs"] / b["num_gs"]))
        if r["time"] and b["time"]:
            parts.append("time x%.3f" % (r["time"] / b["time"]))
        if r["mem"] is not None and b["mem"] is not None:
            parts.append("mem %s GiB" % format(r["mem"] - b["mem"], "+.2f"))
        lines.append(
            "%s minus %s, %s, %d steps: %s"
            % (
                VERSION_NAMES.get(r["version"], r["version"]),
                VERSION_NAMES.get(base, base),
                r["length"],
                r["steps"],
                ", ".join(parts),
            )
        )
    if lines:
        print()
        print("Differences against %s" % VERSION_NAMES.get(base, base))
        for line in lines:
            print(line)



if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    results_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "results")
    rows = collect(results_dir)
    if not rows:
        print("No stats found under %s" % os.path.join(results_dir, "<version>", "<length>", "stump", "stats"))
        sys.exit(1)
    print_table(rows)
    print_differences(rows)
