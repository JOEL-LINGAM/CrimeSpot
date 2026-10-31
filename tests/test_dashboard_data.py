import json
import pandas as pd
import pytest

from dashboard import data as D


@pytest.fixture()
def ds(tmp_path):
    """A tiny hand-made 'processed dataset' (Parquet cubes) so tests never need Spark or a download."""
    rows = []
    for ym, cat, wd, hr, n in [("2021-01", "Theft", 1, 10, 4), ("2021-01", "Theft", 6, 23, 2), ("2021-02", "Battery", 3, 2, 5),
                               ("2021-03", "Theft", 7, 14, 3), ("2021-03", "Battery", 2, 9, 1)]:
        rows.append(dict(year_month=ym, category=cat, weekday_num=wd, hour=hr, incidents=n))
    pd.DataFrame(rows).to_parquet(tmp_path / "cube_time")
    cells = []
    for cid, la, lo, ym, cat, hb, wk, n in [("a", 41.885, -87.625, "2021-01", "Theft", 3, False, 4), ("a", 41.885, -87.625, "2021-01", "Theft", 7, True, 2),
                                            ("b", 41.705, -87.605, "2021-02", "Battery", 0, False, 5), ("a", 41.885, -87.625, "2021-03", "Theft", 4, True, 3),
                                            ("b", 41.705, -87.605, "2021-03", "Battery", 3, False, 1)]:
        cells.append(dict(cell_id=cid, cell_lat=la, cell_lon=lo, year_month=ym, category=cat, hour_block=hb, is_weekend=wk, incidents=n))
    pd.DataFrame(cells).to_parquet(tmp_path / "cube_cell")
    (tmp_path / "dataset_info.json").write_text(json.dumps({"name": "x"}))
    return tmp_path


F = D.Filters("2021-01", "2021-03")


def test_unfiltered_total_and_date_filter(ds):
    assert D.total_incidents(D.load_time(ds, F)) == 15
    assert D.total_incidents(D.load_time(ds, D.Filters("2021-02", "2021-03"))) == 9
    assert D.load_time(ds, D.Filters("2022-01", "2022-02")).empty


def test_category_hour_and_daytype_filters(ds):
    assert D.total_incidents(D.load_time(ds, D.Filters("2021-01", "2021-03", ("Theft",)))) == 9
    assert D.total_incidents(D.load_time(ds, D.Filters("2021-01", "2021-03", hour_min=9, hour_max=14))) == 8
    assert D.total_incidents(D.load_time(ds, D.Filters("2021-01", "2021-03", day_type="Weekend"))) == 5      # Sat + Sun rows
    assert D.total_incidents(D.load_time(ds, D.Filters("2021-01", "2021-03", day_type="Weekday"))) == 10


def test_invalid_filter_combinations_raise(ds):
    with pytest.raises(D.InvalidFilters):
        D.load_time(ds, D.Filters("2021-03", "2021-01"))
    with pytest.raises(D.InvalidFilters):
        D.load_time(ds, D.Filters("2021-01", "2021-03", hour_min=20, hour_max=5))
    with pytest.raises(D.InvalidFilters):
        D.load_cells(ds, D.Filters("2021-01", "2021-03", day_type="Sometimes"))
    assert D.validate_filters(F) == []


def test_cell_hour_blocks_and_exactness(ds):
    df, exact = D.load_cells(ds, D.Filters("2021-01", "2021-03", hour_min=0, hour_max=8), 3)
    assert exact and D.total_incidents(df) == 5                # only the Battery row in block 0 (00:00-02:59)
    assert set(df.hour_block) == {0}
    _, exact2 = D.load_cells(ds, D.Filters("2021-01", "2021-03", hour_min=1, hour_max=8), 3)
    assert not exact2                                        # not aligned to 3-hour blocks -> flagged as widened
    wk, _ = D.load_cells(ds, D.Filters("2021-01", "2021-03", day_type="Weekend"), 3)
    assert D.total_incidents(wk) == 5 and wk.is_weekend.all()


def test_missing_cube_returns_none(tmp_path):
    assert D.read_parquet(tmp_path, "cube_time") is None
    assert D.load_time(tmp_path, F) is None
    assert D.load_cells(tmp_path, F)[0] is None


def test_monthly_series_fills_gaps_with_zero():
    t = pd.DataFrame({"year_month": ["2021-01", "2021-03"], "incidents": [4, 6]})
    m = D.monthly_series(t, "2021-01", "2021-04")
    assert m.year_month.tolist() == ["2021-01", "2021-02", "2021-03", "2021-04"] and m.incidents.tolist() == [4, 0, 6, 0]


def test_pivots_have_fixed_shape_and_order(ds):
    t = D.load_time(ds, F)
    hw = D.pivot_hour_weekday(t)
    assert hw.shape == (7, 24) and list(hw.index) == D.DAY_ORDER and hw.values.sum() == 15
    assert hw.loc["Mon", 10] == 4 and hw.loc["Sat", 23] == 2
    mh = D.pivot_month_hour(t)
    assert mh.shape == (12, 24) and list(mh.index)[:3] == ["Jan", "Feb", "Mar"] and mh.values.sum() == 15


def test_weekday_weekend_normalisation(ds):
    ww = D.weekday_weekend(D.load_time(ds, F))
    assert ww.incidents.tolist() == [10, 5]
    assert ww.avg_per_day_of_week.tolist() == [2.0, 2.5]


def test_kpis_and_empty_kpis(ds):
    t = D.load_time(ds, F); c, _ = D.load_cells(ds, F, 3)
    k = D.kpi_summary(t, c)
    assert k["total"] == 15 and k["categories"] == 2 and k["top_category"] == "Theft" and k["cells"] == 2
    assert k["top_cell_incidents"] == 9 and k["top_cell"] == "41.885°N, 87.625°W"
    e = D.kpi_summary(D.load_time(ds, D.Filters("2030-01", "2030-02")), None)
    assert e["total"] == 0 and e["top_category"] is None


def test_rank_hotspots_pandas(ds):
    c, _ = D.load_cells(ds, F, 3)
    r = D.rank_hotspots(c, 1)
    assert r["rank"].tolist() == [1, 2] and r.incidents.tolist() == [9, 6]
    assert round(r.share_pct.iloc[0], 2) == 60.0 and r.cumulative_share_pct.iloc[-1] == 100.0
    assert r.top_category.tolist() == ["Theft", "Battery"]
    assert D.rank_hotspots(c, 100).empty and D.rank_hotspots(None).empty


def test_half_period_change_and_zero_baseline(ds):
    c, _ = D.load_cells(ds, D.Filters("2021-01", "2021-06"), 3)
    h = D.half_period_change(c, "2021-01", "2021-06").set_index("cell_id")
    assert h.loc["a", "first_half"] == 9 and h.loc["a", "second_half"] == 0 and h.loc["a", "pct_change"] == -100.0
    assert D.half_period_change(c, "2021-01", "2021-03") is None        # too short
    z = pd.DataFrame({"cell_id": ["n"], "year_month": ["2021-05"], "incidents": [7]})
    zz = D.half_period_change(z, "2021-01", "2021-06")
    assert pd.isna(zz["pct_change"].iloc[0])


def test_previous_period_filters():
    pf = D.previous_period_filters(D.Filters("2021-07", "2021-12", ("Theft",)), "2020-01")
    assert (pf.start, pf.end, pf.categories) == ("2021-01", "2021-06", ("Theft",))
    assert D.previous_period_filters(D.Filters("2021-01", "2021-12"), "2021-01") is None


def test_seasonality_needs_a_full_year_and_excludes_partial():
    short = pd.DataFrame({"year_month": ["2021-01", "2021-02"], "incidents": [1, 2]})
    assert D.seasonality(short) is None
    t = pd.DataFrame({"year_month": [f"2021-{m:02d}" for m in range(1, 13)], "incidents": range(1, 13)})
    assert D.seasonality(t, partial=["2021-12"]) is None            # only 11 complete months left
    assert len(D.seasonality(t)) == 12


def test_auto_summary_and_empty(ds):
    s = D.auto_summary(D.load_time(ds, F), D.load_cells(ds, F, 3)[0], ["2021-03"])
    assert any("15 recorded incidents" in x for x in s) and any("Theft" in x for x in s) and any("incomplete" in x for x in s)
    assert D.auto_summary(D.load_time(ds, D.Filters("2030-01", "2030-02"))) == ["No recorded incidents match the current filters."]


def test_list_datasets_ignores_benchmarks_and_orders_real_first(tmp_path):
    for tag in ["sample", "full", "bench_1000_0", "empty"]:
        (tmp_path / tag).mkdir()
        if tag != "empty":
            (tmp_path / tag / "dataset_info.json").write_text("{}"); (tmp_path / tag / "cube_time").mkdir()
    assert D.list_datasets(tmp_path) == ["full", "sample"]
    assert D.list_datasets(tmp_path / "nope") == []
