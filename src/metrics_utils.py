"""Small, pure-Python helpers shared by the pipeline, the dashboard and the tests (no Spark import)."""
import calendar
from datetime import datetime


def safe_pct_change(current, previous):
    """Percent change, or None when it is not meaningful (missing or non-positive baseline)."""
    if current is None or previous is None:
        return None
    try:
        if previous <= 0:
            return None
    except TypeError:
        return None
    return 100.0 * (current - previous) / previous


def month_index(ym: str) -> int:
    y, m = int(ym[:4]), int(ym[5:7])
    return y * 12 + (m - 1)


def index_to_month(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def shift_months(ym: str, delta: int) -> str:
    return index_to_month(month_index(ym) + delta)


def month_range(start: str, end: str):
    """Inclusive list of 'YYYY-MM' strings."""
    a, b = month_index(start), month_index(end)
    return [index_to_month(i) for i in range(a, b + 1)] if a <= b else []


def n_months(start: str, end: str) -> int:
    return len(month_range(start, end))


def split_halves(start: str, end: str, min_months: int = 6):
    """Split a month range into (first_half, second_half) ranges of equal length.
    Returns None when the range is too short or has an odd month that cannot be split evenly
    (an odd range drops its first month so both halves are the same length)."""
    months = month_range(start, end)
    if len(months) < min_months:
        return None
    if len(months) % 2 == 1:
        months = months[1:]
    h = len(months) // 2
    return (months[0], months[h - 1]), (months[h], months[-1])


def previous_period(start: str, end: str, first_available: str):
    """Equal-length period immediately before [start, end]; None if the data does not cover it."""
    n = n_months(start, end)
    if n == 0:
        return None
    p_start, p_end = shift_months(start, -n), shift_months(start, -1)
    return (p_start, p_end) if month_index(p_start) >= month_index(first_available) else None


def partial_months(date_min: str, date_max: str):
    """Months at the edges of the data that MAY be incomplete (heuristic: first record is not on
    day 1, or last record is before the last day of its month)."""
    out = []
    try:
        dmin = datetime.fromisoformat(str(date_min)[:19])
        dmax = datetime.fromisoformat(str(date_max)[:19])
    except ValueError:
        return out
    if dmin.day > 1:
        out.append(f"{dmin.year:04d}-{dmin.month:02d}")
    if dmax.day < calendar.monthrange(dmax.year, dmax.month)[1]:
        out.append(f"{dmax.year:04d}-{dmax.month:02d}")
    return out


def comparison_windows(date_max: str, first_month: str, months: int = 12):
    """Last N complete months vs the N months before them. None if the data is too short.
    The final month counts as complete only if the data reaches its last day."""
    dmax = datetime.fromisoformat(str(date_max)[:19])
    last = f"{dmax.year:04d}-{dmax.month:02d}"
    if dmax.day < calendar.monthrange(dmax.year, dmax.month)[1]:
        last = shift_months(last, -1)
    last_start, prev_end = shift_months(last, -(months - 1)), shift_months(last, -months)
    prev_start = shift_months(prev_end, -(months - 1))
    if month_index(prev_start) < month_index(first_month):
        return None
    return {"prev": (prev_start, prev_end), "last": (last_start, last)}
