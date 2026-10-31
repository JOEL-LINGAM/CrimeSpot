from datetime import datetime
from src.feature_engineering import add_features
from src.aggregation import run_aggregates, monthly_change


def make(spark):
    rows = [(datetime(2021, 1, 5, 10), "Theft", 41.88, -87.63, "A"),
            (datetime(2021, 1, 6, 10), "Theft", 41.88, -87.63, "A"),
            (datetime(2021, 2, 6, 22), "Battery", 41.70, -87.60, "B")]
    df = spark.createDataFrame(rows, ["timestamp", "category", "latitude", "longitude", "area"])
    return add_features(df)


def test_aggregates_sum_to_total_and_match_manual_counts(spark):
    df = make(spark)
    aggs = run_aggregates(spark, df)
    for name in ["agg_year_month", "agg_category", "agg_hour_weekday", "agg_cell", "agg_area", "agg_month_hour"]:
        assert aggs[name].agg({"incidents": "sum"}).first()[0] == 3, name
    cats = {r.category: r.incidents for r in aggs["agg_category"].collect()}
    assert cats == {"Theft": 2, "Battery": 1}
    assert aggs["agg_cell"].count() == 2


def test_monthly_change_handles_zero_baseline(spark):
    ym = spark.createDataFrame([("2021-01", 0), ("2021-02", 5), ("2021-03", 10)], ["year_month", "incidents"])
    r = {x.year_month: x for x in monthly_change(spark, ym).collect()}
    assert r["2021-01"].pct_change is None
    assert r["2021-02"].pct_change is None          # previous month is 0 -> no percentage
    assert r["2021-03"].pct_change == 100.0 and r["2021-03"].abs_change == 5


def test_empty_input_gives_empty_aggregates(spark):
    df = make(spark).limit(0)
    assert run_aggregates(spark, df)["agg_category"].count() == 0
