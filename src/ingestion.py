"""Step A: Spark session creation, CSV loading, column mapping and schema validation."""
import os
import sys
from pyspark.sql import SparkSession, DataFrame
import pyspark.sql.functions as F


class MissingColumnsError(ValueError):
    pass


def get_spark(cfg: dict, app_name: str = "CrimeScope") -> SparkSession:
    sp = cfg.get("spark", {})
    # make Spark use the same Python as the virtual environment (important on Windows)
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    spark = (
        SparkSession.builder.appName(app_name)
        .master(sp.get("master", "local[*]"))
        .config("spark.driver.memory", sp.get("driver_memory", "2g"))
        .config("spark.sql.shuffle.partitions", str(sp.get("shuffle_partitions", 8)))
        .config("spark.sql.session.timeZone", "UTC")   # we never convert time zones (see methodology)
        .config("spark.sql.ansi.enabled", "false")     # bad values become NULL and are counted, not fatal
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def build_mapping(source_columns, column_cfg: dict) -> dict:
    """Return {canonical_name: actual_source_column} for every canonical column we can find."""
    lower = {c.lower(): c for c in source_columns}
    mapping = {}
    for canon, candidates in column_cfg.items():
        for cand in candidates:
            if cand.lower() in lower:
                mapping[canon] = lower[cand.lower()]
                break
    return mapping


def read_raw_csv(spark: SparkSession, path) -> DataFrame:
    """Read every column as string; types are applied explicitly in cleaning so bad values
    are counted instead of silently corrupting the schema (no inferSchema = no extra full pass)."""
    if not os.path.exists(str(path)):
        raise FileNotFoundError(
            f"Input file not found: {path}\n"
            "Download the dataset and place it there, or change dataset.raw_path in config/config.yaml."
        )
    return (
        spark.read.option("header", True)
        .option("multiLine", False)
        .option("escape", '"')
        .option("mode", "PERMISSIVE")
        .csv(str(path))
    )


def standardise_columns(df: DataFrame, cfg: dict):
    """Rename source columns to canonical names; fail clearly if required ones are missing."""
    mapping = build_mapping(df.columns, cfg["columns"])
    missing = [c for c in cfg.get("required_columns", []) if c not in mapping]
    if missing:
        raise MissingColumnsError(
            f"Required column(s) {missing} not found. Columns in file: {df.columns}. "
            "Add the right names under 'columns:' in config/config.yaml."
        )
    out = df.select(*[F.col(f"`{src}`").alias(canon) for canon, src in mapping.items()])
    return out, mapping
