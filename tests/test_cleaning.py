import pytest
from src.cleaning import clean
from src.ingestion import standardise_columns, MissingColumnsError, build_mapping, read_raw_csv

COLS = ["incident_id", "timestamp", "category", "latitude", "longitude"]
GOOD = ("1", "01/05/2021 10:30:00 PM", "theft", "41.88", "-87.63")


def mk(spark, rows, cols=COLS):
    return spark.createDataFrame(rows, cols)


def test_each_rule_and_reconciliation(spark, cfg):
    rows = [
        GOOD,
        ("2", "", "THEFT", "41.88", "-87.63"),                      # missing timestamp
        ("3", "garbage", "THEFT", "41.88", "-87.63"),               # malformed timestamp
        ("4", "01/05/2021 10:30:00 PM", "  ", "41.88", "-87.63"),   # missing category
        ("5", "01/05/2021 10:30:00 PM", "THEFT", None, None),       # missing coords
        ("6", "01/05/2021 10:30:00 PM", "THEFT", "0", "0"),         # invalid coords
        ("7", "01/05/2021 10:30:00 PM", "THEFT", "30.0", "-90.0"),  # outside study area
        ("1", "01/05/2021 10:30:00 PM", "THEFT", "41.88", "-87.63"),# duplicate id
    ]
    out, rep = clean(mk(spark, rows), cfg)
    assert rep["input_records"] == 8
    assert rep["retained_records"] == 1 and rep["duplicates_removed"] == 1
    assert rep["excluded_by_reason"] == {
        "missing_timestamp": 1, "malformed_or_out_of_range_timestamp": 1, "missing_category": 1,
        "missing_coordinates": 1, "invalid_coordinates": 1, "outside_study_area": 1}
    assert rep["reconciles"]
    assert out.first()["category"] == "Theft"          # case normalised


def test_distinct_incidents_with_same_attributes_are_preserved(spark, cfg):
    rows = [("1", *GOOD[1:]), ("2", *GOOD[1:]), ("3", *GOOD[1:])]   # same time/place/type, different IDs
    _, rep = clean(mk(spark, rows), cfg)
    assert rep["retained_records"] == 3 and rep["duplicates_removed"] == 0


def test_without_id_only_exact_duplicates_removed(spark, cfg):
    cols = COLS[1:]
    rows = [GOOD[1:], GOOD[1:], ("01/05/2021 10:30:00 PM", "THEFT", "41.8801", "-87.63")]
    _, rep = clean(mk(spark, rows, cols), cfg)
    assert rep["retained_records"] == 2 and rep["duplicates_removed"] == 1


def test_empty_dataset(spark, cfg):
    from pyspark.sql.types import StructType, StructField, StringType
    empty = spark.createDataFrame([], StructType([StructField(c, StringType()) for c in COLS]))
    out, rep = clean(empty, cfg)
    assert rep["input_records"] == 0 and rep["retained_records"] == 0 and rep["reconciles"]


def test_missing_required_column_gives_clear_error(spark, cfg):
    df = spark.createDataFrame([("1", "x")], ["ID", "Date"])
    with pytest.raises(MissingColumnsError, match="Required column"):
        standardise_columns(df, cfg)


def test_column_name_mapping_is_case_insensitive(cfg):
    m = build_mapping(["id", "DATE", "primary type", "LATITUDE", "longitude"], cfg["columns"])
    assert m["timestamp"] == "DATE" and m["category"] == "primary type" and m["incident_id"] == "id"


def test_missing_file_gives_clear_error(spark):
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        read_raw_csv(spark, "does/not/exist.csv")
