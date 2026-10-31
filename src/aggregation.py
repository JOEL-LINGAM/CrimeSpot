"""Step D: distributed aggregations written with Spark SQL over a temp view of the cleaned data."""
from pyspark.sql import DataFrame, SparkSession

AGGREGATES = {
    "agg_year_month": "SELECT year, month, year_month, COUNT(*) AS incidents FROM crimes GROUP BY year, month, year_month",
    "agg_hour_weekday": "SELECT weekday_num, weekday_name, hour, COUNT(*) AS incidents FROM crimes GROUP BY weekday_num, weekday_name, hour",
    "agg_month_hour": "SELECT month, month_name, hour, COUNT(*) AS incidents FROM crimes GROUP BY month, month_name, hour",
    "agg_category": "SELECT category, COUNT(*) AS incidents FROM crimes GROUP BY category",
    "agg_category_year_month": "SELECT category, year, month, year_month, COUNT(*) AS incidents FROM crimes GROUP BY category, year, month, year_month",
    "agg_category_hour": "SELECT category, hour, COUNT(*) AS incidents FROM crimes GROUP BY category, hour",
    "agg_category_weekday": "SELECT category, weekday_num, weekday_name, COUNT(*) AS incidents FROM crimes GROUP BY category, weekday_num, weekday_name",
    "agg_weekend": "SELECT is_weekend, COUNT(*) AS incidents, COUNT(DISTINCT year_month) AS months_covered FROM crimes GROUP BY is_weekend",
    "agg_area": "SELECT area, COUNT(*) AS incidents FROM crimes WHERE area IS NOT NULL GROUP BY area",
    "agg_area_year_month": "SELECT area, year, month, year_month, COUNT(*) AS incidents FROM crimes WHERE area IS NOT NULL GROUP BY area, year, month, year_month",
    "agg_cell": ("SELECT cell_id, cell_lat, cell_lon, COUNT(*) AS incidents, "
                 "MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen FROM crimes GROUP BY cell_id, cell_lat, cell_lon"),
    "agg_cell_year": "SELECT cell_id, cell_lat, cell_lon, year, COUNT(*) AS incidents FROM crimes GROUP BY cell_id, cell_lat, cell_lon, year",
    "agg_cell_category": "SELECT cell_id, cell_lat, cell_lon, category, COUNT(*) AS incidents FROM crimes GROUP BY cell_id, cell_lat, cell_lon, category",
    "agg_cell_hour": "SELECT cell_id, cell_lat, cell_lon, hour, COUNT(*) AS incidents FROM crimes GROUP BY cell_id, cell_lat, cell_lon, hour",
}


def run_aggregates(spark: SparkSession, df: DataFrame, include_area: bool = True) -> dict:
    """Return {name: Spark DataFrame}. Nothing is collected to the driver here."""
    df.createOrReplaceTempView("crimes")
    out = {}
    for name, sql in AGGREGATES.items():
        if "area" in name and (not include_area or "area" not in df.columns):
            continue
        out[name] = spark.sql(sql)
    return out


def monthly_change(spark: SparkSession, agg_year_month: DataFrame) -> DataFrame:
    """Month-over-month change using a window; percent change is NULL when the previous month is 0."""
    agg_year_month.createOrReplaceTempView("ym")
    return spark.sql("""
        SELECT year_month, incidents,
               LAG(incidents) OVER (ORDER BY year_month) AS previous,
               incidents - LAG(incidents) OVER (ORDER BY year_month) AS abs_change,
               CASE WHEN LAG(incidents) OVER (ORDER BY year_month) > 0
                    THEN 100.0 * (incidents - LAG(incidents) OVER (ORDER BY year_month))
                         / LAG(incidents) OVER (ORDER BY year_month) END AS pct_change
        FROM ym ORDER BY year_month""")


def build_cubes(spark: SparkSession, df: DataFrame, hour_block: int = 3, include_area: bool = True) -> dict:
    """Compact 'cubes' that let the dashboard apply date/category/hour/day-type filters on the fly
    without re-running Spark. Counts stay EXACT; only the grain is coarsened (hours -> blocks on the map cube,
    years instead of months for the area-by-hour cube)."""
    df.createOrReplaceTempView("crimes")
    sql = {
        "cube_time": "SELECT year_month, category, weekday_num, hour, COUNT(*) AS incidents "
                     "FROM crimes GROUP BY year_month, category, weekday_num, hour",
        "cube_cell": f"SELECT cell_id, cell_lat, cell_lon, year_month, category, "
                     f"CAST(hour DIV {int(hour_block)} AS INT) AS hour_block, is_weekend, COUNT(*) AS incidents "
                     f"FROM crimes GROUP BY cell_id, cell_lat, cell_lon, year_month, category, "
                     f"CAST(hour DIV {int(hour_block)} AS INT), is_weekend",
    }
    if include_area and "area" in df.columns:
        sql["cube_area"] = ("SELECT area, year_month, category, COUNT(*) AS incidents FROM crimes "
                            "WHERE area IS NOT NULL GROUP BY area, year_month, category")
        sql["cube_area_time"] = ("SELECT area, year, weekday_num, hour, COUNT(*) AS incidents FROM crimes "
                                 "WHERE area IS NOT NULL GROUP BY area, year, weekday_num, hour")
    return {name: spark.sql(q) for name, q in sql.items()}
