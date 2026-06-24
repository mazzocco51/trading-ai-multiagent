from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.config import Settings


def parse_asset_classes(asset_classes: list[str]) -> dict[str, str]:
    """Parse asset_classes list (e.g. ["BTC/USDT:crypto", "AAPL:stock"]) into a dict."""
    result: dict[str, str] = {}
    for entry in asset_classes:
        entry = entry.strip()
        if ":" in entry:
            symbol, cls = entry.rsplit(":", 1)
            result[symbol.strip()] = cls.strip()
    return result


class AssetRegistry:
    """Registry mapping symbols to their asset class (crypto or stock)."""

    def __init__(self, settings: Settings) -> None:
        self._map = parse_asset_classes(settings.asset_classes)

    def get_asset_class(self, symbol: str) -> Literal["crypto", "stock"]:
        """Return the asset class for a symbol. Defaults to 'crypto' (backward compatible)."""
        val = self._map.get(symbol, "crypto")
        if val == "stock":
            return "stock"
        return "crypto"
