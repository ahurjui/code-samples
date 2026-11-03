from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

Money = Decimal
Quantity = Decimal
Price = Decimal


def to_decimal(value: "str | int | Decimal") -> Decimal:
    """Exact Decimal. Floats are rejected — they are not exact for money."""
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise TypeError("bool is not a valid money value")
    if isinstance(value, float):
        raise TypeError("float is not allowed for money/quantity/price; pass str or Decimal")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        return Decimal(str(value))
    raise TypeError(f"unsupported type for to_decimal: {type(value)!r}")


def quantize_to_step(value: Decimal, step: Decimal, *, rounding: str = ROUND_DOWN) -> Decimal:
    """Round value DOWN (default) to a multiple of step (exchange lot/tick size)."""
    if isinstance(value, float) or isinstance(step, float):
        raise TypeError("float is not allowed in quantize_to_step")
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=rounding) * step
