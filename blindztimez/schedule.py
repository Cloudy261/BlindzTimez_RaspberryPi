"""Schedule computation: turn Settings into today's open/close minute-of-day.

Supports fixed times, separate weekend times, and sunrise/sunset (with offset).
Unlike the Flipper, the Pi knows its real timezone, so the sun calc uses the
system UTC offset for the given date -- DST is handled automatically.
"""

from __future__ import annotations

import datetime as dt
import math

from blindztimez.store import Settings, TimeSpec


def parse_hhmm(text: str) -> int:
    """Parse 'HH:MM' into minutes-of-day; raise ValueError on anything malformed."""
    parts = text.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {text!r}")
    return hour * 60 + minute


def format_hhmm(minute_of_day: int) -> str:
    """Format a minute-of-day back into 'HH:MM'."""
    minute_of_day %= 1440
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _utc_offset_hours(date: dt.date) -> float:
    """Return the system's local UTC offset (hours) at noon on the given date."""
    local_noon = dt.datetime(date.year, date.month, date.day, 12, 0)
    offset = local_noon.astimezone().utcoffset()
    return offset.total_seconds() / 3600.0 if offset else 0.0


def sun_minute(lat: float, lon: float, date: dt.date, sunrise: bool) -> int | None:
    """Sunrise/sunset in local minutes-of-day (Almanac algorithm). None if no event."""
    d2r = math.pi / 180.0
    r2d = 180.0 / math.pi
    zenith = 90.833
    n = date.timetuple().tm_yday
    lng_hour = lon / 15.0

    t = n + ((6.0 if sunrise else 18.0) - lng_hour) / 24.0
    m = (0.9856 * t) - 3.289
    lsun = m + (1.916 * math.sin(m * d2r)) + (0.020 * math.sin(2.0 * m * d2r)) + 282.634
    lsun %= 360.0

    ra = r2d * math.atan(0.91764 * math.tan(lsun * d2r))
    ra %= 360.0
    ra += (math.floor(lsun / 90.0) * 90.0) - (math.floor(ra / 90.0) * 90.0)
    ra /= 15.0

    sin_dec = 0.39782 * math.sin(lsun * d2r)
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(zenith * d2r) - (sin_dec * math.sin(lat * d2r))) / (
        cos_dec * math.cos(lat * d2r)
    )
    if cos_h > 1.0 or cos_h < -1.0:
        return None  # sun never rises/sets at this latitude/date

    h = (360.0 - r2d * math.acos(cos_h)) if sunrise else (r2d * math.acos(cos_h))
    h /= 15.0
    local_t = h + ra - (0.06571 * t) - 6.622
    ut = (local_t - lng_hour) % 24.0
    local = (ut + _utc_offset_hours(date)) % 24.0
    return int(local * 60.0 + 0.5)


def _edge_minute(spec: TimeSpec, fixed_fallback: str, s: Settings, date: dt.date) -> int:
    """Resolve one edge (open/close) to a minute-of-day for the given date."""
    if spec.source == "fixed":
        return parse_hhmm(fixed_fallback)
    sm = sun_minute(s.latitude, s.longitude, date, spec.source == "sunrise")
    if sm is None:
        return parse_hhmm(fixed_fallback)  # graceful fallback near the poles
    return (sm + spec.offset_min) % 1440


def effective_times(s: Settings, date: dt.date) -> tuple[int, int]:
    """Return (open_minute, close_minute) for the given date, honouring weekend rules."""
    weekend = s.weekend_separate and date.weekday() >= 5  # 5=Sat, 6=Sun
    open_fixed = s.weekend_open_time if weekend else s.open.time
    close_fixed = s.weekend_close_time if weekend else s.close.time
    open_m = _edge_minute(s.open, open_fixed, s, date)
    close_m = _edge_minute(s.close, close_fixed, s, date)
    return open_m, close_m
