"""Compare gsplat runs written by run_scene.bat (and run_stump.bat).

Usage:
    python compare.py [results_dir]
    python compare.py --run results/<version>/<length>/<scene>

--run prints a summary of one run instead: the number of Gaussians in each saved splat
(read from the ply file), and the quality, training time and memory at each step.
run_scene.bat calls it at the end of every run.

Reads results/<version>/<length>/<scene>/stats/*.json, where <version> is 153 (gsplat 1.5.3)
or 160 (gsplat 1.6.0), <length> is 7k or 30k with an optional _mcmc and _packed suffix,
and <scene> is stump, amorphophallus_rs and so on. Versions are only compared within the same
scene and length. simple_trainer.py writes two kinds of files:

    val_step<N>.json              psnr, ssim, lpips, ellipse_time (render s/image), num_GS
    train_step<N>_rank0.json      mem (peak GiB allocated), ellipse_time (training s), num_GS

N is the zero based step index, so 6999 means 7000 steps. The val file comes from the
evaluation pass over the saved checkpoint, the train file from the training run.
"""

import argparse
import glob
import json
import os
import re
import sys


VERSION_NAMES = {"153": "1.5.3", "160": "1.6.0"}

# A ply header is a few hundred bytes. Stop looking for end_header after this many
PLY_HEADER_MAX_BYTES = 65536



def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("Skipping %s: %s" % (path, e), file=sys.stderr)
        return None



def length_key(length):
    # 7k before 30k, and plain runs before their _mcmc and _packed variants
    m = re.match(r"(\d+)k(.*)$", length)
    return (int(m.group(1)), m.group(2)) if m else (10**9, length)



def read_stats(stats_dir):
    """
    Read the val and train json files of one run.

    Args:
        stats_dir: the run's stats folder

    Returns:
        dict of zero based step -> {"val": dict or None, "train": dict or None}
    """
    steps = {}
    for path in glob.glob(os.path.join(stats_dir, "val_step*.json")):
        m = re.search(r"val_step(\d+)\.json$", path)
        if m:
            steps.setdefault(int(m.group(1)), {})["val"] = load_json(path)
    for path in glob.glob(os.path.join(stats_dir, "train_step*_rank0.json")):
        m = re.search(r"train_step(\d+)_rank0\.json$", path)
        if m:
            steps.setdefault(int(m.group(1)), {})["train"] = load_json(path)
    return steps



def collect(results_dir):
    """Return a list of rows, one per (scene, version, length, step)."""
    rows = []
    for stats_dir in sorted(glob.glob(os.path.join(results_dir, "*", "*", "*", "stats"))):
        parts = os.path.normpath(stats_dir).split(os.sep)
        version, length, scene = parts[-4], parts[-3], parts[-2]
        steps = read_stats(stats_dir)
        for step in sorted(steps):
            val = steps[step].get("val") or {}
            train = steps[step].get("train") or {}
            rows.append(
                {
                    "scene": scene,
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
    rows.sort(key=lambda r: (r["scene"], r["version"], length_key(r["length"]), r["steps"]))
    return rows



def fmt(value, spec, missing="n/a"):
    return missing if value is None else format(value, spec)



def print_table(rows):
    header = "%-15s %-8s %-16s %7s %8s %8s %8s %10s %12s %10s" % (
        "scene",
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
            "%-15s %-8s %-16s %7d %8s %8s %8s %10s %12s %10s"
            % (
                r["scene"],
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
    by_key = {(r["scene"], r["version"], r["length"], r["steps"]): r for r in rows}
    lines = []
    for r in rows:
        if r["version"] == base:
            continue
        b = by_key.get((r["scene"], base, r["length"], r["steps"]))
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
            "%s: %s minus %s, %s, %d steps: %s"
            % (
                r["scene"],
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



def ply_vertex_count(path):
    """
    Number of Gaussians in a splat ply, read from its header.

    Each Gaussian is one vertex, so the header line "element vertex N" gives the count
    without reading the rest of the file.

    Args:
        path: ply file written by simple_trainer.py --save_ply

    Returns:
        the vertex count, or None when the header has no vertex element
    """
    with open(path, "rb") as f:
        header = f.read(PLY_HEADER_MAX_BYTES)
    header = header.split(b"end_header", 1)[0].decode("ascii", "replace")
    m = re.search(r"^element vertex (\d+)", header, re.MULTILINE)
    return int(m.group(1)) if m else None



def print_run_summary(run_dir):
    """
    Print the Gaussian count of each saved splat and the stats of one run.

    Args:
        run_dir: results/<version>/<length>/<scene>

    Returns:
        0 when the run has a splat or stats, 1 when it has neither
    """
    run_dir = os.path.normpath(run_dir)
    plys = []
    for path in glob.glob(os.path.join(run_dir, "ply", "point_cloud_*.ply")):
        m = re.search(r"point_cloud_(\d+)\.ply$", path)
        if m:
            plys.append((int(m.group(1)), path))
    steps = read_stats(os.path.join(run_dir, "stats"))

    print()
    print("Run summary: %s" % run_dir)
    if not plys and not steps:
        print("  no splat and no stats found, the run did not get to step 7000")
        return 1
    for step, path in sorted(plys):
        count = ply_vertex_count(path)
        size_mb = os.path.getsize(path) / 1024**2
        print("  splat at step %d: %s Gaussians, %.0f MB, %s" % (step + 1, fmt(count, ",d"), size_mb, path))
    for step in sorted(steps):
        val = steps[step].get("val") or {}
        train = steps[step].get("train") or {}
        print(
            "  step %d: PSNR %s, SSIM %s, LPIPS %s, training time %s s, peak GPU memory %s GiB"
            % (
                step + 1,
                fmt(val.get("psnr"), ".3f"),
                fmt(val.get("ssim"), ".4f"),
                fmt(val.get("lpips"), ".3f"),
                fmt(train.get("ellipse_time"), ".1f"),
                fmt(train.get("mem"), ".2f"),
            )
        )
    return 0



if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Compare gsplat runs, or summarise one run with --run")
    ap.add_argument("results_dir", nargs="?", default=os.path.join(here, "results"))
    ap.add_argument("--run", help="results/<version>/<length>/<scene> to summarise")
    args = ap.parse_args()
    if args.run:
        sys.exit(print_run_summary(args.run))
    results_dir = args.results_dir
    rows = collect(results_dir)
    if not rows:
        print("No stats found under %s" % os.path.join(results_dir, "<version>", "<length>", "<scene>", "stats"))
        sys.exit(1)
    print_table(rows)
    print_differences(rows)
