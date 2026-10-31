from src.feature_engineering import add_features


def test_temporal_and_grid_features(spark):
    from datetime import datetime
    # 2021-01-02 is a Saturday; 2021-01-04 is a Monday
    df = spark.createDataFrame([(datetime(2021, 1, 2, 23, 5), 41.8851, -87.6251),
                                (datetime(2021, 1, 4, 0, 0), 41.8851, -87.6251)],
                               ["timestamp", "latitude", "longitude"])
    r = add_features(df, 0.01).orderBy("timestamp").collect()
    sat, mon = r
    assert (sat.year, sat.month, sat.month_name, sat.day, sat.hour) == (2021, 1, "Jan", 2, 23)
    assert sat.weekday_name == "Sat" and sat.is_weekend is True and sat.weekday_num == 6
    assert mon.weekday_name == "Mon" and mon.is_weekend is False and mon.hour == 0
    assert sat.year_month == "2021-01"
    assert sat.cell_id == mon.cell_id                                  # same coordinates, same cell
    assert abs(sat.cell_lat - 41.885) < 1e-9 and abs(sat.cell_lon - (-87.625)) < 1e-9
