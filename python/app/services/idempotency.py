from __future__ import annotations

import hashlib
from datetime import datetime

from app.services.config_service import canonical_json


def deterministic_client_order_id(
    *, strategy_id: str, venue_symbol: str, signal_timestamp: datetime
) -> str:
    """Stable clientOrderId from (strategy, venue_symbol, bar timestamp).

    Network retries and signal replays of the same bar reuse the same id, so
    duplicate orders cannot be created. Length is pinned to 36 chars: "d" (1) +
    first 35 hex chars of the SHA-256 hexdigest. 36 matches the
    orders.client_order_id column width (String(36)) and the venue's max id length.
    signal_timestamp is the closed candle's open_time — the bar the signal fired
    on, stable across retries.
    """
    payload = canonical_json(
        {
            "strategy_id": strategy_id,
            "venue_symbol": venue_symbol,
            "signal_timestamp": signal_timestamp.isoformat(),
        }
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return "d" + digest[:35]
