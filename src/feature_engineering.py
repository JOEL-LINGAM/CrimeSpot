"""Step C: temporal and spatial features. Timestamps are treated as LOCAL wall-clock time of the
reporting city (the source gives no zone); no time-zone conversion is applied."""
import pyspark.sql.functions as F
from pyspark.sql import DataFrame

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def add_features(df: DataFrame, cell_degrees: float = 0.01) -> DataFrame:
    ts = F.col("timestamp")
    iso_dow = ((F.dayofweek(ts) + 5) % 7) + 1          # Spark: 1=Sun..7=Sat  ->  ISO: 1=Mon..7=Sun
    month_names = F.array(*[F.lit(m) for m in MONTH_NAMES])
    wd_names = F.array(*[F.lit(d) for d in WEEKDAY_NAMES])
    lat_i = F.floor(F.col("latitude") / cell_degrees).cast("long")
    lon_i = F.floor(F.col("longitude") / cell_degrees).cast("long")
    return (
        df.withColumn("year", F.year(ts))
        .withColumn("month", F.month(ts))
        .withColumn("month_name", F.element_at(month_names, F.month(ts)))
        .withColumn("day", F.dayofmonth(ts))
        .withColumn("weekday_num", iso_dow)
        .withColumn("weekday_name", F.element_at(wd_names, iso_dow))
        .withColumn("hour", F.hour(ts))
        .withColumn("is_weekend", iso_dow >= 6)
        .withColumn("year_month", F.date_format(ts, "yyyy-MM"))
        .withColumn("cell_id", F.concat_ws("_", lat_i.cast("string"), lon_i.cast("string")))
        .withColumn("cell_lat", (lat_i + 0.5) * cell_degrees)
        .withColumn("cell_lon", (lon_i + 0.5) * cell_degrees)
    )
