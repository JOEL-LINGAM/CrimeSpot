"""Run the pipeline on increasing input sizes and record REAL measurements (no estimates).
Output: outputs/metrics/benchmarks_<dataset-tag>.json  (shown on the dashboard's Performance Lab page).
Each run starts a fresh Spark session (cold start), so numbers include JVM start-up and are specific to
THIS machine, THIS data and THIS configuration. Do not read them as a general Spark-vs-Pandas result."""
import argparse, json, os, platform, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_config, resolve
from src.pipeline import run_pipeline

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=None)
ap.add_argument("--input", default=None)
ap.add_argument("--sizes", type=int, nargs="+", default=[5000, 10000, 20000],
                help="row limits to test, e.g. 100000 500000 2000000 (use 0 for the whole file)")
ap.add_argument("--repeats", type=int, default=1)
ap.add_argument("--name", default="full", help="dashboard dataset tag these results belong to")
a = ap.parse_args()
cfg = load_config(a.config)
runs = []

def save():
    out = {"recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset_tag": a.name,
           "is_synthetic": bool(cfg["dataset"].get("is_synthetic")),
           "machine": {"platform": platform.platform(), "python": platform.python_version(), "logical_cpus": os.cpu_count(),
                       "spark_master": cfg["spark"]["master"], "driver_memory": cfg["spark"]["driver_memory"]},
           "note": "Cold-start runs on a single machine in Spark local mode; not a distributed-cluster measurement.", "runs": runs}
    d = resolve(cfg["paths"]["metrics_dir"]); d.mkdir(parents=True, exist_ok=True)
    (d / f"benchmarks_{a.name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return d / f"benchmarks_{a.name}.json"

for n in a.sizes:
    for r in range(a.repeats):
        tag = f"bench_{n}_{r}"
        res = run_pipeline(a.config, a.input, n or None, tag)
        m = res["metrics"]
        runs.append({"requested_rows": n or "all", "repeat": r + 1, "input_records": m["input_records"], "retained_records": m["retained_records"],
                     "input_file_bytes": m["input_file_bytes"], "total_seconds": m["total_seconds"], "stage_seconds": m["stage_seconds"],
                     "records_per_second": m["records_per_second"], "input_partitions": m["input_partitions"],
                     "output_bytes_total": m["output_bytes_total"]})
        shutil.rmtree(resolve(cfg["paths"]["processed_dir"]) / tag, ignore_errors=True)
        print("done", n, r + 1, m["total_seconds"], "s"); save()
print("saved", save())
