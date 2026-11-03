"""Tests for the pure Kelly-criterion fraction_from_trades helper."""

from decimal import Decimal

import pytest

from app.domain.kelly import kelly_fraction_from_trades


def test_kelly_known_value() -> None:
    """W=0.6, R=2.0 => f* = 0.6 - 0.4/2.0 = 0.6 - 0.2 = 0.4 exactly."""
    result = kelly_fraction_from_trades(
        win_count=6,
        loss_count=4,
        avg_win=Decimal("2"),
        avg_loss=Decimal("1"),
    )
    assert result == Decimal("0.4")


def test_kelly_clamps_to_zero() -> None:
    """W=0.3, R=1.0 => f* = 0.3 - 0.7/1.0 = -0.4, clamped to Decimal("0"), not None."""
    result = kelly_fraction_from_trades(
        win_count=3,
        loss_count=7,
        avg_win=Decimal("1"),
        avg_loss=Decimal("1"),
    )
    assert result == Decimal("0")
    assert result is not None


def test_kelly_none_zero_trades() -> None:
    """win_count=0, loss_count=0 => total=0 => None."""
    result = kelly_fraction_from_trades(
        win_count=0,
        loss_count=0,
        avg_win=Decimal("1"),
        avg_loss=Decimal("1"),
    )
    assert result is None


def test_kelly_none_zero_avg_loss() -> None:
    """avg_loss=0 => degenerate R => None."""
    result = kelly_fraction_from_trades(
        win_count=5,
        loss_count=5,
        avg_win=Decimal("2"),
        avg_loss=Decimal("0"),
    )
    assert result is None


def test_kelly_none_all_flat() -> None:
    """No wins, no losses (all flat closes) => total=0 => None."""
    result = kelly_fraction_from_trades(
        win_count=0,
        loss_count=0,
        avg_win=Decimal("0"),
        avg_loss=Decimal("0"),
    )
    assert result is None


def test_kelly_returns_zero_for_zero_avg_win() -> None:
    """All-losses run: avg_win=0 => r=0 => clamp to Decimal(0), NOT div-by-zero."""
    result = kelly_fraction_from_trades(
        win_count=0,
        loss_count=20,
        avg_win=Decimal("0"),
        avg_loss=Decimal("50"),
    )
    assert result == Decimal("0")
