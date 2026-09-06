"""Market-quote observation-age helpers (D10).

One source of truth for judging a quote's freshness, shared by the top-level
freshness service and the quote-comparison block so both report the SAME status.
Staleness is always judged by the provider-reported OBSERVATION time, never the
fetch/replay time.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

QUOTE_STALE_AFTER_DAYS = 7


def parse_observed_at(s: str) -> datetime | None:
    """Parse a provider-reported observation time to a naive UTC datetime.

    Accepts e.g. 'Sep 3, 2026 9:58 AM ET' or '2026-09-03 09:58:41'. Returns
    None when unparseable (which the caller treats as degraded, never as fetch
    time).
    """
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"\s+(ET|PT|CT|MT)\s*$", "", s)
    for fmt in ("%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
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
    obs = obs.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
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
