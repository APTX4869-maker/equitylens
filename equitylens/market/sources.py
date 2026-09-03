"""Market source configuration loader (config/market/sources.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from equitylens.config import CONFIG_DIR

DEFAULT_PATH = CONFIG_DIR / "market" / "sources.yaml"


@dataclass(frozen=True)
class ProviderMeta:
    label: str
    endpoint: str
    license_notes: str
    encoding: str = "utf-8"
    timezone: str = ""


@dataclass(frozen=True)
class MarketSourceConfig:
    version: str
    active_providers: tuple[str, ...]
    stale_after_minutes: int
    providers: dict[str, ProviderMeta] = field(default_factory=dict)
    symbols: dict[str, dict[str, str]] = field(default_factory=dict)

    def symbol_for(self, ticker: str, provider: str) -> str:
        per = self.symbols.get(ticker.upper()) or {}
        sym = per.get(provider)
        if not sym:
            raise KeyError(f"no {provider} symbol configured for {ticker}")
        return sym


_config: MarketSourceConfig | None = None


def load_config(path: Path = DEFAULT_PATH) -> MarketSourceConfig:
    raw = yaml.safe_load(Path(path).read_text())
    providers = {
        name: ProviderMeta(
            label=spec.get("label", name),
            endpoint=spec["endpoint"],
            license_notes=spec.get("license_notes", ""),
            encoding=spec.get("encoding", "utf-8"),
            timezone=spec.get("timezone", ""),
        )
        for name, spec in raw.get("providers", {}).items()
    }
    return MarketSourceConfig(
        version=raw.get("version", "market-sources.v1"),
        active_providers=tuple(raw.get("active_providers", [])),
        stale_after_minutes=int(raw.get("stale_after_minutes", 90)),
        providers=providers,
        symbols={k: dict(v) for k, v in raw.get("symbols", {}).items()},
    )


def get_config(path: Path = DEFAULT_PATH) -> MarketSourceConfig:
    """Module-level singleton so hot paths (API reads) do not re-parse YAML."""
    global _config
    if _config is None:
        _config = load_config(path)
    return _config
