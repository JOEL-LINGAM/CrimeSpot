"""Check a raw CSV BEFORE running the full pipeline: file exists, columns map, a quick row sample parses."""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_config, resolve
from src.ingestion import get_spark, read_raw_csv, standardise_columns, MissingColumnsError

ap = argparse.ArgumentParser()
ap.add_argument("--config", default=None)
ap.add_argument("--input", default=None)
a = ap.parse_args()
cfg = load_config(a.config)
path = resolve(a.input or cfg["dataset"]["raw_path"])
try:
    spark = get_spark(cfg, "CrimeScope-validate")
    raw = read_raw_csv(spark, path)
    print("File:", path, f"({path.stat().st_size/1e6:.1f} MB)")
    print("Columns found:", raw.columns)
    df, mapping = standardise_columns(raw, cfg)
    print("Column mapping:", mapping)
    print("Sample rows:"); df.limit(5).show(truncate=40)
    print("OK - dataset looks usable. Next: python scripts/run_pipeline.py")
except (FileNotFoundError, MissingColumnsError) as e:
    print("PROBLEM:", e); sys.exit(1)
