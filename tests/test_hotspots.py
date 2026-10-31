from datetime import datetime
import pytest
from src.feature_engineering import add_features
from src.hotspot_analysis import rank_hotspots, cluster_cells
from src.metrics_utils import (safe_pct_change, comparison_windows, split_halves, previous_period,
                               month_range, partial_months, shift_months)


def crimes(spark, spec):
    """spec: list of (lat, lon, category, n, datetime)"""
    rows = [(dt, cat, lat, lon) for lat, lon, cat, n, dt in spec for _ in range(n)]
    return add_features(spark.createDataFrame(rows, ["timestamp", "category", "latitude", "longitude"]), 0.01)


def test_ranking_order_shares_and_min_threshold(spark):
    d = datetime(2021, 3, 3, 12)
    df = crimes(spark, [(41.885, -87.625, "Theft", 6, d), (41.885, -87.625, "Battery", 2, d),
                        (41.705, -87.605, "Theft", 3, d), (41.955, -87.705, "Theft", 1, d)])
    r = rank_hotspots(df, min_incidents=2).collect()
    assert [x.rank for x in r] == [1, 2]                         # the 1-incident cell is below the threshold
    assert [x.incidents for x in r] == [8, 3]
    assert r[0].top_category == "Theft" and round(r[0].top_category_share_pct, 1) == 75.0
    assert round(r[0].share_pct, 2) == round(100 * 8 / 12, 2)    # share of ALL incidents, not just ranked ones
    assert round(r[1].cumulative_share_pct, 2) == round(100 * 11 / 12, 2)
    assert "pct_change_12m" not in rank_hotspots(df, 1).columns   # < 24 months of data: no trend columns


def test_ties_are_broken_deterministically(spark):
    d = datetime(2021, 3, 3, 12)
    df = crimes(spark, [(41.885, -87.625, "Theft", 2, d), (41.705, -87.605, "Theft", 2, d)])
    a = [x.cell_id for x in rank_hotspots(df, 1).collect()]
    b = [x.cell_id for x in rank_hotspots(df, 1).collect()]
    assert a == b == sorted(a)


def test_trend_columns_and_zero_baseline(spark):
    spec = [(41.885, -87.625, "Theft", 4, datetime(2020, 5, 10)), (41.885, -87.625, "Theft", 6, datetime(2021, 5, 10)),
            (41.705, -87.605, "Theft", 5, datetime(2021, 5, 10)),   # nothing in the previous 12 months
            (41.885, -87.625, "Theft", 1, datetime(2021, 12, 31))]
    df = crimes(spark, spec)
    r = {x.cell_id: x for x in rank_hotspots(df, 1, "2021-12-31 00:00:00", "2020-01").collect()}
    busy = r[[k for k in r if r[k].incidents == 11][0]]
    new = r[[k for k in r if r[k].incidents == 5][0]]
    assert (busy.incidents_prev_12m, busy.incidents_last_12m) == (4, 7) and round(busy.pct_change_12m, 1) == 75.0
    assert new.incidents_prev_12m == 0 and new.pct_change_12m is None


def test_kmeans_separates_blobs_and_labels_west_to_east(spark):
    pts = [(41.70 + i * 0.01, -87.90 + j * 0.01, 20) for i in range(3) for j in range(3)] + \
          [(41.95 + i * 0.01, -87.55 + j * 0.01, 5) for i in range(3) for j in range(3)]
    cells = spark.createDataFrame([(f"{i}", la, lo, n) for i, (la, lo, n) in enumerate(pts)],
                                  ["cell_id", "cell_lat", "cell_lon", "incidents"])
    assign, summary, info = cluster_cells(spark, cells, k=2, min_incidents=1)
    a = {r.cell_id: r.cluster_no for r in assign.collect()}
    assert len(a) == 18 and set(a.values()) == {1, 2}
    assert len({a[str(i)] for i in range(9)}) == 1 and len({a[str(i)] for i in range(9, 18)}) == 1
    assert a["0"] == 1 and a["9"] == 2                        # western blob is Cluster 1
    s = {r.cluster_no: r for r in summary.collect()}
    assert s[1].incidents == 180 and s[2].incidents == 45 and s[1].cells == 9
    assert info["chosen_k"] == 2 and -1 <= info["silhouette"] <= 1


def test_kmeans_auto_k_and_too_few_cells(spark):
    pts = [(41.70 + (i % 5) * 0.02, -87.90 + (i // 5) * 0.02, 10) for i in range(25)]
    cells = spark.createDataFrame([(str(i), la, lo, n) for i, (la, lo, n) in enumerate(pts)],
                                  ["cell_id", "cell_lat", "cell_lon", "incidents"])
    assign, summary, info = cluster_cells(spark, cells, k_min=3, k_max=5, min_incidents=1)
    assert 3 <= info["chosen_k"] <= 5 and len(info["scan"]) == 3 and assign.count() == 25
    none_a, _, info2 = cluster_cells(spark, cells.limit(2), min_incidents=1)
    assert none_a is None and "skipped" in info2["note"]


def test_pure_helpers():
    assert safe_pct_change(15, 10) == 50.0
    assert safe_pct_change(5, 0) is None and safe_pct_change(5, None) is None
    assert month_range("2020-11", "2021-02") == ["2020-11", "2020-12", "2021-01", "2021-02"]
    assert month_range("2021-02", "2020-11") == []
    assert shift_months("2021-01", -1) == "2020-12"
    assert split_halves("2020-01", "2020-12") == (("2020-01", "2020-06"), ("2020-07", "2020-12"))
    assert split_halves("2020-01", "2020-03") is None
    assert previous_period("2021-01", "2021-12", "2020-01") == ("2020-01", "2020-12")
    assert previous_period("2021-01", "2021-12", "2020-06") is None
    assert partial_months("2020-01-01 00:00:00", "2021-06-15 10:00:00") == ["2021-06"]
    assert partial_months("2020-01-03 00:00:00", "2021-06-30 23:00:00") == ["2020-01"]
    w = comparison_windows("2021-12-31 23:00:00", "2020-01")
    assert w == {"prev": ("2020-01", "2020-12"), "last": ("2021-01", "2021-12")}
    assert comparison_windows("2021-12-31", "2020-06") is None
    assert comparison_windows("2021-12-10", "2019-01")["last"][1] == "2021-11"
