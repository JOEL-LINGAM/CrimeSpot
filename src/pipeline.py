"""Orchestrates ingestion -> cleaning -> features -> aggregation -> Parquet + metrics JSON."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import pyspark.sql.functions as F

from .config import load_config, resolve
from .ingestion import get_spark, read_raw_csv, standardise_columns
from .cleaning import clean
from .feature_engineering import add_features
from .aggregation import run_aggregates, monthly_change, build_cubes
from .hotspot_analysis import rank_hotspots, cluster_cells
from .metrics_utils import month_range


def _dir_size_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def run_pipeline(config_path=None, raw_path=None, limit_rows=None, tag="full") -> dict:
    cfg = load_config(config_path)
    raw = resolve(raw_path or cfg["dataset"]["raw_path"])
    out_dir = resolve(cfg["paths"]["processed_dir"]) / tag
    metrics_dir = resolve(cfg["paths"]["metrics_dir"]); metrics_dir.mkdir(parents=True, exist_ok=True)
    nparts = cfg["spark"].get("output_partitions", 4)

    stages, t_all = {}, time.perf_counter()
    spark = get_spark(cfg)

    t = time.perf_counter()
    df = read_raw_csv(spark, raw)
    if limit_rows:
        df = df.limit(int(limit_rows))
    df, mapping = standardise_columns(df, cfg)
    input_partitions = df.rdd.getNumPartitions()
    stages["ingest_and_map_s"] = time.perf_counter() - t   # lazy: real read cost shows up in the next stage

    t = time.perf_counter()
    cleaned, quality = clean(df, cfg)
    stages["clean_and_dedup_s"] = time.perf_counter() - t

    t = time.perf_counter()
    feats = add_features(cleaned, cfg["features"]["grid_cell_degrees"])
    (feats.repartition(nparts).write.mode("overwrite").parquet(str(out_dir / "clean_crimes")))
    stages["features_and_write_clean_s"] = time.perf_counter() - t
    cleaned.unpersist()

    t = time.perf_counter()
    stored = spark.read.parquet(str(out_dir / "clean_crimes"))      # aggregate from Parquet, not from raw CSV
    aggs = run_aggregates(spark, stored)
    agg_rows = {}
    for name, adf in aggs.items():
        adf.coalesce(1).write.mode("overwrite").parquet(str(out_dir / name))   # small outputs -> 1 file
        agg_rows[name] = spark.read.parquet(str(out_dir / name)).count()
    monthly_change(spark, spark.read.parquet(str(out_dir / "agg_year_month"))).coalesce(1) \
        .write.mode("overwrite").parquet(str(out_dir / "agg_monthly_change"))
    stages["aggregations_s"] = time.perf_counter() - t

    t = time.perf_counter()
    an = cfg.get("analytics", {})
    for name, cdf in build_cubes(spark, stored, an.get("map_hour_block", 3)).items():
        cdf.coalesce(max(1, nparts // 2)).write.mode("overwrite").parquet(str(out_dir / name))
    stages["cubes_s"] = time.perf_counter() - t

    t = time.perf_counter()
    mm = stored.agg(F.min("timestamp").alias("mn"), F.max("timestamp").alias("mx"), F.min("year_month").alias("fm")).first()
    hot = rank_hotspots(stored, an.get("hotspot_min_incidents", 10), str(mm["mx"]), mm["fm"])
    hot.coalesce(1).write.mode("overwrite").parquet(str(out_dir / "hotspots"))
    assign, csum, cinfo = cluster_cells(
        spark, spark.read.parquet(str(out_dir / "agg_cell")), None, an.get("kmeans_k_min", 4),
        an.get("kmeans_k_max", 10), an.get("kmeans_min_cell_incidents", 10), an.get("kmeans_seed", 42))
    if assign is not None:
        assign.coalesce(1).write.mode("overwrite").parquet(str(out_dir / "cell_clusters"))
        csum.coalesce(1).write.mode("overwrite").parquet(str(out_dir / "cluster_summary"))
    (out_dir / "cluster_info.json").write_text(json.dumps(cinfo, indent=2), encoding="utf-8")
    stages["hotspots_and_clustering_s"] = time.perf_counter() - t

    stats = stored.agg(F.min("timestamp").alias("mn"), F.max("timestamp").alias("mx"),
                       F.countDistinct("category").alias("cats"), F.countDistinct("cell_id").alias("cells")).first()
    total_s = time.perf_counter() - t_all
    raw_size = raw.stat().st_size
    metrics = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tag": tag, "spark_version": spark.version, "master": cfg["spark"]["master"],
        "default_parallelism": spark.sparkContext.defaultParallelism,
        "input_file": str(raw), "input_file_bytes": raw_size,
        "input_records": quality["input_records"], "retained_records": quality["retained_records"],
        "input_partitions": input_partitions, "output_partitions": nparts,
        "stage_seconds": {k: round(v, 3) for k, v in stages.items()},
        "total_seconds": round(total_s, 3),
        "records_per_second": round(quality["input_records"] / total_s, 1) if total_s > 0 else None,
        "output_bytes_clean": _dir_size_bytes(out_dir / "clean_crimes"),
        "output_bytes_total": _dir_size_bytes(out_dir),
        "aggregate_row_counts": agg_rows,
        "is_synthetic": bool(cfg["dataset"].get("is_synthetic", False)),
    }
    dataset_info = {
        "name": cfg["dataset"]["name"], "source_url": cfg["dataset"]["source_url"],
        "attribution": cfg["dataset"]["attribution"], "is_synthetic": metrics["is_synthetic"],
        "date_min": str(stats["mn"]), "date_max": str(stats["mx"]),
        "n_categories": stats["cats"], "n_cells": stats["cells"],
        "column_mapping": mapping, "grid_cell_degrees": cfg["features"]["grid_cell_degrees"],
        "timestamp_note": "Local wall-clock time of the reporting city; no time-zone conversion applied.",
    }
    for name, obj in [("quality_report", quality), ("pipeline_metrics", metrics), ("dataset_info", dataset_info)]:
        (out_dir / f"{name}.json").write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    spark.stop()
    return {"quality": quality, "metrics": metrics, "dataset_info": dataset_info}
