"""Market-quote observation-age helpers (D10).

One source of truth for judging a quote's freshness, shared by the top-level
freshness service and the quote-comparison block so both report the SAME status.
Staleness is always judged by the provider-reported OBSERVATION time, never the
fetch/replay time.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

QUOTE_STALE_AFTER_DAYS = 7


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_observed_at(s: str) -> datetime | None:
    """Parse a provider-reported observation time to an aware UTC datetime.

    Accepts e.g. 'Sep 3, 2026 9:58 AM ET' or '2026-09-03 09:58:41'. Returns
    None when unparseable (which the caller treats as degraded, never as fetch
    time).
    """
    if not s:
        return None
    s = s.strip()
    match = re.search(r"\s+(ET|PT|CT|MT)\s*$", s)
    zone = match.group(1) if match else None
    if match:
        s = s[:match.start()]
    zones = {
        "ET": "America/New_York", "PT": "America/Los_Angeles",
        "CT": "America/Chicago", "MT": "America/Denver",
    }
    for fmt in ("%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(s, fmt)
            localized = parsed.replace(tzinfo=ZoneInfo(zones[zone])) if zone else parsed.replace(tzinfo=timezone.utc)
            return localized.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def quote_observation_status(observed_at: str) -> dict:
    """Judge a quote's freshness by observation time.

    Returns {"status", "days_ago", "detail", "as_of"} with status one of
    "ok", "stale", or "degraded". An unparseable observation time is degraded
    (not silently replaced by fetch time); a future time is anomalous -> stale.
    """
    obs = parse_observed_at(observed_at)
    if obs is None:
        return {
            "status": "degraded", "days_ago": None,
            "detail": "观察时间无法解析（降级处理）",
            "as_of": str(observed_at or "")[:10] or None,
        }
    now = _now_utc()
    if obs > now:
        return {
            "status": "stale", "days_ago": None,
            "detail": "观察时间在未来（异常）",
            "as_of": obs.isoformat(),
        }
    days = (now - obs).days
    stale = days > QUOTE_STALE_AFTER_DAYS
    return {
        "status": "stale" if stale else "ok",
        "days_ago": days,
        "detail": (
            f"{days} 天前观察（超过 {QUOTE_STALE_AFTER_DAYS} 天视为过期）"
            if stale else f"{days} 天前观察"
        ),
        "as_of": obs.strftime("%Y-%m-%d"),
    }
