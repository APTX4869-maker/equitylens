"""SEC EDGAR HTTP client.

Responsibilities (only transport):
- identify the application via User-Agent (SEC fair-access policy)
- rate limit well below the SEC 10 req/s cap
- retry with backoff on 429/5xx
- return raw bytes + request metadata (no parsing here)

Never calculates financial metrics.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from equitylens.config import SEC_MAX_RPS, user_agent


class RateLimiter:
    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


class SECClient:
    def __init__(
        self,
        user_agent: str | None = None,
        rps: float = SEC_MAX_RPS,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        self.rate = RateLimiter(rps)
        self.timeout = timeout
        self.max_retries = max_retries
        from equitylens.config import user_agent as default_ua

        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent or default_ua(),
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def get(self, url: str) -> tuple[int, bytes, dict]:
        """Fetch a URL. Returns (status, content, metadata)."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self.rate.wait()
            try:
                response = self._client.get(url)
            except httpx.HTTPError as exc:  # network errors: retry with backoff
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"SEC request failed after retries: {exc}") from exc

            if response.status_code in (429, 500, 502, 503, 504):
                last_error = RuntimeError(f"HTTP {response.status_code} from {url}")
                if attempt < self.max_retries - 1:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after is not None else 0.0
                    except ValueError:
                        delay = 0.0
                    time.sleep(max(2 ** (attempt + 1), delay))
                    continue
            elif response.status_code >= 400:
                response.raise_for_status()

            metadata = {
                "url": url,
                "status": response.status_code,
                "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "content_length": len(response.content),
            }
            return response.status_code, response.content, metadata

        raise RuntimeError(f"SEC request failed: {last_error}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SECClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
