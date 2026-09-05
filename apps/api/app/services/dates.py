"""Relative date resolution.

Relative expressions anchor to the dataset's maximum transaction date, not
today; the resolved window is echoed back to the user.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from ..contracts.plan import DateRange


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, months: int) -> date:
    """Month arithmetic that clamps to the last valid day (31 Jan -1mo -> 31 Dec)."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _quarter_start(year: int, quarter: int) -> date:
    return date(year, 3 * (quarter - 1) + 1, 1)


def _quarter_end(year: int, quarter: int) -> date:
    return _month_end(_quarter_start(year, quarter).replace(month=3 * quarter))


@dataclass(frozen=True)
class DatasetCalendar:
    """The dataset's time bounds; relative expressions resolve against `anchor`."""

    min_date: date
    max_date: date

    @property
    def anchor(self) -> date:
        return self.max_date

    def clamp(self, start: date, end: date) -> tuple[date, date]:
        return (max(start, self.min_date), min(end, self.max_date))


class DateResolutionError(ValueError):
    """An unsupported relative expression; the caller turns this into DATA_UNAVAILABLE."""


def resolve(dr: DateRange, cal: DatasetCalendar, *, clamp: bool = False) -> DateRange:
    """Return a copy of `dr` with the resolved window and label set.

    `clamp` is off by default so a window outside the dataset stays empty and
    is reported as DATA_UNAVAILABLE rather than widened.
    """
    if dr.relative is None:
        start, end = dr.start, dr.end
        assert start is not None and end is not None
        label = _label_for(start, end)
    else:
        start, end, label = _resolve_relative(dr.relative, cal)

    if clamp:
        start, end = cal.clamp(start, end)

    return dr.model_copy(
        update={
            "resolved_start": start,
            "resolved_end": end,
            "resolved_label": label,
        }
    )


def _resolve_relative(expr: str, cal: DatasetCalendar) -> tuple[date, date, str]:
    a = cal.anchor

    if expr == "all_time":
        return cal.min_date, cal.max_date, "all time"

    if expr == "this_month":
        s, e = _month_start(a), _month_end(a)
        return s, e, s.strftime("%B %Y")

    if expr == "last_month":
        prev = _add_months(_month_start(a), -1)
        s, e = _month_start(prev), _month_end(prev)
        return s, e, s.strftime("%B %Y")

    if expr == "month_before_last":
        prev = _add_months(_month_start(a), -2)
        s, e = _month_start(prev), _month_end(prev)
        return s, e, s.strftime("%B %Y")

    if expr == "this_quarter":
        q = _quarter_of(a)
        return _quarter_start(a.year, q), _quarter_end(a.year, q), f"Q{q} {a.year}"

    if expr == "last_quarter":
        q = _quarter_of(a)
        year, q = (a.year - 1, 4) if q == 1 else (a.year, q - 1)
        return _quarter_start(year, q), _quarter_end(year, q), f"Q{q} {year}"

    if expr == "this_year":
        return date(a.year, 1, 1), date(a.year, 12, 31), str(a.year)

    if expr == "last_year":
        y = a.year - 1
        return date(y, 1, 1), date(y, 12, 31), str(y)

    if expr in {"last_7_days", "last_30_days", "last_90_days"}:
        days = int(expr.split("_")[1])
        s = a - timedelta(days=days - 1)
        return s, a, f"last {days} days to {a.isoformat()}"

    if expr in {"last_6_months", "last_12_months"}:
        months = int(expr.split("_")[1])
        s = _month_start(_add_months(_month_start(a), -(months - 1)))
        e = _month_end(a)
        return s, e, f"last {months} months ({s.strftime('%b %Y')} - {e.strftime('%b %Y')})"

    raise DateResolutionError(f"unsupported relative range: {expr!r}")


def _label_for(start: date, end: date) -> str:
    if start == _month_start(start) and end == _month_end(end) and start.month == end.month \
            and start.year == end.year:
        return start.strftime("%B %Y")
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} to {end.isoformat()}"


def preceding_period(dr: DateRange, cal: DatasetCalendar) -> DateRange:
    """The window immediately before a resolved one.

    Whole calendar months shift by one month; other windows by their own length.
    """
    if not dr.is_resolved:
        dr = resolve(dr, cal)
    s, e = dr.resolved_start, dr.resolved_end
    assert s is not None and e is not None

    is_whole_month = s == _month_start(s) and e == _month_end(e) and (s.year, s.month) == (e.year, e.month)
    if is_whole_month:
        prev = _add_months(s, -1)
        ns, ne = _month_start(prev), _month_end(prev)
    else:
        length = (e - s).days + 1
        ne = s - timedelta(days=1)
        ns = ne - timedelta(days=length - 1)

    return DateRange(start=ns, end=ne, resolved_start=ns, resolved_end=ne,
                     resolved_label=_label_for(ns, ne))
