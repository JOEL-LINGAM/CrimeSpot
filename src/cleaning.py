"""Step B: type conversion, validation, de-duplication and the data-quality report.

Every excluded row gets exactly ONE reason (the first rule it breaks, in the order below), so
    input = sum(excluded by reason) + duplicates_removed + retained
always reconciles.
"""
from pyspark.sql import DataFrame, Window
import pyspark.sql.functions as F

REASONS_IN_ORDER = [
    "missing_timestamp", "malformed_or_out_of_range_timestamp", "missing_category",
    "missing_coordinates", "invalid_coordinates", "outside_study_area",
]


def parse_timestamp(col, formats):
    return F.coalesce(*[F.to_timestamp(F.trim(col), f) for f in formats])


def normalise_category(col):
    return F.initcap(F.regexp_replace(F.upper(F.trim(col)), r"\s+", " "))


def tag_records(df: DataFrame, cfg: dict) -> DataFrame:
    v = cfg["validation"]
    ts_raw = F.col("timestamp")
    df = (
        df.withColumn("ts_raw", ts_raw)
        .withColumn("timestamp", parse_timestamp(ts_raw, cfg["timestamp_formats"]))
        .withColumn("latitude", F.col("latitude").cast("double"))
        .withColumn("longitude", F.col("longitude").cast("double"))
        .withColumn("category", F.when(F.trim(F.col("category")) == "", None).otherwise(F.col("category")))
        .withColumn("category", normalise_category(F.col("category")))
    )
    yr = F.year("timestamp")
    lat, lon = F.col("latitude"), F.col("longitude")
    bbox = F.lit(True)
    for col, key, op in [(lat, "lat_min", ">="), (lat, "lat_max", "<="), (lon, "lon_min", ">="), (lon, "lon_max", "<=")]:
        if v.get(key) is not None:
            bbox = bbox & ((col >= v[key]) if op == ">=" else (col <= v[key]))
    reason = (
        F.when(F.col("ts_raw").isNull() | (F.trim(F.col("ts_raw")) == ""), "missing_timestamp")
        .when(F.col("timestamp").isNull() | (yr < v["min_year"]) | (yr > v["max_year"]),
              "malformed_or_out_of_range_timestamp")
        .when(F.col("category").isNull(), "missing_category")
        .when(lat.isNull() | lon.isNull(), "missing_coordinates")
        .when((lat < -90) | (lat > 90) | (lon < -180) | (lon > 180) | ((lat == 0) & (lon == 0)),
              "invalid_coordinates")
        .when(~bbox, "outside_study_area")
    )
    return df.withColumn("reject_reason", reason).drop("ts_raw")


def deduplicate(valid: DataFrame) -> DataFrame:
    """With an incident id: keep ONE row per id (earliest timestamp, ties broken deterministically).
    Without one: remove only exact full-row duplicates. Rows that merely look similar are kept."""
    if "incident_id" in valid.columns:
        has_id = F.col("incident_id").isNotNull() & (F.trim(F.col("incident_id")) != "")
        with_id, no_id = valid.filter(has_id), valid.filter(~has_id)
        order_cols = [F.col("timestamp").asc()] + [F.col(c).asc_nulls_last() for c in sorted(valid.columns)
                                                    if c not in ("timestamp", "incident_id")]
        w = Window.partitionBy("incident_id").orderBy(*order_cols)
        kept = with_id.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")
        return kept.unionByName(no_id.dropDuplicates())   # id-less rows: exact duplicates only
    return valid.dropDuplicates()


def missing_value_stats(df: DataFrame) -> dict:
    """Null/blank counts per mapped column, computed in ONE Spark pass."""
    aggs = [F.count(F.lit(1)).alias("__total")] + [
        F.sum(F.when(F.col(c).isNull() | (F.trim(F.col(c).cast("string")) == ""), 1).otherwise(0)).alias(c)
        for c in df.columns
    ]
    row = df.agg(*aggs).first().asDict()
    total = row.pop("__total")
    return {c: {"missing": int(n or 0), "pct": round(100 * (n or 0) / total, 4) if total else 0.0}
            for c, n in row.items()}


def clean(df: DataFrame, cfg: dict):
    """Returns (clean_df, quality_report_dict). df must already use canonical column names."""
    raw_missing = missing_value_stats(df)
    tagged = tag_records(df, cfg).cache()   # reused for 3 actions below; justified cache
    try:
        input_rows = tagged.count()
        counts = {r["reject_reason"]: r["n"] for r in
                  tagged.filter("reject_reason IS NOT NULL").groupBy("reject_reason").agg(F.count("*").alias("n")).collect()}
        valid = tagged.filter(F.col("reject_reason").isNull()).drop("reject_reason")
        valid_rows = input_rows - sum(counts.values())
        deduped = deduplicate(valid)
        out = deduped.cache()
        retained = out.count()
    finally:
        tagged.unpersist()
    excluded = {r: int(counts.get(r, 0)) for r in REASONS_IN_ORDER}
    dup = valid_rows - retained
    report = {
        "input_records": int(input_rows),
        "excluded_by_reason": excluded,
        "excluded_total": int(sum(excluded.values())),
        "valid_before_dedup": int(valid_rows),
        "duplicates_removed": int(dup),
        "retained_records": int(retained),
        "reconciles": bool(input_rows == sum(excluded.values()) + dup + retained),
        "raw_missing_values": raw_missing,
        "dedup_rule": ("one row per incident_id (earliest timestamp kept)" if "incident_id" in df.columns
                       else "exact full-row duplicates only (no incident_id column)"),
    }
    return out, report
