"""Step E: historical hotspot ranking (frequency-based) and geographical K-Means clustering.

* The geographic unit is a regular grid cell (config features.grid_cell_degrees).
* A "hotspot" here simply means a cell with a historically higher RECORDED incident count.
  It is a descriptive ranking, not a risk score and not a forecast.
* K-Means groups cells by location (weighted by incident counts). Cluster numbers carry NO ranking:
  they are labelled west -> east purely so the labels are stable and meaningless as a "severity".
"""
import math
import pyspark.sql.functions as F
from pyspark.sql import DataFrame, SparkSession, Window

from .metrics_utils import comparison_windows


def rank_hotspots(df: DataFrame, min_incidents: int = 1, date_max=None, first_month=None) -> DataFrame:
    """Rank grid cells by recorded incidents. `df` is the cleaned+features DataFrame.
    Columns: rank, cell, centre, incidents, share_pct (of ALL incidents), cumulative_share_pct,
    top_category (+ its share), active_months and, when >=24 complete months exist,
    last-12-vs-previous-12-month counts and a percentage change that is NULL if the baseline is 0."""
    base = df.groupBy("cell_id", "cell_lat", "cell_lon").agg(
        F.count("*").alias("incidents"), F.countDistinct("year_month").alias("active_months"))
    total = base.agg(F.sum("incidents")).first()[0] or 0
    ranked = base.filter(F.col("incidents") >= min_incidents)
    w = Window.orderBy(F.col("incidents").desc(), F.col("cell_id"))
    # NOTE: a global window moves the (small) per-cell table to one partition; fine for a few thousand cells.
    ranked = (ranked.withColumn("rank", F.row_number().over(w))
              .withColumn("share_pct", F.lit(100.0) * F.col("incidents") / F.lit(float(total or 1)))
              .withColumn("cumulative_share_pct", F.lit(100.0) * F.sum("incidents").over(
                  w.rowsBetween(Window.unboundedPreceding, Window.currentRow)) / F.lit(float(total or 1))))
    # most frequent category inside each cell
    cc = df.groupBy("cell_id", "category").agg(F.count("*").alias("n"))
    wc = Window.partitionBy("cell_id").orderBy(F.col("n").desc(), F.col("category"))
    top = (cc.withColumn("r", F.row_number().over(wc)).filter("r = 1")
           .select("cell_id", F.col("category").alias("top_category"), F.col("n").alias("top_category_n")))
    ranked = ranked.join(top, "cell_id", "left").withColumn(
        "top_category_share_pct", F.lit(100.0) * F.col("top_category_n") / F.col("incidents")).drop("top_category_n")
    win = comparison_windows(date_max, first_month) if (date_max and first_month) else None
    if win:
        (ps, pe), (ls, le) = win["prev"], win["last"]
        yc = df.groupBy("cell_id").agg(
            F.sum(F.when(F.col("year_month").between(ls, le), 1).otherwise(0)).alias("incidents_last_12m"),
            F.sum(F.when(F.col("year_month").between(ps, pe), 1).otherwise(0)).alias("incidents_prev_12m"))
        ranked = ranked.join(yc, "cell_id", "left").withColumn(
            "pct_change_12m", F.when(F.col("incidents_prev_12m") > 0,
                                     100.0 * (F.col("incidents_last_12m") - F.col("incidents_prev_12m"))
                                     / F.col("incidents_prev_12m")))
    return ranked.orderBy("rank")


def cluster_cells(spark: SparkSession, cells: DataFrame, k=None, k_min=4, k_max=10,
                  min_incidents=10, seed=42):
    """K-Means on cell centres, weighted by incident count (MLlib `weightCol`).
    Longitude is scaled by cos(mean latitude) so one unit means roughly the same distance in both axes.
    K is picked by the best weighted silhouette in [k_min, k_max] unless `k` is given.
    Returns (assignments_df, summary_df, info_dict) or (None, None, info) when there are too few cells."""
    from pyspark.ml.clustering import KMeans
    from pyspark.ml.evaluation import ClusteringEvaluator
    from pyspark.ml.feature import VectorAssembler

    c = cells.filter(F.col("incidents") >= min_incidents).select("cell_id", "cell_lat", "cell_lon", "incidents")
    n = c.count()
    info = {"cells_used": n, "min_cell_incidents": min_incidents, "scan": [], "chosen_k": None,
            "method": "KMeans(weightCol=incidents) on [lon*cos(mean_lat), lat]", "seed": seed}
    if n < 3:
        info["note"] = "Fewer than 3 eligible cells: clustering skipped."
        return None, None, info
    lat0 = c.agg(F.avg("cell_lat")).first()[0]
    scale = math.cos(math.radians(lat0))
    feats = VectorAssembler(inputCols=["x", "y"], outputCol="features").transform(
        c.withColumn("x", F.col("cell_lon") * F.lit(scale)).withColumn("y", F.col("cell_lat"))).cache()
    try:
        candidates = [k] if k else list(range(max(2, k_min), min(k_max, n - 1) + 1)) or [2]
        best = None
        for kk in candidates:
            kk = min(kk, n - 1) if n > 2 else 2
            model = KMeans(k=kk, seed=seed, maxIter=50, weightCol="incidents", featuresCol="features").fit(feats)
            pred = model.transform(feats)
            try:
                sil = ClusteringEvaluator(featuresCol="features", predictionCol="prediction",
                                          weightCol="incidents").evaluate(pred)
            except Exception:                      # old Spark without weighted silhouette
                sil = ClusteringEvaluator(featuresCol="features", predictionCol="prediction").evaluate(pred)
            info["scan"].append({"k": kk, "silhouette": round(float(sil), 4)})
            if best is None or sil > best[0]:
                best = (sil, kk, model, pred)
        sil, kk, model, pred = best
        info["chosen_k"], info["silhouette"] = kk, round(float(sil), 4)
        # label clusters west -> east by centroid longitude: stable labels with NO severity meaning
        centres = sorted(enumerate(model.clusterCenters()), key=lambda t: t[1][0])
        mapping = spark.createDataFrame([(int(raw), f"Cluster {i + 1}", i + 1) for i, (raw, _) in enumerate(centres)],
                                        ["prediction", "cluster_label", "cluster_no"])
        assign = pred.join(mapping, "prediction").select("cell_id", "cluster_no", "cluster_label")
        summary = (pred.join(mapping, "prediction").groupBy("cluster_no", "cluster_label").agg(
            F.count("*").alias("cells"), F.sum("incidents").alias("incidents"),
            (F.sum(F.col("cell_lat") * F.col("incidents")) / F.sum("incidents")).alias("centroid_lat"),
            (F.sum(F.col("cell_lon") * F.col("incidents")) / F.sum("incidents")).alias("centroid_lon"),
        ).orderBy("cluster_no"))
        assign, summary = assign.cache(), summary.cache()
        assign.count(); summary.count()      # materialise before unpersisting `feats`
        return assign, summary, info
    finally:
        feats.unpersist()
