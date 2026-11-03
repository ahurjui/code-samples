"""Kelly criterion fractional position sizing."""

from decimal import Decimal

_ZERO = Decimal(0)
_ONE = Decimal(1)


def kelly_fraction_from_trades(
    *,
    win_count: int,
    loss_count: int,
    avg_win: Decimal,
    avg_loss: Decimal,
) -> Decimal | None:
    """Return the fractional Kelly position size f* ∈ [0, 1], or None for degenerate inputs.

    Formula: f* = W − (1 − W) / R
      where W = win_count / total  (win rate)
            R = avg_win / avg_loss (win/loss ratio)

    Returns None when:
      - total <= 0  (no decided trades)
      - avg_loss <= 0  (degenerate win/loss ratio)

    The result is clamped to [0, 1].  A clamped value of Decimal("0") is returned
    (not None) when the raw f* is negative — the caller (Task 4) decides whether
    to skip trading on a zero fraction.

    Args:
        win_count:  Number of winning trades (>= 0).
        loss_count: Number of losing trades (>= 0).
        avg_win:    Mean per-trade return magnitude for winning trades (>= 0).
        avg_loss:   Mean per-trade return magnitude for losing trades (> 0 for valid).

    Returns:
        Clamped Kelly fraction in [0, 1], or None for degenerate inputs.
    """
    total = win_count + loss_count
    if total <= 0:
        return None
    if avg_loss <= 0:
        return None

    w = Decimal(win_count) / total
    r = avg_win / avg_loss
    if r <= 0:
        return _ZERO
    f = w - (_ONE - w) / r

    return max(_ZERO, min(_ONE, f))
