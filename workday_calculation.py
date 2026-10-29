# -*- coding: utf-8 -*-
"""Official and statutory workday counting for inclusive date ranges."""

import json
import logging
import urllib.request
from datetime import date, timedelta
from typing import Optional, Union

_official_cache: dict[int, tuple[set, set]] = {}

DateLike = Union[str, date]

logger = logging.getLogger("prison_calc")


class OfficialDataUnavailable(Exception):
    pass


def _to_date(v: DateLike) -> date:
    return v if isinstance(v, date) else date.fromisoformat(v)


def _dates(begin: date, end: date):
    """Yield every date in the inclusive range."""
    d = begin
    while d <= end:
        yield d
        d += timedelta(days=1)


def _query_official(year: int) -> tuple[set, set]:
    if year in _official_cache:
        return _official_cache[year]
    req = urllib.request.Request(
        f"https://timor.tech/api/holiday/year/{year}",
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.load(r)
    raw = data.get("holiday") or {}
    if not raw:
        raise OfficialDataUnavailable(
            f"timor.tech 尚无 {year} 年的官方放假安排（一般前一年 11 月前后公布）")
    items = [(date.fromisoformat(v["date"]), v["holiday"]) for v in raw.values()]
    result = {d for d, h in items if h}, {d for d, h in items if not h}
    _official_cache[year] = result
    return result


def _statutory_dates(year: int) -> set:
    from lunar_python import Lunar

    def d(sol) -> date:
        return date(int(sol.getYear()), int(sol.getMonth()), int(sol.getDay()))

    lunar = Lunar.fromYmd(year, 1, 1)
    chu1 = d(lunar.getSolar())
    return {
        date(year, 1, 1),
        *[chu1 + timedelta(days=i) for i in (-1, 0, 1, 2)],
        d(lunar.getJieQiTable()["清明"]),
        date(year, 5, 1), date(year, 5, 2),
        d(Lunar.fromYmd(year, 5, 5).getSolar()),
        d(Lunar.fromYmd(year, 8, 15).getSolar()),
        date(year, 10, 1), date(year, 10, 2), date(year, 10, 3),
    }


def _estimated_full_year_workdays(year: int) -> int:
    """Approximate a full year when the calculation crosses an intermediate year."""
    return sum(d.weekday() < 5 for d in _dates(date(year, 1, 1), date(year, 12, 31))) - 13


def _fallback_segment_workdays(seg_begin: date, seg_end: date) -> int:
    hols = _statutory_dates(seg_begin.year)
    return sum(d.weekday() < 5 and d not in hols
               for d in _dates(seg_begin, seg_end))


def _segment_workdays(seg_begin: date, seg_end: date, strict: bool) -> int:
    try:
        off, work = _query_official(seg_begin.year)
    except OfficialDataUnavailable as exc:
        if strict:
            raise
        logger.warning(
            "No official holiday schedule for %s; using statutory estimate (%s)",
            seg_begin.year, exc)
        return _fallback_segment_workdays(seg_begin, seg_end)
    except Exception:
        if strict:
            raise
        logger.warning(
            "Official holiday lookup failed for %s; using statutory estimate",
            seg_begin.year, exc_info=True)
        return _fallback_segment_workdays(seg_begin, seg_end)

    # Count each date once: an official makeup day, or a regular weekday not off.
    return sum(d in work or (d.weekday() < 5 and d not in off)
               for d in _dates(seg_begin, seg_end))


def remaining_workdays(last_day: DateLike, start: Optional[DateLike] = None) -> int:
    """Count workdays from start through last_day, inclusive."""
    end = _to_date(last_day)
    begin = _to_date(start) if start is not None else date.today()

    if begin > end:
        return 0

    this_year = date.today().year

    days = _segment_workdays(
        begin, min(end, date(begin.year, 12, 31)),
        strict=(begin.year == this_year))

    if end.year > begin.year:
        for y in range(begin.year + 1, end.year):
            days += _estimated_full_year_workdays(y)

        days += _segment_workdays(
            date(end.year, 1, 1), end,
            strict=(end.year == this_year))

    return days
