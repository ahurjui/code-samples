from datetime import datetime, timezone

from app.services.idempotency import deterministic_client_order_id

TS = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


def test_id_is_exactly_36_chars_and_starts_with_d():
    cid = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    assert len(cid) == 36
    assert cid.startswith("d")


def test_id_is_byte_identical_across_runs_with_same_inputs():
    a = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    b = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    assert a == b


def test_id_differs_when_any_input_differs():
    base = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    diff_symbol = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="ETHUSDT", signal_timestamp=TS
    )
    diff_strategy = deterministic_client_order_id(
        strategy_id="rsi", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    diff_ts = deterministic_client_order_id(
        strategy_id="sma_crossover",
        venue_symbol="BTCUSDT",
        signal_timestamp=datetime(2026, 6, 7, 13, 0, tzinfo=timezone.utc),
    )
    assert len({base, diff_symbol, diff_strategy, diff_ts}) == 4


def test_id_is_hex_after_prefix():
    cid = deterministic_client_order_id(
        strategy_id="sma_crossover", venue_symbol="BTCUSDT", signal_timestamp=TS
    )
    int(cid[1:], 16)  # raises ValueError if not hex
