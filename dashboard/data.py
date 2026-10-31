"""Dashboard data layer: loading precomputed Parquet outputs, applying filters, computing metrics.
No Streamlit import here, so everything is unit-testable. The Spark pipeline is NEVER run from the dashboard."""
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from src.metrics_utils import (month_range, n_months, safe_pct_change, split_halves, previous_period,
                               partial_months)

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_TYPES = ("All", "Weekday", "Weekend")


class InvalidFilters(ValueError):
    pass


@dataclass(frozen=True)
class Filters:
    start: str                      # 'YYYY-MM' inclusive
    end: str
    categories: tuple = ()          # empty = all categories
    hour_min: int = 0
    hour_max: int = 23
    day_type: str = "All"

    def key(self):
        return (self.start, self.end, tuple(sorted(self.categories)), self.hour_min, self.hour_max, self.day_type)

    @property
    def hours_are_full_day(self):
        return self.hour_min == 0 and self.hour_max == 23


def validate_filters(f: Filters):
    errs = []
    if f.start > f.end:
        errs.append("Start month is after end month.")
    if not (0 <= f.hour_min <= f.hour_max <= 23):
        errs.append("Hour range must satisfy 0 <= from <= to <= 23.")
    if f.day_type not in DAY_TYPES:
        errs.append(f"Day type must be one of {DAY_TYPES}.")
    return errs


def _check(f):
    errs = validate_filters(f)
    if errs:
        raise InvalidFilters(" ".join(errs))


# ---------------------------------------------------------------- dataset discovery / metadata
def list_datasets(processed_root):
    root = Path(processed_root)
    if not root.exists():
        return []
    tags = [p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("bench_")
            and (p / "dataset_info.json").exists() and (p / "cube_time").exists()]
    return sorted(tags, key=lambda t: (t != "full", t))      # real data first


def _read_json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def load_meta(ds_dir):
    d = Path(ds_dir)
    return {"info": _read_json(d / "dataset_info.json", {}), "quality": _read_json(d / "quality_report.json", {}),
            "metrics": _read_json(d / "pipeline_metrics.json", {}), "cluster": _read_json(d / "cluster_info.json", {})}


def read_parquet(ds_dir, name, columns=None, filters=None):
    """Returns a DataFrame or None if that output does not exist. Column pruning + predicate push-down
    keep memory low even for large cubes."""
    p = Path(ds_dir) / name
    if not p.exists():
        return None
    return pd.read_parquet(p, columns=columns, filters=filters or None)


def _pa_filters(f: Filters, with_category=True, with_month=True):
    flt = []
    if with_month:
        flt += [("year_month", ">=", f.start), ("year_month", "<=", f.end)]
    if with_category and f.categories:
        flt.append(("category", "in", list(f.categories)))
    return flt or None


def _day_mask(df, f, col="weekday_num"):
    if f.day_type == "Weekend":
        return df[col] >= 6
    if f.day_type == "Weekday":
        return df[col] <= 5
    return pd.Series(True, index=df.index)


def load_time(ds_dir, f: Filters):
    """cube_time filtered by every global filter (date, category, hour range, day type)."""
    _check(f)
    df = read_parquet(ds_dir, "cube_time", filters=_pa_filters(f))
    if df is None:
        return None
    return df[df.hour.between(f.hour_min, f.hour_max) & _day_mask(df, f)].reset_index(drop=True)


def load_cells(ds_dir, f: Filters, hour_block=3):
    """cube_cell filtered by date, category, day type and hour range. The hour filter works on blocks
    (default 3 h), so a block is included when it overlaps the chosen range -> returns (df, is_exact)."""
    _check(f)
    df = read_parquet(ds_dir, "cube_cell", filters=_pa_filters(f))
    if df is None:
        return None, True
    lo, hi = f.hour_min // hour_block, f.hour_max // hour_block
    df = df[df.hour_block.between(lo, hi)]
    if f.day_type == "Weekend":
        df = df[df.is_weekend]
    elif f.day_type == "Weekday":
        df = df[~df.is_weekend]
    exact = (f.hour_min % hour_block == 0) and ((f.hour_max + 1) % hour_block == 0)
    return df.reset_index(drop=True), exact


def load_area_months(ds_dir, f: Filters, areas=()):
    """cube_area (area x month x category): honours date + category only (it has no hour/weekday grain)."""
    _check(f)
    df = read_parquet(ds_dir, "cube_area", filters=_pa_filters(f))
    if df is None:
        return None
    if areas:
        df = df[df.area.isin(areas)]
    return df.reset_index(drop=True)


def load_area_time(ds_dir, f: Filters, areas=()):
    """cube_area_time (area x year x weekday x hour): honours years, hours and day type; NOT category."""
    _check(f)
    y0, y1 = int(f.start[:4]), int(f.end[:4])
    df = read_parquet(ds_dir, "cube_area_time", filters=[("year", ">=", y0), ("year", "<=", y1)])
    if df is None:
        return None
    df = df[df.hour.between(f.hour_min, f.hour_max) & _day_mask(df, f)]
    if areas:
        df = df[df.area.isin(areas)]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- metrics
def cell_label(lat, lon):
    return f"{abs(lat):.3f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.3f}°{'E' if lon >= 0 else 'W'}"


def total_incidents(df):
    return int(df["incidents"].sum()) if df is not None and len(df) else 0


def monthly_series(time_df, start, end):
    """Complete month index (zeros where there are no incidents) so lines never silently skip months."""
    s = time_df.groupby("year_month")["incidents"].sum() if len(time_df) else pd.Series(dtype="int64")
    out = pd.DataFrame({"year_month": month_range(start, end)})
    out["incidents"] = out.year_month.map(s).fillna(0).astype(int)
    return out


def share_table(df, by):
    g = df.groupby(by, as_index=False)["incidents"].sum().sort_values("incidents", ascending=False, kind="stable")
    tot = g.incidents.sum()
    g["share_pct"] = (100 * g.incidents / tot).round(2) if tot else 0.0
    return g.reset_index(drop=True)


def pivot_hour_weekday(time_df):
    m = time_df.groupby(["weekday_num", "hour"])["incidents"].sum().unstack("hour").reindex(
        index=range(1, 8), columns=range(24)).fillna(0).astype(int)
    m.index = DAY_ORDER
    return m


def pivot_month_hour(time_df):
    t = time_df.assign(month=time_df.year_month.str[5:7].astype(int))
    m = t.groupby(["month", "hour"])["incidents"].sum().unstack("hour").reindex(
        index=range(1, 13), columns=range(24)).fillna(0).astype(int)
    m.index = MONTH_NAMES
    return m


def weekday_weekend(time_df):
    """Incidents per DAY (not per period): weekends have 2 of 7 days, so raw totals are not comparable."""
    wk = time_df[time_df.weekday_num >= 6].incidents.sum()
    wd = time_df[time_df.weekday_num <= 5].incidents.sum()
    return pd.DataFrame({"day_type": ["Weekday (Mon-Fri)", "Weekend (Sat-Sun)"], "incidents": [int(wd), int(wk)],
                         "days_in_week": [5, 2], "avg_per_day_of_week": [wd / 5, wk / 2]})


def year_over_year(time_df, partial=()):
    t = time_df[~time_df.year_month.isin(partial)]
    if t.empty:
        return t.assign(year=[], month=[])
    t = t.assign(year=t.year_month.str[:4].astype(int), month=t.year_month.str[5:7].astype(int))
    return t.groupby(["year", "month"], as_index=False)["incidents"].sum()


def seasonality(time_df, partial=()):
    """Average incidents per calendar month (partial edge months excluded). Needs >= 12 distinct months."""
    t = time_df[~time_df.year_month.isin(partial)]
    if t.year_month.nunique() < 12:
        return None
    s = t.groupby("year_month")["incidents"].sum().reset_index()
    s["month"] = s.year_month.str[5:7].astype(int)
    out = s.groupby("month", as_index=False)["incidents"].mean()
    out["month_name"] = out.month.map(lambda m: MONTH_NAMES[m - 1])
    return out.rename(columns={"incidents": "avg_incidents"})


def rank_hotspots(cell_df, min_incidents=10):
    """Pandas twin of the Spark ranking, applied to FILTERED data (category-/time-specific hotspots)."""
    if cell_df is None or cell_df.empty:
        return pd.DataFrame(columns=["rank", "cell_id", "cell_lat", "cell_lon", "incidents", "share_pct",
                                     "cumulative_share_pct", "top_category", "top_category_share_pct", "location"])
    g = cell_df.groupby(["cell_id", "cell_lat", "cell_lon"], as_index=False)["incidents"].sum()
    total = g.incidents.sum()
    cc = cell_df.groupby(["cell_id", "category"], as_index=False)["incidents"].sum().sort_values(
        ["cell_id", "incidents", "category"], ascending=[True, False, True])
    top = cc.drop_duplicates("cell_id")[["cell_id", "category", "incidents"]].rename(
        columns={"category": "top_category", "incidents": "_n"})
    g = g.merge(top, on="cell_id", how="left")
    g["top_category_share_pct"] = (100 * g._n / g.incidents).round(1)
    g = g[g.incidents >= min_incidents].sort_values(["incidents", "cell_id"], ascending=[False, True]).reset_index(drop=True)
    g["rank"] = g.index + 1
    g["share_pct"] = (100 * g.incidents / total).round(3) if total else 0.0
    g["cumulative_share_pct"] = g.share_pct.cumsum().round(2)
    g["location"] = [cell_label(a, b) for a, b in zip(g.cell_lat, g.cell_lon)]
    return g.drop(columns="_n")


def half_period_change(cell_df, start, end, key="cell_id", min_months=6):
    """Compare the first and second half of the selected period (equal length). Returns None if too short."""
    halves = split_halves(start, end, min_months)
    if halves is None or cell_df is None or cell_df.empty:
        return None
    (a0, a1), (b0, b1) = halves
    a = cell_df[cell_df.year_month.between(a0, a1)].groupby(key)["incidents"].sum().rename("first_half")
    b = cell_df[cell_df.year_month.between(b0, b1)].groupby(key)["incidents"].sum().rename("second_half")
    out = pd.concat([a, b], axis=1).fillna(0).astype(int).reset_index()
    out["abs_change"] = out.second_half - out.first_half
    out["pct_change"] = [safe_pct_change(s, f_) for s, f_ in zip(out.second_half, out.first_half)]
    out.attrs["halves"] = halves
    return out


def previous_period_filters(f: Filters, first_available: str):
    pp = previous_period(f.start, f.end, first_available)
    return replace(f, start=pp[0], end=pp[1]) if pp else None


def kpi_summary(time_df, cell_df, area_df=None):
    k = {"total": total_incidents(time_df), "categories": 0, "cells": 0, "top_category": None, "top_category_share": None,
         "top_cell": None, "top_cell_incidents": None, "top_area": None, "top_area_incidents": None}
    if k["total"] == 0:
        return k
    cats = share_table(time_df, "category")
    k["categories"] = int(len(cats))
    k["top_category"], k["top_category_share"] = cats.category.iloc[0], float(cats.share_pct.iloc[0])
    if cell_df is not None and len(cell_df):
        g = cell_df.groupby(["cell_id", "cell_lat", "cell_lon"], as_index=False)["incidents"].sum().sort_values(
            ["incidents", "cell_id"], ascending=[False, True])
        k["cells"] = int(len(g))
        k["top_cell"] = cell_label(g.cell_lat.iloc[0], g.cell_lon.iloc[0])
        k["top_cell_incidents"] = int(g.incidents.iloc[0])
    if area_df is not None and len(area_df):
        a = area_df.groupby("area", as_index=False)["incidents"].sum().sort_values(["incidents", "area"], ascending=[False, True])
        k["top_area"], k["top_area_incidents"] = str(a.area.iloc[0]), int(a.incidents.iloc[0])
    return k


def auto_summary(time_df, cell_df=None, partial=()):
    """Plain-language observations generated from the filtered data (descriptive only)."""
    tot = total_incidents(time_df)
    if tot == 0:
        return ["No recorded incidents match the current filters."]
    out = [f"{tot:,} recorded incidents match the current filters."]
    cats = share_table(time_df, "category")
    out.append(f"'{cats.category.iloc[0]}' is the most frequently recorded category ({cats.share_pct.iloc[0]:.1f}% of matching records).")
    hr = time_df.groupby("hour")["incidents"].sum()
    out.append(f"Recorded incidents peak at {int(hr.idxmax()):02d}:00-{int(hr.idxmax()):02d}:59 "
               f"and are lowest at {int(hr.idxmin()):02d}:00.")
    wd = time_df.groupby("weekday_num")["incidents"].sum().reindex(range(1, 8), fill_value=0)
    out.append(f"{DAY_ORDER[int(wd.idxmax()) - 1]} has the most recorded incidents, {DAY_ORDER[int(wd.idxmin()) - 1]} the fewest.")
    ww = weekday_weekend(time_df)
    if ww.incidents.sum():
        r = ww.avg_per_day_of_week.iloc[1] / ww.avg_per_day_of_week.iloc[0] if ww.avg_per_day_of_week.iloc[0] else None
        if r:
            out.append(f"Per day of the week, weekends average {r:.2f}x the weekday level (raw totals are not comparable: 2 days vs 5).")
    if cell_df is not None and len(cell_df):
        g = cell_df.groupby("cell_id")["incidents"].sum().sort_values(ascending=False)
        top = max(1, int(round(len(g) * 0.1)))
        out.append(f"The top 10% of active grid cells ({top:,} of {len(g):,}) contain {100 * g.head(top).sum() / g.sum():.1f}% of "
                   "geolocated incidents - recorded incidents are spatially concentrated (counts, not per-capita rates).")
    if any(m in set(time_df.year_month) for m in partial):
        out.append("Note: the first/last month of the dataset may be incomplete, so it is not directly comparable to full months.")
    return out


def cell_polygon(lat, lon, cell_deg):
    h = cell_deg / 2
    return [[lon - h, lat - h], [lon + h, lat - h], [lon + h, lat + h], [lon - h, lat + h]]


def n_months_label(f: Filters):
    n = n_months(f.start, f.end)
    return f"{f.start} to {f.end} ({n} month{'s' if n != 1 else ''})"


def month_range_safe(start, end):
    return month_range(start, end) or []
