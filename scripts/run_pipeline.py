import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.pipeline import run_pipeline

ap = argparse.ArgumentParser(description="Run the CrimeScope PySpark pipeline")
ap.add_argument("--config", default=None)
ap.add_argument("--input", default=None, help="override dataset.raw_path")
ap.add_argument("--limit", type=int, default=None, help="process only the first N rows")
ap.add_argument("--tag", default="full", help="output sub-folder name under data/processed/")
a = ap.parse_args()
res = run_pipeline(a.config, a.input, a.limit, a.tag)
print(json.dumps({"quality": {k: v for k, v in res["quality"].items() if k != "raw_missing_values"},
                  "metrics": res["metrics"]}, indent=2, default=str))
